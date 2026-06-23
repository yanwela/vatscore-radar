import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter
from datetime import datetime, timezone

# ─── API & Sabitler ──────────────────────────────────────────────────────────────
VATSIM_CORE_API   = "https://api.vatsim.net/v2"
VATSIM_DATA_URL   = "https://data.vatsim.net/v3/vatsim-data.json"

# ATC rating: integer index
ATC_RATINGS = {
    -1: "Inactive", 0: "OBS", 1: "S1", 2: "S2", 3: "S3",
    4: "C1", 5: "C2", 6: "C3", 7: "I1", 8: "I2", 9: "I3",
    10: "SUP", 11: "ADM"
}

# Pilot rating: kümülatif bitmask (VATSIM standardı)
# Her değer önceki seviyeleri de içerir
def decode_pilot_rating(value):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return "P0"
    if v >= 63:  return "P6 — Ferry Pilot"
    if v >= 31:  return "P5 — CTP"
    if v >= 15:  return "P4 — ATP"
    if v >= 7:   return "P3 — CMEL"
    if v >= 3:   return "P2 — IR"
    if v >= 1:   return "P1 — PPL"
    return "P0 — OBS"

def decode_pilot_rating_short(value):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return "P0"
    if v >= 63:  return "P6"
    if v >= 31:  return "P5"
    if v >= 15:  return "P4"
    if v >= 7:   return "P3"
    if v >= 3:   return "P2"
    if v >= 1:   return "P1"
    return "P0"

MILITARY_RATINGS = {0: "None", 1: "M1", 2: "M2", 3: "M3"}

http_session = requests.Session()

# ─── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_vatsim_endpoint(endpoint):
    """VATSIM Core API v2'den veri çeker."""
    try:
        r = http_session.get(f"{VATSIM_CORE_API}/{endpoint}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

@st.cache_data(ttl=30, show_spinner=False)
def fetch_live_vatsim_data():
    """Canlı VATSIM veri dosyasını çeker."""
    try:
        r = http_session.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def find_pilot_live(cid: str):
    """Canlı VATSIM feed'inden CID eşleşen pilotu döndürür."""
    data = fetch_live_vatsim_data()
    if not data:
        return None
    for p in data.get("pilots", []):
        if str(p.get("cid", "")) == cid:
            return p
    return None

def format_hours(minutes):
    try:
        minutes = int(float(minutes))
    except (ValueError, TypeError):
        minutes = 0
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m:02d}m"

def prettify_aircraft(raw):
    if not raw:
        return "Unknown"
    # Uçak tip kodunu ICAO standardına çevir
    # B738 Max 8 → B38M, A321neo → A21N gibi - API zaten ICAO kodu döndürüyor
    return raw.split("/")[0].strip().upper()

def manufacturer_of(icao_type: str) -> str:
    """ICAO uçak tipinden üretici adını tahmin et."""
    t = icao_type.upper()
    if t.startswith(("A3", "A2", "A1", "A0")):  return "Airbus"
    if t.startswith(("B7", "B6", "B5", "B4", "B3", "B2", "B1", "B0", "73", "74", "75", "76", "77", "78")):
        return "Boeing"
    if t.startswith(("C5", "C17", "C13", "C14")):  return "Lockheed"
    if t.startswith(("E1", "E17", "E19", "E75", "E50", "E55")):  return "Embraer"
    if t.startswith(("CRJ", "CR2", "CR7", "CR9", "CRK")):  return "Bombardier"
    if t.startswith(("DH8", "DHC", "AT4", "AT7", "SF3", "SF5")):  return "ATR/DHC"
    if t.startswith(("MD8", "MD9", "MD1", "DC9", "DC8", "DC1")):  return "McDonnell Douglas"
    if t.startswith(("F1", "F7", "F28", "F50", "F70", "F10")):  return "Fokker"
    if t.startswith(("BE", "C17", "C25", "C30", "C40", "C55", "C56", "C68", "C72", "GL5", "GL6", "LJ", "CL6")):
        return "Business Jet"
    if t.startswith(("C1", "C17", "C2", "P28", "DA4", "SR2")):  return "General Aviation"
    return "Other"

