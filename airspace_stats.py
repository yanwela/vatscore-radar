import math
from shapely.geometry import Point
from shapely.prepared import prep


def count_pilots_in_areas(pilots, areas, min_gs=50) -> dict:
    result = {}
    processed_areas = []
    for area in areas:
        if not isinstance(area, dict):
            continue
        area_id = area.get("id")
        geometry = area.get("geometry")
        if not isinstance(area_id, str) or geometry is None:
            continue
        if getattr(geometry, "is_empty", False):
            continue
        bounds = area.get("bounds")
        if not (isinstance(bounds, (list, tuple)) and len(bounds) == 4):
            bounds = geometry.bounds
        prepared = area.get("prepared")
        if not (hasattr(prepared, "intersects")):
            try:
                prepared = prep(geometry)
            except Exception:
                continue
        result[area_id] = 0
        processed_areas.append((area_id, bounds, prepared))

    for pilot in pilots:
        if not isinstance(pilot, dict):
            continue
        lat = pilot.get("latitude")
        lon = pilot.get("longitude")
        gs = pilot.get("groundspeed")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        if not isinstance(gs, (int, float)):
            continue
        if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(gs)):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        if gs < min_gs:
            continue
        pt = Point(lon, lat)
        for area_id, bounds, prepared in processed_areas:
            minx, miny, maxx, maxy = bounds
            if not (minx <= lon <= maxx and miny <= lat <= maxy):
                continue
            try:
                if prepared.intersects(pt):
                    result[area_id] += 1
            except Exception:
                continue
    return result


def staffed_area_ids(controllers, key_to_ids, facilities=(1, 6)) -> dict:
    result = {}
    for ctrl in controllers:
        if not isinstance(ctrl, dict):
            continue
        callsign = ctrl.get("callsign")
        facility = ctrl.get("facility")
        if not isinstance(callsign, str) or type(facility) is not int:
            continue
        if facility not in facilities:
            continue
        parts = callsign.upper().split("_")
        if len(parts) < 2:
            continue
        for k in range(len(parts) - 1, 0, -1):
            prefix = "_".join(parts[:k])
            ids = key_to_ids.get(prefix)
            if ids:
                for area_id in ids:
                    result.setdefault(area_id, []).append(callsign)
                break
    return result


def airport_atc_prefixes(controllers, atis) -> set:
    prefixes = set()
    for ctrl in controllers:
        if not isinstance(ctrl, dict):
            continue
        callsign = ctrl.get("callsign")
        facility = ctrl.get("facility")
        if not isinstance(callsign, str) or type(facility) is not int:
            continue
        if facility not in (2, 3, 4, 5):
            continue
        segment = callsign.split("_", 1)[0].upper()
        prefixes.add(segment)
    for entry in atis:
        if not isinstance(entry, dict):
            continue
        cs = entry.get("callsign")
        if isinstance(cs, str):
            segment = cs.split("_", 1)[0].upper()
            prefixes.add(segment)
    return prefixes


def airport_has_atc(icao, prefixes) -> bool:
    if not isinstance(icao, str):
        return False
    icao_up = icao.upper()
    if icao_up in prefixes:
        return True
    if len(icao_up) == 4 and icao_up[0] in ("K", "P"):
        trimmed = icao_up[1:]
        if trimmed in prefixes:
            return True
    return False