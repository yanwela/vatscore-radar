def build_index(rows):
    # the same type designator often has one row per manufacturer/model variant (a big airliner's own sub-models, or a foreign
    # licensed build); the fields that matter for classification (description/engine/wtc) agree across those rows almost always,
    # but the manufacturer/model shown to a person should be the one behind most of a type's real-world aircraft, not whichever
    # row the source file happens to list first (that could be a single obscure licensee)
    grouped = {}
    for row in rows:
        td = str(row.get("type_designator") or "").strip().upper()
        if not td:
            continue
        manufacturer = str(row.get("manufacturer") or "").strip()
        model = str(row.get("model") or "").strip()
        description = str(row.get("description") or "").strip()
        engine_type = str(row.get("engine_type") or "").strip()
        wtc = str(row.get("wtc") or "").strip().upper()
        ec_raw = row.get("engine_count")
        try:
            engine_count = int(str(ec_raw).strip())
        except Exception:
            engine_count = 0
        grouped.setdefault(td, []).append({
            "manufacturer": manufacturer,
            "model": model,
            "description": description,
            "engine_type": engine_type,
            "engine_count": engine_count,
            "wtc": wtc,
        })
    index = {}
    for td, variants in grouped.items():
        counts = {}
        for v in variants:
            counts[v["manufacturer"]] = counts.get(v["manufacturer"], 0) + 1
        best_manufacturer = max(counts, key=lambda m: counts[m])
        # among that manufacturer's own rows, the base variant's model name is consistently the shortest one (a VIP/BBJ/ACJ
        # conversion adds a suffix, e.g. "A-320" vs "A-320 Prestige", "737-800" vs "737-800 BBJ2")
        same_maker = [v for v in variants if v["manufacturer"] == best_manufacturer]
        record = dict(min(same_maker, key=lambda v: len(v["model"])))
        index[td] = record
    return index

def category_of(record):
    if not isinstance(record, dict):
        return None
    desc = record.get("description")
    eng_type = record.get("engine_type")
    eng_cnt = record.get("engine_count")
    wtc = record.get("wtc")
    if desc in ("Helicopter", "Gyrocopter", "Tiltrotor"):
        return "Helicopter"
    if desc in ("LandPlane", "SeaPlane", "Amphibian") and eng_type == "Piston" and isinstance(eng_cnt, int) and eng_cnt <= 2:
        return "General Aviation"
    if desc in ("LandPlane", "SeaPlane", "Amphibian") and eng_type == "Turboprop/Turboshaft" and eng_cnt == 1 and wtc == "L":
        return "General Aviation"
    return None