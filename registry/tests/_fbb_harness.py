"""FB-B0 harness extension: the direct-NVS durable fault model and a strict
simulator for the Fallback Profile code (self-tested by
registry/tests/test_fallback_durable_harness.py; used by the FB-B0 host
compile / fault matrix and, from FB-B1 on, by the capture suites).

Why it exists (architecture 2.2 FB-B0 item 3; S6 BLK-07/18/42/43):
_dump_sim's durable store is tag-keyed and atomic - it cannot model the
direct NVS primitive FB-B uses (decimal keys, the two-step read and its side
effects, per-key write results whose effect is not what the result code
says, post-reboot resolution, a partition wipe, a zero handle, an INVALID
page), it has no pending-queue model, no `wait_until` timeout, no
`is_running()`, no Modbus hub, cannot execute the ecco_fallback:: /
ecco_fbdurable:: namespaces (brace-init, arrays, `name.field[i]`,
RecordLoad 4) and silently zero-initialises unknown struct-typed globals.
Everything here closes one of those gaps and FAILS rather than skips on
anything it does not model (FbbNotModelled).

Contents:
  DirectNvs        IDF-exact enough NVS model of one partition, keyed by the
                   32-bit preference key (rendered as ESPHome's decimal key
                   string in its op log). It IS an NVS policy for
                   registry/fallback_durable.py (handle / set_blob / get_blob /
                   get_stats / now_us). Fault injection: per-key WriteFault
                   (result code, what a readback sees now, what the next
                   boot resolves to, health after), queued read errors,
                   cross-key erase, a between-read-steps hook (interleaved
                   Wi-Fi GC / IntervalSyncer), power cut before/after any
                   event, zero handle, INVALID page, reboot(), wipe().
  EspHomePrefs     ESPHome's pending save queue (save / load / sync) on top of
                   a DirectNvs, with the queue-presence tripwire: any
                   preference touching an FB key raises FbbTripwire.
  install_durable_tripwire(sim)  the same tripwire on a _dump_sim.Sim.
  Scenario / run_scenario        the durable transaction scenario runner
                   shared with the C++ host fault driver (byte-identical
                   result lines).
  FbbSim           a strict _dump_sim.Sim: C++-exact ecco_fallback:: /
                   ecco_fbdurable:: adapter (the C++ semantics of FB-A's
                   invalidate_profile, not the Python mirror's ValueError
                   guard), struct globals with copy semantics,
                   `name.field[i]` and `id(g).field` assignment, is_running(),
                   wait_until timeouts and delay on a cooperative clock with
                   background tasks, and a Modbus hub model.

FB-B1 additions (self-tested by registry/tests/test_fallback_capture_harness.py;
the capability list is FbbSim.CAPABILITIES, asserted there):
  std::array globals / locals (bounds-checked FbArray, value semantics,
  indexing, by-reference passing), a generic `ecco_fbcap::` adapter over the
  Python mirror registry/fallback_capture.py (_fbb1_fbcap), direct-NVS
  ecco_durable::ValidMarker probes, random_uint32() with an observable seed,
  Modbus handlers with `values.size()` / `exception_code`, deferred (late)
  frame delivery on a hub model with injectable foreign frames, ESPHome-shaped
  asynchronous scripts, a generic interval scheduler and injectable events
  (_fbb1_engine), and the transpiler gaps of _fbb1_xpile (casts, unsigned
  wrap, loops, constexpr, sizeof, std::string +).

FB-B2 additions (self-tested by registry/tests/test_fallback_save_harness.py; the capability list is
FbbSim.CAPABILITIES_FBB2, asserted there):
  esphome::StringRef api-action variables (call_api), template-switch automations (turn_on_action /
  turn_off_action / on_turn_on / on_turn_off / on_state, optimistic, the Deduplicator of publish_state) with
  operator-side switch flips, a payload-carrying direct-NVS set log and a before-op hook, a write-allowing
  safety audit (`Since.violations_fb`), the `ecco_fbsave::` namespace (firmware/include/ecco_fallback_save.h) resolved by
  introspection over registry/fallback_save.py, the std::string mutators, and the remaining ecco_fbdurable names the
  SAVE / INVALIDATE lambdas use (MirrorRecords{}, seal_provision, validate_transition, decimal_key, IDF_* / WIT_DEFECT_*).

No I/O, no hardware.
"""

from __future__ import annotations

import copy
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "registry"))
import struct  # noqa: E402

import _dump_sim as ds  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
from _fbb1_types import (ARRAY_ELEM_TYPES, ConstArray, FbArray, FbbNotModelled, FbbTimeout, FCStr, NPOS, PowerCut, U32,  # noqa: E402,F401
                         U64, StringRef, c_div_t, c_mod_t, cast_t, duration_ms, mkarr, parse_array_ctype, str_from, str_mut)
from _fbb1_xpile import XpileMixin, c_to_string, incdec_idx, incdec_l, static_assert_fail  # noqa: E402
from _fbb1_fbcap import FbcapNamespace, PodValue, set_record_factory  # noqa: E402
from _fbb1_engine import (EngineMixin, FrameSpec, P_EXTERNAL, P_LOOP, P_SCHED, Task, Wire)  # noqa: E402,F401


class FbbTripwire(AssertionError):
    """A preference / ecco_durable record operation named an FB key."""


FB_KEYS = (fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_KEY, fd.FAILBACK_STATE_KEY)
FB_TAGS = (fp.FALLBACK_PROFILE_TAG, fd.FAILBACK_PROVISION_TAG, fp.FAILBACK_STATE_TAG)
FB_KEY_STRINGS = tuple(fd.decimal_key(k) for k in FB_KEYS)


def is_fb_key(key) -> bool:
    return key in FB_KEYS or key in FB_TAGS or str(key) in FB_KEY_STRINGS


def fnv64_hex(data: bytes) -> str:
    return f"{fp.fnv1a_64(bytes(data)):016X}"


# ---------------------------------------------------------------------------
# Direct NVS model
# ---------------------------------------------------------------------------
# What a direct readback sees right after a set (WriteFault.visible):
VIS_NEW = "NEW"                  # the new bytes, clean
VIS_OLD = "OLD"                  # the old blob exactly as before (absent if there was none)
VIS_ABSENT = "ABSENT"            # the key vanished (INVALID page hid it, N9, ...)
VIS_CRCBAD = "CRCBAD"            # new bytes whose data CRC fails: the data read erases the chunk -> NOT_FOUND
VIS_NOCHUNK_OLD = "NOCHUNK_OLD"  # old index kept, old chunk gone (N9): the data read erases the index -> ESP_FAIL
VIS_OTHER = "OTHER"              # different bytes of the right size (duplicate poisoning / foreign writer)
VIS_WRONGSIZE = "WRONGSIZE"      # a blob of another length
VIS_UNAVAILABLE = "UNAVAILABLE"  # the new bytes landed, but every later read this boot reports NOT_INITIALIZED
VISIBLE_STATES = (VIS_NEW, VIS_OLD, VIS_ABSENT, VIS_CRCBAD, VIS_NOCHUNK_OLD, VIS_OTHER, VIS_WRONGSIZE, VIS_UNAVAILABLE)
# What the next boot resolves a written key to (WriteFault.boot):
BOOT_ASIS = "ASIS"      # the end-of-boot flash state (after IDF init clean-up)
BOOT_NEW = "NEW"
BOOT_OLD = "OLD"
BOOT_ABSENT = "ABSENT"
BOOT_STATES = (BOOT_ASIS, BOOT_NEW, BOOT_OLD, BOOT_ABSENT)


@dataclass
class Blob:
    data: bytes
    crc_ok: bool = True
    chunk_present: bool = True

    def copy(self) -> "Blob":
        return Blob(bytes(self.data), self.crc_ok, self.chunk_present)


@dataclass
class WriteFault:
    result: int = fd.IDF_OK
    visible: str = VIS_NEW
    boot: str = BOOT_ASIS
    healthy_after: bool = True
    other: bytes = b""
    wrong_len: int = 0

    def __post_init__(self):
        if self.visible not in VISIBLE_STATES or self.boot not in BOOT_STATES:
            raise FbbNotModelled(f"unknown write fault {self.visible}/{self.boot}")


