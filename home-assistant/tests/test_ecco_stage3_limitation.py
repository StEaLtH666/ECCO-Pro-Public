"""Offline static suite: the Stage 3 LIMITATION is stated, in plain words and identically, everywhere a reader meets the Stage 3 overrides
(release gate RG-ST3; owner directive of 17 Nov 2026, "do not describe Hold battery, Skip tonight or Prepare for power cut as fully enforced").

The limitation: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant or by an
assistant. The Stage 3 overrides and the reserve protect ECCO's own starts and the dashboard card, NOT an administrator, an assistant or a press of
the dongle's own button, and the helpers are plain helpers an administrator or assistant can write. Binding the Start button needs a firmware gate
(a flash), which is a separate approval and is not part of Stage 3.

  [1] places    ONE regex (the sentence, word for word, on one line) matches exactly once in each of: the card's visible Stage 3 controls (the source
                and the built bundle), the card README, the plan-core README, and the headers of the two Stage 3 Home Assistant packages; in the
                packages it sits on a comment line, so it adds no YAML content
  [2] visible   in the card the note is a plain paragraph placed in the controls block ABOVE the "scripts not found" branch, so it is shown
                whenever the controls are, with no event binding, no button and no link
  [3] no path   the card source adds no call-service or write path for it: no service call in src/plan/, the controls keep exactly their two
                click handlers, the plan call allow-list is still `script.turn_on` on three ids and names no button press, and the Stage 3
                package headers add comments only
  [4] mutation  each way of losing the text or adding a path is caught by the checks above; the untouched tree is not flagged
  [5] manifest  the deployment manifest states the limitation in one short sentence on the guarded-start stanza (and never claims full enforcement);
                the scheduled Dump to Grid stanza carries the helper dependency and the active-override warning beside R9's full-restart note;
                the three Stage 3 stanzas (plan helpers, scheduled start, guarded start) say the plan helpers go in the SAME deployment, before the
                ONE full restart, that the order of the stanzas does not matter, and make no copy-order claim (the deploy tool copies every package and
                restarts only as a separate step); the guarded start package header says the same
  [6] wording   (finding 3 of the independent review of 18 Nov 2026; additive) the corrected wording stands at each place that carries it: an override
                holds back ECCO's own scheduled and guarded export starts, Prepare for power cut sets the reserve ECCO's plan uses, and no override changes the
                inverter's own reserve, stops the house using the battery, charges the battery or binds the dongle's own Start button; the phrase 'protected
                reserve' (any case) is absent from the card sources, the bundle, both READMEs and the plan helper package; the plan-core README has the
                'Known limitations (stated, not fixed in this change)' section with all its items, each with its direction of failure; the Stage 3
                limitation sentence is still in every place; mutants and a control
  [7] second    (second independent review of the fixes, 18 Nov 2026; additive) the Known limitations section now has 22 items: 9 and 10 say what was shown (item 9 was
                run and is not a failure; item 10 was only read), 11 is reworded, 19 to 22 are new (restart inside the repeated hour, the overwritten BLOCKED text, a
                momentary unreadable sensor, the leftover staging); the status wording of each, the helper package comment, the schedule package header and the
                CHANGELOG caveats are required, the over-claiming sentences must be gone; mutants and a control
  [8] item 20   (owner decision r14, 19 Nov 2026; additive) limitation 20, the press-time BLOCKED text overwritten with STARTED OK, is FIXED: item 20, the schedule package header, the alert
                sentence and the CHANGELOG say so in the new words, the old wording (overwritten, no alert, dismissed, only the record is lost) is gone from item 20 and the header, the Stage 3
                limitation sentence (RG-ST3: the dongle's own Start button is not bound) stands exactly once in each place and item 20 and the header still say so, nothing says 'fully enforced',
                all 22 items are still listed; mutants and a control

Writes nothing; no Home Assistant, no network, no hardware. It proves the text is there and that no path was added; it does not make the
overrides stronger (they stay a PARTIAL protection until the firmware boundary is addressed).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

CARD = ROOT / "frontend" / "ecco-energy-actions-card"
PLACES = {
    "card controls (source)": CARD / "src" / "plan" / "controls.ts",
    "card bundle": CARD / "dist" / "ecco-energy-actions-card.js",
    "card README": CARD / "README.md",
    "plan-core README": ROOT / "frontend" / "ecco-plan-core" / "README.md",
    "package header: ecco_plan_helpers.yaml": ROOT / "home-assistant" / "packages" / "ecco_plan_helpers.yaml",
    "package header: ecco_dump_to_grid_guarded_start.yaml": ROOT / "home-assistant" / "packages" / "ecco_dump_to_grid_guarded_start.yaml",
}
PACKAGE_PLACES = ("package header: ecco_plan_helpers.yaml", "package header: ecco_dump_to_grid_guarded_start.yaml")

# The one sentence (ASCII, one line, no site value), restated here independently of the card source.
LIMITATION = (
    "Partial protection only: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant "
    "or by an assistant. These overrides and the reserve protect ECCO's own starts and this card, not an administrator, an assistant or a press of "
    "the dongle's own button, and their helpers are plain helpers that an administrator or assistant can write. Binding the Start button needs a "
    "firmware gate (a flash, approved separately)."
)
LIMITATION_RE = re.compile(re.escape(LIMITATION))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def text_of(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    except OSError:
        return ""


BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
LINE_COMMENT = re.compile(r"(?m)^\s*//.*$")


def code_of(ts: str) -> str:
    """TypeScript source with block comments and whole-line comments removed."""
    return LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", ts))


def places_problems(texts: dict[str, str]) -> list[str]:
    out = []
    for name in PLACES:
        n = len(LIMITATION_RE.findall(texts.get(name, "")))
        if n != 1:
            out.append(f"{name}: {n}x")
    return out


def package_comment_problems(texts: dict[str, str]) -> list[str]:
    """In each package the sentence is on a comment line (so no YAML content is added)."""
    out = []
    for name in PACKAGE_PLACES:
        lines = [ln for ln in texts.get(name, "").split("\n") if LIMITATION in ln]
        if len(lines) != 1 or not lines[0].lstrip().startswith("#"):
            out.append(name)
    return out


def visible_problems(controls: str) -> list[str]:
    """The note is one plain paragraph in controlsView, above the scripts-missing branch."""
    out = []
    note = re.findall(r"<p class=\"plan-reason plan-limitation\" data-plan-limitation role=\"note\">\$\{START_BUTTON_LIMITATION\}</p>", controls)
    if len(note) != 1:
        out.append(f"the note paragraph appears {len(note)}x")
        return out
    at, branch = controls.index(note[0]), controls.find("${vm.missingScripts.length")
    if not 0 <= at < branch:
        out.append("the note is not above the scripts-missing branch")
    view = controls[controls.find("export function controlsView"):]
    if view.find(note[0]) < 0 or view.find(note[0]) > view.find("vm.missingScripts.length"):
        out.append("the note is not inside controlsView before its conditional")
    if not re.search(r"export const START_BUTTON_LIMITATION =\s*\n?\s*\"" + re.escape(LIMITATION) + r"\";", controls):
        out.append("START_BUTTON_LIMITATION is not exactly the sentence")
    if re.search(r"data-plan-limitation[^>]*[@.?]?(click|change|input|keydown)", note[0]) or "@" in note[0] or "<button" in note[0] or "<a " in note[0]:
        out.append("the note carries an event binding, a button or a link")
    return out


def path_problems(controls: str, actions: str, plan_dir_texts: dict[str, str]) -> list[str]:
    out = []
    cc = code_of(controls)
    if "callService" in cc or re.search(r"\bhass\b", cc):
        out.append("controls.ts calls the service layer or touches hass")
    if len(re.findall(r"@click=", cc)) != 2:
        out.append("controls.ts no longer has exactly its two click handlers (a choice and Cancel)")
    if len(re.findall(r"\bdispatch\(", cc)) != 2:
        out.append("controls.ts no longer dispatches exactly two calls")
    for name, t in plan_dir_texts.items():
        if "callService" in code_of(t):
            out.append(f"src/plan/{name} names callService")
    ac = code_of(actions)
    ids = re.search(r"export const PLAN_CONTROL_IDS = \{(.*?)\} as const;", ac, re.S)
    keys = sorted(re.findall(r"\"(\w+)\"\s*:", ids.group(1))) if ids else []
    if keys != ["cancel_script", "last_result", "start_script"]:
        out.append(f"PLAN_CONTROL_IDS is not the three declared ids ({keys})")
    if not re.search(r"c\.domain !== \"script\" \|\| c\.service !== \"turn_on\"", ac):
        out.append("the allow-list no longer requires script.turn_on")
    if re.search(r"\"button\"|\bpress\b|\"switch\"|set_value|\"esphome\"|domain:\s*\"(?!script\")", ac):
        out.append("planActions.ts names a button press or another domain")
    return out


texts = {name: text_of(p) for name, p in PLACES.items()}
controls_text = texts["card controls (source)"]
actions_text = text_of(CARD / "src" / "plan" / "planActions.ts")
plan_dir = {p.name: text_of(p) for p in sorted((CARD / "src" / "plan").glob("*.ts"))}

# ===========================================================================
print("[1] places")
# ===========================================================================
check("every place exists and is readable", all(texts[n] for n in PLACES), str([n for n in PLACES if not texts[n]]))
check("the sentence is ASCII, one line, and names no address, token or site value",
      LIMITATION.isascii() and "\n" not in LIMITATION and not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|token|password|key=", LIMITATION, re.I))
for name in PLACES:
    n = len(LIMITATION_RE.findall(texts[name]))
    check(f"the limitation sentence stands exactly once in {name}", n == 1, f"{n}x")
check("in each Stage 3 package it is a comment line (no YAML content added)", not package_comment_problems(texts), str(package_comment_problems(texts)))

# ===========================================================================
print("")
print("[2] visible in the card")
# ===========================================================================
check("the card shows it as a plain paragraph above the scripts-missing branch of the controls, with no binding, button or link",
      not visible_problems(controls_text), str(visible_problems(controls_text)))

# ===========================================================================
print("")
print("[3] no call-service or write path")
# ===========================================================================
check("the card source adds no service call or write path for it (controls: two handlers, no callService, no hass; allow-list unchanged)",
      not path_problems(controls_text, actions_text, plan_dir), str(path_problems(controls_text, actions_text, plan_dir)))
check("no file under src/plan/ names callService", all("callService" not in code_of(t) for t in plan_dir.values()))
check("the plan call allow-list still reads script.turn_on on exactly the override start, the override cancel and a configured guarded start",
      "script.ecco_plan_override_start" in actions_text and "script.ecco_plan_override_cancel" in actions_text
      and "isGuardedStart" in actions_text and "button.press" not in code_of(actions_text))

# ===========================================================================
print("")
print("[4] mutation (each loss or added path is caught; the untouched tree is not flagged)")
# ===========================================================================
for name in PLACES:
    gone = dict(texts)
    gone[name] = texts[name].replace(LIMITATION, "")
    check(f"mutant caught: the sentence removed from {name}", bool(places_problems(gone)))
    soft = dict(texts)
    soft[name] = texts[name].replace("Partial protection only", "Protected")
    check(f"mutant caught: the heading words softened in {name}", bool(places_problems(soft)))
    twice = dict(texts)
    twice[name] = texts[name] + "\n" + LIMITATION
    check(f"mutant caught: the sentence doubled in {name}", bool(places_problems(twice)))
for name in PACKAGE_PLACES:
    live = dict(texts)
    live[name] = texts[name].replace("# STATED LIMITATION (release gate RG-ST3): " + LIMITATION, "limit: " + LIMITATION)
    check(f"mutant caught: the sentence moved out of a comment in {name}", bool(package_comment_problems(live)))
check("mutant caught: a click handler on the note", bool(visible_problems(controls_text.replace('role="note">${START_BUTTON_LIMITATION}', 'role="note" @click=${() => dispatch(x)}>${START_BUTTON_LIMITATION}'))))
check("mutant caught: the note moved below the scripts-missing branch",
      bool(visible_problems(re.sub(r"(      <p class=\"plan-reason plan-limitation\"[^\n]*\n)(      \$\{vm\.missingScripts\.length)", r"\2", controls_text).replace(
          "</div>\n  `;\n}\n\n/** The renderer", "<p class=\"plan-reason plan-limitation\" data-plan-limitation role=\"note\">${START_BUTTON_LIMITATION}</p></div>\n  `;\n}\n\n/** The renderer"))))
check("mutant caught: a callService in the controls", bool(path_problems(controls_text + "\nconst x = () => hass.callService('button', 'press', {});\n", actions_text, plan_dir)))
check("mutant caught: a third click handler in the controls", bool(path_problems(controls_text + "\n// @click=\nhtml`<b @click=${() => 1}></b>`;\n", actions_text, plan_dir)))
check("mutant caught: a button press in the plan allow-list", bool(path_problems(controls_text, actions_text.replace('c.service !== "turn_on"', 'c.service !== "press"'), plan_dir)))
check("mutant caught: a fourth plan control id", bool(path_problems(controls_text, actions_text.replace('"cancel_script": "script.ecco_plan_override_cancel"', '"cancel_script": "script.ecco_plan_override_cancel",\n  "start_button": "button.x"'), plan_dir)))
check("control: the untouched tree is not flagged", not places_problems(texts) and not package_comment_problems(texts) and not visible_problems(controls_text)
      and not path_problems(controls_text, actions_text, plan_dir))

# ===========================================================================
print("")
print("[5] the deployment manifest states the same limitation in one short sentence, on the guarded-start stanza, and its warnings stand on the schedule stanza")
# ===========================================================================
# The manifest is where an installer reads what a package needs and what it does not guarantee, so the unresolved limitation is stated there too, in
# one short ASCII sentence (no number, entity id, address or site value), on a comment line in the comment block directly above the guarded start's
# stanza. The manifest never calls the protection fully enforced. The scheduled Dump to Grid stanza carries the helper dependency (the plan helpers go in
# the SAME deployment, before the ONE full restart; until they are installed and Home Assistant has restarted fully every scheduled start is refused) and
# the active-override warning (while an override is active, the records cannot be read or the reserve is invalid, every scheduled and every guarded start
# is REFUSED, seen only at the start time). The ORDER of the copies does not matter (the deploy tool copies every package in the manifest, checks the
# configuration and restarts Home Assistant only when that is separately requested), so no stanza may say the plan helpers must be copied first; the
# three stanzas (plan helpers, scheduled start, guarded start) say the same thing.
MANIFEST = ROOT / "deployment" / "ha-manifest.yaml"
MANIFEST_LIMITATION = "The dongle's own Start button is not bound by these protections (unresolved; it needs a firmware gate, approved separately)."
GUARD_STANZA = "  - source: home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml"
SCHEDULE_STANZA = "  - source: home-assistant/packages/ecco_dump_to_grid_schedule.yaml"
HELPERS_STANZA = "  - source: home-assistant/packages/ecco_plan_helpers.yaml"
SCHEDULE_NOTES = ("FULL Home Assistant restart",                       # R9's note, kept
                  "ecco_plan_helpers.yaml", "OVERRIDE_UNREADABLE",     # the helper dependency (its same-deployment wording: DEPENDENCY_NOTES)
                  "Hold battery, Skip tonight or Prepare for power cut", "REFUSED", "blocked alert", "last-result text")   # the active-override warning
# What each of the three Stage 3 stanzas says about the helper package, as prose (comment markers dropped, lines joined, so a phrase may wrap).
DEPENDENCY_NOTES = {
    "scheduled-start": ("SAME deployment", "ONE full Home Assistant restart", "does not matter", "every scheduled start is refused", "every guarded start is refused"),
    "guarded-start": ("SAME deployment", "ONE full Home Assistant restart", "does not matter", "every guarded start is refused"),
    "plan helpers": ("SAME deployment", "ONE full Home Assistant restart", "does not matter"),
}
DEPENDENCY_STANZAS = {"scheduled-start": SCHEDULE_STANZA, "guarded-start": GUARD_STANZA, "plan helpers": HELPERS_STANZA}
COPY_ORDER_CLAIM = re.compile(r"plan helpers first|installed first|WITH or BEFORE|BEFORE the guarded|BEFORE the changed|copied first", re.I)
FULL_CLAIM = re.compile(r"fully[- ]enforc|full enforcement|fully[- ]protect|completely (?:enforc|protect)", re.I)


def block_above(lines: list[str], stanza: str) -> list[str]:
    """The comment lines directly above `stanza` (empty when the stanza is missing or not preceded by comments)."""
    if lines.count(stanza) != 1:
        return []
    j = lines.index(stanza)
    k = j
    while k > 0 and lines[k - 1].lstrip().startswith("#"):
        k -= 1
    return lines[k:j]


def dependency_problems(lines: list[str]) -> list[str]:
    """What each Stage 3 stanza says about the helper package: the same deployment, the one full restart, no copy-order claim."""
    out = []
    for name, stanza in DEPENDENCY_STANZAS.items():
        prose = " ".join(ln.lstrip().lstrip("#").strip() for ln in block_above(lines, stanza))
        lacking = [s for s in DEPENDENCY_NOTES[name] if s not in prose]
        if lacking:
            out.append(f"the {name} stanza's comment block lacks {lacking}")
        claim = COPY_ORDER_CLAIM.search(prose)
        if claim:
            out.append(f"the {name} stanza's comment block claims a copy order ({claim.group(0)!r})")
    return out


def manifest_problems(text: str) -> list[str]:
    out = []
    lines = text.split("\n")
    hits = [i for i, ln in enumerate(lines) if MANIFEST_LIMITATION in ln]
    if len(hits) != 1 or text.count(MANIFEST_LIMITATION) != 1:
        out.append(f"the limitation sentence stands {text.count(MANIFEST_LIMITATION)}x in {len(hits)} line(s), not exactly once")
    elif not lines[hits[0]].lstrip().startswith("#"):
        out.append("the limitation sentence is not on a comment line")
    elif lines[hits[0]] not in block_above(lines, GUARD_STANZA):
        out.append("the limitation sentence is not in the comment block directly above the guarded-start stanza")
    if FULL_CLAIM.search(text):
        out.append("the manifest claims full enforcement")
    above = "\n".join(block_above(lines, SCHEDULE_STANZA))
    missing = [s for s in SCHEDULE_NOTES if s not in above]
    if missing:
        out.append(f"the schedule stanza's comment block lacks {missing}")
    out.extend(dependency_problems(lines))
    return out


manifest_text = text_of(MANIFEST)
check("the manifest sentence is ASCII, one line, short, and spells no number, entity id, address or site value",
      MANIFEST_LIMITATION.isascii() and "\n" not in MANIFEST_LIMITATION and len(MANIFEST_LIMITATION) < 140
      and not re.search(r"\d|\b(?:sensor|switch|button|number|input_[a-z]+|script)\.|token|password", MANIFEST_LIMITATION, re.I))
check("the manifest exists and is readable", bool(manifest_text))
check("the manifest states the limitation exactly once, on a comment line directly above the guarded-start stanza; it never claims full enforcement; the schedule stanza "
      "carries the helper dependency, the active-override warning and R9's full-restart note", not manifest_problems(manifest_text), str(manifest_problems(manifest_text)))
check("the plan helpers, scheduled-start and guarded-start stanzas each say the plan helpers go in the SAME deployment, before the ONE full restart, that the order of "
      "the stanzas does not matter, and none claims a copy order", not dependency_problems(manifest_text.split("\n")), str(dependency_problems(manifest_text.split("\n"))))
check("the manifest names no entity id, address or site value in the notes above the two stanzas (comment lines only)",
      not re.search(r"\b(?:sensor|switch|button|number|input_[a-z]+|binary_sensor)\.[a-z_]+|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
                    "\n".join(block_above(manifest_text.split("\n"), GUARD_STANZA) + block_above(manifest_text.split("\n"), SCHEDULE_STANZA)), re.I))
_gone = manifest_text.replace(MANIFEST_LIMITATION, "")
check("mutant caught: the manifest sentence removed", bool(manifest_problems(_gone)))
check("mutant caught: the manifest sentence doubled", bool(manifest_problems(manifest_text + "\n# " + MANIFEST_LIMITATION)))
check("mutant caught: the manifest sentence softened", bool(manifest_problems(manifest_text.replace("is not bound by", "is bound by"))))
check("mutant caught: the manifest sentence moved above another stanza",
      bool(manifest_problems(manifest_text.replace("  # " + MANIFEST_LIMITATION + "\n", "").replace(SCHEDULE_STANZA, "  # " + MANIFEST_LIMITATION + "\n" + SCHEDULE_STANZA))))
check("mutant caught: the manifest sentence on a line that is not a comment",
      bool(manifest_problems(manifest_text.replace("# " + MANIFEST_LIMITATION, "note: " + MANIFEST_LIMITATION))))
check("mutant caught: the manifest claims the protection is fully enforced", bool(manifest_problems(manifest_text + "\n# The overrides are fully enforced.")))
check("mutant caught: the schedule stanza's helper dependency removed", bool(manifest_problems(manifest_text.replace("SAME deployment", "other deployment"))))


def caught(mutant: str) -> bool:
    """A mutant is caught when it really differs from the untouched manifest and the manifest check flags it."""
    return mutant != manifest_text and bool(manifest_problems(mutant))


check("mutant caught: the schedule stanza says the plan helpers go first again", caught(manifest_text.replace(SCHEDULE_STANZA, "  # Install the two together, the plan helpers first.\n" + SCHEDULE_STANZA)))
check("mutant caught: the plan helpers stanza says BEFORE the guarded start again", caught(manifest_text.replace("the SAME deployment as the guarded start below", "BEFORE the guarded start below", 1)))
check("mutant caught: the guarded-start stanza says installed first again", caught(manifest_text.replace("installed in the SAME deployment, before the ONE full", "installed first, before the ONE full", 1)))
check("mutant caught: the guarded-start stanza no longer says every guarded start is refused until the helpers are in",
      caught(manifest_text.replace("every guarded start\n  # is refused.", "every guarded start\n  # is allowed.", 1)))
check("mutant caught: the one-full-restart statement removed from the scheduled-start stanza", caught(manifest_text.replace("before the ONE full Home Assistant restart (the R9 note", "before the restart (the R9 note", 1)))
check("mutant caught: the order-does-not-matter sentence removed from the plan helpers stanza", caught(manifest_text.replace("(the order of the stanzas in this list does not matter): both", "): both", 1)))
_guard_header = texts["package header: ecco_dump_to_grid_guarded_start.yaml"]


def guard_header_problems(text: str) -> list[str]:
    head = " ".join(ln.lstrip().lstrip("#").strip() for ln in text.split("\n")[:8])
    out = []
    if "installed in the same deployment, before the one full Home Assistant restart" not in head:
        out.append("the header does not say the plan helpers go in the same deployment, before the one full restart")
    if "installed first" in text:
        out.append("the header says the plan helpers must be installed first")
    return out


check("the guarded start package header says the plan helpers go in the same deployment, before the one full restart, and claims no copy order",
      not guard_header_problems(_guard_header), str(guard_header_problems(_guard_header)))
check("mutant caught: the guarded start package header says installed first again",
      bool(guard_header_problems(_guard_header.replace("installed in the same deployment, before the one full Home Assistant restart", "installed first"))))
check("mutant caught: the schedule stanza's active-override warning removed", bool(manifest_problems(manifest_text.replace("last-result text", "result"))))
check("mutant caught: R9's full-restart note removed from the schedule stanza", bool(manifest_problems(manifest_text.replace("FULL Home Assistant restart", "restart"))))
check("control: the untouched manifest is not flagged", not manifest_problems(manifest_text))

# ===========================================================================
print("")
print("[6] the corrected wording (what an override does and does not do), no 'protected reserve', and the known limitations (finding 3 of the review of 18 Nov 2026)")
# ===========================================================================
# Finding 3 (MAJOR, over-claim): the card and the documents said that Prepare for power cut "raises a protected reserve (never lowers it)". That over-stated
# it. The raised reserve is the reserve ECCO's PLAN uses (the effective reserve sensor: the larger of the owner's reserve and a running power-cut reserve,
# each rounded up). The trusted backend refuses the scheduled Dump to Grid start and the card's guarded manual start when it cannot be read or is invalid, and
# raises the Stop SOC the scheduled start stages to at least that reserve; it does NOT change the inverter's own reserve or any inverter setting, does not
# stop the house using the battery, does not charge the battery and does not bind the dongle's own Start button. These checks are ADDITIVE: they require that
# wording at each place that carries it, forbid the old phrase, and require the "Known limitations" section of the plan-core README with all its items.
CARD_SRC_DIR = CARD / "src"
PLAN_HELPERS_PKG = ROOT / "home-assistant" / "packages" / "ecco_plan_helpers.yaml"
OVERRIDE_POLICY_TS = ROOT / "frontend" / "ecco-plan-core" / "src" / "overridePolicy.ts"
card_sources = {str(p.relative_to(CARD)).replace("\\", "/"): text_of(p) for p in sorted(CARD_SRC_DIR.rglob("*.ts"))}

PROTECTED_RE = re.compile(r"protected\s+(?:reserve|floor)", re.I)
INVERTER_RESERVE_RE = re.compile(r"(?:(?:does|do) not change the inverter's own reserve|the inverter's own reserve is not changed)", re.I)


def flat(text: str) -> str:
    """Prose view: every run of white space becomes one space, so a phrase may wrap across lines."""
    return re.sub(r"\s+", " ", text)


def flat_yaml(text: str) -> str:
    """Prose view of a YAML file's comments: the comment marker at the start of each line is dropped, then as flat()."""
    return flat(re.sub(r"(?m)^[ \t]*# ?", "", text))


