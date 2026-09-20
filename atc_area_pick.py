import re
from shapely.geometry import Point
from shapely.prepared import prep
from atc_timeline import parse_iso
from fir_crossings import great_circle_points

ID_RE = r"^\d{1,15}$"

def pick_crossing_flights(flights, airports, geometry, t_on, t_off, limit=30, steps=40, margin_deg=1.5, slack_s=1200):
    if not isinstance(flights, list) or geometry is None or getattr(geometry, "is_empty", False):
        return []
    area = prep(geometry.buffer(margin_deg))
    airports = airports or {}
    seen = set()
    found = []
    for f in flights:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id"))
        if not re.fullmatch(ID_RE, fid) or fid in seen:
            continue
        callsign = f.get("callsign")
        if not isinstance(callsign, str):
            continue
        dep = str(f.get("departure") or "").strip().upper()
        dest = str(f.get("destination") or "").strip().upper()
        a = airports.get(dep)
        b = airports.get(dest)
        if a is None or b is None:
            continue
        t_dep = parse_iso(f.get("departed"))
        t_arr = parse_iso(f.get("arrived"))
        if t_dep is None or t_arr is None or t_arr <= t_dep:
            continue
        pts = great_circle_points((a["lat"], a["lon"]), (b["lat"], b["lon"]), steps)
        inside = [i for i, (lat, lon) in enumerate(pts) if area.intersects(Point(lon, lat))]
        if not inside:
            continue
        span = t_arr - t_dep
        t_first = t_dep + span * inside[0] / steps
        t_last = t_dep + span * inside[-1] / steps
        if t_last + slack_s < t_on or t_first - slack_s > t_off:
            continue
        overlap = max(0.0, min(t_last, t_off) - max(t_first, t_on))
        entry = {
            "id": fid,
            "callsign": callsign.strip().upper(),
            "departure": dep,
            "destination": dest,
            "aircraft": str(f.get("aircraft") or ""),
            "direction": "local",
            "t_dep": t_dep,
            "t_arr": t_arr,
            "t_first": t_first,
            "t_last": t_last,
        }
        seen.add(fid)
        found.append((overlap, entry))
    found.sort(key=lambda x: (-x[0], x[1]["callsign"]))
    limited = [e for _, e in found[:limit]]
    limited.sort(key=lambda e: e["t_first"])
    return limited