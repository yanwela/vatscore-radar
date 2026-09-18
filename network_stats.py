import math
import re
from datetime import datetime, timezone

ON_GROUND_MAX_GS = 50
ON_GROUND_MAX_AGL_FT = 300
AIRPORT_RADIUS_NM = 10
TERMINAL_RADIUS_NM = 60

ATC_RATINGS = {
    -1: "Inactive",
    0: "Suspended",
    1: "OBS",
    2: "S1",
    3: "S2",
    4: "S3",
    5: "C1",
    6: "C2",
    7: "C3",
    8: "I1",
    9: "I2",
    10: "I3",
    11: "SUP",
    12: "ADM"
}

ATC_POSITION_ORDER = ("DEL", "GND", "TWR", "APP")

FACILITIES = {
    0: "OBS",
    1: "FSS",
    2: "DEL",
    3: "GND",
    4: "TWR",
    5: "APP",
    6: "CTR"
}

def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def parse_logon(ts):
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def _flight_plan(pilot):
    return pilot.get("flight_plan") or {}

def _code(value):
    return str(value or "").strip().upper()

def _route(pilot):
    fp = _flight_plan(pilot)
    return _code(fp.get("departure")), _code(fp.get("arrival"))

def _aircraft_type(pilot):
    fp = _flight_plan(pilot)
    short = _code(fp.get("aircraft_short"))
    if short:
        return short
    return _code(str(fp.get("aircraft") or "").split("/")[0])

def _airport_code(callsign, airports):
    base = _code(str(callsign or "").split("_")[0])
    if len(base) == 3 and ("K" + base) in airports:
        return "K" + base
    return base

def online_minutes(logon_time, now=None):
    dt = parse_logon(logon_time)
    if dt is None:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)
    diff = now - dt
    if diff.total_seconds() < 0:
        return 0
    return int(diff.total_seconds() // 60)

def format_online(minutes):
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins:02d}m"

def pilot_status(pilot, airports):
    dep, arr = _route(pilot)
    if not dep and not arr:
        return "No FPL"
    dep_info = airports.get(dep)
    arr_info = airports.get(arr)
    if not dep_info or not arr_info:
        return "Unknown"
    lat = pilot.get("latitude") or 0.0
    lon = pilot.get("longitude") or 0.0
    alt = pilot.get("altitude") or 0
    gs = pilot.get("groundspeed") or 0
    dist_dep = haversine_nm(lat, lon, dep_info.get("lat") or 0.0, dep_info.get("lon") or 0.0)
    dist_arr = haversine_nm(lat, lon, arr_info.get("lat") or 0.0, arr_info.get("lon") or 0.0)
    closer_is_dep = dist_dep <= dist_arr
    ref_elev = (dep_info if closer_is_dep else arr_info).get("elevation") or 0
    on_ground = gs < ON_GROUND_MAX_GS and (alt - ref_elev) < ON_GROUND_MAX_AGL_FT
    if on_ground:
        if closer_is_dep and dist_dep <= AIRPORT_RADIUS_NM:
            return "Departing"
        if not closer_is_dep and dist_arr <= AIRPORT_RADIUS_NM:
            return "Landed"
        return "On ground"
    if closer_is_dep and dist_dep <= TERMINAL_RADIUS_NM:
        return "Departed"
    if not closer_is_dep and dist_arr <= TERMINAL_RADIUS_NM:
        return "Arriving"
    return "Enroute"

def pilot_rows(pilots, airports, now=None):
    rows = []
    for p in pilots:
        dep, arr = _route(p)
        online_min = online_minutes(p.get("logon_time"), now)
        rows.append({
            "cid": p.get("cid", ""),
            "callsign": p.get("callsign", ""),
            "name": p.get("name", ""),
            "status": pilot_status(p, airports),
            "aircraft": _aircraft_type(p),
            "departure": dep,
            "arrival": arr,
            "online_min": online_min,
            "online": format_online(online_min),
            "altitude": p.get("altitude", 0),
            "groundspeed": p.get("groundspeed", 0),
        })
    rows.sort(key=lambda x: x["online_min"], reverse=True)
    return rows

