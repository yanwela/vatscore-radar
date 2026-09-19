import math
from shapely.geometry import Point
from shapely.prepared import prep

def count_pilots_smallest_area(pilots, areas, min_gs=50) -> dict:
    # Prepare valid areas with computed bounds and prepared geometry
    valid_areas = []
    for area in areas:
        if not isinstance(area, dict):
            continue
        area_id = area.get("id")
        geometry = area.get("geometry")
        if not isinstance(area_id, str) or not area_id:
            continue
        if geometry is None:
            continue
        # geometry must have bounds and area attributes; skip empty geometries
        if getattr(geometry, "is_empty", False):
            continue
        # bounds: use supplied if valid, else compute
        bounds = area.get("bounds")
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 4
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bounds)
        ):
            bounds = geometry.bounds  # (minx, miny, maxx, maxy)
        # prepared geometry: use supplied if valid, else compute
        prepared = area.get("prepared")
        if not hasattr(prepared, "intersects"):
            prepared = prep(geometry)
        valid_areas.append(
            {
                "id": area_id,
                "geometry": geometry,
                "bounds": bounds,
                "prepared": prepared,
                "area": geometry.area,
            }
        )

    # Initialize result dict with zero counts for all valid area ids
    result = {area["id"]: 0 for area in valid_areas}

    # Process each pilot
    for pilot in pilots:
        if not isinstance(pilot, dict):
            continue
        lat = pilot.get("latitude")
        lon = pilot.get("longitude")
        gs = pilot.get("groundspeed")
        # Validate numeric and finite
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        if not isinstance(gs, (int, float)):
            continue
        if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(gs)):
            continue
        # Validate ranges
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            continue
        if gs < min_gs:
            continue

        point = Point(lon, lat)

        # Find containing areas
        candidates = []
        for area in valid_areas:
            minx, miny, maxx, maxy = area["bounds"]
            if not (minx <= point.x <= maxx and miny <= point.y <= maxy):
                continue
            if area["prepared"].intersects(point):
                candidates.append(area)

        if not candidates:
            continue

        # Select area with smallest geometry area, tie‑break by smaller id
        selected = candidates[0]
        for cand in candidates[1:]:
            if cand["area"] < selected["area"]:
                selected = cand
            elif cand["area"] == selected["area"] and cand["id"] < selected["id"]:
                selected = cand

        result[selected["id"]] += 1

    return result