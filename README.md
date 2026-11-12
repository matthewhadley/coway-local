# Coway Local

A single Home Assistant custom integration for local Coway control, tested with the **AP-1022K**. It hosts the certificate service and TLS MQTT broker inside Home Assistant. Initial Wi-Fi setup uses a nearby Mac or Android device running Chrome and Web Bluetooth.

No add-on, external MQTT integration, Raspberry Pi, or Bluetooth adapter on the HA host is required. After enrollment, the fan connects directly to HA over your LAN. The Coway cloud and provisioning website are not needed for ongoing control.

This is an experimental implementation of the observed **FFC0 / P001 / P002** protocol. Bluetooth discovery uses the manufacturer's advertisement layouts found in the IoCare app, without an exact model-name restriction. Other models can be tried if they advertise those layouts and expose the same setup services and identity format. Only AP-1022K has been tested on physical hardware; other models and firmware are unverified. See [discovery evidence and limitations](BLE_DISCOVERY.md).

## Included

- Fan entity: power, three manual speeds, smart and sleep modes.
- Select entities: lighting levels 1–4, timer, smart sensitivity, pre-filter cleaning cycle.
- Measurement sensors: PM2.5, ambient light, pre-filter remaining, and MAX2 filter remaining.
- Connection sensor, refresh-status button, and an optional last-seen timestamp (disabled by default).
- Independent credentials and exact MQTT topic permissions for each fan.
- Persistent local CA, mutual TLS, 15-minute enrollment links, and redacted diagnostics.
- Static Web Bluetooth page with no analytics, external JavaScript or browser-to-HA requests.

## Install

Minimum supported/tested Home Assistant Core: **2026.10.2** (Python 3.14).

For a manual install, copy `custom_components/coway_local` into your HA configuration directory and restart Home Assistant. The release ZIP has the same directory layout and can be extracted into `/config`.

In HACS, add `https://github.com/scottjg/coway-local` as a custom repository, category **Integration**. Install **Coway Local**, then restart HA.

Add **Coway Local** under **Settings → Devices & services → Add integration**.

1. Enter the HA host’s reserved LAN **IPv4 address**. Do not enter `homeassistant.local`, a cloud URL, `0.0.0.0`, or a Docker-internal address.
2. Choose three unused TCP ports. Defaults: HTTP **8080**, HTTPS **9443**, MQTT TLS **9883**.
3. Set the provisioning page URL to your published HTTPS site. The project’s hosted page is `https://scottjg.github.io/coway-local/`. You can also publish the included `web/` directory to your own HTTPS host. For offline development, use `http://localhost:18765/` as described below.
4. Submit. If a port is busy, HA reports setup retrying; choose another port in the entry’s settings.

Reserve the HA host address in your router before provisioning. Changing the address or ports requires provisioning the fan again.

## Add a fan

1. Open **Coway Local → Configure → Add or provision a fan**.
2. Leave **Custom device name** blank to use the Bluetooth name, or enter a name such as “Bedroom purifier,” then select **Submit**. No printed serial number is needed.
3. Open the generated **Bluetooth setup** link in a **new Chrome tab** on a nearby Mac or Android device. Keep the HA setup dialog open.
4. Put the fan in Wi-Fi/Bluetooth setup mode and close the Coway app.
5. Follow the four-step wizard: **Fan → Wi-Fi → Review → Connect**. Choose the fan, select a 2.4 GHz Wi-Fi network and enter its password, then review the fan, network, and local server before starting setup. Back lets you revise the details. The Bluetooth picker filters for Coway setup advertisements without an exact model-name restriction; the page checks the selected device's services and identity.
6. Watch connection progress in the final step. When it says **Finish in Home Assistant**, return to HA and press **Submit**. HA confirms the connection and the **3-week pre-filter cleaning interval** applied during enrollment.

Every enrollment, including provisioning an existing fan again, sets its cleaning interval to **3 weeks**. This is the integration's chosen default, not a verified factory default. Change it afterward using **Pre-filter cleaning cycle**. HA saves confirmed changes and restores the last known interval after a restart; ordinary reconnects do not reset your choice. If initialization is interrupted before confirmation, HA retries when the fan reconnects or during its next periodic refresh.

The setup link expires after 15 minutes and is revoked when canceled or completed. If it expires or the fan exits setup mode, generate a new link and re-enter setup mode. Safari and iPhone browsers are not supported by this setup path.

### Device names

Names use an explicitly chosen custom name, otherwise the selected device's
advertised Bluetooth name. If the advertisement has no name, setup uses the
module name returned by the BLE identity response when available.

