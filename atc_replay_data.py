from concurrent.futures import ThreadPoolExecutor

from atc_flight_pick import pick_flights
from flight_replay_data import fetch_flight_track
from flight_track import STATSIM_API

_TRACK_PAD_S = 3600  # tracks are cut to the session window plus an hour on each side, which is enough for the lead-in and tail
_MAX_TRACK_POINTS = 500


def fetch_airport_flights(icao, t_from, t_to, api_key, session, timeout=25):
    """Every statsim flight that departed from or arrived at `icao` in the window (epoch seconds); None when statsim.net fails."""
    from datetime import datetime, timezone

    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {"X-API-Key": api_key, "accept": "application/json", "User-Agent": "VatScore/4.0"}
    try:
        resp = session.get(f"{STATSIM_API}/Flights/Icao", params={"icao": icao, "from": iso(t_from), "to": iso(t_to)}, headers=headers, timeout=timeout)
        if resp.status_code == 404:
            return []  # statsim answers 404 when nothing matches
        body = resp.json() if resp.status_code == 200 else None
    except Exception:
        return None
    return body if isinstance(body, list) else None


def _trim(points, lo, hi):
    kept = [p for p in points if lo <= p[3] <= hi]
    if len(kept) > _MAX_TRACK_POINTS:
        step = -(-len(kept) // _MAX_TRACK_POINTS)
        kept = kept[::step] + kept[-1:]
    return kept


def build_atc_replay(sess, api_key, http, limit=30, workers=5):
    """Payload for the ATC replay of one airport controller session (`sess` comes from atc_sessions.replay_sessions); None when statsim.net fails."""
    on, off = sess["on"], sess["off"]
    flights = fetch_airport_flights(sess["icao"], on - _TRACK_PAD_S, off + _TRACK_PAD_S, api_key, http)
    if flights is None:
        return None
    picked = pick_flights(flights, sess["icao"], sess["role"], on, off, limit)

    def one(entry):
        res = fetch_flight_track(entry["id"], api_key, http, max_points=1200)
        if not res.get("ok"):
            return None
        points = _trim(res["points"], on - _TRACK_PAD_S, off + _TRACK_PAD_S)
        if len(points) < 2:
            return None
        return {"id": entry["id"], "callsign": entry["callsign"], "departure": entry["departure"], "destination": entry["destination"],
                "aircraft": entry["aircraft"], "direction": entry["direction"], "points": points}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        tracked = [f for f in pool.map(one, picked) if f]
    return {
        "session": {"id": sess["id"], "callsign": sess["callsign"], "role": sess["role"], "icao": sess["icao"], "on": on, "off": off},
        "airport": {"icao": sess["icao"], "name": sess["name"], "lat": sess["lat"], "lon": sess["lon"], "elevation": sess["elevation"]},
        "flights": tracked,
        "stats": {"found": len(picked), "tracked": len(tracked)},
    }
