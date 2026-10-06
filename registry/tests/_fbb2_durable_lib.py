"""FB-B2 durable power-cut / NVS-fault / anti-rollback matrix - support library of test_fallback_save_durable.py.

Everything here drives the REAL firmware YAML (SAVE gate, dispatch, SAVE_FINAL parts 1+2, INVALIDATE, boot load) through the
FB-B2 scenario driver (_fbb2_drive.Driver -> _fbb_harness.FbbSim, the strict transpiler harness). Nothing here edits a
firmware / header / mirror file, and it owns no state outside this process.

THE TWO INDEPENDENT ORACLES every row is judged by (neither is "what the YAML printed"):
  1. the FB-B0 durable model, imported as a SEPARATE module object (`fdo`, a fresh exec of registry/fallback_durable.py), so
     that the in-process mutants (which patch the shared `fallback_durable` module the harness uses) can never touch it.
     It re-derives, from the raw NVS bytes alone: the composed class (compose_profile_class), the generation formula
     (save_generation_base), the intended FBP / FBW pair, the writer's outcome over a CLONE of the NVS with the same fault
     queue (commit_transition), and the next-boot state (DirectNvs.reboot + read_pair);
  2. the locked documents, typed in here as plain tables (master architecture 4.3 per-key outcome table, 4.7 / 4.8 texts,
     section 5 power-cut tables, S2 final 6.1 K0-K6 stage model, header contract section 5 texts): `doc_readback`,
     `doc_key_outcome`, `doc_txn`, `doc_b9`, `PRIORS[...].stages`.

A row is a function returning a `Rep` (asserts evaluated + failure messages). A family is a list of rows (an `Acc`).
`ROWS` maps a stable row NAME to a zero-argument callable, so a mutant can be "killed by the named row".

The mutation environment (`mutated(...)`): a YAML text mutant, a mutated copy of registry/fallback_save.py or
registry/fallback_capture.py injected through the driver, and attribute patches of the shared fallback_durable model. Every
`make_driver` honours the active environment; the oracles never do.
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REG))
import _fbb2_drive as D  # noqa: E402
import _fbb_harness as H  # noqa: E402
import fallback_capture as fc  # noqa: E402,F401
import fallback_durable as fd  # noqa: E402  (the SHARED module: the mutants patch it)
import fallback_profile as fp  # noqa: E402


def _isolated(modname: str, path: Path):
    spec = importlib.util.spec_from_file_location(modname, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


fdo = _isolated("fbb2_durable_oracle_fd", REG / "fallback_durable.py")   # the independent FB-B0 oracle (never patched)

# ---------------------------------------------------------------------------
# names, keys, small records
# ---------------------------------------------------------------------------
K_P, K_W, K_S = fdo.FALLBACK_PROFILE_KEY, fdo.FAILBACK_PROVISION_KEY, fdo.FAILBACK_STATE_KEY
KEY = {"P": K_P, "W": K_W}
NAME = {"P": "FBP", "W": "FBW"}
SZ = {"P": fp.PROFILE_SIZE, "W": fdo.PROVISION_SIZE}
OP_SAVE, OP_INV, OP_RC = fdo.PROV_OP_SAVE, fdo.PROV_OP_INVALIDATE, fdo.PROV_OP_REPLACE_CORRUPT
B2_OP = {0: "-", OP_SAVE: "SAVE", OP_INV: "INV", OP_RC: "RC"}
CLS_NAME = dict(D.CLASS)
CLS_NUM = {v: k for k, v in CLS_NAME.items()}
WHY_NAME = dict(fdo.WHY_NAMES)
U32 = 0xFFFFFFFF
FB_DEC = {fd.decimal_key(K_P): "FBP", fd.decimal_key(K_W): "FBW"}

G7 = D.GOLD                      # the golden stored profile (generation 7)
B7 = G7["binding"]
HEX = lambda v: f"{v:016X}"     # noqa: E731


def prof(g: int, **ov) -> dict:
    """The profile the golden register words save as at generation g (flags 0, captured_epoch = the NTP epoch of the Driver)."""
    return D.gold_profile(generation=g, **ov)


def wit(hw, hwb, pg, pbind=0x6666, op=OP_SAVE, tag=K_P, schema=1) -> bytes:
    """A sealed FBW record (prior_binding forced to 0 when prior_generation is 0)."""
    return fdo.pack_provision(fdo.make_provision(hw, hwb, pg, pbind if pg else 0, tag, schema, op))


def pb(p) -> bytes:
    return fp.pack_profile(p)


INV8 = fp.invalidate_profile(G7)
DOM7 = D.gold_profile(reg244=7)  # CORRUPT_DOMAIN, authentic, generation 7


# ---------------------------------------------------------------------------
# row bookkeeping
# ---------------------------------------------------------------------------
class Rep:
    """The outcome of one row: how many assertions it evaluated and which failed."""

    def __init__(self, label: str = ""):
        self.label = label
        self.asserts = 0
        self.fails: list[str] = []

    def ok(self, cond, msg: str = "") -> bool:
        self.asserts += 1
        if not cond:
            self.fails.append(f"[{self.label}] {msg}")
        return bool(cond)

    def eq(self, got, want, msg: str = "") -> bool:
        self.asserts += 1
        if got != want:
            self.fails.append(f"[{self.label}] {msg}: got {got!r} want {want!r}")
            return False
        return True


@dataclass
class Acc:
    """A family of rows."""

    name: str
    rows: int = 0
    asserts: int = 0
    fails: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def add(self, rep: Rep) -> None:
        self.rows += 1
        self.asserts += rep.asserts
        self.fails.extend(rep.fails)

    def merge(self, other: "Acc") -> None:
        self.rows += other.rows
        self.asserts += other.asserts
        self.fails.extend(other.fails)
        for k, v in other.extra.items():
            self.extra[k] = self.extra.get(k, 0) + v if isinstance(v, int) else v


ROWS: dict = {}          # stable name -> zero-arg callable -> Rep


def register(name: str, fn) -> None:
    if name in ROWS:
        raise KeyError(f"duplicate row name {name}")
    ROWS[name] = fn


# every FB set key seen over every row of the process (aggregate evidence: only FBW / FBP, never FBS, never a third key)
KEYS_SEEN: set = set()
SET_ORDERS: dict = {}


def note_sets(sets) -> None:
    """sets: [(decimal-key-string-or-int, bytes, result)] of one transaction."""
    for k, _d, _r in sets:
        KEYS_SEEN.add(int(k) if not isinstance(k, int) else k)


# ---------------------------------------------------------------------------
# the mutation environment (honoured by make_driver; the oracles never see it)
# ---------------------------------------------------------------------------
_ENV: dict = {"text": None, "fbsave": None, "fbcap": None}


def mirror_module(filename: str, edits: list, modname: str):
    """A mutated copy of registry/<filename> as a module object (exact-count anchors)."""
    src = (REG / filename).read_text(encoding="utf-8")
    for old, new, count in edits:
        n = src.count(old)
        if n != count:
            raise D.DriverError(f"mirror mutation anchor occurs {n} times, want {count}: {old[:70]!r}")
        src = src.replace(old, new)
    mod = types.ModuleType(modname)
    mod.__file__ = str(REG / filename)
    sys.modules[modname] = mod
    exec(compile(src, str(REG / filename), "exec"), mod.__dict__)
    return mod


@contextlib.contextmanager
def mutated(*, yaml_edits=None, save_edits=None, cap_edits=None, patches=None, tag="m"):
    """Activate a mutant: yaml_edits [(old, new, count)] on the firmware text; save_edits / cap_edits on the two mirrors;
    patches {name: callable} replacing attributes of the shared fallback_durable module. Restores everything on exit."""
    saved_env = dict(_ENV)
    saved_attrs = {}
    try:
        if yaml_edits:
            txt = D.FW_PATH.read_text(encoding="utf-8")
            for old, new, count in yaml_edits:
                txt = D.mutate(txt, old, new, count)
            _ENV["text"] = txt
        if save_edits:
            _ENV["fbsave"] = mirror_module("fallback_save.py", save_edits, f"fallback_save__{tag}")
        if cap_edits:
            _ENV["fbcap"] = mirror_module("fallback_capture.py", cap_edits, f"fallback_capture__{tag}")
        for name, fn in (patches or {}).items():
            saved_attrs[name] = getattr(fd, name)
            setattr(fd, name, fn)
        yield
    finally:
        for name, fn in saved_attrs.items():
            setattr(fd, name, fn)
        _ENV.update(saved_env)
        for k in ("fallback_save__" + tag, "fallback_capture__" + tag):
            sys.modules.pop(k, None)


def make_driver(seed="valid", *, review=True, expect="CANDIDATE_READY", **kw) -> D.Driver:
    """A Driver on the live firmware (or the active mutant), booted from the seed; with review=True the Review is pressed and
    a saveable candidate is required."""
    args = dict(kw)
    if _ENV["text"] is not None:
        args["text"] = _ENV["text"]
    if _ENV["fbsave"] is not None:
        args["fbsave"] = _ENV["fbsave"]
    if _ENV["fbcap"] is not None:
        args["fbcap"] = _ENV["fbcap"]
    d = D.Driver(seed=seed, **args)
    if review:
        d.review(expect=expect)
    return d


# ---------------------------------------------------------------------------
# the oracle view of the two durable keys
# ---------------------------------------------------------------------------
def peek(nvs, key: int, size: int):
    """(load, bytes, stored_len) of a key as the FB-B0 reader would classify it, without reading (no CRC side effect)."""
    b = nvs.blobs.get(key)
    if b is None:
        return fp.LOAD_ABSENT, bytes(size), 0
    if not b.crc_ok or not b.chunk_present:
        return fp.LOAD_READ_ERROR, bytes(size), len(b.data)
    if len(b.data) != size:
        return fp.LOAD_WRONG_SIZE, bytes(size), len(b.data)
    return fp.LOAD_OK, bytes(b.data), len(b.data)


@dataclass
class Flash:
    """What the two durable keys hold, classified by the independent FB-B0 oracle."""

    p_load: int
    p_bytes: bytes
    p_len: int
    w_load: int
    w_bytes: bytes
    w_len: int

    @classmethod
    def of(cls, nvs) -> "Flash":
        pl, pbs, plen = peek(nvs, K_P, SZ["P"])
        wl, wbs, wlen = peek(nvs, K_W, SZ["W"])
        return cls(pl, pbs, plen, wl, wbs, wlen)

    # -- classification
    def compose(self, anomaly: int = 0):
        return fdo.compose_profile_class(self.p_load, self.p_bytes, self.w_load, self.w_bytes, anomaly)

    @property
    def p(self) -> dict:
        return fp.unpack_profile(self.p_bytes)

    @property
    def w(self) -> dict:
        return fdo.unpack_provision(self.w_bytes)

    @property
    def pc(self) -> int:                    # FB-A class of the profile record
        return fp.classify_profile(self.p_load, self.p)

    @property
    def wc(self) -> int:                    # witness class
        return fdo.classify_witness(self.w_load, self.w_bytes)

    @property
    def authentic(self) -> bool:
        return fdo.fba_authentic(self.pc)

    @property
    def g(self) -> int:
        return self.p["generation"] if self.p_load == fp.LOAD_OK else 0

    @property
    def b(self) -> int:
        return self.p["binding"] if self.p_load == fp.LOAD_OK else 0

    @property
    def hw(self) -> int:                    # the witness high-water if it is VALID, else 0
        return self.w["hw_generation"] if self.wc == fdo.W_VALID else 0

    @property
    def cls_why(self):
        c, w, _r = self.compose()
        return CLS_NAME[c], WHY_NAME[w]

    def prior_fingerprint(self):
        """(generation, binding) the candidate binds for this prior (authentic: (g, b); CORRUPT: raw fields / (0, len); else 0,0)."""
        if self.authentic:
            return self.g, self.b
        if self.pc == fp.PROFILE_CORRUPT and self.p_load == fp.LOAD_OK:
            return self.g, self.b
        if self.pc == fp.PROFILE_CORRUPT and self.p_load == fp.LOAD_WRONG_SIZE:
            return 0, self.p_len
        return 0, 0


def boot_flash(nvs, **kw) -> Flash:
    """The oracle's resolution of the NEXT boot: DirectNvs.reboot() (each written key per its fault, indexes with a missing
    chunk dropped) classified by the independent model."""
    return Flash.of(nvs.reboot(**kw))


def seen_at_boot(fl: Flash) -> int:
    """seen_hw_gen after a boot read: max of the authentic FBP generation and a VALID witness' high-water."""
    return fdo.next_seen_hw_gen(0, fl.pc, fl.g, fl.wc, fl.hw)


