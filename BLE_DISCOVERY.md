# Bluetooth discovery evidence

Examined Coway IoCare Android **2.28.0**, APK SHA-256
`4afaba9fa063ccd278ce688f1bb94616b932addf60db436ad0d8cc5d22ee0539`.
These findings describe the app's normal BLE registration path. Tuya and legacy
mattress paths also exist and are outside this integration's protocol.

## What the app does

1. `DefaultDeviceRegistrationBleDataSource.r()` starts scanning with an empty
   Android `ScanFilter`. Its scan callback requires a scan record, a nonempty
   device name and an acceptable connectability state.
2. `DefaultDeviceRegistrationBleRepository`, in the scan collector's
   `AnonymousClass2.invokeSuspend()`, parses manufacturer-specific advertisement
   data using these rules. Offsets exclude the two-byte manufacturer ID:

   | Manufacturer ID | Required layout | Product/material code |
   | --- | --- | --- |
   | `0x0639` (1593) | At least 7 bytes; byte 1 is `0x40` | Bytes 2–6, decoded from base 36 |
   | `0xFFFF` (65535) | At least 8 bytes | Bytes 3–7 decoded from base 36 if byte 2 is `0x40`; otherwise bytes 2–7 as text |

   The parser also extracts protocol/encryption information from the latter
   format. It gives the `0x0639` field priority when both IDs are present.
3. `FindTargetDeviceInfoUseCase.a()` matches the parsed material code against
   the locally stored product catalog for nearby discovery. Unknown products
   are dropped. The selected-model setup path uses the corresponding model list.
4. `SearchNearbyDevicesBottomSheetViewModel` adds only successfully resolved
   products to its displayed list, deduplicates them and caps it at ten devices.

There is no exact `AP-1022K` name filter in this normal-device discovery path.
The low-level scan is broad; manufacturer parsing and catalog matching narrow
the app's displayed results.

## Capture cross-check

The saved Android setup capture contained 68 distinct advertisers with
manufacturer data across nine manufacturer IDs. Only one matched the two
manufacturer layout rules above: the tested AP-1022K.

Its manufacturer ID is `0xFFFF`; the payload is
`00 16 31 31 33 34 33 39 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 C5`.
Bytes 2–7 identify material code `113439`. Its scan response also advertises
the FFC0, FFC1 and FFC3 services. Device addresses and name suffixes are omitted.

## Browser implementation

Chrome's `manufacturerData` filters support a company ID, byte prefix and mask
([Chrome documentation](https://developer.chrome.com/docs/capabilities/bluetooth#manufacturer_data_filter)).
The page expresses the two layout checks as alternative filters. Zero mask bits
allow any product code while retaining the minimum payload length. Service UUIDs
remain in `optionalServices`, so devices need not advertise them to appear.

This is a discovery hint, not authentication or a full copy of the app's catalog
filter. In particular, `0xFFFF` is not an exclusive Coway identifier, and an
unrelated device using it can still appear. A device advertising both IDs may
match either browser filter, unlike the app's priority rule. The browser does
not impose the app's nonempty-name or known-product restrictions. After
selection, the page still requires the expected GATT services/characteristics
and a valid identity response before enabling Wi-Fi provisioning.

No exact advertised name, product code or setup-bundle model label is required.
Other models remain experimental: the integration's server protocol mappings
are still based on the AP-1022K.