class DirectNvs:
    """One NVS partition (namespace "esphome") as FB-B sees it. Events that
    count for power cuts: every get_blob call (probe or data), set_blob and
    get_stats; cut point 2n is BEFORE event n, 2n+1 AFTER it."""

    def __init__(self, handle: int = 1):
        self.blobs: dict[int, Blob] = {}
        self.handle_value = handle
        self.healthy = True
        self.unavailable = False
        self.faults: dict[int, list[WriteFault]] = {}
        self.read_faults: dict[int, list[int]] = {}
        self.poisoned: set[int] = set()
        self.pending_boot: dict[int, tuple[str, Blob | None, Blob | None]] = {}
        self.between_read_steps = None
        self.after_set = None
        self.ops: list[tuple] = []
        self.events = 0
        self.cut_at: int | None = None
        self.clock_us = 0
        # FB-B1: an optional listener(event) called after every op ("nvs", op, key, result) - FbbSim
        # routes it into its ONE ordered event timeline (and event_hook), so a test can inject a
        # power cut / bank mutation right after any NVS read or set.
        self.listener = None
        # FB-B2: every set_blob in call order as (key, bytes, result) - the evidence for "only FBW then FBP, exactly these
        # bytes" (the `ops` log carries no payload) - and a hook called at the START of every operation, before the
        # power-cut point of that event: before_op(op, key) with op "stats" | "get" (size probe) | "read" (data read) |
        # "set" and key the decimal key string (None for stats). It may raise PowerCut: "cut BEFORE the FBP set".
        self.sets: list[tuple] = []
        self.before_op = None

    # -- helpers --
    def put(self, key: int, data: bytes, crc_ok: bool = True, chunk_present: bool = True) -> None:
        self.blobs[key] = Blob(bytes(data), crc_ok, chunk_present)

    def state_of(self, key: int) -> str:
        b = self.blobs.get(key)
        if b is None:
            return "ABS"
        tag = "OK" if b.crc_ok and b.chunk_present else ("CRCBAD" if b.chunk_present else "NOCHUNK")
        return f"{tag}:{len(b.data)}:{fnv64_hex(b.data)}"

    def set_count(self) -> int:
        return sum(1 for op in self.ops if op[0] == "set")

    def read_probe_count(self) -> int:
        """Number of two-step reads started (one size probe each) - FB-B1 counts these."""
        return sum(1 for op in self.ops if op[0] == "get")

    def _notify(self, op, key, result) -> None:
        if self.listener is not None:
            self.listener(("nvs", op, key, result))

    def _event(self, where: str) -> None:
        if self.cut_at is not None:
            point = 2 * self.events + (0 if where == "before" else 1)
            if point == self.cut_at:
                raise PowerCut(f"cut at point {point}")

    # -- the NVS policy --
    def handle(self) -> int:
        return self.handle_value

    def now_us(self) -> int:
        self.clock_us += 7
        return self.clock_us & 0xFFFFFFFF

    def get_stats(self) -> int:
        if self.before_op is not None:
            self.before_op("stats", None)
        self._event("before")
        r = fd.IDF_OK if self.healthy else fd.IDF_ERR_INVALID_STATE
        self.ops.append(("stats", None, r))
        self._notify("stats", None, r)
        self._event("after")
        self.events += 1
        return r

    def get_blob(self, key: int, capacity):
        if self.before_op is not None:
            self.before_op("get" if capacity is None else "read", fd.decimal_key(key))
        self._event("before")
        r = self._get_blob(key, capacity)
        self.ops.append(("get" if capacity is None else "read", fd.decimal_key(key), r[0]))
        self._notify("get" if capacity is None else "read", fd.decimal_key(key), r[0])
        self._event("after")
        self.events += 1
        return r

    def _get_blob(self, key: int, capacity):
        for k in sorted(self.poisoned):
            self.blobs.pop(k, None)  # cross-key erase: a scan erases another key's inconsistent entry
        self.poisoned.clear()
        if self.handle_value == 0:
            return fd.IDF_ERR_NVS_INVALID_HANDLE, 0, None
        if self.unavailable:
            return fd.IDF_ERR_NVS_NOT_INITIALIZED, 0, None
        queue = self.read_faults.get(key)
        if queue:
            err = queue.pop(0)
            if err != fd.IDF_OK:
                return err, 0, None
        b = self.blobs.get(key)
        if b is None:
            return fd.IDF_ERR_NVS_NOT_FOUND, 0, None
        if capacity is None:
            return fd.IDF_OK, len(b.data), None  # the size probe reads the index only
        if self.between_read_steps is not None:
            self.between_read_steps(self, key)
            b = self.blobs.get(key)
            if b is None:
                return fd.IDF_ERR_NVS_NOT_FOUND, 0, None
        if not b.chunk_present:
            del self.blobs[key]  # missing chunk: the read erases the index
            return fd.IDF_FAIL, 0, None
        if not b.crc_ok:
            b.chunk_present = False  # CRC-bad chunk: erased by THIS read
            return fd.IDF_ERR_NVS_NOT_FOUND, 0, None
        if capacity < len(b.data):
            return fd.IDF_ERR_NVS_INVALID_LENGTH, len(b.data), None
        return fd.IDF_OK, len(b.data), bytes(b.data)

    def set_blob(self, key: int, data: bytes) -> int:
        if self.before_op is not None:
            self.before_op("set", fd.decimal_key(key))
        self._event("before")
        r = self._set_blob(key, bytes(data))
        self.sets.append((key, bytes(data), r))
        self.ops.append(("set", fd.decimal_key(key), r))
        self._notify("set", fd.decimal_key(key), r)
        self._event("after")
        self.events += 1
        if self.after_set is not None:
            self.after_set(self, key)
        return r

    def _set_blob(self, key: int, data: bytes) -> int:
        if self.handle_value == 0:
            return fd.IDF_ERR_NVS_INVALID_HANDLE
        queue = self.faults.get(key)
        fault = queue.pop(0) if queue else WriteFault()
        old = self.blobs.get(key)
        old_copy = old.copy() if old is not None else None
        new = Blob(data)
        vis = fault.visible
        if vis == VIS_NEW:
            self.blobs[key] = new
        elif vis == VIS_OLD:
            pass
        elif vis == VIS_ABSENT:
            self.blobs.pop(key, None)
        elif vis == VIS_CRCBAD:
            self.blobs[key] = Blob(data, crc_ok=False)
        elif vis == VIS_NOCHUNK_OLD:
            if old is None:
                self.blobs.pop(key, None)
            else:
                self.blobs[key] = Blob(old.data, old.crc_ok, chunk_present=False)
        elif vis == VIS_OTHER:
            if len(fault.other) != len(data):
                raise FbbNotModelled("VIS_OTHER needs replacement bytes of the record size")
            self.blobs[key] = Blob(bytes(fault.other))
        elif vis == VIS_WRONGSIZE:
            if fault.wrong_len == len(data):
                raise FbbNotModelled("VIS_WRONGSIZE needs a different length")
            self.blobs[key] = Blob(bytes(fault.wrong_len))
        elif vis == VIS_UNAVAILABLE:
            self.blobs[key] = new
            self.unavailable = True
        if not fault.healthy_after:
            self.healthy = False  # an INVALID page stays INVALID in RAM until reboot
        self.pending_boot[key] = (fault.boot, old_copy, new)
        return fault.result

    # -- boots --
    def reboot(self, absent_keys=(), handle: int = 1) -> "DirectNvs":
        """The next boot: every written key resolves per its WriteFault.boot;
        IDF init then erases indexes whose chunks are missing (a CRC-bad
        chunk survives until it is read). RAM state (health, unavailable,
        faults, hooks, cut) resets. `absent_keys` models an init-time loss
        (e.g. the 24-bit duplicate-hash erase, F11)."""
        n = DirectNvs(handle=handle)
        blobs = {k: b.copy() for k, b in self.blobs.items()}
        for key, (boot, old, new) in self.pending_boot.items():
            if boot == BOOT_NEW:
                blobs[key] = new.copy()
            elif boot == BOOT_OLD:
                if old is None:
                    blobs.pop(key, None)
                else:
                    blobs[key] = old.copy()
            elif boot == BOOT_ABSENT:
                blobs.pop(key, None)
        for key in list(blobs):
            if not blobs[key].chunk_present:
                del blobs[key]
        for key in absent_keys:
            blobs.pop(key, None)
        n.blobs = blobs
        return n

    @staticmethod
    def wipe(handle: int = 1) -> "DirectNvs":
        """ESPHome's whole-partition erase after a failed nvs_open (S7)."""
        return DirectNvs(handle=handle)


# ---------------------------------------------------------------------------
# ESPHome's pending preference queue + the queue-presence tripwire
# ---------------------------------------------------------------------------
class EspHomePrefs:
    """ESP32Preferences as FB-B must never use it for FB keys: save() only
    queues (same key replaces), load() serves the queue first, sync()
    flushes EVERY queued key, clears the queue even on failure and returns
    one aggregate result (esphome/components/esp32/preferences.cpp)."""

    def __init__(self, nvs: DirectNvs):
        self.nvs = nvs
        self.pending: dict[int, bytes] = {}
        self.sync_count = 0

    def _tripwire(self, key, what: str) -> None:
        if is_fb_key(key):
            shown = fd.decimal_key(key) if isinstance(key, int) else str(key)
            raise FbbTripwire(f"ESPHome preference {what} names FB key {shown} - FB keys are written "
                              "only by commit_transition_t and read only by read_direct_t")

    def save(self, key: int, data: bytes) -> bool:
        self._tripwire(key, "save")
        self.pending[key] = bytes(data)
        return True

    def load(self, key: int, size: int):
        self._tripwire(key, "load")
        if key in self.pending:
            data = self.pending[key]
            return data if len(data) == size else None
        err, length, _ = self.nvs.get_blob(key, None)
        if err != fd.IDF_OK or length != size:
            return None
        err, _got, data = self.nvs.get_blob(key, size)
        return data if err == fd.IDF_OK else None

    def sync(self) -> bool:
        self.sync_count += 1
        failed = 0
        for key, data in list(self.pending.items()):
            if self.nvs.set_blob(key, data) != fd.IDF_OK:
                failed += 1
        self.pending.clear()
        return failed == 0


def install_durable_tripwire(sim) -> None:
    """Runtime twin of pin X3 on a _dump_sim.Sim: any ecco_durable
    commit/load naming an FB tag or key raises FbbTripwire."""
    d = sim.D
    for name in ("commit_record", "load_record", "load_record_status"):
        original = getattr(d, name)

        def guarded(key, record, _orig=original, _name=name):
            if is_fb_key(key):
                raise FbbTripwire(f"ecco_durable::{_name} named FB key {key!r}")
            return _orig(key, record)

        setattr(d, name, guarded)


# ---------------------------------------------------------------------------
# The durable transaction scenario runner (shared with the C++ fault driver)
# ---------------------------------------------------------------------------
PRIOR_ABSENT, PRIOR_OK, PRIOR_WS, PRIOR_CRCBAD, PRIOR_NOCHUNK = 0, 1, 2, 3, 4


@dataclass
class Scenario:
    name: str
    prior_p: tuple  # (kind, bytes_or_len)
    prior_w: tuple
    new_p: bytes
    new_w: bytes
    handle: int = 1
    health_before: bool = True
    latch: bool = False
    faults: list = field(default_factory=list)  # WriteFault per set_blob call, in call order
    cut: int = -1
    boot_absent: tuple = ()
    boot_wipe: bool = False
    handle_at_commit: int = -1  # >= 0: the handle the commit sees (the boot reads used `handle`)


