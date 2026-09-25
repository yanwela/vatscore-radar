import hashlib
import os
import threading
import time

import streamlit as st

from github_file_store import GitHubFileStore

SITE_BANNER_FILE = "site_banner.json"
CID_BLOCKLIST_FILE = "cid_blocklist.json"
PAGE_VIEWS_FILE = "page_views.jsonl"
ADMIN_AUDIT_FILE = "admin_audit_log.jsonl"
RADAR_LOG_FILE = "radar_traffic_logs.csv"
SHARED_PREFIXES = ("layouts/", "events_history/")  # public data, identical everywhere: synced even when DATA_SYNC is "off"
SYNCED_FILES = (SITE_BANNER_FILE, CID_BLOCKLIST_FILE, PAGE_VIEWS_FILE, ADMIN_AUDIT_FILE, RADAR_LOG_FILE)

_lock = threading.Lock()
_state = {"pulled": False, "last_ok": None, "last_error": None, "pushes": 0, "last_pushed": {}, "hashes": {}, "store": None, "remote": None}


def _secret(key):
    try:
        return str(st.secrets.get(key, "") or "")
    except Exception:
        return ""


def _get_store(path=None):
    # DATA_SYNC = "off" keeps the mutable admin data (banner, blocklist, logs) local, e.g. on a dev machine. The cached OpenStreetMap
    # airport layouts and the event history are public, not sensitive and identical everywhere, so they sync regardless of that switch.
    if _state["store"] is not None:  # an injected store (tests) wins over everything
        return _state["store"]
    shared_layout = bool(path) and str(path).startswith(SHARED_PREFIXES)
    if _secret("DATA_SYNC").lower() == "off" and not shared_layout:
        return None
    if _state["remote"] is None:
        repo, token = _secret("DATA_REPO"), _secret("DATA_REPO_TOKEN")
        if not repo or not token:
            return None
        _state["remote"] = GitHubFileStore(repo, token, branch=_secret("DATA_REPO_BRANCH") or "main")
    return _state["remote"]


def enabled(path=None):
    return _get_store(path) is not None


def _note(ok, store):
    if ok:
        _state["last_ok"] = time.time()
        _state["last_error"] = None
    else:
        _state["last_error"] = store.last_error or "unknown error"


def ensure_pulled(paths=SYNCED_FILES):
    # Once per server process: the repo copy is the source of truth, so a fresh deploy (empty disk) gets its data back.
    if _state["pulled"]:
        return
    with _lock:
        if _state["pulled"]:
            return
        store = _get_store()
        if store is not None:
            for path in paths:
                text = store.read(path)
                if text is not None:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(text)
                    _state["hashes"][path] = _digest(text)
                    _note(True, store)
                elif store.last_error:
                    _note(False, store)
        _state["pulled"] = True


def _digest(text):
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def push(path, message=None):
    store = _get_store(path)
    if store is None:
        return False
    with _lock:
        message = message or f"update {path}"
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
        else:
            text = None
        digest = _digest(text)
        if _state["hashes"].get(path, "unset") == digest:
            return True
        ok = store.write(path, text, message) if text is not None else store.delete(path, message)
        _note(ok, store)
        if ok:
            _state["hashes"][path] = digest
            _state["pushes"] += 1
            _state["last_pushed"][path] = time.time()
        return ok


def push_if_due(path, min_seconds=600):
    # Frequently changing files (page views, audit log) are pushed at most every min_seconds, off the request thread.
    if not enabled() or not os.path.exists(path):
        return
    now = time.time()
    last = _state["last_pushed"].get(path)
    if last is None:
        _state["last_pushed"][path] = now
        return
    if now - last < min_seconds:
        return
    _state["last_pushed"][path] = now
    threading.Thread(target=push, args=(path, f"update {path} (batched)"), daemon=True).start()


def pull_one(path):
    store = _get_store(path)
    if store is None:
        return None
    text = store.read(path)
    if text is None:
        if store.last_error:
            _note(False, store)
        return None
    _state["hashes"][path] = _digest(text)
    _note(True, store)
    return text


def push_background(path, message=None):
    if enabled(path):
        threading.Thread(target=push, args=(path, message), daemon=True).start()


def status():
    return {"enabled": enabled(), "last_ok": _state["last_ok"], "last_error": _state["last_error"], "pushes": _state["pushes"]}
