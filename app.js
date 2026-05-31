let rawPilots = [];
let globalDossiers = {};
let sessionID = "";
const BACKEND_API = "http://127.0.0.1:8000/api/vatsim";

function initApp() {
    sessionID = Math.floor(Math.random() * 900000) + 100000;
    runRadarEngine();
}

function switchTab(evt, tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    evt.target.classList.add('active');
}

function toggleCustomizer() {
    const el = document.getElementById("customizer");
    el.style.display = el.style.display === "block" ? "none" : "block";
}

function toggleCharts() {
    const el = document.getElementById("charts-container");
    el.style.display = el.style.display === "grid" ? "none" : "grid";
}

function toggleColumn(index) {
    const tbl = document.getElementById("radar-table");
    const show = [
        document.getElementById("col-origin").checked, 
        document.getElementById("col-dest").checked, 
        document.getElementById("col-aircraft").checked, 
        document.getElementById("col-category").checked
    ];
    for (let row of tbl.rows) {
        if(row.cells[index]) row.cells[index].style.display = show[index-1] ? "" : "none";
    }
}

function classifyAircraft(acType, callsign) {
    acType = String(acType || "").toUpperCase().trim();
    callsign = String(callsign || "").toUpperCase().trim();
    
    const militaryTypes = ["F16", "F18", "F15", "F22", "F35", "F4", "F5", "EFAF", "SU27", "C17", "A400", "C130", "KC135", "UH60"];
    const militaryPrefixes = ["TUR", "RCH", "AME", "BAF", "GAF", "MIL", "NAVY"];
    if (militaryTypes.includes(acType) || militaryPrefixes.some(pfx => callsign.startsWith(pfx)) || callsign.includes("MIL")) return "⚔️ Military";
    
    const gaTypes = ["C150", "C152", "C172", "C182", "PA28", "DA40", "DA42", "SR22"];
    if (gaTypes.includes(acType)) return "🛩️ General Aviation";

    const bizJets = ["GLF5", "GLF6", "CL60", "CRJ2", "C56X"];
    if (bizJets.includes(acType)) return "💼 Business Jet";
    
    return "✈️ Commercial";
}

