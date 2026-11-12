# Coway Local

A Home Assistant custom integration for local control of Coway Air purifiers, tested with the **AP-1022K**. Using this integration disconnects your device from the Coway cloud. The device is paired with Home Assistant directly, through this custom integration that implements a modified MQTT broker which the fan connects to.

This is an experimental implementation of the observed **FFC0 / P001 / P002** protocol. Bluetooth discovery uses the manufacturer's advertisement layouts found in the IoCare app. Other models can be tried if they advertise those layouts and expose the same setup services and identity format. Only AP-1022K has been tested on physical hardware; other models and firmware are unverified. See [discovery evidence and limitations](BLE_DISCOVERY.md).

## Included

- Fan entity: power, three manual speeds, smart and sleep modes.
- Select entities: lighting levels 1–4, timer, smart sensitivity, pre-filter cleaning cycle.
- Measurement sensors: PM2.5, ambient light, pre-filter remaining, and MAX2 filter remaining.
- Connection sensor, refresh-status button, and an optional last-seen timestamp (disabled by default).
- Independent credentials and exact MQTT topic permissions for each fan.
- Persistent local CA, mutual TLS, 15-minute enrollment links, and redacted diagnostics.
- Static Web Bluetooth page with no analytics, external JavaScript or browser-to-HA API calls.

## Install

Minimum supported/tested Home Assistant Core: **2026.10.2** (Python 3.14).

For a manual install, copy `custom_components/coway_local` into your HA configuration directory and restart Home Assistant. The release ZIP has the same directory layout and can be extracted into `/config`.

In HACS, add `https://github.com/scottjg/coway-local` as a custom repository, category **Integration**. Install **Coway Local**, then restart HA.

Add **Coway Local** under **Settings → Devices & services → Add integration**.

The form shows the LAN **IPv4 address** that Home Assistant detected for itself. In most installations you only need to confirm it and submit.

- **Address:** change it only if the fan cannot reach Home Assistant there. With Docker bridge networking, enter the Docker host’s LAN address instead of the detected container address. Reserve the address in your router before provisioning.
- **Advanced settings:** three TCP ports (defaults: HTTP **8080**, HTTPS **9443**, MQTT TLS **9883**), the listen address, and the provisioning page URL. The default page is `https://scottjg.github.io/coway-local/`; you can also publish the included `web/` directory yourself, as described below.

If a port is busy, HA reports setup retrying; choose another port under **Configure → Server settings**.

Changing the address or ports requires provisioning the fan again. If the machine later loses the configured address, Coway Local raises a repair notice under **Settings → Repairs**.

## Add a fan

1. Open **Coway Local → Configure → Add or provision a fan**.
2. Bluetooth setup opens in a new tab. Use **Chrome on a nearby Mac or Android device** and keep the HA setup dialog open. If the browser blocks the tab, use HA’s **Open website** button. No serial number or device name is needed.
3. Put the fan in Wi-Fi/Bluetooth setup mode and close the Coway app.
4. Follow the four-step wizard: **Fan → Wi-Fi → Review → Connect**. Choose the fan, select a 2.4 GHz Wi-Fi network and enter its password, then review the fan, network, and local server before starting setup. Back lets you revise the details. The Bluetooth picker filters for Coway setup advertisements without an exact model-name restriction; the page checks the selected device's services and identity.
5. After Bluetooth setup succeeds, the browser returns to HA automatically. HA verifies the authenticated connection and the **3-week pre-filter cleaning interval** applied during enrollment, then finishes setup without a Submit step. If verification is still pending, HA explains that finishing setup can take another 2 minutes. Leave the dialog open until **Fan ready** appears. You can rename the device in HA afterward.

Every enrollment, including provisioning an existing fan again, sets its cleaning interval to **3 weeks**. This is the integration's chosen default, not a verified factory default. Change it afterward using **Pre-filter cleaning cycle**. HA saves confirmed changes and restores the last known interval after a restart; ordinary reconnects do not reset your choice. If initialization is interrupted before confirmation, HA retries when the fan reconnects or during its next periodic refresh.

The setup link expires after 15 minutes and is revoked when canceled or completed. If it expires or the fan exits setup mode, generate a new link and re-enter setup mode. Safari and iPhone browsers are not supported by this setup path.

## Networking

| Deployment | Network setup |
| --- | --- |
| Home Assistant OS | The listeners run in Core’s host network. Allow the fan to reach the HA machine on the three configured TCP ports. No add-on port mapping is involved. |
| HA Container, host network | Use the Docker host’s LAN address. The listeners bind directly on that host. |
| HA Container, bridge network | Publish all three TCP ports **with identical inside/outside port numbers**, and advertise the host’s LAN address. For the defaults: `8080:8080`, `9443:9443`, `9883:9883`. |
| Separate IoT VLAN | Permit fan → HA on those ports and normal Wi-Fi/DHCP access. Browser and fan must be within Bluetooth range during setup. |

