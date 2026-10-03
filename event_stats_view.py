from datetime import datetime, timezone
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_traffic_core as et
import events_stats as es
from event_replay import render_event_replay
from event_traffic_store import all_traffic
from events_history_store import all_records
from ui_theme import AMBER, CYAN, EMERALD, LINE, PANEL, TEXT, VIOLET, stat_card
from vatsim_data import load_airports

# chart fills: the dataviz palette validator passes this pair against the panel surface in dark mode (lightness band, colour-blind separation, contrast)
HELD, OPEN = "#0ea5c4", "#8b5cf6"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FONT = dict(family="ui-monospace, 'Cascadia Code', monospace", color=TEXT, size=11)
MS_DAY = 86400000
CONFIG = {"displayModeBar": False}


def _bar_marker(color):
    # thin marks with rounded data ends and a 2px surface-coloured gap between neighbours
    return dict(color=color, cornerradius=4, line=dict(color=PANEL, width=2))


def _style(fig, height):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=height, font=FONT, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                      hoverlabel=dict(bgcolor=PANEL, bordercolor=LINE, font=dict(color=TEXT, size=12)))
    fig.update_xaxes(gridcolor=LINE, zeroline=False, title="", linecolor=LINE)
    fig.update_yaxes(gridcolor=LINE, zeroline=False, title="")
    return fig


def _section(title, note):
    st.markdown(f"##### {title}")
    st.caption(note)


def _weekly_chart(weeks):
    dates = [w["week"] for w in weeks]
    width = [5 * MS_DAY] * len(weeks)
    fig = go.Figure()
    fig.add_bar(x=dates, y=[w["held"] for w in weeks], width=width, name="Held", marker=_bar_marker(HELD), hovertemplate="Week of %{x|%d %b}<br>Held: %{y}<extra></extra>")
    fig.add_bar(x=dates, y=[w["open"] for w in weeks], width=width, name="Live or scheduled", marker=_bar_marker(OPEN),
                hovertemplate="Week of %{x|%d %b}<br>Live or scheduled: %{y}<extra></extra>")
    _style(fig, 260)
    fig.update_layout(barmode="stack", showlegend=True, legend=dict(orientation="h", y=1.16, x=0, traceorder="normal"))
    fig.update_xaxes(type="date", tickformat="%d %b")
    return fig


def _column_chart(labels, values, hover, height=230, tick_every=1):
    peak = max(values) if values else 0
    # one series needs no legend; only the peak is labelled directly
    fig = go.Figure(go.Bar(x=labels, y=values, marker=_bar_marker(HELD), text=[str(v) if peak and v == peak else "" for v in values], textposition="outside", cliponaxis=False,
                           hovertemplate=hover + "<extra></extra>"))
    _style(fig, height)
    fig.update_layout(bargap=0.55 if len(values) <= 8 else 0.2)  # a handful of bars would otherwise be slabs
    # "00".."23" would be read as numbers (an axis of 0, 5, 10 ...): keep them as category labels
    fig.update_xaxes(type="category", tickmode="array", tickvals=labels[::tick_every])
    return fig


def _ranked_chart(rows, hover_names, unit):
    labels, counts = [r[0] for r in rows], [r[1] for r in rows]
    fig = go.Figure(go.Bar(x=counts, y=labels, orientation="h", marker=_bar_marker(HELD), text=counts, textposition="outside", cliponaxis=False,
                           customdata=[hover_names.get(label, "") for label in labels], hovertemplate="%{y} %{customdata}<br>%{x} " + unit + "<extra></extra>"))
    _style(fig, 34 * len(rows) + 30)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(range=[0, (max(counts) if counts else 1) * 1.18], showticklabels=False)
    return fig