def formula_gen(fl: Flash, seen: int):
    """Master 3.9 / 4.7: gen = max(authentic g, valid hw, seen) + 1; None when the counter is exhausted (base 0xFFFFFFFF)."""
    base = fdo.save_generation_base(fl.pc, fl.g, fl.wc, fl.hw, seen)
    return None if not fdo.save_generation_available(base) else base + 1


def intended_pair(fl: Flash, gen: int, replace: bool):
    """The record pair a clean SAVE of the golden register words must write over this prior (locked table, FB_B2_IMPLEMENTATION_NOTES.md section 6)."""
    p_new = prof(gen)
    auth = fl.authentic
    w_new = fdo.make_provision(gen, p_new["binding"], fl.g if auth else 0, fl.b if auth else 0, K_P, fp.PROFILE_SCHEMA,
                               OP_RC if replace else OP_SAVE)
    return p_new, w_new


def clone_nvs(nv) -> "H.DirectNvs":
    n = H.DirectNvs(handle=nv.handle_value)
    n.blobs = {k: b.copy() for k, b in nv.blobs.items()}
    n.healthy, n.unavailable = nv.healthy, nv.unavailable
    n.faults = {k: [copy.copy(f) for f in v] for k, v in nv.faults.items()}
    n.read_faults = {k: list(v) for k, v in nv.read_faults.items()}
    n.clock_us = nv.clock_us
    return n


