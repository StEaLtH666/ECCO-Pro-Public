# Assurance lab V0.1: offline cross-domain scenarios

Status: **offline, test-only.** Every result in this document comes from simulators that run the repository's own firmware and
Home Assistant source. Nothing was run on a dongle, an inverter or a Home Assistant instance. The lab changes no production
behaviour.

This document describes version **V0.1** of the lab. The file keeps its V0 name. V0.1 applies the corrections that the
independent audit of 2026-10-19 asked for (items B1 to B7 of its implementation brief). It changes no production file:
only the lab's own files, this document and `docs/dev/assurance-lab-v0/LAB_SUMMARY.txt`. Section 14 reconciles every V0
headline number with its V0.1 value, with units. Section 15 lists the known open items. Where this document says "the V0.1
review", it means the lab's own review of these corrections before they were committed, whose findings are corrected
here; that review is not the independent validation.

An independent re-check of V0.1 took place on 2026-10-21. Among its observations was one gap in the lab's mutation
coverage, W6-1: a mutation that stops the Dump restore verifying one of the slots 256, 257, 258, 259 or 261 failed no
behavioural check in any suite, because only the whole 256-261 block and slot 260 alone had a readback-mismatch scenario.
The W6-1 correction (test code only) adds six per-slot scenarios, FW-09 b3-256 to b3-261, with six corpus documents and
eight catalogued slot mutants: the 8 named per-slot mutants (C6k0 to C6k5, C6s0, C6s5) are killed on the
non-containment per-slot plan (sections 7 and 9). An internal review of that correction found six further per-slot
verify regressions that still survived all 14 suites. The W6-1b correction (test code only, a follow-up of W6-1) adds
seven FW-09 scenarios, b4-ct, b4-cb, b4-co, b5-lo, b6-ok, b6-x257 and b6-x260, with seven corpus documents and six
catalogued mutants, one per survivor (C6bf, C6om, C6lt, C6r1, C6r4, C6v34): the 6 survivors are killed on the modelled
shapes, the containment path, a readback above the expected value and pairwise-distinct slot originals (sections 7 and
9). An internal review of the W6-1b correction found four containment-claim regressions that still survived all 14
suites. The W6-1c correction (test code only, the final correction cycle) adds five FW-09 scenarios, b7-rbnr, b7-rber,
b7-cmnr, b7-ab and b7-af, with five corpus documents, a containment-claim truthfulness helper applied to every FW-09
timeline and four catalogued mutants, one per survivor (C6rh, C6rn, C6rs, C6m0): the 4 survivors are killed on the
modelled shapes, a failed 256-261 readback in containment, a verified containment attempt followed by a failed one and a
containment with every 256-261 slot FOREIGN (sections 7 and 9). In all, the 8 W6-1, 6 W6-1b and 4 W6-1c mutants are
killed on the modelled shapes; what remains open is section 15, items 15 and 16. After W6-1c the owner stopped the
mutation search: no further correction cycle is started, and a final independent audit of the completed candidate
followed (section 15, item 11). Section 14 gives every number the three corrections moved. The final
independent audit (2026-10-22) re-applied these mutants on disk in its own forms and found them killed (section 15,
item 11).

**What V0.1 changed.**

- **Drift rule and baseline (B1).** A changed pinned file is judged by its tier (section 2.8). A non-behavioural file (a
  document read only for anchor texts) prints SOURCE DRIFT and passes. A behavioural file (the firmware, the packages, the
  simulators, the registry modules the lab imports) fails with a message that names the file, the corpus documents that
  replay it and the re-record procedure. A lab file fails until the catalogue is regenerated. A deleted pinned file fails
  in every tier. The baseline now pins every behavioural file the lab reads at run time, found by an audit-hook trace that
  `trace_inputs.py` repeats, and every corpus document pins its tier's behavioural sources. Every suite ends with a
  run-time import guard, and the catalogue is written only from suite outputs that record the tree they ran on.
- **CRLF (B2).** Line endings are normalised in the test code. `.gitattributes` is unchanged.
- **Mutation coverage (B3).** A new suite, `test_lab_fw_guards` (FW-09 to FW-11), kills the audit mutants M9, C6, M7, C3
  and C7 with named directed checks. Two survivor rationales are corrected. The catalogue records which control rows
  repeat a mutation: 115 control rows over 95 distinct mutations (section 9; 111 over 91 before the W6-1c correction,
  105 over 85 before the W6-1b correction and 97 over 77 before the W6-1 correction).
- **Simulator and oracle assumptions (B4).** Four new harness limitations, HL-10 to HL-13 (section 5.2). The real scope of
  "fail loud", with a measured register of silent divergences (section 2.7). Per-outcome projection windows, a refusal of
  a press the lab would drop wrongly (section 2.6), and a static guard against package options the HA interpreter ignores
  (section 2.7).
  HL-1 fixed at the root. Every check that depends on the lab's scheduler phase is tagged and counted (section 2.5).
  Under an ESPHome-like phase patch the property suite and the firmware self-test, which used to stop, now end with a
  LAB-SUMMARY in which every failure is named and tagged.
- **NVS fault realism (B5).** An NVS fault is injected only on a key stored earlier in the run, after a completed lease
  (section 2.4).
- **Classifications and counts (B6).** A suite output contract with explicit units (section 3), runner cross-checks, the
  audit's re-classifications, two-axis verdicts for every counted finding (section 4), audit notes per root cause
  (section 8) and corrected texts.
- **CI portability and runtime (B7).** The 90 s per-suite budget applies to sequential runs only. A failing suite names
  its failed checks in its last lines. LAB-SUMMARY reports whether zoneinfo was usable. A firmware self-test no longer
  crashes on a production change. Section 12 describes the PR-time Linux validation.
- **Per-slot restore verify (W6-1).** The Dump restore verifies its 256-261 readback slot by slot. Six directed scenarios,
  one per slot, make that slot's single-register writes acknowledged but not applied next to a FOREIGN slot, so the
  restore writes per slot; each expectation is cited from the firmware source. On that non-containment per-slot plan
  they kill the slot mutants C6k0 to C6k5 and the loop-bound mutants C6s0 and C6s5 (section 9). No counted finding
  changed. An internal review of the correction found six further per-slot verify regressions that survived it; W6-1b
  kills them (next item).
- **Containment, readback above the expected value and slot cross-wiring (W6-1b).** Seven directed FW-09 scenarios,
  each expectation cited from the firmware source: b4-ct, b4-cb and b4-co run the restore on the containment path
  (register 244 acknowledged but not applied) with one slot's floor write, the 6-slot floor block, or the floor write of
  a slot that reads its ORIGINAL acknowledged but not applied; b5-lo leaves unapplied a slot whose original is below the
  lease power; b6-ok, b6-x257 and b6-x260 restore pairwise-distinct originals, fault-free or with the lease power equal
  to a neighbour's original. They kill the six survivors of the W6-1 review (C6bf, C6om, C6lt, C6r1, C6r4 and C6v34;
  section 9) on these modelled shapes. No counted finding changed; what remains is section 15, item 15. An internal
  review of the correction found four containment-claim regressions that survived it; W6-1c kills them (next item).
- **Containment-claim truthfulness (W6-1c, the final correction cycle).** Five directed FW-09 scenarios, each
  expectation cited from the firmware source: b7-rbnr and b7-rber run the containment path with the 6-slot floor block,
  or slot 258's floor write next to a FOREIGN 261, acknowledged but not applied and a 256-261 readback that gets no
  response or an error; b7-cmnr reaches the comms path in containment (244's verify read errors); b7-ab is a verified
  containment attempt followed by a failed one; b7-af contains with every 256-261 slot FOREIGN. A truthfulness helper
  checks every containment claim of every FW-09 timeline against the bank as it stood when the status was published.
  They kill the four survivors of the W6-1b review (C6rh, C6rn, C6rs and C6m0; section 9) on these modelled shapes. No
  counted finding changed; what remains is section 15, item 16. The owner stopped the mutation search after W6-1c; a
  final independent audit of the completed candidate followed (section 15, item 11).

Code: `registry/tests/assurance_lab/`. It holds five helpers (`_lab_clock.py`, `_lab_trace.py`, `_lab_fw.py`, `_lab_rtc.py`,
`_lab_ha.py`), 14 suites (`test_lab_*.py`), four command-line tools (the runner `run_lab.py`, the catalogue generator
`gen_catalogue.py`, the corpus re-record tool `rerecord_corpus.py` and the input trace `trace_inputs.py`), the generator's
two helper modules (`_catalogue_data.py`, the hand-written catalogue fields; `_catalogue_ast.py`, the static reader of the
suite tables), 115 replay documents (`corpus/*.json`) and the machine-readable index `SCENARIO_CATALOGUE.json`, which
`gen_catalogue.py` generates (section 11). The runner's generated report is `docs/dev/assurance-lab-v0/LAB_SUMMARY.txt`. The catalogue is the
authoritative list of scenarios, findings, root causes, negative controls, coverage, unsupported items, harness
limitations and source tiers. This document explains the design and summarises the catalogue. Where the two differ, the
catalogue and the suite sources win.

## 1. Purpose and scope

The existing offline suites test one layer at a time, often against a hand-written model of the other layers: the firmware
against a fixed inverter image, the Home Assistant packages against hand-written dongle models, the RTC policy against a rig with
no lease. The lab runs the layers together and adds what single-layer suites cannot express: reboots and power cuts at chosen
events, durable-commit faults, Home Assistant restarts with helper rollback, owner edits that race a schedule, and the two
Europe/London clock-change nights on a UTC-true timeline.

**What "real source" means here.**

| Layer | Source that runs | Engine |
|---|---|---|
| Firmware | `firmware/ecco_clock_dongle_stage3_4_free_power.yaml`: the Free Power and Dump to Grid START / END / restore / recovery / containment scripts, both 15 s watchdogs, the FULL `on_boot` (every runtime item except the FB durable boot read, which does not transpile; section 5, item 12), the manual TOU and register 244 Load / Apply / Restore buttons, the real poll scripts and their failure handlers | `registry/tests/_dump_sim.py` (parsed ESPHome action trees and the C++-subset transpiler) |
| Home Assistant | `home-assistant/packages/ecco_free_power_schedule.yaml` (FPS1), `ecco_dump_to_grid_schedule.yaml` (DGS1), `ecco_schedule_manual_restore.yaml` (SMR1) | `home-assistant/tests/_ha_script_sim.py` |
| RTC | the firmware's RTC read / correction lambdas, with `ecco_rtc::` resolved to the Python mirror `registry/rtc_policy.py` | `registry/tests/_fbd1_harness.py` (`make_rig`, D1Sim) |

The lab never re-implements a control decision. It supplies the environment (clock, inverter register bank, telemetry image,
latencies, faults, owner actions) and observes. Where a construct cannot run, the lab labels it (MODEL, NOT MODELLED,
UNSUPPORTED) instead of guessing. Where the lab cannot tell that it differs from the device, section 2.7 says so.

**What it is not.**

- **Not a digital twin.** There is no inverter physics. The site is synthetic. Timings are model parameters.
- **Not hardware evidence.** A PASS means: this source, under the stated models, behaves as described. It does not show that the
  device does the same. A green CI run of these suites is not hardware evidence either.
- **Not a fix.** Findings are reproduced, classified and given a smallest safe repair scope as a description. Nothing is
  implemented here, and each repair needs its own reviewed change.
- **Offline only.** No network, no Home Assistant, no inverter, no Modbus, no SSH, no InfluxDB, no OTA. The suites write nothing:
  they print to stdout. Every suite and every command-line tool sets `sys.dont_write_bytecode = True` before its first
  non-standard-library import, and `test_lab_selftest_core` [13] checks that statically.

**The synthetic site** (`_lab_fw.SITE`; synthetic choices, not measured values; 8000 W is the firmware's documented
architectural maximum, `docs/dev/dump-to-grid-ceiling.md`):

| Item | Value |
|---|---|
| Register 244 (export mode) ORIGINAL | 2 |
| 256-261 (slot power) | 8000, 8000, 7000, 8000, 8000, 5000 |
| 230 / 232 | 120 A / 0 |
| 250-255 (slot start, HHMM) | 0, 400, 800, 1300, 1800, 2100 |
| 268-273 (slot SOC) | 20 each |
| 274-279 (slot charge source) | 1, 0, 0, 0, 0, 0 (slot 1 grid charge 00:00-04:00 only) |
| Battery | 52 V, SOC 70 % |
| Dump environment | grid CT -1000 W, battery 1050 W |
| Dump limits | ceiling 8000 W, maximum export 8000 W |

Dates are synthetic calendar choices too. Most ordinary-day scenarios use 2026-10-21 (BST) and 2026-11-04 (GMT); a few use
nearby days (PB-03-a starts on 2026-10-20; in HF-02 the owner moves a start to the next day, 2026-10-22, and HF-04 also
tries a Dump arm for that day; a firmware self-test checks GMT on 2026-11-02). The DST scenarios use the two clock-change
nights 2026-10-25 and 2027-03-28, some starting on the evening before (2026-10-24 in HF-08-c and RT-02-a); the DST suite uses
2026-10-18 and 2027-03-21, one week before each change, as its ordinary-night controls. The time-property sweeps cover
2026-01-01 to 2027-12-31, including the changes of 2026-03-29 and 2027-10-31.

## 2. Architecture

```
            synthetic inputs: SITE bank, telemetry, owner actions, faults, latencies
                                           |
      +------------------------------------+-------------------------------------+
      |                                    |                                     |
 firmware tier                        coupled tier                           rtc tier
 FirmwareWorld (_lab_fw)              CoupledWorld (_lab_ha)                 RtcWorld (_lab_rtc)
 StrictSim over ds.Sim                S.World + S.HA(real FPS1/DGS1/SMR1)    make_rig (D1Sim)
 real firmware YAML                     | service calls                      real RTC lambdas
 full-boot reboot primitive             v                                    + rtc_policy.py mirror
 NVS / Modbus / link faults           RealDongle (the one adapter)           + real FP START and
                                        |                                      15 s FP watchdog
                                        v
                                      one FirmwareWorld (CoupledFirmware)
      |                                    |                                     |
      +-------------- one EventLog per world (_lab_trace, digest) --------------+
                                           |
            invariant checkers -> PASS / FINDING lines -> FAILED line -> LAB-SUMMARY line
                                           |
            corpus/*.json replay documents (replay DSL, trace digest, tiered drift rule)
```

### 2.1 The three tiers

| Tier | Engine | What is real | Main models |
|---|---|---|---|
| firmware | `FirmwareWorld` over `ds.Sim` | one firmware: both START scripts, both watchdogs, every executable interval, the FULL `on_boot` except the FB durable boot read (section 5, item 12) | synthetic bank and telemetry; synchronous scripts (HL-11); the scheduler phase (HL-10); injected RTC lock windows |
| coupled | `CoupledWorld`: the HA interpreter with the three real packages, and one `RealDongle` adapter over one `FirmwareWorld` | every HA decision (packages) and every dongle decision (firmware) | latencies, bus model, projection of synchronous firmware runs (sections 2.6 and 2.7, HL-12), HA restore-state, reconnect and service-call fault ASSUMPTIONS |
| rtc | `RtcWorld` over `_fbd1_harness.make_rig` (D1Sim) | the RTC read / correction lambdas, the Free Power START and its 15 s watchdog | Python policy mirror; exact NTP clock; inverter clock as offset + rate; no `on_boot` |

The two hand-written dongle models of the HA suites (`S.Dongle`, `D.DumpDongle`) are not used by the coupled tier; section 5.1
lists where they differ from the firmware. `RealDongle`
maps every dongle entity id the three packages use (36 ids, 12 of them assembled TOU slot ids) onto a firmware entity, script or
button by the slug rule; an unmapped id raises `S.Unsupported`.

### 2.2 Timeline and London time

- The true timeline is the **UTC epoch in seconds** (int, or float for sub-second instants). Epochs are never stored in
  milliseconds.
- Local time is derived from it by `_lab_clock` with the EU rule: BST from 01:00 UTC on the last Sunday of March to 01:00 UTC on
  the last Sunday of October. `london_offset_s`, `local_fields`, `utc_of_local(..., fold=)` and the `LONDON` tzinfo follow
  zoneinfo semantics: in the repeated hour `fold=0` is the first (BST) copy; in the gap `fold=0` uses the pre-transition offset, so
  2027-03-28 01:30 becomes 02:30 BST.
- The self-test cross-checks the rule against the two existing hand-coded oracles (`registry/tests/_fbd1_harness.py`,
  `tools/fbd1_soak/timeutil.py`) and against zoneinfo when it is importable (never required). Since V0.1 every suite reports
  in its LAB-SUMMARY line whether `zoneinfo.ZoneInfo('Europe/London')` was usable in its process (`zoneinfo`, from
  `_lab_clock.zoneinfo_available()`). Without it, each zoneinfo comparison prints
  `  info  SKIPPED (zoneinfo unavailable): <check>` and is never counted as or inside a PASS; no PASS text names zoneinfo
  (section 12 gives the counts).
- **Firmware tier:** `_fbd1_harness.WallClock` is installed as `id(ntp_time)`, so `now()` hour, minute and `is_dst` follow the
  epoch. Uptime and UTC move together. A booted world starts at uptime `boot_ms` (default 2000 ms), not at ds.Sim's 1 000 000 ms.
  The first NTP sync runs the firmware's real `time: on_time_sync` lambda at uptime `ntp_after_s`.
- **Coupled tier:** the HA World clock is the same UTC epoch. The interpreter's fixed UTC+1 `LOCAL`
  (`LOCAL = timezone(timedelta(hours=1))`, `home-assistant/tests/_ha_script_sim.py`) is replaced by `LONDON` inside
  `patched_ha_local(S)` and restored on exit, also on an exception. Before every firmware call the FirmwareWorld runs up to the
  World clock.
- **RTC tier:** the rig's own `WallClock` (exact NTP, no jitter) is the timeline; the world never steps it.

### 2.3 Reboot and power cut

- `world.reboot(down_s, nvs_fault=None, keep_prefs=True)` is a power cut followed by a new `StrictSim`. It carries over: the NVS
  records, the inverter bank, the preference values that had reached flash, and `restore_value` numbers. Switches return to their
  `restore_mode` defaults, so ALWAYS_OFF write enables come back OFF. RAM is fresh. The FULL `on_boot` runs in order, never a
  boot slice, except the FB durable boot read, which does not transpile, and two compile-time `static_assert` blocks (section 5,
  item 12). Hooks are re-bound to the new sim. The EventLog continues and the boot counter increments.
- `arm_power_cut(predicate | kind / key / addr / state, nth=1)` cuts at a matching firmware event (a commit, a write, a read). The
  event's effect has landed; the rest of the running action never happens; the world reboots from the captured state.
  `capture_points(fn)` returns a capture after every firmware event of `fn`, for sweeps.
- Preferences: only flushed values survive. A `restore_value` global is queued by its own 1000 ms poll and reaches flash at the
  next `global_preferences->sync()` (`flash_write_interval`, parsed from the firmware's `preferences:`), inside every
  `commit_record`, or at a graceful restart.
- In the coupled tier `reboot_dongle(at_utc, down_s, nvs_fault=None)` takes the same path. Dongle entities read `unavailable` until
  the API reconnects, attempt counters restart at 0, and polled sensors read `unknown` until the new boot's first sample.
  `restart_ha(at_utc, down_s, rollback_to_utc=None, ...)` stops and starts the HA instance; with `rollback_to_utc` every package
  helper is rolled back to its value at that instant (crash model, section 5).
- The rtc tier refuses a reboot (`RtcLabUnsupported`): `FbbSim.reboot` would drop the rig's clocks and keep stale hooks.

### 2.4 Fault injection

| Fault | Interface | Semantics |
|---|---|---|
| NVS commit | `nvs_policy(tag_or_pred, state_pred=None, mode, times=1)` | `landed`, `not_landed` (nothing stored, False), `false_negative` (stored, False), `false_positive` (nothing stored, True); wraps `commit_record` per instance. Since V0.1 a `not_landed`, `false_negative` or `false_positive` fault that fires on a key never stored earlier in the run is refused (the used-key rule below) |
| NVS at boot | `reboot(nvs_fault=...)` | `('absent', tag)` deletes a stored record (false ABSENT; refused when nothing is stored), `('read_error', tag)`, `('read_error_all',)`, `('wrong_size', tag)`, `('erase_all',)` (NVS and every preference). Since V0.1 `read_error` and `wrong_size` on a key never stored earlier in the run are refused (the used-key rule below) |
| Modbus | `modbus_policy(...)` with a function or a table | outcomes from the allow-list only; the most specific table key decides (`write:256`, `read:244x12`, `write:*`, `*`) |
| Link | `set_link(up)` | reads `no_response`, writes `timeout_lost`; the telemetry and configuration polls fail through their real handlers |
| Bus | `set_bus_idle(idle)`; coupled `BusModel` | the firmware's own bus-busy deferrals run |
| Foreign write | `set_register(addr, value, actor=...)`, actor `owner` or `inverter` | an owner change moves the ORIGINAL; an inverter change marks the register foreign |
| RTC lock | `rtc_lock_windows([(utc_a, utc_b), ...])` | `correction_in_progress` is true inside each window (MODEL) |
| RAM | `inject_global(name, value)` | white-box lock-leak injection, logged as `fault.ram`; a lab fault, never firmware behaviour |
| HA service call (coupled) | the interpreter's `World.fail_services` hook (`home-assistant/tests/_ha_script_sim.py`), set inside a suite; `api_outage` under `offline_policy='raise'` | the next N calls of the named service (`fail_services["domain.service"] = N`) raise `S.ServiceError` before they reach the dongle; under `'raise'` every dongle call during an API outage raises; the hook is not a replay action (section 5.2, HL-9) |

Every fault injected through a world method above is a logged event, so a replay reproduces it and an invariant checker can
tell an explained delay from an unexplained one. The HA service-call hook is set on the interpreter directly, inside the HF-09
suite only: no replay action injects it (section 5.2, HL-9).

**The NVS fault-cell model.** Each NVS primitive models one physical outcome. The lab does not know how often a device
reaches it.

- `false_negative` models one ESP-IDF fault cell: the new copy is stored, it is read at the next boot, and the store stays
  healthy. The other cells after `ESP_ERR_NVS_REMOVE_FAILED` are not modelled: the old copy resurfacing at the next boot, or
  a page going INVALID and refusing further writes. The ESP-IDF 5.5.5 semantics after `REMOVE_FAILED` are REPORTED (read
  from documentation and source summaries), not verified offline. A finding that needs a false negative therefore holds on
  a device only if ESP-IDF behaves as this one cell does.
- A per-key `read_error` heals at the next plain boot. That is optimistic for a data-CRC cause: ESP-IDF's CRC path does not
  heal by itself.
- `read_error_all` keeps the data. In ESPHome that state exists only after a failed partition erase: `open()` erases the
  whole partition when `nvs_open` fails (ESPHome 2026.8.2 `preferences.cpp:131-148`), so every read failing with the data
  still present also needs that erase to fail.
- Every finding that rests on one of these primitives states "trigger: <primitive>; device reachability: UNKNOWN pending
  the ESP-IDF host NVS test" (RC-FALSE-ABSENT: "PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN pending the ESP-IDF host NVS
  test"). 14 of the 37 counted findings rest on an injected NVS primitive (section 4). That host test (section 10, V-10)
  is not part of the lab.

**The used-key rule (V0.1).** An injected NVS fault needs a key that was stored earlier in the run.

- What is refused: the commit modes `not_landed`, `false_negative` and `false_positive` (`_lab_fw.NVS_USED_KEY_MODES`), and
  the per-key boot faults `read_error` and `wrong_size` (`_lab_fw.NVS_USED_KEY_BOOT_FAULTS`), on a key never stored earlier
  in the run. `landed` is never refused. `('absent', tag)` keeps its stricter rule: a record must be present now.
- "Stored earlier in the run" (`FirmwareWorld.nvs_stored_earlier`): the world's NVS holds a record under the key now (a
  seeded boot image, a record kept across boots, or one carried in by a capture), or the world's event log holds a landed
  `fw.commit` of the key after the last `('erase_all',)` boot fault. A `false_negative` commit counts as landed, because its
  record is stored. `('erase_all',)` un-stores every key. A false ABSENT does not: it models a platform misreporting a
  record that was stored.
- When: the commit rule is judged when the fault fires (at the faulting commit), not when the policy is armed. A policy
  armed before the first store, which fires after it, is accepted. The boot rule is judged at the boot.
- The physical reason for `false_negative`: the only device route to a Phase-B marker false negative is the marker's own
  `ESP_ERR_NVS_REMOVE_FAILED`. The new copy is written and erasing the earlier version fails, so the key must have an
  earlier version. The other route, an unrelated pending key failing the same `sync()`, cannot reach a Phase-B marker
  commit: ESPHome's `sync()` empties its whole queue (`preferences.cpp:248`), and the data commit's `sync()` runs in the
  same lambda just before the marker commit (firmware `:9154` -> `:9159` Free Power, `:17182` -> `:17187` register 244,
  `:18541` -> `:18547` Dump).
- The physical reason for the boot faults: a per-key `read_error` needs a stored record to fail reading (with nothing
  stored, `_dump_sim.load_record_status` still reports READ_ERROR: HL-6), and a `wrong_size` blob on a never-stored key would
  be a record created from nothing (the HL-6 sibling, a MALFORMED lockout no device reaches).
- `not_landed` and `false_positive` follow the same rule by the V0.1 brief's choice, not by a verified physical
  impossibility: an honest failed write needs no earlier version. See the coverage cost below.
- A refusal is a `LabHarnessError`, never `LabUnsupported` (some suites record `LabUnsupported` as a non-failing
  UNSUPPORTED point), so the scenario fails loudly. The message names the key, the physical precondition and the source,
  and asks for a completed-lease prelude.
- Tested by `test_lab_selftest_firmware` [8b]: each refused mode on the never-stored Free Power marker, a key predicate on
  the never-stored Dump marker, a refusal after `('erase_all',)`, a false ABSENT that does not un-store a key, and the
  `read_error` / `wrong_size` boot faults; each refusal has an accepted twin on a used key. [8] runs every commit-mode
  capability check on a used key.
- Measured: an independent fault scan (its own stored-earlier tracker) found 0 injections on never-stored keys in the 97
  corpus documents of V0.1 before the W6-1 correction, in every suite in quick mode, in `test_lab_fw_durability`,
  `test_lab_fw_obligations`, `test_lab_ha_phantom`, `test_lab_fw_guards` and `test_lab_fw_runtime` in extended mode, and
  in PB-01 (quick and extended). Before the rule it found 23 injections in 22 corpus documents, and 29 / 371 in PB-01
  quick / extended. The scan was not re-run after the W6-1, W6-1b and W6-1c corrections: their 18 scenarios and their
  18 corpus documents (FW-09-b3-256 to FW-09-b3-261; FW-09-b4-ct, b4-cb, b4-co, b5-lo, b6-ok, b6-x257 and b6-x260;
  FW-09-b7-rbnr, b7-rber, b7-cmnr, b7-ab and b7-af) inject no NVS fault (at most a Modbus outcome policy and inverter
  writes).

**Completed-lease preludes.** Every corpus document and directed scenario that injects on a lease key first completes a
lease of that domain, as PB-01-a already did in V0:

- Free Power and Dump to Grid: a 1-minute lease (`fp_start` / `dump_start` with `minutes: 1`), ended by its own watchdog
  with a verified restore, which leaves the marker CLEAR ("RESTORED OK - original inverter settings verified"). The rest of
  the V0 timeline moves 200 s later.
- Register 244: the owner's Apply (Essentials), then Restore through the real buttons, with the replay action
  `r244_restore` added in V0.1 (`FirmwareWorld.r244_restore`: the master arm, then "Restore Original Reg244" with its Free
  Power / Dump ownership gate; Phase C VERIFIED_PENDING_CLEAR, then Phase D CLEAR). FW-03-c uses it before its Dump
  prelude.
- Coupled tier (HF-07): a 1-minute scheduled lease through FPS1 or DGS1 before the main schedule.
- The 22 corpus documents that had injected on a never-stored key were re-recorded with an allowed `trace_digest` change
  (the added prelude actions and the shifted action times); every other document was re-recorded for provenance only, with
  an unchanged digest.
- No counted finding changed. F-FW01-2 (FW-01-b) is unchanged apart from its end epochs, which move 200 s with the Free
  Power START (F-FW01-3's document FW-01-d pins the same Free Power end epoch, moved the same way). F-FW01-1, F-FW02-2 and
  F-FW03-2 reproduce as before. Other expectation changes follow from the prelude's own events, each derived from source: a
  violation's sequence number in FW-05-e; FW-06-a, HF-07-c and HF-07-e now expect exactly the prelude's writes instead of
  none (still nothing written by the failed START), which binds them to the timeline (phase-sensitive); PB-01-d's marker
  reads CLEAR, the prelude's Phase D record, instead of ABSENT, and its status history now also contains the prelude's
  "RESTORED OK - original inverter settings verified".

**PB-01 normaliser.** PB-01 never meets the refusal, because `test_lab_property.pb01_normalise` rewrites a draw before it
executes:

- a per-key `read_error`, `wrong_size` or `absent` boot fault on a key that holds no record now becomes a plain reboot;
- an `nvs_policy` draw of any refused mode on a key that holds no record now becomes `run_for(0)`;
- an `('erase_all',)` boot fault becomes a plain reboot while a kept policy is still armed (its next commit would be on a
  key with no earlier version).

Every run checks the result with an event-log fault scan (every fired commit fault and per-key boot fault hit a key that
held a record), which has its own hand-built negative control. The PB-01 statistics (quick 160 sequences, extended 2000;
the first row counts fired faults, the others count the violations matched to each known-risk signature of the scenario):

| PB-01 | V0 quick | V0.1 quick | V0 extended | V0.1 extended |
|---|---|---|---|---|
| fired faults on a never-stored key | 29 | 0 | 371 | 0 |
| N17 (restore over a corrupt holder, F-PB01-2) | 1 | 0 | 19 | 1 |
| phantom admission (F-PB01-1) | 3 | 0 | 24 | 11 |
| partition erase (F-PB01-3) | 8 | 8 | 44 | 42 |
| false ABSENT (F-PB01-3:single-key) | 3 | 4 | 29 | 36 |
| false-positive commit (F-PB01-4) | 0 | 0 | 12 | 0 |
| unclassified | 0 | 0 | 0 | 0 |

The V0 columns were measured on the V0 generator before the rule; the V0.1 quick column is the current quick run; the
V0.1 extended column is the catalogue's PB-01 result. The PB-01 findings stay pinned by the corpus (PB-01-a, -b, -c, -d,
-f), so fewer random hits fail no pin. In V0 most N17 hits came from never-stored `read_error` / `wrong_size` draws (HL-6
and its sibling); the one extended hit left in V0.1 is a `wrong_size` fault on a stored CLEAR Dump marker.

**The coverage cost of the rule.** Because `not_landed` and `false_positive` are refused on never-stored keys as well, the
lab no longer exercises:

- an honest Phase-B marker failure on a never-used domain (the FW-04 repair premise, the FW-06 guard and NC-FW06-1 now run
  on a used device);
- the never-used ABSENT forms of F-FW06-2, F-FW06-3 and F-PB01-4 (they reproduce only in the used-device form, with the
  previous lease's stale CLEAR marker);
- the fail-closed register-244 lockout on a missing data record at a fresh-device Apply;
- the `test_lab_ha_phantom` control of a true START commit failure with the marker ABSENT.

Restricting the refusal to `false_negative`, the one mode with a physical need for an earlier version, would restore these
forms. That choice is open (section 15); nothing else here depends on it.

**Open observation (not counted, not triaged).** On a used register-244 domain, an Apply whose data-record commit is a
false positive resolves at the next boot from the previous transaction's stale data record (the FW-06 outcome of that
flow moved from a visible "RECOVERY BLOCKED" to resolved). A scratch probe (the owner sets 244 := 1, an Apply with a
data-record false positive, a reboot) shows the later Restore writing 2, not 1: an N15-like stale-ORIGINAL restore. No
invariant fires because the lab takes the landed write of the owner-initiated register-244 Restore as the owner's new
ORIGINAL (`_lab_fw.OWNER_DOMAINS` includes `r244`): the stale 2 becomes the baseline, and the pre-Apply value 1 is never
compared. By the same rule a stale-ORIGINAL restore through the register-244 domain is invisible to
INV-NO-SILENT-OVERRIDE. Its device reachability is UNKNOWN. The catalogue records it as an uncounted note of
RC-COMMIT-FALSE-POSITIVE (section 8).

### 2.5 Scheduler

`run_for(seconds, wd_order=('fp', 'dump'))` runs the firmware's own `interval:` entries at their declared periods and startup
delays. Each interval is found by a content marker; every marker must match exactly one interval and every interval one marker,
else the harness raises. Jobs due on the same millisecond run in firmware order, except the Free Power / Dump watchdog pair (same
period, same 15 s startup delay), whose order is the explicit `wd_order`. Executed: the 1 s export trip, the 5 s census, both
15 s watchdogs, the 10 s telemetry, 60 s configuration and 2 s owed-configuration polls (partly MODEL, section 5), the 10 s
evidence expiry, the 1 s supervision and the 1 s manual TOU jobs. Not executed: the 60 s clock read, the 1 s RTC tick, the 10 s FB
housekeeping and the 1 s supervision shadow (they do not transpile).

**The phase model (HL-10).** Every executed interval runs first at its declared `startup_delay`, else one full period, after
power-on (uptime 0), with zero offset plus the world's `phase_ms` sweep parameter. It is rescheduled at due + T (now + T
only for a slot that a raw advance already missed). The coupled tier samples its polled template sensors first one period
after power-on, then on the uptime grid; the RTC rig starts its intervals at a fixed phase. ESPHome 2026.8.2 runs an
interval first at setup plus a random offset, uniform in [0, min(T/2, 5 s)), and reschedules it at now + T. On the lab grid,
intervals with commensurate periods meet on the same millisecond: the two 15 s watchdogs tie (their order is `wd_order`)
and the 10 s telemetry poll meets them every 30 s. A check that pins an instant, a same-tick order or a bound on that grid
therefore holds at the lab's phase only.

**Phase-sensitivity tags.** Every such check is tagged. Each suite keeps a `PHASE_SENSITIVE_TAGS` registry (check-name
prefix -> reason), and its closing check `check_phase_registry()` fails on a prefix that matches no executed check (a stale
tag). LAB-SUMMARY `phase_sensitive` counts the executed tagged checks: 442 in a quick run and 503 in an extended run
(427 and 488 before the W6-1c correction, 406 and 467 before the W6-1b correction and 388 and 449 before the W6-1
correction: each of the five W6-1c, seven W6-1b and six W6-1 corpus documents adds one tagged trace-digest pin to
`test_lab_fw_guards` and two tagged replay checks to `test_lab_replay_corpus`, in both modes). The registries hold 200
prefixes in 13 suites, 4 of them extended-only. The catalogue flags 21 of 39 scenarios and 18 of 51
findings (11 of them counted) with `phase_sensitive: true` and a reason. The tags cover every check that failed under an
in-memory ESPHome-like phase patch (first run at setup plus the startup delay plus a seeded offset, reschedule at now + T;
17 quick configurations and 3 extended seeds, run outside the lab), every timing-bound check the audit named, and every
check the V0.1 review found phase-dependent without a FAIL line: the HF-03 whole-site cut grid of
`test_lab_ha_lifecycle` (check names starting `HA down `, whose point can take a held branch while its
`finding-reproduces:F-HF03-2 (...)` pin vanishes) and that suite's finding register (it holds only while every finding
prints). Under the patch:

- the exact pins of four counted reproductions fail: F-HF01-1 and F-HF04-2 in every configuration, F-HF04-1 in 14 of 17
  and F-HF08-3 in 6 of 17;
- F-FW03-2's pin is composite (both explicit `wd_order` outcomes in one run: the Dump-first context hold with its operator
  exits and the Free Power-first N17 contrast), so it fails by construction in 17 of 17, while its Dump-first context-hold
  signature reproduces whenever the Dump watchdog's random offset is the smaller (10 of the 17);
- F-HF03-2 reproduced at the 60 s and 120 s / 5 s whole-site cut points wherever its section ran, while the 5 s / 5 s
  point took the no-new-lease branch in 4 of the 5 configurations in which the section ran (its pin then absent, with no
  FAIL line);
- the corpus FINDING documents FW-05-e, FW-06-a, FW-07-i3 and HF-05-b fail an expectation (6, 11, 10 and 11 of the
  review's 11 patched quick configurations; on HF-05-b's fixed timeline the recorded deviation does not occur), while the
  suite pins of F-FW05-2, F-FW06-1, F-FW07-5 and F-HF05-2 hold; these four findings are flagged for that reason;
- in quick mode `test_lab_ha_schedules` (in all 11 configurations of the review) and `test_lab_ha_lifecycle` (in 12 of
  the 17) stop without a LAB-SUMMARY on a refused interleaving (`LabUnsupported`), and extended mode adds refusals in the
  extended sections of `test_lab_ha_lifecycle` and `test_lab_ha_phantom`. `test_lab_property` and
  `test_lab_selftest_firmware`, which also stopped at commit f11d85f (V0.1's third commit), now record the failure as a
  tagged FAIL and continue, and `test_lab_selftest_rtc` runs its replay-engine controls on a draft without its
  timeline-bound expectation (section 9); with patch seeds 1 to 3 these three suites end with a LAB-SUMMARY and every FAIL
  tagged.

The 18 FW-09 scenarios of the W6-1, W6-1b and W6-1c corrections (b3-256 to b3-261, b4-ct, b4-cb, b4-co, b5-lo, b6-ok,
b6-x257, b6-x260, b7-rbnr, b7-rber, b7-cmnr, b7-ab and b7-af) are tagged only through their corpus trace-digest pins.
In-suite, that their checks do not depend on the phase rests on the suite's extended sweeps, which re-run each b3
timeline (30 runs), each b4, b5 and b6 timeline (35 runs) and each b7 timeline (25 runs) at five watchdog phase offsets
(section 9). The phase patch was run on them once, outside the suites: the internal regression review of the W6-1c
candidate applied it with seeds 1 to 3 to `test_lab_fw_guards` and `test_lab_replay_corpus`, and every FAIL line was a
tagged check (30 in `test_lab_fw_guards` and 128 to 134 in `test_lab_replay_corpus`, per seed), so the b3 to b7 directed
checks, the `FW-09 claims` check and NC-FW09-20 to NC-FW09-23 held under it.

Section 5.2 (HL-10) gives the details. The tags disclose the phase dependence; they do not remove it. An ESPHome-faithful
phase distribution is not modelled.

### 2.6 Projection of synchronous firmware runs (coupled tier)

ds.Sim runs a script synchronously: `wait_until` and `delay` are no-ops (`elif kind in ("wait_until", "delay", "logger.log"):`
in `registry/tests/_dump_sim.py`), so a START takes 0 ms of simulator time. The coupled tier does not interleave such a run with
Home Assistant. It projects the run onto the HA clock:

- The run executes at its gate instant `t0` (the press time plus `press_s`, 0.117 s).
- A run is a **transaction** when it wrote a register, or did a Modbus op, an NVS commit or an explicit `delay:` while a
  transaction lock (a Free Power or Dump operation, a manual write, a register-244 apply) was held.
- Each stretch of the run ends at `t0` plus the durations summed so far. Since V0.1 a Modbus op lasts by its outcome:

  | Outcome of the op | Projected duration | Source |
  |---|---|---|
  | `no_response`, `no_response_landed`, `no_response_lost` | `no_response_s` = 2.0 s | the ESPHome 2026.8.2 Modbus hub's send-wait: `modbus/__init__.py:56` (`CONF_SEND_WAIT_TIME` default `2000ms`), `modbus.h:319`, `modbus.cpp:62-65`; the firmware's `modbus:` block sets no `send_wait_time` (its comment: "2000ms default, unmodified") |
  | `timeout`, `timeout_landed`, `timeout_lost` | `timeout_s` = 3.0 s | the firmware's bounded `wait_until` (`timeout: 3000ms`); ds.Sim fires no callback for a timeout, so the firmware waits the bound out |
  | every other outcome | `op_s` = 0.58 s | the recorded Dump START, 4.07 s for its 7 ops (`home-assistant/tests/_ha_dump_sim.py`) |

  An NVS commit adds `commit_s` (0.01 s, a model value). An explicit `delay:` executed while a lock is held adds its own length.
  With no fault outcome and no in-lock delay the window is exactly the V0 value `k*op_s + c*commit_s`.
- Explicit publishes keep their order. Template binary sensors (their real lambdas) are sampled at the end of each stretch. HA
  sees each state `publish_s` (0.12 s) later.
- `busy_until` is the end of the last op, commit or in-lock delay done under a lock (or of the last write). Lock-free reads after
  it (START's closing `poll_inverter_configuration_dispatch`) are projected but do not hold the window. A lock-free run (a
  telemetry or configuration poll) and a lock-free `delay:` keep **zero** projected duration. This is not modelled; it is
  counted in the register in section 2.7.
- Inside the busy window:
  - periodic firmware work is deferred to `busy_until`;
  - any dongle mutation (switch, number, press, power cut, `set_env`, `fw_action`) and any other firmware entry raises
    `LabUnsupported('interleaving inside a projected firmware transaction is not modelled')`. When the instant lies between
    the V0 end of the window and its corrected end, the message adds "in the projection gap" (ISS-HA-2: V0 applied such a
    mutation silently);
  - one exception: a press of a button whose `on_press` only executes scripts that are all in the window, all `mode: single`,
    and whose **own** work is still pending (their own last op, commit or in-lock delay at the top of the script stack) is
    **dropped**. It is logged as `dongle.dropped` `busy_same_script` and counted. ESPHome's single-mode script drops it too
    (`script.h:79-87`);
  - a press of a script that is in the window **only through a nested `script.execute`** (its own work has ended; ds.Sim keeps
    the caller on its stack, ESPHome does not) raises `LabUnsupported` (MISS-HA-1), because the device would run it. V0 dropped
    it silently.
- A sweep point that meets a refusal is reported as an UNSUPPORTED point, never as a PASS.

Measured at commit f11d85f, the V0.1 tree after the NVS correction (quick / extended, scenario suites plus the replay
corpus; section 2.7 says how): 792 / 2499 projected transactions; none with a `no_response` or `timeout` op and none with
an in-lock delay (0 / 0); 0 / 0 refusals in the projection gap; 0 / 0 nested-only refusals; 1 / 1 own-work drop (`test_lab_ha_lifecycle`,
where the device drops the press as well); 2 / 10 refused interleavings, all pre-existing UNSUPPORTED points outside the
gap. `test_lab_selftest_coupling` sections [15] to [18] exercise every rule with crafted probes.

### 2.7 Fail-loud rules and their scope

**What "fail loud" means here.** A construct the lab detects and does not model raises an exception (`LabHarnessError`,
`LabUnsupported`, `ds.Unsupported`, `S.Unsupported`, a replay or schema error). The scenario then becomes a FAIL, a BLOCKED
scenario or an UNSUPPORTED point. A suite that catches such an exception records it as one of those three, never as a PASS.

Fail loud does **not** mean that every difference between the lab and the device is detected. The lab runs on one thread,
with synchronous scripts and a fixed scheduler grid. The divergences it does not detect are listed in the register below,
with their measured occurrences. A PASS therefore means "this run met no detected unmodelled construct", not "the device
would behave the same" (HL-12).

**Firmware tier (`StrictSim`, `FirmwareWorld`).**

- Modbus outcomes outside the allow-list raise `LabHarnessError` (writes: `ok`, `ack_not_applied`, `error`, `not_sent`,
  `no_response_landed`, `no_response_lost`, `timeout_landed`, `timeout_lost`, `custom_response`; reads: `ok`, `error`,
  `not_sent`, `no_response`, `custom_response`, `timeout`).
- The entity registry is pre-created from every firmware entity id and sealed: an unknown id raises. Switch and binary sensor
  states are bool by construction, so an unset arm can never read as NaN-truthy. A read of a register the bank does not hold
  raises.
- A save of a restoring switch on a path the lab does not model, a button press of an unmodelled platform and a restart
  without a world raise `LabUnsupported`.
- Since V0.1, the **NVS used-key rule**: a `not_landed`, `false_negative` or `false_positive` commit fault, and a `read_error`
  or `wrong_size` boot fault, on a key never stored earlier in the run raises `LabHarnessError` naming the physical
  precondition (section 2.4). A false ABSENT of a missing record was already refused.
- `ds.Unsupported`, `S.Unsupported`, `KeyError`, `ValueError` and `AttributeError` raised while source runs are never caught.

**Coupled tier (`CoupledWorld`, `RealDongle`).**

- The projection refusals of section 2.6: since V0.1 the window lasts by op outcome, and a press of a script that is busy
  only through a nested `script.execute` is refused (MISS-HA-1).
- Since V0.1, a **static guard** at every package load (`check_packages`). Any construct of FPS1, DGS1, SMR1, or of the limit
  sensor of `ecco_runtime_config.yaml`, that the unmodified interpreter `home-assistant/tests/_ha_script_sim.py` would
  silently ignore raises `LabUnsupported`. Examples: `enabled:` on an action, condition or trigger; a state trigger with
  `for`, `from`, `not_from`, `not_to` or `attribute`, a `to:` list or no `to:`; a state condition with `for`, `attribute` or
  `match`, or an `entity_id` list; a template trigger with `for:`; automation `variables`. The full list is the FAIL-LOUD
  GUARDS paragraph of the `_lab_ha` docstring. The real packages use none of them. The self-test refuses `enabled: false` and
  25 other injected constructs.
- Since V0.1, two **runtime guards** while a world is open. Template truthiness: the interpreter's `_truthy` accepts `on`,
  `yes`, `1`, `enable` and non-zero numbers, while Home Assistant's condition rule accepts only `true` (REPORTED). An
  `input_number.set_value` outside the helper's declared range: Home Assistant refuses it (REPORTED), while the interpreter
  stores it. Both raise `LabUnsupported`. For template triggers the truthiness guard is conservative: Home Assistant's
  `result_as_boolean` would accept `on`, and the guard refuses it.
- An unmapped dongle id raises `S.Unsupported`. A `delay:` that is not a literal duration inside a transaction raises
  `LabUnsupported`.

**Replay engine and checkers.**

- The replay engine checks every action and observer name before it builds a world. An action due before the world clock
  raises. An observer that appends to the log raises. A type mismatch is a failed expectation, never a pass.
- Invariant parameters are routed to the checker that names them; an unknown or ambiguous parameter raises.
- A negative-control mutant that crashes is `MUTANT-INVALID`: a negative-control failure, not a kill.

**Suites and runners (the V0.1 output contract, section 3).**

- Every suite ends with `FAILED: <n> check(s): <names>` when a check failed, then one `LAB-SUMMARY` line whose counts are
  detected from the printed lines and the collections the suite passes to `_lab_trace.finish`, never literals. Before
  those lines `finish` runs the run-time import guard: an unclassified repository import is a FAIL of the suite (section
  2.8).
- `run_lab.judge` and `gen_catalogue` fail a suite on any FAIL line even at exit code 0, on a missing or garbled LAB-SUMMARY,
  and on counts that do not match the printed PASS, finding-pin, FAIL and UNSUPPORTED lines. Every catalogued UNSUPPORTED id
  must be printed in the mode it belongs to.
- Every suite has exactly one exit gate (`if FAILURES: ... sys.exit(1)`), checked statically by
  `registry/tests/test_offline_suite_exit_codes.py`. No suite imports another `test_*.py` file.

**The scope of "dropped, exactly like ESPHome".** `Sim.execute` in `registry/tests/_dump_sim.py` drops an execute of a script
that is in `running`, with the comment `return  # mode: single - dropped, exactly like ESPHome` (the HL-11 anchor). In ds.Sim,
`running` holds only the scripts on the synchronous call stack. In ESPHome 2026.8.2 a script is running while any of its
actions is in flight, including a `delay`, a `wait_until` or a Modbus request awaiting its response, and `script.execute`
does not wait for the callee (`script.h:79-87`, `:239`). The drop is therefore exactly ESPHome's only where both agree that
the script is running. Where they disagree, the firmware tier diverges silently (rows 1 to 4 of the register; harness
limitation HL-11). In the coupled tier the one form that would hide an owner or schedule press (MISS-HA-1) is refused. The
lab drops every re-entrant execute whatever the script's mode; the firmware has one non-single script
(`ecco_safety_census`, `mode: queued`, RAM only). No execute was dropped in any measured run (0 / 0).

**Register of silent divergences.** One row per known divergence between the lab and the device that a scenario can meet.
"Silent" means the lab neither refuses nor flags it in a check; "refused" means it raises `LabUnsupported`; "latent" means
the construct does not occur in the executed firmware today. Occurrences were measured at commit f11d85f, the V0.1 tree
after the NVS correction (B5), in quick and in extended mode, over the nine scenario suites plus the replay corpus; the
self-test probes are in brackets. The later V0.1 changes (the tiered drift rule, the re-classifications, the corrections
of the V0.1 review) changed no corpus trace digest and no executed scenario; the counts were not re-taken after them. The
W6-1, W6-1b and W6-1c corrections later added 18 firmware-tier scenarios (FW-09 b3, then b4, b5 and b6, then b7) and
their 18 corpus documents; they left every existing check verdict and every recorded trace digest unchanged, and the
counts were not re-taken after them either, so they do not include those runs. The
coupled-tier counts come from the lab's own `_lab_ha.DIVERGENCE_COUNTS`. The firmware-tier counts (rows 1 to 4, 8 to 10 and 14 to 18) come from a scratch observation
hook outside the repository; every suite's output was identical with and without it (runtimes masked). The lab does not
produce those counts itself. The hook instruments the firmware's simulator in the firmware and coupled tiers
(`StrictSim`); the RTC tier's rig, whose scripts are synchronous as well, is not instrumented.

| # | Item | Tier | Effect on the device versus the lab | V0.1 status | Quick / extended (self-tests) | Evidence |
|---|---|---|---|---|---|---|
| 1 | FWA-01, caller continues after a suspended callee (C1) | firmware, coupled | firmware work the caller runs after `script.execute` happens in the lab after the callee's whole remainder, on the device before it; all three patterns are Dump: the watchdog's `request_dump_end` -> restore then its next branch (800 / 3622), the watchdog's `dump_controller_tick` then a lambda (461 / 2824), Force Restore -> restore then the arm turn-off (11 / 69) | silent (HL-11) | 1272 / 6515 (23 / 23) | scratch hook; `script.h:239` |
| 2 | FWA-01, double end: a second execute in the same world step after the first run reached a suspension point | firmware, coupled | the lab runs the script again (a crafted double-end Dump watchdog tick re-runs the restore and replaces RESTORED OK with END IGNORED); the device drops it | silent (HL-11) | 0 / 0 (0 / 0; crafted probe: 1) | V0.1 reproduction probe; `script.h:79-87` |
| 3 | FWA-01, same-instant re-execute from a separate world action (0 ms spacing) | firmware, coupled | repeated START presses, telemetry polls at a slot instant and configuration polls run again in the lab; the device would drop the second while the first is in flight | silent (HL-11) | 183 / 1715 (0 / 1) | scratch hook |
| 4 | FWA-01, `script.is_running()` answered from the call stack | firmware, coupled | reads false for a script still waiting in its own delays on the device | silent (HL-11) | 0 / 0 evaluations (0 / 0) | scratch hook; its firmware uses sit in paths no scenario reaches or behind a false condition |
| 5 | MISS-HA-1, same-script press while the script is busy only through a nested execute | coupled | V0 dropped a press the device would run | refused since V0.1 | 0 / 0 (1 / 1); own-work drops, correct on the device too: 1 / 1 (2 / 2) | `test_lab_selftest_coupling` [16] |
| 6 | ISS-HA-2, projection gap after a `no_response` or `timeout` op | coupled | V0 projected every op as `op_s` and applied a mutation the device would refuse | refused since V0.1 (per-outcome window) | gap refusals 0 / 0 (2 / 2); transactions with such an op 0 / 0 (3 / 3) | `test_lab_selftest_coupling` [15] |
| 7 | An explicit `delay:` under a transaction lock | coupled | V0 gave it zero duration | modelled since V0.1 (extends the window) | 0 / 0 (1 / 1) | `test_lab_selftest_coupling` [15] |
| 8 | Lock-free delays and polls (zero duration) | firmware, coupled | a poll's reads spread over seconds on the device (`delay: 2500ms` between them) but happen at one instant in the lab; later commands can meet the device's poll in flight | silent, counted | lock-free delays inside coupled runs 77664 / 286912 (2992 / 20392); delays skipped in the firmware and coupled tiers 171176 / 826468 (10169 / 27813) | `DIVERGENCE_COUNTS` `delay_lock_free`; scratch hook |
| 9 | Modbus turnaround and queueing | firmware: 0 ms per op; coupled: `op_s` per op inside a transaction, no frame time, no queueing behind another run | two firmware runs' requests at one instant run back to back in the lab; on the device the second waits for the first's request and response | silent | ops of two different world steps at one firmware instant 1961 / 8914 (102 / 121), of 342703 / 1628134 ops | scratch hook |
| 10 | A `wait_until` whose condition is false in the lab | firmware, coupled | the lab proceeds at once; the device blocks up to its timeout; every occurrence follows a `timeout` or `custom_response` outcome, so the divergence is in duration only | silent | 87 / 186 (1 / 1) | scratch hook |
| 11 | ISS-HA-5, package options the interpreter ignores | coupled | `enabled: false`, state `for:` / `from:` and the rest would run, or be skipped, unlike Home Assistant | refused at load since V0.1 | 0 / 0 uses in 247 / 708 package-set checks | `test_lab_selftest_coupling` [17] |
| 12 | ISS-HA-5, template truthiness | coupled | `on`, `yes`, `1`, `enable` and non-zero numbers pass a template condition in the interpreter, not in Home Assistant (REPORTED) | refused at run time since V0.1 | 0 refusals of 283424 / 881859 values (4 of 16586 / 53354) | `test_lab_selftest_coupling` [18] |
| 13 | ISS-HA-5, `input_number` outside its range | coupled | the interpreter stores it; Home Assistant refuses it (REPORTED) | refused at run time since V0.1 | 0 of 2665 / 7503 writes; 0 to undeclared helpers (1 refused, 1 undeclared) | `test_lab_selftest_coupling` [18] |
| 14 | FWA-05, `continue` in a lambda | firmware, coupled | the transpiler has no `continue` (a translated `for` loop would skip its increment) | latent | 0 lambdas | static scan of the compiled lambdas |
| 15 | FWA-05, `sizeof` of anything but a char array of the lambda | firmware, coupled | evaluates to 0 | latent | 0 sites | static scan |
| 16 | FWA-05, statement-form `snprintf` | firmware, coupled | no truncation at the buffer size | silent | 0 outputs longer than their buffer, of 17197 / 62050 executions at 102 / 112 sites (0 of 1008 / 1200) | scratch hook |
| 17 | FWA-05, unsigned 32-bit wrap | firmware, coupled | Python integers do not wrap | silent | 0 out-of-range values in 676 / 2727 executions of the 5 sites (of 84) that do not reduce their result (0 of 161 / 161) | scratch hook |
| 18 | FWA-05, the signedness of a `u` / `UL` literal | firmware, coupled | the transpiler drops the suffix | not measured | 48 lambdas use one | static scan |
| 19 | Scheduler phase: zero offset, first run one period after power-on, due + T (ESPHome: a random offset in [0, min(T/2, 5 s)) after setup, now + T) | every tier | timing-bound checks, the exact pins of four counted reproductions and F-FW03-2's composite pin hold only at the lab's phase; four corpus FINDING documents are timeline-bound | silent, tagged (HL-10) | 442 / 503 executed phase-sensitive checks; 21 of 39 scenarios and 18 of 51 findings flagged | `PHASE_SENSITIVE_TAGS`; LAB-SUMMARY `phase_sensitive`; an in-memory ESPHome-like phase patch (17 quick configurations, 3 extended seeds) |

Oracle limits that can hide a violation even where the simulation matches the device are listed separately in section 5.2
(HL-4, HL-5 and HL-13).

### 2.8 Event log, replay DSL and drift rule

- `_lab_trace.EventLog` is append-only: `{seq, t_utc, up_ms, boot, src ('fw' | 'ha' | 'lab'), kind, data}`. `digest()` is the
  sha256 of canonical JSON (sorted keys, ASCII, floats rounded to 3 dp), so it is platform independent.
- A corpus document (`schema: ecco-assurance-lab-replay/v0`) holds: `id`, `title`, `tier`, `seed`, `utc_start`, `synthetic: true`,
  `ownership`, `source_anchors` (exact text, `line_at_record`), `source_digests` (sha256 of the LF-normalised files), `world`
  (world arguments), `actions` (`{at_s, do, args}`), `expect` (`{observe, args, op, value}`; ops `==`, `!=`, `startswith`,
  `contains`, `not_contains`, `<=`, `>=`), `classification`, `invariant`, `grade`, `confidence`, `failure_outcome`,
  `smallest_safe_repair_scope` and `trace_digest`. Optional: `notes`, and since V0.1 `scenario_priority` (the owning
  scenario's priority) and `finding_priority` (the highest root-cause priority among the counted owners of the catalogue
  findings that list the document, null when none does), both or neither. The V0 key `priority` (the scenario priority in
  73 of the 85 V0 documents; in the other 12 another value, in 6 of them the V0 priority of the finding's root-cause group)
  is now refused as unknown. All 115 documents carry both keys: 53 are listed by a finding (`finding_priority` P1 4,
  P2 18, P3 31) and 62 carry null (the six W6-1, the seven W6-1b and the five W6-1c documents among them).
- `replay(doc)` builds the tier's world, advances it to each action's `at_s`, logs a `replay.action` event, calls the action, takes
  the digest, then evaluates every expectation. A type mismatch is a failed expectation, never a pass.
- **Per-document drift rule (the replay engine).** If every `source_digests` entry matches the worktree, the replay must hold
  every expectation, give `digest == trace_digest` and find every anchor exactly once at its recorded line; a digest
  mismatch is a FAIL (non-determinism or harness drift). If a source digest differs, the replay prints
  `SOURCE DRIFT: <path>` and is judged on its expectations only. The catalogue-level tiered rule below decides whether
  that drift fails the lab.
- `record(draft, tier_pins=False)` fills `source_digests`, every `line_at_record` and `trace_digest` from two replays that must
  agree; `tier_pins=True` also pins the document tier's behavioural sources. `rerecord_corpus.py` re-records committed
  documents (section 11).
- `ddmin(items, still_fails)` is deterministic delta debugging. The property suite uses it to shrink a failing random sequence and
  print it as a replay document (stdout only). Its negative control NC-PB01-a runs that path end to end: the printed document
  passes the validate / dump / load round trip in memory, replays on the in-memory mutant with the re-execution's digest and
  the planted violation, and replays on the real firmware without it.

**Source tiers (B1).** The lab sorts every repository file it reads into one of three tiers:

- **Lab files:** every file under `registry/tests/assurance_lab/` (suites, helpers, tools, corpus documents). They are
  pinned exactly; a changed or unpinned lab file fails until the catalogue is regenerated. `test_lab_replay_corpus.py`,
  the checker of the pins, is pinned like every other lab file: it embeds nothing derived from its own digest, so this is
  not circular, and an edit of that gate is a catalogue change too. The one exemption is `SCENARIO_CATALOGUE.json`, which
  cannot record its own digest: `test_lab_replay_corpus` checks it against the tree ([0], [3]) and against a fresh static
  build ([5]), and `gen_catalogue.py --check` against a fresh full build (`_lab_trace.LAB_RULE`).
- **Behavioural:** a file outside the lab that lab code imports, executes, parses as data, or derives an expectation from
  (any content other than an exactly-once anchor text). Examples: the firmware YAML and `ecco_durable_snapshot.h`, the
  three packages and `ecco_runtime_config.yaml`, the HA and firmware simulators, `registry/rtc_policy.py`.
- **Non-behavioural:** a file outside the lab that lab code reads only through exactly-once anchor checks, its LF-normalised
  sha256 digest, or an existence check. Examples: `CHANGELOG.md`, `SAFETY.md`, the design and incident documents.

The table is `_lab_trace.BEHAVIOURAL`, `_lab_trace.NON_BEHAVIOURAL` and `_lab_trace.TIER_SOURCES` (with the prose
`TIER_RULE`, `LAB_RULE`, `DRIFT_RULE` and `TIER_METHOD`). `gen_catalogue.py` publishes it as the catalogue's
`baseline.tiers` (rule, lab, drift, method, behavioural, non_behavioural with the pinned flag, tier_sources) and validates
it: every pinned non-lab file is classified, no file is in both tiers, every tier set lies inside the behavioural tier,
every behavioural and anchor-read file is pinned, every existence-only file is unpinned, and every corpus document's tier is
known.

| Tier | Files | Pinned in `baseline.sources` | Members | A change gives |
|---|---|---|---|---|
| lab | 140 (25 `.py` files, 115 corpus documents) | all | the helpers, every suite (`test_lab_replay_corpus.py` included), the four tools, the generator's two helper modules, every corpus document | a FAIL: re-generate the catalogue (re-record first the documents that still record the old digest) |
| behavioural | 27 | all | the firmware YAML, `firmware/include/ecco_durable_snapshot.h`, FPS1, DGS1, SMR1, `ecco_runtime_config.yaml`, `_ha_script_sim.py`, `_ha_dump_sim.py`, `_dump_sim.py` and the other imported `registry/tests/_*.py` modules, `registry/rtc_policy.py` and the four other imported `registry/*.py` modules, `tools/fbd1_soak/__init__.py` and `timeutil.py` | a FAIL that names the file, the corpus documents that replay it and the re-record procedure |
| non-behavioural, anchor-read | 28 | all | `CHANGELOG.md`, `SAFETY.md`, the cited design, incident and fallback documents, `firmware/include/ecco_rtc_policy.h`, four frontend files, `ecco_system_health.yaml`, the dashboard, three HA test suites, two registry YAML files and four registry test files read for anchors | SOURCE DRIFT, not a failure; every anchor in it is still checked exactly once |
| non-behavioural, existence only | 20 | none | test files the coverage matrix cites (section 6) | nothing, as long as the file exists |

A pinned file that is missing fails, whatever its tier (the drift rule below). `baseline.sources` therefore pins 195
files: 140 lab files, 27 behavioural files and 28 anchor-read non-behavioural files (190 and 135 before the five W6-1c
corpus documents, 183 and 128 before the seven W6-1b corpus documents, 177 and 122 before the six W6-1 corpus
documents). The
lab reads 75 non-lab files at run time (27 behavioural, 48 non-behavioural). V0 pinned 144 files (106 lab, 38 non-lab) and
left 37 of those 75 unpinned: V0.1 pins 17 of them (16 behavioural, among them `registry/rtc_policy.py`, and the anchor-read
`registry/tests/test_fbd1_liveness.py`) and keeps the 20 existence-only citations unpinned. Files that the V0.1 brief named as
behavioural examples but which the trace shows read only by exactly-once anchors are non-behavioural:
`firmware/include/ecco_rtc_policy.h` (the rtc tier runs the Python mirror, never the header), the three frontend sources,
`ecco_system_health.yaml`, `registry/health_reason_codes.yaml` and `registry/system_health_checks.yaml`. The fallback design
record `S4_domains_decisions_final.md` became non-behavioural when `test_lab_selftest_core`'s row and heading checks were
rewritten as exactly-once anchors of the full table rows, blind-spot items and heading.

**How the table was derived.** Not by hand: an audit-hook trace, which the command-line tool
`registry/tests/assurance_lab/trace_inputs.py` repeats (standard library only; not a suite, so CI does not collect it).
It writes a `sitecustomize` module into a temporary directory outside the repository and puts it on `PYTHONPATH`
(inherited by the suites' own child processes); the module installs `sys.addaudithook` and logs every `open` of a file
under the repository root, with the four innermost in-repository caller frames and whether the import machinery is on
the stack. Every lab suite runs from the repository root as `python -B <file>` with `PYTHONDONTWRITEBYTECODE=1` (CI runs
`python <file>`; the two switches only keep the trace from writing bytecode) in quick mode, and with `--extended` in
extended mode too, and every corpus document is replayed alone in its own process with only its tier module imported (the
per-tier sets). A read with the import machinery on the stack, or one whose innermost in-repository frames are not one of
the named anchor, digest, overlay or existence helpers (`trace_inputs.HELPERS`), is behavioural. The tool then compares
the trace with the table and prints one `MISMATCH: ...` line per difference: a traced process that did not exit 0, a
write inside the repository, a non-lab file read but not in the table or in the wrong tier, a wrong pinned flag, a table
entry nothing read, or a document whose behavioural reads differ from its tier's `TIER_SOURCES`. It exits 1 on any
mismatch. On the V0.1 tree with the W6-1c correction it reports, for quick and extended mode alike: 75 non-lab files
read, 27 behavioural and 48 non-behavioural (20 of them existence-only), one behavioural read set per tier (coupled 25,
firmware 19, rtc 15) and `0 mismatch(es) against _lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL / TIER_SOURCES`. `TIER_METHOD`, published as the
catalogue's `baseline.tiers.method`, records the method and names the tool; the command is in section 11.

**The run-time import guard.** `_lab_trace.unclassified_imports()` lists every repository module in the process's
`sys.modules` outside the lab that the behavioural tier does not list, whoever imported it (a suite, a lab helper, a shared
simulator, the generator), at module level or lazily. `_lab_trace.finish()` runs it at the end of every suite: when it is
not empty, the suite prints `  FAIL  B1 import guard (end of suite): every repository module in this process's sys.modules
outside registry/tests/assurance_lab/ is listed in _lab_trace.BEHAVIOURAL - unclassified repository import(s) [...]: ...`,
the check joins the suite's FAILURES list (so the FAILED line, LAB-SUMMARY `fail` and the exit gate see it), and when it is
empty nothing is printed and no count changes. `test_lab_replay_corpus` [2] (`B1 import guard (mid-run): ...`) and
`test_lab_selftest_core` [11b] also check it mid-run, and the harness control NC-RC-48 plants an unclassified module to
show the end-of-suite FAIL. The guard does not see a data read (a file opened, not imported) or an import made only by a
command-line tool outside the suites (`run_lab.py`, `gen_catalogue.py`, `rerecord_corpus.py`): those are found by
re-running `trace_inputs.py`.

**Per-document tier pins.** `TIER_SOURCES` lists the behavioural files a replay of each tier executes: firmware 19,
coupled 25 (the firmware set plus the four packages and the two HA simulators), rtc 15. Every corpus document pins its
tier's set in its own `source_digests` (82 firmware, 30 coupled and 3 rtc documents). `rerecord_corpus.py
--pin-tier-sources` writes them (`record(..., tier_pins=True)`); a re-record without the option keeps the pins a document
already has. `test_lab_replay_corpus` [2] (the checks named `B1 tier pins: ...`) and `gen_catalogue.py` (`corpus <id>:
does not pin <k> of its tier's TIER_SOURCES in its own source_digests (<paths>); re-record it: python -B
registry/tests/assurance_lab/rerecord_corpus.py <id> --pin-tier-sources`) fail a document that lacks them; the
catalogued control NC-RC-44 shows both on a copy of FW-06-a with one tier pin removed. Both judge each document against
its effective pins (`_lab_trace.effective_pins`: its own `source_digests` plus its tier's set) at the
catalogue's digests. In V0, eight coupled documents (HF-02-a..d, HF-05-a, b, HF-08-a, b) executed the firmware without
pinning it, and only some of the 30 coupled documents pinned DGS1 (13), SMR1 (17) or `ecco_runtime_config.yaml` (9),
which every coupled world loads.

**The tiered drift rule.** One function, `_lab_trace.drift_report`, serves `test_lab_replay_corpus` [5],
`gen_catalogue.py --check` and `run_lab.py`'s baseline check. For every `baseline.sources` file whose LF-normalised digest
differs from the tree, or which is missing:

| Changed file | Outcome | Message (`<title> - <detail>`) |
|---|---|---|
| lab file | FAIL | `re-generate the catalogue: lab file changed: <path>` - `sha256 <now> != recorded <old>; <k> corpus document(s) still record the old digest (<ids>): re-record procedure (doc section 11): python -B registry/tests/assurance_lab/rerecord_corpus.py <ids or --all> (it refuses a changed trace_digest unless --allow-digest-change <id> names it: explain each), then python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1`; when no document records the old digest the detail ends `regenerate the catalogue: python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1` |
| behavioural file | one FAIL per file | `behavioural source changed: <path>` - `sha256 <now> != recorded <old>; <n> corpus document(s) replay it (<ids>); re-record procedure (doc section 11): ...` as above; with no document: `...; 0 corpus document(s) replay it (none); no corpus document pins it: run the lab (python -B registry/tests/assurance_lab/run_lab.py), then regenerate the catalogue: ...` |
| non-behavioural file | not a failure | the line `SOURCE DRIFT (non-behavioural): <path>` |
| a pinned file in neither tier | FAIL | `unclassified pinned source changed: <path>` - `...; it is in neither tier of the B1 tier table (_lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL): classify it (judged behavioural until then); ...` |
| a missing pinned file, any tier | FAIL | a lab, behavioural or unclassified file fails under its tier's title with the detail `sha256 missing != recorded <old>; ...`; a non-behavioural file as `pinned source missing: <path>` - `sha256 missing != recorded <old>; a non-behavioural file pinned in the catalogue baseline; <n> corpus document(s) replay it (<ids>); restore the file, or remove it from the lab (tier table, anchors, corpus pins) and regenerate the catalogue: python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1`; the replay suite's [5] also prints its line `SOURCE DRIFT (non-behavioural): <path> (file missing)`, and the generator's build reports any missing pinned file as a problem (`pinned sources missing: [...]`) |

`<ids>` are grouped by family (`FW-01-a,b,c,d; FW-02-a,b`). The procedure names the ids when there are at most 12 and fewer
than all documents, else `--all`; for a subset re-recorded with `--all` it says why: `(... explain each; --all because <n>
of the <N> documents pin it: a re-record leaves the documents whose digests and anchors did not change byte-identical)`. A
one-line comment in the firmware YAML or in `registry/rtc_policy.py` therefore fails with one check naming all 115
documents; in FPS1 it names the 30 coupled documents.

- **Where the lines appear.** `test_lab_replay_corpus` [5] turns each failure into a check named
  `gen_catalogue drift rule (tiered): <title>` (in strict mode `gen_catalogue drift rule (STRICT): <title>`) with the
  detail, and prints each SOURCE DRIFT line; when nothing fails its check reads `gen_catalogue drift rule (tiered): no lab
  or behavioural pinned source changed and no pinned source missing in this tree (<k> non-behavioural SOURCE DRIFT
  line(s), not a failure)`, in strict mode `gen_catalogue drift rule (STRICT): no pinned source changed or missing in this
  tree (whole-baseline rule, ECCO_LAB_STRICT_BASELINE=1)`. `gen_catalogue.py --check` prints the SOURCE DRIFT lines and
  `TIERED DRIFT RULE: <n> failure(s) (one per changed file):` (in strict mode `STRICT DRIFT RULE: ...`) with one
  `  - <title> - <detail>` line each, or, when nothing fails, `catalogue up to date (static parts)` (`; <n> non-behavioural
  SOURCE DRIFT line(s)` appended when there are any; without `(static parts)` after a full run). `run_lab.py` prints
  `note: SOURCE DRIFT (non-behavioural): <path> (catalogue baseline; not a failure: ECCO_LAB_STRICT_BASELINE=1 makes it
  one)` for a changed (not a missing) non-behavioural file,
  names the drifted files on its report's Baseline line, and counts each failure as a cross-check problem, so even a run
  of one suite (`--suite`) fails a tree with a pinned file missing.
- **Anchors still count.** Every anchor in a non-behavioural file is still checked exactly once (the catalogue anchors and
  harness-limitation anchors in [3], the static build, the suites' own anchor checks, and per document in [2]). An edit
  that removes or repeats an anchor text fails, whatever the file's tier.
- **Two checks per document.** `test_lab_replay_corpus` [2] always prints two checks per corpus document (230 for 115
  documents). Without drift: `replay <id>: every expectation holds` and `replay <id>: digest == trace_digest and every
  anchor at its recorded line`. With drift: `replay <id>: SOURCE DRIFT (<paths>) - judged on its expectations only`, then
  either `replay <id>: non-behavioural SOURCE DRIFT only - digest == trace_digest and every anchor occurs exactly once (a
  non-behavioural file cannot change a trace)` or `replay <id>: every anchor still occurs exactly once (lab or behavioural
  SOURCE DRIFT: the trace digest is not compared; [5] names the changed file and the documents to re-record)`.
- **Strict mode.** With `ECCO_LAB_STRICT_BASELINE=1` in the environment every pinned difference fails: a changed
  non-behavioural file becomes `gen_catalogue drift rule (STRICT): non-behavioural source changed (STRICT,
  ECCO_LAB_STRICT_BASELINE=1): <path>` with the detail `...; the whole-baseline rule: <k> corpus document(s) pin it (<ids>);
  <procedure>`, and no SOURCE DRIFT line is printed. The switch is the environment value `1` exactly (any other value, or
  none, is the tiered rule) for the replay suite, `gen_catalogue.py --check` and `run_lab.py` alike; only the replay suite
  also takes a `--strict-baseline` option. `gen_catalogue.py --check` then prints `  info  drift rule: STRICT
  (ECCO_LAB_STRICT_BASELINE=1): every pinned source must be unchanged`. Strict mode is for checking a tree after
  re-recording and regenerating (section 11), not for everyday runs.
- **The end-to-end controls.** `test_lab_replay_corpus` [5] runs the real [5] path over an in-memory overlay of the tree
  (nothing is written): NC-RC-40 adds one comment line to `CHANGELOG.md` and survives as expected (exactly one SOURCE
  DRIFT line, no failure, its anchor still exactly once; in strict mode exactly one FAIL, named `gen_catalogue drift rule
  (STRICT): ...`); NC-RC-41 (the firmware YAML) and NC-RC-42 (`registry/rtc_policy.py`, pinned since V0.1) are killed by
  exactly one added check that names the file, its 115 documents (the expected list and count are computed from the corpus
  JSON and `TIER_SOURCES`, not by the functions under test) and the re-record target `--all`; NC-RC-43 (`run_lab.py`, a
  lab file no corpus document pins) is killed by exactly one added `re-generate the catalogue: lab file changed` check
  naming the file and the regeneration command; NC-RC-44 (a copy of FW-06-a without its tier pin of
  `firmware/include/ecco_durable_snapshot.h`) is named by the generator's build and by the [2] tier-pin short-list;
  NC-RC-45 (`SAFETY.md` taken out of the tier table for the control, then restored, plus one comment line) is killed by
  exactly one added `unclassified pinned source changed` check. The six are catalogued negative controls (section 9).
  The uncatalogued harness controls NC-RC-46 to NC-RC-48 cover the missing-file rule in every tier (also through the
  generator's `compare()` path of section [5]), the saved-runs record of section 11 and the end-of-suite import guard.

What this means in practice: an edit of `CHANGELOG.md`, `SAFETY.md` or another anchor-read document that keeps its anchors
passes, with a SOURCE DRIFT line. An edit of the firmware, a package, a simulator or an imported registry module fails,
even when it is only a comment, until the corpus documents that replay it are re-recorded and the catalogue is
regenerated. A changed lab file, the replay suite included, fails until the catalogue is regenerated. A deleted pinned file
fails, whatever its tier. An edit of a non-behavioural file that corpus documents pin as an anchor file (for example
`docs/dev/dump-to-grid-safety-fcp2.md`, pinned by 10 documents) passes every check, but the next `gen_catalogue.py
--write` refuses until those documents are re-recorded, because `--write` refuses any corpus pin that is not this tree's.

### 2.9 Invariant checkers

The catalogue lists 48 invariants with their checker functions: 24 firmware, 17 coupled and 7 rtc. The 48 entries are core
checkers, scenario-local predicates and whole checked sections, not 48 separate checker functions. The core checkers run over
any EventLog and return violation records `{inv, seq, detail, tags}`; each has a negative-control self-test (a hand-built
violating log is caught, a clean twin is not).

| Invariant | Meaning |
|---|---|
| `INV-WS` | inverter writes stay inside {22-24, 230, 232, 244, 250-261, 268-279} |
| `INV-ONE-LEASE` | Free Power and Dump to Grid are never both active |
| `INV-NO-2ND-RESTORER` | no domain writes 256-261 while the other holds a durable RESTORE_REQUIRED marker (tagged N17 when the holder is corrupt) |
| `INV-NO-RESUME` | no lease is active after a reboot without a new START |
| `INV-LOCKOUT-QUIET` | nothing writes a corrupt-locked domain's registers except the SG-02 literal 244 = 2 |
| `INV-NO-SILENT-OVERRIDE` | at steady points, owned registers that differ from ORIGINAL have a RAM-visible obligation (any domain's visible obligation explains every differing register: HL-13) |
| `INV-RESTORE-BOUND` | a due restore completes within a bound unless a lockout or an injected fault explains the delay (one excuse explains the whole due period: HL-4, HL-13) |
| `INV-BOOT-MIRROR` | after the FULL `on_boot` a stored RESTORE_REQUIRED / PENDING_CLEAR / MALFORMED marker is mirrored in RAM |
| `INV-HF-ONE-LEASE` | firmware truth never shows both leases on the merged log |
| `INV-HF-ARM-OFF` | no write enable left on while no schedule script runs (grace period) |
| `INV-HF-SMR1-QUIET` | SMR1 writes a staged number only while firmware truth shows no operation, lease or snapshot |
| `INV-HF-WINDOW` | the firmware override ends within the window end plus a bound (the overrun is recorded) |
| `INV-HF-OWNER-INTENT` | no new firmware session for a schedule run after the owner's End / cancel |
| `INV-HF-NO-FALSE-SUCCESS` | SMR1 never reports RESTORED while the owner's value is not on the number |

The other 34 are scenario-local (for example `INV-16` owed Stop SOC supervision, `INV-RTC-WD-SKIP`, `INV-TZ-FOLD`); the
catalogue gives each one's meaning and checker. No invariant checks SG-02 containment itself (HL-13). Some core checkers are
weaker or stricter than their one-line meaning above in specific situations; section 5.2 lists each such limitation with
the suites that work around it.

## 3. Running the lab

Run from the repository root. Python 3.12, standard library plus PyYAML and Jinja2 (the suites and `rerecord_corpus.py`; the
runner's run, `--list` and report need the standard library only). Always keep bytecode out of the tree.

**One suite at a time.** Each suite is a plain script that exits 0 or 1.

```sh
export PYTHONDONTWRITEBYTECODE=1
python -B registry/tests/assurance_lab/test_lab_fw_obligations.py               # quick mode (the default)
python -B registry/tests/assurance_lab/test_lab_fw_obligations.py --extended    # extended mode
ECCO_LAB_EXTENDED=1 python -B registry/tests/assurance_lab/test_lab_property.py  # extended mode, by environment
```

**The runner, `registry/tests/assurance_lab/run_lab.py`.** It is not named `test_*.py`, so CI and the exit-code meta-check do not
collect it. It runs each lab suite as its own subprocess (with `-B` and `PYTHONDONTWRITEBYTECODE=1`, from the repository root)
and accepts a suite only when all of these hold (`run_lab.judge`):

- it exits 0 within `--timeout`;
- it prints exactly one `LAB-SUMMARY {...}` line: strict JSON with exactly the V0.1 keys in order (below), naming the suite
  itself, non-negative integer counts, `zoneinfo` a bool, `unsupported_ids` <= `unsupported_points` (both 0 or both above 0),
  `fail` 0;
- the LAB-SUMMARY numbers agree with the printed lines: `pass` == `  PASS  ` lines minus the finding-pin lines
  (`  PASS  finding-reproduces:...`), `finding_pins` == those pin lines, `fail` == `  FAIL  ` lines, `unsupported_points` ==
  `  UNSUPPORTED  <id> ...` lines and `unsupported_ids` == the distinct ids on them;
- it prints no `  FAIL  ` line at all (any FAIL line fails the suite, even at exit code 0);
- the output ends with the LAB-SUMMARY line, preceded by exactly one `FAILED: <fail> check(s): <names>` line when a check
  failed and by no FAILED line otherwise;
- its `  info  mode: quick|EXTENDED` line, when printed, matches the requested mode.

Then it cross-checks `SCENARIO_CATALOGUE.json` (read as data, never executed) against the run: the pinned source digests by
the tiered drift rule (section 2.8); every lab `.py` file (`test_lab_replay_corpus.py` included) and every corpus document pinned;
the discovered suites equal the catalogued ones; each suite's LAB-SUMMARY `finding` value equals its counted catalogue
findings; every counted finding printed as reproduced (`  FINDING  <id>`) and every FINDING line naming a catalogue finding
of that suite (a re-classified or merged id prints none); every counted finding carrying its two-axis verdict fields
(section 4); every catalogued UNSUPPORTED id printed in the mode it belongs to (an entry whose description starts "extended
mode only" is printed in an extended run and never in a quick run), and no uncatalogued id printed. A cross-check problem is
a FAIL of the run. Then it prints a plain-text report.

```sh
python registry/tests/assurance_lab/run_lab.py                       # every lab suite, quick mode, one at a time
python registry/tests/assurance_lab/run_lab.py --parallel 4          # four suites at once
python registry/tests/assurance_lab/run_lab.py --extended            # ECCO_LAB_EXTENDED=1 for every suite
python registry/tests/assurance_lab/run_lab.py --suite test_lab_property --suite test_lab_fw_runtime
python registry/tests/assurance_lab/run_lab.py --list                # the suites and their catalogue scenario ids
python registry/tests/assurance_lab/run_lab.py --replay FW-01-a registry/tests/assurance_lab/corpus/HF-08-a.json
python registry/tests/assurance_lab/run_lab.py --parallel 4 --write-summary docs/dev/assurance-lab-v0/LAB_SUMMARY.txt
```

| Option | Effect |
|---|---|
| (none) | every `test_lab_*.py`, quick mode (`ECCO_LAB_EXTENDED` removed from the child environment), one at a time |
| `--parallel N` | N suites at once (default 1); the 90 s quick budget per suite is noted only in a quick `--parallel 1` run |
| `--extended` | sets `ECCO_LAB_EXTENDED=1` for every suite |
| `--suite NAME` | run only this suite (repeatable; `test_lab_` and `.py` may be left out) |
| `--timeout S` | seconds per suite (default 1800) |
| `--list` | print the suites with their catalogue scenario ids and corpus counts |
| `--replay FILE ...` | replay corpus documents (paths or corpus ids such as `FW-01-a`) and print drift, digest vs `trace_digest`, anchors and failed expectations; diagnostic only (below) |
| `--write-summary PATH` | also write the report to PATH (ASCII, LF), after a privacy guard; nothing is written without it |

`--list` and `--replay` are separate modes; `--write-summary`, `--suite` and `--extended` apply to a suite run only. Exit code: 0
everything ok; 1 a suite failed or timed out, a catalogue cross-check failed, a replay failed or the summary was refused; 2 a
usage error or no suite found. `docs/dev/assurance-lab-v0/LAB_SUMMARY.txt` is the generated report; it is refreshed only by
re-running the invocation it names. Besides the per-suite table it prints the catalogue's root causes with their tagged
notes, the two-axis verdict distribution of the counted findings (section 4), the UNSUPPORTED entries and the catalogue
counts. Its "Extended" line is the recorded extended measurement `run_lab.EXTENDED_RECORD`, not a measurement of the quick
run.

`--replay` is diagnostic. It applies only the per-document rule of the replay engine: a document whose own pinned digest
differs from the tree prints `SOURCE DRIFT` and is judged on its expectations only (`OK on its expectations only`), even
when the changed file is behavioural. It does not add the tier's `TIER_SOURCES` pins and does not apply the tiered drift
rule; the gates are `test_lab_replay_corpus` [2] and [5], `gen_catalogue.py --check` and the runner's baseline check below.

**Baseline check and SOURCE DRIFT in the runner.** The runner judges every source the catalogue pins (`baseline.sources`, 195
digests) by the tiered drift rule of section 2.8, with the same function as `test_lab_replay_corpus` (`_lab_trace.drift_report`;
`_lab_trace` and `_lab_clock` use the standard library only):

- a changed lab file, a changed behavioural file or a changed file in neither tier is a cross-check failure (exit 1) named as
  in section 2.8, a missing pinned file of any tier is one too (a non-behavioural one as `pinned source missing: <path>`),
  and so is a lab file the catalogue does not pin;
- a changed non-behavioural file is not a failure: the runner prints `note: SOURCE DRIFT (non-behavioural): <path>
  (catalogue baseline; not a failure: ECCO_LAB_STRICT_BASELINE=1 makes it one)`, and the report's Baseline line reads
  `<m> of <n> catalogue-pinned sources match this tree; SOURCE DRIFT (non-behavioural, not a failure): <paths> (tiered drift
  rule: a changed lab or behavioural file fails; ECCO_LAB_STRICT_BASELINE=1: every pinned file must match)`;
- with `ECCO_LAB_STRICT_BASELINE=1` in the environment (the value `1` exactly; the runner has no command-line switch for
  it) every pinned source must match. The runner passes its environment to each suite, so `test_lab_replay_corpus` then
  runs under its strict rule as well.

**Without the runner:**

```sh
for f in registry/tests/assurance_lab/test_lab_*.py; do python -B "$f" > /dev/null || echo "FAILED: $f"; done
```

```powershell
cls
$env:PYTHONDONTWRITEBYTECODE = "1"
Get-ChildItem registry/tests/assurance_lab/test_lab_*.py | ForEach-Object { python -B $_.FullName | Out-Null; if ($LASTEXITCODE -ne 0) { "FAILED: $($_.Name)" } }
```

**Output (the V0.1 suite output contract).** Every check prints one line, with exactly two leading spaces, the tag and two
spaces: `  PASS  <check name>` or `  FAIL  <check name>[ - detail]`. A reproduced finding prints `  FINDING  <id> <text>`
(section 4). Each UNSUPPORTED point prints `  UNSUPPORTED  <id> <text>` exactly once, where `<id>` is the catalogue's
UNSUPPORTED id and several points may share one id. Suites also print `  info  ...` lines. The output ends with these lines,
printed by `_lab_trace.finish`, and nothing after them:

0. only if the run-time import guard finds an unclassified repository module (section 2.8): one
   `  FAIL  B1 import guard (end of suite): ...` line, whose check joins the suite's failures (nothing is printed and no
   count changes otherwise);
1. only if a check failed: `FAILED: <n> check(s): <name1>; <name2>; ...` (names joined by `; `, the whole line cut at a name
   boundary to at most 4000 characters and ended ` ... (+<k> more)`), so a CI log tail always shows the failing names;
2. one machine-readable line, `LAB-SUMMARY {json}`, with the keys in this order;
3. then the suite's single exit gate (`if FAILURES: sys.exit(1)`).

| Key | Unit |
|---|---|
| `suite` | the suite name |
| `pass` | checks that held, **excluding finding pins** |
| `fail` | checks that failed (one `  FAIL  ` line each) |
| `finding` | counted findings the suite reproduced (a duplicate or a merged variant is not counted) |
| `finding_pins` | held `finding-reproduces:` checks (printed as PASS, counted only here) |
| `unsupported_ids` | distinct catalogue UNSUPPORTED ids among the suite's UNSUPPORTED lines |
| `unsupported_points` | UNSUPPORTED lines (one per point) |
| `blocked` | scenarios that could not run |
| `zoneinfo` | `true` when `zoneinfo.ZoneInfo('Europe/London')` was usable in the suite's process |
| `phase_sensitive` | executed checks (held or failed) whose name starts with a registered phase-sensitive prefix (section 2.5) |
| `runtime_s` | the suite's own runtime in seconds, rounded to 3 dp |

```
LAB-SUMMARY {"suite": "test_lab_fw_obligations", "pass": 74, "fail": 0, "finding": 5, "finding_pins": 8, "unsupported_ids": 0, "unsupported_points": 0, "blocked": 0, "zoneinfo": true, "phase_sensitive": 13, "runtime_s": 9.47}
```

Every count is detected from the printed items and the collections a suite passes to `finish()`, never written as a literal
(`finish` refuses an integer count). Output is deterministic: two runs print the same lines except `runtime_s` and the
`runtime` info lines (fixed published seeds, `random.Random(seed)` only, no wall clock in any decision); `zoneinfo` depends
on the host, not on the run.

**Replay one corpus document** with `run_lab.py --replay FW-01-a` (above), or through the API:

```sh
PYTHONDONTWRITEBYTECODE=1 python -B - <<'EOF'
import sys
sys.dont_write_bytecode = True
sys.path[:0] = ["registry/tests/assurance_lab", "registry/tests", "registry", "home-assistant/tests", "tools"]
import _lab_trace as T
import _lab_fw, _lab_ha, _lab_rtc   # importing a helper registers its replay tier
r = T.replay(T.load_doc("registry/tests/assurance_lab/corpus/FW-01-a.json"))
print("ok", r.ok, "drift", r.drift, "digest_mismatch", r.digest_mismatch, "failed", r.failed_expectations)
EOF
```

`test_lab_replay_corpus.py` replays all 115 documents in quick mode (it prints `skipped: none`); `--extended` replays each a second
time and requires identical digests and observations.

**How CI runs them.** `tools/offline_test_roots.txt` lists `registry/tests` as an offline test root. `tools/run_offline_tests.py
--root registry/tests --parallel 2` (one matrix job per root in `.github/workflows/validate.yml`, 7200 s per suite for this
root) walks the root recursively and runs every `test_*.py`, including `registry/tests/assurance_lab/test_lab_*.py`, as
`python <file>` from the repository root; each must exit 0. It adds neither `-B` nor `PYTHONDONTWRITEBYTECODE`, so each
suite's own `sys.dont_write_bytecode = True` is the only protection: `test_lab_selftest_core` [13] checks it statically for
every suite and tool, with negative controls, and a CI-style run (every suite as `python <file>`, no `-B`, the variable
unset) left a sha256 manifest of the tree unchanged. CI runs quick mode only and never runs `run_lab.py` or
`gen_catalogue.py`. The `_lab_*.py` helpers, the four tools and the generator's helper modules are not suites and are never
collected. For a failing suite CI prints the last 20,000 characters of its output, which end with the `FAILED:` line and
LAB-SUMMARY; a passing suite's output is not printed (section 12). `registry/tests/test_offline_suite_exit_codes.py` checks
every discovered suite's exit gate, `tools/validate_repo.py` checks encoding and parsing, and `tools/tests/test_public_privacy.py`
scans every tracked file. Under the tiered drift rule (section 2.8) a change to `CHANGELOG.md`, `SAFETY.md` or another
anchor-read document prints SOURCE DRIFT and passes; a change to the firmware, a package, a simulator or an imported registry
module fails `test_lab_replay_corpus` until the documents that replay it are re-recorded and the catalogue is regenerated; a
change to any lab file fails it until the catalogue is regenerated.

**Line endings.** The lab reads every text and digest with CRLF normalised to LF (`_lab_trace.source_digest` and
`read_source_text`, `run_lab.lf_digest`, `gen_catalogue`'s tree reader, the suites' corpus checks). V0's one raw-byte LF test
in a replay verdict (`test_lab_fw_obligations`) was removed in V0.1. LF hygiene stays with `test_lab_replay_corpus` (the
canonical-form checks and NC-RC-13) and `tools/validate_repo.py`. `.gitattributes` is unchanged. A CRLF copy of the V0.1
tree with the W6-1c correction (every text file converted, 687 of its 688 files, as a `core.autocrlf=true` checkout gives)
passes `run_lab.py --parallel 4` with the same totals as the LF tree.

**Catalogue workflow for a lab change.** `SCENARIO_CATALOGUE.json` is generated by
`registry/tests/assurance_lab/gen_catalogue.py` and is regenerated in the same change as any lab-file change (section 11):

```sh
export PYTHONDONTWRITEBYTECODE=1
python -B registry/tests/assurance_lab/gen_catalogue.py --check              # before committing a lab change: run, build, compare
python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1 # regenerate (sequential: --parallel 1 is the default)
```

`--check` runs the 14 lab suites in quick mode one at a time (about 5.5 min on the development PC), builds the catalogue and
compares it with the committed file; the quick runtimes are wall-clock values and are excluded from the comparison (printed
as notes). `--write` writes the catalogue only when the build has no problem. `runtime_quick_s` is taken only from
sequential outputs (`--parallel 1`, or saved runs whose record says so), and only there is a quick runtime over 90 s a
problem; with `--parallel N` above 1 a runtime over 90 s is a WARNING, the committed runtimes are kept, and a suite without
one is a problem. In CI, `test_lab_replay_corpus` checks only the static parts (the suite tables, the corpus,
`_catalogue_data.py`, the tier table and the tiered drift rule), because running the other thirteen suites inside it would
exceed its 90 s budget; it says so in its output. The run-derived parts (negative-control outcomes, FINDING / DUPLICATE /
merge lines, counted findings against LAB-SUMMARY, quick runtimes) are checked only by `gen_catalogue.py --check`, and the
counts and FINDING lines also by `run_lab.py`. A lab change therefore runs `gen_catalogue.py --check` before it is committed;
a green CI run alone does not check those parts.

**Suites and runtimes.** The quick counts are those of the `--parallel 4` run reported in
`docs/dev/assurance-lab-v0/LAB_SUMMARY.txt`. The quick runtimes are the catalogue's `runtime_quick_s`, measured by
`gen_catalogue.py --write` with the suites run one at a time on the development PC (CI runners differ).

| Suite | Scope | Pass | Pins | Finding | UNSUPPORTED ids | UNSUPPORTED points | Phase | Quick s |
|---|---|---|---|---|---|---|---|---|
| `test_lab_selftest_core` | clock, trace, replay engine, ddmin, known-risk anchors, tier table, output contract, bytecode guard | 259 | 0 | 0 | 0 | 0 | 0 | 11.6 |
| `test_lab_selftest_firmware` | FirmwareWorld: allow-list, registry, reboot, faults, NVS used-key rule, scheduler, checkers, HL-1 rule | 262 | 0 | 0 | 0 | 0 | 16 | 8.6 |
| `test_lab_selftest_rtc` | RtcWorld: DST nights, lock windows, refusals | 148 | 0 | 0 | 0 | 0 | 3 | 3.9 |
| `test_lab_selftest_coupling` | CoupledWorld: mapping, projection, lifecycle, checkers, fail-loud probes and guards | 106 | 0 | 0 | 0 | 0 | 6 | 9.6 |
| `test_lab_fw_obligations` | FW-01, FW-02, FW-03 | 74 | 8 | 5 | 0 | 0 | 13 | 9.5 |
| `test_lab_fw_durability` | FW-04, FW-05, FW-06 | 97 | 15 | 8 | 0 | 0 | 15 | 22.4 |
| `test_lab_fw_runtime` | FW-07-A..I, FW-08-A..F | 125 | 9 | 6 | 3 | 3 | 39 | 20.8 |
| `test_lab_fw_guards` | FW-09 (with the per-slot b3, the W6-1b b4, b5 and b6 and the W6-1c b7 scenarios), FW-10, FW-11 | 268 | 0 | 0 | 0 | 0 | 30 | 14.7 |
| `test_lab_ha_lifecycle` | HF-02, HF-03, HF-05, HF-09 | 172 | 24 | 7 | 3 | 5 | 26 | 40.7 |
| `test_lab_ha_phantom` | HF-07 | 67 | 6 | 1 | 1 | 1 | 6 | 27.9 |
| `test_lab_ha_schedules` | HF-01, HF-04, HF-06 | 60 | 13 | 7 | 0 | 0 | 13 | 37.6 |
| `test_lab_dst_rtc` | HF-08, RT-01, RT-02, RT-03 | 143 | 8 | 3 | 0 | 0 | 27 | 21.0 |
| `test_lab_property` | PB-01, PB-02, PB-03 | 65 | 6 | 0 | 0 | 0 | 18 | 57.1 |
| `test_lab_replay_corpus` | corpus schema and replay, catalogue cross-checks, tiered drift rule, harness controls | 314 | 0 | 0 | 0 | 0 | 230 | 45.9 |
| total | 14 suites | 2160 | 89 | 37 | 7 | 9 | 442 | 331.3 |

The `finding` column is the suite's number of counted findings; its total, 37, equals the catalogue's counted
findings. The UNSUPPORTED ids total is the sum of each suite's distinct ids. Pass plus pins, 2249, is the number of
checks that held. Every quick runtime of the sequential run is within the 90 s budget per suite; the slowest is
`test_lab_property` at 57.1 s. The suites' unrounded sequential runtimes add up to 331.3 s (the column's rounded
values to 331.3 s), within the V0.1 limit of about 350 s (the V0 reference of 291 s plus 20 %). The sequential run is
the `gen_catalogue.py --write --parallel 1` run of the V0.1 tree re-based on public main `a7235433` (the same lab code
apart from its `PUBLIC_MAIN` base constant measured 311.6 s when the W6-1c correction was regenerated, so the
difference is run-to-run variation of the development PC; counts are unchanged), with the W6-1c correction (before it:
2103 pass, 2192
held, 427 phase-sensitive, 308.5 s; before the W6-1b correction: 2028 pass, 2117 held, 406 phase-sensitive, 314.2 s;
before the W6-1 correction: 1964 pass, 2053 held, 388 phase-sensitive, 307.9 s); it was made with no other test
workload on the PC (checked every 15 s while it ran). The W6-1 correction moved two rows: `test_lab_fw_guards` from
108 to 160 pass (30 b3 checks, 8 control checks, 6 corpus replays and 8 discrimination checks) and from 12 to 18
phase-sensitive checks, and `test_lab_replay_corpus` from 278 to 290 pass and from 194 to 206 phase-sensitive checks
(two replay checks per new document). The W6-1b correction moved the same two rows: `test_lab_fw_guards` from 160 to
221 pass (34 b4, b5 and b6 checks, 6 control checks, 7 corpus replays and 14 discrimination checks) and from 18 to 25
phase-sensitive checks, and `test_lab_replay_corpus` from 290 to 304 pass and from 206 to 220 phase-sensitive checks
(two replay checks per new document). The W6-1c correction moved the same two rows: `test_lab_fw_guards` from 221 to
268 pass (30 b7 checks, one containment-claim check over every FW-09 timeline, 4 control checks, 5 corpus replays and
7 discrimination checks) and from 25 to 30 phase-sensitive checks, and `test_lab_replay_corpus` from 304 to 314 pass
and from 220 to 230 phase-sensitive checks (two replay checks per new document).

**Extended mode.** One `run_lab.py --extended --parallel 4` run of the V0.1 tree with the W6-1c correction on the
development PC, with no other test workload on it (checked every 15 s while it ran; four suites share the CPU, so the
times are contended; see below):

| Suite | Pass | Pins | Finding | UNSUPPORTED ids | UNSUPPORTED points | Phase | Extended s |
|---|---|---|---|---|---|---|---|
| `test_lab_selftest_core` | 272 | 0 | 0 | 0 | 0 | 0 | 46.1 |
| `test_lab_selftest_firmware` | 262 | 0 | 0 | 0 | 0 | 16 | 9.4 |
| `test_lab_selftest_rtc` | 149 | 0 | 0 | 0 | 0 | 3 | 6.6 |
| `test_lab_selftest_coupling` | 108 | 0 | 0 | 0 | 0 | 6 | 32.5 |
| `test_lab_fw_obligations` | 83 | 8 | 5 | 0 | 0 | 14 | 31.6 |
| `test_lab_fw_durability` | 112 | 15 | 8 | 0 | 0 | 15 | 83.6 |
| `test_lab_fw_runtime` | 130 | 9 | 6 | 3 | 3 | 41 | 35.9 |
| `test_lab_fw_guards` | 272 | 0 | 0 | 0 | 0 | 30 | 22.3 |
| `test_lab_ha_lifecycle` | 212 | 55 | 7 | 3 | 7 | 84 | 67.6 |
| `test_lab_ha_phantom` | 74 | 6 | 1 | 1 | 1 | 6 | 78.5 |
| `test_lab_ha_schedules` | 61 | 13 | 7 | 1 | 8 | 13 | 145.5 |
| `test_lab_dst_rtc` | 147 | 8 | 3 | 0 | 0 | 27 | 41.4 |
| `test_lab_property` | 65 | 6 | 0 | 0 | 0 | 18 | 449.4 |
| `test_lab_replay_corpus` | 315 | 0 | 0 | 0 | 0 | 230 | 71.6 |
| total | 2262 | 120 | 37 | 8 | 19 | 503 | 1122.0 |

The run took 533.6 s wall clock (about 9 min). The suites' own extended runtimes add up to 1122.0 s (about 18.5 min),
but four suites shared the CPU, so that sum is not a sequential measurement and none was made. `test_lab_property`
dominates (449.4 s on its own). `run_lab.EXTENDED_RECORD` records this run (534 s wall, 1122 s runtime sum; before the
W6-1c correction 555 s and 1162 s, with 2204 pass and 488 phase-sensitive checks; before the W6-1b correction 553 s and
1150 s, with 2128 pass and 467 phase-sensitive checks; before the W6-1 correction 570 s and 1175 s, with 2063 pass and
449 phase-sensitive checks); every quick report prints it as the recorded extended measurement. The W6-1 correction
moved two rows: `test_lab_fw_guards` from 109 to 162 pass (the quick-mode additions and one extended check, `EXT FW-09
b3`, which re-runs the six b3 timelines at five watchdog phase offsets, 30 runs) and from 12 to 18 phase-sensitive
checks, and `test_lab_replay_corpus` from 279 to 291 pass and from 194 to 206 phase-sensitive checks. The W6-1b
correction moved the same two rows: `test_lab_fw_guards` from 162 to 224 pass (the quick-mode additions and one extended
check, `EXT FW-09 b4 / b5 / b6`, which re-runs the seven new timelines at five watchdog phase offsets, 35 runs) and from
18 to 25 phase-sensitive checks, and `test_lab_replay_corpus` from 291 to 305 pass and from 206 to 220 phase-sensitive
checks. The W6-1c correction moved the same two rows: `test_lab_fw_guards` from 224 to 272 pass (the quick-mode
additions and one extended check, `EXT FW-09 b7`, which re-runs the five new timelines at five watchdog phase offsets,
25 runs) and from 25 to 30 phase-sensitive checks, and `test_lab_replay_corpus` from 305 to 315 pass and from 220 to 230
phase-sensitive checks. In extended mode `test_lab_ha_schedules` meets 8 UNSUPPORTED points of one id (HF-04-UNS-EXT)
where quick mode meets none, and `test_lab_ha_lifecycle` 7 points of its 3 ids where quick mode meets 5: the extended
run meets 8 ids at 19 points, the quick run 7 ids at 9 points (section 10).

## 4. Evidence vocabulary

**Classification** (exactly these strings, `_lab_trace.CLASSIFICATIONS`):

| Value | Meaning |
|---|---|
| `PASS` | the expected invariant holds on the real source under the stated models |
| `FAIL` | an expected invariant is violated with no registered explanation, or a harness exception occurred: the suite exits 1 |
| `FINDING-NEW` | a reproduced deviation from the intended behaviour that no public document records |
| `FINDING-KNOWN:<id>` | a reproduced deviation that a public document already records; `<id>` is a key of `_lab_trace.KNOWN_RISKS` |
| `UNSUPPORTED` | the lab cannot represent the case (for example an interleaving inside a projected transaction); never counted as PASS. Each occurrence is one printed line `  UNSUPPORTED  <id> <text>`, one UNSUPPORTED **point**; `<id>` is the catalogue's UNSUPPORTED id, and several points can share one id |
| `BLOCKED` | a scenario cannot run because a source construct is not supported by the engines; none in V0.1 |

`KNOWN_RISKS` registers 19 ids, each anchored by a text snippet that must occur exactly once in a public file (the core self-test
re-counts them). The 11 used by V0.1 classifications are `FCP2-F6`, `FCP2-R1`, `N15`, `N16`, `N17`, `NVS-PARTITION-ERASE`,
`PLATFORM-ABSENT`, `PR41-GHOST`, `SG-25`, `SMR1-OWNER-RESTORING` and `SMR1-UNCLEAN-SHUTDOWN`. (`SMR1-OWNER-STAGING` stays
registered; since F-HF05-1 was re-classified, no classification uses it.) Their anchors are in
`docs/dev/dump-to-grid-safety-fcp2.md`, `docs/dev/schedule-manual-restore.md`,
`docs/architecture/fallback/design/S4_domains_decisions_final.md` and the firmware's own status texts.

**Evidence grade** (the grade of the lab's own execution; it is not device reachability, see the two-axis verdicts below):

| Grade | Meaning |
|---|---|
| `VERIFIED` | executed in this harness against the real source |
| `REPORTED` | stated by an external source the lab cannot execute (for example ESP-IDF API documentation) |
| `INFERRED` | reasoned from source or from a proxy run, not executed as such |
| `UNKNOWN` | no evidence either way (typically the real-world rate of a trigger) |

Confidence is `high`, `medium` or `low`; priority is `P1` (high), `P2` or `P3` (low).

**Units.** Each count has one unit; numbers with different units are never added. The LAB-SUMMARY keys are listed in
section 3. The catalogue counts these:

| Catalogue count | Unit |
|---|---|
| findings (51) | finding ledger entries: counted (37), printed duplicates (12) and merged variants (2) |
| root-cause groups (31) | one group per root mechanism; the meaningful defect count |
| negative controls (115) | control rows: one in-suite control check each, or one audit mutant; they apply 95 distinct mutations, because a mutation applied in several rows counts once (`same_mutation_as`, section 9) |
| UNSUPPORTED (8) | catalogue entries; a run reports the ids and the points it met: quick 7 ids at 9 points, extended 8 ids at 19 points |
| invariants (48) | catalogue entries, each with its checker; core checkers, scenario-local predicates and whole checked sections |

**Two-axis verdicts.** Every counted finding carries two separate verdicts, a product-change flag and its trigger. The lab can
show a mechanism in simulation; it cannot show that the trigger occurs on the device. The values are
`_catalogue_data.MECHANISM_VERDICTS`, `DEVICE_REACHABILITY` and `PRODUCT_CHANGE`; `gen_catalogue.py` refuses any other value
and `run_lab.py` checks that every counted finding carries all of them. A duplicate or merged entry has them null: it is
graded through its owner.

| Field | Value | Meaning |
|---|---|---|
| `mechanism_verdict` | `CONFIRMED-IN-SIMULATION` | given the trigger, the deviation was reproduced by executing the real production source (firmware lambdas, HA package YAML) in the lab, with a finding pin and a corpus document; it says nothing about whether the trigger occurs on the device |
| | `PLAUSIBLE-UNDER-ASSUMPTIONS` | the deviation follows in the lab only through a stated proxy or an unverifiable platform assumption that is itself part of the mechanism (a PROXY reproduction graded INFERRED, or an HA-core semantic such as the `input_datetime` fold=0 resolution) |
| | `NOT-CONFIRMED` | reserved: a finding with this verdict is re-classified, never counted |
| `device_reachability` | `VERIFIED` | the trigger was observed on the real device stack (ESP32, ESPHome 2026.8.2, ESP-IDF 5.5.5, real Home Assistant, real inverter) or reproduced by executing that platform code |
| | `PLAUSIBLE-UNDER-ASSUMPTIONS` | the trigger is an ordinary event (a reboot, a power cut, a link outage, a failed Modbus read, an owner action, a DST night, chained schedules) or a platform behaviour reported by sources, and reaches the device if the stated assumptions hold; its rate is stated separately |
| | `UNKNOWN` | the trigger rests on an injected lab primitive whose device route is unestablished or contested (every NVS primitive: "UNKNOWN pending the ESP-IDF host NVS test"), or on a fault with no known code path |
| | `UNVERIFIABLE-OFFLINE` | the trigger depends on a component the lab cannot execute or read offline (Home Assistant's restore-state cadence and crash rollback, an inverter refusing a register write) |
| | `NOT-APPLICABLE` | the finding makes no device claim (a test-model or documentation item) |
| `needs_product_change` | `yes` / `no` | yes: the smallest adequate repair changes firmware or package behaviour. no: none is needed (a documented residual or limit), or the repair is documentation, field text or the test model only. A reason is recorded either way |
| `injected_primitive` | text | the trigger the lab injects: a text starting `nvs ` or `boot ` is an injected NVS primitive, one starting `none` needs no injected fault, any other names another injected fault (Modbus, link, power cut, RAM, HA restart, HA service call) |

A finding whose trigger is an injected NVS primitive states it at the start of its reachability text: "trigger:
<primitive>; device reachability: UNKNOWN pending the ESP-IDF host NVS test" (RC-FALSE-ABSENT: "PLAUSIBLE-UNDER-ASSUMPTIONS,
rate UNKNOWN pending the ESP-IDF host NVS test"); `gen_catalogue.py` enforces the prefix.

**Rules at the edges of the vocabulary.** Three classification rules decide cases the definitions above leave open; each
moves a printed count, so they are stated here:

1. The UNKNOWN rule applies to every injected NVS primitive, an honest commit failure included. F-FW06-1's corpus trigger is
   a `not_landed` data-record commit (a full partition or a flash write error would do it), a route nobody contests, and
   its device reachability is still UNKNOWN by this rule. Graded PLAUSIBLE-UNDER-ASSUMPTIONS instead, the distribution
   below would read PLAUSIBLE-UNDER-ASSUMPTIONS 21 / UNKNOWN 11.
2. A synthetic telemetry condition that a scenario builds is not an injected primitive. F-FW07-5's grid CT that already
   repeats at the START is `none (synthetic telemetry: ...)`; counted as injected, 29 of 37 would rest on an injected
   fault primitive.
3. A conditional repair counts as `yes`. F-FW06-2 and F-FW06-3 need a product change "only if the trigger is confirmed";
   counted as `no`, 8 of 37 would need no product change.

**The distribution** (37 counted findings; `run_lab.py` prints the same distribution in `LAB_SUMMARY.txt`, and
`gen_catalogue.py` as `  info  two-axis verdicts:`): mechanism CONFIRMED-IN-SIMULATION 34 / PLAUSIBLE-UNDER-ASSUMPTIONS 3;
device reachability VERIFIED 0 / PLAUSIBLE-UNDER-ASSUMPTIONS 20 / UNKNOWN 12 / UNVERIFIABLE-OFFLINE 4 / NOT-APPLICABLE 1;
6 of 37 need no product change (F-FW05-2, F-FW07-3, F-HF01-1, F-HF02-2, F-HF05-2, F-HF06-1); 14 of 37 rest on an injected
NVS primitive and 28 of 37 on any injected fault primitive (the other 9 need no injected fault). No counted finding has
VERIFIED device reachability. The audit's figure "18 of 39 counted findings rest on an injected primitive" does not
reproduce under any per-finding rule the catalogue can apply (for the 39 findings V0 counted: 15 NVS, 29 any; section
15).

**Why findings are pinned by `finding-reproduces` checks.** A finding is not a pass. Each reproduced finding prints at least
one `  FINDING  <id> ...` line (sweeps and multi-variant scenarios print one per reproducing point or variant; some suites
add a `[classification; counted | DUPLICATE of ...]` block after the id, others print the classification in the text), and
at least one check named `finding-reproduces:<id>` (some with a variant suffix, such as
`finding-reproduces:F-FW04-1:read-error-then-absent`) asserts that the deviation reproduces exactly (the same texts,
writes and end state). Such a check is printed as `  PASS  finding-reproduces:...`, but it is **not counted in `pass`**:
LAB-SUMMARY counts it under `finding_pins` (89 in a quick run, 120 in an extended run). `pass` plus `finding_pins` is the
number of checks that held (2249 in a quick run). A later change that alters the pinned behaviour, a fix included, makes
that check fail and the suite exit 1; section 13 gives the procedure for such a change.

**Counting.** Each finding is counted once across the lab. A finding that reproduces a deviation another finding already
owns is a duplicate and is not counted: it prints `DUPLICATE of <owner>, not counted`, and its `finding-reproduces` check
still runs. A merged variant prints no FINDING line of its own; its owner's `finding-reproduces` checks pin it and its
suite prints a merge record (`<id> -> merged into <owner>`). Two are merged: F-RT03-1 into F-HF08-3 (its RT-03 variant) and,
since V0.1, F-HF07-2 into F-HF07-1 (one HA-side diagnostics gap in two mirror instances, FPS1 and DGS1). The LAB-SUMMARY
`finding` value is the number of counted findings in that suite. The catalogue has 51 findings: 37 counted and 14 not
counted (its `reported_as` field: 37 FINDING, 12 DUPLICATE and 2 MERGED). It groups the 37 counted findings into 31
root-cause groups, 5 of which have more than one counted member (RC-FALSE-ABSENT three; RC-PR41-STRANDED-OVERRIDE,
RC-COMMIT-FALSE-POSITIVE, RC-STARTUP-RECOVERY-ROLLBACK and RC-PACKAGE-DST-ARM-GUARD two each). Every group has one
classification and at least one counted member.

**Re-classified entries.** Some drafted findings are not findings; the catalogue's suites record each in a `RECLASSIFIED`
table, which `gen_catalogue.py` checks against `_catalogue_data.RECLASSIFIED`. A re-classified id prints no FINDING line.

| Id | Suite | Record | Why |
|---|---|---|---|
| F-RT02-1 | `test_lab_dst_rtc` | PASS | documented behaviour (RT-02; section 7) |
| F-RT03-1 | `test_lab_dst_rtc` | merged into F-HF08-3 | the RT-03 RTC-step variant of SG-25 |
| F-HF05-1 | `test_lab_ha_lifecycle` | PASS | since V0.1: the documented limit SMR1-OWNER-STAGING (`docs/dev/schedule-manual-restore.md`, "Owner change during a scheduled start"); HF-05 still checks it as a plain check. The CHANGELOG line "the owner's own later change always wins" is unqualified against that limit: a documentation nit, recorded and not counted |

F-HF05-1 and F-RT02-1 left the finding ledger; F-RT03-1 and F-HF07-2 stay in it as MERGED entries.

**Independent checks.** For every finding the catalogue's `verification` field records two summaries: an independent
source-fidelity check (`source_fidelity_check`: the mechanism re-read against the cited source) and an independent
classification check (`classification_check`: the classification, severity and reachability judged against the vocabulary
above). Three findings had no independent check and their entries say so: F-FW03-3 (a duplicate of F-FW01-3), F-FW07-5 and
F-HF09-1. Those three rest on their reproduction in the suite and their `finding-reproduces` checks; F-FW07-5 also on a
control run and an in-memory repair-direction mutant (its corpus document FW-07-i3 fails against that mutant), F-HF09-1 also
on its 40 s boundary twin HF-09-b and the negative controls NC-HF09-1 to NC-HF09-3 (sections 8.3 and 9).

## 5. Model assumptions and known blind spots

The full lists are in the helper docstrings (`MODEL ASSUMPTIONS`, `NOT MODELLED`, `FAIL-LOUD GUARDS`) and the catalogue's
`tiers[].model_assumptions`. The ones that limit what a result means:

1. **Synchronous scripts.** ds.Sim runs every script in 0 ms (`elif kind in ("wait_until", "delay", "logger.log"):` is a no-op in
   `registry/tests/_dump_sim.py`). A power cut lands between two firmware events, never inside a Modbus frame or an NVS write. A
   torn record is not modelled. A firmware end epoch is the gate second here and about 1-2 s later on the device (after the
   snapshot reads; INFERRED, not measured), so the lab is conservative for window-end overruns and lease tails. `script.execute`
   runs the callee to completion inside the caller, while ESPHome's caller continues as soon as the callee suspends: the
   forms in which the two differ, and how often they occur, are HL-11 and rows 1 to 4 of the register in section 2.7.
2. **Latencies.** The coupled defaults are `press_s` 0.117 s and `op_s` 0.58 s per Modbus op, both derived from transaction
   timings already recorded in `home-assistant/tests/_ha_dump_sim.py`; `publish_s` 0.12 s, `cmd_s` 0.03 s and `commit_s` 0.01 s
   are model values. One `op_s` serves both domains. Since V0.1 an op whose outcome is `no_response*` lasts `no_response_s`
   2.0 s (the ESPHome Modbus hub's send-wait) and one whose outcome is `timeout*` lasts `timeout_s` 3.0 s (the firmware's
   bounded wait), both device constants (section 2.6).
3. **Bus model.** `BusModel` is the HA sims' recorded busy windows (`BUSY_10S` / `BUSY_60S` in `_ha_script_sim.py`), the lab's own
   poll traffic, or explicit synthetic windows. It is sampled at entry instants only, and one `bus_idle` flag stands for the bus
   (the turnaround after a transaction's own reply is not modelled). The watchdog phase relative to the HA clock is a sweepable
   parameter; HF-01 sweeps phases 0, 5 and 10 s in quick mode and 0..14 s in extended mode. The scheduler phase itself is
   HL-10 (section 2.5).
4. **Polled sensors.** The attempt counters (30 s) and the TOU power ceiling (60 s) are sampled at uptime multiples of their
   update interval, first one period after power-on. Before a boot's first sample they read `unknown`. ESPHome samples a
   polled sensor first within its random first-run offset (at most 5 s after setup), so the lab is one period late; the
   polled-sensor self-tests and the HF-03 early-reset reach are tagged phase-sensitive (HL-10).
5. **HA restore-state, reconnect and offline calls (ASSUMPTION).** Home Assistant saves helper states every 15 minutes and at a
   clean stop; a crash rolls every package helper back to the last save; persistent notifications are not restored. Dongle
   entities read `unavailable` for a reconnect gap after an HA start or a dongle boot. Real reconnect timing and backoff are not
   modelled. A service call to a dongle entity while the API link is down is dropped silently and logged
   (`offline_policy='silent'`, the `CoupledWorld` default; ASSUMPTION: HA skips an unavailable ESPHome entity);
   `offline_policy='raise'` instead raises `S.ServiceError`, the assumption `home-assistant/tests/_ha_dump_sim.py` makes.
   Every scenario and corpus document runs with the default `'silent'` except HF-09: its outage variants HF-09.6 (under
   both policies) and HF-09.7, and its corpus documents HF-09-a and HF-09-b, use `'raise'`; the coupling self-test checks
   both policies. Which one matches Home Assistant is not known offline (section 5.1, row 5).
6. **HA input_datetime fold (ASSUMPTION).** Home Assistant resolves a naive wall time like zoneinfo with `fold=0`. Real behaviour in
   the repeated or missing hour is not verified offline; HF-08 states both conventions where they differ.
7. **Dump plant (MODEL).** FirmwareWorld has no inverter physics, so a static telemetry image would end a Dump lease early. The
   opt-in `dump_plant` makes the battery follow the ceiling written to 256 while 244 = 0 and drops SOC 1 % per 180 s of discharge.
   PB-02 runs without it (stated in its result).
8. **No inverter physics.** Export, SOC drift and PV change only when a scenario publishes telemetry. A frozen-telemetry guard is
   satisfied by an alternating 1 W noise pattern. The noise MODEL can be switched off only for a whole world (`noise=False`),
   not per signal, so FW-07-I, which freezes one reading while another keeps moving, runs without it and sets every reading
   explicitly for each 10 s poll slot.
9. **No inverter TOU on its own clock.** The inverter executing its TOU slots is not modelled anywhere. The RTC tier models the
   inverter clock as offset plus rate; where a result depends on when the inverter's own clock crosses a slot, it is INFERRED.
10. **RTC policy as a Python mirror.** `ecco_rtc::` runs as `registry/rtc_policy.py`, not the C++ header
    `firmware/include/ecco_rtc_policy.h`. Header-mirror parity is enforced only by `registry/tests/test_rtc_policy.py` section [4]
    (`def section_parity() -> None:`), which needs a C++ compiler: `ECCO_CXX` when it is set, else the first of `g++`, `c++`
    and `clang++` found on `PATH` (`find_compiler`); without one that check fails rather than skips.
11. **Split model for RTC + Dump.** A Dump lease cannot run on D1Sim (its START needs a construct the rig does not model). RT-03
    extracts the lock windows from a DST-night rig and replays them into a FirmwareWorld Dump lease as `correction_in_progress`
    windows. The correction itself does not run in the firmware tier.
12. **Not executed.** Intervals: the 60 s clock read, the 1 s RTC tick, the 10 s FB housekeeping, the 1 s supervision shadow.
    `on_boot` items: two `static_assert` blocks and the FB durable boot read. MODEL handlers replace the poll `on_response` lambdas
    that do not transpile (59x58 display-only no-op; 150x47 the real decode with an exact-count cast rewrite; Blocks A 200x41 and
    B 241x53 their own cache statements). `home-assistant/packages/ecco_system_health.yaml` is not executed in the coupled world.
13. **Physical cause of commit faults unproven.** The `false_negative` and `false_positive` commit policies are lab triggers. For a
    false negative the only device route left is the marker's own `ESP_ERR_NVS_REMOVE_FAILED` (the new copy written, the
    erase of the earlier version failing; ESP-IDF semantics REPORTED); the "unrelated pending key" route cannot reach a
    Phase-B marker commit (section 2.4). The lab models one ESP-IDF fault cell and injects only on a key stored earlier in
    the run. For a false positive no route exists at the ESPHome layer; an ESP-IDF route (an INVALID page after a reported
    flash-op failure) was described by the V0 independent audit (medium confidence, not executed), so the trigger is
    UNKNOWN, not a model artefact. Every finding that needs an injected NVS primitive has device reachability UNKNOWN
    pending the ESP-IDF host NVS test (RC-FALSE-ABSENT: PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN; section 4).
14. **Single-thread interleaving.** Everything runs on one thread. The ESPHome scheduler's interleaving, its random interval
    offsets (HL-10: the lab anchors timers at power-on; same-tick watchdog order is an explicit parameter, both orders swept),
    script modes other than `single`, Modbus latency beyond the per-outcome projection and CRC errors are not modelled. Only
    the first NTP sync per boot is modelled.
15. **Service-call exceptions (ASSUMPTION, HF-09).** `S.ServiceError` is the interpreter's only modelled exception class, and
    it is raised before the call reaches the dongle (a call that raises after it was delivered is not modelled). A Home
    Assistant `vol.Invalid`, other error classes and a timeout after the command was sent are not modelled. The interpreter's
    `fail_services` hook is keyed by service name, so HF-09 arms each injection where the targeted call is the next call of
    that service, and every check asserts which call raised. ESPHome's default 15-minute no-client `reboot_timeout`, which
    would reboot the dongle during a long API outage, is not modelled.

### 5.1 HA dongle models versus the firmware

The existing HA suites drive the real packages against two hand-written dongle models: `S.Dongle` (Free Power,
`home-assistant/tests/_ha_script_sim.py`) and `D.DumpDongle` (Dump to Grid, `home-assistant/tests/_ha_dump_sim.py`). The
coupled tier replaces both with the real firmware (`RealDongle` over one `FirmwareWorld`). The table lists every difference
between a model and the firmware found while the coupled tier was built. Only row 6 is a catalogued finding
(RC-HA-MODEL-FAILED-START, F-HF06-1); rows 1-5 are test-model fidelity notes, not product defects, and are not counted. `FW` is
`firmware/ecco_clock_dongle_stage3_4_free_power.yaml`; each quoted snippet occurs once in its file unless noted.

| # | HA model behaviour | Firmware behaviour (anchor) | Grade | Lab coverage of the firmware behaviour |
|---|---|---|---|---|
| 1 | `S.Dongle` starts with the status `IDLE - no Free Power override active` (`status = "IDLE - no Free Power override active"`) and ends a lease with `RESTORED - exact snapshot verified`. The firmware emits neither text. FPS1 matches only `REJECTED` prefixes of the status today, but the status text is copied into its FAILED results | boots to `Inactive` (`FW` `id(free_power_status).publish_state("Inactive");`) and ends with `FW` `id(free_power_status).publish_state("RESTORED OK - original inverter settings verified");` | VERIFIED by coupled run | `test_lab_selftest_coupling` [1] (the real `RESTORED OK` text after the scheduled lease) and its offline-policy checks (status `Inactive`); HF-01; HF-06-b, where the real `RESTORED OK` text lands in FPS1's FAILED result (F-HF06-3) |
| 2 | the `S.Dongle` gate (`self.flags = {"snapshot": False, "dump": False, "ntp_bad": False, "corrupt": False}`) has no branch for three firmware refusals; the voltage text is in its `REJECT` table but no flag can produce it. FPS1's retried battery-voltage path and its persistent register-244 path are therefore never exercised by the existing FPS1 suite | the Free Power START gate also refuses `FW` `else if (id(reg244_snapshot_valid)) id(free_power_status).publish_state("REJECTED - Register 244 proof transaction awaiting restoration");`, `FW` `REJECTED - plausible live battery voltage required for W-to-A conversion` and the catch-all `FW` `REJECTED - Free Power safety precondition failed` | INFERRED (source read; not executed) | none: no scenario drives a register-244 proof transaction, an implausible battery voltage or the catch-all through FPS1 (a gap) |
| 3 | `S.Dongle` keeps Free Power Snapshot Valid off for a whole healthy lease and goes from ACTIVE straight to its end text (`self._pub(E_STATUS, "RESTORED - exact snapshot verified")`): no RESTORING phase, no restore transaction | Snapshot Valid is set at the durable commit (`FW` `if (data_committed && marker_committed) {` followed by `id(free_power_snapshot_valid) = true;`, a pair that occurs once) and stays on until the restore's Phase D; Active stays on until the restore verifies; the restore starts with `FW` `RESTORING - confirming live inverter state before writing` | VERIFIED by coupled run | `test_lab_selftest_coupling` [1] (mid-lease Active and Snapshot Valid on; RESTORING at the first watchdog slot after the end epoch; the lease end measured inside the restore transaction); HF-01 measures window-end overruns to that edge; NC-PB02-b (SMR1's blocker without Active / Snapshot Valid) is killed |
| 4 | the two models clobber each other when used together for one device: after `set_offline`, `S.Dongle` republishes the Dump Active and Snapshot Valid sensors as `off` (`(E_ATTEMPTS, f"{float(self.attempts)}"), (E_DUMP_ACTIVE, "off"), (E_DUMP_SNAP, "off"),`) and `D.DumpDongle` republishes Free Power Snapshot Valid as `off` and Free Power Active from its own flag; neither model's cross-domain gate flags follow the other model's state. The SMR1 suite builds both models but calls no `set_offline`, so no existing check triggers it | one firmware holds both domains' state, and each START gate reads the other domain's real flags (the Free Power refusal `FW` `id(dump_snapshot_valid)) id(free_power_status).publish_state("REJECTED - Dump to Grid override/recovery owns inverter settings");`) | INFERRED (model code read) | the coupled tier has one `RealDongle` over one `FirmwareWorld`, and every reconnect republishes the whole view from firmware truth; `test_lab_selftest_coupling` checks that the HA-visible binary sensors equal the firmware lambdas and that an API outage republishes the view; HF-04, HF-07 and PB-02 run both domains on that one firmware |
| 5 | the models disagree about a call to an offline dongle: `D.DumpDongle` raises by default (`raise S.ServiceError("dongle offline (ESPHome API not connected)")`, an ASSUMPTION stated in its docstring; the DGS1 suite keeps that default), `S.Dongle`'s switch, number and press handlers drop the call silently. The FPS1 and DGS1 suites therefore test their packages under opposite assumptions | not a firmware question: what Home Assistant does with a service call to an unavailable ESPHome entity | UNKNOWN (real HA behaviour); the lab's default is an ASSUMPTION | `CoupledWorld(..., offline_policy='silent')` by default (section 5, item 5); `'raise'` is selectable and `test_lab_selftest_coupling` checks both; every scenario uses `'silent'` except HF-09's API-outage variants (HF-09.6 under both policies, HF-09.7 and the corpus documents HF-09-a / HF-09-b under `'raise'`); F-HF09-1 reaches the same end state under either policy (V-5 in section 10) |
| 6 | both models keep a failed START's snapshot pending until End & Restore, and SMR1 suite [3] asserts it as the nominal case | a single failed START restores by itself: Dump at its next watchdog tick, Free Power inline; the Dump text still says `FW` `snapshot retained - press End & Restore Now` | VERIFIED by coupled run | HF-06-a, HF-06-b (F-HF06-1, RC-HA-MODEL-FAILED-START, section 8.3) |

### 5.2 Known harness-oracle limitations

The lab's own oracle (the core helpers' bookkeeping, checkers and replay vocabulary, the scheduler and projection models, and
one shared simulator) has 13 known limitations. They are the catalogue's `harness_limitations` (HL-1 to HL-13), each with an
anchor in the code that `test_lab_replay_corpus` re-counts (exactly once; NC-RC-15 shows that a moved anchor is detected),
its effect on the lab's verdicts, the suites that work around it and its status. **Two are fixed in V0.1 (HL-1, HL-6) and 11
are open.** V0.1 added HL-10 to HL-13 and corrected the texts of HL-3 and HL-5. "Missed violation" means a checker can pass a
case it should flag; "false violation" the reverse.

| ID | Where | Limitation | Effect on verdicts | Worked around in | Status |
|---|---|---|---|---|---|
| HL-1 | `_lab_fw.accept_adoption` (called by `FirmwareWorld._adopt_if_clear`): the lab's ORIGINAL after an operator Accept | V0 adopted the live bank as the new ORIGINAL after any Accept call whose marker read CLEAR or ABSENT, also after a refused Accept and for registers the other domain's lease held. V0.1 adopts only after an Accept whose last status is a firmware SUCCESS text that cleared an obligation the domain held, and never for a register another domain holds | V0: wrong in both directions (a residue adopted as baseline hid an override; a false INV-NO-SILENT-OVERRIDE, PB-01 extended seed 929). The root fix changed no counted finding, no suite verdict and no corpus trace digest. Residual: a Free Power Accept whose durable clear is pending (PENDING_CLEAR) adopts nothing, which can only give a false (loud) violation; measured once in quick and twice in extended mode, with no violation | `test_lab_selftest_firmware` [16d] pins the rule against the V0 rule run in memory; PB-01 still issues an Accept only when it cannot move the ORIGINAL (now redundant, kept for comparable statistics); FW-01 to FW-03 and the FW-06 Accept flows judge an Accept by its own result | fixed at the root; the PENDING_CLEAR residual is open |
| HL-2 | `_lab_fw.FirmwareWorld` foreign-register marks (`set_register`, actor `inverter`) | a register the inverter changes itself is marked foreign and keeps the previous ORIGINAL; the mark clears only when ECCO writes that register, so after a later START snapshots and restores the foreign value, the oracle still holds the stale ORIGINAL | `INV-NO-SILENT-OVERRIDE` can report a false override after a foreign change outside any lease is snapshotted by a later START (false violation); a foreign change while a domain holds the register is judged correctly while the holding domain's RAM obligation is visible; a register held only by a ghost's durable marker (a PR41-GHOST false negative, RAM clear) can give a false violation when the ghost-admitted START snapshots the foreign value (PB-01 extended seed 366 under the scratch ESPHome-like phase patch; the RC-PR41-GHOST observation note) | PB-01 draws a foreign change only while a domain holds that register, else an owner change (the new baseline); the FW-06 flows set foreign values only during a lease or an owed restore | open |
| HL-3 | `_lab_fw.FirmwareWorld.rtc_lock_windows`: the RTC lock window MODEL | an empty window list returns before `correction_in_progress` is updated, so replacing the windows with `[]` while a lock is held leaves the RTC lock set until the next reboot (the boot's fresh RAM starts `correction_in_progress` false) | meanwhile every lease end and restore is deferred and every Free Power / Dump START is REJECTED "RTC correction currently active"; `INV-RESTORE-BOUND` explains the deferral as a held lock (missed violation) while directed timing checks would fail; no scenario does this | PB-01 never draws an empty list; FW-08-E, RT-03 and the HF-02 RTC-lock variant pass one non-empty list per world | open |
| HL-4 | `_lab_fw.check_restore_bound` (`INV-RESTORE-BOUND`) | once a restore is due, a link-down, bus-busy, injected-fault or power-off event anywhere in the due period explains the whole period, however long the restore then takes after the link recovered or the fault cleared | a restore delayed long after a link recovery passes (missed violation): the checker itself does not catch F-FW07-1 (the Free Power restore waiting out its comms backoff); in PB-01, where random link, bus and fault actions explain most due periods, the invariant is weak (HL-13 measures it) | FW-07-A, FW-07-B and FW-07-F check the delay after the link recovery directly; FW-07-A and FW-07-I rebase `INV-RESTORE-BOUND` at the link recovery or the boot. **Not worked around in PB-01** | open |
| HL-5 | the `_lab_fw` invariant set: no cross-boot owed-restore checker | `INV-RESTORE-BOUND` explains an open period by any lock held at least one watchdog period and by any `fw.power_off` event (every power cut, reboot and firmware restart logs one; a fired cut counts as well), and `INV-NO-RESUME` and `INV-BOOT-MIRROR` judge each boot on its own, so a restore that stays owed through repeated restarts and is never attempted raises no core violation | a restart loop that never completes an owed restore passes every core invariant: each restart's `fw.power_off` alone excuses the open period (missed violation) | FW-08-F characterises the stuck-lock restart loop itself (restarts about 203 s apart, no restore attempt, 244 and 256-261 unchanged, no CRITICAL status), pins it as F-FW08-1 with a `finding-reproduces` check and corpus FW-08-f, and states that the core checkers see no violation | open |
| HL-6 | `registry/tests/_dump_sim.py` `load_record_status` (shared simulator): a per-key boot load fault; and its sibling, the lab's `wrong_size` boot fault | an injected per-key boot load fault reads READ_ERROR also for a key that was never stored, while the firmware's length probe (`classify_load_failure` in `firmware/include/ecco_durable_snapshot.h`) reports NOT_FOUND, that is ABSENT, there; the `wrong_size` fault likewise created a malformed record under a key that held none | V0: a fail-closed UNKNOWN or MALFORMED lockout no device reaches; such PB-01 draws drove 18 of its 19 extended-mode N17 hits. Since V0.1 both faults are refused on a key never stored earlier in the run, so no verdict rests on them | `test_lab_selftest_firmware` [8b] pins the refusal; PB-01 draws a per-key boot fault only on a key holding a record; the directed boot read errors of FW-03, FW-04 and FW-05 fault keys a lease has stored | fixed by a lab-side refusal (the NVS used-key rule); the shared simulator is unchanged |
| HL-7 | `_lab_ha` replay observer `invariants` (coupled tier) | it returns the raw violation list of the whole merged log, without the firmware tier's filters (boot, tags, untagged, count and summary forms of `_lab_fw.filter_violations`) | a coupled corpus document cannot pin an expected violation in a sequence-free form: a coupled FINDING document asserts its violation only as `!= []` for one invariant, so an additional violation of that same invariant would not fail the replay | HF-09-a (F-HF09-1) pins `!= []` on `INV-HF-ARM-OFF` plus exact result, switch, SMR1, blocker, notification and firmware-status expectations, and `== []` on the invariants that must hold; the HF-01 documents bracket the simulated overrun between two `INV-HF-WINDOW` bounds; the HF-07 documents assert `== []` on the firmware invariants that must hold | open |
| HL-8 | `_lab_ha.CoupledWorld.dump_plant`: the opt-in Dump plant MODEL | the plant is a `CoupledWorld` method, not a replay action or a world option, so no corpus document and no PB-02 sequence can run a Dump lease with it; on the static telemetry image the firmware's own controller ends a Dump lease early (CONTROLLER NO RESPONSE, failing closed) | Dump windows in the corpus and in PB-02 are mostly not run to their end, so Dump window-end behaviour is judged only where a suite calls `dump_plant()` in memory (a coverage limit, not a wrong verdict) | HF-01 and HF-04 run their Dump schedules with the plant (corpus HF-01-c is shrunk to a 5-min window that ends by DURATION EXPIRED without it); the HF-07 main chains, the HF-08 Dump runs and the HF-03 extended site-cut variant use it; the HF-07 corpus cuts 5 min into the lease; PB-02 states the gap in its result | open |
| HL-9 | `_lab_ha` coupled replay actions: no service-fault action | the coupled replay vocabulary has no action that makes a Home Assistant service call raise (the interpreter's `World.fail_services` hook); a raised call reaches the corpus only through `api_outage` under `offline_policy='raise'` | HF-09.1 to HF-09.5 (a raised press, arm, restore write or turn-off) are verified in their suite only and are not pinned by corpus documents; F-HF09-1 is pinned only in its API-outage form (a coverage limit of the corpus, not a wrong verdict) | HF-09 sets `fail_services` per service name inside its suite, every check asserting which call raised; HF-09-a (F-HF09-1) and its PASS twin HF-09-b reach `S.ServiceError` through `api_outage` with `offline_policy='raise'` and are replayed by the suite and by `test_lab_replay_corpus` | open |
| HL-10 | the interval phase MODEL: `_lab_fw` scheduler (`_sched_reset`, `run_for`), the coupled tier's polled template sensors, the RTC rig's interval start | every executed interval runs first at its `startup_delay`, else one period, after power-on with zero offset (plus the `phase_ms` sweep) and is rescheduled at due + T; ESPHome 2026.8.2 runs it first at setup plus a random offset in [0, min(T/2, 5 s)) and reschedules at now + T (section 2.5) | a verdict that pins an instant, a same-tick order or a bound on the 5 s / 10 s / 15 s grid holds at the lab's phase only. Every check that failed under an in-memory ESPHome-like phase patch (17 quick configurations, 3 extended seeds), every timing-bound check the audit named and every check the V0.1 review found phase-dependent without a FAIL line (the HF-03 whole-site cut grid and the `test_lab_ha_lifecycle` finding register) is tagged: 200 prefixes in 13 suites, 442 executed tagged checks in quick mode and 503 in extended mode, 21 of 39 scenarios and 18 of 51 findings (11 counted) flagged (195, 427 and 488 before the W6-1c correction, 188, 406 and 467 before the W6-1b correction and 182, 388 and 449 before the W6-1 correction; the three corrections' 18 corpus trace-digest pins and their replay checks are tagged, and the patch was run on the b3 to b7 scenarios only by the internal regression review of W6-1c, on `test_lab_fw_guards` and `test_lab_replay_corpus`, with no untagged FAIL). Under the patch the exact pins of four counted reproductions fail (F-HF01-1 and F-HF04-2 in 17 of 17; F-HF04-1 in 14 of 17; F-HF08-3 in 6 of 17); F-FW03-2's composite pin fails in 17 of 17 by construction while its Dump-first context-hold signature reproduces in 10 of the 17; F-HF03-2 reproduced at the 60 s and 120 s / 5 s whole-site cut points wherever its section ran, the 5 s / 5 s point taking the no-new-lease branch in 4 of 5; the corpus FINDING documents FW-05-e, FW-06-a, FW-07-i3 and HF-05-b fail an expectation while the suite pins of their findings hold. In quick mode `test_lab_ha_schedules` (11 of the review's 11 configurations) and `test_lab_ha_lifecycle` (12 of 17) end without a LAB-SUMMARY on a refused interleaving; extended mode adds `LabUnsupported` refusals in the `test_lab_ha_lifecycle` and `test_lab_ha_phantom` extended sections. At f11d85f `test_lab_property` (the PB-03-b replay) and `test_lab_selftest_firmware` (a ValueError) stopped too; they now record a tagged FAIL and continue. The RC-FALSE-ABSENT, RC-PR41-STRANDED-OVERRIDE and RC-PR41-GHOST reproductions held under the patch; only their corpus trace digests failed | FW-03 runs both watchdog orders and, in extended mode, a de-aligned phase sweep; HF-01 sweeps the watchdog phase; every timing-bound check carries a tag, the HF-03.4 whole-site cut grid checks, the F-HF03-2 pins and the finding register included; in every suite a stale-tag check fails loud; the replay suite's engine controls (NC-RC-1, NC-RC-4) run on the expectations that hold on the tree under test | open: the lab keeps its zero-offset grid; an ESPHome-faithful phase distribution is not modelled |
| HL-11 | `registry/tests/_dump_sim.py` `Sim.execute` (shared simulator) and `_lab_fw` `StrictSim` / `LabEntity.is_running`: synchronous `script.execute` | `script.execute` runs the callee to completion inside the caller, and a script counts as running only while it is on the lab's call stack; ESPHome's caller continues as soon as the callee suspends, and a single-mode script drops an execute while an earlier run is still in flight | four divergent forms (section 2.7, rows 1 to 4), measured at f11d85f with a scratch hook: the caller-continues form 1272 / 6515 times in quick / extended mode, all in Dump paths; the double-end form 0 / 0 (a crafted probe gives 1); a same-instant re-execute 183 / 1715; `is_running()` evaluated 0 / 0 times. No catalogued verdict is known to rest on these forms, but the lab does not detect them: in the firmware tier they pass silently | `test_lab_selftest_coupling` [16] pins the coupled-tier half (MISS-HA-1 refused; a press while the script's own work is pending still dropped, as on the device) | open: an asynchronous script model is not implemented, and `_dump_sim.py` is a shared interpreter the lab does not modify |
| HL-12 | the lab's fail-loud rule (`_lab_ha` projection, press rule and guards; `_lab_fw` allow-lists and used-key rule; the replay engine; the output contract) | fail loud covers only the constructs the lab detects. Still silent: lock-free delays and polls (zero projected time), Modbus turnaround and queueing, a `wait_until` false in the lab, the synchronous `script.execute` forms (HL-11), the scheduler phase (HL-10) and the signedness of `u`-suffixed literals | a PASS means the run met no detected unmodelled construct, not that the device would behave the same where the lab is silent. The V0.1 refusals met 0 scenario occurrences (measured at f11d85f); the silent items are counted in the register (section 2.7). The V0.1 corrections turned no previously passing scenario UNSUPPORTED | `test_lab_selftest_coupling` [15] to [18] and `test_lab_selftest_firmware` [8b] pin every refusal; `test_lab_ha_lifecycle` and `test_lab_ha_schedules` print refused sweep points as UNSUPPORTED | open (a scope statement): refusing the silent items needs an asynchronous script and bus model |
| HL-13 | `_lab_fw` oracle checkers: `INV-NO-SILENT-OVERRIDE`'s explanation rule, `INV-RESTORE-BOUND`'s excuse set, the invariant set | (1) any RAM-visible obligation explains every differing owned register: the checker does not map a register to the domain that owns it; (2) one excuse inside a due period explains the whole period (HL-4); (3) no invariant checks SG-02 containment: `INV-LOCKOUT-QUIET` only whitelists the literal 244 = 2 | each can only miss a violation. (1) a white-box override of 230 during a Dump lease stays masked while a Dump obligation is visible; (2) measured at f11d85f with a counting copy of the checker: 580 / 3955 over-bound evaluations excused in quick / extended mode, a true latch 4 / 68 times (3 / 38 distinct periods), among them 32 PB-01 extended-mode periods not triaged; (3) the audit's mutant M5 (containment never armed) passes all eight firmware invariants; at f11d85f it is killed only by directed checks and corpus replays | FW-07-A, FW-07-B and FW-07-F measure the delay after link recovery directly; FW-01, the FW-04 guard and the HF-07 chains assert the SG-02 containment writes and the bank values directly | open: a per-register explanation rule, expiring excuses and an SG-02 containment invariant are not implemented |

The HL-11 to HL-13 counts were measured at commit f11d85f, the V0.1 tree after the NVS correction (B5), as the register in
section 2.7 was; the later V0.1 changes changed no executed scenario and no corpus trace, and the counts were not re-taken
(the catalogue's HL texts say the same). The W6-1, W6-1b and W6-1c corrections added the 18 FW-09 b3 to b7 scenarios
and their corpus documents after that, leaving every existing check verdict and trace digest unchanged; the counts do not
include their runs.

## 6. Coverage matrix

**What the lab runs as real source, as a stub or model, and not at all.** Every lab result rests on this split; the section 5
items give the detail.

| Class | Components |
|---|---|
| REAL (the repository source executes) | firmware (firmware and coupled tiers): the Free Power and Dump to Grid START / END / restore / recovery / containment scripts, both 15 s watchdogs, `on_boot` except the FB durable boot read, the manual TOU and register 244 Load / Apply / Restore buttons, the poll scripts with their Modbus reads and failure handlers, the executed intervals (1 s export trip, 5 s census, 10 s evidence expiry, 1 s supervision, 1 s manual TOU, the poll intervals' conditions), the template binary sensor lambdas; firmware (rtc tier): the RTC read / correction lambdas, the Free Power START and its 15 s watchdog; HA (coupled tier): the FPS1, DGS1 and SMR1 packages and the effective grid charge limit template of `home-assistant/packages/ecco_runtime_config.yaml` |
| STUB / MODEL (the lab supplies it) | the poll `on_response` handlers (59x58 a display-only no-op; 150x47 the real decode after an exact-count cast rewrite; Blocks A 200x41 and B 241x53 their own cache statements); the inverter register bank (`SITE`), the telemetry image and the opt-in `dump_plant`; `ecco_rtc::` as the Python mirror `registry/rtc_policy.py`; the NTP clock (exact, first sync only) and the inverter clock as offset plus rate; the RTC lock windows of the firmware tier; NVS (one ESP-IDF fault cell per primitive, injected only on keys stored earlier in the run), Modbus and link fault policies; the meter-noise pattern (switchable off per world); the scheduler phase (zero offset on the power-on grid); the coupled latencies with the per-outcome projection (`op_s`, `no_response_s`, `timeout_s`), `BusModel`, the projection of synchronous firmware runs, the polled-sensor phase, HA restore-state, the reconnect gap, the offline service-call policy and service-call exceptions (`S.ServiceError` raised before delivery, injected by the interpreter's `fail_services` hook) |
| UNMODELLED (not executed or not represented) | in the firmware and coupled tiers the 60 s clock read and the 1 s RTC tick (the rtc tier runs the RTC lambdas instead); the 10 s FB housekeeping, the 1 s supervision shadow and the FB Review / Save scripts; `home-assistant/packages/ecco_system_health.yaml`; the ESPHome scheduler's interleaving and random interval offsets, asynchronous `script.execute`, script modes other than `single`, Modbus turnaround and queueing, lock-free delay durations, CRC errors; a cut inside a Modbus frame or an NVS write (torn records); the other ESP-IDF NVS fault cells (an old copy resurfacing, an INVALID page refusing writes), a persistent CRC read error, commit faults on a never-used key; NTP loss after a first sync; the inverter running its TOU slots on its own clock; inverter physics; real HA reconnect timing; HA exception classes other than `S.ServiceError` and a service call that raises after delivery; ESPHome's no-client `reboot_timeout` |

**Existing coverage** is by test file (`test_ecco_*` files are in `home-assistant/tests/`, the others in `registry/tests/`); lab
coverage is by scenario. Each existing suite carries its class for the behaviour it covers: **(R)** the firmware source executes
in a simulator (`registry/tests/_dump_sim.py`, `registry/tests/_free_power_action_sim.py` or `registry/tests/_fbd1_harness.py`),
sometimes as a script or boot slice with other parts stubbed; **(S)** the behaviour comes from a hand-written stand-in for a
layer: an HA dongle model (the HA packages themselves are real), a Python reference model or the RTC policy mirror; **(T)**
source-text or structural checks only, no behaviour; **(T+S)** both T and S. The class is the lab's reading of each suite's
imports and docstring, not a property the suites declare.

| Dimension | Existing suites | Lab scenarios |
|---|---|---|
| schedule start / retry | `test_ecco_free_power_schedule_reliability` (S), `test_ecco_dump_to_grid_schedule_reliability` (S), `test_ecco_start_failure_alert` (S) | HF-01, HF-02, HF-04, HF-05, HF-06, HF-09, PB-02 |
| lease acquisition | `test_cross_domain_start_gates` (T+S), `test_dump_to_grid_behaviour` (R), `test_free_power_write_sequencing_hardening` (R), `test_sg01_journal_phase1_2` (R) | FW-01, FW-05, FW-06, FW-10, HF-04, HF-07, PB-01 |
| durable snapshot | `test_recovery_marker_state_machine` (T), `test_sg06_boot_durable_read_fail_closed` (R), `test_dump_v2_ownership_evidence` (R), `test_free_power_dump_obligation_arbitration` (T+S), `test_durable_obligation_arbitration` (T+S) | FW-01, FW-02, FW-03, FW-04, FW-05, FW-06, FW-10, FW-11, PB-01 |
| commit false negative | `test_free_power_dump_obligation_arbitration` (T+S), `test_sg01_journal_phase1_2` (R; true negatives only) | FW-01, FW-02, FW-03, FW-05, FW-06, HF-07, PB-01 (injected only on keys stored earlier in the run) |
| active lease | `test_dump_to_grid_behaviour` (R), `test_dump_safety_fcp2` (R), `test_free_power_reboot_behaviour` (R) | FW-04, FW-07-A, FW-07-C, FW-07-H, FW-07-I, FW-08-C, FW-08-D, HF-01, HF-03, RT-01, RT-03 |
| HA restore obligation | `test_ecco_schedule_manual_restore` (S) | HF-01, HF-02, HF-05, HF-06, HF-07, HF-09, PB-02 |
| lock contention | `test_write_surface_invariants` (T), `test_dump_safety_fcp2` (R), `test_rtc_verification_lock_leak` (T+S), `test_fbd1_liveness` (R) | FW-08-A, FW-08-B, FW-08-C, FW-08-D, FW-08-F, HF-05 |
| stale state | `test_dump_to_grid_behaviour` (R), `test_dump_safety_fcp2` (R), `test_ecco_dump_to_grid_schedule_reliability` (S) | FW-07-A, FW-07-B, FW-07-C, FW-07-F, FW-07-H, FW-07-I |
| clock policy (RTC / DST) | `test_rtc_policy` (S; the C++ header only where a compiler is found: `ECCO_CXX`, else `g++`, `c++` or `clang++` on `PATH`), `test_fbd1_liveness` (R), `test_cross_domain_start_gates` (T+S) | FW-08-E, HF-08, RT-01, RT-02, RT-03, PB-03 |
| terminal restoration | `test_dump_to_grid_behaviour` (R), `test_sg01_self_partial_phase3_4` (R), `test_free_power_recovery_force_restore` (T+S), `test_dump_lockout_containment_sg02` (R) | FW-01, FW-02, FW-03, FW-05, FW-06, FW-07-B, FW-07-F, FW-07-I, FW-09, HF-01, HF-06, HF-09, RT-01 |
| human manual change | `test_manual_tou_phase1_ownership_gates` (R), `test_ecco_tou_target_soc_edit` (S), `test_ecco_schedule_manual_restore` (S), `test_dump_lockout_containment_sg02` (R) | FW-02, FW-07-D, HF-02, HF-05, PB-01 |
| HA restart | `test_ecco_free_power_schedule_reliability` (S), `test_ecco_dump_to_grid_schedule_reliability` (S), `test_ecco_schedule_manual_restore` (S) (graceful restarts only) | HF-02, HF-03, HF-07, PB-02 |
| dongle reboot / power cut | `test_sg01_phase5_hardening` (R), `test_dump_v2_ownership_evidence` (R), `test_free_power_reboot_behaviour` (R), `test_dump_to_grid_behaviour` (R) | FW-01, FW-04, FW-05, FW-07-C, FW-07-E, FW-07-G, FW-07-I, FW-08-B, FW-11, HF-03, HF-07, PB-01, PB-03 |
| Modbus faults | `test_dump_to_grid_behaviour` (R), `test_free_power_write_sequencing_hardening` (R), `test_free_power_reg244_context_v4` (R), `test_fbd1_liveness` (R) | FW-07-B, FW-07-D, FW-07-F, FW-07-H, FW-08-A, FW-09, HF-06, PB-01 |

Unexpected Home Assistant service exceptions are covered by HF-09 (schedule start / retry, HA restore obligation, terminal
restoration). The existing FPS1, DGS1 and SMR1 suites already raise service calls with the interpreter's `fail_services`
hook, against the hand-written dongle models (S); HF-09 raises such calls, and the write-enable turn-offs, against the real
firmware.

**Intersections.** The catalogue records 19 intersections. The 9 marked R are the required high-risk pairs: the list is
`REQUIRED_PAIRS` in `test_lab_replay_corpus.py`, which checks that the catalogue records each of them. The Existing column
uses the same (R) / (S) / (T) classes.

| | Pair | Existing | Lab | Remaining gap |
|---|---|---|---|---|
| R | schedule start / retry x HA restart | `test_ecco_free_power_schedule_reliability` (S) | HF-02, PB-02 | existing coverage is graceful restarts against the dongle model; the crash rollback rests on the 15-min restore-state ASSUMPTION; real reconnect timing not modelled |
| R | lease acquisition x commit false negative | `test_free_power_dump_obligation_arbitration` (T+S) | FW-01, FW-05, HF-07, PB-01 | the physical trigger (the marker's own `REMOVE_FAILED`) is REPORTED, not verifiable offline; rate UNKNOWN; since V0.1 injected only on a key stored earlier in the run (one ESP-IDF fault cell, the others not modelled) |
| R | active lease x dongle reboot / power cut | `test_free_power_reboot_behaviour` (R) | FW-04, FW-07-C, FW-07-E, HF-03, HF-07 | a cut inside a Modbus frame or NVS write is not modelled; a cut inside a projected transaction is UNSUPPORTED (HF-03-UNS-1) |
| R | HA restore obligation x human manual change | `test_ecco_schedule_manual_restore` (S) | HF-05, HF-02 | owner edits inside a projected transaction are UNSUPPORTED (HF-05-UNS-1, -2); the restore-write race rests on model latencies |
| R | lock contention x terminal restoration | `test_dump_safety_fcp2` (R) | FW-08-B, FW-08-C, FW-08-D, FW-08-F | the lock leak is a white-box RAM injection (no leaking path that overlaps a lease is known); FB Review / Save mutex holds UNSUPPORTED (FW-08-U2) |
| R | stale state x active lease | `test_dump_safety_fcp2` (R) | FW-07-A, FW-07-C, FW-07-H, FW-07-I | the polls run with MODEL `on_response` handlers; frozen telemetry with the link up (FW-07-I) needs the meter-noise MODEL off for the whole world, so every poll slot is set explicitly and the SOC changes only when a scenario sets it (no SOC physics); NTP loss after a first sync UNSUPPORTED (FW-07-U1) |
| R | clock policy x active lease | `test_fbd1_liveness` (R) | RT-01, RT-03, FW-08-E | no Dump lease on the RTC rig (split model); windows beyond the 90 s breaker UNSUPPORTED in the firmware tier (FW-08-E-U1) |
| R | durable snapshot x dongle reboot / power cut | `test_sg01_phase5_hardening` (R) | FW-04, FW-05, FW-06, FW-11, PB-01 | torn records and a cut between `save()` and `sync()` are not modelled; the lab boots through the FULL `on_boot` where existing sweeps use boot slices |
| R | commit false negative x HA restore obligation | none | HF-07 | only the Phase-B marker false negative is driven through HA; the system-health mapping is UNSUPPORTED (HF-07/system-health) |
| | schedule start / retry x dongle reboot / power cut | none | HF-03 | the early-reset case is a PROXY (grade INFERRED); later in-transaction cuts UNSUPPORTED |
| | schedule start / retry x terminal restoration | `test_ecco_free_power_schedule_reliability` (S) | HF-01, HF-04 | the existing window-end check runs against the model's instant end; the watchdog phase and bus traffic are not measured on hardware |
| | HA restart x dongle reboot / power cut | none | HF-03 | the outcome depends on the HA versus dongle boot order (swept by down times); real reconnect timing not modelled |
| | durable snapshot x human manual change | none | FW-02 | the HA target-SOC editor path under a phantom obligation is source-read only |
| | commit false negative x terminal restoration | `test_durable_obligation_arbitration` (T+S) | FW-03, FW-05 | the same-tick watchdog order is a lab tie; both orders swept (on hardware each boot draws a random order) |
| | stale state x terminal restoration | `test_dump_safety_fcp2` (R) | FW-07-B, FW-07-F | none recorded |
| | Modbus faults x schedule start / retry | `test_ecco_schedule_manual_restore` (S) | HF-06 | the existing SMR1 premise (End & Restore after a failed START) holds only for the HA models |
| | schedule start / retry x HA restore obligation | `test_ecco_schedule_manual_restore` (S) | HF-01, HF-06, HF-09 | a raised service call (`S.ServiceError` before delivery, the interpreter's only modelled exception) is injected per service name inside the HF-09 suite; no replay action injects it (HL-9), so only the API-outage form (HF-09-a, HF-09-b) is pinned in the corpus |
| | clock policy x schedule start / retry | none | HF-08, PB-02 | real HA fold / gap resolution INFERRED (fold=0 ASSUMPTION) |
| | clock policy x lease acquisition | `test_cross_domain_start_gates` (T+S) | HF-08, RT-03 | SG-25 reproduces (known, deferred); inverter TOU on its own clock not modelled |

## 7. Scenario catalogue summary

39 scenarios: 26 firmware, 10 coupled, 3 rtc (scenario priority P1 11, P2 19, P3 9). FW-07 and FW-08 are listed by their
sub-scenarios. Every scenario's grade is VERIFIED. A scenario's classification is its headline label: 17 PASS, 15
FINDING-NEW and 7 FINDING-KNOWN. The labels are not finding counts and do not line up with the finding classes: FW-07-I is
PASS but owns the counted F-FW07-5; PB-01 is FINDING-NEW with no counted finding (each of its signatures duplicates a
directed finding); FW-03 is FINDING-NEW but its one counted finding, F-FW03-2, is KNOWN:N16; RT-03 is KNOWN:SG-25 with
its finding merged into F-HF08-3. The counted findings are in section 8.

| ID | Title | Tier | Pri | Classification | Corpus |
|---|---|---|---|---|---|
| FW-01 | Phase-B marker false negative (phantom), the other domain's START admitted, reboot: PR41 dual lockout, SG-02 containment, operator surfaces | firmware | P1 | FINDING-NEW | FW-01-a..d |
| FW-02 | Phantom obligation plus an owner manual TOU slot apply, then reboot | firmware | P2 | FINDING-KNOWN:N15 | FW-02-a, b |
| FW-03 | Multi-obligation boot order (S4 before PR41) and same-tick watchdog order | firmware | P2 | FINDING-NEW | FW-03-a..c |
| FW-04 | NVS false ABSENT at reboot during an ACTIVE lease: single key vs whole-partition erase | firmware | P1 | FINDING-KNOWN:PLATFORM-ABSENT | FW-04-a..e |
| FW-05 | Power cut at every durable / Modbus event of a START and a restore while the other domain holds RESTORE_REQUIRED | firmware | P1 | FINDING-KNOWN:N17 | FW-05-a..e |
| FW-06 | Commit false negatives / positives at every other commit site; the START commit-failure status cascade | firmware | P2 | FINDING-NEW | FW-06-a..e |
| FW-07-A | Link down during an ACTIVE Dump lease: TELEMETRY LOST, supervised retries, SG-39 recovery | firmware | P2 | PASS | FW-07-a |
| FW-07-B | Link down during the restore: comms backoff 15/30/60/120/300 s, SG-39 at recovery | firmware | P2 | PASS | FW-07-b |
| FW-07-C | Reboot during an ACTIVE lease, link down after boot: no resume, 90 s no-fresh-SOC supervision | firmware | P2 | PASS | FW-07-c |
| FW-07-D | Reboot with the inverter refusing 244 writes: the persisted owed Stop SOC governs | firmware | P2 | FINDING-KNOWN:FCP2-R1 | FW-07-d |
| FW-07-E | Reboot with NTP invalid at early uptime: the 300 s uptime grace never delays the owed restore | firmware | P2 | PASS | FW-07-e |
| FW-07-F | Free Power analogue: link down during the restore, no SG-39 retry | firmware | P2 | FINDING-NEW | FW-07-f |
| FW-07-G | Reboot while a restore is owed: the end reason is misattributed to the restart | firmware | P3 | FINDING-NEW | FW-07-g |
| FW-07-H | One failed configuration block read ends an ACTIVE Dump lease | firmware | P3 | FINDING-NEW | FW-07-h |
| FW-07-I | Frozen telemetry with the link up during an ACTIVE Dump lease (grid CT, battery power, SOC): the frozen end crossed with the restore, a power cut at a restore write and a reboot | firmware | P2 | PASS | FW-07-i, i2, i3 |
| FW-08-A | Single-op Modbus outcome sweep: which outcome leaks a transaction lock | firmware | P3 | PASS | FW-08-a |
| FW-08-B | Manual write lock leaked at Dump lease end: deferral, 180 s escalation, restart, boot restore | firmware | P3 | PASS | FW-08-c |
| FW-08-C | Dump operation flag leaked during an ACTIVE lease: WRITE LOCK STUCK end, restart, boot restore | firmware | P3 | PASS | FW-08-d |
| FW-08-D | Free Power analogue of a lock leak: escalation restart, S3, restore | firmware | P3 | PASS | FW-08-e |
| FW-08-E | RTC lock windows deferring restores | firmware | P3 | PASS | FW-08-b |
| FW-08-F | Lock leak recurring before every boot's first watchdog tick: restart loop | firmware | P3 | FINDING-KNOWN:FCP2-F6 | FW-08-f |
| FW-09 | Dump restore verification: a write acknowledged but not applied (244; 256-261 block; a single slot; in containment), a verify read that fails after the write landed (244; 256-261) or in containment, and every containment claim backed by the bank | firmware | P1 | PASS | FW-09-a, b, b2, b3-256..261, b4-ct, b4-cb, b4-co, b5-lo, b6-ok, b6-x257, b6-x260, b7-rbnr, b7-rber, b7-cmnr, b7-ab, b7-af, c, c2 |
| FW-10 | Dump START gate: the Free Power terms refuse alone (Free Power RESTORE_REQUIRED, PENDING_CLEAR, UNKNOWN lockout) with every Free Power owned register at ORIGINAL | firmware | P2 | PASS | FW-10-a..c |
| FW-11 | Free Power marker boot faults on a used `fp.valid` key: read error -> UNKNOWN lockout; wrong size and bad magic -> MALFORMED lockout | firmware | P2 | PASS | FW-11-a..d |
| HF-01 | Scheduled Free Power and Dump end to end; window-end overrun vs the HA suites' model-only +30 s check (the packages state that nothing starts or runs after the window end) | coupled | P1 | FINDING-NEW | HF-01-a..c |
| HF-02 | HA restart in STARTING / ACTIVE, crash-window helper rollback, reconnect gaps | coupled | P1 | FINDING-NEW | HF-02-a..d |
| HF-03 | Dongle reset right after the START gate pass, during ACTIVE, and a whole-site power cut | coupled | P1 | FINDING-NEW | HF-03-a..c |
| HF-04 | Back-to-back lease tails: Dump to Free Power, Free Power to Dump, same domain | coupled | P2 | FINDING-NEW | HF-04-a..d |
| HF-05 | Owner edits of the staged values during STARTING / ACTIVE / RESTORING; owner START racing the schedule | coupled | P2 | FINDING-KNOWN:SMR1-OWNER-RESTORING | HF-05-a, b |
| HF-06 | Failed START with a retained snapshot vs the HA model premise (End & Restore required) | coupled | P2 | FINDING-NEW | HF-06-a, b |
| HF-07 | Phantom obligation through HA, the other schedule admitted, dongle reboot, PR41 lockout | coupled | P1 | FINDING-NEW | HF-07-a..f |
| HF-08 | DST nights through FPS1 / DGS1 and the firmware Dump START TOU gate | coupled | P1 | FINDING-NEW | HF-08-a..d |
| HF-09 | Unexpected HA service exceptions against the real firmware: the scheduled START press, DGS1's write-enable arm, an SMR1 restore write right after the firmware's restore, the post-START and no-answer write-enable turn-offs | coupled | P2 | FINDING-NEW | HF-09-a, b |
| RT-01 | Free Power lease across 01:00 UTC on both nights: lost write callback, breaker, cooldown, deferral | rtc | P1 | PASS | RT-01-a, b |
| RT-02 | Stopped inverter clock with an outstanding restore obligation | rtc | P3 | PASS | RT-02-a |
| RT-03 | Split model: DST-night lock windows replayed into a FirmwareWorld Dump lease | rtc | P2 | FINDING-KNOWN:SG-25 | RT-03-a, b |
| PB-01 | Firmware random sequences, all eight firmware invariants, known residuals by signature | firmware | P1 | FINDING-NEW | PB-01-a..f |
| PB-02 | Coupled random sequences: arms, owner edits, HA restarts, dongle reboots, bus, link | coupled | P2 | PASS | PB-02-a |
| PB-03 | Time properties: London tz vs oracles, fold / gap, UTC-monotonic logs, millis() wrap | firmware | P2 | PASS | PB-03-a, b |

HF-05's label changed in V0.1 from FINDING-KNOWN:SMR1-OWNER-STAGING to FINDING-KNOWN:SMR1-OWNER-RESTORING: its STARTING
case is now a documented limit, not a finding (section 4), and F-HF05-2 is its remaining counted finding.

**Notable PASS results** (from the catalogue's result summaries):

- FW-05: 41 quick power-cut runs (a cut at every state-changing START / restore event, both directions and the N17 shape), each
  rebooted through the FULL `on_boot`, leave no invariant violation; INV-BOOT-MIRROR judged all 41 boots. Since V0.1 each
  phantom is injected on a used marker key after a completed lease of its domain; every cut point's outcome equals the
  never-used form.
- FW-06: 47 `commit_record` sites in 28 component / tag groups; every group is reached by the 15 flows (40 distinct commit
  signatures; text sites inside one group are not distinguished one by one). False negatives and false positives at every
  reachable signature leave no violation except the two Phase-B marker false positives (RC-COMMIT-FALSE-POSITIVE). Since
  V0.1 every flow first completes a lease of its domain, so the never-used forms are no longer injected.
- FW-07-I: with the link up, a grid CT that repeats while the battery moves ends the ACTIVE Dump lease 'GRID CT FROZEN' 60 s
  after the first frozen read; a repeating battery power reading ends it 'BATTERY POWER TELEMETRY FROZEN'; a SOC that stays
  fresh and plausible but never changes ends it 'SOC TELEMETRY FROZEN' once 1500 Wh are counted (about 5158 s after START). A
  power cut at the restore's first write boots with the stored RESTORE_REQUIRED mirrored in RAM and no resume, and the
  boot-path restore completes 13 s after the boot. A reboot after a completed restore owes nothing; a new START on the
  still-frozen CT ends again by the detector 78 s later. The end reasons themselves are already tested by
  `registry/tests/test_dump_safety_fcp2.py` on hand-fed publishes; new here is the crossing with the restore, the power cut and
  the reboot. Extended mode sweeps freeze onset x power-cut point. The scenario also found F-FW07-5 (section 8.3). Its
  timing checks sit on the 10 s poll / 15 s watchdog grid and are phase-sensitive.
- FW-09 (new in V0.1): the inverter acknowledges but never applies the Dump restore's 244 := 2; both attempts fail on the
  244 readback, 256-261 are contained at min(original, 500 W), the marker stays RESTORE_REQUIRED, one automatic retry,
  then the durable operator lockout; Force Restore Original completes once 244 is applied again. A 6-slot 256-261 write
  acknowledged but not applied, and a single-slot write next to a FOREIGN slot, fail on their readback the same way, with
  no "restored and verified" claim. A failed verify read after the write landed (244, or 256-261) fails the attempt on the
  comms path, keeps the marker and completes after the backoff. Every core invariant holds; the status texts match the
  bank. Since the W6-1 correction, b3-256 to b3-261 (corpus FW-09-b3-256 to FW-09-b3-261) exercise the per-slot
  readback verify of each slot k on the non-containment per-slot plan, which is where the 8 named per-slot mutants
  (C6k0 to C6k5, C6s0, C6s5) are killed (section 9; the six regressions that survived it are killed by the W6-1b
  scenarios below): a
  FOREIGN slot (the inverter's own 4000 W in 261, or in 256 for b3-261) makes the restore plan per slot and is never
  written, and every single-register write of k after the End is acknowledged but not applied. The first attempt
  writes 244 and then every non-FOREIGN slot one by one, k included, and fails on k's readback; the retry at the next
  watchdog tick writes k alone and fails again; then the documented operator lockout, with no "RESTORED OK" and no
  "restored and verified" claim, the marker RESTORE_REQUIRED, k reported at the lease's 1000 W and no
  INV-NO-SILENT-OVERRIDE violation. The expectations are derived from the firmware source and cite its lines in the check
  names (the FOREIGN classification, the per-slot plan, the readback compare, the FOREIGN-lockout text and the
  second-mismatch lockout). Since the W6-1b correction, seven more scenarios cover the shapes on which an internal review
  of W6-1 found per-slot verify regressions that survived it (section 9; what remains is section 15, item 15). b4-ct,
  b4-cb and b4-co (corpus FW-09-b4-ct, FW-09-b4-cb, FW-09-b4-co) acknowledge every 244 write without applying it, so 244
  is not proven and the restore contains every non-FOREIGN slot at min(original, 500 W); then one slot's floor write (258,
  next to a FOREIGN 261, so the plan is per slot), the 6-slot floor block (nothing FOREIGN) or the floor write of 256 is
  acknowledged but not applied (in b4-co the inverter puts 256 back to its ORIGINAL at the End, so ECCO does not own it,
  yet the containment writes it). Both attempts fail on the readback, `dump_restore_contained` stays clear, both
  failure statuses and the operator wait say 'export may continue' and none claims 'ECCO's own at 500 W' or 'held at the
  500 W floor'; then the operator lockout. b5-lo (corpus FW-09-b5-lo) is b3's shape for 259 on a site whose 259 ORIGINAL is 600 W, below the 1000 W
  lease value, so the unapplied slot reads above its expected value; both attempts fail on it. b6-ok (corpus
  FW-09-b6-ok) restores pairwise-distinct originals (3000/8000/7000/6000/4500/5000 W) fault-free: exactly one attempt,
  RESTORING then RESTORED OK, marker CLEAR. b6-x257 and b6-x260 (corpus FW-09-b6-x257, FW-09-b6-x260) are b3's shape for
  257 / 260 on that bank with 256's / 259's original equal to the 1000 W lease value, so the unapplied slot reads its
  neighbour's expected value; both attempts still fail on it. Every expectation is derived from the firmware source and
  cites its lines in the check names (the containment plan, the readback compare, `block_failed` and the containment
  claim, the suffix texts, the slot-order `v[]` initialiser). Since the W6-1c correction, five more scenarios cover the
  shapes on which an internal review of W6-1b found containment-claim regressions that survived it (section 9; what
  remains is section 15, item 16). b7-rbnr and b7-rber (corpus FW-09-b7-rbnr, FW-09-b7-rber) are b4-cb's and b4-ct's
  containment (every 244 write acknowledged but not applied; the 6-slot floor block, or the floor write of 258 next to a
  FOREIGN 261, acknowledged but not applied) with a 256-261 readback that gets no response or an error: the failure
  handler sets `dump_restore_block_failed`, so `dump_restore_contained` stays clear; the 244 readback mismatch takes
  the mismatch path, both attempts fail, both failure statuses and the operator wait say 'export may continue' and none
  claims the containment; then the operator lockout. b7-cmnr (corpus FW-09-b7-cmnr) reaches the comms path in
  containment: 244 lands but its verify read errors, the 6-slot floor block is acknowledged but not applied and its
  readback gets no response, so the attempt fails with 'RESTORE WRITE FAILED' and 'export may continue' (backoff, marker
  kept); the suite's retry after the backoff finds 244 ORIGINAL, restores ORIGINAL and completes. b7-ab (corpus
  FW-09-b7-ab) is a verified containment attempt, whose 'held at the 500 W floor' is true when it is published,
  followed by a failed one: the inverter puts 258 back to its ORIGINAL 7000 W after the first attempt and the second
  floor block is acknowledged but not applied; the per-attempt reset keeps `dump_restore_contained` clear and no later
  status claims the containment. b7-af (corpus FW-09-b7-af) has every 256-261 slot FOREIGN (the inverter's own
  4000 W), so the containment plan writes nothing, `dump_restore_contain` stays clear and every status names all six
  NOT CONTAINED with 'export may continue'. A containment-claim truthfulness helper checks every containment claim
  ("ECCO's own at 500 W", 'held at the 500 W floor') of every FW-09 timeline against the bank as it stood when that
  status was published (5 claims in 23 timelines: a 3, c 1, b7-ab 1). Every expectation is derived from the firmware
  source and cites its lines in the check names.
- FW-10 (new): with every Free Power owned register at ORIGINAL, a Dump START is REJECTED citing Free Power with zero writes
  in three Free Power states (RESTORE_REQUIRED, PENDING_CLEAR, the SG-06 UNKNOWN lockout); the same START is admitted once
  the state is resolved.
- FW-11 (new): after a completed Free Power lease, an NVS read error of the used `fp.valid` key at boot gives the SG-06
  UNKNOWN lockout, and a wrong-size or bad-magic record gives the MALFORMED lockout, with the record CLEAR and with a second
  lease ACTIVE; no Free Power write, every core invariant holds. The bad-magic record is a white-box edit (suite only).
- HF-05: in STARTING a non-schedule owner value is kept; a schedule-shaped value is replaced by the pre-schedule value,
  exactly the documented limit SMR1-OWNER-STAGING (PASS; formerly F-HF05-1). In ACTIVE the owner edit is kept.
- HF-09, its PASS parts (the scenario's headline is F-HF09-1, section 8.3): against the real firmware, a raised FPS1 START
  press is contained by `continue_on_error`; 'never reached the dongle' is true on the firmware's RAM gate-pass counter, and
  the retry is one ordinary gated START (one lease). A DGS1 write-enable turn_on that raises once presses nothing and starts
  on attempt 2; one that raises on every call reaches nothing and ends 'FAILED TO START - retries ended' with its alert. An
  SMR1 restore write that raises 0.5 s after the firmware's own restore ends PARTIAL with the field named and one
  notification open (no false RESTORED). A raised closing turn_off is harmless because the firmware disarms the write enable
  at the press. A raised press plus a raised no-answer turn_off ends 'outcome unconfirmed, not retried' with an alert, and
  the closing turn_off ends the switch off. A 40 s API outage (HF-09.7, corpus HF-09-b) ends with the switch off.
- FW-08-A: 296 single-op faulted runs leave a transaction lock held in exactly one case, the documented manual TOU verify read;
  the lock-age monitor reports it and the manual apply refuses while anything is owed.
- RT-01: on the fault-free night one verified large correction lands about 105 s after 01:00 UTC; a lost write callback gives
  the 90 s breaker abort, the 300 s cooldown and then the DST correction, at +345.12 s on the rig's one fixed 60 s read phase.
  The audit swept the read phase and reports a model-only single-fault worst case of about +540 s queued and +552 s lock end
  (about 9 min); no V0.1 directed scenario reproduces that sweep. A lease ending inside a lock window is deferred out of it,
  ends on its UTC epoch and restores verified. The RT-01 checks bound to one read phase are phase-sensitive.
- RT-02: with a stopped inverter clock and an owed restore only large corrections run, each reads back 'Verified OK' with
  `failed_corrections` 0, the error stays within 600 s and the stall signal reports the stopped clock. F-RT02-1, first drafted
  as FINDING-NEW, is classified PASS (documented behaviour) and is not a finding.
- PB-01: 160 quick sequences of 12 actions from published seeds (2000 in extended mode); every violation matches a known
  signature, none is unclassified. The quick run hits partition erase 8 times and a single-key false ABSENT 4 times; the
  extended run restore over a corrupt holder once, phantom admission 11 times, partition erase 42 times and false ABSENT 36
  times (section 2.4). PB-02: 14 quick coupled sequences (150 extended), no unexplained violation. PB-03: London time agrees
  with both oracles at every 15-min instant of 2026-2027.

## 8. Findings by root cause

**No production behaviour was changed.** The lab reproduces, classifies and describes. Every repair scope below is a description
of the smallest change judged safe, intended to add no write path and to weaken no gate unless it says so. None is implemented
or tested. Each needs its own reviewed change, with its own tests; a firmware change also needs its own build and flash
procedure. Where a scope would relax a fail-closed rule, it is marked as a design decision, not a repair.

Severity and priority are those of the catalogue's root-cause group; confidence is the counted findings' `confidence_level`.
The priorities are those of V0.1: the 2026-10-19 independent audit re-triaged five groups (RC-PR41-GHOST and
RC-PR41-STRANDED-OVERRIDE P1 -> P2; RC-FP-NO-SG39-RETRY and RC-COMMIT-FALSE-POSITIVE P2 -> P3; RC-FALSE-ABSENT stays P1),
and RC-SMR1-OWNER-STAGING left the list with its only member F-HF05-1 (a documented limit, section 4). "Mech." is the
`mechanism_verdict` (CONFIRMED = CONFIRMED-IN-SIMULATION, PLAUSIBLE = PLAUSIBLE-UNDER-ASSUMPTIONS), "Reach." the
`device_reachability`, "Change" `needs_product_change` (section 4); every counted member of a group has the same three
values. In brackets: the group's printed duplicates and merged variants, which are not counted.

| Group | Counted (not counted) | Classification | Pri | Conf. | Mech. | Reach. | Change | Reproducer |
|---|---|---|---|---|---|---|---|---|
| RC-FALSE-ABSENT | F-FW04-1, F-FW04-2, F-FW04-3 (F-PB01-3:single-key) | FINDING-KNOWN:PLATFORM-ABSENT | P1 | high | CONFIRMED | PLAUSIBLE | yes | FW-04-a, b, c |
| RC-PR41-GHOST | F-FW01-1 (F-FW05-1, F-HF07-4, F-PB01-1) | FINDING-KNOWN:PR41-GHOST | P2 | high | CONFIRMED | UNKNOWN | yes | FW-01-a |
| RC-PR41-STRANDED-OVERRIDE | F-FW01-2, F-HF07-1 (merged F-HF07-2) | FINDING-NEW | P2 | high | CONFIRMED | UNKNOWN | yes | FW-01-b, HF-07-b |
| RC-N15-STALE-ORIGINAL | F-FW02-2 (F-FW02-1) | FINDING-KNOWN:N15 | P2 | high | CONFIRMED | UNKNOWN | yes | FW-02-b |
| RC-PARTITION-ERASE | F-FW04-4 (F-PB01-3) | FINDING-KNOWN:NVS-PARTITION-ERASE | P2 | high | CONFIRMED | UNKNOWN | yes | FW-04-d |
| RC-STARTUP-RECOVERY-ROLLBACK | F-HF02-1, F-HF03-2 | FINDING-NEW | P2 | high / medium | CONFIRMED | UNVERIFIABLE-OFFLINE | yes | HF-02-a, HF-03-c |
| RC-SAME-DOMAIN-SILENT-LOSS | F-HF04-2 | FINDING-NEW | P2 | high | CONFIRMED | PLAUSIBLE | yes | HF-04-b, c |
| RC-SG25-DST-TOU-GATE | F-HF08-3 (merged F-RT03-1) | FINDING-KNOWN:SG-25 | P2 | high | CONFIRMED | PLAUSIBLE | yes | HF-08-c, d |
| RC-LOCKOUT-CAUSE-TEXT | F-FW01-3 (F-FW03-3, F-HF07-5) | FINDING-NEW | P3 | high | CONFIRMED | UNKNOWN | yes | FW-01-d |
| RC-N17-CROSS-DOMAIN-RESTORE | F-FW05-2 (F-FW03-1, F-PB01-2) | FINDING-KNOWN:N17 | P3 | high | CONFIRMED | UNKNOWN | no | FW-05-e |
| RC-N16-CONTAINMENT-OVERLAY | F-FW03-2 | FINDING-KNOWN:N16 | P3 | high | CONFIRMED | UNKNOWN | yes | FW-03-b |
| RC-COMMIT-FALSE-POSITIVE | F-FW06-3, F-FW06-2 (F-PB01-4) | FINDING-NEW | P3 | low | CONFIRMED | UNKNOWN | yes | FW-06-c, FW-06-b |
| RC-FP-START-COMMIT-CASCADE | F-FW06-1 (F-HF07-3) | FINDING-NEW | P3 | high | CONFIRMED | UNKNOWN | yes | FW-06-a |
| RC-FP-NO-SG39-RETRY | F-FW07-1 | FINDING-NEW | P3 | high | CONFIRMED | PLAUSIBLE | yes | FW-07-f |
| RC-END-REASON-MISATTRIBUTION | F-FW07-2 | FINDING-NEW | P3 | high | CONFIRMED | PLAUSIBLE | yes | FW-07-g |
| RC-FCP2-R1 | F-FW07-3 | FINDING-KNOWN:FCP2-R1 | P3 | high | CONFIRMED | UNVERIFIABLE-OFFLINE | no | FW-07-d |
| RC-CONFIG-READ-FAIL-CLOSED | F-FW07-4 | FINDING-NEW | P3 | low | CONFIRMED | PLAUSIBLE | yes | FW-07-h |
| RC-FCP2-F6-RESTART-LOOP | F-FW08-1 | FINDING-KNOWN:FCP2-F6 | P3 | low | CONFIRMED | UNKNOWN | yes | FW-08-f |
| RC-WINDOW-END-OVERRUN | F-HF01-1 | FINDING-NEW | P3 | medium | CONFIRMED | PLAUSIBLE | no | HF-01-b, c |
| RC-SMR1-UNCLEAN-SHUTDOWN | F-HF02-2 | FINDING-KNOWN:SMR1-UNCLEAN-SHUTDOWN | P3 | high | CONFIRMED | UNVERIFIABLE-OFFLINE | no | HF-02-c |
| RC-RESTART-ABANDONS-RUN | F-HF02-3 | FINDING-NEW | P3 | high | CONFIRMED | PLAUSIBLE | yes | HF-02-d |
| RC-PRESS-PROOF-COUNTER-RESET | F-HF03-1 | FINDING-NEW | P3 | medium | PLAUSIBLE | PLAUSIBLE | yes | HF-03-a |
| RC-TAIL-PERSISTENT-REFUSAL | F-HF04-1 | FINDING-NEW | P3 | high | CONFIRMED | PLAUSIBLE | yes | HF-04-a |
| RC-DGS1-WALK-READS-FP-OVERRIDE | F-HF04-3 | FINDING-NEW | P3 | high | CONFIRMED | PLAUSIBLE | yes | HF-04-d |
| RC-SMR1-OWNER-RESTORING | F-HF05-2 | FINDING-KNOWN:SMR1-OWNER-RESTORING | P3 | medium | CONFIRMED | PLAUSIBLE | no | HF-05-b |
| RC-HA-MODEL-FAILED-START | F-HF06-1 | FINDING-NEW | P3 | high | CONFIRMED | N/A | no | HF-06-a, b |
| RC-DGS1-STALE-ADVICE | F-HF06-2 | FINDING-NEW | P3 | high | CONFIRMED | PLAUSIBLE | yes | HF-06-a |
| RC-FPS1-FAILED-REASON-LOST | F-HF06-3 | FINDING-NEW | P3 | high | CONFIRMED | PLAUSIBLE | yes | HF-06-b |
| RC-PACKAGE-DST-ARM-GUARD | F-HF08-1, F-HF08-2 | FINDING-NEW | P3 | medium | PLAUSIBLE | PLAUSIBLE | yes | HF-08-a, b |
| RC-FROZEN-CT-RANGE-NOT-RESEEDED | F-FW07-5 | FINDING-NEW | P3 | medium | CONFIRMED | PLAUSIBLE | yes | FW-07-i3 |
| RC-WRITE-ENABLE-LEFT-ON | F-HF09-1 | FINDING-NEW | P3 | medium | CONFIRMED | PLAUSIBLE | yes | HF-09-a |

Totals: 31 groups (1 P1, 7 P2, 23 P3; 20 FINDING-NEW, 11 FINDING-KNOWN) and 37 counted findings (24 FINDING-NEW, 13
FINDING-KNOWN; 3 in the P1 group, 9 in P2 groups, 25 in P3 groups), plus 14 not counted (12 duplicates, 2 merged). All
reproducer files are under `registry/tests/assurance_lab/corpus/`. Grades are VERIFIED except F-HF03-1 (INFERRED: an
early-reset proxy). 6 of the 37 need no product change; none has VERIFIED device reachability (section 4).

**Notes.** The catalogue keeps tagged notes per group (`root_causes[].notes`; `run_lab.py` prints the tags). `[priority]`,
`[design-review]`, `[design-decision]`, `[documentation-test-bound]` and `[coupling]` notes explain a group's V0.1 standing.
`[audit-reported, uncounted]` notes record consequences the 2026-10-19 independent audit reported; they are not counted and
not reproduced by a V0.1 directed scenario unless the note says where, and since the V0.1 review every such note states its
reproduction status in its own text (where it is reproduced, or that it is not). `[v0.1-observation, uncounted, untriaged]` notes
record what a V0.1 scratch probe found; they are neither counted nor triaged. The notes below summarise them.

Below, for each group: what reproduces, the source anchors (path and an exact snippet, each occurring once unless noted), the
smallest safe repair scope and the notes. Paths: `FW` is `firmware/ecco_clock_dongle_stage3_4_free_power.yaml`, `S4` is
`docs/architecture/fallback/design/S4_domains_decisions_final.md`, `FPS1`, `DGS1` and `SMR1` are the three packages in
`home-assistant/packages/`. Firmware line numbers (`FW:<n>`) are those the catalogue notes cite.

### 8.1 P1 group

**RC-FALSE-ABSENT.** A held lease marker lost at boot (single key, read as ABSENT = CLEAR) during an ACTIVE lease. Dump: 244 = 0
and the lease ceiling stay applied and unsupervised (no export trip, no Stop SOC supervision, no SG-02 path), with no obligation,
lockout or alert. Free Power: the grid-charge override stays applied. A later START snapshots the residue as ORIGINAL and its
restore reports 'verified' (F-FW04-3).

- Anchors: `FW` `id(dump_marker_state) = state;` (Dump marker block) and `id(free_power_marker_state) = state;`; `FW`
  `export containment not armed - do NOT reboot: a reboot may make the record read as absent`.
- Repair scope: `on_boot` only. When a lease marker loads ABSENT while the same domain's current data record loads with
  `active_persisted == 1`, enter the existing READ_ERROR-style UNKNOWN lockout (no commit, no Modbus at boot). It makes the
  loss alarmed, not contained, and cannot see a partition erase or a false-positive commit on a used device. The audit's
  refinement of the key is in the note below.
- Priority (P1, unchanged): mechanism CONFIRMED-IN-SIMULATION; device reachability PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN.
  The remaining route is ESP-IDF erasure of a corrupt entry (REPORTED by the S4 notes and the firmware's own 'do NOT
  reboot' text, not verified offline); the second reboot needs no owner action (ESPHome's 15-min API or Wi-Fi reboot, safe
  mode, a power cut). Ruled out: a power cut between the ordered commits, key derivation, a tag rename and a 24-bit
  item-hash collision.
- Audit-reported, uncounted: in the READ_ERROR (UNKNOWN) state the safety census labels the domain 'a Dump to Grid restore
  is owed' (`FW:20661-20662`) and the gated Restart offers the override (`FW:20693-20701`), against the firmware's own 'do
  NOT reboot' (`FW:913`); the register-244 domain has the same ABSENT-to-CLEAR mapping (`FW:982-985`), which no V0.1
  scenario covers; the repair keyed on `active_persisted == 1` alone also locks an idle domain whose CLEAR marker is lost
  after a clean end, and the refined Dump check is `active_persisted == 1 and restore_requested == 0` (Free Power needs a
  data-record closure commit; a page-level loss defeats any data-record witness); after the false ABSENT, HA can show a
  schedule-started lease as COMPLETED.

### 8.2 P2 groups

**RC-PR41-GHOST.** A Phase-B marker commit false negative leaves a durable RESTORE_REQUIRED marker while the RAM mirror stays
clear. The other domain's START gate and HA's snapshot sensors read the RAM mirror, so the other domain's START is admitted in the
same runtime and writes the shared 256-261. Nothing is written in an unsafe direction until a reboot inside the admitted lease
(RC-PR41-STRANDED-OVERRIDE).

- Anchors: `S4` `A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear) is invisible`; `FW`
  `// Free Power owns 256-261 during its own lease and reads`.
- Repair scope: when a Phase-B marker commit returns false after the data record committed, fill the RAM mirror exactly as the
  success branch does (snapshot valid, marker RESTORE_REQUIRED, end epoch and targets, restore requested), so the domain's own
  watchdog runs the existing verified no-op restore and commits CLEAR. Intended to add no write path and only to tighten gates
  (not implemented or tested); PR41 / S4 stay as the boot backstop. The audit widens it: all three Phase-B false-return
  branches (Free Power `FW:9233-9240`, Dump `FW:18555-18558`, register 244 `FW:17204-17211`), including the success branch's
  RAM pacing reset (`FW:9184-9187`), with the stale comments corrected and the data-to-marker commit adjacency pinned
  (a repair-scope statement, not reproduced: no V0.1 scenario runs a repaired firmware).
- Priority P2 (V0: P1; P3 by likelihood): mechanism CONFIRMED-IN-SIMULATION; device reachability UNKNOWN, likely very low
  (it is the trigger of RC-PR41-STRANDED-OVERRIDE and depends on the ESP-IDF fault cell). The repair is cheap hardening.
- Audit-reported, uncounted: three register-244 legs (a reg244 ghost admits a genuine Dump lease and a reboot inside it
  gives the S4 dual lockout with 256-261 stuck; a Dump ghost followed by the owner's reg244 Apply gives the S4 dual lockout
  on any later reboot; a lone reg244 phantom never self-heals and blocks Free Power, Dump and manual applies after any
  reboot); FW-03 boots a reg244 ghost together with a Dump ghost, but the three legs as stated are not reproduced.
- V0.1 observation, uncounted, untriaged: PB-01 extended generator seed 366 under the scratch ESPHome-like phase patch gives
  an UNCLASSIFIED `INV-NO-SILENT-OVERRIDE` (a ghost on a used Free Power marker, a foreign write of 126 to 268, a second Free
  Power START that snapshots 126 while the lab's ORIGINAL stays 20): either the foreign-register oracle limit (HL-2: a
  foreign change on a register held only by a ghost's durable marker is snapshotted by the ghost-admitted START) or a real
  ghost consequence (the true ORIGINAL 20 is overwritten in the data record); not seen on the lab's own phase; not
  reproduced by a V0.1 directed scenario or corpus document.

**RC-PR41-STRANDED-OVERRIDE.** A Dump phantom, a genuine ACTIVE Free Power lease and a reboot inside it: the PR41 dual lockout
locks both domains, and the Free Power override (grid charge, all six slots) stays applied past its end epoch with no in-firmware
exit and no time bound; every operator surface refuses. In HA, FPS1 / DGS1 keep showing ACTIVE and no persistent notification
names the lockout for about 24 h. F-HF07-1 is that HA-side gap in two mirror instances: FPS1 (mirror b) and DGS1 (mirror a,
formerly the separately counted F-HF07-2, merged in V0.1).

- Anchors: `FW` `if (id(free_power_recovery_metadata_corrupt)) return false;`; `S4`
  `"Permanent" means that no assignment to false exists anywhere in the firmware.`; `FPS1`
  `# ACTIVE / STARTING / ARMED / FAILED / COMPLETED / IDLE. FAILED and COMPLETED describe the`.
- Repair scope: removing the trigger is RC-PR41-GHOST's repair. HA side, read-only: FPS1 / DGS1 status templates map a structured
  lockout signal (the firmware Recovery State, or Active still on past the window end plus a margin) to LOCKED instead of ACTIVE,
  plus one notification that says not to reboot the dongle. A bounded automatic firmware exit for an expired lease would open a
  write path under a lockout: a design decision, not a repair.
- Priority P2 (V0: P1): mechanism CONFIRMED-IN-SIMULATION; device reachability UNKNOWN, likely very low (a Dump marker
  own-key landed-then-error write, ESP-IDF returning the new copy at the next boot, a Free Power START in the same runtime
  and a reboot inside that lease). The consequence is severe, the trigger narrow and unverified.
- Design review: the PR41 premise is stale since fcp2. PR41 justifies the dual lockout with the Dump restore being blind
  (`FW:1100-1104`), but since the fcp2 ownership pre-read the Dump restore fresh-reads 244-261 and never writes ORIGINAL or
  FOREIGN slots (`FW:19796-19808`). The exit-less strand is a design-review item, neither "by design" nor a defect yet;
  review it with SG-02 for Allow-Export sites.
- Audit-reported, uncounted: on Allow-Export sites (ORIGINAL 244 = 0) SG-02 writes 244 := 2 about 13 s after the boot and
  keeps it, and the containment text replaces the only status text that names the real cause (partly pinned by corpus
  FW-01-c); the Dump mirror strands a 256-261 battery-ceiling residue (pinned by FW-01-a and HF-07-a); erasing NVS while
  locked clears the lockout but leaves the override silent, and the next Free Power START adopts it as ORIGINAL, so a
  recovery must restore the inverter first.
- Coupling: decide the HA alert for "a function still active past its own lease end" together with
  RC-SAME-DOMAIN-SILENT-LOSS.

**RC-N15-STALE-ORIGINAL.** A ghost marker plus a later owner write. Dump: an owner slot power equal to a value the Dump evidence
counts as ECCO's (the phantom's feed-forward ceiling or the 500 W floor) is rewritten to the stale ORIGINAL at the next boot and
reported RESTORED OK. Free Power: the classifier fails closed (OPERATOR DECISION REQUIRED, zero writes).

- Anchors: `S4` `| N15 | P3 does not exist`; `FW`
  `bool ecco_value = live == id(dump_target_power) || live == id(dump_evidence_pending_ceiling) || live == floor_v;`.
- Repair scope: RC-PR41-GHOST's repair (no phantom outlives its runtime). The classifier must not change. Optional documentation:
  an external change equal to ECCO's ceiling, pending value or 500 W floor is taken as ECCO's.

**RC-PARTITION-ERASE.** A whole-partition NVS erase at boot during a lease loses every marker and record. Dump: 244 = 0 stays and
a later Free Power START captures the Dump residue as ORIGINAL. Free Power: the override stays applied. The erase path is
VERIFIED from the ESPHome 2026.8.2 source (`preferences.cpp:131-148`: `open()` erases and re-initialises the partition when
`nvs_open` fails); the trigger, an `nvs_open` failure at a boot inside an ACTIVE lease, is INFERRED and its rate UNKNOWN.

- Anchors: `S4` `makes every marker ABSENT.`
- Repair scope: no firmware-local cross-check closes it (the records are erased too). Smallest first step, diagnostics only: an
  HA-side alert when a lease seen before a dongle reboot vanishes without a restore completion. A durable lease-marker witness is a
  new NVS commit path and a design decision.

**RC-STARTUP-RECOVERY-ROLLBACK.** FPS1 / DGS1 startup recovery decides from package helpers alone. A crash rollback that restores
`armed` ON after the run already started makes the recovery start an unrequested second session after the owner's End & Restore,
a new lease after a firmware early end, or a false 'MISSED' alert after a natural end (F-HF02-1). A whole-site power cut during a
scheduled Dump makes DGS1 start a new lease whose alert its own success dismisses (F-HF03-2). Every firmware START gate, the
window end and Stop SOC still apply.

- Anchors: `FPS1` `Home Assistant restarted during the scheduled Free Power window. ECCO is starting it now`; `SMR1`
  `# Home Assistant saves restored states every 15 minutes`; `FW`
  `id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");`.
- Repair scope: FPS1 / DGS1 startup recovery only (it can only hold back a START): require evidence that a crash rollback cannot
  undo that this window's run has not started (for Dump, the dongle's Last End Reason), else record and alert 'interrupted, not
  restarted' with a notification the run's own success does not dismiss.
- Design decision: P2 as a design-decision item (P3 on harm alone). Whether a startup recovery may re-create a lease after an
  unclean Home Assistant stop or a site power cut is a policy question. Reachability rests on HA's restore-state cadence,
  UNVERIFIABLE-OFFLINE.
- Phase: F-HF03-2 is phase-sensitive. Which whole-site cut grid points start a new Dump lease depends on whether Home
  Assistant's post-restart read of the Dump status comes before the firmware's boot restore; under the phase patch the
  section is refused at its first point in 12 of 17 configurations, and where it ran the 5 s / 5 s point took the
  no-new-lease branch in 4 of 5, while the 60 s and 120 s / 5 s points reproduced F-HF03-2 (section 2.5).

**RC-SAME-DOMAIN-SILENT-LOSS.** A schedule whose start falls at the end of (or inside) the same function's previous lease records
'BLOCKED - ... already active', raises no failure alert, dismisses the readiness alert, ends IDLE and loses the whole window.

- Anchors: `FPS1` `value: "BLOCKED - Free Power already active"`; `DGS1` `value: "BLOCKED - Dump to Grid already active"`.
- Repair scope: package only. Turn the pre-check into a bounded wait inside the existing stage-nothing / press-nothing branch; the
  success test must not count a lease that was already active when the run began. Smaller, diagnostics only: drop the 'already
  active' exemption from the alert.
- Coupling: it comes from the documented rule "already active = started", not an alert oversight; decide it together with
  RC-PR41-STRANDED-OVERRIDE. The F-HF04-2 pins are phase-sensitive (they failed in every configuration of the phase patch).

**RC-SG25-DST-TOU-GATE.** The firmware Dump START TOU gate and its DGS1 arm-time mirror walk local minutes from the start's wall
time. On both clock-change nights they admit a lease that really overlaps a synthetic charge slot for 30 min, and on the fall
night they spuriously refuse a window outside the lease's real span (fail closed). RT-03 reproduces the same gate with the RTC
correction lock mid-lease (F-RT03-1, merged).

- Anchors: `FW` `int m0 = now.hour * 60 + now.minute;`; `docs/dev/dump-to-grid-safety-fcp2.md`
  `**SG-25, the DST-aware TOU charge-slot gate.**`.
- Repair scope: the firmware START gate only, as SG-25 already documents (walk the window in UTC, check both offsets). No RTC-side
  change.
- Audit-reported, uncounted: the SG-25 operational restriction (no Dump between 00:00 and 03:00 local on a change night) is
  procedural only; no package or firmware guard exists. The RT-03 compound pin is phase-sensitive.

### 8.3 P3 groups

**RC-LOCKOUT-CAUSE-TEXT.** Under the PR41 (or S4) dual lockout the partner domain's status names the wrong cause ('snapshot data
cannot be trusted') although its record loaded; the dual-obligation text in the Dump status lasts only until a Dump START /
Accept / End press; every HA-reachable refusal misstates the cause. The lockout itself is reported correctly.

- Anchors: `FW` `RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261)`; `FW`
  `id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data`.
- Repair scope: status text only, no control change: a RAM-only lockout cause assigned next to each corrupt-flag set site and read
  by the boot status block and the refusal texts, for both dual-lockout sites. A publish inside the PR41 branch alone does not work
  (the status block later in the same lambda overwrites it).

**RC-N17-CROSS-DOMAIN-RESTORE.** With the other domain corrupt / UNKNOWN at boot (PR41 skipped), a trusted restore writes 256-261
over that domain's unresolved obligation. The value written is the restoring domain's own verified ORIGINAL. No product change
is needed (an accepted residual).

- Anchors: `S4` `| **N17** | P1 restores (FP and Dump) carry no cross-domain terms.`
- Repair scope: none needed. A bare '!other_corrupt' term is not safe: in-memory mutants show it strands the Free Power override
  or leaves 244 = 0 uncontained.
- Phase: corpus FW-05-e, F-FW05-2's FINDING document, fails an expectation under the phase patch (6 of 11 configurations)
  while the suite pins hold; F-FW05-2 is flagged phase-sensitive for that reason.

**RC-N16-CONTAINMENT-OVERLAY.** With the Free Power lease context 244 = 0, the watchdog that runs first after the boot
decides: Dump first, SG-02 writes 244 := 2 and the Free Power restore is then held by its register-244 context gate behind
OPERATOR DECISION REQUIRED (Force resolves it, Accept refuses). Restrictive direction, alarmed. On the lab grid the two
watchdogs tie and the explicit `wd_order` picks the order; under the ESPHome-like phase patch their random offsets pick it,
and the Dump-first context hold reproduces whenever the Dump watchdog's offset is the smaller (10 of the 17 patched
configurations). The F-FW03-2 pin is composite (both explicit orders in one run: the Dump-first context hold with its
operator exits and the Free Power-first N17 contrast), so it fails under the patch by construction; it is tagged
phase-sensitive.

- Anchors: `S4` `Known residual: P0 does not check other domains' obligations (N16).`; `FW`
  `snprintf(msg, sizeof(msg), "RESTORE BLOCKED - register 244 context changed since this lease started (%s)"`.
- Repair scope: RC-PR41-GHOST's repair makes the construction unreachable. Optional diagnostics only: the context-hold text names
  ECCO's own SG-02 containment as the 244 writer. Deferring SG-02 behind a due Free Power restore is not safe (unbounded).

**RC-COMMIT-FALSE-POSITIVE.** A Phase-B marker commit that reports success without storing. The lease runs on RAM only; a reboot
during it leaves the override applied with the previous lease's stale CLEAR marker (a used device; the never-used ABSENT form is
no longer injected since V0.1). Dump: unsupervised 244 = 0 and ceiling. Free Power: the grid-charge override.

- Anchors: `S4` `The commit result itself can be a false negative or a false positive`; `firmware/include/ecco_durable_snapshot.h`
  `Returns true only if BOTH the queue step and the flash sync succeeded`.
- Repair scope: only if such a trigger is confirmed. In the Phase-B guards, read the marker back with a read that cannot be served
  from ESPHome's pending-save queue, before the RAM mirror is set and before any override write; require RESTORE_REQUIRED, else
  take the existing commit-failure path ('START FAILED ... nothing written').
- Priority P3 (V0: P2), pending the ESP-IDF host NVS test: the trigger is UNKNOWN and is not labelled a model artefact. No
  route exists at the ESPHome layer (`sync()` returns success only when no pending write failed); an ESP-IDF route (an
  INVALID page after one reported flash-op failure) was described by the V0 independent audit (medium confidence, not
  executed). Since the V0.1 review the finding texts of F-FW06-2, F-FW06-3 and F-PB01-4 say the same; they no longer call
  the trigger "MODEL-dependent" or "a lab trigger with no identified physical route".
- V0.1 observation, uncounted, untriaged: the register-244 data-record false positive of section 2.4 (a later Restore
  writes 2, not the owner's 1). No invariant fires because the lab takes the owner-initiated register-244 Restore's write
  as the owner's new ORIGINAL (`_lab_fw.OWNER_DOMAINS` includes `r244`), so the stale 2 becomes the baseline; by the same
  rule a stale-ORIGINAL restore through that domain is invisible to INV-NO-SILENT-OVERRIDE. Free Power and Dump are not
  affected (their START re-commits the data record after activation). No directed scenario or corpus document pins it.

**RC-FP-START-COMMIT-CASCADE.** A Free Power START durable-commit failure publishes 'START FAILED', is overwritten at once by
'ACTIVATION WRITE FAILED - restoring saved snapshot' (no activation write was attempted), counts two failures and ends on
'END IGNORED'; FPS1 copies that text.

- Anchors: `FW` `START FAILED - could not durably commit the recovery snapshot; nothing written`; `FW`
  `ACTIVATION WRITE FAILED - restoring saved snapshot`.
- Repair scope: `start_free_power_override` only: run the activation branch only after a successful commit phase, and in the
  commit-failure branch run the restore only when the snapshot is valid. No write, gate or durable change.
- Device reachability UNKNOWN by the rule for every injected NVS primitive (section 4), although the corpus trigger is an
  honest `not_landed` commit failure. Phase: corpus FW-06-a's `writes` expectation lists the used-key prelude's writes with
  their sequence numbers, so it fails under the phase patch (11 of 11) while the suite pins hold; F-FW06-1 is flagged
  phase-sensitive for that reason.

**RC-FP-NO-SG39-RETRY.** After a long link outage during a Free Power restore, the restore waits out the rest of the current comms
backoff window (about 238 s in the scenario) once the link is back; the Dump analogue restores within one watchdog tick through
SG-39. The audit measured the Free Power restore 3-288 s after the link returns, against 1-13 s for Dump.

- Anchors: `FW` `if (next_ms != 0 && (int32_t)(now_ms - next_ms) < 0) {`; `docs/dev/dump-to-grid-safety-fcp2.md`
  `**The restore backoff (SG-39).**`.
- Repair scope: Free Power restore pacing only, mirroring the Dump SG-39 clause: a RAM-only link-down stamp, one extra clause in
  the backoff gate after the operator lockout check, the stamp cleared on a verified restore, at START and on End. No change to the
  backoff table, the classifier, the lockout or the writes.
- Priority P3 (V0: P2): a bounded, cost-only parity gap.

**RC-END-REASON-MISATTRIBUTION.** A reboot between a Dump lease end and its verified restore publishes 'ESP RESTARTED DURING
LEASE' for the already-ended lease (also after every stuck-lock escalation restart; pinned in FW-07-g, FW-08-c, FW-08-d).

- Anchors: `FW` `// (active_persisted == 0), this is already true anyway.`
- Repair scope: diagnostics only, the Dump boot block: publish that text only when the loaded record shows the lease was running;
  otherwise a distinct text. No write path, gate or restore change.

**RC-FCP2-R1.** After a restart with the inverter refusing every 244 write, export stays enabled; ECCO's own slots are held at the
500 W floor and the owed Stop SOC (bound to the obligation's end epoch) governs the supervision. Documented accepted residual; no
product change is needed.

- Anchors: `docs/dev/dump-to-grid-safety-fcp2.md` `| R1 SG-04: block never restored when 244 fails; no supervision |`.
- Repair scope: none in firmware; 244 must be cleared at the inverter, after which the next attempt restores 256-261.

**RC-CONFIG-READ-FAIL-CLOSED.** One failed configuration block read during an ACTIVE Dump lease ends it at the next watchdog tick
as 'TELEMETRY LOST - failing closed'. It is an explicit fail-closed term whose intent the public documents do not state
(confidence that it is unintended: low).

- Anchors: `FW` `return !soc_plausible || !soc_fresh || !id(configuration_online).state;`
- Repair scope: (a) diagnostics only: give the configuration-offline case its own end reason; (b) narrowing the term relaxes an
  explicit fail-closed end: a design decision.

**RC-FCP2-F6-RESTART-LOOP.** A lock leak that recurs before the first watchdog tick of every boot gives a stuck-lock restart about
every 203 s with no restore attempt; 244 stays at Allow Export and no status is CRITICAL. The trigger is hypothetical (no such code
path is known). No core checker sees a violation (HL-5).

- Anchors: `docs/dev/dump-to-grid-safety-fcp2.md`
  `If a code path leaks the lock again after every boot, the device restarts at most once per bound`.
- Repair scope: a design decision under the documented FCP2-F6 item: a stuck-restart counter that survives a software restart, a
  CRITICAL status, corrected wording. Lock rules and restore path unchanged.

**RC-WINDOW-END-OVERRUN.** Every scheduled start gated within about 20 s of its time ends after the authorised window end. The
packages state that nothing starts or runs after the window end (FPS1 / DGS1 field descriptions) and that a late start ends
within about a minute of it. The "+30 s" bound is not a package claim: it is the HA test suites' model-only check
(`home-assistant/tests/test_ecco_free_power_schedule_reliability.py`, `test_ecco_dump_to_grid_schedule_reliability.py`,
asserted against hand models whose session ends at start + duration). With a busy end slot, or start retries plus a busy end
slot, the override outlives that bound. On the recorded-busy-window bus model (`BUSY_10S` / `BUSY_60S` of
`home-assistant/tests/_ha_script_sim.py`) the lab's simulated overruns are: Dump 35.93 s (lease-end edge) / 34.17 s (override
end); Free Power 52.4 s / 48.32 s. These are phase-dependent examples on one bus model, not field measurements (idle-bus maxima
about 15.9 s Dump / 19.4 s Free Power; the exact pins fail under the phase patch); the magnitude on a device is UNKNOWN. Cost
negligible; the lease stays supervised until its verified restore.

- Anchors: `FPS1` `description: "End of the authorised window (epoch seconds); nothing starts or runs after it"`; `FW`
  `return (uint32_t) now.timestamp >= id(free_power_end_epoch);`.
- Repair scope: documentation and tests only: correct the window-end description in both packages, state the firmware end-latency
  budget, and label the HA suites' +30 s check as model-only. A documentation / test-bound item; no product change is needed.

**RC-SMR1-UNCLEAN-SHUTDOWN.** A crash during STARTING loses the SMR1 obligation (documented); the recovery's re-stage then saves a
schedule-staged duration as the owner's and SMR1 reports a false RESTORED (understated in the limit text).

- Anchors: `docs/dev/schedule-manual-restore.md`
  `- **Unclean shutdown.** Home Assistant saves restored helper states every 15`.
- Repair scope: documentation first (extend the 'Unclean shutdown' limit text). Optional, in the SMR1 track: record 'LOST'
  with a notification instead of saving.

**RC-RESTART-ABANDONS-RUN.** A graceful HA restart while STARTING, after the owner moved the start helper without disarming,
abandons today's run silently ('ARMED AFTER RESTART', no alert, no lease). No write direction is affected.

- Anchors: `FPS1` `ARMED AFTER RESTART - waiting for`.
- Repair scope: FPS1 / DGS1 startup recovery, the not-yet-started branch only: when the last result starts with STARTING, record
  'INTERRUPTED' and create the schedule's notification. No new write path.

**RC-PRESS-PROOF-COUNTER-RESET.** A dongle reset right after the START gate pass, before the gate's publishes reach HA: FPS1 /
DGS1 conclude 'never reached the dongle (no start counted)' from the RAM-only attempt counters and press START again. The cut START
wrote nothing, so the retry is harmless; the proof text is false. Grade INFERRED (a proxy cut at START's first Modbus read);
mechanism PLAUSIBLE-UNDER-ASSUMPTIONS.

- Anchors: `FPS1` `# No answer to this press (the switch still reads ON). Either the press never reached the`; `FW`
  `id(free_power_start_attempts)++;`.
- Repair scope: FPS1 / DGS1 no-answer branch only, read-only: capture a per-boot identity of the dongle with the counter and retry
  only when it is unchanged, else report 'outcome unconfirmed, not retried'.

**RC-TAIL-PERSISTENT-REFUSAL.** A Free Power schedule armed after the Dump schedule disarmed, for the Dump window end, fails at
once with an alert although the Dump obligation clears 0-16 s after the window end, inside FPS1's own 10-minute retry budget
(mirrored for Dump after Free Power). One lease at a time always holds. The F-HF04-1 pin is phase-sensitive.

- Anchors: `FPS1` `{{ f_start < d_end + 120 and d_start < f_end + 120 }}`; `FW`
  `else if (id(dump_active_persisted) || id(dump_snapshot_valid)) id(free_power_status).publish_state("REJECTED - Dump to Grid override/recovery owns inverter settings");`.
- Repair scope: package only, the firmware gate unchanged: extend FPS1's arm-time overlap check to a running Dump lease, or add the
  Dump Active / Snapshot Valid sensors to the bounded not-ready wait.

**RC-DGS1-WALK-READS-FP-OVERRIDE.** A Dump schedule armed while a Free Power lease runs is refused as overlapping 'a TOU slot with a
charge source set': the slots are the Free Power override's own temporary grid-charge settings. Fails safe; names the wrong cause.

- Anchors: `DGS1` `REJECTED - window overlaps a TOU slot with a charge source set`; `FW`
  `id(ecco_tou1_charge).publish_state(charge_source(values[33]));`.
- Repair scope: DGS1 arm validation only, refusal only: before the TOU walk, refuse with an explicit 'Free Power is active' text
  while the Free Power Active, Snapshot Valid or Operation In Progress sensor is on.

**RC-SMR1-OWNER-RESTORING.** An owner change landing within about one command + publish latency of SMR1's restore write is
overwritten and reported RESTORED with no notification. The limit is documented; the documented consequence (PARTIAL / FAILED,
notified) is wrong. The race window rests on model latencies.

- Anchors: `docs/dev/schedule-manual-restore.md` `- **Owner change during the restore.**`
- Repair scope: documentation first (correct the limit text). A true fix needs a single writer or a compare-and-set on the dongle:
  a firmware change, out of scope here.
- Phase: on corpus HF-05-b's fixed timeline the recorded deviation does not occur under the phase patch (the duration
  number ends at 25.0 instead of the recorded 40.0 and INV-HF-NO-FALSE-SUCCESS does not fire, in 11 of 11 configurations),
  while the suite pins hold; F-HF05-2 is flagged phase-sensitive for that reason.

**RC-HA-MODEL-FAILED-START.** The HA dongle models keep a failed START's snapshot pending until End & Restore, and SMR1 suite [3]
asserts it as the nominal case. With the real firmware source in the lab, a single failed START restores by itself (Dump at
its next watchdog tick, Free Power inline) and SMR1 then restores the owner's values. Test-model fidelity, not a product defect;
device reachability NOT-APPLICABLE. Section 5.1 lists the other places where the HA dongle models differ from the firmware (not
counted as findings).

- Anchors: `FW` `snapshot retained - press End & Restore Now`.
- Repair scope: tests only: an opt-in auto-restore in the HA dongle models and the realistic chain in the SMR1 suite; keep the
  retained-snapshot checks relabelled 'automatic restore also failed'.

**RC-DGS1-STALE-ADVICE.** DGS1's 'did NOT start' alert repeats 'snapshot retained - press End & Restore Now', but the firmware's
watchdog restores at its next tick; the stale advice persists until a later start or arm, and an End press finds nothing.

- Anchors: `FW` `snapshot retained - press End & Restore Now`.
- Repair scope: text only. Smallest: DGS1's recorded-result template adds that the dongle restores automatically. Root cause: the
  firmware string (a firmware change, together with RC-HA-MODEL-FAILED-START's test update).

**RC-FPS1-FAILED-REASON-LOST.** A scheduled Free Power whose activation write or verify fails is recorded and alerted as 'FAILED TO
START - RESTORED OK - original inverter settings verified ...': the failure reason is lost from FPS1's result and alert.

- Anchors: `FW` `ACTIVATION VERIFY FAILED - restoring saved snapshot`; `FPS1`
  `(start transaction began on attempt {{ repeat.index }}; not retried)`.
- Repair scope: FPS1 text only, based on firmware truth (snapshot valid or not), keeping the 'FAILED' prefix the loop and alert
  test. Recovering the cause needs a firmware text sensor.

**RC-PACKAGE-DST-ARM-GUARD.** FPS1 arm validation has no DST guard. On the fall night an 01:xx start always means the BST copy
(fold=0 ASSUMPTION); an arm meant for the GMT copy is refused as a past start (F-HF08-1). The nonexistent spring 01:30 is ARMED with
no warning and runs one hour from the typed wall time (F-HF08-2). Mechanism PLAUSIBLE-UNDER-ASSUMPTIONS: Home Assistant's fold=0
resolution is not verifiable offline.

- Anchors: `FPS1` `at: input_datetime.ecco_free_power_schedule_start`; `FPS1`
  `value_template: "{{ start_ts <= as_timestamp(now()) }}"`.
- Repair scope: FPS1 arm validation only: refuse an ambiguous or nonexistent local start with a DST-specific message (a round trip
  of the resolved instant).
- Audit-reported, uncounted: editing an already-armed start into the repeated hour is not re-validated and can start Free Power
  at once (reproduced by the audit in the coupled simulation, not by a V0.1 directed scenario); the repair scope extends to
  edits while armed.

**RC-FROZEN-CT-RANGE-NOT-RESEEDED.** The battery range of the fast frozen-CT criterion (`dump_ct_same_bmin` /
`dump_ct_same_bmax`) is not re-seeded at START or outside a lease. A grid CT that already repeats when a Dump START is pressed,
with a steady battery (moving 2 W), therefore ends the lease 'GRID CT FROZEN' after 7 reads instead of the documented 30-read
slow criterion, and the end text names a battery movement no reading during the repeats showed: 1051 W from the range's boot
value, or about 1000 W carried over from a previous lease. A control (a CT that changes after the 30 s grace and then repeats)
ends after 30 reads and names the real 2 W. Fail closed: no write or gate is affected. Found incidentally while FW-07-I was
built (no independent check, section 4); reproduced on the real firmware in both forms; reachability PLAUSIBLE-UNDER-ASSUMPTIONS
(a CT that stopped updating before the START, with a steady battery), deterministic once it occurs.

- Anchors: `FW` `// fcp2 (SG-15 / SG-43): fresh frozen-telemetry evidence.`; `docs/dev/dump-to-grid-safety-fcp2.md`
  ``| Grid CT, slow | it repeats exactly for `ecco_dump_frozen_ct_long_samples` reads, whatever the battery did.``
- Repair scope: the frozen-CT evidence only: seed `dump_ct_same_bmin` / `dump_ct_same_bmax` empty (as the CT hook's own re-seed
  does) together with `dump_ct_same_count` in the START block's fresh frozen-telemetry evidence; no threshold, write path or gate
  change. It is a design decision, because it restores the documented slow criterion for a CT already frozen at START with a
  steady battery (a fail-closed end then comes after about 5 minutes instead of about 1). A diagnostics-only alternative keeps
  the decision and reports only the battery movement seen during the repeats. An in-memory mutant with the empty seed restores
  the slow criterion, and FW-07-i3 fails against it.
- Classification: the CT that already repeats at the START is synthetic telemetry the scenario builds, not an injected
  primitive (section 4). Phase: corpus FW-07-i3 fails an expectation under the phase patch (10 of 11 configurations: the
  end text counts 6 identical readings instead of 7) while the suite pins hold; F-FW07-5 is flagged phase-sensitive for
  that reason.

**RC-WRITE-ENABLE-LEFT-ON.** After an unanswered START press, FPS1 / DGS1 turn the write enable off with single unchecked calls.
When both turn-offs of the run fail, the firmware keeps the write enable ON after the run (it disarms it only at a START press or
a reboot): SMR1 stays OWED, blocked by `<function> write enable armed`, and the run ends 'FAILED TO START' ('outcome unconfirmed, not
retried', or 'not started' when an outage outlasts the window) with its alert, which names neither the switch nor the blocked
restore. Free Power and Dump to Grid; exactly one `INV-HF-ARM-OFF` violation, every other check
holds. Triggers: three service errors while Home Assistant still sees the dongle (the press, then the turn-offs about 17 s and
62 s after it), or one ESPHome API outage covering both turn-offs under `offline_policy` `'raise'` or `'silent'` (the same end
state). For an outage that starts inside the press's flight, the extended sweep leaves the switch ON exactly when the outage
still covers the closing call (down time of about 62 s or more); a 40 s outage (HF-09-b) ends with the switch off. Severity
low: the write enable writes nothing by itself and only permits a START; the end state is that of the already-fixed D4 defect
of `docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md` (arm protection bypassed) plus a blocked SMR1 restore.
Reachability PLAUSIBLE-UNDER-ASSUMPTIONS, very low in rate; the outage form is bounded by ESPHome's 15-minute no-client reboot,
which the lab does not model (section 5, item 15). Partly documented: `docs/incidents/2026-10-11-scheduled-free-power-start.md`
names a write enable left on across a Wi-Fi-only drop for the restart recovery; the unqualified 'the write enable always ends
off' claims of both incident records, and the blocked SMR1 restore, are not documented. No independent check (section 4).

- Anchors: `FPS1` `# The write enable always ends off (the safe state: it only permits a START).`; `FW`
  `# and auto-disarms as soon as Start Free Power is pressed. Ending/restoring never`; `SMR1`
  `('switch.ecco_clock_dongle_free_power_write_enable', 'Free Power write enable armed'),`;
  `docs/incidents/2026-10-11-scheduled-free-power-start.md`
  `across a Wi-Fi-only drop stays on until the next press or reboot (it only permits a START).`
- Repair scope: FPS1 / DGS1 closing step only (Home Assistant side, no new write path): after the closing turn_off, wait a
  bounded time (about 10 s) to see the write enable off; if it is not seen off, add to the run's alert that the write enable may
  still be ON and must be turned off first (these paths already alert), and optionally send one more bounded turn_off when the
  dongle is seen again inside the run. Documentation alternative: qualify 'the write enable always ends off' (one attempt per
  step; a Wi-Fi drop or repeated service errors can leave it on until the next press or reboot). A firmware auto-disarm (timeout
  or API disconnect) needs a firmware change and is out of this scope.

**F-HF05-1, no longer a finding.** An owner change to a schedule-shaped value during STARTING is taken for the schedule's write
and the pre-schedule value is restored over it. `docs/dev/schedule-manual-restore.md` ("Owner change during a scheduled
start") documents exactly this, so since V0.1 it is a documented limit (SMR1-OWNER-STAGING), re-classified PASS and not
counted, as F-RT02-1 was in V0. The CHANGELOG line "the owner's own later change always wins" is unqualified against it: a
documentation nit. HF-05 still checks the documented outcome, and corpus HF-05-a pins it as PASS.

## 9. Negative controls and harness self-tests

A negative control mutates one guard or source-backed condition **in memory** and confirms that the intended check then fails
with the expected invariant id or the expected named checks, and no harness exception. Most controls are an exact-count
`text.replace` on the loaded firmware or package text followed by a fresh load (NC-RT02-2 and NC-RT02-3 too: they rewrite
the firmware's policy-input and stall-detector assignments). A few mutate the lab side instead: NC4 a hand-built event log
for the suite's settled-edge view, NC-PB03-a..d a time oracle, the lab clock's repeated-hour folds, one event's `t_utc` and
a per-instance `millis()`, and NC-RC-40..45 an in-memory overlay of the tree. A crashing mutant is `MUTANT-INVALID` and fails
the control. Nothing is written to disk.

A control's target is a catalogue invariant, a `finding-reproduces` check, or (since V0.1) `checks: <name>, ...`: named checks
of a scenario of the same suite, each of which must fail under the mutant and hold in the plain run (`gen_catalogue.py`
checks that every named check holds in the plain run). An **audit mutant** (outcome `killed(audit)`, id `AUDIT-<n>`) is a
mutation the lab does not run itself: it was applied in memory, outside the lab, to the firmware every suite loads, and its
row names the directed checks that failed under it (those checks hold in the plain run).

The catalogue lists 115 negative-control rows over 95 distinct mutations: **105 killed, 8 survived as expected, 2 killed as
audit mutants (`killed(audit)`: AUDIT-M1, AUDIT-M2), 0 invalid.** `run_lab.py` and `LAB_SUMMARY.txt` print the same as
`negative controls: 115 control rows over 95 distinct mutations (105 killed, 8 survived as expected, 2 killed by an audit
mutant the lab does not run itself (killed(audit): AUDIT-M1, AUDIT-M2))`, and `gen_catalogue.py` prints `negative
controls: 115 control rows over 95 distinct mutations` in its `  info  built:` line; any other outcome would be named with
its row id. The W6-1 correction added the eight rows NC-FW09-6 to NC-FW09-13, eight distinct mutations, all killed
(before it: 97 rows over 77 distinct mutations, 87 killed). The eight new distinct mutations are eight distinct mutation
texts but 6 distinct behaviours: C6k0 = C6s0 and C6k5 = C6s5 semantically (each pair leaves the same slot unverified,
with identical outcomes); `same_mutation_as` stays text identity for them (below). The W6-1b correction added the six
rows NC-FW09-14 to NC-FW09-19, six distinct mutations, all killed (before it: 105 rows over 85 distinct mutations, 95
killed). The W6-1c correction added the four rows NC-FW09-20 to NC-FW09-23, four distinct mutations, all killed
(before it: 111 rows over 91 distinct mutations, 101 killed).

| Suite | Controls | Killed | Survived (expected) | Killed (audit) | Repeat an earlier mutation |
|---|---|---|---|---|---|
| `test_lab_fw_obligations` | 9 | 7 | 0 | 2 | 0 |
| `test_lab_fw_durability` | 5 | 5 | 0 | 0 | 1 |
| `test_lab_fw_runtime` | 13 | 13 | 0 | 0 | 2 |
| `test_lab_fw_guards` | 33 | 30 | 3 | 0 | 5 |
| `test_lab_ha_schedules` | 7 | 7 | 0 | 0 | 0 |
| `test_lab_ha_lifecycle` | 12 | 10 | 2 | 0 | 3 |
| `test_lab_ha_phantom` | 9 | 7 | 2 | 0 | 5 |
| `test_lab_dst_rtc` | 11 | 11 | 0 | 0 | 1 |
| `test_lab_property` | 10 | 10 | 0 | 0 | 3 |
| `test_lab_replay_corpus` | 6 | 5 | 1 | 0 | 0 |
| total | 115 | 105 | 8 | 2 | 20 |

**Independence rule (distinct mutations).** A row is one control check. An identical mutation applied in several rows or
suites is one distinct mutation, and the catalogue records it: each row's `same_mutation_as` is null when the row applies
its own distinct mutation, or names the row whose mutation it repeats (the canonical row, the first of its group in
catalogue order; the table is `_catalogue_data.SAME_MUTATION`). A canonical row is never listed, and no value is itself a
repeat (no chains): `gen_catalogue.py` refuses a row id that is not a catalogued control, a self-map and a chain, and
`test_lab_replay_corpus` [3] checks the field (NC-RC-49 plants a chain). A repeat is the same mutant text byte for byte, or
provably the same program change written differently (a condition made constant false through another conjunct; a
statement removed or turned into a no-op; a conjunct removed or replaced by `true`); where that was not certain, the rows
stay distinct. 20 rows repeat a mutation, so the 115 rows apply 95 distinct mutations; the audit found about 13 repeats in
V0. Read "105 killed" as control checks over 95 distinct mutations, not as 105 different guards. The groups with repeats:

| Mutation | Canonical row | Repeated in |
|---|---|---|
| the PR41 dual-obligation boot check made constant false | NC-FW01-1 | NC-FW05-1, NC1a, NC1b |
| both Free Power lockout write guards removed (watchdog corrupt gate and restore-script precondition) | NC-FW01-2 | NC2b |
| S3 removed (an ACTIVE Free Power lease no longer becomes a restore request at boot) | NC-FW04-1 | NC-FW07-6, NC-HF03-2, NC-PB01-b |
| the Dump boot restore request for an ACTIVE lease removed | NC-FW04-2 | NC-FW07-5, NC-HF03-3 |
| the Dump on_boot reads a stored marker as CLEAR | NC-FW04-3 | NC6a, NC-PB01-d |
| the Dump watchdog RTC lock skip and the restore's `correction_in_progress` gate removed | NC-FW08-3 | NC-RT03-2 |
| C6, the Dump restore's 256-261 readback mismatch term | NC-FW09-2 | NC-FW09-3 |
| M7, both Free Power terms of the Dump START gate | NC-FW10-1 | NC-FW10-2 |
| M7b, only `!free_power_snapshot_valid` of the Dump START gate | NC-FW10-3 | NC-FW10-4 |
| C7, the Free Power malformed-marker lockout | NC-FW11-2 | NC-FW11-3 |
| C7ws, the wrong-size term only | NC-FW11-4 | NC-FW11-5 |
| the Free Power START gate without its two Dump terms | NC-HF04-1 | NC-PB01-a |
| the firmware's own write-enable disarm at a START press | NC-HF09-2 | NC-HF09-2b |
| only the Free Power restore-script corrupt precondition | NC2b-rs | NC2b-rs-end |

So the 33 `test_lab_fw_guards` rows apply 28 distinct mutations (M9, C6, MC244, MC256, C6k0 to C6k5, C6s0, C6s5, C6bf,
C6om, C6lt, C6r1, C6r4, C6v34, C6rh, C6rn, C6rs, C6m0, M7, M7a, M7b, C3, C7, C7ws; the suite prints `33 control checks
over 28 distinct mutations`, before the W6-1c correction 29 over 24, before the W6-1b correction 23 over 18 and before
the W6-1 correction 15 over 10), and AUDIT-M1 and AUDIT-M2 are two. None of the eight W6-1 rows repeats a mutation:
C6k0 and C6s0 both leave slot 256 unverified, and C6k5 and C6s5 slot 261, but by different edits of different lines,
so they stay distinct under the W6-1 correction's text-identity rule for `same_mutation_as` (8 distinct texts, 6
distinct behaviours), and C6 (the whole mismatch term) differs from every slot mutant. None of the six W6-1b rows
repeats a mutation either: they are six different text changes of three firmware lines (`:20333`, `:20336`, `:20337`),
each catalogued once, as one row over every scenario that kills it. None of the four W6-1c rows repeats a mutation
either: C6rh and C6rn both drop `dump_restore_block_failed` from the readback's no-response handler (`:20352`), but
C6rh also from its error and not-sent handlers and its timeout fallback (`:20347`, `:20357`, `:20365`), so their texts
differ; C6rs (`:19819`) and C6m0 (`:20043`) edit other lines. Kept distinct, among others: the Free Power end shifts
of +60 s, +300 s and +600 s (NC-HF01-1, NC-PB02-a, NC-HF08-3; different constants or sites), the four different SMR1
blocker term sets (NC-HF05-1, NC-PB02-b, NC3b, NC-HF06-1), NC2b-wd and NC2b-rs against NC2b (one guard each of NC2b's
two), NC-RT03-1 against NC-RT03-2 (a strict subset), NC-FW03-2 and AUDIT-M1 / AUDIT-M2 against NC-FW01-1 (PR41 still
fires) and NC-PB01-c against NC-FW06-1 (another domain and another change).

The outcomes of NC-FW07-1, NC-HF04-1, NC-HF04-2, NC-HF06-1, NC-RT01-1 and NC-RT01-2 depend on the lab's scheduler phase; the
catalogue marks them phase-sensitive (section 2.5).

**Survived by design** (defence in depth: one of two independent guards removed, the other still holds; or an equivalent
mutant). Each survival is scoped to the path the control runs; where another path exists, the same mutation is killed there.

- `NC-HF02-1b`: only the FPS1 startup recovery's 'not armed any more' guard disabled; the start script's own cancel check
  still ends the run (INV-HF-OWNER-INTENT holds). `NC-HF02-1` removes the disarm itself and is killed.
- `NC2b-wd`: only the Free Power watchdog corrupt gate removed; the restore script's corrupt precondition keeps
  INV-LOCKOUT-QUIET. `NC2b` removes both and is killed.
- `NC2b-rs`: only the restore script's corrupt precondition removed, **on the watchdog path only**. With no owner press, the
  watchdog's own corrupt gate (firmware `:24119`) still holds. On the End path the mutation does not survive: End & Restore
  runs the restore script unconditionally (firmware `:23298-23299`), so `NC2b-rs-end`, the same mutation with the owner's
  End / Force presses after the lockout boot, is killed by INV-LOCKOUT-QUIET. V0 stated this survival for both paths; its
  control ran without owner presses.
- `NC-HF09-2b`: only the firmware's own write-enable disarm at a START press removed, with no service error, **on the
  scheduled path only**: the package's closing turn_off still ends the switch off (INV-HF-ARM-OFF holds). `NC-HF09-2`, the
  same mutation with the closing turn_off raising, is killed. On the owner-armed path no package turn_off follows, and the
  same mutation is killed elsewhere: `test_lab_selftest_firmware` ("...the same START with the arm turned on is admitted and
  the firmware turns the arm off again"), `test_lab_ha_lifecycle` HF-09.4 ("Free Power: firmware truth - the real gate
  disarmed the write enable itself at the press ...") and the corpus trace digests (HF-02-a..c, HF-03-a, HF-03-b, HF-05-a,
  HF-05-b, HF-07-a..f, HF-08-b). No owner-armed control row exists: INV-HF-ARM-OFF exempts an owner-armed switch, so that
  kill comes from firmware-truth checks and digests, not from an invariant.
- `NC-FW10-4`: M7b (only `!free_power_snapshot_valid` removed from the Dump START gate) while Free Power holds
  RESTORE_REQUIRED: the `!free_power_active_persisted` term still refuses. M7b is killed in the other two states
  (`NC-FW10-3`).
- `NC-FW10-5`: M7a (only `!free_power_active_persisted` removed) is an equivalent mutant: the snapshot is valid in every
  reachable state in which the active flag is set. A static site check ("FW-10 M7a-equivalence") fails if that stops
  holding.
- `NC-FW11-5`: C7ws (only the wrong-size term removed) on a bad-magic record: the magic term (firmware `:527`) still
  classifies the record MALFORMED.
- `NC-RC-40`: one comment line added to `CHANGELOG.md`, a non-behavioural file: the tiered drift rule adds its SOURCE DRIFT
  line and no failure, by design (in strict mode the same edit fails).

**The audit mutants (B3).** The 2026-10-19 independent audit applied these mutations in memory to the firmware of every
V0 suite. In V0, M9, C6 and M7 failed no check at all, and C3 and C7 failed only one PB-01 check. V0.1 adds directed
scenarios (FW-09, FW-10, FW-11 in `test_lab_fw_guards`, each with corpus documents) whose named checks kill each of
them; every expected value in those checks is derived from the restore, gate and boot lambdas line by line. No FW-09,
FW-10 or FW-11 scenario check is phase-sensitive (the suite's 30 tagged checks are the trace-digest pins of its 30
corpus documents, which replay one recorded timeline on the lab grid; 25 of each before the W6-1c correction, 18 before
the W6-1b correction and 12 before the W6-1 correction); extended mode re-runs every FW-09 and FW-10 timeline at five
watchdog phase offsets (the six FW-09 b3 timelines in a check of their own, `EXT FW-09 b3`, 30 runs, the seven W6-1b
timelines in another, `EXT FW-09 b4 / b5 / b6`, 35 runs, and the five W6-1c timelines in a third, `EXT FW-09 b7`, 25
runs).

| Mutant | Guard disabled | V0 (all suites) | Killed in V0.1 by | Rows |
|---|---|---|---|---|
| M9 | Dump restore: register-244 readback compare (firmware `:19982`) | survived | FW-09 a.1, a.2, a.5 (244 write acknowledged but not applied); the replay of FW-09-a | NC-FW09-1 |
| C6 | Dump restore: 256-261 readback mismatch term (firmware `:20336`) | survived | FW-09 b.1, b.2, b.5 (6-slot block); FW-09 b2.3, b2.4 (single-slot partial mask); the replays of FW-09-b, FW-09-b2 | NC-FW09-2, NC-FW09-3 |
| C6k0 to C6k5 | Dump restore: the 256-261 readback skips one slot, 256 + k (`i != k &&` added to the compare, firmware `:20336`) | not run; V0.1 before the W6-1 correction: C6k4 killed by FW-09 b2, the other five survived every suite | the .2, .3 and .4 checks of the b3 scenario of the slot each skips, from FW-09 b3-256.2, .3, .4 (C6k0) to FW-09 b3-261.2, .3, .4 (C6k5); C6k4 also FW-09 b2.2, b2.3, b2.4; the replay of that slot's FW-09-b3 document | NC-FW09-6 to NC-FW09-11 |
| C6s0 / C6s5 | Dump restore: the readback loop's bounds (firmware `:20335`, anchored with `:20336`): it starts at slot 257 / stops before slot 261 | not run; V0.1 before the W6-1 correction: survived every suite | C6s0: FW-09 b3-256.2, .3, .4; C6s5: FW-09 b3-261.2, .3, .4; the replays of FW-09-b3-256 / FW-09-b3-261 | NC-FW09-12, NC-FW09-13 |
| C6bf / C6om / C6lt | Dump restore, the containment path: the mismatch branch's `dump_restore_block_failed = true` (firmware `:20337`); the compare's mask (`:20336`, `dump_restore_owned_mask` instead of `dump_restore_wmask`); the compare's operator (`:20336`, `<` instead of `!=`) | not run; V0.1 with the W6-1 correction: survived every suite (the internal review's V8, V6, V5) | C6bf: FW-09 b4-ct.3, .4, b4-cb.3, .4, b4-co.3, .4; C6om: FW-09 b4-co.3, .4; C6lt: the six b4 checks and FW-09 b5-lo.2, .3, .4; the replays of FW-09-b4-ct, FW-09-b4-cb, FW-09-b4-co and FW-09-b5-lo | NC-FW09-14 to NC-FW09-16 |
| C6r1 / C6r4 / C6v34 | Dump restore, slot cross-wiring: slot 257 / 260 compared with the previous slot's expected value (`:20336`); the readback's `v[]` initialiser with `id(dump_restore_v3)` and `id(dump_restore_v4)` swapped (`:20333`) | not run; V0.1 with the W6-1 correction: survived every suite (the internal review's V4a, V4b, V7) | each: FW-09 b6-ok.1, .2; C6r1: FW-09 b6-x257.2, .3, .4; C6r4 and C6v34: FW-09 b6-x260.2, .3, .4; the replays of FW-09-b6-ok and FW-09-b6-x257 / FW-09-b6-x260 | NC-FW09-17 to NC-FW09-19 |
| C6rh / C6rn / C6rs / C6m0 | Dump restore, the containment claim: `dump_restore_block_failed = true` dropped from the 256-261 readback's failure handlers (`:20347`, `:20352`, `:20357`, `:20365`; C6rn only `:20352`); the per-attempt reset of `dump_restore_contained` dropped (`:19819`); `&& m != 0` dropped from the containment flag (`:20043`) | not run; V0.1 with the W6-1b correction: survived every suite (the internal review's F28, F29, F32, F16) | C6rh: FW-09 b7-rbnr.3, .4, .6, b7-rber.3, .4, .6, b7-cmnr.2, .3, .6; C6rn: FW-09 b7-rbnr.3, .4, .6, b7-cmnr.2, .3, .6; C6rs: FW-09 b7-ab.3, .4, .6; C6m0: FW-09 b7-af.3, .4, .6; the replays of FW-09-b7-rbnr, FW-09-b7-rber, FW-09-b7-cmnr, FW-09-b7-ab and FW-09-b7-af | NC-FW09-20 to NC-FW09-23 |
| MC244 | the 244 verify read's on_error no longer fails the attempt (firmware `:19993`) | not run | FW-09 c.1, c.2 | NC-FW09-4 |
| MC256 | the 256-261 verify read's on_no_response no longer fails the attempt (firmware `:20352`) | not run | FW-09 c2.1, c2.2 | NC-FW09-5 |
| M7 | Free Power terms of the Dump START gate (firmware `:18060-18061`) | survived | FW-10 A.2, A.3 (Free Power RESTORE_REQUIRED), FW-10 B.2 (PENDING_CLEAR) | NC-FW10-1, NC-FW10-2 |
| M7b / M7a | one of the two terms (`:18061` / `:18060`) | not run | M7b: FW-10 B.2, C.2, C.3; M7a: equivalent (static check) | NC-FW10-3, -4, -5 |
| C3 | Free Power marker READ_ERROR treated as CLEAR (firmware `:525`) | one PB-01 check | FW-11 read_error (CLEAR).1, (RESTORE_REQUIRED).1, (RESTORE_REQUIRED).3, on a used `fp.valid` key | NC-FW11-1 |
| C7 | malformed / wrong-size Free Power marker treated as CLEAR (firmware `:526-531`) | one PB-01 check | FW-11 wrong_size and bad_magic (CLEAR).1, (RESTORE_REQUIRED).1, (RESTORE_REQUIRED).3 | NC-FW11-2, NC-FW11-3 |
| C7ws | the wrong-size term only (firmware `:526`) | not run | FW-11 wrong_size (CLEAR).1, (RESTORE_REQUIRED).1 | NC-FW11-4, -5 |
| M1 / M2 | the PR41 boot check locks only Dump / only Free Power (the other corrupt assignment removed, firmware `:1146` / `:1147`) | killed by directed checks; survive PB-01 | `test_lab_fw_obligations` "FW-01: the FULL on_boot's PR41 check locks BOTH domains at every boot"; `test_lab_fw_durability` "FW-05 A-start: every cut whose capture holds BOTH markers RESTORE_REQUIRED ..." and its siblings; `test_lab_ha_phantom` "a: the full on_boot fires PR41" / "b: the full on_boot fires PR41" | AUDIT-M1, AUDIT-M2 |

Scenario FW-09 c / c2 (the verify READ fails after an acknowledged write) cannot kill M9 or C6 by construction: those compares
run only in `on_response`, while c and c2 take `on_error` / `on_no_response`. They carry their own error-branch mutants, MC244
and MC256, and a characterisation check ("FW-09 c-blind") shows that M9 and C6 leave their outcome unchanged. In every FW-09
case the failing attempt reports no "RESTORED OK" and keeps the marker RESTORE_REQUIRED; no case has an
INV-NO-SILENT-OVERRIDE violation, and the status texts match the bank. The independent re-check of V0.1 (2026-10-21)
re-applied the audit mutants M9, C6, M7, C3, C7, M1 and M2 on disk, in its own forms and independently of the lab's
mutant strings, and found each killed by named directed checks (M7a equivalent, as above); it also found the per-slot gap
below.

**The per-slot verify gap (W6-1): the named slot mutants killed on the non-containment per-slot plan.** The Dump
restore verifies its 256-261 readback slot by slot: the loop `for (int i = 0; i < 6; i++) {` and the compare
`if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {` (firmware `:20335-20336`). Before the W6-1
correction the lab tested a readback mismatch only for the whole 6-slot block (b) and for slot 260 alone (b2). The
independent re-check applied fresh per-slot mutants on disk: a mutation that stops verifying slot 256, 257, 258, 259 or
261, or that cuts the loop short, failed no behavioural check in any of the 14 suites (C6s0 and C6s5 survived all 14
suites; C6k1 to C6k3 tripped only the anchor tripwires of the edited line; C6k4 was killed by b2). With such a
regression the restore would report success with that slot still at the lease value whenever the inverter acknowledged
the write but did not apply it. Before the correction the lab reproduced this in memory, with the exact-count text
replace its controls use: the loop line occurs 16 times in the firmware, so C6s0 and C6s5 anchor on lines
`:20335-20336` together, which occur once. All 14 suites, quick mode, in memory:

| Mutant | Slot never verified | Before the W6-1 correction | After it (catalogue row) |
|---|---|---|---|
| C6k0 | 256 | survived: no FAIL line in any suite | killed by FW-09 b3-256.2, .3, .4 and the expectations of corpus FW-09-b3-256 (NC-FW09-6) |
| C6k1 | 257 | survived: no FAIL line in any suite | killed by FW-09 b3-257.2, .3, .4 and the expectations of corpus FW-09-b3-257 (NC-FW09-7) |
| C6k2 | 258 | survived: no FAIL line in any suite | killed by FW-09 b3-258.2, .3, .4 and the expectations of corpus FW-09-b3-258 (NC-FW09-8) |
| C6k3 | 259 | survived: no FAIL line in any suite | killed by FW-09 b3-259.2, .3, .4 and the expectations of corpus FW-09-b3-259 (NC-FW09-9) |
| C6k4 | 260 | killed by FW-09 b2.2, b2.3, b2.4 and the expectations of corpus FW-09-b2 | killed as before, and by FW-09 b3-260.2, .3, .4 and the expectations of corpus FW-09-b3-260 (NC-FW09-10) |
| C6k5 | 261 | survived: no FAIL line in any suite | killed by FW-09 b3-261.2, .3, .4 and the expectations of corpus FW-09-b3-261 (NC-FW09-11) |
| C6s0 | 256 | survived: no FAIL line in any suite | killed by FW-09 b3-256.2, .3, .4 and the expectations of corpus FW-09-b3-256 (NC-FW09-12) |
| C6s5 | 261 | survived: no FAIL line in any suite | killed by FW-09 b3-261.2, .3, .4 and the expectations of corpus FW-09-b3-261 (NC-FW09-13) |

Each mutant fails the checks of its own slot's scenarios only (b2 is a slot-260 scenario too; this was measured in memory
before the W6-1b and W6-1c scenarios existed; on disk the internal review of W6-1c re-applied the 8 with them present,
and all stay killed, C6k0 and C6s0 also by b4-co and the `FW-09 claims` check, C6k1 by b6-x257, C6k2 by b4-ct, b7-ab and
`FW-09 claims`, C6k3 by b5-lo and C6k4 by b6-x260). Under it the first attempt
ends in the FOREIGN-lockout text that ECCO's own settings were "restored and verified" (firmware `:20460-20481`), with
the skipped slot still at the lease's 1000 W, and the mismatch count stays 0; the marker stays RESTORE_REQUIRED and the
operator lockout is set, so no core invariant checker sees a violation (section 15). The kills therefore rest on the
directed checks (.2 the number of attempts, .3 the claims and the mismatch count, .4 the truthful report) and the corpus
expectations (the globals, and the status history containing the second-mismatch text and not the FOREIGN-lockout text);
`test_lab_fw_guards` [5] also replays each FW-09-b3 document against every slot mutant that skips its slot (8
discrimination checks). In memory the
replay suite's trace-digest check of the document fails as well, but it is not counted as a kill: on disk the tiered
drift rule judges a changed firmware on its expectations only. No counted finding changed. The final independent audit
(2026-10-22) re-applied these mutants on disk in its own forms and found them killed (section 15, item 11).

What the W6-1 correction covers is exactly this: the 8 named per-slot mutants (C6k0 to C6k5, C6s0, C6s5) are killed on
the non-containment per-slot plan. They are 6 distinct behaviours (C6k0 = C6s0 and C6k5 = C6s5 semantically). An
internal review of the correction (not the independent re-validation) found six further per-slot verify regressions that
still survived all 14 suites: on the containment path, against a readback above the expected value, and through slot
cross-wiring that the repeated synthetic SITE ORIGINAL values masked. The W6-1b correction kills them on the modelled
shapes (below); what remains is section 15, item 15, and the block path's partial application is item 13.

**The W6-1b correction: the six survivors of the W6-1 review killed on the modelled shapes.** The internal reviewer's
on-disk forms are the reference: each of the six is catalogued as an in-memory mutant whose text is byte-identical to
the reviewer's form, applied by the exact-count text replace of the other controls on a line that occurs once with its
indentation (the bare `id(dump_restore_block_failed) = true;` of `:20337` occurs 33 times in the firmware, the bare
`v[]` initialiser line of `:20333` twice). Before the correction each one, applied in memory to the committed W6-1 tree,
failed no check in any of the 14 suites in quick mode. The correction adds seven FW-09 scenarios whose expectations are
derived from the firmware source (section 7): on the containment path, where 244 is not proven and the restore writes
every non-FOREIGN slot at min(original, 500 W) (firmware `:20019-20031`), b4-ct leaves the floor write of 258 unapplied
next to a FOREIGN 261, b4-cb the 6-slot floor block (nothing FOREIGN) and b4-co the floor write of 256, which reads its
ORIGINAL and is written although ECCO does not own it; b5-lo is b3's shape for a 259 whose original (600 W) is below the
1000 W lease value; b6-ok restores pairwise-distinct originals fault-free, and b6-x257 / b6-x260 are b3's shape for 257
/ 260 on that bank with 256's / 259's original equal to the lease value. All 14 suites, quick mode, in memory:

| Mutant | Review variant | Edit (firmware) | Before the W6-1b correction | After it (catalogue row) |
|---|---|---|---|---|
| C6bf | V8 | `id(dump_restore_block_failed) = true;` commented out (`:20337`) | survived: no FAIL line in any suite | killed by FW-09 b4-ct.3, .4, b4-cb.3, .4, b4-co.3, .4 and the expectations of corpus FW-09-b4-ct, FW-09-b4-cb, FW-09-b4-co (NC-FW09-14) |
| C6om | V6 | `dump_restore_owned_mask` instead of `dump_restore_wmask` in the compare (`:20336`) | survived: no FAIL line in any suite | killed by FW-09 b4-co.3, .4 and the expectations of corpus FW-09-b4-co (NC-FW09-15) |
| C6lt | V5 | `values[i] < v[i]` instead of `values[i] != v[i]` (`:20336`) | survived: no FAIL line in any suite | killed by FW-09 b4-ct.3, .4, b4-cb.3, .4, b4-co.3, .4, b5-lo.2, .3, .4 and the expectations of corpus FW-09-b4-ct, FW-09-b4-cb, FW-09-b4-co, FW-09-b5-lo (NC-FW09-16) |
| C6r1 | V4a | slot 257 compared with slot 256's expected value, `v[i == 1 ? i - 1 : i]` (`:20336`) | survived: no FAIL line in any suite | killed by FW-09 b6-ok.1, .2, b6-x257.2, .3, .4 and the expectations of corpus FW-09-b6-ok, FW-09-b6-x257 (NC-FW09-17) |
| C6r4 | V4b | slot 260 compared with slot 259's expected value, `v[i == 4 ? i - 1 : i]` (`:20336`) | survived: no FAIL line in any suite | killed by FW-09 b6-ok.1, .2, b6-x260.2, .3, .4 and the expectations of corpus FW-09-b6-ok, FW-09-b6-x260 (NC-FW09-18) |
| C6v34 | V7 | the readback's `v[]` initialiser swaps `id(dump_restore_v3)` and `id(dump_restore_v4)` (`:20333`) | survived: no FAIL line in any suite | killed by FW-09 b6-ok.1, .2, b6-x260.2, .3, .4 and the expectations of corpus FW-09-b6-ok, FW-09-b6-x260 (NC-FW09-19) |

How each is killed. On the containment path the unapplied floor write must fail the readback and set
`dump_restore_block_failed` (`:20337`), which keeps `dump_restore_contained` clear (`:20372`). C6bf drops that flag,
C6lt misses a readback above the 500 W floor and C6om checks the slots ECCO owned at the pre-read instead of the slots
written (of the W6-1b modelled shapes, that changes the outcome only in b4-co, where the containment writes a slot that
reads its ORIGINAL): the restore then claims the containment ("ECCO's own at 500 W", or "held at the 500 W floor";
`:20453-20456`, `:20541-20544`) while the slot is not at the floor, so the b4 checks .3 (the statuses' exact suffix and
no containment claim) and .4 (`dump_restore_block_failed` set, `dump_restore_contained` clear) fail. On b5-lo C6lt
misses the mismatch of the unapplied 259, which reads 1000 W above its 600 W original, and b5-lo.2, .3 and .4 fail (the
retry, the claims and the mismatch count, the truthful report). C6r1, C6r4 and C6v34 compare a slot with its neighbour's
expected value: on b6-ok a fault-free restore shows a false mismatch and a second attempt, whose final state is the same
as the plain run's, so the kill rests on b6-ok.1 (exactly one attempt) and .2 (exactly RESTORING, RESTORED OK, no
'RESTORE VERIFY FAILED'); on b6-x257 / b6-x260 the unapplied slot reads 1000 W, its neighbour's expected value, so the
mismatch is missed and .2, .3 and .4 fail. `test_lab_fw_guards` [5] also replays each new document against every W6-1b
mutant it targets (14 discrimination checks). In memory the replay suite's trace-digest checks of the new documents fail
as well; as for W6-1 they are not counted as kills. No counted finding changed. An internal review of this correction
re-applied the six on disk in its own forms (all killed) and found four further containment-claim regressions that
survived all 14 suites; the W6-1c correction kills them on the modelled shapes (below). The W6-1b mutants were measured
in memory before the W6-1c scenarios existed; on disk the internal review of W6-1c re-applied the six with them present,
and all stay killed, C6lt, C6om and C6bf also by b7-ab and the `FW-09 claims` check. The final independent audit
(2026-10-22) re-applied these mutants on disk in its own forms and found them killed (section 15, item 11).

**The W6-1c correction: the four containment-claim survivors of the W6-1b review killed on the modelled shapes.** This
is the final correction cycle: after it the owner stopped the mutation search, and a final independent audit of the
completed candidate followed (section 15, item 11). As for W6-1b, the internal reviewer's on-disk forms are the
reference: each of the four is catalogued as an in-memory mutant whose text is byte-identical to the reviewer's form,
applied by the exact-count text replace of the other controls on a text that occurs once (the readback's failure-handler
line `if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }`
occurs 24 times in the firmware and its timeout fallback's line 8 times, so C6rh anchors on the readback's whole failure
tail `:20340-20366` and C6rn on MC256's `:20340-20352`; the per-attempt reset `:19819` and the containment flag `:20043`
are whole lines with their indentation). Before the correction each one, applied in memory to the committed W6-1b tree,
failed no check in any of the 14 suites in quick mode. The correction adds five FW-09 scenarios whose expectations are
derived from the firmware source (section 7) and a containment-claim truthfulness helper. All 14 suites, quick mode, in
memory:

| Mutant | Review variant | Edit (firmware) | Before the W6-1c correction | After it (catalogue row) |
|---|---|---|---|---|
| C6rh | F28 | `id(dump_restore_block_failed) = true;` dropped from the 256-261 readback's on_error, on_no_response and on_not_sent handlers and its timeout fallback (`:20347`, `:20352`, `:20357`, `:20365`) | survived: no FAIL line in any suite | killed by FW-09 b7-rbnr.3, .4, .6, b7-rber.3, .4, .6, b7-cmnr.2, .3, .6 and the expectations of corpus FW-09-b7-rbnr, FW-09-b7-rber, FW-09-b7-cmnr (NC-FW09-20) |
| C6rn | F29 | `id(dump_restore_block_failed) = true;` dropped from the on_no_response handler only (`:20352`) | survived: no FAIL line in any suite | killed by FW-09 b7-rbnr.3, .4, .6, b7-cmnr.2, .3, .6 and the expectations of corpus FW-09-b7-rbnr, FW-09-b7-cmnr (NC-FW09-21) |
| C6rs | F32 | the per-attempt reset `id(dump_restore_contained) = false;` replaced by a comment (`:19819`) | survived: no FAIL line in any suite | killed by FW-09 b7-ab.3, .4, .6 and the expectations of corpus FW-09-b7-ab (NC-FW09-22) |
| C6m0 | F16 | `id(dump_restore_contain) = contain && m != 0;` loses `&& m != 0` (`:20043`) | survived: no FAIL line in any suite | killed by FW-09 b7-af.3, .4, .6 and the expectations of corpus FW-09-b7-af (NC-FW09-23) |

How each is killed. On the containment path (244 not proven) the restore claims the containment ("ECCO's own at 500 W",
or 'held at the 500 W floor'; `:20447-20459`, `:20535-20546`) only while `dump_restore_contained` is set, and `:20372`
sets it only when the attempt's containment plan was written (`dump_restore_contain`, `:20043`) and nothing set
`dump_restore_block_failed`. A failed 256-261 readback sets that flag in its handler (`:20343-20366`). C6rh and C6rn
drop it: on b7-rbnr and b7-rber (C6rn: b7-rbnr) the restore then claims a containment that no readback confirmed while
the unapplied slots hold the 1000 W lease value, and on b7-cmnr the comms-path 'RESTORE WRITE FAILED' status carries the
claim. C6rs drops the per-attempt reset (`:19819`): on b7-ab the first attempt's verified containment is carried into
the failed second attempt, whose lockout and operator wait claim 'held at the 500 W floor' while 258 is at its ORIGINAL
7000 W. C6m0 flags the containment although the plan writes nothing: on b7-af (every slot FOREIGN) the statuses claim
"ECCO's own at 500 W" with all six slots NOT CONTAINED. In each case the scenario's checks .3 (the statuses' exact
suffix and no containment claim; on b7-cmnr .2), .4 (the containment globals and the truthful report; on b7-cmnr .3) and
.6 (the containment-claim helper) fail. The helper (`contain_claims` in `test_lab_fw_guards`) is derived from the
firmware source (`:20453-20456`, `:20541-20544`, `:20028-20031`, `:20043`): a status that claims the containment must be
backed by the bank as it stood when that status was published, with at least one 256-261 slot non-FOREIGN at the
attempt's ownership pre-read and every such slot at min(original, 500 W). It rebuilds the bank at each publish instant
from the event log (every landed firmware write and every inverter change) and fails loud if the rebuilt end state
differs from the world's. It holds on the plain firmware on every FW-09 timeline: the aggregate check `FW-09 claims` in
section [1] applies it to all 23 timelines, the suite tails included, and checks 5 claims (a 3, c 1, b7-ab 1); each b7
scenario has its own check .6. The helper reaches the existing timelines through these new checks only, so every check
`test_lab_fw_guards` already had keeps its name and verdict; in the replay suite only the four check names that embed
the corpus count change (110 -> 115 documents: the corpus-load check, the B1 tier-pin check, NC-RC-41 and NC-RC-42), as
in the earlier corrections. Applied in memory with all 14 suites, each of the four also fails `FW-09 claims` and the
expectations of its corpus documents, in `test_lab_fw_guards` [5] and in the replay suite; `test_lab_fw_guards` [5] also
replays each new document against every W6-1c mutant it targets (7 discrimination checks). In memory the replay suite's
trace-digest checks of the new documents fail as well; as before they are not counted as kills. No counted finding
changed.

One planned shape differs from the correction's specification, and the source decides it. A containment made by an
unapplied 244 write ('write:244x1' acknowledged but not applied) with a failed 256-261 readback takes the firmware's
MISMATCH path, not its comms path: the 244 readback mismatch sets `dump_restore_mismatch_this_attempt` (`:19982-19984`),
so the failed attempt publishes 'RESTORE VERIFY FAILED' and, at the second mismatch, the operator lockout
(`:20482-20507`), and `dump_comms_restore_attempts` stays 0. b7-rbnr and b7-rber encode that path. The comms path
(`:20508-20519`) is reached in containment only when 244 is unproven by a comms failure with no 244 mismatch, as in
FW-09 c (a 244 verify-read error, `:19989-19993`); b7-cmnr is that shape with the floor block unapplied and the readback
unanswered, and the suite follows its retry. No expectation was bent: the difference was raised at step 0 and accepted,
with b7-cmnr added, in place of the specification's STOP.

An internal review of this correction (not the independent re-validation) re-applied the four on disk in its own
forms, each byte-identical to the catalogued text, and found each killed by named behavioural checks with as many
behavioural FAIL lines as in memory (C6rh 16, C6rn 11, C6rs 6, C6m0 6); it re-applied the 14 earlier closures of W6-1
and W6-1b on disk (all killed), checked the new expectations and the helper against the firmware source, and ran the
regression matrix (LF and CRLF exports, five environment variants, the phase patch with seeds 1 to 3, `trace_inputs`,
`rerecord_corpus --check`). It ran no new mutation search. What remains is section 15, item 16: a partially applied
256x6 block is not modelled; the helper is a suite-level check, not a core invariant, judges a claim at its first
publication and assumes the 1000 W START ceiling; the readback's on_not_sent and timeout handlers (`:20357`, `:20365`)
are covered only through C6rh as a whole; a containment claim republished during the operator wait is not re-read
against 256-261 by the firmware. The final independent audit (2026-10-22) re-applied these mutants on disk in its
own forms and found them killed (section 15, item 11).

Every control row (the catalogue's `negative_controls`; in brackets the outcome when it is not `killed`; the last column is
`same_mutation_as`, `-` for a row that applies its own distinct mutation):

| ID | Suite | In-memory mutation | Target | Same mutation as |
|---|---|---|---|---|
| NC-FW01-1 | fw_obligations | PR41 condition replaced by false (no Free Power / Dump dual-obligation lockout) | INV-NO-2ND-RESTORER | - |
| NC-FW01-2 | fw_obligations | Free Power corrupt gates removed from the watchdog and the restore precondition | INV-LOCKOUT-QUIET | - |
| NC-FW01-3 | fw_obligations | SG-02 containment literal 2 (Zero Export) changed to 1 | INV-LOCKOUT-QUIET | - |
| NC-FW01-4 | fw_obligations | status-only repair-shaped mutant (lambda-local dual flag set in PR41, dual sub-branch in the Free Power status block) | finding-reproduces:F-FW01-3 | - |
| NC-FW02-1 | fw_obligations | Dump restore pre-read treats every changed slot as ECCO-owned | INV-NO-SILENT-OVERRIDE | - |
| NC-FW03-1 | fw_obligations | Free Power restore register-244 lease-context comparison replaced by true (both pre-write gates) | INV-NO-2ND-RESTORER | - |
| NC-FW03-2 | fw_obligations | PR41 guard without '!dump_recovery_metadata_corrupt' (PR41 also fires after S4) | finding-reproduces:F-FW03-1 | - |
| NC-FW04-1 | fw_durability | S3 removed: the boot no longer converts an ACTIVE Free Power lease into a restore request | INV-NO-RESUME | - |
| NC-FW04-2 | fw_durability | the Dump boot no longer sets dump_restore_requested for an ACTIVE lease | INV-NO-RESUME | - |
| NC-FW04-3 | fw_durability | the Dump on_boot reads a stored marker as CLEAR (a stored RESTORE_REQUIRED ignored during an ACTIVE lease) | INV-BOOT-MIRROR | - |
| NC-FW05-1 | fw_durability | PR41 never fires (cut after the phantom-admitted START's 256-261 write) | INV-NO-2ND-RESTORER | NC-FW01-1 |
| NC-FW06-1 | fw_durability | Phase-B guard: START proceeds on the data commit alone (marker true negative + reboot during the lease) | INV-NO-SILENT-OVERRIDE | - |
| NC-FW07-1 | fw_runtime | SG-39 link-recovery clause removed (FW-07-A; the kill depends on the scheduler phase: phase_sensitive) | INV-RESTORE-BOUND | - |
| NC-FW07-2 | fw_runtime | TELEMETRY LOST monitor neutered (FW-07-A) | INV-17 | - |
| NC-FW07-3 | fw_runtime | no-fresh-SOC clause removed (FW-07-C) | INV-16 | - |
| NC-FW07-4 | fw_runtime | owed Stop SOC record binding removed (FW-07-D) | INV-16 | - |
| NC-FW07-5 | fw_runtime | Dump boot no-resume removed (FW-07-E) | INV-NO-RESUME | NC-FW04-2 |
| NC-FW07-6 | fw_runtime | Free Power S3 removed (FW-07-E) | INV-NO-RESUME | NC-FW04-1 |
| NC-FW07-7 | fw_runtime | the owner's lower configured Stop SOC replaces the owed one (FW-07-D) | INV-16 | - |
| NC-FW07-8 | fw_runtime | the fast frozen-CT criterion removed: only the 30-read slow window is left (FW-07-I) | INV-17 | - |
| NC-FW07-9 | fw_runtime | the frozen-SOC energy term removed from the watchdog's frozen condition (FW-07-I) | INV-17 | - |
| NC-FW07-10 | fw_runtime | the battery-power repeat term removed from the watchdog's frozen condition (FW-07-I) | INV-17 | - |
| NC-FW08-1 | fw_runtime | stuck-lock escalation restart removed (FW-08-B) | INV-20 | - |
| NC-FW08-2 | fw_runtime | lock age ignores the shared write mutex (FW-08-B) | INV-20 | - |
| NC-FW08-3 | fw_runtime | watchdog trigger and restore gate ignore the RTC lock (FW-08-E) | INV-RTC-EXCL | - |
| NC-FW09-1 | fw_guards | the Dump restore's register-244 readback compare disabled (M9, FW:19982); 244 write acknowledged but not applied | checks: FW-09 a.1, FW-09 a.2, FW-09 a.5 | - |
| NC-FW09-2 | fw_guards | the Dump restore's 256-261 readback mismatch term disabled (C6, FW:20336); 6-slot block write acknowledged but not applied | checks: FW-09 b.1, FW-09 b.2, FW-09 b.5 | - |
| NC-FW09-3 | fw_guards | C6 on the single-slot partial-mask restore (a FOREIGN 261, every retry a 260-only write) | checks: FW-09 b2.3, FW-09 b2.4 | NC-FW09-2 |
| NC-FW09-4 | fw_guards | the Dump restore's 244 verify read on_error no longer fails the attempt (MC244, FW:19993; the error-branch mutant of scenario c, which M9 cannot reach) | checks: FW-09 c.1, FW-09 c.2 | - |
| NC-FW09-5 | fw_guards | the Dump restore's 256-261 verify read on_no_response no longer fails the attempt (MC256, FW:20352; the error-branch mutant of scenario c2, which C6 cannot reach) | checks: FW-09 c2.1, FW-09 c2.2 | - |
| NC-FW09-6 | fw_guards | the Dump restore's 256-261 readback never verifies slot 256 (C6k0, FW:20336 gains 'i != 0 &&'); a FOREIGN 261, every single-register write of 256 after the End (policy write:256x1) acknowledged but not applied | checks: FW-09 b3-256.2, FW-09 b3-256.3, FW-09 b3-256.4 | - |
| NC-FW09-7 | fw_guards | the Dump restore's 256-261 readback never verifies slot 257 (C6k1, FW:20336 gains 'i != 1 &&'); a FOREIGN 261, every single-register write of 257 after the End (policy write:257x1) acknowledged but not applied | checks: FW-09 b3-257.2, FW-09 b3-257.3, FW-09 b3-257.4 | - |
| NC-FW09-8 | fw_guards | the Dump restore's 256-261 readback never verifies slot 258 (C6k2, FW:20336 gains 'i != 2 &&'); a FOREIGN 261, every single-register write of 258 after the End (policy write:258x1) acknowledged but not applied | checks: FW-09 b3-258.2, FW-09 b3-258.3, FW-09 b3-258.4 | - |
| NC-FW09-9 | fw_guards | the Dump restore's 256-261 readback never verifies slot 259 (C6k3, FW:20336 gains 'i != 3 &&'); a FOREIGN 261, every single-register write of 259 after the End (policy write:259x1) acknowledged but not applied | checks: FW-09 b3-259.2, FW-09 b3-259.3, FW-09 b3-259.4 | - |
| NC-FW09-10 | fw_guards | the Dump restore's 256-261 readback never verifies slot 260 (C6k4, FW:20336 gains 'i != 4 &&'); the b2 single-slot retries and a FOREIGN 261 with every single-register write of 260 after the End (policy write:260x1) acknowledged but not applied | checks: FW-09 b2.2, FW-09 b2.3, FW-09 b2.4, FW-09 b3-260.2, FW-09 b3-260.3, FW-09 b3-260.4 | - |
| NC-FW09-11 | fw_guards | the Dump restore's 256-261 readback never verifies slot 261 (C6k5, FW:20336 gains 'i != 5 &&'); a FOREIGN 256, every single-register write of 261 after the End (policy write:261x1) acknowledged but not applied | checks: FW-09 b3-261.2, FW-09 b3-261.3, FW-09 b3-261.4 | - |
| NC-FW09-12 | fw_guards | the Dump restore's 256-261 readback loop starts at slot 257, so 256 is never verified (C6s0, FW:20335 'i = 1', anchored with FW:20336); a FOREIGN 261, every single-register write of 256 after the End (policy write:256x1) acknowledged but not applied | checks: FW-09 b3-256.2, FW-09 b3-256.3, FW-09 b3-256.4 | - |
| NC-FW09-13 | fw_guards | the Dump restore's 256-261 readback loop stops before slot 261, so 261 is never verified (C6s5, FW:20335 'i < 5', anchored with FW:20336); a FOREIGN 256, every single-register write of 261 after the End (policy write:261x1) acknowledged but not applied | checks: FW-09 b3-261.2, FW-09 b3-261.3, FW-09 b3-261.4 | - |
| NC-FW09-14 | fw_guards | a 256-261 readback mismatch no longer sets dump_restore_block_failed (C6bf, FW:20337 commented out), so an unapplied containment write still counts as contained (FW:20372); 244 acknowledged but not applied (containment) with slot 258's floor write (FOREIGN 261), the 6-slot floor block (nothing FOREIGN) or the floor write of 256 back at its ORIGINAL (FOREIGN 261) acknowledged but not applied | checks: FW-09 b4-ct.3, FW-09 b4-ct.4, FW-09 b4-cb.3, FW-09 b4-cb.4, FW-09 b4-co.3, FW-09 b4-co.4 | - |
| NC-FW09-15 | fw_guards | the Dump restore's 256-261 readback checks the slots ECCO owned at the pre-read instead of the slots written this attempt (C6om, FW:20336 dump_restore_owned_mask instead of dump_restore_wmask); containment writes 256, which reads its ORIGINAL (not owned), and that write is acknowledged but not applied | checks: FW-09 b4-co.3, FW-09 b4-co.4 | - |
| NC-FW09-16 | fw_guards | the Dump restore's 256-261 readback flags only a value below the expected one (C6lt, FW:20336 '<' instead of '!='); the three containment scenarios (the unapplied slots read 1000 W or 8000 W against the 500 W floor) and slot 259 at the 1000 W lease value against its 600 W original | checks: FW-09 b4-ct.3, FW-09 b4-ct.4, FW-09 b4-cb.3, FW-09 b4-cb.4, FW-09 b4-co.3, FW-09 b4-co.4, FW-09 b5-lo.2, FW-09 b5-lo.3, FW-09 b5-lo.4 | - |
| NC-FW09-17 | fw_guards | the Dump restore's 256-261 readback compares slot 257 with slot 256's expected value (C6r1, FW:20336 'v[i == 1 ? i - 1 : i]'); a fault-free restore of pairwise-distinct originals, and 257 acknowledged but not applied (FOREIGN 261) with 256's original equal to the 1000 W lease value | checks: FW-09 b6-ok.1, FW-09 b6-ok.2, FW-09 b6-x257.2, FW-09 b6-x257.3, FW-09 b6-x257.4 | - |
| NC-FW09-18 | fw_guards | the Dump restore's 256-261 readback compares slot 260 with slot 259's expected value (C6r4, FW:20336 'v[i == 4 ? i - 1 : i]'); a fault-free restore of pairwise-distinct originals, and 260 acknowledged but not applied (FOREIGN 261) with 259's original equal to the 1000 W lease value | checks: FW-09 b6-ok.1, FW-09 b6-ok.2, FW-09 b6-x260.2, FW-09 b6-x260.3, FW-09 b6-x260.4 | - |
| NC-FW09-19 | fw_guards | the Dump restore's 256-261 readback expected values swap slots 259 and 260 (C6v34, FW:20333 v[] initialiser 'id(dump_restore_v4), id(dump_restore_v3)'); a fault-free restore of pairwise-distinct originals, and 260 acknowledged but not applied (FOREIGN 261) with 259's original equal to the 1000 W lease value | checks: FW-09 b6-ok.1, FW-09 b6-ok.2, FW-09 b6-x260.2, FW-09 b6-x260.3, FW-09 b6-x260.4 | - |
| NC-FW09-20 | fw_guards | the Dump restore's 256-261 readback failure handlers no longer set dump_restore_block_failed (C6rh, FW:20347, FW:20352, FW:20357, FW:20365), so a containment whose readback failed still counts as contained (FW:20372); 244 acknowledged but not applied (containment) with the 6-slot floor block unapplied and the readback unanswered, with slot 258's floor write unapplied (FOREIGN 261) and the readback erroring, and 244 unproven by a verify-read error with the floor block unapplied and the readback unanswered | checks: FW-09 b7-rbnr.3, FW-09 b7-rbnr.4, FW-09 b7-rbnr.6, FW-09 b7-rber.3, FW-09 b7-rber.4, FW-09 b7-rber.6, FW-09 b7-cmnr.2, FW-09 b7-cmnr.3, FW-09 b7-cmnr.6 | - |
| NC-FW09-21 | fw_guards | the Dump restore's 256-261 readback no-response handler no longer sets dump_restore_block_failed (C6rn, FW:20352), so a containment whose readback got no response still counts as contained (FW:20372); the two containment scenarios whose readback gets no response (the mismatch path and the comms path) | checks: FW-09 b7-rbnr.3, FW-09 b7-rbnr.4, FW-09 b7-rbnr.6, FW-09 b7-cmnr.2, FW-09 b7-cmnr.3, FW-09 b7-cmnr.6 | - |
| NC-FW09-22 | fw_guards | the Dump restore no longer resets dump_restore_contained when an attempt starts (C6rs, FW:19819); a verified containment attempt followed by a failed one (258 back at its ORIGINAL, the second floor block acknowledged but not applied) | checks: FW-09 b7-ab.3, FW-09 b7-ab.4, FW-09 b7-ab.6 | - |
| NC-FW09-23 | fw_guards | the Dump restore flags the containment even when its plan writes nothing (C6m0, FW:20043 '&& m != 0' dropped); containment (244 acknowledged but not applied) with every 256-261 slot FOREIGN | checks: FW-09 b7-af.3, FW-09 b7-af.4, FW-09 b7-af.6 | - |
| NC-FW10-1 | fw_guards | both Free Power terms removed from the Dump START gate (M7, FW:18060-18061); Free Power RESTORE_REQUIRED | checks: FW-10 A.2, FW-10 A.3 | - |
| NC-FW10-2 | fw_guards | M7 with Free Power PENDING_CLEAR | checks: FW-10 B.2 | NC-FW10-1 |
| NC-FW10-3 | fw_guards | only '!free_power_snapshot_valid' removed from the Dump START gate (M7b, FW:18061); Free Power PENDING_CLEAR and the UNKNOWN lockout | checks: FW-10 B.2, FW-10 C.2, FW-10 C.3 | - |
| NC-FW10-4 | fw_guards | M7b with Free Power RESTORE_REQUIRED (the '!free_power_active_persisted' term still refuses) | checks: FW-10 A (survived(expected)) | NC-FW10-3 |
| NC-FW10-5 | fw_guards | only '!free_power_active_persisted' removed from the Dump START gate (M7a, FW:18060): an equivalent mutant, snapshot_valid is set in every reachable state with active_persisted set (the static site check) | checks: FW-10 M7a-equivalence (survived(expected)) | - |
| NC-FW11-1 | fw_guards | the Free Power marker READ_ERROR lockout removed: an unreadable marker reads as CLEAR (C3, FW:525) | checks: FW-11 read_error (CLEAR).1, FW-11 read_error (RESTORE_REQUIRED).1, FW-11 read_error (RESTORE_REQUIRED).3 | - |
| NC-FW11-2 | fw_guards | the Free Power malformed-marker lockout removed: a wrong-size or bad-magic record reads as CLEAR (C7, FW:526-531); wrong size | checks: FW-11 wrong_size (CLEAR).1, FW-11 wrong_size (RESTORE_REQUIRED).1, FW-11 wrong_size (RESTORE_REQUIRED).3 | - |
| NC-FW11-3 | fw_guards | C7 with a bad-magic record | checks: FW-11 bad_magic (CLEAR).1, FW-11 bad_magic (RESTORE_REQUIRED).1, FW-11 bad_magic (RESTORE_REQUIRED).3 | NC-FW11-2 |
| NC-FW11-4 | fw_guards | only the wrong-size term of the Free Power malformed-marker test removed (C7ws, FW:526) | checks: FW-11 wrong_size (CLEAR).1, FW-11 wrong_size (RESTORE_REQUIRED).1 | - |
| NC-FW11-5 | fw_guards | C7ws with a bad-magic record (the magic term of FW:527 stays) | checks: FW-11 bad_magic (survived(expected)) | NC-FW11-4 |
| AUDIT-M1 | fw_obligations | audit mutant M1: the PR41 dual-obligation boot check locks only the Dump domain (the Free Power corrupt assignment removed, firmware :1146); also killed in fw_durability (FW-05) and ha_phantom; it survives PB-01 | checks: FW-01: the FULL on_boot's PR41 check locks BOTH domains at every boot (killed(audit)) | - |
| AUDIT-M2 | fw_obligations | audit mutant M2: the PR41 dual-obligation boot check locks only the Free Power domain (the Dump corrupt assignment removed, firmware :1147); also killed in fw_durability (FW-05) and ha_phantom; it survives PB-01 | checks: FW-01: the FULL on_boot's PR41 check locks BOTH domains at every boot (killed(audit)) | - |
| NC-HF01-1 | ha_schedules | firmware Free Power watchdog end condition shifted +60 s | INV-HF-WINDOW | - |
| NC-HF01-2 | ha_schedules | firmware Dump watchdog end condition shifted +60 s | INV-HF-WINDOW | - |
| NC-HF01-3 | ha_schedules | SMR1's Free Power track saves the schedule's value instead of the owner's | INV-HF-NO-FALSE-SUCCESS | - |
| NC-HF04-1 | ha_schedules | the Free Power START gate without its Dump ownership conjuncts (the kill depends on the scheduler phase: phase_sensitive) | INV-HF-ONE-LEASE | - |
| NC-HF04-2 | ha_schedules | FPS1's 'already active' pre-check never matches (the kill depends on the scheduler phase: phase_sensitive) | INV-HF-NO-PRESS-INTO-LEASE | - |
| NC-HF06-1 | ha_schedules | SMR1's restore blocker without the Dump snapshot (the kill depends on the scheduler phase: phase_sensitive) | INV-HF-SMR1-QUIET | - |
| NC-HF06-2 | ha_schedules | the Dump watchdog's 'snapshot valid but not active' restore rule removed | INV-RESTORE-BOUND | - |
| NC-HF02-1 | ha_lifecycle | FPS1 fire automation: the on-time start never disarms the schedule after its run | INV-HF-OWNER-INTENT | - |
| NC-HF02-1b | ha_lifecycle | only the startup recovery's 'not armed any more' guard disabled (the start script's own cancel check still ends the run) | INV-HF-OWNER-INTENT (survived(expected)) | - |
| NC-HF02-2 | ha_lifecycle | FPS1 startup recovery: the write-enable turn-off after a restart never runs | INV-HF-ARM-OFF | - |
| NC-HF03-1 | ha_lifecycle | FPS1 no-answer proof: the attempt-counter equality dropped | INV-HF-PRESS-PROOF | - |
| NC-HF03-2 | ha_lifecycle | firmware on_boot: Free Power S3 boot restore request removed | INV-NO-RESUME | NC-FW04-1 |
| NC-HF03-3 | ha_lifecycle | firmware on_boot: Dump to Grid boot restore request removed | INV-NO-RESUME | NC-FW04-2 |
| NC-HF05-1 | ha_lifecycle | SMR1 restore blocker: the three Free Power ownership entities removed | INV-HF-SMR1-QUIET | - |
| NC-HF05-2 | ha_lifecycle | SMR1 Free Power track: an owner change while owed is never dropped | INV-HF-NO-FALSE-SUCCESS | - |
| NC-HF09-1 | ha_lifecycle | FPS1: continue_on_error removed from the scheduled START press (the press raises once) | INV-HF-ARM-OFF | - |
| NC-HF09-2 | ha_lifecycle | firmware START gate: the pass branch no longer disarms the Free Power write enable (the run's closing turn_off raises) | INV-HF-ARM-OFF | - |
| NC-HF09-2b | ha_lifecycle | only the firmware's own write-enable disarm removed, no service error, scheduled path only (the package's closing turn_off still ends the switch off); killed elsewhere on the owner-armed path (see above) | INV-HF-ARM-OFF (survived(expected)) | NC-HF09-2 |
| NC-HF09-3 | ha_lifecycle | SMR1 Free Power restore: the per-field read-back check of the result dropped (the power restore write raises) | INV-HF-NO-FALSE-SUCCESS | - |
| NC1a | ha_phantom | firmware PR41 Free Power / Dump check disabled (mirror a) | INV-NO-2ND-RESTORER | NC-FW01-1 |
| NC1b | ha_phantom | firmware PR41 Free Power / Dump check disabled (mirror b) | INV-NO-2ND-RESTORER | NC-FW01-1 |
| NC2b | ha_phantom | both Free Power lockout write guards removed (watchdog corrupt gate + restore-script precondition) | INV-LOCKOUT-QUIET | NC-FW01-2 |
| NC2b-wd | ha_phantom | only the Free Power watchdog corrupt gate removed (the remaining guard holds) | INV-LOCKOUT-QUIET (survived(expected)) | - |
| NC2b-rs | ha_phantom | only the Free Power restore-script corrupt precondition removed, watchdog path (no owner press: the watchdog's own corrupt gate, firmware :24119, still holds; the End path is NC2b-rs-end) | INV-LOCKOUT-QUIET (survived(expected)) | - |
| NC2b-rs-end | ha_phantom | only the Free Power restore-script corrupt precondition removed, with the owner's End / Force presses after the lockout boot (End & Restore runs the restore script unconditionally, firmware :23298-23299); the same mutation as NC2b-rs (one distinct mutation, two control checks) | INV-LOCKOUT-QUIET | NC2b-rs |
| NC3b | ha_phantom | SMR1 blocker loses its lease-active and snapshot-pending terms | INV-HF-SMR1-QUIET | - |
| NC4 | ha_phantom | harness: settled_events keeps the reloaded lease across a boot transient (an override held past its window must be flagged) | INV-HF-WINDOW | - |
| NC6a | ha_phantom | the Dump on_boot reads its stored marker as CLEAR | INV-BOOT-MIRROR | NC-FW04-3 |
| NC-HF08-1 | dst_rtc | DGS1 walk charge test != 'None' changed to == 'Never' | INV-DST-TOU-REFUSE | - |
| NC-HF08-2 | dst_rtc | firmware gate charge mask 0x0003 changed to 0x0000 | INV-DST-TOU-REFUSE | - |
| NC-HF08-3 | dst_rtc | Free Power end epoch + 600 s | INV-EPOCH-END | - |
| NC-RT01-1 | dst_rtc | Free Power watchdog RTC lock skip removed (the kill depends on the scheduler phase: phase_sensitive) | INV-RTC-WD-SKIP | - |
| NC-RT01-2 | dst_rtc | Free Power watchdog lock skip and the restore's correction_in_progress gate removed (the kill depends on the scheduler phase: phase_sensitive) | INV-RTC-NO-RESTORE-IN-LOCK | - |
| NC-RT02-1 | dst_rtc | rp.lease_active without dump_restore_requested | INV-RTC-LEASE-HOLD | - |
| NC-RT02-2 | dst_rtc | policy input cooldown_active forced true | INV-RTC-DRIFT-BOUND | - |
| NC-RT02-3 | dst_rtc | stall detector forced false | INV-RTC-STALL-SURFACED | - |
| NC-RT03-1 | dst_rtc | Dump watchdog RTC lock skip removed | INV-RTC-WD-SKIP | - |
| NC-RT03-2 | dst_rtc | Dump watchdog lock skip and the restore's correction_in_progress gate removed | INV-RTC-NO-RESTORE-IN-LOCK | NC-FW08-3 |
| NC-RT03-3 | dst_rtc | Dump START gate without !correction_in_progress | INV-RTC-START-LOCK | - |
| NC-PB01-a | property | Free Power START admission without its two cross-domain Dump terms | INV-ONE-LEASE | NC-HF04-1 |
| NC-PB01-b | property | S3 removed: a persisted ACTIVE lease no longer forces restore_requested at boot | INV-NO-RESUME | NC-FW04-1 |
| NC-PB01-c | property | Dump START commits a CLEAR marker instead of RESTORE_REQUIRED (must stay unclassified) | INV-NO-SILENT-OVERRIDE | - |
| NC-PB01-d | property | Dump on_boot ignores a stored RESTORE_REQUIRED marker (reads it as CLEAR) | INV-BOOT-MIRROR | NC-FW04-3 |
| NC-PB02-a | property | Free Power watchdog ends the lease 300 s after its end epoch | INV-HF-WINDOW | - |
| NC-PB02-b | property | SMR1's blocker ignores Free Power Active / Snapshot Valid | INV-HF-SMR1-QUIET | - |
| NC-PB03-a | property | oracle with BST ending one week after the last Sunday of October | INV-TZ-ORACLE | - |
| NC-PB03-b | property | lab clock with the repeated-hour folds swapped | INV-TZ-FOLD | - |
| NC-PB03-c | property | one event t_utc moved 5 s back | INV-UTC-MONOTONIC | - |
| NC-PB03-d | property | a per-instance millis() without the 32-bit mask | INV-MILLIS-WRAP | - |
| NC-RC-40 | replay_corpus | CHANGELOG.md plus one comment line, a non-behavioural file: section [5] prints its SOURCE DRIFT (non-behavioural) line and adds no failure, its anchor still exactly once; the same edit fails in strict mode | checks: gen_catalogue drift rule (tiered) (survived(expected)) | - |
| NC-RC-41 | replay_corpus | firmware/ecco_clock_dongle_stage3_4_free_power.yaml plus one comment line, a behavioural file: section [5] fails with the one named check listing the corpus documents that replay it and the re-record procedure | checks: gen_catalogue drift rule (tiered) | - |
| NC-RC-42 | replay_corpus | registry/rtc_policy.py plus one comment line, a behavioural file pinned from V0.1 on: section [5] fails with the one named check listing the corpus documents that replay it and the re-record procedure | checks: gen_catalogue drift rule (tiered) | - |
| NC-RC-43 | replay_corpus | registry/tests/assurance_lab/run_lab.py plus one comment line, a lab file no corpus document pins: section [5] fails with exactly the one added check 're-generate the catalogue: lab file changed' naming the file and the regeneration command | checks: gen_catalogue drift rule (tiered) | - |
| NC-RC-44 | replay_corpus | a copy of corpus FW-06-a with one of its tier's TIER_SOURCES pins (firmware/include/ecco_durable_snapshot.h) removed from its source_digests: gen_catalogue's build names it ('does not pin 1 of its tier's TIER_SOURCES') and the section [2] tier-pin short-list names it | checks: B1 tier pins | - |
| NC-RC-45 | replay_corpus | SAFETY.md taken out of the B1 tier table for the control (restored afterwards) plus one comment line, a pinned file in neither tier: section [5] fails with exactly the one added check 'unclassified pinned source changed' (judged behavioural until classified) | checks: gen_catalogue drift rule (tiered) | - |

The three random-search PB-01 controls (NC-PB01-a, -b and -d) also show that `ddmin` shrinks each planted violation to at
most 3 actions (2 actions each in this baseline; NC-PB01-c is a fixed directed trace and is not shrunk); NC-PB01-a also
exercises the counterexample report path (section 2.8).

**Harness self-tests.** The four self-test suites (775 quick checks: 259 core, 262 firmware, 148 rtc, 106 coupling) check the
harness before any scenario relies on it. Among them:

- the Modbus outcome allow-list rejects a typo before anything runs (firmware and rtc tiers); an unknown entity id raises; an unset
  ALWAYS_OFF arm reads OFF and a START without arming is refused with the firmware's own arm text;
- the London clock agrees with both oracles every 15 min of 2026-2027 and per second around the four changes; the sweep comparators
  themselves have negative controls; without a tz database each zoneinfo comparison is printed as SKIPPED and LAB-SUMMARY
  reports `zoneinfo: false`;
- every invariant checker catches a hand-built violating log and passes its clean twin;
- the EventLog digest changes when a single event changes; a replay with an altered expectation fails; the drift rule prints
  `SOURCE DRIFT` for a changed source;
- every `KNOWN_RISKS` anchor occurs exactly once in its public file;
- same seed and actions give an identical digest (determinism); a D1Sim reboot is refused; an unmapped dongle entity raises; any
  mutation inside a projected transaction fails loud;
- the tier table and the run-time import guard (core [11b]); the suite output contract (`_lab_trace.finish`, `failed_line`,
  `unsupported_line`; core [12]); the bytecode guard of every suite and tool (core [13]);
- the NVS used-key rule: each refused commit mode and boot fault on a never-stored key, each with its accepted twin on a used
  key, and every commit-mode capability on a used key (firmware [8], [8b]);
- the HL-1 rule: the lab ORIGINAL adopts the bank only after a successful Accept that cleared the domain's own obligation,
  never for another domain's registers, each case with the V0 rule run in memory as its control (firmware [16d]);
- the coupled fail-loud probes: a Dump START inside a `no_response` / `timeout` projection gap (ISS-HA-2) and a press of a
  script that is busy only through a nested `script.execute` (MISS-HA-1) raise `LabUnsupported`; an in-lock `delay:` extends
  the window; a package option the interpreter ignores is refused at load; template truthiness and `input_number` ranges are
  guarded (coupling [15] to [18]);
- a `record()` failure in a self-test suite (for example after a production fix) becomes a named FAIL, and the suite still
  prints its FAILED line and LAB-SUMMARY (firmware, coupling, rtc); since the V0.1 review the self-tests also hold up
  under an ESPHome-like phase patch: the firmware self-test's two same-tick watchdog checks fail with a tag (detail `jobs at
  15 s: [...]`) instead of raising a ValueError, and when `record()` fails the RTC self-test records the same draft again
  without its timeline-bound `lock_windows` expectation and runs its round trip and five replay-engine controls on that
  document (if that fails too, each of the six prints a FAIL `not run: record() failed`); the plain-run output is
  unchanged;
- the run-time import guard at the end of every suite (`_lab_trace.finish`, section 2.8; NC-RC-48 below).

The scenario suite `test_lab_property` holds up the same way: a harness exception in a corpus replay becomes that
document's FAIL (`<id>: replay ok (...) - not completed: harness exception`, plus `finding-reproduces:<label> (<id>: not
run: its replay raised)` for a FINDING document, so its pin never disappears without a line) and the suite continues.

**Harness controls of `test_lab_replay_corpus`.** It runs 49 harness negative controls, NC-RC-1 to NC-RC-49, all passing:

- NC-RC-1 to NC-RC-17 (V0): an altered expectation fails its replay (`NC-RC-1`); an altered action list changes the digest
  (`NC-RC-2`); an unknown key is rejected by the schema (`NC-RC-3`); a changed recorded source digest prints SOURCE DRIFT, is
  judged on its expectations only and is flagged as unexplained drift and by the corpus / baseline digest cross-check
  (`NC-RC-4`); a missing corpus file, a document owned by two scenarios, a wrong classification, a flipped counted flag and a
  changed lab-file baseline digest are each detected by the catalogue cross-checker (`NC-RC-5` to `NC-RC-9`); a changed
  non-lab baseline digest (`CHANGELOG.md`) is drift and not a baseline problem, and in strict mode asks to re-generate the
  catalogue (`NC-RC-10`); a merged variant (now F-HF07-2) relabelled as a printed duplicate and a `confidence_level` that
  contradicts its confidence text are detected (`NC-RC-11`, `NC-RC-12`); a CRLF working copy passes the LF / canonical checks
  while a lone CR or a non-canonical body fails (`NC-RC-13`); a 13-digit run outside a sha256 digest, and a meter word on a
  line whose digest holds one, are detected (`NC-RC-14`); a harness limitation whose anchor no longer occurs in its file and a
  required intersection whose `required` flag is cleared are detected (`NC-RC-15`, `NC-RC-16`); a committed catalogue with a
  stale scenario entry is reported out of date by the generator's check, while a changed runtime value alone is only a note
  (`NC-RC-17`). Since V0.1, `NC-RC-1` and `NC-RC-4` run on the expectations of their control document (FW-06-a) that hold on
  the tree under test, so they do not depend on its timeline-bound expectation (section 2.5).
- NC-RC-18 to NC-RC-37 (V0.1 output contract and tools): `run_lab.judge` and `gen_catalogue.suite_output` accept a clean
  synthetic output (LF and CRLF) and reject, each with its own reason, an extra PASS line, an extra finding pin, a FAIL line
  at exit code 0, a hard-coded unsupported count, removed UNSUPPORTED lines, ids counted as points, a missing or misplaced
  FAILED line, a FAILED line without a failure and garbled LAB-SUMMARY records; the generator does not judge the replay
  suite's own FAIL lines but does judge its counts; the 90 s budget is a problem only for sequential outputs; catalogued
  UNSUPPORTED ids are required in the mode they belong to; the runner's LAB-SUMMARY key tuple equals `_lab_trace`'s;
  `rerecord_corpus.stale_report` flags a stale pinned digest.
- NC-RC-38 and NC-RC-39: a phase-sensitive scenario without its reason, and a `checks:` target naming no scenario of its
  suite, are detected.
- NC-RC-40 to NC-RC-45 (B1, end to end): the tiered drift rule over an in-memory overlay of the tree; NC-RC-40 survives as
  expected (a non-behavioural edit), NC-RC-41 and NC-RC-42 are killed (a behavioural edit of the firmware or of
  `registry/rtc_policy.py`; their expected document list is computed independently from the corpus JSON and
  `TIER_SOURCES`), NC-RC-43 is killed (a lab file no corpus document pins), NC-RC-44 is killed (a corpus document without
  one tier pin) and NC-RC-45 is killed (a pinned file in neither tier). These six are also catalogued negative-control rows
  (section 2.8).
- NC-RC-46 to NC-RC-49 (since the V0.1 review; uncatalogued, like NC-RC-1 to NC-RC-39): a missing pinned file is a
  failure of the shared drift rule in every tier, in both modes, and the generator's `compare()` path names a deleted
  non-behavioural file as `pinned source missing` with no drift-rule PASS (`NC-RC-46`);
  `gen_catalogue.tree_record_problems` refuses suite outputs without a record of the tree they ran on and outputs whose
  recorded digest of a pinned source differs from the tree, and accepts a matching record (`NC-RC-47`, section 11);
  `_lab_trace.finish` prints one FAIL for a planted unclassified module, appends it to the suite's FAILURES list and
  counts it, refuses a tuple instead of that list, and adds nothing once the module is gone (`NC-RC-48`); a
  `same_mutation_as` chain is detected (`NC-RC-49`).

## 10. UNSUPPORTED items and scoped future validation

**UNSUPPORTED in V0.1.** The catalogue has 8 entries (its `unsupported`); none is counted as PASS. Units: an entry is one
catalogue id; a run prints one `  UNSUPPORTED  <id> ...` line per point it meets, and several points can share an id. Seven
ids are met in quick mode, at 9 points (HF-03-UNS-1 is met 3 times); the eighth, HF-04-UNS-EXT, is met only in extended
mode, where the run meets 8 ids at 19 points (section 3). `run_lab.py` and `gen_catalogue.py` require every catalogued id to
be printed in the mode it belongs to, and refuse a printed id the catalogue does not list for that suite.

| ID | Suite | What cannot be represented |
|---|---|---|
| FW-07-U1 | `test_lab_fw_runtime` | NTP loss after a first sync: only the first SNTP sync per boot is modelled (the firmware's invalid-clock fallback ends a lease once this boot's uptime reaches 300 s, `millis() >= ecco_free_power_invalid_clock_grace_ms`: an uptime bound, not a grace counted from the loss) |
| FW-08-E-U1 | `test_lab_fw_runtime` | an RTC lock longer than the 90 s deadline breaker: the RTC tick is not executed in the firmware tier |
| FW-08-U2 | `test_lab_fw_runtime` | a hold or leak of the shared write mutex by the FB Review / Save scripts: they and the FB housekeeping interval do not transpile |
| HF-03-UNS-1 | `test_lab_ha_lifecycle` | a dongle power cut inside the projected START transaction after the gate (data commit, marker commit, write 256, active commit) |
| HF-05-UNS-1 | `test_lab_ha_lifecycle` | an owner START press or write-enable command inside the schedule's projected START transaction |
| HF-05-UNS-2 | `test_lab_ha_lifecycle` | an owner number edit inside the firmware's projected Free Power restore transaction |
| HF-07/system-health | `test_lab_ha_phantom` | `home-assistant/packages/ecco_system_health.yaml` is not executable in the coupled world; its health states for the lockout chain are INFERRED |
| HF-04-UNS-EXT | `test_lab_ha_schedules` | extended mode only: 8 lease-tail gap x watchdog-phase points whose next schedule command falls inside a projected firmware transaction |

Two further ids are printed by code if they are ever met, and are not catalogued: `HF-01-UNS` (`test_lab_ha_schedules`) and
`PB-02-UNS` (`test_lab_property`). No run has met them; if one did, the runners would report it as an uncatalogued id.

Unexpected Home Assistant service exceptions are covered, not UNSUPPORTED: HF-09 runs them against the real firmware in the
interpreter's fault model (`S.ServiceError` raised before delivery, section 5, item 15). What that model leaves out (other
exception classes, a call that raises after delivery) is part of V-5 below. The corpus pins HF-09
only in its API-outage form; that is a harness limitation (HL-9, section 5.2), not an UNSUPPORTED item. The silent
divergences of section 2.7 are not UNSUPPORTED items either: the lab does not detect them when it meets them.

**Scoped future validation.** The questions below cannot be settled offline. Each is phrased as a possible future validation
request: an offline extension, or a supervised bench test on hardware that is not part of any installation. None is planned here,
and none needs a change to the lab's results to be meaningful.

| Request | Question | Possible form |
|---|---|---|
| V-1 | Can a Phase-B marker commit report failure after the record landed (false negative), or success without storing (false positive), and how often? | supervised bench test on a spare ESP32 with the vendored ESPHome, injected NVS / flash faults, no inverter |
| V-2 | In which order and with which phase do the firmware's intervals (both 15 s watchdogs) really run after a boot, given ESPHome's random first-run offsets (HL-10)? | bench ESP32 with timing logs, no inverter |
| V-3 | How does real Home Assistant resolve an `input_datetime` in the repeated and the missing hour, and does a time trigger fire once or twice? | offline Home Assistant core test environment, no dongle |
| V-4 | When does an inverter switch its TOU slots across a clock step, before and after ECCO's RTC correction? | supervised bench test with a test inverter, or vendor documentation |
| V-5 | How often does Home Assistant save restore-state, and what does a crash roll back? How long is the ESPHome reconnect gap, and does a service call to an unavailable ESPHome entity fail or get dropped (the lab's `offline_policy`)? Which exceptions can a dongle service call raise, and can a call raise after it was delivered (HF-09 models only `S.ServiceError` before delivery)? | offline Home Assistant instance with a simulated ESPHome device |
| V-6 | What happens on a power cut inside an NVS write (a torn record) or inside a Modbus frame? | offline extension of `_dump_sim.py` with sub-event cut points, then a supervised bench test |
| V-7 | Does the compiled `ecco_rtc_policy.h` match the Python mirror for the DST cases here? | run `registry/tests/test_rtc_policy.py` where a C++ compiler is found (`ECCO_CXX`, else `g++`, `c++` or `clang++` on `PATH`) |
| V-8 | Can the interleavings the coupled tier refuses (UNSUPPORTED above), and the silent divergences of section 2.7, happen, and what do they do? | an offline asynchronous scheduler and script model for ds.Sim, replacing the projection |
| V-9 | What do the system-health package's checks report for the lockout chain? | offline extension that executes `ecco_system_health.yaml` in the coupled world |
| V-10 | How does ESP-IDF 5.5.5 behave after `ESP_ERR_NVS_REMOVE_FAILED` (which copy is read at the next boot; does the page go INVALID), how are duplicate entries resolved, and does a data-CRC read error persist? This decides the device reachability of every finding that rests on an injected NVS primitive (section 4) | the ESP-IDF host (Linux) NVS test, offline, outside the lab |

## 11. Adding a scenario, re-recording, and SOURCE DRIFT

**Add a scenario.**

1. Pick the tier and the suite (or a new `registry/tests/assurance_lab/test_lab_<family>.py`, which CI then picks up). A new suite
   follows the skeleton of the existing ones: `sys.dont_write_bytecode = True` before the first non-standard-library import
   (`test_lab_selftest_core` [13] checks it), a local `check()` that routes a held `finding-reproduces:` check to the pin list,
   `FAILURES`, an `  info  mode: quick|EXTENDED` line, every check before exactly one exit gate, UNSUPPORTED points printed
   with `_lab_trace.unsupported_line(<catalogue id>, text)`, a `PHASE_SENSITIVE_TAGS` registry closed by
   `check_phase_registry()`, and a final `_lab_trace.finish(SUITE, passes=..., failures=..., finding=..., finding_pins=...,
   unsupported_points=..., blocked=..., phase_sensitive=..., runtime_s=...)`, after which nothing is printed. Never import
   another `test_*.py` file; copy a small helper and credit its source instead.
2. Add the scenario to the suite's SCENARIOS table: ownership assumptions, exact source anchors (text that occurs exactly once;
   re-counted at run time), the expected invariant, the failure outcome, classification, grade and confidence.
3. Use only synthetic values (the lab `SITE`, synthetic dates). Store epochs in seconds. Avoid the privacy shapes the repository
   scan rejects (no addresses, no user paths, no e-mail addresses, no 13-digit numbers, no six 2-digit groups). An injected NVS
   fault needs a completed-lease prelude of its domain (section 2.4).
4. A reproduced deviation becomes a FINDINGS entry with a `FINDING` line, a `finding-reproduces:<id>` check, a severity,
   reachability, model dependence and a smallest safe repair scope (described, never implemented). If its root cause is already
   owned, mark it `DUPLICATE of <owner>` so it is not counted twice. A timing-bound check gets a phase-sensitivity tag with
   its reason.
5. Add at least one negative control: an in-memory mutation of the guard the scenario relies on, asserted to fail with the
   expected invariant id (or named checks) and no harness exception.
6. Record a corpus document: write the draft (id, tier, world, actions, expectations, anchors, `scenario_priority`,
   `finding_priority`) by hand or from a scratch script outside the repository, call `_lab_trace.record(draft,
   tier_pins=True)` and save `_lab_trace.dumps_doc(doc)` as `registry/tests/assurance_lab/corpus/<ID>-<n>.json`. Tests never
   write corpus files at run time.
7. Add the hand-written catalogue fields to `registry/tests/assurance_lab/_catalogue_data.py`: the scenario's result summary, a
   verification summary per finding, the two-axis verdicts and injected primitive of each finding (`VERDICTS`, `PRIMITIVES`),
   the root-cause group with its notes, the negative controls, the phase-sensitivity entry, the coverage entries and any
   UNSUPPORTED item or harness limitation. A new suite also goes into the generator's `SCENARIO_SUITES` list and needs a
   reader block in `gen_catalogue.py`. Update `LAB_SUMMARY_FINDING` in `test_lab_replay_corpus.py` if a suite's counted
   findings changed. A new non-lab file the lab reads goes into the tier table (`_lab_trace.BEHAVIOURAL` or
   `NON_BEHAVIOURAL`, and `TIER_SOURCES` when a replay executes it); `trace_inputs.py` (below) shows any read the table
   misses. Then regenerate the catalogue with `gen_catalogue.py --write` (below), in the same reviewed change.
8. Run every lab suite (`run_lab.py`) and confirm the catalogue cross-checks pass, refresh
   `docs/dev/assurance-lab-v0/LAB_SUMMARY.txt` with the invocation it names, and update the counts in this document
   (section 14 lists every headline number).

**Regenerate the catalogue.** `SCENARIO_CATALOGUE.json` is generated by `registry/tests/assurance_lab/gen_catalogue.py`, never
edited by hand. Regenerate it in the same change as **any change to a lab file**: a suite, a helper, a tool, the generator's
helper modules, or a corpus document (new or re-recorded). Until then `test_lab_replay_corpus` fails on its baseline pins (a
changed or unpinned lab file) and on its generator check. A change to a non-lab file needs it only when the file is
behavioural, after the corpus documents that replay it are re-recorded (the re-record procedure below); a changed
non-behavioural file needs nothing, and regenerating only brings the baseline back in step.

```sh
export PYTHONDONTWRITEBYTECODE=1
python -B registry/tests/assurance_lab/gen_catalogue.py --check                # run every lab suite (quick), build, compare
python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1   # the same, sequentially, then write SCENARIO_CATALOGUE.json
python -B registry/tests/assurance_lab/gen_catalogue.py --static --check       # no suite run: the static parts only
python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1 --save-runs DIR   # also keep the outputs in DIR
python -B registry/tests/assurance_lab/gen_catalogue.py --write --runs-from DIR   # from outputs saved on this tree
```

- **Inputs.** The suites' tables (SCENARIOS, FINDINGS, anchors and so on), evaluated statically from their source by
  `_catalogue_ast.py`: a suite is never imported or executed by the generator. The corpus documents. The hand-written fields in
  `_catalogue_data.py` (tiers, invariants, result summaries, verification summaries, two-axis verdicts and injected
  primitives, re-classification records, root causes with their tagged notes, phase sensitivity, negative controls,
  UNSUPPORTED items, harness limitations, coverage matrix). The tier table in `_lab_trace.py`. Every lab suite's quick-run
  output (the LAB-SUMMARY counts and runtime, the FINDING / DUPLICATE / merge lines, the UNSUPPORTED lines, the
  negative-control outcomes).
- **Runs.** By default the generator runs the 14 lab suites itself through `run_lab.py`'s runner, one at a time (`--parallel 1`
  by default, so each `runtime_quick_s` is an uncontended quick runtime; about 5.5 min on the development PC). `--runs-from DIR`
  reads saved outputs `DIR/<suite>.txt` instead; `--save-runs DIR` keeps the outputs, with a saved-runs record
  `DIR/_runs.json`, in a directory outside the repository (a directory inside it is refused). The record (schema
  `ecco-assurance-lab-saved-runs/v2`) holds the `--parallel` value, each suite's exit code and `sources`: the LF-normalised
  sha256 of every file a catalogue baseline can pin (every lab `.py` file and corpus document, every file the tier table
  pins, every corpus pin), taken before the suites run. Saved outputs count as sequential only when that record says
  `parallel` 1 (`--runs-sequential` asserts it and refuses a record that says otherwise). The generator is standard library
  only and never imports a `test_*.py` file.
- **The tree the suites ran on.** The catalogue is built only from suite outputs that belong to the tree being built, so a
  changed file that no corpus document pins (a behavioural file such as `tools/fbd1_soak/timeutil.py`, say) cannot be
  re-baselined from outputs made before the change. `--runs-from` refuses a directory without the record (`--runs-from:
  <dir>/_runs.json is missing: saved outputs that carry no record of the tree they ran on are refused (save them with
  gen_catalogue.py --save-runs DIR)`), an older v1 record (`--runs-from: _runs.json is a v1 record without the tree
  digests ('sources'): ...`) or a malformed one, with exit 1 before anything is built. The build then refuses outputs whose
  record differs from the tree: `the suite outputs were made on another tree: <n> pinned source(s) differ from their
  saved-runs record (<paths>): re-run the suites on this tree (gen_catalogue.py --write runs them; or --save-runs DIR, then
  --runs-from DIR)`. A run made by the generator itself records the tree just before the suites start.
- **Checks.** Public-text rules on every prose field (no review-process wording, no overclaim, no event date outside a cited
  file path, the runner's privacy shapes); every anchor exactly once; the lab vocabulary; corpus ownership, each finding
  document's classification, grade and confidence, and every document's `scenario_priority` / `finding_priority`; root-cause
  groups, duplicates, merges and tagged notes; the two-axis verdicts and the NVS reachability-text prefix; the
  re-classification records; invariants and their checkers; known risks; negative controls (in the suite source, their
  outcomes in the run, and every named check of a `checks:` target held in the plain run); phase-sensitivity entries against
  the suites' registries; coverage files and scenarios and the nine required intersections; harness-limitation anchors and
  workaround suites; the tier table; every corpus document's pins against this tree; each suite's output against the V0.1
  output contract; counted findings per suite against LAB-SUMMARY; every catalogued UNSUPPORTED id printed in its mode; every
  quick runtime within 90 s for sequential outputs. A problem is printed and nothing is written. A short table in the generator
  (`PUBLIC_TEXT_REPLACEMENTS`) rewrites a few exact suite phrases into the catalogue's public wording; an entry whose phrase no
  longer occurs (its suite was reworded) is reported as a problem, so the table shrinks in the same change.
- **Modes.** `--check` compares a fresh build with the committed file: the runtime values are wall-clock and excluded (printed as
  notes), the pinned digests are judged by the tiered drift rule (section 2.8), and everything else must be identical. `--write`
  writes `SCENARIO_CATALOGUE.json` (ASCII, LF) only when there is no problem and the outputs came from a run or `--runs-from`,
  never with `--static`; it also refuses a corpus document that records a digest other than this tree's (`corpus
  document(s) record a <path> sha256 that is not this tree's (<n>: <ids>): <re-record procedure>`; re-record it first)
  and suite outputs made on another tree (above). `ECCO_LAB_STRICT_BASELINE=1` (the environment value `1` exactly; the
  generator has no command-line switch for it) makes `--check` apply the strict rule (section 2.8).
  `runtime_quick_s` is stored only from sequential outputs; with `--parallel N` above 1 the committed runtimes are kept. Nothing
  else is ever written. Exit 0 built (and written, or up to date), 1 a problem or an out-of-date catalogue, 2 a usage error.
  The generator prints `  info  built: <counts>` and `  info  two-axis verdicts: <distribution>`.
- **Who checks what.** `test_lab_replay_corpus` [5] runs the static check and the tiered drift rule only, and says so in its
  output: running the thirteen other suites inside it would exceed its 90 s budget, so negative-control outcomes, FINDING /
  DUPLICATE / merge lines, counted findings against LAB-SUMMARY and runtimes are not re-checked there. `run_lab.py`
  cross-checks the counts, FINDING lines and UNSUPPORTED ids against a fresh run of the suites; `gen_catalogue.py --check`
  checks all of it.

**Re-record a corpus document** after an intended source change, with `registry/tests/assurance_lab/rerecord_corpus.py`:

```sh
export PYTHONDONTWRITEBYTECODE=1
python -B registry/tests/assurance_lab/rerecord_corpus.py --check                     # which documents are stale
python -B registry/tests/assurance_lab/rerecord_corpus.py FW-01-a FW-01-b             # re-record these documents
python -B registry/tests/assurance_lab/rerecord_corpus.py --all                       # re-record every document
python -B registry/tests/assurance_lab/rerecord_corpus.py FW-06-a --allow-digest-change FW-06-a
python -B registry/tests/assurance_lab/rerecord_corpus.py --all --pin-tier-sources    # also pin each tier's TIER_SOURCES
```

The tool re-records each selected document from itself with `_lab_trace.record`: its `source_digests` (its own keys plus every
anchor path) and anchor lines are recomputed from the tree, it is replayed twice (both digests must agree and every expectation
must hold) and `trace_digest` is set from the replay. Nothing else in the document changes. When a document's `trace_digest`
would change, the tool prints `REFUSED <id>: trace_digest would change <old> -> <new>` and refuses, unless that id is passed in
`--allow-digest-change` (which takes one or more ids, each also selected; then it prints `ALLOWED <id>: trace_digest <old> ->
<new>`). An unchanged digest means the re-record only updated provenance (`update <id>: trace_digest unchanged`). Every allowed
change must be explained by its mechanism. All or nothing: a document that fails (`FAILED <id>`) or is refused means `NOTHING
WRITTEN` (exit 1). `--check` lists the documents whose recorded digests differ from the tree or whose anchors moved (`STALE`);
`--pin-tier-sources` is needed only for a new document or after `TIER_SOURCES` grows, because a re-record keeps the tier pins a
document already has. If an expectation no longer holds, the behaviour changed: go to "React to SOURCE DRIFT" below, or to
section 13 for a fix of a pinned finding.

**The re-record procedure** (what a tiered-drift FAIL asks for, doc section 11):

1. Run `python -B registry/tests/assurance_lab/run_lab.py` and confirm that the scenario outcomes and finding pins still hold.
2. Run `python -B registry/tests/assurance_lab/rerecord_corpus.py <ids named in the FAIL>` (or `--all`). Explain every
   `--allow-digest-change` by mechanism. The FAIL names `--all` when every document or more than 12 are affected; for a
   subset it says why: a re-record leaves the documents whose digests and anchors did not change byte-identical.
3. Run `python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1`. It must be sequential:
   `runtime_quick_s` is stored only from sequential runs. `--write` refuses a stale corpus pin.
4. Optionally run `ECCO_LAB_STRICT_BASELINE=1 python -B registry/tests/assurance_lab/test_lab_replay_corpus.py` to confirm that
   nothing is left drifted.

**React to SOURCE DRIFT.**

- The replay engine's `SOURCE DRIFT: <path>` means a file the document pins has changed; the replay is then judged on its
  expectations only. The catalogue-level `SOURCE DRIFT (non-behavioural): <path>` means a non-behavioural pinned file changed;
  that is not a failure, and every anchor in it is still checked exactly once (section 2.8).
- `gen_catalogue drift rule (tiered): behavioural source changed: <path>`: follow the re-record procedure above for the
  documents the message names, then regenerate.
- `gen_catalogue drift rule (tiered): re-generate the catalogue: lab file changed: <path>`: the same procedure, with the named
  documents first (or none, then only the regeneration).
- `gen_catalogue drift rule (tiered): unclassified pinned source changed: <path>`: classify the file in the tier table
  (section 2.8; `trace_inputs.py` gives the evidence), then follow the procedure for its tier.
- `gen_catalogue drift rule (tiered): pinned source missing: <path>` (or a tier title with `sha256 missing`): restore the
  file, or remove it from the lab (tier table, anchors, corpus pins) and regenerate.
- `gen_catalogue drift rule (STRICT): ...`: strict mode is on (`ECCO_LAB_STRICT_BASELINE=1`); a non-behavioural file
  changed, so re-record the named documents and regenerate, or run without the switch.
- `B1 import guard (end of suite): ...` in any suite: a repository module outside the lab was imported that the tier table
  does not list; classify it (below) and regenerate.
- An expectation or a `finding-reproduces` check fails: the behaviour changed. If the change was a fix, follow section 13. If
  it was not meant to change the behaviour, it is a regression: fix the change, not the expectation.
- A digest mismatch **without** SOURCE DRIFT is never accepted: the harness or a helper changed, or a world is not deterministic.
  Find the cause before re-recording anything.
- An `ANCHOR DRIFT` line means an anchor text moved or no longer occurs exactly once. Re-anchor on the new text only after
  checking that it still names the same construct.
- After re-recording and regenerating, a run with `ECCO_LAB_STRICT_BASELINE=1` checks that no pinned source and no document is
  left drifted.

**Keep the tier table in step.** A new import of a repository module outside the lab is caught by the run-time import guard
at the end of every suite (`_lab_trace.finish`, section 2.8): add the module to `BEHAVIOURAL` (and to `TIER_SOURCES` when a
replay executes it) and pin it by regenerating. A new data read of a non-lab file (opened, not imported), and an import
made only by `run_lab.py`, `gen_catalogue.py` or `rerecord_corpus.py`, is not caught by the guard: repeat the audit-hook
trace with the trace tool and update `BEHAVIOURAL` / `NON_BEHAVIOURAL` / `TIER_SOURCES` until it reports no mismatch.

```sh
export PYTHONDONTWRITEBYTECODE=1
python -B registry/tests/assurance_lab/trace_inputs.py                 # every suite (quick) and every corpus replay alone
python -B registry/tests/assurance_lab/trace_inputs.py --extended      # ... and every suite in extended mode too
python -B registry/tests/assurance_lab/trace_inputs.py --parallel 2    # processes at once (default 4)
```

It prints one `trace_inputs: ...` summary line per result (the processes traced, the non-lab files read per tier, the
behavioural read set of each tier's replays), one `MISMATCH: ...` line per difference from the table, and last `trace_inputs:
<n> mismatch(es) against _lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL / TIER_SOURCES`; exit 0 when the trace equals the table,
1 on a mismatch, 2 on a usage error. It writes nothing inside the repository (its hook module and logs live in a temporary
directory, removed at the end). A quick trace starts 129 processes (14 suites and 115 replays). `gen_catalogue.py` validates
the table's own consistency on every build.

## 12. PR-time Linux validation

The lab was built and measured on Windows (Python 3.12). It has never run on Linux. The first Linux evidence will be the CI
run of the pull request that adds it: GitHub's `ubuntu-24.04` runner, Python 3.12, the `offline-tests` job of
`.github/workflows/validate.yml` for the root `registry/tests`.

**What CI runs.** `tools/run_offline_tests.py --root registry/tests --parallel 2` runs every
`registry/tests/assurance_lab/test_lab_*.py` in quick mode as `python <file>` from the repository root, two suites at a time,
with a 7200 s timeout per suite. It adds neither `-B` nor `PYTHONDONTWRITEBYTECODE`; every lab suite sets
`sys.dont_write_bytecode = True` before its first non-standard-library import, so it writes nothing into the tree. On Windows
a CI-style run of the V0.1 tree with the W6-1c correction (all 14 suites as `python <file>`, no `-B`, the variable unset)
exited 0 for every suite and left a sha256 manifest of the 688 files of the tree unchanged; on Linux this is unverified
until the PR run. CI runs no extended mode, and the 90 s budget is not judged there (two suites share the runner).

**What a green CI run shows.** Every lab suite exits 0 on Linux. That covers each suite's own checks: every corpus document
replays with `digest == trace_digest` (the digest is the sha256 of canonical JSON, so it is platform independent and an exact
match is strong evidence that the simulators behave the same), every `finding-reproduces` pin holds, the phase-sensitivity
registry has no stale tag, and the static catalogue check and the tiered drift rule pass. A failing suite prints its last
20,000 characters, which end with `FAILED: <n> check(s): <names>` and the LAB-SUMMARY line.

**What it does not show.** `tools/run_offline_tests.py` prints a suite's output only when it fails, and the job summary records
only the result and the seconds per suite. A passing suite's LAB-SUMMARY line is therefore not in the CI log, and a count
difference that still exits 0 (for example `zoneinfo: false`, with the zoneinfo checks printed as SKIPPED) is invisible in a
green run. CI also never runs `run_lab.py`. **The per-suite comparison below is therefore UNVERIFIED** until one of these is
done (a decision outside the lab; neither is part of V0.1):

- a separately authorised run on a Linux host of `python registry/tests/assurance_lab/run_lab.py --parallel 2` from the
  repository root (its table prints every suite's LAB-SUMMARY values, and it exercises `run_lab.py`'s POSIX paths); or
- a separate, reviewed change to the CI tooling that keeps each passing suite's LAB-SUMMARY line in the log or the job
  summary (outside the lab's paths).

Until then a green CI run proves the exit codes and the trace digests only.

**Comparison procedure.** Compare each suite's LAB-SUMMARY line from the Linux run with the expected values below.

1. Mask `runtime_s`. Every other field must equal the expected value, with one documented exception: `zoneinfo`.
2. The `zoneinfo` delta. With a usable tz database (the expected case) `zoneinfo` is `true` and nothing differs. Without one,
   `zoneinfo` is `false`, the zoneinfo comparisons print `  info  SKIPPED (zoneinfo unavailable): ...`, and the exit code
   stays 0. Measured on Windows with the tz database hidden (every suite of the V0.1 tree with the W6-1c correction, as
   before it): `test_lab_selftest_core` prints
   7 SKIPPED lines and its `pass` drops from 259 to 253 (one skipped comparison is part of a check that still runs on the
   other oracles); `test_lab_property` prints 4 SKIPPED lines and keeps `pass` 65; every other suite is unchanged.
   `requirements-ci.txt` installs no `tzdata` package, so on the runner zoneinfo relies on the system tz database.
3. Any other difference (a pass, pin, finding, unsupported, blocked or phase-sensitive count) fails the validation and must be
   explained before the merge. A different trace digest already fails the suite.

**Expected LAB-SUMMARY values** (quick mode, `zoneinfo` true, `runtime_s` masked). They are the values of the sequential run
behind the catalogue's `runtime_quick_s` and equal those of `docs/dev/assurance-lab-v0/LAB_SUMMARY.txt`. For
`test_lab_replay_corpus` they are the values after the catalogue was written (inside a `--write` run it checks the catalogue
being replaced).

| Suite | pass | fail | finding | finding_pins | unsupported_ids | unsupported_points | blocked | phase_sensitive |
|---|---|---|---|---|---|---|---|---|
| `test_lab_dst_rtc` | 143 | 0 | 3 | 8 | 0 | 0 | 0 | 27 |
| `test_lab_fw_durability` | 97 | 0 | 8 | 15 | 0 | 0 | 0 | 15 |
| `test_lab_fw_guards` | 268 | 0 | 0 | 0 | 0 | 0 | 0 | 30 |
| `test_lab_fw_obligations` | 74 | 0 | 5 | 8 | 0 | 0 | 0 | 13 |
| `test_lab_fw_runtime` | 125 | 0 | 6 | 9 | 3 | 3 | 0 | 39 |
| `test_lab_ha_lifecycle` | 172 | 0 | 7 | 24 | 3 | 5 | 0 | 26 |
| `test_lab_ha_phantom` | 67 | 0 | 1 | 6 | 1 | 1 | 0 | 6 |
| `test_lab_ha_schedules` | 60 | 0 | 7 | 13 | 0 | 0 | 0 | 13 |
| `test_lab_property` | 65 | 0 | 0 | 6 | 0 | 0 | 0 | 18 |
| `test_lab_replay_corpus` | 314 | 0 | 0 | 0 | 0 | 0 | 0 | 230 |
| `test_lab_selftest_core` | 259 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `test_lab_selftest_coupling` | 106 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| `test_lab_selftest_firmware` | 262 | 0 | 0 | 0 | 0 | 0 | 0 | 16 |
| `test_lab_selftest_rtc` | 148 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |

**POSIX code that stays unexercised.** `run_lab.py` starts each suite with `start_new_session=True` on POSIX and kills a
timed-out suite's whole process group with `os.killpg` (`run_lab.run_one`, `run_lab._kill`). CI does not run `run_lab.py` (it
runs the suites through `tools/run_offline_tests.py`, which uses the same pattern in its own `run_one` / `_kill`), so the PR's
CI run does not exercise this code. Only a Linux run of `run_lab.py` or `gen_catalogue.py` does, and the kill path only on a
timeout. Until then it is unverified.

**Cost.** The quick suites took 331.3 s in all, one at a time, on the development PC (311.6 s for the same lab code
apart from its `PUBLIC_MAIN` base constant, before the re-base onto public main `a7235433`, 308.5 s before the W6-1c
correction, 314.2 s before the W6-1b correction, 307.9 s before the W6-1 correction). Hosted runners are slower and
shared, and CI runs two suites at a time, so the CI times are not comparable with section 3.

## 13. Developer workflow for a PR that fixes a pinned finding

**Why CI turns red.** Every reproduced finding is pinned three times: by its suite's `finding-reproduces:<id>` checks, by its
corpus documents (expectations and `trace_digest`) and by the catalogue (its finding, root-cause group, counts and baseline
digests). A production change that fixes a pinned finding changes that behaviour, so the pull request's CI run fails until the
lab's tables, corpus and catalogue are updated **in the same pull request**. The 2026-10-19 audit measured this on V0: a fix in
the style of RC-PR41-GHOST's repair (the RAM mirror set fail-closed at the Phase-B false branches) gave 138 FAILs in 6 suites.
Since V0.1 `test_lab_selftest_firmware` reports such a change as named FAILs instead of crashing without a LAB-SUMMARY.

Any change to a behavioural-tier source (section 2.8: the firmware, a package, a simulator, an imported registry module) also
fails `test_lab_replay_corpus` until the corpus documents that replay it are re-recorded and the catalogue is regenerated, even
when no finding changes. The failure names the file, the documents to re-record and the procedure
(`gen_catalogue drift rule (tiered): behavioural source changed: <path> - ...`). Steps 4 to 6 below are that procedure.

**Procedure.** Run everything from the repository root, offline, with bytecode writing off. Keep the production change and the
lab update in one reviewed change. Never change an expected value only to make a check pass: derive every new or changed
expectation from the changed production source and cite its lines.

```sh
export PYTHONDONTWRITEBYTECODE=1
```

```powershell
cls
$env:PYTHONDONTWRITEBYTECODE = "1"
```

1. **See what fails.** `python registry/tests/assurance_lab/run_lab.py --parallel 4`. Each failing suite ends with
   `FAILED: <n> check(s): <names>`. Sort the names:
   - `finding-reproduces:<id>` checks, and the corpus replays of that finding's documents: the pinned behaviour changed (steps
     2 to 4);
   - any other behavioural check: a regression unless the change intends it. Fix the change, not the expectation;
   - `test_lab_replay_corpus` drift-rule FAILs that name changed sources: steps 4 and 5;
   - `B1 import guard (end of suite): ...`: the change made the lab import a repository module the tier table does not
     list (section 11, "Keep the tier table in step");
   - "phase-sensitivity registry: ..." (a stale tag): a tagged check was renamed or removed (step 2).
2. **Re-classify the finding in its suite.**
   - In the suite's `FINDINGS` table, remove the fixed finding or re-classify it (usually its scenario becomes PASS; record a
     re-classified id in the suite's `RECLASSIFIED` table and in `_catalogue_data.RECLASSIFIED`), and update the duplicates
     other suites print for it (for example RC-PR41-GHOST's F-FW01-1 has the printed duplicates F-FW05-1, F-HF07-4 and
     F-PB01-1).
   - Replace each `finding-reproduces:<id>` check with a plain check of the fixed behaviour.
   - Update the suite's entry in `LAB_SUMMARY_FINDING` (`test_lab_replay_corpus.py`): its number of counted findings.
   - Update the suite's `PHASE_SENSITIVE_TAGS` for every renamed or removed tagged check; `check_phase_registry()` fails on a
     prefix that no executed check matches.
   - In the self-test suites, update any check that recorded the old behaviour (also with source citations).
3. **Update the catalogue's hand-written data** in `_catalogue_data.py`: the scenario's `RESULT_SUMMARY`; the finding's
   `FINDING_CORPUS`, `MODEL_DEPENDENCE`, `VERIFICATION`, `VERDICTS` and `PRIMITIVES` entries; `ROOT_CAUSES` (remove the member; a
   group left with no counted member is removed or re-scoped, and its notes go with it); `PHASE_SENSITIVE`; `NEGATIVE_CONTROLS`
   whose target names a removed check (a `checks:` target must name checks that hold in the plain run). If a suite phrase
   listed in `gen_catalogue.PUBLIC_TEXT_REPLACEMENTS` changed, update that table too.
4. **Re-record the corpus.**
   - List what is stale: `python -B registry/tests/assurance_lab/rerecord_corpus.py --check`.
   - For each document of the fixed finding, edit its `classification`, `expect` entries and `finding_priority` by hand to the
     fixed behaviour (each value derived from source), then re-record it and allow its digest change:
     `python -B registry/tests/assurance_lab/rerecord_corpus.py FW-01-a --allow-digest-change FW-01-a`. Put the ids before
     `--allow-digest-change`, which takes one or more ids, each of which must also be selected.
   - Re-record every other document: `python -B registry/tests/assurance_lab/rerecord_corpus.py --all`. A document whose
     source changed but whose behaviour did not is updated for provenance only (`trace_digest unchanged`). If any other
     document's `trace_digest` would change, the tool prints `REFUSED` and writes nothing: explain that behaviour change
     (another pinned finding, or a regression) before you add its id with `--all --allow-digest-change <id> ...`. A document
     whose expectations no longer hold fails (`FAILED <id>`); that is step 2 or 4 work, never a re-record.
5. **Regenerate the catalogue sequentially**, on an otherwise idle PC:
   `python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1`. It runs every lab suite in quick mode, stores
   the sequential runtimes and writes `SCENARIO_CATALOGUE.json` only when there is no problem. Then
   `python -B registry/tests/assurance_lab/gen_catalogue.py --static --check` must print `catalogue up to date (static parts)`.
6. **Run the lab and refresh the summary.**
   `python registry/tests/assurance_lab/run_lab.py --parallel 4 --write-summary docs/dev/assurance-lab-v0/LAB_SUMMARY.txt`
   must report `PASS: <n> of <n> suites ok and every catalogue cross-check holds` and exit 0. Then check that nothing is left
   drifted: `ECCO_LAB_STRICT_BASELINE=1 python -B registry/tests/assurance_lab/test_lab_replay_corpus.py` (PowerShell:
   `$env:ECCO_LAB_STRICT_BASELINE = "1"` first).
7. **Update this document**: the counts in sections 3, 4, 7, 8 and 9, the finding's section 8 entry, and the old-to-new
   reconciliation (section 14); recompute every number from the catalogue and the run.
8. **Commit** the production change, the suites, `_catalogue_data.py`, the corpus documents, `SCENARIO_CATALOGUE.json`,
   `LAB_SUMMARY.txt` and this document together. CI then runs every lab suite in quick mode.

## 14. Old-to-new reconciliation (V0 to V0.1)

Every headline number of V0, its unit, its V0.1 value and the correction item that changed it (B1 to B7, the items of
the 2026-10-19 audit's implementation brief; W6-1, the per-slot restore-verify correction after the independent re-check
of V0.1; W6-1b, its follow-up for the six regressions that survived W6-1; and W6-1c, the final correction cycle, for the
four containment-claim regressions that survived W6-1b). "Unit" says what one count is; numbers with different units are
never added. V0 values are those of the V0 catalogue, the V0 `LAB_SUMMARY.txt` and the V0 text of this document. V0.1
values include the W6-1, W6-1b and W6-1c corrections; where one of them moved a number, the last column also gives its
value before that correction.

| Number | Unit | V0 | V0.1 | What changed it |
|---|---|---|---|---|
| lab suites | `test_lab_*.py` suites | 13 | 14 | B3: `test_lab_fw_guards` (FW-09, FW-10, FW-11) |
| scenarios | catalogue scenarios (firmware / coupled / rtc) | 36 (23 / 10 / 3) | 39 (26 / 10 / 3) | B3: FW-09, FW-10, FW-11 |
| scenario labels | scenario headline labels PASS / FINDING-NEW / FINDING-KNOWN | 14 / 15 / 7 | 17 / 15 / 7 | B3: three PASS scenarios (HF-05 changed its KNOWN id, B6.3); labels are headlines, not finding counts (section 7) |
| finding ledger | catalogue finding entries | 52 | 51 | B6.3: F-HF05-1 re-classified as a documented limit and removed |
| counted findings | counted ledger entries (= the sum of LAB-SUMMARY `finding`) | 39 | 37 | B6.3: F-HF05-1 not counted; F-HF07-2 merged into F-HF07-1 |
| uncounted findings | ledger entries DUPLICATE / MERGED | 12 / 1 | 12 / 2 | B6.3: F-HF07-2 MERGED |
| counted by class | counted findings FINDING-NEW / FINDING-KNOWN | 25 / 14 | 24 / 13 | B6.3 |
| root-cause groups | groups (the defect count) | 32 | 31 | B6.3: RC-SMR1-OWNER-STAGING removed with its only member |
| group priorities | groups P1 / P2 / P3 | 3 / 7 / 22 | 1 / 7 / 23 | B6.3: RC-PR41-GHOST and RC-PR41-STRANDED-OVERRIDE P1 -> P2; RC-FP-NO-SG39-RETRY and RC-COMMIT-FALSE-POSITIVE P2 -> P3 |
| counted findings by group priority | counted findings in P1 / P2 / P3 groups | 7 / 9 / 23 | 3 / 9 / 25 | B6.3 |
| group classes | groups FINDING-NEW / FINDING-KNOWN | 20 / 12 | 20 / 11 | B6.3 |
| groups with more than one counted member | groups | 5 | 5 | B6.3: RC-PR41-STRANDED-OVERRIDE three -> two members |
| known risks | registered / used by classifications | 19 / 12 | 19 / 11 | B6.3: SMR1-OWNER-STAGING no longer used |
| mechanism verdicts | counted findings CONFIRMED / PLAUSIBLE | not stated | 34 / 3 | B6.4 two-axis verdicts |
| device reachability | counted findings VERIFIED / PLAUSIBLE / UNKNOWN / UNVERIFIABLE-OFFLINE / NOT-APPLICABLE | not stated | 0 / 20 / 12 / 4 / 1 | B6.4 |
| VERIFIED device reachability | counted findings | the audit: 0 of 39 | 0 of 37 | B6.4 |
| no product change needed | counted findings | the audit: at least 5 (F-FW05-2, F-FW07-3, F-HF05-1, F-HF01-1, F-HF06-1) | 6 of 37 (4 of the audit's 5, plus F-HF02-2 and F-HF05-2) | B6.4; B6.3: F-HF05-1 left the ledger (section 4) |
| injected NVS primitive | counted findings resting on an injected NVS primitive | the audit: 18 of 39 (does not reproduce; V0 recount 15 of 39) | 14 of 37 | B5.5, B6.4 (section 4) |
| any injected fault primitive | counted findings resting on any injected fault primitive | V0 recount 29 of 39 | 28 of 37 | B6.4 (section 4) |
| pass (quick) | checks held, excluding finding pins | 1683 | 2160 | B3 (`test_lab_fw_guards`), B4 (self-tests, NC2b-rs-end, the phase registry check in every suite), B5 (preludes, [8b], the PB-01 fault scan), B6 (runner controls NC-RC-18 to NC-RC-39, register checks), B1 (tier checks, NC-RC-40 to NC-RC-42), the V0.1 review (NC-RC-43 to NC-RC-49); W6-1: +64 (+52 in `test_lab_fw_guards`, +12 in `test_lab_replay_corpus`; 1964 before); W6-1b: +75 (+61 in `test_lab_fw_guards`, +14 in `test_lab_replay_corpus`; 2028 before); W6-1c: +57 (+47 in `test_lab_fw_guards`, +10 in `test_lab_replay_corpus`; 2103 before) |
| `test_lab_fw_guards` checks (quick) | pass of `test_lab_fw_guards` | - (no such suite) | 268 | B3: the new suite (108); W6-1: +52 (30 b3 checks, 8 control checks, 6 corpus replays, 8 discrimination checks); W6-1b: +61 (34 b4, b5 and b6 checks, 6 control checks, 7 corpus replays, 14 discrimination checks); W6-1c: +47 (30 b7 checks, 1 containment-claim check, 4 control checks, 5 corpus replays, 7 discrimination checks) |
| finding pins (quick) | held `finding-reproduces:` checks, not in pass | 90 (not reported) | 89 | B6.1: reported as `finding_pins`; B6.3: the F-HF05-1 pin became a plain check |
| checks held (quick) | pass + finding pins | 1773 (not reported) | 2249 | B6.1; W6-1: +64 (2053 before); W6-1b: +75 (2117 before); W6-1c: +57 (2192 before) |
| fail (quick) | failed checks | 0 | 0 | - |
| UNSUPPORTED (quick) | V0: the sum of each suite's distinct ids, called "constructs"; V0.1: ids and points | 7 | 7 ids at 9 points | B6.1: ids and points reported separately (HF-03-UNS-1 is met 3 times) |
| UNSUPPORTED (extended) | V0: ids and points mixed; V0.1: ids and points | 15 | 8 ids at 19 points | B6.1: V0 `ha_lifecycle` reported 3 while printing 7 lines and `ha_phantom` hard-coded 1 |
| UNSUPPORTED entries | catalogue entries | 8 | 8 | - |
| blocked | scenarios | 0 | 0 | - |
| phase-sensitive checks | executed tagged checks, quick / extended | not measured | 442 / 503 | B4.7; the V0.1 review (the HF-03 whole-site cut grid, the F-HF03-2 pins and the finding register of `test_lab_ha_lifecycle`); W6-1: +18 in each mode (the six new trace-digest pins of `test_lab_fw_guards` and the 12 replay checks of the new documents; 388 / 449 before); W6-1b: +21 in each mode (the seven new trace-digest pins of `test_lab_fw_guards` and the 14 replay checks of the new documents; 406 / 467 before); W6-1c: +15 in each mode (the five new trace-digest pins of `test_lab_fw_guards`, tagged by five new `PHASE_SENSITIVE_TAGS` prefixes, 195 -> 200, and the 10 replay checks of the new documents; 427 / 488 before) |
| phase-sensitive entries | catalogue scenarios / findings flagged | not measured | 21 of 39 / 18 of 51 | B4.7; the V0.1 review (F-HF03-2, and F-FW05-2, F-FW06-1, F-FW07-5, F-HF05-2 for their timeline-bound corpus FINDING documents) |
| zoneinfo | suites reporting a usable zoneinfo | not reported | 14 of 14 | B7.3 |
| corpus documents | replay documents | 85 | 115 | B3: 12 new (FW-09-a, b, b2, c, c2; FW-10-a..c; FW-11-a..d); W6-1: 6 new (FW-09-b3-256 to FW-09-b3-261; 97 before); W6-1b: 7 new (FW-09-b4-ct, b4-cb, b4-co, b5-lo, b6-ok, b6-x257, b6-x260; 103 before); W6-1c: 5 new (FW-09-b7-rbnr, b7-rber, b7-cmnr, b7-ab, b7-af; 110 before) |
| pinned sources | catalogue `baseline.sources` (lab + non-lab) | 144 (106 + 38) | 195 (140 + 55) | B3, B5: new lab files and documents; B1: 17 run-time inputs newly pinned; the V0.1 review: `test_lab_replay_corpus.py` pinned (`LAB_RULE`) and the new `trace_inputs.py`; W6-1: the six new corpus documents (before: 177, 122 + 55); W6-1b: the seven new corpus documents (before: 183, 128 + 55); W6-1c: the five new corpus documents (before: 190, 135 + 55) |
| non-lab tiers | pinned non-lab files behavioural / anchor-read non-behavioural | not tiered | 27 / 28 | B1 (plus 20 existence-only citations, unpinned) |
| invariants | catalogue entries (firmware / coupled / rtc) | 48 (24 / 17 / 7) | 48 (24 / 17 / 7) | - |
| negative controls | catalogue rows (control checks) | 73 | 115 | B3: 15 `test_lab_fw_guards` rows, NC2b-rs-end, AUDIT-M1 / M2; B1: NC-RC-40 to NC-RC-42; the V0.1 review: NC-RC-43 to NC-RC-45; W6-1: NC-FW09-6 to NC-FW09-13 (97 before); W6-1b: NC-FW09-14 to NC-FW09-19 (105 before); W6-1c: NC-FW09-20 to NC-FW09-23 (111 before) |
| negative-control outcomes | killed / survived(expected) / killed(audit) / invalid | 69 / 4 / - / 0 | 105 / 8 / 2 / 0 | B3, B1, the V0.1 review; W6-1: 8 killed (87 / 8 / 2 / 0 before); W6-1b: 6 killed (95 / 8 / 2 / 0 before); W6-1c: 4 killed (101 / 8 / 2 / 0 before) |
| harness controls | `NC-RC-<n>` in `test_lab_replay_corpus` | 17 | 49 | B6.2 (NC-RC-18 to NC-RC-37), B4.7 (NC-RC-38, NC-RC-39), B1 (NC-RC-40 to NC-RC-42), the V0.1 review (NC-RC-43 to NC-RC-49) |
| harness limitations | catalogue entries (open) | 9 (9 open) | 13 (11 open) | B4.6: HL-1 fixed at the root; B5: HL-6 fixed by a lab-side refusal; B4.1: HL-10 to HL-13 added |
| self-test checks (quick) | pass of the 4 self-test suites (core / firmware / rtc / coupling) | 701 (237 / 228 / 147 / 89) | 775 (259 / 262 / 148 / 106) | B1, B4, B5, B6, B7 self-tests |
| replay-suite checks (quick) | pass of `test_lab_replay_corpus` | 216 | 314 | B3 documents, B6.2 controls, B1 tier checks and controls, the V0.1 review's controls; W6-1: two replay checks per new document (278 before); W6-1b: two replay checks per new document (290 before); W6-1c: two replay checks per new document (304 before) |
| intersections | catalogue intersections (required) | 19 (9) | 19 (9) | - |
| quick runtime | s, the sum of the catalogue's `runtime_quick_s` | 263.4 | 331.3 | the new suite and checks; stored from sequential runs only (B7.1); W6-1: re-measured sequentially on the otherwise idle PC (307.9 before); W6-1b: re-measured sequentially on the otherwise idle PC (314.1 before); W6-1c: re-measured sequentially on the otherwise idle PC (308.6 before); re-base on public main `a7235433`: re-measured sequentially on the otherwise idle PC, the same lab code apart from its `PUBLIC_MAIN` base constant (311.7 before) |
| quick runtime limit | s, sequential total on the development PC | 291 (the V0 reference run) | 331.3 measured, limit about 350 | B7 acceptance: at most +20 %; W6-1: the unrounded sum of that run (307.9 before); W6-1b: the unrounded sum of that run (314.2 before); W6-1c: the unrounded sum of that run (308.5 before); re-base on public main `a7235433`: the unrounded sum of that run (311.6 before) |
| quick run, `--parallel 4` | s, whole-run wall / suite runtime sum | 75.6 / 273.2 | see `LAB_SUMMARY.txt` | host and load dependent; not compared |
| extended pass | checks held, excluding pins, extended mode | 1781 | 2262 | as pass (quick); W6-1: +65 (+53 in `test_lab_fw_guards`, the quick additions and `EXT FW-09 b3`; +12 in `test_lab_replay_corpus`; 2063 before); W6-1b: +76 (+62 in `test_lab_fw_guards`, the quick additions and `EXT FW-09 b4 / b5 / b6`; +14 in `test_lab_replay_corpus`; 2128 before); W6-1c: +58 (+48 in `test_lab_fw_guards`, the quick additions and `EXT FW-09 b7`; +10 in `test_lab_replay_corpus`; 2204 before) |
| extended finding pins | held `finding-reproduces:` checks, extended mode | not reported | 120 | B6.1 |
| extended runtime | s, one `--extended --parallel 4` run: whole-run wall / suites' contended runtime sum | 527 / 1062 | 534 / 1122 | re-measured with no other workload (`run_lab.EXTENDED_RECORD`; section 3): W6-1: on the V0.1 tree with the W6-1 correction (570 / 1175 before); W6-1b: on the V0.1 tree with the W6-1b correction (553 / 1150 before); W6-1c: last on the V0.1 tree with the W6-1c correction (555 / 1162 before); the sum was wrongly called sequential in V0 (B6.7) |
| FW-06 coverage | commit sites / groups / distinct signatures reached | "all 47 sites reached" | 47 sites in 28 groups; every group reached (40 distinct signatures) | B6.6 wording (the check covers groups) |
| PB-01 N17 hits | violations, quick / extended | 1 / 19 | 0 / 1 | B5.3: never-stored fault draws normalised away |
| NVS faults on never-stored keys | fired injections: corpus; PB-01 quick / extended | 23 in 22 documents; 29 / 371 | 0; 0 / 0 | B5.1 used-key rule |
| distinct mutations | different mutations applied by the control rows (independence rule) | not stated (the audit: about 13 repeats) | 95 over 115 rows (20 rows repeat a mutation) | B3.6; the V0.1 review: `same_mutation_as` (section 9); W6-1: 8 new distinct mutations (77 over 97 before), 8 distinct texts but 6 distinct behaviours (C6k0 = C6s0 and C6k5 = C6s5 semantically; `same_mutation_as` stays text identity); W6-1b: 6 new distinct mutations (85 over 105 before), 6 distinct texts, none repeating another row's; W6-1c: 4 new distinct mutations (91 over 111 before), 4 distinct texts, none repeating another row's |

The V0 values of the finding pins, the checks held and the PB-01 and never-stored counts were not reported by V0; they are
the audit's recount and the V0.1 B5 baseline measurement. The V0 recounts 15 of 39 and 29 of 39 apply V0.1's per-finding
`injected_primitive` to the 39 findings V0 counted (F-HF07-2's trigger is an NVS false negative, as F-HF07-1's, on the
other mirror's marker; F-HF05-1 needs no injected fault). The 291 s reference is the brief's V0 measurement on the development PC.

## 15. Known open items

Disclosed, not fixed in V0.1:

1. **Register-244 data-record false positive (observation).** On a used register-244 domain an Apply whose data-record
   commit is a false positive resolves at the next boot from the stale data record; the later Restore writes 2, not the
   owner's 1, and no invariant fires (section 2.4; an uncounted note of RC-COMMIT-FALSE-POSITIVE). Untriaged; reachability
   UNKNOWN.
2. **PB-01 seed 366 under the phase patch.** PB-01 extended generator seed 366 under the scratch ESPHome-like phase patch gives
   an UNCLASSIFIED `INV-NO-SILENT-OVERRIDE` (a note of RC-PR41-GHOST). The B5 changes do not remove it; triage is open (the
   foreign-register oracle limit HL-2 on a register held only by a ghost's durable marker, or a real ghost consequence).
3. **Fresh-device coverage.** The used-key refusal of `not_landed` and `false_positive` removed the fresh-device forms
   (section 2.4, "The coverage cost of the rule"). Restricting the refusal to `false_negative` would restore them; the choice
   is open.
4. **Free Power final verify read.** The Free Power restore's final 230x3 verify read counts a comms error as a verify
   mismatch: two transient read errors give the durable operator lockout. Not triaged as a finding.
5. **Phase-sensitive counted reproductions.** The exact pins of four counted reproductions hold only at the lab's scheduler
   phase (under the phase patch F-HF01-1 and F-HF04-2 failed in every configuration, F-HF04-1 in 14 of 17, F-HF08-3 in 6 of
   17); F-FW03-2's composite pin fails under the patch by construction, although its Dump-first signature reproduces in 10
   of 17; F-HF03-2's 5 s / 5 s point changes branch; the corpus FINDING documents of F-FW05-2, F-FW06-1, F-FW07-5 and
   F-HF05-2 are timeline-bound. In quick mode `test_lab_ha_schedules` and, at most patched configurations,
   `test_lab_ha_lifecycle` stop without a LAB-SUMMARY under the patch (HL-10; extended mode adds refusals in the
   `test_lab_ha_lifecycle` and `test_lab_ha_phantom` extended sections). The tags disclose this; an ESPHome-faithful phase
   distribution is not modelled.
6. **Reserved UNSUPPORTED ids.** `HF-01-UNS` and `PB-02-UNS` are printed by code if ever met and are not catalogued (section 10).
7. **Latched restore-bound excuses in PB-01.** 32 distinct PB-01 extended-mode due periods pass `INV-RESTORE-BOUND` only through
   a latched excuse (HL-13). They are uncounted and not triaged.
8. **The audit's "18 of 39".** The audit's figure "18 of 39 counted findings rest on an injected primitive" does not reproduce
   under any per-finding rule: the catalogue's per-finding primitives give 15 NVS and 29 any injected primitive for the 39
   findings V0 counted, and 14 NVS and 28 any for the 37 that V0.1 counts.
9. **No Linux evidence of the counts.** CI never runs `run_lab.py`, and `tools/run_offline_tests.py` prints a suite's output
   only when it fails, so the per-suite comparison of section 12 needs a Linux run of `run_lab.py` or a CI tooling change: it
   is UNVERIFIED until then, and the POSIX timeout paths of `run_lab.py` stay unexercised.
10. **Measurements at f11d85f.** The register of silent divergences (section 2.7) and the HL-11 to HL-13 counts were measured
    at f11d85f and not re-taken after the later V0.1 changes, which changed no executed scenario and no corpus trace digest.
    The W6-1, W6-1b and W6-1c corrections then added 18 FW-09 scenarios (b3 to b7) and their corpus documents; those
    counts do not include them.
11. **Independent validation.** The independent re-check of V0.1 took place on 2026-10-21. Its on-disk forms of the B3
    audit mutants (M9, C6, M7, C3, C7, M1, M2) were killed, and it found the gap W6-1 (section 9). The W6-1 correction
    kills the 8 named per-slot mutants (C6k0 to C6k5, C6s0, C6s5) on the non-containment per-slot plan, the W6-1b
    correction kills the six regressions that an internal review of W6-1 found surviving it (C6bf, C6om, C6lt, C6r1,
    C6r4, C6v34) on the modelled shapes, and the W6-1c correction kills the four containment-claim regressions that an
    internal review of W6-1b found surviving it (C6rh, C6rn, C6rs, C6m0) on the modelled shapes; items 15 and 16 list
    what remains. The owner stopped the mutation search after W6-1c. A final independent audit of the completed
    candidate followed on 2026-10-22, offline and on Windows only:
    - **The 18 named mutants.** It applied its own on-disk forms of the 18 named mutants of W6-1, W6-1b and W6-1c,
      written from their published descriptions (C6k0 to C6k5, C6s0, C6s5, C6bf, C6om, C6lt, C6r1, C6r4, C6v34, C6rh,
      C6rn, C6rs and C6m0). All 18 were killed by named directed behavioural checks, no kill rested on a tripwire alone,
      and the 37 counted findings were unchanged.
    - **The W6-1c expectations.** It re-derived them from the firmware source and found them correct, including the
      mismatch and comms paths of section 9. It graded the step-0 deviation from the specification's STOP as correct
      by source and a minor process deviation.
    - **Reproduction.** It reproduced the headline counts and the catalogue check.
    - **Verdict.** It found the offline lab source ready to consider as a pull request, and graded the remaining
      limitations recorded in this section as non-blocking for an offline lab pull request. It left the lab's use as
      a required gate conditional on the first Linux run and the per-suite comparison of section 12.
12. **W6-1: the core oracle does not flag the slot mutants' false claim.** Under every slot mutant (C6k0 to C6k5, C6s0,
    C6s5) the restore ends its first attempt in the FOREIGN-lockout text that ECCO's own settings were "restored and
    verified" while the skipped slot is still at the lease power, and no core invariant fires: the marker stays
    RESTORE_REQUIRED and the operator lockout is set, so `INV-NO-SILENT-OVERRIDE` sees a visible obligation (HL-13). The
    kills rest on the directed checks (.2 the number of attempts, .3 the claims and the mismatch count, .4 the truthful
    report) and on the corpus expectations (the globals and the status history), not on an invariant.
13. **W6-1: per-slot verify on the per-slot plan only.** The b3 scenarios exercise the per-slot readback verify on the
    per-slot plan, which the firmware uses only when a FOREIGN slot exists (firmware `:20035`); otherwise it writes the
    full 0x3F block. On the block path a slot-skip mutant matters only if the inverter applies a 6-register write in
    part, which the lab's per-operation outcome policies do not model (whether a `custom_response` outcome could was not
    checked), so that path's partial application is not exercised. FW-09 b (all six slots unapplied) still fails the
    restore under every slot mutant, because the other slots mismatch. The FW-09 scenario's model text in
    `test_lab_fw_guards` and its result summary in the catalogue record this boundary.
14. **W6-1: the phase patch was run on the b3 scenarios only by the internal regression review.** The in-memory
    ESPHome-like phase patch (section 2.5) predates them. In-suite their phase independence rests on the extended sweep
    `EXT FW-09 b3` (five watchdog phase offsets, 30 runs, all held), not on the patch. The internal regression review of
    the W6-1c candidate later ran the patch (seeds 1 to 3) on `test_lab_fw_guards` and `test_lab_replay_corpus`: no
    untagged check failed (section 2.5).
15. **W6-1b: the per-slot verify regressions that survived W6-1, killed on the modelled shapes.** An internal review of
    the W6-1 correction (not the independent re-validation) applied further regressions of the 256-261 readback verify
    on disk and found six that survived all 14 suites, in three classes: the containment path (V8 drops
    `id(dump_restore_block_failed) = true;` from the mismatch branch, `:20337`; V6 tests `dump_restore_owned_mask`
    instead of `dump_restore_wmask`, `:20336`; V5 compares with `<` instead of `!=`, `:20336`), a readback above the
    expected value (V5) and slot cross-wiring (V4a and V4b compare 257 and 260 against `v[i-1]`, `:20336`; V7 swaps two
    entries of the readback's `v[]` initialiser, `:20333`). No scenario then combined containment with an unapplied
    write, every synthetic SITE ORIGINAL was above the 1000 W lease, and the synthetic SITE ORIGINAL repeated 8000 W.
    The W6-1b correction kills all six on the modelled shapes (section 9: C6bf, C6om, C6lt, C6r1, C6r4 and C6v34, rows
    NC-FW09-14 to NC-FW09-19, with the scenarios b4-ct, b4-cb, b4-co, b5-lo, b6-ok, b6-x257 and b6-x260). What remains:
    - **A partially applied 256x6 block is not modelled** (item 13): b4-cb and b6-ok exercise the 6-slot block only
      whole (all six unapplied, all six applied).
    - **No core invariant for a false containment or a false verified claim.** Under each of the six mutants no core
      invariant fires; the kills rest on the directed checks and the corpus expectations, as in item 12. Since W6-1c a
      suite-level helper in `test_lab_fw_guards` checks every containment claim of every FW-09 timeline against the
      bank (item 16); it is not a core invariant, so a false claim outside FW-09 (for example in PB-01 or the coupled
      tier) would not be flagged.
    - **Before W6-1c, C6om was killed only by b4-co**: in memory it changed the outcome of no other scenario of the
      14 suites. b4-co is the modelled shape in which the containment writes a slot that reads its ORIGINAL (so it is
      not in `dump_restore_owned_mask`), and that write is not applied. This was measured in memory before the W6-1c
      scenarios existed; on disk the internal review of W6-1c found C6om also killed by b7-ab and the `FW-09 claims`
      check.
    - **The phase patch was run on b4 to b6 only by the internal regression review** (as item 14 for b3): in-suite
      their phase independence rests on the extended sweep `EXT FW-09 b4 / b5 / b6` (five watchdog phase offsets,
      35 runs, all held); the internal regression review of W6-1c ran the patch with no untagged FAIL (section 2.5).

    The final independent audit (2026-10-22) re-applied these mutants on disk in its own forms and found them killed
    (section 15, item 11).

16. **W6-1c: the four containment-claim regressions of the W6-1b review, killed on the modelled shapes.** An internal
    review of the W6-1b correction (not the independent re-validation) applied 31 further regressions of the restore's
    verify and containment code on disk: 27 were killed, and four survived all 14 suites in quick and extended mode,
    each live on a timeline built only from fault types the lab already models:
    - **F28 / F29.** The 256-261 readback's failure handlers (`:20347`, `:20352`, `:20357`, `:20365`; F29 only `:20352`)
      no longer set `dump_restore_block_failed`. On the containment path a failed readback then still sets
      `dump_restore_contained` (`:20372`), and the status claims ECCO's slots are held at the 500 W floor although the
      readback never confirmed it.
    - **F32.** The per-attempt reset of `dump_restore_contained` (`:19819`) is dropped, so a containment claim from a
      verified first attempt is carried into a failed second attempt.
    - **F16.** `&& m != 0` is dropped (`:20043`): with every slot FOREIGN, the containment is flagged although no slot
      was written.

    The lab then had no scenario that combined containment with a failed 256-261 readback, a verified containment
    attempt followed by a failed one, or a containment with every 256-261 slot FOREIGN, and no check that a containment
    claim is backed by the bank. The W6-1c correction kills all four on the modelled shapes (section 9: C6rh, C6rn, C6rs
    and C6m0, rows NC-FW09-20 to NC-FW09-23, with the scenarios b7-rbnr, b7-rber, b7-cmnr, b7-ab and b7-af) and adds the
    containment-claim truthfulness helper, applied to every FW-09 timeline through new checks only. The specified shape
    of a failed readback in containment (244 unproven by an unapplied write) takes the firmware's mismatch path
    (`:19982-19984`, `:20482-20507`), not its comms path; b7-cmnr covers the comms path (`:20508-20519`). What remains:
    - **A partially applied 256x6 block is not modelled** (item 13).
    - **The helper is a suite-level check, not a core invariant.** It judges each claim at its first publication (the
      lab logs a status only when its text changes, so a claim republished unchanged after a later bank change would
      not be judged again; no FW-09 timeline changes the bank after its last attempt), and it takes ECCO's ceiling as
      the 1000 W START ceiling every FW-09 timeline shares without checking that against the world. Its fail-loud
      check compares the rebuilt bank with the world's at the end only, so an unlogged bank change in mid-timeline that
      a later logged write overwrites would go unnoticed (a reboot or a capture restore could make one, and a read
      override feeds the firmware values the bank does not hold; no FW-09 timeline uses any of them). In-suite the extended sweeps apply it to the five b7 timelines only;
      the four claims of FW-09 a and c are judged at phase 0 (an internal review measured them backed at five phases).
    - **The readback's on_not_sent and timeout handlers** (`:20357`, `:20365`) are covered only through C6rh as a
      whole: no scenario drives a not_sent or timeout readback, so an edit of those lines alone would not be seen (an
      incidental observation, recorded as a limit; no search was made).
    - **The phase patch was run on b4 to b7 only by the internal regression review** (seeds 1 to 3, no untagged
      FAIL; section 2.5). In-suite the phase independence of b7 rests on the extended sweep `EXT FW-09 b7` (five
      watchdog phase offsets, 25 runs, all held).
    - **A containment claim can go stale during the operator wait** (an incidental observation from the firmware source
      by an internal reviewer, recorded as a limit; graded by the final independent audit (below), not a finding, no
      test added and no search made). While
      the operator lockout lasts, the operator-wait status (`:20535-20550`) builds its claim from the RAM flag
      `dump_restore_contained`, which only a restore attempt writes (reset at its start, `:19819`; set at its outcome,
      `:20372`); nothing re-reads 256-261 in that state, and the ACTIVE drift check is off once `dump_restore_requested`
      is set (`:24268-24272`, set at `:20606`).
      After a verified containment and lockout (FW-09 a's shape), a later inverter or app change of a 256-261 slot would
      leave 'held at the 500 W floor' published although it no longer holds, and the helper, which judges a claim at
      its first publication, cannot see it. The final independent audit (item 11) graded it LOW for safety and
      LOW-MEDIUM for operator information. It is a firmware display-text question rather than a lab defect, reachable
      only through a non-ECCO actor, and is proposed for a separate firmware review.

    An internal review of W6-1c (not the independent re-validation) re-applied the four and the 14 earlier closures
    on disk (all killed by named behavioural checks), checked the new expectations against the firmware source and ran
    the regression matrix; it ran no new mutation search (section 9).

    **The mutation search is stopped.** By the owner's decision the W6-1c correction is the last correction cycle: the
    mutation search is not expanded and no further correction cycle is started. A final independent audit of the
    completed candidate followed (item 11). The final independent audit (2026-10-22) re-applied these
    mutants on disk in its own forms and found them killed (section 15, item 11).

Resolved by the corrections of the V0.1 review and removed from this list: the display of the two `killed(audit)` rows as
"2 other" (`run_lab.py` now names them, section 9), the phase reasons of the corpus tags of FW-06-a, HF-07-c and HF-07-e
(they now say that the `writes` expectation is timeline-bound since the B5 preludes), and the missing lab-wide count of
distinct mutations (then 97 control rows over 77 distinct mutations; now 115 over 95, section 9). Resolved in part by
the W6-1 correction: the 8 named per-slot mutants of the Dump restore's 256-261 readback verify (C6k0 to C6k5, C6s0,
C6s5) are killed on the non-containment per-slot plan (section 9). Resolved in part by the W6-1b correction: the six
regressions that survived W6-1 (C6bf, C6om, C6lt, C6r1, C6r4, C6v34) are killed on the modelled shapes (section 9).
Resolved in part by the W6-1c correction: the four containment-claim regressions that survived W6-1b (C6rh, C6rn, C6rs,
C6m0) are killed on the modelled shapes (section 9); the rest of that gap stays open (items 13, 15 and 16).
