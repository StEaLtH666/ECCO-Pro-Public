#!/usr/bin/env python3
"""Consistency suite: the Ghost second-update runbook and its short GO checklist against the real tools and facts.

  docs/intelligence/GHOST_SECOND_UPDATE_RUNBOOK.md     the runbook (cited by the checklist as "runbook N")
  docs/intelligence/GHOST_SECOND_UPDATE_GO_CHECKLIST.md the short checklist (at most 120 lines)

A short document that a person decides on is only worth something while it says what the long one and the tools say. This suite
reads both documents as text (no Home Assistant, no network, no PowerShell, no git) and checks them against the sources they name:

  [1] shape: both exist, are ASCII, the checklist has at most 120 lines, the runbook has sections 1 to 12 and the checklist 1 to 8
  [2] tools and flags: every tool a command names exists in tools/, every flag it carries exists in that tool's source (the
      interpreter's own flags, written before the script, are not the tool's), every -Action value is in the deploy tool's
      ValidateSet, every drill sub-command exists, the Plan and Upgrade lines carry the flags the route requires and the Rollback line
      takes no kit
  [3] the kit: tools/build_ha_integration.py is run into temporary directories (outside the repository), with no commit and with the
      fixed reference commit; the two SHA256SUMS sha256 values, the file counts and the new and changed file names the documents state
      are those the build produces
  [4] numbers and names: the two table names, the retention bound, the rows a day (kinds x the slot cycles of the clock-change day),
      the incident list size, the two read budgets and the export epsilon are those of the sources, and EVERY mention in either
      document of a retention period, a rows-a-day figure and the incident list size equals the source constant
  [5] STORE_RECORD: the documents state the semantics (INFO, WARN while an incident is open, PASS only after a verified write, the
      incident kept) and quote texts the store really produces; the runtime document says the same; the download shows a passing
      check as the word PASS only (the self-test export), and the runbook says so and says what to look for instead
  [6] no automatic restart: no restart flag or command in any block, the deploy tool has no restart parameter, the restart is the
      owner's, approved separately, and says nothing in the documents restarts Home Assistant
  [7] every PowerShell block starts with cls
  [8] the owner's three quotes are in the runbook in full, their substance in the checklist
  [9] the plain sentences: no automatic installation or live access is authorised; never run in a real Home Assistant
 [10] forbidden: the three phrases the owner ruled out, an entity id, an address, a token, a workstation path, the live host alias, a
      commit id, a hash that is not one of the pinned ones, a non-ASCII character
 [11] preconditions: P1 (the L3 WSL kit-equivalence run on the exact kit) is OPEN and says what it must show (the executor reads in the
      download and the log lines in a real Home Assistant); the open set is the same in the runbook and the checklist
 [12] the steps: the same step numbers in both, the same who, an owner go at each live step, the restart with its own approval
 [13] the rollback: RB1 to RB6 in order in both, a proof for each in the runbook, the rollback command with its stamp, the heavy
      last resort that is never the first rollback in both, no bare R-number citation anywhere (the install runbook's items are
      named in full), and the case of a rollback before any restart (S6: ask the owner)
 [14] the owner's items D-U2-1 to D-U2-9 are open in both, never decided here; the two named questions carry the source's own facts
 [15] no entity: the platforms are sensor and binary sensor only, the integration has eleven contract entities, and the files directly
      under the kit's package are the known set (a new platform file would be a new entity)
 [16] what is NOT established: every bullet of the runbook's section 12 has a keyword, and the checklist's section 8 has each keyword
 [17] the drill: the statement of what it proves is in the runbook, the drill suite and tool say it, and the REAL drill is run here with
      the real kit on a mock root whose state folder holds a scorecard file with both new tables: the state folder is byte-identical
      after install, upgrade, rollback and uninstall
 [18] quoted tool phrases exist in the tools' sources
 [19] every block sets the variables it uses
 [20] every section the checklist cites exists in the runbook, and every install-runbook row or section the documents cite exists
 [21] every PowerShell block that calls a tool under tools/ sets its working folder first
 [22] the incident log lines: the first-failure line is a WARNING and the close line is logged at INFO (derived from the coordinator),
      so the close line may not show in the log read: the runbook and the checklist say so, say its absence is not a failure and
      say that P1 and the after-checks record the logger level
 [23] the write statement: the runbook and the checklist list the same writes (the integration folder, the staging and backup folders,
      the two tables, store_meta.json, the pause helper) and neither says the pause helper is the only write outside the scorecard file
 [24] when the tables are created: advice_log at the first advice-log attempt (even if it writes no row), advice_incident by the
      incident persist after a verified write; the code does so, and the documents say the same in every place that says it
 [25] mutants (all in memory): each is killed by the rule that exists for it

Usage: python custom_components/ecco_intelligence/tests/test_ghost_update_docs.py [--docs-root DIR]
--docs-root names another folder to read the two documents from (this is how the suite is shown to fail on missing or stub documents).
Test-only, no network. Reads repository files, builds into temporary directories and removes them.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(TESTS))
sys.path.append(str(REPO))

import _harness as H  # noqa: E402

FAILURES: list[str] = []
PASSED = [0]
PREFIX = "ecco_ghost_docs_"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED[0] += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


RB_REL = "docs/intelligence/GHOST_SECOND_UPDATE_RUNBOOK.md"
CL_REL = "docs/intelligence/GHOST_SECOND_UPDATE_GO_CHECKLIST.md"
INSTALL_REL = "docs/intelligence/INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md"
RUNTIME_DOC_REL = "docs/intelligence/INTELLIGENCE_HA_RUNTIME.md"
PKG = "custom_components/ecco_intelligence"
SOURCES = {
    "build": "tools/build_ha_integration.py", "drill": "tools/ecco_intel_drill.py", "deploy": "tools/deploy-ha-kit.ps1",
    "status": "tools/ha-status.ps1", "logs": "tools/ha-logs.ps1", "psm1": "tools/EccoDeploy.psm1",
    "scorecard": "intelligence/scorecard.py", "ghost_compare": "intelligence/ghost_compare.py", "ghost_feed": "intelligence/ghost_feed.py",
    "store": PKG + "/runtime/store.py", "ghost_link": PKG + "/runtime/ghost_link.py", "coordinator": PKG + "/coordinator.py",
    "const": PKG + "/const.py", "drill_suite": PKG + "/tests/test_install_drill.py",
    "runtime_doc": RUNTIME_DOC_REL, "install": INSTALL_REL, "selftest": PKG + "/runtime/selftest.py",
}
TOOL_KEYS = {"build_ha_integration.py": "build", "ecco_intel_drill.py": "drill", "deploy-ha-kit.ps1": "deploy",
             "ha-status.ps1": "status", "ha-logs.ps1": "logs"}
FIXED_SHA = "0000000"                 # the fixed reference commit of the second build (not a commit: a placeholder)
BASE_KIT_SUMS = "47391f0d67144739774034e471486814dae2fd47229a130aae8109968a70ee40"   # recorded from the merged base's kit; not pinned
OPEN_AT_WRITING = ("P1", "P3", "P4", "P5", "P6", "P7", "P9")
NEW_FILES = ("_vendor/intelligence/ghost.py", "_vendor/intelligence/ghost_compare.py", "_vendor/intelligence/ghost_feed.py",
             "_vendor/intelligence/net_value.py", "runtime/ghost_link.py")
CHANGED_FILES = ("_vendor/intelligence/scorecard.py", "runtime/store.py", "coordinator.py", "diagnostics.py", "VENDOR_MANIFEST.json")
PKG_ROOT_PY = {"__init__", "binary_sensor", "config_flow", "const", "coordinator", "diagnostics", "entity_base", "sensor"}   # file stems
GO_STEPS = (1, 3, 4, 5, 6, 7, 8, 9, 10)
STEP_NUMBERS = tuple(range(12))
FENCE = "`" * 3
MAX_CHECKLIST_LINES = 120
FORBIDDEN_WORDS = ("fully enforced", "guaranteed", "safe to install")
OWNER_QUOTES = (
    "Keep Ghost as the second update, with its own restart and rollback requirements.",
    "Ghost remains a separate second update with its own backup, restart and rollback verification.",
    "For a failed advice write, retain an incident record and show the failure honestly. After a subsequent verified successful "
    "write, allow current health to recover while retaining the earlier incident for diagnosis.",
)
CHECKLIST_SUBSTANCE = ("second update", "own backup, restart and rollback verification", "incident record and shows the failure honestly",
                       "later verified write")
COVERAGE = (   # one keyword per bullet of the runbook's section 12 (and the same keyword in the checklist's section 8)
    "never run in a real home assistant", "l3 (wsl)", "write latency", "durability proof", "lost", "log lines", "executor reads",
    "rows per day", "rollback with the tables", "simulation", "listing commands", "d-u2-7", "recalled",
)
STORE_TEXTS = ("advice log not verified (", "PASS needs a verified write", "the scorecard step completed",
               "the advice log write is verified", "no advice row was written yet")
TOOL_PHRASES = (   # (the phrase the runbook quotes, [(source key, fragment that proves the tool prints it)])
    ("ECCO INTELLIGENCE KIT UPGRADE PASSED", [("deploy", "ECCO INTELLIGENCE KIT"), ("deploy", "PASSED"), ("deploy", "ToUpperInvariant")]),
    ("RESTART REQUIRED - separately gated, not performed", [("deploy", "RESTART REQUIRED - separately gated, not performed")]),
    ("HA check : passed", [("deploy", "HA check : passed")]),
    ("NO CHANGE", [("deploy", "NO CHANGE")]),
    ("ROLLBACK NOT CONFIRMED", [("psm1", "ROLLBACK NOT CONFIRMED")]),
    ("was rolled back", [("psm1", "was rolled back")]),
)
AUTOMATIC_VARS = {"_", "null", "true", "false", "erroractionpreference", "outputencoding", "lastexitcode", "matches", "args"}
HA_DOMAINS = "sensor|binary_sensor|input_boolean|input_number|input_text|input_select|switch|number|select|button|light|automation|script|climate|cover|fan|lock"
ENTITY_RE = re.compile(r"\b(?:" + HA_DOMAINS + r")\.[a-z0-9_]{2,}\b")
IPV4_RE = re.compile(r"(?<![0-9.])\d{1,3}(?:\.\d{1,3}){3}(?!\d)(?!\.\d)")
TOKEN_RE = re.compile(r"ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{20,}|" + "-" * 5 + r"BEGIN|Bearer\s+[A-Za-z0-9._-]{20,}")
PATH_RE = re.compile(r"\b[A-Za-z]:\\|/[cC]/" + "Users/|(?<![A-Za-z])/" + "Users/|" + r"\\" + "Users" + r"\\")
COMMIT_RE = re.compile(r"(?<![0-9A-Za-z_])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
HEX64_RE = re.compile(r"(?<![0-9A-Za-z_])[0-9a-f]{64}(?![0-9A-Za-z_])")
TOOL_CALL_RE = re.compile(r"(?<![\w-])tools\\[A-Za-z0-9_.-]+\.(?:py|ps1|psm1)")       # a tool called by its relative path
BARE_R_RE = re.compile(r"(?<![A-Za-z0-9_-])R[1-8](?![A-Za-z0-9_])")                  # R1 to R8: never this runbook's items (RB1 to RB6)
MENTIONS = (   # (what, the patterns that capture one mention each in plain text, the key of the source's own constant)
    ("a retention period", (r"(?<![\d.])(\d+)[- ]days?\b",), "retention"),
    ("a rows-a-day figure", (r"\b(\d+) rows a day", r"\bat most (\d+) a day\b"), "rows_max"),
    ("the rows of a normal day", (r"\((\d+) on a normal day\)",), "rows_normal"),
    ("the incident list size", (r"\bnewest (\d+)\b", r"\bat most (\d+) incidents\b", r"advice_incident \(at most (\d+) rows\)"), "kept"),
)

DOCS_ROOT = REPO
if "--docs-root" in sys.argv:
    DOCS_ROOT = Path(sys.argv[sys.argv.index("--docs-root") + 1])


# ---------------------------------------------------------------------------------------------------------------------
# reading and parsing
# ---------------------------------------------------------------------------------------------------------------------
def read_doc(rel: str) -> str | None:
    p = DOCS_ROOT / rel
    return p.read_bytes().decode("utf-8", errors="replace") if p.is_file() else None


def read_src(rel: str) -> str:
    return (REPO / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def P(text: str) -> str:
    """Plain text: block-quote marks, emphasis and code ticks removed, whitespace folded."""
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    return " ".join(text.replace("*", "").replace("`", "").split())


def has(text: str, phrase: str) -> bool:
    return P(phrase).lower() in P(text).lower()


def has_cs(text: str, phrase: str) -> bool:
    """The same, case-sensitive (a phrase a tool prints is quoted exactly)."""
    return P(phrase) in P(text)


def ps_blocks(text: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"^( *)" + FENCE + r"powershell\n(.*?)^\1" + FENCE, text, re.S | re.M)]


def outside_blocks(text: str) -> str:
    return re.sub(r"^( *)" + FENCE + r"[a-z]*\n.*?^\1" + FENCE, "", text, flags=re.S | re.M)


def logical_lines(block: str) -> list[str]:
    return re.sub(r"`[ \t]*\n[ \t]*", " ", block).split("\n")


def headings(text: str) -> list[tuple[str, str]]:
    return re.findall(r"^(#{2,3}) (\d+(?:\.\d+)?)\.? ", text, re.M)


def section(text: str, num: str) -> str:
    m = re.search(r"^(#{2,3}) " + re.escape(num) + r"\.? .*$", text, re.M)
    if not m:
        return ""
    level = len(m.group(1))
    rest = text[m.end():]
    n = re.search(r"^#{2," + str(level) + r"} \S", rest, re.M)
    return rest[: n.start()] if n else rest


def table_rows(text: str) -> list[list[str]]:
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if s.startswith("|") and not re.fullmatch(r"\|[-| :]+\|", s):
            out.append([c.strip() for c in s.strip("|").split("|")])
    return out


def py_flags(src: str) -> set[str]:
    return set(re.findall(r'add_argument\(\s*"(--[a-z][a-z-]*)"', src))


def ps_params(src: str) -> set[str]:
    """The parameter names of the script's own param( ... ) block (a [bool] cast in the code below it is not a parameter)."""
    m = re.search(r"\bparam\((.*?)\n\)", src, re.S)
    return {n.lower() for n in re.findall(r"\[(?:string|switch|int|bool)\]\s*\$(\w+)", m.group(1))} if m else set()


