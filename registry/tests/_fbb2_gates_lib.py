"""FB-B2 SAVE gates / refusals / races suite - shared library (t-gates).

Support module of registry/tests/test_fallback_save_gates.py (and of the scenario modules _fbb2_gates_success.py,
_fbb2_gates_refusals.py, _fbb2_gates_races.py, _fbb2_gates_mutants.py). It owns nothing of the firmware: every scenario runs the REAL
firmware YAML through registry/tests/_fbb2_drive.Driver (the transpiled lambdas on the strict FbbSim harness).

WHAT IS INDEPENDENT HERE. A scenario never takes an expectation from the implementation under test:
  * the expected FBP / FBW byte images are built from the FB-A profile mirror (registry/fallback_profile.py: blank_profile +
    seal_profile over the NAMED golden fields) and the independent FB-B0 mirror (registry/fallback_durable.py: make_provision),
    with the locked golden vectors of the architecture (W-FIRST 0xA8B8788B4C915BB6, first profile binding 0xB74CE0FA6297474D)
    asserted as literals;
  * the expected operator texts (TXT) are literals copied from the locked design (FB_B2_IMPLEMENTATION_NOTES.md section 3, S1 4.5 / 8.5,
    master 4.7), NOT read back from registry/fallback_save.py;
  * the next-boot class of every durable image is judged by the FB-B0 model oracle (Driver.model_class);
  * the gate ORDER (first failure wins) is the S1 8.5 list written out in ORDER below.

STRUCTURE. A scenario is a function `fn(mk, ex)`: `mk(**driver_kwargs)` builds a Driver over the firmware under test (the live YAML,
or a mutant text / mutant mirror: class Mk), `ex` records assertions in named ROWS (Exp.row). run_scenario(name, mk) runs one and
returns the Exp; on the live firmware every row becomes a check(), for a mutant the mutant is KILLED by a scenario iff some row fails
(an exception is an ERROR, never a kill).
"""

from __future__ import annotations

import re
import sys
import traceback
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import _fbb1_engine as E  # noqa: E402
import _fbb2_drive as D  # noqa: E402
import _fbb_harness as H  # noqa: E402
import fallback_capture as fc  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

REGISTRY = HERE.parent
FW_PATH = D.FW_PATH

# ---------------------------------------------------------------------------
# assertion rows
# ---------------------------------------------------------------------------


class Exp:
    """Assertions grouped in named rows. `failed` = [(row label, [failure messages])]."""

    def __init__(self):
        self.rows: list = []
        self._cur = None
        self.n = 0
        self.errors: list = []

    def row(self, label: str) -> "Exp":
        self._cur = [label, [], 0]
        self.rows.append(self._cur)
        return self

    def _need_row(self):
        if self._cur is None:
            self.row("(scenario)")

    def ok(self, cond, label: str) -> bool:
        self._need_row()
        self._cur[2] += 1
        self.n += 1
        if not cond:
            self._cur[1].append(label)
        return bool(cond)

    def eq(self, got, want, label: str) -> bool:
        return self.ok(got == want, f"{label}: got {got!r}, want {want!r}")

    def has(self, text, frag, label: str) -> bool:
        return self.ok(frag in str(text), f"{label}: {frag!r} not in {str(text)[:140]!r}")

    def starts(self, text, prefix, label: str) -> bool:
        return self.ok(str(text).startswith(prefix), f"{label}: {str(text)[:100]!r} does not start with {prefix!r}")

    def empty(self, seq, label: str) -> bool:
        return self.ok(not seq, f"{label}: {seq!r}")

    @property
    def failed(self) -> list:
        return [(r[0], r[1]) for r in self.rows if r[1]]

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_fail_messages(self) -> int:
        return sum(len(r[1]) for r in self.rows)


SCENARIOS: dict = {}
SCENARIO_DOC: dict = {}


def scenario(name: str, doc: str = ""):
    def deco(fn):
        if name in SCENARIOS:
            raise AssertionError(f"duplicate scenario {name}")
        SCENARIOS[name] = fn
        SCENARIO_DOC[name] = doc or (fn.__doc__ or "").strip().split("\n")[0]
        return fn
    return deco


