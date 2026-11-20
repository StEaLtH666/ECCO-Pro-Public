#!/usr/bin/env python3
"""Consistency suite: the U1 GO checklist (docs/product-ui/GEEK_MODE_U1_GO_CHECKLIST.md) against the first-update runbook
(docs/product-ui/GEEK_MODE_FIRST_UPDATE_RUNBOOK.md), the pins of the card suite and the sources of the tools the checklist names.

A short document that a person decides on is only worth something while it says what the long one and the tools say. This suite reads the
checklist and the runbook as text (no Home Assistant, no network, no Node, no git, no PowerShell) and asserts:

  [1] the pins: the card's sha8 and full sha256, its size, the generated configuration's size and sha256, and the catalogue counts are in the
      checklist exactly as pinned in tools/tests/test_ecco_mode_shell_card.py (parsed from that file, never copied by hand)
  [2] the five checks of the owner's directive are present by name (exact module resource, admin-only dashboard setup, backup, rollback,
      correct-dashboard targeting), as the first cell of a row of the checks table
  [3] every runbook section the checklist cites exists (a `## N.` or `### N.M` heading), and so does every section of the checklist it cites
  [4] every tool flag and sub-command named in the checklist exists in that tool's source (the interpreter's own flags, written before the
      tool's name, are not the tool's), and every upper-case output phrase it quotes is printed by one of the tools
  [5] every PowerShell block of the checklist and of the runbook starts with `cls`
  [6] the plain statements: never run in a real Home Assistant; a module resource is global; Require admin is not a security boundary
  [7] no forbidden word (the three phrases the owner ruled out), no private address, no token shape, no entity id, no non-ASCII character, no
      unexplained hash-like blob (the two pinned hashes are the only 64-hex strings of the checklist)
  [8] the checklist and the runbook agree: the step numbers 0 to 9 and what each is, the section 5.N each step is described in, which steps
      need the owner's go, and the rollback order (dashboard A3, resource A2, file A1)
  [9] the command lines of both documents: no -Restart, -SkipValidation or -AllowDirtyWorkingTree (in a block, or in a paragraph that does
      not forbid it); the deploy line carries only its five allowed flags and the exact source and destination; every verify-resource line
      has --plan, --resources, --before and --base-url, every verify-served line --plan and --base-url; the generation block makes
      dist\\geek-u1 first; every runbook block sets the variables it uses; the runbook's blocks use only flags that exist in the tools
 [10] the exact names wherever they are named: the resource URL and the file name (derived from the card's sha8 and from the generator's
      own plan constants, never typed here), the type module, "Require admin", the stop cell of each of the five checks, and the rollback
      order stated the same way in the checklist's heading and in the runbook's section 7
 [11] the sentences added after the review of round 3 (the targeting text, the second new file, the scope of the write statement, the limit of
      step 8, the re-run of the gate) are in the section they belong to, and the claims they replaced are gone
 [12] the Node generated-config test is named with ECCO_PYTHON and "0 skipped" wherever the runbook names it, and what the runbook says of
      that test is true of its source (it takes its interpreter from ECCO_PYTHON and skips five tests without one)
 [13] checklist section 8 covers every bullet of runbook section 9 (a keyword per bullet; a new bullet without a keyword fails)
 [14] mutants (all in memory): a wrong sha8, a wrong card or configuration hash, a missing check, a dropped `cls`, a cited section that does
      not exist, a forbidden word, a changed rollback order, a dropped statement, a flag that does not exist, a removed step, a quoted tool
      phrase that the tool never prints, an address, a token, an entity id, a runbook with its rollback order changed, a runbook heading that is
      gone, and (round 4) every mutant of the review of round 3 (a forbidden deploy flag, a mistyped sha8 in each place it is written, a wrong
      type, a dropped Require admin or --before or stop, a swapped order wording) and a removal of each pinned sentence and of each coverage
      keyword: each is killed by the rule that exists for it

Usage: python tools/tests/test_geek_mode_checklist.py [CHECKLIST_FILE]
The optional argument names another checklist (this is how the suite is shown to fail on a checklist with a wrong hash).

Test-only, no network. Reads repository files; writes nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST_REL = "docs/product-ui/GEEK_MODE_U1_GO_CHECKLIST.md"
RUNBOOK_REL = "docs/product-ui/GEEK_MODE_FIRST_UPDATE_RUNBOOK.md"
PINS_REL = "tools/tests/test_ecco_mode_shell_card.py"
NODE_TEST_REL = "frontend/ecco-mode-shell/test/generated-config.test.mjs"
TOOLS = {   # the name as it is written in a command, its kind, its source
    "geek_mode_dashboard_config.py": ("py", "tools/geek_mode_dashboard_config.py"),
    "ecco_deploy_preflight.py": ("py", "tools/ecco_deploy_preflight.py"),
    "deploy-ha.ps1": ("ps", "tools/deploy-ha.ps1"),
    "ha-logs.ps1": ("ps", "tools/ha-logs.ps1"),
}
EXTRA_SOURCES = ("tools/EccoDeploy.psm1",)   # printed by deploy-ha.ps1 through its module

FAILURES: list[str] = []
PASSED = [0]
MAX_CHECKLIST_LINES = 140   # "at most about 130 lines": a short document stays short
FENCE = "`" * 3


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED[0] += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def read(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8")


# ---------------------------------------------------------------------------------------------------------------------------------
# what the rules are made of
# ---------------------------------------------------------------------------------------------------------------------------------
FORBIDDEN_WORDS = ("fully enforced", "guaranteed", "safe to install")
OWNER_CHECKS = ("exact module resource", "admin-only dashboard setup", "backup", "rollback", "correct-dashboard targeting")
STATEMENTS = {   # a plain sentence of the checklist: a phrase of it, in lower case, whitespace folded
    "never run in a real Home Assistant": "never run in a real home assistant",
    "a module resource is global": "a module resource is global",
    "Require admin is not a security boundary": "not a security boundary",
}
STEP_WORDS = {0: "offline", 1: "baseline", 2: "backup", 3: "deploy-ha", 4: "resource", 5: "dashboard", 6: "after-check", 7: "look", 8: "no-write", 9: "close-out"}
LIVE_GO_STEPS = (1, 3, 4, 6, 8)   # the runbook's step table: "own owner authorisation: yes" (steps 2, 5 and 7 are the owner's own actions)
ROLLBACK_ORDER = ["A3", "A2", "A1"]   # the dashboard, the resource, the file: newest first

IPV4 = re.compile(r"(?<![0-9])(?<![0-9]\.)(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)")   # an address at the end of a sentence is still an address
TOKEN = re.compile(r"-----BEGIN [A-Z ]*KEY-----|\bghp_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bAKIA[0-9A-Z]{16}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}"
                   r"|\bsk-[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}|\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}", re.I)
ENTITY_ID = re.compile(r"(?<![A-Za-z0-9_.\\/-])(?:sensor|binary_sensor|switch|input_boolean|input_number|input_select|input_text|input_datetime|number|select|button|"
                       r"automation|climate|light)\.[a-z0-9]+_[a-z0-9_]+")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
HEX64 = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
HEX_BLOB = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")

# round 4: what the review of round 3 found the suite let through
FORBIDDEN_FLAG = re.compile(r"(?<![\w-])-(?:Restart|SkipValidation|AllowDirtyWorkingTree)\b")
DEPLOY_FLAGS_OK = ("-Source", "-Destination", "-Python", "-SshHost", "-Target")
DEPLOY_SOURCE = "frontend\\ecco-mode-shell\\ecco-mode-shell.js"
PLAN_ARG = "dist\\geek-u1\\plan.json"
VERIFY_FLAGS = {"verify-resource": ("--plan", "--resources", "--before", "--base-url"), "verify-served": ("--plan", "--base-url")}
CHECK_STOP_KEYS = {   # what the Stop cell of each of the five checks in checklist section 3 must still hold (lower case)
    "exact module resource": "resource verified",
    "admin-only dashboard setup": "require_admin",
    "backup": "no protected backup",
    "rollback": "re-check",
    "correct-dashboard targeting": "pre-save check",
}
PINNED = [   # (document, heading number of the section the sentence is in, a phrase of it: lower case, markup-free, whitespace folded)
    # F8: the write statement is scoped, and the existing statement stays
    ("runbook", "1.1", "the shell itself never writes, and nobody taps the tile during this update"),
    ("runbook", "1.1", "that statement is scoped to the card's own code and to what the dashboard places"),
    ("runbook", "1.1", "the standard more-info dialog (opened by the pause tile's hold action and by the geek row action for a sensor) keeps home "
                       "assistant's own admin settings (entity registry edits), the same as on any dashboard (recalled, not verified)"),
    ("runbook", "1.1", "the look does not open it (5.7)"),
    ("runbook", "5.8", "holds for the card's own code and for what the dashboard places"),
    ("runbook", "5.8", "standard more-info dialog (opened by the pause tile's hold action and by the geek row action for a sensor)"),
    ("runbook", "5.8", "keeps home assistant's own admin settings (entity registry edits), the same as on any dashboard (recalled, not verified)"),
    ("runbook", "5.8", "step 8 reads states and state history, not the entity registry"),
    ("checklist", "2", "nobody taps it (runbook 1.1)"),
    ("checklist", "2", "that statement is scoped to the card's own code and what the page places: the standard more-info dialog keeps home assistant's own "
                       "admin settings (entity registry edits), as on any dashboard (recalled, not verified)"),
    # F3: the Node generator test names its interpreter, and 0 skipped is part of the pass
    ("runbook", "5.0", "skips all 5 of its tests and still exits 0"),
    ("runbook", "5.0", "a green row that tested nothing"),
    ("runbook", "5.0", "$env:ecco_python = '<py>' first"),
    ("runbook", "5.0", "5 of 5 pass, 0 skipped is the pass condition, and anything else is not a pass"),
    ("runbook", "5.0", "ecco_python=<py> node --test --test-concurrency=2 test/generated-config.test.mjs"),
    # F2: the pre-save check, the second new file, the way back
    ("runbook", "5.5", "an empty, default or auto-generated configuration of the new dashboard"),
    ("runbook", "5.5", "if the editor offers \"start with an empty dashboard\", the owner may tick it (recalled, not verified)"),
    ("runbook", "5.5", "the recognisable content of the production overview, of the existing intelligence dashboard or of any other existing dashboard"),
    ("runbook", "5.5", "do not fail this check, and the address bar of check 2 is the real proof of targeting"),
    ("runbook", "5.5", "after pasting and before pressing save, the browser's address bar shows the path of the new dashboard"),
    ("runbook", "5.5", "as a second new lovelace file (s1, second case)"),
    ("runbook", "5.6", "a new list with a second file"),
    ("runbook", "5.6", "so it shows as a second new lovelace file, not as a changed one, and the baseline holds no copy of it to paste back"),
    ("runbook", "5.6", "require_admin true (stop if it is not"),
    ("runbook", "7", "or a second new lovelace file). stop; touch nothing else"),
    ("runbook", "7", "which dashboard is a stored file?"),
    ("runbook", "7", "dashboards-before.json or dashboards-after.json"),
    ("runbook", "7", "the dashboard's id gives lovelace.<id>"),
    ("runbook", "7", "the file named only .storage/lovelace, with no id, is the default dashboard's"),
    ("runbook", "7", "first case: a changed existing file"),
    ("runbook", "7", "second case: a second new lovelace file"),
    ("runbook", "7", "had no stored file before"),
    ("runbook", "7", "recalled, not verified: such a dashboard has no stored file until its first save"),
    ("runbook", "7", "there is no baseline copy of it"),
    ("runbook", "7", "returns to its automatically generated page"),
    ("runbook", "7", "delete the stored configuration through that dashboard's own ui"),
    ("runbook", "7", "(recalled, not verified: whether and where home assistant's own screens offer it for that dashboard)"),
    ("runbook", "7", "if the screens offer no way, or anything is unclear, restore the protected backup of step 2"),
    ("runbook", "10", "for a second new lovelace file clear that dashboard's stored configuration"),
    ("checklist", "3", "an empty, default or auto-generated configuration of the new dashboard"),
    ("checklist", "3", "or a second new lovelace file (runbook 7, s1)"),
    ("checklist", "5", "a second new file is a stop"),
    ("checklist", "6", "a second new lovelace file: no baseline copy exists"),
    ("checklist", "6", "clear that dashboard's stored configuration through its own ui, else the protected backup"),
    # F4: the host reads that never ran, said in section 9 as well
    ("runbook", "9", "neither have the globbed sha256sum and the scp of the stored .storage files (5.1, 5.6)"),
    # F5: step 8 checks within limits and does not prove
    ("runbook", "5.7", "step 8 checks it, within the limits stated in 5.8"),
]
FORBIDDEN_PHRASES = [   # (document, section or None for the whole text, a phrase that must be gone)
    ("runbook", None, "step 8 proves it"),
    ("checklist", None, "step 8 proves it"),
    ("runbook", "5.5", "with no ecco card in it"),
]
COVERAGE = [   # (a phrase of a bullet of runbook section 9, the keywords that checklist section 8 must hold for it; lower case)
    ("has never run in a real home assistant or a real browser", ("never run in a real home assistant",)),
    ("42 of the 344 declared attribute rows are conditional", ("42 of the 344",)),
    ("the pins and the mutation proof are offline", ("ci runs no node", "mutation proof")),
    ("a service call that changes no state leaves no durable record", ("leaves no durable record",)),
    ("the resource is global", ("a module resource is global",)),
    ("known console noise", ("old phone web view",)),
    ("intelligence is not accepted overall", ("intelligence stays not accepted",)),
    ("admin-only is a visibility setting, not a security boundary", ("not a security boundary",)),
    ("recalled from home assistant's behaviour, not verified on this host", ("recalled, not verified",)),
    ("the tools of steps 3 and 4 were read", ("deploy and preflight tools", "never run against the real host")),
    ("phone and tablet layouts are not part of u1", ("phone and tablet layouts are not part of u1",)),
    ("the state read, the history read and the log reads", ("supervisor state, history and log reads",)),
]


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def plain(text: str) -> str:
    """Lower case, whitespace folded, markdown emphasis and code ticks removed: what a sentence says, whatever its markup."""
    return re.sub(r"\s+", " ", text.replace("*", "").replace("`", "")).strip().lower()


def sections(text: str) -> dict[str, str]:
    """The numbered `## N.` sections of a document: {"1": body, ...}."""
    out: dict[str, str] = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        m = re.match(r"(\d+)\.", part)
        if m:
            out[m.group(1)] = part
    return out


def has_heading(text: str, number: str) -> bool:
    """`## 7.` or `### 5.3 ` (a heading whose number is exactly `number`)."""
    return re.search(r"^#{2,4} " + re.escape(number) + r"(?:\.|\s)", text, re.M) is not None


def subsection_span(text: str, number: str) -> tuple[int, int] | None:
    """The span of the section whose heading is numbered `number` (`## 7.` or `### 5.5 `), up to the next `##` or `###` heading."""
    m = re.search(r"^#{2,4} " + re.escape(number) + r"\.? .*?(?=^#{2,3} |\Z)", text, re.S | re.M)
    return (m.start(), m.end()) if m else None


def subsection(text: str, number: str) -> str:
    span = subsection_span(text, number)
    return text[span[0]:span[1]] if span else ""


def powershell_blocks(text: str) -> list[str]:
    return [b for _indent, b in re.findall(r"^( *)" + FENCE + r"powershell\n(.*?)^\1" + FENCE, text, re.S | re.M)]


def command_lines(text: str) -> list[str]:
    """Every non-empty line of every PowerShell block, stripped: the command lines of a document."""
    return [ln.strip() for b in powershell_blocks(text) for ln in b.split("\n") if ln.strip()]


def fence_lines(text: str) -> list[str]:
    """Every non-empty line of every fenced block of any kind (not only PowerShell), stripped."""
    return [ln.strip() for _indent, b in re.findall(r"^( *)" + FENCE + r"[a-z]*\n(.*?)^\1" + FENCE, text, re.S | re.M) for ln in b.split("\n") if ln.strip()]


def strip_fences(text: str) -> str:
    return re.sub(r"^( *)" + FENCE + r".*?^\1" + FENCE, "", text, flags=re.S | re.M)


def bullets(body: str) -> list[str]:
    """The top-level `- ` bullets of a section body, each joined into one line."""
    out: list[str] = []
    cur: str | None = None
    for ln in body.splitlines():
        if ln.startswith("- "):
            if cur is not None:
                out.append(cur)
            cur = ln[2:]
        elif cur is not None and ln.startswith("  "):
            cur += " " + ln.strip()
        elif cur is not None and not ln.strip():
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def parse_pins(pin_text: str) -> dict:
    def grab(name: str, rx: str) -> str | None:
        m = re.search(r"^" + name + r"\s*=\s*" + rx + r"\s*$", pin_text, re.M)
        return m.group(1) if m else None
    counts = re.search(r"^CAT_COUNTS\s*=\s*\{([^}]*)\}", pin_text, re.M)
    return {
        "card_size": grab("CARD_SIZE", r"(\d+)"), "card_sha256": grab("CARD_SHA256", r'"([0-9a-f]{64})"'),
        "config_size": grab("CONFIG_SIZE", r"(\d+)"), "config_sha256": grab("CONFIG_SHA256", r'"([0-9a-f]{64})"'),
        "sources": (re.search(r'"sources":\s*(\d+)', counts.group(1)).group(1) if counts and re.search(r'"sources":\s*(\d+)', counts.group(1)) else None),
        "attribute_rows": (re.search(r'"attribute_rows":\s*(\d+)', counts.group(1)).group(1) if counts and re.search(r'"attribute_rows":\s*(\d+)', counts.group(1)) else None),
    }


def with_commas(n: str) -> str:
    return f"{int(n):,}"


def command_segments(text: str) -> list[tuple[str, str]]:
    """(tool name, the rest of its line from the tool's name on) for every line of the text that names one of the tools."""
    out = []
    for line in text.splitlines():
        for tool in TOOLS:
            i = line.find(tool)
            if i >= 0:
                out.append((tool, line[i + len(tool):]))
    return out


def tool_problems(segments: list[tuple[str, str]], sources: dict[str, str]) -> list[str]:
    problems = []
    for tool, rest in segments:
        kind, _rel = TOOLS[tool]
        src = sources[tool]
        for flag in re.findall(r"(?<![\w$.\\/-])(--?[A-Za-z][\w-]*)", rest):
            if kind == "py":
                ok = re.search(r"[\"']" + re.escape(flag) + r"[\"']", src) is not None
            else:
                ok = re.search(r"\$" + re.escape(flag.lstrip("-")) + r"\b", src, re.I) is not None
            if not ok:
                problems.append(f"{tool}: the flag {flag} is not in the tool's source")
        if tool == "ecco_deploy_preflight.py":
            m = re.match(r"\s+([a-z][a-z-]+)", rest)
            if m and re.search(r"add_parser\(\s*[\"']" + re.escape(m.group(1)) + r"[\"']", src) is None:
                problems.append(f"{tool}: the sub-command {m.group(1)} is not in the tool's source")
    return problems


def quoted_phrases(text: str) -> list[str]:
    """Upper-case output phrases of two words or more in code spans: what a tool is said to print."""
    return re.findall(r"`([A-Z][A-Z]+(?: [A-Z]+)+)`", text)


def expected_names(pins: dict, sources: dict[str, str]) -> dict | None:
    """The exact names, derived: the sha8 from the card's pinned sha256, the rest from the generator's own plan code and the deploy tool's allowlist."""
    gen = sources["geek_mode_dashboard_config.py"]
    tag = re.search(r'^TAG = "([a-z0-9-]+)"', gen, re.M)
    prefix = re.search(r'"resource_url": f"(/[a-z/]+/)\{name\}"', gen)
    rtype = re.search(r'"resource_type": "([a-z]+)"', gen)
    dest_dir = re.search(r"(/config/www/ecco/)", sources["deploy-ha.ps1"])
    if not (tag and prefix and rtype and dest_dir and pins.get("card_sha256")):
        return None
    sha8 = pins["card_sha256"][:8]
    name = f"{tag.group(1)}.{sha8}.js"
    return {"sha8": sha8, "sha256": pins["card_sha256"], "name": name, "url": prefix.group(1) + name, "type": rtype.group(1), "dest": dest_dir.group(1) + name}


# ---------------------------------------------------------------------------------------------------------------------------------
# round 4 rules: the review of round 3 found the suite let these through
# ---------------------------------------------------------------------------------------------------------------------------------
def command_problems(label: str, text: str, names: dict, sources: dict[str, str], runbook_style: bool) -> list[str]:
    """[9] the command lines (the lines of the PowerShell blocks) of a document."""
    p: list[str] = []
    lines = command_lines(text)
    for ln in fence_lines(text):   # every fenced block, whatever its language: a command is a command
        if FORBIDDEN_FLAG.search(ln):
            p.append(f"{label}: a forbidden flag in a command line: {ln[:60]}")
    for para in re.split(r"\n\s*\n", strip_fences(text)):
        for m in FORBIDDEN_FLAG.finditer(para):   # in prose a flag may only be named by a sentence that forbids it, or reports that its warning is absent
            before = plain(para[max(0, m.start() - 100):m.start()])
            if "never pass" not in before and "no warning names" not in before:
                p.append(f"{label}: {m.group(0)} is named in prose outside a sentence that forbids it")
    deploy = [ln for ln in lines if "deploy-ha.ps1" in ln]
    if not deploy:
        p.append(f"{label}: no deploy command line")
    for ln in deploy:
        rest = ln.split("deploy-ha.ps1", 1)[1]
        for flag in re.findall(r"(?<![\w$.\\/-])(-[A-Za-z]+)\b", rest):
            if flag not in DEPLOY_FLAGS_OK:
                p.append(f"{label}: the deploy line has the flag {flag}, which is not one of {', '.join(DEPLOY_FLAGS_OK)}")
        m = re.search(r"-Source (\S+)", rest)
        if not m or m.group(1) != DEPLOY_SOURCE:
            p.append(f"{label}: the deploy line's -Source is not {DEPLOY_SOURCE}")
        m = re.search(r"-Destination (\S+)", rest)
        if not m or m.group(1) not in (names["dest"], names["dest"].replace(names["sha8"], "<sha8>")):
            p.append(f"{label}: the deploy line's -Destination is not the content-addressed name")
        if not re.search(r"-Python \$PY(?!\w)", rest):
            p.append(f"{label}: the deploy line does not pass -Python $PY")
    served = resource = 0
    for ln in lines:
        if "ecco_deploy_preflight.py" not in ln:
            continue
        rest = ln.split("ecco_deploy_preflight.py", 1)[1].split()
        sub = rest[0] if rest else ""
        need = VERIFY_FLAGS.get(sub)
        if need is None:
            p.append(f"{label}: a preflight command line with the sub-command '{sub}', which is not verify-served or verify-resource")
            continue
        served += sub == "verify-served"
        resource += sub == "verify-resource"
        for flag in need:
            if not re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", ln):
                p.append(f"{label}: a {sub} command line without {flag}")
        if PLAN_ARG not in ln:
            p.append(f"{label}: a {sub} command line whose --plan is not {PLAN_ARG}")
        if sub == "verify-resource" and not re.search(r'--before "\$E\\resources-before\.json"', ln):
            p.append(f"{label}: a verify-resource command line whose --before is not the baseline copy resources-before.json")
    if not served or not resource:
        p.append(f"{label}: expected a verify-served and a verify-resource command line (found {served} and {resource})")
    # the generation block makes its output folder first (the generator refuses a missing folder, exit 2)
    gen_blocks = 0
    for i, b in enumerate(powershell_blocks(text), 1):
        bl = [ln.strip() for ln in b.split("\n")]
        gens = [k for k, ln in enumerate(bl) if "geek_mode_dashboard_config.py" in ln and "--out dist\\geek-u1" in ln]
        made = [k for k, ln in enumerate(bl) if re.match(r"New-Item -ItemType Directory -Force dist\\geek-u1\b", ln)]
        gen_blocks += len(gens)
        for g in gens:
            if not any(k < g for k in made):
                p.append(f"{label} block {i}: the generator writes to dist\\geek-u1 before a New-Item makes the folder")
    if not gen_blocks:
        p.append(f"{label}: no generation block")
    if runbook_style:
        # every runbook block is self-contained: it sets $H, $E and $PY itself where it uses them
        for i, b in enumerate(powershell_blocks(text), 1):
            used = set(re.findall(r"\$\{?(E|H|PY)\b", b))
            assigned = set(re.findall(r"^\s*\$(E|H|PY) = ", b, re.M))
            if used - assigned:
                p.append(f"{label} block {i} uses ${', $'.join(sorted(used - assigned))} without setting it")
        if not re.search(r'verify-resource [^\n]*--resources "\$E\\resources-after\.json"', text):
            p.append(f"{label}: no verify-resource command line on the fresh read-back resources-after.json")
        if not re.search(r'verify-resource [^\n]*--resources "\$E\\resources-now\.json"', text):
            p.append(f"{label}: no verify-resource command line on resources-now.json (step 4)")
        # the flags of every tool a runbook block runs exist in that tool's source (what follows a pipe belongs to the next command)
        p += tool_problems([(t, rest.split("|")[0]) for t, rest in command_segments("\n".join(lines))], sources)
    return p


def names_problems(checklist: str, runbook: str, names: dict | None) -> list[str]:
    """[10] the exact names, the type, Require admin, the stop cells and the rollback order stated the same way."""
    if names is None:
        return ["the exact names could not be derived from the pin suite, the generator and the deploy tool"]
    p: list[str] = []
    sha8, url, typ, dest = names["sha8"], names["url"], names["type"], names["dest"]
    for label, text in (("checklist", checklist), ("runbook", runbook)):
        for tok in re.findall(r"/local/ecco/ecco-mode-shell\.([^\s`'\"),;]+?)\.js", text):
            if tok not in (sha8, "<sha8>"):
                p.append(f"{label}: a resource URL with the content address '{tok}', not the card's")
        for tok in re.findall(r"ecco-mode-shell\.([^\s`'\"),;./\\]+)\.js", text):
            if tok not in (sha8, "<sha8>"):
                p.append(f"{label}: a file name with the content address '{tok}', not the card's")
        if re.search(r"\btype[\s:]+(?:js|css|html|javascript(?!\s+module))\b", plain(text)):
            p.append(f"{label}: a resource type that is not module")
    csec = sections(checklist)
    a1 = re.search(r"^\| A1 \|.*$", checklist, re.M)
    a2 = re.search(r"^\| A2 \|.*$", checklist, re.M)
    if not a1 or f"`{dest}`" not in a1.group(0):
        p.append("the checklist's A1 row does not hold the exact destination")
    if not a2 or f"URL `{url}`, type {typ} |" not in a2.group(0):
        p.append("the checklist's A2 row does not hold the exact URL and the type module")
    if not re.search(r"^\| the file on the host \(A1\)[^|\n]*\| `" + re.escape(dest) + r"` \|", runbook, re.M):
        p.append("runbook 5.3: the destination row does not hold the exact destination")
    if not re.search(r"^\| the resource URL \(A2\)[^|\n]*\| `" + re.escape(url) + r"` \|", runbook, re.M):
        p.append("runbook 5.3: the resource URL row does not hold the exact URL")
    if not re.search(r"^\| the resource type \(A2\) \| `" + re.escape(typ) + r"`", runbook, re.M):
        p.append("runbook 5.3: the resource type row does not hold the type module")
    if f"adds a resource with the url {url} (the exact value of 5.3) and the type javascript {typ}" not in plain(subsection(runbook, "5.4")):
        p.append("runbook 5.4: the sentence that names the exact URL and the type JavaScript module is not as pinned")
    if f"one lovelace resource of type {typ} for a1" not in plain(subsection(runbook, "1")):
        p.append("runbook section 1: the A2 row does not say type module")
    if f"sha256 `{names['sha256'][:12]}...`" not in subsection(runbook, "5.3"):
        p.append("runbook 5.3 does not quote the card's sha256 prefix (the first twelve characters) as pinned")
    for where in ("5.3", "13"):
        if f"so <sha8> is {sha8}" not in plain(subsection(runbook, where)):
            p.append(f"runbook {where}: the sentence that says what <sha8> is, is not as pinned")
    if f"(sha8 `{sha8}`)" not in checklist:
        p.append("the checklist's section 1 does not say '(sha8 `<the card's sha8>`)'")
    # Require admin, and the stop cell of each check
    row5 = next((m.group(0) for m in re.finditer(r"^\| 5 \|.*$", csec.get("4", ""), re.M)), "")
    if "require admin" not in plain(row5):
        p.append("checklist step 5 does not say Require admin")
    if "switches require admin on, and creates it" not in plain(subsection(runbook, "5.5")):
        p.append("runbook 5.5 does not say that the owner switches Require admin on")
    rows3 = {m.group(1).strip().lower(): m.group(0) for m in re.finditer(r"^\| \*\*([^*|]+)\*\* \|.*$", csec.get("3", ""), re.M)}
    if "require admin" not in plain(rows3.get("admin-only dashboard setup", "")):
        p.append("the checklist's admin-only row does not say Require admin")
    for check_name, key in CHECK_STOP_KEYS.items():
        row = rows3.get(check_name)
        cells = [c.strip() for c in row.strip().strip("|").split("|")] if row else []
        if len(cells) < 3 or key not in plain(cells[-1]):
            p.append(f"the Stop cell of the check '{check_name}' does not hold '{key}'")
    # the rollback order, stated the same way in the runbook's section 7 and in the checklist's heading
    if "newest first (the dashboard a3, then the resource a2, then the file a1)" not in plain(subsection(runbook, "7")):
        p.append("runbook section 7 does not state the rollback order as 'newest first (the dashboard A3, then the resource A2, then the file A1)'")
    head6 = re.search(r"^## 6\. (.*)$", checklist, re.M)
    labels = ["A" + n for n in re.findall(r"\bA([123])\b", head6.group(1))] if head6 else []
    if labels != ROLLBACK_ORDER or not head6 or "newest first" not in head6.group(1).lower():
        p.append(f"the checklist's section 6 heading does not say 'newest first' with the order {ROLLBACK_ORDER} (it names {labels})")
    return p


def pinned_problems(checklist: str, runbook: str) -> list[str]:
    """[11] the sentences added after the review of round 3 are in their sections, and the claims they replaced are gone."""
    docs = {"checklist": checklist, "runbook": runbook}
    cache: dict[tuple[str, str | None], str] = {}

    def scope_text(doc: str, scope: str | None) -> str:
        if (doc, scope) not in cache:
            cache[(doc, scope)] = plain(docs[doc] if scope is None else subsection(docs[doc], scope))
        return cache[(doc, scope)]

    p = []
    for doc, scope, phrase in PINNED:
        text = scope_text(doc, scope)
        if not text:
            p.append(f"the {doc} has no section {scope}")
        elif plain(phrase) not in text:
            p.append(f"the {doc} {scope}: the sentence '{phrase[:70]}' is missing")
    for doc, scope, phrase in FORBIDDEN_PHRASES:
        if plain(phrase) in scope_text(doc, scope):
            p.append(f"the {doc}{'' if scope is None else ' ' + scope}: the claim '{phrase}' is still there")
    return p


def node_problems(runbook: str, node_src: str) -> list[str]:
    """[12] the Node generated-config test: named with ECCO_PYTHON and 0 skipped, and the runbook's claims about it are true of its source."""
    p = []
    cmds = [ln for ln in runbook.splitlines() if "generated-config.test.mjs" in ln and "node --test" in ln]
    if len(cmds) < 3:
        p.append(f"the runbook names the Node generated-config command {len(cmds)} times (expected 5.0 and the two rows of section 13)")
    for ln in cmds:
        if "ECCO_PYTHON=<PY>" not in ln:
            p.append("a Node generated-config command without ECCO_PYTHON=<PY>")
        if ln.startswith("|") and "0 skipped" not in ln:
            p.append("a section 13 row for the Node generated-config test without '0 skipped'")
    if "process.env.ECCO_PYTHON || 'python'" not in node_src:
        p.append("the Node test no longer takes its interpreter from ECCO_PYTHON (default python): the runbook says it does")
    if "SKIPPED" not in node_src:
        p.append("the Node test no longer says SKIPPED when it cannot run the generator")
    if len(re.findall(r"\{ skip \}", node_src)) != 5:
        p.append("the Node test no longer has exactly five skippable tests: the runbook says 5 of 5")
    return p


def coverage_problems(checklist: str, runbook: str) -> list[str]:
    """[13] checklist section 8 covers every bullet of runbook section 9 (a keyword per bullet), and no bullet is without a keyword."""
    p = []
    items = bullets(sections(runbook).get("9", ""))
    sec8 = plain(sections(checklist).get("8", ""))
    if not items:
        p.append("runbook section 9 has no bullets")
    for item in items:
        hits = [phrase for phrase, _kw in COVERAGE if plain(phrase) in plain(item)]
        if not hits:
            p.append(f"runbook section 9 has a bullet without a coverage keyword: '{plain(item)[:60]}'")
        elif len(hits) > 1:
            p.append(f"runbook section 9: the bullet '{plain(item)[:40]}' matches {len(hits)} coverage entries")
    for phrase, keywords in COVERAGE:
        if sum(plain(phrase) in plain(item) for item in items) != 1:
            p.append(f"the coverage entry '{phrase[:50]}' matches no bullet (or more than one) of runbook section 9")
        for kw in keywords:
            if plain(kw) not in sec8:
                p.append(f"checklist section 8 does not cover runbook section 9 '{phrase[:40]}' (no '{kw}')")
    return p


# ---------------------------------------------------------------------------------------------------------------------------------
# the analysis: every rule gives the list of its problems; an empty list is a pass
# ---------------------------------------------------------------------------------------------------------------------------------
def analyse(checklist: str, runbook: str, pins: dict, sources: dict[str, str], node_src: str = "") -> dict[str, list[str]]:
    r: dict[str, list[str]] = {}
    cl, rb = fold(checklist), fold(runbook)
    csec, rsec = sections(checklist), sections(runbook)

    # [1] the pins
    p = []
    if not pins.get("card_sha256") or not pins.get("config_sha256"):
        p.append("the pins could not be read from the pin suite")
    else:
        if pins["card_sha256"][:8] not in checklist:
            p.append("the card's sha8 is not in the checklist")
        if not re.search(r"ecco-mode-shell\." + pins["card_sha256"][:8] + r"\.js", checklist):
            p.append("the content-addressed file name is not in the checklist")
        if pins["card_sha256"] not in checklist:
            p.append("the card's full sha256 is not in the checklist")
        if pins["config_sha256"] not in checklist:
            p.append("the generated configuration's sha256 is not in the checklist")
        for what, size in (("card", pins["card_size"]), ("generated configuration", pins["config_size"])):
            if not size or (with_commas(size) not in checklist and size not in checklist):
                p.append(f"the {what}'s size is not in the checklist")
        for what in ("sources", "attribute_rows"):
            if not pins.get(what) or not re.search(r"(?<![\d,])" + pins[what] + r"(?![\d,])", checklist):
                p.append(f"the catalogue count {what} is not in the checklist")
        # the card's sha256 is given in full everywhere it appears with eight or more characters of it, and no other 64-hex string is there
        allowed = {pins["card_sha256"], pins["config_sha256"]}
        stray = {h.lower() for h in HEX64.findall(checklist)} - allowed
        if stray:
            p.append(f"{len(stray)} hash(es) in the checklist that are not the two pinned ones")
    r["pins"] = p

    # [2] the five checks
    sec3 = csec.get("3", "")
    names = [m.group(1).strip().lower() for m in re.finditer(r"^\| \*\*([^*|]+)\*\* \|", sec3, re.M)]
    r["checks"] = [f"the check '{c}' is not a row of the checks table" for c in OWNER_CHECKS if c not in names]

    # [3] cited sections exist
    p = []
    cited = set()
    for group in re.findall(r"\brunbook (\d+(?:\.\d+)?(?:,\s*\d+(?:\.\d+)?)*)", checklist, re.I):
        cited |= {n.strip() for n in group.split(",")}
    for num in sorted(cited):
        if not has_heading(runbook, num):
            p.append(f"the checklist cites runbook {num}, which is not a heading of the runbook")
    for num in sorted(set(re.findall(r"(?<!runbook )(?<!\w)section (\d+)\b", checklist, re.I))):
        if num not in csec:
            p.append(f"the checklist cites its own section {num}, which does not exist")
    r["sections"] = p

    # [4] flags, sub-commands and quoted tool phrases
    p = tool_problems(command_segments(checklist), sources)
    seen_tools = {t for t, _ in command_segments(checklist)}
    if not seen_tools >= {"geek_mode_dashboard_config.py", "ecco_deploy_preflight.py", "deploy-ha.ps1"}:
        p.append("the checklist names too few tools to be checked (expected the generator, the preflight and the deploy tool)")
    # what a tool prints: the tools' sources, and the runbook's own PowerShell blocks (the baseline block prints EXACT / NOT EXACT)
    everything = "\n".join(sources.values()) + "\n" + "\n".join(powershell_blocks(runbook))
    for phrase in quoted_phrases(checklist):
        if phrase not in everything:
            p.append(f"the checklist quotes `{phrase}`, which no tool prints")
    if "`Restart     : no`" in checklist and "Restart     : " not in sources["deploy-ha.ps1"]:
        p.append("the padded `Restart     : no` line is not what the deploy tool prints")
    r["tools"] = p

    # [5] every PowerShell block starts with cls
    p = []
    for label, text in (("checklist", checklist), ("runbook", runbook)):
        blocks = powershell_blocks(text)
        if not blocks:
            p.append(f"the {label} has no PowerShell block")
        for i, b in enumerate(blocks, 1):
            first = next((ln.strip() for ln in b.split("\n") if ln.strip()), "")
            if first != "cls":
                p.append(f"{label} block {i} starts with {first[:30]!r}, not cls")
    r["cls"] = p

    # [6] the plain statements
    r["statements"] = [f"the sentence '{name}' is missing" for name, phrase in STATEMENTS.items() if phrase not in cl]

    # [7] words, addresses, tokens, entity ids, characters
    p = []
    for label, text in (("checklist", checklist), ("runbook", runbook)):
        low = fold(text)
        p += [f"{label}: the forbidden phrase '{w}'" for w in FORBIDDEN_WORDS if w in low]
        if IPV4.search(text):
            p.append(f"{label}: an IPv4 address")
        if TOKEN.search(text):
            p.append(f"{label}: a token shape")
        if ENTITY_ID.search(text):
            p.append(f"{label}: an entity id ({ENTITY_ID.search(text).group(0)[:12]}...)")
        if EMAIL.search(text) and not re.search(r"@users\.noreply\.github\.com|noreply@anthropic\.com", EMAIL.search(text).group(0)):
            p.append(f"{label}: an e-mail address")
        if not text.isascii():
            p.append(f"{label}: a non-ASCII character")
    hex_blobs = {h.lower() for h in HEX_BLOB.findall(checklist)} - {pins.get("card_sha256"), pins.get("config_sha256")}
    if hex_blobs:
        p.append("checklist: a hash-like blob that is not a pinned hash")
    if len(checklist.splitlines()) > MAX_CHECKLIST_LINES:
        p.append(f"the checklist has {len(checklist.splitlines())} lines (limit {MAX_CHECKLIST_LINES})")
    r["hygiene"] = p

    # [8] the checklist and the runbook agree
    p = []
    sec4_rb, sec4_cl = rsec.get("4", ""), csec.get("4", "")
    rb_rows = {int(m.group(1)): m.group(0) for m in re.finditer(r"^\| (\d) \|.*$", sec4_rb, re.M)}
    cl_rows = {int(m.group(1)): m.group(0) for m in re.finditer(r"^\| (\d) \|.*$", sec4_cl, re.M)}
    if sorted(rb_rows) != list(range(10)):
        p.append(f"the runbook's step table has the steps {sorted(rb_rows)}, not 0 to 9")
    if sorted(cl_rows) != sorted(rb_rows):
        p.append(f"the checklist has the steps {sorted(cl_rows)}, the runbook {sorted(rb_rows)}")
    for n, word in STEP_WORDS.items():
        if n in rb_rows and word not in rb_rows[n].lower():
            p.append(f"runbook step {n} does not mention '{word}'")
        if n in cl_rows and word not in cl_rows[n].lower():
            p.append(f"checklist step {n} does not mention '{word}'")
        if n in cl_rows and not re.search(r"\brunbook 5\." + str(n) + r"\b", cl_rows[n]):
            p.append(f"checklist step {n} does not cite runbook 5.{n}")
        if not re.search(r"^### 5\." + str(n) + r" Step " + str(n) + r"\b", runbook, re.M):
            p.append(f"the runbook has no section '5.{n} Step {n}'")
    for n in LIVE_GO_STEPS:
        if n in cl_rows and "your go" not in cl_rows[n].lower():
            p.append(f"checklist step {n} does not say that the owner's go is needed")
        if n in rb_rows and not re.search(r"\*\*yes\*\*", rb_rows[n]):
            p.append(f"runbook step {n} no longer asks for the owner's authorisation")
    order_rb = re.findall(r"^\d\. \*\*(A[123])\b", rsec.get("7", ""), re.M)
    order_cl = re.findall(r"^\d\. \*\*(A[123])\b", csec.get("6", ""), re.M)
    if order_rb != ROLLBACK_ORDER:
        p.append(f"the runbook's rollback order is {order_rb}, not {ROLLBACK_ORDER}")
    if order_cl != order_rb:
        p.append(f"the checklist's rollback order is {order_cl}, the runbook's {order_rb}")
    r["agreement"] = p

    # [9] to [13] (round 4)
    exact = expected_names(pins, sources)
    if exact is None:
        r["commands"] = ["the exact names could not be derived (pin suite, generator, deploy tool)"]
    else:
        r["commands"] = command_problems("checklist", checklist, exact, sources, False) + command_problems("runbook", runbook, exact, sources, True)
    r["names"] = names_problems(checklist, runbook, exact)
    r["pinned"] = pinned_problems(checklist, runbook)
    r["node"] = node_problems(runbook, node_src)
    r["coverage"] = coverage_problems(checklist, runbook)
    return r


RULES = ("pins", "checks", "sections", "tools", "cls", "statements", "hygiene", "agreement", "commands", "names", "pinned", "node", "coverage")
RULE_TITLES = {
    "pins": "[1] the pins are in the checklist exactly as the pin suite holds them",
    "checks": "[2] the five checks of the owner's directive are present by name",
    "sections": "[3] every section the checklist cites exists",
    "tools": "[4] every flag, sub-command and quoted output phrase of the checklist exists in the tools",
    "cls": "[5] every PowerShell block starts with cls",
    "statements": "[6] the three plain statements are there",
    "hygiene": "[7] no forbidden word, address, token, entity id, hash blob or non-ASCII character; the checklist is short",
    "agreement": "[8] the step numbers, the live-step go and the rollback order agree with the runbook",
    "commands": "[9] command lines: no -Restart, -SkipValidation or -AllowDirtyWorkingTree; the deploy, verify and generation lines are complete; runbook blocks are self-contained",
    "names": "[10] the exact URL, file name and type module, Require admin, each check's stop and the rollback order are stated as pinned",
    "pinned": "[11] the sentences added after the review of round 3 are in their sections and the claims they replaced are gone",
    "node": "[12] the Node generated-config test is named with ECCO_PYTHON and 0 skipped, and the runbook's claims about it are true of its source",
    "coverage": "[13] checklist section 8 covers every bullet of runbook section 9",
}


def fired(result: dict[str, list[str]]) -> set[str]:
    return {k for k, v in result.items() if v}


# ---------------------------------------------------------------------------------------------------------------------------------
# the mutants (all in memory); they are built here so that a scratch script can run them against another version of the rules
# ---------------------------------------------------------------------------------------------------------------------------------
def on_line(text: str, needle: str, fn, nth: int = 0) -> str:
    """Apply fn to the nth line that holds `needle`; the rest of the text is untouched."""
    lines = text.split("\n")
    seen = -1
    for i, ln in enumerate(lines):
        if needle in ln:
            seen += 1
            if seen == nth:
                lines[i] = fn(ln)
                break
    return "\n".join(lines)


def edit_block(text: str, marker: str, fn) -> str:
    """Apply fn to the body of the first PowerShell block that holds `marker`."""
    done = [False]

    def sub(m):
        if not done[0] and marker in m.group(2):
            done[0] = True
            return m.group(1) + FENCE + "powershell\n" + fn(m.group(2)) + m.group(1) + FENCE
        return m.group(0)
    return re.sub(r"^( *)" + FENCE + r"powershell\n(.*?)^\1" + FENCE, sub, text, flags=re.S | re.M)


def kill_words(text: str, phrase: str, scope: str | None = None) -> str:
    """Replace the first occurrence of a phrase (whatever its line breaks and markup between the words), inside a section if one is named."""
    # markdown emphasis and code ticks may sit between any two characters of the raw text (`**Save**,` is the plain `save,`)
    rx = "".join(r"[\s*`]+" if ch == " " else re.escape(ch) + r"[*`]*" for ch in plain(phrase))
    lo, hi = 0, len(text)
    if scope is not None:
        span = subsection_span(text, scope)
        if span is None:
            return text
        lo, hi = span
    return text[:lo] + re.sub(rx, "REMOVED", text[lo:hi], count=1, flags=re.I) + text[hi:]


def kill_stop(text: str, title: str, key: str) -> str:
    def fn(ln: str) -> str:
        cells = ln.split("|")
        cells[-2] = re.sub(re.escape(key), "REMOVED", cells[-2], flags=re.I)
        return "|".join(cells)
    return on_line(text, "| **" + title + "** |", fn)


def make_mutants(pins: dict, checklist: str, runbook: str) -> list[tuple[str, str, object, str]]:
    """(target, name, mutate, rule that must fire). target is 'checklist' or 'runbook'."""
    # samples that would trip a scanner are assembled here, so this file holds none
    sample_addr = "192" + "." + "168" + "." + "1" + "." + "5"
    sample_token = "ghp" + "_" + "a" * 36
    sample_entity = "sen" + "sor" + "." + "some_value"
    sha8 = pins["card_sha256"][:8]
    wrong8 = ("0" if sha8[0] != "0" else "1") + sha8[1:]

    def flip(h: str) -> str:
        return h[:-1] + ("0" if h[-1] != "0" else "1")

    def drop_first_cls(text: str) -> str:
        return text.replace(FENCE + "powershell\ncls\n", FENCE + "powershell\n", 1)

    def swap_rollback(text: str) -> str:
        a = re.search(r"^1\. \*\*A3\b", text, re.M)
        b = re.search(r"^2\. \*\*A2\b", text, re.M)
        assert a and b
        return text[:a.start()] + "1. **A2" + text[a.end():b.start()] + "2. **A3" + text[b.end():]

    def remove_row(text: str, n: int) -> str:
        return re.sub(r"^\| " + str(n) + r" \|.*\n", "", text, count=1, flags=re.M)

    def kill(text: str, *phrases: str) -> str:
        for ph in phrases:
            text = re.sub(re.escape(ph), "REMOVED", text, flags=re.I)
        return text

    dep = "deploy-ha.ps1 -Source"
    verify_resource, verify_served = "ecco_deploy_preflight.py verify-resource", "ecco_deploy_preflight.py verify-served"

    def no_before(ln: str) -> str:
        return re.sub(r' --before "[^"]*"', "", ln)

    def no_base_url(ln: str) -> str:
        return re.sub(r" --base-url <[^>]*>", "", ln)

    out: list[tuple[str, str, object, str]] = []

    def add(target: str, name: str, fn, rule: str) -> None:
        out.append((target, name, fn, rule))

    # --- the original mutants (round 3)
    for name, fn, rule in [
        ("M1 a wrong sha8", lambda t: t.replace(sha8, wrong8), "pins"),
        ("M2 a wrong card sha256", lambda t: t.replace(pins["card_sha256"], flip(pins["card_sha256"])), "pins"),
        ("M3 a wrong generated-configuration sha256", lambda t: t.replace(pins["config_sha256"], flip(pins["config_sha256"])), "pins"),
        ("M4 a wrong generated-configuration size", lambda t: t.replace(with_commas(pins["config_size"]), "147,179"), "pins"),
        ("M5 a missing check (correct-dashboard targeting)", lambda t: kill(t, "Correct-dashboard targeting"), "checks"),
        ("M6 a missing check (backup)", lambda t: t.replace("| **Backup** |", "| Backup |"), "checks"),
        ("M7 a dropped cls", drop_first_cls, "cls"),
        ("M8 a cited runbook section that does not exist", lambda t: t.replace("runbook 5.3", "runbook 5.33", 1), "sections"),
        ("M9 a cited runbook section that is not there at all", lambda t: t + "\nSee runbook 14 for more.\n", "sections"),
        ("M10 a forbidden word (safe to install)", lambda t: t + "\nThis is safe to install.\n", "hygiene"),
        ("M11 a forbidden word (guaranteed)", lambda t: t + "\nIt is guaranteed.\n", "hygiene"),
        ("M12 a forbidden word (fully enforced)", lambda t: t + "\nThe gate is fully enforced.\n", "hygiene"),
        ("M13 a changed rollback order", swap_rollback, "agreement"),
        ("M14 the never-run statement dropped", lambda t: kill(t, "never run in a real Home Assistant"), "statements"),
        ("M15 the global-resource statement dropped", lambda t: kill(t, "A module resource is global"), "statements"),
        ("M16 the admin-only limit dropped", lambda t: kill(t, "not a security boundary"), "statements"),
        ("M17 a flag that the tool does not have", lambda t: t.replace("--verify-storage", "--verify-store"), "tools"),
        ("M18 a sub-command that the tool does not have", lambda t: t.replace("ecco_deploy_preflight.py verify-served", "ecco_deploy_preflight.py verify-serve", 1), "tools"),
        ("M19 a quoted output phrase that no tool prints", lambda t: t.replace("STORED CONFIGURATION EQUALS THE GENERATED ONE", "STORED CONFIGURATION IS FINE"), "tools"),
        ("M20 a removed step (5)", lambda t: remove_row(t, 5), "agreement"),
        ("M21 a step row that lost its owner's go (3)", lambda t: re.sub(r"(^\| 3 \|.*?)your go", r"\1the coordinator", t, count=1, flags=re.M), "agreement"),
        ("M22 an address (at the end of a sentence)", lambda t: t + f"\nThe host is {sample_addr}.\n", "hygiene"),
        ("M22b an address (in a URL with a port)", lambda t: t + f"\nOpen http://{sample_addr}:8123/ now.\n", "hygiene"),
        ("M23 a token", lambda t: t + f"\nThe key is {sample_token}.\n", "hygiene"),
        ("M24 an entity id", lambda t: t + f"\nThe helper is {sample_entity}.\n", "hygiene"),
        ("M25 an extra hash-like blob", lambda t: t + "\n" + "ab" * 32 + "\n", "pins"),
        ("M26 a non-ASCII character", lambda t: t + "\nA " + chr(0xB7) + " dot.\n", "hygiene"),
        ("M27 a checklist that grew past the limit", lambda t: t + "\n" * (MAX_CHECKLIST_LINES + 5), "hygiene"),
    ]:
        add("checklist", name, fn, rule)
    for name, fn, rule in [
        ("R1 the runbook's rollback order changed", swap_rollback, "agreement"),
        ("R2 a runbook heading that the checklist cites is gone", lambda t: t.replace("### 5.3 Step 3", "### 5.3x Step 3", 1), "sections"),
        ("R3 a runbook PowerShell block without cls", drop_first_cls, "cls"),
        ("R4 a forbidden word in the runbook", lambda t: t + "\nThis is safe to install.\n", "hygiene"),
        ("R5 a runbook step row removed", lambda t: remove_row(t, 4), "agreement"),
    ]:
        add("runbook", name, fn, rule)

    # --- F1: the mutants of the review of round 3, in the checklist
    add("checklist", "F1 -Restart added to the checklist's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -Restart"), "commands")
    add("checklist", "F1 -SkipValidation added to the checklist's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -SkipValidation"), "commands")
    add("checklist", "F1 -AllowDirtyWorkingTree added to the checklist's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -AllowDirtyWorkingTree"), "commands")
    add("checklist", "F1 a made-up flag added to the checklist's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -Force"), "commands")
    add("checklist", "F1 -Restart in a fenced block that is not PowerShell", lambda t: t + "\n" + FENCE + "text\n.\\tools\\deploy-ha.ps1 -Restart\n" + FENCE + "\n", "commands")
    add("checklist", "F1 -Restart recommended in the checklist's prose", lambda t: t + "\nIf the card does not load, run the deploy with -Restart.\n", "commands")
    add("checklist", "F1 the sha8 mistyped in the checklist's A2 row", lambda t: on_line(t, "| A2 |", lambda ln: ln.replace(sha8, wrong8)), "names")
    add("checklist", "F1 the sha8 mistyped in the checklist's A1 row", lambda t: on_line(t, "| A1 |", lambda ln: ln.replace(sha8, wrong8)), "names")
    add("checklist", "F1 the sha8 mistyped in the checklist's deploy line only", lambda t: on_line(t, dep, lambda ln: ln.replace(sha8, wrong8)), "commands")
    add("checklist", "F1 the sha8 mistyped in the checklist's section 1 pin line", lambda t: t.replace("(sha8 `" + sha8 + "`)", "(sha8 `" + wrong8 + "`)", 1), "names")
    add("checklist", "F1 a query string on the URL of the checklist's A2 row", lambda t: on_line(t, "| A2 |", lambda ln: ln.replace(".js`", ".js?v=1`")), "names")
    add("checklist", "F1 type module changed to type js in the checklist's A2 row", lambda t: on_line(t, "| A2 |", lambda ln: ln.replace("type module", "type js")), "names")
    add("checklist", "F1 Require admin dropped from checklist step 5", lambda t: on_line(t, "| 5 | you |", lambda ln: ln.replace("Require admin on, ", "")), "names")
    add("checklist", "F1 Require admin dropped from the admin-only check row", lambda t: t.replace("\"Require admin\" on at creation", "it is on at creation"), "names")
    add("checklist", "F1 --before dropped from the checklist's verify-resource line", lambda t: on_line(t, verify_resource, no_before), "commands")
    add("checklist", "F1 --base-url dropped from the checklist's verify-resource line", lambda t: on_line(t, verify_resource, no_base_url), "commands")
    add("checklist", "F1 --base-url dropped from the checklist's verify-served line", lambda t: on_line(t, verify_served, no_base_url), "commands")
    add("checklist", "F1 --before of the checklist's verify-resource line pointed at the later read-back", lambda t: on_line(t, verify_resource, lambda ln: ln.replace("resources-before.json", "resources-now.json")), "commands")
    add("checklist", "F1 --resources dropped from the checklist's verify-resource line", lambda t: on_line(t, verify_resource, lambda ln: re.sub(r' --resources "[^"]*"', "", ln)), "commands")
    add("checklist", "F1 the plan of the checklist's verify-served line pointed elsewhere", lambda t: on_line(t, verify_served, lambda ln: ln.replace("plan.json", "other.json")), "commands")
    add("checklist", "F1 the require_admin stop dropped from the admin-only check row", lambda t: kill_stop(t, "Admin-only dashboard setup", "require_admin"), "names")
    add("checklist", "F1 the stop dropped from the exact-resource check row", lambda t: kill_stop(t, "Exact module resource", "RESOURCE VERIFIED"), "names")
    add("checklist", "F1 the stop dropped from the backup check row", lambda t: kill_stop(t, "Backup", "no protected backup"), "names")
    add("checklist", "F1 the stop dropped from the rollback check row", lambda t: kill_stop(t, "Rollback", "re-check"), "names")
    add("checklist", "F1 the stop dropped from the targeting check row", lambda t: kill_stop(t, "Correct-dashboard targeting", "pre-save check"), "names")
    add("checklist", "F1 the rollback order swapped in the checklist's heading", lambda t: t.replace("A3 the dashboard, A2 the resource, A1 the file", "A1 the file, A2 the resource, A3 the dashboard"), "names")
    add("checklist", "F1 'newest first' dropped from the checklist's heading", lambda t: t.replace("Rollback, newest first:", "Rollback:"), "names")
    # --- F6: the generation block of the checklist makes its folder
    add("checklist", "F6 the New-Item line dropped from the checklist's generation block", lambda t: t.replace("New-Item -ItemType Directory -Force dist\\geek-u1 | Out-Null\n", "", 1), "commands")
    add("checklist", "F6 the New-Item line moved after the generator in the checklist's block",
        lambda t: edit_block(t, "--out dist\\geek-u1", lambda b: re.sub(r"^(New-Item[^\n]*\n)(.*?\n)", r"\2\1", b, count=1, flags=re.S | re.M)), "commands")

    # --- F1: the mutants of the review of round 3, in the runbook
    add("runbook", "F1 -Restart added to the runbook's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -Restart"), "commands")
    add("runbook", "F1 -SkipValidation added to the runbook's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -SkipValidation"), "commands")
    add("runbook", "F1 -AllowDirtyWorkingTree added to the runbook's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -AllowDirtyWorkingTree"), "commands")
    add("runbook", "F1 -Restart recommended inside the paragraph that forbids it", lambda t: t.replace("so this is a rule of the runbook", "so this is a rule of the runbook (use -Restart when the card does not load)", 1), "commands")
    add("runbook", "F1 -Restart recommended in a runbook paragraph that does not forbid it", lambda t: t + "\nIf the card does not load, run the deploy with -Restart.\n", "commands")
    add("runbook", "F1 the sha8 mistyped in the runbook's 5.3 resource URL row", lambda t: on_line(t, "| the resource URL (A2)", lambda ln: ln.replace(sha8, wrong8)), "names")
    add("runbook", "F1 the sha8 mistyped in the runbook's 5.3 destination row", lambda t: on_line(t, "| the file on the host (A1)", lambda ln: ln.replace(sha8, wrong8)), "names")
    add("runbook", "F1 the sha8 mistyped in the runbook's 5.4 sentence", lambda t: on_line(t, "adds a resource with the URL", lambda ln: ln.replace(sha8, wrong8)), "names")
    add("runbook", "F1 a query string on the URL of the runbook's 5.4 sentence", lambda t: on_line(t, "adds a resource with the URL", lambda ln: ln.replace(".js` (the exact", ".js?v=1` (the exact")), "names")
    add("runbook", "F1 the sha8 mistyped in the runbook's 5.3 reminder text", lambda t: t.replace("with URL /local/ecco/ecco-mode-shell.<sha8>.js", "with URL /local/ecco/ecco-mode-shell." + wrong8 + ".js", 1), "names")
    add("runbook", "F1 the sha256 prefix mistyped in the runbook's 5.3 sentence", lambda t: t.replace("(sha256 `" + pins["card_sha256"][:12] + "...`", "(sha256 `" + wrong8 + pins["card_sha256"][8:12] + "...`", 1), "names")
    add("runbook", "F1 the sha8 mistyped in the runbook's 5.3 sentence that says what <sha8> is", lambda t: t.replace("so `<sha8>` is `" + sha8 + "`", "so `<sha8>` is `" + wrong8 + "`", 1), "names")
    add("runbook", "F1 the sha8 mistyped in the runbook's section 13 table row", lambda t: on_line(t, "| the destination file name", lambda ln: ln.replace("(so `<sha8>` is `" + sha8 + "`)", "(so `<sha8>` is `" + wrong8 + "`)")), "names")
    add("runbook", "F1 a literal wrong sha8 in the runbook's deploy line", lambda t: on_line(t, dep, lambda ln: ln.replace("<sha8>", wrong8)), "commands")
    add("runbook", "F1 type module changed to js in the runbook's 5.3 type row", lambda t: on_line(t, "| the resource type (A2)", lambda ln: ln.replace("`module`", "`js`")), "names")
    add("runbook", "F1 JavaScript module changed in the runbook's 5.4 sentence", lambda t: t.replace("the type **JavaScript\nmodule**", "the type **JavaScript\nfile**", 1), "names")
    add("runbook", "F1 type module changed to js in the runbook's section 1 A2 row", lambda t: t.replace("resource of type `module` for A1", "resource of type `js` for A1", 1), "names")
    add("runbook", "F1 Require admin dropped from runbook 5.5", lambda t: t.replace("switches **Require admin** on", "switches the setting on", 1), "names")
    add("runbook", "F1 --before dropped from the runbook's 5.4 verify-resource line", lambda t: on_line(t, verify_resource, no_before, 0), "commands")
    add("runbook", "F1 --before of the runbook's 5.4 verify-resource line pointed at the later read-back", lambda t: on_line(t, verify_resource, lambda ln: ln.replace("resources-before.json", "resources-now.json"), 0), "commands")
    add("runbook", "F1 --base-url dropped from the runbook's 5.4 verify-resource line", lambda t: on_line(t, verify_resource, no_base_url, 0), "commands")
    add("runbook", "F1 --base-url dropped from the runbook's verify-served line", lambda t: on_line(t, verify_served, no_base_url), "commands")
    add("runbook", "F1 the runbook section 7 order wording swapped", lambda t: t.replace("(the dashboard A3, then the resource A2, then the file A1)", "(the dashboard A1, then the resource A2, then the file A3)", 1), "names")
    add("runbook", "F1 'newest first' changed to 'oldest first' in runbook section 7", lambda t: t.replace("newest first (the dashboard", "oldest first (the dashboard", 1), "names")
    add("runbook", "F1 a flag that the tool does not have in a runbook command line", lambda t: t.replace("geek_mode_dashboard_config.py --verify-storage", "geek_mode_dashboard_config.py --verify-store", 1), "commands")
    add("runbook", "F1 a made-up flag added to the runbook's deploy line", lambda t: on_line(t, dep, lambda ln: ln + " -Force"), "commands")
    add("runbook", "F6 the New-Item line dropped from the runbook's generation block", lambda t: t.replace("New-Item -ItemType Directory -Force dist\\geek-u1 | Out-Null\n", "", 1), "commands")
    # --- F7: the re-run of the gate in 5.6
    add("runbook", "F7 the 5.6 re-run reads resources-now.json again", lambda t: on_line(t, "--resources \"$E\\resources-after.json\"", lambda ln: ln.replace("resources-after.json", "resources-now.json")), "commands")
    add("runbook", "F7 --before dropped from the runbook's 5.6 re-run line", lambda t: on_line(t, "--resources \"$E\\resources-after.json\"", no_before), "commands")
    add("runbook", "F7 --base-url dropped from the runbook's 5.6 re-run line", lambda t: on_line(t, "--resources \"$E\\resources-after.json\"", no_base_url), "commands")
    add("runbook", "F7 the 5.6 re-run block no longer sets $E", lambda t: edit_block(t, "--resources \"$E\\resources-after.json\"", lambda b: re.sub(r"^\$E = [^\n]*\n", "", b, flags=re.M)), "commands")
    add("runbook", "F7 the 5.6 re-run block no longer sets $PY", lambda t: edit_block(t, "--resources \"$E\\resources-after.json\"", lambda b: re.sub(r"^\$PY = [^\n]*\n", "", b, flags=re.M)), "commands")
    # --- F3: the Node generated-config test names its interpreter
    add("runbook", "F3 ECCO_PYTHON dropped from the round 3 Node row", lambda t: on_line(t, "| the Node suite that runs the generator", lambda ln: ln.replace("ECCO_PYTHON=<PY> ", ""), 0), "node")
    add("runbook", "F3 ECCO_PYTHON dropped from the round 2 Node row", lambda t: on_line(t, "| the Node suite that runs the generator", lambda ln: ln.replace("ECCO_PYTHON=<PY> ", ""), 1), "node")
    add("runbook", "F3 ECCO_PYTHON dropped from the 5.0 command", lambda t: on_line(t, "`ECCO_PYTHON=<PY> node --test", lambda ln: ln.replace("ECCO_PYTHON=<PY> ", "", 1), 0), "node")
    add("runbook", "F3 '0 skipped' dropped from the round 3 Node row", lambda t: on_line(t, "| the Node suite that runs the generator", lambda ln: ln.replace(", 0 skipped", ""), 0), "node")
    add("runbook", "F3 '0 skipped' dropped from the round 2 Node row", lambda t: on_line(t, "| the Node suite that runs the generator", lambda ln: ln.replace(", 0 skipped", ""), 1), "node")
    # --- F4: a new section 9 bullet without coverage
    add("runbook", "F4 a new bullet in runbook section 9 that the checklist does not cover", lambda t: t.replace("\n## 10.", "\n- A new limit that nobody has written into the checklist.\n\n## 10.", 1), "coverage")
    add("runbook", "F4 a section 9 bullet whose words changed so that its keyword no longer matches", lambda t: t.replace("Known console noise:", "Known browser noise:", 1), "coverage")
    # the pinned sentences and the coverage keywords: the removal of each is killed
    for n, (doc, scope, phrase) in enumerate(PINNED, 1):
        add(doc, f"P{n} the sentence '{phrase[:46]}' removed from the {doc} {scope}", lambda t, s=scope, ph=phrase: kill_words(t, ph, s), "pinned")
    for n, (doc, scope, phrase) in enumerate(FORBIDDEN_PHRASES, 1):
        if scope is None:
            add(doc, f"Q{n} the claim '{phrase}' put back into the {doc}", lambda t, ph=phrase: t + "\nNothing was written (" + ph + ").\n", "pinned")
        else:
            add(doc, f"Q{n} the claim '{phrase}' put back into the {doc} {scope}",
                lambda t, s=scope, ph=phrase: (t[:subsection_span(t, s)[1]] + "\nA line that says " + ph + ".\n" + t[subsection_span(t, s)[1]:]), "pinned")
    for n, (phrase, keywords) in enumerate(COVERAGE, 1):
        for kw in keywords:
            add("checklist", f"C{n} the keyword '{kw}' removed from checklist section 8", lambda t, k=kw: kill_words(t, k, "8"), "coverage")
    return out