def validate_set(src: str, name: str) -> list[str]:
    m = re.search(r"\[ValidateSet\(([^)]*)\)\]\s*\[string\]\$" + name + r"\b", src)
    return re.findall(r"'([^']+)'", m.group(1)) if m else []


def drill_subcommands(src: str) -> set[str]:
    out = set(re.findall(r'add_parser\("([a-z-]+)"\)', src))
    m = re.search(r"for name in \(([^)]*)\):", src)
    if m:
        out |= set(re.findall(r'"([a-z-]+)"', m.group(1)))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# the rules: each returns a list of problems
# ---------------------------------------------------------------------------------------------------------------------
def rule_shape(rb, cl, S, F):
    pr = []
    for label, doc in (("runbook", rb), ("checklist", cl)):
        if not doc.strip():
            pr.append(f"the {label} is empty")
        if not doc.isascii():
            pr.append(f"the {label} is not ASCII")
    if len(cl.splitlines()) > MAX_CHECKLIST_LINES:
        pr.append(f"the checklist has {len(cl.splitlines())} lines, at most {MAX_CHECKLIST_LINES}")
    rb_nums = [n for h, n in headings(rb) if h == "##"]
    if rb_nums != [str(i) for i in range(1, 13)]:
        pr.append(f"the runbook's sections are {rb_nums}, not 1 to 12")
    cl_nums = [n for h, n in headings(cl) if h == "##"]
    if cl_nums != [str(i) for i in range(1, 9)]:
        pr.append(f"the checklist's sections are {cl_nums}, not 1 to 8")
    return pr


def commands_of(doc: str) -> list[str]:
    """Every command string of a document: the logical lines of its PowerShell blocks and its inline code spans."""
    out = []
    for b in ps_blocks(doc):
        out += logical_lines(b)
    out += re.findall(r"`([^`\n]+)`", outside_blocks(doc))
    return out


def rule_tools(rb, cl, S, F):
    pr = []
    flags = {"build": py_flags(S["build"]), "drill": py_flags(S["drill"])}
    subs = drill_subcommands(S["drill"])
    params = {k: ps_params(S[k]) for k in ("deploy", "status", "logs")}
    actions = validate_set(S["deploy"], "Action")
    targets = validate_set(S["deploy"], "Target")
    if not (flags["build"] and flags["drill"] and subs and all(params.values()) and actions and targets):
        pr.append("the tool sources could not be parsed (no flags, parameters or ValidateSet found)")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for ref in sorted(set(re.findall(r"tools[\\/]([A-Za-z0-9_.-]+\.(?:py|ps1|psm1))", doc))):
            if not (REPO / "tools" / ref).is_file():
                pr.append(f"{label}: tools/{ref} does not exist")
        for val in re.findall(r"-Action\s+([A-Za-z]+)", doc):
            if val not in actions:
                pr.append(f"{label}: -Action {val} is not in the deploy tool's ValidateSet {actions}")
        for val in re.findall(r"-Target\s+([A-Za-z]+)", doc):
            if val not in targets:
                pr.append(f"{label}: -Target {val} is not in the deploy tool's ValidateSet {targets}")
        for cmd in commands_of(doc):
            for m in re.finditer(r"([A-Za-z0-9_-]+\.(?:py|ps1))", cmd):
                key = TOOL_KEYS.get(m.group(1))
                if key is None:
                    continue
                toks = [t.strip(",;)(][") for t in cmd[m.end():].split(" | ")[0].split() if not t.startswith("<")]
                if key in ("build", "drill"):
                    for t in toks:
                        if t.startswith("--") and t not in flags[key]:
                            pr.append(f"{label}: {m.group(1)} has no flag {t}")
                    if key == "drill":
                        first = next((t for t in toks if not t.startswith("-")), None)
                        if first is not None and first not in subs:
                            pr.append(f"{label}: {m.group(1)} has no sub-command {first}")
                else:
                    for t in toks:
                        if re.fullmatch(r"-[A-Za-z]+", t) and t[1:].lower() not in params[key]:
                            pr.append(f"{label}: {m.group(1)} has no parameter {t}")
    for b in ps_blocks(rb):
        for ln in logical_lines(b):
            m = re.search(r"deploy-ha-kit\.ps1\s+-Action\s+(\w+)", ln)
            if not m:
                continue
            act = m.group(1)
            if act in ("Plan", "Upgrade"):
                need = ("-SshHost", "-Target Production", "-ExpectedHaVersion", "-Kit", "-ExpectedSumsSha256", "-ReferenceKit",
                        "-ReferenceSumsSha256")
                miss = [n for n in need if n not in ln]
                if miss:
                    pr.append(f"runbook: the {act} line lacks {miss}")
            elif act == "Rollback":
                if "-BackupStamp" not in ln:
                    pr.append("runbook: the Rollback line lacks -BackupStamp")
                if re.search(r"-(Kit|ExpectedSumsSha256|ReferenceKit|ReferenceSumsSha256)\b", ln):
                    pr.append("runbook: the Rollback line names a kit (the tool refuses one)")
    for b in ps_blocks(rb):
        for ln in logical_lines(b):
            if "build_ha_integration.py" in ln and "--out" in ln:
                m = re.search(r"--git-sha\s+(\S+)", ln)
                if m and m.group(1) not in (FIXED_SHA, "(git"):
                    pr.append(f"runbook: --git-sha {m.group(1)} is neither the fixed reference nor the install commit")
            if "ecco_intel_drill.py" in ln and "drill" in ln.split() and ("--config-root" not in ln or "--kit" not in ln):
                pr.append("runbook: the drill line lacks --config-root or --kit")
    return pr