def run_scenario(name: str, mk) -> Exp:
    ex = Exp()
    try:
        SCENARIOS[name](mk, ex)
    except D.DriverError as e:
        # a setup guard of the driver (review(expect=...)) did not hold: the firmware under test does not behave the way every scenario
        # builds on, which is a detection (a failing row), not an evaluation error
        ex.row("setup guard")
        ex.ok(False, f"setup guard failed: {str(e)[:200]}")
    except BaseException as e:  # noqa: BLE001 - an exception is reported as an ERROR (a failing row on the live firmware)
        ex.errors.append("".join(traceback.format_exception_only(type(e), e)).strip()[:300])
    return ex


# ---------------------------------------------------------------------------
# the firmware (or a mutant of it) under test
# ---------------------------------------------------------------------------
_LIVE_TEXT: list = []


def live_text() -> str:
    if not _LIVE_TEXT:
        _LIVE_TEXT.append(FW_PATH.read_text(encoding="utf-8"))
    return _LIVE_TEXT[0]


class Mk:
    """Driver factory over the firmware under test. text= a mutant YAML text; fbsave= / fbcap= mutant mirror modules."""

    def __init__(self, label: str = "live", *, text: str | None = None, fbsave=None, fbcap=None):
        self.label = label
        self.text = text
        self.fw = D.load_fw(text) if text is not None else None
        self.fbsave = fbsave
        self.fbcap = fbcap

    def __call__(self, **kw) -> "D.Driver":
        return D.Driver(fw=self.fw, fbsave=self.fbsave, fbcap=self.fbcap, **kw)


LIVE = Mk()

# ---------------------------------------------------------------------------
# text mutation helpers (the mutants are exact-count text edits, never silent no-ops)
# ---------------------------------------------------------------------------


def script_span(text: str, script_id: str) -> tuple:
    """[start, end) of one top-level `script:` entry (`  - id: <script_id>`) in the firmware text."""
    head = f"\n  - id: {script_id}\n"
    i = text.find(head)
    if i < 0 or text.find(head, i + 1) >= 0:
        raise D.DriverError(f"script {script_id!r} found {text.count(head)} times")
    i += 1
    m = re.compile(r"\n  - id: |\n\n[a-z_]+:\n").search(text, i + 8)
    return i, (m.start() if m else len(text))


def edit_script(text: str, script_id: str, old: str, new: str, count: int = 1) -> str:
    a, b = script_span(text, script_id)
    body = text[a:b]
    n = body.count(old)
    if n != count:
        raise D.DriverError(f"in script {script_id}: anchor occurs {n} times, want {count}: {old[:90]!r}")
    return text[:a] + body.replace(old, new) + text[b:]


def edit_text(text: str, old: str, new: str, count: int = 1) -> str:
    return D.mutate(text, old, new, count)


_MUTANT_MODULES = [0]


def _load_module(modname: str, src: str, path: Path, swap: dict | None = None):
    """Execute a (mutated) copy of a mirror source as a module of its own. The module is registered in sys.modules under a UNIQUE name (the
    dataclass machinery looks its defining module up by name); `swap` temporarily replaces other modules the source imports by name."""
    _MUTANT_MODULES[0] += 1
    name = f"{modname}_{_MUTANT_MODULES[0]}"
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    saved = {}
    for k, m in {**(swap or {}), name: mod}.items():
        saved[k] = sys.modules.get(k)
        sys.modules[k] = m
    try:
        exec(compile(src, str(path), "exec"), mod.__dict__)
    finally:
        for k, m in saved.items():
            if k == name:
                continue            # stays registered
            if m is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = m
    return mod


def mirror_mutant(old: str, new: str, count: int = 1, *, which: str = "save") -> tuple:
    """(fbsave module, fbcap module) of a mutated Python mirror: which="save" mutates registry/fallback_save.py, "capture" mutates
    registry/fallback_capture.py (fbcap AND the capture module the save mirror sees). The mutation anchor must occur exactly `count` times."""
    p_cap = REGISTRY / "fallback_capture.py"
    p_save = REGISTRY / "fallback_save.py"
    cap_src = p_cap.read_text(encoding="utf-8")
    save_src = p_save.read_text(encoding="utf-8")
    if which == "save":
        if save_src.count(old) != count:
            raise D.DriverError(f"fallback_save.py anchor occurs {save_src.count(old)} times, want {count}: {old[:80]!r}")
        mod = _load_module("fallback_save_mutant", save_src.replace(old, new), p_save)
        return mod, None
    if cap_src.count(old) != count:
        raise D.DriverError(f"fallback_capture.py anchor occurs {cap_src.count(old)} times, want {count}: {old[:80]!r}")
    cap_mod = _load_module("fallback_capture_mutant", cap_src.replace(old, new), p_cap)
    save_mod = _load_module("fallback_save_mutant", save_src, p_save, swap={"fallback_capture": cap_mod})
    return save_mod, cap_mod


