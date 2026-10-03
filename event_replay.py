import os

import requests
import streamlit as st

from airport_layout_cache import is_retrying, load_airport_layout
from atc_replay_data import build_atc_replay
from atc_replay_view import atc_replay_document
from event_traffic_store import api_key
from security_utils import SlidingWindowLimiter
from vatsim_data import load_airports

FLIGHT_LIMIT = 40  # one fresh replay = 1 list request + up to this many track requests on the shared StatSim key


def replay_session(key, name, icao, window, airport):
    """The stand-in 'controller session' the ATC replay plays for an event: tower view of one airport over the measured window; None when unusable."""
    code = str(icao or "").strip().upper()
    if len(code) != 4 or not code.isalnum() or not key:
        return None
    try:
        on, off = float(window[0]), float(window[1])
        lat, lon = float(airport["lat"]), float(airport["lon"])
        elevation = float(airport.get("elevation") or 0)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return None
    if not off > on:
        return None
    title = " ".join(str(name or "").split())[:60] or "Event"
    return {"id": f"ev-{key}-{code}", "callsign": title, "role": "TWR", "icao": code, "on": on, "off": off, "name": str(airport.get("name") or ""),
            "lat": lat, "lon": lon, "elevation": elevation}


@st.cache_resource
def _http():
    return requests.Session()


@st.cache_resource
def _limiters():
    return SlidingWindowLimiter(4, 60), SlidingWindowLimiter(12, 60)


@st.cache_resource
def _loaded():
    # ids of the replays already in the cache below: showing one again costs no StatSim request, so it is not limited
    return set()


@st.cache_data(ttl=86400, max_entries=16, show_spinner=False)
def _payload(sess):
    payload = build_atc_replay(sess, api_key(), _http(), limit=FLIGHT_LIMIT)
    if payload is None:
        raise RuntimeError("statsim.net failed")  # an exception is never cached, so the visitor can simply try again
    payload["session"]["kind"] = "event"
    return payload


def render_event_replay(rec, traffic_rec):
    airports = traffic_rec.get("airports") or {}
    window = traffic_rec.get("window")
    if not airports or not window or not api_key():
        return
    busiest = max(airports, key=lambda a: airports[a].get("dep", 0) + airports[a].get("arr", 0))
    st.markdown("**Replay**")
    st.caption(f"Plays back the aircraft around one airport during the event, with the airport layout: up to {FLIGHT_LIMIT} flights, the ones closest to the middle of the window. "
               "Only flights with a recorded track can be drawn.")
    icao = busiest
    if len(airports) > 1:
        icao = st.selectbox("Airport", list(airports), index=list(airports).index(busiest), key=f"evrep_ap_{rec['key']}")
    open_key = f"{rec['key']}|{icao}"
    if st.button("Load the replay", key=f"evrep_btn_{open_key}"):
        st.session_state["ev_replay_open"] = open_key
    if st.session_state.get("ev_replay_open") != open_key:
        return
    airport = load_airports().get(icao)
    sess = replay_session(rec["key"], rec.get("name"), icao, window, airport or {})
    if sess is None:
        st.info("This airport is not in the airport list, so it cannot be replayed.")
        return
    if sess["id"] not in _loaded():
        per_visitor, overall = _limiters()
        visitor = st.session_state.setdefault("_limiter_key", os.urandom(8).hex())
        if not per_visitor.allow(visitor):
            st.warning(f"You opened several new replays in a short time. Try again in {int(per_visitor.seconds_until_allowed(visitor)) + 1}s (replays you already opened are not limited).")
            return
        if not overall.allow("global"):
            st.warning(f"The service is busy right now. Try again in {int(overall.seconds_until_allowed('global')) + 1}s.")
            return
    with st.spinner("Loading the flights of this event from statsim.net…"):
        try:
            payload = _payload(sess)
        except Exception:
            payload = None
    if payload is None:
        st.session_state.pop("ev_replay_open", None)  # a failed load must not stay "open"
        st.warning("statsim.net could not be reached right now. Try again in a moment.")
        return
    _loaded().add(sess["id"])
    if not payload["flights"]:
        st.info("statsim.net has no recorded track for the flights of this event, so there is nothing to draw. Tracks are only kept for a pilot's last 60 flights.")
    with st.spinner("Loading the airport layout (taxiways, stands)…"):
        layout = load_airport_layout(icao, sess["lat"], sess["lon"], _http())
    layout_state = "ready" if layout is not None else ("retrying" if is_retrying(icao) else "failed")
    st.iframe(atc_replay_document({**payload, "layout": layout, "layoutState": layout_state}), height=800)
