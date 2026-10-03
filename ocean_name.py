import math

def ocean_name(lat, lon):
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return None
    if lat_f < -90 or lat_f > 90:
        return None
    lon_f = ((lon_f + 180) % 360) - 180
    if lat_f >= 66.5:
        return "Arctic Ocean"
    if lat_f <= -60:
        return "Southern Ocean"
    hemi = "North" if lat_f >= 0 else "South"
    if 20 <= lon_f < 147 and lat_f >= 30:
        return None
    if 20 <= lon_f < 100 and lat_f < 30:
        return "Indian Ocean"
    if 100 <= lon_f < 147 and lat_f < -11:
        return "Indian Ocean"
    if -70 <= lon_f < 20:
        return hemi + " Atlantic Ocean"
    return hemi + " Pacific Ocean"