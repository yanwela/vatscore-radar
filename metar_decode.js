function decodeMetar(text) {
    if (typeof text !== "string") return null;
    const rawTokens = text.trim().split(/\s+/);
    if (rawTokens.length === 0 || (rawTokens.length === 1 && rawTokens[0] === "")) return null;
    let tokens = rawTokens.slice();
    if (tokens[0] === "METAR" || tokens[0] === "SPECI") tokens = tokens.slice(1);
    if (tokens.length < 2) return null;
    const station = tokens[0];
    if (!/^[A-Z0-9]{4}$/.test(station)) return null;
    const timeMatch = tokens[1].match(/^(\d{2})(\d{2})(\d{2})Z$/);
    if (!timeMatch) return null;
    const time_z = timeMatch[2] + ":" + timeMatch[3] + "Z";
    const stopTokens = new Set(["RMK", "TEMPO", "BECMG", "PROB30", "PROB40"]);
    const body = [];
    for (let i = 2; i < tokens.length; i++) {
        const t = tokens[i];
        if (stopTokens.has(t) || /^FM\d+/.test(t)) break;
        if (t === "AUTO" || t === "COR" || t === "NIL") continue;
        body.push(t);
    }
    const result = {
        station: station,
        time_z: time_z,
        wind_dir: null,
        wind_variable: false,
        wind_speed_kt: null,
        wind_gust_kt: null,
        wind_var_from: null,
        wind_var_to: null,
        cavok: false,
        visibility_m: null,
        clouds: [],
        ceiling_ft: null,
        weather: [],
        temp_c: null,
        dew_c: null,
        altimeter_inhg: null,
        qnh_hpa: null,
        category: null
    };
    // WIND
    for (const t of body) {
        const m = t.match(/^(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)$/);
        if (m) {
            if (m[1] === "VRB") {
                result.wind_variable = true;
                result.wind_dir = null;
            } else {
                result.wind_dir = parseInt(m[1], 10);
            }
            const speedVal = parseInt(m[2], 10);
            const gustVal = m[3] ? parseInt(m[3], 10) : null;
            const unit = m[4];
            const toKnots = (val) => {
                if (unit === "KT") return val;
                if (unit === "MPS") return Math.floor(val * 1.943844 + 0.5);
                return Math.floor(val / 1.852 + 0.5);
            };
            result.wind_speed_kt = toKnots(speedVal);
            result.wind_gust_kt = gustVal !== null ? toKnots(gustVal) : null;
            break;
        }
    }
    // WIND VARIATION
    for (const t of body) {
        const m = t.match(/^(\d{3})V(\d{3})$/);
        if (m) {
            result.wind_var_from = parseInt(m[1], 10);
            result.wind_var_to = parseInt(m[2], 10);
            break;
        }
    }
    // CAVOK
    if (body.includes("CAVOK")) {
        result.cavok = true;
        result.visibility_m = 10000;
    }
    // VISIBILITY
    if (!result.cavok) {
        for (let i = 0; i < body.length; i++) {
            const t = body[i];
            let m;
            if (/^\d{4}$/.test(t)) {
                result.visibility_m = parseInt(t, 10);
                break;
            }
            if ((m = t.match(/^(\d+)SM$/))) {
                const sm = parseInt(m[1], 10);
                result.visibility_m = Math.floor(sm * 1609.344 + 0.5);
                break;
            }
            if ((m = t.match(/^P(\d+)SM$/))) {
                const sm = parseInt(m[1], 10);
                result.visibility_m = Math.floor(sm * 1609.344 + 0.5);
                break;
            }
            if ((m = t.match(/^M(\d)\/(\d)SM$/))) {
                const sm = parseInt(m[1], 10) / parseInt(m[2], 10);
                result.visibility_m = Math.floor(sm * 1609.344 + 0.5);
                break;
            }
            if ((m = t.match(/^(\d)\/(\d)SM$/))) {
                const sm = parseInt(m[1], 10) / parseInt(m[2], 10);
                result.visibility_m = Math.floor(sm * 1609.344 + 0.5);
                break;
            }
            if (/^\d$/.test(t) && i + 1 < body.length && (m = body[i + 1].match(/^(\d)\/(\d)SM$/))) {
                const whole = parseInt(t, 10);
                const frac = parseInt(m[1], 10) / parseInt(m[2], 10);
                const sm = whole + frac;
                result.visibility_m = Math.floor(sm * 1609.344 + 0.5);
                break;
            }
        }
    }
    // CLOUDS and CEILING
    let vvFt = null;
    for (const t of body) {
        let m;
        if ((m = t.match(/^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?$/))) {
            const cover = m[1];
            const height_ft = parseInt(m[2], 10) * 100;
            const type = m[3] || null;
            result.clouds.push({ cover, height_ft, type });
            if (cover === "BKN" || cover === "OVC") {
                if (result.ceiling_ft === null || height_ft < result.ceiling_ft) {
                    result.ceiling_ft = height_ft;
                }
            }
        } else if ((m = t.match(/^VV(\d{3})$/))) {
            vvFt = parseInt(m[1], 10) * 100;
        }
    }
    if (vvFt !== null) {
        if (result.ceiling_ft === null || vvFt < result.ceiling_ft) {
            result.ceiling_ft = vvFt;
        }
    }
    // TEMPERATURE
    for (const t of body) {
        const m = t.match(/^(M?\d{2})\/(M?\d{2})?$/);
        if (m) {
            const parseTemp = (s) => {
                if (s.startsWith("M")) return -parseInt(s.slice(1), 10);
                return parseInt(s, 10);
            };
            result.temp_c = parseTemp(m[1]);
            result.dew_c = m[2] ? parseTemp(m[2]) : null;
            break;
        }
    }
    // PRESSURE
    for (const t of body) {
        let m;
        if ((m = t.match(/^Q(\d{4})$/))) {
            const qnh = parseInt(m[1], 10);
            result.qnh_hpa = qnh;
            result.altimeter_inhg = Math.round(qnh / 33.8639 * 100) / 100;
            break;
        }
        if ((m = t.match(/^A(\d{4})$/))) {
            const alt = parseInt(m[1], 10) / 100;
            result.altimeter_inhg = alt;
            result.qnh_hpa = Math.floor(alt * 33.8639 + 0.5);
            break;
        }
    }
    // WEATHER
    for (const t of body) {
        if (/^[-+]?(VC)?(MI|BC|PR|DR|BL|SH|TS|FZ)?(DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$/.test(t)) {
            result.weather.push(t);
        }
    }
    // CATEGORY
    const visSm = result.visibility_m !== null ? Math.round(result.visibility_m / 1609.344 * 100) / 100 : null;
    const visCat = visSm === null ? "VFR" : visSm < 1 ? "LIFR" : visSm < 3 ? "IFR" : visSm <= 5 ? "MVFR" : "VFR";
    const ceilCat = result.ceiling_ft === null ? "VFR" : result.ceiling_ft < 500 ? "LIFR" : result.ceiling_ft < 1000 ? "IFR" : result.ceiling_ft <= 3000 ? "MVFR" : "VFR";
    if (result.cavok) {
        result.category = "VFR";
    } else if (result.visibility_m === null && result.ceiling_ft === null && result.clouds.length === 0) {
        result.category = null;
    } else {
        const order = { VFR: 0, MVFR: 1, IFR: 2, LIFR: 3 };
        result.category = order[visCat] > order[ceilCat] ? visCat : ceilCat;
    }
    return result;
}