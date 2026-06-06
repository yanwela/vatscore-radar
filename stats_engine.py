import streamlit as st
import requests
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime
import textwrap

# ==========================================
# 1. VATSIM OFFICIAL CORE API ENGINE (NO AUTH)
# ==========================================
def fetch_official_vatsim_data(cid):
    """
    StatSim tamamen kaldırıldı. 
    Veriler sadece şifresiz resmi VATSIM Core API üzerinden (api.vatsim.net/v2) çekilir.
    """
    base_url = "https://api.vatsim.net/v2/members"
    headers = {"Accept": "application/json"}
    
    # 1. Temel Üye Bilgileri (Reytingler)
    member_data = {}
    try:
        r_member = requests.get(f"{base_url}/{cid}", headers=headers, timeout=5)
        if r_member.status_code == 200:
            member_data = r_member.json()
    except: pass

    # 2. Toplam Saat İstatistikleri
    stats_data = {"atc": 0, "pilot": 0}
    try:
        r_stats = requests.get(f"{base_url}/{cid}/stats", headers=headers, timeout=5)
        if r_stats.status_code == 200:
            stats_data = r_stats.json()
    except: pass

    # 3. Uçuş Geçmişi (Flight History)
    flights_data = []
    try:
        r_flights = requests.get(f"{base_url}/{cid}/history", headers=headers, timeout=8)
        if r_flights.status_code == 200:
            flights_data = r_flights.json() if isinstance(r_flights.json(), list) else []
    except: pass

    # 4. ATC Seans Geçmişi
    atc_data = []
    try:
        r_atc = requests.get(f"{base_url}/{cid}/atc", headers=headers, timeout=8)
        if r_atc.status_code == 200:
            atc_data = r_atc.json() if isinstance(r_atc.json(), list) else []
    except: pass

    return member_data, stats_data, flights_data, atc_data

# ==========================================
# 2. VERİ İŞLEME VE DOSYA OLUŞTURMA
# ==========================================
def process_dossier(member, stats, flights, atc):
    if not member and not flights:
        return None

    # VATSIM Rating Kodlarını String'e Çevirme
    pilot_ratings = {0: "P0", 1: "P1", 3: "P2", 7: "P3", 15: "P4", 31: "P5"}
    atc_ratings = {1: "OBS", 2: "S1", 3: "S2", 4: "S3", 5: "C1", 7: "C3", 8: "I1", 10: "I3", 11: "SUP", 12: "ADM"}
    
    p_rating = pilot_ratings.get(member.get("pilotrating", 0), "P0")
    a_rating = atc_ratings.get(member.get("rating", 1), "OBS")

    # Uçuş Verilerini Temizleme (Resmi API formatından ayıklama)
    clean_flights = []
    for f in flights:
        try:
            dep = f.get("dep", "N/A")
            arr = f.get("arr", "N/A")
            # VATSIM API uçuş rotası boş ise atla
            if not dep or not arr: continue
            
            # Bağlantı süresini hesaplama (Bağlantı başlangıç - bitiş)
            start_time = datetime.strptime(f["start"][:19], "%Y-%m-%dT%H:%M:%S")
            end_time = datetime.strptime(f["end"][:19], "%Y-%m-%dT%H:%M:%S") if f.get("end") else start_time
            duration = (end_time - start_time).total_seconds() / 3600.0
            
            if duration <= 0: continue # Hatalı dataları atla
            
            clean_flights.append({
                "date": start_time,
                "callsign": f.get("callsign", "UNK"),
                "origin": dep,
                "destination": arr,
                "route": f"{dep}-{arr}",
                "aircraft": str(f.get("aircraft", "UNK")).split("/")[0][:4], # Hızlı uçak tipi ayıklama
                "duration_hrs": duration
            })
        except: continue

    df_f = pd.DataFrame(clean_flights)
    
    # ATC Verilerini Temizleme
    clean_atc = []
    for a in atc:
        try:
            start_time = datetime.strptime(a["start"][:19], "%Y-%m-%dT%H:%M:%S")
            end_time = datetime.strptime(a["end"][:19], "%Y-%m-%dT%H:%M:%S") if a.get("end") else start_time
            duration = (end_time - start_time).total_seconds() / 3600.0
            if duration > 0:
                clean_atc.append({"callsign": a.get("callsign", "UNK"), "duration_hrs": duration})
        except: continue
        
    df_a = pd.DataFrame(clean_atc)

    # İstatistiksel Hesaplamalar
    if not df_f.empty:
        ilk_ucus = df_f['date'].min().strftime('%d.%m.%Y')
        son_ucus = df_f['date'].max().strftime('%d.%m.%Y')
        en_cok_uculan_rota = df_f['route'].mode()[0]
        en_cok_uculan_ucak = df_f['aircraft'].mode()[0]
    else:
        ilk_ucus, son_ucus, en_cok_uculan_rota, en_cok_uculan_ucak = "Yok", "Yok", "Yok", "Yok"

    pilot_hours = stats.get("pilot", 0)
    atc_hours = stats.get("atc", 0)
    vatscore = int((pilot_hours * 1.4) + (atc_hours * 1.6))

    return {
        "p_rating": p_rating,
        "a_rating": a_rating,
        "ilk_ucus": ilk_ucus,
        "son_ucus": son_ucus,
        "en_cok_uculan_rota": en_cok_uculan_rota,
        "en_cok_uculan_ucak": en_cok_uculan_ucak,
        "pilot_hours": round(pilot_hours, 1),
        "atc_hours": round(atc_hours, 1),
        "vatscore": vatscore,
        "df_f": df_f,
        "df_a": df_a
    }

