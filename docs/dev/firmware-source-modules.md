# Firmware S2a: source areas and the assembler

Status: **tooling only.** This adds `tools/assemble_firmware.py`, `tools/firmware_areas.yaml` and the suite
`tools/tests/test_firmware_assembly.py`. It creates and changes **nothing under `firmware/`**, no header, no wrapper, no CI
workflow, no write-surface rule and no proof-chain entry, and it creates no write path. Fragments exist only in temp
directories outside the repository. Nothing here was run on hardware.

**Areas are review and navigation boundaries, not safety isolation.** The ten areas share state: the write mutex
`manual_write_in_progress`, the configuration cache (`manual_cfg_reg*_raw`), the snapshot flags and the 14 ordered
`interval:` items. A Free Power item can read a Dump flag, and an RTC item reads the mutex. Every safety argument is still made
over the whole monolith. An item's area says where to read first, not what it may affect.

The line numbers and counts below are for the monolith the map was reviewed against (LF sha256 `9cb4bd6c…`). They change
when the firmware changes; use the commands, not the numbers.

## Model

The production firmware stays one file, `firmware/ecco_clock_dongle_stage3_4_free_power.yaml`. It is the only file ESPHome, the
write-surface analyser, the S0 checker (`docs/dev/firmware-s0-equivalence.md`) and the proof chain read. The tool adds an
optional **source view** of it.

| Term | Meaning |
|---|---|
| Section | A top-level `key:` line at column 0 and everything under it. A section is a **list section** when its first content line is a `  - ` item (12 of them). |
| Item | One `  - ` entry of a list section (a global, script, sensor, interval, ...). 1,083 in total. |
| Unit | An item, or a section key line with its body, or the file head. |
| Attachment rule | Blank lines and comments at indent 0-2 before an item (or before a section key) belong to the **following** unit, so a region boundary sits before them. A deeper comment (for example `#endif` closing a lambda) stays with the item above. The file-head comment block is its own unit. Lines after the last content line belong to the last unit. |
| Region | A run of whole units. Never starts inside an item. A **non-core** region holds only items of its declared list section (no key line, no non-list section) and is anchored on an item. The FB-A header include must stay in a core region (it is the one declared includer). |
| Marker | The first line of a region in an area file: `#@ecco-region <area>/<section>.<n>`. The grammar may not occur inside the monolith. |
| Manifest | The region list in emission order, one line each: `<area>/<section>.<n> <section> <anchor> [attach=prev]`. |
| Anchor | Where a region starts: `start`, `key:<section>`, `id:<id>`, `name:<name>` or `item:<k>` (0-based index in the section). |
| `attach=prev` | The region starts at the anchor line itself. Its leading comments stay with the previous region. |
| Area file | `<area>.yaml`: the markers and bodies of that area's regions, in order. |

Nothing is normalised. A uniformly CRLF file is read as LF and reported with a warning; a BOM, non-UTF-8, a lone CR, mixed line
endings or a missing final newline are refused (exit 2).

### The ten areas

`python -B tools/assemble_firmware.py --validate-map` prints:

```
area map OK for firmware/ecco_clock_dongle_stage3_4_free_power.yaml: 1083 items in 12 list sections; core 2, telemetry 157, diagnostics 16, modbus 52, rtc 48, arbitration 17, tou 125, free_power 238, dump 213, fallback 215
```

| Area | Items | Content (from `tools/firmware_areas.yaml`) |
|---|---|---|
| core | 2 | Substitutions, `esphome:` (on_boot, header includes), `api`, `ota`, `wifi`, `time`, `uart`, `modbus`, the section key lines. Its 2 items are the `ota` and `time` platform entries. |
| telemetry | 157 | Read-only live telemetry, configuration readback sinks, capability profile entities. No writes. |
| diagnostics | 16 | Wi-Fi signal, lock-age and lock-held diagnostics, debug heap and reset reason, build identity. |
| modbus | 52 | Telemetry and configuration polling, the configuration cache, the Block-B fence. |
| rtc | 48 | NTP and inverter clock reading, the clock correction write and its policy state. |
| arbitration | 17 | The shared write mutex, safety census, lock escalation, restart arm. |
| tou | 125 | Manual TOU slots and the register-244 export-mode policy. |
| free_power | 238 | Free Power override, its snapshot, verified restore and operator recovery. |
| dump | 213 | Dump to Grid, its operating limits, and three Dump-coupled sensors whose `on_value` feeds the Dump guards. |
| fallback | 215 | HA supervision heartbeat, the FB-C failback evaluator, the boot-time marker loads (S1 had them in arbitration; their only reader is the fallback profile review), the fallback profile (review, save, invalidate). |

