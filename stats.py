import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from collections import Counter
from datetime import datetime, timezone

# ─── API & Sabitler ───────────────────────────────────────────────────────────
VATSIM_CORE_API = "https://api.vatsim.net/v2"
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"

ATC_RATINGS = {
    -1: "Inactive", 0: "OBS", 1: "S1", 2: "S2", 3: "S3",
    4: "C1", 5: "C2", 6: "C3", 7: "I1", 8: "I2", 9: "I3",
    10: "SUP", 11: "ADM"
}
MILITARY_RATINGS = {0: "None", 1: "M1", 2: "M2", 3: "M3"}

def decode_pilot_rating(value):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return "P0 — OBS"
    if v >= 63: return "P6 — Ferry Pilot"
    if v >= 31: return "P5 — CTP"
    if v >= 15: return "P4 — ATP"
    if v >= 7:  return "P3 — CMEL"
    if v >= 3:  return "P2 — IR"
    if v >= 1:  return "P1 — PPL"
    return "P0 — OBS"

http_session = requests.Session()

def _api_headers():
    key = st.secrets.get("VATSIM_API_KEY", "")
    h = {"User-Agent": "VatScore/2.0"}
    if key:
        h["X-API-Key"] = key
    return h

# ─── Fetch fonksiyonları ──────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def fetch_endpoint(endpoint: str):
    try:
        r = http_session.get(
            f"{VATSIM_CORE_API}/{endpoint}",
            headers=_api_headers(),
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
        st.warning(f"API yanıtı: {r.status_code} — {endpoint}", icon="⚠️")
    except Exception as e:
        st.warning(f"Bağlantı hatası: {e}", icon="⚠️")
    return None

@st.cache_data(ttl=30, show_spinner=False)
def fetch_live_data():
    try:
        r = http_session.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def find_live_pilot(cid: str):
    data = fetch_live_data()
    if not data:
        return None
    for p in data.get("pilots", []):
        if str(p.get("cid", "")) == cid:
            return p
    return None

# ─── Yardımcılar ──────────────────────────────────────────────────────────────
def fmt_hours(minutes):
    try:
        m = int(float(minutes))
    except (ValueError, TypeError):
        m = 0
    return f"{m // 60}h {m % 60:02d}m"

def icao_type(raw):
    if not raw:
        return "Unknown"
    return raw.split("/")[0].strip().upper()

def manufacturer(t: str) -> str:
    t = t.upper()
    if t[:2] in ("A3", "A2", "A1", "A0") or t.startswith("A"[:1]) and t[1:2].isdigit():
        if t.startswith(("A3", "A2", "A1", "A0", "A35", "A38", "A32", "A31", "A30")):
            return "Airbus"
    if t.startswith(("B73", "B74", "B75", "B76", "B77", "B78", "B72", "B71",
                      "737", "747", "757", "767", "777", "787")):
        return "Boeing"
    if t.startswith(("E17", "E19", "E75", "E55", "E50", "ERJ", "E13", "E14")):
        return "Embraer"
    if t.startswith(("CRJ", "CR2", "CR7", "CR9", "CRK", "DH8", "DHC", "Q40")):
        return "Bombardier/ATR"
    if t.startswith(("MD8", "MD9", "MD1", "DC9", "DC8")):
        return "McDonnell Douglas"
    if t.startswith(("C17", "C13", "C5 ")):
        return "Lockheed"
    if t.startswith(("GL5", "GL6", "GL7", "LJ", "CL6", "C56", "C68", "FA7", "F2T")):
        return "Business Jet"
    if t.startswith(("C17", "C17", "C17", "C17")):
        return "Lockheed"
    return "Airbus" if t.startswith("A") else "Boeing" if t.startswith("B") else "Other"

def stat_card(label, value, sub="", color="#10b981"):
    return f"""
<div style="background:#0f111a;border:1px solid #1e293b;border-radius:8px;
            padding:18px 20px;text-align:center;margin-bottom:14px;">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;
              font-weight:700;letter-spacing:1px;margin-bottom:8px;">{label}</div>
  <div style="font-size:24px;font-weight:800;color:{color};
              font-family:'Consolas',monospace;line-height:1.2;">{value}</div>
  {"" if not sub else f'<div style="font-size:11px;color:#475569;margin-top:6px;">{sub}</div>'}
</div>"""

# ─── ANA SAYFA ────────────────────────────────────────────────────────────────
st.subheader("📊 CID Bazlı Stats & Dossier")

cid_input = st.text_input(
    "VATSIM CID Gir",
    placeholder="örn. 1863530",
    max_chars=10,
    key="cid_stats_input"
)

if not (cid_input and cid_input.strip().isdigit()):
    st.info("Geçerli bir VATSIM CID girerek profili yükle.")
    st.stop()

s_cid = cid_input.strip()

with st.spinner("📡 VATSIM Core API ile bağlantı kuruluyor..."):
    s_details = fetch_endpoint(f"members/{s_cid}")
    s_stats   = fetch_endpoint(f"members/{s_cid}/stats")
    s_fplans  = fetch_endpoint(f"members/{s_cid}/flightplans")
    atc_raw   = fetch_endpoint(f"members/{s_cid}/atcsessions?limit=200")
    live_p    = find_live_pilot(s_cid)

if isinstance(atc_raw, dict):
    s_atcsess = atc_raw.get("items", atc_raw.get("results", []))
elif isinstance(atc_raw, list):
    s_atcsess = atc_raw
else:
    s_atcsess = []

if not s_details:
    st.error(f"❌ CID {s_cid} VATSIM kayıtlarında bulunamadı veya API erişimi başarısız.")
    st.stop()

# ─── Profil verileri ──────────────────────────────────────────────────────────
s_name      = f"{s_details.get('name_first','')} {s_details.get('name_last','')}".strip() or f"CID {s_cid}"
s_reg_date  = str(s_details.get("reg_date", ""))[:10]
s_division  = s_details.get("division_id", "N/A")
s_region    = s_details.get("region_id", "N/A")

# Rating: live feed öncelikli (online pilot varsa daha güncel)
raw_atc_r   = live_p.get("rating", s_details.get("rating", 0)) if live_p else s_details.get("rating", 0)
raw_pilot_r = live_p.get("pilot_rating", s_details.get("pilotrating", 0)) if live_p else s_details.get("pilotrating", 0)
raw_mil_r   = s_details.get("militaryrating", 0)

atc_label   = ATC_RATINGS.get(int(raw_atc_r), f"Rating {raw_atc_r}")
pilot_label = decode_pilot_rating(raw_pilot_r)
mil_label   = MILITARY_RATINGS.get(int(raw_mil_r), "None")

pilot_mins  = (s_stats or {}).get("pilot", 0)
atc_mins    = (s_stats or {}).get("atc", 0)

# ─── Profil kartı ─────────────────────────────────────────────────────────────
online_badge = ""
if live_p:
    cs = live_p.get("callsign", "")
    online_badge = f' <span style="background:#064e3b;color:#34d399;border:1px solid #059669;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:bold;font-family:monospace;vertical-align:middle;">🟢 ONLINE — {cs}</span>'

mil_badge = ""
if int(raw_mil_r) > 0:
    mil_badge = f'<span style="background:#2d1b4e;color:#a78bfa;border:1px solid #a78bfa40;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">MIL: {mil_label}</span>'

st.markdown(f"""
<div style="background:linear-gradient(135deg,#0f172a 0%,#111827 100%);
            border:1px solid #1e293b;border-left:5px solid #3b82f6;
            border-radius:10px;padding:24px;margin-bottom:24px;
            box-shadow:0 4px 15px rgba(0,0,0,0.3);">
  <div style="font-size:26px;font-weight:800;color:#f8fafc;margin-bottom:4px;letter-spacing:0.5px;">
    {s_name}{online_badge}
  </div>
  <div style="font-size:13px;color:#94a3b8;font-family:monospace;margin-bottom:18px;">
    🎯 CID: {s_cid} &nbsp;|&nbsp; 🌍 {s_region} / {s_division} &nbsp;|&nbsp; 📅 Kayıt: {s_reg_date}
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;">
    <span style="background:#172554;color:#60a5fa;border:1px solid #2563eb40;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">ATC: {atc_label}</span>
    <span style="background:#1c1917;color:#fbbf24;border:1px solid #d97706;padding:5px 14px;border-radius:6px;font-size:12px;font-weight:bold;font-family:monospace;">Real Life / Pilot: {pilot_label}</span>
    {mil_badge}
  </div>
</div>
""", unsafe_allow_html=True)

# ─── Metrik kartlar ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
with c1: st.markdown(stat_card("Pilot Saati",   fmt_hours(pilot_mins),          f"{pilot_mins} dk"), unsafe_allow_html=True)
with c2: st.markdown(stat_card("ATC Saati",     fmt_hours(atc_mins),            f"{atc_mins} dk",     "#3b82f6"), unsafe_allow_html=True)
with c3: st.markdown(stat_card("Kayıtlı Uçuş", str(len(s_fplans) if s_fplans else 0), "Son 50 kayıt", "#f59e0b"), unsafe_allow_html=True)
with c4: st.markdown(stat_card("ATC Oturumu",  str(len(s_atcsess)),            "Son 200 kayıt",      "#8b5cf6"), unsafe_allow_html=True)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# UÇUŞ VERİLERİ
# ══════════════════════════════════════════════════════════════════════════════
if not s_fplans:
    st.info("Bu pilot için kayıtlı uçuş planı bulunamadı.")
else:
    df = pd.DataFrame(s_fplans)
    df["duration_min"]   = df.get("hrsenroute", pd.Series(dtype=int)).fillna(0) * 60 \
                         + df.get("minenroute",  pd.Series(dtype=int)).fillna(0)
    df["ac"]             = df.get("aircraft", pd.Series(dtype=str)).apply(icao_type)
    df["mfr"]            = df["ac"].apply(manufacturer)
    df["dep"]            = df.get("dep", pd.Series(dtype=str)).fillna("???").str.upper()
    df["arr"]            = df.get("arr", pd.Series(dtype=str)).fillna("???").str.upper()
    df["route"]          = df["dep"] + "→" + df["arr"]
    df["filed_dt"]       = pd.to_datetime(df.get("filed"), errors="coerce", utc=True)

    # ── Zaman filtresi ────────────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    tf_col, _ = st.columns([0.5, 0.5])
    with tf_col:
        time_range = st.radio(
            "Zaman Aralığı",
            ["Tümü", "Son 1 Ay", "Son 6 Ay", "Bu Yıl"],
            horizontal=True, key="stats_tf"
        )

    if time_range == "Son 1 Ay":
        m = now_utc.month - 1 or 12
        y = now_utc.year if now_utc.month > 1 else now_utc.year - 1
        cutoff = now_utc.replace(month=m, year=y)
    elif time_range == "Son 6 Ay":
        m = now_utc.month - 6
        y = now_utc.year
        if m <= 0: m += 12; y -= 1
        cutoff = now_utc.replace(month=m, year=y)
    elif time_range == "Bu Yıl":
        cutoff = now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        cutoff = None

    dff = df[df["filed_dt"] >= cutoff].copy() if cutoff is not None else df.copy()
    st.caption(f"Gösterilen: **{len(dff)}** uçuş  |  Toplam kayıt: **{len(df)}**")

    # ── Panel 1 + Panel 2 ─────────────────────────────────────────────────────
    p1, p2 = st.columns(2)

    # Panel 1 — Uçuş İstatistikleri
    with p1:
        st.markdown("#### ✈️ Uçuş İstatistikleri")
        first_f = df["filed_dt"].min()
        last_f  = df["filed_dt"].max()
        avg_dur = dff[dff["duration_min"] > 0]["duration_min"].mean() if len(dff) else 0
        fmt = "%d %b %Y"

        st.markdown(f"""
<div style="background:#0f111a;border:1px solid #1e293b;border-radius:8px;padding:16px;margin-bottom:10px;">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
    <div>
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;margin-bottom:4px;">İlk Uçuş</div>
      <div style="color:#f8fafc;font-family:monospace;font-size:13px;">{first_f.strftime(fmt) if pd.notna(first_f) else "N/A"}</div>
    </div>
    <div>
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;margin-bottom:4px;">Son Uçuş</div>
      <div style="color:#3b82f6;font-family:monospace;font-size:13px;">{last_f.strftime(fmt) if pd.notna(last_f) else "N/A"}</div>
    </div>
    <div>
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;margin-bottom:4px;">Toplam Uçuş</div>
      <div style="color:#10b981;font-family:monospace;font-size:22px;font-weight:800;">{len(dff)}</div>
    </div>
    <div>
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;margin-bottom:4px;">Ort. Süre</div>
      <div style="color:#f59e0b;font-family:monospace;font-size:22px;font-weight:800;">{int(avg_dur)} dk</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

        # Aylık uçuş grafiği
        if not dff["filed_dt"].isna().all():
            dm = dff.copy()
            dm["month"] = dm["filed_dt"].dt.to_period("M").astype(str)
            mc = dm.groupby("month").size().reset_index(name="count")
            fig_m = px.bar(mc, x="month", y="count",
                           color="count",
                           color_continuous_scale=[[0,"#1e3a8a"],[1,"#3b82f6"]],
                           template="plotly_dark",
                           labels={"month":"","count":"Uçuş"})
            fig_m.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=0,r=0,t=5,b=0),height=190,
                                showlegend=False,coloraxis_showscale=False,
                                xaxis=dict(tickangle=-45,tickfont=dict(size=9)),
                                yaxis=dict(gridcolor="#1e293b"))
            fig_m.update_traces(marker_line_width=0,opacity=0.9)
            st.plotly_chart(fig_m, use_container_width=True)

    # Panel 2 — Üretici + ICAO tipi
    with p2:
        st.markdown("#### 🏭 Fleet Dağılımı")
        mfr_counts = dff["mfr"].value_counts().head(8).reset_index()
        mfr_counts.columns = ["Üretici", "Uçuş"]
        fig_pie = px.pie(mfr_counts, names="Üretici", values="Uçuş",
                         color_discrete_sequence=px.colors.qualitative.Bold,
                         template="plotly_dark", hole=0.4)
        fig_pie.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                              margin=dict(l=0,r=0,t=0,b=0),height=200,
                              legend=dict(font=dict(color="#94a3b8",size=10),bgcolor="rgba(0,0,0,0)"))
        st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("**ICAO Tipi — Top 8**")
        ac_counts = dff["ac"].value_counts().head(8).reset_index()
        ac_counts.columns = ["Uçak","Uçuş"]
        fig_ac = px.bar(ac_counts, x="Uçuş", y="Uçak", orientation="h",
                        color="Uçuş",
                        color_continuous_scale=[[0,"#1e3a8a"],[1,"#3b82f6"]],
                        template="plotly_dark")
        fig_ac.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                             margin=dict(l=0,r=0,t=0,b=0),height=200,
                             showlegend=False,coloraxis_showscale=False,
                             yaxis=dict(autorange="reversed",title="",tickfont=dict(size=11)),
                             xaxis=dict(title="",gridcolor="#1e293b"))
        fig_ac.update_traces(marker_line_width=0,opacity=0.9)
        st.plotly_chart(fig_ac, use_container_width=True)

    st.markdown("---")

    # ── Panel 3 — En Uzun Uçuşlar ────────────────────────────────────────────
    st.markdown("#### ⏱️ En Uzun Uçuşlar")
    sl1, sl2 = st.columns([0.3, 0.7])
    with sl1:
        dur_min_h = st.slider("Min. süre (saat)", 0, 12, 0, key="dur_min")
    with sl2:
        show_n = st.slider("Gösterilecek uçuş", 5, 30, 15, step=5, key="show_n")

    df_dur = dff[dff["duration_min"] >= dur_min_h * 60].copy()
    df_dur = df_dur[df_dur["duration_min"] > 0].sort_values("duration_min", ascending=False).head(show_n)
    df_dur["label"]   = df_dur["route"] + " (" + df_dur["ac"] + ")"
    df_dur["hm"]      = df_dur["duration_min"].apply(lambda m: f"{int(m)//60}h {int(m)%60:02d}m")

    if len(df_dur):
        fig_dur = px.bar(df_dur, x="duration_min", y="label", orientation="h",
                         color="duration_min",
                         color_continuous_scale=[[0,"#064e3b"],[1,"#10b981"]],
                         template="plotly_dark", custom_data=["hm"])
        fig_dur.update_traces(hovertemplate="%{y}<br>Süre: %{customdata[0]}<extra></extra>",
                              marker_line_width=0, opacity=0.9)
        fig_dur.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                              margin=dict(l=0,r=0,t=5,b=0),
                              height=max(250, len(df_dur)*28),
                              showlegend=False,coloraxis_showscale=False,
                              yaxis=dict(autorange="reversed",title="",tickfont=dict(size=11)),
                              xaxis=dict(title="Süre (Dakika)",gridcolor="#1e293b"))
        st.plotly_chart(fig_dur, use_container_width=True)
    else:
        st.info("Bu süre filtresinde uçuş yok.")

    st.markdown("---")

    # ── Panel 4 — Rotalar + Favori + İlginç ──────────────────────────────────
    r1, r2 = st.columns(2)

    with r1:
        st.markdown("#### 🧭 En Çok Uçulan Rotalar")
        rc = Counter(dff["route"].tolist())
        html = ""
        for route, cnt in rc.most_common(8):
            parts = route.split("→")
            d = parts[0] if parts else "???"
            a = parts[1] if len(parts) > 1 else "???"
            bar_w = min(100, round(cnt / max(len(dff),1) * 300))
            html += f"""
<div style="background:#0f111a;border:1px solid #1e293b;border-left:3px solid #3b82f6;
            border-radius:6px;padding:10px 14px;margin-bottom:6px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-family:monospace;font-size:14px;font-weight:bold;color:#f8fafc;">
      <span style="color:#60a5fa;">{d}</span>
      <span style="color:#475569;margin:0 4px;">✈</span>
      <span style="color:#60a5fa;">{a}</span>
    </span>
    <span style="background:#064e3b;color:#34d399;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{cnt}×</span>
  </div>
  <div style="height:3px;background:#1e293b;border-radius:2px;">
    <div style="height:3px;width:{bar_w}%;background:linear-gradient(90deg,#1d4ed8,#3b82f6);border-radius:2px;"></div>
  </div>
</div>"""
        st.markdown(html, unsafe_allow_html=True)

    with r2:
        st.markdown("#### 🌍 En İlginç (Nadir) Rota")
        # Frekansı 1 olan en uzun süreli rota
        rc_all = Counter(dff["route"].tolist())
        df_rare = dff.copy()
        df_rare["freq"] = df_rare["route"].map(rc_all)
        df_rare = df_rare[df_rare["duration_min"] > 30].sort_values(
            ["freq", "duration_min"], ascending=[True, False]
        ).head(5)

        if len(df_rare):
            rare_html = ""
            for _, row in df_rare.iterrows():
                pts = row["route"].split("→")
                d2 = pts[0] if pts else "???"
                a2 = pts[1] if len(pts) > 1 else "???"
                hm = f"{int(row['duration_min'])//60}h {int(row['duration_min'])%60:02d}m"
                rare_html += f"""
<div style="background:#0f111a;border:1px solid #1e293b;border-left:3px solid #f59e0b;
            border-radius:6px;padding:10px 14px;margin-bottom:6px;">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span style="font-family:monospace;font-size:14px;font-weight:bold;">
      <span style="color:#fbbf24;">{d2}</span>
      <span style="color:#475569;margin:0 4px;">✈</span>
      <span style="color:#fbbf24;">{a2}</span>
    </span>
    <span style="color:#94a3b8;font-size:12px;font-family:monospace;">{row['ac']} · {hm}</span>
  </div>
</div>"""
            st.markdown(rare_html, unsafe_allow_html=True)
        else:
            st.info("Nadir rota analizi için yeterli veri yok.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### ✈️ Favori Uçak & Firma")
        if len(dff):
            top_ac  = dff["ac"].value_counts().idxmax()
            top_mfr = dff["mfr"].value_counts().idxmax()
            top_cnt = int(dff["ac"].value_counts().max())
            st.markdown(f"""
<div style="background:#0f111a;border:1px solid #1e293b;border-radius:8px;padding:16px;">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;margin-bottom:8px;">En Çok Uçulan</div>
  <div style="font-size:24px;font-weight:800;color:#10b981;font-family:monospace;">{top_ac}</div>
  <div style="font-size:12px;color:#475569;margin-top:4px;">{top_mfr} · {top_cnt} uçuş</div>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ATC SEKTÖR ANALİZİ
# ══════════════════════════════════════════════════════════════════════════════
if atc_mins > 0 and s_atcsess:
    st.markdown("#### 🎧 ATC Sektör Mastery")

    df_atc = pd.DataFrame(s_atcsess)

    # Dönem filtresi
    atc_tf = st.radio("ATC Dönem", ["Tümü","Bu Yıl","Son 6 Ay"],
                      horizontal=True, key="atc_tf")
    if "start" in df_atc.columns:
        df_atc["start_dt"] = pd.to_datetime(df_atc["start"], errors="coerce", utc=True)
        now_utc = datetime.now(timezone.utc)
        if atc_tf == "Bu Yıl":
            df_atc = df_atc[df_atc["start_dt"] >= now_utc.replace(month=1,day=1,hour=0,minute=0,second=0,microsecond=0)]
        elif atc_tf == "Son 6 Ay":
            m = now_utc.month - 6; y = now_utc.year
            if m <= 0: m += 12; y -= 1
            df_atc = df_atc[df_atc["start_dt"] >= now_utc.replace(month=m,year=y)]

    a1, a2 = st.columns(2)
    with a1:
        if "callsign" in df_atc.columns:
            atc_cnt = df_atc["callsign"].value_counts().head(12).reset_index()
            atc_cnt.columns = ["Pozisyon","Oturum"]
            fig_atc = px.bar(atc_cnt, x="Oturum", y="Pozisyon", orientation="h",
                             color="Oturum",
                             color_continuous_scale=[[0,"#312e81"],[1,"#6366f1"]],
                             template="plotly_dark")
            fig_atc.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                  margin=dict(l=0,r=0,t=5,b=0),height=350,
                                  showlegend=False,coloraxis_showscale=False,
                                  yaxis=dict(autorange="reversed",title="",tickfont=dict(size=11)),
                                  xaxis=dict(title="Oturum",gridcolor="#1e293b"))
            fig_atc.update_traces(marker_line_width=0,opacity=0.9)
            st.plotly_chart(fig_atc, use_container_width=True)

    with a2:
        if "callsign" in df_atc.columns:
            def stype(cs):
                cs = str(cs).upper()
                if "_CTR" in cs: return "CTR"
                if "_APP" in cs: return "APP"
                if "_TWR" in cs: return "TWR"
                if "_GND" in cs: return "GND"
                if "_DEL" in cs: return "DEL"
                if "_FSS" in cs: return "FSS"
                return "Diğer"
            df_atc["tip"] = df_atc["callsign"].apply(stype)
            tc = df_atc["tip"].value_counts().reset_index()
            tc.columns = ["Tip","Oturum"]
            fig_tp = px.pie(tc, names="Tip", values="Oturum",
                            color_discrete_sequence=["#6366f1","#3b82f6","#10b981","#f59e0b","#ef4444","#8b5cf6"],
                            template="plotly_dark", hole=0.4, title="Sektör Tipi")
            fig_tp.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                 margin=dict(l=0,r=0,t=30,b=0),height=300,
                                 legend=dict(font=dict(color="#94a3b8",size=11),bgcolor="rgba(0,0,0,0)"),
                                 title_font_color="#94a3b8",title_font_size=13)
            st.plotly_chart(fig_tp, use_container_width=True)

    st.markdown("---")

# ── Leaderboard rozeti (Phase 3 placeholder) ──────────────────────────────────
st.markdown("#### 🏅 Global Sıralama")
lb1, lb2 = st.columns(2)
with lb1:
    st.markdown(f"""
<div style="background:#0f111a;border:1px solid #1e293b;border-radius:8px;padding:16px;text-align:center;">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;margin-bottom:8px;">Pilot Sıralaması</div>
  <div style="font-size:32px;font-weight:800;color:#f59e0b;font-family:'Consolas',monospace;">#—</div>
  <div style="font-size:12px;color:#475569;margin-top:6px;">{fmt_hours(pilot_mins)} pilot saati</div>
</div>
""", unsafe_allow_html=True)
with lb2:
    st.markdown(f"""
<div style="background:#0f111a;border:1px solid #1e293b;border-radius:8px;padding:16px;text-align:center;">
  <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;margin-bottom:8px;">ATC Sıralaması</div>
  <div style="font-size:32px;font-weight:800;color:#6366f1;font-family:'Consolas',monospace;">#—</div>
  <div style="font-size:12px;color:#475569;margin-top:6px;">{fmt_hours(atc_mins)} ATC saati</div>
</div>
""", unsafe_allow_html=True)