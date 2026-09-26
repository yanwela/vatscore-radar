def build_timeline(records, now_s, span_s=7200, bucket_s=300):
    import math

    # Validate and sanitize bucket and span sizes
    try:
        bucket_s = float(bucket_s)
        span_s = float(span_s)
    except Exception:
        bucket_s = 300.0
        span_s = 7200.0
    if bucket_s <= 0 or span_s <= 0:
        bucket_s = 300.0
        span_s = 7200.0

    # Validate now timestamp
    try:
        now_s = float(now_s)
    except Exception:
        now_s = 0.0

    # Determine number of buckets
    n = int(span_s // bucket_s)
    if n < 1:
        n = 1

    # Compute bucket start times
    start0 = now_s - n * bucket_s
    starts = [start0 + i * bucket_s for i in range(n)]

    # Initialize counts per severity
    counts = {"high": [0] * n, "medium": [0] * n, "low": [0] * n}

    # If records is not a list or empty, return empty timeline
    if not isinstance(records, list) or not records:
        return {"starts": starts, "counts": counts}

    for rec in records:
        if not isinstance(rec, dict):
            continue
        first = rec.get("first")
        last = rec.get("last")
        severity = rec.get("severity")

        # Validate numeric timestamps
        if not isinstance(first, (int, float)) or not isinstance(last, (int, float)):
            continue
        if not (math.isfinite(first) and math.isfinite(last)):
            continue

        # Validate severity
        if severity not in ("high", "medium", "low"):
            continue

        # Ensure first <= last
        if last < first:
            first, last = last, first

        # Count overlap with each bucket
        for i in range(n):
            bucket_start = starts[i]
            bucket_end = bucket_start + bucket_s
            if first <= bucket_end and last >= bucket_start:
                counts[severity][i] += 1

    return {"starts": starts, "counts": counts}