"""The Bluetooth name carried in the fan's enrollment URL."""

import base64
import binascii
import re


def decode_bluetooth_name(encoded):
    """Decode a canonical unpadded base64url label of 1-80 printable characters."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,427}", encoded):
        raise ValueError("Invalid Bluetooth name")
    try:
        data = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(data).decode().rstrip("=") != encoded:
            raise ValueError("Invalid Bluetooth name encoding")
        name = data.decode("utf-8").strip()
    except (binascii.Error, UnicodeError) as error:
        raise ValueError("Invalid Bluetooth name") from error
    if not name or len(name) > 80 or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in name):
        raise ValueError("Invalid Bluetooth name")
    return name
