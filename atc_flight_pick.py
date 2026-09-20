import re
from atc_timeline import parse_iso

WINDOWS = {
    "DEL": {"out": (2700, 0), "in": None},
    "GND": {"out": (2700, 0), "in": (300, 1200)},
    "TWR": {"out": (600, 600), "in": (900, 300)},
    "APP": {"out": (0, 1800), "in": (2700, 0)},
}
ID_RE = r"^\d{1,15}$"


def pick_flights(flights, icao, role, t_on, t_off, limit=30):
    icao = str(icao or "").strip().upper()
    if role not in WINDOWS or not isinstance(flights, list):
        return []
    mid = (t_on + t_off) / 2
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
        is_out = dep == icao
        is_in = dest == icao
        if not (is_out or is_in):
            continue
        t_dep = parse_iso(f.get("departed"))
        t_arr = parse_iso(f.get("arrived"))
        refs = []
        if is_out and WINDOWS[role]["out"] and t_dep is not None:
            before, after = WINDOWS[role]["out"]
            if t_dep - before < t_off and t_dep + after > t_on:
                refs.append(t_dep)
        if is_in and WINDOWS[role]["in"] and t_arr is not None:
            before, after = WINDOWS[role]["in"]
            if t_arr - before < t_off and t_arr + after > t_on:
                refs.append(t_arr)
        if not refs:
            continue
        direction = "local" if is_out and is_in else ("out" if is_out else "in")
        entry = {
            "id": fid,
            "callsign": callsign.strip().upper(),
            "departure": dep,
            "destination": dest,
            "aircraft": str(f.get("aircraft") or ""),
            "direction": direction,
            "t_dep": t_dep,
            "t_arr": t_arr,
        }
        rank = (
            0 if any(t_on <= r <= t_off for r in refs) else 1,
            min(abs(r - mid) for r in refs),
        )
        seen.add(fid)
        found.append((rank, entry))
    found.sort(key=lambda x: x[0])
    limited = [e for _, e in found[:limit]]
    limited.sort(key=lambda e: e["t_dep"] if e["t_dep"] is not None else e["t_arr"])
    return limited