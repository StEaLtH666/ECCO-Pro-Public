"""FB-B1 helper: a REAL syntax-level compile of every FB-B1 lambda (no ESPHome toolchain needed).

`test_fallback_profile_capture.py` section [C] uses this. The offline simulator (`_fbb_harness.FbbSim`)
executes the FB lambdas through a Python transpiler; that proves behaviour but not that the C++ is
well-formed. This module closes that gap as far as it can be closed without `esphome compile`:

  * `lambdas_of(fw)` walks the three Review scripts, the 10 s housekeeping interval and the appended
    on_boot lambda (every action kind the FB code may use: lambda / if / wait_until /
    modbus_client.read_holding_registers with its five handlers / script.execute) and returns every
    lambda body, its C++ kind (void or bool condition) and the handler parameter list ESPHome
    generates for it. An action kind the walker does not know raises: FB-B1 code may not use one.
  * `build_source(fw)` wraps each body in a function and rewrites `id(x)` the way ESPHome's
    codegen does (a global becomes `g_x->value()`, any other component keeps its name), over small
    STUBS of the ESPHome symbols (the entity / script / hub classes, `millis`, `random_uint32`,
    `ESP_LOG*` - printf-checked, so a log call whose arguments do not match its conversions is a REAL compile error under
    -Wformat -Werror -, the durable marker type and the direct NVS adapter). The FB headers
    (ecco_fallback_profile.h, ecco_fallback_durable_model.h, ecco_fallback_capture.h) are the REAL files.
  * `compile_source` / `compile_all` run the cross compiler ESPHome itself installs
    (xtensa-esp32-elf-g++, the firmware's compiler) with `-fsyntax-only -Wall -Wextra -Werror` under
    gnu++17 and gnu++20.

What it does NOT prove: ESPHome's generated glue (trigger plumbing, `GlobalsComponent`), link-time
or run-time behaviour, the ESP-IDF API surface the stubs stand in for. `esphome compile` is the
final word on those.

FB-B2 (the SAVE / INVALIDATE firmware): `lambdas_of` ALSO walks - each only if the firmware has it, so the as-of-FB-B1
text still yields exactly the FB-B1 set - the scripts `fallback_profile_save` / `fallback_profile_invalidate`, the api action
`fallback_profile_execute` (every lambda, `if` condition and `wait_until` condition of an api action is generated as
`[](StringRef action, StringRef target_id, StringRef confirmation)`: StatelessLambdaAction<StringRef, ...>, checked against a
real generated main.cpp) and the `turn_on_action` / `turn_off_action` of the arm switch `fallback_profile_arm`. The stub set
gained a faithful esphome::StringRef (esphome/core/string_ref.h, ESPHome 2026.8.2 - `c_str()` is NOT NUL-terminated, the
conversions and comparison operators are the real ones), switches that `turn_on()` / `turn_off()` / `toggle()`, a time
component stub (`id(ntp_time).now()` -> ESPTime), and - only when a lambda names `ecco_fbsave::` - the real
firmware/include/ecco_fallback_save.h is staged and included (`extra_headers={name: text}` replaces / adds a header, which is
how the self-tests stage a stand-in before the real one exists).
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ROOT / "firmware" / "include"
HEADERS = ("ecco_fallback_profile.h", "ecco_fallback_durable_model.h", "ecco_fallback_capture.h")
STDS = ("gnu++17", "gnu++20")
FLAGS = ("-fsyntax-only", "-Wall", "-Wextra", "-Werror")
FB_SCRIPT_IDS = ("fallback_profile_review", "fallback_profile_capture_dispatch", "fallback_profile_invalidate_candidate")
INTERVAL_MARK = "fallback_profile_cand_valid"
# FB-B2: walked when present (see the module docstring)
FBB2_SCRIPT_IDS = ("fallback_profile_save", "fallback_profile_invalidate")
FBB2_API_ACTION = "fallback_profile_execute"
FBB2_ARM_SWITCH = "fallback_profile_arm"
SAVE_HEADER = "ecco_fallback_save.h"
API_VAR_CTYPES = {"string": "StringRef", "bool": "bool", "int": "int32_t", "float": "float"}
NO_CXX = "no C++ compiler found (this check fails rather than skips)"

# The parameters ESPHome's generated lambda has in each Modbus reply handler (components/modbus_client/modbus_client.h).
HANDLER_PARAMS = {
    "on_response": "std::span<const uint16_t> values",
    "on_error": "std::span<const uint8_t> request, esphome::modbus::ExceptionCode exception_code",
    "on_no_response": "std::span<const uint8_t> request",
    "on_not_sent": "std::span<const uint8_t> request",
    "on_custom_response": "std::span<const uint8_t> request, std::span<const uint8_t> response",
}


def find_compiler() -> str | None:
    """Same search order as test_failback_shadow_core.find_compiler(): $ECCO_CXX, a host g++ / c++ / clang++ on PATH,
    then the xtensa GCC that ESPHome's own ESP-IDF toolchain installs."""
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++", "clang++"):
        found = shutil.which(name)
        if found:
            return found
    patterns = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        patterns.append(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*", "xtensa-esp-elf",
                                     "bin", "xtensa-esp32-elf-g++*"))
    home = Path.home()
    patterns += [str(home / ".esphome" / "**" / "xtensa-esp32-elf-g++*"),
                 str(home / ".platformio" / "packages" / "toolchain-xtensa*" / "bin" / "xtensa-esp32-elf-g++*"),
                 str(home / ".espressif" / "tools" / "xtensa-esp-elf" / "*" / "xtensa-esp-elf" / "bin" / "xtensa-esp32-elf-g++*")]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern, recursive=True))
        hits = [h for h in hits if not h.endswith((".json", ".txt", ".md"))]
        if hits:
            return hits[-1]
    return None


