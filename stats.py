import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════════════════════════════════════════
#  API SABİTLERİ
# ══════════════════════════════════════════════════════════════════════════════
STATSIM_API   = "https://api.statsim.net/api"          # geçmiş veri (flights + atc)
VATSIM_CORE   = "https://api.vatsim.net/v2"            # rating + isim + saat
VATSIM_DATA   = "https://data.vatsim.net/v3/vatsim-data.json"  # live feed

# Tüm geçmişi kapsayacak tarih aralığı (statsim from/to zorunlu istiyor)
HISTORY_FROM  = "2015-01-01T00:00:00Z"

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
        return "P0"
    if v >= 63: return "P6 · Ferry"
    if v >= 31: return "P5 · CTP"
    if v >= 15: return "P4 · ATP"
    if v >= 7:  return "P3 · CMEL"
    if v >= 3:  return "P2 · IR"
    if v >= 1:  return "P1 · PPL"
    return "P0 · New"

http = requests.Session()

def _statsim_headers():
    key = st.secrets.get("STATSIM_API_KEY", st.secrets.get("VATSIM_API_KEY", ""))
    return {"X-API-Key": key, "accept": "application/json", "User-Agent": "VatScore/3.0"}

def _vatsim_headers():
    key = st.secrets.get("VATSIM_API_KEY", "")
    h = {"User-Agent": "VatScore/3.0"}
    if key:
        h["X-API-Key"] = key
    return h

# ══════════════════════════════════════════════════════════════════════════════
#  FETCH
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def statsim_flights(cid: str):
    now = datetime.now(timezone.utc).isoformat()
    try:
        r = http.get(f"{STATSIM_API}/Flights/VatsimId",
                     params={"vatsimId": cid, "from": HISTORY_FROM, "to": now},
                     headers=_statsim_headers(), timeout=25)
        if r.status_code == 200:
            return r.json()
        st.session_state["_flights_err"] = f"{r.status_code}"
    except Exception as e:
        st.session_state["_flights_err"] = str(e)
    return []

@st.cache_data(ttl=600, show_spinner=False)
def statsim_atc(cid: str):
    now = datetime.now(timezone.utc).isoformat()
    try:
        r = http.get(f"{STATSIM_API}/Atcsessions/VatsimId",
                     params={"vatsimId": cid, "from": HISTORY_FROM, "to": now},
                     headers=_statsim_headers(), timeout=25)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

@st.cache_data(ttl=300, show_spinner=False)
def vatsim_member(cid: str):
    out = {}
    for ep in ("", "/stats"):
        try:
            r = http.get(f"{VATSIM_CORE}/members/{cid}{ep}",
                         headers=_vatsim_headers(), timeout=10)
            if r.status_code == 200:
                out[ep or "details"] = r.json()
        except Exception:
            pass
    return out

@st.cache_data(ttl=30, show_spinner=False)
def live_pilot(cid: str):
    try:
        r = http.get(VATSIM_DATA, timeout=10)
        if r.status_code == 200:
            for p in r.json().get("pilots", []):
                if str(p.get("cid", "")) == cid:
                    return p
    except Exception:
        pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  YARDIMCILAR
# ══════════════════════════════════════════════════════════════════════════════
def parse_dt(s):
    if not s:
        return pd.NaT
    try:
        return pd.to_datetime(s, utc=True)
    except Exception:
        return pd.NaT

def fmt_dur(minutes):
    try:
        m = int(round(float(minutes)))
    except (ValueError, TypeError):
        m = 0
    if m < 60:
        return f"{m}dk"
    return f"{m//60}s {m%60:02d}dk"

def icao_type(raw):
    if not raw:
        return "ZZZZ"
    return str(raw).split("/")[0].strip().upper() or "ZZZZ"

