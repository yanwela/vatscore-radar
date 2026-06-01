import streamlit as st
import requests
import pandas as pd
from collections import Counter
from datetime import datetime
import os
import json

# ==============================================================================
# VATSCORE ENGINE - PREMIUM AIRLINE IDENTIFIER SYSTEM
# ==============================================================================

# API URLs
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_FIR_GEO_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatsim-data-geo/main/data/fir-boundaries.json"
VATSIM_RADAR_AIRLINES_URL = "https://data.vatsim-radar.com/airlines"
CSV_FILE_PATH = "airports.csv"

# Page Configuration
st.set_page_config(
    page_title="VatScore Web — Premium ScoreRadar", 
    page_icon="⚡", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Auto-refresh every 30 seconds so live VATSIM data and all tabs stay current.
if hasattr(st, "autorefresh"):
    st.autorefresh(interval=30000, limit=None, key="live_data_autorefresh")
else:
    refresh_html = """
    <script>
        // Load Streamlit component helper and emit a component value every 30s
        const s = document.createElement('script');
        s.src = 'https://cdn.jsdelivr.net/npm/@streamlit/component-lib@1.4.0/dist/index.min.js';
        s.onload = () => {
            function emitRefresh() { Streamlit.setComponentValue('AUTO_REFRESH'); }
            setTimeout(emitRefresh, 200);
            setInterval(emitRefresh, 30000);
        };
        document.head.appendChild(s);
    </script>
    """
    refresh_signal = st.components.v1.html(refresh_html, height=0, width=0)
    if isinstance(refresh_signal, str) and refresh_signal == 'AUTO_REFRESH':
        st.rerun()

# CUSTOM CSS
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stDecoration"] {display: none;}
    [data-testid="sidebarNav"] {display: none !important;}
    div[data-testid="stSidebar"] {display: none !important;}
    .main { background-color: #0f111a; }
    h1 { color: #3b82f6; font-family: 'Segoe UI', sans-serif; }
    .stTabs [data-baseweb="tab"] { color: #94a3b8; font-size: 16px; }
    .stTabs [data-baseweb="tab"]:hover { color: #3b82f6; }
    .stTabs [aria-selected="true"] { color: #3b82f6 !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { color: #22c55e; }
    .signature-container {
        text-align: right; font-family: 'Consolas', monospace; color: #475569; font-size: 12px;
        padding-top: 30px; border-top: 1px solid #1e293b; margin-top: 40px;
        line-height: 1.6;
    }
    .signature-link { color: #3b82f6; text-decoration: none; }
    .signature-link:hover { text-decoration: underline; }
    
    /* Roadmap Card Designs */
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
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123")

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

query_params = st.query_params
is_admin_route = query_params.get("admin") == "true"

if is_admin_route:
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    if not st.session_state.admin_authenticated:
        st.title("🛡️ VatScore HQ Security Login")
        passwd_input = st.text_input("Enter Master Admin Password:", type="password")
        if st.button("Authorize Connection"):
            if passwd_input == ADMIN_PASSWORD:
                st.session_state.admin_authenticated = True
                st.success("Access Granted.")
                st.rerun()
            else:
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
                if st.button("🗑️ Wipe Logs", use_container_width=True):
                    os.remove(LOG_FILE)
                    init_log_file()
                    st.rerun()
                    
            df_display = df_logs.sort_values(by="Timestamp", ascending=False).copy()
            df_display['Timestamp'] = df_display['Timestamp'].dt.strftime('%H:%M:%S || %Y-%m-%d')
            st.dataframe(df_display[["Timestamp", "Device_Type", "OS", "Browser", "Last_Action"]], use_container_width=True)
        st.stop()

@st.cache_data(ttl=30)
def fetch_vatsim_data():
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200: return r.json()
    except: pass
    return None

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

@st.cache_data(ttl=3600)
def load_global_fir_dictionary():
    fir_dict = {}
    try:
        response = requests.get(VATSIM_FIR_GEO_URL, timeout=10)
        if response.status_code == 200:
            geo_data = response.json()
            for feature in geo_data.get("features", []):
                properties = feature.get("properties", {})
                icao = properties.get("icao", properties.get("id", ""))
                name = properties.get("name", "Unknown FIR")
                if icao and len(icao) >= 2:
                    prefix = icao[:2].upper()
                    if prefix not in fir_dict: fir_dict[prefix] = name
    except: pass
    
    fallback = {"LT": "Turkey", "OM": "UAE & Oman", "EG": "United Kingdom", "ED": "Germany", "LF": "France", "K": "United States"}
    for k, v in fallback.items():
        if k not in fir_dict: fir_dict[k] = v
    return fir_dict

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
            
            res_dict = {}
            for _, row in df.iterrows():
                icao_code = row[icao_col]
                res_dict[icao_code] = {
                    "latitude_deg": float(row[lat_col]),
                    "longitude_deg": float(row[lon_col]),
                    "latitude": float(row[lat_col]),
                    "longitude": float(row[lon_col])
                }
            return res_dict
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

def classify_aircraft(ac_type, callsign):
    ac_type = str(ac_type).upper().strip()
    callsign = str(callsign).upper().strip()
    
    military_types = {
        "F16", "F18", "F15", "F22", "F35", "F4", "F5", "EFAF", "GR4", 
        "SU27", "SU35", "B52", "C17", "A400", "C130", "KC10", "K35R", 
        "E3TF", "B1B", "B2", "A10", "TOR", "H64", "UH60", "CH47", "NH90"
    }
    if ac_type in military_types: return "⚔️ Military"
    military_prefixes = ("TUR", "RCH", "AME", "BAF", "IAM", "GAF", "ASY", "MIL", "NAVY", "ARMY", "AF1", "AF2")
    if callsign.startswith(military_prefixes) or "MIL" in callsign: return "⚔️ Military"
        
    ga_types = {"C150", "C152", "C172", "C182", "C206", "C208", "P28A", "PA34", "DA40", "DA42", "SR22", "SR20", "E300", "DV20"}
    if ac_type in ga_types: return "🛩️ General Aviation"
        
    biz_jets = {"GLF5", "GLF6", "CL60", "CRJ2", "C56X", "FA7X", "LJ45"}
    if ac_type in biz_jets: return "💼 Business Jet"
        
    return "✈️ Commercial"

# --- LAST SYNC BACKEND TIME STAMP INITIALIZATION ---
if "last_sync_time" not in st.session_state:
    st.session_state.last_sync_time = datetime.utcnow().strftime('%H:%M:%S Z')

data = fetch_vatsim_data()
global_fir_map = load_global_fir_dictionary()

# Update last sync timestamp on every run (attempted fetch time)
st.session_state.last_sync_time = datetime.utcnow().strftime('%H:%M:%S Z')

if "iframe_signal" not in st.session_state:
    st.session_state.iframe_signal = 0

if data:
    st.session_state.last_sync_time = datetime.utcnow().strftime('%H:%M:%S Z')
    pilots = data.get("pilots", [])
    controllers = data.get("controllers", [])
    
    airports_coords_map = get_coordinates_from_library(pilots)

    title_col, refresh_col, emoji_col = st.columns([0.88, 0.06, 0.06])
    with title_col: st.title("⚡ VATSCORE // Premium Score Radar")
    
    with refresh_col:
        st.write("<div style='padding-top:25px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="top-emoji-btn">', unsafe_allow_html=True)
        refresh_clicked = st.button("🔄", help="Force Manual Refresh Now")
        st.markdown('</div>', unsafe_allow_html=True)
        if refresh_clicked:
            fetch_vatsim_data.clear()
            st.session_state.iframe_signal += 1
            st.session_state.last_sync_time = datetime.utcnow().strftime('%H:%M:%S Z')
            st.rerun()
    
    with emoji_col:
        st.write("<div style='padding-top:25px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="top-emoji-btn">', unsafe_allow_html=True)
        settings_clicked = st.button("⚙️", help="Click to toggle Column visibility and Fleet filters")
        st.markdown('</div>', unsafe_allow_html=True)

    if "show_panel" not in st.session_state: st.session_state.show_panel = False
    if settings_clicked: st.session_state.show_panel = not st.session_state.show_panel

    all_columns = ["Origin", "Destination", "Aircraft", "Category", "Altitude (FT)", "Speed (KT)", "Squawk"]
    if "visible_columns" not in st.session_state: st.session_state.visible_columns = all_columns.copy()
    if "fleet_filter_selection" not in st.session_state: st.session_state.fleet_filter_selection = "All Flights"
    if "rules_filter_selection" not in st.session_state: st.session_state.rules_filter_selection = "All Rules"

    if st.session_state.show_panel:
        with st.container():
            st.markdown("### ⚙️ Live Radar Customizer")
            cfg_col1, cfg_col2 = st.columns(2)
            with cfg_col1:
                st.session_state.visible_columns = st.multiselect("Select Table Columns:", options=all_columns, default=st.session_state.visible_columns)
            with cfg_col2:
                st.session_state.fleet_filter_selection = st.radio("Fleet Category Filter:", ["All Flights", "Commercial Only", "General Aviation Only", "Business Jet Only", "Military Only"], horizontal=True)
                st.session_state.rules_filter_selection = st.radio("Flight Rules Filter:", ["All Rules", "IFR Only", "VFR Only"], horizontal=True)
            st.markdown("---")

    # --- GREEN SYSTEM METRIC - PROPERLY CLEANED FROM OBJECT STRINGS ---
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1: st.metric(label="Total Live Pilots Worldwide", value=len(pilots))
    with col_stat2: st.metric(label="Total Active ATCs", value=len(controllers))
    with col_stat3: st.metric(label="System Status", value=st.session_state.last_sync_time)

    fir_pilots = []
    dep_airports, arr_airports, aircraft_types = [], [], []
    anomalies = []
    highest_p, fastest_p, slowest_p, veteran_p = None, None, None, None
    max_alt, max_gs, min_gs = -1, -1, 9999
    min_logon = "9999-12-31"

    fir_options = [f"{code} - {name}" for code, name in sorted(global_fir_map.items())]
    
    if "saved_fir" in st.query_params:
        st.session_state.current_fir_prefix = st.query_params["saved_fir"]
    
    if "current_fir_prefix" not in st.session_state:
        st.session_state.current_fir_prefix = "LT"

    matched_indices = [i for i, s in enumerate(fir_options) if s.startswith(st.session_state.current_fir_prefix)]
    calculated_index = matched_indices[0] if matched_indices else 0

    if "selected_callsign" in st.query_params:
        st.session_state.active_popup = st.query_params["selected_callsign"]
    if "active_popup" not in st.session_state:
        st.session_state.active_popup = ""

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏆 Leaderboard", "✈️ Selected FIR Focus", "🌐 Global Stats & ATC", "🛸 Anomaly Radar", "🚀 Project Roadmap"])

    with tab2:
        st.subheader("✈️ Regional Airspace Monitor")
        
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
        
        selected_fir_prefix = st.session_state.current_fir_prefix
        current_fleet_filter = st.session_state.fleet_filter_selection
        current_rules_filter = st.session_state.rules_filter_selection

        # Processing loop to build charts & statistics
        for p in pilots:
            callsign = p.get("callsign", "N/A")
            alt = p.get("altitude", 0)
            gs = p.get("groundspeed", 0)
            lat = p.get("latitude", 0.0)
            lon = p.get("longitude", 0.0)
            logon = p.get("logon_time", "")
            fplan = p.get("flight_plan") or {}
            dep = fplan.get("departure", "").strip().upper()
            arr = fplan.get("arrival", "").strip().upper()
            ac_type = fplan.get("aircraft", "").split("/")[0] or "N/A"
            flight_rules = fplan.get("flight_rules", "I")

            if dep: dep_airports.append(dep)
            if arr: arr_airports.append(arr)
            if ac_type and ac_type != "N/A": aircraft_types.append(ac_type)

            category = classify_aircraft(ac_type, callsign)
            if current_fleet_filter == "Commercial Only" and category != "✈️ Commercial": continue
            if current_fleet_filter == "General Aviation Only" and category != "🛩️ General Aviation": continue
            if current_fleet_filter == "Business Jet Only" and category != "💼 Business Jet": continue
            if current_fleet_filter == "Military Only" and category != "⚔️ Military": continue

            if current_rules_filter == "IFR Only" and flight_rules != "I": continue
            if current_rules_filter == "VFR Only" and flight_rules != "V": continue

            matches_flight_plan = str(dep).startswith(selected_fir_prefix) or str(arr).startswith(selected_fir_prefix)
            is_physically_here = False
            if selected_fir_prefix == "LT" and lat and lon and (36.5 <= lat <= 42.0) and (27.0 <= lon <= 44.5): 
                is_physically_here = True

            if matches_flight_plan or is_physically_here:
                display_dep = dep if dep else "⚠️ NO FPL"
                display_arr = arr if arr else "⚠️ NO FPL"
                
                fir_pilots.append({
                    "Callsign": callsign, "Origin": display_dep, "Destination": display_arr,
                    "Aircraft": ac_type if fplan.get("aircraft") else "Unknown",
                    "Category": category, "Altitude (FT)": alt, "Speed (KT)": gs, "Squawk": p.get("transponder", "0000"),
                    "FlightRules": flight_rules
                })

            if alt > max_alt: max_alt = alt; highest_p = p
            if gs > max_gs: max_gs = gs; fastest_p = p
            if alt > 3000 and 45 < gs < min_gs: min_gs = gs; slowest_p = p
            if logon and logon < min_logon: min_logon = logon; veteran_p = p

            if str(p.get("transponder")) == "7700": anomalies.append({"Type": "🚨 EMERGENCY (7700)", "Callsign": callsign, "Details": "Declared Mayday", "Airframe": ac_type})
            if gs > 1150: anomalies.append({"Type": "⚡ Warp Speed Glitch", "Callsign": callsign, "Details": f"Speed: {gs} KT", "Airframe": ac_type})
            if category == "⚔️ Military": anomalies.append({"Type": "⚔️ Tactical Sortie", "Callsign": callsign, "Details": "Military deployment", "Airframe": ac_type})

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
            st.info(f"Showing {len(doc_fir)} active aircraft tracks inside {selected_option}. Click a row to inspect full telemetry.")
            
            th_elements = "".join([f"<th>{col}</th>" for col in active_cols])
            
            # --- CUSTOM IFRAME HTML/JS ENGINE ---
            raw_html_template = """
            <div id="vatscore-custom-container">
                <div id="sync-notification">🛰️ Syncing Live VATSIM data...</div>
                <div id="signal-receiver" data-sig="SIGNAL_STAMP_PLACEHOLDER" style="display:none;"></div>

                <div id="dossierModal" class="v-modal">
                    <div class="v-modal-content">
                        <div class="v-modal-header">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span class="v-modal-title">🛰️ Telemetry Dossier Decoder</span>
                                <span id="popRulesBadge" class="v-rules-badge">IFR</span>
                            </div>
                            <span class="v-close-btn" onclick="closeModal()">&times;</span>
                        </div>
                        <div class="v-modal-body">
                            <h4 id="popCallsign" style="color:#3b82f6; margin-top:0; font-size:22px; font-family:sans-serif; letter-spacing:0.5px; font-style: italic;"></h4>
                            <hr style="border-color:#1e293b; margin-bottom:14px;">
                            
                            <p class="v-label" style="margin-bottom: 6px;">📍 Live Flight Trajectory & Distance Progress</p>
                            <div class="progress-wrapper">
                                <span id="progressDeparture" class="airport-badge">---</span>
                                <div class="progress-container">
                                    <div id="progressBarFill" class="progress-bar-fill"></div>
                                    <div id="progressPlaneIcon" class="progress-plane-icon">✈️</div>
                                </div>
                                <span id="progressArrival" class="airport-badge">---</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; margin-top:4px; margin-bottom:14px; font-size:13px; color:#3b82f6; font-family:monospace; font-weight:bold;">
                                <span id="progressCalculatedText">Distance Tracking Active</span>
                                <span id="progressPercentageText" style="margin-left:auto; color:#22c55e;">0 NM (0%) / Total 0 NM Flown</span>
                            </div>

                            <div class="v-grid">
                                <div>
                                    <p class="v-label">👤 Pilot Name</p><p id="popName" class="v-val"></p>
                                    <p class="v-label">🆔 VATSIM CID</p><p id="popCid" class="v-val"></p>
                                    <p class="v-label">🎖️ VATSIM Ratings</p><p id="popCombinedRating" class="v-val" style="color:#3b82f6; font-weight:600;"></p>
                                </div>
                                <div>
                                    <p class="v-label">🟢 Online Time</p><p id="popOnline" class="v-val" style="color:#22c55e; font-weight:bold;"></p>
                                    <p class="v-label">📻 VHF Comms & Frequency</p><p id="popVoice" class="v-val" style="color:#f59e0b;"></p>
                                    <p class="v-label">📡 Squawk Code</p><p id="popSquawkBox" class="v-val" style="color:#e2e8f0; font-family:monospace; font-weight:bold;"></p>
                                </div>
                                <div>
                                    <p class="v-label">🛫 Origin</p><p id="popOrigin" class="v-val"></p>
                                    <p class="v-label">🛬 Destination</p><p id="popDestination" class="v-val"></p>
                                    <p class="v-label">✈️ Airframe</p><p id="popAirframe" class="v-val"></p>
                                </div>
                            </div>
                            
                            <p class="v-label" style="margin-top:14px;">🎙️ Airline Identity (Airline Name - Callsign)</p>
                            <div class="telephony-premium-box">
                                <span id="airlineCallsignText" class="telephony-text">GENERAL AVIATION</span>
                            </div>

                            <p class="v-label" style="margin-top:14px;">🗺️ Filed Route String</p>
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
                .progress-plane-icon { position: absolute; top: 50%; left: 0%; transform: translate(-50%, -50%) rotate(0deg); font-size: 16px; transition: left 0.4s ease; line-height: 1; margin-top: -1px; }

                .telephony-premium-box { background-color: #141724; border: 1px solid #1e293b; padding: 12px 16px; border-radius: 6px; display: flex; align-items: center; }
                .telephony-text { font-size: 15px; font-weight: bold; color: #22c55e; letter-spacing: 0.5px; text-transform: uppercase; }

                #sync-notification {
                    position: fixed; bottom: 20px; left: 20px; background-color: #1e293b;
                    color: #3b82f6; padding: 10px 16px; border-radius: 30px; border: 1px solid #3b82f650;
                    font-size: 12px; font-weight: bold; font-family: monospace; z-index: 999999;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.5); display: none;
                    animation: pulse-blue 1.5s infinite ease-in-out;
                }
                @keyframes pulse-blue {
                    0% { opacity: 0.6; box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
                    70% { opacity: 1; box-shadow: 0 0 0 10px rgba(59, 130, 246, 0); }
                    100% { opacity: 0.6; box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
                }

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
                .v-rules-badge { background-color: #1d3531; color: #22c55e; border: 1px solid #22c55e40; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; font-family: monospace; }
                .v-close-btn { color: #94a3b8; font-size: 28px; font-weight: bold; cursor: pointer; line-height: 1; }
                .v-close-btn:hover { color: #ef4444; }
                .v-modal-body { padding: 22px; max-height: 85vh; overflow-y: auto; }
                .v-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
                .v-label { color: #64748b; font-size: 11px; font-weight: bold; text-transform: uppercase; margin: 6px 0 4px 0; }
                .v-val { color: #f1f5f9; font-size: 14px; background-color: #0a0c14; padding: 8px 12px; border-radius: 5px; margin: 0; border: 1px solid #1e293b; line-height: 1.4; }
                .v-textarea { width: 100%; height: 80px; background-color: #0a0c14; border: 1px solid #1e293b; color: #cbd5e1; padding: 10px; border-radius: 6px; resize: none; font-family: monospace; font-size: 13px; box-sizing: border-box; line-height: 1.4; }
            </style>

            <script>
                let globalDossiers = {};
                let currentlyOpenCallsign = null;
                const targetPrefix = "TARGET_PREFIX_PLACEHOLDER";
                const activeColumns = ACTIVE_COLS_PLACEHOLDER;
                const autoOpenCallsign = "AUTO_OPEN_CALLSIGN_PLACEHOLDER";
                const airportsDatabase = AIRPORTS_DB_PLACEHOLDER;
                const localAirlinesDb = AIRLINES_DB_PLACEHOLDER; 
                const rulesFilter = "RULES_FILTER_PLACEHOLDER";

                function updateHaversineProgressMetrics(depIcao, arrIcao, currentLat, currentLon) {
                    const txtBox = document.getElementById("progressPercentageText");
                    const fillBar = document.getElementById("progressBarFill");
                    const planeIcon = document.getElementById("progressPlaneIcon");

                    if (!depIcao || !arrIcao || !currentLat || !currentLon) {
                        txtBox.innerText = "No Position Metrics";
                        fillBar.style.width = "0%"; planeIcon.style.left = "0%"; return;
                    }
                    
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
                }

                function classifyAircraftLocal(acType, callsign) {
                    acType = String(acType).toUpperCase().trim();
                    callsign = String(callsign).toUpperCase().trim();
                    const milTypes = ["F16", "F18", "F15", "F22", "F35", "F4", "F5", "EFAF", "C17", "A400", "C130"];
                    if (milTypes.includes(acType)) return "⚔️ Military";
                    if (callsign.startsWith("TUR") || callsign.startsWith("RCH") || callsign.includes("MIL")) return "⚔️ Military";
                    const gaTypes = ["C172", "C152", "PA28", "DA40", "DA42"];
                    if (gaTypes.includes(acType)) return "🛩️ General Aviation";
                    return "✈️ Commercial";
                }

                function fetchAirlineCompany(callsign) {
                    const callsignField = document.getElementById("airlineCallsignText");
                    callsignField.innerText = "GENERAL AVIATION / PRIVATE";
                    if (!callsign) return;
                    let matches = callsign.match(/^[A-Z]+/i);
                    let cleanPrefix = matches ? matches[0].toUpperCase() : "";
                    if (cleanPrefix.length < 2) return;
                    
                    if (localAirlinesDb && localAirlinesDb[cleanPrefix]) {
                        let airlineData = localAirlinesDb[cleanPrefix];
                        if (airlineData && airlineData.name && airlineData.callsign) {
                            callsignField.innerText = airlineData.name + " - " + airlineData.callsign.toUpperCase();
                        } else if (airlineData && airlineData.name) {
                            callsignField.innerText = airlineData.name + " - " + cleanPrefix;
                        } else { callsignField.innerText = cleanPrefix; }
                    } else { callsignField.innerText = cleanPrefix; }
                }

                function sendTimeToStreamlitBackend() {
                    const now = new Date();
                    const hours = String(now.getUTCHours()).padStart(2, '0');
                    const minutes = String(now.getUTCMinutes()).padStart(2, '0');
                    const seconds = String(now.getUTCSeconds()).padStart(2, '0');
                    const formattedTime = hours + ":" + minutes + ":" + seconds + " Z";
                    
                    // PREVENTS SENDING CORES / DOM METRICS TO STREAMLIT RE-RENDER PARENT
                    // SENDS TEXT STRING INSTEAD
                    Streamlit.setComponentValue(formattedTime);
                }

                function buildTable(pilotsList) {
                    const tbody = document.getElementById("table-body");
                    tbody.innerHTML = "";
                    globalDossiers = {};

                    pilotsList.forEach(p => {
                        const callsign = p.callsign || "N/A";
                        const fplan = p.flight_plan || {};
                        const dep = (fplan.departure || "").trim().toUpperCase();
                        const arr = (fplan.arrival || "").trim().toUpperCase();
                        const acType = (fplan.aircraft || "").split("/")[0] || "N/A";
                        const category = classifyAircraftLocal(acType, callsign);
                        const fRules = fplan.flight_rules || "I";
                        
                        if (rulesFilter === "IFR Only" && fRules !== "I") return;
                        if (rulesFilter === "VFR Only" && fRules !== "V") return;

                        const matchesPlan = String(dep).startsWith(targetPrefix) || String(arr).startsWith(targetPrefix);
                        let isPhysHere = false;
                        if (targetPrefix === "LT" && p.latitude && p.longitude && (p.latitude >= 36.5 && p.latitude <= 42.0) && (p.longitude >= 27.0 && p.longitude <= 44.5)) {
                            isPhysHere = true;
                        }

                        if (matchesPlan || isPhysHere) {
                            const rowData = {
                                "Callsign": callsign, "Origin": dep || "⚠️ NO FPL", "Destination": arr || "⚠️ NO FPL",
                                "Aircraft": acType, "Category": category, "Altitude (FT)": p.altitude || 0,
                                "Speed (KT)": p.groundspeed || 0, "Squawk": p.transponder || "0000"
                            };

                            let onlineMins = "Unknown";
                            if (p.logon_time) {
                                const logDt = new Date(p.logon_time);
                                onlineMins = Math.floor((new Date() - logDt) / 60000) + " Mins";
                            }

                            const pRatings = {0:"OBS", 1:"P1", 2:"P2", 3:"P3", 4:"P4", 5:"P5"};
                            const aRatings = {0:"OBS", 1:"S1", 2:"S2", 3:"S3", 4:"C1", 5:"C2", 6:"C3", 7:"INS", 8:"INS+", 9:"SUP", 10:"ADM"};
                            
                            const pRatingText = pRatings[p.pilot_rating] || "P1";
                            const aRatingText = aRatings[p.rating] || "OBS";

                            globalDossiers[callsign] = {
                                name: p.name || "Anonymous", cid: p.cid || "N/A",
                                combined_rating: "P: " + pRatingText + " / ATC: " + aRatingText, online: onlineMins,
                                voice: p.has_voice ? "🎙️ Voice Active" : "⌨️ Text Only",
                                squawk: p.transponder || "0000", origin: rowData.Origin,
                                destination: rowData.Destination, airframe: acType, route: fplan.route || "No FPL Filed.",
                                heading: p.heading || 0, lat: p.latitude || 0, lon: p.longitude || 0,
                                rules: fRules === "V" ? "VFR" : "IFR"
                            };

                            const tr = document.createElement("tr");
                            tr.onclick = () => openDossier(callsign);
                            
                            activeColumns.forEach(col => {
                                const td = document.createElement("td");
                                if (col === "Callsign") {
                                    td.innerHTML = '<b style="color:#3b82f6; cursor:pointer;">' + rowData[col] + '</b>';
                                } else { td.innerText = rowData[col]; }
                                tr.appendChild(td);
                            });
                            tbody.appendChild(tr);
                        }
                    });
                }

                function openDossier(callsign) {
                    const p = globalDossiers[callsign];
                    if (!p) return;
                    currentlyOpenCallsign = callsign;

                    document.getElementById("popCallsign").innerText = " Target Profile: " + callsign;
                    document.getElementById("popName").innerText = p.name;
                    document.getElementById("popCid").innerText = p.cid;
                    document.getElementById("popCombinedRating").innerText = p.combined_rating;
                    document.getElementById("popOnline").innerText = p.online;
                    document.getElementById("popVoice").innerText = p.voice;
                    document.getElementById("popSquawkBox").innerText = p.squawk;
                    document.getElementById("popOrigin").innerText = p.origin;
                    document.getElementById("popDestination").innerText = p.destination;
                    document.getElementById("popAirframe").innerText = p.airframe;
                    document.getElementById("popRoute").value = p.route;

                    const badge = document.getElementById("popRulesBadge");
                    badge.innerText = p.rules;
                    if (p.rules === "VFR") {
                        badge.style.backgroundColor = "#143a24"; badge.style.color = "#22c55e"; badge.style.borderColor = "#22c55e40";
                    } else {
                        badge.style.backgroundColor = "#1d2e47"; badge.style.color = "#3b82f6"; badge.style.borderColor = "#3b82f640";
                    }

                    document.getElementById("progressDeparture").innerText = p.origin;
                    document.getElementById("progressArrival").innerText = p.destination;

                    updateHaversineProgressMetrics(p.origin, p.destination, p.lat, p.lon);
                    fetchAirlineCompany(callsign);
                    document.getElementById("dossierModal").style.display = "block";
                }

                function closeModal() { 
                    currentlyOpenCallsign = null;
                    document.getElementById("dossierModal").style.display = "none"; 
                }
                
                window.onclick = function(e) { 
                    if (e.target == document.getElementById("dossierModal")) closeModal(); 
                }

                async function updateData() {
                    const notifier = document.getElementById("sync-notification");
                    notifier.style.display = "block";
                    try {
                        const res = await fetch("https://data.vatsim.net/v3/vatsim-data.json");
                        const data = await res.json();
                        if (data && data.pilots) {
                            buildTable(data.pilots);
                            sendTimeToStreamlitBackend();
                            if (currentlyOpenCallsign && globalDossiers[currentlyOpenCallsign]) {
                                openDossier(currentlyOpenCallsign);
                            }
                        }
                    } catch(e) { console.log(e); }
                    setTimeout(() => { notifier.style.display = "none"; }, 1500);
                }

                // INJECT STREAMLIT COMPONENT LIBS
                const scriptStreamlit = document.createElement('script');
                scriptStreamlit.src = "https://cdn.jsdelivr.net/npm/@streamlit/component-lib@1.4.0/dist/index.min.js";
                document.head.appendChild(scriptStreamlit);

                const initialData = INITIAL_DATA_PLACEHOLDER;
                buildTable(initialData);

                if (autoOpenCallsign && autoOpenCallsign !== "") {
                    setTimeout(() => { openDossier(autoOpenCallsign); }, 250);
                }

                setInterval(() => {
                    const el = document.getElementById("signal-receiver");
                    const currentSig = el.getAttribute("data-sig");
                    if (window.lastKnownSig !== undefined && window.lastKnownSig !== currentSig) {
                        updateData();
                    }
                    window.lastKnownSig = currentSig;
                }, 500);

                setInterval(updateData, 30000);
            </script>
            """
            
            airlines_db = load_vatsim_radar_airlines()
            
            html_table_and_modal_code = raw_html_template\
                .replace("{HEADERS_PLACEHOLDER}", th_elements)\
                .replace("TARGET_PREFIX_PLACEHOLDER", str(selected_fir_prefix))\
                .replace("ACTIVE_COLS_PLACEHOLDER", json.dumps(active_cols))\
                .replace("AUTO_OPEN_CALLSIGN_PLACEHOLDER", st.session_state.active_popup)\
                .replace("AIRPORTS_DB_PLACEHOLDER", json.dumps(airports_coords_map))\
                .replace("INITIAL_DATA_PLACEHOLDER", json.dumps(pilots))\
                .replace("SIGNAL_STAMP_PLACEHOLDER", str(st.session_state.iframe_signal))\
                .replace("AIRLINES_DB_PLACEHOLDER", json.dumps(airlines_db))\
                .replace("RULES_FILTER_PLACEHOLDER", str(current_rules_filter))

            # --- CORRECTION: USE STREAMLIT NATIVE SAFARI WRAPPER VAL CAPTURING ---
            iframe_output = st.components.v1.html(html_table_and_modal_code, height=650, scrolling=True)
            
            # If the iframe returns data, ensure it is a string before matching
            if iframe_output and isinstance(iframe_output, str) and "DeltaGenerator" not in iframe_output:
                if iframe_output != st.session_state.last_sync_time:
                    st.session_state.last_sync_time = iframe_output
                    st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            csv = doc_fir.to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Download This FIR Data as CSV", data=csv, file_name=f"vatsim_fir_{selected_fir_prefix}_data.csv", mime="text/csv")
        else:
            st.warning("No active flights found for this region prefix right now.")

with tab1:
    st.subheader("Current Flight Records")
    leader_data = []
    if highest_p: leader_data.append({"Record Category": "Highest Cruising Altitude", "Callsign": highest_p['callsign'], "Value": f"{highest_p['altitude']:,} FT", "Pilot": highest_p.get('name')})
    if fastest_p: leader_data.append({"Record Category": "Maximum Velocity (GS)", "Callsign": fastest_p['callsign'], "Value": f"{fastest_p['groundspeed']} KT", "Pilot": fastest_p.get('name')})
    if slowest_p: leader_data.append({"Record Category": "Slowest Airborne Profile", "Callsign": slowest_p['callsign'], "Value": f"{slowest_p['groundspeed']} KT", "Pilot": slowest_p.get('name')})
    if veteran_p: leader_data.append({"Record Category": "Longest Session (Veteran)", "Callsign": veteran_p['callsign'], "Value": f"Since {veteran_p.get('logon_time','')[11:16]} UTC", "Pilot": veteran_p.get('name')})
    st.table(leader_data)

with tab3:
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
        atc_pos = [a.get("callsign", "").split("_")[0] for a in controllers if "_" in a.get("callsign", "")]
        for k, v in Counter(atc_pos).most_common(4): st.write(f"• `{k}_CTR` : {v} open frequencies")

with tab4:
    st.subheader("🛸 Live Anomaly Radar (X-Files)")
    if anomalies: st.dataframe(anomalies, use_container_width=True)
    else: st.success("Sky is clear. No telemetric anomalies or emergencies detected.")

with tab5:
    st.subheader("🚀 VatScore Strategic Development Roadmap")
    st.markdown("""
    <div class="roadmap-card">
        <div class="roadmap-badge" style="background-color: #22c55e;">Phase 1: Completed</div>
        <div class="roadmap-title">✈️ Custom HTML/JS Grid Engine & Flight Detail Insight System</div>
        <div class="roadmap-desc">
            <strong>Status:</strong> Completed — May 31, 2026<br>
            Implementation of a high-performance HTML/JS grid engine enabling real-time telemetry inspection. Users can now access detailed flight plan strings, pilot profiles, and communication frequency metadata through an integrated native JavaScript modal.
        </div>
    </div>
    <div class="roadmap-card in-progress">
        <div class="roadmap-badge" style="background-color: #f59e0b;">Phase 2: In Progress — Codename: "babybus"</div>
        <div class="roadmap-title">📢 Advanced Telemetry Tracking & Precision Filtering</div>
        <div class="roadmap-desc">
            <strong>Status:</strong> Active Development (June 2026)<br>
            Focusing on operational depth and data accuracy. Key milestones include:
            <ul>
                <li><strong> Real-Time Haversine Engine:</strong> Successfully integrated precise distance calculations and a dynamic progress bar within the telemetry dossier.</li>
                <li><strong> Flight Rule Identification:</strong> Completed the deployment of the integrated IFR/VFR Rule Box for instant flight type classification.</li>
                <li><strong> Dynamic Telephony Engine:</strong> Currently optimizing the asynchronous API matcher to map ICAO prefixes to standardized airline callsigns.</li>
            </ul>
        </div>
    </div>
    """, unsafe_allow_html=True)

if data:
    st.markdown("""
    <div class="signature-container">
        ⚡ VatScore Dashboard // Made by alp-1863530 <br>
        📬 For any questions or requests, contact:
        <a class="signature-link" href="mailto:alpqwesy1@gmail.com">alpqwesy1@gmail.com</a>
    </div>
    """, unsafe_allow_html=True)
else:
    st.error("Could not fetch data from VATSIM API. Please reload page.")