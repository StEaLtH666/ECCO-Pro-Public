#!/usr/bin/env python3
"""Consistency suite: the U3 inverter power-balance update runbook and its short GO checklist against the real tools and facts.

  docs/intelligence/POWER_BALANCE_UPDATE_RUNBOOK.md      the runbook (cited by the checklist as "runbook N")
  docs/intelligence/POWER_BALANCE_UPDATE_GO_CHECKLIST.md the short checklist (at most 120 lines)

A short document that a person decides on is only worth something while it says what the long one and the tools say. This suite
reads both documents as text (no Home Assistant, no network, no PowerShell) and checks them against the sources they name:

  [1] shape: both exist, are ASCII, the checklist has at most 120 lines, the runbook has sections 1 to 12 and the checklist 1 to 8
  [2] tools and flags: every tool a command names exists, every flag it carries exists in that tool's source (the interpreter's own
      flags, written before the script, are not the tool's), every -Action and -Target value is in the deploy tool's ValidateSet, every
      drill and fit sub-command exists, the Plan and Upgrade lines carry the flags the route requires, the Rollback line takes no
      kit, every placement line carries the flags it needs and the placement is shown with and without -Plan
  [3] the kit: tools/build_ha_integration.py is run into temporary directories (outside the repository), with no commit and with the
      fixed reference commit; the two SHA256SUMS sha256 values, the file counts and the changed file names the documents state are
      those the build produces; where the checkout holds the history before this change, the previous kit is built too and the
      documents' "none new, none removed, five changed" and the pinned hash of the previous loader are compared with it
  [4] numbers: the bounds (0.90 to 1.0, 0 to 100 W), the fact names, the tolerance, the exposure figures at 5 kW, the rule-set version
      and the blocker codes are those of the sources, EVERY mention of a bound equals the source, and no calibrated-looking decimal
      (three or more decimals) is in either document: the facts are site values
  [5] the order: kit, then one restart, then the placement, then the reload, then the un-pause, in the step table of both documents;
      the rollback takes the facts out first; the documents give the reasons (the facts are the loosening step; the previous loader
      does not refuse them; the facts take effect only at a reload or a restart) and the sources make them true (the loader reads
      the three keys by name only, nothing refuses an unknown key of the site block, the placement tool says it takes effect only at
      a reload or a restart); where the checkout holds the history before this change, the previous loader is run on site files that carry
      the facts and must load them exactly as without
  [6] no automatic restart or reload: no restart flag or command in any block, the deploy tool has no restart parameter, the
      restart is the owner's, once, approved separately, the reload is its own approval and is not a restart
  [7] every PowerShell block starts with cls
  [8] the owner's words are in the runbook in full, their substance in the checklist
  [9] the plain sentences: no automatic installation or live access is authorised; never run in a real Home Assistant
 [10] forbidden: the three phrases the owner ruled out, an entity id, an address, a token, a workstation path, a commit id, a hash
      that is not one of the pinned ones, a non-ASCII character, a calibrated-looking decimal
 [11] preconditions: P1 (the L3 WSL run on the exact kit) is OPEN and says what it must show; the open set (P1, P3, P4, P5, P6, P7, P9)
      AND the closed set (P2, P8) are exact, each closed line gives its reason, and the open set is the same in both documents
 [12] the steps: the same step numbers in both, the same who, an owner go at each live step, the restart and the reload each with
      their own approval
 [13] the rollback: RB1 to RB7 in order in both, a proof for each in the runbook, the facts-only and the full sequence, the commands,
      the heavy last resort that is never the first rollback, no bare R-number citation, and a rollback before any restart (S6)
 [14] the owner's items D-U3-1 to D-U3-9 are open in both, never decided here
 [15] no entity: the platforms are sensor and binary sensor only, the integration has eleven contract entities, and the files directly
      under the kit's package are the known set
 [16] no durable write: the four changed kit sources hold no file, database or network write, the store (the only writer) does not
      name the facts, and the documents say no table, column or row type is added
 [17] what is NOT established: every bullet of the runbook's section 12 has a keyword, and the checklist's section 8 has each keyword
 [18] the drill: its statement is in the runbook, and the REAL drill is run here with a real kit and a synthetic previous kit on a
      mock root: install the previous kit, place a synthetic site file that holds the facts, upgrade, roll back, uninstall; the site
      file and the state folder are byte-identical through every step and the tree after the rollback is the previous kit's; the
      real site-check prints the lines the runbook quotes for no facts, valid facts and invalid facts
 [19] quoted tool phrases exist in the tools' sources
 [20] every block sets the variables it uses
 [21] every section the checklist cites exists in the runbook, and every install-runbook row or section the documents cite exists
 [22] every PowerShell block that calls a tool under tools/ sets its working folder first
 [23] the write statement: the runbook and the checklist list the same writes
 [24] data quality: the documents say it may stay DEGRADED, the source's rule is the one they state, and what to read next
 [25] the fit tool's rows the owner reads exist in the tool's source
 [26] the rollback proofs name real reads and real tool behaviour
 [27] mutants (all in memory): each is killed by the rule that exists for it

Usage: python custom_components/ecco_intelligence/tests/test_power_balance_update_docs.py [--docs-root DIR]
--docs-root names another folder to read the two documents from (this is how the suite is shown to fail on missing or stub documents).
Test-only, no network. Reads repository files, builds into temporary directories and removes them. The checks that need the tree just
before this change (found from the git history with a pickaxe search, never by a commit id written here) print SKIP, and count as neither
a pass nor a failure, where the checkout does not hold that history (a shallow clone).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(TESTS))
sys.path.append(str(REPO))

import _harness as H  # noqa: E402

FAILURES: list[str] = []
PASSED = [0]
SKIPPED: list[str] = []
PREFIX = "ecco_pb_docs_"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED[0] += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def skip(name: str, why: str) -> None:
    SKIPPED.append(name)
    print(f"  SKIP  {name} - {why}")


RB_REL = "docs/intelligence/POWER_BALANCE_UPDATE_RUNBOOK.md"
CL_REL = "docs/intelligence/POWER_BALANCE_UPDATE_GO_CHECKLIST.md"
INSTALL_REL = "docs/intelligence/INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md"
METHOD_REL = "docs/intelligence/DATA_QUALITY_METHOD.md"
PKG = "custom_components/ecco_intelligence"
SOURCES = {
    "build": "tools/build_ha_integration.py", "drill": "tools/ecco_intel_drill.py", "deploy": "tools/deploy-ha-kit.ps1",
    "place": "tools/place-ha-site-file.ps1", "status": "tools/ha-status.ps1", "logs": "tools/ha-logs.ps1",
    "psm1": "tools/EccoDeploy.psm1", "runoff": "tools/run_offline_tests.py", "deploy_suite": "tools/tests/Test-EccoDeploy.ps1",
    "fit": "intelligence/tools/power_balance_fit.py", "sd": "intelligence/site_decisions.py", "quality": "intelligence/quality.py",
    "contract": "intelligence/advisory_contract.py", "gates": PKG + "/runtime/gates.py", "selftest": PKG + "/runtime/selftest.py",
    "store": PKG + "/runtime/store.py", "coordinator": PKG + "/coordinator.py", "const": PKG + "/const.py",
    "sources": PKG + "/runtime/sources.py", "drill_suite": PKG + "/tests/test_install_drill.py", "install": INSTALL_REL,
    "method": METHOD_REL,
}
TOOL_KEYS = {"build_ha_integration.py": "build", "ecco_intel_drill.py": "drill", "power_balance_fit.py": "fit",
             "run_offline_tests.py": "runoff", "deploy-ha-kit.ps1": "deploy", "place-ha-site-file.ps1": "place",
             "ha-status.ps1": "status", "ha-logs.ps1": "logs"}
PY_TOOLS = ("build", "drill", "fit", "runoff")
PS_TOOLS = ("deploy", "place", "status", "logs")
FIXED_SHA = "0000000"                 # the fixed reference commit of the second build (not a commit: a placeholder)
BASE_KIT_SUMS = "47391f0d67144739774034e471486814dae2fd47229a130aae8109968a70ee40"   # the base kit, no commit recorded; not pinned
BASE_GATES_SHA = "659239f3cca7393d3e82b779a504075c9b6291403195923757712016f591305b"  # runtime/gates.py in the base kit (and in U2's)
OPEN_AT_WRITING = ("P1", "P3", "P4", "P5", "P6", "P7", "P9")
CLOSED_AT_WRITING = ("P2", "P8")
OPEN_LIST_TEXT = "P1, P3, P4, P5, P6, P7 and P9"
CHANGED_FILES = ("_vendor/intelligence/site_decisions.py", "_vendor/intelligence/quality.py",
                 "_vendor/intelligence/advisory_contract.py", "runtime/gates.py", "VENDOR_MANIFEST.json")
PKG_ROOT_PY = {"__init__", "binary_sensor", "config_flow", "const", "coordinator", "diagnostics", "entity_base", "sensor"}   # file stems
GO_STEPS = (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
STEP_NUMBERS = tuple(range(15))
FENCE = "`" * 3
MAX_CHECKLIST_LINES = 120
FORBIDDEN_WORDS = ("fully enforced", "guaranteed", "safe to install")
OWNER_QUOTES = (
    "Also keep the diagnosed inverter power-balance correction ready as the following separate update. I want that degradation fixed, "
    "but not bundled into Ghost.",
    "Do not make live changes or restart Home Assistant until Ghost has its final GO.",
)
CHECKLIST_SUBSTANCE = ("following separate update", "but not bundled into Ghost", "before Ghost has its final GO")
COVERAGE = (   # one keyword per bullet of the runbook's section 12 (the checklist's section 8 has each of the first nine)
    "never run in a real home assistant", "l3 (wsl)", "calibrated, not known", "inside the bounds can still hide",
    "sign-reversal protection is measured offline", "degraded", "config-entry reload", "unmeasured",
    "rollback with the facts", "listing commands", "stays shadow", "recalled, not verified",
)
CHECKLIST_COVERAGE = COVERAGE[:9]
TOOL_PHRASES = (   # (the phrase the runbook quotes, [(source key, fragment that proves the tool prints it)])
    ("ECCO INTELLIGENCE KIT UPGRADE PASSED", [("deploy", "ECCO INTELLIGENCE KIT"), ("deploy", "PASSED"), ("deploy", "ToUpperInvariant")]),
    ("RESTART REQUIRED - separately gated, not performed", [("deploy", "RESTART REQUIRED - separately gated, not performed")]),
    ("HA check : passed", [("deploy", "HA check : passed")]),
    ("NO CHANGE", [("deploy", "NO CHANGE"), ("place", "NO CHANGE")]),
    ("ROLLBACK NOT CONFIRMED", [("psm1", "ROLLBACK NOT CONFIRMED")]),
    ("was rolled back", [("psm1", "was rolled back")]),
    ("ECCO SITE FILE PLACED", [("place", "ECCO SITE FILE PLACED")]),
    ("STOPPED", [("place", "STOPPED"), ("psm1", "STOPPED")]),
    ("could NOT be confirmed", [("psm1", "could NOT be confirmed")]),
    ("Takes effect: only at a config-entry reload or a restart, each separately gated; neither was performed",
     [("place", "Takes effect: only at a config-entry reload or a restart, each separately gated; neither was performed")]),
)
FIT_PHRASES = (   # (what the runbook quotes of the fitting tool's report, [fragments of the tool's source that print it])
    ("proposed site facts (the site block of the site file), rounded as entered", ["proposed site facts (the site block of the site file), rounded as entered"]),
    ("NOT USABLE as site facts", ["NOT USABLE as site facts"]),
    ("WARNING", ["WARNING: the loss-aware rule accepts under"]),
    ("loss-aware rule (proposed facts)", ["loss-aware rule (proposed facts)"]),
    ("loss-aware at the bounds (not a fit)", ["loss-aware at the bounds (not a fit)"]),
    ("accepted before the fault", ["accepted before the fault"]),
    ("grid CT sign reversed", ["grid CT sign reversed"]),
    ("battery sign reversed", ["battery sign reversed"]),
    ("second part, loss-aware", ["second part, loss-aware"]),
    ("second part, CT sign reversed", ["second part, {title", "CT sign reversed"]),
)
AUTOMATIC_VARS = {"_", "null", "true", "false", "erroractionpreference", "outputencoding", "lastexitcode", "matches", "args", "env"}
HA_DOMAINS = "sensor|binary_sensor|input_boolean|input_number|input_text|input_select|switch|number|select|button|light|automation|script|climate|cover|fan|lock"
ENTITY_RE = re.compile(r"\b(?:" + HA_DOMAINS + r")\.[a-z0-9_]{2,}\b")
IPV4_RE = re.compile(r"(?<![0-9.])\d{1,3}(?:\.\d{1,3}){3}(?!\d)(?!\.\d)")
TOKEN_RE = re.compile(r"ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{20,}|" + "-" * 5 + r"BEGIN|Bearer\s+[A-Za-z0-9._-]{20,}")
PATH_RE = re.compile(r"\b[A-Za-z]:\\|/[cC]/" + "Users/|(?<![A-Za-z])/" + "Users/|" + r"\\" + "Users" + r"\\")
COMMIT_RE = re.compile(r"(?<![0-9A-Za-z_])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
HEX64_RE = re.compile(r"(?<![0-9A-Za-z_])[0-9a-f]{64}(?![0-9A-Za-z_])")
DECIMAL_RE = re.compile(r"(?<![0-9A-Za-z_.-])\d+\.\d{3,}(?![0-9A-Za-z_])")        # three or more decimals: a calibrated-looking value
TOOL_CALL_RE = re.compile(r"(?<![\w-])tools\\[A-Za-z0-9_.-]+\.(?:py|ps1|psm1)")       # a tool called by its relative path
BARE_R_RE = re.compile(r"(?<![A-Za-z0-9_-])R[1-8](?![A-Za-z0-9_])")                  # R1 to R8: never this runbook's items (RB1 to RB7)

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
    return set(re.findall(r'add_argument\(\s*(?:f)?"(--[a-z][a-z-]*)"', src))


def ps_params(src: str) -> set[str]:
    """The parameter names of the script's own param( ... ) block (a [bool] cast in the code below it is not a parameter)."""
    m = re.search(r"\bparam\((.*?)\n\)", src, re.S)
    return {n.lower() for n in re.findall(r"\[(?:string|switch|int|bool)\]\s*\$(\w+)", m.group(1))} if m else set()


