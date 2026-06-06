import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter
from datetime import datetime, timezone

# ─── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VatScore // CID Stats",
    page_icon="📊",
    layout="wide"
)

# ─── Styling ─────────────────────────────────────────────────────────────────────
st.markdown("""
    <style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="sidebarNav"] { display: none !important; }
    .block-container { padding-top: 2rem; max-width: 1400px; }

    .profile-card {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid #1e3a5f;
        border-radius: 12px;
        padding: 24px 28px;
        margin-bottom: 24px;
    }
    .profile-name {
        font-size: 26px;
        font-weight: bold;
        color: #f8fafc;
        margin-bottom: 4px;
    }
    .profile-cid {
        font-size: 13px;
        color: #64748b;
        font-family: monospace;
        margin-bottom: 16px;
    }
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: bold;
        font-family: monospace;
        margin-right: 8px;
    }
    .badge-pilot { background: #143a24; color: #22c55e; border: 1px solid #22c55e40; }
    .badge-atc   { background: #172554; color: #3b82f6; border: 1px solid #3b82f640; }
    .badge-rl    { background: #2d1b4e; color: #a78bfa; border: 1px solid #a78bfa40; }

    .stat-box {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 16px 20px;
        text-align: center;
    }
    .stat-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
    .stat-value { font-size: 22px; font-weight: bold; color: #22c55e; font-family: monospace; }
    .stat-sub   { font-size: 11px; color: #475569; margin-top: 2px; }

    .section-title {
        font-size: 13px;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin: 24px 0 12px 0;
        border-bottom: 1px solid #1e293b;
        padding-bottom: 6px;
    }
    .route-item {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 6px;
        font-family: monospace;
        font-size: 13px;
        color: #94a3b8;
        display: flex;
        justify-content: space-between;
    }
    .route-highlight { color: #3b82f6; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# ─── Rating Maps ─────────────────────────────────────────────────────────────────
PILOT_RATINGS = {
    0: "P0 - Observer", 1: "P1 - PPL", 3: "P2 - IR",
    7: "P3 - CMEL", 15: "P4 - ATP", 31: "P5 - CTP", 63: "P6 - Ferry"
}
ATC_RATINGS = {
    -1: "Inactive", 0: "OBS", 1: "S1", 2: "S2", 3: "S3",
    4: "C1", 5: "C2", 6: "C3", 7: "I1", 8: "I2", 9: "I3",
    10: "SUP", 11: "ADM"
}
MILITARY_RATINGS = {0: "None", 1: "M1", 2: "M2", 3: "M3"}

# ─── API Helpers ─────────────────────────────────────────────────────────────────
VATSIM_API = "https://api.vatsim.net/v2"

def fetch_member_details(cid):
    try:
        r = requests.get(f"{VATSIM_API}/members/{cid}", timeout=10)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def fetch_member_stats(cid):
    try:
        r = requests.get(f"{VATSIM_API}/members/{cid}/stats", timeout=10)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def fetch_member_flightplans(cid):
    try:
        r = requests.get(f"{VATSIM_API}/members/{cid}/flightplans", timeout=10)
        return r.json() if r.status_code == 200 else []
    except:
        return []

def fetch_member_atcsessions(cid):
    try:
        r = requests.get(f"{VATSIM_API}/members/{cid}/atcsessions?limit=100&offset=0", timeout=10)
        data = r.json() if r.status_code == 200 else {}
        return data.get("items", []) if isinstance(data, dict) else []
    except:
        return []

# ─── Aircraft ICAO Full Name ──────────────────────────────────────────────────────
def prettify_aircraft(raw):
    # Extract short ICAO code from ICAO/equipment strings like "B738/H-SDE3/LB1"
    if not raw:
        return "Unknown"
    return raw.split("/")[0].strip().upper()

# ─── Hours Formatting ─────────────────────────────────────────────────────────────
def format_hours(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m:02d}m"

# ─── Header ──────────────────────────────────────────────────────────────────────
st.markdown("### 📊 VatScore // CID-Based Statistics Dashboard")
st.markdown("---")

# ─── CID Input ───────────────────────────────────────────────────────────────────
cid_input = st.text_input(
    "Enter VATSIM CID",
    placeholder="e.g. 1863530",
    max_chars=10
)

if not cid_input or not cid_input.strip().isdigit():
    st.info("Enter a valid numeric VATSIM CID above to load the dashboard.")
    st.stop()

cid = cid_input.strip()

# ─── Data Fetch ───────────────────────────────────────────────────────────────────
with st.spinner("Fetching member data..."):
    details   = fetch_member_details(cid)
    stats     = fetch_member_stats(cid)
    fplans    = fetch_member_flightplans(cid)
    atc_sess  = fetch_member_atcsessions(cid)

if not details:
    st.error(f"CID {cid} not found or API unavailable.")
    st.stop()

# ─── Parse Details ────────────────────────────────────────────────────────────────
name_first   = details.get("name_first", "")
name_last    = details.get("name_last", "")
full_name    = f"{name_first} {name_last}".strip() or f"CID {cid}"
rating       = details.get("rating", 0)
pilot_rating = details.get("pilotrating", 0)
mil_rating   = details.get("militaryrating", 0)
reg_date     = details.get("reg_date", "")
division     = details.get("division_id", "N/A")
region       = details.get("region_id", "N/A")

atc_label    = ATC_RATINGS.get(rating, f"Rating {rating}")
pilot_label  = PILOT_RATINGS.get(pilot_rating, f"P{pilot_rating}")
mil_label    = MILITARY_RATINGS.get(mil_rating, "None")

reg_display  = reg_date[:10] if reg_date else "N/A"

# ─── Parse Stats ──────────────────────────────────────────────────────────────────
pilot_mins = stats.get("pilot", 0) if stats else 0
atc_mins   = stats.get("atc", 0)   if stats else 0

# ─── Profile Card ─────────────────────────────────────────────────────────────────
st.markdown(f"""
    <div class="profile-card">
        <div class="profile-name">{full_name}</div>
        <div class="profile-cid">VATSIM CID: {cid} &nbsp;·&nbsp; {region} / {division} &nbsp;·&nbsp; Joined: {reg_display}</div>
        <span class="badge badge-atc">ATC: {atc_label}</span>
        <span class="badge badge-pilot">PILOT: {pilot_label}</span>
        {'<span class="badge badge-rl">MIL: ' + mil_label + '</span>' if mil_rating > 0 else ''}
    </div>
""", unsafe_allow_html=True)

# ─── Top Stats Row ────────────────────────────────────────────────────────────────
sc1, sc2, sc3, sc4 = st.columns(4)

with sc1:
    st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Pilot Hours</div>
            <div class="stat-value">{format_hours(pilot_mins)}</div>
            <div class="stat-sub">{pilot_mins} total minutes</div>
        </div>
    """, unsafe_allow_html=True)