The map lists runs of consecutive items per area (`runs:` in the YAML), each with `n`, and `# why:` notes for non-obvious
calls (for example `ntp_synced` is written by `time` in core but is RTC state, so it is in rtc). Two runs, 81 globals and 5 text
sensors of the FB-C failback evaluator, are anchored by index instead of id (see Limits).

## Commands

Run from the repository root. Every write goes only to a caller-given path **outside the repository and outside any git work
tree** (another ECCO checkout included). Containment is decided by file identity of every existing ancestor, so case variants,
`..`, short names and junctions cannot escape it; Windows device and UNC forms (`\\?\...`, `\\server\...`) are refused, and so
is an existing `--out`. An I/O failure is exit 2, never "stale".

| Command | Reads | May write | Purpose |
|---|---|---|---|
| `--validate-map` | monolith, `tools/firmware_areas.yaml` | nothing | The map covers every item once, in order, with the right counts |
| `--map [--area A] [--items]` | monolith, map | nothing | Region table (lines, bytes, items, first/last) or one row per item |
| `--where ARG` | monolith, map | nothing | Item, area and fragment position for a line, `yaml:N`, `file.yaml:N`, `#line N "..."` or a device-log header |
| `--lookup ID` | monolith, map | nothing | Where an id is defined; which areas assign, call, read it |
| `--xref [--area A]` | monolith, map | nothing | Ids defined in one area and used in another |
| `--diff-regions BASE [--head REV]` | git blobs (`git cat-file`), map | nothing | Items added, removed or changed between two revisions, by area |
| `--plan [--areas ..] [--sections ..] [--lines A-B,..] [--out FILE]` | monolith, map | `--out FILE` only (must not exist); else stdout | Candidate manifest |
| `--split --manifest FILE --out DIR` | monolith, manifest | new `DIR` (area files and `manifest.txt`) | Cut the monolith into area files |
| `--check --fragments DIR --manifest FILE` | fragments, manifest, monolith | nothing | Assemble and compare with the monolith |
| `--write --fragments DIR --manifest FILE --output PATH` | fragments, manifest | a new `PATH` only (an existing file is refused); never the canonical monolith | Write the assembled text |

Common options: `--monolith PATH` or `--rev REV` (default: the working-tree monolith), `--areas-file PATH`, `--strict-map`
(refuse a map reviewed against another monolith; otherwise it only warns), `--json`.

Exit codes: **0** ok or equal; **1** stale (well-formed but different; `--check` prints the first differing monolith line and
the fragment it came from); **2** input or structure error, fail closed (`refused: ...` on stderr).

`--map` and `--where` use the all-areas plan derived from the map unless `--manifest` is given. Without a manifest, `--where`
labels the position `fragment_if_full_plan`: where the line would sit under that plan, not a real file.

## Worked navigation

Output is trimmed to the essential lines. The CRLF warning line and the path prefix are omitted.

### (a) Free Power restore

Start from the snapshot flag.

```
$ python -B tools/assemble_firmware.py --lookup free_power_snapshot_valid
free_power_snapshot_valid: defined at line 2175 (globals, area free_power)
  arbitration  read 2x (first 20665)
  core         assign 6x (first 536); read 4x (first 715)
  dump         read 2x (first 18061)
  fallback     read 9x (first 21321)
  free_power   assign 5x (first 9164); read 14x (first 6212)
  modbus       read 1x (first 16666)
  tou          read 39x (first 13716)
  cross-area: arbitration, core, dump, fallback, modbus, tou
```

The flag is owned by free_power but read in six other areas, including 39 reads in tou. The first free_power assignment (line
9164) is in a script. List the area's scripts:

```
$ python -B tools/assemble_firmware.py --map --area free_power --items      # script rows
9940    10159   220     free_power      script  id:restore_free_power_snapshot
10160   11403   1244    free_power      script  id:restore_free_power_snapshot_dispatch
```

```
$ python -B tools/assemble_firmware.py --lookup restore_free_power_snapshot_dispatch
restore_free_power_snapshot_dispatch: defined at line 10178 (script, area free_power)
  fallback     read 6x (first 21328)
  free_power   call 1x (first 10144)
  cross-area: fallback

$ python -B tools/assemble_firmware.py --where 10144
item: id:restore_free_power_snapshot
item_lines: [9940, 10159]
area: free_power
text:                             id: restore_free_power_snapshot_dispatch
```

