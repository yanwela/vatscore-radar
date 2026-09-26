_MERGE_GROUPS = {
    "K": "PA PC PF PG PH PJ PL PM PO PP PT PW",
    "CY": "CJ CK CL CN CP CS CW CZ",
    "SA": "BA",
    "SB": "SD SI SJ SS SW",
    "NC": "NI",
    "HD": "HF",
    "ED": "ET",
    "MT": "CT",
    "VA": "VE VI VO",
    "WA": "WI",
    "OI": "TE",
    "RJ": "RO",
    "WM": "WB",
    "UU": "UE UH UI UL UN UO UR US UW XE XH XI XK XL XM XN XO XR XS XU XW",
    "LE": "GC GE",
    "VV": "XV",
}
_MERGE = {p: hub for hub, members in _MERGE_GROUPS.items() for p in members.split()}


def region_prefix(code):
    code = str(code or "").strip().upper()
    if code.startswith("K"):
        return "K"
    if code.startswith("Y"):
        return "Y"
    if code.startswith("Z") and code[1:2].isalpha() and code[:2] not in ("ZK", "ZM"):
        return "Z"
    return _MERGE.get(code[:2], code[:2])


def canonical_region(prefix):
    # a saved 1-2 letter region (an old link or pin such as PH) as the hub it is merged into now (K)
    p = str(prefix or "").strip().upper()
    return p if len(p) < 2 else region_prefix(p + "AA")


def fir_base(fid):
    s = str(fid or "").strip().upper()
    base = s.split("-")[0]
    return base if len(base) == 4 and base.isalnum() else None


def sub_firs(ids, prefix):
    try:
        iterator = iter(ids)
    except TypeError:
        return []
    result = set()
    for i in iterator:
        base = fir_base(i)
        if base is None:
            continue
        if region_prefix(base) != prefix:
            continue
        if base.endswith("XX"):
            continue
        result.add(base)
    return sorted(result)


def fir_display_name(base, rows):
    if rows is None:
        return f"{base} FIR"
    base_norm = str(base or "").strip().upper()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        icao = str(row[0] or "").strip().upper()
        name = row[1]
        boundary_id = row[3] if len(row) > 3 else None
        if isinstance(name, str) and name.strip():
            if icao == base_norm or (isinstance(boundary_id, str) and boundary_id.strip().upper() == base_norm):
                return name.strip()
    return f"{base} FIR"


def count_controllers(callsigns, prefixes):
    # centre / FSS controllers whose callsign starts with one of the FIR's callsign prefixes (ANK_W_CTR for the "ANK_W" prefix)
    wanted = [str(p).strip().upper() + "_" for p in prefixes or [] if str(p).strip()]
    count = 0
    for cs in callsigns or []:
        if not isinstance(cs, str):
            continue
        cs_norm = cs.strip().upper()
        if cs_norm.endswith(("_CTR", "_FSS")) and any(cs_norm.startswith(w) for w in wanted):
            count += 1
    return count
