from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

import network_stats as ns
from ui_theme import (AMBER, CYAN, EMERALD, LINE, ROSE, SUBTLE, TEXT, VIOLET, apply_base_css, page_url,
                      set_browser_title, stat_card)
from vatsim_data import fetch_feed, load_airlines, load_airports

REFRESH_SECONDS = 20
CHART_TOP_N = 15

PLOTLY_FONT = dict(family="ui-monospace, 'Cascadia Code', monospace", color=TEXT, size=11)

STATUS_COLORS = {"departing": EMERALD, "departed": CYAN, "arriving": AMBER, "landed": ROSE}

st.set_page_config(page_title="VatScoreRadar — Network Stats", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")

apply_base_css()


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
        st.markdown(stat_card(label, f"{int(value):,}", color), unsafe_allow_html=True)


def search_box(key, placeholder):
    return st.text_input("Search", key=key, placeholder=placeholder, label_visibility="collapsed", max_chars=60)


def show_table(df, query, column_config=None, link=None):
    shown = filter_df(df, query)
    config = dict(column_config or {})
    if link:
        column, page, param, pattern = link
        shown = shown.copy()
        shown[column] = shown[column].map(lambda v: page_url(page, **{param: v}))
        config[column] = st.column_config.LinkColumn(column, display_text=pattern)
    st.caption(f"Showing {len(shown):,} of {len(df):,}")
    st.dataframe(shown, hide_index=True, width="stretch", column_config=config)


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
                                            "atc": "ATC", "atis": "ATIS"})), q,
               link=("ICAO", "Airport", "icao", r"icao=([^&]+)"))


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
    show_table(view, q, link=("CID", "CID_Stats", "cid", r"cid=(\d+)"))


def tab_atc(rows):
    df = make_df(rows, ["cid", "callsign", "frequency", "rating", "facility", "name", "online"])
    df["cid"] = df["cid"].astype(str)
    q = search_box("q_atc", "Search CID, callsign, name, rating or facility…")
    show_table(df.rename(columns={"cid": "CID", "callsign": "Callsign", "frequency": "Frequency",
                                  "rating": "Rating", "facility": "Facility", "name": "Name",
                                  "online": "Time online"}), q,
               link=("CID", "CID_Stats", "cid", r"cid=(\d+)"))


def tab_observers(rows):
    df = make_df(rows, ["cid", "callsign", "name", "rating", "online"])
    df["cid"] = df["cid"].astype(str)
    q = search_box("q_observers", "Search CID, callsign or name…")
    show_table(df.rename(columns={"cid": "CID", "callsign": "Callsign", "name": "Name", "rating": "Rating",
                                  "online": "Time online"}), q,
               link=("CID", "CID_Stats", "cid", r"cid=(\d+)"))


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


set_browser_title("Network Stats")
st.page_link("app.py", label="Back to Live Radar", icon="⬅️")
st.title("📈 Network Stats")
render_network_stats()
