import math
import time
import concurrent.futures

MAX_STANDS = 800
MAX_REF = 12
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

def _clean_ref(value):
    s = str(value).strip()
    return s[:MAX_REF]

def _point_inside(lat, lon, lat0, lon0, radius_m):
    try:
        lat = float(lat)
        lon = float(lon)
        lat0 = float(lat0)
        lon0 = float(lon0)
        radius_m = float(radius_m)
    except (TypeError, ValueError):
        return False
    x = (lon - lon0) * 111320.0 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 110540.0
    return math.hypot(x, y) <= radius_m

def _distance_point_to_segment(px, py, x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)

def _simplify(pts, tol_m):
    if len(pts) < 3:
        return pts[:]
    lat0 = pts[0][0]
    def to_xy(lat, lon):
        x = (lon - pts[0][1]) * 111320.0 * math.cos(math.radians(lat0))
        y = (lat - lat0) * 110540.0
        return x, y
    stack = [(0, len(pts) - 1)]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    while stack:
        start, end = stack.pop()
        x1, y1 = to_xy(*pts[start])
        x2, y2 = to_xy(*pts[end])
        max_dist = -1.0
        index = -1
        for i in range(start + 1, end):
            px, py = to_xy(*pts[i])
            d = _distance_point_to_segment(px, py, x1, y1, x2, y2)
            if d > max_dist:
                max_dist = d
                index = i
        if max_dist > tol_m:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    result = [pts[i] for i, k in enumerate(keep) if k]
    return result

def build_query(lat, lon, radius_m=3500):
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        radius_i = int(radius_m)
    except (TypeError, ValueError):
        return ""
    q = (
        "[out:json][timeout:40];\n"
        f'way["aeroway"~"^(runway|taxiway|taxilane|apron|terminal)$"](around:{radius_i},{lat_f},{lon_f});\n'
        "out geom;\n"
        f'way["aeroway"="parking_position"](around:{radius_i},{lat_f},{lon_f});\n'
        "out center;\n"
        f'node["aeroway"~"^(gate|parking_position|holding_position)$"](around:{radius_i},{lat_f},{lon_f});\n'
        "out;"
    )
    return q

def parse_layout(data, lat, lon, radius_m=3500, tolerance_m=2.0):
    if not isinstance(data, dict):
        return None
    elements = data.get("elements")
    if not isinstance(elements, list):
        return None
    result = {
        "runways": [],
        "taxiways": [],
        "aprons": [],
        "terminals": [],
        "stands": [],
        "holds": [],
    }
    stands_set = set()
    for e in elements:
        if not isinstance(e, dict):
            continue
        tags = e.get("tags")
        if not isinstance(tags, dict):
            tags = {}
        kind = tags.get("aeroway")
        ref = _clean_ref(tags.get("ref") or tags.get("name") or "")
        typ = e.get("type")
        if typ == "way" and kind in ("runway", "taxiway", "taxilane"):
            geom = e.get("geometry")
            if not isinstance(geom, list):
                continue
            pts = []
            for pt in geom:
                try:
                    lat_pt = float(pt["lat"])
                    lon_pt = float(pt["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                pts.append([round(lat_pt, 5), round(lon_pt, 5)])
            if len(pts) < 2:
                continue
            if not any(_point_inside(p[0], p[1], lat, lon, radius_m) for p in pts):
                continue
            pts_s = _simplify(pts, tolerance_m)
            entry = {"ref": ref, "pts": pts_s}
            if kind == "runway":
                result["runways"].append(entry)
            else:
                result["taxiways"].append(entry)
        elif typ == "way" and kind in ("apron", "terminal"):
            geom = e.get("geometry")
            if not isinstance(geom, list):
                continue
            pts = []
            for pt in geom:
                try:
                    lat_pt = float(pt["lat"])
                    lon_pt = float(pt["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                pts.append([round(lat_pt, 5), round(lon_pt, 5)])
            if len(pts) < 3:
                continue
            pts_s = _simplify(pts, 3.0)
            if len(pts_s) < 3:
                continue
            entry = {"pts": pts_s}
            if kind == "apron":
                result["aprons"].append(entry)
            else:
                result["terminals"].append(entry)
        elif typ == "way" and kind == "parking_position":
            geom = e.get("geometry")
            center = e.get("center")
            if isinstance(center, dict):
                geom = [center]
            if not isinstance(geom, list) or not geom:
                continue
            sum_lat = sum_lon = cnt = 0
            for pt in geom:
                try:
                    lat_pt = float(pt["lat"])
                    lon_pt = float(pt["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                sum_lat += lat_pt
                sum_lon += lon_pt
                cnt += 1
            if cnt == 0:
                continue
            avg_lat = round(sum_lat / cnt, 5)
            avg_lon = round(sum_lon / cnt, 5)
            if not _point_inside(avg_lat, avg_lon, lat, lon, radius_m):
                continue
            key = (ref, avg_lat, avg_lon)
            if key in stands_set:
                continue
            if len(result["stands"]) >= MAX_STANDS:
                continue
            stands_set.add(key)
            result["stands"].append({"ref": ref, "lat": avg_lat, "lon": avg_lon})
        elif typ == "node" and kind in ("gate", "parking_position"):
            try:
                lat_n = float(e["lat"])
                lon_n = float(e["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not _point_inside(lat_n, lon_n, lat, lon, radius_m):
                continue
            lat_n = round(lat_n, 5)
            lon_n = round(lon_n, 5)
            key = (ref, lat_n, lon_n)
            if key in stands_set:
                continue
            if len(result["stands"]) >= MAX_STANDS:
                continue
            stands_set.add(key)
            result["stands"].append({"ref": ref, "lat": lat_n, "lon": lon_n})
        elif typ == "node" and kind == "holding_position":
            try:
                lat_h = float(e["lat"])
                lon_h = float(e["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not _point_inside(lat_h, lon_h, lat, lon, radius_m):
                continue
            result["holds"].append({"ref": ref, "lat": round(lat_h, 5), "lon": round(lon_h, 5)})
    return result

def fetch_layout(lat, lon, session, radius_m=3500, timeout=20, mirrors=MIRRORS, rounds=2, retry_wait_s=2.0):
    query = build_query(lat, lon, radius_m)
    if not query:
        return None
    def worker(url):
        try:
            resp = session.post(url, data={"data": query}, timeout=timeout, headers={"User-Agent": "VatScoreRadar"})
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            body = resp.json()
        except Exception:
            return None
        if not isinstance(body, dict):
            return None
        if not body.get("elements") and body.get("remark"):
            return None
        return parse_layout(body, lat, lon, radius_m)
    if not mirrors:
        return None
    for attempt in range(rounds):
        if attempt:
            time.sleep(retry_wait_s)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(mirrors))
        pending = {executor.submit(worker, m) for m in mirrors}
        try:
            while pending:
                done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                for f in done:
                    try:
                        result = f.result()
                    except Exception:
                        result = None
                    if result is not None:
                        return result
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    return None
