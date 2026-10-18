# Firmware S0: the equivalence checker

Status: **tooling only.** This adds `tools/check_firmware_equivalence.py` and its suite
`tools/tests/test_firmware_equivalence.py`. It changes no firmware file, no header, no wrapper, no CI workflow, no write-surface
rule and no proof-chain entry, and it creates no write path. Nothing here was run against a device.

## Why

Any later restructuring of the firmware source (for example splitting the production YAML into smaller files) must show that it
changed the **layout** and not the **behaviour**. `registry/tests/check_esp32s3_equivalence.py` already proves one such claim:
the ESP32-S3 wrapper generates the same C++ as production apart from the logger UART. This tool generalises that idea. It compares
any two firmware trees (two git revisions, or a revision and a directory) and reports a proof matrix. It is S0 of the
modularisation plan, and it stops there: no split is made.

## Layers

Every check is strict. A difference is a FAIL; nothing is normalised. A layer that did not run is NOT-RUN or BLOCKED, never PASS.

| Layer | What is compared | Needs |
|---|---|---|
| L0 source | the bytes (sha256) of every `firmware/*.yaml` and `firmware/include/*.h`, and the set of file names (line endings included) | Python |
| L1 inventory | per target YAML (production and S3 wrapper), as ordered lists: top-level key order; substitutions; every list section item by item (position + digest of the item, so a one-character lambda edit or a swapped pair is caught and located); every declared id; entities (section, platform, id, name); API actions and variables; globals with `restore_value`; the interval block (period, startup delay, digest); `esphome: includes:`; every C++ body (`!lambda` and `lambda:`); the durable tags the headers declare (`registry/tests/_tag_inventory.py`) | Python, PyYAML |
| L2 authority | `tools/analyze_write_surface.analyze()` (unchanged, imported read-only) on each side: every write path, its Modbus operations, ownership flags, arm switches, obligations and dispatches. Fails if **either** side has a write of unknown extent or an unclassified bus access, even if both sides agree | Python |
| L3 generated | `esphome config` and `esphome compile --only-generate` for the classic and the S3 target: the whole generated `src/` tree byte for byte (`main.cpp`, `esphome/core/defines.h` and every other file), the validated configuration, and `ESPHOME_CONFIG_HASH` | ESPHome **2026.8.2** exactly (`--generate`) |

### L3 determinism controls (declared, never hidden)

- **Build time, the one declared exclusion.** ESPHome 2026.8.2 writes the wall clock into
  `esphome/core/build_info_data.cpp` (`ESPHOME_BUILD_TIME`, `ESPHOME_BUILD_TIME_STR`; no `SOURCE_DATE_EPOCH` support). Only those
  line shapes may differ. The report always shows this exclusion as its own row, and every other line of the file, including
  the config hash, is still compared.
- **Same sandbox path for both sides.** ESPHome echoes absolute include paths into comments in `main.cpp` and into
  `idf_component.yml`, and the config hash also depends on the path. Both sides therefore run one after the other in the same
  sandbox path, so nothing has to be rewritten. For a baseline that has to be reproduced later, pass `--sandbox <fixed path>`
  (it must not exist; the tool creates it and removes it afterwards). With a random temporary path, the `main.cpp` and
  config-hash values in the baseline are only valid for that one run.
- **`PYTHONHASHSEED=0` for ESPHome.** `esphome config` prints some keys in hash-seed order (two orderings of `tag: main` lines were
  observed across seeds 0-11). The generated C++, `defines.h` and the config hash were observed to be seed-independent
  (seeds 0, 3, 8, 9). Fixing the seed controls the toolchain's input; the output is not edited.
- **No hidden network.** ESPHome downloads library sources (noise-c, libsodium from the PlatformIO registry) while
  generating. L3 runs only with `--esphome-cache DIR` (a `pio_components/` seed copied into each sandbox) or with
  `--allow-toolchain-downloads`. Every download URL is reported, and a download despite a seeded cache FAILS. With
  `--allow-toolchain-downloads` and an empty `--esphome-cache`, the first run fills the cache.
- **No device.** The tool can only build the argv `esphome version`, `esphome config <yaml>` and
  `esphome compile --only-generate <yaml>` (`ESPHOME_COMMANDS`, pinned by the suite). Sandboxes hold copies of the firmware and
  CI-style placeholder secrets. A `secrets.yaml` in an input tree is never read. The tool never writes into the repository:
  `--baseline-out`, `--esphome-cache` and `--sandbox` inside it are refused.

