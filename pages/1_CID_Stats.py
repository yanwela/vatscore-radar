import math
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from html import escape as html_escape

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from security_utils import SlidingWindowLimiter
from ui_theme import page_url, set_browser_title
from cid_panels import render_activity_panels
from flight_connections import group_connections, merge_tracks
from flight_replay_data import callsigns_in, fetch_flight_track, flight_label, flights_for_callsign
from flight_replay_view import replay_document
from atc_area_data import build_area_replay
from atc_area_sessions import area_sessions
from atc_replay_data import build_atc_replay
from atc_replay_view import atc_replay_document
from atc_sessions import replay_sessions
from replay_atc_data import (FIR_ALIAS_NAMES, FIR_ALIASES, fetch_atc_sessions, load_fir_index, load_fir_names, load_fir_prefixes, load_uirs,
                             replay_atc_entries)
from vatsim_data import load_airport_key_map, load_airports

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
STATSIM_API = "https://api.statsim.net/api"
VATSIM_CORE = "https://api.vatsim.net/v2"
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_RADAR_AIRLINES_URL = "https://data.vatsim-radar.com/airlines"
AIRPORTS_CSV = "airports.csv"

# statsim.net only accepts a max 31-day range per request (anything longer
# returns 400), so the full history is split into 30-day chunks and fetched
# in parallel.
CHUNK_DAYS = 30
MAX_LOOKBACK_YEARS = 4  # safety ceiling on request count for very old accounts

# Per vatsim.dev's official rating table: OBS starts at 1, not 0 (0 is Suspended),
# so every tier is shifted up by one from what you'd naively guess.
ATC_RATINGS = {
    -1: "Inactive", 0: "Suspended", 1: "OBS", 2: "S1", 3: "S2", 4: "S3",
    5: "C1", 6: "C2", 7: "C3", 8: "I1", 9: "I2", 10: "I3", 11: "SUP", 12: "ADM",
}
MILITARY_RATINGS = {0: "None", 1: "M1", 2: "M2", 3: "M3"}

INK, PANEL, LINE = "#0a0e1a", "#10141f", "#1f2937"
SUBTLE, TEXT = "#5b6b82", "#e8eef7"
CYAN, VIOLET, AMBER, EMERALD, ROSE = "#22d3ee", "#8b5cf6", "#fbbf24", "#34d399", "#fb7185"
PLOTLY_FONT = dict(family="ui-monospace, 'Cascadia Code', monospace", color=TEXT, size=11)

_MFR_PREFIXES = [
    ("Airbus", ("A18", "A19", "A20", "A21", "A22", "A30", "A31", "A32", "A33", "A34", "A35", "A38")),
    ("Boeing", ("707", "717", "727", "737", "747", "757", "767", "777", "787",
                "B70", "B71", "B72", "B73", "B74", "B75", "B76", "B77", "B78", "B38", "B39")),
    ("Embraer", ("E11", "E12", "E13", "E14", "E17", "E19", "E29", "E45", "E50", "E55", "E70", "E75", "ERJ")),
    ("Bombardier", ("BD1", "CL6", "CR1", "CR2", "CR7", "CR9", "CRJ",
                     "DH1", "DH2", "DH3", "DH4", "DH8", "DHC", "GL5", "GL6", "GL7", "GLF", "Q40")),
    ("ATR", ("AT4", "AT5", "AT7", "AT8")),
    ("Cessna", ("C17", "C20", "C21", "C25", "C42", "C50", "C51", "C52", "C55", "C56", "C68", "C72", "C75", "C82")),
    ("Piper", ("P28", "P32", "PA2", "PA3", "PA4", "PA6")),
    ("Cirrus", ("SR2", "S22")),
    ("Diamond", ("DA4", "DA6", "DA2", "DA7", "DV2")),
    ("McDonnell Douglas", ("MD8", "MD9", "MD1", "DC8", "DC9", "DC1")),
    ("Lockheed", ("C13", "C5M", "L10", "C30")),
    ("Beechcraft", ("BE2", "BE3", "BE4", "BE5", "BE6", "BE9", "B190", "BE10", "BE20", "BE40", "BE58", "BE60", "B350")),
    ("Pilatus", ("PC12", "PC24", "PC6", "PC7", "PC9")),
    ("Sukhoi", ("SU9", "SU95")),
]

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def get_secret(key, default=""):
    # st.secrets.get() raises instead of falling back to default when no
    # secrets.toml exists at all. That would crash the whole page, so catch it.
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


STATSIM_API_KEY = get_secret("STATSIM_API_KEY", "")
http = requests.Session()


