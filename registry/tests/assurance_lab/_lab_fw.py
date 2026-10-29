"""Assurance lab V0: FirmwareWorld - the whole ECCO dongle firmware on a true UTC timeline (test-only helper: no network, no
Home Assistant, no hardware; it reads repository files and writes nothing).

One FirmwareWorld is one physical dongle plus its inverter. The REAL firmware (Free Power and Dump to Grid START / END /
restore / recovery scripts, both 15 s watchdogs, every executable interval, the FULL on_boot) runs through
registry/tests/_dump_sim.py (parsed ESPHome action trees + the strict C++-subset transpiler). Nothing here decides what the
firmware does: the lab supplies the environment (clock, inverter registers, telemetry image, faults) and observes.

PUBLIC API
  constants   FW_REL, FW_PATH, TIER ('firmware'); WRITE_OUTCOMES / READ_OUTCOMES (the Modbus outcome allow-lists),
              LANDED_OUTCOMES; WRITE_SURFACE {22-24, 230, 232, 244, 250-261, 268-279}; OWNED (WRITE_SURFACE minus 22-24);
              DOMAIN_REGS {fp, dump, r244}; TAGS (alias -> durable NVS tag: fp.valid / fp.data / fp.retry / fp.journal,
              dump.valid / dump.data / dump.data_v1 / dump.retry, r244.valid / r244.data); MARKER_TAGS {fp, dump, r244};
              STATUS_IDS {fp, dump, dump_end, manual, r244}; HA_VIEW; OWNER_DOMAINS; SITE; ENV_DEFAULT; INTERVAL_SPECS /
              BOOT_SPECS (content markers); NOT_EXECUTED {job: reason}; PARTIAL {job: reason}; NOT_EXECUTED_BOOT {item:
              reason}; MODEL_HANDLERS {(script, start_address, count): reason}; PREF_JOBS ('pref_poll', 'pref_sync');
              SOURCE_ANCHORS; NVS_MODES; NVS_BOOT_FAULTS; ACCEPT_SUCCESS_TEXTS {fp, dump} / DUMP_ACCEPT_RESIDUE_FORM (the
              firmware's operator Accept SUCCESS texts, the HL-1 rule)
  accept_succeeded(dom, text) -> bool; accept_adoption(dom, pre_obl, post_obl, texts) -> {result, success, held, cleared,
              adopt, kept, reason}: the HL-1 rule for the lab ORIGINAL after an operator Accept (pure; MODEL ASSUMPTIONS)
  errors      LabHarnessError (harness misuse, an environment the lab refuses to guess), LabUnsupported(LabHarnessError) (a
              construct the lab cannot represent). ds.Unsupported, KeyError, ValueError and AttributeError raised while the
              firmware runs are never caught: they propagate (fail loud).
  load_fw(text=None) -> fw          parsed once per text (cache key sha256 of the text); None = the worktree FW_PATH
  fw_info(fw) -> _FwInfo            derived tables: entity registry, interval jobs, boot items, MODEL handler code
  site_bank(overrides=None) -> dict the synthetic register image; rewrite_static_casts(code) -> code (see MODEL)
  script_domain(script_id) -> 'fp' | 'dump' | 'manual' | 'r244' | 'rtc' | 'other' | 'interval'
  class LabEntity(ds.Entity)        a firmware entity of a known kind: switch / binary_sensor states are bool by
                                    construction (assigning NaN or any non-bool raises), select.current_option() per
                                    instance, script.is_running(), explicit initial states (MODEL ASSUMPTIONS);
                                    turn_on() / turn_off() of a restoring switch raises LabUnsupported
  class StrictSim(ds.Sim)           (a) Modbus outcome allow-list: any other outcome string raises LabHarnessError;
                                    (b) sealed entity registry pre-created from EVERY firmware entity id (sensor,
                                    binary_sensor, switch, number, text_sensor, button, select, script, time, modbus, uart):
                                    ent() of an unknown id raises; (c) explicit initial states; (d) per-instance select
                                    options (ds.Entity is never patched); (e) a read of a register the bank does not hold
                                    raises (never a silent 0); (f) MODEL_HANDLERS for the non-transpilable poll on_response
                                    lambdas; (g) script call stack (writer attribution) and START / publish callbacks;
                                    (h) button.press runs a template button's real on_press (ds.Sim only records it) and a
                                    press of the `restart` platform button reboots through the world
  class FirmwareWorld(fw=None, *, utc_start, bank=None, dump_limits=SITE['dump_limits'] | 'factory', boot='full',
                      boot_ms=2000, ntp_after_s=5, seed=0, noise=True, phase_ms=None, warmup_s=0, restart_down_s=3.0)
      utc_start (int epoch s) is the UTC instant of the first on_boot; bank: register overrides merged onto site_bank();
      dump_limits: the persisted (ceiling, max_export) or 'factory'; boot='full' boots in the constructor, None defers to
      world.boot(nvs=...) (seed an NVS image first); boot_ms: uptime at on_boot; ntp_after_s: uptime of the first NTP sync
      (None: never); noise: the meter-noise MODEL; phase_ms {job: extra first-run delay ms}; warmup_s: run_for after
      boot; restart_down_s: the down time of a firmware-requested restart.
    state     log (T.EventLog, kept across reboots), sim (the current StrictSim), bank (the inverter), boot_no (0 = first
              boot), original (the synthetic ORIGINAL the owner expects), foreign (registers last changed by the
              inverter), accept_log (one accept_adoption() record + boot, t_utc, dom per operator Accept; in memory, never
              logged), env (telemetry environment), job_counts, job_trace (None, or a list to fill), cuts_fired, t_utc
              (int epoch s, float when not whole), uptime_s, link_up, bus_idle
    clock     advance(seconds) raw: uptime and UTC move together and NOTHING runs; advance_to(utc_s) live run_for up to
              utc_s (the replay world protocol; continues across a power cut); run_for(seconds, *, wd_order=('fp',
              'dump'), telemetry=True, config=True) the scheduler (below)
    boot      boot(nvs=None, nvs_fault=None) (first boot only); reboot(down_s=5.0, nvs_fault=None, keep_prefs=True);
              reboot_from(capture, down_s=5.0, nvs_fault=None, keep_prefs=True); arm_power_cut(predicate=None, *,
              kind=None, key=None, addr=None, state=None, nth=1, down_s=5.0, nvs_fault=None, keep_prefs=True);
              capture_points(fn) -> [capture after EVERY fw event of fn(world)]
    faults    nvs_policy(tag_or_pred, state_pred=None, mode='not_landed', times=1) (a not_landed / false_negative /
              false_positive commit on a key never stored earlier in this run raises LabHarnessError when it fires,
              and so do boot faults read_error / wrong_size on such a key: the NVS USED-KEY RULE in MODEL
              ASSUMPTIONS); nvs_stored_earlier(tag) -> bool (that rule, read-only); modbus_policy(None | fn(kind, addr,
              count) -> outcome or None | table {'write:256' | 'read:244x12' | 'read:244' | 'write:*' | 'read:*' | '*':
              [outcome, ...] consumed per op | outcome for every op}; the MOST SPECIFIC key present decides, an exhausted
              list then yields 'ok' - never a less specific key's outcome); set_link(up, *, read_outcome='no_response',
              write_outcome='timeout_lost'); set_bus_idle(idle); set_register(addr, value, actor='owner' | 'inverter');
              rtc_lock_windows([(utc_a, utc_b), ...]) (epoch s or 'YYYY-MM-DDTHH:MM:SSZ')
    env       telemetry(*, poll=True, soc=, batt_v=, batt_w=, grid_w=, pv_w=, house_w=, inverter_w=, grid_connected=);
              config_poll()
    actions   fp_start(power_w=None, minutes=None, arm=True); fp_end(); dump_start(power_w=None, stop_soc=None,
              minutes=None, arm=True); dump_end(); dump_force_restore(arm=True); dump_accept(arm=True);
              fp_operator(action='FORCE_RESTORE_ORIGINAL' | 'ACCEPT_CURRENT_STATE', arm=True, evidence_id=None,
              phrase=None); manual_slot_apply(slot, start_hhmm=None, end_hhmm=None, power_w=None, soc=None,
              charge_source=None, mode=None, arm=True); r244_apply(target='Allow Export' | 'Essentials' | 'Zero Export',
              arm=True) (the real Load button, the staged target select, the arm, the real Apply button); owner_set_number(
              eid, value) (act.set_number: set_number() as a logged action - what HA's number.set_value does). Each is one
              logged world action: never nested, and the power-cut boundary. Building blocks (not actions): set_number(eid,
              value), set_switch(eid, on), set_select(eid, option), press(button_id).
    faults+   inject_global(name, value): WHITE-BOX RAM fault injection (logged fault.ram {name, type, value, old}; the
              value must fit the global's C type exactly - bool / in-range int / finite float / str; arrays raise
              LabUnsupported); a lab fault, never firmware behaviour, and not an INV-RESTORE-BOUND fault explanation.
    observers status(dom), status_history(dom), ha_view() (HA_VIEW template sensors through their REAL lambdas),
              nvs_marker(dom) -> CLEAR | RESTORE_REQUIRED | PENDING_CLEAR | ABSENT | MALFORMED, corrupt(dom),
              bank_view(addrs) -> {str(addr): value}, writes() (every write across boots: boot, t_utc, seq, addr, vals,
              outcome, landed, dom), globals_view(names) (NaN / inf as strings), obligations(), text_state(eid) (any
              firmware text_sensor), quiet_state() -> {booting, locked, diff, visible (RAM rule), nvs, silent} (read-only),
              invariants(names=None, *, boot_from=None, tags=None, untagged=False, form='list' | 'count' | 'summary',
              **checker params) = filter_violations(check_invariants(log, names, world=self, ...), log, ...)
  filter_violations(violations, events, *, boot_from=None, tags=None, untagged=False, form='list')   boot_from keeps the
      violations whose event belongs to boot >= boot_from; tags keeps those carrying every listed tag; untagged those with
      none; form 'count' -> int, 'summary' -> [{inv, tags, boot}] in seq order (seq-free: robust to event renumbering)
  invariant checkers  (events: an EventLog or a list of event dicts; each returns [{inv, seq, detail, tags}])
      check_write_surface (INV-WS: every write inside WRITE_SURFACE, uint16 values); check_one_lease (INV-ONE-LEASE:
      never FP and Dump both active_persisted); check_no_second_restorer (INV-NO-2ND-RESTORER: no domain writes 256-261
      while the OTHER domain holds a durable RESTORE_REQUIRED marker; the writer is recorded; tag N17 when the holder is
      corrupt-locked); check_no_resume (INV-NO-RESUME: after a reboot no lease runs - active and no restore request -
      without a new START); check_lockout_quiet (INV-LOCKOUT-QUIET: no write to a corrupt-locked domain's registers
      except the SG-02 literal 244 = 2); check_no_silent_override (INV-NO-SILENT-OVERRIDE, level-based: at every STEADY
      point - a fw.quiet outside a boot, each boot's settle point after the FULL on_boot, the end of the slice (with a
      world: pre-filled from world.log before a slice, and world.quiet_state() when the slice reaches the end of the log)
      - owned registers that differ from ORIGINAL need an obligation the firmware's RAM shows: a valid snapshot mirror
      or a corrupt / UNKNOWN lockout (fp / dump / r244); a stored NVS marker the RAM ignores is NOT visible; never
      evaluated inside a boot; one violation per episode per boot; tag PLATFORM-ABSENT after an injected false ABSENT /
      erase; full rules in its docstring); check_boot_mirror (INV-BOOT-MIRROR: at every fw.booted a STORED marker
      RESTORE_REQUIRED / PENDING_CLEAR must be reflected by the domain's RAM snapshot_valid or a corrupt / UNKNOWN
      lockout, a MALFORMED one by the lockout - BOOT_MIRROR_RULE, from the firmware's on_boot marker blocks; runtime
      ghosts are not judged); check_restore_bound
      (INV-RESTORE-BOUND, bound_s=60, wd_s=None: a due period opens at the first fw.obl / fw.booted showing the
      domain's restore due and is DISCARDED when the snapshot is still valid but no longer due (a START that completed
      after its own mid-transaction due instant); the restore must complete - snapshot cleared, marker CLEAR / ABSENT -
      within bound_s of the opening unless, inside the due period, a lockout (corrupt / operator needed) is seen, an
      injected fault (fault.modbus, fault.nvs_commit, fault.nvs_boot, fw.power_off, cut.fired) occurs, the link is down
      or the bus busy, or a lock other than the domain's own transaction (manual write, RTC correction, the other
      domain's or reg244's transaction) is held continuously for at least wd_s (the domain's watchdog period from the
      firmware when a world is given, else 15 s) - so the 0 ms locks of a START or of the completing restore itself never
      explain; a period whose RAM snapshot cleared while the marker is still set stays open).
      INVARIANTS {id: checker} (default set: all eight, INV-BOOT-MIRROR last); check_invariants(events, names=None,
      world=None, **params).
  replay      tier 'firmware' is registered with _lab_trace at import: make_world(*, utc_start, seed, **world kwargs)
              (bank keys may be strings, dump_limits a list), ACTIONS (the actions above plus run_for, advance, reboot,
              arm_power_cut, nvs_policy(tag, state, mode, times), modbus_policy(table), set_link, set_bus_idle,
              set_register, telemetry, config_poll, rtc_lock_windows(windows), set_number(entity, value) ->
              owner_set_number, inject_global(name, value), r244_apply(target, arm)), OBSERVERS (status, status_history,
              ha_view, nvs_marker, corrupt, bank(addrs), writes, globals(names), obligations, invariants(names, boot_from,
              tags, untagged, form, checker params), t_utc, boot_no, text_state(entity), quiet_state). The new actions
              log events only when a document uses them: existing documents replay with identical digests.

SCHEDULER (run_for)
  Jobs are the firmware's own `interval:` entries, found by CONTENT MARKERS (INTERVAL_SPECS): every interval must match
  exactly one marker and every marker exactly one interval, else LabHarnessError (never a guess by index). An executed job
  runs the interval's real `then` tree at its declared period, first at its declared startup_delay (else one period) after
  power-on, plus phase_ms. Jobs due on the same millisecond run in firmware order, except the FP / Dump watchdog pair
  (same period, same 15 s startup delay), whose order is wd_order. The first NTP sync runs the real `time: on_time_sync`
  lambda at uptime ntp_after_s, before any job of that instant. RTC lock window edges are wake-up points.
  telemetry=False / config=False suppress the telemetry job / the config and owed-config jobs (their slots pass).
  A slot missed by a raw advance() runs once at the next instant (no catch-up burst; INFERRED ESPHome behaviour).
  Two ESPHome framework jobs (PREF_JOBS, MODEL, see Preferences below) run after the firmware jobs of their instant:
  'pref_poll' (every RestoringGlobalsComponent's own 1000 ms poll) then 'pref_sync' (global_preferences->sync() every
  flash_write_interval, parsed from the firmware's `preferences:`); job_counts / job_trace record them too.

EVENT LOG (src 'fw' events carry up_ms = uptime ms and boot = boot_no; src 'lab' events too, once booted)
  fw.boot {boot, reason, nvs_fault, keys} / fw.booted {boot, obl} / fw.power_off / fw.restart / fw.ntp_sync;
  fw.commit {key, rec, landed}, fw.load {key, ok}, fw.write {addr, vals, outcome, landed, scripts, dom, nvs, ram},
  fw.read {addr, count, outcome}; fw.status {dom, text} (on change); fw.start {dom, script} (every START script run);
  fw.obl (obligations(), on change); fw.quiet {diff, visible} (on change, only while no transaction lock is held; the
  record keeps its V0 form - `visible` also lists stored markers as 'nvs.<dom>' - for corpus digest stability, and
  INV-NO-SILENT-OVERRIDE reads only its RAM part); act.<action> {args} (act.set_number {entity, value}, act.r244_apply
  {target, arm}); fault.ram {name, type, value, old} (inject_global); fault.modbus / fault.modbus_policy /
  fault.nvs_commit / fault.nvs_policy / fault.nvs_boot;
  env.link / env.bus / env.register / env.telemetry / env.rtc_windows / env.rtc_lock; cut.armed / cut.fired.

SYNTHETIC SITE (module constant SITE; NONE of these are site values): ORIGINAL 244 = 2; 256..261 = 8000, 8000, 7000, 8000,
  8000, 5000; 230 = 120 A; 232 = 0; 250..255 = 0, 400, 800, 1300, 1800, 2100 (HHMM); 268..273 = 20; 274..279 = 1, 0, 0, 0,
  0, 0 (slot 1 grid charge 00:00-04:00 only); battery 52 V; SOC 70 %; battery temperature register 1250 (25.0 C); Dump
  environment grid CT -1000 W with battery 1050 W; Dump limits ceiling 8000 W / maximum export 8000 W. Every register
  range a poll or script reads (59-116, 150-196, 200-293, 330) is seeded, 0 unless listed.

MODEL ASSUMPTIONS (lab choices, not firmware behaviour)
  - Entity initial states: switch by restore_mode (ALWAYS_OFF -> False, ALWAYS_ON -> True, RESTORE_DEFAULT_ON / _OFF ->
    the last state from flash, True / False on a first boot, after erase_all or with keep_prefs=False; any other mode
    raises LabUnsupported); binary_sensor False (ESPHome BinarySensor default); sensor NaN; text_sensor ''; number its
    substituted initial_value (restore_value numbers keep their last value across a reboot; the two template numbers with
    a lambda stay NaN); select its initial_option, else its first option (no select declares restore_value). Anchors:
    'id: free_power_write_enable' :5864 / 'id: dump_write_enable' :5892 (ALWAYS_OFF), 'id: configuration_polling' :5837
    (RESTORE_DEFAULT_ON), 'id: dump_export_power' :5340 (restore_value true, initial_value 1000).
  - set_number() refuses a value outside the number's [min_value, max_value] loudly (ESPHome would log and ignore it) and
    runs a number's set_action; set_switch() runs turn_on_action / turn_off_action before the optimistic publish (ESPHome
    TemplateSwitch order). A world action publishes the staged values the way Home Assistant's service calls would.
  - Clock: _fbd1_harness.WallClock / EspTime (:186 / :161; Europe/London from the UTC epoch, hand-coded DST, firmware
    'timezone: Europe/London' :1692) is id(ntp_time); uptime and UTC move together. Power-on is uptime 0, on_boot runs at
    boot_ms, interval timers are anchored at uptime 0 (ESPHome's interval offset is not modelled; INFERRED). After a cut
    the next on_boot is at UTC(cut) + down_s + boot_ms. Only the first NTP sync is modelled.
  - Scripts and Modbus are synchronous (ds.Sim; _dump_sim.py:1513 waits are no-ops, :1542 mode single): a START or a
    restore takes 0 ms; script.is_running() is True only for scripts on the synchronous call stack.
  - Power cut (arm_power_cut / capture_points): the matching event's effect has landed (state captured just after it),
    the running action is ABORTED there - the remainder never happens, so no phantom event is logged - and the world
    reboots from the capture (nvs, bank, and what reached flash: pref_flushed and the flushed restore numbers /
    switches). A firmware restart (button.press of the `restart` platform button 'ecco_restart_internal') is a graceful
    cut: every restoring global stores a changed value and the preferences are synced first (ESPHome's safe reboot runs
    the on_shutdown hooks; INFERRED).
  - Polls: the real interval conditions and poll scripts run (real skip conditions, real Modbus reads through the link and
    fault policies, real failure handlers). MODEL_HANDLERS replace the on_response lambdas that cannot run: 59x58
    ('start_address: 59' :16140, switch fall-through) only publishes display sensors that no lambda reads -> no-op;
    150x47 (:16299) is the REAL decode with every 'static_cast<int16_t>(values[k])' (28; e.g. :16332) rewritten into the
    transpiler's int32 cast arithmetic, an exact-count rewrite (the transpiler compiles static_cast into a run-time
    KeyError); Block A 200x41 (:16457) and Block B 241x53 (:16612) run their own statements, extracted verbatim and
    anchored ('id(configuration_block1_ok) = true;' :16462, the manual_cfg_reg*_raw cache lines, 'id(cfg_block_b_seq)++;'
    :16810 and the stamps after it, configuration_online). Block B also caches 268-273 (the real lambda does).
  - Telemetry image: registers 150-196 are encoded from world.env at every telemetry slot (172 grid CT, 175 inverter, 178
    load, 183 battery V x 100, 184 SOC %, 186 PV, 190 battery power, 194 grid connected); noise=True alternates the CT by 1
    W (pattern from registry/tests/test_dump_safety_fcp2.py:126-131 meter()) and battery power by +-1 W, because the
    firmware's frozen-telemetry detectors end a lease on exact repeats (VERIFIED by the self-test). No inverter physics:
    export, SOC drift and PV change only when a scenario calls telemetry().
  - Link down: reads 'no_response', writes 'timeout_lost' (configurable); the polls then fail through their real handlers,
    so telemetry_online / configuration_online / freshness follow the link.
  - RTC lock windows: correction_in_progress is True inside each [utc_a, utc_b) window and False outside (written at the
    install, at every edge and after every boot); the RTC correction itself is not executed.
  - NVS: commit policies wrap sim.D.commit_record per instance (precedent test_dump_to_grid_behaviour.py:515-529): landed
    (normal), not_landed (nothing stored, False), false_negative (stored, False), false_positive (nothing stored, True, no
    preference flush); policies apply in order, `times` each. Boot faults: ('absent', tag) deletes a stored record (false
    ABSENT), ('read_error', tag) / ('read_error_all',) fail loads for that whole boot session, ('wrong_size', tag) stores a
    wrong-size blob, ('erase_all',) clears NVS and every preference.
  - NVS USED-KEY RULE (V0.1, brief B5 change 1; audit 2026-10-19 r1 section 5.3): an injected NVS fault needs a key that
    was STORED EARLIER IN THIS RUN. Definition (FirmwareWorld.nvs_stored_earlier): the world's current NVS holds a record
    under the tag (a seeded boot image, a record kept across boots or carried in by a capture / reboot_from), OR this
    world's EventLog holds a landed fw.commit of the tag after the last ('erase_all',) boot fault, across boots (a
    false_negative commit is landed: its record is stored). ('erase_all',) un-stores every key; a false ABSENT
    (('absent', tag)) does not (it models a platform misreporting a record that was stored). Enforced:
      * nvs_policy modes not_landed / false_negative / false_positive are checked WHEN THE FAULT FIRES (at the faulting
        commit, before it is logged or consumed), not when the policy is armed: the physical precondition - the only
        device route the audit leaves for a false negative on a lease marker is ESP-IDF ESP_ERR_NVS_REMOVE_FAILED
        (ESP-IDF semantics REPORTED), which needs an EARLIER VERSION of the key - must hold when the faulting commit
        happens, so a policy armed before the first store that fires after it is allowed. not_landed / false_positive
        follow the same rule by the brief's choice (B5 change 1), not by a verified physical impossibility: a not_landed
        commit (an honest failed write) needs no earlier version. Mode 'landed' is never refused. A refusal is a
        LabHarnessError (never LabUnsupported, which some suites record as an UNSUPPORTED point): the scenario fails
        loudly and needs a completed-lease prelude for the injected domain (a lease whose verified restore left the
        marker CLEAR).
      * boot faults ('read_error', tag) and ('wrong_size', tag) are refused at the boot on a never-stored tag (HL-6: with
        nothing stored _dump_sim.load_record_status still reports READ_ERROR; a wrong-size blob would create a record
        from nothing); ('absent', tag) keeps its stricter rule (a record must be present now).
    Limit: the EventLog part counts every landed commit this world logged; a reboot_from() of an EARLIER capture of the
    same world (none in the suites at writing) would still count a store from the abandoned branch.
    Not modelled (documented, not enforced): false_negative is ONE ESP-IDF fault cell ("new copy stored and read at the
    next boot, store healthy"; ESP-IDF 5.5.5 semantics after REMOVE_FAILED REPORTED, not verified); a per-key read_error
    heals at the next plain boot (optimistic for a data-CRC cause); read_error_all keeps the data (in ESPHome only after
    an attempted erase).
  - Preferences (ESPHome flash: only what was flushed survives a power cut; ds.Sim's pref_update / pref_sync are reused):
    a restore_value global is queued by an explicit `->update()` or by the 'pref_poll' job, every RestoringGlobalsComponent
    polling its value every 1000 ms (_GLOBALS_POLL_MS; ESPHome framework constant, stated by the firmware: "ESPHome's
    restore_value mechanism (whose 1000ms poll + independent" :2172); a restore_value number is queued by its control
    path (set_number: TemplateNumber::control saves; a lambda publish_state does not), a restoring switch by every
    publish_state (Switch::publish_state saves; turn_on / turn_off of a restoring switch raises LabUnsupported - no
    firmware lambda uses it). The queue reaches flash at every global_preferences->sync(): the 'pref_sync' job every
    flash_write_interval (parsed from `preferences:`, 'flash_write_interval: 1s' :1687; a firmware without it raises
    LabUnsupported), the sync inside commit_record, an explicit sync, and a graceful restart. Both jobs are anchored at
    power-on like the firmware intervals (phase INFERRED), so a value changed inside an action reaches flash within
    poll + flash_write_interval; a cut before that keeps the previously flushed value. advance() is raw: the jobs do not
    run. A first boot treats the initial values plus the configured Dump limits as already in flash.
  - Writer attribution: the domain of the innermost running script (script_domain).
  - INV-NO-SILENT-OVERRIDE ORIGINAL: landed writes of OWNER_DOMAINS (the owner's manual TOU / register 244 applies),
    set_register(actor='owner') and a SUCCESSFUL operator Accept update it; set_register(actor='inverter') marks the
    register foreign (excluded until ECCO writes it again). HL-1 rule (V0.1 root fix, accept_adoption): an Accept
    (dump_accept, fp_operator ACCEPT_CURRENT_STATE) adopts the live bank for DOMAIN_REGS[dom] only when the last status
    text it published is a firmware SUCCESS text (ACCEPT_SUCCESS_TEXTS, from the Accept scripts), the domain held an
    obligation before it (RAM snapshot valid or a stored marker other than CLEAR / ABSENT) and it cleared it (stored
    marker CLEAR / ABSENT, snapshot no longer valid), and never for a register another domain holds after it (snapshot,
    lockout, transaction, stored marker other than CLEAR / ABSENT, or an active lease); a refused, failed or no-op Accept
    adopts nothing, and an FP Accept whose durable clear is pending (:13649) adopts nothing (the later clear-only
    completion is not an Accept).

NOT MODELLED (source anchors)
  - NOT_EXECUTED intervals: [4] 60 s clock read (:24516, its read_inverter_clock 22x3 on_response needs '::'), [8] 1 s RTC
    tick (:24571, ecco_rtc::), [10] 10 s FB housekeeping (:24742, 'ecco_fbcap::breaker_fired('), [11] 1 s supervision
    shadow (:24872, static_assert). NOT_EXECUTED_BOOT: on_boot items [1] (:1293) and [4] (:1401) are static_assert
    blocks, [3] (:1323, 'ecco_fbdurable::EspNvs nvs;') the FB durable boot read.
  - ESPHome scheduler interleaving, wait_until / delay durations, script modes other than single, Modbus latency and CRC
    errors, a torn NVS record, a preference flush cut short part-way (ds.Sim's pref_cut_after: refused while number /
    switch saves are queued), ESPHome's random interval offsets (the preference jobs' phase), SNTP re-syncs, API
    connectivity and its reboot timeout, safe mode, inverter physics, the FB-B3 raw cache globals.

SOURCE ANCHORS (SOURCE_ANCHORS; test_lab_selftest_firmware re-counts each, exactly once; line at writing)
  firmware/ecco_clock_dongle_stage3_4_free_power.yaml
    :472   'id(ntp_synced_sensor).publish_state(false);'                     (on_boot item 0, the main lambda)
    :24133 'if (id(free_power_restore_requested)) return true;'              (the FP watchdog's content marker)
    :864   'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");'
    :1212  'id(free_power_status).publish_state("ACTIVE - reboot recovery pending");'      (S3)
    :9936  'else if (!armed) id(free_power_status).publish_state("REJECTED - arm Free Power Write Enable first");'
    :18920 'else if (!armed) id(dump_status).publish_state("REJECTED - arm Dump to Grid Write Enable first");'
    :16810 'id(cfg_block_b_seq)++;'   :16462 'id(configuration_block1_ok) = true;'
    :2172  "ESPHome's restore_value mechanism (whose 1000ms poll + independent"   (_GLOBALS_POLL_MS)
    :565   "restore_free_power_snapshot's clear-only branch handles"   :1078 'Free Power<->Dump dual durable-obligation
           dead-end (256-261).'   :801 the Dump marker block 'uint8_t state = have_marker ? ...; id(dump_marker_state) =
           state;'   (BOOT_MIRROR_RULE: PENDING_CLEAR -> snapshot_valid, the PR41 dual lockout, the Dump RR branch)
    :13644 / :13649 / :20936 the ACCEPT_SUCCESS_TEXTS; :20942 'std::string("ACCEPTED CURRENT STATE - ") +
           id(dump_accept_residue_note) +' and :20943 the residue form's suffix (the HL-1 rule)
  registry/tests/_dump_sim.py
    :1318  'self.now_ms = 1_000_000'  (the default uptime this lab replaces with boot_ms)
    :1568  'if outcome in ("ok", "no_response_landed", "timeout_landed"):'  (LANDED_OUTCOMES)
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _dump_sim as ds  # noqa: E402
import _fbd1_harness as F  # noqa: E402  (WallClock / EspTime only)
import _sg01_recovery_harness as H  # noqa: E402  (script ids and review() only)
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402

FW_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
FW_PATH = ROOT / FW_REL
TIER = "firmware"


class LabHarnessError(Exception):
    """Harness misuse or an environment the lab refuses to guess (fail loud)."""


class LabUnsupported(LabHarnessError):
    """A firmware construct or configuration this lab cannot represent."""


class _PowerCut(BaseException):
    """Raised from the event hook to abort the running action at a power cut (BaseException: nothing may swallow it)."""

    def __init__(self, capture: dict, opts: dict):
        super().__init__("power cut")
        self.capture, self.opts = capture, opts


# ---------------------------------------------------------------------------------------------------------------------------
# vocabularies and the synthetic site
# ---------------------------------------------------------------------------------------------------------------------------
WRITE_OUTCOMES = ("ok", "ack_not_applied", "error", "not_sent", "no_response_landed", "no_response_lost", "timeout_landed",
                  "timeout_lost", "custom_response")
READ_OUTCOMES = ("ok", "error", "not_sent", "no_response", "custom_response", "timeout")
LANDED_OUTCOMES = ("ok", "no_response_landed", "timeout_landed")  # _dump_sim.py:1568
WRITE_SURFACE = frozenset({22, 23, 24, 230, 232, 244, *range(250, 262), *range(268, 280)})
OWNED = tuple(sorted(WRITE_SURFACE - {22, 23, 24}))
TOU_POWER = frozenset(range(256, 262))
DOMAIN_REGS = {"fp": frozenset({230, 232, *range(256, 262), *range(268, 280)}), "dump": frozenset({244, *range(256, 262)}),
               "r244": frozenset({244})}
NVS_MODES = ("landed", "not_landed", "false_negative", "false_positive")
NVS_BOOT_FAULTS = ("absent", "read_error", "read_error_all", "erase_all", "wrong_size")
# the NVS USED-KEY RULE (module docstring; brief B5 change 1): the commit modes and per-key boot faults refused on a key
# never stored earlier in this run
NVS_USED_KEY_MODES = ("not_landed", "false_negative", "false_positive")
NVS_USED_KEY_BOOT_FAULTS = ("read_error", "wrong_size")
NVS_STORED_EARLIER_RULE = ("stored earlier in this run = a record under the key in the world's NVS now, or a landed "
                           "fw.commit of the key in this world's EventLog after the last ('erase_all',) boot fault")
NVS_USED_KEY_SOURCE = "audit 2026-10-19-assurance-lab-independent-audit-r1 section 5.3; V0.1 brief section B5 change 1"
_D = ds.Durable
TAGS = {"fp.valid": _D.FREE_POWER_VALID_TAG, "fp.data": _D.FREE_POWER_DATA_TAG, "fp.retry": _D.FREE_POWER_RETRY_TAG,
        "fp.journal": _D.FREE_POWER_START_JOURNAL_TAG, "dump.valid": _D.DUMP_TO_GRID_VALID_TAG,
        "dump.data": _D.DUMP_TO_GRID_DATA_TAG, "dump.data_v1": _D.DUMP_TO_GRID_DATA_TAG_V1,
        "dump.retry": _D.DUMP_TO_GRID_RETRY_TAG, "r244.valid": _D.REG244_VALID_TAG, "r244.data": _D.REG244_DATA_TAG}
MARKER_TAGS = {"fp": TAGS["fp.valid"], "dump": TAGS["dump.valid"], "r244": TAGS["r244.valid"]}
MARKER_NAMES = {_D.MARKER_CLEAR: "CLEAR", _D.MARKER_RESTORE_REQUIRED: "RESTORE_REQUIRED",
                _D.MARKER_RESTORE_VERIFIED_PENDING_CLEAR: "PENDING_CLEAR"}
STATUS_IDS = {"fp": "free_power_status", "dump": "dump_status", "dump_end": "dump_last_end_reason",
              "manual": "manual_config_last_result", "r244": "reg244_last_result"}
_STATUS_BY_ID = {v: k for k, v in STATUS_IDS.items()}
OWNER_DOMAINS = ("manual", "r244")   # owner-initiated manual TOU / register 244 applies (and the reg244 owner restore)
START_SCRIPTS = {"start_free_power_override": "fp", "start_dump_to_grid_override": "dump"}
HA_VIEW = {"fp_active": "free_power_active_sensor", "fp_snapshot_valid": "free_power_snapshot_valid_sensor",
           "fp_op": "free_power_operation_in_progress_sensor", "dump_active": "dump_active_sensor",
           "dump_snapshot_valid": "dump_snapshot_valid_sensor", "dump_op": "dump_operation_in_progress_sensor",
           "manual_write_in_progress": "manual_write_in_progress_sensor",
           "fp_start_attempts": "free_power_start_attempts_sensor", "fp_start_successes": "free_power_start_successes_sensor",
           "dump_start_attempts": "dump_start_attempts_sensor", "dump_start_successes": "dump_start_successes_sensor"}
OPERATOR_PHRASES = {"FORCE_RESTORE_ORIGINAL": "FORCE RESTORE ORIGINAL ", "ACCEPT_CURRENT_STATE": "ACCEPT CURRENT STATE "}
# ^ pattern from registry/tests/_sg01_recovery_harness.py:459 (operator_action)
# HL-1 rule (V0.1 root fix): the operator Accept result texts that mean SUCCESS, verbatim from the firmware's Accept scripts
# (SOURCE_ANCHORS re-counts each exactly once; lines at writing):
#   fp    free_power_recovery_accept_current_state_dispatch (:13195), after its Phase C commit landed (:13620-13621):
#         :13644 Phase D landed too (marker CLEAR, snapshot_valid false); :13649 Phase D failed (marker PENDING_CLEAR,
#         snapshot still valid: the clear-only restore branch completes it later). Every other free_power_status text of
#         the Accept path is a refusal ('ACCEPT REFUSED - ' :13378 :13468 :13494 :13504 :13553 :13599 :13656), and the
#         gate refusals of free_power_recovery_accept_current_state (:13045) publish no status at all (they set only
#         free_power_recovery_invalidate_reason), so a stale earlier text is never read as this Accept's result.
#   dump  dump_accept_current_state (:20833), after its CLEAR commit landed ('if (clear_ok) {' :20919): :20936 without a
#         residue note, :20942-20943 with one (std::string("ACCEPTED CURRENT STATE - ") + note + "; export is not
#         enabled; no inverter write performed"). Refusals: 'ACCEPT FAILED - ' :20949, 'REJECTED - ' :20954-20958,
#         'ACCEPT REFUSED - ' :20959.
ACCEPT_SUCCESS_TEXTS = {
    "fp": ("ACCEPT CURRENT STATE SUCCESS - current live configuration accepted, durable recovery marker cleared",
           "ACCEPT CURRENT STATE SUCCESS - accepted; durable recovery-marker clear pending, will retry"),
    "dump": ("ACCEPTED CURRENT STATE - recovery obligation cleared; no inverter write performed",),
}
DUMP_ACCEPT_RESIDUE_FORM = ("ACCEPTED CURRENT STATE - ", "; export is not enabled; no inverter write performed")

_ORIGINAL = {230: 120, 232: 0, 244: 2, 250: 0, 251: 400, 252: 800, 253: 1300, 254: 1800, 255: 2100,
             256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000,
             **{268 + i: 20 for i in range(6)}, 274: 1, **{275 + i: 0 for i in range(5)}}
SITE = {
    "synthetic": True,          # NOT site values: a self-consistent placeholder installation
    "original": dict(_ORIGINAL),
    "soc": 70, "battery_v": 52.0,
    "dump_grid_w": -1000, "dump_battery_w": 1050,   # a Dump lease exporting 1000 W from the battery
    "dump_limits": (8000, 8000),
    "seeded_ranges": ((59, 117), (150, 197), (200, 294), (330, 331)),
    "telemetry_static": {182: 1250},   # battery temperature register: (1250 - 1000) x 0.1 = 25.0 C
}
ENV_DEFAULT = {"soc": SITE["soc"], "batt_v": SITE["battery_v"], "batt_w": 0, "grid_w": 0, "pv_w": 0, "house_w": 0,
               "inverter_w": 0, "grid_connected": True}
_ENV_REG = {"grid_w": 172, "inverter_w": 175, "house_w": 178, "batt_v": 183, "soc": 184, "pv_w": 186, "batt_w": 190,
            "grid_connected": 194}


def site_bank(overrides: dict | None = None) -> dict:
    """The synthetic inverter register image: every seeded range 0, then the ORIGINAL, then `overrides`."""
    bank = {a: 0 for lo, hi in SITE["seeded_ranges"] for a in range(lo, hi)}
    bank.update(SITE["original"])
    bank.update(SITE["telemetry_static"])
    for a, v in (overrides or {}).items():
        bank[_reg(a)] = _u16(v, f"bank[{a}]")
    return bank


def _reg(a) -> int:
    if isinstance(a, str) and a.isdigit():
        a = int(a)
    if isinstance(a, bool) or not isinstance(a, int) or not 0 <= a <= 65535:
        raise LabHarnessError(f"bad register address {a!r}")
    return a


def _u16(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 65535:
        raise LabHarnessError(f"{what}: a register holds an int 0..65535, got {v!r}")
    return v


def _i16(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise LabHarnessError(f"{what}: finite number required, got {v!r}")
    iv = int(round(v))
    if not -32768 <= iv <= 32767:
        raise LabHarnessError(f"{what}: {v!r} does not fit a signed 16-bit register")
    return iv & 0xFFFF


# ---------------------------------------------------------------------------------------------------------------------------
# firmware: load once per text, derived tables found by content markers
# ---------------------------------------------------------------------------------------------------------------------------
# (job, marker text found in the interval's string leaves, executed)
INTERVAL_SPECS = (
    ("census", "id(ecco_lock_since_ms) = millis();", True),
    ("export_trip", "id(dump_export_trip) != 0 && id(dump_active_persisted)", True),
    ("fp_wd", "if (id(free_power_restore_requested)) return true;", True),
    ("dump_wd", "dump_overpower_samples", True),
    ("clock_read", "return !id(correction_in_progress) && !id(manual_write_in_progress);", False),
    ("telemetry", "return id(live_telemetry).state && !id(correction_in_progress) && !id(manual_write_in_progress);", True),
    ("config", "return id(configuration_polling).state && !id(correction_in_progress) && !id(manual_write_in_progress);",
     True),
    ("owed_config", "return id(cfg_poll_owed) > 0 && id(configuration_polling).state &&", True),
    ("rtc", "id(rtc_txn_since_ms)", False),
    ("evidence_expiry", "free_power_recovery_evidence_captured_ms", True),
    ("fb_housekeeping", "ecco_fbcap::breaker_fired(", False),
    ("shadow", "T_suspect + T_start_max must be below T_lost", False),
    ("supervision", "uint8_t prev = id(supervision_state);", True),
    ("manual_tou", "if (!owned && !id(manual_tou_owner_seen)) return;", True),
)
NOT_EXECUTED = {
    "clock_read": "60 s RTC clock read: it presses read_inverter_clock, whose 22x3 on_response (the RTC decision) does "
                  "not transpile ('::' namespace call); RTC belongs to the rtc tier and is replayed here only as lock windows",
    "rtc": "1 s RTC correction tick: ecco_rtc:: calls do not transpile (Unsupported); RTC is replayed only as "
           "correction_in_progress lock windows (MODEL)",
    "fb_housekeeping": "10 s FB housekeeping / leak breaker: ecco_fbcap:: calls do not transpile; FB is out of scope",
    "shadow": "1 s supervision shadow interval: starts with static_assert (Unsupported in the transpiler); observe-only",
}
PARTIAL = {
    "telemetry": "real interval condition + real poll_inverter_telemetry tree, Modbus reads and failure handlers; the "
                 "59x58 on_response lambda does not transpile (switch fall-through) and is a MODEL no-op (display only)",
    "config": "real interval condition + real poll_inverter_configuration / _dispatch trees, Modbus reads and failure "
              "handlers; the Block A 200x41 and Block B 241x53 on_response lambdas do not transpile and are MODEL handlers "
              "built from their own cache / freshness statements",
    "owed_config": "real condition (script.is_running() answered from the synchronous call stack); runs the same poll",
}
BOOT_SPECS = (
    ("main", "// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/", True),
    ("static_supervision", "supervision: stable max gap must be shorter than the SUSPECT threshold", False),
    ("supervision_nonce", "id(supervision_boot_nonce) = random_uint32();", True),
    ("fb_boot_read", "ecco_fbdurable::EspNvs nvs;", False),
    ("static_dump", "Dump ceiling: ecco_dump_controller_max_ceiling_w must be a plain decimal integer (W)", False),
    ("dump_limits", "id(dump_limits_valid) = (why == 0);", True),
)
NOT_EXECUTED_BOOT = {
    "static_supervision": "static_assert block: compile-time checks only, no runtime effect",
    "static_dump": "static_assert block: compile-time checks only, no runtime effect",
    "fb_boot_read": "FB durable boot read (ecco_fbdurable / ecco_fbcap namespaces) does not transpile; FB is out of scope",
}
MODEL_HANDLERS = {
    ("poll_inverter_telemetry", 59, 58): "telemetry block 59-116: inverter state / energy / temperature / fault display "
                                         "publishes only (no lambda reads any of them) -> MODEL no-op",
    ("poll_inverter_telemetry", 150, 47): "telemetry block 150-196: the REAL decode lambda, with every "
                                          "static_cast<int16_t>(values[k]) rewritten into the transpiler's int32 cast "
                                          "arithmetic (the transpiler has no static_cast; a mechanical, exact-count rewrite)",
    ("poll_inverter_configuration_dispatch", 200, 41): "Block A: runs its own 'configuration_block1_ok = true' and register "
                                                       "cache statements; display publishes not modelled",
    ("poll_inverter_configuration_dispatch", 241, 53): "Block B: runs its own register cache, cache-valid, "
                                                       "cfg_block_b freshness and configuration_online statements; display "
                                                       "publishes and the FB-B3 raw cache not modelled",
}
_BLOCK_EXACT = {
    200: ("id(configuration_block1_ok) = true;",),
    241: ("id(manual_config_raw_cache_valid) = id(configuration_block1_ok);", "id(cfg_block_b_seq)++;",
          "id(cfg_block_b_ok_ms) = millis();",
          "id(cfg_block_b_response_dispatch_seq) = id(cfg_block_b_dispatch_seq);",
          "bool ok = id(configuration_block1_ok);", "id(configuration_online).publish_state(ok);"),
}
_BLOCK_CACHE = {200: {232}, 241: {244, *range(250, 262), *range(268, 280)}}
# MODEL: ESPHome's preference machinery as two framework jobs (module docstring, Preferences). The 1000 ms poll of every
# RestoringGlobalsComponent is an ESPHome constant (not configurable in YAML; the firmware states it at SOURCE_ANCHORS
# "whose 1000ms poll"); flash_write_interval is parsed from the firmware's `preferences:` section.
PREF_JOBS = ("pref_poll", "pref_sync")
_GLOBALS_POLL_MS = 1000
_CACHE_RE = re.compile(r"id\(manual_cfg_reg(\d+)_raw\) = values\[(\d+)\];")
_CAST_RE = re.compile(r"static_cast<int16_t>\((values\[\d+\])\)")


def rewrite_static_casts(code: str) -> str:
    """static_cast<int16_t>(values[k]) -> the same signed 16-bit value in the transpiler's int32 cast arithmetic; any
    other static_cast left over raises LabUnsupported (exact-count rewrite, never a silent partial one)."""
    new = _CAST_RE.sub(lambda m: f"((int32_t) {m.group(1)} - ((((int32_t) {m.group(1)}) & 0x8000) ? 65536 : 0))", code)
    if "static_cast" in new:
        raise LabUnsupported("a static_cast form other than static_cast<int16_t>(values[k]) is not rewritten")
    return new


SOURCE_ANCHORS = (
    (FW_REL, "id(ntp_synced_sensor).publish_state(false);"),
    (FW_REL, "if (id(free_power_restore_requested)) return true;"),
    (FW_REL, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");'),
    (FW_REL, 'id(free_power_status).publish_state("ACTIVE - reboot recovery pending");'),
    (FW_REL, 'else if (!armed) id(free_power_status).publish_state("REJECTED - arm Free Power Write Enable first");'),
    (FW_REL, 'else if (!armed) id(dump_status).publish_state("REJECTED - arm Dump to Grid Write Enable first");'),
    (FW_REL, "id(cfg_block_b_seq)++;"),
    (FW_REL, "id(configuration_block1_ok) = true;"),
    (FW_REL, "ESPHome's restore_value mechanism (whose 1000ms poll + independent"),
    (FW_REL, "restore_free_power_snapshot's clear-only branch handles"),            # BOOT_MIRROR_RULE: PENDING_CLEAR
    (FW_REL, "Free Power<->Dump dual durable-obligation dead-end (256-261)."),        # BOOT_MIRROR_RULE: PR41 lockout
    (FW_REL, "uint8_t state = have_marker ? marker.state : (uint8_t) ecco_durable::MARKER_CLEAR;\n"
             "              id(dump_marker_state) = state;"),                       # the Dump marker block (selftest mutant)
    *((FW_REL, t) for t in ACCEPT_SUCCESS_TEXTS["fp"] + ACCEPT_SUCCESS_TEXTS["dump"]),   # HL-1 rule: SUCCESS texts
    (FW_REL, 'std::string("ACCEPTED CURRENT STATE - ") + id(dump_accept_residue_note) +'),   # HL-1: residue form
    (FW_REL, '"' + DUMP_ACCEPT_RESIDUE_FORM[1] + '"'),
    ("registry/tests/_dump_sim.py", "self.now_ms = 1_000_000"),
    ("registry/tests/_dump_sim.py", 'if outcome in ("ok", "no_response_landed", "timeout_landed"):'),
)
_ENTITY_SKIP = {"globals", "substitutions", "esphome", "interval", "api", "wifi", "logger", "ota", "safe_mode", "preferences",
                "esp32", "debug"}
_DUR = re.compile(r"^(\d+)(ms|s|min)$")


def _ms(text) -> int:
    m = _DUR.match(str(text).strip())
    if not m:
        raise LabUnsupported(f"unsupported ESPHome duration {text!r}")
    return int(m.group(1)) * {"ms": 1, "s": 1000, "min": 60000}[m.group(2)]


def _leaves(node) -> str:
    """Every string leaf of a parsed YAML subtree, newline-joined (content-marker matching, independent of yaml.dump)."""
    out: list = []

    def walk(n):
        if isinstance(n, str):
            out.append(str(n))
        elif isinstance(n, dict):
            for k, v in n.items():
                out.append(str(k))
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
        elif n is not None:
            out.append(str(n))
    walk(node)
    return "\n".join(out)


def _classify(items: list, specs: tuple, what: str) -> dict:
    """{spec name: index} - every item matched by exactly one spec, every spec matching exactly one item (fail loud)."""
    texts = [_leaves(x) for x in items]
    found: dict = {}
    for i, t in enumerate(texts):
        hits = [s[0] for s in specs if s[1] in t]
        if len(hits) != 1:
            raise LabHarnessError(f"{what} [{i}] matches {len(hits)} content markers {hits} (need exactly one)")
        found.setdefault(hits[0], []).append(i)
    for s in specs:
        if len(found.get(s[0], [])) != 1:
            raise LabHarnessError(f"{what} marker {s[0]!r} matches {len(found.get(s[0], []))} items (need exactly one)")
    return {k: v[0] for k, v in found.items()}


class _FwInfo:
    """Tables derived once per firmware text (see fw_info)."""

    def __init__(self, fw: dict):
        self.fw = fw
        self.sha = hashlib.sha256(fw["_text"].encode("utf-8")).hexdigest()
        subs = fw["_substitutions"]
        # entity registry: every top-level component list/dict with ids
        self.entities: dict = {}
        for sect, val in fw.items():
            if sect.startswith("_") or sect in _ENTITY_SKIP:
                continue
            nodes = val if isinstance(val, list) else [val] if isinstance(val, dict) else []
            for node in nodes:
                if isinstance(node, dict) and isinstance(node.get("id"), str):
                    if node["id"] in self.entities:
                        raise LabHarnessError(f"duplicate entity id {node['id']!r}")
                    self.entities[node["id"]] = (sect, node)
        self.globals = {g["id"]: g for g in fw["globals"]}
        self.initial = {}
        for g in fw["globals"]:
            raw = g.get("initial_value")
            raw = ds.substitute(raw, subs) if isinstance(raw, str) else raw
            self.initial[g["id"]] = ds.Sim._initial(g["type"], raw)
        self.restore_globals = tuple(g["id"] for g in fw["globals"] if g.get("restore_value"))
        self.restore_numbers = tuple(sorted(e for e, (k, n) in self.entities.items()
                                            if k == "number" and n.get("restore_value")))
        self.restore_switches = tuple(sorted(e for e, (k, n) in self.entities.items() if k == "switch"
                                             and _RESTORE_MODES.get(n.get("restore_mode"), (None, False))[1]))
        pref = fw.get("preferences")
        if not isinstance(pref, dict) or "flash_write_interval" not in pref:
            raise LabUnsupported("the firmware has no 'preferences: flash_write_interval' (the lab never guesses ESPHome's "
                                 "default flush interval)")
        self.flash_write_ms = _ms(pref["flash_write_interval"])
        if self.flash_write_ms <= 0:
            raise LabUnsupported(f"flash_write_interval {pref['flash_write_interval']!r} is not modelled (needs > 0)")
        # intervals and on_boot items by content
        ivs = fw["interval"]
        idx = _classify(ivs, INTERVAL_SPECS, "interval")
        self.jobs = []
        for name, _marker, executed in INTERVAL_SPECS:
            iv = ivs[idx[name]]
            period = _ms(iv["interval"])
            startup = _ms(iv["startup_delay"]) if "startup_delay" in iv else None
            self.jobs.append({"name": name, "index": idx[name], "period_ms": period, "startup_ms": startup,
                              "executed": executed, "then": iv["then"]})
        self.jobs.sort(key=lambda j: j["index"])
        self.job = {j["name"]: j for j in self.jobs}
        boot_items = fw["esphome"]["on_boot"]["then"]
        bidx = _classify(boot_items, BOOT_SPECS, "on_boot item")
        self.boot_items = []
        for name, _marker, executed in BOOT_SPECS:
            item = boot_items[bidx[name]]
            if set(item) != {"lambda"}:
                raise LabUnsupported(f"on_boot item {name!r} is not a lambda: {sorted(item)}")
            self.boot_items.append({"name": name, "index": bidx[name], "executed": executed, "lambda": item["lambda"]})
        self.boot_items.sort(key=lambda b: b["index"])
        # scripts, buttons, api
        self.scripts = {s["id"]: s for s in fw["script"]}
        self.buttons = {b["id"]: b for b in fw["button"] if "id" in b}
        self.api = {a["action"]: a for a in fw["api"]["actions"]}
        # MODEL handlers for the non-transpilable poll on_response lambdas (by content: script + start_address + count)
        self.model_bodies: dict = {}
        self.block_code: dict = {}
        for (sid, addr, count), _why in MODEL_HANDLERS.items():
            bodies = [b for b in _reads(self.scripts[sid]["then"]) if int(b["start_address"]) == addr
                      and int(b["count"]) == count]
            if len(bodies) != 1:
                raise LabHarnessError(f"{sid}: read {addr}x{count} found {len(bodies)}x (need exactly one)")
            self.model_bodies[id(bodies[0])] = addr
            if addr == 150:
                self.block_code[addr] = rewrite_static_casts(bodies[0]["on_response"]["then"][0]["lambda"])
            if addr in _BLOCK_EXACT:
                code = bodies[0]["on_response"]["then"][0]["lambda"]
                stmts = []
                for s in _BLOCK_EXACT[addr]:
                    if code.count(s) != 1:
                        raise LabHarnessError(f"Block {addr} on_response: {s!r} found {code.count(s)}x (need 1)")
                    stmts.append((code.index(s), s))
                regs = set()
                for m in _CACHE_RE.finditer(code):
                    reg, k = int(m.group(1)), int(m.group(2))
                    if k != reg - addr:
                        raise LabHarnessError(f"Block {addr}: manual_cfg_reg{reg}_raw cached from values[{k}]")
                    regs.add(reg)
                    stmts.append((m.start(), m.group(0)))
                if regs != _BLOCK_CACHE[addr]:
                    raise LabHarnessError(f"Block {addr}: cached registers {sorted(regs)} != {sorted(_BLOCK_CACHE[addr])}")
                self.block_code[addr] = "\n".join(s for _p, s in sorted(stmts))
        for key, eid in {**HA_VIEW, **{f"status:{k}": v for k, v in STATUS_IDS.items()}}.items():
            if eid not in self.entities:
                raise LabHarnessError(f"{key}: entity {eid!r} is not in the firmware")
        self.ha_lambdas = {k: self.entities[eid][1]["lambda"] for k, eid in HA_VIEW.items()}


def _reads(actions) -> list:
    out = []
    for a in actions or []:
        (kind, body), = a.items()
        if kind == ds.READ:
            out.append(body)
        elif kind == "if":
            out += _reads(body.get("then")) + _reads(body.get("else"))
    return out


_FW_CACHE: dict = {}
_INFO: dict = {}
_LIVE_TEXT: list = []


def fw_text() -> str:
    if not _LIVE_TEXT:
        _LIVE_TEXT.append(FW_PATH.read_text(encoding="utf-8"))
    return _LIVE_TEXT[0]


def load_fw(text: str | None = None) -> dict:
    """The parsed firmware for `text` (default: the worktree firmware), cached by sha256 of the text."""
    text = fw_text() if text is None else text
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    fw = _FW_CACHE.get(key)
    if fw is None:
        fw = _FW_CACHE[key] = ds.load_firmware_text(text)
    return fw


def fw_info(fw: dict) -> _FwInfo:
    key = hashlib.sha256(fw["_text"].encode("utf-8")).hexdigest()
    info = _INFO.get(key)
    if info is None or info.fw is not fw:
        info = _INFO[key] = _FwInfo(fw)
    return info


# ---------------------------------------------------------------------------------------------------------------------------
# strict entities and the strict simulator
# ---------------------------------------------------------------------------------------------------------------------------
_BOOL_KINDS = ("switch", "binary_sensor")
_RESTORE_MODES = {"ALWAYS_OFF": (False, False), "ALWAYS_ON": (True, False), "RESTORE_DEFAULT_OFF": (False, True),
                  "RESTORE_DEFAULT_ON": (True, True)}


class LabEntity(ds.Entity):
    """A firmware entity of a known kind with an explicit initial state (see MODEL ASSUMPTIONS)."""

    def __init__(self, sim, name: str, kind: str, node: dict, subs: dict):
        self.kind, self.node, self._init = kind, node, True
        super().__init__(sim, name)
        self._init = False
        if kind == "switch":
            mode = node.get("restore_mode")
            if mode not in _RESTORE_MODES:
                raise LabUnsupported(f"switch {name}: restore_mode {mode!r} is not modelled")
            self.state = _RESTORE_MODES[mode][0]
        elif kind == "binary_sensor":
            self.state = False
        elif kind == "text_sensor":
            self.state = ds.CStr("")
        elif kind == "number" and "initial_value" in node:
            self.state = float(ds.substitute(str(node["initial_value"]), subs))
        elif kind == "select":
            opts = node.get("options") or []
            if not opts:
                raise LabUnsupported(f"select {name} has no options")
            self.state = ds.CStr(node.get("initial_option", opts[0]))

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        if self.kind in _BOOL_KINDS and not self._init:
            if isinstance(value, bool):
                pass
            elif isinstance(value, int):
                value = bool(value)  # C++ implicit int -> bool conversion
            else:
                raise LabHarnessError(f"{self.kind} {self.name}: state must be bool, got {value!r} (NaN-truthy guard)")
        self._state = value

    def current_option(self):
        if self.kind != "select":
            raise AttributeError(f"{self.kind} {self.name} has no current_option()")
        return self._state

    def is_running(self):
        if self.kind != "script":
            raise AttributeError(f"{self.kind} {self.name} has no is_running()")
        return self.name in self._sim.running

    def turn_on(self):
        self._restoring_guard("turn_on")
        super().turn_on()

    def turn_off(self):
        self._restoring_guard("turn_off")
        super().turn_off()

    def _restoring_guard(self, what: str) -> None:
        # on the device turn_on/off of a restoring switch publishes and saves its state; ds.Entity only sets it, so the
        # lab's flash model would silently miss the save (no firmware lambda does this today)
        if self.kind == "switch" and _RESTORE_MODES[self.node["restore_mode"]][1]:
            raise LabUnsupported(f"switch {self.name}.{what}(): the save of a restoring switch on this path is not modelled")

    def publish_state(self, value):
        super().publish_state(value)
        hook = self._sim.publish_hook
        if hook is not None:
            hook(self.name, self._state)


class StrictSim(ds.Sim):
    """ds.Sim with the lab's strictness (see the module docstring, StrictSim (a)-(g))."""

    def __init__(self, fw: dict):
        self.info = fw_info(fw)
        self._policy = lambda kind, addr, count: "ok"
        super().__init__(fw, dump_limits="configured")
        clock = self.entities["ntp_time"]
        subs = fw["_substitutions"]
        self.entities = {eid: LabEntity(self, eid, kind, node, subs) for eid, (kind, node) in self.info.entities.items()}
        self.entities["ntp_time"] = clock
        self.publish_hook = None
        self.start_hook = None
        self.restart_hook = None
        self.script_stack: list = []

    # (a) outcome allow-list: ds.Sim calls self.outcome_fn(kind, addr, count)
    @property
    def outcome_fn(self):
        return self._checked_outcome

    @outcome_fn.setter
    def outcome_fn(self, fn):
        if not callable(fn):
            raise LabHarnessError("outcome_fn must be callable")
        self._policy = fn

    def _checked_outcome(self, kind, addr, count):
        outcome = self._policy(kind, addr, count)
        allowed = WRITE_OUTCOMES if kind == "write" else READ_OUTCOMES
        if outcome not in allowed:
            raise LabHarnessError(f"Modbus {kind} {addr}x{count}: outcome {outcome!r} is not in the allow-list {allowed}")
        return outcome

    # (b) sealed registry
    def ent(self, name):
        try:
            return self.entities[name]
        except KeyError:
            raise LabHarnessError(f"unknown entity id {name!r}: the lab's entity registry is sealed") from None

    # (e) no silent 0 for an unseeded register; (f) MODEL handlers
    def _modbus_read(self, body, local):
        addr, count = int(body["start_address"]), int(body["count"])
        missing = [a for a in range(addr, addr + count) if a not in self.bank]
        if missing:
            raise LabHarnessError(f"read {addr}x{count}: registers {missing[:6]} are not seeded in the bank")
        return super()._modbus_read(body, local)

    def _handler(self, body, name, local, values=None, exception_code=None):
        addr = self.info.model_bodies.get(id(body))
        if addr is not None and name == "on_response":
            code = self.info.block_code.get(addr)
            if code is not None:  # MODEL: the block's own statements, verbatim, through the real transpiler
                self.run_lambda(code, {"values": ds.Vec(values)}, params=("values",))
            return None
        return super()._handler(body, name, local, values, exception_code)

    # (h) button.press from an action list: ds.Sim only records it; the device runs a template button's on_press and a
    # `restart` platform button reboots the MCU
    def run_actions(self, actions, local=None):
        for action in actions or []:
            (kind, body), = action.items()
            if kind != "button.press":
                super().run_actions([action], local)
                continue
            bid = body.get("id") if isinstance(body, dict) else str(body)
            kind_, node = self.info.entities.get(bid, (None, {}))
            self.pressed.append(bid)
            if kind_ == "button" and node.get("platform") == "restart":
                if self.restart_hook is None:
                    raise LabUnsupported(f"button.press {bid}: a restart needs a FirmwareWorld (restart_hook)")
                self.restart_hook(bid)
            elif kind_ == "button" and node.get("platform") == "template" and "on_press" in node:
                self.run_actions(node["on_press"], None)
            else:
                raise LabUnsupported(f"button.press {bid}: platform {node.get('platform')!r} is not modelled")

    # (g) call stack, START callback
    def execute(self, script_id, params=None):
        dom = START_SCRIPTS.get(script_id)
        if dom is not None and self.start_hook is not None:
            self.start_hook(dom, script_id)
        dropped = script_id in self.running
        if not dropped:
            self.script_stack.append(script_id)
        try:
            super().execute(script_id, params)
        finally:
            if not dropped:
                self.script_stack.pop()


