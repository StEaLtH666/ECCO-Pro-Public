#!/usr/bin/env python3
"""Regression suite: tools/check_firmware_equivalence.py (firmware S0 equivalence checker).

No firmware SHAPE is pinned here (owner decision C1, 2026-10-18). Every expectation and every mutation anchor is DERIVED from the
checked-out firmware (git HEAD blobs), and each derived mutant has a deterministic precondition: re-parsing it must show exactly
the intended change and nothing else. So a firmware PR that legitimately adds a global or edits an anchor line does not turn
this suite red, while the comparison itself stays strict: any difference between the two sides still FAILS.

  [1] identity      HEAD (git blobs) vs a directory copy: every L0-L2 row PASS, L3 NOT-RUN (never PASS); the tool's inventory
                    equals counts derived independently from HEAD (a separate YAML reader, not the tool's)
  [2] mutants       derived from HEAD, each NOT EQUIVALENT at the right layer: one-character lambda edit; changed substitution;
                    swapped pair of sensor items; swapped pair of intervals; a hidden Modbus write in an interval; a
                    one-character header edit; a line-ending-only change (not normalised: L0 fails, L1/L2 still match); an
                    ESP32-S3 wrapper edit
  [3] comparator    `!lambda` vs plain text, 1 / "1" / True / 1.0, mapping key order, list order
  [4] safety        AST scan of the tool: imports from an allow-list, no network / socket / os.system / Popen / eval; every
                    subprocess.run is git or an ESPHOME_COMMANDS entry; the ESPHome argv set is version / config /
                    compile --only-generate; secrets.yaml is never read and sandboxes hold placeholders only; outputs inside
                    the repository are refused; the L3 version gate and the cache gate are each exercised with ESPHome
                    STUBBED (so the result does not depend on whether this machine or the CI runner has ESPHome), and
                    generation is proven not to start; the repository's firmware files are unchanged by this suite
  [5] L3 (opt-in)   ECCO_FW_EQUIV_GENERATE=1 and ECCO_FW_EQUIV_CACHE=<dir holding pio_components/> (ESPHome 2026.8.2):
                    identity is EQUIVALENT on L3, and the lambda mutant fails main.cpp identity for both targets. Without
                    the opt-in it prints SKIPPED and is not counted as a pass. It runs real ESPHome, which may use the
                    network (the tool detects logged downloads; it does not block traffic)
  [6] C1 proof      a hypothetical future firmware (one more global, an edited substitution, lambda line, header and
                    wrapper; built by the same derived helpers) is used as the baseline: identity holds, the derived
                    inventory follows it, HEAD vs it is NOT EQUIVALENT, and every derived mutant of it is still caught

Test-only. I/O: reads repo files and git blobs; writes only under temp dirs. No network except the opt-in [5].
"""

from __future__ import annotations

import ast
import contextlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_firmware_equivalence as E  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name)
    if not ok:
        FAILURES.append(name + (f" :: {detail}" if detail else ""))


def failing(rep: E.Report) -> list[E.Row]:
    return [r for r in rep.rows if r.status == "FAIL"]


class PreconditionError(AssertionError):
    """A derived mutant could not be built exactly. The suite FAILS (it never falls back to a weaker mutant)."""


def need(ok: bool, what: str) -> None:
    if not ok:
        raise PreconditionError(what)


# ---------------------------------------------------------------------------
# An independent reader (NOT the tool's loader or inventory) for derived expectations
# ---------------------------------------------------------------------------


class _Plain(yaml.SafeLoader):
    pass


def _plain_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return ("!" + suffix, loader.construct_scalar(node))
    if isinstance(node, yaml.SequenceNode):
        return ("!" + suffix, loader.construct_sequence(node, deep=True))
    return ("!" + suffix, loader.construct_mapping(node, deep=True))


_Plain.add_multi_constructor("!", _plain_tag)


def plain(text: str):
    return yaml.load(text, Loader=_Plain)


