import json
from html import escape
from urllib.parse import urlencode, urlsplit

import streamlit as st

from page_views import record_view

PAGE_VIEWS_FILE = "page_views.jsonl"
SITE_BANNER_FILE = "site_banner.json"
CID_BLOCKLIST_FILE = "cid_blocklist.json"

# Look of the stats pages (Network Stats, CID Stats, Airport).
INK, PANEL, LINE = "#0a0e1a", "#10141f", "#1f2937"
SUBTLE, TEXT = "#5b6b82", "#e8eef7"
CYAN, VIOLET, AMBER, EMERALD, ROSE = "#22d3ee", "#8b5cf6", "#fbbf24", "#34d399", "#fb7185"

_CSS = f"""
[data-testid="stAppViewContainer"], [data-testid="stApp"] {{ background-color: {INK} !important; }}
[data-testid="stSidebarNav"] {{ display: none !important; }}
[data-testid="stSidebar"] {{ display: none !important; }}
header, footer {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ display: none; }}
div[data-testid="stElementContainer"]:has(iframe[srcdoc*="vs-title-sync"]) {{ display: none; }}
[data-stale="true"] {{ opacity: 1 !important; transition: none !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: #94a3b8 !important; }}
[data-testid="stTextInput"] div[data-baseweb="input"], [data-testid="stTextInput"] input {{
    background-color: {PANEL} !important; color: {TEXT} !important; }}
[data-testid="stTextInput"] div[data-baseweb="input"] {{ border: 1px solid {LINE} !important; }}
[data-testid="stTextInput"] input::placeholder {{ color: #64748b !important; opacity: 1; }}
h1, h2, h3 {{ color: {CYAN} !important; font-family: 'Segoe UI', sans-serif; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ color: #94a3b8; font-size: 15px; }}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {{ color: {CYAN}; }}
[data-testid="stTabs"] [aria-selected="true"] {{ color: {CYAN} !important; font-weight: bold; }}
.vs-card {{ background:{PANEL}; border:1px solid {LINE}; border-radius:10px; padding:14px 16px; text-align:center; }}
.vs-kpi-label {{ font-size:10px; letter-spacing:1.5px; text-transform:uppercase; color:{SUBTLE}; font-weight:700; }}
.vs-kpi-val {{ font-size:24px; font-weight:800; line-height:1.1; margin-top:6px; font-variant-numeric:tabular-nums; }}
.vs-sub {{ font-size:12px; color:{SUBTLE}; margin-top:4px; }}
"""

# Runs inside a same-origin iframe and keeps the browser tab title in sync:
# a fixed section name for plain pages, or the selected top-level tab for the radar.
_TITLE_JS = """/*vs-title-sync*/
// This iframe only runs a script: remove it (and its Streamlit wrapper) from the layout.
try {
  const box = window.frameElement.closest('[data-testid="stElementContainer"]') || window.frameElement;
  box.style.display = "none";
} catch (e) {}
const BASE = "VatScoreRadar";
const FIXED = __FIXED__;
const LABELS = __LABELS__;
let last = null;
function section() {
  if (FIXED) return FIXED;
  const sel = window.parent.document.querySelector('[data-baseweb="tab-list"] button[aria-selected="true"]');
  if (!sel) return "";
  const text = sel.textContent.trim();
  return LABELS.find(l => text.endsWith(l)) || "";
}
function apply() {
  try {
    const s = section();
    const title = s ? BASE + " - " + s : BASE;
    if (window.parent.document.title !== title) window.parent.document.title = title;
    if (title !== last) {
      last = title;
      // Hosts that embed the app (e.g. Streamlit Community Cloud) own the outer tab title.
      try { window.top.postMessage({ stCommVersion: 1, type: "SET_PAGE_TITLE", title: title }, "*"); } catch (e) {}
    }
  } catch (e) {}
}
setInterval(apply, 300);
apply();
"""


def apply_base_css():
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)


def set_browser_title(section=None, labels=None):
    # A 1px script-only iframe; the script hides its own wrapper, and the body is transparent
    # with no scrollbars so nothing is visible in the moment before that happens.
    js = _TITLE_JS.replace("__FIXED__", json.dumps(section)).replace("__LABELS__", json.dumps(labels or []))
    st.iframe(f"<style>html,body{{margin:0;padding:0;overflow:hidden;background:transparent}}</style><script>{js}</script>",
              height=1)


def page_url(page, **params):
    # Absolute URL of another page of this app, so links keep working from a new browser tab.
    try:
        parts = urlsplit(st.context.url)
        base = f"{parts.scheme}://{parts.netloc}"
    except Exception:
        base = ""
    query = f"?{urlencode(params)}" if params else ""
    return f"{base}/{page}{query}"


def stat_card(label, value, color=CYAN):
    # label/value may contain API data, so they are always escaped here.
    return (f'<div class="vs-card"><div class="vs-kpi-label">{escape(str(label))}</div>'
            f'<div class="vs-kpi-val" style="color:{color};">{escape(str(value))}</div></div>')


def card_css():
    # just the KPI card rules of the theme, for a page (the live radar) that has its own base CSS
    return (f"<style>.vs-card {{ background:{PANEL}; border:1px solid {LINE}; border-radius:10px; padding:14px 16px; text-align:center; }}"
            f".vs-kpi-label {{ font-size:10px; letter-spacing:1.5px; text-transform:uppercase; color:{SUBTLE}; font-weight:700; }}"
            f".vs-kpi-val {{ font-size:24px; font-weight:800; line-height:1.1; margin-top:6px; font-variant-numeric:tabular-nums; }}</style>")


def track_page_view(page_name):
    # One count per browser session per page (not per rerun - a Streamlit script reruns on every widget interaction),
    # same convention as app.py's own "Radar Dashboard Opened" visit log.
    key = "viewed_" + page_name
    if key in st.session_state:
        return
    st.session_state[key] = True
    try:
        record_view(PAGE_VIEWS_FILE, page_name)
    except Exception:
        pass


def render_banner(banner):
    # banner is whatever site_banner.read_banner() returned (None = nothing to show); text is escaped, it comes from
    # whoever last typed it into the admin panel, kept honest exactly like every other feed-derived string in this app.
    if not banner:
        return
    fn = {"warning": st.warning, "error": st.error}.get(banner.get("level"), st.info)
    fn(escape(str(banner.get("text", ""))))


def record_card(label, value, holder, detail="", color=CYAN, runners_up=()):
    # a KPI card for a record: the value, who holds it, and optionally the runners-up as small lines (all text is escaped, it comes from the feed)
    lines = "".join(f'<div>{escape(str(line))}</div>' for line in runners_up)
    extra = (f'<div style="margin-top:10px;padding-top:8px;border-top:1px solid {LINE};font-size:11px;line-height:1.7;color:{SUBTLE};">{lines}</div>'
             if lines else "")
    return (f'<div class="vs-card"><div class="vs-kpi-label">{escape(str(label))}</div>'
            f'<div class="vs-kpi-val" style="color:{color};">{escape(str(value))}</div>'
            f'<div style="margin-top:8px;font-size:13px;font-weight:700;color:{TEXT};">{escape(str(holder))}</div>'
            f'<div style="font-size:11px;color:{SUBTLE};min-height:15px;">{escape(str(detail))}</div>{extra}</div>')
