"""Small RFC 6238 and secret-storage helpers for admin profile 2FA."""
import base64
import hashlib
import hmac
import io
import secrets
import struct
import time

CHALLENGE_TTL_SECONDS = 300
ENROLLMENT_TTL_SECONDS = 600


def _fernet(secret_key):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"capsstream-totp-v1",
        info=b"profile-admin-totp",
    ).derive(str(secret_key).encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret, secret_key):
    return _fernet(secret_key).encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(token, secret_key):
    return _fernet(secret_key).decrypt(token.encode("ascii")).decode("ascii")


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret, account, issuer="CapsStream"):
    from urllib.parse import quote
    label = quote(f"{issuer}:{account}", safe=":")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def code_at(secret, timestamp=None):
    timestamp = time.time() if timestamp is None else timestamp
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    counter = int(timestamp // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}", counter


def matching_step(secret, submitted, last_step=-1, timestamp=None):
    submitted = str(submitted or "").strip()
    if len(submitted) != 6 or not submitted.isdigit():
        return None
    now_step = int((time.time() if timestamp is None else timestamp) // 30)
    matched = []
    last_step = -1 if last_step is None else int(last_step)
    for step in range(now_step - 1, now_step + 2):
        if step <= last_step:
            continue
        expected, _ = code_at(secret, step * 30)
        if hmac.compare_digest(expected, submitted):
            matched.append(step)
    return max(matched) if matched else None


def qr_png_data_uri(uri):
    import qrcode
    image = qrcode.make(uri)
    output = io.BytesIO()
    image.save(output, format="PNG")
    import base64 as _base64
    return "data:image/png;base64," + _base64.b64encode(output.getvalue()).decode("ascii")


def recovery_codes(count=10):
    return [secrets.token_hex(16).upper() for _ in range(count)]


def recovery_hash(code):
    normalized = str(code or "").strip().replace("-", "").upper()
    return hashlib.sha256(normalized.encode("ascii", errors="ignore")).hexdigest()
