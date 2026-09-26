import threading
import time

import requests

import anomaly_engine

FEED_URL = "https://data.vatsim.net/v3/vatsim-data.json"
INTERVAL_S = 20

_lock = threading.Lock()
_state = {"started": False, "last_ok": 0.0, "last_error": None, "passes": 0}


def _once(fetch=None):
    if fetch is None:
        r = requests.get(FEED_URL, timeout=10, headers={"User-Agent": "VatScoreRadar"})
        r.raise_for_status()
        feed = r.json()
    else:
        feed = fetch()
    anomaly_engine.update(feed.get("pilots", []), anomaly_engine.feed_time(feed))
    _state["last_ok"] = time.time()
    _state["passes"] += 1
    _state["last_error"] = None


def _loop(interval):
    while True:
        try:
            _once()
        except Exception as e:
            _state["last_error"] = f"{type(e).__name__}: {e}"[:160]
        time.sleep(interval)


def start(interval=INTERVAL_S):
    # one background thread per server process: the archive keeps recording while nobody has the site open
    with _lock:
        if _state["started"]:
            return False
        _state["started"] = True
    threading.Thread(target=_loop, args=(interval,), daemon=True, name="anomaly-recorder").start()
    return True


def status():
    return {"running": _state["started"], "last_ok": _state["last_ok"] or None, "last_error": _state["last_error"], "passes": _state["passes"]}
