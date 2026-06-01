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
                if st.button("🗑️ Wipe Logs", use_container_width=False):
                    os.remove(LOG_FILE)
                    init_log_file()
                    st.rerun()
                    
            df_display = df_logs.sort_values(by="Timestamp", ascending=False).copy()
            df_display['Timestamp'] = df_display['Timestamp'].dt.strftime('%H:%M:%S || %Y-%m-%d')
            st.dataframe(df_display[["Timestamp", "Device_Type", "OS", "Browser", "Last_Action"]], width='stretch')
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

if "last_sync_check" not in st.session_state:
    st.session_state.last_sync_check = datetime.utcnow()

# Auto-update every 30 seconds on Python side
current_time = datetime.utcnow()
if (current_time - st.session_state.last_sync_check).total_seconds() >= 30:
    st.session_state.last_sync_time = current_time.strftime('%H:%M:%S Z')
    st.session_state.last_sync_check = current_time
    fetch_vatsim_data.clear()  # Force cache refresh
    st.rerun()

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

            # Display FIR data table with auto-refresh every 30 seconds (Python handles it via st.rerun)
            active_cols = ["Callsign"] + [c for c in st.session_state.visible_columns if c in doc_fir.columns]
            display_df = doc_fir[active_cols].copy()
            
            # Create clickable callsigns in the dataframe
            def create_clickable_table():
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.markdown("#### Available Aircraft")
                
                for idx, row in display_df.iterrows():
                    col1, col2, col3, col4 = st.columns([2, 1.5, 1.5, 0.5])
                    with col1:
                        if st.button(f"🛫 {row['Callsign']}", key=f"callsign_{idx}", use_container_width=True):
                            st.session_state.active_popup = row['Callsign']
                            st.rerun()
                    with col2:
                        st.caption(f"{row['Altitude (FT)']:.0f} FT")
                    with col3:
                        st.caption(f"{row['Speed (KT)']:.0f} KT")
            
            create_clickable_table()
            
            # Telemetry Dossier Modal when active_popup is set
            if st.session_state.active_popup and st.session_state.active_popup != "":
                selected_callsign = st.session_state.active_popup
                pilot_data = None
                
                # Find the pilot in the pilots list
                for p in pilots:
                    if p.get("callsign", "").upper() == selected_callsign.upper():
                        pilot_data = p
                        break
                
                if pilot_data:
                    with st.container(border=True):
                        st.markdown(f"### 🛰️ Telemetry Dossier Decoder — **{selected_callsign}**")
                        
                        col_close = st.columns([20, 1])[1]
                        with col_close:
                            if st.button("✕ Close", key="close_dossier"):
                                st.session_state.active_popup = ""
                                st.rerun()
                        
                        # Telemetry Details
                        fplan = pilot_data.get("flight_plan") or {}
                        dep = (fplan.get("departure") or "").strip().upper()
                        arr = (fplan.get("arrival") or "").strip().upper()
                        actype = (fplan.get("aircraft") or "").split("/")[0]
                        
                        # Ratings
                        p_ratings = {0:"OBS", 1:"P1", 2:"P2", 3:"P3", 4:"P4", 5:"P5"}
                        a_ratings = {0:"OBS", 1:"S1", 2:"S2", 3:"S3", 4:"C1", 5:"C2", 6:"C3", 7:"INS", 8:"INS+", 9:"SUP", 10:"ADM"}
                        p_rating = p_ratings.get(pilot_data.get("pilot_rating", 0), "P1")
                        a_rating = a_ratings.get(pilot_data.get("rating", 0), "OBS")
                        
                        # Online time
                        online_time = "Unknown"
                        if pilot_data.get("logon_time"):
                            log_dt = datetime.fromisoformat(pilot_data["logon_time"].replace("Z", "+00:00"))
                            online_mins = int((datetime.utcnow() - log_dt.replace(tzinfo=None)).total_seconds() / 60)
                            online_time = f"{online_mins} mins"
                        
                        # Flight Rules
                        flight_rules = fplan.get("flight_rules", "I")
                        rules_text = "IFR" if flight_rules == "I" else "VFR"
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("👤 Pilot Name", pilot_data.get("name", "Anonymous"))
                            st.metric("🆔 VATSIM CID", pilot_data.get("cid", "N/A"))
                        with col2:
                            st.metric("🎖️ Ratings", f"P:{p_rating} / ATC:{a_rating}")
                            st.metric("🟢 Online Time", online_time)
                        with col3:
                            st.metric("📡 Squawk", pilot_data.get("transponder", "0000"))
                            st.metric("📻 Voice", "🎙️ Active" if pilot_data.get("has_voice") else "⌨️ Text")
                        
                        st.divider()
                        
                        # Flight Progress Bar (Haversine calculation)
                        if dep and arr and dep in airports_coords_map and arr in airports_coords_map:
                            dep_coords = airports_coords_map[dep]
                            arr_coords = airports_coords_map[arr]
                            curr_lat = pilot_data.get("latitude", 0)
                            curr_lon = pilot_data.get("longitude", 0)
                            
                            # Haversine distance
                            def haversine(lat1, lon1, lat2, lon2):
                                from math import radians, cos, sin, asin, sqrt
                                lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                                dlon = lon2 - lon1
                                dlat = lat2 - lat1
                                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                                c = 2 * asin(sqrt(a))
                                r = 3440.065  # Radius of earth in nautical miles
                                return c * r
                            
                            total_nm = haversine(dep_coords.get("latitude", 0), dep_coords.get("longitude", 0),
                                                arr_coords.get("latitude", 0), arr_coords.get("longitude", 0))
                            flown_nm = haversine(dep_coords.get("latitude", 0), dep_coords.get("longitude", 0),
                                               curr_lat, curr_lon)
                            
                            if flown_nm > total_nm:
                                flown_nm = total_nm
                            
                            progress_pct = (flown_nm / total_nm * 100) if total_nm > 0 else 0
                            
                            st.markdown("##### 📍 Flight Progress")
                            col_dep, col_prog, col_arr = st.columns([1, 4, 1])
                            with col_dep:
                                st.caption(f"🛫 {dep}")
                            with col_prog:
                                st.progress(min(progress_pct / 100, 1.0), text=f"{flown_nm:.0f} NM ({progress_pct:.0f}%) / {total_nm:.0f} NM")
                            with col_arr:
                                st.caption(f"🛬 {arr}")
                        
                        st.divider()
                        
                        # Flight Details
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("**✈️ Origin**")
                            st.text(dep if dep else "⚠️ NO FPL")
                            st.markdown("**🛫 Destination**")
                            st.text(arr if arr else "⚠️ NO FPL")
                        with col2:
                            st.markdown("**📋 Aircraft Type**")
                            st.text(actype if actype else "Unknown")
                            st.markdown("**✈️ Flight Rules**")
                            st.text(rules_text)
                        
                        st.markdown("**🗺️ Filed Route**")
                        route_text = fplan.get("route", "No FPL Filed.")
                        st.text_area("Route", value=route_text, disabled=True, height=80)
            
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
    if anomalies: st.dataframe(anomalies, width='stretch')
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