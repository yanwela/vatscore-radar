// ATC replay: plays back the traffic one controller position worked during a session: an airport position (DEL / GND / TWR / APP, a circle around
// the airport) or an area position (CTR / FSS, the VATSpy boundary of the airspace).
// Expects ATC_DATA (see atc_replay_view.py), replay_core.js (replayStateAt, replayIndexAt, replayNextTime, replayClock, replayDuration) and atc_zone.js.
(function () {
    const D = ATC_DATA, S = D.session, ROLE = S.role, zone = atcZone(ROLE), IS_AREA = S.kind === "area";
    const AP = IS_AREA ? { icao: D.area.name, name: "", lat: D.area.lat, lon: D.area.lon, elevation: 0 } : D.airport;
    const LEAFLET_BASE = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
    const LEAFLET_SRI = {
        "leaflet.css": "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H",
        "leaflet.js": "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
    };
    // ground positions look at the real airport layout (satellite imagery); approach uses the same dark canvas as the Flight Record map
    const GROUND = !IS_AREA && (ROLE === "DEL" || ROLE === "GND" || ROLE === "TWR");
    const TILES = GROUND
        ? { url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", maxZoom: 19,
            attribution: "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community" }
        : { url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", maxZoom: 12,
            attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, OpenStreetMap contributors, and the GIS user community" };
    const DIR_COLOR = { out: "#f59e0b", "in": "#22d3ee", local: IS_AREA ? "#34d399" : "#a78bfa" };
    const DIR_LABEL = { out: "Outbound", "in": "Inbound", local: IS_AREA ? "Through" : "Local" };
    const ROLE_TEXT = {
        DEL: "Departures on the ground within " + zone.radiusNm + " NM, until they start the take-off roll.",
        GND: "Aircraft on the ground within " + zone.radiusNm + " NM (push-back, taxi, stands). Arrivals appear " + Math.round(zone.leadS / 60) + " min before they touch down.",
        TWR: "Runway and circuit: aircraft within " + zone.radiusNm + " NM below 3,500 ft AGL. Arrivals appear " + Math.round(zone.leadS / 60) + " min early, departures stay " + Math.round(zone.tailS / 60) + " min after leaving.",
        CTR: "Aircraft inside the " + (IS_AREA ? D.area.name : "") + " airspace (VATSpy boundary). Flights appear " + Math.round(zone.leadS / 60) + " min before they enter and stay " + Math.round(zone.tailS / 60) + " min after they leave.",
        FSS: "Aircraft inside the " + (IS_AREA ? D.area.name : "") + " airspace (VATSpy boundary). Flights appear " + Math.round(zone.leadS / 60) + " min before they enter and stay " + Math.round(zone.tailS / 60) + " min after they leave.",
        APP: "Aircraft within " + zone.radiusNm + " NM between 300 and 15,000 ft AGL. Inbounds appear " + Math.round(zone.leadS / 60) + " min before they enter, outbounds stay " + Math.round(zone.tailS / 60) + " min after they leave."
    }[ROLE];
    const TRAIL_S = ROLE === "TWR" ? 300 : 240;
    const AREA_MIN_GS = 80;  // an area controller does not work aircraft that are taxiing or still on the take-off roll inside the boundary
    const SPEEDS = [1, 10, 30, 60, 120, 300];
    const tStart = S.on, tEnd = S.off;
    const $ = id => document.getElementById(id);

    // only flights that really touch the zone matter; each keeps the spans in which it is inside
    const flights = D.flights.filter(f => Array.isArray(f.points) && f.points.length > 1)
        .map(f => Object.assign({}, f, { spans: IS_AREA ? atcPolySpans(f.points.filter(p => (p[4] || 0) >= AREA_MIN_GS), D.area.rings) : atcFlightSpans(f.points, AP, ROLE, f.direction), first: f.points[0][3], last: f.points[f.points.length - 1][3] }))
        .filter(f => f.spans.length);
    const handled = flights.filter(f => f.spans.some(sp => sp[1] >= tStart && sp[0] <= tEnd)).length;
    let t = tStart, playing = false, timer = null, speed = 60, map = null, layer = null;

    (function pickSpeed() {
        const wanted = Math.max(1, tEnd - tStart) / 120;
        speed = SPEEDS.reduce((best, s) => Math.abs(s - wanted) < Math.abs(best - wanted) ? s : best, SPEEDS[0]);
    })();

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

    function planeIcon(f) {
        const box = el("div", "ar-ac");
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", GROUND ? "26" : "20"); svg.setAttribute("height", GROUND ? "26" : "20");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", "M12 1.5 L14.2 9.5 L22 14 L22 16.2 L14.2 13.8 L13.6 19.5 L16 21.3 L16 22.6 L12 21.6 L8 22.6 L8 21.3 L10.4 19.5 L9.8 13.8 L2 16.2 L2 14 L9.8 9.5 Z");
        path.setAttribute("stroke", "#0a0c14"); path.setAttribute("stroke-width", "1");
        svg.appendChild(path);
        const tag = el("span", "ar-tag", f.callsign);
        box.appendChild(svg); box.appendChild(tag);
        f.ui = { box: box, svg: svg, path: path, tag: tag };
        return L.divIcon({ className: "ar-ac-wrap", html: box, iconSize: [0, 0], iconAnchor: [0, 0] });
    }

    function place(f, s, state) {
        if (!f.marker) {
            f.marker = L.marker([s.lat, s.lon], { icon: planeIcon(f), keyboard: false, interactive: false });
            f.trail = L.polyline([], { weight: 2, opacity: 0.8, interactive: false });
        }
        if (!layer.hasLayer(f.marker)) { layer.addLayer(f.trail); layer.addLayer(f.marker); }
        const color = state === "in" ? DIR_COLOR[f.direction] : "#94a3b8";
        f.marker.setLatLng([s.lat, s.lon]);
        f.ui.svg.style.transform = "rotate(" + Math.round(s.heading || 0) + "deg)";
        f.ui.path.setAttribute("fill", color);
        f.ui.box.style.opacity = state === "in" ? "1" : "0.55";
        f.ui.tag.style.opacity = state === "in" ? "1" : "0.7";
        const idx = Math.max(0, replayIndexAt(f.points, t)), line = [];
        for (let i = idx; i >= 0 && line.length < 80 && f.points[i][3] >= t - TRAIL_S; i--) line.unshift([f.points[i][0], f.points[i][1]]);
        line.push([s.lat, s.lon]);
        f.trail.setLatLngs(line);
        f.trail.setStyle({ color: color, opacity: state === "in" ? 0.85 : 0.4, dashArray: state === "in" ? null : "3 5" });
    }

    function hide(f) {
        if (f.marker && layer.hasLayer(f.marker)) { layer.removeLayer(f.marker); layer.removeLayer(f.trail); }
    }

    function altText(f, s) {
        const agl = Math.round((s.alt - (AP.elevation || 0)) / 100) * 100;
        if (agl <= 200 && s.gs < 40) return "on ground";
        return (GROUND ? agl.toLocaleString("en-US") + " ft AGL" : Math.round(s.alt / 100) * 100 >= 18000 ? "FL" + Math.round(s.alt / 1000) * 10 : Math.round(s.alt / 100) * 100 + " ft");
    }

    function fillList(rows) {
        const box = $("arList");
        box.textContent = "";
        [["in", "In the zone"], ["lead", "Approaching the zone"], ["tail", "Just left the zone"]].forEach(([key, title]) => {
            if (!rows[key].length) return;
            const head = el("div", "ar-sec", title + " (" + rows[key].length + ")");
            box.appendChild(head);
            rows[key].sort((a, b) => a.f.callsign.localeCompare(b.f.callsign)).forEach(r => {
                const row = el("div", "ar-row");
                const dot = el("span", "ar-dot"); dot.style.backgroundColor = key === "in" ? DIR_COLOR[r.f.direction] : "#64748b";
                row.appendChild(dot);
                row.appendChild(el("b", "", r.f.callsign));
                row.appendChild(el("span", "ar-dim", (r.f.aircraft ? r.f.aircraft.split("/")[0] + " · " : "") + (r.f.departure || "----") + " → " + (r.f.destination || "----")));
                row.appendChild(el("span", "ar-dim", DIR_LABEL[r.f.direction] + " · " + altText(r.f, r.s) + " · " + Math.round(r.s.gs) + " kt"));
                box.appendChild(row);
            });
        });
        if (!box.childNodes.length) box.appendChild(el("div", "ar-dim", "No aircraft in or near the zone at this moment."));
    }

    function setTime(tt) {
        t = Math.max(tStart, Math.min(tEnd, tt));
        const rows = { "in": [], lead: [], tail: [] };
        flights.forEach(f => {
            const state = t >= f.first && t <= f.last ? atcVisibility(f.spans, t, f.direction, ROLE) : null;
            if (!state) { hide(f); return; }
            const s = replayStateAt(f.points, t);
            place(f, s, state);
            rows[state].push({ f: f, s: s });
        });
        $("arCount").textContent = rows["in"].length;
        $("arLead").textContent = rows.lead.length;
        $("arTail").textContent = rows.tail.length;
        $("arTime").textContent = replayClock(t) + "  ·  " + replayDuration(t - tStart) + " / " + replayDuration(tEnd - tStart);
        $("arScrub").value = String(Math.round(t));
        fillList(rows);
    }

    function setPlaying(on) {
        playing = on;
        $("arPlay").textContent = on ? "Pause" : "Play";
        if (timer) { clearInterval(timer); timer = null; }
        if (on) {
            if (t >= tEnd) setTime(tStart);
            timer = setInterval(() => {
                const next = t + 0.25 * speed;
                if (next >= tEnd) { setTime(tEnd); setPlaying(false); } else setTime(next);
            }, 250);
        }
    }

    function buildUi() {
        $("arTitle").textContent = S.callsign;
        $("arMeta").textContent = (IS_AREA ? D.area.name : AP.icao + " " + (AP.name || "")) + "  ·  " + replayClock(tStart) + "–" + replayClock(tEnd);
        if (IS_AREA) {
            const legend = document.querySelector(".ar-legend");
            legend.textContent = "";
            [["#34d399", "In the airspace"], ["#64748b", "About to enter / just left"]].forEach(([c, label]) => {
                const item = el("span"), dot = el("i");
                dot.style.background = c; item.appendChild(dot); item.appendChild(document.createTextNode(label)); legend.appendChild(item);
            });
        }
        $("arRole").textContent = ROLE_TEXT;
        $("arHandled").textContent = handled;
        const stats = D.stats || {};
        $("arNote").textContent = stats.found === undefined ? "" :
            stats.tracked + " of " + stats.found + " flights of this session have a recorded track (statsim keeps tracks of a pilot's last 60 flights only). " +
            (IS_AREA ? "Flights are picked from their planned great-circle route and confirmed by their recorded track" + (stats.capped ? "; a busy airspace is capped at " + stats.found + " flights, so not every flight is shown." : ".")
                     : "Local and VFR flights appear when their flight plan names " + AP.icao + "; pilots without any flight plan are not in statsim's airport data.");
        const scrub = $("arScrub");
        scrub.min = String(Math.floor(tStart)); scrub.max = String(Math.ceil(tEnd)); scrub.value = String(Math.floor(tStart));
        scrub.oninput = e => setTime(Number(e.target.value));
        $("arPlay").onclick = () => setPlaying(!playing);
        const sel = $("arSpeed");
        sel.innerHTML = SPEEDS.map(s => '<option value="' + s + '">' + s + "×</option>").join("");
        sel.value = String(speed);
        sel.onchange = () => { speed = Number(sel.value); };
    }

    async function start() {
        buildUi();
        try { await loadLeaflet(); } catch (e) { $("arMapNote").textContent = "Map library could not be loaded"; return; }
        map = L.map("arMap", { minZoom: 2, attributionControl: true, zoomSnap: 0.25 });
        map.setView([AP.lat, AP.lon], IS_AREA ? 5 : 11);  // a circle / polygon needs a view before its bounds can be computed
        L.tileLayer(TILES.url, { maxZoom: TILES.maxZoom, attribution: TILES.attribution }).addTo(map);
        let areaShape = null;
        if (IS_AREA) {
            areaShape = L.polygon(D.area.rings, { color: "#3b82f6", weight: 1.5, dashArray: "6 6", fillOpacity: 0.06, interactive: false }).addTo(map);
        } else {
            L.circle([AP.lat, AP.lon], { radius: zone.radiusNm * 1852, color: "#3b82f6", weight: 1.5, dashArray: "6 6", fill: true, fillOpacity: 0.05, interactive: false }).addTo(map);
            L.circleMarker([AP.lat, AP.lon], { radius: 4, color: "#e2e8f0", weight: 1.5, fillColor: "#0a0c14", fillOpacity: 1 })
                // el(...) returns a real element (.textContent), never a bare string: Leaflet renders a string tooltip through
                // innerHTML, and AP.icao ultimately traces back to server data - always go through a safe node, not a string.
                .bindTooltip(el("span", "", AP.icao), { permanent: true, direction: "top", offset: [0, -6], className: "ar-airport-tip" }).addTo(map);
        }
        layer = L.layerGroup().addTo(map);
        // ground positions are zoomed in on the airfield itself (the taxiways are within ~1 NM), the zone ring reaches beyond the view; pan or zoom out to follow approaching aircraft
        const VIEW_NM = { DEL: 1.3, GND: 1.3, TWR: 4.5, APP: zone.radiusNm * 1.35 }[ROLE];
        map.fitBounds(IS_AREA ? areaShape.getBounds().pad(0.1) : L.latLng(AP.lat, AP.lon).toBounds(VIEW_NM * 2 * 1852));
        if (!flights.length) $("arMapNote").textContent = "No recorded tracks for the traffic of this session.";
        setTime(tStart);
    }

    start();
})();
