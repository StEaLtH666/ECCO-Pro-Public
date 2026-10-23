"""Hand-written catalogue fields that the lab suite sources do not carry, read by gen_catalogue.py (data only: standard
library, no imports, no side effects; test-only, offline).

What lives here: the tier descriptions, the invariant table, one result summary per scenario, the finding fields some suites
keep no table for (titles, severity, reachability, model dependence, corpus), the per-finding verification summaries, the
two-axis verdicts and injected primitives of the findings (with their vocabularies and the NVS reachability-text rule),
the reclassification records, the phase-sensitivity table, the root-cause groups with their tagged notes, the negative
controls (in-suite controls and audit mutants) with their distinct-mutation table, the UNSUPPORTED items, the harness
limitations and the coverage matrix.
Everything
the suites DO carry (scenario titles, classifications, grades, anchors, finding texts) is read from their source by
gen_catalogue.py, never copied here.

Public text rules (gen_catalogue.py checks them on every prose field): synthetic values only; no event date of a real
installation (cite the public file instead, e.g. docs/incidents/...); simulator output is called simulated, never measured
in the field; no claim that the lab proves a product safe; repair scopes are described, never implemented, and a choice
between repairs is a design decision. A verification summary states what each independent check concluded: the
source-fidelity check re-reads the mechanism against the cited source, the classification check judges the classification,
severity and reachability against the lab vocabulary. A finding that had no independent check says so. A note of a
root-cause group starts with one NOTE_TAGS tag; an audit-reported consequence is uncounted and names where (if anywhere) a
V0.1 directed scenario or corpus document reproduces it.
"""

# ------------------------------------------------------------------------------------------------------------------------
# tiers and invariants
# ------------------------------------------------------------------------------------------------------------------------
TIERS = [
    {"id": "firmware",
     "engine": "FirmwareWorld (registry/tests/assurance_lab/_lab_fw.py) over the transpiled firmware in ds.Sim "
               "(registry/tests/_dump_sim.py): one real firmware, a strict entity registry, a UTC-true clock, an "
               "interval scheduler, NVS / Modbus fault policies and a full-boot reboot primitive",
     "real_source": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml: the real Free Power and Dump to Grid START / END / "
                    "restore / recovery / containment scripts, both 15 s watchdogs, the FULL on_boot except the FB durable "
                    "boot read and two static_assert blocks, the manual TOU and register 244 Load / Apply buttons, the real "
                    "poll scripts and their failure handlers",
     "model_assumptions": [
         "synthetic SITE bank and telemetry (no site values); no inverter physics: export, SOC and PV change only when a "
         "scenario publishes telemetry",
         "scripts and Modbus are synchronous: a START or a restore takes 0 ms, so a power cut lands between two firmware "
         "events, never inside a Modbus frame or an NVS write",
         "the clock derives Europe/London local time from the UTC epoch with the hand-coded rule; only the first NTP sync "
         "per boot is modelled; interval timers are anchored at power-on (ESPHome's random interval offsets are not "
         "modelled, harness_limitations HL-10; same-tick watchdog order is an explicit parameter); script.execute runs "
         "the callee to completion inside the caller (HL-11); a scenario or finding whose verdict depends on "
         "this scheduler phase carries phase_sensitive true with the reason, and every corpus trace digest depends on it "
         "by construction",
         "NVS commit policies wrap commit_record per instance: landed, not_landed, false_negative (stored, False), "
         "false_positive (nothing stored, True); boot faults: a single key read as ABSENT, read errors, a wrong-size "
         "blob, a whole-partition erase that also clears every preference",
         "NVS fault cells (V0.1): false_negative models one ESP-IDF fault cell (the new copy stored and read at the next "
         "boot, the store healthy); the other cells after ESP_ERR_NVS_REMOVE_FAILED (an old copy resurfacing, a page "
         "refusing further writes) are not modelled, and the ESP-IDF semantics are REPORTED, not verified offline; a "
         "per-key read_error heals at the next plain boot, which is optimistic for a data CRC cause; read_error_all "
         "keeps the data, which in ESPHome exists only after a failed partition erase",
         "NVS USED-KEY RULE (V0.1): a not_landed, false_negative or false_positive commit fault and a per-key read_error "
         "or wrong_size boot fault are refused with a harness error on a key never stored earlier in the run (no record "
         "under it now and no landed commit of it since the last whole-partition erase): the device route of a false "
         "negative needs an earlier stored version of the key; scenarios that inject on a marker key first complete a "
         "lease of that domain (a verified restore leaves the marker CLEAR). Coverage cost: the never-used forms are no "
         "longer exercised (an honest marker commit failure on a fresh device, the never-used ABSENT forms of the "
         "Phase-B marker false positive, the fresh-device register 244 lockout)",
         "ESPHome preferences: only flushed values survive a power cut (1 s global poll plus the flash write interval)",
         "a Modbus link model (reads no_response, writes timeout_lost) that also stops the telemetry / configuration "
         "polls; MODEL handlers replace the poll on_response lambdas that do not transpile",
         "RTC correction lock windows are injected as correction_in_progress windows; the RTC tick itself is not "
         "executed in this tier",
         "not executed: the 60 s clock read, the 1 s RTC tick, the FB housekeeping interval and the supervision shadow "
         "interval (they do not transpile)"]},
    {"id": "coupled",
     "engine": "CoupledWorld (registry/tests/assurance_lab/_lab_ha.py): the HA script interpreter "
               "(home-assistant/tests/_ha_script_sim.py) running the real packages, with a RealDongle adapter that maps "
               "every dongle entity the packages use onto one FirmwareWorld (the hand-written dongle models are not used)",
     "real_source": "home-assistant/packages/ecco_free_power_schedule.yaml, home-assistant/packages/"
                    "ecco_dump_to_grid_schedule.yaml, home-assistant/packages/ecco_schedule_manual_restore.yaml and the "
                    "firmware of the firmware tier, under Europe/London time on a UTC-true timeline",
     "model_assumptions": [
         "a firmware run executes synchronously at its gate instant; its Modbus ops, commits and publishes are projected "
         "onto the HA clock (op_s per op, except no_response_s 2.0 s for an op with a no_response outcome (the ESPHome "
         "Modbus hub's default send_wait_time) and timeout_s 3.0 s for an op with a timeout outcome (the firmware's "
         "bounded wait_until), commit_s per commit, the length of an explicit delay executed under a transaction lock, "
         "publish_s to HA); any other dongle mutation inside a projected transaction is refused "
         "loudly (UNSUPPORTED); a second press of a single-mode script whose own work is still pending is dropped and "
         "counted, a press of a script that is in the transaction only through a nested script.execute is refused loudly "
         "(UNSUPPORTED); package options the interpreter ignores are refused at load",
         "latency defaults (press, command, op, publish, commit) are fixed parameters: the press-to-gate delay and the "
         "per-op time are derived from recorded transaction timings, the others are model values; one op time serves "
         "both domains",
         "bus model: recorded busy windows, the lab's own poll traffic, or explicit synthetic windows; the watchdog phase "
         "relative to the HA clock is a sweepable parameter",
         "ASSUMPTION: Home Assistant saves restore-state every 15 minutes and at a clean stop; a crash rolls every package "
         "helper back to its value at the last save; persistent notifications are not restored",
         "ASSUMPTION: dongle entities read unavailable for a reconnect gap after an HA start or a dongle boot; polled "
         "counters read unknown until the new boot's first sample",
         "ASSUMPTION: a service call to a dongle entity while the ESPHome API link is down is dropped silently "
         "(offline_policy 'silent', the default and the policy of most scenarios) or raises S.ServiceError before "
         "delivery (offline_policy 'raise', used by HF-09 and its corpus HF-09-a / HF-09-b); which one matches Home "
         "Assistant is not known offline",
         "service-call faults: S.ServiceError (raised before delivery) is the interpreter's only modelled exception; "
         "HF-09 injects it per service name with the interpreter's fail_services hook inside its suite (not a replay "
         "action)",
         "dump_plant is an opt-in plant stand-in for Dump leases (battery follows the written ceiling)",
         "exact non-:00 time triggers through the interpreter's schedule_time_triggers helper"]},
    {"id": "rtc",
     "engine": "RtcWorld (registry/tests/assurance_lab/_lab_rtc.py) over registry/tests/_fbd1_harness.make_rig (D1Sim) "
               "with the real Free Power START and its 15 s watchdog on the same simulator",
     "real_source": "the firmware's RTC read / correction lambdas and the Free Power START + watchdog of "
                    "firmware/ecco_clock_dongle_stage3_4_free_power.yaml; ecco_rtc:: runs as the Python mirror "
                    "registry/rtc_policy.py (header parity with firmware/include/ecco_rtc_policy.h is enforced only by "
                    "registry/tests/test_rtc_policy.py, which needs a C++ compiler: ECCO_CXX when set, else the first of "
                    "g++, c++, clang++ found on PATH; without one that check fails rather than skips)",
     "model_assumptions": [
         "exact NTP wall clock (no jitter) with the hand-coded Europe/London rule; the inverter clock is the harness "
         "InverterRtc model (offset + rate)",
         "the rig does not run on_boot; only the RTC read, the RTC tick and the Free Power watchdog intervals run",
         "Free Power START inputs (battery voltage, configuration_online) are set as entity states because no poll runs",
         "a D1Sim reboot is not modelled (refused loudly); a Dump lease cannot run on D1Sim, so RT-03 replays the "
         "extracted lock windows into a FirmwareWorld (split model)",
         "the inverter executing its TOU slots on its own clock is not modelled"]},
]

# id -> (tier, meaning, checker 'module.function')
INVARIANTS = {
    "INV-WS": ("firmware", "inverter writes stay inside the write surface {22-24, 230, 232, 244, 250-261, 268-279}",
               "_lab_fw.check_write_surface"),
    "INV-ONE-LEASE": ("firmware", "Free Power and Dump to Grid are never both active", "_lab_fw.check_one_lease"),
    "INV-NO-2ND-RESTORER": ("firmware", "no domain writes 256-261 while the other domain holds a durable RESTORE_REQUIRED "
                            "marker (tagged N17 when the other domain is corrupt)", "_lab_fw.check_no_second_restorer"),
    "INV-NO-RESUME": ("firmware", "no lease is active after a reboot without a new START", "_lab_fw.check_no_resume"),
    "INV-LOCKOUT-QUIET": ("firmware", "while a domain is corrupt-locked nothing writes its registers except the SG-02 "
                          "literal 244 = 2", "_lab_fw.check_lockout_quiet"),
    "INV-NO-SILENT-OVERRIDE": ("firmware", "at steady points, owned registers that differ from the synthetic ORIGINAL have "
                               "a RAM-visible obligation (snapshot valid or a corrupt / UNKNOWN lockout); tagged "
                               "PLATFORM-ABSENT when an injected marker loss caused it",
                               "_lab_fw.check_no_silent_override"),
    "INV-RESTORE-BOUND": ("firmware", "a due restore completes within a bound unless a lockout or an injected fault "
                          "explains the delay", "_lab_fw.check_restore_bound"),
    "INV-BOOT-MIRROR": ("firmware", "after the FULL on_boot a stored RESTORE_REQUIRED / PENDING_CLEAR / MALFORMED marker "
                        "is mirrored in RAM", "_lab_fw.check_boot_mirror"),
    "INV-HF-ONE-LEASE": ("coupled", "firmware truth never shows both leases active on the merged log",
                         "_lab_ha.check_hf_one_lease"),
    "INV-HF-ARM-OFF": ("coupled", "no write enable is left on while no schedule script runs (grace period)",
                       "_lab_ha.check_hf_arm_off"),
    "INV-HF-SMR1-QUIET": ("coupled", "SMR1 writes a staged number only while firmware truth shows no operation, lease or "
                          "snapshot for that domain", "_lab_ha.check_hf_smr1_quiet"),
    "INV-HF-WINDOW": ("coupled", "the firmware override ends within the authorised window end plus a bound (the simulated "
                      "overrun is recorded)", "_lab_ha.check_hf_window"),
    "INV-HF-OWNER-INTENT": ("coupled", "no new firmware session for a schedule run after the owner's End / cancel for that "
                            "run", "_lab_ha.check_hf_owner_intent"),
    "INV-HF-NO-FALSE-SUCCESS": ("coupled", "SMR1 never reports RESTORED while the owner's value is not on the number",
                                "_lab_ha.check_hf_no_false_success"),
    "INV-STATUS-CAUSE": ("firmware", "an operator-facing lockout text names its real cause (scenario-local)",
                         "test_lab_fw_obligations.section_fw01"),
    "INV-STATUS-TRUTH": ("firmware", "a failed START is reported by its real cause and counted once (suite-local)",
                         "test_lab_fw_durability.sec_fw06"),
    "INV-14": ("firmware", "a failed restore is retried on the bounded comms backoff 15 / 30 / 60 / 120 / 300 s",
               "test_lab_fw_runtime.section_07b"),
    "INV-16": ("firmware", "after a restart the owed Stop SOC (bound to the obligation's end epoch) supervises the restore; "
               "a missing SOC counts as reached once 90 s of uptime have passed", "test_lab_fw_runtime.stop_soc_violations"),
    "INV-17": ("firmware", "a Modbus link loss, or telemetry that keeps arriving unchanged (grid CT, battery power, SOC), "
                           "during an ACTIVE Dump lease ends the lease with the firmware's own reason within its bound "
                           "(frozen telemetry: test_lab_fw_runtime.frozen_end_violations)",
               "test_lab_fw_runtime.inv17_violations"),
    "INV-20": ("firmware", "a leaked transaction lock is never released by time; the lock-age monitor escalates within its "
               "bound and the owed restore then completes", "test_lab_fw_runtime.escalation_violations"),
    "INV-FIRST-END-REASON": ("firmware", "Last End Reason keeps the first reason the current or last lease ended",
                             "test_lab_fw_runtime.section_07g"),
    "INV-RTC-EXCL": ("firmware", "no restore write inside an RTC correction lock window", "test_lab_fw_runtime.rtc_violations"),
    "INV-HF-PRESS-PROOF": ("coupled", "a schedule never presses START again after a START gate passed",
                           "test_lab_ha_lifecycle.check_press_proof"),
    "INV-HF-NEVER-SILENT": ("coupled", "a scheduled run never ends without a STARTED / CANCELLED result or an alert",
                            "test_lab_ha_lifecycle.check_never_silent"),
    "INV-HF-NO-RESUME": ("coupled", "no new lease is started for a run the firmware ended at a reboot (coupled-level form "
                         "of the no-resume rule)", "test_lab_ha_lifecycle.check_hf_no_resume"),
    "INV-HF-NO-PRESS-INTO-LEASE": ("coupled", "a schedule never presses START into an active lease of the same domain",
                                   "test_lab_ha_schedules.check_no_press_into_lease"),
    "INV-HF-TAIL-RETRY": ("coupled", "a blocker that clears inside the schedule's own retry budget is retried, not failed at "
                          "once", "test_lab_ha_schedules.section_hf04_dump_fp"),
    "INV-HF-NO-SILENT-LOSS": ("coupled", "a scheduled window is never lost without a failure alert",
                              "test_lab_ha_schedules.section_hf04_same"),
    "INV-HF-ARM-INTENT": ("coupled", "an arm is refused only for a real conflict of its own window",
                          "test_lab_ha_schedules.section_hf04_fp_dump"),
    "INV-HF-MODEL-FIDELITY": ("coupled", "the HA dongle models match the firmware's failed-START behaviour",
                              "test_lab_ha_schedules.section_hf06_dump"),
    "INV-HF-ALERT-TRUTH": ("coupled", "a schedule alert states the failure's real cause and current advice",
                           "test_lab_ha_schedules.section_hf06_fp"),
    "INV-HF07-TRUTHFUL-REPORT": ("coupled", "FPS1's recorded result does not contradict an outstanding durable obligation",
                                 "test_lab_ha_phantom.section_report_text"),
    "INV-DST-OWNER-START": ("coupled", "a local start runs at that wall time or is refused with a DST-specific reason",
                            "test_lab_dst_rtc.section_hf08"),
    "INV-DST-TOU-SLOT-CLEAR": ("firmware", "an admitted Dump lease overlaps no charge slot in real local time",
                               "test_lab_dst_rtc.check_slot_clear"),
    "INV-DST-TOU-REFUSE": ("firmware", "normal-day control: a Dump lease that overlaps a charge slot is refused",
                           "test_lab_dst_rtc.check_tou_refuse"),
    "INV-EPOCH-END": ("firmware", "a lease ends at its gate second plus its duration on the UTC epoch",
                      "test_lab_dst_rtc.check_epoch_end"),
    "INV-RTC-DST-CORRECTED": ("rtc", "one verified large correction after the clock change, within the design bound",
                              "test_lab_dst_rtc.check_dst_corrected"),
    "INV-RTC-WD-SKIP": ("rtc", "no lease-end action inside an RTC correction lock window", "test_lab_dst_rtc.check_wd_skip"),
    "INV-RTC-NO-RESTORE-IN-LOCK": ("rtc", "no restore write inside an RTC correction lock window",
                                   "test_lab_dst_rtc.check_no_restore_in_lock"),
    "INV-RTC-START-LOCK": ("rtc", "a START inside an RTC correction lock window is refused with zero writes",
                           "test_lab_dst_rtc.check_start_lock"),
    "INV-RTC-LEASE-HOLD": ("rtc", "while a restore obligation is owed only large corrections run (firmware equals the "
                           "policy mirror)", "test_lab_dst_rtc.check_lease_hold"),
    "INV-RTC-DRIFT-BOUND": ("rtc", "the inverter clock error stays within 600 s", "test_lab_dst_rtc.check_drift_bound"),
    "INV-RTC-STALL-SURFACED": ("rtc", "a stopped inverter clock is reported by the documented stall signal",
                               "test_lab_dst_rtc.check_stall_surfaced"),
    "INV-TZ-ORACLE": ("firmware", "London local time agrees with the two hand-coded oracles (and zoneinfo when importable)",
                      "test_lab_property.section_pb03"),
    "INV-TZ-ROUNDTRIP": ("firmware", "every local wall time round-trips through UTC with its fold",
                         "test_lab_property.section_pb03"),
    "INV-TZ-FOLD": ("firmware", "fold / gap semantics follow zoneinfo (fold=0: first occurrence; gap: pre-transition offset)",
                    "test_lab_property.section_pb03"),
    "INV-UTC-MONOTONIC": ("firmware", "every event log is UTC-monotonic, also across reboots and power cuts",
                          "test_lab_property.section_pb03"),
    "INV-MILLIS-WRAP": ("firmware", "millis() is the low 32 bits of the uptime; a lease across the wrap ends on its UTC epoch",
                        "test_lab_property.millis_masked"),
}

