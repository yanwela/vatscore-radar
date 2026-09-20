import re

def decode_metar(text):
    if not isinstance(text, str):
        return None
    tokens = text.split()
    if tokens and tokens[0] in ("METAR", "SPECI"):
        tokens = tokens[1:]
    if len(tokens) < 2:
        return None
    station = tokens[0]
    if not re.fullmatch(r'^[A-Z0-9]{4}$', station):
        return None
    if not re.fullmatch(r'^(\d{2})(\d{2})(\d{2})Z$', tokens[1]):
        return None
    m = re.fullmatch(r'^(\d{2})(\d{2})(\d{2})Z$', tokens[1])
    dd, hh, mm = m.group(1), m.group(2), m.group(3)
    time_z = hh + ":" + mm + "Z"
    body = tokens[2:]
    cut_idx = len(body)
    for i, tok in enumerate(body):
        if tok in ("RMK", "TEMPO", "BECMG", "PROB30", "PROB40") or re.fullmatch(r'^FM\d+', tok):
            cut_idx = i
            break
    body = body[:cut_idx]
    result = {
        "station": station,
        "time_z": time_z,
        "wind_dir": None,
        "wind_variable": False,
        "wind_speed_kt": None,
        "wind_gust_kt": None,
        "wind_var_from": None,
        "wind_var_to": None,
        "cavok": False,
        "visibility_m": None,
        "clouds": [],
        "ceiling_ft": None,
        "weather": [],
        "temp_c": None,
        "dew_c": None,
        "altimeter_inhg": None,
        "qnh_hpa": None,
        "category": None
    }
    wind_re = re.compile(r'^(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)$')
    for tok in body:
        m = wind_re.fullmatch(tok)
        if m:
            g1, g2, g3, unit = m.group(1), m.group(2), m.group(3), m.group(4)
            if g1 == "VRB":
                result["wind_variable"] = True
                result["wind_dir"] = None
            else:
                result["wind_dir"] = int(g1)
            speed = int(g2)
            gust = int(g3) if g3 is not None else None
            if unit == "KT":
                pass
            elif unit == "MPS":
                speed = int(speed * 1.943844 + 0.5)
                if gust is not None:
                    gust = int(gust * 1.943844 + 0.5)
            elif unit == "KMH":
                speed = int(speed / 1.852 + 0.5)
                if gust is not None:
                    gust = int(gust / 1.852 + 0.5)
            result["wind_speed_kt"] = speed
            result["wind_gust_kt"] = gust
            break
    var_re = re.compile(r'^(\d{3})V(\d{3})$')
    for tok in body:
        m = var_re.fullmatch(tok)
        if m:
            result["wind_var_from"] = int(m.group(1))
            result["wind_var_to"] = int(m.group(2))
            break
    if "CAVOK" in body:
        result["cavok"] = True
        result["visibility_m"] = 10000
    else:
        vis_found = False
        i = 0
        while i < len(body) and not vis_found:
            tok = body[i]
            if re.fullmatch(r'^\d{4}$', tok):
                result["visibility_m"] = int(tok)
                vis_found = True
            elif re.fullmatch(r'^(\d+)SM$', tok):
                sm = int(re.fullmatch(r'^(\d+)SM$', tok).group(1))
                result["visibility_m"] = int(sm * 1609.344 + 0.5)
                vis_found = True
            elif re.fullmatch(r'^P(\d+)SM$', tok):
                sm = int(re.fullmatch(r'^P(\d+)SM$', tok).group(1))
                result["visibility_m"] = int(sm * 1609.344 + 0.5)
                vis_found = True
            elif re.fullmatch(r'^M(\d)/(\d)SM$', tok):
                m = re.fullmatch(r'^M(\d)/(\d)SM$', tok)
                sm = int(m.group(1)) / int(m.group(2))
                result["visibility_m"] = int(sm * 1609.344 + 0.5)
                vis_found = True
            elif re.fullmatch(r'^(\d)/(\d)SM$', tok):
                m = re.fullmatch(r'^(\d)/(\d)SM$', tok)
                sm = int(m.group(1)) / int(m.group(2))
                result["visibility_m"] = int(sm * 1609.344 + 0.5)
                vis_found = True
            elif re.fullmatch(r'^\d$', tok) and i + 1 < len(body) and re.fullmatch(r'^(\d)/(\d)SM$', body[i + 1]):
                whole = int(tok)
                m = re.fullmatch(r'^(\d)/(\d)SM$', body[i + 1])
                sm = whole + int(m.group(1)) / int(m.group(2))
                result["visibility_m"] = int(sm * 1609.344 + 0.5)
                vis_found = True
                i += 1
            i += 1
    cloud_re = re.compile(r'^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?$')
    vv_re = re.compile(r'^VV(\d{3})$')
    vv_ft = None
    for tok in body:
        m = cloud_re.fullmatch(tok)
        if m:
            result["clouds"].append({
                "cover": m.group(1),
                "height_ft": int(m.group(2)) * 100,
                "type": m.group(3)
            })
        m = vv_re.fullmatch(tok)
        if m:
            vv_ft = int(m.group(1)) * 100
    heights = [c["height_ft"] for c in result["clouds"] if c["cover"] in ("BKN", "OVC")]
    if vv_ft is not None:
        heights.append(vv_ft)
    if heights:
        result["ceiling_ft"] = min(heights)
    temp_re = re.compile(r'^(M?\d{2})/(M?\d{2})?$')
    for tok in body:
        m = temp_re.fullmatch(tok)
        if m:
            t = m.group(1)
            d = m.group(2)
            if t.startswith("M"):
                result["temp_c"] = -int(t[1:])
            else:
                result["temp_c"] = int(t)
            if d is not None:
                if d.startswith("M"):
                    result["dew_c"] = -int(d[1:])
                else:
                    result["dew_c"] = int(d)
            break
    q_re = re.compile(r'^Q(\d{4})$')
    a_re = re.compile(r'^A(\d{4})$')
    for tok in body:
        m = q_re.fullmatch(tok)
        if m:
            result["qnh_hpa"] = int(m.group(1))
            result["altimeter_inhg"] = round(result["qnh_hpa"] / 33.8639, 2)
            break
        m = a_re.fullmatch(tok)
        if m:
            result["altimeter_inhg"] = int(m.group(1)) / 100
            result["qnh_hpa"] = int(result["altimeter_inhg"] * 33.8639 + 0.5)
            break
    wx_re = re.compile(r'^[-+]?(VC)?(MI|BC|PR|DR|BL|SH|TS|FZ)?(DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$')
    for tok in body:
        if wx_re.fullmatch(tok):
            result["weather"].append(tok)
    # rounded so that exactly 3 SM (4828 m) counts as 3.0 and not as 2.9999
    vis_sm = round(result["visibility_m"] / 1609.344, 2) if result["visibility_m"] is not None else None
    if vis_sm is not None:
        if vis_sm < 1:
            vis_cat = "LIFR"
        elif vis_sm < 3:
            vis_cat = "IFR"
        elif vis_sm <= 5:
            vis_cat = "MVFR"
        else:
            vis_cat = "VFR"
    else:
        vis_cat = "VFR"
    if result["ceiling_ft"] is not None:
        if result["ceiling_ft"] < 500:
            ceil_cat = "LIFR"
        elif result["ceiling_ft"] < 1000:
            ceil_cat = "IFR"
        elif result["ceiling_ft"] <= 3000:
            ceil_cat = "MVFR"
        else:
            ceil_cat = "VFR"
    else:
        ceil_cat = "VFR"
    if result["visibility_m"] is None and result["ceiling_ft"] is None and len(result["clouds"]) == 0:
        if result["cavok"]:
            result["category"] = "VFR"
        else:
            result["category"] = None
    else:
        order = ["VFR", "MVFR", "IFR", "LIFR"]
        idx_vis = order.index(vis_cat)
        idx_ceil = order.index(ceil_cat)
        result["category"] = order[max(idx_vis, idx_ceil)]
    return result