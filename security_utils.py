import re
import threading
import time

class SlidingWindowLimiter:
    def __init__(self, max_calls, window_seconds):
        self._max = max_calls
        self._window = window_seconds
        self._history = {}
        self._lock = threading.Lock()

    def allow(self, key, now=None):
        if now is None:
            now = time.monotonic()
        with self._lock:
            lst = self._history.get(key)
            if lst is None:
                lst = []
                self._history[key] = lst
            cutoff = now - self._window
            i = 0
            while i < len(lst) and lst[i] < cutoff:
                i += 1
            if i:
                del lst[:i]
            if len(lst) < self._max:
                lst.append(now)
                return True
            else:
                return False

    def seconds_until_allowed(self, key, now=None):
        if now is None:
            now = time.monotonic()
        with self._lock:
            lst = self._history.get(key)
            if lst is None:
                return 0.0
            cutoff = now - self._window
            i = 0
            while i < len(lst) and lst[i] < cutoff:
                i += 1
            if i:
                valid = lst[i:]
            else:
                valid = lst
            if len(valid) < self._max:
                return 0.0
            oldest = valid[0]
            return max(0.0, (oldest + self._window) - now)

    def usage(self, key, now=None):
        # Read-only: how much of this key's budget is used right now, for a diagnostics panel - never mutates state,
        # so just looking at it can't itself count as a call.
        if now is None:
            now = time.monotonic()
        with self._lock:
            lst = self._history.get(key, [])
            cutoff = now - self._window
            used = sum(1 for t in lst if t >= cutoff)
        return {"used": used, "max": self._max, "window_seconds": self._window}

def is_valid_callsign(value):
    return isinstance(value, str) and re.fullmatch(r'^[A-Z0-9_-]{1,12}$', value) is not None

def is_valid_fir_prefix(value):
    return isinstance(value, str) and re.fullmatch(r'^[A-Z]{1,2}$', value) is not None