# Third-party notices

ECCO-Pro's own code and documentation are licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)). This file lists
third-party software and content that the repository **contains, builds with, or expects you to install**, and what is known
about each licence. Nothing here is legal advice.

Status words: **Verified** = read from the licence file / package metadata of the exact version used (the source is named).
**TODO(verify)** = not yet checked against the upstream licence file; it must be checked before the project is published.

## 1. Bundled in this repository (redistributed)

| Component | Where | Version | Licence | Status |
|---|---|---|---|---|
| Lit (`lit`, `lit-html`, `lit-element`, `@lit/reactive-element`) | Inlined into the prebuilt card bundles `frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js` and `frontend/ecco-energy-flow-card/dist/ecco-energy-flow-card.js` | 3.3.3 / 3.3.3 / 4.2.2 / 2.1.2 (the cards' `package-lock.json`) | BSD-3-Clause, "Copyright (c) 2017 Google LLC" | **Verified** from the packages' `LICENSE` files and `package.json` metadata. Full text: [frontend/LIT-LICENSE.txt](frontend/LIT-LICENSE.txt) (verbatim). The energy-flow bundle carries Lit's `@license` comments at its end; the energy-actions bundle does not yet (see below) |
| Icon path data | Inline SVG path strings (`ICON`) in `frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js` | n/a | **Not established.** Several paths match the shapes of Material Design Icons (Pictogrammers), but their origin is not recorded | TODO(owner) / TODO(verify): confirm where the paths came from. If they are Material Design Icons, record that project's licence and notice here; otherwise confirm they are self-drawn or redraw them |
| Code of Conduct text | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Contributor Covenant 3.0, adapted only in its two designated places (reporting route; enforcement note) | CC BY-SA 4.0, as stated in its own attribution section | Official text; the attribution section is kept unchanged. ShareAlike applies to that text only |

`@types/trusted-types` 2.0.7 (MIT, verified from its `LICENSE` file) is a type-declaration dependency of Lit: it contains no
runtime code and is not part of the bundles.

**Known gap (energy-actions bundle).** `frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js` was built with
`legalComments: "none"`, so Lit's notice is not inside that file; it ships alongside it in this repository
([frontend/LIT-LICENSE.txt](frontend/LIT-LICENSE.txt), this file). That card folder is pinned by the offline proof chain, so its
rebuild with `legalComments: "eof"` is a declared change still to be made. <!-- TODO(release): rebuild the energy-actions bundle
with legal comments through a declared chain entry, before the card is distributed on its own (for example through HACS). -->

**The ECCO cards' own licence.** The three cards' `package.json` files (and two card READMEs) still say `MIT`.
<!-- TODO(owner): choose GPL-3.0-or-later for the cards (the project licence) or record a deliberate MIT carve-out, then align
package.json, the card READMEs and this file. -->

## 2. Build-time and test-time tools (not redistributed)

| Component | Used for | Version | Licence | Status |
|---|---|---|---|---|
| esbuild | Bundling the two Lit-based cards | 0.21.5 | MIT | **Verified** (`LICENSE.md`, `package.json`) |
| TypeScript | Type-checking the two Lit-based cards | 5.9.3 | Apache-2.0 | **Verified** (`LICENSE.txt`, `package.json`) |
| PyYAML | Repository validation and tests | 6.0.3 (`requirements-ci.txt`) | MIT | **Verified** (installed package metadata) |
| Jinja2 | Home Assistant template tests | 3.1.6 (`requirements-ci.txt`) | BSD-3-Clause (Pallets) | **Verified** (installed package `LICENSE.txt`) |
| MarkupSafe | Jinja2 dependency | 3.0.3 (`requirements-ci.txt`) | BSD-3-Clause | **Verified** (installed package metadata) |
| ESPHome (Python package) | Validating and compiling the firmware | 2026.8.2 (pinned in the CI workflow) | MIT for the Python package (package metadata); see section 3 for its C++ runtime | **Verified** (installed package metadata) |
| Node.js | Running the card tests | not pinned (tested locally with Node 24) | TODO(verify) | |
| Host C++ compiler (for example GCC) | Host-compile test suites | not pinned | TODO(verify) | Not redistributed |

## 3. Firmware build inputs (not vendored)

The firmware is an ESPHome configuration plus first-party C++ headers (`firmware/include/*.h`). ESPHome downloads and links its
own dependencies when you build it.

| Component | Role | Licence | Notes |
|---|---|---|---|
| ESPHome C++ runtime and components | Linked into the firmware binary | GPLv3 for ESPHome's C/C++ runtime code (its `LICENSE` file; the Python code is MIT) | A firmware binary would be distributed under GPLv3. If ESPHome's C++ is GPL-3.0-only, "or later" applies to ECCO's own sources, not to a combined binary. TODO(verify) against the `LICENSE` file of the ESPHome version you build with |
| ESP-IDF 5.5.5 (via ESPHome) | Framework underneath the firmware | Apache-2.0 (its `LICENSE` file) | TODO(verify): licences of other components bundled inside ESP-IDF that the build links |
| `espressif/mdns` 1.11.3 | mDNS | Apache-2.0 | TODO(verify) against its licence file |
| `esphome/noise-c` 0.1.21 | API encryption | MIT per its library metadata | TODO(verify) against its licence file |
| `esphome/libsodium` port 1.10021.4 | API encryption | MIT per the port's metadata | TODO(verify): the licence of the libsodium sources actually compiled |

No firmware binary is distributed by this repository today. If one ever is, ship the corresponding source and all notices
above with it.

## 4. GitHub Actions used by CI (referenced, not copied)

| Action | Used in | Licence |
|---|---|---|
| `actions/checkout@v4` | `.github/workflows/validate.yml` | TODO(verify) |
| `actions/setup-python@v5` | `.github/workflows/validate.yml` | TODO(verify) |
| `actions/upload-artifact@v4` | `.github/workflows/validate.yml` | TODO(verify) |

## 5. Prerequisites you install yourself (not bundled)

ECCO's dashboard and packages expect these in your Home Assistant. They are not part of this repository and keep their own
licences and terms. ECCO-Pro is not affiliated with them.

| Prerequisite | Why | Licence |
|---|---|---|
| Home Assistant Core and its ESPHome integration | Required platform | TODO(verify) |
| `button-card`, `apexcharts-card`, `flex-horseshoe-card`, `sunsynk-power-flow-card`, `card-mod` (custom cards) | Used by the ECCO dashboard | TODO(verify) for each |
| HACS (optional) | Installing the custom cards | TODO(verify) |
| Octopus Energy integration (optional, UK) | Tariff entities referenced by the packages (placeholders until you render your own ids, see `ecco_site.example.yaml`) | TODO(verify) |
| Solcast PV forecast integration (optional) | Forecast sensors referenced by the packages / dashboard | TODO(verify) |
| InfluxDB and its Home Assistant integration (optional) | History and Battery Outlook | TODO(verify) |

## 6. Names and register information

- Deye, Sunsynk, SmartDeye, Octopus Energy, Solcast, Home Assistant, ESPHome and HACS are trademarks of their respective owners.
  They are used only to describe compatibility; ECCO-Pro is an independent project, not affiliated with or endorsed by them. No
  logos are included.
- Register addresses and meanings: see [docs/dev/register-provenance.md](docs/dev/register-provenance.md). No vendor protocol
  document is included or reproduced.
