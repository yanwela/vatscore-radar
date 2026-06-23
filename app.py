import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter
from datetime import datetime, timezone
import os
import json
import re
from shapely.geometry import shape, Point

# API URLs
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_FIR_GEO_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/Boundaries.geojson"
VATSIM_RADAR_AIRLINES_URL = "https://data.vatsim-radar.com/airlines"
CSV_FILE_PATH = "airports.csv"

# Page Configuration
st.set_page_config(
    page_title="VatScore Web — Premium ScoreRadar", 
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

@st.cache_data(ttl=15)
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
                properties = feature.get("properties", {})
                geometry = feature.get("geometry", {})
                icao = properties.get("id", properties.get("icao", "")).upper().strip()
                if not icao:
                    continue
                prefix = "K" if icao.startswith("K") else icao[:2]
                if prefix not in raw_groups:
                    raw_groups[prefix] = []
                if geometry:
                    raw_groups[prefix].append(geometry)
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
    if ac_type in military_types: return "Military"
    military_prefixes = ("TUR", "RCH", "AME", "BAF", "IAM", "GAF", "ASY", "MIL", "NAVY", "ARMY", "AF1", "AF2")
    if callsign.startswith(military_prefixes) or "MIL" in callsign: return "Military"
        
    ga_types = {"C150", "C152", "C172", "C182", "C206", "C208", "P28A", "PA34", "DA40", "DA42", "SR22", "SR20", "E300", "DV20"}
    if ac_type in ga_types: return "General Aviation"
        
    biz_jets = {"GLF5", "GLF6", "CL60", "CRJ2", "C56X", "FA7X", "LJ45"}
    if ac_type in biz_jets: return "Business Jet"
        
    return "Commercial"

if "last_js_sync_time" not in st.session_state:
    st.session_state.last_js_sync_time = datetime.utcnow().strftime('%H:%M:%S Z')

data = fetch_vatsim_data()
global_grouped_firs = load_and_group_fir_boundaries()

if "iframe_signal" not in st.session_state:
    st.session_state.iframe_signal = 0

if data:
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
            st.session_state.last_js_sync_time = datetime.utcnow().strftime('%H:%M:%S Z')
    
    with emoji_col:
        st.write("<div style='padding-top:25px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="top-emoji-btn">', unsafe_allow_html=True)
        settings_clicked = st.button("⚙️", help="Click to toggle Column visibility and Fleet filters")
        st.markdown('</div>', unsafe_allow_html=True)

    if "show_panel" not in st.session_state: st.session_state.show_panel = False
    if settings_clicked:
        st.session_state.show_panel = not st.session_state.show_panel
        st.rerun()

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

    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1: st.metric(label="Total Live Pilots Worldwide", value=len(pilots))
    with col_stat2: st.metric(label="Total Active ATCs", value=len(controllers))
    with col_stat3: st.metric(label="Last Sync", value=f" {st.session_state.last_js_sync_time}")

    fir_pilots = []
    filtered_pilots_raw = []
    dep_airports, arr_airports, aircraft_types = [], [], []
    anomalies = []
    highest_p, fastest_p, slowest_p, veteran_p = None, None, None, None
    max_alt, max_gs, min_gs = -1, -1, 9999
    min_logon = "9999-12-31"

    defined_fir_prefixes = {"LT", "ED", "EG", "LF", "K", "OM", "LO", "LI", "LE"}
    fir_options = [f"{code} - {info['name']}" for code, info in sorted(global_grouped_firs.items()) if code in defined_fir_prefixes]
    
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

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🏆 Leaderboard", "✈️ Selected FIR Focus", "🌐 Global Stats & ATC", "🛸 Anomaly Radar", "🚀 Project Roadmap", "📊 CID Stats"])

    with tab2:
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
            cid = str(p.get("cid", "N/A"))
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

            matches_flight_plan = str(dep).startswith(selected_fir_prefix) or str(arr).startswith(selected_fir_prefix)
            
            is_physically_here = False
            if lat and lon and target_fir_shapes:
                aircraft_point = Point(lon, lat)
                for fir_shape in target_fir_shapes:
                    if aircraft_point.within(fir_shape):
                        is_physically_here = True
                        break

            if st.session_state.only_physical_inside:
                include_aircraft = is_physically_here
            else:
                include_aircraft = matches_flight_plan

            if include_aircraft:
                display_dep = dep if dep else "NO FPL"
                display_arr = arr if arr else "NO FPL"
                
                fir_pilots.append({
                    "Callsign": callsign, "Origin": display_dep, "Destination": display_arr,
                    "Aircraft": ac_type if fplan.get("aircraft") else "Unknown",
                    "Category": category, "Altitude (FT)": alt, "Speed (KT)": gs, "Squawk": p.get("transponder", "0000"),
                    "FlightRules": flight_rules
                })
                filtered_pilots_raw.append(p)

            if alt > max_alt: max_alt = alt; highest_p = p
            if gs > max_gs: max_gs = gs; fastest_p = p
            if alt > 3000 and 45 < gs < min_gs: min_gs = gs; slowest_p = p
            if logon and logon < min_logon: min_logon = logon; veteran_p = p

            if str(p.get("transponder")) == "7700": 
                anomalies.append({"Type": "🚨 EMERGENCY (7700)", "Callsign": callsign, "Details": "Declared Mayday Status", "Airframe": ac_type, "Altitude": alt, "Speed": gs})
            if gs > 1150: 
                anomalies.append({"Type": "⚠️ Warp Speed Glitch", "Callsign": callsign, "Details": f"Critical Speed: {gs} KT", "Airframe": ac_type, "Altitude": alt, "Speed": gs})
            if category == "Military": 
                anomalies.append({"Type": "⚔️ Tactical Sortie", "Callsign": callsign, "Details": "Military deployment sector track", "Airframe": ac_type, "Altitude": alt, "Speed": gs})
            
            vip_cid_array = [c.strip() for c in st.session_state.vip_cids.split(",") if c.strip()]
            vip_callsign_array = [cs.strip().upper() for cs in st.session_state.vip_callsigns.split(",") if cs.strip()]
            if cid in vip_cid_array or callsign in vip_callsign_array:
                anomalies.insert(0, {
                    "Type": "🎯 VIP WATCHLIST TARGET DETECTED",
                    "Callsign": f"{callsign} (CID: {cid})",
                    "Details": f"Tracked Pilot Online - Route: {dep}->{arr}",
                    "Airframe": ac_type,
                    "Altitude": alt,
                    "Speed": gs
                })

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
            
            raw_html_template = """
            <div id="vatscore-custom-container">
                <div id="sync-notification">Syncing Live VATSIM data...</div>
                <div id="signal-receiver" data-sig="SIGNAL_STAMP_PLACEHOLDER" style="display:none;"></div>

                <div id="dossierModal" class="v-modal">
                    <div class="v-modal-content">
                        <div class="v-modal-header">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span class="v-modal-title">Telemetry Dossier Decoder</span>
                            </div>
                            <span class="v-close-btn" onclick="closeModal()">&times;</span>
                        </div>
                        <div class="v-modal-body">
                            <div style="display: flex; align-items: center; gap: 12px; margin-top:0; margin-bottom:14px;">
                                <h4 id="popCallsign" style="color:#3b82f6; margin:0; font-size:22px; font-family:sans-serif; letter-spacing:0.5px; font-style: italic;"></h4>
                                <span id="popRulesBadge" class="v-rules-badge">IFR</span>
                            </div>
                            <hr style="border-color:#1e293b; margin-bottom:14px;">
                            
                            <p class="v-label" style="margin-bottom: 6px;">Live Flight Trajectory & Distance Progress</p>
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

                            <p class="v-label" style="margin-top:14px;">Filed Route String</p>
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
                .v-rules-badge { background-color: #143a24; color: #22c55e; border: 1px solid #22c55e40; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; font-family: monospace; }
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
                const isolationFilterRaw = "ISOLATION_FILTER_PLACEHOLDER";
                const includeArrDepJs = INCLUDE_ARR_DEP_PLACEHOLDER;

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

                function classifyAircraftLocal(acType, callsign) {
                    acType = String(acType).toUpperCase().trim();
                    callsign = String(callsign).toUpperCase().trim();
                    const milTypes = ["F16", "F18", "F15", "F22", "F35", "F4", "F5", "EFAF", "C17", "A400", "C130"];
                    if (milTypes.includes(acType)) return "Military";
                    if (callsign.startsWith("TUR") || callsign.startsWith("RCH") || callsign.includes("MIL")) return "Military";
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

                function sendTimeToStreamlitBackend() {
                    const now = new Date();
                    const hours = String(now.getUTCHours()).padStart(2, '0');
                    const minutes = String(now.getUTCMinutes()).padStart(2, '0');
                    const seconds = String(now.getUTCSeconds()).padStart(2, '0');
                    const formattedTime = hours + ":" + minutes + ":" + seconds + " Z";
                    Streamlit.setComponentValue(formattedTime);
                }

                function buildTable(pilotsList) {
                    const tbody = document.getElementById("table-body");
                    tbody.innerHTML = "";
                    globalDossiers = {};

                    let allowedAirlines = [];
                    if (isolationFilterRaw && isolationFilterRaw.trim() !== "") {
                        allowedAirlines = isolationFilterRaw.split(",").map(s => s.trim().toUpperCase()).filter(s => s.length > 0);
                    }

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

                        if (allowedAirlines.length > 0) {
                            let csPrefixMatch = callsign.match(/^[A-Z]+/i);
                            let csPrefix = csPrefixMatch ? csPrefixMatch[0].toUpperCase() : "";
                            if (!allowedAirlines.includes(csPrefix)) return;
                        }

                        let matchesPlan = false;
                        if (includeArrDepJs) {
                            matchesPlan = String(dep).startsWith(targetPrefix) || String(arr).startsWith(targetPrefix);
                        }
                        
                        // Backend already filtered pilots by Shapely boundary check — all pilots in this list are physically inside the FIR
                        let isPhysHere = p.latitude && p.longitude ? true : false;

                        if (isPhysHere || matchesPlan) {
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

                            const pRatings = {0:"OBS", 1:"P1", 2:"P2", 3:"P3", 4:"P4", 5:"P5"};
                            const aRatings = {0:"OBS", 1:"S1", 2:"S2", 3:"S3", 4:"C1", 5:"C2", 6:"C3", 7:"INS", 8:"INS+", 9:"SUP", 10:"ADM"};
                            
                            const pRatingText = pRatings[p.pilot_rating] || "P1";
                            const aRatingText = aRatings[p.rating] || "OBS";

                            globalDossiers[callsign] = {
                                name: p.name || "Anonymous", cid: p.cid || "N/A",
                                combined_rating: "P: " + pRatingText + " / ATC: " + aRatingText, online: onlineMins,
                                voice: p.has_voice ? "Voice Active" : "Text Only",
                                squawk: p.transponder || "0000", origin: rowData.Origin,
                                destination: rowData.Destination, airframe: acType, route: fplan.route || "No FPL Filed.",
                                heading: p.heading || 0, lat: p.latitude || 0, lon: p.longitude || 0,
                                rules: fRules === "V" ? "VFR" : "IFR",
                                reg: (function(r) { if (!r) return ""; const m = r.match(/REG\/([A-Z0-9\-]{2,10})/i); return m ? m[1].toUpperCase() : ""; })(fplan.remarks || ""),
                                selcal: (function(r) { if (!r) return ""; const m = r.match(/SEL\/([A-Z]{4})/i); return m ? m[1].toUpperCase() : ""; })(fplan.remarks || "")
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
                    try {
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
                        // Build airframe display as "Type | Reg | SELCAL" — show only available parts
                        const airframeParts = [p.airframe];
                        if (p.reg) airframeParts.push(p.reg);
                        if (p.selcal) airframeParts.push(p.selcal);
                        document.getElementById("popAirframe").innerText = airframeParts.join(" | ");
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
                    } catch (fatalErr) {
                        console.log("Fatal crash intercepted in openDossier:", fatalErr);
                    }
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
                        // Trigger Streamlit rerun via backend time sync — Python handles filtering and re-renders filtered data
                        sendTimeToStreamlitBackend();
                        if (currentlyOpenCallsign && globalDossiers[currentlyOpenCallsign]) {
                            openDossier(currentlyOpenCallsign);
                        }
                    } catch(e) { console.log(e); }
                    setTimeout(() => { notifier.style.display = "none"; }, 1500);
                }

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
                .replace("INITIAL_DATA_PLACEHOLDER", json.dumps(filtered_pilots_raw))\
                .replace("SIGNAL_STAMP_PLACEHOLDER", str(st.session_state.iframe_signal))\
                .replace("AIRLINES_DB_PLACEHOLDER", json.dumps(airlines_db))\
                .replace("RULES_FILTER_PLACEHOLDER", str(current_rules_filter))\
                .replace("INCLUDE_ARR_DEP_PLACEHOLDER", "false" if st.session_state.only_physical_inside else "true")\
                .replace("ISOLATION_FILTER_PLACEHOLDER", str(current_isolation_filter))

            # Dynamic height: 48px per row, min 300, max 900
            dynamic_height = min(900, max(300, 120 + len(fir_pilots) * 48))
            iframe_output = st.components.v1.html(html_table_and_modal_code, height=dynamic_height, scrolling=True)
            
            if iframe_output and isinstance(iframe_output, str) and "DeltaGenerator" not in iframe_output:
                if iframe_output != st.session_state.get("last_js_sync_time", ""):
                    st.session_state.last_js_sync_time = iframe_output
                    st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            csv = doc_fir.to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Download This FIR Data as CSV", data=csv, file_name=f"vatsim_fir_{selected_fir_prefix}_data.csv", mime="text/csv")
        else:
            st.warning("No active flights found within the boundaries of this unified FIR focus right now.")


# ─── CID Stats — statsim.net API ─────────────────────────────────────────────
STATSIM_API  = "https://api.statsim.net/api"
VATSIM_DATA_LIVE = "https://data.vatsim.net/v3/vatsim-data.json"
HISTORY_FROM = "2015-01-01T00:00:00.000Z"

ATC_RATINGS = {
    -1: "Inactive", 0: "OBS", 1: "S1", 2: "S2", 3: "S3",
    4: "C1", 5: "C2", 6: "C3", 7: "I1", 8: "I2", 9: "I3", 10: "SUP", 11: "ADM"
}
MILITARY_RATINGS = {0: "None", 1: "M1", 2: "M2", 3: "M3"}

def decode_pilot_rating(v):
    try: v = int(v)
    except: return "P0"
    if v >= 63: return "P6 · Ferry"
    if v >= 31: return "P5 · CTP"
    if v >= 15: return "P4 · ATP"
    if v >= 7:  return "P3 · CMEL"
    if v >= 3:  return "P2 · IR"
    if v >= 1:  return "P1 · PPL"
    return "P0 · New"

def _sh():
    key = st.secrets.get("STATSIM_API_KEY", "")
    return {"X-API-Key": key, "accept": "application/json", "User-Agent": "VatScore/3.0"}

@st.cache_data(ttl=600, show_spinner=False)
def statsim_flights(cid):
    from datetime import timezone as tz
    _n = datetime.now(tz.utc)
    now = _n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_n.microsecond//1000:03d}Z"
    # params= kullanmıyoruz: requests ':' -> '%3A' encode eder, statsim 400 verir
    url = f"{STATSIM_API}/Flights/VatsimId?vatsimId={cid}&from={HISTORY_FROM}&to={now}"
    try:
        r = requests.get(url, headers=_sh(), timeout=25)
        if r.status_code == 200:
            return r.json()
        st.session_state["_cid_flights_err"] = f"{r.status_code}: {r.text[:200]}"
    except Exception as e:
        st.session_state["_cid_flights_err"] = str(e)
    return []

@st.cache_data(ttl=600, show_spinner=False)
def statsim_atc(cid):
    from datetime import timezone as tz
    _n = datetime.now(tz.utc)
    now = _n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_n.microsecond//1000:03d}Z"
    url = f"{STATSIM_API}/Atcsessions/VatsimId?vatsimId={cid}&from={HISTORY_FROM}&to={now}"
    try:
        r = requests.get(url, headers=_sh(), timeout=25)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

@st.cache_data(ttl=30, show_spinner=False)
def live_pilot_lookup(cid):
    try:
        r = requests.get(VATSIM_DATA_LIVE, timeout=10)
        if r.status_code == 200:
            for p in r.json().get("pilots", []):
                if str(p.get("cid","")) == cid:
                    return p
    except: pass
    return None

def _parse_dt(s):
    if not s: return pd.NaT
    try: return pd.to_datetime(s, utc=True)
    except: return pd.NaT

def _fmt(minutes):
    try: m = int(round(float(minutes)))
    except: m = 0
    return f"{m//60}s {m%60:02d}dk" if m >= 60 else f"{m}dk"

def _icao(raw):
    if not raw: return "ZZZZ"
    return str(raw).split("/")[0].strip().upper() or "ZZZZ"

_MFR = [
    ("Airbus",     ("A30","A31","A32","A33","A34","A35","A38","A19","A20","A21","A22")),
    ("Boeing",     ("B73","B74","B75","B76","B77","B78","B71","B72","B38","B39","737","747","757","767","777","787")),
    ("Embraer",    ("E17","E19","E75","E55","E50","ERJ","E13","E14","E29","E45")),
    ("Bombardier", ("CRJ","CR2","CR7","CR9","CL6","DH8","DHC","Q40")),
    ("ATR",        ("AT4","AT5","AT7","AT8")),
    ("Cessna",     ("C17","C20","C21","C25","C42","C50","C51","C52","C55","C56","C68","C72","C75","C82")),
    ("Cirrus",     ("SR2","SR22","S22T")),
    ("Diamond",    ("DA4","DA6","DA2","DA7","DV2")),
    ("Piper",      ("P28","PA2","PA3","PA4","PA6")),
    ("McDonnell",  ("MD8","MD9","MD1","DC8","DC9")),
    ("Pilatus",    ("PC12","PC24","PC6","PC7")),
]
def _mfr(t):
    t = t.upper()
    for name, pfx in _MFR:
        if t.startswith(pfx): return name
    if t.startswith("A"): return "Airbus"
    if t.startswith("B"): return "Boeing"
    return "Diğer"

# Renk paleti
_INK    = "#0a0e1a"
_PANEL  = "#10141f"
_LINE   = "#1f2937"
_MUTED  = "#5b6b82"
_TEXT   = "#e8eef7"
_CYAN   = "#22d3ee"
_VIO    = "#8b5cf6"
_AMBER  = "#fbbf24"
_GREEN  = "#34d399"
_ROSE   = "#fb7185"
_PF     = dict(family="ui-monospace,'Cascadia Code',monospace", color=_TEXT, size=11)

def _bare(fig, h=200):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=0,r=0,t=6,b=0), height=h, font=_PF,
                      showlegend=False, coloraxis_showscale=False)
    fig.update_xaxes(gridcolor=_LINE, zeroline=False, title="")
    fig.update_yaxes(gridcolor=_LINE, zeroline=False, title="")
    return fig

def _kpi(label, val, sub, color):
    return f"""<div style="background:{_PANEL};border:1px solid {_LINE};border-radius:10px;
      padding:16px 18px;text-align:center;">
      <div style="font-size:10px;letter-spacing:1.5px;text-transform:uppercase;
                  color:{_MUTED};font-weight:700;">{label}</div>
      <div style="font-size:24px;font-weight:800;line-height:1.1;margin-top:6px;
                  color:{color};font-variant-numeric:tabular-nums;">{val}</div>
      <div style="font-size:11px;color:{_MUTED};margin-top:4px;">{sub}</div></div>"""

def _sec(title):
    st.markdown(f'<div style="font-size:13px;font-weight:700;color:{_TEXT};letter-spacing:.5px;'
                f'display:flex;align-items:center;gap:8px;margin:20px 0 10px;">'
                f'<span style="width:3px;height:16px;background:{_CYAN};display:inline-block;border-radius:2px;"></span>'
                f'{title}</div>', unsafe_allow_html=True)

# ─── Mevcut tab1,tab3,tab4,tab5 ──────────────────────────────────────────────
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
    st.subheader("🛸 Live Anomaly Radar")
    with st.expander("⚙️ Open VIP Watchlist Controller", expanded=False):
        st.markdown("#### Custom Surveillance Parameters")
        wl_c1, wl_c2 = st.columns(2)
        with wl_c1:
            st.session_state.vip_cids = st.text_input("Target Pilot CIDs (Comma Separated):", value=st.session_state.vip_cids, placeholder="e.g. 1863530, 1869429", key="input_vip_cids")
        with wl_c2:
            st.session_state.vip_callsigns = st.text_input("Target Tracking Callsigns (Comma Separated):", value=st.session_state.vip_callsigns, placeholder="e.g. THY123, PGT456", key="input_vip_callsigns")
        st.markdown("---")
    if anomalies:
        df_anomalies = pd.DataFrame(anomalies)
        st.dataframe(df_anomalies, use_container_width=True)
    else:
        st.success("Sky is clear. No telemetric anomalies or emergencies detected.")

with tab5:
    st.subheader("🚀 VatScore Strategic Development Roadmap")
    st.markdown("""
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

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — CID STATS (statsim.net)
# ══════════════════════════════════════════════════════════════════════════════
with tab6:
    from datetime import timedelta as _td

    st.markdown(f"""
    <style>
    .vs-chip{{display:inline-block;padding:5px 12px;border-radius:6px;font-size:12px;font-weight:700;letter-spacing:.5px;font-family:monospace;}}
    .vs-route{{display:flex;justify-content:space-between;align-items:center;
               padding:9px 14px;border-radius:7px;margin-bottom:6px;
               background:{_INK};border:1px solid {_LINE};}}
    .vs-route .ap{{font-size:14px;font-weight:700;letter-spacing:1px;}}
    </style>""", unsafe_allow_html=True)

    st.markdown(f'<div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:{_MUTED};font-weight:700;margin-bottom:2px;">VatScore · Dossier</div>', unsafe_allow_html=True)
    st.markdown(f'<h3 style="margin-top:0;color:{_TEXT};font-weight:800;">CID İstatistikleri</h3>', unsafe_allow_html=True)

    cid_input = st.text_input("VATSIM CID", placeholder="örn. 1481801",
                               max_chars=10, key="cid_stats_input", label_visibility="collapsed")

    if not (cid_input and cid_input.strip().isdigit()):
        st.info("Bir VATSIM CID gir — tüm uçuş ve ATC geçmişi çekilir.")
        st.stop()

    cid = cid_input.strip()

    with st.spinner("Tüm geçmiş çekiliyor (statsim.net)…"):
        flights_raw = statsim_flights(cid)
        atc_raw     = statsim_atc(cid)
        lp          = live_pilot_lookup(cid)

    # ── Profil: sadece live feed'den (VATSIM Core key'e gerek yok) ────────────
    lp_name   = ""
    lp_rating = 0
    lp_pilot_r= 0
    if lp:
        lp_name    = lp.get("name", "")
        lp_rating  = lp.get("rating", 0)
        lp_pilot_r = lp.get("pilot_rating", 0)

    atc_lbl   = ATC_RATINGS.get(int(lp_rating), f"R{lp_rating}") if lp else "—"
    pilot_lbl = decode_pilot_rating(lp_pilot_r) if lp else "—"

    # Online rozeti
    online_badge = ""
    if lp:
        cs = lp.get("callsign","")
        online_badge = f'<span class="vs-chip" style="background:#062e25;color:{_GREEN};border:1px solid #0c5;margin-left:10px;vertical-align:middle;">● CANLI · {cs}</span>'

    # Rating chip'leri sadece online ise göster (live feed'den geliyor)
    rating_chips = ""
    if lp:
        rating_chips = f"""
        <span class="vs-chip" style="background:#0c2a3a;color:{_CYAN};border:1px solid {_CYAN}40;">PILOT {pilot_lbl}</span>
        <span class="vs-chip" style="background:#1e1633;color:{_VIO};border:1px solid {_VIO}40;margin-left:8px;">ATC {atc_lbl}</span>"""

    display_name = lp_name or f"CID {cid}"

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{_PANEL} 0%,{_INK} 100%);
                border:1px solid {_LINE};border-left:4px solid {_CYAN};
                border-radius:10px;padding:22px 24px;margin-bottom:22px;
                font-family:ui-monospace,'Cascadia Code',monospace;">
      <div style="font-size:24px;font-weight:800;color:{_TEXT};margin-bottom:3px;">
        {display_name}{online_badge}
      </div>
      <div style="font-size:12px;color:{_MUTED};margin-bottom:{'14px' if lp else '0'};">
        CID {cid}{"  ·  Uçuş sayısı: "+str(len(flights_raw)) if flights_raw else ""}
      </div>
      {rating_chips}
    </div>
    """, unsafe_allow_html=True)

    if not flights_raw:
        err = st.session_state.get("_cid_flights_err","")
        if err:
            st.error(f"statsim.net'ten veri çekilemedi (hata: {err}). Secrets'taki STATSIM_API_KEY'i kontrol et.")
        else:
            st.info("Bu CID için uçuş kaydı bulunamadı.")
        st.stop()

    # ── DataFrame ──────────────────────────────────────────────────────────────
    df = pd.DataFrame(flights_raw)
    df["dep"]         = df.get("departure",   pd.Series(dtype=str)).fillna("????").str.upper()
    df["arr"]         = df.get("destination", pd.Series(dtype=str)).fillna("????").str.upper()
    df["ac"]          = df.get("aircraft",    pd.Series(dtype=str)).apply(_icao)
    df["mfr"]         = df["ac"].apply(_mfr)
    df["route"]       = df["dep"] + "→" + df["arr"]
    df["dep_dt"]      = df.get("departed",  pd.Series(dtype=str)).apply(_parse_dt)
    df["arr_dt"]      = df.get("arrived",   pd.Series(dtype=str)).apply(_parse_dt)
    df["logon_dt"]    = df.get("loggedOn",  pd.Series(dtype=str)).apply(_parse_dt)
    df["when"]        = df["dep_dt"].fillna(df["logon_dt"])
    dur               = (df["arr_dt"] - df["dep_dt"]).dt.total_seconds() / 60
    df["dur_min"]     = dur.where(dur > 0).fillna(0)
    total_flights     = len(df)

    # ── Zaman filtresi ─────────────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    tf = st.radio("", ["Tümü","Son 1 Ay","Son 6 Ay","Bu Yıl","Son 1 Yıl"],
                  horizontal=True, key="cid_tf", label_visibility="collapsed")
    cutoff = {"Son 1 Ay": now_utc-_td(days=30), "Son 6 Ay": now_utc-_td(days=182),
              "Bu Yıl": now_utc.replace(month=1,day=1,hour=0,minute=0,second=0,microsecond=0),
              "Son 1 Yıl": now_utc-_td(days=365)}.get(tf)
    dff = df[df["when"] >= cutoff].copy() if cutoff else df.copy()
    st.caption(f"**{len(dff)}** uçuş gösteriliyor · toplam **{total_flights}** kayıt")

    # ── KPI şeridi ─────────────────────────────────────────────────────────────
    uniq_ap = [a for a in pd.unique(dff[["dep","arr"]].values.ravel()) if a not in ("????","")]
    fl_dur  = dff[dff["dur_min"] > 0]["dur_min"]
    avg_dur = int(fl_dur.mean()) if len(fl_dur) else 0
    k1,k2,k3,k4,k5 = st.columns(5)
    with k1: st.markdown(_kpi("Uçuş", f"{len(dff)}", f"/{total_flights} tüm zaman", _CYAN), unsafe_allow_html=True)
    with k2: st.markdown(_kpi("Ort. Süre", _fmt(avg_dur), "süresi hesaplanan", _GREEN), unsafe_allow_html=True)
    with k3: st.markdown(_kpi("Havalimanı", f"{len(uniq_ap)}", "farklı meydan", _AMBER), unsafe_allow_html=True)
    with k4: st.markdown(_kpi("Uçak Tipi", f"{dff['ac'].nunique()}", "ICAO type", _ROSE), unsafe_allow_html=True)
    with k5: st.markdown(_kpi("ATC Oturum", f"{len(atc_raw)}", "tüm geçmiş", _VIO), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Panel 1: Aktivite grafiği + İlk/Son ────────────────────────────────────
    _sec("Aktivite")
    a1, a2 = st.columns([0.7, 0.3])
    with a1:
        dm = dff.dropna(subset=["when"]).copy()
        if len(dm):
            dm["month"] = dm["when"].dt.to_period("M").astype(str)
            mc = dm.groupby("month").size().reset_index(name="n")
            fig = px.area(mc, x="month", y="n", template="plotly_dark")
            fig.update_traces(line=dict(color=_CYAN, width=2), fill="tozeroy",
                              fillcolor=f"rgba(34,211,238,0.10)", mode="lines")
            _bare(fig, 210); fig.update_xaxes(tickangle=-45, tickfont=dict(size=9))
            st.plotly_chart(fig, use_container_width=True)
    with a2:
        first_f = df["when"].min(); last_f = df["when"].max()
        fmt = "%d.%m.%Y"
        st.markdown(f"""
<div style="background:{_PANEL};border:1px solid {_LINE};border-radius:8px;padding:16px;">
  <div style="font-size:10px;color:{_MUTED};text-transform:uppercase;font-weight:700;margin-bottom:4px;">İlk Uçuş</div>
  <div style="color:{_TEXT};font-family:monospace;font-size:14px;margin-bottom:12px;">{first_f.strftime(fmt) if pd.notna(first_f) else '—'}</div>
  <div style="font-size:10px;color:{_MUTED};text-transform:uppercase;font-weight:700;margin-bottom:4px;">Son Uçuş</div>
  <div style="color:{_CYAN};font-family:monospace;font-size:14px;margin-bottom:12px;">{last_f.strftime(fmt) if pd.notna(last_f) else '—'}</div>
  <div style="font-size:10px;color:{_MUTED};text-transform:uppercase;font-weight:700;margin-bottom:4px;">Ort. Uçuş Süresi</div>
  <div style="color:{_AMBER};font-family:monospace;font-size:18px;font-weight:800;">{_fmt(avg_dur)}</div>
</div>""", unsafe_allow_html=True)

    # ── Panel 2: Fleet ─────────────────────────────────────────────────────────
    _sec("Filo")
    f1, f2 = st.columns(2)
    with f1:
        mc2 = dff["mfr"].value_counts().head(7).reset_index(); mc2.columns=["mfr","n"]
        fig = px.pie(mc2, names="mfr", values="n", hole=0.55, template="plotly_dark",
                     color_discrete_sequence=[_CYAN,_VIO,_GREEN,_AMBER,_ROSE,"#60a5fa","#a78bfa"])
        fig.update_traces(textposition="outside", textinfo="label+percent",
                          textfont=dict(size=10,color=_TEXT),
                          marker=dict(line=dict(color=_INK,width=2)))
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=0,r=0,t=0,b=0),height=230,showlegend=False,font=_PF,
                          annotations=[dict(text=f"<b>{dff['mfr'].nunique()}</b><br>üretici",
                                            x=0.5,y=0.5,font=dict(size=13,color=_MUTED),showarrow=False)])
        st.plotly_chart(fig, use_container_width=True)
    with f2:
        ac2 = dff["ac"].value_counts().head(8).reset_index(); ac2.columns=["ac","n"]
        fig = px.bar(ac2, x="n", y="ac", orientation="h", template="plotly_dark",
                     color="n", color_continuous_scale=[[0,"#0c2a3a"],[1,_CYAN]])
        fig.update_traces(marker_line_width=0, opacity=0.95,
                          text=ac2["n"], textposition="outside", textfont=dict(color=_MUTED,size=10))
        _bare(fig, 230); fig.update_yaxes(autorange="reversed", tickfont=dict(size=11))
        st.plotly_chart(fig, use_container_width=True)

    # ── Panel 3: En uzun uçuşlar ───────────────────────────────────────────────
    _sec("En Uzun Uçuşlar")
    s1, s2 = st.columns([0.35, 0.65])
    with s1: min_h = st.slider("Min. süre (saat)", 0, 14, 0, key="cid_min_h")
    with s2: top_n = st.slider("Adet", 5, 30, 12, key="cid_top_n")

    dl = dff[(dff["dur_min"] >= min_h*60) & (dff["dur_min"]>0)].sort_values("dur_min",ascending=False).head(top_n).copy()
    if len(dl):
        dl["lbl"] = dl["route"] + "  " + dl["ac"]
        dl["hm"]  = dl["dur_min"].apply(_fmt)
        fig = px.bar(dl, x="dur_min", y="lbl", orientation="h", template="plotly_dark",
                     color="dur_min", color_continuous_scale=[[0,"#0c2e26"],[1,_GREEN]], custom_data=["hm"])
        fig.update_traces(marker_line_width=0, opacity=0.95,
                          hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>",
                          text=dl["hm"], textposition="outside", textfont=dict(color=_MUTED,size=10))
        _bare(fig, max(260,len(dl)*30)); fig.update_yaxes(autorange="reversed",tickfont=dict(size=11))
        fig.update_xaxes(title="dakika")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Bu filtreyle süre verisi olan uçuş yok. (statsim bazı uçuşlarda departed/arrived vermez)")

    # ── Panel 4: Rotalar ───────────────────────────────────────────────────────
    _sec("Rotalar")
    r1, r2 = st.columns(2)
    rc = Counter(dff[dff["route"]!="????→????"]["route"].tolist())

    with r1:
        st.markdown(f'<div style="font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:{_MUTED};font-weight:700;margin-bottom:8px;">En Çok Uçulan</div>', unsafe_allow_html=True)
        mx = rc.most_common(1)[0][1] if rc else 1
        html = ""
        for route, cnt in rc.most_common(7):
            d2, a2 = route.split("→")
            w = int(cnt/mx*100)
            html += f"""<div class="vs-route">
              <span class="ap"><span style="color:{_CYAN}">{d2}</span><span style="color:{_MUTED};margin:0 6px;">→</span><span style="color:{_CYAN}">{a2}</span></span>
              <span style="display:flex;align-items:center;gap:8px;">
                <span style="width:50px;height:4px;background:{_LINE};border-radius:2px;overflow:hidden;display:inline-block;">
                  <span style="display:block;height:4px;width:{w}%;background:{_CYAN};"></span></span>
                <span class="vs-chip" style="background:#0c2a3a;color:{_CYAN};padding:2px 8px;">{cnt}×</span>
              </span></div>"""
        st.markdown(html or f"<div style='color:{_MUTED}'>Veri yok</div>", unsafe_allow_html=True)

    with r2:
        st.markdown(f'<div style="font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:{_MUTED};font-weight:700;margin-bottom:8px;">En İlginç (Nadir & Uzun)</div>', unsafe_allow_html=True)
        dr = dff[dff["route"]!="????→????"].copy()
        dr["freq"] = dr["route"].map(rc)
        dr = dr[dr["dur_min"]>30].sort_values(["freq","dur_min"],ascending=[True,False]).head(6)
        if len(dr):
            rh = ""
            for _, row in dr.iterrows():
                d2,a2 = row["route"].split("→")
                rh += f"""<div class="vs-route" style="border-left:2px solid {_AMBER};">
                  <span class="ap"><span style="color:{_AMBER}">{d2}</span><span style="color:{_MUTED};margin:0 6px;">→</span><span style="color:{_AMBER}">{a2}</span></span>
                  <span style="font-size:11px;color:{_MUTED};font-family:monospace;">{row['ac']} · {_fmt(row['dur_min'])}</span></div>"""
            st.markdown(rh, unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='color:{_MUTED};font-size:12px;'>Süre verisi yeterli değil</div>", unsafe_allow_html=True)

        if len(dff):
            top_ac  = dff["ac"].value_counts().idxmax()
            top_mfr = dff["mfr"].value_counts().idxmax()
            top_cnt = int(dff["ac"].value_counts().max())
            st.markdown(f"""<div style="background:{_PANEL};border:1px solid {_LINE};border-radius:8px;
              padding:14px;margin-top:10px;display:flex;justify-content:space-between;align-items:center;">
              <div><div style="font-size:10px;color:{_MUTED};text-transform:uppercase;font-weight:700;">Favori Uçak</div>
              <div style="font-size:20px;font-weight:800;color:{_GREEN};font-family:monospace;">{top_ac}
              <span style="font-size:12px;color:{_MUTED};font-weight:400;">· {top_mfr}</span></div></div>
              <span class="vs-chip" style="background:#0c2e26;color:{_GREEN};">{top_cnt} uçuş</span>
            </div>""", unsafe_allow_html=True)

    # ── Panel 5: ATC ───────────────────────────────────────────────────────────
    if atc_raw:
        _sec("ATC Sektör Mastery")
        da = pd.DataFrame(atc_raw)
        da["on"]  = da.get("loggedOn",  pd.Series(dtype=str)).apply(_parse_dt)
        da["off"] = da.get("loggedOff", pd.Series(dtype=str)).apply(_parse_dt)
        da["dur_min"] = ((da["off"]-da["on"]).dt.total_seconds()/60).clip(lower=0).fillna(0)
        da["cs"] = da.get("callsign", pd.Series(dtype=str)).fillna("???").str.upper()

        atc_tf = st.radio("", ["Tümü","Bu Yıl","Son 6 Ay"], horizontal=True,
                          key="cid_atc_tf", label_visibility="collapsed")
        if atc_tf == "Bu Yıl":
            da = da[da["on"] >= now_utc.replace(month=1,day=1,hour=0,minute=0,second=0,microsecond=0)]
        elif atc_tf == "Son 6 Ay":
            da = da[da["on"] >= now_utc - _td(days=182)]

        total_atc_min = da["dur_min"].sum()
        g1,g2,g3 = st.columns(3)
        with g1: st.markdown(_kpi("Oturum", f"{len(da)}", "kayıt", _VIO), unsafe_allow_html=True)
        with g2: st.markdown(_kpi("Toplam Süre", _fmt(total_atc_min), "kontrol süresi", _VIO), unsafe_allow_html=True)
        with g3: st.markdown(_kpi("Pozisyon", f"{da['cs'].nunique()}", "farklı sektör", _VIO), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            pos = da.groupby("cs")["dur_min"].sum().sort_values(ascending=False).head(12).reset_index()
            pos["hm"] = pos["dur_min"].apply(_fmt)
            fig = px.bar(pos, x="dur_min", y="cs", orientation="h", template="plotly_dark",
                         color="dur_min", color_continuous_scale=[[0,"#1e1633"],[1,_VIO]], custom_data=["hm"])
            fig.update_traces(marker_line_width=0, opacity=0.95,
                              hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>")
            _bare(fig, 360); fig.update_yaxes(autorange="reversed",tickfont=dict(size=11))
            fig.update_xaxes(title="dakika")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            def _stype(cs):
                cs = str(cs).upper()
                for s,n in (("_CTR","CTR"),("_APP","APP"),("_DEP","APP"),("_TWR","TWR"),("_GND","GND"),("_DEL","DEL"),("_FSS","FSS")):
                    if s in cs: return n
                return "Diğer"
            da["tip"] = da["cs"].apply(_stype)
            tc = da.groupby("tip")["dur_min"].sum().reset_index(); tc.columns=["tip","dur"]
            fig = px.pie(tc, names="tip", values="dur", hole=0.55, template="plotly_dark",
                         color_discrete_sequence=[_VIO,_CYAN,_GREEN,_AMBER,_ROSE,"#60a5fa"])
            fig.update_traces(textposition="outside", textinfo="label+percent",
                              textfont=dict(size=11,color=_TEXT),
                              marker=dict(line=dict(color=_INK,width=2)))
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                              margin=dict(l=0,r=0,t=0,b=0),height=360,showlegend=False,font=_PF,
                              annotations=[dict(text="sektör<br>tipi",x=0.5,y=0.5,
                                                font=dict(size=12,color=_MUTED),showarrow=False)])
            st.plotly_chart(fig, use_container_width=True)

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