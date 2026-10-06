"""FB-B2 scenario driver: one object that runs the REAL firmware YAML (SAVE / INVALIDATE and everything FB-B1 left) the way
an operator, Home Assistant and the inverter would, and records what happened. Support module for the FB-B2 scenario suites
(test_fallback_save_gates.py, _durable.py, test_fallback_invalidate.py, ...); self-tested by test_fallback_save_harness.py.

It adds no behaviour of its own: every action goes through registry/tests/_fbb_harness.FbbSim (the transpiled firmware
lambdas, the discrete-event engine, the direct-NVS fault model, the Modbus hub). It exists so that a scenario reads as the
story it tells and so that the dozens of ways to build the same sim are built ONE way.

QUICK START
    import _fbb2_drive as D
    d = D.Driver()                          # live firmware, boot VALID g7 profile + witness, trusted NTP + supervision,
                                            # bank == the stored profile, the 10 s housekeeping tick running
    d.review(expect="CANDIDATE_READY")      # press "Review Current Configuration", run to idle
    st = d.save()                           # arm ON (as Home Assistant would), fallback_profile_execute(SAVE, <B4>, "SAVE <B4>")
    assert st.violations_fb(("FBW", "FBP")) == [] and d.b9.startswith("SAVED - ")
    d.reboot()                              # the REAL on_boot over the NVS the previous boot left
    assert d.b1 == "VALID"

CONSTRUCTION  Driver(fw=None, *, text=None, seed="valid", words=None, markers=(), fail_tags=(), fbs=None, pre=None,
                     env="trusted", mode=None, boot=True, salt=True, housekeeping=True, epoch=None, tick_ms=10,
                     api="fallback_profile_execute", arm="fallback_profile_arm", review_button=..., arm_on_ms_global=
                     "fallback_profile_arm_on_ms", fbsave=None, fbcap=None)
    fw / text     a parsed firmware dict (default: the LIVE firmware, parsed once per process) / YAML text (a mutant); cached by sha
    seed          the direct-NVS image before the boot: a name of SEEDS ("none" "valid" "invalidated" "corrupt" "wsize"
                  "corrupt_domain" "unreadable" "lost" "stale" "lag" "witness_corrupt"), a dict {"fbp": bytes|dict|None,
                  "fbw": bytes|None, "fbs": bytes|None} or a callable(sim)
    words         the 31 register words the inverter holds (default GWORDS = what the golden stored profile holds)
    markers       [(domain, state, seed_marker kwargs)] lease markers in the legacy store + direct NVS ("fp" "dump" "r244")
    env           "trusted" (NTP synced + valid, supervision SUPERVISED and Stable), "bare" (what a fresh boot has: untrusted)
    mode          None (immediate Modbus) or ("deferred", latency_ms)
    housekeeping  start the FB 10 s interval (candidate TTL, arm TTL, IE7/IE8/IE11) - the device always runs it
    epoch         NTP wall clock (default 1_790_000_000 = the golden profile's captured_epoch); time does not flow unless
                  set_time(flow=True)
    api / arm     the api action / arm switch ids (the synthetic fixture of _fbb2_synth.py uses its own names);   arm_on_ms_global the global
                  the arm's turn_on_action stamps
    fbsave/fbcap  a mirror module (or its name) standing in for registry/fallback_save.py / fallback_capture.py (mutants, doubles)

OPERATOR / HOME ASSISTANT ACTIONS (each returns a Step; idle=True (default) drives the engine to idle afterwards, catch_cut=True keeps a PowerCut)
    review(expect=None)             press the Review button; expect="CANDIDATE_READY" etc. asserts B3's st= (setup guard)
    press_review()                  the same without the guard
    arm_on() / arm_off()            Home Assistant switch.turn_on / turn_off on the arm (runs turn_on_action: the TTL stamp)
    execute(action, target_id, confirmation)   the api action fallback_profile_execute with those three strings
    save(target_id=None, confirmation=None, arm=True, replace_corrupt=False)    id defaults to B4, phrase to "SAVE <id>"
    invalidate(target_id=None, confirmation=None, arm=True)    id defaults to the stored profile's full binding (B2 id=)
    heartbeat() / establish_supervision()   the REAL ha_supervision_heartbeat action (one beat / three beats 30 s apart)
    step(label, fn, ...)            run any callable as a measured Step (see below)

STATE OF THE WORLD (all take effect immediately; none is an operator action)
    set_words(words) / poke(reg, v) the inverter's registers; before_read(k, fn) changes them just before the k-th read;
                                    bank_at(delay_ms, {reg: v}) changes them at a virtual instant; read_override(fn) rewrites what a read returns
    set_time(epoch=None, ntp=True, flow=False) / untrusted_time()   NTP wall clock + the ntp_synced global
    supervise(ok=True | state=, stable=)    the supervision_* globals the api action snapshots
    write_arm(name, on)             free_power_write_enable / dump_write_enable / manual_config_write_enable
    lease(name) / mutex(held)       a Free Power / Dump / R244 lease state (LEASE_RAM) / manual_write_in_progress
    set_g(name, v) / run(code)      any global / any C++ lambda text
    put(key, data) / erase(key) / fault_write(key, ...) / fault_read(key, err)    the direct NVS after the boot
    advance(ms) / idle() / mode(kind, ms) / hold_bus(ms)     time and the Modbus hub

OBSERVATION
    b1 .. b9, text("B3"), texts()   the nine FB text entities (str); published("B9") every value since boot
    g                               the globals dict (arrays: use arr(name) - slicing an FbArray raises);   cls   effective class name from the firmware's own mirror
    candidate()                     dict of the fallback_profile_cand_* globals;   arm_on_ms / arm_state / write_latched
    stored("FBP"|"FBW"|"FBS")       decoded record from the direct NVS (None if absent/damaged), state_of(), nvs_image()
    model_class()                   the class the FB-B0 model derives from the NVS image (the independent oracle)
    mark() / since(m)               E.Mark / E.Since;   nvs_set_history()  every direct-NVS set over ALL boots of this driver
    snapshot() / diff(snap)         every global + publication count / which globals moved and what was published since
    modbus_writes() / modbus_reads()   the sim's Modbus log (all boots of the CURRENT sim); reads_seen counts every firmware read

MODULE HELPERS  load_fw(text=None) (cached parse) / mutate(text, old, new, count=1) (an exact-count text mutant) / gold_profile / GOLD /
    GWORDS / bank_for / prov_bytes / SEEDS / seed_fbs / LEASE_RAM / WRITE_ARMS / K_P K_W K_S FBP_DEC FBW_DEC FBS_DEC / B_IDS / CLASS /
    B9_PREFIXES / text_invariants(driver) / idle_invariants(driver) / sweep_nvs_cuts / sweep_timeline_cuts

STEP  (what execute()/review()/... return)   .since (E.Since)  .texts (B1..B9 after)  .published ({B#: [values this step]})
      .cut (the PowerCut or None)  .elapsed_ms  .task  .reads  .writes  .fb_sets  .fb_set_order
      .violations_fb(expect, bytes_=, reads=)  .violations()   - the safety audits of E.Since

POWER CUTS / REBOOT
    reboot(env="same", wipe=, absent_keys=, handle=)   a power cycle: new FbbSim over the SAME firmware, the NVS resolved per its write
                                    faults (or wiped / losing keys / handle 0 at boot), the REAL on_boot run, the environment re-applied; returns self
    cut_when(pred) / cut_before_nvs(op, key, nth) / cut_after_nvs(...) / cut_at_nvs_point(n) / cut_after_event(k, kinds)
    when(pred, fn)                  run fn(sim) at the first timeline event satisfying pred (an interleaving at an exact instant)
    sweep_nvs_cuts(make, operation) / sweep_timeline_cuts(...)   a power cut at EVERY NVS event / timeline event of
                                    `operation(driver)`, each followed by reboot(); returns [CutPoint]
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))  # registry/
import _dump_sim as ds  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbb_harness as H  # noqa: E402
import fallback_capture as fc  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
PowerCut = H.PowerCut
FbbNotModelled = H.FbbNotModelled


class DriverError(AssertionError):
    """A scenario precondition the driver checks (expect=...) did not hold - a bug in the scenario, not in the firmware."""


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------
K_P, K_W, K_S = fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_KEY, fd.FAILBACK_STATE_KEY
KEY = {"FBP": K_P, "FBW": K_W, "FBS": K_S}
FBP_DEC, FBW_DEC, FBS_DEC = (fd.decimal_key(K_P), fd.decimal_key(K_W), fd.decimal_key(K_S))
B_IDS = {  # B1..B9 -> entity id
    "B1": "fallback_profile_state_text", "B2": "fallback_profile_summary_text", "B3": "fallback_profile_review_text",
    "B4": "fallback_profile_review_id_text", "B5": "fallback_profile_review_slots_text",
    "B6": "fallback_profile_review_context_text", "B7": "fallback_profile_slots_text", "B8": "fallback_profile_context_text",
    "B9": "fallback_profile_last_result_text",
}
CLASS = {0: "UNREADABLE", 1: "NOT_CAPTURED", 2: "CORRUPT", 3: "CORRUPT_DOMAIN", 4: "INVALIDATED", 5: "VALID", 6: "PROFILE_LOST",
         7: "SAVE_UNCONFIRMED", 8: "PROFILE_STALE"}
WRITE_ARMS = ("free_power_write_enable", "dump_write_enable", "manual_config_write_enable")
MARKER_TAGS = {"fp": "ecco_free_power_snapshot_valid_v1", "dump": "ecco_dump_to_grid_snapshot_valid_v1",
               "r244": "ecco_reg244_snapshot_valid_v1"}
REVIEW_BUTTON = "fallback_profile_review_button"
HOUSEKEEPING_MARK = "fallback_profile_cand_valid"
READS = [(230, 3), (241, 53), (230, 3), (241, 53)]
EPOCH0 = 1_790_000_000
ALL_CLEAR_OBL = "FP:CA,DP:CA,R4:CA,MT:CN,FS:CA,BUS:OK"
IDLE_B3 = "st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-"


# B9 (last action-result) values must start with one of these (M L1121 + the FB-B1 lines): the locked prefix set, plus the lowercase
# in-progress lines. Everything every FB text entity publishes is also checked for length and the card-hostile words.
B9_PREFIXES = ("No Fallback Profile action since boot", "review in progress (read-only)", "save in progress", "CANDIDATE READY",
               "CANDIDATE NOT SAVEABLE", "REVIEW REFUSED", "REVIEW NOT COMPLETED", "REVIEW EXPIRED", "REVIEW CLEARED", "SAVE REFUSED",
               "SAVED", "SAVE NOT COMMITTED", "SAVE OUTCOME UNKNOWN", "INVALIDATE REFUSED", "INVALIDATED", "INVALIDATE NOT COMMITTED",
               "INVALIDATE OUTCOME UNKNOWN", "REFUSED", "RESTORE REFUSED", "ACKNOWLEDGE REFUSED", "INTERNAL")
# The D8 hazard words (case-insensitive) no FB text may contain or begin with, besides the Energy Actions card's own regexes
# (the same list the FB-B1 suite pins).
D8_HAZARD = [re.compile(p_, re.I) for p_ in (
    r"RECOVERY REQUIRED", r"OPERATOR DECISION REQUIRED", r"RESTORE BLOCKED", r"RECOVERY BLOCKED", r"\bFAILED\b",
    r"VERIFY (ERROR|TIMEOUT|REFUSED)", r"DEFERRED", r"ACCEPT REFUSED", r"Recovery Arm first", r"inverter writes? (are |is )?locked",
    r"deliberate recovery required", r"START FAILED", r"ACTIVATION (VERIFY|WRITE) FAILED", r"press End Free Power",
    r"retry restore", r"snapshot retained", r"^RESTORING", r"^STARTING", r"^ACTIVATION VERIFY", r"failed", r"deferred")]


# ---------------------------------------------------------------------------
# the firmware under test (parsed once per distinct text)
# ---------------------------------------------------------------------------
_FW_CACHE: dict = {}


def load_fw(text: str | None = None) -> dict:
    """The parsed firmware: the LIVE yaml (default) or `text` (a mutant). Cached by sha256; FbbSim never mutates it, so
    every Driver shares one dict."""
    if text is None:
        text = FW_PATH.read_text(encoding="utf-8")
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    fw = _FW_CACHE.get(key)
    if fw is None:
        fw = _FW_CACHE[key] = ds.load_firmware_text(text)
    return fw


def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    """A mutant of firmware text: `old` must occur EXACTLY `count` times (so a mutant can never be a silent no-op)."""
    n = text.count(old)
    if n != count:
        raise DriverError(f"mutation anchor occurs {n} times, want {count}: {old[:80]!r}")
    return text.replace(old, new)


# ---------------------------------------------------------------------------
# golden fixtures (the FB-B1 suite's, kept in step on purpose: a candidate reviewed from GWORDS has the golden profile's id)
# ---------------------------------------------------------------------------
GOLD_FIELDS = dict(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=EPOCH0, flags=0, reg244=2,
                   reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30],
                   reg274_279=[1, 0, 1, 0, 0, 1], reg232=0x0011, reg243=1, reg248=1,
                   reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1,
                   reserved0=0, reserved1=0, binding=0)


def gold_profile(**over) -> dict:
    return fp.seal_profile(fp.blank_profile(**{**GOLD_FIELDS, **over}))


GOLD = gold_profile()
GWORDS = fc.words_of(GOLD)


def bank_for(words) -> dict:
    """The inverter register bank for 31 capture words (every other register of the polled range is 0)."""
    b = {a: 0 for a in range(230, 294)}
    for k, r in enumerate(fc.REGS):
        b[r] = words[k]
    return b


def prov_bytes(hw, hwb, pg, op=fd.PROV_OP_SAVE, pb=0x6666) -> bytes:
    """A sealed FBW record (hw_generation, hw_binding, prior_generation, prior_binding=0x6666 unless pb)."""
    return fd.pack_provision(fd.make_provision(hw, hwb, pg, pb if pg else 0, K_P, 1, op))


def _seed_valid(sim):
    sim.nvs_direct.put(K_P, fp.pack_profile(GOLD))
    sim.nvs_direct.put(K_W, prov_bytes(7, GOLD["binding"], 6))


def _seed_invalidated(sim):
    inv = fp.invalidate_profile(GOLD)
    sim.nvs_direct.put(K_P, fp.pack_profile(inv))
    sim.nvs_direct.put(K_W, prov_bytes(8, inv["binding"], 7, fd.PROV_OP_INVALIDATE))


def _seed_unreadable(sim):
    sim.nvs_direct.put(K_P, fp.pack_profile(GOLD))
    sim.nvs_direct.read_faults[K_P] = [fd.IDF_FAIL, fd.IDF_FAIL]  # the boot read AND the next fresh read fail


SEEDS = {
    "none": lambda sim: None,
    "valid": _seed_valid,
    "invalidated": _seed_invalidated,
    "corrupt": lambda sim: sim.nvs_direct.put(K_P, bytes(range(96))),
    "wsize": lambda sim: sim.nvs_direct.put(K_P, bytes(40)),
    "corrupt_domain": lambda sim: sim.nvs_direct.put(K_P, fp.pack_profile(gold_profile(reg244=7))),
    "unreadable": _seed_unreadable,
    "lost": lambda sim: sim.nvs_direct.put(K_W, prov_bytes(7, GOLD["binding"], 6)),
    "stale": lambda sim: (sim.nvs_direct.put(K_P, fp.pack_profile(gold_profile(generation=5))),
                          sim.nvs_direct.put(K_W, prov_bytes(7, GOLD["binding"], 6))),
    "lag": lambda sim: (sim.nvs_direct.put(K_P, fp.pack_profile(GOLD)), sim.nvs_direct.put(K_W, prov_bytes(6, 0x1111, 5))),
    "witness_corrupt": lambda sim: (sim.nvs_direct.put(K_P, fp.pack_profile(GOLD)), sim.nvs_direct.put(K_W, bytes(range(48)))),
}


def seed_fbs(kind):
    """A callable(sim) seeding the failback-state record (FBS) the boot reads once: clear / episode / corrupt / unreadable."""
    def seed(sim):
        if kind == "clear":
            sim.nvs_direct.put(K_S, fp.pack_failback(fp.failback_clear_record(3)))
        elif kind == "episode":
            rec = fp.seal_failback(fp.blank_failback(magic=fp.FAILBACK_MAGIC, schema=fp.FAILBACK_SCHEMA,
                                                     size=fp.FAILBACK_SIZE, state=1, reason=1, event_seq=2))
            sim.nvs_direct.put(K_S, fp.pack_failback(rec))
        elif kind == "corrupt":
            sim.nvs_direct.put(K_S, bytes(range(fp.FAILBACK_SIZE)))
        elif kind == "unreadable":
            sim.nvs_direct.put(K_S, fp.pack_failback(fp.failback_clear_record(3)))
            sim.nvs_direct.read_faults[K_S] = [fd.IDF_FAIL]
        else:
            raise DriverError(f"unknown FBS seed {kind!r}")
    return seed


# The RAM legs a lease / obligation can occupy, as the lambda that puts the globals in that state, the obligation-vector code
# the FB gate reports and a fragment of the refusal text (REVIEW REFUSED / SAVE REFUSED share the body).
LEASE_RAM = {
    "fp_active": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1; id(free_power_active_persisted) = true;",
                  "FP:AC", "Free Power is active"),
    "fp_restore_required": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1; "
                            "id(free_power_restore_requested) = true;", "FP:RR", "Free Power must restore original settings first"),
    "fp_pending_clear": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 2;", "FP:PC",
                         "Free Power restore verified; durable clear still pending"),
    "fp_operator_needed": ("id(free_power_snapshot_valid) = true; id(free_power_marker_state) = 1; "
                           "id(free_power_operator_needed) = true;", "FP:ON", "Free Power needs an operator recovery action first"),
    "fp_metadata_corrupt": ("id(free_power_recovery_metadata_corrupt) = true;", "FP:MC", "Free Power recovery metadata is CORRUPT"),
    "dump_active": ("id(dump_snapshot_valid) = true; id(dump_marker_state) = 1; id(dump_active_persisted) = true;", "DP:AC",
                    "Dump to Grid is active"),
    "dump_restore_required": ("id(dump_snapshot_valid) = true; id(dump_marker_state) = 1;", "DP:RR",
                              "Dump to Grid must restore original settings first"),
    "dump_operator_needed": ("id(dump_snapshot_valid) = true; id(dump_marker_state) = 1; id(dump_operator_needed) = true;",
                             "DP:ON", "Dump to Grid needs an operator recovery action first"),
    "dump_metadata_corrupt": ("id(dump_recovery_metadata_corrupt) = true; id(dump_containment_state) = 3;", "DP:MC",
                              "containment K=3"),
    "r244_operator_needed": ("id(reg244_snapshot_valid) = true; id(reg244_marker_state) = 1;", "R4:ON",
                              "Register 244 test needs an operator recovery action first"),
    "r244_pending_clear": ("id(reg244_snapshot_valid) = true; id(reg244_marker_state) = 2;", "R4:PC",
                           "Register 244 test restore verified; durable clear still pending"),
    "r244_metadata_corrupt": ("id(reg244_recovery_metadata_corrupt) = true;", "R4:MC",
                              "Register 244 test recovery metadata is CORRUPT"),
}
MUTEX_ON = "id(manual_write_in_progress) = true;"


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------
@dataclass
class Step:
    """One measured operation: what it did to the world (see the module docstring)."""

    label: str
    since: object                      # E.Since
    texts: dict                        # B1..B9 after the step
    published: dict                    # {"B9": [values published during the step], ...} (only entities that published)
    task: object = None
    cut: BaseException | None = None
    t0: int = 0
    t1: int = 0

    @property
    def elapsed_ms(self) -> int:
        return self.t1 - self.t0

    @property
    def reads(self):
        return self.since.reads

    @property
    def writes(self):
        return self.since.writes

    @property
    def fb_sets(self):
        return self.since.fb_sets

    @property
    def fb_set_order(self):
        return self.since.fb_set_order

    @property
    def nvs_sets(self):
        return self.since.nvs_set_log

    @property
    def b9(self) -> str:
        return self.texts["B9"]

    def violations_fb(self, expect=(), **kw):
        return self.since.violations_fb(expect, **kw)

    def violations(self, **kw):
        return self.since.violations(**kw)


@dataclass
class CutPoint:
    """One row of a power-cut sweep."""

    index: int
    label: str
    cut: bool                          # a PowerCut was raised (False: the operation finished before this point)
    drv: "Driver"                      # the driver AFTER the reboot (or frozen at the cut when reboot=False)
    sets_before_cut: list = field(default_factory=list)   # [(name, bytes, result)] FB sets issued before the cut
    point: int | None = None           # DirectNvs.cut_at (kind "nvs") / timeline event index (kind "timeline")
    error: BaseException | None = None


# ---------------------------------------------------------------------------
# the Modbus read hooks
# ---------------------------------------------------------------------------
class _ReadHooks:
    """sim.read_override_fn: counts every firmware read, runs the registered hooks BEFORE the k-th read takes its snapshot (so a
    hook that changes the bank changes what THAT read returns) and then an optional inner override."""

    def __init__(self):
        self.sim = None
        self.n = 0
        self.before: dict = {}
        self.inner = None
        self.log: list = []          # (n, addr, count)

    def __call__(self, addr, count, values):
        self.n += 1
        self.log.append((self.n, addr, count))
        fns = self.before.get(self.n, ())
        for fn in fns:
            fn(self.sim, addr, count)
        if fns:
            values = [self.sim.bank.get(addr + i, 0) for i in range(count)]
        if self.inner is not None:
            values = self.inner(addr, count, values)
        return values


# ---------------------------------------------------------------------------
# the driver
# ---------------------------------------------------------------------------
class Driver:
    def __init__(self, fw: dict | None = None, *, text: str | None = None, seed="valid", words=None, markers=(), fail_tags=(),
                 fbs=None, pre=None, env="trusted", mode=None, boot=True, salt=True, housekeeping=True, epoch=None,
                 tick_ms: int = 10, api="fallback_profile_execute", arm="fallback_profile_arm", review_button=REVIEW_BUTTON,
                 arm_on_ms_global="fallback_profile_arm_on_ms", fbsave=None, fbcap=None):
        if fw is not None and text is not None:
            raise DriverError("pass fw OR text")
        self.fw = fw if fw is not None else load_fw(text)
        self.api_name, self.arm_id, self.review_button = api, arm, review_button
        self.arm_on_ms_global = arm_on_ms_global
        self.tick_ms, self.fbsave, self.fbcap = tick_ms, fbsave, fbcap
        self.env_name, self.housekeeping_on, self.salt = env, housekeeping, salt
        self.mode_args = mode
        self.boots = 1
        self.steps: list[Step] = []
        self._sets_prior_boots: list = []
        self._hooks = _ReadHooks()
        self.epoch = EPOCH0 if epoch is None else epoch
        self._time_flows = False
        sim = H.FbbSim(self.fw, tick_ms=tick_ms, fbcap=fbcap, fbsave=fbsave)
        self.sim = sim
        if fail_tags:
            sim.nvs_fail_load_tags = set(fail_tags)
        for dom, state, kw in markers:
            sim.seed_marker(MARKER_TAGS[dom], state, **kw)
        self._seed(seed)
        if fbs is not None:
            (seed_fbs(fbs) if isinstance(fbs, str) else fbs)(sim)
        if pre:
            pre(sim)
        sim.epoch = self.epoch
        if boot:
            sim.run_boot()
        if salt:
            sim.random_values = [0]
        self.words = list(GWORDS if words is None else words)
        sim.bank.update(bank_for(self.words))
        self._bind_hooks()
        if mode:
            sim.set_modbus_mode(*mode)
        self.apply_env(env)
        if housekeeping:
            self.start_housekeeping()

    # ------------------------------------------------------------------ construction helpers
    def _seed(self, seed):
        sim = self.sim
        if callable(seed):
            seed(sim)
        elif isinstance(seed, dict):
            for name, key in (("fbp", K_P), ("fbw", K_W), ("fbs", K_S)):
                if seed.get(name) is not None:
                    v = seed[name]
                    sim.nvs_direct.put(key, fp.pack_profile(v) if isinstance(v, dict) and name == "fbp" else bytes(v))
        else:
            if seed not in SEEDS:
                raise DriverError(f"unknown seed {seed!r} (have {sorted(SEEDS)})")
            SEEDS[seed](sim)

    def _bind_hooks(self):
        self._hooks.sim = self.sim
        self.sim.read_override_fn = self._hooks

    def has_api(self, name=None) -> bool:
        try:
            self.sim.api_action(name or self.api_name)
            return True
        except FbbNotModelled:
            return False

    def has_arm(self) -> bool:
        return self.arm_id in self.sim._switches

    # ------------------------------------------------------------------ environment
    def apply_env(self, env):
        """"trusted" | "bare" | None | a callable(driver)."""
        if env == "trusted":
            self.set_time(ntp=True)
            self.supervise(True)
        elif env == "bare":
            self.set_time(ntp=False)
            self.supervise(False)
        elif env is None:
            pass
        elif callable(env):
            env(self)
        else:
            raise DriverError(f"unknown env {env!r}")
        return self

    def set_time(self, epoch=None, *, ntp=True, flow=None):
        """The NTP wall clock the firmware sees (`id(ntp_time).now()`) and the ntp_synced global. flow=True makes the wall clock
        advance with the virtual clock from now on (captured_epoch then differs by the elapsed seconds)."""
        sim = self.sim
        if epoch is not None:
            self.epoch = epoch
        sim.ntp_valid = bool(ntp)
        sim.epoch = self.epoch
        sim.g["ntp_synced"] = bool(ntp)
        if flow is not None:
            self._time_flows = bool(flow)
            if flow:
                sim.entities["ntp_time"] = _FlowingClock(sim, sim.now_ms, self.epoch)
            else:
                sim.entities["ntp_time"] = ds.Clock(sim, "ntp_time")
        return self

    def untrusted_time(self):
        """No NTP sync this boot: ntp_synced false and the clock invalid."""
        return self.set_time(ntp=False)

    def supervise(self, ok=True, *, state=None, stable=None):
        """The supervision_* globals the api action snapshots: ok=True -> SUPERVISED (1) and Stable; ok=False -> STARTUP (0), not
        stable; or give state= / stable= explicitly."""
        g = self.sim.g
        g["supervision_state"] = (1 if ok else 0) if state is None else int(state)
        g["supervision_stable"] = bool(ok) if stable is None else bool(stable)
        return self

    def heartbeat(self, challenge=None):
        """One REAL ha_supervision_heartbeat call with the current challenge (or the one given)."""
        ch = str(self.sim.g["supervision_challenge"]) if challenge is None else challenge
        return self.sim.call_api("ha_supervision_heartbeat", challenge=ch)

    def establish_supervision(self, beats=3, spacing_ms=30_000):
        """The REAL heartbeat action `beats` times, `spacing_ms` apart: after three beats over >= 55 s the firmware's own rule
        sets supervision_stable (the unit tests set the flag directly with supervise())."""
        for i in range(beats):
            self.heartbeat()
            if i != beats - 1:
                self.advance(spacing_ms)
        return self

    def write_arm(self, name, on=True):
        if name not in WRITE_ARMS:
            raise DriverError(f"{name!r} is not one of the three write arms {WRITE_ARMS}")
        self.sim.ent(name).set(bool(on))
        return self

    def lease(self, name):
        """Put a Free Power / Dump / R244 obligation leg in the RAM state LEASE_RAM[name] (REVIEW and SAVE refuse on it)."""
        if name not in LEASE_RAM:
            raise DriverError(f"unknown lease preset {name!r} (have {sorted(LEASE_RAM)})")
        self.sim.run_lambda(LEASE_RAM[name][0])
        return self

    def mutex(self, held=True):
        self.sim.run_lambda(f"id(manual_write_in_progress) = {'true' if held else 'false'};")
        return self

    def set_g(self, name, value):
        self.sim.set_global(name, value)
        return self

    def run(self, code, **local):
        return self.sim.run_lambda(code, local, params=tuple(local))

    # ------------------------------------------------------------------ the inverter
    def set_words(self, words):
        self.words = list(words)
        self.sim.bank.update(bank_for(self.words))
        return self

    def bank_words(self):
        return [self.sim.bank.get(r, 0) for r in fc.REGS]

    def poke(self, register, value):
        self.sim.bank[int(register)] = int(value)
        return self

    def before_read(self, k, fn, *, relative=True):
        """fn(sim, addr, count) runs just BEFORE the k-th firmware read (1-based, counted from now when relative=True) takes
        its snapshot of the bank: to change a register between read k-1 and read k, mutate the bank in the hook."""
        n = (self._hooks.n if relative else 0) + int(k)
        self._hooks.before.setdefault(n, []).append(fn)
        return self

    def change_word_before_read(self, k, word_index, value):
        """Convenience: set register `fc.REGS[word_index]` to `value` just before the k-th read."""
        reg = fc.REGS[word_index]
        return self.before_read(k, lambda sim, a, c: sim.bank.__setitem__(reg, int(value)))

    def read_override(self, fn):
        """fn(addr, count, values) -> values: what a read returns, applied after the bank snapshot and the before_read hooks (a short, garbled or
        shifted reply); None removes it."""
        self._hooks.inner = fn
        return self

    def bank_at(self, delay_ms, updates):
        """Change inverter registers `delay_ms` of virtual time from now (another master / the LCD / the cloud), on the engine timeline:
        with a deferred hub a read frame takes its snapshot when it goes on the wire, so this decides which read sees the change."""
        self.sim.at_bank(self.sim.now_ms + int(delay_ms), updates)
        return self

    @property
    def reads_seen(self) -> int:
        return self._hooks.n

    def mode(self, kind, latency_ms=None):
        self.sim.set_modbus_mode(kind, latency_ms)
        return self

    def hold_bus(self, ms, at=None):
        self.sim.hold_bus(ms, at=at)
        self.sim.run_for(1)
        return self

    # ------------------------------------------------------------------ the direct NVS after the boot
    def put(self, key, data, **kw):
        """Store raw bytes (or a profile dict for FBP) under FBP / FBW / FBS (crc_ok= / chunk_present= for damage)."""
        k = KEY[key]
        if isinstance(data, dict):
            data = fp.pack_profile(data) if key == "FBP" else (fp.pack_failback(data) if key == "FBS" else fd.pack_provision(data))
        self.sim.nvs_direct.put(k, bytes(data), **kw)
        return self

    def erase(self, key):
        self.sim.nvs_direct.blobs.pop(KEY[key], None)
        return self

    def fault_write(self, key, **kw):
        """Queue a WriteFault for the next set_blob of FBP / FBW (result=, visible=, boot=, healthy_after=, other=, wrong_len=)."""
        self.sim.nvs_direct.faults.setdefault(KEY[key], []).append(H.WriteFault(**kw))
        return self

    def fault_read(self, key, err, *more):
        """Queue read errors for the next get_blob calls of that key (probe and data read each consume one)."""
        self.sim.nvs_direct.read_faults.setdefault(KEY[key], []).extend([err, *more])
        return self

    def unhealthy(self):
        self.sim.nvs_direct.healthy = False
        return self

    # ------------------------------------------------------------------ observation
    @property
    def g(self) -> dict:
        return self.sim.g

    def arr(self, name) -> list:
        """A std::array global as a plain list (the globals hold bounds-checked FbArrays: slicing them raises FbbNotModelled)."""
        return list(self.sim.g[name])

    def text(self, which) -> str:
        eid = B_IDS[which] if which in B_IDS else which
        return str(self.sim.ent(eid).state)

    def texts(self) -> dict:
        return {k: self.text(k) for k in B_IDS}

    def published(self, which) -> list:
        eid = B_IDS[which] if which in B_IDS else which
        return [str(x) for x in self.sim.ent(eid).published]

    b1 = property(lambda self: self.text("B1"))
    b2 = property(lambda self: self.text("B2"))
    b3 = property(lambda self: self.text("B3"))
    b4 = property(lambda self: self.text("B4"))
    b5 = property(lambda self: self.text("B5"))
    b6 = property(lambda self: self.text("B6"))
    b7 = property(lambda self: self.text("B7"))
    b8 = property(lambda self: self.text("B8"))
    b9 = property(lambda self: self.text("B9"))

    @property
    def cls(self) -> str:
        return CLASS[self.sim.g["fallback_profile_class"]]

    def b3_field(self, name) -> str:
        """One key of the B3 text (`st`, `prior`, `exp`, `warn`, `obl`, `latch`, `sv`)."""
        for part in self.b3.split(";"):
            if part.startswith(name + "="):
                return part[len(name) + 1:]
        raise DriverError(f"no {name}= in B3 {self.b3!r}")

    def b2_id(self) -> str:
        """The full 16-hex binding of the stored profile as B2 shows it (`id=`); '-' when there is none."""
        for part in self.b2.split(";"):
            if part.startswith("id="):
                return part[3:]
        raise DriverError(f"no id= in B2 {self.b2!r}")

    @property
    def write_latched(self) -> bool:
        """The FB-B0 per-boot write latch (set by an UNKNOWN_REBOOT key outcome; only a reboot clears it)."""
        return bool(self.sim.write_latch.write_latched)

    @property
    def arm_state(self) -> bool:
        return bool(self.sim.ent(self.arm_id).state)

    @property
    def arm_on_ms(self):
        return self.sim.g.get(self.arm_on_ms_global)

    def candidate(self) -> dict:
        g = self.sim.g
        return {k[len("fallback_profile_cand_"):]: (list(v) if isinstance(v, list) else v)
                for k, v in g.items() if k.startswith("fallback_profile_cand_")}

    def _peek(self, key):
        """(load, bytes) of a key as the FB-B0 reader would classify it - without performing a read (no CRC side effect)."""
        b = self.sim.nvs_direct.blobs.get(KEY[key])
        size = {"FBP": fp.PROFILE_SIZE, "FBW": fd.PROVISION_SIZE, "FBS": fp.FAILBACK_SIZE}[key]
        if b is None:
            return fp.LOAD_ABSENT, bytes(size)
        if not b.crc_ok or not b.chunk_present:
            return fp.LOAD_READ_ERROR, bytes(size)
        if len(b.data) != size:
            return fp.LOAD_WRONG_SIZE, bytes(size)
        return fp.LOAD_OK, bytes(b.data)

    def stored(self, key):
        """The decoded record in the direct NVS (a dict), or None when absent / damaged / the wrong size."""
        load, data = self._peek(key)
        if load != fp.LOAD_OK:
            return None
        return {"FBP": fp.unpack_profile, "FBW": fd.unpack_provision, "FBS": fp.unpack_failback}[key](data)

    def state_of(self, key) -> str:
        return self.sim.nvs_direct.state_of(KEY[key])

    def nvs_image(self) -> dict:
        return {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in self.sim.nvs_direct.blobs.items()}

    def model_class(self, anomaly=0):
        """(class name, why, rule): what the FB-B0 model composes from the CURRENT NVS image - the oracle the next boot's B1 must
        agree with (compose_profile_class over the stored bytes; no read is performed)."""
        pl, pb = self._peek("FBP")
        wl, wb = self._peek("FBW")
        cls, why, rule = fd.compose_profile_class(pl, pb, wl, wb, anomaly)
        return CLASS[cls], fd.WHY_NAMES[why], rule

    def snapshot(self):
        """Every global (frozen) and every entity's publication count - the evidence for 'this refusal touched NOTHING'."""
        return self.sim.snapshot_state()

    def diff(self, snap, ignore=()):
        """{"globals": [names that changed since snap], "published": {entity: [values published since]}} (E.EngineMixin.state_diff)."""
        return self.sim.state_diff(snap, ignore)

    def mark(self):
        return self.sim.mark()

    def since(self, m):
        return self.sim.since(m)

    def nvs_set_history(self) -> list:
        """Every direct-NVS set_blob over ALL boots of this driver: [(boot_no, name, bytes, result)]."""
        cur = [(self.boots, E.FB_KEY_NAMES.get(k, str(k)), d, r) for k, d, r in self.sim.nvs_direct.sets]
        return list(self._sets_prior_boots) + cur

    def modbus_writes(self) -> list:
        return [x for x in self.sim.modbus_log if x[0] == "write"]

    def modbus_reads(self) -> list:
        return [(x[1], len(x[2])) for x in self.sim.modbus_log if x[0] == "read"]

    # ------------------------------------------------------------------ time
    def advance(self, ms):
        self.sim.run_for(int(ms))
        return self

    def idle(self, max_ms=600_000):
        return self.sim.run_until_idle(max_ms)

    def start_housekeeping(self):
        """Start the FB 10 s interval (the one that mentions the candidate flag), as the device always has it running."""
        started = self.sim.start_intervals(HOUSEKEEPING_MARK)
        self.housekeeping_on = True
        return started

    def stop_housekeeping(self):
        self.sim.stop_intervals(HOUSEKEEPING_MARK)
        self.housekeeping_on = False

    # ------------------------------------------------------------------ steps
    def step(self, label, fn, *, idle=True, max_ms=600_000, catch_cut=False) -> Step:
        """Run `fn(driver)` as one measured operation: a Mark before, the engine run to idle after (idle=True), then a Step.
        A PowerCut inside is re-raised unless catch_cut=True (then Step.cut holds it and the sim stays frozen at the cut)."""
        sim = self.sim
        m = sim.mark()
        t0 = sim.now_ms
        before = {k: len(sim.ent(eid).published) for k, eid in B_IDS.items()}
        task, cut = None, None
        try:
            task = fn(self)
            if idle:
                sim.run_until_idle(max_ms)
        except PowerCut as e:
            if not catch_cut:
                raise
            cut = e
        pub = {k: [str(x) for x in sim.ent(B_IDS[k]).published[before[k]:]] for k in B_IDS
               if len(sim.ent(B_IDS[k]).published) > before[k]}
        st = Step(label, sim.since(m), self.texts(), pub, task, cut, t0, sim.now_ms)
        self.steps.append(st)
        return st

    def press_review(self, **kw) -> Step:
        return self.step("review", lambda d: d.sim.press_button(d.review_button), **kw)

    def review(self, expect=None, **kw) -> Step:
        st = self.press_review(**kw)
        if expect is not None and not self.b3.startswith(f"st={expect};"):
            raise DriverError(f"review(): expected st={expect}, B3 is {self.b3!r}, B9 {self.b9!r}")
        return st

    def arm_on(self):
        if not self.has_arm():
            raise FbbNotModelled(f"the firmware has no switch {self.arm_id!r}")
        self.sim.operator_switch(self.arm_id, True)
        return self

    def arm_off(self):
        if not self.has_arm():
            raise FbbNotModelled(f"the firmware has no switch {self.arm_id!r}")
        self.sim.operator_switch(self.arm_id, False)
        return self

    def execute(self, action, target_id="", confirmation="", *, tail=None, **kw) -> Step:
        """The api action (esphome.<node>_fallback_profile_execute) with these three strings, then the engine to idle."""
        if not self.has_api():
            raise FbbNotModelled(f"the firmware has no api action {self.api_name!r}")
        extra = {} if tail is None else {"_tail": tail}
        return self.step(f"execute {action}", lambda d: d.sim.call_api(d.api_name, action=action, target_id=target_id,
                                                                        confirmation=confirmation, **extra), **kw)

    def save(self, target_id=None, confirmation=None, *, arm=True, replace_corrupt=False, **kw) -> Step:
        tid = self.b4 if target_id is None else target_id
        phrase = (f"SAVE {tid}" + (" REPLACE CORRUPT" if replace_corrupt else "")) if confirmation is None else confirmation
        if arm:
            self.arm_on()
        return self.execute("SAVE", tid, phrase, **kw)

    def invalidate(self, target_id=None, confirmation=None, *, arm=True, **kw) -> Step:
        tid = self.b2_id() if target_id is None else target_id
        phrase = f"INVALIDATE {tid}" if confirmation is None else confirmation
        if arm:
            self.arm_on()
        return self.execute("INVALIDATE", tid, phrase, **kw)

    # ------------------------------------------------------------------ power cuts
    def cut_when(self, pred, message="power cut"):
        """Raise PowerCut from the first timeline event (sim.events entry) satisfying pred(event)."""
        self.sim.power_cut_when(pred, message)
        return self

    def cut_before_nvs(self, op="set", key="FBP", nth=1):
        """PowerCut at the START of the nth direct-NVS `op` ("set" | "read" | "get" | "stats") of that key, before it takes effect."""
        want = None if key is None else fd.decimal_key(KEY[key]) if key in KEY else str(key)
        seen = [0]
        prev = self.sim.nvs_direct.before_op

        def hook(o, k):
            if prev is not None:
                prev(o, k)
            if o == op and (want is None or k == want):
                seen[0] += 1
                if seen[0] == nth:
                    raise PowerCut(f"power cut before NVS {op} #{nth} of {key}")
        self.sim.nvs_direct.before_op = hook
        return self

    def cut_after_nvs(self, op="set", key="FBW", nth=1):
        """PowerCut right AFTER the nth direct-NVS `op` of that key took effect (the flash holds the result)."""
        want = None if key is None else fd.decimal_key(KEY[key]) if key in KEY else str(key)
        seen = [0]

        def pred(ev):
            if ev[0] == "nvs" and ev[1] == op and (want is None or ev[2] == want):
                seen[0] += 1
                return seen[0] == nth
            return False
        return self.cut_when(pred, f"power cut after NVS {op} #{nth} of {key}")

    def cut_at_nvs_point(self, point, *, from_now=True):
        """DirectNvs.cut_at = `point`: 2n = BEFORE the n-th NVS event (get_blob probe / read, set_blob, get_stats) counted from now,
        2n+1 = AFTER it."""
        if from_now:
            self.sim.nvs_direct.events = 0
        self.sim.nvs_direct.cut_at = int(point)
        return self

    def cut_after_event(self, k, kinds=("nvs",), *, from_now=True):
        """PowerCut right after the k-th (0-based) timeline event whose kind (event[0]) is in `kinds`, counted from now."""
        n = [-1]

        def pred(ev):
            if ev[0] in kinds:
                n[0] += 1
                return n[0] == k
            return False
        return self.cut_when(pred, f"power cut after timeline event {k}")

    def when(self, pred, fn, *, once=True):
        """Run fn(sim) at the first (every, if once=False) timeline event satisfying pred(event) - right after that event took effect and
        before anything else runs: interleave the world with the firmware at an exact instant (a write arm turning on between two reads, a
        register changing right after the FBW set, a foreign frame appearing after the witness landed)."""
        prev = self.sim.event_hook
        fired = [False]

        def hook(ev):
            if prev is not None:
                prev(ev)
            if (not once or not fired[0]) and pred(ev):
                fired[0] = True
                fn(self.sim)
        self.sim.event_hook = hook
        return self

    def clear_cuts(self):
        self.sim.event_hook = None
        self.sim.nvs_direct.before_op = None
        self.sim.nvs_direct.cut_at = None
        return self

    # ------------------------------------------------------------------ reboot
    def reboot(self, *, env="same", boot=True, resolve_nvs=True, boot_ms=1_000_000, housekeeping=None, wipe=False, absent_keys=(),
               handle=1):
        """A power cycle. Everything in RAM is gone (globals, scripts, the arm, the candidate, the write latch); what survives is the
        register bank, the legacy tag store and the direct NVS (resolved per its write faults). The REAL on_boot runs, then the
        driver's environment is re-applied (env="same" = the one it was built with; "bare" = an untrusted fresh boot).
        Boot-time storage events: wipe=True = ESPHome's whole-partition erase after a failed nvs_open (F10: every FB key and every legacy
        record gone); absent_keys=("FBW", ...) = an init-time loss of those keys (F11, the 24-bit duplicate erase); handle=0 = the NVS
        handle is zero at boot (F12: every read reports unavailable)."""
        old = self.sim
        self._sets_prior_boots += [(self.boots, E.FB_KEY_NAMES.get(k, str(k)), d, r) for k, d, r in old.nvs_direct.sets]
        nv = None
        if wipe:
            nv = H.DirectNvs.wipe(handle=handle)
        elif absent_keys or handle != 1:
            nv = old.nvs_direct.reboot(absent_keys=tuple(KEY[k] if isinstance(k, str) else k for k in absent_keys), handle=handle)
        sim = old.reboot(boot_ms=boot_ms, resolve_nvs=(resolve_nvs and nv is None))
        if nv is not None:
            sim.nvs_direct = nv
        if wipe:
            sim.nvs = {}
        self.sim = sim
        self.boots += 1
        self._hooks.before = {}
        self._bind_hooks()
        if boot:
            sim.run_boot()
        if self.salt:
            sim.random_values = [0]
        self._time_flows = False
        sim.epoch = self.epoch
        self.apply_env(self.env_name if env == "same" else env)
        if (self.housekeeping_on if housekeeping is None else housekeeping):
            self.start_housekeeping()
        return self