def unique_route_score(dep: str, arr: str, all_routes: list) -> float:
    """
    Rotanın ne kadar 'ilginç/nadir' olduğunu skora çevirir.
    Frekansı az olanlar daha yüksek skor alır.
    """
    route = f"{dep}→{arr}"
    count = sum(1 for r in all_routes if r == route)
    return 1.0 / (count + 1)

# ─── Metric kart HTML yardımcısı ─────────────────────────────────────────────────
def stat_card(label: str, value: str, sub: str = "", color: str = "#10b981") -> str:
    return f"""
<div style="background:#0f111a; border:1px solid #1e293b; border-radius:8px;
            padding:18px 20px; text-align:center; margin-bottom:14px;">
    <div style="font-size:11px; color:#64748b; text-transform:uppercase;
                font-weight:700; letter-spacing:1px; margin-bottom:8px;">{label}</div>
    <div style="font-size:24px; font-weight:800; color:{color};
                font-family:'Consolas',monospace; line-height:1.2;">{value}</div>
    {"" if not sub else f'<div style="font-size:11px; color:#475569; margin-top:6px;">{sub}</div>'}
</div>"""

# ─── Ana Gövde (CID Stats) ────────────────────────────────────────────────────────
st.subheader("📊 CID Bazlı Stats & Dossier")

cid_input = st.text_input(
    "VATSIM CID Gir",
    placeholder="örn. 1863530",
    max_chars=10,
    key="premium_cid_input"
)

if not (cid_input and cid_input.strip().isdigit()):
    st.info("Yukarıya geçerli bir VATSIM CID girerek profili yükle.")
    st.stop()

s_cid = cid_input.strip()

with st.spinner("📡 VATSIM API'ye bağlanılıyor..."):
    s_details  = fetch_vatsim_endpoint(f"members/{s_cid}")
    s_stats    = fetch_vatsim_endpoint(f"members/{s_cid}/stats")
    s_fplans   = fetch_vatsim_endpoint(f"members/{s_cid}/flightplans")
    atc_raw    = fetch_vatsim_endpoint(f"members/{s_cid}/atcsessions?limit=200")

    if isinstance(atc_raw, dict):
        s_atcsess = atc_raw.get("items", atc_raw.get("results", []))
    else:
        s_atcsess = atc_raw if isinstance(atc_raw, list) else []

    # Canlı feed'de bu pilot online mı? Rating doğrulaması için
    live_pilot = find_pilot_live(s_cid)

if not s_details:
    st.error(f"❌ CID {s_cid} VATSIM kayıtlarında bulunamadı.")
    st.stop()

# ─── Profil Verileri ──────────────────────────────────────────────────────────────
s_name_first  = s_details.get("name_first", "")
s_name_last   = s_details.get("name_last", "")
s_full_name   = f"{s_name_first} {s_name_last}".strip() or f"CID {s_cid}"
s_reg_date    = str(s_details.get("reg_date", ""))[:10]
s_division    = s_details.get("division_id", "N/A")
s_region      = s_details.get("region_id", "N/A")

# Rating: önce live feed'e bak (online pilot), yoksa API v2'den al
if live_pilot:
    raw_rating       = live_pilot.get("rating", s_details.get("rating", 0))
    raw_pilot_rating = live_pilot.get("pilot_rating", s_details.get("pilotrating", 0))
else:
    raw_rating       = s_details.get("rating", 0)
    raw_pilot_rating = s_details.get("pilotrating", 0)

raw_mil_rating  = s_details.get("militaryrating", 0)

s_atc_label    = ATC_RATINGS.get(int(raw_rating), f"Rating {raw_rating}")
s_pilot_label  = decode_pilot_rating(raw_pilot_rating)
s_mil_label    = MILITARY_RATINGS.get(int(raw_mil_rating), "None")

# Real-life rating alanı (VATSIM API v2'de "vatsim_details" veya "real_name" altında olabilir)
# Bazı profillerde "real_name" field'ı gerçek pilot ratingini içerir — API döndürmüyorsa N/A
s_real_rating  = s_details.get("real_name", s_details.get("vatsim_details", {}).get("real_name", None))
# real_name aslında kişinin adı — real-life rating ayrı bir field değil VATSIM'de
# Wireframe'deki "Real Life Rating" → VATSIM'deki pilot_rating zaten bunu temsil ediyor (PPL, IR vs)
# Yani s_pilot_label'ı "Real Life Rating" olarak göstereceğiz

