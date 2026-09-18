import re
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import network_stats as ns
from ui_theme import AMBER, CYAN, EMERALD, ROSE, apply_base_css, page_url, set_browser_title, stat_card
from vatsim_data import fetch_feed, load_airports
import html

REFRESH_SECONDS = 20
CODE_RE = re.compile(r"[A-Z0-9]{3,4}")

st.set_page_config(page_title="VatScoreRadar - Airport", page_icon="🛫", layout="wide", initial_sidebar_state="collapsed")
apply_base_css()
st.page_link("pages/2_Network_Stats.py", label="Back to Network Stats", icon="⬅️")
st.title("🛫 Airport")

param = str(st.query_params.get("icao", "")).strip().upper()
if CODE_RE.fullmatch(param) and "airport_icao" not in st.session_state:
    st.session_state["airport_icao"] = param

icao_input = st.text_input("ICAO code", key="airport_icao", placeholder="e.g. LTFM", max_chars=4, label_visibility="collapsed")
code = icao_input.strip().upper()
if not CODE_RE.fullmatch(code):
    set_browser_title("Airport")
    st.info("Enter an airport ICAO code to see its live traffic and ATC.")
    st.stop()
if st.query_params.get("icao") != code:
    st.query_params["icao"] = code
set_browser_title("Airport " + code)

def local_time(tz):
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).strftime("%H:%M")
    except Exception:
        return ""

def aircraft_table(rows, place_key, place_label):
    if not rows:
        st.caption("None right now.")
        return
    data = []
    for r in rows:
        data.append({
            "CID": page_url("CID_Stats", cid=str(r["cid"])),
            "Callsign": r["callsign"],
            place_label: r[place_key],
            "Aircraft": r["aircraft"],
            "Status": r["status"],
            "Altitude (FT)": r["altitude"],
            "GS (KT)": r["groundspeed"],
            "Distance (NM)": r["distance_nm"]
        })
    df = pd.DataFrame(data)
    st.dataframe(df, hide_index=True, width="stretch", column_config={"CID": st.column_config.LinkColumn("CID", display_text=r"cid=(\d+)")})

@st.fragment(run_every=REFRESH_SECONDS)
def render(code):
    feed = fetch_feed()
    if not feed:
        st.error("Could not fetch data from VATSIM API. Please reload page.")
        return
    detail = ns.airport_detail(code, feed.get("pilots", []), feed.get("controllers", []), feed.get("atis", []), load_airports())
    if detail is None:
        st.warning(f"No airport found for {code}.")
        return
    icao_esc = html.escape(code)
    name_esc = html.escape(detail.get("name", ""))
    line1 = f"{icao_esc} - {name_esc}"
    city_esc = html.escape(detail.get("city", ""))
    country_esc = html.escape(detail.get("country", ""))
    elevation = detail.get("elevation")
    elev_str = f"{int(elevation):,} ft" if elevation is not None else ""
    lt = local_time(detail.get("tz", ""))
    lt_str = f"Local time {html.escape(lt)}" if lt else ""
    parts = [p for p in [city_esc, country_esc, elev_str, lt_str] if p]
    sub = " · ".join(parts)
    st.markdown(f'<div class="vs-card" style="margin-bottom:12px;text-align:left;"><div style="font-size:22px;font-weight:bold;">{line1}</div><div class="vs-sub">{sub}</div></div>', unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(stat_card("Departing", detail["counts"].get("departing", 0), EMERALD), unsafe_allow_html=True)
    with col2:
        st.markdown(stat_card("Departed", detail["counts"].get("departed", 0), CYAN), unsafe_allow_html=True)
    with col3:
        st.markdown(stat_card("Arriving", detail["counts"].get("arriving", 0), AMBER), unsafe_allow_html=True)
    with col4:
        st.markdown(stat_card("Landed", detail["counts"].get("landed", 0), ROSE), unsafe_allow_html=True)
    st.subheader("ATC")
    if detail.get("atc"):
        atc_data = []
        for a in detail["atc"]:
            atc_data.append({
                "Position": a.get("position", ""),
                "Callsign": a.get("callsign", ""),
                "Frequency": a.get("frequency", ""),
                "Rating": a.get("rating", ""),
                "Controller": a.get("name", ""),
                "Online": a.get("online", False)
            })
        df_atc = pd.DataFrame(atc_data)
        st.dataframe(df_atc, hide_index=True, width="stretch")
    else:
        st.caption("No ATC online.")
    for ati in detail.get("atis", []):
        callsign = ati.get("callsign", "")
        frequency = ati.get("frequency", "")
        text = ati.get("text", "")
        if callsign or frequency:
            mark = f"**{callsign}** {frequency}"
            if ati.get("code"):
                mark += f" - information {ati['code']}"
            st.markdown(mark)
        if text:
            st.text(text)
    left, right = st.columns(2)
    with left:
        st.subheader("Departures")
        aircraft_table(detail.get("departures", []), "destination", "To")
    with right:
        st.subheader("Arrivals")
        aircraft_table(detail.get("arrivals", []), "origin", "From")
    st.caption(f"Live · refreshes every {REFRESH_SECONDS}s · last sync " + datetime.now(timezone.utc).strftime("%H:%M:%S Z"))

render(code)