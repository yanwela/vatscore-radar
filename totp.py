import hmac, hashlib, struct, base64, secrets, binascii

def _decode_secret(secret_b32):
    s = str(secret_b32 or "").strip().upper().replace(" ", "")
    if not s:
        return None
    padding = (-len(s)) % 8
    if padding:
        s += "=" * padding
    try:
        return base64.b32decode(s)
    except Exception:
        return None

def hotp_code(key_bytes, counter, digits=6):
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key_bytes, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = ((digest[offset] & 0x7F) << 24) | ((digest[offset + 1] & 0xFF) << 16) | ((digest[offset + 2] & 0xFF) << 8) | (digest[offset + 3] & 0xFF)
    return str(code_int % (10 ** digits)).zfill(digits)

def totp_code(secret_b32, for_time, step=30, digits=6):
    key = _decode_secret(secret_b32)
    if key is None:
        return None
    counter = int(for_time // step)
    if counter < 0:
        counter = 0
    return hotp_code(key, counter, digits)

def verify_totp(secret_b32, code, for_time, step=30, digits=6, window=1):
    code = str(code or "").strip()
    if len(code) != digits or not code.isdigit():
        return False
    key = _decode_secret(secret_b32)
    if key is None:
        return False
    counter = int(for_time // step)
    if counter < 0:
        counter = 0
    for offset in range(-window, window + 1):
        candidate_counter = counter + offset
        if candidate_counter < 0:
            continue
        candidate = hotp_code(key, candidate_counter, digits)
        if hmac.compare_digest(candidate, code):
            return True
    return False

def new_totp_secret(length_bytes=20):
    raw = secrets.token_bytes(length_bytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")