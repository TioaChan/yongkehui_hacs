# YongKeHui HACS Repository Notes

This repository contains a Home Assistant HACS custom integration for 永客会.
Use this file as the handoff note when continuing in a new Codex session.

## Project Layout

- HACS repo root: this directory
- Integration code: `custom_components/yongkehui`
- API package: `custom_components/yongkehui/api`
- Local HA debug environment: `dev/ha_debug`
- Reference Spring project: local `yongkehui_door_unlocker` project, not committed
- Packet captures inspected: local capture exports, not committed
- IPA inspected: local YongKeHui app IPA, not committed

The source of truth is this repository. Do not edit a sibling or workspace-level
`custom_components` directory if one appears later.

## Git State

The HACS repo is a standalone git repository.

Remote:

```bash
git remote -v
```

Expected origin:

```text
<your git remote URL>
```

Recent commits:

```text
7b4f759 Update branding and lock identifiers
1a3beca Add handoff docs and HA debug setup
6f739bc Update YongKeHui API flow
eab3164 Initial YongKeHui HACS integration
```

In this Codex desktop environment, git commands that write `.git` may need
`sandbox_permissions: require_escalated`, especially `git add`, `git commit`,
and `git push`.

## Implemented Behavior

- Chinese integration name: `永客会`
- Domain: `yongkehui`
- Exposes Home Assistant `LockEntity` for each YongKeHui door.
- Unlock calls the YongKeHui open-door API and marks the HA lock as unlocked.
- The lock automatically returns to locked state after 5 seconds.
- HA integration brand assets live under `custom_components/yongkehui/brand/`;
  the brands component checks this directory via `Integration.has_branding`.
  The repository root `icon.png` is kept for HACS/repository display.
- HACS dashboard rows for integrations render icons with Home Assistant
  `brandsUrl(domain)`. Before the integration is installed, that generally means
  HACS can only show a store-list icon if the domain exists in the
  `home-assistant/brands` data. The local `brand/` images are picked up after
  HACS downloads the integration into `custom_components` and Home Assistant is
  restarted. README keeps a logo image so the HACS repository detail page still
  renders a picture from this repository.
- `deviceid` is generated once during config flow and persisted in the config entry.
- `communityid` is not sent during login, captcha, or profile calls.
- `communityid` is only sent after house selection, for door list and unlock calls.
- Token/session refresh calls the user profile endpoint every 6 hours to extend
  the existing login state.
- API request logs are centralized in
  `custom_components/yongkehui/api/transport.py`
  `YongKeHuiTransport.async_json_request()`: successful calls log at debug
  level, while HTTP/network, JSON parse, and non-zero API `code` failures log at
  warning level. Do not log passwords, cookies, captcha text, random tokens, or
  full request/response bodies.
- API failures that log at warning level also create or update a Home Assistant
  persistent notification via `custom_components/yongkehui/notifications.py`.
  Notification IDs are keyed by method and endpoint to avoid spamming multiple
  notifications for repeated failures of the same API.
- Login API codes `20010` and `20020` are expected captcha-required responses,
  so transport logs them at debug level with outcome `requires_action`.
- The RSA public key parsed from `sg-rsa.js` is intentionally logged at info
  level because it is public material and useful for field verification.
- During config flow, the API client that already fetched `doorList` is held in
  `hass.data[DOMAIN]["pending_apis"]` and reused by `async_setup_entry`. This
  avoids an immediate duplicate `profile -> doorList` round when the entry is
  created. A normal HA restart still constructs a fresh API client and performs
  the initial refresh.

## API Flow

Configuration flow:

1. User enters username and password.
2. Integration generates a persistent `deviceid`.
3. Password is transformed as the app does:
   `Base64(password)` then RSA PKCS#1 v1.5 encrypt-long.
4. POST `/authc-restapi/v1/user/auth/login`.
5. If API returns `20010` or `20020`, fetch captcha:
   GET `/authc-restapi/v1/auth/code/getImgCode`.
6. Show captcha form in HA.
7. Retry login with `imgCode` and `randomToken`.
8. GET `/uhomecp-sso/v3/userApp/profile`.
9. Extract `houseList` and ask the user to choose a house/community.
10. Persist selected `communityId`, `custId`, `userId`, house name, cookies, and device id.
11. Fetch doors with GET `/door-restapi/v1/userapp/doorList`.
12. Expose each returned door as an HA `LockEntity`.
    - Entity default name is `name_flagName` from the doorList payload, for
      example `南门_大门门禁`.
    - Entity unique id and device identifier are `communityId.doorId`, for
      example `12940241.123456`.

Unlock flow:

1. POST `/door-restapi/v1/userapp/opendoor/submit.json`.
2. JSON body includes `custId`, `communityId`, `userId`, `doorId`, `doorIdStr`,
   `appType: "2"`, and `appVersion: "1.3.0"`.
3. On failure it retries the same unlock request 1 time.

Scheduled login-state refresh flow:

1. Every 6 hours, GET `/uhomecp-sso/v3/userApp/profile` with current cookies.
2. Store any returned cookies in memory.
3. Return the already discovered door list to Home Assistant.

## RSA Public Key Finding

The integration fetches `https://www.uhomecp.com/web/sassLogin/lib/sg-rsa.js`
before full login and parses the first long Base64 string that validates as a
DER RSA public key. If the fetch or parse fails, it falls back to the bundled
key below. The web JS and IPA have historically contained the same RSA public
key. The IPA does not store it as plain `MIGf...` text. It is stored as
XOR-obfuscated data in the main binary.

When re-checking the key from an IPA, use the IPA only as local reference
material. Do not commit the IPA, extracted app bundle, binary dumps, packet
captures, or account data.