with sc2:
    st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">ATC Hours</div>
            <div class="stat-value">{format_hours(atc_mins)}</div>
            <div class="stat-sub">{atc_mins} total minutes</div>
        </div>
    """, unsafe_allow_html=True)

with sc3:
    total_flights = len(fplans)
    st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">Recent Flights</div>
            <div class="stat-value">{total_flights}</div>
            <div class="stat-sub">Last 50 on record</div>
        </div>
    """, unsafe_allow_html=True)

with sc4:
    atc_count = len(atc_sess)
    st.markdown(f"""
        <div class="stat-box">
            <div class="stat-label">ATC Sessions</div>
            <div class="stat-value">{atc_count}</div>
            <div class="stat-sub">Last 100 on record</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─── Flight Plan Analysis ─────────────────────────────────────────────────────────
if fplans:
    df_fp = pd.DataFrame(fplans)

    # Build duration in minutes from hrsenroute + minenroute
    df_fp["duration_min"] = df_fp["hrsenroute"] * 60 + df_fp["minenroute"]
    df_fp["aircraft_short"] = df_fp["aircraft"].apply(prettify_aircraft)
    df_fp["route_str"] = df_fp["dep"].fillna("?") + " → " + df_fp["arr"].fillna("?")
    df_fp["filed_dt"] = pd.to_datetime(df_fp["filed"], errors="coerce", utc=True)

    first_flight = df_fp["filed_dt"].min()
    last_flight  = df_fp["filed_dt"].max()

    col_left, col_right = st.columns([1, 1])

    # ── Left column: Most Flown Routes + First/Last ──────────────────────────────
    with col_left:
        st.markdown('<div class="section-title">Most Flown Routes (Last 50)</div>', unsafe_allow_html=True)

        route_counts = Counter(df_fp["route_str"].tolist())
        for route, count in route_counts.most_common(8):
            dep, arr = route.split(" → ")
            st.markdown(f"""
                <div class="route-item">
                    <span><span class="route-highlight">{dep}</span> → <span class="route-highlight">{arr}</span></span>
                    <span style="color:#22c55e;">{count}x</span>
                </div>
            """, unsafe_allow_html=True)

        st.markdown('<div class="section-title">Flight Timeline</div>', unsafe_allow_html=True)
        t1, t2 = st.columns(2)
        with t1:
            st.markdown(f"""
                <div class="stat-box">
                    <div class="stat-label">First on Record</div>
                    <div class="stat-value" style="font-size:15px;">{first_flight.strftime('%Y-%m-%d') if pd.notna(first_flight) else 'N/A'}</div>
                </div>
            """, unsafe_allow_html=True)
        with t2:
            st.markdown(f"""
                <div class="stat-box">
                    <div class="stat-label">Latest on Record</div>
                    <div class="stat-value" style="font-size:15px;">{last_flight.strftime('%Y-%m-%d') if pd.notna(last_flight) else 'N/A'}</div>
                </div>
            """, unsafe_allow_html=True)

    # ── Right column: Aircraft Distribution ──────────────────────────────────────
    with col_right:
        st.markdown('<div class="section-title">Aircraft Distribution (ICAO Type)</div>', unsafe_allow_html=True)

        ac_counts = df_fp["aircraft_short"].value_counts().head(10).reset_index()
        ac_counts.columns = ["Aircraft", "Count"]

        fig_ac = px.bar(
            ac_counts,
            x="Count", y="Aircraft",
            orientation="h",
            color="Count",
            color_continuous_scale=[[0, "#1e3a5f"], [1, "#3b82f6"]],
            template="plotly_dark"
        )
        fig_ac.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            height=300,
            showlegend=False,
            coloraxis_showscale=False,
            yaxis=dict(autorange="reversed")
        )
        fig_ac.update_traces(marker_line_width=0)
        st.plotly_chart(fig_ac, use_container_width=True)

    # ── Flight Duration Ranking ───────────────────────────────────────────────────
    st.markdown('<div class="section-title">Flight Duration Ranking (Longest → Shortest)</div>', unsafe_allow_html=True)

    df_dur = df_fp[df_fp["duration_min"] > 0].sort_values("duration_min", ascending=False).head(20).copy()
    df_dur["label"] = df_dur["route_str"] + " (" + df_dur["aircraft_short"] + ")"
    df_dur["duration_display"] = df_dur["duration_min"].apply(format_hours)

    fig_dur = px.bar(
        df_dur,
        x="duration_min", y="label",
        orientation="h",
        color="duration_min",
        color_continuous_scale=[[0, "#143a24"], [1, "#22c55e"]],
        template="plotly_dark",
        hover_data={"duration_display": True, "duration_min": False, "label": False}
    )
    fig_dur.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        height=420,
        showlegend=False,
        coloraxis_showscale=False,
        yaxis=dict(autorange="reversed", title=""),
        xaxis=dict(title="Minutes")
    )
    fig_dur.update_traces(marker_line_width=0)
    st.plotly_chart(fig_dur, use_container_width=True)

else:
    st.warning("No flight plan history found for this CID.")

# ─── ATC Sessions (only if rating > 0) ───────────────────────────────────────────
if atc_mins > 0 and atc_sess:
    st.markdown('<div class="section-title">Most Opened ATC Sectors</div>', unsafe_allow_html=True)

    df_atc = pd.DataFrame(atc_sess)

    if "callsign" in df_atc.columns:
        # Count by callsign
        atc_counts = df_atc["callsign"].value_counts().head(12).reset_index()
        atc_counts.columns = ["Position", "Sessions"]

        fig_atc = px.bar(
            atc_counts,
            x="Sessions", y="Position",
            orientation="h",
            color="Sessions",
            color_continuous_scale=[[0, "#172554"], [1, "#3b82f6"]],
            template="plotly_dark"
        )
        fig_atc.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            height=350,
            showlegend=False,
            coloraxis_showscale=False,
            yaxis=dict(autorange="reversed", title=""),
            xaxis=dict(title="Sessions")
        )
        fig_atc.update_traces(marker_line_width=0)
        st.plotly_chart(fig_atc, use_container_width=True)

# ─── Footer ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<p style='text-align:center; color:#334155; font-size:12px;'>VatScore CID Stats — Phase 3 / Data: VATSIM Core API v2 (Last 50 Flight Plans)</p>",
    unsafe_allow_html=True
)