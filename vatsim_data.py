import os
import time

import pandas as pd
import requests
import streamlit as st

from member_store import MemberStore, classify_status
from security_utils import SlidingWindowLimiter

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_RADAR_AIRLINES_URL = "https://data.vatsim-radar.com/airlines"
VATSPY_DAT_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/VATSpy.dat"
AIRPORTS_CSV = "airports.csv"
EVENTS_URL = "https://my.vatsim.net/api/v2/events/latest"


@st.cache_data(ttl=15, show_spinner=False)
def fetch_feed():
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


@st.cache_data(ttl=600, show_spinner=False)
def fetch_events_raw():
    r = requests.get(EVENTS_URL, timeout=15, headers={"User-Agent": "VatScoreRadar", "Accept": "application/json"})
    r.raise_for_status()  # an exception is never cached, so the next visit simply tries again
    return r.json()


@st.cache_resource(ttl=86400, show_spinner=False)
def load_airports():
    if not os.path.exists(AIRPORTS_CSV):
        return {}
    df = pd.read_csv(AIRPORTS_CSV, usecols=["icao", "name", "city", "country", "elevation", "lat", "lon", "tz"])
    df = df.dropna(subset=["icao", "lat", "lon"])
    df[["name", "city", "country", "tz"]] = df[["name", "city", "country", "tz"]].fillna("")
    airports = {}
    for icao, name, city, country, tz, elev, lat, lon in zip(
            df["icao"], df["name"], df["city"], df["country"], df["tz"], df["elevation"], df["lat"], df["lon"]):
        airports[str(icao).strip().upper()] = {
            "name": name, "city": city, "country": country, "tz": tz,
            "elevation": None if pd.isna(elev) else float(elev), "lat": float(lat), "lon": float(lon),
        }
    return airports


@st.cache_data(ttl=86400, show_spinner=False)
def _load_airport_key_map():
    # Raises on failure so a bad response is never cached for 24h.
    r = requests.get(VATSPY_DAT_URL, timeout=20)
    r.raise_for_status()
    keys, inside = {}, False
    for line in r.text.splitlines():
        text = line.strip()
        if text.startswith("["):
            inside = text == "[Airports]"
            continue
        parts = text.split("|")
        if not inside or not text or text.startswith(";") or len(parts) < 5:
            continue
        icao, code = parts[0].strip().upper(), parts[4].strip().upper()
        for k in {code, code.split("-")[0]}:
            if k:
                keys.setdefault(k, []).append(icao)
    if not keys:
        raise ValueError("no airports")
    return keys


def load_airport_key_map():
    """callsign prefix -> airport ICAOs, from the IATA/LID column of VATSpy.dat (IST_W_APP is LTFM, JFK_TWR is KJFK); {} when unavailable."""
    try:
        return _load_airport_key_map()
    except Exception:
        return {}


@st.cache_resource(ttl=86400, show_spinner=False)
def _load_airlines():
    # Raises on failure so a bad response is never cached for 24h.
    r = requests.get(VATSIM_RADAR_AIRLINES_URL, timeout=10)
    r.raise_for_status()
    airlines = {}
    for item in r.json():
        icao = str(item.get("icao") or "").strip().upper()
        if icao:
            airlines.setdefault(icao, {"name": item.get("name", ""), "callsign": item.get("callsign", ""),
                                       "virtual": bool(item.get("virtual", False))})
    return airlines


def load_airlines():
    try:
        return _load_airlines()
    except Exception:
        return {}


@st.cache_resource
def _member_store():
    # Ratings barely change, so they are kept for 7 days and survive an app restart (file), which keeps us far
    # below VATSIM's 10 requests/minute per IP. The same file remembers an active ban (Retry-After).
    return MemberStore(os.path.join(".cache", "member_ratings.json"))


@st.cache_resource
def _member_api_limiter():
    # Our own cap on top of VATSIM's limit; the CID Stats page shares that budget.
    return SlidingWindowLimiter(6, 60)


def _ident_headers():
    # Like VATSIM-Radar: identify the app. VATSIM issues an ident token to approved developers,
    # set it as VATSIM_IDENT_TOKEN in the secrets; without it a descriptive User-Agent is sent.
    try:
        token = st.secrets.get("VATSIM_IDENT_TOKEN", "")
    except Exception:
        token = ""
    return {"User-Agent": token or "VatScoreRadar/1.0 (+https://github.com/yanwela/vatscore-radar)"}


def _member_error(reason, now, seconds):
    return {"error": True, "reason": reason, "t": now, "retry_at": now + max(0, seconds)}


def fetch_member_rating(cid):
    cid = str(cid)
    now = time.time()
    if not cid.isdigit():
        return _member_error("invalid", now, 3600)
    store = _member_store()
    cached = store.get(cid, now)
    if cached:
        return cached
    if store.is_blocked(now):
        return _member_error("rate_limited", now, store.blocked_until() - now)
    if not _member_api_limiter().allow("member"):
        return _member_error("rate_limited", now, 30)
    try:
        r = requests.get(f"https://api.vatsim.net/v2/members/{cid}", headers=_ident_headers(), timeout=6)
    except requests.Timeout:
        return _member_error("timeout", now, 30)
    except requests.RequestException:
        return _member_error("network", now, 30)
    reason, seconds = classify_status(r.status_code, r.headers.get("Retry-After"))
    if reason == "ok":
        try:
            data = r.json()
        except ValueError:
            return _member_error("vatsim_error", now, 60)
        store.put(cid, data.get("rating"), data.get("pilotrating"), now)
        return {"rating": data.get("rating"), "pilotrating": data.get("pilotrating")}
    if reason == "rate_limited":
        store.block(now + seconds)
    return _member_error(reason, now, seconds)
