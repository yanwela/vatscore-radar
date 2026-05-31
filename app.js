let rawPilots = [];
let globalDossiers = {};
let currentFleetFilter = 'All';
const BACKEND_API = "http://127.0.0.1:8000/api/vatsim";

// Sekme Değiştirici
function switchTab(evt, tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    evt.target.classList.add('active');
}

// Fleet Filtresi Seçimi
function setFleetFilter(evt, filterType) {
    document.querySelectorAll('.filter-btn').forEach(el => el.classList.remove('active'));
    evt.target.classList.add('active');
    currentFleetFilter = filterType;
    filterData(); // Tabloyu yeniden çiz
}

// Uçak Sınıflandırma Motoru (Eski Python Mantığı)
function classifyAircraft(acType, callsign) {
    acType = String(acType || "").toUpperCase().trim();
    callsign = String(callsign || "").toUpperCase().trim();
    
    const militaryTypes = ["F16", "F18", "F15", "F22", "F35", "F4", "F5", "EFAF", "SU27", "C17", "A400M", "C130", "KC135"];
    const militaryPrefixes = ["TUR", "RCH", "AME", "BAF", "GAF", "MIL", "ASY"];
    
    if (militaryTypes.includes(acType) || militaryPrefixes.some(pfx => callsign.startsWith(pfx)) || callsign.includes("MIL")) {
        return "⚔️ Military";
    }
    
    const gaTypes = ["C150", "C152", "C172", "C182", "PA28", "DA40", "DA42", "SR22"];
    if (gaTypes.includes(acType)) return "🛩️ General Aviation";
    
    return "✈️ Commercial";
}

// Ana Filtreleme ve Tabloyu Çizme Fonksiyonu
function filterData() {
    const selectedFir = document.getElementById("fir-dropdown").value;
    const tbody = document.getElementById("table-body");
    tbody.innerHTML = "";
    globalDossiers = {};

    let records = { maxAlt: -1, maxAltP: null, maxSpd: -1, maxSpdP: null, longest: "9999", longestP: null };
    let anomalies = [];

    rawPilots.forEach(p => {
        const callsign = p.callsign || "N/A";
        const alt = p.altitude || 0;
        const gs = p.groundspeed || 0;
        const fplan = p.flight_plan || {};
        const dep = fplan.departure || "";
        const arr = fplan.arrival || "";
        const acType = (fplan.aircraft || "").split("/")[0] || "N/A";
        
        const category = classifyAircraft(acType, callsign);

        // --- Anomalileri Topla ---
        if (p.transponder === 7700) {
            anomalies.push({ type: "🚨 EMERGENCY (7700)", callsign, details: "Declared Mayday", acType });
        }
        if (gs > 1150) {
            anomalies.push({ type: "⚡ Warp Speed Glitch", callsign, details: `Speed: ${gs} KT`, acType });
        }
        if (category === "⚔️ Military") {
            anomalies.push({ type: "⚔️ Tactical Sortie", callsign, details: "Military Deployment", acType });
        }

        // --- Rekorları Hesapla (Leaderboard) ---
        if (alt > records.maxAlt) { records.maxAlt = alt; records.maxAltP = p; }
        if (gs > records.maxSpd) { records.maxSpd = gs; records.maxSpdP = p; }
        if (p.logon_time && p.logon_time < records.longest) { records.longest = p.logon_time; records.longestP = p; }

        // --- FIR ve Fleet Filtrelerini Uygula ---
        const matchesFir = dep.startsWith(selectedFir) || arr.startsWith(selectedFir);
        let isPhysicallyInTr = false;
        if (selectedFir === "LT" && (p.latitude >= 36.5 && p.latitude <= 42.0) && (p.longitude >= 27.0 && p.longitude <= 44.5)) {
            isPhysicallyInTr = true;
        }

        if (matchesFir || isPhysicallyInTr) {
            if (currentFleetFilter === 'Commercial' && category !== '✈️ Commercial') return;
            if (currentFleetFilter === 'General' && category !== '🛩️ General Aviation') return;
            if (currentFleetFilter === 'Military' && category !== '⚔️ Military') return;

            // Dossier Verisini Hazırla
            globalDossiers[callsign] = {
                name: p.name || "Anonymous", cid: p.cid || "N/A",
                online: p.logon_time ? Math.floor((new Date() - new Date(p.logon_time)) / 60000) + " Mins" : "N/A",
                voice: p.has_voice ? "🎙️ Voice Active" : "⌨️ Text Only",
                origin: dep || "⚠️ NO FPL", destination: arr || "⚠️ NO FPL", route: fplan.route || "No FPL Filed."
            };

            const tr = document.createElement("tr");
            tr.onclick = () => openDossier(callsign);
            tr.innerHTML = `
                <td><b style="color:#3b82f6;">${callsign}</b></td>
                <td>${dep || "⚠️ NO FPL"}</td>
                <td>${arr || "⚠️ NO FPL"}</td>
                <td>${acType}</td>
                <td>${alt.toLocaleString()} FT</td>
                <td>${gs} KT</td>
                <td>${p.transponder || "0000"}</td>
            `;
            tbody.appendChild(tr);
        }
    });

    buildLeaderboard(records);
    buildAnomalies(anomalies);
}

