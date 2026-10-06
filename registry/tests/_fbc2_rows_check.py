"""Runner: evaluates the 81 golden rows (and their extras) against the Python mirror registry/failback_shadow.py.

Prints one line per row: PASS, or FAIL with every differing field (expected vs got). Exit code 0 only if all 81 rows pass
(extras attached to a row count toward that row; the FINAL-document extras are reported separately and also gate the code).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import failback_shadow as sh  # noqa: E402
import _fbc2_rows as rows  # noqa: E402

FRAMES = (("F244", sh.FR_F244), ("F256_DOWN", sh.FR_F256_DOWN), ("F268_279", sh.FR_F268_279), ("F256_UP", sh.FR_F256_UP))
RS_NAME = {v: k for k, v in sh.RS.items()}
BD_NAME = {0: "NONE", 1: "SUPERVISION", 2: "BOOT", 3: "DUMP", 4: "FP", 5: "R244", 6: "BUS", 7: "MTOU", 8: "MTOU_JOURNAL",
           9: "FBP", 10: "SITE", 11: "LIVE"}
ROW_NAME = {getattr(sh, n): n[4:] for n in dir(sh) if n.startswith("ROW_")}
EH_NAME = {0: "UNKNOWN", 1: "NO", 2: "YES"}


def pn(plan):
    return f"{plan}:{sh.PLAN_NAMES.get(plan, '?')}"


def rn(reason):
    return f"{reason}:{RS_NAME.get(reason, '?')}"


def frames_of(mask):
    return {n for n, b in FRAMES if mask & b}


def check(exp: dict, plan: "sh.ShadowPlan") -> list:
    """Compare the keys present in `exp` (a key missing or None is not checked, except where None is meaningful)."""
    d = []

    def cmp(name, e, g, fmt=str):
        if e != g:
            d.append(f"{name}: expected {fmt(e)} got {fmt(g)}")

    if "plan" in exp:
        cmp("plan", exp["plan"], plan.plan, pn)
    if "reason" in exp:
        cmp("reason", exp["reason"], plan.reason, rn)
    if "blocking_domain" in exp:
        cmp("blocking_domain", exp["blocking_domain"], plan.blocking_domain, lambda v: BD_NAME.get(v, v))
    if "row" in exp and exp["row"] is not None:
        cmp("precedence_row", exp["row"], plan.row, lambda v: ROW_NAME.get(v, v))
    if "fba" in exp:
        got = None if plan.fba_state == sh.NONE_U8 else (plan.fba_state, plan.fba_result)
        cmp("fba(state,result)", exp["fba"], got)
    if "fba_a" in exp:
        got = None if plan.fba_result_policy_a == sh.NONE_U8 else plan.fba_result_policy_a
        cmp("fba_result_policy_a", exp["fba_a"], got)
    if "pre" in exp:
        got = "FP+DUMP" if plan.would_preempt_fp and plan.would_preempt_dump else "FP" if plan.would_preempt_fp else \
            "DUMP" if plan.would_preempt_dump else None
        cmp("pre", exp["pre"], got)
    if "app" in exp:
        cmp("app", exp["app"], int(plan.would_apply))
    if "frames" in exp:
        cmp("frames", sorted(exp["frames"]), sorted(frames_of(plan.projected_frames)))
    if exp.get("hazard") is not None:
        cmp("export_hazard", exp["hazard"], plan.export_hazard, lambda v: EH_NAME.get(v, v))
    if exp.get("alt") is not None:
        cmp("alt_plan_absence_accepted", exp["alt"], plan.alt_plan_absence_accepted, pn)
    if exp.get("projected_after") is not None:
        cmp("projected_after", exp["projected_after"], plan.projected_after, pn)
    for k, v in (exp.get("flags") or {}).items():
        cmp("flag " + k, v, bool(getattr(plan, k)))
    for k, v in (exp.get("masks") or {}).items():
        cmp("mask " + k, v, getattr(plan, k), lambda x: hex(x))
    if exp.get("dump_detail") is not None:
        cmp("dom[DUMP].detail", exp["dump_detail"], plan.dom[sh.DS_DUMP].detail, lambda x: hex(x))
    if exp.get("would_write_244") is not None:
        cmp("would_write_244", exp["would_write_244"], bool(plan.would_write_244))
    return d


def run_one(label, build, mode, exp):
    inp = build()
    inp.mode = mode
    try:
        plan = sh.evaluate(inp)
    except Exception as e:  # noqa: BLE001 - a crash is a failure of the row, reported
        return [f"{label}: evaluate() raised {type(e).__name__}: {e}"]
    return [f"{label}: {x}" for x in check(exp, plan)]


def main() -> int:
    failed, passed = [], 0
    for r in rows.ROWS:
        diffs = run_one("main", r["build"], r["mode"], r["expect"])
        if "readiness_plan" in r:
            diffs += run_one("readiness(IF_LOST)", r["build"], sh.MODE_IF_LOST, r["readiness_plan"])
        for e in r["extra"]:
            diffs += run_one(e["label"], e["build"], e["mode"], e["expect"])
        if diffs:
            failed.append(r["n"])
            print(f"FAIL row {r['n']:>2} {r['title']}")
            for x in diffs:
                print(f"       {x}")
            if r["note"]:
                print(f"       note: {r['note']}")
        else:
            passed += 1
            print(f"PASS row {r['n']:>2} {r['title']}")
    print()
    xfail = 0
    for e in rows.FINAL_EXTRAS:
        diffs = run_one("extra", e["build"], e["mode"], e["expect"])
        if diffs:
            xfail += 1
            print(f"FAIL extra {e['label']}")
            for x in diffs:
                print(f"       {x}")
        else:
            print(f"PASS extra {e['label']}")
    print()
    ofail = 0
    for e in getattr(rows, "OBSERVATIONS", []):
        diffs = run_one("obs", e["build"], e["mode"], e["expect"])
        if diffs:
            ofail += 1
            print(f"OBS-FAIL {e['label']}")
            for x in diffs:
                print(f"       {x}")
        else:
            print(f"OBS-PASS {e['label']}")
    print()
    print(f"rows: {passed} PASS / {len(failed)} FAIL of {len(rows.ROWS)}" + (f"  (failing: {failed})" if failed else ""))
    print(f"FINAL extras: {len(rows.FINAL_EXTRAS) - xfail} PASS / {xfail} FAIL")
    print(f"observations (non-gating): {len(getattr(rows, 'OBSERVATIONS', [])) - ofail} PASS / {ofail} FAIL")
    return 0 if (not failed and not xfail and len(rows.ROWS) == 81) else 1


if __name__ == "__main__":
    sys.exit(main())
