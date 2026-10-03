import re
from collections import defaultdict
from fir_regions import region_prefix

_MAX_KEYS = {"airports": 60, "airlines": 40, "types": 40, "regions": 60}
_ICAO = re.compile(r"^[A-Z0-9]{4}$")
_AIRLINE = re.compile(r"^([A-Z]{3})[0-9]")
_TYPE = re.compile(r"^[A-Z0-9]{2,4}$")
_FIELDS = ("airports", "airlines", "types", "regions")


def sample_counts(pilots, controllers):
    result = {
        "pilots": 0,
        "controllers": 0,
        "airports": defaultdict(int),
        "airlines": defaultdict(int),
        "types": defaultdict(int),
        "regions": defaultdict(int),
    }

    if isinstance(pilots, list):
        for pilot in pilots:
            if not isinstance(pilot, dict):
                continue
            result["pilots"] += 1
            fp = pilot.get("flight_plan")
            if not isinstance(fp, dict):
                fp = {}
            dep = str(fp.get("departure") or "").strip().upper()
            arr = str(fp.get("arrival") or "").strip().upper()
            airports_here = set()
            if _ICAO.fullmatch(dep):
                airports_here.add(dep)
            if _ICAO.fullmatch(arr):
                airports_here.add(arr)
            for icao in airports_here:
                result["airports"][icao] += 1
            regions_here = set()
            for icao in airports_here:
                prefix = region_prefix(icao)
                if prefix:
                    regions_here.add(prefix)
            for prefix in regions_here:
                result["regions"][prefix] += 1
            cs = str(pilot.get("callsign") or "").strip().upper()
            m = _AIRLINE.match(cs)
            if m:
                result["airlines"][m.group(1)] += 1
            t = str(fp.get("aircraft_short") or "").strip().upper()
            if not t:
                t = str(fp.get("aircraft") or "").split("/", 1)[0].strip().upper()
            if _TYPE.fullmatch(t):
                result["types"][t] += 1

    if isinstance(controllers, list):
        for ctrl in controllers:
            if isinstance(ctrl, dict):
                result["controllers"] += 1

    # convert defaultdicts to regular dicts
    for key in ("airports", "airlines", "types", "regions"):
        result[key] = dict(result[key])
    return result


def new_day():
    return {
        "n": 0,
        "pilots": 0,
        "controllers": 0,
        "pilots_max": 0,
        "controllers_max": 0,
        "hours": {},
        "airports": {},
        "airlines": {},
        "types": {},
        "regions": {},
    }


def add_sample(day, sample, hour):
    if not (isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour <= 23):
        return day
    day["n"] += 1
    day["pilots"] += sample.get("pilots", 0)
    day["controllers"] += sample.get("controllers", 0)
    if sample.get("pilots", 0) > day["pilots_max"]:
        day["pilots_max"] = sample["pilots"]
    if sample.get("controllers", 0) > day["controllers_max"]:
        day["controllers_max"] = sample["controllers"]
    hh = f"{hour:02d}"
    h = day["hours"].setdefault(hh, [0, 0, 0])
    h[0] += 1
    h[1] += sample.get("pilots", 0)
    h[2] += sample.get("controllers", 0)
    for field in _FIELDS:
        src = sample.get(field, {})
        if not isinstance(src, dict):
            continue
        dst = day[field]
        for k, v in src.items():
            dst[k] = dst.get(k, 0) + v
    return day


def prune_day(day, max_keys=_MAX_KEYS):
    for field, limit in max_keys.items():
        if field not in day:
            continue
        items = day[field].items()
        sorted_items = sorted(items, key=lambda kv: (-kv[1], kv[0]))
        limited = dict(sorted_items[:limit])
        day[field] = limited
    return day


def merge_days(a, b):
    base = new_day()
    a = a or {}
    b = b or {}
    base["n"] = a.get("n", 0) + b.get("n", 0)
    base["pilots"] = a.get("pilots", 0) + b.get("pilots", 0)
    base["controllers"] = a.get("controllers", 0) + b.get("controllers", 0)
    base["pilots_max"] = max(a.get("pilots_max", 0), b.get("pilots_max", 0))
    base["controllers_max"] = max(a.get("controllers_max", 0), b.get("controllers_max", 0))

    hours_a = a.get("hours", {})
    hours_b = b.get("hours", {})
    all_hh = set(hours_a) | set(hours_b)
    for hh in all_hh:
        ha = hours_a.get(hh, [0, 0, 0])
        hb = hours_b.get(hh, [0, 0, 0])
        base["hours"][hh] = [ha[i] + hb[i] for i in range(3)]

    for field in _FIELDS:
        dict_a = a.get(field, {})
        dict_b = b.get(field, {})
        merged = {}
        for k, v in dict_a.items():
            merged[k] = merged.get(k, 0) + v
        for k, v in dict_b.items():
            merged[k] = merged.get(k, 0) + v
        base[field] = merged
    return base


def day_average(day):
    if not day or day.get("n", 0) == 0:
        return {
            "samples": 0,
            "pilots_avg": 0.0,
            "controllers_avg": 0.0,
            "pilots_max": 0,
            "controllers_max": 0,
            "top": {field: [] for field in _FIELDS},
        }
    n = day["n"]
    pilots_avg = round(day.get("pilots", 0) / n, 1)
    controllers_avg = round(day.get("controllers", 0) / n, 1)
    top = {}
    for field in _FIELDS:
        items = day.get(field, {})
        transformed = [(k, round(v / n, 1)) for k, v in items.items()]
        transformed.sort(key=lambda kv: (-kv[1], kv[0]))
        top[field] = transformed
    return {
        "samples": n,
        "pilots_avg": pilots_avg,
        "controllers_avg": controllers_avg,
        "pilots_max": day.get("pilots_max", 0),
        "controllers_max": day.get("controllers_max", 0),
        "top": top,
    }


def hourly_curve(day):
    if not day or not isinstance(day.get("hours"), dict):
        return []
    result = []
    for hh, vals in day["hours"].items():
        samples, pilots_sum, controllers_sum = vals
        if samples <= 0:
            continue
        hour_int = int(hh)
        pilots_avg = round(pilots_sum / samples, 1)
        controllers_avg = round(controllers_sum / samples, 1)
        result.append((hour_int, pilots_avg, controllers_avg))
    result.sort(key=lambda t: t[0])
    return result