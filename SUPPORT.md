# Getting help and reporting problems

ECCO-Pro is an experimental, volunteer-maintained project. There is **no service-level agreement** and no guaranteed response time. Please be patient and kind (see the [Code of Conduct](CODE_OF_CONDUCT.md)).

> **Safety first.** If you think ECCO has written something unexpected to your inverter, **stop**: turn the ECCO write-enable switches off, disconnect the controller from the RS485 bus if necessary, and restore your inverter settings from your own backup or through the manufacturer's tools. Then report it. See [SAFETY.md](SAFETY.md).

## Which channel to use

| You want to… | Use |
|---|---|
| Ask how something works, how to set it up, or whether your hardware might work | **GitHub Discussions → Q&A** (`https://github.com/StEaLtH666/ECCO-Pro-Public/discussions`) |
| Suggest an idea or discuss design | **GitHub Discussions → Ideas** |
| Report a **reproducible** bug in ECCO | **GitHub Issues → Bug report** |
| Share a compatibility result (what you tested, read-only or otherwise) | **GitHub Issues → Hardware compatibility report** |
| Propose a code or documentation change | A pull request, after reading [CONTRIBUTING.md](CONTRIBUTING.md) |
| Report a security problem, or anything that could cause **unintended inverter writes** | **Private** vulnerability reporting; see [SECURITY.md](SECURITY.md). Do **not** open a public issue |

Please search existing issues and discussions first.

### What is *not* supported

- Inverter models or firmware versions that are not listed in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md). You can ask about them, but the answer is usually "unknown".
- Problems that come from the inverter vendor's cloud app or other Modbus masters sharing the same bus (see [SAFETY.md](SAFETY.md)).
- Electrical installation, DNO/grid-connection or warranty questions. Ask your installer or the manufacturer.
- Help recovering a system after an unreviewed local modification of the safety-critical code.

## Before you open a bug report

Please try to reproduce the problem and note:

1. What you expected, and what happened instead.
2. Exact steps to reproduce.
3. Whether any write-enable switch was on, and which ECCO action was running (for example Free Power, Dump-to-Grid, manual TOU, fallback profile).
4. Whether it happens read-only (nothing armed) or only when writing.

## What information to provide

Provide the following, **after sanitising it** (next section):

| Item | Why |
|---|---|
| ECCO version, tag or commit | To find the code you are running |
| Firmware YAML name (classic ESP32 or ESP32-S3 wrapper) and the **ESPHome version** used to build it | The firmware only builds with ESPHome 2026.8.x |
| Home Assistant version | Entity and template behaviour changes between versions |
| Inverter make, model, **firmware version strings as shown on the inverter or its app**, phase type (single/three), battery type | Register meanings can differ by model and firmware |
| Controller hardware: board, RS485 adapter type | Wiring/direction issues are common |
| What is armed/running, and the relevant ECCO status text sensors | They explain which safety gate acted |
| A short, relevant log excerpt around the event (see below) | ESPHome logs and Home Assistant logs are the main evidence |
| Whether you changed any ECCO YAML | To tell product bugs from local edits |

Do **not** send full database dumps, full Home Assistant diagnostics, or your whole configuration.

## How to sanitise logs and configuration

Before pasting anything publicly, search it and replace:

| Remove or replace | Replace with |
|---|---|
| Wi-Fi SSID/password, API encryption key, OTA password, Home Assistant or InfluxDB tokens, SSH keys | `<REDACTED>` (and **rotate** anything that already leaked) |
| Inverter, battery or logger **serial numbers** | `<INVERTER_SERIAL>` |
| Electricity **MPAN / MPRN**, **meter serial**, **account number**, tariff/agreement ids (these also appear inside Octopus Energy entity ids) | `<IMPORT_MPAN>`, `<EXPORT_MPAN>`, `<METER_SERIAL>`, `<ACCOUNT_ID>` |
| IP addresses on your LAN, hostnames that identify you, **MAC addresses** | `<LAN_IP>`, `<HOST>`, `<MAC>` |
| Your name, e-mail, home address, postcode, precise location or coordinates | `<PERSON>`, `<EMAIL>`, `<ADDRESS>`, `<LOCATION>` |
| Local file paths that contain your username | `<HOME>/…` |
| Household energy history, occupancy patterns, absence/holiday times | Not needed for a bug report. Share a small synthetic or aggregated example instead |

A useful habit is to search the text for: runs of 13 or more digits, `192.168.`, `10.`, `172.16`–`172.31`, `:` separated hex pairs, `secret`, `token`, `password`, `key`, `serial`, `mpan`, `account`, your surname and your street.

Entity ids are generally fine to share **unless** they contain a serial, MPAN, account or meter id (some tariff integrations put them in the entity id).

If a report cannot be made safe to share publicly, say so and describe the problem in words. A maintainer can ask for specific, further sanitised details.

## Response and triage

Maintainers triage on a best-effort basis, with no target response time. Reports that include a clear, sanitised, reproducible description, plus hardware and version details, are the easiest to act on. Reports that concern writes to inverter settings are prioritised over cosmetic issues.