# ICAO uçak tipi → üretici (genişletilmiş)
_MFR_PREFIX = [
    ("Airbus",        ("A30","A31","A32","A33","A34","A35","A38","A19","A20","A21","A22","A18")),
    ("Boeing",        ("B70","B71","B72","B73","B74","B75","B76","B77","B78","B79","737","747","757","767","777","787","B38","B39","B73")),
    ("Embraer",       ("E11","E12","E13","E14","E17","E19","E29","E45","E50","E55","E75","E70","ER3","ERJ")),
    ("Bombardier",    ("CRJ","CR1","CR2","CR7","CR9","CL6","BD1","GLF","GL5","GL6","GL7","DH8","DH1","DH2","DH3","DH4")),
    ("ATR",           ("AT4","AT5","AT7","AT8")),
    ("Cessna",        ("C72","C82","C17","C20","C21","C25","C50","C51","C52","C55","C56","C68","C75","C82","C42")),
    ("Piper",         ("P28","PA2","PA3","PA4","PA6")),
    ("Cirrus",        ("SR2","SR22","S22T")),
    ("Diamond",       ("DA4","DA6","DA2","DA7","DV2")),
    ("McDonnell D.",  ("MD8","MD9","MD1","DC8","DC9","DC1","B71")),
    ("Lockheed",      ("C13","C17","C5 ","L10","C30")),
    ("Beechcraft",    ("BE2","BE3","BE4","BE5","BE6","BE9","B190","BE10","BE20","BE40","BE58","BE60","B350")),
    ("Pilatus",       ("PC12","PC24","PC6","PC7","PC9")),
]
def manufacturer(t: str) -> str:
    t = t.upper()
    for name, prefixes in _MFR_PREFIX:
        if t.startswith(prefixes):
            return name
    if t.startswith("A"): return "Airbus"
    if t.startswith("B"): return "Boeing"
    return "Diğer"

# ── Renk paleti (tutarlı tek tema) ──────────────────────────────────────────
INK       = "#0a0e1a"   # en koyu arka
PANEL     = "#10141f"   # panel
LINE      = "#1f2937"   # çizgi
SUBTLE    = "#5b6b82"   # silik metin
TEXT      = "#e8eef7"   # ana metin
CYAN      = "#22d3ee"   # pilot / vurgu
VIOLET    = "#8b5cf6"   # ATC
AMBER     = "#fbbf24"   # uyarı / nadir
EMERALD   = "#34d399"   # pozitif
ROSE      = "#fb7185"   # sıcak vurgu

PLOTLY_FONT = dict(family="ui-monospace, 'Cascadia Code', monospace", color=TEXT, size=11)

def _bare_layout(fig, h=200):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=6, b=0), height=h, font=PLOTLY_FONT,
        showlegend=False, coloraxis_showscale=False,
    )
    fig.update_xaxes(gridcolor=LINE, zeroline=False, title="")
    fig.update_yaxes(gridcolor=LINE, zeroline=False, title="")
    return fig

# ══════════════════════════════════════════════════════════════════════════════
#  STİL (tek seferlik CSS)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f"""
<style>
.vs-wrap {{ font-family: ui-monospace, 'Cascadia Code', 'SF Mono', monospace; }}
.vs-eyebrow {{
  font-size:11px; letter-spacing:3px; text-transform:uppercase;
  color:{SUBTLE}; font-weight:700; margin:0 0 2px 0;
}}
.vs-h {{ font-size:15px; font-weight:700; color:{TEXT}; letter-spacing:.5px;
        margin:18px 0 10px 0; display:flex; align-items:center; gap:8px; }}
.vs-h::before {{ content:""; width:3px; height:16px; background:{CYAN}; display:inline-block; border-radius:2px; }}
.vs-card {{
  background:{PANEL}; border:1px solid {LINE}; border-radius:10px;
  padding:16px 18px;
}}
.vs-kpi-label {{ font-size:10px; letter-spacing:1.5px; text-transform:uppercase;
                 color:{SUBTLE}; font-weight:700; }}
.vs-kpi-val {{ font-size:26px; font-weight:800; line-height:1.1; margin-top:6px;
               font-variant-numeric:tabular-nums; }}
