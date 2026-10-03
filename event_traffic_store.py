import json
import os
import threading
import time
from datetime import datetime, timezone

import requests
import streamlit as st

import data_sync
import events_history_store
import events_stats
from atc_replay_data import fetch_airport_flights
from event_traffic_core import baseline_windows, build_record, count_movements, parse_ts, window_for
from replay_atc_data import fetch_atc_sessions
from vatsim_data import load_airport_key_map

TRAFFIC_DIR = "events_traffic"
MAX_AIRPORTS = 6        # an event listing more airports than this is measured on its first six only
REQUEST_PAUSE_S = 1.2   # StatSim is a free service the rest of the site leans on too: stay well under any limit
EVENT_PAUSE_S = 20
IDLE_PAUSE_S = 300
RETRY_AFTER_FAIL_S = 300
PUSH_MIN_S = 600
MAX_FAILURES = 3
RECORD_VERSION = 2  # a record written by an older version of the measuring is measured again: v2 matches US-style callsigns (MSN_TWR for KMSN)

_lock = threading.Lock()
_state = {"started": False, "last_error": None, "computed": 0, "fail_until": 0.0, "failures": {}, "dirty": set(), "last_push": 0.0, "cache": None, "remote": None, "http": None}


def _path(year):
    return f"{TRAFFIC_DIR}/{year}.json"


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


def _write(path, obj):
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _union(a, b):
    # two writers (the hosted app and a dev machine) may both measure: the record computed later wins, nothing is dropped
    out = dict(a)
    for key, rec in b.items():
        if isinstance(rec, dict) and (key not in out or rec.get("computed", 0) > out[key].get("computed", 0)):
            out[key] = rec
    return out


def _remote_years():
    cache = _state["remote"]
    if cache and time.time() - cache[0] < 300:
        return cache[1]
    found = {}
    this_year = datetime.now(timezone.utc).year
    for year in range(this_year - 1, this_year + 2):
        if data_sync.enabled(_path(year)):
            parsed = _parse(data_sync.pull_one(_path(year)))
            if parsed:
                found[str(year)] = parsed
    _state["remote"] = (time.time(), found)
    return found


def all_traffic(ttl=60):
    # every measured event: {event key: traffic record}, this server's files plus the data repo's, cached briefly for the statistics view
    cache = _state["cache"]
    if cache and time.time() - cache[0] < ttl:
        return cache[1]
    merged = {}
    if os.path.isdir(TRAFFIC_DIR):
        for name in sorted(os.listdir(TRAFFIC_DIR)):
            if name.endswith(".json"):
                merged = _union(merged, _read_local(f"{TRAFFIC_DIR}/{name}") or {})
    for remote in _remote_years().values():
        merged = _union(merged, remote)
    _state["cache"] = (time.time(), merged)
    return merged


def _airports(rec):
    seen, out = set(), []
    for item in rec.get("airports") or []:
        code = str(item).strip().upper()
        if len(code) == 4 and code.isalnum() and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _callsign_keys(airports):
    # {icao: [the other codes controllers log on with]}, from VATSpy's IATA/LID column (KMSN is MSN_TWR, LTFM is IST_APP)
    out = {icao: [] for icao in airports}
    try:
        key_map = load_airport_key_map() or {}
    except Exception:
        key_map = {}
    for prefix, icaos in key_map.items():
        for icao in icaos:
            if icao in out:
                out[icao].append(prefix)
    return out


def pending_events(records, traffic, now_s):
    # finished events that have airports and no measurement yet, newest first. An event is measured once BOTH comparison days (the day before
    # and the day after, same hours) are over, so every event gets the same kind of comparison.
    now_dt = datetime.fromtimestamp(now_s, timezone.utc)
    todo = []
    for rec in records or []:
        key = rec.get("key") if isinstance(rec, dict) else None
        if not key or _state["failures"].get(key, 0) >= MAX_FAILURES:
            continue
        done = traffic.get(key)
        if isinstance(done, dict) and done.get("v", 1) >= RECORD_VERSION:
            continue
        if events_stats.classify(rec, now_dt) != "held" or not _airports(rec):
            continue
        lo, hi = window_for(parse_ts(rec["start"]), parse_ts(rec["end"]))
        if len(baseline_windows(lo, hi, now_s)) < 2:
            continue
        todo.append(rec)
    todo.sort(key=lambda r: r["start"], reverse=True)
    return todo


