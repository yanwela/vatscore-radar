import json
import os
import datetime as dt


def record_view(path, page, now=None):
    if not isinstance(path, str):
        raise TypeError("path must be a string")
    if not isinstance(page, str):
        raise TypeError("page must be a string")
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    elif not isinstance(now, dt.datetime):
        raise TypeError("now must be a datetime instance")
    row = {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "page": page}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def summarize_views(path, hours=None):
    if not isinstance(path, str):
        raise TypeError("path must be a string")
    if not os.path.exists(path):
        return []
    cutoff = None
    if hours is not None:
        if isinstance(hours, (int, float)):
            hrs = float(hours)
        elif isinstance(hours, str) and hours.isdigit():
            hrs = float(hours)
        else:
            return []
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hrs)
    counts = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if not isinstance(obj, dict) or "page" not in obj:
                continue
            if cutoff is not None:
                ts_raw = obj.get("ts")
                if not isinstance(ts_raw, str):
                    continue
                try:
                    ts = dt.datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
            page = str(obj["page"])
            counts[page] = counts.get(page, 0) + 1
    rows = [{"page": p, "count": c} for p, c in counts.items()]
    rows.sort(key=lambda x: (-x["count"], x["page"]))
    return rows