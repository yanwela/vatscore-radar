function tgDistNm(lat1, lon1, lat2, lon2) {
  const R = 3440.065;
  const toRad = function (d) { return d * Math.PI / 180; };
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function trackStepPlausible(prev, next) {
  if (!Array.isArray(prev) || !Array.isArray(next)) return false;
  if (typeof prev[0] !== "number" || !isFinite(prev[0]) ||
      typeof prev[1] !== "number" || !isFinite(prev[1]) ||
      typeof prev[2] !== "number" || !isFinite(prev[2]) ||
      typeof prev[3] !== "number" || !isFinite(prev[3]) ||
      typeof next[0] !== "number" || !isFinite(next[0]) ||
      typeof next[1] !== "number" || !isFinite(next[1]) ||
      typeof next[2] !== "number" || !isFinite(next[2]) ||
      typeof next[3] !== "number" || !isFinite(next[3])) return false;
  const nm = tgDistNm(prev[0], prev[1], next[0], next[1]);
  const dt = next[3] - prev[3];
  const dalt = Math.abs(next[2] - prev[2]);
  if (dt <= 0) {
    return nm <= 2 && dalt <= 2000;
  }
  return nm <= 2 + (dt / 3600) * 1100 && dalt <= 2000 + (dt / 60) * 15000;
}

function liveVerticalSpeedFpm(points) {
  if (!Array.isArray(points)) return null;
  const slope = function (list, minDt) {
    if (list.length < 2) return null;
    const last = list[list.length - 1];
    for (let i = list.length - 2; i >= 0; i--) {
      const dt = last[3] - list[i][3];
      if (dt >= minDt) {
        if (dt > 900) return null;
        return Math.round(((last[2] - list[i][2]) / (dt / 60)) / 50) * 50;
      }
    }
    return null;
  };
  const live = points.filter(function (q) { return Array.isArray(q) && q[5] === 1; });
  const rec = points.filter(function (q) { return Array.isArray(q) && q[5] !== 1; });
  let v = live.length >= 2 ? slope(live, 45) : null;
  if (v === null) v = slope(rec, 120);
  if (v !== null && Math.abs(v) > 12000) return null;
  return v;
}

function pickLiveEntry(pilots, cid, callsign, ref) {
  if (!Array.isArray(pilots)) return null;
  const matches = pilots.filter(function (x) {
    return x && typeof x === "object" && String(x.cid) === String(cid) && x.callsign === callsign;
  });
  if (matches.length === 0) return null;
  if (matches.length === 1) return matches[0];
  if (ref && typeof ref.lat === "number" && isFinite(ref.lat) &&
      typeof ref.lon === "number" && isFinite(ref.lon)) {
    const valid = matches.filter(function (x) {
      return typeof x.latitude === "number" && isFinite(x.latitude) &&
             typeof x.longitude === "number" && isFinite(x.longitude);
    });
    if (valid.length > 0) {
      let best = valid[0];
      let bestD = tgDistNm(ref.lat, ref.lon, best.latitude, best.longitude);
      for (let i = 1; i < valid.length; i++) {
        const d = tgDistNm(ref.lat, ref.lon, valid[i].latitude, valid[i].longitude);
        if (d < bestD) {
          bestD = d;
          best = valid[i];
        }
      }
      return best;
    }
  }
  return matches[0];
}