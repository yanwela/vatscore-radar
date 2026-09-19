function replayIndexAt(points, t) {
    if (!Array.isArray(points) || points.length === 0 || typeof t !== 'number' || !isFinite(t)) {
        return -1;
    }
    let lo = 0, hi = points.length - 1;
    if (t < points[0][3]) return -1;
    let ans = -1;
    while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (points[mid][3] <= t) {
            ans = mid;
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    return ans;
}

function _normLon(lon) {
    lon = ((lon + 180) % 360 + 360) % 360 - 180;
    return lon;
}

function _bearingDeg(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const phi1 = lat1 * toRad;
    const phi2 = lat2 * toRad;
    const dLon = (lon2 - lon1) * toRad;
    const y = Math.sin(dLon) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
    let brg = Math.atan2(y, x) * 180 / Math.PI;
    brg = (brg + 360) % 360;
    return brg;
}

function _sameLoc(a, b) {
    return a[0] === b[0] && a[1] === b[1];
}

function replayStateAt(points, t) {
    if (!Array.isArray(points) || points.length === 0 || typeof t !== 'number' || !isFinite(t)) {
        return null;
    }
    const n = points.length;
    const first = points[0];
    const last = points[n - 1];

    if (t <= first[3]) {
        let heading = 0;
        for (let i = 0; i < n - 1; i++) {
            if (!_sameLoc(points[i], points[i + 1])) {
                heading = _bearingDeg(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1]);
                break;
            }
        }
        return { lat: first[0], lon: first[1], alt: first[2], gs: first[4], heading: heading, t: first[3] };
    }

    if (t >= last[3]) {
        let heading = 0;
        for (let i = n - 1; i > 0; i--) {
            if (!_sameLoc(points[i - 1], points[i])) {
                heading = _bearingDeg(points[i - 1][0], points[i - 1][1], points[i][0], points[i][1]);
                break;
            }
        }
        return { lat: last[0], lon: last[1], alt: last[2], gs: last[4], heading: heading, t: last[3] };
    }

    const idx = replayIndexAt(points, t);
    const i = idx;
    const j = i + 1;
    const p1 = points[i];
    const p2 = points[j];

    let f = 0;
    const dt = p2[3] - p1[3];
    if (dt !== 0) {
        f = (t - p1[3]) / dt;
    }

    const lat = p1[0] + (p2[0] - p1[0]) * f;
    const alt = p1[2] + (p2[2] - p1[2]) * f;
    const gs = p1[4] + (p2[4] - p1[4]) * f;

    let dLon = p2[1] - p1[1];
    dLon = ((dLon + 180) % 360 + 360) % 360 - 180;
    const lon = _normLon(p1[1] + dLon * f);

    let heading = 0;
    if (!_sameLoc(p1, p2)) {
        heading = _bearingDeg(p1[0], p1[1], p2[0], p2[1]);
    } else {
        for (let k = j + 1; k < n; k++) {
            if (!_sameLoc(p1, points[k])) {
                heading = _bearingDeg(p1[0], p1[1], points[k][0], points[k][1]);
                break;
            }
        }
        if (heading === 0) {
            for (let k = i - 1; k >= 0; k--) {
                if (!_sameLoc(p1, points[k])) {
                    heading = _bearingDeg(p1[0], p1[1], points[k][0], points[k][1]);
                    break;
                }
            }
        }
    }

    return { lat: lat, lon: lon, alt: alt, gs: gs, heading: heading, t: t };
}

function replayClock(t) {
    if (typeof t !== 'number' || !isFinite(t)) {
        return "-";
    }
    const d = new Date(t * 1000);
    const h = d.getUTCHours();
    const m = d.getUTCMinutes();
    const hh = h < 10 ? "0" + h : "" + h;
    const mm = m < 10 ? "0" + m : "" + m;
    return hh + ":" + mm + "Z";
}

function replayDuration(seconds) {
    if (typeof seconds !== 'number' || !isFinite(seconds) || seconds < 0) {
        return "0h 00m";
    }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const mm = minutes < 10 ? "0" + minutes : "" + minutes;
    return hours + "h " + mm + "m";
}