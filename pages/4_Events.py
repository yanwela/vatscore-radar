from datetime import datetime, timezone
from html import escape

import streamlit as st

import network_stats as ns
from events_data import event_ics, filter_events, group_events, parse_events, relative, time_line, utc_label
from site_banner import read_banner
from ui_theme import (AMBER, CYAN, EMERALD, LINE, PANEL, SITE_BANNER_FILE, SUBTLE, TEXT, VIOLET, apply_base_css, page_url,
                      render_banner, stat_card, track_page_view, visitor_tz)
from vatsim_data import fetch_events_raw, fetch_feed, load_airport_key_map, load_airports

REFRESH_SECONDS = 30
LATER_STEP = 25
MAX_CHIPS = 12
SECTIONS = [("live", "Live now"), ("today", "Today"), ("week", "Next 7 days"), ("later", "Later")]

st.set_page_config(page_title="VatScoreRadar - Events", page_icon="🗓️", layout="wide", initial_sidebar_state="collapsed")
track_page_view("Events")
render_banner(read_banner(SITE_BANNER_FILE))
apply_base_css()
st.markdown(f"""<style>
.ev-card {{ background:{PANEL}; border:1px solid {LINE}; border-bottom:none; border-radius:10px 10px 0 0; padding:12px 16px 16px; margin-top:10px; }}
div[data-testid="stElementContainer"]:has(.ev-card) {{ margin-bottom:-1rem; }}
div[data-testid="stElementContainer"]:has(.ev-card) + div [data-testid="stExpander"] details {{ background:{PANEL}; border:1px solid {LINE}; border-top:1px solid {LINE}; border-radius:0 0 10px 10px; }}
div[data-testid="stElementContainer"]:has(.ev-card) + div [data-testid="stExpander"] summary {{ padding:6px 16px; color:{SUBTLE}; font-size:13px; background:transparent !important; }}
div[data-testid="stElementContainer"]:has(.ev-card) + div [data-testid="stExpander"] summary:hover {{ color:{TEXT}; }}
div[data-testid="stHorizontalBlock"]:has([data-testid="stMultiSelect"]) {{ margin-top:14px; }}
.ev-banner {{ display:block; max-width:100%; max-height:280px; border-radius:8px; margin:0 0 12px; }}
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{ background-color:{PANEL} !important; border:1px solid {LINE} !important; min-height:40px; color:{TEXT} !important; }}
[data-testid="stMultiSelect"] input::placeholder {{ color:#64748b !important; opacity:1; }}
[data-testid="stMultiSelect"] div[data-baseweb="select"] svg {{ color:{SUBTLE} !important; }}
[data-testid="stCheckbox"] {{ padding-top:8px; }}
.ev-name {{ font-size:16px; font-weight:700; color:{TEXT}; }}
.ev-meta {{ font-size:13px; color:{SUBTLE}; margin-top:3px; }}
.ev-badge {{ display:inline-block; font-size:11px; font-weight:600; padding:0 6px; border-radius:4px; margin-left:8px; border:1px solid {LINE}; color:{SUBTLE}; vertical-align:middle; }}
.ev-live {{ color:{EMERALD}; border-color:{EMERALD}; }}
.ev-exam {{ color:{AMBER}; border-color:{AMBER}; }}
.ev-chips {{ margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }}
.ev-chip {{ font-size:12px; padding:1px 8px; border-radius:999px; border:1px solid {LINE}; color:{TEXT} !important; text-decoration:none !important; }}
.ev-chip:hover {{ border-color:{CYAN}; }}
.ev-more {{ color:{SUBTLE} !important; }}
</style>""", unsafe_allow_html=True)


def chips(ev, live_rows, show_live):
    out = []
    for icao in ev["airports"][:MAX_CHIPS]:
        label = escape(icao)
        if show_live:
            row = live_rows.get(icao)
            if row:
                label += f" · {row['total']} aircraft · " + (escape(row["atc"]) if row["atc"] else "no ATC")
            else:
                label += " · no traffic yet"
        out.append(f'<a class="ev-chip" href="{escape(page_url("Airport", icao=icao))}" target="_blank" rel="noopener">{label}</a>')
    if len(ev["airports"]) > MAX_CHIPS:
        out.append(f'<span class="ev-chip ev-more">+{len(ev["airports"]) - MAX_CHIPS} more</span>')
    return "".join(out)


