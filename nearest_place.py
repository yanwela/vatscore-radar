import math

def build_index(rows):
    try:
        iterator = iter(rows)
    except TypeError:
        return {}
    index = {}
    for row in iterator:
        try:
            lat_raw, lon_raw, label_raw = row
        except Exception:
            continue
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except Exception:
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        label = str(label_raw).strip()
        if not label:
            continue
        key = (math.floor(lat), math.floor(lon))
        index.setdefault(key, []).append((lat, lon, label))
    return index

def nearest_label(index, lat, lon, max_nm):
    if not isinstance(index, dict):
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        max_nm_f = float(max_nm)
    except Exception:
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f) and math.isfinite(max_nm_f)):
        return None
    lon_f = ((lon_f + 180) % 360) - 180
    lat_span = max(1, math.ceil(max_nm_f / 60))
    cos_lat = math.cos(math.radians(lat_f))
    denom = 60 * max(cos_lat, 1e-12)
    lon_span = min(180, max(1, math.ceil(max_nm_f / denom)))
    best_dist = None
    best_label = None
    base_lat_cell = math.floor(lat_f)
    base_lon_cell = math.floor(lon_f)
    for dy in range(-lat_span, lat_span + 1):
        cell_lat = base_lat_cell + dy
        if cell_lat < -90 or cell_lat > 89:
            continue
        for dx in range(-lon_span, lon_span + 1):
            cell_lon = ((base_lon_cell + dx + 180) % 360) - 180
            candidates = index.get((cell_lat, cell_lon))
            if not candidates:
                continue
            for cand_lat, cand_lon, cand_label in candidates:
                dlat = math.radians(cand_lat - lat_f)
                dlon = math.radians(cand_lon - lon_f)
                rad_lat1 = math.radians(lat_f)
                rad_lat2 = math.radians(cand_lat)
                a = math.sin(dlat / 2) ** 2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(dlon / 2) ** 2
                c = 2 * math.asin(min(1.0, math.sqrt(a)))
                dist = 3440.065 * c
                if dist <= max_nm_f:
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best_label = cand_label
    if best_label is None:
        return None
    return (best_label, best_dist)