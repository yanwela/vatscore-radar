import requests
from shapely.geometry import Point, shape
from shapely.prepared import prep

from atc_timeline import build_atc_timeline
from geo_compact import compact_rings
from flight_track import STATSIM_API
from tracon_areas import approach_areas_at

_VATSPY_BASE = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/"
_MAX_TRACK_SAMPLES = 400

# Upper airspaces that have no boundary of their own: their controllers cover several of the FIRs below them.
FIR_ALIASES = {"EDUU": ("EDGG", "EDMM", "EDWW"), "EDYY": ("EBBU", "EHAA")}
FIR_ALIAS_NAMES = {"EDUU": "Rhein UAC", "EDYY": "Maastricht UAC"}
_FIR_MARGIN = 600


def _dat_sections():
    r = requests.get(_VATSPY_BASE + "VATSpy.dat", timeout=20)
    r.raise_for_status()
    return r.text.splitlines()


def load_fir_prefixes():
    """FIR boundary id -> callsign prefixes of the controllers that staff it (VATSpy.dat [FIRs]: icao|name|prefix|boundary)."""
    out, inside = {}, False
    for line in _dat_sections():
        text = line.strip()
        if text.startswith("["):
            inside = text == "[FIRs]"
            continue
        parts = [x.strip().upper() for x in text.split("|")]
        if not inside or not text or text.startswith(";") or len(parts) < 4:
            continue
        icao, prefix, boundary = parts[0], parts[2], parts[3]
        for k in (icao, prefix):
            if k:
                out.setdefault(boundary or icao, set()).add(k)
    if not out:
        raise ValueError("no FIRs")
    return {b: sorted(v) for b, v in out.items()}


def load_uirs():
    """Upper information regions: UIR code -> (name, member FIR codes or boundary ids), VATSpy.dat [UIRs]: code|name|member,member,..."""
    out, inside = {}, False
    for line in _dat_sections():
        text = line.strip()
        if text.startswith("["):
            inside = text == "[UIRs]"
            continue
        parts = [x.strip() for x in text.split("|")]
        if not inside or not text or text.startswith(";") or len(parts) < 3:
            continue
        members = [m.strip().upper() for m in parts[2].split(",") if m.strip()]
        if members:
            out[parts[0].upper()] = (parts[1], members)
    return out


def load_fir_names():
    """FIR boundary id -> display name (VATSpy.dat [FIRs]: icao|name|prefix|boundary)."""
    out, inside = {}, False
    for line in _dat_sections():
        text = line.strip()
        if text.startswith("["):
            inside = text == "[FIRs]"
            continue
        parts = [x.strip() for x in text.split("|")]
        if not inside or not text or text.startswith(";") or len(parts) < 4:
            continue
        out.setdefault(parts[3].upper() or parts[0].upper(), parts[1])
    return out


def load_fir_index():
    r = requests.get(_VATSPY_BASE + "Boundaries.geojson", timeout=25)
    r.raise_for_status()
    items = []
    for f in r.json().get("features", []):
        fid = str((f.get("properties") or {}).get("id") or "").strip()
        if not fid or not f.get("geometry"):
            continue
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        items.append({"id": fid, "geometry": g, "bounds": g.bounds, "prepared": prep(g)})
    if not items:
        raise ValueError("no FIR boundaries")
    return items


def fir_windows(points, fir_index, fir_prefixes):
    """Callsign prefix of every FIR the track went through -> ((first, last) epoch second the aircraft was inside it, ids of its boundaries)."""
    step = max(1, len(points) // _MAX_TRACK_SAMPLES)
    windows, ids = {}, {}
    for p in points[::step] + points[-1:]:
        lat, lon, t = p[0], p[1], p[3]
        pt = Point(lon, lat)
        for fir in fir_index:
            minx, miny, maxx, maxy = fir["bounds"]
            if not (minx <= lon <= maxx and miny <= lat <= maxy) or not fir["prepared"].intersects(pt):
                continue
            base = fir["id"].split("-")[0]
            for key in {fir["id"], base, *fir_prefixes.get(fir["id"], ()), *fir_prefixes.get(base, ())}:
                first, last = windows.get(key, (t, t))
                windows[key] = (min(first, t), max(last, t))
                ids.setdefault(key, set()).add(fir["id"])
    return windows, ids


def fetch_atc_sessions(t_from, t_to, api_key, session, timeout=25):
    """Every ATC session on the network that overlaps [t_from, t_to] (epoch seconds), or None when statsim.net fails."""
    from datetime import datetime, timezone

    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {"X-API-Key": api_key, "accept": "application/json", "User-Agent": "VatScore/4.0"}
    try:
        resp = session.get(f"{STATSIM_API}/Atcsessions/Dates", params={"from": iso(t_from), "to": iso(t_to)}, headers=headers, timeout=timeout)
        body = resp.json() if resp.status_code == 200 else None
    except Exception:
        return None
    return body if isinstance(body, list) else None


def _area(area_id, kind, name, geometry):
    point = geometry.representative_point()
    return {"id": area_id, "kind": kind, "name": name, "lat": round(point.y, 3), "lon": round(point.x, 3),
            "poly": compact_rings(geometry, 0.05 if kind == "fir" else 0.01, 3, 300 if kind == "fir" else 150)}


def replay_atc_entries(points, dep, arr, sessions, airport_keys, fir_index, fir_prefixes, airport_points):
    """{"entries": controllers online during the flight, "areas": id -> polygon to draw while one of its controllers is online}.
    airport_points: {ICAO: (lat, lon)} of the departure / arrival airport, used to find the approach areas over them."""
    t_from, t_to = points[0][3], points[-1][3]
    windows, fir_ids = fir_windows(points, fir_index, fir_prefixes)
    fir_by_id = {f["id"]: f for f in fir_index}
    approach = {}
    for icao, (lat, lon) in airport_points.items():
        approach[icao] = approach_areas_at(lat, lon)
    entries, areas = [], {}
    for e in build_atc_timeline(sessions, dep, arr, airport_keys, set(windows), t_from, t_to):
        if e["kind"] == "fir":
            # only while the aircraft was in (or about to enter / just left) that FIR
            first, last = windows[e["place"]]
            e = {**e, "on": max(e["on"], first - _FIR_MARGIN), "off": min(e["off"], last + _FIR_MARGIN)}
            if e["off"] <= e["on"]:
                continue
            area_id = "fir:" + e["place"]
            if area_id not in areas:
                parts = [_area(area_id, "fir", e["place"], fir_by_id[i]["geometry"]) for i in sorted(fir_ids.get(e["place"], ()))[:6] if i in fir_by_id]
                if parts:
                    areas[area_id] = {**parts[0], "poly": [ring for p in parts for ring in p["poly"]]}
            e["area"] = area_id if area_id in areas else None
        else:
            prefix = e["callsign"].split("_")[0]
            tracon = next((t for t in approach.get(e["place"], []) if e["role"] in ("APP", "DEP") and prefix in t["keys"]), None)
            e["area"] = None
            if tracon:
                area_id = "app:" + tracon["id"]
                if area_id not in areas:
                    areas[area_id] = _area(area_id, "app", tracon["name"], tracon["geometry"])
                e["area"] = area_id
        entries.append(e)
    return {"entries": entries, "areas": areas}