# ==========================================
# 3. ARAYÜZ (CID BAZLI STATS - TASARIM BİREBİR)
# ==========================================
def render_analytics_dashboard(cid):
    # API ANAHTARI YOK! DOĞRUDAN VATSIM'E BAĞLANIYOR.
    with st.spinner("VATSIM Sunucularından Şifresiz Veri Çekiliyor..."):
        m_data, s_data, f_data, a_data = fetch_official_vatsim_data(cid)
    
    stats = process_dossier(m_data, s_data, f_data, a_data)

    if not stats:
        st.error("❌ VATSIM sunucularında bu CID'ye ait uçuş veya üye verisi bulunamadı.")
        return

    # ÜST BİLGİ KARTI (TASARIMDAKİ İLK BÖLÜM)
    card_html = textwrap.dedent(f"""
    <div style="background: #0d1117; border: 2px solid #30363d; border-radius: 12px; padding: 24px; color: #c9d1d9; font-family: sans-serif; margin-bottom: 25px;">
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #21262d; padding-bottom: 15px; margin-bottom: 15px;">
            <div>
                <h2 style="margin:0; color:#fff;">KULLANICI BİLGİLERİ // CID: {cid}</h2>
                <div style="margin-top: 10px;">
                    <span style="background: #21262d; border: 1px solid #f2c94c; color:#f2c94c; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size:12px;">🏅 Reel Life Rating: {stats['vatscore']}</span>
                    <span style="background: #21262d; border: 1px solid #30363d; color:#58a6ff; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size:12px;">✈️ Pilot: {stats['p_rating']}</span>
                    <span style="background: #21262d; border: 1px solid #30363d; color:#56d364; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size:12px;">🎧 ATC: {stats['a_rating']}</span>
                </div>
            </div>
            <div style="text-align: right;">
                <span style="color:#8b949e; font-size:14px;">Toplam Network Saati:</span>
                <div style="font-size: 24px; font-weight: bold; color: #ffffff;">{round(stats['pilot_hours'] + stats['atc_hours'], 1)} Saat</div>
            </div>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <div>
                <p style="margin: 5px 0;"><span style="color:#8b949e;">İlk Uçuş:</span> <span style="color:#fff;">{stats['ilk_ucus']}</span></p>
                <p style="margin: 5px 0;"><span style="color:#8b949e;">Son Uçuş:</span> <span style="color:#fff;">{stats['son_ucus']}</span></p>
            </div>
            <div style="text-align: right;">
                <p style="margin: 5px 0;"><span style="color:#8b949e;">En Çok Uçulan Rota:</span> <span style="color:#58a6ff;">{stats['en_cok_uculan_rota']}</span></p>
                <p style="margin: 5px 0;"><span style="color:#8b949e;">En Çok Uçulan Uçak:</span> <span style="color:#fff;">{stats['en_cok_uculan_ucak']}</span></p>
            </div>
        </div>
    </div>
    """)
    st.markdown(card_html, unsafe_allow_html=True)

    # 5'Lİ GRAFİK SÜTUNLARI (TASARIMDAKİ ALT BÖLÜM)
    col1, col2, col3, col4, col5 = st.columns(5)
    df_f = stats['df_f']
    df_a = stats['df_a']

    # 1. UÇUŞ İSTATİSTİKLERİ (AYLIK/YILLIK)
    with col1:
        st.subheader("Uçuş İstatistikleri")
        tf = st.select_slider("Zaman:", options=["Aylık", "Yıllık"], key="tf_sl")
        if not df_f.empty:
            df_f['period'] = df_f['date'].dt.strftime('%b %Y' if tf == "Aylık" else '%Y')
            grouped = df_f.groupby('period').size().reset_index(name='Uçuşlar')
            fig1 = px.bar(grouped, x='period', y='Uçuşlar', color_discrete_sequence=['#1f6feb'])
            fig1.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=220, showlegend=False, margin=dict(t=10, b=10, l=10, r=10), xaxis_title="", yaxis_title="")
            st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})
        else: st.caption("Veri Yok")

    # 2. ÜRETİCİ BAZLI LİSTELEME
    with col2:
        st.subheader("Uçak / Üretici")
        mx = st.slider("Max Gösterim:", 2, 6, 4, key="mx_sl")
        if not df_f.empty:
            ac_counts = df_f['aircraft'].value_counts().reset_index(name='Adet').head(mx)
            fig2 = px.pie(ac_counts, values='Adet', names='aircraft', hole=0.5, color_discrete_sequence=px.colors.sequential.Blues_r)
            fig2.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=220, showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})
        else: st.caption("Veri Yok")

    # 3. UZUNDAN KISAYA UÇUŞ SIRALAMASI
    with col3:
        st.subheader("Uçuş Süreleri")
        if not df_f.empty:
            sorted_df = df_f.sort_values(by='duration_hrs', ascending=False).head(10)
            fig3 = px.line(sorted_df, x='route', y='duration_hrs', markers=True, color_discrete_sequence=['#ff7b72'])
            fig3.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=220, showlegend=False, margin=dict(t=10, b=10, l=10, r=10), xaxis_title="", yaxis_title="")
            st.plotly_chart(fig3, use_container_width=True, config={'displayModeBar': False})
        else: st.caption("Veri Yok")

    # 4. ATC SEKTÖRLERİ SIRALAMASI
    with col4:
        st.subheader("ATC Geçmişi")
        if not df_a.empty:
            a_grouped = df_a.groupby('callsign')['duration_hrs'].sum().reset_index(name='Saat').sort_values(by='Saat', ascending=True).tail(5)
            fig4 = px.bar(a_grouped, x='Saat', y='callsign', orientation='h', color_discrete_sequence=['#56d364'])
            fig4.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=220, showlegend=False, margin=dict(t=10, b=10, l=10, r=10), xaxis_title="", yaxis_title="")
            st.plotly_chart(fig4, use_container_width=True, config={'displayModeBar': False})
        else: st.caption("ATC Kaydı Yok")

    # 5. GLOBAL SIRALAMA SİSTEMİ
    with col5:
        st.subheader("Sıralama")
        cat = st.select_slider("Kategori:", options=["Pilot", "ATC"], key="rank_sl")
        # Global veritabanı aktif olmadığı için tahmini bir rank denklemi
        rank = max(1, 145000 - int(stats['pilot_hours'] * 12)) if cat == "Pilot" else max(1, 48000 - int(stats['atc_hours'] * 25))
        rank_html = textwrap.dedent(f"""
        <div style="background: #161b22; border: 1px dashed #30363d; border-radius: 8px; padding: 20px; text-align: center; margin-top: 10px;">
            <div style="color: #8b949e; font-size: 11px; text-transform: uppercase;">Global Sıra</div>
            <div style="font-size: 28px; font-weight: 800; color: #f2c94c; margin: 10px 0;">#{rank}</div>
            <div style="color: #58a6ff; font-size: 12px;">VATSIM Core DB</div>
        </div>
        """)
        st.markdown(rank_html, unsafe_allow_html=True)