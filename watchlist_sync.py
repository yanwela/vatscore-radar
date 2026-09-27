import json

import streamlit as st

# Keeps the Member Watchlist (CIDs and callsigns, each optionally with a note) in the browser's localStorage, the
# same way pin_sync.py keeps pinned regions:
#  - "save": whatever is currently typed, if any field is non-empty: store it
#  - "clear": every field is empty during this visit (the visitor cleared them all): forget the stored copy
#  - "restore": a fresh visit with every field empty: if the browser has a stored watchlist, type its JSON into one hidden
#    field, which the server then parses and validates before using anything
_JS = """
(function () {
    const MODE = __MODE__, VALUES = __VALUES__, KEY = "vs_watchlist";
    try {
        const w = window.parent, store = w.localStorage;
        if (MODE === "save") { store.setItem(KEY, JSON.stringify(VALUES)); return; }
        if (MODE === "clear") { store.removeItem(KEY); return; }
        const raw = store.getItem(KEY);
        if (!raw || raw.length > 1600) return;
        let tries = 0;
        const send = () => {
            const input = w.document.querySelector('input[aria-label="vs_watch_restore"]');
            if (!input) { if (++tries < 40) setTimeout(send, 250); return; }
            const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, "value").set;
            setter.call(input, raw);
            input.dispatchEvent(new w.Event("input", { bubbles: true }));
            const enter = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true };
            input.dispatchEvent(new w.KeyboardEvent("keydown", enter));
            input.dispatchEvent(new w.KeyboardEvent("keypress", enter));
            input.dispatchEvent(new w.KeyboardEvent("keyup", enter));
        };
        send();
    } catch (e) {}
})();
"""


def render_watchlist_sync(mode, values=None):
    js = _JS.replace("__MODE__", json.dumps(mode)).replace("__VALUES__", json.dumps(values or {}))
    st.iframe(f"<style>html,body{{margin:0;padding:0;overflow:hidden;background:transparent}}</style><script>{js}</script>", height=1)