.vs-kpi-sub {{ font-size:11px; color:{SUBTLE}; margin-top:4px; }}
.vs-chip {{ display:inline-block; padding:5px 12px; border-radius:6px;
            font-size:12px; font-weight:700; letter-spacing:.5px; }}
.vs-route {{ display:flex; justify-content:space-between; align-items:center;
             padding:9px 14px; border-radius:7px; margin-bottom:6px;
             background:{INK}; border:1px solid {LINE}; }}
.vs-route .ap {{ font-size:14px; font-weight:700; letter-spacing:1px; }}
.vs-route .arrow {{ color:{SUBTLE}; margin:0 7px; }}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  GİRİŞ
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(f'<div class="vs-eyebrow">VatScore Radar · Dossier</div>', unsafe_allow_html=True)
st.markdown(f'<h2 style="margin-top:0;color:{TEXT};font-weight:800;">CID İstatistikleri</h2>', unsafe_allow_html=True)

cid_input = st.text_input("VATSIM CID", placeholder="örn. 1481801",
                          max_chars=10, key="cid_stats_input", label_visibility="collapsed")

if not (cid_input and cid_input.strip().isdigit()):
    st.info("Bir VATSIM CID gir, tüm uçuş ve ATC geçmişini çekelim.")
    st.stop()

cid = cid_input.strip()

with st.spinner("Veriler çekiliyor (tüm geçmiş)…"):
    flights_raw = statsim_flights(cid)
    atc_raw     = statsim_atc(cid)
    member      = vatsim_member(cid)
    lp          = live_pilot(cid)

details = member.get("details", {})
stats   = member.get("/stats", {})

# ── Profil alanları ──────────────────────────────────────────────────────────
name = f"{details.get('name_first','')} {details.get('name_last','')}".strip() or f"CID {cid}"
reg  = str(details.get("reg_date",""))[:10]
region   = details.get("region_id","—")
division = details.get("division_id","—")

raw_atc_r   = (lp or {}).get("rating",       details.get("rating", 0))
raw_pilot_r = (lp or {}).get("pilot_rating", details.get("pilotrating", 0))
raw_mil_r   = details.get("militaryrating", 0)

atc_label   = ATC_RATINGS.get(int(raw_atc_r), f"R{raw_atc_r}")
pilot_label = decode_pilot_rating(raw_pilot_r)
mil_label   = MILITARY_RATINGS.get(int(raw_mil_r), "None")

pilot_mins = (stats or {}).get("pilot", 0)
atc_mins   = (stats or {}).get("atc", 0)

# ── Profil başlık kartı ────────────────────────────────────────────────────────
online = ""
if lp:
    online = f'<span class="vs-chip" style="background:#062e25;color:{EMERALD};border:1px solid #0c5;margin-left:10px;vertical-align:middle;">● CANLI · {lp.get("callsign","")}</span>'

mil_chip = ""
if int(raw_mil_r) > 0:
    mil_chip = f'<span class="vs-chip" style="background:#1e1633;color:{VIOLET};border:1px solid {VIOLET}40;">MIL {mil_label}</span>'