# ------------------------------------------------------------------------------------------------------------------------
# scenario result summaries (final state at this baseline; hand-written from the runs and the reconciled verdicts)
# ------------------------------------------------------------------------------------------------------------------------
RESULT_SUMMARY = {
    "FW-01": "Both phantom orders reproduce F-FW01-1 (the phantom START writes nothing, the other domain's START is admitted "
             "and writes 256-261) and the PR41 dual lockout at every boot (1 and 3 reboots, 40 watchdog ticks). "
             "INV-LOCKOUT-QUIET, INV-NO-RESUME, INV-WS, INV-ONE-LEASE, INV-NO-SILENT-OVERRIDE and INV-BOOT-MIRROR hold: in "
             "(a) the only write is SG-02's literal 244 = 2 and the Dump ceiling residue stays below the ORIGINAL; in (b) "
             "nothing is written after any reboot and the Free Power override is still applied 6 h after the operator "
             "sweep, every operator surface refusing (F-FW01-2). The Free Power status names untrusted data although its "
             "record loaded (F-FW01-3); a status publish inside the PR41 branch alone is overwritten later in the boot "
             "lambda. The SG-02 variant with ORIGINAL 244 = 0 switches the owner's Allow Export to Zero Export by design "
             "(PASS, FW-01-c). 7 negative controls killed. Since V0.1 every phantom is injected on a used marker key: "
             "the scenario first completes a one-minute lease of the phantom's domain (verified restore, marker CLEAR; "
             "the used-key prelude, checked in every corpus replay log), and every outcome above is the same as in the "
             "never-used form.",
    "FW-02": "The manual slot 2 Apply is admitted under every phantom (its gate reads RAM mirrors only). Free Power phantom: "
             "after the reboot the classifier fails closed (OPERATOR DECISION REQUIRED, zero writes, the owner's value "
             "kept; F-FW02-1, duplicate of F-FW02-2); a start-time edit restores as ORIGINAL with zero writes. Dump "
             "phantom: an owner power equal to the phantom's feed-forward ceiling or the 500 W floor is silently rewritten "
             "to the stale ORIGINAL and reported RESTORED OK (F-FW02-2, N15); an owner value that is not ECCO's (4000 W) is "
             "FOREIGN and never written. INV-WS, INV-ONE-LEASE, INV-NO-RESUME, INV-LOCKOUT-QUIET and INV-BOOT-MIRROR hold "
             "in all runs. Since V0.1 the phantom follows a completed one-minute lease of its domain (the used-key "
             "prelude, run before the synthetic telemetry); every outcome and the coincidence set are unchanged.",
    "FW-03": "Triple obligation: S4 fires first at every boot, PR41 is skipped by its '!dump corrupt' guard and the Free "
             "Power automatic restore writes 256-261 over Dump's open obligation (F-FW03-1, N17, duplicate of F-FW05-2); "
             "the same with an unreadable Dump data record. With the Free Power lease context 244 = 0 the watchdog order "
             "decides: Dump first, SG-02 writes 244 := 2 and the Free Power restore is held by its register-244 context gate "
             "behind OPERATOR DECISION REQUIRED (F-FW03-2, N16; Force resolves, Accept refuses); Free Power first, it "
             "restores. Under the S4 lockout the reg244 result names unreadable data although its record loaded (F-FW03-3, "
             "duplicate of F-FW01-3). After a transient data read error the next clean boot trusts Dump again (zero-write "
             "RESTORED OK). INV-WS, INV-NO-RESUME, INV-ONE-LEASE and INV-BOOT-MIRROR hold. Since V0.1 every injection "
             "follows a completed lease of its domain (the used-key prelude: a register 244 Apply then its Restore, a "
             "one-minute Dump lease); every outcome is unchanged.",
    "FW-04": "Baselines with intact NVS end and restore the lease (no resume). A single-key false ABSENT at a reboot during "
             "an ACTIVE lease reads CLEAR: the Dump override (244 = 0, lease ceiling) or the Free Power grid-charge override "
             "stays live with no obligation, lockout or alert (F-FW04-1 / F-FW04-2, PLATFORM-ABSENT); INV-NO-SILENT-OVERRIDE "
             "reports exactly one episode, never INV-BOOT-MIRROR (nothing stored to mirror). A later START adopts the "
             "residue as ORIGINAL and its restore reports 'verified' (F-FW04-3, consequence row). A whole-partition erase "
             "does the same from the erase boot (F-FW04-4, NVS-PARTITION-ERASE). A READ_ERROR boot is the fail-closed "
             "UNKNOWN lockout; losing the data record locks out; losing the retry, tombstone or journal record still "
             "restores. NC-FW04-1..3 killed.",
    "FW-05": "41 quick cut runs (a power cut at every state-changing START / restore event, both directions and the N17 "
             "shape), each rebooted through the FULL on_boot, show no invariant violation after the reboot: cuts that leave "
             "both markers RESTORE_REQUIRED boot into the PR41 dual lockout (only SG-02's 244 := 2 is written), "
             "PENDING_CLEAR / RESTORE_REQUIRED mixes resolve (PENDING_CLEAR clears with zero Modbus writes), single-marker "
             "cuts are resolved by that domain's own restore; INV-BOOT-MIRROR judged all 41 boots. The phantom precondition "
             "is re-verified (F-FW05-1, duplicate of F-FW01-1): a latent phantom self-heals at the next boot with a "
             "zero-write verified no-op, or stops at OPERATOR DECISION REQUIRED after an owner change. F-FW05-2 (N17, the "
             "lab's owner) reproduces in three forms, the bank ending at ORIGINAL in each. NC-FW05-1 killed. Since V0.1 "
             "each phantom is injected on a used marker key after a completed lease of its domain (the used-key "
             "prelude); every cut point's outcome equals the never-used form.",
    "FW-06": "47 commit_record sites in 28 component / tag groups; every group is reached by the 15 flows (40 distinct "
             "commit signatures; text sites inside one group are not distinguished one by one); false negatives and false "
             "positives at every reachable signature leave no invariant violation except the two Phase-B marker false "
             "positives (F-FW06-2 Free Power, F-FW06-3 Dump: a reboot during the lease leaves the override live with the "
             "previous lease's stale CLEAR marker). A Free Power START commit failure publishes START FAILED, then "
             "ACTIVATION WRITE FAILED, counts two failures and ends on END IGNORED for the data / marker cases (F-FW06-1); "
             "every Dump START commit failure ends on one terminal START FAILED with nothing written. NC-FW06-1 killed. "
             "Since V0.1 every flow, nominal and injected, first completes a lease of its domain (the used-key prelude: "
             "a one-minute Free Power or Dump lease, or a register 244 Apply then its Restore), so the never-used forms "
             "are no longer injected (a Phase-B marker false positive reading ABSENT at the reboot, an honest marker "
             "failure on a fresh device); the nominal signatures and injection plans are unchanged.",
    "FW-07-A": "PASS: TELEMETRY LOST about 28 s after the link loss; supervised restore attempts every 15 s while the SOC is "
               "stale, with no write; the restore completes about 13 s after the link recovery through the SG-39 path "
               "(NC-FW07-1 removes that clause and the restore stays open; NC-FW07-2 neuters the TELEMETRY LOST monitor).",
    "FW-07-B": "PASS: restore attempt gaps follow the comms backoff (28 / 30 / 60 / 120 / 300 / 300 s on the watchdog "
               "grid); SG-39 completes the restore about 18 s after the link recovery.",
    "FW-07-C": "PASS: the lease is not resumed after the reboot; restore attempts at uptime 15, 30 and 60 s, then every "
               "tick from 105 s (no fresh SOC beyond 90 s of uptime); the persisted owed Stop SOC is bound to the "
               "obligation's end epoch (NC-FW07-3 killed).",
    "FW-07-D": "INV-16 PASS: at SOC 50 % the retries follow the backoff, at 24 % they run every tick, so the owed Stop SOC "
               "25 % governs, not the owner's lower configured 10 % (NC-FW07-4 and NC-FW07-7 killed). Export stays enabled "
               "while the inverter refuses every 244 write (F-FW07-3, FCP2-R1); ECCO's own slots are held at the 500 W "
               "floor and each failed attempt's status names the unproven 244.",
    "FW-07-E": "PASS: in both domains the owed restore completes at boot uptime 15 s while now() is still invalid (first NTP "
               "sync at uptime 400 s); the 300 s invalid-clock grace never delays it (NC-FW07-5 and NC-FW07-6 killed).",
    "FW-07-F": "During the outage the Free Power restore retries follow the comms backoff; after the link recovery the "
               "restore runs about 238 s later (the rest of the current backoff window), while the Dump analogue restores "
               "within one watchdog tick through SG-39 (F-FW07-1).",
    "FW-07-G": "Reproduced: a reboot between a Dump lease end and its verified restore publishes 'ESP RESTARTED DURING "
               "LEASE' for the already-ended lease (F-FW07-2); the restore completes and the invariants hold. FW-08-B and "
               "FW-08-C reproduce the same text after stuck-lock escalation restarts (counted once).",
    "FW-07-H": "Reproduced: one failed reply on one configuration block read (Blocks A and B: every allow-listed failure "
               "outcome; display-only Block C: error or no response) ends the ACTIVE Dump lease at the next watchdog tick "
               "as 'TELEMETRY LOST - failing closed' (F-FW07-4); Block C not_sent / non-standard replies are tolerated; the "
               "restore completes and nothing resumes.",
    "FW-07-I": "PASS: with the link up, a grid CT repeating while the battery moves ends the ACTIVE Dump lease 'GRID CT "
               "FROZEN' 60 s after the first frozen read, a repeating battery power reading ends it 'BATTERY POWER "
               "TELEMETRY FROZEN', and a SOC that stays fresh and plausible but never changes ends it 'SOC TELEMETRY "
               "FROZEN' once 1500 Wh are counted (about 5158 s after START); a power cut at the restore's first write "
               "boots with the stored RESTORE_REQUIRED mirrored in RAM, no resume, and the boot-path restore completes "
               "13 s after the boot (INV-17, INV-RESTORE-BOUND rebased at the boot, INV-NO-RESUME, INV-NO-SILENT-OVERRIDE, "
               "INV-BOOT-MIRROR hold). A reboot after a completed restore owes nothing; a new START on the still-frozen "
               "CT ends again by the detector 78 s later. The end reasons themselves are already tested by "
               "registry/tests/test_dump_safety_fcp2.py on hand-fed publishes; new here is the crossing with the "
               "restore, the power cut and the reboot. Incidental F-FW07-5: the fast frozen-CT criterion's battery range "
               "is not re-seeded at START (corpus FW-07-i3). NC-FW07-8, NC-FW07-9 and NC-FW07-10 killed; extended mode "
               "sweeps freeze onset x power-cut point.",
    "FW-08-A": "PASS (documented behaviour): 296 single-op faulted runs over Dump / Free Power START and END and manual slot "
               "2 leave a transaction lock held in exactly one case, the manual TOU verify read with no callback, which "
               "the write-surface notes document; the lock-age monitor reports it and the manual apply refuses while "
               "anything is owed, so it cannot overlap a lease.",
    "FW-08-B": "PASS: the leaked manual_write_in_progress defers the owed restore; the lock-age monitor escalates after "
               "180 s, the firmware restarts about 188 s after the leak and the boot path completes the restore about "
               "206 s after it (NC-FW08-1 and NC-FW08-2 killed). Its corpus FW-08-c also pins F-FW07-2's text.",
    "FW-08-C": "PASS: a leaked Dump operation flag suspends the lease monitors; WRITE LOCK STUCK ends the lease durably, the "
               "restart and the boot restore follow and the Stop SOC overrun stays within the escalation bound. Its "
               "corpus FW-08-d also pins F-FW07-2's text.",
    "FW-08-D": "PASS: Free Power analogue - the escalation restart, S3 converts the lease into a restore request and the "
               "restore is verified.",
    "FW-08-E": "PASS: a Dump end inside an RTC lock window is deferred ('END DEFERRED - RTC correction active') and the "
               "restore runs after the window; no restore write inside a window (NC-FW08-3 killed). Windows longer than "
               "the 90 s deadline breaker are UNSUPPORTED in this tier (FW-08-E-U1).",
    "FW-08-F": "Reproduced: stuck-lock restarts about every 203 s with no restore attempt; 244 stays at Allow Export and "
               "256-261 at the lease power, nothing is written after the leak and no status is CRITICAL (F-FW08-1, "
               "FCP2-F6); the core checkers see no violation.",
    "FW-09": "PASS: a: the inverter acknowledges but never applies 244 := 2; both attempts fail on the 244 readback, 256-261 "
             "are contained at min(original, 500 W) and named so, the marker stays RESTORE_REQUIRED, one automatic retry, "
             "then the durable operator lockout; Force Restore Original completes once 244 is applied again. b: the "
             "6-slot 256-261 write is acknowledged but not applied; both attempts fail on the readback, then the operator "
             "lockout, with 256-261 at 1000 W reported as a repeated mismatch. b2: a FOREIGN 261 makes the plan per slot "
             "and is never written; after a comms error on 260 every retry is a single-slot 260 write, acknowledged but "
             "not applied and failed on its readback, with no 'restored and verified' claim. b3-256 .. b3-261 (one per "
             "slot k): a FOREIGN slot (261, or 256 for b3-261) makes the plan per slot and is never written; every "
             "single-register write of k after the End (policy write:<k>x1) is acknowledged but not applied, so the "
             "first attempt (244 and every other slot written one by one) and the single-slot retry of k both fail on "
             "k's readback, then the operator lockout, with k at 1000 W reported as a repeated mismatch and no "
             "'restored and verified' claim. b4-ct / b4-cb / b4-co (the containment path): every 244 write is "
             "acknowledged but not applied, so 244 is not proven and every non-FOREIGN slot is written at min(original, "
             "500 W); the floor write of 258 (a FOREIGN 261 makes the plan per slot), the 6-slot floor block (nothing "
             "FOREIGN) or the floor write of 256 (put back to its ORIGINAL by the inverter, so not ECCO-owned, yet "
             "written by the containment) is acknowledged but not applied; both attempts fail on the readback, "
             "dump_restore_contained stays clear and every status says 'export may continue' (naming the FOREIGN 261 NOT "
             "CONTAINED), never 'ECCO's own at 500 W' or 'held at the 500 W floor', then the operator lockout. b5-lo: "
             "b3's shape for 259 on a site whose 259 ORIGINAL is 600 W, below the 1000 W lease value: the unapplied 259 "
             "reads above its expected value and both attempts fail on it. b6-ok: a fault-free restore of "
             "pairwise-distinct originals (3000/8000/7000/6000/4500/5000 W) verifies every slot against its own "
             "original in one attempt (RESTORED OK, marker CLEAR); b6-x257 / b6-x260: b3's shape for 257 / 260 on that "
             "bank with 256's / 259's original equal to the 1000 W lease value, so the unapplied slot reads its "
             "neighbour's expected value, and both attempts still fail on it. b7-rbnr / b7-rber (a failed readback in "
             "containment): b4-cb's / b4-ct's containment whose 256-261 readback gets no response / an error; the "
             "failure handler sets block_failed, so dump_restore_contained stays clear and every status says 'export "
             "may continue'; the 244 readback mismatch takes the mismatch path, so both attempts fail, then the "
             "operator lockout. b7-cmnr (the comms path in containment): 244 lands but its verify read errors, the "
             "6-slot floor block is acknowledged but not applied and its readback gets no response: 'RESTORE WRITE "
             "FAILED' with 'export may continue' (backoff, marker kept); the retry after the backoff finds 244 "
             "ORIGINAL, restores ORIGINAL and completes. b7-ab (two attempts): the first containment attempt verifies and "
             "truthfully says 'held at the 500 W floor'; the inverter then puts 258 back to its ORIGINAL and the second "
             "floor block is acknowledged but not applied: the per-attempt reset keeps dump_restore_contained clear and "
             "no later status claims the containment. b7-af: every 256-261 slot FOREIGN, so the containment writes "
             "nothing, dump_restore_contain stays clear and every status names all six NOT CONTAINED with 'export may "
             "continue'. Every containment claim of every FW-09 timeline is backed by the bank at the instant its status "
             "was published (5 claims: a, c, b7-ab). c / c2: a failed 244 / "
             "256-261 verify read fails the attempt on the comms path (backoff, marker kept; 244 unproven, so contained "
             "in c) and the retry after the backoff completes. Every core invariant holds. 23 negative controls killed "
             "(M9, C6 twice, MC244, MC256, the slot mutants C6k0..C6k5 and the loop-bound mutants C6s0 / C6s5, each "
             "killed by the b3 scenario of the slot it skips, C6k4 also by b2; C6bf (block_failed dropped) by the three "
             "b4 scenarios, C6om (the owned mask) by b4-co, C6lt ('<') by the three b4 scenarios and b5-lo, C6r1 (257 "
             "against 256's value) by b6-ok and b6-x257, C6r4 (260 against 259's) and C6v34 (259 / 260 swapped) by "
             "b6-ok and b6-x260; C6rh (block_failed dropped from every readback failure handler) by b7-rbnr, b7-rber and "
             "b7-cmnr, C6rn (the no-response handler only) by b7-rbnr and b7-cmnr, C6rs (the per-attempt reset of "
             "dump_restore_contained dropped) by b7-ab, C6m0 ('m != 0' dropped from the containment flag) by b7-af); c / "
             "c2 cannot kill M9 / C6 by construction (their failure path never runs the mutated "
             "readback compares), so they carry their own error-branch mutants. Model boundary: multi-register writes "
             "are all-or-nothing in the model (one outcome per operation), so a single unapplied slot is exercised on "
             "the per-slot plan only (a FOREIGN slot present, FW:20035, FW:20031) and the 6-slot block only whole (b4-cb "
             "all six unapplied, b6-ok all six applied); a partially applied 256x6 block is not modelled. The "
             "containment-claim helper judges each claim at its first publication (a status re-published unchanged is "
             "logged once) and takes ECCO's ceiling as the 1000 W START ceiling every FW-09 timeline shares.",
    "FW-10": "PASS: with every Free Power owned register at ORIGINAL, a Dump START is REJECTED citing Free Power with zero "
             "writes in three Free Power states: RESTORE_REQUIRED after a failed final verify read (active and snapshot "
             "set), PENDING_CLEAR after a durable clear that did not land (snapshot only), and the SG-06 UNKNOWN lockout "
             "after an NVS read error on the used fp.valid key (snapshot and corrupt). The same START is admitted once the "
             "state is resolved, or in the control timeline without the fault. M7 is killed in all three states; M7b "
             "(the snapshot term only) is killed in B and C and survives A by design; M7a (the active term only) is an "
             "equivalent mutant (static site check).",
    "FW-11": "PASS: after a completed Free Power lease (a used fp.valid key), an NVS read error at boot gives the SG-06 "
             "UNKNOWN lockout and a wrong-size or bad-magic record gives the MALFORMED lockout, both with the record "
             "CLEAR and with a second lease ACTIVE: snapshot_valid and metadata_corrupt set, the cause-specific status, "
             "the record untouched, no Free Power write, every core invariant holds. C3, C7 (wrong size and bad magic) "
             "and C7ws (wrong size) are killed; C7ws survives the bad magic by design. The bad-magic record is a "
             "white-box edit (suite only, no corpus document).",
    "HF-02": "Graceful restarts in STARTING and ACTIVE and a crash in ACTIVE (reconnect gaps 10 / 25 / 230 s) PASS: one "
             "recovery, one lease, never a second START, and exactly the documented SMR1-UNCLEAN-SHUTDOWN outcome. A "
             "crash-window rollback after the owner's End & Restore starts an unrequested second session (Free Power and "
             "Dump to Grid), after a firmware early end a new lease, and after a natural end a false MISSED alert "
             "(F-HF02-1). A crash during STARTING leads to a false SMR1 RESTORED (F-HF02-2). A graceful restart while "
             "STARTING after the owner moved the start helper abandons the run silently (F-HF02-3). NC-HF02-1 and "
             "NC-HF02-2 killed; NC-HF02-1b survives as expected (defence in depth).",
    "HF-03": "The early-reset PROXY (a cut at START's first Modbus read) reproduces F-HF03-1 at 4 of 6 swept points (grade "
             "INFERRED): 'never reached the dongle' and a second START press, while the cut START wrote nothing; later "
             "in-transaction cuts are UNSUPPORTED (HF-03-UNS-1). With attempts_before above 0 the no-answer guard holds. "
             "A reboot during ACTIVE never resumes (INV-NO-RESUME; NC-HF03-2 and NC-HF03-3 killed). A whole-site power cut "
             "during a scheduled Dump makes the DGS1 recovery start a new lease whose alert its own success dismisses, or "
             "record a false 'STARTED OK - running' (F-HF03-2).",
    "HF-05": "STARTING: a non-schedule owner value is kept (PASS); a schedule-shaped value is replaced by the pre-schedule "
             "value, exactly the documented limit SMR1-OWNER-STAGING (PASS, documented limit; formerly F-HF05-1, "
             "reclassified and not counted, as F-RT02-1; doc nit: the CHANGELOG line \"the owner's own later change "
             "always wins\" is unqualified against it). ACTIVE: the owner edit is kept and the firmware lease is unaffected. "
             "RESTORING: an owner change landing within about one command + publish latency of SMR1's restore write is "
             "lost and reported RESTORED with no notification (F-HF05-2, SMR1-OWNER-RESTORING). Edits inside a projected "
             "firmware transaction are UNSUPPORTED (HF-05-UNS-1, HF-05-UNS-2). NC-HF05-1 and NC-HF05-2 killed.",
    "HF-09": "Service exceptions against the real firmware (the interpreter's fail_services hook; S.ServiceError raised "
             "before delivery). A raised FPS1 START press is contained by continue_on_error: 'never reached the dongle' "
             "is true on the firmware's RAM gate-pass counter and the retry is one ordinary gated START (one lease). A "
             "DGS1 write-enable turn_on raising once presses nothing and starts on attempt 2; raising on every call "
             "reaches nothing and ends 'FAILED TO START - retries ended' with its alert. An SMR1 restore write raising "
             "0.5 s after the firmware's own restore ends PARTIAL with the field named and one notification open (no "
             "false RESTORED). A raised closing turn_off is harmless because the firmware disarms the write enable at the "
             "press. A raised press plus a raised no-answer turn_off ends 'outcome unconfirmed, not retried' with an "
             "alert, the closing turn_off ending the switch off. F-HF09-1: when both turn-offs of a run fail after an "
             "unanswered press (three service errors, or one API outage of about 62 s or more from inside the press's "
             "flight under either offline policy) the write enable stays ON after the run, SMR1 stays OWED and the "
             "alert does not name the switch; a 40 s outage (HF-09-b) ends with the switch off. NC-HF09-1, NC-HF09-2 and "
             "NC-HF09-3 killed; NC-HF09-2b survives as expected on the scheduled path (the package's closing turn_off is "
             "the backstop) and is killed elsewhere on the owner-armed path (test_lab_selftest_firmware's owner-armed "
             "START check, HF-09.4 and the corpus trace digests).",
    "HF-07": "Both mirrors: the phantom START writes nothing, HA shows the first domain idle and the other schedule's START "
             "is admitted over the durable RESTORE_REQUIRED (F-HF07-4 = F-FW01-1); after the dongle power cut PR41 locks "
             "both domains at both reboots and the only write during the lockout is SG-02's 244 := 2 (mirror a). FPS1 / "
             "DGS1 keep showing ACTIVE past the window and no persistent notification names the lockout for about 24 h "
             "(F-HF07-1, counted here, in two mirror instances; the DGS1 instance F-HF07-2 is merged into it); the 'did "
             "NOT start' result reads END IGNORED although a durable "
             "obligation exists (F-HF07-3 = F-FW06-1); every HA-reachable recovery press refuses with a misstated cause "
             "(F-HF07-5 = F-FW01-3). SMR1 makes no staged write after the lockout and HA restarts start nothing. Negative "
             "controls: 7 killed, 2 survived as expected (defence in depth on the watchdog path; the restore-script "
             "precondition alone is killed on the owner's End-press path, NC2b-rs-end); ecco_system_health.yaml is "
             "UNSUPPORTED. Since V0.1 each chain first runs a completed one-minute scheduled lease of the phantom's "
             "domain through that domain's own schedule (the used-key prelude: verified restore, marker CLEAR), and the "
             "true START commit-failure control runs on the used key (its marker stays CLEAR); every outcome above is "
             "unchanged, and corpus HF-07-c and HF-07-f with the prelude removed are refused by the lab.",
    "HF-08": "FPS1: an 01:xx start on the fall night always resolves to the BST copy (fold=0); an arm meant for the GMT copy "
             "is refused as a past start (F-HF08-1); the nonexistent spring 01:30 is ARMED and runs one hour from the "
             "typed wall time (F-HF08-2). Dump: on both nights the DGS1 arm walk and the firmware START gate admit a lease "
             "that really overlaps a synthetic charge slot for 30 min, and on the fall night they spuriously refuse a "
             "window outside the lease's real span, fail closed (F-HF08-3, SG-25); normal-day controls are refused by both "
             "layers. NC-HF08-1..3 killed.",
    "RT-01": "PASS: the fault-free night gives one verified large correction about 105 s after 01:00 UTC; a lost write "
             "callback gives the 90 s breaker abort, the 300 s cooldown and then the DST correction, at +345.12 s on the "
             "rig's one fixed 60 s read phase (the V0 independent audit swept the read phase and reports a model-only "
             "worst case of about +540 s queued and +552 s lock end, about 9 min; not reproduced by a V0.1 directed "
             "scenario); a lease ending inside a lock window is deferred out of it, ends on its UTC epoch and restores "
             "verified. NC-RT01-1 and NC-RT01-2 killed.",
    "RT-02": "PASS (documented behaviour): with a stopped inverter clock and an owed restore only large corrections run, "
             "each reading back 'Verified OK' with failed_corrections 0; the error stays within 600 s and the documented "
             "stall signal reports the stopped clock. F-RT02-1, first drafted as FINDING-NEW, is classified PASS "
             "(documented behaviour) and prints no FINDING line; residue OBS-RT02-1 (the stall entity drops to off for about 108 s after each "
             "verified correction) is undocumented diagnostics. NC-RT02-1..3 killed.",
    "RT-03": "Split model: lock windows extracted from the RTC rig, replayed into a FirmwareWorld Dump lease, defer the lease "
             "end out of the lock and refuse a START inside it with zero writes. The compound DST case admits the lease "
             "across the synthetic charge slot (SG-25); this RTC-step variant, formerly F-RT03-1, is merged into F-HF08-3 "
             "and not counted. NC-RT03-1..3 killed.",
    "PB-01": "160 quick sequences x 12 actions from published seeds (2000 in extended mode), all eight firmware invariants "
             "after every action and at quiescence: every violation matches a known signature and none is unclassified. "
             "The quick sequences hit partition erase 8 x (F-PB01-3 = F-FW04-4) and single-key false ABSENT 4 x "
             "(F-PB01-3:single-key = F-FW04-2); phantom admission (F-PB01-1 = F-FW01-1) and restore over a corrupt holder "
             "(F-PB01-2 = F-FW05-2) are pinned by corpus PB-01-a and PB-01-b, and the false-positive-commit signature "
             "(F-PB01-4 = F-FW06-3, its used-device form with the previous lease's stale CLEAR marker) by a directed "
             "section and corpus PB-01-d; the 2000 extended sequences hit restore over a corrupt holder once (a "
             "wrong-size blob on a stored marker), phantom admission 11 x, partition erase 42 x and false ABSENT 36 x, "
             "the false-positive-commit signature never. Every class duplicates a directed-suite finding, so none is "
             "counted here. NC-PB01-a, -b, -c and -d killed (ddmin shrinks the three random-search controls a, b and d to 2 "
             "actions each; c is a fixed directed trace); NC-PB01-a also exercises the unclassified-violation report "
             "path: its shrunk counterexample is printed as a replay document that survives the validate / dumps / load "
             "round trip and replays deterministically on the in-memory mutant, not on the real firmware. Generator "
             "constraints (harness_limitations HL-1 to HL-3 and HL-6): an operator Accept is issued only when it cannot "
             "move the lab's ORIGINAL (otherwise recorded as run_for 0), a register change is drawn as a foreign "
             "(inverter) write only while a domain holds that register, and an RTC lock window list is never empty; this "
             "narrows the searched operator actions and foreign writes. Since V0.1 a per-key boot fault (read error, "
             "wrong-size blob) and a commit-fault policy (not_landed, false_negative, false_positive) are drawn only on "
             "a key that holds a record (otherwise a plain reboot or run_for 0), and a whole-partition erase is not drawn "
             "while such a policy is armed, so no NVS fault hits a key never stored in the run (the lab refuses one); an "
             "event-log fault scan pins this in every run (quick: 8 commit faults and 8 per-key boot faults, none on a "
             "key without a record). The PB-01-a, PB-01-b and PB-01-d corpus documents start with one completed lease.",
    "PB-02": "14 quick coupled sequences (150 in extended mode): no unexplained coupled or firmware violation, no "
             "UNSUPPORTED point, every merged log UTC-monotonic; window-end overruns above the generic 30 s stay inside "
             "the documented 90 s late-start allowance (HF-01 owns their classification). Dump leases run without the "
             "dump_plant stand-in (stated gap). NC-PB02-a and NC-PB02-b killed.",
    "PB-03": "London time agrees with both hand-coded oracles (and zoneinfo when importable) at every 15-min instant of "
             "2026-2027 and at the random instants; fold / gap round trips hold for every minute of the four transition "
             "days; every event log is UTC-monotonic; Free Power leases across the millis() wrap and the DST night end on "
             "their UTC epoch. NC-PB03-a..d killed.",
}

# ------------------------------------------------------------------------------------------------------------------------
# finding fields the sources do not carry
# ------------------------------------------------------------------------------------------------------------------------
# corpus documents that pin a finding (only documents whose classification is the finding's; PASS guard documents of the
# same scenario are listed by the scenario only)
FINDING_CORPUS = {
    "F-FW01-1": ["FW-01-a"], "F-FW01-2": ["FW-01-b"], "F-FW01-3": ["FW-01-d"], "F-FW02-1": ["FW-02-a"],
    "F-FW02-2": ["FW-02-b"], "F-FW03-1": ["FW-03-a"], "F-FW03-2": ["FW-03-b"], "F-FW03-3": ["FW-03-c"],
    "F-HF02-1": ["HF-02-a"], "F-HF02-2": ["HF-02-c"], "F-HF02-3": ["HF-02-d"], "F-HF03-1": ["HF-03-a"],
    "F-HF03-2": ["HF-03-c"], "F-HF05-2": ["HF-05-b"], "F-HF09-1": ["HF-09-a"],
    "F-HF08-1": ["HF-08-a"], "F-HF08-2": ["HF-08-b"], "F-HF08-3": ["HF-08-c", "HF-08-d"], "F-RT03-1": ["RT-03-b"],
}

# test_lab_fw_runtime and test_lab_dst_rtc keep no per-finding table: titles / severity / reachability below condense the
# suites' own FINDING-line and evidence texts; classification / confidence / grade come from the scenario table. A finding
# of a PASS scenario (an incidental finding) carries its own classification / grade / confidence / corpus here, which the
# generator checks against the pinned corpus document, and its own model_dependence when the scenario's model text does
# not describe the finding's run.
FW_RUNTIME_FINDINGS = {
    "F-FW07-1": {"scenario": "FW-07-F",
                 "title": "Free Power restore has no SG-39 link-recovery retry: after a long link outage it waits out the "
                          "rest of the current comms backoff window once the link is back",
                 "severity": "low: cost / availability (the Free Power override stays 0-300 s after link recovery; no "
                             "export); the status stays accurate and an owner End press clears the backoff",
                 "reachability": "INFERRED: a link outage long enough to reach the long comms backoff during a Free Power "
                                 "restore; the extra delay depends on the backoff phase (0-300 s on the watchdog grid)"},
    "F-FW07-2": {"scenario": "FW-07-G",
                 "title": "A reboot while a Dump restore is owed publishes 'ESP RESTARTED DURING LEASE' for a lease that "
                          "had already ended (also after every stuck-lock escalation restart; pinned in corpus FW-07-g, "
                          "FW-08-c, FW-08-d; counted once)",
                 "severity": "diagnostics, low (P3): a display-only text sensor; no package reads it; the restore "
                             "completes and nothing resumes",
                 "reachability": "INFERRED: any reboot between a Dump lease end and its verified restore (a power cut, a "
                                 "crash, an escalation restart)"},
    "F-FW07-3": {"scenario": "FW-07-D",
                 "title": "After a restart with the inverter refusing every 244 write, export stays enabled; ECCO's "
                          "256-261 are contained at the 500 W floor; the owed Stop SOC (record-bound, not the lower "
                          "configured value) governs the supervision",
                 "severity": "safety class (SG-04 export-mode residual), documented accepted residual, low in practice",
                 "reachability": "INFERRED: an inverter that refuses every register 244 write (Modbus exception) around a "
                                 "restart during an owed Dump restore"},
    "F-FW07-4": {"scenario": "FW-07-H",
                 "title": "One failed configuration block read during an ACTIVE Dump lease ends it as 'TELEMETRY LOST - "
                          "failing closed' (explicit fail-closed term, intent not stated in the public docs)",
                 "severity": "low (P3): availability, fail closed; the end reason names telemetry (diagnostics)",
                 "reachability": "INFERRED: one transient failed configuration read during an ACTIVE Dump lease; "
                                 "deterministic once it occurs"},
    "F-FW07-5": {"scenario": "FW-07-I",
                 "classification": "FINDING-NEW", "grade": "VERIFIED", "corpus": ["FW-07-i3"],
                 "confidence": "medium (the mechanism is VERIFIED on the real firmware in two forms with a control; "
                               "whether the documented fast criterion was meant to use battery values from before the "
                               "repeat window is not stated in the public docs)",
                 "title": "The battery range of the fast frozen-CT criterion (dump_ct_same_bmin / bmax) is not re-seeded "
                          "at START or outside a lease: a grid CT already repeating at START with a steady battery ends "
                          "the lease after 7 reads instead of the documented 30-read slow criterion, and the end text "
                          "names a battery movement no reading during the repeats showed (1051 W from the range's boot "
                          "value, or about 1000 W carried over from a previous lease)",
                 "severity": "low (P3): fail closed (an earlier lease end) and diagnostics (a misleading end text); no "
                             "write or gate is affected",
                 "reachability": "INFERRED: a grid CT that already repeats exactly when a Dump START is pressed (for "
                                 "example a CT that stopped updating before the START) with a battery that stays "
                                 "steady; deterministic once it occurs",
                 "model_dependence": "MODEL: meter-noise MODEL off (world noise=False) with explicit grid CT and battery "
                                     "power values for every 10 s poll slot: the CT repeating from the first poll after "
                                     "the boot, the battery steady (moving 2 W); no SOC physics; the carried-over form "
                                     "runs a previous lease first; no power cut"},
    "F-FW08-1": {"scenario": "FW-08-F",
                 "title": "A lock leak recurring before the first watchdog tick of every boot gives an unbounded stuck-lock "
                          "restart loop; the owed Dump restore never runs",
                 "severity": "safety-adjacent, low overall risk (hypothetical trigger); availability (a restart about "
                             "every 203 s) and diagnostics (no CRITICAL status)",
                 "reachability": "UNKNOWN: needs a lock leak that recurs before each boot's first Dump watchdog tick; no "
                                 "such code path is known (the only documented leak cannot overlap a lease)"},
}
DST_RTC_TITLES = {
    "F-HF08-1": "FPS1 repeated autumn hour: an input_datetime 01:xx on 2026-10-25 always means the BST copy (fold=0 "
                "assumption); the GMT copy cannot be scheduled, a later second-copy arm is refused 'scheduled start must "
                "be in the future', and the texts show a bare HH:MM; the DGS1 mirror is under the SG-25 restriction",
    "F-HF08-2": "FPS1 nonexistent spring-forward start (2027-03-28 01:30) is ARMED with no warning and runs one hour from "
                "the typed wall time: 02:30 BST under fold=0, 00:30 GMT under fold=1",
    "F-HF08-3": "SG-25: the firmware Dump START gate and its DGS1 UX mirror walk local minutes from the start's wall time; "
                "on both change nights they admit a lease that really overlaps a charge slot for 30 min, and on the fall "
                "night they spuriously refuse (fail closed); RT-03 RTC-step variant included",
}
F_RT03_1 = {
    "scenario": "RT-03", "classification": "FINDING-KNOWN:SG-25", "duplicate_of": "F-HF08-3", "confidence": "medium",
    "title": "RT-03 RTC-step variant of F-HF08-3: the same Dump START gate admits a lease across a charge slot with the "
             "rig's DST correction lock mid-lease (same root cause, same synthetic slot geometry; merged, not counted)",
    "severity": "low, under the qualified SG-25 severity of F-HF08-3 (known, DEFERRED)",
    "reachability": "INFERRED, low: a Dump lease on a change night against the documented SG-25 operational restriction, "
                    "with the RTC large correction inside the lease",
    "repair_scope": "firmware START gate only (SG-25 as documented, both offsets); no RTC-side change",
}

