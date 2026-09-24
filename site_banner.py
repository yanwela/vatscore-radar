import json
import os
import datetime

VALID_LEVELS = ("info", "warning", "error")
_FMT = "%Y-%m-%dT%H:%M:%SZ"

def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.datetime.strptime(ts, _FMT).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None

def write_banner(path, text, level="info", now=None, starts_at=None, expires_at=None):
    text = str(text or "").strip()
    if not text:
        clear_banner(path)
        return None
    level = level if level in VALID_LEVELS else "info"
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    row = {
        "text": text,
        "level": level,
        "set_at": now.strftime(_FMT),
        "starts_at": starts_at.strftime(_FMT) if starts_at else None,
        "expires_at": expires_at.strftime(_FMT) if expires_at else None
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(row, f)
    return row

def read_banner_raw(path):
    # The banner exactly as scheduled, regardless of whether it has started or already ended - the admin panel needs to
    # see/edit/cancel a banner that isn't live yet or has finished, not just what visitors currently see.
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return None
    if not isinstance(obj, dict) or not obj.get("text"):
        return None
    level = obj.get("level")
    if level not in VALID_LEVELS:
        level = "info"
    return {
        "text": str(obj["text"]),
        "level": level,
        "set_at": str(obj.get("set_at") or ""),
        "starts_at": obj.get("starts_at"),
        "expires_at": obj.get("expires_at")
    }

def read_banner(path, now=None):
    banner = read_banner_raw(path)
    if not banner:
        return None
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = _parse(banner["expires_at"])
    if expires_at and now >= expires_at:
        clear_banner(path)
        return None
    starts_at = _parse(banner["starts_at"])
    if starts_at and now < starts_at:
        return None  # scheduled for later - the file stays put so it goes live on its own
    return banner

def clear_banner(path):
    if os.path.exists(path):
        os.remove(path)
    return None
