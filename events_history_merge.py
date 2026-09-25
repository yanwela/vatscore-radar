import copy
import hashlib
from datetime import datetime, timezone, timedelta

def event_key(ev):
    ev_id = ev.get("id")
    if isinstance(ev_id, int) and not isinstance(ev_id, bool):
        return "e" + str(ev_id)
    name = ev.get("name", "")
    start_dt = ev.get("start")
    if not isinstance(start_dt, datetime):
        raise ValueError("Invalid start datetime")
    start_str = start_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = f"{name}|{start_str}"
    return "h" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

def merge_events(history, events, now):
    new_history = copy.deepcopy(history)
    now_utc = now.astimezone(timezone.utc)
    now_s = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = False
    KEEP = ("id", "name", "type", "start", "end", "airports", "region", "division", "link")
    seen_keys = set()
    for ev in events:
        key = event_key(ev)
        seen_keys.add(key)
        start_dt = ev["start"]
        end_dt = ev["end"]
        if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
            raise ValueError("Invalid datetime in event")
        new_rec = {
            "id": ev.get("id"),
            "name": ev.get("name"),
            "type": ev.get("type"),
            "start": start_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "airports": list(ev.get("airports", [])),
            "region": ev.get("region"),
            "division": ev.get("division"),
            "link": ev.get("link"),
        }
        if key not in new_history:
            rec = new_rec.copy()
            rec["first_seen"] = now_s
            rec["last_seen"] = now_s
            new_history[key] = rec
            changed = True
        else:
            rec = new_history[key]
            for field in KEEP:
                if rec.get(field) != new_rec.get(field):
                    rec[field] = new_rec[field]
                    changed = True
            if "withdrawn" in rec:
                del rec["withdrawn"]
                changed = True
            rec["last_seen"] = now_s
    if len(events) >= 1:
        for key, rec in new_history.items():
            if key in seen_keys:
                continue
            if "withdrawn" in rec:
                continue
            end_dt = datetime.strptime(rec["end"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            start_dt = datetime.strptime(rec["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if end_dt > now_utc and start_dt > now_utc + timedelta(minutes=30):
                rec["withdrawn"] = now_s
                changed = True
    return new_history, changed