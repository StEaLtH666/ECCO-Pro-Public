"""A tiny TEST DOUBLE of registry/fallback_capture.py (the Python mirror of the
FB-B1 capture header), used only by test_fallback_capture_harness.py so the
generic `ecco_fbcap::` adapter is exercised without depending on the real
mirror existing. It deliberately covers every shape the adapter must handle:

  constants         ints, a text constant, a constexpr array (REGS)
  enums             an IntEnum (`ecco_fbcap::Purpose::REVIEW`)
  POD types         dataclasses with scalar, array and string fields, CTYPES
                    width hints, a nested POD, a namedtuple
  pure functions    scalar / array / POD arguments, POD and array returns
  in-place output   `store_block_241(words, values)` fills the caller's array
  functional output `store_functional` + HARNESS_OUT_PARAMS (returns the new array)
  text              a str-returning builder and a TextBuf-like with c_str() / size()
  hints             HARNESS_SIZEOF, HARNESS_TYPES
"""

from __future__ import annotations

import dataclasses  # noqa: F401 - an imported MODULE: the adapter must refuse to expose it as a header name
import enum
import sys
from collections import namedtuple
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

CANDIDATE_TTL_MS = 120000
BREAKER_MS = 30000
IDLE_WAIT_MS = 7000
STEP_WAIT_MS = 3000
TXT_READY = "CANDIDATE READY - test double"
REGS = (230, 232, 244) + tuple(range(250, 262)) + tuple(range(268, 280)) + (243, 245, 247, 248)

READ_SHORT = 3
READ_EXCEPTION = 4
READ_BOUNDED_WAIT = 7


class Purpose(enum.IntEnum):
    NONE = 0
    REVIEW = 1


@dataclass
class Slot:
    hhmm: int = 0
    watts: int = 0  # no width hint on purpose: stored as given

    CTYPES = {"hhmm": "uint16_t"}


@dataclass
class Pod:
    """A POD input struct: scalar fields with width hints, an array field, a text field, a nested POD."""

    kind: int = 0
    word: int = 0
    big: int = 0
    words: list = field(default_factory=lambda: [0, 0, 0, 0])
    label: str = ""
    slot: Slot = field(default_factory=Slot)

    CTYPES = {"word": "uint16_t", "big": "uint32_t", "kind": "uint8_t"}


@dataclass
class Verdict:
    refused: bool = False
    code: int = 0
    words: list = field(default_factory=lambda: [0] * 31)


Pair = namedtuple("Pair", ["kind", "basis"])


class TextBuf:
    """A TextBuf-like: c_str() / size() / append()."""

    def __init__(self):
        self._s = ""

    def append(self, s):
        self._s += str(s)
        return self

    def c_str(self):
        return self._s

    def size(self):
        return len(self._s)


def decide(pod, now_ms):
    v = Verdict()
    v.refused = pod.kind > 5
    v.code = (pod.word + (now_ms & 0xFF)) & 0xFFFF
    v.words[0] = pod.words[1]
    v.words[30] = pod.slot.watts
    return v


def classify(kind):
    return Pair(kind=kind + 1, basis=kind * 2)


def candidate_expired(now_ms, born_ms):
    return ((now_ms - born_ms) & 0xFFFFFFFF) >= CANDIDATE_TTL_MS


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return -1


def store_block_241(words, values):
    """The C++ reference-parameter style: fills the caller's std::array in place (words 3.. <- the first 28 of the
    53 words; words 0..2 belong to the 230/3 block)."""
    if len(values) != 53:
        return False
    for i, v in enumerate(values):
        if 3 + i < len(words):
            words[3 + i] = v
    return True


def store_functional(words, values):
    new = list(words)
    for i, v in enumerate(values):
        new[i] = v
    return True, new


HARNESS_OUT_PARAMS = {"store_functional": (0,)}
HARNESS_SIZEOF = {"Pod": 28}


def epc_name(cls):
    names = {0: "UNREADABLE", 1: "NOT_CAPTURED", 5: "VALID"}
    return names.get(cls, "?")


def refusal_text(code):
    t = TextBuf()
    t.append("REVIEW REFUSED - code ").append(code)
    return t


def sv_text(n):
    return "NO:" + ",".join(f"PWRL{i}" for i in range(1, n + 1)) if n else "OK"


def make_words():
    return [7, 8, 9]


def store_block_slices(words, values):
    """A mirror written in plain Python: slice assignment and negative indexes on the caller's std::array."""
    words[1:4] = values[0:3]
    words[-1] = 9
    return words[-2]


def make_profile_dict(words):
    """A mirror function returning a record as a dict (the C++ returns a FallbackProfileV1)."""
    w = list(words)
    return fp.blank_profile(magic=fp.PROFILE_MAGIC, schema=1, size=96, reg244=w[0], reg232=w[1])


@dataclass
class ReadIn:
    """Fields the mirror declares as a dict / bytes: a record / std::array<uint8_t, N> stored in them converts."""

    p: dict = field(default_factory=fp.blank_profile)
    raw: bytes = bytes(96)
    n: int = 0


@dataclass
class ReadOut:
    latch: fd.ReadLatch = field(default_factory=fd.ReadLatch)
    gen: int = 0
    raw_len: int = 0


def read_eval(ri):
    out = ReadOut()
    out.latch.present_seen = 1 if ri.p["magic"] == fp.PROFILE_MAGIC else 0
    out.gen = ri.p["generation"]
    out.raw_len = len(ri.raw)
    return out


class Txt(str):
    """A TextBuf(str): a plain str with the C++ accessors."""

    def c_str(self):
        return str(self)

    def size(self):
        return len(self)


def echo_c(s):
    """Proves a std::string argument still answers c_str() inside the mirror."""
    return s.c_str() + "!"


def kind_to_name(kind):
    return {1: "REVIEW"}[kind]


_private_helper = 5