st.markdown(f"""
<div class="vs-wrap vs-card" style="border-left:4px solid {CYAN};margin-bottom:22px;
     background:linear-gradient(135deg,{PANEL} 0%,{INK} 100%);">
  <div style="font-size:25px;font-weight:800;color:{TEXT};margin-bottom:3px;">{name}{online}</div>
  <div style="font-size:12px;color:{SUBTLE};margin-bottom:16px;">
    CID {cid} &nbsp;·&nbsp; {region}/{division} &nbsp;·&nbsp; Kayıt {reg or '—'}
  </div>
  <div style="display:flex;gap:9px;flex-wrap:wrap;">
    <span class="vs-chip" style="background:#0c2a3a;color:{CYAN};border:1px solid {CYAN}40;">PILOT {pilot_label}</span>
    <span class="vs-chip" style="background:#1e1633;color:{VIOLET};border:1px solid {VIOLET}40;">ATC {atc_label}</span>
    {mil_chip}
  </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  UÇUŞ DATAFRAME
# ══════════════════════════════════════════════════════════════════════════════
if not flights_raw:
    err = st.session_state.get("_flights_err")
    if err:
        st.error(f"statsim.net uçuş verisi çekilemedi (kod: {err}). API key'i ve secrets'ı kontrol et.")
    else:
        st.info("Bu CID için uçuş kaydı bulunamadı.")
    st.stop()

df = pd.DataFrame(flights_raw)
df["dep"]        = df.get("departure",   pd.Series(dtype=str)).fillna("????").str.upper().replace("", "????")
df["arr"]        = df.get("destination", pd.Series(dtype=str)).fillna("????").str.upper().replace("", "????")
df["ac"]         = df.get("aircraft",    pd.Series(dtype=str)).apply(icao_type)
df["mfr"]        = df["ac"].apply(manufacturer)
df["route"]      = df["dep"] + "→" + df["arr"]
df["departed_dt"]= df.get("departed", pd.Series(dtype=str)).apply(parse_dt)
df["arrived_dt"] = df.get("arrived",  pd.Series(dtype=str)).apply(parse_dt)
df["logon_dt"]   = df.get("loggedOn", pd.Series(dtype=str)).apply(parse_dt)
# tarih ekseni: departed yoksa logon
df["when"]       = df["departed_dt"].fillna(df["logon_dt"])
# süre: arrived-departed varsa, dakika
dur = (df["arrived_dt"] - df["departed_dt"]).dt.total_seconds() / 60
df["dur_min"]    = dur.where(dur > 0).fillna(0)

total_flights = len(df)

# ══════════════════════════════════════════════════════════════════════════════
#  ZAMAN FİLTRESİ
# ══════════════════════════════════════════════════════════════════════════════
now_utc = datetime.now(timezone.utc)
tf = st.radio("Zaman", ["Tümü","Son 1 Ay","Son 6 Ay","Bu Yıl","Son 1 Yıl"],
              horizontal=True, key="tf", label_visibility="collapsed")
cutoff = {
    "Son 1 Ay":  now_utc - timedelta(days=30),
    "Son 6 Ay":  now_utc - timedelta(days=182),
    "Bu Yıl":    now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
    "Son 1 Yıl": now_utc - timedelta(days=365),
}.get(tf)

dff = df[df["when"] >= cutoff].copy() if cutoff is not None else df.copy()
st.caption(f"**{len(dff)}** uçuş gösteriliyor · toplam **{total_flights}** kayıt")

# ══════════════════════════════════════════════════════════════════════════════
#  KPI ŞERİDİ
# ══════════════════════════════════════════════════════════════════════════════
flown_dur = dff[dff["dur_min"] > 0]["dur_min"]
def kpi(label, val, sub, color):
    return f"""<div class="vs-card" style="text-align:center;">
      <div class="vs-kpi-label">{label}</div>
      <div class="vs-kpi-val" style="color:{color};">{val}</div>
      <div class="vs-kpi-sub">{sub}</div></div>"""

k1,k2,k3,k4,k5 = st.columns(5)
with k1: st.markdown(kpi("Toplam Uçuş", f"{len(dff)}", f"/{total_flights} tüm zaman", CYAN), unsafe_allow_html=True)
with k2: st.markdown(kpi("Pilot Saati", fmt_dur(pilot_mins), "VATSIM kaydı", EMERALD), unsafe_allow_html=True)
with k3: st.markdown(kpi("ATC Saati",   fmt_dur(atc_mins),   "VATSIM kaydı", VIOLET), unsafe_allow_html=True)
with k4:
    uniq_ap = pd.unique(dff[["dep","arr"]].values.ravel())
    uniq_ap = [a for a in uniq_ap if a != "????"]
    st.markdown(kpi("Havalimanı", f"{len(uniq_ap)}", "farklı meydan", AMBER), unsafe_allow_html=True)
with k5:
    st.markdown(kpi("Uçak Tipi", f"{dff['ac'].nunique()}", "farklı ICAO", ROSE), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 1 — AKTİVİTE (aylık) + İLK/SON
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="vs-h">Aktivite</div>', unsafe_allow_html=True)
a1, a2 = st.columns([0.7, 0.3])

with a1:
    if not dff["when"].isna().all():
        dm = dff.dropna(subset=["when"]).copy()
        dm["month"] = dm["when"].dt.to_period("M").astype(str)
        mc = dm.groupby("month").size().reset_index(name="n")
        fig = px.area(mc, x="month", y="n", template="plotly_dark")
        fig.update_traces(line=dict(color=CYAN, width=2),
                          fill="tozeroy", fillcolor="rgba(34,211,238,0.12)",
                          mode="lines")
        _bare_layout(fig, 220)
        fig.update_xaxes(tickangle=-45, tickfont=dict(size=9))
        st.plotly_chart(fig, use_container_width=True)

with a2:
    first_f = df["when"].min()
    last_f  = df["when"].max()
    fmt = "%d.%m.%Y"
    avg = int(flown_dur.mean()) if len(flown_dur) else 0
    st.markdown(f"""
<div class="vs-card">
  <div class="vs-kpi-label">İlk Uçuş</div>
  <div style="color:{TEXT};font-size:15px;margin:4px 0 12px;">{first_f.strftime(fmt) if pd.notna(first_f) else '—'}</div>
  <div class="vs-kpi-label">Son Uçuş</div>
  <div style="color:{CYAN};font-size:15px;margin:4px 0 12px;">{last_f.strftime(fmt) if pd.notna(last_f) else '—'}</div>
  <div class="vs-kpi-label">Ortalama Süre</div>
  <div style="color:{AMBER};font-size:19px;font-weight:800;margin-top:4px;">{fmt_dur(avg)}</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 2 — FLEET (üretici donut + ICAO bar)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="vs-h">Filo</div>', unsafe_allow_html=True)
f1, f2 = st.columns(2)

with f1:
    mc = dff["mfr"].value_counts().head(7).reset_index()
    mc.columns = ["mfr","n"]
    fig = px.pie(mc, names="mfr", values="n", hole=0.58, template="plotly_dark",
                 color_discrete_sequence=[CYAN,VIOLET,EMERALD,AMBER,ROSE,"#60a5fa","#a78bfa"])
    fig.update_traces(textposition="outside", textinfo="label+percent",
                      textfont=dict(size=11, color=TEXT),
                      marker=dict(line=dict(color=INK, width=2)))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=0,r=0,t=0,b=0), height=240, showlegend=False,
                      font=PLOTLY_FONT,
                      annotations=[dict(text=f"<b>{dff['mfr'].nunique()}</b><br>üretici",
                                        x=0.5, y=0.5, font=dict(size=14, color=SUBTLE),
                                        showarrow=False)])
    st.plotly_chart(fig, use_container_width=True)

