"""Offline suite for the reserve control package (home-assistant/packages/ecco_reserve_control.yaml): ONE guarded script that sets the owner's battery reserve.

The script validates a request (a whole percent from 0 to 80 and inside the helper's own range), asks for a confirmation when the value is below the reserve the plan uses now OR below
the owner's own (a real lowering, or a raise that stays below the plan reserve while a Prepare for power cut reserve runs: the text says which), writes ONLY
input_number.ecco_minimum_reserve_soc (after a stamped WRITING text, so that an aborted run never leaves an old OK standing), reads it back and leaves a result text for a card. It never writes an inverter, dongle, TOU, number, switch or
button entity. Nothing was installed and nothing was written live. This suite runs the REAL package on the repository's own models (the FPS1 interpreter and the zone-aware plan
layer with Home Assistant's helper range checks), with the REAL owner reserve helper definition and the REAL plan helper package, so the effective reserve is produced by its real template.

  [0] static      the file defines one script and one helper, the write vocabulary is exactly input_number.set_value on one entity, input_text.set_value on one entity and the
                  notification calls; it reads only the reserve helper and the plan's effective reserve; no dongle slug, no forecast, no Intelligence entity; ASCII, LF, no site
                  value; the header states the rules; the manifest stanza, the README section and the CHANGELOG bullet
  [1] table       raise, lower, same value, with and without confirm, at the limits, during a Prepare for power cut reserve
  [2] values      every kind of junk in the value field, one at a time; the confirm field in every spelling
  [3] unreadable  the helper and the effective reserve missing, unavailable, unknown or junk, one at a time
  [4] failure     a write that does not stick, one that lands on another number, one that raises: FAILED, one write, no retry, a notification, dismissed by the next success;
                  F8: a write that raises a VALIDATION error (vol.Invalid) ends the run, and the text then reads WRITING, never an old OK; a narrowed helper range is refused before the write
  [4b] nochange   F9: the same value in every spelling (5.0, " 5 ", +5, 5e0) is NO CHANGE and writes nothing, with and without a power cut reserve
  [4c] lowering   F9: lowering from 1, 2, 3 or 80 with an unreadable plan reserve is refused (never a guess), whatever confirm says
  [5] vocabulary  over a whole session the only service calls are the four allowed ones, on the allowed entities, and no state outside the helper and the result text changes
  [6] mutation    in-memory mutants of the package, each caught
  [7] callers     the caller pin: nothing under home-assistant/ or frontend/*/src calls the script (an EMPTY allow-list, no literal confirm true), with negative and positive controls and mutants of the pin itself

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _ha_script_sim as S  # noqa: E402
import _reserve_control_sim as M  # noqa: E402
import ecco_site_render as render  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_reserve_control.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
PKG_RAW = (ROOT / PKG_REL).read_bytes()
PKGS = ROOT / "home-assistant" / "packages"
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
FAILURES: list[str] = []
MISSING = S._MISSING


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _v in node.value]
    dup = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dup:
        raise ValueError(f"duplicate mapping key(s) {dup}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)

HELPER, PLAN, RESULT, NOTE = M.HELPER, M.PLAN, M.RESULT, M.NOTE


def slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")

ALLOWED_ACTIONS = {"input_number.set_value", "input_text.set_value", "persistent_notification.create", "persistent_notification.dismiss"}
ID_RE = re.compile(r"(?<![A-Za-z0-9_.])((?:binary_)?sensor|input_[a-z]+|switch|button|number|select|script|automation|climate|light|lock|cover|fan|esphome|modbus|mqtt|rest_command|"
                   r"shell_command|scene|group|timer|counter)\.([a-z0-9_]+)")
FORBIDDEN_DOMAINS = ("number", "select", "switch", "button", "climate", "light", "lock", "cover", "fan", "esphome", "modbus", "mqtt", "rest_command", "shell_command", "scene",
                     "group", "timer", "counter", "binary_sensor", "input_boolean", "input_select", "input_datetime")
INTEL = "ecco_" "intel"
SOLCAST = "solc" "ast"
HEADER_MUST = ("WHAT IT WRITES, AND WHAT IT NEVER WRITES", "THE RULES", "HARD RULES", "LIMITS", "RECORDER FOOTPRINT (ESTIMATE", "INSTALL.", "never lowers on an unreadable reserve",
               "KNOWN CONFLICT", "second writer", "exactly one writer", "does NOT lower the effective reserve", "CONFIRM_NEEDED", "NOT_A_NUMBER", "OUT_OF_RANGE", "NOT_WHOLE", "HELPER_UNREADABLE", "RESERVE_UNREADABLE", "WRITE_NOT_CONFIRMED",
               "NO CHANGE", "the inverter's own floor registers are NOT changed", "never while the script runs", "THE WRITE.", "WRITING", "vol.Invalid", "OWNER DECISION", "ONE LAST SEPARATE COMMIT",
               "compared as a NUMBER", "your reserve 5 -> 20", "a raise to or above the effective reserve never asks")


def code_lines(text: str) -> str:
    return "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))


def collect(node, key: str, acc: list) -> list:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                acc.append(v)
            collect(v, key, acc)
    elif isinstance(node, list):
        for v in node:
            collect(v, key, acc)
    return acc


def privacy_problems(text: str) -> list:
    bad = []
    if re.search(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])", text):
        bad.append("an IPv4 address")
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", text):
        bad.append("an e-mail address")
    if re.search(r"https?://|www\.", text):
        bad.append("a link")
    if re.search(r"api[_ -]?key|password|secret|token", text, re.I):
        bad.append("a key or secret word")
    if re.search(r"[A-Za-z]:\\|/Users/|/home/", text):
        bad.append("a path")
    if any(ord(c) > 126 or (ord(c) < 32 and c != "\n") for c in text):
        bad.append("a non-ASCII or control character")
    if re.search(r"[ \t]+$", text, re.M):
        bad.append("trailing space")
    return bad


def static_problems(text: str) -> list:
    bad = []
    try:
        doc = yaml.load(text, Loader=UniqueKeyLoader) or {}
    except Exception as exc:  # noqa: BLE001
        return [f"YAML does not parse: {str(exc)[:100]}"]
    if set(doc) != {"input_text", "script"}:
        return [f"top-level keys are {sorted(doc)}"]
    it = doc["input_text"]
    if set(it) != {"ecco_reserve_set_result"} or it["ecco_reserve_set_result"].get("max") != 255 or "initial" in it["ecco_reserve_set_result"]:
        bad.append("the result helper is not exactly one input_text with max 255 and no initial value")
    sc = doc["script"]
    if set(sc) != {"ecco_reserve_set"}:
        return bad + [f"scripts are {sorted(sc)}"]
    s = sc["ecco_reserve_set"]
    if s.get("mode") != "single" or set(s.get("fields") or {}) != {"value", "confirm"}:
        bad.append("the script is not mode single with exactly the fields value and confirm")
    acts = collect(doc, "action", [])
    if set(acts) != ALLOWED_ACTIONS:
        bad.append(f"the service calls are {sorted(set(acts))}")
    # the one write: input_number.set_value on exactly the reserve helper, once
    nums = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("action") == "input_number.set_value":
                nums.append(((node.get("target") or {}).get("entity_id"), node.get("continue_on_error")))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(s)
    if nums != [(HELPER, True)]:
        bad.append(f"input_number.set_value calls are {nums}")
    seq = s.get("sequence") or []
    idx = [i for i, a in enumerate(seq) if isinstance(a, dict) and a.get("action") == "input_number.set_value"]
    if len(idx) != 1 or idx[0] < 1 or not (isinstance(seq[idx[0] - 1], dict) and seq[idx[0] - 1].get("action") == "input_text.set_value"
                                           and str((seq[idx[0] - 1].get("data") or {}).get("value", "")).startswith("WRITING {{ stamp }} - writing {{ want }} percent")):
        bad.append("the write is not directly preceded by the stamped WRITING text")
    if "state_attr('input_number.ecco_minimum_reserve_soc', 'min')" not in text or "state_attr('input_number.ecco_minimum_reserve_soc', 'max')" not in text:
        bad.append("the helper's own min and max are not read")
    texts = []

    def walk2(node):
        if isinstance(node, dict):
            if node.get("action") == "input_text.set_value":
                texts.append((node.get("target") or {}).get("entity_id"))
            for v in node.values():
                walk2(v)
        elif isinstance(node, list):
            for v in node:
                walk2(v)
    walk2(s)
    if not texts or set(texts) != {RESULT}:
        bad.append(f"input_text.set_value targets are {texts}")
    code = code_lines(text)
    ids = {f"{m.group(1)}.{m.group(2)}" for m in ID_RE.finditer(code)} - ALLOWED_ACTIONS
    if ids != {HELPER, RESULT, PLAN}:
        bad.append(f"it mentions {sorted(ids)} (expected the helper, the result text and the plan's effective reserve)")
    dom = sorted({i for i in ids if i.split(".", 1)[0] in FORBIDDEN_DOMAINS})
    if dom:
        bad.append(f"a write domain appears: {dom}")
    if "ecco_clock_dongle" in text:
        bad.append("it names a dongle entity")
    low = code.lower()
    for word in (INTEL, SOLCAST, "forecast", "intelligence"):
        if word in low:
            bad.append(f"it reads or names {word!r}")
    if "template" in doc or "automation" in doc:
        bad.append("a template or an automation appears")
    if re.search(r"\bnotify\.|\bhomeassistant\.|\btrigger\b", code):
        bad.append("a notify service, a homeassistant service or a trigger appears")
    for p in privacy_problems(text):
        bad.append(f"hygiene: {p}")
    if "\r" in text or "\t" in text:
        bad.append("a CR or a tab")
    for phrase in HEADER_MUST:
        if phrase not in text:
            bad.append(f"the header lost {phrase!r}")
    return bad


# ===========================================================================================================================
# scenarios (each returns the problems it found, for the package and for every mutant)
# ===========================================================================================================================
STAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"


def go(text, owner=5, cut=None, plan=True, **fields):
    cw = M.ControlWorld(text, reserve=owner, with_plan=plan)
    if cut:
        cw.power_cut(cut)
    n0, h0 = len(cw.w.service_log), len(cw.w.history)
    res = cw.run(**fields)
    cw.n0, cw.h0 = n0, h0
    return cw, res


def kinds(cw) -> list:
    return [(s, e) for s, e, _d in cw.services(cw.n0)]


def judge(label: str, cw, res: str, kind: str, owner_after, notified: bool, writes: int, bad: list, extra: str = "") -> None:
    pat = {"OK": rf"^OK {STAMP} - your reserve is now \d+ percent \(it was \d+\)\. ", "NOCHANGE": rf"^OK {STAMP} - NO CHANGE: your reserve already is \d+ percent; nothing was written$"}.get(
        kind, rf"^REFUSED (?:{kind}) {STAMP} - ")
    if not re.match(pat, res) or len(res) > 255 or (kind == "OK" and not res.endswith("Nothing was written to the inverter or the dongle.")):
        bad.append(f"{label}: result {res!r}")
    if abs(float(cw.owner()) - float(owner_after)) > 1e-9:
        bad.append(f"{label}: the helper reads {cw.owner()}, wanted {owner_after}")
    if (NOTE in cw.notified()) != notified:
        bad.append(f"{label}: notification {list(cw.notified())}, wanted {notified}")
    if len(cw.write_log) != writes:
        bad.append(f"{label}: {len(cw.write_log)} reserve writes, wanted {writes}")
    if extra and extra not in res:
        bad.append(f"{label}: result lacks {extra!r}: {res!r}")
    if kind == "OK" and "lower" in res.lower():
        bad.append(f"{label}: an OK text says lower: {res!r}")


def sc_table(text: str) -> list:
    bad = []
    # (label, owner, power cut reserve, fields, kind, helper after, notification, writes, a phrase the result must carry)
    cases = [
        ("a raise needs no confirm", 5, None, dict(value=10), "OK", 10, False, 1, "The plan reserve is now 10 percent."),
        ("a raise with confirm false", 5, None, dict(value=6, confirm=False), "OK", 6, False, 1, ""),
        ("a raise to the maximum", 5, None, dict(value=80), "OK", 80, False, 1, "The plan reserve is now 80 percent."),
        ("the same value is NO CHANGE and writes nothing", 5, None, dict(value=5), "NOCHANGE", 5, False, 0, ""),
        ("zero is a whole percent in range: lowering to 0 asks to confirm", 5, None, dict(value=0), "CONFIRM_NEEDED", 5, False, 0, "nothing was written"),
        ("a lowering asks to confirm", 5, None, dict(value=3), "CONFIRM_NEEDED", 5, False, 0, "call again with confirm true"),
        ("a lowering with confirm false asks", 5, None, dict(value=3, confirm=False), "CONFIRM_NEEDED", 5, False, 0, ""),
        ("a lowering with confirm true is written", 5, None, dict(value=3, confirm=True), "OK", 3, False, 1, "(it was 5)"),
        ("lowering to 0 with confirm", 5, None, dict(value=0, confirm=True), "OK", 0, False, 1, "The plan reserve is now 0 percent."),
        ("lowering by one from the maximum asks", 80, None, dict(value=79), "CONFIRM_NEEDED", 80, False, 0, "your reserve 80 -> 79 is a lowering"),
        ("lowering from the maximum with confirm", 80, None, dict(value=40, confirm=True), "OK", 40, False, 1, "(it was 80)"),
        ("raising from zero by one", 0, None, dict(value=1), "OK", 1, False, 1, ""),
        ("zero over zero is NO CHANGE", 0, None, dict(value=0), "NOCHANGE", 0, False, 0, ""),
        ("a power cut reserve: raising the owner's value below it still asks (below the reserve the plan uses now), and the text says what it is (F7)", 5, 80, dict(value=20), "CONFIRM_NEEDED", 5, False, 0,
         "your reserve 5 -> 20 is below the effective reserve 80: nothing was written; call again with confirm true to set your own reserve to 20 (the plan keeps 80 until the power-cut reserve ends)"),
        ("a power cut reserve: the same raise with confirm is written and the OK text says the plan keeps 80, not that a lower value does anything (F7)", 5, 80, dict(value=20, confirm=True), "OK", 20, False, 1,
         "The plan keeps using 80 percent until the Prepare for power cut reserve ends: your reserve 5 -> 20 does not change that."),
        ("a power cut reserve: a raise to one below its value still asks", 40, 80, dict(value=79), "CONFIRM_NEEDED", 40, False, 0, "your reserve 40 -> 79 is below the effective reserve 80"),
        ("a power cut reserve: lowering the owner's value without confirm asks and says it is a lowering and what the plan keeps", 40, 80, dict(value=20), "CONFIRM_NEEDED", 40, False, 0,
         "your reserve 40 -> 20 is a lowering; the plan keeps 80 until the power-cut reserve ends; nothing was written; call again with confirm true to lower it"),
        ("a power cut reserve: lowering the owner's value with confirm is allowed and does not lower the plan reserve", 40, 80, dict(value=20, confirm=True), "OK", 20, False, 1,
         "The plan keeps using 80 percent until the Prepare for power cut reserve ends: your reserve 40 -> 20 does not change that."),
        ("a power cut reserve of 100: the same raise asks, with the longest text", 5, 100, dict(value=20), "CONFIRM_NEEDED", 5, False, 0, "(the plan keeps 100 until the power-cut reserve ends)"),
        ("a power cut reserve: the same value as the owner's is NO CHANGE", 5, 80, dict(value=5), "NOCHANGE", 5, False, 0, ""),
        ("a power cut reserve: raising to its own value needs no confirm", 5, 80, dict(value=80), "OK", 80, False, 1, "The plan reserve is now 80 percent."),
        ("a power cut reserve below the owner's own does not count: the plan uses the owner's value", 50, 40, dict(value=45), "CONFIRM_NEEDED", 50, False, 0, "your reserve 50 -> 45 is a lowering; nothing was written"),
    ]
    for label, owner, cut, fields, kind, after, notified, writes, phrase in cases:
        cw, res = go(text, owner, cut, **fields)
        judge(label, cw, res, kind, after, notified, writes, bad, phrase)
    # the owner-only lowering: the plan's value is below the owner's (a plain sensor, as no real plan can read): the owner's own reserve is still compared
    cw, res = go(text, 10, None, plan=False, value=7)
    cw.w.set(PLAN, "4")
    cw.n0, cw.h0 = len(cw.w.service_log), len(cw.w.history)
    res = cw.run(value=7)
    judge("lowering below the owner's own reserve but above the plan's asks", cw, res, "CONFIRM_NEEDED", 10, False, 0, bad, "your reserve 10 -> 7 is a lowering")
    if "power-cut" in res:
        bad.append(f"a plain lowering mentions a power cut: {res!r}")
    return bad


def sc_values(text: str) -> list:
    bad = []
    nan, inf = float("nan"), float("inf")
    refused = [(None, "NOT_A_NUMBER"), ("", "NOT_A_NUMBER"), (" ", "NOT_A_NUMBER"), ("abc", "NOT_A_NUMBER"), ("7x", "NOT_A_NUMBER"), ("nan", "NOT_A_NUMBER"), (nan, "NOT_A_NUMBER"),
               (True, "NOT_A_NUMBER"), (False, "NOT_A_NUMBER"), ([], "NOT_A_NUMBER"), ([7], "NOT_A_NUMBER"), ({}, "NOT_A_NUMBER"), (inf, "OUT_OF_RANGE|NOT_A_NUMBER"), (-inf, "OUT_OF_RANGE|NOT_A_NUMBER"),
               ("inf", "OUT_OF_RANGE"), (-1, "OUT_OF_RANGE"), ("-1", "OUT_OF_RANGE"), (81, "OUT_OF_RANGE"), ("81", "OUT_OF_RANGE"), (100, "OUT_OF_RANGE"), (1000, "OUT_OF_RANGE"),
               (80.5, "OUT_OF_RANGE"), (-0.5, "OUT_OF_RANGE"), (5.5, "NOT_WHOLE"), ("5.5", "NOT_WHOLE"), (0.5, "NOT_WHOLE"), (79.9, "NOT_WHOLE"), (6.0000001, "NOT_WHOLE")]
    for v, code in refused:
        cw, res = go(text, 5, None, value=v, confirm=True)
        judge(f"value {v!r}", cw, res, code, 5, True, 0, bad)
    cw, res = go(text, 5, None)
    judge("no value field at all", cw, res, "NOT_A_NUMBER", 5, True, 0, bad)
    for v, want in [("7", 7), (7.0, 7), (" 8 ", 8), ("1e1", 10), ("+9", 9), (80, 80), ("80", 80), (6, 6)]:
        cw, res = go(text, 5, None, value=v)
        judge(f"value {v!r}", cw, res, "OK", want, False, 1, bad)
    for c, kind, after in [(True, "OK", 3), (False, "CONFIRM_NEEDED", 5), (None, "CONFIRM_NEEDED", 5), ("true", "CONFIRM_NEEDED", 5), ("True", "CONFIRM_NEEDED", 5), (1, "CONFIRM_NEEDED", 5),
                           ("yes", "CONFIRM_NEEDED", 5), ("on", "CONFIRM_NEEDED", 5), ([], "CONFIRM_NEEDED", 5), ({}, "CONFIRM_NEEDED", 5), ("", "CONFIRM_NEEDED", 5), (MISSING, "CONFIRM_NEEDED", 5)]:
        cw, res = go(text, 5, None, value=3, confirm=c)
        judge(f"confirm {c!r}", cw, res, kind, after, False, 1 if kind == "OK" else 0, bad)
    return bad


def sc_unreadable(text: str) -> list:
    bad = []
    for junk in (None, "unavailable", "unknown", "", "abc", "nan", "inf", "-1", "101"):
        cw = M.ControlWorld(text, reserve=5)
        cw.raw(HELPER, junk)
        n0 = len(cw.w.service_log)
        res = cw.run(value=10, confirm=True)
        cw.n0 = n0
        judge(f"the helper reads {junk!r}", cw, res, "HELPER_UNREADABLE", 5 if junk is None else 5, True, 0, bad) if False else None
        if not re.match(rf"^REFUSED HELPER_UNREADABLE {STAMP} - ", res) or cw.write_log or NOTE not in cw.notified():
            bad.append(f"the helper reads {junk!r}: {res!r} writes {len(cw.write_log)} notified {list(cw.notified())}")
    for junk in (None, "unavailable", "unknown", "", "abc", "nan", "inf", "-1", "101"):
        # a LOWERING cannot be judged: refused, with confirm too, nothing written
        cw = M.ControlWorld(text, reserve=5, with_plan=False)
        cw.raw(PLAN, junk)
        res = cw.run(value=3, confirm=True)
        if not re.match(rf"^REFUSED RESERVE_UNREADABLE {STAMP} - ", res) or cw.write_log or NOTE not in cw.notified() or float(cw.owner()) != 5.0:
            bad.append(f"the plan reserve reads {junk!r}: a lowering reads {res!r} writes {len(cw.write_log)}")
        # a raise needs no plan reserve: written, and the result says the plan reserve cannot be read
        cw = M.ControlWorld(text, reserve=5, with_plan=False)
        cw.raw(PLAN, junk)
        res = cw.run(value=10)
        if not res.startswith("OK ") or "The plan reserve cannot be read now." not in res or float(cw.owner()) != 10.0 or len(cw.write_log) != 1:
            bad.append(f"the plan reserve reads {junk!r}: a raise reads {res!r} writes {len(cw.write_log)}")
        # the same value: nothing to write
        cw = M.ControlWorld(text, reserve=5, with_plan=False)
        cw.raw(PLAN, junk)
        res = cw.run(value=5)
        if "NO CHANGE" not in res or cw.write_log:
            bad.append(f"the plan reserve reads {junk!r}: the same value reads {res!r}")
    # the plan package is not installed at all: the sensor does not exist
    cw = M.ControlWorld(text, reserve=5, with_plan=False)
    cw.w.states.pop(PLAN, None)
    res = cw.run(value=3, confirm=True)
    if not re.match(rf"^REFUSED RESERVE_UNREADABLE {STAMP} - ", res) or cw.write_log:
        bad.append(f"no plan sensor: a lowering reads {res!r}")
    res = cw.run(value=10)
    if not res.startswith("OK ") or len(cw.write_log) != 1:
        bad.append(f"no plan sensor: a raise reads {res!r}")
    return bad


def sc_failure(text: str) -> list:
    bad = []
    for label, hook in (("the write does not stick", dict(drop=True)), ("the write lands on another number", dict(skew=1.0)), ("the write raises", dict(raise_next=1))):
        cw = M.ControlWorld(text, reserve=5)
        for k, v in hook.items():
            setattr(cw, k, v)
        n0 = len(cw.w.service_log)
        res = cw.run(value=10)
        cw.n0 = n0
        if not re.match(rf"^FAILED WRITE_NOT_CONFIRMED {STAMP} - ", res) or len(cw.write_log) != 1 or NOTE not in cw.notified():
            bad.append(f"{label}: {res!r} writes {len(cw.write_log)} notified {list(cw.notified())}")
        if label == "the write does not stick" and abs(float(cw.owner()) - 5.0) > 1e-9:
            bad.append("a dropped write changed the helper")
        # the next success dismisses the notification and says OK
        cw.drop, cw.skew, cw.raise_next = False, 0.0, 0
        res = cw.run(value=30)
        if not res.startswith("OK ") or NOTE in cw.notified() or float(cw.owner()) != 30.0:
            bad.append(f"{label}: the retry reads {res!r}, notified {list(cw.notified())}")
    return bad


def sc_abort(text: str) -> list:
    """F8: a write that raises a VALIDATION error (vol.Invalid) is not continued on by continue_on_error: the run ENDS at the call. The result text must then read WRITING (stamped, not OK) and an earlier
    OK must not stay up; a helper range narrowed after a request is refused before any write; an unreadable range is refused."""
    bad = []
    cw = M.ControlWorld(text, reserve=5)
    res1 = cw.run(value=10)
    if not res1.startswith("OK "):
        return [f"the first request reads {res1!r}"]
    cw.invalid_next = 1
    res = cw.run(value=20)
    if not re.match(rf"^WRITING {STAMP} - writing 20 percent; if this text stays, the run did not finish", res) or res.startswith("OK") or res == res1:
        bad.append(f"after an aborted run the result reads {res!r} (an earlier OK was {res1!r})")
    if float(cw.owner()) != 10.0 or len(cw.write_log) != 2:
        bad.append(f"an aborted run: the helper reads {cw.owner()}, writes {len(cw.write_log)}")
    # a Home Assistant error from the call IS continued on: judged by the read-back
    cw.raise_next = 1
    res = cw.run(value=30)
    if not re.match(rf"^FAILED WRITE_NOT_CONFIRMED {STAMP} - ", res):
        bad.append(f"a Home Assistant error from the write reads {res!r}")
    # the next request works: the run is not stuck
    res = cw.run(value=40)
    if not res.startswith("OK ") or float(cw.owner()) != 40.0:
        bad.append(f"the request after an aborted run reads {res!r}")
    # a helper range narrowed after the last request: refused BEFORE the write, naming the range; no write attempt at all
    for lo, hi, value, want in ((0, 50, 60, "from 0 to 50"), (0, 50, 51, "from 0 to 50"), (10, 80, 5, "from 10 to 80"), (0, 30, 80, "from 0 to 30")):
        cw = M.ControlWorld(text, reserve=20)
        cw.narrow_helper(lo, hi)
        n0 = len(cw.write_log)
        res = cw.run(value=value, confirm=True)
        if not re.match(rf"^REFUSED OUT_OF_RANGE {STAMP} - ", res) or want not in res or len(cw.write_log) != n0 or NOTE not in cw.notified() or float(cw.owner()) != 20.0:
            bad.append(f"a helper range {lo}..{hi} and the value {value}: {res!r} writes {len(cw.write_log) - n0}")
        if cw.pw.rejected:
            bad.append(f"the helper itself refused a write: {cw.pw.rejected[:1]}")
    cw = M.ControlWorld(text, reserve=20)
    cw.narrow_helper(0, 50)
    res = cw.run(value=50)
    if not res.startswith("OK ") or float(cw.owner()) != 50.0:
        bad.append(f"the new maximum itself is refused: {res!r}")
    cw = M.ControlWorld(text, reserve=20)
    cw.narrow_helper(10, 80)
    res = cw.run(value=10, confirm=True)
    if not res.startswith("OK ") or float(cw.owner()) != 10.0:
        bad.append(f"the new minimum itself is refused: {res!r}")
    # a helper range WIDER than 0..80 (Home Assistant's own range 0..100): the script's fixed 0..80 still holds
    for value in (81, 100, 90):
        cw = M.ControlWorld(text, reserve=20)
        cw.narrow_helper(0, 100)
        res = cw.run(value=value, confirm=True)
        if not re.match(rf"^REFUSED OUT_OF_RANGE {STAMP} - ", res) or "from 0 to 80" not in res or cw.write_log:
            bad.append(f"a helper range 0..100 and the value {value}: {res!r} writes {len(cw.write_log)}")
    cw = M.ControlWorld(text, reserve=20)
    cw.narrow_helper(0, 100)
    res = cw.run(value=80)
    if not res.startswith("OK ") or float(cw.owner()) != 80.0:
        bad.append(f"80 with a helper range 0..100 reads {res!r}")
    # an unreadable range does not lift the fixed 0..80: the value is refused as out of range first, an in-range value as HELPER_UNREADABLE
    for value, code in ((81, "OUT_OF_RANGE"), (-1, "OUT_OF_RANGE"), (100, "OUT_OF_RANGE"), (-5, "OUT_OF_RANGE"), (30, "HELPER_UNREADABLE"), (80, "HELPER_UNREADABLE"), (0, "HELPER_UNREADABLE")):
        cw = M.ControlWorld(text, reserve=20)
        cw.w.states[HELPER] = (cw.w.state(HELPER), {})
        res = cw.run(value=value, confirm=True)
        if not re.match(rf"^REFUSED {code} {STAMP} - ", res) or cw.write_log:
            bad.append(f"the helper range unreadable and the value {value}: {res!r}, wanted {code}")
    # the helper's range cannot be read: a refusal, never a guess
    for attrs in ({}, {"min": 0.0}, {"max": 80.0}, {"min": "abc", "max": 80.0}, {"min": 0.0, "max": "unknown"}, {"min": 0.0, "max": 500.0}, {"min": -3.0, "max": 80.0}):
        cw = M.ControlWorld(text, reserve=20)
        cw.w.states[HELPER] = (cw.w.state(HELPER), dict(attrs))
        res = cw.run(value=30)
        if not re.match(rf"^REFUSED HELPER_UNREADABLE {STAMP} - ", res) or cw.write_log:
            bad.append(f"the helper attributes {attrs}: {res!r} writes {len(cw.write_log)}")
    return bad


NOCHANGE_SPELLINGS = [5, 5.0, "5", "5.0", " 5 ", "+5", "5e0", "05", "5.00", "0.5e1"]


def sc_nochange(text: str) -> list:
    """F9: the same value is NO CHANGE whatever its spelling: it is compared as a number, nothing is written, nothing is asked, with and without a power cut reserve and with confirm either way."""
    bad = []
    for owner, spellings in ((5, NOCHANGE_SPELLINGS), (0, [0, 0.0, "0", "0.0", " 0", "-0", "-0.0", "+0", "00"]), (80, [80, "80.0", "8e1", " 80 "]), (1, [1, "1.0", "+1"])):
        for v in spellings:
            for cut, cf in ((None, MISSING), (None, True), (90, MISSING), (90, False)):
                kw = dict(value=v)
                if cf is not MISSING:
                    kw["confirm"] = cf
                cw, res = go(text, owner, cut, **kw)
                if not re.match(rf"^OK {STAMP} - NO CHANGE: your reserve already is {owner} percent; nothing was written$", res) or cw.write_log or NOTE in cw.notified():
                    bad.append(f"owner {owner}, value {v!r}, power cut {cut}: {res!r} writes {len(cw.write_log)}")
    return bad


def sc_lowering(text: str) -> list:
    """F9: a LOWERING with an unreadable plan reserve is refused for every owner reserve (1, 2, 3, 40, 80), whatever confirm says; a raise and the same value go on."""
    bad = []
    for owner in (1, 2, 3, 40, 80):
        for junk in (None, "unavailable", "unknown", "", "abc"):
            for cf in (True, MISSING):
                cw = M.ControlWorld(text, reserve=owner, with_plan=False)
                cw.raw(PLAN, junk)
                kw = dict(value=owner - 1)
                if cf is not MISSING:
                    kw["confirm"] = cf
                res = cw.run(**kw)
                if not re.match(rf"^REFUSED RESERVE_UNREADABLE {STAMP} - ", res) or cw.write_log or NOTE not in cw.notified() or float(cw.owner()) != float(owner):
                    bad.append(f"owner {owner}, plan {junk!r}, confirm {cf!r}: a lowering to {owner - 1} reads {res!r} writes {len(cw.write_log)}")
        cw = M.ControlWorld(text, reserve=owner, with_plan=False)
        cw.raw(PLAN, "unknown")
        res = cw.run(value=0, confirm=True) if owner == 0 else cw.run(value=min(owner + 1, 80))
        if owner < 80 and (not res.startswith("OK ") or len(cw.write_log) != 1):
            bad.append(f"owner {owner}: a raise with an unreadable plan reserve reads {res!r}")
    return bad


def sc_text(text: str) -> list:
    """The result is always one line below the helper's 255 characters, the helper never rejects it, and a success carries the stamp, the new and the old value."""
    bad = []
    worst = 0
    for owner, cut, fields in [(5, None, dict(value=10)), (40, 80, dict(value=20, confirm=True)), (5, 80, dict(value=20)), (80, None, dict(value=79)), (5, None, dict(value="x" * 400)),
                               (50, 40, dict(value=45)), (5, 100, dict(value=3, confirm=True)), (5, 100, dict(value=20)), (40, 100, dict(value=20)), (40, 100, dict(value=20, confirm=True)),
                               (79, 100, dict(value=78)), (5, 100, dict(value=99))]:
        cw, res = go(text, owner, cut, **fields)
        worst = max(worst, len(res))
        if "\n" in res or len(res) > 250 or not res or any("invalid value of length" in w for w in cw.w.warnings):
            bad.append(f"result {res!r} ({len(res)} characters)")
        if res.startswith("REFUSED CONFIRM_NEEDED") and not (res.endswith("lower it") or res.endswith("power-cut reserve ends)")):
            bad.append(f"a CONFIRM_NEEDED text is cut short: {res!r}")
    return bad


