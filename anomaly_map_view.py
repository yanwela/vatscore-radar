from flight_replay_view import _js, asset

_CSS = """
html, body { margin: 0; background: #0a0c14; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
.wrap { position: relative; height: 340px; border: 1px solid #1e293b; border-radius: 8px; overflow: hidden; }
#anMap { position: absolute; inset: 0; background: #07080c; }
#anNote { position: absolute; left: 0; right: 0; top: 12px; text-align: center; color: #94a3b8; z-index: 500; pointer-events: none; }
.an-blip { background: none; border: none; }
.an-blip svg { display: block; filter: drop-shadow(0 0 2px #000); }
.an-tag { background: none; border: none; }
.an-tag-box { display: inline-block; min-width: 92px; padding: 4px 8px; background-color: #11131f; border: 1px solid #334155; border-left: 3px solid #94a3b8; border-radius: 3px; color: #cbd5e1;
  font-size: 12px; line-height: 1.4; white-space: nowrap; cursor: grab; user-select: none; }
.an-tag-box b { color: #f8fafc; font-weight: 600; }
.an-tag-box:active { cursor: grabbing; }
.an-why { color: #94a3b8; font-size: 11px; }
.an-tag-box.hot { animation: anHot 1.4s ease-out; }
@keyframes anHot { from { border-color: #fbbf24; background-color: #2a2413; } to { border-color: #334155; background-color: #11131f; } }
@media (prefers-reduced-motion: reduce) { .an-tag-box.hot { animation: none; } }
"""


def anomaly_map_document(points):
    """One self-contained HTML page: a small map of the anomalous aircraft; `points` = [{"lat","lon","callsign","title","severity"}]."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + _CSS + "</style></head><body>"
        "<div class='wrap'><div id='anMap'></div><div id='anNote'></div></div>"
        "<script>const ANOMALY_MAP_DATA = " + _js({"points": points}) + ";</script>"
        "<script>" + asset("anomaly_map.js") + "</script></body></html>"
    )
