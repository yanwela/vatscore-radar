from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from shapely.ops import unary_union

from atc_area_pick import pick_crossing_flights
from atc_replay_data import _TRACK_PAD_S, _trim
from flight_replay_data import fetch_flight_track
from flight_track import STATSIM_API
from geo_compact import compact_rings

# statsim's date search matches the departure time, so a long flight that left before the session must be searched for too
_LOOKBACK_S = 14 * 3600


def fetch_flights_between(t_from, t_to, api_key, session, timeout=60):
    """Every statsim flight that departed in the window (epoch seconds), network wide; None when statsim.net fails."""
    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {"X-API-Key": api_key, "accept": "application/json", "User-Agent": "VatScore/4.0"}
    try:
        resp = session.get(f"{STATSIM_API}/Flights/Dates", params={"from": iso(t_from), "to": iso(t_to)}, headers=headers, timeout=timeout)
        if resp.status_code == 404:
            return []
        body = resp.json() if resp.status_code == 200 else None
    except Exception:
        return None
    return body if isinstance(body, list) else None


def build_area_replay(sess, api_key, http, fir_index, airports, limit=30, workers=5):
    """Payload for the replay of a CTR / FSS session (`sess` comes from atc_area_sessions.area_sessions); None when statsim.net fails.
    The airspace is the union of the VATSpy boundaries behind the callsign prefix; flights are picked by their planned great-circle route
    and confirmed by their recorded track in the browser."""
    on, off = sess["on"], sess["off"]
    wanted = set(sess["boundaries"])
    shapes = [f["geometry"] for f in fir_index if f["id"] in wanted]
    if not shapes:
        return None
    geometry = unary_union(shapes)
    flights = fetch_flights_between(on - _LOOKBACK_S, off, api_key, http)
    if flights is None:
        return None
    picked = pick_crossing_flights(flights, airports, geometry, on, off, limit)

    def one(entry):
        res = fetch_flight_track(entry["id"], api_key, http, max_points=1200)
        if not res.get("ok"):
            return None
        points = _trim(res["points"], on - _TRACK_PAD_S, off + _TRACK_PAD_S)
        if len(points) < 2:
            return None
        return {"id": entry["id"], "callsign": entry["callsign"], "departure": entry["departure"], "destination": entry["destination"],
                "aircraft": entry["aircraft"], "direction": "local", "points": points}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        tracked = [f for f in pool.map(one, picked) if f]
    centre = geometry.representative_point()
    return {
        "session": {"id": sess["id"], "callsign": sess["callsign"], "role": sess["role"], "kind": "area", "icao": sess["name"], "on": on, "off": off},
        "airport": None,
        "area": {"name": sess["name"], "lat": round(centre.y, 3), "lon": round(centre.x, 3), "rings": compact_rings(geometry, 0.05, 3, 500)},
        "flights": tracked,
        "stats": {"found": len(picked), "tracked": len(tracked), "capped": len(picked) >= limit},
    }
