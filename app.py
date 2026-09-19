import streamlit as st
import requests
import pandas as pd
from collections import Counter
from datetime import datetime, timezone
import os
import json
import re
import hmac
import hashlib
import time
from shapely.geometry import LineString, shape, Point
from shapely.prepared import prep

from security_utils import SlidingWindowLimiter, is_valid_callsign, is_valid_fir_prefix
from registration_country import country_of_registration, extract_registration
from ui_theme import page_url, set_browser_title
from vatsim_data import fetch_member_rating
from flight_track import fetch_track
from fir_crossings import fir_crossings, great_circle_points
from geo_compact import compact_rings
from flight_plan_firs import boundaries_for_codes, eet_fir_codes

def get_secret(key, default=""):
    # st.secrets.get() raises StreamlitSecretNotFoundError (instead of
    # returning the default) when no secrets.toml exists at all, which
    # would otherwise crash the whole app on first load.
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

# API URLs
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_TRANSCEIVERS_URL = "https://data.vatsim.net/v3/transceivers-data.json"
VATSIM_FIR_GEO_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/Boundaries.geojson"
VATSPY_DAT_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/VATSpy.dat"
TRACON_GEO_URL = "https://github.com/vatsimnetwork/simaware-tracon-project/releases/latest/download/TRACONBoundaries.geojson"
VATSIM_RADAR_AIRLINES_URL = "https://data.vatsim-radar.com/airlines"
CSV_FILE_PATH = "airports.csv"

# Page Configuration
st.set_page_config(
    page_title="VatScoreRadar",
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
    div[data-testid="stPageLink"]:has(a[href="Network_Stats"]) { display: none; }
    div[data-testid="stElementContainer"]:has(input[aria-label="vs_lookup_cid"]) { display: none; }
    div[data-testid="stElementContainer"]:has(input[aria-label="vs_track_req"]) { display: none; }
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
LOG_FILE = "radar_traffic_logs.csv"
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "")
ADMIN_PASSWORD_HASH = get_secret("ADMIN_PASSWORD_HASH", "")
MAX_ADMIN_FAILS = 5
ADMIN_FAIL_WINDOW = 600
ADMIN_LOCK_SECONDS = 900