@dataclass
class Lam:
    name: str
    kind: str      # "void" (an action lambda) | "bool" (an if / wait_until condition)
    params: str    # the C++ parameter list ESPHome generates ("" for everything but a Modbus handler)
    code: str


def _cond_code(cond) -> str:
    if isinstance(cond, dict):
        if set(cond) != {"lambda"}:
            raise ValueError(f"non-lambda condition {cond!r}")
        return cond["lambda"]
    if isinstance(cond, str) and cond.strip():
        return cond
    raise ValueError(f"unsupported condition {cond!r}")


def _walk(actions, label: str, out: list, params: str = "") -> None:
    """`params` = the C++ parameter list every lambda / condition of this tree is generated with (an api action's
    `StringRef action, ...`); the Modbus reply handlers set their own."""
    for i, action in enumerate(actions or []):
        if not isinstance(action, dict) or len(action) != 1:
            raise ValueError(f"{label}[{i}]: not a single-key action: {action!r}")
        (kind, body), = action.items()
        here = f"{label}[{i}]"
        if kind == "lambda":
            out.append(Lam(here, "void", params, body))
        elif kind == "if":
            out.append(Lam(here + ".if", "bool", params, _cond_code(body["condition"])))
            _walk(body.get("then"), here + ".then", out, params)
            _walk(body.get("else"), here + ".else", out, params)
        elif kind == "wait_until":
            cond = body["condition"] if isinstance(body, dict) and "condition" in body else body
            out.append(Lam(here + ".wait", "bool", params, _cond_code(cond)))
        elif kind == "modbus_client.read_holding_registers":
            for oc, handler_params in HANDLER_PARAMS.items():
                if oc in body:
                    _walk(body[oc]["then"], f"{here}.{oc}", out)
                    for lam in out:
                        if lam.name.startswith(f"{here}.{oc}[") and not lam.params:
                            lam.params = handler_params
        elif kind == "script.execute":
            continue
        else:
            raise ValueError(f"{here}: action {kind!r} is not allowed in FB-B1 / FB-B2 code")


def api_params(act: dict) -> str:
    """The C++ parameter list ESPHome generates for the lambdas of an api action: `StringRef action, StringRef target_id, ...`
    (a `string` variable is a StringRef; bool / int / float are plain values)."""
    parts = []
    for name, ctype in (act.get("variables") or {}).items():
        if ctype not in API_VAR_CTYPES:
            raise ValueError(f"api action {act.get('action')!r}: variable {name!r} has the unmodelled type {ctype!r}")
        parts.append(f"{API_VAR_CTYPES[ctype]} {name}")
    return ", ".join(parts)


