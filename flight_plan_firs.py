import re

def eet_fir_codes(remarks) -> list[str]:
    if not isinstance(remarks, str):
        return []
    text = remarks.upper()
    idx = text.find("EET/")
    if idx == -1:
        return []
    tokens = text[idx + 4 :].split()
    pattern = re.compile(r'^[A-Z]{4}\d{4}$')
    codes: list[str] = []
    for token in tokens:
        if pattern.fullmatch(token):
            code = token[:4]
            if code not in codes:
                codes.append(code)
        else:
            break
    return codes

def boundaries_for_codes(codes, boundary_ids, rows) -> list[str]:
    boundary_set = set(boundary_ids)
    result: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if not isinstance(code, str):
            continue
        candidates: set[str] = set()
        # rows matching the code
        for row in rows:
            if not isinstance(row, tuple) or len(row) != 2:
                continue
            icao, boundary = row
            if icao == code:
                cand = boundary if boundary else icao
                candidates.add(cand)
        # the code itself
        candidates.add(code)
        # ids starting with code-
        prefix = f"{code}-"
        for bid in boundary_set:
            if bid.startswith(prefix):
                candidates.add(bid)
        # keep only available ids
        valid = [c for c in candidates if c in boundary_set]
        # order: exact code first, then alphabetically
        ordered: list[str] = []
        if code in valid:
            ordered.append(code)
        ordered.extend(sorted(c for c in valid if c != code))
        for cid in ordered:
            if cid not in seen:
                seen.add(cid)
                result.append(cid)
    return result