So `restore_free_power_snapshot` (lines 9940-10159) starts the dispatch script at line 10144, and the dispatch body is lines
10160-11403. The fallback area reads it; no other area calls it.

### (b) Dump to Grid start

```
$ python -B tools/assemble_firmware.py --lookup dump_write_enable
dump_write_enable: defined at line 5890 (switch, area dump)
  dump         call 2x (first 18133); read 2x (first 18051)
  fallback     read 3x (first 21303)
  cross-area: fallback

$ python -B tools/assemble_firmware.py --map --area dump --items      # script rows only
17957   18923   967     dump    script  id:start_dump_to_grid_override
18924   19726   803     dump    script  id:dump_controller_tick
19727   20564   838     dump    script  id:restore_dump_to_grid_snapshot
20565   20624   60      dump    script  id:request_dump_end
20742   20778   37      dump    script  id:dump_clear_verified_marker
20779   20812   34      dump    script  id:dump_force_restore_original
20813   20961   149     dump    script  id:dump_accept_current_state
20962   21258   297     dump    script  id:dump_lockout_containment
```

`dump_write_enable` is the arming switch; the start script (17957-18923) reads it and calls it at line 18133. To see what Dump
takes from other areas:

```
$ python -B tools/assemble_firmware.py --xref --area dump
(id)                owner      line  used by
configuration_online        modbus    6153  core(call), dump(read), fallback(read), free_power(read), tou(read)
correction_in_progress      rtc       1738  arbitration(read), diagnostics(read), dump(read), fallback(read), ...
ecco_inverter_power         telemetry 8047  dump(read), modbus(call)
ecco_battery_power          dump      7409  modbus(call)
```

(Columns are tab separated: id, owning area, definition line, users with the kinds of use. The header row above is added for
reading; the tool prints none. 82 rows for this area, filtered here.) Dump reads `ecco_inverter_power`, a telemetry sensor
defined at line 8047, and it reads the RTC flag `correction_in_progress`. Follow the first Dump use of the inverter power:

```
$ python -B tools/assemble_firmware.py --where 19016
item: id:dump_controller_tick
item_lines: [18924, 19726]
area: dump
text:           bool ecco_feas_inv_ok = id(ecco_inverter_power).has_state() &&
```

### (c) RTC write

```
$ python -B tools/assemble_firmware.py --lookup correction_in_progress
correction_in_progress: defined at line 1738 (globals, area rtc)
  arbitration  read 1x (first 20655)
  ...
  dump         read 8x (first 18056)
  modbus       read 9x (first 16294)
  rtc          assign 9x (first 8696); read 6x (first 23048)
  tou          read 16x (first 13698)
  cross-area: arbitration, diagnostics, dump, fallback, free_power, modbus, tou
```

Only rtc assigns the flag; seven other areas read it. The write script is `write_inverter_rtc` (lines 8674-8794). Its Modbus
write call sits at line 8711:

```
$ python -B tools/assemble_firmware.py --where 8711
item: id:write_inverter_rtc
item_lines: [8674, 8794]
area: rtc
text:                   - modbus_client.write_multiple_registers:
```

**Reading a device log header.** ESPHome writes a log line as `[L][tag:NNN]`. For a source line above 999 the logger prints four
characters: the thousands digit is written as the character `'0' + thousands`, followed by the last three digits. So 25634
prints as `I634` (`chr(ord('0') + 25) = 'I'`), and 22837 prints as `F837` (`chr(48 + 22) = 'F'`). Below 10,000 the first character
is still a digit; at exactly 10,000 it is `:`. `--where` reverses this:

```
$ python -B tools/assemble_firmware.py --where "[W][ecco:F837]"
monolith_line: 22837
item: id:read_inverter_clock
item_lines: [22809, 23165]
area: rtc
text:                     ESP_LOGW("ecco", "Invalid inverter RTC data received");

$ python -B tools/assemble_firmware.py --where "[I][rtc:I634]"
monolith_line: 25634
item: item:13
area: tou
```