def image(nv) -> dict:
    return {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in nv.blobs.items()}


@dataclass
class Oracle:
    outcome: int
    result: "fdo.TxnResult"
    latched: bool
    nvs: "H.DirectNvs"
    flash0: Flash


def oracle_commit(onvs, p_new: dict, w_new: dict) -> Oracle:
    """What SAVE_FINAL part 2 does to the storage, re-derived with the isolated FB-B0 model: the fresh two-key read + health
    probe, then the ONE writer call over a clone of the NVS that carries the same fault queue."""
    pl, pbs, dp = fdo.read_direct(onvs, K_P, SZ["P"])
    wl, wbs, dw = fdo.read_direct(onvs, K_W, SZ["W"])
    fdo.storage_healthy(onvs)
    latch = fdo.WriteLatch()
    o, r = fdo.commit_transition(onvs, latch, fdo.pack_provision(w_new), wbs, (wl, dw.stored_len), fp.pack_profile(p_new), pbs,
                                 (pl, dp.stored_len))
    return Oracle(o, r, latch.write_latched, onvs, Flash(pl, pbs, dp.stored_len, wl, wbs, dw.stored_len))


# ---------------------------------------------------------------------------
# the locked documents as tables
# ---------------------------------------------------------------------------
PRE_WRITE = (fdo.IDF_ERR_NVS_INVALID_HANDLE, fdo.IDF_ERR_NVS_READ_ONLY, fdo.IDF_ERR_NVS_NOT_INITIALIZED)   # master 4.3
RB_INTENDED, RB_PRIOR, RB_OTHER, RB_ABSENT, RB_WSIZE, RB_RERR, RB_UNAV = 1, 2, 3, 4, 5, 6, 7
RB_NAMES = {1: "INTENDED", 2: "PRIOR", 3: "OTHER_BYTES", 4: "ABSENT_UNEXPECTED", 5: "WRONG_SIZE", 6: "READ_ERROR", 7: "UNAVAILABLE"}


def e_txt(err: int) -> str:
    """<err> as the texts render it (J13): E<hex> of the 32-bit code, '-' for none."""
    err &= U32
    return "-" if err == 0 else "E%X" % err


def doc_readback(visible: str, prior_kind: str, wrong_len: int = 0, other_is_prior: bool = False) -> int:
    """The readback class a key shows right after a set whose post-state is `visible` (S2 final 1.x / master 4.3 vocabulary).
    prior_kind: 'ABSENT' | 'BYTES' | 'WS<n>' (a stored blob of n bytes that is not the record size)."""
    absent = prior_kind == "ABSENT"
    if visible == H.VIS_NEW:
        return RB_INTENDED
    if visible == H.VIS_OLD:
        return RB_PRIOR
    if visible == H.VIS_ABSENT:
        return RB_PRIOR if absent else RB_ABSENT
    if visible == H.VIS_CRCBAD:
        return RB_RERR
    if visible == H.VIS_NOCHUNK_OLD:
        return RB_PRIOR if absent else RB_RERR
    if visible == H.VIS_OTHER:
        return RB_PRIOR if (other_is_prior and prior_kind == "BYTES") else RB_OTHER
    if visible == H.VIS_WRONGSIZE:
        return RB_PRIOR if prior_kind == f"WS{wrong_len}" else RB_WSIZE
    if visible == H.VIS_UNAVAILABLE:
        return RB_UNAV
    raise KeyError(visible)


def doc_key_outcome(err: int, rb: int, healthy_after: bool) -> str:
    """Master 4.3, the per-key outcome table, typed in from the document."""
    if not healthy_after:
        return "UNKNOWN"          # "... or !nvs_healthy()"
    if err == fdo.IDF_OK and rb == RB_INTENDED:
        return "COMMITTED"
    if err in PRE_WRITE and rb == RB_PRIOR:
        return "NOT_COMMITTED"
    return "UNKNOWN"


@dataclass
class Cell:
    """One injected write fault on one key: the code set_blob returns, what a readback sees, what the next boot resolves to."""

    key: str                                 # 'W' | 'P'
    code: int = fdo.IDF_OK
    vis: str = H.VIS_NEW
    boot: str = H.BOOT_ASIS
    healthy: bool = True
    other: bytes = b""
    wrong_len: int = 0

    def kwargs(self) -> dict:
        n = SZ[self.key]
        other = self.other if self.other else (bytes([0xA5]) * n if self.vis == H.VIS_OTHER else b"")
        wl = self.wrong_len if self.wrong_len else (n + 4 if self.vis == H.VIS_WRONGSIZE else 0)
        return dict(result=self.code, visible=self.vis, boot=self.boot, healthy_after=self.healthy, other=other, wrong_len=wl)

    def fault(self):
        return H.WriteFault(**self.kwargs())

    @property
    def label(self) -> str:
        return f"{self.key}:{self.code & U32:x}:{self.vis}:{self.boot}:{int(self.healthy)}"


