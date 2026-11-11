# Threat model: blink_live own Blink login (v0.2.0)

Issue: Derinbay-Labs/ha-blink-live#8. Scope: config flow (email, password, 2FA PIN, reauth), token storage and
refresh in the config entry, a second blinkpy session beside core Blink, and the local live-view relay in
`camera.py` (`_join_live` / `_serve`). Single-user, local HA; the repo is public, so anyone can install it.

## Assets and trust boundaries
- Blink account password and OAuth tokens (full account control: cameras, video, arm state).
- Live video served on a local TCP port; HA config entry store; HA logs and diagnostics downloads (often
  pasted into public issues).
- Boundaries: HA to Blink cloud (HTTPS); HA to other local processes/add-ons (shared loopback).

## Evidence (upstream behaviour)
- blinkpy `Auth.login_attributes` returns token, refresh token, host, region, client/account/user id and
  `hardware_id`; `self.data` may also hold `username`/`password` if the caller supplied them.
  https://github.com/fronzbot/blinkpy/blob/dev/blinkpy/auth.py
- `startup()` tries `oauth_refresh_token()` first, falls back to a full username+password login, and logs the
  refresh error only at debug level. A 2FA challenge raises `BlinkTwoFARequiredError`, finished by
  `complete_2fa_login()`. `hardware_id` is a random UUID unless supplied, so persisting it is what makes the
  client a stable device. Same file.
- blinkpy logs raw response bodies in two paths (malformed login response, content-type mismatch in
  `validate_response`), which can contain tokens. Same file.
- Core Blink stores `login_attributes` (with username/password) as entry data, does not store the PIN, uses
  username as `unique_id`, and reuses `hardware_id` on reauth.
  https://github.com/home-assistant/core/blob/dev/homeassistant/components/blink/config_flow.py

## Threats (STRIDE) and mitigations

| # | Threat | Cat. | Mitigation (developer) | Proof |
|---|---|---|---|---|
| T1 | Password/tokens leaked in logs, diagnostics, issue reports (our code or blinkpy raw-response logging) | I | Never log credentials, PIN, tokens or `login_attributes`; log only the exception class. No diagnostics platform, or if added `async_redact_data` on username, password, token, refresh_token, hardware_id, account_id, user_id, host. Never enable debug for `blinkpy` by default. | Test: full flow with sentinel password/token under `caplog` at DEBUG; sentinel absent from all records. |
| T2 | Password persisted needlessly in the entry store (plain JSON on disk, in backups) | I | Do not store the password or PIN. Persist only what refresh needs (`refresh_token`, `hardware_id`, host/region/ids from `login_attributes`, plus username as unique id). On refresh failure raise `ConfigEntryAuthFailed` to start reauth instead of silently re-logging in. | Test: `entry.data` has no `password`/`pin` key and no sentinel value. |
| T3 | Secrets echoed or retained in flow state | I/S | Password field uses a password selector, PIN a numeric text field; neither is a default or echoed on error. Drop the password from the flow object once 2FA completes. A repeated `BlinkTwoFARequiredError` ends the step with an error, no auto-retry. | Test: error re-render has no password/pin in suggested values; flow attributes cleared after create_entry. |
| T4 | Reauth abuse / account confusion: reauth or a new flow accepts a different account and overwrites the entry, or a duplicate entry spawns two sessions | S/T | `unique_id` = lower-cased username. Reauth: `async_set_unique_id` then `_abort_if_unique_id_mismatch(reason="wrong_account")`; new entry: `_abort_if_unique_id_configured()`. Reauth updates tokens only, never camera selection. | Tests: other username aborts `wrong_account`; second add aborts `already_configured`. |
| T5 | Brute force / lockout: repeated bad logins or PIN attempts trip Blink rate limits | D | Map errors to fixed keys (`invalid_auth`, `cannot_connect`, `unknown`); no background re-login loops; a failed refresh yields one reauth request, not repeated logins. | Test: refresh failure gives exactly one `ConfigEntryAuthFailed` and zero further login calls. |
| T6 | Two sessions interfere: our login invalidates core Blink tokens (or reverse), or both share one `hardware_id` | D/T | Never read core entry data or its `hardware_id`; generate our own UUID once and persist it. Pin `blinkpy` to the exact version core ships. Persist refreshed tokens (T7). README notes Blink may list us as an extra device. Whether Blink invalidates the other session is not documented upstream, so it must be proven on the real account. | Real-account check (plan step 7) across a token-expiry cycle: neither integration asks for reauth. Unit test: our `hardware_id` differs from the core fixture. |
| T7 | Refreshed tokens not persisted, so a restart forces full login and 2FA | D | Use blinkpy refresh callback to `async_update_entry` with new `login_attributes` minus credentials. | Test: simulated refresh updates `entry.data`; restart uses the refresh path, not password login. |
| T8 | Any local process/add-on connects to the relay port, gets live video or forces a Blink live session | I/D | Keep bind to `127.0.0.1` port 0, never `0.0.0.0` or a hostname. One viewer at a time; extra connections are closed. Close listener and live session on entity removal and when the viewer leaves. Do not log the port at INFO. Residual: other loopback processes can reach it. | Test: listener host is `127.0.0.1`; second concurrent client is closed; removal closes the listener. |
| T9 | Relay spoofing/tampering: upstream address is not what blinkpy returned | S/T | Connect upstream only to the address from `live.socket.getsockname()`; never from user input. Relay forwards bytes only, no parsing of client data. | Test: `_join_live` connects only to the live object address. |
| T10 | Vulnerable or malicious dependency (public HACS repo) | T | Exact `blinkpy` pin in manifest as the only requirement; lockfile committed; Renovate on. | CI audit green; manifest has one requirement. |
| T11 | Repudiation: user cannot tell which sessions or changes occurred | R | INFO logs without secrets: entry setup, reauth started, live view start/stop with entity id. | Shared with T1 test: records present, secrets absent. |
| T12 | Privilege escalation via new services | E | No new services in v0.2.0; HA auth guards the stream endpoints. | Inspection: no entity service registered in the diff. |

## Residual risks (accepted)
- Refresh token is plain JSON in HA storage, same as core Blink; whoever can read HA config owns the Blink account.
- Loopback relay is reachable by other local processes (T8).
- Blink may treat the second login as a new device and notify by email.

## Must for v0.2.0
1. No password, PIN or token in logs or diagnostics; DEBUG `caplog` sentinel test passes (T1, T11).
2. Entry data holds no password or PIN; refresh failure raises `ConfigEntryAuthFailed` and starts reauth, no silent password re-login (T2, T5).
3. `unique_id` = lower-cased username; reauth aborts `wrong_account` on a different account; duplicate add aborts `already_configured` (T4).
4. Own persisted `hardware_id` (never core's); `blinkpy` pinned to core's version; refresh callback persists tokens; real-account two-session check recorded in the PR (T6, T7).
5. Relay binds `127.0.0.1` only, serves one viewer at a time, and closes on removal or when the viewer leaves (T8, T9).
6. Password field uses a password selector; nothing secret is echoed or kept in flow state after completion (T3).