def _install_prior(nvs: DirectNvs, key: int, prior: tuple) -> None:
    kind, val = prior
    if kind == PRIOR_ABSENT:
        return
    if kind == PRIOR_OK:
        nvs.put(key, val)
    elif kind == PRIOR_WS:
        nvs.put(key, bytes(val))
    elif kind == PRIOR_CRCBAD:
        nvs.put(key, val, crc_ok=False)
    elif kind == PRIOR_NOCHUNK:
        nvs.put(key, val, chunk_present=False)
    else:
        raise FbbNotModelled(f"prior kind {kind}")


def _keyrep(k: fd.KeyReport) -> str:
    return f"{k.outcome}/{k.rb_class}/{k.err}/{int(bool(k.healthy_after))}/{k.rb_load}"


def run_scenario(s: Scenario) -> str:
    """Runs one scenario through the Python mirror; the result line format is
    byte-identical to the C++ driver's (see test_fallback_durable_host_compile.py)."""
    nvs = DirectNvs(handle=s.handle)
    _install_prior(nvs, fd.FALLBACK_PROFILE_KEY, s.prior_p)
    _install_prior(nvs, fd.FAILBACK_PROVISION_KEY, s.prior_w)
    for f in s.faults:
        key = fd.FAILBACK_PROVISION_KEY if f[0] == "W" else fd.FALLBACK_PROFILE_KEY
        nvs.faults.setdefault(key, []).append(f[1])
    p_load, p_bytes, dp = fd.read_direct(nvs, fd.FALLBACK_PROFILE_KEY, fp.PROFILE_SIZE)
    w_load, w_bytes, dw = fd.read_direct(nvs, fd.FAILBACK_PROVISION_KEY, fd.PROVISION_SIZE)
    if s.handle_at_commit >= 0:
        nvs.handle_value = s.handle_at_commit
    nvs.healthy = s.health_before
    latch = fd.WriteLatch(s.latch)
    nvs.events = 0
    nvs.cut_at = s.cut if s.cut >= 0 else None
    sets_before = nvs.set_count()
    cut = False
    try:
        o, r = fd.commit_transition(nvs, latch, s.new_w, w_bytes, (w_load, dw.stored_len), s.new_p, p_bytes,
                                    (p_load, dp.stored_len))
    except PowerCut:
        cut = True
    if s.boot_wipe:
        boot_nvs = DirectNvs.wipe()
    else:
        boot_nvs = nvs.reboot(absent_keys=s.boot_absent)
    boot = fd.read_pair(boot_nvs, fd.ReadLatch())
    head = (f"{s.name} ld={p_load}/{w_load} sets={nvs.set_count() - sets_before} fp={nvs.state_of(fd.FALLBACK_PROFILE_KEY)} "
            f"fw={nvs.state_of(fd.FAILBACK_PROVISION_KEY)} boot={boot.cls}/{boot.why}/{boot.rule}")
    if cut:
        return f"{head} txn=CUT latch={int(latch.write_latched)}"
    mp, mw, mpl, mwl = fd.mirror_after(o, r, p_bytes, p_load, w_bytes, w_load)
    return (f"{head} txn={o} ref={r.refusal} w={_keyrep(r.w)} p={_keyrep(r.p)} latch={int(latch.write_latched)} "
            f"adv={int(r.witness_advanced)} mirror={mpl}:{fnv64_hex(mp)}/{mwl}:{fnv64_hex(mw)}")


def scenario_cxx_initializer(s: Scenario) -> str:
    """The same scenario as a C++ aggregate initializer for the host driver."""
    def prior(p):
        kind, val = p
        if kind == PRIOR_WS:
            return f"{{{kind}, \"\", {val}u}}"
        if kind == PRIOR_ABSENT:
            return "{0, \"\", 0u}"
        return f"{{{kind}, \"{bytes(val).hex()}\", {len(val)}u}}"

    faults = []
    vis_index = {v: i for i, v in enumerate(VISIBLE_STATES)}
    boot_index = {b: i for i, b in enumerate(BOOT_STATES)}
    for key, f in s.faults:
        faults.append(f"{{'{key}', {f.result}, {vis_index[f.visible]}, {boot_index[f.boot]}, {int(f.healthy_after)}, "
                      f"\"{bytes(f.other).hex()}\", {f.wrong_len}u}}")
    while len(faults) < 2:
        faults.append("{0, 0, 0, 0, 1, \"\", 0u}")
    absent = 0
    for k in s.boot_absent:
        absent |= 1 if k == fd.FALLBACK_PROFILE_KEY else 2
    return (f"{{\"{s.name}\", {prior(s.prior_p)}, {prior(s.prior_w)}, \"{bytes(s.new_p).hex()}\", \"{bytes(s.new_w).hex()}\", "
            f"{s.handle}u, {int(s.health_before)}, {int(s.latch)}, {len(s.faults)}, {{{', '.join(faults)}}}, {s.cut}, "
            f"{absent}, {int(s.boot_wipe)}, {s.handle_at_commit}}}")


# ---------------------------------------------------------------------------
# FB records and the C++-exact adapter for the strict simulator
# ---------------------------------------------------------------------------
_WIDTH_OF = {"B": "uint8_t", "H": "uint16_t", "I": "uint32_t", "Q": "uint64_t"}


class FbRecord:
    """A trivially-copyable C++ record: fixed fields, C-width wrapping on
    every store, arrays as fixed-length lists, value (copy) semantics on
    assignment via copy()."""

    _layouts = {
        "FallbackProfileV1": fp.PROFILE_LAYOUT,
        "FailbackProvisionV1": fd.PROVISION_LAYOUT,
        "FailbackStateV1": fp.FAILBACK_LAYOUT,
    }

    def __init__(self, kind: str, *init):
        if kind not in self._layouts:
            raise FbbNotModelled(f"record kind {kind}")
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_layout", self._layouts[kind])
        for f, c, n in self._layout:
            object.__setattr__(self, f, [0] * n if n > 1 else 0)
        if init:
            flat = [(f, c, n) for f, c, n in self._layout]
            if len(init) > len(flat):
                raise FbbNotModelled(f"{kind} brace-init with {len(init)} values")
            for (f, c, n), v in zip(flat, init):
                setattr(self, f, v)

    def __setattr__(self, name, value):
        for f, c, n in self._layout:
            if f == name:
                if n > 1:
                    if not isinstance(value, (list, tuple)) or len(value) != n:
                        raise FbbNotModelled(f"{self._kind}.{name} needs {n} values")
                    object.__setattr__(self, name, [ds.wrap(v, _WIDTH_OF[c]) for v in value])
                else:
                    object.__setattr__(self, name, ds.wrap(value, _WIDTH_OF[c]))
                return
        raise FbbNotModelled(f"{self._kind} has no field {name}")

    def set_field(self, name, value):
        setattr(self, name, value)

    def set_elem(self, name, idx, value):
        for f, c, n in self._layout:
            if f == name and n > 1:
                if not 0 <= int(idx) < n:
                    raise FbbNotModelled(f"{self._kind}.{name}[{idx}] out of range")
                getattr(self, name)[int(idx)] = ds.wrap(value, _WIDTH_OF[c])
                return
        raise FbbNotModelled(f"{self._kind}.{name} is not an array")

    def as_dict(self) -> dict:
        return {f: (list(getattr(self, f)) if n > 1 else getattr(self, f)) for f, _c, n in self._layout}

    def to_bytes(self) -> bytes:
        if self._kind == "FallbackProfileV1":
            return fp.pack_profile(self.as_dict())
        if self._kind == "FailbackProvisionV1":
            return fd.pack_provision(self.as_dict())
        return fp.pack_failback(self.as_dict())

    def load_bytes(self, data: bytes) -> None:
        if self._kind == "FallbackProfileV1":
            rec = fp.unpack_profile(bytes(data))
        elif self._kind == "FailbackProvisionV1":
            rec = fd.unpack_provision(bytes(data))
        else:
            rec = fp.unpack_failback(bytes(data))
        for f, v in rec.items():
            setattr(self, f, v)

    @classmethod
    def from_bytes(cls, kind: str, data: bytes) -> "FbRecord":
        r = cls(kind)
        r.load_bytes(data)
        return r

    def copy(self) -> "FbRecord":
        return FbRecord.from_bytes(self._kind, self.to_bytes())

    __copy__ = copy

    def __deepcopy__(self, memo):
        return self.copy()

    def __eq__(self, other):
        return isinstance(other, FbRecord) and self._kind == other._kind and self.to_bytes() == other.to_bytes()


def _record_from_dict(d: dict):
    """A record dict returned by a Python mirror function (profile_from_words, ...) -> the FbRecord a lambda holds."""
    for kind, layout in FbRecord._layouts.items():
        if set(d) == {f for f, _c, _n in layout}:
            r = FbRecord(kind)
            for f, _c, n in layout:
                setattr(r, f, list(d[f]) if n > 1 else d[f])
            return r
    return None


set_record_factory(_record_from_dict)


class Plain:
    """A small C++ aggregate (PriorDesc, ReadDiag, ReadLatch, ...): named
    fields, brace-init in declaration order, copy on assignment."""

    def __init__(self, kind: str, fields: tuple, *init):
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_fields", fields)
        for f in fields:
            object.__setattr__(self, f, 0)
        if len(init) > len(fields):
            raise FbbNotModelled(f"{kind} brace-init with {len(init)} values")
        for f, v in zip(fields, init):
            object.__setattr__(self, f, v)

    def __setattr__(self, name, value):
        if name not in self._fields:
            raise FbbNotModelled(f"{self._kind} has no field {name}")
        object.__setattr__(self, name, value)

    def set_field(self, name, value):
        setattr(self, name, value)

    def copy(self):
        return copy.deepcopy(self)


