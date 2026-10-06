#!/usr/bin/env python3
"""tools/analyze_write_surface.py must fail closed, never under-report.

2026-09-28 safety-gap audit findings this file pins:

  * EXTENT. `values: !lambda '...'` (the inline single-quoted form Dump to
    Grid uses for its two register 244 writes) was not recognised, so the
    write's element count came back None and was silently defaulted to ONE
    register. Harmless today (both are single-element), but a future
        start_address: 244
        values: !lambda 'return std::vector<uint16_t>{a, b};'
    would also write register 245 and the write surface would still say
    {244}. Now a count is only taken when it is certain; otherwise the
    write is UNKNOWN EXTENT and every consumer fails.
  * COVERAGE. The write surface is built from `script:` entries only. A
    Modbus writer added to a button, interval, api action, on_boot hook,
    entity trigger, raw C++ lambda, included header, `modbus_controller`
    entity, ... would have been invisible. The analyzer now walks the whole
    parsed YAML tree and reports every such bus access for review.

No I/O beyond temporary fixture files, no hardware, no ESPHome toolchain.
Each fixture is a small synthetic firmware; the last group runs against
the real production firmware and proves its write surface is unchanged.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "analyze_write_surface.py"
sys.path.insert(0, str(ROOT / "tools"))

from analyze_write_surface import (  # noqa: E402
    DEFAULT_FIRMWARE,
    WriteExtentUnknown,
    analyze,
    write_surface,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


TMP = Path(tempfile.mkdtemp(prefix="ecco_write_surface_fixture_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

HEADER = """\
esphome:
  name: fixture
{esphome_extra}
uart:
  id: inverter_uart
  tx_pin: GPIO17
  rx_pin: GPIO16
  baud_rate: 9600

modbus:
  id: inverter_modbus
  uart_id: inverter_uart
  role: client

globals:
  - id: manual_write_in_progress
    type: bool
    initial_value: 'false'
"""


def write_action(start: str, values: str, indent: int) -> str:
    """A modbus_client.write_multiple_registers list item at `indent`."""
    body = f"""\
- modbus_client.write_multiple_registers:
    modbus_id: inverter_modbus
    address: 0x01
    start_address: {start}
{textwrap.indent(values, "    ") if values else ""}
    on_response:
      then:
        - lambda: 'ESP_LOGI("fixture", "write, acknowledged");'
    on_error:
      then:
        - lambda: 'id(manual_write_in_progress) = false;'
