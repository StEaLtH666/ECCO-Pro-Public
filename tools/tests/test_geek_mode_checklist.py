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
  [9] mutants (all in memory): a wrong sha8, a wrong card or configuration hash, a missing check, a dropped `cls`, a cited section that does
      not exist, a forbidden word, a changed rollback order, a dropped statement, a flag that does not exist, a removed step, a quoted tool
      phrase that the tool never prints, an address, a token, an entity id, a runbook with its rollback order changed, a runbook heading that is
      gone: each is killed by the rule that exists for it

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


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


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


def powershell_blocks(text: str) -> list[str]:
    fence = "`" * 3
    return [b for _indent, b in re.findall(r"^( *)" + fence + r"powershell\n(.*?)^\1" + fence, text, re.S | re.M)]


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


# ---------------------------------------------------------------------------------------------------------------------------------
# the analysis: every rule gives the list of its problems; an empty list is a pass
# ---------------------------------------------------------------------------------------------------------------------------------
def analyse(checklist: str, runbook: str, pins: dict, sources: dict[str, str]) -> dict[str, list[str]]:
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
    return r


RULES = ("pins", "checks", "sections", "tools", "cls", "statements", "hygiene", "agreement")
RULE_TITLES = {
    "pins": "[1] the pins are in the checklist exactly as the pin suite holds them",
    "checks": "[2] the five checks of the owner's directive are present by name",
    "sections": "[3] every section the checklist cites exists",
    "tools": "[4] every flag, sub-command and quoted output phrase of the checklist exists in the tools",
    "cls": "[5] every PowerShell block starts with cls",
    "statements": "[6] the three plain statements are there",
    "hygiene": "[7] no forbidden word, address, token, entity id, hash blob or non-ASCII character; the checklist is short",
    "agreement": "[8] the step numbers, the live-step go and the rollback order agree with the runbook",
}


def fired(result: dict[str, list[str]]) -> set[str]:
    return {k for k, v in result.items() if v}


# ---------------------------------------------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    pins = parse_pins(read(PINS_REL))
    runbook = read(RUNBOOK_REL)
    sources = {tool: read(rel) for tool, (_kind, rel) in TOOLS.items()}
    sources["deploy-ha.ps1"] += "\n" + "\n".join(read(rel) for rel in EXTRA_SOURCES)
    path = Path(argv[1]) if len(argv) > 1 else ROOT / CHECKLIST_REL
    print(f"checklist: {path}")
    if not path.is_file():
        check("the checklist exists", False, str(path))
        return finish()
    checklist = path.read_bytes().decode("utf-8", errors="replace")
    check("the pins could be read from the pin suite", all(pins[k] for k in ("card_size", "card_sha256", "config_size", "config_sha256", "sources", "attribute_rows")), str(pins))

    result = analyse(checklist, runbook, pins, sources)
    for rule in RULES:
        check(RULE_TITLES[rule], not result[rule], "; ".join(result[rule][:4]))

    # the facts behind the agreement rule, said once more as plain checks (so a pass names what it saw)
    csec = sections(checklist)
    check("the checklist cites the runbook at least ten times", len(re.findall(r"\brunbook \d", checklist, re.I)) >= 10)
    check("the checklist has the eight sections 1 to 8", sorted(csec, key=int) == [str(i) for i in range(1, 9)], str(sorted(csec)))
    check("the checklist's rollback list is the dashboard, the resource, the file (A3, A2, A1), then a re-check",
          re.findall(r"^\d\. \*\*(A[123]|Re-check)", csec.get("6", ""), re.M) == ROLLBACK_ORDER + ["Re-check"])
    check("the decisions D-U1-1 to D-U1-6 are each a row of the decisions table", all(re.search(r"^\| D-U1-" + str(i) + r" ", csec.get("7", ""), re.M) for i in range(1, 7)))
    own_bytes = Path(__file__).read_bytes()
    own = own_bytes.decode("utf-8", errors="replace")
    check("this suite's own source is ASCII and holds no address, token or entity id",
          own_bytes.isascii() and not IPV4.search(own) and not TOKEN.search(own) and not ENTITY_ID.search(own))

    if len(argv) > 1:
        return finish()   # another checklist was named: no mutants, only the verdict on that one

    # the mutants: samples that would trip a scanner are assembled here, so this file holds none
    sample_addr = "192" + "." + "168" + "." + "1" + "." + "5"
    sample_token = "ghp" + "_" + "a" * 36
    sample_entity = "sen" + "sor" + "." + "some_value"
    real = result
    check("the unmutated checklist and runbook pass every rule (the baseline of the mutants)", not fired(real), str(fired(real)))
    sha8 = pins["card_sha256"][:8]
    wrong8 = ("0" if sha8[0] != "0" else "1") + sha8[1:]

    def flip(h: str) -> str:
        return h[:-1] + ("0" if h[-1] != "0" else "1")

    def drop_first_cls(text: str) -> str:
        return text.replace("```powershell\ncls\n", "```powershell\n", 1)

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

    CHECKLIST_MUTANTS = [
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
    ]
    RUNBOOK_MUTANTS = [
        ("R1 the runbook's rollback order changed", swap_rollback, "agreement"),
        ("R2 a runbook heading that the checklist cites is gone", lambda t: t.replace("### 5.3 Step 3", "### 5.3x Step 3", 1), "sections"),
        ("R3 a runbook PowerShell block without cls", drop_first_cls, "cls"),
        ("R4 a forbidden word in the runbook", lambda t: t + "\nThis is safe to install.\n", "hygiene"),
        ("R5 a runbook step row removed", lambda t: remove_row(t, 4), "agreement"),
    ]
    killed = 0
    for name, mutate, rule in CHECKLIST_MUTANTS:
        mutated = mutate(checklist)
        check(f"{name}: the mutation changes the text", mutated != checklist)
        got = fired(analyse(mutated, runbook, pins, sources))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    for name, mutate, rule in RUNBOOK_MUTANTS:
        mutated = mutate(runbook)
        check(f"{name}: the mutation changes the text", mutated != runbook)
        got = fired(analyse(checklist, mutated, pins, sources))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    check(f"at least six mutants are run, and every one is killed ({killed} of {len(CHECKLIST_MUTANTS) + len(RUNBOOK_MUTANTS)})",
          len(CHECKLIST_MUTANTS) + len(RUNBOOK_MUTANTS) >= 6 and killed == len(CHECKLIST_MUTANTS) + len(RUNBOOK_MUTANTS))
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
