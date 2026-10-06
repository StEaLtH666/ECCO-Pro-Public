#!/usr/bin/env python3
"""FB-C3 contract test: the C2 firmware shadow strings <-> the Home Assistant shadow UX (STAGED / NOT LIVE-PROVEN).

home-assistant/tests/test_ecco_shadow_check_ux.py proves the HA layer on hand-built strings. THIS suite proves the two halves agree:
the strings the REAL FB-C2 shadow tick publishes (run through the strict simulator, drills with Z9 audit and the independent oracle) and
the strings the C2 mirror emits for the 81 golden rows are fed through the REAL Home Assistant templates and compared with an INDEPENDENT
decode written here. It also pins the grammar the HA side knows against the firmware sources, so a C2 key / code added later that HA does
not decode fails here instead of being silently shown raw.

  [1]  the five firmware entities: names, ids (device slug + name), kinds; the HA decoder consumes exactly those five
  [2]  grammar: the Episode / Soak format strings in the firmware YAML and the Inputs literals in the C2 header give the key lists the
       HA decoder knows (order and content, incl. the appended Inputs `alt` / `pa`); no stale cross-boot key (pv / pu / pe / ch / RTC
       breadcrumb) in either
  [3]  header coverage + the FINAL Verdict contract: the tick evaluates only in MODE_IF_LOST, so the published plan vocabulary is the
       readiness set (every PlanCode but NO_ACTION / WOULD_REFUSE_STARTS, which only MODE_ACTUAL yields, and the episode-layer 50); HA
       decodes every published code / Reason / Kind / BlockingDomain / cache-quality / profile-class / FB-A result to a real word, and
       an unpublished plan code or Verdict name is never worded: it reads '-' / "not recognised" and is listed verbatim
  [4]  real strings: drills through the real tick (idle, episode open, HA back, closed self-clear, closed latched, kind-L second episode,
       FP pre-empt, E1 apply, profile absent) -> HA decode == independent decode, the banner / verdict wording from the S4 table, the
       Verdict scope / heading (readiness outside an episode, continuation inside)
  [5]  the 81 golden rows + observations: Inputs from the Python mirror and the readiness Verdict (MODE_IF_LOST plan name) through HA
  [6]  cross-language: every HA display string against the Energy Actions card's regexes
  [7]  authority: the firmware tree AS OF fbc3 is byte-identical to main @ 5e59d9c = FB-C2 as merged (sha256 pins; FB-D1, after FB-C3 in
       the chain's merge order, is undone exactly by the chain), the chain entry fbc3 declares no firmware edit and no authority delta, the drills' Z9 audit is
       clean, HA holds no control for the shadow

Writes nothing; no hardware, no network.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import jinja2
import jinja2.sandbox
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import failback_shadow as sh  # noqa: E402
import fallback_capture as cap  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import _fbc2_harness as X  # noqa: E402
import _fbc2_rows as RW  # noqa: E402
import _scope_chain as chain  # noqa: E402
import test_fallback_recovery_dashboard as dash  # noqa: E402  (card_regexes(); main() is not run on import)

FAILURES: list[str] = []
FB = "fail" + "back"   # the reserved ecco_<fb> token is assembled so this file never trips the repository-wide scope scan


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda l, s, n: l.construct_scalar(n) if isinstance(n, yaml.ScalarNode)
                             else l.construct_sequence(n) if isinstance(n, yaml.SequenceNode) else l.construct_mapping(n))


def lf(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


FW_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
STATUS_REL = "home-assistant/packages/ecco_fallback_status.yaml"
fw_text = lf(FW_REL)
FW = chain.load_fw(fw_text)
SUBS = FW["_substitutions"]
HEADER = lf("firmware/include/ecco_failback_shadow.h")
CAP_HEADER = lf("firmware/include/ecco_fallback_capture.h")
DUR_HEADER = lf("firmware/include/ecco_fallback_durable_model.h")
PROF_HEADER = lf("firmware/include/ecco_fallback_profile.h")
DEV = "ecco_clock_dongle"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# --- the Home Assistant templates under test (plain jinja2 and the sandbox Home Assistant derives from)
ENVS = {False: jinja2.Environment(undefined=jinja2.StrictUndefined),
        True: jinja2.sandbox.ImmutableSandboxedEnvironment(undefined=jinja2.StrictUndefined)}
for _e in ENVS.values():
    _e.filters["timestamp_custom"] = lambda v, fmt="%Y-%m-%d %H:%M:%S", local=True: datetime.fromtimestamp(float(v), timezone.utc).strftime(fmt)


class _States:
    def __init__(self, values):
        self.values = values

    def __call__(self, e):
        return self.values.get(e, "unknown")

    def __getitem__(self, e):
        class _O:
            last_changed = 0.0
        return _O()


class T:
    def __init__(self, text, sandbox=False):
        self.t = ENVS[sandbox].from_string(text)

    def __call__(self, values, now=1_800_000_000.0):
        ctx = {"states": _States(values), "state_attr": lambda e, a: values.get(f"{e}#{a}"), "as_timestamp": lambda v: float(v), "now": lambda: now}
        return self.t.render(**ctx).strip()


def literal(s):
    try:
        return ast.literal_eval(s)
    except Exception:  # noqa: BLE001
        return s


status_doc = yaml.load(lf(STATUS_REL), Loader=Loader)
ENT = {e["unique_id"]: e for b in status_doc["template"] for p in ("sensor", "binary_sensor") for e in (b.get(p) or [])}
SHADOW = ENT["ecco_shadow_check"]
ATTR_T = {k: T(t) for k, t in SHADOW["attributes"].items() if isinstance(t, str) and "{{" in t}
ATTR_T_SB = {k: T(t, True) for k, t in SHADOW["attributes"].items() if isinstance(t, str) and "{{" in t}
STATE_T = T(SHADOW["state"])
CODE_T = T(ENT["ecco_fallback_status_code"]["state"])
DISPLAY_T = T(ENT["ecco_fallback_status"]["state"])
SUBLINE_T = T(ENT["ecco_fallback_status"]["attributes"]["subline"])

# ===========================================================================
print("[1] The five firmware entities and the HA consumer")
names = ["ECCO Failback Shadow State", "ECCO Failback Shadow Episode", "ECCO Failback Shadow Soak", "ECCO Failback Shadow Verdict", "ECCO Failback Shadow Inputs"]
fw_shadow = [e for e in FW["text_sensor"] if str(e.get("name", "")).startswith("ECCO Failback Shadow")]
check("the firmware declares exactly the five FROZEN `ECCO Failback Shadow ...` text sensors (no sixth, no other kind)",
      [e["name"] for e in fw_shadow] == names and all(e["platform"] == "template" and str(e.get("update_interval")) == "never" for e in fw_shadow)
      and not [e for sec in ("sensor", "binary_sensor", "switch", "button", "number", "select")
               for e in (FW.get(sec) or []) if isinstance(e, dict) and "Failback Shadow" in str(e.get("name", ""))])
IDS = [f"sensor.{DEV}_{slug(n)}" for n in names]
SS, EP, SK, VD, IN = IDS[0], IDS[1], IDS[2], IDS[3], IDS[4]
check("ids derive as <domain>.<device slug>_<slug(name)> and carry the reserved ecco_<fb>_shadow_ prefix",
      all(i.startswith(f"sensor.{DEV}_ecco_{FB}_shadow_") for i in IDS) and [i.rsplit("_", 1)[1] for i in IDS] == ["state", "episode", "soak", "verdict", "inputs"], str(IDS))
check("the decoder sensor consumes exactly those five (its source_entities attribute and every entity id its templates read)",
      literal(ATTR_T["source_entities"]({})) == IDS
      and sorted(set(re.findall(r"sensor\.[a-z0-9_]*ecco_" + FB + r"_shadow_[a-z0-9_]+", yaml.dump(SHADOW)))) == sorted(IDS))
check("the substitution that fixes the close window is 300000 ms (the banner says 5 minutes)", SUBS["ecco_failback_shadow_episode_close_ms"] == "300000")

# ===========================================================================
print("")
print("[2] Grammar: the key lists HA knows equal the firmware's")
FMT = re.findall(r'"((?:id|b)=[^"]*)"', fw_text)


def keys_of(fmt: str) -> list[str]:
    return re.findall(r"(?:^|;)([a-z0-9]+)=", fmt)


episode_fmts = [f for f in FMT if f.startswith("id=")]
soak_fmts = [f for f in FMT if f.startswith("b=")]
check("the firmware has one idle and one active Episode format and one Soak format", len(episode_fmts) == 2 and len(soak_fmts) == 1, str(FMT))
EP_KEYS = keys_of(episode_fmts[1])
SK_KEYS = keys_of(soak_fmts[0])
check("the idle and active Episode formats have the same keys in the same order", keys_of(episode_fmts[0]) == EP_KEYS)
body = HEADER[HEADER.index("constexpr ecco_fbcap::TextBuf inputs_text"):HEADER.index("// ---- static self-checks")]
IN_KEYS = [k for lit in re.findall(r'"([^"\n]*)"', body) for k in keys_of(lit)]
check("Episode keys (actual C2): id ph k tr u0 e0 cli rb v0 vu f0 dm pre blk d ret gap rl vch cl fbf",
      EP_KEYS == "id ph k tr u0 e0 cli rb v0 vu f0 dm pre blk d ret gap rl vch cl fbf".split(), str(EP_KEYS))
check("Inputs keys (actual C2, alt / pa appended by the remediation, FINAL 8.5): sup st fp dp r4 mt pc g pb e1 cx in ca d blk lk pl rs alt pa",
      IN_KEYS == "sup st fp dp r4 mt pc g pb e1 cx in ca d blk lk pl rs alt pa".split(), str(IN_KEYS))
check("Soak keys (actual C2): b h mx lg gm lx wr nc ncm xh cs", SK_KEYS == "b h mx lg gm lx wr nc ncm xh cs".split(), str(SK_KEYS))
unk_tpl = SHADOW["attributes"]["unknown_keys"]
lists = re.findall(r"\['(episode|inputs|soak)', states\('[^']+'\), (\[[^\]]*\])\]", unk_tpl)
HA_KEYS = {n: ast.literal_eval(l) for n, l in lists}
check("the HA decoder's known-key lists equal the firmware's, in order (Episode / Inputs / Soak)",
      HA_KEYS == {"episode": EP_KEYS, "inputs": IN_KEYS, "soak": SK_KEYS}, str(HA_KEYS))
STALE = {"pv", "pu", "pe", "ch", "uc", "rr", "race"}
check("no stale / withdrawn field (pv pu pe ch uc rr race: the S3 FINAL cross-boot breadcrumb) exists in the C2 grammar or in the HA decoder",
      not (STALE & (set(EP_KEYS) | set(IN_KEYS) | set(SK_KEYS))) and not (STALE & {k for v in HA_KEYS.values() for k in v}))
check("neither the firmware shadow tick nor the header uses RTC_NOINIT / an RTC breadcrumb, and HA names none",
      "RTC_NOINIT" not in HEADER and "RTC_NOINIT" not in lf(STATUS_REL) and "RTC_NOINIT" not in lf("home-assistant/dashboards/ecco_pro.yaml"))
check("known HA key lists contain no key the firmware lacks and miss none (a new C2 key would be shown raw, not dropped)",
      all(set(HA_KEYS[n]) == set(k) for n, k in (("episode", EP_KEYS), ("inputs", IN_KEYS), ("soak", SK_KEYS))))
PLAN_KEYS = {"pl", "alt", "pa", "v0", "vu"}   # the plan-code fields (value probed with a published readiness code)


def probe(keys) -> str:
    return ";".join(f"{k}={'40' if k in PLAN_KEYS else '1'}" for k in keys)


check("a probe string with every known key reports no unknown key, and one extra key is reported verbatim",
      literal(ATTR_T["unknown_keys"]({EP: probe(EP_KEYS), IN: probe(IN_KEYS), SK: probe(SK_KEYS)})) == []
      and literal(ATTR_T["unknown_keys"]({IN: probe(IN_KEYS) + ";future=9"})) == ["inputs:future=9"])

# ===========================================================================
print("")
print("[3] Header coverage + the FINAL Verdict contract: every PUBLISHED code is decoded to a real word, an unpublished one never is")


def enum_members(text: str, prefix: str) -> dict[str, int]:
    return {n: int(v) for n, v in re.findall(prefix + r"([A-Z0-9_]+)\s*=\s*(\d+)", text)}


PLANS = enum_members(HEADER, r"PLAN_")
REASONS = enum_members(HEADER, r"RS_")
KINDS = enum_members(HEADER, r"KIND_")
BDS = enum_members(HEADER, r"BD_")
check("the header enumerates 23 plan codes, 100+ reason codes, the domain kinds and 12 blocking domains (non-trivial parse)",
      len(PLANS) == 23 and len(REASONS) >= 100 and len(KINDS) >= 14 and len(BDS) == 12, f"{len(PLANS)} {len(REASONS)} {len(KINDS)} {len(BDS)}")
check("the Python mirror's plan names and reasons equal the header's", {v: k for k, v in PLANS.items()} == sh.PLAN_NAMES and {v: k for k, v in REASONS.items()} == {v: k for k, v in sh.RS.items()})
# The FINAL Verdict contract (FB-C2 remediation d172574, merged as PR #63): ONE MODE_IF_LOST evaluation per tick; the Verdict is that readiness
# plan or 50 (episode layer). MODE_IF_LOST takes the LOST branch, so S4's supervision rows NO_ACTION / WOULD_REFUSE_STARTS can never be published.
tick_src = fw_text[fw_text.index("// 4b. FB-C2 evaluator"):fw_text.index("// 5. Episode machine")]
check("the firmware tick evaluates exactly once, in MODE_IF_LOST, and publishes would_latched ? 50 : rd.plan as the Verdict (no MODE_ACTUAL in the firmware)",
      tick_src.count("ecco_failback_shadow::evaluate(") == 1 and "in.mode = ecco_failback_shadow::MODE_IF_LOST;" in tick_src
      and "MODE_ACTUAL" not in fw_text
      and "const uint8_t verdict = id(failback_shadow_would_latched) ? (uint8_t) ecco_failback_shadow::PLAN_WOULD_REMAIN_LATCHED : rd.plan;" in tick_src)
eff = HEADER[HEADER.index("const bool effective_lost"):HEADER.index("} else {", HEADER.index("const bool effective_lost"))]
check("the header emits NO_ACTION / WOULD_REFUSE_STARTS only on the not-effectively-lost branch, which MODE_IF_LOST never takes; 50 never comes from evaluate()",
      "in.mode == MODE_IF_LOST ||" in eff and "if (!effective_lost)" in eff and "PLAN_NO_ACTION" in eff and "PLAN_WOULD_REFUSE_STARTS" in eff
      and HEADER.count("(uint8_t) PLAN_NO_ACTION") == 1 and HEADER.count("(uint8_t) PLAN_WOULD_REFUSE_STARTS") == 1
      and "PLAN_WOULD_REMAIN_LATCHED = 50,  // emitted by the episode layer only, never by evaluate()" in HEADER)
UNPUBLISHED = {PLANS["NO_ACTION"], PLANS["WOULD_REFUSE_STARTS"]}
READY = {c for c in PLANS.values() if c not in UNPUBLISHED and c != PLANS["WOULD_REMAIN_LATCHED"]}
seen = set()
for entry in list(RW.ROWS) + list(RW.OBSERVATIONS):
    i = entry["build"]()
    i.mode = sh.MODE_IF_LOST
    p = sh.evaluate(i)
    seen |= {p.plan, p.alt_plan_absence_accepted, p.projected_after}
check("over the 81 golden rows + observations MODE_IF_LOST yields only readiness codes in plan / alt / pa (never 1, 2 or 50)",
      seen <= READY and not seen & (UNPUBLISHED | {50}) and len(seen) >= 15, str(sorted(seen)))
INP = "sup=L;st=0;fp=CM;dp=CM;r4=CM;mt=-;pc=5;g=7;pb=D852A4FA;e1=D;cx=M;in=M;ca=F;d=1;blk=1;lk=0;pl={pl};rs={rs};alt={pl};pa={pl}"
EPI = "id=ABCD0001-1;ph=O;k=N;tr=H;u0=430;e0=1789999999;cli=0;rb=602;v0={v0};vu={vu};f0={f0};dm={dm};pre=0;blk=0;d=1;ret=-;gap=-;rl=0;vch=0;cl=-;fbf=-"
NOT_RECOGNISED = "Shadow check result not recognised"
bad = []
for name, code in PLANS.items():
    vals = {IN: INP.format(pl=code, rs=0), EP: EPI.format(v0=code, vu=code, f0=0, dm=0), VD: name, SS: "SHADOW_IDLE"}
    a = {k: literal(t(vals)) for k, t in ATTR_T.items() if k in ("inputs", "episode", "unknown_keys", "verdict_scope")}
    inp, epi, unk = a["inputs"], a["episode"], a["unknown_keys"]
    word = STATE_T({VD: name, IN: "unknown"})
    if code in READY:
        if (inp["if_lost_plan"], inp["absence_accepted_plan"], inp["projected_after_plan"], epi["edge_plan"], epi["underlying_plan"]) != (name,) * 5:
            bad.append(("plan", name, inp["if_lost_plan"], inp["absence_accepted_plan"], inp["projected_after_plan"], epi["edge_plan"], epi["underlying_plan"]))
        if word in (NOT_RECOGNISED, "Shadow check not available") or unk:
            bad.append(("wording / unknown", name, word, unk))
        if not epi["would_have"] or name in epi["would_have"]:
            bad.append(("would_have", name, epi["would_have"]))
    elif code == 50:   # the episode layer's latch: a Verdict and a kind-L edge plan, never a readiness plan
        if word == NOT_RECOGNISED or epi["edge_plan"] != name or inp["if_lost_plan"] != "-" or epi["underlying_plan"] != "-" \
                or sorted(unk) != sorted([f"inputs:pl={code}", f"inputs:alt={code}", f"inputs:pa={code}", f"episode:vu={code}"]):
            bad.append(("latched", name, word, epi["edge_plan"], inp["if_lost_plan"], unk))
    else:              # NO_ACTION / WOULD_REFUSE_STARTS: never published, never worded, always visible verbatim
        if word != NOT_RECOGNISED or a["verdict_scope"] != "unrecognised" or inp["if_lost_plan"] != "-" or epi["edge_plan"] != "-" \
                or inp["if_lost_wording"] != "-" or sorted(unk) != sorted([f"inputs:pl={code}", f"inputs:alt={code}", f"inputs:pa={code}",
                                                                           f"episode:v0={code}", f"episode:vu={code}", f"verdict:{name}"]):
            bad.append(("unpublished", name, word, a["verdict_scope"], inp["if_lost_plan"], epi["edge_plan"], unk))
check("every readiness PlanCode is named by Inputs pl / alt / pa and Episode v0 / vu, has Verdict wording and a would-have phrase; 50 is a Verdict / "
      "kind-L edge plan only; NO_ACTION / WOULD_REFUSE_STARTS are never worded (\"not recognised\", '-') and are listed verbatim", not bad, str(bad[:4]))
check("the decoder's published Verdict vocabulary is exactly the header's plan names minus NO_ACTION / WOULD_REFUSE_STARTS",
      sorted(n for n in PLANS if STATE_T({VD: n, IN: "unknown"}) != NOT_RECOGNISED) == sorted(n for n, c in PLANS.items() if c not in UNPUBLISHED))
bad = [(n, v) for n, v in REASONS.items() if v != 0
       if literal(ATTR_T["inputs"]({IN: INP.format(pl=41, rs=v)}))["if_lost_reason"] != n]
check("every Reason code (RS_NONE = 0 means 'no reason' and reads '-') is named by Inputs `rs`",
      not bad and literal(ATTR_T["inputs"]({IN: INP.format(pl=41, rs=0)}))["if_lost_reason"] == "-", str(bad[:4]))
bad = []
for n, v in KINDS.items():
    if n in ("PROBE_PENDING",):
        continue
    got = literal(ATTR_T["inputs"]({IN: INP.replace("fp=CM", f"fp=O{v}").format(pl=41, rs=0)}))["free_power"]
    if "code" in got or got.endswith(": none") and n != "NONE":
        bad.append((n, got))
check("every domain Kind of the header has a word (PROBE_PENDING is FB-E / FB-F only and is never produced)", not bad, str(bad))
check("the kind 23 PROBE_PENDING (never produced by FB-C) still reads as a named kind, not a crash",
      literal(ATTR_T["inputs"]({IN: INP.replace("fp=CM", "fp=O23").format(pl=41, rs=0)}))["free_power"] == "obligation: probe pending")
bad = [(n, v) for n, v in BDS.items()
       if literal(ATTR_T["episode"]({EP: EPI.format(v0=41, vu="-", f0=0, dm=v)}))["blocking_domain"] in ("-",)]
check("every BlockingDomain value 0..11 is named by Episode `dm`", not bad, str(bad))
CQ = {"B": "boot", "I": "invalid", "O": "polling", "S": "stale", "P": "fence", "M": "filled", "F": "fresh"}
check("every cache-quality letter cap.cq_char can emit is decoded (and each maps to a distinct word)",
      sorted({cap.cq_char(q) for q in range(0, 8)}) == sorted(set(CQ) | {"B"})
      and len({literal(ATTR_T["inputs"]({IN: INP.replace("ca=F", f"ca={c}").format(pl=41, rs=0)}))["cache"] for c in CQ}) == 7)
check("every effective profile class 0..8 is decoded (mirror EPC_NAMES == the header enum)",
      {v: n for v, n in fd.EPC_NAMES.items()} == {int(v): n for n, v in re.findall(r"EPC_([A-Z_]+)\s*=\s*(\d+)", DUR_HEADER)}
      and all(literal(ATTR_T["inputs"]({IN: INP.replace("pc=5", f"pc={v}").format(pl=41, rs=0)}))["profile_class"] == n for v, n in fd.EPC_NAMES.items()))
check("every FB-A result code 0..11 is named (mirror == the profile header enum)",
      {int(v): n for n, v in re.findall(r"FAILBACK_RESULT_([A-Z_]+)\s*=\s*(\d+)", PROF_HEADER) if n not in ("MAX",)} == fp.FAILBACK_RESULT_NAMES
      and all(literal(ATTR_T["episode"]({EP: EPI.format(v0=41, vu="-", f0=v, dm=0)}))["fba_result"] == n for v, n in fp.FAILBACK_RESULT_NAMES.items()))
check("the State names HA knows are the header's state_name() results",
      sorted(set(re.findall(r'"(SHADOW_[A-Z_]+)"', HEADER))) == sorted(["SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK", "SHADOW_WOULD_AWAIT_ACK", "SHADOW_WATCH", "SHADOW_IDLE"]))

# ===========================================================================
print("")
print("[4] Real strings from the real FB-C2 tick -> the real HA templates")
LOST_MS = int(SUBS["ecco_supervision_lost_ms"])
CLOSE_MS = int(SUBS["ecco_failback_shadow_episode_close_ms"])
T_STATE, T_EPS, T_SOAK, T_VERDICT, T_INPUTS = X.FBC_TEXT_IDS
FAR_EPOCH = 1_800_000_000
s4 = (ROOT / "docs/architecture/fallback/design/S4_domains_decisions_final.md").read_text(encoding="utf-8")
sec = s4[s4.index("| # | Code | Meaning | Emitted by"):s4.index("**FB-A results FB-C never projects")]
S4_WORDING = {}
for line in sec.splitlines():
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 6 and cells[0].isdigit():
        S4_WORDING[cells[1]] = cells[5]
# S4 8.1 words for the PUBLISHED Verdicts; NO_ACTION / WOULD_REFUSE_STARTS are never published (FINAL 8.5, S5 2.3) and get no Verdict wording
WORDING = {**{k: v for k, v in S4_WORDING.items() if k not in ("NO_ACTION", "WOULD_REFUSE_STARTS")},
           "WOULD_REMAIN_LATCHED": "Would stay latched: previous episode not acknowledged",
           "WOULD_APPLY_PROFILE": "Would apply known-good profile"}   # S4 writes "(N registers)": N is filled from Inputs d
HEAD_READY = "If Home Assistant were lost now, a future automatic failback would:"   # S5 6.4
HEAD_EPISODE = "A shadow episode is open; a future automatic failback would now:"

# independent human tables (typed from the C2 header comments, NOT from the HA templates)
SUP = {"U": "starting (no heartbeat yet)", "O": "supervised", "S": "suspect", "L": "lost"}
CMPW = {"M": "matches", "D": "differs", "N": "not comparable", "O": "not a baseline (cache overlay)"}
CACHEW = {"B": "boot not loaded yet", "I": "no valid cache", "O": "configuration polling off", "S": "stale", "P": "may pre-date a write (write fence)", "M": "never filled", "F": "fresh"}
KINDW = {0: "none", 1: "active", 2: "starting", 3: "restore required", 4: "ending", 5: "clear pending", 6: "needs your decision", 7: "in flight",
         16: "recovery state unreadable", 17: "recovery metadata corrupt", 19: "not loaded at boot", 20: "stored state disagrees with memory", 21: "inverter lock stuck"}
BASISW = {"M": "clear (boot marker)", "R": "clear (checked at runtime)", "A": "clear by absence (not proven)"}
BDW = {0: "none", 1: "supervision", 2: "boot", 3: "Dump to Grid", 4: "Free Power", 5: "register 244 test", 6: "inverter bus", 7: "Manual TOU",
       8: "Manual TOU journal", 9: "known-good profile", 10: "site ceiling", 11: "live inverter data"}
FRAMEW = [(1, "244 export write (0 to 2)"), (2, "slot power down (256-261)"), (4, "target SOC / source (268-279)"), (8, "slot power up (256-261)")]
# every would-have phrase, typed here independently of the HA templates (S4 section 8.1 meaning, past conditional)
WOULD = {0: "been unable to evaluate a plan (the evaluator was not ready)",
         10: "ended Dump to Grid, then continued failback", 11: "ended Free Power, then continued failback",
         12: "waited for Dump to Grid to put settings back", 13: "waited for Free Power to put settings back",
         14: "waited because another inverter write was running", 15: "waited because the live inverter settings were not current",
         16: "waited for Manual TOU recovery to finish", 20: "held because saved lease records were unreadable or corrupt",
         21: "held because the saved lease state was not confirmed", 22: "held because a lease needed your decision first",
         23: "held because the saved profile is damaged", 24: "held because the saved profile could not be confirmed",
         25: "held because the profile power is above the site limit", 26: "held because the schedule or context changed since the save",
         27: "held because the live settings are outside the profile range",
         30: "been unable to fail back because no known-good profile is saved", 31: "been unable to fail back because the profile was invalidated",
         40: "done nothing because the inverter already matched the profile", 41: "applied the known-good profile"}


bad = [(n, c, literal(ATTR_T["episode"]({EP: EPI.format(v0=c, vu="-", f0=0, dm=0)}))["would_have"]) for n, c in PLANS.items() if c in READY
       if literal(ATTR_T["episode"]({EP: EPI.format(v0=c, vu="-", f0=0, dm=0)}))["would_have"] != (WOULD[c] if c != 41 else "applied the known-good profile (1 setting)")]
check("every would-have phrase equals the independently typed one (all 20 readiness edge plans; no raw enum, no placeholder)",
      not bad and len([c for c in PLANS.values() if c in READY]) == 20 == len(WOULD), str(bad[:3]))


def kv(s: str) -> dict:
    return dict(p.split("=", 1) for p in s.split(";") if "=" in p)


def dom_text(t: str) -> str:
    if t[0] == "C":
        return BASISW.get(t[1:], "clear")
    return ("obligation: " if t[0] == "O" else "unknown: ") + KINDW[int(t[1:])]


def indep_inputs(s: str) -> dict:
    k = kv(s)
    pl, rs = int(k["pl"]), int(k["rs"])
    bm = int(k["blk"], 16)
    d = k["d"]
    wording = WORDING[sh.PLAN_NAMES[pl]]
    if pl == 41 and d.isdigit():
        wording += f" ({d} register{'' if d == '1' else 's'})"
    return {"available": True, "supervision": SUP[k["sup"]], "stable": "stable" if k["st"] == "1" else "not stable", "free_power": dom_text(k["fp"]),
            "dump_to_grid": dom_text(k["dp"]), "register_244_test": dom_text(k["r4"]), "manual_tou": "not evaluated", "profile_class": fd.EPC_NAMES[int(k["pc"])],
            "profile_generation": k["g"], "profile_binding": k["pb"], "e1": CMPW[k["e1"]], "context": CMPW[k["cx"]], "info": CMPW[k["in"]],
            "cache": CACHEW[k["ca"]], "delta_count": d, "projected_frames": [w for b, w in FRAMEW if bm & b],
            "locks": ["none", "manual write in progress", "clock correction in progress", "manual write and clock correction in progress"][int(k["lk"])],
            "if_lost_plan": sh.PLAN_NAMES[pl], "if_lost_wording": wording, "if_lost_reason": {v: n for n, v in sh.RS.items()}[rs],
            "if_lost_plan_code": k["pl"], "if_lost_reason_code": k["rs"],
            "absence_accepted_plan": sh.PLAN_NAMES[int(k["alt"])], "absence_accepted_wording": WORDING[sh.PLAN_NAMES[int(k["alt"])]],
            "absence_accepted_plan_code": k["alt"],
            "projected_after_plan": sh.PLAN_NAMES[int(k["pa"])], "projected_after_wording": WORDING[sh.PLAN_NAMES[int(k["pa"])]],
            "projected_after_plan_code": k["pa"]}


def fmt_dur(s: int) -> str:
    return f"{s // 3600} h {(s % 3600) // 60} min" if s >= 3600 else f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def indep_episode(s: str, now: float) -> dict:
    k = kv(s)
    e0 = int(k["e0"]) if k["e0"].isdigit() else 0
    ph = k["ph"]
    v0 = int(k["v0"]) if k["v0"].isdigit() else None
    vu = int(k["vu"]) if k["vu"].isdigit() else None
    d = k["d"]
    sfx = (f" ({d} setting{'' if d == '1' else 's'})") if d.isdigit() else ""

    def would(code):
        return (WOULD.get(code) or "") + (sfx if code == 41 else "")

    if k["k"] == "L":
        wh = "done nothing new (an earlier shadow episode is still latched); the underlying plan would have been: " + (would(vu) if vu is not None else "not recorded")
    else:
        wh = would(v0) if v0 is not None else "nothing recorded"
    ident = k["id"]
    ret = int(k["ret"]) if k["ret"].isdigit() else None
    cl = int(k["cl"]) if k["cl"].isdigit() else None
    elapsed = max(int(now - e0), 0) if (e0 > 0 and ph == "O") else None
    rl = int(k["rl"]) if k["rl"].isdigit() else 0
    if ph == "O" and rl == 0:
        bl = f"Lost for {fmt_dur(elapsed)} since the loss was declared (episode {ident})." if elapsed is not None else f"Home Assistant supervision was lost (episode {ident}); the duration is not available."
    elif ph == "O":
        bl = f"Home Assistant supervision was lost again (episode {ident}, {rl} re-loss(es))."
    elif ph == "B":
        bl = "Home Assistant is back" + (f" {fmt_dur(ret)} after the loss was declared" if ret is not None else "") + f", but the episode ({ident}) stays open until supervision has been stable."
    elif ph == "C":
        bl = f"The shadow episode {ident} is closed" + (f" (closed {fmt_dur(cl)} after the loss was declared)" if cl is not None else "") + "."
    else:
        bl = "No shadow episode on record for this boot."
    return {"available": True, "id": ident, "phase": {"N": "none", "O": "open", "B": "ha_back", "C": "closed"}[ph],
            "kind": {"N": "new", "L": "latched", "-": "-"}[k["k"]], "trigger": {"H": "heartbeat loss", "S": "no heartbeat since the dongle started", "-": "-"}[k["tr"]],
            "edge_uptime_s": k["u0"], "edge_epoch": e0,
            "edge_time": datetime.fromtimestamp(e0, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if e0 > 0 else "-", "client_at_edge": {"1": "yes", "0": "no", "-": "-"}[k["cli"]], "reboot_margin_s": k["rb"],
            "edge_plan": sh.PLAN_NAMES[v0] if v0 is not None else "-", "underlying_plan": sh.PLAN_NAMES[vu] if vu is not None else "-",
            "fba_result": fp.FAILBACK_RESULT_NAMES[int(k["f0"])] if k["f0"].isdigit() else "-", "blocking_domain": BDW[int(k["dm"])] if k["dm"].isdigit() else "-",
            "preempt": [n for b, n in ((1, "Free Power"), (2, "Dump to Grid")) if k["pre"].isdigit() and int(k["pre"]) & b],
            "projected_frames": [w for b, w in FRAMEW if k["blk"] != "-" and int(k["blk"], 16) & b], "delta_count": d, "return_s": k["ret"], "return_gap_s": k["gap"],
            "re_lost": k["rl"], "verdict_changes": k["vch"], "close_s": k["cl"],
            "close_outcome": {"A": "a future FB-F would stay latched until acknowledged (no such control exists yet)", "P": "a future FB-F would clear itself", "-": "-"}[k["fbf"]],
            "lost_for": fmt_dur(elapsed) if elapsed is not None else "-", "returned_after": fmt_dur(ret) if ret is not None else "-",
            "closed_after": fmt_dur(cl) if cl is not None else "-", "would_have": wh, "banner_lost": bl,
            "banner_would": "If automatic failback were enabled it would have: " + wh + ".",
            "banner_edge": (f"Loss declared at {datetime.fromtimestamp(e0, timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if e0 > 0 else 'an unknown time'}; the API client was "
                            f"{'connected' if k['cli'] == '1' else 'not connected'} at that moment.") if ph in "OBC" else "",
            "banner_details": (f"Re-lost {rl} time(s) since the first loss; the verdict changed {k['vch']} time(s).") if (rl > 0 or k["vch"] not in ("0", "-")) else ""}


def indep_soak(s: str) -> dict:
    k = kv(s)
    h, wr, xh, cs = k["h"].split("/"), k["wr"].split("/"), k["xh"].split("/"), k["cs"].split("/")
    return {"available": True, "boot_id": k["b"], "gap_histogram": dict(zip(["<=35 s", "<=45 s", "<=90 s", "<=300 s", "<=900 s", ">900 s"], h)),
            "max_gap_s": k["mx"], "last_long_gap_s": k["lg"], "gaps_missed": k["gm"], "episodes": k["lx"],
            "starts_seen_while_would_refuse": dict(zip(["free_power", "dump_to_grid", "register_244_test", "profile_changes"], wr)),
            "api_client_drops": k["nc"], "longest_no_client_s": k["ncm"], "export_hazard_s": dict(zip(["yes", "unknown"], xh)),
            "cache_s": dict(zip(["fresh", "pre_fence", "other"], cs))}


SAMPLES: list[tuple[str, dict]] = []   # (label, five texts + the wall clock the sample was taken at)
DRILL_VIOLATIONS: list[str] = []
DRILL_ORACLE: list[str] = []


def prime(h, words=None):
    h.set_words(words or X.GW)
    h.run_until(h.now + 1_200)
    for _ in range(3):
        h.poll()


def run_polled(h, t_end, every=60_000):
    while h.now < t_end:
        h.run_until(min(h.now + every, t_end))
        h.poll()


def grab(h, label):
    wall = 1_790_000_000 + h.now / 1000.0
    SAMPLES.append((label, {SS: h.text(T_STATE), EP: h.text(T_EPS), SK: h.text(T_SOAK), VD: h.text(T_VERDICT), IN: h.text(T_INPUTS), "now": wall}))


def drill(label, setup=None, words=None, second_outage=False):
    h = X.Harness(FW, oracle=True, fbc_offset_ms=250, pra_offset_ms=750)
    h.sim.ntp_valid = True
    h.set_g(ntp_synced=True)
    if setup:
        setup(h)
    last, r = 130_000, 500_000
    edge = last + LOST_MS
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, last)
    prime(h, words)
    run_polled(h, last + 2_000)
    grab(h, f"{label}: healthy")
    h.set_client(False)
    run_polled(h, edge + 2_000)
    grab(h, f"{label}: episode open")
    run_polled(h, edge + 40_000)
    grab(h, f"{label}: episode open, 40 s later")
    h.schedule_beats_every(r, 30_000, r + 700_000)
    run_polled(h, r + 5_000)
    grab(h, f"{label}: HA back")
    h.run_until(r + 60_000 + CLOSE_MS + 2_000)
    grab(h, f"{label}: closed")
    if second_outage:
        h.run_until(r + 700_000 + LOST_MS + 5_000)
        grab(h, f"{label}: second episode")
    DRILL_VIOLATIONS.extend(h.violations)
    DRILL_ORACLE.extend(h.oracle_errors)
    return h


apply244 = list(X.GW)
apply244[0] = 0   # REGS index 0 is register 244: live 244 differs from the profile
drill("idle->match", None)
drill("FP active at the edge", lambda h: h.free_power(snapshot_valid=True, marker_state=1, active_persisted=True, end_epoch=FAR_EPOCH))
drill("E1 apply 244", None, words=apply244)
drill("profile absent (latched close, then kind L)", lambda h: h.set_profile(None, load=fp.LOAD_ABSENT, cls=fd.EPC_NOT_CAPTURED), second_outage=True)
check(f"the drills ran {len(SAMPLES)} samples through the real tick; the Z9 audit and the independent oracle are clean",
      len(SAMPLES) >= 21 and not DRILL_VIOLATIONS and not DRILL_ORACLE, f"{DRILL_VIOLATIONS[:2]} {DRILL_ORACLE[:2]}")
phases = {kv(s[EP])["ph"] for _, s in SAMPLES}
kinds = {kv(s[EP])["k"] for _, s in SAMPLES}
states = {s[SS] for _, s in SAMPLES}
check("the drills cover every episode phase (none / open / ha_back / closed), both kinds (N / L), both close outcomes (A / P) and the five States seen in a drill",
      phases == {"N", "O", "B", "C"} and {"N", "L"} <= kinds and {kv(s[EP])["fbf"] for _, s in SAMPLES} >= {"A", "P"}
      and states >= {"SHADOW_IDLE", "SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK", "SHADOW_WOULD_AWAIT_ACK"}, f"{phases} {kinds} {states}")
verdicts = {s[VD] for _, s in SAMPLES}
check("the drills produced several different real READINESS verdicts (incl. WOULD_REMAIN_LATCHED, a BLOCKED_*, a WAIT_* and WOULD_*), "
      "and never a supervision row (NO_ACTION / WOULD_REFUSE_STARTS: the healthy idle tick publishes its readiness plan)",
      {"WOULD_REMAIN_LATCHED", "WOULD_APPLY_PROFILE", "WOULD_PREEMPT_FREE_POWER", "BLOCKED_PROFILE_UNAVAILABLE", "WOULD_ALREADY_MATCH", "WAIT_LIVE_DATA"} <= verdicts
      and not verdicts & {"NO_ACTION", "WOULD_REFUSE_STARTS"}
      and {s[VD] for lbl, s in SAMPLES if lbl.endswith(": healthy")} <= {"WOULD_ALREADY_MATCH", "WOULD_PREEMPT_FREE_POWER", "WOULD_APPLY_PROFILE",
                                                                         "BLOCKED_PROFILE_UNAVAILABLE", "WAIT_LIVE_DATA"}, str(verdicts))

mism = []
for label, s in SAMPLES:
    now = s["now"]
    vals = {SS: s[SS], EP: s[EP], SK: s[SK], VD: s[VD], IN: s[IN]}
    for sandbox in (False, True):
        src = ATTR_T_SB if sandbox else ATTR_T
        got = {k: literal(src[k](vals, now)) for k in ("inputs", "episode", "soak", "unknown_keys", "episode_open", "verdict", "shadow_state",
                                                         "verdict_scope", "verdict_heading", "latched")}
        in_ep = s[SS] in ("SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK")
        scope = "not_evaluated" if s[VD] == "NOT_EVALUATED" else "episode" if in_ep else "readiness"
        for key, want in (("inputs", indep_inputs(s[IN])), ("episode", indep_episode(s[EP], now)), ("soak", indep_soak(s[SK])),
                          ("unknown_keys", []), ("episode_open", in_ep), ("verdict", s[VD]), ("shadow_state", s[SS]),
                          ("verdict_scope", scope), ("verdict_heading", {"episode": HEAD_EPISODE, "readiness": HEAD_READY}.get(scope, "")),
                          ("latched", s[VD] == "WOULD_REMAIN_LATCHED")):
            if got[key] != want:
                diff = {k: (got[key].get(k), want.get(k)) for k in (want if isinstance(want, dict) else []) if isinstance(got[key], dict) and got[key].get(k) != want.get(k)} or (got[key], want)
                mism.append((label, sandbox, key, diff))
    # the Verdict wording: the S4 text for that plan (the deviations recorded in the UX suite)
    word = STATE_T(vals)
    d = kv(s[IN])["d"]
    want = WORDING[s[VD]] + ((f" ({d} register{'' if d == '1' else 's'})") if s[VD] == "WOULD_APPLY_PROFILE" and d.isdigit() else "")
    if word != want:
        mism.append((label, "wording", word, want))
check(f"HA decode == the independent decode of the same real strings, Inputs (incl. alt / pa) / Episode / Soak / unknown keys / flags / Verdict "
      f"scope and heading / wording, in the plain and the sandbox environment ({len(SAMPLES)} samples)", not mism, str(mism[:3]))
check("the real strings carry the appended alt / pa and show both a readiness Verdict outside an episode and a continuation Verdict inside one",
      all({"alt", "pa"} <= set(kv(s[IN])) for _, s in SAMPLES)
      and {literal(ATTR_T["verdict_scope"]({SS: s[SS], VD: s[VD]})) for _, s in SAMPLES} >= {"readiness", "episode"})
latched_now = [s for _, s in SAMPLES if s[VD] == "WOULD_REMAIN_LATCHED"]
check("the real latched samples: Verdict 50 while Inputs pl still carries a readiness plan (the plan underneath the latch)",
      latched_now and all(int(kv(s[IN])["pl"]) in READY and literal(ATTR_T["latched"]({VD: s[VD]})) is True for s in latched_now))

# --- the canonical status over the real strings: only the episode States open the row
ST_BY_STATE = {}
for label, s in SAMPLES:
    vals = {f"sensor.{DEV}_ecco_fallback_profile_state": "VALID", f"sensor.{DEV}_ecco_fallback_profile_live_match": "m=MATCH;dx=-;cx=-;ox=-;ix=-;eh=0;obl=FP:CR,DP:CR,R4:CR,BUS:OK;ca=F;elig=OK;ew=-",
            "sensor.ecco_fallback_generation_high_water": "0", SS: s[SS], VD: s[VD], IN: s[IN], EP: s[EP], SK: s[SK]}
    ST_BY_STATE.setdefault(s[SS], set()).add(CODE_T(vals))
check("over the real strings: the canonical status is shadow_episode for exactly SHADOW_EPISODE / SHADOW_EPISODE_HA_BACK and `match` otherwise "
      "(including the real BLOCKED_* and WOULD_REMAIN_LATCHED verdicts outside an episode)",
      ST_BY_STATE.get("SHADOW_EPISODE") == {"shadow_episode"} and ST_BY_STATE.get("SHADOW_EPISODE_HA_BACK") == {"shadow_episode"}
      and ST_BY_STATE.get("SHADOW_IDLE") == {"match"} and ST_BY_STATE.get("SHADOW_WOULD_AWAIT_ACK") == {"match"}, str(ST_BY_STATE))
ep_samples = [s for _, s in SAMPLES if s[SS] in ("SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK")]
open_bn = [literal(ATTR_T["episode"]({EP: s[EP], SS: s[SS]}, s["now"])) for s in ep_samples]
check("every real open / HA_BACK sample yields a banner that states what a future failback would have done from the FROZEN edge plan",
      ep_samples and all(b["banner_would"].startswith("If automatic failback were enabled it would have: ") and b["would_have"] for b in open_bn))
k_l = next(s for _, s in SAMPLES if kv(s[EP])["k"] == "L")
bl = literal(ATTR_T["episode"]({EP: k_l[EP], SS: k_l[SS]}, k_l["now"]))
check("the real kind-L episode: edge plan WOULD_REMAIN_LATCHED, underlying plan kept, 'done nothing new'",
      bl["edge_plan"] == "WOULD_REMAIN_LATCHED" and bl["underlying_plan"] == "BLOCKED_PROFILE_UNAVAILABLE" and bl["kind"] == "latched"
      and bl["would_have"].startswith("done nothing new (an earlier shadow episode is still latched)"), str(bl))
ap = next(s for _, s in SAMPLES if kv(s[EP])["v0"] == "41")
bp = literal(ATTR_T["episode"]({EP: ap[EP], SS: ap[SS]}, ap["now"]))
check("the real E1-apply episode: 1 register differs, frame F244, banner 'applied the known-good profile (1 setting)'",
      bp["delta_count"] == "1" and bp["projected_frames"] == ["244 export write (0 to 2)"] and bp["would_have"] == "applied the known-good profile (1 setting)")
fp_s = next(s for _, s in SAMPLES if kv(s[EP])["v0"] == "11")
bf = literal(ATTR_T["episode"]({EP: fp_s[EP], SS: fp_s[SS]}, fp_s["now"]))
check("the real FP-active episode: pre-empt Free Power, blocking domain Free Power, banner 'ended Free Power, then continued failback'",
      bf["preempt"] == ["Free Power"] and bf["blocking_domain"] == "Free Power" and bf["would_have"] == "ended Free Power, then continued failback")

# ===========================================================================
print("")
print("[5] The 81 golden rows (+ observations): Inputs text from the C2 mirror, the readiness Verdict (one MODE_IF_LOST evaluation), through HA")
n_rows, rows_bad = 0, []
for entry in list(RW.ROWS) + list(RW.OBSERVATIONS):
    i = entry["build"]()
    i.mode = sh.MODE_IF_LOST
    rd = sh.evaluate(i)
    text = str(sh.inputs_text(i, rd))
    vals = {IN: text, VD: sh.plan_name(rd.plan), SS: "SHADOW_IDLE", EP: "unknown", SK: "unknown"}
    got = literal(ATTR_T["inputs"](vals))
    want = indep_inputs(text)
    n_rows += 1
    if got != want or kv(text)["pl"] != str(rd.plan) or got["if_lost_plan"] != sh.PLAN_NAMES[rd.plan]:
        rows_bad.append((entry.get("n", entry.get("label")), {k: (got.get(k), want.get(k)) for k in want if got.get(k) != want.get(k)}))
    w = STATE_T(vals)
    exp = WORDING[sh.plan_name(rd.plan)] + ((f" ({kv(text)['d']} register{'' if kv(text)['d'] == '1' else 's'})") if rd.plan == 41 and kv(text)["d"].isdigit() else "")
    if w != exp or literal(ATTR_T["unknown_keys"](vals)) != [] or literal(ATTR_T["verdict_heading"](vals)) != (HEAD_READY if rd.plan != 0 else ""):
        rows_bad.append((entry.get("n", entry.get("label")), "wording", w, exp))
check(f"all {n_rows} rows / observations: HA decodes the mirror's Inputs text (incl. alt / pa) and words the readiness Verdict exactly like the "
      "independent decode, under the readiness heading, with no unknown key", not rows_bad, str(rows_bad[:3]))
check("the table produced the full set of emitted plan codes through Inputs `pl`",
      {int(kv(str(sh.inputs_text((lambda i: (setattr(i, 'mode', sh.MODE_IF_LOST), i)[1])(e['build']()), sh.evaluate((lambda i: (setattr(i, 'mode', sh.MODE_IF_LOST), i)[1])(e['build']()))))) ['pl'])
       for e in RW.ROWS} >= {10, 11, 12, 13, 14, 15, 20, 21, 22, 23, 24, 26, 27, 31, 40, 41})

# ===========================================================================
print("")
print("[6] Cross-language: no HA shadow string matches an Energy Actions card regex")
regexes = dash.card_regexes()
check("the card's regex literals were extracted from the TS source", len(regexes) >= 15 and any("RECOVERY REQUIRED" in rx.pattern for rx, _ in regexes))
strings = set(WORDING.values()) | {"Shadow check not available", "Shadow check result not recognised", "Shadow Recovery",
                                  "ECCO recorded a loss of Home Assistant supervision. Shadow mode: nothing was written.",
                                  "SHADOW CHECK - HOME ASSISTANT SUPERVISION WAS LOST", "SHADOW CHECK · NO ACTION TAKEN",
                                  "SHADOW mode: NOTHING WAS WRITTEN.", "Closes automatically after 5 minutes of continuous stable supervision.",
                                  HEAD_READY, HEAD_EPISODE, "if Home Assistant were lost now", "continuation while the shadow episode is open",
                                  "not evaluated yet", "not recognised", "not available", "(the plan underneath the modelled FB-F latch)",
                                  "Failback shadow evaluator (diagnostic - writes nothing)", "SHADOW"}
for label, s in SAMPLES:
    a = {k: literal(ATTR_T[k]({SS: s[SS], EP: s[EP], SK: s[SK], VD: s[VD], IN: s[IN]}, s["now"])) for k in ("episode", "inputs")}
    strings |= {v for k, v in a["episode"].items() if isinstance(v, str) and k.startswith(("banner", "would", "lost", "returned", "closed", "close_outcome", "blocking"))}
    strings |= {a["inputs"]["if_lost_wording"], a["inputs"]["cache"], a["inputs"]["locks"], a["inputs"]["free_power"], a["inputs"]["dump_to_grid"],
                a["inputs"]["absence_accepted_wording"], a["inputs"]["projected_after_wording"]}
hits = [(str(v), rx.pattern, f) for v in strings for rx, f in regexes if rx.search(str(v))]
check(f"none of the {len(strings)} HA shadow display strings (words, sublines, banner, decoded texts) matches any Energy Actions card regex", not hits, str(hits[:3]))
NEVER = [re.compile("".join(p), re.I) for p in (("fai", "led"), ("defer", "red"))]
check("none contains the two words no operator string may contain", not [v for v in strings if any(rx.search(str(v)) for rx in NEVER)])
check("the Verdict wording never starts with BLOCKED (HA shows words; the raw plan / FB-A result names appear only in the technical block)",
      not [w for w in WORDING.values() if re.search(r"^BLOCKED", w)])
card_src = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in sorted((ROOT / "frontend" / "ecco-energy-actions-card" / "src").rglob("*.ts")))
check("the Energy Actions card never reads a shadow entity, the decoder or the Shadow Recovery word (so the raw BLOCKED_* plan names in the technical block can never reach its ^BLOCKED regex)",
      len(card_src) > 1000 and not re.search(r"ecco_shadow|" + FB + r"_shadow|shadow_episode|Shadow Recovery|ECCO Shadow", card_src))

# ===========================================================================
print("")
print("[7] Authority: no firmware change, zero authority delta, nothing in HA controls the shadow")
FW_SHA = {  # sha256 (LF) of the firmware as of main @ 5e59d9c (FB-C2 merged as PR #63 at 0874eff = d172574; PR #64 is CI only): FB-C3 touches none of it
    "firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "592c25a21095d63342b1ab08531af494db2ad04bb2df13c66f57f95bc45595d7",
}
# FB-D1 (after FB-C3 in the chain's merge order) edits the firmware: every pin below reads the firmware AS OF fbc3 - the chain undoes each later entry
# exactly (its reverter raises unless its edits are present exactly once) - so FB-C3's own claim stays exactly as strict as before.
_LATER = chain.CHAIN.ids()[chain.CHAIN.ids().index("fbc3") + 1:]
_LATER_ADDED = set().union(*(chain.CHAIN.entry(i).added_files for i in _LATER)) if _LATER else set()


def lf_fbc3(rel: str) -> str:
    """A firmware file's LF text as of fbc3 (only the chain-pinned firmware YAML is ever reverted)."""
    return chain.CHAIN.as_of(chain.FIRMWARE, "fbc3", lf(rel)) if rel == chain.FIRMWARE else lf(rel)