The browser derives an 18-character local protocol identifier as `LOCAL0` followed
by the fan's 12 uppercase Wi-Fi MAC digits. This value is sent in the firmware's
`serial` field and used for local certificates, MQTT topics, and HA entity IDs.
It is not the manufacturer's printed serial number, and HA does not display it
as one. The physical AP-1022K accepted this identity for enrollment and control.

Names are saved locally. Re-enrollment with a blank custom-name field preserves an
existing custom name. Names assigned through HA's device settings take precedence
and are never overwritten. Existing entity IDs remain unchanged on re-enrollment.

The browser carries the Bluetooth label in a base64url path
on the fan's existing HTTPS enrollment request. The server validates the token and verifies that the supplied local identifier
exactly matches the Wi-Fi MAC. The first valid request binds the token to that
fan; another MAC cannot claim it, including with concurrent requests. Wi-Fi credentials and tokens
are not included in that path; short certificate/key download URLs are unchanged.
Use the current integration and hosted setup page together.
No migrations or compatibility paths for earlier development snapshots are included.
Before re-enrolling a fan that used its printed serial in an earlier development
version, remove that old device from Coway Local. New setup links use version 2;
update both the integration and setup page, then create a fresh link.

The browser displays the destination server before transmitting anything. Its setup token is in the URL fragment, which is not sent in the HTTPS request, and the page removes that fragment immediately. The Wi-Fi password is entered only in the page, stays in memory, and is cleared after completion or disconnection. HA does not receive or store the Wi-Fi password.

## Networking

| Deployment | Network setup |
| --- | --- |
| Home Assistant OS | The listeners run in Core’s host network. Allow the fan to reach the HA machine on the three configured TCP ports. No add-on port mapping is involved. |
| HA Container, host network | Use the Docker host’s LAN address. The listeners bind directly on that host. |
| HA Container, bridge network | Publish all three TCP ports **with identical inside/outside port numbers**, and advertise the host’s LAN address. For the defaults: `8080:8080`, `9443:9443`, `9883:9883`. |
| Separate IoT VLAN | Permit fan → HA on those ports and normal Wi-Fi/DHCP access. Browser and fan must be within Bluetooth range during setup. |

HA’s normal UI can remain on HTTP port 8123. The HTTPS provisioning website only communicates with the fan using Bluetooth, so it does not need CORS, local-network browser permission, a reverse proxy to HA, or a HA login token. Do not embed it under an HTTP HA page in an iframe.

The fan’s CA bootstrap intentionally uses HTTP, matching the device protocol. Certificate enrollment and private-key downloads use TLS; MQTT additionally requires the enrolled device certificate. Keep these listeners on your trusted LAN, without Internet port forwarding. The old firmware requires compatibility with TLS 1.2 / `AES128-SHA256`.

## Serve the provisioning page

Publish only **`web/`** to a trusted HTTPS static host. The included GitHub Pages workflow deploys this directory when manually dispatched:

1. Enable GitHub Pages with **GitHub Actions** as its source.
2. Run **Actions → Provisioning page → Run workflow**.
3. Enter the resulting HTTPS URL in the integration’s server settings.

The static site has no backend. Anyone can host the code, but the site operator controls JavaScript that sees the enrollment token and Wi-Fi password. Use a deployment you trust; no third-party scripts are included.

For a completely local setup page on the nearby computer:

```sh
python3 -m http.server 18765 --bind 127.0.0.1 --directory web
```

Set the integration’s provisioning URL to `http://localhost:18765/`, then open its generated setup link in Chrome **on that computer**. Loopback is a secure-context exception; a plain HTTP LAN address is not. All web assets are included, so this option also works without Internet access.

## Storage and lifecycle

Credentials are stored under `/config/.storage/coway_local/` with private file permissions. Back up this directory together with HA’s config entries. Losing the CA or device credentials requires restoring that backup or provisioning the fan again. The implementation refuses to silently replace a partially missing CA store.

Each device’s certificate fingerprint is bound to its MQTT client ID. It can publish only its own observed status/event topics and subscribe only to its four observed command topics, including its exact `$aws/...` topic. The embedded broker is dedicated to these fans; it is not a general-purpose MQTT broker and does not replace an existing HA MQTT integration.

Unloading or restarting the integration closes all three listeners. Fans reconnect automatically when it returns. Removing a fan from HA revokes its broker access and deletes its stored client credentials. This does not factory-reset the physical fan. Removing and reinstalling the integration preserves the credential store for recovery.

## Limits and troubleshooting

The four measurement sensors consume the fan's periodic `A1020` reports:

| Sensor | Attribute | Interpretation |
| --- | --- | --- |
| PM2.5 | `A1020.0001` | Concentration in μg/m³ |
| Ambient light | `A1020.0007` | Illuminance in lx; physical scaling has not been independently calibrated |
| Pre-filter remaining | `A1020.0011` | `100 − usage`, percent remaining until cleaning |
| MAX2 filter remaining | `A1020.0012` | `100 − usage`, percent remaining until replacement |

