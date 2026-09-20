import json

import streamlit as st

# Keeps the pinned FIR regions in the browser's localStorage, so they survive leaving the site (the URL alone cannot: ?pins= is lost on a fresh visit).
#  - pins present: store them
#  - no pins and the user has just unpinned the last one (`cleared`): clear the store
#  - no pins otherwise (a fresh visit): if the browser has stored pins, hand them to the server through a hidden text field (a sandboxed
#    iframe may not navigate the page, but it can type into a field; the same trick as the member rating lookup)
# (Clearing is tied to the click, not to "no pins": Streamlit reruns right after the first render and that must not wipe the store.)
_JS = """
(function () {
    const PINS = __PINS__, CLEARED = __CLEARED__, KEY = "vs_pins";
    try {
        const w = window.parent, store = w.localStorage;
        if (PINS.length) { store.setItem(KEY, PINS.join(",")); return; }
        if (CLEARED) { store.removeItem(KEY); return; }
        const saved = (store.getItem(KEY) || "").split(",").filter(p => /^[A-Z]{1,2}$/.test(p)).slice(0, 8);
        if (!saved.length) return;
        let tries = 0;
        const send = () => {
            const input = w.document.querySelector('input[aria-label="vs_pins_restore"]');
            if (!input) { if (++tries < 40) setTimeout(send, 250); return; }
            const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, "value").set;
            setter.call(input, saved.join(","));
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


def render_pin_sync(pins, cleared):
    js = _JS.replace("__PINS__", json.dumps(list(pins))).replace("__CLEARED__", "true" if cleared else "false")
    st.iframe(f"<style>html,body{{margin:0;padding:0;overflow:hidden;background:transparent}}</style><script>{js}</script>", height=1)