# ---------------------------------------------------------------------------
# independent expected records
# ---------------------------------------------------------------------------
K_P, K_W, K_S = D.K_P, D.K_W, D.K_S
OPNAME = {fd.PROV_OP_SAVE: "SAVE", fd.PROV_OP_INVALIDATE: "INV", fd.PROV_OP_REPLACE_CORRUPT: "RC"}
FIRST_PROFILE_BINDING = 0xB74CE0FA6297474D   # locked golden: the first-save profile (generation 1, the golden words, epoch 1790000000)
W_FIRST_BINDING = 0xA8B8788B4C915BB6         # locked golden vector W-FIRST (hw 1, prior 0/0, hw_binding = the profile binding, op SAVE)
EPOCH0 = D.EPOCH0


def exp_profile(generation: int, epoch: int = EPOCH0, **fields) -> dict:
    """The sealed FBP the SAVE must write for the golden words (or for the golden fields overridden by `fields`)."""
    return D.gold_profile(generation=generation, captured_epoch=epoch, **fields)


def exp_witness(generation: int, profile: dict, prior_generation: int, prior_binding: int, op: int = fd.PROV_OP_SAVE) -> dict:
    """The sealed FBW: hw = the new generation, hw_binding = the new profile's binding, prior_* = the AUTHENTIC prior (else 0 / 0)."""
    return fd.make_provision(generation, profile["binding"], prior_generation, prior_binding if prior_generation else 0, K_P, 1, op)


def pair_bytes(profile: dict, witness: dict) -> dict:
    return {"FBW": fd.pack_provision(witness), "FBP": fp.pack_profile(profile)}


def words_for(**fields) -> list:
    """The 31 capture words for the golden fields overridden by `fields` (the inverse mapping of the capture mirror)."""
    return list(fc.words_of(D.gold_profile(**fields)))


def word_index(register: int) -> int:
    return fc.REGS.index(register)


READS4 = list(D.READS)

# ---------------------------------------------------------------------------
# locked operator texts (literals; FB_B2_IMPLEMENTATION_NOTES.md section 3 / S1 4.5 / master 4.7)
# ---------------------------------------------------------------------------
SAVE_PFX = "SAVE REFUSED - "
TXT = {
    "progress": "save in progress - re-reading live configuration",
    "G1": SAVE_PFX + "another Fallback Profile operation is in progress",
    "G2": SAVE_PFX + "ECCO Fallback Profile Arm is not on",
    "G3": SAVE_PFX + "no saveable candidate - press Review Current Configuration first",
    "G4": SAVE_PFX + "candidate expired (120 s) - review again",
    "G5": SAVE_PFX + "candidate ID must be 16 hex characters",
    "G6": SAVE_PFX + "candidate ID does not match the current candidate",
    "G8": SAVE_PFX + "durable state not loaded yet",
    "G9": SAVE_PFX + "previous save outcome unknown this boot - reboot to re-verify first",
    "G9a": SAVE_PFX + "stored profile read anomaly this boot; reboot to re-derive it first",
    "G10": SAVE_PFX + "Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again",
    "G11": SAVE_PFX + "clock not NTP-synchronised this boot; the capture time would be untrusted",
    "G12": SAVE_PFX + "a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first",
    "G13": SAVE_PFX + "another ECCO inverter write started since Review - review again",
    "G15_episode": SAVE_PFX + "a failback episode record exists; only the firmware that created it can resolve it",
    "RESTORE": "RESTORE REFUSED - not implemented in this firmware",
    "ACKNOWLEDGE": "ACKNOWLEDGE REFUSED - not implemented in this firmware",
    "idle7": SAVE_PFX + "inverter bus stayed busy for 7 s; profile unchanged; review again",
    "prior_changed": SAVE_PFX + "stored profile changed since Review; profile unchanged",
    "bus_quiet": SAVE_PFX + "inverter bus not quiet at commit; profile unchanged",
    "storage_unhealthy": SAVE_PFX + "storage not healthy - nothing saved",
    "internal_ctx": "INTERNAL - Fallback Profile dispatch context invalid; nothing written",
    # FB-B2 (final review F3): plan_save PO14, the built record did not validate (FB_B2_IMPLEMENTATION_NOTES.md section 3.3, S2-8)
    "internal_record": SAVE_PFX + "internal: built record did not validate; nothing written",
}


