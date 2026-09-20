import requests
import streamlit as st
from shapely.geometry import Point, shape
from shapely.prepared import prep

# Approach areas from the SimAware TRACON project (CC BY-SA 4.0), downloaded at run time and never stored in the repo.
TRACON_GEO_URL = "https://github.com/vatsimnetwork/simaware-tracon-project/releases/latest/download/TRACONBoundaries.geojson"


@st.cache_resource(ttl=86400, show_spinner=False)
def _tracon_index():
    # Raises on failure so a bad download is never cached for a day.
    r = requests.get(TRACON_GEO_URL, timeout=25)
    r.raise_for_status()
    items = []
    for f in r.json().get("features", []):
        props = f.get("properties") or {}
        tid = str(props.get("id") or "").strip()
        if not tid or not f.get("geometry"):
            continue
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        keys = {str(k).upper() for k in [tid] + list(props.get("prefix") or []) if k}
        items.append({"id": tid, "name": str(props.get("name") or ""), "keys": keys, "geometry": g, "bounds": g.bounds, "prepared": prep(g)})
    if not items:
        raise ValueError("no TRACON boundaries")
    return items


def approach_areas_at(lat, lon):
    """The approach areas that lie over this point (Yesilkoy Approach covers LTFM), each with id, name, callsign prefixes and geometry; [] when unavailable."""
    try:
        index = _tracon_index()
    except Exception:
        return []
    pt = Point(lon, lat)
    return [t for t in index if t["bounds"][0] <= lon <= t["bounds"][2] and t["bounds"][1] <= lat <= t["bounds"][3] and t["prepared"].intersects(pt)]


def approach_keys_at(lat, lon):
    """Callsign prefixes of the approach areas over this point (IST for Istanbul); empty when unavailable."""
    keys = set()
    for t in approach_areas_at(lat, lon):
        keys |= t["keys"]
    return keys
