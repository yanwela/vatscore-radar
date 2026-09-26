import math
import datetime

COUNT_ONLY = {"position_jump","altitude_jump","frozen","slow_at_altitude","ga_too_fast"}
MERGE_GAP_MIN = 30
KEEP_DAYS = 90

def make_event(a, first_s, last_s):
    k = str(a.get("type"))
    t = int(first_s // 60)
    d = max(1, int((last_s - first_s) // 60))
    cs = str(a.get("callsign") or "")
    cid_raw = a.get("cid")
    cid = int(cid_raw) if isinstance(cid_raw, (int, str)) and str(cid_raw).isdigit() else None
    ac = str(a.get("aircraft") or "")[:8]
    lat = None
    lon = None
    try:
        lat_val = float(a.get("lat"))
        if math.isfinite(lat_val):
            lat = round(lat_val, 1)
    except Exception:
        lat = None
    try:
        lon_val = float(a.get("lon"))
        if math.isfinite(lon_val):
            lon = round(lon_val, 1)
    except Exception:
        lon = None
    return {"k": k, "t": t, "d": d, "cs": cs, "cid": cid, "ac": ac, "lat": lat, "lon": lon}

def who(ev):
    return str(ev["cid"]) if ev.get("cid") is not None else ev.get("cs", "")

def _same_event(e1, e2):
    if e1.get("k") != e2.get("k"):
        return False
    if who(e1) != who(e2):
        return False
    s1, e1_end = e1["t"], e1["t"] + e1["d"]
    s2, e2_end = e2["t"], e2["t"] + e2["d"]
    gap = max(s1, s2) - min(e1_end, e2_end)
    return gap <= MERGE_GAP_MIN

def merge_events(existing, new):
    events = [e for e in (existing or []) + (new or []) if isinstance(e, dict)]
    merged = []
    while events:
        base = events.pop(0)
        i = 0
        while i < len(events):
            if _same_event(base, events[i]):
                other = events.pop(i)
                start = min(base["t"], other["t"])
                end = max(base["t"] + base["d"], other["t"] + other["d"])
                dur = max(1, end - start)
                later = base if (base["t"] + base["d"]) >= (other["t"] + other["d"]) else other
                merged_event = later.copy()
                merged_event["t"] = start
                merged_event["d"] = dur
                base = merged_event
                i = 0
            else:
                i += 1
        merged.append(base)
    merged.sort(key=lambda e: (e["t"], e["k"], who(e)))
    return merged

def count_event(counts, ev):
    ts = ev["t"] * 60
    dt = datetime.datetime.utcfromtimestamp(ts)
    day = dt.date().isoformat()
    hour = f"{dt.hour:02d}"
    if day not in counts:
        counts[day] = {}
    if ev["k"] not in counts[day]:
        counts[day][ev["k"]] = {}
    if hour not in counts[day][ev["k"]]:
        counts[day][ev["k"]][hour] = 0
    counts[day][ev["k"]][hour] += 1
    return counts

def split_events(events):
    detail = [e for e in events if isinstance(e, dict) and e.get("k") not in COUNT_ONLY]
    counted = [e for e in events if isinstance(e, dict) and e.get("k") in COUNT_ONLY]
    return detail, counted

def rollup(events, now_min, keep_days=KEEP_DAYS):
    threshold = now_min - keep_days * 1440
    kept = []
    counts = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev["t"] < threshold:
            count_event(counts, ev)
        else:
            kept.append(ev)
    return kept, counts

def merge_counts(a, b):
    result = {}
    for src in (a, b):
        for day, types in src.items():
            if day not in result:
                result[day] = {}
            for typ, hrs in types.items():
                if typ not in result[day]:
                    result[day][typ] = {}
                for hr, cnt in hrs.items():
                    result[day][typ][hr] = result[day][typ].get(hr, 0) + cnt
    return result

def purge_cid(events, cid):
    cid_str = str(cid)
    if not cid_str.isdigit():
        return list(events)
    target = int(cid_str)
    return [e for e in events if isinstance(e, dict) and e.get("cid") != target]

def summarize(events, counts, now_min, days):
    start_min = now_min - days * 1440
    start_ts = start_min * 60
    start_date = datetime.datetime.utcfromtimestamp(start_ts).date().isoformat()
    detail = [e for e in events if isinstance(e, dict) and e.get("k") not in COUNT_ONLY and e["t"] >= start_min]
    by_type = {}
    by_hour = {}
    for e in detail:
        k = e["k"]
        by_type[k] = by_type.get(k, 0) + 1
        hour = datetime.datetime.utcfromtimestamp(e["t"] * 60).hour
        if k not in by_hour:
            by_hour[k] = [0] * 24
        by_hour[k][hour] += 1
    for day, types in counts.items():
        if day < start_date:
            continue
        for k, hrs in types.items():
            for hr_str, cnt in hrs.items():
                by_type[k] = by_type.get(k, 0) + cnt
                hour = int(hr_str)
                if k not in by_hour:
                    by_hour[k] = [0] * 24
                by_hour[k][hour] += cnt
    recent = sorted(detail, key=lambda e: e["t"], reverse=True)[:20]
    return {"by_type": by_type, "by_hour": by_hour, "recent": recent}