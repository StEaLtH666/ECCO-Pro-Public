"""Behavioural simulator for the Manual Dump-to-Grid V1 firmware scripts.

Executes the REAL firmware source - the parsed ESPHome action trees of the
Dump scripts / watchdog / sensor on_value hooks, and every lambda inside
them - against an in-memory inverter register bank, an in-memory NVS store
and scripted Modbus outcomes. Built for the 2026-09-26 pre-live hardening
pass because registry/tests/_free_power_action_sim.py's deliberately tiny
interpreter cannot execute Dump's lambdas (braceless ifs, loops, struct
records, snprintf, durable commits).

How lambdas run: a small C++-subset -> Python transpiler (tokenizer, Pratt
expression parser, statement parser). It supports exactly the constructs
the Dump code uses and RAISES `Unsupported` on anything else, so a firmware
change that introduces new syntax fails loudly instead of being guessed at.
C semantics that matter here are modelled explicitly: integer division and
modulo truncate toward zero, casts wrap (`(uint32_t)`, `(int32_t)`,
`(uint16_t)`), assignments to typed globals/locals wrap to their declared
width - so millis() rollover arithmetic behaves as it does on the ESP32.

Deliberate simplifications (documented, not hidden):
  - Scripts run synchronously: `script.execute` runs the target script to
    completion before returning (ESPHome would interleave at the first
    async action). `mode: single` re-entry is modelled (a second execute
    while running is dropped, as ESPHome does).
  - A Modbus operation's handler runs immediately when the operation action
    executes; `wait_until` then sees the terminal flag. A "timeout" outcome
    runs no handler, so the script's own bounded-wait fallback lambda runs.
  - Entities are plain objects whose state the test sets directly.

No I/O beyond reading the firmware file, no hardware, no ESPHome toolchain.
"""

from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import _sg01_journal_model as jm
import _dump_v2_evidence_model as dv2


class Unsupported(Exception):
    pass


# ---------------------------------------------------------------------------
# Firmware loading
# ---------------------------------------------------------------------------
class _Loader(yaml.SafeLoader):
    pass


class LambdaStr(str):
    """A `!lambda` scalar - distinguishes a templated script parameter from a
    literal string parameter."""


