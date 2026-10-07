#!/usr/bin/env python3
"""ecco_core.state: observations keep raw / normalised / derived apart, refuse what they cannot represent, and a snapshot
is immutable with one observation per signal. Pure, synthetic, offline."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ecco_core.state import DERIVED, NORMALIZED, RAW, SIGNALS, Observation, Snapshot, spec_for  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def refuses(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


UTC = timezone.utc
NOW = datetime(2030, 5, 1, 12, 0, tzinfo=UTC)

print("[1] signals and units")
check("every signal has a description; families end in '.*'", all(s.description and (("*" not in n) or n.endswith(".*"))
                                                                   for n, s in SIGNALS.items()))
check("sign conventions are stated for battery and grid power",
      "discharg" in (SIGNALS["battery.power"].sign or "") and "import" in (SIGNALS["grid.power"].sign or ""))
check("a family member resolves to its family", spec_for("pv.forecast.today.s000_solcast").name == "pv.forecast.today.*")
check("an unknown name does not resolve", spec_for("battery.socc") is None and spec_for("pv.forecast.today") is None)
check("an unknown signal is refused (no silent typo signals)",
      refuses(lambda: Observation("battery.socc", 50.0, NOW, "x")))
check("the canonical unit is filled in", Observation("battery.soc", 50.0, NOW, "x").unit == "%")
check("a different unit is refused", refuses(lambda: Observation("battery.soc", 0.5, NOW, "x", unit="fraction")))

print("[2] values, times and kinds")
for bad in (float("nan"), float("inf"), -float("inf"), [1], {"a": 1}):
    check(f"value {bad!r} is refused", refuses(lambda b=bad: Observation("battery.soc", b, NOW, "x")))
check("None, bool, str and finite numbers are accepted for a unit-less signal",
      all(Observation("inverter.state", v, NOW, "x").value == v for v in (None, True, "normal", 3, 2.5)))
for bad in ("unavailable", "55", True, False):
    check(f"a measured signal (battery.soc, %) refuses {bad!r}: a reading is a number or nothing",
          refuses(lambda b=bad: Observation("battery.soc", b, NOW, "ha:x")))
check("...but keeps such a source value in raw, with the value None",
      Observation("battery.soc", None, NOW, "ha:x", raw="unavailable").raw == "unavailable")
check("a naive observation time is refused", refuses(lambda: Observation("battery.soc", 1.0, datetime(2030, 5, 1, 12), "x")))
check("an empty source is refused", refuses(lambda: Observation("battery.soc", 1.0, NOW, "")))
check("an unknown kind is refused", refuses(lambda: Observation("battery.soc", 1.0, NOW, "x", kind="guessed")))
check("DERIVED requires derived_from", refuses(lambda: Observation("pv.power", 1.0, NOW, "x", DERIVED)))
check("only DERIVED may name derived_from", refuses(lambda: Observation("pv.power", 1.0, NOW, "x", NORMALIZED,
                                                                        derived_from=("pv.string_power.1",))))
check("derived_from must name known signals",
      refuses(lambda: Observation("pv.power", 1.0, NOW, "x", DERIVED, derived_from=("pv.typo",))))
o = Observation("battery.soc", 50.0, NOW - timedelta(seconds=30), "x")
check("age is now minus observation time", o.age_s(NOW) == 30.0)
check("an observation from the future has an UNKNOWN age (never zero)",
      Observation("battery.soc", 50.0, NOW + timedelta(seconds=5), "x").age_s(NOW) is None)
check("an unknown observation time has an unknown age", Observation("battery.soc", 50.0, None, "x").age_s(NOW) is None)
check("value None means unavailable", Observation("battery.soc", None, NOW, "x").available is False and o.available)

print("[3] raw and derived stay apart")
raw = Observation("battery.power", -200.0, NOW, "controller:register:190", NORMALIZED, raw=0xFF38)
s1 = Observation("pv.string_power.1", 1200.0, NOW, "c", NORMALIZED, raw=1200)
s2 = Observation("pv.string_power.2", 800.0, NOW, "c", NORMALIZED, raw=800)
tot = Observation("pv.power", 2000.0, NOW, "c", DERIVED, derived_from=("pv.string_power.1", "pv.string_power.2"))
snap = Snapshot.of(NOW, [raw, s1, s2, tot])
check("the raw word survives next to the normalised value", snap.get("battery.power").raw == 0xFF38
      and snap.value("battery.power") == -200.0)
check("a derived total sits beside, never instead of, its inputs",
      snap.value("pv.power") == 2000.0 and snap.value("pv.string_power.1") == 1200.0 and snap.get("pv.power").kind == DERIVED)
check("RAW is a distinct kind", Observation("battery.soc", None, NOW, "c", RAW, raw=99999).kind == RAW)

print("[4] snapshots")
check("two observations for one signal are refused", refuses(lambda: Snapshot.of(NOW, [o, o])))
check("a naive as_of is refused", refuses(lambda: Snapshot.of(datetime(2030, 5, 1), [o])))
check("a key that does not match its observation is refused", refuses(lambda: Snapshot(NOW, {"battery.power": o})))
mut = False
try:
    snap.observations["battery.soc"] = o            # type: ignore[index]
except TypeError:
    mut = True
check("a snapshot's observations cannot be mutated", mut)
fz = False
try:
    o.value = 1.0                                    # type: ignore[misc]
except Exception:  # noqa: BLE001 - FrozenInstanceError
    fz = True
check("an observation cannot be mutated", fz)
check("signals(prefix) lists a family in order", snap.signals("pv.string_power.") == ("pv.string_power.1", "pv.string_power.2"))
check("a missing signal reads as None with an unknown age", snap.value("grid.power") is None and snap.age_s("grid.power") is None)
check("to_dict is strict JSON", json.loads(json.dumps(snap.to_dict(), allow_nan=False))["as_of"] == NOW.isoformat())

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in ecco_core state:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll ecco_core state checks passed")