NODE_MUTANTS = [   # mutants of the Node test's source (the runbook says what it does: these show the claim is checked against it)
    ("N1 the Node test no longer reads ECCO_PYTHON", lambda s: s.replace("process.env.ECCO_PYTHON", "process.env.PYTHON_BIN"), "node"),
    ("N2 the Node test has a sixth skippable test", lambda s: s + "\ntest('x', { skip }, () => {});\n", "node"),
    ("N3 the Node test no longer says SKIPPED", lambda s: s.replace("SKIPPED", "not run"), "node"),
]


# ---------------------------------------------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    pins = parse_pins(read(PINS_REL))
    runbook = read(RUNBOOK_REL)
    node_src = read(NODE_TEST_REL)
    sources = {tool: read(rel) for tool, (_kind, rel) in TOOLS.items()}
    sources["deploy-ha.ps1"] += "\n" + "\n".join(read(rel) for rel in EXTRA_SOURCES)
    path = Path(argv[1]) if len(argv) > 1 else ROOT / CHECKLIST_REL
    print(f"checklist: {path}")
    if not path.is_file():
        check("the checklist exists", False, str(path))
        return finish()
    checklist = path.read_bytes().decode("utf-8", errors="replace")
    check("the pins could be read from the pin suite", all(pins[k] for k in ("card_size", "card_sha256", "config_size", "config_sha256", "sources", "attribute_rows")), str(pins))

    result = analyse(checklist, runbook, pins, sources, node_src)
    for rule in RULES:
        check(RULE_TITLES[rule], not result[rule], "; ".join(result[rule][:4]))

    # the facts behind the agreement rule, said once more as plain checks (so a pass names what it saw)
    csec = sections(checklist)
    check("the checklist cites the runbook at least ten times", len(re.findall(r"\brunbook \d", checklist, re.I)) >= 10)
    check("the checklist has the eight sections 1 to 8", sorted(csec, key=int) == [str(i) for i in range(1, 9)], str(sorted(csec)))
    check("the checklist's rollback list is the dashboard, the resource, the file (A3, A2, A1), then a re-check",
          re.findall(r"^\d\. \*\*(A[123]|Re-check)", csec.get("6", ""), re.M) == ROLLBACK_ORDER + ["Re-check"])
    check("the decisions D-U1-1 to D-U1-6 are each a row of the decisions table", all(re.search(r"^\| D-U1-" + str(i) + r" ", csec.get("7", ""), re.M) for i in range(1, 7)))
    exact = expected_names(pins, sources)
    check("the exact names are derived (sha8 from the card's pin; the URL prefix, the tag and the type from the generator's plan code; the folder from the deploy tool)",
          exact is not None and exact["url"].startswith("/local/ecco/") and exact["type"] == "module" and exact["dest"].startswith("/config/www/ecco/"))
    items9 = bullets(sections(runbook).get("9", ""))
    check(f"runbook section 9 has {len(COVERAGE)} bullets and each one has its keyword in checklist section 8 ({len(items9)} found)", len(items9) == len(COVERAGE) and not result["coverage"])
    own_bytes = Path(__file__).read_bytes()
    own = own_bytes.decode("utf-8", errors="replace")
    check("this suite's own source is ASCII and holds no address, token or entity id",
          own_bytes.isascii() and not IPV4.search(own) and not TOKEN.search(own) and not ENTITY_ID.search(own))

    if len(argv) > 1:
        return finish()   # another checklist was named: no mutants, only the verdict on that one

    real = result
    check("the unmutated checklist and runbook pass every rule (the baseline of the mutants)", not fired(real), str(fired(real)))
    mutants = make_mutants(pins, checklist, runbook)
    killed = 0
    for target, name, mutate, rule in mutants:
        base = checklist if target == "checklist" else runbook
        mutated = mutate(base)
        check(f"{name}: the mutation changes the text", mutated != base)
        if target == "checklist":
            got = fired(analyse(mutated, runbook, pins, sources, node_src))
        else:
            got = fired(analyse(checklist, mutated, pins, sources, node_src))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    for name, mutate, rule in NODE_MUTANTS:
        mutated = mutate(node_src)
        check(f"{name}: the mutation changes the text", mutated != node_src)
        got = fired(analyse(checklist, runbook, pins, sources, mutated))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    total = len(mutants) + len(NODE_MUTANTS)
    n_cl = sum(1 for m in mutants if m[0] == "checklist")
    check(f"at least six mutants are run, and every one is killed ({killed} of {total}: {n_cl} of the checklist, {len(mutants) - n_cl} of the runbook, {len(NODE_MUTANTS)} of the Node test)",
          total >= 6 and killed == total)
    return finish()


def finish() -> int:
    print("")
    print(f"{PASSED[0]} PASS, {len(FAILURES)} FAIL")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