def rule_kit(rb, cl, S, F):
    pr = []
    k = F["kit"]
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for key in ("nosha", "fixed"):
            if k[key] not in doc:
                pr.append(f"{label} lacks the {key} SHA256SUMS sha256 {k[key][:8]}")
    m = re.search(r"with (\d+) vendored modules and (\d+) integration files; (\d+) files", k["line"])
    if not m:
        return pr + ["the build line could not be read"]
    for needle in (f"{m.group(1)} vendored modules", f"{m.group(2)} integration files", f"{m.group(3)} files",
                   f"{len(k['pkg'])} files", k["line"].split(";")[0]):
        if not has(rb, needle):
            pr.append(f"runbook lacks '{needle}'")
    if not has(cl, f"{m.group(3)} files"):
        pr.append("checklist lacks the file count")
    for rel in NEW_FILES + CHANGED_FILES:
        if PKG + "/" + rel not in k["all"]:
            pr.append(f"{rel} is not in the kit")
        if rel.rsplit("/", 1)[-1] not in rb:
            pr.append(f"runbook does not name {rel}")
    if k["nosha"] == k["fixed"]:
        pr.append("the two reference builds are identical (the commit is not recorded)")
    return pr


def mentions(text: str, patterns) -> list[int]:
    """Every number the patterns capture in a document's plain text (one capture group each; a thousands space is allowed)."""
    return [int(m.group(1).replace(" ", "")) for rx in patterns for m in re.finditer(rx, text, re.I)]


def rule_numbers(rb, cl, S, F):
    pr = []
    f = F["facts"]
    for label, doc in (("runbook", rb), ("checklist", cl)):
        if not has(doc, f"{f['retention']} days"):
            pr.append(f"{label} lacks the retention bound of {f['retention']} days")
        if not has(doc, f"{f['rows_max']} rows a day"):
            pr.append(f"{label} lacks '{f['rows_max']} rows a day'")
        for t in f["tables"]:
            if f"`{t}`" not in doc:
                pr.append(f"{label} lacks the table name `{t}`")
        if not has(doc, f"{f['eps']} kWh"):
            pr.append(f"{label} lacks the export epsilon {f['eps']} kWh")
        text = P(doc)       # EVERY mention equals the source's constant (not only one of them)
        for what, patterns, key in MENTIONS:
            wrong = sorted({n for n in mentions(text, patterns) if n != f[key]})
            if wrong:
                pr.append(f"{label}: {what} {wrong} is not the source's {f[key]}")
        want = f["retention"] * f["rows_max"]
        for n in mentions(text, (r"\babout (\d+(?: \d{3})+) rows",)):
            if abs(n - want) > 0.05 * want:
                pr.append(f"{label}: the table size estimate {n} is not near {want} (the retention x the rows a day)")
    if sorted(f["tables"]) != ["advice_incident", "advice_log"]:
        pr.append(f"the sources create the tables {f['tables']}")
    if not has(rb, f"newest {f['kept']}") or not has(cl, f"at most {f['kept']} incidents"):
        pr.append(f"the incident list size {f['kept']} is not stated")
    if not has(rb, f"{f['slots']} slot cycles a day") or not has(rb, f"{f['slots'] + 1} on the day the clocks go back"):
        pr.append(f"the runbook lacks the {f['slots']} and {f['slots'] + 1} slot cycles a day")
    if not has(rb, f"at most {f['stored_budget']:g} s") or not has(rb, f"at most {f['ghost_budget']:g} s"):
        pr.append(f"the read budgets {f['stored_budget']:g} s and {f['ghost_budget']:g} s are not stated")
    return pr


