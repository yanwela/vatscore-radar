WIDE_BODY = frozenset({
    "A306", "A30B", "A310", "A332", "A333", "A338", "A339",
    "A342", "A343", "A345", "A346", "A359", "A35K", "A388",
    "A124", "A225", "B742", "B743", "B744", "B748", "B74S",
    "B762", "B763", "B764", "B772", "B773", "B77L", "B77W",
    "B788", "B789", "B78X", "MD11", "DC10", "IL86", "IL96",
    "L101"
})


def fleet_summary(types, top_n=8):
    # Validate top_n
    if not isinstance(top_n, int) or top_n < 1:
        top_n = 1

    # Clean and filter input types
    valid = []
    for t in types:
        if not isinstance(t, str):
            continue
        t_clean = t.strip().upper()
        if not t_clean:
            continue
        if t_clean in {"N/A", "NA", "UNKNOWN", "ZZZZ"}:
            continue
        valid.append(t_clean)

    total = len(valid)
    if total == 0:
        return {"total": 0, "rows": [], "other": 0, "wide_pct": 0.0, "other_pct": 0.0}

    # Count occurrences
    counts = {}
    wide = 0
    for typ in valid:
        counts[typ] = counts.get(typ, 0) + 1
        if typ in WIDE_BODY:
            wide += 1

    # Sort types by count desc then type asc
    sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    # Build rows up to top_n
    rows = []
    covered = 0
    for typ, cnt in sorted_items[:top_n]:
        share = round(100 * cnt / total, 1)
        rows.append({"type": typ, "count": cnt, "share": share})
        covered += cnt

    other = total - covered
    wide_pct = round(100 * wide / total, 1)
    other_pct = round(100 - wide_pct, 1)

    return {
        "total": total,
        "rows": rows,
        "other": other,
        "wide_pct": wide_pct,
        "other_pct": other_pct
    }


def hub_rows(departures, arrivals, mode, top_n=8):
    # Helper to clean airport codes
    def clean_codes(codes):
        cleaned = []
        for c in codes:
            if not isinstance(c, str):
                continue
            c_clean = c.strip().upper()
            if len(c_clean) != 4:
                continue
            if not c_clean.isalnum():
                continue
            cleaned.append(c_clean)
        return cleaned

    dep_clean = clean_codes(departures)
    arr_clean = clean_codes(arrivals)

    # Count occurrences
    dep_counts = {}
    for icao in dep_clean:
        dep_counts[icao] = dep_counts.get(icao, 0) + 1

    arr_counts = {}
    for icao in arr_clean:
        arr_counts[icao] = arr_counts.get(icao, 0) + 1

    # Determine ranking source
    ranking_source = arr_counts if mode == "arrivals" else dep_counts

    # Sort ranking source
    sorted_rank = sorted(ranking_source.items(), key=lambda x: (-x[1], x[0]))

    # Build result rows up to top_n
    result = []
    for icao, cnt in sorted_rank[:top_n]:
        result.append({
            "icao": icao,
            "count": cnt,
            "departures": dep_counts.get(icao, 0),
            "arrivals": arr_counts.get(icao, 0)
        })

    return result