"""Decode the A1020 measurements observed on the AP-1022K."""

# Wire suffix: (entity key, upper bound, convert usage to remaining).
# PM2.5 and light have no verified upper bound; only accept nonnegative integers.
FIELDS = {
    "0001": ("pm25", None, False),
    "0007": ("illuminance", None, False),
    "0011": ("prefilter_remaining", 100, True),
    "0012": ("max2_remaining", 100, True),
}


def decode_report(attributes: dict) -> dict[str, int | None]:
    """Keep absent fields unchanged; an explicitly invalid reading becomes unknown."""
    readings = {}
    for suffix, (key, maximum, remaining) in FIELDS.items():
        attribute = f"A1020.{suffix}"
        if attribute not in attributes:
            continue
        value = attributes[attribute]
        if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
            readings[key] = None
        else:
            readings[key] = 100 - value if remaining else value
    return readings
