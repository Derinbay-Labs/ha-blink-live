# Blink Live View for Home Assistant

[![Validate](https://github.com/Derinbay-Labs/ha-blink-live/actions/workflows/validate.yml/badge.svg)](https://github.com/Derinbay-Labs/ha-blink-live/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/Derinbay-Labs/ha-blink-live)](https://github.com/Derinbay-Labs/ha-blink-live/releases)
[![HACS](https://img.shields.io/badge/HACS-custom-41BDF5)](https://hacs.xyz/docs/faq/custom_repositories/)

The [Blink integration](https://www.home-assistant.io/integrations/blink/) that ships
with Home Assistant shows the last snapshot a camera took. The Blink app can also open
a live view. This integration brings that live view into Home Assistant: for each
camera you pick, it adds a **Live** camera entity that streams video when you open it.

It does not replace the core integration and does not need it. It has its own Blink
login and its own Blink client, and puts each Live entity on a device of its own. You
can run it next to the core integration or without it.

## Requirements

- Home Assistant 2026.10 or newer. Older releases are untested.
- A Blink account: its email and password, and access to the email or phone that
  receives Blink's PIN.
- No Blink subscription is needed. Live view works on the free plan, as it does in
  the app.

## Installation

### HACS

[![Open your Home Assistant instance and add this repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Derinbay-Labs&repository=ha-blink-live&category=integration)

The button adds the repository to HACS (to the Marketplace on Home Assistant 2026.11
and later). To do it by hand:

1. Open HACS, then the menu in the top right corner, then **Custom repositories**.
2. Add `https://github.com/Derinbay-Labs/ha-blink-live` with the type **Integration**.
3. Search for **Blink Live View**, download it, and restart Home Assistant.

### Manual

Copy `custom_components/blink_live` from the
[latest release](https://github.com/Derinbay-Labs/ha-blink-live/releases/latest) into the
`custom_components` folder of your Home Assistant configuration, then restart.

## Configuration

1. Go to **Settings > Devices & services > Add integration** and choose
   **Blink Live View**.
2. Enter the email and password of your Blink account.
3. If Blink sends a PIN by email or text, enter it.
4. Select the cameras that should get a live view, then submit.

To change the selection later, open the integration and choose **Configure**. One
entry covers every camera on a Blink account; the same account cannot be added twice.

### The separate login

This integration signs in to Blink on its own, even if the core Blink integration is
already set up with the same account. Blink sees it as one more signed-in device, the
way it sees a second phone with the Blink app, and may send a PIN for it.

The password is used for that sign-in only. Home Assistant stores the tokens Blink
returns, never the password or the PIN. When Blink rejects the stored token, Home
Assistant shows a **Reauthenticate** notice: enter the password (and the PIN, if Blink
asks) again. A Blink outage or a lost connection does not ask for a login; the
integration retries on its own.

Upgrading from 0.1.0, which borrowed the core integration's login, asks for this login
once. The camera selection is kept.

## Usage

Each selected camera gets an entity named after it, such as
`camera.front_door_live`, on a device of its own named after the camera, such as
**Front door Live**. If the core Blink integration is set up too, each camera then
appears as two devices: the core one and the Live one. Open the entity from the
more-info dialog or a dashboard card; the live view starts when the stream starts and
ends when you close it.

The entity's thumbnail is Blink's last snapshot, the same image the core camera
entity shows. Rendering a dashboard never wakes a camera.

### Attributes

| Attribute | Values | Meaning |
|-----------|--------|---------|
| `online`  | `true`, `false`, `null` | Whether Blink reports the camera as online. `null` means Blink sent no status. |

Blink refreshes this status about every five minutes. A camera that is offline cannot
start a live view, so the attribute is useful for marking such cameras on a
dashboard, for example with a template condition:

```yaml
{{ state_attr('camera.front_door_live', 'online') == false }}
```

## How it works

blinkpy, the library the core integration uses, can open the same live view the app
does: a TLS connection to Blink that carries an MPEG-TS video stream. Each Live entity
listens on a local port (`127.0.0.1`) and gives that address to Home Assistant as its
stream source. Nothing happens until a viewer connects to that port. Then the entity
asks Blink for a live view and relays the stream to the viewer; when the viewer
disconnects, the live view ends. The relay serves one viewer at a time, which is how
Home Assistant's stream component reads it.

Because the stream source is only an address, Home Assistant can look it up at
startup and whenever it likes without starting a live view or using any battery.

## Limitations

- **Live views are short.** Blink ends each live view after about 45 seconds, as the
  app does. Open the camera again for another one.
- **Battery.** Every live view wakes the camera. Battery-powered cameras that are
  opened often will drain faster, exactly as they would from the app.
- **The stream is only reachable on the Home Assistant host.** The relay listens on
  `127.0.0.1`. The go2rtc server built into Home Assistant can read it; a go2rtc or
  NVR running on another machine cannot.
- **Unofficial API.** Blink does not publish an API. This integration uses blinkpy,
  pinned to the version the core integration ships, so a Blink-side change can break
  live view until blinkpy and Home Assistant catch up.
- **Thumbnails are Blink's last snapshot.** They update about every five minutes when
  the integration refreshes, not while a live view is running.

## Troubleshooting

**The login fails with "The email or password is wrong".** Check the account in the Blink
app. The integration does not use the core Blink integration's login, so it needs the
account password even when core Blink is already set up.

**Home Assistant asks to reauthenticate.** Blink rejected the stored token, for
example after a password change or after signing out all devices in the Blink app.
Enter the password again.

**A camera opens but shows no video.** Check the `online` attribute. If it is
`false`, the camera is offline in the Blink app too. If it is `true`, enable debug
logging, open the camera once, and include the log in your issue:

```yaml
logger:
  logs:
    custom_components.blink_live: debug
```

Do not enable debug logging for `blinkpy` itself unless asked. Its log lines contain
your Blink account, network and camera identifiers; remove them before posting.

## Disclaimer

This project is not affiliated with, endorsed by or supported by Blink, Amazon or the
Home Assistant project. Blink is a trademark of Amazon Technologies, Inc.

## License

[MIT](LICENSE)
