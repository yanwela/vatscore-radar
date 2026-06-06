import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from collections import Counter

# ─── API & Sabitler ─────────────────────────────────────────────────────────────
VATSIM_CORE_API = "https://api.vatsim.net/v2"

PILOT_RATINGS = {
    0: "P0 - Observer", 1: "P1 - PPL", 3: "P2 - IR",
    7: "P3 - CMEL", 15: "P4 - ATP", 31: "P5 - CTP", 63: "P6 - Ferry"
}
ATC_RATINGS = {
    -1: "Inactive", 0: "OBS", 1: "S1", 2: "S2", 3: "S3",
    4: "C1", 5: "C2", 6: "C3", 7: "I1", 8: "I2", 9: "I3", 10: "SUP", 11: "ADM"
}
MILITARY_RATINGS = {0: "None", 1: "M1", 2: "M2", 3: "M3"}

# Oturum havuzu oluşturarak API isteklerini hızlandırıyoruz
http_session = requests.Session()

# ─── Yardımcı Fonksiyonlar ──────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def fetch_vatsim_endpoint(endpoint):
    """Core API'den veri çeker ve hataları güvenli bir şekilde yönetir."""
    try:
        url = f"{VATSIM_CORE_API}/{endpoint}"
        r = http_session.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        pass
    return None

def stats_format_hours(minutes):
    try:
        minutes = int(float(minutes))
    except (ValueError, TypeError):
        minutes = 0
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m:02d}m"

def stats_prettify_aircraft(raw):
    if not raw: return "Unknown"
    return raw.split("/")[0].strip().upper()

# ─── Ana Gövde (CID Stats) ──────────────────────────────────────────────────────
st.subheader("📊 Premium CID Statistics & Dossier")

cid_input = st.text_input("Enter VATSIM CID to Inspect", placeholder="e.g. 1863530", max_chars=10, key="premium_cid_input")

