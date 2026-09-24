def parse_user_agent(ua):
    if not isinstance(ua, str) or not ua:
        return {"os": "Unknown OS", "browser": "Unknown Browser", "device_type": "PC / Laptop"}
    ua_l = ua.lower()
    if "edg/" in ua_l:
        browser = "Edge"
    elif "opr/" in ua_l or "opera" in ua_l:
        browser = "Opera"
    elif "firefox/" in ua_l:
        browser = "Firefox"
    elif "chrome/" in ua_l:
        browser = "Chrome"
    elif "safari/" in ua_l and "version/" in ua_l:
        browser = "Safari"
    else:
        browser = "Other"
    if "windows nt" in ua_l:
        os = "Windows"
    elif any(x in ua_l for x in ("iphone", "ipad", "ios")):
        os = "iOS"
    elif "mac os x" in ua_l:
        os = "macOS"
    elif "android" in ua_l:
        os = "Android"
    elif "linux" in ua_l:
        os = "Linux"
    else:
        os = "Unknown OS"
    if "ipad" in ua_l or ("android" in ua_l and "mobile" not in ua_l):
        device_type = "Tablet"
    elif "mobile" in ua_l or "iphone" in ua_l or ("android" in ua_l and "mobile" in ua_l):
        device_type = "Mobile"
    else:
        device_type = "PC / Laptop"
    return {"os": os, "browser": browser, "device_type": device_type}