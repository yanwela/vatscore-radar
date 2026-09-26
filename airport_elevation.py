import math

def build_index(airports):
    try:
        iterator = iter(airports)
    except TypeError:
        return {}
    index = {}
    for item in iterator:
        try:
            lat, lon, elev = item
        except Exception:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            elev_f = float(elev)
        except Exception:
            continue
        if not (math.isfinite(lat_f) and math.isfinite(lon_f) and math.isfinite(elev_f)):
            continue
        if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lon_f <= 180.0):
            continue
        key = (math.floor(lat_f), math.floor(lon_f))
        index.setdefault(key, []).append((lat_f, lon_f, elev_f))
    return index

def nearest_elevation(index, lat, lon, max_nm=30.0):
    if not isinstance(index, dict):
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return None
    if not (-90.0 <= lat_f <= 90.0):
        return None
    lon_f = (lon_f + 180.0) % 360.0 - 180.0
    lat_cell = math.floor(lat_f)
    lon_cell = math.floor(lon_f)
    lat_span = max(1, math.ceil(max_nm / 60.0))
    cos_lat = math.cos(math.radians(lat_f))
    lon_factor = max(cos_lat, 1e-12)
    lon_span = min(180, max(1, math.ceil(max_nm / (60.0 * lon_factor))))
    visited = set()
    best = None
    best_dist = None
    radius = 3440.065
    lat_rad = math.radians(lat_f)
    lon_rad = math.radians(lon_f)
    for dy in range(-lat_span, lat_span + 1):
        cell_lat = lat_cell + dy
        if not (-90 <= cell_lat <= 89):
            continue
        for dx in range(-lon_span, lon_span + 1):
            cell_lon = ((lon_cell + dx + 180) % 360) - 180
            cell_key = (cell_lat, cell_lon)
            if cell_key in visited:
                continue
            visited.add(cell_key)
            airports = index.get(cell_key)
            if not airports:
                continue
            for a_lat, a_lon, a_elev in airports:
                dlat = math.radians(a_lat) - lat_rad
                dlon = ((a_lon - lon_f + 180.0) % 360.0) - 180.0
                dlon = math.radians(dlon)
                sin_dlat = math.sin(dlat / 2.0)
                sin_dlon = math.sin(dlon / 2.0)
                aa = sin_dlat * sin_dlat + math.cos(lat_rad) * math.cos(math.radians(a_lat)) * sin_dlon * sin_dlon
                c = 2.0 * math.asin(min(1.0, math.sqrt(aa)))
                dist = radius * c
                if dist <= max_nm:
                    if best_dist is None or dist < best_dist:
                        best = (a_elev, dist)
                        best_dist = dist
    return best