# What the card says now (the source strings; the bundle carries them too). The effect text of Prepare for power cut has a number in the middle, so it is two parts.
CONTROLS_WORDING = (
    "Holds back ECCO's own scheduled and guarded export starts. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",
    "Holds back ECCO's own scheduled and guarded export starts tonight. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",
    "Sets the reserve ECCO's plan uses to the larger of your own reserve and the power-cut reserve, and holds back ECCO's own export starts. It does not change the inverter's own reserve and does not stop the house using the battery. It does not charge the battery.",
    "They hold back ECCO's own export starts and, for Prepare for power cut, set the reserve ECCO's plan uses. They do not change the inverter's own reserve or any inverter setting, do not stop the house using the battery and never charge it.",
)
PRESENT_WORDING = (
    "An override can only hold back ECCO's own export starts or raise the reserve ECCO's plan uses; it never writes the inverter's table, does not change the inverter's own reserve and never stops a running session.",
    "Intended: ECCO's own scheduled and guarded export starts are held; charging and the inverter table are untouched.",
    "Intended: ECCO's own export starts tonight are held; charging continues.",
    "Intended: the reserve ECCO's plan uses is ",
    " % or more, and ECCO's own export starts are held. The inverter's own reserve is not changed.",
)
CARD_README_WORDING = (
    "override holds back ECCO's own scheduled and guarded export starts; it does not stop the battery charging or discharging and it does not stop the dongle's own Start button.",
    "Prepare for power cut also sets the reserve ECCO's plan uses (the larger of your own reserve and the power-cut reserve, each rounded up). It does not change the inverter's own reserve or any inverter setting, does not stop the house using the battery, and never charges.",
    "\"Known limitations (stated, not fixed in this change)\"",
)
PLAN_CORE_README_WORDING = (
    "**What an override does, and does not do.**",
    "gate ECCO's own scheduled Dump to Grid start and the card's guarded manual start, and nothing else",
    "Prepare for power cut also sets the reserve ECCO's plan uses",
    "An override does NOT change the inverter's own reserve or any inverter setting, does NOT stop the house using the battery, does NOT stop the battery charging or discharging, does NOT charge the battery, and does NOT bind the dongle's own Start button",
    "Prepare for power cut sets the reserve ECCO's plan uses (the row above) and NEVER charges",
    "an unreadable input is skipped (the other value stands)",
)
PACKAGE_WORDING = (
    "It is the reserve ECCO's own plan uses, not an inverter setting.",
    "Prepare for power cut adds a running reserve to ECCO's plan",
    "it does not change the inverter's own reserve or any inverter setting, it does not stop the house using the battery, it does not stop the battery charging or discharging, it never starts a charge, and it does not bind the dongle's own Start button",
)