def sc_vocabulary(text: str) -> list:
    """Over a whole session the only service calls are the four allowed ones on the allowed entities, and no state outside the helper, the result text and the script itself changes."""
    bad = []
    cw = M.ControlWorld(text, reserve=5)
    n0, h0 = len(cw.w.service_log), len(cw.w.history)
    for fields in (dict(value=10), dict(value=3), dict(value=3, confirm=True), dict(value="abc"), dict(value=99), dict(value=10), dict(value=10), dict(value=5.5)):
        cw.run(**fields)
    cw.drop = True
    cw.run(value=30)
    cw.drop = False
    cw.run(value=30)
    calls = cw.services(n0)
    for s, e, d in calls:
        if s not in ALLOWED_ACTIONS:
            bad.append(f"service {s}")
        elif s == "input_number.set_value" and e != HELPER:
            bad.append(f"input_number.set_value on {e}")
        elif s == "input_text.set_value" and e != RESULT:
            bad.append(f"input_text.set_value on {e}")
        elif s.startswith("persistent_notification") and d.get("notification_id") != NOTE:
            bad.append(f"a notification other than {NOTE}")
    touched = {e for _t, e, _s in cw.w.history[h0:]}
    if touched - {HELPER, RESULT, "script.ecco_reserve_set"}:
        bad.append(f"states changed: {sorted(touched - {HELPER, RESULT, 'script.ecco_reserve_set'})}")
    if not any(s == "input_number.set_value" for s, _e, _d in calls) or not any(s == "persistent_notification.dismiss" for s, _e, _d in calls):
        bad.append("the session did not exercise the write and the dismissal")
    if cw.w.warnings and any("already running" in w for w in cw.w.warnings):
        bad.append("a run found the script still running")
    return bad