@dataclass
class DocKey:
    err: int
    rb: int
    out: str


@dataclass
class DocTxn:
    w: DocKey
    p: DocKey | None        # None: the profile write was never attempted
    txn: str                # COMMITTED | NOT_COMMITTED | UNKNOWN
    adv: bool               # witness advanced (FBW committed, FBP not committed)
    nsets: int


def prior_kind(load: int, length: int) -> str:
    if load == fp.LOAD_ABSENT:
        return "ABSENT"
    if load == fp.LOAD_WRONG_SIZE:
        return f"WS{length}"
    return "BYTES"


def doc_txn(fl: Flash, wcell: Cell | None, pcell: Cell | None) -> DocTxn:
    """The transaction outcome the DOCUMENT prescribes (master 4.2 / 4.3 composition) for these two injected cells."""
    wc = wcell or Cell("W")
    pc = pcell or Cell("P")
    w_rb = doc_readback(wc.vis, prior_kind(fl.w_load, fl.w_len), wc.kwargs()["wrong_len"], wc.kwargs()["other"] == fl.w_bytes)
    w = DocKey(wc.code, w_rb, doc_key_outcome(wc.code, w_rb, wc.healthy))
    if w.out == "NOT_COMMITTED":
        return DocTxn(w, None, "NOT_COMMITTED", False, 1)
    if w.out == "UNKNOWN":
        return DocTxn(w, None, "UNKNOWN", False, 1)
    p_rb = doc_readback(pc.vis, prior_kind(fl.p_load, fl.p_len), pc.kwargs()["wrong_len"], pc.kwargs()["other"] == fl.p_bytes)
    p = DocKey(pc.code, p_rb, doc_key_outcome(pc.code, p_rb, pc.healthy))
    if p.out == "COMMITTED":
        return DocTxn(w, p, "COMMITTED", False, 2)
    if p.out == "NOT_COMMITTED":
        return DocTxn(w, p, "NOT_COMMITTED", True, 2)
    return DocTxn(w, p, "UNKNOWN", False, 2)


def doc_b9(dt: DocTxn, gen: int) -> str:
    """The SAVE outcome texts: master 4.7 (normative) with the contract section 5 `<err>/<readback>` detail on UNKNOWN."""
    if dt.txn == "COMMITTED":
        return f"SAVED - known-good profile generation {gen} saved (verified this boot)"
    if dt.txn == "NOT_COMMITTED":
        if dt.adv:
            return ("SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and "
                    "save again")
        return f"SAVE NOT COMMITTED - storage refused the write ({e_txt(dt.w.err)}); nothing changed"
    k = dt.w if dt.w.out == "UNKNOWN" else dt.p
    return (f"SAVE OUTCOME UNKNOWN - storage reported {e_txt(k.err)}/{RB_NAMES[k.rb]}; reboot the dongle (when no temporary "
            "operation is active) to re-verify; saving disabled until then")


def doc_werr(dt: DocTxn) -> int:
    """B2 werr: the first non-OK esp_err of (FBW, FBP) of the transaction."""
    if dt.w.err != 0:
        return dt.w.err & U32
    return (dt.p.err & U32) if dt.p is not None else 0


def parse_b2(s: str) -> dict:
    return dict(kv.split("=", 1) for kv in s.split(";"))


def b2_expect(fl: Flash) -> dict:
    """B2 g / hw / op / w as the document derives them from the two stored records."""
    out = {}
    out["g"] = str(fl.g) if fl.authentic else "-"
    out["hw"] = str(fl.w["hw_generation"]) if fl.wc == fdo.W_VALID else "-"
    out["op"] = B2_OP.get(fl.w["last_op"], "-") if fl.wc == fdo.W_VALID else "-"
    return out


# ---------------------------------------------------------------------------
# the priors: every state SAVE can start from, with the LOCKED TABLE (master 5.1-5.4, S2 final 6.2-6.5) typed in
# ---------------------------------------------------------------------------
@dataclass
class Prior:
    name: str
    seed: object                    # a D.Driver seed
    boot: tuple                     # (class, why) the boot must show
    save_gen: int                   # the generation of a clean SAVE (formula, as a constant)
    w_op: int                       # witness last_op of that SAVE
    w_prior: tuple                  # witness (prior_generation, prior_binding) of that SAVE
    before: tuple                   # next-boot class if the power fails before the FBW index is written
    w_only: tuple                   # ... after the FBW index is written, FBP not
    follow_w_only: int              # the generation the next clean SAVE gets from the w_only boot
    rc: bool = False                # REPLACE CORRUPT phrase needed
    note: str = ""