# Stats
s_pilot_mins = (s_stats or {}).get("pilot", 0)
s_atc_mins   = (s_stats or {}).get("atc", 0)

# ─── Üst Profil Kartı ─────────────────────────────────────────────────────────────
online_badge = ""
if live_pilot:
    cs = live_pilot.get("callsign", "")
    online_badge = f'<span style="background:#064e3b;color:#34d399;border:1px solid #059669;padding:4px 10px;border-radius:4px;font-size:11px;font-weight:bold;font-family:monospace;margin-left:10px;">🟢 ONLINE — {cs}</span>'

mil_badge = ""
if raw_mil_rating and int(raw_mil_rating) > 0:
    mil_badge = f'<span style="background:#2d1b4e;color:#a78bfa;border:1px solid #a78bfa40;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">MIL: {s_mil_label}</span>'

st.markdown(f"""
<div style="background:linear-gradient(135deg,#0f172a 0%,#111827 100%);
            border:1px solid #1e293b; border-left:5px solid #3b82f6;
            border-radius:10px; padding:24px; margin-bottom:24px;
            box-shadow:0 4px 15px rgba(0,0,0,0.3);">
    <div style="font-size:28px; font-weight:800; color:#f8fafc; margin-bottom:4px; letter-spacing:0.5px;">
        {s_full_name}{online_badge}
    </div>
    <div style="font-size:13px; color:#94a3b8; font-family:monospace; margin-bottom:18px;">
        🎯 CID: {s_cid} &nbsp;|&nbsp; 🌍 {s_region} / {s_division} &nbsp;|&nbsp; 📅 Kayıt: {s_reg_date}
    </div>
    <div style="display:flex; gap:10px; flex-wrap:wrap;">
        <span style="background:#172554;color:#60a5fa;border:1px solid #2563eb40;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">ATC: {s_atc_label}</span>
        <span style="background:#1c1917;color:#fbbf24;border:1px solid #d97706;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">Real Life / Pilot: {s_pilot_label}</span>
        {mil_badge}
    </div>
</div>
""", unsafe_allow_html=True)

# ─── Özet Metrik Kartları (4'lü) ──────────────────────────────────────────────────
sc1, sc2, sc3, sc4 = st.columns(4)
with sc1: st.markdown(stat_card("Pilot Saati", format_hours(s_pilot_mins), f"{s_pilot_mins} dk"), unsafe_allow_html=True)
with sc2: st.markdown(stat_card("ATC Saati",   format_hours(s_atc_mins),   f"{s_atc_mins} dk", "#3b82f6"), unsafe_allow_html=True)
with sc3: st.markdown(stat_card("Kayıtlı Uçuş", str(len(s_fplans) if s_fplans else 0), "Son 50 kayıt", "#f59e0b"), unsafe_allow_html=True)
with sc4: st.markdown(stat_card("ATC Oturum",  str(len(s_atcsess)),        "Son 200 kayıt", "#8b5cf6"), unsafe_allow_html=True)

st.markdown("---")

# ─── UÇUŞ VERİLERİ ANALİZİ ────────────────────────────────────────────────────────
if not s_fplans:
    st.info("Bu pilot için kayıtlı uçuş planı verisi bulunamadı.")
