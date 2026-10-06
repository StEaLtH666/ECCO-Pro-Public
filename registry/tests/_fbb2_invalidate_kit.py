"""FB-B2 INVALIDATE suite support (t-invalidate): helpers private to registry/tests/test_fallback_invalidate.py.

Nothing here edits or wraps the shared FB-B2 harness (_fbb2_drive.py, _fbb_harness.py, ...): it builds, on top of the public
Driver, the few things the INVALIDATE suite needs that the driver does not offer.

  GlobalWatch      every global assignment a driver's CURRENT sim performs (the transpiled lambdas assign through
                   sim.set_global), so a scenario can prove "this lambda never assigned manual_write_in_progress"
  nvs helpers      NVS image snapshots / event slices
  the ORACLE       what an INVALIDATE must write and what the FB-B0 writer must conclude, derived WITHOUT the firmware YAML and
                   WITHOUT registry/fallback_save.py: the intended pair comes from the FB-A mirror (fp.invalidate_profile,
                   guarded) + fd.make_provision exactly as the locked design lists it (master 4.8 / S2B 4.3, witness table
                   in the brief: hw = g+1, hw_binding = new binding, prior = g / old binding, op INVALIDATE), the writer's
                   verdict comes from the FB-B0 Python model (fd.commit_transition over a fresh H.DirectNvs holding the same
                   image and the same injected faults), the next-boot class from fd.compose_profile_class over the resolved
                   flash image
  texts            the four INVALIDATE outcome strings of master 4.8 / S2B 4.4 as format templates keyed on the oracle verdict
  fault rows       the WriteFault matrix (key x raw result x readback x health x boot resolution)
  mirror mutants   load a mutated copy of registry/fallback_save.py as a module the driver can use as `ecco_fbsave::`

No I/O besides reading repository files; no hardware.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import _fbb2_drive as D  # noqa: E402
import _fbb_harness as H  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

K_P, K_W, K_S = D.K_P, D.K_W, D.K_S
U32 = 0xFFFFFFFF
SAVE_MIRROR_PATH = ROOT / "registry" / "fallback_save.py"


# ---------------------------------------------------------------------------
# global-assignment watch
# ---------------------------------------------------------------------------
class GlobalWatch:
    """Records (name, value) of every global assignment a driver's sim performs, in order. attach() again after reboot()
    (a reboot builds a new sim); the log is kept across boots. Assignments made by the TEST through sim.g[...] directly are
    not recorded (use that to inject hooks without polluting the evidence); Driver.set_g() IS recorded, so take mark() after
    the set-up."""

    def __init__(self, drv):
        self.drv = drv
        self.log: list = []
        self.attach()

    def attach(self):
        sim = self.drv.sim
        if getattr(sim, "_inv_watch", None) is self:
            return self
        orig = sim.set_global

        def watched(name, value, _orig=orig):
            self.log.append((name, value))
            return _orig(name, value)
        sim.set_global = watched
        sim._inv_watch = self
        return self

    def mark(self) -> int:
        return len(self.log)

    def names(self, since: int = 0) -> set:
        # FB-B3 Slice A: the Live Match tick's own fence scalars are not part of the INVALIDATE flow's assignment evidence.
        return {n for n, _ in self.log[since:] if not n.startswith("fallback_profile_live_")}

    def values(self, name: str, since: int = 0) -> list:
        return [v for n, v in self.log[since:] if n == name]


def nvs_mark(d) -> int:
    return len(d.sim.nvs_direct.ops)


def nvs_events_since(d, m: int) -> list:
    return list(d.sim.nvs_direct.ops[m:])


def blobs_of(d) -> dict:
    """{key: (bytes, crc_ok, chunk_present)} of the direct NVS right now (no read performed)."""
    return {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in d.sim.nvs_direct.blobs.items()}


def copy_blobs(d) -> dict:
    return {k: b.copy() for k, b in d.sim.nvs_direct.blobs.items()}


# ---------------------------------------------------------------------------
# the oracle
# ---------------------------------------------------------------------------
def intended_pair(p: dict) -> tuple:
    """(p_new, w_new) an INVALIDATE of the VALID profile `p` must write: payload verbatim, generation + 1, flag bit0, re-sealed
    (FB-A, guarded: it raises for anything but VALID) and the witness (hw = g+1, hw_binding = new binding, prior = g / old
    binding, op INVALIDATE) that FB-B0's make_provision seals."""
    pn = fp.invalidate_profile(p)
    wn = fd.make_provision(pn["generation"], pn["binding"], p["generation"], p["binding"], fd.FALLBACK_PROFILE_KEY,
                           fp.PROFILE_SCHEMA, fd.PROV_OP_INVALIDATE)
    return pn, wn


