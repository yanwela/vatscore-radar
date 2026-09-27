from collections import Counter

def most_interesting_route(flights, region_of):
    if not flights:
        return None
    candidates = []
    for f in flights:
        dur = f.get("dur_min")
        dist = f.get("distance_nm")
        dep = f.get("dep")
        arr = f.get("arr")
        if not (isinstance(dur, (int, float)) and isinstance(dist, (int, float, type(None)))):
            continue
        if dur is None or dist is None:
            continue
        if dur > 30 and dist is not None and dist > 0 and dep and arr and dep != arr:
            candidates.append(f)
    if not candidates:
        return None
    route_counts = Counter(f.get("route") for f in flights if f.get("route") is not None)
    ac_counts = Counter(f.get("ac") for f in flights if f.get("ac"))
    best = None
    best_score = None
    best_dist = None
    best_route = None
    for f in candidates:
        route = f.get("route")
        ac = f.get("ac", "")
        dist = f.get("distance_nm")
        rarity = 1.0 / route_counts.get(route, 1)
        try:
            region_dep = region_of(f.get("dep")) or ""
        except Exception:
            region_dep = ""
        try:
            region_arr = region_of(f.get("arr")) or ""
        except Exception:
            region_arr = ""
        cross_region = region_dep != region_arr and region_dep != "" and region_arr != ""
        rare_aircraft = ac != "" and ac_counts.get(ac, 0) == 1
        multiplier = 1.0
        if cross_region:
            multiplier *= 1.5
        if rare_aircraft:
            multiplier *= 1.3
        score = dist * rarity * multiplier
        if (best_score is None or score > best_score or
            (score == best_score and (dist > best_dist or
                                      (dist == best_dist and route < best_route)))):
            best = f
            best_score = score
            best_dist = dist
            best_route = route
            best_cross = cross_region
            best_rare_ac = rare_aircraft
    if best is None:
        return None
    route = best.get("route")
    ac = best.get("ac", "")
    dist = best.get("distance_nm")
    reasons = []
    rc = route_counts.get(route, 0)
    if rc == 1:
        reasons.append("only flown once")
    elif rc <= 2:
        reasons.append(f"rarely flown ({rc}x)")
    if dist >= 3000:
        reasons.append("long haul")
    if best_cross:
        reasons.append("crosses regions")
    if best_rare_ac:
        reasons.append("rare aircraft for this pilot")
    return {
        "route": route,
        "dep": best.get("dep"),
        "arr": best.get("arr"),
        "ac": ac,
        "dur_min": best.get("dur_min"),
        "distance_nm": dist,
        "score": best_score,
        "reasons": reasons
    }