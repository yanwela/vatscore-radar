function replayPhaseMarkers(points, gapSeconds) {
  if (gapSeconds === undefined) {
    gapSeconds = 600;
  }
  if (!Array.isArray(points) || points.length < 5) {
    return [];
  }

  let maxAlt = -Infinity;
  let maxGs = -Infinity;
  for (let i = 0; i < points.length; i++) {
    const alt = points[i][2];
    const gs = points[i][4];
    if (alt > maxAlt) maxAlt = alt;
    if (gs > maxGs) maxGs = gs;
  }

  // 1. takeoff
  let takeoffIdx = -1;
  for (let i = 1; i < points.length; i++) {
    if (points[i][4] >= 60 && points[i - 1][4] < 60) {
      takeoffIdx = i;
      break;
    }
  }

  // 2. toc
  let tocIdx = -1;
  if (maxAlt >= 5000 && points[0][2] < 0.7 * maxAlt) {
    for (let i = 0; i < points.length; i++) {
      if (points[i][2] >= 0.97 * maxAlt) {
        tocIdx = i;
        break;
      }
    }
  }

  // 3. maxalt
  let maxaltIdx = -1;
  if (maxAlt >= 5000) {
    for (let i = 0; i < points.length; i++) {
      if (points[i][2] === maxAlt) {
        maxaltIdx = i;
        break;
      }
    }
  }

  // 4. maxgs
  let maxgsIdx = -1;
  if (maxGs >= 100) {
    for (let i = 0; i < points.length; i++) {
      if (points[i][4] === maxGs) {
        maxgsIdx = i;
        break;
      }
    }
  }

  // 5. tod
  let todIdx = -1;
  if (maxAlt >= 5000) {
    let lastAbove = -1;
    for (let i = points.length - 1; i >= 0; i--) {
      if (points[i][2] >= 0.97 * maxAlt) {
        lastAbove = i;
        break;
      }
    }
    if (lastAbove !== -1 && lastAbove !== tocIdx) {
      let hasLaterLow = false;
      for (let j = lastAbove + 1; j < points.length; j++) {
        if (points[j][2] < 0.7 * maxAlt) {
          hasLaterLow = true;
          break;
        }
      }
      if (hasLaterLow) {
        todIdx = lastAbove;
      }
    }
  }

  // 6. landing
  let landingIdx = -1;
  let lastGs60 = -1;
  for (let i = points.length - 1; i >= 0; i--) {
    if (points[i][4] >= 60) {
      lastGs60 = i;
      break;
    }
  }
  if (lastGs60 !== -1) {
    const afterTakeoff = takeoffIdx === -1 || lastGs60 > takeoffIdx;
    const lastAltLow = points[points.length - 1][2] < 0.3 * maxAlt;
    if (afterTakeoff && lastAltLow) {
      landingIdx = lastGs60;
    }
  }

  const usedIndices = new Set();
  const markers = [];

  function addMarker(kind, index) {
    if (index !== -1 && !usedIndices.has(index)) {
      usedIndices.add(index);
      markers.push({
        kind: kind,
        index: index,
        t: points[index][3],
        lat: points[index][0],
        lon: points[index][1],
        alt: points[index][2]
      });
    }
  }

  if (takeoffIdx !== -1) addMarker("takeoff", takeoffIdx);
  if (tocIdx !== -1) addMarker("toc", tocIdx);
  if (maxaltIdx !== -1) addMarker("maxalt", maxaltIdx);
  if (maxgsIdx !== -1) addMarker("maxgs", maxgsIdx);
  if (todIdx !== -1) addMarker("tod", todIdx);
  if (landingIdx !== -1) addMarker("landing", landingIdx);

  for (let i = 1; i < points.length; i++) {
    // only a hole in the FLIGHT is a reconnection: between takeoff and landing (a gap on the ground before takeoff or after landing is not);
    // without a takeoff in the record (it starts in the air) the aircraft must have been moving when the record broke off
    const inFlight = takeoffIdx !== -1
      ? (i > takeoffIdx && (landingIdx === -1 || i <= landingIdx))
      : points[i - 1][4] >= 60;
    if (inFlight && points[i][3] - points[i - 1][3] > gapSeconds) {
      // a reconnection is always shown, even when it sits on the same point as another marker (e.g. logging on again at cruise level)
      markers.push({ kind: "reconnect", index: i, t: points[i][3], lat: points[i][0], lon: points[i][1], alt: points[i][2] });
    }
  }

  markers.sort((a, b) => a.index - b.index);
  return markers;
}

function replayNextTime(points, t, gapSeconds) {
  if (gapSeconds === undefined) {
    gapSeconds = 600;
  }
  if (!Array.isArray(points) || points.length === 0 || typeof t !== 'number' || !isFinite(t)) {
    return t;
  }

  let low = 0;
  let high = points.length - 1;
  let i = -1;
  while (low <= high) {
    let mid = (low + high) >> 1;
    if (points[mid][3] <= t) {
      i = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  if (i >= 0 && i + 1 < points.length && t > points[i][3] && (points[i + 1][3] - points[i][3] > gapSeconds)) {
    return points[i + 1][3];
  }
  return t;
}