## Use

```
python tools/check_firmware_equivalence.py --before <rev|dir> --after <rev|dir>
python tools/check_firmware_equivalence.py --before <rev|dir> --after <rev|dir> --generate \
    --esphome-cache <dir outside the repo> [--sandbox <fixed path>] [--baseline-out <file outside the repo>] [--json]
```

Exit codes: 0 every check that ran PASSES; 1 at least one FAIL; 2 usage or input error; 3 BLOCKED (for example ESPHome missing
or not 2026.8.2, or `--generate` without a cache seed or download permission).

Static layers take about 5 s. L3 takes about 1 minute (four ESPHome runs).

## Baseline recorded at S0 (2026-10-18)

`--before d1c9a3e1 --after 555cf859` (the source of the Build Identity of the live image vs public main): **45 PASS, 0 FAIL**.
The firmware trees are byte-identical (production YAML blob sha256 `9cb4bd6c…`).

| Item | Value |
|---|---|
| Toolchain | Python 3.12.10, PyYAML 6.0.3 (libyaml), ESPHome 2026.8.2, `PYTHONHASHSEED=0` |
| Inventory (production) | 665 globals, 39 scripts, 14 intervals, 1,248 C++ bodies, 1,127 ids, 363 entities, 7 restored globals, 3 API actions, 17 header durable tags |
| Write surface | 48 write paths, 58 write ops, 65 read ops (analyser model); digest `7cc4554c…` |
| `defines.h` (path-independent) | classic `37163fdd…`, S3 `acadcd7d…` |
| Generated `src/` | 276 files per target |

`main.cpp`, the validated configuration and the config hash depend on the sandbox path and on the placeholder secrets, so they
are recorded with the fixed sandbox used, not here. The live image's config hash cannot be reproduced by this tool: it was built
with the real secrets and an `ecco_build_tag`, and the tool deliberately never sees either.

## Suite

`tools/tests/test_firmware_equivalence.py` (offline root `tools/tests`, about 25 s):

1. identity: HEAD (git blobs) vs a directory copy is equivalent; L3 not requested is NOT-RUN;
2. negative controls, each NOT EQUIVALENT at the right layer: one-character lambda edit, changed substitution, swapped sensor
   pair (reported as ORDER), swapped interval pair, hidden Modbus write in an interval (the analyser's finding is carried through),
   one-character header edit, line-ending-only change (L0 fails, L1/L2 still match: nothing normalised), S3 wrapper edit;
3. comparator: `!lambda` vs plain text, `1`/`"1"`/`True`/`1.0`, key order and list order all distinguished;
4. safety: the ESPHome argv set, every subprocess call is git or ESPHome, secrets never read, placeholder secrets only,
   repository-internal outputs refused, `--generate` without cache or permission BLOCKED, the firmware files unchanged;
5. L3 (opt-in: `ECCO_FW_EQUIV_GENERATE=1`, `ECCO_FW_EQUIV_CACHE=<dir>`, about 2 minutes): identity equivalent on L3, and the
   one-character lambda mutant fails `main.cpp` identity for both targets. Without the opt-in it prints SKIPPED and is not a pass.

## Implemented vs proposed

| Item | State |
|---|---|
| L0-L2 static layers, L3 generated layer, baseline JSON, negative controls | implemented |
| `restore_value` globals as the NVS preference surface; header durable tags | implemented (inventory). ESPHome's own preference hashes are covered only indirectly, through `main.cpp` identity |
| Image size (RAM / flash) comparison | **proposed**: needs a full `esphome compile` (cross-compile), which S0 does not run |
| Running L3 in CI | **proposed**: CI already installs ESPHome in the firmware job, but the workflow is out of scope for S0 |
| Order-insensitive equivalence (for a reordering split) | **not planned at S0**: any reordering fails here by design |
| Resolving `packages:` / `!include` in the write-surface analyser | **not started**. The analyser keeps failing closed on them, which this tool reports as an L2 FAIL |

## Limitations

- L1 and L2 read the source text; L3 is the only layer that sees what ESPHome makes of it. A layout-only change can pass L3 and
  still fail L0/L1 (for example moved comments). That is intended: the report shows exactly which layers held.
- The tool proves equality of two **sources**. It says nothing about the hardware, and it does not replace the proof chain, the
  staged deployment kit or a hardware test.
- L3 trusts ESPHome 2026.8.2 as the reference compiler front end. The determinism observations above hold for that version only.
