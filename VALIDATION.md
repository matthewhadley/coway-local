# Validation for 0.2.4

Validation uses Home Assistant **2026.10.2**, Python **3.14.6**, and aMQTT **0.12.1** on macOS and Linux. The suite contains 23 Python tests and 12 JavaScript tests.

- Dependency resolution with HA’s pinned dependencies succeeds.
- Real HA config/options flows, eleven enabled entities plus the disabled-by-default Last seen registry entry, fan and select service calls, entry reload and unload are exercised in isolated temporary storage.
- Synthetic `A1020` reports travel through the TLS MQTT broker to HA sensor entities. Checks cover PM2.5 and light units, filter usage-to-remaining conversion including 0/100 boundaries, partial updates, invalid readings, disconnect/reconnect and reload. HA's Activity helper classifies all four measurements as continuous sensors to exclude their routine updates.
- Real loopback clients exercise TLS 1.2 / AES128-SHA256, mutual certificates, the four subscription topics, reserved `$aws/...` status publications, command acknowledgements, two-device isolation and impersonation rejection.
- HTTP exposes only the public CA. Enrollment and short-lived private-key downloads require HTTPS and a valid pending setup capability.
- Credential persistence, setup expiry, listener cleanup and redacted diagnostics pass.
- JavaScript P001/P002 output matches the independent fixed codec fixture; fragment reassembly and invalid input checks pass.
- Browser names are display labels and do not gate device acceptance. Tests cover synchronous manufacturer-filtered discovery, matching the captured advertisement and alternate product codes, excluding unrelated manufacturers and malformed layouts, service permissions, alternate/renamed/unnamed devices, alternate setup-bundle model labels, and rejection of malformed identity responses even when the advertised name matches AP-1022K. FFA0's module name remains distinct from the advertised name.
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

Installed implementation commit `7af9f36` through HACS and restarted HAOS. The integration page reported version **0.2.1**. The already-enrolled physical fan initially retained its unknown interval; selecting **3 weeks** received device confirmation. After reloading Coway Local, the fan automatically reconnected and the dropdown still showed **3 weeks**, confirming persistence into a new service instance. The four measurement sensors continued reporting and Last seen remained disabled. No Bluetooth re-enrollment was performed for this release; the complete enrollment initialization sequence is covered by the real MQTT/HA tests above.

## v0.2.2 Bluetooth discovery

The chooser applies the IoCare app's manufacturer-layout checks for IDs `0x0639` and `0xFFFF`, then the page reads the expected services, characteristics and identity. In the saved Android scan these checks match the fan and exclude the other 67 advertisers with manufacturer data. The [APK analysis](BLE_DISCOVERY.md) records the layouts and the differences from the app's full catalog-based discovery. Neither the advertised name nor setup-bundle model label must equal AP-1022K. Before starting a different connection, old Wi-Fi scan results are cleared. Missing setup services produce an actionable error. The server's protocol mappings are unchanged; the updated hosted page works with existing v0.2.1 setup links without restarting HA. Tests simulate alternate device names and identity responses; no additional physical model has been tested.

Chrome on macOS loaded the published page and opened the manufacturer-filtered chooser using a synthetic setup link. After refreshing cached modules, the unrelated-device list disappeared; no candidate was advertising during that check. The captured physical fan advertisement is covered by the filter test, but no new physical enrollment was performed. Versioned module URLs prevent reuse of the preceding unfiltered setup code. The test link was cleared afterward.

## v0.2.3 automatic device names

The local catalog matches the documented model-code position in an 18-character
serial number. Tests cover verified product names, unknown-code Bluetooth names,
Unicode labels, explicit custom names, re-enrollment, and restart persistence. The real HA
flow accepts an omitted name, updates its device-registry default from the BLE
label, and retains a user-assigned registry name across re-enrollment and reload.

Tests exercise Unicode/base64url name transport, reject malformed labels,
require the enrollment token/serial/MAC checks, and confirm the enrollment endpoint
is unavailable over HTTP. The new named URL requires a physical-fan check; previous
successful hardware enrollments used the original endpoint.

Installed implementation commit `4d6fb45` through HACS and restarted HAOS. The
existing device automatically changed from **Coway** to **Coway Airmega IconS**,
and its Connection sensor returned to **Connected** with fresh telemetry. Its
existing device page and entities were retained; no Bluetooth re-enrollment or
manual rename was needed. A certificate-validated GET to the new HTTPS enrollment
route returned 405 (the route accepts POST), confirming the updated server loaded.

## v0.2.4 development cleanup

Removed the startup name migration, legacy-name fallback, unnamed enrollment route,
and optional browser capability branches for earlier development versions. The
integration and browser now share one enrollment format, with a Bluetooth name in
every enrollment URL. Two tests solely for upgrades from development snapshots were
removed; current enrollment, name persistence, re-enrollment, user overrides, and
interrupted initialization remain covered by 23 Python and 12 JavaScript tests.
The original captured codec fixture is retained as independent protocol evidence.

Coverage is limited to this AP-1022K and the firmware listed in the README. The v0.2.0 pre-filter cycle initially showed unknown; v0.2.1 establishes a known value during new enrollment and persists confirmed choices. A read-only interval query remains unidentified. Other models, long-term operation, and HA Container networking have not been tested on physical hardware.
