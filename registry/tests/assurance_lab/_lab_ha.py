"""Assurance lab V0: CoupledWorld - the REAL Home Assistant schedule packages (FPS1 / DGS1 / SMR1) run by the
home-assistant/tests/_ha_script_sim.py interpreter, coupled to the REAL dongle firmware (_lab_fw.FirmwareWorld over
registry/tests/_dump_sim.py) through ONE adapter, RealDongle, on one UTC-true timeline (test-only helper: no network, no
Home Assistant, no hardware; it reads repository files and writes nothing).

Nothing here decides what Home Assistant or the firmware does. The packages' own scripts / automations / templates make
every HA decision; the firmware's own scripts, intervals and template lambdas make every dongle decision. The lab supplies
the clock, the latencies, the bus / link / power environment, and the projection of the synchronous firmware runs onto the
HA clock (the MODEL ASSUMPTIONS below). The two hand-written dongle models (S.Dongle, D.DumpDongle) are NOT used.

PUBLIC API
  constants  TIER ('coupled'); PACKAGES {fps1 | dgs1 | smr1: repo path}; RUNTIME_CONFIG_REL; LIMIT_SENSOR_NAME; E_LIMIT,
             E_CEILING, E_OPERATING_LIMIT; DOMS ('fp', 'dump'); per-domain HA ids ARMED, START_HELPER, DURATION_HELPER,
             POWER_HELPER, STOP_SOC_HELPER, LAST_RESULT, SCHEDULE_STATUS, SCRIPT, SMR1_STATE, ACTIVE, ARM, NUMBERS; firmware
             button ids START_BUTTON / END_BUTTON; FW_ACTIONS (the firmware environment / fault actions fw_action() accepts);
             SOURCE_ANCHORS [(path, text)] (the self-test re-counts each, exactly once)
  errors     LabHarnessError / LabUnsupported (the _lab_fw classes, re-exported); S.Unsupported for an unmapped dongle
             entity; S.ServiceError for a call to an offline dongle under offline_policy='raise'
  Latency(press_s=(0.117,), cmd_s=0.03, publish_s=0.12, op_s=0.58, commit_s=0.01, no_response_s=2.0, timeout_s=3.0)
             frozen; see MODEL ASSUMPTIONS ('Projection': the duration of one projected Modbus op by its outcome)
  BusModel(phase_s=0.0, windows='measured' | 'polls' | [(utc_a, utc_b), ...])  .busy(utc, polls=()) -> bool
  ha_slug(name) -> str; dongle_entity_map(fw=None) -> {HA entity id: (firmware id, kind)}; package_text(name) -> str;
  package_dongle_ids(texts) -> sorted [HA id] (every dongle entity id the given package texts use, the 12 assembled TOU slot
  ids included); tou_text(what, raw) -> str; limit_template() -> str
  class CoupledFirmware(L.FirmwareWorld)  + recorder hooks, next_due_ms(), sync_to(t_ms) (live), raw_to(t_ms) (raw),
                                           capture_now(), command(name, args, fn) (one firmware world action)
  class RealDongle    the adapter (built by CoupledWorld): .entity_map, .commands {HA id: (fid, kind)} (switch / number /
                      button), .view {HA id: spec} (every HA-read dongle id: src entity | lambda | polled | tou), .connected,
                      .down {link-down reason: count} (ha | power | api), .off (unpowered), .busy_t0 / .busy_until /
                      .busy_scripts (the open projected transaction), .busy_own_end {script: UTC end of that script's own
                      last op / commit / in-lock delay in it}, .busy_v0_until (where the V0 projection, every op op_s and
                      no delay, ended the same window), .counts (this world's DIVERGENCE_COUNTS), .pending_until (the
                      latest scheduled HA delivery: the HA view is quiescent once the World clock passes it),
                      entry(cmd=None, fn=None) (firmware work now; LabUnsupported inside a busy window),
                      press_scripts(fid), full_view(), ha_visible(), warm_up(seconds) (the fw_world_kwargs warmup_s run,
                      called by CoupledWorld)
  class CoupledWorld(utc_start: int, *, packages=('fps1', 'dgs1', 'smr1'), package_texts=None, london=True,
                     fw_world_kwargs=None, latencies=None, offline_policy='silent' | 'raise', bus=None, wd_phase_s=0.0,
                     grid_charge_limit_w=8000, reconnect_gap_s=10.0, seed=0)
      one open CoupledWorld per process at a time (S.LOCAL and the sim modules are process-global); with london=True it
      is built inside _lab_clock.patched_ha_local(S); close() / `with` restore S.LOCAL (also when construction or the
      body raises)
    state     w (S.World), ha (S.HA, replaced by restart_ha), ha_up, fw (CoupledFirmware), dongle (RealDongle), log (the
              merged T.EventLog = fw.log), lat, bus, offline_policy, t_utc
    clock     run_until(utc), run_for(seconds), advance_to(utc) (the replay world protocol)
    actors    arm_schedule(dom, start_local 'YYYY-MM-DD HH:MM:SS', minutes, power_w, stop_soc=None, at_utc=None);
              owner_set(entity, value, at_utc=None, via='ha' | 'dongle'); owner_press(button, at_utc=None, via='ha' |
              'dongle'); restart_ha(at_utc, down_s, rollback_to_utc=None, clear_notifications=True, reconnect_gap_s=10.0,
              reset_last_changed=True); reboot_dongle(at_utc, down_s=5.0, nvs_fault=None, reconnect_gap_s=None);
              api_outage(at_utc, down_s); set_env(at_utc=None, **telemetry values); fw_action(name, at_utc=None, **args);
              dump_plant(house_w=50, soc_drop_s=180, period_s=5) (MODEL plant stand-in, see MODEL ASSUMPTIONS)
              (at_utc None = now, else scheduled on the World clock)
    observers schedule_status(dom), last_result(dom), smr1_state(dom), notifications(), ha_state(entity), ha_visible(),
              firmware(), fw_status(dom), invariants(names=None, params=None, **flat) (INV-HF-* and / or firmware ids,
              None = every INV-HF-*; parameters routed per invariant, see below), window_overruns()
  coupled invariant checkers (events: an EventLog or a list; each returns [{inv, seq, detail, tags}])
      check_hf_one_lease (INV-HF-ONE-LEASE: never both leases - firmware truth via L.check_one_lease, and the HA view of
      the two Active binary sensors); check_hf_arm_off(grace_s=10) (INV-HF-ARM-OFF: no write enable left on for more than
      grace_s while its scheduled start script is off, unless the owner armed it); check_hf_smr1_quiet (INV-HF-SMR1-QUIET:
      an SMR1 number write reaches the firmware only while firmware truth shows no op / active / snapshot for that domain);
      check_hf_window(bound_s=30) (INV-HF-WINDOW: the firmware override of a scheduled run ends within window_end +
      bound; window_overruns(events, world) records every measured overrun); check_hf_owner_intent (INV-HF-OWNER-INTENT:
      no new firmware lease from a schedule START press after the owner's End / disarm of that run); check_hf_no_false_
      success (INV-HF-NO-FALSE-SUCCESS: SMR1 never says RESTORED while the owner's pre-schedule value is not on the
      number); HF_INVARIANTS; check_hf_invariants(events, names=None, world=None, params=None, **flat)
      parameters (check_hf_invariants and CoupledWorld.invariants): params={inv id: {name: value}} sets one invariant's
      parameters; a flat keyword (bound_s=45) goes to the ONE selected checker that names it. Params for an unselected
      invariant, a name its checker does not take, a flat name that no selected checker or more than one takes (bound_s
      with INV-HF-WINDOW and INV-RESTORE-BOUND selected) raise LabHarnessError: nothing is dropped silently
  fail-loud guards (see FAIL-LOUD GUARDS)
             ignored_options(docs, runtime_config=None) -> [str] (pure: every construct of the parsed packages {name:
             doc} / of the runtime-config doc that _ha_script_sim or this lab would silently ignore); check_packages(texts)
             (raises LabUnsupported listing them; CoupledWorld runs it on every package set it loads);
             DIVERGENCE_COUNTS (process totals, never reset) / divergence_counts() -> a copy: the measured occurrences of
             the silent-divergence register (own-op-pending drops, nested-only refusals, refused interleavings and those
             in the projection gap, fault / delay transactions, guard checks and refusals)
  replay     tier 'coupled' is registered with _lab_trace at import: make_world(*, utc_start, seed, **kw) (JSON kwargs:
             latencies / bus dicts, fw_world_kwargs with string bank keys; 'fw' and package_texts are refused), ACTIONS
             (arm_schedule, owner_set, owner_press, restart_ha, reboot_dongle, api_outage, set_env, fw_action, run_for),
             OBSERVERS (schedule_status, last_result, smr1_state, notifications, ha_state, ha_visible, fw_status,
             fw_ha_view, bank, nvs_marker, writes, invariants, window_overruns, t_utc, boot_no)

MERGED EVENT LOG (one T.EventLog: the firmware's own events plus)
  ha.state {e, s} (every HA state change) and ha.call {svc, e, data, by} (every service call, by = owner | schedule |
  smr1 | ha), src 'ha'; ha.stop / ha.start / ha.rollback / ha.notifications_cleared / ha.last_changed_reset; owner.arm /
  owner.set / owner.press; dongle.cmd {svc, e, fid, kind, value, by, obl, mw, old} (a command reaching the firmware),
  dongle.dropped {svc, e, why}, dongle.txn {t0, until, ops, commits, writes, scripts, cmd[, projection {no_response,
  timeout, delay_ms, v0_until}: only when a fault outcome or an in-lock delay made the window differ from V0]},
  dongle.edge {dom, act, snap, at, boot} (a lease flag change at its projected instant `at`), dongle.link {up, reason},
  dongle.power_off / power_on /
  self_restart, env.bus {idle, source} (the FirmwareWorld kind, logged on the World clock), env.plant; src 'lab'. Lab and
  HA events carry t_utc = the World clock rounded to the ms; the log is UTC-monotonic (the self-test checks it), except
  across a dongle reboot (NOT MODELLED).

MODEL ASSUMPTIONS (lab choices; HA-side ones marked ASSUMPTION are INFERRED Home Assistant behaviour, not measured)
  - Clock: firmware time follows the World clock: before every firmware call the FirmwareWorld runs LIVE up to w.t
    (sync_to). A self-rescheduling World.at driver wakes at the firmware's next due job instant (the FirmwareWorld
    scheduler's own interval table), at every polled-sensor sample instant and at the end of a busy window. The watchdog
    phase relative to the HA clock is wd_phase_s (extra first-run delay of both 15 s watchdogs, phase_ms; sweepable).
  - Projection: a firmware run (a press at its gate instant t0, a switch / number command, a driver tick) executes
    synchronously at t0 (ds.Sim: waits are no-ops, _dump_sim.py:1513). It is a TRANSACTION when it wrote a register, or did
    a Modbus op / NVS commit / explicit delay while a transaction lock (FP / Dump operation, manual write, reg244 apply)
    was held. Its effects are projected onto the World clock: the stretch after an op, commit or in-lock delay ends at t0
    + the summed durations so far. Durations: a Modbus op by its outcome (the ds.Sim event's outcome, _dump_sim.py:1571
    write / :1588 read) - no_response / no_response_landed / no_response_lost no_response_s 2.0 s (the ESPHome 2026.8.2
    hub's send-wait expiry: modbus/__init__.py:56 CONF_SEND_WAIT_TIME default "2000ms", modbus.h:319 send_wait_time_
    {2000}, modbus.cpp:62-65 expire_waiting_() at last_send_tx_offset_ + send_wait_time_; the firmware's modbus: block
    sets no send_wait_time, firmware :1716-1719 and the comment at :16995 '2000ms default, unmodified'), timeout /
    timeout_landed / timeout_lost timeout_s 3.0 s (no callback fires, _dump_sim.py:1576-1578 / :1589-1590, so the
    firmware waits out its bounded wait_until, 'timeout: 3000ms', e.g. firmware :8937), every other outcome op_s; a commit
    commit_s; an explicit `delay:` action executed while a transaction lock is held its own length (observed per instance
    through the sim's run_actions, CoupledFirmware; ds.Sim itself skips it, _dump_sim.py:1513) - a lock-free delay keeps
    zero projected duration (NOT MODELLED). With no fault outcome and no in-lock delay the sum is exactly the V0
    k*op_s + c*commit_s. An explicit publish (text sensor, switch turn_on / turn_off, number, published binary sensor /
    sensor) keeps its order; template binary sensors (their REAL lambdas) and the TOU slot sensors are sampled at the end
    of each stretch; HA sees each state publish_s later (a newer publish of an entity is never overwritten by an older one
    landing later). busy_until = the end of the LAST op / commit / in-lock delay done under a lock (or a write): lock-free
    reads after it (START's closing poll_inverter_configuration, which ESPHome runs as a separate script) are projected but
    do not hold the window. Inside a busy window periodic firmware work is DEFERRED to busy_until (the firmware clock moves
    RAW over the window, so its job slots there run once at busy_until), and ANY dongle mutation (switch, number, press,
    set_env, fw_action, power cut) raises LabUnsupported, with ONE exception: a press of a button whose on_press is only
    script.execute of scripts that are all in the window (busy_scripts), all `mode: single`, and whose OWN work (their
    own last op / commit / in-lock delay as the top of the script stack, busy_own_end) is still pending at the press, is
    DROPPED (logged dongle.dropped busy_same_script, counted): ESPHome's SingleScript drops a run while is_action_running()
    (script.h:77-87). When a pressed script is in the window only through a nested script.execute (its own work has
    ended; the lab's ds.Sim keeps the caller on the stack, _dump_sim.py:1539-1547, but ESPHome's script.execute does not
    block the caller, core/automation.h:489-493, script.h:239) the device WOULD run it: LabUnsupported (MISS-HA-1),
    never a silent drop. Non-transaction runs (polls) publish with zero projected duration.
  - Latency defaults and where they were measured: press_s 0.117 s (press -> gate, measured 6 Oct 2026, _ha_dump_sim.py:13
    'the gate answered 0.117 s'; the FPS1 incident measured 0.6 / 0.1 s, test_ecco_free_power_schedule_reliability.py:77
    INCIDENT_DELAYS); op_s 0.58 s per Modbus op (the 6 Oct Dump START took 4.07 s, _ha_dump_sim.py:14, for its 7 ops, the
    reconciliation probe count; S.Dongle's 6.0 s FP transaction is a model value, _ha_script_sim.py:777); publish_s 0.12 s
    (S.Dongle's publish default, _ha_script_sim.py:776, a model value); cmd_s 0.03 s (service -> firmware for a switch /
    number, S.Dongle._switch, _ha_script_sim.py:887, a model value); commit_s 0.01 s (NVS commit, adapter sketch, model);
    no_response_s 2.0 s and timeout_s 3.0 s (device constants, cited under Projection; the turnaround / frame time on top
    of them is not added). One op_s for both domains (the only measured figure).
  - Bus: the firmware's tx_buffer_empty / tx_blocked (one ds.Sim bus_idle flag, _dump_sim.py:484-488) follows the BusModel
    at every firmware entry: 'measured' (the default) = S.Dongle.bus_busy (the 11 Oct HA-side busy windows BUSY_10S /
    BUSY_60S, _ha_script_sim.py:753-754, shifted by phase_s, on the UTC clock); 'polls' = busy while one of the lab's own
    firmware runs does its projected Modbus ops [t0, t0 + ops*op_s) (self-consistent with the lab firmware's poll
    schedule); or explicit absolute UTC windows ([] = never busy). It also defers the firmware's own restore paths ('END
    DEFERRED - Modbus bus busy'), and it is sampled at entry instants only. With 'measured' at phase 0 the lab's watchdog
    slots (boot at a whole second, boot_ms 2000: x3 s) fall inside BUSY_10S every other tick: the window-end overrun then
    depends on the phases (the self-test reports it; HF-01 sweeps it).
  - Plant (dump_plant, MODEL, opt-in): FirmwareWorld has no inverter physics, so a static telemetry image ends a Dump lease
    early (the controller sees no effective grid response, or a battery power above its ceiling). dump_plant makes the
    battery follow the ceiling the controller writes into register 256 while a lease exports (244 == 0), grid = house -
    battery, and drops the SOC 1 % per soc_drop_s of discharge (the frozen-SOC detector needs a moving SOC).
  - HA-visible dongle entities are published from firmware truth, only on change: template binary sensors through their
    REAL lambdas (the same lambdas FirmwareWorld.ha_view runs); text sensors, switches, numbers (with min / max / step
    attributes from the firmware node) and published binary sensors / sensors from their entity state; polled template
    sensors (the attempt counters, 30 s; the TOU power ceiling, 60 s) sampled at uptime multiples of their update_interval
    (first sample one period after power-on, INFERRED ESPHome PollingComponent phase) and published ONLY from a sample:
    before a boot's first sample they have no state, so world start, a reconnect after a dongle reboot and a dongle
    restart publish 'unknown' (INFERRED: ESPHome reports a sensor without a state as missing, HA shows 'unknown'), never
    the live lambda; a fw_world_kwargs warm-up samples on the same grid (RealDongle.warm_up); the 12 TOU slot sensors
    (DGS1's arm-time walk) from the firmware's manual_cfg_reg250..255_raw / 274..279_raw cache once Block B has landed
    (cfg_block_b_seq > 0), formatted with the firmware's own format_time / charge_source rules (MODEL: the lab's Block B
    handler does not run the display publishes). HA states: 'on' / 'off'; f'{float}' for numbers / sensors (NaN ->
    'unknown'); text as is ('' -> 'unknown'); 'unavailable' while the API link is down.
  - Effective grid charge limit: sensor.ecco_config_maximum_grid_charge_power is the REAL state + availability template of
    home-assistant/packages/ecco_runtime_config.yaml (extracted by name, rendered on read; that package cannot load in the
    sim), over the firmware's own 'Inverter TOU Power Ceiling' lambda (published) and a synthetic
    input_number.ecco_max_grid_charge_power = grid_charge_limit_w (default 8000 W, NOT a site value). Its template block
    is trigger-based (homeassistant start, a 5 min time_pattern, state changes of three entities, ecco_runtime_config.yaml
    :14-23): HA renders it on those triggers and keeps the value in between. Render-on-read gives the same value because
    its state and availability templates read only the dongle ceiling sensor and the operating-limit helper, both
    watched by the block's state trigger; the static guard (FAIL-LOUD GUARDS) re-checks that condition at every load.
  - Offline: a service call while the API link is down is dropped silently (offline_policy='silent', ASSUMPTION: HA's
    entity service call skips an unavailable ESPHome entity) or raises S.ServiceError (offline_policy='raise', the
    _ha_dump_sim.py:15 ASSUMPTION); a command in flight when the link drops is lost. A whole-view republish follows every
    reconnect (ESPHome sends every state at connect; polled sensors send their last sample of this boot, or 'unknown').
  - restart_ha (ASSUMPTIONS): graceful stop = S.HA.stop() (the World keeps every state, i.e. HA's restore-state at a clean
    stop); crash = rollback_to_utc: every package helper (input_*) is rolled back to its value at that instant (HA saves
    restore-state every 15 minutes and at a clean stop, ecco_schedule_manual_restore.yaml:37 / docs/dev/schedule-manual-
    restore.md:71); persistent notifications are cleared at start (not restored by HA); restored helpers' last_changed is
    the start instant (HA writes fresh state objects); dongle entities read 'unavailable' from HA start until the ESPHome
    reconnect reconnect_gap_s later.
  - reboot_dongle: a power cut at at_utc (state captured there, entities unavailable at once), the power back at at_utc +
    down_s, on_boot boot_ms later (FirmwareWorld.reboot_from: FULL on_boot, RAM fresh, ALWAYS_OFF arms OFF, attempt
    counters 0 in RAM, HA 'unknown' until the new boot's first 30 s sample), the API back reconnect_gap_s after on_boot
    (ASSUMPTION). A firmware-initiated restart (its restart button, or a cut armed with fw_action('arm_power_cut')) inside
    an entry takes the same offline path from the firmware's new boot.
  - Time triggers: after ha.start() and after every input_datetime write each automation's schedule_time_triggers() (the
    sim helper, _ha_script_sim.py:690, otherwise never called) puts the exact trigger instant on the World queue, so a start
    with seconds (12:00:30) fires at that second (the self-test proves it); without it the sim fires only when a poll lands
    within 1 s after the instant (_ha_script_sim.py:674).
  - Call attribution ('by'): a per-instance wrapper of each S.HA instance's _action tags a service call 'smr1' (variables
    hold plan / schedule_value), 'schedule' (requested_duration) or 'ha' (pattern from home-assistant/tests/
    test_ecco_schedule_manual_restore.py:100-112, which patches the class; here the instance); the owner helpers tag
    'owner'. The World's set / call are wrapped per instance (logging, time-trigger rescheduling); nothing is patched
    class-wide.

FAIL-LOUD GUARDS (ISS-HA-5: options the unmodified _ha_script_sim would silently ignore; the Home Assistant semantics
named here are REPORTED, not verified - Home Assistant is not installed in this lab)
  - Static, at package load (check_packages on every package set a CoupledWorld loads, and on ecco_runtime_config.yaml's
    limit sensor at limit_template()): LabUnsupported naming every construct the interpreter or this lab would not read -
    `enabled:` on any action, condition or trigger (the sim drops the key, _ha_script_sim.py:486, and never reads it on
    conditions / triggers: HA skips a disabled one); a state trigger with for / from / not_from / not_to / attribute or any
    key beyond trigger / entity_id / to / id / alias, a `to:` list (the sim compares str(list), :683) or no `to:` (HA also
    fires on attribute-only changes); a state condition with for / attribute / match or any key beyond condition /
    entity_id / state / alias, or an entity_id list (:571-574); a template trigger with for:, an event trigger with
    event_data or a list event_type, a homeassistant trigger other than start, a time trigger whose `at:` is not a
    date+time input_datetime of the loaded packages (a time-only helper never fires in the sim, :671-672); a condition
    shorthand string; per action kind (the sim's dispatch order, :486-560) any key it does not read (e.g. a target other
    than entity_id, data_template, stop error / response_variable, continue_on_error outside a service / script call);
    automation keys beyond id / alias / description / mode / max / triggers / conditions / actions (variables,
    trigger_variables, initial_state, singular trigger / condition / action are not read; max_exceeded only sets a log
    level and is allowed); script keys beyond alias / description / mode / sequence / variables / fields / icon /
    max_exceeded and field keys beyond name / description / example / selector; template-sensor keys beyond name / state /
    unique_id / icon / attributes (attributes only while no loaded package reads them: the sim renders state alone, :358);
    helper keys the sim does not apply (input_text pattern, a min length > 0); in ecco_runtime_config.yaml an automation /
    script (the lab loads none), any top-level key but template, a limit-sensor key beyond name / unique_id / state /
    availability / unit_of_measurement / device_class / state_class / icon / unread attributes, or a trigger-based block
    whose value render-on-read would not reproduce (see 'Effective grid charge limit').
  - Runtime, per open CoupledWorld: (1) template truthiness - while the world is open S._truthy (:91-94, the only
    truthiness of condition: template, wait_template and template triggers) is wrapped (restored by close()) and raises
    LabUnsupported when the sim's answer differs from HA's condition rule (the stripped render lowercased == 'true'):
    'on' / 'yes' / '1' / 'enable', a non-zero number, a non-empty list; a template TRIGGER would accept those as HA does
    (result_as_boolean), so for triggers the guard is conservative (it refuses, never passes a divergence); (2)
    input_number.set_value - World.service_handlers (consulted first, :289) gets a handler that refuses (LabUnsupported) a
    value outside the declared [min, max] of a loaded package helper (HA refuses it; the sim's default handler, :301-302,
    stores it), and otherwise stores exactly what the default handler stores; a write to an input_number no loaded
    package declares is stored unchecked and counted ('input_number_unranged').
  - Counted in DIVERGENCE_COUNTS (process totals) and RealDongle.counts (this world).

NOT MODELLED (anchors are text snippets; line numbers at writing)
  - Interleaving inside a firmware transaction (fail loud instead, see Projection), Modbus latency beyond the per-outcome
    op durations (no turnaround / frame time, no queueing behind another transaction), a lock-free poll's own duration
    for the commands that follow it (a lock-free `delay:` included), a nested script.execute running CONCURRENTLY with its
    caller (the lab runs it synchronously inside the caller, FWA-01; a same-script press it would hide is refused, see
    Projection), ESPHome loop / template-sensor evaluation order beyond 'explicit publishes first, lambda sensors at the
    stretch end', inverter physics (dump_plant is a stand-in).
  - Everything FirmwareWorld does not execute (_lab_fw NOT_EXECUTED / PARTIAL / NOT_EXECUTED_BOOT / MODEL_HANDLERS).
  - HA: real ESPHome reconnect timing / backoff, API stalls, HA restart ordering beyond stop / start, automation reload,
    `initial:` overriding restore (no shipped helper of the three packages declares one), number min / max / step
    validation by HA (out-of-range values are refused loudly by FirmwareWorld.set_number), the interpreter's own
    NOT-MODELLED list (home-assistant/tests/_ha_script_sim.py:1-19; e.g. mode: restart runs concurrently, :702-726).
  - A power cut between a projected transaction's ops (use the firmware tier's arm_power_cut sweeps), a torn NVS record.
  - Event-log order across a dongle reboot: FirmwareWorld logs fw.power_off with the power-return instant when the new boot
    runs, boot_ms later; an HA event inside that gap precedes it (EventLog.utc_regressions lists it). A firmware-initiated
    restart logs its boot ahead of the World clock likewise.

SOURCE ANCHORS (SOURCE_ANCHORS; test_lab_selftest_coupling re-counts each, exactly once; line at writing)
  home-assistant/tests/_ha_script_sim.py
    :32   'LOCAL = timezone(timedelta(hours=1))'                (fixed UTC+1; patched to LONDON with london=True)
    :674  'if w.t >= when and key not in self._time_fired and w.t - when < 1.0:'   (time triggers need a poll)
    :690  'def schedule_time_triggers(self):'                   (the exact-instant helper this lab calls)
    :753  'BUSY_10S = ((2.38, 3.15), (4.88, 5.62))'             (the measured bus windows BusModel reuses)
    :776  'def __init__(self, world: World, phase: float = 0.0, handle_delays=(0.15,), publish: float = 0.12,'
    :887  'self.w.after(0.03, lambda: self._set_arm(on))'       (cmd_s)
    :93   'return value.strip().lower() in ("true", "on", "yes", "1", "enable")'   (_truthy: the runtime truthiness guard)
    :302  'handler = lambda e, d: self.set(e, f"{float(d['value'])}")  # noqa: E731'   (input_number: no range check)
    :486  'keys = set(act) - {"alias", "enabled", "continue_on_error"}'   (enabled: dropped: the static guard)
    :573  'if self.w.state(c["entity_id"]) not in [str(x) for x in want]:'   (state condition: entity_id / state only)
    :683  'want = tr.get("to", new[0])'                         (state trigger: entity_id / to only)
  home-assistant/tests/_ha_dump_sim.py
    :13   'HA pressed at +2.019 s, the gate answered 0.117 s'   :14 'later, the transaction took 4.07 s.'
    :15   'a call to a dongle entity while the dongle is offline raises in Home Assistant'
  home-assistant/tests/test_ecco_free_power_schedule_reliability.py  :77 'INCIDENT_DELAYS = (0.6, 0.1)'
  home-assistant/tests/test_ecco_schedule_manual_restore.py  :108 'SOURCE[0] = "restore" if "plan" in v else'
  home-assistant/packages/ecco_runtime_config.yaml  :80 '- name: ECCO Config Maximum Grid Charge Power'
  home-assistant/packages/ecco_dump_to_grid_schedule.yaml  :604 the assembled TOU id (ASSEMBLED_TOU[0])
  home-assistant/packages/ecco_schedule_manual_restore.yaml  :37 '# Home Assistant saves restored states every 15 minutes'
  firmware/ecco_clock_dongle_stage3_4_free_power.yaml
    :7009  'return (float) ${ecco_inverter_tou_power_ceiling_w};'   :7156 'return (float) id(free_power_start_attempts);'
    :16681 'auto format_time = [](uint16_t raw) -> std::string {'   :16724 'case 1: return std::string("Grid");'
    :16995 "shorter than the hub's send_wait_time (2000ms default, unmodified"   (no_response_s 2.0 s)
    :8941  'ESP_LOGE("free_power", "Snapshot regs230-232 read did not reach a terminal state within the bounded wait");'
           (four lines below the 'timeout: 3000ms' bound at :8937: timeout_s 3.0 s)
  registry/tests/_dump_sim.py  :1513 'elif kind in ("wait_until", "delay", "logger.log"):'  (synchronous scripts)
    :1543 'self.running.add(script_id)'                         (a nested script.execute keeps its caller running)
"""
from __future__ import annotations