def lambdas_of(fw: dict, *, scripts_fbb2=FBB2_SCRIPT_IDS, api_action=FBB2_API_ACTION, arm_switch=FBB2_ARM_SWITCH) -> list[Lam]:
    """Every lambda of the three Review scripts, the housekeeping interval and the appended on_boot lambda - and, when the
    firmware has them (FB-B2), of the SAVE / INVALIDATE scripts, the `fallback_profile_execute` api action and the arm
    switch's turn_on / turn_off actions (the names are parameters so a synthetic fixture can be walked too)."""
    out: list[Lam] = []
    scripts = {s["id"]: s for s in fw["script"]}
    for sid in FB_SCRIPT_IDS:
        _walk(scripts[sid]["then"], sid, out)
    import yaml
    ivs = [iv for iv in fw["interval"] if INTERVAL_MARK in yaml.dump(iv["then"])]
    if len(ivs) != 1:
        raise ValueError(f"{len(ivs)} intervals mention {INTERVAL_MARK}")
    _walk(ivs[0]["then"], "interval", out)
    boot = fw["esphome"]["on_boot"]["then"]
    _walk([boot[3]], "on_boot", out)
    for sid in scripts_fbb2:
        if sid in scripts:
            _walk(scripts[sid]["then"], sid, out)
    for act in ((fw.get("api") or {}).get("actions") or []):
        if act.get("action") == api_action:
            _walk(act.get("then"), f"api:{api_action}", out, api_params(act))
    for sw in fw.get("switch") or []:
        if sw.get("id") == arm_switch:
            for key in ("turn_on_action", "turn_off_action"):
                spec = sw.get(key)
                if spec is not None:
                    _walk(spec["then"] if isinstance(spec, dict) and "then" in spec else spec,
                          f"switch:{arm_switch}.{key}", out)
    return out


_ID = re.compile(r"\bid\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)(\.?)")


def _subst(code: str, subs: dict) -> str:
    def rep(m):
        key = m.group(1)
        if key not in subs:
            raise ValueError(f"unknown substitution ${{{key}}}")
        return str(subs[key])
    return re.sub(r"\$\{(\w+)\}", rep, code)


