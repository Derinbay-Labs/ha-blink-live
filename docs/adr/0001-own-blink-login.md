---
status: accepted
date: 2026-11-11
decision-makers: architect
consulted: HACS reviewer (hacs/default#12859)
---

# blink_live owns its Blink login, client and devices

## Context and Problem Statement

`blink_live` v0.1.0 borrows the core `blink` entry's client (`entry.runtime_data.api`) and
attaches its entities to the core device `("blink", serial)`. The HACS review
(hacs/default#12859) rejected both. Issue #8; plan in Derinbay-Labs/home-assistant#76. Drivers:
no core Blink internals; never break core Blink (same environment and account); least
credential material.

## Considered Options

1. **Own login**: own config flow, own blinkpy client per entry, own devices.
2. **Contribute live view to core Blink**, then retire `blink_live`.
3. **Keep borrowing** the core client and devices.

## Decision Outcome

Chosen option: **1, own login**, the only option that passes review on our timeline.
Option 2 is the better long-term home but slow and uncertain (blinkpy's local TCP relay may not
pass core review); option 3 means leaving HACS default.

### Login, client and devices (decided, recorded here)

- Config flow: email + password, 2FA PIN, camera selection; reauth repeats login and PIN.
- One blinkpy `Blink` client per entry in `entry.runtime_data`; nothing from the core entry.
- `manifest.json`: `"blink"` leaves `dependencies`; `blinkpy` joins `requirements`.
- Devices are fully separate: identifier `(blink_live, serial)`, no `via_device`, name
  `"<camera> Live"`. The reviewer did not answer the `via_device` question.

### blinkpy pin rule

`requirements` sets blinkpy's minimum with `>=` to the exact version core's `blink` integration
requires in the current HA stable release. hassfest rejects an `==` pin on a package Home
Assistant itself depends on. With `>=`, the blinkpy already installed for core (Home Assistant's
images ship it, and core `blink` installs its exact pin) satisfies the requirement and is kept, so
both integrations run the same blinkpy; a newer blinkpy is installed only where none is present.

- Today: **`blinkpy>=0.25.9`**; core requires `blinkpy==0.25.9` in 2026.11.1 (current stable,
  manifest line 26) and equally in 2026.10.0, 2026.10.4, 2026.11.0 and `dev`; it is blinkpy's
  latest release.
- The minimum moves only with core's pin, in the release that raises `hacs.json` `homeassistant`
  to the first HA version with the new pin. Renovate PRs for blinkpy are not merged on their own.

### What the config entry stores

blinkpy `Auth(login_data, ...)` loads its state from `login_data`; both refresh paths post only
the refresh token (api.py lines 144-149 and 1030+), so no password is needed to stay logged in.

- `entry.data` holds an allow-listed copy of `login_attributes`: `username`, `token`,
  `expires_in`, `expiration_date`, `refresh_token`, `host`, `region_id`, `client_id`,
  `account_id`, `user_id`, `hardware_id`, `uid`, `device_id`. **Never the password** (core
  stores it). `login_attributes` returns `Auth.data` itself, which holds the password during
  login, so the copy is built from the named keys. Camera selection stays in `entry.options`.
- `hardware_id` is minted by blinkpy for our entry, persisted, reused on reauth, never copied
  from core's entry, so Blink sees two distinct clients.
- Token persistence: `entry.data` is written (a) after the 2FA step completes, (b) after setup's
  token startup, and (c) from the `Auth` callback, which blinkpy fires only after a refresh on
  the request path (auth.py lines 262-270). A token write never reloads the entry: the update
  listener reloads only when `options` change, or a refresh would cut a running live view.
- blinkpy's password fallback never runs. `Auth.startup()` swallows a failed refresh and falls
  through to the full sign-in (auth.py lines 186-209), which posts `self.data["password"]`
  (lines 328-332), here `None`, on an account core also uses. blinkpy cannot tell a rejected
  token from an outage, so `blink_live` refreshes itself and classifies the failure:
  - token rejected by Blink (401/400 on the refresh): `ConfigEntryAuthFailed`, start reauth;
  - connection error, timeout or 5xx: `ConfigEntryNotReady` at setup, retry at runtime, no reauth.
- Credentials and tokens are never logged; the flow's password field is a secret.

### Two sessions on one Blink account

Core and `blink_live` hold separate OAuth sessions (distinct `hardware_id` and refresh tokens).
Whether Blink invalidates one client's tokens when the other logs in or refreshes is **unknown
until verified**. As a precaution `blink_live` uses its own aiohttp session
(`async_create_clientsession`), so its OAuth cookies never mix with core's shared session.

### Consequences

- Good: no dependency on core Blink internals or devices; no password at rest in our entry.
- Bad: the user logs in twice and confirms a second 2FA PIN; each camera shows as two devices.
- Bad: a lost refresh token always means reauth with PIN (core can retry with its stored
  password); the blinkpy minimum must follow core's pin release by release.
- If the real-account check shows the sessions invalidate each other, a new ADR supersedes this.

### Confirmation

Tests (`tests/`, mocked blinkpy):

- Config flow: credentials, 2FA PIN, wrong PIN, invalid auth, cannot connect, reauth; reauth
  with a different account aborts.
- The created and refreshed `entry.data` never contains `password` and holds only the allowed keys.
- A token write through the `Auth` callback updates `entry.data` without reloading the entry.
- A rejected refresh raises `ConfigEntryAuthFailed`; a connection error or 5xx raises
  `ConfigEntryNotReady`; neither calls the sign-in.
- Setup succeeds with no core `blink` entry; devices use `(blink_live, serial)`, no `via_device`.
- The manifest's blinkpy minimum equals the `==` requirement in the installed HA's `blink`
  manifest.

Real account, with core Blink logged in on the same account throughout:

1. Set up `blink_live` with 2FA; core Blink must not need reauth.
2. Leave both running for at least 24 h, spanning several token expiries on both sides; record
   the observed `expires_in`. Neither entry may enter reauth.
3. Restart HA; then reload each entry on its own. Both come back without reauth.
4. Reauth `blink_live` while core stays loaded; core stays working.
5. Start and stop a live view; it starts, streams and ends cleanly; core snapshots still update.

## More Information

- [Core Blink pin, HA 2026.11.1](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/blink/manifest.json#L26);
  [core persists via the callback](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/blink/__init__.py#L85-L114),
  [stores the password](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/blink/config_flow.py#L170-L233).
- blinkpy v0.25.9 `Auth`: [constructor and `login_attributes`](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L30-L92),
  [`startup`](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L186-L209),
  [refresh callback](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L262-L270),
  [sign-in reads the password](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L328-L332),
  refresh without password: [request path](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/api.py#L144-L149),
  [startup path](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/api.py#L1030-L1062),
  [releases (latest v0.25.9)](https://github.com/fronzbot/blinkpy/releases).