LIMITS_HEADING = "### Known limitations (stated, not fixed in this change)"
LIMIT_ITEMS = (   # (number, a phrase that must stand in the item's bold title, lower case)
    (1, "unreadable input falls back"), (2, "raise-only is compared"), (3, "start and cancel can interleave"), (4, "does not handle a failed press"),
    (5, "unguarded unless"), (6, "floored to the minute"), (7, "first-run seed marker"), (8, "owner_reserve"), (9, "0.0001"), (10, "clock-change day"),
    (11, "timestamp"), (12, "not atomic"),
    # beyond the twelve the review's list names: smaller or informational items
    (13, "input shapes"), (14, "discretionary"), (15, "already staged"), (16, "confirmation switch"), (17, "modelled, not live-proven"), (18, "site mapping"),
    # the second review of the fixes (18 Nov 2026): a restart inside the repeated hour, the overwritten BLOCKED text, a momentary unreadable sensor, the leftover staging
    (19, "repeated hour"), (20, "overwritten"), (21, "momentary"), (22, "leftover staging"),
)
DIRECTION_RE = re.compile(r"Direction: (?:fail open|fail closed|either way|neutral|informational|unknown|believed fail closed|not applicable|your limits)")


def card_text_places() -> dict[str, str]:
    """The places that carry the corrected card wording (by name), as read now."""
    return {
        "card controls (source)": text_of(CARD / "src" / "plan" / "controls.ts"),
        "card plan view (source)": text_of(CARD / "src" / "plan" / "present.ts"),
        "card bundle": text_of(CARD / "dist" / "ecco-energy-actions-card.js"),
        "card README": text_of(CARD / "README.md"),
        "plan-core README": text_of(ROOT / "frontend" / "ecco-plan-core" / "README.md"),
        "package: ecco_plan_helpers.yaml": text_of(PLAN_HELPERS_PKG),
    }


