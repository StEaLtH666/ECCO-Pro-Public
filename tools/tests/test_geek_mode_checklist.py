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
 [14] (round 5, the owner's decision of 21 Nov 2026) the decisions: D-U1-1, D-U1-2 and D-U1-4 are marked decided and D-U1-3, D-U1-5 and D-U1-6 keep their defaults,
      in both documents; "no automatic installation or live access is authorised" is said in both; RG-F3 is resolved for U1 only, in the owner's words
 [15] the exact targets: one table in the runbook (1.2) and the checklist (2) holds the file, the URL, the type, the dashboard path and title and the `.storage`
      names read, derived from the card's pin and the generator's plan code; the four target checks (a) to (d) are in both; block 1 of 5.1 makes checks (a) and (b)
 [16] the live shape check (step 1b): the step row in both step tables, the runbook section 5.1b and its command line, the extended block 3, the reference counts of
      the 14 Nov listing (derived from the committed ledger), and the stop text; the tool it names exists and has the flags and exit codes the documents say.
      Round 5 (the review of round 4): block 3's append of the undeclared ecco_intel states is pinned line by line and in its order (F2); NOT_CHECKED_LIVE fails
      closed unless --allow-not-checked, the self_test NOTE title and the tool's printed `proposed default` line are the tool's own words (F3, F4: each claim is checked against the tool's source;
      round 6: the documents call that wording superseded, the tool is preserved as reviewed)
 [17] the write-path statement: every Node test it names exists under that exact name; what it says of the card's mode switch, the `canOpenMoreInfo` domains and
      the actions of the example is true of their sources
 [18] the check of every existing dashboard after the global resource: the block that writes `dashboards-to-check.txt` from the baseline, and the three questions.
      Round 5 (F1): the catch-all row, the header of three answer columns and the three empty cells of every row are pinned line by line in that block, and the rule that the
      coordinator confirms every row yes, yes, yes before step 5 is pinned in 5.4, in both step 4 rows and in checklist 5 (F5: item 1 says it is done at step 4, before step 5)
 [19] the release gates (G1 to G7 of runbook 3, each marked) and what the rollback is measured against (the baseline, the protected backup)
 [20] (round 6, the owner's ruling of 21 Nov 2026 on the baseline and step 1b stops) the STOP, NOTE and values paragraphs are in the checklist (4.1), runbook 5.1b and runbook 6 word for
      word; each of the nine STOP items is in each place; the NOTE paragraph lists no unknown, unavailable or failed state before its closing sentence 'Unknown, unavailable or failed
      safety-relevant states are never notes.'; the values sentence (the shape tool never clears a value; the coordinator reads the values) is there; gate G4 says the baseline is saved AND no
      STOP condition of the list holds (both documents); the step 1 and step 1b rows of both step tables point to the rule; the sentence that supersedes the tool's printed `proposed default` line
      is in the checklist and runbook 5.1b; `proposed default` and the old confirm-at-the-final-GO wording appear only in a sentence that says superseded; the pins of the old wording are replaced by
      stricter ones of the new wording, and 'you have not ruled on it yet', 'or its state noted if not' and 'the owner has not ruled on it' are forbidden
 [21] mutants (all in memory): a wrong sha8, a wrong card or configuration hash, a missing check, a dropped `cls`, a cited section that does
      not exist, a forbidden word, a changed rollback order, a dropped statement, a flag that does not exist, a removed step, a quoted tool
      phrase that the tool never prints, an address, a token, an entity id, a runbook with its rollback order changed, a runbook heading that is
      gone, and (round 4) every mutant of the review of round 3 (a forbidden deploy flag, a mistyped sha8 in each place it is written, a wrong
      type, a dropped Require admin or --before or stop, a swapped order wording) and a removal of each pinned sentence and of each coverage
      keyword: each is killed by the rule that exists for it. Round 5 (review of round 4): the dashboards-to-check block without its catch-all row, its
      answer columns or its header; block 3 without `+ $more`, with another filter word, without the line, with the append after the write; the tool's source
      without the flag, with another NOTE title, without the fail-closed term, with another proposed-default sentence. Round 6 (the owner's ruling of 21 Nov 2026): each of the nine STOP items dropped in
      each of the three places, the NOTE paragraph, its closing sentence, the values sentence and the SHADOW-with-a-fresh-result words dropped, a safety-relevant state moved into the NOTE list, the
      old G4 wording and the old confirm-at-the-final-GO wording put back, the supersession sentence dropped, the step 1 and 1b rows pointing to the old shorter list

Usage: python tools/tests/test_geek_mode_checklist.py [CHECKLIST_FILE]
The optional argument names another checklist (this is how the suite is shown to fail on a checklist with a wrong hash).

Test-only, no network. Reads repository files; writes nothing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST_REL = "docs/product-ui/GEEK_MODE_U1_GO_CHECKLIST.md"
RUNBOOK_REL = "docs/product-ui/GEEK_MODE_FIRST_UPDATE_RUNBOOK.md"
PINS_REL = "tools/tests/test_ecco_mode_shell_card.py"
NODE_TEST_REL = "frontend/ecco-mode-shell/test/generated-config.test.mjs"
EXTRA_REL = {   # round 5: read-only sources the new rules check the documents against
    "element": "frontend/ecco-mode-shell/test/element.test.mjs", "core": "frontend/ecco-mode-shell/test/core.test.mjs", "generated-config": NODE_TEST_REL,
    "card": "frontend/ecco-mode-shell/ecco-mode-shell.js", "example": "frontend/ecco-mode-shell/examples/intelligence-modes.yaml",
    "ledger": "frontend/ecco-mode-shell/catalogue/intelligence.ledger.json",
}
DASH_URL = "ecco-modes-u1"                # D-U1-5, the default (runbook 5.5 suggests it)
DASH_TITLE = "ECCO Modes (first look)"    # D-U1-5, the default
SHAPE_LINE = r'& $PY -I -B -X utf8 tools\geek_mode_live_shape_check.py "$E\states-before.json"'
WRITE_TESTS = [   # (the Node file, the exact test name, named by the checklist too): what the write-path statement points at
    ("generated-config", "generated config: both modes and a state change touch nothing but hass.states, locale and themes (no service, no websocket, no storage, no network)", True),
    ("element", "AC5 the switch never changes helper or service state: Production-only and always cards see no extra hass call from a mode change", True),
    ("generated-config", "generated config: Geek Mode shows the 17 sources and the 344 declared attribute rows, and the Production-only tile is hidden", True),
    ("element", "AC16 [r1] Geek Mode opens a dialog only for read-only domains: over every domain the real catalogue discovers no writable one offers it, and none dispatches hass-more-info", True),
    ("element", "AC16 [r1] the guard is also in the dispatch itself: _openEntity sends hass-more-info for a read-only domain and never for a writable, malformed or non-text id", False),
    ("core", "AC16 validateChildCards: the read-only Intelligence card passes; the pause tile (a toggle) is refused in a Geek-visible region", False),
]
TOOLS = {   # the name as it is written in a command, its kind, its source
    "geek_mode_dashboard_config.py": ("py", "tools/geek_mode_dashboard_config.py"),
    "ecco_deploy_preflight.py": ("py", "tools/ecco_deploy_preflight.py"),
    "deploy-ha.ps1": ("ps", "tools/deploy-ha.ps1"),
    "ha-logs.ps1": ("ps", "tools/ha-logs.ps1"),
    "geek_mode_live_shape_check.py": ("py", "tools/geek_mode_live_shape_check.py"),
}
EXTRA_SOURCES = ("tools/EccoDeploy.psm1",)   # printed by deploy-ha.ps1 through its module

FAILURES: list[str] = []
PASSED = [0]
MAX_CHECKLIST_LINES = 200   # round 5: it was 136 lines and may grow to about 200 with the exact targets, the release gates and the per-dashboard check; no more
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
NOTE_TITLE = "NOTE (free-form self-test check codes under the declared self_test attribute; recorded, not a failure)"   # round 5 (F4): the tool prints it, the runbook quotes it
# the live shape check tool's own printed line, preserved as reviewed: the documents call that wording superseded by the owner's ruling of 21 Nov 2026 (round 6)
PROPOSED_DEFAULT = ("proposed default (the owner confirms or changes it at the final GO): a self_test note is recorded, not a stop; "
                    "anything else UNDECLARED or any unexplained absence is a STOP")
# ---- round 6 (the owner's ruling of 21 Nov 2026 on the baseline and step 1b stops): the canonical text, word for word as the coordinator wrote it; the documents carry it verbatim
STOP_LEAD = "STOP (change nothing, ask the owner):"
STOP_P = ("STOP (change nothing, ask the owner): Core not running; the Intelligence status not SHADOW with a fresh result; the status, freshness or watchdog enti"
           "ty unknown or unavailable; any self-test check that reads a failure, unknown or unavailable; any control entity of the earlier supervised installs (th"
           "e write enables, the arm and schedule switches, the manual write counter, the TOU edit helper) or the pause helper absent, unknown or unavailable; the"
           " shape tool exiting 1 (anything undeclared, a declared entity missing or not checked, an unexplained absence); a baseline copy that is not byte-exact;"
           " anything that cannot be read.")
STOP_ITEMS = (   # the nine STOP conditions of the ruling (a control entity of the earlier installs and the pause helper are two), in order
    "Core not running",
    "the Intelligence status not SHADOW with a fresh result",
    "the status, freshness or watchdog entity unknown or unavailable",
    "any self-test check that reads a failure, unknown or unavailable",
    "any control entity of the earlier supervised installs (the write enables, the arm and schedule switches, the manual write counter, the TOU edit helper)",
    "or the pause helper absent, unknown or unavailable",
    "the shape tool exiting 1 (anything undeclared, a declared entity missing or not checked, an unexplained absence)",
    "a baseline copy that is not byte-exact",
    "anything that cannot be read",
)
NOTE_LEAD = "NOTE (recorded, shown to the owner, never hidden):"
NOTE_P = ("NOTE (recorded, shown to the owner, never hidden): informational findings only: the names of the check codes under a recorded self_test (shape only, a"
          " note only while every check value reads as passing), the declared conditional attribute rows that are legitimately empty, informational log lines; ea"
          "ch note is written in the evidence with why it is informational. Unknown, unavailable or failed safety-relevant states are never notes.")
NEVER_NOTES = "Unknown, unavailable or failed safety-relevant states are never notes."
NOTE_BAD_WORDS = ("unknown", "unavailable", "failed", "failure", "absent", "missing", "not running", "not shadow")   # none may be a note: the NOTE paragraph holds none before its closing sentence
VALUES_P = "The shape tool sees only names and types, so it can never clear a value: the coordinator reads the values in the captured states and applies this list."
SUPERSEDED_S = ("The live shape tool still prints a line beginning `proposed default` and calls a self_test note `not a failure`: that wording is shape-only (names and"
                " types, never a value), its code is preserved as reviewed, and it is SUPERSEDED by the owner's ruling of 21 Nov 2026: the tool's note never clears a v"
                "alue, the coordinator reads the values in `states-before.json` and applies the list, and where the list says STOP nothing proceeds.")
G4_TEXT = "the live baseline (steps 1 and 1b) is saved AND no STOP condition of the list holds"   # gate G4, in both documents (it no longer says "or its state noted if not")
CL_POINTER = "any STOP condition of the list in 4.1 (the owner's ruling of 21 Nov 2026)"   # the checklist's step 1 and 1b rows point to the rule
RB_POINTER = "any STOP condition of the list in 5.1b and section 6 (the owner's ruling of 21 Nov 2026)"   # the runbook's step 1 and 1b rows point to the rule
OLD_RULE_PHRASES = ("proposed default", "confirms or changes it at the final go", "confirms or changes at the final go", "confirm or change the proposed default")   # lower case: only in a sentence that says superseded
BLOCK3_MORE = "$more = @($index.Keys | Where-Object { $_ -like '*ecco_intel*' -and $ids -notcontains $_ } | Sort-Object | ForEach-Object { $index[$_] })"   # round 5 (F2)
BLOCK3_APPEND = "$out = @($out) + $more"
BLOCK3_WRITE = "ConvertTo-Json -InputObject $out -Depth 20 | Out-File -Encoding utf8 \"$E\\states-$Tag.json\""
DASH_LINES = (   # round 5 (F1): the lines of the dashboards-to-check block that make the catch-all row and the three empty answer columns, in this order
    "$what = @('the default dashboard (the production Overview)')",
    "$what += 'every other sidebar entry (Energy, Map, any YAML dashboard registered elsewhere)'",
    "$what += 'any wall or phone client the owner uses'",
    "$lines = @('| open this | renders as before | no console error naming the shell | responds |')",
    "$lines += @($what | ForEach-Object { '| {0} |  |  |  |' -f $_ })",
    "$lines | Out-File -Encoding utf8 \"$E\\dashboards-to-check.txt\"",
)
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
    # ---- round 5 (the owner's decision of 21 Nov 2026): T1 the decisions, nothing authorised by the approval
    ("runbook", None, "No automatic installation or live access is authorised by that approval."),
    ("checklist", None, "No automatic installation or live access is authorised by that approval:"),
    ("runbook", None, "each live step below still needs its own go"),
    ("checklist", "1", "each live step needs its own go"),
    ("checklist", "1", "nothing is installed and nothing live is touched until your final installation GO"),
    ("runbook", None, "Nothing is installed and no live system is touched until the owner gives the final installation GO"),
    ("runbook", None, "Ghost diagnostics stays the second update, with its own restart and rollback requirements"),
    ("checklist", "1", "Ghost stays the second update, with its own restart and rollback requirements"),
    ("runbook", "3", "resolved for U1 only, by the owner on 21 Nov 2026 (D-U1-2): the existing voice-assistant exposure settings remain a separately tracked F3 issue because this installation creates no new entity"),
    ("runbook", "3", "This is not acceptance of F3 and not permission to introduce new exposed controls: any later install that creates an entity still needs both settings off"),
    ("runbook", "5.1", "RG-F3 (G5) is resolved for U1 only, by the owner on 21 Nov 2026"),
    ("runbook", "12", "DECIDED by the owner on 21 Nov 2026, for U1 only: the existing voice-assistant exposure settings remain a separately tracked F3 issue because this installation creates no new entity"),
    ("runbook", "12", "This is not acceptance of F3 and not permission to introduce new exposed controls: any later install that creates an entity still needs both settings off"),
    ("runbook", "12", "DECIDED by the owner on 21 Nov 2026: option (a), install from the branch commit after the draft pull request's CI is green"),
    ("runbook", "12", "Merge is a separate later decision, and the card's sha256 must be unchanged at the merge"),
    ("runbook", "12", "so the installed bytes equal the reviewed card whatever later commits do"),
    ("runbook", "12", "DECIDED by the owner on 21 Nov 2026: push dev/geek-mode-u1, open a DRAFT pull request, run the complete M2 scan on the exact commit first (generated assets, commit metadata and pull request text included) and run CI"),
    ("runbook", "12", "keeps its default: deferred until after the first look (section 11)"),
    ("runbook", "12", "keeps its default (5.5): ECCO Modes (first look), ecco-modes-u1, shown in the sidebar (admin-only)"),
    ("runbook", "12", "keeps its default (H5): only after the Production look passes and the owner says go"),
    ("runbook", "5.0", "D-U1-1, the commit to install from: decided by the owner on 21 Nov 2026, option (a)"),
    ("runbook", "5.0", "Install from the branch commit after the draft pull request's CI is green"),
    ("runbook", "5.0", "Merge is a separate later decision, and the card's sha256 must be unchanged at the merge"),
    ("runbook", "5.0", "the card file is content-addressed, so the installed bytes equal the reviewed card whatever later commits do"),
    ("runbook", "5.0", "it runs on the exact commit before the push, including the generated assets, the commit metadata and the pull request text"),
    ("runbook", "5.0", "If anything changes after a scan, the applicable verification and the privacy scans are repeated"),
    ("checklist", "1", "Push dev/geek-mode-u1, open a DRAFT pull request, run the complete M2 private-pattern scan on the exact commit first (generated assets, commit metadata and pull request text included), run CI (D-U1-4)"),
    ("checklist", "1", "Install from the branch commit after green CI; merge is a separate later decision and the card's sha256 must be unchanged at the merge (D-U1-1, option a)"),
    ("checklist", "1", "RG-F3 (D-U1-2) is resolved for U1 only: the existing voice-assistant exposure settings remain a separately tracked F3 issue because this installation creates no new entity"),
    ("checklist", "1", "That is not acceptance of F3 and not permission to introduce new exposed controls; any later install that creates an entity still needs both settings off"),
    ("checklist", "7", "decided, option (a): the branch commit after green CI on the draft pull request"),
    ("checklist", "7", "decided, for U1 only: the existing voice-assistant exposure settings remain a separately tracked F3 issue because this installation creates no new entity; not acceptance of F3 and not permission to introduce new exposed controls"),
    ("checklist", "7", "decided: push, a DRAFT pull request, the complete M2 scan on the exact commit first (generated assets, commit metadata, pull request text), CI"),
    ("checklist", "7", "default: defer it all until after the first look"),
    ("checklist", "7", "default: ECCO Modes (first look), ecco-modes-u1, shown in the sidebar (admin-only)"),
    ("checklist", "7", "default: yes, only after the Production look passes and you say go"),
    # ---- T2 the exact targets and the four target checks
    ("runbook", "1.2", "(a) step 1. The baseline shows that the existing Intelligence card's resource URL uses the same /local/ecco/ form, so /config/www/ecco/ is the right folder"),
    ("runbook", "1.2", "(b) step 1. The dashboard URL path ecco-modes-u1 is not already in the dashboard list, and the resource URL is not already in the resource list"),
    ("runbook", "1.2", "(c) step 3. verify-served proves the mapping from /config/www/ecco/ to /local/ecco/ and the bytes before any resource exists (5.3)"),
    ("runbook", "1.2", "(d) step 4. verify-resource proves that the registered resource URL and type equal the plan's (5.4)"),
    ("runbook", "1.2", "an unmet check stops the update at that step"),
    ("runbook", "5.1", "the number of the baseline's resources that are under /local/ecco/ and name the Intelligence card (at least 1: a 0 means that card is not served from the folder this runbook uses, so stop)"),
    ("runbook", "5.1", "then 0 for the new resource URL already being in the resource list and 0 for the dashboard URL path ecco-modes-u1 already being in the dashboard list"),
    ("runbook", "5.3", "This is target check (c) of 1.2: verify-served proves the mapping from /config/www/ecco/ to /local/ecco/ and the bytes before any resource exists"),
    ("runbook", "5.3", "so a 404 or a mismatch here is the wrong folder, name or file, never a resource problem"),
    ("runbook", "5.4", "This is target check (d) of 1.2: it proves that the registered resource URL and type equal the plan's"),
    ("checklist", "2", "(a) step 1: the baseline shows the existing Intelligence card's resource URL under /local/ecco/ too, so /config/www/ecco/ is the right folder"),
    ("checklist", "2", "(b) step 1: the dashboard path ecco-modes-u1 and the resource URL are not already in the baseline lists"),
    ("checklist", "2", "(c) step 3: verify-served proves the /config/www/ecco/ to /local/ecco/ mapping and the bytes before any resource exists"),
    ("checklist", "2", "(d) step 4: verify-resource proves the registered URL and type equal the plan"),
    ("checklist", "2", "an unmet check is a stop at that step"),
    # ---- T3 the live shape check (step 1b)
    ("runbook", "5.1b", "A live read, and it needs the owner's own go, separate from the go for step 1: block 3 of 5.1 is its live read"),
    ("runbook", "5.1b", "converts the states in memory to the value-free listing format (attribute names, types, encoded sizes and the first-level keys of dict attributes: no value is kept)"),
    ("runbook", "5.1b", "calling compare_live of tools/geek_mode_coverage.py (imported, not copied), prints counts and names and never a value, and writes nothing"),
    ("runbook", "5.1b", "Exit 0: the shape matches (nothing UNDECLARED, no declared entity missing, no unexplained absence); exit 1: it does not, and the lines say which; exit 2: bad input"),
    ("runbook", "5.1b", "Expected: exit 0, the line RESULT: MATCH (exit 0) and the counts: PRESENT_LIVE 17 of 17 declared entities"),
    ("runbook", "5.1b", "NOT_PRESENT_LIVE 0 declared entities missing and 0 unexplained attribute rows, UNDECLARED 0 entities and 0 attributes, NOT_CHECKED_LIVE 0"),
    ("runbook", "5.1b", "The number of conditional attribute rows depends on the day (42 on 14 Nov: the live item is not OK, or a parent attribute is empty); it is information, never a stop"),
    ("runbook", "5.1b", "Anything UNDECLARED, any declared entity missing and any unexplained absence (exit 1) is a stop: it means the catalogue is out of date for this host, so the Geek inspector would be wrong. Production is unaffected. Ask the owner"),
    ("runbook", "5.1b", "The reserve helper's attributes were never confirmed live, because the 14 Nov listing did not include it"),
    ("runbook", "5.1b", "its check codes appear as UNDECLARED dotted attributes (self_test.<check code>)"),
    ("runbook", "5.1b", "--write-shape <path> also writes the value-free listing, only outside the repository's checkout, never over an existing file unless --overwrite is given"),
    ("runbook", "5.1", "The listed entities are kept, and so is every entity whose id contains ecco_intel (so that step 1b can find what the catalogue does not declare)"),
    ("runbook", "5.1", "The file holds values: it stays in <OFFLINE_EVIDENCE_DIR> and never enters a repository"),
    ("checklist", "4", "live shape check: block 3 (the state read), then the offline tool geek_mode_live_shape_check.py on states-before.json (runbook 5.1b)"),
    ("checklist", "4", "exit 0; 17 of 17 declared entities present, 0 undeclared, 0 unexplained"),
    ("checklist", "4", "The second holds the commands of steps 1b, 3, 4 and 6"),
    # ---- T4 the write-path statement
    ("runbook", "1.1", "Write-path statement (checked again in round 4; no change to the card)"),
    ("runbook", "1.1", "(a) Switching Production and Geek invokes no service"),
    ("runbook", "1.1", "each of the two mode buttons has one click handler, this._ctl.set(mode)"),
    ("runbook", "1.1", "has no reference to hass and can only remember a presentation choice"),
    ("runbook", "1.1", "traps every hass function and every network, storage and window API, switches Production to Geek and back, and finds no call and no hit (that file: 5 of 5 pass, 0 skipped)"),
    ("runbook", "1.1", "(b) The pause tile is the only write-capable control the page places"),
    ("runbook", "1.1", "The one write-capable control the page places is the existing pause tile (an input boolean toggle: the same tile and the same write as on the existing Intelligence dashboard)"),
    ("runbook", "1.1", "its only actions are toggle (the tile's tap and icon tap) and more-info (the tile's hold action), and it has no service-call shaped key"),
    ("runbook", "1.1", "dispatches Home Assistant's own more-info event only for sensor, binary sensor and event entities"),
    ("runbook", "1.1", "every other domain gets \"Copy entity id\" instead"),
    ("runbook", "1.1", "this is not an ECCO write path and not part of the first look, which presses none of Open in Home Assistant, Copy, JSON or CSV"),
    ("runbook", "1.1", "Geek Mode hides the pause tile (the tests"),
    ("checklist", "2", "Write-path statement (runbook 1.1; no card change)"),
    ("checklist", "2", "(a) Switching Production and Geek invokes no service: the switch handler only sets a presentation choice"),
    ("checklist", "2", "that file ran 5 of 5, 0 skipped"),
    ("checklist", "2", "element suite 150 of 150, core suite 157 of 157"),
    ("checklist", "2", "(b) The pause tile is the only write-capable control the page places"),
    ("checklist", "2", "the one write-capable control is the existing pause tile (an input boolean toggle: the same tile and write as on the existing Intelligence dashboard)"),
    ("checklist", "2", "Geek Mode hides it"),
    ("checklist", "2", "opens Home Assistant's own more-info dialog only for sensor, binary sensor and event entities (every other domain gets \"Copy entity id\""),
    ("checklist", "2", "not an ECCO write path and not part of the first look, which presses none of Open in Home Assistant, Copy, JSON or CSV"),
    # ---- T5 the check of every existing dashboard
    ("runbook", "5.4", "The check of every existing dashboard (owner, desktop browser, hard refresh with Ctrl+F5, console open)"),
    ("runbook", "5.4", "the coordinator writes the list of what to look at from the baseline into the evidence folder, so that no dashboard is forgotten"),
    ("runbook", "5.4", "every other dashboard of dashboards-before.json and every YAML dashboard file listed in sha-before.txt"),
    ("runbook", "5.4", "the owner opens EACH of them and records yes or no for each of three questions"),
    ("runbook", "5.4", "it renders as before (the same cards, nothing red, no new error card)"),
    ("runbook", "5.4", "the console shows no new error that names the shell or its resource"),
    ("runbook", "5.4", "the page responds (no freeze, no blank page)"),
    ("runbook", "5.4", "For any wall or phone client the owner uses, the result is a note, not a stop, when it is only the known old-web-view module error below"),
    ("runbook", "5.4", "Any no is a stop: record the text and the page, the owner deletes the one resource (rollback A2, section 7, item 2), and then the same list is looked at again"),
    ("runbook", "5.4", "The production Overview's file hash stays at its baseline, and step 6 proves it"),
    ("runbook", "4", "then the owner checks EACH existing dashboard, because the resource is global (5.4)"),
    ("runbook", "4", "every existing dashboard: yes to all three questions of 5.4"),
    ("runbook", "6", "existing dashboard (the production Overview included) shows an error naming the shell or no longer renders as before"),
    ("checklist", "5", "Every existing dashboard answers yes to three questions: it renders as before (same cards, nothing red, no new error card), the console shows no new error that names the shell or its resource, and the page responds"),
    ("checklist", "5", "The list is dashboards-to-check.txt, written by the coordinator from the baseline before step 4"),
    ("checklist", "5", "and any wall or phone client (a note for the known old-web-view error)"),
    ("checklist", "5", "Any no is a stop: you delete the one resource (rollback A2) and the same list is looked at again"),
    ("checklist", "5", "The Overview's file hash stays at its baseline"),
    ("checklist", "4", "then your check of EACH existing dashboard (runbook 5.4)"),
    # ---- T6 the baseline, the backup, the rollback proofs, the release gates
    ("checklist", "6", "Measured against two things made before any live write: (i) the baseline, the read-only reads of runbook 5.1"),
    ("checklist", "6", "with a byte-exact copy of each .storage/lovelace* file, each hash-checked EXACT"),
    ("checklist", "6", "and (ii) your protected full backup, made in the Home Assistant UI (runbook 5.2), the last resort"),
    ("checklist", "6", "Proven: /config/www/ecco/ equals the baseline, or differs by only that file when it is left in place"),
    ("checklist", "6", "the production Overview and the existing Intelligence dashboard among them (the -rollback reads of runbook 7)"),
    ("checklist", "7", "Release gates (runbook 3). Only G1 is met by the offline work, and only in part"),
    # ---- round 5 (the review of round 4: F1 to F6)
    ("runbook", "5.4", "dashboards-to-check.txt is a table of rows with three empty answer columns (renders as before, no console error naming the shell, responds)"),
    ("runbook", "5.4", "then one catch-all row, every other sidebar entry (Energy, Map, any YAML dashboard registered elsewhere)"),
    ("runbook", "5.4", "the list is built from two sources only, the stored dashboard list and the YAML dashboard files under ecco/dashboards"),
    ("runbook", "5.4", "a YAML dashboard registered from another path, and Home Assistant's own panels that can also load global resources (Energy, Map and similar sidebar entries; recalled, not verified), would not be in it"),
    ("runbook", "5.4", "for that row the owner goes through the whole sidebar and answers for every entry that is not already a row"),
    ("runbook", "5.4", "records yes or no for each of three questions in the three empty columns of its row"),
    ("runbook", "5.4", "The coordinator confirms every row is filled yes, yes, yes before step 5 goes ahead; a single no or an empty cell is the STOP of 5.4"),
    ("runbook", "5.4", "the owner writes note in that row's console cell instead of no, the one cell that may hold anything but yes"),
    ("runbook", "4", "every row of dashboards-to-check.txt filled yes, yes, yes, which the coordinator confirms before step 5"),
    ("runbook", "4", "a no or an empty cell for any row of the list (the owner deletes the one resource)"),
    ("checklist", "4", "every row of dashboards-to-check.txt filled yes, yes, yes (every existing dashboard and the catch-all row), confirmed by the coordinator"),
    ("checklist", "4", "a no or an empty cell on any row (you delete the one resource)"),
    ("checklist", "5", "The read-only checks (item 1 at step 4, before step 5; items 2 to 6 after the install)"),
    ("checklist", "5", "At step 4, before step 5 (the dashboard does not exist yet), every existing dashboard answers yes to three questions"),
    ("checklist", "5", "one catch-all row for every other sidebar entry (Energy, Map, any YAML dashboard registered elsewhere)"),
    ("checklist", "5", "Each row has three empty answer columns that you fill yes or no"),
    ("checklist", "5", "the coordinator confirms every row is filled yes, yes, yes before step 5 goes ahead, and a single no or an empty cell is the stop"),
    ("runbook", "5.1b", "In short: expected exit 0, 17 of 17 present, NOT_CHECKED 0"),
    ("runbook", "5.1b", "NOT_CHECKED_LIVE fails closed: a declared entity that is neither in the states file nor marked absent (a hand-made capture, an edited entity list) is a failure, exit 1, unless the caller passes the explicit flag --allow-not-checked"),
    ("runbook", "5.1b", "which exists for one deliberate case only, the 14 Nov listing converted back (its capture filter did not cover the reserve helper)"),
    ("runbook", "5.1b", "the read of the install day never uses it, and block 3 lists every catalogued entity or marks it absent"),
    ("runbook", "5.1b", "and 1 not checked (the reserve helper), when --allow-not-checked is given, and exit 1 without it"),
    ("runbook", "5.1b", "A declared entity that is NOT_CHECKED_LIVE is a stop too (exit 1 without --allow-not-checked)"),
    ("runbook", "4", "any declared entity missing or not checked"),
    ("runbook", "4", "exit 0 and the counts of 5.1b (17 of 17 present, NOT_CHECKED 0)"),
    ("checklist", "4", "exit 0; 17 of 17 declared entities present, 0 undeclared, 0 unexplained, 0 not checked"),
    ("runbook", "5.1b", "The tool sets such a path apart from the failures, in a separate section titled NOTE (free-form self-test check codes under the declared self_test attribute; recorded, not a failure), with names only, and it does not change the exit code"),
    ("runbook", "5.1b", "a dotted path under any other declared attribute (for example advice.<x>), a self_test attribute on an entity that does not declare it, any other undeclared entity or attribute, a missing source entity, an unexplained absence and a NOT_CHECKED_LIVE entity all stay failures"),
    ("runbook", "13", "the fixture-built states exit 0 including the self_test note"),
    ("runbook", "13", "the 14 Nov listing converted back exits 0 only with --allow-not-checked"),
    ("runbook", "13", "that exit is 0 only with --allow-not-checked; without it the tool now exits 1 on that one not checked entity"),
    ("runbook", "5.1b", "The names of the ecco_intel entities and of the one catalogued helper outside that name filter appear in the tool's output and in a --write-shape listing (by design: entity ids, attribute names, check codes)"),
    ("runbook", "5.1b", "so the output stays in the evidence folder (<OFFLINE_EVIDENCE_DIR>) and is never pasted into a repository or a chat"),
    ("runbook", "5.1b", "Values never appear, and neither does any entity id that the catalogue does not declare and that is not named ecco_intel (those states are only counted)"),
    ("runbook", "13", "Round 5 (21 Nov 2026: the fixes of the independent review of round 4"),
    # ---- round 6 (the owner's ruling of 21 Nov 2026): these REPLACE the ten pins of the old wording (a self_test note as a proposed default that the owner confirms at the final GO, and its
    # step 1b stop list) with stricter pins of the new wording; the STOP, NOTE and values paragraphs themselves are checked word for word by rule [20], in three places
    ("checklist", "4", "any STOP condition of the list in 4.1 (the owner's ruling of 21 Nov 2026), not only the tool's exit 1 (anything UNDECLARED, a declared entity missing or not checked, an unexplained absence: stop and ask you; the catalogue is out of date for this host, so the Geek inspector would be wrong; Production is unaffected)"),
    ("checklist", "4", "the tool's note never clears a value"),
    ("checklist", "4", "and the coordinator reads the values in states-before.json (the status entity's state, mode, applies_nothing and last update; every self_test check value; the freshness and watchdog entities; each control entity and the pause helper: state and last_changed) and finds no STOP condition of the list in 4.1"),
    ("checklist", "4.1", "the shape tool exiting 1 (anything undeclared, a declared entity missing or not checked, an unexplained absence)"),
    ("checklist", "4.1", "a note only while every check value reads as passing"),
    ("checklist", "4.1", "Unknown, unavailable or failed safety-relevant states are never notes."),
    ("checklist", "4.1", "the coordinator reads the values in the captured states and applies this list"),
    ("checklist", "4.1", "still prints a line beginning proposed default and calls a self_test note not a failure: that wording is shape-only (names and types, never a value), its code is preserved as reviewed, and it is SUPERSEDED by the owner's ruling of 21 Nov 2026"),
    ("checklist", "4.1", "the tool's note never clears a value, the coordinator reads the values in states-before.json and applies the list, and where the list says STOP nothing proceeds"),
    ("checklist", "7", "the live baseline (steps 1 and 1b) is saved AND no STOP condition of the list holds"),
    ("checklist", "7", "the stop and note rules of 4.1 are your ruling of 21 Nov 2026, not an open default"),
    ("runbook", "3", "the live baseline (steps 1 and 1b) is saved AND no STOP condition of the list holds"),
    ("runbook", "3", "the status, freshness and watchdog entities, every control entity of the earlier supervised installs and the pause helper are present and readable (none absent, unknown or unavailable), each with its state and last_changed recorded"),
    ("runbook", "4", "and the coordinator has read the values in states-before.json and finds no STOP condition of the list"),
    ("runbook", "4", "the tool's note, being shape-only, never clears a value"),
    ("runbook", "5.1", "Record from it, offline, the values that the coordinator reads for the STOP and NOTE list of 5.1b: the Intelligence status entity (its state, its mode and applies_nothing attributes, when it was last updated, and every check value under its self_test attribute)"),
    ("runbook", "5.1", "the freshness and watchdog entities (state and last_changed), the pause helper (state and last_changed) and each control entity of the earlier installs (state and last_changed)"),
    ("runbook", "5.1", "An id shown as absent is recorded, not guessed; for the pause helper or a control entity it is a STOP (5.1b)"),
    ("runbook", "5.1b", "The tool decides only the shape of the data; these rules decide whether the installation goes on"),
    ("runbook", "5.1b", "Unknown, unavailable or failed safety-relevant states are never notes."),
    ("runbook", "5.1b", "the coordinator reads the values in the captured states and applies this list"),
    ("runbook", "5.1b", "the coordinator reads and records the status entity's state, mode, applies_nothing, its last update and every self_test check value; the freshness and watchdog entities; each control entity of the earlier installs and the pause helper: state and last_changed"),
    ("runbook", "5.1b", "still prints a line beginning proposed default and calls a self_test note not a failure: that wording is shape-only (names and types, never a value), its code is preserved as reviewed, and it is SUPERSEDED by the owner's ruling of 21 Nov 2026"),
    ("runbook", "5.1b", "the tool's note never clears a value, the coordinator reads the values in states-before.json and applies the list, and where the list says STOP nothing proceeds"),
    ("runbook", "5.1b", "That is the tool's shape-only wording, superseded as stated above: the names are a note only while every check value in states-before.json reads as passing, and a check that reads a failure, unknown or unavailable is a STOP"),
    ("runbook", "5.1b", "the tool counts such entities in a NOTE, which is shape-only and clears nothing"),
    ("runbook", "5.1b", "a note of the list below only while the rows are legitimately empty: an entity that reads unknown or unavailable is judged by the STOP list, never by this count"),
    ("runbook", "5.1b", "for any other entity the coordinator reads an absence on it with care, repeats the read while Intelligence is publishing, and stops and asks the owner when it cannot tell"),
    ("runbook", "5.1b", "If the entity is one that the STOP list names (the status, freshness or watchdog entity, a control entity of the earlier installs, the pause helper), unknown or unavailable is a STOP"),
    ("runbook", "5.1b", "Stop and note rules, the owner's ruling of 21 Nov 2026 (the same text is in section 6 and in checklist 4.1)"),
    ("runbook", "6", "The baseline STOP and NOTE rules, the owner's ruling of 21 Nov 2026 (the same text is in 5.1b and in checklist 4.1)"),
    ("checklist", "4.1", "Stop and note rules, the owner's ruling of 21 Nov 2026"),
    ("runbook", "6", "a STOP condition of the baseline list below holds (and, at any later step, the Intelligence status is no longer what the baseline recorded)"),
    ("runbook", "6", "Unknown, unavailable or failed safety-relevant states are never notes."),
    ("runbook", "6", "the coordinator reads the values in the captured states and applies this list"),
    ("runbook", "12", "The owner also ruled on 21 Nov 2026 on the stop and note rules of the baseline and step 1b (5.1b, section 6, checklist 4.1): decided, not an open default"),
    ("runbook", "13", "Round 6 (21 Nov 2026: the owner's ruling on the baseline and step 1b stops, put into the documents before the installation)"),
    ("runbook", "13", "where an unknown, unavailable or failed safety-relevant state is never a note"),
    ("runbook", "13", "under a proposed default that the owner confirms or changes at the final GO (F4; superseded by the owner's ruling of 21 Nov 2026 (5.1b))"),
    ("runbook", "13", "a proposed default that the owner confirms or changes at the final GO, superseded by the owner's ruling of 21 Nov 2026 (5.1b))"),
    ("runbook", "13", "Proposed default (the owner confirms or changes it at the final GO): a self_test note is recorded, not a stop; anything else UNDECLARED or any unexplained absence is a STOP, superseded by the owner's ruling of 21 Nov 2026 (5.1b)"),
]
FORBIDDEN_PHRASES = [   # (document, section or None for the whole text, a phrase that must be gone)
    ("runbook", None, "step 8 proves it"),
    ("checklist", None, "step 8 proves it"),
    ("runbook", "5.5", "with no ecco card in it"),
    # round 5: what the owner's decision of 21 Nov replaced
    ("runbook", None, "one look at the production Overview"),
    ("checklist", None, "one look at the production Overview"),
    ("checklist", None, "D-U1-1 and D-U1-2 are not decided"),
    ("checklist", None, "you record the voice-assistant setting"),
    ("runbook", "3", "consciously waived"),
    # round 6: the wording the owner's ruling of 21 Nov 2026 replaced ('proposed default' and the confirm-at-the-final-GO wording only inside a sentence that says superseded: rule [20])
    ("runbook", None, "you have not ruled on it yet"),
    ("checklist", None, "you have not ruled on it yet"),
    ("runbook", None, "or its state noted if not"),
    ("checklist", None, "or its state noted if not"),
    ("runbook", None, "the owner has not ruled on it"),
    ("checklist", None, "the owner has not ruled on it"),
    ("runbook", None, "the states noted"),
    ("checklist", None, "the states noted"),
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
# round 5 rules: the owner's decision of 21 Nov 2026 (T1 to T6)
# ---------------------------------------------------------------------------------------------------------------------------------
def decisions_problems(checklist: str, runbook: str) -> list[str]:
    """[14] D-U1-1, D-U1-2 and D-U1-4 are decided and D-U1-3, D-U1-5 and D-U1-6 keep their defaults (both documents); nothing is authorised by the approval."""
    p = []
    top = {"runbook": re.split(r"^## 1\. ", runbook, maxsplit=1, flags=re.M)[0], "checklist": sections(checklist).get("1", "")}   # where the sentence belongs: the top of the runbook, checklist section 1
    for label, text in (("checklist", top["checklist"]), ("runbook", top["runbook"]), ("runbook section 12", subsection(runbook, "12"))):
        if "no automatic installation or live access is authorised" not in plain(text):
            p.append(f"the {label} does not say, where it belongs, that no automatic installation or live access is authorised")
    for label, body, status_col in (("runbook", subsection(runbook, "12"), 2), ("checklist", sections(checklist).get("7", ""), 1)):
        for n in range(1, 7):
            m = re.search(r"^\| D-U1-" + str(n) + r"[ |].*$", body, re.M)
            if not m:
                p.append(f"the {label} has no row for D-U1-{n}")
                continue
            cells = [c.strip() for c in m.group(0).strip().strip("|").split("|")]
            row = plain(cells[status_col]) if len(cells) > status_col else ""   # the status cell: the decision's second column (checklist) or third (runbook)
            if n in (1, 2, 4) and "decided" not in row:
                p.append(f"the {label} D-U1-{n} status is not marked decided")
            if n in (3, 5, 6) and ("default" not in row or "decided" in row):
                p.append(f"the {label} D-U1-{n} status does not keep its default (or is marked decided)")
    if "resolved for u1 only" not in plain(subsection(runbook, "3")):
        p.append("runbook section 3: G5 does not say that RG-F3 is resolved for U1 only")
    return p


def targets_problems(checklist: str, runbook: str, names: dict | None) -> list[str]:
    """[15] the exact targets (runbook 1.2, checklist 2) and the four target checks."""
    if names is None:
        return ["the exact names could not be derived from the pin suite, the generator and the deploy tool"]
    p: list[str] = []
    sec = subsection(runbook, "1.2")
    if not sec:
        return ["the runbook has no section 1.2 (the exact targets)"]
    cells = {plain(m.group(1)): m.group(2) for m in re.finditer(r"^\| (.+?) \| (.+?) \| (.+?) \|$", sec, re.M)}

    def cell(prefix: str) -> str:
        return next((v for k, v in cells.items() if k.startswith(prefix)), "")
    for prefix, value in (("the card file on the host (a1)", names["dest"]), ("the lovelace resource url (a2)", names["url"]), ("the lovelace resource type (a2)", names["type"]),
                          ("the new dashboard's url path", DASH_URL), ("the new dashboard's title", DASH_TITLE)):
        if f"`{value}`" not in cell(prefix):
            p.append(f"runbook 1.2: the row '{prefix}' does not hold `{value}`")
    for prefix, values in (("the .storage files read", (".storage/lovelace_resources", ".storage/lovelace_dashboards", ".storage/lovelace*", ".storage/lovelace.<dashboard id>")),
                           ("the dashboard files hashed", ("ecco/dashboards/",)), ("the folder listed", ("/config/www/ecco/",))):
        for v in values:
            if v not in cell(prefix):
                p.append(f"runbook 1.2: the row '{prefix}' does not hold {v}")
    for letter, step in (("a", "1"), ("b", "1"), ("c", "3"), ("d", "4")):
        if not re.search(r"^- \*\*\(" + letter + r"\) step " + step + r"\.\*\*", sec, re.M):
            p.append(f"runbook 1.2: the target check ({letter}) of step {step} is missing")
        if f"({letter}) step {step}:" not in plain(sections(checklist).get("2", "")):
            p.append(f"checklist section 2: the target check ({letter}) of step {step} is missing")
    a3 = next((m.group(0) for m in re.finditer(r"^\| A3 \|.*$", checklist, re.M)), "")
    if f"`{DASH_URL}`" not in a3 or f"`{DASH_TITLE}`" not in a3:
        p.append("the checklist's A3 row does not hold the dashboard's URL path and title (D-U1-5)")
    rd = next((m.group(0) for m in re.finditer(r"^\| read \|.*$", checklist, re.M)), "")
    for v in (".storage/lovelace_resources", ".storage/lovelace_dashboards", "ecco/dashboards/*.yaml", "/config/www/ecco/"):
        if v not in rd:
            p.append(f"the checklist's read row does not hold {v}")
    if fold(DASH_URL) not in fold(subsection(runbook, "5.5")) or fold(DASH_TITLE) not in fold(subsection(runbook, "5.5")):
        p.append("runbook 5.5 no longer suggests the dashboard URL path and title that the targets table holds")
    b1 = next((b for b in powershell_blocks(subsection(runbook, "5.1")) if "lovelace-before" in b), "")
    for need in ("-like '/local/ecco/*ecco-intelligence-card*'", f"-eq '{names['url']}'", f"-eq '{DASH_URL}'"):
        if need not in b1:
            p.append(f"runbook 5.1 block 1 does not make the target checks (a) and (b): {need} is missing")
    return p


def shape_problems(checklist: str, runbook: str, pins: dict, extra: dict, sources: dict[str, str]) -> list[str]:
    """[16] step 1b: the rows, the section, the command line, the extended block 3, the reference counts of the 14 Nov listing, the tool's flags and exit codes."""
    p: list[str] = []
    for label, body, keys in (
            ("runbook", sections(runbook).get("4", ""), ("geek_mode_live_shape_check.py", "states-before.json", "block 3", "its own go", "undeclared", "unexplained", "out of date for this host")),
            ("checklist", sections(checklist).get("4", ""), ("your separate go", "geek_mode_live_shape_check.py", "states-before.json", "undeclared", "unexplained", "out of date for this host", "production is unaffected"))):
        row = re.search(r"^\| 1b \|.*$", body, re.M)
        if not row:
            p.append(f"the {label}'s step table has no step 1b row")
            continue
        for k in keys:
            if k not in plain(row.group(0)):
                p.append(f"the {label}'s step 1b row does not say '{k}'")
    if not re.search(r"^### 5\.1b Step 1b: the live shape check$", runbook, re.M):
        p.append("the runbook has no section '5.1b Step 1b: the live shape check'")
    sec = subsection(runbook, "5.1b")
    if SHAPE_LINE not in "\n".join(powershell_blocks(sec)):
        p.append("runbook 5.1b: no PowerShell block holds the command line of the live shape check")
    if SHAPE_LINE not in "\n".join(powershell_blocks(checklist)):
        p.append("the checklist's PowerShell blocks do not hold the command line of the live shape check")
    b3 = next((b for b in powershell_blocks(subsection(runbook, "5.1")) if "core/api/states" in b), "")
    for need in ("-like '*ecco_intel*'", "$ids -notcontains $_", "ConvertTo-Json -InputObject $out -Depth 20", BLOCK3_MORE, BLOCK3_APPEND, BLOCK3_WRITE):
        if need not in b3:
            p.append(f"runbook 5.1 block 3 (the state read) no longer keeps every ecco_intel entity: {need} is missing")
    if all(n in b3 for n in (BLOCK3_MORE, BLOCK3_APPEND, BLOCK3_WRITE)) and not b3.index(BLOCK3_MORE) < b3.index(BLOCK3_APPEND) < b3.index(BLOCK3_WRITE):
        p.append("runbook 5.1 block 3: the entities named ecco_intel are no longer collected, appended and then written, in that order")
    src = sources.get("geek_mode_live_shape_check.py", "")
    if not src:
        p.append("the live shape check tool is missing")
    else:
        if "return 2" not in src or "G.compare_live(" not in src or "def compare_live" in src:
            p.append("the live shape check tool does not exit 2 on bad input, or does not call compare_live of geek_mode_coverage, or copies it")
        for fl in sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", plain(sec)))):
            if f'"{fl}"' not in src:
                p.append(f"runbook 5.1b names the flag {fl}, which the tool does not have")
        if plain(NOTE_TITLE) not in plain(sec):
            p.append("runbook 5.1b does not quote the title of the tool's self_test NOTE section")
        if NOTE_TITLE not in src:
            p.append("the live shape check tool does not print the NOTE title that runbook 5.1b quotes")
        if PROPOSED_DEFAULT not in src:
            p.append("the live shape check tool no longer prints the proposed-default line that the documents call superseded (the tool is preserved as reviewed)")
        mm = re.search(r"\ndef exit_code\(.*?(?=\n\ndef |\Z)", src, re.S)
        if not mm or 'rep["not_checked"]' not in mm.group(0) or "not allow_not_checked" not in mm.group(0):
            p.append("the tool's exit code does not fail closed on NOT_CHECKED_LIVE unless --allow-not-checked is given, as runbook 5.1b says")
    try:
        led = json.loads(extra["ledger"])
        live, tl = led["live"]["live_entities"], led["totals"]["live"]
        declared = pins.get("sources") or "?"
        reference = (f"exit 0 with {live} of {declared} present, {tl['PRESENT_LIVE'] - live} attribute rows present, {tl['NOT_PRESENT_LIVE']} conditional, "
                     f"0 unexplained, 0 undeclared and {tl['NOT_CHECKED_LIVE']} not checked")
        if plain(reference) not in plain(sec):
            p.append(f"runbook 5.1b: the reference counts of the committed 14 Nov listing are not '{reference}' (derived from the committed ledger)")
        if f"present_live {declared} of {declared} declared entities" not in plain(sec):
            p.append("runbook 5.1b: the expected PRESENT_LIVE count is not 'all of the declared entities'")
    except (KeyError, ValueError, TypeError):
        p.append("the committed ledger could not be read for the reference counts")
    return p


def writepath_problems(checklist: str, runbook: str, extra: dict) -> list[str]:
    """[17] the write-path statement: every test it names exists under that exact name; what it says of the card and the example is true of their sources."""
    p: list[str] = []
    rbf, clf = fold(runbook), fold(checklist)
    for key, name, in_checklist in WRITE_TESTS:
        if f"'{name}'" not in extra.get(key, ""):
            p.append(f"the Node test '{name[:60]}...' does not exist under that exact name in the {key} suite")
        if fold(name) not in rbf:
            p.append(f"the runbook does not name the test '{name[:60]}...' exactly")
        if in_checklist and fold(name) not in clf:
            p.append(f"the checklist does not name the test '{name[:60]}...' exactly")
    card = extra.get("card", "")
    if "on(b, 'click', () => this._ctl.set(mode))" not in card:
        p.append("the card's mode buttons no longer have the one click handler this._ctl.set(mode) that the runbook names")
    if "export const MORE_INFO_DOMAINS = Object.freeze(['sensor', 'binary_sensor', 'event']);" not in card:
        p.append("the card's more-info domains are no longer sensor, binary_sensor and event")
    m = re.search(r"export function createModeController\(.*?\n}\n", card, re.S)
    if not m or re.search(r"hass|callService|call_service|fetch\(", m.group(0)):
        p.append("createModeController is missing, or it now touches hass, a service or the network")
    example = extra.get("example", "")
    if sorted(re.findall(r"^\s*action:\s*([a-z-]+)\s*$", example, re.M)) != ["more-info", "toggle", "toggle"]:
        p.append("the example's actions are no longer the pause tile's toggle (tap and icon tap) and more-info (hold)")
    if re.search(r"^\s*(?:service|perform_action|target|navigation_path|url_path)\s*:", example, re.M):
        p.append("the example holds a service-call shaped key")
    sec11 = plain(subsection(runbook, "1.1"))
    for word in ("createmodecontroller", "canopenmoreinfo", "_applymode"):
        if word not in sec11:
            p.append(f"runbook 1.1 does not name {word}")
    if "createmodecontroller" not in plain(checklist):
        p.append("the checklist does not name createModeController")
    return p


def dashboards_problems(checklist: str, runbook: str) -> list[str]:
    """[18] the check of every existing dashboard: the block that writes the list from the baseline, and the step 4 rows."""
    p: list[str] = []
    blk = next((b for b in powershell_blocks(subsection(runbook, "5.4")) if "dashboards-to-check.txt" in b), "")
    if not blk:
        p.append("runbook 5.4 has no block that writes dashboards-to-check.txt")
    else:
        for need in ("$E = ", "dashboards-before.json", "sha-before.txt", "ecco/dashboards/*", "url_path") + DASH_LINES:
            if need not in blk:
                p.append(f"the dashboards-to-check block does not use {need}")
        if all(n in blk for n in DASH_LINES) and [blk.index(n) for n in DASH_LINES] != sorted(blk.index(n) for n in DASH_LINES):
            p.append("the dashboards-to-check block no longer builds the rows, then the header, then the cells, then writes the file, in that order")
    for label, body in (("runbook", sections(runbook).get("4", "")), ("checklist", sections(checklist).get("4", ""))):
        row = re.search(r"^\| 4 \|.*$", body, re.M)
        if not row or "each existing dashboard" not in plain(row.group(0)):
            p.append(f"the {label}'s step 4 row does not say that the owner checks EACH existing dashboard")
    return p


def gates_problems(checklist: str, runbook: str) -> list[str]:
    """[19] the release gates G1 to G7 of runbook 3 are in the checklist, each marked; the rollback is measured against the baseline and the backup, each step proven."""
    p: list[str] = []
    rb_gates = sorted(int(m.group(1)) for m in re.finditer(r"^\| G(\d) \|", subsection(runbook, "3"), re.M))
    if rb_gates != list(range(1, 8)):
        p.append(f"runbook section 3 has the gates {rb_gates}, not G1 to G7")
    rows = {int(m.group(1)): plain(m.group(0)) for m in re.finditer(r"^\| G(\d)\b.*$", sections(checklist).get("7", ""), re.M)}
    if sorted(rows) != rb_gates:
        p.append(f"the checklist's release gates are {sorted(rows)}, the runbook's {rb_gates}")
    for n, row in rows.items():
        if n == 1 and "satisfied by the offline work" not in row:
            p.append("checklist gate G1 is not marked 'satisfied by the offline work'")
        elif n == 5 and "resolved for u1 by the owner on 21 nov: separately tracked f3, no new entity" not in row:
            p.append("checklist gate G5 (RG-F3) is not marked 'resolved for U1 by the owner on 21 Nov: separately tracked F3, no new entity'")
        elif n not in (1, 5) and "yours at install time" not in row:
            p.append(f"checklist gate G{n} is not marked 'yours at install time'")
    sec6 = sections(checklist).get("6", "")
    for key in ("(i) the baseline", "byte-exact copy", "(ii) your protected full backup"):
        if key not in plain(sec6):
            p.append(f"checklist section 6 does not say '{key}'")
    items = re.findall(r"^\d\. \*\*(A[123])\b(.*)$", sec6, re.M)
    if [a for a, _ in items] != ROLLBACK_ORDER:
        p.append("checklist section 6 does not list the rollback A3, A2, A1")
    for a, rest in items:
        if "proven" not in rest.lower():
            p.append(f"checklist section 6: the rollback step {a} has no proof")
    return p


# ---------------------------------------------------------------------------------------------------------------------------------
# round 6 rule: the owner's ruling of 21 Nov 2026 on the baseline and step 1b stops
# ---------------------------------------------------------------------------------------------------------------------------------
def sentences(text: str) -> list[str]:
    """The sentences of a document as plain text: a paragraph, a table row, a numbered item and a bullet are each a unit of their own (so a table without full stops is not one long sentence), and a unit is cut after . ! or ?"""
    out: list[str] = []
    for par in re.split(r"\n\s*\n", text):
        for unit in re.split(r"\n(?=\|)|\n(?=\s*\d+\. )|\n(?=\s*[-*] )", par):
            out += re.split(r"(?<=[.!?])\s+", plain(unit))
    return out


def stoprules_problems(checklist: str, runbook: str) -> list[str]:
    """[20] the STOP, NOTE and values paragraphs word for word in the checklist (4.1), runbook 5.1b and runbook 6; each of the nine STOP items in each place; the NOTE paragraph holds no
    unknown, unavailable or failed state before its closing sentence; gate G4 in both documents; the step 1 and 1b rows point to the rule; the sentence that supersedes the tool's printed
    `proposed default` line; and `proposed default` or the old confirm-at-the-final-GO wording appear only in a sentence that says superseded."""
    p: list[str] = []
    places = (("checklist 4.1", subsection(checklist, "4.1")), ("runbook 5.1b", subsection(runbook, "5.1b")), ("runbook 6", subsection(runbook, "6")))
    stop, note, vals, never = plain(STOP_P), plain(NOTE_P), plain(VALUES_P), plain(NEVER_NOTES)
    for label, raw in places:
        text = plain(raw)
        if not text:
            p.append(f"{label}: the section is missing")
            continue
        if stop not in text:
            p.append(f"{label}: the STOP paragraph of the owner's ruling is not there word for word")
        for item in STOP_ITEMS:
            if plain(item) not in text:
                p.append(f"{label}: the STOP item '{item[:44]}' is missing")
        if note not in text:
            p.append(f"{label}: the NOTE paragraph of the owner's ruling is not there word for word")
        if never not in text:
            p.append(f"{label}: the sentence '{NEVER_NOTES}' is missing")
        if vals not in text:
            p.append(f"{label}: the values sentence (the shape tool never clears a value; the coordinator reads the values) is missing")
        lead_ok = False
        for par in re.split(r"\n\s*\n", raw):
            pt = plain(par)
            if pt.startswith(plain(NOTE_LEAD)):
                lead_ok = True
                head = pt.split(never)[0]
                bad = [w for w in NOTE_BAD_WORDS if w in head]
                if bad:
                    p.append(f"{label}: the NOTE paragraph lists a safety-relevant state as a note ({', '.join(bad)})")
        if not lead_ok:
            p.append(f"{label}: no paragraph starts with '{NOTE_LEAD}'")
        if not any(plain(par).startswith(plain(STOP_LEAD)) for par in re.split(r"\n\s*\n", raw)):
            p.append(f"{label}: no paragraph starts with '{STOP_LEAD}'")
    # gate G4, in both documents
    for label, body in (("checklist", sections(checklist).get("7", "")), ("runbook", subsection(runbook, "3"))):
        row = re.search(r"^\| G4 \|.*$", body, re.M)
        if not row or plain(G4_TEXT) not in plain(row.group(0)):
            p.append(f"the {label}'s gate G4 does not say '{G4_TEXT}'")
    # the step 1 and 1b rows of both step tables point to the rule
    for label, body, ptr, starts in (("checklist", sections(checklist).get("4", ""), CL_POINTER, ("| 1 | coordinator", "| 1b | coordinator")),
                                     ("runbook", sections(runbook).get("4", ""), RB_POINTER, ("| 1 | live read-only", "| 1b | live shape check"))):
        for start in starts:
            row = next((ln for ln in body.split("\n") if ln.startswith(start)), "")
            if not row or plain(ptr) not in plain(row):
                p.append(f"the {label}'s step row '{start[2:4].strip()}' does not point to the rule ('{ptr}')")
            elif "1b" in start and "never clears a value" not in plain(row):
                p.append(f"the {label}'s step 1b row does not say that the tool's note never clears a value")
    # the sentence that supersedes the tool's printed line
    for label, text in (("checklist 4.1", subsection(checklist, "4.1")), ("runbook 5.1b", subsection(runbook, "5.1b"))):
        if plain(SUPERSEDED_S) not in plain(text):
            p.append(f"{label}: the sentence that says the tool's printed `proposed default` wording is superseded by the owner's ruling is missing or changed")
    # the old wording only inside a sentence that says superseded (the history of rounds 4 and 5 is kept, marked)
    for label, text in (("checklist", checklist), ("runbook", runbook)):
        for sent in sentences(text):
            hit = [k for k in OLD_RULE_PHRASES if k in sent]
            if hit and "superseded" not in sent:
                p.append(f"the {label}: '{hit[0]}' is stated outside a sentence that says it is superseded: '{sent[:70]}'")
    return p


# ---------------------------------------------------------------------------------------------------------------------------------
# the analysis: every rule gives the list of its problems; an empty list is a pass
# ---------------------------------------------------------------------------------------------------------------------------------
def analyse(checklist: str, runbook: str, pins: dict, sources: dict[str, str], node_src: str = "", extra: dict | None = None) -> dict[str, list[str]]:
    r: dict[str, list[str]] = {}
    extra = extra or {}
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
    claim = re.search(r"it is now\s+(\d+)\s+lines", checklist)
    if not claim or int(claim.group(1)) != len(checklist.splitlines()):
        p.append(f"the checklist says it is now {claim.group(1) if claim else '?'} lines; it has {len(checklist.splitlines())}")
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
    # [14] to [19] (round 5)
    r["decisions"] = decisions_problems(checklist, runbook)
    r["targets"] = targets_problems(checklist, runbook, exact)
    r["shape"] = shape_problems(checklist, runbook, pins, extra, sources)
    r["writepath"] = writepath_problems(checklist, runbook, extra)
    r["dashboards"] = dashboards_problems(checklist, runbook)
    r["gates"] = gates_problems(checklist, runbook)
    # [20] (round 6)
    r["stoprules"] = stoprules_problems(checklist, runbook)
    return r


RULES = ("pins", "checks", "sections", "tools", "cls", "statements", "hygiene", "agreement", "commands", "names", "pinned", "node", "coverage",
         "decisions", "targets", "shape", "writepath", "dashboards", "gates", "stoprules")
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
    "decisions": "[14] D-U1-1, D-U1-2 and D-U1-4 are decided, D-U1-3, D-U1-5 and D-U1-6 keep their defaults, and nothing is authorised by the approval (both documents)",
    "targets": "[15] the exact targets table and the four target checks are in the runbook (1.2) and the checklist (2), derived from the pins; block 1 makes checks (a) and (b)",
    "shape": "[16] step 1b: the rows, the section, the command line, block 3 line by line (the append of the undeclared states included), the 14 Nov reference counts (from the ledger), the tool's flags, exit codes, NOTE title and fail-closed exit",
    "writepath": "[17] the write-path statement names Node tests that exist, and what it says of the card's mode switch, the more-info domains and the example's actions is true",
    "dashboards": "[18] the check of every existing dashboard: the dashboards-to-check block (catch-all row, header, three empty cells per row, in order) and the step 4 rows",
    "gates": "[19] the release gates G1 to G7 are in the checklist, each marked; the rollback is measured against the baseline and the backup, each step proven",
    "stoprules": "[20] the owner's ruling of 21 Nov 2026: the STOP (nine items), NOTE and values paragraphs word for word in the checklist 4.1, runbook 5.1b and runbook 6; G4; the step 1 and 1b rows; the supersession of the tool's printed line; the old wording only where superseded",
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


def kill_words(text: str, phrase: str, scope: str | None = None, repl: str = "REMOVED") -> str:
    """Replace the first occurrence of a phrase (whatever its line breaks and markup between the words), inside a section if one is named, by REMOVED (or by repl)."""
    # markdown emphasis and code ticks may sit between any two characters of the raw text (`**Save**,` is the plain `save,`)
    rx = "".join(r"[\s*`]+" if ch == " " else re.escape(ch) + r"[*`]*" for ch in plain(phrase))
    lo, hi = 0, len(text)
    if scope is not None:
        span = subsection_span(text, scope)
        if span is None:
            return text
        lo, hi = span
    return text[:lo] + re.sub(rx, lambda _m: repl, text[lo:hi], count=1, flags=re.I) + text[hi:]


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
    # --- round 5: the owner's decision of 21 Nov 2026 (T1 to T6), one structural mutant for each rule's own checks (the pinned sentences are killed one by one below)
    def drop_row(text: str, first_cell: str) -> str:
        return re.sub(r"^\| " + re.escape(first_cell) + r" \|.*\n", "", text, count=1, flags=re.M)

    no_auto = "No automatic installation or live access is authorised"
    shape_cmd = "geek_mode_live_shape_check.py"
    for name, fn, rule in [
        ("G1 the checklist's A3 row names another dashboard path", lambda t: on_line(t, "| A3 |", lambda ln: ln.replace(DASH_URL, "ecco-modes-u2")), "targets"),
        ("G2 the checklist's A3 row loses the dashboard title", lambda t: on_line(t, "| A3 |", lambda ln: ln.replace(DASH_TITLE, "ECCO Modes")), "targets"),
        ("G3 the checklist's read row loses the resource list", lambda t: on_line(t, "| read |", lambda ln: ln.replace("`.storage/lovelace_resources`, ", "")), "targets"),
        ("G4 the checklist's read row is dropped", lambda t: drop_row(t, "read"), "targets"),
        ("G5 the target check (c) of the checklist is mislabelled", lambda t: t.replace("(c) step 3:", "(c) step 4:", 1), "targets"),
        ("G6 the checklist's step 1b row is removed", lambda t: drop_row(t, "1b"), "shape"),
        ("G7 the live shape command line is dropped from the checklist's blocks", lambda t: edit_block(t, shape_cmd, lambda b: re.sub(r"^[^\n]*" + shape_cmd + r"[^\n]*\n", "", b, flags=re.M)), "shape"),
        ("G8 the checklist's step 1b row loses its separate go", lambda t: on_line(t, "| 1b |", lambda ln: ln.replace("your separate go", "your go")), "shape"),
        ("G9 the checklist's step 4 row checks only the Overview", lambda t: on_line(t, "| 4 | you add", lambda ln: ln.replace("EACH existing dashboard", "the production Overview")), "dashboards"),
        ("G10 the checklist's G3 gate row is removed", lambda t: drop_row(t, "G3"), "gates"),
        ("G11 G5 (RG-F3) is marked as yours at install time", lambda t: on_line(t, "| G5, RG-F3 |", lambda ln: ln.replace("resolved for U1 by the owner on 21 Nov: separately tracked F3, no new entity", "yours at install time")), "gates"),
        ("G12 G1 is marked as yours at install time", lambda t: on_line(t, "| G1 |", lambda ln: ln.replace("satisfied by the offline work", "yours at install time")), "gates"),
        ("G13 the rollback step A1 loses its proof", lambda t: on_line(t, "3. **A1, the card file.**", lambda ln: ln.replace("Proven:", "Checked:")), "gates"),
        ("G14 the baseline is no longer named in the rollback section", lambda t: t.replace("(i) the baseline", "(i) a list", 1), "gates"),
        ("G15 D-U1-4 is no longer marked decided", lambda t: on_line(t, "| D-U1-4 ", lambda ln: ln.replace("**decided:**", "**open:**")), "decisions"),
        ("G16 D-U1-6 is marked decided instead of keeping its default", lambda t: on_line(t, "| D-U1-6 ", lambda ln: ln.replace("default: yes", "decided: yes")), "decisions"),
        ("G17 the claimed length of the checklist is wrong", lambda t: re.sub(r"it is now\s+\d+\s+lines", "it is now 150 lines", t), "hygiene"),
        ("G18 the no-automatic-installation sentence is dropped from the checklist", lambda t: kill_words(t, no_auto, None), "decisions"),
        ("G19 a write-path test name is mistyped in the checklist", lambda t: t.replace("generated config: both modes and a state change touch nothing", "generated config: both modes and a state change touch nothin", 1), "writepath"),
        ("G20 the checklist no longer names createModeController", lambda t: t.replace("`createModeController`", "`createController`", 1), "writepath"),
    ]:
        add("checklist", name, fn, rule)
    for name, fn, rule in [
        ("H1 the runbook's 1.2 dashboard path is changed", lambda t: on_line(t, "| the new dashboard's URL path", lambda ln: ln.replace(DASH_URL, "ecco-modes-u2")), "targets"),
        ("H2 the runbook's 1.2 dashboard title is changed", lambda t: on_line(t, "| the new dashboard's title", lambda ln: ln.replace(DASH_TITLE, "ECCO Modes")), "targets"),
        ("H3 the sha8 is mistyped in the runbook's 1.2 resource URL row", lambda t: on_line(t, "| the Lovelace resource URL (A2)", lambda ln: ln.replace(sha8, wrong8)), "targets"),
        ("H4 the runbook's 1.2 .storage row loses the dashboard list", lambda t: on_line(t, "| the `.storage` files read", lambda ln: ln.replace("`.storage/lovelace_dashboards`, ", "")), "targets"),
        ("H5 the target check (c) of the runbook is mislabelled", lambda t: t.replace("- **(c) step 3.**", "- **(c) step 4.**", 1), "targets"),
        ("H6 block 1 loses the count of Intelligence-card resources under /local/ecco/", lambda t: t.replace("@($res | Where-Object { $_.url -like '/local/ecco/*ecco-intelligence-card*' }).Count\n", "", 1), "targets"),
        ("H7 block 1 checks another dashboard path", lambda t: edit_block(t, "lovelace-before", lambda b: b.replace("-eq 'ecco-modes-u1'", "-eq 'ecco-modes-u2'")), "targets"),
        ("H8 the runbook's 5.5 suggests another dashboard title", lambda t: t.replace("(suggested: `ECCO Modes\n(first look)`)", "(suggested: `ECCO Modes\n(look)`)", 1), "targets"),
        ("H9 the runbook's step 1b row is removed", lambda t: drop_row(t, "1b"), "shape"),
        ("H10 block 3 no longer keeps every ecco_intel entity", lambda t: t.replace("-like '*ecco_intel*'", "-like '*ecco_x*'", 1), "shape"),
        ("H11 the 293 reference count of 5.1b is changed", lambda t: t.replace("293 attribute rows present", "292 attribute rows present", 1), "shape"),
        ("H12 the 42 reference count of 5.1b is changed", lambda t: on_line(t, "into states gives, offline, exit 0 with 16 of 17 present", lambda ln: ln.replace("42 conditional", "41 conditional")), "shape"),
        ("H13 the tool name is mistyped in the 5.1b block", lambda t: edit_block(t, shape_cmd, lambda b: b.replace("shape_check", "shape_chek")), "shape"),
        ("H14 5.1b names a flag that the tool does not have", lambda t: t.replace("`--write-shape <path>`", "`--write-shapes <path>`", 1), "shape"),
        ("H15 the 5.1b heading is renamed", lambda t: t.replace("### 5.1b Step 1b: the live shape check", "### 5.1b Step 1b: a check", 1), "shape"),
        ("H16 the expected PRESENT_LIVE count of 5.1b is not all of the declared entities", lambda t: t.replace("PRESENT_LIVE 17\nof 17", "PRESENT_LIVE 16\nof 17", 1), "shape"),
        ("H17 the runbook's step 4 row checks only the Overview", lambda t: on_line(t, "| 4 | the owner adds ONE module resource", lambda ln: ln.replace("EACH existing dashboard", "the production Overview")), "dashboards"),
        ("H18 the dashboards-to-check block reads another baseline file", lambda t: edit_block(t, "dashboards-to-check.txt", lambda b: b.replace("sha-before.txt", "sha-after.txt")), "dashboards"),
        ("H19 the dashboards-to-check file is renamed", lambda t: edit_block(t, "dashboards-to-check.txt", lambda b: b.replace("dashboards-to-check.txt", "list.txt")), "dashboards"),
        ("H20 G7 is removed from the runbook's gates", lambda t: drop_row(t, "G7"), "gates"),
        ("H21 RG-F3 is waived instead of resolved in the runbook's G5", lambda t: t.replace("**resolved for U1 only**", "**waived for U1 only**", 1), "decisions"),
        ("H22 D-U1-2 is no longer marked decided in the runbook", lambda t: on_line(t, "| D-U1-2 |", lambda ln: ln.replace("**DECIDED by the owner on 21 Nov 2026, for U1 only:**", "**to decide:**")), "decisions"),
        ("H23 D-U1-3 is marked decided in the runbook", lambda t: on_line(t, "| D-U1-3 |", lambda ln: ln.replace("keeps its default", "DECIDED")), "decisions"),
        ("H24 a write-path test name is mistyped in the runbook", lambda t: t.replace("AC5 the switch never changes helper or service state", "AC5 the switch never changes helper or service stat", 1), "writepath"),
        ("H25 the runbook drops a write-path test it must name", lambda t: kill_words(t, WRITE_TESTS[5][1], "1.1"), "writepath"),
        ("H26 the no-automatic-installation sentence is dropped from the runbook", lambda t: kill_words(t, no_auto, None), "decisions"),
        ("H27 the runbook's 1.1 no longer names canOpenMoreInfo", lambda t: t.replace("(`canOpenMoreInfo`:", "(`canOpen`:", 1), "writepath"),
    ]:
        add("runbook", name, fn, rule)
    # --- round 5, F1: the dashboards-to-check block (the three answer columns, the catch-all row, the header)
    def dash_block(fn):
        return lambda t: edit_block(t, "dashboards-to-check.txt", fn)
    cells = "'| {0} |  |  |  |'"
    catch_all = "$what += 'every other sidebar entry (Energy, Map, any YAML dashboard registered elsewhere)'\n"
    wall = "$what += 'any wall or phone client the owner uses'\n"
    add("runbook", "F1 the catch-all row is dropped from the dashboards-to-check block", dash_block(lambda b: b.replace(catch_all, "")), "dashboards")
    add("runbook", "F1 the catch-all row names only Energy", dash_block(lambda b: b.replace("(Energy, Map, any YAML dashboard registered elsewhere)", "(Energy)")), "dashboards")
    add("runbook", "F1 the answer cells are dropped from every row", dash_block(lambda b: b.replace(cells, "'| {0} |'")), "dashboards")
    add("runbook", "F1 one answer cell is missing from every row", dash_block(lambda b: b.replace(cells, "'| {0} |  |  |'")), "dashboards")
    add("runbook", "F1 the header lost the third question", dash_block(lambda b: b.replace(" | no console error naming the shell | responds |'", " | no console error naming the shell |'")), "dashboards")
    add("runbook", "F1 the wall and phone row is dropped from the block", dash_block(lambda b: b.replace(wall, "")), "dashboards")
    add("runbook", "F1 the rows are written without the answer format", dash_block(lambda b: b.replace("$lines += @($what | ForEach-Object { " + cells + " -f $_ })", "$lines += $what")), "dashboards")
    add("runbook", "F1 the table is not written to the file", dash_block(lambda b: b.replace("$lines | Out-File -Encoding utf8 \"$E\\dashboards-to-check.txt\"\n", "")), "dashboards")
    add("runbook", "F1 the header is written after the rows", dash_block(lambda b: b.replace("$lines = @('| open this | renders as before | no console error naming the shell | responds |')\n", "")
                                                                         .replace("$lines | Out-File", "$lines = @('| open this | renders as before | no console error naming the shell | responds |') + $lines\n$lines | Out-File")), "dashboards")
    # --- round 5, F2: block 3 appends the undeclared ecco_intel states (the review found that dropping '+ $more' survived)
    def block3(fn):
        return lambda t: edit_block(t, "core/api/states", fn)
    add("runbook", "F2 block 3 no longer appends the undeclared ecco_intel states (the '+ $more' dropped)", lambda t: t.replace(BLOCK3_APPEND, "$out = @($out)", 1), "shape")
    add("runbook", "F2 the filter of block 3's $more line names another word", lambda t: t.replace("$_ -like '*ecco_intel*' -and $ids", "$_ -like '*ecco_other*' -and $ids", 1), "shape")
    add("runbook", "F2 the append line of block 3 is dropped", lambda t: t.replace(BLOCK3_APPEND + "\n", "", 1), "shape")
    add("runbook", "F2 the $more line of block 3 is dropped", block3(lambda b: b.replace(BLOCK3_MORE + "\n", "")), "shape")
    add("runbook", "F2 the $more line of block 3 no longer leaves out the listed ids", lambda t: t.replace(" -and $ids -notcontains $_ }", " }", 1), "shape")
    add("runbook", "F2 the append of block 3 comes after the write of the file", block3(lambda b: b.replace(BLOCK3_APPEND + "\n", "", 1).replace("$out | Select-Object", BLOCK3_APPEND + "\n$out | Select-Object", 1)), "shape")
    # --- round 6 (the owner's ruling of 21 Nov 2026): the STOP, NOTE and values rule word for word in three places; each of the nine STOP items dropped in turn
    def append_in(text: str, scope: str, line: str) -> str:
        span = subsection_span(text, scope)
        if span is None:   # the section is not there: nothing to append to (the mutation then does not change the text, and the suite says so)
            return text
        return text[:span[1]] + "\n" + line + "\n" + text[span[1]:]

    places6 = (("checklist", "4.1", "the checklist 4.1"), ("runbook", "5.1b", "runbook 5.1b"), ("runbook", "6", "runbook 6"))
    for target, scope, label in places6:
        for n, item in enumerate(STOP_ITEMS, 1):
            add(target, f"S{n} STOP item {n} ('{item[:34]}') dropped from {label}", lambda t, s=scope, it=item: kill_words(t, it, s), "stoprules")
        add(target, f"S10 the NOTE paragraph dropped from {label}", lambda t, s=scope: kill_words(t, NOTE_P, s), "stoprules")
        add(target, f"S11 'never notes' (the closing sentence of the NOTE paragraph) dropped from {label}", lambda t, s=scope: kill_words(t, NEVER_NOTES, s), "stoprules")
        add(target, f"S12 the values sentence dropped from {label}", lambda t, s=scope: kill_words(t, VALUES_P, s), "stoprules")
        add(target, f"S13 'SHADOW with a fresh result' becomes 'SHADOW' in {label}",
            lambda t, s=scope: kill_words(t, "the Intelligence status not SHADOW with a fresh result", s, "the Intelligence status not SHADOW"), "stoprules")
        add(target, f"S14 a safety-relevant state (unknown) is moved into the NOTE list in {label}",
            lambda t, s=scope: kill_words(t, "informational findings only: the names of the check codes", s, "informational findings only: unknown states, the names of the check codes"), "stoprules")
    add("checklist", "S15 gate G4 of the checklist is back to 'the states noted'",
        lambda t: on_line(t, "| G4 |", lambda ln: ln.replace(G4_TEXT + " (4.1)", "the live baseline saved (steps 1 and 1b), the shape check exits 0, the states noted")), "stoprules")
    add("runbook", "S16 gate G4 of the runbook no longer says that no STOP condition holds", lambda t: on_line(t, "| G4 |", lambda ln: ln.replace("is saved AND no STOP condition of the list holds", "is saved")), "stoprules")
    add("runbook", "S17 'or its state noted if not' is restored in gate G4 of the runbook",
        lambda t: on_line(t, "| G4 |", lambda ln: ln.replace("the Intelligence status reads SHADOW with a fresh result;", "the Intelligence status reading SHADOW with a fresh result (or its state noted if not);")), "pinned")
    add("checklist", "S18 'you have not ruled on it yet' is restored in the checklist's section 7", lambda t: t.replace("not an open default.", "you have not ruled on it yet.", 1), "pinned")
    add("runbook", "S19 'the owner has not ruled on it' is restored in runbook 5.1b", lambda t: append_in(t, "5.1b", "The default is the coordinator's proposal and the owner has not ruled on it."), "pinned")
    add("checklist", "S20 the supersession sentence is dropped from the checklist 4.1", lambda t: kill_words(t, SUPERSEDED_S, "4.1"), "stoprules")
    add("runbook", "S21 the supersession sentence is dropped from runbook 5.1b", lambda t: kill_words(t, SUPERSEDED_S, "5.1b"), "stoprules")
    add("checklist", "S22 'proposed default' is stated again outside a sentence that says superseded (checklist)", lambda t: append_in(t, "4.1", "The self_test note is a proposed default of the shape check."), "stoprules")
    add("runbook", "S23 'proposed default' is stated again outside a sentence that says superseded (runbook 5.1b)", lambda t: append_in(t, "5.1b", "The self_test note is a proposed default of the shape check."), "stoprules")
    add("runbook", "S24 the confirm-at-the-final-GO wording is stated again without 'superseded' (runbook 5.1b)", lambda t: append_in(t, "5.1b", "The owner confirms or changes it at the final GO."), "stoprules")
    add("runbook", "S25 the round 5 sentence loses its supersession marker (section 13, the F4 sentence)",
        lambda t: t.replace("(F4; superseded by the owner's ruling of 21 Nov 2026 (5.1b));", "(F4);", 1), "stoprules")
    add("runbook", "S26 the round 4 sentence loses its supersession marker (section 13, item 3)",
        lambda t: t.replace("at the final GO, superseded by the owner's ruling of 21 Nov 2026 (5.1b)).", "at the final GO).", 1), "stoprules")
    add("runbook", "S27 the round 4 sentence of item 7 loses its supersession marker (section 13)",
        lambda t: t.replace("is a STOP, superseded by the owner's ruling of 21 Nov 2026 (5.1b).**", "is a STOP.**", 1), "stoprules")
    for target, pointer, who, starts in (("checklist", CL_POINTER, "checklist", ("| 1 | coordinator", "| 1b | coordinator")),
                                         ("runbook", RB_POINTER, "runbook", ("| 1 | live read-only", "| 1b | live shape check"))):
        for start in starts:
            add(target, f"S28 the {who}'s step {start[2:4].strip()} row lists the old shorter stops instead of pointing to the rule",
                lambda t, st=start, ptr=pointer: on_line(t, st, lambda ln: ln.replace(ptr, "Core not running; a copy that is not byte-exact")), "stoprules")
    add("checklist", "S29 the checklist's step 1b row no longer says that the tool's note never clears a value",
        lambda t: on_line(t, "| 1b | coordinator", lambda ln: ln.replace("; the tool's note never clears a value", "")), "stoprules")
    add("runbook", "S30 the runbook's step 1b row no longer says that the tool's note never clears a value",
        lambda t: on_line(t, "| 1b | live shape check", lambda ln: ln.replace(", and the tool's note, being shape-only, never clears a value", "")), "stoprules")
    add("runbook", "S31 section 6 keeps the old baseline clause (Core not running or the status not what it was) instead of the list",
        lambda t: t.replace("a STOP condition of the baseline list below holds (and, at any later step, the Intelligence\nstatus is no longer what the baseline recorded)", "the baseline shows Core not running or the Intelligence\nstatus not what it was", 1), "pinned")
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

TOOL_MUTANTS = [   # mutants of the live shape check tool's source (round 5: what runbook 5.1b says of the flag, the NOTE title, the exit code and the proposed default is checked against it)
    ("T1 the tool has no --allow-not-checked flag", lambda s: s.replace('"--allow-not-checked"', '"--allow-checked"'), "shape"),
    ("T2 the tool's NOTE title is not the one the runbook quotes", lambda s: s.replace("NOTE (free-form self-test", "NOTE (free self-test"), "shape"),
    ("T3 the tool's exit code no longer fails closed on NOT_CHECKED_LIVE", lambda s: s.replace('(rep["not_checked"] and not allow_not_checked)', "False"), "shape"),
    ("T4 the tool no longer prints the proposed-default line that the documents call superseded", lambda s: s.replace("anything else UNDECLARED or any unexplained absence is a STOP", "anything else UNDECLARED is a STOP"), "shape"),
]

EXTRA_MUTANTS = [   # mutants of the sources the new rules read (the documents say what the card, the example, the ledger and the Node suites hold: these show each claim is checked against them)
    ("E1 the card's mode buttons call a service", "card", lambda s: s.replace("this._ctl.set(mode)", "this._hass.callService('x', 'y')", 1), "writepath"),
    ("E2 the example gains a service action", "example", lambda s: s + "\n            tap_action:\n              action: call-service\n", "writepath"),
    ("E3 the more-info domains gain switch", "card", lambda s: s.replace("['sensor', 'binary_sensor', 'event']", "['sensor', 'switch', 'event']", 1), "writepath"),
    ("E4 the mode controller reads hass", "card", lambda s: s.replace("  let mode = DEFAULT_MODE;\n  const api = {", "  let mode = DEFAULT_MODE;\n  const hass = null;\n  const api = {", 1), "writepath"),
    ("E5 the ledger's conditional count changes", "ledger", lambda s: re.sub(r'("NOT_PRESENT_LIVE":\s*)42\b', r"\g<1>43", s, count=1), "shape"),
    ("E6 a Node test is renamed", "element", lambda s: s.replace("AC5 the switch never changes helper or service state", "AC5 the switch never changes state", 1), "writepath"),
    ("E7 the example loses an action", "example", lambda s: s.replace("action: more-info", "action: none", 1), "writepath"),
    ("E8 the ledger's not-checked count changes", "ledger", lambda s: re.sub(r'("NOT_CHECKED_LIVE":\s*)1\b', r"\g<1>2", s, count=1), "shape"),
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
    extra = {key: read(rel) for key, rel in EXTRA_REL.items()}
    path = Path(argv[1]) if len(argv) > 1 else ROOT / CHECKLIST_REL
    print(f"checklist: {path}")
    if not path.is_file():
        check("the checklist exists", False, str(path))
        return finish()
    checklist = path.read_bytes().decode("utf-8", errors="replace")
    check("the pins could be read from the pin suite", all(pins[k] for k in ("card_size", "card_sha256", "config_size", "config_sha256", "sources", "attribute_rows")), str(pins))

    result = analyse(checklist, runbook, pins, sources, node_src, extra)
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
    check("the nine STOP items are each a part of the canonical STOP paragraph, in order",
          len(STOP_ITEMS) == 9 and all(plain(i) in plain(STOP_P) for i in STOP_ITEMS) and [plain(STOP_P).index(plain(i)) for i in STOP_ITEMS] == sorted(plain(STOP_P).index(plain(i)) for i in STOP_ITEMS))
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
            got = fired(analyse(mutated, runbook, pins, sources, node_src, extra))
        else:
            got = fired(analyse(checklist, mutated, pins, sources, node_src, extra))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    for name, mutate, rule in NODE_MUTANTS:
        mutated = mutate(node_src)
        check(f"{name}: the mutation changes the text", mutated != node_src)
        got = fired(analyse(checklist, runbook, pins, sources, mutated, extra))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    for name, key, mutate, rule in EXTRA_MUTANTS:
        mutated = mutate(extra[key])
        check(f"{name}: the mutation changes the text", mutated != extra[key])
        got = fired(analyse(checklist, runbook, pins, sources, node_src, {**extra, key: mutated}))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    tool_key = "geek_mode_live_shape_check.py"
    for name, mutate, rule in TOOL_MUTANTS:
        mutated = mutate(sources[tool_key])
        check(f"{name}: the mutation changes the text", mutated != sources[tool_key])
        got = fired(analyse(checklist, runbook, pins, {**sources, tool_key: mutated}, node_src, extra))
        ok = rule in got
        killed += ok
        check(f"{name}: killed by the rule [{rule}] (fired: {', '.join(sorted(got)) or 'none'})", ok)
    total = len(mutants) + len(NODE_MUTANTS) + len(EXTRA_MUTANTS) + len(TOOL_MUTANTS)
    n_cl = sum(1 for m in mutants if m[0] == "checklist")
    check(f"at least six mutants are run, and every one is killed ({killed} of {total}: {n_cl} of the checklist, {len(mutants) - n_cl} of the runbook, {len(NODE_MUTANTS)} of the Node test, "
          f"{len(EXTRA_MUTANTS)} of the card, the example, the ledger and the Node suites, {len(TOOL_MUTANTS)} of the live shape check tool)", total >= 6 and killed == total)
    print("")
    print(f"{PASSED[0]} PASS, {len(FAILURES)} FAIL")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


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