def _next_label(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%d %b %H:%MZ")
    except (TypeError, ValueError):
        return "-"


def _event_label(rec):
    try:
        day = datetime.strptime(rec["start"], "%Y-%m-%dT%H:%M:%SZ").strftime("%d %b")
    except (TypeError, ValueError, KeyError):
        day = ""
    name = " ".join(str(rec.get("name") or "").split())
    return f"{name[:30]}{'...' if len(name) > 30 else ''} {day}".strip()


def _ranked_traffic_chart(rows):
    labels = [escape(_event_label(r)) for r in rows]
    values = [r["extra"] if r["extra"] is not None else r["movements"] for r in rows]
    text = [f"{r['movements']} (+{r['extra']:g})" if r["extra"] is not None else str(r["movements"]) for r in rows]
    custom = [[r["movements"], "-" if r["base"] is None else f"{r['base']:g}", ", ".join(r["airports"][:4])] for r in rows]
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker=_bar_marker(HELD), text=text, textposition="outside", cliponaxis=False, customdata=custom,
                           hovertemplate="%{y}<br>Movements: %{customdata[0]}<br>Normal day: %{customdata[1]}<br>%{customdata[2]}<extra></extra>"))
    _style(fig, 34 * len(rows) + 30)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(range=[0, (max(values) if values else 1) * 1.3], showticklabels=False)
    return fig