with f2:
    ac = dff["ac"].value_counts().head(8).reset_index()
    ac.columns = ["ac","n"]
    fig = px.bar(ac, x="n", y="ac", orientation="h", template="plotly_dark",
                 color="n", color_continuous_scale=[[0,"#0c2a3a"],[1,CYAN]])
    fig.update_traces(marker_line_width=0, opacity=0.95,
                      text=ac["n"], textposition="outside",
                      textfont=dict(color=SUBTLE, size=10))
    _bare_layout(fig, 240)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=12))
    st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 3 — EN UZUN UÇUŞLAR
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="vs-h">En Uzun Uçuşlar</div>', unsafe_allow_html=True)
s1, s2 = st.columns([0.35, 0.65])
with s1:
    min_h = st.slider("Min. süre (saat)", 0, 14, 0, key="min_h")
with s2:
    top_n = st.slider("Adet", 5, 30, 12, step=1, key="top_n")

dl = dff[(dff["dur_min"] >= min_h*60) & (dff["dur_min"] > 0)] \
        .sort_values("dur_min", ascending=False).head(top_n).copy()

if len(dl):
    dl["lbl"] = dl["route"] + "  " + dl["ac"]
    dl["hm"]  = dl["dur_min"].apply(fmt_dur)
    fig = px.bar(dl, x="dur_min", y="lbl", orientation="h", template="plotly_dark",
                 color="dur_min", color_continuous_scale=[[0,"#0c2e26"],[1,EMERALD]],
                 custom_data=["hm"])
    fig.update_traces(marker_line_width=0, opacity=0.95,
                      hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>",
                      text=dl["hm"], textposition="outside",
                      textfont=dict(color=SUBTLE, size=10))
    _bare_layout(fig, max(260, len(dl)*30))
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=11))
    fig.update_xaxes(title="dakika")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Bu filtreyle süre verisi olan uçuş yok. (statsim bazı uçuşlarda departed/arrived vermez)")

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 4 — ROTALAR  (en çok / en nadir)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="vs-h">Rotalar</div>', unsafe_allow_html=True)
r1, r2 = st.columns(2)
rc = Counter(dff[dff["route"] != "????→????"]["route"].tolist())