def _prior_table() -> dict:
    W = wit
    dom_w = W(7, DOM7["binding"], 6)
    t = [
        Prior("first", {}, ("NOT_CAPTURED", "-"), 1, OP_SAVE, (0, 0), ("NOT_CAPTURED", "-"), ("PROFILE_LOST", "FIRST"), 2,
              note="master 5.2 first capture"),
        Prior("valid", "valid", ("VALID", "-"), 8, OP_SAVE, (7, B7), ("VALID", "-"), ("PROFILE_STALE", "INT"), 9,
              note="master 5.1 recapture over VALID g7 (hw 7)"),
        Prior("invalidated", "invalidated", ("INVALIDATED", "-"), 9, OP_SAVE, (8, INV8["binding"]), ("INVALIDATED", "-"),
              ("PROFILE_STALE", "INT"), 10),
        Prior("cdom_w", {"fbp": DOM7, "fbw": dom_w}, ("CORRUPT_DOMAIN", "-"), 8, OP_SAVE, (7, DOM7["binding"]),
              ("CORRUPT_DOMAIN", "-"), ("PROFILE_STALE", "INT"), 9),
        Prior("cdom_nw", "corrupt_domain", ("CORRUPT_DOMAIN", "MISS"), 8, OP_SAVE, (7, DOM7["binding"]),
              ("CORRUPT_DOMAIN", "MISS"), ("PROFILE_STALE", "INT"), 9),
        Prior("lost", "lost", ("PROFILE_LOST", "-"), 8, OP_SAVE, (0, 0), ("PROFILE_LOST", "-"), ("PROFILE_LOST", "-"), 9,
              note="master 5.2 after loss (hw = 7)"),
        Prior("lost_first", {"fbw": W(1, 0x1111, 0)}, ("PROFILE_LOST", "FIRST"), 2, OP_SAVE, (0, 0), ("PROFILE_LOST", "FIRST"),
              ("PROFILE_LOST", "-"), 3, note="first save unconfirmed (B5): hw 1, prior 0, op SAVE"),
        Prior("lost_wc", {"fbw": bytes(range(48))}, ("PROFILE_LOST", "LWC"), 1, OP_SAVE, (0, 0), ("PROFILE_LOST", "LWC"),
              ("PROFILE_LOST", "FIRST"), 2, note="loss with a corrupt witness (B7): baseline unknown, gen 1"),
        Prior("stale_rbk", "stale", ("PROFILE_STALE", "RBK"), 8, OP_SAVE, (5, prof(5)["binding"]), ("PROFILE_STALE", "RBK"),
              ("PROFILE_STALE", "INT"), 9, note="FBP g5 under a witness hw 7: ROLLBACK (B13)"),
        Prior("stale_int", {"fbp": G7, "fbw": W(8, 0x8888, 7, B7)}, ("PROFILE_STALE", "INT"), 9, OP_SAVE, (7, B7),
              ("PROFILE_STALE", "INT"), ("PROFILE_STALE", "INT"), 10, note="an interrupted earlier save (B12)"),
        Prior("stale_mis", {"fbp": G7, "fbw": W(7, 0x7777, 6)}, ("PROFILE_STALE", "MIS"), 8, OP_SAVE, (7, B7),
              ("PROFILE_STALE", "MIS"), ("PROFILE_STALE", "INT"), 9, note="g == hw, binding differs (B11)"),
        Prior("stale_sup", {"fbp": G7, "fbw": W(7, B7, 6, tag=0x12345678)}, ("PROFILE_STALE", "SUP"), 8, OP_SAVE, (7, B7),
              ("PROFILE_STALE", "SUP"), ("PROFILE_STALE", "INT"), 9, note="foreign hw tag (B9)"),
        Prior("lag", "lag", ("VALID", "LAG"), 8, OP_SAVE, (7, B7), ("VALID", "LAG"), ("PROFILE_STALE", "INT"), 9,
              note="witness lagging (B8): SAVE repairs it"),
        Prior("wmiss", {"fbp": G7}, ("VALID", "MISS"), 8, OP_SAVE, (7, B7), ("VALID", "MISS"), ("PROFILE_STALE", "INT"), 9,
              note="witness missing (B14)"),
        Prior("wcorr", "witness_corrupt", ("VALID", "CORR"), 8, OP_SAVE, (7, B7), ("VALID", "CORR"), ("PROFILE_STALE", "INT"), 9,
              note="witness corrupt (B15)"),
        Prior("corrupt", {"fbp": bytes(range(96)), "fbw": W(9, 0x9999, 8)}, ("CORRUPT", "-"), 10, OP_RC, (0, 0),
              ("CORRUPT", "-"), ("CORRUPT", "-"), 11, rc=True, note="master 5.4 REPLACE CORRUPT with hw 9 (golden: g10)"),
        Prior("wsize", {"fbp": bytes(40), "fbw": W(9, 0x9999, 8)}, ("CORRUPT", "-"), 10, OP_RC, (0, 0), ("CORRUPT", "-"),
              ("CORRUPT", "-"), 11, rc=True, note="WRONG_SIZE FBP"),
        Prior("corrupt_nw", {"fbp": bytes(range(96))}, ("CORRUPT", "-"), 1, OP_RC, (0, 0), ("CORRUPT", "-"), ("CORRUPT", "-"), 2,
              rc=True, note="CORRUPT with no witness: baseline unknown, gen 1"),
    ]
    return {p.name: p for p in t}


PRIORS = _prior_table()
STAGE_LABELS = {"before": "before the FBW index is written", "w_only": "FBW indexed, FBP not", "both": "FBP indexed"}

# S2 final 6.1: the per-key stage model. K0-K3 resolve to OLD at the next init, K4-K6 to NEW.
K_STAGES = [("K0", "before nvs_set_blob", "old"), ("K1", "new chunk partially programmed", "old"),
            ("K2", "new chunk complete, index not programmed", "old"), ("K3", "new index programmed, state not WRITTEN", "old"),
            ("K4", "new index WRITTEN, old index still WRITTEN", "new"), ("K5", "old index erased, old chunk not yet", "new"),
            ("K6", "all done, before return", "new")]


# ---------------------------------------------------------------------------
# generic observations
# ---------------------------------------------------------------------------
def boot_invariants(d: D.Driver, rep: Rep) -> None:
    """Right after a boot: nothing held, nothing latched, nothing written, nothing armed (everything RAM was lost)."""
    errs = D.idle_invariants(d)
    rep.ok(not errs, f"idle invariants at boot: {errs}")
    g = d.g
    rep.ok(not g["fallback_profile_save_unconfirmed"] and not d.write_latched, "SAVE_UNCONFIRMED / write latch survived a reboot")
    rep.ok(not g["fallback_profile_save_ctx_valid"] and not g["fallback_profile_save_verified"], "a SAVE context survived a reboot")
    rep.ok(not g["fallback_profile_cand_valid"] and not d.arm_state, "a candidate or the arm survived a reboot")
    rep.eq(d.sim.nvs_direct.sets, [], "the boot wrote to NVS")
    rep.ok(not d.modbus_writes(), "a Modbus write at boot")
    rep.ok(g["fallback_profile_boot_loaded"] is True, "boot load did not complete")


