"""Assurance lab V0, RTC tier: thin wrappers over registry/tests/_fbd1_harness.make_rig (D1Sim) for the two Europe/London DST
nights, with the real Free Power START script and the real Free Power 15 s lease watchdog on the same D1Sim, extraction of the
RTC lock windows (for split-model replay into a FirmwareWorld), RTC correction and Free Power lease timelines, the
test_fbd1_liveness invariants, and the replay tier 'rtc' (test-only helper: no network, no Home Assistant, no hardware; it reads
repository files and writes nothing).

THE RTC POLICY RUNS AS THE PYTHON MIRROR. Every ecco_rtc:: call inside the firmware lambdas is resolved by the FB-B harness onto
registry/rtc_policy.py (_fbb_harness.py:1113 'self._fbr = FbcapNamespace(sim, None, default_module="rtc_policy", ns="ecco_rtc")'),
NOT onto firmware/include/ecco_rtc_policy.h. Header == mirror is enforced only by registry/tests/test_rtc_policy.py section [4]
('def section_parity() -> None:', :652), which needs a C++ compiler: ECCO_CXX when set, else the first of g++, c++,
clang++ found on PATH (test_rtc_policy.find_compiler); without one that check fails rather than skips. Everything here
proves the firmware YAML lambdas plus the mirror under the simulator's model, not the compiled binary.

PUBLIC API
  errors   RtcLabError (harness misuse or invalid input: unknown kind, outcome typo, bad start, clock misuse, unknown global /
           button); RtcLabUnsupported(RtcLabError) (deliberately not modelled: a D1Sim reboot)
  consts   KINDS = ('fall', 'spring'); CHANGE_UTC {kind: epoch s} (= _lab_clock.DST_FALL_2026_UTC / DST_SPRING_2027_UTC);
           DEFAULT_START_LOCAL {kind: (y, m, d, h, mi, s)} (the PW11 starts of test_fbd1_liveness.sc_dst);
           WRITE_OUTCOMES (= _fbd1_harness.WRITE_OUTCOMES, aliases refused); READ_OUTCOMES (= _fbb1_engine.FRAME_OUTCOMES);
           REASON_NAMES {rtc_policy R_* value: 'large' | 'quiet' | ...}; SYNTHETIC_ORIGINAL (bank) and SYNTHETIC_BATTERY_V;
           FP_WRITE_SURFACE; FP_TAGS; SOURCE_ANCHORS ((path, text, line at writing), re-counted by the self-test)
  dst_night_rig(kind='fall', start_local=None, *, start_utc=None, fp_lease=False, fp_minutes=40, fp_power_w=6000,
                write_outcomes=None, verify_outcomes=None, regular_outcomes=None, rate=0.0, offset_s=-2.0,
                image_period_ms=0, image_phase_ms=0, tou=GOLD_TOU, fp_phase_ms=0, oracle=True, seed=0, text=None) -> RtcWorld
      make_rig(text, local=start, offset_s, rate, image_period_ms, image_phase_ms, tou, oracle, seed) (deferred reads and
      writes, 120 ms, threshold 20 s, Automatic Clock Sync on, intervals rtc_read + rtc_tick) + the synthetic bank + the FP
      watchdog interval (found by content, exactly one; started from the rig boot with phase fp_phase_ms) + validated outcomes.
      start: start_local (Europe/London wall time; an ambiguous one is read as BST, like make_rig) OR start_utc (epoch s; the
      GMT copy of the repeated hour is refused); default DEFAULT_START_LOCAL[kind]; |start - change| <= 24 h.
      outcomes: each a str / FrameSpec, a non-empty list of them (consumed in order, the last repeats) or a callable(sim)
      whose every result is checked when used; anything outside WRITE_OUTCOMES / READ_OUTCOMES raises RtcLabError at once.
      fp_lease=True presses the real START button at the start instant (fp_start(fp_minutes, fp_power_w)).
  class RtcWorld (also the replay world)
      .sim (the D1Sim), .kind, .change_utc, .seed, .log (_lab_trace.EventLog), .boot (always 0), .fp_used, .fp_watchdog_idx
      .t_utc -> float epoch s (sim.clock.utc_ms() / 1000; ms resolution)
      advance_to(utc_s) / run_for(seconds) / run_to_change(delta_s=0.0): run the sim; times must lie on the 1 ms grid and
          never go backwards (RtcLabError); every call harvests new firmware evidence into .log
      fp_start(minutes=40, power_w=6000): MODEL stand-ins (battery voltage, configuration_online), stage the two FP numbers,
          arm free_power_write_enable through sim.operator_switch (HA switch.turn_on), press start_free_power_button (HA
          button.press); the START runs on as the world advances (about 1.2 s)
      set_outcomes(write=None, verify=None, regular=None): validated like the rig's outcomes and bound to THIS sim with a
          fresh list-consumption state (all None = every outcome 'ok'); rtc_offset(offset_s) / rtc_rate(rate) /
          rtc_step(seconds) (InverterRtc.set_offset / set_rate / step at the current instant); poke(name, value) (an
          existing global, bool / int; D1Sim.poke, exempt from the state audit); press(button) (read_inverter_clock |
          sync_inverter_clock, the HA presses)
      observers (read-only, never append to .log): lock_windows(); corrections(after_change=None); decisions(
          after_change=None); fp_statuses(); fp_leases(); fp_status(); invariants(); rtc_offset_s(); results()
      close(): restores the sim's previous event_hook; later clock / action calls raise RtcLabError
      sim.reboot() raises RtcLabUnsupported (per-instance guard against the known FbbSim.reboot hazard)
  lock_windows(sim) -> [(utc_a, utc_b | None)]   from sim.cip_edges (strictly alternating, else RtcLabError), UTC float s
  corrections(sim) -> [dict]   one per lock window: queued_utc, released_utc, held_s, reason (oracle reason of the regular read
      that queued it, None for a manual / poked lock), decided_err_s (what that read saw), err_before_s / err_after_s (the
      InverterRtc model's true error vs NTP local at queue / release), writes ([FC16 22-24 outcomes]), results
      ([last_correction_result texts]), result (the last one), verified (result starts with 'Verified OK')
  invariant_violations(sim, *, fp=False) -> {i1, i2, i3, i6, audit, state, wire, nvs, oracle: [str]}   the
      test_fbd1_liveness.inv() set. fp=False: exactly D1Sim's state / wire / nvs audits. fp=True (a Free Power lease ran):
      state = D1Sim.state_violations() minus globals an 'other'-path lambda (the FP scripts / watchdog) assigned through
      set_global; wire = RTC issuers only RTC frames, poll issuers only poll frames, FC16 22 only from write_inverter_rtc,
      other issuers only start_free_power_override* / restore_free_power_snapshot*, never registers 22-24, writes only inside
      FP_WRITE_SURFACE; nvs = no direct-NVS operation or load, every durable commit a Free Power tag (FP_TAGS)
  fp_watchdog_index(fw) -> int   the 15 s interval whose actions name free_power_end_epoch (exactly one, else RtcLabError)
  rtc_world(*, utc_start, seed, **kw) -> RtcWorld   the replay factory (kw: kind, fp_lease, fp_minutes, fp_power_w,
      write_outcomes, verify_outcomes, regular_outcomes, rate, offset_s, image_period_ms, image_phase_ms, tou, fp_phase_ms)
  replay tier 'rtc' (registered at import):
      actions   run_for(seconds), fp_start(minutes=40, power_w=6000), set_outcomes(write, verify, regular),
                rtc_offset(offset_s), rtc_rate(rate), rtc_step(seconds), poke(name, value), press(button)
      observers lock_windows, corrections(after_change), n_corrections(after_change, reason, verified), decisions(
                after_change), fp_leases, fp_status, invariants ({name: count}), rtc_offset_s, results, global_value(name)
  EVENT LOG (src 'fw', up_ms = sim millis, boot 0): rtc.decision {reason, err_s, correct}, rtc.lock {held}, mb.write {addr, n,
      outcome, issuer}, rtc.result {text}, fp.status {text}, nvs.commit {tag, ok[, end_epoch]}, oracle.mismatch, inv.i1, inv.i3;
      plus one src 'lab' rtc.rig event at build.

MODEL ASSUMPTIONS (MODEL = modelled here or inherited from make_rig, with the reason)
  - Wall clock: _fbd1_harness.WallClock (exact NTP, no jitter, hand-coded Europe/London rule, valid = sim.ntp_valid). The world
    timeline is that clock's UTC; this module never steps it (an SNTP step would move t_utc).
  - Inverter clock: _fbd1_harness.InverterRtc ('class InverterRtc:', _fbd1_harness.py:245), naive local time = local + offset
    + rate * elapsed; errors are measured against NTP local time.
  - Rig boot (inherited from make_rig): on_boot is NOT run; millis() starts at ds.Sim's 1_000_000 ('self.now_ms = 1_000_000',
    _dump_sim.py:1318). The RTC lambdas and the FP watchdog use millis() differences and the epoch only.
  - Modbus: the _fbb1_engine hub (one frame in flight, writes ahead of queued reads, 120 ms latency, deferred outcomes).
  - Free Power START inputs (MODEL, because no telemetry or configuration poll runs in this rig): ecco_battery_voltage =
    SYNTHETIC_BATTERY_V (52.0 V) and configuration_online = True are set as entity states (no hooks) right before the press;
    the gate refuses otherwise ('else if (!id(configuration_online).state) id(free_power_status).publish_state("REJECTED -
    inverter configuration offline");', firmware yaml:9933; 'REJECTED - plausible live battery voltage required for W-to-A
    conversion', :9935). The staged numbers are set as HA number.set_value would (optimistic template numbers, range-checked
    against the firmware's own min / max).
  - Bank: SYNTHETIC_ORIGINAL (the spec 2.3 synthetic site; NOT site values) with 250..255 = the rig's TOU words so that the
    bank and the RTC TOU cache (manual_cfg_reg250..255_raw, poked by make_rig) agree.
  - Intervals: only rtc_read (60 s, 30 s delay), rtc_tick (1 s, 5 s delay) and the FP watchdog (15 s, 15 s delay + phase) run;
    the telemetry / configuration polls, the Dump watchdog, the export trip, the census and the other intervals do not.
  - Event-log order: events of the same millisecond are ordered by a fixed source rank (decision, lock, write, result /
    status, commit, mismatch, i1, i3), not by causality; the order is deterministic.

NOT MODELLED (fail loud where reachable)
  - A dongle reboot on a D1Sim. FbbSim.reboot() builds a plain sim without WallClock / InverterRtc and carries the OLD sim's
    hooks ('for attr in ("ntp_valid", "epoch", "hour", "minute", "outcome_fn", "read_override_fn", "modbus_mode",',
    _fbb_harness.py:1680; 'self.read_override_fn = self._rtc_read_override', _fbd1_harness.py:584). reboot_d1 is not provided
    (spec 2.4: not required, and no V0 RTC scenario needs it); sim.reboot() raises RtcLabUnsupported.
  - A Dump to Grid lease on D1Sim: the real START raises FbbNotModelled at 'dump_owed_stop_soc_rec->update();' (firmware
    yaml:18478). Use lock_windows() and replay the windows into a FirmwareWorld (split model, RT-03).
  - A start inside the GMT copy of the repeated hour (make_rig's utc_of_local reads an ambiguous wall time as BST): refused.
  - Inverter TOU zone switching on the inverter's own clock, SNTP resync / wrong NTP, the compiled C++ header at run time,
    Home Assistant.

SOURCE ANCHORS (text, line at writing; SOURCE_ANCHORS below, each re-counted by test_lab_selftest_rtc)
  firmware yaml:24120 'if (id(free_power_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress))
      return false;' (the FP watchdog skips while the RTC lock is held); :24138 'return (uint32_t) now.timestamp >=
      id(free_power_end_epoch);' (the lease ends on its UTC epoch); :9092 'uint32_t end_epoch = (uint32_t) now.timestamp +
      (minutes * 60U);'; :9930 the 'REJECTED - RTC correction currently active' Free Power refusal; :18478 (above)
  registry/tests/_fbd1_harness.py:1058 'def make_rig(', :584 (above); registry/tests/_fbb_harness.py:1113, :1680 (above);
  registry/tests/test_fbd1_liveness.py:1067 / :1069 the sc_dst starts; registry/tests/test_rtc_policy.py:652 (above)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yaml  # noqa: E402

import _dump_sim as ds  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbd1_harness as X  # noqa: E402
import rtc_policy as rp  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402

FW_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"


class RtcLabError(Exception):
    """Harness misuse or invalid input (fail loud; never turned into a pass)."""


class RtcLabUnsupported(RtcLabError):
    """Something this wrapper deliberately does not model."""


KINDS = ("fall", "spring")
CHANGE_UTC = {"fall": C.DST_FALL_2026_UTC, "spring": C.DST_SPRING_2027_UTC}
DEFAULT_START_LOCAL = {"fall": (2026, 10, 25, 1, 50, 15), "spring": (2027, 3, 28, 0, 50, 15)}
MAX_START_DISTANCE_S = 86400
WRITE_OUTCOMES = tuple(X.WRITE_OUTCOMES)
READ_OUTCOMES = tuple(E.FRAME_OUTCOMES)
REASON_NAMES = {v: k[2:].lower() for k, v in vars(rp).items() if k.startswith("R_") and isinstance(v, int)}

# Synthetic site (spec 2.3 SITE; NOT site values). 250..255 are filled from the rig's TOU words.
SYNTHETIC_ORIGINAL = {244: 2, 230: 120, 231: 0, 232: 0,
                      **dict(zip(range(256, 262), (8000, 8000, 7000, 8000, 8000, 5000))),
                      **dict.fromkeys(range(262, 268), 0),
                      **dict.fromkeys(range(268, 274), 20),
                      **dict(zip(range(274, 280), (1, 0, 0, 0, 0, 0)))}
SYNTHETIC_BATTERY_V = 52.0
FP_OWNED = (230, 232) + tuple(range(256, 262)) + tuple(range(268, 280))
FP_WRITE_SURFACE = frozenset(FP_OWNED)
FP_TAGS = frozenset({ds.Durable.FREE_POWER_DATA_TAG, ds.Durable.FREE_POWER_VALID_TAG, ds.Durable.FREE_POWER_RETRY_TAG,
                     ds.Durable.FREE_POWER_START_JOURNAL_TAG})
FP_ISSUER_PREFIXES = ("start_free_power_override", "restore_free_power_snapshot")
FP_STATUS = "free_power_status"
FP_START_BUTTON = "start_free_power_button"
FP_ARM = "free_power_write_enable"
FP_RESTORED_TEXT = "RESTORED OK - original inverter settings verified"

SOURCE_ANCHORS = (
    (FW_REL, "if (id(free_power_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;",
     24120),
    (FW_REL, "return (uint32_t) now.timestamp >= id(free_power_end_epoch);", 24138),
    (FW_REL, "uint32_t end_epoch = (uint32_t) now.timestamp + (minutes * 60U);", 9092),
    (FW_REL, 'else if (id(correction_in_progress)) id(free_power_status).publish_state("REJECTED - RTC correction currently '
             'active");', 9930),
    (FW_REL, 'else if (!id(configuration_online).state) id(free_power_status).publish_state("REJECTED - inverter configuration '
             'offline");', 9933),
    (FW_REL, "REJECTED - plausible live battery voltage required for W-to-A conversion", 9935),
    (FW_REL, "dump_owed_stop_soc_rec->update();", 18478),
    ("registry/tests/_fbd1_harness.py", "def make_rig(", 1058),
    ("registry/tests/_fbd1_harness.py", "self.read_override_fn = self._rtc_read_override", 584),
    ("registry/tests/_fbd1_harness.py", "class InverterRtc:", 245),
    ("registry/tests/_fbb_harness.py", 'self._fbr = FbcapNamespace(sim, None, default_module="rtc_policy", ns="ecco_rtc")', 1113),
    ("registry/tests/_fbb_harness.py",
     'for attr in ("ntp_valid", "epoch", "hour", "minute", "outcome_fn", "read_override_fn", "modbus_mode",', 1680),
    ("registry/tests/_dump_sim.py", "self.now_ms = 1_000_000", 1318),
    ("registry/tests/test_fbd1_liveness.py", "day, local = (2026, 10, 25), (2026, 10, 25, 1, 50, 15)", 1067),
    ("registry/tests/test_fbd1_liveness.py", "day, local = (2027, 3, 28), (2027, 3, 28, 0, 50, 15)", 1069),
    ("registry/tests/test_rtc_policy.py", "def section_parity() -> None:", 652),
)


# ---------------------------------------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------------------------------------
def _num(x, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise RtcLabError(f"{what}: a finite number is required, got {x!r}")
    return x


def _to_ms(x, what: str) -> int:
    """Seconds -> integer ms; the value must lie on the 1 ms grid (within 1e-6 s)."""
    ms = round(_num(x, what) * 1000)
    if abs(ms / 1000 - x) > 1e-6:
        raise RtcLabError(f"{what}: {x!r} is not on the 1 ms grid of the simulator")
    return int(ms)


def _utc(sim, t_ms: int) -> float:
    return sim.clock.utc_ms(int(t_ms)) / 1000


def _checked_outcome(r, allowed: tuple, what: str):
    o = r.outcome if isinstance(r, E.FrameSpec) else r
    if not isinstance(o, str) or o not in allowed:
        raise RtcLabError(f"{what} outcome {o!r} is not one of {allowed}")
    return r


def _outcome_spec(spec, allowed: tuple, what: str):
    """Validated spec for _fbd1_harness.outcomes(): None, a str / FrameSpec, a non-empty list / tuple of them, or a callable
    whose every result is checked when it is used."""
    if spec is None:
        return None
    if isinstance(spec, (list, tuple)):
        if not spec:
            raise RtcLabError(f"{what} outcomes: an empty list")
        return [_checked_outcome(x, allowed, what) for x in spec]
    if callable(spec) and not isinstance(spec, E.FrameSpec):
        return lambda sim, fn=spec: _checked_outcome(fn(sim), allowed, what)
    return _checked_outcome(spec, allowed, what)


def _maker(write, verify, regular):
    """An outcomes() maker (or None when every spec is None); typos raise RtcLabError here, before anything runs."""
    w = _outcome_spec(write, WRITE_OUTCOMES, "write")
    v = _outcome_spec(verify, READ_OUTCOMES, "verify")
    r = _outcome_spec(regular, READ_OUTCOMES, "regular")
    if w is None and v is None and r is None:
        return None
    return X.outcomes(write=w, verify=v, regular=r)


_FP_WD: dict = {}


def fp_watchdog_index(fw: dict) -> int:
    """The Free Power lease watchdog: the one 15 s interval whose actions name free_power_end_epoch."""
    hit = _FP_WD.get(id(fw))
    if hit is not None and hit[0] is fw:
        return hit[1]
    idx = [i for i, iv in enumerate(fw.get("interval") or [])
           if str(iv.get("interval")) == "15s" and "free_power_end_epoch" in yaml.dump(iv.get("then"))]
    if len(idx) != 1:
        raise RtcLabError(f"{len(idx)} 15 s intervals name free_power_end_epoch (want exactly one): {idx}")
    _FP_WD[id(fw)] = (fw, idx[0])
    return idx[0]


def _number_range(sim, number_id: str) -> tuple:
    for n in sim.fw.get("number") or []:
        if n.get("id") == number_id:
            return (float(ds.substitute(str(n["min_value"]), sim.subs)), float(ds.substitute(str(n["max_value"]), sim.subs)))
    raise RtcLabError(f"number {number_id!r} does not exist in the firmware")


def _windows_ms(sim) -> list:
    """[(a_ms, b_ms | None)] from sim.cip_edges, which must alternate True / False starting with True."""
    out, start = [], None
    for i, (t, held) in enumerate(sim.cip_edges):
        if bool(held) == (start is not None):
            raise RtcLabError(f"cip_edges[{i}] = {(t, held)!r} does not alternate (edges {sim.cip_edges[:i + 1]!r})")
        if held:
            start = t
        else:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, None))
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# extraction (on a D1Sim)
# ---------------------------------------------------------------------------------------------------------------------------
def lock_windows(sim) -> list:
    """The RTC lock (correction_in_progress) windows as UTC epoch seconds [(a, b | None)] (None = still held)."""
    return [(_utc(sim, a), None if b is None else _utc(sim, b)) for a, b in _windows_ms(sim)]


def corrections(sim) -> list:
    """One dict per lock window (see the module docstring)."""
    reads = {}
    for rd in sim.oracle_reads:
        reads.setdefault(rd["t"], rd)
    out = []
    for a, b in _windows_ms(sim):
        rd = reads.get(a)
        queued_by_read = rd is not None and rd["action"] == rp.ACT_CORRECT
        res = [v for t, n, v in sim.pub_times if n == "last_correction_result" and t >= a and (b is None or t <= b)]
        wr = [w.outcome for w in sim.write_log if w.addr == 22 and w.t >= a and (b is None or w.t <= b)]
        out.append({
            "queued_utc": _utc(sim, a), "released_utc": None if b is None else _utc(sim, b),
            "held_s": None if b is None else (b - a) / 1000,
            "reason": REASON_NAMES[rd["reason"]] if queued_by_read else None,
            "decided_err_s": int(rd["err"]) if queued_by_read else None,
            "err_before_s": round(sim.rtc.offset_s(a), 3),
            "err_after_s": None if b is None else round(sim.rtc.offset_s(b), 3),
            "writes": wr, "results": res, "result": res[-1] if res else None,
            "verified": bool(res) and res[-1].startswith("Verified OK"),
        })
    return out


def _fp_scope_wire(sim) -> list:
    out = []
    for w in sim.wire_log:
        if w.origin != "fw":
            continue
        key = (w.kind, w.addr, w.count)
        regs = set(range(w.addr, w.addr + w.count))
        if w.kind == "write" and w.addr == 22 and w.issuer != "write_inverter_rtc":
            out.append(f"FC16 22 from {w.issuer}")
        if w.issuer in X.RTC_ISSUERS:
            if key not in X.RTC_FRAMES:
                out.append(f"RTC path sent {key}")
        elif w.issuer in X.POLL_ISSUERS:
            if key not in X.POLL_FRAMES:
                out.append(f"poll path sent {key}")
        else:
            if not (isinstance(w.issuer, str) and w.issuer.startswith(FP_ISSUER_PREFIXES)):
                out.append(f"frame {key} from {w.issuer} (not an RTC, poll or Free Power path)")
            if regs & {22, 23, 24}:
                out.append(f"{w.issuer} touched the RTC registers {key}")
            if w.kind == "write" and not regs <= FP_WRITE_SURFACE:
                out.append(f"write {key} from {w.issuer} outside the Free Power write surface")
    return out


def _fp_scope_nvs(sim) -> list:
    if sim.nvs_mark is None:
        return ["mark_nvs() was never called"]
    direct0, commits0, loads0, events0 = sim.nvs_mark
    out = []
    if len(sim.nvs_direct.ops) != direct0 or sum(1 for e in sim.events if e and e[0] == "nvs") != events0:
        out.append("direct NVS activity")
    if len(sim.nvs_loads) != loads0:
        out.append(f"durable loads {sim.nvs_loads[loads0:]}")
    out += [f"durable commit of {key} (not a Free Power tag)" for key, _rec in sim.nvs_commits[commits0:] if key not in FP_TAGS]
    return out


def invariant_violations(sim, *, fp: bool = False) -> dict:
    """The test_fbd1_liveness.inv() invariants as {name: [violation text]} (see the module docstring for fp=True)."""
    if fp:
        state = [k for k in sim.state_violations() if ("other", k) not in sim.assign_seen]
        wire, nvs = _fp_scope_wire(sim), _fp_scope_nvs(sim)
    else:
        state, wire, nvs = list(sim.state_violations()), list(sim.wire_violations()), list(sim.nvs_violations())
    return {
        "i1": [f"{t}: {flags}" for t, flags in sim.i1_violations],
        "i2": [f"{t}: {n} RTC frames" for t, n in sim.i2_violations],
        "i3": [f"{t}: {msg}" for t, msg in sim.i3_violations],
        "i6": [f"{t}: {why}" for t, ok, why in sim.successes if not ok],
        "audit": list(sim.audit_violations()), "state": state, "wire": wire, "nvs": nvs,
        "oracle": [f"{t}: {field} want {want!r} got {got!r}" for t, field, want, got in sim.oracle_mismatches]
        if sim.oracle_on else [],
    }


# ---------------------------------------------------------------------------------------------------------------------------
# the world
# ---------------------------------------------------------------------------------------------------------------------------
_PUB_KINDS = {"last_correction_result": "rtc.result", FP_STATUS: "fp.status"}


class RtcWorld:
    """A DST-night D1Sim with an event log (build it with dst_night_rig() or rtc_world())."""

    def __init__(self, sim, *, kind: str, seed: int, fp_watchdog_idx: int):
        self.sim, self.kind, self.seed = sim, kind, int(seed)
        self.change_utc = CHANGE_UTC[kind]
        self.log = T.EventLog()
        self.boot = 0
        self.fp_used = False
        self.fp_watchdog_idx = fp_watchdog_idx
        self.closed = False
        self._commits: list = []  # (t_ms, ('commit', key, record, ok)) through sim.event_hook
        self._cur = dict.fromkeys(("decision", "lock", "write", "pub", "commit", "mismatch", "i1", "i3"), 0)
        self._prev_hook = prev = sim.event_hook

        def hook(ev):
            if prev is not None:
                prev(ev)
            if ev and ev[0] == "commit":
                self._commits.append((sim.now_ms, ev))
        sim.event_hook = hook

        def refuse_reboot(*_a, **_k):
            raise RtcLabUnsupported("D1Sim reboot is not modelled by _lab_rtc: FbbSim.reboot() drops the WallClock / InverterRtc "
                                    "and keeps read_override_fn / outcome_fn bound to the OLD sim")
        sim.reboot = refuse_reboot

    # -- clock ---------------------------------------------------------------------------------------------------------------
    @property
    def t_utc(self) -> float:
        return self.sim.clock.utc_ms() / 1000

    def _open(self) -> None:
        if self.closed:
            raise RtcLabError("the RtcWorld is closed")

    def _advance_ms(self, target_utc_ms: int) -> None:
        self._open()
        cur = self.sim.clock.utc_ms()
        if target_utc_ms < cur:
            raise RtcLabError(f"time cannot go backwards: target {target_utc_ms / 1000} < now {cur / 1000}")
        self.sim.run_until(self.sim.now_ms + (target_utc_ms - cur))
        self._harvest()

    def advance_to(self, utc_s) -> None:
        self._advance_ms(_to_ms(utc_s, "advance_to"))

    def run_for(self, seconds) -> None:
        ms = _to_ms(seconds, "run_for")
        if ms < 0:
            raise RtcLabError(f"run_for: negative duration {seconds!r}")
        self._advance_ms(self.sim.clock.utc_ms() + ms)

    def run_to_change(self, delta_s=0.0) -> None:
        self._advance_ms(self.change_utc * 1000 + _to_ms(delta_s, "run_to_change"))

    # -- evidence harvest (the only writer of .log after the build) --------------------------------------------------------
    def _harvest(self) -> None:
        s, cur, rows = self.sim, self._cur, []

        def take(name, seq, rank, conv):
            for i in range(cur[name], len(seq)):
                row = conv(seq[i])
                if row is not None:
                    rows.append((int(row[0]), rank, i, row[1], row[2]))
            cur[name] = len(seq)

        take("decision", s.oracle_reads, 0, lambda r: (r["t"], "rtc.decision", {
            "reason": REASON_NAMES[r["reason"]], "err_s": int(r["err"]), "correct": r["action"] == rp.ACT_CORRECT}))
        take("lock", s.cip_edges, 1, lambda e: (e[0], "rtc.lock", {"held": bool(e[1])}))
        take("write", s.write_log, 2, lambda w: (w.t, "mb.write", {"addr": int(w.addr), "n": len(w.vals),
                                                                 "outcome": str(w.outcome), "issuer": w.issuer}))
        take("pub", s.pub_times, 3, lambda p: (p[0], _PUB_KINDS[p[1]], {"text": str(p[2])}) if p[1] in _PUB_KINDS else None)
        take("commit", self._commits, 4, self._commit_row)
        take("mismatch", s.oracle_mismatches, 5, lambda m: (m[0], "oracle.mismatch", {"field": str(m[1]), "want": repr(m[2]),
                                                                                       "got": repr(m[3])}))
        take("i1", s.i1_violations, 6, lambda v: (v[0], "inv.i1", {"detail": repr(v[1])}))
        take("i3", s.i3_violations, 7, lambda v: (v[0], "inv.i3", {"detail": str(v[1])}))
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
        for t, _rank, _i, kind, data in rows:
            self.log.append(t_utc=_utc(s, t), up_ms=t, boot=self.boot, src="fw", kind=kind, data=data)

    @staticmethod
    def _commit_row(item):
        t, (_c, key, rec, ok) = item
        data = {"tag": str(key), "ok": bool(ok)}
        if "end_epoch" in ds._RECORD_FIELDS.get(getattr(rec, "_kind", None), ()):
            data["end_epoch"] = int(rec.end_epoch)
        return (t, "nvs.commit", data)

    # -- actions -----------------------------------------------------------------------------------------------------------
    def fp_start(self, minutes=40, power_w=6000) -> None:
        self._open()
        s = self.sim
        for name, v in (("free_power_duration_minutes", minutes), ("free_power_max_power", power_w)):
            lo, hi = _number_range(s, name)
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise RtcLabError(f"{name}: {v!r} is not an int in [{lo:g}, {hi:g}] (HA number.set_value would refuse it)")
        s.ent("ecco_battery_voltage").set(SYNTHETIC_BATTERY_V)   # MODEL: telemetry stand-in (no telemetry poll runs)
        s.ent("configuration_online").set(True)                  # MODEL: configuration-poll stand-in
        s.ent("free_power_duration_minutes").set(float(minutes))
        s.ent("free_power_max_power").set(float(power_w))
        s.operator_switch(FP_ARM, True)                          # HA switch.turn_on
        s.press_button(FP_START_BUTTON)                          # HA button.press -> script.execute start_free_power_override
        self.fp_used = True
        self._harvest()

    def set_outcomes(self, write=None, verify=None, regular=None) -> None:
        self._open()
        maker = _maker(write, verify, regular)
        X.bind_outcomes(self.sim, maker if maker is not None else X.outcomes())

    def rtc_offset(self, offset_s) -> None:
        self._open()
        self.sim.rtc.set_offset(float(_num(offset_s, "rtc_offset")))

    def rtc_rate(self, rate) -> None:
        self._open()
        self.sim.rtc.set_rate(float(_num(rate, "rtc_rate")))

    def rtc_step(self, seconds) -> None:
        self._open()
        self.sim.rtc.step(float(_num(seconds, "rtc_step")))

    def poke(self, name, value) -> None:
        self._open()
        if not isinstance(name, str) or name not in self.sim.g:
            raise RtcLabError(f"poke: {name!r} is not a firmware global")
        if not isinstance(value, int):
            raise RtcLabError(f"poke: {name} value must be a bool or an int, got {value!r}")
        self.sim.poke(name, value)
        self._harvest()

    def press(self, button) -> None:
        self._open()
        if button not in X.RTC_BUTTONS:
            raise RtcLabError(f"press: {button!r} is not one of the RTC buttons {X.RTC_BUTTONS}")
        self.sim.press_button(button)
        self._harvest()

    def close(self) -> None:
        if not self.closed:
            self.sim.event_hook = self._prev_hook
            self.closed = True

    # -- observers (read-only) ---------------------------------------------------------------------------------------------
    def lock_windows(self) -> list:
        return lock_windows(self.sim)

    def _rel(self, utc_s, after_change) -> bool:
        return after_change is None or (utc_s > self.change_utc) == bool(after_change)

    def corrections(self, after_change=None) -> list:
        out = []
        for c in corrections(self.sim):
            if self._rel(c["queued_utc"], after_change):
                out.append(dict(c, rel_change_s=round(c["queued_utc"] - self.change_utc, 3)))
        return out

    def decisions(self, after_change=None) -> list:
        out = []
        for rd in self.sim.oracle_reads:
            u = _utc(self.sim, rd["t"])
            if self._rel(u, after_change):
                out.append({"utc": u, "rel_change_s": round(u - self.change_utc, 3), "reason": REASON_NAMES[rd["reason"]],
                            "err_s": int(rd["err"]), "correct": rd["action"] == rp.ACT_CORRECT})
        return out

    def fp_statuses(self) -> list:
        return [(_utc(self.sim, t), str(v)) for t, n, v in self.sim.pub_times if n == FP_STATUS]

    def fp_leases(self) -> list:
        """One dict per Free Power START (a 'STARTING' status): start_utc, active_utc, end_epoch (from the lease's first
        successful durable data commit with a non-zero end_epoch), restore_start_utc ('RESTORING'), restored_utc ('RESTORED OK'
        prefix), restored_text, final_status, statuses [[utc, text]]."""
        st = [(t, str(v)) for t, n, v in self.sim.pub_times if n == FP_STATUS]
        starts = [i for i, (_t, v) in enumerate(st) if v.startswith("STARTING")]
        out = []
        for k, i in enumerate(starts):
            j = starts[k + 1] if k + 1 < len(starts) else len(st)
            seg, t0 = st[i:j], st[i][0]
            t1 = st[j][0] if j < len(st) else None
            ends = [int(rec.end_epoch) for t, (_c, key, rec, ok) in self._commits
                    if key == ds.Durable.FREE_POWER_DATA_TAG and ok and t >= t0 and (t1 is None or t < t1)
                    and int(rec.end_epoch) != 0]

            def first(prefix):
                return next(((t, v) for t, v in seg if v.startswith(prefix)), (None, None))
            act, rs, rd = first("ACTIVE"), first("RESTORING"), first("RESTORED OK")
            out.append({"start_utc": _utc(self.sim, t0), "active_utc": None if act[0] is None else _utc(self.sim, act[0]),
                        "end_epoch": ends[0] if ends else None,
                        "restore_start_utc": None if rs[0] is None else _utc(self.sim, rs[0]),
                        "restored_utc": None if rd[0] is None else _utc(self.sim, rd[0]), "restored_text": rd[1],
                        "final_status": seg[-1][1], "statuses": [[_utc(self.sim, t), v] for t, v in seg]})
        return out

    def fp_status(self) -> str:
        return str(self.sim.ent(FP_STATUS).state)

    def invariants(self) -> dict:
        return invariant_violations(self.sim, fp=self.fp_used)

    def rtc_offset_s(self) -> float:
        return float(self.sim.rtc.offset_s())

    def results(self) -> list:
        return [str(x) for x in self.sim.results()]


# ---------------------------------------------------------------------------------------------------------------------------
# the rig
# ---------------------------------------------------------------------------------------------------------------------------
def _start_of(kind, start_local, start_utc) -> tuple:
    """(local fields for make_rig, start epoch s)."""
    if start_local is not None and start_utc is not None:
        raise RtcLabError("give start_local or start_utc, not both")
    if start_utc is not None:
        if isinstance(start_utc, bool) or not isinstance(start_utc, int):
            raise RtcLabError(f"start_utc must be an int epoch in seconds, got {start_utc!r}")
        local = tuple(C.local_fields(start_utc)[:6])
        if X.utc_of_local(*local) != start_utc:
            raise RtcLabError(f"start_utc {C.iso_utc(start_utc)} lies in the GMT copy of the repeated hour: make_rig reads "
                              f"{local} as BST (not modelled; start earlier and run through the change)")
        return local, start_utc
    local = DEFAULT_START_LOCAL[kind] if start_local is None else tuple(start_local)
    if len(local) != 6 or any(isinstance(v, bool) or not isinstance(v, int) for v in local):
        raise RtcLabError(f"start_local must be six ints (y, m, d, h, mi, s), got {start_local!r}")
    if C.local_kind(*local) == "gap":
        raise RtcLabError(f"start_local {local} does not exist in Europe/London (the spring-forward gap)")
    return local, X.utc_of_local(*local)


def dst_night_rig(kind: str = "fall", start_local=None, *, start_utc=None, fp_lease: bool = False, fp_minutes: int = 40,
                  fp_power_w: int = 6000, write_outcomes=None, verify_outcomes=None, regular_outcomes=None, rate: float = 0.0,
                  offset_s: float = -2.0, image_period_ms: int = 0, image_phase_ms: int = 0, tou=X.GOLD_TOU,
                  fp_phase_ms: int = 0, oracle: bool = True, seed: int = 0, text: str | None = None) -> RtcWorld:
    """A DST-night RtcWorld (see the module docstring)."""
    if kind not in KINDS:
        raise RtcLabError(f"kind must be one of {KINDS}, got {kind!r}")
    local, t0 = _start_of(kind, start_local, start_utc)
    if abs(t0 - CHANGE_UTC[kind]) > MAX_START_DISTANCE_S:
        raise RtcLabError(f"start {C.iso_utc(t0)} is more than 24 h from the {kind} change {C.iso_utc(CHANGE_UTC[kind])}")
    if isinstance(fp_phase_ms, bool) or not isinstance(fp_phase_ms, int) or not 0 <= fp_phase_ms < 15000:
        raise RtcLabError(f"fp_phase_ms must be an int in [0, 15000), got {fp_phase_ms!r}")
    tou = tuple(int(x) for x in tou)
    if len(tou) != 6:
        raise RtcLabError(f"tou must hold six HHMM words, got {tou!r}")
    maker = _maker(write_outcomes, verify_outcomes, regular_outcomes)  # typos fail before anything is built
    sim = X.make_rig(text, local=local, offset_s=float(_num(offset_s, "offset_s")), rate=float(_num(rate, "rate")),
                     image_period_ms=int(image_period_ms), image_phase_ms=int(image_phase_ms), tou=tou, oracle=oracle,
                     seed=int(seed))
    if sim.clock.utc_s() != t0:
        raise RtcLabError(f"make_rig started at {sim.clock.utc_s()}, want {t0}")
    sim.bank.update(SYNTHETIC_ORIGINAL)
    sim.bank.update(dict(zip(range(250, 256), tou)))
    sim.pub_timed.add(FP_STATUS)  # per-instance: time-stamp the Free Power status publications
    wd = fp_watchdog_index(sim.fw)
    sim.start_intervals([wd], phase={wd: fp_phase_ms})
    if maker is not None:
        X.bind_outcomes(sim, maker)
    world = RtcWorld(sim, kind=kind, seed=seed, fp_watchdog_idx=wd)
    world.log.append(t_utc=world.t_utc, up_ms=None, boot=None, src="lab", kind="rtc.rig",
                     data={"kind": kind, "start_utc": t0, "change_utc": world.change_utc, "seed": int(seed),
                           "fp_lease": bool(fp_lease)})
    world._harvest()
    if fp_lease:
        world.fp_start(fp_minutes, fp_power_w)
    return world


def rtc_world(*, utc_start, seed, kind="fall", fp_lease=False, fp_minutes=40, fp_power_w=6000, write_outcomes=None,
              verify_outcomes=None, regular_outcomes=None, rate=0.0, offset_s=-2.0, image_period_ms=0, image_phase_ms=0,
              tou=None, fp_phase_ms=0) -> RtcWorld:
    """The replay factory of tier 'rtc' (utc_start is an epoch in seconds)."""
    return dst_night_rig(kind, start_utc=utc_start, seed=seed, fp_lease=fp_lease, fp_minutes=fp_minutes, fp_power_w=fp_power_w,
                         write_outcomes=write_outcomes, verify_outcomes=verify_outcomes, regular_outcomes=regular_outcomes,
                         rate=rate, offset_s=offset_s, image_period_ms=image_period_ms, image_phase_ms=image_phase_ms,
                         tou=X.GOLD_TOU if tou is None else tou, fp_phase_ms=fp_phase_ms)


# ---------------------------------------------------------------------------------------------------------------------------
# replay tier 'rtc'
# ---------------------------------------------------------------------------------------------------------------------------
def _act_run_for(w, seconds):
    w.run_for(seconds)


def _act_fp_start(w, minutes=40, power_w=6000):
    w.fp_start(minutes, power_w)


def _act_set_outcomes(w, write=None, verify=None, regular=None):
    w.set_outcomes(write, verify, regular)


def _act_rtc_offset(w, offset_s):
    w.rtc_offset(offset_s)


def _act_rtc_rate(w, rate):
    w.rtc_rate(rate)


def _act_rtc_step(w, seconds):
    w.rtc_step(seconds)


def _act_poke(w, name, value):
    w.poke(name, value)


def _act_press(w, button):
    w.press(button)


def _obs_lock_windows(w):
    return [[a, b] for a, b in w.lock_windows()]


def _obs_corrections(w, after_change=None):
    return w.corrections(after_change)


def _obs_n_corrections(w, after_change=None, reason=None, verified=None):
    return sum(1 for c in w.corrections(after_change)
               if (reason is None or c["reason"] == reason) and (verified is None or c["verified"] == bool(verified)))


def _obs_decisions(w, after_change=None):
    return w.decisions(after_change)


def _obs_fp_leases(w):
    return w.fp_leases()


def _obs_fp_status(w):
    return w.fp_status()


def _obs_invariants(w):
    return {k: len(v) for k, v in w.invariants().items()}


def _obs_rtc_offset_s(w):
    return w.rtc_offset_s()


def _obs_results(w):
    return w.results()


def _obs_global_value(w, name):
    if name not in w.sim.g:
        raise RtcLabError(f"global_value: {name!r} is not a firmware global")
    v = w.sim.g[name]
    if isinstance(v, (bool, int, float, str)):
        return v
    raise RtcLabError(f"global_value: {name} holds a {type(v).__name__} (only scalar globals are observable)")


ACTIONS = {"run_for": _act_run_for, "fp_start": _act_fp_start, "set_outcomes": _act_set_outcomes, "rtc_offset": _act_rtc_offset,
           "rtc_rate": _act_rtc_rate, "rtc_step": _act_rtc_step, "poke": _act_poke, "press": _act_press}
OBSERVERS = {"lock_windows": _obs_lock_windows, "corrections": _obs_corrections, "n_corrections": _obs_n_corrections,
             "decisions": _obs_decisions, "fp_leases": _obs_fp_leases, "fp_status": _obs_fp_status,
             "invariants": _obs_invariants, "rtc_offset_s": _obs_rtc_offset_s, "results": _obs_results,
             "global_value": _obs_global_value}
T.register_tier("rtc", rtc_world)
T.register_actions("rtc", ACTIONS)
T.register_observers("rtc", OBSERVERS)