_PRE = r"""
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>
#if __cplusplus >= 202002L
#include <span>
#else
// gnu++17 has no std::span (the firmware builds as C++20); a minimal read-only stand-in keeps the same lambdas checkable.
namespace std {
template <class T> class span {
 public:
  constexpr span(const T *p, size_t n) : p_(p), n_(n) {}
  constexpr size_t size() const { return n_; }
  constexpr const T &operator[](size_t i) const { return p_[i]; }
  constexpr const T *data() const { return p_; }
  constexpr const T *begin() const { return p_; }
  constexpr const T *end() const { return p_ + n_; }
 private:
  const T *p_;
  size_t n_;
};
}  // namespace std
#endif
#include "ecco_fallback_capture.h"
#include <algorithm>
#include <cstring>
#include <iterator>
namespace esphome { namespace modbus { enum class ExceptionCode : uint8_t { ILLEGAL_FUNCTION = 1 }; } }
// esphome::StringRef: the type of every `string` api-action variable. The public surface and the operators are those of
// esphome/core/string_ref.h (ESPHome 2026.8.2); c_str() is NOT NUL-terminated and find(const char *) needs it to be.
namespace esphome {
class StringRef {
 public:
  using size_type = size_t;
  using const_reference = const char &;
  using const_pointer = const char *;
  using const_iterator = const_pointer;
  constexpr StringRef() : base_(""), len_(0) {}
  explicit StringRef(const std::string &s) : base_(s.c_str()), len_(s.size()) {}
  explicit StringRef(const char *s) : base_(s), len_(strlen(s)) {}
  constexpr StringRef(const char *s, size_t n) : base_(s), len_(n) {}
  constexpr const_iterator begin() const { return base_; }
  constexpr const_iterator end() const { return base_ + len_; }
  constexpr const char *c_str() const { return base_; }
  constexpr size_type size() const { return len_; }
  constexpr size_type length() const { return len_; }
  constexpr bool empty() const { return len_ == 0; }
  constexpr const_reference operator[](size_type pos) const { return *(base_ + pos); }
  bool starts_with(const StringRef &prefix) const { return len_ >= prefix.len_ && std::memcmp(base_, prefix.base_, prefix.len_) == 0; }
  bool starts_with(const char *prefix) const { return this->starts_with(StringRef(prefix)); }
  bool starts_with(const std::string &prefix) const { return this->starts_with(StringRef(prefix)); }
  std::string str() const { return std::string(base_, len_); }
  const uint8_t *byte() const { return reinterpret_cast<const uint8_t *>(base_); }
  operator std::string() const { return str(); }
  int compare(const StringRef &other) const {
    int result = std::memcmp(base_, other.base_, std::min(len_, other.len_));
    if (result != 0) return result;
    if (len_ < other.len_) return -1;
    if (len_ > other.len_) return 1;
    return 0;
  }
  int compare(const char *s) const { return compare(StringRef(s)); }
  int compare(const std::string &s) const { return compare(StringRef(s)); }
  size_type find(const char *s, size_type pos = 0) const {
    if (pos >= len_) return std::string::npos;
    const char *result = std::strstr(base_ + pos, s);
    if (result && result + std::strlen(s) <= base_ + len_) return static_cast<size_type>(result - base_);
    return std::string::npos;
  }
  size_type find(char c, size_type pos = 0) const {
    if (pos >= len_) return std::string::npos;
    const void *result = std::memchr(base_ + pos, static_cast<unsigned char>(c), len_ - pos);
    return result ? static_cast<size_type>(static_cast<const char *>(result) - base_) : std::string::npos;
  }
  std::string substr(size_type pos = 0, size_type count = std::string::npos) const {
    if (pos >= len_) return std::string();
    size_type actual_count = (count == std::string::npos || pos + count > len_) ? len_ - pos : count;
    return std::string(base_ + pos, actual_count);
  }
 private:
  const char *base_;
  size_type len_;
};
inline bool operator==(const StringRef &lhs, const StringRef &rhs) { return lhs.size() == rhs.size() && std::equal(std::begin(lhs), std::end(lhs), std::begin(rhs)); }
inline bool operator==(const StringRef &lhs, const std::string &rhs) { return lhs.size() == rhs.size() && std::equal(std::begin(lhs), std::end(lhs), std::begin(rhs)); }
inline bool operator==(const std::string &lhs, const StringRef &rhs) { return rhs == lhs; }
inline bool operator==(const StringRef &lhs, const char *rhs) { return lhs.size() == strlen(rhs) && std::equal(std::begin(lhs), std::end(lhs), rhs); }
inline bool operator==(const char *lhs, const StringRef &rhs) { return rhs == lhs; }
inline bool operator!=(const StringRef &lhs, const StringRef &rhs) { return !(lhs == rhs); }
inline bool operator!=(const StringRef &lhs, const std::string &rhs) { return !(lhs == rhs); }
inline bool operator!=(const std::string &lhs, const StringRef &rhs) { return !(rhs == lhs); }
inline bool operator!=(const StringRef &lhs, const char *rhs) { return !(lhs == rhs); }
inline bool operator!=(const char *lhs, const StringRef &rhs) { return !(rhs == lhs); }
inline bool operator<(const StringRef &lhs, const StringRef &rhs) { return std::lexicographical_compare(std::begin(lhs), std::end(lhs), std::begin(rhs), std::end(rhs)); }
inline std::string &operator+=(std::string &lhs, const StringRef &rhs) { lhs.append(rhs.c_str(), rhs.size()); return lhs; }
inline std::string operator+(const char *lhs, const StringRef &rhs) { auto str = std::string(lhs); str.append(rhs.c_str(), rhs.size()); return str; }
inline std::string operator+(const StringRef &lhs, const char *rhs) { auto str = lhs.str(); str.append(rhs); return str; }
inline std::string operator+(const StringRef &lhs, const std::string &rhs) { auto str = lhs.str(); str.append(rhs); return str; }
inline std::string operator+(const std::string &lhs, const StringRef &rhs) { std::string str(lhs); str.append(rhs.c_str(), rhs.size()); return str; }
}  // namespace esphome
using esphome::StringRef;
namespace ecco_durable {
struct ValidMarker { uint32_t magic; uint8_t state; };
constexpr const char *FREE_POWER_VALID_TAG = "tag_fp";
constexpr const char *DUMP_TO_GRID_VALID_TAG = "tag_dump";
constexpr const char *REG244_VALID_TAG = "tag_r244";
inline uint32_t key_for(const char *) { return 7u; }
}
namespace ecco_fbdurable {
struct EspNvs {
  uint32_t handle() const { return 1; }
  int32_t set_blob(uint32_t, const void *, size_t) { return 0; }
  int32_t get_blob(uint32_t, void *, size_t *) { return 0; }
  int32_t get_stats() const { return 0; }
  uint32_t now_us() const { return 0; }
};
inline bool nvs_healthy() { return true; }
}
static uint32_t millis() { return 12345; }
static uint32_t random_uint32() { return 77; }
void esp_log_stub(const char *tag, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
#define ESP_LOGI(tag, ...) esp_log_stub(tag, __VA_ARGS__)
#define ESP_LOGW(tag, ...) esp_log_stub(tag, __VA_ARGS__)
#define ESP_LOGE(tag, ...) esp_log_stub(tag, __VA_ARGS__)
#define ESP_LOGD(tag, ...) esp_log_stub(tag, __VA_ARGS__)
#define ESP_LOGV(tag, ...) esp_log_stub(tag, __VA_ARGS__)
struct TextSensorStub { std::string state; void publish_state(const std::string &s) { state = s; } void publish_state(const char *s) { state = s; } };
struct SwitchStub { bool state = false; void turn_on() { state = true; } void turn_off() { state = false; } void toggle() { state = !state; } void publish_state(bool s) { state = s; } };
struct ESPTimeStub { int64_t timestamp = 0; uint8_t second = 0, minute = 0, hour = 0; bool is_valid() const { return timestamp > 1600000000; } };
struct ClockStub { ESPTimeStub now() { return ESPTimeStub{}; } };
struct ScriptStub { bool is_running() { return false; } void execute() {} };
struct HubStub { bool tx_buffer_empty() { return true; } bool tx_blocked() { return false; } };
template<class T> struct GlobalStub { T v{}; T &value() { return v; } };
"""