MODEL_DEPENDENCE = {
    "F-FW01-1": "MODEL: nvs_policy false_negative (the record lands, commit_record returns False) on the used Phase-B "
                "marker key after a completed lease of its domain (V0.1 used-key prelude); synchronous scripts; "
                "synthetic SITE and telemetry; a same-tick watchdog tie broken by an explicit wd_order (the extended "
                "phase sweep covers both orders)",
    "F-FW01-2": "MODEL: nvs_policy false_negative on the used Dump marker key after a completed Dump lease (V0.1 used-key "
                "prelude); the reboot primitive (FULL on_boot, ALWAYS_OFF arms "
                "off); synthetic SITE; both same-tick watchdog orders give the same end state",
    "F-FW01-3": "MODEL: as F-FW01-2; the texts come from the synchronous boot lambda (no timing dependence)",
    "F-FW02-1": "MODEL: nvs_policy false_negative on the used marker key after a completed lease of its domain (V0.1 "
                "used-key prelude); the owner's apply runs through the real Load / Apply buttons and the lab "
                "ORIGINAL follows the owner's landed apply",
    "F-FW02-2": "MODEL: as F-FW02-1; the coincidence set follows the phantom's telemetry-dependent feed-forward ceiling "
                "(synthetic telemetry)",
    "F-FW03-1": "MODEL: two nvs_policy false negatives (reg244 via the core r244_apply action, Dump) or one false negative "
                "plus a boot read_error on the Dump data record, each on a used key after a completed lease of its "
                "domain (V0.1 used-key prelude: a register 244 Apply then its Restore, a one-minute Dump lease)",
    "F-FW03-2": "MODEL: as F-FW03-1 with ORIGINAL 244 = 0; the watchdog order is an explicit parameter (on hardware both "
                "orders are reachable through random interval offsets per boot)",
    "F-FW03-3": "MODEL: as F-FW03-1 (the triple obligation through r244_apply); the text comes from the boot lambda",
    "F-FW04-1": "MODEL: boot fault ('absent', tag) deletes the stored Dump marker before on_boot; synchronous scripts; "
                "synthetic SITE; the preference flush model",
    "F-FW04-2": "MODEL: as F-FW04-1 for the Free Power marker",
    "F-FW04-3": "MODEL: as F-FW04-1 / F-FW04-2, then a later owner START on the residue",
    "F-FW04-4": "MODEL: boot fault ('erase_all',) clears NVS and every preference (ESPHome's erase-and-reinit when "
                "nvs_open fails: path VERIFIED in the local ESPHome 2026.8.2 source, esphome components/esp32/"
                "preferences.cpp:131-148; the trigger, an nvs_open failure at that boot, is INFERRED)",
    "F-FW05-1": "MODEL: nvs_policy false_negative on the used marker key after a completed lease of its domain (V0.1 "
                "used-key prelude); power cuts land between two firmware events (never inside a Modbus frame "
                "or an NVS write)",
    "F-FW05-2": "MODEL: nvs_policy false_negative on a used marker key (V0.1 used-key prelude) plus a boot read_error on "
                "the other domain's stored data record (or a READ_ERROR "
                "marker for the UNKNOWN form); FULL on_boot",
    "F-FW06-1": "MODEL: nvs_policy not_landed / false_negative at each Free Power START commit site (data, marker, retry "
                "reset, journal), on used keys after a completed Free Power lease (V0.1 used-key prelude)",
    "F-FW06-2": "MODEL: nvs_policy false_positive (nothing stored, True) on the used Free Power Phase-B marker key after "
                "a completed lease (V0.1 used-key prelude), so the reboot reads the previous lease's stale CLEAR (the "
                "never-used ABSENT form is no longer injected); no route at the ESPHome layer; an ESP-IDF route (an "
                "INVALID page after a reported flash-op failure) was described by the V0 independent audit (medium "
                "confidence, not executed); trigger UNKNOWN pending the ESP-IDF host NVS test",
    "F-FW06-3": "MODEL: as F-FW06-2 on the Dump Phase-B marker",
    "F-HF02-1": "ASSUMPTION: HA restore-state is saved every 15 min and at a clean stop, and a crash rolls the package "
                "helpers back to the last save; the ESPHome reconnect gap; the latency set (the finding survives every "
                "perturbation tried)",
    "F-HF02-2": "ASSUMPTION: as F-HF02-1; plus a bus window that keeps the run STARTING (synthetic) and a recovery re-stage "
                "that crosses a minute boundary",
    "F-HF02-3": "MODEL: a graceful stop kills running scripts (as HA does); the start helper edited without disarming "
                "(a path around the card's frontend-only lock)",
    "F-HF03-1": "PROXY: the early reset is the core arm_power_cut at START's first Modbus read with the cut entry's "
                "publishes dropped; the first counter sample one 30 s period after power-on (INFERRED)",
    "F-HF03-2": "ASSUMPTION: the restore-state rollback of F-HF02-1; HA and the dongle lose power together; the down-time "
                "sweep decides which of the two outcomes appears",
    "F-HF05-2": "MODEL: command 0.03 s / publish 0.12 s latencies (model values, not measured); via='dongle' needs another "
                "native-API client",
    "F-HF09-1": "ASSUMPTION: S.ServiceError is raised before delivery and is the interpreter's only modelled exception "
                "(a Home Assistant vol.Invalid or a timeout after delivery is not modelled); the outage form rests on the "
                "offline_policy ASSUMPTION ('raise' and 'silent' give the same end state) and on the 0.117 s press flight; "
                "ESPHome's 15-minute no-client reboot, which would clear the switch, is not modelled",
    "F-HF08-1": "ASSUMPTION: Home Assistant resolves an input_datetime wall time with zoneinfo semantics (fold=0)",
    "F-HF08-2": "ASSUMPTION: the fold=0 gap resolution (fold=1 would give 00:30 GMT; both are an hour from the typed time)",
    "F-HF08-3": "MODEL: London local time from the UTC epoch; synthetic charge slots; the firmware gate and the DGS1 walk "
                "run on their real lambda / template",
    "F-RT03-1": "MODEL (split model): RTC lock windows extracted from the RTC rig replayed into a FirmwareWorld; the "
                "inverter's own TOU execution is not modelled (in-slot seconds INFERRED)",
    "F-PB01-1": "MODEL: nvs_policy false_negative drawn by the random generator from published seeds (since V0.1 only on "
                "a key that holds a record; corpus PB-01-a starts with a completed lease)",
    "F-PB01-2": "MODEL: a per-key boot load fault on a stored marker key (READ_ERROR) drawn by the random generator",
    "F-PB01-3": "MODEL: boot fault erase_all (preferences lost too) drawn by the random generator",
    "F-PB01-3:single-key": "MODEL: boot fault ('absent', marker) drawn by the random generator",
    "F-PB01-4": "MODEL: nvs_policy false_positive on the used Dump marker key after a completed Dump lease (corpus "
                "PB-01-d since V0.1; the never-used form is no longer injected); no route at the ESPHome layer; an "
                "ESP-IDF route (an INVALID page after a reported flash-op failure) was described by the V0 independent "
                "audit (medium confidence, not executed); trigger UNKNOWN pending the ESP-IDF host NVS test",
}

# verification summaries: (source-fidelity check, classification check) per finding id; see the module docstring
VERIFICATION = {
    "F-FW01-1": ("confirmed on the real firmware: a Phase-B false negative leaves the RAM mirror clear and the other "
                 "domain's START is admitted; the closest prior record is the firmware's PR41 on_boot comment and S4 "
                 "section 2.10 blind spot 1",
                 "first matched to N15 as the closest registered id, with severity lowered to an availability / cost "
                 "precondition; finally classified FINDING-KNOWN:PR41-GHOST (a registered known risk)"),
    "F-FW01-2": ("FINDING-NEW scoped to the consequence: the lockout, its permanence and its out-of-band exit are "
                 "documented, a genuine override still applied past its end epoch is not",
                 "first KNOWN:N15 with severity lowered to cost / availability medium, safety low; finally FINDING-NEW "
                 "scoped to the consequence"),
    "F-FW01-3": ("confirmed FINDING-NEW, diagnostics low; repair scope corrected (a publish inside the PR41 branch alone is "
                 "overwritten later in the same lambda)",
                 "confirmed FINDING-NEW, diagnostics low"),
    "F-FW02-1": ("confirmed FINDING-KNOWN:N15 (fail closed, zero writes)",
                 "confirmed FINDING-KNOWN:N15, availability low; recorded as a duplicate of F-FW02-2 (one N15 root)"),
    "F-FW02-2": ("confirmed FINDING-KNOWN:N15",
                 "confirmed FINDING-KNOWN:N15; severity lowered from medium to low (owner intent / cost with a "
                 "diagnostics part)"),
    "F-FW03-1": ("N17 kept: the triple obligation is a new route into N17 through evaluation order; severity lowered from "
                 "medium",
                 "confirmed FINDING-KNOWN:N17, safety-rule low; recorded as a duplicate of F-FW05-2 (the lab's N17 owner)"),
    "F-FW03-2": ("confirmed FINDING-KNOWN:N16 (closest registered id, same root: the SG-02 gate has no other-domain term)",
                 "confirmed; severity lowered to availability / cost low; reachability and repair scope corrected (both "
                 "watchdog orders reachable; deferring SG-02 would weaken P0)"),
    "F-FW03-3": ("no independent check: added afterwards as the S4 / reg244 sibling of F-FW01-3, found in the same boot "
                 "source; reproduced on the real on_boot",
                 "no independent check; recorded as a duplicate of F-FW01-3 (same root and repair item)"),
    "F-FW04-1": ("confirmed FINDING-KNOWN:PLATFORM-ABSENT (re-run against the real firmware)",
                 "confirmed; severity kept as safety with the qualifier 'bounded' (ECCO's own supervision is lost, the "
                 "inverter's own protections are untouched); field frequency low / UNKNOWN"),
    "F-FW04-2": ("confirmed FINDING-KNOWN:PLATFORM-ABSENT, cost", "confirmed, cost"),
    "F-FW04-3": ("confirmed",
                 "classification kept; recorded as a consequence row of F-FW04-1 / F-FW04-2 with severity lowered to "
                 "diagnostics (incremental)"),
    "F-FW04-4": ("confirmed (first labelled PLATFORM-ABSENT)",
                 "confirmed; severity narrowed to safety (secondary, bounded); finally classified "
                 "FINDING-KNOWN:NVS-PARTITION-ERASE (S4 section 2.10 blind spot 3)"),
    "F-FW05-1": ("a re-check of F-FW01-1, not an independent finding",
                 "duplicate of F-FW01-1, not counted; severity lowered to an availability precondition; finally "
                 "classified FINDING-KNOWN:PR41-GHOST"),
    "F-FW05-2": ("N17 confirmed; severity low (an R1 ownership overlay, the bank ends at ORIGINAL)",
                 "N17 confirmed, severity diagnostics; no firmware repair needed (bare '!other_corrupt' terms are shown "
                 "unsafe by in-memory mutants)"),
    "F-FW06-1": ("confirmed FINDING-NEW, diagnostics",
                 "confirmed FINDING-NEW, diagnostics; repair scope refined to keep the restore hand-off the existing "
                 "journal suite pins"),
    "F-FW06-2": ("FINDING-NEW rather than PLATFORM-ABSENT: that entry matches neither the trigger nor the realistic "
                 "stale-CLEAR boot state",
                 "FINDING-NEW with confidence low (no physical trigger identified by that check; the V0 independent "
                 "audit later described an ESP-IDF route, medium confidence, not executed)"),
    "F-FW06-3": ("mechanism confirmed (first labelled PLATFORM-ABSENT as the false-positive variant of F-FW04-1)",
                 "reconciled to FINDING-NEW with confidence low: a used device boots on the previous lease's stale CLEAR "
                 "marker, not ABSENT"),
    "F-FW07-1": ("confirmed FINDING-NEW, low (cost / availability)",
                 "confirmed; reworded to 'the rest of the current backoff window' (the delay depends on the backoff "
                 "phase)"),
    "F-FW07-2": ("confirmed FINDING-NEW, diagnostics low; reworded from 'overwrites' to 'misattributes' (a RAM-only text "
                 "sensor)",
                 "confirmed, diagnostics low (P3)"),
    "F-FW07-3": ("confirmed FINDING-KNOWN:FCP2-R1 (documented accepted residual)",
                 "confirmed; low practical severity; the 500 W containment bounds ECCO's own discharge slots, not PV "
                 "export"),
    "F-FW07-4": ("mechanism confirmed against the real handlers; NEW only against the public documents and the known-risk "
                 "registry (explicit fail-closed code with no stated rationale)",
                 "confirmed FINDING-NEW; priority lowered to P3; confidence that it is unintended low"),
    "F-FW07-5": ("no independent check: found incidentally while FW-07-I was built; reproduced on the real firmware in two "
                 "forms (the range at its boot value, the range carried over from a previous lease) with a control (a CT "
                 "that changes after the 30 s grace) and a repair-direction mutant",
                 "no independent check; FINDING-NEW (neither the public documents nor the known-risk registry state it), "
                 "fail closed, P3"),
    "F-FW08-1": ("confirmed FINDING-KNOWN:FCP2-F6 (a refinement of the restart-loop residual)",
                 "confirmed; availability / cost with a diagnostics defect, safety-adjacent only if the hypothetical "
                 "trigger exists; confidence low"),
    "F-HF01-1": ("confirmed FINDING-NEW: the new part is the firmware end tail no budget covers and the model-only +30 s "
                 "check",
                 "confirmed; severity diagnostics / documentation, cost negligible; confidence medium"),
    "F-HF04-1": ("confirmed", "confirmed; severity lowered to low (pre-warned by the readiness alert, alerted with a remedy)"),
    "F-HF04-2": ("confirmed (availability)",
                 "confirmed; severity low-medium (availability / cost plus diagnostics, not safety)"),
    "F-HF04-3": ("confirmed (fails closed; the refusal names the wrong cause)", "confirmed, low"),
    "F-HF06-1": ("confirmed (test-model fidelity, not a product defect)", "confirmed, low (test coverage)"),
    "F-HF06-2": ("confirmed, diagnostics low", "confirmed, diagnostics low"),
    "F-HF06-3": ("confirmed, diagnostics low", "confirmed, diagnostics low"),
    "F-HF02-1": ("confirmed: the mechanism is in the shipped FPS1 / DGS1 startup recovery and survives every model "
                 "perturbation tried; the load-bearing premises are the rollback instant and the already-ended lease",
                 "confirmed FINDING-NEW, low (owner intent / cost)"),
    "F-HF02-2": ("suggested FINDING-NEW with SMR1-UNCLEAN-SHUTDOWN as its related premise",
                 "FINDING-KNOWN:SMR1-UNCLEAN-SHUTDOWN with the understated consequence named in the title (the suite "
                 "follows this classification)"),
    "F-HF02-3": ("confirmed", "confirmed, diagnostics low"),
    "F-HF03-1": ("narrowed to the HA-side press-proof weakness after a dongle reset; grade INFERRED (proxy)",
                 "confirmed FINDING-NEW, low"),
    "F-HF03-2": ("same startup-recovery root as F-HF02-1 (one defect, two triggers); the new lease is in effect silent",
                 "confirmed FINDING-NEW, low; kept as its own counted entry in the suite"),
    "F-HF05-2": ("suggested FINDING-NEW (the realistic trigger window lies outside the documented one; the documented "
                 "consequence is wrong)",
                 "FINDING-KNOWN:SMR1-OWNER-RESTORING with the wrong documented consequence named in the title (the suite "
                 "follows this classification)"),
    "F-HF07-1": ("narrowed to the HA-side diagnostics gap (the firmware half is FW-01)",
                 "FINDING-NEW narrowed to the HA diagnostics chain, MEDIUM (downgraded from cost / availability)"),
    "F-HF07-2": ("FINDING-NEW: the HA reporting gap; the root is FW-01",
                 "confirmed, diagnostics low-medium; recorded as the DGS1 mirror instance of F-HF07-1 and merged into it "
                 "(one HA-side repair covers both), not counted"),
    "F-HF07-3": ("the coupled-tier view of F-FW06-1, not an independent defect",
                 "confirmed FINDING-NEW, diagnostics low; the suite marks it a duplicate of F-FW06-1"),
    "F-HF07-4": ("FINDING-KNOWN: the firmware's own documented PR41 pre-boot residual",
                 "first the closest id N15 with severity lowered to a latent precondition; finally classified "
                 "FINDING-KNOWN:PR41-GHOST, duplicate of F-FW01-1"),
    "F-HF07-5": ("the HA-reachable extension of F-FW01-3",
                 "confirmed FINDING-NEW, diagnostics low; the suite marks it a duplicate of F-FW01-3"),
    "F-HF08-1": ("confirmed FINDING-NEW for FPS1 (publicly undocumented); the DGS1 half falls under the documented SG-25 "
                 "operational restriction",
                 "confirmed, low; real-HA fold resolution INFERRED (confidence medium)"),
    "F-HF08-2": ("confirmed FINDING-NEW (publicly undocumented)", "confirmed; severity lowered to diagnostics / UX low"),
    "F-HF08-3": ("confirmed FINDING-KNOWN:SG-25 (documented, deferred)",
                 "confirmed; severity qualified: a precautionary gate misses a case, no hazard demonstrated here"),
    "F-HF09-1": ("no independent check: added with HF-09; reproduced against the real firmware and packages in five forms "
                 "(three service errors in each domain; API outages under offline_policy 'raise' and 'silent'), with a "
                 "40 s boundary twin and the negative controls NC-HF09-1 to NC-HF09-3",
                 "no independent check; FINDING-NEW: the public incident records cover a write enable left on only for a "
                 "restart case, not this end state or the blocked SMR1 restore; P3, reachability very low"),
    "F-RT03-1": ("confirmed SG-25, a sub-aspect of F-HF08-3",
                 "recorded as a variant of F-HF08-3 (same gate, same root), not a separate finding: merged, not counted"),
    "F-PB01-1": ("confirmed (same root as F-FW01-1)",
                 "confirmed, availability / cost low-medium (no latent safety impact); classified "
                 "FINDING-KNOWN:PR41-GHOST"),
    "F-PB01-2": ("confirmed N17", "confirmed, low (an ownership-integrity residual)"),
    "F-PB01-3": ("confirmed (first labelled PLATFORM-ABSENT; the more exact anchor is S4 section 2.10 blind spot 3)",
                 "confirmed; classified FINDING-KNOWN:NVS-PARTITION-ERASE; duplicate of F-FW04-4"),
    "F-PB01-3:single-key": ("covered by the F-PB01-3 checks (its single-key form)",
                            "FINDING-KNOWN:PLATFORM-ABSENT; duplicate of F-FW04-2"),
    "F-PB01-4": ("same end state as FW-04-a / FW-06-c; not a separate mechanism",
                 "FINDING-NEW, confidence low; duplicate of F-FW06-3"),
}

# ------------------------------------------------------------------------------------------------------------------------
# two-axis verdicts (V0.1): every COUNTED finding carries a mechanism verdict, a device-reachability verdict and whether
# its smallest adequate repair needs a product change; every ledger entry (counted or not) names its injected primitive.
# gen_catalogue writes them as the finding fields mechanism_verdict, device_reachability, injected_primitive,
# needs_product_change and needs_product_change_reason (the verdict fields are null for a DUPLICATE or MERGED entry: it is
# graded through its owner), refuses an unknown value, a missing or stale key, and checks the NVS reachability-text rule
# below; run_lab prints the distribution from the catalogue. 0 counted findings have VERIFIED device reachability.
# ------------------------------------------------------------------------------------------------------------------------
MECHANISM_VERDICTS = {
    "CONFIRMED-IN-SIMULATION": "given the trigger, the deviation was reproduced by executing the real production source "
                               "(firmware lambdas / HA package YAML) in the lab, with a finding pin and a corpus "
                               "document; says nothing about whether the trigger occurs on the device",
    "PLAUSIBLE-UNDER-ASSUMPTIONS": "the deviation follows in the lab only through a stated proxy or an unverifiable "
                                   "platform assumption that is itself part of the mechanism (a PROXY reproduction "
                                   "graded INFERRED, or an HA-core semantic such as the input_datetime fold=0 "
                                   "resolution)",
    "NOT-CONFIRMED": "reserved: the mechanism did not reproduce or contradicts source; a finding with this verdict is "
                     "reclassified, not counted (no counted finding may carry it)",
}
DEVICE_REACHABILITY = {
    "VERIFIED": "the trigger was observed on the real device stack (ESP32 + ESPHome 2026.8.2 + ESP-IDF 5.5.5, real Home "
                "Assistant, real inverter) or reproduced by executing that platform code",
    "PLAUSIBLE-UNDER-ASSUMPTIONS": "the trigger is an ordinary event (a reboot, a power cut, a link outage, a failed "
                                   "Modbus read, an owner action, a DST night, chained schedules) or a platform "
                                   "behaviour reported by sources, and reaches the device if the stated assumptions "
                                   "hold; its rate is stated separately (often UNKNOWN / low)",
    "UNKNOWN": "the trigger rests on an injected lab primitive whose device route is unestablished or contested (every "
               "NVS primitive: 'UNKNOWN pending the ESP-IDF host NVS test') or on a fault with no known code path; an "
               "offline platform test could settle it",
    "UNVERIFIABLE-OFFLINE": "the trigger depends on the behaviour of a component the lab cannot execute or read offline "
                            "(Home Assistant core restore-state cadence and crash rollback, an inverter refusing a "
                            "register write); only a bench or live observation could settle it",
    "NOT-APPLICABLE": "the finding makes no device claim (a test-model or documentation item); reachability is not "
                      "graded",
}
PRODUCT_CHANGE = {
    "yes": "the smallest adequate repair changes firmware or HA package behaviour (code, templates, automations), "
           "including a repair shared with another finding (named)",
    "no": "none needed (a documented residual or documented limit), or the repair is documentation, field text or the "
          "test model only",
}
# injected-primitive classes; the class is also readable from the text: a text starts with 'nvs ' or 'boot ' exactly for
# the nvs class and with 'none' exactly for the none class (run_lab.primitive_kind, which the report uses; gen_catalogue
# checks that the two agree)
PRIMITIVE_CLASSES = {
    "nvs": "an injected NVS primitive: nvs_policy false_negative / not_landed / false_positive, or a boot fault absent / "
           "read_error / wrong_size / erase_all / read_error_all",
    "modbus": "an injected Modbus fault outcome through modbus_policy (error, no_response, ack_not_applied ...)",
    "link": "set_link down / up (a link outage)",
    "power": "a power cut or reboot primitive as the trigger (reboot, arm_power_cut, reboot_dongle)",
    "ram": "a white-box RAM injection (inject_global), never firmware behaviour",
    "ha_restart": "a Home Assistant restart: graceful, or a crash with restore-state rollback (ASSUMPTION)",
    "ha_service": "a Home Assistant service-call exception or API outage (S.ServiceError before delivery, "
                  "offline_policy 'raise')",
    "none": "no injected fault: ordinary operation, owner actions, schedule timing, DST nights, synthetic telemetry",
}
# The reachability text of every ledger entry whose injected primitive is an NVS primitive starts with this text for
# its device reachability (a DUPLICATE / MERGED entry: its owner's): 'UNKNOWN pending the ESP-IDF host NVS test' for
# every NVS finding, except a group listed in NVS_REACHABILITY_GROUPS (RC-FALSE-ABSENT: PLAUSIBLE-UNDER-ASSUMPTIONS, the
# boot 'absent' route being ESP-IDF erasure of a corrupt entry, REPORTED, whose rate the ESP-IDF test settles).
NVS_REACHABILITY_TEXT = {
    "UNKNOWN": "trigger: {primitive}; device reachability: UNKNOWN pending the ESP-IDF host NVS test",
    "PLAUSIBLE-UNDER-ASSUMPTIONS": "trigger: {primitive}; device reachability: PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN "
                                   "pending the ESP-IDF host NVS test",
}
NVS_REACHABILITY_GROUPS = {"RC-FALSE-ABSENT": "PLAUSIBLE-UNDER-ASSUMPTIONS"}
# counted fid -> (mechanism_verdict, device_reachability, needs_product_change, needs_product_change_reason)
VERDICTS = {
    "F-FW01-1": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "firmware: keep the RAM mirror fail-closed at the Phase-B false-return branches (FP FW:9233-9240, "
                 "Dump FW:18555-18558, reg244 FW:17204-17211) incl. the success branch's pacing reset FW:9184-9187"),
    "F-FW01-2": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "trigger removed by F-FW01-1's repair; HA-side LOCKED mapping + notification; PR41 design review"),
    "F-FW01-3": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "firmware status text only (lambda-local flag in the PR41 branch + a RAM cause global for the "
                 "runtime refusals)"),
    "F-FW02-2": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "shared: F-FW01-1's repair (no phantom outlives its runtime); the classifier must not change"),
    "F-FW03-2": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "shared: F-FW01-1's repair makes the dual-obligation construction unreachable; optional diagnostics "
                 "text"),
    "F-FW04-1": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "on_boot cross-check: ABSENT marker + data active_persisted == 1 -> the existing UNKNOWN lockout "
                 "(audit-refined Dump form: active_persisted == 1 && restore_requested == 0)"),
    "F-FW04-2": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "as F-FW04-1 (Free Power needs a data-record closure commit for the refined check)"),
    "F-FW04-3": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "shared: the F-FW04-1 cross-check refuses the laundering START (single-key case)"),
    "F-FW04-4": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "HA package: a 'lease vanished across a dongle reboot' alert (no firmware-local cross-check closes "
                 "it)"),
    "F-FW05-2": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "no",
                 "none needed: N17 is the S4 record's accepted residual; bare '!other_corrupt' terms are unsafe "
                 "(in-memory mutants)"),
    "F-FW06-1": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "start_free_power_override branch order / text only (no write, gate or durable change)"),
    "F-FW06-2": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "start_free_power_override: read the marker back after the Phase-B commit (only if the trigger is "
                 "confirmed)"),
    "F-FW06-3": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "start_dump_to_grid_override: read the marker back after the Phase-B commit (only if the trigger is "
                 "confirmed)"),
    "F-FW07-1": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "firmware: Free Power restore pacing gets the Dump SG-39 link-recovery clause"),
    "F-FW07-2": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "firmware Dump boot block: a distinct end text when a restore was already owed"),
    "F-FW07-3": ("CONFIRMED-IN-SIMULATION", "UNVERIFIABLE-OFFLINE", "no",
                 "none in firmware: documented accepted residual FCP2-R1 (the owner clears 244 at the inverter)"),
    "F-FW07-4": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "firmware Dump watchdog: (a) a distinct end reason (diagnostics); (b) narrowing "
                 "configuration_online is a design decision"),
    "F-FW07-5": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "firmware START re-seeds dump_ct_same_bmin / bmax (a design decision) or a diagnostics-only text"),
    "F-FW08-1": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "firmware design decision: a stuck-restart counter in RTC no-init memory + a CRITICAL status"),
    "F-HF01-1": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "no",
                 "documentation / test only: the window_end_ts field text (FPS1:77, DGS1:90) and the HA suites' "
                 "model-only +30 s check (test_ecco_free_power_schedule_reliability.py:199, "
                 "test_ecco_dump_to_grid_schedule_reliability.py:277)"),
    "F-HF02-1": ("CONFIRMED-IN-SIMULATION", "UNVERIFIABLE-OFFLINE", "yes",
                 "FPS1 / DGS1 startup recovery: require crash-proof evidence before restarting a window (design "
                 "decision)"),
    "F-HF02-2": ("CONFIRMED-IN-SIMULATION", "UNVERIFIABLE-OFFLINE", "no",
                 "documentation-only primary repair (extend the 'Unclean shutdown' limit text, "
                 "docs/dev/schedule-manual-restore.md:71-73 and the package header); the SMR1 track hardening is "
                 "optional"),
    "F-HF02-3": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 / DGS1 startup recovery 'now_ts < start_ts' branch: record + notification"),
    "F-HF03-1": ("PLAUSIBLE-UNDER-ASSUMPTIONS", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 / DGS1 no-answer branch: capture the per-boot nonce with attempts_before (HA side, read-only)"),
    "F-HF03-2": ("CONFIRMED-IN-SIMULATION", "UNVERIFIABLE-OFFLINE", "yes",
                 "DGS1 / FPS1 startup recovery honours dongle-held evidence (design decision whether any resume is "
                 "wanted)"),
    "F-HF04-1": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 package: arm-time check / pre-check against a running Dump lease (no firmware change)"),
    "F-HF04-2": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 / DGS1: bounded wait in the stage-nothing / press-nothing branch, or drop the 'already "
                 "active' alert exemption"),
    "F-HF04-3": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "DGS1 arm validation: refuse with an explicit 'Free Power is active' text"),
    "F-HF05-2": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "no",
                 "documentation-only primary repair (docs/dev/schedule-manual-restore.md:70 claims PARTIAL / FAILED; "
                 "the change is overwritten and RESTORED reported); the SMR1 track change is optional"),
    "F-HF06-1": ("CONFIRMED-IN-SIMULATION", "NOT-APPLICABLE", "no",
                 "test only: the HA dongle models S.Dongle / D.DumpDongle (no product write path)"),
    "F-HF06-2": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "DGS1 recorded-result template text (package) or the firmware text"),
    "F-HF06-3": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 result text based on firmware truth (package)"),
    "F-HF07-1": ("CONFIRMED-IN-SIMULATION", "UNKNOWN", "yes",
                 "HA-side read-only: FPS1 / DGS1 map a structured lockout signal to LOCKED + one notification"),
    "F-HF08-1": ("PLAUSIBLE-UNDER-ASSUMPTIONS", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 arm validation: refuse an ambiguous local start"),
    "F-HF08-2": ("PLAUSIBLE-UNDER-ASSUMPTIONS", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 arm validation: refuse a nonexistent local start"),
    "F-HF08-3": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "firmware START gate: the documented, deferred SG-25 fix"),
    "F-HF09-1": ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "yes",
                 "FPS1 / DGS1 closing step: see the write enable off, else name it in the alert (package)"),
}
# every ledger fid -> (primitive class, injected primitive)
PRIMITIVES = {
    "F-FW01-1": ("nvs", "nvs false_negative on a used Phase-B marker (fp.valid; dump.valid in the mirror order)"),
    "F-FW01-2": ("nvs", "nvs false_negative on the used Dump Phase-B marker (dump.valid), then a reboot inside the "
                        "admitted Free Power lease"),
    "F-FW01-3": ("nvs", "nvs false_negative on the used Dump Phase-B marker (dump.valid), then a reboot (the PR41 "
                        "lockout precondition)"),
    "F-FW02-2": ("nvs", "nvs false_negative on the used Dump Phase-B marker (dump.valid), an owner write equal to an "
                        "ECCO value (the phantom ceiling or the 500 W floor), then a reboot"),
    "F-FW03-2": ("nvs", "nvs false_negative on the used Dump Phase-B marker (and on reg244 in the suite's triple "
                        "form) plus a boot read_error on the stored Dump data record"),
    "F-FW04-1": ("nvs", "boot absent of the held Dump marker (dump.valid) during an ACTIVE lease (route: ESP-IDF "
                        "erasure of a corrupt entry, REPORTED)"),
    "F-FW04-2": ("nvs", "boot absent of the held Free Power marker (fp.valid) during an ACTIVE lease (route: ESP-IDF "
                        "erasure of a corrupt entry, REPORTED)"),
    "F-FW04-3": ("nvs", "boot absent of the held Dump marker (dump.valid), then a later owner START on the residue"),
    "F-FW04-4": ("nvs", "boot erase_all (ESPHome erase-and-reinit when nvs_open fails: path VERIFIED, esphome "
                        "components/esp32/preferences.cpp:131-148; trigger INFERRED)"),
    "F-FW05-2": ("nvs", "nvs false_negative on the used Dump Phase-B marker plus a boot read_error on the stored "
                        "Dump data record (the UNKNOWN form: a READ_ERROR marker)"),
    "F-FW06-1": ("nvs", "nvs not_landed / false_negative at a Free Power START commit site (data, marker, retry "
                        "reset, journal) on a used key (corpus FW-06-a: not_landed on fp.data)"),
    "F-FW06-2": ("nvs", "nvs false_positive on the used Free Power Phase-B marker (fp.valid), then a reboot during "
                        "the lease"),
    "F-FW06-3": ("nvs", "nvs false_positive on the used Dump Phase-B marker (dump.valid), then a reboot during the "
                        "lease"),
    "F-FW07-1": ("link", "link outage (set_link down / up) during a Free Power restore"),
    "F-FW07-2": ("power", "power cut / reboot between a Dump lease end and its verified restore"),
    "F-FW07-3": ("modbus", "Modbus fault outcome write:244 -> error on every attempt (the inverter refuses the "
                           "write), across a reboot"),
    "F-FW07-4": ("modbus", "Modbus fault outcome on one configuration block read (corpus FW-07-h: read:241x53 -> "
                           "no_response; the suite sweeps every allow-listed failure outcome)"),
    "F-FW07-5": ("none", "none (synthetic telemetry: a grid CT repeating from the first poll, battery steady; "
                         "meter-noise MODEL off)"),
    "F-FW08-1": ("ram", "RAM white-box injection inject_global manual_write_in_progress = true, recurring before "
                        "every boot's first watchdog tick"),
    "F-HF01-1": ("none", "none (scheduler / bus timing: watchdog phase, the recorded-busy-window bus model)"),
    "F-HF02-1": ("ha_restart", "Home Assistant crash with restore-state rollback (restart_ha rollback_to_utc) after "
                               "the lease ended"),
    "F-HF02-2": ("ha_restart", "Home Assistant crash with restore-state rollback while STARTING (synthetic bus-busy "
                               "window)"),
    "F-HF02-3": ("ha_restart", "graceful Home Assistant restart while STARTING after the owner moved the start "
                               "helper (no rollback)"),
    "F-HF03-1": ("power", "dongle power cut at the START's first Modbus read (arm_power_cut PROXY, the cut entry's "
                          "publishes dropped)"),
    "F-HF03-2": ("power", "whole-site power cut: HA crash with restore-state rollback plus a dongle reboot"),
    "F-HF04-1": ("none", "none (Free Power armed after the Dump run started, at the Dump window end)"),
    "F-HF04-2": ("none", "none (same-function windows chained back to back)"),
    "F-HF04-3": ("none", "none (a Dump arm during a Free Power lease)"),
    "F-HF05-2": ("none", "none (an owner edit within about one command + publish latency of SMR1's restore write; "
                         "model latencies)"),
    "F-HF06-1": ("modbus", "Modbus fault outcome write:256 -> ack_not_applied (activation verify failure)"),
    "F-HF06-2": ("modbus", "Modbus fault outcome write:256 -> ack_not_applied (activation verify failure)"),
    "F-HF06-3": ("modbus", "Modbus fault outcome write:256 -> ack_not_applied (activation verify failure)"),
    "F-HF07-1": ("nvs", "nvs false_negative on the used Dump Phase-B marker (dump.valid, mirror b), then a dongle "
                        "power cut inside the admitted Free Power lease"),
    "F-HF07-2": ("nvs", "nvs false_negative on the used Free Power Phase-B marker (fp.valid, mirror a), then a "
                        "dongle power cut inside the admitted Dump lease"),
    "F-HF08-1": ("none", "none (FPS1 armed inside 01:00-02:00 local on the fall-back night)"),
    "F-HF08-2": ("none", "none (a typed 01:00-01:59 start on the spring-forward night)"),
    "F-HF08-3": ("none", "none (a Dump lease on a change night across a charge-slot boundary, against the documented "
                         "restriction)"),
    "F-HF09-1": ("ha_service", "ESPHome API outage of about 70 s from inside the press flight under offline_policy "
                               "'raise' (corpus HF-09-a); in the suite also S.ServiceError on three consecutive "
                               "calls (fail_services)"),
    "F-FW02-1": ("nvs", "nvs false_negative on the used Free Power Phase-B marker (fp.valid), an owner apply, then a "
                        "reboot"),
    "F-FW03-1": ("nvs", "nvs false_negative on the used Dump Phase-B marker (and on reg244 in the triple form) plus "
                        "a boot read_error on the stored Dump data record"),
    "F-FW03-3": ("nvs", "nvs false_negative on the used reg244 and Dump Phase-B markers"),
    "F-FW05-1": ("nvs", "nvs false_negative on a used Phase-B marker"),
    "F-HF07-3": ("nvs", "nvs false_negative on the used Free Power Phase-B marker (fp.valid; the phantom START)"),
    "F-HF07-4": ("nvs", "nvs false_negative on a used Phase-B marker (both mirrors)"),
    "F-HF07-5": ("nvs", "nvs false_negative on a used Phase-B marker, then a dongle power cut (the PR41 lockout)"),
    "F-PB01-1": ("nvs", "nvs false_negative on a used Phase-B marker, drawn by the PB-01 generator"),
    "F-PB01-2": ("nvs", "boot read_error on a stored marker key, drawn by the PB-01 generator"),
    "F-PB01-3": ("nvs", "boot erase_all, drawn by the PB-01 generator (path VERIFIED, esphome "
                        "components/esp32/preferences.cpp:131-148)"),
    "F-PB01-3:single-key": ("nvs", "boot absent of a held marker, drawn by the PB-01 generator"),
    "F-PB01-4": ("nvs", "nvs false_positive on the used Dump Phase-B marker (dump.valid)"),
    "F-RT03-1": ("none", "none (RTC lock windows from the RTC rig replayed into a FirmwareWorld)"),
}

