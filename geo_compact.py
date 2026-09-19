import math
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection

def compact_rings(geometry, tolerance=0.03, decimals=3, max_points=400) -> list:
    if geometry is None or getattr(geometry, "is_empty", False):
        return []

    def collect_polygons(g):
        polys = []
        if isinstance(g, Polygon):
            polys.append(g)
        elif isinstance(g, MultiPolygon):
            for p in g.geoms:
                polys.append(p)
        elif isinstance(g, GeometryCollection):
            for sub in g.geoms:
                polys.extend(collect_polygons(sub))
        return polys

    def process(tol):
        rings = []
        for poly in collect_polygons(geometry):
            area = poly.area
            simp = poly.simplify(tol, preserve_topology=True)
            coords = list(simp.exterior.coords)
            rounded = []
            prev = None
            for x, y in coords:
                lon = round(x, decimals)
                lat = round(y, decimals)
                pt = (lat, lon)
                if pt != prev:
                    rounded.append([lat, lon])
                    prev = pt
            if len(rounded) >= 4:
                rings.append((rounded, area))
        rings.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in rings]

    current_tol = tolerance
    for i in range(7):  # original + up to 6 doublings
        rings = process(current_tol)
        total_pts = sum(len(r) for r in rings)
        if total_pts <= max_points:
            return rings
        if i == 6:
            break
        current_tol *= 2

    # Exceeded max_points after all doublings: keep largest rings respecting limit
    selected = []
    running = 0
    for ring in rings:
        if not selected:
            selected.append(ring)
            running += len(ring)
            continue
        if running + len(ring) <= max_points:
            selected.append(ring)
            running += len(ring)
    return selected