import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Union

STATSIM_API = "https://api.statsim.net/api"


def _parse_ts(s) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def pick_flight(flights, callsign) -> Optional[dict]:
    if not isinstance(flights, list):
        return None
    matches = [f for f in flights if isinstance(f, dict) and isinstance(f.get("callsign"), str) and f["callsign"].lower() == callsign.lower()]
    if not matches:
        return None
    in_progress = [f for f in matches if f.get("arrived") is None]
    candidates = in_progress if in_progress else matches

    def logged_on_key(f):
        ts = _parse_ts(f.get("loggedOn"))
        if ts is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return ts

    return max(candidates, key=logged_on_key)


def compact_positions(positions, max_points=500) -> list:
    if max_points < 2:
        max_points = 2
    valid = []
    for p in positions:
        if not isinstance(p, dict):
            continue
        ts = _parse_ts(p.get("time"))
        if ts is None:
            continue
        lat = p.get("latitude")
        lon = p.get("longitude")
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180):
            continue
        alt = p.get("altitude")
        try:
            alt_i = int(float(alt))
        except (TypeError, ValueError, OverflowError):
            alt_i = 0
        try:
            spd_i = int(float(p.get("speed")))
        except (TypeError, ValueError, OverflowError):
            spd_i = 0
        valid.append((ts, lat_f, lon_f, alt_i, spd_i))

    valid.sort(key=lambda x: x[0])
    rows = [[round(lat, 4), round(lon, 4), alt, int(ts.timestamp()), spd] for ts, lat, lon, alt, spd in valid]

    if len(rows) > max_points:
        n = len(rows)
        stride = n / max_points
        indices = [int(i * stride) for i in range(max_points)]
        indices[-1] = n - 1
        indices = sorted(set(indices))
        rows = [rows[i] for i in indices]
    return rows


def fetch_track(cid, callsign, api_key, session, now=None, timeout=25) -> dict:
    if not isinstance(cid, (str, int)) or isinstance(cid, bool):
        return {"ok": False, "reason": "invalid_input"}
    cid_str = str(cid)
    if not re.fullmatch(r"\d{1,10}", cid_str):
        return {"ok": False, "reason": "invalid_input"}

    if not isinstance(callsign, str):
        return {"ok": False, "reason": "invalid_input"}
    callsign = callsign.upper()
    if not re.fullmatch(r"^[A-Z0-9_-]{1,12}$", callsign):
        return {"ok": False, "reason": "invalid_input"}

    if not api_key:
        return {"ok": False, "reason": "no_key"}

    if now is None:
        now = datetime.now(timezone.utc)

    headers = {"X-API-Key": api_key, "accept": "application/json", "User-Agent": "VatScore/4.0"}

    try:
        resp = session.get(
            STATSIM_API + "/Flights/VatsimId",
            params={
                "vatsimId": cid_str,
                "from": (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code == 404:
            return {"ok": False, "reason": "not_found"}
        if resp.status_code != 200:
            return {"ok": False, "reason": f"http_{resp.status_code}"}
        body = resp.json()
        if not isinstance(body, list):
            return {"ok": False, "reason": "bad_response"}
        flight = pick_flight(body, callsign)
        if flight is None:
            return {"ok": False, "reason": "not_found"}
    except Exception:
        return {"ok": False, "reason": "network"}

    flight_id = str(flight.get("id", ""))
    if not re.fullmatch(r"\d{1,15}", flight_id):
        return {"ok": False, "reason": "bad_response"}

    try:
        resp2 = session.get(
            STATSIM_API + "/Flights/Id/" + flight_id,
            headers=headers,
            timeout=timeout,
        )
        if resp2.status_code == 404:
            return {"ok": False, "reason": "not_found"}
        if resp2.status_code != 200:
            return {"ok": False, "reason": f"http_{resp2.status_code}"}
        body2 = resp2.json()
        if not isinstance(body2, dict) or not isinstance(body2.get("positions"), list):
            return {"ok": False, "reason": "bad_response"}
        points = compact_positions(body2["positions"])
        if not points:
            return {"ok": False, "reason": "no_positions"}
        return {
            "ok": True,
            "points": points,
            "flight_id": flight["id"],
            "departure": flight.get("departure"),
            "destination": flight.get("destination"),
            "in_progress": flight.get("arrived") is None,
        }
    except Exception:
        return {"ok": False, "reason": "network"}