import re
from flight_track import STATSIM_API, compact_positions


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def _clean(f) -> dict:
    return {
        "id": str(f.get("id")),
        "callsign": _s(f.get("callsign")),
        "departure": _s(f.get("departure")),
        "destination": _s(f.get("destination")),
        "aircraft": _s(f.get("aircraft")),
        "route": _s(f.get("route")),
        "departed": _s(f.get("departed")),
        "arrived": _s(f.get("arrived")),
        "loggedOn": _s(f.get("loggedOn")),
    }


_ID_REGEX = re.compile(r"^\d{1,15}$")


def flights_for_callsign(flights, callsign) -> list:
    if not isinstance(callsign, str):
        return []
    target = callsign.strip().upper()
    if not target:
        return []
    cleaned = []
    for item in flights:
        if not isinstance(item, dict):
            continue
        cid = item.get("callsign")
        if not isinstance(cid, str):
            continue
        if cid.strip().upper() != target:
            continue
        fid = str(item.get("id"))
        if not _ID_REGEX.fullmatch(fid):
            continue
        cleaned.append(_clean(item))
    cleaned.sort(
        key=lambda f: (f.get("loggedOn", ""), int(f.get("id", "0"))),
        reverse=True,
    )
    return cleaned


def callsigns_in(flights) -> list:
    latest = {}
    for item in flights:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id"))
        if not _ID_REGEX.fullmatch(fid):
            continue
        cs = item.get("callsign")
        if not isinstance(cs, str):
            continue
        cs_clean = cs.strip().upper()
        if not cs_clean:
            continue
        logged = item.get("loggedOn", "")
        prev = latest.get(cs_clean)
        if prev is None or logged > prev:
            latest[cs_clean] = logged
    cs_list = sorted(latest.keys())
    cs_list.sort(key=lambda cs: latest[cs], reverse=True)
    return cs_list


_MIDDLE_DOT = "\u00B7"
_ARROW = "\u2192"


def flight_label(f) -> str:
    if not isinstance(f, dict):
        return "unknown flight"
    logged = f.get("loggedOn", "")
    if isinstance(logged, str) and len(logged) >= 10:
        date = logged[:10]
    else:
        date = "unknown date"
    dep = f.get("departure", "")
    dep = dep.strip().upper() if isinstance(dep, str) and dep.strip() else "----"
    dest = f.get("destination", "")
    dest = dest.strip().upper() if isinstance(dest, str) and dest.strip() else "----"
    ac = f.get("aircraft", "")
    if isinstance(ac, str) and ac.strip():
        typ = ac.split("/", 1)[0].strip().upper()
        typ = typ if typ else "?"
    else:
        typ = "?"
    return f"{date} {_MIDDLE_DOT} {dep} { _ARROW } {dest} {_MIDDLE_DOT} {typ}"


def fetch_flight_track(flight_id, api_key, session, max_points=1200, timeout=25) -> dict:
    fid_str = str(flight_id)
    if not _ID_REGEX.fullmatch(fid_str):
        return {"ok": False, "reason": "invalid_input"}
    if not isinstance(api_key, str) or not api_key:
        return {"ok": False, "reason": "no_key"}
    url = f"{STATSIM_API}/Flights/Id/{fid_str}"
    headers = {
        "X-API-Key": api_key,
        "accept": "application/json",
        "User-Agent": "VatScore/4.0",
    }
    try:
        resp = session.get(url, headers=headers, timeout=timeout)
    except Exception:
        return {"ok": False, "reason": "network"}
    if resp.status_code == 404:
        return {"ok": False, "reason": "not_found"}
    if resp.status_code != 200:
        return {"ok": False, "reason": f"http_{resp.status_code}"}
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "reason": "network"}
    if not isinstance(body, dict):
        return {"ok": False, "reason": "bad_response"}
    positions = body.get("positions")
    if not isinstance(positions, list):
        return {"ok": False, "reason": "bad_response"}
    points = compact_positions(positions, max_points)
    if not points:
        return {"ok": False, "reason": "no_positions"}
    flight_clean = _clean({**body, "id": body.get("id", flight_id)})
    return {"ok": True, "points": points, "flight": flight_clean}