def wording_problems(t: dict[str, str]) -> list[str]:
    """The corrected wording at every place that carries it, and the inverter's-own-reserve statement in the card text and both READMEs."""
    out = []
    for name in ("card controls (source)", "card bundle"):
        for phrase in CONTROLS_WORDING:
            if phrase not in flat(t.get(name, "")):
                out.append(f"{name} lacks: {phrase[:70]}")
    for name in ("card plan view (source)", "card bundle"):
        for phrase in PRESENT_WORDING:
            if phrase not in flat(t.get(name, "")):
                out.append(f"{name} lacks: {phrase[:70]}")
    for phrase in CARD_README_WORDING:
        if phrase not in flat(t.get("card README", "")):
            out.append(f"card README lacks: {phrase[:70]}")
    for phrase in PLAN_CORE_README_WORDING:
        if phrase not in flat(t.get("plan-core README", "")):
            out.append(f"plan-core README lacks: {phrase[:70]}")
    for phrase in PACKAGE_WORDING:
        if phrase not in flat_yaml(t.get("package: ecco_plan_helpers.yaml", "")):
            out.append(f"plan helper package lacks: {phrase[:70]}")
    for name in ("card controls (source)", "card bundle", "card README", "plan-core README"):
        if not INVERTER_RESERVE_RE.search(flat(t.get(name, ""))):
            out.append(f"{name} does not say that an override does not change the inverter's own reserve")
    return out