# Reclassification records: a finding id a suite drafted and then reclassified, kept OUT of the counted ledger. Each
# suite's own RECLASSIFIED table must hold exactly these ids with a text starting with the given verdict; a 'PASS' id is
# no catalogue finding and prints no FINDING line; a 'merged into <owner>' id is the MERGED ledger entry of that owner.
#   fid -> (suite, the start of the suite's RECLASSIFIED text)
RECLASSIFIED = {
    "F-RT02-1": ("test_lab_dst_rtc", "PASS"),                    # documented behaviour (RT-02)
    "F-RT03-1": ("test_lab_dst_rtc", "merged into F-HF08-3"),    # RT-03 RTC-step variant of SG-25
    "F-HF05-1": ("test_lab_ha_lifecycle", "PASS"),               # documented limit SMR1-OWNER-STAGING (HF-05)
}

# ------------------------------------------------------------------------------------------------------------------------
# phase sensitivity: scenario / finding id -> (reason, [PHASE_SENSITIVE_TAGS prefixes of its suite]). The catalogue sets
# phase_sensitive true with this reason for every id listed; the tags themselves were found by running every suite under
# an in-memory ESPHome-like scheduler phase patch (first run at setup + startup delay + a seeded offset in [0, min(T/2,
# 5 s)), reschedule at now+T; 17 quick configurations and 3 extended seeds, outside the lab) plus the audit's list of
# timing-bound checks and the V0.1 review's additions (a grid point that changes branch with no FAIL line, a meta-check
# that depends on it, and four corpus FINDING documents that fail an expectation while their suite pins hold; the
# review's 11 patched quick configurations are the full patch's 8 seeds and the power-on-anchored variant's 3 seeds).
# gen_catalogue checks every prefix against the suite's registry and that every registry tag of a
# scenario suite is listed here or is a pure corpus trace-digest pin (every corpus document's digest is bound to the
# lab's phase by construction; that alone does not flag a scenario).
# ------------------------------------------------------------------------------------------------------------------------
PHASE_SENSITIVE = {
    "FW-03": ("the watchdog that runs first on the tick after the boot decides the outcome: the lab ties the Free Power "
              "and Dump watchdogs (same period and startup delay, zero offset) and orders them by an explicit parameter, "
              "while ESPHome draws an independent random offset for each; F-FW03-1's reproduction and the Free "
              "Power-first sweep point depend on that order, F-FW03-2's pin is composite (both explicit orders in one "
              "run) and so fails by construction under random offsets although its Dump-first signature still "
              "reproduces whenever the Dump watchdog's offset is the smaller, and corpus FW-03-b's expectations are "
              "timeline-bound",
              ["finding-reproduces:F-FW03-1", "finding-reproduces:F-FW03-2",
               "FW-03 order sweep: FP first with ORIGINAL 244 = 0",
               "every finding in the table was reproduced exactly once in this run",
               "EXT FW-03 watchdog phase sweep (de-aligned watchdogs)", "corpus FW-03-b: replay ok ("]),
    "F-FW03-1": ("its reproduction needs one watchdog order on the tick after the boot (a lab tie broken by an explicit "
                 "parameter); it fails under an ESPHome-like phase patch at some seeds (10 of 17 patched quick "
                 "configurations)",
                 ["finding-reproduces:F-FW03-1"]),
    "F-FW03-2": ("a composite pin: it needs both explicit wd_order outcomes (the Dump-first context hold with its operator "
                 "exits and the Free Power-first N17 contrast) in one run, so under an ESPHome-like phase patch, where "
                 "the random offsets fix one order per boot, it fails by construction (17 of 17 patched quick "
                 "configurations); its Dump-first context-hold signature reproduces whenever the Dump watchdog's random "
                 "offset is the smaller (the context hold with its operator exits held in 10 of those 17; a V0.1 review "
                 "probe of both the triple and the unreadable-data construction gives it at full-patch seeds 1, 3, 4 "
                 "and 8 of 1 to 8 and power-on seeds 1 and 3 of 1 to 3, both wd_order values giving the same outcome "
                 "at every seed)",
                 ["finding-reproduces:F-FW03-2"]),
    "FW-05": ("only corpus FW-05-e's expectations are timeline-bound: under an ESPHome-like phase patch one fails at some "
              "seeds (the directed cut-run checks held)",
              ["corpus FW-05-e: replays ok ("]),
    "F-FW05-2": ("corpus FINDING document FW-05-e timeline-bound under an ESPHome-like phase (it failed an expectation in "
                 "6 of the V0.1 review's 11 patched quick configurations); the suite pins hold",
                 ["corpus FW-05-e: replays ok ("]),
    "FW-06": ("only corpus FW-06-a's expectations are timeline-bound: since V0.1 its writes expectation lists the used-key "
              "prelude's writes with their event sequence numbers and instants, which an ESPHome-like phase patch changes "
              "(it failed in all 17 patched quick configurations; the directed checks held)",
              ["corpus FW-06-a: replays ok ("]),
    "F-FW06-1": ("corpus FINDING document FW-06-a timeline-bound under an ESPHome-like phase (its writes expectation lists "
                 "the used-key prelude's writes with their event sequence numbers; it failed in 11 of the V0.1 review's "
                 "11 patched quick configurations); the suite pins hold",
                 ["corpus FW-06-a: replays ok ("]),
    "FW-07-A": ("which runs first after the link recovery, the first telemetry poll (10 s) or the Dump watchdog's restore "
                "pre-read (15 s), is the two intervals' relative phase: on the lab grid the poll wins and the restore is "
                "the SG-39 path; at ESPHome-like offsets the watchdog usually runs first, the every-tick supervision "
                "restores within the bound and the NC-FW07-1 kill is lost",
                ["FW-07-A: the recovery restore is the SG-39 path", "NC-FW07-1 (FW-07) mutant killed",
                 "every scenario family has at least one killed negative control and no mutant survived"]),
    "FW-07-E": ("the boot-path restore is pinned to the first watchdog tick at uptime 15 s (the startup delay with zero "
                "offset); ESPHome runs that first tick at setup + 15 s + a random offset below 5 s",
                ["FW-07-E dump: the lease STARTed with a valid clock", "FW-07-E fp: the lease STARTed with a valid clock"]),
    "FW-07-I": ("the rebased boot-restore bound is the first watchdog tick 15 s after the boot (zero offset), the "
                "frozen-end windows and same-tick checks sit on the 10 s poll / 15 s watchdog grid, the F-FW07-5 control "
                "counts identical reads between explicit telemetry actions and the watchdog's end, and the corpus "
                "expectations are timeline-bound",
                ["FW-07-I: every explicit telemetry action lies strictly between two poll slots", "FW-07-I ct INV-17:",
                 "FW-07-I bp INV-17:", "FW-07-I soc INV-17:", "FW-07-I ct: the power cut fired at the Dump restore's write",
                 "FW-07-I bp: the power cut fired at the Dump restore's write",
                 "FW-07-I soc: the power cut fired at the Dump restore's write",
                 "FW-07-I ct INV-RESTORE-BOUND rebased at the boot", "FW-07-I bp INV-RESTORE-BOUND rebased at the boot",
                 "FW-07-I soc INV-RESTORE-BOUND rebased at the boot",
                 "FW-07-I soc: corpus FW-07-i2's last action (at_s I_SOC_END_AT) comes after the boot-path restore",
                 "FW-07-I after: the frozen end's restore completes in the same watchdog tick",
                 "FW-07-I after: the owner's new START on the still-frozen CT is accepted",
                 "F-FW07-5 control (the documented criteria hold when the range is seeded inside the lease)",
                 "EXT FW-07-I:", "corpus FW-07-i (", "corpus FW-07-i2 (", "corpus FW-07-i3 ("]),
    "F-FW07-5": ("corpus FINDING document FW-07-i3 timeline-bound under an ESPHome-like phase (it failed an expectation in "
                 "10 of the V0.1 review's 11 patched quick configurations: the end text counts 6 identical readings "
                 "instead of 7); the suite pins hold",
                 ["corpus FW-07-i3 ("]),
    "FW-08-B": ("the INV-20 escalation bound (a restart within the stuck-lock limit plus two 5 s census periods, the "
                "boot-path restore at the first watchdog tick) sits on the census / watchdog grid; corpus FW-08-c's "
                "expectations are timeline-bound",
                ["FW-08-B INV-20:", "EXT FW-08-B:", "corpus FW-08-c ("]),
    "FW-08-C": ("the INV-20 escalation bound (restart and boot restore) sits on the census / watchdog grid; corpus "
                "FW-08-d's expectations are timeline-bound",
                ["FW-08-C INV-20:", "corpus FW-08-d ("]),
    "FW-08-D": ("the Free Power analogue of FW-08-B: the same escalation bound on the census / watchdog grid; corpus "
                "FW-08-e's expectations are timeline-bound",
                ["FW-08-D INV-20:", "corpus FW-08-e ("]),
    "HF-01": ("the exact lease-end overruns F-HF01-1 pins (the values above 30 s) are the first watchdog slot after the "
              "window end on the lab's 15 s grid; the HF-01-a..c corpus expectations are timeline-bound",
              ["finding-reproduces:F-HF01-1", "all 9 corpus documents exist, replay ok"]),
    "F-HF01-1": ("the pinned overrun values are one watchdog phase (the first slot after the window end on the lab's 15 s "
                 "grid); the exact pins fail under an ESPHome-like phase patch in all 17 patched quick configurations",
                 ["finding-reproduces:F-HF01-1"]),
    "HF-03": ("the early-reset reach (which swept points retry) is the first-sample phase of the 30 s polled attempt "
              "counter, which the lab takes one period after power-on (4 of 6 points on the lab grid, 5 of 6 under an "
              "ESPHome-like phase patch); the whole-site cut (HF-03.4) is refused by LabUnsupported (the suite stops: "
              "an interleaving inside a projected firmware transaction) at most ESPHome-like phases (12 of 17 patched "
              "quick configurations), and where it runs the whole-site cut grid's branch per point and the finding "
              "register (it holds only while every finding prints) are phase-dependent; corpus HF-03-a's expectations "
              "are timeline-bound",
              ["fp early reset down", "dump early reset down", "finding-reproduces:F-HF03-1 (",
               "corpus HF-03-a: replay ok", "HA down ", "finding-reproduces:F-HF03-2 (",
               "finding register: every FINDINGS entry was reproduced"]),
    "F-HF03-1": ("which swept early-reset points reproduce it is the first-sample phase of the 30 s polled attempt counter "
                 "(4 of 6 points on the lab grid, 5 of 6 under an ESPHome-like phase patch); it reproduces at both",
                 ["finding-reproduces:F-HF03-1 (", "fp early reset down"]),
    "F-HF03-2": ("which whole-site cut grid points start a new Dump lease depends on whether Home Assistant's "
                 "post-restart read of the Dump status comes before the firmware's boot restore (the watchdog phase "
                 "after the dongle boot); under an ESPHome-like phase patch the section is refused by LabUnsupported "
                 "(the suite stops) at its first point in 12 of 17 patched quick configurations, and where it ran the "
                 "5 s / 5 s point took the no-new-lease branch in 4 of 5, its pin then absent with no FAIL line "
                 "(extended grid: a new lease at 9 of 15 points against 11 of 15 on the lab grid); F-HF03-2 still "
                 "reproduced at the 60 s and 120 s / 5 s points wherever the section ran",
                 ["finding-reproduces:F-HF03-2 (", "HA down "]),
    "HF-04": ("the lease tails F-HF04-1 and F-HF04-2 pin are the Dump / Free Power watchdog slot after the window end on "
              "the lab grid; at other phases the back-to-back runs meet an interleaving inside a projected firmware "
              "transaction that the coupled tier refuses (the NC-HF04-1 / NC-HF04-2 outcomes change); corpus HF-04-a "
              "and HF-04-c are timeline-bound",
              ["finding-reproduces:F-HF04-1", "finding-reproduces:F-HF04-2 [", "negative control NC-HF04-1 (HF-04)",
               "negative control NC-HF04-2 (HF-04)",
               "every scenario family has at least one killed negative control and none survived",
               "all 9 corpus documents exist, replay ok"]),
    "F-HF04-1": ("the Free Power start at (or 8 s after) the Dump window end fails only while the Dump restore still "
                 "runs, the Dump watchdog's slot after the window end; it fails under an ESPHome-like phase patch in 14 "
                 "of 17 patched quick configurations",
                 ["finding-reproduces:F-HF04-1"]),
    "F-HF04-2": ("the pin fixes the first run's own override tail (19.4 s Free Power, 15.93 s Dump), the watchdog slot "
                 "after the window end on the lab grid; it fails under an ESPHome-like phase patch in all 17 patched quick "
                 "configurations",
                 ["finding-reproduces:F-HF04-2 ["]),
    "HF-05": ("only corpus HF-05-b's expectations are timeline-bound: under an ESPHome-like phase patch one fails",
              ["corpus HF-05-b: replay ok"]),
    "F-HF05-2": ("corpus FINDING document HF-05-b timeline-bound under an ESPHome-like phase (it failed an expectation in "
                 "11 of the V0.1 review's 11 patched quick configurations: the duration number ends at 25.0 instead of "
                 "the recorded 40.0 and INV-HF-NO-FALSE-SUCCESS does not fire, so the recorded deviation does not occur "
                 "on that fixed timeline); the suite pins hold",
                 ["corpus HF-05-b: replay ok"]),
    "HF-06": ("at other phases the failed-start runs meet an interleaving inside a projected firmware transaction that "
              "the coupled tier refuses, and the NC-HF06-1 outcome changes (refused, or the blocker mutant survives); "
              "corpus HF-06-a is timeline-bound",
              ["negative control NC-HF06-1 (HF-06)",
               "every scenario family has at least one killed negative control and none survived",
               "all 9 corpus documents exist, replay ok"]),
    "HF-07": ("only corpus HF-07-c's and HF-07-e's expectations are timeline-bound: since V0.1 their writes expectations "
              "list the used-key prelude's writes with their event sequence numbers, which an ESPHome-like phase patch "
              "changes (both failed in all 17 patched quick configurations; the directed checks held)",
              ["corpus HF-07-c: id / tier / classification", "corpus HF-07-e: id / tier / classification"]),
    "HF-08": ("F-HF08-3's RT-03 compound reproduction pins the inverter clock's in-slot time to one RTC read phase",
              ["finding-reproduces:F-HF08-3 (RT-03 compound"]),
    "F-HF08-3": ("its RT-03 compound reproduction pins the inverter clock's in-slot time to one RTC read phase (it fails "
                 "under an ESPHome-like phase patch in 6 of 17 patched quick configurations); the HF-08 gate and package "
                 "reproductions are not phase-tagged",
                 ["finding-reproduces:F-HF08-3 (RT-03 compound"]),
    "F-RT03-1": ("the RT-03 compound pin it is merged into (F-HF08-3's RT-03 reproduction) depends on one RTC read phase",
                 ["finding-reproduces:F-HF08-3 (RT-03 compound"]),
    "RT-01": ("the RTC rig's 60 s read interval phase sets when the post-change reads come (the correction instants and "
              "lock windows are one read phase) and the restore delay after a lease end is the Free Power watchdog's "
              "slot on the rig; the NC-RT01-1 / NC-RT01-2 kills need a watchdog tick inside a lock window; the RT-01-a / "
              "RT-01-b corpus expectations are timeline-bound",
              ["RT-01 fall baseline: one verified large correction",
               "RT-01 fall lost callback 75 s before the change: the pre-change",
               "RT-01 fall the DST correction's own callback lost", "RT-01 fall 10-min lease", "RT-01 fall 11-min lease",
               "RT-01 spring baseline: one verified large correction",
               "RT-01 spring lost callback 75 s before the change: the pre-change",
               "RT-01 spring the DST correction's own callback lost", "RT-01 spring 10-min lease",
               "RT-01 spring 11-min lease", "negative control NC-RT01-1 (RT-01)", "NC-RT01-1 characterised",
               "negative control NC-RT01-2 (RT-01)", "RT-01-a: replay ok", "RT-01-b: replay ok"]),
    "RT-03": ("the replayed lock windows are one RTC read phase, the Dump watchdog slot after the lock release (pinned "
              "+25 s) is the firmware tier's watchdog phase, and the compound DST case's in-slot time is one read phase; "
              "corpus RT-03-a's expectations are timeline-bound",
              ["RT-03 windows: the fall rig gives the DST lock", "RT-03 a: a Dump lease ending at -8 s inside the lock",
               "finding-reproduces:F-HF08-3 (RT-03 compound", "RT-03-a: replay ok"]),
    "PB-01": ("its corpus finding pins require each replay to be ok, which includes the trace digest; the random "
              "sequences are timed on the lab scheduler, so which violations a seed reaches depends on the phase (the "
              "extended-mode classification check failed under an ESPHome-like phase patch)",
              ["finding-reproduces:F-PB01-1 (PB-01-a", "finding-reproduces:F-PB01-2 (PB-01-b",
               "finding-reproduces:F-PB01-3 (PB-01-c", "finding-reproduces:F-PB01-3:single-key (PB-01-f",
               "finding-reproduces:F-PB01-4 (PB-01-d",
               "every PB-01 finding (and finding variant) of the catalogue reproduced in this run",
               "NC-PB-corpus: the PB-01-a document with one altered expectation",
               "NC-PB-corpus-summary: the PB-01-c document", "PB-01: every invariant violation in "]),
    "F-PB01-1": ("its corpus reproduction (PB-01-a) requires the replay to be ok, which includes the trace digest",
                 ["finding-reproduces:F-PB01-1 (PB-01-a"]),
    "F-PB01-2": ("its corpus reproduction (PB-01-b) requires the replay to be ok, which includes the trace digest",
                 ["finding-reproduces:F-PB01-2 (PB-01-b"]),
    "F-PB01-3": ("its corpus reproduction (PB-01-c) requires the replay to be ok, which includes the trace digest",
                 ["finding-reproduces:F-PB01-3 (PB-01-c"]),
    "F-PB01-3:single-key": ("its corpus reproduction (PB-01-f) requires the replay to be ok, which includes the trace "
                            "digest", ["finding-reproduces:F-PB01-3:single-key (PB-01-f"]),
    "F-PB01-4": ("its corpus reproduction (PB-01-d) requires the replay to be ok, which includes the trace digest",
                 ["finding-reproduces:F-PB01-4 (PB-01-d"]),
    "PB-02": ("only corpus PB-02-a's expectations are timeline-bound: under an ESPHome-like phase patch one fails",
              ["PB-02-a: replay ok ("]),
    "PB-03": ("the replay of corpus PB-03-b is timeline-bound: at ESPHome-like phases its reboot action falls before the "
              "instant the previous action already reached, and the replay refuses it",
              ["PB-03-b: replay ok ("]),
}