def sc_restart(text: str) -> list:
    """A Home Assistant restart runs nothing of this package (it has no trigger), the helper and the result text come back as they were, the script works afterwards, and a helper that
    comes back unreadable is refused (never a guess)."""
    bad = []
    cw = M.ControlWorld(text, reserve=5)
    res = cw.run(value=10)
    if not res.startswith("OK "):
        bad.append(f"the first request reads {res!r}")
    n0 = len(cw.w.service_log)
    cw.pw.restart()
    cw.w.run_until(cw.w.t + 300)
    if cw.services(n0):
        bad.append(f"a restart ran services: {cw.services(n0)[:2]}")
    if float(cw.owner()) != 10.0 or "your reserve is now 10 percent" not in cw.result:
        bad.append("the helper or the result text did not come back after a restart")
    res = cw.run(value=10)
    if "NO CHANGE" not in res:
        bad.append(f"the same value after a restart reads {res!r}")
    res = cw.run(value=12)
    if not res.startswith("OK ") or float(cw.owner()) != 12.0:
        bad.append(f"a raise after a restart reads {res!r}")
    cw.pw.restart(numbers={HELPER: "unavailable"})
    w0 = len(cw.write_log)
    res = cw.run(value=20)
    if not re.match(rf"^REFUSED HELPER_UNREADABLE {STAMP} - ", res) or len(cw.write_log) != w0:
        bad.append(f"a helper that comes back unavailable reads {res!r}")
    return bad


