import streamlit as st
import requests
import pandas as pd
from collections import Counter
from datetime import datetime
import os
import json
import re
from shapely.geometry import shape, Point

# API URLs
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_FIR_GEO_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/Boundaries.geojson"
VATSIM_RADAR_AIRLINES_URL = "https://data.vFtsim-radar.com/airlines"
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
    div[data-testid=\"stDecoration\"] {display: none;}
    [data-testid=\"sidebarNav\"] {display: none !important;}
    div[data-testid=\"stSidebar\"] {display: none !important;}
    .main { background-color: #0f111a; }
    h1 { color: #3b82f6; font-family: 'Segoe UI', sans-serif; font-weight: 800; font-style: italic; letter-spacing: -1px; margin-bottom: 2px; }
    .stTabs [data-baseweb="tab-list"] { background-color: #11131f; border-radius: 8px; padding: 6px; border: 1px solid #1e293b; gap: 8px; }
    .stTabs [data-baseweb="tab"] { color: #94a3b8; font-weight: 600; font-family: 'Segoe UI', sans-serif; padding: 10px 20px; border-radius: 6px; border: none; background-color: transparent; transition: all 0.2s ease; }
    .stTabs [data-baseweb="tab"]:hover { color: #3b82f6; background-color: #1e293b50; }
    .stTabs [aria-selected="true"] { color: #3b82f6 !important; background-color: #1e293b !important; border-bottom: none !important; box-shadow: 0 4px 12px rgba(59,130,246,0.15); }
    .metric-card { background-color: #11131f; border: 1px solid #1e293b; padding: 18px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
    .metric-label { color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
    .metric-value { color: #f8fafc; font-size: 26px; font-weight: 800; font-family: monospace; margin-top: 4px; }
    .roadmap-card { background-color: #11131f; border: 1px solid #1e293b; padding: 20px; border-radius: 10px; margin-bottom: 16px; box-shadow: 0 4px 10px rgba(0,0,0,0.2); position: relative; overflow: hidden; }
    .roadmap-card.in-progress { border-left: 4px solid #f59e0b; }
    .roadmap-badge { position: absolute; top: 20px; right: 20px; padding: 4px 12px; border-radius: 30px; font-size: 11px; font-weight: 700; text-transform: uppercase; color: #fff; }
    .roadmap-title { font-size: 18px; font-weight: 700; color: #f8fafc; font-family: 'Segoe UI', sans-serif; margin-bottom: 8px; max-width: 80%; }
    .roadmap-desc { font-size: 14px; color: #94a3b8; line-height: 1.6; }
    .signature-container { text-align: center; margin-top: 40px; padding: 20px; background-color: #11131f; border-top: 1px solid #1e293b; border-radius: 8px; font-family: monospace; font-size: 12px; color: #64748b; line-height: 1.8; }
    .signature-link { color: #3b82f6; text-decoration: none; font-weight: bold; }
    .signature-link:hover { text-decoration: underline; }
    div[data-testid="stTextInput"] input { background-color: #11131f !important; color: #f8fafc !important; border: 1px solid #1e293b !important; border-radius: 6px !important; }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] { background-color: #11131f !important; border: 1px solid #1e293b !important; border-radius: 6px !important; }
    div[data-testid="stSelectbox"] div { color: #f8fafc !important; }
    </style>
""", unsafe_allow_html=True)

# Map dictionary to group FIR IDs under clean regional headings
ICAO_REGION_MAP = {
    "LT": "Turkey (LT)",
    "EG": "United Kingdom (EG)",
    "K": "United States (K)",
    "Z": "China (Z)",
    "ED": "Germany (ED)",
    "LF": "France (LF)",
    "LE": "Spain (LE)",
    "LI": "Italy (LI)",
    "OB": "Middle East (OB/OE/OM)",
    "OE": "Middle East (OB/OE/OM)",
    "OM": "Middle East (OB/OE/OM)"
}

@st.cache_data(ttl=300)
def get_grouped_fir_boundaries(geojson_url):
    # Fetch VatSpy GeoJSON boundaries and group them logically by ICAO prefix
    try:
        response = requests.get(geojson_url)
        if response.status_code != 200:
            return {}, []
        geo_data = response.json()
        features = geo_data.get("features", [])
        
        grouped_firs = {}
        for feature in features:
            properties = feature.get("properties", {})
            fir_id = properties.get("id", "").upper().strip()
            fir_name = properties.get("name", "").strip()
            
            if not fir_id:
                continue
                
            prefix_2 = fir_id[:2]
            prefix_1 = fir_id[:1]
            
            if prefix_2 in ICAO_REGION_MAP:
                region_label = ICAO_REGION_MAP[prefix_2]
            elif prefix_1 in ICAO_REGION_MAP:
                region_label = ICAO_REGION_MAP[prefix_1]
            else:
                region_label = f"Other Regions ({prefix_2 if len(fir_id) >= 2 else prefix_1})"
                
            if region_label not in grouped_firs:
                grouped_firs[region_label] = []
                
            grouped_firs[region_label].append({
                "id": fir_id,
                "name": fir_name,
                "feature": feature
            })
            
        sorted_regions = sorted(list(grouped_firs.keys()))
        return grouped_firs, sorted_regions
    except Exception:
        return {}, []

@st.cache_data(ttl=900)
def load_airports_database(file_path):
    # Ingest the local CSV coordinate database for airport definitions
    if not os.path.exists(file_path):
        return {}
    try:
        df = pd.read_csv(file_path)
        db = {}
        for _, row in df.iterrows():
            icao = str(row.get("ident", "")).strip().upper()
            if icao and len(icao) == 4:
                db[icao] = {
                    "latitude": float(row.get("latitude_deg", 0)),
                    "longitude": float(row.get("longitude_deg", 0)),
                    "name": str(row.get("name", "Unknown Airport"))
                }
        return db
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def load_airlines_telephony():
    # Query production endpoint for real-time ICAO prefix telemetry callsign matching
    try:
        res = requests.get(VATSIM_RADAR_AIRLINES_URL, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {
        "THY": {"name": "Turkish Airlines", "callsign": "Turkish"},
        "PGT": {"name": "Pegasus Airlines", "callsign": "Sunsplash"},
        "BAW": {"name": "British Airways", "callsign": "Speedbird"},
        "DLH": {"name": "Lufthansa", "callsign": "Lufthansa"}
    }

def fetch_vatsim_live_core():
    # Request latest live stream from standard VATSIM data servers
    try:
        r = requests.get(VATSIM_DATA_URL)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# Load structural databases
airports_db = load_airports_database(CSV_FILE_PATH)
airlines_db = load_airlines_telephony()
grouped_firs, sorted_regions = get_grouped_fir_boundaries(VATSIM_FIR_GEO_URL)

# Layout Setup
col_title, col_time = st.columns([3, 1])
with col_title:
    st.markdown("<h1>VatScore — Global High-Fidelity Radar Matrix</h1>", unsafe_allow_html=True)

with col_time:
    time_placeholder = st.empty()
    time_placeholder.markdown("""
        <div class='metric-card' style='padding:10px 14px; margin-top:5px; border-color:#3b82f640;'>
            <div class='metric-label' style='color:#3b82f6;'>System Clock UTC</div>
            <div class='metric-value' style='font-size:18px; color:#3b82f6;'>00:00:00 Z</div>
        </div>
    """, unsafe_allow_html=True)

# Dynamic filter interface components
col_f1, col_f2, col_f3, col_f4 = st.columns([1, 1, 1, 1])
with col_f1:
    selected_region = st.selectbox(
        "Regional Umbrella Focus",
        options=sorted_regions if sorted_regions else ["Turkey (LT)"],
        index=sorted_regions.index("Turkey (LT)") if sorted_regions and "Turkey (LT)" in sorted_regions else 0
    )
with col_f2:
    if sorted_regions and selected_region in grouped_firs:
        fir_list = grouped_firs[selected_region]
        fir_options = [f"{f['id']} — {f['name']}" for f in fir_list]
        selected_fir_str = st.selectbox("Specific Center FIR Boundary", options=fir_options)
        target_prefix = selected_fir_str.split(" — ")[0][:2]
    else:
        target_prefix = "LT"
        st.selectbox("Specific Center FIR Boundary", options=["LTAA — Ankara", "LTBB — Istanbul"])

with col_f3:
    rules_filter = st.selectbox("Flight Category Rules", ["All Rules", "IFR Only", "VFR Only"])
with col_f4:
    isolation_filter = st.text_input("Fleet Code Isolation (Comma Separated ICAO)", placeholder="e.g. THY, PGT, BAW")

# Load real-time network payload
data = fetch_vatsim_live_core()

# State Management for Client Selection
if "selected_callsign" not in st.session_state:
    st.session_state.selected_callsign = ""

# Component synchronization parsing
query_params = st.query_params
js_time_signal = ""
if "js_time" in query_params:
    js_time_signal = query_params["js_time"]

# Tab Construction
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Airspace Radar Grid", 
    "Live Analytics Matrix", 
    "Global Leaderboard", 
    "Traffic Event Logger", 
    "Project Roadmap"
])

# Operational metrics parsing logic
pilots_dataset = data.get("pilots", []) if data else []
total_pilots_network = len(pilots_dataset)
total_atc_network = len(data.get("controllers", [])) if data else 0

filtered_pilots_for_stats = []
for p in pilots_dataset:
    fplan = p.get("flight_plan", {})
    dep = str(fplan.get("departure", "")).strip().upper()
    arr = str(fplan.get("arrival", "")).strip().upper()
    
    # Simple cross-reference filtering logic for statistical matrices
    if dep.startswith(target_prefix) or arr.startswith(target_prefix):
        filtered_pilots_for_stats.append(p)
    elif p.get("latitude") and p.get("longitude"):
        if target_prefix == "LT" and (36.5 <= p["latitude"] <= 42.0) and (27.0 <= p["longitude"] <= 44.5):
            filtered_pilots_for_stats.append(p)

local_traffic_count = len(filtered_pilots_for_stats)

with tab1:
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Global Active Pilots</div><div class='metric-value'>{total_pilots_network}</div></div>", unsafe_allow_html=True)
    with col_m2:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Global Active ATC</div><div class='metric-value'>{total_atc_network}</div></div>", unsafe_allow_html=True)
    with col_m3:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Filtered Local Traffic</div><div class='metric-value' style='color:#3b82f6;'>{local_traffic_count}</div></div>", unsafe_allow_html=True)
    
    st.write("")
    
    # Process visual grid component execution
    if data:
        active_cols = ["Callsign", "Origin", "Destination", "Aircraft", "Category", "Altitude (FT)", "Speed (KT)", "Squawk"]
        
        # Inject structural template parameters down to native components
        headers_placeholder = "".join([f"<th>{col}</th>" for col in active_cols])
        
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
                            <h4 style="color:#3b82f6; margin:0; font-size:22px; font-family:sans-serif; letter-spacing:0.5px; font-style: italic; display: flex; align-items: center; gap: 8px;">
                                <span id="popCallsign">Target Profile: ---</span>
                                <span class="plane-glyph-fallback">&#9992;</span>
                            </h4>
                        </div>
                        <hr style="border-color:#1e293b; margin-bottom:14px;">
                        
                        <p class="v-label" style="margin-bottom: 6px;">Live Flight Trajectory & Distance Progress (Rules: <span id="popRulesText" style="color:#22c55e; font-weight:bold;">IFR</span>)</p>
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
                                <p class="v-label">Airframe</p><p id="popAirframe" class="v-val"></p>
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
            .progress-plane-icon { 
                position: absolute; 
                top: 50%; 
                left: 0%; 
                transform: translate(-50%, -50%) rotate(90deg); 
                font-size: 16px; 
                transition: left 0.4s ease; 
                line-height: 1; 
                color: #22c55e; 
                font-weight: bold;
                font-family: "Segoe UI Symbol", "Arial Unicode MS", "Apple Color Emoji", sans-serif !important;
            }

            .plane-glyph-fallback { font-family: "Segoe UI Symbol", "Arial Unicode MS", sans-serif !important; color: #3b82f6; font-size: 20px; display: inline-block; transform: rotate(90deg); line-height: 1; }

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
            const includeArrDepJs = true;

            function updateHaversineProgressMetrics(depIcao, arrIcao, currentLat, currentLon) {
                // High-precision mathematical distance routing implementation using spherical trigonometry
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
                // Categorize real-time airframes into operational classes
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
                // Isolate prefix patterns and resolve company metadata
                const callsignField = document.getElementById("airlineCallsignText");
                callsignField.innerText = "GENERAL AVIATION / PRIVATE";
                if (!callsign) return;
                
                try {
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
                } catch (err) {
                    callsignField.innerText = "IDENTITY CORRUPTED";
                }
            }

            function sendTimeToStreamlitBackend() {
                // Sync front-end heartbeat with backend systems
                const now = new Date();
                const hours = String(now.getUTCHours()).padStart(2, '0');
                const minutes = String(now.getUTCMinutes()).padStart(2, '0');
                const seconds = String(now.getUTCSeconds()).padStart(2, '0');
                const formattedTime = hours + ":" + minutes + ":" + seconds + " Z";
                Streamlit.setComponentValue(formattedTime);
            }

            function buildTable(pilotsList) {
                // Dynamically process DOM matrix rows without triggering full layout loops
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
                    
                    let isPhysHere = false;
                    if (targetPrefix === "LT" && p.latitude && p.longitude && (p.latitude >= 36.5 && p.latitude <= 42.0) && (p.longitude >= 27.0 && p.longitude <= 44.5)) {
                        isPhysHere = true;
                    } else if (targetPrefix === "ED" && p.latitude && p.longitude && (p.latitude >= 47.0 && p.latitude <= 55.0) && (p.longitude >= 5.0 && p.longitude <= 16.0)) {
                        isPhysHere = true;
                    } else if (targetPrefix === "EG" && p.latitude && p.longitude && (p.latitude >= 49.0 && p.latitude <= 61.0) && (p.longitude >= -11.0 && p.longitude <= 2.0)) {
                        isPhysHere = true;
                    } else if (p.latitude && p.longitude) {
                        isPhysHere = true;
                    }

                    if (isPhysHere || matchesPlan) {
                        const rowData = {
                            "Callsign": callsign, "Origin": dep || "NO FPL", "Destination": arr || "NO FPL",
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
                            voice: p.has_voice ? "Voice Active" : "Text Only",
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
                // Populate interface targets inside the modal window viewport
                try {
                    const p = globalDossiers[callsign];
                    if (!p) return;
                    currentlyOpenCallsign = callsign;

                    document.getElementById("popCallsign").innerText = "Target Profile: " + callsign;
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

                    const rulesTextField = document.getElementById("popRulesText");
                    rulesTextField.innerText = p.rules;
                    if (p.rules === "VFR") {
                        rulesTextField.style.color = "#f59e0b";
                    } else {
                        rulesTextField.style.color = "#22c55e";
                    }

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
                // Query server loop for fresh live positions
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

            const scriptStreamlit = document.createElement('script');
            scriptStreamlit.src = "https://cdn.jsdelivr.net/npm/@streamlit/component-lib@1.4.0/dist/index.min.js";
            document.head.appendChild(scriptStreamlit);

            const initialData = INITIAL_DATA_PLACEHOLDER;
            buildTable(initialData);

            if (autoOpenCallsign && autoOpenCallsign !== "") {
                setTimeout(() => { openDossier(autoOpenCallsign); }, 250);
            }

            setInterval(() => {
                // Monitor communication sync stamps from backend framework layers
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
        
        # Inject variable parameters into frontend structures safely
        rendered_html = raw_html_template\
            .replace("{HEADERS_PLACEHOLDER}", headers_placeholder)\
            .replace("TARGET_PREFIX_PLACEHOLDER", str(target_prefix))\
            .replace("ACTIVE_COLS_PLACEHOLDER", json.dumps(active_cols))\
            .replace("AUTO_OPEN_CALLSIGN_PLACEHOLDER", str(st.session_state.selected_callsign))\
            .replace("AIRPORTS_DB_PLACEHOLDER", json.dumps(airports_db))\
            .replace("AIRLINES_DB_PLACEHOLDER", json.dumps(airlines_db))\
            .replace("RULES_FILTER_PLACEHOLDER", str(rules_filter))\
            .replace("ISOLATION_FILTER_PLACEHOLDER", str(isolation_filter))\
            .replace("SIGNAL_STAMP_PLACEHOLDER", str(js_time_signal))
            
        # Parse physical local filtered structures to populate client layout grids
        final_ui_list = []
        for p in pilots_dataset:
            fplan = p.get("flight_plan", {})
            dep = str(fplan.get("departure", "")).strip().upper()
            arr = str(fplan.get("arrival", "")).strip().upper()
            
            passes_route = dep.startswith(target_prefix) or arr.startswith(target_prefix)
            passes_geo = False
            if p.get("latitude") and p.get("longitude"):
                if target_prefix == "LT" and (36.5 <= p["latitude"] <= 42.0) and (27.0 <= p["longitude"] <= 44.5):
                    passes_geo = True
            
            if passes_route or passes_geo:
                final_ui_list.append(p)
                
        rendered_html = rendered_html.replace("INITIAL_DATA_PLACEHOLDER", json.dumps(final_ui_list))
        
        # Deploy structural element matrix inside framework iframe bounds
        response_stamp = st.components.v1.html(rendered_html, height=620, scrolling=True)
        
        if response_stamp:
            st.query_params["js_time"] = str(response_stamp)
    else:
        st.error("No valid telemetry received from network endpoints.")

with tab2:
    st.subheader("Live Operational Matrix Logs")
    if filtered_pilots_for_stats:
        df_local = pd.DataFrame([{
            "Callsign": p.get("callsign"),
            "Altitude": p.get("altitude", 0),
            "Speed": p.get("groundspeed", 0),
            "Aircraft": p.get("flight_plan", {}).get("aircraft", "N/A")
        } for p in filtered_pilots_for_stats])
        
        col_an1, col_an2 = st.columns(2)
        with col_an1:
            st.markdown("<p class='v-label'>Altitude Distribution</p>", unsafe_allow_html=True)
            st.bar_chart(df_local["Altitude"])
        with col_an2:
            st.markdown("<p class='v-label'>Groundspeed Index</p>", unsafe_allow_html=True)
            st.line_chart(df_local["Speed"])
    else:
        st.info("Insufficient local data vectors to compile matrix layouts.")

with tab3:
    st.subheader("Global Network Connection Leaderboard")
    if data:
        leaderboard_data = sorted(pilots_dataset, key=lambda x: x.get("logon_time", ""), reverse=False)[:10]
        df_leader = pd.DataFrame([{
            "Position": idx + 1,
            "Callsign": p.get("callsign"),
            "Pilot Name": p.get("name"),
            "VATSIM CID": p.get("cid"),
            "Logon Stamp": p.get("logon_time")
        } for idx, p in enumerate(leaderboard_data)])
        st.dataframe(df_leader, use_container_width=True)

with tab4:
    st.subheader("Administrative Traffic Event Logging Chamber")
    log_file = "radar_traffic_logs.csv"
    if os.path.exists(log_file):
        df_logs = pd.read_csv(log_file)
        st.dataframe(df_logs.tail(30), use_container_width=True)
    else:
        st.info("No active log streams mapped on this station instance.")

with tab5:
    st.subheader("VatScore Strategic Development Roadmap")
    st.markdown("""
    <div class="roadmap-card">
        <div class="roadmap-badge" style="background-color: #22c55e;">Phase 1: Completed</div>
        <div class="roadmap-title">Custom HTML/JS Grid Engine & Flight Detail Insight System</div>
        <div class="roadmap-desc">
            <strong>Status:</strong> Completed — May 31, 2026<br>
            Implementation of a high-performance HTML/JS grid engine enabling real-time telemetry inspection. Users can access detailed flight plan strings, pilot profiles, and communication frequency metadata through an integrated native JavaScript modal.
        </div>
    </div>
    <div class="roadmap-card in-progress">
        <div class="roadmap-badge" style="background-color: #f59e0b;">Phase 2: In Progress — Codename: "babybus"</div>
        <div class="roadmap-title">Advanced Telemetry Tracking & Precision Filtering</div>
        <div class="roadmap-desc">
            <strong>Status:</strong> Active Development (June 2026)<br>
            Focusing on operational depth, data integrity, and Turkish FIR optimization. Key milestones include:
            <ul>
                <li><strong>Real-Time Haversine Engine:</strong> Successfully integrated precise distance calculations and a dynamic progress bar within the telemetry dossier.</li>
                <li><strong>Flight Rule Identification:</strong> Completed the deployment of the integrated IFR/VFR Rule Box for instant flight type classification.</li>
                <li><strong>Dynamic Telephony Engine & Isolation:</strong> Enriched with asynchronous API matcher and premium ICAO fleet code isolation filter.</li>
                <li><strong>Selected FIR Regional Umbrella Focus:</strong> Implemented hierarchical grouping for boundaries (LT, EG, K, Z, ED) to prevent front-end grid discrepancies.</li>
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