import math
from shapely.geometry import Point
from shapely.prepared import prep

def great_circle_points(a, b, n) -> list[tuple]:
    # a, b: (lat, lon) in degrees
    lat1, lon1 = a
    lat2, lon2 = b
    # Ensure at least one segment
    if n < 1:
        n = 1
    # Convert to radians
    lat1_r = math.radians(lat1)
    lon1_r = math.radians(lon1)
    lat2_r = math.radians(lat2)
    lon2_r = math.radians(lon2)
    # Unit vectors
    v0 = (
        math.cos(lat1_r) * math.cos(lon1_r),
        math.cos(lat1_r) * math.sin(lon1_r),
        math.sin(lat1_r),
    )
    v1 = (
        math.cos(lat2_r) * math.cos(lon2_r),
        math.cos(lat2_r) * math.sin(lon2_r),
        math.sin(lat2_r),
    )
    # Angular distance
    dot = v0[0] * v1[0] + v0[1] * v1[1] + v0[2] * v1[2]
    # Clamp dot to [-1, 1] to avoid domain errors
    dot = max(-1.0, min(1.0, dot))
    omega = math.acos(dot)
    sin_omega = math.sin(omega)
    # Identical or antipodal case
    if sin_omega < 1e-9:
        return [(float(lat1), float(lon1)), (float(lat2), float(lon2))]
    points = []
    for i in range(n + 1):
        t = i / n
        factor0 = math.sin((1 - t) * omega) / sin_omega
        factor1 = math.sin(t * omega) / sin_omega
        x = factor0 * v0[0] + factor1 * v1[0]
        y = factor0 * v0[1] + factor1 * v1[1]
        z = factor0 * v0[2] + factor1 * v1[2]
        lat_r = math.atan2(z, math.hypot(x, y))
        lon_r = math.atan2(y, x)
        lat = math.degrees(lat_r)
        lon = math.degrees(lon_r)
        # Normalize longitude to [-180, 180]
        lon = ((lon + 180) % 360) - 180
        points.append((lat, lon))
    return points

def fir_crossings(points, firs, max_results=15) -> list[dict]:
    # Prepare FIR data without mutating input
    fir_data = []
    for fir in firs:
        fid = fir.get("id")
        geom = fir.get("geometry")
        if not fid or geom is None or getattr(geom, "is_empty", False):
            continue
        bounds = fir.get("bounds")
        if bounds is None:
            bounds = geom.bounds  # (minx, miny, maxx, maxy)
        prepared = fir.get("prepared")
        if prepared is None:
            prepared = prep(geom)
        fir_data.append({
            "id": fid,
            "bounds": bounds,
            "prepared": prepared,
            "matched": False,
        })
    results = []
    for idx, (lat, lon) in enumerate(points):
        # Validate point
        if not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        pt = Point(lon, lat)
        for fir in fir_data:
            if fir["matched"]:
                continue
            minx, miny, maxx, maxy = fir["bounds"]
            if not (minx <= lon <= maxx and miny <= lat <= maxy):
                continue
            if fir["prepared"].intersects(pt):
                results.append({
                    "id": fir["id"],
                    "lat": lat,
                    "lon": lon,
                    "index": idx,
                })
                fir["matched"] = True
        if len(results) >= max_results:
            break
    # Sort and truncate
    results.sort(key=lambda r: (r["index"], r["id"]))
    return results[:max_results]