def build_source(fw: dict, lams: list[Lam] | None = None, *, type_override: dict | None = None,
                 inject: tuple[str, str] | None = None, rename: tuple[str, str] | None = None,
                 extra_headers: dict | None = None) -> str:
    """The translation unit. `type_override` {global id: C++ type} replaces a global's stub type (a negative control);
    `inject` = (lambda-name substring, C++ text) appends the text to the first matching lambda body; `rename`
    = (old, new) is a textual replace over every body (a misspelled-field control). FB-B2: when a lambda names `ecco_fbsave::`
    the translation unit includes ecco_fallback_save.h (the real header, or `extra_headers[name]` handed to compile_source)."""
    lams = lams if lams is not None else lambdas_of(fw)
    gl = {g["id"]: g["type"] for g in fw["globals"]}
    if type_override:
        gl.update(type_override)
    tsens = {t["id"] for t in fw["text_sensor"] if "id" in t}
    sws = {t["id"] for t in fw["switch"] if "id" in t}
    # FB-B3 Slice A: the Live Match tick reads configuration_online.state, a binary sensor (stubbed like a switch: a bool `state`).
    bsens = {t["id"] for t in (fw.get("binary_sensor") or []) if isinstance(t, dict) and "id" in t}
    clocks = {t["id"] for t in (fw.get("time") or []) if isinstance(t, dict) and "id" in t}
    scripts = {s["id"] for s in fw["script"]}
    used: set[str] = set()

    def rewrite(code: str) -> str:
        def sub(m):
            name, dot = m.group(1), m.group(2)
            used.add(name)
            return (f"g_{name}->value()" if name in gl else name) + ("->" if (dot and name not in gl) else dot)
        return _ID.sub(sub, _subst(code, fw["_substitutions"]))

    funcs = []
    injected = False
    for i, lam in enumerate(lams):
        code = lam.code
        if inject and not injected and inject[0] in lam.name and lam.kind == "void":
            code = code + "\n" + inject[1] + "\n"
            injected = True
        if rename:
            code = code.replace(rename[0], rename[1])
        body = rewrite(code)
        if lam.kind == "bool" and "return" not in body:
            body = "return " + body
        params = ", ".join(f"[[maybe_unused]] {p.strip()}" for p in lam.params.split(",") if p.strip())
        fname = "lam_%03d_%s" % (i, re.sub(r"\W", "_", lam.name))
        funcs.append(f"{lam.kind} {fname}({params}) {{\n{body}\n}}\n")
    if inject and not injected:
        raise ValueError(f"inject target {inject[0]!r} matched no void lambda")
    decls = []
    for name in sorted(used):
        if name in gl:
            decls.append(f"static GlobalStub<{gl[name]}> g_{name}_o; static GlobalStub<{gl[name]}> *g_{name} = &g_{name}_o;")
        elif name in tsens:
            decls.append(f"static TextSensorStub {name}_o; static TextSensorStub *{name} = &{name}_o;")
        elif name in sws or name in bsens:
            decls.append(f"static SwitchStub {name}_o; static SwitchStub *{name} = &{name}_o;")
        elif name in clocks:
            decls.append(f"static ClockStub {name}_o; static ClockStub *{name} = &{name}_o;")
        elif name in scripts:
            decls.append(f"static ScriptStub {name}_o; static ScriptStub *{name} = &{name}_o;")
        elif name == "inverter_modbus":
            decls.append(f"static HubStub {name}_o; static HubStub *{name} = &{name}_o;")
        else:
            raise ValueError(f"a lambda references id({name}), which the stub set does not know")
    pre = _PRE
    if any("ecco_fbsave::" in f for f in funcs):
        pre = pre.replace('#include "ecco_fallback_capture.h"\n', f'#include "ecco_fallback_capture.h"\n#include "{SAVE_HEADER}"\n', 1)
    return pre + "\n".join(decls) + "\n\n" + "\n".join(funcs) + "\nint main() { return 0; }\n"


