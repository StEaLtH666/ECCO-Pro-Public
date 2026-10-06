# Security policy

ECCO-Pro controls a battery inverter. A defect that makes ECCO write something unexpected to an inverter is treated as **both a
security issue and a safety issue**, even when no attacker is involved.

## Reporting a vulnerability

**Do not open a public issue for a vulnerability, or if ECCO wrote something unexpected to your inverter.**

Use GitHub's private vulnerability reporting for this repository: **Security → Report a vulnerability**. This is the only
reporting channel; the project publishes no personal e-mail address. If the button is missing, open a public issue that says
only "please enable private vulnerability reporting", with **no details**, and wait for it to be enabled.

A good report contains:

- the ECCO version or commit, the firmware file, the ESPHome and Home Assistant versions;
- what an attacker (or a fault) can make ECCO do, and the impact on the inverter, the battery or the household;
- steps to reproduce, ideally offline (a test, a simulation, a configuration);
- **no real data**: no secrets, serial numbers, tariff / meter / MPAN / account identifiers, IP or MAC addresses, locations or
  household telemetry.

Please do not test against other people's systems, and give the maintainer reasonable time to fix an issue before disclosing it.
This is a volunteer, single-maintainer project: reports are acknowledged and handled on a best-effort basis, with no guaranteed
response time. Reports that could cause an unintended inverter write are handled first.

## Scope

In scope:

- the ESPHome firmware and its headers (`firmware/`): write surface, transaction sequencing, durable records, recovery, the
  native API actions;
- the Home Assistant packages, dashboard and custom cards (`home-assistant/`, `frontend/`): anything that can trigger a write,
  arm a schedule, or mislead an operator about the inverter's state;
- the deployment and bundle tooling (`tools/`, `deployment/`): path handling, what gets copied to a Home Assistant host;
- the Intelligence layer (`intelligence/`): it must stay read-only; any route to a write is in scope;
- the CI workflows (`.github/workflows/`): permissions, action pinning, untrusted input handling.

Out of scope (report to the respective project): vulnerabilities in Home Assistant, ESPHome, ESP-IDF, the inverter's own firmware
or the manufacturer's cloud service. ECCO-specific misuse of them is in scope.

## Supported versions

| Version | Supported |
|---|---|
| `main` | yes |
| 0.9.x (first public pre-release) | yes, until the next minor release |
| anything older | no (there is no older public release) |

Fixes land on `main` first; a fixed 0.9.x pre-release is tagged when needed.
