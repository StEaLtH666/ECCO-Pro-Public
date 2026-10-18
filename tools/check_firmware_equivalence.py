#!/usr/bin/env python3
"""Firmware S0 equivalence checker: is the firmware AFTER exactly the firmware BEFORE? (fails closed, offline only).

S0 of the firmware modularisation proposal: before any future YAML split, a tool must be able to show that a change
of source LAYOUT is not a change of BEHAVIOUR. This tool compares two firmware trees (a git ref, or a directory holding
a `firmware/` tree) and reports a proof matrix. It changes nothing: it reads the two trees, works only in its own
temporary directories, and never writes inside the repository.

Layers (every check is STRICT: nothing is normalised, a difference is a FAIL, never a warning):

  L0 source      the byte content (sha256) of every firmware/*.yaml and firmware/include/*.h, and the set of file names.
                 `secrets.yaml` is never read: it is skipped by name, and every sandbox gets CI-style PLACEHOLDER secrets.
  L1 inventory   pure Python, no ESPHome. The production YAML and the ESP32-S3 wrapper are parsed (ESPHome tags kept as
                 typed values, `!lambda` distinct from plain text) and compared as ORDERED inventories: top-level key
                 order; substitutions (key and value, in order); for every list section the item order with a digest of
                 each item (so a one-character lambda edit, a changed value or a swapped pair is caught and located);
                 every declared id in document order; entities (section, platform, id, name); API actions and their
                 variables; globals with restore_value; the interval block in order (period, startup delay, digest);
                 the `esphome: includes:` list; the durable tags the headers declare (registry/tests/_tag_inventory.py).
  L2 authority   tools/analyze_write_surface.analyze() on each side (unchanged, imported read-only): every write path
                 with its Modbus operations, ownership flags, arm switches, obligations and dispatches, compared exactly.
                 Fail closed: if EITHER side has a write of unknown extent or an unclassified bus access, the row FAILS
                 even when both sides agree, because the write surface is then not established at all.
  L3 generated   optional (`--generate`): ESPHome `config` and `compile --only-generate` for the classic and the S3 target.
                 Both sides run one after the other in the SAME absolute sandbox path (emptied in between), so the
                 sandbox paths ESPHome echoes into comments are identical without any rewriting. The whole generated
                 `src/` tree (main.cpp, esphome/core/defines.h and every other file) must be byte-identical, and so must
                 the validated configuration ESPHome prints and the App config hash (ESPHOME_CONFIG_HASH). ONE declared
                 exclusion, always listed as its own report row: the two build-time lines ESPHome writes from the wall
                 clock into esphome/core/build_info_data.cpp (no SOURCE_DATE_EPOCH support in 2026.8.2); every other line
                 of that file is still compared. Requires ESPHome exactly 2026.8.2 (the firmware static_asserts
                 < 2026.9.0); any other version is BLOCKED.
                 ESPHome fetches library sources from the PlatformIO registry while generating. L3 therefore runs only
                 with `--esphome-cache DIR` (a pio_components/ seed copied into each sandbox, no download expected) or
                 with `--allow-toolchain-downloads`; every download URL is reported, and a download despite a seeded
                 cache FAILS. ESPHome runs with PYTHONHASHSEED=0: `esphome config` prints some keys in hash-seed order
                 (the generated C++ and the config hash were observed seed-independent). The generated hashes depend on
                 the sandbox path (ESPHome echoes include paths into comments), so a baseline that must be reproduced
                 later uses `--sandbox <fixed path>`.

What L3 runs and why it cannot reach a device: only `esphome version`, `esphome config <yaml>` and
`esphome compile --only-generate <yaml>`. These subcommands do not upload, flash, open a serial port, open logs or talk to
the API; the argv list is fixed in this file (ESPHOME_COMMANDS) and checked by the test suite. The sandbox holds copies of
the firmware files and placeholder secrets only; ESPHOME_DATA_DIR points into the sandbox.

Exit codes: 0 every check PASS; 1 at least one FAIL; 2 usage or input error; 3 BLOCKED (a requested layer could not run,
for example ESPHome missing or the wrong version). A BLOCKED or NOT-RUN layer is never reported as PASS.

    python tools/check_firmware_equivalence.py --before d1c9a3e1 --after HEAD
    python tools/check_firmware_equivalence.py --before d1c9a3e1 --after HEAD --generate --baseline-out <file outside repo>
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import analyze_write_surface as aws  # noqa: E402  (read-only use)
import _tag_inventory as tags  # noqa: E402  (read-only use)

PROD = "ecco_clock_dongle_stage3_4_free_power.yaml"
S3 = "ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml"
TARGETS = {"classic": PROD, "s3": S3}
ESPHOME_VERSION = "2026.8.2"
NODE_NAME = "ecco-clock-dongle"
NEVER_READ = frozenset({"secrets.yaml"})
# Identical to registry/tests/check_esp32s3_equivalence.py and the CI firmware job: no real value.
PLACEHOLDER_SECRETS = (
    'wifi_ssid: "ci-test"\nwifi_password: "ci-test-password"\n'
    'ecco_api_key: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="\necco_ota_password: "ci-test-password"\n'
)
# The ONLY ESPHome invocations this tool can make (test_firmware_equivalence.py pins this).
ESPHOME_COMMANDS = {
    "version": ("esphome", "version"),
    "config": ("esphome", "config"),
    "generate": ("esphome", "compile", "--only-generate"),
}
ENTITY_SECTIONS = ("number", "switch", "select", "binary_sensor", "text_sensor", "sensor", "button")


class InputError(Exception):
    pass


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@dataclass
class Tree:
    label: str
    files: dict[str, bytes]  # path relative to firmware/ (e.g. "include/ecco_rtc_policy.h") -> bytes

    def text(self, rel: str) -> str:
        if rel not in self.files:
            raise InputError(f"{self.label}: firmware/{rel} is missing")
        return self.files[rel].decode("utf-8")


def _wanted(rel: str) -> bool:
    if Path(rel).name in NEVER_READ:
        return False
    parts = rel.split("/")
    return (len(parts) == 1 and rel.endswith(".yaml")) or (len(parts) == 2 and parts[0] == "include" and rel.endswith(".h"))


def load_tree(spec: str, repo: Path = ROOT) -> Tree:
    """`spec` is a directory that contains `firmware/` (or is one), or a git revision of `repo`. Git blobs are read
    exactly as committed (`git cat-file`), so no checkout and no line-ending conversion is involved."""
    p = Path(spec)
    if p.is_dir():
        fw = p / "firmware" if (p / "firmware").is_dir() else p
        files = {}
        for f in sorted(fw.rglob("*")):
            rel = f.relative_to(fw).as_posix()
            if f.is_file() and _wanted(rel):
                files[rel] = f.read_bytes()
        if PROD not in files:
            raise InputError(f"{spec}: no firmware/{PROD}")
        return Tree(f"dir:{p}", files)
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{spec}^{{commit}}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise InputError(f"{spec!r} is neither a directory nor a commit of {repo}")
    commit = r.stdout.strip()
    ls = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", commit, "--", "firmware/"],
                        capture_output=True, text=True, check=True).stdout.splitlines()
    files = {}
    for path in ls:
        rel = path[len("firmware/"):]
        if _wanted(rel):
            files[rel] = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
                                        capture_output=True, check=True).stdout
    if PROD not in files:
        raise InputError(f"{spec}: no firmware/{PROD}")
    return Tree(f"git:{commit}", files)


def sha(b: bytes | str) -> str:
    return hashlib.sha256(b.encode("utf-8") if isinstance(b, str) else b).hexdigest()


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class Row:
    layer: str
    check: str
    target: str
    status: str  # PASS | FAIL | BLOCKED | NOT-RUN
    detail: str = ""


@dataclass
class Report:
    before: str
    after: str
    rows: list[Row] = field(default_factory=list)
    baseline: dict = field(default_factory=dict)

    def add(self, layer, check, target, ok, detail=""):
        self.rows.append(Row(layer, check, target, "PASS" if ok else "FAIL", "" if ok else detail))

    def mark(self, layer, check, target, status, detail):
        self.rows.append(Row(layer, check, target, status, detail))

    def exit_code(self) -> int:
        st = {r.status for r in self.rows}
        if "FAIL" in st:
            return 1
        if "BLOCKED" in st:
            return 3
        return 0


# ---------------------------------------------------------------------------
# L1 inventory
# ---------------------------------------------------------------------------


class Lambda(str):
    """A `!lambda` scalar: same text as a plain string, never equal to one in a digest."""


class _Loader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    pass


def _tagged(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        v = loader.construct_scalar(node)
        return Lambda(v) if suffix == "lambda" else {"!" + suffix: v}
    if isinstance(node, yaml.SequenceNode):
        return {"!" + suffix: loader.construct_sequence(node, deep=True)}
    return {"!" + suffix: loader.construct_mapping(node, deep=True)}


_Loader.add_multi_constructor("!", _tagged)


def parse(text: str):
    doc = yaml.load(text, Loader=_Loader)
    if not isinstance(doc, dict):
        raise InputError("firmware YAML is not a mapping")
    return doc


def canon(obj):
    """A JSON-safe, type-preserving form: mapping key ORDER is kept (YAML order is part of the source), a Lambda is
    tagged, and Python types are spelled out so 1, 1.0, "1" and True never collide."""
    if isinstance(obj, Lambda):
        return ["lambda", str(obj)]
    if isinstance(obj, dict):
        return ["map", [[canon(k), canon(v)] for k, v in obj.items()]]
    if isinstance(obj, list):
        return ["seq", [canon(v) for v in obj]]
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return [type(obj).__name__, repr(obj) if isinstance(obj, float) else obj]
    return [type(obj).__name__, repr(obj)]


def digest(obj) -> str:
    return sha(json.dumps(canon(obj), ensure_ascii=False, separators=(",", ":")))


def _ids(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "id" and isinstance(v, str):
                out.append(v)
            _ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _ids(v, out)
    return out


def _lambdas(obj, out):
    """Every C++ body: `!lambda` scalars and the value of every `lambda:` action key, in document order."""
    if isinstance(obj, Lambda):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k == "lambda" and isinstance(v, str) and not isinstance(v, Lambda):
                out.append(v)
            else:
                _lambdas(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _lambdas(v, out)
    return out


def inventory(doc: dict, headers: dict[str, str]) -> dict:
    inv: dict = {"top_level_order": list(doc)}
    subs = doc.get("substitutions") or {}
    inv["substitutions"] = [[k, canon(v)] for k, v in subs.items()] if isinstance(subs, dict) else canon(subs)
    sections = {}
    for k, v in doc.items():
        if isinstance(v, list):
            sections[k] = [[(it.get("id") if isinstance(it, dict) else None), digest(it)] for it in v]
        else:
            sections[k] = digest(v)
    inv["sections"] = sections
    inv["ids"] = _ids(doc, [])
    inv["entities"] = [[s, it.get("platform"), it.get("id"), it.get("name")]
                       for s in ENTITY_SECTIONS for it in (doc.get(s) or []) if isinstance(it, dict)]
    api = doc.get("api") or {}
    acts = api.get("actions", api.get("services", [])) if isinstance(api, dict) else []
    inv["api_actions"] = [[a.get("action", a.get("service")), canon(a.get("variables"))] for a in acts or []]
    inv["restored_globals"] = [[g.get("id"), canon(g.get("type")), canon(g.get("initial_value"))]
                               for g in doc.get("globals") or []
                               if isinstance(g, dict) and str(g.get("restore_value")).lower() in ("true", "yes", "on")]
    inv["intervals"] = [[canon(i.get("interval")), canon(i.get("startup_delay")), digest(i)]
                        for i in doc.get("interval") or [] if isinstance(i, dict)]
    esp = doc.get("esphome") or {}
    inv["includes"] = list(esp.get("includes") or []) if isinstance(esp, dict) else []
    inv["header_tags"] = {rel: [list(t) for t in tags.inventory(text)] for rel, text in sorted(headers.items())}
    lams = _lambdas(doc, [])
    inv["lambda_count"] = len(lams)
    inv["lambda_digest"] = sha("\0".join(lams))
    return inv


def _first_list_diff(a: list, b: list, what: str) -> str:
    if len(a) != len(b):
        extra = [x for x in b if x not in a][:3]
        missing = [x for x in a if x not in b][:3]
        return f"{what}: {len(a)} -> {len(b)} entries; added {extra}; removed {missing}"
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            same_set = sorted(map(json.dumps, a)) == sorted(map(json.dumps, b))
            kind = "ORDER changed (same entries, different positions)" if same_set else "content changed"
            return f"{what}: {kind}; first difference at index {i}: {str(x)[:160]} -> {str(y)[:160]}"
    return f"{what}: differs"


def compare_inventories(rep: Report, target: str, ia: dict, ib: dict) -> None:
    for key in ("top_level_order", "substitutions", "ids", "entities", "api_actions", "restored_globals", "intervals",
                "includes"):
        a, b = ia[key], ib[key]
        rep.add("L1", f"{key} identical (ordered)", target, a == b,
                _first_list_diff(a, b, key) if isinstance(a, list) and isinstance(b, list) else f"{key} differs")
    sa, sb = ia["sections"], ib["sections"]
    if list(sa) != list(sb):
        rep.add("L1", "section items identical (ordered, per-item digest)", target, False,
                f"section set/order differs: {list(sa)} -> {list(sb)}")
    else:
        bad = [k for k in sa if sa[k] != sb[k]]
        detail = ""
        if bad:
            k = bad[0]
            detail = (_first_list_diff(sa[k], sb[k], f"section {k!r}") if isinstance(sa[k], list) and isinstance(sb[k], list)
                      else f"section {k!r} content differs") + (f" (also: {bad[1:6]})" if len(bad) > 1 else "")
        rep.add("L1", "section items identical (ordered, per-item digest)", target, not bad, detail)
    rep.add("L1", "lambda text identical (count + digest)", target,
            (ia["lambda_count"], ia["lambda_digest"]) == (ib["lambda_count"], ib["lambda_digest"]),
            f"{ia['lambda_count']} -> {ib['lambda_count']} lambdas, digest {ia['lambda_digest'][:12]} -> {ib['lambda_digest'][:12]}")
    rep.add("L1", "header durable-tag inventory identical", target, ia["header_tags"] == ib["header_tags"],
            "durable tags declared by firmware/include/*.h differ")


# ---------------------------------------------------------------------------
# L2 authority (tools/analyze_write_surface.py, unchanged)
# ---------------------------------------------------------------------------


def _materialise(tree: Tree, dest: Path, with_secrets: bool) -> Path:
    fw = dest / "firmware"
    (fw / "include").mkdir(parents=True, exist_ok=True)
    for rel, data in tree.files.items():
        out = fw / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    if with_secrets:
        (fw / "secrets.yaml").write_text(PLACEHOLDER_SECRETS, encoding="ascii", newline="\n")
    return fw


_AUTH_CACHE: dict[str, dict] = {}


def authority(tree: Tree) -> dict:
    """Cached by the exact bytes of every firmware file (a pure function of them)."""
    key = sha("".join(f"{rel}|{sha(data)}|" for rel, data in sorted(tree.files.items())))
    if key not in _AUTH_CACHE:
        _AUTH_CACHE[key] = _authority(tree)
    return _AUTH_CACHE[key]


def _authority(tree: Tree) -> dict:
    with tempfile.TemporaryDirectory(prefix="ecco_fw_equiv_auth_") as td:
        fw = _materialise(tree, Path(td), with_secrets=False)
        res = aws.analyze(fw / PROD)
        prefix = str(fw)

        def scrub(rows):
            return [{k: (str(v).replace(prefix, "<fw>") if isinstance(v, str) else v) for k, v in r.items()} for r in rows]

        paths = []
        for p in res["paths"]:
            paths.append({
                "name": p.name, "kind": p.kind,
                "ops": [[o.kind, o.start_address, o.count, o.value_expr, o.extent_unknown_reason] for o in p.ops],
                "acquires": sorted(p.acquires), "checks": sorted(p.checks), "releases": sorted(p.releases),
                "arms_checked": sorted(p.arms_checked), "obligations_set": sorted(p.obligations_set),
                "obligations_cleared": sorted(p.obligations_cleared), "delays_ms": p.delays_ms,
                "dispatches": p.dispatches, "wait_untils": len(p.wait_until_offsets),
                "durable_commits": len(p.durable_commit_offsets),
            })
        return {"paths": paths, "unknown_extent_writes": scrub(res["unknown_extent_writes"]),
                "bus_access_findings": scrub(res["bus_access_findings"])}


def compare_authority(rep: Report, aa: dict, ab: dict) -> None:
    for side, a in (("before", aa), ("after", ab)):
        problems = a["unknown_extent_writes"] + a["bus_access_findings"]
        rep.add("L2", f"write surface determinable ({side})", "classic+s3", not problems,
                f"{len(problems)} unknown-extent / unclassified bus access: {problems[:3]}")
    na = [p["name"] for p in aa["paths"]]
    nb = [p["name"] for p in ab["paths"]]
    rep.add("L2", "write paths identical (names, order)", "classic+s3", na == nb, _first_list_diff(na, nb, "write paths"))
    bad = [x["name"] for x, y in zip(aa["paths"], ab["paths"]) if x != y]
    rep.add("L2", "per-path Modbus ops, flags, arms, obligations identical", "classic+s3", na == nb and not bad,
            f"differs in: {bad[:6]}")


# ---------------------------------------------------------------------------
# L3 generated (ESPHome)
# ---------------------------------------------------------------------------


def esphome_version() -> str | None:
    exe = shutil.which("esphome")
    if not exe:
        return None
    r = subprocess.run(list(ESPHOME_COMMANDS["version"]), capture_output=True, text=True)
    m = re.search(r"Version:\s*(\S+)", r.stdout + r.stderr)
    return m.group(1) if m else None


def _run_esphome(kind: str, yaml_name: str, fw: Path, data_dir: Path) -> subprocess.CompletedProcess:
    # PYTHONHASHSEED is fixed because `esphome config` 2026.8.2 prints some keys in hash-seed order (observed: two
    # orderings of `tag: main` lines across seeds 0-11). This fixes the toolchain's input; no output is rewritten. The
    # generated C++, defines.h and the config hash were observed seed-independent (seeds 0, 3, 8, 9).
    env = dict(os.environ, ESPHOME_DATA_DIR=str(data_dir), PYTHONHASHSEED="0")
    return subprocess.run([*ESPHOME_COMMANDS[kind], yaml_name], cwd=fw, env=env, capture_output=True, text=True)


# ESPHome 2026.8.2 writes the wall-clock build time into this one generated file (esphome/writer.py get_build_info:
# `int(time.time())`, no SOURCE_DATE_EPOCH). These two line shapes are the ONLY generated difference the tool accepts,
# and the report always lists the exclusion as its own row. The config hash in the same file is still compared.
BUILD_INFO = "esphome/core/build_info_data.cpp"
BUILD_TIME_LINE = re.compile(r'^const (time_t ESPHOME_BUILD_TIME = \d+;|char ESPHOME_BUILD_TIME_STR\[\] (PROGMEM )?= "[^"]*";)  // NOLINT$|'
                             r'^const char ESPHOME_BUILD_TIME_STR\[\] (PROGMEM )?= "[^"]*";$')
CONFIG_HASH_LINE = re.compile(r"^const uint32_t ESPHOME_CONFIG_HASH = (0x[0-9a-fA-F]+)U;")
DOWNLOAD_LINE = re.compile(r"Downloading (\S+)")


def generate(tree: Tree, target: str, work: Path, cache: Path | None) -> dict:
    """Generated sources and the validated config of one target. `work` must not exist; both sides of a comparison
    use the SAME `work` path one after the other, so absolute paths ESPHome echoes into comments are identical
    without any rewriting. `cache` (optional) holds a `pio_components/` seed copied in first, so ESPHome need not
    download its library sources. Raises InputError on failure."""
    fw = _materialise(tree, work, with_secrets=True)
    yaml_name = TARGETS[target]
    data_dir = work / "esphome_data"
    if cache is not None and (cache / "pio_components").is_dir():
        shutil.copytree(cache / "pio_components", data_dir / "pio_components")
    cfg = _run_esphome("config", yaml_name, fw, data_dir)
    if cfg.returncode != 0:
        raise InputError(f"esphome config failed for {tree.label} {target}: {(cfg.stdout + cfg.stderr)[-1500:]}")
    gen = _run_esphome("generate", yaml_name, fw, data_dir)
    if gen.returncode != 0:
        raise InputError(f"esphome generate failed for {tree.label} {target}: {(gen.stdout + gen.stderr)[-1500:]}")
    src = data_dir / "build" / NODE_NAME / "src"
    if not (src / "main.cpp").is_file():
        raise InputError(f"no generated main.cpp under {src}")
    files = {f.relative_to(src).as_posix(): f.read_bytes() for f in sorted(src.rglob("*")) if f.is_file()}
    chash = None
    for ln in files.get(BUILD_INFO, b"").decode("utf-8", "replace").splitlines():
        if m := CONFIG_HASH_LINE.match(ln):
            chash = m.group(1).lower()
    downloads = DOWNLOAD_LINE.findall(cfg.stdout + cfg.stderr + gen.stdout + gen.stderr)
    return {"files": files, "config": cfg.stdout, "config_hash": chash, "downloads": downloads,
            "pio_components": data_dir / "pio_components"}


def build_info_diff(a: bytes, b: bytes) -> tuple[list[str], int]:
    """(differing lines that are NOT a declared build-time line, number of declared build-time lines that differ)."""
    la, lb = a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines()
    if len(la) != len(lb):
        return [f"line count {len(la)} -> {len(lb)}"], 0
    bad, excluded = [], 0
    for x, y in zip(la, lb):
        if x == y:
            continue
        if BUILD_TIME_LINE.match(x.strip()) and BUILD_TIME_LINE.match(y.strip()):
            excluded += 1
        else:
            bad.append(f"{x[:100]} -> {y[:100]}")
    return bad, excluded


def _line_diff(a: bytes, b: bytes, n: int = 4) -> list[str]:
    out = []
    for ln in difflib.unified_diff(a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines(),
                                   lineterm="", n=0):
        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")):
            out.append(ln[:160])
            if len(out) >= n:
                break
    return out


def compare_generated(rep: Report, target: str, ga: dict, gb: dict) -> None:
    fa, fb = ga["files"], gb["files"]
    rep.add("L3", "generated src/ file set identical", target, list(fa) == list(fb),
            f"added {sorted(set(fb) - set(fa))[:5]}, removed {sorted(set(fa) - set(fb))[:5]}")
    for rel in ("main.cpp", "esphome/core/defines.h"):
        a, b = fa.get(rel), fb.get(rel)
        rep.add("L3", f"{rel} byte-identical", target, a is not None and a == b,
                "missing" if a is None or b is None else f"sha {sha(a)[:12]} -> {sha(b)[:12]}: {_line_diff(a, b)}")
    other = [r for r in fa if r in fb and fa[r] != fb[r] and r not in ("main.cpp", "esphome/core/defines.h", BUILD_INFO)]
    rep.add("L3", f"every other generated file byte-identical ({len(fa) - 3} files)", target, not other,
            f"differs: {other[:6]}")
    if BUILD_INFO in fa and BUILD_INFO in fb:
        bad, excluded = build_info_diff(fa[BUILD_INFO], fb[BUILD_INFO])
        rep.add("L3", f"{BUILD_INFO} identical apart from the build time", target, not bad, f"{bad[:4]}")
        rep.mark("L3", "DECLARED EXCLUSION: build time (ESPHOME_BUILD_TIME / _STR)", target, "PASS" if not bad else "FAIL",
                 f"{excluded} build-time line(s) differ; wall clock written by ESPHome, not by the firmware source")
    else:
        rep.add("L3", f"{BUILD_INFO} present on both sides", target, False, "missing")
    rep.add("L3", "validated config (esphome config) identical", target, ga["config"] == gb["config"],
            f"{_line_diff(ga['config'].encode(), gb['config'].encode())}")
    ha, hb = ga["config_hash"], gb["config_hash"]
    rep.add("L3", "App config hash identical (ESPHOME_CONFIG_HASH)", target, ha is not None and ha == hb,
            f"{ha} -> {hb}")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run(before: "str | Tree", after: "str | Tree", do_generate: bool = False, repo: Path = ROOT, cache: Path | None = None,
        allow_downloads: bool = False, sandbox: Path | None = None) -> Report:
    ta = before if isinstance(before, Tree) else load_tree(before, repo)
    tb = after if isinstance(after, Tree) else load_tree(after, repo)
    rep = Report(ta.label, tb.label)
    bl = rep.baseline
    bl["toolchain"] = {"python": platform.python_version(), "pyyaml": yaml.__version__,
                       "libyaml": bool(getattr(yaml, "__with_libyaml__", False))}
    bl["sources"] = {t.label: {rel: sha(data) for rel, data in sorted(t.files.items())} for t in (ta, tb)}

    # L0
    rep.add("L0", "firmware file set identical", "classic+s3", sorted(ta.files) == sorted(tb.files),
            f"added {sorted(set(tb.files) - set(ta.files))}, removed {sorted(set(ta.files) - set(tb.files))}")
    changed = [r for r in sorted(set(ta.files) & set(tb.files)) if ta.files[r] != tb.files[r]]
    rep.add("L0", "firmware file bytes identical (sha256, no line-ending normalisation)", "classic+s3", not changed,
            f"changed: {changed}")

    # L1
    for target, name in TARGETS.items():
        if name not in ta.files or name not in tb.files:
            rep.add("L1", "target YAML present on both sides", target, False, f"firmware/{name} missing")
            continue
        heads_a = {r: ta.text(r) for r in ta.files if r.startswith("include/")}
        heads_b = {r: tb.text(r) for r in tb.files if r.startswith("include/")}
        ia, ib = inventory(parse(ta.text(name)), heads_a), inventory(parse(tb.text(name)), heads_b)
        bl.setdefault("inventory", {})[target] = {
            "ids": len(ib["ids"]), "entities": len(ib["entities"]), "api_actions": [a[0] for a in ib["api_actions"]],
            "restored_globals": [g[0] for g in ib["restored_globals"]], "intervals": len(ib["intervals"]),
            "lambdas": ib["lambda_count"], "lambda_digest": ib["lambda_digest"],
            "sections": {k: (len(v) if isinstance(v, list) else "map") for k, v in ib["sections"].items()},
            "header_tags": sum(len(v) for v in ib["header_tags"].values()),
        }
        compare_inventories(rep, target, ia, ib)

    # L2 (the analyser models the production YAML; the S3 wrapper adds no logic and is covered by L0/L1/L3)
    aa, ab = authority(ta), authority(tb)
    bl["authority"] = {"write_paths": len(ab["paths"]),
                       "write_ops": sum(1 for p in ab["paths"] for o in p["ops"] if o[0] == "write"),
                       "read_ops": sum(1 for p in ab["paths"] for o in p["ops"] if o[0] == "read"),
                       "digest": digest(ab["paths"])}
    compare_authority(rep, aa, ab)

    # L3
    if not do_generate:
        for target in TARGETS:
            rep.mark("L3", "generated C++ / validated config", target, "NOT-RUN", "not requested (--generate)")
        return rep
    ver = esphome_version()
    bl["toolchain"]["esphome"] = ver
    if ver != ESPHOME_VERSION:
        for target in TARGETS:
            rep.mark("L3", "generated C++ / validated config", target, "BLOCKED",
                     f"ESPHome {ESPHOME_VERSION} required, found {ver or 'none on PATH'}")
        return rep
    have_cache = cache is not None and (cache / "pio_components").is_dir()
    if not have_cache and not allow_downloads:
        for target in TARGETS:
            rep.mark("L3", "generated C++ / validated config", target, "BLOCKED",
                     "ESPHome fetches library sources (PlatformIO registry) while generating: pass --esphome-cache DIR "
                     "holding pio_components/, or --allow-toolchain-downloads to permit (and record) the download")
        return rep
    bl["commands"] = [" ".join(ESPHOME_COMMANDS[k]) + " <target yaml>" for k in ("config", "generate")]
    bl["declared_exclusions"] = [f"{BUILD_INFO}: ESPHOME_BUILD_TIME and ESPHOME_BUILD_TIME_STR (wall clock)"]
    downloads: list[str] = []
    bl["toolchain"]["PYTHONHASHSEED"] = "0 (ESPHome subprocesses)"
    if sandbox is not None:
        if sandbox.exists():
            raise InputError(f"--sandbox {sandbox} must not exist (the tool creates it and removes it afterwards)")
        sandbox.mkdir(parents=True)
        root = sandbox
    else:
        root = Path(tempfile.mkdtemp(prefix="ecco_fw_equiv_"))
    bl["sandbox"] = "fixed (--sandbox): generated hashes reproducible at this path" if sandbox is not None else \
        "random temp dir: main.cpp / config-hash baselines are path-dependent (comments, includes)"
    try:
        work = root / "w"  # the same absolute path for every run, emptied in between
        for target in TARGETS:
            outs = []
            for tree in (ta, tb):
                if work.exists():
                    shutil.rmtree(work)
                try:
                    g = generate(tree, target, work, cache if have_cache else None)
                except InputError as exc:
                    rep.mark("L3", "generated C++ / validated config", target, "BLOCKED", str(exc)[:600])
                    break
                downloads += g["downloads"]
                if not have_cache and cache is not None and g["pio_components"].is_dir():
                    shutil.copytree(g["pio_components"], cache / "pio_components")
                    have_cache = True
                g.pop("pio_components")
                outs.append(g)
            if len(outs) != 2:
                continue
            ga, gb = outs
            bl.setdefault("generated", {})[target] = {
                "main.cpp": sha(gb["files"]["main.cpp"]),
                "defines.h": sha(gb["files"].get("esphome/core/defines.h", b"")),
                "src_tree_excluding_build_info": digest(sorted((r, sha(d)) for r, d in gb["files"].items() if r != BUILD_INFO)),
                "src_files": len(gb["files"]),
                "validated_config": sha(gb["config"]),
                "config_hash": gb["config_hash"],
            }
            compare_generated(rep, target, ga, gb)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bl["toolchain_downloads"] = sorted(set(downloads))
    rep.mark("L3", "toolchain downloads during generation", "classic+s3",
             "PASS" if not downloads or allow_downloads else "FAIL",
             (f"{len(set(downloads))} download(s), permitted by --allow-toolchain-downloads: {sorted(set(downloads))}"
              if downloads and allow_downloads else
              f"unexpected download(s) with a seeded cache: {sorted(set(downloads))}" if downloads else
              "none (library sources taken from the --esphome-cache seed)"))
    return rep


def render(rep: Report) -> str:
    lines = [f"ECCO firmware equivalence: before={rep.before} after={rep.after}", ""]
    w = max(len(r.check) for r in rep.rows)
    for r in rep.rows:
        lines.append(f"  {r.status:8s} {r.layer}  {r.target:11s} {r.check:{w}s}  {r.detail}".rstrip())
    counts = {s: sum(1 for r in rep.rows if r.status == s) for s in ("PASS", "FAIL", "BLOCKED", "NOT-RUN")}
    lines += ["", "  " + "  ".join(f"{k} {v}" for k, v in counts.items())]
    verdict = {0: "EQUIVALENT on every layer that ran", 1: "NOT EQUIVALENT", 3: "BLOCKED: a requested layer could not run"}
    lines.append("  verdict: " + verdict[rep.exit_code()])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--before", required=True, help="git revision of this repository, or a directory with firmware/")
    ap.add_argument("--after", required=True, help="git revision of this repository, or a directory with firmware/")
    ap.add_argument("--generate", action="store_true", help="also run the ESPHome L3 layer (ESPHome 2026.8.2)")
    ap.add_argument("--json", action="store_true", help="print the rows and baseline as JSON")
    ap.add_argument("--baseline-out", type=Path, help="write the baseline JSON here (refused inside the repository)")
    ap.add_argument("--esphome-cache", type=Path,
                    help="directory (outside the repository) holding pio_components/ to seed each L3 sandbox; with "
                         "--allow-toolchain-downloads an empty one is filled by the first run")
    ap.add_argument("--allow-toolchain-downloads", action="store_true",
                    help="permit ESPHome to download library sources while generating (each URL is reported)")
    ap.add_argument("--sandbox", type=Path,
                    help="fixed L3 sandbox path (outside the repository, must not exist; removed afterwards) so the "
                         "path-dependent generated hashes in the baseline are reproducible")
    args = ap.parse_args(argv)
    for opt in ("baseline_out", "esphome_cache", "sandbox"):
        p = getattr(args, opt)
        if p is not None and (p.resolve() == ROOT or ROOT in p.resolve().parents):
            print(f"refused: --{opt.replace('_', '-')} must be outside the repository (the tool never writes into it)",
                  file=sys.stderr)
            return 2
    if args.esphome_cache is not None:
        args.esphome_cache.mkdir(parents=True, exist_ok=True)
    try:
        rep = run(args.before, args.after, args.generate, cache=args.esphome_cache,
                  allow_downloads=args.allow_toolchain_downloads, sandbox=args.sandbox)
    except InputError as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    payload = {"before": rep.before, "after": rep.after, "exit_code": rep.exit_code(),
               "rows": [r.__dict__ for r in rep.rows], "baseline": rep.baseline}
    if args.baseline_out is not None:
        args.baseline_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2) if args.json else render(rep))
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
