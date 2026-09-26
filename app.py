import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from html import escape as html_escape
import requests
import pandas as pd
from collections import Counter
from datetime import datetime, timedelta, timezone
import os
import json
import re
import hmac
import hashlib
import time
from shapely.geometry import LineString, shape, Point
from shapely.prepared import prep

from admin_audit import append_audit_event, read_audit_events
from health_monitor import record_result, summarize as summarize_health
from airport_layout_cache import sync_local_layouts_in_background, warm_in_background
from anomaly_engine import feed_time as anomaly_feed_time, snapshot_view as anomaly_view, update as anomaly_update
from anomaly_timeline import build_timeline
from anomaly_map_view import anomaly_map_document
import anomaly_archive_store
from events_history_store import maybe_record, status as events_history_status
from data_sync import ADMIN_AUDIT_FILE, RADAR_LOG_FILE, ensure_pulled, push, push_if_due, status as sync_status
from page_views import record_view, summarize_views
from redaction import add_to_blocklist, is_blocked, load_blocklist, remove_from_blocklist
from site_banner import clear_banner, read_banner, read_banner_raw, write_banner
from security_utils import SlidingWindowLimiter, is_valid_callsign, is_valid_fir_prefix
from totp import new_totp_secret, verify_totp
from user_agent_parser import parse_user_agent
from pin_sync import render_pin_sync
from region_options import FEATURED, order_regions, parse_country_names, traffic_by_region
from registration_country import country_of_registration, extract_registration
from ui_theme import (AMBER, CID_BLOCKLIST_FILE, CYAN, EMERALD, LINE as UI_LINE, PAGE_VIEWS_FILE, ROSE, SITE_BANNER_FILE,
                      TEXT as UI_TEXT, VIOLET, card_css, page_url, record_card, render_banner, set_browser_title, stat_card)
from leaderboard_records import flight_records, member_records
from vatsim_data import _member_api_limiter, fetch_member_rating, load_airports
from flight_track import fetch_track
from fir_crossings import fir_crossings, great_circle_points
from geo_compact import compact_rings
from area_assign import count_pilots_smallest_area
from airspace_stats import airport_atc_prefixes, airport_has_atc, count_pilots_in_areas, staffed_area_ids
from fleet_stats import fleet_summary, hub_rows
from flight_plan_firs import boundaries_for_codes, eet_fir_codes

def get_secret(key, default=""):
    # st.secrets.get() raises StreamlitSecretNotFoundError (instead of
    # returning the default) when no secrets.toml exists at all, which
    # would otherwise crash the whole app on first load.
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def _parse_banner_ts(ts):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def csv_safe_for_download(df):
    # A pilot's callsign or flight-plan fields are free text they fully control; if a cell starts with =, +, - or @,
    # Excel/Sheets reads it as a formula on open ("CSV injection" / formula injection). A leading apostrophe forces
    # every spreadsheet app to treat the cell as plain text without changing what is displayed.
    # Every column is mapped (not filtered by dtype first): pandas may store text as classic "object" or as its newer
    # dedicated string dtype depending on version/config, and checking for both reliably is more fragile than just
    # letting the lambda itself skip anything that isn't a Python str.
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].map(lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v)
    return df

# API URLs
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_TRANSCEIVERS_URL = "https://data.vatsim.net/v3/transceivers-data.json"
VATSIM_FIR_GEO_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/Boundaries.geojson"
VATSPY_DAT_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/VATSpy.dat"
TRACON_GEO_URL = "https://github.com/vatsimnetwork/simaware-tracon-project/releases/latest/download/TRACONBoundaries.geojson"
VATSIM_RADAR_AIRLINES_URL = "https://data.vatsim-radar.com/airlines"
CSV_FILE_PATH = "airports.csv"