def script_domain(script_id: str | None) -> str:
    if not script_id:
        return "interval"
    if script_id.startswith(("start_free_power", "restore_free_power", "free_power_recovery")):
        return "fp"
    if script_id.startswith(("start_dump", "restore_dump", "dump_", "request_dump_end")):
        return "dump"
    if script_id.startswith("apply_manual_slot"):
        return "manual"
    if script_id in ("apply_reg244_settings", "restore_reg244_snapshot"):
        return "r244"
    if script_id == "write_inverter_rtc":
        return "rtc"
    return "other"


def _rec_dict(rec) -> dict:
    return {"kind": rec._kind, **{f: getattr(rec, f) for f in ds._RECORD_FIELDS[rec._kind]}}


def _jsonable(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else repr(v)
    if isinstance(v, str):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    raise LabHarnessError(f"value {v!r} is not representable in an observation")


def _marker_name(rec) -> str:
    if rec is None:
        return "ABSENT"
    if rec._kind != "ValidMarker" or rec.magic != _D.VALID_MARKER_MAGIC or rec.state not in MARKER_NAMES:
        return "MALFORMED"
    return MARKER_NAMES[rec.state]


def _tag(name) -> str:
    if name in TAGS:
        return TAGS[name]
    if name in TAGS.values():
        return name
    raise LabHarnessError(f"unknown NVS tag {name!r} (aliases: {sorted(TAGS)})")


def _never_stored_error(fault: str, key: str) -> LabHarnessError:
    """The NVS USED-KEY RULE refusal (module docstring): `fault` is an nvs_policy mode (NVS_USED_KEY_MODES) or a boot
    fault kind (NVS_USED_KEY_BOOT_FAULTS), `key` the durable tag. A LabHarnessError (never LabUnsupported): fail loud."""
    alias = next((a for a, t in TAGS.items() if t == key), None)
    name = f"{key} ({alias})" if alias else key
    head = (f"{fault!r} on NVS key {name}: refused - the key was never stored earlier in this run "
            f"({NVS_STORED_EARLIER_RULE}). ")
    if fault == "false_negative":
        why = ("Physical precondition: the device route of a false negative (record stored, commit reported failed) is "
               "ESP-IDF ESP_ERR_NVS_REMOVE_FAILED - the new copy is written and erasing the earlier version fails - so it "
               "needs an earlier stored version of the key (the other route, an unrelated pending key failing the same "
               "sync(), cannot reach a Phase-B marker commit: the data commit's sync() in the same lambda clears ESPHome "
               "2026.8.2's queue, preferences.cpp:248). ")
    elif fault in NVS_USED_KEY_MODES:
        why = ("The V0.1 fault model injects every commit fault only where the precondition of the one device route the "
               "audit leaves for a marker false negative holds: ESP-IDF ESP_ERR_NVS_REMOVE_FAILED needs an earlier stored "
               "version of the key. ")
    elif fault == "read_error":
        why = ("Physical precondition: a per-key read error needs a stored record to fail reading; with nothing stored "
               "_dump_sim.load_record_status still reports READ_ERROR (HL-6), a state no device reaches. ")
    else:
        why = ("Physical precondition: a wrong-size record needs an earlier stored version of the key; on a never-stored "
               "key the blob would be a record created from nothing (the HL-6 sibling, a MALFORMED lockout no device "
               "reaches). ")
    return LabHarnessError(head + why + f"Source: {NVS_USED_KEY_SOURCE}. Give the scenario a completed-lease prelude for "
                           "that domain (a lease whose verified restore left the marker CLEAR) before the fault.")


def _is_locked(obl: dict) -> bool:
    """A transaction lock is held (an FP / Dump / reg244 operation or a manual write): no steady point."""
    return bool(obl["fp"]["op"] or obl["dump"]["op"] or obl["r244"]["op"] or obl["mw"])


def _ram_visible(obl: dict) -> list:
    """The obligations the firmware's RAM shows (what every firmware gate reads): '<dom>.snap' for a valid snapshot mirror,
    '<dom>.corrupt' for a corrupt / UNKNOWN lockout, for fp / dump / r244. A stored NVS marker alone is not listed."""
    return sorted([f"{d}.snap" for d in ("fp", "dump", "r244") if obl[d]["snap"]]
                  + [f"{d}.corrupt" for d in ("fp", "dump", "r244") if obl[d]["corrupt"]])


def accept_succeeded(dom: str, text) -> bool:
    """True when `text` is one of the firmware's operator Accept SUCCESS texts for dom 'fp' / 'dump' (ACCEPT_SUCCESS_TEXTS;
    the Dump text with a residue note by its fixed prefix and suffix around a non-empty note)."""
    if dom not in ACCEPT_SUCCESS_TEXTS:
        raise LabHarnessError(f"accept_succeeded: dom must be 'fp' or 'dump', got {dom!r}")
    if not isinstance(text, str):
        return False
    if text in ACCEPT_SUCCESS_TEXTS[dom]:
        return True
    pre, suf = DUMP_ACCEPT_RESIDUE_FORM
    return dom == "dump" and text.startswith(pre) and text.endswith(suf) and len(text) > len(pre) + len(suf)


def _obl_holds(obl: dict, dom: str) -> bool:
    """`dom` (fp / dump / r244) holds its registers in the obligation snapshot `obl` (the fw.obl shape): a valid RAM
    snapshot, a corrupt / UNKNOWN lockout, a transaction in progress, a stored marker other than CLEAR / ABSENT, or (fp /
    dump) an active lease."""
    o = obl[dom]
    return bool(o["snap"] or o["corrupt"] or o["op"] or o.get("act") or obl["nvs"][dom] not in ("CLEAR", "ABSENT"))


def accept_adoption(dom: str, pre: dict, post: dict, texts) -> dict:
    """The HL-1 rule (pure): which registers the lab ORIGINAL adopts from the live bank after an operator Accept of dom
    'fp' / 'dump'. pre / post: obligations() just before the Accept and just after it; texts: the domain's status texts
    the Accept published, in order. Adoption needs ALL of: (1) success - the last published text is a SUCCESS text
    (accept_succeeded); (2) held - dom held an obligation before the Accept (a valid RAM snapshot or a stored marker
    other than CLEAR / ABSENT); (3) cleared - after it the stored marker is CLEAR / ABSENT and the RAM snapshot is no
    longer valid (an FP Accept whose durable clear is still pending adopts nothing yet). The registers of DOMAIN_REGS[dom]
    that another domain holds after the Accept (_obl_holds: fp / dump / r244) are never adopted.
    Returns {result, success, held, cleared, adopt: [addr], kept: {other dom: [addr]}, reason}."""
    if dom not in ACCEPT_SUCCESS_TEXTS:
        raise LabHarnessError(f"accept_adoption: dom must be 'fp' or 'dump', got {dom!r}")
    texts = [str(t) for t in texts]
    last = texts[-1] if texts else None
    success = last is not None and accept_succeeded(dom, last)
    held = bool(pre[dom]["snap"]) or pre["nvs"][dom] not in ("CLEAR", "ABSENT")
    cleared = post["nvs"][dom] in ("CLEAR", "ABSENT") and not post[dom]["snap"]
    out = {"result": last, "success": success, "held": held, "cleared": cleared, "adopt": [], "kept": {}}
    if not success:
        out["reason"] = "no SUCCESS text published by this Accept (refused, failed or nothing published)"
        return out
    if not held:
        out["reason"] = f"{dom} held no obligation before the Accept"
        return out
    if not cleared:
        out["reason"] = f"the Accept did not clear {dom}'s obligation (marker {post['nvs'][dom]}, snapshot " \
                        f"{'valid' if post[dom]['snap'] else 'invalid'})"
        return out
    for other in ("fp", "dump", "r244"):
        shared = DOMAIN_REGS[dom] & DOMAIN_REGS[other] if other != dom else frozenset()
        if shared and _obl_holds(post, other):
            out["kept"][other] = sorted(shared)
    kept = set().union(*out["kept"].values()) if out["kept"] else set()
    out["adopt"] = sorted(DOMAIN_REGS[dom] - kept)
    out["reason"] = "adopted" + (f"; kept registers other domains hold: {out['kept']}" if kept else "")
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# the world
# ---------------------------------------------------------------------------------------------------------------------------
class FirmwareWorld:
    """One dongle + inverter on a true UTC timeline (see the module docstring)."""

    def __init__(self, fw: dict | None = None, *, utc_start: int, bank: dict | None = None, dump_limits=None,
                 boot: str | None = "full", boot_ms: int = 2000, ntp_after_s: float | None = 5, seed: int = 0,
                 noise: bool = True, phase_ms: dict | None = None, warmup_s: float = 0, restart_down_s: float = 3.0):
        if isinstance(utc_start, bool) or not isinstance(utc_start, int):
            raise LabHarnessError(f"utc_start must be an int epoch in seconds, got {utc_start!r}")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise LabHarnessError(f"seed must be an int >= 0, got {seed!r}")
        if isinstance(boot_ms, bool) or not isinstance(boot_ms, int) or not 0 <= boot_ms <= 600000:
            raise LabHarnessError(f"boot_ms must be an int 0..600000, got {boot_ms!r}")
        self.fw = fw if fw is not None else load_fw()
        self.info = fw_info(self.fw)
        self.utc_start, self.seed, self.boot_ms, self.noise = utc_start, seed, boot_ms, bool(noise)
        self.restart_down_s = float(restart_down_s)
        self.ntp_ms = None if ntp_after_s is None else int(round(float(ntp_after_s) * 1000))
        if self.ntp_ms is not None and self.ntp_ms < boot_ms:
            raise LabHarnessError("ntp_after_s must not be earlier than boot_ms")
        self.phase_ms = dict(phase_ms or {})
        for k, v in self.phase_ms.items():
            if k not in self.info.job or isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise LabHarnessError(f"phase_ms: bad entry {k!r}: {v!r}")
        dump_limits = SITE["dump_limits"] if dump_limits is None else dump_limits
        if dump_limits != "factory":
            if not (isinstance(dump_limits, (tuple, list)) and len(dump_limits) == 2
                    and all(isinstance(x, int) and not isinstance(x, bool) for x in dump_limits)):
                raise LabHarnessError(f"dump_limits must be (ceiling, max_export) ints or 'factory', got {dump_limits!r}")
            dump_limits = tuple(dump_limits)
        self.dump_limits = dump_limits
        self.log = T.EventLog()
        self.bank = site_bank(bank)
        self.original = {a: self.bank[a] for a in OWNED}
        self.foreign: set = set()
        self._accept_watch = None      # {dom, pre, texts} while an operator Accept action runs (HL-1 rule)
        self.accept_log: list = []     # one accept_adoption() record per operator Accept (in memory, never logged)
        self.env = dict(ENV_DEFAULT)
        self.link_up, self.bus_idle = True, True
        self._link_outcomes = {"read": "no_response", "write": "timeout_lost"}
        self._modbus = None
        self._ent_flash: dict = {}     # restore numbers / switches as they stand in flash (survives a cut)
        self._ent_pending: dict = {}   # their saves queued since the last global_preferences->sync() (lost at a cut)
        self._nvs_policies: list = []
        self._rtc_windows: list = []
        self._cip_model = None
        self._cut = None
        self._capture_all = None
        self._tel_n = 0
        self._writes: list = []
        self._last_obl = None
        self._last_quiet = None
        self._last_status: dict = {}
        self.job_counts: Counter = Counter()
        self.cuts_fired = 0
        self.job_trace: list | None = None
        self.sim = None
        self.boot_no = -1
        self._depth = 0
        self._booting = False
        if boot == "full":
            self.boot()
            if warmup_s:
                self.run_for(warmup_s)
        elif boot is not None:
            raise LabHarnessError(f"boot must be 'full' or None, got {boot!r}")
        elif warmup_s:
            raise LabHarnessError("warmup_s needs boot='full'")

    # -- clock -----------------------------------------------------------------------------------------------------------
    def _utc_ms(self) -> int:
        if self.sim is None:
            return self.utc_start * 1000
        return self.sim.entities["ntp_time"].utc_ms()

    @property
    def t_utc(self):
        ms = self._utc_ms()
        return ms // 1000 if ms % 1000 == 0 else ms / 1000

    @property
    def uptime_s(self) -> float:
        return self.sim.now_ms / 1000

    def _need_sim(self) -> StrictSim:
        if self.sim is None:
            raise LabHarnessError("the world has not booted yet (boot=None): call world.boot() first")
        return self.sim

    @staticmethod
    def _dur_ms(seconds, what: str) -> int:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise LabHarnessError(f"{what}: a finite duration >= 0 s is required, got {seconds!r}")
        return int(round(seconds * 1000))

    # -- logging ---------------------------------------------------------------------------------------------------------
    def _log(self, kind: str, data=None, src: str = "lab") -> dict:
        up = None if self.sim is None else int(self.sim.now_ms)
        boot = None if self.boot_no < 0 else self.boot_no
        if src == "fw" and (up is None or boot is None):
            raise LabHarnessError(f"fw event {kind} before the first boot")
        return self.log.append(t_utc=self.t_utc, up_ms=up, boot=boot, src=src, kind=kind, data=data)

    def _nvs_markers(self) -> dict:
        return {d: _marker_name(self.sim.nvs.get(t)) for d, t in MARKER_TAGS.items()}

    def obligations(self) -> dict:
        """The obligation snapshot logged as fw.obl (RAM flags of both lease domains and reg244, locks, NVS markers)."""
        g, now = self.sim.g, self._utc_ms() / 1000
        out = {}
        for d, p in (("fp", "free_power"), ("dump", "dump")):
            o = {"act": bool(g[f"{p}_active_persisted"]), "snap": bool(g[f"{p}_snapshot_valid"]),
                 "op": bool(g[f"{p}_operation_in_progress"]), "req": bool(g[f"{p}_restore_requested"]),
                 "corrupt": bool(g[f"{p}_recovery_metadata_corrupt"]), "opn": bool(g[f"{p}_operator_needed"]),
                 "end": int(g[f"{p}_end_epoch"]), "marker": int(g[f"{p}_marker_state"])}
            o["run"] = o["act"] and not o["req"]
            o["due"] = o["snap"] and (o["req"] or not o["act"] or (o["end"] != 0 and now >= o["end"]))
            out[d] = o
        out["r244"] = {"snap": bool(g["reg244_snapshot_valid"]), "corrupt": bool(g["reg244_recovery_metadata_corrupt"]),
                       "op": bool(g["reg244_apply_in_progress"])}
        out["mw"], out["cip"] = bool(g["manual_write_in_progress"]), bool(g["correction_in_progress"])
        out["nvs"] = self._nvs_markers()
        return out

    def _ram_flags(self, obl: dict) -> dict:
        return {"fp_act": obl["fp"]["act"], "fp_snap": obl["fp"]["snap"], "fp_corrupt": obl["fp"]["corrupt"],
                "dump_act": obl["dump"]["act"], "dump_snap": obl["dump"]["snap"], "dump_corrupt": obl["dump"]["corrupt"],
                "r244_snap": obl["r244"]["snap"], "r244_corrupt": obl["r244"]["corrupt"]}

    def _quiet_diff(self) -> dict:
        """{str(addr): [ORIGINAL, live]} of the owned registers that differ from ORIGINAL (foreign ones excluded)."""
        return {str(a): [self.original[a], self.bank.get(a)] for a in OWNED
                if a not in self.foreign and self.bank.get(a) != self.original[a]}

    def _note_state(self) -> None:
        if self.sim is None:
            return
        obl = self.obligations()
        if obl != self._last_obl:
            self._last_obl = obl
            self._log("fw.obl", obl, src="fw")
        if not _is_locked(obl):
            # the logged fw.quiet record keeps its V0 form (digest stability of the corpus): `visible` also lists stored
            # markers ('nvs.<dom>'); check_no_silent_override uses only its RAM part (see that checker)
            visible = sorted([f"nvs.{d}" for d, m in obl["nvs"].items() if m != "CLEAR" and m != "ABSENT"]
                             + _ram_visible(obl))
            quiet = {"diff": self._quiet_diff(), "visible": visible}
            if quiet != self._last_quiet:
                self._last_quiet = quiet
                self._log("fw.quiet", quiet, src="fw")

    def quiet_state(self) -> dict:
        """INV-NO-SILENT-OVERRIDE's view of NOW (read-only: logs nothing, changes nothing): {booting, locked, diff,
        visible, nvs, silent}. diff as in fw.quiet; visible = the RAM rule (_ram_visible: '<dom>.snap' / '<dom>.corrupt'
        for fp / dump / r244 - a stored marker alone is NOT visible); nvs = the stored markers; silent = a non-empty diff
        with nothing visible at a steady point (not booting, no transaction lock held)."""
        self._need_sim()
        obl = self.obligations()
        locked, diff, visible = _is_locked(obl), self._quiet_diff(), _ram_visible(obl)
        return {"booting": bool(self._booting), "locked": locked, "diff": diff, "visible": visible, "nvs": obl["nvs"],
                "silent": bool(diff) and not visible and not locked and not self._booting}

    def _on_publish(self, name: str, value) -> None:
        if name in self.info.restore_switches:   # Switch::publish_state saves a restoring switch (queued until a sync)
            self._ent_pending[name] = value
        dom = _STATUS_BY_ID.get(name)
        if dom is not None:
            text = str(value)
            watch = self._accept_watch
            if watch is not None and watch["dom"] == dom:   # every publish, also an unchanged text (HL-1 rule)
                watch["texts"].append(text)
            if self._last_status.get(dom) != text:
                self._last_status[dom] = text
                self._log("fw.status", {"dom": dom, "text": text}, src="fw")

    def _on_start(self, dom: str, script_id: str) -> None:
        self._log("fw.start", {"dom": dom, "script": script_id}, src="fw")

    def _on_restart(self, button_id: str) -> None:
        """A press of the `restart` platform button: ESPHome's safe reboot (on_shutdown: every RestoringGlobalsComponent
        stores a changed value, then global_preferences->sync(); INFERRED), then a FULL boot after restart_down_s -
        modelled as a graceful power cut at the press."""
        if not (self._depth or self._booting):
            raise LabHarnessError(f"restart button {button_id} pressed outside a world action")
        self._pref_job("pref_poll")
        self._pref_job("pref_sync")
        self._log("fw.restart", {"button": button_id}, src="fw")
        raise _PowerCut(self._capture(None), {"down_s": self.restart_down_s, "nvs_fault": None, "keep_prefs": True})

    def _on_event(self, ev) -> None:
        sim, kind = self.sim, ev[0]
        if kind == "commit":
            data = {"key": ev[1], "rec": _rec_dict(ev[2]), "landed": bool(ev[3])}
        elif kind == "load":
            data = {"key": ev[1], "ok": bool(ev[2])}
        elif kind == "write":
            addr, vals, outcome = ev[1], [int(v) if isinstance(v, int) else v for v in ev[2]], ev[3]
            obl = self.obligations()
            top = sim.script_stack[-1] if sim.script_stack else None
            landed = outcome in LANDED_OUTCOMES
            data = {"addr": addr, "vals": vals, "outcome": outcome, "landed": landed, "scripts": list(sim.script_stack),
                    "dom": script_domain(top), "nvs": obl["nvs"], "ram": self._ram_flags(obl)}
            if landed:
                self.foreign.difference_update(range(addr, addr + len(vals)))
                if data["dom"] in OWNER_DOMAINS:   # the owner's own manual apply: its values are the new ORIGINAL
                    for i, v in enumerate(vals):
                        if addr + i in self.original:
                            self.original[addr + i] = v
        elif kind == "read":
            data = {"addr": ev[1], "count": ev[2], "outcome": ev[3]}
        else:
            raise LabHarnessError(f"unknown simulator event {ev!r}")
        e = self._log("fw." + kind, data, src="fw")
        if kind == "write":
            self._writes.append({"boot": self.boot_no, "t_utc": e["t_utc"], "seq": e["seq"], **{k: data[k] for k in (
                "addr", "vals", "outcome", "landed", "dom")}})
        self._note_state()
        if self._capture_all is not None:
            self._capture_all.append(self._capture(e))
        cut = self._cut
        if cut is not None and (self._depth or self._booting) and cut["pred"](e):
            cut["seen"] += 1
            if cut["seen"] >= cut["nth"]:
                self._cut = None
                cap = self._capture(e)
                self._log("cut.fired", {"seq": e["seq"], "kind": e["kind"]})
                raise _PowerCut(cap, cut["opts"])

    # -- outcomes --------------------------------------------------------------------------------------------------------
    def _outcome(self, kind, addr, count):
        if not self.link_up:
            outcome, source = self._link_outcomes[kind], "link"
        else:
            outcome, source = (self._modbus(kind, addr, count) if self._modbus else None) or "ok", "policy"
        if outcome != "ok":
            self._log("fault.modbus", {"op": kind, "addr": addr, "count": count, "outcome": outcome, "source": source})
        return outcome

    def modbus_policy(self, policy=None) -> None:
        """policy: None (all ok), fn(kind, addr, count) -> outcome or None (= ok), or a table {key: [outcome, ...] | outcome}
        with keys 'write:256', 'read:244x12', 'read:244', 'write:*', 'read:*', '*'. Only the MOST SPECIFIC key present
        for an operation decides it: a list is consumed one outcome per such operation and then yields 'ok' (it never
        falls through to a less specific key), a string applies to every such operation."""
        if policy is None or callable(policy):
            fn = policy
        elif isinstance(policy, dict):
            table = {}
            for key, v in policy.items():
                if not isinstance(key, str) or not re.match(r"^(\*|(read|write):(\*|\d+(x\d+)?))$", key):
                    raise LabHarnessError(f"modbus_policy: bad key {key!r}")
                outs = [v] if isinstance(v, str) else list(v) if isinstance(v, list) else None
                op = key.split(":")[0]
                allowed = (set(READ_OUTCOMES) & set(WRITE_OUTCOMES) if key == "*"
                           else set(WRITE_OUTCOMES if op == "write" else READ_OUTCOMES))
                if outs is None or any(o not in allowed for o in outs):
                    raise LabHarnessError(f"modbus_policy: {key!r} -> {v!r} is not an allow-listed outcome")
                table[key] = (isinstance(v, str), outs)

            def fn(kind, addr, count):
                key = next((k for k in (f"{kind}:{addr}x{count}", f"{kind}:{addr}", f"{kind}:*", "*") if k in table), None)
                if key is None:
                    return None
                always, outs = table[key]
                return outs[0] if always else outs.pop(0) if outs else None
        else:
            raise LabHarnessError(f"modbus_policy: unsupported policy {policy!r}")
        self._modbus = fn
        self._log("fault.modbus_policy", {"policy": "none" if policy is None else "fn" if callable(policy) else policy})

    def set_link(self, up: bool, *, read_outcome: str = "no_response", write_outcome: str = "timeout_lost") -> None:
        if not isinstance(up, bool) or read_outcome not in READ_OUTCOMES or write_outcome not in WRITE_OUTCOMES:
            raise LabHarnessError(f"set_link({up!r}, {read_outcome!r}, {write_outcome!r})")
        self.link_up = up
        self._link_outcomes = {"read": read_outcome, "write": write_outcome}
        self._log("env.link", {"up": up, "read": read_outcome, "write": write_outcome})

    def set_bus_idle(self, idle: bool) -> None:
        if not isinstance(idle, bool):
            raise LabHarnessError(f"set_bus_idle needs a bool, got {idle!r}")
        self.bus_idle = idle
        if self.sim is not None:
            self.sim.bus_idle = idle
        self._log("env.bus", {"idle": idle})

    def set_register(self, addr, value, actor: str = "owner") -> None:
        addr, value = _reg(addr), _u16(value, f"set_register({addr})")
        if actor not in ("owner", "inverter"):
            raise LabHarnessError(f"set_register: actor must be 'owner' or 'inverter', got {actor!r}")
        old = self.bank.get(addr)
        self.bank[addr] = value
        if addr in self.original:
            if actor == "owner":
                self.original[addr] = value
                self.foreign.discard(addr)
            else:
                self.foreign.add(addr)
        self._log("env.register", {"addr": addr, "value": value, "old": old, "actor": actor})
        self._note_state()

    # -- NVS commit policy -----------------------------------------------------------------------------------------------
    def nvs_policy(self, tag_or_pred, state_pred=None, mode: str = "not_landed", times: int | None = 1) -> None:
        """The next `times` (None: every) commits whose key matches (tag / alias string, or fn(key, record) -> bool) and
        whose record matches state_pred (None, an int compared with record.state, or fn(record) -> bool) get `mode`.
        NVS USED-KEY RULE (module docstring): a not_landed / false_negative / false_positive policy that FIRES on a key
        never stored earlier in this run (nvs_stored_earlier) raises LabHarnessError at that commit; arming is never
        refused for it (the precondition is judged when the faulting commit happens; predicates are not evaluated
        here)."""
        if mode not in NVS_MODES:
            raise LabHarnessError(f"nvs_policy: mode {mode!r} not in {NVS_MODES}")
        if times is not None and (isinstance(times, bool) or not isinstance(times, int) or times < 1):
            raise LabHarnessError(f"nvs_policy: times must be an int >= 1 or None, got {times!r}")
        if callable(tag_or_pred):
            key_pred, key_desc = tag_or_pred, "fn"
        else:
            tag = _tag(tag_or_pred)
            key_pred, key_desc = (lambda k, r, _t=tag: k == _t), tag
        if state_pred is None:
            st_pred, st_desc = (lambda r: True), None
        elif callable(state_pred):
            st_pred, st_desc = state_pred, "fn"
        elif isinstance(state_pred, int) and not isinstance(state_pred, bool):
            st_pred, st_desc = (lambda r, _s=state_pred: getattr(r, "state", None) == _s), state_pred
        else:
            raise LabHarnessError(f"nvs_policy: bad state_pred {state_pred!r}")
        self._nvs_policies.append({"key": key_pred, "state": st_pred, "mode": mode, "left": times,
                                   "desc": {"key": key_desc, "state": st_desc, "mode": mode, "times": times}})
        self._log("fault.nvs_policy", self._nvs_policies[-1]["desc"])

    @staticmethod
    def _stored_earlier(sim: StrictSim, log, key: str) -> bool:
        """The NVS USED-KEY RULE (module docstring) for durable tag `key` on `sim` (its NVS now) and `log` (this world's
        EventLog, across boots). Read-only; logs nothing."""
        if key in sim.nvs:
            return True
        stored = False
        for e in log:
            kind = e["kind"]
            if kind == "fw.commit" and e["data"]["key"] == key and e["data"]["landed"]:
                stored = True
            elif kind == "fault.nvs_boot" and e["data"]["fault"] == ["erase_all"]:
                stored = False
        return stored

    def nvs_stored_earlier(self, tag) -> bool:
        """True when NVS tag `tag` (alias or tag) was STORED EARLIER IN THIS RUN (the NVS USED-KEY RULE of the module
        docstring: a record under it in the current NVS, or a landed fw.commit of it in this world's EventLog after the
        last ('erase_all',) boot fault). Read-only."""
        return self._stored_earlier(self._need_sim(), self.log, _tag(tag))

    def _install_commit(self, sim: StrictSim) -> None:
        real = sim.D.commit_record

        def commit(key, record):
            pol = next((p for p in self._nvs_policies if (p["left"] is None or p["left"] > 0)
                        and p["key"](key, record) and p["state"](record)), None)
            if pol is None:
                return real(key, record)
            mode = pol["mode"]
            if mode in NVS_USED_KEY_MODES and not self._stored_earlier(sim, self.log, key):
                # the NVS USED-KEY RULE, judged at the faulting commit (before the fault is consumed or logged)
                raise _never_stored_error(mode, key)
            if pol["left"] is not None:
                pol["left"] -= 1
            self._log("fault.nvs_commit", {"key": key, "mode": mode, "rec": _rec_dict(record),
                                           "returned": mode in ("landed", "false_positive")})
            if mode == "landed":
                return real(key, record)
            if mode == "false_negative":
                real(key, record)
                return False
            sim.nvs_commits.append((key, record.copy()))   # not_landed / false_positive: nothing stored
            sim._log_event(("commit", key, record.copy(), False))
            return mode == "false_positive"
        sim.D.commit_record = commit

    # -- boot ------------------------------------------------------------------------------------------------------------
    def _first_prefs(self) -> dict:
        info = self.info
        prefs = {n: info.initial[n] for n in info.restore_globals}
        if self.dump_limits != "factory":
            ceiling, max_export = self.dump_limits
            cap = int(self.fw["_substitutions"]["ecco_dump_capability_w"])
            prefs.update({"dump_op_ceiling_w": ceiling, "dump_max_export_w": max_export, "dump_limits_cap_w": cap,
                          # the integrity value the validated set_actions store (_dump_sim.py:1410)
                          "dump_limits_check": ds.wrap(ceiling + 3 * max_export + 7 * cap + 12345, "uint32_t")})
        return prefs

    def boot(self, nvs: dict | None = None, nvs_fault=None) -> None:
        """The first boot (boot=None worlds only call this once): `nvs` = a durable image {tag: ds.Record}."""
        if self.sim is not None:
            raise LabHarnessError("already booted: use reboot()")
        self._boot(nvs=dict(nvs or {}), prefs=self._first_prefs(), numbers={}, switches={},
                   utc_on_boot_ms=self.utc_start * 1000, nvs_fault=nvs_fault, reason="first boot")

    def _boot(self, *, nvs, prefs, numbers, switches, utc_on_boot_ms, nvs_fault, reason) -> None:
        for _attempt in range(3):
            try:
                self._boot_once(nvs=nvs, prefs=prefs, numbers=numbers, switches=switches, utc_on_boot_ms=utc_on_boot_ms,
                                nvs_fault=nvs_fault, reason=reason)
                return
            except _PowerCut as cut:   # a cut armed on a boot-time event: reboot from that capture once more
                self._log("cut.during_boot", {"boot": self.boot_no})
                c, o = cut.capture, cut.opts
                nvs, prefs, numbers, switches, nvs_fault = (c["nvs"], c["prefs"] if o["keep_prefs"] else {},
                                                            c["numbers"] if o["keep_prefs"] else {},
                                                            c["switches"] if o["keep_prefs"] else {}, o["nvs_fault"])
                self.bank = dict(c["bank"])
                utc_on_boot_ms = c["utc_ms"] + self._dur_ms(o["down_s"], "down_s") + self.boot_ms
                reason = "power cut during boot"
        raise LabHarnessError("power cut re-armed during every boot attempt")

    def _boot_once(self, *, nvs, prefs, numbers, switches, utc_on_boot_ms, nvs_fault, reason) -> None:
        info = self.info
        sim = StrictSim(self.fw)
        self.boot_no += 1
        sim.seed_rng(self.seed * 7919 + self.boot_no)
        sim.now_ms = self.boot_ms
        clock = F.WallClock(sim, 0, t0_ms=self.boot_ms)
        clock.utc0_ms = int(utc_on_boot_ms)
        sim.entities["ntp_time"] = clock
        sim.ntp_valid = False
        sim.nvs = {k: v.copy() for k, v in nvs.items()}
        sim.bank = self.bank
        sim.bus_idle = self.bus_idle
        for name in ("dump_max_export_w", "dump_limits_check", "dump_limits_valid"):   # undo ds.Sim's 'configured' shortcut
            sim.g[name] = info.initial[name]
        for name in info.restore_globals:
            sim.g[name] = prefs.get(name, info.initial[name])
        sim.pref_baseline()
        for eid, v in numbers.items():
            sim.entities[eid].set(v)
        for eid, v in switches.items():
            sim.entities[eid].state = v
        self._ent_flash, self._ent_pending = {**numbers, **switches}, {}
        self._install_pref_sync(sim)
        self.sim, self._last_obl, self._last_quiet, self._last_status, self._cip_model = sim, None, None, {}, None
        fault = self._apply_boot_fault(sim, nvs_fault)
        sim.outcome_fn = self._outcome
        sim.event_hook = self._on_event
        sim.publish_hook = self._on_publish
        sim.start_hook = self._on_start
        sim.restart_hook = self._on_restart
        self._install_commit(sim)
        self._sched_reset()
        self._log("fw.boot", {"boot": self.boot_no, "reason": reason, "nvs_fault": fault, "keys": sorted(sim.nvs),
                              "boot_ms": self.boot_ms}, src="fw")
        self._booting = True
        try:
            for item in info.boot_items:
                if item["executed"]:
                    sim.run_lambda(item["lambda"])
        finally:
            self._booting = False
        self._apply_rtc()
        self._log("fw.booted", {"boot": self.boot_no, "obl": self.obligations()}, src="fw")
        self._note_state()

    def _apply_boot_fault(self, sim: StrictSim, nvs_fault):
        if nvs_fault is None:
            return None
        if not isinstance(nvs_fault, (tuple, list)) or not nvs_fault or nvs_fault[0] not in NVS_BOOT_FAULTS:
            raise LabHarnessError(f"nvs_fault must be one of {NVS_BOOT_FAULTS} as a tuple, got {nvs_fault!r}")
        kind = nvs_fault[0]
        if kind in ("read_error_all", "erase_all"):
            if len(nvs_fault) != 1:
                raise LabHarnessError(f"nvs_fault {nvs_fault!r} takes no tag")
            if kind == "read_error_all":
                sim.nvs_fail_load_all = True
            else:
                sim.nvs.clear()
            out = [kind]
        else:
            if len(nvs_fault) != 2:
                raise LabHarnessError(f"nvs_fault {nvs_fault!r} needs exactly one tag")
            tag = _tag(nvs_fault[1])
            if kind in NVS_USED_KEY_BOOT_FAULTS and not self._stored_earlier(sim, self.log, tag):
                raise _never_stored_error(kind, tag)   # the NVS USED-KEY RULE (HL-6 and its wrong_size sibling)
            if kind == "absent":
                if tag not in sim.nvs:
                    raise LabHarnessError(f"nvs_fault absent: {tag} is not stored (a false ABSENT needs a record)")
                del sim.nvs[tag]
            elif kind == "read_error":
                sim.nvs_fail_load_tags = {tag}
            else:
                sim.nvs[tag] = ds.Record("_WrongSizeBlob")
            out = [kind, tag]
        self._log("fault.nvs_boot", {"fault": out})
        return out

    def _install_pref_sync(self, sim: StrictSim) -> None:
        """Per instance: global_preferences->sync() (ds.Sim.pref_sync: the queued globals) also writes the queued number /
        switch saves - ESPHome has ONE pending-save queue (commit_record's sync calls this too)."""
        real = sim.pref_sync

        def pref_sync():
            if sim.pref_cut_after is not None and self._ent_pending:
                raise LabUnsupported("a preference flush cut short while number / switch saves are queued is not modelled")
            ok = real()
            pending, self._ent_pending = self._ent_pending, {}
            if ok:   # a failed flush drops the queue (as ds.Sim.pref_sync does for the globals)
                self._ent_flash.update(pending)
            return ok
        sim.pref_sync = pref_sync

    def _pref_job(self, name: str) -> None:
        """MODEL (PREF_JOBS): 'pref_poll' = RestoringGlobalsComponent::update() of every restore_value global (a changed
        value is queued: ds.Sim.pref_update); 'pref_sync' = the preferences IntervalSyncer's global_preferences->sync()."""
        if name == "pref_poll":
            for g in self.info.restore_globals:
                self.sim.pref_update(g)
        elif name == "pref_sync":
            self.sim.pref_sync()
        else:
            raise LabHarnessError(f"unknown preference job {name!r}")

    def _capture(self, event: dict | None) -> dict:
        """The state a power cut leaves: NVS, the inverter bank, and what reached flash (globals, numbers, switches)."""
        sim, flash, info = self.sim, self._ent_flash, self.info
        return {"seq": None if event is None else event["seq"], "event": event, "utc_ms": self._utc_ms(),
                "uptime_ms": sim.now_ms, "boot": self.boot_no, "nvs": {k: v.copy() for k, v in sim.nvs.items()},
                "bank": dict(self.bank), "prefs": dict(sim.pref_flushed),
                "numbers": {e: flash[e] for e in info.restore_numbers if e in flash},
                "switches": {e: flash[e] for e in info.restore_switches if e in flash}}

    def reboot(self, down_s: float = 5.0, nvs_fault=None, keep_prefs: bool = True) -> None:
        """A power cut NOW and a FULL boot after down_s (see MODEL ASSUMPTIONS)."""
        self._need_sim()
        self._log("act.reboot", {"down_s": down_s, "nvs_fault": None if nvs_fault is None else list(nvs_fault),
                                 "keep_prefs": keep_prefs})
        self.reboot_from(self._capture(None), down_s=down_s, nvs_fault=nvs_fault, keep_prefs=keep_prefs)

    def reboot_from(self, capture: dict, down_s: float = 5.0, nvs_fault=None, keep_prefs: bool = True) -> None:
        """Boot a new StrictSim from `capture` (nvs, bank, prefs, restore numbers / switches); RAM fresh; FULL on_boot;
        hooks re-bound to the new sim; the EventLog and the boot counter continue."""
        self._need_sim()
        down_ms = self._dur_ms(down_s, "down_s")
        if not isinstance(keep_prefs, bool):
            raise LabHarnessError("keep_prefs must be a bool")
        erase = nvs_fault is not None and tuple(nvs_fault)[:1] == ("erase_all",)
        keep = keep_prefs and not erase
        self._log("fw.power_off", {"boot": self.boot_no, "capture_seq": capture["seq"], "down_s": down_s,
                                   "keep_prefs": keep_prefs}, src="fw")
        self.bank = dict(capture["bank"])
        utc_cut = max(capture["utc_ms"], self._utc_ms())   # UTC never runs backwards
        self._boot(nvs=capture["nvs"], prefs=capture["prefs"] if keep else {}, numbers=capture["numbers"] if keep else {},
                   switches=capture["switches"] if keep else {}, utc_on_boot_ms=utc_cut + down_ms + self.boot_ms,
                   nvs_fault=nvs_fault, reason="reboot")

    def arm_power_cut(self, predicate=None, *, kind: str | None = None, key: str | None = None, addr: int | None = None,
                      state: int | None = None, nth: int = 1, down_s: float = 5.0, nvs_fault=None,
                      keep_prefs: bool = True) -> None:
        """Cut power at the nth fw event matching `predicate(event) -> bool` (or the kind / key / addr / state spec); the
        running action aborts and the world reboots from the capture taken just after that event."""
        if isinstance(nth, bool) or not isinstance(nth, int) or nth < 1:
            raise LabHarnessError(f"nth must be an int >= 1, got {nth!r}")
        if predicate is None:
            if kind is not None and kind not in ("fw.commit", "fw.load", "fw.write", "fw.read"):
                raise LabHarnessError(f"arm_power_cut: kind {kind!r}")
            tag = None if key is None else _tag(key)

            def predicate(e, _k=kind, _t=tag, _a=addr, _s=state):
                d = e["data"]
                return ((_k is None or e["kind"] == _k) and e["kind"] in ("fw.commit", "fw.load", "fw.write", "fw.read")
                        and (_t is None or d.get("key") == _t) and (_a is None or d.get("addr") == _a)
                        and (_s is None or (d.get("rec") or {}).get("state") == _s))
            desc = {"kind": kind, "key": tag, "addr": addr, "state": state}
        elif callable(predicate):
            desc = "fn"
        else:
            raise LabHarnessError("arm_power_cut: predicate must be callable")
        self._cut = {"pred": predicate, "nth": nth, "seen": 0,
                     "opts": {"down_s": down_s, "nvs_fault": nvs_fault, "keep_prefs": keep_prefs}}
        self._log("cut.armed", {"match": desc, "nth": nth, "down_s": down_s,
                                "nvs_fault": None if nvs_fault is None else list(nvs_fault)})

    def capture_points(self, fn) -> list:
        """Run fn(world) and return a capture after EVERY fw event it caused (for power-cut sweeps with reboot_from)."""
        self._need_sim()
        if self._capture_all is not None:
            raise LabHarnessError("capture_points does not nest")
        self._capture_all = []
        try:
            fn(self)
            return self._capture_all
        finally:
            self._capture_all = None

    @contextlib.contextmanager
    def _acting(self, name: str, args: dict):
        """One world action: logged, never nested, and the power-cut boundary (an armed cut aborts the action here)."""
        self._need_sim()
        if self._depth:
            raise LabHarnessError(f"world action {name!r} called inside another world action")
        self._log("act." + name, args)
        self._depth += 1
        try:
            yield
        except _PowerCut as cut:
            self._depth = 0
            o = cut.opts
            self.reboot_from(cut.capture, down_s=o["down_s"], nvs_fault=o["nvs_fault"], keep_prefs=o["keep_prefs"])
            self.cuts_fired += 1
        finally:
            self._depth = 0
        self._note_state()

    # -- scheduler -------------------------------------------------------------------------------------------------------
    def _sched_reset(self) -> None:
        self._next, self._period = {}, {}
        for j in self.info.jobs:
            if j["executed"]:
                first = j["startup_ms"] if j["startup_ms"] is not None else j["period_ms"]
                self._next[j["name"]] = first + self.phase_ms.get(j["name"], 0)
                self._period[j["name"]] = j["period_ms"]
        for name, period in zip(PREF_JOBS, (_GLOBALS_POLL_MS, self.info.flash_write_ms)):   # anchored at power-on
            self._next[name] = self._period[name] = period
        self._ntp_due = self.ntp_ms

    def _rtc_edges_up(self) -> list:
        sim, u = self.sim, self._utc_ms()
        return [sim.now_ms + (e - u) for w in self._rtc_windows for e in w if e > u]

    def _apply_rtc(self) -> None:
        """MODEL: correction_in_progress follows the lock windows (written at every edge and after every boot)."""
        if not self._rtc_windows or self.sim is None:
            return
        u = self._utc_ms()
        inside = any(a <= u < b for a, b in self._rtc_windows)
        if inside != self._cip_model:
            self.sim.g["correction_in_progress"] = inside
            self._cip_model = inside
            self._log("env.rtc_lock", {"locked": inside})

    def rtc_lock_windows(self, windows) -> None:
        """MODEL: correction_in_progress is held inside every [utc_a, utc_b) window (epoch s or 'YYYY-MM-DDTHH:MM:SSZ')."""
        out = []
        for w in windows:
            if not isinstance(w, (list, tuple)) or len(w) != 2:
                raise LabHarnessError(f"rtc_lock_windows: bad window {w!r}")
            a, b = (C.parse_iso_utc(x) if isinstance(x, str) else x for x in w)
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (a, b)) or not a < b:
                raise LabHarnessError(f"rtc_lock_windows: window {w!r} must have utc_a < utc_b")
            out.append((int(round(a * 1000)), int(round(b * 1000))))
        self._rtc_windows = sorted(out)
        self._cip_model = None
        self._log("env.rtc_windows", {"windows": [[a / 1000, b / 1000] for a, b in self._rtc_windows]})
        self._apply_rtc()
        self._note_state()

    def advance(self, seconds) -> None:
        """Raw time: uptime and UTC move together and NOTHING runs (no interval, no poll, no NTP)."""
        ms = self._dur_ms(seconds, "advance")
        self._need_sim().advance(ms)
        self._apply_rtc()
        self._note_state()

    def advance_to(self, utc_s) -> None:
        """The replay world protocol: a LIVE advance (run_for with defaults) landing exactly on utc_s; a power cut on the
        way reboots and the advance continues on the new boot."""
        target = int(round(utc_s * 1000))
        if target < self._utc_ms():
            raise LabHarnessError(f"advance_to({utc_s}) is in the past")
        while self._utc_ms() < target:
            self.run_for((target - self._utc_ms()) / 1000)
        if self._utc_ms() != target:
            raise LabHarnessError(f"advance_to({utc_s}): a power cut and reboot ran past it (now {self._utc_ms() / 1000})")

    def run_for(self, seconds, *, wd_order=("fp", "dump"), telemetry: bool = True, config: bool = True) -> None:
        """The scheduler (module docstring): every due job, NTP and RTC-window edge up to now + seconds."""
        span = self._dur_ms(seconds, "run_for")
        if tuple(wd_order) not in (("fp", "dump"), ("dump", "fp")):
            raise LabHarnessError(f"wd_order must be ('fp', 'dump') or ('dump', 'fp'), got {wd_order!r}")
        with self._acting("run_for", {"seconds": seconds, "wd_order": list(wd_order), "telemetry": telemetry,
                                      "config": config}):
            sim = self.sim
            end = sim.now_ms + span
            order = [j["name"] for j in self.info.jobs if j["executed"]]
            i, k = order.index("fp_wd"), order.index("dump_wd")
            if tuple(wd_order) == ("dump", "fp") and i < k or tuple(wd_order) == ("fp", "dump") and i > k:
                order[i], order[k] = order[k], order[i]
            order += list(PREF_JOBS)   # MODEL: after the firmware jobs of the same instant, the poll before the sync
            skip = set() if telemetry else {"telemetry"}
            if not config:
                skip |= {"config", "owed_config"}
            while True:
                cands = list(self._next.values()) + [e for e in self._rtc_edges_up() if e > sim.now_ms]
                if self._ntp_due is not None:
                    cands.append(self._ntp_due)
                t = min(cands)
                if t > end:
                    break
                sim.now_ms = max(sim.now_ms, t)
                self._apply_rtc()
                if self._ntp_due is not None and self._ntp_due <= sim.now_ms:
                    self._ntp_due = None
                    self._ntp_sync()
                for name in order:
                    due = self._next[name]
                    if due <= sim.now_ms:
                        period = self._period[name]
                        # a slot missed by a raw advance() runs once now; no burst of catch-up runs (INFERRED ESPHome)
                        self._next[name] = due + period if due + period > sim.now_ms else sim.now_ms + period
                        if name not in skip:
                            self._run_job(name)
                self._note_state()
            sim.now_ms = end
            self._apply_rtc()

    def _ntp_sync(self) -> None:
        sim = self.sim
        sim.ntp_valid = True
        for t in self.fw.get("time") or []:
            for a in ((t.get("on_time_sync") or {}).get("then") or []):
                if "lambda" in a:
                    sim.run_lambda(a["lambda"])   # pattern from registry/tests/_fbd1_harness.py:921-928 (ntp_sync)
        self._log("fw.ntp_sync", {}, src="fw")

    def _run_job(self, name: str, scheduled: bool = True) -> None:
        if scheduled:
            self.job_counts[name] += 1
            if self.job_trace is not None:
                self.job_trace.append((self.sim.now_ms, name))
        if name in PREF_JOBS:
            self._pref_job(name)
            return
        if name == "telemetry":
            self._encode_env()
        self.sim.run_actions(self.info.job[name]["then"])

    # -- environment -----------------------------------------------------------------------------------------------------
    def _encode_env(self) -> None:
        """MODEL: world.env -> the inverter's telemetry registers, as the real 150-196 decode reads them back."""
        env, n, b, r = self.env, self._tel_n, self.bank, _ENV_REG
        self._tel_n += 1
        noisy = {"grid_w": env["grid_w"] - (n % 2 if self.noise else 0),
                 "batt_w": env["batt_w"] + ((n % 3) - 1 if self.noise else 0)}
        for k in ("grid_w", "inverter_w", "house_w", "pv_w", "batt_w"):
            b[r[k]] = _i16(noisy.get(k, env[k]), k)
        b[r["batt_v"]] = _u16(int(round(env["batt_v"] * 100)), "batt_v x100")
        b[r["soc"]] = env["soc"]
        b[r["grid_connected"]] = 1 if env["grid_connected"] else 0
        for a in (187, 188, 189):   # PV strings 2-4 (the decode sums four strings)
            b[a] = 0

    def telemetry(self, *, poll: bool = True, **values) -> None:
        """Set the inverter's live telemetry (MODEL image of registers 150-196) and, with poll=True, run the real
        telemetry interval now (its own condition, the real poll script and decode, gated by the link)."""
        for k, v in values.items():
            if k not in ENV_DEFAULT:
                raise LabHarnessError(f"telemetry: unknown field {k!r} (known: {sorted(ENV_DEFAULT)})")
            if k == "grid_connected":
                if not isinstance(v, bool):
                    raise LabHarnessError("telemetry: grid_connected must be a bool")
            elif k == "soc":
                if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100:
                    raise LabHarnessError(f"telemetry: soc is an integer percent 0..100 (register 184), got {v!r}")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise LabHarnessError(f"telemetry: {k} must be a finite number, got {v!r}")
        with self._acting("telemetry", {"poll": poll, **values}):
            self.env.update(values)
            self._log("env.telemetry", dict(self.env))
            if poll:
                self._run_job("telemetry", scheduled=False)
            else:
                self._encode_env()

    def config_poll(self) -> None:
        """One configuration poll now: the real poll_inverter_configuration script (wrapper, dispatch, Block A / B / C
        reads through the link and fault policies; MODEL Block A / B on_response handlers)."""
        with self._acting("config_poll", {}):
            self.sim.execute("poll_inverter_configuration")

    # -- entity actions --------------------------------------------------------------------------------------------------
    def _number_node(self, eid: str, value) -> dict:
        """The firmware number's node after the range check set_number() applies (raises LabHarnessError)."""
        kind, node = self.info.entities.get(eid, (None, None))
        if kind != "number":
            raise LabHarnessError(f"{eid!r} is not a firmware number")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise LabHarnessError(f"number {eid}: finite value required, got {value!r}")
        subs = self.fw["_substitutions"]
        lo, hi = (float(ds.substitute(str(node[k]), subs)) for k in ("min_value", "max_value"))
        if not lo <= value <= hi:
            raise LabHarnessError(f"number {eid}: {value} outside [{lo}, {hi}] (ESPHome would refuse it)")
        return node

    def set_number(self, eid: str, value) -> None:
        node = self._number_node(eid, value)
        sim = self.sim
        if "set_action" in node:
            sim.run_actions(node["set_action"], {"x": float(value)})   # pattern from test_dump_safety_fcp2.py:1570
        if node.get("optimistic"):
            sim.ent(eid).publish_state(float(value))
        if node.get("restore_value"):   # TemplateNumber::control saves the value (queued until the next sync)
            self._ent_pending[eid] = float(value)

    def set_switch(self, eid: str, on: bool) -> None:
        kind, node = self.info.entities.get(eid, (None, None))
        if kind != "switch" or not isinstance(on, bool):
            raise LabHarnessError(f"set_switch({eid!r}, {on!r}): not a firmware switch / bool")
        if not node.get("optimistic"):
            raise LabUnsupported(f"switch {eid} is not optimistic: its state source is not modelled")
        sim = self.sim
        if on and "turn_on_action" in node:
            sim.run_actions(node["turn_on_action"])
        if not on and "turn_off_action" in node:
            sim.run_actions(node["turn_off_action"])
        sim.ent(eid).publish_state(on)

    def set_select(self, eid: str, option: str) -> None:
        kind, node = self.info.entities.get(eid, (None, None))
        if kind != "select" or option not in (node.get("options") or []):
            raise LabHarnessError(f"set_select({eid!r}, {option!r}): not a firmware select option")
        if not node.get("optimistic"):
            raise LabUnsupported(f"select {eid} is not optimistic")
        self.sim.ent(eid).publish_state(ds.CStr(option))

    def press(self, button_id: str) -> None:
        """What a Home Assistant button press does: the button's real on_press (a building block of the actions)."""
        node = self.info.buttons.get(button_id)
        if node is None or "on_press" not in node:
            raise LabHarnessError(f"{button_id!r} is not a firmware button with on_press")
        self.sim.run_actions(node["on_press"])

    def fp_start(self, power_w=None, minutes=None, arm: bool = True) -> str:
        with self._acting("fp_start", {"power_w": power_w, "minutes": minutes, "arm": arm}):
            if power_w is not None:
                self.set_number("free_power_max_power", power_w)
            if minutes is not None:
                self.set_number("free_power_duration_minutes", minutes)
            if arm:
                self.set_switch("free_power_write_enable", True)
            self.press("start_free_power_button")
        return self.status("fp")

    def fp_end(self) -> str:
        with self._acting("fp_end", {}):
            self.press("end_free_power_button")
        return self.status("fp")

    def dump_start(self, power_w=None, stop_soc=None, minutes=None, arm: bool = True) -> str:
        with self._acting("dump_start", {"power_w": power_w, "stop_soc": stop_soc, "minutes": minutes, "arm": arm}):
            for eid, v in (("dump_export_power", power_w), ("dump_stop_soc", stop_soc), ("dump_duration_minutes", minutes)):
                if v is not None:
                    self.set_number(eid, v)
            if arm:
                self.set_switch("dump_write_enable", True)
            self.press("start_dump_to_grid_button")
        return self.status("dump")

    def dump_end(self) -> str:
        with self._acting("dump_end", {}):
            self.press("end_dump_to_grid_button")
        return self.status("dump")

    def dump_force_restore(self, arm: bool = True) -> str:
        with self._acting("dump_force_restore", {"arm": arm}):
            if arm:
                self.set_switch("dump_recovery_arm", True)
            self.press("dump_force_restore_button")
        return self.status("dump")

    def dump_accept(self, arm: bool = True) -> str:
        with self._acting("dump_accept", {"arm": arm}):
            self._accept_watch = {"dom": "dump", "pre": self.obligations(), "texts": []}
            try:
                if arm:
                    self.set_switch("dump_recovery_arm", True)
                self.press("dump_accept_current_state_button")
                self._adopt_if_clear("dump")
            finally:
                self._accept_watch = None
        return self.status("dump")

    def fp_operator(self, action: str = "FORCE_RESTORE_ORIGINAL", arm: bool = True, evidence_id: str | None = None,
                    phrase: str | None = None) -> str:
        """Review, arm, then the real free_power_recovery_execute API action (pattern from
        registry/tests/_sg01_recovery_harness.py:421-462; its audited() wrapper is not used because it rebinds hooks)."""
        if action not in OPERATOR_PHRASES:
            raise LabHarnessError(f"fp_operator: action must be one of {sorted(OPERATOR_PHRASES)}")
        with self._acting("fp_operator", {"action": action, "arm": arm, "evidence_id": evidence_id, "phrase": phrase}):
            eid = H.review(self.sim)
            if arm:
                self.set_switch("free_power_recovery_arm", True)
            use_id = evidence_id if evidence_id is not None else (eid or "")
            conf = phrase if phrase is not None else OPERATOR_PHRASES[action] + use_id
            accept = action == "ACCEPT_CURRENT_STATE"
            if accept:
                self._accept_watch = {"dom": "fp", "pre": self.obligations(), "texts": []}
            try:
                self.sim.run_actions(self.info.api["free_power_recovery_execute"]["then"],
                                     {"action": ds.CStr(action), "evidence_id": ds.CStr(use_id),
                                      "confirmation": ds.CStr(conf)})
                if accept:
                    self._adopt_if_clear("fp")
            finally:
                self._accept_watch = None
        return self.status("fp")

    def _adopt_if_clear(self, dom: str) -> None:
        """HL-1 (V0.1 root fix): after the operator Accept of `dom` that this action just ran, the lab ORIGINAL adopts the
        live bank only for the registers accept_adoption() grants (a SUCCESS result text published by this Accept, an
        obligation of `dom` held before it and cleared by it, never a register another domain holds). Records the
        decision in accept_log (in memory only: nothing is logged, so the EventLog changes only through the ORIGINAL
        that the next fw.quiet diff reads)."""
        watch = self._accept_watch
        if watch is None or watch["dom"] != dom:
            raise LabHarnessError(f"_adopt_if_clear({dom!r}) outside that domain's Accept action")
        res = accept_adoption(dom, watch["pre"], self.obligations(), watch["texts"])
        for a in res["adopt"]:
            self.original[a] = self.bank[a]
            self.foreign.discard(a)
        self.accept_log.append({"boot": self.boot_no, "t_utc": self.t_utc, "dom": dom, **res})

    def manual_slot_apply(self, slot: int, start_hhmm=None, end_hhmm=None, power_w=None, soc=None, charge_source=None,
                          mode=None, arm: bool = True) -> str:
        """The real Load button, staged edits, the arm, then the real Apply button (its ownership gate included)."""
        if slot not in range(1, 7):
            raise LabHarnessError(f"slot must be 1..6, got {slot!r}")
        args = {"slot": slot, "start_hhmm": start_hhmm, "end_hhmm": end_hhmm, "power_w": power_w, "soc": soc,
                "charge_source": charge_source, "mode": mode, "arm": arm}
        with self._acting("manual_slot_apply", args):
            self.press(f"load_manual_slot{slot}_staging")
            for f, v in (("start_hhmm", start_hhmm), ("end_hhmm", end_hhmm), ("power", power_w), ("soc", soc)):
                if v is not None:
                    self.set_number(f"manual_slot{slot}_{f}", v)
            for f, v in (("charge_source", charge_source), ("mode", mode)):
                if v is not None:
                    self.set_select(f"manual_slot{slot}_{f}", v)
            if arm:
                self.set_switch("manual_config_write_enable", True)
            self.press(f"apply_manual_slot{slot}_button")
        return str(self.sim.ent("manual_config_last_result").state)

    def r244_apply(self, target: str = "Allow Export", arm: bool = True) -> str:
        """The owner's register 244 Apply: the real Load button (load_reg244_staging), the staged target select
        (manual_reg244_staged_target), the master arm, then the real Apply button (apply_reg244_settings_button, its Free
        Power ownership gate included) - the sequence test_lab_fw_obligations.py r244_apply drove white-box (pattern from
        test_lab_selftest_firmware.py r244_apply)."""
        opts = self.info.entities["manual_reg244_staged_target"][1].get("options") or []
        if target not in opts:
            raise LabHarnessError(f"r244_apply: target must be one of {opts}, got {target!r}")
        if not isinstance(arm, bool):
            raise LabHarnessError(f"r244_apply: arm must be a bool, got {arm!r}")
        with self._acting("r244_apply", {"target": target, "arm": arm}):
            self.press("load_reg244_staging")
            self.set_select("manual_reg244_staged_target", target)
            if arm:
                self.set_switch("manual_config_write_enable", True)
            self.press("apply_reg244_settings_button")
        return self.status("r244")

    def r244_restore(self, arm: bool = True) -> str:
        """The owner's register 244 Restore: the master arm, then the real 'Restore Original Reg244' button
        (restore_reg244_button -> restore_reg244_snapshot, its Free Power / Dump ownership gate included; Phase C
        VERIFIED_PENDING_CLEAR then Phase D CLEAR, firmware :17788-17799). Replay action 'r244_restore' (B5: a reg244
        marker fault needs a completed reg244 Apply -> Restore earlier in the run)."""
        if not isinstance(arm, bool):
            raise LabHarnessError(f"r244_restore: arm must be a bool, got {arm!r}")
        with self._acting("r244_restore", {"arm": arm}):
            if arm:
                self.set_switch("manual_config_write_enable", True)
            self.press("restore_reg244_button")
        return self.status("r244")

    def owner_set_number(self, eid: str, value) -> None:
        """One logged world action (act.set_number): what a Home Assistant number.set_value call does - set_number()
        (range-checked against the firmware number's [min_value, max_value], its set_action, the optimistic publish,
        the restore_value save)."""
        self._number_node(eid, value)   # refuse before anything is logged
        with self._acting("set_number", {"entity": eid, "value": value}):
            self.set_number(eid, value)

    def inject_global(self, name: str, value) -> None:
        """WHITE-BOX RAM fault injection (a lab fault, not firmware behaviour): set firmware global `name` to `value` in
        the current sim's RAM, logged as fault.ram {name, type, value, old}. The value must fit the global's C type
        exactly (bool for bool; an int inside the integer type's range - never a silent wrap; a finite number for
        float / double; a str for std::string); array globals raise LabUnsupported. Nothing else is changed: a
        restore_value global then reaches flash through the normal preference jobs, as a RAM corruption would. It is
        NOT an injected-fault explanation for INV-RESTORE-BOUND (a leaked lock explains a late restore through the
        checker's own lock-hold rule)."""
        sim = self._need_sim()
        g = self.info.globals.get(name)
        if g is None:
            raise LabHarnessError(f"inject_global: unknown firmware global {name!r}")
        ctype = g["type"]
        if ctype == "bool":
            if not isinstance(value, bool):
                raise LabHarnessError(f"inject_global {name} (bool): a bool is required, got {value!r}")
            v = value
        elif ctype in ds._WIDTH:
            bits, signed = ds._WIDTH[ctype]
            lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise LabHarnessError(f"inject_global {name} ({ctype}): an int in [{lo}, {hi}] is required, got {value!r}")
            v = value
        elif ctype in ("float", "double"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise LabHarnessError(f"inject_global {name} ({ctype}): a finite number is required, got {value!r}")
            v = float(value)
        elif ctype == "std::string":
            if not isinstance(value, str):
                raise LabHarnessError(f"inject_global {name} (std::string): a str is required, got {value!r}")
            v = ds.CStr(value)
        else:
            raise LabUnsupported(f"inject_global {name}: global type {ctype!r} is not injectable")
        old = sim.g[name]
        sim.g[name] = v
        self._log("fault.ram", {"name": name, "type": ctype, "value": _jsonable(v), "old": _jsonable(old)})
        self._note_state()

    # -- observers -------------------------------------------------------------------------------------------------------
    def status(self, dom: str) -> str:
        if dom not in STATUS_IDS:
            raise LabHarnessError(f"status: dom must be one of {sorted(STATUS_IDS)}")
        return str(self.sim.ent(STATUS_IDS[dom]).state)

    def status_history(self, dom: str) -> list:
        if dom not in STATUS_IDS:
            raise LabHarnessError(f"status_history: dom must be one of {sorted(STATUS_IDS)}")
        return [e["data"]["text"] for e in self.log.events(kind="fw.status") if e["data"]["dom"] == dom]

    def ha_view(self) -> dict:
        """The HA-visible template binary sensors and counters, evaluated with their REAL lambdas."""
        out = {}
        for k, code in self.info.ha_lambdas.items():
            v = self.sim.run_lambda(code)
            out[k] = bool(v) if isinstance(v, bool) else (int(v) if float(v).is_integer() else float(v))
        return out

    def nvs_marker(self, dom: str) -> str:
        if dom not in MARKER_TAGS:
            raise LabHarnessError(f"nvs_marker: dom must be one of {sorted(MARKER_TAGS)}")
        return _marker_name(self.sim.nvs.get(MARKER_TAGS[dom]))

    def corrupt(self, dom: str) -> bool:
        names = {"fp": "free_power_recovery_metadata_corrupt", "dump": "dump_recovery_metadata_corrupt",
                 "r244": "reg244_recovery_metadata_corrupt"}
        if dom not in names:
            raise LabHarnessError(f"corrupt: dom must be one of {sorted(names)}")
        return bool(self.sim.g[names[dom]])

    def bank_view(self, addrs) -> dict:
        return {str(_reg(a)): self.bank.get(_reg(a)) for a in addrs}

    def writes(self) -> list:
        return [dict(w, vals=list(w["vals"])) for w in self._writes]

    def globals_view(self, names) -> dict:
        g = self.sim.g
        for n in names:
            if n not in g:
                raise LabHarnessError(f"unknown global {n!r}")
        return {n: _jsonable(g[n]) for n in names}

    def text_state(self, eid: str) -> str:
        """The current state of any firmware text_sensor (e.g. dump_recovery_state, free_power_recovery_last_action,
        ecco_restart_status); any other entity kind raises."""
        kind, _node = self.info.entities.get(eid, (None, None))
        if kind != "text_sensor":
            raise LabHarnessError(f"text_state: {eid!r} is not a firmware text_sensor")
        return str(self.sim.ent(eid).state)

    def invariants(self, names=None, *, boot_from=None, tags=None, untagged=False, form="list", **params):
        """check_invariants over the whole log (world given), then filter_violations(boot_from, tags, untagged, form)."""
        return filter_violations(check_invariants(self.log, names=names, world=self, **params), self.log,
                                 boot_from=boot_from, tags=tags, untagged=untagged, form=form)


# ---------------------------------------------------------------------------------------------------------------------------
# invariant checkers (over the EventLog; each returns [{inv, seq, detail, tags}])
# ---------------------------------------------------------------------------------------------------------------------------
def _events(events) -> list:
    return list(events) if not isinstance(events, list) else events


def _viol(inv: str, e: dict, detail: str, tags=()) -> dict:
    return {"inv": inv, "seq": e["seq"], "detail": detail, "tags": sorted(tags)}


def _span(e: dict) -> range:
    d = e["data"]
    return range(d["addr"], d["addr"] + len(d["vals"]))


def check_write_surface(events, **_kw) -> list:
    out = []
    for e in _events(events):
        if e["kind"] == "fw.write":
            bad = [a for a in _span(e) if a not in WRITE_SURFACE]
            nonu16 = [v for v in e["data"]["vals"] if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 65535]
            if bad or nonu16:
                out.append(_viol("INV-WS", e, f"write {e['data']['addr']} by {e['data'].get('dom')}: registers {bad} "
                                              f"outside the write surface, non-uint16 values {nonu16}"))
    return out


def check_one_lease(events, **_kw) -> list:
    out, inside = [], False
    for e in _events(events):
        obl = e["data"] if e["kind"] == "fw.obl" else e["data"].get("obl") if e["kind"] == "fw.booted" else None
        if obl is None:
            continue
        both = obl["fp"]["act"] and obl["dump"]["act"]
        if both and not inside:
            out.append(_viol("INV-ONE-LEASE", e, "Free Power and Dump to Grid both active_persisted"))
        inside = both
    return out


def check_no_second_restorer(events, **_kw) -> list:
    out = []
    for e in _events(events):
        if e["kind"] != "fw.write" or not set(_span(e)) & TOU_POWER:
            continue
        d = e["data"]
        for holder in ("fp", "dump"):
            if holder != d["dom"] and d["nvs"][holder] == "RESTORE_REQUIRED":
                tags = ["N17"] if d["ram"][f"{holder}_corrupt"] else []
                out.append(_viol("INV-NO-2ND-RESTORER", e, f"{d['dom']} wrote {d['addr']}x{len(d['vals'])} "
                                 f"({d['scripts'][-1] if d['scripts'] else 'no script'}) while {holder} holds a durable "
                                 f"RESTORE_REQUIRED marker", tags))
    return out


def check_no_resume(events, **_kw) -> list:
    out, armed, reported = [], set(), set()
    for e in _events(events):
        k = e["kind"]
        if k == "fw.booted":
            armed = {"fp", "dump"} if e["data"]["boot"] > 0 else set()
            reported = set()
        elif k == "fw.start":
            armed.discard(e["data"]["dom"])
        obl = e["data"] if k == "fw.obl" else e["data"].get("obl") if k == "fw.booted" else None
        if obl is None:
            continue
        for dom in sorted(armed - reported):
            if obl[dom]["run"]:
                reported.add(dom)
                out.append(_viol("INV-NO-RESUME", e, f"{dom} lease running (active, no restore request) after boot "
                                                     f"{e['boot']} without a new START"))
    return out


def check_lockout_quiet(events, **_kw) -> list:
    out = []
    for e in _events(events):
        if e["kind"] != "fw.write":
            continue
        d = e["data"]
        if d["addr"] == 244 and d["vals"] == [2]:
            continue  # SG-02 containment literal
        for dom, regs in DOMAIN_REGS.items():
            if d["ram"][f"{dom}_corrupt"] and set(_span(e)) & regs:
                out.append(_viol("INV-LOCKOUT-QUIET", e, f"{d['dom']} wrote {d['addr']} {d['vals'][:6]} while {dom} is "
                                                         f"corrupt-locked"))
    return out


def _world_log(world):
    log = getattr(world, "log", None) if world is not None else None
    return log if isinstance(log, T.EventLog) else None


def _log_prefix(evs: list, world) -> list | None:
    """The world-log events BEFORE a contiguous slice `evs` of world.log ([] when evs starts the log; the whole log for an
    empty slice, which is read as a slice at the end of the log; None when no world is given or evs is not a slice of
    world.log)."""
    log = _world_log(world)
    if log is None:
        return None
    if not evs:
        return list(log)
    s0 = evs[0].get("seq")
    if isinstance(s0, bool) or not isinstance(s0, int) or not 0 <= s0 < len(log) or log[s0] != evs[0]:
        return None
    return log[:s0] if s0 else []


def _reaches_log_end(evs: list, world) -> bool:
    """evs ends with the last event of world.log (or is empty while the world has a log): the world's state NOW is
    the state at the end of the slice."""
    log = _world_log(world)
    if log is None or not len(log):
        return False
    if not evs:
        return True
    s = evs[-1].get("seq")
    return not isinstance(s, bool) and isinstance(s, int) and s == len(log) - 1 and log[s] == evs[-1]


def check_no_silent_override(events, world=None, **_kw) -> list:
    """INV-NO-SILENT-OVERRIDE: at every STEADY point, owned registers that differ from the lab ORIGINAL (the fw.quiet
    diff; foreign registers excluded) need an obligation the firmware's RAM shows - a valid snapshot mirror
    ('<dom>.snap') or a corrupt / UNKNOWN lockout ('<dom>.corrupt'), fp / dump / r244. A stored NVS marker the RAM and
    status surface ignore (a ghost, a boot that dropped a stored RESTORE_REQUIRED) is NOT visible: the 'nvs.<dom>' entries
    of the logged fw.quiet record (kept in its V0 form) are ignored.
    Steady points (level-based, never inside a boot): every fw.quiet logged outside a boot (fw.quiet is only logged while no
    transaction lock is held); the settle point of every boot (fw.booted, merged with the fw.obl / fw.quiet records the
    post-boot state note logs at the same instant, so the state after the FULL on_boot is judged, never a transient from
    inside it); and the END of the slice. Records logged between fw.boot and fw.booted only update the tracked state.
    Slices: with `world`, a contiguous slice of world.log is pre-filled with the state before it (so a silent override
    that persists into the slice is reported at the slice's end even when the slice logs no new fw.quiet); when the slice
    reaches the end of world.log (or is empty), the end point is world.quiet_state() (the world's state now). Without a
    world, a slice holding no fw.quiet cannot be judged (the diff is unknown).
    One violation per episode: a steady point reports when it is silent and the previous steady point of the same boot was
    not silent with the same diff (a new boot starts a new episode, as the per-boot fw.quiet record did). seq = the
    fw.quiet record that holds the reported state when it lies inside the slice, else the evaluation point (the fw.booted
    or the last event). Tag PLATFORM-ABSENT once an injected false ABSENT / partition erase (fault.nvs_boot absent /
    erase_all) was seen (also before the slice)."""
    evs = _events(events)
    first_seq = evs[0]["seq"] if evs else None
    st = {"diff": None, "vis": [], "rec": None, "locked": False, "boot": False, "absent": False, "nvs": None}

    def update(e) -> None:
        k, d = e["kind"], e["data"]
        if k == "fault.nvs_boot" and d["fault"][0] in ("absent", "erase_all"):
            st["absent"] = True
        elif k == "fw.boot":
            st["boot"] = True
        elif k == "fw.booted":
            st["boot"], st["locked"], st["nvs"] = False, _is_locked(d["obl"]), d["obl"]["nvs"]
        elif k == "fw.obl":
            st["locked"], st["nvs"] = _is_locked(d), d["nvs"]
        elif k == "fw.quiet":
            st["diff"], st["vis"], st["rec"] = d["diff"], [v for v in d["visible"] if not v.startswith("nvs.")], e

    pre = _log_prefix(evs, world)
    for e in pre or []:
        update(e)
    out, episode = [], [None]

    def evaluate(point, diff, vis, locked, booting, where: str, rec, nvs=None) -> None:
        if diff is None or locked or booting:
            return
        if not diff or vis:
            episode[0] = None
            return
        key = T.canonical_json(diff)
        if key == episode[0]:
            return
        episode[0] = key
        in_slice = rec is not None and first_seq is not None and rec["seq"] >= first_seq
        nvs = {k: v for k, v in ((st["nvs"] if nvs is None else nvs) or {}).items() if v not in ("CLEAR", "ABSENT")}
        out.append(_viol("INV-NO-SILENT-OVERRIDE", rec if in_slice else point,
                         f"owned registers differ from ORIGINAL with no visible obligation: {diff}"
                         + (f" (stored markers the RAM ignores: {nvs})" if nvs else "") + f" [{where}]",
                         ["PLATFORM-ABSENT"] if st["absent"] else []))

    def same_note(point, e) -> bool:
        return e["kind"] in ("fw.obl", "fw.quiet") and e["boot"] == point["boot"] and e["up_ms"] == point["up_ms"]

    def steady(point) -> None:
        where = "boot settle point" if point["kind"] == "fw.booted" else "steady fw.quiet"
        evaluate(point, st["diff"], st["vis"], st["locked"], st["boot"], where, st["rec"])

    pending = None
    for e in evs:
        if pending is not None and not same_note(pending, e):
            steady(pending)
            pending = None
        if e["kind"] == "fw.boot":
            episode[0] = None
        update(e)
        if pending is None and (e["kind"] == "fw.booted" or (e["kind"] == "fw.quiet" and not st["boot"])):
            pending = e
    if pending is not None:
        steady(pending)
    if world is not None and callable(getattr(world, "quiet_state", None)) and _reaches_log_end(evs, world):
        q = world.quiet_state()
        rec = st["rec"]
        if rec is not None and (rec["data"]["diff"] != q["diff"] or st["vis"] != q["visible"]):
            rec = None   # the world's state now is not the last record's (a white-box edit): anchor at the end point
        evaluate(evs[-1] if evs else _world_log(world)[-1], q["diff"], q["visible"], q["locked"], q["booting"],
                 "end of the log: world.quiet_state()", rec, q["nvs"])
    elif evs:
        evaluate(evs[-1], st["diff"], st["vis"], st["locked"], st["boot"], "end of the slice", st["rec"])
    return out


# INV-BOOT-MIRROR: what the FULL on_boot must leave in RAM for each STORED marker state (firmware on_boot main lambda, the
# three marker blocks: RESTORE_REQUIRED with trusted data -> snapshot_valid; with untrusted data, the S4 / FP-Dump (PR41)
# dual-obligation arbitration or a corrupt lease-context field -> metadata_corrupt; PENDING_CLEAR -> snapshot_valid (the
# clear-only restore branch then completes the durable clear with zero Modbus I/O); a malformed record -> snapshot_valid +
# metadata_corrupt; an unreadable marker (NVS read error) -> snapshot_valid + metadata_corrupt, UNKNOWN). CLEAR / ABSENT
# need nothing.
BOOT_MIRROR_RULE = {"RESTORE_REQUIRED": ("snap", "corrupt"), "PENDING_CLEAR": ("snap", "corrupt"), "MALFORMED": ("corrupt",)}


def check_boot_mirror(events, **_kw) -> list:
    """INV-BOOT-MIRROR: at every fw.booted (after the FULL on_boot), each domain (fp, dump, r244) whose STORED NVS marker is
    RESTORE_REQUIRED or PENDING_CLEAR must be reflected in RAM by its snapshot_valid mirror or a corrupt / UNKNOWN lockout,
    and a MALFORMED one by the lockout (BOOT_MIRROR_RULE). Only boot states are judged: a ghost marker during the runtime
    that created it (PR41-GHOST: NVS RR while RAM is clear) is not a violation here; only its next boot is judged, where
    the dual-obligation arbitration locks the domains (a reflection, so no violation). One violation per domain per
    boot; seq = the fw.booted event; the detail names the domain's last status text."""
    out, status = [], {}
    for e in _events(events):
        k = e["kind"]
        if k == "fw.status":
            status[e["data"]["dom"]] = e["data"]["text"]
        if k != "fw.booted":
            continue
        obl = e["data"]["obl"]
        for dom in ("fp", "dump", "r244"):
            marker = obl["nvs"][dom]
            need = BOOT_MIRROR_RULE.get(marker)
            if need and not any(obl[dom][f] for f in need):
                out.append(_viol("INV-BOOT-MIRROR", e, f"boot {e['data']['boot']}: the stored {dom} marker is {marker} but "
                                                       f"the RAM mirror shows none of {list(need)} after the full on_boot "
                                                       f"(status {status.get(dom, '')[:80]!r})"))
    return out


_FAULT_KINDS = ("fault.modbus", "fault.nvs_commit", "fault.nvs_boot", "fw.power_off", "cut.fired")


def _long_locks(held: dict, since_t, t, wd_s) -> set:
    """The locks of `held` {name: held since t0} that were held for >= wd_s inside the due period [since_t, t]."""
    return {"lock:" + n for n, t0 in held.items() if t - max(t0, since_t) >= wd_s}


def check_restore_bound(events, world=None, bound_s: float = 60, wd_s: float | None = None, **_kw) -> list:
    """INV-RESTORE-BOUND (module docstring): a due restore (snapshot valid and: restore requested, not active, or
    end_epoch passed) must complete (snapshot cleared, NVS marker CLEAR / ABSENT) within bound_s of the first observation
    of the due state, unless a lockout, an injected fault, a down link / busy bus, or a lock other than the domain's own
    transaction held >= wd_s explains it. A due state that turns back into a valid, not-due snapshot (a START completing
    after its own mid-transaction due instant) discards the period; zero-length locks (a START's, the completing
    restore's) never explain."""
    evs = _events(events)
    out = []
    for dom, other in (("fp", "dump"), ("dump", "fp")):
        wd = float(wd_s) if wd_s is not None else (
            world.info.job[f"{dom}_wd"]["period_ms"] / 1000 if world is not None else 15.0)
        since, why, held, link_up, bus_idle = None, set(), {}, True, True
        for e in evs:
            k, t = e["kind"], e["t_utc"]
            if k == "env.link":
                link_up = bool(e["data"]["up"])
            elif k == "env.bus":
                bus_idle = bool(e["data"]["idle"])
            obl = e["data"] if k == "fw.obl" else e["data"].get("obl") if k == "fw.booted" else None
            if obl is not None:
                o = obl[dom]
                for name, on in (("mw", obl["mw"]), ("cip", obl["cip"]), ("r244.op", obl["r244"]["op"]),
                                 (f"{other}.op", obl[other]["op"])):
                    if on and name not in held:
                        held[name] = t
                    elif not on and name in held:
                        t0 = held.pop(name)
                        if since is not None:
                            why |= _long_locks({name: t0}, since["t_utc"], t, wd)
                if o["due"] and since is None:
                    since, why = e, set()
            if since is None:
                continue
            if k in _FAULT_KINDS:
                why.add(k)
            if not link_up:
                why.add("link down")
            if not bus_idle:
                why.add("bus busy")
            if obl is None:
                continue
            if o["corrupt"] or o["opn"]:
                why.add("lockout")
            if o["due"]:
                continue
            if o["snap"]:   # valid and no longer due: the lease runs again - not a restore obligation
                since = None
            elif obl["nvs"][dom] in ("CLEAR", "ABSENT"):   # completed
                why |= _long_locks(held, since["t_utc"], t, wd)
                took = t - since["t_utc"]
                if took > bound_s and not why:
                    out.append(_viol("INV-RESTORE-BOUND", since, f"{dom} restore due at {since['t_utc']} completed only "
                                                                 f"after {took:.0f} s (bound {bound_s} s), unexplained"))
                since = None
            # else: the RAM snapshot cleared but the durable marker is still set - not complete, the period stays open
        if since is not None:
            end_t = world.t_utc if world is not None else evs[-1]["t_utc"]
            why |= _long_locks(held, since["t_utc"], end_t, wd)
            if end_t - since["t_utc"] > bound_s and not why:
                out.append(_viol("INV-RESTORE-BOUND", since, f"{dom} restore due since {since['t_utc']} still open after "
                                                             f"{end_t - since['t_utc']:.0f} s (bound {bound_s} s), "
                                                             f"unexplained"))
    return sorted(out, key=lambda v: v["seq"])


INVARIANTS = {"INV-WS": check_write_surface, "INV-ONE-LEASE": check_one_lease,
              "INV-NO-2ND-RESTORER": check_no_second_restorer, "INV-NO-RESUME": check_no_resume,
              "INV-LOCKOUT-QUIET": check_lockout_quiet, "INV-NO-SILENT-OVERRIDE": check_no_silent_override,
              "INV-RESTORE-BOUND": check_restore_bound, "INV-BOOT-MIRROR": check_boot_mirror}
INVARIANT_FORMS = ("list", "count", "summary")


def check_invariants(events, names=None, world=None, **params) -> list:
    evs = _events(events)
    out = []
    for name in (names or list(INVARIANTS)):
        if name not in INVARIANTS:
            raise LabHarnessError(f"unknown invariant {name!r}")
        out += INVARIANTS[name](evs, world=world, **params)
    return out


def filter_violations(violations: list, events, *, boot_from=None, tags=None, untagged: bool = False, form: str = "list"):
    """Select and shape checker output (the 'invariants' observer's filters; an op-friendly, seq-free form for corpus files).
    boot_from (int >= 0): keep violations whose event (events[seq]) belongs to boot >= boot_from (an event before the
    first boot never does); tags (non-empty list of str): keep those carrying EVERY listed tag; untagged=True: keep those
    with no tag (not combinable with tags); form 'list' -> the violation dicts unchanged (in checker order), 'count' ->
    their number, 'summary' -> [{inv, tags, boot}, ...] in seq order (no seq / detail, so it survives event renumbering)."""
    if boot_from is not None and (isinstance(boot_from, bool) or not isinstance(boot_from, int) or boot_from < 0):
        raise LabHarnessError(f"invariants: boot_from must be an int >= 0, got {boot_from!r}")
    if tags is not None and (not isinstance(tags, (list, tuple)) or not tags
                             or not all(isinstance(t, str) and t for t in tags)):
        raise LabHarnessError(f"invariants: tags must be a non-empty list of str, got {tags!r}")
    if not isinstance(untagged, bool) or (untagged and tags is not None):
        raise LabHarnessError("invariants: untagged must be a bool and cannot be combined with tags")
    if form not in INVARIANT_FORMS:
        raise LabHarnessError(f"invariants: form must be one of {INVARIANT_FORMS}, got {form!r}")
    by_seq = None
    if boot_from is not None or form == "summary":
        if isinstance(events, T.EventLog):
            n = len(events)
            boot_of = lambda s: events[s]["boot"] if isinstance(s, int) and 0 <= s < n else None  # noqa: E731
        else:
            by_seq = {e["seq"]: e.get("boot") for e in _events(events)}
            boot_of = by_seq.get
    out = []
    for v in violations:
        if boot_from is not None:
            b = boot_of(v["seq"])
            if b is None or b < boot_from:
                continue
        if tags is not None and not set(tags) <= set(v["tags"]):
            continue
        if untagged and v["tags"]:
            continue
        out.append(v)
    if form == "count":
        return len(out)
    if form == "summary":
        return [{"inv": v["inv"], "tags": list(v["tags"]), "boot": boot_of(v["seq"])}
                for v in sorted(out, key=lambda v: v["seq"])]
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# replay tier 'firmware'
# ---------------------------------------------------------------------------------------------------------------------------
def make_world(*, utc_start: int, seed: int, **kw) -> FirmwareWorld:
    """The replay factory: JSON world kwargs (bank keys may be strings; dump_limits a list or 'factory')."""
    if "fw" in kw:
        raise LabHarnessError("replay worlds always run the worktree firmware")
    if "bank" in kw:
        kw["bank"] = {_reg(a): v for a, v in kw["bank"].items()}
    return FirmwareWorld(utc_start=utc_start, seed=seed, **kw)


def _a_reboot(w, down_s=5.0, nvs_fault=None, keep_prefs=True):
    w.reboot(down_s=down_s, nvs_fault=None if nvs_fault is None else tuple(nvs_fault), keep_prefs=keep_prefs)


def _a_cut(w, kind=None, key=None, addr=None, state=None, nth=1, down_s=5.0, nvs_fault=None, keep_prefs=True):
    w.arm_power_cut(kind=kind, key=key, addr=addr, state=state, nth=nth, down_s=down_s,
                    nvs_fault=None if nvs_fault is None else tuple(nvs_fault), keep_prefs=keep_prefs)


def _a_nvs(w, tag, state=None, mode="not_landed", times=1):
    w.nvs_policy(tag, state, mode=mode, times=times)


ACTIONS = {
    "fp_start": lambda w, **a: w.fp_start(**a), "fp_end": lambda w: w.fp_end(),
    "dump_start": lambda w, **a: w.dump_start(**a), "dump_end": lambda w: w.dump_end(),
    "dump_force_restore": lambda w, **a: w.dump_force_restore(**a), "dump_accept": lambda w, **a: w.dump_accept(**a),
    "fp_operator": lambda w, **a: w.fp_operator(**a), "manual_slot_apply": lambda w, **a: w.manual_slot_apply(**a),
    "run_for": lambda w, seconds, **a: w.run_for(seconds, **a), "advance": lambda w, seconds: w.advance(seconds),
    "reboot": _a_reboot, "arm_power_cut": _a_cut, "nvs_policy": _a_nvs,
    "modbus_policy": lambda w, table=None: w.modbus_policy(table), "set_link": lambda w, **a: w.set_link(**a),
    "set_bus_idle": lambda w, idle: w.set_bus_idle(idle), "set_register": lambda w, **a: w.set_register(**a),
    "telemetry": lambda w, **a: w.telemetry(**a), "config_poll": lambda w: w.config_poll(),
    "rtc_lock_windows": lambda w, windows: w.rtc_lock_windows(windows),
    "set_number": lambda w, entity, value: w.owner_set_number(entity, value),
    "inject_global": lambda w, name, value: w.inject_global(name, value),
    "r244_apply": lambda w, **a: w.r244_apply(**a),
    "r244_restore": lambda w, **a: w.r244_restore(**a),
}
OBSERVERS = {
    "status": lambda w, dom: w.status(dom), "status_history": lambda w, dom: w.status_history(dom),
    "ha_view": lambda w: w.ha_view(), "nvs_marker": lambda w, dom: w.nvs_marker(dom),
    "corrupt": lambda w, dom: w.corrupt(dom), "bank": lambda w, addrs: w.bank_view(addrs), "writes": lambda w: w.writes(),
    "globals": lambda w, names: w.globals_view(names), "obligations": lambda w: w.obligations(),
    "invariants": lambda w, names=None, **p: w.invariants(names, **p), "t_utc": lambda w: w.t_utc,
    "boot_no": lambda w: w.boot_no, "text_state": lambda w, entity: w.text_state(entity),
    "quiet_state": lambda w: w.quiet_state(),
}
T.register_tier(TIER, make_world)
T.register_actions(TIER, ACTIONS)
T.register_observers(TIER, OBSERVERS)
