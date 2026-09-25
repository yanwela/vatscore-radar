import re, hashlib
from datetime import datetime, timezone, timedelta

BANNER_PREFIX = "https://vatsim-my.nyc3.digitaloceanspaces.com/"

def _escape_ical(text):
    if not text:
        return ""
    text = str(text)
    text = text.replace("\\", r"\\")
    text = text.replace(";", r"\;")
    text = text.replace(",", r"\,")
    text = text.replace("\r\n", r"\n")
    text = text.replace("\n", r"\n")
    return text

def _fold_line(line):
    encoded = line.encode("utf-8")
    parts = []
    start = 0
    while start < len(encoded):
        end = start + (75 if not parts else 74)
        if end >= len(encoded):
            parts.append(encoded[start:].decode("utf-8"))
            break
        cut = end
        while cut > start and (encoded[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(encoded[start:cut].decode("utf-8"))
        start = cut
    if len(parts) == 1:
        return [parts[0]]
    folded = [parts[0]]
    for p in parts[1:]:
        folded.append(" " + p)
    return folded

def parse_events(raw):
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, dict):
        data = raw.get("data")
    else:
        return []
    if not isinstance(data, list):
        return []
    events = []
    for item in data:
        if not isinstance(item, dict):
            continue
        start_str = item.get("start_time")
        end_str = item.get("end_time")
        if not isinstance(start_str, str) or not isinstance(end_str, str):
            continue
        try:
            start_iso = start_str.replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(start_iso)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            end_iso = end_str.replace("Z", "+00:00")
            end_dt = datetime.fromisoformat(end_iso)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if end_dt <= start_dt:
            continue
        name = str(item.get("name") or "")
        name = re.sub(r"[\x00-\x1f\x7f]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()[:120]
        if not name:
            name = "Untitled event"
        typ = str(item.get("type") or "")
        typ = re.sub(r"[\x00-\x1f\x7f]", " ", typ)
        typ = re.sub(r"\s+", " ", typ).strip()[:40]
        if not typ:
            typ = "Event"
        link = str(item.get("link", ""))
        if not link.startswith("https://my.vatsim.net/"):
            link = ""
        banner = str(item.get("banner") or "")
        if not banner.startswith(BANNER_PREFIX) or not re.fullmatch(r"[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+", banner):
            banner = ""
        airports_raw = item.get("airports", [])
        airports = []
        if isinstance(airports_raw, list):
            for a in airports_raw:
                code = None
                if isinstance(a, dict):
                    code = a.get("icao")
                elif isinstance(a, str):
                    code = a
                if code is None:
                    continue
                code = str(code).strip().upper()
                if re.fullmatch(r"[A-Z0-9]{4}", code) and code not in airports:
                    airports.append(code)
                if len(airports) >= 30:
                    break
        organisers = item.get("organisers", [])
        region = ""
        division = ""
        if isinstance(organisers, list) and organisers and isinstance(organisers[0], dict):
            first = organisers[0]
            region = str(first.get("region", "")).strip()[:20]
            division = str(first.get("division", "")).strip()[:20]
        desc = str(item.get("description") or "")
        desc = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", desc)
        desc = re.sub(r"\[([^\]]*)\]\((?!https?://|mailto:)[^)]*\)", r"\1", desc, flags=re.IGNORECASE)
        def _bold_headings(m):
            return f"**{m.group(1)}**"
        desc = re.sub(r"^#{1,6}\s*(.+)$", _bold_headings, desc, flags=re.MULTILINE)
        desc = re.sub(r"\n{3,}", "\n\n", desc).strip()[:2000]
        short_raw = str(item.get("short_description") or "")
        short = ""
        for line in short_raw.splitlines():
            line = line.strip()
            if line:
                line = re.sub(r"^#+\s*", "", line)
                short = line[:200]
                break
        if not short:
            first_sentence = desc.split(".")[0].strip()
            short = first_sentence[:200]
        id_val = item.get("id")
        ev_id = id_val if isinstance(id_val, int) else None
        events.append({
            "id": ev_id,
            "name": name,
            "type": typ,
            "start": start_dt,
            "end": end_dt,
            "link": link,
            "banner": banner,
            "airports": airports,
            "region": region,
            "division": division,
            "description": desc,
            "short": short
        })
    events.sort(key=lambda e: e["start"])
    return events

def group_events(events, now, tz=None):
    if tz is None:
        tz = timezone.utc
    result = {"live": [], "today": [], "week": [], "later": []}
    for ev in events:
        if ev["end"] <= now:
            continue
        if ev["start"] <= now < ev["end"]:
            result["live"].append(ev)
        else:
            d_start = ev["start"].astimezone(tz).date()
            d_now = now.astimezone(tz).date()
            if d_start == d_now:
                result["today"].append(ev)
            else:
                diff = (d_start - d_now).days
                if 0 < diff <= 7:
                    result["week"].append(ev)
                else:
                    result["later"].append(ev)
    for key in result:
        result[key].sort(key=lambda e: e["start"])
    return result

def filter_events(events, query="", regions=None, include_exams=True):
    q = query.strip().lower()
    region_set = set(regions) if regions else None
    filtered = []
    for ev in events:
        if q:
            match = False
            if q in ev["name"].lower():
                match = True
            elif q in ev["short"].lower():
                match = True
            elif q in ev["region"].lower():
                match = True
            elif q in ev["division"].lower():
                match = True
            else:
                for ap in ev["airports"]:
                    if q in ap.lower():
                        match = True
                        break
            if not match:
                continue
        if region_set is not None and ev["region"] not in region_set:
            continue
        if not include_exams and "exam" in ev["type"].lower():
            continue
        filtered.append(ev)
    return filtered

def event_ics(event, now):
    uid_part = f"vatsim-event-{event['id']}" if event["id"] is not None else None
    if uid_part is None:
        hash_input = (event["name"] + event["start"].isoformat()).encode("utf-8")
        uid_part = f"vatsim-event-{hashlib.sha1(hash_input).hexdigest()}"
    uid = f"{uid_part}@vatscoreradar"
    dtstamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = event["start"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtend = event["end"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = _escape_ical(event["name"])
    desc_body = event["short"]
    if event["link"]:
        desc_body = desc_body + "\n" + event["link"]
    description = _escape_ical(desc_body)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//VatScoreRadar//Events//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}"
    ]
    if event["airports"]:
        location = _escape_ical(", ".join(event["airports"]))
        lines.append(f"LOCATION:{location}")
    if event["link"]:
        lines.append(f"URL:{_escape_ical(event['link'])}")
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded = []
    for line in lines:
        folded.extend(_fold_line(line))
    return "\r\n".join(folded) + "\r\n"


def utc_label(moment):
    offset = moment.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    if minutes == 0:
        return "UTC"
    sign = "+" if minutes > 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def time_line(ev, tz):
    s, e = ev["start"].astimezone(tz), ev["end"].astimezone(tz)
    day = lambda d: d.strftime("%a %d %b")
    if s.date() == e.date():
        local = f"{day(s)} {s:%H:%M}-{e:%H:%M}"
    else:
        local = f"{day(s)} {s:%H:%M} - {day(e)} {e:%H:%M}"
    zulu = f"{ev['start']:%H:%M}-{ev['end']:%H:%M}Z"
    if utc_label(s) == "UTC":
        return f"{local} UTC"
    return f"{local} ({utc_label(s)}) · {zulu}"


def relative(ev, now):
    def span(delta):
        minutes = max(int(delta.total_seconds() // 60), 0)
        if minutes < 60:
            return f"{minutes}m"
        if minutes < 48 * 60:
            return f"{minutes // 60}h {minutes % 60:02d}m"
        return f"{minutes // 1440} days"
    if ev["start"] <= now < ev["end"]:
        return "ends in " + span(ev["end"] - now)
    return "starts in " + span(ev["start"] - now)


def events_at_airport(events, icao, now, limit=5):
    code = str(icao).strip().upper()
    return [e for e in events if code in e["airports"] and e["end"] > now][:limit]
