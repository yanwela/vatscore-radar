import json
import os
import threading
import time

import data_sync
from anomaly_archive_core import count_event, make_event, merge_events, purge_cid, rollup, split_events, summarize

ARCHIVE_DIR = "anomaly_history"
EVENTS_PATH = f"{ARCHIVE_DIR}/events.json"
COUNTS_PATH = f"{ARCHIVE_DIR}/counts.json"
FLUSH_INTERVAL_S = 1800

_lock = threading.Lock()
_state = {"pending": [], "last_flush": 0.0, "running": False, "last_error": None, "last_written": 0}


def _parse(text, kind):
    try:
        obj = json.loads(text) if text else None
    except Exception:
        return None
    return obj if isinstance(obj, kind) else None


def _read(path, kind):
    # this server's copy first, else the data repo's (a fresh deploy starts with an empty disk)
    try:
        with open(path, encoding="utf-8") as f:
            found = _parse(f.read(), kind)
    except OSError:
        found = None
    return found if found is not None else (_parse(data_sync.pull_one(path), kind) or kind())


def _write(path, obj):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _max_counts(a, b):
    # two servers roll up the same old events: the per-hour value that is larger wins, so nothing is counted twice
    out = {day: {k: dict(hours) for k, hours in types.items()} for day, types in a.items()}
    for day, types in b.items():
        for k, hours in types.items():
            slot = out.setdefault(day, {}).setdefault(k, {})
            for hh, n in hours.items():
                slot[hh] = max(slot.get(hh, 0), n)
    return out


def _blocked():
    try:
        from redaction import load_blocklist
        return {str(c) for c in load_blocklist(data_sync.CID_BLOCKLIST_FILE)}
    except Exception:
        return set()


def add_closed(closed):
    # closed = [(anomaly dict, first_s, last_s)] of anomalies that have gone away; kept in memory until the next flush
    blocked = _blocked()
    events = [make_event(a, first, last) for a, first, last in closed if str(a.get("cid")) not in blocked]
    if events:
        with _lock:
            _state["pending"].extend(events)


def flush(now_s=None, interval=FLUSH_INTERVAL_S, inline=False):
    # at most once per `interval`: folds the pending events into the files, in a background thread (returns it; None when nothing was due)
    now_s = time.time() if now_s is None else now_s
    with _lock:
        if _state["running"] or not _state["pending"] or now_s - _state["last_flush"] < interval:
            return None
        _state["running"] = True
        _state["last_flush"] = now_s
        batch, _state["pending"] = _state["pending"], []

    def run():
        try:
            events = merge_events(_read(EVENTS_PATH, list), batch)
            remote = _parse(data_sync.pull_one(EVENTS_PATH), list) if data_sync.enabled(EVENTS_PATH) else None
            if remote:
                events = merge_events(events, remote)
            events, old_counts = rollup(events, int(now_s // 60))
            for cid in _blocked():
                events = purge_cid(events, cid)
            _write(EVENTS_PATH, events)
            counts = _read(COUNTS_PATH, dict)
            if old_counts:
                counts = _max_counts(counts, old_counts)
                _write(COUNTS_PATH, counts)
            data_sync.push_background(EVENTS_PATH, "anomaly history")
            if old_counts:
                data_sync.push_background(COUNTS_PATH, "anomaly history counts")
            _state["last_written"] = len(events)
            _state["last_error"] = None
        except Exception as e:
            _state["last_error"] = f"{type(e).__name__}: {e}"[:160]
            with _lock:
                _state["pending"] = batch + _state["pending"]
                _state["last_flush"] = now_s - interval + 300
        finally:
            with _lock:
                _state["running"] = False

    if inline:
        run()
        return None
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def history(now_s, days):
    # what the History section shows: the archive plus what is still waiting in memory (cached for a minute: the section refreshes every 20 s
    # and an empty disk would otherwise ask the data repo every time)
    with _lock:
        cached = _state.get("view", {}).get(days)
        if cached and time.time() - cached[0] < 60:
            return cached[1]
        pending = list(_state["pending"])
    events = merge_events(_read(EVENTS_PATH, list), pending)
    blocked = _blocked()
    events = [e for e in events if str(e.get("cid")) not in blocked]
    detail, counted = split_events(events)
    counts = _max_counts(_read(COUNTS_PATH, dict), {})
    for e in counted:  # the noisy kinds are only ever counted, per day and hour
        count_event(counts, e)
    result = summarize(detail, counts, int(now_s // 60), days)
    with _lock:
        _state.setdefault("view", {})[days] = (time.time(), result)
    return result


def purge(cid):
    # a CID that was just redacted disappears from the archive too
    with _lock:
        _state["pending"] = purge_cid(_state["pending"], cid)
        _state["view"] = {}
    events = purge_cid(_read(EVENTS_PATH, list), cid)
    _write(EVENTS_PATH, events)
    data_sync.push_background(EVENTS_PATH, "anomaly history")
