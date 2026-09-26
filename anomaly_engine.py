import threading
from datetime import datetime, timezone

import streamlit as st

from airport_elevation import build_index, nearest_elevation
import anomaly_archive_store
from anomaly_rules import anomaly_key, detect_anomalies
from vatsim_data import load_airports

RECENT_S = 2 * 3600
ARCHIVE_AFTER_S = 120  # an anomaly that has been gone this long is over: it goes to the long-term archive


def feed_time(feed):
    # the feed's own clock: two visits inside the same feed update must not count as two passes, and stale data is not a teleport
    try:
        stamp = feed["general"]["update_timestamp"]
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


@st.cache_resource(show_spinner=False)
def _ground_elevation():
    # ground elevation under an aircraft = the elevation of the nearest airport within 30 NM (28,000 airports, grid-indexed once per process)
    index = build_index((a.get("lat"), a.get("lon"), a.get("elevation")) for a in load_airports().values())

    def lookup(lat, lon):
        found = nearest_elevation(index, lat, lon, 30.0)
        return found[0] if found else None

    return lookup


@st.cache_resource
def _engine():
    # one per server process, shared by every visitor's session: the previous snapshot (for jump / frozen checks) and the last 2 hours
    return {"lock": threading.Lock(), "snapshot": {}, "feed_t": 0.0, "started": 0.0, "active": [], "seen": {}}


def update(pilots, feed_t):
    engine = _engine()
    with engine["lock"]:
        if feed_t is None or feed_t <= engine["feed_t"]:
            return
        anomalies, snapshot = detect_anomalies(pilots, engine["snapshot"], feed_t, _ground_elevation())
        engine["snapshot"], engine["feed_t"], engine["active"] = snapshot, feed_t, anomalies
        engine["started"] = engine["started"] or feed_t
        for a in anomalies:
            key = anomaly_key(a)
            record = engine["seen"].get(key)
            if record is None:
                engine["seen"][key] = {"first": feed_t, "last": feed_t, "a": a, "archived": False}
            else:
                record["last"], record["a"], record["archived"] = feed_t, a, False
        closed = []
        for record in engine["seen"].values():
            if not record["archived"] and feed_t - record["last"] >= ARCHIVE_AFTER_S:
                record["archived"] = True
                closed.append((record["a"], record["first"], record["last"]))
        if closed:
            anomaly_archive_store.add_closed(closed)
        engine["seen"] = {k: r for k, r in engine["seen"].items() if r["last"] >= feed_t - RECENT_S}
    anomaly_archive_store.flush()


def snapshot_view():
    # what the table shows: the anomalies of the newest pass (with when each was first seen) and the ones that have since gone away
    engine = _engine()
    with engine["lock"]:
        feed_t = engine["feed_t"]
        active = []
        for a in engine["active"]:
            record = engine["seen"].get(anomaly_key(a))
            active.append({"a": a, "first": record["first"] if record else feed_t, "key": anomaly_key(a)})
        active_keys = {row["key"] for row in active}
        recent = [{"a": r["a"], "first": r["first"], "last": r["last"], "key": k, "ended_now": r["last"] >= feed_t - 30} for k, r in engine["seen"].items() if k not in active_keys]
        recent.sort(key=lambda r: -r["last"])
        records = [{"first": r["first"], "last": r["last"], "severity": r["a"]["severity"], "cid": r["a"]["cid"]} for r in engine["seen"].values()]
        return {"feed_t": feed_t, "started": engine["started"], "active": active, "recent": recent, "records": records}
