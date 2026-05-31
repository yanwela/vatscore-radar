from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import pandas as pd
from datetime import datetime
from user_agents import parse

app = FastAPI()

# Tarayıcının (index.html) güvenle bağlanabilmesi için CORS (güvenlik) ayarı
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
LOG_FILE = "radar_traffic_logs.csv"

# Log dosyası yoksa otomatik olarak oluşturur (Eski sistemin birebir aynısı)
def init_log_file():
    if not os.path.exists(LOG_FILE):
        df = pd.DataFrame(columns=["Timestamp", "OS", "Browser", "Device_Type"])
        df.to_csv(LOG_FILE, index=False)

init_log_file()

# Kullanıcı trafiğini arka planda sessizce loglayan fonksiyon
def log_visitor(user_agent_string: str):
    try:
        user_agent = parse(user_agent_string)
        os_name = f"{user_agent.os.family} {user_agent.os.version_string}"
        browser_name = f"{user_agent.browser.family} {user_agent.browser.version_string}"
        
        if user_agent.is_mobile:
            device_type = "📱 Mobile"
        elif user_agent.is_pc:
            device_type = "💻 PC / Laptop"
        else:
            device_type = "🤖 Bot/Unknown"
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        df = pd.read_csv(LOG_FILE)
        new_row = pd.DataFrame([{
            "Timestamp": timestamp, 
            "OS": os_name, 
            "Browser": browser_name, 
            "Device_Type": device_type
        }])
        
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(LOG_FILE, index=False)
    except:
        pass  # Loglama sırasındaki hatalar arayüzü kilitlemesin diye sessiz geçiyoruz

# JavaScript (app.js) motorunun her 30 saniyede bir vuracağı API endpoint'i
@app.get("/api/vatsim")
def get_vatsim_data(user_agent: str = Header(None)):
    # İstek atan kullanıcının User-Agent bilgisini alıp logluyoruz
    if user_agent:
        log_visitor(user_agent)
        
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"VATSIM API Fetch Error: {e}")
        
    # Hata durumunda uygulamanın çökmemesi için boş bir şablon dönüyoruz
    return {"pilots": [], "controllers": []}