def compute_event(rec, api_key, http, now_s, pause=REQUEST_PAUSE_S):
    # StatSim: the flights at each event airport in the window (from one hour before the start to 45 minutes after the end), the same airport's
    # movements in the two comparison windows, and the network's ATC sessions of the window. None when StatSim fails at any step.
    lo, hi = window_for(parse_ts(rec["start"]), parse_ts(rec["end"]))
    airports = _airports(rec)[:MAX_AIRPORTS]
    flights, baseline = {}, {}
    for icao in airports:
        got = fetch_airport_flights(icao, lo, hi, api_key, http)
        if got is None:
            return None
        flights[icao] = got
        time.sleep(pause)
        totals = []
        for lo2, hi2 in baseline_windows(lo, hi, now_s):
            other = fetch_airport_flights(icao, lo2, hi2, api_key, http)
            if other is None:
                return None
            counted = count_movements(other, icao, lo2, hi2)
            totals.append(counted["dep"] + counted["arr"])
            time.sleep(pause)
        baseline[icao] = totals
    sessions = fetch_atc_sessions(lo, hi, api_key, http)
    if sessions is None:
        return None
    record = build_record(airports, flights, baseline, sessions, lo, hi, now_s, keys=_callsign_keys(airports))
    record["v"] = RECORD_VERSION
    return record


def _save(rec, result):
    year = str(rec["start"])[:4]
    path = _path(year)
    with _lock:
        stored = _read_local(path) or {}
        if data_sync.enabled(path):
            stored = _union(stored, _parse(data_sync.pull_one(path)) or {})
        stored[rec["key"]] = result
        _write(path, stored)
        _state["cache"] = None
        _state["dirty"].add(path)


def _push_due(now):
    with _lock:
        if not _state["dirty"] or now - _state["last_push"] < PUSH_MIN_S:
            return
        paths, _state["dirty"] = list(_state["dirty"]), set()
        _state["last_push"] = now
    for path in paths:
        data_sync.push_background(path, f"event traffic {os.path.basename(path)[:-5]}")


def _api_key():
    try:
        key = str(st.secrets.get("STATSIM_API_KEY", "") or "")
    except Exception:
        key = ""
    return key or os.environ.get("STATSIM_API_KEY", "")


def api_key():
    return _api_key()


def _tick():
    # one step of the worker: at most one event, returns how long to wait before the next
    now = time.time()
    _push_due(now)
    if now < _state["fail_until"]:
        return min(RETRY_AFTER_FAIL_S, _state["fail_until"] - now)
    key = _api_key()
    if not key:
        return IDLE_PAUSE_S
    todo = pending_events(events_history_store.all_records(), all_traffic(), now)
    if not todo:
        return IDLE_PAUSE_S
    rec = todo[0]
    if _state["http"] is None:
        _state["http"] = requests.Session()
    result = compute_event(rec, key, _state["http"], now)
    if result is None:
        _state["failures"][rec["key"]] = _state["failures"].get(rec["key"], 0) + 1
        _state["fail_until"] = now + RETRY_AFTER_FAIL_S
        _state["last_error"] = f"StatSim did not answer for {str(rec.get('name'))[:40]}"
        return RETRY_AFTER_FAIL_S
    _save(rec, result)
    _state["computed"] += 1
    _state["last_error"] = None
    return EVENT_PAUSE_S


def _loop():
    while True:
        pause = IDLE_PAUSE_S
        try:
            pause = _tick()
        except Exception as e:
            _state["last_error"] = f"{type(e).__name__}: {e}"[:160]
        time.sleep(max(1, pause))


def start():
    # one background thread per server process
    with _lock:
        if _state["started"]:
            return False
        _state["started"] = True
    threading.Thread(target=_loop, daemon=True, name="event-traffic").start()
    return True


def status():
    now = time.time()
    try:
        waiting = len(pending_events(events_history_store.all_records(), all_traffic(), now))
        stored = len(all_traffic())
    except Exception:
        waiting, stored = None, None
    return {"started": _state["started"], "key_set": bool(_api_key()), "computed": _state["computed"], "stored": stored, "waiting": waiting, "last_error": _state["last_error"]}
