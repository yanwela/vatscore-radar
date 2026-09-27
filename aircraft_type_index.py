import csv
import os

import streamlit as st

from aircraft_types import build_index, category_of

TYPES_CSV_PATH = "aircraft_types.csv"

# a few well-known types missing from the current ICAO designator list (mostly retired aircraft); merged in after the CSV so the
# downloaded file itself stays untouched
_EXTRA_TYPES = [
    {"type_designator": "CONC", "manufacturer": "Aerospatiale/BAC", "model": "Concorde", "description": "LandPlane", "engine_type": "Jet", "engine_count": "4", "wtc": "M"},
]


@st.cache_resource(show_spinner=False)
def type_index():
    # ICAO type designator -> {manufacturer, model, description, engine_type, engine_count, wtc}, built once per process
    # from a static reference file (ICAO Doc 8643 designators, MIT-licensed list: github.com/ColtJD45/icao-aircraft-designator-list)
    rows = []
    if os.path.exists(TYPES_CSV_PATH):
        try:
            with open(TYPES_CSV_PATH, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        except OSError:
            rows = []
    return build_index(rows + _EXTRA_TYPES)


def aircraft_info(icao_type):
    # {"manufacturer", "model", "category"} for a known type, or None
    record = type_index().get(str(icao_type or "").strip().upper())
    if not record:
        return None
    return {"manufacturer": record["manufacturer"], "model": record["model"], "category": category_of(record)}