def rule_store_record(rb, cl, S, F):
    pr = []
    for phrase in ("WARN while an advice write incident is open", "PASS only after a verified write",
                   "INFO (never PASS) while a run has written and verified nothing yet", "After a restart nothing is assumed",
                   "later verified write", "not a durability or fsync proof", "same-connection"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    for phrase in ("WARN while an incident is open", "PASS again only after a later verified write", "INFO then PASS"):
        if not has(cl, phrase):
            pr.append(f"checklist lacks '{phrase}'")
    for text in STORE_TEXTS:
        if text not in S["store"]:
            pr.append(f"the store does not produce '{text}'")
        if text.startswith("advice log not verified") or text in ("PASS needs a verified write", "the advice log write is verified"):
            if not has(rb, text):
                pr.append(f"runbook does not quote '{text}'")
    for phrase in ("returns to PASS only after a verified write", "not a durability or fsync proof"):
        if not has(S["runtime_doc"], phrase):
            pr.append(f"the runtime document lacks '{phrase}'")
    # the download shows a passing check as the word PASS only: the self-test export returns a text for INFO, WARN and FAIL
    if "c.level if c.level == PASS else" not in S["selftest"]:
        pr.append("the self-test export no longer returns only the level for a passing check (the runbook says the download shows PASS only)")
    for phrase in ("shows a passing check as the single word PASS, without any text", "is not exported anywhere in the download",
                   "STORE_RECORD: PASS", "advice_incidents.verified_writes", "last_store.advice_verified"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    for old in ('PASS with "the advice log write is verified"', "(its text:"):
        if has(rb, old):
            pr.append(f"runbook still says the PASS text is visible in the download ('{old}')")
    return pr


def rule_no_restart(rb, cl, S, F):
    pr = []
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for b in ps_blocks(doc):
            if re.search(r"(?<!\w)-Restart\b", b) or re.search(r"core restart|reboot|shutdown|\bRestart-[A-Za-z]", b, re.I):
                pr.append(f"{label}: a block restarts or reboots")
        for span in re.findall(r"`([^`\n]+)`", outside_blocks(doc)):
            if re.search(r"(?<!\w)-Restart\b", span) or re.search(r"core restart|reboot|\bRestart-[A-Za-z]", span, re.I):
                pr.append(f"{label}: an inline command restarts")
    if "restart" in ps_params(S["deploy"]):
        pr.append("the deploy tool has a restart parameter")
    code = re.sub(r"<#.*?#>", "", S["deploy"], flags=re.S)
    code = "\n".join(ln for ln in code.split("\n") if not ln.strip().startswith("#"))
    if re.search(r"core restart|host reboot|Restart-Computer|Restart-Service", code, re.I):
        pr.append("the deploy tool sends a restart command")
    for phrase in ("only with the owner's explicit approval, separate from the Upgrade", "no tool in this runbook performs it",
                   "RESTART REQUIRED - separately gated, not performed"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    for phrase in ("nothing in this list restarts Home Assistant", "own approval"):
        if not has(cl, phrase):
            pr.append(f"checklist lacks '{phrase}'")
    return pr


def rule_cls(rb, cl, S, F):
    pr = []
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for i, b in enumerate(ps_blocks(doc), 1):
            if b.strip().split("\n", 1)[0].strip() != "cls":
                pr.append(f"{label}: block {i} does not start with cls")
    if not ps_blocks(rb):
        pr.append("the runbook has no PowerShell block")
    return pr


def rule_quotes(rb, cl, S, F):
    pr = [f"runbook lacks the owner's words '{q[:40]}...'" for q in OWNER_QUOTES if not has(rb, q)]
    pr += [f"checklist lacks '{s}'" for s in CHECKLIST_SUBSTANCE if not has(cl, s)]
    return pr


def rule_sentences(rb, cl, S, F):
    pr = []
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for phrase in ("no automatic installation or live access is authorised", "never run in a real Home Assistant"):
            if not has(doc, phrase):
                pr.append(f"{label} lacks '{phrase}'")
    return pr


def rule_forbidden(rb, cl, S, F):
    pr = []
    k = F["kit"]
    allowed = {k["nosha"], k["fixed"], BASE_KIT_SUMS}
    for label, doc in (("runbook", rb), ("checklist", cl)):
        low = doc.lower()
        for w in FORBIDDEN_WORDS:
            if w in low:
                pr.append(f"{label}: the forbidden phrase '{w}'")
        for name, rx in (("an entity id", ENTITY_RE), ("an address", IPV4_RE), ("a token", TOKEN_RE), ("a workstation path", PATH_RE),
                         ("a commit id", COMMIT_RE)):
            hit = rx.search(doc)
            if hit:
                pr.append(f"{label}: {name} ({hit.group(0)[:20]})")
        if "ecco-ha" in low:
            pr.append(f"{label}: the live host alias")
        extra = [h for h in HEX64_RE.findall(doc) if h not in allowed]
        if extra:
            pr.append(f"{label}: an unexplained 64-hex blob {extra[0][:12]}")
        if not doc.isascii():
            pr.append(f"{label}: a non-ASCII character")
    return pr


def open_ids(rb: str) -> set[str]:
    out = set()
    for cells in table_rows(section(rb, "5")):
        if re.fullmatch(r"P\d+", cells[0]) and "OPEN" in cells[-1]:
            out.add(cells[0])
    return out


def rule_preconditions(rb, cl, S, F):
    pr = []
    sec = section(rb, "5")
    ids = [c[0] for c in table_rows(sec) if re.fullmatch(r"P\d+", c[0])]
    if ids != [f"P{i}" for i in range(1, 10)]:
        pr.append(f"the runbook's preconditions are {ids}")
    p1 = next((c for c in table_rows(sec) if c[0] == "P1"), None)
    if p1 is None or "OPEN" not in p1[-1]:
        pr.append("P1 (the L3 run) is not OPEN in the runbook")
    elif not all(has(p1[1], x) for x in ("WSL", "kit-equivalence", "repeated on the exact kit", "executor reads in the diagnostics download",
                                         "log lines observed in the real Home Assistant", "-ReferenceSumsSha256", "never on production")):
        pr.append("P1 does not say what the run must show")
    got = open_ids(rb)
    if got != set(OPEN_AT_WRITING):
        pr.append(f"the open preconditions are {sorted(got)}, expected {list(OPEN_AT_WRITING)} (closing one is a deliberate edit of this suite)")
    listed = "P1, P3, P4, P5, P6, P7 and P9"
    if not has(rb, "NOT READY") or not has(rb, listed):
        pr.append("the runbook's status does not say NOT READY and list the open preconditions")
    c1 = section(cl, "1")
    if not has(c1, "NOT yet ready") or not has(c1, "P1, P3, P4, P5, P6, P7 and P9"):
        pr.append("the checklist does not say NOT yet ready and list the open preconditions")
    for phrase in ("L3 (WSL) kit-equivalence reference run", "executor reads in the diagnostics download", "log lines", "exact kit"):
        if not has(c1, phrase):
            pr.append(f"the checklist's answer lacks '{phrase}'")
    for needle in ("independent review", "CI", "M2", "U1"):
        if not has(sec, needle):
            pr.append(f"the preconditions do not name {needle}")
    return pr


def rule_steps(rb, cl, S, F):
    pr = []
    rr = {int(c[0]): c for c in table_rows(section(rb, "7")) if re.fullmatch(r"\d+", c[0])}
    cr = {int(c[0]): c for c in table_rows(section(cl, "4")) if re.fullmatch(r"\d+", c[0])}
    if tuple(sorted(rr)) != STEP_NUMBERS:
        pr.append(f"the runbook's steps are {sorted(rr)}")
    if tuple(sorted(cr)) != STEP_NUMBERS:
        pr.append(f"the checklist's steps are {sorted(cr)}")
    for n, cells in rr.items():
        if len(cells) != 8:
            pr.append(f"runbook step {n} has {len(cells)} cells, not 8")
    for n in STEP_NUMBERS:
        if n not in rr or n not in cr:
            continue
        who_rb = rr[n][2].upper()
        who_cl = cr[n][1].lower()
        for rbw, clw in (("COORDINATOR", "coordinator"), ("OWNER", "you")):
            if (rbw in who_rb) != (clw in who_cl):
                pr.append(f"step {n}: who differs ({rr[n][2]} / {cr[n][1]})")
        if n in GO_STEPS:
            if "yes" not in rr[n][5].lower():
                pr.append(f"runbook step {n} has no own authorisation")
            if not any("**go**" in c or "own approval" in c for c in cr[n]):
                pr.append(f"checklist step {n} has no go")
    if 7 in rr and not (has(rr[7][5], "own approval") and has(rr[7][5], "separate from the Upgrade") and has(rr[7][1], "the restart")):
        pr.append("runbook step 7 is not the restart with its own separate approval")
    if 7 in cr and not (any("own approval" in c for c in cr[7]) and has(" ".join(cr[7]), "the restart")):
        pr.append("checklist step 7 is not the restart with its own approval")
    if 3 in rr and not has(rr[3][1], "pause helper"):
        pr.append("runbook step 3 is not the pause")
    if 1 in rr and not all(has(rr[1][1], x) for x in ("listing", "hashes and sizes", "diagnostics download")):
        pr.append("runbook step 1 lacks the listing, hashes and sizes or the download")
    if 4 in rr and not has(rr[4][1], "hash and size"):
        pr.append("runbook step 4 lacks the scorecard file's hash and size")
    if 5 in rr and not (has(rr[5][1], "-Action Plan") and has(rr[5][1], "-Action Upgrade")):
        pr.append("runbook step 5 does not name Plan and Upgrade")
    if 5 in cr and not (has(" ".join(cr[5]), "-Action Plan") and has(" ".join(cr[5]), "-Action Upgrade")):
        pr.append("checklist step 5 does not name Plan and Upgrade")
    if 2 in rr and not has(rr[2][1], "protected full backup"):
        pr.append("runbook step 2 is not the protected backup")
    return pr


def rule_rollback(rb, cl, S, F):
    pr = []
    s10 = section(rb, "10")
    items = re.findall(r"^\d+\. \*\*(RB\d)\b(.*?)(?=^\d+\. \*\*RB|\*\*Special cases|\Z)", s10, re.S | re.M)
    if [i[0] for i in items] != [f"RB{n}" for n in range(1, 7)]:
        pr.append(f"the runbook's rollback items are {[i[0] for i in items]}")
    for name, body in items:
        if "Proof" not in body:
            pr.append(f"runbook {name} has no proof")
    order = re.findall(r"\*\*(RB\d)\b", section(cl, "6"))
    if order != [f"RB{n}" for n in range(1, 7)]:
        pr.append(f"the checklist's rollback order is {order}")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        if not has(doc, "-Action Rollback -BackupStamp"):
            pr.append(f"{label} lacks the rollback command with its stamp")
    if not has(s10, "against the baseline") or not has(s10, "the owner's protected full backup"):
        pr.append("the runbook's rollback is not measured against the baseline and the protected backup")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        bare = sorted(set(BARE_R_RE.findall(P(doc))))
        if bare:
            pr.append(f"{label}: bare R-number citation(s) {bare}: this runbook's items are RB1 to RB6 and an install-runbook item is named in full")
        for phrase in ("heavy last resort", "never the first rollback"):       # RB6 is the last resort, whatever the wording elsewhere
            if not has(doc, phrase):
                pr.append(f"{label} lacks '{phrase}' (the protected backup restore)")
    if not has(s10, "install runbook's section 7 go / no-go for the first observed runs"):
        pr.append("RB4 does not name the install runbook's first-run go / no-go in full")
    # a rollback before any restart: the case is written down, with the owner asked and the reason why
    if "*S6," not in s10:
        pr.append("the runbook's special cases have no S6 (a rollback before the restart of step 7)")
    for phrase in ("before the restart of step 7", "the old code is still running", "RB3 applies", "ask the owner", "recalled, not verified",
                   "whether RB3 is then needed is S6's question"):
        if not has(s10, phrase):
            pr.append(f"the runbook's section 10 lacks '{phrase}' (the rollback before any restart)")
    if not (has(section(cl, "6"), "before the restart of step 7") and re.search(r"\bS6\b", section(cl, "6"))):
        pr.append("the checklist's rollback does not say that a rollback before the restart of step 7 leaves RB3 to the owner (S6)")
    return pr


def rule_decisions(rb, cl, S, F):
    pr = []
    f = F["facts"]
    for label, sec in (("runbook", section(rb, "4")), ("checklist", section(cl, "3"))):
        rows = {c[0]: c for c in table_rows(sec) if re.fullmatch(r"D-U2-\d", c[0])}
        if sorted(rows) != [f"D-U2-{i}" for i in range(1, 10)]:
            pr.append(f"{label}: the items are {sorted(rows)}")
        for k, cells in rows.items():
            if not P(cells[-1]).lower().startswith("open"):
                pr.append(f"{label}: {k} is not open")
        r7, r8 = rows.get("D-U2-7"), rows.get("D-U2-8")
        if r7 is not None and not all(x in " ".join(r7) for x in ("advice.followed", "advice_in_force_hours")):
            pr.append(f"{label}: D-U2-7 lacks advice.followed or advice_in_force_hours")
        if r8 is not None and not (any("EXPORT_DIFF_EPS_KWH" in c for c in r8) and f"{f['eps']} kWh" in " ".join(r8)):
            pr.append(f"{label}: D-U2-8 lacks EXPORT_DIFF_EPS_KWH or its value {f['eps']}")
    if not has(rb, "it decides none") or not has(cl, "I decide none"):
        pr.append("the documents do not say they decide none of the items")
    if "advice_in_force_hours" not in F["ghost_feed_src"]:
        pr.append("advice_in_force_hours is not in the feed source")
    if "EXPORT_DIFF_EPS_KWH" not in S["ghost_compare"]:
        pr.append("EXPORT_DIFF_EPS_KWH is not in the comparison source")
    return pr


def rule_no_entity(rb, cl, S, F):
    pr = []
    f = F["facts"]
    if f["platforms"] != ("sensor", "binary_sensor"):
        pr.append(f"the platforms are {f['platforms']}")
    if f["entities"] != 11:
        pr.append(f"the integration has {f['entities']} contract entities")
    if F["kit"]["root_py"] != PKG_ROOT_PY:
        pr.append(f"the files directly under the package are {sorted(F['kit']['root_py'])}")
    for phrase in ("this update creates no entity", "eleven entities", "RG-F3"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    if not has(cl, "No entity, helper or service is created") or not has(cl, "RG-F3"):
        pr.append("checklist lacks the no-entity statement or RG-F3")
    return pr


def rule_coverage(rb, cl, S, F):
    pr = []
    s12 = section(rb, "12")
    bullets = [b for b in re.split(r"^- ", s12, flags=re.M)[1:]]
    for b in bullets:
        if not any(k in P(b).lower() for k in COVERAGE):
            pr.append(f"a bullet of runbook 12 has no keyword: {P(b)[:50]}")
    c8 = P(section(cl, "8")).lower()
    r12 = P(s12).lower()
    for k in COVERAGE:
        if k not in c8:
            pr.append(f"the checklist's section 8 lacks '{k}'")
        if k not in r12:
            pr.append(f"the runbook's section 12 lacks '{k}'")
    if len(bullets) < len(COVERAGE) - 2:
        pr.append(f"the runbook's section 12 has only {len(bullets)} bullets")
    return pr


def rule_drill(rb, cl, S, F):
    pr = []
    for phrase in ("What the drill proves, exactly", "byte-identical", "The suite of this runbook repeats that with a scorecard file that really holds both tables",
                   "does not run the previous kit"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    if not has(cl, "the drill proves the state folder is untouched"):
        pr.append("checklist lacks the drill statement")
    if "site.local.json, state/ and the other integration untouched by every step" not in S["drill_suite"]:
        pr.append("the drill suite no longer has the check the runbook relies on")
    if '"ecco/intelligence/state"' not in S["drill"]:
        pr.append("the drill tool no longer protects the state folder")
    d = F["drill"]
    if not d.get("ok"):
        pr.append(f"the real drill on a state folder with both tables failed: {d.get('detail')}")
    if not has(rb, "synthetic data, not a repository suite"):
        pr.append("runbook does not label the previous-code experiment as scratch, synthetic and not a suite")
    return pr


def rule_phrases(rb, cl, S, F):
    pr = []
    for phrase, proofs in TOOL_PHRASES:
        if not has_cs(rb, phrase):
            pr.append(f"runbook does not quote '{phrase}'")
        for key, frag in proofs:
            if not has_cs(S[key], frag):
                pr.append(f"{key} does not print '{frag}'")
    if not has_cs(cl, "ECCO INTELLIGENCE KIT UPGRADE PASSED"):
        pr.append("checklist does not quote the Upgrade's PASSED line")
    if "INSTALLED TREE EQUALS THE KIT" not in "\n".join(ps_blocks(rb)):
        pr.append("no runbook block prints INSTALLED TREE EQUALS THE KIT")
    if not has(rb, F["kit"]["line"].split(";")[0]):
        pr.append("runbook does not quote the build tool's line")
    for frag in ("built ", "SHA256SUMS sha256"):
        if frag not in S["build"]:
            pr.append(f"the build tool does not print '{frag}'")
    return pr


def rule_vars(rb, cl, S, F):
    pr = []
    for i, b in enumerate(ps_blocks(rb), 1):
        body = re.sub(r"'[^']*'", "''", b)
        used = {v.lower() for v in re.findall(r"\$(\w+)", body)} - AUTOMATIC_VARS
        assigned = {v.lower() for v in re.findall(r"\$(\w+)(?:\[[^\]]*\])*\s*(?:\+=|=)(?!=)", body)}
        assigned |= {v.lower() for v in re.findall(r"foreach\s*\(\s*\$(\w+)\s+in", body)}
        missing = sorted(used - assigned)
        if missing:
            pr.append(f"runbook block {i} uses {missing} without setting it")
    return pr


def rule_cites(rb, cl, S, F):
    pr = []
    heads = {n for _h, n in headings(rb)}
    for num in re.findall(r"(?<!install )\brunbook (\d+(?:\.\d+)?)", cl):
        if num not in heads:
            pr.append(f"the checklist cites runbook {num}, which has no such heading")
    install = S["install"]
    install_heads = {n for _h, n in headings(install)}
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for tok in re.findall(r"install runbook(?:'s)? (?:section )?([GRTQ]\d+|\d+)", P(doc)):
            if re.fullmatch(r"\d+", tok):
                ok = tok in install_heads
            else:
                ok = re.search(r"^\| " + tok + r" \|", install, re.M) is not None
            if not ok:
                pr.append(f"{label} cites install runbook {tok}, which does not exist")
    for num in re.findall(r"(?<!install runbook's )(?<!install runbook )\bsection (\d+(?:\.\d+)?)", rb):    # the install runbook's own are checked above
        if num not in heads:
            pr.append(f"the runbook cites its section {num}, which has no heading")
    return pr


def rule_workdir(rb, cl, S, F):
    """A block is run alone in a fresh console: the first line that calls a tool by its relative path comes after a Set-Location."""
    pr = []
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for i, b in enumerate(ps_blocks(doc), 1):
            lines = logical_lines(b)
            for j, ln in enumerate(lines):
                if TOOL_CALL_RE.search(ln):
                    if not any(re.match(r"\s*Set-Location\s+\S", earlier) for earlier in lines[:j]):
                        pr.append(f"{label}: block {i} calls a tool under tools/ before it sets its working folder")
                    break
    return pr


def rule_log_lines(rb, cl, S, F):
    pr = []
    levels = {}
    for key, text in (("open", "the advice log write failed or could not be verified"), ("close", "the advice log write is verified again")):
        m = re.search(r'_LOGGER\.(\w+)\(\s*"ECCO Intelligence: ' + re.escape(text), S["coordinator"])
        levels[key] = m.group(1).upper() if m else None
    if None in levels.values():
        return ["the coordinator's incident log lines (the one when an incident opens, the one when it closes) were not found"]
    opened, closed = levels["open"], levels["close"]
    for phrase in (f"the first-failure line is a {opened}", f"the close line is logged at {closed}",
                   f"only if the logger level for the integration allows {closed}", "recalled, not verified for the pinned Core",
                   f"absence of the {closed} close line is not a failure", "a closed incident is read from the diagnostics download"):
        if not has(section(rb, "2.3"), phrase):         # where the owner reads what to expect (not only somewhere in the runbook)
            pr.append(f"runbook 2.3 lacks '{phrase}'")
    p1 = next((c for c in table_rows(section(rb, "5")) if c[0] == "P1"), None)
    if p1 is None or not (has(" ".join(p1), "records the logger level") and has(" ".join(p1), f"close line is logged at {closed}")):
        pr.append("P1 does not say that the close line is logged at INFO and that the run records the logger level")
    if not has(section(rb, "12"), f"close line is logged at {closed}"):
        pr.append(f"runbook 12 does not say that the close line is logged at {closed}")
    if not has(section(rb, "8.10"), "logger level") or not has(section(rb, "8.10"), "not a failure"):
        pr.append("8.10 does not say that the after-checks record the logger level and that a missing close line is not a failure")
    if not any(has(" ".join(c), "close line") and has(" ".join(c), "logger level") for c in table_rows(section(rb, "11"))):
        pr.append("section 11 has no row for a close line that does not show")
    c2 = section(cl, "2")
    for phrase in (f"close line logged at {closed}", "its absence is not a failure"):
        if not has(c2, phrase):
            pr.append(f"the checklist's section 2 lacks '{phrase}'")
    if not has(section(cl, "5"), "logger level"):
        pr.append("the checklist's verification does not say that the log is read at a noted logger level")
    return pr


def rule_write_statement(rb, cl, S, F):
    """The same list of writes in both documents, and never 'the only write outside the scorecard file is the pause helper'."""
    pr = []
    for label, text in (("runbook 2.4", section(rb, "2.4")), ("checklist 2", section(cl, "2"))):
        for phrase in ("the integration folder", "the staging and backup folders", "scorecard file", "store_meta.json", "pause helper"):
            if not has(text, phrase):
                pr.append(f"{label} does not list '{phrase}' among the writes")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        if has(doc, "only write outside the scorecard file"):
            pr.append(f"{label} says the only write outside the scorecard file is the pause helper (the update also replaces the integration folder, "
                      "writes the staging and backup folders, and store_meta.json is still written)")
    return pr


def rule_lazy_tables(rb, cl, S, F):
    pr = []
    sc = S["scorecard"]
    if not re.search(r"def record_advice\(.*?self\._ensure_advice_log\(\)\s*\n\s*for r in advice_log_rows\(", sc, re.S) \
            or sc.count("self._ensure_advice_log()") != 1:
        pr.append("record_advice no longer creates advice_log first, once, before it looks at any row (the documents say: at the first "
                  "advice-log attempt, even if it writes no row)")
    if sc.count("self._ensure_incident_table()") != 1 or not re.search(r"def persist_advice_incidents\(.*?self\._ensure_incident_table\(\)", sc, re.S):
        pr.append("advice_incident is created somewhere other than the incident persist (the documents say: by the incident persist after a verified write)")
    a_rows = {c[0]: " ".join(c) for c in table_rows(section(rb, "2.1")) if re.fullmatch(r"A\d", c[0])}
    d2 = {"runbook": " ".join(next((c for c in table_rows(section(rb, "4")) if c[0] == "D-U2-2"), [])),
          "checklist": " ".join(next((c for c in table_rows(section(cl, "3")) if c[0] == "D-U2-2"), []))}
    places = (("runbook A2", a_rows.get("A2", ""), ("first advice-log attempt", "even if that attempt writes no row")),
              ("runbook A3", a_rows.get("A3", ""), ("incident persist", "verified advice write")),
              ("runbook 2.3", section(rb, "2.3"), ("first advice-log attempt", "even if that attempt writes no row", "incident persist")),
              ("runbook D-U2-2", d2["runbook"], ("first advice-log attempt", "even if that attempt writes no row", "incident persist")),
              ("checklist 2", section(cl, "2"), ("first advice-log attempt", "even if that attempt writes no row", "incident persist")),
              ("checklist D-U2-2", d2["checklist"], ("first advice-log attempt", "even if that attempt writes no row", "incident persist")))
    for where, text, phrases in places:
        for phrase in phrases:
            if not has(text, phrase):
                pr.append(f"{where} lacks '{phrase}'")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for old in ("first advice write", "by an advice write", "not by the advice write"):
            if has(doc, old):
                pr.append(f"{label} still says '{old}' (advice_log is created at the first advice-log attempt, even if it writes no row)")
    return pr


RULES = {
    "shape": rule_shape, "tools": rule_tools, "kit": rule_kit, "numbers": rule_numbers, "store_record": rule_store_record,
    "no_restart": rule_no_restart, "cls": rule_cls, "quotes": rule_quotes, "sentences": rule_sentences, "forbidden": rule_forbidden,
    "preconditions": rule_preconditions, "steps": rule_steps, "rollback": rule_rollback, "decisions": rule_decisions,
    "no_entity": rule_no_entity, "coverage": rule_coverage, "drill": rule_drill, "phrases": rule_phrases, "vars": rule_vars,
    "cites": rule_cites, "workdir": rule_workdir, "log_lines": rule_log_lines, "write_statement": rule_write_statement,
    "lazy_tables": rule_lazy_tables,
}
RULE_TITLES = {
    "shape": "[1] both documents exist, are ASCII, the checklist has at most 120 lines, the sections are numbered",
    "tools": "[2] every tool, flag, sub-command and -Action value the documents name exists in the tool's source; Plan, Upgrade and Rollback carry the right flags",
    "kit": "[3] the SHA256SUMS sha256 of both reference builds, the file counts and the new and changed file names are what the build produces",
    "numbers": "[4] the table names, retention bound, rows a day, incident list size, read budgets and export epsilon are the sources' own, in EVERY mention",
    "store_record": "[5] the STORE_RECORD semantics are stated, quote texts the store produces, and agree with the runtime document; the download shows PASS only",
    "no_restart": "[6] no restart flag or command anywhere; the restart is the owner's, approved separately",
    "cls": "[7] every PowerShell block starts with cls",
    "quotes": "[8] the owner's three quotes are in the runbook, their substance in the checklist",
    "sentences": "[9] no automatic installation or live access is authorised; never run in a real Home Assistant",
    "forbidden": "[10] none of the three forbidden phrases, an entity id, an address, a token, a workstation path, a commit id or an unexplained hash",
    "preconditions": "[11] P1 (the L3 WSL run on the exact kit) is OPEN and says what it must show; the open set agrees in both documents",
    "steps": "[12] the same steps and who in both, an owner go at each live step, the restart with its own approval",
    "rollback": "[13] RB1 to RB6 in order in both, a proof for each, the rollback command with its stamp, no bare R-number, the heavy last resort, S6",
    "decisions": "[14] D-U2-1 to D-U2-9 are open in both; the two named questions carry the source's own facts",
    "no_entity": "[15] the update creates no entity: the platforms, eleven contract entities, the package's file set",
    "coverage": "[16] every bullet of 'what is NOT established' has a keyword, and the checklist says each",
    "drill": "[17] the drill's statement is made and true: the real drill leaves a state folder with both tables byte-identical",
    "phrases": "[18] the tool phrases the runbook quotes are printed by the tools",
    "vars": "[19] every PowerShell block sets the variables it uses",
    "cites": "[20] every section and install-runbook section or row the documents cite exists",
    "workdir": "[21] every PowerShell block that calls a tool under tools/ sets its working folder first",
    "log_lines": "[22] the first-failure line is a WARNING and the close line is logged at INFO (the coordinator's own levels): the documents say the close line may not show and that its absence is not a failure",
    "write_statement": "[23] the runbook and the checklist list the same writes; neither says the pause helper is the only write outside the scorecard file",
    "lazy_tables": "[24] advice_log is created at the first advice-log attempt, advice_incident by the incident persist after a verified write: the code does so and every place that says it agrees",
}


def analyse(rb, cl, S, F):
    return {name: fn(rb, cl, S, F) for name, fn in RULES.items()}


def fired(result: dict) -> set[str]:
    return {k for k, v in result.items() if v}


# ---------------------------------------------------------------------------------------------------------------------
# facts from the sources, the kit build and the real drill
# ---------------------------------------------------------------------------------------------------------------------
def kit_facts(base: Path) -> dict:
    out = {}
    for key, sha in (("nosha", None), ("fixed", FIXED_SHA)):
        d = base / f"kit_{key}"
        r = H.build_kit(d, git_sha=sha)
        check(f"the kit builds ({key}), rc 0", r.returncode == 0, (r.stdout + r.stderr)[-300:])
        sums = (d / "SHA256SUMS").read_bytes()
        out[key] = hashlib.sha256(sums).hexdigest()
        if key == "nosha":
            out["line"] = r.stdout.splitlines()[0] if r.stdout else ""
            paths = [ln.split("  ", 1)[1] for ln in sums.decode("utf-8").splitlines() if "  " in ln]
            out["all"] = set(paths)
            out["pkg"] = [p for p in paths if p.startswith(PKG + "/")]
            out["root_py"] = {p[len(PKG) + 1:-3] for p in out["pkg"] if "/" not in p[len(PKG) + 1:] and p.endswith(".py")}
    out["dir"] = base / "kit_fixed"
    return out


def real_facts() -> dict:
    from intelligence import advisory_contract as ac
    from intelligence import scorecard as sc
    const_src = read_src(SOURCES["const"])
    consts = re.search(r"PLATFORMS = \(([^)]*)\)", const_src)
    sched = re.search(r"SCHEDULE_DAILY_LOCAL = \((\d+), (\d+)\)", const_src)
    slots = 0          # a slot cycle at every full hour, plus the daily time when it is not on the hour
    if sched:
        slots = 24 + (1 if int(sched.group(2)) != 0 else 0)
    kinds = len(sc.ADVICE_LOG_KINDS)
    return {
        "slots": slots, "rows_normal": kinds * slots, "rows_max": kinds * (slots + 1),     # the day the clocks go back has one more hour
        "retention": sc.ADVICE_LOG_RETENTION_DAYS, "kept": sc.ADVICE_INCIDENTS_KEPT, "kinds": kinds,
        "tables": re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sc.ADVICE_LOG_DDL + sc.ADVICE_INCIDENT_DDL),
        "eps": re.search(r"EXPORT_DIFF_EPS_KWH = ([0-9.]+)", read_src(SOURCES["ghost_compare"])).group(1),
        "ghost_budget": float(re.search(r"PROPOSED_GHOST_BUDGET_S = ([0-9.]+)", read_src(SOURCES["ghost_link"])).group(1)),
        "stored_budget": float(re.search(r"STORED_INCIDENTS_BUDGET_S = ([0-9.]+)", read_src(SOURCES["coordinator"])).group(1)),
        "entities": len(ac.INTEGRATION_ENTITY_KEYS),
        "platforms": tuple(re.findall(r'"(\w+)"', consts.group(1))) if consts else (),
    }


def advice_payloads(gen: datetime) -> dict:
    from intelligence import advisory_contract as ac
    base = {"mode": "SHADOW", "applies_nothing": True, "contract_version": ac.CONTRACT_VERSION}
    until = gen + timedelta(seconds=900)
    ct_sum = {"target_soc_pct": 80.0, "effective_reserve_pct": 40.0, "conservative_fallback": False,
              "window": [(gen + timedelta(hours=2)).isoformat(), (gen + timedelta(hours=6)).isoformat()]}
    dp_sum = {"dump_advisable": True, "stop_soc_pct": 55.0, "export_kwh": 3.2, "export_kw_avg": 3.2, "effective_reserve_pct": 40.0}
    ct = ac.ItemView("charge_target", "OK", 80.0, until, "MEDIUM", (), ("R1",), ct_sum)
    dp = ac.ItemView("dump_to_grid", "OK", 3.2, until, "LOW", (), ("D1",), dp_sum)
    out = {}
    for v in (ct, dp):
        rec = {**base, "kind": v.key, "status": v.status, "generated_at": gen.isoformat(), "unit": v.unit,
               "valid_until": v.valid_until.isoformat(), "confidence": v.confidence, "blockers": [], "reason_codes": list(v.reason_codes)}
        out[ac.ENTITY_IDS[v.key]] = (v.value, rec, {"advice": ac._view_advice(v, True)})
    return out


def run_real_drill(base: Path, kit_a: Path) -> dict:
    """The repository's own drill, on a marked mock root whose state folder holds a scorecard file with BOTH new tables."""
    from intelligence import scorecard as sc
    spec = importlib.util.spec_from_file_location("ecco_intel_drill_ghost", REPO / "tools" / "ecco_intel_drill.py")
    D = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(D)
    kit_b = base / "kit_b"
    shutil.copytree(kit_a, kit_b)
    target = kit_b / PKG / "runtime" / "selftest.py"
    target.write_bytes(target.read_bytes() + b"\n# a synthetic upgrade\n")
    sums = "".join(f"{hashlib.sha256((kit_b / rel).read_bytes()).hexdigest()}  {rel}\n"
                   for rel in sorted(k for k in H.tree_hashes(kit_b) if not k.endswith("/") and k != "SHA256SUMS"))
    (kit_b / "SHA256SUMS").write_bytes(sums.encode("utf-8"))
    root = base / "mock"
    state = root / "ecco" / "intelligence" / "state"
    state.mkdir(parents=True)
    (root / "ecco" / "intelligence" / "site.local.json").write_text('{"_comment": "synthetic mock site file"}\n', encoding="utf-8")
    (root / "custom_components" / "other_integration").mkdir(parents=True)
    (root / "custom_components" / "other_integration" / "__init__.py").write_text("# another integration\n", encoding="utf-8")
    (root / D.MARKER).write_text("mock\n", encoding="utf-8")
    t0 = datetime(2030, 3, 4, 20, 0, tzinfo=timezone.utc)
    card = sc.Scorecard(str(state / "scorecard.sqlite3"))
    wrote = card.record_advice(advice_payloads(t0))
    inc = {"first_failed_utc": (t0 + timedelta(minutes=5)).isoformat(), "last_failed_utc": (t0 + timedelta(minutes=5)).isoformat(),
           "failed_count": 1, "missed_slots": 1, "reason": "OperationalError", "first_reason": "OperationalError",
           "first_issued_utc": t0.isoformat(), "last_issued_utc": t0.isoformat(),
           "recovered_utc": (t0 + timedelta(hours=1)).isoformat(), "rows_since": 2}
    persisted = card.persist_advice_incidents([inc], t0 + timedelta(hours=1))
    card.close()
    con = sqlite3.connect(f"file:{(state / 'scorecard.sqlite3').as_posix()}?mode=ro", uri=True)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    if not ({"advice_log", "advice_incident"} <= tables and wrote == 2 and persisted.get("error") is None):
        return {"ok": False, "detail": f"set-up: tables {sorted(tables)}, rows {wrote}, persist {persisted}"}

    def state_hashes() -> dict:
        return {k: v for k, v in H.tree_hashes(root).items() if k.startswith(("ecco/intelligence/", "custom_components/other_integration"))}

    before = state_hashes()
    d = D.Drill(D.mock_root(str(root)), log=lambda *_: None)
    try:
        d.install(kit_a, "20300115-120000")
        d.install(kit_b, "20300115-120001", upgrade=True)
        d.rollback("20300115-120002", "20300115-120001")
        d.uninstall("20300115-120003")
    except D.DrillError as exc:
        return {"ok": False, "detail": f"the drill stopped: {exc}"}
    after = state_hashes()
    ok = before == after and all(s[0] == "PASS" for s in d.steps) and len(d.steps) > 20
    return {"ok": ok, "detail": f"{len(d.steps)} steps, state unchanged: {before == after}"}


# ---------------------------------------------------------------------------------------------------------------------
# the mutants (all in memory)
# ---------------------------------------------------------------------------------------------------------------------
def sub1(text: str, old: str, new: str) -> str:
    return text.replace(old, new, 1)


def subw(text: str, old: str, new: str) -> str:
    """sub1, but the phrase may wrap over lines: any run of whitespace in the text matches a space of `old` (the first match is replaced)."""
    rx = r"\s+".join(re.escape(w) for w in old.split())
    return re.sub(rx, lambda _m: new, text, count=1)


def drop_line(text: str, needle: str) -> str:
    return "\n".join(ln for ln in text.split("\n") if needle not in ln)


def make_mutants(F):
    k = F["kit"]
    sample_entity = "sen" + "sor" + "." + "some_value"
    sample_addr = "192" + "." + "168" + "." + "1" + "." + "5"
    sample_path = "C" + ":" + chr(92) + "Users" + chr(92) + "someone"
    sample_commit = "ab12" * 10
    sample_token = "ghp" + "_" + "a" * 36
    out = []

    def add(target, name, fn, rule):
        out.append((target, name, fn, rule))

    add("rb", "a wrong build flag (--git-sh)", lambda t: sub1(t, "--out $KIT --git-sha 0000000", "--out $KIT --git-sh 0000000"), "tools")
    add("rb", "a deploy parameter that does not exist (-ReferenceKitt)", lambda t: sub1(t, "-ReferenceKit <the L3-tested kit>", "-ReferenceKitt <the L3-tested kit>"), "tools")
    add("rb", "an -Action that does not exist (Upgrad)", lambda t: sub1(t, "-Action Upgrade -SshHost", "-Action Upgrad -SshHost"), "tools")
    add("rb", "a drill sub-command that does not exist (drils)", lambda t: sub1(t, "ecco_intel_drill.py drill --config-root", "ecco_intel_drill.py drils --config-root"), "tools")
    add("rb", "the Plan and Upgrade lines without -ExpectedSumsSha256", lambda t: t.replace("-ExpectedSumsSha256 <sha256> ", ""), "tools")
    add("rb", "a proof dropped from RB2", lambda t: sub1(t, "Proof: the PASSED block", "The PASSED block"), "rollback")
    add("rb", "RB5's proof dropped", lambda t: sub1(t, "Proof: `PRAGMA integrity_check`", "Check: `PRAGMA integrity_check`"), "rollback")
    add("rb", "the first block's cls dropped", lambda t: sub1(t, FENCE + "powershell\ncls\n", FENCE + "powershell\n"), "cls")
    add("rb", "the restart sentence removed", lambda t: re.sub(r"only with the owner's explicit\s+approval,\s+separate from the\s+Upgrade", "at some point", t, count=1), "no_restart")
    add("rb", "an automatic restart flag added to the Upgrade line", lambda t: re.sub(r"(-Action Upgrade[^\n]*\n[^\n]*-Python \$PY)", r"\1 -Restart", t, count=1), "no_restart")
    add("rb", "the retention bound changed (400 to 300 days)", lambda t: t.replace("400 days", "300 days"), "numbers")
    add("cl", "the rows a day changed (52 to 60)", lambda t: t.replace("52 rows a day", "60 rows a day"), "numbers")
    add("rb", "a table name misspelled", lambda t: t.replace("advice_incident`", "advice_incidnt`"), "numbers")
    add("rb", "the export epsilon changed in the runbook", lambda t: t.replace("0.001 kWh", "0.01 kWh"), "numbers")
    add("rb", "the L3 precondition closed", lambda t: re.sub(r"(\| P1 \|.*?)\*\*OPEN\*\*", r"\1closed", t, count=1, flags=re.S), "preconditions")
    add("rb", "the L3 precondition no longer asks for the executor reads", lambda t: t.replace("executor reads in the diagnostics download", "reads"), "preconditions")
    add("cl", "the checklist drops the WSL run", lambda t: t.replace("L3 (WSL) kit-equivalence reference run", "reference run"), "preconditions")
    add("cl", "the checklist claims it is ready", lambda t: t.replace("NOT yet ready", "ready"), "preconditions")
    add("rb", "a forbidden word added (guaranteed)", lambda t: t + "\nThe rollback is guaranteed.\n", "forbidden")
    add("cl", "a forbidden phrase added (safe to install)", lambda t: t + "\nIt is safe to install.\n", "forbidden")
    add("rb", "an entity id added", lambda t: t + f"\nSee {sample_entity}.\n", "forbidden")
    add("cl", "an address added", lambda t: t + f"\nHost {sample_addr}.\n", "forbidden")
    add("rb", "a workstation path added", lambda t: t + f"\nFile {sample_path}.\n", "forbidden")
    add("rb", "a commit id added", lambda t: t + f"\nBuilt from {sample_commit}.\n", "forbidden")
    add("cl", "a token added", lambda t: t + f"\nKey {sample_token}.\n", "forbidden")
    add("rb", "a hash that is not pinned", lambda t: t + "\n" + "ab" * 32 + "\n", "forbidden")
    add("rb", "the nosha hash changed by one digit", lambda t: t.replace(k["nosha"], k["nosha"][:-1] + ("0" if k["nosha"][-1] != "0" else "1")), "kit")
    add("cl", "the fixed-reference hash removed from the checklist", lambda t: t.replace(k["fixed"], "REMOVED"), "kit")
    add("rb", "the file count changed (58 files)", lambda t: t.replace("58 files", "59 files"), "kit")
    add("rb", "a new file's name dropped", lambda t: t.replace("ghost_link.py", "glue.py"), "kit")
    add("cl", "no automatic installation sentence removed from the checklist", lambda t: re.sub(r"(?i)no automatic installation or live access is authorised", "REMOVED", t), "sentences")
    add("rb", "never run in a real Home Assistant removed from the runbook", lambda t: re.sub(r"never run in a real Home Assistant", "REMOVED", t), "sentences")
    add("rb", "an owner quote altered", lambda t: t.replace("allow current health to recover", "let health recover"), "quotes")
    add("cl", "the substance of a quote dropped", lambda t: t.replace("own backup, restart and rollback verification", "own checks"), "quotes")
    add("cl", "a step row removed from the checklist", lambda t: drop_line(t, "| 6 | coordinator, **go** |"), "steps")
    add("cl", "a step's who changed", lambda t: t.replace("| 4 | coordinator, **go** |", "| 4 | you, **go** |"), "steps")
    add("rb", "a live step without its own authorisation", lambda t: re.sub(r"(\| 6 \|.*?\| read-only \| )\*\*yes\*\*", r"\1no", t, count=1), "steps")
    add("rb", "the restart's own approval weakened", lambda t: t.replace("**yes, its own approval, separate from the Upgrade**", "**yes**"), "steps")
    add("cl", "the rollback order swapped (RB2 and RB3)", lambda t: t.replace("**RB2 restore", "**RB9 restore").replace("**RB3 restart", "**RB2 restart").replace("**RB9 restore", "**RB3 restore"), "rollback")
    add("rb", "the rollback command without its stamp", lambda t: t.replace("-Action Rollback -BackupStamp <stamp>", "-Action Rollback"), "tools")
    add("cl", "D-U2-7 marked decided", lambda t: t.replace("| D-U2-7 | `advice.followed` counts a row withdrawn by a later BLOCKED row before its window; the simulation's own use is `advice_in_force_hours` | open |", "| D-U2-7 | `advice.followed` counts a row withdrawn by a later BLOCKED row before its window; the simulation's own use is `advice_in_force_hours` | decided |"), "decisions")
    add("rb", "an owner item removed (D-U2-9)", lambda t: drop_line(t, "| D-U2-9 |"), "decisions")
    add("rb", "the no-entity statement removed", lambda t: t.replace("this update creates no entity", "this update may add a helper"), "no_entity")
    add("cl", "the checklist's RG-F3 mention removed", lambda t: t.replace("RG-F3", "the exposure item"), "no_entity")
    add("rb", "a not-established bullet's keyword removed", lambda t: t.replace("durability proof", "proof"), "coverage")
    add("cl", "the checklist forgets the executor reads in section 8", lambda t: sub1(t, "The log lines and the download's executor reads have not been seen", "The log lines have not been seen"), "coverage")
    add("rb", "the drill statement removed", lambda t: t.replace("What the drill proves, exactly.", "What the drill does."), "drill")
    add("rb", "a quoted tool phrase altered (NO CHANGE)", lambda t: t.replace("NO CHANGE", "NOTHING CHANGED"), "phrases")
    add("rb", "STORE_RECORD recovery weakened", lambda t: t.replace("PASS only after a verified write", "PASS after any write"), "store_record")
    add("cl", "the WARN semantics dropped from the checklist", lambda t: t.replace("WARN while an incident is open", "a warning at times"), "store_record")
    add("rb", "a variable not set in a block", lambda t: sub1(t, "$E = '<OFFLINE_EVIDENCE_DIR>\\u2-baseline'\n$KIT = '<the install kit>'\n$prefix", "$KIT = '<the install kit>'\n$prefix"), "vars")
    add("cl", "the checklist grows past 120 lines", lambda t: t + "\n" * 30 + "\n".join(["- more"] * 30), "shape")
    add("cl", "the checklist cites a runbook section that does not exist", lambda t: t.replace("(runbook 10;", "(runbook 77;"), "cites")
    add("rb", "an install runbook row that does not exist is cited", lambda t: sub1(t, "install runbook G4", "install runbook G44"), "cites")

    # --- the second review round: a block's working folder (F1)
    add("rb", "step 8's log read without its working folder", lambda t: sub1(t, "Set-Location <checkout>\n& $PY -I -B -X utf8 -c", "& $PY -I -B -X utf8 -c"), "workdir")
    add("rb", "the kit build block without its working folder",
        lambda t: sub1(t, "Set-Location <checkout>\n& $PY -I -B -X utf8 tools\\build_ha_integration.py --out $KIT --git-sha 0000000",
                       "& $PY -I -B -X utf8 tools\\build_ha_integration.py --out $KIT --git-sha 0000000"), "workdir")
    # the incident-close line is logged at INFO (F2)
    add("rb", "the INFO level of the close line no longer stated", lambda t: subw(t, "the close line is logged at INFO, so it shows", "the close line shows"), "log_lines")
    add("rb", "the missing close line no longer called not a failure",
        lambda t: subw(t, "The absence of the INFO close line is not a failure:", "The absence of the INFO close line matters:"), "log_lines")
    add("rb", "P1 no longer records the logger level", lambda t: subw(t, "the run records the logger level it ran under", "the run records the lines"), "log_lines")
    add("rb", "the section 11 row for a close line that does not show removed", lambda t: drop_line(t, "| no INFO close line in the log"), "log_lines")
    add("cl", "the checklist no longer says the close line may not show",
        lambda t: subw(t, "a close line logged at INFO that may not show at your logger level (its absence is not a failure; runbook 2.3)", "a close line"), "log_lines")
    # the download shows PASS only (F3)
    add("rb", "the PASS text said to be visible in the download",
        lambda t: subw(t, "PASS only after a verified write.", 'PASS only after a verified write (its text: "the scorecard step completed; the advice log write is verified").'),
        "store_record")
    add("rb", "the PASS text no longer said to be unexported", lambda t: subw(t, "is not exported anywhere in the download", "is exported"), "store_record")
    # this runbook's items are RB1 to RB6; an install-runbook item is named in full (F4)
    add("rb", "RB4's listing comparison cited as R2", lambda t: subw(t, "the listing comparison of RB2 is still empty", "the listing comparison of R2 is still empty"), "rollback")
    add("rb", "the drill note cites R3 for the previous-code experiment", lambda t: subw(t, "(section 10, RB3)", "(section 10, R3)"), "rollback")
    add("rb", "RB4 cites the install runbook's R1 and R4 again",
        lambda t: subw(t, "the install runbook's section 7 go / no-go for the first observed runs: supervision", "the install runbook's R1 and R4: supervision"), "rollback")
    add("rb", "an install runbook section that does not exist is cited (section 77)",
        lambda t: subw(t, "install runbook's section 7 go / no-go", "install runbook's section 77 go / no-go"), "cites")
    # a rollback before any restart (F5)
    add("rb", "S6 no longer asks the owner", lambda t: subw(t, "So **ask the owner** before skipping RB3", "So skip RB3"), "rollback")
    add("rb", "S6 removed", lambda t: subw(t, "*S6, a no-go at step 6", "*S9, a no-go at step 6"), "rollback")
    add("cl", "the checklist no longer leaves RB3 to the owner before the restart", lambda t: subw(t, "runbook 10, S6", "runbook 10"), "rollback")
    # the writes of the update (F6)
    add("cl", "the false sentence restored (the only write outside the scorecard file is the pause helper)",
        lambda t: subw(t, "The one helper the procedure touches is the existing pause helper, which you turn on and off.",
                       "The only write outside the scorecard file is the pause helper, which you turn on and off (runbook 2.4)."), "write_statement")
    add("rb", "the staging and backup folders left out of the write statement",
        lambda t: subw(t, "the staging and backup folders of the Upgrade (A4)", "the Upgrade's folders (A4)"), "write_statement")
    add("cl", "store_meta.json left out of the checklist's writes", lambda t: subw(t, "with `store_meta.json` still written as before", "with nothing else"), "write_statement")
    # every mention of a constant, and the RB6 wording (F7)
    add("rb", "the retention changed in the runbook's bounds row only (D-U2-3)", lambda t: subw(t, "an age bound of 400 days (PROPOSED", "an age bound of 300 days (PROPOSED"), "numbers")
    add("cl", "the retention changed in the checklist's bounds row only (D-U2-3)", lambda t: subw(t, "the 400-day age bound", "the 300-day age bound"), "numbers")
    add("rb", "the rows a day changed in section 12 only", lambda t: subw(t, "At most 52 a day", "At most 60 a day"), "numbers")
    add("cl", "the rows a day changed in the bounds row only (D-U2-3)", lambda t: subw(t, "D-U2-3 | at most 52 rows a day", "D-U2-3 | at most 60 rows a day"), "numbers")
    add("rb", "the rows of a normal day changed", lambda t: subw(t, "(50 on a normal day)", "(40 on a normal day)"), "numbers")
    add("rb", "the incident list size changed in 2.3 only", lambda t: subw(t, "(the newest 10)", "(the newest 12)"), "numbers")
    add("cl", "the incident list size changed in the second table's row only", lambda t: subw(t, "`advice_incident` (at most 10 rows)", "`advice_incident` (at most 12 rows)"), "numbers")
    add("rb", "the table size estimate changed", lambda t: subw(t, "about 21 000 rows", "about 41 000 rows"), "numbers")
    add("rb", "'heavy' removed everywhere from the runbook (the protected backup restore)", lambda t: t.replace("heavy ", ""), "rollback")
    add("cl", "'heavy' removed everywhere from the checklist (the protected backup restore)", lambda t: t.replace("heavy ", ""), "rollback")
    add("rb", "'never the first rollback' removed everywhere", lambda t: t.replace("never the first rollback", "the last step"), "rollback")
    add("cl", "'never the first rollback' removed", lambda t: t.replace("never the first rollback", "not the first"), "rollback")
    # when the tables are created (F8)
    add("rb", "A2 back to 'created by the first advice write'",
        lambda t: subw(t, "created at the first advice-log attempt of the running integration, even if that attempt writes no row",
                       "created by the first advice write of the running integration"), "lazy_tables")
    add("rb", "D-U2-2 loses the incident persist",
        lambda t: subw(t, "`advice_incident` by the incident persist that runs right after a verified write, only when",
                       "`advice_incident` only after the first verified write, only when"), "lazy_tables")
    add("cl", "the checklist's second table loses the incident persist",
        lambda t: subw(t, "created by the incident persist that runs right after a verified write", "created only after a verified write"), "lazy_tables")
    add("rb", "A3 says 'not by an advice write' again", lambda t: subw(t, "not by the advice-log attempt itself", "not by an advice write"), "lazy_tables")
    return out


def make_source_mutants():
    def drop_param(src):
        return src.replace("[string]$ReferenceKit,", "")

    def drop_gitsha(src):
        return src.replace('"--git-sha"', '"--git-shaX"')

    def drop_phrase(src):
        return src.replace("ROLLBACK NOT CONFIRMED", "ROLLBACK UNCLEAR")

    def drop_validate(src):
        return src.replace("'Upgrade', ", "")

    def drop_drill_check(src):
        return src.replace("site.local.json, state/ and the other integration untouched by every step", "untouched")

    def drop_store_text(src):
        return src.replace("PASS needs a verified write", "PASS needs a write")

    def close_line_warning(src):
        return src.replace('_LOGGER.info("ECCO Intelligence: the advice log write is verified again',
                           '_LOGGER.warning("ECCO Intelligence: the advice log write is verified again')

    def pass_text_exported(src):
        return src.replace('c.level if c.level == PASS else f"{c.level}: {c.short}"', 'f"{c.level}: {c.short}"')

    def no_early_create(src):
        return src.replace("self._ensure_advice_log()\n            for r in advice_log_rows(", "for r in advice_log_rows(")

    def reader_creates_table(src):
        return src.replace("    def advice_incidents(self) -> list[dict]:", "    def advice_incidents(self) -> list[dict]:\n        self._ensure_advice_log()", 1)

    return [
        ("deploy", "the deploy tool without the -ReferenceKit parameter", drop_param, "tools"),
        ("build", "the build tool without the --git-sha flag", drop_gitsha, "tools"),
        ("psm1", "the module no longer prints ROLLBACK NOT CONFIRMED", drop_phrase, "phrases"),
        ("deploy", "the deploy tool's ValidateSet without Upgrade", drop_validate, "tools"),
        ("drill_suite", "the drill suite without the check the runbook relies on", drop_drill_check, "drill"),
        ("store", "the store no longer says PASS needs a verified write", drop_store_text, "store_record"),
        ("coordinator", "the close line is logged at WARNING", close_line_warning, "log_lines"),
        ("selftest", "the self-test export returns the text of a passing check", pass_text_exported, "store_record"),
        ("scorecard", "record_advice no longer creates advice_log before it looks at any row", no_early_create, "lazy_tables"),
        ("scorecard", "a reader creates advice_log too", reader_creates_table, "lazy_tables"),
    ]


# ---------------------------------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------------------------------
print(f"== the two documents (read from {'the repository' if DOCS_ROOT == REPO else 'a named folder'})")
RB = read_doc(RB_REL)
CL = read_doc(CL_REL)
check("the runbook exists", RB is not None, RB_REL)
check("the checklist exists", CL is not None, CL_REL)

S0 = {k: read_src(v) for k, v in SOURCES.items()}
base = H.mktemp(PREFIX)
try:
    print("== the kit, built by the repository's own tool into temporary directories")
    F = {"kit": kit_facts(base), "facts": real_facts(), "ghost_feed_src": S0["ghost_feed"]}
    print("== the real drill, with the real kit and a state folder that holds both new tables")
    F["drill"] = run_real_drill(base, F["kit"]["dir"])
    check("the real drill leaves the state folder byte-identical through install, upgrade, rollback and uninstall",
          F["drill"]["ok"], F["drill"]["detail"])
    own_bytes = Path(__file__).read_bytes()
    own = own_bytes.decode("utf-8", errors="replace")
    check("this suite's own source is ASCII and holds no address, token, entity id or workstation path",
          own_bytes.isascii() and not IPV4_RE.search(own) and not TOKEN_RE.search(own) and not ENTITY_RE.search(own)
          and not PATH_RE.search(own))

    if RB is not None and CL is not None:
        print("== the rules")
        result = analyse(RB, CL, S0, F)
        for name in RULES:
            check(RULE_TITLES[name], not result[name], "; ".join(result[name][:4]))
        check("the open preconditions are exactly P1, P3, P4, P5, P6, P7 and P9 at the time of writing", open_ids(RB) == set(OPEN_AT_WRITING),
              str(sorted(open_ids(RB))))
        base_ok = not fired(result)
        check("the unmutated documents pass every rule (the baseline of the mutants)", base_ok, str(sorted(fired(result))))
        if base_ok:
            print("== the mutants")
            mutants = make_mutants(F)
            killed = 0
            for target, name, fn, rule in mutants:
                src = RB if target == "rb" else CL
                mutated = fn(src)
                check(f"{name}: the mutation changes the text", mutated != src)
                got = fired(analyse(mutated, CL, S0, F) if target == "rb" else analyse(RB, mutated, S0, F))
                ok = rule in got
                killed += ok
                check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
            smutants = make_source_mutants()
            for key, name, fn, rule in smutants:
                mutated = fn(S0[key])
                check(f"{name}: the mutation changes the text", mutated != S0[key])
                got = fired(analyse(RB, CL, {**S0, key: mutated}, F))
                ok = rule in got
                killed += ok
                check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
            total = len(mutants) + len(smutants)
            check(f"at least ten mutants are run and every one is killed ({killed} of {total}: {len(mutants)} of the documents, "
                  f"{len(smutants)} of the sources)", total >= 10 and killed == total)
finally:
    H.rmtree_own(base, PREFIX)

print("")
print(f"{PASSED[0]} PASS, {len(FAILURES)} FAIL")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the Ghost update documents suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all Ghost update documents checks passed")