# ------------------------------------------------------------------------------------------------------------------------
# root causes (each counted once; members derived from counted / duplicate_of and the suites' relation texts)
# ------------------------------------------------------------------------------------------------------------------------
# Every note of a root-cause group (the 6th tuple element, a list) starts with one of these tags and a space. Notes are
# uncounted context: they change no count, no priority and no verdict of the lab.
NOTE_TAGS = {
    "[priority]": "why the group has its V0.1 priority (a two-axis summary)",
    "[design-review]": "a design question for the design review; not a defect verdict",
    "[design-decision]": "the group is a design-decision item, not a plain defect",
    "[documentation-test-bound]": "the item is a documentation / test-bound item",
    "[coupling]": "decide together with another group",
    "[audit-reported, uncounted]": "a consequence reported by the V0 independent audit; uncounted; not reproduced by a "
                                   "V0.1 directed scenario unless the note says where it is",
    "[v0.1-observation, uncounted, untriaged]": "found during the V0.1 work by a scratch probe; uncounted; untriaged",
}
ROOT_CAUSES = [
    ("RC-PR41-GHOST", "A Phase-B marker commit false negative leaves a durable RESTORE_REQUIRED ghost with the RAM "
                      "mirror clear: the other domain's START gate and HA's RAM-mirror sensors miss it until the "
                      "next reboot",
     ["F-FW01-1", "F-FW05-1", "F-HF07-4", "F-PB01-1"], "availability / cost precondition (low-medium)", "P2",
     ["[priority] P2 (V0: P1; P3 by likelihood). Mechanism CONFIRMED-IN-SIMULATION; device reachability UNKNOWN, "
      "likely very low (the trigger of RC-PR41-STRANDED-OVERRIDE; the harmful chain also depends on the ESP-IDF "
      "fault cell). The repair is cheap hardening.",
      "[audit-reported, uncounted] Register 244 legs: (a) a reg244 ghost admits a genuine Dump lease and a reboot "
      "inside it gives the S4 dual lockout with 256-261 stuck; (b) a Dump ghost followed by the owner's reg244 Apply "
      "gives the S4 dual lockout on any later reboot (reg244 has no end time); (c) a lone reg244 phantom never "
      "self-heals and blocks Free Power, Dump and manual applies after any reboot; INV-NO-2ND-RESTORER cannot see "
      "the 244 pairs. Partly exercised: FW-03 boots a reg244 ghost together with a Dump ghost into the S4 dual "
      "lockout (F-FW03-1 / -2 / -3); the three legs as stated are not reproduced by a V0.1 directed scenario.",
      "[audit-reported, uncounted] Repair scope: set the RAM mirror fail-closed at all three Phase-B false-return "
      "branches (Free Power FW:9233-9240, Dump FW:18555-18558, register 244 FW:17204-17211) and include the success "
      "branch's RAM pacing reset (FW:9184-9187), else a stale durable operator_needed holds the phantom; correct the "
      "stale comments (FW:1012-1020, 1088-1104); pin the data-to-marker commit adjacency (FW:9154-9159, 17182-17187, "
      "18541-18547) that keeps the ESPHome 'unrelated pending key' route closed. A repair-scope statement: not "
      "reproduced by a V0.1 directed scenario (no scenario runs a repaired firmware).",
      "[v0.1-observation, uncounted, untriaged] PB-01 extended generator seed 366 under the scratch ESPHome-like "
      "phase patch gives an UNCLASSIFIED INV-NO-SILENT-OVERRIDE: a PR41-GHOST false negative on a used Free Power "
      "marker, a foreign inverter write of 126 to 268, then a second Free Power START (admitted, RAM clear) that "
      "snapshots 126 while the lab's ORIGINAL stays 20; either the foreign-register oracle limit (HL-2: a foreign "
      "change on a register held only by a ghost's durable marker is snapshotted by the ghost-admitted START) or a "
      "real ghost consequence (the true ORIGINAL 20 is overwritten in the data record); not seen on the lab's own "
      "phase; not reproduced by a V0.1 directed scenario or corpus document."]),
    ("RC-PR41-STRANDED-OVERRIDE", "Under the PR41 dual lockout a genuine Free Power override still applied has no "
                                  "in-firmware exit or time bound, and FPS1 / DGS1 keep showing ACTIVE with no "
                                  "lockout notification",
     ["F-FW01-2", "F-HF07-1", "F-HF07-2"],
     "cost / availability medium (stranded override); diagnostics medium (HA view); safety low", "P2",
     ["[priority] P2 (V0: P1). Mechanism CONFIRMED-IN-SIMULATION; device reachability UNKNOWN, likely very low: a "
      "Dump marker own-key landed-then-error write (ESP-IDF REMOVE_FAILED on a key used before), ESP-IDF returning "
      "the new RESTORE_REQUIRED copy at the next boot (contested), a Free Power START in the same runtime and a "
      "reboot inside that lease. The consequence is severe, the trigger narrow and unverified.",
      "[design-review] PR41 premise stale since fcp2: PR41 justifies the dual lockout with 'Dump's restore is "
      "unconditional/blind' (FW:1100-1104), but since the fcp2 ownership pre-read the Dump restore fresh-reads "
      "244-261 and never writes ORIGINAL or FOREIGN slots (FW:19796-19808). With PR41's two '= true' lines removed "
      "in memory the bank returned to ORIGINAL in all 8 non-coincident combinations (audit); PR41 stays load-bearing "
      "only when the Free Power watts equal the ghost Dump ceiling or the two ORIGINALs diverge. The exit-less "
      "strand is a design-review item, neither 'by design' nor a defect yet; review it with SG-02 for Allow-Export "
      "sites.",
      "[audit-reported, uncounted] Allow-Export sites (ORIGINAL 244 = 0): SG-02 writes 244 := 2 about 13 s after the "
      "boot and keeps it, so the owner's Allow Export becomes Zero Export indefinitely, and the containment text "
      "replaces the only status text that names the real cause. Partly reproduced: corpus FW-01-c (PASS, documented "
      "containment design) pins 244 = 2 and 'export CONTAINED' on such a site; the duration and the lost cause text "
      "are not asserted.",
      "[audit-reported, uncounted] The Dump mirror strands a 256-261 battery-ceiling residue. Reproduced but "
      "uncounted: corpus FW-01-a pins 256 / 261 = 1500 W and HF-07-a pins 256-261 at the Dump ceiling (7000 W "
      "without the plant, model-dependent) under the lockout.",
      "[audit-reported, uncounted] NVS-erase laundering: erasing NVS while locked clears the lockout but leaves the "
      "override silent, and the next Free Power START adopts it as ORIGINAL; a recovery procedure must restore the "
      "inverter first and only then repair NVS. Not reproduced by a V0.1 directed scenario.",
      "[audit-reported, uncounted] 'Stated nowhere as accepted' is partly overstated: the PR41 test docstring "
      "intends 'once locked neither domain performs any further register write'. A source-reading statement: not "
      "reproduced by a V0.1 directed scenario.",
      "[coupling] Decide the HA alert for 'a function still active past its own lease end' together with "
      "RC-SAME-DOMAIN-SILENT-LOSS."]),
    ("RC-LOCKOUT-CAUSE-TEXT", "A dual-lockout branch (PR41 or S4) retains no lockout cause, so the partner domain's "
                              "status and every refusal text name the wrong cause",
     ["F-FW01-3", "F-FW03-3", "F-HF07-5"], "diagnostics (low)", "P3", []),
    ("RC-N15-STALE-ORIGINAL", "A ghost marker plus a later owner write: the next boot restores a stale ORIGINAL or "
                              "locks out (no final-writer latch, N15)",
     ["F-FW02-2", "F-FW02-1"], "owner intent / cost (low) with a diagnostics part", "P2", []),
    ("RC-N17-CROSS-DOMAIN-RESTORE", "P1 restores carry no cross-domain terms: with the other domain corrupt / "
                                    "UNKNOWN at boot a trusted restore writes the shared 256-261 over its unresolved "
                                    "obligation (N17)",
     ["F-FW05-2", "F-FW03-1", "F-PB01-2"], "diagnostics / safety-rule (low), documented accepted residual", "P3", []),
    ("RC-N16-CONTAINMENT-OVERLAY", "The SG-02 containment gate has no other-domain obligation term and can overlay "
                                   "the Free Power lease's register-244 context (N16)",
     ["F-FW03-2"], "availability / cost (low), restrictive direction", "P3", []),
    ("RC-FALSE-ABSENT", "A held lease marker lost at boot (single key, read as ABSENT = CLEAR) leaves the override "
                        "live with no visible obligation; a later START adopts the residue as ORIGINAL",
     ["F-FW04-1", "F-FW04-2", "F-FW04-3", "F-PB01-3:single-key"],
     "Dump: safety (bounded); Free Power: cost; plus diagnostics", "P1",
     ["[priority] P1 (unchanged). Mechanism CONFIRMED-IN-SIMULATION; device reachability "
      "PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN: the remaining route is ESP-IDF erasure of a corrupt entry "
      "(REPORTED by the S4 notes and the firmware's own 'do NOT reboot' text, FW:913; not verified offline); the "
      "second reboot needs no owner action (ESPHome's 15-min API / Wi-Fi reboot, safe mode, a power cut). Ruled out: "
      "a power cut between the ordered commits, key derivation, a tag rename and a 24-bit item-hash collision "
      "(test_fallback_nvs_keyhash.py).",
      "[audit-reported, uncounted] In the READ_ERROR (UNKNOWN) state the safety census labels the domain 'a Dump to "
      "Grid restore is owed' (FW:20661-20662) and the gated Restart offers the override 'the boot path re-opens it' "
      "(FW:20693-20701), against the firmware's own 'do NOT reboot' (FW:913) and HA's 'Do NOT restart the dongle'. "
      "Not reproduced by a V0.1 directed scenario.",
      "[audit-reported, uncounted] The register 244 domain has the same ABSENT-to-CLEAR mapping (FW:982-985); no "
      "V0.1 scenario covers it. Not reproduced by a V0.1 directed scenario.",
      "[audit-reported, uncounted] Repair design: the boot cross-check 'ABSENT marker and data active_persisted == 1 "
      "-> UNKNOWN lockout' also locks an idle domain whose CLEAR marker is lost after a clean end (the end commit "
      "keeps active_persisted = 1; Force and Accept refuse, no exit); the refined Dump check 'active_persisted == 1 "
      "and restore_requested == 0' removes those idle lockouts without a new commit; Free Power needs a data-record "
      "closure commit; a page-level loss defeats any data-record witness. Evaluated by the audit as in-memory "
      "mutants; not reproduced by a V0.1 directed scenario.",
      "[audit-reported, uncounted] After the false ABSENT, HA can show a schedule-started lease as COMPLETED, and a "
      "saved fallback profile gives only a generic drift WARNING (HA is not completely silent then). Not reproduced "
      "by a V0.1 directed scenario."]),
    ("RC-PARTITION-ERASE", "A whole-partition NVS erase at boot loses every marker and record: the override stays "
                           "live and a Free Power START captures the Dump residue as ORIGINAL",
     ["F-FW04-4", "F-PB01-3"], "safety (secondary, bounded); Free Power lease: cost", "P2", []),
    ("RC-COMMIT-FALSE-POSITIVE", "A Phase-B marker commit that reports success without storing: the lease runs on "
                                 "RAM only and a reboot leaves the override live with a stale CLEAR marker (ABSENT "
                                 "on a never-used domain, a form the lab no longer injects since V0.1)",
     ["F-FW06-3", "F-FW06-2", "F-PB01-4"],
     "Dump: safety (bounded); Free Power: cost; trigger reachability UNKNOWN pending the ESP-IDF host NVS test (not "
     "labelled a model artefact)", "P3",
     ["[priority] P3 (V0: P2) pending the ESP-IDF host NVS test; trigger UNKNOWN, not labelled a model artefact. No "
      "route exists at the ESPHome layer (ESPHome 2026.8.2 sync() returns success only when no pending set_blob "
      "failed); a physical ESP-IDF route via an INVALID page after one reported flash-op failure was described in "
      "the audit (medium confidence, not executed).",
      "[v0.1-observation, uncounted, untriaged] With a used register 244 domain (a completed Apply / Restore first), "
      "an owner change 244 := 1 and then an Apply whose data-record commit is a lab false_positive (nothing stored, "
      "true returned) resolve at the next boot from the previous transaction's stale data record: the later Restore "
      "writes 2 ('RESTORED OK - register 244 confirmed back at 2'), not the true pre-Apply value 1, and no invariant "
      "fires: the lab treats the owner-initiated register 244 Restore's landed write as the owner's new ORIGINAL "
      "(_lab_fw OWNER_DOMAINS includes r244), so the stale value 2 becomes the baseline and the pre-Apply value 1 is "
      "not compared (by the same rule a stale-ORIGINAL restore through the r244 domain is invisible to "
      "INV-NO-SILENT-OVERRIDE). An N15-like stale-ORIGINAL restore through "
      "a data-record false positive (compare RC-N15-STALE-ORIGINAL); trigger reachability UNKNOWN as F-FW06-2 / -3; "
      "Free Power and Dump are not affected (their START re-commits the data record after activation). Found by a "
      "V0.1 scratch probe; no directed scenario or corpus document pins it."]),
    ("RC-FP-START-COMMIT-CASCADE", "A Free Power START commit failure runs the activation-failure branch too: the "
                                   "real cause is overwritten, failures count twice, and FPS1 copies the misleading "
                                   "final text",
     ["F-FW06-1", "F-HF07-3"], "diagnostics (low)", "P3", []),
    ("RC-FP-NO-SG39-RETRY", "The Free Power restore has no link-recovery retry (the Dump SG-39 analogue)",
     ["F-FW07-1"], "low: cost / availability", "P3",
     ["[priority] P3 (V0: P2): a bounded, cost-only parity gap. The Free Power restore comes 3-288 s after the link "
      "returns against 1-13 s for Dump (FW:10131-10136 has no link-recovery clause; the Dump SG-39 clause is "
      "FW:19776-19783)."]),
    ("RC-END-REASON-MISATTRIBUTION", "The Dump boot path attributes an already-ended lease's end to the restart",
     ["F-FW07-2"], "diagnostics (low)", "P3", []),
    ("RC-FCP2-R1", "Export stays enabled when the inverter refuses every 244 write (documented SG-04 residual)",
     ["F-FW07-3"], "safety class, documented accepted residual, low in practice", "P3", []),
    ("RC-CONFIG-READ-FAIL-CLOSED", "One failed configuration block read ends an ACTIVE Dump lease as TELEMETRY LOST "
                                   "(explicit fail-closed term with no stated rationale)",
     ["F-FW07-4"], "low: availability (fail closed) and diagnostics", "P3", []),
    ("RC-FCP2-F6-RESTART-LOOP", "A lock leak recurring before every boot's first watchdog tick gives an unbounded "
                                "stuck-lock restart loop (documented FCP2-F6 residual, refined)",
     ["F-FW08-1"], "safety-adjacent, low overall risk (hypothetical trigger)", "P3", []),
    ("RC-WINDOW-END-OVERRUN", "The firmware end tail (end epoch fixed at commit, 15 s watchdog quantum, busy-bus "
                              "deferral, multi-op restore) is not budgeted by the packages' window-end texts (FPS1 / "
                              "DGS1: nothing starts or runs after the window end); the +30 s bound exists only as "
                              "the HA suites' model-only check",
     ["F-HF01-1"], "diagnostics / documentation (low)", "P3",
     ["[documentation-test-bound] P3. '+30 s' is the HA test suites' model-only bound "
      "(home-assistant/tests/test_ecco_free_power_schedule_reliability.py:199, "
      "test_ecco_dump_to_grid_schedule_reliability.py:277, run against hand models whose session ends at start + "
      "duration), not a package claim; the package texts are 'nothing starts or runs after it' (FPS1:77, DGS1:90) "
      "and 'a late start ends within about a minute of the window end' (FPS1:26, DGS1:29). The 36 / 52 s overruns "
      "are phase-dependent examples on one recorded-busy-window bus model (idle-bus maxima about 15.9 s Dump / 19.4 "
      "s Free Power). Mechanism CONFIRMED-IN-SIMULATION as an existence claim."]),
    ("RC-STARTUP-RECOVERY-ROLLBACK", "FPS1 / DGS1 startup recovery decides only from package helpers a crash rolls "
                                     "back and starts a new session after an End, a firmware end or a site power cut",
     ["F-HF02-1", "F-HF03-2"], "low: owner intent / cost plus diagnostics", "P2",
     ["[design-decision] P2 as a design-decision item (P3 on harm alone): whether a startup recovery may re-create a "
      "lease after an unclean Home Assistant stop or a site power cut is a policy question. Reachability rests on "
      "HA's restore-state cadence (a 15-min save), UNVERIFIABLE offline; the finding reproduces at about (900 - D) / "
      "900 of rollback instants; FPS1 variant: the run's own success dismisses the recovery notice, so End & Restore "
      "is overridden silently."]),
    ("RC-SMR1-UNCLEAN-SHUTDOWN", "A crash during STARTING loses the SMR1 obligation and the recovery re-stage yields "
                                 "a false RESTORED (documented limit, understated consequence)",
     ["F-HF02-2"], "diagnostics (low)", "P3", []),
    ("RC-RESTART-ABANDONS-RUN", "A graceful HA restart while STARTING, after the start helper was moved, abandons "
                                "the run silently",
     ["F-HF02-3"], "diagnostics (low)", "P3", []),
    ("RC-PRESS-PROOF-COUNTER-RESET", "The no-answer proof uses RAM-only attempt counters that a dongle reset clears",
     ["F-HF03-1"], "diagnostics (low)", "P3", []),
    ("RC-TAIL-PERSISTENT-REFUSAL", "A cross-domain lease tail is treated as a persistent refusal: the next schedule "
                                   "fails at once although the blocker clears inside its retry budget",
     ["F-HF04-1"], "availability / diagnostics (low)", "P3", []),
    ("RC-SAME-DOMAIN-SILENT-LOSS", "A same-function schedule at or inside the previous lease's end records BLOCKED "
                                   "with no failure alert and loses the window",
     ["F-HF04-2"], "availability / diagnostics (low-medium)", "P2",
     ["[coupling] P2 (low end). It comes from the documented rule 'already active = started' (FPS1:99 'BLOCKED - "
      "Free Power already active' and the alert condition that exempts it, FPS1:449 / :832; DGS1:135, :468, :905), "
      "not an alert oversight. Decide together with RC-PR41-STRANDED-OVERRIDE (F1): alert when a function is still "
      "active past its own lease end."]),
    ("RC-DGS1-WALK-READS-FP-OVERRIDE", "DGS1's arm-time TOU walk reads the Free Power override's own grid-charge "
                                       "slots and refuses every Dump arm during a Free Power lease",
     ["F-HF04-3"], "availability / diagnostics (low)", "P3", []),
    ("RC-SMR1-OWNER-RESTORING", "An owner change within the restore write's latency is overwritten and reported "
                                "RESTORED (documented limit, wrong documented consequence)",
     ["F-HF05-2"], "diagnostics / owner intent (low)", "P3", []),
    ("RC-HA-MODEL-FAILED-START", "The HA dongle models keep a failed START's snapshot pending until End & Restore, "
                                 "unlike the firmware's automatic restore",
     ["F-HF06-1"], "diagnostics (test-model fidelity, low)", "P3", []),
    ("RC-DGS1-STALE-ADVICE", "DGS1's failed-start alert keeps 'press End & Restore Now' after the firmware restored",
     ["F-HF06-2"], "diagnostics (low)", "P3", []),
    ("RC-FPS1-FAILED-REASON-LOST", "FPS1 records 'FAILED TO START - RESTORED OK' for an activation write / verify "
                                   "failure: the reason is lost",
     ["F-HF06-3"], "diagnostics (low)", "P3", []),
    ("RC-PACKAGE-DST-ARM-GUARD", "FPS1 / DGS1 arm validation has no DST guard: an ambiguous or nonexistent local "
                                 "start is resolved silently (fold=0) or refused with a misleading text",
     ["F-HF08-1", "F-HF08-2"], "availability / diagnostics (low)", "P3",
     ["[audit-reported, uncounted] Editing an already-armed start into the repeated hour is not re-validated and can "
      "start Free Power at once (reproduced by the audit in the coupled simulation; not reproduced by a V0.1 "
      "directed scenario); the repair scope extends to edits while armed. Mechanism PLAUSIBLE-UNDER-ASSUMPTIONS (HA "
      "fold=0 resolution not verifiable offline)."]),
    ("RC-SG25-DST-TOU-GATE", "The Dump START TOU gate (and its DGS1 mirror) walks local minutes: on DST change "
                             "nights it admits a lease across a charge slot (SG-25, deferred)",
     ["F-HF08-3", "F-RT03-1"], "safety (known, DEFERRED), qualified: practical impact low", "P2",
     ["[audit-reported, uncounted] The SG-25 operational restriction (no Dump 00:00-03:00 local on a change night) "
      "is procedural only: no package or firmware guard exists (a cheap DGS1 arm-time refusal is possible later). "
      "F-HF08-3 and the RT-03 compound case reproduce the gate admitting the lease; the missing guard is a source "
      "fact, not reproduced by a V0.1 directed scenario."]),
    ("RC-FROZEN-CT-RANGE-NOT-RESEEDED", "The battery range of the fast frozen-CT criterion is not re-seeded at START "
                                        "or outside a lease, so a CT already repeating at START meets the fast "
                                        "criterion on battery values from outside the repeat window",
     ["F-FW07-5"], "low: fail closed (an earlier lease end) and diagnostics (a misleading end text)", "P3", []),
    ("RC-WRITE-ENABLE-LEFT-ON", "After an unanswered START press FPS1 / DGS1 turn the write enable off with single "
                                "unchecked calls; when both fail the firmware keeps it ON (it disarms only at a "
                                "press or a reboot), SMR1's restore stays blocked and the alert does not name the "
                                "switch",
     ["F-HF09-1"],
     "low: a write enable left on permits a START without the arm step; SMR1 restore blocked; diagnostics", "P3", []),
]

