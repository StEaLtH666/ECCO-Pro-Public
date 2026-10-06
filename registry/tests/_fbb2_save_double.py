"""A tiny TEST DOUBLE of registry/fallback_save.py (the Python mirror of firmware/include/ecco_fallback_save.h, namespace
ecco_fbsave), used only by test_fallback_save_harness.py so that the generic `ecco_fbsave::` adapter is proved without depending
on the real mirror's evolving surface. It copies the CONVENTIONS the real mirror uses, nothing else:

  constants        ints (ARM_TTL_MS), tuple-unpacked enum ints (ACT_*, SG_*)
  C strings        `const char *` arrives as `str | bytes | None` with an optional byte length `n` (without it the string runs
                   to its first NUL, read at most `limit + 1` bytes - so a StringRef::c_str() pointer that is NOT NUL-terminated
                   over-reads exactly like the C++ would)
  POD structs      dataclasses in C++ field order, a nested dataclass, a TextBuf field
  functions        pure; return an int / bool / TextBuf / POD
  text             TextBuf = a str with c_str() / size()
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

ARM_TTL_MS = 120000
PRECOMMIT_WAIT_MS = 3000
PURPOSE_SAVE = 2
ECHO_MAX = 24
(ACT_UNSUPPORTED, ACT_SAVE, ACT_INVALIDATE, ACT_RESTORE, ACT_ACKNOWLEDGE) = range(5)
(SG_UNSET, SG_ACCEPT, SG_ARM_OFF, SG_ID_MISMATCH) = range(4)
U32 = 0xFFFFFFFF


class TextBuf(str):
    def c_str(self):
        return str(self)

    def size(self):
        return len(self)


def _cb(s):
    if s is None:
        return None
    return bytes(s) if isinstance(s, (bytes, bytearray)) else str(s).encode("utf-8", "surrogatepass")


def bounded_len(s, limit):
    b = _cb(s)
    if b is None:
        return 0
    i = b.find(b"\0")
    return min(len(b) if i < 0 else i, limit + 1)


def action_token(action, n=None):
    if n is None:
        n = bounded_len(action, 16)
    b = _cb(action)
    if b is None:
        return ACT_UNSUPPORTED
    return {b"SAVE": ACT_SAVE, b"INVALIDATE": ACT_INVALIDATE, b"RESTORE": ACT_RESTORE,
            b"ACKNOWLEDGE": ACT_ACKNOWLEDGE}.get(b[:n], ACT_UNSUPPORTED)


def unsupported_action_text(action, n=None):
    if n is None:
        n = bounded_len(action, ECHO_MAX)
    b = _cb(action) or b""
    echo = "".join(chr(c) if (48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c == 95) else "?" for c in b[:min(n, ECHO_MAX)])
    return TextBuf("REFUSED - unsupported action '" + echo + "'")


def expected_phrase(kind, ident):
    return TextBuf(("SAVE " if kind == ACT_SAVE else "INVALIDATE ") + format(ident, "X").rjust(16, "0"))


def arm_expired(now_ms, on_ms):
    return ((now_ms - on_ms) & U32) >= ARM_TTL_MS


@dataclass
class Bus:
    mutex: bool = False
    busy_for_ms: int = 0


@dataclass
class GateIn:
    arm_was_on: bool = False
    cand_id: int = 0
    now_ms: int = 0
    bus: Bus = field(default_factory=Bus)
    note: str = ""

    CTYPES = {"now_ms": "uint32_t", "cand_id": "uint64_t"}


@dataclass
class GateOut:
    code: int = SG_UNSET
    text: TextBuf = field(default_factory=TextBuf)


def gate_decide(inp, action, action_len, target_id, target_len):
    out = GateOut()
    if action_token(action, action_len) != ACT_SAVE:
        out.code, out.text = SG_ARM_OFF, unsupported_action_text(action, action_len)
    elif not inp.arm_was_on:
        out.code, out.text = SG_ARM_OFF, TextBuf("SAVE REFUSED - arm is not on")
    elif _cb(target_id)[:target_len] != format(inp.cand_id, "X").rjust(16, "0").encode():
        out.code, out.text = SG_ID_MISMATCH, TextBuf("SAVE REFUSED - candidate ID does not match")
    else:
        out.code = SG_ACCEPT
    return out


@dataclass
class Wide:
    """Plain `int` annotations (no CTYPES): a uint64_t id and a 0xFFFFFFFF sentinel must survive a store from a lambda untruncated."""

    id64: int = 0
    seen: int = 0xFFFFFFFF
    ms: int = 0


@dataclass
class Planned:
    """A result whose members are records the mirror holds as dicts (the C++ struct members p_new / w_new)."""

    code: int = 0
    p_new: dict = field(default_factory=fp.blank_profile)
    w_new: dict = field(default_factory=fd.blank_provision)


def make_plan(w, generation):
    out = Planned()
    out.code = 1 if w.id64 == 0xD852A4FA2DF7DBA3 and w.seen == 0xFFFFFFFF else 2
    out.p_new = fp.seal_profile(fp.blank_profile(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=generation))
    out.w_new = fd.make_provision(generation, out.p_new["binding"], 0, 0, fd.FALLBACK_PROFILE_KEY, 1, fd.PROV_OP_SAVE)
    return out


def first_non_ok(err_w, err_p):
    return (err_w & U32) if err_w else (err_p & U32)


HARNESS_SIZEOF = {"GateIn": 40}
_private_thing = 1