_PLAIN = {
    "PriorDesc": ("load", "stored_len"),
    "ReadDiag": ("probe_err", "data_err", "stored_len"),
    "ReadLatch": ("present_seen", "read_anomaly"),
    "EffectiveProfile": ("cls", "why", "rule"),
    "KeyReport": ("err", "rb_load", "rb_diag", "rb_class", "healthy_after", "outcome", "us"),
}


def _is_fb_value(v) -> bool:
    return isinstance(v, (FbRecord, Plain, TxnResultRec, PairReadRec, MirrorRec, FbArray, PodValue))


def fb_copy(v):
    """C++ value semantics for record-typed assignment / initialisation."""
    return v.copy() if _is_fb_value(v) else v


class TxnResultRec:
    def __init__(self):
        self.w = Plain("KeyReport", _PLAIN["KeyReport"])
        self.p = Plain("KeyReport", _PLAIN["KeyReport"])
        self.w.rb_diag = Plain("ReadDiag", _PLAIN["ReadDiag"])
        self.p.rb_diag = Plain("ReadDiag", _PLAIN["ReadDiag"])
        self.w_rb = FbRecord("FailbackProvisionV1")
        self.p_rb = FbRecord("FallbackProfileV1")
        self.witness_advanced = 0
        self.refusal = 0

    def copy(self):
        return copy.deepcopy(self)


class PairReadRec:
    def copy(self):
        return copy.deepcopy(self)


class MirrorRec:
    def copy(self):
        return copy.deepcopy(self)


def _keyreport_into(dst: Plain, k: fd.KeyReport) -> None:
    dst.err, dst.rb_load, dst.rb_class = k.err, k.rb_load, k.rb_class
    dst.healthy_after, dst.outcome, dst.us = int(bool(k.healthy_after)), k.outcome, k.us
    dst.rb_diag = Plain("ReadDiag", _PLAIN["ReadDiag"], k.rb_diag.probe_err, k.rb_diag.data_err, k.rb_diag.stored_len)


class FbaNamespace:
    """ecco_fallback:: with C++ semantics."""

    def __init__(self):
        for name in dir(fp):
            if re.fullmatch(r"(LOAD|PROFILE|FAILBACK|REG|V1|SOC)_[A-Z0-9_]+", name) and isinstance(getattr(fp, name), int):
                setattr(self, name, getattr(fp, name))

    def FallbackProfileV1(self, *init):
        return FbRecord("FallbackProfileV1", *init)

    def FailbackStateV1(self, *init):
        return FbRecord("FailbackStateV1", *init)

    @staticmethod
    def classify_profile(load, p):
        return fp.classify_profile(load, p.to_bytes())

    @staticmethod
    def classify_failback(load, s):
        return fp.classify_failback(load, s.to_bytes())

    @staticmethod
    def profile_binding(p):
        return fp.profile_binding(p.to_bytes())

    @staticmethod
    def seal_profile(p):
        return FbRecord.from_bytes("FallbackProfileV1", fp.pack_profile(fp.seal_profile(p.as_dict())))

    @staticmethod
    def invalidate_profile(p):
        # C++ semantics: NO permission re-check, generation wraps at 2^32 (V8).
        return FbRecord.from_bytes("FallbackProfileV1", fp.pack_profile(fd.invalidate_profile_cxx(p.as_dict())))

    @staticmethod
    def profile_invalidate_permitted(p):
        return fp.profile_invalidate_permitted(p.as_dict())

    @staticmethod
    def profile_generation_advances(previous, nxt):
        return fp.profile_generation_advances(previous, nxt)

    # -- FB-B1: the byte image of a record (the firmware keeps std::array<uint8_t, N> globals, never a
    #    struct global) and the other pure FB-A helpers a lambda may call (C++ semantics).
    @staticmethod
    def ProfileBytes(*init):
        return FbArray("uint8_t", fp.PROFILE_SIZE, list(init) or None)

    @staticmethod
    def FailbackBytes(*init):
        return FbArray("uint8_t", fp.FAILBACK_SIZE, list(init) or None)

    @staticmethod
    def encode_profile(p):
        # encode_profile does NOT seal: the binding is encoded verbatim (bytes 88..95)
        return FbArray.from_bytes(fp.pack_profile(p.as_dict()))

    @staticmethod
    def decode_profile(b):
        return FbRecord.from_bytes("FallbackProfileV1", _bytes_arg(b, fp.PROFILE_SIZE, "decode_profile"))

    @staticmethod
    def encode_failback(s):
        return FbArray.from_bytes(fp.pack_failback(s.as_dict()))

    @staticmethod
    def decode_failback(b):
        return FbRecord.from_bytes("FailbackStateV1", _bytes_arg(b, fp.FAILBACK_SIZE, "decode_failback"))

    @staticmethod
    def profile_defect(p):
        return fp.profile_defect(p.as_dict())

    @staticmethod
    def profile_domain_valid(p):
        return fp.profile_domain_valid(p.as_dict())

    @staticmethod
    def failback_binding(s):
        return fp.failback_binding(s.to_bytes())

    @staticmethod
    def seal_failback(s):
        return FbRecord.from_bytes("FailbackStateV1", fp.pack_failback(fp.seal_failback(s.as_dict())))

    @staticmethod
    def failback_defect(s):
        return fp.failback_defect(s.as_dict())

    @staticmethod
    def register_class(addr):
        return fp.register_class(int(addr))

    @staticmethod
    def register_class_mask(addr):
        return fp.register_class_mask(int(addr))

    @staticmethod
    def ctx_matches(addr, profile_value, live_value):
        # C++: FALSE for any non-CTX register (the Python mirror raises ValueError)
        if fp.register_class(int(addr)) != fp.REG_CTX:
            return False
        return fp.ctx_matches(int(addr), int(profile_value), int(live_value))

    @staticmethod
    def reg244_domain_valid(v):
        return fp.reg244_domain_valid(int(v))

    @staticmethod
    def tou_power_domain_valid(v):
        return fp.tou_power_domain_valid(int(v))

    @staticmethod
    def soc_domain_valid(v):
        return fp.soc_domain_valid(int(v))

    @staticmethod
    def slot_source_domain_valid(v):
        return fp.slot_source_domain_valid(int(v))

    @staticmethod
    def from_244_domain_valid(v):
        return fp.from_244_domain_valid(int(v))

    @staticmethod
    def reg244_write_permitted(live, target):
        return fp.reg244_write_permitted(int(live), int(target))


def _bytes_arg(b, size, what):
    if not isinstance(b, (FbArray, list, tuple, bytes, bytearray)) or len(b) != size:
        raise FbbNotModelled(f"{what} needs a std::array<uint8_t, {size}>")
    return bytes(list(b))


_MARKER = struct.Struct("<IB3x")  # ecco_durable::ValidMarker {uint32_t magic; uint8_t state;}: sizeof 8, 3 bytes padding


def key_int(key) -> int:
    """An NVS key as lambda code names it: a number, a decimal key string, or an ecco_durable tag
    (ecco_durable::key_for(TAG) is the tag itself in the legacy store; on the device it is its FNV-1 32)."""
    if isinstance(key, int):
        return int(key)
    s = str(key)
    if s.isdigit():
        return int(s)
    return fp.tag_key_fnv1_32(s)


