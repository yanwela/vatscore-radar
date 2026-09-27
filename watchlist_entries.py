import re

_ID_RE = re.compile(r"[^A-Za-z0-9_]")
_NOTE_RE = re.compile(r"[\x00-\x1f]")


def sanitize_entries(rows, id_max=20, note_max=30):
    result = []
    seen = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id")
        if not isinstance(raw_id, str):
            continue
        raw_id_stripped = raw_id.strip()
        if not raw_id_stripped:
            continue
        cleaned_id = _ID_RE.sub("", raw_id_stripped)[:id_max]
        if not cleaned_id:
            continue
        raw_note = row.get("note")
        if not isinstance(raw_note, str):
            note = ""
        else:
            note = _NOTE_RE.sub("", raw_note).strip()[:note_max]
        key = cleaned_id.upper()
        if key in seen:
            seen[key]["note"] = note
        else:
            entry = {"id": cleaned_id, "note": note}
            seen[key] = entry
            result.append(entry)
    return result


def match_map(entries):
    cid = {}
    callsign = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if not isinstance(raw_id, str):
            continue
        stripped_id = raw_id.strip()
        if not stripped_id:
            continue
        note = entry.get("note") if isinstance(entry.get("note"), str) else ""
        if stripped_id.isascii() and stripped_id.isdigit():
            cid[stripped_id] = note
        else:
            callsign[stripped_id.upper()] = note
    return {"cid": cid, "callsign": callsign}