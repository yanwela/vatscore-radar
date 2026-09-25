function wxrLatestFrame(index) {
    if (typeof index !== "object" || index === null || index.host !== "https://tilecache.rainviewer.com") {
        return null;
    }
    var radar = index.radar;
    if (typeof radar !== "object" || radar === null || !Array.isArray(radar.past)) {
        return null;
    }
    var past = radar.past;
    var pathRegex = /^\/v2\/radar\/[A-Za-z0-9_-]{6,64}$/;
    var best = null;
    for (var i = 0; i < past.length; i++) {
        var item = past[i];
        if (typeof item !== "object" || item === null) continue;
        var time = item.time;
        var path = item.path;
        if (typeof time !== "number" || !isFinite(time)) continue;
        if (typeof path !== "string" || !pathRegex.test(path)) continue;
        if (best === null || time > best.time) {
            best = { host: index.host, path: path, time: time };
        }
    }
    return best;
}
function wxrTileUrl(frame, scheme, smooth, snow) {
    if (typeof frame !== "object" || frame === null || typeof frame.host !== "string" || typeof frame.path !== "string") {
        return null;
    }
    var s = 6;
    if (Number.isInteger(scheme) && scheme >= 0 && scheme <= 8) {
        s = scheme;
    }
    var sm = 1;
    if (typeof smooth === "number" && (smooth === 0 || smooth === 1)) {
        sm = smooth;
    }
    var sn = 1;
    if (typeof snow === "number" && (snow === 0 || snow === 1)) {
        sn = snow;
    }
    return frame.host + frame.path + "/256/{z}/{x}/{y}/" + s + "/" + sm + "_" + sn + ".png";
}
function wxrAgeText(frameTimeS, nowS) {
    if (typeof frameTimeS !== "number" || !isFinite(frameTimeS) || typeof nowS !== "number" || !isFinite(nowS)) {
        return "";
    }
    var m = Math.max(0, Math.floor((nowS - frameTimeS) / 60));
    if (m < 1) {
        return "just now";
    }
    if (m < 90) {
        return m + " min old";
    }
    return Math.floor(m / 60) + "h " + (m % 60) + "m old";
}
function wxrTimeText(frameTimeS) {
    if (typeof frameTimeS !== "number" || !isFinite(frameTimeS)) {
        return "";
    }
    return new Date(frameTimeS * 1000).toISOString().slice(11, 16) + "Z";
}