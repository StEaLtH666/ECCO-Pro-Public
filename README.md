# ECCO-Pro

**An open-source, experimental energy-control, monitoring and optimisation project for specific, tested Deye/Sunsynk-family hybrid inverter systems, built on ESPHome and Home Assistant.**

> ### ⚠️ Safety warning: read this before connecting anything
>
> ECCO-Pro can **write settings to your inverter** (grid charging, battery discharge limits, time-of-use slots, export mode, the inverter clock). Wrong settings can change how your battery charges and discharges, how much power you import or export, and what you pay. They can also cause the inverter to behave differently from what its installer configured.
>
> - This is **experimental software**. It has been hardware-tested on **one reference installation** only. It is **not** certified, approved or warranted for any purpose.
> - **Do not** connect it to an inverter unless you understand your installation, have **backed up the inverter's current configuration**, and accept the risk yourself.
> - Only systems listed in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md) have any evidence of working. Everything else is **unsupported and unknown**, including other models and other firmware versions of the same brand.
> - ECCO-Pro does not replace the installer, your inverter's own protections, your DNO/grid-operator obligations, or professional electrical advice. See [SAFETY.md](SAFETY.md).
>
> The software is provided under the terms of its licence, **without warranty**.

---

## Contents

- [What ECCO does](#what-ecco-does)
- [Status](#status)
- [Current capabilities](#current-capabilities)
- [Supported and tested hardware](#supported-and-tested-hardware)
- [Architecture overview](#architecture-overview)
- [Safety philosophy](#safety-philosophy)
- [Installation overview](#installation-overview)
- [Home Assistant integration](#home-assistant-integration)
- [Intelligence (advisory layer)](#intelligence-advisory-layer)
- [Development and testing](#development-and-testing)
- [Contributing](#contributing)
- [Security](#security)
- [Licence](#licence)
- [Trademarks and affiliation](#trademarks-and-affiliation)

## What ECCO does

ECCO-Pro sits between a hybrid solar/battery inverter and Home Assistant. It does three things:

1. **See what the energy system is doing, clearly and live.** A small ESP32 device reads the inverter over its RS485 Modbus interface and publishes the values to Home Assistant, where ECCO's dashboard and cards show power flow, battery state, configuration and health.
2. **Change a small, well-defined set of inverter settings safely.** Each supported change goes through a staged, verified transaction: read the current state, stage the change, require an explicit arm, write, **read back and verify**, and restore the original settings when the action ends or fails. ECCO never assumes that a write worked.
3. **Learn before automating.** An optional advisory layer ("Intelligence") learns household usage and scores its own predictions, but in this release it only recommends and displays. It has no way to write to the inverter.

ECCO is not a general-purpose inverter integration. It deliberately supports a narrow, explicitly listed set of registers and actions (see [SAFETY.md](SAFETY.md)) rather than exposing every register as a writable entity.

## Status

**Experimental, pre-1.0.** Interfaces, entity names, firmware behaviour and file layout can change between releases. Each release states, per feature, whether it is *Offline only*, *Hardware tested* or *Production proven*. The definitions are in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md#proof-levels).

This is **ECCO-Pro 0.9.0**, the first public pre-release (see [CHANGELOG.md](CHANGELOG.md)). `1.0.0` is planned only after testing on more than one installation.

## Current capabilities

The evidence column uses the three proof levels defined in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md#proof-levels) (*Offline only*, *Hardware tested*, *Production proven*; nothing is production proven yet) and refers to the one reference installation only. It is not a promise about your system.

| Capability | What it does | Evidence today |
|---|---|---|
| Live monitoring | Read-only polling of inverter telemetry and configuration, published to Home Assistant; dashboard and cards | Hardware tested (dashboard 7.17.0 in full; the 7.18.0 shadow-check display is deployed and its everyday view was checked live, while its supervision-loss (Shadow Recovery) view is not yet live-proven, see `VERSION.yaml`) |
| Inverter clock (RTC) correction | Detects inverter clock drift and corrects it with write-and-verify, under a policy that avoids correcting near time-of-use boundaries | Hardware tested |
| Manual six-slot time-of-use (TOU) editor | Stage, review and apply the six TOU slots with confirmation and verification. **No automatic rollback of a manual apply**, so you own the result | Hardware tested |
| Free Power | Temporary grid-charging override ("now" or on a schedule you configure) with a durable snapshot, verified writes, a timer and an exact restore | Hardware tested for the normal start → automatic restore path. Operator recovery tools (review, force restore, accept current state): Offline only |
| Export-mode (register 244) policy write | Staged change of the inverter's load/export mode with a durable snapshot and verified restore | Hardware tested |
| Dump-to-Grid | Timed, closed-loop battery export to the grid with a durable snapshot and verified restore | Hardware tested for two scenarios only; every other path, including the low-side infeasible path, is Offline only |
| Fallback profile (save / invalidate / compare) | Saves a user-captured "known-good" inverter profile in the controller's own storage and compares it with the live inverter | Hardware tested. **Restore and automatic failback are not implemented.** ECCO does **not** yet put your inverter back to a saved profile if Home Assistant is lost |
| Home Assistant supervision and shadow check | Heartbeat from Home Assistant to the controller, plus an observe-only evaluation of what *would* happen if Home Assistant were lost | Hardware tested, observe-only, for the heartbeat and the everyday shadow evaluation and display. A supervision-loss episode has not yet been exercised live (an authorised Home Assistant loss drill is still owed). It changes nothing on the inverter. Design and stage status: [docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md](docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md) |
| System Health | Home Assistant-side health checks with reason codes | Hardware tested (on the reference installation's Home Assistant) |
| Battery Outlook (InfluxDB, optional) | Learned five-minute battery outlook, written to and read back from InfluxDB | Hardware tested (on the reference installation's Home Assistant and InfluxDB) |
| Intelligence V1 (advisory) | Usage learning, predictions, safe-target and safe-export recommendations, self-scoring | **Offline only**: shadow-only, synthetic-data tests. No inverter authority |
| Automatic optimiser control | Letting software decide on its own to change inverter settings | **Not implemented** (intentionally) |

Notes on automation: ECCO can act without you pressing a button **only** when you arm a schedule you configured yourself (for example a scheduled Free Power window). There is no learning-driven or optimiser-driven control.

## Supported and tested hardware

**No inverter model is listed as "supported" yet.** ECCO-Pro has been tested on **one reference installation**: a single-phase, low-voltage Deye/Sunsynk-family hybrid inverter system, first with a classic ESP32 controller and now with an ESP32-S3 controller variant. The project's evidence does not record that inverter's exact model or firmware version strings, so this README does not name any; treat every other system, including other models and firmware versions of the same family, as untested.

The full matrix, the proof levels and the list of what is *not* known are in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md). If you have a different system, please read [SUPPORT.md](SUPPORT.md) about sharing **read-only** compatibility reports. Do not enable writes on an untested system.

## Architecture overview

```
 Inverter  ◄──── RS485 / Modbus RTU ────►  ECCO controller (ESP32 / ESP32-S3, ESPHome firmware)
 (Deye/Sunsynk-family)                       • deterministic safety/control layer
                                             • transaction engine: snapshot → write → verify → restore
                                             • ownership/arbitration between features
                                                       │ ESPHome native API
                                                       ▼
                                             Home Assistant
                                             • ECCO packages (helpers, templates, scripts, schedules)
                                             • ECCO dashboard + 3 custom cards
                                             • System Health, supervision heartbeat
                                                       │                       │ (optional)
                                                       ▼                       ▼
                                             Intelligence (advisory,      InfluxDB (history,
                                             read-only, no write path)     Battery Outlook)
```

The controller, not Home Assistant and not the Intelligence layer, is the authority over what may be written and when. See [ARCHITECTURE.md](ARCHITECTURE.md) for a short tour.

## Safety philosophy

- **Known registers only.** The controller can write a small, explicitly pinned set of registers. A test fails if a code change widens that set unnoticed.
- **Read, stage, arm, write, reread, verify, restore.** A write that has not been read back and matched is not treated as successful.
- **Fail closed.** Unreadable or unknown durable state blocks writes and asks for a decision rather than guessing.
- **Durable obligations.** A temporary change records what it must undo in the controller's non-volatile storage, so a reboot cannot silently drop a pending restore.
- **One owner at a time.** Features that touch overlapping registers or meanings arbitrate ownership instead of racing.
- **Humans decide recovery.** Where the situation is ambiguous, ECCO shows the evidence and waits for a person.
- **CI is not authority.** Passing tests never counts as permission to write to real hardware; hardware proof is recorded separately and per feature.

Details, limits and what ECCO **cannot** protect you from are in [SAFETY.md](SAFETY.md).

## Installation overview

> This is an overview, not a complete procedure. The firmware build is described in [docs/user/firmware.md](docs/user/firmware.md) and site-specific entity ids in [docs/user/site-render.md](docs/user/site-render.md). A full step-by-step installation guide is planned after 0.9.0.

**Prerequisites**

- A tested inverter system (see above) and an installer-approved way to reach its RS485 Modbus port.
- An ESP32 or ESP32-S3 board and an RS485 transceiver. The firmware uses UART TX on GPIO17 and RX on GPIO16 at 9600 baud 8N1 and has **no direction-control pin**, so the RS485 adapter must be an automatic-direction type.
- Home Assistant with the ESPHome integration.
- **ESPHome 2026.8.x only.** The firmware pins ESPHome ≥ 2026.8.2 and < 2026.9.0; newer versions are expected to fail to build by design.
- Home Assistant custom cards used by the dashboard (installed separately, not bundled): `button-card`, `apexcharts-card`, `flex-horseshoe-card`, `sunsynk-power-flow-card`, and `card-mod`. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Optional: InfluxDB (history and Battery Outlook).
- Tariff and forecast integrations: the packages reference Octopus Energy tariff entities through `your_*` placeholders and Solcast forecast entities by their default ids. Render your own ids into a local copy with the site renderer (see [docs/user/site-render.md](docs/user/site-render.md)).

**Outline**

1. Read [SAFETY.md](SAFETY.md) and **back up the inverter's configuration**.
2. Create your own `secrets.yaml` from the provided example (`firmware/secrets.yaml.example`, see [docs/user/firmware.md](docs/user/firmware.md)) and build the firmware with ESPHome 2026.8.x. Keep Wi-Fi, API and OTA secrets out of version control.
3. First connect **read-only**: leave every write-enable switch off and confirm that the values you see match the inverter's own display.
4. Add the Home Assistant packages and dashboard, and install the required custom cards.
5. Only then consider enabling a single write capability, with a conservative test (for example a short, low-power Free Power run), and observe the verified restore.
6. When upgrading firmware, flash only when no durable recovery obligation is open (every recovery marker reads clear). This rule is described in the safety document.

## Home Assistant integration

ECCO's Home Assistant side is plain YAML, deployed by you; nothing is pushed to your Home Assistant automatically.

- **Packages** (`home-assistant/packages/`): core helpers and telemetry, runtime configuration, scheduled Free Power and Dump-to-Grid, TOU helpers, canonical telemetry, System Health, the supervision heartbeat, Fallback status and operator wrappers, and the optional Battery Outlook read-back.
- **Dashboard** (`home-assistant/dashboards/ecco_pro.yaml`): live energy flow, energy actions, manual controls, safety/fallback view, inverter configuration view and health.
- **Custom cards** (`frontend/`): `ecco-energy-actions-card`, `ecco-energy-flow-card`, `ecco-fallback-recovery-card`. Prebuilt bundles are included; sources and tests are in each folder.
- **Entity names.** With the firmware's default node name `ecco-clock-dongle`, a fresh Home Assistant install creates entities of the form `<domain>.ecco_clock_dongle_<entity>`. If your device slug or tariff entity ids differ, render a site copy with `tools/ecco_site_render.py` and deploy that copy; the tracked files stay generic (see [docs/user/site-render.md](docs/user/site-render.md)).
- **Supervision heartbeat.** A Home Assistant automation calls an ESPHome API action roughly every 30 seconds so the controller can tell whether Home Assistant is supervising it. Today this is used for display and observation only.
- **Write-enable switches** on the controller (for example the Free Power write enable) restore to **off** at every boot. Dashboard and schedule scripts turn one on only as part of a request you made or a schedule you armed.

## Intelligence (advisory layer)

`intelligence/` is a pure-Python (standard library only) engine: **read → learn → predict → recommend → score**.

- It reads Home Assistant long-term statistics **read-only**, learns how a household uses energy, forecasts the next hours and days with stated uncertainty, recommends an overnight battery target and a safe export amount, and scores every prediction against what actually happened.
- It has **no write path**: the engine imports no network, serial or process modules and contains no control vocabulary; a test enforces this (the one exception, allow-listed by that test, is the developer preview tool `intelligence/tools/preview_dashboard.py`, which runs a local Node.js process to render a preview). Its outputs are a report, optional read-only Home Assistant display sensors, and its own local SQLite scorecard file.
- Status: **Offline only, shadow-only, not deployed.** Examples and tests use synthetic data only.
- Reserve handling: every recommendation is computed against an *effective reserve*, the larger of your **user reserve** (configurable, default 40%), a **technical minimum** and, optionally, a reserve value read from Home Assistant at run time (an input only: nothing enforces it); recommended targets then keep a further safety margin (default 5 percentage points) above it. Intelligence does **not** read the inverter's own battery shutdown setting: the technical minimum defaults to 10% only as a placeholder, and you set it to the minimum permitted by your inverter / battery configuration. Home Assistant also has a reserve helper, `input_number.ecco_minimum_reserve_soc` (0-80%; a one-time defaults automation in the core package sets it to 15% when Home Assistant first starts with ECCO). In 0.9.0 nothing enforces it: no firmware feature and no Home Assistant script uses it as a limit. Intelligence can take it as a run-time input, and then it can only **raise** the effective reserve, never lower it. Intelligence recommendations (including any export advice) respect that effective reserve. **Dump-to-Grid does not:** in 0.9.0 its firmware enforces only its own stop-level bounds, not the Intelligence reserve policy (see [SAFETY.md](SAFETY.md#9-battery-reserve)).

See `docs/intelligence/` for the design.

## Development and testing

Most of the project is verified **offline**, without hardware.

- Python 3.12 with PyYAML and Jinja2 for the repository checks and test suites.
- `python tools/validate_repo.py` checks tracked YAML, Python, JSON, Flux and manifest references.
- Test suites are plain `test_*.py` scripts. The directories to run are listed in one file, `tools/offline_test_roots.txt` (`registry/tests`, `home-assistant/tests`, `health/tests`, `influxdb`, `intelligence/tests`, `tools/tests`); `python tools/run_offline_tests.py --all` runs them all.
- Some suites compile firmware headers with a host C++ compiler and are slow; some firmware checks need `esphome==2026.8.2`.
- The three custom cards have their own `npm test` (the first two also `npm run typecheck` and `npm run build`). They were run locally with Node.js 24; CI does not run them yet.
- Hardware proof is separate from CI. A change that can write to an inverter needs a supervised test on real hardware (read back, verified and restored, see the proof levels in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md#proof-levels) and the evidence rules in [CONTRIBUTING.md](CONTRIBUTING.md)) before it is called hardware-tested.

## Contributing

Feedback, issues, documentation, tests, portability work and pull requests are welcome. Changes that touch inverter writes, the register map, transaction sequencing, restore/fallback, RTC correction, export control, charging or ownership/arbitration get stricter review and must say whether they are *Offline only* or *Hardware tested*. Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and [SUPPORT.md](SUPPORT.md) for how to ask questions and what to include in reports. Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

Do not post secrets, serial numbers, tariff/account identifiers, private network addresses or household telemetry anywhere in this project.

## Security

Report vulnerabilities privately; see [SECURITY.md](SECURITY.md). A defect that could cause unintended inverter writes is both a security and a safety issue.

## Licence

ECCO-Pro is free software, licensed under the **GNU General Public License, version 3 or (at your option) any later version** (SPDX identifier: `GPL-3.0-or-later`). Distributed modifications must remain open under the same terms. The full licence text is in [LICENSE](LICENSE). It comes **without warranty** (see sections 15 and 16 of the licence and [SAFETY.md](SAFETY.md)). Third-party components keep their own licences; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The three custom cards are ECCO's own code under the same licence (GPL-3.0-or-later). The two prebuilt card bundles also contain the Lit library (BSD-3-Clause); its notices are kept inside each bundle and in [frontend/LIT-LICENSE.txt](frontend/LIT-LICENSE.txt).

Contributions are accepted under the same licence with a Developer Certificate of Origin sign-off (`git commit -s`); there is no CLA. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Trademarks and affiliation

Deye, Sunsynk, SmartDeye, Octopus Energy, Solcast, Home Assistant, ESPHome, HACS and other product names are trademarks of their respective owners. ECCO-Pro is an independent open-source project. It is **not** affiliated with, endorsed by or sponsored by any of them. Names are used only to describe compatibility. "ECCO" is this project's name; it is unrelated to any company or product that uses the same word.