def old_phrase_problems(t: dict[str, str]) -> list[str]:
    """'protected reserve' (any case) must not stand in the card sources, the bundle, both READMEs or the plan helper package."""
    return [name for name, text in t.items() if PROTECTED_RE.search(text)]


def never_charges_problems(t: dict[str, str]) -> list[str]:
    """The statements that an override never charges are still there (kept on purpose)."""
    want = {
        "card controls (source)": ("It does not charge the battery.",),
        "card README": ("never charges",),
        "plan-core README": ("NEVER charges",),
        "package: ecco_plan_helpers.yaml": ("it never starts a charge",),
    }
    out = []
    for name, phrases in want.items():
        body = flat_yaml(t.get(name, "")) if name.startswith("package") else flat(t.get(name, ""))
        out.extend(f"{name} lost: {p}" for p in phrases if p not in body)
    return out


def limitations_problems(readme: str) -> list[str]:
    """The Known limitations section of the plan-core README: present once, all its items numbered in order, each naming its subject, its direction of failure and what you would see."""
    n = readme.count(LIMITS_HEADING)
    if n != 1:
        return [f"the heading stands {n}x"]
    start = readme.index(LIMITS_HEADING) + len(LIMITS_HEADING)
    nxt = re.search(r"(?m)^#{2,3} ", readme[start:])
    section = readme[start:start + nxt.start()] if nxt else readme[start:]
    heads = [(int(num), title) for num, title in re.findall(r"(?m)^(\d+)\. \*\*(.+?)\*\*", section)]
    out = []
    if [num for num, _ in heads] != [num for num, _ in LIMIT_ITEMS]:
        out.append(f"the numbered items are {[num for num, _ in heads]}, not 1..{len(LIMIT_ITEMS)}")
        return out
    bodies = re.split(r"(?m)^(?=\d+\. \*\*)", section)[1:]
    for (num, phrase), (_, title), body in zip(LIMIT_ITEMS, heads, bodies):
        if phrase not in title.lower():
            out.append(f"item {num} does not name '{phrase}' in its title")
        if not DIRECTION_RE.search(flat(body)):
            out.append(f"item {num} states no direction of failure")
        if "You would see:" not in flat(body):
            out.append(f"item {num} does not say what you would see")
    return out


w6 = card_text_places()
scope_texts = dict(w6)
scope_texts.update({f"card {k}": v for k, v in card_sources.items()})   # every card source file, by name
scope_texts["package: ecco_dump_to_grid_guarded_start.yaml"] = texts["package header: ecco_dump_to_grid_guarded_start.yaml"]

check("the corrected wording stands at each place that carries it: the card blurbs and Quick overrides note, the plan view's effect and status texts (source and bundle), "
      "the card README, the plan-core README and the plan helper package comments", not wording_problems(w6), str(wording_problems(w6)))
check("'protected reserve' (any case) is absent from every card source file, the card bundle, both READMEs and the plan helper package (and the guarded start package)",
      not old_phrase_problems(scope_texts), str(old_phrase_problems(scope_texts)))
check("the card sources are read (the scan is not vacuous)", len(card_sources) >= 15 and "src/plan/controls.ts" in card_sources, str(sorted(card_sources)[:3]))
check("it is said, in the card text and in the plan-core README, that an override does not change the inverter's own reserve",
      all(INVERTER_RESERVE_RE.search(flat(w6[n])) for n in ("card controls (source)", "card bundle", "plan-core README")))
check("the statements that an override never charges are still there (card text, card README, plan-core README, package)", not never_charges_problems(w6), str(never_charges_problems(w6)))
def refusal_text_problems(policy_ts: str, package_yaml: str) -> list[str]:
    """The refusal text 'an override never lowers a reserve' stays, unchanged, in the validator and in the plan helper package (it is true there; the suites compare the two)."""
    return [n for n, t in (("overridePolicy.ts", policy_ts), ("ecco_plan_helpers.yaml", package_yaml)) if "an override never lowers a reserve" not in t]


check("the refusal text 'an override never lowers a reserve' is unchanged in the validator and in the plan helper package (true there; the suites compare the two)",
      not refusal_text_problems(text_of(OVERRIDE_POLICY_TS), w6["package: ecco_plan_helpers.yaml"]), str(refusal_text_problems(text_of(OVERRIDE_POLICY_TS), w6["package: ecco_plan_helpers.yaml"])))
check("nothing claims the overrides are fully enforced (the card sources, the bundle, both READMEs, the package comments)",
      not [n for n, v in scope_texts.items() if FULL_CLAIM.search(v)], str([n for n, v in scope_texts.items() if FULL_CLAIM.search(v)]))
check("the Stage 3 limitation sentence is still in every place it was, exactly once (the new section and the new wording did not add or remove a copy)",
      not places_problems(texts) and not package_comment_problems(texts) and not visible_problems(controls_text))
check("the plan-core README has the 'Known limitations (stated, not fixed in this change)' section: twenty-two numbered items (the review's twelve first, six smaller ones, the four of the second review), each with its direction "
      "of failure and what you would see", not limitations_problems(w6["plan-core README"]), str(limitations_problems(w6["plan-core README"])))
check("the card README points to that section (a one-line pointer)", "Known limitations (stated, not fixed in this change)" in flat(w6["card README"]))

# ---- mutants: each way of losing the corrected wording, re-introducing the old phrase or losing the section is caught; the untouched tree is not flagged ----
for name in ("card controls (source)", "card plan view (source)", "card bundle", "card README", "plan-core README", "package: ecco_plan_helpers.yaml"):
    bad = dict(w6)
    bad[name] = w6[name] + "\nRaises a protected reserve (never lowers it).\n"
    sc = dict(scope_texts)
    sc[name] = bad[name]
    check(f"mutant caught: 'raises a protected reserve' back in {name}", bool(old_phrase_problems(sc)))
    sc[name] = w6[name] + "\nThe Protected\n  Reserve is raised.\n"
    check(f"mutant caught: 'Protected Reserve' (case and a line wrap) back in {name}", bool(old_phrase_problems(sc)))
_old_prepare = "Raises a protected reserve (never lowers it) and holds exports. It does not charge the battery."
_new_prepare = CONTROLS_WORDING[2]
check("mutant caught: the old Prepare for power cut blurb restored in the card source", bool(wording_problems({**w6, "card controls (source)": w6["card controls (source)"].replace(_new_prepare, _old_prepare)})))
check("mutant caught: the old Prepare for power cut blurb restored in the bundle", bool(wording_problems({**w6, "card bundle": w6["card bundle"].replace(_new_prepare, _old_prepare)})))
check("mutant caught: the old effect text 'the reserve is raised to ... (never lowered)' restored in the plan view",
      bool(wording_problems({**w6, "card plan view (source)": w6["card plan view (source)"].replace(PRESENT_WORDING[3], "Intended: the reserve is raised to ").replace(PRESENT_WORDING[4], " % (never lowered) and export starts are held.")})))
check("mutant caught: 'It does not charge the battery.' dropped from the card source", bool(never_charges_problems({**w6, "card controls (source)": w6["card controls (source)"].replace("It does not charge the battery.", "")})))
check("mutant caught: 'NEVER charges' dropped from the plan-core README", bool(never_charges_problems({**w6, "plan-core README": w6["plan-core README"].replace("NEVER charges", "charges")})))
check("mutant caught: the inverter's-own-reserve statement dropped from the card source",
      bool(wording_problems({**w6, "card controls (source)": w6["card controls (source)"].replace("does not change the inverter's own reserve", "keeps the reserve")})))
check("mutant caught: the inverter's-own-reserve statement dropped from the plan-core README",
      bool(wording_problems({**w6, "plan-core README": re.sub(r"does NOT change the\s+inverter's own reserve", "keeps the reserve", w6["plan-core README"])})))
check("mutant caught: the card README pointer to the limitations section removed",
      bool(wording_problems({**w6, "card README": w6["card README"].replace("Known limitations (stated, not fixed in this change)", "Known limits")})))