function filterData() {
    const selectedFir = document.getElementById("fir-dropdown").value;
    const fleetFilter = document.getElementById("fleet-filter").value;
    const tbody = document.getElementById("table-body");
    tbody.innerHTML = "";
    globalDossiers = {};

    let records = { maxAlt: -1, maxAltP: null, maxSpd: -1, maxSpdP: null, minSpd: 9999, minSpdP: null, veteran_p: null, longestTime: 0 };
    let anomalies = [];
    let matchCount = 0;
    
    let altChartData = [];
    let spdChartData = [];

    rawPilots.forEach(p => {
        const callsign = p.callsign || "N/A";
        const alt = p.altitude || 0;
        const gs = p.groundspeed || 0;
        const lat = p.latitude || 0;
        const lon = p.longitude || 0;
        const fplan = p.flight_plan || {};
        const dep = fplan.departure || "";
        const arr = fplan.arrival || "";
        const acType = (fplan.aircraft || "").split("/")[0] || "N/A";
        
        const category = classifyAircraft(acType, callsign);

        // Record Engine Calculation
        if (alt > records.maxAlt) { records.maxAlt = alt; records.maxAltP = p; }
        if (gs > records.maxSpd) { records.maxSpd = gs; records.maxSpdP = p; }
        if (alt > 3000 && gs > 45 && gs < records.minSpd) { records.minSpd = gs; records.minSpdP = p; }
        
        if (p.logon_time) {
            let sessionMs = new Date() - new Date(p.logon_time);
            if (sessionMs > records.longestTime) {
                records.longestTime = sessionMs;
                records.veteran_p = p;
            }
        }

        // Anomalies Detector
        if (String(p.transponder) === "7700") anomalies.push({ type: "🚨 EMERGENCY (7700)", callsign, details: "Declared Mayday", acType });
        if (gs > 1150) anomalies.push({ type: "⚡ Warp Speed Glitch", callsign, details: `${gs} KT`, acType });
        if (category === "⚔️ Military") anomalies.push({ type: "⚔️ Tactical Sortie", callsign, details: "Tactical Operation", acType });

        // Boundaries Checks
        const matchesFir = dep.startsWith(selectedFir) || arr.startsWith(selectedFir);
        let isPhysicallyInTr = (selectedFir === "LT" && (lat >= 36.5 && lat <= 42.0) && (lon >= 27.0 && lon <= 44.5));

        if (matchesFir || isPhysicallyInTr) {
            if (fleetFilter === 'Commercial' && category !== '✈️ Commercial') return;
            if (fleetFilter === 'General' && category !== '🛩️ General Aviation') return;
            if (fleetFilter === 'Business' && category !== '💼 Business Jet') return;
            if (fleetFilter === 'Military' && category !== '⚔️ Military') return;

            matchCount++;
            altChartData.push({callsign, val: alt});
            spdChartData.push({callsign, val: gs});

            // FIXED DOSSIER TELEMETRY MAPPING
            let ratingTxt = {0:"OBS", 1:"P1", 2:"P2", 3:"P3", 4:"P4", 5:"P5"}[p.pilot_rating || 0] || "P1";
            let onlineMins = p.logon_time ? Math.floor((new Date() - new Date(p.logon_time)) / 60000) + " Mins" : "N/A";
            let sqw = p.transponder || "0000";

            globalDossiers[callsign] = {
                name: p.name || "Anonymous", 
                cid: p.cid || "N/A", 
                rating: ratingTxt, 
                online: onlineMins,
                voice: p.has_voice ? "🎙️ Voice Active" : "⌨️ Text Only", 
                squawk: sqw,
                origin: dep || "⚠️ NO FPL", 
                destination: arr || "⚠️ NO FPL", 
                airframe: acType, 
                route: fplan.route || "No FPL Filed."
            };

            const tr = document.createElement("tr");
            tr.onclick = () => openDossier(callsign);
            tr.innerHTML = `
                <td><b style="color:#3b82f6;">${callsign}</b></td>
                <td>${dep || "⚠️ NO FPL"}</td>
                <td>${arr || "⚠️ NO FPL"}</td>
                <td>${acType}</td>
                <td>${category}</td>
                <td>${alt.toLocaleString()} FT</td>
                <td>${gs} KT</td>
                <td>${sqw}</td>
            `;
            tbody.appendChild(tr);
        }
    });

    document.getElementById("info-text").innerText = `Showing ${matchCount} active aircraft tracks inside ${selectedFir}. Click a row to inspect full telemetry.`;
    buildLeaderboard(records);
    buildAnomalies(anomalies);
    renderSimpleCharts(altChartData, spdChartData);
    
    toggleColumn(1); toggleColumn(2); toggleColumn(3); toggleColumn(4);
}

function renderSimpleCharts(altData, spdData) {
    const aBox = document.getElementById("alt-chart");
    const sBox = document.getElementById("spd-chart");
    aBox.innerHTML = ""; sBox.innerHTML = "";
    
    altData.slice(0, 15).forEach(d => {
        let pct = (d.val / 45000) * 100;
        if(pct < 3) pct = 3;
        aBox.innerHTML += `<div class="chart-bar" style="height:${pct}%" data-label="${d.callsign}: ${d.val}FT"></div>`;
    });
    spdData.slice(0, 15).forEach(d => {
        let pct = (d.val / 600) * 100;
        if(pct < 3) pct = 3;
        sBox.innerHTML += `<div class="chart-bar" style="height:${pct}%; background-color:#22c55e;" data-label="${d.callsign}: ${d.val}KT"></div>`;
    });
}

function buildLeaderboard(rec) {
    const lBody = document.getElementById("leaderboard-body"); lBody.innerHTML = "";
    if(rec.maxAltP) lBody.innerHTML += `<tr><td>Highest Cruising Altitude</td><td><b>${rec.maxAltP.callsign}</b></td><td>${rec.maxAlt.toLocaleString()} FT</td><td>${rec.maxAltP.name}</td></tr>`;
    if(rec.maxSpdP) lBody.innerHTML += `<tr><td>Maximum Velocity (GS)</td><td><b>${rec.maxSpdP.callsign}</b></td><td>${rec.maxSpd} KT</td><td>${rec.maxSpdP.name}</td></tr>`;
    if(rec.minSpdP) lBody.innerHTML += `<tr><td>Slowest Airborne Profile</td><td><b>${rec.minSpdP.callsign}</b></td><td>${rec.minSpd} KT</td><td>${rec.minSpdP.name}</td></tr>`;
    if(rec.veteran_p) {
        let logStr = rec.veteran_p.logon_time ? rec.veteran_p.logon_time.substring(11,16) : "00:00";
        lBody.innerHTML += `<tr><td>Longest Session (Veteran)</td><td><b>${rec.veteran_p.callsign}</b></td><td>Since ${logStr} Z</td><td>${rec.veteran_p.name}</td></tr>`;
    }
}