# Page Configuration
# The browser tab title for fixed-name routes (like Admin) is set here, directly through Streamlit's own
# mechanism, rather than through the JS-based set_browser_title() below: that one drives an iframe that tries
# to reach the real tab title via window.parent/window.top, which some hosts (e.g. Streamlit Community Cloud)
# sandbox as a different, non-same-origin frame, silently breaking the title update there even though it works
# fine on localhost. set_page_config has no such cross-frame dependency, so it is used wherever the title is
# already known before this call (a fixed route), and only the home page's tab-driven title (which changes
# without a rerun) still needs the JS approach.
st.set_page_config(
    page_title="VatScoreRadar - Admin" if st.query_params.get("admin") == "true" else "VatScoreRadar",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CUSTOM CSS
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stDecoration"] {display: none;}
    [data-testid="stSidebarNav"] {display: none !important;}
    [data-testid="stSidebar"] {display: none !important;}
    /* Streamlit dropped the semantic .main/.stTabs classes in favor of
       data-testid + hashed emotion classes; target those instead, and
       force with !important since the framework's own generated rules
       otherwise win the specificity/cascade-order fight. */
    [data-testid="stAppViewContainer"], [data-testid="stApp"] { background-color: #0f111a !important; }
    h1 { color: #3b82f6 !important; font-family: 'Segoe UI', sans-serif; }
    [data-testid="stTabs"] [data-baseweb="tab"] { color: #94a3b8; font-size: 16px; }
    [data-testid="stTabs"] [data-baseweb="tab"]:hover { color: #3b82f6; }
    [data-testid="stTabs"] [aria-selected="true"] { color: #3b82f6 !important; font-weight: bold; }
    /* Hidden helper link that the CID Stats tab's watcher script clicks to
       actually navigate — see the tab_cid block below. */
    div[data-testid="stPageLink"]:has(a[href="CID_Stats"]),
    div[data-testid="stPageLink"]:has(a[href="Network_Stats"]),
    div[data-testid="stPageLink"]:has(a[href="Events"]) { display: none; }
    div[data-testid="stElementContainer"]:has(input[aria-label="vs_lookup_cid"]) { display: none; }
    div[data-testid="stElementContainer"]:has(input[aria-label="vs_track_req"]) { display: none; }
    div[data-testid="stElementContainer"]:has(input[aria-label="vs_pins_restore"]) { display: none; }
    div[data-testid="stElementContainer"]:has(iframe[srcdoc*="vs-rating-sync"]) { display: none; }
    /* Streamlit fades elements while a (fragment) rerun is running; with 20s auto-refresh that reads as constant flicker. */
    [data-stale="true"] { opacity: 1 !important; transition: none !important; }
    div[data-testid="stMetricValue"] { color: #22c55e; }
    .signature-container {
        text-align: right; font-family: 'Consolas', monospace; color: #475569; font-size: 12px;
        padding-top: 30px; border-top: 1px solid #1e293b; margin-top: 40px;
        line-height: 1.6;
    }
    .signature-link { color: #3b82f6; text-decoration: none; }
    .signature-link:hover { text-decoration: underline; }
    
    .roadmap-card {
        background-color: #1e293b;
        border-left: 5px solid #3b82f6;
        padding: 15px 20px;
        border-radius: 6px;
        margin-bottom: 15px;
    }
    .roadmap-card.in-progress {
        border-left: 5px solid #f59e0b;
    }
    .roadmap-title { color: #f8fafc; font-weight: bold; font-size: 16px; margin-bottom: 5px; }
    .roadmap-desc { color: #94a3b8; font-size: 14px; line-height: 1.5; }
    .roadmap-badge {
        color: white; padding: 2px 8px; border-radius: 4px;
        font-size: 11px; font-weight: bold; text-transform: uppercase; display: inline-block; margin-bottom: 8px;
    }
    .top-emoji-btn button {
        background: none !important; border: none !important; font-size: 24px !important;
        padding: 0px !important; cursor: pointer; line-height: 1;
    }
    </style>
""", unsafe_allow_html=True)

# Admin Activity Logging System
LOG_FILE = RADAR_LOG_FILE
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "")
ADMIN_PASSWORD_HASH = get_secret("ADMIN_PASSWORD_HASH", "")
ADMIN_TOTP_SECRET = get_secret("ADMIN_TOTP_SECRET", "")
MIN_PBKDF2_ITERATIONS = 100_000
MAX_ADMIN_FAILS = 5
ADMIN_FAIL_WINDOW = 600
ADMIN_LOCK_SECONDS = 900
ADMIN_SESSION_SECONDS = 1800  # an open admin tab is logged out after 30 minutes of inactivity, password (+ TOTP) required again
ADMIN_TOTP_STEP_SECONDS = 300  # the password step and the TOTP step must happen within 5 minutes of each other


def _log_admin_event(event, detail=""):
    try:
        append_audit_event(ADMIN_AUDIT_FILE, event, detail)
        push_if_due(ADMIN_AUDIT_FILE, 60)
    except Exception:
        pass  # the audit trail is best-effort and must never block a login/logout

@st.cache_resource
def _admin_guard():
    # Process-wide state shared by every session, so opening a new browser
    # tab doesn't reset the brute-force counter.
    return {"fails": [], "lock_until": 0.0}


@st.cache_resource
def _health_store():
    # Process-wide, so the admin panel sees the health of a data source regardless of which visitor's request last hit it.
    return {}


def _report_health(source, ok, error=None):
    try:
        record_result(_health_store(), source, ok, error)
    except Exception:
        pass  # health tracking must never be the reason a data fetch fails

def admin_lock_remaining():
    guard = _admin_guard()
    lock_until = guard["lock_until"]
    now = time.time()
    if lock_until > now:
        return lock_until - now
    else:
        return 0.0
def register_admin_failure():
    guard = _admin_guard()
    now = time.time()
    guard["fails"].append(now)
    guard["fails"] = [t for t in guard["fails"] if now - t < ADMIN_FAIL_WINDOW]
    if len(guard["fails"]) >= MAX_ADMIN_FAILS:
        guard["lock_until"] = now + ADMIN_LOCK_SECONDS
        guard["fails"] = []
def clear_admin_failures():
    guard = _admin_guard()
    guard["fails"] = []
    guard["lock_until"] = 0.0
def verify_admin_password(candidate):
    # Use hmac.compare_digest for constant-time comparison to prevent timing attacks
    try:
        if ADMIN_PASSWORD_HASH:
            parts = ADMIN_PASSWORD_HASH.split('$')
            if len(parts) != 4 or parts[0] != 'pbkdf2_sha256':
                return False
            iterations = int(parts[1])
            salt_hex = parts[2]
            hash_hex = parts[3]
            computed = hashlib.pbkdf2_hmac(
                'sha256',
                candidate.encode(),
                bytes.fromhex(salt_hex),
                iterations
            )
            return hmac.compare_digest(computed, bytes.fromhex(hash_hex))
        elif ADMIN_PASSWORD:
            return hmac.compare_digest(candidate.encode(), ADMIN_PASSWORD.encode())
        else:
            return False
    except Exception:
        return False

def init_log_file():
    if not os.path.exists(LOG_FILE):
        df = pd.DataFrame(columns=["Timestamp", "Session_ID", "OS", "Browser", "Device_Type", "Last_Action"])
        df.to_csv(LOG_FILE, index=False)

init_log_file()

def log_activity(action):
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if "user_session_id" not in st.session_state:
            st.session_state.user_session_id = datetime.now().strftime('%H%M%S') + str(os.getpid())

        session_id = st.session_state.user_session_id
        df = pd.read_csv(LOG_FILE)

        if session_id in df['Session_ID'].values:
            df.loc[df['Session_ID'] == session_id, 'Timestamp'] = timestamp
            df.loc[df['Session_ID'] == session_id, 'Last_Action'] = action
        else:
            try:
                ua = st.context.headers.get("User-Agent", "")
            except Exception:
                ua = ""
            client = parse_user_agent(ua)
            new_row = pd.DataFrame([{
                "Timestamp": timestamp, "Session_ID": session_id,
                "OS": client["os"], "Browser": client["browser"], "Device_Type": client["device_type"], "Last_Action": action
            }])
            df = pd.concat([df, new_row], ignore_index=True)

        df.to_csv(LOG_FILE, index=False)
        push_if_due(LOG_FILE)
    except:
        pass

try:
    ensure_pulled()
    sync_local_layouts_in_background()
except Exception:
    pass

if "initialized" not in st.session_state:
    log_activity("Radar Dashboard Opened")
    try:
        record_view(PAGE_VIEWS_FILE, "Live Radar")
        push_if_due(PAGE_VIEWS_FILE)
    except Exception:
        pass
    st.session_state.initialized = True

# Initialize VIP Watchlist Session State
if "vip_watchlist" not in st.session_state:
    st.session_state.vip_watchlist = []
if "vip_cids" not in st.session_state:
    st.session_state.vip_cids = ""
if "vip_callsigns" not in st.session_state:
    st.session_state.vip_callsigns = ""

query_params = st.query_params
def _admin_hash_iterations():
    if not ADMIN_PASSWORD_HASH:
        return None
    parts = ADMIN_PASSWORD_HASH.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@st.cache_data(ttl=15)
def fetch_vatsim_data():
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            _report_health("VATSIM feed", True)
            return data
        _report_health("VATSIM feed", False, f"HTTP {r.status_code}")
    except Exception as e:
        _report_health("VATSIM feed", False, e)
    return None

@st.cache_data(ttl=15)
def fetch_pilot_frequencies():
    # VATSIM's main data feed has no per-pilot frequency field — it lives in this
    # separate transceivers feed instead, keyed by callsign, frequency in Hz.
    freq_map = {}
    try:
        r = requests.get(VATSIM_TRANSCEIVERS_URL, timeout=10)
        if r.status_code == 200:
            for entry in r.json():
                callsign = entry.get("callsign")
                transceivers = entry.get("transceivers") or []
                if callsign and transceivers:
                    hz = transceivers[0].get("frequency")
                    if hz:
                        freq_map[callsign] = f"{hz / 1_000_000:.3f}"
            _report_health("VATSIM transceivers feed", True)
        else:
            _report_health("VATSIM transceivers feed", False, f"HTTP {r.status_code}")
    except Exception as e:
        _report_health("VATSIM transceivers feed", False, e)
    return freq_map

@st.cache_data(ttl=86400)
def load_vatsim_radar_airlines():
    airlines_map = {}
    try:
        r = requests.get(VATSIM_RADAR_AIRLINES_URL, timeout=10)
        if r.status_code == 200:
            raw_list = r.json()
            if isinstance(raw_list, list):
                for item in raw_list:
                    icao_code = item.get("icao")
                    if icao_code:
                        key = icao_code.upper().strip()
                        virtual = bool(item.get("virtual"))
                        # For many big airlines (DLH, THY, AAL...) the list holds only a VIRTUAL airline ("vDLH"): never let a
                        # virtual entry replace a real one, and the page shows virtual ones as just "ICAO (TELEPHONY)".
                        if virtual and key in airlines_map and not airlines_map[key]["virtual"]:
                            continue
                        airlines_map[key] = {
                            "name": item.get("name", "Unknown Airline"),
                            "callsign": item.get("callsign", "UNKNOWN"),
                            "virtual": virtual
                        }
            _report_health("Airlines list (vatsim-radar)", True)
        else:
            _report_health("Airlines list (vatsim-radar)", False, f"HTTP {r.status_code}")
    except Exception as e:
        _report_health("Airlines list (vatsim-radar)", False, e)
    return airlines_map

@st.cache_data(ttl=86400, show_spinner=False)
def load_country_names():
    # ICAO prefix -> country name from VATSpy.dat [Countries]; raises on failure so nothing bad is cached for a day
    try:
        r = requests.get(VATSPY_DAT_URL, timeout=15)
        r.raise_for_status()
        result = parse_country_names(r.text)
        _report_health("VATSpy.dat", True)
        return result
    except Exception as e:
        _report_health("VATSpy.dat", False, e)
        raise

MIN_REGION_AIRCRAFT = 5

FIR_FALLBACK_NAMES = {
    "LT": "Türkiye Airspace Hub",
    "ED": "Germany Airspace Hub",
    "EG": "United Kingdom Airspace Hub",
    "LF": "France Airspace Hub",
    "K": "United States Airspace Hub",
    "OM": "UAE & Oman Airspace Hub",
    "LO": "Austria Airspace Hub",
    "LI": "Italy Airspace Hub",
    "LE": "Spain Airspace Hub"
}

@st.cache_data(ttl=86400)
def load_fir_raw_geometries():
    # Cache only raw GeoJSON geometry dicts — Shapely objects are not serializable by Streamlit cache
    raw_groups = {}
    try:
        response = requests.get(VATSIM_FIR_GEO_URL, timeout=12)
        if response.status_code == 200:
            geo_data = response.json()
            for feature in geo_data.get("features", []):
                try:
                    properties = feature.get("properties", {}) or {}
                    geometry = feature.get("geometry", {})
                    icao = str(properties.get("id") or properties.get("icao") or "").upper().strip()
                    if not icao:
                        continue
                    prefix = "K" if icao.startswith("K") else icao[:2]
                    if prefix not in raw_groups:
                        raw_groups[prefix] = []
                    if geometry:
                        raw_groups[prefix].append(geometry)
                except Exception:
                    # One malformed feature shouldn't drop every FIR after it.
                    continue
    except:
        pass
    return raw_groups

def load_and_group_fir_boundaries():
    # Build Shapely shapes from cached raw geometries every run — avoids cache serialization bug
    raw_groups = load_fir_raw_geometries()
    grouped_boundaries = {}
    for prefix, geom_list in raw_groups.items():
        name = FIR_FALLBACK_NAMES.get(prefix, f"{prefix} Airspace Zone")
        shapes = []
        for geometry in geom_list:
            try:
                shapely_shape = shape(geometry)
                if shapely_shape.geom_type == 'MultiPolygon':
                    shapes.extend(list(shapely_shape.geoms))
                else:
                    shapes.append(shapely_shape)
            except:
                pass
        grouped_boundaries[prefix] = {"name": name, "shapes": shapes}
    for k, v in FIR_FALLBACK_NAMES.items():
        if k not in grouped_boundaries:
            grouped_boundaries[k] = {"name": v, "shapes": []}
    return grouped_boundaries

@st.cache_data
def load_csv_database():
    if os.path.exists(CSV_FILE_PATH):
        try:
            df = pd.read_csv(CSV_FILE_PATH)
            df.columns = [c.lower().strip() for c in df.columns]
            
            icao_col = 'icao' if 'icao' in df.columns else df.columns[0]
            lat_col = 'latitude' if 'latitude' in df.columns else 'latitude_deg' if 'latitude_deg' in df.columns else 'lat'
            lon_col = 'longitude' if 'longitude' in df.columns else 'longitude_deg' if 'longitude_deg' in df.columns else 'lon'
            
            df[icao_col] = df[icao_col].astype(str).str.upper().str.strip()
            df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
            df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
            df = df.dropna(subset=[lat_col, lon_col])

            # Vectorized instead of iterrows(): ~28k airport rows built via zip()
            # over numpy arrays rather than one Python-level loop iteration per row.
            names = df["name"].fillna("").astype(str) if "name" in df.columns else [""] * len(df)
            return {
                icao: {"latitude_deg": lat, "longitude_deg": lon, "latitude": lat, "longitude": lon, "name": name}
                for icao, lat, lon, name in zip(df[icao_col], df[lat_col], df[lon_col], names)
            }
        except: pass
    return {}

def get_coordinates_from_library(pilots_list):
    coords_map = {}
    csv_db = load_csv_database()
    
    for p in pilots_list:
        fplan = p.get("flight_plan") or {}
        dep = str(fplan.get("departure", "")).strip().upper()
        arr = str(fplan.get("arrival", "")).strip().upper()
        
        if dep and len(dep) == 4 and dep not in coords_map:
            if dep in csv_db:
                coords_map[dep] = {
                    "latitude_deg": csv_db[dep]['latitude'],
                    "longitude_deg": csv_db[dep]['longitude'],
                    "name": csv_db[dep].get('name', '')
                }
                
        if arr and len(arr) == 4 and arr not in coords_map:
            if arr in csv_db:
                coords_map[arr] = {
                    "latitude_deg": csv_db[arr]['latitude'],
                    "longitude_deg": csv_db[arr]['longitude'],
                    "name": csv_db[arr].get('name', '')
                }
        
    fallback = {
        "LTBA": {"latitude_deg": 40.9769, "longitude_deg": 28.8146},
        "LTFM": {"latitude_deg": 41.2753, "longitude_deg": 28.7519},
        "LTAC": {"latitude_deg": 40.1281, "longitude_deg": 32.9950},
        "LTAI": {"latitude_deg": 36.9003, "longitude_deg": 30.7928},
        "EGLL": {"latitude_deg": 51.4700, "longitude_deg": -0.4543},
        "GMMN": {"latitude_deg": 33.3675, "longitude_deg": -7.5899},
        "KJFK": {"latitude_deg": 40.6398, "longitude_deg": -73.7789}
    }
    for k, v in fallback.items():
        if k not in coords_map: coords_map[k] = v
        
    return coords_map

def js_safe(value):
    # json.dumps produces a properly quoted/escaped JS literal; the extra
    # replace defangs "</script>" so untrusted strings (pilot remarks,
    # callsigns, URL query params) can't break out of the <script> block.
    return json.dumps(value).replace("</", "<\\/")

@st.cache_resource
def _track_limiters():
    # statsim.net publishes no rate limit, so keep our own modest budget: per browser session and for the whole app.
    return SlidingWindowLimiter(8, 60), SlidingWindowLimiter(40, 60)


@st.cache_data(ttl=86400, show_spinner=False)
def load_fir_features_raw():
    # One record per FIR boundary (id + GeoJSON geometry), unlike load_fir_raw_geometries which merges them by 2-letter
    # prefix. Raises on failure so that a failed download is never cached for a day.
    try:
        r = requests.get(VATSIM_FIR_GEO_URL, timeout=15)
        r.raise_for_status()
        out = []
        for f in r.json().get("features", []):
            props = f.get("properties") or {}
            fid = str(props.get("id") or "").strip()
            if fid and f.get("geometry"):
                try:
                    label = [float(props["label_lat"]), float(props["label_lon"])]
                except (KeyError, TypeError, ValueError):
                    label = None
                out.append({"id": fid, "geometry": f["geometry"], "label": label})
        if not out:
            raise ValueError("no FIR boundaries")
        _report_health("FIR boundaries (Boundaries.geojson)", True)
        return out
    except Exception as e:
        _report_health("FIR boundaries (Boundaries.geojson)", False, e)
        raise


@st.cache_resource(ttl=86400, show_spinner=False)
def fir_index():
    items = []
    for f in load_fir_features_raw():
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        items.append({"id": f["id"], "geometry": g, "bounds": g.bounds, "prepared": prep(g), "label": f.get("label")})
    return items


@st.cache_data(ttl=86400, show_spinner=False)
def load_tracon_features_raw():
    # Approach areas from the SimAware TRACON project (CC BY-SA 4.0), downloaded at run time and never stored in the repo.
    try:
        r = requests.get(TRACON_GEO_URL, timeout=20)
        r.raise_for_status()
        out = []
        for f in r.json().get("features", []):
            props = f.get("properties") or {}
            tid = str(props.get("id") or "").strip()
            if tid and f.get("geometry"):
                keys = sorted({str(k).upper() for k in [tid] + list(props.get("prefix") or []) if k})
                out.append({"id": tid, "name": str(props.get("name") or ""), "keys": keys, "geometry": f["geometry"]})
        if not out:
            raise ValueError("no TRACON boundaries")
        _report_health("TRACON boundaries (SimAware)", True)
        return out
    except Exception as e:
        _report_health("TRACON boundaries (SimAware)", False, e)
        raise


@st.cache_resource(ttl=86400, show_spinner=False)
def tracon_index():
    items = []
    for f in load_tracon_features_raw():
        try:
            g = shape(f["geometry"])
            p = g.representative_point()
        except Exception:
            continue
        items.append({"id": f["id"], "name": f["name"], "keys": f["keys"], "geometry": g, "bounds": g.bounds,
                      "prepared": prep(g), "label": [p.y, p.x]})
    return items


@st.cache_data(ttl=86400, show_spinner=False)
def load_vatspy_fir_rows():
    # (FIR icao, boundary id, callsign prefix) rows from VATSpy.dat, [FIRs] section. Raises on failure so nothing bad is cached.
    r = requests.get(VATSPY_DAT_URL, timeout=15)
    r.raise_for_status()
    rows = []
    in_firs = False
    for line in r.text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_firs = s == "[FIRs]"
            continue
        if not in_firs or not s or s.startswith(";"):
            continue
        parts = [x.strip() for x in s.split("|")]
        if len(parts) >= 4:
            rows.append((parts[0].upper(), parts[3].upper(), parts[2].upper(), parts[1]))
    if not rows:
        raise ValueError("no FIR rows")
    return rows


@st.cache_data(ttl=86400, show_spinner=False)
def load_fir_callsign_keys():
    # FIR boundary id -> callsign prefixes of the controllers that staff it
    keys = {}
    for icao, boundary, prefix, _name in load_vatspy_fir_rows():
        for k in (icao, prefix):
            if k:
                keys.setdefault(boundary or icao, set()).add(k)
    return {b: sorted(v) for b, v in keys.items()}


def route_atc_spec(pilot, track_points):
    # Which FIRs and approach areas matter for this flight? FIRs: the ones the pilot filed as EET/ in the flight plan (so
    # they follow the planned route), plus any the flown track really went through; without an EET, the flown track and
    # the direct line to the destination. Approach areas: only those over the departure and arrival airports. The browser
    # draws them and matches the live controller list against them, so nothing goes stale when controllers log on/off.
    fplan = pilot.get("flight_plan") or {}
    airports = load_csv_database()
    dep = airports.get(str(fplan.get("departure", "")).strip().upper())
    arr = airports.get(str(fplan.get("arrival", "")).strip().upper())
    here = (pilot.get("latitude"), pilot.get("longitude"))
    flown = [(p[0], p[1]) for p in (track_points or [])]
    fir_idx = fir_index()
    fir_by_id = {i["id"]: i for i in fir_idx}
    fir_keys = load_fir_callsign_keys()

    codes = eet_fir_codes(fplan.get("remarks"))
    rows = [(icao, boundary) for icao, boundary, _prefix, _name in load_vatspy_fir_rows()]
    fir_names = {}
    for icao, boundary, _prefix, name in load_vatspy_fir_rows():
        fir_names.setdefault(boundary or icao, name)
    # FIRs already flown through (full-precision boundaries, departure airport included): the browser only has simplified
    # polygons, which can miss a departure airport sitting on a boundary (KJFK next to KZNY) and call that FIR "still ahead"
    visit_points = ([(dep["latitude"], dep["longitude"])] if dep else []) + flown
    flown_hits = fir_crossings(visit_points, fir_idx, max_results=300) if visit_points else []
    visited = {h["id"] for h in flown_hits}
    fir_ids = boundaries_for_codes(codes, fir_by_id.keys(), rows) if codes else []
    if fir_ids:
        source = "eet"
        fir_ids += [h["id"] for h in flown_hits if h["id"] not in fir_ids]
        # An EET names a whole FIR ("EGPX"), but its sub-sectors ("EGPX-S") are only relevant when the aircraft has been
        # through them or the rest of its route runs close to them; otherwise they would show up as "ahead" for nothing.
        near_ahead = set()
        start = flown[-1] if flown else (here if None not in here else None)
        if arr and start and any("-" in f for f in fir_ids):
            gc = great_circle_points(start, (arr["latitude"], arr["longitude"]), 100)
            if all(abs(b[1] - a[1]) < 180 for a, b in zip(gc, gc[1:])):  # a line across the antimeridian would span the world
                corridor = LineString([(lon, lat) for lat, lon in gc]).buffer(1.0)  # about 60 NM either side
                near_ahead = {i["id"] for i in fir_idx if "-" in i["id"] and i["prepared"].intersects(corridor)}
        fir_ids = [f for f in fir_ids if "-" not in f or f in visited or f in near_ahead]
    else:
        source = "geometry"
        if flown:
            samples = list(flown)
            if arr:
                samples += great_circle_points(samples[-1], (arr["latitude"], arr["longitude"]), 120)
        elif dep and arr:
            samples = great_circle_points((dep["latitude"], dep["longitude"]), (arr["latitude"], arr["longitude"]), 160)
        elif arr and None not in here:
            samples = great_circle_points(here, (arr["latitude"], arr["longitude"]), 120)
        else:
            samples = [here] if None not in here else []
        fir_ids = [h["id"] for h in fir_crossings(samples, fir_idx, max_results=26)]

    def area(item, keys, tolerance, max_points):
        label = item.get("label")
        if not label:
            pt = item["geometry"].representative_point()
            label = [pt.y, pt.x]
        return {"id": item["id"], "name": item.get("name") or fir_names.get(item["id"], ""), "lat": round(label[0], 3), "lon": round(label[1], 3),
                "label": [round(label[0], 3), round(label[1], 3)], "keys": keys,
                "poly": compact_rings(item["geometry"], tolerance, 3, max_points)}

    # sub-sectors ("LIRR-NE") come right after their FIR, so a generous cap keeps the last FIRs of a long flight
    firs = [area(fir_by_id[fid], fir_keys.get(fid, [fid]), 0.05, 200 if "-" in fid else 300) for fid in fir_ids[:60] if fid in fir_by_id]
    airport_points = [(a["latitude"], a["longitude"]) for a in (dep, arr) if a]
    tracon_by_id = {i["id"]: i for i in tracon_index()}
    tracons = [area(tracon_by_id[h["id"]], tracon_by_id[h["id"]]["keys"], 0.01, 150)
               for h in fir_crossings(airport_points, list(tracon_by_id.values()), max_results=8)]
    return {"source": source, "eet": codes, "firs": firs, "tracons": tracons,
            "visited": [f["id"] for f in firs if f["id"] in visited]}


@st.cache_data(ttl=45, show_spinner=False)
def cached_flight_bundle(cid, callsign):
    # statsim track (see flight_track.py) plus the FIRs on the route; either part may be missing without hurting the other
    result = dict(fetch_track(cid, callsign, get_secret("STATSIM_API_KEY", ""), requests.Session()))
    try:
        feed = fetch_vatsim_data() or {}
        pilot = next((p for p in feed.get("pilots", []) if str(p.get("cid")) == cid and p.get("callsign") == callsign), None)
        if pilot:
            result["atc"] = route_atc_spec(pilot, result.get("points") if result.get("ok") else [])
    except Exception:
        pass
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def load_fir_names():
    names = {}
    for icao, boundary, _prefix, name in load_vatspy_fir_rows():
        names.setdefault(boundary or icao, name)
    return names


@st.cache_data(ttl=86400, show_spinner=False)
def load_airport_key_map():
    # callsign prefix -> airport ICAOs, from the IATA/LID column of VATSpy.dat's [Airports] section ("SY-R" is also kept as "SY").
    # Controllers of US style airports log on as JFK_TWR, SCT_APP, ... rather than with the ICAO code.
    r = requests.get(VATSPY_DAT_URL, timeout=20)
    r.raise_for_status()
    keys, in_airports = {}, False
    for line in r.text.splitlines():
        text = line.strip()
        if text.startswith("["):
            in_airports = text == "[Airports]"
            continue
        if not in_airports or not text or text.startswith(";"):
            continue
        parts = text.split("|")
        if len(parts) < 5:
            continue
        icao, code = parts[0].strip().upper(), parts[4].strip().upper()
        for k in {code, code.split("-")[0]}:
            if k:
                keys.setdefault(k, []).append(icao)
    if not keys:
        raise ValueError("no airports")
    return keys


GLOBAL_OVERLAY_NAME = re.compile(r"\b(fis|military|information)\b")  # boundaries that lie on top of the normal FIRs
GLOBAL_NEEDS_MIN_AIRCRAFT = 8   # airborne aircraft in an unstaffed FIR before it is listed as "needs ATC"
GLOBAL_NEEDS_MIN_FLIGHTS = 6    # filed flights to/from an airport without any controller before it is listed


@st.cache_data(ttl=20, show_spinner=False)
def global_airspace_snapshot():
    # Airborne traffic per FIR, which FIRs are staffed and which airports have a controller, from the shared 15 s feed.
    d = fetch_vatsim_data() or {}
    pilots = d.get("pilots") or []
    controllers = d.get("controllers") or []
    atis = d.get("atis") or []
    prefixes = sorted(airport_atc_prefixes(controllers, atis))
    snap = {
        "airborne": sum(1 for p in pilots if isinstance(p, dict) and isinstance(p.get("groundspeed"), (int, float)) and p["groundspeed"] >= 50),
        "atc": sum(1 for c in controllers if isinstance(c, dict) and type(c.get("facility")) is int and 1 <= c["facility"] <= 6),
        "atc_prefixes": prefixes, "atc_airports": [], "airports_atc": 0, "firs_staffed": 0, "busiest": [], "needs_atc": [],
    }
    atc_airports = {p for p in prefixes if len(p) == 4}
    try:
        key_map = load_airport_key_map()
        for p in prefixes:
            atc_airports.update(key_map.get(p, []))
    except Exception:
        pass  # without the airport table only ICAO style callsigns are matched
    snap["atc_airports"] = sorted(atc_airports)
    snap["airports_atc"] = len(atc_airports)
    try:
        parents = [i for i in fir_index() if "-" not in i["id"]]  # sub-sectors overlap their FIR: count each aircraft once
        counts = count_pilots_in_areas(pilots, parents)
        key_to_ids = {}
        for boundary, keys in load_fir_callsign_keys().items():
            for k in keys:
                key_to_ids.setdefault(k.upper(), set()).add(boundary.split("-")[0])
        staffed = staffed_area_ids(controllers, {k: sorted(v) for k, v in key_to_ids.items()})
        names = load_fir_names()
        snap["firs_staffed"] = len(staffed)
        snap["busiest"] = sorted(
            ({"id": i, "name": names.get(i, ""), "aircraft": counts[i], "controllers": len(set(cs))} for i, cs in staffed.items() if i in counts),
            key=lambda r: (-r["aircraft"], r["id"]))[:8]
        # FIS-only and military boundaries lie on top of the normal FIRs and would double count, so "needs ATC" only counts
        # aircraft that no staffed FIR covers, never lists those overlay boundaries, and gives each aircraft to the SMALLEST
        # FIR it is in (NAT and Gander Oceanic overlap)
        staffed_items = [i for i in parents if i["id"] in staffed]

        def covered(p):
            try:
                lat, lon = float(p["latitude"]), float(p["longitude"])
            except (KeyError, TypeError, ValueError):
                return True
            pt = Point(lon, lat)
            return any(a["bounds"][0] <= lon <= a["bounds"][2] and a["bounds"][1] <= lat <= a["bounds"][3] and a["prepared"].intersects(pt)
                       for a in staffed_items)

        uncovered = [p for p in pilots if isinstance(p, dict) and isinstance(p.get("groundspeed"), (int, float)) and p["groundspeed"] >= 50 and not covered(p)]
        open_areas = [i for i in parents if i["id"] not in staffed and not GLOBAL_OVERLAY_NAME.search(names.get(i["id"], "").lower())]
        snap["needs_atc"] = sorted(
            ({"id": i, "name": names.get(i, ""), "aircraft": n} for i, n in count_pilots_smallest_area(uncovered, open_areas).items() if n >= GLOBAL_NEEDS_MIN_AIRCRAFT),
            key=lambda r: (-r["aircraft"], r["id"]))[:8]
    except Exception:
        pass  # boundary data not available right now: the panels that do not need it still work
    return snap


_ASSET_DIR = os.path.dirname(os.path.abspath(__file__))


@st.cache_data(show_spinner=False)
def _read_asset(name, mtime):
    # the mtime is part of the cache key, so editing a file shows up on the next run without restarting the server
    with open(os.path.join(_ASSET_DIR, name), encoding="utf-8") as f:
        return f.read()


def flight_map_asset(name):
    return _read_asset(name, os.path.getmtime(os.path.join(_ASSET_DIR, name)))


def classify_aircraft(ac_type, callsign):
    ac_type = str(ac_type).upper().strip()
    callsign = str(callsign).upper().strip()
    
    military_types = {
        "F16", "F18", "F15", "F22", "F35", "F4", "F5", "EFAF", "GR4", 
        "SU27", "SU35", "B52", "C17", "A400", "C130", "KC10", "K35R", 
        "E3TF", "B1B", "B2", "A10", "TOR", "H64", "UH60", "CH47", "NH90"
    }
    if ac_type in military_types: return "Military"
    military_prefixes = ("TUR", "RCH", "AME", "BAF", "IAM", "GAF", "ASY", "MIL", "NAVY", "ARMY", "AF1", "AF2")
    if callsign.startswith(military_prefixes): return "Military"
        
    ga_types = {"C150", "C152", "C172", "C182", "C206", "C208", "P28A", "PA34", "DA40", "DA42", "SR22", "SR20", "E300", "DV20"}
    if ac_type in ga_types: return "General Aviation"
        
    biz_jets = {"GLF5", "GLF6", "CL60", "C56X", "FA7X", "LJ45"}
    if ac_type in biz_jets: return "Business Jet"
        
    return "Commercial"

is_admin_route = query_params.get("admin") == "true"

if is_admin_route:
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    # An idle admin tab must not stay authenticated forever: any interaction while inside the panel refreshes the
    # timer below, so this is really an inactivity timeout, not a fixed session length.
    if st.session_state.admin_authenticated and time.time() - st.session_state.get("admin_auth_at", 0) > ADMIN_SESSION_SECONDS:
        st.session_state.admin_authenticated = False
        st.session_state.pop("admin_auth_at", None)
        _log_admin_event("session_expired")
        st.info("Your admin session timed out after being idle. Please log in again.")

    if not st.session_state.admin_authenticated:
        st.title("🛡️ VatScoreRadar // Admin Login")
        if not (ADMIN_PASSWORD or ADMIN_PASSWORD_HASH):
            st.error("Admin access is not configured. Set ADMIN_PASSWORD_HASH (or ADMIN_PASSWORD) in .streamlit/secrets.toml to enable this panel.")
            st.stop()
        lock_left = admin_lock_remaining()
        if lock_left > 0:
            st.error(f"Too many failed attempts. Try again in {int(lock_left // 60) + 1} minute(s).")
            st.stop()

        totp_pending_since = st.session_state.get("admin_totp_pending")
        if totp_pending_since and time.time() - totp_pending_since > ADMIN_TOTP_STEP_SECONDS:
            st.session_state.pop("admin_totp_pending", None)
            totp_pending_since = None
            st.warning("That took too long, enter the password again.")

        if ADMIN_TOTP_SECRET and totp_pending_since:
            st.caption("Password accepted. Enter the 6-digit code from your authenticator app.")
            totp_input = st.text_input("Authenticator code:", max_chars=6)
            tc1, tc2 = st.columns(2)
            with tc1:
                submit_totp = st.button("Verify Code", width="stretch")
            with tc2:
                if st.button("Back", width="stretch"):
                    st.session_state.pop("admin_totp_pending", None)
                    st.rerun()
            if submit_totp:
                if verify_totp(ADMIN_TOTP_SECRET, totp_input, time.time()):
                    clear_admin_failures()
                    st.session_state.pop("admin_totp_pending", None)
                    st.session_state.admin_authenticated = True
                    st.session_state.admin_auth_at = time.time()
                    _log_admin_event("login_ok", "password+totp")
                    st.success("Access Granted.")
                    st.rerun()
                else:
                    register_admin_failure()
                    _log_admin_event("login_fail", "totp")
                    st.error("Invalid or expired code.")
        else:
            passwd_input = st.text_input("Enter Admin Password:", type="password")
            if st.button("Authorize Connection"):
                if passwd_input and verify_admin_password(passwd_input):
                    if ADMIN_TOTP_SECRET:
                        st.session_state.admin_totp_pending = time.time()
                        _log_admin_event("login_step1_ok")
                        st.rerun()
                    else:
                        clear_admin_failures()
                        st.session_state.admin_authenticated = True
                        st.session_state.admin_auth_at = time.time()
                        _log_admin_event("login_ok", "password only")
                        st.success("Access Granted.")
                        st.rerun()
                else:
                    register_admin_failure()
                    _log_admin_event("login_fail", "password")
                    st.error("Invalid Secret Token.")
        st.stop()
    else:
        st.session_state.admin_auth_at = time.time()  # any interaction while inside the panel counts as activity
        st.title("🛰️ VatScoreRadar // Admin")
        top_c1, top_c2 = st.columns([0.8, 0.2])
        with top_c1:
            st.caption(f"Session stays open while active, times out {ADMIN_SESSION_SECONDS // 60} min after the last click.")
        with top_c2:
            if st.button("⬅️ Return to Live Radar", width="stretch"):
                st.session_state.admin_authenticated = False
                st.session_state.pop("admin_auth_at", None)
                _log_admin_event("logout")
                st.query_params.clear()
                st.rerun()

        with st.expander("🔐 Account security", expanded=False):
            iterations = _admin_hash_iterations()
            if ADMIN_PASSWORD_HASH and iterations and iterations >= MIN_PBKDF2_ITERATIONS:
                st.success(f"Password: pbkdf2_sha256, {iterations:,} iterations.")
            elif ADMIN_PASSWORD_HASH and iterations:
                st.warning(f"Password hash uses only {iterations:,} PBKDF2 iterations; {MIN_PBKDF2_ITERATIONS:,}+ is recommended. Regenerate ADMIN_PASSWORD_HASH.")
            else:
                st.warning("Using a plain ADMIN_PASSWORD instead of a hash. Set ADMIN_PASSWORD_HASH instead and remove ADMIN_PASSWORD.")
            if ADMIN_TOTP_SECRET:
                st.success("Two-factor authentication: enabled.")
            else:
                st.warning("Two-factor authentication: not enabled. A leaked password alone is enough to reach this panel.")
                if st.button("Generate a 2FA secret"):
                    st.session_state.admin_totp_suggestion = new_totp_secret()
                suggestion = st.session_state.get("admin_totp_suggestion")
                if suggestion:
                    st.code(suggestion, language=None)
                    st.caption("Add this to any authenticator app (Google Authenticator, Authy, ...) as a manual key (SHA1, 6 digits, "
                               "30s), then add ADMIN_TOTP_SECRET to .streamlit/secrets.toml with this value and restart the app. "
                               "This secret is shown once and never saved by the app - store it yourself.")
            st.markdown("---")
            st.caption("Recent admin security events")
            audit_rows = read_audit_events(ADMIN_AUDIT_FILE, limit=50)
            if audit_rows:
                st.dataframe(pd.DataFrame(audit_rows), hide_index=True, width="stretch")
            else:
                st.caption("No admin events recorded yet.")

        with st.expander("🩺 Site health & limits", expanded=False):
            st.caption("Every external data source this app depends on, since the server last restarted.")
            health_rows = summarize_health(_health_store())
            if health_rows:
                STATUS_ICON = {"ok": "🟢", "failing": "🔴", "unknown": "⚪"}

                def _age(seconds):
                    if seconds is None:
                        return "-"
                    if seconds < 90:
                        return f"{int(seconds)}s ago"
                    if seconds < 5400:
                        return f"{int(seconds // 60)}m ago"
                    return f"{seconds / 3600:.1f}h ago"

                table = [{"": STATUS_ICON.get(r["status"], "⚪"), "Source": r["source"], "Last OK": _age(r["seconds_since_ok"]),
                          "Last error": _age(r["seconds_since_error"]), "Error": r["last_error"] or "-",
                          "Fails in a row": r["consecutive_fails"], "OK / Fail (total)": f"{r['total_ok']} / {r['total_fail']}"}
                         for r in health_rows]
                st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
            else:
                st.caption("No data source has been used yet this run.")
            st.caption(f"statsim.net API key: {'configured' if get_secret('STATSIM_API_KEY', '') else '⚠️ NOT configured'}.")
            sync = sync_status()
            sync_mode = sync.get("mode") or ("on" if sync.get("enabled") else "missing")  # .get: a module cached from an older deploy has no "mode" yet
            if sync_mode == "off":
                st.caption("Persistent storage: ⏸️ switched off on this machine (DATA_SYNC = \"off\"): announcements, blocked CIDs, page views and logs stay local here. "
                           "Airport layouts and the event history still sync.")
            elif not sync["enabled"]:
                st.caption("Persistent storage: ⚠️ not configured (DATA_REPO / DATA_REPO_TOKEN missing), announcements, blocked CIDs and page views reset on every deploy.")
            elif sync["last_error"]:
                st.caption(f"Persistent storage: 🔴 last sync failed ({sync['last_error']}).")
            else:
                st.caption(f"Persistent storage: 🟢 GitHub data repo connected, {sync['pushes']} save(s) since this server started.")
            try:
                maybe_record()  # the admin page also keeps the event record going (the radar page does the same, at most every 6 h)
            except Exception:
                pass
            hist = events_history_status()
            if hist["last_error"]:
                st.caption(f"Event history: 🔴 last recording failed ({hist['last_error']}).")
            else:
                per_year = ", ".join(f"{y}: {n}" for y, n in hist["years"].items()) or "nothing recorded yet"
                st.caption(f"Event history: 🟢 {hist['total']} event(s) recorded ({per_year}), {hist['withdrawn']} withdrawn. Finished events stay here after VATSIM drops them.")

            st.markdown("---")
            st.caption("Site-wide request budgets (shared by every visitor)")
            limiter_rows = []
            for label, getter, key in [
                ("Flight track fetches (map)", lambda: _track_limiters()[1], "global"),
                ("VATSIM Core member lookups", lambda: _member_api_limiter(), "member"),
            ]:
                try:
                    u = getter().usage(key)
                    limiter_rows.append({"Budget": label, "Used": u["used"], "Max": u["max"], "Per": f"{u['window_seconds']}s"})
                except Exception:
                    pass
            if limiter_rows:
                st.dataframe(pd.DataFrame(limiter_rows), hide_index=True, width="stretch")
            st.caption("Per-visitor budgets (one per browser session) aren't listed here - only the site-wide ones matter for \"is everyone getting rate limited right now\".")

            st.markdown("---")
            st.caption("Force a fresh copy of a cached data source (normally refreshes on its own after its cache expires)")
            rc1, rc2, rc3, rc4 = st.columns(4)
            with rc1:
                if st.button("VATSIM feed", width="stretch"):
                    fetch_vatsim_data.clear(); st.toast("Cleared")
            with rc2:
                if st.button("Airlines list", width="stretch"):
                    load_vatsim_radar_airlines.clear(); st.toast("Cleared")
            with rc3:
                if st.button("VATSpy.dat", width="stretch"):
                    load_country_names.clear(); load_vatspy_fir_rows.clear(); st.toast("Cleared")
            with rc4:
                if st.button("FIR / TRACON shapes", width="stretch"):
                    load_fir_raw_geometries.clear(); load_fir_features_raw.clear(); load_tracon_features_raw.clear(); st.toast("Cleared")

        with st.expander("📢 Site-wide announcement", expanded=False):
            now_utc = datetime.now(timezone.utc)
            current = read_banner_raw(SITE_BANNER_FILE)
            if current:
                starts_at = _parse_banner_ts(current["starts_at"])
                expires_at = _parse_banner_ts(current["expires_at"])
                if expires_at and now_utc >= expires_at:
                    st.caption("Previous announcement has ended and will be cleaned up on the next page view.")
                elif starts_at and now_utc < starts_at:
                    end_note = f", auto-removes {current['expires_at']}" if current.get("expires_at") else ""
                    st.info(f"Scheduled ({current['level']}) - goes live {current['starts_at']}{end_note}: {current['text']}")
                else:
                    end_note = f", auto-removes {current['expires_at']}" if current.get("expires_at") else ""
                    st.info(f"Currently live ({current['level']}, set {current['set_at']}{end_note}): {current['text']}")
            banner_text = st.text_area("Message", value=current["text"] if current else "", max_chars=280, key="banner_text_input")
            banner_level = st.selectbox("Style", ["info", "warning", "error"],
                                        index=["info", "warning", "error"].index(current["level"]) if current else 0, key="banner_level_input")

            sc1, sc2 = st.columns(2)
            with sc1:
                schedule_start = st.checkbox("Schedule for later (otherwise publishes immediately)", key="banner_schedule_start")
                if schedule_start:
                    start_date = st.date_input("Goes live on (UTC)", value=now_utc.date(), key="banner_start_date")
                    start_time = st.time_input("Goes live at (UTC)", value=now_utc.time().replace(microsecond=0), key="banner_start_time")
            with sc2:
                schedule_end = st.checkbox("Auto-remove at a specific date/time", key="banner_schedule_end")
                if schedule_end:
                    end_date = st.date_input("Auto-removes on (UTC)", value=now_utc.date(), key="banner_end_date")
                    end_time = st.time_input("Auto-removes at (UTC)", value=now_utc.time().replace(microsecond=0), key="banner_end_time")

            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("Publish", width="stretch"):
                    starts_at = datetime.combine(start_date, start_time, tzinfo=timezone.utc) if schedule_start else None
                    expires_at = datetime.combine(end_date, end_time, tzinfo=timezone.utc) if schedule_end else None
                    if starts_at and expires_at and expires_at <= starts_at:
                        st.error("The auto-remove time must be after the go-live time.")
                    else:
                        write_banner(SITE_BANNER_FILE, banner_text, banner_level, starts_at=starts_at, expires_at=expires_at)
                        push(SITE_BANNER_FILE, "announcement published")
                        _log_admin_event("banner_set", banner_text[:100])
                        st.rerun()
            with bc2:
                if st.button("Clear announcement", width="stretch"):
                    clear_banner(SITE_BANNER_FILE)
                    push(SITE_BANNER_FILE, "announcement cleared")
                    _log_admin_event("banner_cleared")
                    st.rerun()

        with st.expander("🚫 Redacted CIDs", expanded=False):
            st.caption("A blocked CID's flights/sessions are hidden from CID Stats (whole page), the Network Stats pilot list, the "
                       "Airport page's departure/arrival tables, and the Leaderboard.")
            rb1, rb2 = st.columns([0.3, 0.7])
            with rb1:
                block_cid = st.text_input("CID", key="block_cid_input", max_chars=10)
            with rb2:
                block_reason = st.text_input("Reason (optional, for your own reference)", key="block_reason_input")
            if st.button("Block this CID"):
                if block_cid.strip().isdigit():
                    add_to_blocklist(CID_BLOCKLIST_FILE, block_cid.strip(), block_reason)
                    push(CID_BLOCKLIST_FILE, "cid blocked")
                    _log_admin_event("cid_blocked", block_cid.strip())
                    st.rerun()
                else:
                    st.error("CID must be numeric.")
            blocked = load_blocklist(CID_BLOCKLIST_FILE)
            if blocked:
                for bcid, meta in sorted(blocked.items()):
                    row_c1, row_c2 = st.columns([0.85, 0.15])
                    with row_c1:
                        st.caption(f"**{bcid}** - {meta['reason'] or 'no reason given'} (blocked {meta['added_at']})")
                    with row_c2:
                        if st.button("Unblock", key=f"unblock_{bcid}"):
                            remove_from_blocklist(CID_BLOCKLIST_FILE, bcid)
                            push(CID_BLOCKLIST_FILE, "cid unblocked")
                            _log_admin_event("cid_unblocked", bcid)
                            st.rerun()
            else:
                st.caption("No CIDs are currently blocked.")

        st.markdown("---")
        if os.path.exists(LOG_FILE):
            df_logs = pd.read_csv(LOG_FILE)
            df_logs['Timestamp'] = pd.to_datetime(df_logs['Timestamp'])
            time_delta = (datetime.now() - df_logs['Timestamp']).dt.total_seconds()

            total_unique = len(df_logs['Session_ID'].unique())
            active_now = len(df_logs[time_delta < 300]['Session_ID'].unique())

            view_rows = summarize_views(PAGE_VIEWS_FILE)
            top_page = f"{view_rows[0]['page']} ({view_rows[0]['count']})" if view_rows else "N/A"

            adm_c1, adm_c2, adm_c3 = st.columns(3)
            with adm_c1: st.metric(label="🟢 Active Users (Last 5 Mins)", value=active_now)
            with adm_c2: st.metric(label="👥 Total Unique Connections", value=total_unique)
            with adm_c3: st.metric(label="📄 Most-Viewed Page (all time)", value=top_page)

            st.markdown("<br>", unsafe_allow_html=True)
            with st.expander("📄 Page views", expanded=False):
                st.caption("One count per browser session per page (a reload of the same page doesn't count twice).")
                pv_c1, pv_c2 = st.columns(2)
                with pv_c1:
                    st.caption("Last 24 hours")
                    recent = summarize_views(PAGE_VIEWS_FILE, hours=24)
                    st.dataframe(pd.DataFrame(recent) if recent else pd.DataFrame([{"page": "-", "count": 0}]), hide_index=True, width="stretch")
                with pv_c2:
                    st.caption("All time")
                    st.dataframe(pd.DataFrame(view_rows) if view_rows else pd.DataFrame([{"page": "-", "count": 0}]), hide_index=True, width="stretch")

            st.markdown("<br>", unsafe_allow_html=True)
            if not st.session_state.get("confirm_wipe_logs"):
                btn_c1, btn_c2 = st.columns([0.8, 0.2])
                with btn_c1: st.subheader("👥 Live Session Logs")
                with btn_c2:
                    if st.button("🗑️ Wipe Logs", width='stretch'):
                        st.session_state.confirm_wipe_logs = True
                        st.rerun()
            else:
                st.subheader("👥 Live Session Logs")
                st.warning("This permanently deletes every visitor session log. This cannot be undone.")
                wc1, wc2 = st.columns(2)
                with wc1:
                    if st.button("Confirm wipe", width="stretch"):
                        os.remove(LOG_FILE)
                        init_log_file()
                        push(LOG_FILE, "visitor session log wiped")
                        _log_admin_event("logs_wiped")
                        st.session_state.confirm_wipe_logs = False
                        st.rerun()
                with wc2:
                    if st.button("Cancel", width="stretch"):
                        st.session_state.confirm_wipe_logs = False
                        st.rerun()

            df_display = df_logs.sort_values(by="Timestamp", ascending=False).copy()
            df_display['Timestamp'] = df_display['Timestamp'].dt.strftime('%H:%M:%S || %Y-%m-%d')
            df_display = df_display[["Timestamp", "Device_Type", "OS", "Browser", "Last_Action"]].rename(
                columns={"Device_Type": "Device Type", "Last_Action": "Last Action"})
            st.dataframe(df_display, hide_index=True, width='stretch')
        st.stop()


set_browser_title(labels=["Leaderboard", "Selected FIR Focus", "Global Stats & ATC", "Anomaly Radar", "CID Stats", "Network Stats", "Events", "Project Roadmap"])

data = fetch_vatsim_data()
if data:
    # the airports with the most filed flights right now get their ground layout fetched in the background (at most once an hour,
    # one polite request at a time), so an ATC Replay of a busy airport finds it ready instead of waiting for OpenStreetMap
    try:
        _traffic = Counter()
        for _p in data.get("pilots", []):
            _fp = _p.get("flight_plan") or {}
            for _k in ("departure", "arrival"):
                _code = str(_fp.get(_k, "")).strip().upper()
                if len(_code) == 4:
                    _traffic[_code] += 1
        _csv_airports = load_csv_database()
        warm_in_background("popular", [(c, _csv_airports[c]["latitude"], _csv_airports[c]["longitude"]) for c, _n in _traffic.most_common(40) if c in _csv_airports][:12])
        maybe_record()  # VATSIM drops an event from its list once it is over: keep our own record of every event we see (at most every 6 h)
    except Exception:
        pass
global_grouped_firs = load_and_group_fir_boundaries()

if data:
    pilots = data.get("pilots", [])
    controllers = data.get("controllers", [])

    airports_coords_map = get_coordinates_from_library(pilots)

    title_col, refresh_col, emoji_col = st.columns([0.88, 0.06, 0.06])
    with title_col: st.title("VatScoreRadar")

    with refresh_col:
        st.write("<div style='padding-top:25px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="top-emoji-btn">', unsafe_allow_html=True)
        refresh_clicked = st.button("🔄", help="Force Manual Refresh Now")
        st.markdown('</div>', unsafe_allow_html=True)
        if refresh_clicked:
            fetch_vatsim_data.clear()
    
    with emoji_col:
        st.write("<div style='padding-top:25px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="top-emoji-btn">', unsafe_allow_html=True)
        settings_clicked = st.button("⚙️", help="Click to toggle Column visibility and Fleet filters")
        st.markdown('</div>', unsafe_allow_html=True)

    try:
        render_banner(read_banner(SITE_BANNER_FILE))
    except Exception:
        pass

    if "show_panel" not in st.session_state: st.session_state.show_panel = False
    if settings_clicked:
        st.session_state.show_panel = not st.session_state.show_panel

    all_columns = ["Origin", "Destination", "Aircraft", "Category", "Altitude (FT)", "Speed (KT)", "Squawk"]
    if "visible_columns" not in st.session_state: st.session_state.visible_columns = all_columns.copy()
    if "fleet_filter_selection" not in st.session_state: st.session_state.fleet_filter_selection = "All Flights"
    if "rules_filter_selection" not in st.session_state: st.session_state.rules_filter_selection = "All Rules"
    if "airline_isolation_filter" not in st.session_state: st.session_state.airline_isolation_filter = ""

    if st.session_state.show_panel:
        with st.container():
            st.markdown("### ⚙️ Live Radar Customizer")
            cfg_col1, cfg_col2 = st.columns(2)
            with cfg_col1:
                st.session_state.visible_columns = st.multiselect("Select Table Columns:", options=all_columns, default=st.session_state.visible_columns)
                st.session_state.airline_isolation_filter = st.text_input(
                    "Airline Call-Sign Isolation (ICAO):", 
                    value=st.session_state.airline_isolation_filter,
                    placeholder="e.g. THY, PGT, BAW (Leave empty for all)"
                )
            with cfg_col2:
                st.session_state.fleet_filter_selection = st.radio("Fleet Category Filter:", ["All Flights", "Commercial Only", "General Aviation Only", "Business Jet Only", "Military Only"], horizontal=True)
                st.session_state.rules_filter_selection = st.radio("Flight Rules Filter:", ["All Rules", "IFR Only", "VFR Only"], horizontal=True)
            st.markdown("---")

    @st.fragment(run_every=20)
    def render_network_counts():
        d = fetch_vatsim_data()
        nc_col1, nc_col2, nc_col3 = st.columns(3)
        with nc_col1: st.metric(label="Total Live Pilots Worldwide", value=len(d.get("pilots", [])) if d else len(pilots))
        with nc_col2: st.metric(label="Total Active ATCs", value=len(d.get("controllers", [])) if d else len(controllers))
        with nc_col3: st.metric(label="Last Sync", value=f" {datetime.now(timezone.utc).strftime('%H:%M:%S Z')}")

    render_network_counts()

    fir_pilots = []
    filtered_pilots_raw = []

    if is_valid_fir_prefix(st.query_params.get("saved_fir")):
        st.session_state.current_fir_prefix = st.query_params["saved_fir"]
    
    if "current_fir_prefix" not in st.session_state:
        st.session_state.current_fir_prefix = "LT"

    # pinned regions live in the URL (?pins=EG,ED) and in the browser's localStorage (pin_sync.py): a fresh visit without the URL gets them
    # back through this hidden field, which the sync script fills
    if "pinned_firs" not in st.session_state:
        st.session_state.pinned_firs = [p for p in str(st.query_params.get("pins", "")).split(",") if is_valid_fir_prefix(p)][:8]
    restored_pins = st.text_input("vs_pins_restore", key="vs_pins_restore", label_visibility="collapsed", max_chars=40)
    if restored_pins and not st.session_state.pinned_firs and not st.session_state.get("pins_cleared", False):
        st.session_state.pinned_firs = [p for p in restored_pins.split(",") if is_valid_fir_prefix(p)][:8]
        if st.session_state.pinned_firs:
            st.query_params["pins"] = ",".join(st.session_state.pinned_firs)

    try:
        country_names = load_country_names()
    except Exception:
        country_names = {}

    def region_name(prefix):
        return FIR_FALLBACK_NAMES.get(prefix) or (f"{country_names[prefix]} Airspace Hub" if prefix in country_names else f"{prefix} Airspace Zone")

    # options are the plain prefixes (stable values); the counts only live in the label, so a changing traffic number never resets the choice.
    # Order: pinned, the well-known regions, then every other region that has traffic right now, busiest first.
    fir_counts = traffic_by_region(pilots)
    # regions with only a handful of aircraft would just clutter the list (search finds them if pinned / selected); a region is known when it has
    # an airspace boundary or a country name (Canada's airports are CY.., its FIRs CZ..)
    listed_counts = {p: n for p, n in fir_counts.items() if n >= MIN_REGION_AIRCRAFT}
    fir_options = order_regions(listed_counts, set(global_grouped_firs) | set(country_names), FEATURED, st.session_state.pinned_firs, st.session_state.current_fir_prefix)

    def region_label(prefix):
        mark = "📌 " if prefix in st.session_state.pinned_firs else ("★ " if prefix in FEATURED else "")
        count = fir_counts.get(prefix, 0)
        return f"{mark}{prefix} - {region_name(prefix)}" + (f" · {count} aircraft" if count else "")

    calculated_index = fir_options.index(st.session_state.current_fir_prefix) if st.session_state.current_fir_prefix in fir_options else 0

    if is_valid_callsign(st.query_params.get("selected_callsign")):
        st.session_state.active_popup = st.query_params["selected_callsign"]
    if "active_popup" not in st.session_state:
        st.session_state.active_popup = ""

    # These three tabs are read-only network-wide views (no interactive filters of
    # their own besides simple display toggles), so each gets its own fragment that
    # independently re-fetches (cached, so cheap) and redraws itself every 20s.
    # Fragments only rerun their own body — everything outside them (FIR Focus
    # controls, settings panel, VIP watchlist inputs) is untouched by the tick.
    LB_TOP = 50        # rows in every ranking table
    LB_CHART_TOP = 15  # bars in every ranking chart

    @st.fragment(run_every=20)
    def render_leaderboard():
        d = fetch_vatsim_data()
        blocklist = load_blocklist(CID_BLOCKLIST_FILE)
        lb_pilots = [p for p in (d.get("pilots", []) if d else []) if str((p or {}).get("cid", "")) not in blocklist]
        lb_controllers = [c for c in (d.get("controllers", []) if d else []) if str((c or {}).get("cid", "")) not in blocklist]
        now = datetime.now(timezone.utc)
        flight = flight_records(lb_pilots, load_airports(), top=LB_TOP)
        members = member_records(lb_pilots, lb_controllers, now, top=LB_TOP)

        def duration(minutes):
            return f"{minutes // 1440} d {(minutes % 1440) // 60} h" if minutes >= 1440 else f"{minutes // 60} h {minutes % 60:02d} min"

        def style_chart(fig, height=300):
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=6, b=0), height=height,
                              font=dict(family="ui-monospace, 'Cascadia Code', monospace", color=UI_TEXT, size=11), legend_title_text="")
            fig.update_xaxes(gridcolor=UI_LINE, zeroline=False, title="")
            fig.update_yaxes(gridcolor=UI_LINE, zeroline=False, title="")
            return fig

        # key, ranking name, card title (None = no card), entries, value text, colour, bar height (None = a CID rank has no meaningful bar),
        # header of the value column, description
        records = [
            ("altitude", "Altitude", "Highest altitude", flight["altitude"], lambda e: f"{int(e['value']):,} ft", CYAN, lambda e: e["value"],
             "Altitude", "The highest reported altitude among the pilots online right now."),
            ("speed", "Ground speed", "Highest ground speed", flight["speed"], lambda e: f"{int(e['value'])} kt", EMERALD, lambda e: e["value"],
             "Ground speed", "The highest ground speed among the pilots online right now."),
            ("slow", "Slowest airborne", "Lowest ground speed (airborne)", flight["slow"], lambda e: f"{int(e['value'])} kt", AMBER, lambda e: e["value"],
             "Ground speed", "The lowest ground speed among aircraft that are airborne (above 3,000 ft and faster than 45 kt)."),
            ("session", "Longest sessions", "Longest continuous session", members["session"], lambda e: duration(e["value"]), VIOLET,
             lambda e: round(e["value"] / 60, 1), "Time online", "Pilots and controllers that have been connected the longest without a break (bars show hours)."),
            ("route", "Longest routes", None, flight["route"], lambda e: f"{e['value']:,} NM", VIOLET, lambda e: e["value"],
             "Distance", "The longest filed routes, measured as the great-circle distance between departure and arrival."),
            ("away", "Farthest out", None, flight["away"], lambda e: f"{e['value']:,} NM", ROSE, lambda e: e["value"],
             "Distance from departure", "Airborne aircraft that are the farthest from their departure airport right now."),
            ("senior", "Most senior", None, members["senior"], lambda e: f"CID {e['value']}", CYAN, None,
             "CID", "Members online right now with the lowest CID. A lower CID belongs to an older VATSIM account."),
            ("newest", "Newest", None, members["newest"], lambda e: f"CID {e['value']}", AMBER, None,
             "CID", "Members online right now with the highest CID, that is the most recently registered accounts."),
        ]

        # the four headline records; each card also names the runners-up, so most of the picture is visible without a click
        st.markdown(card_css() + """<style>
            @keyframes lbFadeA { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
            @keyframes lbFadeB { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
            .st-key-lb_rank_0 { animation: lbFadeA 0.4s ease-out; }
            .st-key-lb_rank_1 { animation: lbFadeB 0.4s ease-out; }
            [data-testid="stPills"] button, [data-testid="stButtonGroup"] button { transition: background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease; }
            @media (prefers-reduced-motion: reduce) { .st-key-lb_rank_0, .st-key-lb_rank_1 { animation: none; } }
        </style>""", unsafe_allow_html=True)
        headline = [r for r in records if r[2]]
        for col, (_key, _name, title, entries, fmt, color, _bar, _value_header, _description) in zip(st.columns(len(headline)), headline):
            with col:
                if entries:
                    runners = [f"{rank}.  {e['callsign']}  ·  {fmt(e)}" for rank, e in enumerate(entries[1:3], 2)]
                    st.markdown(record_card(title, fmt(entries[0]), entries[0]["callsign"], entries[0]["name"], color, runners), unsafe_allow_html=True)
                else:
                    st.markdown(record_card(title, "-", "No data", "", color), unsafe_allow_html=True)

        # the full rankings: one picker (pills, not a second tab bar), then chart, search and table of the chosen record
        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.subheader("Rankings")
        names = [r[1] for r in records]
        chosen = st.pills("Ranking", names, default=names[0], key="lb_ranking", label_visibility="collapsed") or names[0]
        key, _name, _title, entries, fmt, color, bar, value_header, description = next(r for r in records if r[1] == chosen)
        # the container's key flips whenever another ranking is picked: the changed class name restarts the CSS fade below, while the 20 s refresh
        # and typing in the search box keep the key (and so do not replay it)
        if st.session_state.get("lb_prev_ranking") != key:
            st.session_state["lb_prev_ranking"] = key
            st.session_state["lb_fade"] = 1 - st.session_state.get("lb_fade", 0)
        with st.container(key=f"lb_rank_{st.session_state.get('lb_fade', 0)}"):
            st.caption(description)
            if not entries:
                st.info("No data available right now.")
            else:
                rows = []
                for rank, e in enumerate(entries, 1):
                    # the member cell links to CID Stats and shows the name (the CID when the pilot gave no name): the link text sits after the "#"
                    label = e["name"] if e["name"] and e["name"] != str(e["cid"]) else (str(e["cid"]) if e["cid"] else "-")
                    rows.append({"Rank": rank, "Callsign": e["callsign"], value_header: fmt(e), "Route": e["route"].replace("->", "→"),
                                 "Member": f"{page_url('CID_Stats', cid=e['cid'])}#{label}" if e["cid"] else None, "_label": label, "_bar": bar(e) if bar else 0})
                df = pd.DataFrame(rows)
                if bar:
                    fig = px.bar(df.head(LB_CHART_TOP), x="Callsign", y="_bar", template="plotly_dark", color_discrete_sequence=[color], custom_data=[value_header])
                    fig.update_traces(hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>")
                    fig.update_layout(transition=dict(duration=400, easing="cubic-in-out"))
                    st.plotly_chart(style_chart(fig), width="stretch", config={"displayModeBar": False})
                if not (df["Route"] != "").any():
                    df = df.drop(columns=["Route"])
                query = st.text_input("Search", key=f"lb_q_{key}", placeholder="Search callsign, name or CID…", label_visibility="collapsed", max_chars=60).strip()
                if query:
                    haystack = df["Callsign"] + " " + df["_label"] + " " + df["Member"].fillna("").str.extract(r"cid=(\d+)")[0].fillna("")
                    df = df[haystack.str.contains(query, case=False, regex=False)]
                df = df.drop(columns=["_label", "_bar"])
                st.caption(f"Showing {len(df)} of {len(entries)}")
                st.dataframe(df, hide_index=True, width="stretch", height=min(460, 38 + 35 * max(len(df), 1)),
                             column_config={"Rank": st.column_config.NumberColumn("Rank", width=60),
                                            "Member": st.column_config.LinkColumn("Member", display_text=r"#(.*)$")})


        st.markdown(f'<div style="margin-top:28px;font-size:11px;color:#475569;">Live · refreshes every 20s · last sync {now:%H:%M:%S} Z · '
                    f'values come from the live VATSIM data feed</div>', unsafe_allow_html=True)

    @st.fragment(run_every=20)
    def render_global_stats():
        d = fetch_vatsim_data()
        gs_pilots = d.get("pilots", []) if d else []

        dep_airports, arr_airports, aircraft_types = [], [], []
        # Flight-plan fields are free text typed by pilots, so only accept plain ICAO-style tokens.
        token_ok = re.compile(r"[A-Z0-9]{2,8}").fullmatch
        for p in gs_pilots:
            fplan = p.get("flight_plan") or {}
            dep = fplan.get("departure", "").strip().upper()
            arr = fplan.get("arrival", "").strip().upper()
            ac_type = fplan.get("aircraft", "").split("/")[0].strip().upper() or "N/A"
            if token_ok(dep): dep_airports.append(dep)
            if token_ok(arr): arr_airports.append(arr)
            if ac_type != "N/A" and token_ok(ac_type): aircraft_types.append(ac_type)

        snap = global_airspace_snapshot()
        prefixes = set(snap["atc_prefixes"])
        atc_airports = set(snap["atc_airports"])
        has_atc = lambda icao: icao in atc_airports or airport_has_atc(icao, prefixes)
        airport_link = st.column_config.LinkColumn("Airport", display_text=r"icao=([A-Z0-9]+)", help="Click to open the airport page")

        st.subheader("Global Network Insights")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Airborne Now", f"{snap['airborne']:,}")
        k2.metric("ATC Positions Online", f"{snap['atc']:,}")
        k3.metric("Airports With ATC", f"{snap['airports_atc']:,}")
        k4.metric("Airspaces Staffed", f"{snap['firs_staffed']:,}")

        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            st.markdown("### 📍 Busiest Hubs")
            hub_view = st.radio("Select Focus:", ["🛫 Top Departures", "🛬 Top Arrivals"], horizontal=True, label_visibility="collapsed")
            arrivals = "Arrivals" in hub_view
            rows = hub_rows(dep_airports, arr_airports, "arrivals" if arrivals else "departures", top_n=8)
            st.write("**Top Flight Arrivals Currently:**" if arrivals else "**Top Flight Departures Currently:**")
            if rows:
                df_hubs = pd.DataFrame([{"Airport": page_url("Airport", icao=r["icao"]), "Flights": r["count"],
                                         "ATC": "online" if has_atc(r["icao"]) else "none"} for r in rows])
                st.dataframe(df_hubs, hide_index=True, width="stretch", column_config={
                    "Airport": airport_link,
                    "Flights": st.column_config.ProgressColumn("Flights", min_value=0, max_value=max(r["count"] for r in rows), format="%d")})
        with col_g2:
            st.markdown("### ✈️ Fleet Distribution")
            fleet = fleet_summary(aircraft_types, top_n=8)
            if fleet["rows"]:
                df_fleet = pd.DataFrame([{"Type": r["type"], "Aircraft": r["count"], "Share": r["share"]} for r in fleet["rows"]])
                st.dataframe(df_fleet, hide_index=True, width="stretch", column_config={
                    "Share": st.column_config.ProgressColumn("Share", min_value=0, max_value=max(r["share"] for r in fleet["rows"]), format="%.1f%%")})
                st.caption(f"Wide-body {fleet['wide_pct']}% · other {fleet['other_pct']}% of {fleet['total']:,} filed flights")
        with col_g3:
            st.markdown("### 👑 Busiest Airspaces (ATC)")
            if snap["busiest"]:
                df_busy = pd.DataFrame([{"Airspace": r["id"], "Name": r["name"], "Aircraft": r["aircraft"], "ATC": r["controllers"]} for r in snap["busiest"]])
                st.dataframe(df_busy, hide_index=True, width="stretch", column_config={
                    "Aircraft": st.column_config.ProgressColumn("Aircraft", min_value=0, max_value=max(r["aircraft"] for r in snap["busiest"]) or 1, format="%d"),
                    "ATC": st.column_config.NumberColumn("ATC", help="Controllers on this airspace", format="%d")})
                st.caption("Aircraft currently airborne inside each staffed FIR.")
            else:
                st.info("No staffed airspace with traffic right now.")

        st.markdown("### 🎯 Where ATC Is Needed")
        need_fir, need_apt = st.columns(2)
        with need_fir:
            st.write("**Airspaces with traffic but no controller**")
            if snap["needs_atc"]:
                st.dataframe(pd.DataFrame([{"Airspace": r["id"], "Name": r["name"], "Aircraft": r["aircraft"]} for r in snap["needs_atc"]]),
                             hide_index=True, width="stretch")
            else:
                st.caption(f"Every airspace with {GLOBAL_NEEDS_MIN_AIRCRAFT}+ aircraft airborne has a controller.")
        with need_apt:
            st.write("**Airports with flights but no controller**")
            totals = Counter(dep_airports) + Counter(arr_airports)
            missing = sorted(((k, n) for k, n in totals.items() if len(k) == 4 and n >= GLOBAL_NEEDS_MIN_FLIGHTS and not has_atc(k)),
                             key=lambda kv: (-kv[1], kv[0]))[:8]
            if missing:
                st.dataframe(pd.DataFrame([{"Airport": page_url("Airport", icao=k), "Flights": n} for k, n in missing]), hide_index=True,
                             width="stretch", column_config={"Airport": airport_link})
            else:
                st.caption(f"Every airport with {GLOBAL_NEEDS_MIN_FLIGHTS}+ filed flights has a controller.")
        st.caption("Airspaces count aircraft airborne right now; airports count flights filed from or to them.")

    SEVERITY_LABEL = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟡 Low"}

    AN_SEV_COLOR = {"high": "#fb7185", "medium": "#fb923c", "low": "#facc15"}
    # Motion only where the data changes (a new row, a row that just went away, a counter that changed, the refresh cycle); nothing loops or glows,
    # and everything is switched off for visitors who ask their system for reduced motion.
    AN_CSS = """<style>
.an-wrap { overflow-x: auto; margin: 6px 0 4px; }
.an-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.an-table th { text-align: left; font-weight: 600; color: #94a3b8; padding: 8px 10px; border-bottom: 1px solid #1f2937; white-space: nowrap; }
.an-table td { padding: 8px 10px; border-bottom: 1px solid #161c2b; color: #e8eef7; vertical-align: top; }
.an-table td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.an-table td:first-child { border-left: 3px solid transparent; white-space: nowrap; }
.an-table tr.sev-high td:first-child { border-left-color: #fb7185; }
.an-table tr.sev-medium td:first-child { border-left-color: #fb923c; }
.an-table tr.sev-low td:first-child { border-left-color: #facc15; }
.an-table tr.sev-watch td:first-child { border-left-color: #60a5fa; }
.an-table a { color: #60a5fa; text-decoration: none; }
.an-table a:hover { text-decoration: underline; }
.an-table tr[data-an-lat] { cursor: pointer; }
.an-table tr[data-an-lat]:hover td { background: rgba(148, 163, 184, 0.07); }
.an-table tr.is-new { animation: anFlash 1.6s ease-out; }
.an-table tr.is-leaving { animation: anLeave 1.2s ease-in forwards; }
@keyframes anFlash { from { background-color: rgba(251, 191, 36, 0.16); } to { background-color: transparent; } }
@keyframes anLeave { from { opacity: 1; } to { opacity: 0; visibility: collapse; } }
.an-tick { animation: anTick 0.35s ease-out; }
@keyframes anTick { from { opacity: 0.3; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.an-refresh { height: 2px; background: #1f2937; border-radius: 1px; overflow: hidden; margin: 8px 0 3px; }
.an-refresh i { display: block; height: 100%; background: #334155; transform-origin: left; }
.an-refresh.cycle-a i { animation: anCycleA 20s linear forwards; }
.an-refresh.cycle-b i { animation: anCycleB 20s linear forwards; }
@keyframes anCycleA { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes anCycleB { from { transform: scaleX(0); } to { transform: scaleX(1); } }
.an-meta { color: #64748b; font-size: 12px; }
@media (prefers-reduced-motion: reduce) {
  .an-table tr.is-new, .an-tick, .an-refresh i { animation: none !important; }
  .an-table tr.is-leaving { display: none; }
}
</style>"""

    def an_card(label, value, color, tick):
        return (f'<div class="vs-card"><div class="vs-kpi-label">{html_escape(label)}</div>'
                f'<div class="vs-kpi-val{" an-tick" if tick else ""}" style="color:{color};">{html_escape(str(value))}</div></div>')

    def an_cid_cell(cid):
        cid = str(cid)
        if cid.isdigit():
            return f'<a href="{html_escape(page_url("CID_Stats", cid=cid))}" target="_blank" rel="noopener">{html_escape(cid)}</a>'
        return html_escape(cid)

    def an_row_html(cls, severity_text, title, callsign, details, aircraft, altitude, speed, cid, since, lat=None, lon=None):
        pos = f' data-an-lat="{lat:.5f}" data-an-lon="{lon:.5f}" data-an-cs="{html_escape(str(callsign))}"' if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else ""
        return (f'<tr class="{cls}"{pos}><td>{html_escape(severity_text)}</td><td>{html_escape(title)}</td><td><b>{html_escape(str(callsign))}</b></td><td>{html_escape(details)}</td>'
                f'<td>{html_escape(str(aircraft))}</td><td class="num">{int(altitude or 0):,}</td><td class="num">{int(speed or 0):,}</td><td>{an_cid_cell(cid)}</td><td>{html_escape(since)}</td></tr>')

    @st.fragment(run_every=20)
    def render_anomaly_table():
        d = fetch_vatsim_data()
        an_pilots = d.get("pilots", []) if d else []
        anomaly_update(an_pilots, anomaly_feed_time(d))
        view = anomaly_view()
        blocked = load_blocklist(CID_BLOCKLIST_FILE)  # a redacted member is not listed here either
        active = [row for row in view["active"] if row["a"]["cid"] not in blocked]
        recent = [row for row in view["recent"] if row["a"]["cid"] not in blocked]
        vip_cid_array = [c.strip() for c in st.session_state.vip_cids.split(",") if c.strip()]
        vip_callsign_array = [cs.strip().upper() for cs in st.session_state.vip_callsigns.split(",") if cs.strip()]
        feed_t = view["feed_t"] or time.time()

        def ago(t):
            minutes = max(int((feed_t - t) // 60), 0)
            return "just now" if minutes < 1 else (f"{minutes} min" if minutes < 90 else f"{minutes // 60} h {minutes % 60:02d} min")

        st.markdown(card_css() + AN_CSS, unsafe_allow_html=True)
        counts = {sev: sum(1 for row in active if row["a"]["severity"] == sev) for sev in SEVERITY_LABEL}
        prev_counts = st.session_state.get("an_prev_counts", {})
        cur_counts = {}
        kpis = st.columns(4)
        for col, (label, value, color) in zip(kpis, [("High", counts["high"], ROSE), ("Medium", counts["medium"], AMBER), ("Low", counts["low"], CYAN),
                                                      ("Recent (2 h)", len(recent), UI_TEXT)]):
            cur_counts[label] = value
            with col:
                st.markdown(an_card(label, value, color, label in prev_counts and prev_counts[label] != value), unsafe_allow_html=True)
        st.session_state["an_prev_counts"] = cur_counts

        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        shown_sev = st.multiselect("Show", list(SEVERITY_LABEL.values()), default=[SEVERITY_LABEL["high"]], key="an_severity", label_visibility="collapsed")
        body = []
        for p in an_pilots:
            cid = str(p.get("cid", ""))
            callsign = p.get("callsign", "N/A")
            if cid in vip_cid_array or str(callsign).upper() in vip_callsign_array:
                fplan = p.get("flight_plan") or {}
                body.append(an_row_html("sev-watch", "🎯 Watchlist", "Watchlist match", callsign, f"Pilot is online. Route: {fplan.get('departure', '')} to {fplan.get('arrival', '')}",
                                        (fplan.get("aircraft", "") or "N/A").split("/")[0] or "N/A", p.get("altitude", 0), p.get("groundspeed", 0), cid, "-", p.get("latitude"), p.get("longitude")))
        for row in active:
            a = row["a"]
            if SEVERITY_LABEL[a["severity"]] not in shown_sev:
                continue
            cls = f"sev-{a['severity']}" + (" is-new" if feed_t - row["first"] <= 30 else "")
            body.append(an_row_html(cls, SEVERITY_LABEL[a["severity"]], a["title"], a["callsign"], a["details"], a["aircraft"], a["altitude"], a["speed"], a["cid"], ago(row["first"]), a.get("lat"), a.get("lon")))
        # an anomaly that went away in the latest update fades out here once, before it only lives in the "Recent" list
        for r in recent:
            a = r["a"]
            if r["ended_now"] and SEVERITY_LABEL[a["severity"]] in shown_sev:
                body.append(an_row_html(f"sev-{a['severity']} is-leaving", SEVERITY_LABEL[a["severity"]], a["title"], a["callsign"], a["details"], a["aircraft"], a["altitude"], a["speed"], a["cid"], "ended", a.get("lat"), a.get("lon")))

        # a new emergency squawk pops up once per browser session, without anyone having to watch the table
        toasted = st.session_state.setdefault("an_toasted", set())
        for row in active:
            if row["a"]["severity"] == "high" and row["key"] not in toasted:
                toasted.add(row["key"])
                if feed_t - row["first"] <= 120:
                    st.toast(f"{row['a']['callsign']}: {row['a']['title']}", icon="🚨")

        if body:
            head = "".join(f"<th>{h}</th>" for h in ("Severity", "Type", "Callsign", "Details", "Aircraft", "Altitude (ft)", "Speed (kt)", "CID", "Since"))
            st.markdown(f'<div class="an-wrap"><table class="an-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)
        else:
            st.success("No anomalies or emergencies at the moment.")

        if body:
            by_cid = {(str(p.get("cid", "")), str(p.get("callsign", ""))): p for p in an_pilots}
            grouped = {}
            for r in active:
                a = r["a"]
                if SEVERITY_LABEL[a["severity"]] not in shown_sev or not isinstance(a.get("lat"), (int, float)) or not isinstance(a.get("lon"), (int, float)):
                    continue
                g = grouped.setdefault((str(a["cid"]), str(a["callsign"])), {"lat": a["lat"], "lon": a["lon"], "callsign": str(a["callsign"]), "aircraft": a["aircraft"], "alt": a["altitude"],
                                                                          "gs": a["speed"], "severity": a["severity"], "titles": [], "heading": (by_cid.get((str(a["cid"]), str(a["callsign"]))) or {}).get("heading", 0)})
                if a["title"] not in g["titles"]:
                    g["titles"].append(a["title"])
            map_points = list(grouped.values())
            st.iframe(anomaly_map_document(map_points), height=350)
            st.caption("Click a row in the table to bring that aircraft into view on the map.")

        cycle = st.session_state["an_cycle"] = 1 - st.session_state.get("an_cycle", 0)
        stamp = datetime.fromtimestamp(feed_t, timezone.utc).strftime("%H:%M:%S")
        st.markdown(f'<div class="an-refresh cycle-{"ab"[cycle]}"><i></i></div><div class="an-meta">VATSIM data from {stamp}Z · this list refreshes every 20 s</div>', unsafe_allow_html=True)

        watched_min = int((feed_t - view["started"]) // 60) if view["started"] else 0
        if watched_min < 10:
            st.caption(f"The 2-hour timeline appears after about 10 minutes of data (this server has been watching for {watched_min} min).")
        else:
            tl = build_timeline([r for r in view["records"] if r["cid"] not in blocked], feed_t)
            fig = go.Figure()
            for sev, name in (("high", "High"), ("medium", "Medium"), ("low", "Low")):
                fig.add_bar(x=pd.to_datetime(tl["starts"], unit="s", utc=True), y=tl["counts"][sev], name=name, marker_color=AN_SEV_COLOR[sev])
            fig.update_layout(barmode="stack", height=150, margin=dict(l=0, r=0, t=8, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", template="plotly_dark",
                              legend=dict(orientation="h", y=1.3, x=0), bargap=0.15)
            fig.update_yaxes(nticks=4, gridcolor=UI_LINE, zeroline=False, rangemode="tozero")
            fig.update_xaxes(gridcolor=UI_LINE)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            st.caption(f"Anomalies per 5 minutes over the last 2 hours (this server has been watching for {watched_min} min).")

        recent = [r for r in recent if SEVERITY_LABEL[r["a"]["severity"]] in shown_sev]
        with st.expander(f"Recent anomalies, last 2 hours ({len(recent)})"):
            if recent:
                clock = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")
                st.dataframe(pd.DataFrame([{"Severity": SEVERITY_LABEL[r["a"]["severity"]], "Type": r["a"]["title"], "Callsign": r["a"]["callsign"], "Details": r["a"]["details"],
                                            "First seen (Z)": clock(r["first"]), "Last seen (Z)": clock(r["last"]), "CID": page_url("CID_Stats", cid=r["a"]["cid"])} for r in recent]),
                             hide_index=True, width="stretch", column_config={"CID": st.column_config.LinkColumn("CID", display_text=r"cid=(\d+)")})
            else:
                st.caption("Nothing else in the last 2 hours: anomalies that have gone away are listed here.")
        with st.expander("History (kept long-term)"):
            days = st.radio("Period", [7, 30, 90, 365], index=1, horizontal=True, key="an_hist_days", format_func=lambda d: f"{d} days", label_visibility="collapsed")
            hist = anomaly_archive_store.history(feed_t, days)
            if not hist["by_type"]:
                st.caption("Nothing archived for this period yet. Anomalies are written to the archive about 2 minutes after they end, and saved to disk every 30 minutes.")
            else:
                titles = {"squawk_7700": "Emergency squawk (7700)", "squawk_7600": "Radio failure squawk (7600)", "squawk_7500": "Hijack squawk (7500)", "impossible_speed": "Implausible ground speed",
                          "impossible_altitude": "Implausible altitude", "duplicate_cid": "Duplicate connection", "shared_callsign": "Callsign in use twice", "position_jump": "Position jump",
                          "altitude_jump": "Altitude jump", "frozen": "Reports speed but not moving", "slow_at_altitude": "Very slow at high altitude", "ga_too_fast": "Light aircraft too fast"}
                st.dataframe(pd.DataFrame([{"Type": titles.get(k, k), "Count": n} for k, n in sorted(hist["by_type"].items(), key=lambda kv: -kv[1])]), hide_index=True, width="stretch")
                fig = go.Figure()
                for k, hours in sorted(hist["by_hour"].items(), key=lambda kv: -sum(kv[1])):
                    fig.add_bar(x=[f"{h:02d}" for h in range(24)], y=hours, name=titles.get(k, k))
                fig.update_layout(barmode="stack", height=220, margin=dict(l=0, r=0, t=8, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", template="plotly_dark", legend=dict(orientation="h", y=-0.25))
                fig.update_yaxes(gridcolor=UI_LINE, zeroline=False)
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                st.caption("Anomalies by hour of day (UTC).")
                if hist["recent"]:
                    clock = lambda m: datetime.fromtimestamp(m * 60, timezone.utc).strftime("%Y-%m-%d %H:%M")
                    st.dataframe(pd.DataFrame([{"Started (UTC)": clock(e["t"]), "Type": titles.get(e["k"], e["k"]), "Callsign": e["cs"], "Aircraft": e["ac"], "Minutes": e["d"],
                                                "Near": (f"{e['lat']}, {e['lon']}" if e.get("lat") is not None and e.get("lon") is not None else ""),
                                                "CID": (page_url("CID_Stats", cid=e["cid"]) if e.get("cid") else "")} for e in hist["recent"]]),
                                 hide_index=True, width="stretch", column_config={"CID": st.column_config.LinkColumn("CID", display_text=r"cid=(\d+)")})
                st.caption("Squawk, implausible-value and duplicate cases are kept one by one for 90 days, then only counted. Jumps, frozen and slow cases are only ever counted. "
                           "Recorded by this server since it started watching.")
        st.caption("Rules: emergency squawks (7700 / 7600 / 7500), duplicate connections and shared callsigns, position or altitude jumps between two feed updates, "
                   "aircraft frozen in the air, implausible speed or altitude, light aircraft flying too fast, very slow high above the nearest airport. "
                   "The history covers what this server has seen since it started.")

    # Keep the Roadmap LAST: put any new tab before it in both the label list and the unpacking below.
    tab_leaderboard, tab_fir, tab_global, tab_anomaly, tab_cid, tab_network, tab_events, tab_roadmap = st.tabs([
        "🏆 Leaderboard", "✈️ Selected FIR Focus", "🌐 Global Stats & ATC", "🛸 Anomaly Radar",
        "📊 CID Stats", "📈 Network Stats", "🗓️ Events", "🚀 Project Roadmap",
    ])

    # st.tabs() has no on-click callback and renders every tab's body on every
    # run regardless of which one is visible, so tab_cid/tab_network can't just call
    # st.switch_page() directly (it would redirect immediately on every load).
    # Instead: a real (but hidden) page_link provides the actual navigation
    # target, and a tiny watcher script inside the tab clicks it the moment
    # that tab's panel actually becomes visible on screen.
    st.page_link("pages/1_CID_Stats.py", label="CID Stats", icon="📊")
    st.page_link("pages/2_Network_Stats.py", label="Network Stats", icon="📈")
    st.page_link("pages/4_Events.py", label="Events", icon="🗓️")

    def nav_watcher(page_key):
        st.components.v1.html("""
        <script>
            let wasVisible = false;
            setInterval(() => {
                // offsetParent is null when this iframe (or any ancestor, i.e. the
                // tab panel) has display:none — unlike a bounding-rect check, this
                // isn't fooled by the iframe's own explicit height=0.
                const isVisible = window.frameElement.offsetParent !== null;
                if (isVisible && !wasVisible) {
                    const link = window.parent.document.querySelector(
                        'a[data-testid="stPageLink-NavLink"][href*="PAGE_KEY"]'
                    );
                    if (link) link.click();
                }
                wasVisible = isVisible;
            }, 150);
        </script>
        """.replace("PAGE_KEY", page_key), height=0)

    with tab_cid:
        nav_watcher("CID_Stats")

    with tab_network:
        nav_watcher("Network_Stats")

    with tab_events:
        nav_watcher("Events")

    with tab_fir:
        st.subheader("✈️ Selected FIR Focus")
        
        # When the box is closed with Escape or loses focus, the browser can hand back the visible LABEL ("📌 EG - United Kingdom ... · 324 aircraft")
        # instead of the value: always reduce whatever comes back to the plain prefix.
        def region_of(value):
            match = re.match(r"^(?:📌 |★ )?([A-Z]{1,2})(?: - .*)?$", str(value or ""))
            return match.group(1) if match else st.session_state.current_fir_prefix

        def on_fir_change():
            new_prefix = region_of(st.session_state["main_fir_selectbox"])
            st.session_state.current_fir_prefix = new_prefix
            st.query_params["saved_fir"] = new_prefix

        def toggle_pin():
            prefix = region_of(st.session_state["main_fir_selectbox"])
            pins = [p for p in st.session_state.pinned_firs if p != prefix]
            if prefix not in st.session_state.pinned_firs:
                pins.append(prefix)
            st.session_state.pinned_firs = pins[-8:]
            st.session_state.pins_cleared = not st.session_state.pinned_firs
            if st.session_state.pinned_firs:
                st.query_params["pins"] = ",".join(st.session_state.pinned_firs)
            elif "pins" in st.query_params:
                del st.query_params["pins"]

        select_col, pin_col = st.columns([10, 2], vertical_alignment="bottom")
        with select_col:
            selected_option = st.selectbox(
                "Choose Region/FIR Focus:", 
                options=fir_options, 
                index=calculated_index, 
                format_func=region_label,
                key="main_fir_selectbox",
                on_change=on_fir_change
            )
        selected_option = region_of(selected_option)
        with pin_col:
            st.button("📌 Unpin" if selected_option in st.session_state.pinned_firs else "📌 Pin", key="fir_pin_button", on_click=toggle_pin,
                      help="Pinned regions stay at the top of the list.", width="stretch")
        # keeps the pins in the browser (and restores them on a fresh visit whose URL carries none)
        render_pin_sync(st.session_state.pinned_firs, st.session_state.get("pins_cleared", False))
        
        if "only_physical_inside" not in st.session_state:
            st.session_state.only_physical_inside = False

        st.session_state.only_physical_inside = st.checkbox(
            "📍 Only Show Aircraft Inside Airspace Boundaries (Ignore Departure/Arrival FPL)",
            value=st.session_state.only_physical_inside
        )
        
        selected_fir_prefix = selected_option.split(" - ")[0]
        current_fleet_filter = st.session_state.fleet_filter_selection
        current_rules_filter = st.session_state.rules_filter_selection
        current_isolation_filter = st.session_state.airline_isolation_filter

        target_fir_shapes = global_grouped_firs.get(selected_fir_prefix, {}).get("shapes", [])
        if st.session_state.only_physical_inside and not target_fir_shapes:
            st.caption("This region has no airspace boundary under this code, so the inside-airspace filter cannot show anything here.")

        for p in pilots:
            callsign = p.get("callsign", "N/A")
            alt = p.get("altitude", 0)
            gs = p.get("groundspeed", 0)
            lat = p.get("latitude", 0.0)
            lon = p.get("longitude", 0.0)
            fplan = p.get("flight_plan") or {}
            dep = fplan.get("departure", "").strip().upper()
            arr = fplan.get("arrival", "").strip().upper()
            ac_type = fplan.get("aircraft", "").split("/")[0] or "N/A"
            flight_rules = fplan.get("flight_rules", "I")

            category = classify_aircraft(ac_type, callsign)
            if current_fleet_filter == "Commercial Only" and category != "Commercial": continue
            if current_fleet_filter == "General Aviation Only" and category != "General Aviation": continue
            if current_fleet_filter == "Business Jet Only" and category != "Business Jet": continue
            if current_fleet_filter == "Military Only" and category != "Military": continue

            if current_rules_filter == "IFR Only" and flight_rules != "I": continue
            if current_rules_filter == "VFR Only" and flight_rules != "V": continue

            if current_isolation_filter.strip():
                allowed_codes = [c.strip().upper() for c in current_isolation_filter.split(",") if c.strip()]
                cs_prefix_match = re.match(r"^[A-Z]+", callsign.upper())
                cs_prefix = cs_prefix_match.group(0) if cs_prefix_match else ""
                if cs_prefix not in allowed_codes:
                    continue

            if st.session_state.only_physical_inside:
                # Shapely point-in-polygon checks are the expensive part of this loop,
                # so only run them when the result can actually change the outcome.
                is_physically_here = False
                if lat and lon and target_fir_shapes:
                    aircraft_point = Point(lon, lat)
                    for fir_shape in target_fir_shapes:
                        if aircraft_point.within(fir_shape):
                            is_physically_here = True
                            break
                include_aircraft = is_physically_here
            else:
                include_aircraft = str(dep).startswith(selected_fir_prefix) or str(arr).startswith(selected_fir_prefix)

            if include_aircraft:
                display_dep = dep if dep else "NO FPL"
                display_arr = arr if arr else "NO FPL"
                
                fir_pilots.append({
                    "Callsign": callsign, "Origin": display_dep, "Destination": display_arr,
                    "Aircraft": ac_type if fplan.get("aircraft") else "Unknown",
                    "Category": category, "Altitude (FT)": alt, "Speed (KT)": gs, "Squawk": p.get("transponder", "0000"),
                    "FlightRules": flight_rules
                })
                # Ship the server-computed category with the raw pilot so the JS
                # table doesn't have to (incompletely) re-derive it client-side.
                p["_category"] = category
                p["_reg_iso"] = country_of_registration(extract_registration(fplan.get("remarks"))) or ""
                filtered_pilots_raw.append(p)

        chart_expander = st.expander("📊 Open Interactive Analytics Charts (Altitude & Speed Profiles)", expanded=False)
        
        if fir_pilots:
            doc_fir = pd.DataFrame(fir_pilots)
            with chart_expander:
                c_col1, c_col2 = st.columns(2)
                with c_col1:
                    st.markdown("##### 📈 FIR Altitude Profiles (FT)")
                    df_alt_chart = doc_fir[['Callsign', 'Altitude (FT)']].copy().set_index('Callsign')
                    st.bar_chart(df_alt_chart, y='Altitude (FT)', color='#3b82f6')
                with c_col2:
                    st.markdown("##### ⚡ FIR Groundspeed Profiles (KT)")
                    df_spd_chart = doc_fir[['Callsign', 'Speed (KT)']].copy().set_index('Callsign')
                    st.bar_chart(df_spd_chart, y='Speed (KT)', color='#22c55e')

            active_cols = ["Callsign"] + [c for c in st.session_state.visible_columns if c in doc_fir.columns]
            st.info(f"Showing {len(doc_fir)} active aircraft tracks inside unified airspace {selected_option} - {region_name(selected_option)}. Click a row to open the flight record.")
            
            th_elements = "".join([f"<th>{col}</th>" for col in active_cols])
            
            raw_html_template = r"""
            <div id="vatscore-custom-container">
                <div id="dossierModal" class="v-modal">
                    <div class="v-modal-content">
                        <div class="v-modal-header">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span class="v-modal-title">Flight Record</span>
                            </div>
                            <span class="v-close-btn" onclick="closeModal()">&times;</span>
                        </div>
                        <div class="v-modal-body">
                            <div style="display: flex; align-items: center; gap: 12px; margin-top:0; margin-bottom:14px;">
                                <h4 id="popCallsign" style="color:#3b82f6; margin:0; font-size:22px; font-family:sans-serif; letter-spacing:0.5px; font-style: italic;"></h4>
                                <span id="popRulesBadge" class="v-rules-badge">IFR</span>
                                <span id="popMapBadge" class="v-rules-badge v-map-badge" onclick="toggleMap()" title="Show this flight on a live map">Map</span>
                            </div>
                            <hr style="border-color:#1e293b; margin-bottom:14px;">

                            FLIGHT_MAP_HTML_PLACEHOLDER

                            <p class="v-label" style="margin-bottom: 6px;">Live Flight Status & Distance Progress</p>
                            <div id="flightStatusText" style="text-align:center; font-size:14px; font-weight:bold; margin:0 0 8px 0; min-height:18px;"></div>
                            <div class="progress-wrapper">
                                <span id="progressDeparture" class="airport-badge">---</span>
                                <div class="progress-container">
                                    <div id="progressBarFill" class="progress-bar-fill"></div>
                                    <div id="progressPlaneIcon" class="progress-plane-icon">&#9992;</div>
                                </div>
                                <span id="progressArrival" class="airport-badge">---</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; margin-top:4px; margin-bottom:14px; font-size:13px; color:#3b82f6; font-family:monospace; font-weight:bold;">
                                <span id="progressCalculatedText">Distance Tracking Active</span>
                                <span id="progressPercentageText" style="margin-left:auto; color:#22c55e;">0 NM (0%) / Total 0 NM Flown</span>
                            </div>

                            <div class="v-grid">
                                <div>
                                    <p class="v-label">Pilot Name</p><p id="popName" class="v-val"></p>
                                    <p class="v-label">VATSIM CID</p><p id="popCid" class="v-val"></p>
                                    <p class="v-label">VATSIM Ratings</p><p id="popCombinedRating" class="v-val" style="color:#3b82f6; font-weight:600;"></p>
                                </div>
                                <div>
                                    <p class="v-label">Online Time</p><p id="popOnline" class="v-val" style="color:#22c55e; font-weight:bold;"></p>
                                    <p class="v-label">VHF Comms & Frequency</p><p id="popVoice" class="v-val" style="color:#f59e0b;"></p>
                                    <p class="v-label">Squawk Code</p><p id="popSquawkBox" class="v-val" style="color:#e2e8f0; font-family:monospace; font-weight:bold;"></p>
                                </div>
                                <div>
                                    <p class="v-label">Origin</p><p id="popOrigin" class="v-val"></p>
                                    <p class="v-label">Destination</p><p id="popDestination" class="v-val"></p>
                                    <p class="v-label">Airframe Info (Type/Reg/Selcal)</p>
                                    <p id="popAirframe" class="v-val" style="color:#3b82f6; font-weight:bold;"></p>
                                </div>
                            </div>
                            
                            <p class="v-label" style="margin-top:14px;">Airline Identity (Airline Name - Callsign)</p>
                            <div class="telephony-premium-box">
                                <span id="airlineCallsignText" class="telephony-text">GENERAL AVIATION</span>
                            </div>

                            <p class="v-label" style="margin-top:14px;">Filed Route</p>
                            <textarea id="popRoute" class="v-textarea" readonly></textarea>
                        </div>
                    </div>
                </div>

                <div class="table-responsive">
                    <table class="radar-html-table">
                        <thead>
                            <tr id="table-headers">
                                {HEADERS_PLACEHOLDER}
                            </tr>
                        </thead>
                        <tbody id="table-body"></tbody>
                    </table>
                </div>
            </div>

            <style>
                #vatscore-custom-container { font-family: 'Segoe UI', sans-serif; background-color: #0f111a; color: #f8fafc; }
                .table-responsive { width: 100%; overflow-x: auto; border: 1px solid #1e293b; border-radius: 8px; background-color: #11131f; margin-top: 5px; }
                .radar-html-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }
                .radar-html-table th { background-color: #1e293b; color: #94a3b8; padding: 12px 16px; font-weight: 600; }
                .radar-html-table tr { border-bottom: 1px solid #1e293b; transition: background-color 0.2s ease; cursor: pointer; }
                .radar-html-table tr:hover { background-color: #1e293b80; }
                .radar-html-table td { padding: 12px 16px; color: #e2e8f0; }
                
                .progress-wrapper { display: flex; align-items: center; background-color: #0a0c14; padding: 10px 14px; border-radius: 6px; border: 1px solid #1e293b; gap: 12px; }
                .airport-badge { background-color: #1e293b; color: #f1f5f9; font-weight: bold; font-family: monospace; padding: 4px 10px; border-radius: 4px; font-size: 14px; border: 1px solid #3b82f630; }
                .progress-container { flex-grow: 1; height: 6px; background-color: #1e293b; border-radius: 3px; position: relative; }
                .progress-bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, #3b82f6, #22c55e); border-radius: 3px; transition: width 0.4s ease; }
                .progress-plane-icon { position: absolute; top: 50%; left: 0%; transform: translate(-50%, -50%); font-size: 16px; transition: left 0.4s ease; line-height: 1; color: #22c55e; font-weight: bold; }

                .telephony-premium-box { background-color: #141724; border: 1px solid #1e293b; padding: 12px 16px; border-radius: 6px; display: flex; align-items: center; }
                .telephony-text { font-size: 15px; font-weight: bold; color: #22c55e; letter-spacing: 0.5px; text-transform: uppercase; }

                .v-modal {
                    display: none; position: fixed; z-index: 99999999; left: 0; top: 0; width: 100vw; height: 100vh; 
                    background-color: rgba(0, 0, 0, 0.65); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
                }
                .v-modal-content { 
                    background-color: #11131f; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); 
                    width: 75%; max-width: 950px; border: 1px solid #3b82f640; border-radius: 12px; box-shadow: 0 20px 50px rgba(0,0,0,0.7); box-sizing: border-box; 
                }
                .v-modal-header { padding: 16px 22px; background-color: #1e293b; border-top-left-radius: 11px; border-top-right-radius: 11px; display: flex; justify-content: space-between; align-items: center; }
                .v-modal-title { color: #94a3b8; font-weight: bold; font-size: 15px; }
                .v-rules-badge { background-color: #143a24; color: #22c55e; border: 1px solid #22c55e40; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; font-family: monospace; }
                FLIGHT_MAP_CSS_PLACEHOLDER                .v-close-btn { color: #94a3b8; font-size: 28px; font-weight: bold; cursor: pointer; line-height: 1; }
                .v-close-btn:hover { color: #ef4444; }
                .v-modal-body { padding: 22px; max-height: 85vh; overflow-y: auto; }
                .v-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
                .v-link { color: #3b82f6; text-decoration: underline; }
                .v-link:hover { color: #60a5fa; }
                .v-label { color: #64748b; font-size: 11px; font-weight: bold; text-transform: uppercase; margin: 6px 0 4px 0; }
                .v-val { color: #f1f5f9; font-size: 14px; background-color: #0a0c14; padding: 8px 12px; border-radius: 5px; margin: 0; border: 1px solid #1e293b; line-height: 1.4; }
                .v-textarea { width: 100%; height: 80px; background-color: #0a0c14; border: 1px solid #1e293b; color: #cbd5e1; padding: 10px; border-radius: 6px; resize: none; font-family: monospace; font-size: 13px; box-sizing: border-box; line-height: 1.4; }
            </style>

            <script>
                let globalDossiers = {};
                let currentlyOpenCallsign = null;
                const activeColumns = ACTIVE_COLS_PLACEHOLDER;
                const autoOpenCallsign = AUTO_OPEN_CALLSIGN_PLACEHOLDER;
                const airportsDatabase = AIRPORTS_DB_PLACEHOLDER;
                const localAirlinesDb = AIRLINES_DB_PLACEHOLDER;
                const pilotFrequencies = FREQUENCIES_DB_PLACEHOLDER;
                const memberRatings = MEMBER_RATINGS_PLACEHOLDER;
                const cidStatsUrl = CID_STATS_URL_PLACEHOLDER;
                const airportUrl = AIRPORT_URL_PLACEHOLDER;

                function updateHaversineProgressMetrics(depIcao, arrIcao, currentLat, currentLon) {
                    const txtBox = document.getElementById("progressPercentageText");
                    const fillBar = document.getElementById("progressBarFill");
                    const planeIcon = document.getElementById("progressPlaneIcon");

                    if (!depIcao || !arrIcao || !currentLat || !currentLon) {
                        txtBox.innerText = "No Position Metrics";
                        fillBar.style.width = "0%"; planeIcon.style.left = "0%"; return;
                    }
                    
                    try {
                        const depPoint = airportsDatabase[depIcao.toUpperCase()];
                        const arrPoint = airportsDatabase[arrIcao.toUpperCase()];
                        
                        if (!depPoint || !arrPoint) {
                            txtBox.innerText = "Coordinates Missing (NM Tracker Offline)";
                            fillBar.style.width = "50%"; planeIcon.style.left = "50%"; return;
                        }
                        
                        const lat1 = depPoint.latitude_deg || depPoint.latitude;
                        const lon1 = depPoint.longitude_deg || depPoint.longitude;
                        const lat2 = arrPoint.latitude_deg || arrPoint.latitude;
                        const lon2 = arrPoint.longitude_deg || arrPoint.longitude;
                        
                        function toRad(v) { return v * Math.PI / 180; }
                        function getDistanceNM(la1, lo1, la2, lo2) {
                            let R = 6371; 
                            let dLat = toRad(la2 - la1); let dLon = toRad(lo2 - lo1);
                            let a = Math.sin(dLat/2) * Math.sin(dLat/2) + Math.cos(toRad(la1)) * Math.cos(toRad(la2)) * Math.sin(dLon/2) * Math.sin(dLon/2);
                            let c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                            return (R * c) * 0.539957; 
                        }
                        
                        let totalNM = Math.round(getDistanceNM(lat1, lon1, lat2, lon2));
                        let remainingNM = Math.round(getDistanceNM(currentLat, currentLon, lat2, lon2));
                        // Progress = the route length minus what is still to go, so it always agrees with "To go (direct)" on the map ribbon.
                        // (The old figure was the straight line from the departure airport, which is not progress once the aircraft is off that line.)
                        let flownNM = Math.max(0, totalNM - remainingNM);

                        if (flownNM > totalNM) flownNM = totalNM;
                        if (remainingNM < 5) flownNM = totalNM;

                        let pct = totalNM > 0 ? Math.round((flownNM / totalNM) * 100) : 0;
                        if (pct > 100) pct = 100; if (pct < 0) pct = 0;

                        fillBar.style.width = pct + "%";
                        planeIcon.style.left = pct + "%";
                        
                        txtBox.innerText = flownNM + " NM (" + pct + "%) / Total " + totalNM + " NM direct";
                        txtBox.title = "Straight-line progress: total distance minus the distance still to go. The 'Flown (track)' figure on the map adds up the path actually flown (taxi, turns and procedures included), so it is normally larger.";
                    } catch (err) {
                        txtBox.innerText = "Error Calculating Metrics";
                    }
                }

                // Mirrors Python's decode_pilot_rating(): pilot_rating is a cumulative
                // bitmask (1,3,7,15,31,63), NOT a plain 0-5 sequential index.
                function decodePilotRatingLocal(v) {
                    v = parseInt(v, 10);
                    if (isNaN(v)) return "P0";
                    if (v >= 63) return "P6";
                    if (v >= 31) return "P5";
                    if (v >= 15) return "P4";
                    if (v >= 7) return "P3";
                    if (v >= 3) return "P2";
                    if (v >= 1) return "P1";
                    return "P0";
                }

                // Mirrors the VATSIM controller rating scale (must match ATC_RATINGS in pages/1_CID_Stats.py).
                // Per vatsim.dev's official rating table: OBS starts at 1, not 0
                // (0 is Suspended), so every tier is shifted up by one.
                const ATC_RATINGS_LOCAL = {
                    "-1": "Inactive", 0: "Suspended", 1: "OBS", 2: "S1", 3: "S2", 4: "S3",
                    5: "C1", 6: "C2", 7: "C3", 8: "I1", 9: "I2", 10: "I3",
                    11: "SUP", 12: "ADM"
                };
                function decodeAtcRatingLocal(v) {
                    return ATC_RATINGS_LOCAL[v] !== undefined ? ATC_RATINGS_LOCAL[v] : "OBS";
                }

                function classifyAircraftLocal(acType, callsign) {
                    acType = String(acType).toUpperCase().trim();
                    callsign = String(callsign).toUpperCase().trim();
                    const milTypes = ["F16", "F18", "F15", "F22", "F35", "F4", "F5", "EFAF", "C17", "A400", "C130"];
                    if (milTypes.includes(acType)) return "Military";
                    if (callsign.startsWith("TUR") || callsign.startsWith("RCH") || callsign.startsWith("MIL")) return "Military";
                    const gaTypes = ["C172", "C152", "PA28", "DA40", "DA42"];
                    if (gaTypes.includes(acType)) return "General Aviation";
                    return "Commercial";
                }

                function fetchAirlineCompany(callsign) {
    const callsignField = document.getElementById("airlineCallsignText");
    callsignField.innerText = "GENERAL AVIATION / PRIVATE";
    if (!callsign) return;
    
    try {
        // Callsign içerisindeki ilk harf bloğunu yakala (Örn: THY123X -> THY)
        let matches = callsign.match(/^[A-Z]+/i);
        let cleanPrefix = matches ? matches[0].toUpperCase().trim() : "";
        if (cleanPrefix.length < 2) return;
        
        if (localAirlinesDb && localAirlinesDb[cleanPrefix]) {
            let airlineData = localAirlinesDb[cleanPrefix];
            let name = airlineData.name || "Unknown Airline";
            let telephony = airlineData.callsign || "UNKNOWN";
            
            // Virtual-airline entries ("vDLH") are not the airline's real name, so show the code and the radio callsign instead.
            callsignField.innerText = (airlineData.virtual ? cleanPrefix : name) + " (" + telephony.toUpperCase() + ")";
        } else {
            // Eğer veritabanında yoksa en azından ham prefix'i göster
            callsignField.innerText = "AIRLINE: " + cleanPrefix;
        }
    } catch (err) {
        callsignField.innerText = "IDENTITY CORRUPTED";
    }
}

                function buildTable(pilotsList) {
                    const tbody = document.getElementById("table-body");
                    tbody.innerHTML = "";
                    globalDossiers = {};

                    // pilotsList is already filtered server-side (fleet, rules, isolation,
                    // FIR boundary match). No need to re-filter here.
                    pilotsList.forEach(p => {
                        const callsign = p.callsign || "N/A";
                        const fplan = p.flight_plan || {};
                        const dep = (fplan.departure || "").trim().toUpperCase();
                        const arr = (fplan.arrival || "").trim().toUpperCase();
                        const acType = (fplan.aircraft || "").split("/")[0] || "N/A";
                        // Prefer the server-computed category; classifyAircraftLocal is
                        // only a fallback for older cached data that lacks it.
                        const category = p._category || classifyAircraftLocal(acType, callsign);
                        const fRules = fplan.flight_rules || "I";

                        {
                            const rowData = {
                                "Callsign": callsign, "Origin": dep || "NO FPL", "Destination": arr || "NO FPL",
                                "Aircraft": acType, "Category": category, "Altitude (FT)": p.altitude || 0,
                                "Speed (KT)": p.groundspeed || 0, "Squawk": p.transponder || "0000"
                            };

                            let onlineMins = "Unknown";
                            if (p.logon_time) {
                                const logDt = new Date(p.logon_time);
                                const totalMins = Math.floor((new Date() - logDt) / 60000);
                                const hrs = Math.floor(totalMins / 60);
                                const mins = totalMins % 60;
                                // Format as "XXX Min | X Hour XX Min"
                                onlineMins = totalMins + " Min | " + hrs + " Hour " + String(mins).padStart(2, "0") + " Min";
                            }

                            globalDossiers[callsign] = {
                                name: p.name || "Anonymous", cid: p.cid || "N/A",
                                online: onlineMins,
                                voice: (() => {
                                    // Only voice-connected clients have a transceiver (frequency) entry.
                                    const freq = pilotFrequencies[callsign];
                                    return freq ? ("Voice · " + freq) : "Text Only";
                                })(),
                                squawk: p.transponder || "0000", origin: rowData.Origin,
                                destination: rowData.Destination, airframe: acType, route: fplan.route || "No FPL Filed.",
                                heading: p.heading || 0, lat: p.latitude || 0, lon: p.longitude || 0,
                                rules: fRules === "V" ? "VFR" : "IFR",
                                reg: (function(r) { if (!r) return ""; const m = r.match(/REG\/([A-Z0-9\-]{2,10})/i); return m ? m[1].toUpperCase() : ""; })(fplan.remarks || ""),
                                selcal: (function(r) { if (!r) return ""; const m = r.match(/SEL\/([A-Z]{4})/i); return m ? m[1].toUpperCase() : ""; })(fplan.remarks || ""),
                                regIso: /^[a-z]{2}$/.test(p._reg_iso || "") ? p._reg_iso : "",
                                pilotRatingFeed: p.pilot_rating, alt: p.altitude || 0, gs: p.groundspeed || 0, filedAlt: fplan.altitude || ""
                            };

                            const tr = document.createElement("tr");
                            tr.onclick = () => openDossier(callsign);
                            
                            activeColumns.forEach(col => {
                                const td = document.createElement("td");
                                if (col === "Callsign") {
                                    const b = document.createElement("b");
                                    b.style.color = "#3b82f6";
                                    b.style.cursor = "pointer";
                                    b.textContent = rowData[col];
                                    td.appendChild(b);
                                } else { td.innerText = rowData[col]; }
                                tr.appendChild(td);
                            });
                            tbody.appendChild(tr);
                        }
                    });
                }

                function openDossier(callsign) {
                    try {
                        const p = globalDossiers[callsign];
                        if (!p) return;
                        closeMap();
                        currentlyOpenCallsign = callsign;

                        document.getElementById("popCallsign").innerText = " Target Profile: " + callsign;
                        document.getElementById("popName").innerText = p.name;
                        const cidBox = document.getElementById("popCid");
                        cidBox.textContent = "";
                        if (/^\d{1,10}$/.test(String(p.cid))) {
                            const cidLink = document.createElement("a");
                            cidLink.className = "v-link";
                            cidLink.href = cidStatsUrl + "?cid=" + p.cid;
                            cidLink.target = "_blank";
                            cidLink.rel = "noopener";
                            cidLink.title = "Open CID Stats";
                            cidLink.textContent = p.cid;
                            cidBox.appendChild(cidLink);
                        } else {
                            cidBox.textContent = p.cid;
                        }
                        document.getElementById("popCombinedRating").innerText = ratingLabel(p);
                        const flightStatus = computeFlightStatus(p);
                        const statusBox = document.getElementById("flightStatusText");
                        statusBox.innerText = flightStatus.title;
                        statusBox.style.color = flightStatus.color;
                        document.getElementById("popOnline").innerText = p.online;
                        document.getElementById("popVoice").innerText = p.voice;
                        document.getElementById("popSquawkBox").innerText = p.squawk;
                        document.getElementById("popOrigin").innerText = p.origin;
                        document.getElementById("popDestination").innerText = p.destination;
                        // Build airframe display as "Type | Reg | SELCAL" — show only available parts
                        const airframeParts = [p.airframe];
                        if (p.reg) airframeParts.push(p.reg);
                        if (p.selcal) airframeParts.push(p.selcal);
                        const airframeBox = document.getElementById("popAirframe");
                        airframeBox.textContent = airframeParts.join(" | ");
                        if (p.regIso) {
                            const flag = document.createElement("img");
                            flag.src = "https://flagcdn.com/w40/" + p.regIso + ".png";
                            flag.alt = p.regIso.toUpperCase();
                            try { flag.title = new Intl.DisplayNames(["en"], {type: "region"}).of(p.regIso.toUpperCase()); } catch (e) {}
                            flag.style.cssText = "height:14px; margin-left:8px; vertical-align:middle; border-radius:2px;";
                            flag.onerror = () => flag.remove();
                            airframeBox.appendChild(flag);
                        }
                        document.getElementById("popRoute").value = p.route;

                        const badge = document.getElementById("popRulesBadge");
                        badge.innerText = p.rules;
                        
                        badge.style.backgroundColor = "#143a24"; 
                        badge.style.color = "#22c55e"; 
                        badge.style.borderColor = "#22c55e40";

                        document.getElementById("progressDeparture").innerText = p.origin;
                        document.getElementById("progressArrival").innerText = p.destination;

                        try {
                            updateHaversineProgressMetrics(p.origin, p.destination, p.lat, p.lon);
                        } catch (e) { console.log("Haversine sub-error ignored"); }

                        try {
                            fetchAirlineCompany(callsign);
                        } catch (e) { console.log("Airline identification sub-error ignored"); }

                        document.getElementById("dossierModal").style.display = "block";
                        const knownRating = memberRatings[String(p.cid)];
                        if (!knownRating || (knownRating.error && Date.now() / 1000 >= (knownRating.retry_at || 0))) requestMemberRating(p.cid);
                    } catch (fatalErr) {
                        console.log("Fatal crash intercepted in openDossier:", fatalErr);
                    }
                }

                const lookupFailed = {};

                function ratingErrorText(mr) {
                    const mins = Math.max(1, Math.ceil(((mr.retry_at || 0) - Date.now() / 1000) / 60));
                    if (mr.reason === "rate_limited") return "VATSIM limit, retry in " + mins + " min";
                    if (mr.reason === "vatsim_error") return "VATSIM error, retry later";
                    if (mr.reason === "timeout" || mr.reason === "network") return "VATSIM not responding";
                    if (mr.reason === "not_found") return "not found";
                    return "unavailable";
                }

                function ratingLabel(d) {
                    const mr = memberRatings[String(d.cid)];
                    const known = !!(mr && !mr.error);
                    const pText = decodePilotRatingLocal(known ? mr.pilotrating : d.pilotRatingFeed);
                    const aText = known ? decodeAtcRatingLocal(mr.rating) : (mr ? ratingErrorText(mr) : (lookupFailed[String(d.cid)] ? "unavailable" : "loading…"));
                    return "P: " + pText + " / ATC: " + aText;
                }

                function refreshOpenRating() {
                    if (!currentlyOpenCallsign) return;
                    const d = globalDossiers[currentlyOpenCallsign];
                    if (d) document.getElementById("popCombinedRating").innerText = ratingLabel(d);
                }

                // Called by the hidden rating-sync frame (see member_rating_bridge): updates the open window in place.
                window.setMemberRatings = function(data) {
                    Object.assign(memberRatings, data || {});
                    refreshOpenRating();
                };

                function distNM(la1, lo1, la2, lo2) {
                    const toRad = v => v * Math.PI / 180;
                    const dLa = toRad(la2 - la1), dLo = toRad(lo2 - lo1);
                    const a = Math.sin(dLa / 2) ** 2 + Math.cos(toRad(la1)) * Math.cos(toRad(la2)) * Math.sin(dLo / 2) ** 2;
                    return 3440.065 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
                }

                // Same rules as VATSIM Radar (app/utils/server/vatsim/update.ts), same labels.
                const FLIGHT_STATUS = {
                    arriving: { title: "Arriving", color: "#f97316" }, departed: { title: "Departed", color: "#93c5fd" },
                    cruising: { title: "Cruising", color: "#3b82f6" }, climbing: { title: "Climbing", color: "#60a5fa" },
                    descending: { title: "Descending", color: "#fb923c" }, enroute: { title: "Enroute", color: "#3b82f6" }
                };
                function computeFlightStatus(d) {
                    const unknown = { title: "Status unknown", color: "#94a3b8" };
                    const dep = airportsDatabase[String(d.origin || "").toUpperCase()];
                    const arr = airportsDatabase[String(d.destination || "").toUpperCase()];
                    if (!dep || !arr || !d.lat || !d.lon) return unknown;
                    const depLat = dep.latitude_deg ?? dep.latitude, depLon = dep.longitude_deg ?? dep.longitude;
                    const arrLat = arr.latitude_deg ?? arr.latitude, arrLon = arr.longitude_deg ?? arr.longitude;
                    const dDep = distNM(d.lat, d.lon, depLat, depLon), dArr = distNM(d.lat, d.lon, arrLat, arrLon);
                    const total = distNM(depLat, depLon, arrLat, arrLon);
                    const gs = d.gs || 0, alt = d.alt || 0;
                    if (gs < 50 && (dDep < 5 || dArr < 5)) {
                        const atGate = gs <= 2;
                        if (dDep <= dArr) return { title: atGate ? "Departing | At gate" : "Departing", color: "#22c55e" };
                        return { title: atGate ? "Arrived | At gate" : "Arrived", color: "#ef4444" };
                    }
                    let status = null;
                    if (dArr < 40) status = "arriving";
                    else if (dDep < 40) status = "departed";
                    const filedText = String(d.filedAlt || "");
                    let filed = /^S/i.test(filedText) ? 0 : parseInt(filedText.replace(/\D/g, ""), 10);
                    if (filed && filed < 1000) filed *= 100;
                    if (filed) {
                        if (alt + 300 >= filed && gs > 50) status = "cruising";
                        else if (!status && total > 0) status = total / 2 < dArr ? "climbing" : "descending";
                    }
                    return FLIGHT_STATUS[status || "enroute"];
                }

                function requestMemberRating(cid) {
                    try {
                        const doc = window.parent.document;
                        const input = doc.querySelector('input[aria-label="vs_lookup_cid"]');
                        if (!input || !/^\d{1,10}$/.test(String(cid))) return;
                        const win = window.parent;
                        const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, "value").set;
                        setter.call(input, String(cid) + ":" + (Date.now() % 100000));
                        input.dispatchEvent(new win.Event("input", { bubbles: true }));
                        const enter = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true };
                        input.dispatchEvent(new win.KeyboardEvent("keydown", enter));
                        input.dispatchEvent(new win.KeyboardEvent("keypress", enter));
                        input.dispatchEvent(new win.KeyboardEvent("keyup", enter));
                        setTimeout(() => {
                            if (!memberRatings[String(cid)]) { lookupFailed[String(cid)] = true; refreshOpenRating(); }
                        }, 9000);
                    } catch (e) { console.log("member rating lookup skipped", e); }
                }

                FLIGHT_MAP_JS_PLACEHOLDER                function closeModal() {
                    closeMap();
                    currentlyOpenCallsign = null;
                    document.getElementById("dossierModal").style.display = "none"; 
                }
                
                window.onclick = function(e) { 
                    if (e.target == document.getElementById("dossierModal")) closeModal(); 
                }

                const initialData = INITIAL_DATA_PLACEHOLDER;
                buildTable(initialData);

                if (autoOpenCallsign && autoOpenCallsign !== "") {
                    setTimeout(() => { openDossier(autoOpenCallsign); }, 250);
                }
            </script>
            """
            
            airlines_db = load_vatsim_radar_airlines()
            pilot_frequencies = fetch_pilot_frequencies()

            # The pilot feed carries no ATC rating and api.vatsim.net has no CORS. Clicking a pilot writes the CID
            # into this hidden field (see requestMemberRating). Being a fragment, the lookup reruns only this block
            # (one cached call) and pushes the result into the open window, so the table never reloads.
            rating_sync_html = """<style>html,body{margin:0;padding:0;overflow:hidden;background:transparent}</style>
            <script>/*vs-rating-sync*/
            const data = RATINGS_PLACEHOLDER;
            try { window.frameElement.closest('[data-testid="stElementContainer"]').style.display = "none"; } catch (e) {}
            function push() {
                try {
                    const table = Array.from(window.parent.document.querySelectorAll("iframe"))
                        .find(f => (f.getAttribute("srcdoc") || "").includes("vatscore-" + "custom-container"));
                    if (table && table.contentWindow && typeof table.contentWindow.setMemberRatings === "function") {
                        table.contentWindow.setMemberRatings(data);
                        return true;
                    }
                } catch (e) {}
                return false;
            }
            if (!push()) {
                let tries = 0;
                const timer = setInterval(() => { if (push() || ++tries > 20) clearInterval(timer); }, 250);
            }
            </script>"""

            @st.fragment
            def member_rating_bridge():
                ratings = st.session_state.setdefault("member_ratings", {})
                looked = st.text_input("vs_lookup_cid", key="vs_lookup_cid", label_visibility="collapsed", max_chars=24)
                cid = looked.split(":")[0]  # the browser appends ":<nonce>" so a retry of the same CID still reruns
                known = ratings.get(cid)
                retry_after_error = bool(known and known.get("error") and time.time() >= known.get("retry_at", 0))
                if cid.isdigit() and (known is None or retry_after_error):
                    ratings[cid] = fetch_member_rating(cid)
                st.iframe(rating_sync_html.replace("RATINGS_PLACEHOLDER", js_safe(ratings)), height=1)

            member_rating_bridge()

            # Same trick for the real flight track from statsim.net: the map writes "<cid>:<callsign>:<nonce>" into a hidden
            # field, this fragment fetches the track (the API key stays on the server) and pushes it into the open window.
            track_sync_html = """<style>html,body{margin:0;padding:0;overflow:hidden;background:transparent}</style>
            <script>/*vs-track-sync*/
            const data = TRACK_PLACEHOLDER;
            try { window.frameElement.closest('[data-testid="stElementContainer"]').style.display = "none"; } catch (e) {}
            function push() {
                try {
                    const table = Array.from(window.parent.document.querySelectorAll("iframe"))
                        .find(f => (f.getAttribute("srcdoc") || "").includes("vatscore-" + "custom-container"));
                    if (table && table.contentWindow && typeof table.contentWindow.setFlightTrack === "function") {
                        table.contentWindow.setFlightTrack(data);
                        return true;
                    }
                } catch (e) {}
                return false;
            }
            if (!push()) {
                let tries = 0;
                const timer = setInterval(() => { if (push() || ++tries > 20) clearInterval(timer); }, 250);
            }
            </script>"""

            @st.fragment
            def flight_track_bridge():
                req = st.text_input("vs_track_req", key="vs_track_req", label_visibility="collapsed", max_chars=40)
                cid, _, rest = req.partition(":")
                callsign, _, nonce = rest.partition(":")
                payload = {}
                if cid.isdigit() and len(cid) <= 10 and is_valid_callsign(callsign):
                    # The nonce makes every answer differ, otherwise an identical answer would leave the iframe untouched
                    # and the browser would never be told (e.g. closing and reopening the same map within the cache time).
                    payload = {"key": f"{cid}:{callsign}", "nonce": nonce[:8] if nonce.isdigit() else ""}
                    session_limiter, global_limiter = _track_limiters()
                    session_key = st.session_state.setdefault("_track_limiter_key", os.urandom(8).hex())
                    if session_limiter.allow(session_key) and global_limiter.allow("global"):
                        payload.update(cached_flight_bundle(cid, callsign))
                    else:
                        payload.update({"ok": False, "reason": "rate_limited"})
                st.iframe(track_sync_html.replace("TRACK_PLACEHOLDER", js_safe(payload)), height=1)

            flight_track_bridge()

            html_table_and_modal_code = raw_html_template\
                .replace("FLIGHT_MAP_JS_PLACEHOLDER", flight_map_asset("metar_decode.js") + "\n" + flight_map_asset("follow_math.js") + "\n" + flight_map_asset("track_guard.js") + "\n" + flight_map_asset("wxr_data.js") + "\n" + flight_map_asset("flight_map.js"))\
                .replace("FLIGHT_MAP_CSS_PLACEHOLDER", flight_map_asset("flight_map.css"))\
                .replace("FLIGHT_MAP_HTML_PLACEHOLDER", flight_map_asset("flight_map_panel.html"))\
                .replace("{HEADERS_PLACEHOLDER}", th_elements)\
                .replace("ACTIVE_COLS_PLACEHOLDER", js_safe(active_cols))\
                .replace("AUTO_OPEN_CALLSIGN_PLACEHOLDER", js_safe(st.session_state.active_popup))\
                .replace("AIRPORTS_DB_PLACEHOLDER", js_safe(airports_coords_map))\
                .replace("INITIAL_DATA_PLACEHOLDER", js_safe(filtered_pilots_raw))\
                .replace("AIRLINES_DB_PLACEHOLDER", js_safe(airlines_db))\
                .replace("FREQUENCIES_DB_PLACEHOLDER", js_safe(pilot_frequencies))\
                .replace("MEMBER_RATINGS_PLACEHOLDER", js_safe(st.session_state.member_ratings))\
                .replace("CID_STATS_URL_PLACEHOLDER", js_safe(page_url("CID_Stats")))\
                .replace("AIRPORT_URL_PLACEHOLDER", js_safe(page_url("Airport")))

            # Dynamic height: 48px per row, max 900. The Flight Record window is centred in this iframe (position: fixed, 100vh), so even a
            # one-row table needs room for it: below ~760px the window is cut off at the top.
            dynamic_height = min(900, max(760, 120 + len(fir_pilots) * 48))
            st.components.v1.html(html_table_and_modal_code, height=dynamic_height, scrolling=True)

            st.markdown("<br>", unsafe_allow_html=True)
            csv = csv_safe_for_download(doc_fir).to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Download This FIR Data as CSV", data=csv, file_name=f"vatsim_fir_{selected_fir_prefix}_data.csv", mime="text/csv")
        else:
            st.warning("No active flights found within the boundaries of this unified FIR focus right now.")


# ─── Remaining tabs (FIR focus, CID and Network live above) ─────────────────
# The tabs only exist when the VATSIM feed answered; without it, say so instead of crashing on the missing tab objects.
if not data:
    st.error("Could not fetch data from VATSIM API. Please reload page.")
    st.stop()

with tab_leaderboard:
    render_leaderboard()

with tab_global:
    render_global_stats()

with tab_anomaly:
    st.subheader("🛸 Live Anomalies")
    with st.expander("⚙️ Pilot Watchlist", expanded=False):
        st.markdown("#### Watchlist Settings")
        wl_c1, wl_c2 = st.columns(2)
        with wl_c1:
            st.text_input("Pilot CIDs (comma-separated):", placeholder="e.g. 1863530, 1869429", key="vip_cids")
        with wl_c2:
            st.text_input("Callsigns (comma-separated):", placeholder="e.g. THY123, PGT456", key="vip_callsigns")
        st.markdown("---")
    render_anomaly_table()

with tab_roadmap:
    st.subheader("🚀 VatScore Strategic Development Roadmap")
    st.markdown("""
    <div class="roadmap-card">
        <div class="roadmap-badge" style="background-color: #22c55e;">Phase 3: Completed</div>
        <div class="roadmap-title">📊 The Ultimate Score, Analytics & Hyper-Personalization</div>
        <div class="roadmap-desc">
            <strong>Status:</strong> Completed — August 5, 2026<br>
            Turned VatScore from a live radar into a full performance analytics hub. Key milestones delivered:
            <ul>
                <li><strong> Dedicated CID Intelligence Hub:</strong> Replaced the flat CID Stats tab with a fully independent stats page, reachable via a seamless single-click native tab.</li>
                <li><strong> Full-History statsim.net Integration:</strong> Chunked, parallelized fetch pipeline that works around statsim.net's 31-day query ceiling to pull a pilot's entire history in seconds.</li>
                <li><strong> Fleet, Route & Airline Intelligence:</strong> Manufacturer distribution, longest-flight rankings with hour/NM sliders, most-flown route/aircraft/airline, and a "most interesting route" algorithm.</li>
                <li><strong> ATC Sector Mastery Module:</strong> Per-position ATC session analytics with All Time / This Year / This Month ranking.</li>
                <li><strong> Real VHF Frequency Telemetry:</strong> Live COM frequency data sourced directly from VATSIM's official transceivers feed.</li>
                <li><strong> Network-Wide Auto-Refresh Engine:</strong> Scoped-fragment architecture keeps Leaderboard, Global Stats, and Anomaly Radar live without disturbing in-progress input elsewhere.</li>
                <li><strong> Rating Accuracy Overhaul:</strong> ATC and pilot rating decoders now match VATSIM's official tables exactly, fixing a long-standing off-by-one misclassification.</li>
            </ul>
        </div>
    </div>
    <div class="roadmap-card">
        <div class="roadmap-badge" style="background-color: #22c55e;">Phase 2: Completed — Codename: "babybus"</div>
        <div class="roadmap-title">📢 Advanced Telemetry Tracking & Precision Filtering</div>
        <div class="roadmap-desc">
            <strong>Status:</strong> Completed — June 6, 2026<br>
            Focused on operational depth and data accuracy. Key milestones delivered:
            <ul>
                <li><strong> Real-Time Haversine Engine:</strong> Successfully integrated precise distance calculations and a dynamic progress bar within the telemetry dossier.</li>
                <li><strong> Flight Rule Identification:</strong> Completed the deployment of the integrated IFR/VFR Rule Box for instant flight type classification.</li>
                <li><strong> Dynamic Telephony Engine & Isolation:</strong> Enriched with asynchronous API matcher and premium ICAO fleet code isolation filter.</li>
                <li><strong> FIR Boundary Engine Overhaul:</strong> Replaced legacy prefix-only matching with a dual-mode Shapely geometry system.</li>
                <li><strong> VIP Surveillance Watchlist:</strong> Deployed a live pilot tracking module inside the Anomaly Radar.</li>
            </ul>
        </div>
    </div>
    <div class="roadmap-card">
        <div class="roadmap-badge" style="background-color: #22c55e;">Phase 1: Completed</div>
        <div class="roadmap-title">✈️ Custom HTML/JS Grid Engine & Flight Detail Insight System</div>
        <div class="roadmap-desc">
            <strong>Status:</strong> Completed — May 31, 2026<br>
            Implementation of a high-performance HTML/JS grid engine enabling real-time telemetry inspection.
        </div>
    </div>
    """, unsafe_allow_html=True)

if data:
    st.markdown("""
    <div class="signature-container">
        VatScoreRadar - Made by alp-1863530 <br>
        📬 For any questions or requests, contact:
        <a class="signature-link" href="mailto:alpqwesy1@gmail.com">alpqwesy1@gmail.com</a>
        <br><span style="opacity:0.7;">This site logs basic, non-personal session info (device type, browser, OS, page visited) for admin diagnostics only - no accounts, no tracking cookies, never shared with third parties.</span>
    </div>
    """, unsafe_allow_html=True)

else:
    st.error("Could not fetch data from VATSIM API. Please reload page.")