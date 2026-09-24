const toRad = v => {
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new TypeError('Invalid number');
  return v * Math.PI / 180;
};

function followDistanceNm(lat1, lon1, lat2, lon2) {
  if (typeof lat1 !== 'number' || !Number.isFinite(lat1)) throw new TypeError('Invalid lat1');
  if (typeof lon1 !== 'number' || !Number.isFinite(lon1)) throw new TypeError('Invalid lon1');
  if (typeof lat2 !== 'number' || !Number.isFinite(lat2)) throw new TypeError('Invalid lat2');
  if (typeof lon2 !== 'number' || !Number.isFinite(lon2)) throw new TypeError('Invalid lon2');
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return 3440.065 * c;
}

function shouldRecenterMap(centerLat, centerLon, planeLat, planeLon, thresholdNm) {
  if (typeof centerLat !== 'number' || !Number.isFinite(centerLat)) throw new TypeError('Invalid centerLat');
  if (typeof centerLon !== 'number' || !Number.isFinite(centerLon)) throw new TypeError('Invalid centerLon');
  if (typeof planeLat !== 'number' || !Number.isFinite(planeLat)) throw new TypeError('Invalid planeLat');
  if (typeof planeLon !== 'number' || !Number.isFinite(planeLon)) throw new TypeError('Invalid planeLon');
  if (typeof thresholdNm !== 'number' || !Number.isFinite(thresholdNm)) throw new TypeError('Invalid thresholdNm');
  return followDistanceNm(centerLat, centerLon, planeLat, planeLon) > thresholdNm;
}