else:
    df_fp = pd.DataFrame(s_fplans)
    df_fp["duration_min"]   = df_fp.get("hrsenroute", pd.Series(dtype=int)).fillna(0) * 60 \
                            + df_fp.get("minenroute",  pd.Series(dtype=int)).fillna(0)
    df_fp["aircraft_short"] = df_fp.get("aircraft", pd.Series(dtype=str)).apply(prettify_aircraft)
    df_fp["manufacturer"]   = df_fp["aircraft_short"].apply(manufacturer_of)
    df_fp["dep"]            = df_fp.get("dep", pd.Series(dtype=str)).fillna("???").str.upper()
    df_fp["arr"]            = df_fp.get("arr", pd.Series(dtype=str)).fillna("???").str.upper()
    df_fp["route_str"]      = df_fp["dep"] + "→" + df_fp["arr"]
    df_fp["filed_dt"]       = pd.to_datetime(df_fp.get("filed"), errors="coerce", utc=True)

    all_routes_list = df_fp["route_str"].tolist()

    # Tarih bazlı filtre seçeneği (üst bar)
    # Ay/Yıl filtresi
    filter_col1, filter_col2 = st.columns([0.5, 0.5])
    with filter_col1:
        time_range = st.radio(
            "Zaman Aralığı",
            ["Tümü", "Son 1 Ay", "Son 6 Ay", "Bu Yıl"],
            horizontal=True,
            key="stats_time_range"
        )
    with filter_col2:
        now_utc = datetime.now(timezone.utc)
        if time_range == "Son 1 Ay":
            cutoff = now_utc.replace(month=now_utc.month - 1 if now_utc.month > 1 else 12,
                                     year=now_utc.year if now_utc.month > 1 else now_utc.year - 1)
        elif time_range == "Son 6 Ay":
            m = now_utc.month - 6
            y = now_utc.year
            if m <= 0: m += 12; y -= 1
            cutoff = now_utc.replace(month=m, year=y)
        elif time_range == "Bu Yıl":
            cutoff = now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff = None

    if cutoff and "filed_dt" in df_fp.columns:
        df_filtered = df_fp[df_fp["filed_dt"] >= cutoff].copy()
    else:
        df_filtered = df_fp.copy()

    st.caption(f"Gösterilen: {len(df_filtered)} uçuş  |  Toplam kayıt: {len(df_fp)}")

    # ── Panel 1: Uçuş İstatistikleri + Panel 2: Üretici Bazlı ────────────────────
    pan1, pan2 = st.columns(2)

    with pan1:
        st.markdown("#### ✈️ Uçuş İstatistikleri")

        total_nm_approx = df_filtered["duration_min"].sum() * 8  # ~8 NM/dk kaba tahmin
        avg_dur = df_filtered[df_filtered["duration_min"] > 0]["duration_min"].mean() if len(df_filtered) > 0 else 0

        first_flight = df_fp["filed_dt"].min()
        last_flight  = df_fp["filed_dt"].max()
        fmt = "%d %b %Y"
        val_first = first_flight.strftime(fmt) if pd.notna(first_flight) else "N/A"
        val_last  = last_flight.strftime(fmt)  if pd.notna(last_flight)  else "N/A"

        st.markdown(f"""
<div style="background:#0f111a; border:1px solid #1e293b; border-radius:8px; padding:16px; margin-bottom:10px;">
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
        <div>
            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; margin-bottom:4px;">İlk Uçuş</div>
            <div style="color:#f8fafc; font-family:monospace; font-size:14px;">{val_first}</div>
        </div>
        <div>
            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; margin-bottom:4px;">Son Uçuş</div>
            <div style="color:#3b82f6; font-family:monospace; font-size:14px;">{val_last}</div>
        </div>
        <div>
            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; margin-bottom:4px;">Toplam Uçuş</div>
            <div style="color:#10b981; font-family:monospace; font-size:18px; font-weight:800;">{len(df_filtered)}</div>
        </div>
        <div>
            <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; margin-bottom:4px;">Ort. Süre</div>
            <div style="color:#f59e0b; font-family:monospace; font-size:18px; font-weight:800;">{int(avg_dur)} dk</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

        # Aylık uçuş grafiği
        if "filed_dt" in df_filtered.columns and not df_filtered["filed_dt"].isna().all():
            df_monthly = df_filtered.copy()
            df_monthly["month"] = df_monthly["filed_dt"].dt.to_period("M").astype(str)
            monthly_counts = df_monthly.groupby("month").size().reset_index(name="count")
            fig_monthly = px.bar(
                monthly_counts, x="month", y="count",
                color="count",
                color_continuous_scale=[[0, "#1e3a8a"], [1, "#3b82f6"]],
                template="plotly_dark",
                labels={"month": "", "count": "Uçuş"}
            )
            fig_monthly.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=10, b=0), height=200,
                showlegend=False, coloraxis_showscale=False,
                xaxis=dict(title="", tickangle=-45, tickfont=dict(size=9)),
                yaxis=dict(title="", gridcolor="#1e293b")
            )
            fig_monthly.update_traces(marker_line_width=0, opacity=0.9)
            st.plotly_chart(fig_monthly, use_container_width=True)

    with pan2:
        st.markdown("#### 🏭 Üretici Bazlı Fleet")

        # Üretici filtresi için slider / seçim
        mfr_counts = df_filtered["manufacturer"].value_counts()
        top_mfrs = mfr_counts.head(8).reset_index()
        top_mfrs.columns = ["Üretici", "Uçuş"]

        fig_mfr = px.pie(
            top_mfrs, names="Üretici", values="Uçuş",
            color_discrete_sequence=px.colors.qualitative.Bold,
            template="plotly_dark", hole=0.4
        )
        fig_mfr.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0), height=220,
            legend=dict(font=dict(color="#94a3b8", size=11), bgcolor="rgba(0,0,0,0)")
        )
        st.plotly_chart(fig_mfr, use_container_width=True)

        # ICAO tipi detayı
        st.markdown("**ICAO Tipi Dağılımı** (Top 8)")
        ac_counts = df_filtered["aircraft_short"].value_counts().head(8).reset_index()
        ac_counts.columns = ["Uçak (ICAO)", "Uçuş"]

        fig_ac = px.bar(
            ac_counts, x="Uçuş", y="Uçak (ICAO)", orientation="h",
            color="Uçuş",
            color_continuous_scale=[[0, "#1e3a8a"], [1, "#3b82f6"]],
            template="plotly_dark"
        )
        fig_ac.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=5, b=0), height=200,
            showlegend=False, coloraxis_showscale=False,
            yaxis=dict(autorange="reversed", title="", tickfont=dict(size=11)),
            xaxis=dict(title="", gridcolor="#1e293b")
        )
        fig_ac.update_traces(marker_line_width=0, opacity=0.9)
        st.plotly_chart(fig_ac, use_container_width=True)

    st.markdown("---")

    # ── Panel 3: Saat ve NM sıralaması ───────────────────────────────────────────
    st.markdown("#### ⏱️ En Uzun Uçuşlar")

    dur_filter_col1, dur_filter_col2 = st.columns([0.3, 0.7])
    with dur_filter_col1:
        dur_min_hours = st.slider(
            "Min. süre (saat)",
            min_value=0, max_value=12, value=0, step=1,
            key="stats_dur_min"
        )
    with dur_filter_col2:
        show_n_flights = st.slider(
            "Gösterilecek uçuş sayısı",
            min_value=5, max_value=30, value=15, step=5,
            key="stats_show_n"
        )

    df_dur = df_filtered[df_filtered["duration_min"] >= dur_min_hours * 60].copy()
    df_dur = df_dur[df_dur["duration_min"] > 0].sort_values("duration_min", ascending=False).head(show_n_flights)
    df_dur["label"] = df_dur["route_str"] + " (" + df_dur["aircraft_short"] + ")"
    df_dur["saat_dk"] = df_dur["duration_min"].apply(lambda m: f"{m//60}h {m%60:02d}m")

    if len(df_dur) > 0:
        fig_dur = px.bar(
            df_dur, x="duration_min", y="label", orientation="h",
            color="duration_min",
            color_continuous_scale=[[0, "#064e3b"], [1, "#10b981"]],
            template="plotly_dark",
            custom_data=["saat_dk"]
        )
        fig_dur.update_traces(
            hovertemplate="%{y}<br>Süre: %{customdata[0]}<extra></extra>",
            marker_line_width=0, opacity=0.9
        )
        fig_dur.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=5, b=0),
            height=max(250, len(df_dur) * 28),
            showlegend=False, coloraxis_showscale=False,
            yaxis=dict(autorange="reversed", title="", tickfont=dict(size=11)),
            xaxis=dict(title="Süre (Dakika)", gridcolor="#1e293b")
        )
        st.plotly_chart(fig_dur, use_container_width=True)
    else:
        st.info("Bu süre filtresinde uçuş bulunamadı.")

    st.markdown("---")

    # ── Panel 4: En Çok Uçulan Rotalar + İlginç Rota ──────────────────────────────
    rota_col1, rota_col2 = st.columns([1, 1])

    with rota_col1:
        st.markdown("#### 🧭 En Çok Uçulan Rotalar")
        route_counts = Counter(df_filtered["route_str"].tolist())

        routes_html = ""
        for route, count in route_counts.most_common(8):
            parts = route.split("→")
            dep_r = parts[0] if len(parts) > 0 else "???"
            arr_r = parts[1] if len(parts) > 1 else "???"
            pct   = round(count / max(len(df_filtered), 1) * 100, 1)
            bar_w = min(100, pct * 3)
            routes_html += f"""
<div style="background:#0f111a; border:1px solid #1e293b; border-left:3px solid #3b82f6;
            border-radius:6px; padding:10px 14px; margin-bottom:6px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
        <span style="font-family:monospace; font-size:14px; font-weight:bold; color:#f8fafc;">
            <span style="color:#60a5fa;">{dep_r}</span>
            <span style="color:#475569; margin:0 4px;">✈</span>
            <span style="color:#60a5fa;">{arr_r}</span>
        </span>
        <span style="background:#064e3b; color:#34d399; padding:2px 8px;
                     border-radius:4px; font-size:12px; font-weight:bold;">{count}×</span>
    </div>
    <div style="height:3px; background:#1e293b; border-radius:2px;">
        <div style="height:3px; width:{bar_w}%; background:linear-gradient(90deg,#1d4ed8,#3b82f6);
                    border-radius:2px;"></div>
    </div>
</div>"""
        st.markdown(routes_html, unsafe_allow_html=True)

    with rota_col2:
        st.markdown("#### 🌍 En İlginç Rota (Nadir)")

        df_unique = df_filtered.copy()
        df_unique["uniqueness"] = df_unique["route_str"].apply(
            lambda r: unique_route_score(r.split("→")[0], r.split("→")[1] if "→" in r else "???", all_routes_list)
        )
        # Sadece bir kez uçulmuş (veya çok az), en uzun süreli olanı göster
        df_rare = df_unique[df_unique["duration_min"] > 30].sort_values(
            ["uniqueness", "duration_min"], ascending=[False, False]
        ).head(5)

        if len(df_rare) > 0:
            rare_html = ""
            for _, row in df_rare.iterrows():
                parts = row["route_str"].split("→")
                dep_r = parts[0] if len(parts) > 0 else "???"
                arr_r = parts[1] if len(parts) > 1 else "???"
                dur_str = f"{int(row['duration_min'])//60}h {int(row['duration_min'])%60:02d}m"
                rare_html += f"""
<div style="background:#0f111a; border:1px solid #1e293b; border-left:3px solid #f59e0b;
            border-radius:6px; padding:10px 14px; margin-bottom:6px;">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-family:monospace; font-size:14px; font-weight:bold; color:#f8fafc;">
            <span style="color:#fbbf24;">{dep_r}</span>
            <span style="color:#475569; margin:0 4px;">✈</span>
            <span style="color:#fbbf24;">{arr_r}</span>
        </span>
        <span style="color:#94a3b8; font-size:12px; font-family:monospace;">{row['aircraft_short']} · {dur_str}</span>
    </div>
</div>"""
            st.markdown(rare_html, unsafe_allow_html=True)
        else:
            st.info("Filtreli veri setinde nadir rota analizi için yeterli veri yok.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### ✈️ En Çok Uçulan Uçak & Firma")
        top_ac   = df_filtered["aircraft_short"].value_counts().idxmax() if len(df_filtered) > 0 else "N/A"
        top_mfr  = df_filtered["manufacturer"].value_counts().idxmax()   if len(df_filtered) > 0 else "N/A"
        top_ac_cnt = df_filtered["aircraft_short"].value_counts().max()  if len(df_filtered) > 0 else 0

        st.markdown(f"""
<div style="background:#0f111a; border:1px solid #1e293b; border-radius:8px; padding:16px; margin-bottom:8px;">
    <div style="font-size:12px; color:#64748b; text-transform:uppercase; font-weight:700; margin-bottom:8px;">Favori Uçak</div>
    <div style="font-size:22px; font-weight:800; color:#10b981; font-family:monospace;">{top_ac}</div>
    <div style="font-size:12px; color:#475569; margin-top:4px;">{top_mfr} · {top_ac_cnt} uçuş</div>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

# ─── ATC SEKTÖR ANALİZİ (ATC rating varsa) ────────────────────────────────────────
if s_atc_mins > 0 and s_atcsess:
    st.markdown("#### 🎧 ATC Sektör Mastery")

    df_atc = pd.DataFrame(s_atcsess)

    # Ay/Yıl filtresi ATC için
    atc_period = st.radio(
        "ATC Dönem Filtresi",
        ["Tümü", "Bu Yıl", "Son 6 Ay"],
        horizontal=True, key="atc_period"
    )

    if "start" in df_atc.columns:
        df_atc["start_dt"] = pd.to_datetime(df_atc["start"], errors="coerce", utc=True)
        now_utc = datetime.now(timezone.utc)
        if atc_period == "Bu Yıl":
            df_atc = df_atc[df_atc["start_dt"] >= now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)]
        elif atc_period == "Son 6 Ay":
            m = now_utc.month - 6
            y = now_utc.year
            if m <= 0: m += 12; y -= 1
            df_atc = df_atc[df_atc["start_dt"] >= now_utc.replace(month=m, year=y)]

    atc_panel1, atc_panel2 = st.columns(2)

    with atc_panel1:
        if "callsign" in df_atc.columns:
            atc_cnt = df_atc["callsign"].value_counts().head(12).reset_index()
            atc_cnt.columns = ["Pozisyon", "Oturum"]

            fig_atc = px.bar(
                atc_cnt, x="Oturum", y="Pozisyon", orientation="h",
                color="Oturum",
                color_continuous_scale=[[0, "#312e81"], [1, "#6366f1"]],
                template="plotly_dark"
            )
            fig_atc.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=5, b=0), height=350,
                showlegend=False, coloraxis_showscale=False,
                yaxis=dict(autorange="reversed", title="", tickfont=dict(size=11)),
                xaxis=dict(title="Oturum Sayısı", gridcolor="#1e293b")
            )
            fig_atc.update_traces(marker_line_width=0, opacity=0.9)
            st.plotly_chart(fig_atc, use_container_width=True)

    with atc_panel2:
        # Sektör tipi dağılımı (_GND, _TWR, _APP, _CTR vs)
        if "callsign" in df_atc.columns:
            def extract_sector_type(cs: str) -> str:
                cs = str(cs).upper()
                if "_CTR" in cs: return "CTR (Radar)"
                if "_APP" in cs: return "APP"
                if "_TWR" in cs: return "TWR"
                if "_GND" in cs: return "GND"
                if "_DEL" in cs: return "DEL"
                if "_FSS" in cs: return "FSS"
                return "Diğer"

            df_atc["sector_type"] = df_atc["callsign"].apply(extract_sector_type)
            type_counts = df_atc["sector_type"].value_counts().reset_index()
            type_counts.columns = ["Tip", "Oturum"]

            fig_type = px.pie(
                type_counts, names="Tip", values="Oturum",
                color_discrete_sequence=["#6366f1", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"],
                template="plotly_dark", hole=0.4,
                title="Sektör Tipi Dağılımı"
            )
            fig_type.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0), height=300,
                legend=dict(font=dict(color="#94a3b8", size=11), bgcolor="rgba(0,0,0,0)"),
                title_font_color="#94a3b8", title_font_size=13
            )
            st.plotly_chart(fig_type, use_container_width=True)

    st.markdown("---")