def clone_write_fault(f: "H.WriteFault") -> "H.WriteFault":
    return H.WriteFault(result=f.result, visible=f.visible, boot=f.boot, healthy_after=f.healthy_after, other=bytes(f.other),
                        wrong_len=f.wrong_len)


@dataclass
class Verdict:
    """What the independent model concludes for one INVALIDATE commit over an NVS image."""
    outcome: int                      # fd.TXN_*
    r: object                         # fd.TxnResult (None when no commit was attempted)
    sets: list                        # [(key, result)] in call order
    nvs_after: object                 # the DirectNvs the commit ran on (flash state at the end / at the cut)
    cut: bool
    p_prior: dict
    p_bytes: bytes
    p_load: int
    w_bytes: bytes
    w_load: int
    dp: object
    dw: object
    p_new: dict
    w_new: dict


def oracle_invalidate(blobs: dict, *, faults=None, cut_point=None, health_before=True, latch=False, handle=1) -> Verdict:
    """Replay the INVALIDATE commit on an independent H.DirectNvs holding the image `blobs` ({key: Blob}) with the same
    injected write faults. The prior records are READ the way the lambda reads them (fd.read_direct), the pair is the
    locked-design pair, the verdict is fd.commit_transition's. `cut_point` is relative to the first NVS event of the commit
    (the writer's own health check = event 0)."""
    nvs = H.DirectNvs(handle=handle)
    nvs.blobs = {k: b.copy() for k, b in blobs.items()}
    p_load, p_bytes, dp = fd.read_direct(nvs, K_P, fp.PROFILE_SIZE)
    w_load, w_bytes, dw = fd.read_direct(nvs, K_W, fd.PROVISION_SIZE)
    p = fp.unpack_profile(p_bytes)
    p_new, w_new = intended_pair(p)
    for key, flist in (faults or {}).items():
        nvs.faults[key] = [clone_write_fault(f) for f in flist]
    nvs.healthy = health_before
    nvs.events = 0
    nvs.cut_at = cut_point
    wl = fd.WriteLatch(latch)
    cut, o, r = False, fd.TXN_UNKNOWN_REBOOT, None
    try:
        o, r = fd.commit_transition(nvs, wl, w_new, w_bytes, (w_load, dw.stored_len), p_new, p_bytes, (p_load, dp.stored_len))
    except H.PowerCut:
        cut = True
    nvs.cut_at = None
    return Verdict(o, r, [(k, res) for k, _d, res in nvs.sets], nvs, cut, p, p_bytes, p_load, w_bytes, w_load, dp, dw, p_new,
                   w_new)


def class_after_boot(nvs) -> tuple:
    """(class name, why name, rule) the next boot derives from `nvs` once every pending write resolved (DirectNvs.reboot):
    fd.compose_profile_class over two fresh direct reads - the model oracle, no firmware."""
    n2 = nvs.reboot()
    pl, pb, _ = fd.read_direct(n2, K_P, fp.PROFILE_SIZE)
    wl, wb, _ = fd.read_direct(n2, K_W, fd.PROVISION_SIZE)
    cls, why, rule = fd.compose_profile_class(pl, pb, wl, wb, 0)
    return D.CLASS[cls], fd.WHY_NAMES[why], rule


def image_after_boot(nvs) -> dict:
    """{key: (bytes, crc_ok, chunk_present)} of the flash after the next boot's init clean-up."""
    n2 = nvs.reboot()
    return {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in n2.blobs.items()}


def image_now(nvs) -> dict:
    return {k: (bytes(b.data), b.crc_ok, b.chunk_present) for k, b in nvs.blobs.items()}


def expected_mirror(v: Verdict) -> tuple:
    """(class name, why name, 'overlay' flag) the RAM mirror must show after the commit: the composition of what the FB-B0
    mirror rule keeps (readbacks after COMMITTED / NOT_COMMITTED, the pre-transaction values after UNKNOWN or a refusal);
    the SAVE_UNCONFIRMED overlay wins after UNKNOWN."""
    if v.r is None:
        raise ValueError("no commit attempted")
    mp, mw, mpl, mwl = fd.mirror_after(v.outcome, v.r, v.p_bytes, v.p_load, v.w_bytes, v.w_load)
    cls, why, _rule = fd.compose_profile_class(mpl, mp, mwl, mw, 0)
    return D.CLASS[cls], fd.WHY_NAMES[why], v.outcome == fd.TXN_UNKNOWN_REBOOT


