// ── Live map inside the Flight Record window (Leaflet, loaded only when "Map" is pressed) ──
                const LEAFLET_BASE = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
                const LEAFLET_SRI = {
                    "leaflet.css": "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H",
                    "leaflet.js": "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
                };
                const VATSIM_FEED_URL = "https://data.vatsim.net/v3/vatsim-data.json";
                const MAP_REFRESH_MS = 20000;
                const TRACK_WAIT_MS = 20000;
                // CARTO's free dark tiles now stamp "API KEY REQUIRED" on every tile, so use Esri's public dark gray canvas
                // (darkened further with CSS).
                const MAP_TILES_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
                const MAP_TILES_ATTRIBUTION = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, OpenStreetMap contributors, and the GIS user community &middot; Sectors: VATSpy &amp; SimAware (CC BY-SA 4.0)";
                const ALT_STOPS = [[0, [249, 115, 22]], [12000, [234, 179, 8]], [26000, [34, 197, 94]], [40000, [56, 189, 248]]];
                const RING_STEPS_NM = [5, 10, 25, 50, 100, 250, 500, 1000];
                const ATC_ROLES = ["ATIS", "DEL", "GND", "TWR", "APP", "DEP", "CTR", "FSS"];
                const FACILITY_ROLE = { 1: "FSS", 2: "DEL", 3: "GND", 4: "TWR", 5: "APP", 6: "CTR" };
                let leafletPromise = null, flightMap = null, mapLayers = null, mapLive = null, mapTimer = null, mapBusy = false;
                let mapFlightKey = "", trackPts = [], trackNote = "", trackWhy = "", trackWait = null;
                let profMode = "alt", lastControllers = [], lastAtis = [], controllersLoaded = false, atcSpec = null;
                const mapOpts = { rings: true, atc: true, sectors: true, follow: false };
                let tagOffset = { x: 28, y: -24 };  // where the aircraft tag sits relative to the aircraft, in screen pixels (draggable)

                function loadLeaflet() {
                    if (window.L) return Promise.resolve();
                    if (leafletPromise) return leafletPromise;
                    leafletPromise = new Promise((resolve, reject) => {
                        const css = document.createElement("link");
                        css.rel = "stylesheet"; css.href = LEAFLET_BASE + "leaflet.css";
                        css.integrity = LEAFLET_SRI["leaflet.css"]; css.crossOrigin = "anonymous";
                        document.head.appendChild(css);
                        const js = document.createElement("script");
                        js.src = LEAFLET_BASE + "leaflet.js";
                        js.integrity = LEAFLET_SRI["leaflet.js"]; js.crossOrigin = "anonymous";
                        js.onload = () => resolve();
                        js.onerror = () => { leafletPromise = null; reject(new Error("leaflet failed to load")); };
                        document.head.appendChild(js);
                    });
                    return leafletPromise;
                }

                // Leaflet's bindTooltip/bindPopup run untrusted strings through innerHTML; a pilot's flight-plan departure/arrival
                // field is free text they fully control, so it must always reach Leaflet as a real DOM node (textContent), never
                // as a bare string, however "airport-code-shaped" it looks.
                function safeTipNode(text) {
                    const span = document.createElement("span");
                    span.textContent = text;
                    return span;
                }

                function airportLatLon(icao) {
                    const a = airportsDatabase[String(icao || "").toUpperCase()];
                    if (!a) return null;
                    const lat = a.latitude_deg ?? a.latitude, lon = a.longitude_deg ?? a.longitude;
                    return (typeof lat === "number" && typeof lon === "number") ? [lat, lon] : null;
                }

                // Great-circle line a -> b whose longitudes stay continuous (no jump at +-180) and start exactly at a[1].
                function gcLine(a, b, steps) {
                    const r = Math.PI / 180, deg = 180 / Math.PI;
                    const la1 = a[0] * r, lo1 = a[1] * r, la2 = b[0] * r, lo2 = b[1] * r;
                    const dist = 2 * Math.asin(Math.min(1, Math.sqrt(Math.sin((la2 - la1) / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2)));
                    if (dist < 1e-6 || Math.abs(Math.sin(dist)) < 1e-9) return [a, b];
                    const pts = [];
                    let prev = null;
                    for (let i = 0; i <= steps; i++) {
                        const f = i / steps;
                        const A = Math.sin((1 - f) * dist) / Math.sin(dist), B = Math.sin(f * dist) / Math.sin(dist);
                        const x = A * Math.cos(la1) * Math.cos(lo1) + B * Math.cos(la2) * Math.cos(lo2);
                        const y = A * Math.cos(la1) * Math.sin(lo1) + B * Math.cos(la2) * Math.sin(lo2);
                        const z = A * Math.sin(la1) + B * Math.sin(la2);
                        let lon = Math.atan2(y, x) * deg;
                        if (prev === null) lon += 360 * Math.round((a[1] - lon) / 360);
                        else { while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; }
                        prev = lon;
                        pts.push([Math.atan2(z, Math.sqrt(x * x + y * y)) * deg, lon]);
                    }
                    return pts;
                }

                // A point may sit on the "other copy" of the world than the line; shift it by 360 deg to the nearest one.
                function nearestLon(lat, lon, path) {
                    let best = lon, bestD = Infinity;
                    [-360, 0, 360].forEach(k => path.forEach(pt => {
                        const d = (pt[0] - lat) ** 2 + (pt[1] - (lon + k)) ** 2;
                        if (d < bestD) { bestD = d; best = lon + k; }
                    }));
                    return best;
                }

                // Point `nm` nautical miles from (lat, lon) on true bearing `hdg`; longitude aligned to the start longitude.
                function destPoint(lat, lon, hdg, nm) {
                    const r = Math.PI / 180, d = nm / 3440.065, b = hdg * r, la1 = lat * r, lo1 = lon * r;
                    const la2 = Math.asin(Math.sin(la1) * Math.cos(d) + Math.cos(la1) * Math.sin(d) * Math.cos(b));
                    const lo2 = lo1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la1), Math.cos(d) - Math.sin(la1) * Math.sin(la2));
                    let lonOut = lo2 / r;
                    lonOut += 360 * Math.round((lon - lonOut) / 360);
                    return [la2 / r, lonOut];
                }

                function altColor(alt) {
                    const a = Math.max(0, Math.min(40000, Math.round((Number(alt) || 0) / 1500) * 1500));
                    for (let i = 1; i < ALT_STOPS.length; i++) {
                        if (a <= ALT_STOPS[i][0]) {
                            const [a0, c0] = ALT_STOPS[i - 1], [a1, c1] = ALT_STOPS[i], f = (a - a0) / (a1 - a0);
                            return "rgb(" + c0.map((v, k) => Math.round(v + (c1[k] - v) * f)).join(",") + ")";
                        }
                    }
                    return "rgb(" + ALT_STOPS[ALT_STOPS.length - 1][1].join(",") + ")";
                }

                function fmtFt(a) { return Math.round(a || 0).toLocaleString("en-US") + " ft"; }
                function fmtFl(a) { return a >= 5000 ? "FL" + String(Math.round(a / 100)).padStart(3, "0") : Math.round(a || 0) + " ft"; }

                function setMapNote(text) {
                    const n = document.getElementById("mapNote");
                    n.textContent = text || "";
                    n.style.display = text ? "block" : "none";
                }

                // ── METAR in the airport pop-up: plain text from metar.vatsim.net (CORS is open), decoded by metar_decode.js ──
                // A page that has no use for a current METAR (the replay of an old flight) defines `const metarEnabled = false;`.
                const METAR_URL = "https://metar.vatsim.net/";
                const METAR_MAX_AGE_MS = 5 * 60 * 1000;
                const METAR_CATEGORY_COLOR = { VFR: "#16a34a", MVFR: "#2563eb", IFR: "#dc2626", LIFR: "#7c3aed" };
                const metarCache = {};

                function metarWind(m) {
                    if (m.wind_speed_kt === null) return "-";
                    if (m.wind_speed_kt === 0) return "Calm";
                    let text = (m.wind_variable ? "Variable" : String(m.wind_dir).padStart(3, "0") + "\u00b0") + " " + m.wind_speed_kt + " kt";
                    if (m.wind_gust_kt) text += " G" + m.wind_gust_kt;
                    return text;
                }
                function metarVisibility(m) {
                    const v = m.visibility_m;
                    if (v === null) return "-";
                    if (v >= 9999) return "10 km +";
                    return v >= 1000 ? (v / 1000).toFixed(1) + " km" : v + " m";
                }
                function metarCeiling(m) {
                    if (m.cavok) return "CAVOK";
                    if (m.ceiling_ft === null) return "no ceiling";
                    const layer = m.clouds.find(c => (c.cover === "BKN" || c.cover === "OVC") && c.height_ft === m.ceiling_ft);
                    return (layer ? layer.cover : "VV") + " " + m.ceiling_ft.toLocaleString("en-US") + " ft";
                }

                function fillMetar(el, raw) {
                    el.textContent = "";
                    const m = decodeMetar(raw);
                    if (!m) { el.textContent = "No METAR for this airport"; return; }
                    const head = document.createElement("div"), b = document.createElement("b");
                    b.textContent = "METAR";
                    head.appendChild(b);
                    if (m.category) {
                        const chip = document.createElement("span");
                        chip.className = "v-metar-cat"; chip.textContent = m.category; chip.style.backgroundColor = METAR_CATEGORY_COLOR[m.category] || "#64748b";
                        head.appendChild(chip);
                    }
                    head.appendChild(document.createTextNode(m.time_z));
                    const l1 = document.createElement("div"), l2 = document.createElement("div"), rawEl = document.createElement("div");
                    l1.textContent = "Wind " + metarWind(m) + "  \u00b7  Vis " + metarVisibility(m) + "  \u00b7  " + metarCeiling(m);
                    l2.textContent = (m.temp_c !== null && m.dew_c !== null ? m.temp_c + " / " + m.dew_c + " \u00b0C" : "") + (m.qnh_hpa ? "  \u00b7  QNH " + m.qnh_hpa : "") + (m.weather.length ? "  \u00b7  " + m.weather.join(" ") : "");
                    rawEl.className = "v-metar-raw"; rawEl.textContent = raw;
                    [head, l1, l2, rawEl].forEach(n => el.appendChild(n));
                }

                function loadMetar(icao, el) {
                    const cached = metarCache[icao];
                    if (cached && Date.now() - cached.at < METAR_MAX_AGE_MS) { fillMetar(el, cached.raw); return; }
                    el.textContent = "Loading METAR\u2026";
                    const ctl = new AbortController(), timeout = setTimeout(() => ctl.abort(), 8000);
                    fetch(METAR_URL + icao, { signal: ctl.signal })
                        .then(r => r.ok ? r.text() : "")
                        .then(t => { const raw = t.trim(); metarCache[icao] = { raw: raw, at: Date.now() }; fillMetar(el, raw); })
                        .catch(() => { el.textContent = "METAR unavailable"; })
                        .finally(() => clearTimeout(timeout));
                }

                function airportPopup(icao) {
                    const box = document.createElement("div");
                    if (/^[A-Z0-9]{4}$/.test(icao)) {
                        if (typeof metarEnabled === "undefined" || metarEnabled) {
                            const metar = document.createElement("div");
                            metar.className = "v-metar";
                            box.appendChild(metar);
                        }
                        const a = document.createElement("a");
                        a.href = airportUrl + "?icao=" + icao; a.target = "_blank"; a.rel = "noopener"; a.className = "v-link";
                        a.textContent = "Open " + icao + " airport page";
                        box.appendChild(a);
                    } else { box.textContent = icao; }
                    return box;
                }

                function fillTag(box, p, live) {
                    box.textContent = "";
                    const head = document.createElement("b");
                    head.textContent = currentlyOpenCallsign || "";
                    box.appendChild(head);
                    box.appendChild(document.createElement("br"));
                    box.appendChild(document.createTextNode((p.airframe || "") + " · " + fmtFl(live.alt)));
                    box.appendChild(document.createElement("br"));
                    box.appendChild(document.createTextNode(Math.round(live.gs || 0) + " kt"));
                }

                function blipIcon(heading) {
                    const svg = '<svg viewBox="0 0 24 24" width="24" height="24" style="transform:rotate(' + (Number(heading) || 0) + 'deg)">' +
                        '<path d="M12 3 L19 20 L12 16 L5 20 Z" fill="#f8fafc" stroke="#0a0c14" stroke-width="1.2" stroke-linejoin="round"/></svg>';
                    return L.divIcon({ className: "v-blip", html: svg, iconSize: [24, 24], iconAnchor: [12, 12] });
                }

                // The tag keeps a fixed pixel offset from the aircraft until the user drags it somewhere else.
                function tagLatLng(planeLL) {
                    return flightMap.containerPointToLatLng(flightMap.latLngToContainerPoint(planeLL).add(L.point(tagOffset.x, tagOffset.y)));
                }
                function placeTag() {
                    if (!flightMap || !mapLayers || !mapLayers.tag) return;
                    const planeLL = mapLayers.plane.getLatLng(), ll = tagLatLng(planeLL);
                    mapLayers.tag.setLatLng(ll);
                    mapLayers.leader.setLatLngs([planeLL, ll]);
                }

                function trackDistanceNM() {
                    let nm = 0;
                    for (let i = 1; i < trackPts.length; i++) {
                        const d = distNM(trackPts[i - 1][0], trackPts[i - 1][1], trackPts[i][0], trackPts[i][1]);
                        if (d < 250) nm += d;  // a bigger hop between samples is a data gap, not distance flown
                    }
                    return nm;
                }

                function verticalSpeedFpm() {
                    if (trackPts.length < 2) return null;
                    const last = trackPts[trackPts.length - 1];
                    for (let i = trackPts.length - 2; i >= 0; i--) {
                        const dt = last[3] - trackPts[i][3];
                        if (dt >= 120) return dt > 900 ? null : Math.round(((last[2] - trackPts[i][2]) / (dt / 60)) / 50) * 50;
                    }
                    return null;
                }

                function pushTrackSample() {
                    if (!mapLive) return;
                    const t = Math.floor(Date.now() / 1000), last = trackPts[trackPts.length - 1];
                    if (last && (t - last[3] < 15 || (last[0] === mapLive.lat && last[1] === mapLive.lon))) return;
                    trackPts.push([mapLive.lat, mapLive.lon, mapLive.alt || 0, t, mapLive.gs || 0]);
                }

                // Track points with continuous longitudes, moved to the same "copy" of the world as the plane.
                function unwrappedTrack(refLon) {
                    if (!trackPts.length) return [];
                    const out = [];
                    let prev = trackPts[0][1];
                    trackPts.forEach(pt => {
                        let lon = pt[1];
                        while (lon - prev > 180) lon -= 360;
                        while (lon - prev < -180) lon += 360;
                        prev = lon;
                        out.push([pt[0], lon, pt[2]]);
                    });
                    const shift = 360 * Math.round((refLon - out[out.length - 1][1]) / 360);
                    return shift ? out.map(o => [o[0], o[1] + shift, o[2]]) : out;
                }

                function renderTrack(planeLL) {
                    mapLayers.track.clearLayers();
                    const pts = unwrappedTrack(planeLL[1]);
                    if (pts.length < 2) return pts;
                    let run = [[pts[0][0], pts[0][1]]], runColor = altColor((pts[0][2] + pts[1][2]) / 2);
                    for (let i = 1; i < pts.length; i++) {
                        const color = altColor((pts[i - 1][2] + pts[i][2]) / 2);
                        if (color !== runColor) {
                            L.polyline(run, { color: runColor, weight: 3, opacity: 0.95, lineCap: "round", interactive: false }).addTo(mapLayers.track);
                            run = [[pts[i - 1][0], pts[i - 1][1]]]; runColor = color;
                        }
                        run.push([pts[i][0], pts[i][1]]);
                    }
                    L.polyline(run, { color: runColor, weight: 3, opacity: 0.95, lineCap: "round", interactive: false }).addTo(mapLayers.track);
                    return pts;
                }

                // Range rings whose spacing follows the zoom (about 70-140 px apart).
                function renderRings() {
                    if (!flightMap || !mapLayers || !mapLive) return;
                    mapLayers.rings.clearLayers();
                    const center = mapLayers.plane.getLatLng();
                    const mpp = 40075016.686 * Math.cos(center.lat * Math.PI / 180) / (256 * Math.pow(2, flightMap.getZoom()));
                    const nmPerPx = Math.max(mpp, 1) / 1852;
                    const step = RING_STEPS_NM.find(s => s / nmPerPx >= 70) || RING_STEPS_NM[RING_STEPS_NM.length - 1];
                    for (let k = 1; k <= 4; k++) {
                        const nm = step * k;
                        L.circle(center, { radius: nm * 1852, color: "#94a3b8", weight: 1, opacity: 0.28, fill: false, dashArray: "3 5", interactive: false }).addTo(mapLayers.rings);
                        const top = destPoint(center.lat, center.lng, 0, nm);
                        L.marker(top, { interactive: false, keyboard: false, icon: L.divIcon({ className: "v-ring-label", html: nm + " NM", iconSize: [44, 12], iconAnchor: [22, 14] }) }).addTo(mapLayers.rings);
                    }
                }

                // Altitude or ground speed over time, chosen with the tabs above the chart.
                function renderProfile() {
                    const svg = document.getElementById("profileSvg"), span = document.getElementById("profSpan");
                    const gsMode = profMode === "gs";
                    svg.textContent = "";
                    if (trackPts.length < 5) { span.textContent = (trackWhy || "live samples only") + " (" + trackPts.length + " pts)"; return; }
                    const NS = "http://www.w3.org/2000/svg", W = 600, H = 54, PAD = 4;
                    const val = q => gsMode ? (q[4] || 0) : q[2];
                    const t0 = trackPts[0][3], t1 = trackPts[trackPts.length - 1][3];
                    const maxV = Math.max(gsMode ? 50 : 1000, ...trackPts.map(val));
                    const xy = q => [((q[3] - t0) / Math.max(1, t1 - t0)) * W, H - PAD - (val(q) / (maxV * 1.05)) * (H - 2 * PAD)];
                    const line = trackPts.map((q, i) => { const [x, y] = xy(q); return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1); }).join(" ");
                    const area = document.createElementNS(NS, "path");
                    area.setAttribute("d", line + " L" + W + " " + H + " L0 " + H + " Z");
                    area.setAttribute("fill", "#3b82f6"); area.setAttribute("fill-opacity", "0.14");
                    const stroke = document.createElementNS(NS, "path");
                    stroke.setAttribute("d", line); stroke.setAttribute("fill", "none");
                    stroke.setAttribute("stroke", "#3b82f6"); stroke.setAttribute("stroke-width", "1.5"); stroke.setAttribute("vector-effect", "non-scaling-stroke");
                    const [lx, ly] = xy(trackPts[trackPts.length - 1]);
                    const dot = document.createElementNS(NS, "circle");
                    dot.setAttribute("cx", lx); dot.setAttribute("cy", ly); dot.setAttribute("r", "3"); dot.setAttribute("fill", "#f1f5f9");
                    [area, stroke, dot].forEach(n => svg.appendChild(n));
                    const mins = Math.round((t1 - t0) / 60);
                    span.textContent = (trackNote === "statsim track" ? "statsim track" : "live samples") + " · " + trackPts.length + " pts · " + Math.floor(mins / 60) + "h " + String(mins % 60).padStart(2, "0") + "m · max " + (gsMode ? Math.round(maxV) + " kt" : fmtFl(maxV));
                }

                function setProfileMode(mode) {
                    profMode = mode === "gs" ? "gs" : "alt";
                    document.getElementById("tabAlt").classList.toggle("on", profMode === "alt");
                    document.getElementById("tabGs").classList.toggle("on", profMode === "gs");
                    renderProfile();
                }

                function updateStrip(live, arr) {
                    const set = (id, v) => { document.getElementById(id).textContent = v; };
                    set("stAlt", fmtFt(live.alt));
                    set("stGs", Math.round(live.gs || 0) + " kt");
                    set("stHdg", String(Math.round(live.heading || 0) % 360).padStart(3, "0") + "°");
                    const vs = verticalSpeedFpm();
                    set("stVs", vs === null ? "-" : (Math.abs(vs) < 100 ? "level" : (vs > 0 ? "+" : "-") + Math.abs(vs).toLocaleString("en-US") + " fpm"));
                    if (arr) {
                        const togo = distNM(live.lat, live.lon, arr[0], arr[1]);
                        set("stTogo", Math.round(togo).toLocaleString("en-US") + " NM");
                        if ((live.gs || 0) >= 60 && togo > 3) {
                            const eta = new Date(Date.now() + (togo / live.gs) * 3600000);
                            set("stEta", "~" + String(eta.getUTCHours()).padStart(2, "0") + ":" + String(eta.getUTCMinutes()).padStart(2, "0") + "Z");
                        } else { set("stEta", "-"); }
                    } else { set("stTogo", "-"); set("stEta", "-"); }
                    set("stFlown", trackPts.length > 1 ? Math.round(trackDistanceNM()).toLocaleString("en-US") + " NM" : "-");
                }

                function fillRibbon(p) {
                    const set = (id, v) => { document.getElementById(id).textContent = v; };
                    const dA = airportsDatabase[String(p.origin).toUpperCase()], aA = airportsDatabase[String(p.destination).toUpperCase()];
                    const f = pilotFrequencies[currentlyOpenCallsign];
                    set("mrDep", p.origin); set("mrDepName", (dA && dA.name) || "");
                    set("mrArr", p.destination); set("mrArrName", (aA && aA.name) || "");
                    set("mrMeta", [p.airframe, f ? String(f) : ""].filter(Boolean).join(" · "));
                }

                // ── ATC that concerns this flight: airports, plus the FIRs and approach areas the route touches ──
                function atcRole(c) {
                    const last = String(c.callsign).split("_").pop().toUpperCase();
                    return ATC_ROLES.includes(last) ? last : (FACILITY_ROLE[c.facility] || "");
                }
                function atAirport(c, icao) {
                    const pre = String(c.callsign).split("_")[0].toUpperCase();
                    return pre === icao || (/^[KP]/.test(icao) && pre === icao.slice(1));
                }
                function byRole(a, b) { return ATC_ROLES.indexOf(a.role) - ATC_ROLES.indexOf(b.role) || a.callsign.localeCompare(b.callsign); }

                // Controllers of the given facilities grouped by the crossed area whose callsign prefix they carry.
                function groupByArea(areas, facilities) {
                    const keyToArea = {}, groups = {};
                    (areas || []).forEach(f => (f.keys || [f.id]).forEach(k => { keyToArea[String(k).toUpperCase()] = f; }));
                    lastControllers.filter(c => facilities.includes(c.facility)).forEach(c => {
                        const parts = String(c.callsign).toUpperCase().split("_");
                        for (let k = parts.length - 1; k >= 1; k--) {
                            const f = keyToArea[parts.slice(0, k).join("_")];
                            if (f) { (groups[f.id] = groups[f.id] || []).push({ role: atcRole(c), callsign: c.callsign, freq: c.frequency }); break; }
                        }
                    });
                    return (areas || []).filter(f => groups[f.id]).map(f => ({ area: f, list: groups[f.id].sort(byRole) }));
                }

                // "LYBA" and "LYBA-N" are one FIR for the reader: one entry, every sector callsign goes into the hover text.
                function mergeByParent(groups) {
                    const out = [], idx = {};
                    groups.forEach(g => {
                        const pid = g.area.id.split("-")[0];
                        if (idx[pid] === undefined) { idx[pid] = out.length; out.push({ area: g.area, list: g.list.slice(), parts: [g.area] }); }
                        else {
                            const m = out[idx[pid]];
                            m.list = m.list.concat(g.list).sort(byRole);
                            m.parts.push(g.area);
                            if (g.area.id === pid) m.area = g.area;
                        }
                    });
                    return out;
                }

                function relevantAtc(p) {
                    const out = { airports: [], firs: [], firGroups: [], tracons: [] };
                    const seen = new Set();
                    [p.origin, p.destination].forEach(raw => {
                        const icao = String(raw || "").toUpperCase();
                        if (!/^[A-Z0-9]{4}$/.test(icao) || seen.has(icao)) return;
                        seen.add(icao);
                        const list = lastControllers.filter(c => c.facility >= 2 && c.facility <= 5 && atAirport(c, icao))
                            .map(c => ({ role: atcRole(c), callsign: c.callsign, freq: c.frequency }));
                        lastAtis.filter(a => atAirport(a, icao)).forEach(a => {
                            const mid = String(a.callsign).split("_");  // "LTFM_D_ATIS" = departure ATIS, "_A_" = arrival
                            const kind = mid.length > 2 ? ({ A: "arrival", D: "departure" }[mid[1]] || "") : "";
                            list.push({ role: "ATIS", kind: kind, callsign: a.callsign, freq: a.frequency, code: a.atis_code });
                        });
                        list.sort(byRole);
                        if (list.length) out.airports.push({ icao: icao, list: list });
                    });
                    if (atcSpec) {
                        out.firs = groupByArea(atcSpec.firs, [1, 6]);
                        out.firGroups = mergeByParent(out.firs);
                        out.tracons = groupByArea(atcSpec.tracons, [5]);
                    }
                    return out;
                }

                function atcChip(text, tip, cls) {
                    const s = document.createElement("span");
                    s.className = "v-atc-chip" + (cls ? " " + cls : "");
                    s.textContent = text;
                    if (tip) s.setAttribute("data-tip", tip);
                    return s;
                }
                function atcChipRow(chips) {
                    const row = document.createElement("div");
                    row.className = "v-atc-row";
                    chips.forEach(ch => row.appendChild(atcChip(ch.text, ch.tip, ch.cls)));
                    return row;
                }

                // One entry per role (TWR, GND, ...) instead of one per open sector; the sectors go into the hover text.
                function groupRoles(list) {
                    const groups = [];
                    list.forEach(c => {
                        const label = c.label || c.role;
                        let g = groups.find(x => x.label === label);
                        if (!g) { g = { role: c.role, label: label, items: [] }; groups.push(g); }
                        g.items.push(c);
                    });
                    return groups;
                }
                function groupTip(g) {
                    return g.items.map(c => c.callsign + "  " + c.freq + (c.kind ? "  ·  " + c.kind : "") + (c.code ? "  ·  information " + c.code : "")).join("\n");
                }
                function groupText(g) { return g.label; }

