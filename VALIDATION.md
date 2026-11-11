# Validation for 0.1.0

Checked with Home Assistant **2026.10.2**, Python **3.14.6**, and aMQTT **0.12.1** on macOS, with the same 14 Python tests and 5 JavaScript tests also passing on GitHub’s Linux runner. Home Assistant’s hassfest validator passes.

- Dependency resolution with HA’s pinned dependencies succeeds.
- Real HA config/options flows, all eight entities, fan and select service calls, entry reload and unload pass in isolated temporary storage.
- Real loopback clients exercise TLS 1.2 / AES128-SHA256, mutual certificates, the four subscription topics, reserved `$aws/...` status publications, command acknowledgements, two-device isolation and impersonation rejection.
- HTTP exposes only the public CA. Enrollment and short-lived private-key downloads require HTTPS and a valid pending setup capability.
- Credential persistence, setup expiry, listener cleanup and redacted diagnostics pass.
- JavaScript P001/P002 output matches the independent fixed codec fixture; fragment reassembly and invalid input checks pass.
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

**Remaining deployment check:** install this packaged integration on the actual HAOS machine and perform a fresh browser enrollment into its new CA and server address. The hardware check above verifies the new broker/control implementation; it does not claim that final HAOS enrollment has already happened.