def airport_stats(pilots, controllers, atis, airports):
    counts = {}
    for p in pilots:
        dep, arr = _route(p)
        status = pilot_status(p, airports)
        if status in ("Departing", "Departed"):
            icao = dep
        elif status in ("Arriving", "Landed"):
            icao = arr
        else:
            continue
        row = counts.setdefault(icao, {"departing": 0, "departed": 0, "arriving": 0, "landed": 0})
        row[status.lower()] += 1
    positions = {}
    for c in controllers:
        parts = str(c.get("callsign") or "").upper().split("_")
        pos = "APP" if parts[-1] == "DEP" else parts[-1]
        icao = _airport_code(c.get("callsign"), airports)
        if len(parts) > 1 and pos in ATC_POSITION_ORDER and icao in airports:
            positions.setdefault(icao, set()).add(pos)
    atis_airports = set()
    for a in atis:
        icao = _airport_code(a.get("callsign"), airports)
        if icao in airports:
            atis_airports.add(icao)
    rows = []
    for icao in set(counts) | set(positions) | atis_airports:
        info = airports.get(icao) or {}
        c = counts.get(icao, {})
        departing = c.get("departing", 0)
        departed = c.get("departed", 0)
        arriving = c.get("arriving", 0)
        landed = c.get("landed", 0)
        rows.append({
            "icao": icao,
            "name": info.get("name", ""),
            "city": info.get("city", ""),
            "country": info.get("country", ""),
            "departing": departing,
            "departed": departed,
            "arriving": arriving,
            "landed": landed,
            "total": departing + departed + arriving + landed,
            "atc": " ".join(p for p in ATC_POSITION_ORDER if p in positions.get(icao, ())),
            "atis": icao in atis_airports,
        })
    rows.sort(key=lambda x: (-x["total"], x["icao"]))
    return rows

def airline_stats(pilots, airlines):
    counts = {}
    for p in pilots:
        callsign = p.get("callsign", "")
        if not callsign:
            continue
        cs_up = callsign.strip().upper()
        m = re.match(r'^[A-Z]+', cs_up)
        if m:
            code = m.group(0)
            if len(code) == 3 and code in airlines:
                counts[code] = counts.get(code, 0) + 1
    rows = []
    for icao, cnt in counts.items():
        info = airlines.get(icao, {})
        rows.append({
            "icao": icao,
            "pilots": cnt,
            "callsign": info.get("callsign", ""),
            "name": info.get("name", ""),
            "virtual": bool(info.get("virtual", False))
        })
    rows.sort(key=lambda x: (-x["pilots"], x["icao"]))
    return rows

def aircraft_stats(pilots):
    counts = {}
    for p in pilots:
        aircraft = _aircraft_type(p)
        if aircraft:
            counts[aircraft] = counts.get(aircraft, 0) + 1
    total = sum(counts.values())
    rows = [
        {"aircraft": ac, "pilots": n, "share_pct": round(100 * n / total, 1)}
        for ac, n in counts.items()
    ]
    rows.sort(key=lambda x: (-x["pilots"], x["aircraft"]))
    return rows

def route_stats(pilots):
    counts = {}
    for p in pilots:
        dep, arr = _route(p)
        if dep and arr:
            counts[(dep, arr)] = counts.get((dep, arr), 0) + 1
    rows = [{"from": d, "to": a, "aircraft": n} for (d, a), n in counts.items()]
    rows.sort(key=lambda x: (-x["aircraft"], x["from"], x["to"]))
    return rows

def atc_rows(controllers, now=None):
    rows = []
    for c in controllers:
        facility = c.get("facility", 0)
        if facility == 0:
            continue
        cid = c.get("cid", "")
        callsign = c.get("callsign", "")
        frequency = c.get("frequency", "")
        rating_raw = c.get("rating")
        rating_label = ATC_RATINGS.get(rating_raw)
        if rating_label is None:
            rating_label = f"R{rating_raw}" if rating_raw is not None else "RNone"
        facility_label = FACILITIES.get(facility, "")
        name = c.get("name", "")
        online_min = online_minutes(c.get("logon_time"), now)
        online = format_online(online_min)
        rows.append({
            "cid": cid,
            "callsign": callsign,
            "frequency": frequency,
            "rating": rating_label,
            "facility": facility_label,
            "name": name,
            "online_min": online_min,
            "online": online
        })
    rows.sort(key=lambda x: x["online_min"], reverse=True)
    return rows

