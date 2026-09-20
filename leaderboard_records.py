import math
import datetime

def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if math.isfinite(v):
            return float(v)
    return None

def _cid(v):
    try:
        i = int(v)
        if i > 0:
            return i
    except Exception:
        pass
    return None

def _entry(p, value, route=""):
    return {
        "callsign": p["callsign"].strip().upper(),
        "name": str(p.get("name") or "").strip(),
        "cid": _cid(p.get("cid")),
        "value": value,
        "route": route,
    }

def _top(items, key, reverse, top):
    sorted_items = sorted(
        items,
        key=lambda x: (x[0] if not reverse else -x[0], x[1]["callsign"])
    )
    return [entry for _, entry in sorted_items[:top]]

def great_circle_nm(lat1, lon1, lat2, lon2):
    r = 3440.065
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return r * c

def flight_records(pilots, airports, top=3):
    if not isinstance(pilots, list):
        pilots = []
    airports = airports or {}
    altitude_items = []
    speed_items = []
    slow_items = []
    route_items = []
    away_items = []
    for p in pilots:
        if not isinstance(p, dict):
            continue
        cs = p.get("callsign")
        if not isinstance(cs, str):
            continue
        entry_base = {"callsign": cs.strip().upper(), "name": str(p.get("name") or "").strip(), "cid": _cid(p.get("cid"))}
        alt = _num(p.get("altitude"))
        if alt is not None:
            entry = dict(entry_base, value=alt, route="")
            altitude_items.append((alt, entry))
        gs = _num(p.get("groundspeed"))
        if gs is not None:
            entry = dict(entry_base, value=gs, route="")
            speed_items.append((gs, entry))
        if alt is not None and alt > 3000 and gs is not None and gs > 45:
            entry = dict(entry_base, value=gs, route="")
            slow_items.append((gs, entry))
        fp = p.get("flight_plan")
        if isinstance(fp, dict):
            dep = str(fp.get("departure") or "").strip().upper()
            arr = str(fp.get("arrival") or "").strip().upper()
            if dep and arr and dep != arr and dep in airports and arr in airports:
                d = round(great_circle_nm(
                    airports[dep]["lat"], airports[dep]["lon"],
                    airports[arr]["lat"], airports[arr]["lon"]
                ))
                route = f"{dep} -> {arr}"
                entry = dict(entry_base, value=d, route=route)
                route_items.append((d, entry))
            if gs is not None and gs >= 50:
                lat = _num(p.get("latitude"))
                lon = _num(p.get("longitude"))
                if lat is not None and lon is not None and dep in airports:
                    d = round(great_circle_nm(
                        lat, lon,
                        airports[dep]["lat"], airports[dep]["lon"]
                    ))
                    arr_display = arr if arr else "----"
                    route = f"{dep} -> {arr_display}"
                    entry = dict(entry_base, value=d, route=route)
                    away_items.append((d, entry))
    return {
        "altitude": _top(altitude_items, None, True, top),
        "speed": _top(speed_items, None, True, top),
        "slow": _top(slow_items, None, False, top),
        "route": _top(route_items, None, True, top),
        "away": _top(away_items, None, True, top),
    }

def member_records(pilots, controllers, now, top=3):
    if not isinstance(pilots, list):
        pilots = []
    if not isinstance(controllers, list):
        controllers = []
    members = pilots + controllers
    session_items = []
    senior_items = []
    newest_items = []
    seen_cids = set()
    for p in members:
        if not isinstance(p, dict):
            continue
        cs = p.get("callsign")
        if not isinstance(cs, str):
            continue
        entry_base = {"callsign": cs.strip().upper(), "name": str(p.get("name") or "").strip(), "cid": _cid(p.get("cid"))}
        # one member is one entry, even if the feed lists the same CID twice (pilot and controller)
        if entry_base["cid"] is not None:
            if entry_base["cid"] in seen_cids:
                continue
            seen_cids.add(entry_base["cid"])
        logon_str = p.get("logon_time")
        if isinstance(logon_str, str):
            iso = logon_str.replace("Z", "+00:00")
            try:
                logon = datetime.datetime.fromisoformat(iso)
                if logon.tzinfo is None:
                    logon = logon.replace(tzinfo=datetime.timezone.utc)
                minutes = int((now - logon).total_seconds() // 60)
                if minutes >= 0:
                    entry = dict(entry_base, value=minutes, route="")
                    session_items.append((minutes, entry))
            except Exception:
                pass
        cid = entry_base["cid"]
        if cid is not None:
            entry = dict(entry_base, value=cid, route="")
            senior_items.append((cid, entry))
            newest_items.append((cid, entry))
    return {
        "session": _top(session_items, None, True, top),
        "senior": _top(senior_items, None, False, top),
        "newest": _top(newest_items, None, True, top),
    }