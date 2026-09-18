import os
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

import network_stats as ns

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_RADAR_AIRLINES_URL = "https://data.vatsim-radar.com/airlines"
AIRPORTS_CSV = "airports.csv"
REFRESH_SECONDS = 20
CHART_TOP_N = 15

INK, PANEL, LINE = "#0a0e1a", "#10141f", "#1f2937"
SUBTLE, TEXT = "#5b6b82", "#e8eef7"
CYAN, VIOLET, AMBER, EMERALD, ROSE = "#22d3ee", "#8b5cf6", "#fbbf24", "#34d399", "#fb7185"
PLOTLY_FONT = dict(family="ui-monospace, 'Cascadia Code', monospace", color=TEXT, size=11)

STATUS_COLORS = {"departing": EMERALD, "departed": CYAN, "arriving": AMBER, "landed": ROSE}

st.set_page_config(page_title="VatScoreRadar — Network Stats", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown(f"""
<style>
[data-testid="stAppViewContainer"], [data-testid="stApp"] {{ background-color: {INK} !important; }}
[data-testid="stSidebarNav"] {{ display: none !important; }}
[data-testid="stSidebar"] {{ display: none !important; }}
header, footer {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: #94a3b8 !important; }}
[data-testid="stTextInput"] div[data-baseweb="input"], [data-testid="stTextInput"] input {{
    background-color: {PANEL} !important; color: {TEXT} !important; }}
[data-testid="stTextInput"] div[data-baseweb="input"] {{ border: 1px solid {LINE} !important; }}
[data-testid="stTextInput"] input::placeholder {{ color: #64748b !important; opacity: 1; }}
h1, h2, h3 {{ color: {CYAN} !important; font-family: 'Segoe UI', sans-serif; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ color: #94a3b8; font-size: 15px; }}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {{ color: {CYAN}; }}
[data-testid="stTabs"] [aria-selected="true"] {{ color: {CYAN} !important; font-weight: bold; }}
.vs-eyebrow {{ font-size:11px; letter-spacing:3px; text-transform:uppercase; color:{SUBTLE}; font-weight:700; margin:0 0 2px 0; }}
.vs-card {{ background:{PANEL}; border:1px solid {LINE}; border-radius:10px; padding:14px 16px; text-align:center; }}
.vs-kpi-label {{ font-size:10px; letter-spacing:1.5px; text-transform:uppercase; color:{SUBTLE}; font-weight:700; }}
.vs-kpi-val {{ font-size:24px; font-weight:800; line-height:1.1; margin-top:6px; font-variant-numeric:tabular-nums; }}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=15, show_spinner=False)
def fetch_feed():
    try:
        r = requests.get(VATSIM_DATA_URL, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


@st.cache_resource(ttl=86400, show_spinner=False)
def load_airports():
    if not os.path.exists(AIRPORTS_CSV):
        return {}
    df = pd.read_csv(AIRPORTS_CSV, usecols=["icao", "name", "city", "country", "elevation", "lat", "lon"])
    df = df.dropna(subset=["icao", "lat", "lon"])
    df[["name", "city", "country"]] = df[["name", "city", "country"]].fillna("")
    airports = {}
    for icao, name, city, country, elev, lat, lon in zip(
            df["icao"], df["name"], df["city"], df["country"], df["elevation"], df["lat"], df["lon"]):
        airports[str(icao).strip().upper()] = {
            "name": name, "city": city, "country": country,
            "elevation": None if pd.isna(elev) else float(elev), "lat": float(lat), "lon": float(lon),
        }
    return airports


@st.cache_resource(ttl=86400, show_spinner=False)
def _load_airlines():
    # Raises on failure so a bad response is never cached for 24h.
    r = requests.get(VATSIM_RADAR_AIRLINES_URL, timeout=10)
    r.raise_for_status()
    airlines = {}
    for item in r.json():
        icao = str(item.get("icao") or "").strip().upper()
        if icao:
            airlines.setdefault(icao, {"name": item.get("name", ""), "callsign": item.get("callsign", ""),
                                       "virtual": bool(item.get("virtual", False))})
    return airlines


def load_airlines():
    try:
        return _load_airlines()
    except Exception:
        return {}


def make_df(rows, columns):
    return pd.DataFrame(rows, columns=columns)


def filter_df(df, query):
    q = query.strip()
    if not q or df.empty:
        return df
    mask = df.astype(str).apply(lambda col: col.str.contains(q, case=False, regex=False)).any(axis=1)
    return df[mask]


def with_rank(df):
    df = df.reset_index(drop=True)
    df.insert(0, "#", df.index + 1)
    return df


def style_chart(fig, height=300):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=0, r=0, t=6, b=0), height=height, font=PLOTLY_FONT, legend_title_text="")
    fig.update_xaxes(gridcolor=LINE, zeroline=False, title="")
    fig.update_yaxes(gridcolor=LINE, zeroline=False, title="")
    return fig


def kpi(col, label, value, color):
    with col:
        st.markdown(f"""<div class="vs-card"><div class="vs-kpi-label">{label}</div>
        <div class="vs-kpi-val" style="color:{color};">{int(value):,}</div></div>""", unsafe_allow_html=True)


def search_box(key, placeholder):
    return st.text_input("Search", key=key, placeholder=placeholder, label_visibility="collapsed", max_chars=60)


def show_table(df, query, column_config=None):
    shown = filter_df(df, query)
    st.caption(f"Showing {len(shown):,} of {len(df):,}")
    st.dataframe(shown, hide_index=True, width="stretch", column_config=column_config or {})


def tab_airports(rows):
    df = make_df(rows, ["icao", "name", "city", "country", "departing", "departed", "arriving", "landed",
                        "total", "atc", "atis"])
    if not df.empty:
        top = df[df["total"] > 0].head(CHART_TOP_N)
        if len(top):
            long = top.melt(id_vars="icao", value_vars=list(STATUS_COLORS), var_name="status", value_name="aircraft")
            fig = px.bar(long, x="icao", y="aircraft", color="status", template="plotly_dark",
                         color_discrete_map=STATUS_COLORS)
            st.plotly_chart(style_chart(fig), width="stretch")
    df["atis"] = df["atis"].map({True: "✓", False: ""})
    q = search_box("q_airports", "Search ICAO, name, city, country or ATC…")
    show_table(with_rank(df.rename(columns={"icao": "ICAO", "name": "Name", "city": "City", "country": "Country",
                                            "departing": "Departing", "departed": "Departed",
                                            "arriving": "Arriving", "landed": "Landed", "total": "Total",
                                            "atc": "ATC", "atis": "ATIS"})), q)


def tab_airlines(rows):
    df = make_df(rows, ["icao", "pilots", "callsign", "name", "virtual"])
    if not df.empty:
        fig = px.bar(df.head(CHART_TOP_N), x="icao", y="pilots", template="plotly_dark")
        fig.update_traces(marker_color=CYAN)
        st.plotly_chart(style_chart(fig), width="stretch")
    q = search_box("q_airlines", "Search airline ICAO, callsign or name…")
    df["virtual"] = df["virtual"].map({True: "✓", False: ""})
    show_table(with_rank(df.rename(columns={"icao": "ICAO", "pilots": "Pilots", "callsign": "Callsign",
                                            "name": "Name", "virtual": "Virtual"})), q)


def tab_aircraft(rows):
    df = make_df(rows, ["aircraft", "pilots", "share_pct"])
    if not df.empty:
        fig = px.bar(df.head(CHART_TOP_N), x="aircraft", y="pilots", template="plotly_dark")
        fig.update_traces(marker_color=VIOLET)
        st.plotly_chart(style_chart(fig), width="stretch")
    q = search_box("q_aircraft", "Search aircraft type…")
    show_table(with_rank(df.rename(columns={"aircraft": "Aircraft", "pilots": "Pilots", "share_pct": "Share %"})),
               q, {"Share %": st.column_config.NumberColumn(format="%.1f")})


def tab_routes(rows):
    df = make_df(rows, ["from", "to", "aircraft"])
    if not df.empty:
        top = df.head(CHART_TOP_N).copy()
        top["route"] = top["from"] + " → " + top["to"]
        fig = px.bar(top, x="aircraft", y="route", orientation="h", template="plotly_dark")
        fig.update_traces(marker_color=EMERALD)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(style_chart(fig, 380), width="stretch")
    q = search_box("q_routes", "Search airport ICAO…")
    show_table(with_rank(df.rename(columns={"from": "From", "to": "To", "aircraft": "Aircraft"})), q)


def tab_pilots(rows):
    df = make_df(rows, ["cid", "callsign", "name", "status", "aircraft", "departure", "arrival", "online",
                        "altitude", "groundspeed", "online_min"])
    df["cid"] = df["cid"].astype(str)
    q = search_box("q_pilots", "Search CID, callsign, name, aircraft, airport or status…")
    view = df.drop(columns="online_min").rename(columns={
        "cid": "CID", "callsign": "Callsign", "name": "Name", "status": "Status", "aircraft": "Aircraft",
        "departure": "Departure", "arrival": "Arrival", "online": "Time online",
        "altitude": "Altitude (FT)", "groundspeed": "GS (KT)"})
    show_table(view, q)


def tab_atc(rows):
    df = make_df(rows, ["cid", "callsign", "frequency", "rating", "facility", "name", "online"])
    df["cid"] = df["cid"].astype(str)
    q = search_box("q_atc", "Search CID, callsign, name, rating or facility…")
    show_table(df.rename(columns={"cid": "CID", "callsign": "Callsign", "frequency": "Frequency",
                                  "rating": "Rating", "facility": "Facility", "name": "Name",
                                  "online": "Time online"}), q)


def tab_observers(rows):
    df = make_df(rows, ["cid", "callsign", "name", "rating", "online"])
    df["cid"] = df["cid"].astype(str)
    q = search_box("q_observers", "Search CID, callsign or name…")
    show_table(df.rename(columns={"cid": "CID", "callsign": "Callsign", "name": "Name", "rating": "Rating",
                                  "online": "Time online"}), q)


@st.fragment(run_every=REFRESH_SECONDS)
def render_network_stats():
    feed = fetch_feed()
    if not feed:
        st.error("Could not fetch data from VATSIM API. Please reload page.")
        return

    pilots = feed.get("pilots", [])
    controllers = feed.get("controllers", [])
    atis = feed.get("atis", [])
    airports = load_airports()
    airlines = load_airlines()

    airport_rows = ns.airport_stats(pilots, controllers, atis, airports)
    airline_rows = ns.airline_stats(pilots, airlines)
    aircraft_rows = ns.aircraft_stats(pilots)
    route_rows = ns.route_stats(pilots)
    pilot_rows = ns.pilot_rows(pilots, airports)
    atc_rows = ns.atc_rows(controllers)
    observer_rows = ns.observer_rows(controllers)

    cols = st.columns(6)
    kpi(cols[0], "Pilots", len(pilots), CYAN)
    kpi(cols[1], "ATC", len(atc_rows), VIOLET)
    kpi(cols[2], "Observers", len(observer_rows), SUBTLE)
    kpi(cols[3], "Active airports", sum(1 for r in airport_rows if r["total"] > 0), EMERALD)
    kpi(cols[4], "Airlines", len(airline_rows), AMBER)
    kpi(cols[5], "Aircraft types", len(aircraft_rows), ROSE)
    st.caption(f"Live · refreshes every {REFRESH_SECONDS}s · last sync "
               f"{datetime.now(timezone.utc).strftime('%H:%M:%S Z')}")

    tabs = st.tabs(["Airports", "Airlines", "Aircraft", "Routes", "Pilots", "ATC", "Observers"])
    with tabs[0]:
        tab_airports(airport_rows)
    with tabs[1]:
        tab_airlines(airline_rows)
    with tabs[2]:
        tab_aircraft(aircraft_rows)
    with tabs[3]:
        tab_routes(route_rows)
    with tabs[4]:
        tab_pilots(pilot_rows)
    with tabs[5]:
        tab_atc(atc_rows)
    with tabs[6]:
        tab_observers(observer_rows)


st.page_link("app.py", label="Back to Live Radar", icon="⬅️")
st.markdown('<div class="vs-eyebrow">VatScoreRadar · Network Stats</div>', unsafe_allow_html=True)
st.title("📈 Network Stats")
render_network_stats()
