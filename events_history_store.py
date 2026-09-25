import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

import data_sync
from events_data import parse_events
from events_history_merge import merge_events

HISTORY_DIR = "events_history"
EVENTS_URL = "https://my.vatsim.net/api/v2/events/latest"
MIN_INTERVAL_S = 6 * 3600

_lock = threading.Lock()
_state = {"running": False, "last": 0.0, "last_error": None, "last_written": [], "ensured": set()}


def _path(year):
    return f"{HISTORY_DIR}/{year}.json"


def _parse(text):
    try:
        obj = json.loads(text) if text else None
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _read_local(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _parse(f.read())
    except OSError:
        return None


def _read(path):
    # this server's copy first, else the data repo's (a fresh deploy starts with an empty disk)
    return _read_local(path) or _parse(data_sync.pull_one(path)) or {}


def _union(mine, theirs):
    # Two writers (this server and another one, e.g. the hosted app and a dev machine) may both record events. Whole-file writes would
    # let the last one erase the other's records, so what the repo holds right now is folded in first; the record seen most recently wins.
    out = dict(mine)
    for key, rb in theirs.items():
        ra = out.get(key)
        if not isinstance(rb, dict):
            continue
        if ra is None:
            out[key] = rb
            continue
        newer = ra if str(ra.get("last_seen", "")) >= str(rb.get("last_seen", "")) else rb
        rec = dict(newer)
        firsts = [x for x in (ra.get("first_seen"), rb.get("first_seen")) if x]
        if firsts:
            rec["first_seen"] = min(firsts)
        out[key] = rec
    return out


def _write(path, history):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _ensure_remote(path):
    # a record set that only exists on this disk (an earlier push failed) is copied into the data repo once per server run
    with _lock:
        if path in _state["ensured"] or not data_sync.enabled(path):
            return
        _state["ensured"].add(path)

    def run():
        try:
            if data_sync.pull_one(path) is None:
                data_sync.push(path, f"events history {os.path.basename(path)[:-5]}")
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def record_events(events, now=None):
    # merges a parsed event list into the per-year history files; returns the years that changed
    now = datetime.now(timezone.utc) if now is None else now
    by_year = {}
    for ev in events:
        by_year.setdefault(ev["start"].astimezone(timezone.utc).year, []).append(ev)
    written = []
    for year, year_events in sorted(by_year.items()):
        path = _path(year)
        history = _read(path)
        merged, changed = merge_events(history, year_events, now)
        if not changed:
            _ensure_remote(path)
            continue
        remote = _parse(data_sync.pull_one(path)) if data_sync.enabled(path) else None
        if remote:
            merged = _union(merged, remote)
        _write(path, merged)
        data_sync.push_background(path, f"events history {year}")
        written.append(year)
    return written


def _fetch_events():
    r = requests.get(EVENTS_URL, timeout=15, headers={"User-Agent": "VatScoreRadar", "Accept": "application/json"})
    r.raise_for_status()
    return parse_events(r.json())


def maybe_record(events=None, fetch=_fetch_events, interval=MIN_INTERVAL_S, now_s=None, inline=False):
    # at most once per `interval` per server run, in a background thread: records `events` (or fetches them); returns the thread, None when not due
    now_s = time.time() if now_s is None else now_s
    with _lock:
        if _state["running"] or now_s - _state["last"] < interval:
            return None
        _state["running"] = True
        _state["last"] = now_s

    def run():
        try:
            current = events if events is not None else fetch()
            _state["last_written"] = record_events(current) if current else []
            _state["last_error"] = None
        except Exception as e:
            _state["last_error"] = f"{type(e).__name__}: {e}"[:160]
            _state["last"] = now_s - interval + 300  # a failed run is retried in about 5 minutes, not after the whole interval
        finally:
            with _lock:
                _state["running"] = False

    if inline:
        run()
        return None
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _remote_counts():
    # the hosted disk starts empty after every restart, so the local files alone would say "0 recorded": ask the data repo too (cached for 5 minutes)
    cache = _state.get("remote_cache")
    if cache and time.time() - cache[0] < 300:
        return cache[1]
    found = {}
    if data_sync.enabled(_path(0)):
        this_year = datetime.now(timezone.utc).year
        for year in range(this_year - 1, this_year + 2):
            history = _parse(data_sync.pull_one(_path(year)))
            if history is not None:
                found[str(year)] = history
    _state["remote_cache"] = (time.time(), found)
    return found


def status():
    histories = {}
    if os.path.isdir(HISTORY_DIR):
        for name in sorted(os.listdir(HISTORY_DIR)):
            if name.endswith(".json"):
                histories[name[:-5]] = _read_local(f"{HISTORY_DIR}/{name}") or {}
    for year, history in _remote_counts().items():
        if len(history) > len(histories.get(year, {})):
            histories[year] = history
    counts = {y: len(h) for y, h in sorted(histories.items())}
    withdrawn = sum(1 for h in histories.values() for r in h.values() if isinstance(r, dict) and r.get("withdrawn"))
    return {"years": counts, "total": sum(counts.values()), "withdrawn": withdrawn, "last_run": _state["last"] or None, "last_error": _state["last_error"]}
