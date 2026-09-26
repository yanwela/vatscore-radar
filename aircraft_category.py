MILITARY_TYPES = frozenset({
    "F16", "F18", "F15", "F22", "F35", "F14", "F4", "F5", "EUFI", "EFAF", "RFAL",
    "GR4", "TORN", "SU27", "SU30", "SU35", "MG29", "B52", "B1", "B1B", "B2",
    "C17", "C130", "C30J", "C5", "C5M", "A400", "KC10", "KC135", "K35R", "K35T",
    "KC46", "E3TF", "E3CF", "E6", "P8", "P3", "V22", "A10", "H60", "UH60", "CH47",
    "H64", "AH64", "NH90", "U2", "T38"
})

HELICOPTER_TYPES = frozenset({
    "R22", "R44", "R66", "EC20", "EC30", "EC35", "EC45", "EC55", "EC75", "AS32",
    "AS50", "AS55", "AS65", "B06", "B06T", "B407", "B412", "B429", "B505", "A109",
    "A119", "A139", "A169", "AW09", "S76", "S92", "S61", "H500", "MD52", "MD90",
    "EN28", "EN48", "BK17", "H160", "H125", "H135", "H145", "H175", "H225"
})

GA_TYPES = frozenset({
    "C140", "C150", "C152", "C162", "C170", "C172", "C175", "C177", "C180", "C182",
    "C185", "C206", "C207", "C208", "C210", "C310", "C337", "C340", "C402", "C414",
    "C421", "P28A", "P28B", "P28R", "P28T", "PA24", "PA27", "PA28", "PA31", "PA32",
    "PA34", "PA44", "PA46", "DA20", "DA40", "DA42", "DA62", "SR20", "SR22", "S22T",
    "BE33", "BE35", "BE36", "BE55", "BE58", "BE9L", "BE20", "PC12", "TBM7", "TBM8",
    "TBM9", "M20P", "M20T", "TB10", "TB20", "TB21", "AA5", "RV6", "RV7", "RV8",
    "RV9", "RV10", "DV20", "E300", "COL4", "G115", "SF25", "DR40", "CH7A"
})

BUSINESS_JET_TYPES = frozenset({
    "GLF2", "GLF3", "GLF4", "GLF5", "GLF6", "GALX", "GLEX", "G150", "G200", "G280",
    "CL30", "CL35", "CL60", "CL64", "C25A", "C25B", "C25C", "C25M", "C500", "C501",
    "C510", "C525", "C550", "C560", "C56X", "C650", "C680", "C68A", "C700", "C750",
    "E50P", "E55P", "EA50", "FA10", "FA20", "FA50", "FA7X", "FA8X", "F900", "F2TH",
    "H25A", "H25B", "H25C", "LJ23", "LJ31", "LJ35", "LJ40", "LJ45", "LJ55", "LJ60",
    "LJ75", "PRM1", "HDJT", "SF50", "BE40", "ASTR"
})

MILITARY_CALLSIGN_PREFIXES = (
    "TUR", "RCH", "AME", "BAF", "IAM", "GAF", "ASY", "MIL", "NAVY", "ARMY",
    "AF1", "AF2"
)

def classify_aircraft(ac_type, callsign):
    t = str(ac_type or "").upper().strip()
    cs = str(callsign or "").upper().strip()
    if t in MILITARY_TYPES:
        return "Military"
    for prefix in MILITARY_CALLSIGN_PREFIXES:
        if cs.startswith(prefix):
            return "Military"
    if t in HELICOPTER_TYPES:
        return "Helicopter"
    if t in GA_TYPES:
        return "General Aviation"
    if t in BUSINESS_JET_TYPES:
        return "Business Jet"
    return "Commercial"