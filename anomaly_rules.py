import math
from datetime import datetime, timezone

# some clients report their position only every ~2 minutes, so a position can be that much older than the feed: not a teleport
STALE_S = 120

GA_TYPES = {"C150","C152","C162","C170","C172","C182","C185","C206","C207","P28A","P28R","PA28","PA32","PA34","PA46","DA40","DA42","DA62","SR20","SR22","BE33","BE35","BE36","M20P","M20T","TB20","AA5","RV7","RV8"}

def _num(v):
    try:
        f = float(v)
        if math.isfinite(f):
            return int(f)
    except (ValueError, TypeError, OverflowError):
        pass
    return 0

def _extract_aircraft(fp):
    if not isinstance(fp, dict):
        return "N/A"
    raw = fp.get("aircraft_short") or fp.get("aircraft") or ""
    raw = str(raw)
    parts = raw.split("/")
    for part in parts:
        part = part.strip()
        if 3 <= len(part) <= 5 and part.isalnum():
            return part
    return "N/A"

def _haversine_nm(lat1, lon1, lat2, lon2):
    r = 3440.065
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def _pilot_time(value, now_s):
    # the pilot's own last_updated (ISO, UTC) is when that position was really reported; never in the future, never older than 2 minutes
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
        t = t.timestamp()
    except (ValueError, TypeError, OverflowError):
        return now_s
    return min(now_s, max(now_s - 120, t))


