#!/usr/bin/env python3
"""Regression suite: tools/check_firmware_equivalence.py (firmware S0 equivalence checker).

  [1] identity      the committed firmware compared with itself (git blobs vs a directory copy) is EQUIVALENT on L0-L2,
                    and L3 is reported NOT-RUN (never PASS) when it was not requested
  [2] mutants       each of these edits of the committed firmware is NOT EQUIVALENT, and the failure names the right layer:
                    one-character lambda edit; changed substitution value; swapped pair of sensor items; swapped pair of
                    intervals; a hidden Modbus write in an interval (outside every script); a one-character header edit;
                    a line-ending-only change (not normalised: L0 fails while the parsed inventory still matches); an
                    ESP32-S3 wrapper edit
  [3] comparator    the digest keeps types apart (`!lambda` vs plain text, 1 vs "1" vs True vs 1.0) and mapping key order
  [4] safety        the only ESPHome argv the tool can build is `version`, `config`, `compile --only-generate`; every
                    subprocess call is git or one of those; secrets.yaml is never read and sandboxes get placeholders only;
                    --baseline-out / --esphome-cache / --sandbox inside the repository are refused; --generate without a cache seed or
                    --allow-toolchain-downloads is BLOCKED before ESPHome generates anything; the repository's firmware
                    files are unchanged by this suite
  [5] L3 (opt-in)   with ECCO_FW_EQUIV_GENERATE=1 and ECCO_FW_EQUIV_CACHE=<dir holding pio_components/> (ESPHome 2026.8.2):
                    identity is EQUIVALENT on L3 and the one-character lambda mutant fails main.cpp identity. Without the
                    opt-in this stage prints SKIPPED; it is not counted as a pass

Test-only, no network (L3 opt-in excepted, which uses the seeded cache and fails on any download). I/O: reads repo
files and git blobs; writes only under temp dirs.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

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


def mutate(base: E.Tree, rel: str, fn, label: str) -> E.Tree:
    files = dict(base.files)
    old = files[rel]
    new = fn(old)
    assert new != old, f"mutant {label} did not change {rel}"
    files[rel] = new
    return E.Tree(f"mutant:{label}", files)


def replace_once(old: bytes, new: bytes):
    def fn(b: bytes) -> bytes:
        assert b.count(old) >= 1, old
        return b.replace(old, new, 1)
    return fn


def swap_items(section: str, indent: str = "  "):
    """Swap the first two list items of a top-level section, text-level (comments travel with the item below them)."""
    def fn(b: bytes) -> bytes:
        text = b.decode("utf-8")
        lines = text.split("\n")
        start = next(i for i, ln in enumerate(lines) if ln.rstrip("\r") == f"{section}:")
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"^[a-z_]+:", lines[i])), len(lines))
        heads = [i for i in range(start + 1, end) if lines[i].startswith(indent + "- ")]
        a, b2, c = heads[0], heads[1], heads[2] if len(heads) > 2 else end
        first, second = lines[a:b2], lines[b2:c]
        return "\n".join(lines[:a] + second + first + lines[c:]).encode("utf-8")
    return fn


HIDDEN_WRITE = (
    "  - interval: 3600s\n"
    "    then:\n"
    "      - modbus_client.write_multiple_registers:\n"
    "          modbus_id: inverter_modbus\n"
    "          address: 0x01\n"
    "          start_address: 0x00F4\n"
    "          values: [0]\n"
)


def main() -> int:
    fw_before = {p.name: p.read_bytes() for p in (ROOT / "firmware").rglob("*") if p.is_file()}
    head = E.load_tree("HEAD")

    print("[1] identity")
    with tempfile.TemporaryDirectory(prefix="ecco_fw_equiv_test_") as td:
        fw = E._materialise(head, Path(td), with_secrets=False)
        as_dir = E.load_tree(str(fw.parent))
    rep = E.run(head, as_dir)
    check("HEAD (git blobs) vs a directory copy: no FAIL", not failing(rep), str([r.check for r in failing(rep)]))
    check("L3 not requested -> NOT-RUN rows, never PASS",
          [r.status for r in rep.rows if r.layer == "L3"] == ["NOT-RUN", "NOT-RUN"])
    check("exit code 0 and 28 PASS rows (L0 2, L1 2x11, L2 4)", rep.exit_code() == 0 and
          sum(r.status == "PASS" for r in rep.rows) == 28, str(len(rep.rows)))
    inv = rep.baseline["inventory"]["classic"]
    check("baseline inventory matches the committed firmware shape (665 globals, 39 scripts, 14 intervals, 1248 lambdas, "
          "7 restored globals, 3 API actions)",
          inv["sections"]["globals"] == 665 and inv["sections"]["script"] == 39 and inv["intervals"] == 14 and
          inv["lambdas"] == 1248 and len(inv["restored_globals"]) == 7 and len(inv["api_actions"]) == 3, str(inv)[:300])

    print("[2] mutants are NOT EQUIVALENT, with the right layer named")
    P = E.PROD
    cases = [
        ("one-character lambda edit", P,
         replace_once(b"id(ntp_synced_sensor).publish_state(false);", b"id(ntp_synced_sensor).publish_state(falsE);"),
         {("L0", "bytes"), ("L1", "section items"), ("L1", "lambda text")}),
        ("changed substitution value", P,
         replace_once(b'ecco_dump_runaway_dc_allowance_pct: "12"', b'ecco_dump_runaway_dc_allowance_pct: "13"'),
         {("L1", "substitutions")}),
        ("swapped pair of sensor items", P, swap_items("sensor"),
         {("L1", "section items"), ("L1", "entities")}),
        ("swapped pair of intervals", P, swap_items("interval"),
         {("L1", "intervals")}),
        ("hidden Modbus write in an interval", P, lambda b: b.rstrip(b"\r\n") + b"\n" + HIDDEN_WRITE.encode(),
         {("L2", "determinable (after)")}),
        ("one-character header edit", "include/ecco_rtc_policy.h", replace_once(b"#pragma once", b"#pragma  once"),
         {("L0", "bytes")}),
        ("line-ending-only change (CRLF)", P, lambda b: b.replace(b"\n", b"\r\n"),
         {("L0", "bytes")}),
        ("ESP32-S3 wrapper edit", E.S3, replace_once(b"flash_size: 16MB", b"flash_size: 8MB"),
         {("L1", "section items")}),
    ]
    for label, rel, fn, want in cases:
        m = mutate(head, rel, fn, label)
        r = E.run(head, m)
        fails = failing(r)
        got = {(f.layer, f.check) for f in fails}
        missing = [w for w in want if not any(f[0] == w[0] and w[1] in f[1] for f in got)]
        check(f"{label}: exit 1, failing rows include {sorted(w[1] for w in want)}",
              r.exit_code() == 1 and not missing, f"missing {missing}; got {sorted(got)}")
        if label == "swapped pair of sensor items":
            row = next(f for f in fails if "section items" in f.check)
            check("  ... and the detail says ORDER changed and names the section", "ORDER changed" in row.detail and
                  "'sensor'" in row.detail, row.detail)
        if label == "line-ending-only change (CRLF)":
            check("  ... and nothing is normalised: L0 FAILS while L1 / L2 still match", all(f.layer == "L0" for f in fails),
                  str(sorted(got)))
        if label == "hidden Modbus write in an interval":
            row = next(f for f in fails if "determinable (after)" in f.check)
            check("  ... and the analyser's own finding is carried through", "interval" in row.detail.lower() or
                  "outside" in row.detail.lower(), row.detail[:300])

    print("[3] comparator")
    check("!lambda text is not plain text", E.digest(E.Lambda("x")) != E.digest("x"))
    check("1, '1', True and 1.0 all differ", len({E.digest(v) for v in (1, "1", True, 1.0)}) == 4)
    check("mapping key order is part of the digest", E.digest({"a": 1, "b": 2}) != E.digest({"b": 2, "a": 1}))
    check("list order is part of the digest", E.digest([1, 2]) != E.digest([2, 1]))

    print("[4] safety")
    check("ESPHOME_COMMANDS is exactly version / config / compile --only-generate", E.ESPHOME_COMMANDS == {
        "version": ("esphome", "version"), "config": ("esphome", "config"),
        "generate": ("esphome", "compile", "--only-generate")})
    src = (ROOT / "tools" / "check_firmware_equivalence.py").read_text(encoding="utf-8")
    calls = re.findall(r"subprocess\.run\(\s*([^,]+)", src)
    ok_calls = [c for c in calls if c.startswith('["git"') or "ESPHOME_COMMANDS[" in c]
    check("every subprocess call is git or an ESPHOME_COMMANDS entry", calls and len(ok_calls) == len(calls), str(calls))
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
    r = E.run(head, head, do_generate=True, cache=None, allow_downloads=False)
    l3 = [x for x in r.rows if x.layer == "L3"]
    check("--generate without a cache seed or --allow-toolchain-downloads is BLOCKED (exit 3), nothing generated",
          r.exit_code() == 3 and l3 and all(x.status == "BLOCKED" for x in l3) and "generated" not in r.baseline,
          str([(x.status, x.detail[:80]) for x in l3]))
    with contextlib.redirect_stderr(io.StringIO()):
        code = E.main(["--before", "no-such-ref-xyz", "--after", "HEAD"])
    check("an unknown input is an input error (exit 2), not a comparison", code == 2)

    print("[5] L3 generated (opt-in)")
    cache = os.environ.get("ECCO_FW_EQUIV_CACHE")
    if os.environ.get("ECCO_FW_EQUIV_GENERATE") == "1" and cache:
        r = E.run(head, head, do_generate=True, cache=Path(cache))
        check("identity: every L3 row PASS, no download", r.exit_code() == 0 and
              all(x.status == "PASS" for x in r.rows if x.layer == "L3"),
              str([(x.check, x.status, x.detail[:120]) for x in r.rows if x.status != "PASS"]))
        m = mutate(head, E.PROD, cases[0][2], "lambda-l3")
        r = E.run(head, m, do_generate=True, cache=Path(cache))
        bad = {(x.target, x.check) for x in failing(r) if x.layer == "L3"}
        check("one-character lambda mutant: main.cpp identity FAILS for classic and s3",
              {("classic", "main.cpp byte-identical"), ("s3", "main.cpp byte-identical")} <= bad, str(sorted(bad)))
    else:
        print("  SKIPPED  set ECCO_FW_EQUIV_GENERATE=1 and ECCO_FW_EQUIV_CACHE=<dir> to run (ESPHome 2026.8.2); not a pass")

    fw_after = {p.name: p.read_bytes() for p in (ROOT / "firmware").rglob("*") if p.is_file()}
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
