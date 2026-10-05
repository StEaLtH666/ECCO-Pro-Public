# Contributing to ECCO-Pro

Thank you for helping improve ECCO-Pro.

The project is still preparing its first public release. Until that release is published, contributions should focus on clearly scoped issues, documentation, tests, portability, and reviewed implementation work.

## Before opening a pull request

- Open or reference an issue for substantial changes.
- Keep changes narrowly scoped.
- Do not include secrets, account identifiers, household telemetry, private network details, or local filesystem paths.
- Add or update tests for behavioural changes.
- Document any inverter model, firmware, battery, or Home Assistant assumptions.
- Clearly identify whether a change is offline-tested only or hardware-proven.

## Safety-critical changes

Changes affecting inverter writes, register maps, transaction sequencing, fallback/restore, RTC correction, export control, charging, or ownership/arbitration require explicit maintainer review and suitable regression tests.

A pull request touching these areas should explain:

- what can write
- which registers/capabilities are affected
- failure behaviour
- restore/rollback behaviour
- test evidence

## Development

Detailed local development and validation instructions will be added with the sanitised source import.

## Licence

The project licence will be finalised before the first public release. Do not contribute third-party code unless its provenance and licence are clear.
