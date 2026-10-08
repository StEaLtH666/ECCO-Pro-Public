# Third-party notices

ECCO-Pro's own code and documentation are licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)). This file lists the
third-party software and content that the repository **contains**, **builds or tests with**, or **expects you to install**, and
what is known about each licence. Only section 1 is redistributed by this repository. Nothing here is legal advice.

"Verified" means the licence was read from the licence file or package metadata of the exact version named (checked
2026-10-06), or, for prerequisites, from the upstream project's licence file.

## 1. Bundled in this repository (redistributed)

| Component | Where | Version | Licence | Verified from |
|---|---|---|---|---|
| Lit: `lit`, `lit-html`, `lit-element`, `@lit/reactive-element` | Inlined into the prebuilt card bundles `frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js` and `frontend/ecco-energy-flow-card/dist/ecco-energy-flow-card.js` | 3.3.3 / 3.3.3 / 4.2.2 / 2.1.2 (each card's `package-lock.json`) | BSD-3-Clause, "Copyright (c) 2017 Google LLC. All rights reserved." | Each package's `LICENSE` file and `package.json`. Both bundles were built with esbuild `legalComments: "eof"`, so Lit's `@license` comments are kept at the end of each bundle. The full licence text is in [frontend/LIT-LICENSE.txt](frontend/LIT-LICENSE.txt) (verbatim) |
| Contributor Covenant 3.0 | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | 3.0 | CC BY-SA 4.0, as stated in its own attribution section | The official text, adapted only in its two designated places (the reporting route and the enforcement note). The attribution section is unchanged; ShareAlike applies to that text only |

Nothing else third-party is bundled. In particular:

- The esbuild bundles contain only the four Lit packages above (checked from the esbuild build graph); every other import is
  ECCO's own source. `@types/trusted-types` 2.0.7 (MIT) is a type-declaration dependency of Lit and contains no runtime code;
  `@lit-labs/ssr-dom-shim` 1.6.0 (BSD-3-Clause) is used only under Node and is not in the bundles.
- The inline SVG icons of `frontend/ecco-fallback-recovery-card` are simple geometric shapes drawn for this project (they replace
  an earlier icon table whose origin was not recorded). They are ECCO's own work under GPL-3.0-or-later.
- No vendor document, register table or code from another project is included; see section 6.

## 2. Build-time and test-time tools (not redistributed)

These are used to build or test ECCO. They are installed by you or by CI and are not part of this repository.

| Component | Used for | Version | Licence | Verified from |
|---|---|---|---|---|
| esbuild | Bundling the two Lit-based cards | 0.28.1 (`ecco-energy-flow-card`) / 0.21.5 (`ecco-energy-actions-card`), each card's `package-lock.json` | MIT | `LICENSE.md`, `package.json` (0.28.1 checked 2026-10-08) |
| TypeScript | Type-checking the two Lit-based cards | 5.9.3 | Apache-2.0 | `LICENSE.txt`, `package.json` |
| Node.js | Running the card builds and tests | not pinned; tested with 24.x | MIT (plus the licences of its own bundled components) | Upstream `LICENSE` at the tested version |
| PyYAML | Repository validation and tests | 6.0.3 (`requirements-ci.txt`) | MIT | Installed package `LICENSE` |
| Jinja2 | Home Assistant template tests | 3.1.6 (`requirements-ci.txt`) | BSD-3-Clause | Installed package `LICENSE.txt` |
| MarkupSafe | Jinja2 dependency | 3.0.3 (`requirements-ci.txt`) | BSD-3-Clause | Installed package `LICENSE.txt` |
| ESPHome (Python package) | Validating and compiling the firmware | 2026.8.2 (pinned in the CI workflow) | MIT for the Python code (see section 3 for its C++ runtime) | Installed package `LICENSE` and metadata |
| A native C++ compiler (for example GCC) | Host-compile test suites | not pinned | GCC: GPL-3.0-or-later with the GCC Runtime Library Exception | Not redistributed; only used to run tests |

## 3. Firmware build inputs (downloaded by ESPHome, not vendored)

The firmware is an ESPHome configuration plus first-party C++ headers (`firmware/include/*.h`). ESPHome downloads and links its
own dependencies when you build it. This repository distributes **source only**; it ships no firmware binary.

| Component | Role | Version | Licence | Verified from |
|---|---|---|---|---|
| ESPHome C++ runtime and components | Linked into the firmware binary | 2026.8.2 | GPLv3 for ESPHome's C/C++ files; MIT for the rest of ESPHome | ESPHome's `LICENSE` at tag 2026.8.2 (identical to the installed package's copy) |
| ESP-IDF (via ESPHome) | Framework underneath the firmware | 5.5.5 | Apache-2.0 (some sub-components carry their own permissive licences) | Its `LICENSE` file |
| `espressif/mdns` | mDNS | 1.11.3 | Apache-2.0 | Its `LICENSE` file |
| `esphome/noise-c` | API encryption | 0.1.21 | MIT, "Copyright (C) 2016 Southern Storm Software, Pty Ltd." | Its `LICENSE` file |
| `esphome/libsodium` port | API encryption (port glue) | 1.10021.4 | MIT, "Copyright (c) 2021 Otto Winter" | Its `LICENSE` file |
| libsodium (sources compiled by that port) | Cryptography | as shipped with the port | ISC, "Copyright (c) 2013-2026 Frank Denis" | The `LICENSE` file shipped with the compiled sources |

**GPL compatibility.** ESPHome's statement says "GPLv3" without saying "only" or "or later". ECCO's own sources are
GPL-3.0-or-later, which is compatible with either reading. A combined firmware binary would be distributed under GPLv3 terms.
Apache-2.0, MIT and ISC components are compatible with GPLv3. If you distribute a firmware binary, provide the corresponding
source (ECCO's sources, the exact ESPHome version and the build configuration) and keep the notices of every component above.

## 4. GitHub Actions used by CI (referenced, not copied)

| Action | Release (pinned commit) | Licence |
|---|---|---|
| `actions/checkout` | v4.4.0 (`11d5960a326750d5838078e36cf38b85af677262`) | MIT |
| `actions/setup-python` | v5.6.0 (`a26af69be951a213d495a4c3e4e4022e16d87065`) | MIT |
| `actions/upload-artifact` | v4.6.2 (`ea165f8d65b6e75b540449e92b4886f43607fa02`) | MIT |

## 5. Prerequisites you install yourself (not bundled)

ECCO's dashboard and packages expect these in your Home Assistant. They are not part of this repository, keep their own licences
and terms, and are not affiliated with ECCO-Pro. Licences below are those stated by each project's repository.

| Prerequisite | Why | Required? | Licence |
|---|---|---|---|
| Home Assistant Core (with its ESPHome integration) | The platform | Required | Apache-2.0 |
| `button-card` (custom-cards/button-card) | ECCO dashboard | Required for the dashboard | MIT |
| `apexcharts-card` (RomRider/apexcharts-card) | ECCO dashboard | Required for the dashboard | MIT |
| `flex-horseshoe-card` (AmoebeLabs/flex-horseshoe-card) | ECCO dashboard | Required for the dashboard | MIT according to its README (the repository has no `LICENSE` file) |
| `sunsynk-power-flow-card` (slipx06/sunsynk-power-flow-card) | ECCO dashboard | Required for the dashboard | MIT |
| `card-mod` (thomasloven/lovelace-card-mod) | ECCO dashboard styling | Required for the dashboard | MIT |
| HACS | Installing custom cards | Optional | MIT |
| Octopus Energy integration (BottlecapDave/HomeAssistant-OctopusEnergy) | Tariff entities (placeholders until you render your own ids, see `ecco_site.example.yaml`) | Optional (UK) | MIT |
| Solcast PV forecast integration (BJReplay/ha-solcast-solar) | Forecast sensors | Optional | Apache-2.0 |
| InfluxDB 2.x and Home Assistant's InfluxDB integration | History and Battery Outlook | Optional | InfluxDB 2.x: MIT; the integration is part of Home Assistant Core (Apache-2.0) |

## 6. Names and register information

- Deye, Sunsynk, SmartDeye, Octopus Energy, Solcast, Home Assistant, ESPHome and HACS are trademarks of their respective owners.
  They are used only to describe compatibility; ECCO-Pro is an independent project, not affiliated with or endorsed by them. No
  logos are included.
- Register addresses and meanings: see [docs/dev/register-provenance.md](docs/dev/register-provenance.md). No vendor protocol
  document is included or reproduced. Some registers were compared with the open-source
  [kellerza/sunsynk](https://github.com/kellerza/sunsynk) project (Apache-2.0, "Copyright 2021-2026 Johann Kellerman"); no code,
  table or text from it is included, so no part of this repository is distributed under its licence.
