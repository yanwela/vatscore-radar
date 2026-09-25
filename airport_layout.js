// Draws the ground layout of an airport (OpenStreetMap: runways, taxiways, aprons, terminals, stands, holding points) on a Leaflet map.
// Expects window.L. Every text (taxiway / stand names) comes from OpenStreetMap contributors, so it only ever goes into elements through textContent.
function drawAirportLayout(map, layout) {
    const groups = { runways: L.layerGroup(), taxiways: L.layerGroup(), aprons: L.layerGroup(), stands: L.layerGroup(), holds: L.layerGroup(), labels: L.layerGroup() };
    const none = { interactive: false };
    const distM = (a, b) => Math.hypot((b[0] - a[0]) * 110540, (b[1] - a[1]) * 111320 * Math.cos(a[0] * Math.PI / 180));
    const lengthM = p => { let s = 0; for (let i = 1; i < p.length; i++) s += distM(p[i - 1], p[i]); return s; };
    function midPoint(p) {
        let left = lengthM(p) / 2;
        for (let i = 1; i < p.length; i++) {
            const d = distM(p[i - 1], p[i]);
            if (d >= left && d > 0) { const f = left / d; return [p[i - 1][0] + (p[i][0] - p[i - 1][0]) * f, p[i - 1][1] + (p[i][1] - p[i - 1][1]) * f]; }
            left -= d;
        }
        return p[p.length - 1];
    }
    const chip = (cls, text) => { const e = document.createElement("span"); e.className = "ar-lbl " + cls; e.textContent = text; return e; };

    layout.aprons.forEach(a => L.polygon(a.pts, Object.assign({ color: "#94a3b8", weight: 1, fillColor: "#64748b", fillOpacity: 0.22 }, none)).addTo(groups.aprons));
    layout.terminals.forEach(a => L.polygon(a.pts, Object.assign({ color: "#cbd5e1", weight: 1, fillColor: "#94a3b8", fillOpacity: 0.3 }, none)).addTo(groups.aprons));
    layout.taxiways.forEach(t => {
        L.polyline(t.pts, Object.assign({ color: "#0a0c14", weight: 4.5, opacity: 0.5 }, none)).addTo(groups.taxiways);
        L.polyline(t.pts, Object.assign({ color: "#facc15", weight: 2.2, opacity: 0.9 }, none)).addTo(groups.taxiways);
    });
    layout.runways.forEach(r => L.polyline(r.pts, Object.assign({ color: "#f8fafc", weight: 3, opacity: 0.85, dashArray: "10 8" }, none)).addTo(groups.runways));
    layout.stands.forEach(s => L.circleMarker([s.lat, s.lon], Object.assign({ radius: 2.5, color: "#0a0c14", weight: 1, fillColor: "#38bdf8", fillOpacity: 1 }, none)).addTo(groups.stands));
    layout.holds.forEach(h => L.circleMarker([h.lat, h.lon], Object.assign({ radius: 3, color: "#7f1d1d", weight: 1, fillColor: "#f87171", fillOpacity: 1 }, none)).addTo(groups.holds));

    // one name per taxiway, on its longest piece that is in view; a piece is named where its middle is
    const taxiNames = {};
    layout.taxiways.filter(t => t.ref).forEach(t => (taxiNames[t.ref] = taxiNames[t.ref] || []).push({ at: midPoint(t.pts), len: lengthM(t.pts) }));
    Object.keys(taxiNames).forEach(k => taxiNames[k].sort((a, b) => b.len - a.len));
    const runwayNames = layout.runways.filter(r => r.ref).map(r => ({ ref: r.ref, at: midPoint(r.pts) }));

    function refreshLabels() {
        groups.labels.clearLayers();
        if (!map.hasLayer(groups.labels)) return;
        const z = map.getZoom(), view = map.getBounds().pad(0.05);
        const put = (at, cls, text) => L.marker(at, { icon: L.divIcon({ className: "ar-lbl-wrap", html: chip(cls, text), iconSize: [0, 0] }), interactive: false, keyboard: false }).addTo(groups.labels);
        if (z >= 12) runwayNames.forEach(r => { if (view.contains(r.at)) put(r.at, "ar-lbl-rwy", r.ref); });
        if (z >= 15) Object.keys(taxiNames).forEach(k => { const hit = taxiNames[k].find(p => view.contains(p.at)); if (hit) put(hit.at, "ar-lbl-twy", k); });
        if (z >= 16) layout.holds.filter(h => h.ref && view.contains([h.lat, h.lon])).slice(0, 80).forEach(h => put([h.lat, h.lon], "ar-lbl-hold", h.ref));
        if (z >= 17) layout.stands.filter(s => s.ref && view.contains([s.lat, s.lon])).slice(0, 150).forEach(s => put([s.lat, s.lon], "ar-lbl-stand", s.ref));
    }

    ["aprons", "taxiways", "runways", "stands", "holds", "labels"].forEach(k => groups[k].addTo(map));
    L.control.layers(null, { "Runways": groups.runways, "Taxiways": groups.taxiways, "Aprons and terminals": groups.aprons, "Stands and gates": groups.stands,
                             "Holding points": groups.holds, "Names": groups.labels }, { collapsed: true, position: "topright" }).addTo(map);
    map.attributionControl.addAttribution('Airport layout &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors (ODbL)');
    map.on("moveend zoomend overlayadd overlayremove", refreshLabels);
    refreshLabels();
    return { groups: groups, refreshLabels: refreshLabels };
}
