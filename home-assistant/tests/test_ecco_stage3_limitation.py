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
                the scheduled Dump to Grid stanza carries the helper dependency and the active-override warning beside R9's full-restart note

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
# stanza. The manifest never calls the protection fully enforced. The scheduled Dump to Grid stanza carries the helper dependency (install the plan
# helpers WITH or BEFORE it, one full restart; until they exist every scheduled start is refused) and the active-override warning (while an override
# is active, the records cannot be read or the reserve is invalid, every scheduled and every guarded start is REFUSED, seen only at the start time).
MANIFEST = ROOT / "deployment" / "ha-manifest.yaml"
MANIFEST_LIMITATION = "The dongle's own Start button is not bound by these protections (unresolved; it needs a firmware gate, approved separately)."
GUARD_STANZA = "  - source: home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml"
SCHEDULE_STANZA = "  - source: home-assistant/packages/ecco_dump_to_grid_schedule.yaml"
SCHEDULE_NOTES = ("FULL Home Assistant restart",                       # R9's note, kept
                  "ecco_plan_helpers.yaml", "WITH or BEFORE", "the plan helpers first", "OVERRIDE_UNREADABLE",   # the helper dependency
                  "Hold battery, Skip tonight or Prepare for power cut", "REFUSED", "blocked alert", "last-result text")   # the active-override warning
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
    return out


manifest_text = text_of(MANIFEST)
check("the manifest sentence is ASCII, one line, short, and spells no number, entity id, address or site value",
      MANIFEST_LIMITATION.isascii() and "\n" not in MANIFEST_LIMITATION and len(MANIFEST_LIMITATION) < 140
      and not re.search(r"\d|\b(?:sensor|switch|button|number|input_[a-z]+|script)\.|token|password", MANIFEST_LIMITATION, re.I))
check("the manifest exists and is readable", bool(manifest_text))
check("the manifest states the limitation exactly once, on a comment line directly above the guarded-start stanza; it never claims full enforcement; the schedule stanza "
      "carries the helper dependency, the active-override warning and R9's full-restart note", not manifest_problems(manifest_text), str(manifest_problems(manifest_text)))
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
check("mutant caught: the schedule stanza's helper dependency removed", bool(manifest_problems(manifest_text.replace("WITH or BEFORE", "after"))))
check("mutant caught: the schedule stanza's active-override warning removed", bool(manifest_problems(manifest_text.replace("last-result text", "result"))))
check("mutant caught: R9's full-restart note removed from the schedule stanza", bool(manifest_problems(manifest_text.replace("FULL Home Assistant restart", "restart"))))
check("control: the untouched manifest is not flagged", not manifest_problems(manifest_text))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print(f"  - {n}")
    sys.exit(1)
print("All Stage 3 limitation static tests PASSED.")
print("NOTE: a static check that the limitation is stated and that no path was added; the overrides stay a PARTIAL protection (release gate RG-ST3).")