def _ground(ground_elevation, lat, lon):
    # elevation (ft) of the ground under the aircraft, from the nearest airport; None when unknown
    if not callable(ground_elevation) or lat is None or lon is None:
        return None
    try:
        value = ground_elevation(lat, lon)
        value = float(value)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def detect_anomalies(pilots, prev, now_s, ground_elevation=None):
    if not isinstance(pilots, list):
        return [], {}
    if not isinstance(prev, dict):
        prev = {}

    parsed = []
    for p in pilots:
        if not isinstance(p, dict):
            continue
        cs = str(p.get("callsign", "")).strip()
        if not cs:
            continue
        cid = str(p.get("cid", "")) if p.get("cid") is not None else ""
        alt = _num(p.get("altitude"))
        gs = _num(p.get("groundspeed"))
        lat = None
        try:
            lat = float(p.get("latitude"))
            if not math.isfinite(lat):
                lat = None
        except (ValueError, TypeError, OverflowError):
            lat = None
        lon = None
        try:
            lon = float(p.get("longitude"))
            if not math.isfinite(lon):
                lon = None
        except (ValueError, TypeError, OverflowError):
            lon = None
        squawk = str(p.get("transponder", "")).strip()
        fp = p.get("flight_plan")
        aircraft = _extract_aircraft(fp)
        parsed.append({"cs": cs, "cid": cid, "alt": alt, "gs": gs, "lat": lat, "lon": lon, "squawk": squawk, "aircraft": aircraft, "t": _pilot_time(p.get("last_updated"), now_s), "elev": _ground(ground_elevation, lat, lon)})

    anomalies = []

    def add(severity, type_, title, details, cs, cid, aircraft, alt, gs, lat, lon):
        anomalies.append({
            "severity": severity,
            "type": type_,
            "title": title,
            "callsign": cs,
            "cid": cid,
            "details": details,
            "aircraft": aircraft,
            "altitude": alt,
            "speed": gs,
            "lat": lat,
            "lon": lon
        })

    for p in parsed:
        cs, cid, alt, gs, lat, lon, squawk, aircraft = p["cs"], p["cid"], p["alt"], p["gs"], p["lat"], p["lon"], p["squawk"], p["aircraft"]
        agl = None if p["elev"] is None else int(alt - p["elev"])
        if squawk == "7700":
            add("high", "squawk_7700", "Emergency squawk (7700)", "Transponder set to 7700 (general emergency)", cs, cid, aircraft, alt, gs, lat, lon)
        elif squawk == "7600":
            add("high", "squawk_7600", "Radio failure squawk (7600)", "Transponder set to 7600 (communication failure)", cs, cid, aircraft, alt, gs, lat, lon)
        elif squawk == "7500":
            add("high", "squawk_7500", "Hijack squawk (7500)", "Transponder set to 7500. On VATSIM this is often a test or a mistake", cs, cid, aircraft, alt, gs, lat, lon)
        if gs > 1150:
            add("high", "impossible_speed", "Implausible ground speed", f"Ground speed {gs} kt is above the 1,150 kt limit", cs, cid, aircraft, alt, gs, lat, lon)
        if alt > 60000 or alt < -2000:
            add("high", "impossible_altitude", "Implausible altitude", f"Altitude {alt:,} ft", cs, cid, aircraft, alt, gs, lat, lon)
        if aircraft in GA_TYPES and gs > 260:
            add("low", "ga_too_fast", "Light aircraft too fast", f"{aircraft} at {gs} kt", cs, cid, aircraft, alt, gs, lat, lon)
        # Height above the nearest airport (AGL), not a fixed MSL number: a parked aircraft at a 12,000 ft airport is on the ground, not "high". Far from every
        # airport (no elevation known) only an altitude no airport can explain counts.
        too_high = agl > 6000 if agl is not None else alt > 20000
        if too_high and (gs == 0 or 0 < gs < 80):
            above = f" ({agl:,} ft above the nearest airport)" if agl is not None else ""
            add("low", "slow_at_altitude", "Very slow at high altitude", f"{gs} kt at {alt:,} ft{above}", cs, cid, aircraft, alt, gs, lat, lon)

    cid_counts = {}
    for p in parsed:
        if p["cid"]:
            cid_counts[p["cid"]] = cid_counts.get(p["cid"], 0) + 1
    for p in parsed:
        if p["cid"] and cid_counts[p["cid"]] > 1:
            n = cid_counts[p["cid"]]
            cs_list = [q["cs"] for q in parsed if q["cid"] == p["cid"]]
            add("low", "duplicate_cid", "Duplicate connection", f"CID {p['cid']} is online {n} times: {', '.join(cs_list)}", p["cs"], p["cid"], p["aircraft"], p["alt"], p["gs"], p["lat"], p["lon"])

    cs_cid_map = {}
    for p in parsed:
        key = p["cs"].lower()
        if key not in cs_cid_map:
            cs_cid_map[key] = set()
        cs_cid_map[key].add(p["cid"])
    for p in parsed:
        key = p["cs"].lower()
        if len(cs_cid_map[key]) > 1:
            n = len(cs_cid_map[key])
            add("low", "shared_callsign", "Callsign in use twice", f"{p['cs']} is used by {n} different pilots", p["cs"], p["cid"], p["aircraft"], p["alt"], p["gs"], p["lat"], p["lon"])

    new_snapshot = {}
    for p in parsed:
        cs, cid, alt, gs, lat, lon, t = p["cs"], p["cid"], p["alt"], p["gs"], p["lat"], p["lon"], p["t"]
        agl = None if p["elev"] is None else int(alt - p["elev"])
        if lat is None or lon is None:
            continue
        key = f"{cid}|{cs}"
        p_prev = prev.get(key)
        still_since = t
        record = None
        if isinstance(p_prev, dict) and isinstance(p_prev.get("t"), (int, float)):
            dt = t - p_prev["t"]
            if dt <= 0:
                record = p_prev
                still_since = p_prev.get("still_since", p_prev["t"])
                t = p_prev["t"]
            elif dt <= 300:
                nm = _haversine_nm(lat, lon, p_prev.get("lat"), p_prev.get("lon"))
                if nm > max(25, 3 + ((dt + STALE_S) / 3600) * 1100):
                    add("medium", "position_jump", "Position jump", f"{nm:.0f} NM in {dt:.0f} s", cs, cid, p["aircraft"], alt, gs, lat, lon)
                if abs(alt - p_prev.get("alt", 0)) > 3000 + ((dt + STALE_S) / 60) * 6000:
                    add("medium", "altitude_jump", "Altitude jump", f"{abs(alt - p_prev.get('alt', 0)):,} ft in {dt:.0f} s", cs, cid, p["aircraft"], alt, gs, lat, lon)
                if nm <= 0.15:
                    still_since = p_prev.get("still_since", t)
        new_snapshot[key] = record if record is not None else {"lat": lat, "lon": lon, "alt": alt, "t": t, "still_since": still_since}
        if gs >= 60 and (agl > 1500 if agl is not None else alt > 3000) and (max(t, now_s) - still_since) >= 300:
            add("medium", "frozen", "Reports speed but not moving", f"{gs} kt reported, position unchanged for {int((max(t, now_s) - still_since) / 60)} min", cs, cid, p["aircraft"], alt, gs, lat, lon)

    sev_order = {"high": 0, "medium": 1, "low": 2}
    anomalies.sort(key=lambda a: (sev_order.get(a["severity"], 3), a["type"], a["callsign"].lower()))
    return anomalies, new_snapshot

def anomaly_key(a):
    return f"{a['type']}|{a['cid']}|{a['callsign']}"