BATTERY = [("static", lambda t: static_problems(t)), ("table", sc_table), ("values", sc_values), ("unreadable", sc_unreadable), ("failure", sc_failure), ("abort", sc_abort),
           ("nochange", sc_nochange), ("lowering", sc_lowering), ("text", sc_text), ("vocabulary", sc_vocabulary), ("restart", sc_restart)]


def battery(text: str, kill: bool = False, prefer: str | None = None, info: dict | None = None) -> list:
    found = []
    for name, fn in sorted(BATTERY, key=lambda b: 0 if b[0] == prefer else 1):
        try:
            probs = fn(text)
        except Exception as exc:  # noqa: BLE001 - a mutant that breaks the model is caught
            probs = [f"{type(exc).__name__}: {str(exc)[:100]}"]
        if probs:
            found += [f"[{name}] {p}" for p in probs]
            if info is not None:
                info["section"] = name
            if kill:
                return found
    return found


# ===========================================================================================================================
print("[0] static: the file, its vocabulary, its reads, its words")
# ===========================================================================================================================
check("the package parses and satisfies every static rule (one script, one helper, the write vocabulary, the reads, the words, hygiene, the header)", static_problems(PKG_TEXT) == [],
      str(static_problems(PKG_TEXT)[:3]))
check("the static rules are live: each flags an injected breach",
      all(static_problems(m) for m in (PKG_TEXT + "\n# 203.0.113.5\n", PKG_TEXT.replace("persistent_notification.dismiss", "button.press"), PKG_TEXT + "\t",
                                       PKG_TEXT.replace("input_number.ecco_minimum_reserve_soc\n        data:", "input_number.ecco_normal_max_charge_target\n        data:"),
                                       PKG_TEXT.replace("sensor.ecco_plan_effective_reserve') | float(none) -%}\n            {{ v if (v is number and v == v and v >= 0 and v <= 100) else -1 }}\n          hmin:",
                                                        "sensor.ecco_clock_dongle_ecco_battery_shutdown') | float(none) -%}\n            {{ v if (v is number and v == v and v >= 0 and v <= 100) else -1 }}\n          hmin:"),
                                       PKG_TEXT.replace("    max: 255", "    max: 255\n    initial: x"))))
class _TagTolerantLoader(UniqueKeyLoader):
    pass


_TagTolerantLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)   # !secret and the like


def defined_ids(path_or_text) -> tuple:
    """(entity ids, unique_ids, automation ids) a package defines."""
    text = path_or_text.read_text(encoding="utf-8") if isinstance(path_or_text, Path) else path_or_text
    d = yaml.load(text, Loader=_TagTolerantLoader) or {}
    ents, uids = set(), set()
    for dom in ("input_boolean", "input_datetime", "input_number", "input_text", "input_select", "script", "counter", "timer"):
        for k in d.get(dom) or {}:
            ents.add(f"{dom}.{k}")
    for blk in d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in blk.get(kind) or []:
                if isinstance(it, dict) and it.get("name"):
                    ents.add(f"{kind}.{slug(it['name'])}")
                    if it.get("unique_id"):
                        uids.add(it["unique_id"])
    autos = {a["id"] for a in d.get("automation") or [] if isinstance(a, dict) and a.get("id")}
    return ents, uids, autos


_mine = defined_ids(PKG_TEXT)
_clash = []
for _p in sorted(PKGS.glob("*.yaml")):
    if _p.name == Path(PKG_REL).name:
        continue
    try:
        _theirs = defined_ids(_p)
    except Exception as exc:  # noqa: BLE001
        _clash.append(f"{_p.name}: {exc}")
        continue
    for _a, _b, _what in zip(_mine, _theirs, ("entity", "unique_id", "automation id")):
        if _a & _b:
            _clash.append(f"{_p.name}: {_what} {sorted(_a & _b)[:2]}")
check(f"every id the package defines ({sum(len(x) for x in _mine)}: entities, unique_ids, automation ids) is defined in no other package of the repository ({len(list(PKGS.glob('*.yaml'))) - 1} others)",
      _clash == [] and sum(len(x) for x in _mine) >= 2, str(_clash[:3]))

site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
try:
    rendered, counts = render.render_text(PKG_REL, PKG_TEXT, site, render.firmware_actions(ROOT))
except render.RenderError as exc:
    rendered, counts = "", {"error": str(exc)[:120]}
check("the package names no dongle entity at all, so the site renderer has nothing to rewrite and leaves it unchanged", counts == {} and rendered == PKG_TEXT, str(counts))
man = yaml.safe_load(MANIFEST_TEXT)
stanza = [p for p in man["home_assistant_packages"] if p["source"] == PKG_REL]
check("the deployment manifest lists the package exactly once, to /config/packages, by ssh_file_copy, with restart_required false (two reloads install it; the pin-chain entry rrb1 pins the stanza)",
      stanza == [{"source": PKG_REL, "destination": "/config/packages/ecco_reserve_control.yaml", "method": "ssh_file_copy", "restart_required": False}], str(stanza))
README = re.sub(r"\s+", " ", (PKGS / "README.md").read_text(encoding="utf-8"))
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
BULLET = next((ln for ln in CHANGELOG.splitlines() if "ecco_reserve_control.yaml" in ln), "")
check("the packages README has a Reserve control section (the script, its fields, every refusal code, the confirmation rule, the power cut rule, the write vocabulary, the install reloads) and the CHANGELOG has one bullet "
      "that says offline, nothing installed and that it writes only the reserve helper",
      all(s in README for s in ("## Reserve control", "script.ecco_reserve_set", "input_text.ecco_reserve_set_result", "input_number.ecco_minimum_reserve_soc", "NOT_A_NUMBER", "OUT_OF_RANGE", "NOT_WHOLE",
                                "HELPER_UNREADABLE", "RESERVE_UNREADABLE", "CONFIRM_NEEDED", "WRITE_NOT_CONFIRMED", "Prepare for power cut", "never writes an inverter", "Input texts and Scripts",
                                "WRITING", "OWNER DECISION", "your reserve 5 -> 20", "a raise to or above the effective reserve never asks", "vol.Invalid", "compared as a number"))
      and all(s in BULLET for s in ("nothing installed", "writes only", "CONFIRM_NEEDED", "no inverter, dongle, TOU, number, switch or button entity", "restart", "Input texts and Scripts", "WRITING",
                                    "OWNER DECISION", "a raise that stays below")), BULLET[:80])
check("the package, the model and this suite are ASCII with LF line ends", b"\r" not in PKG_RAW and all(ord(c) < 128 for c in PKG_TEXT)
      and b"\r" not in (HERE / "_reserve_control_sim.py").read_bytes() and b"\r" not in Path(__file__).read_bytes())
helper = M.helper_package()["input_number"]["ecco_minimum_reserve_soc"]
check("the model's helper is the repository's own definition: 0 to 80, whole percent steps (the script's range is the helper's)", (helper["min"], helper["max"], helper["step"]) == (0, 80, 1), str(helper))
ctl = M.ControlWorld(PKG_TEXT)
ctl.pw.num(HELPER, 5)
rej0 = len(ctl.pw.rejected)
try:
    ctl.w.call("input_number.set_value", [HELPER], {"value": 81})
    raised = False
except M.VolInvalid:
    raised = True
check("the model's own control: the helper refuses a value outside its range with a VALIDATION error (vol.Invalid), as Home Assistant's does, and the interpreter ends a run on it even under continue_on_error "
      "(a Home Assistant error from the call, by contrast, is continued on)", raised and len(ctl.pw.rejected) == rej0 + 1)
_ab = M.ControlWorld(PKG_TEXT, reserve=5)
_ab.invalid_next = 1
_ab.run(value=10)
_ce = M.ControlWorld(PKG_TEXT, reserve=5)
_ce.raise_next = 1
_ce.run(value=10)
check("the model's second control: with the same package an injected validation error ends the run at the write (the text stays WRITING) and an injected Home Assistant error is continued on (FAILED)",
      _ab.result.startswith("WRITING ") and _ce.result.startswith("FAILED WRITE_NOT_CONFIRMED"), f"{_ab.result[:40]!r} {_ce.result[:40]!r}")
