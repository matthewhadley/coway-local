"""Verified product labels and names supplied during local Bluetooth enrollment."""

import base64
import binascii
import re

# Coway's published serial-code table: five model characters after the first three.
# https://cowaymega.zendesk.com/hc/en-us/articles/4402478387603
# These are naming entries, not a list of tested/supported device protocols.
PRODUCT_NAMES = {
    "02FJ3": "Coway Airmega IconS",
    "02F9R": "Coway Airmega 250S",
    "02DXB": "Coway Airmega 300S",
    "02EUZ": "Coway Airmega 400S",
    "02DNO": "Coway Airmega 400S",
    "02F5O": "Coway Airmega AP-1512HHS",
}


def clean_name(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Device names must be at most 80 characters")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("Device names cannot contain control characters")
    return value.strip()


def catalog_name(serial):
    # Do not guess from arbitrary substrings or short, nonstandard serial numbers.
    if re.fullmatch(r"[A-Za-z0-9]{18}", serial):
        return PRODUCT_NAMES.get(serial[3:8].upper())
    return None


def choose_name(serial, custom_name="", bluetooth_name=""):
    if custom_name:
        return custom_name, "custom"
    if name := catalog_name(serial):
        return name, "catalog"
    # Before Bluetooth selection, an unknown product's display name is empty.
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
