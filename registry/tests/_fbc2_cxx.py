"""FB-C2 helper: C++-vs-Python parity for the pure shadow evaluator.

The Python mirror (registry/failback_shadow.py) and the C++ header (firmware/include/ecco_failback_shadow.h) must agree on every
input. This module turns a Python ShadowInputs into C++ statements that build the SAME value, folds every output field of
ShadowPlan (and the Inputs text) into one 64-bit FNV digest on both sides, and emits `static_assert`s so that a real C++ compiler
EVALUATES the header at compile time (no driver has to run: the only compiler on the development machines is the ESP32 cross
compiler, which can evaluate constexpr but not execute code).

No I/O except building source text; compile_source() writes a temporary directory.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INCLUDE = ROOT / "firmware" / "include"
sys.path.insert(0, str(ROOT / "registry"))
import failback_shadow as sh  # noqa: E402
import fallback_capture as cap  # noqa: E402
import fallback_profile as fpm  # noqa: E402

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
M64 = (1 << 64) - 1


def fnv_step(h: int, v: int, width: int) -> int:
    """FNV-1a over `width` little-endian bytes of v (the C++ digest does the same)."""
    for k in range(width):
        h ^= (v >> (8 * k)) & 0xFF
        h = (h * FNV_PRIME) & M64
    return h


def plan_fields(p: "sh.ShadowPlan") -> list[tuple[int, int]]:
    """(value, byte width) of every ShadowPlan field, in the fixed digest order (mirrored by CXX_DIGEST)."""
    f = [
        (p.plan, 1), (p.reason, 2), (p.blocking_domain, 1), (p.row, 1), (p.fba_state, 1), (p.fba_result, 1),
        (p.fba_result_policy_a, 1), (p.projected_after, 1), (p.alt_plan_absence_accepted, 1), (p.export_hazard, 1), (p.ca, 1),
        (int(p.would_refuse_starts) | int(p.would_preempt_fp) << 1 | int(p.would_preempt_dump) << 2 | int(p.would_apply) << 3
         | int(p.would_write_244) << 4 | int(p.absence_relied) << 5 | int(p.durable_leg_projected) << 6
         | int(p.fp_stale_operator_needed) << 7, 1),
        (int(p.dump_stale_operator_needed) | int(p.r244_lav_marker_absent) << 1 | int(p.fp_ctx_unknown) << 2
         | int(p.profile_changed_since_lost) << 3 | int(p.dump_force_bypass_armed) << 4
         | int(p.sup_returned_episode_open) << 5 | int(p.masks_valid) << 6 | int(p.hazard_obligation) << 7, 1),
        (p.e1_delta_mask, 4), (p.out_of_domain_mask, 4), (p.ctx_mismatch_mask, 2), (p.info_mismatch_mask, 1),
        (p.delta_count, 1), (p.e1_state, 1), (p.cx_state, 1), (p.in_state, 1), (p.projected_frames, 1),
        (p.projected_frame_count, 1),
    ]
    for d in p.dom:
        f += [(d.c0, 1), (d.kind, 1), (d.evidence, 1), (d.detail, 1)]
    return f


def digest_py(p: "sh.ShadowPlan", text: str) -> int:
    h = FNV_OFFSET
    for v, w in plan_fields(p):
        h = fnv_step(h, v, w)
    for ch in text:
        h = fnv_step(h, ord(ch), 1)
    return h


CXX_DIGEST = r"""
using namespace ecco_failback_shadow;
constexpr uint64_t step(uint64_t h, uint64_t v, int width) {
  for (int k = 0; k < width; k++) {
    h ^= (v >> (8 * k)) & 0xFFu;
    h *= 0x100000001B3ULL;
  }
  return h;
}
constexpr uint64_t digest(const ShadowPlan &p, const ecco_fbcap::TextBuf &t) {
  uint64_t h = 0xCBF29CE484222325ULL;
  h = step(h, p.plan, 1); h = step(h, p.reason, 2); h = step(h, p.blocking_domain, 1); h = step(h, p.row, 1);
  h = step(h, p.fba_state, 1); h = step(h, p.fba_result, 1); h = step(h, p.fba_result_policy_a, 1);
  h = step(h, p.projected_after, 1); h = step(h, p.alt_plan_absence_accepted, 1); h = step(h, p.export_hazard, 1);
  h = step(h, p.ca, 1);
  h = step(h, (p.would_refuse_starts ? 1u : 0u) | (p.would_preempt_fp ? 2u : 0u) | (p.would_preempt_dump ? 4u : 0u) |
                  (p.would_apply ? 8u : 0u) | (p.would_write_244 ? 16u : 0u) | (p.absence_relied ? 32u : 0u) |
                  (p.durable_leg_projected ? 64u : 0u) | (p.fp_stale_operator_needed ? 128u : 0u), 1);
  h = step(h, (p.dump_stale_operator_needed ? 1u : 0u) | (p.r244_lav_marker_absent ? 2u : 0u) | (p.fp_ctx_unknown ? 4u : 0u) |
                  (p.profile_changed_since_lost ? 8u : 0u) | (p.dump_force_bypass_armed ? 16u : 0u) |
                  (p.sup_returned_episode_open ? 32u : 0u) | (p.masks_valid ? 64u : 0u) | (p.hazard_obligation ? 128u : 0u), 1);
  h = step(h, p.e1_delta_mask, 4); h = step(h, p.out_of_domain_mask, 4); h = step(h, p.ctx_mismatch_mask, 2);
  h = step(h, p.info_mismatch_mask, 1); h = step(h, p.delta_count, 1); h = step(h, p.e1_state, 1); h = step(h, p.cx_state, 1);
  h = step(h, p.in_state, 1); h = step(h, p.projected_frames, 1); h = step(h, p.projected_frame_count, 1);
  for (size_t i = 0; i < DOM_COUNT; i++) {
    h = step(h, p.dom[i].c0, 1); h = step(h, p.dom[i].kind, 1); h = step(h, p.dom[i].evidence, 1); h = step(h, p.dom[i].detail, 1);
  }
  for (size_t i = 0; i < t.size(); i++) h = step(h, (uint8_t) t.buf[i], 1);
  return h;
}
"""


# ---------------------------------------------------------------------------
# Python ShadowInputs -> C++ statements
# ---------------------------------------------------------------------------
def _is_default(a, b) -> bool:
    return a == b


def _emit(prefix: str, value, default, out: list[str]) -> None:
    """Statements assigning `value` to the C++ lvalue `prefix`, only where it differs from the C++ default-initialised value."""
    if dataclasses.is_dataclass(value):
        for f in dataclasses.fields(value):
            _emit(f"{prefix}.{f.name}", getattr(value, f.name), getattr(default, f.name), out)
        return
    if isinstance(value, dict):  # a FallbackProfileV1 record
        for k, v in value.items():
            dv = default.get(k) if isinstance(default, dict) else None
            _emit(f"{prefix}.{k}", v, dv, out)
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            dv = default[i] if isinstance(default, (list, tuple)) and i < len(default) else None
            _emit(f"{prefix}[{i}]", v, dv, out)
        return
    if value is None:
        return
    if isinstance(value, bool):
        v = "true" if value else "false"
    else:
        v = f"{int(value)}u" + ("ull" if int(value) > 0xFFFFFFFF else "")
        if int(value) > 0xFFFFFFFF:
            v = f"{int(value)}ull"
    if default is not None and not isinstance(default, (dict, list)) and value == default and type(value) == type(default):
        return
    out.append(f"  {prefix} = {v};")


def default_inputs_for_emit() -> "sh.ShadowInputs":
    d = sh.ShadowInputs()
    d.lm.p = fpm.blank_profile()
    return d


def emit_case(name: str, i: "sh.ShadowInputs") -> str:
    """`constexpr ShadowInputs name() {...}` building the same value as the Python `i` (a None profile is the C++ zero record)."""
    base = default_inputs_for_emit()
    val = dataclasses.replace(i)
    if val.lm.p is None:
        val = dataclasses.replace(i, lm=dataclasses.replace(i.lm, p=fpm.blank_profile()))
    lines: list[str] = []
    _emit("in", val, base, lines)
    # the profile is a dict: emit it in full (the mirror carries the 96-byte record fields by name)
    return "constexpr ShadowInputs %s() {\n  ShadowInputs in{};\n%s\n  return in;\n}\n" % (name, "\n".join(lines))


def case_digest_py(i: "sh.ShadowInputs") -> int:
    p = sh.evaluate(i)
    return digest_py(p, str(sh.inputs_text(i, p)))


def emit_asserts(cases: list["sh.ShadowInputs"], prefix: str = "case") -> str:
    parts = [CXX_DIGEST]
    asserts = []
    for n, i in enumerate(cases):
        parts.append(emit_case(f"{prefix}_{n}", i))
        asserts.append(
            f"static_assert(digest(evaluate({prefix}_{n}()), inputs_text({prefix}_{n}(), evaluate({prefix}_{n}()))) == "
            f"0x{case_digest_py(i):016X}ULL, \"parity case {n}\");")
    return "\n".join(parts) + "\n" + "\n".join(asserts) + "\n"


# ---------------------------------------------------------------------------
# Compiling
# ---------------------------------------------------------------------------
def find_compiler() -> str | None:
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++", "clang++"):
        found = shutil.which(name)
        if found:
            return found
    import glob
    local = os.environ.get("LOCALAPPDATA")
    pats = []
    if local:
        pats.append(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*", "xtensa-esp-elf", "bin",
                                 "xtensa-esp32-elf-g++*"))
    home = Path.home()
    pats += [str(home / ".esphome" / "**" / "xtensa-esp32-elf-g++*"),
             str(home / ".espressif" / "tools" / "xtensa-esp-elf" / "*" / "xtensa-esp-elf" / "bin" / "xtensa-esp32-elf-g++*")]
    for pat in pats:
        hits = [h for h in sorted(glob.glob(pat, recursive=True)) if not h.endswith((".json", ".txt", ".md"))]
        if hits:
            return hits[-1]
    return None


HEADERS = ("ecco_fallback_profile.h", "ecco_fallback_durable_model.h", "ecco_fallback_capture.h", "ecco_failback_shadow.h")


def compile_source(src: str, std: str, header_overrides: dict | None = None, extra_flags: tuple = ()) -> tuple[int, str]:
    """(returncode, output) of a -fsyntax-only -Wall -Wextra -Werror compile of `src`. returncode 127 when no compiler exists.
    `header_overrides` {name: text} replaces the real header of that name (a mutant)."""
    cxx = find_compiler()
    if cxx is None:
        return 127, "no C++ compiler found (this check fails rather than skips)"
    ov = dict(header_overrides or {})
    with tempfile.TemporaryDirectory(prefix="fbc2_cpp_") as d:
        tmp = Path(d)
        (tmp / "tu.cpp").write_text(src, encoding="utf-8", newline="\n")
        for h in HEADERS:
            text = ov[h] if h in ov else (INCLUDE / h).read_text(encoding="utf-8")
            (tmp / h).write_text(text, encoding="utf-8", newline="\n")
        cmd = [cxx, f"-std={std}", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-fconstexpr-ops-limit=200000000",
               "-fconstexpr-loop-limit=2000000", *extra_flags, "-I", str(tmp), str(tmp / "tu.cpp")]
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr)[-4000:]