Recommended reverse trail:

1. Extract the IPA as a zip archive and inspect `Payload/*.app`.
2. First search plain resources and strings:
   `rg -a "sg-rsa|jsencrypt|MIGf|BEGIN PUBLIC KEY|setPublicKey|encryptLong" Payload`
   and `strings -a Payload/*.app/* | rg "RSA|MIGf|setPublicKey|encryptLong"`.
3. If no plain key appears, open the main Mach-O binary in Hopper, Ghidra, or
   IDA and search Objective-C selectors/classes around RSA setup. Useful terms
   from the inspected app are `SEGEncryptManager` and `setPublicKey:`.
4. Follow cross references from the public-key setter back to the call site.
   Look for helper functions that materialize a string from an address, length,
   and a simple transform key.
5. For this historical IPA, the helper uses XOR obfuscation. Dump the referenced
   byte range and decode it as `bytes(byte ^ 0x58 for byte in blob[:216])`.
6. Validate the result before changing the integration: Base64-decode it,
   ensure it loads as a DER RSA public key, and compare it with the key fetched
   from `sg-rsa.js` plus the bundled fallback in `api/crypto.py`.

Native trail:

- `+[SEGEncryptManager setPublicKey:]`
- call site around `0x1004ebadc`
- key is produced by `sub_1003fa810(*(0x101983208))`
- structure uses `key_byte = 0x58`, `length = 216`
- decode algorithm: XOR each byte with `0x58`

Decoded key:

```text
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC03KMpYBkJ51nCrWUsMr1E3T5/q8ETu/UbeJnbyjYD4u3F/4iEECLbUxe9k49gQcb4rR2zciI0Oy8R3x1Irndjc81f9w9g2fTqNnsM00siVsqh6VGEV9XBkWOUoyg601WNbR3HiIa3GyLvo79oND0mdFBP0QqQc2h7IMqaR71hEwIDAQAB
```

The bundled fallback key is this decoded value.

## Home Assistant Debug Flow

Debug config lives in `dev/ha_debug`.

Start HA from this repository root:

```bash
docker compose -f dev/ha_debug/docker-compose.yml up -d
```

Open:

```text
http://localhost:8123
```

The compose file bind-mounts the integration source read-only:

```text
../../custom_components/yongkehui:/config/custom_components/yongkehui:ro
```

After editing Python code, restart HA to ensure imports reload:

```bash
docker compose -f dev/ha_debug/docker-compose.yml restart homeassistant
```

Follow logs:

```bash
docker logs -f yongkehui-ha-debug
```

Run HA config check:

```bash
docker exec yongkehui-ha-debug python -m homeassistant --script check_config -c /config
```

Verify integration imports inside the HA container:

```bash
docker exec yongkehui-ha-debug python -c "import sys; sys.path.insert(0, '/config'); import custom_components.yongkehui.config_flow; import custom_components.yongkehui.api; import custom_components.yongkehui.lock; print('imports ok')"
```

Search current HA log for integration errors:

```bash
rg -n "ERROR|Traceback|yongkehui|custom_components" dev/ha_debug/config/home-assistant.log
```

Stop HA:

```bash
docker compose -f dev/ha_debug/docker-compose.yml down
```

If UI login is needed and the local debug password is unknown, reset it instead
of storing secrets in this file:

```bash
docker exec yongkehui-ha-debug python -m homeassistant --script auth -c /config change_password codex '<new-password>'
```

The local debug HA instance has completed onboarding once. If the config is
deleted and onboarding is reset, recreate a local user through the UI or with:

```bash
docker exec yongkehui-ha-debug python -m homeassistant --script auth -c /config add codex '<password>'
```

## Debug Results So Far

Validated against `ghcr.io/home-assistant/home-assistant:stable`, which resolved
to Home Assistant `2026.7.1` during testing.

Passed checks:

- HA starts successfully.
- The custom integration is discovered by HA.
- Python imports pass inside the container.
- `check_config` passes.
- Config flow first step returns username/password form.
- Submitting a fake account reaches the captcha step instead of crashing.
- Captcha image is written under `.yongkehui_captcha/` and served through a
  dynamically registered `/yongkehui_captcha/<uuid>.jpg` static path.
- Captcha form displays the image and includes a refresh-captcha checkbox.
- Submitting a wrong captcha returns `captcha_required` and refreshes the image
  without traceback.
- HA log only shows the normal custom-integration warning.

Not yet fully validated in HA UI:

- Real account login through the UI.
- House selection with real `houseList`.
- Door entity creation from real `doorList`.
- Real unlock call and 5-second auto relock in HA UI.

## Useful Commands

Repository status:

```bash
git status --short --branch
```

Compile integration modules:

```bash
python3 -m py_compile custom_components/yongkehui/{__init__.py,config_flow.py,const.py,coordinator.py,lock.py} custom_components/yongkehui/api/*.py
```

Whitespace check before commit:

```bash
git diff --check
```

Commit and push:

```bash
git add README.md custom_components/yongkehui hacs.json AGENTS.md dev/ha_debug icon.png
git commit -m "Describe change"
git push
```

## Notes For Future Work

- Avoid logging credentials, captcha text, cookies, or HA auth tokens.
- Do not persist temporary HA debug passwords in docs.
- If changing `manifest.json` requirements, restart the HA container so HA can
  install or reload dependencies.
- If adding files under `dev/ha_debug/config`, remember that HA generates
  `.storage`, database files, logs, and captcha images there; these are local
  debug artifacts, not HACS deliverables.
- The HACS deliverable is this repository root.