PM2.5 is identified by [Coway's public sensor definitions](https://iocare2.coway.com/_next/static/chunks/3kv1xb4at9t7g.js). The light and filter mappings agree with [PyCoway's sensor codes](https://github.com/Antonio112009/pycoway/blob/9d5929bee7f4d3a61e45275bb6486669b4b3474e/src/pycoway/constants.py) and [filter conversion](https://github.com/Antonio112009/pycoway/blob/9d5929bee7f4d3a61e45275bb6486669b4b3474e/src/pycoway/devices/parser.py). All four attributes were observed on the tested fan; filter percentages have not been compared side by side with the original app.

Sensors show unknown until the first report after connection, and unavailable while disconnected. Partial reports preserve other readings; invalid types, negative values, and filter usage above 100 become unknown. No additional cloud requests or device commands are sent. These are measurement sensors with history/statistics, so their routine updates are excluded from Activity.

- "Last seen" changes on every MQTT message. It is disabled by default to avoid filling Activity and the recorder with routine timestamps. Enable it in the entity settings only when needed for troubleshooting. The Connection sensor remains enabled. Disabling Last seen stops new updates but does not delete historical entries.
- Tested on one AP-1022K, MCU firmware `V1.0.0.1`, Wi-Fi firmware `000011`. Do not assume other Coway devices use this protocol.
- The name-independent setup page enables experiments with other models, not automatic multi-model support. The server still uses the AP-1022K control/telemetry mappings and MQTT service code `002AIR007`; its model metadata also defaults to AP-1022K. Compatible Bluetooth services alone do not establish compatibility with those server mappings.
- A read-only query for the pre-filter cleaning interval has not been identified. Enrollment establishes a confirmed 3-week default, and confirmed changes are saved across HA restarts.
- PM10, other air-quality metrics, filter notification flags, firmware updates, and AWS shadow synchronization are not implemented. The broker accepts the observed shadow/FOTA subscriptions but does not provide those services.
- Wi-Fi association failure: use a 2.4 GHz network compatible with the fan, re-enter setup mode, and check the password.
- Certificate or broker failure: check the advertised LAN IP, the three ports, routing/VLAN isolation, and HA logs. Keep the short HTTPS download URLs intact.
- HA setup retrying: commonly a port conflict or unreadable credential storage. Other integrations keep running.
- Controls unavailable: check the connection sensor, fan power, and listener reachability. Restarting the integration should not require provisioning again.

This integration is independent of the Coway IoCare cloud integration. Provisioning to this server replaces the fan’s cloud destination; the original mobile app is not the controller for this local configuration.

## Development and validation

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest -q
.venv/bin/ruff check .
node --test tests/web.test.mjs
.venv/bin/python scripts/package.py
```

Tests use temporary credentials and real loopback HTTP/TLS/MQTT sockets. They cover enrollment expiry, credential isolation, MQTT acknowledgements and reserved topics, device impersonation, persistence, reconnect, configuration validation, and real HA flows/entities/services/reload. Cleaning-interval tests cover the enrollment default, matching acknowledgements, interrupted initialization, later preferences surviving restarts, and re-enrollment. Telemetry tests cover wire-to-entity values and units, percentage conversion, partial and invalid reports, stale-value clearing on reconnect, and Activity filtering. Browser codec tests use an independent fixed protocol fixture. No test requires a real fan. For interactive wizard checks with synthetic Bluetooth responses, run `python tests/browser/serve.py` and open `http://localhost:18765/preview`. Its scenario controls exercise cancellation, unsupported devices, empty scans, Wi-Fi failure, and disconnect recovery without touching hardware. The test adapter is outside the published `web/` directory.

Hardware checks confirmed status queries, speed changes, power off/on, and automatic reconnect with this service. A fresh enrollment from the published HTTPS page into HAOS also passed, using ports 8080, 9443, and 9883. HA created the original eight entities, controlled the fan, and continued receiving fresh status after the old laptop services stopped. See `VALIDATION.md` for the tested versions and limits.

aMQTT is pinned to **0.12.1** because the adapter overrides private broker hooks. Re-run wire and HA compatibility tests before changing that pin.

MIT licensed. The broker adapter includes behavior adapted from aMQTT; its copyright and license are preserved in `LICENSE.amqtt`. This project is not affiliated with Coway or an official Home Assistant integration.

Packaging follows the [HACS integration layout](https://www.hacs.xyz/docs/publish/integration/); the static deployment follows [GitHub Pages’ Actions workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
