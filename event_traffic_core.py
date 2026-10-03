import math
from datetime import datetime, timezone

def parse_ts(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()

def window_for(start_s, end_s):
    return (start_s - 3600, end_s + 2700)

def count_movements(flights, icao, lo, hi):
    result = {"dep": 0, "arr": 0, "hourly": []}
    if not isinstance(flights, list):
        flights = []
    icao = (str(icao) or "").strip().upper()
    n_hours = max(1, math.ceil((hi - lo) / 3600))
    hourly = [0] * n_hours
    dep = 0
    arr = 0
    seen = set()
    for f in flights:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        dep_code = str(f.get("departure") or "").strip().upper()
        dest_code = str(f.get("destination") or "").strip().upper()
        if dep_code == icao:
            t = parse_ts(f.get("departed"))
            if t is not None and lo <= t <= hi and (fid is None or (fid, "d") not in seen):
                if fid is not None:
                    seen.add((fid, "d"))
                dep += 1
                idx = int((t - lo) // 3600)
                if idx < 0:
                    idx = 0
                if idx >= n_hours:
                    idx = n_hours - 1
                hourly[idx] += 1
        if dest_code == icao:
            t = parse_ts(f.get("arrived"))
            if t is not None and lo <= t <= hi and (fid is None or (fid, "a") not in seen):
                if fid is not None:
                    seen.add((fid, "a"))
                arr += 1
                idx = int((t - lo) // 3600)
                if idx < 0:
                    idx = 0
                if idx >= n_hours:
                    idx = n_hours - 1
                hourly[idx] += 1
    result["dep"] = dep
    result["arr"] = arr
    result["hourly"] = hourly
    return result

def baseline_windows(lo, hi, now, settle=10800):
    kept = []
    for shift in (-86400, 86400):
        lo2 = lo + shift
        hi2 = hi + shift
        if hi2 <= now - settle:
            kept.append((lo2, hi2))
    return kept

def average(values):
    if values is None:
        return None
    total = 0.0
    count = 0
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            if isinstance(v, float) and math.isnan(v):
                continue
            total += v
            count += 1
    if count == 0:
        return None
    return round(total / count, 1)

def atc_positions(sessions, icaos, lo, hi, limit=20, keys=None):
    # keys: optional {icao: [extra callsign prefixes]}, because many airports log on under another code (the US ones as MSN_TWR for KMSN)
    if not isinstance(sessions, list):
        return []
    keys = keys if isinstance(keys, dict) else {}
    names = []
    for i in (icaos or []):
        if isinstance(i, str) and i.strip():
            code = i.strip().upper()
            names.append(code)
            names.extend(k.strip().upper() for k in (keys.get(code) or []) if isinstance(k, str) and k.strip())
    prefixes = tuple(n + "_" for n in names)
    if not prefixes:
        return []
    agg = {}
    for s in sessions:
        if not isinstance(s, dict):
            continue
        cs = str(s.get("callsign") or "").strip().upper()
        if not cs.startswith(prefixes):
            continue
        if cs.endswith("_ATIS"):
            continue
        on = parse_ts(s.get("loggedOn"))
        if on is None:
            continue
        off = parse_ts(s.get("loggedOff"))
        if off is None:
            off = hi
        overlap = min(off, hi) - max(on, lo)
        if overlap <= 0:
            continue
        entry = agg.setdefault(cs, {"seconds": 0, "people": set()})
        entry["seconds"] += overlap
        entry["people"].add(str(s.get("vatsimid")))
    result = []
    for cs, data in agg.items():
        minutes = round(data["seconds"] / 60)
        if minutes < 1:
            continue
        result.append({"callsign": cs, "minutes": minutes, "people": len(data["people"])})
    result.sort(key=lambda x: (-x["minutes"], x["callsign"]))
    return result[:limit]

def build_record(airports, flights_by_airport, baseline_by_airport, sessions, lo, hi, now, keys=None):
    if airports is None:
        airports = []
    distinct = []
    seen_air = set()
    for a in airports:
        a_str = str(a).strip().upper()
        if a_str and a_str not in seen_air:
            seen_air.add(a_str)
            distinct.append(a_str)
    flights_by_airport = flights_by_airport or {}
    baseline_by_airport = baseline_by_airport or {}
    airports_out = {}
    hourly_sum = []
    movements_total = 0
    bases = []
    for icao in distinct:
        c = count_movements(flights_by_airport.get(icao), icao, lo, hi)
        base = average(baseline_by_airport.get(icao))
        airports_out[icao] = {"dep": c["dep"], "arr": c["arr"], "base": base}
        movements_total += c["dep"] + c["arr"]
        bases.append(base)
        if not hourly_sum:
            hourly_sum = c["hourly"][:]
        else:
            hourly_sum = [x + y for x, y in zip(hourly_sum, c["hourly"])]
    if not distinct:
        hourly_sum = []
    base_total = None
    if bases and all(b is not None for b in bases):
        base_total = round(sum(bases), 1)
    extra = None
    if base_total is not None:
        extra = round(movements_total - base_total, 1)
    atc = atc_positions(sessions, distinct, lo, hi, keys=keys)
    return {
        "computed": int(now),
        "window": [int(lo), int(hi)],
        "airports": airports_out,
        "movements": movements_total,
        "base": base_total,
        "extra": extra,
        "hourly": hourly_sum,
        "atc": atc,
    }

def ranked_events(records, traffic, limit=10):
    if not isinstance(records, list) or not isinstance(traffic, dict):
        return []
    items = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        key = rec.get("key")
        if key not in traffic:
            continue
        tr = traffic.get(key)
        if not isinstance(tr, dict):
            continue
        mov = tr.get("movements")
        if not isinstance(mov, int):
            continue
        item = {
            "key": key,
            "name": rec.get("name"),
            "start": rec.get("start"),
            "airports": rec.get("airports") if isinstance(rec.get("airports"), list) else [],
            "movements": mov,
            "base": tr.get("base"),
            "extra": tr.get("extra"),
        }
        items.append(item)
    def sort_key(it):
        score = it["extra"] if it["extra"] is not None else it["movements"]
        name = it["name"]
        name_key = (name or "").casefold()
        return (-score, -it["movements"], name_key)
    items.sort(key=sort_key)
    return items[:limit]

def series_traffic(records, traffic, min_count=2, limit=10):
    if not isinstance(records, list) or not isinstance(traffic, dict):
        return []
    valid = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        key = rec.get("key")
        if key not in traffic:
            continue
        tr = traffic.get(key)
        if not isinstance(tr, dict):
            continue
        mov = tr.get("movements")
        if not isinstance(mov, int):
            continue
        valid.append(rec)
    groups = {}
    for rec in valid:
        name_raw = str(rec.get("name") or "")
        norm = " ".join(name_raw.split()).casefold()
        if not norm:
            continue
        groups.setdefault(norm, []).append(rec)
    results = []
    for norm, members in groups.items():
        if len(members) < min_count:
            continue
        earliest_start = None
        chosen_name = None
        mov_vals = []
        extra_vals = []
        atc_counts = []
        for rec in members:
            key = rec.get("key")
            tr = traffic.get(key, {})
            mov_vals.append(tr.get("movements"))
            extra = tr.get("extra")
            if extra is not None:
                extra_vals.append(extra)
            atc = tr.get("atc")
            atc_counts.append(len(atc) if isinstance(atc, list) else 0)
            start = rec.get("start")
            if isinstance(start, str):
                if earliest_start is None or start < earliest_start:
                    earliest_start = start
                    chosen_name = rec.get("name")
        if not mov_vals:
            continue
        avg_mov = round(sum(mov_vals) / len(mov_vals), 1)
        avg_extra = None
        if extra_vals:
            avg_extra = round(sum(extra_vals) / len(extra_vals), 1)
        avg_atc = round(sum(atc_counts) / len(atc_counts), 1) if atc_counts else 0.0
        name_norm = " ".join((chosen_name or "").split())
        results.append({
            "name": name_norm,
            "count": len(members),
            "avg_movements": avg_mov,
            "avg_extra": avg_extra,
            "avg_atc": avg_atc,
        })
    results.sort(key=lambda x: (-x["avg_movements"], (x["name"] or "").casefold()))
    return results[:limit]