check("mutant caught: the package comment's 'does not bind the dongle's own Start button' dropped",
      bool(wording_problems({**w6, "package: ecco_plan_helpers.yaml": w6["package: ecco_plan_helpers.yaml"].replace("it does not bind the dongle's own Start button", "it binds the Start button")})))
check("mutant caught: the overrides called fully enforced in the card source", bool(FULL_CLAIM.search(w6["card controls (source)"] + "\n// The overrides are fully enforced.")))
check("mutant caught: the refusal text reworded in the validator", bool(refusal_text_problems(text_of(OVERRIDE_POLICY_TS).replace("an override never lowers a reserve", "an override keeps a reserve"), w6["package: ecco_plan_helpers.yaml"])))
check("mutant caught: the refusal text reworded in the plan helper package", bool(refusal_text_problems(text_of(OVERRIDE_POLICY_TS), w6["package: ecco_plan_helpers.yaml"].replace("an override never lowers a reserve", "an override keeps a reserve"))))
check("mutant caught: the Stage 3 limitation sentence removed from the new section's neighbourhood (the plan-core README)",
      bool(places_problems({**texts, "plan-core README": texts["plan-core README"].replace(LIMITATION, "")})))
check("mutant caught: the Stage 3 limitation sentence doubled by a copy in the Known limitations section",
      bool(places_problems({**texts, "plan-core README": texts["plan-core README"].replace(LIMITS_HEADING, LIMITS_HEADING + "\n\n" + LIMITATION)})))
_lim = w6["plan-core README"]
check("mutant caught: the Known limitations heading removed", bool(limitations_problems(_lim.replace(LIMITS_HEADING, "### Notes"))))
check("mutant caught: the Known limitations heading doubled", bool(limitations_problems(_lim + "\n" + LIMITS_HEADING + "\n")))
_h = _lim.find(LIMITS_HEADING)
_sec_end = _lim.find("\n### ", _h + 1) if _h >= 0 else -1
_built = 0
for num, phrase in LIMIT_ITEMS[:-1]:   # remove item `num` from inside the section (other numbered lists of the README are left alone)
    _a, _b = _lim.find(f"\n{num}. **", _h, _sec_end), _lim.find(f"\n{num + 1}. **", _h, _sec_end)
    if _h >= 0 and 0 <= _a < _b:
        _built += 1
        check(f"mutant caught: limitation item {num} ('{phrase}') removed", bool(limitations_problems(_lim[:_a] + _lim[_b:])))
_last = _lim.find(f"\n{len(LIMIT_ITEMS)}. **", _h, _sec_end)
check("mutant caught: the last limitation item removed", _h >= 0 and 0 <= _last < _sec_end and bool(limitations_problems(_lim[:_last] + "\n" + _lim[_sec_end:])))
check("the limitation-item mutants were all built (one per item but the last)", _built == len(LIMIT_ITEMS) - 1, f"{_built} built")
check("mutant caught: an item's direction of failure removed", bool(limitations_problems(_lim.replace("Direction: fail open for that one number", "Note: for that one number"))))
check("mutant caught: an item's 'You would see' removed", bool(limitations_problems(_lim.replace("You would see: a stale last result and no start.", "Nothing else."))))
check("mutant caught: an item's subject reworded (the schedule packages' clock-change reads)", bool(limitations_problems(_lim.replace("clock-change day", "clock change"))))
check("mutant caught: the items renumbered", bool(limitations_problems(_lim.replace("\n7. **The first-run", "\n8. **The first-run"))))
check("control: the untouched tree is not flagged by the new checks", not wording_problems(w6) and not old_phrase_problems(scope_texts) and not never_charges_problems(w6) and not limitations_problems(_lim))

# ===========================================================================
print("")
print("[7] the second independent review of the fixes (18 Nov 2026; additive): the limitation items say what was shown, and the caveats stand in the comments and the CHANGELOG")
# ===========================================================================
# The first version of known limitations 9 and 10 was written from a task text and not run. Item 9 (a reserve in (0, 0.0001)) was run against the current packages and simulators and
# is NOT a failure there; item 10 (the schedule packages' start-time reads on the clock-change day) was only read. Both now say so. Four items are new: 19 (a restart inside the repeated
# hour may restore an expiry an hour early: recalled from Home Assistant core, not verified, not modelled), 20 (a press-time BLOCKED text overwritten with STARTED OK when Dump to Grid is
# active as the loop ends; FIXED on 19 Nov 2026 by owner decision r14, see [8]), 21 (a momentarily unreadable sensor at press time costs that night's export) and 22 (the leftover staging). The checks below require the status wording of those
# items, the four new items by name (LIMIT_ITEMS above, never fewer than before), and the caveats in the helper package comment, the schedule package header and the CHANGELOG; each is shown
# to fail without it.
SCHEDULE_PKG = ROOT / "home-assistant" / "packages" / "ecco_dump_to_grid_schedule.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
ITEM_STATUS = {   # item number -> phrases its body must carry (what was reproduced, what was only reasoned or recalled, what was not examined)
    9: ("NOT reproduced", "Run now against the current packages and simulators", "Reasoned, not examined"),
    10: ("Shown by reading", "Not examined: what those reads give", "not reproduced and is not claimed"),
    11: ("modelled, not live-proven", "stricter than the earlier state-string read"),
    19: ("recalled", "not verified here", "NOT said to be preserved across a restart", "open owner decision", "supervised check"),
    20: ("FIXED on 19 Nov 2026 (owner decision r14)", "is never overwritten", "the schedule notifications are not dismissed", "Dump to Grid is active now",
         "this run did not start it", "test_ecco_plan_enforcement.py` [12]", "still not bound by any override (RG-ST3)", "STARTING, FAILED or CANCELLED", "Not examined: how real Home Assistant renders the notice"),
    21: ("Reproduced offline", "not examined: whether and for how long a real template reload", "lost until the owner arms the schedule again", "every attempt, the first included"),
    22: ("Reproduced offline", "not examined on a dongle", "no step that restores the earlier values"),
}
SCHEDULE_HEADER_WORDING = (
    "Fixed 19 Nov 2026 (owner decision r14: a refusal stays a refusal)",
    "a result that starts with BLOCKED is never replaced by",
    "the schedule notifications are not dismissed",
    "that Dump to Grid is active now and that this run did not start it",
    "which no override binds (RG-ST3)",
    "A STARTING, FAILED or CANCELLED result keeps the rule it had",
    "It runs on EVERY attempt, the first included",
    "momentarily unknown or unavailable at that moment",
    "that night's scheduled export is lost until the owner arms it again",
    "The staging of that attempt stays on the dongle",
    "the steps after the loop still run",
    "This script presses nothing in that case",
)
HELPER_COMMENT_WORDING = (
    "NOT PROVEN, and not claimed",
    "stays so across a restart",
    "restores that expiry 60 minutes early",
    "an open owner decision and an item for the supervised check",
)
CHANGELOG_WORDING = (
    "stricter than before when the attribute is missing",
    "Residual, not fixed and not proven in real Home Assistant",
    "The attribute is not claimed to be preserved across a restart",
)
OLD_WORDING = (   # the sentences that over-claimed: they must not stand
    ("the plan helper package comment", "which is the true instant"),
    ("the CHANGELOG", "exactly as an unparseable state was"),
    ("the CHANGELOG", "(the true instant) instead of parsing"),
    ("the CHANGELOG", "late and never early"),
)


def item_bodies(readme: str) -> dict[int, str]:
    """The Known limitations items of the plan-core README as {number: flat text}; empty when the section is not there exactly once."""
    if readme.count(LIMITS_HEADING) != 1:
        return {}
    start = readme.index(LIMITS_HEADING) + len(LIMITS_HEADING)
    nxt = re.search(r"(?m)^#{2,3} ", readme[start:])
    section = readme[start:start + nxt.start()] if nxt else readme[start:]
    out: dict[int, str] = {}
    for part in re.split(r"(?m)^(?=\d+\. \*\*)", section)[1:]:
        out[int(re.match(r"(\d+)\.", part).group(1))] = flat(part)
    return out