def decode_pilot_rating(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return "P0"
    if v >= 63: return "P6 · Ferry"
    if v >= 31: return "P5 · CTP"
    if v >= 15: return "P4 · ATP"
    if v >= 7:  return "P3 · CMEL"
    if v >= 3:  return "P2 · IR"
    if v >= 1:  return "P1 · PPL"
    return "P0 · New"


def decode_atc_rating(v):
    try:
        return ATC_RATINGS.get(int(v), f"R{v}")
    except (TypeError, ValueError):
        return "OBS"


def decode_military_rating(v):
    try:
        return MILITARY_RATINGS.get(int(v), "None")
    except (TypeError, ValueError):
        return "None"


def icao_type(raw):
    if not raw:
        return "ZZZZ"
    return str(raw).split("/")[0].strip().upper() or "ZZZZ"


def manufacturer_of(icao):
    t = str(icao).upper()
    for name, prefixes in _MFR_PREFIXES:
        if t.startswith(prefixes):
            return name
    if t.startswith("A"): return "Airbus"
    if t.startswith("B"): return "Boeing"
    return "Other"


def fmt_hm(minutes):
    try:
        m = int(round(float(minutes)))
    except (TypeError, ValueError):
        m = 0
    if m < 60:
        return f"{m} min"
    return f"{m // 60}h {m % 60:02d}m"


def haversine_nm(lat1, lon1, lat2, lon2):
    r = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c * 0.539957


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _chunk_windows(start, end, days=CHUNK_DAYS):
    windows, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        windows.append((cur, nxt))
        cur = nxt
    return windows


def _statsim_headers():
    return {"X-API-Key": STATSIM_API_KEY, "accept": "application/json", "User-Agent": "VatScore/4.0"}


def _fetch_chunk_raw(endpoint, cid, from_iso, to_iso):
    url = f"{STATSIM_API}/{endpoint}/VatsimId?vatsimId={cid}&from={from_iso}&to={to_iso}"
    try:
        r = http.get(url, headers=_statsim_headers(), timeout=25)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
        if r.status_code == 404:
            return []  # no records in this window, not an error
        return {"__error__": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"__error__": str(e)}


# Closed (past) windows are immutable -> safe to cache for a long time.
# The window containing "now" can gain new records at any moment -> short TTL.
@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_chunk_closed(endpoint, cid, from_iso, to_iso):
    return _fetch_chunk_raw(endpoint, cid, from_iso, to_iso)


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_chunk_recent(endpoint, cid, from_iso, to_iso):
    return _fetch_chunk_raw(endpoint, cid, from_iso, to_iso)


def fetch_history(endpoint, cid, since_dt):
    """Splits history into 30-day windows (statsim.net's 31-day cap) and fetches
    them in parallel. Returns (results, truncated, error_count)."""
    now = datetime.now(timezone.utc)
    lookback_floor = now - timedelta(days=365 * MAX_LOOKBACK_YEARS)
    truncated = bool(since_dt and since_dt < lookback_floor)
    start = since_dt if (since_dt and since_dt > lookback_floor) else lookback_floor

    windows = _chunk_windows(start, now)
    results, errors = [], 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {}
        for w_start, w_end in windows:
            fn = _fetch_chunk_closed if w_end < now - timedelta(days=1) else _fetch_chunk_recent
            futures[ex.submit(fn, endpoint, cid, _iso(w_start), _iso(w_end))] = (w_start, w_end)
        for fut in as_completed(futures):
            chunk = fut.result()
            if isinstance(chunk, dict) and "__error__" in chunk:
                errors += 1
                continue
            results.extend(chunk)
    return results, truncated, errors


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_member_details(cid):
    try:
        r = http.get(f"{VATSIM_CORE}/members/{cid}", timeout=10)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_member_stats(cid):
    try:
        r = http.get(f"{VATSIM_CORE}/members/{cid}/stats", timeout=10)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


@st.cache_data(ttl=20, show_spinner=False)
def fetch_live_pilot(cid):
    try:
        r = http.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            for p in r.json().get("pilots", []):
                if str(p.get("cid", "")) == cid:
                    return p
    except Exception:
        pass
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def load_airport_coords():
    coords = {}
    if os.path.exists(AIRPORTS_CSV):
        try:
            df = pd.read_csv(AIRPORTS_CSV)
            df.columns = [c.lower().strip() for c in df.columns]
            lat_col = "lat" if "lat" in df.columns else "latitude_deg"
            lon_col = "lon" if "lon" in df.columns else "longitude_deg"
            for _, row in df.iterrows():
                icao = str(row.get("icao", "")).upper().strip()
                if not icao:
                    continue
                try:
                    coords[icao] = (float(row[lat_col]), float(row[lon_col]))
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
    return coords


@st.cache_data(ttl=86400, show_spinner=False)
def load_airlines_db():
    airlines = {}
    try:
        r = http.get(VATSIM_RADAR_AIRLINES_URL, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                icao = item.get("icao")
                # The list often holds only a virtual airline for big carriers ("vTHY"); leave those out so the page falls
                # back to the plain ICAO code instead of showing a virtual airline's name as if it were the real one.
                if icao and not item.get("virtual"):
                    airlines[icao.upper().strip()] = item.get("name", "Unknown Airline")
    except Exception:
        pass
    return airlines


def callsign_prefix(callsign):
    import re
    m = re.match(r"^[A-Z]+", str(callsign).upper())
    return m.group(0) if m else ""


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE / STYLE
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="VatScoreRadar — CID Stats", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")

st.markdown(f"""
<style>
[data-testid="stAppViewContainer"], [data-testid="stApp"] {{ background-color: {INK} !important; }}
[data-testid="stSidebarNav"] {{ display: none !important; }}
[data-testid="stSidebar"] {{ display: none !important; }}
h1, h2, h3 {{ color: {CYAN} !important; font-family: 'Segoe UI', sans-serif; }}
.vs-wrap {{ font-family: ui-monospace, 'Cascadia Code', 'SF Mono', monospace; }}
.vs-eyebrow {{ font-size:11px; letter-spacing:3px; text-transform:uppercase; color:{SUBTLE}; font-weight:700; margin:0 0 2px 0; }}
.vs-h {{ font-size:15px; font-weight:700; color:{TEXT}; letter-spacing:.5px; margin:22px 0 10px 0; display:flex; align-items:center; gap:8px; }}
.vs-h::before {{ content:""; width:3px; height:16px; background:{CYAN}; display:inline-block; border-radius:2px; }}
.vs-card {{ background:{PANEL}; border:1px solid {LINE}; border-radius:10px; padding:16px 18px; }}
.vs-kpi-label {{ font-size:10px; letter-spacing:1.5px; text-transform:uppercase; color:{SUBTLE}; font-weight:700; }}
.vs-kpi-val {{ font-size:24px; font-weight:800; line-height:1.1; margin-top:6px; font-variant-numeric:tabular-nums; }}
.vs-kpi-sub {{ font-size:11px; color:{SUBTLE}; margin-top:4px; }}
.vs-chip {{ display:inline-block; padding:6px 14px; border-radius:8px; font-size:12px; font-weight:700; letter-spacing:.5px; font-family:monospace; text-align:center; }}
.vs-route {{ display:flex; justify-content:space-between; align-items:center; padding:9px 14px; border-radius:7px; margin-bottom:6px; background:{INK}; border:1px solid {LINE}; }}
.vs-route .ap {{ font-size:14px; font-weight:700; letter-spacing:1px; }}
</style>
""", unsafe_allow_html=True)

set_browser_title("CID Stats")
st.page_link("app.py", label="Back to Live Radar", icon="⬅️")
st.title("📊 CID Stats")

# ?cid=123 in the URL pre-fills the lookup, so a CID page can be linked and shared.
_cid_param = st.query_params.get("cid", "")
if _cid_param.isdigit() and len(_cid_param) <= 10 and "cid_stats_input" not in st.session_state:
    st.session_state["cid_stats_input"] = _cid_param

cid_input = st.text_input("VATSIM CID", placeholder="e.g. 1863530", max_chars=10,
                           key="cid_stats_input", label_visibility="collapsed")

if not (cid_input and cid_input.strip().isdigit()):
    st.info("Enter a VATSIM CID to pull the full flight and ATC history from statsim.net.")
    st.stop()

if not STATSIM_API_KEY:
    st.error("STATSIM_API_KEY is not set. Add it to `.streamlit/secrets.toml` and reload the page.")
    st.stop()

cid = cid_input.strip()
if st.query_params.get("cid") != cid:
    st.query_params["cid"] = cid


@st.cache_resource
def _lookup_limiters():
    # Every new CID fans out to dozens of statsim.net requests on the shared
    # API key, so cap fresh lookups per session and across the whole app.
    return SlidingWindowLimiter(8, 60), SlidingWindowLimiter(40, 60)


# Widget interactions (sliders, radios) rerun this script with the same CID and
# are served from cache, so only a CID we haven't just looked up counts.
if st.session_state.get("_cid_last_ok") != cid:
    session_limiter, global_limiter = _lookup_limiters()
    session_key = st.session_state.setdefault("_limiter_key", os.urandom(8).hex())
    if not session_limiter.allow(session_key):
        wait = int(session_limiter.seconds_until_allowed(session_key)) + 1
        st.warning(f"Too many lookups. Try again in {wait}s.")
        st.stop()
    if not global_limiter.allow("global"):
        wait = int(global_limiter.seconds_until_allowed("global")) + 1
        st.warning(f"The service is busy right now. Try again in {wait}s.")
        st.stop()
    st.session_state["_cid_last_ok"] = cid

# ══════════════════════════════════════════════════════════════════════════════
#  DATA FETCH
# ══════════════════════════════════════════════════════════════════════════════
with st.spinner("Fetching full history (statsim.net + VATSIM Core)…"):
    details = fetch_member_details(cid)
    mstats = fetch_member_stats(cid)
    live = fetch_live_pilot(cid)

    reg_date = None
    if details.get("reg_date"):
        parsed = pd.to_datetime(details["reg_date"], utc=True, errors="coerce")
        if pd.notna(parsed):
            reg_date = parsed.to_pydatetime()

    flights_raw, flights_truncated, flights_err = fetch_history("Flights", cid, reg_date)
    atc_raw, atc_truncated, atc_err = fetch_history("Atcsessions", cid, reg_date)

if not details and not flights_raw and not atc_raw and not live:
    st.warning(f"No data found for CID {cid}. Double-check the CID.")
    st.stop()

airport_coords = load_airport_coords()
airlines_db = load_airlines_db()

# ── Flight DataFrame ───────────────────────────────────────────────────────
df = pd.DataFrame(flights_raw) if flights_raw else pd.DataFrame(
    columns=["callsign", "departure", "destination", "aircraft", "departed", "arrived", "loggedOn"])
if len(df):
    df["dep"] = df.get("departure", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.strip()
    df["arr"] = df.get("destination", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.strip()
    df["ac"] = df.get("aircraft", pd.Series(dtype=str)).apply(icao_type)
    df["mfr"] = df["ac"].apply(manufacturer_of)
    df["cs_prefix"] = df.get("callsign", pd.Series(dtype=str)).fillna("").apply(callsign_prefix)
    df["route"] = df["dep"] + "→" + df["arr"]
    df["departed_dt"] = pd.to_datetime(df.get("departed"), utc=True, errors="coerce")
    df["arrived_dt"] = pd.to_datetime(df.get("arrived"), utc=True, errors="coerce")
    df["logon_dt"] = pd.to_datetime(df.get("loggedOn"), utc=True, errors="coerce")
    df["when"] = df["departed_dt"].fillna(df["logon_dt"])
    dur = (df["arrived_dt"] - df["departed_dt"]).dt.total_seconds() / 60
    df["dur_min"] = dur.where(dur > 0).fillna(0)

    def _dist(row):
        p1, p2 = airport_coords.get(row["dep"]), airport_coords.get(row["arr"])
        if p1 and p2:
            return haversine_nm(p1[0], p1[1], p2[0], p2[1])
        return None

    df["distance_nm"] = df.apply(_dist, axis=1)

has_flights = len(df) > 0
has_valid_routes = has_flights and (df["route"] != "→").any()

# ══════════════════════════════════════════════════════════════════════════════
#  PROFILE CARD
# ══════════════════════════════════════════════════════════════════════════════
live_name = live.get("name") if live else None
display_name = html_escape(live_name) if live_name else f"CID {cid}"

pilot_rating_raw = (live or {}).get("pilot_rating", details.get("pilotrating", 0))
atc_rating_raw = (live or {}).get("rating", details.get("rating", 0))
mil_rating_raw = details.get("militaryrating", 0)

pilot_label = decode_pilot_rating(pilot_rating_raw)
atc_label = decode_atc_rating(atc_rating_raw)
mil_label = decode_military_rating(mil_rating_raw)

online_badge = ""
if live:
    cs = html_escape(str(live.get("callsign", "")))
    online_badge = (f'<span class="vs-chip" style="background:#062e25;color:{EMERALD};'
                     f'border:1px solid #0c5;margin-left:10px;vertical-align:middle;">● LIVE · {cs}</span>')

region = html_escape(str(details.get("region_id", "—")))
division = html_escape(str(details.get("division_id", "—")))
reg_date_str = reg_date.strftime("%d.%m.%Y") if reg_date else "—"

REPLAY_LAST_FLIGHTS = 60  # statsim only keeps the recorded track of a pilot's most recent 60 flights
replay_open = st.query_params.get("replay") == "1"
replay_chip = ""
# ATC replay: only for members who hold an ATC rating (S1 and above; 1 = OBS, 0 = suspended)
atc_rating_int = atc_rating_raw if isinstance(atc_rating_raw, int) else 0


@st.cache_resource(ttl=86400, show_spinner=False)
def _fir_index():
    return load_fir_index()


@st.cache_data(ttl=86400, show_spinner=False)
def _fir_prefix_lookup():
    # callsign prefix -> boundary ids. First VATSpy.dat [FIRs] (NAT_I_FSS -> NAT, LON_SC_CTR -> EGTT, HOU_46_CTR -> KZHU), then the ids of
    # Boundaries.geojson itself (a prefix that is a boundary id, or the base of "EDGG-N"), then the upper airspaces without a boundary (EDUU).
    inverse = {}
    for boundary, keys in load_fir_prefixes().items():
        for key in list(keys) + [boundary]:
            inverse.setdefault(key, set()).add(boundary)
    from_geojson = {}
    for fir in _fir_index():
        for key in {fir["id"], fir["id"].split("-")[0]}:
            from_geojson.setdefault(key, set()).add(fir["id"])
    for key, ids in from_geojson.items():
        inverse.setdefault(key, ids)
    known = {fir["id"] for fir in _fir_index()}
    for uir, (_name, members) in load_uirs().items():
        # a member is a boundary id ("BIRD-E") or a FIR code ("FLFI") that VATSpy.dat maps to its boundary
        ids = set()
        for member in members:
            ids |= set(inverse.get(member, ())) or ({member} if member in known else set())
        if ids:
            inverse.setdefault(uir, ids)
    for alias, targets in FIR_ALIASES.items():
        ids = {t for t in targets if t in known}
        if ids:
            inverse.setdefault(alias, ids)
    return {key: sorted(ids) for key, ids in inverse.items()}


@st.cache_data(ttl=86400, show_spinner=False)
def _fir_display_names():
    return {**load_fir_names(), **{uir: name for uir, (name, _m) in load_uirs().items()}, **FIR_ALIAS_NAMES}


atc_replay_sessions = []
if atc_rating_int >= 2:
    atc_replay_sessions = replay_sessions(atc_raw, load_airport_key_map(), load_airports())
    try:
        atc_replay_sessions += area_sessions(atc_raw, _fir_prefix_lookup(), _fir_display_names())
    except Exception:
        pass  # the airport positions still work without the VATSpy tables
    atc_replay_sessions.sort(key=lambda s: s["on"], reverse=True)
atc_replay_open = st.query_params.get("atcreplay") == "1" and atc_rating_int >= 2
atc_replay_chip = ""
if atc_rating_int >= 2:
    _atc_href = f"?cid={cid}" if atc_replay_open else f"?cid={cid}&atcreplay=1"
    _atc_bg, _atc_border = ("#3a2a08", AMBER) if atc_replay_open else ("#2a1f06", f"{AMBER}40")
    atc_replay_chip = (f'<a class="vs-chip" href="{_atc_href}" target="_self" style="background:{_atc_bg};color:{AMBER};'
                       f'border:1px solid {_atc_border};text-decoration:none;">&#9654;&nbsp;ATC&nbsp;REPLAY<br>'
                       f'<span style="font-size:15px;">{len(atc_replay_sessions):,}&nbsp;Sessions</span></a>')
if has_flights:
    _replay_href = f"?cid={cid}" if replay_open else f"?cid={cid}&replay=1"
    # the label stays "Flight Replay"; while the replay is open the chip is lit up and a click on it closes the replay again
    _replay_bg, _replay_border = ("#0a4a38", EMERALD) if replay_open else ("#062e25", f"{EMERALD}40")
    _replay_count = f"Last&nbsp;{REPLAY_LAST_FLIGHTS}&nbsp;Flights" if len(df) > REPLAY_LAST_FLIGHTS else f"{len(df):,}&nbsp;Flights"
    replay_chip = (f'<a class="vs-chip" href="{_replay_href}" target="_self" style="background:{_replay_bg};color:{EMERALD};'
                   f'border:1px solid {_replay_border};text-decoration:none;">&#9654;&nbsp;FLIGHT&nbsp;REPLAY<br>'
                   f'<span style="font-size:15px;">{_replay_count}</span></a>')

st.markdown(f"""
<div class="vs-wrap vs-card" style="border-left:4px solid {CYAN};margin-bottom:18px;
     background:linear-gradient(135deg,{PANEL} 0%,{INK} 100%);">
  <div style="font-size:25px;font-weight:800;color:{TEXT};margin-bottom:3px;">{display_name}{online_badge}</div>
  <div style="font-size:12px;color:{SUBTLE};margin-bottom:16px;">
    CID {cid} &nbsp;·&nbsp; {region}/{division} &nbsp;·&nbsp; Registered {reg_date_str}
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;">
    <div class="vs-chip" style="background:#1e1633;color:{VIOLET};border:1px solid {VIOLET}40;">
      MILITARY&nbsp;RATING<br><span style="font-size:15px;">{mil_label}</span>
    </div>
    <div class="vs-chip" style="background:#0c2a3a;color:{CYAN};border:1px solid {CYAN}40;">
      PILOT&nbsp;RATING<br><span style="font-size:15px;">{pilot_label}</span>
    </div>
    <div class="vs-chip" style="background:#1e1633;color:{VIOLET};border:1px solid {VIOLET}40;">
      ATC&nbsp;RATING<br><span style="font-size:15px;">{atc_label}</span>
    </div>
    {replay_chip}
    {atc_replay_chip}
  </div>
</div>
""", unsafe_allow_html=True)

if flights_truncated or flights_err or atc_err:
    notes = []
    if flights_truncated:
        notes.append(f"history limited to the last {MAX_LOOKBACK_YEARS} years (account is older)")
    if flights_err:
        notes.append(f"{flights_err} flight time window(s) failed to fetch")
    if atc_err:
        notes.append(f"{atc_err} ATC time window(s) failed to fetch")
    st.caption("⚠️ " + "; ".join(notes) + ". Data may be incomplete.")

# ══════════════════════════════════════════════════════════════════════════════
#  FLIGHT REPLAY (opened with the chip in the profile card: ?replay=1)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def _replay_limiters():
    # one fetch per newly picked flight; reruns of the same pick are served from the cache below
    return SlidingWindowLimiter(12, 60), SlidingWindowLimiter(60, 60)


@st.cache_data(ttl=86400, show_spinner=False)
def _replay_track_closed(flight_id):
    # a finished flight never changes
    return fetch_flight_track(flight_id, STATSIM_API_KEY, http)


@st.cache_data(ttl=60, show_spinner=False)
def _replay_track_open(flight_id):
    return fetch_flight_track(flight_id, STATSIM_API_KEY, http)


@st.cache_data(ttl=86400, show_spinner=False)
def _fir_prefixes():
    return load_fir_prefixes()


def _replay_atc_compute(points, dep, arr):
    sessions = fetch_atc_sessions(points[0][3], points[-1][3], STATSIM_API_KEY, http)
    if sessions is None:
        return None
    airports = load_airports()
    airport_points = {i: (airports[i]["lat"], airports[i]["lon"]) for i in {dep.upper(), arr.upper()} if i in airports}
    return replay_atc_entries(points, dep, arr, sessions, load_airport_key_map(), _fir_index(), _fir_prefixes(), airport_points)


@st.cache_data(ttl=86400, show_spinner=False)
def _replay_atc_closed(ids, dep, arr, t_from, t_to, _points):
    return _replay_atc_compute(_points, dep, arr)


@st.cache_data(ttl=120, show_spinner=False)
def _replay_atc_open(ids, dep, arr, t_from, t_to, _points):
    return _replay_atc_compute(_points, dep, arr)


def render_flight_replay():
    st.markdown('<div class="vs-h" id="flight-replay">Flight Replay</div>', unsafe_allow_html=True)
    recent = sorted((f for f in flights_raw if isinstance(f, dict)), key=lambda f: str(f.get("loggedOn") or ""), reverse=True)[:REPLAY_LAST_FLIGHTS] if has_flights else []
    known = callsigns_in(recent)
    if not known:
        st.info("No flights found for this CID on statsim.net, so there is nothing to replay.")
        return
    st.caption(f"statsim.net keeps the recorded track of the last {REPLAY_LAST_FLIGHTS} flights only.")
    live_cs = str((live or {}).get("callsign", "")).upper()
    linked_cs = str(st.query_params.get("callsign", "")).strip().upper()
    start_cs = linked_cs or (live_cs if live_cs in known else known[0])
    options = known if start_cs in known else [start_cs] + known  # a linked callsign that is not in the list stays selectable
    col_cs, col_flight = st.columns([1, 2])
    with col_cs:
        picked = st.selectbox("Callsign", options, index=options.index(start_cs), accept_new_options=True, key="replay_callsign",
                              placeholder="Select or type a callsign")
    typed = str(picked or "").strip().upper()
    if not typed:
        st.info("Pick a callsign from the list or type one.")
        return
    matches = flights_for_callsign(recent, typed)
    if not matches:
        if flights_for_callsign(flights_raw, typed):
            st.info(f"Callsign {typed} has no flight among the last {REPLAY_LAST_FLIGHTS}, and statsim.net only keeps the track of those.")
        else:
            st.warning(f"Callsign {typed} was not found in this CID's flights.")
        return
    # one real flight can be recorded as several connections (disconnected in flight, logged on again): show it once
    groups = group_connections(matches)
    labels = [flight_label(g["flight"]) + (f"  ·  {g['connections']} connections" if g["connections"] > 1 else "")
              + ("  ·  in progress" if not g["flight"]["arrived"] else "") for g in groups]
    linked_flight = str(st.query_params.get("flight", ""))
    linked_idx = next((i for i, g in enumerate(groups) if linked_flight in g["ids"]), 0)
    with col_flight:
        idx = st.selectbox("Flight", range(len(groups)), format_func=lambda i: labels[i], key=f"replay_flight_{typed}", index=linked_idx)
    group = groups[idx]
    chosen = {"id": group["ids"][0], "arrived": group["flight"]["arrived"], "departure": group["flight"]["departure"],
              "destination": group["flight"]["destination"]}
    if st.query_params.get("callsign") != typed:
        st.query_params["callsign"] = typed
    if st.query_params.get("flight") != chosen["id"]:
        st.query_params["flight"] = chosen["id"]

    if st.session_state.get("_replay_last") != chosen["id"]:
        session_limiter, global_limiter = _replay_limiters()
        session_key = st.session_state.setdefault("_limiter_key", os.urandom(8).hex())
        if not session_limiter.allow(session_key) or not global_limiter.allow("global"):
            st.warning("Too many replays in a short time. Try again in a minute.")
            return
        st.session_state["_replay_last"] = chosen["id"]
    with st.spinner("Loading the flight track from statsim.net…"):
        results = []
        for n, fid in enumerate(group["ids"]):
            # an earlier connection is finished for good; only the last one can still be running
            is_last = n == len(group["ids"]) - 1
            results.append((_replay_track_closed if (not is_last or chosen["arrived"]) else _replay_track_open)(fid))
    good = [r for r in results if r["ok"]]
    if not good:
        reason = results[0].get("reason")
        if reason in ("not_found", "no_positions"):
            st.warning("statsim.net has no recorded track for this flight.")
        else:
            st.warning("The flight track could not be loaded right now. Try again in a moment.")
        return
    if len(good) < len(results):
        st.caption("One of the connections of this flight has no recorded track; the replay shows the rest.")
    result = {"points": merge_tracks([r["points"] for r in good]), "flight": {**good[0]["flight"], **group["flight"]}}
    airports = load_airports()
    known_airports = {}
    for icao in {chosen["departure"].upper(), chosen["destination"].upper()}:
        a = airports.get(icao)
        if a:
            known_airports[icao] = {"latitude_deg": a["lat"], "longitude_deg": a["lon"], "name": a["name"]}
    atc = None
    try:
        with st.spinner("Loading the controllers that were online…"):
            pts = result["points"]
            fn = _replay_atc_closed if chosen["arrived"] else _replay_atc_open
            atc = fn(tuple(group["ids"]), chosen["departure"], chosen["destination"], pts[0][3], pts[-1][3], pts)
    except Exception:
        atc = None  # the replay itself works without the ATC list
    payload = {"points": result["points"], "flight": result["flight"], "airports": known_airports, "cid": cid,
               "airportUrl": page_url("Airport"), "atc": atc}
    st.iframe(replay_document(payload), height=770)


@st.cache_resource
def _atc_replay_limiters():
    # one FRESH ATC replay = 1 list request + up to 30 track requests on the shared API key, so this budget is tight
    return SlidingWindowLimiter(5, 60), SlidingWindowLimiter(15, 60)


@st.cache_resource
def _atc_replay_loaded():
    # ids of the sessions whose payload is already in the cache below: showing one again costs no statsim.net request, so it is not limited
    return set()


@st.cache_data(ttl=86400, show_spinner=False)
def _atc_replay_payload(session_key, sess):
    if sess.get("kind") == "area":
        payload = build_area_replay(sess, STATSIM_API_KEY, http, _fir_index(), load_airports())
    else:
        payload = build_atc_replay(sess, STATSIM_API_KEY, http)
    if payload is None:
        raise RuntimeError("statsim.net failed")  # an exception is never cached, so the user can simply try again
    return payload


def render_atc_replay():
    st.markdown('<div class="vs-h" id="atc-replay">ATC Replay</div>', unsafe_allow_html=True)
    if not atc_replay_sessions:
        st.info("No controller sessions (DEL, GND, TWR, APP with a known airport, or CTR / FSS with a known airspace) were found for this CID on statsim.net.")
        return
    st.caption("Plays back the traffic one controller position worked: pick a session. Only aircraft that belong to the position are shown "
               "(ground positions on the airport layout, CTR / FSS in their VATSpy airspace); flights appear a little before they enter and stay a little after they leave.")
    linked = str(st.query_params.get("atcsession", ""))
    ids = [s["id"] for s in atc_replay_sessions]
    idx = st.selectbox("Session", range(len(ids)), format_func=lambda i: atc_replay_sessions[i]["label"], key="atc_replay_session",
                       index=ids.index(linked) if linked in ids else 0)
    chosen = atc_replay_sessions[idx]
    if st.query_params.get("atcsession") != chosen["id"]:
        st.query_params["atcsession"] = chosen["id"]
    loaded = _atc_replay_loaded()
    if chosen["id"] not in loaded and st.session_state.get("_atc_replay_last") != chosen["id"]:
        session_limiter, global_limiter = _atc_replay_limiters()
        session_key = st.session_state.setdefault("_limiter_key", os.urandom(8).hex())
        if not session_limiter.allow(session_key):
            wait = int(session_limiter.seconds_until_allowed(session_key)) + 1
            st.warning(f"You opened several new ATC replays in a short time. Try again in {wait}s (sessions you already opened are not limited).")
            return
        if not global_limiter.allow("global"):
            wait = int(global_limiter.seconds_until_allowed("global")) + 1
            st.warning(f"The service is busy right now. Try again in {wait}s.")
            return
        st.session_state["_atc_replay_last"] = chosen["id"]
    with st.spinner("Loading the traffic of this session from statsim.net…"):
        try:
            payload = _atc_replay_payload(chosen["id"], chosen)
        except Exception:
            payload = None
    if payload is None:
        st.session_state.pop("_atc_replay_last", None)  # a failed load must not count as shown
        st.warning("statsim.net could not be reached right now. Try again in a moment.")
        return
    loaded.add(chosen["id"])
    if not payload["flights"]:
        st.info("statsim.net has no recorded track for the traffic of this session, so there is nothing to draw. Tracks are only kept for a pilot's last 60 flights.")
    st.iframe(atc_replay_document(payload), height=800)


if atc_replay_open:
    render_atc_replay()
elif replay_open:
    render_flight_replay()

# ── First/last flight, most flown route/aircraft/airline, most interesting route ──
p1, p2, p3 = st.columns(3)

with p1:
    first_f = df["when"].min() if has_flights else pd.NaT
    last_f = df["when"].max() if has_flights else pd.NaT
    fmt = "%d.%m.%Y"
    st.markdown(f"""
    <div class="vs-card">
      <div class="vs-kpi-label">First Flight</div>
      <div style="color:{TEXT};font-size:15px;margin:4px 0 12px;">{first_f.strftime(fmt) if pd.notna(first_f) else '—'}</div>
      <div class="vs-kpi-label">Last Flight</div>
      <div style="color:{CYAN};font-size:15px;">{last_f.strftime(fmt) if pd.notna(last_f) else '—'}</div>
    </div>""", unsafe_allow_html=True)

with p2:
    top_route_html = "—"
    top_ac_html = "—"
    if has_valid_routes:
        rc = Counter(df[df["route"] != "→"]["route"].tolist())
        if rc:
            route, cnt = rc.most_common(1)[0]
            d, a = route.split("→")
            top_route_html = f"{html_escape(d)} → {html_escape(a)} <span class='vs-kpi-sub'>({cnt}×)</span>"
    if has_flights:
        ac_counts = df["ac"].value_counts()
        if len(ac_counts):
            top_ac = ac_counts.idxmax()
            top_mfr = df[df["ac"] == top_ac]["mfr"].iloc[0]
            top_airline = "—"
            cs_counts = df["cs_prefix"].value_counts()
            cs_counts = cs_counts[cs_counts.index != ""]
            if len(cs_counts):
                top_prefix = cs_counts.idxmax()
                top_airline = airlines_db.get(top_prefix, top_prefix)
            top_ac_html = f"{html_escape(str(top_ac))} <span class='vs-kpi-sub'>({html_escape(top_mfr)})</span><br><span class='vs-kpi-sub'>{html_escape(str(top_airline))}</span>"
    st.markdown(f"""
    <div class="vs-card">
      <div class="vs-kpi-label">Most Flown Route</div>
      <div style="color:{TEXT};font-size:15px;margin:4px 0 12px;">{top_route_html}</div>
      <div class="vs-kpi-label">Most Flown Aircraft / Airline</div>
      <div style="color:{CYAN};font-size:15px;">{top_ac_html}</div>
    </div>""", unsafe_allow_html=True)

with p3:
    interesting_html = "—"
    if has_valid_routes:
        rc = Counter(df[df["route"] != "→"]["route"].tolist())
        dr = df[(df["route"] != "→") & (df["dur_min"] > 30)].copy()
        if len(dr) and rc:
            dr["freq"] = dr["route"].map(rc)
            dr = dr.sort_values(["freq", "dur_min"], ascending=[True, False])
            row = dr.iloc[0]
            d, a = row["route"].split("→")
            interesting_html = f"{html_escape(d)} → {html_escape(a)} <span class='vs-kpi-sub'>({html_escape(str(row['ac']))} · {fmt_hm(row['dur_min'])})</span>"
    st.markdown(f"""
    <div class="vs-card">
      <div class="vs-kpi-label">Most Interesting Route Flown</div>
      <div style="color:{AMBER};font-size:15px;margin:4px 0;">{interesting_html}</div>
      <div class="vs-kpi-sub" style="margin-top:8px;">Among rarely-flown routes over 30 min</div>
    </div>""", unsafe_allow_html=True)

# ── KPI strip ──────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
pilot_hours = (mstats or {}).get("pilot")
atc_hours = (mstats or {}).get("atc")
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(f"""<div class="vs-card" style="text-align:center;">
      <div class="vs-kpi-label">Total Flights</div>
      <div class="vs-kpi-val" style="color:{CYAN};">{len(df)}</div></div>""", unsafe_allow_html=True)
with k2:
    val = fmt_hm(pilot_hours * 60) if pilot_hours is not None else "—"
    st.markdown(f"""<div class="vs-card" style="text-align:center;">
      <div class="vs-kpi-label">Pilot Hours</div>
      <div class="vs-kpi-val" style="color:{EMERALD};">{val}</div>
      <div class="vs-kpi-sub">VATSIM record</div></div>""", unsafe_allow_html=True)
with k3:
    val = fmt_hm(atc_hours * 60) if atc_hours is not None else "—"
    st.markdown(f"""<div class="vs-card" style="text-align:center;">
      <div class="vs-kpi-label">ATC Hours</div>
      <div class="vs-kpi-val" style="color:{VIOLET};">{val}</div>
      <div class="vs-kpi-sub">VATSIM record</div></div>""", unsafe_allow_html=True)
with k4:
    st.markdown(f"""<div class="vs-card" style="text-align:center;">
      <div class="vs-kpi-label">ATC Sessions</div>
      <div class="vs-kpi-val" style="color:{ROSE};">{len(atc_raw)}</div></div>""", unsafe_allow_html=True)

if not has_flights:
    st.info("No flight records found for this CID on statsim.net. The charts below may be empty.")

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 1 — FLIGHT ACTIVITY (Monthly/Yearly)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="vs-h">Flight Activity</div>', unsafe_allow_html=True)
period = st.radio("Period", ["Monthly", "Yearly"], horizontal=True, key="flight_period", label_visibility="collapsed")
if has_flights:
    dm = df.dropna(subset=["when"]).copy()
    if len(dm):
        dm["bucket"] = dm["when"].dt.to_period("M" if period == "Monthly" else "Y").astype(str)
        counts = dm.groupby("bucket").size().reset_index(name="n")
        fig = px.area(counts, x="bucket", y="n", template="plotly_dark")
        fig.update_traces(line=dict(color=CYAN, width=2), fill="tozeroy", fillcolor="rgba(34,211,238,0.12)", mode="lines")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           margin=dict(l=0, r=0, t=6, b=0), height=240, font=PLOTLY_FONT, showlegend=False)
        fig.update_xaxes(gridcolor=LINE, zeroline=False, title="", tickangle=-45, tickfont=dict(size=9))
        fig.update_yaxes(gridcolor=LINE, zeroline=False, title="")
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No flights with date information.")
else:
    st.info("No flight data.")

render_activity_panels(df, has_flights)

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 2 — FLEET / MANUFACTURER DISTRIBUTION
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="vs-h">Fleet Distribution</div>', unsafe_allow_html=True)
if has_flights:
    mfr_options = ["All"] + sorted(df["mfr"].unique().tolist())
    selected_mfr = st.selectbox("Manufacturer", mfr_options, key="mfr_filter")
    dff2 = df if selected_mfr == "All" else df[df["mfr"] == selected_mfr]
    ac_counts = dff2["ac"].value_counts().head(10).reset_index()
    ac_counts.columns = ["ac", "n"]
    if len(ac_counts):
        fig = px.bar(ac_counts, x="n", y="ac", orientation="h", template="plotly_dark",
                     color="n", color_continuous_scale=[[0, "#0c2a3a"], [1, CYAN]])
        fig.update_traces(marker_line_width=0, opacity=0.95, text=ac_counts["n"], textposition="outside",
                           textfont=dict(color=SUBTLE, size=10))
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           margin=dict(l=0, r=0, t=6, b=0), height=280, font=PLOTLY_FONT,
                           showlegend=False, coloraxis_showscale=False)
        fig.update_xaxes(gridcolor=LINE, zeroline=False, title="")
        fig.update_yaxes(gridcolor=LINE, zeroline=False, title="", autorange="reversed", tickfont=dict(size=12))
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No flights for this manufacturer.")
else:
    st.info("No flight data.")

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 3 — LONGEST FLIGHTS (hour + NM filter)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="vs-h">Flights: Longest to Shortest</div>', unsafe_allow_html=True)
s1, s2 = st.columns(2)
with s1:
    min_hours = st.slider("Min. duration (hours)", 0, 16, 0, key="min_hours")
with s2:
    min_nm = st.slider("Min. distance (NM)", 0, 6000, 0, step=100, key="min_nm")

if has_flights:
    dl = df[(df["dur_min"] >= min_hours * 60) & (df["dur_min"] > 0)].copy()
    dl = dl[dl["distance_nm"].fillna(0) >= min_nm]
    dl = dl.sort_values("dur_min", ascending=False).head(20)
    if len(dl):
        dl["lbl"] = dl["route"] + "  " + dl["ac"]
        dl["hm"] = dl["dur_min"].apply(fmt_hm)
        fig = px.bar(dl, x="dur_min", y="lbl", orientation="h", template="plotly_dark",
                     color="dur_min", color_continuous_scale=[[0, "#0c2e26"], [1, EMERALD]], custom_data=["hm"])
        fig.update_traces(marker_line_width=0, opacity=0.95, hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>",
                           text=dl["hm"], textposition="outside", textfont=dict(color=SUBTLE, size=10))
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           margin=dict(l=0, r=0, t=6, b=0), height=max(260, len(dl) * 30), font=PLOTLY_FONT,
                           showlegend=False, coloraxis_showscale=False)
        fig.update_xaxes(gridcolor=LINE, zeroline=False, title="minutes")
        fig.update_yaxes(gridcolor=LINE, zeroline=False, title="", autorange="reversed", tickfont=dict(size=11))
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No flights found with this filter. (Distance calculation needs airport coordinates; some airports may be missing from the database.)")
else:
    st.info("No flight data.")

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 4 — ATC SECTOR STATS (if any)
# ══════════════════════════════════════════════════════════════════════════════
has_atc_history = len(atc_raw) > 0
if has_atc_history:
    st.markdown('<div class="vs-h">ATC Sector Stats</div>', unsafe_allow_html=True)
    atc_period = st.radio("Period", ["All Time", "This Year", "This Month"], horizontal=True, key="atc_period",
                           label_visibility="collapsed")

    da = pd.DataFrame(atc_raw)
    da["on"] = pd.to_datetime(da.get("loggedOn"), utc=True, errors="coerce")
    da["off"] = pd.to_datetime(da.get("loggedOff"), utc=True, errors="coerce")
    da["dur_min"] = ((da["off"] - da["on"]).dt.total_seconds() / 60).clip(lower=0).fillna(0)
    da["cs"] = da.get("callsign", pd.Series(dtype=str)).fillna("???").str.upper()

    now_utc = datetime.now(timezone.utc)
    if atc_period == "This Year":
        da = da[da["on"] >= now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)]
    elif atc_period == "This Month":
        da = da[da["on"] >= now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]

    if len(da):
        pos = da.groupby("cs")["dur_min"].sum().sort_values(ascending=False).head(12).reset_index()
        pos["hm"] = pos["dur_min"].apply(fmt_hm)
        fig = px.bar(pos, x="dur_min", y="cs", orientation="h", template="plotly_dark",
                     color="dur_min", color_continuous_scale=[[0, "#1e1633"], [1, VIOLET]], custom_data=["hm"])
        fig.update_traces(marker_line_width=0, opacity=0.95, hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           margin=dict(l=0, r=0, t=6, b=0), height=360, font=PLOTLY_FONT,
                           showlegend=False, coloraxis_showscale=False)
        fig.update_xaxes(gridcolor=LINE, zeroline=False, title="minutes")
        fig.update_yaxes(gridcolor=LINE, zeroline=False, title="", autorange="reversed", tickfont=dict(size=11))
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No ATC sessions in this period.")
