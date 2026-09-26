import json

import streamlit as st

# Keeps the table settings (columns, fleet and rules filters, airlines) in the browser's localStorage, the same way pin_sync.py keeps pinned regions:
#  - "save": the settings differ from the defaults: store them
#  - "clear": the visitor went back to the defaults during this visit: forget the stored ones
#  - "restore": a fresh visit on the defaults: if the browser has stored settings, type them into the hidden field vs_prefs_restore, which the
#    server validates before using anything
_JS = """
(function () {
    const MODE = __MODE__, DATA = __DATA__, KEY = "vs_table_prefs";
    try {
        const w = window.parent, store = w.localStorage;
        if (MODE === "save") { store.setItem(KEY, DATA); return; }
        if (MODE === "clear") { store.removeItem(KEY); return; }
        const saved = store.getItem(KEY) || "";
        if (!saved || saved.length > 800) return;
        let tries = 0;
        const send = () => {
            const input = w.document.querySelector('input[aria-label="vs_prefs_restore"]');
            if (!input) { if (++tries < 40) setTimeout(send, 250); return; }
            const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, "value").set;
            setter.call(input, saved);
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


def render_table_prefs_sync(mode, data=""):
    js = _JS.replace("__MODE__", json.dumps(mode)).replace("__DATA__", json.dumps(data).replace("</", "<\/"))
    st.iframe(f"<style>html,body{{margin:0;padding:0;overflow:hidden;background:transparent}}</style><script>{js}</script>", height=1)