def validate_set(src: str, name: str) -> list[str]:
    m = re.search(r"\[ValidateSet\(([^)]*)\)\]\s*\[string\]\$" + name + r"\b", src)
    return re.findall(r"'([^']+)'", m.group(1)) if m else []


def drill_subcommands(src: str) -> set[str]:
    out = set(re.findall(r'add_parser\("([a-z-]+)"', src))
    m = re.search(r"for name in \(([^)]*)\):", src)
    if m:
        out |= set(re.findall(r'"([a-z-]+)"', m.group(1)))
    return out


def fit_flags(src: str) -> set[str]:
    out = py_flags(src)
    m = re.search(r"ROLES = \(([^)]*)\)", src)
    if m:
        out |= {f"--{r}" for r in re.findall(r'"([a-z]+)"', m.group(1))}
    return out


def commands_of(doc: str) -> list[str]:
    """Every command string of a document: the logical lines of its PowerShell blocks and its inline code spans."""
    out = []
    for b in ps_blocks(doc):
        out += logical_lines(b)
    out += re.findall(r"`([^`\n]+)`", outside_blocks(doc))
    return out


def step_rows(rb: str) -> dict[int, list[str]]:
    return {int(c[0]): c for c in table_rows(section(rb, "7")) if re.fullmatch(r"\d+", c[0])}


def step_where(rows: dict[int, list[str]], cell: int, pattern: str) -> int | None:
    for n in sorted(rows):
        if re.search(pattern, rows[n][cell]):
            return n
    return None


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


def rule_tools(rb, cl, S, F):
    pr = []
    flags = {"build": py_flags(S["build"]), "drill": py_flags(S["drill"]), "fit": fit_flags(S["fit"]), "runoff": py_flags(S["runoff"])}
    subs = {"drill": drill_subcommands(S["drill"]), "fit": set(re.findall(r'add_parser\("([a-z-]+)"', S["fit"]))}
    params = {k: ps_params(S[k]) for k in PS_TOOLS}
    actions = validate_set(S["deploy"], "Action")
    targets = validate_set(S["deploy"], "Target")
    place_targets = validate_set(S["place"], "Target")
    if not (all(flags.values()) and all(subs.values()) and all(params.values()) and actions and targets and place_targets):
        pr.append("the tool sources could not be parsed (no flags, sub-commands, parameters or ValidateSet found)")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for ref in sorted(set(re.findall(r"tools[\\/]([A-Za-z0-9_.-]+\.(?:py|ps1|psm1))", doc))):
            if not ((REPO / "tools" / ref).is_file() or (REPO / "intelligence" / "tools" / ref).is_file()):
                pr.append(f"{label}: tools/{ref} does not exist")
        for val in re.findall(r"-Action\s+([A-Za-z]+)", doc):
            if val not in actions:
                pr.append(f"{label}: -Action {val} is not in the deploy tool's ValidateSet {actions}")
        for val in re.findall(r"-Target\s+([A-Za-z]+)", doc):
            if val not in set(targets) | set(place_targets):
                pr.append(f"{label}: -Target {val} is not in a ValidateSet {targets}")
        for cmd in commands_of(doc):
            for m in re.finditer(r"([A-Za-z0-9_-]+\.(?:py|ps1))", cmd):
                key = TOOL_KEYS.get(m.group(1))
                if key is None:
                    continue
                toks = [t.strip(",;)(][") for t in cmd[m.end():].split(" | ")[0].split() if not t.startswith("<")]
                if key in PY_TOOLS:
                    for t in toks:
                        if t.startswith("--") and t not in flags[key]:
                            pr.append(f"{label}: {m.group(1)} has no flag {t}")
                    if key in subs:
                        first = next((t for t in toks if not t.startswith("-")), None)
                        if first is not None and first not in subs[key]:
                            pr.append(f"{label}: {m.group(1)} has no sub-command {first}")
                else:
                    for t in toks:
                        if re.fullmatch(r"-[A-Za-z][A-Za-z0-9]*", t) and t[1:].lower() not in params[key]:
                            pr.append(f"{label}: {m.group(1)} has no parameter {t}")
    plan_lines = no_plan_lines = 0
    for b in ps_blocks(rb):
        for ln in logical_lines(b):
            m = re.search(r"deploy-ha-kit\.ps1\s+-Action\s+(\w+)", ln)
            if m:
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
            if "place-ha-site-file.ps1" in ln:
                need = ("-SiteFile", "-ExpectedSha256", "-SshHost", "-Target Production", "-ReplaceExistingSha256", "-Python")
                miss = [n for n in need if n not in ln]
                if miss:
                    pr.append(f"runbook: a placement line lacks {miss}")
                if re.search(r"\s-Plan\b", ln):
                    plan_lines += 1
                else:
                    no_plan_lines += 1
            if "build_ha_integration.py" in ln and "--out" in ln:
                m2 = re.search(r"--git-sha\s+(\S+)", ln)
                if m2 and m2.group(1) not in (FIXED_SHA, "(git"):
                    pr.append(f"runbook: --git-sha {m2.group(1)} is neither the fixed reference nor the install commit")
            if "ecco_intel_drill.py" in ln and re.search(r"\sdrill\s", ln):
                if not all(f in ln for f in ("--config-root", "--kit", "--upgrade-kit")):
                    pr.append("runbook: the drill line lacks --config-root, --kit (the previous kit) or --upgrade-kit (this kit)")
            if "ecco_intel_drill.py" in ln and "site-check" in ln and "--site" not in ln:
                pr.append("runbook: the site-check line lacks --site")
            if "power_balance_fit.py" in ln and "ha-history" in ln.split():
                if not all(f in ln for f in ("--house", "--pv", "--battery", "--grid")):
                    pr.append("runbook: the ha-history fit line lacks a role")
    if plan_lines < 2 or no_plan_lines < 2:
        pr.append(f"runbook: the placement is shown with -Plan ({plan_lines}) and without ({no_plan_lines}) fewer than twice each "
                  "(step 9 and RB2)")
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
    for rel in CHANGED_FILES:
        if PKG + "/" + rel not in k["all"]:
            pr.append(f"{rel} is not in the kit")
        if rel.rsplit("/", 1)[-1] not in rb:
            pr.append(f"runbook does not name {rel}")
    if not has(rb, "none new, 5 changed") or not has(rb, "no file is new, none is removed and five change"):
        pr.append("runbook does not say none new, none removed, five changed")
    if not has(cl, "none new, 5 changed"):
        pr.append("checklist does not say none new, 5 changed")
    if len(k["pkg"]) != int(m.group(3)) - 1:
        pr.append("the installed file count is not the kit's less the root manifest")
    if k["nosha"] == k["fixed"]:
        pr.append("the two reference builds are identical (the commit is not recorded)")
    return pr


def rule_numbers(rb, cl, S, F):
    pr = []
    f = source_facts(S, F)
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for what, text in (("the factors' bound", f["factor_text"]), ("the standby bound", f["standby_text"])):
            if not has(doc, text):
                pr.append(f"{label} lacks {what} '{text}'")
        text = P(doc)
        for lo, hi in re.findall(r"\b(\d\.\d+) to (\d\.\d+)\b", text):          # EVERY mention of a bound equals the source's
            if (lo, hi) != (f["lo_f"], f["hi_f"]):
                pr.append(f"{label}: a factor bound {lo} to {hi} is not the source's {f['lo_f']} to {f['hi_f']}")
        for lo, hi in re.findall(r"\b(\d+) to (\d+) W\b", text):
            if (lo, hi) != (f["lo_w"], f["hi_w"]):
                pr.append(f"{label}: a standby bound {lo} to {hi} W is not the source's {f['lo_w']} to {f['hi_w']} W")
        for n in re.findall(r"at least (\d+) %", text):
            if int(n) != f["clean_pct"]:
                pr.append(f"{label}: 'at least {n} %' is not the fit tool's {f['clean_pct']} % bound")
        if not has(doc, f"{f['dis_shift']} W") or not has(doc, f"{f['chg_shift']} W") or not has(doc, f"{f['tol_5kw']} W"):
            pr.append(f"{label} lacks the exposure figures {f['dis_shift']} W, {f['chg_shift']} W and the tolerance {f['tol_5kw']} W at 5 kW")
        for ver in re.findall(r"\bintel-quality-[0-9.]+-cfg\b", doc):
            if ver != f["quality_version"]:
                pr.append(f"{label}: the rule-set version {ver} is not the source's {f['quality_version']}")
    for phrase in (f"{f['dis_factor']} x d + {f['hi_w']} W", f"{f['chg_factor']} x |d| + {f['hi_w']} W", f"the larger of {f['tol_w']} W and {f['tol_pct']} % of the largest magnitude",
                   f"{f['tol_w']} W or {f['tol_pct']} % of the largest magnitude", f["quality_version"]):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    for name in f["fact_names"]:
        if f"`{name}`" not in rb:
            pr.append(f"runbook lacks the fact name `{name}`")
    for code in ("POWER_BALANCE_INCONSISTENT", "CT_SIGN_REVERSED", "BATTERY_SIGN_REVERSED", "POWER_LOSS_FACTS_INVALID"):
        if code not in S["quality"]:
            pr.append(f"the engine does not produce {code}")
        if not re.search(r"(?<![A-Za-z0-9_])" + code + r"(?![A-Za-z0-9_])", rb):
            pr.append(f"runbook does not name {code}")
    if "SITE_INVERTER_CONVERSION" not in S["gates"]:
        pr.append("the loader does not produce SITE_INVERTER_CONVERSION")
    if tuple(f["power_items"]) != ("export_event", "dump_to_grid") or not has(rb, "the export event and Dump to Grid"):
        pr.append(f"the items resting on the balance are {f['power_items']}; the runbook says the export event and Dump to Grid")
    if tuple(f["fact_names"]) != ("inverter_dc_to_ac_factor", "inverter_ac_to_dc_factor", "inverter_standby_w"):
        pr.append(f"the fact names are {f['fact_names']}")
    return pr