def _traffic_detail(rec, traffic_rec):
    window = traffic_rec.get("window") or [0, 0]
    hourly = traffic_rec.get("hourly") or []
    fmt = "%a %H:%MZ" if len(hourly) > 24 else "%H:%MZ"
    labels = [datetime.fromtimestamp(window[0] + i * 3600, timezone.utc).strftime(fmt) for i in range(len(hourly))]
    cols = st.columns(4)
    atc = traffic_rec.get("atc") or []
    extra = traffic_rec.get("extra")
    for col, (label, value, color) in zip(cols, [("Movements", traffic_rec.get("movements", 0), CYAN), ("Normal day", "-" if traffic_rec.get("base") is None else f"{traffic_rec['base']:g}", VIOLET),
                                                 ("Added by the event", "-" if extra is None else f"{extra:+g}", EMERALD), ("ATC positions", len(atc), AMBER)]):
        with col:
            st.markdown(stat_card(label, value, color), unsafe_allow_html=True)
    if hourly:
        st.caption("Movements per hour, UTC, from one hour before the start to 45 minutes after the end.")
        st.plotly_chart(_column_chart(labels, hourly, "%{x}<br>%{y} movements", height=210, tick_every=max(1, len(labels) // 8)), width="stretch", config=CONFIG)
    left, right = st.columns(2)
    with left:
        airports = traffic_rec.get("airports") or {}
        st.dataframe(pd.DataFrame([{"Airport": icao, "Departures": a.get("dep", 0), "Arrivals": a.get("arr", 0), "Normal day": "-" if a.get("base") is None else a["base"]}
                                   for icao, a in airports.items()]), hide_index=True, width="stretch")
    with right:
        if atc:
            st.dataframe(pd.DataFrame([{"Position": a["callsign"], "Minutes": a["minutes"], "People": a["people"]} for a in atc]), hide_index=True, width="stretch")
        else:
            st.caption("No controller was online at the event airports in this window.")
    render_event_replay(rec, traffic_rec)


def _traffic_section(records, finished):
    traffic = all_traffic()
    ranked = et.ranked_events(records, traffic, limit=10)
    measured = len(et.ranked_events(records, traffic, limit=len(records) + 1))
    _section("Event traffic", "Take-offs and landings at the event's airports, from one hour before the start to 45 minutes after the end (StatSim). "
                              "A normal day is the same hours on the day before and the day after.")
    if not measured:
        st.info("No event has been measured yet. Each finished event is measured about a day after it ends, a few at a time.")
        return
    st.caption(f"Measured for {measured} of {finished} finished events so far.")
    st.markdown("**Events that added the most traffic**")
    st.plotly_chart(_ranked_traffic_chart(ranked), width="stretch", config=CONFIG)
    regular = et.series_traffic(records, traffic, limit=10)
    if regular:
        st.markdown("**Regular events, on average**")
        st.dataframe(pd.DataFrame([{"Event": r["name"], "Measured": r["count"], "Movements": r["avg_movements"], "Added": "-" if r["avg_extra"] is None else r["avg_extra"],
                                    "ATC positions": r["avg_atc"]} for r in regular]), hide_index=True, width="stretch", height=38 + 35 * len(regular))
    options = et.ranked_events(records, traffic, limit=len(records) + 1)
    options.sort(key=lambda r: str(r.get("start")), reverse=True)
    by_key = {r["key"]: r for r in options}
    st.markdown("**One event**")
    keys = [r["key"] for r in options]
    # opens on the event that added the most traffic, not on whichever finished last (often a controller exam)
    picked = st.selectbox("Event", keys, index=keys.index(ranked[0]["key"]) if ranked and ranked[0]["key"] in keys else 0, format_func=lambda k: _event_label(by_key[k]),
                          key="ev_traffic_pick", label_visibility="collapsed")
    if picked in traffic:
        _traffic_detail(by_key[picked], traffic[picked])


def render_event_stats():
    records, now = all_records(), datetime.now(timezone.utc)
    summary = es.summarize(records, now)
    counts = summary["counts"]
    if not counts["recorded"]:
        st.info("No events have been recorded yet. This page fills in as the server sees events on VATSIM's list.")
        return

    cols = st.columns(4)
    for col, (label, value, color) in zip(cols, [("Held so far", counts["held"], CYAN), ("Live now", counts["live"], EMERALD), ("Scheduled", counts["scheduled"], VIOLET),
                                                 ("Withdrawn", counts["withdrawn"], AMBER)]):
        with col:
            st.markdown(stat_card(label, value, color), unsafe_allow_html=True)
    since = summary["since"]
    st.caption(f"{counts['recorded']} events recorded since {since}. VATSIM's public list only shows events that have not ended, so earlier ones are not here. "
               f"A typical event runs {summary['median_hours']} h, 9 in 10 are over within {summary['p90_hours']} h, the longest runs {summary['longest_hours']} h.")

    weeks = es.weekly_counts(records, now)
    if weeks:
        _section("Events per week", "By start date (UTC), the next 90 days included. Held events have already ended.")
        st.plotly_chart(_weekly_chart(weeks), width="stretch", config=CONFIG)
        with st.expander("Show the numbers"):
            st.dataframe(pd.DataFrame([{"Week starting": w["week"], "Held": w["held"], "Live or scheduled": w["open"]} for w in weeks]), hide_index=True, width="stretch")

    _traffic_section(records, counts["held"])

    profile = es.start_profile(records)
    left, right = st.columns(2)
    with left:
        _section("When events start", "Start hour, UTC.")
        st.plotly_chart(_column_chart([f"{h:02d}" for h in range(24)], profile["hours"], "%{x}:00 UTC<br>%{y} events start", tick_every=3), width="stretch", config=CONFIG)
    with right:
        _section("Which day", "Start day of the week, UTC.")
        st.plotly_chart(_column_chart(WEEKDAYS, profile["weekdays"], "%{x}<br>%{y} events start"), width="stretch", config=CONFIG)

    try:
        airports = load_airports()
    except Exception:
        airports = {}
    left, right = st.columns(2)
    divisions, busiest = es.count_by(records, "division", 10), es.count_by(records, "airport", 10)
    with left:
        _section("Busiest divisions", "Events per VATSIM division, withdrawn ones left out.")
        if divisions:
            st.plotly_chart(_ranked_chart(divisions, {}, "events"), width="stretch", config=CONFIG)
    with right:
        _section("Busiest airports", "Events that list the airport.")
        if busiest:
            st.plotly_chart(_ranked_chart(busiest, {icao: (airports.get(icao) or {}).get("name", "") for icao, _ in busiest}, "events"), width="stretch", config=CONFIG)

    regular = es.series(records, now, limit=15)
    if regular:
        _section("Regular events", "Events that keep coming back under the same name, most frequent first.")
        st.dataframe(pd.DataFrame([{"Event": s["name"], "Times": s["count"], "Held": s["held"], "Usually": f"{WEEKDAYS[s['typical_weekday']]} {s['typical_hour']:02d}:00Z",
                                    "Division": s["division"] or "-", "Next": _next_label(s["next_start"])} for s in regular]), hide_index=True, width="stretch",
                     height=38 + 35 * len(regular))

    withdrawn = es.withdrawn_list(records)
    if withdrawn:
        with st.expander(f"Withdrawn events ({len(withdrawn)})"):
            st.caption("Removed from VATSIM's list before they started.")
            st.dataframe(pd.DataFrame([{"Event": w["name"], "Was due": _next_label(w["start"]), "Type": w["type"]} for w in withdrawn]), hide_index=True, width="stretch")
