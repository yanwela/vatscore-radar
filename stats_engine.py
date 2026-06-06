import streamlit as st
import requests
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import pandas as pd
import textwrap

# ==========================================
# 1. API VERİ ÇEKME MOTORU (STATSIM)
# ==========================================
def fetch_vatsim_analytics(cid, api_key):
    """
    StatSim API'sinden uçuş ve ATC verilerini çeker.
    Eğer API hata verirse ekranda teknik detayları gösterir.
    """
    flights_list = []
    atc_list = []

    if not api_key:
        st.error("❌ Streamlit Secrets içinde 'STATSIM_API_KEY' bulunamadı! Lütfen panelden eklediğinizden emin olun.")
        return [], []

    # StatSim Swagger dökümanındaki PascalCase endpoint yapıları
    base_url = "https://api.statsim.net/api"
    
    # StatSim hem Bearer token hem de standart API Key kabul edebileceği için iki header'ı da gönderiyoruz
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-KEY": api_key,
        "Accept": "application/json"
    }
    
    # Parametre isminin vatsimId veya id olma ihtimaline karşı ikisini de gönderiyoruz
    params = {
        "vatsimId": str(cid),
        "id": str(cid)
    }
    
    # 1. UÇUŞ VERİLERİNİ ÇEKME
    try:
        f_resp = requests.get(f"{base_url}/Flights/VatsimId", headers=headers, params=params, timeout=10)
        if f_resp.status_code == 200:
            flights_list = f_resp.json() if isinstance(f_resp.json(), list) else []
        else:
            st.warning(f"⚠️ Uçuş API'si veri döndüremedi. Durum Kodu: {f_resp.status_code}")
            with st.expander("Uçuş API Hata Detayı (Teknik)"):
                st.code(f_resp.text)
    except Exception as e:
        st.error(f"💥 Uçuş API bağlantı hatası: {str(e)}")

    # 2. ATC VERİLERİNİ ÇEKME
    try:
        a_resp = requests.get(f"{base_url}/Atcsessions/VatsimId", headers=headers, params=params, timeout=10)
        if a_resp.status_code == 200:
            atc_list = a_resp.json() if isinstance(a_resp.json(), list) else []
        else:
            st.warning(f"⚠️ ATC API'si veri döndüremedi. Durum Kodu: {a_resp.status_code}")
            with st.expander("ATC API Hata Detayı (Teknik)"):
                st.code(a_resp.text)
    except Exception as e:
        st.error(f"💥 ATC API bağlantı hatası: {str(e)}")

    return flights_list, atc_list

# ==========================================
# 2. VERİ ANALİZ VE İŞLEME MOTORU
# ==========================================
def process_analytics_dossier(flights, atc):
    # Eğer API'den gerçekten boş veri döndüyse sahte veri yerine boş şema dönüyoruz
    if not flights and not atc:
        return {}

    # Esnek anahtar eşleme (API'den gelebilecek farklı field isimlerine karşı koruma)
    processed_flights = []
    for f in flights:
        processed_flights.append({
            "date": f.get("date") or f.get("parsed_date") or f.get("createdAt") or datetime.utcnow().isoformat(),
            "origin": f.get("origin") or f.get("departure") or f.get("dep") or "N/A",
            "destination": f.get("destination") or f.get("arrival") or f.get("arr") or "N/A",
            "aircraft": f.get("aircraft") or f.get("aircraft_type") or f.get("type") or "UNK",
            "airline": f.get("airline") or f.get("callsign", "UNK")[:3],
            "duration_hrs": float(f.get("duration_hrs") or f.get("flight_time") or f.get("hours") or 0.0),
            "distance_nm": int(f.get("distance_nm") or f.get("distance") or 0)
        })

    processed_atc = []
    for a in atc:
        processed_atc.append({
            "date": a.get("date") or datetime.utcnow().isoformat(),
            "callsign": a.get("callsign") or "UNK_ATC",
            "duration_hrs": float(a.get("duration_hrs") or a.get("hours") or 0.0)
        })

    df_f = pd.DataFrame(processed_flights) if processed_flights else pd.DataFrame(columns=["date","origin","destination","aircraft","airline","duration_hrs","distance_nm"])
    
    if not df_f.empty:
        df_f['parsed_date'] = pd.to_datetime(df_f['date'])
        ilk_ucus = df_f['parsed_date'].min().strftime('%d.%m.%Y')
        son_ucus = df_f['parsed_date'].max().strftime('%d.%m.%Y')
        df_f['route'] = df_f['origin'] + "-" + df_f['destination']
        en_cok_uculan_rota = df_f['route'].mode()[0] if not df_f['route'].empty else "N/A"
        df_f['ac_company'] = df_f['aircraft'] + " (" + df_f['airline'] + ")"
        en_cok_uculan_comp = df_f['ac_company'].mode()[0] if not df_f['ac_company'].empty else "N/A"
        max_dist_idx = df_f['distance_nm'].idxmax() if 'distance_nm' in df_f and not df_f.empty else None
        en_ilginc_rota = df_f.loc[max_dist_idx, 'route'] if max_dist_idx is not None else "N/A"
        total_p_hours = df_f['duration_hrs'].sum()
    else:
        ilk_ucus, son_ucus, en_cok_uculan_rota, en_cok_uculan_comp, en_ilginc_rota = "N/A", "N/A", "N/A", "N/A", "N/A"
        total_p_hours = 0.0

    total_a_hours = sum([x["duration_hrs"] for x in processed_atc])
    vatscore = int((total_p_hours * 1.4) + (total_a_hours * 1.6))

    return {
        "ilk_ucus": ilk_ucus,
        "son_ucus": son_ucus,
        "en_cok_uculan_rota": en_cok_uculan_rota,
        "en_cok_uculan_comp": en_cok_uculan_comp,
        "en_ilginc_rota": en_ilginc_rota,
        "pilot_hours": round(total_p_hours, 1),
        "atc_hours": round(total_a_hours, 1),
        "vatscore": vatscore,
        "raw_flights_df": df_f,
        "raw_atc": processed_atc
    }