function buildAnomalies(anomalies) {
    const aBody = document.getElementById("anomaly-body"); aBody.innerHTML = "";
    if(anomalies.length === 0) { aBody.innerHTML = `<tr><td colspan="4" style="color:#22c55e; text-align:center;">Sky is clear. No anomalies.</td></tr>`; return; }
    anomalies.forEach(a => { aBody.innerHTML += `<tr><td>${a.type}</td><td><b>${a.callsign}</b></td><td>${a.details}</td><td>${a.acType}</td></tr>`; });
}

function openDossier(callsign) {
    const p = globalDossiers[callsign]; 
    if (!p) return;
    document.getElementById("popCallsign").innerText = "Target Profile: " + callsign;
    document.getElementById("popName").innerText = p.name; 
    document.getElementById("popCid").innerText = p.cid;
    document.getElementById("popRating").innerText = p.rating; 
    document.getElementById("popOnline").innerText = p.online;
    document.getElementById("popVoice").innerText = p.voice; 
    document.getElementById("popSquawk").innerText = p.squawk;
    document.getElementById("popOrigin").innerText = p.origin; 
    document.getElementById("popDestination").innerText = p.destination;
    document.getElementById("popAirframe").innerText = p.airframe; 
    document.getElementById("popRoute").value = p.route;
    document.getElementById("dossierModal").style.display = "block";
}

function closeModal() { document.getElementById("dossierModal").style.display = "none"; }

async function runRadarEngine() {
    try {
        const res = await fetch(`${BACKEND_API}?sid=${sessionID}`);
        const data = await res.json();
        if (data) {
            rawPilots = data.pilots || [];
            document.getElementById("stat-pilots").innerText = rawPilots.length;
            document.getElementById("stat-atcs").innerText = (data.controllers || []).length;
            document.getElementById("stat-sync").innerText = new Date().toLocaleTimeString() + " LOC";
            
            const an = data.analytics || {};
            document.getElementById("global-deps").innerHTML = (an.top_deps || []).map(i => `<li><code>${i[0]}</code>: ${i[1]} flights</li>`).join('');
            document.getElementById("global-fleet").innerHTML = (an.top_aircraft || []).map(i => `<li><b>${i[0]}</b>: ${i[1]} aircraft</li>`).join('');
            document.getElementById("global-atc").innerHTML = (an.top_atc || []).map(i => `<li><code>${i[0]}_CTR</code>: ${i[1]} frequencies</li>`).join('');

            filterData();
        }
    } catch (e) { console.error(e); }
}

function triggerManualRefresh() { runRadarEngine(); }

async function authAdmin() {
    const pwd = document.getElementById("admin-password").value;
    try {
        const res = await fetch(`http://127.0.0.1:8000/api/admin/logs?password=${pwd}`);
        if(res.status === 200) {
            const data = await res.json();
            document.getElementById("admin-auth-box").style.display = "none";
            document.getElementById("admin-dashboard").style.display = "block";
            document.getElementById("adm-active").innerText = data.active_now;
            document.getElementById("adm-total").innerText = data.total_unique;
            document.getElementById("adm-hw").innerText = data.dominant_hardware;
            
            const abody = document.getElementById("admin-logs-body"); abody.innerHTML = "";
            data.logs.forEach(l => {
                abody.innerHTML += `<tr><td>${l.Timestamp}</td><td>${l.Device_Type}</td><td>${l.OS}</td><td>${l.Browser}</td><td>${l.Last_Action}</td></tr>`;
            });
        } else { alert("Invalid Secret Token."); }
    } catch(e) { alert("Auth failed."); }
}

async function wipeLogs() {
    const pwd = document.getElementById("admin-password").value;
    await fetch(`http://127.0.0.1:8000/api/admin/logs/wipe?password=${pwd}`, {method: 'DELETE'});
    authAdmin();
}

setInterval(runRadarEngine, 30000);