# ------------------------------------------------------------------------------------------------------------------------
# negative controls (id, suite, mutation, target, outcome) - from the suites' own NC tables / output at this baseline;
# SAME_MUTATION below marks the rows that repeat another row's mutation (control rows vs distinct mutations)
# ------------------------------------------------------------------------------------------------------------------------
NEGATIVE_CONTROLS = [
    ("NC-FW01-1", "test_lab_fw_obligations", "PR41 condition replaced by false (no Free Power / Dump dual-obligation "
     "lockout)", "INV-NO-2ND-RESTORER", "killed"),
    ("NC-FW01-2", "test_lab_fw_obligations", "Free Power corrupt gates removed from the watchdog and the restore "
     "precondition", "INV-LOCKOUT-QUIET", "killed"),
    ("NC-FW01-3", "test_lab_fw_obligations", "SG-02 containment literal 2 (Zero Export) changed to 1", "INV-LOCKOUT-QUIET",
     "killed"),
    ("NC-FW01-4", "test_lab_fw_obligations", "status-only repair-shaped mutant (lambda-local dual flag set in PR41, dual "
     "sub-branch in the Free Power status block)", "finding-reproduces:F-FW01-3", "killed"),
    ("NC-FW02-1", "test_lab_fw_obligations", "Dump restore pre-read treats every changed slot as ECCO-owned",
     "INV-NO-SILENT-OVERRIDE", "killed"),
    ("NC-FW03-1", "test_lab_fw_obligations", "Free Power restore register-244 lease-context comparison replaced by true "
     "(both pre-write gates)", "INV-NO-2ND-RESTORER", "killed"),
    ("NC-FW03-2", "test_lab_fw_obligations", "PR41 guard without '!dump_recovery_metadata_corrupt' (PR41 also fires after "
     "S4)", "finding-reproduces:F-FW03-1", "killed"),
    ("NC-FW04-1", "test_lab_fw_durability", "S3 removed: the boot no longer converts an ACTIVE Free Power lease into a "
     "restore request", "INV-NO-RESUME", "killed"),
    ("NC-FW04-2", "test_lab_fw_durability", "the Dump boot no longer sets dump_restore_requested for an ACTIVE lease",
     "INV-NO-RESUME", "killed"),
    ("NC-FW04-3", "test_lab_fw_durability", "the Dump on_boot reads a stored marker as CLEAR (a stored RESTORE_REQUIRED "
     "ignored during an ACTIVE lease)", "INV-BOOT-MIRROR", "killed"),
    ("NC-FW05-1", "test_lab_fw_durability", "PR41 never fires (cut after the phantom-admitted START's 256-261 write)",
     "INV-NO-2ND-RESTORER", "killed"),
    ("NC-FW06-1", "test_lab_fw_durability", "Phase-B guard: START proceeds on the data commit alone (marker true negative "
     "+ reboot during the lease)", "INV-NO-SILENT-OVERRIDE", "killed"),
    ("NC-FW07-1", "test_lab_fw_runtime", "SG-39 link-recovery clause removed (FW-07-A; the kill depends on the scheduler "
     "phase: phase_sensitive)", "INV-RESTORE-BOUND", "killed"),
    ("NC-FW07-2", "test_lab_fw_runtime", "TELEMETRY LOST monitor neutered (FW-07-A)", "INV-17", "killed"),
    ("NC-FW07-3", "test_lab_fw_runtime", "no-fresh-SOC clause removed (FW-07-C)", "INV-16", "killed"),
    ("NC-FW07-4", "test_lab_fw_runtime", "owed Stop SOC record binding removed (FW-07-D)", "INV-16", "killed"),
    ("NC-FW07-5", "test_lab_fw_runtime", "Dump boot no-resume removed (FW-07-E)", "INV-NO-RESUME", "killed"),
    ("NC-FW07-6", "test_lab_fw_runtime", "Free Power S3 removed (FW-07-E)", "INV-NO-RESUME", "killed"),
    ("NC-FW07-7", "test_lab_fw_runtime", "the owner's lower configured Stop SOC replaces the owed one (FW-07-D)", "INV-16",
     "killed"),
    ("NC-FW07-8", "test_lab_fw_runtime", "the fast frozen-CT criterion removed: only the 30-read slow window is left "
     "(FW-07-I)", "INV-17", "killed"),
    ("NC-FW07-9", "test_lab_fw_runtime", "the frozen-SOC energy term removed from the watchdog's frozen condition "
     "(FW-07-I)", "INV-17", "killed"),
    ("NC-FW07-10", "test_lab_fw_runtime", "the battery-power repeat term removed from the watchdog's frozen condition "
     "(FW-07-I)", "INV-17", "killed"),
    ("NC-FW08-1", "test_lab_fw_runtime", "stuck-lock escalation restart removed (FW-08-B)", "INV-20", "killed"),
    ("NC-FW08-2", "test_lab_fw_runtime", "lock age ignores the shared write mutex (FW-08-B)", "INV-20", "killed"),
    ("NC-FW08-3", "test_lab_fw_runtime", "watchdog trigger and restore gate ignore the RTC lock (FW-08-E)", "INV-RTC-EXCL",
     "killed"),
    # test_lab_fw_guards: 28 distinct mutations in 33 control checks (an identical mutation applied to several scenarios
    # counts once); each target names the suite checks the control asserts (killed: they fail under the mutant;
    # survived(expected): they still hold)
    ("NC-FW09-1", "test_lab_fw_guards", "the Dump restore's register-244 readback compare disabled (M9, FW:19982); 244 "
     "write acknowledged but not applied", "checks: FW-09 a.1, FW-09 a.2, FW-09 a.5", "killed"),
    ("NC-FW09-2", "test_lab_fw_guards", "the Dump restore's 256-261 readback mismatch term disabled (C6, FW:20336); 6-slot "
     "block write acknowledged but not applied", "checks: FW-09 b.1, FW-09 b.2, FW-09 b.5", "killed"),
    ("NC-FW09-3", "test_lab_fw_guards", "C6 on the single-slot partial-mask restore (a FOREIGN 261, every retry a 260-only "
     "write)", "checks: FW-09 b2.3, FW-09 b2.4", "killed"),
    ("NC-FW09-4", "test_lab_fw_guards", "the Dump restore's 244 verify read on_error no longer fails the attempt (MC244, "
     "FW:19993; the error-branch mutant of scenario c, which M9 cannot reach)", "checks: FW-09 c.1, FW-09 c.2", "killed"),
    ("NC-FW09-5", "test_lab_fw_guards", "the Dump restore's 256-261 verify read on_no_response no longer fails the attempt "
     "(MC256, FW:20352; the error-branch mutant of scenario c2, which C6 cannot reach)", "checks: FW-09 c2.1, FW-09 c2.2",
     "killed"),
    # W6-1 (the independent recheck of V0.1): the per-slot 256-261 readback verify; each slot mutant on the b3 scenario of
    # the slot it skips (C6k4 also on b2). No two of these rows apply the identical text change (C6k0 / C6s0 and C6k5 /
    # C6s5 skip the same slot by different edits of different lines), so none is in SAME_MUTATION
    ("NC-FW09-6", "test_lab_fw_guards", "the Dump restore's 256-261 readback never verifies slot 256 (C6k0, FW:20336 gains "
     "'i != 0 &&'); a FOREIGN 261, every single-register write of 256 after the End (policy write:256x1) acknowledged "
     "but not applied", "checks: FW-09 b3-256.2, FW-09 b3-256.3, FW-09 b3-256.4", "killed"),
    ("NC-FW09-7", "test_lab_fw_guards", "the Dump restore's 256-261 readback never verifies slot 257 (C6k1, FW:20336 gains "
     "'i != 1 &&'); a FOREIGN 261, every single-register write of 257 after the End (policy write:257x1) acknowledged "
     "but not applied", "checks: FW-09 b3-257.2, FW-09 b3-257.3, FW-09 b3-257.4", "killed"),
    ("NC-FW09-8", "test_lab_fw_guards", "the Dump restore's 256-261 readback never verifies slot 258 (C6k2, FW:20336 gains "
     "'i != 2 &&'); a FOREIGN 261, every single-register write of 258 after the End (policy write:258x1) acknowledged "
     "but not applied", "checks: FW-09 b3-258.2, FW-09 b3-258.3, FW-09 b3-258.4", "killed"),
    ("NC-FW09-9", "test_lab_fw_guards", "the Dump restore's 256-261 readback never verifies slot 259 (C6k3, FW:20336 gains "
     "'i != 3 &&'); a FOREIGN 261, every single-register write of 259 after the End (policy write:259x1) acknowledged "
     "but not applied", "checks: FW-09 b3-259.2, FW-09 b3-259.3, FW-09 b3-259.4", "killed"),
    ("NC-FW09-10", "test_lab_fw_guards", "the Dump restore's 256-261 readback never verifies slot 260 (C6k4, FW:20336 gains "
     "'i != 4 &&'); the b2 single-slot retries and a FOREIGN 261 with every single-register write of 260 after the End "
     "(policy write:260x1) acknowledged but not applied",
     "checks: FW-09 b2.2, FW-09 b2.3, FW-09 b2.4, FW-09 b3-260.2, FW-09 b3-260.3, FW-09 b3-260.4", "killed"),
    ("NC-FW09-11", "test_lab_fw_guards", "the Dump restore's 256-261 readback never verifies slot 261 (C6k5, FW:20336 gains "
     "'i != 5 &&'); a FOREIGN 256, every single-register write of 261 after the End (policy write:261x1) acknowledged "
     "but not applied", "checks: FW-09 b3-261.2, FW-09 b3-261.3, FW-09 b3-261.4", "killed"),
    ("NC-FW09-12", "test_lab_fw_guards", "the Dump restore's 256-261 readback loop starts at slot 257, so 256 is never "
     "verified (C6s0, FW:20335 'i = 1', anchored with FW:20336); a FOREIGN 261, every single-register write of 256 after "
     "the End (policy write:256x1) acknowledged but not applied", "checks: FW-09 b3-256.2, FW-09 b3-256.3, FW-09 "
     "b3-256.4", "killed"),
    ("NC-FW09-13", "test_lab_fw_guards", "the Dump restore's 256-261 readback loop stops before slot 261, so 261 is never "
     "verified (C6s5, FW:20335 'i < 5', anchored with FW:20336); a FOREIGN 256, every single-register write of 261 after "
     "the End (policy write:261x1) acknowledged but not applied", "checks: FW-09 b3-261.2, FW-09 b3-261.3, FW-09 "
     "b3-261.4", "killed"),
    # W6-1b: the six per-slot verify regressions that survived the W6-1 review, each on every scenario that makes it
    # observable (the containment path b4-ct / b4-cb / b4-co, a readback above the expected value b5-lo, slot cross-wiring
    # on pairwise-distinct originals b6-ok / b6-x257 / b6-x260). Six distinct text changes, none identical to another
    # row's, so none is in SAME_MUTATION
    ("NC-FW09-14", "test_lab_fw_guards", "a 256-261 readback mismatch no longer sets dump_restore_block_failed (C6bf, "
     "FW:20337 commented out), so an unapplied containment write still counts as contained (FW:20372); 244 acknowledged "
     "but not applied (containment) with slot 258's floor write (FOREIGN 261), the 6-slot floor block (nothing FOREIGN) "
     "or the floor write of 256 back at its ORIGINAL (FOREIGN 261) acknowledged but not applied",
     "checks: FW-09 b4-ct.3, FW-09 b4-ct.4, FW-09 b4-cb.3, FW-09 b4-cb.4, FW-09 b4-co.3, FW-09 b4-co.4", "killed"),
    ("NC-FW09-15", "test_lab_fw_guards", "the Dump restore's 256-261 readback checks the slots ECCO owned at the pre-read "
     "instead of the slots written this attempt (C6om, FW:20336 dump_restore_owned_mask instead of dump_restore_wmask); "
     "containment writes 256, which reads its ORIGINAL (not owned), and that write is acknowledged but not applied",
     "checks: FW-09 b4-co.3, FW-09 b4-co.4", "killed"),
    ("NC-FW09-16", "test_lab_fw_guards", "the Dump restore's 256-261 readback flags only a value below the expected one "
     "(C6lt, FW:20336 '<' instead of '!='); the three containment scenarios (the unapplied slots read 1000 W or 8000 W "
     "against the 500 W floor) and slot 259 at the 1000 W lease value against its 600 W original",
     "checks: FW-09 b4-ct.3, FW-09 b4-ct.4, FW-09 b4-cb.3, FW-09 b4-cb.4, FW-09 b4-co.3, FW-09 b4-co.4, FW-09 b5-lo.2, "
     "FW-09 b5-lo.3, FW-09 b5-lo.4", "killed"),
    ("NC-FW09-17", "test_lab_fw_guards", "the Dump restore's 256-261 readback compares slot 257 with slot 256's expected "
     "value (C6r1, FW:20336 'v[i == 1 ? i - 1 : i]'); a fault-free restore of pairwise-distinct originals, and 257 "
     "acknowledged but not applied (FOREIGN 261) with 256's original equal to the 1000 W lease value",
     "checks: FW-09 b6-ok.1, FW-09 b6-ok.2, FW-09 b6-x257.2, FW-09 b6-x257.3, FW-09 b6-x257.4", "killed"),
    ("NC-FW09-18", "test_lab_fw_guards", "the Dump restore's 256-261 readback compares slot 260 with slot 259's expected "
     "value (C6r4, FW:20336 'v[i == 4 ? i - 1 : i]'); a fault-free restore of pairwise-distinct originals, and 260 "
     "acknowledged but not applied (FOREIGN 261) with 259's original equal to the 1000 W lease value",
     "checks: FW-09 b6-ok.1, FW-09 b6-ok.2, FW-09 b6-x260.2, FW-09 b6-x260.3, FW-09 b6-x260.4", "killed"),
    ("NC-FW09-19", "test_lab_fw_guards", "the Dump restore's 256-261 readback expected values swap slots 259 and 260 "
     "(C6v34, FW:20333 v[] initialiser 'id(dump_restore_v4), id(dump_restore_v3)'); a fault-free restore of "
     "pairwise-distinct originals, and 260 acknowledged but not applied (FOREIGN 261) with 259's original equal to the "
     "1000 W lease value",
     "checks: FW-09 b6-ok.1, FW-09 b6-ok.2, FW-09 b6-x260.2, FW-09 b6-x260.3, FW-09 b6-x260.4", "killed"),
    # W6-1c: the four containment-claim regressions that survived the W6-1b review, each on every scenario that makes it
    # observable (a failed readback in containment b7-rbnr / b7-rber / b7-cmnr, a verified containment attempt followed
    # by a failed one b7-ab, every slot FOREIGN b7-af). Four distinct text changes (C6rh edits FW:20347 / 20352 / 20357 /
    # 20365, C6rn FW:20352 alone: different texts), none identical to another row's, so none is in SAME_MUTATION
    ("NC-FW09-20", "test_lab_fw_guards", "the Dump restore's 256-261 readback failure handlers no longer set "
     "dump_restore_block_failed (C6rh, FW:20347, FW:20352, FW:20357, FW:20365), so a containment whose readback failed "
     "still counts as contained (FW:20372); 244 acknowledged but not applied (containment) with the 6-slot floor block "
     "unapplied and the readback unanswered, with slot 258's floor write unapplied (FOREIGN 261) and the readback "
     "erroring, and 244 unproven by a verify-read error with the floor block unapplied and the readback unanswered",
     "checks: FW-09 b7-rbnr.3, FW-09 b7-rbnr.4, FW-09 b7-rbnr.6, FW-09 b7-rber.3, FW-09 b7-rber.4, FW-09 b7-rber.6, "
     "FW-09 b7-cmnr.2, FW-09 b7-cmnr.3, FW-09 b7-cmnr.6", "killed"),
    ("NC-FW09-21", "test_lab_fw_guards", "the Dump restore's 256-261 readback no-response handler no longer sets "
     "dump_restore_block_failed (C6rn, FW:20352), so a containment whose readback got no response still counts as "
     "contained (FW:20372); the two containment scenarios whose readback gets no response (the mismatch path and the "
     "comms path)",
     "checks: FW-09 b7-rbnr.3, FW-09 b7-rbnr.4, FW-09 b7-rbnr.6, FW-09 b7-cmnr.2, FW-09 b7-cmnr.3, FW-09 b7-cmnr.6",
     "killed"),
    ("NC-FW09-22", "test_lab_fw_guards", "the Dump restore no longer resets dump_restore_contained when an attempt starts "
     "(C6rs, FW:19819); a verified containment attempt followed by a failed one (258 back at its ORIGINAL, the second "
     "floor block acknowledged but not applied)", "checks: FW-09 b7-ab.3, FW-09 b7-ab.4, FW-09 b7-ab.6", "killed"),
    ("NC-FW09-23", "test_lab_fw_guards", "the Dump restore flags the containment even when its plan writes nothing (C6m0, "
     "FW:20043 '&& m != 0' dropped); containment (244 acknowledged but not applied) with every 256-261 slot FOREIGN",
     "checks: FW-09 b7-af.3, FW-09 b7-af.4, FW-09 b7-af.6", "killed"),
    ("NC-FW10-1", "test_lab_fw_guards", "both Free Power terms removed from the Dump START gate (M7, FW:18060-18061); Free "
     "Power RESTORE_REQUIRED", "checks: FW-10 A.2, FW-10 A.3", "killed"),
    ("NC-FW10-2", "test_lab_fw_guards", "M7 with Free Power PENDING_CLEAR", "checks: FW-10 B.2", "killed"),
    ("NC-FW10-3", "test_lab_fw_guards", "only '!free_power_snapshot_valid' removed from the Dump START gate (M7b, "
     "FW:18061); Free Power PENDING_CLEAR and the UNKNOWN lockout", "checks: FW-10 B.2, FW-10 C.2, FW-10 C.3", "killed"),
    ("NC-FW10-4", "test_lab_fw_guards", "M7b with Free Power RESTORE_REQUIRED (the '!free_power_active_persisted' term "
     "still refuses)", "checks: FW-10 A", "survived(expected)"),
    ("NC-FW10-5", "test_lab_fw_guards", "only '!free_power_active_persisted' removed from the Dump START gate (M7a, "
     "FW:18060): an equivalent mutant, snapshot_valid is set in every reachable state with active_persisted set (the "
     "static site check)", "checks: FW-10 M7a-equivalence", "survived(expected)"),
    ("NC-FW11-1", "test_lab_fw_guards", "the Free Power marker READ_ERROR lockout removed: an unreadable marker reads as "
     "CLEAR (C3, FW:525)", "checks: FW-11 read_error (CLEAR).1, FW-11 read_error (RESTORE_REQUIRED).1, FW-11 read_error "
     "(RESTORE_REQUIRED).3", "killed"),
    ("NC-FW11-2", "test_lab_fw_guards", "the Free Power malformed-marker lockout removed: a wrong-size or bad-magic record "
     "reads as CLEAR (C7, FW:526-531); wrong size", "checks: FW-11 wrong_size (CLEAR).1, FW-11 wrong_size "
     "(RESTORE_REQUIRED).1, FW-11 wrong_size (RESTORE_REQUIRED).3", "killed"),
    ("NC-FW11-3", "test_lab_fw_guards", "C7 with a bad-magic record", "checks: FW-11 bad_magic (CLEAR).1, FW-11 bad_magic "
     "(RESTORE_REQUIRED).1, FW-11 bad_magic (RESTORE_REQUIRED).3", "killed"),
    ("NC-FW11-4", "test_lab_fw_guards", "only the wrong-size term of the Free Power malformed-marker test removed (C7ws, "
     "FW:526)", "checks: FW-11 wrong_size (CLEAR).1, FW-11 wrong_size (RESTORE_REQUIRED).1", "killed"),
    ("NC-FW11-5", "test_lab_fw_guards", "C7ws with a bad-magic record (the magic term of FW:527 stays)",
     "checks: FW-11 bad_magic", "survived(expected)"),
    # audit mutants the lab does not run itself (applied in memory to every firmware parse of every suite, outside the
    # lab): each row names the directed checks that failed under it; those checks hold in the plain run
    ("AUDIT-M1", "test_lab_fw_obligations", "audit mutant M1: the PR41 dual-obligation boot check locks only the Dump "
     "domain (the Free Power corrupt assignment removed, firmware :1146); killed by FW-01 here and also by "
     "test_lab_fw_durability 'FW-05 A-start: every cut whose capture holds BOTH markers RESTORE_REQUIRED ... boots into "
     "the PR41 dual lockout' (and its A-restore, B-start, B-restore and C-restore siblings) and test_lab_ha_phantom "
     "'a: the full on_boot fires PR41' / 'b: the full on_boot fires PR41'; it survives PB-01",
     "checks: FW-01: the FULL on_boot's PR41 check locks BOTH domains at every boot", "killed(audit)"),
    ("AUDIT-M2", "test_lab_fw_obligations", "audit mutant M2: the PR41 dual-obligation boot check locks only the Free "
     "Power domain (the Dump corrupt assignment removed, firmware :1147); killed by FW-01 here and also by "
     "test_lab_fw_durability 'FW-05 A-start: every cut whose capture holds BOTH markers RESTORE_REQUIRED ... boots into "
     "the PR41 dual lockout' (and its siblings) and test_lab_ha_phantom 'a: the full on_boot fires PR41' / 'b: the full "
     "on_boot fires PR41'; it survives PB-01", "checks: FW-01: the FULL on_boot's PR41 check locks BOTH domains at every "
     "boot", "killed(audit)"),
    ("NC-HF01-1", "test_lab_ha_schedules", "firmware Free Power watchdog end condition shifted +60 s", "INV-HF-WINDOW",
     "killed"),
    ("NC-HF01-2", "test_lab_ha_schedules", "firmware Dump watchdog end condition shifted +60 s", "INV-HF-WINDOW", "killed"),
    ("NC-HF01-3", "test_lab_ha_schedules", "SMR1's Free Power track saves the schedule's value instead of the owner's",
     "INV-HF-NO-FALSE-SUCCESS", "killed"),
    ("NC-HF04-1", "test_lab_ha_schedules", "the Free Power START gate without its Dump ownership conjuncts (the kill "
     "depends on the scheduler phase: phase_sensitive)", "INV-HF-ONE-LEASE", "killed"),
    ("NC-HF04-2", "test_lab_ha_schedules", "FPS1's 'already active' pre-check never matches (the kill depends on the "
     "scheduler phase: phase_sensitive)", "INV-HF-NO-PRESS-INTO-LEASE", "killed"),
    ("NC-HF06-1", "test_lab_ha_schedules", "SMR1's restore blocker without the Dump snapshot (the kill depends on the "
     "scheduler phase: phase_sensitive)", "INV-HF-SMR1-QUIET", "killed"),
    ("NC-HF06-2", "test_lab_ha_schedules", "the Dump watchdog's 'snapshot valid but not active' restore rule removed",
     "INV-RESTORE-BOUND", "killed"),
    ("NC-HF02-1", "test_lab_ha_lifecycle", "FPS1 fire automation: the on-time start never disarms the schedule after its "
     "run", "INV-HF-OWNER-INTENT", "killed"),
    ("NC-HF02-1b", "test_lab_ha_lifecycle", "only the startup recovery's 'not armed any more' guard disabled (the start "
     "script's own cancel check still ends the run)", "INV-HF-OWNER-INTENT", "survived(expected)"),
    ("NC-HF02-2", "test_lab_ha_lifecycle", "FPS1 startup recovery: the write-enable turn-off after a restart never runs",
     "INV-HF-ARM-OFF", "killed"),
    ("NC-HF03-1", "test_lab_ha_lifecycle", "FPS1 no-answer proof: the attempt-counter equality dropped",
     "INV-HF-PRESS-PROOF", "killed"),
    ("NC-HF03-2", "test_lab_ha_lifecycle", "firmware on_boot: Free Power S3 boot restore request removed", "INV-NO-RESUME",
     "killed"),
    ("NC-HF03-3", "test_lab_ha_lifecycle", "firmware on_boot: Dump to Grid boot restore request removed", "INV-NO-RESUME",
     "killed"),
    ("NC-HF05-1", "test_lab_ha_lifecycle", "SMR1 restore blocker: the three Free Power ownership entities removed",
     "INV-HF-SMR1-QUIET", "killed"),
    ("NC-HF05-2", "test_lab_ha_lifecycle", "SMR1 Free Power track: an owner change while owed is never dropped",
     "INV-HF-NO-FALSE-SUCCESS", "killed"),
    ("NC-HF09-1", "test_lab_ha_lifecycle", "FPS1: continue_on_error removed from the scheduled START press (the press "
     "raises once)", "INV-HF-ARM-OFF", "killed"),
    ("NC-HF09-2", "test_lab_ha_lifecycle", "firmware START gate: the pass branch no longer disarms the Free Power write "
     "enable (the run's closing turn_off raises)", "INV-HF-ARM-OFF", "killed"),
    ("NC-HF09-2b", "test_lab_ha_lifecycle", "only the firmware's own write-enable disarm removed, no service error, "
     "scheduled path only (the package's closing turn_off still ends the switch off); on the owner-armed path it is "
     "killed elsewhere: test_lab_selftest_firmware '...the same START with the arm turned on is admitted and the "
     "firmware turns the arm off again', test_lab_ha_lifecycle HF-09.4 'Free Power: firmware truth - the real gate "
     "disarmed the write enable itself at the press ...' and the corpus trace digests (HF-02-a..c, HF-03-a, HF-03-b, "
     "HF-05-a, HF-05-b, HF-07-a..f, HF-08-b)", "INV-HF-ARM-OFF", "survived(expected)"),
    ("NC-HF09-3", "test_lab_ha_lifecycle", "SMR1 Free Power restore: the per-field read-back check of the result dropped "
     "(the power restore write raises)", "INV-HF-NO-FALSE-SUCCESS", "killed"),
    ("NC1a", "test_lab_ha_phantom", "firmware PR41 Free Power / Dump check disabled (mirror a)", "INV-NO-2ND-RESTORER",
     "killed"),
    ("NC1b", "test_lab_ha_phantom", "firmware PR41 Free Power / Dump check disabled (mirror b)", "INV-NO-2ND-RESTORER",
     "killed"),
    ("NC2b", "test_lab_ha_phantom", "both Free Power lockout write guards removed (watchdog corrupt gate + restore-script "
     "precondition)", "INV-LOCKOUT-QUIET", "killed"),
    ("NC2b-wd", "test_lab_ha_phantom", "only the Free Power watchdog corrupt gate removed (the remaining guard holds)",
     "INV-LOCKOUT-QUIET", "survived(expected)"),
    ("NC2b-rs", "test_lab_ha_phantom", "only the Free Power restore-script corrupt precondition removed, watchdog path "
     "(no owner press: the watchdog's own corrupt gate, firmware :24119, still holds; the End path is NC2b-rs-end)",
     "INV-LOCKOUT-QUIET", "survived(expected)"),
    ("NC2b-rs-end", "test_lab_ha_phantom", "only the Free Power restore-script corrupt precondition removed, with the "
     "owner's End / Force presses after the lockout boot (End & Restore runs the restore script unconditionally, "
     "firmware :23298-23299); the same mutation as NC2b-rs (one distinct mutation, two control checks)",
     "INV-LOCKOUT-QUIET", "killed"),
    ("NC3b", "test_lab_ha_phantom", "SMR1 blocker loses its lease-active and snapshot-pending terms", "INV-HF-SMR1-QUIET",
     "killed"),
    ("NC4", "test_lab_ha_phantom", "harness: settled_events keeps the reloaded lease across a boot transient (an override "
     "held past its window must be flagged)", "INV-HF-WINDOW", "killed"),
    ("NC6a", "test_lab_ha_phantom", "the Dump on_boot reads its stored marker as CLEAR", "INV-BOOT-MIRROR", "killed"),
    ("NC-HF08-1", "test_lab_dst_rtc", "DGS1 walk charge test != 'None' changed to == 'Never'", "INV-DST-TOU-REFUSE",
     "killed"),
    ("NC-HF08-2", "test_lab_dst_rtc", "firmware gate charge mask 0x0003 changed to 0x0000", "INV-DST-TOU-REFUSE", "killed"),
    ("NC-HF08-3", "test_lab_dst_rtc", "Free Power end epoch + 600 s", "INV-EPOCH-END", "killed"),
    ("NC-RT01-1", "test_lab_dst_rtc", "Free Power watchdog RTC lock skip removed (the kill depends on the scheduler "
     "phase: phase_sensitive)", "INV-RTC-WD-SKIP", "killed"),
    ("NC-RT01-2", "test_lab_dst_rtc", "Free Power watchdog lock skip and the restore's correction_in_progress gate removed "
     "(the kill depends on the scheduler phase: phase_sensitive)", "INV-RTC-NO-RESTORE-IN-LOCK", "killed"),
    ("NC-RT02-1", "test_lab_dst_rtc", "rp.lease_active without dump_restore_requested", "INV-RTC-LEASE-HOLD", "killed"),
    ("NC-RT02-2", "test_lab_dst_rtc", "policy input cooldown_active forced true", "INV-RTC-DRIFT-BOUND", "killed"),
    ("NC-RT02-3", "test_lab_dst_rtc", "stall detector forced false", "INV-RTC-STALL-SURFACED", "killed"),
    ("NC-RT03-1", "test_lab_dst_rtc", "Dump watchdog RTC lock skip removed", "INV-RTC-WD-SKIP", "killed"),
    ("NC-RT03-2", "test_lab_dst_rtc", "Dump watchdog lock skip and the restore's correction_in_progress gate removed",
     "INV-RTC-NO-RESTORE-IN-LOCK", "killed"),
    ("NC-RT03-3", "test_lab_dst_rtc", "Dump START gate without !correction_in_progress", "INV-RTC-START-LOCK", "killed"),
    ("NC-PB01-a", "test_lab_property", "Free Power START admission without its two cross-domain Dump terms",
     "INV-ONE-LEASE", "killed"),
    ("NC-PB01-b", "test_lab_property", "S3 removed: a persisted ACTIVE lease no longer forces restore_requested at boot",
     "INV-NO-RESUME", "killed"),
    ("NC-PB01-c", "test_lab_property", "Dump START commits a CLEAR marker instead of RESTORE_REQUIRED (must stay "
     "unclassified)", "INV-NO-SILENT-OVERRIDE", "killed"),
    ("NC-PB01-d", "test_lab_property", "Dump on_boot ignores a stored RESTORE_REQUIRED marker (reads it as CLEAR)",
     "INV-BOOT-MIRROR", "killed"),
    ("NC-PB02-a", "test_lab_property", "Free Power watchdog ends the lease 300 s after its end epoch", "INV-HF-WINDOW",
     "killed"),
    ("NC-PB02-b", "test_lab_property", "SMR1's blocker ignores Free Power Active / Snapshot Valid", "INV-HF-SMR1-QUIET",
     "killed"),
    ("NC-PB03-a", "test_lab_property", "oracle with BST ending one week after the last Sunday of October", "INV-TZ-ORACLE",
     "killed"),
    ("NC-PB03-b", "test_lab_property", "lab clock with the repeated-hour folds swapped", "INV-TZ-FOLD", "killed"),
    ("NC-PB03-c", "test_lab_property", "one event t_utc moved 5 s back", "INV-UTC-MONOTONIC", "killed"),
    ("NC-PB03-d", "test_lab_property", "a per-instance millis() without the 32-bit mask", "INV-MILLIS-WRAP", "killed"),
    # B1 end-to-end controls of the tiered drift rule: test_lab_replay_corpus runs its real section [5] path
    # (generator_results: gen_catalogue's static build and compare(), whose baseline verdict is _lab_trace.drift_report)
    # over an in-memory overlay of the tree with one comment line appended to one file (nothing is written); six
    # distinct mutations (NC-RC-40..45), one control check each; the targets name the [5] drift-rule checks or, for
    # NC-RC-44, the [2] tier-pin checks
    ("NC-RC-40", "test_lab_replay_corpus", "CHANGELOG.md plus one comment line, a non-behavioural file: section [5] "
     "prints its SOURCE DRIFT (non-behavioural) line and adds no failure, its anchor still exactly once; the same edit "
     "fails in strict mode", "checks: gen_catalogue drift rule (tiered)", "survived(expected)"),
    ("NC-RC-41", "test_lab_replay_corpus", "firmware/ecco_clock_dongle_stage3_4_free_power.yaml plus one comment line, a "
     "behavioural file: section [5] fails with the one named check listing the corpus documents that replay it and "
     "the re-record procedure", "checks: gen_catalogue drift rule (tiered)", "killed"),
    ("NC-RC-42", "test_lab_replay_corpus", "registry/rtc_policy.py plus one comment line, a behavioural file pinned from "
     "V0.1 on: section [5] fails with the one named check listing the corpus documents that replay it and the "
     "re-record procedure", "checks: gen_catalogue drift rule (tiered)", "killed"),
    ("NC-RC-43", "test_lab_replay_corpus", "registry/tests/assurance_lab/run_lab.py plus one comment line, a lab file no "
     "corpus document pins: section [5] fails with exactly the one added check 're-generate the catalogue: lab file "
     "changed' naming the file and the regeneration command", "checks: gen_catalogue drift rule (tiered)", "killed"),
    ("NC-RC-44", "test_lab_replay_corpus", "a copy of corpus FW-06-a with one of its tier's TIER_SOURCES pins "
     "(firmware/include/ecco_durable_snapshot.h) removed from its source_digests: gen_catalogue's build names it ('does "
     "not pin 1 of its tier's TIER_SOURCES') and the section [2] tier-pin short-list names it", "checks: B1 tier pins",
     "killed"),
    ("NC-RC-45", "test_lab_replay_corpus", "SAFETY.md taken out of the B1 tier table for the control (restored "
     "afterwards) plus one comment line, a pinned file in neither tier: section [5] fails with exactly the one added "
     "check 'unclassified pinned source changed' (judged behavioural until classified)",
     "checks: gen_catalogue drift rule (tiered)", "killed"),
]