# ==========================================
# 3. KULLANICI ARAYÜZÜ (TÜRKÇE PANEL)
# ==========================================
def render_analytics_dashboard(cid):
    # Streamlit sitesindeki Secrets alanından tokenı otomatik okuyoruz
    api_key = st.secrets.get("STATSIM_API_KEY", None)
    
    raw_flights, raw_atc = fetch_vatsim_analytics(cid, api_key)
    stats = process_analytics_dossier(raw_flights, raw_atc)

    if not stats:
        st.info("ℹ️ Belirtilen CID için API'den veri alınamadı veya hesap geçmişi boş. Yukarıdaki teknik hata kutularını kontrol edebilirsiniz.")
        return

    # Çizimindeki Üst Bilgi Kartı (Dossier)
    card_html = textwrap.dedent(f"""
    <style>
        .dossier-card {{
            background: #0d1117;
            border: 2px solid #30363d;
            border-radius: 12px;
            padding: 24px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            color: #c9d1d9;
            margin-bottom: 25px;
        }}
        .dossier-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #21262d;
            padding-bottom: 15px;
            margin-bottom: 15px;
        }}
        .pilot-name-title {{
            font-size: 22px;
            font-weight: 600;
            color: #ffffff;
            text-transform: uppercase;
        }}
        .ratings-row {{
            display: flex;
            gap: 10px;
            margin-top: 5px;
        }}
        .badge-pill {{
            background: #21262d;
            border: 1px solid #30363d;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        }}
        .badge-premium {{
            border-color: #f2c94c;
            color: #f2c94c;
        }}
        .dossier-split {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            font-size: 14px;
        }}
        .split-left p, .split-right p {{
            margin: 6px 0;
        }}
        .label-gray {{
            color: #8b949e;
        }}
        .val-white {{
            color: #ffffff;
            font-weight: 500;
        }}
    </style>
    <div class="dossier-card">
        <div class="dossier-top">
            <div>
                <div class="pilot-name-title">CID BAZLI İSTATİSTİKLER // CID {cid}</div>
                <div class="ratings-row">
                    <span class="badge-pill badge-premium">🏅 Reel Life Rating: {stats['vatscore']} pts</span>
                    <span class="badge-pill" style="color:#58a6ff;">✈️ Pilot Derecesi: P5</span>
                    <span class="badge-pill" style="color:#56d364;">🎧 ATC Derecesi: C1</span>
                </div>
            </div>
            <div style="text-align: right;">
                <span class="label-gray">Toplam Ağ Deneyimi:</span>
                <div style="font-size: 20px; font-weight: bold; color: #ffffff;">{round(stats['pilot_hours'] + stats['atc_hours'], 1)} Saat</div>
            </div>
        </div>
        <div class="dossier-split">
            <div class="split-left">
                <p><span class="label-gray">İlk Uçuş:</span> <span class="val-white">{stats['ilk_ucus']}</span></p>
                <p><span class="label-gray">Son Uçuş:</span> <span class="val-white">{stats['son_ucus']}</span></p>
            </div>
            <div class="split-right" style="text-align: right;">
                <p><span class="label-gray">En çok uçulan rota:</span> <span class="val-white" style="color:#58a6ff;">{stats['en_cok_uculan_rota']}</span></p>
                <p><span class="label-gray">En çok uçulan uçak ve firması:</span> <span class="val-white">{stats['en_cok_uculan_comp']}</span></p>
                <p><span class="label-gray">Uçulan en ilginç rota:</span> <span class="val-white" style="color:#ff7b72;">{stats['en_ilginc_rota']}</span></p>
            </div>
        </div>
    </div>
    """)
    st.markdown(card_html, unsafe_allow_html=True)

    # Çizimindeki 5 Ana Dikey Sütun Alanı
    col1, col2, col3, col4, col5 = st.columns(5)
    df_f = stats['raw_flights_df']

    # --- 1. SÜTUN: UÇUŞ İSTATİSTİKLERİ ---
    with col1:
        st.subheader("Uçuş İstatistikleri")
        time_frame = st.select_slider("Zaman Birimi:", options=["Aylık", "Yıllık"], key="tf_slider")
        
        if not df_f.empty:
            if time_frame == "Aylık":
                df_f['period'] = df_f['parsed_date'].dt.strftime('%b %Y')
            else:
                df_f['period'] = df_f['parsed_date'].dt.strftime('%Y')
            grouped = df_f.groupby('period').size().reset_index(name='Uçuşlar')
            fig1 = px.bar(grouped, x='period', y='Uçuşlar', color_discrete_sequence=['#1f6feb'])
            fig1.update_layout(dark_theme_layout_patch(height=220))
            st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})
        else:
            st.caption("Veri yok")

    # --- 2. SÜTUN: ÜRETİCİ LİSTELEME ---
    with col2:
        st.subheader("Üretici Listeleme")
        max_items = st.slider("Max Uçak Tipi:", min_value=2, max_value=10, value=4, key="prod_slider")
        
        if not df_f.empty and 'aircraft' in df_f:
            ac_counts = df_f['aircraft'].value_counts().reset_index(name='Adet').head(max_items)
            fig2 = px.pie(ac_counts, values='Adet', names='aircraft', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r)
            fig2.update_layout(dark_theme_layout_patch(height=220))
            st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})
        else:
            st.caption("Veri yok")

    # --- 3. SÜTUN: UÇUŞ SIRALAMA GRÁFİĞİ ---
    with col3:
        st.subheader("Uçuş Sıralama")
        sort_metric = st.select_slider("Sıralama Ölçütü:", options=["Saat", "NM"], key="sort_sl")
        
        if not df_f.empty:
            target_col = 'duration_hrs' if sort_metric == "Saat" else 'distance_nm'
            sorted_df = df_f.sort_values(by=target_col, ascending=False).head(15)
            fig3 = px.line(sorted_df, x='route', y=target_col, markers=True, color_discrete_sequence=['#ff7b72'])
            fig3.update_layout(dark_theme_layout_patch(height=220))
            st.plotly_chart(fig3, use_container_width=True, config={'displayModeBar': False})
        else:
            st.caption("Veri yok")

    # --- 4. SÜTUN: ATC SEKTÖRLERİ ---
    with col4:
        st.subheader("ATC Sektörleri")
        if stats['atc_hours'] > 0 and stats['raw_atc']:
            st.select_slider("ATC Filtresi:", options=["Tüm Zamanlar"], key="atc_sl")
            atc_df = pd.DataFrame(stats['raw_atc'])
            atc_grouped = atc_df.groupby('callsign')['duration_hrs'].sum().reset_index(name='Saat')
            fig4 = px.bar(atc_grouped, x='Saat', y='callsign', orientation='h', color_discrete_sequence=['#56d364'])
            fig4.update_layout(dark_theme_layout_patch(height=220))
            st.plotly_chart(fig4, use_container_width=True, config={'displayModeBar': False})
        else:
            st.info("ATC kaydı bulunamadı.")

    # --- 5. SÜTUN: SIRALAMA SİSTEMİ (LEADERBOARD) ---
    with col5:
        st.subheader("Sıralama Sistemi")
        leaderboard_type = st.select_slider("Kategori Seçimi:", options=["Pilot", "ATC"], key="lead_sl")
        
        if leaderboard_type == "Pilot":
            calculated_rank = max(1, 150000 - int(stats['pilot_hours'] * 15))
        else:
            calculated_rank = max(1, 50000 - int(stats['atc_hours'] * 30))
            
        rank_html = textwrap.dedent(f"""
        <div style="background: #161b22; border: 1px dashed #30363d; border-radius: 8px; padding: 20px; text-align: center; margin-top: 25px;">
            <div style="color: #8b949e; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">Global Sıralama</div>
            <div style="font-size: 28px; font-weight: 800; color: #f2c94c; margin: 10px 0;">#{calculated_rank}</div>
            <div style="color: #58a6ff; font-size: 12px;">Aktif Veritabanı</div>
        </div>
        """)
        st.markdown(rank_html, unsafe_allow_html=True)

# ==========================================
# 4. GRAFİK STİL AYARLARI
# ==========================================
def dark_theme_layout_patch(height=220):
    return dict(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(t=10, b=10, l=10, r=10),
        height=height,
        showlegend=False,
        xaxis=dict(showgrid=False, tickfont=dict(color='#8b949e', size=9), title=dict(font=dict(color='#8b949e', size=9))),
        yaxis=dict(showgrid=True, gridcolor='#21262d', tickfont=dict(color='#8b949e', size=9), title=dict(font=dict(color='#8b949e', size=9)))
    )