_hp = M.ControlWorld(PKG_TEXT, reserve=5)
check("the model's helper carries the attributes min, max and step the script reads", (_hp.w.state_attr(HELPER, "min"), _hp.w.state_attr(HELPER, "max"), _hp.w.state_attr(HELPER, "step")) == (0.0, 80.0, 1.0))

# ===========================================================================================================================
print("[1] to [5] the table, the values, the unreadable inputs, the failures, the text, the vocabulary")
# ===========================================================================================================================
for name, fn in BATTERY[1:]:
    probs = fn(PKG_TEXT)
    check({"table": "the table (18 cases): raise, lower, the same value, with and without confirm, the limits, a Prepare for power cut reserve, the owner-only lowering",
           "values": "every kind of junk in the value field (a missing field, text, nan, infinity, a boolean, a list, out of range, fractional) is refused with its own code and writes nothing; the accepted numeric spellings are written; "
                     "the confirm field is true only as the boolean true",
           "unreadable": "the owner's reserve helper (every request) and the plan's effective reserve (a lowering) each missing, unavailable, unknown, empty or junk: a refusal with its code, a notification and no write; a raise and the same value go on",
           "abort": "F8: a write that raises a validation error (vol.Invalid) ends the run and the text then reads WRITING (never an earlier OK); a Home Assistant error from the write is continued on (FAILED); a helper range narrowed after the last request "
                    "is refused before any write, naming the range; an unreadable range or an out-of-range maximum is refused",
           "nochange": "F9: the same value in every spelling (5.0, ' 5 ', +5, 5e0, 05, -0, 8e1) is NO CHANGE and writes nothing, with and without a power cut reserve and with confirm either way",
           "lowering": "F9: lowering from 1, 2, 3, 40 or 80 with an unreadable plan reserve is refused whatever confirm says (never a guess); a raise goes on",
           "failure": "a write that does not stick, one that lands on another number and one that raises each end FAILED WRITE_NOT_CONFIRMED with one write, no retry, no compensating write and a notification that the next success dismisses",
           "text": "every result is one line below the helper's 255 characters and the helper never rejects it, junk and a power cut included",
           "vocabulary": "over a whole session the only service calls are input_number.set_value on the reserve helper, input_text.set_value on the result text and the notification create and dismiss; no other state changes",
           "restart": "a restart runs nothing of this package, the helper and the result text come back, the script works afterwards, and a helper that comes back unavailable is refused"}[name],
          probs == [], str(probs[:2]))

# ===========================================================================================================================
print("[6] mutation: in-memory mutants of the package, each caught")
# ===========================================================================================================================
MUTANTS = [
    ("range: the lower bound becomes 1", "lo: \"{{ ([0, hmin] | max) if (hmin >= 0 and hmax >= 0) else 0 }}\"", "lo: \"{{ ([1, hmin] | max) if (hmin >= 0 and hmax >= 0) else 1 }}\""),
    ("range: the lower bound becomes -1", "lo: \"{{ ([0, hmin] | max) if (hmin >= 0 and hmax >= 0) else 0 }}\"", "lo: \"{{ ([-1, hmin] | max) if (hmin >= 0 and hmax >= 0) else -1 }}\""),
    ("range: the upper bound becomes 81", "hi: \"{{ ([80, hmax] | min) if (hmin >= 0 and hmax >= 0) else 80 }}\"", "hi: \"{{ ([81, hmax] | min) if (hmin >= 0 and hmax >= 0) else 81 }}\""),
    ("range: the upper bound becomes 79", "hi: \"{{ ([80, hmax] | min) if (hmin >= 0 and hmax >= 0) else 80 }}\"", "hi: \"{{ ([79, hmax] | min) if (hmin >= 0 and hmax >= 0) else 79 }}\""),
    ("whole: the whole-percent rule is dropped", "{%- elif f != (f | round(0)) -%}NOT_WHOLE", "{%- elif false -%}NOT_WHOLE"),
    ("number: a boolean is a number", "(x | float(none)) if (x is not boolean and x is not none) else none -%}\n            {%- if f is none", "(x | float(none)) if (x is not none) else none -%}\n            {%- if f is none"),
    ("number: nan is not refused as a non-number", "{%- if f is none or f != f -%}NOT_A_NUMBER", "{%- if f is none -%}NOT_A_NUMBER"),
    ("number: a missing value is not refused", "{%- if f is none or f != f -%}NOT_A_NUMBER", "{%- if f != f -%}NOT_A_NUMBER"),
    ("helper: an unreadable helper is accepted", "{%- elif owner_now < 0 or hmin < 0 or hmax < 0 -%}HELPER_UNREADABLE", "{%- elif false -%}HELPER_UNREADABLE"),
    ("helper: the helper's own bound is 50", "{{ v if (v is number and v == v and v >= 0 and v <= 100) else -1 }}\n          eff_now", "{{ v if (v is number and v == v and v >= 0 and v <= 50) else -1 }}\n          eff_now"),
    ("reserve: an unreadable plan reserve is accepted for a lowering", "{%- elif eff_now < 0 and f < owner_now -%}RESERVE_UNREADABLE", "{%- elif false -%}RESERVE_UNREADABLE"),
    ("reserve: an unreadable plan reserve refuses a raise too", "{%- elif eff_now < 0 and f < owner_now -%}RESERVE_UNREADABLE", "{%- elif eff_now < 0 -%}RESERVE_UNREADABLE"),
    ("reserve: an unreadable plan reserve refuses the same value too", "{%- elif f == owner_now -%}\n            {%- elif eff_now < 0 and f < owner_now", "{%- elif eff_now < 0 -%}RESERVE_UNREADABLE\n            {%- elif eff_now < 0 and f < owner_now"),
    ("reserve: the plan reserve's bound is 50", "{{ v if (v is number and v == v and v >= 0 and v <= 100) else -1 }}\n          hmin:", "{{ v if (v is number and v == v and v >= 0 and v <= 50) else -1 }}\n          hmin:"),
    ("same: the same value is no longer special", "{%- elif f == owner_now -%}\n", "{%- elif false -%}\n"),
    ("confirm: the plan's reserve is not compared", "(f < owner_now or f < eff_now)", "(f < owner_now)"),
    ("confirm: the owner's own reserve is not compared", "(f < owner_now or f < eff_now)", "(f < eff_now)"),
    ("confirm: a value equal to the reserve asks", "(f < owner_now or f < eff_now)", "(f <= owner_now or f <= eff_now)"),
    ("confirm: any truthy value confirms", "not (cf is boolean and cf)", "not cf"),
    ("confirm: it is always confirmed", "not (cf is boolean and cf)", "false"),
    ("write: another value is written", "          value: \"{{ want }}\"", "          value: \"{{ want + 1 }}\""),
    ("write: a raising call ends the run", "        continue_on_error: true\n", ""),
    ("verify: a larger helper passes", "{{ after == want }}", "{{ after >= want }}"),
    ("verify: a smaller helper passes", "{{ after == want }}", "{{ after <= want }}"),
    ("verify: the read-back is not judged", "{{ after == want }}", "{{ true }}"),
    ("stop: a refusal does not stop", "              - stop: \"refused\"\n", ""),
    ("stop: NO CHANGE does not stop", "              - stop: \"no change\"\n", ""),
    ("notice: the question of a lowering raises a notification", "!= 'CONFIRM_NEEDED' }}\"", "!= 'NEVER' }}\""),
    ("notice: a refusal raises no notification", "!= 'CONFIRM_NEEDED' }}\"", "== 'CONFIRM_NEEDED' }}\""),
    ("notice: a success does not dismiss the notice", "              - action: persistent_notification.dismiss", "              - action: persistent_notification.create"),
    ("text: the plan reserve is said to stay at equality", "if eff_after > want else", "if eff_after >= want else"),
    ("text: a power cut is not named in the question", "if eff_now > owner_now else ''", "if false else ''"),
    ("text: the success text is cut at 20 characters", "okmsg[:250]", "okmsg[:20]"),
    ("text: the refusal text is cut at 20 characters", "value: \"{{ result[:250] }}\"", "value: \"{{ result[:20] }}\"", 0),
    ("text: the refusal code of NOT_WHOLE changes", "REFUSED NOT_WHOLE {{ stamp }}", "REFUSED NOT_WHOLE_X {{ stamp }}"),
    ("text: the time stamp is empty", "stamp: \"{{ now().strftime('%Y-%m-%d %H:%M:%S') }}\"", "stamp: \"\""),
    ("text: the nothing-written claim of a success is removed", "Nothing was written to the inverter or the dongle.", "Done."),
    ("target: another helper is written", "          entity_id: input_number.ecco_minimum_reserve_soc\n        data:\n          value: \"{{ want }}\"", "          entity_id: input_number.ecco_normal_max_charge_target\n        data:\n          value: \"{{ want }}\""),
    ("target: the result goes to another text", "                  entity_id: input_text.ecco_reserve_set_result\n                data:\n                  value: \"{{ okmsg[:250] }}\"", "                  entity_id: input_text.ecco_plan_last_result\n                data:\n                  value: \"{{ okmsg[:250] }}\""),
    ("vocabulary: a switch call replaces the write", "      - action: input_number.set_value\n        continue_on_error: true", "      - action: switch.turn_off\n        continue_on_error: true"),
    ("reads: a dongle entity is read", "stamp: \"{{ now()", "zz: \"{{ states('sensor.ecco_clock_dongle_ecco_battery_shutdown') }}\"\n          stamp: \"{{ now()"),
    ("mode: the script is queued", "    mode: single\n    fields:", "    mode: queued\n    fields:"),
    ("wording: the header drops the effective-reserve rule", "does NOT lower the effective reserve", "lowers the effective reserve"),
    # --- NEW (F7, F8, F9) ---
    ("new write: the WRITING text is a fake OK", "value: \"WRITING {{ stamp }} - writing", "value: \"OK {{ stamp }} - writing"),
    ("new write: the WRITING text is empty", "value: \"WRITING {{ stamp }} - writing {{ want }} percent; if this text stays, the run did not finish and your reserve may or may not have changed (it was {{ owner_now | int }})\"", "value: \"\""),
    ("new write: the WRITING text names the wrong value", "writing {{ want }} percent; if this text stays", "writing {{ owner_now | int }} percent; if this text stays"),
    ("new write: the WRITING text has no stamp", "value: \"WRITING {{ stamp }} - writing", "value: \"WRITING - writing"),
    ("new range: the helper's maximum is ignored", "hi: \"{{ ([80, hmax] | min) if (hmin >= 0 and hmax >= 0) else 80 }}\"", "hi: \"{{ 80 }}\""),
    ("new range: the helper's minimum is ignored", "lo: \"{{ ([0, hmin] | max) if (hmin >= 0 and hmax >= 0) else 0 }}\"", "lo: \"{{ 0 }}\""),
    ("new range: the maximum is read from the minimum attribute", "state_attr('input_number.ecco_minimum_reserve_soc', 'max')", "state_attr('input_number.ecco_minimum_reserve_soc', 'min')"),
    ("new range: the minimum is read from the maximum attribute", "state_attr('input_number.ecco_minimum_reserve_soc', 'min')", "state_attr('input_number.ecco_minimum_reserve_soc', 'max')"),
    ("new range: an unreadable range is accepted", "{%- elif owner_now < 0 or hmin < 0 or hmax < 0 -%}HELPER_UNREADABLE", "{%- elif owner_now < 0 -%}HELPER_UNREADABLE"),
    ("new range: the refusal text names 0 to 80", "from {{ lo | int }} to {{ hi | int }} percent", "from 0 to 80 percent"),
    ("new text: a raise below the plan reserve is called a lowering", "is below the effective reserve {{ eff_now | int }}: nothing was written; call again with confirm true to set your own reserve to {{ want }} (the plan keeps {{ eff_now | int }} until the power-cut reserve ends)",
     "is a lowering; nothing was written; call again with confirm true to lower it"),
    ("new text: a lowering is called a raise below the plan reserve", "{%- elif want < owner_now -%}REFUSED CONFIRM_NEEDED", "{%- elif want > owner_now -%}REFUSED CONFIRM_NEEDED"),
    ("new text: the OK text says a lower value does nothing", "' does not change that.' if eff_after > want else", "' - your lower value does not lower it.' if eff_after > want else"),
    ("new text: the plan sentence swaps the values", "(owner_now | int) ~ ' -> ' ~ want ~ ' does not change that.'", "want ~ ' -> ' ~ (owner_now | int) ~ ' does not change that.'"),
    ("new text: the power cut is not named in a lowering", "{{ ('; the plan keeps ' ~ (eff_now | int) ~ ' until the power-cut reserve ends') if eff_now > owner_now else '' }}", "{{ '' }}"),
    ("new nochange: the raw value is compared", "value_template: \"{{ want == owner_now }}\"", "value_template: \"{{ value == owner_now }}\""),
    ("new nochange: the compare is on text", "value_template: \"{{ want == owner_now }}\"", "value_template: \"{{ want | string == owner_now | string }}\""),
    ("new nochange: the compare uses the plan reserve", "value_template: \"{{ want == owner_now }}\"", "value_template: \"{{ want == eff_now }}\""),
    ("new reserve: the unreadable plan reserve is not judged when the owner reserve is 1 or less", "{%- elif eff_now < 0 and f < owner_now -%}RESERVE_UNREADABLE", "{%- elif eff_now < 0 and f < owner_now and owner_now > 1 -%}RESERVE_UNREADABLE"),
    ("new reserve: the unreadable plan reserve is not judged when the owner reserve is 2 or less", "{%- elif eff_now < 0 and f < owner_now -%}RESERVE_UNREADABLE", "{%- elif eff_now < 0 and f < owner_now and owner_now > 2 -%}RESERVE_UNREADABLE"),
    ("new reserve: a lowering to zero is not judged with an unreadable plan reserve", "{%- elif eff_now < 0 and f < owner_now -%}RESERVE_UNREADABLE", "{%- elif eff_now < 0 and f < owner_now and f > 0 -%}RESERVE_UNREADABLE"),
    ("new reserve: an unreadable plan reserve is judged by confirm", "{%- elif eff_now < 0 and f < owner_now -%}RESERVE_UNREADABLE", "{%- elif eff_now < 0 and f < owner_now and not (cf is boolean and cf) -%}RESERVE_UNREADABLE"),
    ("hygiene: an address appears in a comment", "# NOT INSTALLED, NOT LIVE-PROVEN.", "# 198.51.100.7 NOT INSTALLED, NOT LIVE-PROVEN."),
]
total = len(MUTANTS)
killed = 0
survivors: list = []
prefer: dict = {}
for entry in MUTANTS:
    label, old, new = entry[:3]
    nth = entry[3] if len(entry) > 3 else None
    if (nth is None and PKG_TEXT.count(old) != 1) or (nth is not None and PKG_TEXT.count(old) <= nth):
        check(f"mutant anchor is unique: {label}", False, f"{PKG_TEXT.count(old)}x")
        continue
    if nth is None:
        mutated = PKG_TEXT.replace(old, new, 1)
    else:
        parts = PKG_TEXT.split(old)
        mutated = old.join(parts[:nth + 1]) + new + old.join(parts[nth + 1:])
    family = label.split(":", 1)[0]
    info: dict = {}
    found = battery(mutated, kill=True, prefer=prefer.get(family), info=info)
    if found:
        killed += 1
        prefer[family] = info.get("section")
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        survivors.append(label)
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
_new = len([m for m in MUTANTS if m[0].startswith("new ")])
check(f"{total} mutants, {_new} of them new for F7, F8 and F9 (the range and whole-percent rules, the helper's own range, the number test, the unreadable inputs, the lowering rule, the confirmation and its two texts, "
      "the WRITING text, the write and its read-back, the NO CHANGE compare, the stops, the notification, the texts, the targets, the vocabulary and the words): all caught",
      killed == total and total >= 55 and _new >= 15, f"{killed}/{total} {survivors[:3]}")