elif s_atc_mins == 0:
    st.info("Bu CID için ATC aktivitesi kaydı yok.")

# ─── LEADERBOARD ROZET (Phase 3 — "KESIN DEGİL" bölümü) ──────────────────────────
# Basit sıralama: toplam saat bazlı global rank hesaplanamaz
# (tüm üyeler çekilmeden) — placeholder olarak göster
st.markdown("#### 🏅 Global Sıralama (Yakında)")
rank_col1, rank_col2 = st.columns(2)
with rank_col1:
    pilot_rank_placeholder = "—"
    st.markdown(f"""
<div style="background:#0f111a; border:1px solid #1e293b; border-radius:8px; padding:16px; text-align:center;">
    <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; margin-bottom:8px;">Pilot Sıralaması</div>
    <div style="font-size:32px; font-weight:800; color:#f59e0b; font-family:'Consolas',monospace;">#—</div>
    <div style="font-size:12px; color:#475569; margin-top:6px;">{format_hours(s_pilot_mins)} pilot saati</div>
</div>
""", unsafe_allow_html=True)
with rank_col2:
    st.markdown(f"""
<div style="background:#0f111a; border:1px solid #1e293b; border-radius:8px; padding:16px; text-align:center;">
    <div style="font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; margin-bottom:8px;">ATC Sıralaması</div>
    <div style="font-size:32px; font-weight:800; color:#6366f1; font-family:'Consolas',monospace;">#—</div>
    <div style="font-size:12px; color:#475569; margin-top:6px;">{format_hours(s_atc_mins)} ATC saati</div>
</div>
""", unsafe_allow_html=True)