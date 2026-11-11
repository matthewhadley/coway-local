"""Observed AP-1022K protocol; identifiers are not shared with the cloud integration."""

DOMAIN = "coway_local"
MODEL = "AP-1022K"
SERVICE_CODE = "002AIR007"
PROVISIONER_URL = "https://scottjg.github.io/coway-local/"
DEFAULT_PORTS = {"http_port": 8080, "https_port": 9443, "mqtt_port": 9883}
PAIRING_SECONDS = 900
CIPHERS = "AES128-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384"

# Each entry is (request API, attribute suffix, user-visible value -> wire value).
SETTINGS = {
    "power": ("A1011", "0001", {"off": 0, "on": 1}),
    "mode": ("A1011", "0002", {"smart": 1, "sleep": 2}),
    "speed": ("A1011", "0003", {"1": 1, "2": 2, "3": 3}),
    "lighting": ("A1011", "0007", {"1": 1, "2": 2, "3": 3, "4": 0}),
    "timer": ("A1011", "0008", {"off": 0, "1 hour": 60, "4 hours": 240, "8 hours": 480}),
    "sensitivity": ("A1011", "000A", {"sensitive": 1, "moderate": 2, "insensitive": 3}),
    "prefilter_cycle": ("A1051", "0001", {"2 weeks": 112, "3 weeks": 168, "4 weeks": 224}),
}
REPLIES = {"A1011": "A1010", "A1013": "A1012", "A1051": "A1050"}