@st.cache_resource
def _admin_guard():
    # Process-wide state shared by every session, so opening a new browser
    # tab doesn't reset the brute-force counter.
    return {"fails": [], "lock_until": 0.0}

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
            new_row = pd.DataFrame([{
                "Timestamp": timestamp, "Session_ID": session_id,
                "OS": "Generic OS", "Browser": "Generic Browser", "Device_Type": "PC / Laptop", "Last_Action": action
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            
        df.to_csv(LOG_FILE, index=False)
    except:
        pass

if "initialized" not in st.session_state:
    log_activity("Radar Dashboard Opened")
    st.session_state.initialized = True

# Initialize VIP Watchlist Session State
if "vip_watchlist" not in st.session_state:
    st.session_state.vip_watchlist = []
if "vip_cids" not in st.session_state:
    st.session_state.vip_cids = ""
if "vip_callsigns" not in st.session_state:
    st.session_state.vip_callsigns = ""

query_params = st.query_params
is_admin_route = query_params.get("admin") == "true"

if is_admin_route:
    set_browser_title("Admin")
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    if not st.session_state.admin_authenticated:
        st.title("🛡️ VatScore HQ Security Login")
        if not (ADMIN_PASSWORD or ADMIN_PASSWORD_HASH):
            st.error("Admin access is not configured. Set ADMIN_PASSWORD_HASH (or ADMIN_PASSWORD) in .streamlit/secrets.toml to enable this panel.")
            st.stop()
        lock_left = admin_lock_remaining()
        if lock_left > 0:
            st.error(f"Too many failed attempts. Try again in {int(lock_left // 60) + 1} minute(s).")
            st.stop()
        passwd_input = st.text_input("Enter Master Admin Password:", type="password")
        if st.button("Authorize Connection"):
            if passwd_input and verify_admin_password(passwd_input):
                clear_admin_failures()
                st.session_state.admin_authenticated = True
                st.success("Access Granted.")
                st.rerun()
            else:
                register_admin_failure()
                st.error("Invalid Secret Token.")
        st.stop()
    else:
        st.title("🛰️ VatScore // Core Traffic Analytics HQ")
        if st.button("⬅️ Return to Live Radar"):
            st.session_state.admin_authenticated = False
            st.query_params.clear()
            st.rerun()
            
        st.markdown("---")
        if os.path.exists(LOG_FILE):
            df_logs = pd.read_csv(LOG_FILE)
            df_logs['Timestamp'] = pd.to_datetime(df_logs['Timestamp'])
            time_delta = (datetime.now() - df_logs['Timestamp']).dt.total_seconds()
            
            total_unique = len(df_logs['Session_ID'].unique())
            active_now = len(df_logs[time_delta < 300]['Session_ID'].unique())
            
            adm_c1, adm_c2, adm_c3 = st.columns(3)
            with adm_c1: st.metric(label="🟢 Active Users (Last 5 Mins)", value=active_now)
            with adm_c2: st.metric(label="👥 Total Unique Connections", value=total_unique)
            with adm_c3: st.metric(label="📊 Dominant Hardware", value=df_logs['Device_Type'].mode()[0] if not df_logs.empty else "N/A")
            
            st.markdown("<br>", unsafe_allow_html=True)
            btn_c1, btn_c2 = st.columns([0.8, 0.2])
            with btn_c1: st.subheader("👥 Live Session Logs")
            with btn_c2:
                if st.button("🗑️ Wipe Logs", width='stretch'):
                    os.remove(LOG_FILE)
                    init_log_file()
                    st.rerun()
                    
            df_display = df_logs.sort_values(by="Timestamp", ascending=False).copy()
            df_display['Timestamp'] = df_display['Timestamp'].dt.strftime('%H:%M:%S || %Y-%m-%d')
            st.dataframe(df_display[["Timestamp", "Device_Type", "OS", "Browser", "Last_Action"]], width='stretch')
        st.stop()

@st.cache_data(ttl=15)
def fetch_vatsim_data():
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200: return r.json()
    except: pass
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
    except Exception:
        pass
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
    except: pass
    return airlines_map

FIR_FALLBACK_NAMES = {
    "LT": "Turkey Airspace Hub",
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
    return out


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
    return out


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

set_browser_title(labels=["Leaderboard", "Selected FIR Focus", "Global Stats & ATC", "Anomaly Radar", "CID Stats", "Network Stats", "Project Roadmap"])

data = fetch_vatsim_data()
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

    defined_fir_prefixes = {"LT", "ED", "EG", "LF", "K", "OM", "LO", "LI", "LE"}
    fir_options = [f"{code} - {info['name']}" for code, info in sorted(global_grouped_firs.items()) if code in defined_fir_prefixes]
    
    if is_valid_fir_prefix(st.query_params.get("saved_fir")):
        st.session_state.current_fir_prefix = st.query_params["saved_fir"]
    
    if "current_fir_prefix" not in st.session_state:
        st.session_state.current_fir_prefix = "LT"

    matched_indices = [i for i, s in enumerate(fir_options) if s.startswith(st.session_state.current_fir_prefix)]
    calculated_index = matched_indices[0] if matched_indices else 0

    if is_valid_callsign(st.query_params.get("selected_callsign")):
        st.session_state.active_popup = st.query_params["selected_callsign"]
    if "active_popup" not in st.session_state:
        st.session_state.active_popup = ""

    # These three tabs are read-only network-wide views (no interactive filters of
    # their own besides simple display toggles), so each gets its own fragment that
    # independently re-fetches (cached, so cheap) and redraws itself every 20s.
    # Fragments only rerun their own body — everything outside them (FIR Focus
    # controls, settings panel, VIP watchlist inputs) is untouched by the tick.
    @st.fragment(run_every=20)
    def render_leaderboard():
        d = fetch_vatsim_data()
        lb_pilots = d.get("pilots", []) if d else []

        highest_p = fastest_p = slowest_p = veteran_p = None
        max_alt, max_gs, min_gs = -1, -1, 9999
        min_logon = "9999-12-31"
        for p in lb_pilots:
            alt = p.get("altitude", 0)
            gs = p.get("groundspeed", 0)
            logon = p.get("logon_time", "")
            if alt > max_alt: max_alt = alt; highest_p = p
            if gs > max_gs: max_gs = gs; fastest_p = p
            if alt > 3000 and 45 < gs < min_gs: min_gs = gs; slowest_p = p
            if logon and logon < min_logon: min_logon = logon; veteran_p = p

        st.subheader("Current Flight Records")
        leader_data = []
        if highest_p: leader_data.append({"Record Category": "Highest Cruising Altitude", "Callsign": highest_p['callsign'], "Value": f"{highest_p['altitude']:,} FT", "Pilot": highest_p.get('name')})
        if fastest_p: leader_data.append({"Record Category": "Maximum Velocity (GS)", "Callsign": fastest_p['callsign'], "Value": f"{fastest_p['groundspeed']} KT", "Pilot": fastest_p.get('name')})
        if slowest_p: leader_data.append({"Record Category": "Slowest Airborne Profile", "Callsign": slowest_p['callsign'], "Value": f"{slowest_p['groundspeed']} KT", "Pilot": slowest_p.get('name')})
        if veteran_p:
            _veteran_logon = pd.to_datetime(veteran_p.get('logon_time', ''), utc=True, errors="coerce")
            _veteran_since = _veteran_logon.strftime("%d.%m.%Y %H:%M UTC") if pd.notna(_veteran_logon) else "Unknown"
            leader_data.append({"Record Category": "Longest Session (Veteran)", "Callsign": veteran_p['callsign'], "Value": f"Since {_veteran_since}", "Pilot": veteran_p.get('name')})
        st.table(leader_data)

    @st.fragment(run_every=20)
    def render_global_stats():
        d = fetch_vatsim_data()
        gs_pilots = d.get("pilots", []) if d else []
        gs_controllers = d.get("controllers", []) if d else []

        dep_airports, arr_airports, aircraft_types = [], [], []
        # Flight-plan fields are free text typed by pilots and end up inside
        # markdown below, so only accept plain ICAO-style tokens.
        token_ok = re.compile(r"[A-Z0-9]{2,8}").fullmatch
        for p in gs_pilots:
            fplan = p.get("flight_plan") or {}
            dep = fplan.get("departure", "").strip().upper()
            arr = fplan.get("arrival", "").strip().upper()
            ac_type = fplan.get("aircraft", "").split("/")[0].strip().upper() or "N/A"
            if token_ok(dep): dep_airports.append(dep)
            if token_ok(arr): arr_airports.append(arr)
            if ac_type != "N/A" and token_ok(ac_type): aircraft_types.append(ac_type)

        st.subheader("Global Network Insights")
        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            st.markdown("### 📍 Busiest Hubs")
            hub_view = st.radio("Select Focus:", ["🛫 Top Departures", "🛬 Top Arrivals"], horizontal=True, label_visibility="collapsed")
            st.markdown("<br>", unsafe_allow_html=True)
            if "Departures" in hub_view:
                st.write("**Top Flight Departures Currently:**")
                for k, v in Counter(dep_airports).most_common(5): st.write(f"• `{k}`: {v} flights")
            else:
                st.write("**Top Flight Arrivals Currently:**")
                for k, v in Counter(arr_airports).most_common(5): st.write(f"• `{k}`: {v} flights")
        with col_g2:
            st.markdown("### ✈️ Fleet Distribution")
            for k, v in Counter(aircraft_types).most_common(7): st.write(f"• **{k}** : {v} aircraft")
        with col_g3:
            st.markdown("### 👑 Busiest Airspaces (ATC)")
            atc_pos = [a.get("callsign", "").split("_")[0] for a in gs_controllers if "_" in a.get("callsign", "")]
            for k, v in Counter(atc_pos).most_common(4): st.write(f"• `{k}` : {v} open frequencies")

    @st.fragment(run_every=20)
    def render_anomaly_table():
        d = fetch_vatsim_data()
        an_pilots = d.get("pilots", []) if d else []
        vip_cid_array = [c.strip() for c in st.session_state.vip_cids.split(",") if c.strip()]
        vip_callsign_array = [cs.strip().upper() for cs in st.session_state.vip_callsigns.split(",") if cs.strip()]

        anomalies = []
        for p in an_pilots:
            callsign = p.get("callsign", "N/A")
            cid = str(p.get("cid", "N/A"))
            alt = p.get("altitude", 0)
            gs = p.get("groundspeed", 0)
            fplan = p.get("flight_plan") or {}
            dep = fplan.get("departure", "").strip().upper()
            arr = fplan.get("arrival", "").strip().upper()
            ac_type = fplan.get("aircraft", "").split("/")[0] or "N/A"

            if str(p.get("transponder")) == "7700":
                anomalies.append({"Type": "🚨 Emergency squawk (7700)", "Callsign": callsign, "Details": "Transponder set to 7700 (general emergency)", "Aircraft": ac_type, "Altitude (FT)": alt, "Speed (KT)": gs})
            if gs > 1150:
                anomalies.append({"Type": "⚠️ Implausible ground speed", "Callsign": callsign, "Details": f"Ground speed {gs} KT is above the 1,150 KT limit", "Aircraft": ac_type, "Altitude (FT)": alt, "Speed (KT)": gs})
            if cid in vip_cid_array or callsign in vip_callsign_array:
                anomalies.insert(0, {
                    "Type": "🎯 Watchlist match",
                    "Callsign": f"{callsign} (CID: {cid})",
                    "Details": f"Pilot is online. Route: {dep} to {arr}",
                    "Aircraft": ac_type,
                    "Altitude (FT)": alt,
                    "Speed (KT)": gs
                })

        if anomalies:
            df_anomalies = pd.DataFrame(anomalies)
            st.dataframe(df_anomalies, width='stretch')
        else:
            st.success("No anomalies or emergencies at the moment.")

    # Keep the Roadmap LAST: put any new tab before it in both the label list and the unpacking below.
    tab_leaderboard, tab_fir, tab_global, tab_anomaly, tab_cid, tab_network, tab_roadmap = st.tabs([
        "🏆 Leaderboard", "✈️ Selected FIR Focus", "🌐 Global Stats & ATC", "🛸 Anomaly Radar",
        "📊 CID Stats", "📈 Network Stats", "🚀 Project Roadmap",
    ])

    # st.tabs() has no on-click callback and renders every tab's body on every
    # run regardless of which one is visible, so tab_cid/tab_network can't just call
    # st.switch_page() directly (it would redirect immediately on every load).
    # Instead: a real (but hidden) page_link provides the actual navigation
    # target, and a tiny watcher script inside the tab clicks it the moment
    # that tab's panel actually becomes visible on screen.
    st.page_link("pages/1_CID_Stats.py", label="CID Stats", icon="📊")
    st.page_link("pages/2_Network_Stats.py", label="Network Stats", icon="📈")

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

    with tab_fir:
        st.subheader("✈️ Selected FIR Focus")
        
        def on_fir_change():
            new_prefix = st.session_state["main_fir_selectbox"].split(" - ")[0]
            st.session_state.current_fir_prefix = new_prefix
            st.query_params["saved_fir"] = new_prefix

        selected_option = st.selectbox(
            "Choose Region/FIR Focus:", 
            options=fir_options, 
            index=calculated_index, 
            key="main_fir_selectbox",
            on_change=on_fir_change
        )
        
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
            st.info(f"Showing {len(doc_fir)} active aircraft tracks inside unified airspace {selected_option}. Click a row to inspect full telemetry.")
            
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

                            <div id="mapPanel" class="v-map-panel">
                                <div class="mp-head">
                                    <span class="mp-route"><b id="mrDep"></b> <span id="mrDepName" class="mp-name"></span> <span class="mp-arrow">&rarr;</span> <b id="mrArr"></b> <span id="mrArrName" class="mp-name"></span></span>
                                    <span id="mrMeta" class="mp-meta"></span>
                                </div>
                                <div class="mp-tools">
                                    <button type="button" class="mp-chip on" id="tgRings" onclick="toggleLayer('rings')">Range rings</button>
                                    <button type="button" class="mp-chip on" id="tgAtc" onclick="toggleLayer('atc')">ATC</button>
                                    <button type="button" class="mp-chip on" id="tgSectors" onclick="toggleLayer('sectors')">Sectors</button>
                                </div>
                                <div class="mp-mapwrap">
                                    <div id="flightMap" class="v-map"></div>
                                    <div id="mapNote" class="v-map-note"></div>
                                </div>
                                <div id="atcList" class="mp-atc"></div>
                                <div class="mp-strip">
                                    <div class="mp-cell"><span>Altitude</span><b id="stAlt">-</b></div>
                                    <div class="mp-cell"><span>Ground speed</span><b id="stGs">-</b></div>
                                    <div class="mp-cell"><span>Heading</span><b id="stHdg">-</b></div>
                                    <div class="mp-cell"><span>Vertical speed</span><b id="stVs">-</b></div>
                                    <div class="mp-cell"><span>To go (direct)</span><b id="stTogo">-</b></div>
                                    <div class="mp-cell"><span>ETA (est.)</span><b id="stEta">-</b></div>
                                    <div class="mp-cell"><span>Flown (track)</span><b id="stFlown">-</b></div>
                                </div>
                                <div class="mp-profile">
                                    <div class="mp-profile-head">
                                        <span class="mp-tabs">
                                            <button type="button" class="mp-tab on" id="tabAlt" onclick="setProfileMode('alt')">Altitude</button>
                                            <button type="button" class="mp-tab" id="tabGs" onclick="setProfileMode('gs')">Speed</button>
                                        </span>
                                        <span id="profSpan" class="mp-profile-info"></span>
                                    </div>
                                    <svg id="profileSvg" viewBox="0 0 600 54" preserveAspectRatio="none"></svg>
                                </div>
                                <div class="mp-foot">
                                    <i>The dotted line is the direct path between the airports, not the filed route.</i>
                                    <span class="mp-legend"><span>0</span><span class="bar"></span><span>FL400</span></span>
                                </div>
                            </div>

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
                .v-map-badge { cursor: pointer; user-select: none; }
                .v-map-badge:hover, .v-map-badge.active { background-color: #1a5433; border-color: #22c55e; }
                .v-map-panel { display: none; margin-bottom: 14px; border: 1px solid #1e293b; border-radius: 8px; overflow: hidden; background-color: #0a0c14; font-size: 13px; font-variant-numeric: tabular-nums; }
                .mp-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 14px; background-color: #11131f; border-bottom: 1px solid #1e293b; color: #94a3b8; }
                .mp-route { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .mp-route b { color: #f1f5f9; font-weight: 600; }
                .mp-arrow { margin: 0 6px; color: #64748b; }
                .mp-meta { color: #94a3b8; white-space: nowrap; }
                .mp-tools { display: flex; gap: 8px; padding: 8px 14px; background-color: #0a0c14; border-bottom: 1px solid #1e293b; }
                .mp-chip { padding: 2px 10px; border-radius: 4px; border: 1px solid #1e293b; background-color: #11131f; color: #94a3b8; font: inherit; font-size: 12px; cursor: pointer; }
                .mp-chip:hover { border-color: #334155; color: #e2e8f0; }
                .mp-chip.on { background-color: #143a24; color: #22c55e; border-color: #22c55e40; }
                .mp-mapwrap { position: relative; }
                .v-map { width: 100%; height: 400px; background-color: #07080c; }
                .v-map .leaflet-tile-pane { filter: grayscale(1) brightness(0.55) contrast(1.2); }
                .v-map-note { display: none; position: absolute; left: 50%; bottom: 12px; transform: translateX(-50%); z-index: 1000; background-color: #11131f; border: 1px solid #334155; color: #cbd5e1; padding: 5px 12px; border-radius: 4px; font-size: 12px; }
                .mp-atc { padding: 7px 14px; background-color: #0a0c14; border-top: 1px solid #1e293b; color: #94a3b8; font-size: 12px; line-height: 1.5; }
                .mp-atc:empty { display: none; }
                .mp-atc b { color: #e2e8f0; font-weight: 600; }
                .mp-atc div + div { margin-top: 2px; }
                .mp-atc .note { color: #475569; font-size: 11px; font-style: italic; }
                .atc-row { display: flex; gap: 10px; align-items: baseline; }
                .atc-row + .atc-row { margin-top: 5px; }
                .atc-tag { flex: 0 0 46px; color: #64748b; font-size: 11px; }
                .atc-items { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 16px; min-width: 0; }
                .atc-row.behind .atc-items { opacity: 0.55; }
                .atc-item { position: relative; white-space: nowrap; }
                .atc-item b { color: #e2e8f0; font-weight: 600; }
                [data-tip] { position: relative; }
                [data-tip]:hover::after { content: attr(data-tip); position: absolute; left: 0; bottom: calc(100% + 5px); z-index: 3000; white-space: pre; padding: 4px 8px; background-color: #11131f; border: 1px solid #334155; border-radius: 3px; color: #e2e8f0; font-size: 11px; font-weight: 400; line-height: 1.5; pointer-events: none; }
                .mp-strip { display: grid; grid-template-columns: repeat(7, 1fr); background-color: #11131f; border-top: 1px solid #1e293b; }
                .mp-cell { padding: 8px 14px; border-right: 1px solid #1e293b; min-width: 0; }
                .mp-cell:last-child { border-right: none; }
                .mp-cell span { display: block; color: #64748b; font-size: 11px; white-space: nowrap; }
                .mp-cell b { color: #f1f5f9; font-size: 14px; font-weight: 600; white-space: nowrap; }
                .mp-profile { padding: 8px 14px 2px; background-color: #0a0c14; border-top: 1px solid #1e293b; }
                .mp-profile-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
                .mp-tabs { display: flex; gap: 2px; }
                .mp-tab { padding: 1px 10px; border: none; border-bottom: 2px solid transparent; background: none; color: #64748b; font: inherit; font-size: 12px; cursor: pointer; }
                .mp-tab:hover { color: #e2e8f0; }
                .mp-tab.on { color: #f1f5f9; border-bottom-color: #3b82f6; }
                .mp-profile-info { color: #64748b; font-size: 11px; }
                .mp-profile svg { width: 100%; height: 54px; display: block; }
                .mp-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 3px 14px 8px; background-color: #0a0c14; }
                .mp-foot i { color: #475569; font-size: 11px; }
                .mp-legend { display: flex; align-items: center; gap: 6px; color: #64748b; font-size: 11px; white-space: nowrap; }
                .mp-legend .bar { width: 90px; height: 6px; border-radius: 3px; background: linear-gradient(90deg, #f97316, #eab308, #22c55e, #38bdf8); }
                @media (max-width: 700px) { .mp-strip { grid-template-columns: repeat(4, 1fr); } .mp-name { display: none; } }
                .v-blip { background: none; border: none; }
                .v-blip svg { display: block; filter: drop-shadow(0 0 2px #000); }
                .v-tag { background: none; border: none; }
                .v-tag-box { display: inline-block; min-width: 92px; padding: 4px 8px; background-color: #11131f; border: 1px solid #334155; border-radius: 3px; color: #cbd5e1; font-size: 12px; line-height: 1.4; white-space: nowrap; cursor: grab; user-select: none; }
                .v-tag-box b { color: #f8fafc; font-weight: 600; }
                .v-tag-box:active { cursor: grabbing; }
                .v-map-tip { background-color: #11131f; border: 1px solid #334155; border-radius: 3px; box-shadow: none; color: #e2e8f0; font-weight: 600; font-size: 11px; padding: 1px 6px; }
                .v-map-tip:before { display: none; }
                .v-map-tip small { display: block; color: #94a3b8; font-weight: 400; }
                .v-ring-label { background: none; border: none; box-shadow: none; color: #64748b; font-size: 10px; padding: 0; text-align: center; }
                .v-ring-label:before { display: none; }
                .v-atc { background: none; border: none; }
                .v-atc-row { display: inline-flex; gap: 3px; transform: translateX(-50%); }
                .v-atc-chip.fir { border-color: #3b82f6; }
                .v-atc-chip.app { border-color: #a78bfa; }
                .v-atc-chip { padding: 0 5px; background-color: #11131f; border: 1px solid #475569; border-radius: 3px; color: #e2e8f0; font-size: 10px; font-weight: 600; line-height: 15px; white-space: nowrap; }
                .v-map.leaflet-container { background: #07080c; font-family: 'Segoe UI', sans-serif; }
                .v-map .leaflet-control-attribution { background: #0a0c14cc; color: #64748b; font-size: 10px; }
                .v-map .leaflet-control-attribution a { color: #94a3b8; }
                .v-map .leaflet-bar a { background-color: #11131f; color: #94a3b8; border-bottom-color: #1e293b; font-family: 'Segoe UI', sans-serif; }
                .v-map .leaflet-bar a:hover { background-color: #1e293b; color: #f1f5f9; }
                .v-close-btn { color: #94a3b8; font-size: 28px; font-weight: bold; cursor: pointer; line-height: 1; }
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
                        let flownNM = Math.round(getDistanceNM(lat1, lon1, currentLat, currentLon));
                        
                        if (flownNM > totalNM) flownNM = totalNM;
                        if (remainingNM < 5) flownNM = totalNM;

                        let pct = totalNM > 0 ? Math.round((flownNM / totalNM) * 100) : 0;
                        if (pct > 100) pct = 100; if (pct < 0) pct = 0;

                        fillBar.style.width = pct + "%";
                        planeIcon.style.left = pct + "%";
                        
                        txtBox.innerText = flownNM + " NM (" + pct + "%) / Total " + totalNM + " NM ";
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

                // ── Live map inside the Flight Record window (Leaflet, loaded only when "Map" is pressed) ──
                const LEAFLET_BASE = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
                const LEAFLET_SRI = {
                    "leaflet.css": "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H",
                    "leaflet.js": "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
                };
                const VATSIM_FEED_URL = "https://data.vatsim.net/v3/vatsim-data.json";
                const MAP_REFRESH_MS = 20000;
                const TRACK_WAIT_MS = 20000;
                // CARTO's free dark tiles now stamp "API KEY REQUIRED" on every tile, so use Esri's public dark gray canvas
                // (darkened further with CSS).
                const MAP_TILES_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
                const MAP_TILES_ATTRIBUTION = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, OpenStreetMap contributors, and the GIS user community &middot; Sectors: VATSpy &amp; SimAware (CC BY-SA 4.0)";
                const ALT_STOPS = [[0, [249, 115, 22]], [12000, [234, 179, 8]], [26000, [34, 197, 94]], [40000, [56, 189, 248]]];
                const RING_STEPS_NM = [5, 10, 25, 50, 100, 250, 500, 1000];
                const ATC_ROLES = ["ATIS", "DEL", "GND", "TWR", "APP", "DEP", "CTR", "FSS"];
                const FACILITY_ROLE = { 1: "FSS", 2: "DEL", 3: "GND", 4: "TWR", 5: "APP", 6: "CTR" };
                let leafletPromise = null, flightMap = null, mapLayers = null, mapLive = null, mapTimer = null, mapBusy = false;
                let mapFlightKey = "", trackPts = [], trackNote = "", trackWhy = "", trackWait = null;
                let profMode = "alt", lastControllers = [], lastAtis = [], controllersLoaded = false, atcSpec = null;
                const mapOpts = { rings: true, atc: true, sectors: true };
                let tagOffset = { x: 28, y: -24 };  // where the aircraft tag sits relative to the aircraft, in screen pixels (draggable)

                function loadLeaflet() {
                    if (window.L) return Promise.resolve();
                    if (leafletPromise) return leafletPromise;
                    leafletPromise = new Promise((resolve, reject) => {
                        const css = document.createElement("link");
                        css.rel = "stylesheet"; css.href = LEAFLET_BASE + "leaflet.css";
                        css.integrity = LEAFLET_SRI["leaflet.css"]; css.crossOrigin = "anonymous";
                        document.head.appendChild(css);
                        const js = document.createElement("script");
                        js.src = LEAFLET_BASE + "leaflet.js";
                        js.integrity = LEAFLET_SRI["leaflet.js"]; js.crossOrigin = "anonymous";
                        js.onload = () => resolve();
                        js.onerror = () => { leafletPromise = null; reject(new Error("leaflet failed to load")); };
                        document.head.appendChild(js);
                    });
                    return leafletPromise;
                }

                function airportLatLon(icao) {
                    const a = airportsDatabase[String(icao || "").toUpperCase()];
                    if (!a) return null;
                    const lat = a.latitude_deg ?? a.latitude, lon = a.longitude_deg ?? a.longitude;
                    return (typeof lat === "number" && typeof lon === "number") ? [lat, lon] : null;
                }

                // Great-circle line a -> b whose longitudes stay continuous (no jump at +-180) and start exactly at a[1].
                function gcLine(a, b, steps) {
                    const r = Math.PI / 180, deg = 180 / Math.PI;
                    const la1 = a[0] * r, lo1 = a[1] * r, la2 = b[0] * r, lo2 = b[1] * r;
                    const dist = 2 * Math.asin(Math.min(1, Math.sqrt(Math.sin((la2 - la1) / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2)));
                    if (dist < 1e-6 || Math.abs(Math.sin(dist)) < 1e-9) return [a, b];
                    const pts = [];
                    let prev = null;
                    for (let i = 0; i <= steps; i++) {
                        const f = i / steps;
                        const A = Math.sin((1 - f) * dist) / Math.sin(dist), B = Math.sin(f * dist) / Math.sin(dist);
                        const x = A * Math.cos(la1) * Math.cos(lo1) + B * Math.cos(la2) * Math.cos(lo2);
                        const y = A * Math.cos(la1) * Math.sin(lo1) + B * Math.cos(la2) * Math.sin(lo2);
                        const z = A * Math.sin(la1) + B * Math.sin(la2);
                        let lon = Math.atan2(y, x) * deg;
                        if (prev === null) lon += 360 * Math.round((a[1] - lon) / 360);
                        else { while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; }
                        prev = lon;
                        pts.push([Math.atan2(z, Math.sqrt(x * x + y * y)) * deg, lon]);
                    }
                    return pts;
                }

                // A point may sit on the "other copy" of the world than the line; shift it by 360 deg to the nearest one.
                function nearestLon(lat, lon, path) {
                    let best = lon, bestD = Infinity;
                    [-360, 0, 360].forEach(k => path.forEach(pt => {
                        const d = (pt[0] - lat) ** 2 + (pt[1] - (lon + k)) ** 2;
                        if (d < bestD) { bestD = d; best = lon + k; }
                    }));
                    return best;
                }

                // Point `nm` nautical miles from (lat, lon) on true bearing `hdg`; longitude aligned to the start longitude.
                function destPoint(lat, lon, hdg, nm) {
                    const r = Math.PI / 180, d = nm / 3440.065, b = hdg * r, la1 = lat * r, lo1 = lon * r;
                    const la2 = Math.asin(Math.sin(la1) * Math.cos(d) + Math.cos(la1) * Math.sin(d) * Math.cos(b));
                    const lo2 = lo1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la1), Math.cos(d) - Math.sin(la1) * Math.sin(la2));
                    let lonOut = lo2 / r;
                    lonOut += 360 * Math.round((lon - lonOut) / 360);
                    return [la2 / r, lonOut];
                }

                function altColor(alt) {
                    const a = Math.max(0, Math.min(40000, Math.round((Number(alt) || 0) / 1500) * 1500));
                    for (let i = 1; i < ALT_STOPS.length; i++) {
                        if (a <= ALT_STOPS[i][0]) {
                            const [a0, c0] = ALT_STOPS[i - 1], [a1, c1] = ALT_STOPS[i], f = (a - a0) / (a1 - a0);
                            return "rgb(" + c0.map((v, k) => Math.round(v + (c1[k] - v) * f)).join(",") + ")";
                        }
                    }
                    return "rgb(" + ALT_STOPS[ALT_STOPS.length - 1][1].join(",") + ")";
                }

                function fmtFt(a) { return Math.round(a || 0).toLocaleString("en-US") + " ft"; }
                function fmtFl(a) { return a >= 5000 ? "FL" + String(Math.round(a / 100)).padStart(3, "0") : Math.round(a || 0) + " ft"; }

                function setMapNote(text) {
                    const n = document.getElementById("mapNote");
                    n.textContent = text || "";
                    n.style.display = text ? "block" : "none";
                }

                function airportPopup(icao) {
                    const box = document.createElement("div");
                    if (/^[A-Z0-9]{4}$/.test(icao)) {
                        const a = document.createElement("a");
                        a.href = airportUrl + "?icao=" + icao; a.target = "_blank"; a.rel = "noopener"; a.className = "v-link";
                        a.textContent = "Open " + icao + " airport page";
                        box.appendChild(a);
                    } else { box.textContent = icao; }
                    return box;
                }

                function fillTag(box, p, live) {
                    box.textContent = "";
                    const head = document.createElement("b");
                    head.textContent = currentlyOpenCallsign || "";
                    box.appendChild(head);
                    box.appendChild(document.createElement("br"));
                    box.appendChild(document.createTextNode((p.airframe || "") + " · " + fmtFl(live.alt)));
                    box.appendChild(document.createElement("br"));
                    box.appendChild(document.createTextNode(Math.round(live.gs || 0) + " kt"));
                }

                function blipIcon(heading) {
                    const svg = '<svg viewBox="0 0 24 24" width="24" height="24" style="transform:rotate(' + (Number(heading) || 0) + 'deg)">' +
                        '<path d="M12 3 L19 20 L12 16 L5 20 Z" fill="#f8fafc" stroke="#0a0c14" stroke-width="1.2" stroke-linejoin="round"/></svg>';
                    return L.divIcon({ className: "v-blip", html: svg, iconSize: [24, 24], iconAnchor: [12, 12] });
                }

                // The tag keeps a fixed pixel offset from the aircraft until the user drags it somewhere else.
                function tagLatLng(planeLL) {
                    return flightMap.containerPointToLatLng(flightMap.latLngToContainerPoint(planeLL).add(L.point(tagOffset.x, tagOffset.y)));
                }
                function placeTag() {
                    if (!flightMap || !mapLayers || !mapLayers.tag) return;
                    const planeLL = mapLayers.plane.getLatLng(), ll = tagLatLng(planeLL);
                    mapLayers.tag.setLatLng(ll);
                    mapLayers.leader.setLatLngs([planeLL, ll]);
                }

                function trackDistanceNM() {
                    let nm = 0;
                    for (let i = 1; i < trackPts.length; i++) {
                        const d = distNM(trackPts[i - 1][0], trackPts[i - 1][1], trackPts[i][0], trackPts[i][1]);
                        if (d < 250) nm += d;  // a bigger hop between samples is a data gap, not distance flown
                    }
                    return nm;
                }

                function verticalSpeedFpm() {
                    if (trackPts.length < 2) return null;
                    const last = trackPts[trackPts.length - 1];
                    for (let i = trackPts.length - 2; i >= 0; i--) {
                        const dt = last[3] - trackPts[i][3];
                        if (dt >= 120) return dt > 900 ? null : Math.round(((last[2] - trackPts[i][2]) / (dt / 60)) / 50) * 50;
                    }
                    return null;
                }

                function pushTrackSample() {
                    if (!mapLive) return;
                    const t = Math.floor(Date.now() / 1000), last = trackPts[trackPts.length - 1];
                    if (last && (t - last[3] < 15 || (last[0] === mapLive.lat && last[1] === mapLive.lon))) return;
                    trackPts.push([mapLive.lat, mapLive.lon, mapLive.alt || 0, t, mapLive.gs || 0]);
                }

                // Track points with continuous longitudes, moved to the same "copy" of the world as the plane.
                function unwrappedTrack(refLon) {
                    if (!trackPts.length) return [];
                    const out = [];
                    let prev = trackPts[0][1];
                    trackPts.forEach(pt => {
                        let lon = pt[1];
                        while (lon - prev > 180) lon -= 360;
                        while (lon - prev < -180) lon += 360;
                        prev = lon;
                        out.push([pt[0], lon, pt[2]]);
                    });
                    const shift = 360 * Math.round((refLon - out[out.length - 1][1]) / 360);
                    return shift ? out.map(o => [o[0], o[1] + shift, o[2]]) : out;
                }

                function renderTrack(planeLL) {
                    mapLayers.track.clearLayers();
                    const pts = unwrappedTrack(planeLL[1]);
                    if (pts.length < 2) return pts;
                    let run = [[pts[0][0], pts[0][1]]], runColor = altColor((pts[0][2] + pts[1][2]) / 2);
                    for (let i = 1; i < pts.length; i++) {
                        const color = altColor((pts[i - 1][2] + pts[i][2]) / 2);
                        if (color !== runColor) {
                            L.polyline(run, { color: runColor, weight: 3, opacity: 0.95, lineCap: "round", interactive: false }).addTo(mapLayers.track);
                            run = [[pts[i - 1][0], pts[i - 1][1]]]; runColor = color;
                        }
                        run.push([pts[i][0], pts[i][1]]);
                    }
                    L.polyline(run, { color: runColor, weight: 3, opacity: 0.95, lineCap: "round", interactive: false }).addTo(mapLayers.track);
                    return pts;
                }

                // Range rings whose spacing follows the zoom (about 70-140 px apart).
                function renderRings() {
                    if (!flightMap || !mapLayers || !mapLive) return;
                    mapLayers.rings.clearLayers();
                    const center = mapLayers.plane.getLatLng();
                    const mpp = 40075016.686 * Math.cos(center.lat * Math.PI / 180) / (256 * Math.pow(2, flightMap.getZoom()));
                    const nmPerPx = Math.max(mpp, 1) / 1852;
                    const step = RING_STEPS_NM.find(s => s / nmPerPx >= 70) || RING_STEPS_NM[RING_STEPS_NM.length - 1];
                    for (let k = 1; k <= 4; k++) {
                        const nm = step * k;
                        L.circle(center, { radius: nm * 1852, color: "#94a3b8", weight: 1, opacity: 0.28, fill: false, dashArray: "3 5", interactive: false }).addTo(mapLayers.rings);
                        const top = destPoint(center.lat, center.lng, 0, nm);
                        L.marker(top, { interactive: false, keyboard: false, icon: L.divIcon({ className: "v-ring-label", html: nm + " NM", iconSize: [44, 12], iconAnchor: [22, 14] }) }).addTo(mapLayers.rings);
                    }
                }

                // Altitude or ground speed over time, chosen with the tabs above the chart.
                function renderProfile() {
                    const svg = document.getElementById("profileSvg"), span = document.getElementById("profSpan");
                    const gsMode = profMode === "gs";
                    svg.textContent = "";
                    if (trackPts.length < 5) { span.textContent = (trackWhy || "live samples only") + " (" + trackPts.length + " pts)"; return; }
                    const NS = "http://www.w3.org/2000/svg", W = 600, H = 54, PAD = 4;
                    const val = q => gsMode ? (q[4] || 0) : q[2];
                    const t0 = trackPts[0][3], t1 = trackPts[trackPts.length - 1][3];
                    const maxV = Math.max(gsMode ? 50 : 1000, ...trackPts.map(val));
                    const xy = q => [((q[3] - t0) / Math.max(1, t1 - t0)) * W, H - PAD - (val(q) / (maxV * 1.05)) * (H - 2 * PAD)];
                    const line = trackPts.map((q, i) => { const [x, y] = xy(q); return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1); }).join(" ");
                    const area = document.createElementNS(NS, "path");
                    area.setAttribute("d", line + " L" + W + " " + H + " L0 " + H + " Z");
                    area.setAttribute("fill", "#3b82f6"); area.setAttribute("fill-opacity", "0.14");
                    const stroke = document.createElementNS(NS, "path");
                    stroke.setAttribute("d", line); stroke.setAttribute("fill", "none");
                    stroke.setAttribute("stroke", "#3b82f6"); stroke.setAttribute("stroke-width", "1.5"); stroke.setAttribute("vector-effect", "non-scaling-stroke");
                    const [lx, ly] = xy(trackPts[trackPts.length - 1]);
                    const dot = document.createElementNS(NS, "circle");
                    dot.setAttribute("cx", lx); dot.setAttribute("cy", ly); dot.setAttribute("r", "3"); dot.setAttribute("fill", "#f1f5f9");
                    [area, stroke, dot].forEach(n => svg.appendChild(n));
                    const mins = Math.round((t1 - t0) / 60);
                    span.textContent = (trackNote === "statsim track" ? "statsim track" : "live samples") + " · " + trackPts.length + " pts · " + Math.floor(mins / 60) + "h " + String(mins % 60).padStart(2, "0") + "m · max " + (gsMode ? Math.round(maxV) + " kt" : fmtFl(maxV));
                }

                function setProfileMode(mode) {
                    profMode = mode === "gs" ? "gs" : "alt";
                    document.getElementById("tabAlt").classList.toggle("on", profMode === "alt");
                    document.getElementById("tabGs").classList.toggle("on", profMode === "gs");
                    renderProfile();
                }

                function updateStrip(live, arr) {
                    const set = (id, v) => { document.getElementById(id).textContent = v; };
                    set("stAlt", fmtFt(live.alt));
                    set("stGs", Math.round(live.gs || 0) + " kt");
                    set("stHdg", String(Math.round(live.heading || 0) % 360).padStart(3, "0") + "°");
                    const vs = verticalSpeedFpm();
                    set("stVs", vs === null ? "-" : (Math.abs(vs) < 100 ? "level" : (vs > 0 ? "+" : "-") + Math.abs(vs).toLocaleString("en-US") + " fpm"));
                    if (arr) {
                        const togo = distNM(live.lat, live.lon, arr[0], arr[1]);
                        set("stTogo", Math.round(togo).toLocaleString("en-US") + " NM");
                        if ((live.gs || 0) >= 60 && togo > 3) {
                            const eta = new Date(Date.now() + (togo / live.gs) * 3600000);
                            set("stEta", "~" + String(eta.getUTCHours()).padStart(2, "0") + ":" + String(eta.getUTCMinutes()).padStart(2, "0") + "Z");
                        } else { set("stEta", "-"); }
                    } else { set("stTogo", "-"); set("stEta", "-"); }
                    set("stFlown", trackPts.length > 1 ? Math.round(trackDistanceNM()).toLocaleString("en-US") + " NM" : "-");
                }

                function fillRibbon(p) {
                    const set = (id, v) => { document.getElementById(id).textContent = v; };
                    const dA = airportsDatabase[String(p.origin).toUpperCase()], aA = airportsDatabase[String(p.destination).toUpperCase()];
                    const f = pilotFrequencies[currentlyOpenCallsign];
                    set("mrDep", p.origin); set("mrDepName", (dA && dA.name) || "");
                    set("mrArr", p.destination); set("mrArrName", (aA && aA.name) || "");
                    set("mrMeta", [p.airframe, f ? String(f) : ""].filter(Boolean).join(" · "));
                }

                // ── ATC that concerns this flight: airports, plus the FIRs and approach areas the route touches ──
                function atcRole(c) {
                    const last = String(c.callsign).split("_").pop().toUpperCase();
                    return ATC_ROLES.includes(last) ? last : (FACILITY_ROLE[c.facility] || "");
                }
                function atAirport(c, icao) {
                    const pre = String(c.callsign).split("_")[0].toUpperCase();
                    return pre === icao || (/^[KP]/.test(icao) && pre === icao.slice(1));
                }
                function byRole(a, b) { return ATC_ROLES.indexOf(a.role) - ATC_ROLES.indexOf(b.role) || a.callsign.localeCompare(b.callsign); }

                // Controllers of the given facilities grouped by the crossed area whose callsign prefix they carry.
                function groupByArea(areas, facilities) {
                    const keyToArea = {}, groups = {};
                    (areas || []).forEach(f => (f.keys || [f.id]).forEach(k => { keyToArea[String(k).toUpperCase()] = f; }));
                    lastControllers.filter(c => facilities.includes(c.facility)).forEach(c => {
                        const parts = String(c.callsign).toUpperCase().split("_");
                        for (let k = parts.length - 1; k >= 1; k--) {
                            const f = keyToArea[parts.slice(0, k).join("_")];
                            if (f) { (groups[f.id] = groups[f.id] || []).push({ role: atcRole(c), callsign: c.callsign, freq: c.frequency }); break; }
                        }
                    });
                    return (areas || []).filter(f => groups[f.id]).map(f => ({ area: f, list: groups[f.id].sort(byRole) }));
                }

                // "LYBA" and "LYBA-N" are one FIR for the reader: one entry, every sector callsign goes into the hover text.
                function mergeByParent(groups) {
                    const out = [], idx = {};
                    groups.forEach(g => {
                        const pid = g.area.id.split("-")[0];
                        if (idx[pid] === undefined) { idx[pid] = out.length; out.push({ area: g.area, list: g.list.slice(), parts: [g.area] }); }
                        else {
                            const m = out[idx[pid]];
                            m.list = m.list.concat(g.list).sort(byRole);
                            m.parts.push(g.area);
                            if (g.area.id === pid) m.area = g.area;
                        }
                    });
                    return out;
                }

                function relevantAtc(p) {
                    const out = { airports: [], firs: [], firGroups: [], tracons: [] };
                    const seen = new Set();
                    [p.origin, p.destination].forEach(raw => {
                        const icao = String(raw || "").toUpperCase();
                        if (!/^[A-Z0-9]{4}$/.test(icao) || seen.has(icao)) return;
                        seen.add(icao);
                        const list = lastControllers.filter(c => c.facility >= 2 && c.facility <= 5 && atAirport(c, icao))
                            .map(c => ({ role: atcRole(c), callsign: c.callsign, freq: c.frequency }));
                        lastAtis.filter(a => atAirport(a, icao)).forEach(a => {
                            const mid = String(a.callsign).split("_");  // "LTFM_D_ATIS" = departure ATIS, "_A_" = arrival
                            const kind = mid.length > 2 ? ({ A: "arrival", D: "departure" }[mid[1]] || "") : "";
                            list.push({ role: "ATIS", kind: kind, callsign: a.callsign, freq: a.frequency, code: a.atis_code });
                        });
                        list.sort(byRole);
                        if (list.length) out.airports.push({ icao: icao, list: list });
                    });
                    if (atcSpec) {
                        out.firs = groupByArea(atcSpec.firs, [1, 6]);
                        out.firGroups = mergeByParent(out.firs);
                        out.tracons = groupByArea(atcSpec.tracons, [5]);
                    }
                    return out;
                }

                function atcChip(text, tip, cls) {
                    const s = document.createElement("span");
                    s.className = "v-atc-chip" + (cls ? " " + cls : "");
                    s.textContent = text;
                    if (tip) s.setAttribute("data-tip", tip);
                    return s;
                }
                function atcChipRow(chips) {
                    const row = document.createElement("div");
                    row.className = "v-atc-row";
                    chips.forEach(ch => row.appendChild(atcChip(ch.text, ch.tip, ch.cls)));
                    return row;
                }

                // One entry per role (TWR, GND, ...) instead of one per open sector; the sectors go into the hover text.
                function groupRoles(list) {
                    const groups = [];
                    list.forEach(c => {
                        const label = c.label || c.role;
                        let g = groups.find(x => x.label === label);
                        if (!g) { g = { role: c.role, label: label, items: [] }; groups.push(g); }
                        g.items.push(c);
                    });
                    return groups;
                }
                function groupTip(g) {
                    return g.items.map(c => c.callsign + "  " + c.freq + (c.kind ? "  ·  " + c.kind : "") + (c.code ? "  ·  information " + c.code : "")).join("\n");
                }
                function groupText(g) { return g.label; }

function ringContains(ring, lat, lon) {  // ray casting; ring = [[lat, lon], ...]
                    let inside = false;
                    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                        const yi = ring[i][0], xi = ring[i][1], yj = ring[j][0], xj = ring[j][1];
                        if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
                    }
                    return inside;
                }
                function areaContains(area, lat, lon) { return (area.poly || []).some(r => ringContains(r, lat, lon)); }

                // One FIR / approach polygon: staffed ones are tinted and can be hovered, unstaffed FIRs are only a faint outline.
                function drawArea(area, list, kind, ref, current) {
                    if (!area.poly || !area.poly.length) return 0;
                    const k = 360 * Math.round((nearestLon(area.lat, area.lon, ref) - area.lon) / 360);
                    const rings = k ? area.poly.map(r => r.map(pt => [pt[0], pt[1] + k])) : area.poly;
                    const color = kind === "app" ? "#a78bfa" : "#3b82f6";
                    const style = list
                        ? { color: current ? "#dbeafe" : color, weight: current ? 2.4 : 1.3, opacity: 0.9, fillColor: color, fillOpacity: 0.1, pane: "sectors" }
                        : { color: "#94a3b8", weight: 1, opacity: current ? 0.7 : 0.25, dashArray: "2 4", fill: false, interactive: false, pane: "sectors" };
                    const poly = L.polygon(rings, style).addTo(mapLayers.sectors);
                    if (list) {
                        const tip = document.createElement("div");
                        const head = document.createElement("b");
                        head.textContent = area.name || area.id;
                        tip.appendChild(head);
                        list.forEach(c => { const line = document.createElement("small"); line.textContent = c.callsign + "  " + c.freq; tip.appendChild(line); });
                        poly.bindTooltip(tip, { sticky: true, className: "v-map-tip" });
                        poly.on("mouseover", () => poly.setStyle({ fillOpacity: 0.24 }));
                        poly.on("mouseout", () => poly.setStyle({ fillOpacity: 0.1 }));
                    }
                    return k;
                }

                function renderAtc(p, depLL, arrLL, ref) {
                    mapLayers.atc.clearLayers();
                    mapLayers.sectors.clearLayers();
                    const info = relevantAtc(p);
                    const listEl = document.getElementById("atcList");
                    listEl.textContent = "";
                    const put = (ll, chips, dy) => {
                        L.marker(ll, { keyboard: false, icon: L.divIcon({ className: "v-atc", html: atcChipRow(chips), iconSize: [0, 0], iconAnchor: [0, -dy] }) }).addTo(mapLayers.atc);
                    };

                    // areas: which ones are staffed, and which one the aircraft is in right now
                    const staffedFir = {}, staffedApp = {};
                    info.firs.forEach(g => { staffedFir[g.area.id] = g.list; });
                    info.tracons.forEach(g => { staffedApp[g.area.id] = g.list; });
                    const inside = a => mapLive && areaContains(a, mapLive.lat, mapLive.lon);
                    const insideFirs = ((atcSpec && atcSpec.firs) || []).filter(inside);
                    const curFir = insideFirs.find(f => staffedFir[f.id]) || insideFirs.slice().sort((a, b) => b.id.length - a.id.length)[0] || null;
                    const curApp = ((atcSpec && atcSpec.tracons) || []).find(t => staffedApp[t.id] && inside(t)) || null;
                    if (atcSpec) {
                        const firIds = (atcSpec.firs || []).map(f => f.id);
                        (atcSpec.firs || []).forEach(f => {
                            // an unstaffed sub-sector ("SBBS-NS") whose parent FIR is also on the list would only add noise
                            if (!staffedFir[f.id] && f.id.includes("-") && firIds.includes(f.id.split("-")[0])) return;
                            drawArea(f, staffedFir[f.id], "fir", ref, curFir && curFir.id === f.id);
                        });
                        (atcSpec.tracons || []).forEach(t => { if (staffedApp[t.id]) drawArea(t, staffedApp[t.id], "app", ref, curApp && curApp.id === t.id); });
                    }

                    // chips on the map: one per role at the airports, one label per staffed FIR
                    info.airports.forEach(a => {
                        const ll = a.icao === String(p.origin).toUpperCase() ? depLL : arrLL;
                        if (ll) put(ll, groupRoles(a.list).map(g => ({ text: g.label, tip: groupTip(g) })), 9);
                    });
                    info.firGroups.forEach(g => {
                        const a = g.area, k = a.poly && a.poly.length ? 360 * Math.round((nearestLon(a.lat, a.lon, ref) - a.lon) / 360) : 0;
                        const ll = a.label ? [a.label[0], a.label[1] + k] : [a.lat, nearestLon(a.lat, a.lon, ref)];
                        put(ll, [{ text: a.id + " " + g.list[0].role, tip: (a.name ? a.name + "\n" : "") + g.list.map(c => c.callsign + "  " + c.freq).join("\n"), cls: "fir" }], -9);
                    });

                    // the list under the map, in flight order: where the aircraft is now, what is ahead, what is behind
                    const note = () => {
                        if (!atcSpec || !(atcSpec.firs || []).length) return;
                        const n = document.createElement("div");
                        n.className = "note";
                        n.textContent = atcSpec.source === "eet" ? "FIRs taken from the EET in the flight plan." : "No EET in the flight plan, FIRs estimated from the track and the direct path.";
                        listEl.appendChild(n);
                    };
                    if (!controllersLoaded) { const d = document.createElement("div"); d.textContent = "Checking online ATC…"; listEl.appendChild(d); return; }
                    if (!info.airports.length && !info.firs.length && !info.tracons.length && !curFir) {
                        const d = document.createElement("div"); d.textContent = "No ATC online for the airports or FIRs on this route."; listEl.appendChild(d); note(); return;
                    }
                    const row = (tag, cls) => {
                        const r = document.createElement("div"), t = document.createElement("span"), items = document.createElement("span");
                        r.className = "atc-row" + (cls ? " " + cls : ""); t.className = "atc-tag"; t.textContent = tag; items.className = "atc-items";
                        r.appendChild(t); r.appendChild(items);
                        return { el: r, items: items, count: 0 };
                    };
                    const addItem = (rw, node) => { rw.items.appendChild(node); rw.count++; };
                    const areaItem = g => {
                        const s = document.createElement("span"), b = document.createElement("b");
                        s.className = "atc-item"; b.textContent = g.area.id;
                        s.appendChild(b); s.appendChild(document.createTextNode(" " + g.list[0].role));
                        s.setAttribute("data-tip", (g.area.name ? g.area.name + "\n" : "") + g.list.map(c => c.callsign + "  " + c.freq).join("\n"));
                        return s;
                    };
                    const airportItem = a => {
                        const s = document.createElement("span"), b = document.createElement("b");
                        s.className = "atc-item"; b.textContent = a.icao; s.appendChild(b);
                        groupRoles(a.list).forEach(g => { const c = atcChip(groupText(g), groupTip(g)); c.style.marginLeft = "5px"; s.appendChild(c); });
                        return s;
                    };

                    const dist = ll => (ll && mapLive) ? distNM(mapLive.lat, mapLive.lon, ll[0], ll[1]) : Infinity;
                    const atDep = dist(depLL) <= 30, atArr = dist(arrLL) <= 30;
                    const past = trackPts.map(q => [q[0], q[1]]);
                    if (depLL && trackNote !== "statsim track") past.unshift(depLL);  // without a real track only the departure airport is known
                    // "already flown through": the server's list first (full-precision boundaries), our own polygon test as fallback
                    const visited = new Set((atcSpec && atcSpec.visited) || []);
                    const stateOf = g => g.parts.some(inside) ? "now" : ((g.parts.some(a => visited.has(a.id)) || past.some(q => g.parts.some(a => areaContains(a, q[0], q[1])))) ? "behind" : "ahead");
                    const firGroups = info.firGroups.map(g => ({ g: g, state: stateOf(g) }));
                    const depItem = info.airports.find(a => a.icao === String(p.origin).toUpperCase());
                    const arrItem = info.airports.find(a => a.icao === String(p.destination).toUpperCase() && a !== depItem);

                    const now = row("Now"), ahead = row("Ahead"), behind = row("Behind", "behind");
                    if (curApp) addItem(now, areaItem(info.tracons.find(t => t.area.id === curApp.id)));
                    firGroups.filter(x => x.state === "now").forEach(x => addItem(now, areaItem(x.g)));
                    if (!now.count && curFir) {
                        const s = document.createElement("span"), b = document.createElement("b");
                        s.className = "atc-item"; b.textContent = curFir.id; s.appendChild(b); s.appendChild(document.createTextNode(" (no ATC online)"));
                        addItem(now, s);
                    }
                    if (atDep && depItem) addItem(now, airportItem(depItem));
                    if (atArr && arrItem) addItem(now, airportItem(arrItem));
                    firGroups.filter(x => x.state === "ahead").forEach(x => addItem(ahead, areaItem(x.g)));
                    if (!atArr && arrItem) addItem(ahead, airportItem(arrItem));
                    firGroups.filter(x => x.state === "behind").reverse().forEach(x => addItem(behind, areaItem(x.g)));  // nearest first
                    if (!atDep && depItem) addItem(behind, airportItem(depItem));
                    [now, ahead, behind].forEach(rw => { if (rw.count) listEl.appendChild(rw.el); });
                    note();
                }

function applyLayerOptions() {
                    if (!flightMap || !mapLayers) return;
                    const chips = { rings: "tgRings", atc: "tgAtc", sectors: "tgSectors" };
                    Object.keys(chips).forEach(k => {
                        const g = mapLayers[k];
                        if (mapOpts[k] && !flightMap.hasLayer(g)) flightMap.addLayer(g);
                        if (!mapOpts[k] && flightMap.hasLayer(g)) flightMap.removeLayer(g);
                        const chip = document.getElementById(chips[k]);
                        if (chip) chip.classList.toggle("on", mapOpts[k]);
                    });
                    document.getElementById("atcList").style.display = mapOpts.atc ? "" : "none";
                }

                function toggleLayer(name) {
                    if (!(name in mapOpts)) return;
                    mapOpts[name] = !mapOpts[name];
                    applyLayerOptions();
                }

// Draws (first call) or moves (later calls) every layer of the map.
                function renderMapFlight(fit) {
                    const p = globalDossiers[currentlyOpenCallsign];
                    if (!flightMap || !p || !mapLive) return;
                    const dep = airportLatLon(p.origin), arr = airportLatLon(p.destination);
                    let planeLL = [mapLive.lat, mapLive.lon], path = null, arrLL = arr;
                    if (dep && arr) {
                        path = gcLine(dep, arr, 64);
                        arrLL = path[path.length - 1];
                        planeLL = [mapLive.lat, nearestLon(mapLive.lat, mapLive.lon, path)];
                    }
                    if (!mapLayers) {
                        flightMap.createPane("sectors");
                        flightMap.getPane("sectors").style.zIndex = 350;  // area fills sit under the routes, tracks and markers
                        mapLayers = { direct: L.layerGroup().addTo(flightMap), track: L.layerGroup().addTo(flightMap), rings: L.layerGroup(), sectors: L.layerGroup(), atc: L.layerGroup() };
                        [[p.origin, dep], [p.destination, arrLL]].forEach(([icao, ll]) => {
                            if (!ll) return;
                            L.circleMarker(ll, { radius: 4, color: "#e2e8f0", weight: 1.5, fillColor: "#0a0c14", fillOpacity: 1 })
                                .bindTooltip(icao, { permanent: true, direction: "top", offset: [0, -6], className: "v-map-tip" })
                                .bindPopup(airportPopup(icao)).addTo(flightMap);
                        });
                        mapLayers.plane = L.marker(planeLL, { icon: blipIcon(mapLive.heading), zIndexOffset: 1000, keyboard: false }).addTo(flightMap);
                        mapLayers.blipSvg = mapLayers.plane.getElement().querySelector("svg");
                        // the aircraft tag is its own marker so it can be dragged; a thin leader line ties it to the aircraft
                        const box = document.createElement("div");
                        box.className = "v-tag-box";
                        mapLayers.tagBox = box;
                        mapLayers.tag = L.marker(tagLatLng(planeLL), { draggable: true, keyboard: false, zIndexOffset: 900, icon: L.divIcon({ className: "v-tag", html: box, iconSize: [0, 0], iconAnchor: [0, 0] }) }).addTo(flightMap);
                        mapLayers.leader = L.polyline([planeLL, mapLayers.tag.getLatLng()], { color: "#94a3b8", weight: 1, opacity: 0.8, interactive: false }).addTo(flightMap);
                        mapLayers.tag.on("drag", e => mapLayers.leader.setLatLngs([mapLayers.plane.getLatLng(), e.latlng]));
                        mapLayers.tag.on("dragend", () => {
                            const a = flightMap.latLngToContainerPoint(mapLayers.plane.getLatLng()), b = flightMap.latLngToContainerPoint(mapLayers.tag.getLatLng());
                            tagOffset = { x: b.x - a.x, y: b.y - a.y };
                        });
                        flightMap.on("zoomend", () => { renderRings(); placeTag(); });
                        applyLayerOptions();
                    }
                    mapLayers.direct.clearLayers();
                    if (path) L.polyline(path, { color: "#e2e8f0", weight: 1.2, opacity: 0.35, dashArray: "1 6", interactive: false }).addTo(mapLayers.direct);
                    mapLayers.plane.setLatLng(planeLL);
                    if (mapLayers.blipSvg) mapLayers.blipSvg.style.transform = "rotate(" + (Number(mapLive.heading) || 0) + "deg)";
                    fillTag(mapLayers.tagBox, p, mapLive);
                    placeTag();
                    const pts = renderTrack(planeLL);

                    renderRings();
                    renderAtc(p, dep, arrLL, path || [planeLL]);
                    updateStrip(mapLive, arr);
                    renderProfile();
                    if (fit) {
                        const all = (path || []).concat([planeLL], pts.map(q => [q[0], q[1]]));
                        // extra room on the right so the tag next to the aircraft is never cut off
                        if (all.length > 1) flightMap.fitBounds(L.latLngBounds(all), { paddingTopLeft: [40, 40], paddingBottomRight: [150, 40], maxZoom: 8 });
                        else flightMap.setView(planeLL, 6);
                    }
                }

                function trackReasonText(reason) {
                    if (reason === "no_key") return "live samples only (statsim key not set)";
                    if (reason === "rate_limited") return "live samples only (track requests limited, try again in a minute)";
                    if (reason === "not_found" || reason === "no_positions") return "live samples only (no track on statsim yet)";
                    return "live samples only (track unavailable)";
                }

                // The statsim track is fetched on the server (the API key never reaches the browser) through a hidden field,
                // exactly like the rating lookup; the answer comes back through window.setFlightTrack.
                function requestFlightTrack(p, cs) {
                    try {
                        const input = window.parent.document.querySelector('input[aria-label="vs_track_req"]');
                        if (!input || !/^\d{1,10}$/.test(String(p.cid))) { trackNote = "live"; trackWhy = "live samples only (track bridge unavailable)"; renderProfile(); return; }
                        const win = window.parent;
                        const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, "value").set;
                        setter.call(input, String(p.cid) + ":" + cs + ":" + (Date.now() % 100000));
                        input.dispatchEvent(new win.Event("input", { bubbles: true }));
                        const enter = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true };
                        input.dispatchEvent(new win.KeyboardEvent("keydown", enter));
                        input.dispatchEvent(new win.KeyboardEvent("keypress", enter));
                        input.dispatchEvent(new win.KeyboardEvent("keyup", enter));
                        trackWait = setTimeout(() => {
                            if (mapFlightKey === String(p.cid) + ":" + cs && trackNote !== "statsim track") {
                                trackNote = "live"; trackWhy = "live samples only (track request timed out)"; renderProfile();
                            }
                        }, TRACK_WAIT_MS);
                    } catch (e) { trackNote = "live"; trackWhy = "live samples only (track unavailable)"; }
                }

                window.setFlightTrack = function(d) {
                    if (!d || !flightMap || d.key !== mapFlightKey) return;
                    if (trackWait) { clearTimeout(trackWait); trackWait = null; }
                    if (d.atc && Array.isArray(d.atc.firs)) atcSpec = d.atc;
                    if (d.ok && Array.isArray(d.points) && d.points.length) {
                        const lastT = d.points[d.points.length - 1][3];
                        const newer = trackPts.filter(q => q[3] > lastT + 10);  // live samples collected after statsim's last point
                        trackPts = d.points.concat(newer);
                        trackNote = "statsim track"; trackWhy = "";
                        renderMapFlight(true);
                    } else {
                        trackNote = "live"; trackWhy = trackReasonText(d.reason);
                        renderMapFlight(false);
                    }
                };

                async function pollLiveFlight() {
                    const cs = currentlyOpenCallsign;
                    if (!flightMap || !cs || document.hidden || mapBusy) return;
                    const base = globalDossiers[cs];
                    if (!base) return;
                    mapBusy = true;
                    const ctl = new AbortController();
                    const timeout = setTimeout(() => ctl.abort(), 12000);
                    try {
                        const res = await fetch(VATSIM_FEED_URL, { signal: ctl.signal });
                        if (!res.ok) return;
                        const feed = await res.json();
                        if (cs !== currentlyOpenCallsign || !flightMap) return;
                        lastControllers = Array.isArray(feed.controllers) ? feed.controllers : [];
                        lastAtis = Array.isArray(feed.atis) ? feed.atis : [];
                        controllersLoaded = true;
                        const live = (feed.pilots || []).find(x => String(x.cid) === String(base.cid) && x.callsign === cs);
                        if (!live) { setMapNote("This pilot is no longer online"); renderMapFlight(false); return; }
                        setMapNote("");
                        mapLive = { lat: live.latitude, lon: live.longitude, heading: live.heading, gs: live.groundspeed, alt: live.altitude };
                        pushTrackSample();
                        renderMapFlight(false);
                    } catch (e) { /* keep the last known position */ }
                    finally { clearTimeout(timeout); mapBusy = false; }
                }

                function closeMap() {
                    if (mapTimer) { clearInterval(mapTimer); mapTimer = null; }
                    if (trackWait) { clearTimeout(trackWait); trackWait = null; }
                    if (flightMap) { flightMap.remove(); flightMap = null; }
                    mapLayers = null; mapLive = null; mapFlightKey = ""; trackPts = []; trackNote = ""; trackWhy = "";
                    lastControllers = []; lastAtis = []; controllersLoaded = false; atcSpec = null;
                    document.getElementById("mapPanel").style.display = "none";
                    document.getElementById("popMapBadge").classList.remove("active");
                    setMapNote("");
                }

                async function toggleMap() {
                    const panel = document.getElementById("mapPanel");
                    if (panel.style.display === "block") { closeMap(); return; }
                    const cs = currentlyOpenCallsign, p = globalDossiers[cs];
                    if (!p) return;
                    panel.style.display = "block";
                    document.getElementById("popMapBadge").classList.add("active");
                    fillRibbon(p);
                    setMapNote("Loading map…");
                    try { await loadLeaflet(); } catch (e) { setMapNote("Map library could not be loaded"); return; }
                    if (panel.style.display !== "block" || cs !== currentlyOpenCallsign) return;
                    setMapNote("");
                    mapFlightKey = String(p.cid) + ":" + cs;
                    mapLive = { lat: p.lat, lon: p.lon, heading: p.heading, gs: p.gs, alt: p.alt };
                    trackPts = [[p.lat, p.lon, p.alt || 0, Math.floor(Date.now() / 1000), p.gs || 0]];
                    flightMap = L.map("flightMap", { minZoom: 2, attributionControl: true }).setView([p.lat || 30, p.lon || 0], 5);
                    L.tileLayer(MAP_TILES_URL, { maxZoom: 12, attribution: MAP_TILES_ATTRIBUTION }).addTo(flightMap);
                    renderMapFlight(true);
                    requestFlightTrack(p, cs);
                    mapTimer = setInterval(pollLiveFlight, MAP_REFRESH_MS);
                    pollLiveFlight();
                }

                function closeModal() {
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

            # Dynamic height: 48px per row, min 300, max 900
            dynamic_height = min(900, max(300, 120 + len(fir_pilots) * 48))
            st.components.v1.html(html_table_and_modal_code, height=dynamic_height, scrolling=True)

            st.markdown("<br>", unsafe_allow_html=True)
            csv = doc_fir.to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Download This FIR Data as CSV", data=csv, file_name=f"vatsim_fir_{selected_fir_prefix}_data.csv", mime="text/csv")
        else:
            st.warning("No active flights found within the boundaries of this unified FIR focus right now.")


# ─── Remaining tabs (FIR focus, CID and Network live above) ─────────────────
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
    </div>
    """, unsafe_allow_html=True)

else:
    st.error("Could not fetch data from VATSIM API. Please reload page.")