function ringContains(ring, lat, lon) {  // ray casting; ring = [[lat, lon], ...]
                    let inside = false;
                    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                        const yi = ring[i][0], xi = ring[i][1], yj = ring[j][0], xj = ring[j][1];
                        if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
                    }
                    return inside;
                }
                function areaContains(area, lat, lon) { return (area.poly || []).some(r => ringContains(r, lat, lon)); }

                // One FIR / approach polygon: staffed ones are tinted and can be hovered, unstaffed FIRs are only a faint outline.
                function drawArea(area, list, kind, ref, current) {
                    if (!area.poly || !area.poly.length) return 0;
                    const k = 360 * Math.round((nearestLon(area.lat, area.lon, ref) - area.lon) / 360);
                    const rings = k ? area.poly.map(r => r.map(pt => [pt[0], pt[1] + k])) : area.poly;
                    const color = kind === "app" ? "#a78bfa" : "#3b82f6";
                    const style = list
                        ? { color: current ? "#dbeafe" : color, weight: current ? 2.4 : 1.3, opacity: 0.9, fillColor: color, fillOpacity: 0.1, pane: "sectors" }
                        : { color: "#94a3b8", weight: 1, opacity: current ? 0.7 : 0.25, dashArray: "2 4", fill: false, interactive: false, pane: "sectors" };
                    const poly = L.polygon(rings, style).addTo(mapLayers.sectors);
                    if (list) {
                        const tip = document.createElement("div");
                        const head = document.createElement("b");
                        head.textContent = area.name || area.id;
                        tip.appendChild(head);
                        list.forEach(c => { const line = document.createElement("small"); line.textContent = c.callsign + "  " + c.freq; tip.appendChild(line); });
                        poly.bindTooltip(tip, { sticky: true, className: "v-map-tip" });
                        poly.on("mouseover", () => poly.setStyle({ fillOpacity: 0.24 }));
                        poly.on("mouseout", () => poly.setStyle({ fillOpacity: 0.1 }));
                    }
                    return k;
                }

                function renderAtc(p, depLL, arrLL, ref) {
                    mapLayers.atc.clearLayers();
                    mapLayers.sectors.clearLayers();
                    const info = relevantAtc(p);
                    const listEl = document.getElementById("atcList");
                    listEl.textContent = "";
                    const put = (ll, chips, dy) => {
                        L.marker(ll, { keyboard: false, icon: L.divIcon({ className: "v-atc", html: atcChipRow(chips), iconSize: [0, 0], iconAnchor: [0, -dy] }) }).addTo(mapLayers.atc);
                    };

                    // areas: which ones are staffed, and which one the aircraft is in right now
                    const staffedFir = {}, staffedApp = {};
                    info.firs.forEach(g => { staffedFir[g.area.id] = g.list; });
                    info.tracons.forEach(g => { staffedApp[g.area.id] = g.list; });
                    const inside = a => mapLive && areaContains(a, mapLive.lat, mapLive.lon);
                    const insideFirs = ((atcSpec && atcSpec.firs) || []).filter(inside);
                    const curFir = insideFirs.find(f => staffedFir[f.id]) || insideFirs.slice().sort((a, b) => b.id.length - a.id.length)[0] || null;
                    const curApp = ((atcSpec && atcSpec.tracons) || []).find(t => staffedApp[t.id] && inside(t)) || null;
                    if (atcSpec) {
                        const firIds = (atcSpec.firs || []).map(f => f.id);
                        (atcSpec.firs || []).forEach(f => {
                            // an unstaffed sub-sector ("SBBS-NS") whose parent FIR is also on the list would only add noise
                            if (!staffedFir[f.id] && f.id.includes("-") && firIds.includes(f.id.split("-")[0])) return;
                            drawArea(f, staffedFir[f.id], "fir", ref, curFir && curFir.id === f.id);
                        });
                        (atcSpec.tracons || []).forEach(t => { if (staffedApp[t.id]) drawArea(t, staffedApp[t.id], "app", ref, curApp && curApp.id === t.id); });
                    }

                    // chips on the map: one per role at the airports, one label per staffed FIR
                    info.airports.forEach(a => {
                        const ll = a.icao === String(p.origin).toUpperCase() ? depLL : arrLL;
                        if (ll) put(ll, groupRoles(a.list).map(g => ({ text: g.label, tip: groupTip(g) })), 9);
                    });
                    info.firGroups.forEach(g => {
                        const a = g.area, k = a.poly && a.poly.length ? 360 * Math.round((nearestLon(a.lat, a.lon, ref) - a.lon) / 360) : 0;
                        const ll = a.label ? [a.label[0], a.label[1] + k] : [a.lat, nearestLon(a.lat, a.lon, ref)];
                        put(ll, [{ text: a.id + " " + g.list[0].role, tip: (a.name ? a.name + "\n" : "") + g.list.map(c => c.callsign + "  " + c.freq).join("\n"), cls: "fir" }], -9);
                    });

                    // the list under the map, in flight order: where the aircraft is now, what is ahead, what is behind
                    const note = () => {
                        if (!atcSpec || !(atcSpec.firs || []).length) return;
                        const n = document.createElement("div");
                        n.className = "note";
                        n.textContent = atcSpec.source === "eet" ? "FIRs taken from the EET in the flight plan." : "No EET in the flight plan, FIRs estimated from the track and the direct path.";
                        listEl.appendChild(n);
                    };
                    if (!controllersLoaded) { const d = document.createElement("div"); d.textContent = "Checking online ATC…"; listEl.appendChild(d); return; }
                    if (!info.airports.length && !info.firs.length && !info.tracons.length && !curFir) {
                        const d = document.createElement("div"); d.textContent = "No ATC online for the airports or FIRs on this route."; listEl.appendChild(d); note(); return;
                    }
                    const row = (tag, cls) => {
                        const r = document.createElement("div"), t = document.createElement("span"), items = document.createElement("span");
                        r.className = "atc-row" + (cls ? " " + cls : ""); t.className = "atc-tag"; t.textContent = tag; items.className = "atc-items";
                        r.appendChild(t); r.appendChild(items);
                        return { el: r, items: items, count: 0 };
                    };
                    const addItem = (rw, node) => { rw.items.appendChild(node); rw.count++; };
                    const areaItem = g => {
                        const s = document.createElement("span"), b = document.createElement("b");
                        s.className = "atc-item"; b.textContent = g.area.id;
                        s.appendChild(b); s.appendChild(document.createTextNode(" " + g.list[0].role));
                        s.setAttribute("data-tip", (g.area.name ? g.area.name + "\n" : "") + g.list.map(c => c.callsign + "  " + c.freq).join("\n"));
                        return s;
                    };
                    const airportItem = a => {
                        const s = document.createElement("span"), b = document.createElement("b");
                        s.className = "atc-item"; b.textContent = a.icao; s.appendChild(b);
                        groupRoles(a.list).forEach(g => { const c = atcChip(groupText(g), groupTip(g)); c.style.marginLeft = "5px"; s.appendChild(c); });
                        return s;
                    };

                    const dist = ll => (ll && mapLive) ? distNM(mapLive.lat, mapLive.lon, ll[0], ll[1]) : Infinity;
                    const atDep = dist(depLL) <= 30, atArr = dist(arrLL) <= 30;
                    const past = trackPts.map(q => [q[0], q[1]]);
                    if (depLL && trackNote !== "statsim track") past.unshift(depLL);  // without a real track only the departure airport is known
                    // "already flown through": the server's list first (full-precision boundaries), our own polygon test as fallback
                    const visited = new Set((atcSpec && atcSpec.visited) || []);
                    const stateOf = g => g.parts.some(inside) ? "now" : ((g.parts.some(a => visited.has(a.id)) || past.some(q => g.parts.some(a => areaContains(a, q[0], q[1])))) ? "behind" : "ahead");
                    const firGroups = info.firGroups.map(g => ({ g: g, state: stateOf(g) }));
                    const depItem = info.airports.find(a => a.icao === String(p.origin).toUpperCase());
                    const arrItem = info.airports.find(a => a.icao === String(p.destination).toUpperCase() && a !== depItem);

                    const now = row("Now"), ahead = row("Ahead"), behind = row("Behind", "behind");
                    if (curApp) addItem(now, areaItem(info.tracons.find(t => t.area.id === curApp.id)));
                    firGroups.filter(x => x.state === "now").forEach(x => addItem(now, areaItem(x.g)));
                    if (!now.count && curFir) {
                        const s = document.createElement("span"), b = document.createElement("b");
                        s.className = "atc-item"; b.textContent = curFir.id; s.appendChild(b); s.appendChild(document.createTextNode(" (no ATC online)"));
                        addItem(now, s);
                    }
                    if (atDep && depItem) addItem(now, airportItem(depItem));
                    if (atArr && arrItem) addItem(now, airportItem(arrItem));
                    firGroups.filter(x => x.state === "ahead").forEach(x => addItem(ahead, areaItem(x.g)));
                    if (!atArr && arrItem) addItem(ahead, airportItem(arrItem));
                    firGroups.filter(x => x.state === "behind").reverse().forEach(x => addItem(behind, areaItem(x.g)));  // nearest first
                    if (!atDep && depItem) addItem(behind, airportItem(depItem));
                    [now, ahead, behind].forEach(rw => { if (rw.count) listEl.appendChild(rw.el); });
                    note();
                }

