import re

REGISTRATION_PREFIXES = {
    "N":"us","G":"gb","D":"de","F":"fr","I":"it","EC":"es","CS":"pt","PH":"nl","OO":"be","LX":"lu","HB":"ch","OE":"at","EI":"ie","EJ":"ie","TF":"is","LN":"no","SE":"se","OY":"dk","OH":"fi","ES":"ee","YL":"lv","LY":"lt","SP":"pl","OK":"cz","OM":"sk","HA":"hu","YR":"ro","LZ":"bg","SX":"gr","TC":"tr","5B":"cy","9H":"mt","YU":"rs","9A":"hr","S5":"si","E7":"ba","Z3":"mk","ZA":"al","4O":"me","UR":"ua","EW":"by","RA":"ru","RF":"ru","4L":"ge","EK":"am","4K":"az","UP":"kz","UK":"uz","4X":"il","JY":"jo","OD":"lb","HZ":"sa","A6":"ae","A7":"qa","A9C":"bh","9K":"kw","A4O":"om","EP":"ir","YI":"iq","SU":"eg","CN":"ma","7T":"dz","TS":"tn","5A":"ly","ET":"et","5Y":"ke","ZS":"za","5N":"ng","VT":"in","AP":"pk","S2":"bd","4R":"lk","9N":"np","B":"cn","BH":"hk","BL":"hk","JA":"jp","HL":"kr","9V":"sg","9M":"my","HS":"th","VN":"vn","PK":"id","RP":"ph","VH":"au","ZK":"nz","C":"ca","C6":"bs","XA":"mx","XB":"mx","XC":"mx","PP":"br","PR":"br","PT":"br","PS":"br","PU":"br","LV":"ar","LQ":"ar","CC":"cl","HK":"co","OB":"pe","YV":"ve","CU":"cu","HP":"pa","TI":"cr","HI":"do","6Y":"jm","DQ":"fj"
}

def extract_registration(remarks):
    if not isinstance(remarks,str):
        return ""
    m=re.search(r"REG/([A-Z0-9-]{2,10})",remarks,re.IGNORECASE)
    return m.group(1).upper() if m else ""

def country_of_registration(registration):
    s=re.sub(r"[^A-Z0-9]","",str(registration or "").upper())
    if len(s)<2:
        return None
    for n in (3,2):
        if s[:n] in REGISTRATION_PREFIXES:
            return REGISTRATION_PREFIXES[s[:n]]
    first, rest = s[0], s[1:]
    if first == "B":
        if rest.isdigit():
            return {4: "cn", 5: "tw"}.get(len(rest))
        return None
    if first == "C" and rest[0] not in "FGI":
        return None
    if first in "DFGI" and not rest[0].isalpha():
        return None
    return REGISTRATION_PREFIXES.get(first)