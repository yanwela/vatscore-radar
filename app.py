import streamlit as st
import requests
import pandas as pd
from collections import Counter
from datetime import datetime
import os
from user_agents import parse
import json

# API URLs
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_FIR_GEO_URL = "https://raw.githubusercontent.com/vatsimnetwork/vatsim-data-geo/main/data/fir-boundaries.json"

# Sayfa Yapılandırması
st.set_page_config(
    page_title="VatScore Web — Premium ScoreRadar", 
    page_icon="⚡", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- SESSION STATE INITIALIZATION ---
if "show_panel" not in st.session_state: 
    st.session_state.show_panel = False
if "visible_columns" not in st.session_state:
    st.session_state.visible_columns = ["Origin", "Destination", "Aircraft", "Category", "Altitude (FT)", "Speed (KT)", "Squawk"]
if "fleet_filter_selection" not in st.session_state: 
    st.session_state.fleet_filter_selection = "All Flights"

# CUSTOM CSS (Eski temiz, keskin koyu tema hatları)
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
    
    /* Roadmap Kart Tasarımları */
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
    
    /* Detay Kutusu Tasarımı */
    .telemetry-box {
        background-color: #151824;
        border: 1px solid #3b82f640;
        border-radius: 8px;
        padding: 20px;
        margin-top: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 🛰️ SESSİZ LOGLAMA VE ADMİN SİSTEMİ ---
LOG_FILE = "radar_traffic_logs.csv"
ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]

def init_log_file():
    if not os.path.exists(LOG_FILE):
        df = pd.DataFrame(columns=["Timestamp", "Session_ID", "OS", "Browser", "Device_Type", "Last_Action"])
        df.to_csv(LOG_FILE, index=False)

init_log_file()

def log_activity(action):
    try:
        ua_string = st.context.headers.get("User-Agent", "")
        user_agent = parse(ua_string)
        os_name = f"{user_agent.os.family} {user_agent.os.version_string}"
        browser_name = f"{user_agent.browser.family} {user_agent.browser.version_string}"
        
        if user_agent.is_mobile: device_type = "📱 Mobile"
        elif user_agent.is_tablet: device_type = "平板 Tablet"
        elif user_agent.is_pc: device_type = "💻 PC / Laptop"
        else: device_type = "🤖 Bot/Unknown"
        
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
                "OS": os_name, "Browser": browser_name, "Device_Type": device_type, "Last_Action": action
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

# Canlı Uçuş Verisi Çekici
@st.cache_data(ttl=15)
def fetch_vatsim_data():
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200: return r.json()
    except: pass
    return None

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

data = fetch_vatsim_data()
global_fir_map = load_global_fir_dictionary()

if data:
    pilots = data.get("pilots", [])
    controllers = data.get("controllers", [])

    # Başlık Alanı
    title_col, refresh_col, emoji_col = st.columns([0.88, 0.06, 0.06])
    with title_col: st.title("⚡ VATSCORE // Premium Global Radar")
    
    with refresh_col:
        st.write("<div style='padding-top:25px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="top-emoji-btn">', unsafe_allow_html=True)
        refresh_clicked = st.button("🔄", help="Force Manual Refresh Now")
        st.markdown('</div>', unsafe_allow_html=True)
        if refresh_clicked:
            fetch_vatsim_data.clear()
            load_global_fir_dictionary.clear()
            st.rerun()
    
    with emoji_col:
        st.write("<div style='padding-top:25px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="top-emoji-btn">', unsafe_allow_html=True)
        settings_clicked = st.button("⚙️", help="Click to toggle Column visibility and Fleet filters")
        st.markdown('</div>', unsafe_allow_html=True)

    if settings_clicked: 
        st.session_state.show_panel = not st.session_state.show_panel

    all_columns = ["Origin", "Destination", "Aircraft", "Category", "Altitude (FT)", "Speed (KT)", "Squawk"]

    if st.session_state.show_panel:
        with st.container():
            st.markdown("### ⚙️ Live Radar Customizer")
            cfg_col1, cfg_col2 = st.columns(2)
            with cfg_col1:
                st.session_state.visible_columns = st.multiselect("Select Table Columns:", options=all_columns, default=st.session_state.visible_columns)
            with cfg_col2:
                st.session_state.fleet_filter_selection = st.radio("Fleet Category Filter:", ["All Flights", "Commercial Only", "General Aviation Only", "Business Jet Only", "Military Only"], horizontal=True)
            st.markdown("---")

    # Üst İstatistik Kartları
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1: st.metric(label="Total Live Pilots Worldwide", value=len(pilots))
    with col_stat2: st.metric(label="Total Active ATCs", value=len(controllers))
    with col_stat3: st.metric(label="Last Network Sync", value=datetime.now().strftime('%H:%M:%S UTC'))

    # İlk Veri İşleme
    fir_pilots = []
    dep_airports, arr_airports, aircraft_types = [], [], []
    anomalies = []
    highest_p, fastest_p, slowest_p, veteran_p = None, None, None, None
    max_alt, max_gs, min_gs = -1, -1, 9999
    min_logon = "9999-12-31"

    fir_options = [f"{code} - {name}" for code, name in sorted(global_fir_map.items())]
    default_index = [i for i, s in enumerate(fir_options) if s.startswith("LT")][0] if any(s.startswith("LT") for s in fir_options) else 0
    
    if "main_fir_selectbox" not in st.session_state: selected_fir_prefix = "LT"
    else: selected_fir_prefix = st.session_state["main_fir_selectbox"].split(" - ")[0]

    current_fleet_filter = st.session_state.fleet_filter_selection
    pilot_dossiers = {}

    for p in pilots:
        callsign = p.get("callsign", "N/A")
        alt = p.get("altitude", 0)
        gs = p.get("groundspeed", 0)
        lat = p.get("latitude", 0.0)
        lon = p.get("longitude", 0.0)
        logon = p.get("logon_time", "")
        fplan = p.get("flight_plan") or {}
        dep = fplan.get("departure", "")
        arr = fplan.get("arrival", "")
        route = fplan.get("route", "No Flight Plan Filed.")
        ac_type = fplan.get("aircraft", "").split("/")[0] or "N/A"

        if dep: dep_airports.append(dep)
        if arr: arr_airports.append(arr)
        if ac_type and ac_type != "N/A": aircraft_types.append(ac_type)

        category = classify_aircraft(ac_type, callsign)
        if current_fleet_filter == "Commercial Only" and category != "✈️ Commercial": continue
        if current_fleet_filter == "General Aviation Only" and category != "🛩️ General Aviation": continue
        if current_fleet_filter == "Business Jet Only" and category != "💼 Business Jet": continue
        if current_fleet_filter == "Military Only" and category != "⚔️ Military": continue

        matches_flight_plan = dep.startswith(selected_fir_prefix) or arr.startswith(selected_fir_prefix)
        is_physically_here = False
        if selected_fir_prefix == "LT" and (36.5 <= lat <= 42.0) and (27.0 <= lon <= 44.5): is_physically_here = True

        if matches_flight_plan or is_physically_here:
            display_dep = dep if dep else "⚠️ NO FPL"
            display_arr = arr if arr else "⚠️ NO FPL"
            
            fir_pilots.append({
                "Callsign": callsign, "Origin": display_dep, "Destination": display_arr,
                "Aircraft": ac_type if fplan.get("aircraft") else "Unknown",
                "Category": category, "Altitude (FT)": alt, "Speed (KT)": gs, "Squawk": p.get("transponder", "0000")
            })

            online_mins = "Unknown"
            if logon:
                try:
                    logon_dt = datetime.strptime(logon[:19], "%Y-%m-%dT%H:%M:%S")
                    online_mins = f"{int((datetime.now() - logon_dt).seconds / 60)} Mins"
                except: pass
            
            rating_text = {0:"OBS", 1:"P1", 2:"P2", 3:"P3", 4:"P4", 5:"P5"}.get(p.get("pilot_rating", 0), "P1 (Licensed)")
            v5_voice = "🎙️ Voice Active" if p.get("has_voice", True) else "⌨️ Text Only"

            pilot_dossiers[callsign] = {
                "name": p.get("name", "Anonymous"), "cid": p.get("cid", "N/A"), "rating": rating_text,
                "online": online_mins, "voice": v5_voice, "squawk": p.get("transponder", "0000"),
                "origin": display_dep, "destination": display_arr, "airframe": ac_type, "route": route
            }

        if alt > max_alt: max_alt = alt; highest_p = p
        if gs > max_gs: max_gs = gs; fastest_p = p
        if alt > 3000 and 45 < gs < min_gs: min_gs = gs; slowest_p = p
        if logon and logon < min_logon: min_logon = logon; veteran_p = p

        if str(p.get("transponder")) == "7700": anomalies.append({"Type": "🚨 EMERGENCY (7700)", "Callsign": callsign, "Details": "Declared Mayday", "Airframe": ac_type})
        if gs > 1150: anomalies.append({"Type": "⚡ Warp Speed Glitch", "Callsign": callsign, "Details": f"Speed: {gs} KT", "Airframe": ac_type})
        if category == "⚔️ Military": anomalies.append({"Type": "⚔️ Tactical Sortie", "Callsign": callsign, "Details": "Military deployment", "Airframe": ac_type})

    # Sekmeler
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏆 Leaderboard", "✈️ Selected FIR Focus", "🌐 Global Stats & ATC", "🛸 Anomaly Radar", "🚀 Project Roadmap"])

    with tab1:
        st.subheader("Current Flight Records")
        leader_data = []
        if highest_p: leader_data.append({"Record Category": "Highest Cruising Altitude", "Callsign": highest_p['callsign'], "Value": f"{highest_p['altitude']:,} FT", "Pilot": highest_p.get('name')})
        if fastest_p: leader_data.append({"Record Category": "Maximum Velocity (GS)", "Callsign": fastest_p['callsign'], "Value": f"{fastest_p['groundspeed']} KT", "Pilot": fastest_p.get('name')})
        if slowest_p: leader_data.append({"Record Category": "Slowest Airborne Profile", "Callsign": slowest_p['callsign'], "Value": f"{slowest_p['groundspeed']} KT", "Pilot": slowest_p.get('name')})
        if veteran_p: leader_data.append({"Record Category": "Longest Session (Veteran)", "Callsign": veteran_p['callsign'], "Value": f"Since {veteran_p.get('logon_time','')[11:16]} UTC", "Pilot": veteran_p.get('name')})
        st.table(leader_data)

    with tab2:
        st.subheader("✈️ Regional Airspace Monitor")
        selected_option = st.selectbox("Choose Region/FIR Focus:", options=fir_options, index=default_index, key="main_fir_selectbox")
        
        # Grafik Alanı
        chart_expander = st.expander("📊 Open Interactive Analytics Charts (Altitude & Speed Profiles)", expanded=False)
        
        if fir_pilots:
            df_fir = pd.DataFrame(fir_pilots)
            with chart_expander:
                c_col1, c_col2 = st.columns(2)
                with c_col1:
                    st.markdown("##### 📈 FIR Altitude Profiles (FT)")
                    df_alt_chart = df_fir[['Callsign', 'Altitude (FT)']].copy().set_index('Callsign')
                    st.bar_chart(df_alt_chart, y='Altitude (FT)', color='#3b82f6')
                with c_col2:
                    st.markdown("##### ⚡ FIR Groundspeed Profiles (KT)")
                    df_spd_chart = df_fir[['Callsign', 'Speed (KT)']].copy().set_index('Callsign')
                    st.bar_chart(df_spd_chart, y='Speed (KT)', color='#22c55e')

            # Tablo Sütun Filtrelemesi
            active_cols = ["Callsign"] + [c for c in st.session_state.visible_columns if c in df_fir.columns]
            
            st.info(f"Showing {len(df_fir)} active aircraft tracks inside {selected_option}. Select a row from the list below to decode full telemetry dossier.")
            
            # --- YEREL VE GÜVENLİ VERİ TABLOSU (Eski Temiz Yapı) ---
            df_display_table = df_fir[active_cols].copy()
            
            # Streamlit'in yerel etkileşimli tablosunu kullanıyoruz (Zero-Flicker & No Double Scrollbar)
            selected_rows = st.dataframe(
                df_display_table, 
                use_container_width=True, 
                hide_index=True,
                on_select="rerun",
                selection_mode="single"
            )
            
            # Eğer tablodan bir satıra tıklanırsa detayları alt panelde aç
            if selected_rows and selected_rows.get("selection", {}).get("rows"):
                selected_index = selected_rows["selection"]["rows"][0]
                selected_callsign = df_display_table.iloc[selected_index]["Callsign"]
                
                p_dossier = pilot_dossiers.get(selected_callsign)
                if p_dossier:
                    st.markdown(f"""
                    <div class="telemetry-box">
                        <h3 style="color:#3b82f6; margin-top:0; margin-bottom:15px;">🛰️ Telemetry Dossier Decoder — Target Profile: {selected_callsign}</h3>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    det_c1, det_c2, det_c3 = st.columns(3)
                    with det_c1:
                        st.text_input("👤 PILOT NAME", value=p_dossier["name"], disabled=True)
                        st.text_input("🆔 VATSIM CID", value=p_dossier["cid"], disabled=True)
                        st.text_input("🎖️ RATING", value=p_dossier["rating"], disabled=True)
                    with det_c2:
                        st.text_input("🟢 ONLINE TIME", value=p_dossier["online"], disabled=True)
                        st.text_input("📻 VHF COMMS & FREQUENCY", value=p_dossier["voice"], disabled=True)
                        st.text_input("📡 SQUAWK CODE", value=p_dossier["squawk"], disabled=True)
                    with det_c3:
                        st.text_input("🛫 ORIGIN", value=p_dossier["origin"], disabled=True)
                        st.text_input("🛬 DESTINATION", value=p_dossier["destination"], disabled=True)
                        st.text_input("✈️ AIRFRAME", value=p_dossier["airframe"], disabled=True)
                        
                    st.text_area("🗺️ FILED ROUTE STRING", value=p_dossier["route"], height=80, disabled=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            csv = df_fir.to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Download This FIR Data as CSV", data=csv, file_name=f"vatsim_fir_{selected_fir_prefix}_data.csv", mime="text/csv")
        else:
            st.warning("No active flights found for this region prefix right now.")

    with tab3:
        st.subheader("Global Network Insights")
        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            st.markdown("### 📍 Busiest Hubs")
            st.write("**Top Departures:**")
            for k, v in Counter(dep_airports).most_common(4): st.write(f"• `{k}`: {v} flights")
        with col_g2:
            st.markdown("### ✈️ Fleet Distribution")
            for k, v in Counter(aircraft_types).most_common(7): st.write(f"• **{k}** : {v} aircraft")
        with col_g3:
            st.markdown("### 🎙️ Busiest Airspaces (ATC)")
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
            <div class="roadmap-badge" style="background-color: #22c55e;">Phase 1: Completed — May 31, 2026</div>
            <div class="roadmap-title">✈️ Custom HTML/JS Grid Engine & Flight Detail Insight System</div>
            <div class="roadmap-desc">Successfully implemented interactive row-click actions on data tables to expand and view the full flight plan string (ROUTE), pilot real name, and voice VHF frequency metadata natively without leaving the view. This was achieved by migrating to a premium HTML/JS grid engine and engineering a native JavaScript telemetry modal that locks perfectly to the center of the screen upon click. Fixed dashboard viewports by engineering background asychronous fetch routines for a zero-flicker experience.</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <div class="roadmap-card in-progress">
            <div class="roadmap-badge" style="background-color: #f59e0b;">Phase 2: In Progress</div>
            <div class="roadmap-title">🌐 Advanced Filtering & Ecosystem Scaling</div>
            <div class="roadmap-desc">
                This phase focuses on deep telemetry sorting and production deployment adjustments:
                <ul style="margin-top: 5px; padding-left: 20px; color: #94a3b8;">
                    <li><b>VFR / IFR Flight Rules Separation:</b> Ability to isolate cross-country visual flights from heavy airline operations.</li>
                    <li><b>Airline-Specific Fleet Filtering:</b> Instant focus tags for major operators like THY (Turkish Airlines), PGT (Pegasus), etc.</li>
                    <li><b>User Favorites System:</b> Mark and track specific airframes or pilot CIDs across sessions.</li>
                    <li><b>Custom Domain Deployment:</b> Migrating infrastructure under a dedicated brand domain name.</li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # --- BRANDING SIGNATURE ---
    st.markdown("""
        <div class="signature-container">
            ⚡ VatScore Dashboard // Made by alp-1863530 <br>
            📬 For any questions or requests, contact: <a class="signature-link" href="mailto:alpqwesy1@gmail.com">alpqwesy1@gmail.com</a>
        </div>
    """, unsafe_allow_html=True)
else:
    st.error("Could not fetch data from VATSIM API. Please reload page.")