# ---------------------------------------------------------------------------
# texts (master 4.8, S2B 4.4, api contract 5): the four INVALIDATE outcomes
# ---------------------------------------------------------------------------
def err_text(err: int) -> str:
    err &= U32
    return "-" if err == 0 else "E%X" % err


def b9_invalidated(g_prior: int) -> str:
    return (f"INVALIDATED - profile generation {g_prior} is no longer usable (now INVALIDATED g{g_prior + 1}); "
            "payload kept for reference; save a new profile to re-enable")


def b9_not_committed(err: int, g_prior: int) -> str:
    return f"INVALIDATE NOT COMMITTED - storage refused the write ({err_text(err)}); profile still VALID g{g_prior}"


def b9_witness_advanced(g_prior: int) -> str:
    return ("INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: "
            f"g{g_prior} is now STALE (unusable)")


def b9_unknown(detail: str) -> str:
    return (f"INVALIDATE OUTCOME UNKNOWN - {detail}; treat the profile as unusable; reboot to re-verify "
            "(Fallback Profile writes locked until reboot)")


def expected_b9(v: Verdict) -> str:
    """The B9 text the locked table gives for the writer's verdict (witness-first transaction)."""
    r, g = v.r, v.p_prior["generation"]
    if v.outcome == fd.TXN_COMMITTED:
        return b9_invalidated(g)
    if v.outcome == fd.TXN_NOT_COMMITTED:
        return b9_witness_advanced(g) if r.witness_advanced else b9_not_committed(r.w.err, g)
    if v.outcome == fd.TXN_UNKNOWN_REBOOT:
        k = r.w if r.w.outcome == fd.KEY_UNKNOWN_REBOOT else r.p
        return b9_unknown(f"{err_text(k.err)}/{fd.RB_NAMES[k.rb_class]}")
    raise ValueError(f"unexpected outcome {v.outcome}")


def first_nonzero(*errs) -> int:
    for e in errs:
        if e & U32:
            return e & U32
    return 0


def parse_kv(text: str) -> dict:
    """`k=v;k=v` -> dict (B2 / B3 grammar)."""
    out = {}
    for part in text.split(";"):
        k, _, v = part.partition("=")
        out[k] = v
    return out


OP_SHORT = {fd.PROV_OP_SAVE: "SAVE", fd.PROV_OP_INVALIDATE: "INV", fd.PROV_OP_REPLACE_CORRUPT: "RC"}


def expected_b2(p_bytes: bytes, p_load: int, w_bytes: bytes, w_load: int, why: int, werr: int, us: int) -> dict:
    """The B2 key/value set (brief E grammar `g=;id=;at=;ld=;df=;w=;hw=;op=;why=;werr=;us=`) for a mirror pair: g/id/at only for an
    authentic record, `w` OK|LAG|MISS|CORR|UNR|ABS, hw / op only from a valid witness."""
    p = fp.unpack_profile(p_bytes) if p_load == fp.LOAD_OK else fp.blank_profile()
    w = fd.unpack_provision(w_bytes) if w_load == fd.LOAD_OK else fd.blank_provision()
    pc = fp.classify_profile(p_load, p)
    wc = fd.classify_witness(w_load, w)
    out = {"ld": {fp.LOAD_OK: "OK", fp.LOAD_ABSENT: "ABS", fp.LOAD_WRONG_SIZE: "WSZ", fp.LOAD_READ_ERROR: "RERR",
                  fp.LOAD_STORAGE_UNAVAILABLE: "UNAV"}[p_load]}
    if fd.fba_authentic(pc):
        out.update(g=str(p["generation"]), id=f"{p['binding']:016X}", at=str(p["captured_epoch"]))
    else:
        out.update(g="-", id="-", at="-")
    out["df"] = "-"
    if wc == fd.W_VALID:
        out["w"] = "LAG" if why == fd.WHY_WIT_LAGGING else "OK"
        out["hw"] = str(w["hw_generation"])
        out["op"] = OP_SHORT.get(w["last_op"], "-")
    else:
        out["w"] = {fd.W_ABSENT: "MISS", fd.W_CORRUPT: "CORR", fd.W_UNREADABLE: "UNR"}[wc]
        out["hw"] = "-"
        out["op"] = "-"
    out["why"] = fd.WHY_NAMES[why]
    out["werr"] = err_text(werr)
    out["us"] = "-" if (us & U32) == 0 else str(us & U32)
    return out