def compile_source(src: str, std: str, cxx: str | None = None, extra_headers: dict | None = None) -> tuple[int, str]:
    """(returncode, compiler output). returncode 127 and NO_CXX when no compiler exists. `extra_headers` {name: text} are
    written next to the TU and win over the real header of that name (a stand-in for a header that does not exist yet)."""
    cxx = cxx or find_compiler()
    if cxx is None:
        return 127, NO_CXX
    extra_headers = dict(extra_headers or {})
    with tempfile.TemporaryDirectory(prefix="fbb1_cpp_") as d:
        tmp = Path(d)
        (tmp / "tu.cpp").write_text(src, encoding="utf-8", newline="\n")
        names = list(HEADERS) + ([SAVE_HEADER] if f'#include "{SAVE_HEADER}"' in src else [])
        for h in names:
            if h in extra_headers:
                continue
            if not (INCLUDE / h).is_file():
                return 2, f"the translation unit includes {h}, which does not exist in firmware/include (and no extra header supplies it)"
            (tmp / h).write_bytes((INCLUDE / h).read_bytes())
        for h, text in extra_headers.items():
            (tmp / h).write_text(text, encoding="utf-8", newline="\n")
        r = subprocess.run([cxx, f"-std={std}", *FLAGS, "-I", str(tmp), str(tmp / "tu.cpp")], capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr)


def compile_all(fw: dict, stds=STDS, extra_headers: dict | None = None, **build_kw) -> list[str]:
    """[] when every FB lambda compiles clean under every standard; else one entry per failing standard."""
    src = build_source(fw, **build_kw)
    cxx = find_compiler()
    if cxx is None:
        return [NO_CXX]
    with ThreadPoolExecutor(max_workers=len(stds)) as pool:
        results = list(pool.map(lambda s: compile_source(src, s, cxx, extra_headers), stds))
    return [f"{std}: rc {rc}: {out.strip()[:700]}" for std, (rc, out) in zip(stds, results) if rc != 0]


def compile_rejects(fw: dict, needle: str, std: str = "gnu++20", extra_headers: dict | None = None, **build_kw) -> tuple[bool, str]:
    """A NEGATIVE CONTROL: the (deliberately broken) source must be rejected by the compiler itself - rc != 0, an
    `error:` line, and the compiler's own message mentions `needle`. Never true without a compiler."""
    cxx = find_compiler()
    if cxx is None:
        return False, NO_CXX
    rc, out = compile_source(build_source(fw, **build_kw), std, cxx, extra_headers)
    # GCC prints typographic quotes (U+2018 / U+2019 / U+201C / U+201D) in its diagnostics in a UTF-8 locale (e.g. on the Ubuntu CI runners)
    # and ASCII quotes elsewhere (e.g. this Windows build): normalise them to ASCII before matching, so the needles stay exact ASCII.
    out = out.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})
    ok = rc != 0 and "error:" in out and needle in out
    return ok, out.strip()[:500]