// Leaderboard'u Çiz
function buildLeaderboard(rec) {
    const lBody = document.getElementById("leaderboard-body");
    lBody.innerHTML = "";
    if(rec.maxAltP) addRow(lBody, ["Highest Cruising Altitude", rec.maxAltP.callsign, `${rec.maxAlt.toLocaleString()} FT`, rec.maxAltP.name]);
    if(rec.maxSpdP) addRow(lBody, ["Maximum Velocity (GS)", rec.maxSpdP.callsign, `${rec.maxSpd} KT`, rec.maxSpdP.name]);
    if(rec.longestP) addRow(lBody, ["Longest Session Active", rec.longestP.callsign, `Since ${rec.longestP.logon_time.substring(11,16)} Z`, rec.longestP.name]);
}

// Anomalileri Çiz
function buildAnomalies(anomaliesList) {
    const aBody = document.getElementById("anomaly-body");
    aBody.innerHTML = "";
    if(anomaliesList.length === 0) {
        aBody.innerHTML = `<tr><td colspan="4" style="color:#22c55e; text-align:center; padding:15px;">Sky is clear. No telemetric anomalies or emergencies detected.</td></tr>`;
        return;
    }
    anomaliesList.forEach(a => addRow(aBody, [a.type, a.callsign, a.details, a.acType]));
}

function addRow(targetElement, cellArray) {
    const tr = document.createElement("tr");
    cellArray.forEach(text => { const td = document.createElement("td"); td.innerText = text; tr.appendChild(td); });
    targetElement.appendChild(tr);
}

// Modal Kontrolleri
function openDossier(callsign) {
    const p = globalDossiers[callsign];
    if (!p) return;
    document.getElementById("popCallsign").innerText = "Target Profile: " + callsign;
    document.getElementById("popName").innerText = p.name;
    document.getElementById("popCid").innerText = p.cid;
    document.getElementById("popOnline").innerText = p.online;
    document.getElementById("popVoice").innerText = p.voice;
    document.getElementById("popOrigin").innerText = p.origin;
    document.getElementById("popDestination").innerText = p.destination;
    document.getElementById("popRoute").value = p.route;
    document.getElementById("dossierModal").style.display = "block";
}
function closeModal() { document.getElementById("dossierModal").style.display = "none"; }

// --- 🚀 ÖLÜMSÜZ AUTO-REFRESH ZAMANLAYICISI ---
async function runRadarEngine() {
    while (true) {
        const notifier = document.getElementById("sync-notification");
        if(notifier) notifier.style.display = "block";

        try {
            const res = await fetch(BACKEND_API);
            const data = await res.json();
            if (data) {
                rawPilots = data.pilots || [];
                document.getElementById("stat-pilots").innerText = rawPilots.length;
                document.getElementById("stat-atcs").innerText = (data.controllers || []).length;
                document.getElementById("stat-sync").innerText = new Date().toLocaleTimeString() + " LOC";
                
                filterData(); // Yeni verilerle ekranı güncelle
            }
        } catch (e) { console.error("FastAPI connection down:", e); }

        if(notifier) setTimeout(() => { notifier.style.display = "none"; }, 1200);
        await new Promise(r => setTimeout(r, 30000)); // 30 Saniye kuralı
    }
}

runRadarEngine();