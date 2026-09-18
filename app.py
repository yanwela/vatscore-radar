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
from shapely.geometry import shape, Point

from security_utils import is_valid_callsign, is_valid_fir_prefix
from registration_country import country_of_registration, extract_registration
from ui_theme import page_url, set_browser_title
from vatsim_data import fetch_member_rating

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
                        airlines_map[icao_code.upper().strip()] = {
                            "name": item.get("name", "Unknown Airline"),
                            "callsign": item.get("callsign", "UNKNOWN")
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
            return {
                icao: {"latitude_deg": lat, "longitude_deg": lon, "latitude": lat, "longitude": lon}
                for icao, lat, lon in zip(df[icao_col], df[lat_col], df[lon_col])
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
                    "longitude_deg": csv_db[dep]['longitude']
                }
                
        if arr and len(arr) == 4 and arr not in coords_map:
            if arr in csv_db:
                coords_map[arr] = {
                    "latitude_deg": csv_db[arr]['latitude'],
                    "longitude_deg": csv_db[arr]['longitude']
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
                            </div>
                            <hr style="border-color:#1e293b; margin-bottom:14px;">
                            
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
            
            // Eskiden tam olarak bu formatta havayolunun adını ve telsiz çağrı adını basıyorduk
            callsignField.innerText = name + " (" + telephony.toUpperCase() + ")";
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

                function closeModal() { 
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

            html_table_and_modal_code = raw_html_template\
                .replace("{HEADERS_PLACEHOLDER}", th_elements)\
                .replace("ACTIVE_COLS_PLACEHOLDER", js_safe(active_cols))\
                .replace("AUTO_OPEN_CALLSIGN_PLACEHOLDER", js_safe(st.session_state.active_popup))\
                .replace("AIRPORTS_DB_PLACEHOLDER", js_safe(airports_coords_map))\
                .replace("INITIAL_DATA_PLACEHOLDER", js_safe(filtered_pilots_raw))\
                .replace("AIRLINES_DB_PLACEHOLDER", js_safe(airlines_db))\
                .replace("FREQUENCIES_DB_PLACEHOLDER", js_safe(pilot_frequencies))\
                .replace("MEMBER_RATINGS_PLACEHOLDER", js_safe(st.session_state.member_ratings))\
                .replace("CID_STATS_URL_PLACEHOLDER", js_safe(page_url("CID_Stats")))

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