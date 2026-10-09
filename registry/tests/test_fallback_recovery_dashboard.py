#!/usr/bin/env python3
"""FB-B1 / FB-B2 Fallback / Recovery dashboard tab: view placement, entity ids, service-call hygiene, wording, tests.

Test-only. Reads the dashboard YAML, the deployment manifest, the card folder and the firmware's
entity names; runs the card's own node tests. NODE (20 or newer) IS REQUIRED here: the checks that need it
fail with a clear message when it is missing, they are never skipped. This is the first offline Python test
of the repository that needs node; .github/workflows/validate-ecco.yml installs only pyyaml and jinja2 and
relies on the runner's preinstalled Node. Nothing is deployed and no firmware is touched.

  [1]  the card folder: files, package.json / hacs.json shape, README, fixtures
  [2]  the view: placement between "Inverter / Advanced" and "Manual Controls", keys, spans, heading card
  [3]  entity ids: every id in the card config equals <domain>.ecco_clock_dongle_<slug(name)>
  [4]  service-call hygiene: the only button the view can press is the Review button; FB-B2: the only switch ids in the
       view are the four `entities:` values (the arm and three read-only write arms); no script / esphome / execute
       reference, no tap action, no other service call; the card source has ONE callService
  [5]  the first energy-actions card in document order is still the Dump-to-Grid schedule card
  [6]  wording: no card string matches the energy-actions regexes (parsed live from the TS source) or
       contains the two forbidden words
  [7]  the card's 31-row register table equals the FB-A struct order (header and Python mirror)
  [8]  banned tokens, mojibake and control characters in the card folder; the card source is dependency free
  [9]  YAML parses with yaml.safe_load; CRLF working-tree files stay pure CRLF
  [10] the manifest carries exactly one new frontend_assets stanza of the shape of the actions-card one
  [11] the fixture strings follow the CONTRACT grammars (key order, widths, 200-char cap, masks, ring)
  [12] the card's node tests pass (core, render, element and real-tree DOM tests)
  [13] cross-check against the firmware mirror registry/fallback_capture.py (strings, masks, B9 texts); the import is
       MANDATORY: a mirror that cannot be imported, or that lost a name the check uses, is a FAILURE, never a skip
  [14] README: the deviations from the mockup are written down, no claim that the bundle tooling copies the card,
       no reference to a design document that is not part of this change set
  [15] the dashboard edit is EXACTLY one inserted view: the file minus that view has the sha256 of the pre-FB-B1
       file, and it carries exactly the expected number of reserved tokens (final review CHAIN2)
  [16] FB-B2: the card's write surface against the firmware: the execute service name derives from the node name and the
       api action, its three variables are strings, the arm switch is ALWAYS_OFF, arm and action appear together; the
       checks are run against synthetic firmware text with one defect each (mutants) as well as the real firmware
  [17] FB-B2: nothing under home-assistant/ except the dashboard card config can act on the arm or the execute action,
       and the card builds its calls only in its click handlers (trusted-click guard present)
  [18] FB-B2: card mutants - one broken copy of the card per decision of the guarded flow (the trusted click, the ID and
       phrase that go out, the allow-list, each gate, one request and no retry, never optimistic, the B9 families); each must
       fail the node test that names it
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(HERE))
import fallback_profile as fp  # noqa: E402
import _fbb3_ha_scope as ha3  # noqa: E402  (FB-B3: the exact reverter of every FB-B3 edit to the dashboard)
import _fbc3_scope as c3  # noqa: E402  (FB-C3: the exact reverter of every FB-C3 edit to the dashboard; applied BEFORE ha3's)
import _pub0_scope as _pub0  # noqa: E402  (PUB0: the historical pins below run on the private text; the identity outside the public export)
import _lic0_scope as _lic0  # noqa: E402  (LIC0: the declared v0.9.0 licence alignment of the Energy Actions card)
import _pex  # noqa: E402  (PEX0: the historical pins below read the dashboard AS OF pub0; live safety invariants read the live file)

FAILURES: list[str] = []


def _raises_assert(fn) -> bool:
    try:
        fn()
    except AssertionError:
        return True
    return False


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


CARD_DIR = ROOT / "frontend" / "ecco-fallback-recovery-card"
CARD_JS = CARD_DIR / "ecco-fallback-recovery-card.js"
SIBLING = ROOT / "frontend" / "ecco-energy-actions-card"
DASH = ROOT / "home-assistant" / "dashboards" / "ecco_pro.yaml"
MANIFEST = ROOT / "deployment" / "ha-manifest.yaml"
FIRMWARE = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HEADER = ROOT / "firmware" / "include" / "ecco_fallback_profile.h"
FIXTURES = CARD_DIR / "test" / "fixtures"

VIEW_TITLE = "Fallback / Recovery"
VIEW_PATH = "ecco-fallback-recovery"
VIEW_ICON = "mdi:shield-refresh-outline"
CARD_TYPE = "custom:ecco-fallback-recovery-card"
ACTIONS_CARD = "custom:ecco-energy-actions-card"
DEVICE = "ecco_clock_dongle"

# [15] / CHAIN2: ecco_pro.yaml as it was BEFORE FB-B1 (main @ 4649465) is the working-tree file with the inserted view cut out.
# DERIVED once, by hand, with:   git show HEAD:home-assistant/dashboards/ecco_pro.yaml
# (HEAD = 4649465, LF text; the index blobs are LF, the working tree is CRLF under autocrlf), then sha256 of those LF bytes.
# This test never calls git. If a LATER change legitimately edits ecco_pro.yaml outside the Fallback / Recovery view, this
# constant is re-derived from the new pre-image and the commit says why; an unexplained edit is exactly what it catches.
DASH_PRE_FBB1_SHA256 = "ef6cf8165358e92f72ce11281d881228e4f7095166988c7600fad4038609908e"
# reserved entity-id tokens (BANNED) in the whole file: 0 before FB-B1, 10 in the inserted view, none anywhere else. The scope
# chain declares ecco_pro.yaml as the ONLY file allowed to carry them; this pins HOW MANY.
# FB-B2: 11 = the ten FB-B1 ids plus `entities.arm` (switch.<device>_ecco_fallback_profile_arm). The three read-only write
# arms spell no reserved token.
DASH_RESERVED_TOKENS = 11
# FB-B3 (final integration): the Safety view (the ONLY new view, immediately before Manual Controls), the Overview tile, the hero chips,
# the compact System Health rows and the Manual Controls banner add `ecco_fallback...` entity ids to ecco_pro.yaml. The FB-B1/B2 pins above
# keep holding on the file with exactly those FB-B3 edits reverted (ha3.pre_fbb3_dashboard, an exact-match reverter whose result must be
# main @ 87e6151 byte for byte); this is the exact reserved-token count of the file WITH them.
SAFETY_TITLE = "Safety"
DASH_B3_RESERVED_TOKENS = 83
HEARTBEAT_PKG_SHA256 = "96b9088207f8b3161a0dc1b5d014d31ceefa2e7868443809757d9182b426fed2"   # unchanged since main @ 87e6151
ENERGY_ACTIONS_SHA256 = "57c9798206d8a1850047474e9bdf89401523b03de89a2562a0cc18d81ac17471"   # frontend/ecco-energy-actions-card: git-TRACKED files only (main @ 87e6151 == a clean checkout), LF

BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")
SHADOW = "failback" + "_shadow"
# the saved Fable design (a spec and a mockup page) lives with the architecture docs and is NOT part of this change set:
# nothing in the card folder may point at it by path or file name
DESIGN_REFS = re.compile(r"docs/architecture|UI_UX_DESIGN|fb_b1_fallback_recovery_mockup|design/FB_B1|design/fb_b1", re.I)
# the two words no operator string may contain (assembled so this file does not spell them either)
NEVER = [re.compile("".join(p), re.I) for p in (("fai", "led"), ("defer", "red"))]
# FP-recovery tokens that must not appear anywhere under home-assistant/ (assembled from fragments)
FP_TOKENS = [
    "accept" + "_current_state", "ACCEPT" + "_CURRENT_STATE", "force_restore" + "_original", "FORCE_RESTORE" + "_ORIGINAL",
    "FORCE" + "_RUNNING", "free_power_recovery" + "_execute", "free_power_recovery" + "_force_restore",
    "free_power_recovery" + "_accept_current_state",
]

# name (as the firmware declares it) -> (domain, config key); CONTRACT section 2 plus the five base entities
ENTITIES = {
    "profile_state": ("sensor", "ECCO Fallback Profile State"),
    "summary": ("sensor", "ECCO Fallback Profile Summary"),
    "review": ("sensor", "ECCO Fallback Profile Review"),
    "review_id": ("sensor", "ECCO Fallback Profile Review ID"),
    "review_slots": ("sensor", "ECCO Fallback Profile Review Slots"),
    "review_context": ("sensor", "ECCO Fallback Profile Review Context"),
    "saved_slots": ("sensor", "ECCO Fallback Profile Slots"),
    "saved_context": ("sensor", "ECCO Fallback Profile Context"),
    "last_result": ("sensor", "ECCO Fallback Profile Last Action-Result"),
    "review_button": ("button", "ECCO Fallback Profile: Review Current Configuration"),
    # FB-B2: the arm switch (the card switches it from a user click) ...
    "arm": ("switch", "ECCO Fallback Profile Arm"),
    "supervision_stable": ("binary_sensor", "ECCO Supervision Stable"),
    "supervision_state": ("sensor", "ECCO Supervision State"),
    "ntp_synced": ("binary_sensor", "NTP Synced"),
    "write_lock": ("binary_sensor", "Manual Write In Progress"),
    "configuration_online": ("binary_sensor", "Configuration Online"),
    # FB-B2: ... and the three existing write arms, read-only on the card (the dongle refuses a save while one is on)
    "free_power_arm": ("switch", "Free Power Write Enable"),
    "dump_arm": ("switch", "Dump to Grid Write Enable"),
    "manual_arm": ("switch", "Manual Configuration Write Enable"),
}
BASE_KEYS = ("supervision_stable", "supervision_state", "ntp_synced", "write_lock", "configuration_online",
             "free_power_arm", "dump_arm", "manual_arm")
ARM_KEYS = ("arm", "free_power_arm", "dump_arm", "manual_arm")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower())


def expected_id(key: str) -> str:
    domain, name = ENTITIES[key]
    return f"{domain}.{DEVICE}_{slug(name)}"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def walk(node):
    """Every dict/list/scalar in document order."""
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def strings_in(node):
    return [x for x in walk(node) if isinstance(x, str)]


def card_regexes():
    """Every regex literal in the actions card's TypeScript used with .test( (same extraction as the FB-C1 suite)."""
    src = SIBLING / "src"
    files = sorted(src.glob("*.ts")) + sorted((src / "utils").glob("*.ts"))
    out, seen = [], set()
    for f in files:
        text = read(f)
        found = list(re.finditer(r"const\s+\w+\s*=\s*/((?:\\.|[^/\n\\])+)/([a-z]*)\s*;", text))
        found += list(re.finditer(r"(?<![\w/])/((?:\\.|[^/\n\\])+)/([a-z]*)\.test\(", text))
        for m in found:
            key = (m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            out.append((re.compile(m.group(1), re.I if "i" in m.group(2) else 0), f.name))
    return out


def run_node(args, timeout=600):
    node = shutil.which("node")
    if node is None:
        return None
    return subprocess.run([node, *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


# ---- CONTRACT section 2 grammars (fixtures) -----------------------------------------------------------------
CLASSES = "NOT_CAPTURED|VALID|INVALIDATED|CORRUPT|CORRUPT_DOMAIN|UNREADABLE|PROFILE_LOST|SAVE_UNCONFIRMED|PROFILE_STALE"
RE_B1 = re.compile(rf"^(?:{CLASSES})$")
# FB-B2: B2 `werr` is E<hex> (the last non-OK storage error) and `us` the commit time in microseconds once the dongle has saved
# or invalidated; FB-B1 printed `-` for both. B3 `st` gains SAVING.
RE_B2 = re.compile(
    r"^g=(?:\d{1,10}|-);id=(?:[0-9A-F]{16}|-);at=(?:\d{1,10}|-);ld=(?:OK|ABS|WSZ|RERR|UNAV);"
    r"df=(?:MAGIC|SCHEMA|SIZE|BINDING|RESERVED|FLAGS|GEN|DOMAIN|-);w=(?:OK|LAG|MISS|CORR|UNR|ABS);hw=(?:\d{1,10}|-);"
    r"op=(?:SAVE|INV|RC|-);why=(?:-|INT|RBK|MIS|SUP|LAG|MISS|CORR|PRD|WRD|ANOM|FIRST|LWC);werr=(?:-|E[0-9A-F]{1,8});us=(?:-|\d{1,10})$"
)
RE_B3 = re.compile(
    rf"^st=(?:IDLE|READING|CANDIDATE_READY|CANDIDATE_NOT_SAVEABLE|SAVING);prior=(?:{CLASSES}|-);exp=(?:\d{{1,3}}|-);"
    r"warn=(?:-|W[1-6](?:,W[1-6])*);obl=(?:-|FP:[A-Z]{2},DP:[A-Z]{2},R4:[A-Z]{2},MT:[A-Z]{2},FS:[A-Z]{2},BUS:[A-Z]{2});"
    r"latch=(?:-|FP|DP|R4|FP,DP|FP,R4|DP,R4|FP,DP,R4);sv=(?:-|OK|NO:[A-Z0-9]+(?:,[A-Z0-9]+){0,2}(?:\+\d+)?)$"
)
RE_B4 = re.compile(r"^(?:[0-9A-F]{16}|-)$")
SLOT = r"(?:\d{4,5}/\d{1,5}/\d{1,5}/\d{1,5}|-)"
SLOTS = ";".join(f"{n}={SLOT}" for n in range(1, 7))
RE_B5 = re.compile(rf"^v=(?:CAND|NONE);g=-;244=(?:\d{{1,5}}|-);{SLOTS};dx=(?:[0-9A-F]{{5}}|-)$")
RE_B7 = re.compile(rf"^v=(?:SAVED|NONE);g=(?:\d{{1,10}}|-);244=(?:\d{{1,5}}|-);{SLOTS};dx=-;b=(?:[0-9A-F]{{8}}|-)$")
CTX = (
    r"232=(?:[0-9A-F]{4}|-);243=(?:\d{1,5}|-);248=(?:[0-9A-F]{4}|-);ring=(?:OK|BAD|-);230=(?:\d{1,5}|-);"
    r"245=(?:\d{1,5}|-);247=(?:[0-9A-F]{4}|-)"
)
RE_B6 = re.compile(rf"^v=(?:CAND|NONE);{CTX};dc=(?:[0-9A-F]{{3}}|-);di=(?:[0-9A-F]{{2}}|-)$")
RE_B8 = re.compile(rf"^v=(?:SAVED|NONE);{CTX};dc=-;di=-;b=(?:[0-9A-F]{{8}}|-)$")
B9_PREFIXES = (
    "No Fallback Profile action since boot", "review in progress (read-only)", "CANDIDATE READY", "CANDIDATE NOT SAVEABLE",
    "REVIEW REFUSED", "REVIEW NOT COMPLETED", "REVIEW EXPIRED", "REVIEW CLEARED", "INTERNAL",
    # FB-B2: the Save / Invalidate families (the acceptance line is lower case, every other prefix is a fixed word set)
    "save in progress", "SAVED - ", "SAVE REFUSED - ", "SAVE NOT COMMITTED - ", "SAVE OUTCOME UNKNOWN - ",
    "INVALIDATED - ", "INVALIDATE REFUSED - ", "INVALIDATE NOT COMMITTED", "INVALIDATE OUTCOME UNKNOWN - ", "REFUSED - ",
)
# FB-B2: the prefix of a firmware Save / Invalidate text -> the card's kind of it (parseB9): used by the mirror cross-check
B9_KIND_OF_PREFIX = (
    ("save in progress - ", "saveprogress"), ("SAVE REFUSED - ", "saverefused"), ("SAVED - ", "saved"), ("SAVE NOT COMMITTED - ", "savenotcommitted"),
    ("SAVE OUTCOME UNKNOWN - ", "saveunknown"), ("INVALIDATE REFUSED - ", "invalidaterefused"), ("INVALIDATED - ", "invalidated"),
    ("INVALIDATE NOT COMMITTED", "invalidatenotcommitted"), ("INVALIDATE OUTCOME UNKNOWN - ", "invalidateunknown"),
    ("REFUSED - ", "actionrefused"), ("RESTORE REFUSED - ", "actionrefused"), ("ACKNOWLEDGE REFUSED - ", "actionrefused"),
    ("INTERNAL - ", "internal"),
)


def kv(s: str) -> dict:
    return dict(p.split("=", 1) for p in s.split(";"))


def ring_ok(starts):
    m = []
    for v in starts:
        hh, mm = divmod(v, 100)
        if v > 2359 or hh > 23 or mm > 59:
            return False
        m.append(hh * 60 + mm)
    gaps = [(m[(i + 1) % 6] - m[i] + 1440) % 1440 for i in range(6)]
    return all(g > 0 for g in gaps) and sum(gaps) == 1440


def words(slots: dict, ctx: dict) -> dict:
    w = {}
    if slots["244"] != "-":
        w[244] = int(slots["244"])
    for n in range(1, 7):
        t = slots[str(n)]
        if t != "-":
            hh, p, s, src = (int(x) for x in t.split("/"))
            w[250 + n - 1], w[256 + n - 1], w[268 + n - 1], w[274 + n - 1] = hh, p, s, src
    for r in ("232", "248", "247"):
        if ctx[r] != "-":
            w[int(r)] = int(ctx[r], 16)
    for r in ("243", "230", "245"):
        if ctx[r] != "-":
            w[int(r)] = int(ctx[r])
    return w


def masks(c: dict, s: dict):
    dx = dc = di = 0
    if c[244] != s[244]:
        dx |= 1
    for i in range(6):
        dx |= (c[256 + i] != s[256 + i]) << (1 + i)
        dx |= (c[268 + i] != s[268 + i]) << (7 + i)
        dx |= (c[274 + i] != s[274 + i]) << (13 + i)
        dc |= (c[250 + i] != s[250 + i]) << (3 + i)
    dc |= ((c[232] ^ s[232]) & 1) | ((c[243] != s[243]) << 1) | (((c[248] ^ s[248]) & 1) << 2)
    di |= (c[230] != s[230]) | ((c[245] != s[245]) << 1) | ((c[247] != s[247]) << 2)
    di |= (((c[232] ^ s[232]) & 0xFFFE) != 0) << 3 | (((c[248] ^ s[248]) & 0xFFFE) != 0) << 4
    return f"{dx:05X}", f"{dc:03X}", f"{di:02X}"


# Runs the REAL card (through the test helpers) on entity-state sets that come out of the firmware mirror's text builders and
# prints what the card derives from them: `node --input-type=module -e <this> <helpers.mjs> <cases.json>`.
CARD_FEED_JS = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [helpers, input] = process.argv.slice(1);
const { card, renderScenario, textNodes } = await import(pathToFileURL(helpers).href);
const cases = JSON.parse(readFileSync(input, 'utf8'));
const out = {};
for (const [label, E] of Object.entries(cases)) {
  const r = renderScenario(label, { E, ui: { detailOpen: true } });
  const lm = card.liveMatch(r.vm, r.tv);
  out[label] = {
    word: lm.word,
    sentence: lm.sentence.join(''),
    c2: textNodes(r.out.cards.c2.inner, r.tv).join(' '),
    markers: (r.out.cards.c6.inner.match(/class="diff"/g) || []).length,
    deltas: card.buildRegisterTable(r.vm).rows.map((x) => x.delta),
    cmp: r.vm.cmp,
    candOK: r.vm.candOK,
    savedOK: r.vm.savedOK,
    note: card.notComparedNote(r.vm),
  };
}
process.stdout.write(JSON.stringify(out));
"""


def cross_check_mirror(fc, fixtures, exempt) -> None:
    """Fixture strings, masks and every B9 text builder of the firmware mirror, against the card."""
    def wlist(slots: dict, ctx: dict) -> list:
        w = [0] * 31
        w[0] = int(slots["244"])
        for n in range(1, 7):
            hh, pw, soc, src = (int(x) for x in slots[str(n)].split("/"))
            w[n], w[6 + n], w[12 + n], w[21 + n] = pw, soc, src, hh
        w[19], w[20], w[21] = int(ctx["232"], 16), int(ctx["243"]), int(ctx["248"], 16)
        w[28], w[29], w[30] = int(ctx["230"]), int(ctx["245"]), int(ctx["247"], 16)
        return w

    diffs = []
    n_checked = 0
    for name, s in fixtures.items():
        if name in exempt or "=" not in s["review"] or s["review_slots"] in ("unavailable", "unknown"):
            continue
        b3, b5, b6 = kv(s["review"]), kv(s["review_slots"]), kv(s["review_context"])
        if b5["v"] != "CAND":
            if str(fc.b5_text(False, [0] * 31, False, 0)) != s["review_slots"] or str(fc.b6_text(False, [0] * 31, False, 0, 0)) != s["review_context"]:
                diffs.append(f"{name}: NONE form")
            continue
        w = wlist(b5, b6)
        saved = kv(s["saved_slots"])
        stored = saved["v"] == "SAVED"
        sw = wlist(saved, kv(s["saved_context"])) if stored else None
        dx, dc, di = (fc.e1_delta_mask(w, sw), fc.ctx_mismatch_mask(w, sw), fc.info_mismatch_mask(w, sw)) if stored else (0, 0, 0)
        n_checked += 4
        if str(fc.b5_text(True, w, stored, dx)) != s["review_slots"]:
            diffs.append(f"{name}: B5")
        if str(fc.b6_text(True, w, stored, dc, di)) != s["review_context"]:
            diffs.append(f"{name}: B6")
        if str(fc.sv_text(fc.capture_refusals(w, 8000))) != b3["sv"] and b3["st"] != "CANDIDATE_NOT_SAVEABLE":
            diffs.append(f"{name}: sv")
        if b3["st"] == "CANDIDATE_NOT_SAVEABLE" and b3["sv"] != "OK" and str(fc.sv_text(fc.capture_refusals(w, 8000))) != b3["sv"]:
            diffs.append(f"{name}: sv (not saveable)")
        if str(fc.warn_text(fc.capture_warnings(w))) != b3["warn"]:
            diffs.append(f"{name}: warn")
    check("fixture B5 / B6 / sv / warn strings equal the mirror's text builders and masks", not diffs and n_checked >= 40, f"{n_checked} checked; {diffs[:6]}")

    texts: dict = {}
    kinds = [fc.OBL_ACTIVE, fc.OBL_STARTING, fc.OBL_RESTORE_REQUIRED, fc.OBL_PENDING_CLEAR, fc.OBL_ENDING, fc.OBL_OPERATOR_NEEDED, fc.UNK_DURABLE_UNREADABLE,
             fc.UNK_METADATA_CORRUPT, fc.UNK_BOOT_NOT_LOADED, fc.UNK_DIVERGED, fc.UNK_BUS_OR_LOCK_STUCK, fc.UNK_NOT_PROBED, fc.BUS_BUSY, fc.OBL_CLEAR_PROVEN]
    bases = [fc.BASIS_NONE, fc.BASIS_RUNTIME_PROBE, fc.BASIS_GHOST_RR, fc.BASIS_GHOST_PC, fc.BASIS_RAM_INCONSISTENT, fc.BASIS_FBS_EPISODE, fc.BASIS_BOOT_LOCKOUT, fc.BASIS_LOCK_STUCK]
    for slot in (fc.SLOT_BUS, fc.SLOT_FBS, fc.SLOT_FP, fc.SLOT_DUMP, fc.SLOT_R244, fc.SLOT_MTOU):
        for k in kinds:
            for b in bases:
                for containment in (0, 3):
                    texts[str(fc.refusal_text(slot, fc.SlotClass(k, b), containment, "Free Power", 312))] = "refused"
    for t in (fc.refused_in_flight_text(), fc.refused_not_loaded_text(), fc.refused_arms_text()):
        texts[str(t)] = "refused"
    for code in range(0, 8):
        for step in range(0, 5):
            for exc in (0, 2):
                texts[str(fc.read_fail_text(code, step, exc))] = "notcompleted"
    for slot in (fc.SLOT_FP, fc.SLOT_DUMP, fc.SLOT_R244, fc.SLOT_FBS):
        texts[str(fc.review_cleared_domain_text(slot))] = "cleared"
    texts[str(fc.review_cleared_writes_text())] = "cleared"
    texts[str(fc.review_expired_text())] = "expired"
    texts[str(fc.breaker_text(True))] = "internal"
    texts[str(fc.breaker_text(False))] = "internal"
    texts[str(fc.internal_context_text())] = "internal"
    texts[str(fc.b9_seed_text())] = "seed"
    texts[str(fc.review_in_progress_text())] = "reading"
    texts[str(fc.candidate_ready_text())] = "ready"
    check("the mirror produces a broad set of distinct B9 texts, all within 200 characters", len(texts) > 60 and max(len(t) for t in texts) <= 200, str(len(texts)))
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td) / "b9.json"
        tp.write_text(json.dumps(texts), encoding="utf-8")
        res = run_node([str(CARD_DIR / "test" / "check-b9.mjs"), str(tp)], timeout=300)
    if res is None or res.returncode != 0:
        check("the card handles every mirror B9 text (node ran)", False, "node missing" if res is None else res.stderr[-300:])
    else:
        out = json.loads(res.stdout)
        check("every mirror B9 text maps to the matching card state", not out["wrongState"], str(out["wrongState"][:3]))
        check("no mirror B9 text, echoed by the card, matches an energy-actions regex or a forbidden word", not out["hazards"], str(out["hazards"][:3]))

    # every obligation vector the firmware can publish must be one the card's strict parser accepts (exactly six entries,
    # FP,DP,R4,MT,FS,BUS), and every code in it must have a text and a class
    all_bases = bases + [fc.BASIS_MARKER_CLEAR, fc.BASIS_ABSENT, fc.BASIS_NO_DURABLE_STATE, fc.BASIS_BUS_IDLE]
    clear_slot = fc.SlotClass(fc.OBL_CLEAR_PROVEN, fc.BASIS_ABSENT)
    vectors = {str(fc.vector_text(*([clear_slot] * 6)))}
    for pos in range(6):
        for k in kinds:
            for b in all_bases:
                slots = [clear_slot] * 6
                slots[pos] = fc.SlotClass(k, b)
                vectors.add(str(fc.vector_text(*slots)))
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td) / "obl.json"
        tp.write_text(json.dumps(sorted(vectors)), encoding="utf-8")
        res = run_node([str(CARD_DIR / "test" / "check-obl.mjs"), str(tp)], timeout=300)
    if res is None or res.returncode != 0:
        check("the card parses every mirror obligation vector (node ran)", False, "node missing" if res is None else res.stderr[-300:])
    else:
        out = json.loads(res.stdout)
        check("the mirror produces a broad set of distinct obligation vectors", out["count"] > 60, str(out["count"]))
        check("the card's strict six-entry parser accepts every vector the mirror produces", not out["rejected"], str(out["rejected"]))
        check("every obligation code the mirror produces has a card text", not out["noText"], str(out["noText"]))
        classes = out["classes"]
        check("clear / transient / lockout classes of the mirror's codes",
              {k for k, v in classes.items() if v == "clear"} <= {"CM", "CA", "CN", "OK"}
              and {k for k, v in classes.items() if v == "transient"} <= {"AC", "ST", "RR", "PC", "EN"}
              and {k for k, v in classes.items() if v == "lockout"} <= {"ON", "UR", "MC", "BL", "DV", "LK", "NP", "BY"}, str(classes))

    cross_check_review_masks(fc, fixtures)


def b9_kind_of(text: str):
    for prefix, kind in B9_KIND_OF_PREFIX:
        if text.startswith(prefix):
            return kind
    return None


def cross_check_save_mirror(fs, fc, fd) -> None:
    """FB-B2: every Save / Invalidate B9 text of the firmware mirror (registry/fallback_save.py) through the card: each one is
    classified into the family and outcome its prefix says, stays within 200 characters, leaves the review state alone and
    matches no energy-actions regex or forbidden word. Zero-argument `*_text` builders are found by introspection, so a text
    added to the mirror later is covered without editing this test."""
    import inspect

    texts: dict = {}

    def add(t):
        s = str(t)
        if s:
            texts[s] = b9_kind_of(s)

    for name, fn in inspect.getmembers(fs, inspect.isfunction):
        if name.endswith("_text") and not inspect.signature(fn).parameters:
            add(fn())
    simple_zero = len(texts)
    check("the save mirror has many zero-argument B9 text builders", simple_zero >= 20, str(simple_zero))
    for token in (fs.ACT_SAVE, fs.ACT_INVALIDATE, fs.ACT_RESTORE, fs.ACT_ACKNOWLEDGE, fs.ACT_UNSUPPORTED):
        add(fs.action_refusal_text(token, "FOO", 3))
    for bad in ("FOO", "", "lowercase", "A" * 40, "a'b\"c", "\u00e9"):
        add(fs.unsupported_action_text(bad.encode("utf-8")))
    for kind in (fs.PHRASE_SAVE, fs.PHRASE_SAVE_REPLACE_CORRUPT, fs.PHRASE_INVALIDATE):
        add(fs.save_phrase_text(fs.expected_phrase(kind, 0x5F3A9C21B04E7D18)))
        add(fs.invalidate_phrase_text(fs.expected_phrase(kind, 0x5F3A9C21B04E7D18)))
    for slot in (fc.SLOT_FBS, fc.SLOT_FP, fc.SLOT_DUMP, fc.SLOT_R244, fc.SLOT_MTOU, fc.SLOT_BUS):
        for k in (fc.OBL_ACTIVE, fc.OBL_STARTING, fc.OBL_RESTORE_REQUIRED, fc.OBL_PENDING_CLEAR, fc.OBL_ENDING, fc.OBL_OPERATOR_NEEDED,
                  fc.UNK_DURABLE_UNREADABLE, fc.UNK_METADATA_CORRUPT, fc.UNK_BOOT_NOT_LOADED, fc.UNK_DIVERGED, fc.UNK_BUS_OR_LOCK_STUCK,
                  fc.UNK_NOT_PROBED, fc.BUS_BUSY, fc.OBL_CLEAR_PROVEN):
            for b in (fc.BASIS_NONE, fc.BASIS_RUNTIME_PROBE, fc.BASIS_GHOST_RR, fc.BASIS_GHOST_PC, fc.BASIS_RAM_INCONSISTENT,
                      fc.BASIS_FBS_EPISODE, fc.BASIS_BOOT_LOCKOUT, fc.BASIS_LOCK_STUCK):
                for containment in (0, 3):
                    add(fs.save_slot_refusal_text(slot, fc.SlotClass(k, b), containment, "Free Power", 312))
                if slot == fc.SLOT_FBS:
                    add(fs.invalidate_fbs_text(fc.SlotClass(k, b)))
    for code in range(0, 8):
        for step in range(0, 5):
            for exc in (0, 2):
                add(fs.save_read_fail_text(code, step, exc))
    a, b2 = [0] * 31, [0] * 31
    b2[1] = 5000
    add(fs.save_changed_during_read_text(a, b2))
    add(fs.save_changed_since_review_text(a, b2))
    for cls in range(0, 9):
        for why in range(0, 14):
            add(fs.save_class_text(cls, why))
        add(fs.invalidate_class_text(cls))
        add(fs.invalidate_class_now_text(cls))
    add(fs.invalidate_generation_text(True))
    add(fs.invalidate_generation_text(False))

    def result(w_out, w_err, w_rb, p_out, p_err, p_rb, witness, refusal):
        r = fd.TxnResult()
        r.w.outcome, r.w.err, r.w.rb_class = w_out, w_err, w_rb
        r.p.outcome, r.p.err, r.p.rb_class = p_out, p_err, p_rb
        r.witness_advanced, r.refusal = witness, refusal
        return r

    for op in (0, fd.PROV_OP_SAVE, fd.PROV_OP_REPLACE_CORRUPT, fd.PROV_OP_INVALIDATE):
        for outcome in (fd.TXN_UNKNOWN_REBOOT, fd.TXN_COMMITTED, fd.TXN_NOT_COMMITTED, fd.TXN_REFUSED_LATCHED):
            for refusal in range(0, 6):
                for witness in (False, True):
                    for err in (0, 0x105, 0x1102):
                        for rb in range(0, 8):
                            for unknown_key in (0, 1):
                                r = result(fd.KEY_UNKNOWN_REBOOT if unknown_key == 0 else fd.KEY_COMMITTED, err, rb,
                                           fd.KEY_UNKNOWN_REBOOT if unknown_key == 1 else fd.KEY_COMMITTED, err, rb, witness, refusal)
                                add(fs.txn_outcome_text(op, outcome, r, 8, 7))
    bad_kind = [t for t, k in texts.items() if k is None]
    check("every Save / Invalidate B9 text of the mirror starts with a prefix the card classifies", not bad_kind, str(bad_kind[:3]))
    check("the save mirror produces a broad set of distinct B9 texts, all within 200 characters",
          len(texts) > 200 and max(len(t) for t in texts) <= 200, f"{len(texts)} texts, longest {max(len(t) for t in texts)}")
    kinds_seen = {k for k in texts.values()}
    expected_kinds = {k for _, k in B9_KIND_OF_PREFIX}
    check("the mirror produces every family of the card (save and invalidate refused / saved / not committed / unknown, action refused, internal)",
          expected_kinds <= kinds_seen, str(expected_kinds - kinds_seen))
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td) / "b9_save.json"
        tp.write_text(json.dumps({t: k for t, k in texts.items() if k}), encoding="utf-8")
        res = run_node([str(CARD_DIR / "test" / "check-b9.mjs"), str(tp)], timeout=300)
    if res is None or res.returncode != 0:
        check("the card handles every save mirror B9 text (node ran)", False, "node missing" if res is None else res.stderr[-300:])
    else:
        out = json.loads(res.stdout)
        check("every save mirror B9 text maps to the matching card family and outcome", not out["wrongState"], str(out["wrongState"][:3]))
        check("no save mirror B9 text, echoed by the card, matches an energy-actions regex or a forbidden word", not out["hazards"], str(out["hazards"][:3]))


SYNTHETIC_FIRMWARE = """esphome:
  name: ecco-clock-dongle
api:
  actions:
    - action: ha_supervision_heartbeat
      variables:
        challenge: string
      then:
        - lambda: |-
            return;
    - action: fallback_profile_execute
      variables:
        action: string
        target_id: string
        confirmation: string
      then:
        - lambda: |-
            return;
switch:
  - platform: template
    id: fallback_profile_arm
    name: "ECCO Fallback Profile Arm"
    optimistic: true
    restore_mode: ALWAYS_OFF
  - platform: template
    id: other_switch
    name: "Other Switch"
"""


def _top_level_section(fw: str, key: str) -> str:
    """FB-B2 (AW-2): the text of the top-level YAML key `key` (its own line up to the next unindented, non-comment line); '' when it is absent."""
    m = re.search(rf"(?m)^{re.escape(key)}:[ \t]*(?:#.*)?$", fw)
    if not m:
        return ""
    stop = re.search(r"\n[^\s#]", fw[m.end():])
    return fw[m.start():m.end() + stop.start()] if stop else fw[m.start():]


def firmware_surface_problems(fw: str, card_src: str) -> list:
    """FB-B2: defects in the execute action / arm switch surface the card depends on; an empty list means consistent.
    FB-B2 (AW-2): PRESENCE is a hard requirement. A firmware text with no `fallback_profile_execute` action, or no `ECCO Fallback Profile Arm`
    switch, is a defect (a firmware with neither used to pass, vacuously). Each must be declared exactly once, as a real item of its own
    top-level section (the action under `api:`, the switch under `switch:`), with the pinned single-line forms below.
    The firmware YAML carries !secret / !lambda tags, so this reads it as text, like the supervision heartbeat suite does."""
    fw = fw.replace("\r\n", "\n")
    problems: list = []
    node = re.search(r"(?m)^esphome:\s*\n\s+name:\s*([A-Za-z0-9_-]+)", fw)
    act_rx = r"(?m)^([ \t]*)-[ \t]*action:[ \t]*fallback_profile_execute[ \t]*$"
    acts = list(re.finditer(act_rx, fw))
    arm_name = ENTITIES["arm"][1]
    arm_rx = r'(?m)^[ \t]*name:[ \t]*"' + re.escape(arm_name) + r'"[ \t]*$'
    arm_names = list(re.finditer(arm_rx, fw))
    if len(acts) != 1:
        problems.append(f"the firmware declares the fallback_profile_execute api action {len(acts)} times (exactly one is required)")
    elif not re.search(act_rx, _top_level_section(fw, "api")):
        problems.append("the fallback_profile_execute action is not an item of the top-level api: section")
    if len(arm_names) != 1:
        problems.append(f"the firmware declares the {arm_name!r} switch {len(arm_names)} times (exactly one is required)")
    elif not re.search(arm_rx, _top_level_section(fw, "switch")):
        problems.append("the arm switch is not an item of the top-level switch: section")
    card_service = re.search(r"export const EXECUTE_SERVICE = '([a-z0-9_]+)'", card_src)
    if len(acts) == 1:
        act = acts[0]
        if not node:
            problems.append("the firmware declares no esphome node name")
        elif not card_service or card_service.group(1) != node.group(1).replace("-", "_") + "_fallback_profile_execute":
            problems.append("the card's execute service name is not <node name>_<api action>")
        lines = fw[act.start():].split("\n")
        indent = len(act.group(1))
        block = [lines[0]]
        for ln in lines[1:]:
            if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
                break
            block.append(ln)
        body = "\n".join(block)
        variables = re.search(r"variables:\s*\n((?:[ \t]+\w+:[ \t]*\w+[ \t]*\n)+)", body)
        got = dict(re.findall(r"(\w+):[ \t]*(\w+)", variables.group(1))) if variables else {}
        if got != {"action": "string", "target_id": "string", "confirmation": "string"}:
            problems.append(f"the action variables are not exactly action / target_id / confirmation as strings: {got}")
    if len(arm_names) == 1:
        at = arm_names[0].start()
        start = fw.rfind("\n  - platform:", 0, at)
        stop = re.compile(r"\n(?:  - platform:|[^\s#])").search(fw, at)
        item = fw[start:stop.start() if stop else len(fw)] if start != -1 else ""
        if not re.match(r"\n  - platform: template[ \t]*\n", item):
            problems.append("the arm switch is not a `platform: template` item")
        if not re.search(r"(?m)^    id:[ \t]*fallback_profile_arm[ \t]*$", item):
            problems.append("the arm switch id is not fallback_profile_arm")
        if not re.search(r"(?m)^    restore_mode:[ \t]*ALWAYS_OFF[ \t]*$", item):
            problems.append("the arm switch does not restore ALWAYS_OFF")
        if not re.search(r"(?m)^    optimistic:[ \t]*true[ \t]*$", item):
            problems.append("the arm switch is not optimistic")
    return problems


def cross_check_review_masks(fc, fixtures) -> None:
    """FW0 and ACCEPT0 end to end: the mirror's review_evaluate and B1..B8 text builders produce the entity strings, the real
    card derives the Live Match and the markers from them. The mirror is the firmware's header in Python, so this is what the
    dashboard would show for those firmware outputs, with no hand-written string in between except the B2 summary and the
    supervision/NTP entities (taken from fixtures; the card's masks never read them)."""
    def words_of_fixture(name):
        s = fixtures[name]
        b5, b6 = kv(s["review_slots"]), kv(s["review_context"])
        w = [0] * 31
        w[0] = int(b5["244"])
        for n in range(1, 7):
            hh, pw, soc, src = (int(x) for x in b5[str(n)].split("/"))
            w[n], w[6 + n], w[12 + n], w[21 + n] = pw, soc, src, hh
        w[19], w[20], w[21] = int(b6["232"], 16), int(b6["243"]), int(b6["248"], 16)
        w[28], w[29], w[30] = int(b6["230"]), int(b6["245"]), int(b6["247"], 16)
        return w

    def profile_of(w, generation=7):
        return fp.seal_profile(fp.blank_profile(
            magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=generation, captured_epoch=1790000000, flags=0,
            reg244=w[0], reg256_261=w[1:7], reg268_273=w[7:13], reg274_279=w[13:19], reg232=w[19], reg243=w[20],
            reg248=w[21], reg250_255=w[22:28], reg230=w[28], reg245=w[29], reg247=w[30]))

    stored_w = words_of_fixture("ready_match")
    stored_p = profile_of(stored_w)
    check("mirror review cross-check: the stored profile built from the fixture words is an authentic VALID record that round-trips",
          fp.classify_profile(fp.LOAD_OK, stored_p) == fp.PROFILE_VALID and list(fc.words_of(stored_p)) == stored_w)
    diff_w = list(stored_w)                 # settings (256), context (232 bit 0) and information (230) all differ
    diff_w[1] = 5000 if stored_w[1] != 5000 else 4000
    diff_w[19] ^= 1
    diff_w[28] = stored_w[28] + 1
    info_w = list(stored_w)                 # only information-only registers (230, 245, 247) differ
    info_w[28] = stored_w[28] + 1
    info_w[29] = stored_w[29] - 1
    info_w[30] ^= 1
    clear = fc.SlotClass(fc.OBL_CLEAR_PROVEN, fc.BASIS_ABSENT)
    obl = str(fc.vector_text(*([clear] * 6)))
    base = fixtures["ready_match"]

    def entities(cand_w, cls):
        v = fc.review_evaluate(fc.ReviewInputs(words=cand_w, ceiling_w=8000, cls=cls, read_anomaly=0, p_load=fp.LOAD_OK, p=stored_p, salt=1, seq_next=1))
        st = fc.CAPTURE_CANDIDATE_READY if v.eligible else fc.CAPTURE_CANDIDATE_NOT_SAVEABLE
        e = dict(base)
        e["profile_state"] = str(fc.epc_name(cls))
        e["summary"] = fixtures["not_saveable_unreadable"]["summary"] if cls == fc.fd.EPC_UNREADABLE else base["summary"]
        e["review"] = str(fc.b3_text(st, True, cls, 100, v.warnings, obl, 0, str(v.sv)))
        e["review_id"] = str(fc.b4_text(v.eligible, v.id))
        e["review_slots"] = str(fc.b5_text(True, cand_w, v.has_stored, v.dx))
        e["review_context"] = str(fc.b6_text(True, cand_w, v.has_stored, v.dc, v.di))
        e["saved_slots"] = str(fc.b7_text(fp.LOAD_OK, stored_p, cls))
        e["saved_context"] = str(fc.b8_text(fp.LOAD_OK, stored_p, cls))
        e["last_result"] = str(fc.candidate_ready_text()) if v.eligible else str(fc.not_saveable_text(v.refusals, cand_w, cls, 0))
        return v, e

    v_un, e_un = entities(diff_w, fc.fd.EPC_UNREADABLE)       # FW0: an AUTHENTIC record whose effective class is UNREADABLE
    v_tr, e_tr = entities(diff_w, fc.fd.EPC_VALID)
    v_in, e_in = entities(info_w, fc.fd.EPC_VALID)
    v_eq, e_eq = entities(stored_w, fc.fd.EPC_VALID)
    check("mirror review cross-check: FW0 - an authentic stored record with the effective class UNREADABLE is not trusted (has_stored false; dx / dc / di '-'; B7 / B8 v=NONE)",
          not v_un.has_stored and e_un["review_slots"].endswith(";dx=-") and e_un["review_context"].endswith(";dc=-;di=-")
          and e_un["saved_slots"].startswith("v=NONE") and e_un["saved_context"].startswith("v=NONE") and e_un["profile_state"] == "UNREADABLE"
          and kv(e_un["review"])["prior"] == "UNREADABLE" and kv(e_un["review"])["st"] == "CANDIDATE_NOT_SAVEABLE")
    check("mirror review cross-check: the same candidate under the trusted class VALID carries real masks and the saved views",
          v_tr.has_stored and re.search(r";dx=[0-9A-F]{5}$", e_tr["review_slots"]) and re.search(r";dc=[0-9A-F]{3};di=[0-9A-F]{2}$", e_tr["review_context"])
          and e_tr["saved_slots"].startswith("v=SAVED") and kv(e_tr["review"])["st"] == "CANDIDATE_READY")
    check("mirror review cross-check: the two ACCEPT0 candidates (info-only difference; identical) have dx = dc = 0 and di 07 / 00",
          e_in["review_slots"].endswith(";dx=00000") and e_in["review_context"].endswith(";dc=000;di=07")
          and e_eq["review_slots"].endswith(";dx=00000") and e_eq["review_context"].endswith(";dc=000;di=00"),
          f"{e_in['review_context']} {e_eq['review_context']}")

    with tempfile.TemporaryDirectory() as td:
        tp = Path(td) / "feed.json"
        tp.write_text(json.dumps({"fw0_unreadable": e_un, "trusted_diff": e_tr, "info_only": e_in, "identical": e_eq}), encoding="utf-8")
        res = run_node(["--input-type=module", "-e", CARD_FEED_JS, str(CARD_DIR / "test" / "helpers.mjs"), str(tp)], timeout=300)
    if res is None or res.returncode != 0:
        check("the card renders the mirror review strings (node ran)", False, "node missing" if res is None else res.stderr[-400:])
        return
    out = json.loads(res.stdout)
    un, tr, inf, eq = out["fw0_unreadable"], out["trusted_diff"], out["info_only"], out["identical"]
    check("FW0 end to end: a candidate over an UNREADABLE stored profile is not compared: Live Match UNKNOWN, no match claim, nothing marked",
          un["candOK"] and not un["cmp"]["comparable"] and un["cmp"]["untrusted"] and un["word"] == "UNKNOWN"
          and not re.search(r"MATCHES|matched", un["c2"]) and "31 of 31" not in un["c2"] and un["markers"] == 0 and set(un["deltas"]) == {"none"} and len(un["deltas"]) == 31,
          json.dumps(un)[:300])
    check("FW0 end to end: the card says the profile is not trusted and not compared (no silent 'no differences')",
          "cannot be trusted" in un["c2"] and un["note"].startswith("Not compared: the stored profile is UNREADABLE") and not un["savedOK"])
    check("FW0 end to end: the same candidate over a trusted profile is compared (DIFFERS (CONTEXT), markers, differing deltas)",
          tr["cmp"]["comparable"] and tr["word"] == "DIFFERS (CONTEXT)" and tr["markers"] >= 3 and "ne" in tr["deltas"] and tr["note"] == "", json.dumps(tr)[:300])
    check("ACCEPT0 end to end: only information-only registers differ -> MATCHES SAVED PROFILE, never '31 of 31', and it says info-only values differ",
          inf["word"] == "MATCHES SAVED PROFILE" and "31 of 31" not in inf["c2"] and "Info-only values differ (not restored by Fallback V1)." in inf["c2"]
          and "All compared settings and context matched" in inf["c2"] and inf["markers"] == 3, json.dumps(inf)[:300])
    check("ACCEPT0 end to end: nothing differs -> the design sentence '31 of 31 registers matched at the review <age> ago.'",
          eq["word"] == "MATCHES SAVED PROFILE" and re.search(r"31 of 31 registers matched at the review .+ ago\.", eq["c2"]) and "Info-only" not in eq["c2"] and eq["markers"] == 0,
          json.dumps(eq)[:300])



# FB-B2: card mutants. Each entry breaks ONE decision of the guarded Save / Invalidate flow in a COPY of the card (a text
# replacement that must match the source exactly once); the node test named by (file, --test-name-pattern) must then FAIL.
# (id, what it breaks, old text, new text, test file, name of the killing test)
CARD_MUTANTS = [
    ('M01', 'the trusted-click guard is removed', '    if (ds.pass !== CLICK_PASS) return { sent: false, why: FLOW_TEXT.notAUserClick };\n', '', 'element', 'FB-B2 trusted clicks only'),
    ('M02', 'the click listener hands the pass to every click', 'this._onClick(e, e && e.isTrusted === true ? CLICK_PASS : null)', 'this._onClick(e, CLICK_PASS)', 'element', 'FB-B2 trusted clicks only'),
    ('M03', 'the click listener hands the pass to every click (real tree)', 'this._onClick(e, e && e.isTrusted === true ? CLICK_PASS : null)', 'this._onClick(e, CLICK_PASS)', 'dom', 'FB-B2 a click on the real button'),
    ('M04', 'the Save handler no longer compares the clicked ID with the current candidate ID', "    if (ds.id !== vm.reviewId || (ds.variant || 'save') !== gate.variant) {", '    if (false) {', 'element', 'FB-B2 Save is refused, with no call, unless the ID'),
    ('M05', 'the Save handler no longer compares the variant', "    if (ds.id !== vm.reviewId || (ds.variant || 'save') !== gate.variant) {", '    if (ds.id !== vm.reviewId) {', 'element', 'FB-B2 Save is refused, with no call, unless the ID'),
    ('M06', 'the Save handler sends without re-running the gate', '    if (!gate.allowed) return { sent: false, why: gate.why };\n    // FB-B2 (CARD-08): only the arm THIS card switched on for a save confirms a save (an arm on for any other reason has no panel)\n', '    // FB-B2 (CARD-08): only the arm THIS card switched on for a save confirms a save (an arm on for any other reason has no panel)\n', 'element', 'FB-B2 Save is refused at click time'),
    ('M07', "the Save button carries a fixed ID instead of the candidate's", 'data-act="save" data-fk="save" data-id="${esc(gate.id || \'\')}"', 'data-act="save" data-fk="save" data-id="0000000000000000"', 'render', 'FB-B2 confirmation panel: the candidate ID being confirmed'),
    ('M08', 'the click handler drops the ID of the clicked button', "      id: target.getAttribute('data-id'),\n", '      id: null,\n', 'dom', 'FB-B2 a click on the real button'),
    ('M09', 'an invalidate is sent with the 8-hex short ID', "buildServiceCall('invalidate', this._config, { id: vm.idHex })", "buildServiceCall('invalidate', this._config, { id: vm.idHex.slice(0, 8) })", 'element', 'FB-B2 Invalidate: its own arm'),
    ('M10', 'the REPLACE CORRUPT variant is never chosen', "  const replaceCorrupt = vm.prior === 'CORRUPT';", '  const replaceCorrupt = false;', 'core', 'FB-B2 save gate: REPLACE CORRUPT'),
    ('M11', 'the execute allow-list accepts any confirmation for SAVE', "    return action === 'SAVE' && confirmation === phraseFor(action, id, true);", '    return true;', 'core', 'FB-B2 allow-list'),
    ('M12', 'the execute allow-list accepts any action token', "    if (action !== 'SAVE' && action !== 'INVALIDATE') return false;\n", '', 'core', 'FB-B2 allow-list'),
    ('M13', 'the ID grammar accepts lower-case hex', 'const HEX16_RE = /^[0-9A-F]{16}$/;', 'const HEX16_RE = /^[0-9A-Fa-f]{16}$/;', 'core', 'FB-B2 service calls'),
    ('M14', 'the arm allow-list accepts any switch', '    return onlyEntity && !!config.entities.arm && data.entity_id === config.entities.arm;', '    return onlyEntity && !!config.entities.arm;', 'core', 'FB-B2 allow-list'),
    ('M15', 'the card spells the wrong execute service name', "export const EXECUTE_SERVICE = 'ecco_clock_dongle_fallback_profile_execute';", "export const EXECUTE_SERVICE = 'ecco_clock_dongle_fallback_profile_run';", 'core', 'FB-B2 service calls'),
    ('M16', 'the heartbeat gate no longer requires the state SUPERVISED', "  else if (stable && state === 'SUPERVISED') items.push(gateItem('heartbeat', 'pass', L.heartbeat, 'Stable'));", "  else if (stable) items.push(gateItem('heartbeat', 'pass', L.heartbeat, 'Stable'));", 'core', 'FB-B2 save gate: each prerequisite failing alone'),
    ('M17', 'an unknown item blocks even when the card does not need it', "export const itemBlocks = (it) => it.state === 'fail' || (it.state === 'unknown' && it.required);", "export const itemBlocks = (it) => it.state === 'fail' || it.state === 'unknown';", 'core', 'FB-B2 save gate: each prerequisite failing alone'),
    ('M18', 'an unknown required item (the arm entity unavailable) does not block', "export const itemBlocks = (it) => it.state === 'fail' || (it.state === 'unknown' && it.required);", "export const itemBlocks = (it) => it.state === 'fail';", 'core', 'FB-B2 save gate: each prerequisite failing alone'),
    ('M19', 'an unavailable arm is read as off', "  if (vm.arm.state === null) return gateItem('arm', 'unknown', L, FLOW_TEXT.armUnavailable, true);\n", '', 'core', 'FB-B2 save gate: each prerequisite failing alone'),
    ('M20', 'an expiring candidate is not a failing prerequisite', "  else if (tv.bucket === 'zero') items.push(gateItem('fresh', 'fail', L.fresh, T.candidateExpiring, true));\n", '', 'core', 'FB-B2 save gate: each prerequisite failing alone'),
    ('M21', 'the save is allowed with the arm off', '    allowed: blocking.length === 0,', '    allowed: other.length === 0,', 'core', 'FB-B2 save gate: each prerequisite failing alone'),
    ('M22', "a pending request does not make another operation 'in flight'", "  if (pending || vm.review === 'reading' || vm.review === 'saving') return gateItem('flow', 'fail', L, FLOW_TEXT.inFlight, true);", "  if (vm.review === 'reading' || vm.review === 'saving') return gateItem('flow', 'fail', L, FLOW_TEXT.inFlight, true);", 'core', 'FB-B2 save gate: each prerequisite failing alone'),
    ('M23', 'Invalidate is offered for a profile that is not VALID', "  const valid = vm.profile === 'saved' && vm.idHex !== null && vm.g !== null;", '  const valid = vm.idHex !== null && vm.g !== null;', 'core', 'FB-B2 invalidate gate'),
    ('M24', 'Invalidate does not cross-check the saved values against the record ID', '  else if (vm.savedOK && vm.ssl && vm.ssl.b === vm.idHex.slice(0, 8)) items.push(', '  else if (true) items.push(', 'core', 'FB-B2 invalidate gate'),
    ('M25', 'Arm Save is enabled although a prerequisite fails', '  if (!gate.allowedToArm) return { disabled: true, why: gate.whyToArm };\n', '', 'core', 'FB-B2 armButtonState'),
    ('M26', 'a second Save is sent while the first is pending', "    if (flowPendingKind(this._ui.flow)) return { sent: false, why: FLOW_TEXT.inFlight };\n    if (this._ui.intent === 'invalidate') return { sent: false, why: FLOW_TEXT.armForInvalidate };\n", "    if (this._ui.intent === 'invalidate') return { sent: false, why: FLOW_TEXT.armForInvalidate };\n", 'element', 'FB-B2 Save: exactly one execute call'),
    ('M27', 'Review is not held while a request is pending', 'act: flowPendingKind(this._ui.flow) });', 'act: null });', 'element', 'FB-B2 Save: exactly one execute call'),
    ('M28', 'a request never times out into a message', "  if (flow.state === 'sent' && s.nowMs - flow.atMs >= ACT_PENDING_TIMEOUT_MS) return { ...flow, state: 'timeout' };\n", '', 'element', 'FB-B2 Save: no answer'),
    ('M29', 'the arm turning off alone answers a request (no grace)', '  if (flow.armOn && s.armState === false && s.nowMs - flow.atMs >= ARM_OFF_GRACE_MS) return null;\n', '  if (flow.armOn && s.armState === false) return null;\n', 'core', 'FB-B2 request state'),
    ('M30', 'any state re-publish counts as the answer', '      review: vm ? vm.review : null,\n', '      review: this._lastReviewKey,\n', 'element', 'FB-B2 Save: exactly one execute call'),
    ('M31', 'the confirmation is optimistic (open as soon as the Arm button is pressed)', "vm.review === 'ready' && vm.arm.configured && vm.arm.state === true && ui.intent === 'save' && !savePending && !ui.cancelling;", "vm.review === 'ready' && vm.arm.configured && (vm.arm.state === true || ui.armPending) && ui.intent === 'save' && !savePending && !ui.cancelling;", 'element', 'FB-B2 Arm Save: one switch.turn_on'),
    ('M32', 'the confirmation stays open while the arm is being turned off', "ui.intent === 'save' && !savePending && !ui.cancelling;", "ui.intent === 'save' && !savePending;", 'render', 'FB-B2 confirmation panel: the candidate ID being confirmed'),
    ('M33', 'Cancel does not block a save while the arm is being turned off', '      this._cancelUntil = this._now() + ARM_PENDING_MS; // until Home Assistant reports it off, no confirm is offered\n', '', 'element', 'FB-B2 Cancel'),
    ('M34', 'Cancel sends turn_off although the arm is not on', "    if (this._vm.arm.state !== true) return { sent: false, why: 'The arm is not on' };\n", '', 'element', 'FB-B2 Cancel'),
    ('M35', 'Invalidate does not need the invalidate intent', "    if (this._ui.intent !== 'invalidate') return { sent: false, why: this._ui.intent === 'sent' ? FLOW_TEXT.armSpentWhy : FLOW_TEXT.armElsewhereWhy };\n", '', 'element', 'FB-B2 Invalidate is refused'),
    ('M36', 'the arm countdown starts from the wrong limit', 'export const ARM_TTL_S = 120;', 'export const ARM_TTL_S = 130;', 'core', 'FB-B2 arm countdown'),
    ('M37', 'the 1 Hz tick ignores the arm countdown', 'const needed = ((!!this._anchor && !stale) || (!!this._armAnchor && !armStale)) && this._connected && !hidden;', 'const needed = (!!this._anchor && !stale) && this._connected && !hidden;', 'element', 'FB-B2 timers'),
    ('M38', 'SAVE REFUSED is classified as SAVED', "  else if (/^SAVED\\b/.test(raw)) kind = 'saved';", "  else if (/^SAVE/.test(raw)) kind = 'saved';", 'core', 'FB-B2 B9 families'),
    ('M39', 'a save is called verified whatever generation B2 shows', "verified = b1 === 'VALID' && g !== null && b9.gen !== null && b9.gen === g && storageOk && (b2.op === 'SAVE' || b2.op === 'RC');", "verified = b1 === 'VALID';", 'core', 'FB-B2 B9 families'),
    ('M40', 'the expected generation is off by one', '  return Math.max(vm.g === null ? 0 : vm.g, vm.hw === null ? 0 : vm.hw) + 1;\n', '  return Math.max(vm.g === null ? 0 : vm.g, vm.hw === null ? 0 : vm.hw) + 2;\n', 'core', 'FB-B2 save gate: everything passing allows the save'),
    ('M41', 'Review stays enabled while the dongle is SAVING', "  if (vm.review === 'saving' || act === 'save') return { disabled: true, why: 'Save in progress' };", "  if (act === 'save') return { disabled: true, why: 'Save in progress' };", 'core', 'FB-B2 Review button and Live Match'),
    ('M42', "a click on the Invalidate confirmation panel falls through to the card's tap", 'data-act="stay" data-confirm="invalidate"', 'data-confirm="invalidate"', 'dom', 'FB-B2 clicks inside a confirmation panel'),
    ('M43', 'Arm Invalidate is offered for a profile that is not VALID', "  if (vm.profile === 'saved' && vm.arm.configured) {\n    const gate = invalidateGate(", '  if (vm.arm.configured) {\n    const gate = invalidateGate(', 'render', 'FB-B2 Saved profile card'),
    ('M44', 'a first save is described as replacing a profile', "    case 'NOT_CAPTURED':\n      out.kind = 'first';", "    case 'NOT_CAPTURED':\n      out.kind = 'replace';", 'core', 'FB-B2 save gate: everything passing allows the save'),
    ('M45', 'card 5 does not report what the live save gate refuses', '  } else if (gateFail) {\n    foot =', '  } else if (false) {\n    foot =', 'render', 'card 5: footer sentences and tone'),
    ('M46', 'an invalidate is called verified whatever generation B2 shows', "verified = b1 === 'INVALIDATED' && g !== null && b9.newGen !== null && b9.newGen === g && storageOk && b2.op === 'INV';", "verified = b1 === 'INVALIDATED';", 'core', 'FB-B2 B9 families'),
    ('M47', 'st=SAVING is not known again', "'CANDIDATE_NOT_SAVEABLE', 'SAVING']);", "'CANDIDATE_NOT_SAVEABLE']);", 'core', 'review state: B3 st first'),
    ('M48', 'st=INVALIDATING becomes a known status', "'CANDIDATE_NOT_SAVEABLE', 'SAVING']);", "'CANDIDATE_NOT_SAVEABLE', 'SAVING', 'INVALIDATING']);", 'core', 'review state: B3 st first'),
    ('M49', 'arming moves focus to the Save button instead of the confirmation heading', "this._focusOn(kind === 'invalidate' ? 'confirm-inv-title' : 'confirm-save-title');", "this._focusOn(kind === 'invalidate' ? 'confirm-inv-title' : 'save');", 'element', 'FB-B2 a click that arms moves focus'),
    ('M50', 'an execute call is allowed with no arm entity configured', '    if (!config.entities.arm) return false;\n    if (keys.length !== 3', '    if (keys.length !== 3', 'core', 'FB-B2 allow-list'),
    # card-fix: one mutant per finding of the independent safety audit (CARD-01 .. CARD-12); each fails the test that names it
    ('M51', 'CARD-01: the heartbeat gate treats a shown state that is not SUPERVISED as "unknown" when the stable entity is unavailable', "  if (stable === null && state !== null && state !== 'SUPERVISED') items.push(gateItem('heartbeat', 'fail', L.heartbeat, supervisionStateText(state)));\n  else if (stable === null)", "  if (false) items.push(gateItem('heartbeat', 'fail', L.heartbeat, supervisionStateText(state)));\n  else if (stable === null)", 'core', 'FB-B2 CARD-01'),
    ('M52', 'CARD-01: check 5 shows "Entity unavailable" for a shown state that is not SUPERVISED', "  if (vm.sup.stable === null && vm.sup.state !== null && vm.sup.state !== 'SUPERVISED') add('fail', L5, supervisionStateText(vm.sup.state));\n  else if (vm.sup.stable === null)", "  if (false) add('fail', L5, supervisionStateText(vm.sup.state));\n  else if (vm.sup.stable === null)", 'core', 'FB-B2 CARD-01'),
    ('M53', 'CARD-02: a title attribute carries a gate reason unescaped', 'const titleAttr = (text) => (text ? ` title="${esc(text)}"` : \'\');', 'const titleAttr = (text) => (text ? ` title="${text}"` : \'\');', 'render', 'FB-B2 CARD-02'),
    ('M54', 'CARD-02: a visible gate reason line is unescaped', 'const noteDiv = (text) => `<div class="caption warnnote">${esc(text)}</div>`;', 'const noteDiv = (text) => `<div class="caption warnnote">${text}</div>`;', 'render', 'FB-B2 CARD-02'),
    ('M55', 'CARD-02: a check / gate detail is printed unescaped', 'const withRem = (detail) => esc(detail).replace(', 'const withRem = (detail) => String(detail).replace(', 'render', 'FB-B2 CARD-02'),
    ('M56', 'CARD-03: a READY candidate whose time left is unknown does not block a save', "  else if (!tv || !tv.has) items.push(gateItem('fresh', 'unknown', L.fresh, 'Time left not known', true));\n", "  else if (!tv || !tv.has) items.push(gateItem('fresh', 'unknown', L.fresh, 'Time left not known', false));\n", 'core', 'FB-B2 CARD-03: a READY candidate'),
    ('M57', 'CARD-03: the REPLACE CORRUPT variant follows B1 instead of the candidate prior', "  const replaceCorrupt = vm.prior === 'CORRUPT';", "  const replaceCorrupt = vm.b1 === 'CORRUPT';", 'core', 'FB-B2 CARD-03: the REPLACE CORRUPT variant'),
    ('M58', 'CARD-03: the unknown-outcome guidance claims the save as done', "  saveUnknown:\n    'Do not press Save again.", "  saveUnknown:\n    'The profile was saved. Do not press Save again.", 'core', 'FB-B2 CARD-03: the unknown-outcome guidance'),
    ('M59', 'CARD-03: an unverified save is worded as verified', 'const lead = a.verified ? `${T.savedOk}', 'const lead = true ? `${T.savedOk}', 'render', 'FB-B2 CARD-03: no rendered text claims'),
    ('M60', 'CARD-03: the arm timer is never re-anchored by a new last_changed', '      if (keys.arm !== this._armKey || !this._armAnchor) {', '      if (!this._armAnchor) {', 'element', 'FB-B2 CARD-03: the arm timer is anchored'),
    ('M61', 'CARD-03: the fingerprint ignores last_changed', "parts.push(s ? `${s.state}|${s.last_changed || ''}` : '-');", "parts.push(s ? `${s.state}` : '-');", 'element', 'FB-B2 CARD-03: the arm timer is anchored'),
    ('M62', 'CARD-04: a Save attempt does not use the arm up (the confirmation can come back after a timeout)', "    this._ui.intent = 'sent';\n    this._flowSent(flow);\n", '    this._flowSent(flow);\n', 'element', 'FB-B2 CARD-04: after a timeout'),
    ('M63', 'CARD-04: an Invalidate attempt does not use the arm up', "    this._ui.intent = 'sent'; // FB-B2 (CARD-04): the attempt uses the arm up, as for a save\n", '', 'element', 'FB-B2 CARD-04: after a timeout'),
    ('M64', 'CARD-04: a Review press clears an unanswered request', "      // the dongle's answer does (B3 leaves what it was, or B9 changes). Review turns the arm off and replaces the candidate, so that answer follows.\n", "      // the dongle's answer does (B3 leaves what it was, or B9 changes). Review turns the arm off and replaces the candidate, so that answer follows.\n      this._ui.flow = null;\n", 'element', 'FB-B2 CARD-04: after a timeout'),
    ('M65', 'CARD-04: a Review press makes a spent arm look unspent', "      if (this._ui.intent !== 'sent') this._ui.intent = null;", '      this._ui.intent = null;', 'element', 'FB-B2 CARD-04: after a timeout'),
    ('M66', 'CARD-05: the arm staying off never ends a request', '  if (flow.armOn && s.armState === false && s.nowMs - flow.atMs >= ARM_OFF_GRACE_MS) return null;\n', '', 'core', 'FB-B2 CARD-05'),
    ('M67', 'CARD-06: attaching again does not re-arm the request timer', '    if (!force && !this._connected && !this._flowTimer) return;\n', '    if (!force) return;\n', 'element', 'FB-B2 CARD-06'),
    ('M68', 'CARD-07: a candidate whose values are not on screen can be saved', "  else if (!vm.candOK) items.push(gateItem('candidate', 'unknown', L.candidate, T.candValuesMissing, true));\n", '', 'core', 'FB-B2 CARD-07'),
    ('M69', 'CARD-07: a missing saved-profile summary does not block a save', "  else if (expectedGeneration(vm) === null) items.push(gateItem('stored', 'unknown', L.stored, T.summaryMissing, true));\n", '', 'core', 'FB-B2 CARD-07'),
    ('M70', 'CARD-07: a generation is derived from a missing summary', '  if (vm.b2 === null || vm.prior === null) return null;\n', '  if (vm.prior === null) return null;\n', 'core', 'FB-B2 CARD-07'),
    ('M71', 'CARD-08: the confirmation opens for an arm this card did not switch on for a save', "ui.intent === 'save' && !savePending && !ui.cancelling;", '!savePending && !ui.cancelling;', 'render', 'FB-B2 CARD-08'),
    ('M72', 'CARD-08: the strip calls an arm turned on elsewhere "Arm is on."', "ui.intent === 'sent' ? T.armSpent : T.armElsewhere;", "ui.intent === 'sent' ? T.armSpent : T.armIsOn;", 'render', 'FB-B2 CARD-08'),
    ('M73', 'CARD-08: a Save is sent for an arm this card did not switch on for a save', "    if (this._ui.intent !== 'save') return { sent: false, why: this._ui.intent === 'sent' ? FLOW_TEXT.armSpentWhy : FLOW_TEXT.armElsewhereWhy };\n", '', 'element', 'FB-B2 CARD-08'),
    ('M74', 'CARD-09: a look-alike pass object is accepted by the guard', '    if (ds.pass !== CLICK_PASS) return { sent: false, why: FLOW_TEXT.notAUserClick };\n', '    if (!ds.pass) return { sent: false, why: FLOW_TEXT.notAUserClick };\n', 'element', 'FB-B2 trusted clicks only'),
    ('M75', 'CARD-10: the configuration accepts one entity id for two keys', '    if (usedBy.has(v)) throw new Error(', '    if (false) throw new Error(', 'core', 'FB-B2 CARD-10'),
    ('M76', 'CARD-10: the allow-list does not check that the arm is its own entity', "  const armIsOwn = !config.entities.arm || Object.entries(config.entities).every(([k, v]) => k === 'arm' || v !== config.entities.arm);\n", '  const armIsOwn = true;\n', 'core', 'FB-B2 CARD-10'),
    ('M77', 'CARD-11: a save is called verified with a lagging witness or a storage error', "verified = b1 === 'VALID' && g !== null && b9.gen !== null && b9.gen === g && storageOk && (b2.op === 'SAVE' || b2.op === 'RC');", "verified = b1 === 'VALID' && g !== null && b9.gen !== null && b9.gen === g && (b2.op === 'SAVE' || b2.op === 'RC');", 'core', 'FB-B2 CARD-11'),
    ('M78', 'CARD-11: a save is called verified whatever the last operation was', "verified = b1 === 'VALID' && g !== null && b9.gen !== null && b9.gen === g && storageOk && (b2.op === 'SAVE' || b2.op === 'RC');", "verified = b1 === 'VALID' && g !== null && b9.gen !== null && b9.gen === g && storageOk;", 'core', 'FB-B2 CARD-11'),
    ('M79', 'CARD-11: an invalidate is worded as done although it is not verified', 'html: sentenceP(a.verified ? T.invalidatedOk : T.invalidatedUnverified)', 'html: sentenceP(T.invalidatedOk)', 'core', 'FB-B2 CARD-11'),
    ('M80', 'CARD-12: the focus is not handed to the outcome when the progress row goes', '    if (hadFocus && !flowPendingKind(this._ui.flow)) this._focusOn(', '    if (false) this._focusOn(', 'dom', 'FB-B2 CARD-12: the progress row'),
    ('M81', 'CARD-12: the candidate card heading cannot take focus', "head(word, false, 'act-result')", 'head(word)', 'dom', 'FB-B2 CARD-12: the progress row'),
    ('M82', 'CARD-08: card 5 says "Save is armed" for an arm this card did not switch on for a save', "  } else if (gate.allowed && ui.intent === 'save') {\n", '  } else if (gate.allowed) {\n', 'render', 'card 5: footer sentences and tone'),
]


def run_card_mutants() -> None:
    import concurrent.futures as cf
    import os
    import time

    node = shutil.which("node")
    if node is None:
        check("node is installed (REQUIRED to run the card mutants)", False, "install Node 20+ and re-run")
        return
    sibling_src = SIBLING / "src"

    def make_tree(base: Path, mutation=None) -> Path:
        dst = base / "frontend" / "ecco-fallback-recovery-card"
        shutil.copytree(CARD_DIR, dst, ignore=shutil.ignore_patterns("node_modules", "preview"))
        shutil.copytree(sibling_src, base / "frontend" / "ecco-energy-actions-card" / "src")
        js = dst / CARD_JS.name
        text = js.read_bytes().decode("utf-8").replace("\r\n", "\n")
        if mutation:
            old, new = mutation
            if text.count(old) != 1:
                raise AssertionError(f"the mutation anchor occurs {text.count(old)} times: {old[:60]!r}")
            text = text.replace(old, new)
        js.write_bytes(text.encode("utf-8"))
        return dst

    def run_pattern(dst: Path, fname: str, pattern: str):
        proc = subprocess.run([node, "--test", "--test-reporter=tap", f"--test-name-pattern={pattern}", f"test/{fname}.test.mjs"], cwd=str(dst),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        counts = {m.group(1): int(m.group(2)) for m in re.finditer(r"(?m)^# (tests|pass|fail) (\d+)\s*$", proc.stdout)}
        return proc.returncode, counts, re.findall(r"(?m)^not ok \d+ - (.*)$", proc.stdout)

    def one(m):
        mid, what, old, new, fname, pattern = m
        with tempfile.TemporaryDirectory() as td:
            try:
                dst = make_tree(Path(td), (old, new))
            except AssertionError as exc:
                return mid, what, fname, pattern, None, str(exc)
            rc, counts, failing = run_pattern(dst, fname, pattern)
            return mid, what, fname, pattern, rc != 0 and counts.get("fail", 0) > 0 and counts.get("tests", 0) >= 1, ", ".join(failing[:2])

    with tempfile.TemporaryDirectory() as td:
        dst = make_tree(Path(td))
        for fname, pattern in sorted({(f, pat) for _, _, _, _, f, pat in CARD_MUTANTS}):
            rc, counts, failing = run_pattern(dst, fname, pattern)
            check(f"unmutated card: {fname}.test.mjs '{pattern}' selects tests and passes", rc == 0 and counts.get("tests", 0) >= 1, f"{counts} {failing[:1]}")
    with cf.ThreadPoolExecutor(max_workers=max(2, min(4, os.cpu_count() or 2))) as pool:
        results = list(pool.map(one, CARD_MUTANTS))
    for mid, what, fname, pattern, killed, detail in results:
        check(f"mutant {mid} killed by {fname} '{pattern}': {what}", killed is True, "the mutation anchor is stale" if killed is None else "SURVIVED")
    n = sum(1 for r in results if r[4] is True)
    check(f"all {len(results)} card mutants are killed", n == len(results), f"{n}/{len(results)}")

    # FB-B2 card-fix (CARD-14): a FAILING assertion in a test that runs on real timers must fail fast. Before the fix such a test left a live 1 Hz
    # interval behind, `node --test` printed the failure and then never exited (a CI job would hang until its timeout). The mutant below makes the
    # rejected-call assertions of 'FB-B2 Save: no answer ...' fail; the run must END (non-zero) well inside the limit.
    old_hang = "      this._ui.flow = { ...flow, state: 'unsure' };\n"
    with tempfile.TemporaryDirectory() as td:
        try:
            dst = make_tree(Path(td), (old_hang, ""))
            started = time.monotonic()
            proc = subprocess.run([node, "--test", "--test-reporter=tap", "--test-name-pattern=FB-B2 Save: no answer", "test/element.test.mjs"], cwd=str(dst),
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
            took = time.monotonic() - started
            ended, detail = proc.returncode != 0 and re.search(r"(?m)^not ok \d+ - FB-B2 Save: no answer", proc.stdout) is not None, f"{took:.1f} s"
        except subprocess.TimeoutExpired:
            ended, detail = False, "node --test did not exit within 90 s (a live timer was left behind)"
        except AssertionError as exc:
            ended, detail = False, str(exc)
    check("CARD-14: a failing assertion in a real-timer test ends node --test promptly (no live timer is left behind)", ended, detail)


def main() -> int:
    # =====================================================================================================
    print("[1] the card folder")
    files = {
        "card module": CARD_JS, "README": CARD_DIR / "README.md", "package.json": CARD_DIR / "package.json",
        "hacs.json": CARD_DIR / "hacs.json", "preview": CARD_DIR / "preview" / "index.html",
        "scenarios fixture": FIXTURES / "scenarios.json", "scenario meta": FIXTURES / "scenario_meta.json",
        "core tests": CARD_DIR / "test" / "core.test.mjs", "render tests": CARD_DIR / "test" / "render.test.mjs",
        "element tests": CARD_DIR / "test" / "element.test.mjs", "string dump": CARD_DIR / "test" / "dump-strings.mjs",
        "DOM tests (real node trees)": CARD_DIR / "test" / "dom.test.mjs", "mini DOM": CARD_DIR / "test" / "minidom.mjs",
        "test helpers": CARD_DIR / "test" / "helpers.mjs", "obligation-vector check script": CARD_DIR / "test" / "check-obl.mjs",
    }
    for label, p in files.items():
        check(f"{label} exists ({p.relative_to(ROOT).as_posix()})", p.is_file())
    pkg = json.loads(read(CARD_DIR / "package.json"))
    check("package.json: type module, version, no dependencies of any kind",
          pkg.get("type") == "module" and pkg.get("version") and not any(k in pkg for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")))
    check("package.json: scripts.test runs node --test over test/*.test.mjs",
          re.fullmatch(r'node --test "?test/\*\.test\.mjs"?', pkg.get("scripts", {}).get("test", "")) is not None, str(pkg.get("scripts")))
    check("package.json has no build step", "build" not in pkg.get("scripts", {}))
    hacs = json.loads(read(CARD_DIR / "hacs.json"))
    sib = json.loads(read(SIBLING / "hacs.json"))
    check("hacs.json has the sibling's key set", set(hacs) == set(sib), f"{sorted(hacs)} vs {sorted(sib)}")
    check("hacs.json filename is the card module", hacs.get("filename") == CARD_JS.name)
    readme = read(CARD_DIR / "README.md")
    # FB-B2: the "Coming in FB-B2" placeholder is gone (the Save control is real), so that needle is replaced by the new flow
    for needle in ("/config/www/ecco/", "JavaScript Module", "custom:ecco-fallback-recovery-card", "sensor.example_review", "button.example_review_button", "technical_detail_entity",
                   "switch.example_arm", "Arm Save", "Arm Invalidate", "event.isTrusted", "esphome.ecco_clock_dongle_fallback_profile_execute", "hard refresh"):
        check(f"README mentions {needle!r}", needle in readme)
    # PUB0: in the public export DEVICE is the generic default slug, which the card's ESPHome SERVICE name legitimately contains
    # (esphome.ecco_clock_dongle_fallback_profile_execute; spec C.2 hazard 2). The private-slug ban stays verbatim (_pub0.PRIVATE_SLUG ==
    # DEVICE in the private tree, so there it is the original check) and every domain-qualified DEVICE entity id is banned as well.
    device_entity = re.compile(rf"(?<![\w.])(?!esphome\.)[a-z_]+\.{re.escape(DEVICE)}_")
    check("README spells no real entity id", _pub0.PRIVATE_SLUG not in readme and not device_entity.search(readme))
    src = read(CARD_JS)
    check("card source spells no real entity id or device slug", _pub0.PRIVATE_SLUG not in src and not device_entity.search(src)
          and _pub0.PRIVATE_AREA_PREFIX not in src)
    check("card module has a custom element, customCards registration and no import", "customElements.define(TAG" in src and "window.customCards" in src and not re.search(r"^\s*import\s", src, re.M))

    # =====================================================================================================
    print("[2] the dashboard view")
    dash_text = read(DASH)
    dash = yaml.safe_load(dash_text)
    views = dash["views"]
    titles = [v["title"] for v in views]
    fb = [i for i, v in enumerate(views) if v.get("path") == VIEW_PATH]
    check("exactly one view has the path", len(fb) == 1, str(fb))
    i = fb[0] if fb else -1
    # FB-B3: Safety is the ONLY view FB-B3 adds, and it sits immediately before Manual Controls, after Fallback / Recovery
    # PEX0 (O4): the two view-list pins below are FB-B3's pub0-era layout, so they read the dashboard AS OF pub0; the live adjacency
    # Fallback / Recovery -> Safety -> Manual Controls they carried stays a live check (the third check).
    _views0 = yaml.safe_load(_pex.as_of_pub0("home-assistant/dashboards/ecco_pro.yaml", dash_text))["views"]   # PEX0: the dashboard as of pub0
    _titles0 = [v["title"] for v in _views0]
    _i0 = next((n for n, v in enumerate(_views0) if v.get("path") == VIEW_PATH), -1)
    check("title order: ... Inverter / Advanced, Fallback / Recovery, Safety, Manual Controls (FB-B3: Safety is immediately before Manual Controls)",
          _i0 > 0 and _titles0[_i0 - 1] == "Inverter / Advanced" and _titles0[_i0] == VIEW_TITLE and _titles0[_i0 + 1] == SAFETY_TITLE
          and _titles0[_i0 + 2] == "Manual Controls" and _titles0[-1] == "Manual Controls", str(_titles0))
    check("the original eight views keep their relative order and Safety is the only new view (ten views in total)",
          [t for t in _titles0 if t not in (VIEW_TITLE, SAFETY_TITLE)] == ["Overview", "Intelligence", "Tariffs", "Control", "Recommended", "System", "Inverter / Advanced", "Manual Controls"]
          and len(_titles0) == 10 and _titles0.count(SAFETY_TITLE) == 1 and [v.get("path") for v in _views0].count("ecco-safety") == 1, str(_titles0))
    check("live: Fallback / Recovery, Safety and Manual Controls are consecutive views in this order, Safety exactly once (PEX0: the live part of the FB-B3 placement)",
          i > 0 and titles[i:i + 3] == [VIEW_TITLE, SAFETY_TITLE, "Manual Controls"] and titles.count(SAFETY_TITLE) == 1
          and [v.get("path") for v in views].count("ecco-safety") == 1, str(titles))
    view = views[i]
    check("view keys are exactly the sections-view keys of the other views", set(view) == {"title", "path", "icon", "type", "max_columns", "dense_section_placement", "sections"}, str(sorted(view)))
    check("view path / icon / type / max_columns / dense_section_placement", (view["path"], view["icon"], view["type"], view["max_columns"], view["dense_section_placement"]) == (VIEW_PATH, VIEW_ICON, "sections", 4, True))
    sections = view["sections"]
    check("one section, a grid of column_span 4", len(sections) == 1 and sections[0].get("type") == "grid" and sections[0].get("column_span") == 4)
    cards = sections[0]["cards"]
    check("the section holds a heading card then the custom card", [c.get("type") for c in cards] == ["heading", CARD_TYPE], str([c.get("type") for c in cards]))
    heading, fbcard = cards
    check("heading card: title, icon, ECCO heading style", heading.get("heading") == VIEW_TITLE and heading.get("icon") == VIEW_ICON and heading.get("heading_style") == "title")
    badges = heading.get("badges", [])
    badge_ids = {b.get("entity") for b in badges}
    check("heading badges are the three entity badges (supervision, NTP, write lock) with no actions",
          badge_ids == {expected_id("supervision_stable"), expected_id("ntp_synced"), expected_id("write_lock")}
          and all(b.get("type") == "entity" and set(b) <= {"type", "entity", "name", "show_state", "color"} for b in badges))
    check("heading and card use the full row", heading.get("grid_options") == {"columns": 48, "rows": "auto"} and fbcard.get("grid_options") == {"columns": 48, "rows": "auto"})
    check("card config keys are known", set(fbcard) <= {"type", "title", "show_header", "entities", "technical_detail_entity", "grid_options"}, str(sorted(fbcard)))
    check("the dashboard hides the card's own header (the heading card carries title and badges)", fbcard.get("show_header") is False)

    # =====================================================================================================
    print("[3] entity ids follow the firmware name derivation")
    ents = fbcard.get("entities", {})
    check("the config has exactly the nineteen entity keys (FB-B2: the ten FB-B1 ids, five base entities, the arm and three read-only write arms)",
          set(ents) == set(ENTITIES) and len(ENTITIES) == 19, str(sorted(set(ents) ^ set(ENTITIES))))
    for key in ENTITIES:
        check(f"entities.{key} == {expected_id(key)}", ents.get(key) == expected_id(key), str(ents.get(key)))
    check("every id is unique", len(set(ents.values())) == len(ents))
    fw_text = read(FIRMWARE)
    fw_names = set(re.findall(r'^\s*name:\s*"([^"\n]+)"\s*$', fw_text, re.M))
    for key in BASE_KEYS:
        check(f"firmware declares the base entity name {ENTITIES[key][1]!r}", ENTITIES[key][1] in fw_names)
    fb_names = {n for n in fw_names if n.startswith("ECCO Fallback Profile")}
    expected_fb = {ENTITIES[k][1] for k in ENTITIES if k not in BASE_KEYS}
    fb_b1_names = expected_fb - {ENTITIES["arm"][1]}
    # FB-B2 (AW-2): the firmware declares every Fallback Profile entity, the arm switch and the execute action now, so their PRESENCE is a hard
    # check. The FB-B1 form ("where already declared", an INFO line when none is) and the FB-B2 form ("the arm exists exactly when the action
    # does") both passed vacuously against a firmware that declared neither. [16] pins the rest of that surface and carries the negative controls.
    # FB-B3 Slice A: the firmware also declares the Live Match text sensor (B10). The card does not consume it yet (the HA / dashboard
    # slices do), so it is the ONE named firmware-only extra; any other extra name still fails.
    fb_names -= {"ECCO Fallback Profile Live Match"}
    check("firmware FB-B names are exactly the contract names: none extra, none missing (the ten FB-B1 names and the arm)", fb_names == expected_fb, str(sorted(fb_names ^ expected_fb)))
    check("all ten FB-B1 names are declared by the firmware", fb_b1_names <= fb_names, str(sorted(fb_b1_names - fb_names)))
    check("the firmware declares the arm switch name", ENTITIES["arm"][1] in fw_names)
    check("the firmware declares the fallback_profile_execute api action", bool(re.search(r"(?m)^[ \t]*-[ \t]*action:[ \t]*fallback_profile_execute[ \t]*$", fw_text)))

    # =====================================================================================================
    print("[4] service-call hygiene: the Review button, and (FB-B2) the arm switch ids as config values only")
    start = dash_text.index(f"  - title: {VIEW_TITLE}\n")
    end = dash_text.index(f"  - title: {SAFETY_TITLE}\n")      # FB-B3: the Safety view follows this view immediately
    check("FB-B3: the Safety view starts exactly where the Fallback / Recovery view ends and Manual Controls follows it",
          dash_text.index("  - title: Manual Controls\n") > end > start, "")
    view_text = dash_text[start:end]
    vstrings = strings_in(view)
    buttons = {s for s in vstrings if s.startswith("button.")}
    check("the only button.* id in the view is the Review button", buttons == {expected_id("review_button")}, str(buttons))
    domains = {s.split(".")[0] for s in vstrings if re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", s) and not s.startswith("mdi:")}
    # FB-B2: switch entities are referenced too (the arm and the three write arms), as values of `entities:` keys only
    check("the view references only sensor, binary_sensor, button and (FB-B2) switch entities", domains <= {"sensor", "binary_sensor", "button", "switch"}, str(domains))
    for tok in ("script.", "esphome.", "input_boolean.", "automation.", "number.", "select.", "homeassistant."):
        check(f"no {tok}* reference in the view text", tok not in view_text)
    switch_ids = re.findall(r"switch\.[a-z0-9_]+", view_text)
    arm_ids = {expected_id(k) for k in ARM_KEYS}
    check("FB-B2: the only switch.* ids in the view text are the four configured arm ids, each exactly once", sorted(switch_ids) == sorted(arm_ids), str(switch_ids))
    stray = [(k, v) for x in walk(view) if isinstance(x, dict) for k, v in x.items() if isinstance(v, str) and v.startswith("switch.") and k not in ARM_KEYS]
    check("FB-B2: a switch id appears only as the value of the arm, free_power_arm, dump_arm or manual_arm key", not stray, str(stray))
    check("FB-B2: the card config names the arm keys under entities: only", all(k in ents for k in ARM_KEYS) and not any(k in fbcard for k in ARM_KEYS))
    for tok in ("fallback_profile_execute", "perform_action", "call-service", "tap_action", "hold_action", "double_tap_action", "service:", "action:", "button.press", "confirmation"):
        check(f"the view text contains no {tok!r}", tok not in view_text)
    keys = {k for x in walk(view) if isinstance(x, dict) for k in x}
    check("no action-like key anywhere in the view", not keys & {"tap_action", "hold_action", "service", "action", "perform_action", "service_data", "target"}, str(keys & {"tap_action", "service", "action"}))
    check("technical_detail_entity is absent (no helper exists in FB-B1) or an input_boolean", fbcard.get("technical_detail_entity") in (None,) or str(fbcard.get("technical_detail_entity")).startswith("input_boolean."))
    for tok in FP_TOKENS:
        check(f"the view does not contain the FP-recovery token {tok[:12]}...", tok not in view_text)
    calls = re.findall(r"\bcallService\s*\(", src)
    check("the card source calls hass.callService in exactly one place", len(calls) == 1, str(len(calls)))
    check("the card guards that call with an allowlist", "isAllowedServiceCall(call, this._config)" in src)
    # FB-B2: the allowed service domains grew by exactly `switch` (the arm, turn_on / turn_off) and `esphome` (the execute action)
    for needle in ("'button'", "'press'", "'input_boolean'", "'toggle'", "'switch'", "'turn_on'", "'turn_off'", "'esphome'"):
        check(f"the card source builds its calls with {needle}", needle in src)
    check("the card source has no script / number / select / homeassistant / automation service domain", not re.search(r"domain:\s*'(script|number|select|homeassistant|automation)'", src))
    check("FB-B2: the card's service domains are exactly button, input_boolean, switch and esphome", set(re.findall(r"domain:\s*'([a-z_]+)'", src)) == {"button", "input_boolean", "switch", "esphome"}, str(set(re.findall(r"domain:\s*'([a-z_]+)'", src))))
    second_route = re.findall(
        r"\b(?:callWS|callApi|callWebSocket|sendMessage|subscribeMessage|subscribeEvents|call_service)\b|hass-action|hass-toggle-menu|\bfetch\b|XMLHttpRequest|WebSocket|sendBeacon|\beval\b|new Function",
        src,
    )
    check("the card source has no second route to Home Assistant (callWS, callApi, sendMessage, call_service, hass-action, fetch, XMLHttpRequest, WebSocket, eval)", not second_route, str(second_route))
    hass_members = set(re.findall(r"(?<![A-Za-z0-9])_?hass\.(\w+)", src))
    check("the card source names only the allowed hass members (states, locale, config, language, callService)", hass_members <= {"states", "locale", "config", "language", "callService"}, str(sorted(hass_members)))
    check("the only event the card dispatches is hass-more-info", re.findall(r"new CustomEvent\('([^']+)'", src) == ["hass-more-info"] and src.count("dispatchEvent(") == 1)

    # =====================================================================================================
    print("[5] the first energy-actions card in document order is still the Dump-to-Grid schedule card")
    first = next((x for x in walk(dash) if isinstance(x, dict) and x.get("type") == ACTIONS_CARD), None)
    check("an energy-actions card exists", first is not None)
    check("the first one carries dump_to_grid.schedule", first is not None and isinstance(first.get("dump_to_grid", {}).get("schedule"), dict))
    owner = next((n for n, v in enumerate(views) if any(isinstance(x, dict) and x is first for x in walk(v))), -1)
    check("it lives in a view before the new one", owner != -1 and owner < i, f"view {owner} vs {i}")
    check("the new view holds no energy-actions card", not any(isinstance(x, dict) and x.get("type") == ACTIONS_CARD for x in walk(view)))

    # =====================================================================================================
    print("[6] wording hygiene (energy-actions regexes parsed from the TypeScript, plus the two forbidden words)")
    regexes = card_regexes()
    check("regex literals were parsed from the actions card source", len(regexes) >= 10, str(len(regexes)))
    origins = {o for _, o in regexes}
    check("the three state files are among the sources", {"freePowerState.ts", "dumpState.ts", "recoveryPresentation.ts"} <= origins, str(origins))
    dumped = run_node([str(CARD_DIR / "test" / "dump-strings.mjs")], timeout=120)
    if dumped is None:
        check("node is installed (needed to dump the card strings)", False, "node not found on PATH")
        dump = {"regs": [], "classes": {}, "scenarios": [], "texts": []}
    else:
        check("the string dump runs", dumped.returncode == 0, dumped.stderr[-300:])
        dump = json.loads(dumped.stdout) if dumped.returncode == 0 else {"regs": [], "classes": {}, "scenarios": [], "texts": []}
    check("a large set of rendered strings was dumped", len(dump["texts"]) > 400, str(len(dump["texts"])))
    texts = list(dump["texts"]) + [s for s in vstrings if not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+|mdi:[a-z-]+|custom:[a-z-]+", s)]
    hits = [(t, o) for t in texts for rx, o in regexes if rx.search(t)]
    check("no card or view string matches an energy-actions regex", not hits, str(hits[:3]))
    bad = [t for t in texts for rx in NEVER if rx.search(t)]
    check("no card or view string contains the two forbidden words", not bad, str(bad[:3]))
    busy = [t for t in texts if re.match(r"(?i)(restoring|starting|activation verify)", t)]
    check("no status string starts with a busy-classifier word", not busy, str(busy[:3]))
    fixtures = json.loads(read(FIXTURES / "scenarios.json"))
    b9_hits = [(n, s["last_result"]) for n, s in fixtures.items() for rx, _ in regexes if rx.search(s["last_result"])]
    check("no fixture B9 text matches an energy-actions regex", not b9_hits, str(b9_hits[:2]))

    # =====================================================================================================
    print("[7] the 31-row register table equals the FB-A struct order")
    header = read(HEADER)
    body = re.search(r"struct FallbackProfileV1 \{(.*?)\n\};", header, re.S).group(1)
    header_fields = re.findall(r"uint\d+_t\s+(reg\d+(?:_\d+)?)", body)
    mirror_fields = [name for name, _fmt, _n in fp.PROFILE_LAYOUT if name.startswith("reg")]
    check("header struct and Python mirror list the same register fields in the same order", header_fields == mirror_fields, f"{header_fields} vs {mirror_fields}")
    expected_regs = [r for f in mirror_fields for r in fp.PROFILE_REGISTER_FIELDS[f]]
    check("31 registers in the FB-A order (244, 256-261, 268-273, 274-279, 232, 243, 248, 250-255, 230, 245, 247)", len(expected_regs) == 31 and expected_regs[:2] == [244, 256] and expected_regs[-3:] == [230, 245, 247])
    check("the card's REGS order equals it", dump["regs"] == expected_regs, str(dump["regs"]))
    cls_names = {fp.REG_E1: "E1", fp.REG_CTX: "CTX", fp.REG_INFO: "INFO"}
    check("the card's register classes equal the FB-A register table", {int(k): v for k, v in dump["classes"].items()} == {r: cls_names[fp.register_class(r)] for r in expected_regs})

    # =====================================================================================================
    print("[8] banned tokens, encoding and self-containment of the card folder")
    leaks, mojibake, ctrl, shadow, design_refs = [], [], [], [], []
    for p in sorted(CARD_DIR.rglob("*")):
        if not p.is_file():
            continue
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            mojibake.append(p.name)
            continue
        rel = p.relative_to(ROOT).as_posix()
        if BANNED.search(text):
            leaks.append(rel)
        if SHADOW in text:
            shadow.append(rel)
        if DESIGN_REFS.search(text):
            design_refs.append(rel)
        if any(ch in text for ch in (chr(0x00C2), chr(0x00C3), chr(0xFFFD))):
            mojibake.append(rel)
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in text):
            ctrl.append(rel)
        for rx in NEVER:
            if rx.search(text):
                leaks.append(f"{rel} (forbidden word)")
    check("no banned entity-id token in any card file", not leaks, str(leaks))
    check("no FB-C shadow token in any card file", not shadow, str(shadow))
    check("no card file names a design document path or file (the saved design is not part of this change set)", not design_refs, str(design_refs))
    check("no mojibake marker in any card file", not mojibake, str(mojibake))
    check("no stray control character in any card file", not ctrl, str(ctrl))
    check("the card folder has no node_modules and no dist", not (CARD_DIR / "node_modules").exists() and not (CARD_DIR / "dist").exists())
    check("the card source has no network access or dynamic evaluation", not re.search(r"\bfetch\b|XMLHttpRequest|WebSocket|sendBeacon|\beval\b|new Function|https?://", src))

    # =====================================================================================================
    print("[9] YAML parses and CRLF working-tree files stay pure CRLF")
    for p in (DASH, MANIFEST):
        raw = p.read_bytes()
        crlf, lf = raw.count(bytes([13, 10])), raw.count(bytes([10]))
        check(f"{p.relative_to(ROOT).as_posix()} is pure CRLF (or pure LF)", crlf == lf or crlf == 0, f"{crlf} CRLF / {lf} LF")
        check(f"{p.name} parses with yaml.safe_load", isinstance(yaml.safe_load(raw.decode("utf-8")), dict))
    check("the dashboard header comment (version) is untouched", dash_text.startswith("# ECCO Pro Dashboard v7.16.0"))
    check("the dashboard still defines the card_mod anchor exactly once", dash_text.count("&ecco_card_mod") == 1)

    # =====================================================================================================
    print("[10] the manifest carries one new frontend_assets stanza")
    man_text = _pex.as_of_pub0("deployment/ha-manifest.yaml", read(MANIFEST))   # PEX (acfg1): FB-B1's stanza pins are pub0-era (acfg1 adds a third asset)
    man = yaml.safe_load(man_text)
    assets = man["frontend_assets"]
    mine = [a for a in assets if "ecco-fallback-recovery-card" in a.get("source", "")]
    theirs = [a for a in assets if "ecco-energy-actions-card" in a.get("source", "")]
    check("exactly one stanza for the new card and the actions-card stanza is untouched", len(mine) == 1 and len(theirs) == 1 and len(assets) == 2, str(len(assets)))
    if mine and theirs:
        m = mine[0]
        check("same key set as the actions-card stanza", set(m) == set(theirs[0]), str(sorted(m)))
        check("source / destination / url", (m["source"], m["destination"], m["resource_url"]) == ("frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js", "/config/www/ecco/ecco-fallback-recovery-card.js", "/local/ecco/ecco-fallback-recovery-card.js"))
        check("method / restart / registration copy the actions-card stanza", (m["method"], m["restart_required"], m["resource_registration"]) == (theirs[0]["method"], theirs[0]["restart_required"], theirs[0]["resource_registration"]) and m["resource_registration"] == "manual")
        check("the source file exists", (ROOT / m["source"]).is_file())
    check("the manifest names the new card only in its one stanza (four mentions: source twice, destination, url)", man_text.count("ecco-fallback-recovery-card") == 4, str(man_text.count("ecco-fallback-recovery-card")))
    check("the stanza comment says review-only and NOT deployed", "read-only review" in man_text and "NOT deployed" in man_text)

    # =====================================================================================================
    print("[11] fixture strings follow the CONTRACT grammars")
    meta = json.loads(read(FIXTURES / "scenario_meta.json"))
    check("fixtures and meta list the same scenarios", set(fixtures) == set(meta))
    mockup = {"idle_saved", "reading", "ready_match", "ready_diff", "ready_expiring", "ready_nosup", "not_saveable", "mismatch", "read_error", "refused", "expired", "cleared", "not_captured", "not_captured_cand", "invalidated", "unusable", "unavailable"}
    check("every mockup scenario is present", mockup <= set(fixtures), str(mockup - set(fixtures)))
    check("every scenario has all nineteen entity keys", all(set(s) == set(ENTITIES) for s in fixtures.values()))
    check("FB-B2: the arm states of the fixtures are on, off or unavailable", all(s[k] in ("on", "off", "unavailable") for s in fixtures.values() for k in ARM_KEYS))
    exempt = {n for n, m in meta.items() if m.get("offGrammar")}
    check("only the two deliberately malformed scenarios are exempt from the grammar", exempt == {"malformed_review", "st_unrecognised"}, str(exempt))
    bad = []
    for name, s in fixtures.items():
        if name in exempt or all(v == "unavailable" for v in s.values()):
            continue
        for key, rx in (("profile_state", RE_B1), ("summary", RE_B2), ("review", RE_B3), ("review_id", RE_B4), ("review_slots", RE_B5), ("review_context", RE_B6), ("saved_slots", RE_B7), ("saved_context", RE_B8)):
            v = s[key]
            if v in ("unavailable", "unknown"):
                continue
            if len(v) > 200 or not rx.match(v):
                bad.append(f"{name}.{key}")
        if not s["last_result"].startswith(B9_PREFIXES) or len(s["last_result"]) > 200:
            bad.append(f"{name}.last_result")
    check("every entity string matches its grammar, prefix set and 200-char cap", not bad, str(bad[:6]))
    sem = []
    for name, s in fixtures.items():
        if name in exempt or not RE_B3.match(s["review"]):
            continue
        b3 = kv(s["review"])
        cand = b3["st"] in ("CANDIDATE_READY", "CANDIDATE_NOT_SAVEABLE")
        if cand != (b3["exp"] != "-") or cand != (b3["prior"] != "-"):
            sem.append(f"{name}: exp/prior only while a candidate exists")
        if cand and int(b3["exp"]) > 120:
            sem.append(f"{name}: exp > 120")
        if (s["review_id"] != "-") != (b3["st"] == "CANDIDATE_READY"):
            sem.append(f"{name}: B4 ID only while CANDIDATE_READY")
        if b3["st"] in ("IDLE", "READING") and b3["sv"] != "-":
            sem.append(f"{name}: sv set without a candidate")
        if not RE_B5.match(s["review_slots"]) or not RE_B6.match(s["review_context"]):
            continue
        b5, b6 = kv(s["review_slots"]), kv(s["review_context"])
        if (b5["v"] == "CAND") != cand or (b6["v"] == "CAND") != cand:
            sem.append(f"{name}: B5/B6 v=CAND iff a candidate exists")
        for ent in (b5, b6):
            if ent["v"] == "NONE" and any(v != "-" for k, v in ent.items() if k != "v"):
                sem.append(f"{name}: NONE form must be all '-'")
        if b5["v"] == "CAND":
            slots_starts = [int(b5[str(n)].split("/")[0]) for n in range(1, 7)]
            if (b6["ring"] == "OK") != ring_ok(slots_starts):
                sem.append(f"{name}: ring does not match the slot starts")
            sv_saved, sc_saved = kv(s["saved_slots"]), kv(s["saved_context"])
            if (b5["dx"] != "-") != (sv_saved["v"] == "SAVED"):
                sem.append(f"{name}: dx is '-' iff there is no authentic saved profile")
            elif b5["dx"] != "-":
                got = masks(words(b5, b6), words(sv_saved, sc_saved))
                if got != (b5["dx"], b6["dc"], b6["di"]):
                    sem.append(f"{name}: masks {(b5['dx'], b6['dc'], b6['di'])} != recomputed {got}")
        bs, bc = kv(s["saved_slots"]) if RE_B7.match(s["saved_slots"]) else None, kv(s["saved_context"]) if RE_B8.match(s["saved_context"]) else None
        if bs and bc and bs["v"] == "SAVED":
            if (bc["ring"] == "OK") != ring_ok([int(bs[str(n)].split("/")[0]) for n in range(1, 7)]):
                sem.append(f"{name}: saved ring mismatch")
            if bs["b"] != bc["b"] or bs["b"] == "-":
                sem.append(f"{name}: b= must agree between B7 and B8")
        if bs and bs["v"] == "NONE" and (bc is None or bc["v"] != "NONE"):
            sem.append(f"{name}: B7/B8 NONE together")
    check("fixture semantics (candidate-only B3 keys, B4, NONE forms, ring, masks, b=) hold", not sem, str(sem[:6]))
    all_b1 = {s["profile_state"] for s in fixtures.values()}
    check("every B1 class has a fixture", set(CLASSES.split("|")) <= all_b1, str(set(CLASSES.split("|")) - all_b1))

    # =====================================================================================================
    print("[12] the card's node tests pass")
    node = shutil.which("node")
    check("node is installed (REQUIRED to run the card tests)", node is not None, "install Node 20+ and re-run")
    if node is not None:
        ver = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        print(f"  INFO  node {ver} ({node})")
        test_files = sorted((CARD_DIR / "test").glob("*.test.mjs"))
        check("four node test files (core, render, element, dom)", {f.name for f in test_files} >= {"core.test.mjs", "render.test.mjs", "element.test.mjs", "dom.test.mjs"}, str([f.name for f in test_files]))
        res = run_node(["--test", "--test-reporter=tap", *[str(f) for f in test_files]], timeout=900)
        counts = {m.group(1): int(m.group(2)) for m in re.finditer(r"(?m)^# (tests|pass|fail|cancelled|skipped) (\d+)\s*$", res.stdout)}
        check("node --test exits 0", res.returncode == 0, (res.stdout + res.stderr)[-600:])
        # FB-B2: the floor rises from 120 (FB-B1 had 144 tests) to 215 (the FB-B2 card has 222 tests, none removed): the new flow's tests may not be dropped silently.
        check("node reports at least 215 tests, all passing, none failing or cancelled", counts.get("tests", 0) >= 215 and counts.get("pass") == counts.get("tests") and counts.get("fail") == 0 and counts.get("cancelled", 0) == 0, str(counts))

    # =====================================================================================================
    print("[13] cross-check against the firmware mirror (registry/fallback_capture.py) - the import is mandatory")
    try:
        import fallback_capture as fc  # noqa: E402

        fc_error = ""
    except Exception as exc:  # an ImportError, but also a SyntaxError or NameError inside the mirror: all are failures here
        fc, fc_error = None, f"{type(exc).__name__}: {exc}"
    check("registry/fallback_capture.py imports (this cross-check is never skipped)", fc is not None, fc_error)
    if fc is not None:
        try:
            cross_check_mirror(fc, fixtures, exempt)
        except (AttributeError, TypeError, ValueError, KeyError, IndexError) as exc:
            check("the mirror cross-check ran to completion (the mirror still has every name this test uses)", False, f"{type(exc).__name__}: {exc}")
        # FB-B2: the Save / Invalidate texts of registry/fallback_save.py. The import is mandatory as well.
        try:
            import fallback_durable as fd_mod  # noqa: E402
            import fallback_save as fs_mod  # noqa: E402

            fs_error = ""
        except Exception as exc:
            fs_mod, fd_mod, fs_error = None, None, f"{type(exc).__name__}: {exc}"
        check("registry/fallback_save.py imports (this cross-check is never skipped)", fs_mod is not None, fs_error)
        if fs_mod is not None:
            try:
                cross_check_save_mirror(fs_mod, fc, fd_mod)
            except (AttributeError, TypeError, ValueError, KeyError, IndexError) as exc:
                check("the save mirror cross-check ran to completion (the mirror still has every name this test uses)", False, f"{type(exc).__name__}: {exc}")

    # =====================================================================================================
    print("[14] README: deviations from the mockup are documented; no claim that the deploy tooling copies the card")
    check("README has a 'Deviations from the mockup' section", re.search(r"(?m)^## Deviations from the mockup\s*$", readme) is not None)
    section = re.search(r"(?ms)^## Deviations from the mockup\s*$(.*?)(?=^## |\Z)", readme)
    body_text = section.group(1) if section else ""
    flat = re.sub(r"\s+", " ", readme)                  # the README wraps its lines: phrases are matched on whitespace-collapsed text
    body_flat = re.sub(r"\s+", " ", body_text)
    for needle in ("slot table", "Review button", "44 px", "container", "tab order", "Candidate and Save readiness", "details", "45"):
        check(f"the deviations section covers {needle!r}", needle.lower() in body_text.lower())
    # final review ACCEPT0 / ACCEPT5 / FW0: the three deviations the first version of the README did not state
    for label, needles in (
        ("ACCEPT5: the card is ONE custom element with its own responsive grid (spans -> CSS grid, per-card visibility copies -> CSS order)", ("one custom element", "responsive grid", "spans", "css `order`")),
        ("ACCEPT5: the phone fold target (status row above the fold, each card at most 160 px) is not met: 216 to 394 px per status card at 390 px, the mockup misses it too", ("fold", "160 px", "216 to 394 px", "390 px", "mockup misses")),
        ("ACCEPT0: Live Match does not say '31 of 31' while info-only registers differ (the design wording contradicts itself)", ("31 of 31", "info-only", "contradict", "all compared settings and context matched")),
        ("FW0: a stored profile the firmware does not trust is 'not compared'", ("unreadable", "not compared", "not trusted")),
    ):
        check(f"the deviations section states {label}", all(n.lower() in body_flat.lower() for n in needles), str([n for n in needles if n.lower() not in body_flat.lower()]))
    check("README references the saved design as 'kept with the architecture docs, not part of this change set' and names no design file",
          "kept with the architecture docs, not part of this change set" in flat and not DESIGN_REFS.search(readme))
    check("README documents the Live Match wording table and the untrusted-profile rule outside the deviations list",
          "### Live Match wording" in readme and "### A stored profile the firmware does not trust" in readme)
    check("README states the countdown lingers up to one 10 s tick after 120 s", "up to about 10 s after 120 s" in flat, "10 s tick sentence missing")
    check("README says Node 20 or newer is a requirement of the repository check", "Node (version 20 or newer) a requirement of the repository check" in flat, "Node requirement sentence missing")
    check("README does not claim the bundle tooling copies the card", "bundle" not in readme.lower())
    check("README says copying and resource registration are manual", "manual" in readme.lower() and "frontend_assets" in readme)
    check("README documents that check 4 is not live outside a review", "not live" in readme)
    # FB-B2: the safety model the operator and the reviewer rely on is written down
    for label, needles in (
        ("the guarded Save flow (arm, confirmation panel, one request, no retry)", ("Arm Save", "confirmation panel", "one-shot", "never retries")),
        ("the trusted-click guard and its honest limit", ("event.isTrusted", "script-made", "safety authority")),
        ("what the dongle enforces", ("arm", "ID", "phrase", "120 s", "REPLACE CORRUPT")),
        ("the cache note for a deployed card", ("hard refresh", "?v=")),
        ("the manifest comment is still the FB-B1 one", ("manifest", "read-only review")),
        # FB-B2 card-fix: the audit follow-ups (CARD-01 .. CARD-14) and the places where the card goes beyond or differs from the brief
        ("the trusted-click claim as the code does it (CARD-09)", ("technical-detail toggle do not need one", "module-private pass", "script-made")),
        ("what ends a pending request, and that the confirmation does not come back (CARD-04, 05, 06)", ("answer by itself", "the confirmation does not come back", "detached and attached again", "does not clear an unanswered request")),
        ("whose arm it is (CARD-08)", ("Arm was turned on elsewhere", "neither panel opens")),
        ("what 'saved and verified' needs (CARD-11)", ("w=OK", "werr=-", "op=RC")),
        ("one entity id per key (CARD-10)", ("one entity id may serve only one key",)),
        ("the candidate values and the summary are needed (CARD-07)", ("unknown and blocking", "cannot be shown")),
        ("the focus hand-over (CARD-12)", ("focus moves to the result heading",)),
        ("CARD-13 is recorded as an owner item", ("CARD-13", "pinned artifact")),
    ):
        check(f"README states {label}", all(n.lower() in flat.lower() for n in needles), str([n for n in needles if n.lower() not in flat.lower()]))

    # =====================================================================================================
    print("[15] the dashboard edit is exactly one inserted view (final review CHAIN2)")
    # The file is not hash-pinned by the scope chain and banned_files is a whole-file allowlist with no count, so an edit to existing
    # dashboard content outside the new view would pass every other suite. Cut the view out EXACTLY - from its '  - title: Fallback /
    # Recovery' line up to (not including) the '  - title: Manual Controls' line, in LF text - and compare with the pre-FB-B1 file.
    # PUB0: the FB-C3 / FB-B3 hunks and every hash below are the private dashboard's; in the public export they run on its exact private text.
    # PEX0: every pin of this section is the FB-C3 / FB-B3 / FB-B1 history of the file, so it reads the dashboard AS OF pub0 (exact).
    lf_full = _pub0.private_view("home-assistant/dashboards/ecco_pro.yaml", _pex.as_of_pub0("home-assistant/dashboards/ecco_pro.yaml", dash_text.replace("\r\n", "\n")))
    # FB-B3: undo exactly the declared FB-B3 edits (an exact-match reverter: it raises on ANY other change to those regions) and prove the
    # result is main @ 87e6151 byte for byte; every pin below then runs on that FB-B2 file exactly as before.
    # FB-C3: the FB-B3 reverter is exact over the whole Safety view, so it only applies to the dashboard AS OF FB-B3. Undo exactly the declared
    # FB-C3 edits first (an exact-match reverter, _fbc3_scope.py) and prove the result is the FB-B3 dashboard (== main / FB-C2 head) byte for byte.
    try:
        lf_b3 = c3.pre_fbc3_dashboard(lf_full)
        c3_reverted = True
    except AssertionError as ex:
        lf_b3, c3_reverted = lf_full, False
        print("        FB-C3 reverter:", str(ex)[:200])
    check("FB-C3: ecco_pro.yaml with exactly the declared FB-C3 edits reverted is the FB-B3 dashboard byte for byte (sha256 == the FB-B3 final one)",
          c3_reverted and c3.sha(lf_b3) == c3.DASHBOARD_BASE_SHA == ha3.DASHBOARD_AFTER_SHA, c3.sha(lf_b3))
    check("FB-C3: the reverter is exact: one altered FB-C3 character in any hunk makes it raise",
          all(_raises_assert(lambda h=h: c3.pre_fbc3_dashboard(lf_full.replace(h[2][:60], h[2][:59] + "~", 1))) for h in c3.DASHBOARD_HUNKS if h[2]))
    check("FB-C3: exactly the declared FB-C3 hunks differ (the live file is the FB-B3 file plus the hunks, nothing else)",
          c3.sha(lf_full) == c3.DASHBOARD_AFTER_SHA, c3.sha(lf_full))
    try:
        lf = ha3.pre_fbb3_dashboard(lf_b3)
        reverted = True
    except AssertionError as ex:
        lf, reverted = lf_b3, False
        print("        reverter:", str(ex)[:200])
    check("FB-B3: ecco_pro.yaml with exactly the declared FB-B3 edits reverted is main @ 87e6151 byte for byte (sha256)",
          reverted and ha3.sha(lf) == ha3.DASHBOARD_BASE_SHA, ha3.sha(lf))
    check("FB-B3: the reverter is exact: one altered FB-B3 character makes it raise",
          all(_raises_assert(lambda h=h: ha3.pre_fbb3_dashboard(lf_b3.replace(h[2][:60], h[2][:59] + "~", 1))) for h in ha3.DASHBOARD_HUNKS[:3] if h[2]))
    check("FB-B3: exactly the declared hunks differ (the FB-B3 dashboard, i.e. the live file minus the FB-C3 hunks, is the base plus the hunks, nothing else)",
          ha3.sha(lf_b3) == ha3.DASHBOARD_AFTER_SHA, ha3.sha(lf_b3))
    v_start, v_end = f"  - title: {VIEW_TITLE}\n", "  - title: Manual Controls\n"
    check("the view's first line and the next view's first line each occur exactly once", lf.count(v_start) == 1 and lf.count(v_end) == 1, f"{lf.count(v_start)} / {lf.count(v_end)}")
    a, b = lf.find(v_start), lf.find(v_end)
    check("the inserted view sits before Manual Controls", 0 <= a < b)
    if 0 <= a < b:
        without_view = lf[:a] + lf[b:]
        digest = hashlib.sha256(without_view.encode("utf-8")).hexdigest()
        check("ecco_pro.yaml minus the inserted view is byte-identical to the pre-FB-B1 file (sha256 of HEAD's LF text, hard-coded)",
              digest == DASH_PRE_FBB1_SHA256, f"{digest} != {DASH_PRE_FBB1_SHA256}")
        inserted = lf[a:b]
        check("the inserted view is the single block between the two views (one top-level list item, 40-80 lines)",
              inserted.count("\n  - title: ") == 0 and 40 <= inserted.count("\n") <= 80, str(inserted.count("\n")))
        check(f"the file carries exactly {DASH_RESERVED_TOKENS} reserved entity-id tokens (FB-B2: ten FB-B1 ids plus the arm)", len(BANNED.findall(lf)) == DASH_RESERVED_TOKENS, str(len(BANNED.findall(lf))))
        check("none of the reserved tokens is outside the inserted view", len(BANNED.findall(without_view)) == 0 and len(BANNED.findall(inserted)) == DASH_RESERVED_TOKENS)
    check(f"FB-B3: the final dashboard carries exactly {DASH_B3_RESERVED_TOKENS} reserved entity-id tokens (the 11 above plus the declared FB-B3 surfaces)",
          len(BANNED.findall(lf_full)) == DASH_B3_RESERVED_TOKENS, str(len(BANNED.findall(lf_full))))
    sa = lf_full.index(f"  - title: {SAFETY_TITLE}\n")
    sb = lf_full.index("  - title: Manual Controls\n")
    check("FB-B3: the Fallback / Recovery view text in the FINAL file is byte-identical to the FB-B2 one (nothing inside it was edited)",
          lf_full[lf_full.index(v_start):sa] == lf[a:b])
    check("FB-B3: the Safety view is one top-level list item between Fallback / Recovery and Manual Controls",
          lf_full[sa:sb].count("\n  - title: ") == 0 and sb > sa)
    # deployment/ha-manifest.yaml minus its one added stanza is NOT pinned here: the scope chain already does it (chain entry
    # `fbb1`: the manifest reverter registry/tests/_fbb1_scope.py:pre_fbb1_manifest plus the pinned manifest checkpoints).

    # =====================================================================================================
    print("[16] FB-B2: the card's write surface against the firmware (the real text, then synthetic text with one defect each)")
    check("the synthetic firmware text (execute action, string variables, ALWAYS_OFF arm) is consistent with the card", not firmware_surface_problems(SYNTHETIC_FIRMWARE, src),
          str(firmware_surface_problems(SYNTHETIC_FIRMWARE, src)))
    for label, old, new in (
        ("the action variable target_id renamed to id", "        target_id: string", "        id: string"),
        ("the confirmation variable is not a string", "        confirmation: string", "        confirmation: int"),
        ("a fourth action variable", "        confirmation: string", "        confirmation: string\n        extra: string"),
        ("the node name changed (the HA service name changes with it)", "name: ecco-clock-dongle", "name: other-dongle"),
        ("the arm does not restore ALWAYS_OFF", "    restore_mode: ALWAYS_OFF", "    restore_mode: RESTORE_DEFAULT_OFF"),
        ("the arm is not optimistic", "    optimistic: true", "    optimistic: false"),
        ("the arm switch id changed", "id: fallback_profile_arm", "id: fallback_profile_other"),
        ("the arm switch is missing (the action stays)", '    name: "ECCO Fallback Profile Arm"', '    name: "ECCO Fallback Profile Armed"'),
        ("the action is missing (the arm stays)", "- action: fallback_profile_execute", "- action: fallback_profile_run"),
    ):
        check(f"mutant detected: {label}", bool(firmware_surface_problems(SYNTHETIC_FIRMWARE.replace(old, new), src)))
    check("mutant detected: the card's service constant changed", bool(firmware_surface_problems(SYNTHETIC_FIRMWARE, src.replace("ecco_clock_dongle_fallback_profile_execute", "ecco_clock_dongle_fallback_profile_run"))))
    # FB-B2 (AW-2): negative controls for PRESENCE. The check used to be vacuous for a firmware that declared neither the action nor the arm
    # (an INFO line, no failure); a firmware text without them must FAIL it now, whatever the way they are missing.
    act_line, arm_line = "    - action: fallback_profile_execute", '    name: "ECCO Fallback Profile Arm"'
    no_act, no_arm = "    - action: fallback_profile_run", '    name: "ECCO Fallback Profile Armed"'
    presence_controls = (
        ("neither the execute action nor the arm switch", SYNTHETIC_FIRMWARE.replace(act_line, no_act).replace(arm_line, no_arm)),
        ("only the execute action (no arm switch)", SYNTHETIC_FIRMWARE.replace(arm_line, no_arm)),
        ("only the arm switch (no execute action)", SYNTHETIC_FIRMWARE.replace(act_line, no_act)),
        ("the execute action only in a comment, the arm switch present", SYNTHETIC_FIRMWARE.replace(act_line, "    # - action: fallback_profile_execute")),
        ("the arm switch name only in a comment, the action present", SYNTHETIC_FIRMWARE.replace(arm_line, '    # name: "ECCO Fallback Profile Arm"')),
        ("the execute action declared twice", SYNTHETIC_FIRMWARE.replace("switch:\n", act_line + "\n      variables:\n        action: string\nswitch:\n", 1)),
        ("the arm switch declared twice", SYNTHETIC_FIRMWARE + "  - platform: template\n    id: fallback_profile_arm\n    optimistic: true\n    restore_mode: ALWAYS_OFF\n" + arm_line + "\n"),
        ("the execute action outside the api: section", SYNTHETIC_FIRMWARE.replace("api:\n", "script:\n", 1)),
        ("the arm switch outside the switch: section", SYNTHETIC_FIRMWARE.replace("switch:\n", "sensor:\n", 1)),
        ("the arm item is not a template platform", SYNTHETIC_FIRMWARE.replace("  - platform: template\n    id: fallback_profile_arm", "  - platform: gpio\n    id: fallback_profile_arm", 1)),
        ("an empty firmware text", ""),
    )
    check("the presence controls are real edits of the synthetic firmware text (none is a no-op)", all(v != SYNTHETIC_FIRMWARE for _l, v in presence_controls))
    for label, mutated in presence_controls:
        check(f"negative control: {label} FAILS the surface check", bool(firmware_surface_problems(mutated, src)))
    # the real firmware text carries the surface now: it must pass the check, and the same defects injected into it must fail
    real = firmware_surface_problems(fw_text, src)
    check("the real firmware's execute action and arm switch are consistent with the card", not real, str(real))
    check("the real firmware declares the execute action and the arm switch (presence is a hard requirement)",
          bool(re.search(r"(?m)^[ \t]*-[ \t]*action:[ \t]*fallback_profile_execute[ \t]*$", fw_text)) and (ENTITIES["arm"][1] in fw_names))
    for label, old, new in (
        ("the real action renamed (the arm stays)", act_line + "\n", no_act + "\n"),
        ("the real arm switch renamed (the action stays)", arm_line + "\n", no_arm + "\n"),
        ("the real action's target_id variable renamed", "        target_id: string\n", "        id: string\n"),
        ("the real arm switch id changed", "    id: fallback_profile_arm\n", "    id: fallback_profile_other\n"),
    ):
        check(f"the real-text mutant edits the firmware text exactly once: {label}", fw_text.count(old) == 1, str(fw_text.count(old)))
        check(f"mutant detected in the real firmware text: {label}", bool(firmware_surface_problems(fw_text.replace(old, new, 1), src)))

    # =====================================================================================================
    print("[17] FB-B2: nothing under home-assistant/ but the dashboard card config can act on the arm or the execute action")
    ha_root = ROOT / "home-assistant"
    holders = {q.relative_to(ROOT).as_posix(): read(q) for q in sorted(ha_root.rglob("*")) if q.is_file() and q.suffix in (".yaml", ".yml", ".json", ".jinja", ".md", ".txt", ".j2")}
    dash_rel = "home-assistant/dashboards/ecco_pro.yaml"
    check("home-assistant/ files were read", len(holders) > 5 and dash_rel in holders, str(len(holders)))
    # FB-B3: exact, counted allowlists. HA reads the arm state (status package: the save-available gates) and a human may toggle it from the
    # dashboard; nothing under home-assistant/ may turn, toggle or script it, and ONLY the operator actions package may call the device action.
    STATUS_PKG = "home-assistant/packages/ecco_fallback_status.yaml"
    ACTIONS_PKG = "home-assistant/packages/ecco_fallback_profile_actions.yaml"
    HEALTH_PKG = "home-assistant/packages/ecco_system_health.yaml"
    HB_PKG = "home-assistant/packages/ecco_supervision_heartbeat.yaml"
    arm_files = {rel: text.count("fallback_profile_arm") for rel, text in holders.items() if "fallback_profile_arm" in text}
    check("only the dashboard (3: the card config value, the Safety read, the Safety entities row) and the status package (3: reads) name the arm switch",
          arm_files == {dash_rel: 3, STATUS_PKG: 3}, str(arm_files))
    arm_ctx = [m.group(0) for m in re.finditer(r"[^\n]*fallback_profile_arm[^\n]*", holders[dash_rel])]
    check("the dashboard's three arm references are exactly: the card's entities.arm value, an is_state read, and one entities-card row (no action key on them)",
          len(arm_ctx) == 3 and sum(1 for c in arm_ctx if c.strip().startswith("arm: switch.")) == 1
          and sum(1 for c in arm_ctx if "is_state(" in c) == 1 and sum(1 for c in arm_ctx if c.strip().startswith("- entity: switch.")) == 1, str(arm_ctx))
    status_arm = [m.group(0).strip() for m in re.finditer(r"[^\n]*fallback_profile_arm[^\n]*", holders[STATUS_PKG])]
    check("the status package only READS the arm state (every reference is inside states('switch....') == 'on')",
          len(status_arm) == 3 and all("states('switch." in c and "== 'on'" in c for c in status_arm), str(status_arm))
    arm_actions = [rel for rel, text in holders.items() if rel != dash_rel and re.search(
        r"(switch|homeassistant)\.(turn_on|turn_off|toggle)[\s\S]{0,400}fallback_profile_arm|fallback_profile_arm[\s\S]{0,400}(turn_on|turn_off|toggle)", text)]
    check("FB-B3: no package, automation, schedule or helper script turns / toggles the Fallback Arm", not arm_actions, str(arm_actions))
    dash_text_lf = holders[dash_rel]
    check("FB-B3: in the dashboard nothing but the card config and the Safety row names the Arm, and no tap_action / action sits within 10 lines of any Arm reference",
          all("tap_action" not in "\n".join(dash_text_lf.split("\n")[max(0, n - 10):n + 10])
              for n, l in enumerate(dash_text_lf.split("\n")) if "fallback_profile_arm" in l and "- entity:" in l))
    exec_files = {rel: text.count("fallback_profile_execute") for rel, text in holders.items() if "fallback_profile_execute" in text}
    check("FB-B3: ONLY the operator actions package names the device action (3 wrapper calls + its header comment)", exec_files == {ACTIONS_PKG: 4}, str(exec_files))
    check("FB-B3: exactly three scripts call the device action and each one names the esphome service exactly once",
          len(re.findall(r"action: esphome\.ecco_clock_dongle_fallback_profile_execute", holders[ACTIONS_PKG])) == 3)
    banned_holders = sorted(rel for rel, text in holders.items() if BANNED.search(text))
    check("FB-B3: the reserved entity-id tokens live only in the five declared HA files (dashboard, status / actions / system-health packages)",
          banned_holders == sorted([dash_rel, STATUS_PKG, ACTIONS_PKG, HEALTH_PKG]), str(banned_holders))
    packages_calling_esphome = sorted(rel for rel, text in holders.items() if rel.startswith("home-assistant/packages/") and re.search(r"\besphome\.", text))
    check("FB-B3: exactly two packages call an esphome action: the supervision heartbeat (unchanged) and the operator actions package",
          packages_calling_esphome == sorted([HB_PKG, ACTIONS_PKG]), str(packages_calling_esphome))
    hb_private = _pub0.private_view(HB_PKG, holders[HB_PKG])   # PUB0: the pin is the private package's
    check("FB-B3: the supervision heartbeat package is byte-identical to main and carries no fallback logic",
          ha3.sha(hb_private) == HEARTBEAT_PKG_SHA256 and not re.search(r"fallback_profile|ecco_fallback|failback_shadow|fallback_profile_execute", holders[HB_PKG], re.I), ha3.sha(hb_private))
    check("FB-B3: no RESTORE / ACKNOWLEDGE control exists yet: no wrapper script, no dashboard reference, the tokens only in the actions package's reserved-token comment",
          not re.search(r"script\.ecco_fallback_profile_(restore|acknowledge)", "\n".join(holders.values()))
          and holders[dash_rel].count("ACKNOWLEDGE") == 0 and holders[dash_rel].count("script.ecco_fallback_profile_restore") == 0)
    tap_scripts = sorted(set(re.findall(r"script\.(ecco_fallback_\w+)", holders[dash_rel])))
    check("FB-B3: the dashboard's human callers are exactly the operator wrappers and the helper-only reset (nothing else under script.ecco_fallback_)",
          tap_scripts == sorted(["ecco_fallback_profile_save", "ecco_fallback_profile_replace_corrupt", "ecco_fallback_profile_invalidate", "ecco_fallback_reset_high_water"]),
          str(tap_scripts))
    # The file set is what Git TRACKS beneath the card directory, never a filesystem walk: untracked / git-ignored files, node_modules and
    # build or cache artifacts cannot change the pin on any machine (a CI checkout, or a worktree after `npm ci` or a test run).
    fe_dir = SIBLING.relative_to(ROOT).as_posix() + "/"
    ls = subprocess.run(["git", "ls-files", "-z", "--", fe_dir], cwd=str(ROOT), capture_output=True)
    fe_tracked = sorted(f for f in ls.stdout.decode("utf-8").split("\0") if f)
    check("FB-B3: the Energy Actions pin enumerates ONLY Git-tracked files (git ls-files succeeded, files found, all inside the card directory)",
          ls.returncode == 0 and len(fe_tracked) > 0 and all(f.startswith(fe_dir) for f in fe_tracked), f"rc={ls.returncode} files={len(fe_tracked)}")
    fe = hashlib.sha256()
    for rel in fe_tracked:
        fe.update(rel.encode())                                        # repository-relative POSIX path
        _fe_lf = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")   # tracked content, LF
        _fe_lf = _pex.as_of_pub0(rel, _fe_lf.decode("utf-8")).encode("utf-8") if rel in _pex.FROZEN else _fe_lf   # PEX (esb1): a frozen card file (pub0 target or enrolled) AS OF pub0
        fe.update(_lic0.pre_lic0_bytes(rel, _pub0.private_view_bytes(rel, _fe_lf)))  # tracked content, CRLF normalised to LF (PUB0: private text); LIC0: pre-lic0 bytes
    check("FB-B3: the Energy Actions frontend is byte-identical to main (sha256 over every Git-tracked file)", fe.hexdigest() == ENERGY_ACTIONS_SHA256,
          f"{fe.hexdigest()} over {len(fe_tracked)} tracked files: {fe_tracked}")
    check("the card guards every write action with the trusted-click check (five guarded actions, one isTrusted read)",
          src.count("this._trusted(ds,") == 5 and len(re.findall(r"\bisTrusted\b", src)) >= 2)
    check("the card never reads another hass member to find the arm", "hass.states" in src and not re.search(r"hass\.(callWS|callApi|connection)", src))
    # FB-B2 card-fix (CARD-09): the trust decision is made in the click listener's closure; the pass it hands out is module private
    check("the click pass is module-private: declared once, handed out by the listener only for isTrusted === true, not exported, not stored on the element",
          src.count("const CLICK_PASS") == 1 and "this._onClick(e, e && e.isTrusted === true ? CLICK_PASS : null)" in src and "if (ds.pass !== CLICK_PASS)" in src
          and not re.search(r"export\s+(?:const\s+CLICK_PASS|\{[^}]*CLICK_PASS)", src) and not re.search(r"this\.\w*[pP]ass\b", src))
    check("no caller-supplied trust flag remains in the click handler or the guard", "ds.trusted" not in src and not re.search(r"(?m)^\s*trusted\s*:", src))

    # =====================================================================================================
    print("[18] FB-B2: card mutants (one broken copy of the card per decision of the guarded flow; each must fail its named node test)")
    run_card_mutants()

    if FAILURES:
        print(f"\nFAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
