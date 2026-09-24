import json
import os
from datetime import datetime, timezone

def append_audit_event(path, event, detail="", now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    row = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": str(event),
        "detail": str(detail)
    }
    line = json.dumps(row, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return True

def read_audit_events(path, limit=200):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if isinstance(obj, dict) and "ts" in obj and "event" in obj:
                rows.append(obj)
    tail = rows[-limit:] if limit and limit > 0 else rows
    return list(reversed(tail))