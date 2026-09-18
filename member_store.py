import json
import os
import threading

class MemberStore:
    def __init__(self, path=None, ok_ttl=604800):
        self.path = path
        self.ok_ttl = ok_ttl
        self._lock = threading.Lock()
        self._ratings = {}
        self._blocked_until = 0.0
        if path and os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                ratings = data.get("ratings", {})
                if isinstance(ratings, dict):
                    for cid, entry in ratings.items():
                        if isinstance(entry, dict) and "rating" in entry and "pilotrating" in entry and "t" in entry:
                            self._ratings[str(cid)] = {
                                "rating": entry["rating"],
                                "pilotrating": entry["pilotrating"],
                                "t": entry["t"]
                            }
                blocked = data.get("blocked_until", 0.0)
                try:
                    self._blocked_until = float(blocked)
                except (ValueError, TypeError):
                    self._blocked_until = 0.0
            except Exception:
                self._ratings = {}
                self._blocked_until = 0.0

    def get(self, cid, now):
        cid = str(cid)
        entry = self._ratings.get(cid)
        if entry and now - entry["t"] < self.ok_ttl:
            return {"rating": entry["rating"], "pilotrating": entry["pilotrating"]}
        return None

    def put(self, cid, rating, pilotrating, now):
        cid = str(cid)
        self._ratings[cid] = {"rating": rating, "pilotrating": pilotrating, "t": now}
        self.save()

    def blocked_until(self):
        return self._blocked_until

    def is_blocked(self, now):
        return now < self._blocked_until

    def block(self, until):
        self._blocked_until = max(self._blocked_until, until)
        self.save()

    def prune(self, now):
        to_delete = [cid for cid, entry in self._ratings.items() if now - entry["t"] >= self.ok_ttl]
        for cid in to_delete:
            del self._ratings[cid]
        if to_delete:
            self.save()

    def save(self):
        if self.path is None:
            return
        with self._lock:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, 'w') as f:
                    json.dump({"ratings": self._ratings, "blocked_until": self._blocked_until}, f)
                os.replace(tmp, self.path)
            except OSError:
                pass

def classify_status(status_code, retry_after=None):
    if status_code == 200:
        return ("ok", 0)
    if status_code == 404:
        return ("not_found", 86400)
    if status_code == 429:
        if retry_after is not None and str(retry_after).strip().isdigit():
            retry_seconds = int(retry_after)
        else:
            retry_seconds = 180
        return ("rate_limited", retry_seconds)
    if status_code >= 500:
        return ("vatsim_error", 60)
    return ("http_error", 60)