#!/usr/bin/env python3
"""Geek Mode catalogue suite (ECCO Intelligence tab): the committed catalogue is valid against the agreed schema
`ecco-geek-catalogue/1`, its alerts are derived from the contract and reference only catalogued entities, and the validator
rejects every kind of malformed catalogue (negative controls: a validator that accepts everything proves nothing).

  [1] the committed catalogue validates; it is plain ASCII JSON that Home Assistant's YAML loader reads identically; it is sorted
  [2] negative controls: each malformed catalogue below is refused with the right message
  [3] alerts: derived from the contract's statuses and data-quality states; only catalogued entities; each condition well formed and
      sensible for its entity; every status is alerted or listed as not an alert; plain words, an owner action for each
  [4] sources: stable ids, timing derived from the integration's constants, redaction patterns include the integration's own
  [5] texts: plain words (no placeholders, no markup, no leftover format braces)

Test-only, no network. Reads the committed files; runs nothing live.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geek_scratch import ROOT, check, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import geek_mode_coverage as G  # noqa: E402
import yaml  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402

CAT_PATH = ROOT / G.CATALOGUE_REL
raw = CAT_PATH.read_bytes()
cat = json.loads(raw.decode("utf-8"))

# ===========================================================================
print("[1] the committed catalogue")
# ===========================================================================
errs = G.validate_catalogue(cat)
check("the committed catalogue validates against ecco-geek-catalogue/1 (strict: no unknown key)", errs == [], "; ".join(errs[:5]))
check("the schema id is ecco-geek-catalogue/1 and the view is intelligence", cat["schema"] == "ecco-geek-catalogue/1" and cat["view_id"] == "intelligence")
check("the contract is ecco-intel-entities/1", cat["contract"] == ac.CONTRACT_VERSION)
check("plain ASCII, LF only, one final newline", raw.isascii() and b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n"))
check("Home Assistant's !include (a YAML loader) reads it identically", yaml.safe_load(raw.decode("utf-8")) == cat)
order = {g["id"]: g["order"] for g in cat["groups"]}
check("groups are sorted by order", [g["order"] for g in cat["groups"]] == sorted(g["order"] for g in cat["groups"]))
check("sources are sorted by group order, then id", [(order[s["group"]], s["id"]) for s in cat["sources"]]
      == sorted((order[s["group"]], s["id"]) for s in cat["sources"]))
check("attributes of every source are sorted by name", all([a["name"] for a in s["attributes"]] == sorted(a["name"] for a in s["attributes"])
                                                           for s in cat["sources"]))
rank = {"critical": 0, "warning": 1, "info": 2}
check("alerts are sorted by severity, then id", [(rank[a["severity"]], a["id"]) for a in cat["alerts"]]
      == sorted((rank[a["severity"]], a["id"]) for a in cat["alerts"]))
check("exceptions are sorted by id", [e["id"] for e in cat["exceptions"]] == sorted(e["id"] for e in cat["exceptions"]))
check("the group 'discovered' exists and is where discovery puts new entities", cat["discover"]["group"] == "discovered" and "discovered" in order)
check("every group is used by a source, except 'discovered' (filled at run time)",
      {s["group"] for s in cat["sources"]} == set(order) - {"discovered"})
check("every priority tier is in use (headline, normal and obscure sources)", {s["priority"] for s in cat["sources"]} == set(G.PRIORITIES))
check("every priority tier is in use among attributes", {a["priority"] for s in cat["sources"] for a in s["attributes"]} == set(G.PRIORITIES))
check("headline sources come with headline attributes (high-value signals first)",
      all(any(a["priority"] == "headline" for a in s["attributes"]) for s in cat["sources"] if s["priority"] == "headline" and s["origin"] == "integration"))

# ===========================================================================
print("")
print("[2] negative controls: the validator refuses a malformed catalogue")
# ===========================================================================


def mutated(fn):
    c = copy.deepcopy(cat)
    fn(c)
    return c


def first_source(c):
    return c["sources"][0]


def has(c, text, strict=True):
    return any(text in e for e in G.validate_catalogue(c, strict))


CASES = [
    ("an unknown schema id", lambda c: c.__setitem__("schema", "ecco-geek-catalogue/2"), "catalogue.schema must be"),
    ("a missing top-level key", lambda c: c.pop("alerts"), "missing key alerts"),
    ("an unknown top-level key (strict)", lambda c: c.__setitem__("zz", 1), "unknown key zz"),
    ("sources that is not a list", lambda c: c.__setitem__("sources", {}), "catalogue.sources: must be a list"),
    ("a duplicate source id", lambda c: c["sources"][1].__setitem__("id", c["sources"][0]["id"]), "duplicate"),
    ("a duplicate entity id", lambda c: c["sources"][1].__setitem__("entity_id", c["sources"][0]["entity_id"]), "duplicate"),
    ("a malformed entity id", lambda c: first_source(c).__setitem__("entity_id", "Not An Entity"), "must be a Home Assistant entity id"),
    ("a source in an undeclared group", lambda c: first_source(c).__setitem__("group", "nowhere"), "is not a declared group"),
    ("a bad source priority", lambda c: first_source(c).__setitem__("priority", "urgent"), "priority: must be one of"),
    ("a bad origin", lambda c: first_source(c).__setitem__("origin", "cloud"), "origin: must be one of"),
    ("a negative staleness limit", lambda c: first_source(c).__setitem__("stale_after_s", -1), "must be a positive number or null"),
    ("a staleness limit below the expected update age", lambda c: (first_source(c).__setitem__("expected_update_s", 60), first_source(c).__setitem__("stale_after_s", 30)),
     "must not be below expected_update_s"),
    ("a boolean as a number", lambda c: first_source(c).__setitem__("expected_update_s", True), "must be a positive number or null"),
    ("an empty source description", lambda c: first_source(c).__setitem__("description", "  "), "description: must be a non-empty text"),
    ("a missing source key", lambda c: first_source(c).pop("title"), "missing key title"),
    ("a source attributes value that is not a list", lambda c: first_source(c).__setitem__("attributes", None), "attributes: must be a list"),
    ("a duplicate attribute name", lambda c: first_source(c)["attributes"].append(dict(first_source(c)["attributes"][0])), "duplicate"),
    ("an attribute with a bad priority", lambda c: first_source(c)["attributes"][0].__setitem__("priority", "x"), "priority: must be one of"),
    ("an attribute with an empty description", lambda c: first_source(c)["attributes"][0].__setitem__("description", ""), "description: must be a non-empty text"),
    ("a dotted attribute without its parent", lambda c: first_source(c)["attributes"].append(
        {"name": "ghost.child", "description": "x", "unit": None, "priority": "normal"}), "has no declared parent attribute"),
    ("a path two levels deep", lambda c: first_source(c)["attributes"].append(
        {"name": "a.b.c", "description": "x", "unit": None, "priority": "normal"}), "must be an attribute name"),
    ("a malformed discover prefix", lambda c: c["discover"].__setitem__("entity_prefixes", ["sensor.ecco_intel"]), "entity_prefixes"),
    ("an empty discover prefix list", lambda c: c["discover"].__setitem__("entity_prefixes", []), "entity_prefixes"),
    ("a discover group that does not exist", lambda c: c["discover"].__setitem__("group", "nowhere"), "discover.group"),
    ("an alert with an unknown severity", lambda c: c["alerts"][0].__setitem__("severity", "fatal"), "severity: must be one of"),
    ("an alert on an uncatalogued entity", lambda c: c["alerts"][0].__setitem__("entity_id", "sensor.not_in_the_catalogue"), "is not a catalogued entity"),
    ("an alert with two condition forms", lambda c: c["alerts"][0].__setitem__("when", {"state_in": ["x"], "unavailable": True}), "must be exactly one of"),
    ("an alert with an empty state list", lambda c: c["alerts"][0].__setitem__("when", {"state_in": []}), "non-empty list of texts"),
    ("an alert with unavailable: false", lambda c: c["alerts"][0].__setitem__("when", {"unavailable": False}), "must be true"),
    ("an attribute alert without a list", lambda c: c["alerts"][0].__setitem__("when", {"attribute": "x", "in": "y"}), "when.in"),
    ("an alert without an owner action", lambda c: c["alerts"][0].__setitem__("action", ""), "action: must be a non-empty text"),
    ("a duplicate alert id", lambda c: c["alerts"][1].__setitem__("id", c["alerts"][0]["id"]), "duplicate"),
    ("an exception with an unknown reason", lambda c: c["exceptions"][0].__setitem__("reason", "inconvenient"), "reason: must be one of"),
    ("an unjustified exception (empty note)", lambda c: c["exceptions"][0].__setitem__("note", ""), "every exception is justified"),
    ("a redaction pattern in capitals", lambda c: c["redaction"].__setitem__("extra_key_patterns", ["Token"]), "extra_key_patterns"),
    ("a catalogue that is not an object", lambda c: None, None),
]
for name, fn, expect in CASES[:-1]:
    check(f"refused: {name}", has(mutated(fn), expect), "; ".join(G.validate_catalogue(mutated(fn))[:3]))
check("refused: a catalogue that is not an object", G.validate_catalogue([]) != [] and G.validate_catalogue(None) != [])
check("the card may tolerate unknown keys: only strict mode refuses them (non-strict accepts the extra top-level key)",
      not has(mutated(lambda c: c.__setitem__("zz", 1)), "unknown key", strict=False))
check("a wrong schema is refused even in non-strict mode", has(mutated(lambda c: c.__setitem__("schema", "x")), "catalogue.schema", strict=False))

# ===========================================================================
print("")
print("[3] alerts, derived from the contract")
# ===========================================================================
by_eid = {s["entity_id"]: s for s in cat["sources"]}
check("every alert names a catalogued entity (an alert can never refer to something the shell cannot show)", all(a["entity_id"] in by_eid for a in cat["alerts"]))
check("every alert id is unique", len({a["id"] for a in cat["alerts"]}) == len(cat["alerts"]))
status_alerts = {a["when"]["state_in"][0]: a for a in cat["alerts"] if a["entity_id"] == ac.ENTITY_IDS["status"] and "state_in" in a["when"]
                 and a["when"]["state_in"][0] in ac.SystemStatus.ALL}
no_alert = set(ac.SystemStatus.ALL) - set(status_alerts)
check("every system status is alerted, or is one of the two that are not an alert (OK, NO_ADVICE)", no_alert == {"OK", "NO_ADVICE"}, str(sorted(no_alert)))
check("the self-test failure is critical and the stale result is a warning",
      status_alerts["SELF_TEST_FAILED"]["severity"] == "critical" and status_alerts["STALE"]["severity"] == "warning")
check("paused, starting, blocked and insufficient data are informational (the owner caused or expects them)",
      all(status_alerts[s]["severity"] == "info" for s in ("PAUSED", "STARTING", "BLOCKED", "INSUFFICIENT_DATA")))
dq = {a["when"]["state_in"][0]: a for a in cat["alerts"] if a["entity_id"] == ac.ENTITY_IDS["data_quality"]}
check("data quality BLOCKED and DEGRADED are alerted; OK and UNKNOWN are not", set(dq) == {"BLOCKED", "DEGRADED"} and set(dq) <= set(ac.DataQuality.ALL))
check("the watchdog being off or unavailable is alerted", {a["id"] for a in cat["alerts"]} >= {"watchdog_off", "watchdog_unavailable"})
check("an unavailable or unknown status is alerted (the integration is down or has not published)",
      any(a["entity_id"] == ac.ENTITY_IDS["status"] and a["when"] == {"unavailable": True} for a in cat["alerts"])
      and any(a["entity_id"] == ac.ENTITY_IDS["status"] and a["when"] == {"state_in": ["unknown"]} for a in cat["alerts"]))
check("a missing pause switch is alerted, by the status attribute and by the helper itself",
      any(a["when"] == {"attribute": "pause_control", "in": ["MISSING"]} for a in cat["alerts"])
      and any(a["entity_id"] == ac.ENTITY_IDS["paused"] and a["when"] == {"unavailable": True} for a in cat["alerts"]))
check("applies_nothing false is a critical alert", any(a["severity"] == "critical" and a["when"].get("attribute") == "applies_nothing" for a in cat["alerts"]))
sensible = True
detail = ""
for a in cat["alerts"]:
    s = by_eid[a["entity_id"]]
    declared = {x["name"] for x in s["attributes"]}
    w = a["when"]
    if "attribute" in w and w["attribute"] not in declared:
        sensible, detail = False, f"{a['id']}: attribute {w['attribute']} is not declared"
    for key in ("state_in", "state_not_in"):
        for v in w.get(key, []):
            ok = {"binary_sensor": {"on", "off"}, "input_boolean": {"on", "off"}}.get(a["entity_id"].split(".")[0])
            if a["entity_id"] == ac.ENTITY_IDS["status"]:
                ok = set(ac.SystemStatus.ALL) | {"unknown", "unavailable"}
            if a["entity_id"] == ac.ENTITY_IDS["data_quality"]:
                ok = set(ac.DataQuality.ALL) | {"unknown", "unavailable"}
            if ok is not None and v not in ok:
                sensible, detail = False, f"{a['id']}: state {v!r} is not a state of {a['entity_id']}"
    if w.get("attribute") == "pause_control" and not set(w["in"]) <= set(ac.PAUSE_CONTROL_STATES):
        sensible, detail = False, f"{a['id']}: not a pause_control state"
check("every alert condition names a state or attribute value its entity can really have", sensible, detail)
check("every alert has plain-words text and an owner action of a sentence or two",
      all(20 <= len(a["text"]) <= 220 and 20 <= len(a["action"]) <= 300 and a["text"].endswith(".") and a["action"].endswith(".") for a in cat["alerts"]))
check("alert texts say 'advice only' / 'nothing changed' style safety facts where an action is suggested: none claims it changed anything",
      not any(re.search(r"\b(we|I) (changed|stopped|started)\b", a["text"] + a["action"]) for a in cat["alerts"]))

# ===========================================================================
print("")
print("[4] sources, timing and redaction")
# ===========================================================================
check("source ids follow intel.<contract key>, intel.automation.<id>, intel.pref.<key>",
      all(re.fullmatch(r"intel\.(automation\.|pref\.)?[a-z0-9_]+", s["id"]) for s in cat["sources"]))
for key, eid in ac.ENTITY_IDS.items():
    check(f"the contract entity {key} is source intel.{key}", by_eid.get(eid, {}).get("id") == f"intel.{key}")
integration = [s for s in cat["sources"] if s["origin"] == "integration"]
check("integration sources are time-driven: expected_update_s = the 60 s tick and stale_after_s = the watchdog's 1200 s",
      all(s["expected_update_s"] == 60.0 and s["stale_after_s"] == 1200.0 for s in integration) and len(integration) == 11)
check("package sources are not age-judged (their state changes only when something happens)",
      all(s["expected_update_s"] is None and s["stale_after_s"] is None for s in cat["sources"] if s["origin"] == "package"))
check("units: the advice, forecast and accuracy sources carry their contract unit",
      all(by_eid[ac.ENTITY_IDS[k]]["unit"] == u for k, u in ac.ITEM_UNITS.items()) and by_eid[ac.ENTITY_IDS["accuracy"]]["unit"] == "kWh")
check("the redaction patterns include everything the integration's own diagnostics redact",
      {"config_hash", "git_sha", "latitude", "longitude", "entities"} <= set(cat["redaction"]["extra_key_patterns"]))
prefixes = cat["discover"]["entity_prefixes"]
check("every discovery prefix is <domain>.ecco_intel_ (a prefix of this contract's naming, never the V1 prototype's ecco_intelligence_)",
      all(re.fullmatch(r"[a-z_]+\.ecco_intel_", p) for p in prefixes) and not any("ecco_intelligence" in p for p in prefixes))
check("the discovery prefixes cover the domains of every catalogued ecco_intel_ entity",
      all(any(s["entity_id"].startswith(p) for p in prefixes) for s in cat["sources"] if s["entity_id"].split(".", 1)[1].startswith("ecco_intel_")))
check("discovery excludes nothing by default", cat["discover"]["exclude_entity_ids"] == [])
check("the exceptions cover the diagnostics download, the registries, history, logs and the site file",
      {"diag.cadence", "recorder_history", "logs", "site_file", "device_registry", "entity_registry", "persistent_notifications"} <= {e["id"] for e in cat["exceptions"]})
check("no exception is justified by 'secret': the view holds no secret (the redactor withholds one if it ever appears)",
      not any(e["reason"] == "secret" for e in cat["exceptions"]))

# ===========================================================================
print("")
print("[5] texts: plain words")
# ===========================================================================
texts = [("catalogue.title", cat["title"])]
for g in cat["groups"]:
    texts += [(f"group {g['id']} title", g["title"]), (f"group {g['id']} description", g["description"])]
for s in cat["sources"]:
    texts += [(f"{s['id']} title", s["title"]), (f"{s['id']} description", s["description"])]
    texts += [(f"{s['id']}#{a['name']}", a["description"]) for a in s["attributes"]]
for a in cat["alerts"]:
    texts += [(f"alert {a['id']} text", a["text"]), (f"alert {a['id']} action", a["action"])]
for e in cat["exceptions"]:
    texts += [(f"exception {e['id']} what", e["what"]), (f"exception {e['id']} note", e["note"])]
bad = [n for n, t in texts if not t.isascii() or re.search(r"TODO|FIXME|XXX|lorem|\{[a-z_]*\}|<[a-z/]|&[a-z]+;", t, re.I)]
check("no text holds a placeholder, markup, a leftover format brace or a non-ASCII character", not bad, str(bad[:5]))
long = [n for n, t in texts if len(t) > 420]
check("no text is longer than 420 characters (readable in a row)", not long, str(long[:5]))
unended = [n for n, t in texts if not n.endswith(("title", " what")) and n != "catalogue.title" and not t.rstrip().endswith((".", "?", ")"))]
check("descriptions, alert texts and notes are sentences (end with a full stop)", not unended, str(unended[:5]))
short = [f"{s['id']}#{a['name']}" for s in cat["sources"] for a in s["attributes"] if len(a["description"]) < 20]
check("every attribute description says something (at least 20 characters)", not short, str(short[:5]))
check("the status source describes itself as advice only", "Advice only" in by_eid[ac.ENTITY_IDS["status"]]["description"])

finish()
