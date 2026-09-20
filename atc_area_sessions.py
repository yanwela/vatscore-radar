import datetime
from atc_timeline import parse_iso

AREA_ROLES = ("CTR", "FSS")
MIN_SECONDS = 300

def area_sessions(sessions, prefix_boundaries, names, limit=40):
    if not isinstance(sessions, list):
        return []
    prefix_boundaries = prefix_boundaries or {}
    names = names or {}
    entries = []
    for s in sessions:
        if not isinstance(s, dict):
            continue
        callsign = s.get("callsign")
        if not isinstance(callsign, str):
            continue
        callsign = callsign.strip().upper()
        parts = callsign.split("_")
        if len(parts) < 2:
            continue
        role = parts[-1]
        if role not in AREA_ROLES:
            continue
        # the longest known prefix wins: ANK_18_CTR is sector 18 ("ANK_18"), not the whole "ANK"; LON_SC_CTR falls back to "LON"
        prefix, ids = parts[0], []
        for length in range(len(parts) - 1, 0, -1):
            candidate = "_".join(parts[:length])
            found = sorted(str(i) for i in prefix_boundaries.get(candidate, []))
            if found:
                prefix, ids = candidate, found
                break
        if not ids:
            continue
        on = parse_iso(s.get("loggedOn"))
        off = parse_iso(s.get("loggedOff"))
        if on is None or off is None or off - on < MIN_SECONDS:
            continue
        place_candidate = names.get(prefix) or names.get(ids[0])
        if isinstance(place_candidate, str) and place_candidate.strip():
            place = place_candidate
        else:
            place = prefix
        on_dt = datetime.datetime.utcfromtimestamp(on)
        off_dt = datetime.datetime.utcfromtimestamp(off)
        label = f"{on_dt:%Y-%m-%d} · {callsign} · {on_dt:%H:%M}-{off_dt:%H:%M}Z · {place}"
        entry = {
            "id": str(s.get("id")),
            "callsign": callsign,
            "role": role,
            "kind": "area",
            "prefix": prefix,
            "boundaries": ids,
            "name": place,
            "on": on,
            "off": off,
            "label": label,
        }
        entries.append(entry)
    entries.sort(key=lambda x: x["on"], reverse=True)
    return entries[:limit]