def check_booted(d: D.Driver, rep: Rep, fl: Flash, *, table: tuple | None = None, what: str = "boot") -> None:
    """The booted class equals the independent oracle over the flash the boot read AND (when given) the locked table."""
    cls, why = fl.cls_why
    rep.eq((d.b1, parse_b2(d.b2)["why"]), (cls, why if why != "-" else "-"), f"{what}: class vs the FB-B0 oracle")
    if table is not None:
        rep.eq((cls, why), table, f"{what}: oracle vs the locked table")
        rep.eq((d.b1, parse_b2(d.b2)["why"]), table, f"{what}: B1/why vs the locked table")
    want = b2_expect(fl)
    got = parse_b2(d.b2)
    for k in ("g", "hw", "op"):
        rep.eq(got[k], want[k], f"{what}: B2 {k}")
    rep.eq(CLS_NAME[d.g["fallback_profile_class"]], cls, f"{what}: fallback_profile_class numeric")


def follow_up_save(d: D.Driver, rep: Rep, fl: Flash, *, seen: int | None = None, expect_gen: int | None = None,
                   what: str = "follow-up", reboot: bool = True) -> Flash | None:
    """From the booted state press Review, arm and SAVE (with the REPLACE CORRUPT phrase when the class is CORRUPT): the operator
    action of the locked tables must be possible, must commit exactly FBW then FBP of the intended pair and must get the generation
    the formula gives (and `expect_gen` when the table states one). Returns the flash after it."""
    cls, _why = fl.cls_why
    rc = cls == "CORRUPT"
    seen = seen_at_boot(fl) if seen is None else seen
    gen = formula_gen(fl, seen)
    if expect_gen is not None:
        rep.eq(gen, expect_gen, f"{what}: formula vs the locked table generation")
    d.review()
    if not rep.ok(d.b3.startswith("st=CANDIDATE_READY"), f"{what}: no saveable candidate from the {cls} boot: {d.b3} / {d.b9}"):
        return None
    m = d.mark()
    st = d.save(replace_corrupt=rc)
    p_new, w_new = intended_pair(fl, gen, rc)
    rep.ok(st.since.violations_fb(("FBW", "FBP"), bytes_={"FBW": fdo.pack_provision(w_new), "FBP": fp.pack_profile(p_new)}) == [],
           f"{what}: write audit {st.since.violations_fb(('FBW', 'FBP'))}")
    rep.eq(d.b9, f"SAVED - known-good profile generation {gen} saved (verified this boot)", f"{what}: B9")
    fl2 = Flash.of(d.sim.nvs_direct)
    rep.eq((fl2.cls_why, fl2.g, fl2.hw), (("VALID", "-"), gen, gen), f"{what}: flash after the save")
    note_sets(st.since.nvs_set_log)
    if reboot:
        d.reboot()
        boot_invariants(d, rep)
        check_booted(d, rep, fl2, table=("VALID", "-"), what=f"{what}: reboot")
    return fl2


# ---------------------------------------------------------------------------
# the UNKNOWN battery: nothing afterwards turns an UNKNOWN outcome into ABSENT / CLEAR / VALID in the same boot
# ---------------------------------------------------------------------------
NVS_READ_OPS = ("get", "read", "stats")
INV_UNKNOWN_TEXT = "INVALIDATE REFUSED - previous Fallback Profile write outcome unknown this boot - reboot to re-verify first"
SAVE_UNKNOWN_TEXT = "SAVE REFUSED - previous save outcome unknown this boot - reboot to re-verify first"
REVIEW_UNKNOWN_TEXT = "CANDIDATE NOT SAVEABLE - previous save outcome unknown; reboot to re-verify"


class CutStep:
    """What d.save(catch_cut=True) would return, also when the power fails inside the arm switch (outside the driver's step())."""

    def __init__(self, d, m, cut):
        self.since = d.since(m)
        self.cut = cut


def save_cut(d: D.Driver, replace_corrupt: bool = False):
    """d.save() that survives a PowerCut raised anywhere (the switch events included): returns a Step-like with .cut and .since."""
    m = d.mark()
    try:
        st = d.save(replace_corrupt=replace_corrupt, catch_cut=True)
        return st
    except D.PowerCut as e:
        return CutStep(d, m, e)


def forge_candidate(d: D.Driver, cand: dict) -> None:
    """Put a SAVEABLE candidate back in the RAM globals (the world manipulation a test may do; the firmware consumed the real one)."""
    for k, v in cand.items():
        d.set_g("fallback_profile_cand_" + k, list(v) if isinstance(v, list) else v)
    d.set_g("fallback_profile_cand_ms", d.sim.now_ms & U32)
    d.set_g("fallback_profile_cand_valid", True)
    d.set_g("fallback_profile_cand_saveable", True)


