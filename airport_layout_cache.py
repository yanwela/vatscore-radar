import json
import os
import re
import threading
import time

import requests

import data_sync
from airport_layout import fetch_layout

LAYOUT_DIR = "layouts"
FULL_TTL_S = 90 * 86400
EMPTY_TTL_S = 7 * 86400
RETRY_DELAYS_S = (30, 60, 120, 240)
_ICAO = re.compile(r"[A-Z0-9]{3,4}")

_lock = threading.Lock()
_retrying = set()
_verified = set()
_warm = {"running": False, "last": {}}
_synced = {"done": False}


def _is_empty(layout):
    return not (layout["runways"] or layout["taxiways"] or layout["stands"])


def _fresh(record, now):
    if not isinstance(record, dict) or not isinstance(record.get("layout"), dict) or not isinstance(record.get("fetched_at"), (int, float)):
        return False
    layout = record["layout"]
    if not all(isinstance(layout.get(k), list) for k in ("runways", "taxiways", "aprons", "terminals", "stands", "holds")):
        return False
    return now - record["fetched_at"] < (EMPTY_TTL_S if _is_empty(layout) else FULL_TTL_S)


def _path(icao):
    return f"{LAYOUT_DIR}/{icao}.json"


def _load_record(path):
    for source in (lambda: open(path, encoding="utf-8").read() if os.path.exists(path) else None, lambda: data_sync.pull_one(path)):
        try:
            text = source()
            record = json.loads(text) if text else None
        except Exception:
            continue
        if record is not None:
            return record, text
    return None, None


def _save(icao, layout, now):
    os.makedirs(LAYOUT_DIR, exist_ok=True)
    with open(_path(icao), "w", encoding="utf-8") as f:
        json.dump({"fetched_at": now, "layout": layout}, f, separators=(",", ":"))
    data_sync.push_background(_path(icao), f"airport layout {icao}")


def _ensure_in_repo(icao):
    # A layout that only exists on this server's disk (fetched before the data repo was connected, or before a failed push) is
    # copied into the data repo once per server run, so a fresh deploy never has to download it from OpenStreetMap again.
    with _lock:
        if icao in _verified or not data_sync.enabled(_path(icao)):
            return
        _verified.add(icao)

    def run():
        try:
            path = _path(icao)
            if data_sync.pull_one(path) is None:
                data_sync.push(path, f"airport layout {icao}")
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def sync_local_layouts_in_background():
    # Once per server run: every layout on this disk that the data repo does not have yet is uploaded (one at a time).
    with _lock:
        if _synced["done"]:
            return None
        _synced["done"] = True

    def run():
        try:
            names = sorted(n for n in os.listdir(LAYOUT_DIR) if n.endswith(".json")) if os.path.isdir(LAYOUT_DIR) else []
            for name in names:
                path = f"{LAYOUT_DIR}/{name}"
                if _ICAO.fullmatch(name[:-5]) and data_sync.enabled(path) and data_sync.pull_one(path) is None:
                    data_sync.push(path, f"airport layout {name[:-5]}")
        except Exception:
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def is_retrying(icao):
    with _lock:
        return str(icao).strip().upper() in _retrying


def _retry_in_background(icao, lat, lon, fetch, delays, sleep):
    with _lock:
        if icao in _retrying:
            return
        _retrying.add(icao)

    def run():
        try:
            http = requests.Session()
            for delay in delays:
                sleep(delay)
                layout = fetch(lat, lon, http)
                if layout is not None:
                    _save(icao, layout, time.time())
                    return
        except Exception:
            pass
        finally:
            with _lock:
                _retrying.discard(icao)

    threading.Thread(target=run, daemon=True).start()


def load_airport_layout(icao, lat, lon, session, fetch=fetch_layout, now=None, retry_delays=RETRY_DELAYS_S, sleep=time.sleep):
    icao = str(icao).strip().upper()
    if not _ICAO.fullmatch(icao):
        return None
    now = time.time() if now is None else now
    path = _path(icao)
    record, text = _load_record(path)
    if record is not None and _fresh(record, now):
        if not os.path.exists(path) and text:
            os.makedirs(LAYOUT_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        _ensure_in_repo(icao)
        return record["layout"]
    layout = fetch(lat, lon, session)
    if layout is None:
        if record is not None and isinstance(record.get("layout"), dict):
            return record["layout"]
        if retry_delays:
            _retry_in_background(icao, lat, lon, fetch, retry_delays, sleep)
        return None
    _save(icao, layout, now)
    return layout


def prefetch(airports, session, fetch=fetch_layout, pause_s=4.0, sleep=time.sleep, now=None):
    # airports: (icao, lat, lon) tuples. One request at a time with a pause, so the public Overpass servers are not hammered.
    def polite(lat, lon, s):
        out = fetch(lat, lon, s)
        sleep(pause_s)
        return out

    for icao, lat, lon in airports:
        try:
            load_airport_layout(icao, lat, lon, session, fetch=polite, now=now, retry_delays=())
        except Exception:
            continue


def warm_in_background(key, airports, min_interval_s=3600, fetch=fetch_layout, pause_s=4.0, sleep=time.sleep, now=None):
    airports = list(airports)
    now = time.time() if now is None else now
    if not airports:
        return None
    with _lock:
        if _warm["running"] or now - _warm["last"].get(key, 0) < min_interval_s:
            return None
        _warm["running"] = True
        _warm["last"][key] = now

    def run():
        try:
            prefetch(airports, requests.Session(), fetch=fetch, pause_s=pause_s, sleep=sleep, now=now)
        finally:
            with _lock:
                _warm["running"] = False

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
