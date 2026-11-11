# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-11

### Changed

- The integration has its own Blink login, with a PIN step when Blink asks for one,
  and its own Blink client. It no longer needs or reads the core Blink integration.
- Each Live entity sits on a device of its own, named "<camera> Live", instead of on
  the core Blink device.
- Entries from 0.1.0 ask for the Blink login once; the camera selection is kept.

### Added

- Reauthentication when Blink rejects the stored token. A Blink outage or lost
  connection retries instead of asking for a login.
- One entry per Blink account; adding the same account again is refused.
- A `live` attribute that is `true` while video reaches the viewer, so a dashboard can hide a "camera waking up" caption once the picture plays.

### Security

- Only Blink's tokens are stored; the password and PIN are never stored or logged.
- The live-view relay listens on `127.0.0.1` only and serves one viewer at a time.

## [0.1.0] - 2026-10-28

### Added

- A live-view camera entity for each selected Blink camera, attached to the
  device the core Blink integration created.
- An `online` attribute that reports whether Blink sees the camera as online.
- Camera selection in the setup dialog and in the integration's options.

[Unreleased]: https://github.com/Derinbay-Labs/ha-blink-live/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Derinbay-Labs/ha-blink-live/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Derinbay-Labs/ha-blink-live/releases/tag/v0.1.0