HA’s normal UI can remain on HTTP port 8123. The HTTPS provisioning website sends settings over Bluetooth, then navigates back to HA’s frontend using a separate, one-use return token. Top-level navigation also works when HA uses HTTP; no browser fetch to HA, CORS, local-network browser permission, reverse proxy, or HA login token is needed. The return token only resumes the setup dialog; authenticated MQTT and the initialization reply determine success. Do not embed it under an HTTP HA page in an iframe.

The fan’s CA bootstrap intentionally uses HTTP, matching the device protocol. Certificate enrollment and private-key downloads use TLS; MQTT additionally requires the enrolled device certificate. Keep these listeners on your trusted LAN, without Internet port forwarding. The old firmware requires compatibility with TLS 1.2 / `AES128-SHA256`.

## Serve the provisioning page

The setup page is versioned by setup-link format. The integration appends `v1/` to the configured page URL, so each installed release opens a page that understands its links. An incompatible change to the link gets a new directory (`web/v2/`), and the old one stays published for people who have not updated.

To host it yourself, publish **`web/`** to a trusted HTTPS static host and enter that URL, without the `v1/`, in the integration’s advanced settings. The included GitHub Pages workflow deploys on each release, or manually:

1. Enable GitHub Pages with **GitHub Actions** as its source.
2. Run **Actions → Provisioning page → Run workflow**.

The workflow also keeps the 0.4.2 page at the site root, which releases up to 0.4.2 open.

The static site has no backend. Anyone can host the code, but the site operator controls JavaScript that sees the enrollment token and Wi-Fi password. Use a deployment you trust; no third-party scripts are included.

For a completely local setup page on the nearby computer:

```sh
python3 -m http.server 18765 --bind 127.0.0.1 --directory web
```

Set the integration’s provisioning URL to `http://localhost:18765/`, then open its generated setup link in Chrome **on that computer**. Loopback is a secure-context exception; a plain HTTP LAN address is not. All web assets are included, so this option also works without Internet access.

## Storage and lifecycle

Credentials are stored under `/config/.storage/coway_local/` with private file permissions. Back up this directory together with HA’s config entries. Losing the CA or device credentials requires restoring that backup or provisioning the fan again. 

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

- Other models can be tried, but the server uses the AP-1022K control and telemetry mappings and MQTT service code `002AIR007`. A fan that completes Bluetooth setup is not necessarily compatible with them.
- PM10, other air-quality metrics, filter notification flags, firmware updates, and AWS shadow synchronization are not implemented. The broker accepts the observed shadow/FOTA subscriptions but does not provide those services.
- Wi-Fi association failure: use a 2.4 GHz network compatible with the fan, re-enter setup mode, and check the password.
- Certificate or broker failure: check the advertised LAN IP, the three ports, routing/VLAN isolation, and HA logs. Keep the short HTTPS download URLs intact.
- HA setup retrying: commonly a port conflict or unreadable credential storage. Other integrations keep running.
- Controls unavailable: check the connection sensor, fan power, and listener reachability. Restarting the integration should not require provisioning again.

This integration is independent of the Coway IoCare cloud integration. Provisioning to this server replaces the fan’s cloud destination; the original mobile app is not the controller for this local configuration.

## Development

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest -q
.venv/bin/ruff check .
node --test tests/web.test.mjs
.venv/bin/python scripts/package.py
```

The Python tests run the service and a real Home Assistant instance against loopback HTTP, TLS, and MQTT sockets with temporary credentials. No test needs a fan. To try the wizard with a simulated Bluetooth fan, run `python tests/browser/serve.py` and open `http://localhost:18765/preview`.

## Tested hardware

One AP-1022K (MCU firmware `V1.0.0.1`, Wi-Fi firmware `000011`), enrolled from Chrome on macOS into Home Assistant OS 18.3 with Core 2026.10.2. Enrollment, control, telemetry, and reconnecting after an HA restart work on that fan. Other models, other firmware, and HA Container networking have not been tested on hardware.

aMQTT is pinned to **0.12.1** because the adapter overrides private broker hooks. Re-run wire and HA compatibility tests before changing that pin.

MIT licensed. The broker adapter includes behavior adapted from aMQTT; its copyright and license are preserved in `LICENSE.amqtt`. This project is not affiliated with Coway or an official Home Assistant integration.

Packaging follows the [HACS integration layout](https://www.hacs.xyz/docs/publish/integration/); the static deployment follows [GitHub Pages’ Actions workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
