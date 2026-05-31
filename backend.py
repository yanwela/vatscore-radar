from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import pandas as pd
from datetime import datetime
from user_agents import parse
from collections import Counter

app = FastAPI()

# Frontend'in (index.html) sorunsuz bağlanabilmesi için CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
LOG_FILE = "radar_traffic_logs.csv"

# NOT: Eski st.secrets["ADMIN_PASSWORD"] yerine şifreni buraya gömüyoruz:
ADMIN_PASSWORD = "SÜPER_GİZLİ_ŞİFRENİ_BURAYA_YAZ" 

def init_log_file():
    if not os.path.exists(LOG_FILE):
        df = pd.DataFrame(columns=["Timestamp", "Session_ID", "OS", "Browser", "Device_Type", "Last_Action"])
        df.to_csv(LOG_FILE, index=False)

init_log_file()

def log_activity(user_agent_string: str, action: str, session_id: str = "unknown"):
    try:
        user_agent = parse(user_agent_string)
        os_name = f"{user_agent.os.family} {user_agent.os.version_string}"
        browser_name = f"{user_agent.browser.family} {user_agent.browser.version_string}"
        
        if user_agent.is_mobile: device_type = "📱 Mobile"
        elif user_agent.is_tablet: device_type = "平板 Tablet"
        elif user_agent.is_pc: device_type = "💻 PC / Laptop"
        else: device_type = "🤖 Bot/Unknown"
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        df = pd.read_csv(LOG_FILE)
        
        # Eğer mevcut session varsa güncelle, yoksa yeni satır ekle
        if session_id != "unknown" and session_id in df['Session_ID'].astype(str).values:
            df.loc[df['Session_ID'].astype(str) == session_id, 'Timestamp'] = timestamp
            df.loc[df['Session_ID'].astype(str) == session_id, 'Last_Action'] = action
        else:
            new_row = pd.DataFrame([{
                "Timestamp": timestamp, "Session_ID": session_id,
                "OS": os_name, "Browser": browser_name, "Device_Type": device_type, "Last_Action": action
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            
        df.to_csv(LOG_FILE, index=False)
    except:
        pass

# --- 🛰️ ANA VERİ ENDPOINT'İ ---
@app.get("/api/vatsim")
def get_vatsim_data(user_agent: str = Header(None), sid: str = "unknown"):
    if user_agent:
        log_activity(user_agent, "Radar Data Requested", sid)
        
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            vatsim_json = r.json()
            
            # Gelişmiş İstatistikleri (Busiest Hubs vb.) backend'de hesaplayıp JS'e hazır paslıyoruz
            pilots = vatsim_json.get("pilots", [])
            dep_airports = [p.get("flight_plan", {}).get("departure", "") for p in pilots if p.get("flight_plan")]
            arr_airports = [p.get("flight_plan", {}).get("arrival", "") for p in pilots if p.get("flight_plan")]
            ac_types = [p.get("flight_plan", {}).get("aircraft", "").split("/")[0] for p in pilots if p.get("flight_plan")]
            
            # Boş verileri temizle
            dep_airports = [d for d in dep_airports if d]
            arr_airports = [a for a in arr_airports if a]
            ac_types = [t for t in ac_types if t and t != "N/A"]
            
            # Ekstra analitik düğümünü (node) json'a enjekte ediyoruz
            vatsim_json["analytics"] = {
                "top_deps": Counter(dep_airports).most_common(5),
                "top_arrs": Counter(arr_airports).most_common(5),
                "top_aircraft": Counter(ac_types).most_common(7)
            }
            return vatsim_json
    except Exception as e:
        print(f"Error fetching VATSIM data: {e}")
    
    return {"pilots": [], "controllers": [], "analytics": {"top_deps": [], "top_arrs": [], "top_aircraft": []}}

# --- 🛡️ ADMIN PANEL ENDPOINT'LERİ ---

@app.get("/api/admin/logs")
def get_admin_logs(password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Invalid Master Admin Password Token.")
    
    if not os.path.exists(LOG_FILE):
        return {"active_now": 0, "total_unique": 0, "dominant_hardware": "N/A", "logs": []}
        
    df_logs = pd.read_csv(LOG_FILE)
    if df_logs.empty:
         return {"active_now": 0, "total_unique": 0, "dominant_hardware": "N/A", "logs": []}
         
    df_logs['Timestamp'] = pd.to_datetime(df_logs['Timestamp'])
    time_delta = (datetime.now() - df_logs['Timestamp']).dt.total_seconds()
    
    active_now = int(len(df_logs[time_delta < 300]['Session_ID'].unique()))
    total_unique = int(len(df_logs['Session_ID'].unique()))
    dominant_hardware = str(df_logs['Device_Type'].mode()[0]) if not df_logs.empty else "N/A"
    
    # En son yapılan hareket üste gelsin
    df_display = df_logs.sort_values(by="Timestamp", ascending=False).copy()
    df_display['Timestamp'] = df_display['Timestamp'].dt.strftime('%H:%M:%S || %Y-%m-%d')
    
    return {
        "active_now": active_now,
        "total_unique": total_unique,
        "dominant_hardware": dominant_hardware,
        "logs": df_display.to_dict(orient="records")
    }

@app.delete("/api/admin/logs/wipe")
def wipe_admin_logs(password: str = Query(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized wipe action.")
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    init_log_file()
    return {"status": "success", "message": "All session traffic wiped clean."}