# Coway Local

A single Home Assistant custom integration for local control of the **Coway AP-1022K**. It hosts the certificate service and TLS MQTT broker inside Home Assistant. Initial Wi-Fi setup uses a nearby Mac or Android device running Chrome and Web Bluetooth.

No add-on, external MQTT integration, Raspberry Pi, or Bluetooth adapter on the HA host is required. After enrollment, the fan connects directly to HA over your LAN. The Coway cloud and provisioning website are not needed for ongoing control.

This is an experimental implementation of the observed **FFC0 / P001 / P002** protocol. Other models and firmware are not yet supported.

## Included

- Fan entity: power, three manual speeds, smart and sleep modes.
- Select entities: lighting levels 1–4, timer, smart sensitivity, pre-filter cleaning cycle.
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
2. Enter the serial number from the fan’s product label and a friendly name. BLE exposes the model and MAC address, but not the serial number.
3. Open the generated **Bluetooth setup** link in a **new Chrome tab** on a nearby Mac or Android device. Keep the HA setup dialog open.
4. Put the fan in Wi-Fi/Bluetooth setup mode and close the Coway app.
5. Choose the `AP-1022K_...` device, then select a 2.4 GHz Wi-Fi network from the fan’s scan. Enter its Wi-Fi password and start setup.
6. When the page says the fan reports connected, return to HA and press **Submit**. HA confirms the fan’s authenticated MQTT connection.

The setup link expires after 15 minutes and is revoked when canceled or completed. If it expires or the fan exits setup mode, generate a new link and re-enter setup mode. Safari and iPhone browsers are not supported by this setup path.

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

- "Last seen" changes on every MQTT message. It is disabled by default to avoid filling Activity and the recorder with routine timestamps. Enable it in the entity settings only when needed for troubleshooting. For installations created before v0.1.2, disable the existing Last seen entity manually; upgrading preserves your entity preferences. The Connection sensor remains enabled. Disabling Last seen stops new updates but does not delete historical entries.
- Tested on one AP-1022K, MCU firmware `V1.0.0.1`, Wi-Fi firmware `000011`. Do not assume other Coway devices use this protocol.
- The pre-filter cycle is known after its setting is acknowledged; it may initially show unknown after an HA restart.
- Air-quality readings, filter life, firmware updates, and AWS shadow synchronization are not implemented. The broker accepts the observed shadow/FOTA subscriptions but does not provide those services.
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

Tests use temporary credentials and real loopback HTTP/TLS/MQTT sockets. They cover enrollment expiry, credential isolation, MQTT acknowledgements and reserved topics, device impersonation, persistence, reconnect, configuration validation, and real HA flows/entities/services/reload. Browser codec tests use an independent fixed protocol fixture. No test requires a real fan.

Hardware checks confirmed status queries, speed changes, power off/on, and automatic reconnect with this service. A fresh enrollment from the published HTTPS page into HAOS also passed, using ports 8080, 9443, and 9883. HA created all eight entities, controlled the fan, and continued receiving fresh status after the old laptop services stopped. See `VALIDATION.md` for the tested versions and limits.

aMQTT is pinned to **0.12.1** because the adapter overrides private broker hooks. Re-run wire and HA compatibility tests before changing that pin.

MIT licensed. The broker adapter includes behavior adapted from aMQTT; its copyright and license are preserved in `LICENSE.amqtt`. This project is not affiliated with Coway or an official Home Assistant integration.

Packaging follows the [HACS integration layout](https://www.hacs.xyz/docs/publish/integration/); the static deployment follows [GitHub Pages’ Actions workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
