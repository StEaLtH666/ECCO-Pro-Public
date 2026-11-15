#!/usr/bin/env python3
"""Geek Mode fixtures suite (ECCO Intelligence tab): the synthetic Home Assistant state fixtures for the card tests.

  [1] `tools/gen_geek_fixtures.py --check` passes (the committed files equal a fresh regeneration, byte for byte)
  [2] shape: a map entity_id -> {state, attributes, last_changed, last_updated}; a state is always a text; Home Assistant's standard
      attributes are there; timestamps are fictional 2030 and ISO
  [3] built from the real contract builders: the stale, paused and self-test-failed fixtures carry exactly the contract fixtures'
      payloads; the healthy fixture carries exactly the payload of the real builder; nothing is hand-written
  [4] parity with what a running Home Assistant exposes: the healthy fixture's attribute names equal the live shape listing's, entity
      by entity; no fixture carries an attribute the catalogue does not declare (the extras fixture on purpose, and only there)
  [5] each fixture means what it says (the null rule, the pause, the watchdog, the timing against stale_after_s)
  [6] extras and noise: new ecco_intel_ entities to be discovered, lookalikes not to be; unrelated entities and decoys that no
      Production or Geek row may ever show; none of them is a catalogued entity or an ecco_intel_ one (except the extras on purpose)
  [7] determinism and scale

Test-only, no network, nothing live.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geek_scratch import ROOT, check, finish, run_tool  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import gen_geek_fixtures as F  # noqa: E402
import geek_mode_coverage as G  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402

FX = ROOT / G.FIXTURE_DIR_REL
cat = json.loads((ROOT / G.CATALOGUE_REL).read_bytes())
by_eid = {s["entity_id"]: s for s in cat["sources"]}
declared = {s["entity_id"]: {a["name"] for a in s["attributes"]} for s in cat["sources"]}
fx = {n: json.loads((FX / f"intelligence.states.{n}.json").read_bytes()) for n in G.FIXTURE_NAMES}
meta = json.loads((FX / "intelligence.states.meta.json").read_bytes())
noise = json.loads((FX / "noise.states.json").read_bytes())
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$")


def when(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ===========================================================================
print("[1] regeneration")
# ===========================================================================
rc, out = run_tool("gen_geek_fixtures.py", "--check")
check("gen_geek_fixtures.py --check passes: every committed fixture equals a fresh regeneration", rc == 0, out[-300:])
own = sorted(p.name for p in FX.iterdir() if p.name.startswith(("intelligence.", "noise.")))
check("the eight intelligence fixtures, the noise fixture and the meta file exist (other files may share the folder; these are ours)",
      own == sorted([f"intelligence.states.{n}.json" for n in G.FIXTURE_NAMES] + ["noise.states.json", "intelligence.states.meta.json"]), str(own))
raw_files = [p for p in FX.iterdir() if p.name.startswith(("intelligence.", "noise."))]
check("every fixture file is plain ASCII, LF only, one final newline", all(p.read_bytes().isascii() and b"\r" not in p.read_bytes()
                                                                            and p.read_bytes().endswith(b"\n") for p in raw_files))

# ===========================================================================
print("")
print("[2] shape")
# ===========================================================================
for name, states in list(fx.items()) + [("noise", noise)]:
    ok = all(isinstance(e, str) and re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", e) and set(r) == {"state", "attributes", "last_changed", "last_updated"}
             and isinstance(r["state"], str) and isinstance(r["attributes"], dict) and ISO.match(r["last_changed"]) and ISO.match(r["last_updated"])
             for e, r in states.items())
    check(f"{name}: every entry is exactly {{state: text, attributes: object, last_changed, last_updated}}, keyed by a valid entity id", ok)
    check(f"{name}: every timestamp is fictional (year 2030)", all(r["last_changed"].startswith("2030-") and r["last_updated"].startswith("2030-") for r in states.values()))
    check(f"{name}: entries are sorted by entity id (deterministic)", list(states) == sorted(states))
iso_values = [v for n, s in fx.items() for r in s.values() for v in re.findall(r"\d{4}-\d\d-\d\dT", json.dumps(r))]
check("every timestamp inside the intelligence fixtures' attributes is also 2030", all(v.startswith("2030-") for v in iso_values) and iso_values)
check("the meta file names every fixture with its file, status, reference clock and what it proves",
      set(meta["fixtures"]) == set(G.FIXTURE_NAMES) and all({"file", "reference_now", "status", "what"} <= set(m) for m in meta["fixtures"].values())
      and all(ISO.match(m["reference_now"]) for m in meta["fixtures"].values()))
check("the meta file states the entry shape and that everything is synthetic", meta["schema"] == "ecco-geek-fixtures/1" and "SYNTHETIC" in meta["note"])

# ===========================================================================
print("")
print("[3] built from the real contract builders")
# ===========================================================================
c = F.Contract(ROOT)
CF = ROOT / "intelligence" / "tests" / "fixtures" / "advisory_contract"
ha_standard = {"friendly_name", "unit_of_measurement", "device_class", "options"}
for name, cname in (("stale", "stale"), ("paused", "paused"), ("self-test-failed", "self_test_failed")):
    doc = json.loads((CF / f"{cname}.json").read_bytes())
    same = True
    detail = ""
    for eid, e in doc["entities"].items():
        got = {k: v for k, v in fx[name][eid]["attributes"].items() if k not in ha_standard}
        want = {**e["recorded"], **e["unrecorded"]}
        if got != want:
            same, detail = False, eid
        want_state = {None: "unknown", True: "on", False: "off"}.get(e["state"] if e["state"] in (None, True, False) else "x", str(e["state"]))
        if fx[name][eid]["state"] != want_state:
            same, detail = False, f"{eid} state"
    check(f"{name}: all 11 integration entities carry exactly the contract fixture {cname}.json's payload (plus Home Assistant's standard attributes)", same and len(doc["entities"]) == 11, detail)
env = c.healthy()
payload = ac.to_entity_payloads(env)
check("healthy: every integration entity's attributes are exactly the real builder's payload (plus the standard attributes)",
      all({k: v for k, v in fx["healthy"][eid]["attributes"].items() if k not in ha_standard} == {**rec, **unrec} for eid, (_s, rec, unrec) in payload.items()))
check("healthy: the states are the builder's states as Home Assistant writes them (a missing figure is 'unknown', a flag is on/off)",
      all(fx["healthy"][eid]["state"] == F.Contract._ha_state(c, st) for eid, (st, _r, _u) in payload.items()))
check("healthy is a real envelope: SHADOW, applies nothing, contract version, status OK",
      fx["healthy"]["sensor.ecco_intel_status"]["state"] == "OK" and fx["healthy"]["sensor.ecco_intel_status"]["attributes"]["mode"] == "SHADOW"
      and fx["healthy"]["sensor.ecco_intel_status"]["attributes"]["applies_nothing"] is True
      and fx["healthy"]["sensor.ecco_intel_status"]["attributes"]["contract_version"] == ac.CONTRACT_VERSION)
uni = G.build_universe()
check("the advice samples carry exactly the keys computed from the advisors' source (the generator also refuses a drift)",
      all(set(F.SAMPLES[k]) == {p.split(".", 1)[1] for p, i in uni.by_ident()[f"intel.{k}"].attrs.items() if p.startswith("advice.") and i["shape"] == "ok"}
          for k in F.SAMPLES) and len(F.SAMPLES) == 7)
check("friendly names come from the integration's NAMES and the packages' names",
      fx["healthy"]["sensor.ecco_intel_status"]["attributes"]["friendly_name"] == "ECCO Intel status"
      and fx["healthy"]["binary_sensor.ecco_intel_watchdog_fresh"]["attributes"]["friendly_name"] == "ECCO Intel Watchdog Fresh"
      and fx["healthy"]["automation.ecco_intel_alert_self_test_failed"]["attributes"]["friendly_name"] == "ECCO Intel - alert: self-test failed")

# ===========================================================================
print("")
print("[4] parity with the live shape, and with the catalogue")
# ===========================================================================
shape = G.load_shape(ROOT / G.SHAPE_REL)
diffs = []
for r in shape["ecco_intel"]:
    live, got = set(r["attributes"]), set(fx["healthy"][r["entity_id"]]["attributes"])
    if live != got:
        diffs.append((r["entity_id"], sorted(live ^ got)))
check("healthy: for each of the 16 live entities the attribute NAMES equal what the running Home Assistant exposes", not diffs and len(shape["ecco_intel"]) == 16, str(diffs[:3]))
live_types = {}
for r in shape["ecco_intel"]:
    for a, info in r["attributes"].items():
        live_types[(r["entity_id"], a)] = info["type"]
tmap = {bool: "bool", str: "str", int: "int", float: "float", type(None): "null", list: "list", dict: "dict"}
mismatch = []
for (eid, a), t in live_types.items():
    v = fx["healthy"][eid]["attributes"][a]
    ft = tmap[type(v)]
    if ft != t.split("[")[0] and not (t == "null" or ft == "null") and not {t, ft} <= {"int", "float"}:
        mismatch.append((eid, a, t, ft))
check("healthy: where the live attribute has a value the types agree (a null live may be a value here, and the reverse)", not mismatch, str(mismatch[:4]))
for name, states in fx.items():
    if name == "extras":
        continue
    undeclared = [(e, a) for e, r in states.items() if e in by_eid for a in r["attributes"] if a not in declared[e]]
    check(f"{name}: no entity carries an attribute that the catalogue does not declare", not undeclared, str(undeclared[:3]))
    check(f"{name}: every one of the 17 catalogued sources is present", set(by_eid) <= set(states) and len(states) == 17, str(sorted(set(by_eid) - set(states))))
ex = fx["extras"]
check("extras: the ONLY undeclared attribute on a catalogued entity is the deliberate status.zz_future_attribute",
      [(e, a) for e, r in ex.items() if e in by_eid for a in r["attributes"] if a not in declared[e]] == [("sensor.ecco_intel_status", "zz_future_attribute")])
all_declared = {(e, p) for e, ns in declared.items() for p in ns}
seen = set()
for states in fx.values():
    for e, r in states.items():
        for a, v in r["attributes"].items():
            seen.add((e, a))
            if isinstance(v, dict):
                seen.update((e, f"{a}.{k}") for k in v)
check("every declared attribute path is exercised by at least one fixture", all_declared <= seen, str(sorted(all_declared - seen)[:5]))
healthy_nested = {(e, f"{a}.{k}") for e, r in fx["healthy"].items() for a, v in r["attributes"].items() if isinstance(v, dict) for k in v}
check("healthy exercises every nested path except the non-OK advice shape and last_good",
      {(e, p) for e, p in all_declared if "." in p} - healthy_nested == {(e, p) for e, p in all_declared if p in ("advice.status", "advice.blocker_codes", "last_good.generated_at", "last_good.values")},
      str(sorted(({(e, p) for e, p in all_declared if "." in p} - healthy_nested))[:5]))

# ===========================================================================
print("")
print("[5] each fixture means what it says")
# ===========================================================================
ITEMS = [ac.ENTITY_IDS[k] for k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS]
S = ac.ENTITY_IDS["status"]


def numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


for name in ("stale", "paused", "self-test-failed"):
    st = fx[name]
    check(f"{name}: the null rule: every item and forecast state is 'unknown' and every one is WITHHELD",
          all(st[e]["state"] == "unknown" and st[e]["attributes"]["status"] == "WITHHELD" for e in ITEMS))
    check(f"{name}: the null rule: no number anywhere in an item's attributes (p10, p90, valid_until, advice, confidence)",
          all(st[e]["attributes"].get("p10") is None and st[e]["attributes"].get("p90") is None and st[e]["attributes"]["valid_until"] is None
              and st[e]["attributes"]["confidence"] is None and not any(numeric(v) for v in st[e]["attributes"]["advice"].values()) for e in ITEMS))
    check(f"{name}: the integration's fresh flag is off", st[ac.ENTITY_IDS["fresh"]]["state"] == "off")
check("stale: the status is STALE, the watchdog is off, last_good carries the earlier figures with their time",
      fx["stale"][S]["state"] == "STALE" and fx["stale"][ac.ENTITY_IDS["watchdog_fresh"]]["state"] == "off"
      and fx["stale"][S]["attributes"]["last_good"]["generated_at"] and fx["stale"][S]["attributes"]["last_good"]["values"])
check("paused: the status is PAUSED, the pause switch is on, the watchdog stays on (PAUSED is fresh while the switch is on)",
      fx["paused"][S]["state"] == "PAUSED" and fx["paused"][ac.ENTITY_IDS["paused"]]["state"] == "on"
      and fx["paused"][ac.ENTITY_IDS["watchdog_fresh"]]["state"] == "on" and fx["paused"][S]["attributes"]["pause_control"] == "ON")
check("self-test-failed: the status is SELF_TEST_FAILED, the failed check is named, the watchdog is off, the alert automation has run",
      fx["self-test-failed"][S]["state"] == "SELF_TEST_FAILED" and any(str(v).startswith("FAIL") for v in fx["self-test-failed"][S]["attributes"]["self_test"].values())
      and fx["self-test-failed"][ac.ENTITY_IDS["watchdog_fresh"]]["state"] == "off"
      and fx["self-test-failed"]["automation.ecco_intel_alert_self_test_failed"]["attributes"]["last_triggered"])
check("healthy: all seven items and forecasts are OK with a figure, the watchdog is on, the pause is off",
      all(fx["healthy"][e]["attributes"]["status"] == "OK" and fx["healthy"][e]["state"] not in ("unknown", "unavailable") for e in ITEMS)
      and fx["healthy"][ac.ENTITY_IDS["watchdog_fresh"]]["state"] == "on" and fx["healthy"][ac.ENTITY_IDS["paused"]]["state"] == "off")
mx = fx["mixed"]
check("mixed: a realistic mix (two items OK, one NO_ADVICE, one INSUFFICIENT_DATA; data quality DEGRADED; tariff UNVERIFIED with no value)",
      [mx[ac.ENTITY_IDS[k]]["attributes"]["status"] for k in ac.ADVICE_ITEMS] == ["OK", "OK", "NO_ADVICE", "INSUFFICIENT_DATA"]
      and mx[ac.ENTITY_IDS["data_quality"]]["state"] == "DEGRADED" and mx[S]["attributes"]["tariff"]["provenance"] == "UNVERIFIED" and mx[S]["attributes"]["value"] is None)
check("healthy: a verified tariff, a value, a plan and an engine comparison, all present",
      fx["healthy"][S]["attributes"]["tariff"]["provenance"] == "VERIFIED" and fx["healthy"][S]["attributes"]["value"]["range_gbp"]
      and fx["healthy"][S]["attributes"]["plan"]["headroom_ceiling_pct"] and fx["healthy"][ac.ENTITY_IDS["charge_target"]]["attributes"]["engine_comparison"]["v1_target_soc_pct"])
un = fx["unavailable"]
check("unavailable: every integration entity is 'unavailable' with nothing but its name; the package entities are still there",
      all(un[e["entity_id"]]["state"] == "unavailable" and set(un[e["entity_id"]]["attributes"]) == {"friendly_name"} for e in cat["sources"] if e["origin"] == "integration")
      and un[ac.ENTITY_IDS["watchdog_fresh"]]["state"] == "off" and un[ac.ENTITY_IDS["paused"]]["state"] == "off")
check("every integration entity of one fixture was published together (one generated_at, one timestamp)",
      all(len({fx[n][e]["last_updated"] for e in by_eid if by_eid[e]["origin"] == "integration"}) == 1 for n in fx if n != "extras"))
for n in ("healthy", "mixed"):
    gen_t = when(fx[n][S]["attributes"]["generated_at"])
    check(f"{n}: the reference clock is 30 s after the publish, inside expected_update_s (60 s) and the validity", (when(meta['fixtures'][n]['reference_now']) - gen_t).total_seconds() == 30
          and when(meta['fixtures'][n]['reference_now']) < when(fx[n][S]["attributes"]["valid_until"]))
ws = fx["watchdog-stale"]
age = (when(meta["fixtures"]["watchdog-stale"]["reference_now"]) - when(ws[S]["last_updated"])).total_seconds()
check("watchdog-stale: at its reference clock every integration entity is older than stale_after_s (1200 s) and past valid_until, so none may be shown as live",
      age > 1200 and when(meta["fixtures"]["watchdog-stale"]["reference_now"]) > when(ws[S]["attributes"]["valid_until"]), str(age))
check("watchdog-stale: the status still says OK (the dead-man watchdog, not the status, tells it is silent), the watchdog is off and its alert has run",
      ws[S]["state"] == "OK" and ws[ac.ENTITY_IDS["watchdog_fresh"]]["state"] == "off"
      and ws["automation.ecco_intel_alert_no_fresh_intelligence_result"]["attributes"]["last_triggered"])
check("the pause helper changed after the others only in the paused fixture", fx["paused"][ac.ENTITY_IDS["paused"]]["last_changed"] != fx["healthy"][ac.ENTITY_IDS["paused"]]["last_changed"])

# ===========================================================================
print("")
print("[6] extras and noise")
# ===========================================================================
prefixes = tuple(cat["discover"]["entity_prefixes"])
must, mustnt = meta["fixtures"]["extras"]["must_discover"], meta["fixtures"]["extras"]["must_not_discover"]
check("extras: four new entities that must be discovered, each starts with a discovery prefix and is not in the catalogue",
      len(must) == 4 and all(e.startswith(prefixes) and e not in by_eid and e in ex for e in must))
check("extras: five lookalikes that must NOT be discovered (the V1 prototype's id family, a prefix inside the name, no underscore, a domain "
      "outside the list, another family), none matches a prefix", len(mustnt) == 5 and all(not e.startswith(prefixes) and e in ex for e in mustnt))
check("extras: one new entity carries a simulated flag (the honesty state SIMULATED can be exercised)", ex["sensor.ecco_intel_future_probe"]["attributes"].get("simulated") is True)
check("extras: everything else is the healthy fixture, unchanged",
      {e: r for e, r in ex.items() if e in fx["healthy"] and e != S} == {e: r for e, r in fx["healthy"].items() if e != S}
      and {k: v for k, v in ex[S]["attributes"].items() if k != "zz_future_attribute"} == fx["healthy"][S]["attributes"])
check("noise: at least 300 entities", len(noise) >= 300, str(len(noise)))
check("noise: none is an ecco_intel_ entity, none matches a discovery prefix, none is a catalogued entity",
      not any(e.startswith(prefixes) or e in by_eid for e in noise))
check("noise: the lookalike of the V1 prototype's family is there (outside the prefix)", "sensor.ecco_intelligence_decoy" in noise)
DECOYS = {
    "sensor.synthetic_decoy_token": "access_token", "sensor.synthetic_decoy_credentials": "password", "sensor.synthetic_decoy_jwt": None,
    "sensor.synthetic_decoy_webhook": "webhook_url", "sensor.synthetic_decoy_network": "ip_address", "device_tracker.synthetic_decoy_phone": "latitude",
    "sensor.synthetic_decoy_connection": "connection", "sensor.synthetic_decoy_url_token": None, "sensor.synthetic_decoy_blobs": "digest",
    "sensor.synthetic_decoy_nested": "config", "sensor.synthetic_decoy_keynames": None}
check("noise: every kind of decoy is present (token, password and key, a JWT-shaped state, a webhook, an address, a location, connection strings, "
      "a token in a URL, long blobs, nested secrets, key names that look secret)", all(e in noise and (k is None or k in noise[e]["attributes"]) for e, k in DECOYS.items()))
check("noise: the JWT-shaped state has the shape of three dot-separated segments starting eyJ",
      re.fullmatch(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", noise["sensor.synthetic_decoy_jwt"]["state"]) is not None)
check("noise: nested decoys sit below the first level (the redactor must reach into dicts and lists)",
      noise["sensor.synthetic_decoy_nested"]["attributes"]["config"]["nested"]["list"][0]["bearer"].startswith("SYNTHETIC-DECOY"))
check("noise: every decoy is marked synthetic in its name, its friendly name or its value",
      all("synthetic" in e or "SYNTHETIC" in json.dumps(noise[e]) for e in DECOYS))

# ===========================================================================
print("")
print("[7] determinism and scale")
# ===========================================================================
a, b = F.noise_states(), F.noise_states()
check("the noise generator is deterministic", a == b and json.dumps(a, sort_keys=True) == json.dumps(noise, sort_keys=True))
check("the intelligence fixtures are deterministic", F.intelligence_fixtures(c)[0] == F.intelligence_fixtures(c)[0])
check("the whole fixture folder is small enough to commit (under 400 KB)", sum(p.stat().st_size for p in raw_files) < 400_000, str(sum(p.stat().st_size for p in raw_files)))

finish()
