// Flight replay: plays a recorded statsim track through the Flight Record map (flight_map.js) instead of the live feed.
// Expects REPLAY_DATA and the globals flight_map.js needs (see flight_replay_view.py), plus replay_core.js.
(function () {
    const D = REPLAY_DATA, pts = D.points;
    const t0 = pts[0][3], t1 = pts[pts.length - 1][3];
    const cs = D.flight.callsign || "FLIGHT";
    const SPEEDS = [1, 10, 60, 300, 1000];
    const PHASE_NAMES = { takeoff: "Takeoff", toc: "Top of climb", maxalt: "Max altitude", maxgs: "Max speed", tod: "Top of descent", landing: "Landing", reconnect: "Reconnected" };
    // a pilot who disconnects in flight and logs on again leaves a hole in the record: the replay jumps over it and it does not count as flight time
    const GAP = 600, gaps = [];
    for (let i = 1; i < pts.length; i++) if (pts[i][3] - pts[i - 1][3] > GAP) gaps.push([pts[i - 1][3], pts[i][3]]);
    const gapWithin = (a, b) => gaps.reduce((sum, g) => sum + Math.max(0, Math.min(b, g[1]) - Math.max(a, g[0])), 0);
    const marks = replayPhaseMarkers(pts);
    const takeoff = marks.find(m => m.kind === "takeoff"), landing = marks.find(m => m.kind === "landing");
    // the record starts at logon, often long before the takeoff: the replay starts 3 minutes before it (the scrubber still covers everything)
    const tStart = takeoff ? Math.max(t0, takeoff.t - 180) : t0;
    const tActiveEnd = landing ? Math.min(t1, landing.t + 180) : t1;
    const flightStart = takeoff ? takeoff.t : t0, flightEnd = landing ? landing.t : t1;
    const elapsedAt = tt => { const e = Math.min(flightEnd, tt); return Math.max(0, e - flightStart - gapWithin(flightStart, e)); };
    const flightTotal = () => Math.max(0, flightEnd - flightStart - gapWithin(flightStart, flightEnd));
    let t = tStart, playing = false, timer = null, speed = 60;

    // a whole replay should take about a minute and a half, whatever the flight length
    (function pickSpeed() {
        const wanted = Math.max(1, tActiveEnd - tStart - gapWithin(tStart, tActiveEnd)) / 90;
        speed = SPEEDS.reduce((best, s) => Math.abs(s - wanted) < Math.abs(best - wanted) ? s : best, SPEEDS[0]);
    })();

    function unwrapAll() {
        const out = [];
        let prev = pts[0][1];
        pts.forEach(p => {
            let lon = p[1];
            while (lon - prev > 180) lon -= 360;
            while (lon - prev < -180) lon += 360;
            prev = lon;
            out.push([p[0], lon]);
        });
        return out;
    }

    function setTime(tt) {
        t = Math.max(t0, Math.min(t1, tt));
        const s = replayStateAt(pts, t), i = Math.max(0, replayIndexAt(pts, t));
        mapLive = { lat: s.lat, lon: s.lon, heading: s.heading, gs: s.gs, alt: s.alt };
        trackPts = pts.slice(0, i + 1);
        if (t > pts[i][3]) trackPts = trackPts.concat([[s.lat, s.lon, s.alt, t, s.gs]]);
        renderMapFlight(false);
        document.getElementById("stEta").textContent = replayDuration(elapsedAt(t));
        document.getElementById("rpTime").textContent = replayClock(t) + "  ·  " + replayDuration(elapsedAt(t)) + " / " + replayDuration(flightTotal());
        document.getElementById("rpScrub").value = String(Math.round(t));
    }

    function setPlaying(on) {
        playing = on;
        document.getElementById("rpPlay").textContent = on ? "Pause" : "Play";
        if (timer) { clearInterval(timer); timer = null; }
        if (on) {
            if (t >= t1) setTime(tStart);
            timer = setInterval(() => {
                const next = replayNextTime(pts, t + 0.12 * speed);
                if (next >= t1) { setTime(t1); setPlaying(false); } else setTime(next);
            }, 120);
        }
    }

    function buildControls() {
        const panel = document.getElementById("mapPanel"), strip = panel.querySelector(".mp-strip");
        const bar = document.createElement("div");
        bar.className = "rp-bar";
        bar.innerHTML = '<button type="button" class="mp-chip" id="rpPlay">Play</button>' +
            '<input type="range" id="rpScrub" min="' + Math.floor(t0) + '" max="' + Math.ceil(t1) + '" step="1" value="' + Math.floor(t0) + '">' +
            '<span class="rp-time" id="rpTime"></span>' +
            '<label class="rp-speed">Speed <select id="rpSpeed">' + SPEEDS.map(s => '<option value="' + s + '">' + s + '×</option>').join("") + '</select></label>';
        panel.insertBefore(bar, strip);
        const events = document.createElement("div");
        events.className = "rp-events";
        events.id = "rpEvents";
        panel.insertBefore(events, strip);
        document.getElementById("rpPlay").onclick = () => setPlaying(!playing);
        document.getElementById("rpScrub").oninput = e => setTime(Number(e.target.value));
        const sel = document.getElementById("rpSpeed");
        sel.value = String(speed);
        sel.onchange = () => { speed = Number(sel.value); };
    }

    function addEvents(unwrapped) {
        const box = document.getElementById("rpEvents"), group = L.layerGroup().addTo(flightMap);
        marks.forEach(m => {
            const label = (PHASE_NAMES[m.kind] || m.kind) + " · " + replayClock(m.t);
            L.circleMarker(unwrapped[m.index], { radius: 4, color: "#e2e8f0", weight: 1.5, fillColor: "#0a0c14", fillOpacity: 1 })
                .bindTooltip(label, { direction: "top", offset: [0, -4], className: "v-map-tip" })
                .on("click", () => setTime(m.t)).addTo(group);
            const chip = document.createElement("button");
            chip.type = "button"; chip.className = "mp-chip"; chip.textContent = label;
            chip.onclick = () => setTime(m.t);
            box.appendChild(chip);
        });
        if (!marks.length) box.style.display = "none";
    }

    async function start() {
        const panel = document.getElementById("mapPanel"), dep = D.flight.departure, arr = D.flight.destination;
        panel.style.display = "block";
        globalDossiers[cs] = {
            name: "", cid: D.cid, origin: dep || "----", destination: arr || "----", airframe: String(D.flight.aircraft || "").split("/")[0].toUpperCase(),
            lat: pts[0][0], lon: pts[0][1], heading: 0, gs: 0, alt: pts[0][2]
        };
        currentlyOpenCallsign = cs;
        // no live ATC in a replay: hide the ATC / Sectors buttons and the list under the map
        mapOpts.atc = false; mapOpts.sectors = false;
        ["tgAtc", "tgSectors"].forEach(id => { const b = document.getElementById(id); if (b) b.style.display = "none"; });
        document.getElementById("stEta").previousElementSibling.textContent = "Flight time";
        fillRibbon(globalDossiers[cs]);
        setMapNote("Loading map…");
        try { await loadLeaflet(); } catch (e) { setMapNote("Map library could not be loaded"); return; }
        setMapNote("");
        buildControls();
        mapFlightKey = "replay"; trackNote = "statsim track"; trackWhy = "";
        const first = replayStateAt(pts, t0);
        mapLive = { lat: first.lat, lon: first.lon, heading: first.heading, gs: first.gs, alt: first.alt };
        trackPts = pts.slice();  // the first draw frames the whole flight
        flightMap = L.map("flightMap", { minZoom: 2, attributionControl: true }).setView([first.lat, first.lon], 5);
        L.tileLayer(MAP_TILES_URL, { maxZoom: 12, attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, OpenStreetMap contributors, and the GIS user community" }).addTo(flightMap);
        renderMapFlight(true);
        const unwrapped = unwrapAll();
        L.polyline(unwrapped, { color: "#94a3b8", weight: 1, opacity: 0.35, dashArray: "3 6", interactive: false }).addTo(flightMap);  // the whole flight, faint
        addEvents(unwrapped);
        setTime(tStart);
    }

    start();
})();
