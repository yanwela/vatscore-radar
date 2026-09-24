import json
import os

import streamlit as st

_DIR = os.path.dirname(os.path.abspath(__file__))

# Globals that flight_map.js expects to exist (the live page defines them in its own script); a replay has no pilots table,
# so they are built from the payload instead.
_PRELUDE = """
const airportsDatabase = REPLAY_DATA.airports;
const airportUrl = REPLAY_DATA.airportUrl;
const pilotFrequencies = {};
const liveAtc = false;  // the replay draws its own areas; the live ATC code would wipe them on every step
const metarEnabled = false;  // a METAR is the weather now, not the weather of an old flight
let globalDossiers = {};
let currentlyOpenCallsign = null;
function distNM(la1, lo1, la2, lo2) {
    const toRad = v => v * Math.PI / 180;
    const dLa = toRad(la2 - la1), dLo = toRad(lo2 - lo1);
    const a = Math.sin(dLa / 2) ** 2 + Math.cos(toRad(la1)) * Math.cos(toRad(la2)) * Math.sin(dLo / 2) ** 2;
    return 3440.065 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
"""

_PAGE_CSS = """
html, body { margin: 0; background: #0a0c14; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; }
.v-link { color: #3b82f6; text-decoration: underline; }
.v-map-panel { margin: 0; border-radius: 8px; }
.rp-bar { display: flex; align-items: center; gap: 12px; padding: 8px 14px; background-color: #0a0c14; border-top: 1px solid #1e293b; }
.rp-bar input[type=range] { flex: 1; accent-color: #3b82f6; min-width: 80px; }
.rp-time { color: #94a3b8; font-size: 12px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.rp-speed { color: #64748b; font-size: 12px; white-space: nowrap; }
.rp-speed select { background-color: #11131f; color: #e2e8f0; border: 1px solid #1e293b; border-radius: 4px; font: inherit; font-size: 12px; padding: 1px 4px; }
.rp-events { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 14px 8px; background-color: #0a0c14; }
"""


@st.cache_data(show_spinner=False)
def _read_asset(name, mtime):
    # the mtime is part of the cache key, so editing a file shows up on the next run without restarting the server
    with open(os.path.join(_DIR, name), encoding="utf-8") as f:
        return f.read()


def asset(name):
    return _read_asset(name, os.path.getmtime(os.path.join(_DIR, name)))


def _js(value):
    # json.dumps gives a valid JS literal; "</" is defanged so text from the API cannot close the <script> block
    return json.dumps(value).replace("</", "<\\/")


def replay_document(payload):
    """One self-contained HTML page: the Flight Record map panel plus the replay controls, fed with `payload`."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + _PAGE_CSS + asset("flight_map.css") + "</style></head><body>"
        + asset("flight_map_panel.html")
        + "<script>const REPLAY_DATA = " + _js(payload) + ";" + _PRELUDE + "</script>"
        + "<script>" + asset("replay_core.js") + "</script>"
        + "<script>" + asset("replay_phases.js") + "</script>"
        + "<script>" + asset("metar_decode.js") + "</script>"
        + "<script>" + asset("follow_math.js") + "</script>"
        + "<script>" + asset("flight_map.js") + "</script>"
        + "<script>" + asset("flight_replay.js") + "</script>"
        + "</body></html>"
    )
