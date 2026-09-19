from datetime import datetime, timedelta, timezone

def _ts(v):
    if not isinstance(v, str):
        return None
    try:
        s = v.strip()
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _clean_str(v):
    if v is None:
        return ""
    return str(v).strip().upper()

def group_connections(flights, max_gap_hours=12) -> list:
    if not isinstance(flights, list):
        return []
        
    valid_flights = []
    for f in flights:
        if isinstance(f, dict) and "id" in f and isinstance(f["id"], str):
            valid_flights.append(f)
            
    parseable = []
    unparseable = []
    for f in valid_flights:
        lo_str = f.get("loggedOn")
        lo_dt = _ts(lo_str) if isinstance(lo_str, str) else None
        if lo_dt is not None:
            parseable.append((f, lo_dt))
        else:
            unparseable.append((f, None))
            
    parseable.sort(key=lambda x: x[1])
    sorted_flights = parseable + unparseable
    
    def can_join(item_f, item_dt, last_f, last_dt):
        if item_dt is None or last_dt is None:
            return False
            
        item_cs = _clean_str(item_f.get("callsign"))
        last_cs = _clean_str(last_f.get("callsign"))
        if item_cs != last_cs:
            return False
            
        item_dep = _clean_str(item_f.get("departure"))
        last_dep = _clean_str(last_f.get("departure"))
        if not item_dep or item_dep != last_dep:
            return False
            
        item_dest = _clean_str(item_f.get("destination"))
        last_dest = _clean_str(last_f.get("destination"))
        if not item_dest or item_dest != last_dest:
            return False
            
        last_arr = last_f.get("arrived")
        if last_arr is not None and last_arr != "":
            return False
            
        diff = item_dt - last_dt
        max_gap = timedelta(hours=max_gap_hours)
        if not (timedelta(0) <= diff <= max_gap):
            return False
            
        return True

    groups = []
    for f, dt in sorted_flights:
        if not groups:
            groups.append([(f, dt)])
        else:
            last_group = groups[-1]
            last_f, last_dt = last_group[-1]
            if can_join(f, dt, last_f, last_dt):
                last_group.append((f, dt))
            else:
                groups.append([(f, dt)])
                
    groups_with_index = [(g, i) for i, g in enumerate(groups)]
    
    def group_sort_key(item):
        g, i = item
        first_dt = g[0][1]
        if first_dt is not None:
            return (1, first_dt, -i)
        else:
            return (0, -i)
            
    groups_with_index.sort(key=group_sort_key, reverse=True)
    sorted_groups = [g for g, i in groups_with_index]
    
    result = []
    for g in sorted_groups:
        first_f = g[0][0]
        last_f = g[-1][0]
        ids = [f["id"] for f, _ in g]
        
        merged = first_f.copy()
        if "arrived" in last_f:
            merged["arrived"] = last_f["arrived"]
        else:
            merged.pop("arrived", None)
            
        last_ac = last_f.get("aircraft")
        if last_ac is not None and last_ac != "":
            merged["aircraft"] = last_ac
            
        result.append({
            "ids": ids,
            "first": first_f,
            "last": last_f,
            "connections": len(ids),
            "flight": merged
        })
    return result

def merge_tracks(tracks) -> list:
    if not isinstance(tracks, list):
        return []
        
    all_points = []
    for track in tracks:
        if not isinstance(track, list):
            continue
        for p in track:
            if not isinstance(p, (list, tuple)):
                continue
            if len(p) < 5:
                continue
            t = p[3]
            if isinstance(t, bool) or not isinstance(t, (int, float)):
                continue
            all_points.append(p)
            
    all_points.sort(key=lambda p: p[3])
    
    kept_points = []
    prev_t = None
    for p in all_points:
        t = p[3]
        if prev_t is None or t > prev_t:
            kept_points.append(list(p))
            prev_t = t
            
    return kept_points