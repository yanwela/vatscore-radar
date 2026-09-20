from atc_timeline import parse_iso
import datetime

ROLES = ("DEL", "GND", "TWR", "APP", "DEP")
MIN_SECONDS = 300

def replay_sessions(sessions, airport_keys, airports, limit=40):
    if not isinstance(sessions, list):
        return []
    airport_keys = airport_keys or {}
    airports = airports or {}
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
        if role not in ROLES:
            continue
        prefix = parts[0]
        candidates = []
        if len(prefix) == 4:
            candidates.append(prefix)
        candidates += list(airport_keys.get(prefix, []))
        icao = None
        for cand in candidates:
            if cand in airports:
                icao = cand
                break
        if not icao:
            continue
        on = parse_iso(s.get("loggedOn"))
        off = parse_iso(s.get("loggedOff"))
        if on is None or off is None or (off - on) < MIN_SECONDS:
            continue
        info = airports[icao]
        label_date = datetime.datetime.utcfromtimestamp(on).strftime("%Y-%m-%d")
        label_on = datetime.datetime.utcfromtimestamp(on).strftime("%H:%M")
        label_off = datetime.datetime.utcfromtimestamp(off).strftime("%H:%M")
        label = f"{label_date} · {callsign} · {label_on}-{label_off}Z · {icao}"
        entry = {
            "id": str(s.get("id")),
            "callsign": callsign,
            "role": "APP" if role == "DEP" else role,
            "icao": icao,
            "name": info.get("name", ""),
            "lat": info.get("lat"),
            "lon": info.get("lon"),
            "elevation": info.get("elevation") or 0,
            "on": on,
            "off": off,
            "label": label,
        }
        entries.append(entry)
    entries.sort(key=lambda x: x["on"], reverse=True)
    return entries[:limit]