function applyLayerOptions() {
                    if (!flightMap || !mapLayers) return;
                    const chips = { rings: "tgRings", atc: "tgAtc", sectors: "tgSectors" };
                    Object.keys(chips).forEach(k => {
                        const g = mapLayers[k];
                        if (mapOpts[k] && !flightMap.hasLayer(g)) flightMap.addLayer(g);
                        if (!mapOpts[k] && flightMap.hasLayer(g)) flightMap.removeLayer(g);
                        const chip = document.getElementById(chips[k]);
                        if (chip) chip.classList.toggle("on", mapOpts[k]);
                    });
                    document.getElementById("atcList").style.display = mapOpts.atc ? "" : "none";
                    // "Follow" has no layer group of its own (it is a camera behaviour, not something drawn), so its chip is synced here too
                    const followChip = document.getElementById("tgFollow");
                    if (followChip) followChip.classList.toggle("on", mapOpts.follow);
                }

                function toggleLayer(name) {
                    if (!(name in mapOpts)) return;
                    mapOpts[name] = !mapOpts[name];
                    applyLayerOptions();
                }

                // Keeps the aircraft in view as it moves, without changing the zoom the user picked; shouldRecenterMap (follow_math.js)
                // ignores sub-threshold drift so a stationary or barely-moving aircraft does not keep re-centring the map.
                function followPlane() {
                    if (!flightMap || !mapLayers || !mapLayers.plane) return;
                    const c = flightMap.getCenter(), ll = mapLayers.plane.getLatLng();
                    if (!shouldRecenterMap(c.lat, c.lng, ll.lat, ll.lng, 0.05)) return;
                    flightMap.panTo(ll, { animate: true, duration: 0.4, noMoveStart: true });
                }

                function toggleFollow() {
                    mapOpts.follow = !mapOpts.follow;
                    const chip = document.getElementById("tgFollow");
                    if (chip) chip.classList.toggle("on", mapOpts.follow);
                    if (mapOpts.follow) followPlane();
                }

                // A one-off action: frames the whole route again, the same way the map does when it first opens. Turns Follow off first
                // (the two are opposite intents - one shows everything, the other tracks a single point) so the chip states stay honest.
                function fitRoute() {
                    if (mapOpts.follow) {
                        mapOpts.follow = false;
                        const chip = document.getElementById("tgFollow");
                        if (chip) chip.classList.remove("on");
                    }
                    renderMapFlight(true);
                }