def t_phrase(cid: str, replace_corrupt: bool = False) -> str:
    return SAVE_PFX + f"confirmation phrase mismatch (expected 'SAVE {cid}{' REPLACE CORRUPT' if replace_corrupt else ''}')"


def t_unsupported(tok: str) -> str:
    return f"REFUSED - unsupported action '{tok}'"


def t_saved(gen: int) -> str:
    return f"SAVED - known-good profile generation {gen} saved (verified this boot)"


def t_since_review(reg: int, a: int, b: int) -> str:
    return SAVE_PFX + f"live configuration changed since Review (register {reg}: reviewed {a}, now {b}); profile unchanged; review again"


def t_during_read(reg: int, a: int, b: int) -> str:
    return SAVE_PFX + f"live configuration changed during the read (register {reg}: {a} then {b}); profile unchanged"


# slot refusal bodies (S1 4.5). D = the domain label.
DOMAIN_LABEL = {"fp": "Free Power", "dump": "Dump to Grid", "r244": "Register 244 test"}


def t_slot(kind: str, dom: str) -> str:
    lab = DOMAIN_LABEL[dom]
    body = {
        "active": f"{lab} is active; live settings are a temporary overlay - end it first",
        "rr": f"{lab} must restore original settings first",
        "pc": f"{lab} restore verified; durable clear still pending" + (" - press Restore Original (armed)" if dom == "r244" else ""),
        "on": f"{lab} needs an operator recovery action first",
        "mc": f"{lab} recovery metadata is CORRUPT (hard lockout); Fallback never overwrites or proceeds past it; do not erase NVS",
        "unk_boot": f"{lab} recovery state UNKNOWN since boot (marker unreadable); an obligation cannot be ruled out; Fallback never proceeds past it",
        "ram": f"{lab} in-memory recovery state is inconsistent; a reboot must re-derive it before saving",
        "start": f"a {lab} start is in progress; live settings are about to become a temporary overlay",
        "end": f"a {lab} restore or recovery action is running; try again when it finishes",
        "stuck": f"{lab} in-progress flag is set with no running operation (possible leak); a reboot re-derives it",
        "ghost_rr": f"{lab} stored marker says RESTORE_REQUIRED but memory says clear; saving blocked until reboot, which re-derives it "
                    f"(the domain may then restore its saved original)",
        "ghost_pc": f"{lab} stored marker says PENDING_CLEAR but memory says clear; saving blocked until reboot, which re-derives it "
                    f"(the domain may then restore its saved original)",
        "unr_runtime": f"{lab} recovery marker became unreadable at runtime; saving blocked until reboot. After reboot it may read "
                       f"absent: verify live settings first; do not erase NVS",
        "malformed": f"{lab} recovery marker is malformed (found at runtime); saving blocked until reboot, which re-derives it as a hard lockout",
    }[kind]
    return SAVE_PFX + body


def t_bus(owner: str) -> str:
    return SAVE_PFX + f"another inverter transaction is in progress ({owner}); try again shortly"


def t_lock_stuck(seconds: int) -> str:
    return SAVE_PFX + f"inverter write lock held for {seconds} s (possible leak); a reboot may be required"


def t_read(kind: str, blk: str, code: int = 2) -> str:
    return SAVE_PFX + {
        "no_response": f"no response reading registers {blk}; profile unchanged",
        "exception": f"inverter returned exception code 0x{code:02X} on registers {blk}; profile unchanged",
        "short": f"short reply reading registers {blk}; profile unchanged",
        "not_sent": f"read of registers {blk} could not be queued; profile unchanged",
        "nonstandard": f"non-standard reply reading registers {blk}; profile unchanged",
        "bounded": f"read of registers {blk} did not complete within 3 s; profile unchanged",
    }[kind]


