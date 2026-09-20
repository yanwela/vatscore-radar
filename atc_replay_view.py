import streamlit as st

from flight_replay_view import _js, asset

_CSS = """
html, body { margin: 0; background: #0a0c14; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
.ar { border: 1px solid #1e293b; border-radius: 8px; overflow: hidden; background: #0a0c14; font-variant-numeric: tabular-nums; }
.ar-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 14px; background: #11131f; border-bottom: 1px solid #1e293b; color: #94a3b8; }
.ar-head b { color: #f1f5f9; font-weight: 600; margin-right: 10px; }
.ar-role { padding: 6px 14px; color: #94a3b8; border-bottom: 1px solid #1e293b; }
.ar-mapwrap { position: relative; height: 420px; }
#arMap { position: absolute; inset: 0; background: #07080c; }
.ar-mapnote { position: absolute; left: 0; right: 0; top: 12px; text-align: center; color: #94a3b8; z-index: 500; pointer-events: none; }
.ar-bar { display: flex; align-items: center; gap: 12px; padding: 8px 14px; border-top: 1px solid #1e293b; }
.ar-bar input[type=range] { flex: 1; accent-color: #3b82f6; min-width: 80px; }
.ar-bar button { padding: 2px 12px; border-radius: 4px; border: 1px solid #1e293b; background: #11131f; color: #e2e8f0; font: inherit; cursor: pointer; }
.ar-time, .ar-speed { color: #94a3b8; white-space: nowrap; }
.ar-speed select { background: #11131f; color: #e2e8f0; border: 1px solid #1e293b; border-radius: 4px; font: inherit; padding: 1px 4px; }
.ar-strip { display: grid; grid-template-columns: repeat(4, 1fr); border-top: 1px solid #1e293b; }
.ar-cell { padding: 7px 14px; border-right: 1px solid #1e293b; color: #64748b; }
.ar-cell:last-child { border-right: none; }
.ar-cell b { display: block; color: #f1f5f9; font-size: 15px; font-weight: 600; }
.ar-list { border-top: 1px solid #1e293b; padding: 6px 14px 10px; max-height: 190px; overflow-y: auto; }
.ar-sec { margin: 6px 0 2px; color: #94a3b8; font-weight: 600; }
.ar-row { display: flex; gap: 12px; align-items: center; padding: 1px 0; }
.ar-row b { min-width: 76px; color: #f1f5f9; font-weight: 600; }
.ar-dim { color: #94a3b8; }
.ar-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.ar-legend { display: flex; gap: 14px; padding: 6px 14px; border-top: 1px solid #1e293b; color: #94a3b8; }
.ar-legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
.ar-foot { padding: 6px 14px 8px; color: #64748b; font-style: italic; border-top: 1px solid #1e293b; }
.ar-ac { position: relative; width: 0; height: 0; }
.ar-ac svg { position: absolute; left: -13px; top: -13px; filter: drop-shadow(0 0 2px #000); }
.ar-tag { position: absolute; left: 12px; top: -22px; padding: 0 4px; border-radius: 3px; background: rgba(10, 12, 20, 0.82); color: #f1f5f9; font-size: 11px; white-space: nowrap; }
.ar-airport-tip { background: #f1f5f9; color: #0a0c14; border: none; font-weight: 600; box-shadow: none; }
.ar-airport-tip::before { display: none; }
"""

_BODY = """
<div class="ar">
  <div class="ar-head"><span><b id="arTitle"></b><span id="arMeta"></span></span></div>
  <div class="ar-role" id="arRole"></div>
  <div class="ar-mapwrap"><div id="arMap"></div><div class="ar-mapnote" id="arMapNote"></div></div>
  <div class="ar-bar">
    <button type="button" id="arPlay">Play</button>
    <input type="range" id="arScrub" step="1">
    <span class="ar-time" id="arTime"></span>
    <label class="ar-speed">Speed <select id="arSpeed"></select></label>
  </div>
  <div class="ar-strip">
    <div class="ar-cell">In the zone<b id="arCount">0</b></div>
    <div class="ar-cell">Approaching<b id="arLead">0</b></div>
    <div class="ar-cell">Just left<b id="arTail">0</b></div>
    <div class="ar-cell">Handled this session<b id="arHandled">0</b></div>
  </div>
  <div class="ar-legend"><span><i style="background:#22d3ee"></i>Inbound</span><span><i style="background:#f59e0b"></i>Outbound</span>
    <span><i style="background:#a78bfa"></i>Local / VFR</span><span><i style="background:#64748b"></i>Outside the zone</span></div>
  <div class="ar-list" id="arList"></div>
  <div class="ar-foot" id="arNote"></div>
</div>
"""


def atc_replay_document(payload):
    """One self-contained HTML page for an airport controller session; `payload` = {"session", "airport", "flights", "stats"}."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + _CSS + "</style></head><body>" + _BODY
        + "<script>const ATC_DATA = " + _js(payload) + ";</script>"
        + "<script>" + asset("replay_core.js") + "</script>"
        + "<script>" + asset("atc_zone.js") + "</script>"
        + "<script>" + asset("atc_poly_zone.js") + "</script>"
        + "<script>" + asset("atc_replay.js") + "</script>"
        + "</body></html>"
    )