// Draws (first call) or moves (later calls) every layer of the map.
                function renderMapFlight(fit) {
                    const p = globalDossiers[currentlyOpenCallsign];
                    if (!flightMap || !p || !mapLive) return;
                    const dep = airportLatLon(p.origin), arr = airportLatLon(p.destination);
                    let planeLL = [mapLive.lat, mapLive.lon], path = null, arrLL = arr;
                    if (dep && arr) {
                        path = gcLine(dep, arr, 64);
                        arrLL = path[path.length - 1];
                        planeLL = [mapLive.lat, nearestLon(mapLive.lat, mapLive.lon, path)];
                    }
                    if (!mapLayers) {
                        flightMap.createPane("sectors");
                        flightMap.getPane("sectors").style.zIndex = 350;  // area fills sit under the routes, tracks and markers
                        mapLayers = { direct: L.layerGroup().addTo(flightMap), track: L.layerGroup().addTo(flightMap), rings: L.layerGroup(), sectors: L.layerGroup(), atc: L.layerGroup() };
                        [[p.origin, dep], [p.destination, arrLL]].forEach(([icao, ll]) => {
                            if (!ll) return;
                            L.circleMarker(ll, { radius: 4, color: "#e2e8f0", weight: 1.5, fillColor: "#0a0c14", fillOpacity: 1 })
                                .bindTooltip(safeTipNode(icao), { permanent: true, direction: "top", offset: [0, -6], className: "v-map-tip" })
                                .bindPopup(airportPopup(icao))
                                .on("popupopen", ev => { const el = ev.popup.getContent().querySelector(".v-metar"); if (el) loadMetar(icao, el); })
                                .addTo(flightMap);
                        });
                        mapLayers.plane = L.marker(planeLL, { icon: blipIcon(mapLive.heading), zIndexOffset: 1000, keyboard: false }).addTo(flightMap);
                        mapLayers.blipSvg = mapLayers.plane.getElement().querySelector("svg");
                        // the aircraft tag is its own marker so it can be dragged; a thin leader line ties it to the aircraft
                        const box = document.createElement("div");
                        box.className = "v-tag-box";
                        mapLayers.tagBox = box;
                        mapLayers.tag = L.marker(tagLatLng(planeLL), { draggable: true, keyboard: false, zIndexOffset: 900, icon: L.divIcon({ className: "v-tag", html: box, iconSize: [0, 0], iconAnchor: [0, 0] }) }).addTo(flightMap);
                        mapLayers.leader = L.polyline([planeLL, mapLayers.tag.getLatLng()], { color: "#94a3b8", weight: 1, opacity: 0.8, interactive: false }).addTo(flightMap);
                        mapLayers.tag.on("drag", e => mapLayers.leader.setLatLngs([mapLayers.plane.getLatLng(), e.latlng]));
                        mapLayers.tag.on("dragend", () => {
                            const a = flightMap.latLngToContainerPoint(mapLayers.plane.getLatLng()), b = flightMap.latLngToContainerPoint(mapLayers.tag.getLatLng());
                            tagOffset = { x: b.x - a.x, y: b.y - a.y };
                        });
                        flightMap.on("zoomend", () => { renderRings(); placeTag(); });
                        applyLayerOptions();
                    }
                    mapLayers.direct.clearLayers();
                    if (path) L.polyline(path, { color: "#e2e8f0", weight: 1.2, opacity: 0.35, dashArray: "1 6", interactive: false }).addTo(mapLayers.direct);
                    mapLayers.plane.setLatLng(planeLL);
                    if (mapLayers.blipSvg) mapLayers.blipSvg.style.transform = "rotate(" + (Number(mapLive.heading) || 0) + "deg)";
                    fillTag(mapLayers.tagBox, p, mapLive);
                    placeTag();
                    const pts = renderTrack(planeLL);

                    renderRings();
                    if (typeof liveAtc === "undefined" || liveAtc) renderAtc(p, dep, arrLL, path || [planeLL]);
                    updateStrip(mapLive, arr);
                    renderProfile();
                    if (fit) {
                        const all = (path || []).concat([planeLL], pts.map(q => [q[0], q[1]]));
                        // extra room on the right so the tag next to the aircraft is never cut off
                        if (all.length > 1) flightMap.fitBounds(L.latLngBounds(all), { paddingTopLeft: [40, 40], paddingBottomRight: [150, 40], maxZoom: 8 });
                        else flightMap.setView(planeLL, 6);
                    } else if (mapOpts.follow) {
                        followPlane();
                    }
                }

                function trackReasonText(reason) {
                    if (reason === "no_key") return "live samples only (statsim key not set)";
                    if (reason === "rate_limited") return "live samples only (track requests limited, try again in a minute)";
                    if (reason === "not_found" || reason === "no_positions") return "live samples only (no track on statsim yet)";
                    return "live samples only (track unavailable)";
                }

                // The statsim track is fetched on the server (the API key never reaches the browser) through a hidden field,
                // exactly like the rating lookup; the answer comes back through window.setFlightTrack.
                function requestFlightTrack(p, cs) {
                    try {
                        const input = window.parent.document.querySelector('input[aria-label="vs_track_req"]');
                        if (!input || !/^\d{1,10}$/.test(String(p.cid))) { trackNote = "live"; trackWhy = "live samples only (track bridge unavailable)"; renderProfile(); return; }
                        const win = window.parent;
                        const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, "value").set;
                        setter.call(input, String(p.cid) + ":" + cs + ":" + (Date.now() % 100000));
                        input.dispatchEvent(new win.Event("input", { bubbles: true }));
                        const enter = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true };
                        input.dispatchEvent(new win.KeyboardEvent("keydown", enter));
                        input.dispatchEvent(new win.KeyboardEvent("keypress", enter));
                        input.dispatchEvent(new win.KeyboardEvent("keyup", enter));
                        trackWait = setTimeout(() => {
                            if (mapFlightKey === String(p.cid) + ":" + cs && trackNote !== "statsim track") {
                                trackNote = "live"; trackWhy = "live samples only (track request timed out)"; renderProfile();
                            }
                        }, TRACK_WAIT_MS);
                    } catch (e) { trackNote = "live"; trackWhy = "live samples only (track unavailable)"; }
                }

                window.setFlightTrack = function(d) {
                    if (!d || !flightMap || d.key !== mapFlightKey) return;
                    if (trackWait) { clearTimeout(trackWait); trackWait = null; }
                    if (d.atc && Array.isArray(d.atc.firs)) atcSpec = d.atc;
                    if (d.ok && Array.isArray(d.points) && d.points.length) {
                        const lastT = d.points[d.points.length - 1][3];
                        const newer = trackPts.filter(q => q[3] > lastT + 10);  // live samples collected after statsim's last point
                        trackPts = d.points.concat(newer);
                        trackNote = "statsim track"; trackWhy = "";
                        renderMapFlight(true);
                    } else {
                        trackNote = "live"; trackWhy = trackReasonText(d.reason);
                        renderMapFlight(false);
                    }
                };

                async function pollLiveFlight() {
                    const cs = currentlyOpenCallsign;
                    if (!flightMap || !cs || document.hidden || mapBusy) return;
                    const base = globalDossiers[cs];
                    if (!base) return;
                    mapBusy = true;
                    const ctl = new AbortController();
                    const timeout = setTimeout(() => ctl.abort(), 12000);
                    try {
                        const res = await fetch(VATSIM_FEED_URL, { signal: ctl.signal });
                        if (!res.ok) return;
                        const feed = await res.json();
                        if (cs !== currentlyOpenCallsign || !flightMap) return;
                        lastControllers = Array.isArray(feed.controllers) ? feed.controllers : [];
                        lastAtis = Array.isArray(feed.atis) ? feed.atis : [];
                        controllersLoaded = true;
                        const live = (feed.pilots || []).find(x => String(x.cid) === String(base.cid) && x.callsign === cs);
                        if (!live) { setMapNote("This pilot is no longer online"); renderMapFlight(false); return; }
                        setMapNote("");
                        mapLive = { lat: live.latitude, lon: live.longitude, heading: live.heading, gs: live.groundspeed, alt: live.altitude };
                        pushTrackSample();
                        renderMapFlight(false);
                    } catch (e) { /* keep the last known position */ }
                    finally { clearTimeout(timeout); mapBusy = false; }
                }

                function closeMap() {
                    if (mapTimer) { clearInterval(mapTimer); mapTimer = null; }
                    if (trackWait) { clearTimeout(trackWait); trackWait = null; }
                    if (flightMap) { flightMap.remove(); flightMap = null; }
                    mapLayers = null; mapLive = null; mapFlightKey = ""; trackPts = []; trackNote = ""; trackWhy = "";
                    lastControllers = []; lastAtis = []; controllersLoaded = false; atcSpec = null;
                    document.getElementById("mapPanel").style.display = "none";
                    document.getElementById("popMapBadge").classList.remove("active");
                    setMapNote("");
                }

                async function toggleMap() {
                    const panel = document.getElementById("mapPanel");
                    if (panel.style.display === "block") { closeMap(); return; }
                    const cs = currentlyOpenCallsign, p = globalDossiers[cs];
                    if (!p) return;
                    panel.style.display = "block";
                    document.getElementById("popMapBadge").classList.add("active");
                    fillRibbon(p);
                    setMapNote("Loading map…");
                    try { await loadLeaflet(); } catch (e) { setMapNote("Map library could not be loaded"); return; }
                    if (panel.style.display !== "block" || cs !== currentlyOpenCallsign) return;
                    setMapNote("");
                    mapFlightKey = String(p.cid) + ":" + cs;
                    mapLive = { lat: p.lat, lon: p.lon, heading: p.heading, gs: p.gs, alt: p.alt };
                    trackPts = [[p.lat, p.lon, p.alt || 0, Math.floor(Date.now() / 1000), p.gs || 0]];
                    flightMap = L.map("flightMap", { minZoom: 2, attributionControl: true }).setView([p.lat || 30, p.lon || 0], 5);
                    L.tileLayer(MAP_TILES_URL, { maxZoom: 12, attribution: MAP_TILES_ATTRIBUTION }).addTo(flightMap);
                    renderMapFlight(true);
                    requestFlightTrack(p, cs);
                    mapTimer = setInterval(pollLiveFlight, MAP_REFRESH_MS);
                    pollLiveFlight();
                }