def rule_order(rb, cl, S, F):
    pr = []
    for label, rows in (("runbook", {n: " ".join(c) for n, c in step_rows(rb).items()}),
                        ("checklist", {int(c[0]): " ".join(c) for c in table_rows(section(cl, "4")) if re.fullmatch(r"\d+", c[0])})):
        def at(pattern):
            return next((n for n in sorted(rows) if re.search(pattern, rows[n])), None)
        seq = [("the pause", at(r"PAUSE")), ("the Upgrade", at(r"-Action Upgrade")), ("the restart", at(r"\*\*(?:the )?restart\*\*")),
               ("the placement", at(r"place-ha-site-file\.ps1")), ("the reload", at(r"config-entry reload")),
               ("the un-pause", at(r"un-pause|UN-PAUSE"))]
        if any(n is None for _w, n in seq):
            pr.append(f"{label}: a step is missing from the table: {[w for w, n in seq if n is None]}")
        elif [n for _w, n in seq] != sorted(n for _w, n in seq) or len({n for _w, n in seq}) != len(seq):
            pr.append(f"{label}: the steps are not in the order pause, Upgrade, restart, placement, reload, un-pause: {seq}")
    s71 = section(rb, "7.1")
    for phrase in ("The old loader does not refuse the facts", "no order refuses a file or fails a start-up from this cause",
                   "Kit first, one restart, then the facts", "The facts are the loosening step",
                   "last on the way in and go first on the way out", "The facts take effect only at a reload or a restart",
                   "the integration reads the site file at start-up and at a reload only",
                   "The rollback runs the other way", "the facts out first", "then the previous kit, then one restart",
                   "the other order is allowed, not recommended", "the suite prints SKIP for these two checks", "no code in the previous loader rejects"):
        if not has(s71, phrase):
            pr.append(f"runbook 7.1 lacks '{phrase}'")
    if not has(rb, "last in, first out") and not has(cl, "last in, first out"):
        pr.append("neither document says the facts are last in, first out")
    if not has(cl, "the facts are the loosening step") or not has(cl, "the previous kit does not refuse the facts"):
        pr.append("the checklist does not say that the previous kit does not refuse the facts and that the facts are the loosening step")
    if not has(cl, "The facts take effect only at a reload or a restart"):
        pr.append("the checklist does not say the facts take effect only at a reload or a restart")
    # the rollback takes the facts out first: RB2 is the placement, RB4 the kit rollback, RB5 the restart
    items = dict(re.findall(r"^\d+\. \*\*(RB\d)\b(.*?)(?=^\d+\. \*\*RB|\*\*Special cases|\Z)", section(rb, "10"), re.S | re.M))
    if "place-ha-site-file.ps1" not in items.get("RB2", "") or "-Action Rollback" not in items.get("RB4", ""):
        pr.append("RB2 is not the placement of the previous site file, or RB4 is not the kit rollback")
    cl6 = section(cl, "6")
    ia, ib, ic = cl6.find("RB2"), cl6.find("-Action Rollback"), cl6.find("RB5")
    if not (0 <= ia < ib < ic):
        pr.append("the checklist's rollback does not take the facts out (RB2) before the kit (-Action Rollback) and the restart (RB5)")
    # the sources make the reasons true
    if "Takes effect: only at a config-entry reload or a restart" not in S["place"]:
        pr.append("the placement tool no longer says the file takes effect only at a reload or a restart")
    if "Nothing is deleted, Home Assistant is not restarted or reloaded" not in re.sub(r"\s+", " ", S["place"]):
        pr.append("the placement tool no longer says it neither restarts nor reloads Home Assistant")
    if not has(S["install"], "The integration only reads it, at start-up and at a config-entry reload"):
        pr.append("the install runbook no longer says the integration reads the site file at start-up and at a reload")
    pr += F["order_source_problems"](S)
    return pr


def order_source_problems(S) -> list[str]:
    """What makes 'the previous loader does not refuse the facts' true of the new tree: the keys are read by name, nothing iterates or
    refuses the site block's other keys, the reserve hints are the only other keys looked at, and the strict parts are the
    decisions block and the shadow_runtime map."""
    pr = []
    g, sd, so = S["gates"], S["sd"], S["sources"]
    if not re.search(r"conversion_fact\(site, k\) for k in INVERTER_CONVERSION_FACTS\}", g):
        pr.append("the loader no longer reads the three facts by name through conversion_fact")
    if re.search(r"\bsite\.(?:items|keys|values)\(\)|for \w+ in site\b|for \w+ in site_block\b", g):
        pr.append("the loader iterates the site block's keys (an unknown key could be refused or reported)")
    m = re.search(r"def site_hints_ignored\(.*?\n(?=\n\S|\Z)", sd, re.S)
    body = m.group(0) if m else ""
    if 'for k in ("user_reserve_soc_pct", "technical_min_soc_pct")' not in body:
        pr.append("site_hints_ignored no longer looks at exactly the two reserve hints")
    if not re.search(r'block = profile\.get\("decisions"\)', g) or "DecisionSet.from_mapping(block" not in g:
        pr.append("the decisions block is no longer the only block the loader hands to the strict decisions reader")
    if "_strict(profile[MAP_BLOCK]" not in so:
        pr.append("the entity map's strict reader no longer reads only the shadow_runtime block")
    return pr