import inspect
import math
import re
import sys
import types
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yaml  # noqa: E402
import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _dump_sim as ds  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402

LabHarnessError = L.LabHarnessError
LabUnsupported = L.LabUnsupported
TIER = "coupled"

PACKAGES = {"fps1": "home-assistant/packages/ecco_free_power_schedule.yaml",
            "dgs1": "home-assistant/packages/ecco_dump_to_grid_schedule.yaml",
            "smr1": "home-assistant/packages/ecco_schedule_manual_restore.yaml"}
RUNTIME_CONFIG_REL = "home-assistant/packages/ecco_runtime_config.yaml"
LIMIT_SENSOR_NAME = "ECCO Config Maximum Grid Charge Power"
E_LIMIT = S.E_LIMIT
E_CEILING = f"sensor.{S.P}inverter_tou_power_ceiling"
E_OPERATING_LIMIT = "input_number.ecco_max_grid_charge_power"
DOMS = ("fp", "dump")
_PKG_OF = {"fp": "fps1", "dump": "dgs1"}
ARMED = {"fp": "input_boolean.ecco_free_power_schedule_armed", "dump": "input_boolean.ecco_dump_to_grid_schedule_armed"}
START_HELPER = {"fp": "input_datetime.ecco_free_power_schedule_start",
                "dump": "input_datetime.ecco_dump_to_grid_schedule_start"}
DURATION_HELPER = {"fp": "input_number.ecco_free_power_schedule_duration",
                   "dump": "input_number.ecco_dump_to_grid_schedule_duration"}
POWER_HELPER = {"fp": "input_number.ecco_free_power_schedule_power", "dump": "input_number.ecco_dump_to_grid_schedule_power"}
STOP_SOC_HELPER = {"dump": "input_number.ecco_dump_to_grid_schedule_stop_soc"}
LAST_RESULT = {"fp": "input_text.ecco_free_power_schedule_last_result",
               "dump": "input_text.ecco_dump_to_grid_schedule_last_result"}
SCHEDULE_STATUS = {"fp": "sensor.ecco_free_power_schedule_status", "dump": "sensor.ecco_dump_to_grid_schedule_status"}
SCRIPT = {"fp": "script.ecco_free_power_start_scheduled", "dump": "script.ecco_dump_to_grid_start_scheduled"}
SMR1_STATE = {"fp": "input_text.ecco_sched_restore_fp_state", "dump": "input_text.ecco_sched_restore_dump_state"}
ACTIVE = {"fp": S.E_ACTIVE, "dump": D.D_ACTIVE}
ARM = {"fp": S.E_ARM, "dump": D.D_ARM}
NUMBERS = {"fp": (S.E_PWR, S.E_DUR), "dump": (D.D_PWR, D.D_SOC, D.D_DUR)}
START_BUTTON = {"fp": "start_free_power_button", "dump": "start_dump_to_grid_button"}   # firmware ids
END_BUTTON = {"fp": "end_free_power_button", "dump": "end_dump_to_grid_button"}
ASSEMBLED_TOU = ("{% set t = states('sensor.ecco_clock_dongle_ecco_timezone' ~ i ~ '_time') %}",
                 "{% set c = states('sensor.ecco_clock_dongle_ecco_timezone' ~ i ~ '_charge') %}")
FW_ACTIONS = ("modbus_policy", "nvs_policy", "set_link", "set_register", "telemetry", "config_poll", "rtc_lock_windows",
              "arm_power_cut")
