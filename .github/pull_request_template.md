## Summary

What changes and why. Linked issue: Closes #

## Evidence level of this change

Pick the **lowest** that is true (definitions in SUPPORTED_HARDWARE.md):

- [ ] Offline only (tests / simulation / compile)
- [ ] Hardware tested (state the inverter model, **all** firmware strings, the controller board and the ESPHome version)
- [ ] Production proven (rare; explain)

CI passing is **not** hardware evidence.

## Safety impact (tick all that apply, or the last box)

- [ ] Changes which registers can be written (write surface)
- [ ] Changes ownership / arbitration between features
- [ ] Changes restore, fallback, durable records or recovery behaviour
- [ ] Changes a register's meaning, bounds or the capability registry
- [ ] Changes RTC correction, export, charging or discharge behaviour
- [ ] None of the above

If any of the first five is ticked, describe: what can write, the registers affected, the failure behaviour, the restore path and
the test evidence.

- [ ] Nothing plans or permits discharge below the effective battery reserve

## Validation

- [ ] `python tools/validate_repo.py` and the relevant suites pass (`python tools/run_offline_tests.py --all` for everything)
- [ ] Pinned / hashed artifacts changed only through a declared chain entry (no silent re-hash)
- [ ] Docs and SUPPORTED_HARDWARE.md updated where needed

## Provenance and privacy

- [ ] No secrets, account / meter / MPAN ids, serials, LAN details, locations or personal paths
- [ ] No third-party code, vendor documents or copied text without a compatible licence and attribution (this includes
      AI-generated text; I am responsible for what I submit)
- [ ] I license this contribution under GPL-3.0-or-later (see CONTRIBUTING.md)
- [ ] Every commit is signed off (`git commit -s`) under the Developer Certificate of Origin (see CONTRIBUTING.md)

## Breaking changes

Entity ids, helpers, firmware identity, file layout:
