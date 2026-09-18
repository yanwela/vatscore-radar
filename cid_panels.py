import math
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from ui_theme import AMBER, CYAN, INK, LINE, PANEL, TEXT
from vatsim_data import load_airports
from visit_stats import activity_matrix, peak_slot, summarize_visits, visited_airports

PLOTLY_FONT = dict(family="ui-monospace, 'Cascadia Code', monospace", color=TEXT, size=11)

def render_activity_panels(df, has_flights):
    st.markdown('<div class="vs-h">Activity by Day and Hour (UTC)</div>', unsafe_allow_html=True)
    if has_flights:
        stamps = list(df["when"].dropna())
        matrix = activity_matrix(stamps)
        peak = peak_slot(matrix)
        if peak:
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            fig = px.imshow(matrix, x=[f"{h:02d}" for h in range(24)], y=days, aspect="auto", color_continuous_scale=[[0, PANEL], [1, CYAN]], labels=dict(x="Hour (UTC)", y="", color="Flights"))
            fig.update_traces(hovertemplate="%{y} %{x}:00 UTC<br>%{z} flights<extra></extra>", xgap=2, ygap=2)
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=6, b=0), height=260, font=PLOTLY_FONT, coloraxis_showscale=False)
            st.plotly_chart(fig, width='stretch')
            st.caption(f"Busiest slot: {days[peak[0]]} {peak[1]:02d}:00 UTC ({peak[2]} flights)")
        else:
            st.info("No flights with date information.")
    else:
        st.info("No flight data.")
    st.markdown('<div class="vs-h">Airports Visited</div>', unsafe_allow_html=True)
    if has_flights:
        visited = visited_airports(zip(df["dep"], df["arr"]), load_airports())
        if visited:
            summary = summarize_visits(visited)
            st.caption(f"{summary['airports']} airports in {summary['countries']} countries")
            visits = [v["visits"] for v in visited]
            fig = go.Figure(go.Scattergeo(
                lat=[v["lat"] for v in visited],
                lon=[v["lon"] for v in visited],
                mode="markers",
                marker=dict(size=[min(7 + 2 * math.sqrt(n), 24) for n in visits], color=visits, colorscale=[[0, "#155e75"], [0.5, CYAN], [1, AMBER]], line=dict(width=0), opacity=0.9, colorbar=dict(title="Visits", thickness=10, len=0.6)),
                customdata=[[v["icao"], v["name"], v["city"], v["country"], v["departures"], v["arrivals"]] for v in visited],
                hovertemplate="<b>%{customdata[0]}</b> - %{customdata[1]}<br>%{customdata[2]}, %{customdata[3]}<br>%{customdata[4]} departures, %{customdata[5]} arrivals<extra></extra>",
            ))
            fig.update_geos(projection_type="natural earth", fitbounds="locations", showland=True, landcolor=PANEL, showocean=True, oceancolor=INK, showcountries=True, countrycolor=LINE, coastlinecolor=LINE, showframe=False, bgcolor="rgba(0,0,0,0)")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=6, b=0), height=460, font=PLOTLY_FONT)
            st.plotly_chart(fig, width='stretch', config={"scrollZoom": True})
        else:
            st.info("No airport coordinates available for these flights.")
    else:
        st.info("No flight data.")