SOURCE_ANCHORS = (
    ("home-assistant/tests/_ha_script_sim.py", "LOCAL = timezone(timedelta(hours=1))"),
    ("home-assistant/tests/_ha_script_sim.py", "if w.t >= when and key not in self._time_fired and w.t - when < 1.0:"),
    ("home-assistant/tests/_ha_script_sim.py", "def schedule_time_triggers(self):"),
    ("home-assistant/tests/_ha_script_sim.py", "BUSY_10S = ((2.38, 3.15), (4.88, 5.62))"),
    ("home-assistant/tests/_ha_script_sim.py",
     "def __init__(self, world: World, phase: float = 0.0, handle_delays=(0.15,), publish: float = 0.12,"),
    ("home-assistant/tests/_ha_script_sim.py", "self.w.after(0.03, lambda: self._set_arm(on))"),
    ("home-assistant/tests/_ha_dump_sim.py", "HA pressed at +2.019 s, the gate answered 0.117 s"),
    ("home-assistant/tests/_ha_dump_sim.py", "later, the transaction took 4.07 s."),
    ("home-assistant/tests/_ha_dump_sim.py", "a call to a dongle entity while the dongle is offline raises in Home Assistant"),
    ("home-assistant/tests/test_ecco_free_power_schedule_reliability.py", "INCIDENT_DELAYS = (0.6, 0.1)"),
    ("home-assistant/tests/test_ecco_schedule_manual_restore.py", 'SOURCE[0] = "restore" if "plan" in v else'),
    (RUNTIME_CONFIG_REL, f"- name: {LIMIT_SENSOR_NAME}"),
    (PACKAGES["dgs1"], ASSEMBLED_TOU[0]),
    (PACKAGES["smr1"], "# Home Assistant saves restored states every 15 minutes"),
    (L.FW_REL, "return (float) ${ecco_inverter_tou_power_ceiling_w};"),
    (L.FW_REL, "return (float) id(free_power_start_attempts);"),
    (L.FW_REL, "auto format_time = [](uint16_t raw) -> std::string {"),
    (L.FW_REL, 'case 1: return std::string("Grid");'),
    ("registry/tests/_dump_sim.py", 'elif kind in ("wait_until", "delay", "logger.log"):'),
    ("home-assistant/tests/_ha_script_sim.py", 'return value.strip().lower() in ("true", "on", "yes", "1", "enable")'),
    ("home-assistant/tests/_ha_script_sim.py", "handler = lambda e, d: self.set(e, f\"{float(d['value'])}\")  # noqa: E731"),
    ("home-assistant/tests/_ha_script_sim.py", 'keys = set(act) - {"alias", "enabled", "continue_on_error"}'),
    ("home-assistant/tests/_ha_script_sim.py", 'if self.w.state(c["entity_id"]) not in [str(x) for x in want]:'),
    ("home-assistant/tests/_ha_script_sim.py", 'want = tr.get("to", new[0])'),
    (L.FW_REL, "shorter than the hub's send_wait_time (2000ms default, unmodified"),
    (L.FW_REL,
     'ESP_LOGE("free_power", "Snapshot regs230-232 read did not reach a terminal state within the bounded wait");'),
    ("registry/tests/_dump_sim.py", "self.running.add(script_id)"),
)
# Projected op durations by outcome (MODEL ASSUMPTIONS 'Projection'): the ds.Sim event outcome -> the Latency field
NO_RESPONSE_OUTCOMES = ("no_response", "no_response_landed", "no_response_lost")
TIMEOUT_OUTCOMES = ("timeout", "timeout_landed", "timeout_lost")
# The silent-divergence register's measured occurrences (process totals; RealDongle.counts holds one world's)
DIVERGENCE_COUNTS = {
    "busy_drop_own_op_pending": 0,       # same-script presses dropped while the script's own work is pending (device too)
    "busy_refused_nested_only": 0,       # MISS-HA-1: refused - the pressed script is busy only through a nested execute
    "interleaving_refused": 0,           # every LabUnsupported for a mutation inside a projected window (nested-only too)
    "interleaving_in_projection_gap": 0,  # refusals / drops in [V0 window end, corrected window end) (ISS-HA-2)
    "txn": 0,                            # projected transactions
    "txn_fault_outcome": 0,              # ... with a no_response* / timeout* op (window longer than V0's)
    "txn_in_lock_delay": 0,              # ... with an explicit delay: under a lock (window longer than V0's)
    "delay_in_lock": 0,                  # explicit delay: actions projected (under a lock)
    "delay_lock_free": 0,                # explicit delay: actions met lock-free inside a recorded run (zero duration)
    "package_sets_checked": 0,           # check_packages calls (static guard)
    "ignored_option_uses": 0,            # constructs the static guard found (each set raises)
    "truthy_checked": 0,                 # template values through the runtime truthiness guard
    "truthy_refused": 0,                 # ... refused (the sim and HA's condition rule disagree)
    "input_number_checked": 0,           # input_number.set_value calls through the range guard
    "input_number_refused": 0,           # ... outside the helper's [min, max]
    "input_number_unranged": 0,          # ... to an input_number no loaded package declares (stored unchecked)
}


def divergence_counts() -> dict:
    """A copy of DIVERGENCE_COUNTS (the process totals since import)."""
    return dict(DIVERGENCE_COUNTS)


def _count(counts, key: str, n: int = 1) -> None:
    DIVERGENCE_COUNTS[key] += n
    if counts is not None:
        counts[key] = counts.get(key, 0) + n
_HA_DOMAIN = {"sensor": "sensor", "binary_sensor": "binary_sensor", "text_sensor": "sensor", "switch": "switch",
              "number": "number", "button": "button", "select": "select"}
_SVC_KIND = {"switch.turn_on": "switch", "switch.turn_off": "switch", "number.set_value": "number",
             "button.press": "button"}
_LOCKS = ("free_power_operation_in_progress", "dump_operation_in_progress", "manual_write_in_progress",
          "reg244_apply_in_progress")
_LEASE = {"fp": ("free_power_active_persisted", "free_power_snapshot_valid"),
          "dump": ("dump_active_persisted", "dump_snapshot_valid")}
_TOU_RE = re.compile(r"^ecco_tou([1-6])_(time|charge)$")
_USE_RE = re.compile(r"\b(?:binary_sensor|sensor|switch|button|number|select|text)\.ecco_clock_dongle_[a-z0-9_]+")
_LOCAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_DUR_RE = re.compile(r"^(\d+)(ms|s|min)$")
_OPEN: list = []          # the open CoupledWorld (at most one: S.LOCAL and the sim modules are process-global)


def _ms(utc_s) -> int:
    return int(round(utc_s * 1000))


def _num(v, what: str, lo=None) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or (lo is not None and v < lo):
        raise LabHarnessError(f"{what}: a finite number{'' if lo is None else f' >= {lo}'} is required, got {v!r}")
    return float(v)


def _period_ms(text) -> int:
    m = _DUR_RE.match(str(text).strip())
    if not m:
        raise LabUnsupported(f"unsupported ESPHome update_interval {text!r}")
    return int(m.group(1)) * {"ms": 1, "s": 1000, "min": 60000}[m.group(2)]


# ---------------------------------------------------------------------------------------------------------------------------
# configuration objects
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Latency:
    """press_s: press -> gate per press (cycled); cmd_s: switch / number service -> firmware; publish_s: firmware publish
    -> HA state; op_s: one Modbus op of a projected transaction (ok / error / not_sent / ack_not_applied /
    custom_response); no_response_s: an op whose outcome is no_response* (the hub's send-wait expiry); timeout_s: an op
    whose outcome is timeout* (the firmware's bounded wait_until); commit_s: one NVS commit (see MODEL ASSUMPTIONS)."""
    press_s: tuple = (0.117,)
    cmd_s: float = 0.03
    publish_s: float = 0.12
    op_s: float = 0.58
    commit_s: float = 0.01
    no_response_s: float = 2.0
    timeout_s: float = 3.0

    def __post_init__(self):
        p = self.press_s
        if not isinstance(p, (list, tuple)) or not p:
            raise LabHarnessError(f"Latency.press_s must be a non-empty tuple of delays, got {p!r}")
        object.__setattr__(self, "press_s", tuple(_num(x, "Latency.press_s", 0) for x in p))
        for name in ("cmd_s", "publish_s", "op_s", "commit_s", "no_response_s", "timeout_s"):
            object.__setattr__(self, name, _num(getattr(self, name), f"Latency.{name}", 0))


@dataclass(frozen=True)
class BusModel:
    """The Modbus bus state the firmware's START / restore gates read: 'measured' = the 11 Oct 2026 HA-side busy windows
    (S.BUSY_10S / S.BUSY_60S through S.Dongle.bus_busy, shifted by phase_s); 'polls' = busy while one of the lab's own
    firmware runs is doing its projected Modbus ops (t0 .. t0 + ops*op_s; self-consistent with the firmware schedule,
    phase_s unused); or explicit absolute UTC windows [a, b)."""
    phase_s: float = 0.0
    windows: object = "measured"

    def __post_init__(self):
        object.__setattr__(self, "phase_s", _num(self.phase_s, "BusModel.phase_s"))
        w = self.windows
        if w not in ("measured", "polls"):
            if not isinstance(w, (list, tuple)):
                raise LabHarnessError(f"BusModel.windows must be 'measured' or a list of (utc_a, utc_b), got {w!r}")
            out = []
            for x in w:
                if not isinstance(x, (list, tuple)) or len(x) != 2:
                    raise LabHarnessError(f"BusModel window {x!r} must be (utc_a, utc_b)")
                a, b = _num(x[0], "BusModel window"), _num(x[1], "BusModel window")
                if not a < b:
                    raise LabHarnessError(f"BusModel window {x!r} needs utc_a < utc_b")
                out.append((a, b))
            object.__setattr__(self, "windows", tuple(out))

    def busy(self, t: float, polls=()) -> bool:
        """polls: the (a, b) windows of the lab's own projected Modbus traffic (used by the 'polls' mode)."""
        if self.windows == "measured":
            return S.Dongle.bus_busy(types.SimpleNamespace(phase=self.phase_s), t)   # the measured model, reused
        return any(a <= t < b for a, b in (polls if self.windows == "polls" else self.windows))