def _tagged(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        return LambdaStr(value) if suffix == "lambda" else value
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_Loader.add_multi_constructor("!", _tagged)


# The firmware loader: the same safe loader, backed by libyaml when PyYAML ships it. yaml.CSafeLoader is libyaml's scanner and
# parser joined to yaml.SafeLoader's own SafeConstructor and Resolver classes, so every value, type and tag is still built by the
# same Python code; only the scanning is native, several times faster on the 1.28 MB firmware that the registry suites parse
# over a thousand times per run. Never an unsafe loader, and nothing is cached: every call parses its own text. Without libyaml
# it IS _Loader. registry/tests/test_firmware_yaml_loader.py proves the two build identical trees (values, exact types incl.
# LambdaStr, key order, alias sharing) on the firmware, real firmware mutants and a tag/type edge corpus, and fail alike.
if getattr(yaml, "__with_libyaml__", False):
    class _CLoader(yaml.CSafeLoader):
        pass

    _CLoader.add_multi_constructor("!", _tagged)
    FIRMWARE_LOADER = _CLoader
else:
    FIRMWARE_LOADER = _Loader


def load_firmware(path: Path) -> dict:
    return load_firmware_text(path.read_text(encoding="utf-8"))


def load_firmware_text(text: str) -> dict:
    """Same as load_firmware(), from source text - used by the mutation
    (sensitivity) checks to run scenarios against deliberately broken
    in-memory copies of the firmware."""
    doc = yaml.load(text, Loader=FIRMWARE_LOADER)
    subs = {k: str(v) for k, v in (doc.get("substitutions") or {}).items()}
    doc["_substitutions"] = subs
    doc["_text"] = text
    return doc


def substitute(code: str, subs: dict) -> str:
    def rep(m):
        name = m.group(1)
        if name not in subs:
            raise Unsupported(f"unknown substitution ${{{name}}}")
        return subs[name]

    return re.sub(r"\$\{(\w+)\}", rep, code)


# ---------------------------------------------------------------------------
# Runtime value helpers (C semantics)
# ---------------------------------------------------------------------------
_WIDTH = {"uint8_t": (8, False), "uint16_t": (16, False), "uint32_t": (32, False), "unsigned": (32, False),
          "int32_t": (32, True), "int": (32, True), "uint64_t": (64, False), "size_t": (32, False)}


def wrap(value, ctype: str):
    if ctype in ("float", "double"):
        return float(value)
    if ctype == "bool":
        return bool(value)
    if ctype in _WIDTH:
        bits, signed = _WIDTH[ctype]
        if isinstance(value, float):
            if math.isnan(value):
                raise Unsupported("NaN converted to integer")
            value = int(value)  # C truncation toward zero
        value = int(value) & ((1 << bits) - 1)
        if signed and value >= 1 << (bits - 1):
            value -= 1 << bits
        return value
    return value


class CStr(str):
    def c_str(self):
        return self

    def empty(self):
        return len(self) == 0

    def size(self):
        return len(self)


class Vec(list):
    """FB-B1: the `values` of a Modbus on_response handler as C++ code sees
    it (a vector-like): a list that also answers `.size()` / `.data()` /
    `.empty()`. Behaves exactly like the plain list it replaces."""

    def size(self):
        return len(self)

    def data(self):
        return self

    def empty(self):
        return len(self) == 0


def c_div(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a / b
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def c_mod(a, b):
    return a - c_div(a, b) * b


def c_format(fmt: str, *args) -> CStr:
    # Length modifiers (`%016llX` - SG-01 Phase 5, the recovery evidence ID)
    # carry no information for Python's arbitrary-precision ints.
    py = re.sub(r"%(0?\d*)(?:ll|l|h|hh)([diuxX])", r"%\1\2", fmt)
    py = re.sub(r"%(\d*)u", r"%\1d", py)
    return CStr(py % tuple(int(a) if isinstance(a, bool) else a for a in args))


def c_snprintf_at(L: dict, buf: str, offset: int, size: int, fmt: str, *args) -> int:
    """`snprintf(buf + offset, size, fmt, ...)` used as an EXPRESSION (the
    firmware's `n += snprintf(b + n, sizeof(b) - n, ...)` append idiom):
    writes at most size-1 characters at `offset` and returns the length the
    full output WOULD have had - C99 semantics, truncation included."""
    text = c_format(fmt, *args)
    if size <= 0 or offset < 0:
        raise Unsupported("snprintf with a non-positive size or negative offset")
    L[buf] = CStr(str(L[buf])[:offset] + text[:size - 1])
    return len(text)


# ---------------------------------------------------------------------------
# Durable records (ecco_durable namespace)
# ---------------------------------------------------------------------------
_RECORD_FIELDS = {
    "ValidMarker": ["magic", "state"],
    # Dump V2 (ownership evidence): V1 plus reg_dump_power_pending, same
    # 24-byte size. The retired V1 layout is its own kind, so a test can put
    # a legacy V1 record in NVS - see Durable.load_record()'s same-size
    # reinterpretation below. Layouts: _dump_v2_evidence_model.py.
    dv2.V2_KIND: list(dv2.V2_FIELDS),
    dv2.V1_KIND: list(dv2.V1_FIELDS),
    "DumpToGridRetryState": ["operator_needed"],
    # Free Power / Register 244 records (SG-01 Phase 0): the durable records
    # firmware/include/ecco_durable_snapshot.h already defines. Field order
    # is the header's struct order.
    "FreePowerSnapshotData": ["end_epoch", "active_persisted", "restore_requested", "reg230", "reg232",
                              "reg256", "reg257", "reg258", "reg259", "reg260", "reg261",
                              "reg268", "reg269", "reg270", "reg271", "reg272", "reg273",
                              "reg274", "reg275", "reg276", "reg277", "reg278", "reg279",
                              "reg230_intended", "reg_tou_power_intended", "reg244_lease_context_plus1"],
    "FreePowerRetryState": ["operator_needed"],
    "Reg244SnapshotData": ["value"],
    # SG-01 Free Power START journal (production since SG-01 Phase 1/2).
    # Schema/semantics mirror live in _sg01_journal_model.py.
    jm.JOURNAL_KIND: list(jm.JOURNAL_FIELDS),
    # A stored blob whose size does not match the requested record type.
    "_WrongSizeBlob": [],
}


class Record:
    def __init__(self, kind: str, *init):
        object.__setattr__(self, "_kind", kind)
        fields = _RECORD_FIELDS[kind]
        for i, f in enumerate(fields):
            object.__setattr__(self, f, init[i] if i < len(init) else 0)

    def copy(self):
        r = Record(self._kind)
        for f in _RECORD_FIELDS[self._kind]:
            object.__setattr__(r, f, getattr(self, f))
        return r

    def __setattr__(self, name, value):
        if name not in _RECORD_FIELDS[self._kind]:
            raise Unsupported(f"{self._kind} has no field {name}")
        object.__setattr__(self, name, value)


class Durable:
    MARKER_CLEAR = 0
    MARKER_RESTORE_REQUIRED = 1
    MARKER_RESTORE_VERIFIED_PENDING_CLEAR = 2
    VALID_MARKER_MAGIC = 0x45434356
    # Dump V2 (ownership evidence): the data tag alias points at V2; V1 is
    # the retired, never-read historical tag. Mirrors the header - pinned
    # against it by test_dump_v2_ownership_evidence.py.
    DUMP_TO_GRID_DATA_TAG_V1 = dv2.V1_TAG
    DUMP_TO_GRID_DATA_TAG_V2 = dv2.V2_TAG
    DUMP_TO_GRID_DATA_TAG = dv2.V2_TAG
    DUMP_V1_TOMBSTONE_REG244 = dv2.V1_TOMBSTONE_REG244
    DUMP_TO_GRID_VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1"
    DUMP_TO_GRID_RETRY_TAG = "ecco_dump_to_grid_retry_state_v1"
    # Free Power / Register 244 (SG-01 Phase 0) - mirror the header's constants.
    FREE_POWER_DATA_TAG = "ecco_free_power_snapshot_data_v4"
    FREE_POWER_VALID_TAG = "ecco_free_power_snapshot_valid_v1"
    FREE_POWER_RETRY_TAG = "ecco_free_power_retry_state_v1"
    REG244_DATA_TAG = "ecco_reg244_snapshot_data_v1"
    REG244_VALID_TAG = "ecco_reg244_snapshot_valid_v1"
    # SG-01 START journal - mirrors the header's constants (SG-01 Phase 1).
    FREE_POWER_START_JOURNAL_TAG = jm.JOURNAL_TAG
    FREE_POWER_START_JOURNAL_MAGIC = jm.JOURNAL_MAGIC
    FREE_POWER_START_JOURNAL_MASK_B1 = jm.JOURNAL_MASK_B1
    FREE_POWER_START_JOURNAL_MASK_B2 = jm.JOURNAL_MASK_B2
    FREE_POWER_START_JOURNAL_MASK_B3 = jm.JOURNAL_MASK_B3
    FREE_POWER_START_JOURNAL_MASK_B4 = jm.JOURNAL_MASK_B4
    FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED = jm.JOURNAL_FLAG_START_VERIFIED
    FREE_POWER_START_JOURNAL_KNOWN_FLAGS = jm.JOURNAL_KNOWN_FLAGS

    def __init__(self, sim: "Sim"):
        self.sim = sim

    def key_for(self, tag):
        return tag

    def commit_record(self, key, record):
        """Mirrors ecco_durable::commit_record(): a failed commit leaves the
        previously stored record untouched. Every ATTEMPT is logged in
        `nvs_commits` (failed ones included), like the pre-existing model."""
        sim = self.sim
        sim.nvs_commits.append((key, record.copy()))
        attempt = sum(1 for k, _r in sim.nvs_commits if k == key)
        if attempt in sim.nvs_fail_attempts.get(key, ()):
            sim._log_event(("commit", key, record.copy(), False))
            return False
        if sim.nvs_fail_next.get(key, 0) > 0:
            sim.nvs_fail_next[key] -= 1
            sim._log_event(("commit", key, record.copy(), False))
            return False
        if key in sim.nvs_fail_tags or sim.nvs_fail_all:
            sim._log_event(("commit", key, record.copy(), False))
            return False
        sim.nvs[key] = record.copy()
        sim._log_event(("commit", key, record.copy(), True))
        return True

    def load_record(self, key, record):
        """Mirrors ecco_durable::load_record(): false when nothing is stored
        under `key` (first boot) or the stored size does not match the
        requested type; NEVER validates content (a stored bad-magic journal
        still loads - classifying it is the firmware's job)."""
        sim = self.sim
        sim.nvs_loads.append(key)
        if key in sim.nvs_fail_load_tags or sim.nvs_fail_load_all:
            sim._log_event(("load", key, False))
            return False
        stored = sim.nvs.get(key)
        if stored is not None and stored._kind != record._kind and stored._kind in dv2.PACK                 and record._kind in dv2.UNPACK:
            # Dump V2: the real load_record() checks ONLY the stored size.
            # Dump V1 and V2 are both 24 bytes, so a record of one kind under
            # a key read as the other is NOT rejected - its bytes are
            # reinterpreted (V1's tail padding becomes V2's pending field).
            # Only the tag bump keeps this from happening in the firmware.
            for f, v in dv2.UNPACK[record._kind](dv2.PACK[stored._kind](stored)).items():
                object.__setattr__(record, f, v)
            sim._log_event(("load", key, True))
            return True
        if stored is None or stored._kind != record._kind:
            sim._log_event(("load", key, False))
            return False
        for f in _RECORD_FIELDS[record._kind]:
            object.__setattr__(record, f, getattr(stored, f))
        sim._log_event(("load", key, True))
        return True

    # SG-06: ecco_durable::LoadStatus / load_record_status(). The same load
    # as load_record() (LOAD_OK exactly when it returns true); a failure is
    # then classified the way the header's nvs_get_blob() length probe does:
    # an injected load failure (nvs_fail_load_tags / nvs_fail_load_all) is an
    # NVS READ ERROR, nothing stored is ABSENT, and a record of another kind
    # (a different stored size) is WRONG_SIZE.
    LOAD_OK = 0
    LOAD_ABSENT = 1
    LOAD_WRONG_SIZE = 2
    LOAD_READ_ERROR = 3

    def load_record_status(self, key, record):
        sim = self.sim
        if self.load_record(key, record):
            return self.LOAD_OK
        if key in sim.nvs_fail_load_tags or sim.nvs_fail_load_all:
            return self.LOAD_READ_ERROR
        if sim.nvs.get(key) is None:
            return self.LOAD_ABSENT
        return self.LOAD_WRONG_SIZE

    @staticmethod
    def comms_backoff_ms(n):
        table = [15000, 30000, 60000, 120000, 300000]
        return table[max(0, min(len(table) - 1, n - 1))]

    def ValidMarker(self, *init):
        return Record("ValidMarker", *init)

    def DumpToGridSnapshotData(self, *init):
        return Record(dv2.V2_KIND, *init)

    def DumpToGridSnapshotDataV1(self, *init):
        """The retired V1 layout - only for putting a legacy record in NVS;
        the firmware never constructs one."""
        return Record(dv2.V1_KIND, *init)

    def DumpToGridRetryState(self, *init):
        return Record("DumpToGridRetryState", *init)

    def FreePowerSnapshotData(self, *init):
        return Record("FreePowerSnapshotData", *init)

    def FreePowerRetryState(self, *init):
        return Record("FreePowerRetryState", *init)

    def Reg244SnapshotData(self, *init):
        return Record("Reg244SnapshotData", *init)

    def FreePowerStartJournal(self, *init):
        """SG-01 START journal record. Default-constructed fields are all
        zero, i.e. magic 0 - NOT valid until the firmware stamps it."""
        return Record(jm.JOURNAL_KIND, *init)

    # SG-01 Phase 1 header functions, executed through the Python mirror.
    # The C++ implementations are pinned to the same golden vectors at
    # compile time (static_assert in ecco_durable_snapshot.h), which
    # registry/tests/test_sg01_journal_phase1_2.py re-derives here.
    @staticmethod
    def free_power_start_journal_binding(snapshot):
        if getattr(snapshot, "_kind", None) != "FreePowerSnapshotData":
            raise Unsupported("free_power_start_journal_binding() takes a FreePowerSnapshotData")
        return jm.journal_binding(snapshot)

    @staticmethod
    def free_power_start_journal_mask_valid(mask):
        return int(mask) in jm.JOURNAL_VALID_START_ATTEMPTED_MASKS

    @staticmethod
    def free_power_start_journal_valid(journal, expected_binding):
        if getattr(journal, "_kind", None) != jm.JOURNAL_KIND:
            raise Unsupported("free_power_start_journal_valid() takes a FreePowerStartJournal")
        return jm.journal_valid(journal, expected_binding)


class RecoveryEvidenceNS:
    """firmware/include/ecco_recovery_evidence.h (the Free Power recovery
    evidence fingerprint), executed through its offline Python mirror
    registry/free_power_recovery_evidence.py - the same mirror
    registry/tests/test_free_power_recovery_evidence.py pins to the header.
    Arguments are converted exactly like the C++ parameters (uint16_t /
    uint32_t implicit conversion). SG-01 Phase 5: lets the Review, Force
    Restore and Accept Current State scripts run in this simulator."""

    def __init__(self):
        import sys

        registry_dir = str(Path(__file__).resolve().parents[1])
        if registry_dir not in sys.path:
            sys.path.insert(0, registry_dir)
        import free_power_recovery_evidence as fpre

        self._fpre = fpre
        self.FNV64_OFFSET_BASIS = fpre.FNV64_OFFSET_BASIS
        self.FINGERPRINT_DOMAIN_TAG = CStr(fpre.FINGERPRINT_DOMAIN_TAG)

    def fnv1a64_update_str(self, h, s):
        return self._fpre.fnv1a64(str(s).encode("ascii"), wrap(h, "uint64_t"))

    def fnv1a64_update_u16le(self, h, v):
        return self._fpre.fnv1a64(wrap(v, "uint16_t").to_bytes(2, "little"), wrap(h, "uint64_t"))

    def fnv1a64_update_u32le(self, h, v):
        return self._fpre.fnv1a64(wrap(v, "uint32_t").to_bytes(4, "little"), wrap(h, "uint64_t"))


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Entity:
    def __init__(self, sim: "Sim", name: str):
        self._sim = sim
        self.name = name
        self.state = float("nan")
        self._has = False
        self.published: list = []

    def has_state(self):
        return self._has

    def set(self, value):
        """Test helper: set a value WITHOUT running on_value hooks."""
        self.state = value
        self._has = True

    def publish_state(self, value):
        if isinstance(value, str):
            value = CStr(value)
        self.state = value
        self._has = True
        self.published.append(value)
        self._sim.run_on_value(self.name, value)

    def turn_on(self):
        self.state = True

    def turn_off(self):
        self.state = False

    # `id(some_script).execute();` from inside a lambda - same semantics as
    # the `script.execute:` action (runs to completion, mode: single).
    def execute(self):
        if self.name not in self._sim.scripts:
            raise Unsupported(f"id({self.name}).execute() - not a script")
        self._sim.execute(self.name)

    # inverter_modbus
    def tx_buffer_empty(self):
        return self._sim.bus_idle

    def tx_blocked(self):
        return not self._sim.bus_idle


@dataclass
class TimeNow:
    valid: bool
    timestamp: int
    hour: int
    minute: int

    def is_valid(self):
        return self.valid

    def strftime(self, fmt):
        """ESPTime::strftime (UTC here) - the configuration / telemetry polls stamp their publishes."""
        return time.strftime(str(fmt), time.gmtime(self.timestamp))


class Clock(Entity):
    def now(self):
        return TimeNow(self._sim.ntp_valid, self._sim.epoch, self._sim.hour, self._sim.minute)


# ---------------------------------------------------------------------------
# C++ subset -> Python transpiler
# ---------------------------------------------------------------------------
_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>"(?:\\.|[^"\\])*")
      | (?P<chr>'(?:\\.|[^'\\])')
      | (?P<num>0[xX][0-9a-fA-F]+[uUlL]*|\d+\.\d*[fF]?|\d+[fF]|\d+[uUlL]*)
      | (?P<id>[A-Za-z_]\w*)
      | (?P<op>->|::|\+\+|--|&&|\|\||==|!=|<<=|>>=|<=|>=|\+=|-=|\*=|/=|%=|\^=|\|=|&=|<<|>>|[{}()\[\];,.?:<>=!+\-*/%&|^~])
    )""",
    re.X,
)

TYPES = {"bool", "int", "uint8_t", "uint16_t", "uint32_t", "int32_t", "float", "double", "auto", "char",
         "unsigned", "size_t", "uint64_t"}
CAST_TYPES = {"uint8_t", "uint16_t", "uint32_t", "int32_t", "int", "float", "unsigned", "double", "uint64_t",
              "size_t"}


def tokenize(code: str) -> list:
    code = re.sub(r"//[^\n]*", "", code)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    toks, pos = [], 0
    while pos < len(code):
        if code[pos:].strip() == "":
            break
        m = _TOKEN.match(code, pos)
        if not m or m.end() == pos:
            raise Unsupported(f"cannot tokenize near {code[pos:pos + 40]!r}")
        kind = m.lastgroup
        toks.append((kind, m.group(kind)))
        pos = m.end()
    return toks


class Transpiler:
    """Translates one lambda body into Python source for a function
    `def _f(S, L):` where S is the Sim and L the local scope dict."""

    def __init__(self, globals_types: dict, params: tuple = ()):
        self.gtypes = globals_types
        self.params = set(params)
        self.toks: list = []
        self.i = 0
        self.lines: list = []
        self.ltypes: dict = {}
        self.lambdas: set = set()
        self.char_array_sizes: dict = {}

    # -- token helpers --
    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else (None, None)

    def val(self, k=0):
        return self.peek(k)[1]

    def take(self, expect=None):
        tok = self.peek()
        if tok[0] is None:
            raise Unsupported("unexpected end of lambda")
        if expect is not None and tok[1] != expect:
            raise Unsupported(f"expected {expect!r}, got {tok[1]!r} near token {self.i}")
        self.i += 1
        return tok

    # -- entry --
    def translate(self, code: str) -> str:
        self.toks = tokenize(code)
        self.i = 0
        self.lines = []
        while self.peek()[0] is not None:
            self.stmt(1)
        if not self.lines:
            self.lines.append("    pass")
        return "def _f(S, L):\n" + "\n".join(self.lines)

    def emit(self, depth, text):
        self.lines.append("    " * depth + text)

    # -- statements --
    def block_or_stmt(self, depth):
        start = len(self.lines)
        if self.val() == "{":
            self.take("{")
            while self.val() != "}":
                self.stmt(depth)
            self.take("}")
        else:
            self.stmt(depth)
        if len(self.lines) == start:
            self.emit(depth, "pass")

    def is_decl(self):
        v = self.val()
        if v == "const":
            return True
        if v in TYPES and self.peek(1)[0] == "id" or (v in TYPES and self.val(1) == "*"):
            return True
        if v == "std" and self.val(1) == "::" and self.val(2) == "string" and self.peek(3)[0] == "id":
            return True
        if v == "ecco_durable" and self.val(1) == "::" and self.peek(3)[0] == "id":
            return True
        return False

    def stmt(self, depth):
        v = self.val()
        if v == "{":
            self.take("{")
            while self.val() != "}":
                self.stmt(depth)
            self.take("}")
            return
        if v == ";":
            self.take(";")
            return
        if v == "if":
            self.take("if")
            self.take("(")
            cond = self.expr()
            self.take(")")
            self.emit(depth, f"if {cond}:")
            self.block_or_stmt(depth + 1)
            if self.val() == "else":
                self.take("else")
                self.emit(depth, "else:")
                self.block_or_stmt(depth + 1)
            return
        if v == "for":
            self.take("for")
            self.take("(")
            if self.is_range_for():
                self.range_for(depth)
                return
            if self.val() in TYPES:
                ctype = self.take()[1]
            else:
                raise Unsupported("for-loop without a typed induction variable")
            name = self.take()[1]
            self.take("=")
            init = self.expr()
            self.take(";")
            self.ltypes[name] = ctype
            cond = self.expr()
            self.take(";")
            step_name = self.take()[1]
            op = self.take()[1]
            if step_name != name or op != "++":
                raise Unsupported("only `i++` for-loop steps are supported")
            self.take(")")
            self.emit(depth, f"L[{name!r}] = {init}")
            self.emit(depth, f"while {cond}:")
            self.block_or_stmt(depth + 1)
            # `break` inside the body is translated to a Python break; the
            # increment must therefore run at the END of each iteration and be
            # skipped by break - Python's while/else cannot express `continue`,
            # which the firmware does not use.
            self.emit(depth + 1, f"L[{name!r}] = L[{name!r}] + 1")
            return
        if v == "return":
            self.take("return")
            if self.val() == ";":
                self.take(";")
                self.emit(depth, "return None")
            else:
                e = self.expr()
                self.take(";")
                self.emit(depth, f"return {e}")
            return
        if v == "break":
            self.take("break")
            self.take(";")
            self.emit(depth, "break")
            return
        if v == "switch":
            self.switch(depth)
            return
        if self.is_decl():
            self.decl(depth)
            return
        # snprintf(buf, sizeof(buf), fmt, args...)
        if v == "snprintf":
            self.take("snprintf")
            self.take("(")
            buf = self.take()[1]
            self.take(",")
            self.expr()  # sizeof(...)
            args = []
            while self.val() == ",":
                self.take(",")
                args.append(self.expr())
            self.take(")")
            self.take(";")
            self.emit(depth, f"L[{buf!r}] = c_format({', '.join(args)})")
            return
        if v.startswith("ESP_LOG") if v else False:
            self.take()
            self.skip_parens()
            self.take(";")
            return
        self.expr_stmt(depth)

    # -- SG-01 Phase 5 additions (the Review / Force Restore / Accept Current
    # State scripts). Each supports ONE narrow shape and raises Unsupported on
    # anything wider, like the rest of this transpiler.
    def is_range_for(self):
        """After `for (`: a `:` at paren depth 0 before the first `;`."""
        depth, j = 0, self.i
        while j < len(self.toks):
            t = self.toks[j][1]
            if t == "(":
                depth += 1
            elif t == ")":
                if depth == 0:
                    return False
                depth -= 1
            elif t == ";" and depth == 0:
                return False
            elif t == ":" and depth == 0:
                return True
            j += 1
        return False

    def range_for(self, depth):
        """`for (char c : s)` / `for (const T &x : arr)` - element by value."""
        ctype = self.parse_type()
        if self.val() == "&":
            self.take("&")
        name = self.take()[1]
        self.take(":")
        seq = self.expr()
        self.take(")")
        self.ltypes[name] = ctype
        self.emit(depth, f"for L[{name!r}] in list({seq}):")
        self.block_or_stmt(depth + 1)

    def switch(self, depth):
        """`switch (e) { case K: ... break; ... default: ... break; }` with
        integer-constant labels and NO fall-through: every non-empty clause
        must end in `break;` (stacked labels with no statements between them
        share the next body)."""
        self.take("switch")
        self.take("(")
        subject = self.expr()
        self.take(")")
        self.take("{")
        tmp = f"__switch_{self.i}"
        self.emit(depth, f"L[{tmp!r}] = {subject}")
        clauses, labels, has_default = [], [], False
        while self.val() != "}":
            if self.val() == "case":
                self.take("case")
                labels.append(self.expr())
                self.take(":")
                continue
            if self.val() == "default":
                self.take("default")
                self.take(":")
                labels.append(None)
                continue
            if not labels:
                raise Unsupported("switch: statement before any case label")
            saved, self.lines = self.lines, []
            last_kw = None
            while self.val() not in ("break", "case", "default", "}"):
                last_kw = self.val()
                self.stmt(depth + 1)
            if self.val() == "break":
                self.take("break")
                self.take(";")
            elif last_kw != "return":
                # A clause ending in `return` cannot fall through (the Manual
                # TOU Load buttons' `default: ...; return;`); anything else can.
                raise Unsupported("switch: fall-through (clause does not end in break)")
            body, self.lines = self.lines or ["    " * (depth + 1) + "pass"], saved
            clauses.append((labels, body))
            has_default = has_default or None in labels
            labels = []
        if labels:
            raise Unsupported("switch: trailing label without a body")
        self.take("}")
        first = True
        for labels, body in [c for c in clauses if None not in c[0]] + [c for c in clauses if None in c[0]]:
            if None in labels:
                self.emit(depth, "else:" if not first else "if True:")
            else:
                cond = " or ".join(f"L[{tmp!r}] == ({k})" for k in labels)
                self.emit(depth, f"{'if' if first else 'elif'} {cond}:")
            self.lines.extend(body)
            first = False

    def lambda_def(self, depth, name):
        """`auto name = [](T a, const std::string &b) -> R { body }` - a
        CAPTURELESS lambda (so its body sees only its own parameters and
        locals, exactly as C++ enforces), callable later as `name(...)`."""
        self.take("[")
        if self.val() != "]":
            raise Unsupported("lambda with a capture list")
        self.take("]")
        self.take("(")
        pnames, ptypes = [], {}
        while self.val() != ")":
            ptype = self.parse_type()
            if self.val() in ("&", "*"):
                self.take()
            pname = self.take()[1]
            pnames.append(pname)
            ptypes[pname] = ptype
            if self.val() == ",":
                self.take(",")
        self.take(")")
        if self.val() == "->":
            self.take("->")
            self.parse_type()
        fn = f"__lambda_{name}"
        saved_types, saved_params = self.ltypes, self.params
        self.ltypes, self.params = dict(ptypes), set(pnames)
        self.emit(depth, f"def {fn}(S, *__args):")
        self.emit(depth + 1, f"L = dict(zip({pnames!r}, __args))")
        self.take("{")
        start = len(self.lines)
        while self.val() != "}":
            self.stmt(depth + 1)
        self.take("}")
        if len(self.lines) == start:
            self.emit(depth + 1, "pass")
        self.ltypes, self.params = saved_types, saved_params
        self.lambdas.add(name)
        self.emit(depth, f"L[{name!r}] = (lambda *a: {fn}(S, *a))")

    def skip_parens(self):
        self.take("(")
        depth = 1
        while depth:
            t = self.take()[1]
            if t == "(":
                depth += 1
            elif t == ")":
                depth -= 1

    def parse_type(self):
        parts = []
        if self.val() == "const":
            self.take()
        if self.val() == "std":
            self.take("std")
            self.take("::")
            parts.append("std::" + self.take()[1])
        elif self.val() == "ecco_durable":
            self.take("ecco_durable")
            self.take("::")
            parts.append("ecco_durable::" + self.take()[1])
        else:
            parts.append(self.take()[1])
        ptr = False
        while self.val() == "*":
            self.take("*")
            ptr = True
        return parts[0] + ("*" if ptr else "")

    def decl(self, depth):
        ctype = self.parse_type()
        while True:
            name = self.take()[1]
            if self.val() == "[":
                self.take("[")
                if self.val() != "]":
                    dim = self.expr()
                    if ctype == "char" and dim.isdigit():
                        self.char_array_sizes[name] = int(dim)
                self.take("]")
                if self.val() == "=":
                    self.take("=")
                    self.take("{")
                    elems = []
                    while self.val() != "}":
                        elems.append(self.expr())
                        if self.val() == ",":
                            self.take(",")
                    self.take("}")
                    self.emit(depth, f"L[{name!r}] = [{', '.join(elems)}]")
                else:
                    self.emit(depth, f"L[{name!r}] = CStr('')" if ctype == "char" else f"L[{name!r}] = []")
                self.ltypes[name] = ctype
            elif self.val() == "{":
                self.take("{")
                args = []
                while self.val() != "}":
                    args.append(self.expr())
                    if self.val() == ",":
                        self.take(",")
                self.take("}")
                if not ctype.startswith("ecco_durable::"):
                    raise Unsupported(f"brace-init of {ctype}")
                self.emit(depth, f"L[{name!r}] = D.{ctype.split('::')[1]}({', '.join(args)})")
                self.ltypes[name] = ctype
            elif self.val() == "=" and self.val(1) == "[" and ctype == "auto":
                self.take("=")
                self.lambda_def(depth, name)
                self.ltypes[name] = "lambda"
            elif self.val() == "=":
                self.take("=")
                e = self.expr()
                self.ltypes[name] = ctype
                self.emit(depth, f"L[{name!r}] = {self.wrap_expr(e, ctype)}")
            else:
                self.ltypes[name] = ctype
                self.emit(depth, f"L[{name!r}] = None")
            if self.val() == ",":
                self.take(",")
                continue
            self.take(";")
            return

    @staticmethod
    def wrap_expr(e, ctype):
        base = ctype.replace("*", "")
        if base in _WIDTH or base in ("bool", "float", "double"):
            return f"wrap({e}, {base!r})"
        if base == "std::string":
            return f"CStr({e})"
        return e

    def expr_stmt(self, depth):
        # Assignment forms need their target, not a value.
        start = self.i
        target = self.lvalue()
        op = self.val()
        if op in ("=", "+=", "-=", "|=", "&="):
            self.take()
            rhs = self.expr()
            self.take(";")
            if op != "=":
                rhs = f"({target[1]}) {op[0]} ({rhs})"
            self.emit(depth, self.assign(target, rhs))
            return
        if op in ("++", "--"):
            self.take()
            self.take(";")
            self.emit(depth, self.assign(target, f"({target[1]}) {'+' if op == '++' else '-'} 1"))
            return
        # plain expression statement (calls)
        self.i = start
        e = self.expr()
        self.take(";")
        self.emit(depth, e)

    def lvalue(self):
        """Parses an assignable target: returns (kind, read_expr, write_fmt)."""
        if self.val() == "id" and self.val(1) == "(":
            self.take("id")
            self.take("(")
            name = self.take()[1]
            self.take(")")
            if self.val() in (".", "->"):
                # entity member call - not an lvalue; rewind to expression
                self.i -= 4
                return ("expr", "", "")
            if name not in self.gtypes:
                raise Unsupported(f"assignment to non-global id({name})")
            return ("global", f"S.g[{name!r}]", name)
        tok = self.peek()
        if tok[0] == "id" and tok[1] not in ("ecco_durable", "std"):
            name = self.take()[1]
            if self.val() == ".":
                self.take(".")
                fieldname = self.take()[1]
                if self.val() == "(":
                    self.i -= 3
                    return ("expr", "", "")
                return ("field", f"L[{name!r}].{fieldname}", (name, fieldname))
            if self.val() == "[":
                self.take("[")
                idx = self.expr()
                self.take("]")
                return ("index", f"L[{name!r}][{idx}]", (name, idx))
            return ("local", f"L[{name!r}]", name)
        return ("expr", "", "")

    def assign(self, target, rhs):
        kind, read, w = target
        if kind == "global":
            return f"S.set_global({w!r}, {rhs})"
        if kind == "local":
            ctype = self.ltypes.get(w)
            if ctype is None and w not in self.params:
                raise Unsupported(f"assignment to undeclared local {w}")
            return f"L[{w!r}] = {self.wrap_expr(rhs, ctype) if ctype else rhs}"
        if kind == "field":
            return f"setattr(L[{w[0]!r}], {w[1]!r}, {rhs})"
        if kind == "index":
            return f"L[{w[0]!r}][{w[1]}] = {rhs}"
        raise Unsupported("unsupported assignment target")

    # -- expressions (Pratt parser, C precedence) --
    _BIN = {
        "||": (1, "or"), "&&": (2, "and"), "|": (3, "|"), "^": (4, "^"), "&": (5, "&"),
        "==": (6, "=="), "!=": (6, "!="), "<": (7, "<"), "<=": (7, "<="), ">": (7, ">"), ">=": (7, ">="),
        "<<": (8, "<<"), ">>": (8, ">>"), "+": (9, "+"), "-": (9, "-"), "*": (10, "*"), "/": (10, "/"),
        "%": (10, "%"),
    }

    def expr(self, min_prec=0):
        left = self.unary()
        while True:
            op = self.val()
            if op == "?":
                if min_prec > 0:
                    return left  # the conditional operator binds loosest
                self.take("?")
                a = self.expr()
                self.take(":")
                b = self.expr()
                left = f"(({a}) if ({left}) else ({b}))"
                continue
            if op not in self._BIN:
                return left
            prec, py = self._BIN[op]
            if prec < min_prec:
                return left
            self.take()
            right = self.expr(prec + 1)
            if op == "/":
                left = f"c_div({left}, {right})"
            elif op == "%":
                left = f"c_mod({left}, {right})"
            elif py in ("and", "or"):
                left = f"(bool({left}) {py} bool({right}))"
            else:
                left = f"({left} {py} {right})"

    def unary(self):
        v = self.val()
        if v == "!":
            self.take()
            return f"(not {self.unary()})"
        if v == "-":
            self.take()
            return f"(-{self.unary()})"
        if v == "(" and [self.val(k) for k in (1, 2, 3, 4)] == ["unsigned", "long", "long", ")"]:
            for _ in range(5):
                self.take()
            return f"wrap({self.unary()}, 'uint64_t')"
        if v == "(" and self.val(1) in CAST_TYPES and self.val(2) == ")":
            self.take("(")
            ctype = self.take()[1]
            self.take(")")
            operand = self.unary()
            if ctype in ("float", "double"):
                return f"float({operand})"
            return f"wrap({operand}, {ctype!r})"
        return self.postfix(self.primary())

    def primary(self):
        kind, v = self.peek()
        if kind == "num":
            self.take()
            s = v.rstrip("uUlL")
            if s.lower().startswith("0x"):
                return str(int(s, 16))
            if s.endswith(("f", "F")):
                return repr(float(s[:-1]))
            return s if "." not in s else repr(float(s))
        if kind == "chr":
            self.take()
            return f"CStr({bytes(v[1:-1], 'utf-8').decode('unicode_escape')!r})"
        if v == "ecco_recovery_evidence":
            self.take()
            self.take("::")
            return f"R.{self.take()[1]}"
        if kind == "str":
            self.take()
            parts = [v]
            while self.peek()[0] == "str":  # adjacent string literal concatenation
                parts.append(self.take()[1])
            text = "".join(bytes(p[1:-1], "utf-8").decode("unicode_escape") for p in parts)
            return f"CStr({text!r})"
        if v == "(":
            self.take("(")
            e = self.expr()
            self.take(")")
            return f"({e})"
        if v == "id" and self.val(1) == "(":
            self.take("id")
            self.take("(")
            name = self.take()[1]
            self.take(")")
            if name in self.gtypes:
                return f"S.g[{name!r}]"
            return f"S.ent({name!r})"
        if v == "ecco_durable":
            self.take()
            self.take("::")
            name = self.take()[1]
            return f"D.{name}"
        if v == "std":
            self.take()
            self.take("::")
            name = self.take()[1]
            if name == "string":
                self.take("(")
                e = self.expr()
                self.take(")")
                return f"CStr({e})"
            if name == "isnan":
                return "math.isnan"
            if name == "fabs":
                self.take("(")
                e = self.expr()
                self.take(")")
                return f"abs({e})"
            if name in ("max", "min"):
                self.take("(")
                a = self.expr()
                self.take(",")
                b = self.expr()
                self.take(")")
                return f"{name}({a}, {b})"
            if name == "vector":
                self.take("<")
                self.take()
                self.take(">")
                self.take("{")
                elems = []
                while self.val() != "}":
                    elems.append(self.expr())
                    if self.val() == ",":
                        self.take(",")
                self.take("}")
                return f"[{', '.join(elems)}]"
            raise Unsupported(f"std::{name}")
        if v == "millis":
            self.take()
            self.take("(")
            self.take(")")
            return "S.millis()"
        if v == "random_uint32":
            # FB-B1: ESPHome's random_uint32(), backed by the Sim's seedable RNG
            # (Sim.random_uint32; `sim.rng_seed` is the observable seed).
            self.take()
            self.take("(")
            self.take(")")
            return "S.random_uint32()"
        if v == "millis_64":
            # FB-C1 (P-FBC-03a): the 64-bit, wrap-free microsecond-derived
            # clock. See Sim.millis_64().
            self.take()
            self.take("(")
            self.take(")")
            return "S.millis_64()"
        if v == "lroundf":
            self.take()
            self.take("(")
            e = self.expr()
            self.take(")")
            return f"S.lroundf({e})"
        if v == "sizeof":
            self.take()
            if self.val(1) in self.char_array_sizes and self.val(2) == ")":
                # sizeof(a char array declared in this lambda): its real size
                self.take("(")
                name = self.take()[1]
                self.take(")")
                return str(self.char_array_sizes[name])
            self.skip_parens()
            return "0"
        if v == "snprintf":
            # snprintf as an EXPRESSION: `snprintf(buf + off, sizeof(buf) - off, fmt, ...)`
            # (the statement form is handled in stmt()).
            self.take("snprintf")
            self.take("(")
            buf = self.take()[1]
            if buf not in self.char_array_sizes:
                raise Unsupported(f"snprintf expression into {buf!r}, not a sized char array of this lambda")
            offset = "0"
            if self.val() == "+":
                self.take("+")
                offset = self.expr()
            self.take(",")
            size = self.expr()
            args = []
            while self.val() == ",":
                self.take(",")
                args.append(self.expr())
            self.take(")")
            return f"c_snprintf_at(L, {buf!r}, {offset}, {size}, {', '.join(args)})"
        if v in ("true", "false"):
            self.take()
            return "True" if v == "true" else "False"
        if v == "NAN":
            self.take()
            return "float('nan')"
        if kind == "id":
            self.take()
            return f"L[{v!r}]"
        raise Unsupported(f"unexpected token {v!r}")

    def postfix(self, base):
        while True:
            v = self.val()
            if v in (".", "->"):
                self.take()
                name = self.take()[1]
                if self.val() == "(":
                    self.take("(")
                    args = []
                    while self.val() != ")":
                        args.append(self.expr())
                        if self.val() == ",":
                            self.take(",")
                    self.take(")")
                    base = f"{base}.{name}({', '.join(args)})"
                else:
                    base = f"{base}.{name}"
            elif v == "[":
                self.take("[")
                idx = self.expr()
                self.take("]")
                base = f"{base}[{idx}]"
            elif v == "(" and (base.startswith(("math.", "D.", "R.")) or base in {f"L[{n!r}]" for n in self.lambdas}):
                self.take("(")
                args = []
                while self.val() != ")":
                    args.append(self.expr())
                    if self.val() == ",":
                        self.take(",")
                self.take(")")
                base = f"{base}({', '.join(args)})"
            else:
                return base


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
WRITE = "modbus_client.write_multiple_registers"
READ = "modbus_client.read_holding_registers"


class Sim:
    def __init__(self, firmware: dict):
        self.fw = firmware
        self.subs = firmware["_substitutions"]
        self.g: dict = {}
        self.gtypes: dict = {}
        for g in firmware["globals"]:
            ctype = g["type"]
            self.gtypes[g["id"]] = ctype
            self.g[g["id"]] = self._initial(ctype, g.get("initial_value"))
        self.scripts = {s["id"]: s for s in firmware["script"]}
        self.on_value = {}
        for s in firmware.get("sensor", []):
            if s.get("id") and s.get("on_value"):
                self.on_value[s["id"]] = s["on_value"]["then"]
        self.entities: dict = {"ntp_time": Clock(self, "ntp_time")}
        self.D = Durable(self)
        self.nvs: dict = {}
        self.nvs_commits: list = []
        self.nvs_fail_tags: set = set()
        self.nvs_fail_all = False
        # SG-01 Phase 0 failure injection: fail only the next N commits for a
        # key (then succeed), and make loads fail for a key / everywhere.
        self.nvs_fail_next: dict = {}
        self.nvs_loads: list = []
        self.nvs_fail_load_tags: set = set()
        self.nvs_fail_load_all = False
        # SG-01 Phase 2: ONE ordered timeline of durable commits/loads and
        # Modbus operations, so "journal committed BEFORE the write" is an
        # observable fact rather than an inference from two separate logs.
        # Each entry is logged once the operation has taken effect (NVS
        # updated / write landed on the bank), and `event_hook(event)`, if
        # set, is called at that moment - i.e. at the exact "power cut right
        # after this operation" point a reboot test needs to capture.
        self.events: list = []
        self.event_hook = None
        # Fail exactly these 1-based commit ATTEMPTS for a key (e.g. {key: {2}}
        # fails only the second commit to that key).
        self.nvs_fail_attempts: dict = {}
        self.bank: dict = {}
        self.modbus_log: list = []
        self.outcome_fn = lambda kind, addr, count: "ok"
        self.read_override_fn = None
        self.bus_idle = True
        self.now_ms = 1_000_000
        self.ntp_valid = True
        self.epoch = 1_790_000_000
        self.hour = 14
        self.minute = 0
        self.running: set = set()
        self.executed: list = []
        self._fn_cache: dict = {}
        self._recovery_evidence = None
        # FB-B1: seedable per-sim RNG behind random_uint32(); `random_values`
        # is a FIFO of values returned first (tests force an exact salt),
        # `random_log` records every value handed out. `exception_code` is
        # what an on_error handler sees (Modbus "illegal data address").
        self.rng_seed = 0
        self.rng = random.Random(0)
        self.random_values: list = []
        self.random_log: list = []
        self.exception_code = 2

    def seed_rng(self, seed: int) -> None:
        self.rng_seed = int(seed)
        self.rng = random.Random(self.rng_seed)

    def random_uint32(self) -> int:
        value = (int(self.random_values.pop(0)) if self.random_values else self.rng.getrandbits(32)) & 0xFFFFFFFF
        self.random_log.append(value)
        return value

    @staticmethod
    def _initial(ctype, raw):
        raw = "0" if raw is None else str(raw).strip()
        if ctype == "bool":
            return raw.lower() == "true"
        if ctype == "std::string":
            return CStr(raw.strip('"'))
        if ctype in ("float", "double"):
            return float(raw)
        try:
            return wrap(int(raw, 0), ctype)
        except ValueError:
            return raw

    # -- runtime hooks used by transpiled code --
    def millis(self):
        return self.now_ms & 0xFFFFFFFF

    def millis_64(self):
        """ESPHome's millis_64(): 64-bit, never wraps, derived from
        esp_timer_get_time() rather than FreeRTOS ticks, so it differs from
        millis() by a constant sub-second offset (`millis64_offset_ms`, 0 by
        default; a test may set it). `now_ms` is the harness's monotonic
        64-bit clock - it may exceed 2**32, which is how a millis() wrap is
        modelled (millis() is its low 32 bits)."""
        return self.now_ms + getattr(self, "millis64_offset_ms", 0)

    @staticmethod
    def lroundf(v):
        return int(math.floor(v + 0.5)) if v >= 0 else -int(math.floor(-v + 0.5))

    def ent(self, name):
        if name not in self.entities:
            self.entities[name] = Entity(self, name)
        return self.entities[name]

    def set_global(self, name, value):
        ctype = self.gtypes[name]
        if ctype == "std::string":
            self.g[name] = CStr(value)
        else:
            self.g[name] = wrap(value, ctype)

    def compile(self, code, params=()):
        code = substitute(code, self.subs)
        key = (code, tuple(params))
        fn = self._fn_cache.get(key)
        if fn is None:
            src = Transpiler(self.gtypes, params).translate(code)
            if self._recovery_evidence is None:
                self._recovery_evidence = RecoveryEvidenceNS()
            env = {"math": math, "wrap": wrap, "CStr": CStr, "c_div": c_div, "c_mod": c_mod,
                   "c_format": c_format, "c_snprintf_at": c_snprintf_at, "D": self.D, "R": self._recovery_evidence}
            exec(src, env)  # noqa: S102 - transpiled from the repository's own firmware source
            fn = env["_f"]
            fn._src = src
            self._fn_cache[key] = fn
        return fn

    def run_lambda(self, code, local=None, params=()):
        return self.compile(code, params)(self, dict(local or {}))

    def run_on_value(self, sensor_id, value):
        for action in self.on_value.get(sensor_id, []):
            (kind, body), = action.items()
            if kind != "lambda":
                raise Unsupported(f"on_value action {kind}")
            self.run_lambda(body, {"x": float(value)}, params=("x",))

    # -- action trees --
    def run_actions(self, actions, local=None):
        for action in actions or []:
            (kind, body), = action.items()
            if kind == "lambda":
                self.run_lambda(body, local, params=tuple((local or {}).keys()))
            elif kind == "if":
                cond = body["condition"]
                if not (isinstance(cond, dict) and set(cond) == {"lambda"}):
                    raise Unsupported(f"unsupported if condition {cond!r}")
                taken = bool(self.run_lambda(cond["lambda"], local, params=tuple((local or {}).keys())))
                self.run_actions(body.get("then" if taken else "else"), local)
            elif kind in ("wait_until", "delay", "logger.log"):
                pass
            elif kind == "script.execute":
                if isinstance(body, str):
                    self.execute(body)
                else:
                    params = {}
                    for k, v in body.items():
                        if k == "id":
                            continue
                        if isinstance(v, LambdaStr):
                            params[k] = CStr(self.run_lambda(v, local, params=tuple((local or {}).keys())))
                        else:
                            params[k] = CStr(v)
                    self.execute(body["id"], params)
            elif kind == WRITE:
                self._modbus_write(body, local)
            elif kind == READ:
                self._modbus_read(body, local)
            else:
                raise Unsupported(f"unsupported action {kind}")

    def execute(self, script_id, params=None):
        self.executed.append((script_id, dict(params or {})))
        if script_id in self.running:
            return  # mode: single - dropped, exactly like ESPHome
        self.running.add(script_id)
        try:
            self.run_actions(self.scripts[script_id]["then"], dict(params or {}))
        finally:
            self.running.discard(script_id)

    def _handler(self, body, name, local, values=None, exception_code=None):
        if name is None or name not in body:
            return
        for action in body[name]["then"]:
            (kind, code), = action.items()
            if kind != "lambda":
                raise Unsupported(f"handler action {kind}")
            loc = dict(local or {})
            if values is not None:
                loc["values"] = Vec(values)
            if exception_code is not None:
                loc["exception_code"] = int(exception_code)
            self.compile(code, tuple(loc.keys()))(self, loc)

    def _modbus_write(self, body, local):
        addr = int(body["start_address"])
        vals = self.run_lambda(body["values"], local, params=tuple((local or {}).keys()))
        outcome = self.outcome_fn("write", addr, len(vals))
        self.modbus_log.append(("write", addr, list(vals), outcome))
        if outcome in ("ok", "no_response_landed", "timeout_landed"):
            for i, v in enumerate(vals):
                self.bank[addr + i] = v
        self._log_event(("write", addr, list(vals), outcome))
        # "custom_response" (Manual TOU Phase 1): a reply the hub's dispatch
        # gate diverts as non-standard - it fires on_custom_response INSTEAD
        # of on_response; whether the write itself landed is unknown, so the
        # bank is left untouched (not in the landed set above).
        handler = {"ok": "on_response", "ack_not_applied": "on_response", "error": "on_error",
                   "not_sent": "on_not_sent", "no_response_landed": "on_no_response",
                   "no_response_lost": "on_no_response", "custom_response": "on_custom_response"}.get(outcome)
        self._handler(body, handler, local, exception_code=self.exception_code if handler == "on_error" else None)

    def _modbus_read(self, body, local):
        addr, count = int(body["start_address"]), int(body["count"])
        outcome = self.outcome_fn("read", addr, count)
        values = [self.bank.get(addr + i, 0) for i in range(count)]
        if self.read_override_fn:
            values = self.read_override_fn(addr, count, values)
        self.modbus_log.append(("read", addr, list(values), outcome))
        self._log_event(("read", addr, count, outcome))
        handler = {"ok": "on_response", "error": "on_error", "not_sent": "on_not_sent",
                   "no_response": "on_no_response", "custom_response": "on_custom_response"}.get(outcome)
        self._handler(body, handler, local, values if handler == "on_response" else None,
                      exception_code=self.exception_code if handler == "on_error" else None)

    # -- SG-01: durable-store helpers for the START journal --
    def nvs_put_journal_bytes(self, key, data: bytes):
        """Injects raw NVS content for the journal tag, as a corrupt/foreign
        flash image would present it: exactly JOURNAL_SIZE bytes become a
        journal record (whatever their content - load_record() succeeds and
        the firmware must classify it); any other length is a size mismatch,
        which load_record() reports as "not present"."""
        if len(data) == jm.JOURNAL_SIZE:
            rec = Record(jm.JOURNAL_KIND)
            for f, v in jm.unpack_journal(data).items():
                object.__setattr__(rec, f, v)
            self.nvs[key] = rec
        else:
            self.nvs[key] = Record("_WrongSizeBlob")

    def nvs_journal_bytes(self, key) -> bytes | None:
        rec = self.nvs.get(key)
        if rec is None or rec._kind != jm.JOURNAL_KIND:
            return None
        return jm.pack_journal(rec)

    def reset_durable(self) -> None:
        """A fresh, empty durable store and timeline (failure injection
        cleared), keeping this Sim's compiled-lambda cache - lets a fault
        sweep reuse one Sim as the durable store for thousands of runs."""
        self.nvs = {}
        self.nvs_commits = []
        self.nvs_loads = []
        self.events = []
        self.nvs_fail_tags = set()
        self.nvs_fail_all = False
        self.nvs_fail_next = {}
        self.nvs_fail_load_tags = set()
        self.nvs_fail_load_all = False
        self.nvs_fail_attempts = {}

    def _log_event(self, event) -> None:
        self.events.append(event)
        if self.event_hook is not None:
            self.event_hook(event)

    def commits_for(self, key) -> list:
        """Every commit ATTEMPT (failed included) for `key`, oldest first."""
        return [r for k, r in self.nvs_commits if k == key]

    # -- convenience --
    def writes(self):
        return [(a, v) for k, a, v, o in self.modbus_log if k == "write"]

    def status(self):
        return str(self.ent("dump_status").state)

    def advance(self, ms):
        self.now_ms += ms


def find_interval(firmware: dict, marker_lambda_substring: str) -> list:
    """The `then:` list of the first `interval:` whose actions contain a
    lambda/condition text including `marker_lambda_substring`."""
    for iv in firmware["interval"]:
        if marker_lambda_substring in yaml.dump(iv["then"]):
            return iv["then"]
    raise KeyError(marker_lambda_substring)


def extract_between(text: str, start_marker: str, end_marker: str) -> str:
    a = text.index(start_marker)
    b = text.index(end_marker, a)
    return text[a:b]
