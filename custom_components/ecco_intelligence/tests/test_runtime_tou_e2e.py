#!/usr/bin/env python3
"""WP-E: the grid-charge TOU classification end to end, from Home Assistant states to the published entities.

The BUILT kit runs under the stand-in Home Assistant (_fake_ha) with owner-record decisions (synthetic test values), the
harness's fresh synthetic states in the dongle's own vocabulary (slot 1 'Grid' with flags 1, the literal 'None' on the
other five slots, every mode 'None'; both poll texts moving; configuration-online, both enables on; every overlay off) and
the real vendored run_cycle: sources (WP-3) -> freshness (WP-1) -> classification and validity (WP-2) -> cadence (WP-4).

  [1] slot 1 Grid: charge_target and predicted_morning_soc OK with numbers, the TOU claim capped at UNCERTAIN,
      MORNING_SOC_ASSUMES_CHARGE; slot 3's charge source flipped to HA 'unknown' -> at the next tick every charge-window
      item and overnight_demand BLOCKED (TOU_SLOT_SOURCE_UNKNOWN) with no number while pv_tomorrow keeps its number;
      restored -> OK again within the refresh ceiling (900 s advice validity less the 125 s margin, plus a tick)
  [2] the table's other fail-closed cases from HA states: slot 3's start 'unavailable' (TOU_RING_INVALID), slot 4 'Grid'
      as a second run (TOU_MULTIPLE_GRID_WINDOWS), an overlay entity on (TOU_OVERLAY_ACTIVE), the TOU enable off
      (TOU_DISABLED), the grid-charge enable 'unavailable' (TOU_GRID_CHARGE_ENABLE_UNKNOWN)
  [3] a frozen configuration-poll text while the telemetry poll moves: the charge-window items stay OK while its age is
      below 175 s, are BLOCKED INPUT_EXPIRING (a refresh at every tick) once less than 125 s of validity is left, and
      BLOCKED CONFIG_LIVENESS_STALE past 300 s; pv_tomorrow keeps its number and the status is never STALE
  [4] configuration-online off: no configuration-poll reading and no configuration liveness reach the engine (the
      runtime withholds them), every charge-window item BLOCKED CONFIG_LIVENESS_MISSING with no number, pv_tomorrow keeps
      its number
  [5] the configuration poll seen 130 s old at every tick (one deferred poll): the TOU items stay OK (the 300 s bound
      tolerates it); 190 s: overnight_demand BLOCKED INPUT_EXPIRING and no charge-window number, pv_tomorrow numeric,
      never STALE, a refresh at every tick (refresh_input_expiring) with next_run_at the refresh floor; back to 30 s: the
      TOU items OK again at the next tick (the refresh on INPUT_EXPIRING, integration fixup)
  [6] the raise-only reserve helper (mapped) 'unavailable' -> at the next tick every item I-D1 gates BLOCKED
      PREF_RESERVE_RAISE_UNKNOWN with no number; '140' (out of range) the same; '55' raises the floor (PREF_RESERVE_RAISE,
      charge_target at least 55); unmapped -> no raise and no such code
Every scenario also ends with zero write attempts of any kind, no stand-in violation and the configuration tree unchanged
outside ecco/intelligence/state/. Synthetic data only (2030, test_* ids); no network, no real Home Assistant. Plain script;
exits 1 on any failure.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
NOW = datetime(2030, 1, 15, 20, 5, tzinfo=UTC)
PREFIX = "ecco_intel_tou_e2e_"
root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)
h = H.Harness(kit)
C = h.contract
COORD = importlib.import_module("custom_components.ecco_intelligence.coordinator")
SD = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.site_decisions")
SRC = importlib.import_module("custom_components.ecco_intelligence.runtime.sources")
ITEM_KEYS = C.ADVICE_ITEMS + C.FORECAST_ITEMS
# the published items resting on the charge window, and those I-D1 gates
TOU_ITEMS = ("charge_target", "overnight_demand", "export_event", "dump_to_grid", "predicted_morning_soc")
CW_ITEMS = tuple(k for k in SD.CHARGE_WINDOW_ITEMS if k in ITEM_KEYS)
D1_ITEMS = tuple(k for k in SD.items_gated_by("D1") if k in ITEM_KEYS)
CEILING_TICKS = int((900 - COORD.REFRESH_MARGIN_S) // COORD.TICK_S) + 2


class Scn:
    """One stand-in Home Assistant with the built integration set up on the generic test site file."""

    def __init__(self, name, profile, *, now=NOW):
        self.name = name
        self.cfg = root / name
        self.cfg.mkdir()
        self.hass = h.new_hass(self.cfg, now)
        # the world is set between ticks without state_changed events (as before A23), so these cases are judged at the
        # tick; the poll-driven refresh and its recovery times are test_runtime_poll_phase.py's
        self.hass.states.events = False
        H.write_site(self.cfg, profile)
        self.after_seed = None                 # a callable(scn) run after every re-seed (the scenario's own states)
        H.seed_fresh_states(self.hass.states, now)
        h.recorder().statistics = H.synthetic_statistics(now, days=30)
        self.before = H.tree_hashes(self.cfg)
        self.entry = h.new_entry()
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        self.c.grace_s = 120.0

    def seed(self):
        H.seed_fresh_states(self.hass.states, h.now)
        if self.after_seed is not None:
            self.after_seed(self)

    def advance(self, n=1):
        for _ in range(n):
            h.set_now(h.now + timedelta(seconds=60))
            self.seed()
            h.tick(0, settle=10.0)

    def warm(self):
        """Three ticks with moving poll texts (both liveness memories confirmed), past the grace: the first cycle runs."""
        self.advance(3)

    def attrs(self, key="status"):
        s = h.state(key)
        return {} if s is None else dict(s.attributes)

    def status(self, key):
        return self.attrs(key).get("status")

    def numeric(self, keys=ITEM_KEYS):
        return [k for k in keys if H.numeric_state(h.state(k))]

    def codes(self, key):
        """Every code on the last computed result's item: its blockers and its reason codes."""
        lc = self.c._last_computed  # noqa: SLF001
        if lc is None:
            return set()
        v = {x.key: x for x in tuple(lc.items) + tuple(lc.forecasts)}.get(key)
        return set() if v is None else {c for c, _t in v.blockers} | set(v.reason_codes)

    def close(self):
        if self.c is not None and not self.c.closed:
            h.unload(self.entry)
        after = H.tree_hashes(self.cfg)
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k)
                         and not k.startswith("ecco/intelligence/state/"))
        check(f"{self.name}: zero write attempts", not self.hass.write_attempts, str(self.hass.write_attempts[:3]))
        check(f"{self.name}: no stand-in violation", not self.hass.violations, str(self.hass.violations[:3]))
        check(f"{self.name}: the configuration tree changed only under ecco/intelligence/state/", not changed, str(changed[:3]))


