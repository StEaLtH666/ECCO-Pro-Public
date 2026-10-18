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
| L2 authority (**classic only**) | `tools/analyze_write_surface.analyze()` (unchanged, imported read-only) on the production YAML of each side: every write path, its Modbus operations, ownership flags, arm switches, obligations and dispatches. Fails if **either** side has a write of unknown extent or an unclassified bus access, even if both sides agree. The S3 wrapper is not analysed here (it only pulls production in as a package); it is covered by L0, its own L1 inventory and L3 | Python |
| L3 generated | `esphome config` and `esphome compile --only-generate` for the classic and the S3 target: the whole generated `src/` tree byte for byte (`main.cpp`, `esphome/core/defines.h` and every other file), the validated configuration, and `ESPHOME_CONFIG_HASH` | ESPHome **2026.8.2** exactly (`--generate`) |

### L3 determinism and safety controls (all declared)

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
- **Network: detected, not blocked.** The optional L3 generation runs ESPHome, and ESPHome / PlatformIO may download
  library sources (observed: noise-c and libsodium from the PlatformIO registry). L3 runs only with `--esphome-cache DIR`
  (a `pio_components/` seed copied into each sandbox, no download expected) or with `--allow-toolchain-downloads`. The tool
  **detects** downloads by scraping ESPHome's log for `Downloading <url>` lines. It reports each URL and FAILS on a logged
  download despite a seeded cache. It does **not** block or isolate the network. PlatformIO and user caches outside
  `ESPHOME_DATA_DIR` are not sandboxed, and traffic ESPHome or PlatformIO does not log is not seen. Anyone who needs a
  guaranteed offline run must isolate the machine or process from the network themselves. With `--allow-toolchain-downloads`
  and an empty `--esphome-cache`, the first run fills the cache. L0-L2 run no external process except `git`.
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

Static layers take about 5 s per comparison. L3 takes about 1 minute (four ESPHome runs).

## Baseline recorded at S0 (2026-10-18)

`--before d1c9a3e1 --after 555cf859` (the source of the Build Identity of the live image vs public main): **45 PASS, 0 FAIL**.
This is a dated **record**, not a test expectation: the suite pins none of these numbers.
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

`tools/tests/test_firmware_equivalence.py` (offline root `tools/tests`, about 65 s locally, no ESPHome needed):

**No firmware shape is pinned (owner decision C1, 2026-10-18).** Every expectation and every mutation anchor is derived from
the checked-out firmware (git HEAD blobs). Each derived mutant has a precondition: re-parsing it must show exactly the intended
change and nothing else, otherwise the suite FAILS and does not fall back to a weaker mutant. A firmware PR that legitimately adds
a global or edits an anchor line therefore does not turn `tools/tests` red. The tool's comparison stays strict: any difference
between the two sides FAILS.

1. identity: HEAD (git blobs) vs a directory copy passes every L0-L2 row; L3 not requested is NOT-RUN; the tool's inventory
   equals counts derived from HEAD with a separate YAML reader (not the tool's);
2. negative controls derived from HEAD, each NOT EQUIVALENT at the right layer: one-character lambda edit, changed substitution,
   swapped sensor pair (reported as ORDER), swapped interval pair, hidden Modbus write in an interval (the analyser's finding is
   carried through), one-character header edit, line-ending-only change (L0 fails, L1/L2 still match: nothing normalised),
   S3 wrapper edit;
3. comparator: `!lambda` vs plain text, `1`/`"1"`/`True`/`1.0`, key order and list order all distinguished;
4. safety: an AST scan of the tool (allow-listed imports; no `eval`/`exec`, `os.system`, `Popen`, `shell=`; every
   `subprocess.run` is git or `ESPHOME_COMMANDS`), with its own negative control; the ESPHome argv set; secrets never read,
   placeholder secrets only; repository-internal outputs refused. The L3 **version gate** and **cache gate** are each exercised
   with ESPHome **stubbed**, so the result is the same on a machine with ESPHome (this PC) and without it (the CI offline job).
   The stub also proves generation is never reached. The firmware files are unchanged by the suite;
5. L3 (opt-in: `ECCO_FW_EQUIV_GENERATE=1`, `ECCO_FW_EQUIV_CACHE=<dir>`, about 2 minutes): identity equivalent on L3, and the
   lambda mutant fails `main.cpp` identity for both targets. It runs real ESPHome, which may use the network (detected from
   the log, not blocked). Without the opt-in it prints SKIPPED and is not a pass;
6. C1 proof: a hypothetical future firmware (one more global, an edited substitution, lambda line, header and wrapper, built
   by the same derived helpers) is used as the baseline. Identity holds, the derived inventory follows it, HEAD vs it is
   NOT EQUIVALENT, and every derived mutant of it is still caught.

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

- **Proof gaps for S1 (recorded, not addressed at S0).** The directory and git loaders read only top-level `firmware/*.yaml` and
  `firmware/include/*.h`, and L1/L2 do not resolve `packages:` / `!include`. A split into sub-files would be partly invisible
  to L0 and would FAIL L1/L2 by design. Only L3 could show equivalence for a split, and L3 is local, opt-in and depends on the
  sandbox path. S1 needs include-aware L0/L1 and a CI decision on L3 first.

- L1 and L2 read the source text; L3 is the only layer that sees what ESPHome makes of it. A layout-only change can pass L3 and
  still fail L0/L1 (for example moved comments). That is intended: the report shows exactly which layers held.
- The tool proves equality of two **sources**. It says nothing about the hardware, and it does not replace the proof chain, the
  staged deployment kit or a hardware test.
- L3 trusts ESPHome 2026.8.2 as the reference compiler front end. The determinism observations above hold for that version only.
