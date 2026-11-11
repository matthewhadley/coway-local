# Validation for 0.2.1

All 20 Python tests, 6 JavaScript tests and Ruff checks pass locally with Home Assistant **2026.10.2**, Python **3.14.6**, and aMQTT **0.12.1** on macOS. The Checks workflow runs the same tests on Linux plus Home Assistant's hassfest validator.

- Dependency resolution with HA’s pinned dependencies succeeds.
- Real HA config/options flows, eleven enabled entities plus the disabled-by-default Last seen registry entry, fan and select service calls, entry reload and unload are exercised in isolated temporary storage.
- Synthetic `A1020` reports travel through the TLS MQTT broker to HA sensor entities. Checks cover PM2.5 and light units, filter usage-to-remaining conversion including 0/100 boundaries, partial updates, invalid readings, disconnect/reconnect and reload. HA's Activity helper classifies all four measurements as continuous sensors to exclude their routine updates.
- Real loopback clients exercise TLS 1.2 / AES128-SHA256, mutual certificates, the four subscription topics, reserved `$aws/...` status publications, command acknowledgements, two-device isolation and impersonation rejection.
- HTTP exposes only the public CA. Enrollment and short-lived private-key downloads require HTTPS and a valid pending setup capability.
- Credential persistence, setup expiry, listener cleanup and redacted diagnostics pass.
- JavaScript P001/P002 output matches the independent fixed codec fixture; fragment reassembly and invalid input checks pass.
- The browser validates the AP-1022K model using its advertised name, separately from the `COWAY...` Wi-Fi module identity returned by FFA0. A regression test covers this distinction.
- Chrome loads the static page, accepts a synthetic setup bundle, strips its URL fragment, and exposes Web Bluetooth with empty Wi-Fi credentials.

The **physical AP-1022K** was temporarily connected to the integration’s service using its existing local credentials:

- First reconnect: **7.37 seconds**.
- Status query acknowledged.
- Speed 1 → 2 → 1 acknowledged.
- Power off and on each confirmed by a fresh state query.
- Service restart reconnect: **8.18 seconds**, followed by a successful query.
- Original laptop service restored and fan confirmed on at speed 1.

The earlier prototype successfully performed Web Bluetooth provisioning and tested HTTPS port 9443 and MQTT port 9883 on the same fan.

The static HTTPS page is published at https://scottjg.github.io/coway-local/ and has been checked in Chrome.

## Completed HAOS deployment

A physical AP-1022K was freshly enrolled into **Home Assistant OS 18.3**, Supervisor **2026.10.5**, Core **2026.10.2**:

- Installed v0.1.0 through HACS and restarted HA.
- Created a new HA-owned CA and listeners on HTTP 8080, HTTPS 9443, and MQTT TLS 9883. Verified CA retrieval, HTTPS certificate validation, and MQTT rejection without a client certificate.
- Used Chrome on macOS and the published HTTPS Web Bluetooth page to provision the fan with its normal Wi-Fi network and the HA server address.
- The browser reported successful Wi-Fi association, CA and certificate downloads, and MQTT connection. HA then confirmed the authenticated connection and completed enrollment.
- HA created all eight entities. Its fan control changed speed 1 → 2 → 1, with each change confirmed by device-reported state. The fan was left on at speed 1.
- Stopped the old laptop broker, certificate service, HTTPS relay, and prototype web server. HA remained connected and a fresh status request updated the last-seen entity.

The installed server was v0.1.0; the successful enrollment used the corrected browser identity handling included in v0.1.1. The v0.1.1 patch changed the browser, documentation, and version metadata; server behavior was unchanged.

In v0.1.2, Last seen is disabled by default for newly created entities. The existing HAOS entity was disabled through HA's entity settings to stop routine timestamp Activity updates; no server restart or fan reprovisioning was needed. Existing historical entries are retained.

## v0.2.0 telemetry deployment

HACS downloaded implementation commit `4bf7aec` (manifest version 0.2.0), then Home Assistant was restarted. The existing fan reconnected without Bluetooth provisioning. Its device page displayed all four new sensors from fresh device reports:

| Sensor | Reading observed after restart |
| --- | --- |
| PM2.5 | 0 μg/m³ |
| Ambient light | 533 lx |
| Pre-filter remaining | 74% |
| MAX2 filter remaining | 29% |

The Connection sensor showed Connected and Last seen remained disabled. No control settings or filter counters were changed during this update. These checks confirm local MQTT-to-HA delivery, not independent calibration of the physical sensors or a side-by-side comparison with the original app.

## v0.2.1 cleaning-interval initialization

New enrollment sends the observed `A1051.0001 = 168` command and waits for a matching `A1050` confirmation before completing. Confirmed intervals are stored with each device. Tests cover fresh enrollment, re-enrollment, unrelated acknowledgements, wrong-value replies, interrupted setup and retry after restart, simultaneous updates to two devices, and retaining a later user choice without replaying the default on reconnect. Existing enrollments without a saved interval remain unchanged until the user selects one.

Coverage is limited to this AP-1022K and the firmware listed in the README. The v0.2.0 pre-filter cycle initially showed unknown; v0.2.1 establishes a known value during new enrollment and persists confirmed choices. A read-only interval query remains unidentified. Other models, long-term operation, and HA Container networking have not been tested on physical hardware.