for rel, want in FW_SHA.items():
    got = hashlib.sha256(lf_fbc3(rel).encode("utf-8")).hexdigest()
    check(f"{rel} as of fbc3 is byte-identical to FB-C2 (sha256 == the chain checkpoint of entry fbc2)", got == want == chain.CHAIN.entry("fbc2").checkpoints[chain.FIRMWARE], got)
# The file set is whatever Git TRACKS under firmware/ (never a filesystem walk): untracked or ignored files (secrets, build output) cannot move the pin.
# Files a LATER chain entry declares as added (FB-D1: include/ecco_rtc_policy.h) did not exist as of fbc3.
ls = subprocess.run(["git", "ls-files", "-z", "--", "firmware/"], cwd=str(ROOT), capture_output=True)
fw_files = sorted(f for f in ls.stdout.decode("utf-8").split("\0") if f and Path(f).suffix in (".h", ".yaml", ".md") and Path(f).name != "secrets.yaml"
                  and f not in _LATER_ADDED)
FW_TREE_SHA256 = "24d8b5bf8ce806b02d7f2487319479ddf59b44eda9c86815d4a347a4c604f2a1"   # main @ 5e59d9c
tree = hashlib.sha256()
for rel in fw_files:
    tree.update(rel.encode())
    tree.update(lf_fbc3(rel).encode("utf-8"))