# the gate order of the locked design (S1 8.5; M 3.8): the pair-ordering oracle
ORDER = ["G1", "G0", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G9a", "G10", "G11", "G12", "G13", "G14", "G15", "G16fp",
         "G16dump", "G16r244"]

HAZARD = D.D8_HAZARD


# ---------------------------------------------------------------------------
# state observation helpers
# ---------------------------------------------------------------------------
GATE_REFUSAL_GLOBALS = {
    # the api action's own copies + the arm stamp + the one-shot consumption of the candidate and the idle vector text
    "fallback_profile_exec_action", "fallback_profile_exec_target_id", "fallback_profile_exec_confirmation",
    "fallback_profile_exec_hb_ok", "fallback_profile_arm_on_ms", "fallback_profile_cand_valid", "fallback_profile_cand_saveable",
    "fallback_profile_capture_state", "fallback_profile_obl_text",
}
EXEC_COPIES = {"fallback_profile_exec_action", "fallback_profile_exec_target_id", "fallback_profile_exec_confirmation",
               "fallback_profile_exec_hb_ok", "fallback_profile_arm_on_ms"}
CTX_GLOBALS = ("fallback_profile_save_ctx_valid", "fallback_profile_save_verified", "fallback_profile_save_ctx_id",
               "fallback_profile_save_ctx_prior_class", "fallback_profile_save_ctx_prior_gen", "fallback_profile_save_ctx_prior_binding",
               "fallback_profile_save_ctx_replace_corrupt")
IDLE_B3_RX = re.compile(r"^st=IDLE;prior=-;exp=-;warn=-;obl=[A-Z0-9:,]+;latch=[A-Z0-9,-]+;sv=-$")


def ready(mk, *, seed="none", words=None, expect="CANDIDATE_READY", **kw):
    """A Driver on the firmware under test with a Review already pressed (the candidate exists)."""
    d = mk(seed=seed, words=words, **kw) if words is not None else mk(seed=seed, **kw)
    d.review(expect=expect)
    return d


def nothing_held(d, locked: bool = False) -> list:
    errs = D.idle_invariants(d, locked=locked)
    g = d.g
    for k in CTX_GLOBALS:
        if g[k] not in (False, 0):
            errs.append(f"{k} = {g[k]!r} at idle")
    if any(d.arr("fallback_profile_save_ctx_words")):
        errs.append("fallback_profile_save_ctx_words not cleared")
    return errs


def candidate_consumed(d) -> bool:
    c = d.candidate()
    return (not c["valid"]) and (not c["saveable"])


def execute_call(d, call: dict):
    """The operator call: arm on (default), then the api action with action / target_id / confirmation (defaults: SAVE, B4, SAVE <B4>)."""
    action = call.get("action", "SAVE")
    tid = call.get("target_id", None)
    phrase = call.get("confirmation", None)
    tid = d.b4 if tid is None else tid
    phrase = (f"SAVE {tid}" + (" REPLACE CORRUPT" if call.get("replace_corrupt") else "")) if phrase is None else phrase
    if call.get("arm", True):
        d.arm_on()
    kw = {k: call[k] for k in ("idle", "tail") if k in call}
    return d.execute(action, tid, phrase, **kw)


def check_refusal(ex: Exp, d, st, want, *, reads=(), nvs_ops=0, consumed=True, arm_off=True, label="", globals_subset=True,
                  snap=None, published_once=True, unconfirmed=False, locked=False, accepted=False):
    """Everything a refused SAVE must leave behind (the locked one-shot / zero-authority rules)."""
    L = label or want[:40]
    ex.eq(d.b9, want, f"{L}: B9 text")
    if published_once:
        ex.eq(st.published.get("B9", []), ([TXT["progress"]] if accepted else []) + [want],
              f"{L}: B9 published exactly {'the in-progress line then ' if accepted else ''}this one line")
    ex.eq(st.violations_fb((), reads=[tuple(r) for r in reads]), [], f"{L}: no Modbus write, no durable write, reads exactly {list(reads)}")
    if nvs_ops is not None:
        ex.eq(len(st.since.nvs_ops), nvs_ops, f"{L}: direct NVS operations (a gate refusal never touches storage)")
    if arm_off:
        ex.eq(d.arm_state, False, f"{L}: arm turned off")
    if consumed:
        ex.ok(candidate_consumed(d), f"{L}: candidate consumed")
        ex.eq(d.b4, "-", f"{L}: B4 '-'")
        ex.ok(bool(IDLE_B3_RX.match(d.b3)), f"{L}: B3 is the idle form: {d.b3!r}")
    ex.eq(nothing_held(d, locked=locked), [], f"{L}: nothing held (locks, op flags, context)")
    ex.eq(D.text_invariants(d), [], f"{L}: text invariants (<= 200, no hazard word, locked prefixes)")
    ex.ok(len(want) <= 200, f"{L}: expected text is within 200 chars")
    ex.eq(d.g["fallback_profile_save_unconfirmed"], unconfirmed, f"{L}: SAVE_UNCONFIRMED overlay unchanged by the refusal")
    if snap is not None and globals_subset:
        diff = d.diff(snap)["globals"]
        extra = sorted(set(diff) - GATE_REFUSAL_GLOBALS)
        ex.eq(extra, [], f"{L}: only the one-shot / copy globals changed")