with r1:
    st.markdown(f'<div class="vs-kpi-label" style="margin-bottom:8px;">En Çok Uçulan</div>', unsafe_allow_html=True)
    html = ""
    mx = rc.most_common(1)[0][1] if rc else 1
    for route, cnt in rc.most_common(7):
        d, a = route.split("→")
        w = int(cnt / mx * 100)
        html += f"""<div class="vs-route">
          <span class="ap"><span style="color:{CYAN}">{d}</span><span class="arrow">→</span><span style="color:{CYAN}">{a}</span></span>
          <span style="display:flex;align-items:center;gap:8px;">
            <span style="width:60px;height:4px;background:{LINE};border-radius:2px;overflow:hidden;display:inline-block;">
              <span style="display:block;height:4px;width:{w}%;background:{CYAN};"></span></span>
            <span class="vs-chip" style="background:#0c2a3a;color:{CYAN};padding:2px 9px;">{cnt}×</span>
          </span></div>"""
    st.markdown(html or "<div class='vs-kpi-sub'>Veri yok</div>", unsafe_allow_html=True)

with r2:
    st.markdown(f'<div class="vs-kpi-label" style="margin-bottom:8px;">En İlginç (nadir & uzun)</div>', unsafe_allow_html=True)
    dr = dff[dff["route"] != "????→????"].copy()
    dr["freq"] = dr["route"].map(rc)
    dr = dr[dr["dur_min"] > 30].sort_values(["freq","dur_min"], ascending=[True, False]).head(6)
    if len(dr):
        html = ""
        for _, row in dr.iterrows():
            d, a = row["route"].split("→")
            html += f"""<div class="vs-route" style="border-left:2px solid {AMBER};">
              <span class="ap"><span style="color:{AMBER}">{d}</span><span class="arrow">→</span><span style="color:{AMBER}">{a}</span></span>
              <span class="vs-kpi-sub">{row['ac']} · {fmt_dur(row['dur_min'])}</span></div>"""
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown("<div class='vs-kpi-sub'>Yeterli süre verisi yok</div>", unsafe_allow_html=True)