def unknown_battery(d: D.Driver, rep: Rep, *, cand: dict, quick: bool = True) -> None:
    """After an UNKNOWN outcome: SAVE_UNCONFIRMED is set and the write latch is set, and for the rest of the boot
    - housekeeping ticks, refused SAVE / INVALIDATE calls, repeated Review presses and 'retry' presses write NOTHING (zero sets);
    - the ticks and the refused calls do not touch NVS at all;
    - B1 stays SAVE_UNCONFIRMED (a Review that re-reads a flash which now holds VALID / ABSENT / anything does not change it);
    - Review shows CANDIDATE NOT SAVEABLE; a forged saveable candidate is refused at the gate (G9, zero Modbus reads) and, with the RAM
      overlay cleared by hand, by the writer's own latch (REFUSED_LATCHED, zero sets).
    Only a reboot re-derives (the caller reboots next)."""
    g = d.g

    def still(tag):
        rep.eq(d.b1, "SAVE_UNCONFIRMED", f"{tag}: B1")
        rep.ok(g["fallback_profile_save_unconfirmed"] is True and d.write_latched, f"{tag}: overlay / latch cleared")

    still("after the UNKNOWN outcome")
    m = d.mark()
    d.advance(35_000)                                               # three 10 s housekeeping ticks
    s = d.since(m)
    rep.eq(len(s.nvs_ops), 0, "the housekeeping ticks touched NVS")
    rep.eq(s.nvs_set_log, [], "a housekeeping tick wrote NVS")
    still("after 35 s of housekeeping")
    # a bare retry: SAVE and INVALIDATE with the arm on (no candidate exists: the call consumed it)
    st = d.save(target_id="0" * 16, confirmation="SAVE " + "0" * 16)
    rep.ok(d.b9.startswith("SAVE REFUSED - "), f"a retry SAVE was not refused: {d.b9}")
    rep.eq(len(st.since.nvs_ops), 0, "a refused SAVE touched NVS")
    st = d.invalidate(target_id="1" * 16, confirmation="INVALIDATE " + "1" * 16)
    rep.eq(d.b9, INV_UNKNOWN_TEXT, "INVALIDATE after UNKNOWN")
    rep.eq(len(st.since.nvs_ops), 0, "a refused INVALIDATE touched NVS")
    still("after the refused retries")
    # repeated Review: it re-reads (read-only), may see ANY flash state, and must never turn the overlay into a class
    for i in range(1 if quick else 3):
        m = d.mark()
        d.review()
        s = d.since(m)
        rep.eq(s.nvs_set_log, [], f"Review #{i + 1} wrote NVS")
        rep.ok(all(o[0] in NVS_READ_OPS for o in s.nvs_ops), f"Review #{i + 1} issued an NVS operation other than a read: {s.nvs_ops}")
        if d.b3.startswith("st=CANDIDATE_NOT_SAVEABLE"):
            rep.ok("prior=SAVE_UNCONFIRMED" in d.b3, f"Review #{i + 1} after UNKNOWN: {d.b3}")
            rep.eq(d.b9, REVIEW_UNKNOWN_TEXT, f"Review #{i + 1} B9")
        else:   # the Review gate itself refused (e.g. the storage now reports NOT_INITIALIZED for the lease-marker probes)
            rep.ok(d.b3.startswith("st=IDLE") and d.b9.startswith("REVIEW REFUSED - "), f"Review #{i + 1} after UNKNOWN: {d.b3} / {d.b9}")
        rep.ok(d.b4 == "-" and not g["fallback_profile_cand_saveable"], f"Review #{i + 1}: a saveable candidate exists after UNKNOWN")
        still(f"after Review #{i + 1}")
    # the forged candidate: the gate (G9) refuses before anything is read or issued
    idh = HEX(cand["id"])
    phrase = "SAVE " + idh + (" REPLACE CORRUPT" if cand["prior_class"] == CLS_NUM["CORRUPT"] else "")
    forge_candidate(d, cand)
    reads0 = d.reads_seen
    st = d.save(target_id=idh, confirmation=phrase)
    rep.eq(d.b9, SAVE_UNKNOWN_TEXT, "forged candidate: G9 text")
    rep.eq(d.reads_seen - reads0, 0, "G9 let a Modbus read through")
    rep.eq(len(st.since.nvs_ops), 0, "G9 touched NVS")
    still("after the forged-candidate SAVE")
    if not quick:
        # defence in depth: the RAM overlay cleared by hand - the writer's own latch must still refuse (nothing written)
        d.set_g("fallback_profile_save_unconfirmed", False)
        forge_candidate(d, cand)
        st = d.save(target_id=idh, confirmation=phrase)
        rep.eq(st.since.nvs_set_log, [], "the writer latch let a second commit through")
        rep.ok(d.write_latched, "the write latch was cleared by a refused call")
        rep.eq(d.b9, SAVE_UNKNOWN_TEXT, "latch-only layer text")


# ---------------------------------------------------------------------------
# the transaction row (fault cells over a prior): outcome, texts, mirror, flash, boot, follow-ups
# ---------------------------------------------------------------------------
TXN_NAMES = {fdo.TXN_COMMITTED: "COMMITTED", fdo.TXN_NOT_COMMITTED: "NOT_COMMITTED", fdo.TXN_UNKNOWN_REBOOT: "UNKNOWN",
             fdo.TXN_REFUSED_LATCHED: "REFUSED"}


def resolve_cell(c, fl0: Flash):
    """A cell whose `other` is the sentinel b"PRIOR" reads back the PRIOR bytes of its key (stale bytes: duplicate poisoning)."""
    if c is not None and c.other == b"PRIOR":
        return Cell(c.key, c.code, c.vis, c.boot, c.healthy, fl0.w_bytes if c.key == "W" else fl0.p_bytes, c.wrong_len)
    return c


