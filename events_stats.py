import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _parse(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, _FMT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _times(rec):
    if not isinstance(rec, dict):
        return None
    start = _parse(rec.get("start"))
    end = _parse(rec.get("end"))
    if start is None or end is None:
        return None
    if end < start:
        return None
    return (start, end)


def classify(rec, now):
    t = _times(rec)
    if t is None:
        return None
    start, end = t
    if rec.get("withdrawn"):
        return "withdrawn"
    if end < now:
        return "held"
    if start <= now:
        return "live"
    return "scheduled"


def summarize(records, now):
    if records is None:
        records = []
    counts = {"recorded": 0, "held": 0, "live": 0, "scheduled": 0, "withdrawn": 0, "invalid": 0}
    since = None
    durations = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        cls = classify(rec, now)
        if cls is None:
            counts["invalid"] += 1
        else:
            counts["recorded"] += 1
            counts[cls] += 1
            if cls != "withdrawn":
                t = _times(rec)
                if t is not None:
                    start, end = t
                    durations.append((end - start).total_seconds() / 3600)
        fs = rec.get("first_seen")
        if fs is not None:
            parsed_fs = _parse(fs)
            if parsed_fs is not None:
                if since is None or parsed_fs < since:
                    since = parsed_fs
    if durations:
        durations.sort()
        median_hours = round(statistics.median(durations), 1)
        p90_hours = round(durations[min(len(durations) - 1, int(len(durations) * 0.9))], 1)
        longest_hours = round(max(durations), 1)
    else:
        median_hours = None
        p90_hours = None
        longest_hours = None
    since_str = since.strftime("%Y-%m-%d") if since is not None else None
    return {
        "counts": counts,
        "since": since_str,
        "median_hours": median_hours,
        "p90_hours": p90_hours,
        "longest_hours": longest_hours,
    }


def weekly_counts(records, now, horizon_days=90):
    if records is None:
        records = []
    horizon = now + timedelta(days=horizon_days)
    weeks = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("withdrawn"):
            continue
        t = _times(rec)
        if t is None:
            continue
        start, end = t
        if start > horizon:
            continue
        week = (start.date() - timedelta(days=start.weekday())).isoformat()
        if week not in weeks:
            weeks[week] = {"held": 0, "open": 0}
        if end < now:
            weeks[week]["held"] += 1
        else:
            weeks[week]["open"] += 1
    result = []
    for week in sorted(weeks.keys()):
        result.append({"week": week, "held": weeks[week]["held"], "open": weeks[week]["open"]})
    return result


def start_profile(records):
    if records is None:
        records = []
    hours = [0] * 24
    weekdays = [0] * 7
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("withdrawn"):
            continue
        t = _times(rec)
        if t is None:
            continue
        start, end = t
        hours[start.hour] += 1
        weekdays[start.weekday()] += 1
    return {"hours": hours, "weekdays": weekdays}


def count_by(records, kind, limit=10):
    if records is None:
        records = []
    if kind not in ("division", "region", "type", "airport"):
        return []
    counter = Counter()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("withdrawn"):
            continue
        t = _times(rec)
        if t is None:
            continue
        if kind == "airport":
            airports = rec.get("airports")
            if isinstance(airports, list):
                seen = set()
                for a in airports:
                    val = str(a).strip().upper()
                    if val and val not in seen:
                        seen.add(val)
                        counter[val] += 1
        else:
            val = rec.get(kind)
            if val is not None:
                val = str(val).strip()
                if val:
                    counter[val] += 1
    items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    return items[:limit]


def series(records, now, min_count=2, limit=10):
    if records is None:
        records = []
    groups = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("withdrawn"):
            continue
        if rec.get("type") != "Event":
            continue
        t = _times(rec)
        if t is None:
            continue
        start, end = t
        name = rec.get("name")
        key = " ".join(str(name or "").split()).casefold()
        if not key:
            continue
        if key not in groups:
            groups[key] = []
        groups[key].append((start, end, rec))
    result = []
    for key, members in groups.items():
        if len(members) < min_count:
            continue
        members_sorted = sorted(members, key=lambda x: x[0])
        earliest_start = members_sorted[0][0]
        earliest_rec = members_sorted[0][2]
        name_val = earliest_rec.get("name")
        name_str = " ".join(str(name_val or "").split())
        count = len(members)
        held = sum(1 for m in members if m[1] < now)
        weekday_counter = Counter(m[0].weekday() for m in members)
        max_wd_count = max(weekday_counter.values())
        typical_weekday = min(wd for wd, c in weekday_counter.items() if c == max_wd_count)
        hour_counter = Counter(m[0].hour for m in members)
        max_hr_count = max(hour_counter.values())
        typical_hour = min(hr for hr, c in hour_counter.items() if c == max_hr_count)
        div_counter = Counter()
        for m in members:
            d = m[2].get("division")
            if d is not None:
                d_str = str(d).strip()
                if d_str:
                    div_counter[d_str] += 1
        if div_counter:
            max_div_count = max(div_counter.values())
            division = min(d for d, c in div_counter.items() if c == max_div_count)
        else:
            division = None
        next_start = None
        for m in members:
            if m[0] > now:
                if next_start is None or m[0] < next_start:
                    next_start = m[0]
        next_start_str = next_start.strftime(_FMT) if next_start is not None else None
        result.append({
            "name": name_str,
            "count": count,
            "held": held,
            "typical_weekday": typical_weekday,
            "typical_hour": typical_hour,
            "division": division,
            "next_start": next_start_str,
        })
    result.sort(key=lambda x: (-x["count"], x["name"].casefold()))
    return result[:limit]


def withdrawn_list(records):
    if records is None:
        records = []
    result = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if classify(rec, datetime.now(timezone.utc)) == "withdrawn":
            result.append({
                "name": str(rec.get("name") or ""),
                "start": rec.get("start"),
                "type": str(rec.get("type") or ""),
            })
    result.sort(key=lambda x: x["start"] or "")
    return result