def render_event(ev, now, tz, live_rows, show_live, key):
    is_live = ev["start"] <= now < ev["end"]
    badges = ""
    if is_live:
        badges += '<span class="ev-badge ev-live">Live</span>'
    if "exam" in ev["type"].lower():
        badges += '<span class="ev-badge ev-exam">Exam</span>'
    where = " ".join(x for x in (ev["region"], ev["division"]) if x)
    if where:
        badges += f'<span class="ev-badge">{escape(where)}</span>'
    st.markdown(
        f'<div class="ev-card"><div class="ev-name">{escape(ev["name"])}{badges}</div>'
        f'<div class="ev-meta">{escape(time_line(ev, tz))} · {escape(relative(ev, now))}</div>'
        f'<div class="ev-chips">{chips(ev, live_rows, show_live)}</div></div>', unsafe_allow_html=True)
    with st.expander("Details"):
        if ev["banner"]:
            # loading="lazy": the browser fetches the picture only when this (collapsed) section is opened, not for all events at once
            st.markdown(f'<img class="ev-banner" src="{escape(ev["banner"])}" loading="lazy" alt="" referrerpolicy="no-referrer">', unsafe_allow_html=True)
        if ev["description"]:
            st.markdown(ev["description"])  # raw HTML stays off in st.markdown, so feed text cannot inject markup
        else:
            st.caption("No description.")
        left, right, _ = st.columns([0.2, 0.25, 0.55])
        with left:
            if ev["link"]:
                st.link_button("Open on VATSIM", ev["link"])
        with right:
            st.download_button("Add to calendar (.ics)", data=event_ics(ev, now), file_name=f"vatsim-event-{ev['id'] or key}.ics",
                               mime="text/calendar", key=f"ics_{key}")


def show_more_later():
    st.session_state["ev_later_shown"] = st.session_state.get("ev_later_shown", LATER_STEP) + LATER_STEP


@st.fragment(run_every=REFRESH_SECONDS)
def render_events():
    try:
        events = parse_events(fetch_events_raw())
    except Exception:
        st.error("Could not load the events from VATSIM. Please try again in a moment.")
        return
    now, tz = datetime.now(timezone.utc), visitor_tz()

    exams = st.session_state.get("ev_exams", False)
    everything = group_events(filter_events(events, include_exams=exams), now, tz)  # the KPIs follow the exam switch, not the search
    cols = st.columns(4)
    for col, (label, value, color) in zip(cols, [("Live now", len(everything["live"]), EMERALD), ("Today", len(everything["today"]), CYAN),
                                                 ("Next 7 days", len(everything["week"]), VIOLET),
                                                 ("Upcoming (all)", sum(len(v) for v in everything.values()) - len(everything["live"]), AMBER)]):
        with col:
            st.markdown(stat_card(label, value, color), unsafe_allow_html=True)

    f1, f2, f3 = st.columns([0.45, 0.35, 0.2])
    with f1:
        query = st.text_input("Search", key="ev_query", placeholder="Search event, airport (LTFM) or region…", label_visibility="collapsed", max_chars=60)
    with f2:
        regions = st.multiselect("Region", sorted({e["region"] for e in events if e["region"]}), key="ev_regions", placeholder="All regions", label_visibility="collapsed")
    with f3:
        exams = st.checkbox("Controller exams", key="ev_exams", value=False)

    groups = group_events(filter_events(events, query, regions, exams), now, tz)
    live_rows = {}
    if groups["live"] or groups["today"]:
        try:
            feed = fetch_feed() or {}
            rows = ns.airport_stats(feed.get("pilots", []), feed.get("controllers", []), feed.get("atis", []), load_airports(), key_map=load_airport_key_map())
            live_rows = {r["icao"]: r for r in rows}
        except Exception:
            live_rows = {}

    if not any(groups.values()):
        st.info("No events match your filters.")
    for key, title in SECTIONS:
        items = groups[key]
        if not items:
            continue
        st.subheader(f"{title} ({len(items)})")
        shown = items
        if key == "later":
            limit = st.session_state.get("ev_later_shown", LATER_STEP)
            shown = items[:limit]
        for i, ev in enumerate(shown):
            render_event(ev, now, tz, live_rows, key in ("live", "today"), f"{key}_{i}")
        if key == "later" and len(items) > len(shown):
            st.button(f"Show {min(LATER_STEP, len(items) - len(shown))} more", key="ev_more", on_click=show_more_later)

    tz_note = utc_label(now.astimezone(tz))
    st.caption(f"Times are shown in your time zone ({tz_note}) and in Zulu · events come from my.vatsim.net · refreshes every {REFRESH_SECONDS}s · "
               f"last sync {now:%H:%M:%S}Z")


st.page_link("app.py", label="Back to Live Radar", icon="⬅️")
st.title("🗓️ Events")
render_events()