def gate_case(ex: Exp, mk, label: str, want, *, setup=None, call=None, seed="none", words=None, reads=(), consumed=True, nvs_ops=0,
              kw=None, review=True, arm_off=True, snap_check=True, unconfirmed=False, locked=False):
    """One refusal row: Driver + Review (unless review=False), `setup(d)` changes the world (may return call overrides), the execute call,
    then check_refusal. `want` may be a callable(d) -> text (for texts that embed the candidate id)."""
    ex.row(label)
    d = ready(mk, seed=seed, words=words, **(kw or {})) if review else mk(seed=seed, **(({"words": words} if words is not None else {}) | (kw or {})))
    cid = d.b4
    over = setup(d) if setup else None
    c = dict(call or {})
    if isinstance(over, dict):
        c.update(over)
    snap = d.snapshot()
    st = execute_call(d, c)
    text = want(d, cid) if callable(want) else want
    check_refusal(ex, d, st, text, reads=reads, label=label, consumed=consumed, nvs_ops=nvs_ops, arm_off=arm_off,
                  snap=snap if snap_check else None, unconfirmed=unconfirmed, locked=locked)
    return d, st


# ---------------------------------------------------------------------------
# the success checks
# ---------------------------------------------------------------------------
_US_RX = re.compile(r";us=[0-9]+$")


def strip_us(b2: str) -> str:
    return _US_RX.sub(";us=*", b2)


