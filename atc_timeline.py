import datetime

ROLE_RANK = {"DEL": 0, "GND": 1, "TWR": 2, "APP": 3, "DEP": 4, "ATIS": 5, "CTR": 6, "FSS": 7}
KIND_RANK = {"dep": 0, "fir": 1, "arr": 2}
MAX_ENTRIES = 60

def parse_iso(text):
    if not isinstance(text, str) or not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()

def build_atc_timeline(sessions, dep, arr, airport_keys, fir_keys, t_from, t_to):
    dep = (dep or "").strip().upper()
    arr = (arr or "").strip().upper()
    fir_set = set(fir_keys or [])
    airport_keys = airport_keys or {}
    if not isinstance(sessions, list):
        return []
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
        prefix = parts[0]
        role = parts[-1]
        if role not in ROLE_RANK:
            continue
        on = parse_iso(s.get("loggedOn"))
        if on is None:
            continue
        off = parse_iso(s.get("loggedOff"))
        if off is None:
            off = t_to
        if role in ("CTR", "FSS"):
            if prefix not in fir_set:
                continue
            place = prefix
            kind = "fir"
        else:
            icaos = set(airport_keys.get(prefix, []))
            if len(prefix) == 4:
                icaos.add(prefix)
            if dep and dep in icaos:
                place = dep
                kind = "dep"
            elif arr and arr in icaos:
                place = arr
                kind = "arr"
            else:
                continue
        on = max(on, t_from)
        off = min(off, t_to)
        if off <= on:
            continue
        entry = {"callsign": callsign, "place": place, "kind": kind, "role": role, "on": on, "off": off}
        entries.append(entry)
    entries.sort(key=lambda e: (KIND_RANK[e["kind"]], e["place"], ROLE_RANK[e["role"]], e["callsign"], e["on"]))
    return entries[:MAX_ENTRIES]