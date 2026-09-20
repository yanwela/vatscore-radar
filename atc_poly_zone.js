const ATC_POLY_GAP_S = 300;

function atcRingContains(ring, lat, lon) {
    if (!Array.isArray(ring) || ring.length < 3) return false;
    let inside = false;
    let j = ring.length - 1;
    for (let i = 0; i < ring.length; i++) {
        const yi = ring[i][0];
        const xi = ring[i][1];
        const yj = ring[j][0];
        const xj = ring[j][1];
        if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
            inside = !inside;
        }
        j = i;
    }
    return inside;
}

function atcPolyContains(rings, lat, lon) {
    return Array.isArray(rings) && rings.some(r => atcRingContains(r, lat, lon));
}

function atcPolySpans(points, rings) {
    if (!Array.isArray(points) || !Array.isArray(rings)) return [];
    const spans = [];
    let current = null;
    for (const p of points) {
        if (!Array.isArray(p) || p.length < 4) continue;
        const lat = p[0];
        const lon = p[1];
        const t = p[3];
        if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(t)) continue;
        const inside = atcPolyContains(rings, lat, lon);
        if (inside) {
            if (current && t - current[1] <= ATC_POLY_GAP_S) {
                current[1] = t;
            } else {
                if (current) spans.push(current);
                current = [t, t];
            }
        } else {
            if (current) {
                spans.push(current);
                current = null;
            }
        }
    }
    if (current) spans.push(current);
    return spans;
}