def check_saved(ex: Exp, d, st, *, gen: int, prior_gen: int, prior_binding: int, op: int = fd.PROV_OP_SAVE, epoch: int = EPOCH0,
                profile_fields: dict | None = None, label: str = "", reads=READS4, reboot: bool = True, seen_texts: dict | None = None,
                b9_seq: list | None = None, consumed: bool = True):
    """The locked end state of a SAVE: exact FBW then FBP bytes, outcome text, texts coherent, locks released, candidate consumed, arm off,
    then (reboot=True) the REAL on_boot over the NVS the SAVE left: same class / generation / binding and the same B1 / B2 / B7 / B8."""
    L = label or f"SAVE g{gen}"
    prof = exp_profile(gen, epoch, **(profile_fields or {}))
    wit = exp_witness(gen, prof, prior_gen, prior_binding, op)
    want = pair_bytes(prof, wit)
    ex.eq(d.b9, t_saved(gen), f"{L}: B9")
    ex.eq(st.violations_fb(("FBW", "FBP"), bytes_=want, reads=[tuple(r) for r in reads]), [],
          f"{L}: exactly FBW then FBP with the independently built bytes, zero Modbus writes, reads == {len(reads)}")
    ex.eq([n for n, _b, _r in st.fb_sets], ["FBW", "FBP"], f"{L}: write order witness first")
    ex.eq([r for _n, _b, r in st.fb_sets], [0, 0], f"{L}: both writes returned ESP_OK")
    ex.eq(d.stored("FBP"), prof, f"{L}: stored FBP record")
    ex.eq(d.stored("FBW"), wit, f"{L}: stored FBW record")
    b = prof["binding"]
    ex.eq(d.b1, "VALID", f"{L}: B1")
    ex.ok(re.fullmatch(rf"g={gen};id={b:016X};at={epoch};ld=OK;df=-;w=OK;hw={gen};op={OPNAME[op]};why=-;werr=-;us=[1-9][0-9]*", d.b2) is not None,
          f"{L}: B2 grammar / values: {d.b2!r}")
    ex.eq(d.b7.split(";b=")[0].split(";")[:2], ["v=SAVED", f"g={gen}"], f"{L}: B7 v=SAVED, g")
    ex.ok(d.b7.endswith(f";b={b >> 32:08X}") and d.b8.endswith(f";b={b >> 32:08X}") and d.b8.startswith("v=SAVED;"),
          f"{L}: B7/B8 end with the 8-hex binding {b >> 32:08X}: {d.b7[-20:]!r} {d.b8[-20:]!r}")
    ex.ok(bool(IDLE_B3_RX.match(d.b3)), f"{L}: B3 idle form {d.b3!r}")
    ex.eq((d.b4, d.b5.startswith("v=NONE;"), d.b6.startswith("v=NONE;")), ("-", True, True), f"{L}: B4 '-', B5 / B6 NONE")
    ex.eq(st.published.get("B9", []), b9_seq if b9_seq is not None else [TXT["progress"], t_saved(gen)],
          f"{L}: B9 sequence: in-progress then the outcome")
    ex.eq(d.arm_state, False, f"{L}: arm off")
    if consumed:
        ex.ok(candidate_consumed(d), f"{L}: candidate consumed")
    ex.eq(nothing_held(d), [], f"{L}: nothing held")
    ex.eq(D.text_invariants(d), [], f"{L}: text invariants")
    ex.eq((d.g["fallback_profile_save_unconfirmed"], d.write_latched), (False, False), f"{L}: not SAVE_UNCONFIRMED, write latch clear")
    ex.eq(d.g["fallback_profile_seen_hw_gen"], gen, f"{L}: seen_hw_gen raised to the committed generation")
    ex.eq(d.model_class()[:2], ("VALID", "-"), f"{L}: the FB-B0 oracle reads the NVS image as VALID")
    pre = {"B1": d.b1, "B2": strip_us(d.b2), "B7": d.b7, "B8": d.b8}
    if seen_texts is not None:
        seen_texts.update(pre)
    if reboot:
        hist = d.nvs_set_history()
        d.reboot()
        post = {"B1": d.b1, "B2": strip_us(d.b2), "B7": d.b7, "B8": d.b8}
        ex.eq(d.b1, "VALID", f"{L}: after the real reboot B1 VALID")
        ex.eq(d.b2_id(), f"{b:016X}", f"{L}: after the reboot the same binding")
        ex.eq((post["B1"], post["B7"], post["B8"]), (pre["B1"], pre["B7"], pre["B8"]), f"{L}: B1 / B7 / B8 after the reboot equal the ones the SAVE published")
        ex.eq(re.sub(r";us=\*$", ";us=-", pre["B2"]), post["B2"], f"{L}: B2 after the reboot equals the SAVE's (modulo us)")
        ex.eq(d.model_class()[:2], ("VALID", "-"), f"{L}: oracle class after the reboot")
        names = [h[1] for h in hist]
        ex.eq(names, ["FBW", "FBP"] * (len(names) // 2), f"{L}: history of direct NVS sets across boots: witness-first pairs only")
        ex.eq(names[-2:], ["FBW", "FBP"], f"{L}: the last pair is this SAVE's")
        ex.eq(d.g["fallback_profile_seen_hw_gen"], gen, f"{L}: seen_hw_gen after the reboot")


def dispatch_idle_wait_start(d):
    """Park a SAVE in its dispatch: execute without running to idle (a deferred bus)."""
    return d.execute("SAVE", d.b4, f"SAVE {d.b4}", idle=False)


# ---------------------------------------------------------------------------
# generic probes
# ---------------------------------------------------------------------------
def fbs_slot_value(name: str) -> int:
    return {"unreadable": 0, "clear_absent": 1, "clear_valid": 2, "episode": 3, "corrupt": 4}[name]


def all_driver_violations(d) -> list:
    """Safety evidence over EVERY boot of a driver: no Modbus write ever; no direct set to a key that is not FBP / FBW; FBS never set."""
    errs = []
    if d.modbus_writes():
        errs.append(f"Modbus writes: {d.modbus_writes()}")
    for boot, name, _b, _r in d.nvs_set_history():
        if name not in ("FBP", "FBW"):
            errs.append(f"boot {boot}: set of {name}")
    return errs
