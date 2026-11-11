---
status: accepted
date: 2026-11-11
decision-makers: architect
consulted: HACS reviewer (hacs/default#12859)
---

# blink_live owns its Blink login, client and devices

## Context and Problem Statement

`blink_live` v0.1.0 borrows the blinkpy client of the loaded core `blink` entry
(`entry.runtime_data.api`) and attaches its live-view entities to the core device
`("blink", serial)`. The HACS review (hacs/default#12859) rejected both: another integration's
runtime object is private, and entities must live on our own devices. Issue #8 tracks the change;
the plan is Derinbay-Labs/home-assistant#76.

Drivers: pass HACS review without core Blink internals; never break core Blink (same Python
environment, same account); hold the least credential material that works.

## Considered Options

1. **Own login**: own config flow, own blinkpy client per entry, own devices.
2. **Contribute live view to core Blink**, then retire `blink_live`.
3. **Keep borrowing** the core client and devices.

## Decision Outcome

Chosen option: **1, own login**, the only option that passes review on our timeline.
Option 2 is the better long-term home but slow and uncertain (blinkpy's local TCP relay may not
pass core review); option 3 means leaving HACS default.

### Login, client and devices (decided, recorded here)

- Config flow: email + password, then a 2FA PIN step, then camera selection. A reauth flow
  repeats email + password + PIN on an auth failure.
- `async_setup_entry` creates one blinkpy `Blink` client per entry and keeps it in
  `entry.runtime_data`. No lookup of, wait on, or import from the core `blink` entry.
- `manifest.json`: `"blink"` leaves `dependencies`; `blinkpy` joins `requirements`.
- Devices are fully separate: identifier `(blink_live, serial)`, no `via_device`, name
  `"<camera> Live"`. The reviewer did not answer the `via_device` question.

### blinkpy pin rule

`requirements` pins blinkpy with `==` to the exact version core's `blink` integration requires in
the current HA stable release. Two different pins in one environment conflict: whichever
integration installs last wins, which can break the other.

- Today: **`blinkpy==0.25.9`**, required by core in 2026.11.1 (current stable, manifest line 26)
  and equally in 2026.10.0, 2026.10.4, 2026.11.0 and `dev`; it is blinkpy's latest release.
- The pin moves only with core's, in the release that raises `hacs.json` `homeassistant` to the
  first HA version with the new pin. Renovate PRs for blinkpy are not merged on their own.

### What the config entry stores

blinkpy `Auth(login_data, no_prompt=True, session=..., callback=...)` loads its state from
`login_data`, and `Auth.login_attributes` returns that dict with the token fields written back.
The refresh grant posts only `username` and `refresh_token` (api.py lines 144-149), so a stored
password is not needed to stay logged in.

- `entry.data` holds an allow-listed copy of `login_attributes`: `username`, `token`,
  `expires_in`, `expiration_date`, `refresh_token`, `host`, `region_id`, `client_id`,
  `account_id`, `user_id`, `hardware_id`, `uid`, `device_id`. **Never the password** (core Blink
  does store it; we do not copy that). `login_attributes` returns `Auth.data` itself, which
  contains the password during login, so the copy is built from the named keys only.
- `hardware_id` is minted by blinkpy for our entry (a UUID), persisted, and reused on reauth.
  It is never copied from core's entry, so Blink sees two distinct clients.
- Camera selection stays in `entry.options`.
- Token persistence: `entry.data` is written (a) after the 2FA step completes, (b) after setup's
  token startup, and (c) from the `Auth` callback, which blinkpy fires only after a refresh on
  the request path (auth.py lines 262-270). A token write never reloads the entry: the update
  listener reloads only when `options` change, or a refresh would cut a running live view.
- No password means blinkpy's fallback must not run. `Auth.startup()` falls through to the full
  OAuth sign-in when the refresh fails (auth.py lines 186-209), and that sign-in posts
  `self.data["password"]` (lines 328-332), which would send `None` to Blink on an account core
  also uses. When the refresh fails, setup raises `ConfigEntryAuthFailed` (start reauth) and
  never calls the sign-in without a password. Any blinkpy auth failure at runtime also starts
  reauth.
- Credentials and tokens are never logged; the flow's password field is a secret.

### Two sessions on one Blink account

Core Blink and `blink_live` hold separate OAuth sessions (distinct `hardware_id`, separate
refresh-token chains) on one account. Nothing in blinkpy's code shows whether Blink invalidates
one client's tokens when the other logs in or refreshes; **this risk is unknown until verified.**
As a precaution `blink_live` uses its own aiohttp session (`async_create_clientsession`) so its
OAuth cookies never mix with core's shared session.

### Consequences

- Good: no dependency on core Blink internals or devices; no password at rest in our entry.
- Bad: the user logs in twice and confirms a second 2FA PIN; each camera shows as two devices.
- Bad: a lost refresh token always means reauth with PIN (core can retry with its stored
  password); the blinkpy pin must follow core release by release.
- If the real-account check shows the sessions invalidate each other, a new ADR supersedes this.

### Confirmation

Tests (`tests/`, mocked blinkpy):

- Config flow: credentials, 2FA PIN, wrong PIN, invalid auth, cannot connect, reauth, abort on an
  already configured account.
- The created and refreshed `entry.data` never contains `password` and holds only the allowed keys.
- A token write through the `Auth` callback updates `entry.data` without reloading the entry.
- A failed refresh at setup raises `ConfigEntryAuthFailed` and never calls the sign-in.
- Setup succeeds with no core `blink` entry; devices use `(blink_live, serial)`, no `via_device`.
- The manifest's blinkpy pin equals the requirement in the installed HA's `blink` manifest.

Real account, with core Blink logged in on the same account throughout:

1. Set up `blink_live` with 2FA; core Blink must not need reauth.
2. Leave both running for at least 24 h, spanning several token expiries on both sides; record
   the observed `expires_in`. Neither entry may enter reauth.
3. Restart HA; then reload each entry on its own. Both come back without reauth.
4. Reauth `blink_live` while core stays loaded; core stays working.
5. Start and stop a live view; it starts, streams and ends cleanly; core snapshots still update.

## More Information

- [Core Blink pin, HA 2026.11.1](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/blink/manifest.json#L26);
  [core stores `login_attributes` with password and persists via the callback](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/blink/__init__.py#L85-L114).
- blinkpy v0.25.9 `Auth`: [constructor and `login_attributes`](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L30-L92),
  [`startup`](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L186-L209),
  [refresh callback](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L262-L270),
  [sign-in reads the password](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/auth.py#L328-L332),
  [refresh grant without password](https://github.com/fronzbot/blinkpy/blob/v0.25.9/blinkpy/api.py#L144-L149),
  [releases (latest v0.25.9)](https://github.com/fronzbot/blinkpy/releases).