class _FlowingClock(ds.Clock):
    """ntp_time whose wall clock advances with the virtual clock (set_time(flow=True))."""

    def __init__(self, sim, t0_ms, epoch0):
        super().__init__(sim, "ntp_time")
        self._t0, self._e0 = t0_ms, epoch0

    def now(self):
        t = self._e0 + (self._sim.now_ms - self._t0) // 1000
        return ds.TimeNow(self._sim.ntp_valid, t, (t // 3600) % 24, (t // 60) % 60)


# ---------------------------------------------------------------------------
# invariants every scenario may assert after a step
# ---------------------------------------------------------------------------
def text_invariants(drv: "Driver") -> list:
    """Everything every FB text entity (B1..B9) ever published on this driver's CURRENT sim: at most 200 characters, no hazard word
    (failed / deferred / the card's patterns) anywhere, B1 one of the nine class names, B9 starting with a locked prefix, B3..B8 free of
    spaces. [] = clean."""
    errs = []
    for key, eid in B_IDS.items():
        for s in [str(x) for x in drv.sim.ent(eid).published]:
            if len(s) > 200:
                errs.append(f"{key}: {len(s)} chars")
            for rx in D8_HAZARD:
                if rx.search(s):
                    errs.append(f"{key}: hazard word /{rx.pattern}/ in {s[:70]!r}")
            if key == "B1" and s not in CLASS.values():
                errs.append(f"B1: {s!r} is not a class name")
            if key == "B9" and not s.startswith(B9_PREFIXES):
                errs.append(f"B9 prefix: {s[:70]!r}")
            if key in ("B3", "B4", "B5", "B6", "B7", "B8") and " " in s:
                errs.append(f"{key}: a space in {s[:70]!r}")
    return errs


def idle_invariants(drv: "Driver", *, locked: bool = False) -> list:
    """At idle no FB operation is marked in progress, nothing is half-accepted, no FB script is running, and the shared write mutex is
    free (unless the scenario holds it itself: locked=True). [] = clean."""
    g = drv.sim.g
    errs = []
    for k in ("fallback_profile_op_in_progress", "fallback_profile_gate_accepted"):
        if g.get(k):
            errs.append(f"{k} is set at idle")
    for k in ("fallback_profile_step", "fallback_profile_op_purpose"):
        if g.get(k):
            errs.append(f"{k} == {g[k]} at idle")
    if g.get("manual_write_in_progress") and not locked:
        errs.append("manual_write_in_progress is still held at idle")
    running = sorted(s for s in drv.sim.running if s.startswith("fallback_profile_"))
    if running:
        errs.append(f"FB scripts still running at idle: {running}")
    return errs


# ---------------------------------------------------------------------------
# power-cut sweeps
# ---------------------------------------------------------------------------
def _run_cut(make, operation, install, label, index, point, reboot):
    d = make()
    install(d)
    cut, err = False, None
    try:
        operation(d)
    except PowerCut:
        cut = True
    except BaseException as e:  # noqa: BLE001 - reported to the caller, who asserts on it
        err = e
    sets = [(E.FB_KEY_NAMES.get(k, str(k)), dd, r) for k, dd, r in d.sim.nvs_direct.sets]
    if reboot:
        d.reboot()
    return CutPoint(index, label, cut, d, sets, point, err)


def sweep_nvs_cuts(make, operation, *, reboot=True, points=None):
    """A power cut at EVERY direct-NVS event of `operation(driver)` (get_blob probe / read, set_blob, get_stats), both BEFORE
    (point 2n) and AFTER (2n+1) the event takes effect, each on a fresh driver from `make()`, each followed by reboot() (unless
    reboot=False). A dry run first counts the events; the sweep also contains the 'no cut' row (point == 2*events + 1 is past the
    last event, cut=False). Returns [CutPoint]. `points` restricts the numbers."""
    probe = make()
    probe.sim.nvs_direct.events = 0
    operation(probe)
    n_events = probe.sim.nvs_direct.events
    rows = []
    pts = list(range(0, 2 * n_events + 2)) if points is None else list(points)
    for i, p in enumerate(pts):
        def install(d, p=p):
            d.sim.nvs_direct.events = 0
            d.sim.nvs_direct.cut_at = p
        rows.append(_run_cut(make, operation, install, f"nvs point {p} ({'before' if p % 2 == 0 else 'after'} event {p // 2})", i, p,
                             reboot))
    return rows


def sweep_timeline_cuts(make, operation, *, kinds=("nvs", "read", "deliver", "switch"), reboot=True, points=None):
    """A power cut right after EVERY timeline event of the given kinds (event[0]) that `operation(driver)` produces - Modbus reads and
    deliveries as well as NVS operations - each on a fresh driver, each followed by reboot(). Returns [CutPoint]."""
    probe = make()
    mark = len(probe.sim.events)
    operation(probe)
    n_events = sum(1 for ev in probe.sim.events[mark:] if ev[0] in kinds)
    rows = []
    pts = list(range(n_events)) if points is None else list(points)
    for i, p in enumerate(pts):
        rows.append(_run_cut(make, operation, lambda d, p=p: d.cut_after_event(p, kinds), f"after timeline event {p}", i, p, reboot))
    return rows


CAPABILITIES = {
    "boot_real_yaml": "Driver() boots the live firmware YAML (or a mutant text) through the real on_boot with seeded NVS, markers, "
                      "FBS and the golden stored profile",
    "operator_actions": "review / arm_on / arm_off / execute / save / invalidate / heartbeat as the operator and Home Assistant "
                        "would call them (switch flip, api action call), each a measured Step",
    "world_state": "set_words / before_read (bank hooks at a chosen read) / set_time / supervise / write_arm / lease / mutex / put / "
                   "fault_write / fault_read / advance",
    "observation": "B1..B9 texts, published history, globals, class, candidate, decoded stored records, the FB-B0 model class of the "
                   "NVS image, Modbus and NVS-set logs across reboots",
    "reboot": "reboot() = power cycle through the real on_boot with the NVS carried over and the environment re-applied",
    "power_cuts": "cut_when / cut_before_nvs / cut_after_nvs / cut_at_nvs_point / cut_after_event, sweep_nvs_cuts / sweep_timeline_cuts",
}
