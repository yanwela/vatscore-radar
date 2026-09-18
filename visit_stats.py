def activity_matrix(timestamps):
    matrix = [[0]*24 for _ in range(7)]
    for ts in timestamps:
        try:
            w = ts.weekday()
            h = ts.hour
        except Exception:
            continue
        if not isinstance(w, int) or not isinstance(h, int):
            continue
        matrix[w][h] += 1
    return matrix

def peak_slot(matrix):
    if not matrix:
        return None
    max_count = -1
    best_w = None
    best_h = None
    for w, row in enumerate(matrix):
        for h, cnt in enumerate(row):
            if cnt > max_count or (cnt == max_count and (best_w is None or w < best_w or (w == best_w and h < best_h))):
                max_count = cnt
                best_w = w
                best_h = h
    if max_count <= 0:
        return None
    return (best_w, best_h, max_count)

def visited_airports(flights, airports):
    dep_counts = {}
    arr_counts = {}
    for dep, arr in flights:
        dep_n = str(dep or "").strip().upper()
        arr_n = str(arr or "").strip().upper()
        if dep_n:
            ap = airports.get(dep_n)
            if ap is not None:
                lat = ap.get('lat')
                lon = ap.get('lon')
                if lat is not None and lon is not None:
                    dep_counts[dep_n] = dep_counts.get(dep_n, 0) + 1
        if arr_n:
            ap = airports.get(arr_n)
            if ap is not None:
                lat = ap.get('lat')
                lon = ap.get('lon')
                if lat is not None and lon is not None:
                    arr_counts[arr_n] = arr_counts.get(arr_n, 0) + 1
    icaos = set(dep_counts) | set(arr_counts)
    result = []
    for icao in icaos:
        dep = dep_counts.get(icao, 0)
        arr = arr_counts.get(icao, 0)
        visits = dep + arr
        if visits == 0:
            continue
        ap = airports[icao]
        entry = {
            'icao': icao,
            'name': ap.get('name', ''),
            'city': ap.get('city', ''),
            'country': ap.get('country', ''),
            'lat': ap.get('lat'),
            'lon': ap.get('lon'),
            'departures': dep,
            'arrivals': arr,
            'visits': visits
        }
        result.append(entry)
    result.sort(key=lambda x: (-x['visits'], x['icao']))
    return result

def summarize_visits(items):
    airports_cnt = len(items)
    countries = set()
    total = 0
    for it in items:
        c = it.get('country')
        if c:
            countries.add(c)
        total += it.get('visits', 0)
    return {
        'airports': airports_cnt,
        'countries': len(countries),
        'total_visits': total
    }