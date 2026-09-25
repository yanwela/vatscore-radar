// Live airport map of one airport (tower zone): the OpenStreetMap ground layout (airport_layout.js) on satellite imagery with the aircraft that are on the ground
// or within the tower zone right now. The browser polls the public VATSIM feed itself, so the planes move without any Streamlit rerun.
// Expects LIVE_DATA = {icao, name, lat, lon, elevation, layout|null, layoutState, hide[]} (see airport_live_view.py).
(function () {
    const D = LIVE_DATA;
    const LEAFLET_BASE = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
    const LEAFLET_SRI = {
        "leaflet.css": "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H",
        "leaflet.js": "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
    };
    const FEED_URL = "https://data.vatsim.net/v3/vatsim-data.json";
    const POLL_MS = 15000, ZONE_NM = 8, ZONE_AGL_FT = 3500, GROUND_AGL_FT = 100, ELEV = Number(D.elevation) || 0;
    const COLORS = { dep: "#f59e0b", arr: "#22d3ee", other: "#a78bfa" };
    const HIDE = new Set((D.hide || []).map(String));
    const $ = id => document.getElementById(id);
    const planes = {};
    let map = null, layer = null, lastOk = null;

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

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

    function distNm(lat1, lon1, lat2, lon2) {
        const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r;
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
        return 3440.065 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    function kindOf(p) {
        const fp = p.flight_plan || {};
        const dep = String(fp.departure || "").toUpperCase(), arr = String(fp.arrival || "").toUpperCase();
        return dep === D.icao ? "dep" : arr === D.icao ? "arr" : "other";
    }

    function nearby(pilots) {
        const out = [];
        (Array.isArray(pilots) ? pilots : []).forEach(p => {
            if (!p || typeof p !== "object" || !p.callsign || HIDE.has(String(p.callsign))) return;
            const lat = Number(p.latitude), lon = Number(p.longitude), alt = Number(p.altitude);
            if (!isFinite(lat) || !isFinite(lon) || !isFinite(alt)) return;
            const d = distNm(lat, lon, D.lat, D.lon), agl = alt - ELEV;
            if (d > ZONE_NM || agl > ZONE_AGL_FT) return;
            out.push({ p: p, callsign: String(p.callsign), lat: lat, lon: lon, agl: agl, gs: Number(p.groundspeed) || 0, hdg: Number(p.heading) || 0,
                       ground: agl <= GROUND_AGL_FT, dist: d, kind: kindOf(p) });
        });
        return out;
    }

    function makeMarker(r) {
        const box = el("div", "ar-ac");
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", "26"); svg.setAttribute("height", "26");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", "M12 1.5 L14.2 9.5 L22 14 L22 16.2 L14.2 13.8 L13.6 19.5 L16 21.3 L16 22.6 L12 21.6 L8 22.6 L8 21.3 L10.4 19.5 L9.8 13.8 L2 16.2 L2 14 L9.8 9.5 Z");
        path.setAttribute("stroke", "#0a0c14"); path.setAttribute("stroke-width", "1");
        svg.appendChild(path);
        const tag = el("span", "ar-tag", r.callsign);
        box.appendChild(svg); box.appendChild(tag);
        const marker = L.marker([r.lat, r.lon], { icon: L.divIcon({ className: "ar-ac-wrap", html: box, iconSize: [0, 0], iconAnchor: [0, 0] }), keyboard: false, interactive: false });
        return { marker: marker, svg: svg, path: path, box: box };
    }

    function altText(r) {
        if (r.ground) return "on ground · " + Math.round(r.gs) + " kt";
        return Math.round((r.agl + ELEV) / 100) * 100 + " ft · " + Math.round(r.gs) + " kt";
    }

    function fillList(rows) {
        const box = $("lvList");
        box.textContent = "";
        if (!rows.length) { box.appendChild(el("div", "ar-dim", "No aircraft on the ground or in the tower zone right now.")); return; }
        rows.forEach(r => {
            const row = el("div", "ar-row");
            const dot = el("span", "ar-dot"); dot.style.backgroundColor = COLORS[r.kind];
            row.appendChild(dot);
            row.appendChild(el("b", "", r.callsign));
            const fp = r.p.flight_plan || {};
            row.appendChild(el("span", "ar-dim", (fp.aircraft_short ? fp.aircraft_short + " · " : "") + (fp.departure || "----") + " → " + (fp.arrival || "----")));
            row.appendChild(el("span", "ar-dim", altText(r)));
            box.appendChild(row);
        });
    }

    function update(pilots) {
        const rows = nearby(pilots).sort((a, b) => (b.ground - a.ground) || (a.dist - b.dist));
        const seen = new Set();
        rows.forEach(r => {
            let pl = planes[r.callsign];
            if (!pl) { pl = planes[r.callsign] = makeMarker(r); layer.addLayer(pl.marker); }
            pl.marker.setLatLng([r.lat, r.lon]);
            pl.svg.style.transform = "rotate(" + Math.round(r.hdg) + "deg)";
            pl.path.setAttribute("fill", COLORS[r.kind]);
            pl.box.style.opacity = r.ground ? "1" : "0.85";
            seen.add(r.callsign);
        });
        Object.keys(planes).forEach(cs => { if (!seen.has(cs)) { layer.removeLayer(planes[cs].marker); delete planes[cs]; } });
        const onGround = rows.filter(r => r.ground).length;
        $("lvGround").textContent = onGround;
        $("lvAir").textContent = rows.length - onGround;
        fillList(rows);
    }

    function clock(t) {
        const d = new Date(t);
        return d.toISOString().slice(11, 19) + "Z";
    }

    async function poll() {
        try {
            const resp = await fetch(FEED_URL, { cache: "no-store" });
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            const feed = await resp.json();
            update(feed.pilots);
            lastOk = Date.now();
            $("lvFeed").textContent = clock(lastOk);
            $("lvNote").textContent = "";
        } catch (e) {
            $("lvNote").textContent = lastOk ? "The VATSIM feed did not answer, showing the last positions (from " + clock(lastOk) + ")." : "The VATSIM feed could not be loaded.";
        }
    }

    function layoutBounds(layout) {
        const pts = [];
        ["runways", "taxiways", "aprons"].forEach(k => (layout[k] || []).forEach(o => (o.pts || []).forEach(p => pts.push(p))));
        return pts.length ? L.latLngBounds(pts).pad(0.08) : null;
    }

    function hasLayout(l) {
        return !!l && Array.isArray(l.taxiways) && Array.isArray(l.runways) && (l.taxiways.length > 0 || l.runways.length > 0);
    }

    async function start() {
        $("lvTitle").textContent = D.icao;
        $("lvMeta").textContent = D.name || "";
        $("lvFoot").textContent = "Aircraft on the ground and within " + ZONE_NM + " NM below " + ZONE_AGL_FT.toLocaleString("en-US") + " ft AGL (the tower zone), from the public VATSIM feed, refreshed every " + POLL_MS / 1000 + " s.";
        try { await loadLeaflet(); } catch (e) { $("lvNote").textContent = "Map library could not be loaded"; return; }
        map = L.map("arMap", { minZoom: 6, attributionControl: true, zoomSnap: 0.25 });
        map.setView([D.lat, D.lon], 13);
        L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19,
            attribution: "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community" }).addTo(map);
        L.circleMarker([D.lat, D.lon], { radius: 4, color: "#e2e8f0", weight: 1.5, fillColor: "#0a0c14", fillOpacity: 1 })
            .bindTooltip(el("span", "", D.icao), { permanent: true, direction: "top", offset: [0, -6], className: "ar-airport-tip" }).addTo(map);
        let bounds = null;
        if (hasLayout(D.layout)) { drawAirportLayout(map, D.layout); bounds = layoutBounds(D.layout); }
        else {
            $("lvFoot").textContent += " " + (D.layoutState === "retrying"
                ? "The airport layout (taxiways, stands) is being fetched in the background and appears here on its own within a minute or two."
                : "OpenStreetMap has no taxiway data for " + D.icao + ", so only the satellite image is shown.");
        }
        layer = L.layerGroup().addTo(map);
        map.fitBounds(bounds || L.latLng(D.lat, D.lon).toBounds(3.2 * 1852));
        poll();
        setInterval(poll, POLL_MS);
    }

    start();
})();