def rule_no_restart(rb, cl, S, F):
    pr = []
    for label, doc in (("runbook", rb), ("checklist", cl)):
        for b in ps_blocks(doc):
            if re.search(r"(?<!\w)-Restart\b", b) or re.search(r"core restart|reboot|shutdown|\bRestart-[A-Za-z]|\breload\b", b, re.I):
                pr.append(f"{label}: a block restarts, reboots or reloads")
        for span in re.findall(r"`([^`\n]+)`", outside_blocks(doc)):
            if re.search(r"(?<!\w)-Restart\b", span) or re.search(r"core restart|reboot|\bRestart-[A-Za-z]", span, re.I):
                pr.append(f"{label}: an inline command restarts")
    if "restart" in ps_params(S["deploy"]) or "restart" in ps_params(S["place"]) or "reload" in ps_params(S["place"]):
        pr.append("a deploy or placement tool has a restart or reload parameter")
    for key in ("deploy", "place"):
        code = re.sub(r"<#.*?#>", "", S[key], flags=re.S)
        code = "\n".join(ln for ln in code.split("\n") if not ln.strip().startswith("#"))
        if re.search(r"core restart|host reboot|Restart-Computer|Restart-Service|config_entries/reload|homeassistant/restart", code, re.I):
            pr.append(f"the {key} tool sends a restart or reload command")
    for phrase in ("only with the owner's explicit approval, separate from the Upgrade", "no tool in this runbook performs it",
                   "RESTART REQUIRED - separately gated, not performed", "This is the only restart of the update",
                   "Step 10 is a reload of the one config entry and is not a restart", "a reload, not a restart"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    for phrase in ("nothing in this list restarts Home Assistant", "own approval", "a reload, not a restart", "a reload, not a second restart"):
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
    allowed = {k["nosha"], k["fixed"], BASE_KIT_SUMS, BASE_GATES_SHA}
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
        allowed_decimals = {F["facts"]["chg_factor"]}
        site_like = [d for d in DECIMAL_RE.findall(re.sub(HEX64_RE, "", doc)) if d not in allowed_decimals]
        if site_like:
            pr.append(f"{label}: a calibrated-looking number {site_like[0]} (the facts are site values and never enter a repository)")
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
    elif not all(has(p1[1], x) for x in ("WSL", "kit-equivalence", "on the exact kit", "SITE_INVERTER_CONVERSION", "POWER_LOSS_FACTS_INVALID",
                                         "the previous kit restored on the isolated instance loads with a site file that still holds the facts",
                                         "the config-entry reload observed", "-ReferenceSumsSha256", "never on production")):
        pr.append("P1 does not say what the run must show")
    got = open_ids(rb)
    if got != set(OPEN_AT_WRITING):
        pr.append(f"the open preconditions are {sorted(got)}, expected {list(OPEN_AT_WRITING)} (closing one is a deliberate edit of this suite)")
    closed = sorted(c[0] for c in table_rows(sec) if re.fullmatch(r"P\d+", c[0]) and P(c[-1]).lower().startswith("closed"))
    if closed != sorted(CLOSED_AT_WRITING):
        pr.append(f"the closed preconditions are {closed}, expected {list(CLOSED_AT_WRITING)} (closing or reopening one is a deliberate edit of this suite)")
    rows = {c[0]: " ".join(c) for c in table_rows(sec) if re.fullmatch(r"P\d+", c[0])}
    for pid, words in (("P2", ("one independent review", "no BLOCKER", "one MAJOR", "five minors", "all fixed in a follow-up round")),
                       ("P6", ("U2 (Ghost) installed and verified first", "never both in one window", "section 3")),
                       ("P8", ("repeated in full at step 0", "the drills of 8.0", "the deploy suite"))):
        for w in words:
            if not has(rows.get(pid, ""), w):
                pr.append(f"{pid} lacks '{w}'")
    if not has(rb, "NOT READY") or not has(rb, OPEN_LIST_TEXT):
        pr.append("the runbook's status does not say NOT READY and list the open preconditions")
    c1 = section(cl, "1")
    if not has(c1, "NOT yet ready") or not has(c1, OPEN_LIST_TEXT):
        pr.append("the checklist does not say NOT yet ready and list the open preconditions")
    for phrase in ("L3 (WSL) kit-equivalence reference run", "SITE_INVERTER_CONVERSION", "exact kit", "Closed:", "P2", "P8"):
        if not has(c1, phrase):
            pr.append(f"the checklist's answer lacks '{phrase}'")
    for needle in ("independent review", "CI", "M2", "U2"):
        if not has(sec, needle):
            pr.append(f"the preconditions do not name {needle}")
    return pr


def rule_steps(rb, cl, S, F):
    pr = []
    rr = step_rows(rb)
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
    for n, what in ((7, "the restart"), (10, "the config-entry reload")):
        sep = "separate from the Upgrade" if n == 7 else "separate from the placement"
        if n in rr and not (has(rr[n][5], "own approval") and has(rr[n][5], sep) and has(rr[n][1], what)):
            pr.append(f"runbook step {n} is not {what} with its own separate approval")
        if n in cr and not (any("own approval" in c for c in cr[n]) and has(" ".join(cr[n]), what)):
            pr.append(f"checklist step {n} is not {what} with its own approval")
    if 3 in rr and not has(rr[3][1], "pause helper"):
        pr.append("runbook step 3 is not the pause")
    if 1 in rr and not all(has(rr[1][1], x) for x in ("listing", "hashes and sizes", "diagnostics download", "site file's sha256")):
        pr.append("runbook step 1 lacks the listing, hashes and sizes, the site file's sha256 or the download")
    if 4 in rr and not has(rr[4][1], "hash and size"):
        pr.append("runbook step 4 lacks the scorecard file's hash and size")
    if 5 in rr and not (has(rr[5][1], "-Action Plan") and has(rr[5][1], "-Action Upgrade")):
        pr.append("runbook step 5 does not name Plan and Upgrade")
    if 5 in cr and not (has(" ".join(cr[5]), "-Action Plan") and has(" ".join(cr[5]), "-Action Upgrade")):
        pr.append("checklist step 5 does not name Plan and Upgrade")
    if 9 in rr and not (has(rr[9][1], "place-ha-site-file.ps1 -Plan") and has(rr[9][1], "the placement")):
        pr.append("runbook step 9 is not the Plan and the placement")
    if 9 in cr and not has(" ".join(cr[9]), "place-ha-site-file.ps1 -Plan"):
        pr.append("checklist step 9 does not name the placement tool's Plan")
    if 8 in rr and not (has(rr[8][1], "site file unchanged") and has(rr[8][6], "no SITE_INVERTER_CONVERSION line")):
        pr.append("runbook step 8 is not the kit-alone checkpoint (no SITE_INVERTER_CONVERSION line)")
    if 11 in rr and not has(rr[11][6], "SITE_INVERTER_CONVERSION PASS"):
        pr.append("runbook step 11 does not expect SITE_INVERTER_CONVERSION PASS")
    if 2 in rr and not has(rr[2][1], "protected full backup"):
        pr.append("runbook step 2 is not the protected backup")
    return pr


def rule_rollback(rb, cl, S, F):
    pr = []
    s10 = section(rb, "10")
    items = re.findall(r"^\d+\. \*\*(RB\d)\b(.*?)(?=^\d+\. \*\*RB|\*\*Special cases|\Z)", s10, re.S | re.M)
    if [i[0] for i in items] != [f"RB{n}" for n in range(1, 8)]:
        pr.append(f"the runbook's rollback items are {[i[0] for i in items]}")
    for name, body in items:
        if "Proof" not in body:
            pr.append(f"runbook {name} has no proof")
    order = re.findall(r"\*\*(RB\d)\b", section(cl, "6"))
    if order != [f"RB{n}" for n in range(1, 8)]:
        pr.append(f"the checklist's rollback order is {order}")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        if not has(doc, "-Action Rollback -BackupStamp"):
            pr.append(f"{label} lacks the rollback command with its stamp")
        bare = sorted(set(BARE_R_RE.findall(P(doc))))
        if bare:
            pr.append(f"{label}: bare R-number citation(s) {bare}: this runbook's items are RB1 to RB7 and an install-runbook item is named in full")
        for phrase in ("heavy last resort", "never the first rollback"):
            if not has(doc, phrase):
                pr.append(f"{label} lacks '{phrase}' (the protected backup restore)")
    if not has(s10, "against the baseline") or not has(s10, "the owner's protected full backup"):
        pr.append("the runbook's rollback is not measured against the baseline and the protected backup")
    for phrase in ("A facts-only rollback (the kit stays) is RB1, RB2, RB3 and RB6", "A full rollback is RB1, RB2, RB4, RB5 and RB6",
                   "The facts go out first, and the previous kit second"):
        if not has(s10, phrase):
            pr.append(f"the runbook's section 10 lacks '{phrase}'")
    for phrase in ("A full rollback needs one restart; a facts-only rollback needs none", "The facts go out first, the previous kit second"):
        if not has(section(cl, "6"), phrase):
            pr.append(f"the checklist's rollback lacks '{phrase}'")
    if not has(s10, "install runbook's section 7 go / no-go for the first observed runs"):
        pr.append("RB6 does not name the install runbook's first-run go / no-go in full")
    if "*S6," not in s10 or "*S7," not in s10 or "*S8," not in s10:
        pr.append("the runbook's special cases lack S6, S7 or S8")
    for phrase in ("before the restart of step 7", "the old code is still running", "RB5 applies", "ask the owner", "recalled, not verified",
                   "whether RB5 is then needed is S6's question"):
        if not has(s10, phrase):
            pr.append(f"the runbook's section 10 lacks '{phrase}' (the rollback before any restart)")
    if not (has(section(cl, "6"), "before the restart of step 7") and re.search(r"\bS6\b", section(cl, "6"))):
        pr.append("the checklist's rollback does not say that a rollback before the restart of step 7 leaves RB5 to the owner (S6)")
    return pr


def rule_decisions(rb, cl, S, F):
    pr = []
    f = source_facts(S, F)
    for label, sec in (("runbook", section(rb, "4")), ("checklist", section(cl, "3"))):
        rows = {c[0]: c for c in table_rows(sec) if re.fullmatch(r"D-U3-\d", c[0])}
        if sorted(rows) != [f"D-U3-{i}" for i in range(1, 10)]:
            pr.append(f"{label}: the items are {sorted(rows)}")
        for k, cells in rows.items():
            if not P(cells[-1]).lower().startswith("open"):
                pr.append(f"{label}: {k} is not open")
        for k, words in (("D-U3-5", (f"{f['clean_pct']} %",)), ("D-U3-6", ("season",)), ("D-U3-7", ("DEGRADED",)),
                         ("D-U3-8", ("legacy",)), ("D-U3-9", (f["factor_text"], f["standby_text"]))):
            if k in rows and not all(w in " ".join(rows[k]) for w in words):
                pr.append(f"{label}: {k} lacks {words}")
    if not has(rb, "it decides none") or not has(cl, "I decide none"):
        pr.append("the documents do not say they decide none of the items")
    if has(rb, "CLEAN_SHARE_WARN") and "CLEAN_SHARE_WARN" not in S["fit"]:
        pr.append("the fit tool has no CLEAN_SHARE_WARN")
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
    for phrase in ("No entity, helper, service, package or dashboard is created or edited by this update", "eleven entities", "RG-F3"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    if not has(cl, "No entity, helper or service is created") or not has(cl, "RG-F3"):
        pr.append("checklist lacks the no-entity statement or RG-F3")
    return pr


WRITE_RE = re.compile(r"\bopen\(|\.write\(|write_text|write_bytes|sqlite3|os\.(?:replace|rename|remove|unlink|makedirs|mkdir)|shutil\.|"
                      r"\.execute\(|\.commit\(|subprocess|urllib|socket|requests")


def rule_no_write(rb, cl, S, F):
    pr = []
    for key in ("gates", "sd", "quality", "contract"):
        hit = WRITE_RE.search(re.sub(r'"""(?:.|\n)*?"""|#.*', "", S[key]))
        if hit:
            pr.append(f"the changed kit source {key} holds a file, database or network call ({hit.group(0)})")
    if re.search(r"inverter_|SITE_INVERTER|INVERTER_CONVERSION", S["store"]):
        pr.append("the store (the only writer) names the inverter facts")
    for phrase in ("adds no table, column or row type", "contain no file, database or network write", "It adds no durable write"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    if not has(cl, "No table, column or row type is added"):
        pr.append("checklist lacks 'No table, column or row type is added'")
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
        if k not in r12:
            pr.append(f"the runbook's section 12 lacks '{k}'")
    for k in CHECKLIST_COVERAGE:
        if k not in c8:
            pr.append(f"the checklist's section 8 lacks '{k}'")
    if len(bullets) < len(COVERAGE) - 2:
        pr.append(f"the runbook's section 12 has only {len(bullets)} bullets")
    return pr


def rule_drill(rb, cl, S, F):
    pr = []
    for phrase in ("What the drill proves, exactly", "byte-identical", "synthetic site file that holds the three facts",
                   "does not run the previous integration as a whole", "is exercised against a stand-in host by", "not the production host"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
    if "site.local.json, state/ and the other integration untouched by every step" not in S["drill_suite"]:
        pr.append("the drill suite no longer has the check the runbook relies on")
    if '"ecco/intelligence/site.local.json"' not in S["drill"] or '"ecco/intelligence/state"' not in S["drill"]:
        pr.append("the drill tool no longer protects the site file and the state folder")
    if "# 21. place-ha-site-file.ps1" not in S["deploy_suite"]:
        pr.append("the deploy suite no longer exercises place-ha-site-file.ps1 against a stand-in host (the runbook says it does)")
    d = F["drill"]
    if not d.get("ok"):
        pr.append(f"the real drill on a site file with the facts failed: {d.get('detail')}")
    sc = F["site_check"]
    if sc.get("problems"):
        pr.append(f"the real site-check does not give the output the runbook quotes: {sc['problems']}")
    for phrase in ("PASS  SITE_INVERTER_CONVERSION", "Result      : OK", "exit 0"):
        if not has(rb, phrase):
            pr.append(f"runbook does not quote '{phrase}'")
    return pr


def rule_phrases(rb, cl, S, F):
    pr = []
    for phrase, proofs in TOOL_PHRASES:
        if not has_cs(rb, phrase):
            pr.append(f"runbook does not quote '{phrase}'")
        for key, frag in proofs:
            if not has_cs(S[key], frag):
                pr.append(f"{key} does not print '{frag}'")
    if not has_cs(cl, "ECCO INTELLIGENCE KIT UPGRADE PASSED") or not has_cs(cl, "ECCO SITE FILE PLACED"):
        pr.append("checklist does not quote the Upgrade's PASSED line or the placement's PLACED line")
    blocks = "\n".join(ps_blocks(rb))
    for line in ("INSTALLED TREE EQUALS THE KIT", "THE SITE FILE ON THE HOST IS THE PLACED ONE", "THE OFFLINE COPY EQUALS THE SITE FILE ON THE HOST"):
        if line not in blocks:
            pr.append(f"no runbook block prints {line}")
    if not has(rb, F["kit"]["line"].split(";")[0]):
        pr.append("runbook does not quote the build tool's line")
    for frag in ("built ", "SHA256SUMS sha256"):
        if frag not in S["build"]:
            pr.append(f"the build tool does not print '{frag}'")
    if "c.level if c.level == PASS else" not in S["selftest"]:
        pr.append("the self-test export no longer returns only the level for a passing check (the runbook says the download shows the single word PASS)")
    if not re.search(r'_LOGGER\.debug\("ECCO Intelligence start-up check %s: %s"', S["coordinator"]):
        pr.append("the fact names and reasons of an invalid set no longer go to the debug log only (the runbook says so)")
    for phrase in ("the download shows a passing check as the single word PASS", "go to the debug log only"):
        if not has(rb, phrase):
            pr.append(f"runbook lacks '{phrase}'")
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
    method_heads = {n for _h, n in headings(S["method"])}
    for m in re.finditer(r"\bsection (\d+(?:\.\d+)?)", rb):
        before = rb[max(0, m.start() - 70):m.start()]
        if "install runbook" in before:
            continue                                               # the install runbook's own sections are checked above
        if "DATA_QUALITY_METHOD" in before or "method document" in before:
            if m.group(1) not in method_heads:
                pr.append(f"the runbook cites the method document's section {m.group(1)}, which has no heading")
        elif m.group(1) not in heads:
            pr.append(f"the runbook cites its section {m.group(1)}, which has no heading")
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


def rule_write_statement(rb, cl, S, F):
    pr = []
    for label, text in (("runbook 2.4", section(rb, "2.4")), ("checklist 2", section(cl, "2"))):
        site_phrase = "the site file (A2" if label == "runbook 2.4" else "the site file (replaced by your new file)"
        for phrase in ("the integration folder", site_phrase, "the staging and backup folders", "state folder", "pause helper"):
            if not has(text, phrase):
                pr.append(f"{label} does not list '{phrase}' among the writes")
    for phrase in ("and nothing in the state folder",):
        if not has(section(rb, "2.4"), phrase) or not has(section(cl, "2"), "and nothing in the state folder"):
            pr.append(f"the write statement lacks '{phrase}'")
    for label, doc in (("runbook", rb), ("checklist", cl)):
        if has(doc, "only write outside the scorecard file"):
            pr.append(f"{label} says the only write outside the scorecard file is the pause helper")
    return pr


def rule_data_quality(rb, cl, S, F):
    pr = []
    q = S["quality"]
    if not re.search(r"elif c\.blocked or any\(f\.severity in \(BLOCK, WARN\) for f in c\.findings\):\s*\n\s*dq = DataQuality\.DEGRADED", q):
        pr.append("the engine's DEGRADED rule is no longer 'any item blocked or any WARN or BLOCK finding' (the runbook states it)")
    if not has(S["method"], "Clearing the balance BLOCK does not by itself make data_quality OK"):
        pr.append("the method document no longer says clearing the balance block does not by itself make data quality OK")
    s813 = section(rb, "8.13")
    for phrase in ("It may stay DEGRADED", "any item is blocked or any finding is a WARN or a BLOCK", "What to read next", "reason_codes",
                   "Never loosen a rule and never edit a fact to reach OK", "is not a failure of this update",
                   "The success criterion is the absence of the balance blocker while the inputs are fresh, not a number on the outputs",
                   "Read while PV or battery power is large"):
        if not has(s813, phrase):
            pr.append(f"runbook 8.13 lacks '{phrase}'")
    if not any(has(" ".join(c), "stays DEGRADED") and has(" ".join(c), "D-U3-7") for c in table_rows(section(rb, "11"))):
        pr.append("section 11 has no row for data quality that stays DEGRADED")
    for phrase in ("data quality may return to OK or stay DEGRADED", "any other open warning keeps it so"):
        if not has(section(cl, "2"), phrase):
            pr.append(f"the checklist's section 2 lacks '{phrase}'")
    if not has(section(cl, "5"), "data quality OK or its codes read"):
        pr.append("the checklist's verification does not say data quality is OK or its codes are read")
    return pr


def rule_fit_rows(rb, cl, S, F):
    pr = []
    s80 = section(rb, "8.0")
    for phrase, frags in FIT_PHRASES:
        if not has_cs(s80, phrase):
            pr.append(f"runbook 8.0 does not quote the fit tool's '{phrase}'")
        for frag in frags:
            if not has_cs(S["fit"], frag):
                pr.append(f"the fit tool does not print '{frag}'")
    for phrase in ("the fault-injection rows", "the hold-out rows", "stays in <OFFLINE_EVIDENCE_DIR>", "entered in a copy of the site file",
                   "the facts are not used", "at least 99 %"):
        if not has(s80, phrase):
            pr.append(f"runbook 8.0 lacks '{phrase}'")
    for frag in ("(c) FAULT INJECTION", "(d) HOLD-OUT", "(a) FITTED PARAMETERS", "(b) SHARE OF SAMPLES THE ENGINE ACCEPTS"):
        if frag not in S["fit"]:
            pr.append(f"the fit tool no longer prints its part '{frag}'")
    for phrase in ("Part (a)", "Part (b)", "Part (c)", "Part (d)"):
        if not has(s80, phrase):
            pr.append(f"runbook 8.0 does not name the fit tool's {phrase}")
    return pr


def rule_rollback_reads(rb, cl, S, F):
    """Section 10's proofs name real reads, and what the runbook says about the rollback command is what the deploy tool does."""
    pr = []
    s10 = section(rb, "10")
    items = dict(re.findall(r"^\d+\. \*\*(RB\d)\b(.*?)(?=^\d+\. \*\*RB|\*\*Special cases|\Z)", s10, re.S | re.M))
    rb1, rb2, rb3, rb4, rb5 = (items.get(f"RB{i}", "") for i in range(1, 6))
    blocks = "\n".join(ps_blocks(rb))
    if not has(rb1, "the block of 8.4"):
        pr.append("RB1's proof does not name the paused read of 8.4")
    for phrase in ("ECCO SITE FILE PLACED", "the read-back equal to the baseline's sha256", "site-file-sha-before.txt", "-ReplaceExistingSha256",
                   "needs <checkout> clean"):
        if not has(rb2, phrase):
            pr.append(f"RB2 lacks '{phrase}'")
    for phrase in ("only when the kit stays", "SITE_INVERTER_CONVERSION is absent", "config_hash equals the baseline's"):
        if not has(rb3, phrase):
            pr.append(f"RB3 lacks '{phrase}'")
    for phrase in ("needs <checkout> clean", "it refuses a dirty working tree", "runs the repository validation", "with -Python before it sends anything",
                   "-SkipValidation is never used", "compares the site file and the state folder before and after",
                   "rolls itself back if they changed", "this is why RB1 comes first", "Restored names the backup's file count"):
        if not has(rb4, phrase):
            pr.append(f"RB4 lacks '{phrase}'")
    m81 = re.search(r"it must be (\d+) if the installed kit is the merged base's and (\d+) if it\s+is U2's", P(rb))
    if m81 is None or not has(rb4, f"{m81.group(1)} if the installed kit was the merged base's and {m81.group(2)} if it was U2's"):
        pr.append("RB4 does not give the file counts the baseline's block 1 (8.1) gives")
    for phrase in ("the block of 8.8", "diagnostics-rollback.json", "SITE_INVERTER_CONVERSION None", "self_test FAIL []", "diagnostics-before.json"):
        if not has(rb5, phrase):
            pr.append(f"RB5's proof lacks '{phrase}' (the load-check read of 8.8 on the rollback download, against the baseline download)")
    for frag in ("SITE_INVERTER_CONVERSION", "self_test FAIL"):
        if frag not in blocks:
            pr.append(f"no runbook block prints '{frag}' (RB5 relies on the block of 8.8)")
    if not has(rb, "its To undo line repeats the rollback command with the stamp in it, but without -Python"):
        pr.append("the runbook (8.5) does not say that the To undo line repeats the rollback command with the stamp but without -Python")
    d, m, pl = S["deploy"], S["psm1"], S["place"]
    m_common = re.search(r'\$common = "([^"]*)"', d)
    if m_common is None or "-Python" in m_common.group(1):
        pr.append("the deploy tool's To undo line carries -Python now (8.5 says it is without -Python)")
    if not re.search(r"^Assert-EccoCleanWorkingTree -RepoRoot \$repoRoot\s*$", d, re.M) or not re.search(r"^Assert-EccoCleanWorkingTree -RepoRoot \$repoRoot\s*$", pl, re.M):
        pr.append("a deploy or placement tool does not check the working tree (the runbook says it refuses a dirty one)")
    if not (re.search(r"if \(-not \$SkipValidation\) \{", d) and "validate-ecco.ps1" in d and "-Python $Python" in d):
        pr.append("the deploy tool does not run the repository validation with -Python unless -SkipValidation is given")
    if not re.search(r"To undo\s+: \.\\tools\\deploy-ha-kit\.ps1 -Action Rollback -BackupStamp \$runStamp", d):
        pr.append("the deploy tool does not print a To undo line with the Rollback command and the stamp")
    if not re.search(r"Restored\s+: \$\(@\(\$restoreFiles\.Keys\)\.Count\) files from", d):
        pr.append("the deploy tool does not print a Restored line with the file count of the backup")
    if "the protected site file or state folder changed during the write" not in m or "Invoke-EccoKitRollback @rollback -Reason $failure" not in m:
        pr.append("the kit write no longer compares the protected snapshot and rolls itself back when it changed")
    if "ha core check" not in m:
        pr.append("the kit write no longer runs ha core check")
    if "to replace it, pass -ReplaceExistingSha256 with its full sha256" not in pl or "does not match the site file on the host" not in pl:
        pr.append("the placement tool no longer refuses a replacement without the live file's sha256 (the runbook says it does)")
    if "Read back   : sha256" not in pl or "- matches -ExpectedSha256" not in pl:
        pr.append("the placement tool no longer prints the read-back against -ExpectedSha256")
    return pr


RULES = {
    "shape": rule_shape, "tools": rule_tools, "kit": rule_kit, "numbers": rule_numbers, "order": rule_order,
    "no_restart": rule_no_restart, "cls": rule_cls, "quotes": rule_quotes, "sentences": rule_sentences, "forbidden": rule_forbidden,
    "preconditions": rule_preconditions, "steps": rule_steps, "rollback": rule_rollback, "decisions": rule_decisions,
    "no_entity": rule_no_entity, "no_write": rule_no_write, "coverage": rule_coverage, "drill": rule_drill, "phrases": rule_phrases,
    "vars": rule_vars, "cites": rule_cites, "workdir": rule_workdir, "write_statement": rule_write_statement,
    "data_quality": rule_data_quality, "fit_rows": rule_fit_rows, "rollback_reads": rule_rollback_reads,
}
RULE_TITLES = {
    "shape": "[1] both documents exist, are ASCII, the checklist has at most 120 lines, sections 1 to 12 and 1 to 8",
    "tools": "[2] every tool, flag, parameter, -Action, -Target and sub-command a command names exists; the Plan, Upgrade, Rollback and placement lines carry the right flags",
    "kit": "[3] the two builds' hashes, the file counts and the five changed files are the documents'",
    "numbers": "[4] the bounds, fact names, tolerance, exposure figures, rule-set version and blocker codes are the sources'; no calibrated-looking number",
    "order": "[5] kit, one restart, placement, reload, un-pause; the rollback takes the facts out first; the reasons are stated and true of the sources",
    "no_restart": "[6] no automatic restart or reload: the restart is the owner's, once; the reload is its own approval and is not a restart",
    "cls": "[7] every PowerShell block starts with cls",
    "quotes": "[8] the owner's words are in the runbook, their substance in the checklist",
    "sentences": "[9] no automatic installation or live access is authorised; never run in a real Home Assistant",
    "forbidden": "[10] none of the three forbidden phrases, an entity id, an address, a token, a workstation path, a commit id, an unexplained hash or a calibrated-looking number",
    "preconditions": "[11] P1 (the L3 WSL run on the exact kit) is OPEN and says what it must show; the open and closed sets are exact and agree in both documents",
    "steps": "[12] the same steps and who in both, an owner go at each live step, the restart and the reload each with their own approval",
    "rollback": "[13] RB1 to RB7 in order in both, a proof for each, the two sequences, the commands, the heavy last resort, S6 to S8",
    "decisions": "[14] D-U3-1 to D-U3-9 are open in both",
    "no_entity": "[15] the update creates no entity: the platforms, eleven contract entities, the package's file set",
    "no_write": "[16] the changed kit sources write nothing, the store does not name the facts, and the documents say no table is added",
    "coverage": "[17] every bullet of 'what is NOT established' has a keyword, and the checklist says each",
    "drill": "[18] the drill's statement is made and true: the real drill leaves the site file and the state folder byte-identical; the real site-check prints the quoted lines",
    "phrases": "[19] the tool phrases the runbook quotes are printed by the tools",
    "vars": "[20] every PowerShell block sets the variables it uses",
    "cites": "[21] every section and install-runbook section or row the documents cite exists",
    "workdir": "[22] every PowerShell block that calls a tool under tools/ sets its working folder first",
    "write_statement": "[23] the runbook and the checklist list the same writes",
    "data_quality": "[24] data quality may stay DEGRADED: the engine's rule is the one stated, and what to read next is said",
    "fit_rows": "[25] the fit tool's rows the owner reads exist in the tool's source",
    "rollback_reads": "[26] the rollback proofs name real reads (8.4, 8.8, the placement's read-back) and what the runbook says the tools do is what they do",
}


def analyse(rb, cl, S, F):
    return {name: fn(rb, cl, S, F) for name, fn in RULES.items()}


def fired(result: dict) -> set[str]:
    return {k for k, v in result.items() if v}


# ---------------------------------------------------------------------------------------------------------------------
# facts from the sources, the kit build, the real drill and the old tree
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
    from intelligence import quality as q
    from intelligence import site_decisions as sd
    const_src = read_src(SOURCES["const"])
    consts = re.search(r"PLATFORMS = \(([^)]*)\)", const_src)
    lo_f, hi_f = sd.INVERTER_FACTOR_BOUNDS
    lo_w, hi_w = sd.INVERTER_STANDBY_BOUNDS_W
    tol_w, tol_frac = sd.PROPOSED.power_agree_w, sd.PROPOSED.power_agree_fraction
    return {
        **bound_facts(lo_f, hi_f, lo_w, hi_w, tol_w, tol_frac),
        "fact_names": tuple(sd.INVERTER_CONVERSION_FACTS), "quality_version": q.QUALITY_VERSION, "power_items": tuple(q.POWER_ITEMS),
        "clean_pct": clean_pct(read_src(SOURCES["fit"])),
        "entities": len(ac.INTEGRATION_ENTITY_KEYS),
        "platforms": tuple(re.findall(r'"(\w+)"', consts.group(1))) if consts else (),
    }


def bound_facts(lo_f: float, hi_f: float, lo_w: float, hi_w: float, tol_w: float, tol_frac: float) -> dict:
    """The numbers the documents state, derived from the bounds and the tolerance (the exposure at 5 kW of net DC-side power)."""
    return {
        "lo_f": f"{lo_f:.2f}", "hi_f": f"{hi_f:.1f}", "lo_w": f"{lo_w:g}", "hi_w": f"{hi_w:g}",
        "factor_text": f"{lo_f:.2f} to {hi_f:.1f}", "standby_text": f"{lo_w:g} to {hi_w:g} W",
        "tol_w": f"{tol_w:g}", "tol_pct": f"{tol_frac * 100:g}", "dis_factor": f"{round(1 - lo_f, 3):g}",
        "chg_factor": f"{round(1 / lo_f - 1, 3):.3f}",
        "dis_shift": f"{round(5000 * (1 - lo_f) + hi_w):g}", "chg_shift": f"{round(5000 * (1 / lo_f - 1) + hi_w):g}",
        "tol_5kw": f"{max(tol_w, tol_frac * 5000):g}",
    }


def clean_pct(fit_src: str) -> int:
    m = re.search(r"CLEAN_SHARE_WARN = ([0-9.]+)", fit_src)
    return round(float(m.group(1)) * 100) if m else -1


def source_facts(S, F) -> dict:
    """F's facts with the bounds and the acceptance share read from the (possibly mutated) sources the rule is given."""
    f = dict(F["facts"])
    m = re.search(r"INVERTER_FACTOR_BOUNDS = \(([0-9.]+), ([0-9.]+)\)", S["sd"])
    w = re.search(r"INVERTER_STANDBY_BOUNDS_W = \(([0-9.]+), ([0-9.]+)\)", S["sd"])
    if m and w:
        f.update(bound_facts(float(m.group(1)), float(m.group(2)), float(w.group(1)), float(w.group(2)),
                             float(F["facts"]["tol_w"]), float(F["facts"]["tol_pct"]) / 100))
    f["clean_pct"] = clean_pct(S["fit"])
    return f


def synthetic_site(extra: dict | None, drill_mod) -> bytes:
    readings = {k: v for k, v in H.READING_MAP.items() if k not in drill_mod.V01_UNMAPPED_READINGS}
    p = H.site_profile(decisions=H.owner_decisions(), readings=readings)
    p["site"].update(extra or {})
    return json.dumps(p, indent=1).encode("utf-8")


GOOD_FACTS = {"inverter_dc_to_ac_factor": 0.92, "inverter_ac_to_dc_factor": 0.94, "inverter_standby_w": 40}     # synthetic, round
BAD_FACTS = {"inverter_dc_to_ac_factor": 0.5, "inverter_ac_to_dc_factor": 0.94, "inverter_standby_w": 40}


def load_drill_module():
    spec = importlib.util.spec_from_file_location("ecco_intel_drill_pb", REPO / "tools" / "ecco_intel_drill.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ecco_intel_drill_pb"] = mod
    spec.loader.exec_module(mod)
    return mod


def site_check_facts(D) -> dict:
    """The real site-check on a file with no facts, valid facts and invalid facts: the lines the runbook quotes."""
    problems = []
    none = D.site_check_report(synthetic_site(None, D), "none.json")
    good = D.site_check_report(synthetic_site(GOOD_FACTS, D), "good.json")
    bad = D.site_check_report(synthetic_site(BAD_FACTS, D), "bad.json")
    code = "SITE_INVERTER_CONVERSION"
    if any(c["code"] == code for c in none["checks"]) or none["result"] != "OK":
        problems.append("a file with no facts must give no SITE_INVERTER_CONVERSION check and Result OK")
    text = D.render_site_check(good)
    if good["result"] != "OK" or "PASS  " + code not in text or "Result      : OK" not in text:
        problems.append("a file with valid facts must print 'PASS  SITE_INVERTER_CONVERSION' and 'Result      : OK'")
    for item in ("export_event", "dump_to_grid"):
        if "POWER_LOSS_FACTS_INVALID" in good["items"][item]["blockers"]:
            problems.append(f"valid facts block {item}")
        if "POWER_LOSS_FACTS_INVALID" not in bad["items"][item]["blockers"]:
            problems.append(f"invalid facts do not block {item} with POWER_LOSS_FACTS_INVALID")
    if bad["result"] != "PROBLEMS" or not any(c["code"] == code and c["level"] == "WARN" for c in bad["checks"]):
        problems.append("invalid facts must give a WARN check and PROBLEMS")
    return {"problems": problems}


def run_real_drill(base: Path, kit_a: Path, D) -> dict:
    """The repository's own drill, on a marked mock root: install a synthetic PREVIOUS kit, place a synthetic site file that holds the
    facts (a file copy: the placement tool needs ssh), upgrade to the real kit, roll back, uninstall."""
    kit_p = base / "kit_prev"
    shutil.copytree(kit_a, kit_p)
    target = kit_p / PKG / "runtime" / "selftest.py"
    target.write_bytes(target.read_bytes() + b"\n# a synthetic previous kit\n")
    sums = "".join(f"{hashlib.sha256((kit_p / rel).read_bytes()).hexdigest()}  {rel}\n"
                   for rel in sorted(k for k in H.tree_hashes(kit_p) if not k.endswith("/") and k != "SHA256SUMS"))
    (kit_p / "SHA256SUMS").write_bytes(sums.encode("utf-8"))
    root = base / "mock"
    state = root / "ecco" / "intelligence" / "state"
    state.mkdir(parents=True)
    site = root / "ecco" / "intelligence" / "site.local.json"
    site.write_bytes(synthetic_site(None, D))
    (state / "scorecard.sqlite3").write_bytes(b"synthetic scorecard bytes\n")
    (state / "store_meta.json").write_text('{"synthetic": true}\n', encoding="utf-8")
    (root / "custom_components" / "other_integration").mkdir(parents=True)
    (root / "custom_components" / "other_integration" / "__init__.py").write_text("# another integration\n", encoding="utf-8")
    (root / D.MARKER).write_text("mock\n", encoding="utf-8")

    def keep() -> dict:
        return {k: v for k, v in H.tree_hashes(root).items() if k.startswith(("ecco/intelligence/", "custom_components/other_integration"))
                and k != "ecco/intelligence/site.local.json"}

    d = D.Drill(D.mock_root(str(root)), log=lambda *_: None)
    try:
        d.install(kit_p, "20300115-120000")
        before_state = keep()
        site.write_bytes(synthetic_site(GOOD_FACTS, D))          # the placement (a file copy on the mock root)
        placed = site.read_bytes()
        d.install(kit_a, "20300115-120001", upgrade=True)
        d.rollback("20300115-120002", "20300115-120001")
        pkg_p = {k[len(D.KIT_PREFIX):]: v for k, v in D.read_sums(kit_p / "SHA256SUMS").items() if k.startswith(D.KIT_PREFIX)}
        back = {k: v for k, v in D.tree(d.installed, D.IGNORED_IN_PLACE).items()}
        same_tree = back == pkg_p
        d.uninstall("20300115-120003")
    except D.DrillError as exc:
        return {"ok": False, "detail": f"the drill stopped: {exc}"}
    ok = (keep() == before_state and site.read_bytes() == placed and same_tree and all(s[0] == "PASS" for s in d.steps) and len(d.steps) > 20)
    return {"ok": ok, "detail": f"{len(d.steps)} steps, state unchanged: {keep() == before_state}, site file unchanged: {site.read_bytes() == placed}, "
                                f"tree after the rollback is the previous kit's: {same_tree}"}


OLD_PROBE = r'''
import json, sys
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "custom_components" / "ecco_intelligence" / "tests"))
sys.path.insert(2, str(ROOT / "intelligence" / "tests"))
import _harness as H
from custom_components.ecco_intelligence.runtime import gates
def load(extra):
    p = H.site_profile(decisions=H.owner_decisions(), readings=H.READING_MAP)
    p["site"].update(extra)
    sl = gates.load_site(json.dumps(p).encode(), latitude=51.5, longitude=-0.1)
    return {"checks": [[c.code, c.level, c.text] for c in sl.checks],
            "decisions": sorted(sl.decisions.status_map().items()) if sl.decisions is not None else None,
            "entities": len(sl.entity_map.entity_ids()), "kwp": sl.site_facts.pv_array_kwp}
V = {"none": {}, "valid": {"inverter_dc_to_ac_factor": 0.92, "inverter_ac_to_dc_factor": 0.94, "inverter_standby_w": 40},
     "partial": {"inverter_dc_to_ac_factor": 0.92}, "bounds": {"inverter_dc_to_ac_factor": 0.5, "inverter_ac_to_dc_factor": 1.5, "inverter_standby_w": 900},
     "types": {"inverter_dc_to_ac_factor": "x", "inverter_ac_to_dc_factor": True, "inverter_standby_w": [1]},
     "nulls": {"inverter_dc_to_ac_factor": None, "inverter_ac_to_dc_factor": None, "inverter_standby_w": None}}
base = load(V["none"])
out = {}
for k, v in V.items():
    r = load(v)
    out[k] = {"fail": [c for c in r["checks"] if c[1] == "FAIL"], "added": [c[0] + ":" + c[1] for c in r["checks"] if c not in base["checks"]],
              "same": [r["decisions"], r["entities"], r["kwp"]] == [base["decisions"], base["entities"], base["kwp"]]}
print(json.dumps(out))
'''


def run_probe(tree: Path, scratch: Path) -> dict | None:
    probe = scratch / "probe_loader.py"
    probe.write_text(OLD_PROBE, encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", "-B", str(probe), str(tree)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not r.stdout.strip():
        return {"error": (r.stdout + r.stderr)[-400:]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def previous_commit() -> str | None:
    """The commit just before the one that introduced the inverter facts (the merged base while this branch is unmerged, main before
    the change after a squash merge), found from the history and never named here (no document or test of the runtime carries a commit
    id). None where the checkout does not hold that history (a shallow clone)."""
    try:
        r = subprocess.run(["git", "-C", str(REPO), "log", "--format=%H", "-S", "INVERTER_CONVERSION_FACTS", "--", "intelligence/site_decisions.py"],
                           capture_output=True, text=True, timeout=120)
        shas = r.stdout.split()
        if r.returncode != 0 or not shas:
            return None
        p = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", "-q", shas[-1] + "^"], capture_output=True, text=True, timeout=60)
        out = p.stdout.strip()
        return out if p.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", out) else None
    except (OSError, subprocess.SubprocessError):
        return None


def old_tree_facts(base: Path, kit_fixed: Path) -> dict | None:
    """The tree just before this change, if the checkout holds that history: its loader run on site files that carry the facts, and its
    kit compared with this one (none new, none removed, the five changed files, the previous loader's hash). None when it is not here."""
    prev = previous_commit()
    if prev is None:
        return None
    try:
        arc = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", prev], capture_output=True, timeout=300)
        if arc.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    tree = base / "old_tree"
    tree.mkdir()
    with tarfile.open(fileobj=io.BytesIO(arc.stdout)) as tf:
        try:
            tf.extractall(tree, filter="data")
        except TypeError:
            tf.extractall(tree)
    out: dict = {"old": run_probe(tree, base), "new": run_probe(REPO, base)}
    kit_old = base / "kit_old"
    env_cmd = [sys.executable, "-I", "-B", str(tree / "tools" / "build_ha_integration.py"), "--out", str(kit_old), "--git-sha", FIXED_SHA]
    b = subprocess.run(env_cmd, cwd=str(tree), capture_output=True, text=True, timeout=300)
    out["build_rc"] = b.returncode

    def sums(p: Path) -> dict:
        return {ln.split("  ", 1)[1]: ln.split("  ", 1)[0] for ln in (p / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if "  " in ln}
    if b.returncode == 0:
        old, new = sums(kit_old), sums(kit_fixed)
        pre = PKG + "/"
        out["added"] = sorted(k[len(pre):] for k in set(new) - set(old) if k.startswith(pre))
        out["removed"] = sorted(k[len(pre):] for k in set(old) - set(new) if k.startswith(pre))
        out["changed"] = sorted(k[len(pre):] for k in set(old) & set(new) if k.startswith(pre) and old[k] != new[k])
        out["gates_sha"] = old.get(pre + "runtime/gates.py")
    return out


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

    # --- tools, flags, parameters
    add("rb", "a wrong build flag (--git-sh)", lambda t: sub1(t, "--out $KIT --git-sha 0000000", "--out $KIT --git-sh 0000000"), "tools")
    add("rb", "a deploy parameter that does not exist (-ReferenceKitt)", lambda t: sub1(t, "-ReferenceKit <the L3-tested kit>", "-ReferenceKitt <the L3-tested kit>"), "tools")
    add("rb", "an -Action that does not exist (Upgrad)", lambda t: sub1(t, "-Action Upgrade -SshHost", "-Action Upgrad -SshHost"), "tools")
    add("rb", "a drill sub-command that does not exist (drils)", lambda t: sub1(t, "ecco_intel_drill.py drill --config-root", "ecco_intel_drill.py drils --config-root"), "tools")
    add("rb", "the site-check sub-command misspelled", lambda t: sub1(t, "ecco_intel_drill.py site-check --site $SITE", "ecco_intel_drill.py site-chek --site $SITE"), "tools")
    add("rb", "the fit sub-command misspelled (ha-histor)", lambda t: sub1(t, "power_balance_fit.py ha-history", "power_balance_fit.py ha-histor"), "tools")
    add("rb", "a fit role flag that does not exist (--pvx)", lambda t: sub1(t, '--pv "$E\\pv.json"', '--pvx "$E\\pv.json"'), "tools")
    add("rb", "a placement parameter that does not exist (-ReplaceExistingSha)", lambda t: sub1(t, "-ReplaceExistingSha256 <sha256 of the site file now on the host> -Python $PY -Plan", "-ReplaceExistingSha <sha256 of the site file now on the host> -Python $PY -Plan"), "tools")
    add("rb", "the placement lines without -ReplaceExistingSha256", lambda t: t.replace("-ReplaceExistingSha256 <sha256 of the site file now on the host> ", ""), "tools")
    add("rb", "the placement shown only with -Plan", lambda t: t.replace(" -Python $PY\n```", " -Python $PY -Plan\n```"), "tools")
    add("rb", "a -Target that does not exist (Staging)", lambda t: sub1(t, "-SshHost $H -Target Production `\n    -ReplaceExistingSha256 <sha256 of the site file now on the host> -Python $PY -Plan", "-SshHost $H -Target Staging `\n    -ReplaceExistingSha256 <sha256 of the site file now on the host> -Python $PY -Plan"), "tools")
    add("rb", "the drill line without the upgrade kit", lambda t: sub1(t, " --upgrade-kit $KIT", ""), "tools")
    add("rb", "the Plan and Upgrade lines without -ExpectedSumsSha256", lambda t: t.replace("-ExpectedSumsSha256 <sha256> ", ""), "tools")
    add("rb", "the rollback command without its stamp", lambda t: t.replace("-Action Rollback -BackupStamp <stamp>", "-Action Rollback"), "tools")
    add("rb", "the Rollback line names a kit", lambda t: sub1(t, "-Action Rollback -BackupStamp <stamp> -SshHost $H", "-Action Rollback -BackupStamp <stamp> -Kit $KIT -SshHost $H"), "tools")
    add("rb", "a tool that does not exist is named", lambda t: t + "\nRun `tools/ecco_nothing.py` now.\n", "tools")
    add("rb", "an offline-tests flag that does not exist (--rootdir)", lambda t: sub1(t, "run_offline_tests.py --root custom_components", "run_offline_tests.py --rootdir custom_components"), "tools")
    # --- the kit
    add("rb", "the nosha hash changed by one digit", lambda t: t.replace(k["nosha"], k["nosha"][:-1] + ("0" if k["nosha"][-1] != "0" else "1")), "kit")
    add("cl", "the fixed-reference hash removed from the checklist", lambda t: t.replace(k["fixed"], "REMOVED"), "kit")
    add("rb", "the file count changed (53 files)", lambda t: t.replace("53 files", "54 files"), "kit")
    add("rb", "a changed file's name dropped", lambda t: t.replace("site_decisions.py", "decisions.py"), "kit")
    add("rb", "'none new' dropped", lambda t: t.replace("none new, 5 changed", "7 new, 5 changed"), "kit")
    add("cl", "'none new' dropped from the checklist", lambda t: t.replace("none new, 5 changed", "3 new, 5 changed"), "kit")
    # --- numbers
    add("rb", "the factor bound changed in the runbook (0.90 to 0.85)", lambda t: t.replace("0.90 to 1.0", "0.85 to 1.0"), "numbers")
    add("cl", "the standby bound changed in the checklist (150 W)", lambda t: t.replace("0 to 100 W", "0 to 150 W"), "numbers")
    add("rb", "one mention of the standby bound changed (D-U3-9)", lambda t: subw(t, "0 to 100 W for the standby draw", "0 to 150 W for the standby draw"), "numbers")
    add("rb", "the exposure figure changed (600 W to 900 W)", lambda t: t.replace("600 W and 656 W", "900 W and 656 W"), "numbers")
    add("cl", "the exposure figure changed in the checklist (656 W)", lambda t: t.replace("656 W", "700 W"), "numbers")
    add("rb", "the tolerance changed (100 W or 5 %)", lambda t: subw(t, "100 W or 5 % of the largest magnitude", "100 W or 8 % of the largest magnitude"), "numbers")
    add("rb", "a fact name misspelled", lambda t: t.replace("`inverter_standby_w`", "`inverter_standby_wat`"), "numbers")
    add("rb", "the rule-set version changed", lambda t: t.replace("intel-quality-0.3.2-cfg", "intel-quality-0.3.1-cfg"), "numbers")
    add("rb", "the discharge-side shift changed", lambda t: t.replace("0.1 x d + 100 W", "0.2 x d + 100 W"), "numbers")
    add("rb", "a blocker code misspelled", lambda t: t.replace("`POWER_LOSS_FACTS_INVALID`", "`POWER_LOSS_FACTS_INVALIDE`"), "numbers")
    add("cl", "the 99 % acceptance bound changed in the checklist", lambda t: t.replace("at least 99 % accepted", "at least 95 % accepted"), "numbers")
    add("rb", "the 99 % acceptance bound changed in the runbook", lambda t: t.replace("at least 99 %", "at least 90 %"), "numbers")
    # --- the order and its reasons
    add("rb", "the restart after the placement (step numbers swapped)", lambda t: sub1(sub1(t, "| 7 | **the restart**", "| 9 | **the restart**"), "| 9 | the site file with", "| 7 | the site file with"), "order")
    add("rb", "the reload before the placement (step numbers swapped)", lambda t: sub1(sub1(t, "| 10 | **the config-entry reload**", "| 9 | **the config-entry reload**"), "| 9 | the site file with", "| 10 | the site file with"), "order")
    add("cl", "the checklist's placement before the Upgrade", lambda t: sub1(sub1(t, "| 5 | coordinator, **go** |", "| 9 | coordinator, **go** |"), "| 9 | coordinator, **go** | `place-ha-site-file.ps1", "| 5 | coordinator, **go** | `place-ha-site-file.ps1"), "order")
    add("rb", "the old loader said to refuse the facts", lambda t: t.replace("The old loader does not refuse the facts", "The old loader refuses the facts"), "order")
    add("rb", "'Kit first, one restart, then the facts' removed", lambda t: t.replace("Kit first, one restart, then the facts", "The facts first"), "order")
    add("rb", "the loosening-step reason removed", lambda t: t.replace("The facts are the loosening step", "The facts are a step"), "order")
    add("rb", "the reload-or-restart reason removed", lambda t: t.replace("The facts take effect only at a reload or a restart", "The facts take effect at once"), "order")
    add("rb", "the suite's repeat of the old-loader experiment no longer said to skip honestly", lambda t: t.replace("the suite prints SKIP for these two checks", "the suite always runs these two checks"), "order")
    add("cl", "the checklist's reason dropped", lambda t: t.replace("the previous kit does not refuse the facts", "the previous kit may refuse the facts"), "order")
    add("cl", "the checklist's rollback takes the kit out before the facts (RB2 and RB4 swapped in the text)",
        lambda t: sub1(sub1(sub1(t, "2. **RB2 the facts out:**", "2. **RB9 the facts out:**"), "4. **RB4 restore the previous", "4. **RB2 restore the previous"), "**RB9 the facts out:**", "**RB4 the facts out:**"), "rollback")
    add("rb", "RB2 no longer the placement of the previous site file", lambda t: t.replace("place-ha-site-file.ps1 -SiteFile $PREVSITE", "copy-site-file.ps1 -SiteFile $PREVSITE"), "order")
    add("rb", "the loader guard hash altered", lambda t: t.replace("659239f3cca7393d3e82b779a504075c9b6291403195923757712016f591305b", "659239f3cca7393d3e82b779a504075c9b6291403195923757712016f591305c"), "forbidden")
    # --- restart and reload
    add("rb", "the restart sentence removed", lambda t: re.sub(r"only with the owner's explicit\s+approval,\s+separate from the\s+Upgrade", "at some point", t, count=1), "no_restart")
    add("rb", "an automatic restart flag added to the Upgrade line", lambda t: re.sub(r"(-Action Upgrade[^\n]*\n[^\n]*-Python \$PY)", r"\1 -Restart", t, count=1), "no_restart")
    add("rb", "the reload said to be a restart", lambda t: subw(t, "is a reload of the one config entry and is not a restart", "is a restart of the one config entry"), "no_restart")
    add("rb", "'the only restart' removed", lambda t: subw(t, "This is the only restart of the update.", "A second restart may follow."), "no_restart")
    add("cl", "the checklist no longer says a reload is not a restart", lambda t: t.replace("a reload, not a second restart", "a second restart"), "no_restart")
    # --- cls, quotes, sentences, forbidden
    add("rb", "the first block's cls dropped", lambda t: sub1(t, FENCE + "powershell\ncls\n", FENCE + "powershell\n"), "cls")
    add("rb", "an owner quote altered", lambda t: t.replace("but not bundled into Ghost", "and bundled into Ghost"), "quotes")
    add("rb", "the second owner quote dropped", lambda t: t.replace("Do not make live changes or restart Home Assistant until Ghost has its final GO.", "Wait."), "quotes")
    add("cl", "the substance of a quote dropped", lambda t: t.replace("but not bundled into Ghost", "bundled"), "quotes")
    add("cl", "no automatic installation sentence removed from the checklist", lambda t: re.sub(r"(?i)no automatic installation or live access is authorised", "REMOVED", t), "sentences")
    add("rb", "never run in a real Home Assistant removed from the runbook", lambda t: re.sub(r"never run in a real Home Assistant", "REMOVED", t), "sentences")
    add("rb", "a forbidden word added (guaranteed)", lambda t: t + "\nThe rollback is guaranteed.\n", "forbidden")
    add("cl", "a forbidden phrase added (safe to install)", lambda t: t + "\nIt is safe to install.\n", "forbidden")
    add("rb", "an entity id added", lambda t: t + f"\nSee {sample_entity}.\n", "forbidden")
    add("cl", "an address added", lambda t: t + f"\nHost {sample_addr}.\n", "forbidden")
    add("rb", "a workstation path added", lambda t: t + f"\nFile {sample_path}.\n", "forbidden")
    add("rb", "a commit id added", lambda t: t + f"\nBuilt from {sample_commit}.\n", "forbidden")
    add("cl", "a token added", lambda t: t + f"\nKey {sample_token}.\n", "forbidden")
    add("rb", "a hash that is not pinned", lambda t: t + "\n" + "ab" * 32 + "\n", "forbidden")
    add("rb", "a calibrated factor added (three decimals)", lambda t: t + "\nThe fitted factor is 0.924.\n", "forbidden")
    add("cl", "a calibrated factor added to the checklist (four decimals)", lambda t: t + "\nThe fit gave 0.9238.\n", "forbidden")
    add("rb", "the live host alias added", lambda t: t + "\nHost ecco-ha.\n", "forbidden")
    # --- preconditions
    add("rb", "the L3 precondition closed", lambda t: re.sub(r"(\| P1 \|.*?)\*\*OPEN\*\*", r"\1closed", t, count=1, flags=re.S), "preconditions")
    add("rb", "P3 closed", lambda t: sub1(t, "| **OPEN**: one independent review (lean mode)", "| closed: one independent review (lean mode)"), "preconditions")
    add("rb", "P2 reopened", lambda t: sub1(t, "closed (offline, lean mode, per the project record", "**OPEN** (offline, lean mode, per the project record"), "preconditions")
    add("rb", "P6 closed", lambda t: sub1(t, "| **OPEN**: U2 is prepared and waits", "| closed: U2 is prepared and waits"), "preconditions")
    add("rb", "P8 reopened", lambda t: sub1(t, "| closed on the commit these documents were written on", "| **OPEN** on the commit these documents were written on"), "preconditions")
    add("rb", "P2 closed without its reason", lambda t: sub1(t, "one MAJOR (the factor bounds were too wide) and five minors", "some findings"), "preconditions")
    add("cl", "the checklist lists P6 as closed", lambda t: t.replace(OPEN_LIST_TEXT, "P1, P3, P4, P5, P7 and P9"), "preconditions")
    add("cl", "the checklist claims it is ready", lambda t: t.replace("NOT yet ready", "ready"), "preconditions")
    add("rb", "the L3 precondition no longer asks for the previous kit on a site file with the facts",
        lambda t: subw(t, "the previous kit restored on the isolated instance loads with a site file that still holds the facts", "the previous kit restored"), "preconditions")
    add("cl", "the checklist drops the WSL run", lambda t: t.replace("L3 (WSL) kit-equivalence reference run", "reference run"), "preconditions")
    # --- steps
    add("cl", "a step row removed from the checklist", lambda t: drop_line(t, "| 6 | coordinator, **go** |"), "steps")
    add("cl", "a step's who changed", lambda t: t.replace("| 4 | coordinator, **go** |", "| 4 | you, **go** |"), "steps")
    add("rb", "a live step without its own authorisation", lambda t: re.sub(r"(\| 6 \|.*?\| read-only \| )\*\*yes\*\*", r"\1no", t, count=1), "steps")
    add("rb", "the restart's own approval weakened", lambda t: t.replace("**yes, its own approval, separate from the Upgrade**", "**yes**"), "steps")
    add("rb", "the reload's own approval weakened", lambda t: t.replace("**yes, its own approval, separate from the placement**", "**yes**"), "steps")
    add("cl", "the reload's own approval dropped from the checklist", lambda t: t.replace("| 10 | you, **own approval** |", "| 10 | you |"), "steps")
    add("rb", "step 8 no longer the kit-alone checkpoint", lambda t: t.replace("no `SITE_INVERTER_CONVERSION` line; eleven entities", "eleven entities"), "steps")
    add("rb", "step 11 no longer expects PASS", lambda t: sub1(t, "`SITE_INVERTER_CONVERSION` PASS; no FAIL; the status entity's", "no FAIL; the status entity's"), "steps")
    # --- rollback
    add("rb", "a proof dropped from RB4", lambda t: sub1(t, "Proof: the PASSED block", "The PASSED block"), "rollback")
    add("rb", "RB2's proof dropped", lambda t: sub1(t, "Proof: `ECCO SITE FILE PLACED`", "Seen: `ECCO SITE FILE PLACED`"), "rollback")
    add("cl", "the rollback order swapped (RB4 and RB5)", lambda t: t.replace("**RB4 restore", "**RB9 restore").replace("**RB5 restart", "**RB4 restart").replace("**RB9 restore", "**RB5 restore"), "rollback")
    add("rb", "'heavy' removed everywhere from the runbook", lambda t: t.replace("heavy ", ""), "rollback")
    add("cl", "'never the first rollback' removed", lambda t: t.replace("never the first rollback", "not the first"), "rollback")
    add("rb", "S6 no longer asks the owner", lambda t: subw(t, "So **ask the owner** before skipping RB5", "So skip RB5"), "rollback")
    add("rb", "S7 removed", lambda t: subw(t, "*S7, the placement stopped", "*S9, the placement stopped"), "rollback")
    add("cl", "the checklist no longer leaves RB5 to the owner before the restart", lambda t: subw(t, "runbook 10, S6", "runbook 10"), "rollback")
    add("rb", "the facts-only sequence altered", lambda t: t.replace("is RB1, RB2, RB3 and RB6", "is RB1, RB3 and RB6"), "rollback")
    add("cl", "'a facts-only rollback needs none' removed", lambda t: t.replace("a facts-only rollback needs none", "a facts-only rollback needs one"), "rollback")
    add("rb", "RB4 cited as R4", lambda t: subw(t, "the listing comparison of RB4 is still empty", "the listing comparison of R4 is still empty"), "rollback")
    add("rb", "an install runbook row that does not exist is cited", lambda t: sub1(t, "install runbook G4", "install runbook G44"), "cites")
    # --- decisions, no entity, no write, coverage, drill
    add("cl", "D-U3-5 marked decided", lambda t: sub1(t, "read by you | open |", "read by you | decided |") if "read by you | open |" in t else t.replace("| D-U3-5 |", "| D-U3-5x |"), "decisions")
    add("rb", "an owner item removed (D-U3-9)", lambda t: drop_line(t, "| D-U3-9 |"), "decisions")
    add("cl", "an owner item removed from the checklist (D-U3-2)", lambda t: drop_line(t, "| D-U3-2 |"), "decisions")
    add("rb", "the no-entity statement removed", lambda t: t.replace("No entity, helper, service, package or dashboard is created or edited by this update", "A helper may be added"), "no_entity")
    add("cl", "the checklist's RG-F3 mention removed", lambda t: t.replace("RG-F3", "the exposure item"), "no_entity")
    add("rb", "'adds no table' removed", lambda t: t.replace("adds no table, column or row type", "adds a table"), "no_write")
    add("cl", "the checklist's no-table sentence removed", lambda t: t.replace("No table, column or row type is added", "A table is added"), "no_write")
    add("rb", "a not-established keyword removed", lambda t: t.replace("calibrated, not known", "calibrated"), "coverage")
    add("cl", "the checklist forgets the reload in section 8", lambda t: sub1(t, "the config-entry reload on the production host has never been run", "the reload has been run"), "coverage")
    add("rb", "the drill statement removed", lambda t: t.replace("What the drill proves, exactly.", "What the drill does."), "drill")
    add("rb", "the site-check output no longer quoted", lambda t: t.replace("`PASS  SITE_INVERTER_CONVERSION`", "`a PASS line`"), "drill")
    add("rb", "the stand-in host statement removed", lambda t: t.replace("is exercised against a stand-in host by", "is exercised by"), "drill")
    # --- phrases, variables, working folder, cites, write statement, data quality, fit rows
    add("rb", "a quoted tool phrase altered (NO CHANGE)", lambda t: t.replace("NO CHANGE", "NOTHING CHANGED"), "phrases")
    add("rb", "the placement's PLACED line altered", lambda t: t.replace("ECCO SITE FILE PLACED", "SITE FILE DONE"), "phrases")
    add("rb", "the PASS-word statement dropped", lambda t: t.replace("The download shows a passing check as the single word PASS", "The download shows a passing check in full"), "phrases")
    add("rb", "a variable not set in a block", lambda t: sub1(t, "$E = '<OFFLINE_EVIDENCE_DIR>\\u3-baseline'\n$NEW = '<sha256 of the new site file>'", "$NEW = '<sha256 of the new site file>'"), "vars")
    add("cl", "the checklist grows past 120 lines", lambda t: t + "\n" * 30 + "\n".join(["- more"] * 30), "shape")
    add("cl", "the checklist cites a runbook section that does not exist", lambda t: t.replace("(runbook 10;", "(runbook 77;"), "cites")
    add("rb", "the method document cited at a section that does not exist", lambda t: sub1(t, "DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md) section 10.1", "DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md) section 10.9"), "cites")
    add("rb", "the site-check block without its working folder", lambda t: sub1(t, "Set-Location <checkout>\n& $PY -I -B tools\\ecco_intel_drill.py site-check", "& $PY -I -B tools\\ecco_intel_drill.py site-check"), "workdir")
    add("rb", "the fit block without its working folder", lambda t: sub1(t, "Set-Location <checkout>\n& $PY -I -B -X utf8 intelligence\\tools\\power_balance_fit.py", "& $PY -I -B -X utf8 intelligence\\tools\\power_balance_fit.py"), "workdir")
    add("rb", "the state folder left out of the write statement", lambda t: subw(t, "and nothing in the state folder", "and the state folder"), "write_statement")
    add("cl", "the false sentence restored", lambda t: t.replace("The one helper the procedure touches is the existing pause helper, which you turn on and off.", "The only write outside the scorecard file is the pause helper."), "write_statement")
    add("rb", "the site file left out of the write statement", lambda t: sub1(t, "the site file (A2, replaced by the owner's new file), ", ""), "write_statement")
    add("cl", "the site file left out of the checklist's write statement", lambda t: sub1(t, "the site file (replaced by your new file), ", ""), "write_statement")
    add("rb", "'may stay DEGRADED' dropped", lambda t: t.replace("It may stay DEGRADED", "It will be OK"), "data_quality")
    add("rb", "'read while the flow is large' dropped", lambda t: subw(t, "Read while PV or battery power is large", "Read at any time"), "data_quality")
    add("cl", "the checklist no longer says data quality may stay DEGRADED", lambda t: t.replace("data quality may return to OK or **stay DEGRADED**", "data quality returns to OK"), "data_quality")
    add("rb", "the section 11 DEGRADED row removed", lambda t: drop_line(t, "| data quality stays DEGRADED"), "data_quality")
    add("rb", "a fit row altered (accepted before the fault)", lambda t: t.replace("accepted before the fault", "accepted afterwards"), "fit_rows")
    add("rb", "NOT USABLE no longer quoted", lambda t: t.replace("NOT USABLE as site facts", "not usable"), "fit_rows")
    add("rb", "the hold-out rows no longer read", lambda t: t.replace("the hold-out rows", "the second half"), "fit_rows")
    return out


def make_source_mutants():
    def drop_param(src):
        return src.replace("[string]$ReferenceKit,", "")

    def drop_replace_param(src):
        return src.replace("[string]$ReplaceExistingSha256,", "")

    def drop_gitsha(src):
        return src.replace('"--git-sha"', '"--git-shaX"')

    def drop_phrase(src):
        return src.replace("ROLLBACK NOT CONFIRMED", "ROLLBACK UNCLEAR")

    def drop_validate(src):
        return src.replace("'Upgrade', ", "")

    def takes_effect_changed(src):
        return src.replace("Takes effect: only at a config-entry reload or a restart", "Takes effect: at once")

    def fit_role(src):
        return src.replace('ROLES = ("house", "pv", "battery", "grid")', 'ROLES = ("house", "solar", "battery", "grid")')

    def fit_not_usable(src):
        return src.replace("NOT USABLE as site facts", "not usable")

    def fit_share(src):
        return src.replace("CLEAN_SHARE_WARN = 0.99", "CLEAN_SHARE_WARN = 0.95")

    def bounds_changed(src):
        return src.replace("INVERTER_FACTOR_BOUNDS = (0.90, 1.0)", "INVERTER_FACTOR_BOUNDS = (0.85, 1.0)")

    def code_renamed(src):
        return src.replace("POWER_LOSS_FACTS_INVALID", "POWER_LOSS_INVALID")

    def site_iterated(src):
        return src.replace("    site = profile.get(\"site\") if isinstance(profile, Mapping) else None\n",
                           "    site = profile.get(\"site\") if isinstance(profile, Mapping) else None\n    unknown = [k for k in site.keys()] if isinstance(site, Mapping) else []\n", 1)

    def facts_by_name_dropped(src):
        return src.replace("for k in INVERTER_CONVERSION_FACTS}", "for k in INVERTER_CONVERSION_FACTS[:1]}")

    def hint_added(src):
        return src.replace('for k in ("user_reserve_soc_pct", "technical_min_soc_pct"):', 'for k in ("user_reserve_soc_pct", "technical_min_soc_pct", "inverter_standby_w"):')

    def gates_writes(src):
        return src.replace("def load_site(", "def _dump(p):\n    open(p, 'w').write('x')\n\n\ndef load_site(", 1)

    def store_names_facts(src):
        return src + "\nINVERTER_NOTE = 'inverter_standby_w'\n"

    def degraded_changed(src):
        return src.replace("elif c.blocked or any(f.severity in (BLOCK, WARN) for f in c.findings):", "elif c.blocked:")

    def method_changed(src):
        return src.replace("does not by itself make `data_quality` OK", "makes data_quality OK")

    def selftest_text(src):
        return src.replace('c.level if c.level == PASS else f"{c.level}: {c.short}"', 'f"{c.level}: {c.short}"')

    def debug_to_warning(src):
        return src.replace('_LOGGER.debug("ECCO Intelligence start-up check %s: %s"', '_LOGGER.warning("ECCO Intelligence start-up check %s: %s"')

    def drill_check_dropped(src):
        return src.replace("site.local.json, state/ and the other integration untouched by every step", "untouched")

    def deploy_suite_item(src):
        return src.replace("# 21. place-ha-site-file.ps1", "# 21. something else")

    def no_tree_check(src):
        return src.replace("Assert-EccoCleanWorkingTree -RepoRoot $repoRoot\n", "", 1)

    def no_snapshot_check(src):
        return src.replace("the protected site file or state folder changed during the write", "the protected files changed", 1)

    def no_replace_refusal(src):
        return src.replace("to replace it, pass -ReplaceExistingSha256 with its full sha256", "it is replaced", 1)

    def install_reads(src):
        return src.replace("The integration only reads it, at start-up and at a config-entry\nreload", "The integration reads it at any time")

    def strict_map(src):
        return src.replace("_strict(profile[MAP_BLOCK]", "_strict(profile")

    return [
        ("deploy", "the deploy tool without the -ReferenceKit parameter", drop_param, "tools"),
        ("place", "the placement tool without the -ReplaceExistingSha256 parameter", drop_replace_param, "tools"),
        ("build", "the build tool without the --git-sha flag", drop_gitsha, "tools"),
        ("psm1", "the module no longer prints ROLLBACK NOT CONFIRMED", drop_phrase, "phrases"),
        ("deploy", "the deploy tool's ValidateSet without Upgrade", drop_validate, "tools"),
        ("place", "the placement tool no longer says it takes effect only at a reload or a restart", takes_effect_changed, "order"),
        ("fit", "the fit tool's roles renamed", fit_role, "tools"),
        ("fit", "the fit tool no longer prints NOT USABLE", fit_not_usable, "fit_rows"),
        ("fit", "the fit tool's acceptance share changed", fit_share, "numbers"),
        ("sd", "the factor bounds changed in the source", bounds_changed, "numbers"),
        ("quality", "the blocker code renamed in the engine", code_renamed, "numbers"),
        ("gates", "the loader iterates the site block's keys", site_iterated, "order"),
        ("gates", "the loader no longer reads all three facts by name", facts_by_name_dropped, "order"),
        ("sd", "a third key joins the reserve hints", hint_added, "order"),
        ("sources", "the entity map's strict reader reads more than shadow_runtime", strict_map, "order"),
        ("gates", "the loader writes a file", gates_writes, "no_write"),
        ("store", "the store names the facts", store_names_facts, "no_write"),
        ("quality", "data quality is DEGRADED only when an item is blocked", degraded_changed, "data_quality"),
        ("method", "the method document no longer says clearing the block does not make data quality OK", method_changed, "data_quality"),
        ("selftest", "the self-test export returns the text of a passing check", selftest_text, "phrases"),
        ("coordinator", "the start-up check detail is logged at WARNING", debug_to_warning, "phrases"),
        ("drill_suite", "the drill suite without the check the runbook relies on", drill_check_dropped, "drill"),
        ("deploy_suite", "the deploy suite without the placement item", deploy_suite_item, "drill"),
        ("deploy", "the deploy tool no longer checks the working tree", no_tree_check, "rollback_reads"),
        ("psm1", "the kit write no longer compares the protected snapshot", no_snapshot_check, "rollback_reads"),
        ("place", "the placement tool no longer refuses a replacement without the live sha256", no_replace_refusal, "rollback_reads"),
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
    F = {"kit": kit_facts(base), "facts": real_facts(), "order_source_problems": order_source_problems}
    D = load_drill_module()
    print("== the real drill, with a synthetic previous kit, the real kit and a site file that holds the facts")
    F["drill"] = run_real_drill(base, F["kit"]["dir"], D)
    check("the real drill leaves the site file and the state folder byte-identical through install, upgrade, rollback and uninstall, "
          "and the rollback restores the previous kit's tree", F["drill"]["ok"], F["drill"]["detail"])
    F["site_check"] = site_check_facts(D)
    check("the real site-check prints no check without facts, PASS with valid facts, and WARN with PROBLEMS and POWER_LOSS_FACTS_INVALID with invalid facts",
          not F["site_check"]["problems"], "; ".join(F["site_check"]["problems"]))
    own_bytes = Path(__file__).read_bytes()
    own = own_bytes.decode("utf-8", errors="replace")
    check("this suite's own source is ASCII and holds no address, token, entity id or workstation path",
          own_bytes.isascii() and not IPV4_RE.search(own) and not TOKEN_RE.search(own) and not ENTITY_RE.search(own)
          and not PATH_RE.search(own))

    print("== the tree just before this change (the previous loader), where this checkout holds the history")
    old = old_tree_facts(base, F["kit"]["dir"])
    if old is None:
        skip("the previous loader loads site files that carry the facts exactly as without them", "the history before this change is not in this checkout")
        skip("the previous kit differs from this one by exactly the five files the documents name, and its loader has the pinned hash",
             "the history before this change is not in this checkout")
    else:
        po, pn = old["old"], old["new"]
        ok_old = bool(po) and "error" not in po and all(v["fail"] == [] and v["added"] == [] and v["same"] for v in po.values())
        check("the previous loader loads a site file with the facts valid, partial, out of bounds, of the wrong types and null exactly as without them "
              "(no FAIL, no extra check, the same decisions, entity map and array size)", ok_old, str(po)[:300])
        ok_new = bool(pn) and "error" not in pn and pn["valid"]["added"] == ["SITE_INVERTER_CONVERSION:PASS"] and \
            pn["partial"]["added"] == ["SITE_INVERTER_CONVERSION:WARN"] and pn["none"]["added"] == [] and pn["nulls"]["added"] == []
        check("the same probe on this tree sees the difference (PASS for a valid set, WARN for an invalid one, nothing for none or null)", ok_new, str(pn)[:300])
        check("the previous kit differs from this one by exactly the five files the documents name (none new, none removed)",
              old.get("build_rc") == 0 and old.get("added") == [] and old.get("removed") == [] and sorted(old.get("changed", [])) == sorted(CHANGED_FILES),
              f"added {old.get('added')}, removed {old.get('removed')}, changed {old.get('changed')}")
        check("the previous kit's runtime/gates.py has the hash the baseline guard pins", old.get("gates_sha") == BASE_GATES_SHA, str(old.get("gates_sha")))

    if RB is not None and CL is not None:
        print("== the rules")
        result = analyse(RB, CL, S0, F)
        for name in RULES:
            check(RULE_TITLES[name], not result[name], "; ".join(result[name][:4]))
        check("the open preconditions are exactly P1, P3, P4, P5, P6, P7 and P9 at the time of writing (P2 and P8 closed)", open_ids(RB) == set(OPEN_AT_WRITING),
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
print(f"{PASSED[0]} PASS, {len(FAILURES)} FAIL" + (f", {len(SKIPPED)} SKIP" if SKIPPED else ""))
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the power-balance update documents suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all power-balance update documents checks passed" + (f" ({len(SKIPPED)} skipped: the history before this change is not in this checkout)" if SKIPPED else ""))
