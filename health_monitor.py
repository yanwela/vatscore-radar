import time

def record_result(store, source, ok, error=None, now=None):
    if now is None:
        now = time.time()
    entry = store.setdefault(source, {
        "last_ok_at": None,
        "last_error_at": None,
        "last_error": None,
        "consecutive_fails": 0,
        "total_ok": 0,
        "total_fail": 0
    })
    if ok:
        entry["last_ok_at"] = now
        entry["consecutive_fails"] = 0
        entry["total_ok"] += 1
    else:
        entry["last_error_at"] = now
        entry["last_error"] = str(error) if error is not None else "unknown error"
        entry["consecutive_fails"] += 1
        entry["total_fail"] += 1
    return store

def summarize(store, now=None):
    if now is None:
        now = time.time()
    rows = []
    for source, entry in sorted(store.items()):
        if entry["consecutive_fails"] == 0 and entry["last_ok_at"] is not None:
            status = "ok"
        elif entry["last_ok_at"] is None and entry["last_error_at"] is None:
            status = "unknown"
        else:
            status = "failing"
        age_ok = (now - entry["last_ok_at"]) if entry["last_ok_at"] is not None else None
        age_error = (now - entry["last_error_at"]) if entry["last_error_at"] is not None else None
        row = {
            "source": source,
            "status": status,
            "seconds_since_ok": age_ok,
            "seconds_since_error": age_error,
            "last_error": entry["last_error"],
            "consecutive_fails": entry["consecutive_fails"],
            "total_ok": entry["total_ok"],
            "total_fail": entry["total_fail"]
        }
        rows.append(row)
    return rows