_harmless = PKG_TEXT.replace("# WHY. The owner's reserve", "# WHY, restated. The owner's reserve")
check("a harmless rewrite (a comment) survives the battery, and a rewrite of a rule does not", _harmless != PKG_TEXT and battery(_harmless, kill=True) == []
      and battery(PKG_TEXT.replace("f > hi -%}OUT_OF_RANGE", "f > hi + 8000 -%}OUT_OF_RANGE"), kill=True) != [])

# ===========================================================================================================================
print("[7] callers: nothing calls the script; the allow-list of callers is EMPTY (the panel card is added to it deliberately)")
# ===========================================================================================================================
# The script is pinned, by test_ecco_reserve_default.py, as one of the two named WRITERS of the reserve helper. That does not limit who CALLS the script. This section does: no file under home-assistant/ (packages,
# dashboards, prototypes and the tests, except the three that name the script as their subject) and no file under frontend/*/src may call it, in any spelling, unless the file is on ALLOWED_CALLERS. That list is EMPTY: there
# is no caller today. A future panel card is added to it deliberately, with a `confirm_from` text saying how the confirm field is obtained from a person (a second press, a typed value), and a caller may never pass a literal
# confirm true, allowed or not. This is a tripwire over text and parsed YAML / JSON, not a proof: a card that takes the script id from its own runtime configuration is out of its reach (each card's own suite pins the
# scripts it may address).
import functools  # noqa: E402

SET_ID = "ecco_reserve" + "_set"
DEFINING_REL = PKG_REL
TEST_NAMERS = frozenset({"home-assistant/tests/_reserve_control_sim.py", "home-assistant/tests/test_ecco_reserve_control.py", "home-assistant/tests/test_ecco_reserve_default.py"})
ALLOWED_CALLERS: dict = {}     # path -> {"confirm_from": "how a person gives the confirmation"}; EMPTY now. A future card is added here on purpose.
GENERIC_CALLS = ("script.turn_on", "script.toggle", "script.turn_off", "homeassistant.turn_on", "homeassistant.toggle", "homeassistant.turn_off")
CONFIRM_TEXT_RE = re.compile(r"""["']?confirm["']?\s*[:=]\s*(?:true\b|True\b|!0|1\b|["'](?:true|True)["'])""")
RULES = {
    "token": re.compile(r"reserve_set(?![A-Za-z0-9_])"),                           # the script id (and any id that ends in it); NOT its result text or its notification id
    "frag": re.compile(r"""ecco_reserve_?(?:['"`]|\$\{|\{\{|\{%)"""),                # the id built from pieces: 'script.ecco_reserve_' + x, `ecco_reserve_${x}`
    "dyn_ts": re.compile(r"""callService\s*\(\s*['"`]script['"`]\s*,\s*+(?!['"`])"""),   # a script-domain call whose service name is not a literal
    "confirm_re": CONFIRM_TEXT_RE,
    "suffixes": (".yaml", ".yml", ".json", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".py"),
    "skip": (),                      # path prefixes not scanned
    "frontend": True,
    "tests": "scan",                 # scan | skip | exempt_all
    "defining": "key",               # key | file: what of the defining package is exempt
    "parse_errors": "problem",       # problem | ignore
    "yaml_comments": "ignored",      # ignored | raw
    "json_as": "yaml",               # yaml | text
    "dyn_yaml": True,
    "dyn_keys": ("action", "service", "perform_action"),
    "generic": GENERIC_CALLS,
    "dyn_ts_on": True,
    "frag_on": True,
    "confirm_check": True,
    "confirm_from_required": True,
}


class _TolLoader(yaml.SafeLoader):
    pass


def _tolerant(loader, suffix, node):    # !secret, !include and the like: keep the content, never fail
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


_TolLoader.add_multi_constructor("!", _tolerant)


@functools.lru_cache(maxsize=None)
def _parsed(text: str, exempt_key: bool):
    """(strings, dicts) of one YAML / JSON text, or None when it cannot be parsed. `exempt_key`: the defining package, whose own `script:` key `ecco_reserve_set` is the definition and not a call."""
    try:
        doc = yaml.load(text, Loader=_TolLoader)
    except Exception:  # noqa: BLE001 - any parse failure is a failure to prove the file clean
        return None
    if exempt_key and isinstance(doc, dict) and isinstance(doc.get("script"), dict):
        doc = {**doc, "script": {("__defined__" if k == SET_ID else k): v for k, v in doc["script"].items()}}
    strings_: list = []
    dicts_: list = []

    def walk(n):
        if isinstance(n, dict):
            dicts_.append(n)
            for k, v in n.items():
                if isinstance(k, str):
                    strings_.append(k)
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
        elif isinstance(n, str):
            strings_.append(n)
    walk(doc)
    return tuple(strings_), tuple(dicts_)


def _has_template(s: str) -> bool:
    return "{{" in s or "{%" in s


def _targets(call: dict) -> list:
    data = call.get("data")
    out: list = []
    for part in (call.get("target"), call.get("entity_id"), data.get("entity_id") if isinstance(data, dict) else None):
        stack = [part]
        while stack:
            x = stack.pop()
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return out


def _literal_true(v) -> bool:
    return v is True or (isinstance(v, int) and not isinstance(v, bool) and v == 1) or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "on", "1", "{{ true }}", "{{true}}", "{{ 1 }}"))