class FbdNamespace:
    """ecco_fbdurable:: with C++ semantics, bound to one FbbSim (its DirectNvs,
    write latch and read latch)."""

    def __init__(self, sim: "FbbSim"):
        self._sim = sim
        for name in dir(fd):
            if re.fullmatch(r"(EPC|WHY|W|TXN|KEY|RB|WERR|REFUSAL|PROV_OP|FBS|KEY_BIT|ANOMALY_BIT|WIT_DEFECT)_[A-Z0-9_]+", name) \
                    or name in ("FALLBACK_PROFILE_KEY", "FAILBACK_PROVISION_KEY", "FAILBACK_STATE_KEY", "GENERATION_MAX",
                                "PROVISION_MAGIC", "PROVISION_SCHEMA", "PROVISION_SIZE",
                                # FB-B2: the idf codes ecco_fallback_durable_model.h declares (and nothing wider) + RULE_NONE
                                "IDF_OK", "IDF_ERR_NVS_NOT_INITIALIZED", "IDF_ERR_NVS_NOT_FOUND", "IDF_ERR_NVS_READ_ONLY",
                                "IDF_ERR_NVS_INVALID_HANDLE", "RULE_NONE"):
                setattr(self, name, getattr(fd, name))
        for i in range(1, 16):
            setattr(self, f"RULE_B{i}", i)
        self.RULE_B2A = fd.RULE_B2A

    # types
    def FailbackProvisionV1(self, *init):
        return FbRecord("FailbackProvisionV1", *init)

    def EspNvs(self, *init):
        if init:
            raise FbbNotModelled("EspNvs takes no initializer")
        return self._sim.nvs_direct

    def TxnResult(self, *init):
        if init:
            raise FbbNotModelled("TxnResult brace-init with values")
        return TxnResultRec()

    def PairRead(self, *init):
        if init:
            raise FbbNotModelled("PairRead brace-init with values")
        out = PairReadRec()
        out.p, out.w = FbRecord("FallbackProfileV1"), FbRecord("FailbackProvisionV1")
        out.dp, out.dw = Plain("ReadDiag", _PLAIN["ReadDiag"]), Plain("ReadDiag", _PLAIN["ReadDiag"])
        out.p_load = out.w_load = out.healthy = 0
        out.e = Plain("EffectiveProfile", _PLAIN["EffectiveProfile"])
        return out

    @staticmethod
    def ProvisionBytes(*init):
        return FbArray("uint8_t", fd.PROVISION_SIZE, list(init) or None)

    @staticmethod
    def encode_provision(w):
        return FbArray.from_bytes(fd.pack_provision(w.as_dict()))

    @staticmethod
    def decode_provision(b):
        return FbRecord.from_bytes("FailbackProvisionV1", _bytes_arg(b, fd.PROVISION_SIZE, "decode_provision"))

    @staticmethod
    def witness_defect(w):
        return fd.witness_defect(w.to_bytes())

    @staticmethod
    def fba_authentic(cls):
        return fd.fba_authentic(int(cls))

    @staticmethod
    def records_equal(a, b):
        if not (isinstance(a, FbRecord) and isinstance(b, FbRecord)) or a._kind != b._kind:
            raise FbbNotModelled("records_equal needs two records of the same type")
        return a.to_bytes() == b.to_bytes()

    @staticmethod
    def bytes_equal(a, b):
        if not (isinstance(a, FbArray) and isinstance(b, FbArray)) or len(a) != len(b) or a.ctype != "uint8_t" \
                or b.ctype != "uint8_t":
            raise FbbNotModelled("bytes_equal needs two std::array<uint8_t, N> of the same N")
        return list(a) == list(b)

    def __getattr__(self, name):
        if name in _PLAIN:
            return lambda *init: Plain(name, _PLAIN[name], *init)
        raise FbbNotModelled(f"ecco_fbdurable::{name} is not modelled by the FB-B harness adapter")

    # functions
    @staticmethod
    def classify_witness(load, w):
        return fd.classify_witness(load, w.to_bytes())

    @staticmethod
    def make_provision(hw, hwb, pg, pb, tag, schema, op):
        return FbRecord.from_bytes("FailbackProvisionV1", fd.pack_provision(fd.make_provision(hw, hwb, pg, pb, tag, schema, op)))

    @staticmethod
    def provision_binding(w):
        return fd.provision_binding(w.to_bytes())

    # -- FB-B2 ---------------------------------------------------------------------------------------------------
    @staticmethod
    def seal_provision(w):
        return FbRecord.from_bytes("FailbackProvisionV1", fd.pack_provision(fd.seal_provision(w.as_dict())))

    @staticmethod
    def validate_transition(w_new, w_prior, w_pd, p_new, p_prior, p_pd):
        return fd.validate_transition(w_new.to_bytes(), w_prior.to_bytes(), (w_pd.load, w_pd.stored_len),
                                      p_new.to_bytes(), p_prior.to_bytes(), (p_pd.load, p_pd.stored_len))

    @staticmethod
    def decimal_key(key):
        return FCStr(fd.decimal_key(int(key)))

    @staticmethod
    def MirrorRecords(*init):
        """`ecco_fbdurable::MirrorRecords m{}` / `{p, w, p_load, w_load}` (the struct mirror_after returns)."""
        if len(init) > 4:
            raise FbbNotModelled("MirrorRecords brace-init with more than 4 values")
        out = MirrorRec()
        out.p, out.w, out.p_load, out.w_load = FbRecord("FallbackProfileV1"), FbRecord("FailbackProvisionV1"), 0, 0
        for f, v in zip(("p", "w", "p_load", "w_load"), init):
            setattr(out, f, fb_copy(v))
        return out

    @staticmethod
    def compose_profile_class(p_load, p, w_load, w, anomaly):
        cls, why, rule = fd.compose_profile_class(p_load, p.to_bytes(), w_load, w.to_bytes(), anomaly)
        return Plain("EffectiveProfile", _PLAIN["EffectiveProfile"], cls, why, rule)

    @staticmethod
    def profile_writer_usable(cls, why):
        return fd.profile_writer_usable(cls, why)

    @staticmethod
    def save_class_permitted(cls):
        return fd.save_class_permitted(cls)

    @staticmethod
    def save_requires_replace_phrase(cls):
        return fd.save_requires_replace_phrase(cls)

    @staticmethod
    def invalidate_class_permitted(cls):
        return fd.invalidate_class_permitted(cls)

    @staticmethod
    def save_generation_base(c, g, wc, hw, seen):
        return fd.save_generation_base(c, g, wc, hw, seen)

    @staticmethod
    def save_generation_available(base):
        return fd.save_generation_available(base)

    @staticmethod
    def invalidate_generation_permitted(g, wc, hw, seen):
        return fd.invalidate_generation_permitted(g, wc, hw, seen)

    @staticmethod
    def next_seen_hw_gen(seen, c, g, wc, hw):
        return fd.next_seen_hw_gen(seen, c, g, wc, hw)

    @staticmethod
    def note_read(latch, key_bit, load, healthy):
        ps, ra = fd.note_read(latch.present_seen, latch.read_anomaly, key_bit, load, bool(healthy))
        return Plain("ReadLatch", _PLAIN["ReadLatch"], ps, ra)

    @staticmethod
    def note_committed(latch, key_bit):
        ps, ra = fd.note_committed(latch.present_seen, latch.read_anomaly, key_bit)
        return Plain("ReadLatch", _PLAIN["ReadLatch"], ps, ra)

    @staticmethod
    def fbs_slot(load, s):
        return fd.fbs_slot(load, s.to_bytes())

    @staticmethod
    def fbs_slot_clear(slot):
        return fd.fbs_slot_clear(slot)

    def storage_healthy(self, nvs):
        return fd.storage_healthy(nvs)

    def nvs_healthy(self):
        return fd.storage_healthy(self._sim.nvs_direct)

    def write_latched(self):
        return self._sim.write_latch.write_latched

    def read_direct_t(self, nvs, key, out, diag):
        key = key_int(key)
        if isinstance(out, ds.Record):
            # FB-B1: ecco_durable::ValidMarker marker probes through the SAME direct NVS (key =
            # ecco_durable::key_for(TAG) = FNV-1 32 of the tag), with every two-step read side effect.
            if out._kind != "ValidMarker":
                raise FbbNotModelled(f"read_direct_t of ecco_durable::{out._kind} is not modelled (only ValidMarker)")
            load, data, d = fd.read_direct(nvs, key, _MARKER.size)
            magic, state = _MARKER.unpack(data)  # all-zero unless LOAD_OK (C++: out = T{})
            out.magic, out.state = magic, state
        else:
            size = len(out.to_bytes())
            load, data, d = fd.read_direct(nvs, key, size)
            out.load_bytes(data)
        diag.probe_err, diag.data_err, diag.stored_len = d.probe_err, d.data_err, d.stored_len
        return load

    def read_pair_t(self, nvs, latch):
        pl = fd.ReadLatch(latch.present_seen, latch.read_anomaly)
        r = fd.read_pair(nvs, pl)
        latch.present_seen, latch.read_anomaly = pl.present_seen, pl.read_anomaly
        out = PairReadRec()
        out.p = FbRecord.from_bytes("FallbackProfileV1", r.p)
        out.w = FbRecord.from_bytes("FailbackProvisionV1", r.w)
        out.dp = Plain("ReadDiag", _PLAIN["ReadDiag"], r.dp.probe_err, r.dp.data_err, r.dp.stored_len)
        out.dw = Plain("ReadDiag", _PLAIN["ReadDiag"], r.dw.probe_err, r.dw.data_err, r.dw.stored_len)
        out.p_load, out.w_load, out.healthy = r.p_load, r.w_load, int(r.healthy)
        out.e = Plain("EffectiveProfile", _PLAIN["EffectiveProfile"], r.cls, r.why, r.rule)
        return out

    def commit_transition_t(self, nvs, w_new, w_prior, w_pd, p_new, p_prior, p_pd, r):
        o, res = fd.commit_transition(nvs, self._sim.write_latch, w_new.to_bytes(), w_prior.to_bytes(),
                                      (w_pd.load, w_pd.stored_len), p_new.to_bytes(), p_prior.to_bytes(),
                                      (p_pd.load, p_pd.stored_len))
        _keyreport_into(r.w, res.w)
        _keyreport_into(r.p, res.p)
        r.w_rb = FbRecord.from_bytes("FailbackProvisionV1", res.w_rb)
        r.p_rb = FbRecord.from_bytes("FallbackProfileV1", res.p_rb)
        r.witness_advanced, r.refusal = int(res.witness_advanced), res.refusal
        return o

    @staticmethod
    def mirror_after(o, r, p_prior, p_load, w_prior, w_load):
        res = fd.TxnResult()
        res.p.outcome = r.p.outcome
        res.p.rb_load, res.w.rb_load = r.p.rb_load, r.w.rb_load
        res.p_rb, res.w_rb = r.p_rb.to_bytes(), r.w_rb.to_bytes()
        mp, mw, mpl, mwl = fd.mirror_after(o, res, p_prior.to_bytes(), p_load, w_prior.to_bytes(), w_load)
        out = MirrorRec()
        out.p = FbRecord.from_bytes("FallbackProfileV1", mp)
        out.w = FbRecord.from_bytes("FailbackProvisionV1", mw)
        out.p_load, out.w_load = mpl, mwl
        return out