def count_bodies(obj) -> int:
    if isinstance(obj, tuple) and len(obj) == 2 and isinstance(obj[0], str) and obj[0].startswith("!"):
        return (1 if obj[0] == "!lambda" and isinstance(obj[1], str) else 0) + count_bodies(obj[1])
    if isinstance(obj, dict):
        return sum((1 if k == "lambda" and isinstance(v, str) else count_bodies(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return sum(count_bodies(v) for v in obj)
    return 0


def derived_shape(text: str) -> dict:
    d = plain(text)
    api = d.get("api") or {}
    return {
        "globals": len(d.get("globals") or []),
        "script": len(d.get("script") or []),
        "intervals": len(d.get("interval") or []),
        "lambdas": count_bodies(d),
        "restored_globals": sum(1 for g in d.get("globals") or [] if g.get("restore_value") in (True, "yes", "true", "on")),
        "api_actions": len(api.get("actions", api.get("services", [])) or []),
    }


# ---------------------------------------------------------------------------
# Mutants derived from HEAD, each with an exactness precondition
# ---------------------------------------------------------------------------


def with_file(base: E.Tree, rel: str, data: bytes, label: str) -> E.Tree:
    files = dict(base.files)
    need(files[rel] != data, f"{label}: no change")
    files[rel] = data
    return E.Tree(f"mutant:{label}", files)


def section_span(lines: list[str], section: str) -> tuple[int, int]:
    starts = [i for i, ln in enumerate(lines) if ln.rstrip("\r") == f"{section}:"]
    need(len(starts) == 1, f"exactly one top-level `{section}:`")
    s = starts[0]
    e = next((i for i in range(s + 1, len(lines)) if re.match(r"^[a-z_]+:", lines[i])), len(lines))
    return s, e


def m_lambda(text: str) -> str:
    """Change the last character of the first lambda line that occurs exactly once in the file."""
    bodies = E._lambdas(E.parse(text), [])
    for b in bodies:
        for ln in (x.strip() for x in b.splitlines()):
            if len(ln) >= 8 and text.count(ln) == 1:
                new_ln = ln[:-1] + ("X" if ln[-1] != "X" else "Y")
                out = text.replace(ln, new_ln, 1)
                after = E._lambdas(E.parse(out), [])
                diff = [i for i, (x, y) in enumerate(zip(bodies, after)) if x != y]
                need(len(after) == len(bodies) and len(diff) == 1, "lambda mutant changes exactly one body")
                i = diff[0]
                need(len(bodies[i]) == len(after[i]) and sum(a != c for a, c in zip(bodies[i], after[i])) == 1,
                     "lambda mutant changes exactly one character")
                return out
    raise PreconditionError("no lambda line occurs exactly once")


def m_substitution(text: str) -> str:
    subs = plain(text).get("substitutions") or {}
    for k, v in subs.items():
        if not isinstance(v, str) or '"' in v or "\\" in v:
            continue
        hits = list(re.finditer(rf"(?m)^  {re.escape(k)}:[^\n]*$", text))
        if len(hits) != 1:
            continue
        h = hits[0]
        out = text[:h.start()] + f'  {k}: "{v}X"' + ("\r" if h.group(0).endswith("\r") else "") + text[h.end():]
        after = plain(out).get("substitutions") or {}
        need(list(after) == list(subs) and after[k] == v + "X" and
             all(after[x] == subs[x] for x in subs if x != k), "substitution mutant changes exactly one value")
        return out
    raise PreconditionError("no plain string substitution with a unique line")


def m_swap(section: str, indent: str = "  "):
    def fn(text: str) -> str:
        lines = text.split("\n")
        s, e = section_span(lines, section)
        heads = [i for i in range(s + 1, e) if lines[i].startswith(indent + "- ")]
        need(len(heads) >= 2, f"`{section}` has at least two items")
        a, b, c = heads[0], heads[1], heads[2] if len(heads) > 2 else e
        out = "\n".join(lines[:a] + lines[b:c] + lines[a:b] + lines[c:])
        before, after = plain(text)[section], plain(out)[section]
        need(before[0] != before[1], f"the first two `{section}` items differ")
        need(after[:2] == [before[1], before[0]] and after[2:] == before[2:], f"`{section}` mutant is exactly the swap")
        return out
    return fn


def m_hidden_write(text: str) -> str:
    d = plain(text)
    mb = d.get("modbus") or {}
    need(isinstance(mb, dict) and isinstance(mb.get("id"), str), "a `modbus:` component with an id")
    lines = text.split("\n")
    s, e = section_span(lines, "interval")
    item = ["  - interval: 3600s", "    then:", "      - modbus_client.write_multiple_registers:",
            f"          modbus_id: {mb['id']}", "          address: 0x01", "          start_address: 0x00F4",
            "          values: [0]"]
    end = e
    while end > s + 1 and lines[end - 1].strip() == "":
        end -= 1
    out = "\n".join(lines[:end] + item + lines[end:])
    need(len(plain(out)["interval"]) == len(d["interval"]) + 1, "hidden-write mutant adds exactly one interval")
    return out


def m_header(base: E.Tree) -> tuple[str, bytes]:
    heads = sorted(r for r in base.files if r.startswith("include/"))
    need(bool(heads), "at least one header")
    rel = heads[0]
    data = base.files[rel]
    nl = data.find(b"\n")
    need(nl > 0, f"{rel} has a first line")
    cut = nl - 1 if data[nl - 1:nl] == b"\r" else nl
    out = data[:cut] + b" " + data[cut:]
    need(len(out) == len(data) + 1, "header mutant inserts exactly one byte")
    return rel, out


def m_line_endings(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n") if b"\r\n" in data else data.replace(b"\n", b"\r\n")


def m_wrapper(text: str) -> str:
    """Change one scalar value of the wrapper's first mapping section that has a uniquely spelled `key: value` line."""
    d = plain(text)
    for sec, body in d.items():
        if not isinstance(body, dict):
            continue
        for k, v in body.items():
            if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.]+", v):
                continue
            hits = list(re.finditer(rf"(?m)^(\s+){re.escape(k)}: {re.escape(v)}(\s*)$", text))
            if len(hits) != 1:
                continue
            h = hits[0]
            out = text[:h.start()] + f"{h.group(1)}{k}: {v}X{h.group(2)}" + text[h.end():]
            after = plain(out)
            need(after[sec][k] == v + "X" and {x: y for x, y in after[sec].items() if x != k} ==
                 {x: y for x, y in body.items() if x != k} and
                 {x: y for x, y in after.items() if x != sec} == {x: y for x, y in d.items() if x != sec},
                 "wrapper mutant changes exactly one value")
            return out
    raise PreconditionError("no uniquely spelled scalar in the wrapper")


def add_global(text: str) -> str:
    """A hypothetical future firmware edit: one more global at the end of `globals:`."""
    lines = text.split("\n")
    s, e = section_span(lines, "globals")
    end = e
    while end > s + 1 and lines[end - 1].strip() == "":
        end -= 1
    item = ["  - id: s0_suite_future_global", "    type: uint8_t", "    restore_value: no", "    initial_value: '0'"]
    out = "\n".join(lines[:end] + item + lines[end:])
    need(len(plain(out)["globals"]) == len(plain(text)["globals"]) + 1, "future-firmware fixture adds exactly one global")
    return out


def grown(base: E.Tree) -> E.Tree:
    """HEAD as a later firmware PR might leave it: a new global, an edited substitution, an edited lambda line, an edited
    header and an edited wrapper. Built with the same derived helpers, so it holds no literal from today's firmware."""
    files = dict(base.files)
    t = add_global(base.text(E.PROD))
    t = m_lambda(m_substitution(t))
    files[E.PROD] = t.encode()
    rel, data = m_header(base)
    files[rel] = data
    files[E.S3] = m_wrapper(base.text(E.S3)).encode()
    return E.Tree("fixture:future-firmware", files)


# ---------------------------------------------------------------------------
# Safety: AST scan of the tool
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS = {"__future__", "argparse", "difflib", "hashlib", "json", "os", "platform", "re", "shutil", "subprocess",
                   "sys", "tempfile", "dataclasses", "pathlib", "yaml", "analyze_write_surface", "_tag_inventory"}
FORBIDDEN_CALLS = {("os", "system"), ("os", "popen"), ("os", "startfile"), ("subprocess", "Popen"),
                   ("subprocess", "call"), ("subprocess", "check_call"), ("subprocess", "check_output"),
                   ("subprocess", "getoutput"), ("subprocess", "getstatusoutput")}


def ast_findings(src: str) -> list[str]:
    tree = ast.parse(src)
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            bad += [f"import {a.name}" for a in n.names if a.name.split(".")[0] not in ALLOWED_IMPORTS]
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                bad.append(f"from {n.module} import")
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in {"eval", "exec", "compile", "__import__"}:
                bad.append(f"call {f.id}()")
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                pair = (f.value.id, f.attr)
                if pair in FORBIDDEN_CALLS or (f.value.id == "os" and f.attr.startswith(("exec", "spawn"))):
                    bad.append(f"call {pair[0]}.{pair[1]}()")
                if pair == ("subprocess", "run"):
                    a0 = n.args[0] if n.args else None
                    git = isinstance(a0, ast.List) and a0.elts and isinstance(a0.elts[0], ast.Constant) and a0.elts[0].value == "git"
                    esp = a0 is not None and any(isinstance(x, ast.Name) and x.id == "ESPHOME_COMMANDS" for x in ast.walk(a0))
                    if not (git or esp):
                        bad.append(f"subprocess.run with argv {ast.unparse(a0) if a0 is not None else None}")
                    if any(k.arg == "shell" for k in n.keywords):
                        bad.append("subprocess.run(shell=...)")
    return bad


def mutant_checks(base: E.Tree, tag: str) -> dict:
    """Every derived mutant of `base` must be NOT EQUIVALENT at the right layer. Returns the mutants by label."""
    P = E.PROD
    cases = [
        ("one-character lambda edit", P, lambda b: m_lambda(b.decode()).encode(),
         {("L0", "bytes"), ("L1", "section items"), ("L1", "C++ text")}),
        ("changed substitution value", P, lambda b: m_substitution(b.decode()).encode(), {("L1", "substitutions")}),
        ("swapped pair of sensor items", P, lambda b: m_swap("sensor")(b.decode()).encode(),
         {("L1", "section items"), ("L1", "entities")}),
        ("swapped pair of intervals", P, lambda b: m_swap("interval")(b.decode()).encode(), {("L1", "intervals")}),
        ("hidden Modbus write in an interval", P, lambda b: m_hidden_write(b.decode()).encode(),
         {("L2", "determinable (after)")}),
        ("line-ending-only change", P, m_line_endings, {("L0", "bytes")}),
        ("ESP32-S3 wrapper edit", E.S3, lambda b: m_wrapper(b.decode()).encode(), {("L1", "section items")}),
    ]
    mutants: dict[str, E.Tree] = {}
    for label, rel, fn, want_rows in cases:
        try:
            m = with_file(base, rel, fn(base.files[rel]), label)
        except PreconditionError as exc:
            check(f"{tag}{label}: derived mutant precondition", False, str(exc))
            continue
        mutants[label] = m
        r = E.run(base, m)
        fails = failing(r)
        got_rows = {(f.layer, f.check) for f in fails}
        missing = [w for w in want_rows if not any(g[0] == w[0] and w[1] in g[1] for g in got_rows)]
        check(f"{tag}{label}: exit 1, failing rows include {sorted(w[1] for w in want_rows)}",
              r.exit_code() == 1 and not missing, f"missing {missing}; got {sorted(got_rows)}")
        if label == "swapped pair of sensor items":
            row = next((f for f in fails if "section items" in f.check), None)
            check(f"{tag}  ... and the detail says ORDER changed and names the section",
                  row is not None and "ORDER changed" in row.detail and "'sensor'" in row.detail, row.detail if row else "")
        if label == "line-ending-only change":
            check(f"{tag}  ... and nothing is normalised: L0 FAILS while L1 / L2 still match", all(f.layer == "L0" for f in fails),
                  str(sorted(got_rows)))
        if label == "hidden Modbus write in an interval":
            row = next((f for f in fails if "determinable (after)" in f.check), None)
            check(f"{tag}  ... and the analyser's own finding is carried through",
                  row is not None and ("interval" in row.detail.lower() or "outside" in row.detail.lower()),
                  row.detail[:300] if row else "")
    try:
        hrel, hdata = m_header(base)
        r = E.run(base, with_file(base, hrel, hdata, "header"))
        check(f"{tag}one-character header edit ({hrel}): exit 1, L0 bytes FAIL",
              r.exit_code() == 1 and any(f.layer == "L0" and "bytes" in f.check for f in failing(r)))
    except PreconditionError as exc:
        check("one-character header edit: derived mutant precondition", False, str(exc))

    return mutants


def main() -> int:
    fw_before = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / "firmware").rglob("*") if p.is_file()}
    head = E.load_tree("HEAD")
    prod_text = head.text(E.PROD)

    print("[1] identity, and the inventory against an independent derivation from HEAD")
    with tempfile.TemporaryDirectory(prefix="ecco_fw_equiv_test_") as td:
        fw = E._materialise(head, Path(td), with_secrets=False)
        as_dir = E.load_tree(str(fw.parent))
    rep = E.run(head, as_dir)
    static = [r for r in rep.rows if r.layer in ("L0", "L1", "L2")]
    check("HEAD (git blobs) vs a directory copy: every L0-L2 row PASS", static and all(r.status == "PASS" for r in static),
          str([(r.check, r.status) for r in static if r.status != "PASS"]))
    l1 = {t: sorted(r.check for r in rep.rows if r.layer == "L1" and r.target == t) for t in E.TARGETS}
    check("L1 runs the same checks for every target", len({tuple(v) for v in l1.values()}) == 1 and all(l1.values()), str(l1))
    check("L2 is labelled classic (the analyser reads the production YAML only)",
          {r.target for r in rep.rows if r.layer == "L2"} == {"classic"})
    l3 = [r for r in rep.rows if r.layer == "L3"]
    check("L3 not requested -> exactly one NOT-RUN row per target, never PASS",
          sorted((r.target, r.status) for r in l3) == sorted((t, "NOT-RUN") for t in E.TARGETS))
    check("exit code 0", rep.exit_code() == 0)
    want = derived_shape(prod_text)
    inv = rep.baseline["inventory"]["classic"]
    got = {"globals": inv["sections"].get("globals"), "script": inv["sections"].get("script"),
           "intervals": inv["intervals"], "lambdas": inv["lambdas"],
           "restored_globals": len(inv["restored_globals"]), "api_actions": len(inv["api_actions"])}
    check("tool inventory == independent derivation from HEAD (globals, scripts, intervals, C++ bodies, restored "
          "globals, API actions)", got == want, f"tool {got} vs derived {want}")
    check("derivation preconditions: every derived count is non-zero", all(v > 0 for v in want.values()), str(want))
    print(f"  info  derived from HEAD: {want}")

    print("[2] mutants derived from HEAD are NOT EQUIVALENT, with the right layer named")
    mutants = mutant_checks(head, "")

    print("[3] comparator")
    check("!lambda text is not plain text", E.digest(E.Lambda("x")) != E.digest("x"))
    check("1, '1', True and 1.0 all differ", len({E.digest(v) for v in (1, "1", True, 1.0)}) == 4)
    check("mapping key order is part of the digest", E.digest({"a": 1, "b": 2}) != E.digest({"b": 2, "a": 1}))
    check("list order is part of the digest", E.digest([1, 2]) != E.digest([2, 1]))

    print("[4] safety")
    src = (ROOT / "tools" / "check_firmware_equivalence.py").read_text(encoding="utf-8")
    bad = ast_findings(src)
    check("AST scan: allow-listed imports only; no eval / exec / os.system / Popen / shell; every subprocess.run is git "
          "or ESPHOME_COMMANDS", not bad, str(bad))
    check("AST scan negative control: an injected socket import, os.system call and Popen call are each flagged",
          len(ast_findings("import socket\nimport os, subprocess\nos.system('x')\nsubprocess.Popen(['x'])\n")) == 3)
    check("ESPHOME_COMMANDS is exactly version / config / compile --only-generate", E.ESPHOME_COMMANDS == {
        "version": ("esphome", "version"), "config": ("esphome", "config"),
        "generate": ("esphome", "compile", "--only-generate")})
    check("no device-facing ESPHome subcommand or option appears in the tool",
          not re.search(r'"(upload|logs|run|clean|dashboard|wizard)"|--device|--upload-port', src))
    with tempfile.TemporaryDirectory(prefix="ecco_fw_equiv_test_") as td:
        fw = E._materialise(head, Path(td), with_secrets=False)
        (fw / "secrets.yaml").write_text("wifi_password: SENTINEL-NEVER-READ\n", encoding="utf-8")
        t = E.load_tree(str(fw.parent))
        check("secrets.yaml in an input tree is never read", "secrets.yaml" not in t.files and
              all(b"SENTINEL-NEVER-READ" not in v for v in t.files.values()))
        with tempfile.TemporaryDirectory(prefix="ecco_fw_equiv_test_sb_") as sb:
            out = E._materialise(t, Path(sb), with_secrets=True)
            check("a sandbox gets the placeholder secrets only",
                  (out / "secrets.yaml").read_text(encoding="ascii") == E.PLACEHOLDER_SECRETS)
    for opt in ("--baseline-out", "--esphome-cache", "--sandbox"):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = E.main(["--before", "HEAD", "--after", "HEAD", opt, str(ROOT / "dist" / "x")])
        check(f"{opt} inside the repository is refused (exit 2)", code == 2)

    # L3 gates with ESPHome STUBBED, so the outcome is the same on a machine with or without ESPHome (C2).
    real_version, real_generate = E.esphome_version, E.generate
    calls: list = []

    def no_generate(*a, **k):
        calls.append(a)
        raise AssertionError("generate() must not be reached")

    try:
        E.generate = no_generate
        E.esphome_version = lambda: E.ESPHOME_VERSION
        with tempfile.TemporaryDirectory(prefix="ecco_fw_equiv_test_cache_") as empty_cache:
            for label, cache in (("no cache", None), ("an empty cache dir (no pio_components/)", Path(empty_cache))):
                r = E.run(head, head, do_generate=True, cache=cache, allow_downloads=False)
                l3 = [x for x in r.rows if x.layer == "L3"]
                check(f"cache gate ({label}, version stubbed to {E.ESPHOME_VERSION}): BLOCKED by the cache rule, exit 3",
                      r.exit_code() == 3 and len(l3) == len(E.TARGETS) and
                      all(x.status == "BLOCKED" and x.detail == E.CACHE_RULE for x in l3) and "generated" not in r.baseline,
                      str([(x.status, x.detail[:80]) for x in l3]))
        for label, ver in (("ESPHome missing", None), ("wrong ESPHome version", "2026.9.0")):
            E.esphome_version = lambda v=ver: v
            r = E.run(head, head, do_generate=True, cache=None, allow_downloads=True)
            l3 = [x for x in r.rows if x.layer == "L3"]
            check(f"version gate ({label}, stubbed): BLOCKED by the version rule, exit 3",
                  r.exit_code() == 3 and l3 and all(x.status == "BLOCKED" and f"ESPHome {E.ESPHOME_VERSION} required" in x.detail
                                                    for x in l3), str([(x.status, x.detail[:80]) for x in l3]))
        check("no gate case reached generation", calls == [])
    finally:
        E.esphome_version, E.generate = real_version, real_generate

    with contextlib.redirect_stderr(io.StringIO()):
        code = E.main(["--before", "no-such-ref-xyz", "--after", "HEAD"])
    check("an unknown input is an input error (exit 2), not a comparison", code == 2)

    print("[5] L3 generated (opt-in)")
    cache = os.environ.get("ECCO_FW_EQUIV_CACHE")
    if os.environ.get("ECCO_FW_EQUIV_GENERATE") == "1" and cache:
        r = E.run(head, head, do_generate=True, cache=Path(cache))
        check("identity: every L3 row PASS, no logged download", r.exit_code() == 0 and
              all(x.status == "PASS" for x in r.rows if x.layer == "L3"),
              str([(x.check, x.status, x.detail[:120]) for x in r.rows if x.status != "PASS"]))
        m = mutants.get("one-character lambda edit")
        if m is None:
            check("lambda mutant available for L3", False)
        else:
            r = E.run(head, m, do_generate=True, cache=Path(cache))
            bad3 = {(x.target, x.check) for x in failing(r) if x.layer == "L3"}
            check("one-character lambda mutant: main.cpp identity FAILS for classic and s3",
                  {("classic", "main.cpp byte-identical"), ("s3", "main.cpp byte-identical")} <= bad3, str(sorted(bad3)))
    else:
        print("  SKIPPED  set ECCO_FW_EQUIV_GENERATE=1 and ECCO_FW_EQUIV_CACHE=<dir> to run (ESPHome 2026.8.2); not a pass")

    print("[6] C1: nothing is tied to today's firmware shape (a hypothetical future firmware as the baseline)")
    try:
        fut = grown(head)
    except PreconditionError as exc:
        check("future-firmware fixture builds", False, str(exc))
    else:
        r = E.run(fut, fut)
        check("[future] identity: every L0-L2 row PASS",
              all(x.status == "PASS" for x in r.rows if x.layer in ("L0", "L1", "L2")),
              str([(x.check, x.status) for x in r.rows if x.layer != "L3" and x.status != "PASS"]))
        fi = r.baseline["inventory"]["classic"]
        fd = derived_shape(fut.text(E.PROD))
        check("[future] tool inventory == independent derivation, and the derivation moved with the firmware "
              f"(globals {want['globals']} -> {fd['globals']})",
              fi["sections"]["globals"] == fd["globals"] == want["globals"] + 1 and fi["lambdas"] == fd["lambdas"],
              f"tool {fi['sections']['globals']}/{fi['lambdas']} vs derived {fd}")
        check("[future] HEAD vs the future firmware is NOT EQUIVALENT (strictness unchanged)", E.run(head, fut).exit_code() == 1)
        mutant_checks(fut, "[future] ")

    fw_after = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / "firmware").rglob("*") if p.is_file()}
    check("the repository's firmware files are unchanged by this suite", fw_before == fw_after)

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("\nAll firmware-equivalence checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