def airport_detail(icao, pilots, controllers, atis, airports, now=None):
    icao = _code(icao)
    info = airports.get(icao)
    if info is None:
        return None

    # Helper to compute distance to airport
    def _distance(pilot):
        lat = pilot.get("latitude") or 0.0
        lon = pilot.get("longitude") or 0.0
        return int(round(haversine_nm(lat, lon, info.get("lat") or 0.0, info.get("lon") or 0.0)))

    # Build pilot rows
    departures = []
    arrivals = []
    for p in pilots:
        dep, arr = _route(p)
        status = pilot_status(p, airports)
        distance_nm = _distance(p)
        row = {
            "cid": p.get("cid", ""),
            "callsign": p.get("callsign", ""),
            "name": p.get("name", ""),
            "aircraft": _aircraft_type(p),
            "origin": dep,
            "destination": arr,
            "status": status,
            "altitude": p.get("altitude", 0),
            "groundspeed": p.get("groundspeed", 0),
            "distance_nm": distance_nm,
        }
        if dep == icao and status in ("Departing", "Departed"):
            departures.append(row)
        if arr == icao and status in ("Arriving", "Landed"):
            arrivals.append(row)

    departures.sort(key=lambda x: (0 if x["status"] == "Departing" else 1, x["distance_nm"], x["callsign"]))
    arrivals.sort(key=lambda x: (0 if x["status"] == "Arriving" else 1, x["distance_nm"], x["callsign"]))

    # Build ATC rows
    atc_rows = []
    for c in controllers:
        callsign = str(c.get("callsign") or "")
        if "_" not in callsign:
            continue
        if _airport_code(callsign, airports) != icao:
            continue
        parts = callsign.upper().split("_")
        pos_raw = parts[-1]
        position = "APP" if pos_raw == "DEP" else pos_raw
        if position not in ATC_POSITION_ORDER:
            continue
        rating_raw = c.get("rating")
        rating_label = ATC_RATINGS.get(rating_raw)
        if rating_label is None:
            rating_label = f"R{rating_raw}" if rating_raw is not None else "RNone"
        online_min = online_minutes(c.get("logon_time"), now)
        atc_rows.append({
            "callsign": callsign,
            "position": position,
            "frequency": c.get("frequency", ""),
            "rating": rating_label,
            "name": c.get("name", ""),
            "online_min": online_min,
            "online": format_online(online_min),
        })
    atc_rows.sort(key=lambda x: (ATC_POSITION_ORDER.index(x["position"]), x["callsign"]))

    # Build ATIS rows
    atis_rows = []
    for a in atis:
        if _airport_code(a.get("callsign"), airports) != icao:
            continue
        text_val = a.get("text_atis")
        if isinstance(text_val, list):
            text = " ".join(str(x) for x in text_val)
        elif isinstance(text_val, str):
            text = text_val
        else:
            text = ""
        atis_rows.append({
            "callsign": a.get("callsign", ""),
            "frequency": a.get("frequency", ""),
            "code": a.get("atis_code", "") or "",
            "text": text,
        })
    atis_rows.sort(key=lambda x: x["callsign"])

    # Counts
    counts = {
        "departing": sum(1 for r in departures if r["status"] == "Departing"),
        "departed": sum(1 for r in departures if r["status"] == "Departed"),
        "arriving": sum(1 for r in arrivals if r["status"] == "Arriving"),
        "landed": sum(1 for r in arrivals if r["status"] == "Landed"),
    }

    return {
        "icao": icao,
        "name": info.get("name", ""),
        "city": info.get("city", ""),
        "country": info.get("country", ""),
        "elevation": info.get("elevation", 0),
        "tz": info.get("tz", ""),
        "lat": info.get("lat", 0.0),
        "lon": info.get("lon", 0.0),
        "counts": counts,
        "departures": departures,
        "arrivals": arrivals,
        "atc": atc_rows,
        "atis": atis_rows,
    }


def observer_rows(controllers, now=None):
    rows = []
    for c in controllers:
        facility = c.get("facility", 0)
        if facility != 0:
            continue
        cid = c.get("cid", "")
        callsign = c.get("callsign", "")
        name = c.get("name", "")
        rating_raw = c.get("rating")
        rating_label = ATC_RATINGS.get(rating_raw)
        if rating_label is None:
            rating_label = f"R{rating_raw}" if rating_raw is not None else "RNone"
        online_min = online_minutes(c.get("logon_time"), now)
        online = format_online(online_min)
        rows.append({
            "cid": cid,
            "callsign": callsign,
            "name": name,
            "rating": rating_label,
            "online_min": online_min,
            "online": online
        })
    rows.sort(key=lambda x: x["online_min"], reverse=True)
    return rows