class FbbDurable(ds.Durable):
    """_dump_sim's ecco_durable namespace plus the two FB namespaces, reached
    through the FbbSim source rewrite ecco_fbdurable::X -> ecco_durable::FBD__X
    and ecco_fallback::X -> ecco_durable::FBA__X."""

    def __init__(self, sim: "FbbSim", fbcap=None, fbsave=None):
        super().__init__(sim)
        self._fbd = FbdNamespace(sim)
        self._fba = FbaNamespace()
        self._fbc = FbcapNamespace(sim, fbcap)
        # FB-B2: ecco_fbsave:: = registry/fallback_save.py by the same introspection, imported lazily on the first lookup
        self._fbv = FbcapNamespace(sim, fbsave, default_module="fallback_save", ns="ecco_fbsave")
        # FB-C2: ecco_failback_shadow:: = registry/failback_shadow.py by the same introspection, imported lazily on the first lookup
        self._fbh = FbcapNamespace(sim, None, default_module="failback_shadow", ns="ecco_failback_shadow")
        # FB-D1: ecco_rtc:: = registry/rtc_policy.py by the same introspection, imported lazily on the first lookup
        self._fbr = FbcapNamespace(sim, None, default_module="rtc_policy", ns="ecco_rtc")

    _SIZEOF = {"FBA__FallbackProfileV1": fp.PROFILE_SIZE, "FBA__FailbackStateV1": fp.FAILBACK_SIZE,
               "FBD__FailbackProvisionV1": fd.PROVISION_SIZE, "ValidMarker": _MARKER.size,
               "FBA__ProfileBytes": fp.PROFILE_SIZE, "FBA__FailbackBytes": fp.FAILBACK_SIZE,
               "FBD__ProvisionBytes": fd.PROVISION_SIZE}

    def sizeof_of(self, name):
        """sizeof(ecco_durable::<name>) as the rewritten source spells it."""
        if name.startswith("FBC__"):
            return self._fbc.sizeof_of(name[5:])
        if name.startswith("FBSV__"):
            return self._fbv.sizeof_of(name[6:])
        if name.startswith("FBSH__"):
            return self._fbh.sizeof_of(name[6:])
        if name.startswith("FBRT__"):
            return self._fbr.sizeof_of(name[6:])
        if name in self._SIZEOF:
            return self._SIZEOF[name]
        raise FbbNotModelled(f"sizeof({name}) is not modelled")

    def __getattr__(self, name):
        if name.startswith("FBC__"):
            return self._fbc.lookup(name[5:])
        if name.startswith("FBSV__"):
            return self._fbv.lookup(name[6:])
        if name.startswith("FBSH__"):
            return self._fbh.lookup(name[6:])
        if name.startswith("FBRT__"):
            return self._fbr.lookup(name[6:])
        if name.startswith("FBD__"):
            return getattr(self._fbd, name[5:])
        if name.startswith("FBA__"):
            member = name[5:]
            if hasattr(self._fba, member):
                return getattr(self._fba, member)
            raise FbbNotModelled(f"ecco_fallback::{member} is not modelled by the FB-B harness adapter")
        if name == "FB_copy":
            return fb_copy
        raise AttributeError(name)


_FB_NS = re.compile(r"\b(ecco_fbdurable|ecco_fallback|ecco_fbcap|ecco_fbsave|ecco_failback_shadow|ecco_rtc)::(\w+)((?:::\w+)*)")
_FB_PREFIX = {"ecco_fbdurable": "FBD__", "ecco_fallback": "FBA__", "ecco_fbcap": "FBC__", "ecco_fbsave": "FBSV__",
              "ecco_failback_shadow": "FBSH__", "ecco_rtc": "FBRT__"}


def rewrite_fb_namespaces(code: str) -> str:
    """ecco_fbdurable::X -> ecco_durable::FBD__X, ecco_fallback::X -> ecco_durable::FBA__X,
    ecco_fbcap::X -> ecco_durable::FBC__X, ecco_fbsave::X -> ecco_durable::FBSV__X (a scoped name `ecco_fbcap::A::B`
    becomes ecco_durable::FBC__A__FBCNS__B: ONE identifier the transpiler resolves through the adapter)."""
    def rep(m):
        ns, name, rest = m.groups()
        return f"ecco_durable::{_FB_PREFIX[ns]}{name}{rest.replace('::', '__FBCNS__')}"
    return _FB_NS.sub(rep, code)


FB_RECORD_CTYPES = {
    "ecco_fallback::FallbackProfileV1": "FallbackProfileV1",
    "ecco_fbdurable::FailbackProvisionV1": "FailbackProvisionV1",
    "ecco_fallback::FailbackStateV1": "FailbackStateV1",
}
KNOWN_SCALAR_CTYPES = {"bool", "int", "uint8_t", "uint16_t", "uint32_t", "int32_t", "uint64_t", "float", "double",
                       "std::string", "size_t", "unsigned"}


class FbbTranspiler(XpileMixin, ds.Transpiler):
    """_dump_sim's transpiler plus: `name.field[i] = v`, `id(g).field = v`,
    `id(g).field[i] = v`, default-construction of FB aggregates, and C++
    value semantics (copy) for record-typed initialisation - and, from
    FB-B1, everything in _fbb1_xpile.XpileMixin (arrays, casts, unsigned wrap,
    loops, constexpr, sizeof, std::string +, ...)."""

    def __init__(self, globals_types: dict, params: tuple = (), fb_globals=frozenset(), array_globals=None):
        super().__init__(globals_types, params)
        self.fb_globals = fb_globals
        self._xinit(array_globals)

    @staticmethod
    def wrap_expr(e, ctype):
        base = ctype.replace("*", "")
        if base.startswith("ecco_durable::FB"):
            return f"D.FB_copy({e})"
        return XpileMixin.wrap_expr(e, ctype)

    def decl(self, depth):
        start = self.i
        ctype = self.parse_type()
        if ctype.startswith("ecco_durable::FB") and self.peek(0)[0] == "id" and self.val(1) in (";", ","):
            while True:
                name = self.take()[1]
                self.emit(depth, f"L[{name!r}] = D.{ctype.split('::')[1]}()")
                self.ltypes[name] = ctype
                if self.val() == ",":
                    self.take(",")
                    continue
                self.take(";")
                return
        self.i = start
        super().decl(depth)

    def postfix(self, base):
        # A brace-init temporary of an FB aggregate - `ecco_fbdurable::PriorDesc{load, len}` as an argument or
        # an initializer - constructs it through the namespace adapter (which rejects excess values).
        if base.startswith("D.FB") and self.val() == "{":
            self.take("{")
            args = []
            while self.val() != "}":
                args.append(self.expr())
                if self.val() == ",":
                    self.take(",")
            self.take("}")
            base = f"{base}({', '.join(args)})"
        return super().postfix(base)

    def lvalue(self):
        start = self.i
        if (self.val() == "id" and self.val(1) == "(" and self.val(2) in self.fb_globals and self.val(3) == ")"
                and self.val(4) == "."):
            name = self.val(2)
            self.i += 5
            fieldname = self.take()[1]
            if self.val() == "(":
                self.i = start
                return super().lvalue()
            if self.val() == "[":
                self.take("[")
                idx = self.expr()
                self.take("]")
                return ("gfieldindex", f"S.g[{name!r}].{fieldname}[{idx}]", (name, fieldname, idx))
            return ("gfield", f"S.g[{name!r}].{fieldname}", (name, fieldname))
        if self.peek()[0] == "id" and self.val(1) == "." and self.peek(2)[0] == "id" and self.val(3) == "[":
            name = self.take()[1]
            self.take(".")
            fieldname = self.take()[1]
            self.take("[")
            idx = self.expr()
            self.take("]")
            return ("fieldindex", f"L[{name!r}].{fieldname}[{idx}]", (name, fieldname, idx))
        return super().lvalue()

    def assign(self, target, rhs):
        kind, _read, w = target
        if kind == "fieldindex":
            return f"L[{w[0]!r}].set_elem({w[1]!r}, {w[2]}, {rhs})"
        if kind == "gfield":
            return f"S.g[{w[0]!r}].set_field({w[1]!r}, D.FB_copy({rhs}))"
        if kind == "gfieldindex":
            return f"S.g[{w[0]!r}].set_elem({w[1]!r}, {w[2]}, {rhs})"
        if kind == "field":
            return f"setattr(L[{w[0]!r}], {w[1]!r}, D.FB_copy({rhs}))"
        if kind == "local":
            ctype = self.ltypes.get(w)
            if ctype and ctype.startswith("ecco_durable::FB"):
                return f"L[{w!r}] = D.FB_copy({rhs})"
        return super().assign(target, rhs)


class HubModel:
    """The Modbus hub as FB-B's bus-quiet predicates see it: queued frames
    (tx_buffer_empty) and one frame in flight awaiting its reply (tx_blocked).

    Two ways to drive it, which compose:
      * FB-B0 (legacy): `enqueue(n)` + `tick(now_ms)` count anonymous frames; or set
        `in_flight_until` by hand ("a poll holds the bus until t").
      * FB-B1: in `deferred` Modbus mode FbbSim's engine submits real frames
        (`frames` = queued, `in_flight_frame` = on the wire) and delivers their
        outcomes later; `turnaround_ms` models the inter-frame gap. With `clock`
        set (FbbSim does) an `in_flight_until` that has passed no longer blocks.
    """

    def __init__(self, frame_ms: int = 120):
        self.queued = 0
        self.in_flight_until: int | None = None
        self.frame_ms = frame_ms
        self.frames: list = []
        self.in_flight_frame = None
        self.turnaround_ms = 0
        self.turnaround_until: int | None = None
        self.clock = None

    def enqueue(self, n: int = 1) -> None:
        self.queued += n

    def tx_buffer_empty(self) -> bool:
        return self.queued == 0 and not self.frames

    def tx_blocked(self) -> bool:
        if self.in_flight_frame is not None:
            return True
        now = self.clock.now_ms if self.clock is not None else None
        if self.in_flight_until is not None and (now is None or now < self.in_flight_until):
            return True
        return self.turnaround_until is not None and now is not None and now < self.turnaround_until

    def tick(self, now_ms: int) -> None:
        if self.in_flight_until is not None and now_ms >= self.in_flight_until:
            self.in_flight_until = None
        if self.in_flight_until is None and self.queued > 0:
            self.queued -= 1
            self.in_flight_until = now_ms + self.frame_ms


