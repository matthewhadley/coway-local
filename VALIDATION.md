# Validation for 0.1.2

Checked with Home Assistant **2026.10.2**, Python **3.14.6**, and aMQTT **0.12.1** on macOS, with the same 14 Python tests and 6 JavaScript tests also passing on GitHub’s Linux runner. Home Assistant’s hassfest validator passes.

- Dependency resolution with HA’s pinned dependencies succeeds.
- Real HA config/options flows, seven enabled entities plus the disabled-by-default Last seen registry entry, fan and select service calls, entry reload and unload pass in isolated temporary storage.
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

Coverage is limited to this AP-1022K and the firmware listed in the README. The pre-filter cycle initially showed unknown, as expected until that setting is acknowledged. Other models, long-term operation, and HA Container networking have not been tested on physical hardware.
