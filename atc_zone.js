const ATC_ZONES = {
  DEL: { radiusNm: 3, leadS: 0, tailS: 0, dirs: ["out", "local"] },
  GND: { radiusNm: 3, leadS: 300, tailS: 0, dirs: ["out", "in", "local"] },
  TWR: { radiusNm: 8, leadS: 480, tailS: 300, dirs: ["out", "in", "local"] },
  APP: { radiusNm: 40, leadS: 900, tailS: 600, dirs: ["out", "in", "local"] },
  CTR: { radiusNm: 0, leadS: 600, tailS: 600, dirs: ["local"] },
  FSS: { radiusNm: 0, leadS: 600, tailS: 600, dirs: ["local"] }
};
const ATC_SPAN_GAP_S = 300;
function atcZone(role) {
  return ATC_ZONES.hasOwnProperty(role) ? ATC_ZONES[role] : null;
}
function atcDistNm(lat1, lon1, lat2, lon2) {
  const toRad = v => Number(v) * Math.PI / 180;
  const φ1 = toRad(lat1);
  const φ2 = toRad(lat2);
  const Δφ = toRad(lat2 - lat1);
  const Δλ = toRad(lon2 - lon1);
  const a = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return 3440.065 * c;
}
function atcInZone(role, distNm, aglFt, gs) {
  const zone = atcZone(role);
  if (!zone) return false;
  if (typeof distNm !== "number" || isNaN(distNm) || distNm > zone.radiusNm) return false;
  const agl = Number(aglFt);
  const speed = Number(gs);
  if (role === "DEL" || role === "GND") {
    return agl <= 200 && speed <= 40;
  }
  if (role === "TWR") {
    return agl <= 3500 && !(agl <= 200 && speed < 15);
  }
  if (role === "APP") {
    return agl >= 300 && agl <= 15000;
  }
  return false;
}
function atcFlightSpans(points, airport, role, direction) {
  const zone = atcZone(role);
  if (!zone || !Array.isArray(zone.dirs) || !zone.dirs.includes(direction) || !Array.isArray(points)) return [];
  const elev = Number(airport && airport.elevation) || 0;
  const spans = [];
  let current = null;
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (!Array.isArray(p) || p.length < 5) continue;
    const lat = Number(p[0]);
    const lon = Number(p[1]);
    const altFt = Number(p[2]);
    const t = Number(p[3]);
    const gs = Number(p[4] || 0);
    if ([lat, lon, altFt, t, gs].some(v => typeof v !== "number" || isNaN(v))) continue;
    const agl = altFt - elev;
    const d = atcDistNm(lat, lon, airport.lat, airport.lon);
    const inside = atcInZone(role, d, agl, gs);
    if (inside) {
      if (current && t - current[1] <= ATC_SPAN_GAP_S) {
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
function atcVisibility(spans, t, direction, role) {
  const zone = atcZone(role);
  if (!zone || !Array.isArray(spans) || spans.length === 0) return null;
  const time = Number(t);
  if (typeof time !== "number" || isNaN(time)) return null;
  for (let i = 0; i < spans.length; i++) {
    const span = spans[i];
    if (Array.isArray(span) && span.length >= 2) {
      const start = Number(span[0]);
      const end = Number(span[1]);
      if (time >= start && time <= end) return "in";
    }
  }
  const first = Number(spans[0][0]);
  const last = Number(spans[spans.length - 1][1]);
  if (time < first && (direction === "in" || direction === "local") && time >= first - zone.leadS) return "lead";
  if (time > last && (direction === "out" || direction === "local") && time <= last + zone.tailS) return "tail";
  return null;
}