def file_problems(rel: str, text: str, rules: dict, allow: dict) -> list:
    """Every way one file breaks the pin (empty = clean)."""
    if not rel.endswith(rules["suffixes"]) or any(rel.startswith(p) for p in rules["skip"]):
        return []
    if rel.startswith("home-assistant/tests/"):
        if rules["tests"] == "skip" or rules["tests"] == "exempt_all" or rel in TEST_NAMERS:
            return []
    elif not rel.startswith("home-assistant/") and not (rules["frontend"] and re.match(r"frontend/[^/]+/src/", rel)):
        return []
    if rel == DEFINING_REL and rules["defining"] == "file":
        return []
    allowed = rel in allow
    probs: list = []
    structured = rel.endswith((".yaml", ".yml")) or (rel.endswith(".json") and rules["json_as"] == "yaml")
    if structured:
        view = _parsed(text, rel == DEFINING_REL)
        if view is None:
            if rules["parse_errors"] == "problem":
                probs.append(f"{rel}: cannot be parsed, so it cannot be shown to hold no call")
        else:
            strs, dicts = view
            if not allowed:
                for s in strs:
                    if rules["token"].search(s):
                        probs.append(f"{rel}: names the script ({s.strip()[:50]!r})")
                    if rules["frag_on"] and rules["frag"].search(s):
                        probs.append(f"{rel}: builds the script id from pieces ({s.strip()[:50]!r})")
                if rules["dyn_yaml"]:
                    for d in dicts:
                        for name in [d[k] for k in rules["dyn_keys"] if isinstance(d.get(k), str)]:
                            if _has_template(name):
                                probs.append(f"{rel}: a templated action name could be the script ({name.strip()[:50]!r})")
                            if name in rules["generic"]:
                                for t in _targets(d):
                                    if _has_template(t) or t.strip().lower() == "all":
                                        probs.append(f"{rel}: {name} on a templated or open target could be the script ({t.strip()[:50]!r})")
                        if isinstance(d.get("script"), str) and _has_template(d["script"]):
                            probs.append(f"{rel}: a templated script step could be the script ({d['script'].strip()[:50]!r})")
            if allowed and rules["confirm_check"]:
                for d in dicts:
                    if "confirm" in d and _literal_true(d["confirm"]):
                        probs.append(f"{rel}: passes a literal confirm true")
        if rules["yaml_comments"] == "raw" and not allowed and rules["token"].search(text):
            probs.append(f"{rel}: names the script (raw text, comments included)")
    elif not allowed:
        if rules["token"].search(text):
            probs.append(f"{rel}: names the script")
        if rules["frag_on"] and rules["frag"].search(text):
            probs.append(f"{rel}: builds the script id from pieces")
        if rules["dyn_ts_on"] and rules["dyn_ts"].search(text):
            probs.append(f"{rel}: a script call whose service name is not a literal")
    if allowed:
        if rules["confirm_check"] and rules["confirm_re"].search(text):
            probs.append(f"{rel}: passes a literal confirm true")
        why = allow[rel].get("confirm_from") if isinstance(allow[rel], dict) else None
        if rules["confirm_from_required"] and not (isinstance(why, str) and len(why.strip()) >= 20):
            probs.append(f"{rel}: its allow-list entry does not say how confirm is obtained from a person")
    return probs


def tree_problems(files: dict, rules: dict, allow: dict) -> list:
    out: list = []
    for rel in sorted(files):
        out += file_problems(rel, files[rel], rules, allow)
    return out