# Distinct mutations (B3.6 independence rule: an identical mutation repeated in several suites, or in several scenarios
# of one suite, counts once). repeat control id -> the canonical control id whose mutation it applies again; the
# canonical id is the group's first row above, maps to itself implicitly and is never listed; no chains (no value is
# itself a key); a row not listed is a distinct mutation. gen_catalogue writes each row's 'same_mutation_as' from this
# table and prints '<rows> control rows over <n> distinct mutations'. A row is listed only when its mutant firmware /
# package / harness text is byte-identical to the canonical one, or differs only in a form with the same program
# behaviour at the same site: a boolean condition made constant false by a different conjunct, a statement removed
# versus turned into a no-op (an empty block, a self-assignment, or the re-assignment of the value the same variable was
# given a few lines earlier with no write in between), a conjunct removed versus replaced by 'true'. Mutations at the same
# site with a different constant (the Free Power watchdog end shifted +60 s / +300 s, the start end epoch +600 s) or a
# different removed-term set (the SMR1 blocker controls NC-HF05-1, NC-HF06-1, NC3b, NC-PB02-b; NC2b-wd / NC2b-rs against
# NC2b; NC-RT03-1 against NC-RT03-2; NC-RT01-1 against NC-RT01-2) stay distinct. Re-derived per row from the suites'
# mutation code (scratch byte comparison of the mutant texts; not a lab check).
SAME_MUTATION: dict[str, str] = {
    # the PR41 dual-obligation boot condition made constant false (FW:1140-1145): NC-FW01-1 replaces its two marker
    # conjuncts by 'false', NC-FW05-1 its last conjunct, NC1a / NC1b prefix 'false &&' (both mirrors)
    "NC-FW05-1": "NC-FW01-1",
    "NC1a": "NC-FW01-1",
    "NC1b": "NC-FW01-1",
    # both Free Power lockout write guards removed: the watchdog corrupt gate and the restore-script precondition
    # (NC2b: 'if (...) {}' and 'true &&' at the same two sites)
    "NC2b": "NC-FW01-2",
    # Free Power S3: the boot's 'free_power_restore_requested = true' removed (NC-HF03-2 byte-identical; NC-FW07-6 a
    # self-assignment; NC-PB01-b re-assigns 'data.restore_requested != 0', the value the line before S3 already set)
    "NC-FW07-6": "NC-FW04-1",
    "NC-HF03-2": "NC-FW04-1",
    "NC-PB01-b": "NC-FW04-1",
    # Dump boot no-resume: the boot's 'dump_restore_requested = true' removed (NC-HF03-3 byte-identical; NC-FW07-5 a
    # self-assignment)
    "NC-FW07-5": "NC-FW04-2",
    "NC-HF03-3": "NC-FW04-2",
    # the Dump on_boot reads a stored marker as CLEAR (byte-identical mutant firmware)
    "NC6a": "NC-FW04-3",
    "NC-PB01-d": "NC-FW04-3",
    # the Dump watchdog's RTC lock skip and the Dump restore gate's correction_in_progress term removed (byte-identical)
    "NC-RT03-2": "NC-FW08-3",
    # test_lab_fw_guards: 28 distinct mutations in 33 control checks (C6, M7, M7b, C7 and C7ws each run in two scenarios;
    # the W6-1 slot mutants NC-FW09-6..13 are 8 distinct mutations, the W6-1b mutants NC-FW09-14..19 6 more and the W6-1c
    # mutants NC-FW09-20..23 4 more, each row one mutation over all its scenarios, none listed here)
    "NC-FW09-3": "NC-FW09-2",
    "NC-FW10-2": "NC-FW10-1",
    "NC-FW10-4": "NC-FW10-3",
    "NC-FW11-3": "NC-FW11-2",
    "NC-FW11-5": "NC-FW11-4",
    # the Free Power START gate without its two Dump ownership conjuncts (byte-identical)
    "NC-PB01-a": "NC-HF04-1",
    # the firmware START gate's pass branch without the Free Power write-enable disarm (the same cached mutant firmware,
    # once with a raised closing turn_off, once without: killed / survived as expected)
    "NC-HF09-2b": "NC-HF09-2",
    # the Free Power restore-script corrupt precondition removed (watchdog path / owner End path)
    "NC2b-rs-end": "NC2b-rs",
}

UNSUPPORTED = [
    ("FW-07-U1", "test_lab_fw_runtime", "NTP loss after a first sync: only the first SNTP sync per boot is modelled (the "
     "firmware's invalid-clock fallback ends a lease once THIS boot's uptime reaches 300 s, millis() >= "
     "ecco_free_power_invalid_clock_grace_ms - an uptime bound, not a grace counted from the loss)"),
    ("FW-08-E-U1", "test_lab_fw_runtime", "an RTC lock longer than the 90 s deadline breaker: the RTC tick interval is not "
     "executed in the firmware tier"),
    ("FW-08-U2", "test_lab_fw_runtime", "a Fallback Review / Save hold or leak of the shared write mutex: the FB scripts "
     "and the FB housekeeping interval do not transpile"),
    ("HF-03-UNS-1", "test_lab_ha_lifecycle", "dongle power cut inside the projected START transaction after the gate "
     "(data commit, marker commit, write 256, active commit): the coupled tier drops the cut entry's publishes"),
    ("HF-05-UNS-1", "test_lab_ha_lifecycle", "owner START press / write-enable command inside the schedule's projected "
     "START transaction"),
    ("HF-05-UNS-2", "test_lab_ha_lifecycle", "owner number edit inside the firmware's projected Free Power restore "
     "transaction"),
    ("HF-07/system-health", "test_lab_ha_phantom", "home-assistant/packages/ecco_system_health.yaml is not executable in "
     "the coupled world; its health states for the lockout chain are INFERRED only"),
    ("HF-04-UNS-EXT", "test_lab_ha_schedules", "extended mode only: 8 lease-tail gap x watchdog-phase points whose next "
     "schedule command falls inside a projected firmware transaction (not modelled; never counted as PASS)"),
]

# ------------------------------------------------------------------------------------------------------------------------
# harness limitations: known limits of the lab's own oracles, simulators and replay vocabulary (not product findings).
# The core modules _lab_*.py were frozen for V0 (an edit to them changes trace digests and forces re-recording the
# corpus), so HL-1..HL-9 were disclosed and worked around per suite instead of fixed. V0.1 changed the core modules only
# where its corrections required it: it fixed HL-1 at the root and HL-6 by a lab-side refusal (their statuses say so,
# HL-1's keeps its residual) and added HL-10..HL-13 (the scheduler phase, the synchronous script.execute, the scope of
# fail loud and the oracle explanation breadth), each with its effect on the verdicts and measured occurrence counts.
# The HL-6 entry also covers its wrong_size sibling (no separate id). 'anchor' is (path, snippet occurring exactly
# once); 'worked_around_in' rows are '<lab suite>: <how>'.
# ------------------------------------------------------------------------------------------------------------------------
LAB_FW = "registry/tests/assurance_lab/_lab_fw.py"
LAB_HA = "registry/tests/assurance_lab/_lab_ha.py"
HL_STATUS = "open: not fixed in V0.1 (outside its corrections); disclosed here and worked around in the suites named"
HARNESS_LIMITATIONS = [
    {"id": "HL-1", "component": "_lab_fw.accept_adoption (called by FirmwareWorld._adopt_if_clear): the lab's ORIGINAL "
                                "after an operator Accept",
     "anchor": (LAB_FW, "def accept_adoption(dom: str, pre: dict, post: dict, texts) -> dict:"),
     "limitation": "V0 adopted the live register bank as the new ORIGINAL after ANY operator Accept call (dump_accept, "
                   "fp_operator ACCEPT_CURRENT_STATE) whose domain marker read CLEAR or ABSENT with no valid snapshot: "
                   "also after an Accept the firmware refused, and also for the shared 256-261 while the other domain's "
                   "lease held them. The V0.1 rule adopts it only after an Accept whose last published status is a "
                   "firmware SUCCESS text (Free Power firmware :13644 / :13649, Dump :20936 and the residue form "
                   ":20942-20943) that cleared an obligation the domain held before the Accept (stored marker CLEAR or "
                   "ABSENT and the snapshot no longer valid), and never for a register another domain holds (snapshot, "
                   "lockout, transaction, stored marker other than CLEAR / ABSENT, active lease). Residual: a Free Power "
                   "Accept whose durable clear is pending (:13649, PENDING_CLEAR) adopts nothing and the later clear-only "
                   "completion is not an Accept, so the oracle can keep the pre-Accept ORIGINAL",
     "effect_on_verdicts": "V0: a check that compares the bank with ORIGINAL (INV-NO-SILENT-OVERRIDE above all) could be "
                           "wrong after such an Accept in both directions (a residue adopted as the baseline hid an "
                           "override; the other domain's later restore to its own snapshot then differed from the adopted "
                           "values, a false violation, PB-01 extended seed 929). The root fix changed no counted finding, "
                           "no suite verdict and no corpus trace digest; one uncounted fw_durability FW-06 extended-mode "
                           "run moved from resolved to visible (a refused Accept no longer adopts the Dump override). The "
                           "residual can only give a false (loud) INV-NO-SILENT-OVERRIDE, never a masked one: measured 1 "
                           "such Accept in quick mode and 2 in extended mode (fw_durability FW-06 injection flows on "
                           "foreign registers), with no violation",
     "worked_around_in": [
         "test_lab_selftest_firmware: section [16d] pins the rule (the SUCCESS texts, a table of hand-built Accepts over "
         "every guard, positive controls, refused and no-op Accepts adopting nothing, the PB-01 seed 929 continuation "
         "with a Force Restore and no false INV-NO-SILENT-OVERRIDE, each with the V0 rule run in memory as its control)",
         "test_lab_property: PB-01 still issues an Accept only when it cannot move the ORIGINAL (any other drawn Accept "
         "is recorded as run_for 0); with the root fix this gate is redundant (without it the V0.1 rule gave 0 "
         "unclassified violations over 160 quick / 2000 extended sequences, the V0 rule 3 / 77, measured before the "
         "V0.1 NVS used-key rule changed PB-01's fault draws and not re-measured since) and is kept so PB-01's action "
         "statistics stay comparable",
         "test_lab_fw_obligations: FW-01 to FW-03 judge each Accept by its own result text, the bank values and the "
         "durable marker, not by the ORIGINAL-based checkers",
         "test_lab_fw_durability: the FW-06 Accept flows run with the domain's registers held and assert the commit "
         "outcomes directly"],
     "status": "fixed in V0.1 at the root (_lab_fw.accept_adoption); the PENDING_CLEAR residual stays open (a deferred "
               "adoption at the clear-only completion would need its own design)"},
    {"id": "HL-2", "component": "_lab_fw.FirmwareWorld foreign-register marks (set_register actor 'inverter')",
     "anchor": (LAB_FW, "                self.foreign.difference_update(range(addr, addr + len(vals)))"),
     "limitation": "a register the inverter changes itself is marked foreign and keeps the lab's previous ORIGINAL; the "
                   "mark clears only when ECCO writes that register, so after a later START snapshots the foreign value "
                   "and restores it, the oracle still holds the stale ORIGINAL",
     "effect_on_verdicts": "INV-NO-SILENT-OVERRIDE can report a false override after a foreign change outside any "
                           "lease is snapshotted by a later START (a false violation); a foreign change while a domain "
                           "holds the register is judged correctly while the holding domain's RAM obligation is "
                           "visible; a register held only by a ghost's durable marker (a PR41-GHOST false negative, RAM "
                           "clear) can give a false violation when the ghost-admitted START snapshots the foreign value "
                           "(PB-01 extended seed 366 under the scratch ESPHome-like phase patch; RC-PR41-GHOST "
                           "observation note)",
     "worked_around_in": [
         "test_lab_property: PB-01 draws a register change as foreign (actor 'inverter') only while a domain holds that "
         "register (RAM snapshot, or a durable marker other than CLEAR / ABSENT), else as an owner change, the new "
         "baseline",
         "test_lab_fw_durability: the FW-06 flows set foreign values only during a lease or an owed restore"],
     "status": HL_STATUS},
    {"id": "HL-3", "component": "_lab_fw.FirmwareWorld.rtc_lock_windows: the RTC lock window MODEL",
     "anchor": (LAB_FW, "        if not self._rtc_windows or self.sim is None:"),
     "limitation": "an empty window list returns before correction_in_progress is updated, so replacing the windows "
                   "with [] while a lock is held leaves the RTC lock set until the next reboot (the boot's fresh RAM "
                   "starts correction_in_progress false, firmware restore_value no / initial_value false, and the empty "
                   "list never sets it again)",
     "effect_on_verdicts": "meanwhile every lease end and restore is deferred and every Free Power / Dump START is "
                           "REJECTED 'RTC correction currently active' (the START gates' !correction_in_progress term); "
                           "INV-RESTORE-BOUND explains the deferral as a held lock (a missed violation) while directed "
                           "timing checks would fail; no scenario does this",
     "worked_around_in": [
         "test_lab_property: PB-01 never draws an empty window list (windows are drawn relative to the current instant "
         "and recorded absolute)",
         "test_lab_fw_runtime: FW-08-E sets one non-empty window list per world",
         "test_lab_dst_rtc: RT-03 replays the extracted windows once per world",
         "test_lab_ha_lifecycle: the HF-02 RTC-lock variant passes one non-empty list"],
     "status": HL_STATUS},
    {"id": "HL-4", "component": "_lab_fw.check_restore_bound: INV-RESTORE-BOUND",
     "anchor": (LAB_FW, "def check_restore_bound(events, world=None, bound_s: float = 60, wd_s: float | None = None, "
                        "**_kw) -> list:"),
     "limitation": "once a restore is due, a link-down, bus-busy, injected-fault or power-off event anywhere in the due "
                   "period explains the whole period, however long the restore then takes after the link recovered or "
                   "the fault cleared",
     "effect_on_verdicts": "a restore delayed long after a link recovery passes INV-RESTORE-BOUND (a missed violation): "
                           "the Free Power restore waiting out the rest of its comms backoff (F-FW07-1) is not caught by "
                           "the checker itself; in PB-01, where random link, bus and fault actions explain most due "
                           "periods, the invariant is weak",
     "worked_around_in": [
         "test_lab_fw_runtime: FW-07-A, FW-07-B and FW-07-F measure the delay after link recovery directly (one "
         "watchdog tick plus one telemetry poll plus 5 s for the SG-39 path, the backoff steps for Free Power); FW-07-A "
         "and FW-07-I rebase INV-RESTORE-BOUND at the link recovery or the boot, a fresh period without the earlier "
         "fault",
         "test_lab_property: not worked around; PB-01's INV-RESTORE-BOUND verdicts carry this weakness (stated here)"],
     "status": HL_STATUS},
    {"id": "HL-5", "component": "_lab_fw invariant set: no cross-boot owed-restore checker",
     "anchor": (LAB_FW, 'INVARIANTS = {"INV-WS": check_write_surface, "INV-ONE-LEASE": check_one_lease,'),
     "limitation": "no core checker follows an owed restore across restarts: INV-RESTORE-BOUND explains an open period "
                   "by any lock held at least one watchdog period and by any fw.power_off event (every power cut, "
                   "reboot and firmware restart logs one; a fired cut counts as well), and INV-NO-RESUME and "
                   "INV-BOOT-MIRROR judge each boot on its own, so a restore that stays owed through repeated restarts "
                   "and is never attempted raises no core violation",
     "effect_on_verdicts": "a restart loop that never completes an owed restore passes every core invariant (each "
                           "restart's fw.power_off alone excuses the open period; a missed violation in the core oracle)",
     "worked_around_in": [
         "test_lab_fw_runtime: FW-08-F characterises the stuck-lock restart loop itself (restart instants about 203 s "
         "apart, no restore attempt, 244 and 256-261 unchanged, no CRITICAL status), pins it as F-FW08-1 with a "
         "finding-reproduces check and corpus FW-08-f, and states that the core checkers see no violation"],
     "status": HL_STATUS},
    {"id": "HL-6", "component": "registry/tests/_dump_sim.py load_record_status (shared simulator): a per-key boot load "
                                "fault; and its sibling, the lab's wrong_size boot fault (_lab_fw "
                                "FirmwareWorld._apply_boot_fault), which writes a wrong-size blob under the key",
     "anchor": ("registry/tests/_dump_sim.py", "def load_record_status(self, key, record):"),
     "limitation": "an injected per-key boot load fault reads READ_ERROR also for a key that was never stored, while "
                   "the firmware's length probe (classify_load_failure in firmware/include/ecco_durable_snapshot.h) "
                   "reports NOT_FOUND, i.e. ABSENT, there unless the probe itself fails; the lab's wrong_size boot fault "
                   "likewise creates a malformed record under a key that held none (a state no device write produces)",
     "effect_on_verdicts": "V0: a read-error or wrong-size fault on a never-stored marker key gave the fail-closed "
                           "UNKNOWN or MALFORMED lockout, which the device would show only if its probe also failed (an "
                           "outcome stricter than the likely device behaviour); such PB-01 draws drove 18 of its 19 "
                           "extended-mode N17 hits. Since V0.1 both faults are refused with a harness error on a key "
                           "never stored earlier in the run, so no verdict rests on them",
     "worked_around_in": [
         "test_lab_selftest_firmware: section [8b] pins the refusal (a read_error or wrong_size boot fault on the "
         "never-stored Dump marker raises a harness error naming HL-6, the same faults on the used marker apply, and a "
         "read_error after a whole-partition erase is refused again)",
         "test_lab_property: PB-01 draws a per-key boot fault only on a key that holds a record (otherwise a plain "
         "reboot), and an event-log fault scan pins zero faults on a key without a record; the PB-01-a, PB-01-b and "
         "PB-01-d corpus documents start with one completed lease; a false ABSENT of a key that is not stored is "
         "normalised to a plain reboot",
         "test_lab_fw_durability: the directed boot read errors (FW-04, FW-05) fault keys a lease has stored",
         "test_lab_fw_obligations: the FW-03 read error faults the Dump data record a lease has stored"],
     "status": "fixed in V0.1 by a lab-side refusal (the NVS USED-KEY RULE in _lab_fw "
               "FirmwareWorld._apply_boot_fault refuses read_error and wrong_size on a key never stored earlier in the "
               "run); the shared simulator itself is unchanged"},
    {"id": "HL-7", "component": "_lab_ha replay observer 'invariants' (coupled tier)",
     "anchor": (LAB_HA, '    "invariants": lambda cw, names=None, params=None, **flat: cw.invariants(names, params, '
                        '**flat),'),
     "limitation": "the coupled observer returns the raw violation list of the whole merged log; it lacks the firmware "
                   "tier's filters (boot_from, tags, untagged and the count / summary forms of "
                   "_lab_fw.filter_violations)",
     "effect_on_verdicts": "a coupled corpus document cannot pin an expected violation in a sequence-free form (its "
                           "count, boot or tag): a coupled FINDING document asserts the violation only as '!= []' for "
                           "one invariant, so an additional violation of that same invariant would not fail the replay",
     "worked_around_in": [
         "test_lab_ha_lifecycle: HF-09-a pins F-HF09-1 with '!= []' on INV-HF-ARM-OFF plus exact result, switch, SMR1, "
         "blocker, notification and firmware-status expectations, and '== []' on the invariants that must hold; the "
         "suite asserts the exact violations in memory",
         "test_lab_ha_schedules: the HF-01 documents bracket the simulated overrun between two INV-HF-WINDOW bound "
         "parameters ('!= []' just below it, '== []' just above it), which pins its size without a count form",
         "test_lab_ha_phantom: the HF-07 documents assert '== []' on the firmware invariants that must hold"],
     "status": HL_STATUS},
    {"id": "HL-8", "component": "_lab_ha.CoupledWorld.dump_plant: the opt-in Dump plant MODEL",
     "anchor": (LAB_HA, "    def dump_plant(self, *, house_w: int = 50, soc_drop_s: float = 180.0, period_s: float = "
                        "5.0) -> None:"),
     "limitation": "the plant stand-in is a CoupledWorld method, not a replay action or a world option, so no corpus "
                   "document and no PB-02 sequence can run a Dump lease with it; on the static telemetry image the "
                   "firmware's own controller ends a Dump lease early (CONTROLLER NO RESPONSE, failing closed)",
     "effect_on_verdicts": "Dump windows in the corpus and in PB-02 are mostly not run to their end, so Dump window-end "
                           "behaviour is judged only where a suite calls dump_plant() in memory (a coverage limit, not "
                           "a wrong verdict)",
     "worked_around_in": [
         "test_lab_ha_schedules: HF-01 and HF-04 run their Dump schedules with dump_plant(); corpus HF-01-c is shrunk to "
         "a 5-min window that expires by DURATION EXPIRED without the plant",
         "test_lab_ha_phantom: the HF-07 main chains use dump_plant(); the corpus cuts 5 min into the lease, before the "
         "static image would end it",
         "test_lab_dst_rtc: the HF-08 Dump runs use dump_plant()",
         "test_lab_ha_lifecycle: the HF-03 extended site-cut variant uses dump_plant()",
         "test_lab_property: PB-02 states the gap in its result"],
     "status": HL_STATUS},
    {"id": "HL-9", "component": "_lab_ha coupled replay actions: no service-fault action",
     "anchor": (LAB_HA, '    "reboot_dongle": _a_reboot, "api_outage": lambda cw, **a: cw.api_outage(**a),'),
     "limitation": "the coupled replay vocabulary has no action that makes a Home Assistant service call raise (the "
                   "interpreter's World.fail_services hook); a raised call reaches the corpus only through api_outage "
                   "under offline_policy 'raise'",
     "effect_on_verdicts": "HF-09.1 to HF-09.5 (a raised press, arm, restore write or turn-off) are verified in their "
                           "suite only and are not pinned by corpus documents; F-HF09-1 is pinned only in its API-outage "
                           "form (a coverage limit of the corpus, not a wrong verdict)",
     "worked_around_in": [
         "test_lab_ha_lifecycle: HF-09 sets fail_services per service name on the interpreter world inside the suite, "
         "every check asserting which call raised; HF-09-a (F-HF09-1) and its PASS twin HF-09-b reach S.ServiceError "
         "through api_outage with offline_policy 'raise' and are replayed by the suite and by test_lab_replay_corpus"],
     "status": HL_STATUS},
    {"id": "HL-10", "component": "_lab_fw FirmwareWorld scheduler (_sched_reset, run_for), the coupled tier's polled "
                                 "template sensors (_lab_ha RealDongle) and the RTC rig's interval start: the interval "
                                 "phase MODEL",
     "anchor": (LAB_FW, 'first = j["startup_ms"] if j["startup_ms"] is not None else j["period_ms"]'),
     "limitation": "every executed firmware interval runs first at its declared startup_delay, else one full period, "
                   "after power-on (uptime 0) with zero offset (plus the lab's own phase_ms sweep parameter) and is "
                   "rescheduled at due + T (now + T only for a slot a raw advance already missed); the two ESPHome "
                   "preference jobs are anchored at power-on likewise, the coupled tier samples its polled template "
                   "sensors first one period after power-on and then on the uptime grid, and the RTC rig starts its "
                   "intervals at a fixed phase. ESPHome 2026.8.2 runs an interval first at setup plus a random offset "
                   "uniform in [0, min(T/2, 5 s)) (core/scheduler.cpp:21 MAX_INTERVAL_DELAY 5000, :107-111 "
                   "calculate_interval_offset_, :182-184 first execution at now + offset; core/component.cpp:383 "
                   "start_poller at setup; components/interval/interval.h:14-16, a startup_delay is a set_timeout "
                   "followed by start_poller) and reschedules at now + T (scheduler.cpp:540). On the lab grid intervals "
                   "with commensurate periods meet on the same millisecond: the 15 s Free Power and Dump watchdogs tie "
                   "(their order is the explicit wd_order parameter) and the 10 s telemetry poll meets them every 30 s; "
                   "every timing-bound check therefore sits on one phase",
     "effect_on_verdicts": "a verdict that pins an instant, a same-tick order or a bound on the 5 s / 10 s / 15 s grid "
                           "holds at the lab's phase only. Every check that failed under an in-memory ESPHome-like "
                           "phase patch (first run at setup + startup delay + a seeded offset, reschedule at now + T; 17 "
                           "quick configurations: 8 seeds of the full patch and 3 seeds each of three narrower or "
                           "differently anchored variants; 3 extended seeds), every timing-bound check the independent "
                           "audit named, and every check the V0.1 review found phase-dependent without a FAIL line (the "
                           "HF-03 whole-site cut grid, whose F-HF03-2 pins can vanish while the point takes a held "
                           "branch, and the test_lab_ha_lifecycle finding register) is tagged: 200 PHASE_SENSITIVE_TAGS "
                           "prefixes in 13 suites (4 of them extended-only), 442 executed tagged checks in quick mode and "
                           "503 in extended mode (LAB-SUMMARY phase_sensitive), and 21 of 39 scenarios and 18 of 51 "
                           "findings (11 of them counted) carry phase_sensitive true. Under the patch the exact pins of "
                           "four counted reproductions fail: F-HF01-1 and F-HF04-2 in 17 of 17 configurations, F-HF04-1 "
                           "in 14 of 17 and F-HF08-3 in 6 of 17. F-FW03-2's pin is composite (both explicit wd_order "
                           "outcomes in one run: the Dump-first context hold with its operator exits and the Free "
                           "Power-first N17 contrast) and fails in 17 of 17 by construction, while its Dump-first "
                           "context-hold signature reproduces whenever the Dump watchdog's random offset is the smaller "
                           "(the context hold with its operator exits in 10 of the 17). F-HF03-1 reproduces at both "
                           "phases (4 of 6 swept points on the lab grid, 5 of 6 under the patch); F-HF03-2 reproduced at "
                           "the 60 s and 120 s / 5 s whole-site cut points wherever its section ran, while the 5 s / 5 s "
                           "point took the no-new-lease branch in 4 of the 5 configurations in which the section ran "
                           "(its pin then absent with no FAIL line). The RC-FALSE-ABSENT, RC-PR41-STRANDED-OVERRIDE and "
                           "RC-PR41-GHOST reproductions held under the patch; only their corpus trace digests, which "
                           "replay one recorded timeline on the lab grid by construction, failed. The corpus FINDING "
                           "documents FW-05-e, FW-06-a, FW-07-i3 and HF-05-b also fail an expectation under the patch "
                           "(6, 11, 10 and 11 times in the V0.1 review's 11 patched quick configurations; on HF-05-b's "
                           "fixed timeline the recorded deviation does not occur), while the suite pins of F-FW05-2, "
                           "F-FW06-1, F-FW07-5 and F-HF05-2 hold; these four findings carry phase_sensitive true for "
                           "that reason. In quick mode under the patch test_lab_ha_schedules (HF-04 / HF-06) ends "
                           "without a LAB-SUMMARY in all 11 patched quick configurations of the V0.1 review and "
                           "test_lab_ha_lifecycle in 12 of the 17 patched quick configurations above: both refuse an "
                           "interleaving inside a projected firmware transaction (LabUnsupported, fail loud); "
                           "test_lab_ha_lifecycle refuses the HF-03 whole-site cut at its "
                           "first grid point at full-patch seeds 1 to 5, at seeds 1 to 3 of both narrower variants and "
                           "at power-on seed 1, and completes at full-patch seeds 6 to 8 and power-on seeds 2 and 3, "
                           "where the site-cut 5 s / 5 s point changes branch (F-HF03-2); extended mode adds "
                           "LabUnsupported refusals in the ha_lifecycle and ha_phantom extended sections. At f11d85f "
                           "(V0.1 commit 3) two more suites stopped in quick mode: test_lab_property on the PB-03-b "
                           "replay refusal (an action due before the world clock) and test_lab_selftest_firmware on a "
                           "ValueError in its same-tick watchdog self-test. Since V0.1 commit 4 test_lab_property records "
                           "a replay exception as a FAIL of that document (tagged) and continues, the selftest_firmware "
                           "same-tick checks fail (tagged) instead of raising, and test_lab_selftest_rtc runs its "
                           "replay-engine controls on a draft recorded without its timeline-bound lock_windows "
                           "expectation when record() fails; with patch seeds 1 to 3 these three suites end with a "
                           "LAB-SUMMARY and every FAIL tagged. Re-run at f11d85f with patch seeds 1 to 3: the same "
                           "counted reproductions fail; two test_lab_replay_corpus negative controls (NC-RC-1, NC-RC-4) "
                           "also failed untagged, because their control document FW-06-a has timeline-bound "
                           "expectations since its V0.1 used-key prelude. V0.1 runs those engine controls on the "
                           "expectations that hold on the tree under test; with patch seeds 1 to 3 they hold",
     "worked_around_in": [
         "test_lab_fw_obligations: FW-03 runs both same-tick watchdog orders (the explicit wd_order) and, in extended "
         "mode, a de-aligned watchdog phase sweep; F-FW03-1 and F-FW03-2 are tagged phase-sensitive",
         "test_lab_ha_schedules: HF-01 sweeps the watchdog phase (wd_phase_s 0, 5 and 10 s in quick mode, 0 to 14 s in "
         "extended mode) and reports the overrun per point; the exact F-HF01-1, F-HF04-1 and F-HF04-2 pins and the "
         "NC-HF04 / NC-HF06 controls are tagged",
         "test_lab_ha_lifecycle: the HF-03 early-reset reach is printed per swept point with the polled-counter phase "
         "stated as INFERRED, and tagged; the HF-03.4 whole-site cut grid checks (whose names carry the branch), the "
         "F-HF03-2 pins and the finding register are tagged too",
         "test_lab_fw_runtime: the FW-07-A, FW-07-E, FW-07-I and FW-08-B / C / D timing-bound checks are tagged with "
         "the grid their bound sits on",
         "test_lab_dst_rtc: the RT-01 and RT-03 checks bound to one RTC read phase are tagged",
         "test_lab_replay_corpus: every per-document replay check is tagged (a trace digest replays one recorded "
         "timeline on the lab grid) and its engine negative controls run on the control document's expectations that "
         "hold on the tree under test; in every suite a stale-tag check fails loud when a tag matches no executed check, "
         "and LAB-SUMMARY phase_sensitive counts the executed tagged checks"],
     "status": "open: the lab keeps its zero-offset grid; an ESPHome-faithful phase distribution (many seeded offsets "
               "per run, with per-finding reproduction fractions) is not implemented. The phase dependence is "
               "disclosed by the tags, the catalogue phase_sensitive fields and "
               "LAB-SUMMARY phase_sensitive, not removed"},
    {"id": "HL-11", "component": "registry/tests/_dump_sim.py Sim.execute (shared simulator) and _lab_fw StrictSim / "
                                 "LabEntity.is_running: script.execute runs the callee to completion inside the caller",
     "anchor": ("registry/tests/_dump_sim.py", "return  # mode: single - dropped, exactly like ESPHome"),
     "limitation": "ds.Sim runs every script synchronously (wait_until and delay are no-ops, _dump_sim.py "
                   "'elif kind in (\"wait_until\", \"delay\", \"logger.log\"):'), so script.execute returns only after "
                   "the callee's whole run, and a script counts as running only while it is on the lab's synchronous "
                   "call stack. The re-entry drop the anchor line calls 'exactly like ESPHome' therefore matches ESPHome "
                   "only where both agree that the script is running, and script.is_running() answers from the call "
                   "stack. ESPHome 2026.8.2's ScriptExecuteAction only starts the callee (components/script/script.h:239) "
                   "and the caller continues as soon as the callee suspends at a delay, a wait_until or a Modbus "
                   "request; a single-mode script drops an execute while an earlier run is still in flight (script.h:"
                   "79-87). The divergent forms: (C1) firmware work the caller runs after the call happens in the lab "
                   "after the callee's whole remainder, on the device before it; (R) a second execute of a script at "
                   "the instant its first run reached a suspension point is run again by the lab and dropped by the "
                   "device (a crafted double-end Dump watchdog tick re-runs restore_dump_to_grid_snapshot and replaces "
                   "RESTORED OK with END IGNORED); (ISR) is_running() reads false for a script whose run would still "
                   "wait in its own delays on the device; (busy) in the coupled projection a caller kept on the stack "
                   "by a nested execute would count as busy (MISS-HA-1, refused since V0.1, HL-12)",
     "effect_on_verdicts": "measured at f11d85f (V0.1 commit 3; commit 4 changes no executed scenario or corpus "
                           "trace) by a scratch observation hook that changes no output (every "
                           "suite identical with and without it, runtimes masked), quick / extended, scenario suites "
                           "plus replay corpus: C1 1272 / 6515 (self-tests 23 / 23), in three patterns, all Dump: the "
                           "watchdog's request_dump_end -> restore_dump_to_grid_snapshot then the watchdog's next branch "
                           "800 / 3622, the watchdog's dump_controller_tick then a lambda 461 / 2824, and "
                           "dump_force_restore_original -> restore then the arm turn-off lambda 11 / 69; in each the "
                           "caller's later work reads state the lab's restore already completed. The double-end form "
                           "(R within one world step) occurs 0 / 0 times (the crafted probe gives 1); a same-instant "
                           "re-execute from a separate world action at 0 ms spacing occurs 183 / 1715 times (self-tests "
                           "0 / 1: repeated START presses, telemetry polls at a slot instant, configuration polls), which "
                           "the device would drop while the first run is in flight; is_running() is evaluated 0 / 0 "
                           "times (its firmware uses sit in paths no scenario reaches or behind a condition that is "
                           "false there); no execute is dropped and no non-single script is re-entered (0 / 0). No "
                           "catalogued verdict is known to rest on these forms, but the lab does not detect them: in "
                           "the firmware tier they pass silently",
     "worked_around_in": [
         "test_lab_selftest_coupling: section [16] pins the coupled-tier half: a START press while START is in the "
         "projected window only through its nested restore execute raises LabUnsupported (MISS-HA-1), and a press "
         "while the pressed script's own work is pending is still dropped, as ESPHome's single mode drops it"],
     "status": "open: an asynchronous script model, or a lab-side detector that turns C1 / R occurrences into "
               "UNSUPPORTED points, is not implemented, and _dump_sim.py is a shared interpreter the lab does not "
               "modify; turning C1 into UNSUPPORTED would mark most Dump watchdog lease ends unsupported"},
    {"id": "HL-12", "component": "the lab's fail-loud rule: the _lab_ha projection, same-script press rule and package "
                                 "/ runtime guards, the _lab_fw StrictSim allow-lists and NVS used-key rule, the replay "
                                 "engine and the suite output contract",
     "anchor": (LAB_HA, "  - Interleaving inside a firmware transaction (fail loud instead, see Projection), Modbus "
                        "latency beyond the per-outcome"),
     "limitation": "fail loud covers only the constructs the lab detects: then the scenario is a FAIL, BLOCKED or an "
                   "UNSUPPORTED point, never a PASS. Since V0.1 that includes, in the coupled tier, an interleaving "
                   "anywhere in a projected transaction whose window now lasts by op outcome (no_response 2.0 s, the "
                   "ESPHome 2026.8.2 hub send-wait; timeout 3.0 s, the firmware's bounded wait_until; op_s otherwise; "
                   "plus a delay executed under a lock), so the V0 projection gap is refused (ISS-HA-2); a same-script "
                   "press while the script is busy only through a nested script.execute (MISS-HA-1; a press while its "
                   "own work is pending is still dropped, as the device drops it); package options the interpreter "
                   "ignores (a static guard at load), template values whose truthiness differs from Home Assistant's "
                   "condition rule and input_number values outside the helper's range (runtime guards; ISS-HA-5); and "
                   "in the firmware tier an injected NVS fault on a key never stored earlier in the run. Still silent: "
                   "the duration of lock-free delays and polls (zero projected time), Modbus turnaround and queueing "
                   "behind another firmware run, a wait_until whose condition is false in the lab (skipped where the "
                   "device blocks up to its timeout), the synchronous script.execute forms (HL-11), the scheduler "
                   "phase (HL-10) and the signedness of u-suffixed literals, which the transpiler drops",
     "effect_on_verdicts": "a PASS means the run met no detected unmodelled construct, not that the device would "
                           "behave the same where the lab is silent. Measured at f11d85f (V0.1 commit 3; commit 4 "
                           "changes no executed scenario or corpus trace), quick / extended, "
                           "scenario suites plus replay corpus: projection-gap interleavings 0 / 0, nested-only presses "
                           "0 / 0, transactions with a no_response or timeout op or an in-lock delay 0 / 0, ignored "
                           "package options 0 / 0 (247 / 708 package-set checks), truthiness refusals 0 / 0 (283424 / "
                           "881859 values), input_number refusals 0 / 0 (2665 / 7503 writes); silent: lock-free delays "
                           "met inside coupled runs 77664 / 286912 and explicit delays skipped by the firmware "
                           "simulator 171176 / 826468, Modbus ops of two different world steps at one firmware instant "
                           "1961 / 8914 (of "
                           "342703 / 1628134 ops, each taking 0 ms in the firmware tier), skipped false wait_until 87 / "
                           "186 (every one after a timeout or custom_response outcome: a duration-only divergence), "
                           "transpiler gaps 0 (no `continue` or `sizeof` site, 0 snprintf outputs longer than their "
                           "buffer, 0 out-of-range values at the 5 unreduced unsigned sites). The V0.1 corrections "
                           "turned no previously passing scenario UNSUPPORTED; the existing refused-interleaving points "
                           "(test_lab_ha_lifecycle 2, test_lab_ha_schedules 8 in extended mode) lie outside the "
                           "projection gap",
     "worked_around_in": [
         "test_lab_selftest_coupling: sections [15] to [18] pin the per-outcome projection (the ISS-HA-2 probes refused "
         "with no_response and timeout, the same press applied after the corrected window, an in-lock delay extending "
         "the window), the MISS-HA-1 refusal and the own-work drop, the static guard (the real packages pass; enabled: "
         "false and 25 other injected constructs are refused) and the runtime truthiness and input_number guards",
         "test_lab_selftest_firmware: section [8b] pins the NVS used-key refusal for every refused commit mode and boot "
         "fault, with the same faults on a used key accepted",
         "test_lab_ha_lifecycle: sweep points that meet a refused interleaving or an unclassified harness outcome print "
         "an UNSUPPORTED line, never PASS (3 ids, 5 points in quick mode)",
         "test_lab_ha_schedules: the extended HF-04 interleaving sweep prints its 8 refused points as UNSUPPORTED "
         "(HF-04-UNS-EXT)"],
     "status": "open (a scope statement): the silent items are listed with measured counts in the register of silent "
               "divergences (design document section 2.7); refusing them needs an asynchronous script and bus model"},
    {"id": "HL-13", "component": "_lab_fw oracle checkers: INV-NO-SILENT-OVERRIDE's explanation rule, "
                                 "INV-RESTORE-BOUND's excuse set and the invariant set (no SG-02 containment checker)",
     "anchor": (LAB_FW, "        if not diff or vis:"),
     "limitation": "(1) INV-NO-SILENT-OVERRIDE accepts any RAM-visible obligation (a valid snapshot mirror or a corrupt "
                   "/ UNKNOWN lockout of fp, dump or r244) as explaining every differing owned register (the anchor "
                   "line; quiet_state's 'silent' uses the same rule); it does not map a register to the domain that "
                   "owns it, although DOMAIN_REGS exists, so an override of a Free Power register while a Dump "
                   "obligation is visible, or under any lasting lockout, stays masked while that obligation is "
                   "visible. (2) INV-RESTORE-BOUND's excuse set is filled by any injected fault, power-off, cut, "
                   "link-down, bus-busy, lockout or long-lock observation inside the due period and is reset only when "
                   "a new period opens, so one short excuse explains the whole period however long the restore then "
                   "takes (the mechanism HL-4 states). (3) No invariant checks SG-02 containment: INV-LOCKOUT-QUIET "
                   "only whitelists the literal 244 = 2 write (check_lockout_quiet, 'SG-02 containment literal') and "
                   "INV-NO-SILENT-OVERRIDE is satisfied by the lockout itself",
     "effect_on_verdicts": "each can only miss a violation, never create one. (1) a white-box override of 230 during "
                           "a Dump lease stays masked while dump.snap or dump.corrupt is visible (a V0.1 reproduction "
                           "probe). (2) measured at f11d85f (V0.1 commit 3; commit 4 changes no executed scenario or "
                           "corpus trace) with a scratch counting copy of the checker that "
                           "returns the original result in every call (quick / extended, scenario suites): 580 / 3955 "
                           "over-bound evaluations are excused (246 / 1339 distinct due periods; the audit counted 540 "
                           "at the V0 HEAD), 474 / 2908 of them by a lockout; a true latch, the excuse no longer active "
                           "for more than the 60 s bound before the completion or the end, occurs 4 / 68 times (3 / 38 "
                           "distinct periods): Free Power restores that wait out their comms backoff after the link "
                           "returns (the F-FW07-1 mechanism; test_lab_fw_runtime, 1 period in quick mode, 4 in "
                           "extended mode), one Dump period each in test_lab_fw_runtime and test_lab_ha_schedules, and "
                           "32 distinct PB-01 extended-mode periods (mostly restores still open at the end of the "
                           "sequence, the last Modbus fault 63 to 296 s earlier), not triaged; the replay corpus has "
                           "none (37 / 74 excused). "
                           "(3) a mutant whose Dump watchdog never arms containment (the audit's M5: a "
                           "metadata-corrupt Dump lockout leaves 244 = 0, Allow Export) passes all eight invariants; at "
                           "f11d85f it is killed only by directed checks and corpus replays (test_lab_fw_durability "
                           "'FW-04 guard', test_lab_fw_obligations 'FW-01 (a)' and its SG-02 variant, test_lab_ha_phantom "
                           "'a: no ECCO write during the lockout except SG-02 containment', the FW-01 / FW-04 / FW-05 / "
                           "HF-07 replays)",
     "worked_around_in": [
         "test_lab_fw_runtime: FW-07-A, FW-07-B and FW-07-F measure the restore delay after a link recovery directly "
         "and FW-07-A / FW-07-I rebase INV-RESTORE-BOUND at the recovery or the boot (the latch, as HL-4)",
         "test_lab_fw_obligations: FW-01 asserts the SG-02 containment writes (only the literal 244 = 2, CONTAINED) "
         "and the per-register bank values directly, not through the checkers",
         "test_lab_fw_durability: the FW-04 guard asserts that containment writes only 244 := 2 under the fail-closed "
         "lockout",
         "test_lab_ha_phantom: the HF-07 chains assert that the only ECCO write during the lockout is SG-02's 244 := 2"],
     "status": "open: a per-register explanation rule, expiring excuses and an SG-02 containment invariant are not "
               "implemented; the audit predicts that the first two re-find only already-counted findings (F-FW07-1, "
               "F-FW08-1), which V0.1 did not test"},
]