class FbbEntity(ds.Entity):
    def __init__(self, sim, name):
        super().__init__(sim, name)
        # a template switch's Deduplicator<bool> (esphome/components/switch/switch.cpp): publish_state() drops a repeat of the
        # last PUBLISHED state; None = nothing published yet (FbbSim seeds it with the boot value of every switch)
        self._pub_dedup = None

    def _is_switch(self):
        return self.name in self._sim._switches

    def set(self, value):
        """Test helper (no hooks): force the state. For a switch this also resets the publish Deduplicator - the forced state
        is what was last 'published' - so a later turn_off() / turn_on() from a lambda really changes it."""
        super().set(value)
        if self._is_switch():
            self._pub_dedup = bool(value)

    # A template switch's turn_on()/turn_off()/toggle() are Switch::write_state(): the turn_on_action / turn_off_action
    # automation runs EVERY time (also when the switch is already in that state), then, if `optimistic`, publish_state().
    # Any other entity keeps _dump_sim's legacy behaviour (state only).
    def turn_on(self):
        if self._is_switch():
            self._sim._switch_write(self.name, True)
        else:
            super().turn_on()

    def turn_off(self):
        if self._is_switch():
            self._sim._switch_write(self.name, False)
        else:
            super().turn_off()

    def toggle(self):
        if not self._is_switch():
            raise FbbNotModelled(f"id({self.name}).toggle() - not a switch")
        self._sim._switch_write(self.name, not self.state)

    def control(self, state):
        if not self._is_switch():
            raise FbbNotModelled(f"id({self.name}).control() - not a switch")
        self._sim._switch_write(self.name, bool(state))

    def publish_state(self, value):
        if self._is_switch():
            self._sim._switch_publish(self.name, bool(value))
        else:
            super().publish_state(value)

    def is_running(self):
        if self.name not in self._sim.scripts:
            raise FbbNotModelled(f"id({self.name}).is_running() - not a script")
        return self.name in self._sim.running

    def tx_buffer_empty(self):
        return self._sim.hub.tx_buffer_empty()

    def tx_blocked(self):
        return self._sim.hub.tx_blocked()

    def execute(self):
        if self.name not in self._sim.scripts:
            raise FbbNotModelled(f"id({self.name}).execute() - not a script")
        self._sim._lambda_execute(self.name)

    def press(self):
        self._sim._lambda_press(self.name)

    def __getattr__(self, name):
        # an entity member the harness does not model is a loud FbbNotModelled, not an AttributeError
        if name.startswith("_"):
            raise AttributeError(name)
        raise FbbNotModelled(f"id({self.name}).{name} is not modelled by the FB-B harness")


def _S(v):
    """A text sensor / switch `.state` read as std::string (FCStr); other values untouched."""
    return FCStr(v) if isinstance(v, str) else v


