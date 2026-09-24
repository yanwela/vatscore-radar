import re
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st
import network_stats as ns
from metar_decode import decode_metar
from redaction import is_blocked
from site_banner import read_banner
from ui_theme import (AMBER, CID_BLOCKLIST_FILE, CYAN, EMERALD, ROSE, SITE_BANNER_FILE, VIOLET, apply_base_css, page_url,
                      render_banner, set_browser_title, stat_card, track_page_view)
from tracon_areas import approach_keys_at
from vatsim_data import fetch_feed, load_airport_key_map, load_airports
import html

REFRESH_SECONDS = 20
METAR_URL = "https://metar.vatsim.net/"  # plain-text METARs of the VATSIM network (METAR only, there is no TAF here)
CATEGORY_COLORS = {"VFR": EMERALD, "MVFR": CYAN, "IFR": ROSE, "LIFR": VIOLET}
CODE_RE = re.compile(r"[A-Z0-9]{3,4}")

st.set_page_config(page_title="VatScoreRadar - Airport", page_icon="🛫", layout="wide", initial_sidebar_state="collapsed")
track_page_view("Airport")
render_banner(read_banner(SITE_BANNER_FILE))
apply_base_css()
st.page_link("pages/2_Network_Stats.py", label="Back to Network Stats", icon="⬅️")
st.title("🛫 Airport")

param = str(st.query_params.get("icao", "")).strip().upper()
if CODE_RE.fullmatch(param) and "airport_icao" not in st.session_state:
    st.session_state["airport_icao"] = param

icao_input = st.text_input("ICAO code", key="airport_icao", placeholder="e.g. LTFM", max_chars=4, label_visibility="collapsed")
code = icao_input.strip().upper()
if not CODE_RE.fullmatch(code):
    st.info("Enter an airport ICAO code to see its live traffic and ATC.")
    st.stop()
if st.query_params.get("icao") != code:
    st.query_params["icao"] = code
set_browser_title("Airport " + code)

@st.cache_data(ttl=120, show_spinner=False)
def fetch_metar(icao):
    if not re.fullmatch(r"[A-Z0-9]{4}", icao):
        return ""
    try:
        r = requests.get(METAR_URL + icao, timeout=8, headers={"User-Agent": "VatScoreRadar"})
        return r.text.strip() if r.status_code == 200 else ""
    except requests.RequestException:
        return ""


def wind_text(m):
    if m["wind_speed_kt"] is None:
        return "-"
    if m["wind_speed_kt"] == 0:
        return "Calm"
    direction = "Variable" if m["wind_variable"] else f"{m['wind_dir']:03d}°"
    text = f"{direction} {m['wind_speed_kt']} kt"
    if m["wind_gust_kt"]:
        text += f" G{m['wind_gust_kt']}"
    if m["wind_var_from"] is not None:
        text += f" ({m['wind_var_from']:03d}-{m['wind_var_to']:03d}°)"
    return text


def visibility_text(m):
    v = m["visibility_m"]
    if v is None:
        return "-"
    if v >= 9999:
        return "10 km or more"
    return f"{v / 1000:.1f} km" if v >= 1000 else f"{v} m"


def ceiling_text(m):
    if m["cavok"]:
        return "CAVOK"
    if m["ceiling_ft"] is None:
        return "No ceiling"
    layer = next((c for c in m["clouds"] if c["cover"] in ("BKN", "OVC") and c["height_ft"] == m["ceiling_ft"]), None)
    return f"{layer['cover'] if layer else 'VV'} {m['ceiling_ft']:,} ft"


def render_metar(code):
    raw = fetch_metar(code)
    m = decode_metar(raw)
    st.subheader("METAR")
    if not m:
        st.caption("No METAR available for this airport." if len(code) == 4 else "METARs need a 4-letter ICAO code.")
        return
    cols = st.columns(6)
    cards = [("Category", m["category"] or "-", CATEGORY_COLORS.get(m["category"], CYAN)), ("Wind", wind_text(m), CYAN),
             ("Visibility", visibility_text(m), CYAN), ("Ceiling", ceiling_text(m), CYAN),
             ("Temp / Dew", f"{m['temp_c']} / {m['dew_c']} °C" if m["temp_c"] is not None and m["dew_c"] is not None else "-", AMBER),
             ("QNH", f"{m['qnh_hpa']} hPa" if m["qnh_hpa"] else "-", EMERALD)]
    for col, (label, value, color) in zip(cols, cards):
        with col:
            st.markdown(stat_card(label, value, color), unsafe_allow_html=True)
    extra = []
    if m["weather"]:
        extra.append("Weather: " + " ".join(m["weather"]))
    if m["altimeter_inhg"]:
        extra.append(f"Altimeter {m['altimeter_inhg']:.2f} inHg")
    extra.append(f"Observed {m['time_z']}")
    st.caption(" · ".join(extra))
    st.code(raw, language=None)


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
    airports = load_airports()
    pilots, controllers, atis = feed.get("pilots", []), feed.get("controllers", []), feed.get("atis", [])
    # the counts and tables need nothing but the feed; the ATC block (key map + approach areas, a few seconds on a cold start) fills in last
    detail = ns.airport_detail(code, pilots, controllers, atis, airports)
    if detail is None:
        st.warning(f"No airport found for {code}.")
        return
    detail["departures"] = [r for r in detail.get("departures", []) if not is_blocked(CID_BLOCKLIST_FILE, r.get("cid", ""))]
    detail["arrivals"] = [r for r in detail.get("arrivals", []) if not is_blocked(CID_BLOCKLIST_FILE, r.get("cid", ""))]
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
    counts = detail["counts"]
    cards = [("Departing", counts.get("departing", 0), EMERALD), ("Departed", counts.get("departed", 0), CYAN),
             ("Outbound", counts.get("outbound", 0), VIOLET), ("Inbound", counts.get("inbound", 0), VIOLET),
             ("Arriving", counts.get("arriving", 0), AMBER), ("Landed", counts.get("landed", 0), ROSE)]
    for col, (label, value, color) in zip(st.columns(len(cards)), cards):
        with col:
            st.markdown(stat_card(label, value, color), unsafe_allow_html=True)
    render_metar(code)
    atc_box = st.container()
    left, right = st.columns(2)
    with left:
        st.subheader("Departures")
        aircraft_table(detail.get("departures", []), "destination", "To")
    with right:
        st.subheader("Arrivals")
        aircraft_table(detail.get("arrivals", []), "origin", "From")
    with atc_box:
        with st.spinner("Loading ATC…"):
            here = airports.get(code)
            approach_keys = approach_keys_at(here["lat"], here["lon"]) if here else set()
            atc_detail = ns.airport_detail(code, pilots, controllers, atis, airports, key_map=load_airport_key_map(), approach_keys=approach_keys)
        st.subheader("ATC")
        if atc_detail.get("atc"):
            atc_data = []
            for a in atc_detail["atc"]:
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
        for ati in atc_detail.get("atis", []):
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
    st.caption(f"Live · refreshes every {REFRESH_SECONDS}s · last sync " + datetime.now(timezone.utc).strftime("%H:%M:%S Z"))

render(code)