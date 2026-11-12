"""Names supplied during local Bluetooth enrollment."""

import base64
import binascii
import re


def clean_name(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Device names must be at most 80 characters")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("Device names cannot contain control characters")
    return value.strip()


def choose_name(custom_name="", bluetooth_name=""):
    if custom_name:
        return custom_name, "custom"
    # The name is discovered in the browser after the setup link is created.
    return bluetooth_name, "bluetooth"


def decode_bluetooth_name(encoded):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,427}", encoded):
        raise ValueError("Invalid Bluetooth name")
    try:
        data = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(data).decode().rstrip("=") != encoded:
            raise ValueError("Invalid Bluetooth name encoding")
        name = clean_name(data.decode("utf-8"))
    except (binascii.Error, UnicodeError) as error:
        raise ValueError("Invalid Bluetooth name") from error
    if not name:
        raise ValueError("Empty Bluetooth name")
    return name