# ---------------------------------------------------------------------------
# NVS write-fault rows
# ---------------------------------------------------------------------------
RAW_RESULTS = {
    "OK": fd.IDF_OK,
    "PRE_INVALID_HANDLE": fd.IDF_ERR_NVS_INVALID_HANDLE,
    "PRE_READ_ONLY": fd.IDF_ERR_NVS_READ_ONLY,
    "PRE_NOT_INITIALIZED": fd.IDF_ERR_NVS_NOT_INITIALIZED,
    "NO_MEM": fd.IDF_ERR_NO_MEM,
    "NOT_ENOUGH_SPACE": fd.IDF_ERR_NVS_NOT_ENOUGH_SPACE,
    "FLASH_OP_FAIL": fd.IDF_ERR_FLASH_OP_FAIL,
    "TIMEOUT": fd.IDF_ERR_TIMEOUT,
    "FAIL": fd.IDF_FAIL,
    "NOT_FOUND": fd.IDF_ERR_NVS_NOT_FOUND,
    "NVS_INVALID_STATE": fd.IDF_ERR_NVS_INVALID_STATE,
}
VISIBLES = (H.VIS_NEW, H.VIS_OLD, H.VIS_ABSENT, H.VIS_CRCBAD, H.VIS_NOCHUNK_OLD, H.VIS_OTHER, H.VIS_WRONGSIZE, H.VIS_UNAVAILABLE)
KEY_SIZE = {"FBP": fp.PROFILE_SIZE, "FBW": fd.PROVISION_SIZE}


def make_fault(key: str, result: int, visible: str, healthy_after: bool = True, boot: str = H.BOOT_ASIS):
    """A WriteFault for the next set_blob of `key` ("FBP" | "FBW")."""
    size = KEY_SIZE[key]
    return H.WriteFault(result=result, visible=visible, boot=boot, healthy_after=healthy_after,
                        other=bytes([0xA5]) * size if visible == H.VIS_OTHER else b"",
                        wrong_len=size - 9 if visible == H.VIS_WRONGSIZE else 0)


def fault_label(key, result_name, visible, healthy_after, boot) -> str:
    return f"{key}:{result_name}/{visible}/{'healthy' if healthy_after else 'INVALID-page'}/boot-{boot}"


# ---------------------------------------------------------------------------
# YAML / mirror text mutation helpers
# ---------------------------------------------------------------------------
INV_SCRIPT_HEAD = "  - id: fallback_profile_invalidate\n"
INV_SCRIPT_END = "\nbutton:\n"


def inv_region(text: str) -> tuple:
    """(start, end) of the fallback_profile_invalidate script block in the firmware text (LF)."""
    a = text.index(INV_SCRIPT_HEAD)
    b = text.index(INV_SCRIPT_END, a)
    return a, b


def edit_inv(text: str, old: str, new: str, count: int = 1) -> str:
    """Replace `old` by `new` ONLY inside the INVALIDATE script (so a mutant can never touch the SAVE script, which repeats many
    of the same statements); `old` must occur exactly `count` times in that block (a mutant is never a silent no-op)."""
    a, b = inv_region(text)
    blk = text[a:b]
    n = blk.count(old)
    if n != count:
        raise D.DriverError(f"INVALIDATE-script anchor occurs {n} times, want {count}: {old[:90]!r}")
    return text[:a] + blk.replace(old, new) + text[b:]


def load_mirror_text(source: str, name: str = "fallback_save_mutant") -> types.ModuleType:
    """A module made from (mutated) source text of registry/fallback_save.py, usable as Driver(fbsave=module)."""
    mod = types.ModuleType(name)
    mod.__file__ = str(SAVE_MIRROR_PATH)
    sys.modules[name] = mod  # dataclasses resolve their module through sys.modules
    try:
        exec(compile(source, str(SAVE_MIRROR_PATH), "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


def mutate_mirror(source: str, old: str, new: str, count: int = 1) -> str:
    n = source.count(old)
    if n != count:
        raise D.DriverError(f"mirror anchor occurs {n} times, want {count}: {old[:90]!r}")
    return source.replace(old, new)


class Errs(list):
    """A scenario's list of violation strings; `n` counts the assertions made (the suite reports it)."""

    def __init__(self, *a):
        super().__init__(*a)
        self.n = 0
        self.verdict = None

    def ok(self, cond, msg):
        self.n += 1
        if not cond:
            self.append(msg)
        return bool(cond)

    def eq(self, got, want, msg):
        self.n += 1
        if got != want:
            self.append(f"{msg}: got {got!r}, want {want!r}")
        return got == want