def status_problems(readme: str) -> list[str]:
    bodies = item_bodies(readme)
    out = []
    for num, phrases in ITEM_STATUS.items():
        body = bodies.get(num, "")
        out.extend(f"item {num} lacks: {p}" for p in phrases if p not in body)
    return out


def comment_problems(helper_text: str, schedule_text: str, changelog: str) -> list[str]:
    out = []
    fh, fs, fc = flat_yaml(helper_text), flat_yaml(schedule_text), flat(changelog)
    out.extend(f"the plan helper package comment lacks: {p}" for p in HELPER_COMMENT_WORDING if p not in fh)
    out.extend(f"the schedule package header lacks: {p}" for p in SCHEDULE_HEADER_WORDING if p not in fs)
    out.extend(f"the CHANGELOG lacks: {p}" for p in CHANGELOG_WORDING if p not in fc)
    for where, phrase in OLD_WORDING:
        body = {"the plan helper package comment": fh, "the CHANGELOG": fc}[where]
        if phrase in body:
            out.append(f"{where} still says: {phrase}")
    return out


def drop_phrase(text: str, phrase: str) -> str:
    """`text` with every occurrence of `phrase` replaced by 'REMOVED' (whitespace in the phrase may match a line wrap); asserts that it was there."""
    pat = r"\s+".join(re.escape(w) for w in phrase.split())
    new, n = re.subn(pat, "REMOVED", text)
    assert n >= 1, phrase
    return new


def drop_in_item(readme: str, num: int, phrase: str) -> str:
    """The README with every occurrence of `phrase` removed from limitation item `num` only (the other items are left alone)."""
    h = readme.index(LIMITS_HEADING)
    a = readme.index(f"\n{num}. **", h)
    b = readme.find(f"\n{num + 1}. **", a)
    if b < 0:
        b = readme.find("\n### ", a)
    return readme[:a] + drop_phrase(readme[a:b], phrase) + readme[b:]


s2_helper, s2_schedule, s2_changelog = text_of(PLAN_HELPERS_PKG), text_of(SCHEDULE_PKG), text_of(CHANGELOG)
s2_readme = w6["plan-core README"]
check("the limitation items say what was shown: 9 (not reproduced, run now, the rest only reasoned), 10 (read, not examined), 11, and the new 19 to 22 (recalled or reproduced offline, and what was "
      "not examined)", not status_problems(s2_readme), str(status_problems(s2_readme)))
check("the plan-core README has the four items of the second review (19 restart in the repeated hour, 20 overwritten BLOCKED text, 21 momentary unreadable sensor, 22 leftover staging) "
      "after the earlier eighteen, none removed", [n for n, _ in LIMIT_ITEMS] == list(range(1, 23)) and [p for n, p in LIMIT_ITEMS if n >= 19] == ["repeated hour", "overwritten", "momentary", "leftover staging"]
      and not limitations_problems(s2_readme), str(limitations_problems(s2_readme)))
check("the caveats stand: the plan helper package comment says the timestamp attribute is NOT proven and not claimed across a restart (the open decision), the schedule package header says "
      "what the press-time recheck costs and the STARTED OK overwrite, and the CHANGELOG says stricter-when-missing and the residual; the over-claiming sentences are gone",
      not comment_problems(s2_helper, s2_schedule, s2_changelog), str(comment_problems(s2_helper, s2_schedule, s2_changelog)))
_s2_items = " ".join(item_bodies(s2_readme).values())
check("the limitation items name no address, token or site value, and neither they nor the two package comments claim anything fully enforced",
      bool(_s2_items) and not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|token|password|key=", _s2_items, re.I)
      and not FULL_CLAIM.search(_s2_items + " " + flat_yaml(s2_helper) + " " + flat_yaml(s2_schedule)))

# ---- mutants: each lost or softened statement is caught; the untouched tree is not flagged ----
_cut = s2_readme.find("\n19. **", s2_readme.find(LIMITS_HEADING))
_end = s2_readme.find("\n### ", _cut)
check("mutant caught: the four items of the second review removed (the README back to eighteen items)", _cut > 0 and _end > _cut and bool(limitations_problems(s2_readme[:_cut] + "\n" + s2_readme[_end:])))
check("mutant caught: item 9 worded as a fact again ('reads as unreadable', starts refused)",
      bool(status_problems(s2_readme.replace("a failure was suspected and was NOT reproduced", "renders in exponent form and reads as unreadable"))))
check("mutant caught: item 10 worded as reasoned again", bool(status_problems(drop_in_item(s2_readme, 10, "Not examined: what those reads give"))))
for num, phrases in ITEM_STATUS.items():
    for ph in phrases:
        check(f"mutant caught: item {num} loses '{ph[:48]}'", bool(status_problems(drop_in_item(s2_readme, num, ph))))
for ph in HELPER_COMMENT_WORDING:   # a comment phrase may wrap across lines behind the comment marker: the prose view (marker dropped) is mutated, and the same function reads it
    check(f"mutant caught: the plan helper package comment loses '{ph[:48]}'", bool(comment_problems(drop_phrase(flat_yaml(s2_helper), ph), s2_schedule, s2_changelog)))
for ph in SCHEDULE_HEADER_WORDING:
    check(f"mutant caught: the schedule package header loses '{ph[:48]}'", bool(comment_problems(s2_helper, drop_phrase(flat_yaml(s2_schedule), ph), s2_changelog)))
for ph in CHANGELOG_WORDING:
    check(f"mutant caught: the CHANGELOG loses '{ph[:48]}'", bool(comment_problems(s2_helper, s2_schedule, drop_phrase(s2_changelog, ph))))
for where, phrase in OLD_WORDING:
    bad_h, bad_c = (s2_helper + "\n# which is the true instant\n", s2_changelog) if where.startswith("the plan helper") else (s2_helper, s2_changelog + "\n" + phrase + "\n")
    check(f"mutant caught: {where} says again '{phrase}'", bool(comment_problems(bad_h, s2_schedule, bad_c)))
check("control: the untouched tree is not flagged by the second-review checks",
      not status_problems(s2_readme) and not comment_problems(s2_helper, s2_schedule, s2_changelog) and not limitations_problems(s2_readme))

# ===========================================================================
print("")
print("[8] known limitation 20 is FIXED (owner decision r14, 19 Nov 2026; additive): the new wording stands, the old wording is gone, RG-ST3 and the 22 items stay")
# ===========================================================================
# The press-time BLOCKED text is no longer overwritten with STARTED OK when Dump to Grid is active (running proof: test_ecco_plan_enforcement.py [12]). Item 20 stays in the list (with what was
# done), the schedule package header and the CHANGELOG say so, and what is still true is stated: the dongle's own Start button is not bound by any override (RG-ST3), this change reports an
# active Dump to Grid and does not stop it, and a STARTING, FAILED or CANCELLED result keeps its old rule. These checks are ADDITIVE to [6] and [7]: they require the new wording, forbid the old
# wording where it described the current behaviour, re-require the Stage 3 limitation sentence and the 22 items, and forbid any 'fully enforced' claim.
OLD20_ITEM = ("only the record of the reason is lost", "pins today's behaviour", "the reason is lost from the record", "it documents the limitation and does not approve it")
OLD20_HEADER = ("unless Dump to Grid is found active when the loop ends, in which case the result text reads STARTED OK", "only the record of the reason is lost",
                "the end-of-run alert is skipped and the schedule notifications are dismissed", "A limit, not fixed: this BLOCKED text")
ALERT_SENTENCE = "Dump to Grid is active now, and this run did not start it (it may have been started from the dongle's own Start button or by hand). Check it, and the plan overrides, before assuming it is held."
CHANGELOG20 = ("a press-time BLOCKED result stays BLOCKED", "known limitation 20", "owner decision r14", "STARTING, FAILED and CANCELLED results keep their old rule",
               "the dongle's own Start button, still not bound (RG-ST3)")


