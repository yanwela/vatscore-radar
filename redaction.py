import json
import os
from datetime import datetime, timezone

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def load_blocklist(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    result = {}
    for k, v in obj.items():
        cid = str(k).strip()
        if not cid.isdigit():
            continue
        if isinstance(v, dict):
            result[cid] = {
                "reason": str(v.get("reason", "")),
                "added_at": str(v.get("added_at", ""))
            }
        else:
            result[cid] = {"reason": "", "added_at": ""}
    return result

def add_to_blocklist(path, cid, reason="", now=None):
    cid = str(cid).strip()
    if not cid.isdigit():
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    data = load_blocklist(path)
    data[cid] = {
        "reason": str(reason or ""),
        "added_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    _save(path, data)
    return data[cid]

def remove_from_blocklist(path, cid):
    cid = str(cid).strip()
    data = load_blocklist(path)
    if cid in data:
        del data[cid]
        _save(path, data)
        return True
    return False

def is_blocked(path, cid):
    cid = str(cid).strip()
    if not cid.isdigit():
        return False
    return cid in load_blocklist(path)