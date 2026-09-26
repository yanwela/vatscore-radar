(function () {
    const D = ANOMALY_MAP_DATA;
    const LEAFLET_BASE = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
    const LEAFLET_SRI = {
        "leaflet.css": "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H",
        "leaflet.js": "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
    };
    const COLOR = { high: "#fb7185", medium: "#fb923c", low: "#facc15" };
    const VIEW_KEY = "anMapView";
    const note = document.getElementById("anNote");

    function loadLeaflet() {
        if (window.L) return Promise.resolve();
        return new Promise((resolve, reject) => {
            const css = document.createElement("link");
            css.rel = "stylesheet"; css.href = LEAFLET_BASE + "leaflet.css"; css.integrity = LEAFLET_SRI["leaflet.css"]; css.crossOrigin = "anonymous";
            document.head.appendChild(css);
            const js = document.createElement("script");
            js.src = LEAFLET_BASE + "leaflet.js"; js.integrity = LEAFLET_SRI["leaflet.js"]; js.crossOrigin = "anonymous";
            js.onload = () => resolve(); js.onerror = () => reject(new Error("leaflet failed to load"));
            document.head.appendChild(js);
        });
    }

    function saved() {
        try { return JSON.parse(window.parent.sessionStorage.getItem(VIEW_KEY) || "null"); } catch (e) { return null; }
    }

    function save(map) {
        try {
            const c = map.getCenter();
            window.parent.sessionStorage.setItem(VIEW_KEY, JSON.stringify({ lat: c.lat, lon: c.lng, zoom: map.getZoom() }));
        } catch (e) {}
    }

    async function start() {
        try { await loadLeaflet(); } catch (e) { note.textContent = "Map library could not be loaded"; return; }
        const pts = (D.points || []).filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lon));
        const map = L.map("anMap", { minZoom: 2, attributionControl: true, worldCopyJump: true });
        L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16,
            attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ" }).addTo(map);
        const prev = saved();
        if (prev) map.setView([prev.lat, prev.lon], prev.zoom);
        else if (pts.length) map.fitBounds(L.latLngBounds(pts.map(p => [p.lat, p.lon])), { padding: [40, 40], maxZoom: 7 });
        else map.setView([30, 10], 2);
        const marks = [];
        const fl = alt => (alt >= 18000 ? "FL" + String(Math.round(alt / 100)).padStart(3, "0") : Math.round(alt).toLocaleString("en-US") + " ft");
        const tagLL = (ll, off) => map.containerPointToLatLng(map.latLngToContainerPoint(ll).add(L.point(off.x, off.y)));
        for (const p of pts) {
            const color = COLOR[p.severity] || "#94a3b8";
            const ll = L.latLng(p.lat, p.lon);
            const svg = '<svg viewBox="0 0 24 24" width="24" height="24" style="transform:rotate(' + (Number(p.heading) || 0) + 'deg)">' +
                '<path d="M12 3 L19 20 L12 16 L5 20 Z" fill="' + color + '" stroke="#0a0c14" stroke-width="1.2" stroke-linejoin="round"/></svg>';
            const plane = L.marker(ll, { icon: L.divIcon({ className: "an-blip", html: svg, iconSize: [24, 24], iconAnchor: [12, 12] }), zIndexOffset: 1000, keyboard: false }).addTo(map);
            const box = document.createElement("div");
            box.className = "an-tag-box";
            box.style.borderLeftColor = color;
            const head = document.createElement("b"); head.textContent = p.callsign; box.appendChild(head);
            box.appendChild(document.createElement("br"));
            box.appendChild(document.createTextNode((p.aircraft || "N/A") + " · " + fl(p.alt || 0)));
            box.appendChild(document.createElement("br"));
            box.appendChild(document.createTextNode(Math.round(p.gs || 0) + " kt"));
            for (const t of p.titles) { box.appendChild(document.createElement("br")); const s2 = document.createElement("span"); s2.className = "an-why"; s2.textContent = t; box.appendChild(s2); }
            let off = { x: 22, y: -44 };
            const tag = L.marker(tagLL(ll, off), { draggable: true, keyboard: false, zIndexOffset: 900, icon: L.divIcon({ className: "an-tag", html: box, iconSize: [0, 0], iconAnchor: [0, 0] }) }).addTo(map);
            const leader = L.polyline([ll, tag.getLatLng()], { color: "#94a3b8", weight: 1, opacity: 0.8, interactive: false }).addTo(map);
            tag.on("drag", e => leader.setLatLngs([ll, e.latlng]));
            tag.on("dragend", () => { const a1 = map.latLngToContainerPoint(ll), b1 = map.latLngToContainerPoint(tag.getLatLng()); off = { x: b1.x - a1.x, y: b1.y - a1.y }; });
            map.on("zoomend", () => { tag.setLatLng(tagLL(ll, off)); leader.setLatLngs([ll, tag.getLatLng()]); });
            marks.push({ callsign: p.callsign, box: box });
        }
        map.on("moveend", () => save(map));
        note.textContent = pts.length ? "" : "No anomalies to show right now";
        if (D.focus) {
            const f = pts.find(p => p.callsign === D.focus);
            if (f) map.setView([f.lat, f.lon], Math.min(Math.max(map.getZoom(), 8), 16));
        }
        // rows of the table (in the parent page) call this to bring an aircraft into view
        try {
            window.parent.__anPan = function (lat, lon, callsign) {
                map.setView([lat, lon], Math.min(Math.max(map.getZoom(), 8), 16), { animate: true });
                marks.forEach(m => { m.box.classList.remove("hot"); if (m.callsign === callsign) { void m.box.offsetWidth; m.box.classList.add("hot"); } });
            };
            const doc = window.parent.document;
            if (!window.parent.__anClickBound) {
                window.parent.__anClickBound = true;
                doc.addEventListener("click", ev => {
                    if (ev.target.closest("a")) return;
                    const row = ev.target.closest && ev.target.closest("tr[data-an-lat]");
                    if (!row || !window.parent.__anPan) return;
                    const lat = parseFloat(row.dataset.anLat), lon = parseFloat(row.dataset.anLon);
                    if (Number.isFinite(lat) && Number.isFinite(lon)) window.parent.__anPan(lat, lon, row.dataset.anCs || "");
                });
            }
        } catch (e) {}
    }
    start();
})();