def load_tree() -> dict:
    files: dict = {}
    roots = [ROOT / "home-assistant"] + sorted((ROOT / "frontend").glob("*/src"))
    for base in roots:
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in RULES["suffixes"] and "__pycache__" not in p.parts and "node_modules" not in p.parts:
                files[p.relative_to(ROOT).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return files


REAL = load_tree()
DEF_TEXT = PKG_TEXT
DEC_DASH = "home-assistant/dashboards/ecco_pro.yaml"
DEC_ALLOW_OK = {"confirm_from": "the owner presses a second, separate Confirm button after reading the lowering text"}
_CALL_TS = "this.hass.callService('script', 'ecco_reserve' + '_set', { value: 5 });"
NEGATIVE = [
    # (name, path, text, allow-list for this decoy): each must produce at least one problem
    ("an automation at 03:00 that calls the script with value 0 and confirm true", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n  - id: night_reserve\n    alias: night reserve\n    trigger:\n      - platform: time\n        at: '03:00:00'\n    action:\n      - action: script.{SET_ID}\n        data:\n          value: 0\n          confirm: true\n", {}),
    ("the same with the old service key", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n  - id: night_reserve\n    trigger:\n      - platform: time\n        at: '03:00:00'\n    action:\n      - service: script.{SET_ID}\n        data: {{value: 0, confirm: true}}\n", {}),
    ("script.turn_on with the script as the target", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n  - id: a\n    trigger: []\n    action:\n      - action: script.turn_on\n        target:\n          entity_id: script.{SET_ID}\n        data:\n          variables: {{value: 0, confirm: true}}\n", {}),
    ("script.turn_on with the script in the data entity_id", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n  - id: a\n    trigger: []\n    action:\n      - action: script.turn_on\n        data:\n          entity_id: script.{SET_ID}\n", {}),
    ("homeassistant.turn_on with a list of entities", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n  - id: a\n    trigger: []\n    action:\n      - action: homeassistant.turn_on\n        target:\n          entity_id: [script.other, script.{SET_ID}]\n", {}),
    ("a bare script step", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n  - id: a\n    trigger: []\n    action:\n      - script: {SET_ID}\n", {}),
    ("an action name built by a template", "home-assistant/packages/ecco_night.yaml",
     "automation:\n  - id: a\n    trigger: []\n    action:\n      - action: \"{{ 'script.ecco_reserve_' ~ 'set' }}\"\n", {}),
    ("a service name built by a template (the old key)", "home-assistant/packages/ecco_night.yaml",
     "automation:\n  - id: a\n    trigger: []\n    action:\n      - service: \"{{ s }}\"\n", {}),
    ("script.turn_on on a templated entity id", "home-assistant/packages/ecco_night.yaml",
     "automation:\n  - id: a\n    trigger: []\n    action:\n      - action: script.turn_on\n        target:\n          entity_id: \"script.{{ name }}\"\n", {}),
    ("homeassistant.turn_on on every entity", "home-assistant/packages/ecco_night.yaml",
     "automation:\n  - id: a\n    trigger: []\n    action:\n      - action: homeassistant.turn_on\n        target:\n          entity_id: all\n", {}),
    ("a templated bare script step", "home-assistant/packages/ecco_night.yaml",
     "automation:\n  - id: a\n    trigger: []\n    action:\n      - script: \"{{ which }}\"\n", {}),
    ("the id held in a variable and called through it", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n  - id: a\n    trigger: []\n    variables:\n      s: script.{SET_ID}\n    action:\n      - action: \"{{{{ s }}}}\"\n", {}),
    ("the id built from pieces in a template", "home-assistant/packages/ecco_night.yaml",
     "template:\n  - sensor:\n      - name: x\n        state: \"{{ 'script.ecco_reserve_' ~ 'set' }}\"\n", {}),
    ("an allowed-looking dashboard button (tap action, call-service)", DEC_DASH,
     f"views:\n  - cards:\n      - type: button\n        tap_action:\n          action: call-service\n          service: script.{SET_ID}\n          data: {{value: 3, confirm: true}}\n", {}),
    ("a dashboard button with perform-action", DEC_DASH,
     f"views:\n  - cards:\n      - type: button\n        tap_action:\n          action: perform-action\n          perform_action: script.{SET_ID}\n", {}),
    ("a dashboard as JSON", "home-assistant/dashboards/ecco_x.json",
     f'{{"views": [{{"cards": [{{"tap_action": {{"action": "call-service", "service": "script.{SET_ID}"}}}}]}}]}}', {}),
    ("a dashboard as JSON, templated through script.turn_on", "home-assistant/dashboards/ecco_x.json",
     '{"views": [{"cards": [{"tap_action": {"action": "perform-action", "service": "script.turn_on", "target": {"entity_id": "{{ s }}"}}}]}]}', {}),
    ("a prototype dashboard", "home-assistant/prototypes/intelligence-v1/ecco_x.yaml",
     f"views:\n  - cards:\n      - tap_action: {{action: call-service, service: script.{SET_ID}}}\n", {}),
    ("a prototype generator that writes the call", "home-assistant/prototypes/acs-stage1/x_transform.py",
     f"OUT = \"action: script.{SET_ID}\"\n", {}),
    ("a file that cannot be parsed", "home-assistant/packages/ecco_night.yaml",
     f"automation:\n\t- action: script.{SET_ID}\n", {}),
    ("the defining package with an automation appended that calls its script", DEFINING_REL,
     DEF_TEXT + f"\nautomation:\n  - id: late\n    trigger: []\n    action:\n      - action: script.{SET_ID}\n", {}),
    ("the defining package whose script calls itself", DEFINING_REL,
     DEF_TEXT.replace("    sequence:\n", f"    sequence:\n      - action: script.{SET_ID}\n", 1), {}),
    ("a card source with callService on the script", "frontend/ecco-reserve-card/src/card.ts", f"this.hass.callService('script', '{SET_ID}', {{ value: 5 }});", {}),
    ("a card source with the string form through script.turn_on", "frontend/ecco-reserve-card/src/card.ts",
     f"await hass.callService(\"script\", \"turn_on\", {{ entity_id: 'script.{SET_ID}', variables: {{ value: 5 }} }});", {}),
    ("a card source that builds the id from pieces", "frontend/ecco-reserve-card/src/card.ts", "const id = 'script.ecco_reserve_' + name; hass.callService('script', 'turn_on', { entity_id: id });", {}),
    ("a card source with a template literal", "frontend/ecco-reserve-card/src/card.ts", "const id = `script.ecco_reserve_${name}`;", {}),
    ("a card source that builds the id from two pieces after the prefix", "frontend/ecco-reserve-card/src/card.ts", "const n = 'ecco_' + 'reserve_set'; hass.callService('script', 'turn_on', { entity_id: 'script.' + n });", {}),
    ("a card source that calls a script domain service by a computed name", "frontend/ecco-reserve-card/src/card.ts", "hass.callService('script', name, { value: 5 });", {}),
    ("a card source with callWS", "frontend/ecco-reserve-card/src/card.ts", f"hass.callWS({{ type: 'call_service', domain: 'script', service: '{SET_ID}' }});", {}),
    ("a card source in a plain js file", "frontend/ecco-reserve-card/src/card.js", f"hass.callService('script', '{SET_ID}', {{}});", {}),
    ("a card source in a comment (strict: any mention in code counts)", "frontend/ecco-reserve-card/src/card.ts", f"// TODO call script.{SET_ID}\n", {}),
    ("a test file other than the three that name the script as their subject", "home-assistant/tests/test_ecco_something_else.py", f"CALL = 'script.{SET_ID}'\n", {}),
    ("an allowed card that passes a literal confirm true", "frontend/ecco-reserve-card/src/card.ts",
     f"hass.callService('script', '{SET_ID}', {{ value: 5, confirm: true }});", {"frontend/ecco-reserve-card/src/card.ts": DEC_ALLOW_OK}),
    ("an allowed card that passes a minified confirm", "frontend/ecco-reserve-card/src/card.ts",
     f"e.callService('script','{SET_ID}',{{value:5,confirm:!0}});", {"frontend/ecco-reserve-card/src/card.ts": DEC_ALLOW_OK}),
    ("an allowed card with a quoted confirm", "frontend/ecco-reserve-card/src/card.ts",
     f"hass.callService('script', '{SET_ID}', {{ value: 5, 'confirm': 'true' }});", {"frontend/ecco-reserve-card/src/card.ts": DEC_ALLOW_OK}),
    ("an allowed dashboard button that passes confirm true", DEC_DASH,
     f"views:\n  - cards:\n      - tap_action:\n          action: call-service\n          service: script.{SET_ID}\n          data: {{value: 3, confirm: true}}\n", {DEC_DASH: DEC_ALLOW_OK}),
    ("an allowed dashboard button that passes confirm as the text true", DEC_DASH,
     f"views:\n  - cards:\n      - tap_action:\n          action: call-service\n          service: script.{SET_ID}\n          data: {{value: 3, confirm: 'true'}}\n", {DEC_DASH: DEC_ALLOW_OK}),
    ("an allowed card whose entry does not say how confirm is obtained", "frontend/ecco-reserve-card/src/card.ts",
     f"hass.callService('script', '{SET_ID}', {{ value: 5, confirm: this._confirmed }});", {"frontend/ecco-reserve-card/src/card.ts": {}}),
    ("an allowed card whose entry says nothing useful", "frontend/ecco-reserve-card/src/card.ts",
     f"hass.callService('script', '{SET_ID}', {{ value: 5, confirm: this._confirmed }});", {"frontend/ecco-reserve-card/src/card.ts": {"confirm_from": "ok"}}),
]
POSITIVE = [
    # (name, path, text, allow): each must be clean
    ("the defining package itself (the script key, its own result text and notification id, and its comments)", DEFINING_REL, DEF_TEXT, {}),
    ("a package that reads the result text and the plan reserve", "home-assistant/packages/ecco_other.yaml",
     "template:\n  - sensor:\n      - name: x\n        state: \"{{ states('input_text.ecco_reserve_set_result') }} {{ states('sensor.ecco_reserve_floor_status') }}\"\n", {}),
    ("a YAML comment that names the script (a comment calls nothing)", "home-assistant/packages/ecco_other.yaml", f"# the panel will call script.{SET_ID} one day\nautomation: []\n", {}),
    ("an automation that turns on a different, literal script", "home-assistant/packages/ecco_other.yaml",
     "automation:\n  - id: a\n    trigger: []\n    action:\n      - action: script.turn_on\n        target:\n          entity_id: script.something_else\n", {}),
    ("a card that presses a button and sets a number", "frontend/ecco-x-card/src/card.ts",
     "this.hass.callService('button', 'press', { entity_id: e }); this.hass.callService('script', 'turn_on', { entity_id: s });", {}),
    ("a card that reads the result text and the read-back sensor", "frontend/ecco-x-card/src/card.ts", "const r = hass.states['input_text.ecco_reserve_set_result']; const f = 'sensor.ecco_reserve_floor_status';", {}),
    ("an allowed card whose entry says how confirm is obtained and which passes a variable", "frontend/ecco-reserve-card/src/card.ts",
     f"hass.callService('script', '{SET_ID}', {{ value: this._v, confirm: this._second_press }});", {"frontend/ecco-reserve-card/src/card.ts": DEC_ALLOW_OK}),
    ("an allowed dashboard button that passes confirm from a helper", DEC_DASH,
     f"views:\n  - cards:\n      - tap_action:\n          action: call-service\n          service: script.{SET_ID}\n          data: {{value: 3, confirm: \"{{{{ is_state('input_boolean.x', 'on') }}}}\"}}\n", {DEC_DASH: DEC_ALLOW_OK}),
    ("one of the three test files that name the script as their subject", "home-assistant/tests/_reserve_control_sim.py", f"self.pw.run_script('{SET_ID}', data)\n", {}),
]


def pin_problems(rules: dict, allow: dict) -> list:
    """The whole pin under `rules` and `allow`: the real tree is clean, the allow-list is empty, every negative control is caught and every positive control is clean."""
    out = tree_problems(REAL, rules, allow)
    if allow:
        out.append(f"the allow-list of callers is not empty ({sorted(allow)[:2]})")
    for name, rel, text, dec_allow in NEGATIVE:
        if not file_problems(rel, text, rules, dec_allow):
            out.append(f"negative control not caught: {name}")
    for name, rel, text, dec_allow in POSITIVE:
        got = file_problems(rel, text, rules, dec_allow)
        if got:
            out.append(f"positive control flagged: {name} ({got[0][:80]})")
    return out


_scanned = sorted(REAL)
check("the real tree was read: files from the packages, the dashboards, the prototypes, the tests and the card sources are all in scope",
      all(any(p.startswith(d) for p in _scanned) for d in ("home-assistant/packages/", "home-assistant/dashboards/", "home-assistant/prototypes/", "home-assistant/tests/", "frontend/")) and len(_scanned) >= 60,
      str(len(_scanned)))
_real = tree_problems(REAL, RULES, ALLOWED_CALLERS)
check("no file under home-assistant/ and no card source under frontend/*/src calls the reserve set script (action, service, script.turn_on, a bare script step, a template, callService, callWS)", _real == [], str(_real[:3]))
check("the allow-list of callers is EMPTY (the future panel card is added to it deliberately, with the text that says how its confirm comes from a person)", ALLOWED_CALLERS == {})
check("the defining package is the one place that names the script, as its own `script:` key, and nothing in it calls it",
      _parsed(DEF_TEXT, True) is not None and not any(RULES["token"].search(s) for s in _parsed(DEF_TEXT, True)[0]) and any(RULES["token"].search(s) for s in _parsed(DEF_TEXT, False)[0]))
_neg = [n for n, rel, text, al in NEGATIVE if not file_problems(rel, text, RULES, al)]
check(f"{len(NEGATIVE)} negative controls (an automation at 03:00 with confirm true, the script.turn_on and homeassistant.turn_on forms, a bare script step, a template, an allowed-looking dashboard button, "
      "a card source in callService, callWS and string forms, a minified confirm, an allow-list entry with no confirm text) are each caught", _neg == [], str(_neg[:3]))
_pos = [n for n, rel, text, al in POSITIVE if file_problems(rel, text, RULES, al)]
check(f"{len(POSITIVE)} positive controls (the defining package, the result text, a comment, another script, other card calls, an allowed card with a variable confirm) are each clean", _pos == [], str(_pos[:3]))
check("the whole pin is green on the repository", pin_problems(RULES, ALLOWED_CALLERS) == [], str(pin_problems(RULES, ALLOWED_CALLERS)[:2]))

CALLER_MUTANTS = [
    ("the script id is only recognised after a script. prefix", {"token": re.compile(r"script\.[a-z_]*reserve_set(?![A-Za-z0-9_])")}),
    ("the script id needs the ecco_ prefix in one piece", {"token": re.compile(r"ecco_reserve_set(?![A-Za-z0-9_])")}),
    ("the script id has no end boundary (its result text counts)", {"token": re.compile(r"reserve_set")}),
    ("the id built from pieces is not looked for", {"frag_on": False}),
    ("the piece pattern needs a quote only", {"frag": re.compile(r"""ecco_reserve_?['"]""")}),
    ("the card sources are not scanned", {"frontend": False}),
    ("the dashboards are not scanned", {"skip": ("home-assistant/dashboards/",)}),
    ("the prototypes are not scanned", {"skip": ("home-assistant/prototypes/",)}),
    ("the packages are not scanned", {"skip": ("home-assistant/packages/",)}),
    ("the tests are not scanned", {"tests": "skip"}),
    ("every test file is exempt", {"tests": "exempt_all"}),
    ("TypeScript is not scanned", {"suffixes": (".yaml", ".yml", ".json", ".js", ".mjs", ".cjs", ".tsx", ".jsx", ".html", ".py")}),
    ("JavaScript is not scanned", {"suffixes": (".yaml", ".yml", ".json", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".py")}),
    ("JSON is not scanned", {"suffixes": (".yaml", ".yml", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".py")}),
    ("YAML is not scanned", {"suffixes": (".json", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".py")}),
    ("Python generators are not scanned", {"suffixes": (".yaml", ".yml", ".json", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html")}),
    ("the whole defining package is exempt, not only its script key", {"defining": "file"}),
    ("a file that cannot be parsed is taken as clean", {"parse_errors": "ignore"}),
    ("YAML comments are read as calls", {"yaml_comments": "raw"}),
    ("JSON is read as plain text", {"json_as": "text"}),
    ("a templated action name is not looked for", {"dyn_yaml": False}),
    ("only the action key is looked at for a template", {"dyn_keys": ("action",)}),
    ("homeassistant.turn_on is not a generic call", {"generic": ("script.turn_on", "script.toggle", "script.turn_off", "homeassistant.toggle", "homeassistant.turn_off")}),
    ("script.turn_on is not a generic call", {"generic": ("script.toggle", "script.turn_off", "homeassistant.turn_on", "homeassistant.toggle", "homeassistant.turn_off")}),
    ("a script call with a computed service name is not looked for", {"dyn_ts_on": False}),
    ("the literal confirm check is removed", {"confirm_check": False}),
    ("the literal confirm check only knows the word true", {"confirm_re": re.compile(r"confirm\s*:\s*true\b")}),
    ("an allow-list entry needs no confirm text", {"confirm_from_required": False}),
    ("the allow-list is not empty (a card is allowed)", {"__allow__": {"frontend/ecco-reserve-card/src/card.ts": DEC_ALLOW_OK}}),
    ("the allow-list allows the dashboard (and no confirm text is asked)", {"__allow__": {DEC_DASH: {"confirm_from": "x"}}, "confirm_from_required": False}),
]
_cm_killed = 0
_cm_survived: list = []
for _label, _delta in CALLER_MUTANTS:
    _delta = dict(_delta)
    _allow = _delta.pop("__allow__", ALLOWED_CALLERS)
    _found = pin_problems({**RULES, **_delta}, _allow)
    if _found:
        _cm_killed += 1
        print(f"  PASS  caller-pin mutant caught: {_label} ({_found[0][:90]})")
    else:
        _cm_survived.append(_label)
        FAILURES.append(f"caller-pin mutant survived: {_label}")
        print(f"  FAIL  caller-pin mutant survived: {_label}")
check(f"{len(CALLER_MUTANTS)} mutants of the caller pin (a weaker id pattern, a missing directory or file type, an exempt file, a parse failure taken as clean, the template and generic-call rules, the literal confirm check, "
      "an allow-list that is not empty): all caught", _cm_killed == len(CALLER_MUTANTS) and len(CALLER_MUTANTS) >= 12, f"{_cm_killed}/{len(CALLER_MUTANTS)} {_cm_survived[:3]}")

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll reserve control checks passed.")
print("These prove the package against the repository's own models; nothing was installed, nothing was written live, and the script writes only the owner's reserve helper.")
