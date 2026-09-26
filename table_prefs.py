import json, re

DEFAULT_FLEET = "All Flights"
DEFAULT_RULES = "All Rules"

_airline_regex = re.compile(r"^[A-Z0-9]{2,4}$")
_callsign_regex = re.compile(r"^([A-Z]{3})[0-9]")

def sanitize_prefs(raw, all_columns, fleet_options, rules_options):
    defaults = {
        "columns": list(all_columns),
        "fleet": DEFAULT_FLEET,
        "rules": DEFAULT_RULES,
        "airlines": []
    }
    if not isinstance(raw, str) or len(raw) > 800:
        return defaults
    try:
        parsed = json.loads(raw)
    except Exception:
        return defaults
    if not isinstance(parsed, dict):
        return defaults
    result = {}
    cols = parsed.get("columns")
    if isinstance(cols, list):
        filtered = [c for c in all_columns if c in cols]
        result["columns"] = filtered if filtered else list(all_columns)
    else:
        result["columns"] = list(all_columns)
    fleet = parsed.get("fleet")
    result["fleet"] = fleet if fleet in fleet_options else DEFAULT_FLEET
    rules = parsed.get("rules")
    result["rules"] = rules if rules in rules_options else DEFAULT_RULES
    airlines = parsed.get("airlines")
    if isinstance(airlines, list):
        seen = set()
        out = []
        for item in airlines:
            if not isinstance(item, str):
                continue
            val = item.strip().upper()
            if val in seen:
                continue
            if _airline_regex.fullmatch(val):
                seen.add(val)
                out.append(val)
                if len(out) >= 12:
                    break
        result["airlines"] = out
    else:
        result["airlines"] = []
    return result

def is_default(prefs, all_columns):
    return (
        prefs.get("columns") == list(all_columns)
        and prefs.get("fleet") == DEFAULT_FLEET
        and prefs.get("rules") == DEFAULT_RULES
        and prefs.get("airlines") == []
    )

def prefs_json(prefs):
    return json.dumps(
        {
            "columns": prefs.get("columns"),
            "fleet": prefs.get("fleet"),
            "rules": prefs.get("rules"),
            "airlines": prefs.get("airlines")
        },
        separators=(",", ":"),
        ensure_ascii=False
    )

def airline_counts(callsigns):
    counts = {}
    for cs in callsigns:
        if not isinstance(cs, str):
            continue
        m = _callsign_regex.match(cs.strip().upper())
        if m:
            code = m.group(1)
            counts[code] = counts.get(code, 0) + 1
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))