if cid_input and cid_input.strip().isdigit():
    s_cid = cid_input.strip()
    
    with st.spinner("📡 Interfacing with VATSIM Core API..."):
        # API İstekleri
        s_details = fetch_vatsim_endpoint(f"members/{s_cid}")
        s_stats   = fetch_vatsim_endpoint(f"members/{s_cid}/stats")
        s_fplans  = fetch_vatsim_endpoint(f"members/{s_cid}/flightplans")
        
        # ATC verisi için limit opsiyonu eklendi, items/results çakışması önlendi
        atc_raw = fetch_vatsim_endpoint(f"members/{s_cid}/atcsessions?limit=100")
        if isinstance(atc_raw, dict):
            s_atcsess = atc_raw.get("items", atc_raw.get("results", []))
        else:
            s_atcsess = atc_raw if isinstance(atc_raw, list) else []

    if not s_details:
        st.error(f"❌ Target CID {s_cid} could not be located in the active VATSIM registry.")
    else:
        # 1. Profil Verilerini Hazırlama
        s_name_first   = s_details.get("name_first", "")
        s_name_last    = s_details.get("name_last", "")
        s_full_name    = f"{s_name_first} {s_name_last}".strip() or f"CID {s_cid}"
        s_rating       = s_details.get("rating", 0)
        s_pilot_rating = s_details.get("pilotrating", 0)
        s_mil_rating   = s_details.get("militaryrating", 0)
        s_reg_date     = str(s_details.get("reg_date", ""))[:10]
        s_division     = s_details.get("division_id", "N/A")
        s_region       = s_details.get("region_id", "N/A")
        
        s_atc_label    = ATC_RATINGS.get(s_rating, f"Rating {s_rating}")
        s_pilot_label  = PILOT_RATINGS.get(s_pilot_rating, f"P{s_pilot_rating}")
        s_mil_label    = MILITARY_RATINGS.get(s_mil_rating, "None")
        
        s_pilot_mins   = s_stats.get("pilot", 0) if s_stats else 0
        s_atc_mins     = s_stats.get("atc", 0)   if s_stats else 0

        # 2. Üst Profil Kartı (Sleek UI)
        mil_badge = f'<span style="background:#2d1b4e;color:#a78bfa;border:1px solid #a78bfa40;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;margin-right:10px;">MIL: {s_mil_label}</span>' if s_mil_rating > 0 else ""
        
        st.markdown(f"""
            <div style="background:linear-gradient(135deg, #0f172a 0%, #111827 100%); border: 1px solid #1e293b; border-left: 5px solid #3b82f6; border-radius: 10px; padding: 24px; margin-bottom: 24px; box-shadow: 0 4px 15px rgba(0,0,0,0.3);">
                <div style="font-size: 28px; font-weight: 800; color: #f8fafc; margin-bottom: 6px; letter-spacing: 0.5px;">{s_full_name}</div>
                <div style="font-size: 14px; color: #94a3b8; font-family: monospace; margin-bottom: 20px;">
                    🎯 CID: {s_cid} &nbsp; | &nbsp; 🌍 {s_region} / {s_division} &nbsp; | &nbsp; 📅 Enrolled: {s_reg_date}
                </div>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <span style="background:#172554;color:#60a5fa;border:1px solid #2563eb40;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">ATC: {s_atc_label}</span>
                    <span style="background:#064e3b;color:#34d399;border:1px solid #05966940;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">PILOT: {s_pilot_label}</span>
                    {mil_badge}
                </div>
            </div>
        """, unsafe_allow_html=True)

        # 3. İstatistik Kartları (Metric Dashboard)
        sc1, sc2, sc3, sc4 = st.columns(4)
        metrics = [
            (sc1, "Pilot Hours", stats_format_hours(s_pilot_mins), f"{s_pilot_mins} total mins"),
            (sc2, "ATC Hours",   stats_format_hours(s_atc_mins),   f"{s_atc_mins} total mins"),
            (sc3, "Recent Flights", str(len(s_fplans) if s_fplans else 0), "Last 50 recorded"),
            (sc4, "ATC Sessions",   str(len(s_atcsess) if s_atcsess else 0), "Last 100 recorded")
        ]
        
        for col, label, value, sub in metrics:
            with col:
                st.markdown(f"""
                    <div style="background:#0f111a; border: 1px solid #1e293b; border-radius: 8px; padding: 18px 20px; text-align: center; margin-bottom: 20px;">
                        <div style="font-size: 12px; color: #64748b; text-transform: uppercase; font-weight: 700; letter-spacing: 1px; margin-bottom: 8px;">{label}</div>
                        <div style="font-size: 26px; font-weight: 800; color: #10b981; font-family: 'Consolas', monospace;">{value}</div>
                        <div style="font-size: 12px; color: #475569; margin-top: 6px;">{sub}</div>
                    </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

        # 4. Uçuş Verileri Analizi
        if s_fplans:
            df_fp = pd.DataFrame(s_fplans)
            df_fp["duration_min"]   = df_fp["hrsenroute"] * 60 + df_fp["minenroute"]
            df_fp["aircraft_short"] = df_fp["aircraft"].apply(stats_prettify_aircraft)
            df_fp["route_str"]      = df_fp["dep"].fillna("???") + " → " + df_fp["arr"].fillna("???")
            df_fp["filed_dt"]       = pd.to_datetime(df_fp["filed"], errors="coerce", utc=True)

            first_flight = df_fp["filed_dt"].min()
            last_flight  = df_fp["filed_dt"].max()

            col_left, col_right = st.columns([1, 1])

            with col_left:
                st.markdown("#### 🧭 Top Flown Routes (Recent)")
                route_counts = Counter(df_fp["route_str"].tolist())
                routes_html = ""
                for route, count in route_counts.most_common(6):
                    dep_r, arr_r = route.split(" → ")
                    routes_html += f"""
                    <div style="background:#0f111a; border: 1px solid #1e293b; border-left: 3px solid #3b82f6; border-radius: 6px; padding: 12px 16px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-family: monospace; font-size: 15px; font-weight: bold; color: #f8fafc;">
                            <span style="color: #60a5fa;">{dep_r}</span> ✈️ <span style="color: #60a5fa;">{arr_r}</span>
                        </span>
                        <span style="background: #064e3b; color: #34d399; padding: 2px 8px; border-radius: 4px; font-size: 13px; font-weight: bold;">{count} Flights</span>
                    </div>"""
                st.markdown(routes_html, unsafe_allow_html=True)

                st.markdown("<br>#### 🕒 Flight Timeline", unsafe_allow_html=True)
                t1, t2 = st.columns(2)
                
                date_format = "%b %d, %Y"
                val_first = first_flight.strftime(date_format) if pd.notna(first_flight) else "N/A"
                val_last  = last_flight.strftime(date_format) if pd.notna(last_flight) else "N/A"
                
                with t1:
                    st.markdown(f'<div style="background:#0f111a; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; text-align: center;"><div style="font-size:12px; color:#64748b; text-transform:uppercase; font-weight:bold; margin-bottom:6px;">Oldest Record</div><div style="font-size:16px; font-weight:bold; color:#f8fafc;">{val_first}</div></div>', unsafe_allow_html=True)
                with t2:
                    st.markdown(f'<div style="background:#0f111a; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; text-align: center;"><div style="font-size:12px; color:#64748b; text-transform:uppercase; font-weight:bold; margin-bottom:6px;">Newest Record</div><div style="font-size:16px; font-weight:bold; color:#3b82f6;">{val_last}</div></div>', unsafe_allow_html=True)

            with col_right:
                st.markdown("#### ✈️ Fleet Distribution")
                ac_counts = df_fp["aircraft_short"].value_counts().head(8).reset_index()
                ac_counts.columns = ["Aircraft", "Count"]
                
                fig_ac = px.bar(ac_counts, x="Count", y="Aircraft", orientation="h",
                                color="Count", color_continuous_scale=[[0, "#1e3a8a"], [1, "#3b82f6"]], template="plotly_dark")
                fig_ac.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                     margin=dict(l=0, r=0, t=10, b=0), height=280, showlegend=False,
                                     coloraxis_showscale=False, yaxis=dict(autorange="reversed", title=""), xaxis=dict(title=""))
                fig_ac.update_traces(marker_line_width=0, opacity=0.9)
                st.plotly_chart(fig_ac, use_container_width=True)

            # Uçuş Süresi Tablosu
            st.markdown("<br>#### ⏱️ Longest Executed Flights", unsafe_allow_html=True)
            df_dur = df_fp[df_fp["duration_min"] > 0].sort_values("duration_min", ascending=False).head(15).copy()
            df_dur["label"] = df_dur["route_str"] + " (" + df_dur["aircraft_short"] + ")"
            
            fig_dur = px.bar(df_dur, x="duration_min", y="label", orientation="h",
                             color="duration_min", color_continuous_scale=[[0, "#064e3b"], [1, "#10b981"]], template="plotly_dark")
            fig_dur.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  margin=dict(l=0, r=0, t=10, b=0), height=400, showlegend=False,
                                  coloraxis_showscale=False, yaxis=dict(autorange="reversed", title=""), xaxis=dict(title="Duration (Minutes)"))
            fig_dur.update_traces(marker_line_width=0, opacity=0.9)
            st.plotly_chart(fig_dur, use_container_width=True)

        # 5. ATC Verileri Analizi
        if s_atc_mins > 0 and s_atcsess:
            st.markdown("---")
            st.markdown("#### 🎧 ATC Sector Mastery")
            df_atc = pd.DataFrame(s_atcsess)
            if "callsign" in df_atc.columns:
                atc_cnt = df_atc["callsign"].value_counts().head(12).reset_index()
                atc_cnt.columns = ["Position", "Sessions"]
                
                fig_atc = px.bar(atc_cnt, x="Sessions", y="Position", orientation="h",
                                 color="Sessions", color_continuous_scale=[[0, "#312e81"], [1, "#6366f1"]], template="plotly_dark")
                fig_atc.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                      margin=dict(l=0, r=0, t=10, b=0), height=350, showlegend=False,
                                      coloraxis_showscale=False, yaxis=dict(autorange="reversed", title=""), xaxis=dict(title="Sessions Controlled"))
                fig_atc.update_traces(marker_line_width=0, opacity=0.9)
                st.plotly_chart(fig_atc, use_container_width=True)
        elif s_atc_mins == 0 and s_atcsess:
            st.info("No notable ATC activity found on record.")
else:
    st.info("Enter a valid numeric VATSIM CID above to load the detailed profile analytics.")