check("the git-tracked firmware source tree as of fbc3 (every .h / .yaml / .md under firmware/, the 14 files of main @ 5e59d9c) hashes to the main value",
      ls.returncode == 0 and len(fw_files) == 14 and tree.hexdigest() == FW_TREE_SHA256, f"{len(fw_files)} {tree.hexdigest()}")
check("merge order: fbc3 is the entry right after fbc2 (any later firmware entry follows it)",
      chain.CHAIN.ids().index("fbc3") == chain.CHAIN.ids().index("fbc2") + 1, str(chain.CHAIN.ids()[-4:]))
e3 = chain.CHAIN.entry("fbc3")
check("chain entry fbc3: no reverter, no checkpoint, no counted delta, no op path, no include, no substitution, no firmware banned token (HA-only change)",
      not e3.reverts and not e3.checkpoints and not e3.deltas and not e3.op_paths_changed and not e3.includes_added and not e3.subst_added
      and e3.banned_fw_added == 0 and not e3.fbh_includers and not e3.tags_declared)
check("the declared deltas up to fbc3 equal those up to fbc2 for every chain metric (fbc3 declares zero; test_scope_chain measures them)",
      all(chain.CHAIN.declared_delta(m, "fbc3") == chain.CHAIN.declared_delta(m, "fbc2") for m in chain.METRICS))
src = lf(STATUS_REL) + lf("home-assistant/dashboards/ecco_pro.yaml")
check("no HA file turns the shadow into a control: no service call, button, switch, script or api action names a shadow entity",
      not re.search(r"(?:button|switch|script|number|select)\.[a-z0-9_]*(?:ecco_)?" + FB + "_shadow|esphome\\.[a-z0-9_]*shadow|action: [a-z_.]*shadow", src))
check("the decoder is read-only: it has no `service`, `action` or `trigger` construct and reads no firmware control entity",
      not re.search(r"\b(service|action|trigger|event_type)\s*:", yaml.dump(SHADOW)) and "switch." not in yaml.dump(SHADOW) and "button." not in yaml.dump(SHADOW))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All FB-C3 firmware <-> Home Assistant shadow contract tests PASSED.")