def code_lines(text: str) -> str:
    """The package text without comment lines (a comment is not what Home Assistant runs)."""
    return "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))


def bullet20(changelog: str) -> str:
    """The CHANGELOG bullet about limitation 20 (up to the next bullet); empty when it is not there."""
    a = changelog.find("- **Stage 3: a press-time BLOCKED result stays BLOCKED")
    b = changelog.find("\n- **", a + 1) if a >= 0 else -1
    return changelog[a:b] if a >= 0 and b > a else ""


def fixed20_problems(readme: str, schedule: str, changelog: str) -> list[str]:
    out = []
    item = item_bodies(readme).get(20, "")
    fs, fc = flat_yaml(schedule), flat(bullet20(changelog))
    out.extend(f"item 20 still says: {p}" for p in OLD20_ITEM if p in item)
    out.extend(f"the schedule package header still says: {p}" for p in OLD20_HEADER if p in fs)
    if "(RG-ST3)" not in item or "not bound" not in item:
        out.append("item 20 no longer says that the dongle's own Start button is not bound (RG-ST3)")
    if "which no override binds (RG-ST3)" not in fs:
        out.append("the schedule package header no longer says that no override binds the dongle's own Start button (RG-ST3)")
    out.extend(f"the CHANGELOG lacks: {p}" for p in CHANGELOG20 if p not in fc)
    code = code_lines(schedule)
    if flat(code).count(ALERT_SENTENCE) != 1:
        out.append(f"the alert sentence stands {flat(code).count(ALERT_SENTENCE)}x in the package (not in a comment)")
    if code.count("and not r.startswith('BLOCKED') }}") < 1:
        out.append("the overwrite step does not exclude a BLOCKED result")
    if FULL_CLAIM.search(item + " " + fs + " " + schedule + " " + fc):
        out.append("a 'fully enforced' claim stands in item 20, the package or the CHANGELOG")
    return out


f8_readme, f8_schedule, f8_changelog = s2_readme, s2_schedule, s2_changelog
check("limitation 20 is fixed in the words of item 20, the schedule package header (and its alert sentence in the code) and the CHANGELOG; the old wording is gone from item 20 and the header; item 20 and the "
      "header still say the dongle's own Start button is not bound (RG-ST3); no 'fully enforced' claim", not fixed20_problems(f8_readme, f8_schedule, f8_changelog), str(fixed20_problems(f8_readme, f8_schedule, f8_changelog)))
check("the 22 numbered items are all still listed, item 20 among them (nothing was removed because it was fixed)", [n for n, _ in LIMIT_ITEMS] == list(range(1, 23)) and not limitations_problems(f8_readme)
      and 20 in item_bodies(f8_readme), str(limitations_problems(f8_readme)))
check("the Stage 3 limitation sentence (RG-ST3) is still in every place it was, exactly once", not places_problems(texts) and not package_comment_problems(texts) and not visible_problems(controls_text))
check("the 'Known limitations' introduction says item 20 was fixed and that the other items were not", "except item 20" in flat(f8_readme) and "NOT fixed" in flat(f8_readme))

# ---- mutants: each lost or softened statement is caught; the untouched tree is not flagged ----
for ph in ITEM_STATUS[20]:
    check(f"mutant caught: item 20 loses '{ph[:48]}'", bool(status_problems(drop_in_item(s2_readme, 20, ph))))
check("mutant caught: item 20 worded as the limitation again (only the record of the reason is lost)",
      bool(fixed20_problems(f8_readme.replace("Not examined: how real Home Assistant renders the notice.", "Not examined: how real Home Assistant renders the notice; only the record of the reason is lost."), f8_schedule, f8_changelog)))
check("mutant caught: item 20 worded as a documented, not approved pin again",
      bool(fixed20_problems(f8_readme.replace("it replaces the pin of the old behaviour that stood in [11]", "it documents the limitation and does not approve it"), f8_schedule, f8_changelog)))
check("mutant caught: the old 'A limit, not fixed' bullet restored in the schedule package header", bool(fixed20_problems(f8_readme, f8_schedule.replace("#   - Fixed 19 Nov 2026 (owner decision r14: a refusal stays a refusal): this BLOCKED text", "#   - A limit, not fixed: this BLOCKED text"), f8_changelog)))
check("mutant caught: the old 'unless Dump to Grid is found active ... STARTED OK' sentence restored in the schedule package header",
      bool(fixed20_problems(f8_readme, f8_schedule.replace("raises the notification, also when Dump to Grid is found active when\n# the loop ends (see the last point below).",
                                                           "raises the notification, unless Dump to Grid is found active when\n# the loop ends, in which case the result text reads STARTED OK (see the last point below)."), f8_changelog)))
check("mutant caught: the alert sentence removed from the package code", bool(fixed20_problems(f8_readme, f8_schedule.replace(ALERT_SENTENCE.split(" (it may")[0], "Dump to Grid is running"), f8_changelog)))
check("mutant caught: the alert sentence only in a comment, not in the package code",
      bool(fixed20_problems(f8_readme, f8_schedule.replace("\n                Dump to Grid is active now, and this run did not start it", "\n                # Dump to Grid is active now, and this run did not start it"), f8_changelog)))
check("mutant caught: the overwrite step no longer excludes a BLOCKED result (the old condition)", bool(fixed20_problems(f8_readme, f8_schedule.replace("and not r.startswith('BLOCKED') }}", "}}"), f8_changelog)))
check("mutant caught: item 20 loses the RG-ST3 statement", bool(fixed20_problems(f8_readme.replace("still not bound by any override (RG-ST3)", "still open"), f8_schedule, f8_changelog)))
check("mutant caught: the schedule package header loses the RG-ST3 statement", bool(fixed20_problems(f8_readme, f8_schedule.replace("which no override binds (RG-ST3)", "which nothing binds"), f8_changelog)))
check("mutant caught: the CHANGELOG bullet removed", bool(fixed20_problems(f8_readme, f8_schedule, drop_phrase(f8_changelog, "a press-time BLOCKED result stays BLOCKED"))))
check("mutant caught: the CHANGELOG bullet loses the limitation 20 reference", bool(fixed20_problems(f8_readme, f8_schedule, drop_phrase(f8_changelog, "known limitation 20"))))
check("mutant caught: item 20 claims the overrides are fully enforced", bool(fixed20_problems(f8_readme.replace("**A press-time BLOCKED result was", "**Fully enforced: a press-time BLOCKED result was"), f8_schedule, f8_changelog)))
check("mutant caught: the CHANGELOG bullet claims the overrides are fully enforced",
      bool(fixed20_problems(f8_readme, f8_schedule, f8_changelog.replace("(owner decision r14, 19 Nov 2026; known limitation 20 fixed;", "(fully enforced; owner decision r14, 19 Nov 2026; known limitation 20 fixed;"))))
check("mutant caught: the schedule package header claims full enforcement", bool(fixed20_problems(f8_readme, f8_schedule + "\n# The overrides are fully enforced.\n", f8_changelog)))
check("mutant caught: a copy of the Stage 3 limitation sentence added to the Known limitations item 20 (the sentence must stand once)",
      bool(places_problems({**texts, "plan-core README": texts["plan-core README"].replace("20. **A press-time BLOCKED result was", "20. " + LIMITATION + " **A press-time BLOCKED result was")})))
_h8 = f8_readme.index(LIMITS_HEADING)
check("mutant caught: item 20 removed (21 items)", bool(limitations_problems(f8_readme[:f8_readme.index("\n20. **", _h8)] + f8_readme[f8_readme.index("\n21. **", _h8):])))
check("control: the untouched tree is not flagged by the item 20 checks", not fixed20_problems(f8_readme, f8_schedule, f8_changelog) and not status_problems(f8_readme) and not comment_problems(s2_helper, s2_schedule, s2_changelog))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All Stage 3 limitation static tests PASSED.")
print("NOTE: a static check that the limitation is stated and that no path was added; the overrides stay a PARTIAL protection (release gate RG-ST3).")
