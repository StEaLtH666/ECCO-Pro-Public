#!/usr/bin/env python3
"""The contract mapping: the integration's entities publish EXACTLY advisory_contract.to_entity_payloads (goldens: the
foundation's fixtures in intelligence/tests/fixtures/advisory_contract/, rebuilt from their literal constructors).

  * every fixture envelope -> the eleven entities' HA state and attributes equal the fixture's state and
    {recorded, unrecorded} payload (no transformation, nothing added by the runtime but HA's own friendly_name, unit,
    device_class and ENUM options);
  * entity ids are set explicitly from ENTITY_IDS, unique_id = the object id, one device; status and data quality are ENUM
    sensors whose options are the contract's; units are ITEM_UNITS; no state class;
  * _unrecorded_attributes equals the contract's UNRECORDED_ATTRIBUTES plus the runtime's timestamp-only attributes
    (const.TIMESTAMP_ONLY_ATTRIBUTES, A17) on every entity and the recorder view never holds one of them; no RestoreEntity
    anywhere;
  * the null rule holds on the published states (STARTING / PAUSED / STALE / SELF_TEST_FAILED: every item state unknown);
  * the runtime never passes the acceptance keyword or a provenance constant (AST, all integration sources).
Runs the SOURCE tree under the stand-in Home Assistant (_fake_ha). Plain script; exits 1 on any failure.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(TESTS))
sys.path.insert(2, str(REPO / "intelligence" / "tests"))

import _fake_ha  # noqa: E402
import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


_fake_ha.install()
import _gen_contract_fixtures as G  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402

sensor = importlib.import_module("custom_components.ecco_intelligence.sensor")
binary_sensor = importlib.import_module("custom_components.ecco_intelligence.binary_sensor")
entity_base = importlib.import_module("custom_components.ecco_intelligence.entity_base")
FIXTURES = REPO / "intelligence" / "tests" / "fixtures" / "advisory_contract"
HA_OWN = {"friendly_name", "unit_of_measurement", "device_class", "options"}


class FakeCoordinator:
    def __init__(self) -> None:
        self.payloads: dict = {}
        self.listeners: list = []
        self.added: dict = {}

    def payload(self, entity_id):
        return self.payloads.get(entity_id)

    def async_add_listener(self, cb, key=None):
        self.listeners.append(cb)
        return lambda: self.listeners.remove(cb) if cb in self.listeners else None

    def entity_added(self, key, entity_id):
        self.added[key] = entity_id

    def publish(self, env, now=None):
        self.payloads = ac.to_entity_payloads(env, now)
        for cb in list(self.listeners):
            cb()


class Entry:
    def __init__(self, coordinator) -> None:
        self.runtime_data = coordinator
        self.entry_id = "mapping"
        self.domain = "ecco_intelligence"


loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
hass = _fake_ha.HomeAssistant(loop, str(TESTS))
coord = FakeCoordinator()
entry = Entry(coord)
plats = {}


async def add_all() -> None:
    for name, mod in (("sensor", sensor), ("binary_sensor", binary_sensor)):
        plat = _fake_ha.EntityPlatform(hass, entry, name)
        plats[name] = plat
        await mod.async_setup_entry(hass, entry, plat.add_entities)
        await plat.wait_added()


loop.run_until_complete(add_all())
entities = plats["sensor"].entities + plats["binary_sensor"].entities

print("== the entities")
check("eleven integration entities (ten sensors, one binary sensor)", len(plats["sensor"].entities) == 10
      and len(plats["binary_sensor"].entities) == 1)
by_id = {e.entity_id: e for e in entities}
check("entity ids are exactly the contract's integration ids",
      set(by_id) == {ac.ENTITY_IDS[k] for k in ac.INTEGRATION_ENTITY_KEYS}, str(sorted(by_id)))
check("unique_id = the object id for every entity", all(e.unique_id == ac.UNIQUE_IDS[e._key] for e in entities))
check("each entity reported its id to the coordinator", coord.added == {e._key: e.entity_id for e in entities})
check("one device for all", len({json.dumps(sorted((k, str(v)) for k, v in e.device_info.items())) for e in entities}) == 1)
check("no entity polls", not any(e.should_poll for e in entities))
const_mod = importlib.import_module("custom_components.ecco_intelligence.const")
RUNTIME_UNREC = ac.UNRECORDED_ATTRIBUTES | const_mod.TIMESTAMP_ONLY_ATTRIBUTES
check("_unrecorded_attributes equals the contract's UNRECORDED_ATTRIBUTES plus the timestamp-only attributes generated_at, "
      "valid_until and next_run_at (A17) on every entity; those are recorded contract attributes, so only what the recorder "
      "stores changes, never a payload",
      all(type(e)._unrecorded_attributes == RUNTIME_UNREC and type(e)._combined_unrecorded == RUNTIME_UNREC for e in entities)
      and const_mod.TIMESTAMP_ONLY_ATTRIBUTES == {"generated_at", "valid_until", "next_run_at"}
      and const_mod.TIMESTAMP_ONLY_ATTRIBUTES <= ac.RECORDED_ATTRIBUTES)
check("... and the shared entity mixin states the same set (a class without its own override records no timestamp)",
      importlib.import_module("custom_components.ecco_intelligence.entity_base").EccoIntelEntity._unrecorded_attributes
      == RUNTIME_UNREC)
check("no RestoreEntity / RestoreSensor in any class hierarchy",
      not any("Restore" in c.__name__ for e in entities for c in type(e).__mro__))
st_ent = by_id[ac.ENTITY_IDS["status"]]
dq_ent = by_id[ac.ENTITY_IDS["data_quality"]]
check("status is an ENUM sensor with the contract's statuses as options",
      st_ent.device_class == _fake_ha.SensorDeviceClass.ENUM and st_ent.options == list(ac.SystemStatus.ALL))
check("data_quality is an ENUM sensor with the contract's data-quality values",
      dq_ent.device_class == _fake_ha.SensorDeviceClass.ENUM and dq_ent.options == list(ac.DataQuality.ALL))
check("item units are the contract's ITEM_UNITS", all(by_id[ac.ENTITY_IDS[k]].native_unit_of_measurement == u
                                                       for k, u in ac.ITEM_UNITS.items()))
check("no entity declares a state class (nothing becomes a long-term statistic)",
      not any(hasattr(e, "_attr_state_class") or hasattr(type(e), "state_class") for e in entities))

print("== goldens: every foundation fixture, through the entities")
for name in G.NAMES:
    env = getattr(G, name)()
    doc = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    rendered = json.loads(G.render(name))
    check(f"{name}: the fixture file is what its constructor renders", doc == rendered)
    hass.recorder_rows.clear()
    loop.run_until_complete(asyncio.sleep(0))
    coord.publish(env)
    bad = []
    for eid, want in doc["entities"].items():
        st = hass.states._states.get(eid)
        if st is None:
            bad.append(f"{eid}: no state")
            continue
        exp_state = want["state"]
        if exp_state is None:
            exp_str = "unknown"
        elif isinstance(exp_state, bool):
            exp_str = "on" if exp_state else "off"
        else:
            exp_str = str(exp_state)
        if st.state != exp_str:
            bad.append(f"{eid}: state {st.state!r} != {exp_str!r}")
        attrs = {k: v for k, v in st.attributes.items() if k not in HA_OWN}
        exp_attrs = {**want["recorded"], **want["unrecorded"]}
        if json.loads(json.dumps(attrs)) != exp_attrs:
            bad.append(f"{eid}: attributes differ: {sorted(set(attrs) ^ set(exp_attrs))}")
        if not set(want["unrecorded"]) <= ac.UNRECORDED_ATTRIBUTES:
            bad.append(f"{eid}: fixture unrecorded keys outside the contract set")
    check(f"{name}: states and attributes equal the fixture payloads exactly", not bad, str(bad[:3]))
    leaked = [(eid, k) for eid, _s, rec in hass.recorder_rows for k in rec if k in RUNTIME_UNREC]
    check(f"{name}: the recorder view holds no unrecorded attribute", not leaked, str(leaked[:3]))
    if env.status in ac.SystemStatus.NULL:
        numeric = [k for k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS if H.numeric_state(hass.states._states[ac.ENTITY_IDS[k]])]
        check(f"{name}: null rule - every item state is unknown under {env.status}", not numeric, str(numeric))
check("no violation in the stand-in (thread, JSON, size, ENUM options)", not hass.violations, str(hass.violations[:3]))
check("no write attempt", not hass.write_attempts, str(hass.write_attempts[:3]))

print("== the null rule follows the clock: an OK item past its validity loses its number at once")
env = G.synthetic_ok()
coord.publish(env, env.valid_until + (env.valid_until - env.generated_at))
ct = hass.states._states[ac.ENTITY_IDS["charge_target"]]
check("charge_target past valid_until -> unknown", ct.state == "unknown" and ct.attributes.get("valid_until") is None)
check("fresh past valid_until -> off", hass.states._states[ac.ENTITY_IDS["fresh"]].state == "off")

print("== the manifest, the README and the package files")
PKGDIR = REPO / "custom_components" / "ecco_intelligence"
man = json.loads((PKGDIR / "manifest.json").read_text(encoding="utf-8"))
const = importlib.import_module("custom_components.ecco_intelligence.const")
check("manifest: domain, name, version 0.1.0 (= const), codeowners, documentation", man["domain"] == "ecco_intelligence"
      and man["name"] and man["version"] == "0.1.0" == const.INTEGRATION_VERSION and man["codeowners"]
      and man["documentation"].startswith("https://"))
check("manifest: iot_class calculated, integration_type service, requirements [], dependencies [recorder]",
      man["iot_class"] == "calculated" and man["integration_type"] == "service" and man["requirements"] == []
      and man["dependencies"] == ["recorder"])
check("manifest: single_config_entry and config_flow true; no other key", man["single_config_entry"] is True
      and man["config_flow"] is True and set(man) == {"domain", "name", "codeowners", "config_flow", "dependencies",
                                                       "documentation", "integration_type", "iot_class", "requirements",
                                                       "single_config_entry", "version"})
check("no hacs.json anywhere under custom_components/", not list((REPO / "custom_components").rglob("hacs.json")))
check("README.md states 'source only; install only from the built kit'",
      "source only; install only from the built kit" in (PKGDIR / "README.md").read_text(encoding="utf-8").lower())
check("strings.json and translations/en.json are identical JSON with one confirm step and no fields",
      json.loads((PKGDIR / "strings.json").read_text(encoding="utf-8")) == json.loads(
          (PKGDIR / "translations" / "en.json").read_text(encoding="utf-8"))
      and "data" not in json.loads((PKGDIR / "strings.json").read_text(encoding="utf-8"))["config"]["step"]["user"])
check("the constant mode is SHADOW and the platforms are exactly sensor / binary_sensor",
      const.MODE == "SHADOW" and const.PLATFORMS == ("sensor", "binary_sensor"))
check("no binary or image file in the package (interpreter caches aside)", not [
    p for p in PKGDIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    and p.suffix.lower() in (".png", ".jpg", ".ico", ".svg", ".pyc", ".so", ".pyd")])

print("== the runtime never widens the acceptance (AST over every integration source)")
src = sorted(p for p in (REPO / "custom_components" / "ecco_intelligence").rglob("*.py") if "tests" not in p.relative_to(
    REPO / "custom_components" / "ecco_intelligence").parts)
hits = []
for p in src:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.keyword) and n.arg == "accept_provenance":
            hits.append(f"{p.name}: keyword")
        if isinstance(n, (ast.Name, ast.Attribute)) and getattr(n, "id", getattr(n, "attr", "")) in (
                "accept_provenance", "OWNER_RECORD", "SYNTHETIC_TEST", "ALL_PROVENANCE", "Provenance"):
            hits.append(f"{p.name}: name")
        if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) == "from_mapping":
            kw = {k.arg: k.value for k in n.keywords}
            if not (isinstance(kw.get("source"), ast.Constant) and kw["source"].value == "site_local"):
                hits.append(f"{p.name}: from_mapping without source='site_local'")
check(f"no acceptance keyword, provenance name or non-site-local load in {len(src)} files", not hits and len(src) >= 12, str(hits))

loop.close()

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime mapping:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime mapping checks passed")