def owner_profile(readings=None):
    return H.site_profile(decisions=H.owner_decisions(), readings=readings)


def withheld(s, keys, code, *, code_keys=None):
    """(passed, detail): every item in `code_keys` (default `keys`) BLOCKED with `code`, every item in `keys` not OK and
    without a number, pv_tomorrow showing its number, and the status not STALE (a computed result)."""
    ck = keys if code_keys is None else code_keys
    bad = {k: (s.status(k), sorted(s.codes(k))[:4]) for k in ck if s.status(k) != "BLOCKED" or code not in s.codes(k)}
    shown = [k for k in keys if s.status(k) == "OK"]
    nums = s.numeric(keys)
    pv = H.numeric_state(h.state("pv_tomorrow"))
    st = h.state("status").state
    return (not bad and not shown and not nums and pv and st != "STALE"), f"{bad} ok={shown} numbers={nums} pv={pv} status={st}"


def ok_with_numbers(s, keys=("charge_target", "predicted_morning_soc")):
    return all(s.status(k) == "OK" for k in keys) and set(s.numeric(keys)) == set(keys)


try:
    # -----------------------------------------------------------------------------------------------------------------
    print("== [1] slot 1 Grid -> OK; slot 3's charge source 'unknown' -> BLOCKED; restored -> OK again")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("slot_grid", owner_profile())
    s.warm()
    check("non-vacuity: slot 1 'Grid' (literal 'None' elsewhere): charge_target and predicted_morning_soc OK with numbers",
          ok_with_numbers(s), f"{s.status('charge_target')} {sorted(s.codes('charge_target'))[:8]}")
    check("... the TOU claim capped at UNCERTAIN on charge_target, MORNING_SOC_ASSUMES_CHARGE on predicted_morning_soc",
          "TOU_CLAIM_UNCERTAIN" in s.codes("charge_target") and "TOU_CLAIM_CONFIGURED" not in s.codes("charge_target")
          and "MORNING_SOC_ASSUMES_CHARGE" in s.codes("predicted_morning_soc"), str(sorted(s.codes("charge_target"))))
    s.after_seed = lambda scn: scn.hass.states.seed(H.slot_eid(3, "charge_source"), "unknown")
    s.advance()
    ok_, detail = withheld(s, TOU_ITEMS, "TOU_SLOT_SOURCE_UNKNOWN")
    check("slot 3's charge source 'unknown' (HA) -> at the next tick every charge-window item and overnight_demand BLOCKED "
          "TOU_SLOT_SOURCE_UNKNOWN with no number; pv_tomorrow keeps its number", ok_, detail)
    s.after_seed = None
    back = None
    for i in range(CEILING_TICKS):
        s.advance()
        if ok_with_numbers(s):
            back = i + 1
            break
    check(f"slot 3 restored -> charge_target OK with a number again within the refresh ceiling ({CEILING_TICKS} ticks)",
          back is not None, f"{s.status('charge_target')} after {CEILING_TICKS} ticks")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [2] the table's other fail-closed cases from Home Assistant states")
    # -----------------------------------------------------------------------------------------------------------------
    cases = (
        ("slot3_start_unavailable", "TOU_RING_INVALID", "slot 3's start 'unavailable' (null start: the ring is refused)",
         lambda scn: scn.hass.states.seed(H.slot_eid(3, "start"), "unavailable")),
        ("second_grid_run", "TOU_MULTIPLE_GRID_WINDOWS", "slot 4 'Grid' (flags 1): a second, separate grid run",
         lambda scn: (scn.hass.states.seed(H.slot_eid(4, "charge_source"), "Grid"),
                      scn.hass.states.seed(H.slot_eid(4, "flags_raw"), "1"))),
        ("overlay_on", "TOU_OVERLAY_ACTIVE", "an overlay entity on (Free Power active)",
         lambda scn: scn.hass.states.seed(H.OVERLAY_ENTITIES[0], "on")),
        ("tou_disabled", "TOU_DISABLED", "the TOU enable off",
         lambda scn: scn.hass.states.seed(H.TOU_ENABLED, "off")),
        ("grid_enable_unknown", "TOU_GRID_CHARGE_ENABLE_UNKNOWN", "the grid-charge enable 'unavailable'",
         lambda scn: scn.hass.states.seed(H.GRID_CHARGE_ENABLED, "unavailable")),
    )
    for name, code, label, mutate in cases:
        s = Scn(name, owner_profile())
        s.after_seed = mutate
        mutate(s)
        s.warm()
        ok_, detail = withheld(s, TOU_ITEMS, code, code_keys=CW_ITEMS)
        check(f"{label} -> every charge-window item BLOCKED {code}, no charge-window number; pv_tomorrow keeps its number",
              ok_ and s.status("overnight_demand") == "BLOCKED", detail)
        s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [3] a frozen configuration-poll text while the telemetry poll moves")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("config_frozen", owner_profile())
    s.warm()
    check("non-vacuity: charge_target OK before the freeze", ok_with_numbers(s), s.status("charge_target"))
    frozen = s.hass.states._states[H.CONFIG_POLL_TEXT].state  # noqa: SLF001
    last_change = h.now - timedelta(seconds=H.CONFIG_POLL_AGE_S)
    s.after_seed = lambda scn: scn.hass.states.seed(H.CONFIG_POLL_TEXT, frozen)
    rows = []
    for _ in range(8):
        r0 = s.c.counters["refresh_runs_started"]
        s.advance()
        lc = s.c._last_computed  # noqa: SLF001
        rows.append(((lc.generated_at - last_change).total_seconds(), s.status("charge_target"),
                     "INPUT_EXPIRING" in s.codes("charge_target") | s.codes("overnight_demand"),
                     "CONFIG_LIVENESS_STALE" in s.codes("charge_target"), bool(s.numeric(TOU_ITEMS)),
                     H.numeric_state(h.state("pv_tomorrow")), h.state("status").state,
                     s.c.counters["refresh_runs_started"] > r0))
    fresh_rows = [r for r in rows if r[0] < 300.0 - COORD.REFRESH_MARGIN_S]
    exp_rows = [r for r in rows if 300.0 - COORD.REFRESH_MARGIN_S <= r[0] <= 300.0]
    stale_rows = [r for r in rows if r[0] > 300.0]
    check("configuration-poll age below 175 s at compute time: charge_target still OK with a number",
          bool(fresh_rows) and all(r[1] == "OK" and r[4] for r in fresh_rows), str(fresh_rows))
    check("175 s to 300 s: INPUT_EXPIRING (the charge-window items withheld, no number) and a refresh at every such tick",
          bool(exp_rows) and all(r[2] and not r[4] and r[7] for r in exp_rows), str(exp_rows))
    check("past 300 s: charge_target BLOCKED CONFIG_LIVENESS_STALE, no charge-window number",
          bool(stale_rows) and all(r[1] == "BLOCKED" and r[3] and not r[4] for r in stale_rows), str(stale_rows))
    check("throughout: pv_tomorrow keeps its number and the status is never STALE", all(r[5] and r[6] != "STALE" for r in rows),
          str(rows))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [4] configuration-online off: the configuration-poll readings are withheld")
    # -----------------------------------------------------------------------------------------------------------------
    built = []
    orig_build = SRC.build_sources

    def spy_build(*a, **kw):
        r = orig_build(*a, **kw)
        built.append(r)
        return r
    SRC.build_sources = spy_build
    try:
        s = Scn("config_offline", owner_profile())
        s.warm()
        on_keys = {r.key for r in built[-1].site_readings} if built else set()
        check("non-vacuity: configuration-online on -> the configuration liveness and every configuration-poll reading reach "
              "the engine, and charge_target is OK", {SD.CONFIG_LIVENESS_KEY, *SD.CONFIG_POLL_READINGS} <= on_keys
              and ok_with_numbers(s), f"{sorted({SD.CONFIG_LIVENESS_KEY, *SD.CONFIG_POLL_READINGS} - on_keys)}")
        s.after_seed = lambda scn: scn.hass.states.seed(H.CONFIG_ONLINE, "off")
        n0 = len(built)
        s.advance()
        off_keys = [{r.key for r in x.site_readings} for x in built[n0:]]
        check("configuration-online 'off' -> no configuration liveness and no configuration-poll reading reaches the engine",
              bool(off_keys) and all(not ({SD.CONFIG_LIVENESS_KEY, *SD.CONFIG_POLL_READINGS} & k) for k in off_keys),
              str([sorted({SD.CONFIG_LIVENESS_KEY, *SD.CONFIG_POLL_READINGS} & k) for k in off_keys]))
        ok_, detail = withheld(s, TOU_ITEMS, "CONFIG_LIVENESS_MISSING", code_keys=CW_ITEMS)
        check("... every charge-window item BLOCKED CONFIG_LIVENESS_MISSING (overnight_demand: no table), no number; "
              "pv_tomorrow keeps its number", ok_ and "CHARGE_WINDOW_UNKNOWN" in s.codes("overnight_demand"), detail)
        s.close()
    finally:
        SRC.build_sources = orig_build

    # -----------------------------------------------------------------------------------------------------------------
    print("== [5] the configuration poll 130 s old (one deferred poll), then 190 s, then 30 s again")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("config_age", owner_profile())
    age = {"s": float(H.CONFIG_POLL_AGE_S)}

    def config_aged(scn):
        """A configuration-poll text that changed `age` seconds ago, seen to change at every tick."""
        at = h.now - timedelta(seconds=age["s"])
        scn.hass.states.seed(H.CONFIG_POLL_TEXT, at.strftime("%Y-%m-%d %H:%M:%S"), changed_at=at)
    s.after_seed = config_aged
    s.warm()
    check("non-vacuity: configuration poll 30 s old -> charge_target OK", ok_with_numbers(s), s.status("charge_target"))
    age["s"] = 130.0
    s.advance(3)
    lc = s.c._last_computed  # noqa: SLF001
    check("130 s at every tick: the TOU items stay OK with numbers, valid at least REFRESH_MARGIN_S, no INPUT_EXPIRING",
          ok_with_numbers(s) and "INPUT_EXPIRING" not in set().union(*(s.codes(k) for k in TOU_ITEMS))
          and (lc.item("charge_target").valid_until - lc.generated_at).total_seconds() >= COORD.REFRESH_MARGIN_S,
          f"{s.status('charge_target')} {sorted(s.codes('charge_target'))[:6]}")
    age["s"] = 190.0
    s.advance()
    r0 = s.c.counters["refresh_input_expiring"]
    rows = []
    for _ in range(3):
        n0 = s.c.counters["runs_started"]
        s.advance()
        a_ = s.attrs()
        rows.append((s.c.counters["runs_started"] - n0, "INPUT_EXPIRING" in s.codes("overnight_demand"),
                     bool(s.numeric(TOU_ITEMS)), H.numeric_state(h.state("pv_tomorrow")), h.state("status").state,
                     (datetime.fromisoformat(a_["next_run_at"]) - datetime.fromisoformat(a_["generated_at"])).total_seconds()))
    check("190 s: overnight_demand BLOCKED INPUT_EXPIRING and no charge-window number, pv_tomorrow numeric, never STALE",
          all(r[1] and not r[2] and r[3] and r[4] != "STALE" for r in rows), str(rows))
    check("... a refresh at every tick (refresh_input_expiring) and next_run_at the refresh floor after the cycle start",
          all(r[0] == 1 and abs(r[5] - COORD.PROPOSED_REFRESH_FLOOR_S) <= 1.0 for r in rows)
          and s.c.counters["refresh_input_expiring"] >= r0 + 3, f"{rows} {s.c.counters['refresh_input_expiring'] - r0}")
    age["s"] = float(H.CONFIG_POLL_AGE_S)
    s.advance()
    check("back to 30 s: the TOU items OK with numbers again at the next tick", ok_with_numbers(s),
          f"{s.status('charge_target')} {sorted(s.codes('charge_target'))[:6]}")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [6] the raise-only reserve helper")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("raise_unavailable", owner_profile())
    s.warm()
    check("non-vacuity: the helper at 0 % -> charge_target OK, no PREF_RESERVE_RAISE code", ok_with_numbers(s)
          and not {"PREF_RESERVE_RAISE", "PREF_RESERVE_RAISE_UNKNOWN"} & s.codes("charge_target"), s.status("charge_target"))
    s.after_seed = lambda scn: scn.hass.states.seed(H.RESERVE_RAISE_HELPER, "unavailable", {"unit_of_measurement": "%"})
    s.advance()
    ok_, detail = withheld(s, D1_ITEMS, "PREF_RESERVE_RAISE_UNKNOWN")
    check(f"the helper (mapped) 'unavailable' -> at the next tick every item I-D1 gates {list(D1_ITEMS)} BLOCKED "
          "PREF_RESERVE_RAISE_UNKNOWN with no number; pv_tomorrow keeps its number",
          ok_ and {"charge_target", "predicted_morning_soc"} <= set(D1_ITEMS), detail)
    check("... overnight_demand, which I-D1 does not gate, keeps its number", s.status("overnight_demand") == "OK"
          and "overnight_demand" in s.numeric(), s.status("overnight_demand"))
    s.close()
    for name, value, label in (("raise_out_of_range", "140", "'140' (out of range)"),):
        s = Scn(name, owner_profile())
        s.after_seed = lambda scn, v=value: scn.hass.states.seed(H.RESERVE_RAISE_HELPER, v, {"unit_of_measurement": "%"})
        s.after_seed(s)
        s.warm()
        ok_, detail = withheld(s, D1_ITEMS, "PREF_RESERVE_RAISE_UNKNOWN")
        check(f"the helper {label} -> every item I-D1 gates BLOCKED PREF_RESERVE_RAISE_UNKNOWN, no number", ok_, detail)
        s.close()
    s = Scn("raise_binds", owner_profile())
    s.after_seed = lambda scn: scn.hass.states.seed(H.RESERVE_RAISE_HELPER, "55", {"unit_of_measurement": "%"})
    s.after_seed(s)
    s.warm()
    ct_ = h.state("charge_target")
    check("the helper at 55 % (above I-D1's 30 %) -> charge_target OK with PREF_RESERVE_RAISE and a target of at least 55 %",
          ok_with_numbers(s) and "PREF_RESERVE_RAISE" in s.codes("charge_target") and float(ct_.state) >= 55.0,
          f"{s.status('charge_target')} {ct_.state if ct_ else None} {sorted(s.codes('charge_target'))[:8]}")
    s.close()
    s = Scn("raise_unmapped", owner_profile(readings={k: v for k, v in H.READING_MAP.items()
                                                      if k != "pref.advisory_reserve_raise_pct"}))
    s.after_seed = lambda scn: scn.hass.states.seed(H.RESERVE_RAISE_HELPER, "unavailable", {"unit_of_measurement": "%"})
    s.after_seed(s)
    s.warm()
    check("the helper not mapped (its entity unavailable) -> no raise: charge_target OK, no PREF_RESERVE_RAISE* code",
          ok_with_numbers(s) and not {"PREF_RESERVE_RAISE", "PREF_RESERVE_RAISE_UNKNOWN"} & s.codes("charge_target"),
          f"{s.status('charge_target')} {sorted(s.codes('charge_target'))[:8]}")
    s.close()
finally:
    h.loop.close()
    H.rmtree_own(root, PREFIX)

check("the temporary directory is removed", not root.exists(), str(root))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the TOU end-to-end suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all TOU end-to-end checks passed")