# ---------------------------------------------------------------------------------------------------------------------------
# mapping: HA entity ids <-> firmware entities (slug rule), package scans, the effective limit template
# ---------------------------------------------------------------------------------------------------------------------------
def ha_slug(name: str) -> str:
    """Home Assistant's slugify of an ESPHome entity name (pattern from home-assistant/tests/
    test_ecco_schedule_manual_restore.py:262 and test_ecco_free_power_schedule_reliability.py:154)."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(name).lower())).strip("_")


_MAP_CACHE: dict = {}


def dongle_entity_map(fw: dict | None = None) -> dict:
    """{HA entity id: (firmware id, kind)} for every named, non-internal firmware entity HA would see (text_sensor ->
    sensor.*); a duplicate HA id raises."""
    fw = fw if fw is not None else L.load_fw()
    info = L.fw_info(fw)
    hit = _MAP_CACHE.get(info.sha)
    if hit is not None:
        return dict(hit)
    subs = fw["_substitutions"]
    out = {}
    for fid, (kind, node) in info.entities.items():
        dom = _HA_DOMAIN.get(kind)
        if dom is None or not node.get("name") or str(node.get("internal")).lower() in ("true", "yes"):
            continue
        hid = f"{dom}.{S.P}{ha_slug(ds.substitute(str(node['name']), subs))}"
        if hid in out:
            raise LabHarnessError(f"two firmware entities map to {hid}: {out[hid][0]} and {fid}")
        out[hid] = (fid, kind)
    _MAP_CACHE[info.sha] = dict(out)
    return out


_TEXTS: dict = {}


def package_text(name: str) -> str:
    rel = PACKAGES.get(name, name if name == RUNTIME_CONFIG_REL else None)
    if rel is None:
        raise LabHarnessError(f"unknown package {name!r} (known: {sorted(PACKAGES)})")
    if rel not in _TEXTS:
        _TEXTS[rel] = T.read_source_text(rel)
    return _TEXTS[rel]


def package_dongle_ids(texts) -> list:
    """Every dongle entity id the package texts use (regex over the YAML text, as the FPS1 / DGS1 suites' [0] do), with
    DGS1's assembled id 'sensor.ecco_clock_dongle_ecco_timezone' ~ i ~ '_time' / '_charge' expanded to its 12 slot ids."""
    texts = list(texts)
    ids = set()
    for t in texts:
        ids |= set(_USE_RE.findall(t))
    partial = f"sensor.{S.P}ecco_timezone"
    if partial in ids:
        joined = "\n".join(texts)
        for a in ASSEMBLED_TOU:
            if joined.count(a) != 1:
                raise LabHarnessError(f"the assembled TOU slot id template changed (found {joined.count(a)}x): {a!r}")
        ids.discard(partial)
        ids |= {f"{partial}{i}_{k}" for i in range(1, 7) for k in ("time", "charge")}
    return sorted(ids)


def tou_text(what: str, raw) -> str:
    """MODEL: the firmware's own TOU slot display formatting (format_time / charge_source in the Block B on_response,
    firmware :16681 / :16721), applied to the cached raw register."""
    raw = int(raw)
    if what == "time":
        hh, mm = raw // 100, raw % 100
        return f"?{raw}" if hh > 23 or mm > 59 else f"{hh:02d}:{mm:02d}"
    if what == "charge":
        return ("None", "Grid", "Generator", "Grid + Generator")[raw & 0x0003]
    raise LabHarnessError(f"tou_text: what must be 'time' or 'charge', got {what!r}")


def limit_template() -> str:
    """The REAL state template of ecco_runtime_config.yaml's 'ECCO Config Maximum Grid Charge Power', gated by its REAL
    availability template (unavailable -> 'unavailable', as HA renders an unavailable template sensor)."""
    pkg = yaml.safe_load(package_text(RUNTIME_CONFIG_REL))
    items = [it for block in pkg.get("template") or [] for it in block.get("sensor") or []
             if it.get("name") == LIMIT_SENSOR_NAME]
    if len(items) != 1:
        raise LabHarnessError(f"{RUNTIME_CONFIG_REL}: template sensor {LIMIT_SENSOR_NAME!r} found {len(items)}x")
    m = re.fullmatch(r"(?s)(.*)\{\{(.*)\}\}\s*", items[0]["availability"])
    if not m or "{{" in m.group(1):
        raise LabUnsupported(f"{LIMIT_SENSOR_NAME}: availability template shape not recognised")
    return (m.group(1) + "{% set lab_available = (" + m.group(2) + ") %}{% if lab_available %}" + items[0]["state"]
            + "{% else %}unavailable{% endif %}")


# ---------------------------------------------------------------------------------------------------------------------------
# fail-loud guards (module docstring FAIL-LOUD GUARDS): constructs the unmodified interpreter would silently ignore
# ---------------------------------------------------------------------------------------------------------------------------
# the sim's _action dispatch order (_ha_script_sim.py:486-560) -> the keys it reads for that action kind ('condition': the
# action is a condition, checked by _COND_KEYS)
_ACTION_KEYS = {"condition": None, "stop": {"stop", "alias"}, "variables": {"variables", "alias"},
                "choose": {"choose", "default", "alias"}, "if": {"if", "then", "else", "alias"},
                "repeat": {"repeat", "alias"}, "delay": {"delay", "alias"},
                "wait_template": {"wait_template", "timeout", "continue_on_timeout", "alias"},
                "action": {"action", "data", "target", "continue_on_error", "alias"}}
_COND_KEYS = {"state": {"condition", "entity_id", "state", "alias"}, "template": {"condition", "value_template", "alias"},
              "or": {"condition", "conditions", "alias"}, "and": {"condition", "conditions", "alias"},
              "not": {"condition", "conditions", "alias"}, "trigger": {"condition", "id", "alias"}}      # cond, :566-590
_TRIGGER_KEYS = {"state": {"trigger", "entity_id", "to", "id", "alias"},                             # setup / poll, :632-688
                 "template": {"trigger", "value_template", "id", "alias"}, "time": {"trigger", "at", "id", "alias"},
                 "homeassistant": {"trigger", "event", "id", "alias"}, "event": {"trigger", "event_type", "id", "alias"}}
_AUTOMATION_KEYS = {"id", "alias", "description", "mode", "max", "max_exceeded", "triggers", "conditions", "actions"}
_SCRIPT_KEYS = {"alias", "description", "mode", "sequence", "variables", "fields", "icon", "max_exceeded"}
_FIELD_KEYS = {"name", "description", "example", "selector"}
_SENSOR_KEYS = {"name", "state", "unique_id", "icon"}           # + attributes while no loaded package reads them
_HELPER_KEYS = {"input_boolean": {"name", "initial", "icon"},
                "input_number": {"name", "min", "max", "step", "initial", "mode", "unit_of_measurement", "icon"},
                "input_text": {"name", "min", "max", "initial", "mode", "icon"},
                "input_datetime": {"name", "has_date", "has_time", "initial", "icon"}}
_LIMIT_SENSOR_KEYS = {"name", "unique_id", "state", "availability", "unit_of_measurement", "device_class", "state_class",
                      "icon"}
_GUARD_CACHE: dict = {}


def _strings(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)
    elif isinstance(node, str):
        yield node


def _attrs_read(eid: str, strings) -> bool:
    """Does any template read an attribute of eid (state_attr / is_state_attr / states.<eid>.attributes)?"""
    pats = (f"state_attr('{eid}'", f'state_attr("{eid}"', f"states.{eid}.attributes", f"states['{eid}'].attributes",
            f'states["{eid}"].attributes')
    return any(p in s for s in strings for p in pats)


def _walk_cond(c, where: str, out: list) -> None:
    if isinstance(c, list):
        for i, x in enumerate(c):
            _walk_cond(x, f"{where}[{i}]", out)
        return
    if not isinstance(c, dict):
        out.append(f"{where}: condition shorthand {str(c)[:60]!r} (the sim reads condition mappings only)")
        return
    if "enabled" in c:
        out.append(f"{where}: enabled: {c['enabled']!r} on a condition (the sim evaluates it; HA skips a disabled one)")
    kind = c.get("condition")
    allowed = _COND_KEYS.get(kind)
    if allowed is None:
        return                       # an unknown condition kind raises S.Unsupported when evaluated (already loud)
    extra = sorted(set(c) - allowed - {"enabled"})
    if extra:
        out.append(f"{where}: {kind} condition with {extra} (not read by the sim; e.g. for: / attribute: change the "
                   "result in HA)")
    if kind == "state" and not isinstance(c.get("entity_id"), str):
        out.append(f"{where}: state condition entity_id {c.get('entity_id')!r} is not one entity id (the sim reads one)")
    if kind in ("or", "and", "not"):
        _walk_cond(c.get("conditions") or [], f"{where}.{kind}", out)


def _walk_actions(acts, where: str, out: list) -> None:
    for i, a in enumerate([acts] if isinstance(acts, dict) else (acts or [])):
        w = f"{where}[{i}]"
        if not isinstance(a, dict):
            out.append(f"{w}: action {str(a)[:60]!r} is not a mapping")
            continue
        if "enabled" in a:
            out.append(f"{w}: enabled: {a['enabled']!r} on an action (the sim runs it, _ha_script_sim.py:486; HA skips a "
                       "disabled action)")
        keys = set(a) - {"alias", "enabled", "continue_on_error"}
        kind = next((k for k in _ACTION_KEYS if k in keys), None)
        if kind is None:
            continue                 # the sim raises S.Unsupported when it reaches it (already loud)
        if kind == "condition":
            _walk_cond({k: v for k, v in a.items() if k != "continue_on_error"}, w, out)
            if "continue_on_error" in a:
                out.append(f"{w}: continue_on_error on a condition action (not read by the sim)")
            continue
        extra = sorted(set(a) - _ACTION_KEYS[kind] - {"enabled"})
        if extra:
            out.append(f"{w}: {kind} action with {extra} (the sim dispatches it as '{kind}' and never reads them)")
        if kind == "action":
            tgt = a.get("target")
            if tgt is not None and (not isinstance(tgt, dict) or set(tgt) - {"entity_id"}):
                out.append(f"{w}: target {tgt!r} beyond entity_id (the sim reads target.entity_id only)")
        elif kind == "choose":
            for j, br in enumerate(a.get("choose") or []):
                bw = f"{w}.choose[{j}]"
                if not isinstance(br, dict):
                    out.append(f"{bw}: option {str(br)[:60]!r} is not a mapping")
                    continue
                extra = sorted(set(br) - {"conditions", "sequence", "alias"})
                if extra:
                    out.append(f"{bw}: choose option with {extra} (not read by the sim)")
                _walk_cond(br.get("conditions") or [], f"{bw}.conditions", out)
                _walk_actions(br.get("sequence"), f"{bw}.sequence", out)
            if "default" in a:
                _walk_actions(a["default"], f"{w}.default", out)
        elif kind == "if":
            _walk_cond(a.get("if") or [], f"{w}.if", out)
            _walk_actions(a.get("then"), f"{w}.then", out)
            if "else" in a:
                _walk_actions(a["else"], f"{w}.else", out)
        elif kind == "repeat":
            r = a.get("repeat") if isinstance(a.get("repeat"), dict) else {}
            _walk_actions(r.get("sequence"), f"{w}.repeat.sequence", out)
            if "until" in r:
                _walk_cond(r["until"], f"{w}.repeat.until", out)


def _walk_trigger(t, where: str, out: list, datetimes: dict) -> None:
    if not isinstance(t, dict):
        out.append(f"{where}: trigger {str(t)[:60]!r} is not a mapping")
        return
    if "enabled" in t:
        out.append(f"{where}: enabled: {t['enabled']!r} on a trigger (the sim fires it; HA ignores a disabled trigger)")
    kind = t.get("trigger")
    allowed = _TRIGGER_KEYS.get(kind)
    if allowed is None:
        return                       # S.Unsupported at automation setup (already loud)
    extra = sorted(set(t) - allowed - {"enabled"})
    if extra:
        out.append(f"{where}: {kind} trigger with {extra} (not read by the sim; e.g. for: / from: / not_from: / "
                   "attribute: change when HA fires)")
    if kind == "state" and "to" not in t:
        out.append(f"{where}: state trigger without to: (HA also fires on attribute-only changes; the sim on state "
                   "changes only, _ha_script_sim.py:683-684)")
    elif kind == "state" and isinstance(t.get("to"), list):
        out.append(f"{where}: state trigger to: {t['to']!r} is a list (the sim compares str(list): it never fires)")
    if kind == "homeassistant" and t.get("event") != "start":
        out.append(f"{where}: homeassistant trigger event {t.get('event')!r} (the sim fires 'start' only)")
    if kind == "event" and not isinstance(t.get("event_type"), str):
        out.append(f"{where}: event trigger event_type {t.get('event_type')!r} is not one str (the sim compares one)")
    if kind == "time":
        at = t.get("at")
        spec = datetimes.get(at) if isinstance(at, str) else None
        if isinstance(at, str) and at.startswith("input_datetime.") and not (
                isinstance(spec, dict) and spec.get("has_date") and spec.get("has_time")):
            out.append(f"{where}: time trigger at {at!r} is not a date+time input_datetime of the loaded packages (the "
                       "sim parses 'YYYY-MM-DD HH:MM:SS' only and silently never fires otherwise, :669-672)")


_ENTITY_RE = re.compile(r"""['"]([a-z_]+\.[a-z0-9_]+)['"]""")


def _trigger_block_problems(triggers, item: dict) -> list:
    """A trigger-based template block (HA renders the sensor on its triggers and keeps the state in between) is modelled by
    the lab's render-on-read only when that is the same value: every trigger is homeassistant start / time_pattern /
    state, the item's state and availability templates read entity states only through quoted ids (no now(), no
    state_attr / states.<id> / expand) and every id they read is an entity of a state trigger (so each input change
    re-renders, and the start / periodic re-renders give the same value). Any other shape -> the problems."""
    out, watched = [], set()
    for i, t in enumerate(triggers if isinstance(triggers, list) else [triggers]):
        kind = t.get("trigger") if isinstance(t, dict) else None
        if kind == "state":
            ents = t.get("entity_id")
            watched |= set(ents if isinstance(ents, list) else [ents])
            extra = sorted(set(t) - {"trigger", "entity_id", "id", "alias"})
            if extra:
                out.append(f"the limit sensor's state trigger [{i}] has {extra} (render-on-read would not match)")
        elif not ((kind == "homeassistant" and t.get("event") == "start") or kind == "time_pattern"):
            out.append(f"the limit sensor's block trigger [{i}] {kind!r} is not homeassistant start / time_pattern / state")
    for key in ("state", "availability"):
        tpl = str(item.get(key, ""))
        if re.search(r"now\(|state_attr|states\.|expand\(|this\.", tpl):
            out.append(f"the limit sensor's {key} template reads time / attributes / dynamic entities (render-on-read "
                       "would not match its trigger-based value)")
        missing = sorted(set(_ENTITY_RE.findall(tpl)) - watched)
        if missing:
            out.append(f"the limit sensor's {key} template reads {missing}, which no state trigger of its block "
                       "watches (HA keeps the old value when they change; the lab renders on read)")
    return out


def ignored_options(docs: dict, runtime_config=None) -> list:
    """Every construct of the parsed packages docs {name: package} (and of the parsed ecco_runtime_config.yaml, when
    given) that _ha_script_sim or this lab would silently ignore (module docstring FAIL-LOUD GUARDS): ['<where>: <what>'].
    Pure; constructs the sim already refuses loudly (unknown action / condition / trigger kinds, script modes) are left to
    it."""
    out: list = []
    strings = list(_strings(docs))
    datetimes = {f"input_datetime.{k}": v for d in docs.values() if isinstance(d, dict)
                 for k, v in (d.get("input_datetime") or {}).items()}
    for name, pkg in docs.items():
        if not isinstance(pkg, dict):
            out.append(f"{name}: the package is not a mapping")
            continue
        for dom, allowed in _HELPER_KEYS.items():
            for k, spec in (pkg.get(dom) or {}).items():
                if not isinstance(spec, dict):
                    continue         # the sim's helper set-up reads spec.get (an empty helper fails loudly there)
                extra = sorted(set(spec) - allowed)
                if extra:
                    out.append(f"{name}: {dom}.{k} with {extra} (not applied by the sim)")
                if dom == "input_text" and float(spec.get("min", 0) or 0) > 0:
                    out.append(f"{name}: {dom}.{k} min {spec['min']!r} (HA refuses shorter values; the sim does not)")
                if dom == "input_datetime" and spec.get("has_date") and "initial" in spec:
                    out.append(f"{name}: {dom}.{k} initial on a date helper (the sim leaves date helpers unset)")
        for i, a in enumerate(pkg.get("automation") or []):
            aw = f"{name}: automation[{a.get('id', i) if isinstance(a, dict) else i}]"
            if not isinstance(a, dict):
                out.append(f"{aw} is not a mapping")
                continue
            extra = sorted(set(a) - _AUTOMATION_KEYS)
            if extra:
                out.append(f"{aw} with {extra} (not read by the sim: e.g. automation variables / trigger_variables / "
                           "initial_state, or a singular trigger / condition / action)")
            for j, t in enumerate(a.get("triggers") or []):
                _walk_trigger(t, f"{aw}.triggers[{j}]", out, datetimes)
            _walk_cond(a.get("conditions") or [], f"{aw}.conditions", out)
            _walk_actions(a.get("actions"), f"{aw}.actions", out)
        for sname, s in (pkg.get("script") or {}).items():
            sw = f"{name}: script[{sname}]"
            if not isinstance(s, dict):
                out.append(f"{sw} is not a mapping")
                continue
            extra = sorted(set(s) - _SCRIPT_KEYS)
            if extra:
                out.append(f"{sw} with {extra} (not read by the sim)")
            for f, fv in (s.get("fields") or {}).items():
                if isinstance(fv, dict) and set(fv) - _FIELD_KEYS:
                    out.append(f"{sw}.fields.{f} with {sorted(set(fv) - _FIELD_KEYS)} (the sim reads the caller's data "
                               "only)")
            _walk_actions(s.get("sequence"), f"{sw}.sequence", out)
        for block in pkg.get("template") or []:
            for it in (block.get("sensor") or []) if isinstance(block, dict) else []:
                if not isinstance(it, dict):
                    continue
                eid = "sensor." + str(it.get("name", "")).lower().replace(" ", "_")   # the sim's id rule, :357
                allowed = _SENSOR_KEYS | ({"attributes"} if not _attrs_read(eid, strings) else set())
                extra = sorted(set(it) - allowed)
                if extra:
                    out.append(f"{name}: template sensor {it.get('name')!r} with {extra} (the sim renders state only, "
                               ":358)")
    if runtime_config is not None:
        rc = RUNTIME_CONFIG_REL
        if not isinstance(runtime_config, dict):
            return out + [f"{rc}: not a mapping"]
        extra = sorted(set(runtime_config) - {"template"})
        if extra:
            out.append(f"{rc}: top-level {extra} (the lab loads only the limit sensor's state / availability)")
        found = 0
        for block in runtime_config.get("template") or []:
            items = [it for it in ((block.get("sensor") or []) if isinstance(block, dict) else [])
                     if isinstance(it, dict) and it.get("name") == LIMIT_SENSOR_NAME]
            if not items:
                continue
            found += len(items)
            extra = sorted(set(block) - {"sensor", "triggers"})
            if extra:
                out.append(f"{rc}: the limit sensor's template block has {extra} (not read by the lab)")
            if "triggers" in block:
                out += [f"{rc}: {p}" for it in items for p in _trigger_block_problems(block["triggers"], it)]
            for it in items:
                allowed = _LIMIT_SENSOR_KEYS | ({"attributes"} if not _attrs_read(E_LIMIT, strings) else set())
                extra = sorted(set(it) - allowed)
                if extra:
                    out.append(f"{rc}: {LIMIT_SENSOR_NAME!r} with {extra} (the lab renders state and availability only)")
        if found != 1:
            out.append(f"{rc}: template sensor {LIMIT_SENSOR_NAME!r} found {found}x")
    return out


_RANGES: dict = {}
_TRUTHY_SIM = S._truthy        # the interpreter's own truthiness (_ha_script_sim.py:91-94), restored by close()


def _input_number_ranges(text: str) -> dict:
    """{input_number id: (min, max)} declared by one package text (cached by text)."""
    hit = _RANGES.get(text)
    if hit is None:
        hit = _RANGES[text] = {f"input_number.{k}": (float(spec.get("min", 0)), float(spec.get("max", 100)))
                               for k, spec in ((yaml.safe_load(text) or {}).get("input_number") or {}).items()
                               if isinstance(spec, dict)}
    return hit


def _truthy_guard(value) -> bool:
    """S._truthy while a CoupledWorld is open: the sim's answer, refused (LabUnsupported) where Home Assistant's template
    condition / wait_template rule (the stripped render lowercased == 'true', REPORTED) disagrees with it."""
    res = _TRUTHY_SIM(value)
    world = _OPEN[0] if _OPEN else None
    counts = getattr(getattr(world, "dongle", None), "counts", None)
    _count(counts, "truthy_checked")
    if res != (str(value).strip().lower() == "true"):
        _count(counts, "truthy_refused")
        raise LabUnsupported(f"a template rendered {value!r}: _ha_script_sim's truthiness says {res}, Home Assistant's "
                             f"template condition rule (render == 'true', REPORTED) says {not res} (ISS-HA-5; not "
                             "modelled)")
    return res


def check_packages(texts: dict, counts=None) -> None:
    """The static guard: ignored_options over the package texts {name: text} (yaml.safe_load, the parse CoupledWorld
    uses) and ecco_runtime_config.yaml; raises LabUnsupported listing every construct found. Counted per call."""
    key = tuple(sorted(texts.items()))
    hit = _GUARD_CACHE.get(key)
    if hit is None:
        docs = {n: yaml.safe_load(t) for n, t in sorted(texts.items())}
        hit = _GUARD_CACHE[key] = tuple(ignored_options(docs, yaml.safe_load(package_text(RUNTIME_CONFIG_REL))))
    _count(counts, "package_sets_checked")
    if hit:
        _count(counts, "ignored_option_uses", len(hit))
        raise LabUnsupported(f"the HA package(s) {sorted(texts)} use {len(hit)} construct(s) _ha_script_sim would silently "
                             f"ignore (ISS-HA-5; not modelled): " + "; ".join(hit))


# ---------------------------------------------------------------------------------------------------------------------------
# the firmware side: FirmwareWorld + recorder hooks
# ---------------------------------------------------------------------------------------------------------------------------
class CoupledFirmware(L.FirmwareWorld):
    """FirmwareWorld with the hooks the adapter needs. Nothing here changes what the firmware does."""

    def __init__(self, *args, switch_ids=(), **kw):
        self.recorder = None
        self.switch_ids = tuple(switch_ids)
        super().__init__(*args, **kw)

    def _on_event(self, ev) -> None:
        if self.recorder is not None:
            self.recorder.on_event(ev)
        super()._on_event(ev)

    def _on_publish(self, name, value) -> None:
        super()._on_publish(name, value)
        if self.recorder is not None:
            self.recorder.on_publish(name, value)

    def _boot_once(self, **kw) -> None:
        super()._boot_once(**kw)
        for fid in self.switch_ids:   # per instance: a template switch's turn_on / turn_off publishes (optimistic)
            ent = self.sim.entities[fid]
            for meth in ("turn_on", "turn_off"):
                setattr(ent, meth, self._switch_hook(ent, getattr(ent, meth)))
        self.sim.run_actions = self._delay_hook(self.sim.run_actions)   # per instance (observer only)

    def _delay_hook(self, orig):
        """Observe explicit `delay:` actions (ds.Sim skips them, _dump_sim.py:1513) for the projection: a list holding one
        runs action by action, telling the recorder of each delay before it is (not) run; any other list runs unchanged."""
        def run_actions(actions, local=None):
            if self.recorder is None or not actions or not any(isinstance(a, dict) and "delay" in a for a in actions):
                return orig(actions, local)
            for action in actions:
                if isinstance(action, dict) and len(action) == 1 and "delay" in action and self.recorder is not None:
                    self.recorder.on_delay(action["delay"])
                orig([action], local)
            return None
        return run_actions

    def _switch_hook(self, ent, orig):
        def call():
            orig()
            if self.recorder is not None:
                self.recorder.on_publish(ent.name, ent.state)
        return call

    @property
    def utc_ms(self) -> int:
        return self._utc_ms()

    def next_due_ms(self) -> int:
        """UTC ms of the next scheduler wake-up (job slot, first NTP sync, RTC window edge); now when overdue."""
        sim = self._need_sim()
        ups = list(self._next.values()) + self._rtc_edges_up()
        if self._ntp_due is not None:
            ups.append(self._ntp_due)
        return self._utc_ms() + max(0, min(ups) - sim.now_ms)

    def sync_to(self, t_ms: int) -> None:
        """LIVE: run the scheduler up to UTC t_ms (overdue slots run once now). When nothing is due strictly before t_ms
        (the driver wakes at every due instant) the clock moves first and what is due AT t_ms runs there: the same runs
        as one run_for, and the act.run_for event carries t_ms (a monotonic merged log)."""
        now = self._utc_ms()
        if t_ms < now:
            raise LabHarnessError(f"firmware clock {now / 1000} is ahead of the World clock {t_ms / 1000}")
        if self.next_due_ms() >= t_ms:
            self.raw_to(t_ms)
            if self.next_due_ms() <= t_ms:
                self.run_for(0)
        else:
            self.run_for((t_ms - now) / 1000)

    def raw_to(self, t_ms: int) -> None:
        """RAW: uptime and UTC move to t_ms and nothing runs (a projected busy window)."""
        now = self._utc_ms()
        if t_ms > now:
            self.advance((t_ms - now) / 1000)

    def capture_now(self) -> dict:
        return self._capture(None)

    def command(self, name: str, args: dict, fn) -> None:
        """One firmware world action (logged act.<name>, never nested, the power-cut boundary)."""
        with self._acting(name, args):
            fn()


class _Run:
    """The record of one firmware entry: Modbus / commit counts, ordered HA-visible publishes, lease edges; the projected
    elapsed time sums each op's duration by its outcome, the commits and the in-lock delays (MODEL ASSUMPTIONS)."""

    def __init__(self, dongle: "RealDongle", t0: float, cmd):
        self.d, self.t0, self.cmd = dongle, t0, cmd
        self.ops = self.commits = self.writes = 0
        self.n_no_response = self.n_timeout = 0    # ops with a no_response* / timeout* outcome
        self.delay_ms = 0                           # explicit delay: actions executed under a lock
        self.busy_el = None        # elapsed at the end of the last op / commit / delay done under a lock (or a write)
        self.v0_busy_el = None     # the same instant under the V0 projection (every op op_s, no delay)
        self.own_end: dict = {}    # script -> elapsed at the end of its own last op / commit / in-lock delay
        self.scripts: set = set()
        self.pubs: list = []
        self.edges: list = []

    def elapsed(self) -> float:
        lat = self.d.lat
        base = (self.ops - self.n_no_response - self.n_timeout) * lat.op_s + self.commits * lat.commit_s
        if self.n_no_response or self.n_timeout or self.delay_ms:
            return base + (self.n_no_response * lat.no_response_s + self.n_timeout * lat.timeout_s + self.delay_ms / 1000)
        return base                # exactly the V0 ops * op_s + commits * commit_s

    def v0_elapsed(self) -> float:
        lat = self.d.lat
        return self.ops * lat.op_s + self.commits * lat.commit_s

    def mark(self) -> None:
        self.d._mark(self)

    def _own(self) -> None:
        stack = self.d.fw.sim.script_stack
        if stack:
            self.own_end[stack[-1]] = self.elapsed()

    def on_event(self, ev) -> None:
        self.mark()   # the stretch before this op ends here
        kind = ev[0]
        if kind in ("read", "write"):
            self.ops += 1
            self.writes += kind == "write"
            if ev[3] in NO_RESPONSE_OUTCOMES:
                self.n_no_response += 1
            elif ev[3] in TIMEOUT_OUTCOMES:
                self.n_timeout += 1
        elif kind == "commit":
            self.commits += 1
        else:
            return
        self._own()
        if kind == "write" or self.d.locked():
            self.busy_el, self.v0_busy_el = self.elapsed(), self.v0_elapsed()
            self.scripts.update(self.d.fw.sim.script_stack)

    def on_delay(self, body) -> None:
        """An explicit `delay:` action: under a transaction lock it holds the transaction its own length (the stretch
        before it ends here); lock-free it keeps zero projected duration (NOT MODELLED), counted."""
        if not self.d.locked():
            _count(self.d.counts, "delay_lock_free")
            return
        m = _DUR_RE.match(str(body).strip()) if isinstance(body, str) else None
        if not m:
            raise LabUnsupported(f"an explicit delay {body!r} inside a projected transaction: only a literal "
                                 "<n>ms / <n>s / <n>min is modelled")
        self.mark()
        self.delay_ms += int(m.group(1)) * {"ms": 1, "s": 1000, "min": 60000}[m.group(2)]
        _count(self.d.counts, "delay_in_lock")
        self._own()
        self.busy_el = self.elapsed()
        if self.v0_busy_el is None:
            self.v0_busy_el = 0.0
        self.scripts.update(self.d.fw.sim.script_stack)

    def on_publish(self, fid, value) -> None:
        hid = self.d.pub_ids.get(fid)
        if hid is not None:
            self.pubs.append((self.elapsed(), hid, self.d._fmt(hid, value)))


# ---------------------------------------------------------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------------------------------------------------------
class RealDongle:
    """Installs the dongle service handlers into the World and publishes firmware truth to it (module docstring)."""

    def __init__(self, cw: "CoupledWorld", fw: CoupledFirmware, view_ids):
        self.cw, self.w, self.fw, self.lat = cw, cw.w, fw, cw.lat
        info = fw.info
        subs = fw.fw["_substitutions"]
        self.entity_map = dongle_entity_map(fw.fw)
        self.commands = {h: v for h, v in self.entity_map.items() if v[1] in ("switch", "number", "button")}
        self.view: dict = {}
        for hid in view_ids:
            if hid not in self.entity_map:
                raise LabHarnessError(f"a package uses {hid}, but no firmware entity maps to it (slug rule)")
            fid, kind = self.entity_map[hid]
            if kind == "button":
                continue
            node = info.entities[fid][1]
            spec = {"fid": fid, "kind": kind}
            tou = _TOU_RE.match(fid)
            if kind == "text_sensor" and tou:
                reg = (249 if tou.group(2) == "time" else 273) + int(tou.group(1))
                spec.update(src="tou", what=tou.group(2), glob=f"manual_cfg_reg{reg}_raw")
            elif kind == "binary_sensor" and "lambda" in node:
                spec.update(src="lambda", code=node["lambda"])
            elif kind in ("sensor", "text_sensor") and "lambda" in node:
                spec.update(src="polled", code=node["lambda"], period_ms=_period_ms(node.get("update_interval", "60s")))
            elif "lambda" in node:
                raise LabUnsupported(f"{hid}: a {kind} with a lambda is not modelled")
            else:
                spec["src"] = "entity"
            if kind == "number":
                spec["attrs"] = {k: float(ds.substitute(str(node[f]), subs)) for k, f in (("min", "min_value"),
                                                                                           ("max", "max_value"))}
                spec["attrs"]["step"] = float(ds.substitute(str(node.get("step", 1)), subs))
            self.view[hid] = spec
        g = fw.sim.g
        missing = [n for n in (*_LOCKS, *(x for p in _LEASE.values() for x in p), "cfg_block_b_seq",
                               *(s["glob"] for s in self.view.values() if s["src"] == "tou")) if n not in g]
        if missing:
            raise LabHarnessError(f"firmware globals the adapter reads are missing: {missing}")
        self.pub_ids = {s["fid"]: h for h, s in self.view.items() if s["src"] == "entity"}
        self.down: dict = {}                 # link-down reason -> count (every disconnect is matched by one connect)
        self.gen = 0
        self._pub_seq = 0
        self._seen_seq: dict = {}
        self.off = False
        self.busy_until = -math.inf
        self.busy_t0 = -math.inf
        self.busy_v0_until = -math.inf      # where the V0 projection (every op op_s, no delay) ended the same window
        self.busy_own_end: dict = {}        # script -> UTC end of its own last op / commit / in-lock delay in the window
        self.counts: dict = dict.fromkeys(DIVERGENCE_COUNTS, 0)   # this world's share of DIVERGENCE_COUNTS
        self._modes = {s["id"]: s.get("mode", "single") for s in fw.fw.get("script") or []}
        self.raw_until = None
        self.busy_scripts: frozenset = frozenset()
        self.presses = 0
        self.pending_until = -math.inf       # the latest scheduled HA delivery (quiescent once the World passes it)
        self._bus_polls: list = []
        self._drive_gen = 0
        self._pub_last: dict = {}
        self._lam_last: dict = {}
        self._lease = self._lease_flags()
        self._boot_seen = -1
        self._polled_next: dict = {}
        self._polled_last: dict = {}
        self._reset_polled()
        for svc in _SVC_KIND:
            cw.w.service_handlers[svc] = self._handler(svc)

    # -- truth -> HA ------------------------------------------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return not any(self.down.values())

    def _fmt(self, hid: str, v) -> str:
        kind = self.view[hid]["kind"]
        if kind in ("switch", "binary_sensor"):
            if isinstance(v, bool) or (isinstance(v, int) and v in (0, 1)):
                return "on" if v else "off"
            raise LabHarnessError(f"{hid}: firmware {kind} value {v!r} is not a bool (NaN-truthy guard)")
        if kind in ("number", "sensor"):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise LabHarnessError(f"{hid}: firmware {kind} value {v!r} is not a number")
            f = float(v)
            return f"{f}" if math.isfinite(f) else "unknown"
        s = str(v)
        return s if s else "unknown"

    def locked(self) -> bool:
        """A transaction lock is held (FP / Dump operation, manual write, reg244 apply)."""
        g = self.fw.sim.g
        return any(bool(g[n]) for n in _LOCKS)

    def _lease_flags(self) -> dict:
        g = self.fw.sim.g
        return {d: (bool(g[a]), bool(g[s])) for d, (a, s) in _LEASE.items()}

    def _derived(self) -> dict:
        """Lambda template binary sensors (their REAL lambdas) and the TOU slot sensors (MODEL; None before Block B)."""
        sim, out = self.fw.sim, {}
        block_b = sim.g["cfg_block_b_seq"] > 0
        for hid, spec in self.view.items():
            if spec["src"] == "lambda":
                out[hid] = self._fmt(hid, sim.run_lambda(spec["code"]))
            elif spec["src"] == "tou":
                out[hid] = tou_text(spec["what"], sim.g[spec["glob"]]) if block_b else None
        return out

    def _mark(self, run: _Run) -> None:
        el = run.elapsed()
        for hid, st in self._derived().items():
            if st is not None and self._lam_last.get(hid) != st:
                self._lam_last[hid] = st
                run.pubs.append((el, hid, st))
        for d, f in self._lease_flags().items():
            if f != self._lease[d]:
                self._lease[d] = f
                run.edges.append((el, d, f))

    def full_view(self) -> dict:
        """{HA id: state} of every viewed dongle entity from firmware truth now (what a reconnect publishes). A polled
        template sensor publishes its last sample of this boot, never its live lambda: with no sample since power-on it
        has no state, and HA reads 'unknown' (MODEL ASSUMPTIONS)."""
        sim, out = self.fw.sim, {}
        derived = self._derived()
        for hid, spec in self.view.items():
            src = spec["src"]
            if src == "entity":
                st = self._fmt(hid, sim.ent(spec["fid"]).state)
            elif src == "polled":
                st = self._polled_last.get(hid, "unknown")
            else:
                st = derived[hid]
            if st is not None:
                out[hid] = st
        return out

    def ha_visible(self) -> dict:
        """{_lab_fw.HA_VIEW key: HA state} for the HA_VIEW entities this world views (for comparison with fw.ha_view())."""
        rev = {s["fid"]: h for h, s in self.view.items()}
        return {k: self.w.state(rev[fid]) for k, fid in L.HA_VIEW.items() if fid in rev}

    def _publish(self, when: float, hid: str, st: str) -> None:
        if not self.connected or self._pub_last.get(hid) == st:
            return
        self._pub_last[hid] = st
        attrs, gen = self.view[hid].get("attrs"), self.gen
        self._pub_seq += 1
        seq = self._pub_seq
        self.pending_until = max(self.pending_until, when)
        self.w.at(when, lambda: self._deliver(gen, seq, hid, st, attrs))

    def _deliver(self, gen: int, seq: int, hid: str, st: str, attrs) -> None:
        """Deliver one publish unless the link dropped since, or a NEWER publish of the entity already landed (a projected
        lock-free trailing read can be scheduled later than a newer run's publish)."""
        if gen == self.gen and self.connected and seq > self._seen_seq.get(hid, 0):
            self._seen_seq[hid] = seq
            self.w.set(hid, st, attrs)

    def mark_unavailable(self) -> None:
        for hid in sorted(self.view):
            self.w.set(hid, "unavailable")

    def disconnect(self, reason: str) -> None:
        was = self.connected
        self.down[reason] = self.down.get(reason, 0) + 1
        if was:
            self.gen += 1
            self._pub_last, self._lam_last = {}, {}   # nothing published survives: the next values are new to HA
            self.cw._log("dongle.link", {"up": False, "reason": reason})
            if self.cw.ha_up:
                self.mark_unavailable()

    def connect(self, reason: str) -> None:
        if not self.down.get(reason):
            raise LabHarnessError(f"connect({reason!r}): the link is not down for that reason ({self.down})")
        self.down[reason] -= 1
        if self.connected:
            self.gen += 1
            self.cw._log("dongle.link", {"up": True, "reason": reason})
            when = max(self.w.t, self.busy_until) + self.lat.publish_s
            for hid, st in sorted(self.full_view().items()):
                self._publish(when, hid, st)

    def connect_initial(self) -> None:
        """The dongle is already connected when the world starts: its whole view is in the state machine at once (a
        polled sensor: its warm-up sample, else 'unknown')."""
        for hid, st in sorted(self.full_view().items()):
            self._pub_last[hid] = st
            self.w.set(hid, st, self.view[hid].get("attrs"))

    def warm_up(self, seconds: int) -> None:
        """fw_world_kwargs warmup_s: the firmware runs `seconds` before the World starts (no HA, nothing projected) in
        run_for pieces that end at every polled-sensor sample instant (the same firmware runs as one run_for), so the
        state connect_initial publishes is the model's last warm-up sample. A firmware restart inside raises."""
        fw, boot0 = self.fw, self.fw.boot_no
        end = fw.utc_ms + seconds * 1000
        while True:
            self._sample_polled()
            if fw.utc_ms >= end:
                break
            due = min(self._polled_next.values(), default=None)
            nxt = end if due is None else min(end, fw.utc_ms + due - fw.sim.now_ms)
            fw.run_for((nxt - fw.utc_ms) / 1000)
            if fw.boot_no != boot0:
                raise LabUnsupported("a firmware restart inside the coupled warm-up is not modelled")
        self._lease = self._lease_flags()

    def _reset_polled(self) -> None:
        self._boot_seen = self.fw.boot_no
        self._polled_last = {}
        self._polled_next = {h: s["period_ms"] for h, s in self.view.items() if s["src"] == "polled"}

    def _sample_polled(self) -> list:
        """Sample (REAL lambda) every polled sensor whose sample instant has come -> [(HA id, state)] to publish."""
        sim, out = self.fw.sim, []
        for hid, due in sorted(self._polled_next.items()):
            if sim.now_ms >= due:
                period = self.view[hid]["period_ms"]
                st = self._fmt(hid, sim.run_lambda(self.view[hid]["code"]))
                self._polled_last[hid] = st
                out.append((hid, st))
                self._polled_next[hid] = (sim.now_ms // period + 1) * period
        return out

    # -- HA -> firmware ---------------------------------------------------------------------------------------------------
    def _handler(self, svc: str):
        def handler(entity_id, data):
            self._call(svc, entity_id, data)
        return handler

    def _resolve(self, svc: str, eid: str):
        kind = _SVC_KIND[svc]
        hit = self.commands.get(eid)
        if hit is None or hit[1] != kind:
            raise S.Unsupported(f"RealDongle: {svc} on {eid!r}: not a mapped dongle {kind}")
        return hit[0], kind

    def press_scripts(self, fid: str):
        """The scripts a button's on_press executes when it is ONLY script.execute actions, else None."""
        acts = self.fw.info.buttons[fid].get("on_press") or []
        ids = [a["script.execute"] for a in acts if set(a) == {"script.execute"}]
        if not acts or len(ids) != len(acts):
            return None
        return frozenset(x if isinstance(x, str) else x["id"] for x in ids)

    def _cmd(self, svc: str, eid: str, data: dict, by: str, direct: bool) -> dict:
        fid, kind = self._resolve(svc, eid)
        cmd = {"svc": svc, "e": eid, "fid": fid, "kind": kind, "by": by, "direct": direct, "value": None}
        if kind == "number":
            v = data.get("value")
            cmd["value"] = _num(float(v) if isinstance(v, str) else v, f"number.set_value {eid}")
        elif kind == "switch":
            cmd["value"] = svc == "switch.turn_on"
        return cmd

    def _call(self, svc: str, eid: str, data: dict) -> None:
        cmd = self._cmd(svc, eid, data, self.cw._by or "ha", direct=False)
        if not self.connected:
            self.cw._log("dongle.dropped", {"svc": svc, "e": eid, "why": "offline", "by": cmd["by"]})
            if self.cw.offline_policy == "raise":
                raise S.ServiceError("dongle offline (ESPHome API not connected)")
            return
        if cmd["kind"] == "button":
            delay = self.lat.press_s[self.presses % len(self.lat.press_s)]
            self.presses += 1
        else:
            delay = self.lat.cmd_s
        gen = self.gen
        self.w.at(self.w.t + delay, lambda: self._apply(cmd, gen))

    def direct(self, svc: str, eid: str, data: dict, by: str) -> None:
        """A command through the dongle's own UI (no HA, no latency), applied now."""
        self._apply(self._cmd(svc, eid, data, by, direct=True), self.gen)

    def _apply(self, cmd: dict, gen: int) -> None:
        why = ("powered_off" if self.off else None if cmd["direct"] else
               "lost_in_flight" if gen != self.gen or not self.connected else None)
        if why:
            self.cw._log("dongle.dropped", {"svc": cmd["svc"], "e": cmd["e"], "why": why, "by": cmd["by"]})
            return
        if self.w.t < self.busy_until - 1e-9:
            gap = self._in_gap()
            what = (f"{cmd['svc']} {cmd['e']} at {self.w.t:.3f} inside [{self.busy_t0:.3f}, {self.busy_until:.3f}) of "
                    f"{sorted(self.busy_scripts)}")
            ps = self.press_scripts(cmd["fid"]) if cmd["kind"] == "button" else None
            if ps and ps <= self.busy_scripts:
                modes = {s: self._modes.get(s, "single") for s in sorted(ps)}
                done = sorted(s for s in ps if self.w.t >= self.busy_own_end.get(s, -math.inf) - 1e-9)
                if all(m == "single" for m in modes.values()) and not done:
                    # every pressed script's OWN work is still pending: ESPHome's SingleScript drops the run too
                    _count(self.counts, "busy_drop_own_op_pending")
                    if gap:
                        _count(self.counts, "interleaving_in_projection_gap")
                    self.cw._log("dongle.dropped", {"svc": cmd["svc"], "e": cmd["e"], "why": "busy_same_script",
                                                    "by": cmd["by"]})
                    return
                _count(self.counts, "interleaving_refused")
                if gap:
                    _count(self.counts, "interleaving_in_projection_gap")
                if done:
                    _count(self.counts, "busy_refused_nested_only")
                    own = {s: round(self.busy_own_end[s], 3) if s in self.busy_own_end else None for s in done}
                    raise LabUnsupported(
                        "interleaving inside a projected firmware transaction is not modelled: " + what + f" - {done} "
                        f"in the window only through a nested script.execute (own work ended at {own}): ESPHome would "
                        "run the press (script.execute does not block its caller), the synchronous lab cannot "
                        "(MISS-HA-1)" + self._gap_note(gap))
                raise LabUnsupported("interleaving inside a projected firmware transaction is not modelled: " + what
                                     + f" - pressed script mode {modes} is not 'single'" + self._gap_note(gap))
            _count(self.counts, "interleaving_refused")
            if gap:
                _count(self.counts, "interleaving_in_projection_gap")
            raise LabUnsupported("interleaving inside a projected firmware transaction is not modelled: " + what
                                 + self._gap_note(gap))
        self._entry(cmd=cmd)

    def _in_gap(self) -> bool:
        """The World clock is past where the V0 projection ended the open window (the projection gap: a no_response /
        timeout op or an in-lock delay made it longer; V0 applied a mutation here silently, ISS-HA-2)."""
        return self.w.t >= self.busy_v0_until - 1e-9

    def _gap_note(self, gap: bool) -> str:
        return (f" (in the projection gap [{self.busy_v0_until:.3f}, {self.busy_until:.3f}): a no_response / timeout op "
                "or an in-lock delay holds the transaction past the V0 op_s projection, ISS-HA-2)") if gap else ""

    def _run_cmd(self, cmd: dict) -> None:
        fw, fid, kind = self.fw, cmd["fid"], cmd["kind"]
        o = fw.obligations()
        data = {k: cmd[k] for k in ("svc", "e", "fid", "kind", "value", "by")}
        data["obl"] = {d: {k: o[d][k] for k in ("act", "snap", "op")} for d in DOMS}
        data["mw"] = o["mw"]
        if kind == "number":
            old = fw.sim.ent(fid).state
            data["old"] = float(old) if isinstance(old, (int, float)) and math.isfinite(old) else None
        self.cw._log("dongle.cmd", data)
        if kind == "switch":
            fw.command("ha.switch", {"fid": fid, "on": cmd["value"]}, lambda: fw.set_switch(fid, cmd["value"]))
        elif kind == "number":
            fw.command("ha.number", {"fid": fid, "value": cmd["value"]}, lambda: fw.set_number(fid, cmd["value"]))
        else:
            fw.command("ha.press", {"fid": fid}, lambda: fw.press(fid))

    # -- the single firmware entry point ---------------------------------------------------------------------------------
    def _apply_bus(self, t: float) -> None:
        idle = not self.cw.bus.busy(t, self._bus_polls)
        if idle != self.fw.bus_idle:
            self.fw.bus_idle = idle            # what FirmwareWorld.set_bus_idle does, logged on the World clock instead
            self.fw.sim.bus_idle = idle
            self.cw._log("env.bus", {"idle": idle, "source": "BusModel"})

    def entry(self, cmd=None, fn=None) -> None:
        """Run firmware work at w.t: the clock (deferred raw window, then live), then the command / fn; recorded and
        projected (see MODEL ASSUMPTIONS)."""
        if self.off:
            raise LabHarnessError("firmware entry while the dongle is powered off")
        if self.w.t < self.busy_until - 1e-9:
            gap = self._in_gap()
            _count(self.counts, "interleaving_refused")
            if gap:
                _count(self.counts, "interleaving_in_projection_gap")
            raise LabUnsupported(f"firmware work at {self.w.t:.3f} inside the projected transaction [{self.busy_t0:.3f}, "
                                 f"{self.busy_until:.3f}) of {sorted(self.busy_scripts)} is not modelled"
                                 + self._gap_note(gap))
        self._entry(cmd=cmd, fn=fn)

    def _entry(self, cmd=None, fn=None) -> None:
        fw, t0 = self.fw, self.w.t
        self._apply_bus(t0)
        run = _Run(self, t0, None if cmd is None else {"svc": cmd["svc"], "e": cmd["e"]})
        boot0 = fw.boot_no
        fw.recorder = run
        try:
            if self.raw_until is not None:
                fw.raw_to(_ms(self.raw_until))
                self.raw_until = None
            fw.sync_to(_ms(t0))
            if cmd is not None and fw.boot_no == boot0:
                self._run_cmd(cmd)
            if fn is not None and fw.boot_no == boot0:
                fn()
            if fw.boot_no == boot0:
                run.pubs += [(0.0, hid, st) for hid, st in self._sample_polled()]
        finally:
            fw.recorder = None
        self._finish(run, boot0)

    def _finish(self, run: _Run, boot0: int) -> None:
        fw = self.fw
        run.mark()
        rebooted = fw.boot_no != boot0
        txn = not rebooted and run.busy_el is not None
        scale = 1.0 if txn else 0.0
        for el, d, (act, snap) in run.edges:
            self.cw._log("dongle.edge", {"dom": d, "act": act, "snap": snap, "at": round(run.t0 + el * scale, 3),
                                         "boot": fw.boot_no})
        if txn:
            self.busy_t0, self.busy_until = run.t0, run.t0 + run.busy_el
            self.busy_v0_until = run.t0 + (run.v0_busy_el or 0.0)
            self.busy_own_end = {s: run.t0 + el for s, el in sorted(run.own_end.items())}
            self.raw_until, self.busy_scripts = self.busy_until, frozenset(run.scripts)
            data = {"t0": round(run.t0, 3), "until": round(self.busy_until, 3), "ops": run.ops, "commits": run.commits,
                    "writes": run.writes, "scripts": sorted(run.scripts), "cmd": run.cmd}
            _count(self.counts, "txn")
            if run.n_no_response or run.n_timeout or run.delay_ms:
                # only a projection that differs from V0 carries this key (a V0-equal transaction logs exactly as before)
                data["projection"] = {"no_response": run.n_no_response, "timeout": run.n_timeout,
                                      "delay_ms": run.delay_ms, "v0_until": round(self.busy_v0_until, 3)}
                if run.n_no_response or run.n_timeout:
                    _count(self.counts, "txn_fault_outcome")
                if run.delay_ms:
                    _count(self.counts, "txn_in_lock_delay")
            self.cw._log("dongle.txn", data)
        if run.ops and self.cw.bus.windows == "polls":
            self._bus_polls = [x for x in self._bus_polls if x[1] > run.t0 - 60] + [(run.t0, run.t0 + run.elapsed())]
        if fw.boot_no != self._boot_seen:
            self._reset_polled()
        if rebooted:
            self._self_reboot()
            return
        for el, hid, st in run.pubs:
            self._publish(run.t0 + el * scale + self.lat.publish_s, hid, st)

    # -- driver -----------------------------------------------------------------------------------------------------------
    def start_driver(self) -> None:
        self._drive_gen += 1
        self._schedule()

    def stop_driver(self) -> None:
        self._drive_gen += 1

    def _schedule(self) -> None:
        if self.off:
            return
        fw = self.fw
        t = fw.next_due_ms() / 1000
        for due in self._polled_next.values():
            t = min(t, (fw.utc_ms + max(0, due - fw.sim.now_ms)) / 1000)
        t = max(t, self.w.t, self.busy_until)
        gen = self._drive_gen
        self.w.at(t, lambda: self._drive(gen))

    def _drive(self, gen: int) -> None:
        if gen != self._drive_gen or self.off:
            return
        if self.w.t >= self.busy_until - 1e-9:
            self._entry()
        if not self.off and gen == self._drive_gen:
            self._schedule()

    # -- power ------------------------------------------------------------------------------------------------------------
    def power_off(self) -> dict:
        if self.off:
            raise LabHarnessError("reboot_dongle: the dongle is already powered off")
        self.entry()                          # bring the firmware to the cut instant (fails loud inside a busy window)
        if self.off:
            raise LabUnsupported("reboot_dongle: the firmware restarted itself at the cut instant")
        cap = self.fw.capture_now()
        self.off = True
        self.stop_driver()
        self.cw._log("dongle.power_off", {"boot": self.fw.boot_no})
        self.disconnect("power")
        return cap

    def power_on(self, cap: dict, cut_utc: float, down_s: float, nvs_fault, reconnect_gap_s: float) -> None:
        fw = self.fw
        fw.raw_to(_ms(cut_utc + down_s))      # the unpowered old sim's clock to the power-return instant (nothing runs)
        run = _Run(self, self.w.t, None)
        fw.recorder = run
        try:
            fw.reboot_from(cap, down_s=0, nvs_fault=nvs_fault)
        finally:
            fw.recorder = None
        if fw.utc_ms != _ms(self.w.t):
            raise LabHarnessError(f"power_on: firmware boot at {fw.utc_ms / 1000} != World {self.w.t}")
        self.off = False
        self.busy_until, self.raw_until = -math.inf, None
        self.cw._log("dongle.power_on", {"boot": fw.boot_no, "nvs_fault": None if nvs_fault is None else list(nvs_fault)})
        self._finish(run, fw.boot_no)
        self.start_driver()
        self.w.at(self.w.t + reconnect_gap_s, lambda: self.connect("power"))

    def _self_reboot(self) -> None:
        """The firmware rebooted inside an entry (its restart button, or a cut armed in the firmware): its clock is now at
        the new boot, ahead of the World. The dongle is offline until then, the API back reconnect_gap_s later."""
        fw_t = self.fw.utc_ms / 1000
        self.cw._log("dongle.self_restart", {"boot": self.fw.boot_no, "fw_t": fw_t})
        self.off = True
        self.stop_driver()
        self.busy_until, self.raw_until = -math.inf, None
        self.disconnect("power")

        def up():
            self.off = False
            self.start_driver()
            self.w.at(self.w.t + self.cw.reconnect_gap_s, lambda: self.connect("power"))
        self.w.at(fw_t, up)


# ---------------------------------------------------------------------------------------------------------------------------
# the coupled world
# ---------------------------------------------------------------------------------------------------------------------------
class CoupledWorld:
    """Real FPS1 / DGS1 / SMR1 in one S.World + RealDongle over one CoupledFirmware (module docstring)."""

    def __init__(self, utc_start: int, *, packages=("fps1", "dgs1", "smr1"), package_texts=None, london: bool = True,
                 fw_world_kwargs=None, latencies=None, offline_policy: str = "silent", bus=None, wd_phase_s: float = 0.0,
                 grid_charge_limit_w: int = 8000, reconnect_gap_s: float = 10.0, seed: int = 0):
        if _OPEN:
            raise LabHarnessError("another CoupledWorld is still open: close it first (S.LOCAL and the sim modules are "
                                  "process-global)")
        self.closed = False
        self._local_cm = None
        _OPEN.append(self)
        try:
            S._truthy = _truthy_guard          # the runtime truthiness guard (FAIL-LOUD GUARDS); close() restores it
            if london:
                cm = C.patched_ha_local(S)
                cm.__enter__()
                self._local_cm = cm
            self._build(utc_start, packages, package_texts, london, fw_world_kwargs, latencies, offline_policy, bus,
                        wd_phase_s, grid_charge_limit_w, reconnect_gap_s, seed)
        except BaseException:
            self.close()
            raise

    def _build(self, utc_start, packages, package_texts, london, fw_world_kwargs, latencies, offline_policy, bus,
               wd_phase_s, grid_charge_limit_w, reconnect_gap_s, seed) -> None:
        if isinstance(utc_start, bool) or not isinstance(utc_start, int):
            raise LabHarnessError(f"utc_start must be an int epoch in seconds, got {utc_start!r}")
        packages = tuple(packages)
        if not packages or len(set(packages)) != len(packages) or not set(packages) <= set(PACKAGES):
            raise LabHarnessError(f"packages must be distinct names from {sorted(PACKAGES)}, got {packages!r}")
        if offline_policy not in ("silent", "raise"):
            raise LabHarnessError(f"offline_policy must be 'silent' or 'raise', got {offline_policy!r}")
        if not isinstance(london, bool):
            raise LabHarnessError("london must be a bool")
        wd = _num(wd_phase_s, "wd_phase_s", 0)
        if wd >= 15:
            raise LabHarnessError("wd_phase_s must be in [0, 15) s (the watchdog period)")
        if isinstance(grid_charge_limit_w, bool) or not isinstance(grid_charge_limit_w, int) or grid_charge_limit_w < 0:
            raise LabHarnessError(f"grid_charge_limit_w must be an int >= 0, got {grid_charge_limit_w!r}")
        self.reconnect_gap_s = _num(reconnect_gap_s, "reconnect_gap_s", 0)
        self.lat = latencies if isinstance(latencies, Latency) else Latency(**(latencies or {}))
        self.bus = bus if isinstance(bus, BusModel) else BusModel(**(bus or {}))
        self.offline_policy, self.london, self.packages = offline_policy, london, packages
        texts = dict(package_texts or {})
        if not set(texts) <= set(packages):
            raise LabHarnessError(f"package_texts names {sorted(set(texts) - set(packages))} are not loaded packages")
        self.package_texts = {p: texts.get(p, package_text(p)) for p in packages}
        check_packages(self.package_texts)       # the static guard (FAIL-LOUD GUARDS): raises before anything runs
        # firmware
        kw = dict(fw_world_kwargs or {})
        for bad in ("utc_start", "boot", "seed", "switch_ids"):
            if bad in kw:
                raise LabHarnessError(f"fw_world_kwargs: {bad!r} is set by CoupledWorld")
        warm = kw.pop("warmup_s", 0)
        if isinstance(warm, bool) or not isinstance(warm, int) or warm < 0:
            raise LabHarnessError("fw_world_kwargs warmup_s must be an int >= 0 (the firmware boots that long before)")
        phase = dict(kw.pop("phase_ms", None) or {})
        for job in ("fp_wd", "dump_wd"):
            if job in phase:
                raise LabHarnessError(f"fw_world_kwargs phase_ms[{job!r}]: use wd_phase_s")
            phase[job] = _ms(wd)
        fwd = kw.get("fw") or L.load_fw()
        view_ids = package_dongle_ids(self.package_texts.values()) + [E_CEILING]
        emap = dongle_entity_map(fwd)
        switch_ids = sorted({emap[h][0] for h in view_ids if h in emap and emap[h][1] == "switch"})
        self.fw = CoupledFirmware(utc_start=utc_start - warm, phase_ms=phase, seed=seed, switch_ids=switch_ids, **kw)
        self.log = self.fw.log
        # Home Assistant
        self.w = S.World(float(utc_start))
        D.add_ha_filters(self.w)
        self._by = None
        self.ha = None
        self.ha_up = False
        self._install_world_hooks()
        self.dongle = RealDongle(self, self.fw, sorted(set(view_ids)))
        self.dongle.counts["package_sets_checked"] = 1
        self.w.service_handlers["input_number.set_value"] = self._input_number_handler()
        self.dongle.warm_up(warm)
        if self.fw.utc_ms != utc_start * 1000:
            raise LabHarnessError("the firmware did not reach utc_start after its warm-up")
        self.w.set(E_OPERATING_LIMIT, f"{float(grid_charge_limit_w)}")
        self.w.template_entities[E_LIMIT] = limit_template()
        self.dongle.connect_initial()
        self.ha = self._new_ha()
        self.ha_up = True
        self.ha.start()
        self._schedule_time_triggers()
        self._log("ha.start", {"packages": list(packages), "london": london})
        self.dongle.start_driver()

    # -- plumbing ---------------------------------------------------------------------------------------------------------
    def _t_log(self):
        ms = _ms(self.w.t)
        return ms // 1000 if ms % 1000 == 0 else ms / 1000

    def _log(self, kind: str, data=None, src: str = "lab") -> dict:
        return self.log.append(t_utc=self._t_log(), up_ms=None, boot=None, src=src, kind=kind, data=data)

    def _install_world_hooks(self) -> None:
        w = self.w
        orig_set, orig_call = w.set, w.call

        def set_(entity_id, state, attrs=None):
            old = w.states.get(entity_id)
            changed = old is None or old[0] != str(state)
            if changed:
                self._log("ha.state", {"e": entity_id, "s": str(state)}, src="ha")
            orig_set(entity_id, state, attrs)
            if changed and entity_id.startswith("input_datetime."):
                self._schedule_time_triggers()

        def call_(service, entity_ids, data):
            self._log("ha.call", {"svc": service, "e": list(entity_ids), "data": data, "by": self._by or "ha"}, src="ha")
            try:
                orig_call(service, entity_ids, data)
            finally:
                self._by = None
        w.set, w.call = set_, call_    # per instance (the World is this lab's own object)

    def _input_number_handler(self):
        """input_number.set_value with the helper range HA enforces (REPORTED): a value outside a loaded package helper's
        declared [min, max] raises LabUnsupported (the sim's default handler, _ha_script_sim.py:301-302, would store it);
        otherwise exactly what that default handler stores. An input_number no loaded package declares is stored
        unchecked, counted."""
        ranges = {}
        for text in self.package_texts.values():
            ranges.update(_input_number_ranges(text))
        counts = self.dongle.counts

        def handler(e, d):
            v = float(d["value"])                     # the default handler's conversion (it raises alike)
            _count(counts, "input_number_checked")
            r = ranges.get(e)
            if r is None:
                _count(counts, "input_number_unranged")
            elif not r[0] <= v <= r[1]:
                _count(counts, "input_number_refused")
                raise LabUnsupported(f"input_number.set_value {e} = {v}: outside the helper's declared [min, max] {r}; "
                                     "Home Assistant refuses it (REPORTED), _ha_script_sim would store it (ISS-HA-5; not "
                                     "modelled)")
            self.w.set(e, f"{v}")
        return handler

    def _new_ha(self) -> S.HA:
        ha = S.HA(self.w, [yaml.safe_load(t) for t in self.package_texts.values()])
        orig = ha._action

        def tagged(act, v):   # pattern from home-assistant/tests/test_ecco_schedule_manual_restore.py:100-112, per instance
            if "action" in act:
                self._by = ("smr1" if "plan" in v or "schedule_value" in v else
                            "schedule" if "requested_duration" in v else "ha")
            return (yield from orig(act, v))
        ha._action = tagged
        return ha

    def _schedule_time_triggers(self) -> None:
        if self.ha is not None and self.ha_up and not self.ha.dead:
            for a in self.ha.automations:
                a.schedule_time_triggers()

    def _at(self, at_utc, fn) -> None:
        self._need_open()
        if at_utc is None:
            fn()
            return
        t = _num(at_utc, "at_utc")
        if t < self.w.t - 1e-9:
            raise LabHarnessError(f"at_utc {t} is in the past (World clock {self.w.t})")
        self.w.at(t, fn)

    def _need_open(self) -> None:
        if self.closed:
            raise LabHarnessError("this CoupledWorld is closed")

    def _helper_ids(self) -> list:
        out = []
        for text in self.package_texts.values():
            pkg = yaml.safe_load(text)
            for dom in ("input_boolean", "input_number", "input_text", "input_datetime"):
                out += [f"{dom}.{k}" for k in (pkg.get(dom) or {})]
        return sorted(set(out))

    # -- lifecycle --------------------------------------------------------------------------------------------------------
    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        dongle = getattr(self, "dongle", None)
        if dongle is not None:
            dongle.stop_driver()
        if self in _OPEN:
            _OPEN.remove(self)
        if not _OPEN and S._truthy is _truthy_guard:
            S._truthy = _TRUTHY_SIM
        cm, self._local_cm = self._local_cm, None
        if cm is not None:
            cm.__exit__(None, None, None)

    def __enter__(self) -> "CoupledWorld":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    # -- clock ------------------------------------------------------------------------------------------------------------
    @property
    def t_utc(self):
        t = self.w.t
        return int(t) if float(t).is_integer() else t

    def run_until(self, utc) -> None:
        self._need_open()
        t = _num(utc, "run_until")
        if t < self.w.t - 1e-9:
            raise LabHarnessError(f"run_until({t}) is in the past (World clock {self.w.t})")
        self.w.run_until(t)

    def run_for(self, seconds) -> None:
        self.run_until(self.w.t + _num(seconds, "run_for", 0))

    def advance_to(self, utc) -> None:
        self.run_until(utc)

    # -- actors -----------------------------------------------------------------------------------------------------------
    def arm_schedule(self, dom: str, start_local: str, minutes: int, power_w: int, stop_soc=None, at_utc=None) -> None:
        """The owner sets the schedule helpers and arms it (the arm validation automation runs on the state change)."""
        if dom not in DOMS or _PKG_OF[dom] not in self.packages:
            raise LabHarnessError(f"arm_schedule: dom must be one of the loaded schedules, got {dom!r}")
        if not isinstance(start_local, str) or not _LOCAL_RE.match(start_local):
            raise LabHarnessError(f"arm_schedule: start_local must be 'YYYY-MM-DD HH:MM:SS', got {start_local!r}")
        for v, what in ((minutes, "minutes"), (power_w, "power_w")):
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise LabHarnessError(f"arm_schedule: {what} must be an int >= 1, got {v!r}")
        if (dom == "dump") != (stop_soc is not None) or (stop_soc is not None and (isinstance(stop_soc, bool)
                                                                                   or not isinstance(stop_soc, int))):
            raise LabHarnessError("arm_schedule: stop_soc (an int) is required for 'dump' and refused for 'fp'")

        def go():
            if not self.ha_up:
                raise LabHarnessError("arm_schedule while Home Assistant is down")
            start_utc = S.parse_local(start_local)
            self._log("owner.arm", {"dom": dom, "start_local": start_local, "start_utc": start_utc,
                                    "window_end": start_utc + minutes * 60, "minutes": minutes, "power_w": power_w,
                                    "stop_soc": stop_soc})
            self.w.set(START_HELPER[dom], start_local)
            vals = [(DURATION_HELPER[dom], minutes), (POWER_HELPER[dom], power_w)]
            if dom == "dump":
                vals.append((STOP_SOC_HELPER[dom], stop_soc))
            for helper, v in vals:
                self._by = "owner"
                self.w.call("input_number.set_value", [helper], {"value": v})
            self._by = "owner"
            self.w.call("input_boolean.turn_on", [ARMED[dom]], {})
        self._at(at_utc, go)

    def owner_set(self, entity: str, value, at_utc=None, via: str = "ha") -> None:
        """The owner changes an entity: through Home Assistant (a service call / helper write), or via='dongle' through
        the dongle's own UI (dongle switches / numbers only; no HA, no latency)."""
        dom = str(entity).split(".")[0]
        if via not in ("ha", "dongle"):
            raise LabHarnessError(f"owner_set: via must be 'ha' or 'dongle', got {via!r}")
        if dom in ("switch", "input_boolean"):
            if value in ("on", "off"):
                value = value == "on"
            if not isinstance(value, bool):
                raise LabHarnessError(f"owner_set {entity}: a bool or 'on' / 'off' is required, got {value!r}")
        elif dom in ("number", "input_number"):
            value = _num(value, f"owner_set {entity}")
        elif dom == "input_text":
            if not isinstance(value, str):
                raise LabHarnessError(f"owner_set {entity}: a str is required")
        elif dom == "input_datetime":
            if not isinstance(value, str) or not _LOCAL_RE.match(value):
                raise LabHarnessError(f"owner_set {entity}: 'YYYY-MM-DD HH:MM:SS' is required, got {value!r}")
        else:
            raise LabHarnessError(f"owner_set: unsupported entity domain {dom!r}")
        if via == "dongle" and dom not in ("switch", "number"):
            raise LabHarnessError("owner_set via='dongle' is for dongle switches and numbers only")

        def go():
            self._log("owner.set", {"e": entity, "value": value, "via": via})
            svc, data = ({"switch": ("switch.turn_on" if value else "switch.turn_off", {}),
                          "number": ("number.set_value", {"value": value}),
                          "input_boolean": ("input_boolean.turn_on" if value else "input_boolean.turn_off", {}),
                          "input_number": ("input_number.set_value", {"value": value}),
                          "input_text": ("input_text.set_value", {"value": value})}.get(dom, (None, None)))
            if via == "dongle":
                self.dongle.direct(svc, entity, data, "owner")
                return
            if not self.ha_up:
                raise LabHarnessError("owner_set via Home Assistant while Home Assistant is down (use via='dongle')")
            if dom == "input_datetime":
                self.w.set(entity, value)      # the sim's set_datetime takes only `time`
                return
            self._by = "owner"
            self.w.call(svc, [entity], data)
        self._at(at_utc, go)

    def owner_press(self, button: str, at_utc=None, via: str = "ha") -> None:
        if via not in ("ha", "dongle"):
            raise LabHarnessError(f"owner_press: via must be 'ha' or 'dongle', got {via!r}")
        fid = self.dongle._resolve("button.press", button)[0]

        def go():
            self._log("owner.press", {"e": button, "fid": fid, "via": via})
            if via == "dongle":
                self.dongle.direct("button.press", button, {}, "owner")
                return
            if not self.ha_up:
                raise LabHarnessError("owner_press via Home Assistant while Home Assistant is down (use via='dongle')")
            self._by = "owner"
            self.w.call("button.press", [button], {})
        self._at(at_utc, go)

    def restart_ha(self, at_utc, down_s, rollback_to_utc=None, clear_notifications: bool = True,
                   reconnect_gap_s: float = 10.0, reset_last_changed: bool = True) -> None:
        """Home Assistant stops at at_utc and starts down_s later (ASSUMPTIONS in the module docstring)."""
        down = _num(down_s, "restart_ha down_s", 0)
        gap = _num(reconnect_gap_s, "restart_ha reconnect_gap_s", 0)
        roll = None if rollback_to_utc is None else _num(rollback_to_utc, "rollback_to_utc")

        def stop():
            if not self.ha_up:
                raise LabHarnessError("restart_ha: Home Assistant is already down")
            if roll is not None and roll > self.w.t + 1e-9:
                raise LabHarnessError("restart_ha: rollback_to_utc is after the stop")
            self.ha.stop()
            self.ha_up = False
            self.dongle.disconnect("ha")
            self._log("ha.stop", {"graceful": roll is None})
            if roll is not None:
                self._rollback(roll)
            self.w.at(self.w.t + down, start)

        def start():
            if clear_notifications:
                self._log("ha.notifications_cleared", {"ids": sorted(self.w.notifications)})
                self.w.notifications.clear()
            self.ha = self._new_ha()
            self.ha_up = True
            if not self.dongle.connected:
                self.dongle.mark_unavailable()
            if reset_last_changed:
                ids = [e for e in self._helper_ids() if e in self.w.states]
                for e in ids:
                    self.w.changed_at[e] = self.w.t
                self._log("ha.last_changed_reset", {"n": len(ids)})
            self.ha.start()
            self._schedule_time_triggers()
            self._log("ha.start", {"packages": list(self.packages), "london": self.london})
            self.w.at(self.w.t + gap, lambda: self.dongle.connect("ha"))
        self._at(at_utc, stop)

    def _rollback(self, to_utc: float) -> None:
        """Crash: every package helper back to its value at to_utc (HA's last restore-state save); a helper that did not
        exist then is removed, so the new HA initialises it."""
        last: dict = {}
        for t, e, s in self.w.history:
            if t <= to_utc + 1e-9:
                last[e] = (t, s)
        changes = {}
        for e in self._helper_ids():
            cur = self.w.states.get(e)
            if e in last:
                t, s = last[e]
                if cur is None or cur[0] != s:
                    changes[e] = [None if cur is None else cur[0], s]
                    self.w.states[e] = (s, dict(cur[1]) if cur else {})
                    self.w.changed_at[e] = t
            elif cur is not None:
                changes[e] = [cur[0], None]
                del self.w.states[e]
                self.w.changed_at.pop(e, None)
        self._log("ha.rollback", {"to_utc": to_utc, "changes": changes})

    def reboot_dongle(self, at_utc, down_s: float = 5.0, nvs_fault=None, reconnect_gap_s=None) -> None:
        """A dongle power cut at at_utc, power back down_s later (FirmwareWorld FULL boot), API back reconnect_gap_s
        after on_boot (default: the world's reconnect_gap_s)."""
        down = _num(down_s, "reboot_dongle down_s", 0)
        gap = self.reconnect_gap_s if reconnect_gap_s is None else _num(reconnect_gap_s, "reconnect_gap_s", 0)
        fault = None if nvs_fault is None else tuple(nvs_fault)

        def cut():
            t_cut = self.w.t
            cap = self.dongle.power_off()
            self.w.at(t_cut + down + self.fw.boot_ms / 1000,
                      lambda: self.dongle.power_on(cap, t_cut, down, fault, gap))
        self._at(at_utc, cut)

    def api_outage(self, at_utc, down_s) -> None:
        """The ESPHome API link is down for down_s (the firmware keeps running): entities unavailable, calls offline."""
        down = _num(down_s, "api_outage down_s", 0)

        def go():
            self.dongle.disconnect("api")
            self.w.at(self.w.t + down, lambda: self.dongle.connect("api"))
        self._at(at_utc, go)

    def set_env(self, at_utc=None, **values) -> None:
        """MODEL: the inverter's live telemetry image (FirmwareWorld.telemetry(poll=False)); the firmware's own telemetry
        interval reads it at its next slot."""
        self._at(at_utc, lambda: self.dongle.entry(fn=lambda: self.fw.telemetry(poll=False, **values)))

    def fw_action(self, name: str, at_utc=None, **args) -> None:
        """A firmware environment / fault action of _lab_fw.ACTIONS (FW_ACTIONS only), run as firmware work now."""
        if name not in FW_ACTIONS:
            raise LabHarnessError(f"fw_action: {name!r} is not one of {FW_ACTIONS}")
        self._at(at_utc, lambda: self.dongle.entry(fn=lambda: L.ACTIONS[name](self.fw, **args)))

    def dump_plant(self, *, house_w: int = 50, soc_drop_s: float = 180.0, period_s: float = 5.0) -> None:
        """MODEL (a synthetic plant stand-in, NOT inverter physics - FirmwareWorld has none): every period_s, while the
        firmware holds a Dump lease in export mode (register 244 == 0), the battery discharges at the battery ceiling the
        Dump controller wrote into register 256 (batt_w), the house takes house_w and the rest is exported (grid_w =
        house_w - batt_w); the SOC falls 1 % per soc_drop_s of discharge; otherwise the plant idles (batt_w 0, grid_w =
        house_w). It writes FirmwareWorld.env (the image the firmware's own telemetry interval reads at its next slot) and
        logs env.plant on change. Without it a Dump lease meets a static telemetry image and the firmware's controller
        ends it early (NO RESPONSE / POWER RUNAWAY)."""
        if isinstance(house_w, bool) or not isinstance(house_w, int) or not 0 <= house_w <= 20000:
            raise LabHarnessError(f"dump_plant: house_w must be an int 0..20000, got {house_w!r}")
        drop, period = _num(soc_drop_s, "soc_drop_s", 1), _num(period_s, "period_s", 0.1)
        st = {"dis": 0.0, "last": None}

        def tick():
            if self.closed:
                return
            fw = self.fw
            if not self.dongle.off:
                if fw.sim.g["dump_active_persisted"] and fw.bank.get(244) == 0:
                    b = int(fw.bank[256])
                    env = {"batt_w": b, "grid_w": house_w - b, "house_w": house_w}
                    st["dis"] += period
                    if st["dis"] >= drop:
                        st["dis"] -= drop
                        env["soc"] = max(0, int(fw.env["soc"]) - 1)
                else:
                    env = {"batt_w": 0, "grid_w": house_w, "house_w": house_w}
                fw.env.update(env)
                snap = dict(fw.env)
                if snap != st["last"]:
                    st["last"] = snap
                    self._log("env.plant", snap)
            self.w.after(period, tick)
        self._at(None, tick)

    # -- observers --------------------------------------------------------------------------------------------------------
    def _dom(self, dom: str) -> str:
        if dom not in DOMS:
            raise LabHarnessError(f"dom must be one of {DOMS}, got {dom!r}")
        return dom

    def schedule_status(self, dom: str) -> str:
        return self.w.state(SCHEDULE_STATUS[self._dom(dom)])

    def last_result(self, dom: str) -> str:
        return self.w.state(LAST_RESULT[self._dom(dom)])

    def smr1_state(self, dom: str) -> str:
        return self.w.state(SMR1_STATE[self._dom(dom)])

    def notifications(self) -> dict:
        return {k: dict(v) for k, v in sorted(self.w.notifications.items())}

    def ha_state(self, entity: str) -> str:
        return self.w.state(entity)

    def ha_visible(self) -> dict:
        return self.dongle.ha_visible()

    def firmware(self) -> CoupledFirmware:
        return self.fw

    def fw_status(self, dom: str) -> str:
        return self.fw.status(dom)

    def invariants(self, names=None, params=None, **flat) -> list:
        """names: INV-HF-* and / or firmware (_lab_fw.INVARIANTS) ids, None = every INV-HF-*; the firmware ones run
        through L.check_invariants on the merged log with world = the FirmwareWorld. Parameters as _route_params:
        params={inv id: {name: value}}, or a flat keyword that exactly one selected checker takes."""
        sel = {}
        for n in (names or list(HF_INVARIANTS)):
            fn = HF_INVARIANTS.get(n) or L.INVARIANTS.get(n)
            if fn is None:
                raise LabHarnessError(f"unknown invariant {n!r} (coupled: {sorted(HF_INVARIANTS)}; firmware: "
                                      f"{sorted(L.INVARIANTS)})")
            sel[n] = fn
        kw, out = _route_params(sel, params, flat), []
        for n in sel:
            if n in HF_INVARIANTS:
                out += HF_INVARIANTS[n](self.log, world=self, **kw[n])
            else:
                out += L.check_invariants(self.log, names=[n], world=self.fw, **kw[n])
        return sorted(out, key=lambda v: (v["seq"], v["inv"]))

    def window_overruns(self) -> list:
        return window_overruns(self.log, world=self)


# ---------------------------------------------------------------------------------------------------------------------------
# coupled invariant checkers (over the merged EventLog)
# ---------------------------------------------------------------------------------------------------------------------------
def _evs(events) -> list:
    return events if isinstance(events, list) else list(events)


def _viol(inv: str, e: dict, detail: str, tags=()) -> dict:
    return {"inv": inv, "seq": e["seq"], "detail": detail, "tags": sorted(tags)}


_NUM_DOM = {n: d for d in DOMS for n in NUMBERS[d]}
_SMR_DOM = {v: k for k, v in SMR1_STATE.items()}
_START_DOM = {v: k for k, v in START_BUTTON.items()}
_END_DOM = {v: k for k, v in END_BUTTON.items()}
_ARMED_DOM = {v: k for k, v in ARMED.items()}


def check_hf_one_lease(events, **_kw) -> list:
    evs = _evs(events)
    out = [dict(v, inv="INV-HF-ONE-LEASE", detail="firmware truth: " + v["detail"]) for v in L.check_one_lease(evs)]
    on, both = {"fp": False, "dump": False}, False
    act_dom = {v: k for k, v in ACTIVE.items()}
    for e in evs:
        if e["kind"] == "ha.state" and e["data"]["e"] in act_dom:
            on[act_dom[e["data"]["e"]]] = e["data"]["s"] == "on"
            now = on["fp"] and on["dump"]
            if now and not both:
                out.append(_viol("INV-HF-ONE-LEASE", e, "HA view: Free Power Active and Dump to Grid Active both on"))
            both = now
    return sorted(out, key=lambda v: v["seq"])


def check_hf_arm_off(events, world=None, grace_s: float = 10.0, **_kw) -> list:
    evs, out = _evs(events), []
    st = {d: {"sw": False, "script": False, "owner": False, "since": None} for d in DOMS}
    sw_dom = {ARM[d]: d for d in DOMS}
    sc_dom = {SCRIPT[d]: d for d in DOMS}

    def close(d, t_end):
        s = st[d]
        if s["since"] is not None and t_end - s["since"]["t_utc"] > grace_s:
            out.append(_viol("INV-HF-ARM-OFF", s["since"], f"{d} write enable on for {t_end - s['since']['t_utc']:.1f} s "
                                                           f"while no scheduled start ran (grace {grace_s} s)"))
        s["since"] = None
    for e in evs:
        k, dt, d = e["kind"], e["data"], None
        if k == "ha.state" and dt["e"] in sw_dom:
            d = sw_dom[dt["e"]]
            st[d]["sw"] = dt["s"] == "on"
            if not st[d]["sw"]:
                st[d]["owner"] = False
        elif k == "ha.state" and dt["e"] in sc_dom:
            d = sc_dom[dt["e"]]
            st[d]["script"] = dt["s"] == "on"
        elif k == "dongle.cmd" and dt["svc"] == "switch.turn_on" and dt["e"] in sw_dom:
            d = sw_dom[dt["e"]]
            st[d]["owner"] = dt["by"] == "owner"
        if d is None:
            continue
        s = st[d]
        cond = s["sw"] and not s["script"] and not s["owner"]
        if cond and s["since"] is None:
            s["since"] = e
        elif not cond and s["since"] is not None:
            close(d, e["t_utc"])
    t_end = world.t_utc if world is not None else (evs[-1]["t_utc"] if evs else 0)
    for d in DOMS:
        close(d, t_end)
    return sorted(out, key=lambda v: v["seq"])


def check_hf_smr1_quiet(events, **_kw) -> list:
    out = []
    for e in _evs(events):
        dt = e["data"]
        if e["kind"] == "dongle.cmd" and dt["svc"] == "number.set_value" and dt["by"] == "smr1":
            d = _NUM_DOM.get(dt["e"])
            o = dt["obl"][d] if d else {}
            if d is None or o["act"] or o["snap"] or o["op"]:
                out.append(_viol("INV-HF-SMR1-QUIET", e, f"SMR1 wrote {dt['e']} = {dt['value']} while firmware truth "
                                                         f"shows {d}: {o}"))
    return out


def window_overruns(events, world=None) -> list:
    """For every owner.arm: the projected lease start / end (dongle.edge) and overrun_s = lease end - window end."""
    runs, cur = [], {}
    for e in _evs(events):
        k, dt = e["kind"], e["data"]
        if k == "owner.arm":
            cur[dt["dom"]] = r = {"dom": dt["dom"], "seq": e["seq"], "start_local": dt["start_local"],
                                  "window_end": dt["window_end"], "lease_start": None, "lease_end": None, "overrun_s": None}
            runs.append(r)
        elif k == "dongle.edge" and dt["dom"] in cur:
            r = cur[dt["dom"]]
            if r["lease_start"] is None and dt["act"]:
                r["lease_start"] = dt["at"]
            elif r["lease_start"] is not None and r["lease_end"] is None and not dt["act"] and not dt["snap"]:
                r["lease_end"] = dt["at"]
                r["overrun_s"] = round(dt["at"] - r["window_end"], 3)
    return runs


def check_hf_window(events, world=None, bound_s: float = 30.0, **_kw) -> list:
    evs, out = _evs(events), []
    now = world.t_utc if world is not None else (evs[-1]["t_utc"] if evs else 0)
    for r in window_overruns(evs, world):
        if r["lease_start"] is None:
            continue
        e = {"seq": r["seq"]}
        if r["lease_end"] is None and now - r["window_end"] > bound_s:
            out.append(_viol("INV-HF-WINDOW", e, f"{r['dom']} run of {r['start_local']}: override still held "
                                                 f"{now - r['window_end']:.1f} s after the window end (bound {bound_s} s)"))
        elif r["overrun_s"] is not None and r["overrun_s"] > bound_s:
            out.append(_viol("INV-HF-WINDOW", e, f"{r['dom']} run of {r['start_local']}: override ended {r['overrun_s']} s "
                                                 f"after the window end (bound {bound_s} s)"))
    return out


def check_hf_owner_intent(events, **_kw) -> list:
    out = []
    st = {d: {"ended": False, "press_by": None, "act": False} for d in DOMS}
    for e in _evs(events):
        k, dt = e["kind"], e["data"]
        if k == "owner.arm":
            st[dt["dom"]].update(ended=False, press_by=None)
        elif k == "owner.press" and dt["fid"] in _END_DOM:
            st[_END_DOM[dt["fid"]]]["ended"] = True
        elif k == "owner.set" and dt["e"] in _ARMED_DOM and dt["value"] is False:
            st[_ARMED_DOM[dt["e"]]]["ended"] = True
        elif k == "dongle.cmd" and dt["svc"] == "button.press" and dt["fid"] in _START_DOM:
            st[_START_DOM[dt["fid"]]]["press_by"] = dt["by"]
        elif k == "dongle.edge":
            s = st[dt["dom"]]
            if dt["act"] and not s["act"] and s["ended"] and s["press_by"] == "schedule":
                out.append(_viol("INV-HF-OWNER-INTENT", e, f"{dt['dom']} lease started at {dt['at']} from a schedule START "
                                                           f"press after the owner ended / disarmed that run"))
            s["act"] = dt["act"]
    return out


def check_hf_no_false_success(events, **_kw) -> list:
    out, expected, cur = [], {}, {}
    for e in _evs(events):
        k, dt = e["kind"], e["data"]
        if k == "dongle.cmd" and dt["svc"] == "number.set_value":
            n = dt["e"]
            if dt["by"] == "schedule" and n not in expected:
                expected[n] = dt["old"]
            elif dt["by"] == "owner":
                expected[n] = dt["value"]
            cur[n] = dt["value"]
        elif k == "ha.state" and dt["e"] in _SMR_DOM:
            d, s = _SMR_DOM[dt["e"]], dt["s"]
            if s.startswith("RESTORED"):
                bad = {n: {"reads": cur.get(n), "owner": expected[n]} for n in NUMBERS[d]
                       if n in expected and cur.get(n) != expected[n]}
                if bad:
                    out.append(_viol("INV-HF-NO-FALSE-SUCCESS", e, f"SMR1 says {s[:40]!r} while {bad}"))
            if s.split(" ")[0] in ("RESTORED", "PARTIAL", "FAILED", "STALE", "KEPT"):
                for n in NUMBERS[d]:
                    expected.pop(n, None)
    return out


HF_INVARIANTS = {"INV-HF-ONE-LEASE": check_hf_one_lease, "INV-HF-ARM-OFF": check_hf_arm_off,
                 "INV-HF-SMR1-QUIET": check_hf_smr1_quiet, "INV-HF-WINDOW": check_hf_window,
                 "INV-HF-OWNER-INTENT": check_hf_owner_intent, "INV-HF-NO-FALSE-SUCCESS": check_hf_no_false_success}


def _takes(fn) -> list:
    """The parameters a checker names besides events / world (its **_kw catch-all names none)."""
    return sorted(n for n, p in inspect.signature(fn).parameters.items()
                  if n not in ("events", "world") and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY))


def _route_params(checkers: dict, params, flat: dict) -> dict:
    """{inv id: kwargs} for the selected checkers {inv id: fn}. params {inv id: {name: value}} sets one invariant's
    parameters; a flat keyword goes to the ONE selected checker that takes it. Fail loud (LabHarnessError), never dropped:
    params for an unselected invariant, a name its checker does not take, a flat name that no selected checker or more
    than one takes (bound_s with INV-HF-WINDOW and INV-RESTORE-BOUND: use params), or one name given both ways."""
    out = {n: {} for n in checkers}
    if params is not None and not isinstance(params, dict):
        raise LabHarnessError(f"invariant params must be {{inv id: {{name: value}}}}, got {params!r}")
    for inv, kw in (params or {}).items():
        if inv not in checkers:
            raise LabHarnessError(f"invariant params for {inv!r}, which is not selected ({sorted(checkers)})")
        if not isinstance(kw, dict):
            raise LabHarnessError(f"invariant params[{inv!r}] must be a dict of parameters, got {kw!r}")
        bad = sorted(set(kw) - set(_takes(checkers[inv])))
        if bad:
            raise LabHarnessError(f"{inv} takes no parameter {bad} (it takes {_takes(checkers[inv])})")
        out[inv].update(kw)
    for name, value in flat.items():
        takers = [inv for inv, fn in checkers.items() if name in _takes(fn)]
        if len(takers) != 1:
            raise LabHarnessError(f"invariant parameter {name}={value!r}: {len(takers)} of the selected checkers "
                                  f"{sorted(checkers)} take it {takers}; pass params={{inv id: {{{name!r}: ...}}}}")
        if name in out[takers[0]]:
            raise LabHarnessError(f"invariant parameter {name!r} for {takers[0]} given twice (flat and params)")
        out[takers[0]][name] = value
    return out


def check_hf_invariants(events, names=None, world=None, params=None, **flat) -> list:
    """The selected INV-HF-* checkers (None = all); parameters as _route_params (unknown or unused ones raise)."""
    evs, sel = _evs(events), {}
    for name in (names or list(HF_INVARIANTS)):
        if name not in HF_INVARIANTS:
            raise LabHarnessError(f"unknown coupled invariant {name!r}")
        sel[name] = HF_INVARIANTS[name]
    kw, out = _route_params(sel, params, flat), []
    for name, fn in sel.items():
        out += fn(evs, world=world, **kw[name])
    return sorted(out, key=lambda v: (v["seq"], v["inv"]))


# ---------------------------------------------------------------------------------------------------------------------------
# replay tier 'coupled'
# ---------------------------------------------------------------------------------------------------------------------------
def make_world(*, utc_start: int, seed: int, **kw) -> CoupledWorld:
    """The replay factory: JSON kwargs (latencies / bus dicts; fw_world_kwargs bank keys may be strings)."""
    if "package_texts" in kw:
        raise LabHarnessError("replay worlds always run the worktree packages")
    fwk = dict(kw.pop("fw_world_kwargs", None) or {})
    if "fw" in fwk:
        raise LabHarnessError("replay worlds always run the worktree firmware")
    if "bank" in fwk:
        fwk["bank"] = {int(a) if isinstance(a, str) and a.isdigit() else a: v for a, v in fwk["bank"].items()}
    if "packages" in kw:
        kw["packages"] = tuple(kw["packages"])
    return CoupledWorld(utc_start, seed=seed, fw_world_kwargs=fwk, **kw)


def _a_reboot(cw, at_utc=None, down_s=5.0, nvs_fault=None, reconnect_gap_s=None):
    cw.reboot_dongle(at_utc, down_s=down_s, nvs_fault=nvs_fault, reconnect_gap_s=reconnect_gap_s)


def _a_fw(cw, name, at_utc=None, args=None):
    cw.fw_action(name, at_utc=at_utc, **(args or {}))


ACTIONS = {
    "arm_schedule": lambda cw, **a: cw.arm_schedule(**a), "owner_set": lambda cw, **a: cw.owner_set(**a),
    "owner_press": lambda cw, **a: cw.owner_press(**a), "restart_ha": lambda cw, **a: cw.restart_ha(**a),
    "reboot_dongle": _a_reboot, "api_outage": lambda cw, **a: cw.api_outage(**a),
    "set_env": lambda cw, at_utc=None, **a: cw.set_env(at_utc, **a), "fw_action": _a_fw,
    "run_for": lambda cw, seconds: cw.run_for(seconds),
}
OBSERVERS = {
    "schedule_status": lambda cw, dom: cw.schedule_status(dom), "last_result": lambda cw, dom: cw.last_result(dom),
    "smr1_state": lambda cw, dom: cw.smr1_state(dom), "notifications": lambda cw: cw.notifications(),
    "ha_state": lambda cw, entity: cw.ha_state(entity), "ha_visible": lambda cw: cw.ha_visible(),
    "fw_status": lambda cw, dom: cw.fw_status(dom), "fw_ha_view": lambda cw: cw.fw.ha_view(),
    "bank": lambda cw, addrs: cw.fw.bank_view(addrs), "nvs_marker": lambda cw, dom: cw.fw.nvs_marker(dom),
    "writes": lambda cw: cw.fw.writes(),
    "invariants": lambda cw, names=None, params=None, **flat: cw.invariants(names, params, **flat),
    "window_overruns": lambda cw: cw.window_overruns(), "t_utc": lambda cw: cw.t_utc,
    "boot_no": lambda cw: cw.fw.boot_no,
}
T.register_tier(TIER, make_world)
T.register_actions(TIER, ACTIONS)
T.register_observers(TIER, OBSERVERS)
