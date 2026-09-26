FEATURED = ("LT","EG","ED","LF","K","LE","LI","LO","OM")

from fir_regions import region_prefix

def traffic_by_region(pilots):
    counts = {}
    for pilot in pilots:
        if not isinstance(pilot, dict):
            continue
        fp = pilot.get("flight_plan")
        if not isinstance(fp, dict):
            continue
        prefixes = set()
        for key in ("departure", "arrival"):
            value = fp.get(key)
            if isinstance(value, str) and len(value.strip()) == 4:
                p = region_prefix(value)
                if len(p) >= 1:
                    prefixes.add(p)
        for p in prefixes:
            counts[p] = counts.get(p, 0) + 1
    return counts

def parse_country_names(dat_text):
    if not isinstance(dat_text, str):
        return {"K": "United States"}
    names = {}
    inside = False
    for line in dat_text.splitlines():
        s = line.strip()
        if s.startswith("["):
            inside = (s == "[Countries]")
            continue
        if not inside or not s or s.startswith(";"):
            continue
        parts = [x.strip() for x in s.split("|")]
        if len(parts) < 2 or not parts[0] or len(parts[1]) != 2:
            continue
        prefix = parts[1].upper()
        name = parts[0]
        if prefix not in names:
            names[prefix] = [name]
        elif name not in names[prefix]:
            names[prefix].append(name)
    result = {p: " / ".join(v[:2]) for p, v in names.items()}
    result["K"] = "United States"
    return result

def order_regions(counts, known_prefixes, featured, pinned, selected):
    result = []
    def add(p):
        if p and p not in result:
            result.append(p)
    for p in pinned:
        add(p)
    for p in featured:
        add(p)
    rest = [p for p, n in counts.items() if n > 0 and p in known_prefixes and p not in result]
    rest.sort(key=lambda p: (-counts[p], p))
    for p in rest:
        add(p)
    if selected:
        add(selected)
    return result