"""
    return textwrap.indent(body, " " * indent)


def script(name: str, action: str, *, head: str = "  - id: {name}\n    mode: single\n") -> str:
    return (
        head.format(name=name)
        + "    then:\n"
        + "      - lambda: 'id(manual_write_in_progress) = true;'\n"
        + action
        + "      - lambda: 'id(manual_write_in_progress) = false;'\n"
    )


def firmware(scripts: str, extra: str = "", esphome_extra: str = "") -> str:
    return HEADER.format(esphome_extra=esphome_extra) + "\nscript:\n" + scripts + "\n" + extra


_fixture_n = 0


def fixture(text: str, files: dict[str, str] | None = None) -> Path:
    global _fixture_n
    _fixture_n += 1
    d = TMP / f"fw{_fixture_n}"
    d.mkdir()
    for name, content in (files or {}).items():
        (d / name).write_text(content, encoding="utf-8")
    p = d / "firmware.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def cli(path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), "--firmware", str(path), *extra],
        capture_output=True, text=True, cwd=ROOT,
    )


def single_write_fixture(values: str, start: str = "244") -> Path:
    return fixture(firmware(script("fixture_writer", write_action(start, values, 6))))


def surface_or_error(result: dict):
    try:
        return write_surface(result["paths"])
    except WriteExtentUnknown as exc:
        return exc


# ---------------------------------------------------------------------------
print("[1] Certain extents: single / multi-element lambdas and static lists")
# ---------------------------------------------------------------------------
CERTAIN = {
    "inline lambda, one element at 244": (
        "values: !lambda 'return std::vector<uint16_t>{id(reg244_expected_value)};'", "244", {244}),
    "inline lambda, TWO elements at 244 (would also write 245)": (
        "values: !lambda 'return std::vector<uint16_t>{(uint16_t) 1, (uint16_t) 0};'", "244", {244, 245}),
    "block lambda, one element at 244": (
        "values: !lambda |-\n  return std::vector<uint16_t>{id(reg244_snapshot_value)};", "244", {244}),
    "block lambda, TWO elements at 244, with comments containing commas and a trailing comma": (
        "values: !lambda |-\n"
        "  uint16_t a = id(x);  // not, an, element\n"
        "  ESP_LOGI(\"fixture\", \"return std::vector<uint16_t>{1, 2, 3};\");\n"
        "  return std::vector<uint16_t>{\n"
        "    a,  // register 244\n"
        "    (uint16_t) (a | 0x0001),  /* register 245, (grouped, commas) */\n"
        "  };",
        "244", {244, 245}),
    "block lambda, two conditional returns of the SAME length": (
        "values: !lambda |-\n"
        "  if (id(x)) return std::vector<uint16_t>{1};\n"
        "  return std::vector<uint16_t>{0};",
        "244", {244}),
    "static flow list, two values at 244": ("values: [1, 0]", "244", {244, 245}),
    "static block list, three values at 244": ("values:\n  - 1\n  - 0\n  - 7", "244", {244, 245, 246}),
    "static flow list, one value at 244": ("values: [0]", "244", {244}),
    "hex start_address 0x00F4 with two elements": (
        "values: !lambda 'return std::vector<uint16_t>{1, 2};'", "0x00F4", {244, 245}),
}
for label, (values, start, expected) in CERTAIN.items():
    result = analyze(single_write_fixture(values, start))
    writes = [op for p in result["paths"] for op in p.writes]
    got = surface_or_error(result)
    check(f"{label}: exactly one write, extent known", len(writes) == 1 and writes[0].extent_known,
          f"{[(w.start_address, w.count, w.extent_unknown_reason) for w in writes]}")
    check(f"{label}: write surface is {sorted(expected)}",
          isinstance(got, dict) and set(got) == expected, f"got {got!r}")
    check(f"{label}: no unknown-extent writes and no bus-access findings",
          not result["unknown_extent_writes"] and not result["bus_access_findings"],
          f"{result['unknown_extent_writes']} {result['bus_access_findings']}")

two = analyze(single_write_fixture("values: !lambda 'return std::vector<uint16_t>{(uint16_t) 1, (uint16_t) 0};'"))
check("regression: a two-element inline lambda at 244 is NOT reported as {244} alone (the pre-fix silent default)",
      set(write_surface(two["paths"])) != {244})
ok = cli(single_write_fixture("values: !lambda 'return std::vector<uint16_t>{1, 0};'"))
check("CLI on a certain two-element fixture exits 0 and lists register 245", ok.returncode == 0 and "  245  " in ok.stdout,
      f"rc={ok.returncode}")

# ---------------------------------------------------------------------------
print("")
print("[2] Uncertain extents are UNKNOWN - never assumed to be one register")
# ---------------------------------------------------------------------------
UNCERTAIN = {
    "vector built with push_back": (
        "values: !lambda |-\n  std::vector<uint16_t> v;\n  v.push_back(1);\n  v.push_back(2);\n  return v;", "244"),
    "values returned from a helper call": ("values: !lambda 'return build_values();'", "244"),
    "conditional returns of DIFFERENT lengths": (
        "values: !lambda |-\n  if (id(x)) return std::vector<uint16_t>{1};\n  return std::vector<uint16_t>{1, 2};", "244"),
    "( )-constructor with a count": ("values: !lambda 'return std::vector<uint16_t>(2, id(x));'", "244"),
    "iterator-range initialiser": ("values: !lambda 'return std::vector<uint16_t>{src.begin(), src.end()};'", "244"),
    "nested lambda with its own return": (
        "values: !lambda |-\n  auto f = [&]() { return 5; };\n  return std::vector<uint16_t>{(uint16_t) f()};", "244"),
    "return with trailing expression after the initialiser": (
        "values: !lambda 'return std::vector<uint16_t>{1, 2} , other;'", "244"),
    "empty vector": ("values: !lambda 'return std::vector<uint16_t>{};'", "244"),
    "empty static list": ("values: []", "244"),
    "scalar values:": ("values: 5", "244"),
    "no values: key": ("", "244"),
    "lambda start_address": ("values: [1]", "!lambda 'return 244;'"),
}
for label, (values, start) in UNCERTAIN.items():
    path = single_write_fixture(values, start)
    result = analyze(path)
    writes = [op for p in result["paths"] for op in p.writes]
    check(f"{label}: the write is still found (not skipped)", len(writes) == 1, f"{len(writes)} writes")
    if len(writes) != 1:
        continue
    op = writes[0]
    check(f"{label}: extent is UNKNOWN with a reason", not op.extent_known and bool(op.extent_unknown_reason),
          f"count={op.count} start={op.start_address}")
    try:
        op.addresses
        raised = False
    except WriteExtentUnknown:
        raised = True
    check(f"{label}: op.addresses raises WriteExtentUnknown instead of returning [start]", raised)
    check(f"{label}: write_surface() raises rather than under-counting",
          isinstance(surface_or_error(result), WriteExtentUnknown))
    check(f"{label}: listed in unknown_extent_writes", len(result["unknown_extent_writes"]) == 1)
    run = cli(path)
    check(f"{label}: CLI exits non-zero and prints no write-surface table",
          run.returncode != 0 and "UNKNOWN register extent" in run.stdout and "Full write surface" not in run.stdout,
          f"rc={run.returncode}")
json_run = cli(single_write_fixture("values: !lambda 'return build_values();'"), "--json")
check("CLI --json also fails closed (non-zero, error + unknown_extent_writes, no write_surface key)",
      json_run.returncode != 0 and '"unknown_extent_writes"' in json_run.stdout and '"write_surface"' not in json_run.stdout)

# ---------------------------------------------------------------------------
print("")
print("[3] Bus writers OUTSIDE script: entries (and other unmodelled bus access) are flagged")
# ---------------------------------------------------------------------------
CLEAN_SCRIPT = script("fixture_writer", write_action("256", "values: [1]", 6))
OUTSIDE = {
    "button on_press": (
        "button:\n  - platform: template\n    id: fixture_button\n    name: Fixture\n    on_press:\n"
        + write_action("245", "values: [1]", 6), ""),
    "interval": ("interval:\n  - interval: 10s\n    then:\n" + write_action("245", "values: [1]", 6), ""),
    "api action": (
        "api:\n  actions:\n    - action: fixture\n      then:\n" + write_action("245", "values: [1]", 8), ""),
    "esphome on_boot": (
        "", "  on_boot:\n    priority: -100\n    then:\n" + write_action("245", "values: [1]", 6)),
    "sensor on_value": (
        "sensor:\n  - platform: template\n    id: fixture_sensor\n    on_value:\n      then:\n"
        + write_action("245", "values: [1]", 8), ""),
    "time on_time": (
        "time:\n  - platform: sntp\n    id: t\n    on_time:\n      - seconds: 0\n        then:\n"
        + write_action("245", "values: [1]", 10), ""),
}
for label, (extra, esphome_extra) in OUTSIDE.items():
    path = fixture(firmware(CLEAN_SCRIPT, extra, esphome_extra))
    result = analyze(path)
    findings = result["bus_access_findings"]
    check(f"{label}: the out-of-script write is flagged", any("outside any `script:`" in f["reason"] for f in findings),
          f"{findings}")
    check(f"{label}: the script write surface alone would have missed it (245 absent)",
          245 not in write_surface(result["paths"]))
    run = cli(path)
    check(f"{label}: CLI exits non-zero", run.returncode != 0 and "Unclassified inverter-bus access" in run.stdout,
          f"rc={run.returncode}")

UNMODELLED_IN_SCRIPT = {
    "unmodelled modbus_client action": (
        "      - modbus_client.write_single_register:\n          modbus_id: inverter_modbus\n"
        "          address: 0x01\n          register_address: 245\n          value: 1\n",
        "unmodelled Modbus action"),
    "raw C++ call on the Modbus bus": (
        "      - lambda: |-\n          uint8_t data[4] = {0, 1, 0, 2};\n"
        "          id(inverter_modbus)->send(0x01, 0x10, 244, 2, 4, data);\n",
        "raw C++ call id(inverter_modbus)->send"),
    "raw C++ write on the Modbus UART": (
        "      - lambda: |-\n          uint8_t frame[8] = {0};\n          id(inverter_uart)->write_array(frame, 8);\n",
        "raw C++ call id(inverter_uart)->write_array"),
    "C++ modbus_controller command API": (
        "      - lambda: |-\n          auto cmd = modbus_controller::ModbusCommandItem::create_write_multiple_command"
        "(nullptr, 245, 1, {});\n",
        "C++ Modbus command API"),
}
for label, (action, reason) in UNMODELLED_IN_SCRIPT.items():
    path = fixture(firmware(script("fixture_writer", action)))
    findings = analyze(path)["bus_access_findings"]
    check(f"{label}: flagged", any(reason in f["reason"] for f in findings), f"{findings}")
    check(f"{label}: CLI exits non-zero", cli(path).returncode != 0)

OTHER = {
    "modbus_controller entity": (
        firmware(CLEAN_SCRIPT, "number:\n  - platform: modbus_controller\n    address: 245\n    value_type: U_WORD\n"),
        None, "`modbus_controller` entity"),
    "raw uart.write action": (
        firmware(CLEAN_SCRIPT, "interval:\n  - interval: 10s\n    then:\n      - uart.write:\n"
                                "          id: inverter_uart\n          data: [0x01, 0x10]\n"),
        None, "raw `uart.write` action"),
    "packages: (unscanned YAML)": (firmware(CLEAN_SCRIPT, "packages:\n  extra: {}\n"), None, "top-level `packages:`"),
    "!include (unscanned YAML)": (firmware(CLEAN_SCRIPT, "sensor: !include extra.yaml\n"), None, "`!include`"),
    "external_components": (
        firmware(CLEAN_SCRIPT, "external_components:\n  - source: github://example/x\n"), None,
        "top-level `external_components:`"),
    "included C++ header touching the bus": (
        firmware(CLEAN_SCRIPT, esphome_extra="  includes:\n    - raw.h\n"),
        {"raw.h": "#pragma once\n// comment mentioning inverter_modbus is ignored\n"
                  "inline void f() { id(inverter_modbus)->send(1, 16, 245, 1, 2, nullptr); }\n"},
        "raw C++ call id(inverter_modbus)->send"),
    "included C++ header that is missing": (
        firmware(CLEAN_SCRIPT, esphome_extra="  includes:\n    - missing.h\n"), None, "included file not found"),
    "script entry whose id: is not its first key (text splitter mis-attributes its write)": (
        firmware(CLEAN_SCRIPT + script("sneaky_writer", write_action("245", "values: [1]", 6),
                                       head="  - mode: single\n    id: {name}\n")),
        None, "text extractor and YAML tree disagree"),
}
for label, (text, files, reason) in OTHER.items():
    path = fixture(text, files)
    findings = analyze(path)["bus_access_findings"]
    check(f"{label}: flagged", any(reason in f["reason"] for f in findings), f"{findings}")
    check(f"{label}: CLI exits non-zero", cli(path).returncode != 0)

# Not over-flagging: comments and the gates' read-only bus queries are fine.
benign = fixture(firmware(
    CLEAN_SCRIPT
    + "  - id: fixture_gate\n    then:\n      - lambda: |-\n"
      "          // id(inverter_modbus)->send(1, 16, 245, 1, 2, nullptr);\n"
      "          ESP_LOGI(\"fixture\", \"id(inverter_uart)->write_array\");\n"
      "          if (!id(inverter_modbus)->tx_buffer_empty() || id(inverter_modbus)->tx_blocked()) return;\n"
      "      # - modbus_client.write_multiple_registers:\n",
    "button:\n  - platform: template\n    id: read_only_button\n    on_press:\n"
    "      - modbus_client.read_holding_registers:\n          modbus_id: inverter_modbus\n"
    "          address: 0x01\n          start_address: 245\n          count: 1\n",
))
benign_result = analyze(benign)
check("comments, log strings, tx_buffer_empty()/tx_blocked() and an out-of-script READ are not flagged",
      benign_result["bus_access_findings"] == [], f"{benign_result['bus_access_findings']}")
check("...and the CLI exits 0 on that fixture", cli(benign).returncode == 0)

# ---------------------------------------------------------------------------
print("")
print("[4] Production firmware: every write certain, no unclassified bus access, surface unchanged")
# ---------------------------------------------------------------------------
prod = analyze(DEFAULT_FIRMWARE)
prod_writes = [(p.name, op) for p in prod["paths"] for op in p.writes]
# 51 on main @ 15ee7d2; SG-02 (fix/sg02-dump-lockout-containment) added
# exactly one: dump_lockout_containment's literal 244 = 2 (register 244 was
# already in Dump's write surface - the register set is unchanged).
check("production firmware has 52 modelled writes (51 + the SG-02 containment write)", len(prod_writes) == 52,
      f"{len(prod_writes)}")
check("production firmware: zero unknown-extent writes", prod["unknown_extent_writes"] == [],
      f"{prod['unknown_extent_writes']}")
check("production firmware: zero unclassified bus-access findings", prod["bus_access_findings"] == [],
      f"{prod['bus_access_findings']}")
dump_244 = [(n, op) for n, op in prod_writes
            if op.start_address == 244 and n in ("start_dump_to_grid_override", "restore_dump_to_grid_snapshot")]
check("the two Dump to Grid inline-lambda 244 writes are now parsed (value_expr present, count certain = 1)",
      len(dump_244) == 2 and all(op.value_expr and op.count == 1 for _, op in dump_244),
      f"{[(n, op.count, op.value_expr) for n, op in dump_244]}")
check("every production write to register 244 is a single-element write (245 is not written)",
      all(op.count == 1 for _, op in prod_writes if op.start_address == 244))
containment_writes = [op for n, op in prod_writes if n == "dump_lockout_containment"]
check("SG-02: the containment's only write is 244 with the LITERAL value 2 (never snapshot/default-derived)",
      len(containment_writes) == 1 and containment_writes[0].start_address == 244
      and containment_writes[0].count == 1
      and (containment_writes[0].value_expr or "").replace(" ", "") == "returnstd::vector<uint16_t>{2};",
      f"{[(op.start_address, op.count, op.value_expr) for op in containment_writes]}")

EXPECTED_PER_SCRIPT = {
    "write_inverter_rtc": {22, 23, 24},
    "start_free_power_override": {230, 232} | set(range(256, 262)) | set(range(268, 280)),
    "restore_free_power_snapshot_dispatch": {230, 232} | set(range(256, 262)) | set(range(268, 280)),
    "free_power_recovery_force_restore_dispatch": {230, 232} | set(range(256, 262)) | set(range(268, 280)),
    **{f"apply_manual_slot{n}": {232, 255 + n, 267 + n, 273 + n} | ({249 + n, 250 + n} if n < 6 else {255, 250})
       for n in range(1, 7)},
    "apply_reg244_settings": {244},
    "restore_reg244_snapshot": {244},
    "start_dump_to_grid_override": {244} | set(range(256, 262)),
    "restore_dump_to_grid_snapshot": {244} | set(range(256, 262)),
    "dump_controller_tick": set(range(256, 262)),
    # SG-02 corrupt-lockout export containment: 244 only (never 256-261).
    "dump_lockout_containment": {244},
}
actual_per_script = {p.name: p.written_addresses for p in prod["paths"] if p.kind == "script" and p.writes}
check("production per-script write surface is exactly the pinned pre-change surface",
      actual_per_script == EXPECTED_PER_SCRIPT,
      f"diff={ {k: (sorted(actual_per_script.get(k, ())), sorted(EXPECTED_PER_SCRIPT.get(k, ()))) for k in set(actual_per_script) | set(EXPECTED_PER_SCRIPT) if actual_per_script.get(k) != EXPECTED_PER_SCRIPT.get(k)} }")
prod_run = cli(DEFAULT_FIRMWARE)
check("CLI on production firmware exits 0 with the normal report",
      prod_run.returncode == 0 and "=== Full write surface (register -> writers) ===" in prod_run.stdout
      and "FAILED" not in prod_run.stdout, f"rc={prod_run.returncode}")

# ---------------------------------------------------------------------------
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All write-surface analyzer fail-closed checks passed.")