# ------------------------------------------------------------------------------------------------------------------------
# coverage matrix
# ------------------------------------------------------------------------------------------------------------------------
DIMENSIONS = ["schedule start/retry", "lease acquisition", "durable snapshot", "commit false negative", "active lease",
              "HA restore obligation", "lock contention", "stale state", "clock policy (RTC/DST)", "terminal restoration",
              "human manual change", "HA restart", "dongle reboot / power cut", "Modbus faults"]

FPS1_T = "home-assistant/tests/test_ecco_free_power_schedule_reliability.py"
DGS1_T = "home-assistant/tests/test_ecco_dump_to_grid_schedule_reliability.py"
SMR1_T = "home-assistant/tests/test_ecco_schedule_manual_restore.py"
EXISTING = {
    "schedule start/retry": [
        FPS1_T + ": FPS1 start, poll-phase sweep, transient vs persistent refusals, retry deadline and window clamp, and "
                 "raised service calls (fail_services) against the hand-written dongle model",
        DGS1_T + ": the DGS1 equivalents against the hand-written Dump dongle model",
        "home-assistant/tests/test_ecco_start_failure_alert.py: failed-start health counters against subclassed dongle "
        "models"],
    "lease acquisition": [
        "registry/tests/test_cross_domain_start_gates.py: every cross-domain term of the Free Power and Dump START gates "
        "(structure and mutation)",
        "registry/tests/test_dump_to_grid_behaviour.py: Dump START gate, snapshot before write, exhaustive single-fault "
        "activation",
        "registry/tests/test_free_power_write_sequencing_hardening.py: Free Power START write sequencing under exhaustive "
        "write outcomes",
        "registry/tests/test_sg01_journal_phase1_2.py: Free Power START journal commit before each write"],
    "durable snapshot": [
        "registry/tests/test_recovery_marker_state_machine.py: the marker state machine (structure)",
        "registry/tests/test_sg06_boot_durable_read_fail_closed.py: boot read faults per domain on the real on_boot",
        "registry/tests/test_dump_v2_ownership_evidence.py: Dump record layout and its START / controller power-cut sweep",
        "registry/tests/test_free_power_dump_obligation_arbitration.py: the Free Power / Dump dual-obligation boot "
        "lockout (structure plus a Python reference model)",
        "registry/tests/test_durable_obligation_arbitration.py: the S4 Dump / register 244 dual obligation (structure "
        "plus a model)"],
    "commit false negative": [
        "registry/tests/test_free_power_dump_obligation_arbitration.py: a Phase-B false negative in a hand-written Python "
        "model only (not firmware)",
        "registry/tests/test_sg01_journal_phase1_2.py: journal commit failures (true negatives) at the START blocks"],
    "active lease": [
        "registry/tests/test_dump_to_grid_behaviour.py: ACTIVE monitors, runaway guard and controller",
        "registry/tests/test_dump_safety_fcp2.py: ending-state controller writes, frozen telemetry, ownership-checked "
        "restore",
        "registry/tests/test_free_power_reboot_behaviour.py: S3, an ACTIVE Free Power lease is not resumed after a reboot"],
    "HA restore obligation": [
        SMR1_T + ": SMR1 save / restore, failed start, bus busy, End, graceful restart, ownership blockers, owner changes, "
                 "STALE, a raised restore write and races against the dongle models"],
    "lock contention": [
        "registry/tests/test_write_surface_invariants.py: write paths, arms and the shared write mutex (structure)",
        "registry/tests/test_dump_safety_fcp2.py: stuck-lock escalation and gated restart",
        "registry/tests/test_rtc_verification_lock_leak.py: RTC verification lock release (text plus a hand model)",
        "registry/tests/test_fbd1_liveness.py: polls yield to the RTC lock and the write mutex"],
    "stale state": [
        "registry/tests/test_dump_to_grid_behaviour.py: stale SOC / configuration refusals and READBACK STALE",
        "registry/tests/test_dump_safety_fcp2.py: frozen CT / battery / SOC and the SG-39 backoff after link recovery",
        DGS1_T + ": stale SOC / configuration / grid transient refusals (model)"],
    "clock policy (RTC/DST)": [
        "registry/tests/test_rtc_policy.py: RTC decision table, time arithmetic and C++ / Python parity (needs a compiler)",
        "registry/tests/test_fbd1_liveness.py: RTC transaction, breaker and the DST fall-back / spring-forward large "
        "correction",
        "registry/tests/test_cross_domain_start_gates.py: the RTC lock as a START conjunct (structure)"],
    "terminal restoration": [
        "registry/tests/test_dump_to_grid_behaviour.py: restore single-fault sweep, lockout, backoff, PENDING_CLEAR",
        "registry/tests/test_sg01_self_partial_phase3_4.py: Free Power restore classifier and interrupted restores",
        "registry/tests/test_free_power_recovery_force_restore.py: operator Force Restore gates",
        "registry/tests/test_dump_lockout_containment_sg02.py: SG-02 containment under a corrupt Dump obligation"],
    "human manual change": [
        "registry/tests/test_manual_tou_phase1_ownership_gates.py: manual TOU script-level ownership gates",
        "home-assistant/tests/test_ecco_tou_target_soc_edit.py: guarded TOU target-SOC edit against a manual TOU model",
        SMR1_T + ": owner changes kept or dropped by SMR1 (model)",
        "registry/tests/test_dump_lockout_containment_sg02.py: an external 244 re-enable reported, not reasserted"],
    "HA restart": [
        FPS1_T + ": graceful HA restarts around the start (model)",
        DGS1_T + ": graceful HA restarts (model)",
        SMR1_T + ": graceful restarts during the lease, the settle and RESTORING (model)"],
    "dongle reboot / power cut": [
        "registry/tests/test_sg01_phase5_hardening.py: power cut at every START / restore event, rebooted through the Free "
        "Power boot block",
        "registry/tests/test_dump_v2_ownership_evidence.py: Dump power-cut sweep with a double reboot through the Dump and "
        "arbitration slices",
        "registry/tests/test_free_power_reboot_behaviour.py: reboot during a Free Power lease (S3)",
        "registry/tests/test_dump_to_grid_behaviour.py: a reboot mid-lease ends and restores"],
    "Modbus faults": [
        "registry/tests/test_dump_to_grid_behaviour.py: exhaustive single-fault activation and restore",
        "registry/tests/test_free_power_write_sequencing_hardening.py: exhaustive START / restore write-outcome sweeps",
        "registry/tests/test_free_power_reg244_context_v4.py: register 244 outcome sweeps for the context hold",
        "registry/tests/test_fbd1_liveness.py: RTC write / verify outcome faults"],
}
LAB = {
    "schedule start/retry": ["HF-01", "HF-02", "HF-04", "HF-05", "HF-06", "HF-09", "PB-02"],
    "lease acquisition": ["FW-01", "FW-05", "FW-06", "FW-10", "HF-04", "HF-07", "PB-01"],
    "durable snapshot": ["FW-01", "FW-02", "FW-03", "FW-04", "FW-05", "FW-06", "FW-10", "FW-11", "PB-01"],
    "commit false negative": ["FW-01", "FW-02", "FW-03", "FW-05", "FW-06", "HF-07", "PB-01"],
    "active lease": ["FW-04", "FW-07-A", "FW-07-C", "FW-07-H", "FW-07-I", "FW-08-C", "FW-08-D", "HF-01", "HF-03", "RT-01",
                     "RT-03"],
    "HA restore obligation": ["HF-01", "HF-02", "HF-05", "HF-06", "HF-07", "HF-09", "PB-02"],
    "lock contention": ["FW-08-A", "FW-08-B", "FW-08-C", "FW-08-D", "FW-08-F", "HF-05"],
    "stale state": ["FW-07-A", "FW-07-B", "FW-07-C", "FW-07-F", "FW-07-H", "FW-07-I"],
    "clock policy (RTC/DST)": ["FW-08-E", "HF-08", "RT-01", "RT-02", "RT-03", "PB-03"],
    "terminal restoration": ["FW-01", "FW-02", "FW-03", "FW-05", "FW-06", "FW-07-B", "FW-07-F", "FW-07-I", "FW-09", "HF-01",
                             "HF-06", "HF-09", "RT-01"],
    "human manual change": ["FW-02", "FW-07-D", "HF-02", "HF-05", "PB-01"],
    "HA restart": ["HF-02", "HF-03", "HF-07", "PB-02"],
    "dongle reboot / power cut": ["FW-01", "FW-04", "FW-05", "FW-07-C", "FW-07-E", "FW-07-G", "FW-07-I", "FW-08-B", "FW-11",
                                  "HF-03", "HF-07", "PB-01", "PB-03"],
    "Modbus faults": ["FW-07-B", "FW-07-D", "FW-07-F", "FW-07-H", "FW-08-A", "FW-09", "HF-06", "PB-01"],
}
INTERSECTIONS = [
    (("schedule start/retry", "HA restart"), FPS1_T, ["HF-02", "PB-02"],
     "the existing coverage is graceful restarts against the dongle model; the lab's crash rollback rests on the 15-min "
     "restore-state ASSUMPTION (not measured) and real ESPHome reconnect timing is not modelled"),
    (("lease acquisition", "commit false negative"), "registry/tests/test_free_power_dump_obligation_arbitration.py",
     ["FW-01", "FW-05", "HF-07", "PB-01"],
     "the existing coverage is a Python model; the lab runs the real firmware, but the physical trigger (a same-key NVS "
     "error after the write) is REPORTED from the ESP-IDF documentation, not verifiable offline, and its rate is UNKNOWN; "
     "since V0.1 the lab injects it only on a key stored earlier in the run (one ESP-IDF fault cell, the other cells "
     "not modelled)"),
    (("active lease", "dongle reboot / power cut"), "registry/tests/test_free_power_reboot_behaviour.py",
     ["FW-04", "FW-07-C", "FW-07-E", "HF-03", "HF-07"],
     "a cut inside a Modbus frame or an NVS write (a torn record) is not modelled; in the coupled tier a cut inside a "
     "projected transaction is UNSUPPORTED (HF-03-UNS-1)"),
    (("HA restore obligation", "human manual change"), SMR1_T, ["HF-05", "HF-02"],
     "owner edits inside a projected firmware transaction are UNSUPPORTED (HF-05-UNS-1, HF-05-UNS-2); the restore-write "
     "race window rests on model latencies"),
    (("lock contention", "terminal restoration"), "registry/tests/test_dump_safety_fcp2.py",
     ["FW-08-B", "FW-08-C", "FW-08-D", "FW-08-F"],
     "the lock leak is a white-box RAM injection (no leaking code path that overlaps a lease is known); Fallback Review / "
     "Save mutex holds are UNSUPPORTED (FW-08-U2)"),
    (("stale state", "active lease"), "registry/tests/test_dump_safety_fcp2.py",
     ["FW-07-A", "FW-07-C", "FW-07-H", "FW-07-I"],
     "the polls run with MODEL on_response handlers; frozen telemetry with the link up (FW-07-I) needs the meter-noise "
     "MODEL off for the whole world, so every poll slot is set explicitly and the SOC changes only when a scenario sets "
     "it (no SOC physics); NTP loss after a first sync is UNSUPPORTED (FW-07-U1)"),
    (("clock policy (RTC/DST)", "active lease"), "registry/tests/test_fbd1_liveness.py", ["RT-01", "RT-03", "FW-08-E"],
     "a Dump lease cannot run on the RTC rig (split model with injected windows); windows beyond the 90 s breaker are "
     "UNSUPPORTED in the firmware tier (FW-08-E-U1)"),
    (("clock policy (RTC/DST)", "lease acquisition"), "registry/tests/test_cross_domain_start_gates.py", ["HF-08", "RT-03"],
     "SG-25 reproduces (known, deferred); the inverter executing its TOU on its own clock is not modelled (in-slot seconds "
     "INFERRED)"),
    (("durable snapshot", "dongle reboot / power cut"), "registry/tests/test_sg01_phase5_hardening.py",
     ["FW-04", "FW-05", "FW-06", "FW-11", "PB-01"],
     "torn records and a cut between save() and sync() are not modelled; the lab boots through the FULL on_boot where the "
     "existing sweeps use boot slices"),
    (("commit false negative", "HA restore obligation"), "none", ["HF-07"],
     "only the Phase-B marker false negative is driven through Home Assistant; the HA system-health mapping of the lockout "
     "is UNSUPPORTED (HF-07/system-health)"),
    (("schedule start/retry", "dongle reboot / power cut"), "none", ["HF-03"],
     "the early-reset case is a PROXY (grade INFERRED); later in-transaction cuts are UNSUPPORTED (HF-03-UNS-1)"),
    (("schedule start/retry", "terminal restoration"), FPS1_T, ["HF-01", "HF-04"],
     "the existing window-end check runs against the model's instant end; the lab sweeps the watchdog phase and bus "
     "traffic, which are not measured on hardware"),
    (("HA restart", "dongle reboot / power cut"), "none", ["HF-03"],
     "the outcome depends on the HA versus dongle boot order (swept by down times); real reconnect timing not modelled"),
    (("durable snapshot", "human manual change"), "none", ["FW-02"],
     "the HA target-SOC editor path under a phantom obligation is source-read only, not executed"),
    (("commit false negative", "terminal restoration"), "registry/tests/test_durable_obligation_arbitration.py",
     ["FW-03", "FW-05"],
     "the same-tick watchdog order is a lab tie; both orders are swept (on hardware each boot draws a random order)"),
    (("stale state", "terminal restoration"), "registry/tests/test_dump_safety_fcp2.py", ["FW-07-B", "FW-07-F"], ""),
    (("Modbus faults", "schedule start/retry"), SMR1_T, ["HF-06"],
     "the existing SMR1 premise (End & Restore required after a failed START) holds only for the HA models"),
    (("schedule start/retry", "HA restore obligation"), SMR1_T, ["HF-01", "HF-06", "HF-09"],
     "a raised service call (S.ServiceError before delivery, the interpreter's only modelled exception) is injected per "
     "service name inside the HF-09 suite; no replay action injects it (harness_limitations HL-9), so only the "
     "api_outage form (HF-09-a, HF-09-b) is pinned in the corpus"),
    (("clock policy (RTC/DST)", "schedule start/retry"), "none", ["HF-08", "PB-02"],
     "real Home Assistant fold / gap resolution is INFERRED (fold=0 ASSUMPTION)"),
]
REQUIRED_PAIRS = [("schedule start/retry", "HA restart"), ("lease acquisition", "commit false negative"),
                  ("active lease", "dongle reboot / power cut"), ("HA restore obligation", "human manual change"),
                  ("lock contention", "terminal restoration"), ("stale state", "active lease"),
                  ("clock policy (RTC/DST)", "active lease"), ("durable snapshot", "dongle reboot / power cut"),
                  ("commit false negative", "HA restore obligation")]
