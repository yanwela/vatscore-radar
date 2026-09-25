from atc_replay_view import _CSS
from flight_replay_view import _js, asset

_BODY = """
<div class="ar">
  <div class="ar-head"><span><b id="lvTitle"></b><span id="lvMeta"></span></span><span class="ar-dim">Live</span></div>
  <div class="ar-mapwrap"><div id="arMap"></div><div class="ar-mapnote" id="lvNote"></div></div>
  <div class="ar-strip">
    <div class="ar-cell">On the ground<b id="lvGround">0</b></div>
    <div class="ar-cell">Airborne nearby<b id="lvAir">0</b></div>
    <div class="ar-cell">Tower zone<b>8 NM · 3,500 ft AGL</b></div>
    <div class="ar-cell">Feed updated<b id="lvFeed">-</b></div>
  </div>
  <div class="ar-legend"><span><i style="background:#f59e0b"></i>Departing from here</span><span><i style="background:#22d3ee"></i>Arriving here</span>
    <span><i style="background:#a78bfa"></i>Other / no flight plan</span></div>
  <div class="ar-list" id="lvList"></div>
  <div class="ar-foot" id="lvFoot"></div>
</div>
"""


def airport_live_document(payload):
    """One self-contained HTML page: the live airport map; `payload` = {"icao","name","lat","lon","elevation","layout","layoutState","hide"}."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + _CSS + "</style></head><body>" + _BODY
        + "<script>const LIVE_DATA = " + _js(payload) + ";</script>"
        + "<script>" + asset("airport_layout.js") + "</script>"
        + "<script>" + asset("airport_live_map.js") + "</script>"
        + "</body></html>"
    )
