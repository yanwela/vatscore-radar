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
SYNCED_FILES = (SITE_BANNER_FILE, CID_BLOCKLIST_FILE, PAGE_VIEWS_FILE, ADMIN_AUDIT_FILE, RADAR_LOG_FILE)

_lock = threading.Lock()
_state = {"pulled": False, "last_ok": None, "last_error": None, "pushes": 0, "last_pushed": {}, "hashes": {}, "store": None}


def _secret(key):
    try:
        return str(st.secrets.get(key, "") or "")
    except Exception:
        return ""


def _get_store():
    if _state["store"] is not None:
        return _state["store"]
    if _secret("DATA_SYNC").lower() == "off":
        return None
    repo, token = _secret("DATA_REPO"), _secret("DATA_REPO_TOKEN")
    if not repo or not token:
        return None
    _state["store"] = GitHubFileStore(repo, token, branch=_secret("DATA_REPO_BRANCH") or "main")
    return _state["store"]


def enabled():
    return _get_store() is not None


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
    store = _get_store()
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


def status():
    return {"enabled": enabled(), "last_ok": _state["last_ok"], "last_error": _state["last_error"], "pushes": _state["pushes"]}
