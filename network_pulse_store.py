import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import data_sync
from network_pulse_core import add_sample, merge_days, new_day, prune_day, sample_counts

PULSE_DIR = "network_pulse"
FLUSH_INTERVAL_S = 3600
VIEW_TTL_S = 60
# a day keeps more keys on disk than any page shows: a key that sits near the cut-off during a mid-day save can still climb later
STORE_KEYS = {"airports": 150, "airlines": 80, "types": 80, "regions": 100}

_lock = threading.Lock()
_state = {"delta": {}, "last_feed_t": 0.0, "last_flush": 0.0, "running": False, "last_error": None, "samples": 0, "first_sample": 0.0, "views": {}}


def _path(month):
    return f"{PULSE_DIR}/{month}.json"


def _parse(text):
    try:
        obj = json.loads(text) if text else None
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _read(path):
    # this server's copy first, else the data repo's (a fresh deploy starts with an empty disk)
    try:
        with open(path, encoding="utf-8") as f:
            found = _parse(f.read())
    except OSError:
        found = None
    return found if found is not None else (_parse(data_sync.pull_one(path)) or {})


def _write(path, obj):
    os.makedirs(PULSE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def record(feed_t, pilots, controllers):
    # one sample per new feed timestamp: the totals and the per-airport / airline / aircraft-type / region counts of that moment, folded into
    # the running totals of its UTC day (averages are sum / samples, so a restart or a second recorder never skews them)
    if feed_t is None:
        return
    with _lock:
        if feed_t <= _state["last_feed_t"]:
            return
        _state["last_feed_t"] = feed_t
    try:
        sample = sample_counts(pilots, controllers)
        if not sample["pilots"] and not sample["controllers"]:
            return
        moment = datetime.fromtimestamp(feed_t, timezone.utc)
        with _lock:
            add_sample(_state["delta"].setdefault(moment.strftime("%Y-%m-%d"), new_day()), sample, moment.hour)
            _state["samples"] += 1
            _state["first_sample"] = _state["first_sample"] or feed_t
        flush()
    except Exception as e:  # a bad feed must never stop the recorder thread; the admin panel shows the last error
        _state["last_error"] = f"{type(e).__name__}: {e}"[:160]


def flush(now_s=None, interval=FLUSH_INTERVAL_S, inline=False):
    # at most once per `interval`: folds the pending samples into the month files, in a background thread (returns it; None when nothing was due)
    now_s = time.time() if now_s is None else now_s
    with _lock:
        if _state["running"] or not _state["delta"] or now_s - _state["last_flush"] < interval:
            return None
        _state["running"] = True
        _state["last_flush"] = now_s
        batch, _state["delta"] = _state["delta"], {}

    def run():
        try:
            by_month = {}
            for day, rec in batch.items():
                by_month.setdefault(day[:7], {})[day] = rec
            for month, days in by_month.items():
                stored = _read(_path(month))
                for day, rec in days.items():
                    stored[day] = prune_day(merge_days(stored.get(day), rec), STORE_KEYS)
                _write(_path(month), stored)
                data_sync.push_background(_path(month), f"network history {month}")
            _state["last_error"] = None
        except Exception as e:
            _state["last_error"] = f"{type(e).__name__}: {e}"[:160]
            with _lock:
                for day, rec in batch.items():
                    _state["delta"][day] = merge_days(_state["delta"].get(day), rec)
                _state["last_flush"] = now_s - interval + 300
        finally:
            with _lock:
                _state["running"] = False
                _state["views"] = {}

    if inline:
        run()
        return None
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def load_days(days_back=30, now_s=None):
    # {"YYYY-MM-DD": day record} for the last `days_back` days, saved files plus what is still waiting in memory (cached for a minute)
    now_s = time.time() if now_s is None else now_s
    with _lock:
        cached = _state["views"].get(days_back)
        if cached and time.time() - cached[0] < VIEW_TTL_S:
            return cached[1]
        pending = {day: dict(rec) for day, rec in _state["delta"].items()}
    first = (datetime.fromtimestamp(now_s, timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    last = datetime.fromtimestamp(now_s, timezone.utc).strftime("%Y-%m-%d")
    months = sorted({(datetime.fromtimestamp(now_s, timezone.utc) - timedelta(days=i)).strftime("%Y-%m") for i in range(days_back + 1)})
    out = {}
    for month in months:
        for day, rec in _read(_path(month)).items():
            if first <= day <= last and isinstance(rec, dict):
                out[day] = rec
    for day, rec in pending.items():
        if first <= day <= last:
            out[day] = merge_days(out.get(day), rec)
    with _lock:
        _state["views"][days_back] = (time.time(), out)
    return out


def status():
    with _lock:
        pending = len(_state["delta"])
    files = [n for n in os.listdir(PULSE_DIR) if n.endswith(".json")] if os.path.isdir(PULSE_DIR) else []
    return {"samples": _state["samples"], "first_sample": _state["first_sample"] or None, "last_flush": _state["last_flush"] or None, "pending_days": pending,
            "stored_months": len(files), "last_error": _state["last_error"], "synced": data_sync.enabled(_path("0000-00"))}