class FbbSim(EngineMixin, ds.Sim):
    """A strict Sim for FB-B code. Differences from _dump_sim.Sim:
      - every global's C type must be a known scalar, a std::array<int, N>
        or an FB record type, else FbbNotModelled (never a silent 0 - S2
        Part A m16);
      - FB record globals hold FbRecord objects, array globals FbArray
        objects (bounds-checked, value semantics on assignment);
      - ecco_fallback:: / ecco_fbdurable:: / ecco_fbcap:: code runs through the
        C++-exact adapters over this Sim's DirectNvs (`self.nvs_direct`) and
        the Python mirror registry/fallback_capture.py;
      - wait_until (with timeout) and delay advance a cooperative clock in
        `tick_ms` steps, running `background` callables and the hub model
        between polls; is_running() reports scripts currently executing;
      - FB-B1: the discrete-event engine of _fbb1_engine (see its docstring):
        start_script / press_button / run_for / run_until / run_until_idle /
        start_intervals / at / at_press / at_bank / at_foreign_frame /
        at_power_cut / set_modbus_mode("deferred") / mark + since.

    The blocking `execute(script_id)` of FB-B0 is unchanged (runs the script to
    completion, polling waits on the engine clock); `start_script` is ESPHome's
    `script.execute` (returns at the first park)."""

    MAX_WAIT_MS = 10 * 60 * 1000
    CAPABILITIES = {
        "array_globals": "std::array<uint8_t|uint16_t|uint32_t|...,N> globals (FbArray): zero-init, value copy, id(g)[i] "
                         "read/write, .size(), by-reference / by-value to namespace functions, assignment from a function result",
        "strict_global_types": "a global of an unknown (struct) type raises FbbNotModelled at construction",
        "fbcap_adapter": "ecco_fbcap:: generic adapter over registry/fallback_capture.py: constants, enums, functions, POD "
                         "types, array aliases; a missing name raises FbbNotModelled",
        "byte_image_helpers": "ecco_fallback:: / ecco_fbdurable:: encode / decode / records_equal / bytes_equal and the pure "
                              "FB-A helpers (std::array<uint8_t, N> byte images instead of struct globals)",
        "marker_probes": "ecco_durable::ValidMarker probes through read_direct_t over the DirectNvs "
                         "(key = FNV-1 32 of the tag) with every two-step read side effect",
        "random_uint32": "random_uint32() with a seedable per-sim RNG (rng_seed, random_values, random_log)",
        "modbus_handlers": "Modbus handlers see values.size() / values[i] / exception_code; all five outcomes; per-call "
                           "outcomes (queue_frames / outcome_fn); strict outcomes",
        "deferred_frames": "deferred Modbus delivery on a hub model: queued, on the wire, delivered later (also late, with no "
                           "script running); tx_buffer_empty / tx_blocked follow the frames",
        "foreign_frames": "injectable foreign frames, a held bus and a held foreign script (a configuration poll in flight)",
        "async_scripts": "ESPHome-shaped scripts: script.execute returns at the first park; mode: single drops re-entry; "
                         "is_running() is truthful; button presses are automations",
        "interval_scheduler": "generic interval scheduler: period, startup_delay, declaration order, phase, scheduled "
                              "re-arm, runs while a script is parked, millis() wrap",
        "injectable_events": "at / after / at_press / at_bank / at_foreign_frame / at_power_cut / power_cut_when / reboot",
        "event_timeline": "sim.events and sim.event_hook cover Modbus reads and deliveries, direct-NVS operations and task "
                          "events in one ordered timeline",
        "safety_marks": "mark() / since(): zero Modbus writes, zero NVS sets, zero ecco_durable commits, exact read list",
        "transpiler_gaps": "casts, static_cast, constexpr, while / do / for / continue / break, local arrays, sizeof, "
                           "std::string +, compound assignment, ++ --, static_assert, switch blocks",
        "unsigned_wrap": "uint32_t / uint64_t values wrap like C (millis() - x, typed globals / locals / casts)",
        "strictness": "everything unmodelled raises FbbNotModelled: unknown identifier, `using`, static local, (char), "
                      "reinterpret_cast, unknown entity member, unknown outcome, non-single script mode",
    }
    # FB-B2: asserted by registry/tests/test_fallback_save_harness.py (FbbSim.CAPABILITIES stays the FB-B1 set that
    # test_fallback_capture_harness.py asserts)
    CAPABILITIES_FBB2 = {
        "string_ref": "esphome::StringRef api-action variables: size / str() / c_str() NOT NUL-terminated (reads on into the "
                      "next protobuf bytes) / starts_with / compare / find / substr / operator[] / == / != / + / implicit std::string",
        "call_api": "call_api(name, **vars): an api action by name, variables as StringRef, its then: (lambda / if with a lambda "
                    "condition / script.execute) on the same scheduler; returns the Task; strict on unknown / missing / extra / "
                    "mistyped variables",
        "template_switch": "template switches: turn_on()/turn_off()/toggle() run turn_on_action / turn_off_action every time then "
                           "publish when optimistic, publish_state deduplicates, on_turn_on / on_turn_off / on_state, restore "
                           "ALWAYS_OFF at boot, a reboot re-arms nothing",
        "operator_events": "operator_switch / at_operator_switch / at_api / operator_press: what Home Assistant does (a switch "
                           "flip, an action call, a button press) at a chosen instant, on the same timeline as everything else",
        "nvs_set_log": "DirectNvs.sets = every set_blob as (key, bytes, result); DirectNvs.before_op = a hook before every NVS "
                       "operation (cut BEFORE the FBP set)",
        "fb_write_audit": "Since.fb_sets / violations_fb(): zero Modbus writes, no set to a non-FB key (FBS never), the FB sets "
                          "exactly the expected ordered list (FBW then FBP) with exactly the expected bytes",
        "fbsave_adapter": "ecco_fbsave:: resolved by introspection over registry/fallback_save.py (lazy; a missing mirror raises "
                          "FbbNotModelled only when a lambda names it)",
        "string_mutators": "std::string assign / append / clear / push_back / pop_back / erase / resize / insert, std::string(ptr, n), "
                           "std::string(StringRef), ends_with / starts_with / rfind / front / back",
        "durable_adapter_additions": "MirrorRecords{}, seal_provision, validate_transition, decimal_key, IDF_* / WIT_DEFECT_* / "
                                     "RULE_NONE through ecco_fbdurable::",
    }

    def __init__(self, firmware: dict, nvs: DirectNvs | None = None, tick_ms: int = 10, *, fbcap=None, fbsave=None):
        arrays = {}
        for g in firmware["globals"]:
            ctype = g["type"]
            if ctype in KNOWN_SCALAR_CTYPES or ctype in FB_RECORD_CTYPES:
                continue
            arr = parse_array_ctype(ctype)
            if arr is None:
                raise FbbNotModelled(f"global {g['id']} has type {ctype!r} the FB-B harness does not model")
            arrays[g["id"]] = arr
        super().__init__(firmware)
        self._fbcap_spec = fbcap
        self._fbsave_spec = fbsave
        self._switches = {sw["id"]: sw for sw in firmware.get("switch") or [] if isinstance(sw, dict) and sw.get("id")}
        self.D = FbbDurable(self, fbcap, fbsave)
        self.fb_globals = frozenset(g["id"] for g in firmware["globals"] if g["type"] in FB_RECORD_CTYPES)
        self.array_globals = dict(arrays)
        for g in firmware["globals"]:
            if g["type"] in FB_RECORD_CTYPES:
                if g.get("initial_value") not in (None, "{}", ""):
                    raise FbbNotModelled(f"global {g['id']}: FB record initial_value {g.get('initial_value')!r}")
                self.g[g["id"]] = FbRecord(FB_RECORD_CTYPES[g["type"]])
            elif g["id"] in arrays:
                if g.get("initial_value") not in (None, "{}", ""):
                    raise FbbNotModelled(f"global {g['id']}: array initial_value {g.get('initial_value')!r} "
                                         "(only value-initialisation - omit initial_value - is modelled)")
                self.g[g["id"]] = FbArray(*arrays[g["id"]])
        # `self.nvs` stays _dump_sim's tag-keyed ecco_durable record store; the
        # FB keys live in the direct store the EspNvs adapter binds to.
        self.nvs_direct = nvs if nvs is not None else DirectNvs()
        self.write_latch = fd.WriteLatch()
        self.hub = HubModel()
        self.hub.clock = self
        self.background: list = []
        self.tick_ms = tick_ms
        self._engine_init()
        # Entity states as ESPHome has them right after boot (a plain Sim models every never-published entity as
        # NaN, which is TRUTHY - `!id(arm).state` would be false): a text sensor is the EMPTY std::string until its
        # first publish and a template binary sensor `false` (has_state() stays false for both); a template switch
        # holds its restore_mode boot value (ALWAYS_OFF / RESTORE_DEFAULT_OFF off, ALWAYS_ON / RESTORE_DEFAULT_ON on).
        for ts in firmware.get("text_sensor") or []:
            if ts.get("id"):
                self.ent(ts["id"]).state = FCStr("")
        for bs in firmware.get("binary_sensor") or []:
            if bs.get("id"):
                self.ent(bs["id"]).state = False
        for sw in firmware.get("switch") or []:
            mode = str(sw.get("restore_mode", "RESTORE_DEFAULT_OFF"))
            if sw.get("id") and mode != "DISABLED":
                boot_state = mode in ("ALWAYS_ON", "RESTORE_DEFAULT_ON", "RESTORE_INVERTED_DEFAULT_ON")
                self.ent(sw["id"]).set(boot_state)
                # ESPHome's setup() turns the switch to its boot value (publish_state): the Deduplicator already holds it, so a
                # later turn_off() of an ALWAYS_OFF switch publishes nothing. (Its turn_on_action / turn_off_action are NOT run
                # at boot in this model.)
                self.ent(sw["id"])._pub_dedup = boot_state

    # -- the direct NVS feeds the ONE ordered event timeline ----------------------------------
    @property
    def nvs_direct(self) -> DirectNvs:
        return self._nvs_direct

    @nvs_direct.setter
    def nvs_direct(self, nvs: DirectNvs) -> None:
        self._nvs_direct = nvs
        nvs.listener = self._log_event

    def ent(self, name):
        if name not in self.entities:
            self.entities[name] = FbbEntity(self, name)
        return self.entities[name]

    def set_global(self, name, value):
        if name in self.fb_globals:
            if not isinstance(value, FbRecord) or value._kind != FB_RECORD_CTYPES[self.gtypes[name]]:
                raise FbbNotModelled(f"assignment of a non-{self.gtypes[name]} to {name}")
            self.g[name] = value.copy()
            return
        if name in self.array_globals:
            if not isinstance(value, (list, tuple)) or len(value) != self.array_globals[name][1]:
                raise FbbNotModelled(f"assignment of {type(value).__name__}"
                                     f"{'' if not isinstance(value, (list, tuple)) else f' of {len(value)} elements'} to "
                                     f"{self.gtypes[name]} {name}")
            self.g[name].assign_from(value)  # in place: a reference to the array sees the new value
            return
        super().set_global(name, value)

    def incdec_g(self, name, delta, post):
        old = self.g[name]
        self.set_global(name, old + delta)
        return old if post else self.g[name]

    def seed_rng(self, seed: int) -> None:
        super().seed_rng(seed)
        self.sched_rng = random.Random(int(seed) ^ 0x5CED)

    def compile(self, code, params=()):
        code = ds.substitute(code, self.subs)
        code = rewrite_fb_namespaces(code)
        key = ("fbb", code, tuple(params))
        fn = self._fn_cache.get(key)
        if fn is None:
            try:
                src = FbbTranspiler(self.gtypes, params, self.fb_globals, self.array_globals).translate(code)
            except FbbNotModelled:
                raise
            except ds.Unsupported as e:
                raise FbbNotModelled(str(e)) from e
            if self._recovery_evidence is None:
                self._recovery_evidence = ds.RecoveryEvidenceNS()
            env = {"math": ds.math, "wrap": ds.wrap, "CStr": FCStr, "c_div": c_div_t, "c_mod": c_mod_t,
                   "c_format": ds.c_format, "c_snprintf_at": ds.c_snprintf_at, "D": self.D,
                   "R": self._recovery_evidence, "U32": U32, "U64": U64, "FbArray": FbArray, "mkarr": mkarr,
                   "cast_t": cast_t, "_S": _S, "incdec_l": incdec_l, "incdec_idx": incdec_idx, "NPOS": NPOS,
                   "c_to_string": c_to_string, "static_assert_fail": static_assert_fail, "str_mut": str_mut,
                   "str_from": str_from}
            exec(src, env)  # noqa: S102 - transpiled from repository firmware / test source
            fn = env["_f"]
            fn._src = src
            self._fn_cache[key] = fn
        return fn

    def _step(self) -> None:
        self._pump(self.now_ms + self.tick_ms)
        self.hub.tick(self.now_ms)
        for task in list(self.background):
            task(self)

    def _condition(self, body, local):
        cond = body.get("condition", body) if isinstance(body, dict) else body
        if not (isinstance(cond, dict) and set(cond) == {"lambda"}):
            raise FbbNotModelled(f"wait_until condition {cond!r}")
        return bool(self.run_lambda(cond["lambda"], local, params=tuple((local or {}).keys())))

    def run_actions(self, actions, local=None):
        for action in actions or []:
            (kind, body), = action.items()
            if kind == "wait_until":
                timeout = duration_ms(body["timeout"]) if isinstance(body, dict) and "timeout" in body else None
                waited = 0
                while not self._condition(body, local):
                    if timeout is not None and waited >= timeout:
                        break
                    if waited >= self.MAX_WAIT_MS:
                        raise FbbNotModelled("wait_until without timeout never became true")
                    self._step()
                    waited += self.tick_ms
            elif kind == "delay":
                end = self.now_ms + duration_ms(body)
                while self.now_ms < end:
                    self._step()
            else:
                super().run_actions([action], local)

    # -- durable markers: one coherent picture for the boot lambda (legacy tag store) and REVIEW's probes (direct NVS) --
    @staticmethod
    def marker_bytes(magic: int, state: int, size: int = 8) -> bytes:
        raw = _MARKER.pack(int(magic), int(state))
        return raw if size == len(raw) else (raw + bytes(size))[:size]

    def seed_marker(self, tag: str, state: int, *, magic: int | None = None, direct: bool = True, legacy: bool = True,
                    crc_ok: bool = True, chunk_present: bool = True, size: int = 8) -> None:
        """Store an ecco_durable::ValidMarker for `tag` in the legacy tag-keyed store (what the boot
        lambda's load_record_status reads) and/or the direct NVS (what read_direct_t probes read).
        `legacy=False` / `direct=False` build a deliberate divergence (a ghost marker); `size != 8`
        stores a wrong-size blob; `crc_ok` / `chunk_present` apply the IDF read side effects."""
        magic = ds.Durable.VALID_MARKER_MAGIC if magic is None else int(magic)
        if legacy:
            self.nvs[tag] = ds.Record("ValidMarker", magic, int(state))
        if direct:
            self.nvs_direct.put(fp.tag_key_fnv1_32(tag), self.marker_bytes(magic, state, size), crc_ok, chunk_present)

    def mirror_markers_to_direct(self) -> int:
        """Copy every legacy ValidMarker record into the direct NVS (after a test filled sim.nvs)."""
        n = 0
        for tag, rec in self.nvs.items():
            if isinstance(rec, ds.Record) and rec._kind == "ValidMarker":
                self.nvs_direct.put(fp.tag_key_fnv1_32(tag), self.marker_bytes(rec.magic, rec.state))
                n += 1
        return n

    # -- boot ---------------------------------------------------------------------------------
    def boot_lambdas(self) -> list:
        then = ((self.fw.get("esphome") or {}).get("on_boot") or {}).get("then") or []
        return then

    def run_boot(self, select=None) -> None:
        """Run the firmware's on_boot actions in order (all, or the listed indexes). Only `lambda`
        actions are modelled; anything else raises."""
        then = self.boot_lambdas()
        picks = range(len(then)) if select is None else ([select] if isinstance(select, int) else list(select))
        for i in picks:
            action = then[i]
            if set(action) != {"lambda"}:
                raise FbbNotModelled(f"on_boot action {i}: {sorted(action)} (only lambdas are modelled)")
            self.run_lambda(action["lambda"])

    def reboot(self, *, boot_ms: int = 1_000_000, reseed: bool = True, resolve_nvs: bool = True) -> "FbbSim":
        """A power cycle: a NEW sim over the same firmware with all RAM reset (globals, scripts, intervals,
        entity states, the event timeline), `millis()` restarting at `boot_ms`, and what survives:
        the register bank (the inverter keeps running), the legacy tag-keyed records and the direct NVS
        (resolved per its pending write faults when `resolve_nvs`). The Modbus mode / frame latency /
        outcome hooks are carried; the RNG reseeds to seed+1 (a different boot salt) unless reseed=False."""
        new = type(self)(self.fw, nvs=self.nvs_direct.reboot() if resolve_nvs else self.nvs_direct,
                         tick_ms=self.tick_ms, fbcap=self._fbcap_spec, fbsave=self._fbsave_spec)
        new.now_ms = int(boot_ms)
        new.bank = dict(self.bank)
        new.nvs = {k: v.copy() for k, v in self.nvs.items()}
        for attr in ("ntp_valid", "epoch", "hour", "minute", "outcome_fn", "read_override_fn", "modbus_mode",
                     "frame_latency_ms", "exception_code"):
            setattr(new, attr, getattr(self, attr))
        new.seed_rng(self.rng_seed + 1 if reseed else self.rng_seed)
        return new