def txn_row(prior_name: str, wcell: Cell | None = None, pcell: Cell | None = None, *, label: str = "",
            expect_boot: tuple | None = None, battery: bool = True, same_boot: bool = False, quick_battery: bool = True,
            follow: bool = True) -> Rep:
    """One SAVE over `prior_name` with the given fault cells, judged by the doc tables, the isolated FB-B0 oracle and the booted
    state (see the module docstring).
      same_boot=False  the outcome is followed by a PLAIN REBOOT (`expect_boot` = the locked-table class of that boot), then the
                       operator action (Review + SAVE) from the booted state;
      same_boot=True   (non-UNKNOWN outcomes) the outcome is first followed by a same-boot Review + SAVE (the mirror must equal the
                       flash: no divergence anomaly), then a reboot; `expect_boot` is checked against the oracle's resolution of the
                       state right after the outcome."""
    pr = PRIORS[prior_name]
    rep = Rep(label or f"{prior_name}/{wcell.label if wcell else '-'}/{pcell.label if pcell else '-'}")
    d = make_driver(pr.seed)
    nv = d.sim.nvs_direct
    fl0 = Flash.of(nv)
    seen0 = seen_at_boot(fl0)
    rep.eq(fl0.cls_why, pr.boot, "prior state vs the locked table")
    rep.eq((d.b1, parse_b2(d.b2)["why"]), pr.boot, "booted class")
    gen = formula_gen(fl0, seen0)
    rep.eq(gen, pr.save_gen, "generation formula vs the locked table")
    p_new, w_new = intended_pair(fl0, gen, pr.rc)
    onvs = clone_nvs(nv)
    cand = d.candidate()
    wcell, pcell = (resolve_cell(c, fl0) for c in (wcell, pcell))
    for c in (wcell, pcell):
        if c is not None:
            d.fault_write(NAME[c.key], **c.kwargs())
            onvs.faults.setdefault(KEY[c.key], []).append(c.fault())
    dt = doc_txn(fl0, wcell, pcell)
    orc = oracle_commit(onvs, p_new, w_new)
    st = d.save(replace_corrupt=pr.rc)
    # --- the isolated FB-B0 oracle agrees with the master 4.3 table (the two oracles cross-check each other)
    rep.eq(TXN_NAMES[orc.outcome], dt.txn, "FB-B0 oracle vs the master 4.3 table")
    rep.eq(bool(orc.result.witness_advanced), dt.adv, "oracle witness_advanced vs the table")
    # --- writes: only FBW then FBP, exactly the oracle's bytes and results, nothing else, no retry
    sets = [(FB_DEC.get(fd.decimal_key(k), k), bytes(b), r) for k, b, r in st.since.nvs_set_log]
    osets = [(FB_DEC.get(fd.decimal_key(k), k), bytes(b), r) for k, b, r in orc.nvs.sets]
    note_sets(st.since.nvs_set_log)
    rep.eq(sets, osets, "the NVS sets (key, bytes, result) vs the oracle over the same fault queue")
    rep.eq([s[0] for s in sets], ["FBW", "FBP"][:dt.nsets], "set order / count (2 when the witness commits, else 1; never a retry)")
    rep.ok(st.since.violations_fb(tuple(s[0] for s in sets), bytes_={n: b for n, b, _r in sets}) == [], "write audit")
    rep.eq(st.since.writes, [], "Modbus writes")
    if sets:
        rep.eq(sets[0][1], fdo.pack_provision(w_new), "the first write is the intended FBW (locked table)")
    if len(sets) > 1:
        rep.eq(sets[1][1], fp.pack_profile(p_new), "the second write is the intended FBP")
    # --- texts and state per the document
    rep.eq(d.b9, doc_b9(dt, gen), "B9")
    unknown = dt.txn == "UNKNOWN"
    rep.eq(bool(d.g["fallback_profile_save_unconfirmed"]), unknown, "SAVE_UNCONFIRMED overlay")
    rep.eq(d.write_latched, unknown, "write latch")
    if unknown:
        rep.eq((d.g["fallback_profile_save_unconfirmed_op"], d.g["fallback_profile_save_unconfirmed_gen"]), (pr.w_op, gen),
               "unconfirmed op / generation")
    b2 = parse_b2(d.b2)
    rep.eq(b2["werr"], e_txt(doc_werr(dt)), "B2 werr")
    rep.eq(int(b2["us"]) if b2["us"] != "-" else 0, orc.result.w.us + orc.result.p.us, "B2 us (w.us + p.us) vs the oracle")
    if unknown:
        exp_b1 = "SAVE_UNCONFIRMED"
    elif dt.txn == "COMMITTED":
        exp_b1 = "VALID"
    elif dt.adv:   # the witness advanced under the unchanged profile: whatever the pair composes to (STALE over an authentic FBP)
        exp_b1 = CLS_NAME[fdo.compose_profile_class(fl0.p_load, fl0.p_bytes, fp.LOAD_OK, fdo.pack_provision(w_new), 0)[0]]
        if fl0.authentic:
            rep.eq(exp_b1, "PROFILE_STALE", "the oracle: FBW advanced over an authentic FBP is STALE (master 4.3)")
    else:
        exp_b1 = pr.boot[0]
    rep.eq(d.b1, exp_b1, "B1 after the outcome")
    # the RAM mirror comes from readbacks / the pre-transaction values only (PO5), never from the intended bytes
    mir_p, mir_w = bytes(d.arr("fallback_profile_bytes")), bytes(d.arr("fallback_witness_bytes"))
    if dt.txn == "COMMITTED":
        rep.eq((mir_p, mir_w), (fp.pack_profile(p_new), fdo.pack_provision(w_new)), "mirror after COMMITTED == the readbacks")
    elif unknown:
        rep.eq((mir_p, mir_w), (fl0.p_bytes, fl0.w_bytes), "mirror after UNKNOWN == the unchanged pre-transaction bytes (PO5)")
    elif dt.adv:
        rep.eq((mir_p, mir_w), (fl0.p_bytes, fdo.pack_provision(w_new)), "mirror after NOT_COMMITTED (witness advanced)")
    else:
        rep.eq((mir_p, mir_w), (fl0.p_bytes, fl0.w_bytes), "mirror after NOT_COMMITTED == the prior")
    seen_after = max(seen0, gen) if dt.txn == "COMMITTED" or dt.adv else seen0
    rep.eq(d.g["fallback_profile_seen_hw_gen"], seen_after, "seen_hw_gen after the outcome")
    rep.eq(D.idle_invariants(d), [], "idle invariants after the outcome")
    rep.eq(D.text_invariants(d), [], "text invariants")
    # --- the flash and the next boot, from the oracle and from the real boot
    rep.eq(image(nv), image(orc.nvs), "flash image after the transaction vs the oracle")
    ofl = boot_flash(orc.nvs)
    if expect_boot is not None:
        rep.eq(ofl.cls_why, expect_boot, "next-boot class: the FB-B0 oracle vs the locked table (master 5.5 / S2 6.6)")
    if same_boot and not unknown:
        flash_now = Flash.of(nv)
        gen2 = formula_gen(flash_now, seen_after)
        d.review()
        if rep.ok(d.b3.startswith("st=CANDIDATE_READY"), f"same-boot Review after the outcome: {d.b3} / {d.b9}"):
            stt = d.save(replace_corrupt=(flash_now.cls_why[0] == "CORRUPT"))
            rep.eq(d.b9, f"SAVED - known-good profile generation {gen2} saved (verified this boot)", "same-boot second SAVE")
            rep.eq(stt.since.violations_fb(("FBW", "FBP")), [], "same-boot second SAVE audit")
            note_sets(stt.since.nvs_set_log)
            rep.ok(not d.write_latched, "latch after a same-boot follow-up")
        ofl = boot_flash(nv)
        d.reboot()
        boot_invariants(d, rep)
        check_booted(d, rep, ofl, table=None, what="reboot after the same-boot follow-up")
        return rep
    if unknown and battery:
        unknown_battery(d, rep, cand=cand, quick=quick_battery)
        ofl = boot_flash(nv)
    d.reboot()
    boot_invariants(d, rep)
    check_booted(d, rep, ofl, table=expect_boot, what="plain reboot")
    if follow and ofl.cls_why[0] != "UNREADABLE":
        follow_up_save(d, rep, ofl, what="follow-up after the reboot")
    return rep