# Favori uçak satırı
if len(dff):
    top_ac  = dff["ac"].value_counts().idxmax()
    top_mfr = dff["mfr"].value_counts().idxmax()
    top_cnt = int(dff["ac"].value_counts().max())
    st.markdown(f"""<div class="vs-card" style="margin-top:10px;display:flex;justify-content:space-between;align-items:center;">
      <div><span class="vs-kpi-label">En Çok Uçulan Uçak</span>
      <div style="font-size:22px;font-weight:800;color:{EMERALD};margin-top:3px;">{top_ac}
      <span style="font-size:12px;color:{SUBTLE};font-weight:400;">· {top_mfr}</span></div></div>
      <div class="vs-chip" style="background:#0c2e26;color:{EMERALD};font-size:14px;">{top_cnt} uçuş</div>
    </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  PANEL 5 — ATC
# ══════════════════════════════════════════════════════════════════════════════
if atc_raw:
    st.markdown('<div class="vs-h">ATC Oturumları</div>', unsafe_allow_html=True)
    da = pd.DataFrame(atc_raw)
    da["on"]  = da.get("loggedOn",  pd.Series(dtype=str)).apply(parse_dt)
    da["off"] = da.get("loggedOff", pd.Series(dtype=str)).apply(parse_dt)
    da["dur_min"] = ((da["off"] - da["on"]).dt.total_seconds()/60).clip(lower=0).fillna(0)
    da["cs"] = da.get("callsign", pd.Series(dtype=str)).fillna("???").str.upper()

    atc_tf = st.radio("ATC dönem", ["Tümü","Bu Yıl","Son 6 Ay"],
                      horizontal=True, key="atc_tf", label_visibility="collapsed")
    if atc_tf == "Bu Yıl":
        da = da[da["on"] >= now_utc.replace(month=1,day=1,hour=0,minute=0,second=0,microsecond=0)]
    elif atc_tf == "Son 6 Ay":
        da = da[da["on"] >= now_utc - timedelta(days=182)]

    total_atc_min = da["dur_min"].sum()
    g1,g2,g3 = st.columns(3)
    with g1: st.markdown(kpi("Oturum", f"{len(da)}", "kayıt", VIOLET), unsafe_allow_html=True)
    with g2: st.markdown(kpi("Toplam", fmt_dur(total_atc_min), "kontrol süresi", VIOLET), unsafe_allow_html=True)
    with g3: st.markdown(kpi("Pozisyon", f"{da['cs'].nunique()}", "farklı sektör", VIOLET), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        # En çok açılan pozisyonlar (süre bazlı)
        pos = da.groupby("cs")["dur_min"].sum().sort_values(ascending=False).head(12).reset_index()
        pos["hm"] = pos["dur_min"].apply(fmt_dur)
        fig = px.bar(pos, x="dur_min", y="cs", orientation="h", template="plotly_dark",
                     color="dur_min", color_continuous_scale=[[0,"#1e1633"],[1,VIOLET]],
                     custom_data=["hm"])
        fig.update_traces(marker_line_width=0, opacity=0.95,
                          hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>")
        _bare_layout(fig, 360)
        fig.update_yaxes(autorange="reversed", tickfont=dict(size=11))
        fig.update_xaxes(title="dakika")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        def stype(cs):
            cs = str(cs).upper()
            for suf, name in (("_CTR","CTR"),("_APP","APP"),("_DEP","APP"),
                              ("_TWR","TWR"),("_GND","GND"),("_DEL","DEL"),("_FSS","FSS")):
                if suf in cs: return name
            return "Diğer"
        da["tip"] = da["cs"].apply(stype)
        tc = da.groupby("tip")["dur_min"].sum().reset_index()
        tc.columns = ["tip","dur"]
        fig = px.pie(tc, names="tip", values="dur", hole=0.58, template="plotly_dark",
                     color_discrete_sequence=[VIOLET,CYAN,EMERALD,AMBER,ROSE,"#60a5fa"])
        fig.update_traces(textposition="outside", textinfo="label+percent",
                          textfont=dict(size=11, color=TEXT),
                          marker=dict(line=dict(color=INK, width=2)))
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=0,r=0,t=0,b=0), height=360, showlegend=False,
                          font=PLOTLY_FONT,
                          annotations=[dict(text="sektör<br>tipi", x=0.5, y=0.5,
                                            font=dict(size=13, color=SUBTLE), showarrow=False)])
        st.plotly_chart(fig, use_container_width=True)