**Which log lines map back to the YAML.** The header carries the C++ `__LINE__`. Only code inside a YAML lambda is emitted with a
`#line N "<yaml file>"` directive (1,248 of them in the generated `main.cpp`), so only an `ESP_LOGx` call **inside a lambda**
reports a YAML line, as in the first example (a real `ESP_LOGW` of the RTC button `read_inverter_clock`). A YAML `logger.log:`
action is generated as plain C++ without a directive, so its header line is a line of the generated `main.cpp`, not of the
YAML: decoding it here gives a meaningless position. The headers above are composed for the example, not captured from a device
(this reading of ESPHome 2026.8.2's code generator was not checked on a real build). The second example also shows that the
**tag in the header does not give the area**: `I634` is line 25634, the last line of an interval in tou. Always decode the line.

An ESPHome error position uses the plain file name and line:

```
$ python -B tools/assemble_firmware.py --where ecco_clock_dongle_stage3_4_free_power.yaml:8711
monolith_line: 8711
item: id:write_inverter_rtc
area: rtc
```

`--where` also accepts a bare line number, `yaml:8711`, a `#line 8711 "..."` directive, the parser forms `in "x.yaml", line 8711`
and `x.yaml 8711:5`, and a fragment position such as `rtc.yaml:296` or `firmware/src/rtc.yaml:296`. A fragment position needs
the `--manifest` that produced the fragments; without it the tool refuses (exit 2) rather than guess.

## Measuring a split locally

Use a new temp directory outside the repository. Nothing is created in the repository.

```
$ python -B tools/assemble_firmware.py --plan --areas telemetry --sections sensor --out <tmp>/m.txt
wrote 9 regions -> <tmp>/m.txt
$ python -B tools/assemble_firmware.py --split --manifest <tmp>/m.txt --out <tmp>/frag
split firmware/ecco_clock_dongle_stage3_4_free_power.yaml into 2 area files, 9 regions -> <tmp>/frag
$ python -B tools/assemble_firmware.py --check --fragments <tmp>/frag --manifest <tmp>/m.txt
EQUAL: 9 regions reassemble firmware/ecco_clock_dongle_stage3_4_free_power.yaml byte for byte (LF sha256 9cb4bd6c...)
```

Exit code 0. `<tmp>/frag` holds `core.yaml` (24,666 lines), `telemetry.yaml` (977 lines) and `manifest.txt`. The derived telemetry
sensor plan has **4** telemetry regions (`telemetry/sensor.1` to `.4`); everything between them stays in `core.yaml` so that the
file still reassembles in order. Delete `<tmp>` afterwards.

Review aid for a firmware PR (reads git blobs only):

```
$ python -B tools/assemble_firmware.py --diff-regions origin/main
no item changed
```

With changes, each row is `added | removed | changed`, the area, the section, the item, and its line ranges at head and base.

## Proposed S2b edit workflow (not approved; needs a separate owner decision)

S2b would move the fragments to `firmware/src/` and keep the monolith as a checked-in generated file. This is a proposal only.

1. Edit a fragment under `firmware/src/`.
2. Regenerate the assembled text with `--write --output <tmp>/assembled.yaml` and copy it over the monolith (the tool never writes the canonical monolith itself).
3. Run `--check --fragments firmware/src --manifest <manifest>`; it must exit 0.
4. Declare the monolith change in the proof chain exactly as today. The chain, ESPHome, the analyser and the S0 checker still
   read only the monolith.
5. The reviewer reads the **monolith hunk** for any change in a writer area (rtc, arbitration, tou, free_power, dump, fallback,
   modbus), not only the fragment hunk.

Layout-only PR checklist: monolith sha256 unchanged; `tools/tests` green; full CI green; `--check` exit 0.

**Rollback for S2a:** revert the PR. No firmware file and no proof-chain file is involved, so nothing else changes.

## What the suite proves, and what it does not

`tools/tests/test_firmware_assembly.py` pins no firmware shape (the S0 C1 policy). Plans, anchors and mutation sites are
derived from the checked-out monolith (git HEAD blob) and the map. All comparisons are byte-exact.

| Check | Proves |
|---|---|
| Model | The layout parser finds the same items, ids and order as PyYAML; the map covers every item once, in order, with ten areas |
| A1-A8 | For a pilot plan and the full ten-area plan: assembly equals the monolith and region bytes sum to its size (A1); coverage, uniqueness, order (A2); sections, anchors, unit boundaries, no marker grammar in the monolith, the `attach=prev` override (A3); a re-split reproduces every file (A4); determinism across runs, creation order and hash seeds (A5); every area file parses and item order and digests match (A6); the FB-A include line is exactly once, in `core.yaml` (A7); `--where` decodes log headers including lines above 9,999 (A8) |
| N1-N14 | Each refused with the expected exit code: a 1-byte fragment edit; a monolith-only edit; swapped, dropped, duplicated manifest lines; an unknown fragment file; marker grammar inside a region; lone CR, mixed EOL, BOM, missing final newline; out-of-order regions; a wrong section label; non-UTF-8; a preamble; the include line moved or duplicated; a region starting inside an item |
| Paths, EOL, map rules, safety | Outputs inside the repository or any git work tree, the canonical monolith (also in `\\?\` form), an existing `--out` or `--output`, a hostile region name and a symlinked fragment are refused, each with its reason. CRLF is read as LF. A wrong run count, anchor, area or section in the map is refused; a monolith the map does not cover yet still navigates (core labels, warning). A static AST scan of the tool (imports, no from-import or alias of `os`/`subprocess`, the only subprocess `git cat-file blob`, no `eval`/`exec`/`open()`, file-mutation calls only in the CLI handler) with its own negative control. The tracked `firmware/` files are byte-identical before and after |

Because nothing is pinned, **the map must cover HEAD**. A firmware PR fails `tools/tests` unless it keeps
`tools/firmware_areas.yaml` in step, in any of these cases:

- it adds or removes an item: update that run's `n`;
- it inserts or removes an item **before an index anchor** (`index:510` globals, `index:6`/`index:68` text sensors, `index:14`
  sensors): those anchors move. **Any interval added or removed renumbers every later interval run** (all 14 are `index:N`);
- it renames an id used as a run's `first` or `last`;
- it uses YAML the layout parser refuses (a column-0 key outside `[a-z_][a-z0-9_]*`, list items at an indent other than 2).

`--validate-map` names the run to fix. A map reviewed against another monolith only warns (fails with `--strict-map`), and
navigation keeps working on an uncovered monolith (everything labelled core, with a warning), so `--diff-regions` can still review
such a PR.

**Not proved:**

- Device behaviour. The tool proves equality of **text**, not what the firmware does. It does not replace the proof chain, the S0
  L3 generated-code comparison, the staged deployment kit or a hardware test. ESPHome is not run on the assembled text.
- That an area label is right. Labels are a reviewed classification, not a derived fact. In `cross_area`, `written_by`, `read_by`
  and the notes are not checked mechanically; `--lookup` is checked for the owner area and a non-empty cross-area list only.
- `--lookup` and `--xref` are a heuristic text scan: comments are stripped and C++ is not parsed. A reference built from a
  string, a macro or an indirect call is not seen; the read/assign/call split is a guess from the method name.
- The device-log decoding is checked against the logger's encoding formula, not against captured device output.
- The AST scan is a static guard, not a sandbox (for example `str.replace` and `Path.replace` look the same to it).
- The S2b workflow (fragments committed under `firmware/src/`) is not exercised: nothing is committed there at S2a.
- Junction, short-name and case-variant escapes are handled by the file-identity guard but not covered by a test; the symlink
  refusal is exercised on Linux CI only (Windows needs a privilege to create symlinks, so the check is skipped there).
- Safety isolation. See the top of this page.

## Limits and notes

- **Index anchors.** The 81 globals and 5 text sensors of the FB-C failback evaluator are anchored as `index:N` in the map,
  not by id. The FB-C core suite's Z5 non-authority pin forbids any file under `tools/` from spelling that evaluator's id
  prefix. The tool still prints the real ids at run time.
- **CRLF working copy.** A Windows checkout with `core.autocrlf` has CRLF line endings. The tool reads a uniformly CRLF file as
  LF, prints one warning and hashes the LF text. Line numbers are identical in both forms.
- **Not implemented.** S1 also named `--resplit` (a re-split is `--split` with the existing manifest into a new directory)
  and an optional `--adopt` (fold a monolith edit back into its fragment). `--adopt` is not built; it is for S2b at the earliest.
- **The blank-line span.** S1 named the last telemetry sensor region as lines 7955-8672. The derived region is 7955-8671,
  because the blank line 8672 attaches to the following `script:` key (`core/script.1`, lines 8672-8673). Reproducing S1's span
  needs `attach=prev` on the `script` region.

## Residual UNKNOWNs

| Item | State |
|---|---|
| S2b proof-chain entry (named `fws2` here) | UNKNOWN. Not written. Whether it must list the new `firmware/src` files under `added_files`, and whether the chain accepts a file that only exists at S2b, is not established. |
| Pilot size | Owner decision. The derived plan has **4** telemetry sensor regions (115 items); one of them holds a lambda (`inverter_tou_power_ceiling`, which returns a substitution value). S1's **2** regions (112 template sensors, no lambda) are `--plan --areas telemetry --sections sensor --lines 7642-7868,7955-8671`. |
| S2b itself | Not approved. Everything under "Proposed S2b edit workflow" is a proposal. |
