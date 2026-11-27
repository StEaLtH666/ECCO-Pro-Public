"""Offline suite for the dongle-lost alert package (home-assistant/packages/ecco_dongle_lost_alert.yaml): READ-ONLY, it only informs.

When a Free Power or Dump to Grid lease was REPORTED ACTIVE and the dongle's telemetry has then stayed offline for 5 minutes, ONE persistent notification (fixed id) says that no
firmware guard may be running and what the owner can do; a second automation dismisses it when the telemetry returns. Every trigger is a change FROM `on`, so a restart, a reload or an
unavailable-to-on transition never creates it. Nothing was installed and nothing was written live. This suite runs the REAL package under the repository's own automation
interpreter on a virtual clock.

  [0] static      two automations and nothing else; the only service calls are persistent_notification create and dismiss, with one fixed id; it reads exactly the lease flags and
                  the telemetry flag (all of them exist in the firmware); no forecast, no Intelligence entity, no write domain, no helper; ASCII, LF, no site value; the header states
                  the 5 minutes with their reasons, the manual fallback and the limits; the site renderer's exact slug rules; the manifest stanza, the README section, the CHANGELOG bullet
  [1] scenarios   a lease lost in every order of the three entities, a telemetry loss with the dongle alive, both leases, the boundary at 5 minutes, a return inside the window, a
                  lease reported over, a flap, a second loss, a notice dismissed by the return, a second trigger that does not restart the count
  [2] never       a restart, a reload, an unavailable-to-on transition, an unknown start, a lease flag that reads off, no lease at all, a countdown killed by an automation reload and a
                  dongle lost while Home Assistant restarts (the stated limit): none creates the notification
  [2b] sweep      every flag from every state it can have to every state it can go to, one at a time
  [3] vocabulary  over a whole session the only service calls are the notification create and dismiss, and no state is written
  [4] mutation    in-memory mutants of the package, each caught

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _dongle_lost_alert_sim as M  # noqa: E402
import ecco_site_render as render  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_dongle_lost_alert.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
PKG_RAW = (ROOT / PKG_REL).read_bytes()
PKGS = ROOT / "home-assistant" / "packages"
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
DONGLE = "ecco_clock_dongle"
FP, DG, TEL, NOTE = M.FP, M.DG, M.TEL, M.NOTE
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _v in node.value]
    dup = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dup:
        raise ValueError(f"duplicate mapping key(s) {dup}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)


class FwLoader(yaml.SafeLoader):
    pass


FwLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


def slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def firmware_ids() -> set:
    d = yaml.load(FW_TEXT, Loader=FwLoader)
    out = set()
    for plat, domain in (("sensor", "sensor"), ("binary_sensor", "binary_sensor"), ("text_sensor", "sensor")):
        for e in d.get(plat) or []:
            if isinstance(e, dict) and e.get("name"):
                out.add(f"{domain}.{DONGLE}_{slug(e['name'])}")
    return out


ID_RE = re.compile(r"(?<![A-Za-z0-9_.])((?:binary_)?sensor|input_[a-z]+|switch|button|number|select|script|automation|climate|light|lock|cover|fan|esphome|modbus|mqtt|rest_command|"
                   r"shell_command|scene|group|timer|counter)\.([a-z0-9_]+)")
FORBIDDEN_DOMAINS = ("number", "select", "switch", "button", "script", "climate", "light", "lock", "cover", "fan", "esphome", "modbus", "mqtt", "rest_command", "shell_command",
                     "scene", "group", "timer", "counter", "input_boolean", "input_number", "input_text", "input_select", "input_datetime", "sensor")
INTEL = "ecco_" "intel"
SOLCAST = "solc" "ast"
HEADER_MUST = ("WHEN IT RUNS", "WHAT IT NEVER DOES BY ITSELF", "THE WORDS TO THE OWNER", "HARD RULES", "LIMITS", "RECORDER FOOTPRINT (ESTIMATE", "INSTALL.", "5 minutes", "Zero Export",
               "15 minutes", "90 s", "about 70 s", "Why 5 minutes", "SOFT", "NOT announced", "FROM A POSITIVE READING")


def code_lines(text: str) -> str:
    return "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))


def collect(node, key: str, acc: list) -> list:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                acc.append(v)
            collect(v, key, acc)
    elif isinstance(node, list):
        for v in node:
            collect(v, key, acc)
    return acc


def privacy_problems(text: str) -> list:
    bad = []
    if re.search(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])", text):
        bad.append("an IPv4 address")
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", text):
        bad.append("an e-mail address")
    if re.search(r"https?://|www\.", text):
        bad.append("a link")
    if re.search(r"api[_ -]?key|password|secret|token", text, re.I):
        bad.append("a key or secret word")
    if re.search(r"[A-Za-z]:\\|/Users/|/home/", text):
        bad.append("a path")
    if any(ord(c) > 126 or (ord(c) < 32 and c != "\n") for c in text):
        bad.append("a non-ASCII or control character")
    if re.search(r"[ \t]+$", text, re.M):
        bad.append("trailing space")
    return bad


def static_problems(text: str) -> list:
    bad = []
    try:
        doc = yaml.load(text, Loader=UniqueKeyLoader) or {}
    except Exception as exc:  # noqa: BLE001
        return [f"YAML does not parse: {str(exc)[:100]}"]
    if set(doc) != {"automation"}:
        return [f"top-level keys are {sorted(doc)}"]
    autos = doc["automation"]
    if [a.get("id") for a in autos] != ["ecco_dongle_lost_alert", "ecco_dongle_lost_alert_clear"] or any(a.get("mode") != "single" for a in autos):
        bad.append("the automations are not exactly ecco_dongle_lost_alert and ecco_dongle_lost_alert_clear, both mode single")
    acts = collect(doc, "action", [])
    if sorted(set(acts)) != ["persistent_notification.create", "persistent_notification.dismiss"]:
        bad.append(f"the service calls are {sorted(set(acts))}")
    ids = collect(doc, "notification_id", [])
    if set(ids) != {NOTE} or len(ids) != 2:
        bad.append(f"the notification ids are {ids}")
    code = code_lines(text)
    found = {f"{m.group(1)}.{m.group(2)}" for m in ID_RE.finditer(code)}
    if found != {FP, DG, TEL}:
        bad.append(f"it mentions {sorted(found)}")
    dom = sorted({i for i in found if i.split(".", 1)[0] in FORBIDDEN_DOMAINS})
    if dom:
        bad.append(f"a write or helper domain appears: {dom}")
    low = code.lower()
    for word in (INTEL, SOLCAST, "forecast", "intelligence"):
        if word in low:
            bad.append(f"it reads or names {word!r}")
    if re.search(r"\bnotify\.|\bhomeassistant\.|\bbutton\.|\.turn_on|\.turn_off|\.set_value|\.press|\.select_", code):
        bad.append("a service other than the notification appears")
    if "NO FIRMWARE GUARD MAY BE RUNNING" not in code or "Zero Export" not in code:
        bad.append("the notification no longer says that no firmware guard may be running and what to do")
    for p in privacy_problems(text):
        bad.append(f"hygiene: {p}")
    if "\r" in text or "\t" in text:
        bad.append("a CR or a tab")
    for phrase in HEADER_MUST:
        if phrase not in text:
            bad.append(f"the header lost {phrase!r}")
    return bad


# ===========================================================================================================================
# scenarios
# ===========================================================================================================================
def notified(aw) -> bool:
    return NOTE in aw.notifications


def sc_orders(text: str) -> list:
    """A lease lost, in every order the three entities may go unavailable: exactly one notification, at 5 minutes and not before."""
    bad = []
    for lease, title in ((FP, "Free Power"), (DG, "Dump to Grid")):
        for order in itertools.permutations(M.ALL):
            aw = M.AlertWorld(text, fp="on" if lease == FP else "off", dg="on" if lease == DG else "off")
            aw.lose(order)
            aw.advance(299)
            if aw.notifications:
                bad.append(f"{lease} lost in order {[e[-12:] for e in order]}: a notification before 5 minutes")
            aw.advance(3)
            msg = aw.notifications.get(NOTE, {})
            if list(aw.notifications) != [NOTE] or aw.creates() != 1 or title not in msg.get("title", "") or ("and" in msg.get("title", "").split("while a")[-1]):
                bad.append(f"{lease} lost in order {[e[-12:] for e in order]}: {list(aw.notifications)} creates {aw.creates()} title {msg.get('title')!r}")
            aw.advance(7200)
            if aw.creates() != 1:
                bad.append(f"{lease}: created again while it stands")
    return bad


def sc_text(text: str) -> list:
    bad = []
    aw = M.AlertWorld(text, fp="on")
    aw.lose()
    aw.advance(301)
    msg = aw.notifications.get(NOTE, {})
    body = msg.get("message", "")
    if "Free Power" not in msg.get("title", "") or "may be running" not in msg.get("title", ""):
        bad.append(f"the title {msg.get('title')!r}")
    aw = M.AlertWorld(text)
    aw.put(TEL, "on")
    aw.put(FP, "on")
    aw.put(DG, "on")
    aw.put(TEL, "off")
    aw.advance(301)
    if "Free Power and Dump to Grid" not in aw.notifications.get(NOTE, {}).get("title", ""):
        bad.append(f"both leases still on: title {aw.notifications.get(NOTE, {}).get('title')!r}")
    aw = M.AlertWorld(text, fp="on")
    aw.put(TEL, "unavailable")
    aw.put(FP, "unavailable")
    aw.put(DG, "unavailable")
    aw.advance(301)
    if "Free Power or Dump to Grid" not in aw.notifications.get(NOTE, {}).get("title", ""):
        bad.append(f"no flag reading on: title {aw.notifications.get(NOTE, {}).get('title')!r}")
    for needle in ("NO FIRMWARE GUARD MAY BE RUNNING", "Zero Export", "time-of-use table", "Stop SOC", "15 minutes", "5 minutes", "informational", "clears itself"):
        if needle not in body:
            bad.append(f"the notification lacks {needle!r}")
    if "\n" in body.strip() and False:
        bad.append("x")
    return bad


def sc_telemetry(text: str) -> list:
    """The dongle is alive but cannot read the inverter, or only its telemetry flag goes unavailable, while a lease flag reads on."""
    bad = []
    for lease, kw in ((FP, dict(fp="on")), (DG, dict(dg="on")), ("both", dict(fp="on", dg="on"))):
        for to in ("off", "unavailable"):
            aw = M.AlertWorld(text, **kw)
            aw.put(TEL, to)
            aw.advance(299)
            early = bool(aw.notifications)
            aw.advance(3)
            if early or list(aw.notifications) != [NOTE]:
                bad.append(f"{lease} with telemetry {to}: early {early}, then {list(aw.notifications)}")
    # the dongle comes back on every path: no notice, or it is dismissed
    aw = M.AlertWorld(text, fp="on")
    aw.put(TEL, "off")
    aw.advance(299)
    aw.put(TEL, "on")
    aw.advance(3600)
    if aw.notifications or aw.creates():
        bad.append("telemetry returned at 299 s and a notice was created")
    aw = M.AlertWorld(text, fp="on")
    aw.put(TEL, "off")
    aw.advance(301)
    aw.put(TEL, "on")
    aw.advance(1)
    if aw.notifications or aw.creates() != 1:
        bad.append("the notice was not dismissed when telemetry returned")
    return bad


def sc_window(text: str) -> list:
    bad = []
    # the dongle returns inside the window with the lease still on: nothing
    for back_at in (1, 100, 299):
        aw = M.AlertWorld(text, fp="on")
        aw.lose()
        aw.advance(back_at)
        aw.back({TEL: "on", FP: "on", DG: "off"})
        aw.advance(3600)
        if aw.creates():
            bad.append(f"the dongle returned after {back_at} s and a notice was created")
    # the dongle returns inside the window and the lease has ended meanwhile
    aw = M.AlertWorld(text, fp="on")
    aw.lose()
    aw.advance(120)
    aw.back({TEL: "on", FP: "off", DG: "off"})
    aw.advance(3600)
    if aw.creates():
        bad.append("a lease that ended while the dongle was away raised a notice")
    # telemetry off (the dongle is alive) and the lease is reported over: nothing
    aw = M.AlertWorld(text, fp="on")
    aw.put(TEL, "off")
    aw.advance(60)
    aw.put(FP, "off")
    aw.advance(3600)
    if aw.creates():
        bad.append("a lease reported over (both flags readable and off) still raised a notice")
    # telemetry off, one lease reported over and the other still on: the lease is not over
    aw = M.AlertWorld(text, fp="on", dg="off")
    aw.put(TEL, "off")
    aw.advance(301)
    if list(aw.notifications) != [NOTE]:
        bad.append("a readable off flag of the OTHER lease ended the wait")
    # a flap: two losses of 200 s apart by a return raise nothing; one of 301 s does
    aw = M.AlertWorld(text, fp="on")
    aw.put(TEL, "off")
    aw.advance(200)
    aw.put(TEL, "on")
    aw.advance(10)
    aw.put(TEL, "off")
    aw.advance(200)
    if aw.creates():
        bad.append("two losses of 200 s raised a notice")
    aw.advance(101)
    if aw.creates() != 1:
        bad.append("a loss of 301 s after a flap raised nothing")
    # a second trigger inside the countdown does not restart it (mode single): the notice comes 5 minutes after the FIRST loss, once
    aw = M.AlertWorld(text, fp="on")
    aw.put(TEL, "off")
    aw.advance(100)
    aw.put(FP, "unavailable")
    aw.advance(202)
    if aw.creates() != 1:
        bad.append(f"a second trigger inside the countdown moved the notice ({aw.creates()} creates at 302 s)")
    aw.advance(1000)
    if aw.creates() != 1:
        bad.append("a second countdown raised a second notice")
    # a second loss after the first was dismissed raises a second notice
    aw = M.AlertWorld(text, fp="on")
    aw.lose()
    aw.advance(301)
    aw.back({TEL: "on", FP: "on", DG: "off"})
    aw.advance(10)
    aw.lose()
    aw.advance(301)
    if aw.creates() != 2 or list(aw.notifications) != [NOTE]:
        bad.append(f"a second loss: {aw.creates()} creates, {list(aw.notifications)}")
    # the boundary: just under 5 minutes nothing, just over a notice
    aw = M.AlertWorld(text, fp="on")
    aw.lose()
    aw.advance(299.9)
    under = aw.creates()
    aw.advance(0.4)
    if under or aw.creates() != 1:
        bad.append(f"the 5 minute boundary: {under} before, {aw.creates()} after")
    return bad


def sc_never(text: str) -> list:
    bad = []
    # no lease at all: nothing, whatever the dongle does
    for kw in (dict(fp="off", dg="off"),):
        aw = M.AlertWorld(text, **kw)
        aw.lose()
        aw.advance(3600)
        aw.back({TEL: "on", FP: "off", DG: "off"})
        aw.put(TEL, "off")
        aw.advance(3600)
        if aw.creates():
            bad.append("a dongle loss with no lease raised a notice")
    # unavailable and unknown at the start, then everything returns on: an unavailable-to-on transition creates nothing
    for first in ("unavailable", "unknown"):
        aw = M.AlertWorld(text, fp=first, dg=first, tel=first)
        aw.put(TEL, "on")
        aw.put(FP, "on")
        aw.put(DG, "on")
        aw.advance(7200)
        if aw.creates():
            bad.append(f"entities that were {first} and returned on raised a notice")
        aw.put(TEL, "off")
        aw.advance(301)
        if aw.creates() != 1:
            bad.append(f"a real loss after a {first} start raised {aw.creates()} notices")
    # the lease flag was unknown, then unavailable: not a change from a reading
    aw = M.AlertWorld(text, fp="unknown", dg="unknown", tel="unknown")
    aw.put(FP, "unavailable")
    aw.put(TEL, "unavailable")
    aw.advance(7200)
    if aw.creates():
        bad.append("unknown to unavailable raised a notice")
    # a lease flag that reads off and then goes unavailable
    aw = M.AlertWorld(text, fp="off", dg="off")
    aw.lose()
    aw.advance(7200)
    if aw.creates():
        bad.append("off to unavailable raised a notice")
    # an entity that did not exist before
    aw = M.AlertWorld(text, present=())
    aw.put(FP, "unavailable")
    aw.put(TEL, "unavailable")
    aw.advance(7200)
    if aw.creates():
        bad.append("an entity that did not exist raised a notice")
    # a telemetry flag that was already off (or unknown) when the countdown could have started: not a change from on, and a violation that stands is not acted on
    for first in ("off", "unknown"):
        aw = M.AlertWorld(text, fp="on", tel=first)
        aw.put(TEL, "unavailable")
        aw.advance(7200)
        if aw.creates():
            bad.append(f"a telemetry flag that was {first} and went unavailable raised a notice")
    # a restart with the dongle healthy, and with a lease on: the entities read unavailable, then return on
    aw = M.AlertWorld(text, fp="on")
    aw.advance(100)
    aw.restart()
    aw.advance(30)
    aw.back({TEL: "on", FP: "on", DG: "off"})
    aw.advance(7200)
    if aw.creates():
        bad.append("a restart with a lease running raised a notice")
    # a countdown in progress dies with a restart and with an automation reload
    for how in ("restart", "reload"):
        aw = M.AlertWorld(text, fp="on")
        aw.lose()
        aw.advance(100)
        getattr(aw, "restart" if how == "restart" else "reload_automations")(*(() if how == "restart" else ()))
        aw.advance(7200)
        if aw.creates():
            bad.append(f"a countdown survived an automation {how}")
    # a dongle lost while Home Assistant restarts is NOT announced (the stated limit)
    aw = M.AlertWorld(text, fp="on")
    aw.restart()
    aw.advance(7200)
    if aw.creates():
        bad.append("a notice appeared with no change from on after a restart")
    return bad


def sc_sweep(text: str) -> list:
    """Every input one at a time: each of the three flags, from every state it can have to every state it can go to (a missing entity, unavailable, unknown, empty, on, off, junk):
    the notification is created exactly for the one transition each trigger is written for and never for another. The first state is the world's own at its start (no trigger fires
    for it), the second is one change."""
    bad = []
    states = [None, "unavailable", "unknown", "", "on", "off", "garbage"]
    # the lease flags: the notification only for on -> unavailable (the telemetry flag standing off, so that the dongle is not back); the other lease flag reads off
    for lease, key, okey in ((FP, "fp", "dg"), (DG, "dg", "fp")):
        for first in states:
            for second in states:
                present = tuple(e for e in M.ALL if e != lease or first is not None)
                aw = M.AlertWorld(text, tel="off", present=present, **{key: first if first is not None else "off", okey: "off"})
                if second is None:
                    aw.w.states.pop(lease, None)
                else:
                    aw.put(lease, second)
                aw.advance(301)
                want = first == "on" and second == "unavailable"
                if bool(aw.creates()) != want:
                    bad.append(f"{lease[-18:]} {first!r} -> {second!r}: {aw.creates()} notices, wanted {int(want)}")
    # the telemetry flag, with a lease standing on: the notification only for on -> off and on -> unavailable
    for first in states:
        for second in states:
            present = tuple(e for e in M.ALL if e != TEL or first is not None)
            aw = M.AlertWorld(text, fp="on", dg="off", tel=first if first is not None else "on", present=present)
            if second is None:
                aw.w.states.pop(TEL, None)
            else:
                aw.put(TEL, second)
            aw.advance(301)
            want = first == "on" and second in ("off", "unavailable")
            if bool(aw.creates()) != want:
                bad.append(f"telemetry {first!r} -> {second!r}: {aw.creates()} notices, wanted {int(want)}")
    # and with the lease flags junk, missing or off while the telemetry goes off: only a lease reading on counts
    for lease_state in (None, "unavailable", "unknown", "", "off", "garbage"):
        aw = M.AlertWorld(text, tel="on", fp=("off" if lease_state is None else lease_state), dg=("off" if lease_state is None else lease_state), present=tuple(e for e in M.ALL if e not in (FP, DG) or lease_state is not None))
        aw.put(TEL, "off")
        aw.advance(301)
        if aw.creates():
            bad.append(f"telemetry off with the lease flags {lease_state!r}: {aw.creates()} notices")
    return bad


def sc_vocabulary(text: str) -> list:
    bad = []
    aw = M.AlertWorld(text, fp="on", dg="on")
    n0, h0 = len(aw.w.service_log), len(aw.w.history)
    aw.lose()
    aw.advance(400)
    aw.back({TEL: "on", FP: "on", DG: "on"})
    aw.advance(10)
    aw.put(TEL, "off")
    aw.advance(400)
    aw.put(TEL, "on")
    aw.advance(10)
    calls = aw.services(n0)
    if {s for s, _e, _d in calls} != {"persistent_notification.create", "persistent_notification.dismiss"} or any(d.get("notification_id") != NOTE for _s, _e, d in calls):
        bad.append(f"services {[(s, d.get('notification_id')) for s, _e, d in calls]}")
    touched = {e for _t, e, _s in aw.w.history[h0:]}
    if touched - set(M.ALL):
        bad.append(f"states written beyond the three flags: {sorted(touched - set(M.ALL))}")
    return bad


BATTERY = [("static", lambda t: static_problems(t)), ("orders", sc_orders), ("text", sc_text), ("telemetry", sc_telemetry), ("window", sc_window), ("never", sc_never),
           ("sweep", sc_sweep), ("vocabulary", sc_vocabulary)]


def battery(text: str, kill: bool = False, prefer: str | None = None, info: dict | None = None) -> list:
    found = []
    for name, fn in sorted(BATTERY, key=lambda b: 0 if b[0] == prefer else 1):
        try:
            probs = fn(text)
        except Exception as exc:  # noqa: BLE001 - a mutant that breaks the model is caught
            probs = [f"{type(exc).__name__}: {str(exc)[:100]}"]
        if probs:
            found += [f"[{name}] {p}" for p in probs]
            if info is not None:
                info["section"] = name
            if kill:
                return found
    return found


# ===========================================================================================================================
print("[0] static: the file, its vocabulary, its reads, its words")
# ===========================================================================================================================
check("the package parses and satisfies every static rule (two automations, the notification vocabulary, the three reads, the words, hygiene, the header)", static_problems(PKG_TEXT) == [],
      str(static_problems(PKG_TEXT)[:3]))
check("the static rules are live: each flags an injected breach",
      all(static_problems(m) for m in (PKG_TEXT + "\n# 203.0.113.5\n", PKG_TEXT.replace("persistent_notification.dismiss", "button.press"), PKG_TEXT + "\t",
                                       PKG_TEXT.replace("binary_sensor.ecco_clock_dongle_telemetry_online\n        to: \"on\"", "sensor.ecco_clock_dongle_ecco_battery_shutdown\n        to: \"on\""),
                                       PKG_TEXT.replace("NO FIRMWARE GUARD MAY BE RUNNING", "a guard may be running"), PKG_TEXT.replace("notification_id: ecco_dongle_lost_in_lease", "notification_id: other", 1))))
FW_IDS = firmware_ids()
check("the three dongle entities it reads exist in the firmware (ids derived from the firmware's own names)", {FP, DG, TEL} <= FW_IDS, str(sorted({FP, DG, TEL} - FW_IDS)))
check("the firmware facts the alert relies on, pinned: the telemetry flag is published false on every failed read and true after a good one, the two lease flags exist, and a restore at boot ends an open lease",
      'name: "Telemetry Online"' in FW_TEXT and FW_TEXT.count("id(telemetry_online).publish_state(false);") >= 5 and "id(telemetry_online).publish_state(true);" in FW_TEXT
      and 'name: "Free Power Active"' in FW_TEXT and 'name: "Dump to Grid Active"' in FW_TEXT)
class _TagTolerantLoader(UniqueKeyLoader):
    pass


_TagTolerantLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)   # !secret and the like


def defined_ids(path_or_text) -> tuple:
    """(entity ids, unique_ids, automation ids) a package defines."""
    text = path_or_text.read_text(encoding="utf-8") if isinstance(path_or_text, Path) else path_or_text
    d = yaml.load(text, Loader=_TagTolerantLoader) or {}
    ents, uids = set(), set()
    for dom in ("input_boolean", "input_datetime", "input_number", "input_text", "input_select", "script", "counter", "timer"):
        for k in d.get(dom) or {}:
            ents.add(f"{dom}.{k}")
    for blk in d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in blk.get(kind) or []:
                if isinstance(it, dict) and it.get("name"):
                    ents.add(f"{kind}.{slug(it['name'])}")
                    if it.get("unique_id"):
                        uids.add(it["unique_id"])
    autos = {a["id"] for a in d.get("automation") or [] if isinstance(a, dict) and a.get("id")}
    return ents, uids, autos


_mine = defined_ids(PKG_TEXT)
_clash = []
for _p in sorted(PKGS.glob("*.yaml")):
    if _p.name == Path(PKG_REL).name:
        continue
    try:
        _theirs = defined_ids(_p)
    except Exception as exc:  # noqa: BLE001
        _clash.append(f"{_p.name}: {exc}")
        continue
    for _a, _b, _what in zip(_mine, _theirs, ("entity", "unique_id", "automation id")):
        if _a & _b:
            _clash.append(f"{_p.name}: {_what} {sorted(_a & _b)[:2]}")
check(f"every id the package defines ({sum(len(x) for x in _mine)}: entities, unique_ids, automation ids) is defined in no other package of the repository ({len(list(PKGS.glob('*.yaml'))) - 1} others)",
      _clash == [] and sum(len(x) for x in _mine) >= 2, str(_clash[:3]))

_stale = re.search(r'ecco_dump_soc_stale_ms: "(\d+)"', FW_TEXT)
_reboot = re.search(r'ecco_failback_shadow_assumed_reboot_timeout_ms: "(\d+)"', FW_TEXT)
check("the 5 minutes sit between the firmware's two bounds, both pinned: a Dump lease ends (fail closed) when its SOC telemetry is older than 90 s, and ESPHome restarts a dongle with no Home Assistant "
      "client after its default 15 minutes (the firmware relies on that default and models it as 900000 ms)",
      _stale is not None and _reboot is not None and int(_stale.group(1)) == 90000 and int(_reboot.group(1)) == 900000
      and int(_stale.group(1)) < 5 * 60 * 1000 < int(_reboot.group(1)) and "relies on ESPHome's default reboot_timeout (15 min with no API client)" in FW_TEXT
      and "(fail closed)" in FW_TEXT and 'timeout: "00:05:00"' in PKG_TEXT)
site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
slug_spots = [m.start() for m in re.finditer(DONGLE, PKG_TEXT)]
try:
    rendered, counts = render.render_text(PKG_REL, PKG_TEXT, site, render.firmware_actions(ROOT))
except render.RenderError as exc:
    rendered, counts = "", {"error": str(exc)[:120]}
check("the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every one of them for another device slug and leaves none behind",
      counts == {"entity": len(slug_spots)} and len(slug_spots) >= 6 and DONGLE not in rendered and "binary_sensor.site_dongle_telemetry_online" in rendered, str(counts))
man = yaml.safe_load(MANIFEST_TEXT)
stanza = [p for p in man["home_assistant_packages"] if p["source"] == PKG_REL]
check("the deployment manifest lists the package exactly once, to /config/packages, by ssh_file_copy, with restart_required false (an automation reload installs it; the pin-chain entry rrb1 pins the stanza)",
      stanza == [{"source": PKG_REL, "destination": "/config/packages/ecco_dongle_lost_alert.yaml", "method": "ssh_file_copy", "restart_required": False}], str(stanza))
README = re.sub(r"\s+", " ", (PKGS / "README.md").read_text(encoding="utf-8"))
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
BULLET = next((ln for ln in CHANGELOG.splitlines() if "ecco_dongle_lost_alert.yaml" in ln), "")
check("the packages README has a Dongle lost during a lease section (the two automations, the fixed id, the 5 minutes with their reasons, the change-from-on rule, the manual fallback, the install reload) and the CHANGELOG has one "
      "bullet that says read-only, offline, nothing installed and that no firmware guard may be running",
      all(s in README for s in ("## Dongle lost during a lease", "ecco_dongle_lost_alert", "ecco_dongle_lost_alert_clear", "ecco_dongle_lost_in_lease", "5 minutes", "no firmware guard may be running", "Zero Export",
                                "15 minutes", "90 second", "a change FROM `on`", "reload the Automations", "persistent_notification.create"))
      and all(s in BULLET for s in ("read-only", "nothing installed", "no firmware guard may be running", "5 minutes", "change from `on`", "Automations")), BULLET[:80])
check("the package, the model and this suite are ASCII with LF line ends", b"\r" not in PKG_RAW and all(ord(c) < 128 for c in PKG_TEXT)
      and b"\r" not in (HERE / "_dongle_lost_alert_sim.py").read_bytes() and b"\r" not in Path(__file__).read_bytes())
aw0 = M.AlertWorld(PKG_TEXT, present=())
aw0.put(FP, "unavailable")
aw0.advance(1)
aw1 = M.AlertWorld(PKG_TEXT, fp="on")
aw1.put(FP, "unavailable")
aw1.advance(1)
check("the model's own control: a state trigger for an entity that did not exist carries from_state none (Home Assistant's) and starts no countdown, a change from on does",
      aw0.ha.automations[0].fired == [] and len(aw1.ha.automations[0].fired) == 1)

# ===========================================================================================================================
print("[1] to [3] scenarios, never, vocabulary")
# ===========================================================================================================================
for name, fn in BATTERY[1:]:
    probs = fn(PKG_TEXT)
    check({"orders": "a Free Power or a Dump lease lost, the three entities going unavailable in each of the six orders: nothing before 5 minutes, exactly one notification after, never a second while it stands",
           "text": "the notification names the leases (both here), says NO FIRMWARE GUARD MAY BE RUNNING, the manual fallback (Zero Export, the time-of-use table), the Stop SOC gap, the 15 minute self-restart, and that it clears itself",
           "telemetry": "a telemetry loss with the dongle alive or only the telemetry flag unavailable, with each lease on: the notice at 5 minutes; a return before it raises nothing and a return after it dismisses it",
           "window": "a return inside the window, a lease that ended meanwhile, a lease reported over, the other lease's off flag, a flap, a second trigger inside the countdown, a second loss after a dismissal, and the 299.9 s to 300.3 s boundary",
           "never": "no lease, an unavailable or unknown start, unknown to unavailable, off to unavailable, an entity that did not exist, a restart, a restart with a lease, a countdown killed by a restart or an automation reload, and a dongle lost "
                    "while Home Assistant restarts (the stated limit): none creates the notification",
           "sweep": "every flag from every state it can have to every state it can go to (a missing entity, unavailable, unknown, empty, on, off, junk): the notification exactly for the one transition each trigger is written for",
           "vocabulary": "over a whole session the only service calls are the notification create and dismiss, with the one fixed id, and only the three dongle flags change state"}[name],
          probs == [], str(probs[:2]))

# ===========================================================================================================================
print("[4] mutation: in-memory mutants of the package, each caught")
# ===========================================================================================================================
MUTANTS = [
    ("timeout: the wait is 5 seconds", "timeout: \"00:05:00\"", "timeout: \"00:00:05\""),
    ("timeout: the wait is 4 minutes 59 seconds", "timeout: \"00:05:00\"", "timeout: \"00:04:59\""),
    ("timeout: the wait is 5 minutes 1 second", "timeout: \"00:05:00\"", "timeout: \"00:05:01\""),
    ("timeout: the wait is 50 minutes", "timeout: \"00:05:00\"", "timeout: \"00:50:00\""),
    ("trigger: the lease flag trigger fires on off", "          - binary_sensor.ecco_clock_dongle_dump_to_grid_active\n        to: \"unavailable\"", "          - binary_sensor.ecco_clock_dongle_dump_to_grid_active\n        to: \"off\""),
    ("trigger: the Dump lease flag is not watched", "          - binary_sensor.ecco_clock_dongle_free_power_active\n          - binary_sensor.ecco_clock_dongle_dump_to_grid_active\n", "          - binary_sensor.ecco_clock_dongle_free_power_active\n"),
    ("trigger: the telemetry-off trigger is gone", "        to: \"off\"\n        id: telemetry_off", "        to: \"on\"\n        id: telemetry_off"),
    ("trigger: the telemetry-unavailable trigger is gone", "        to: \"unavailable\"\n        id: telemetry_gone", "        to: \"unknown\"\n        id: telemetry_gone"),
    ("from: a lease flag that read off counts", "{%- if trigger.id == 'lease_flag_lost' -%}{{ was == 'on' }}", "{%- if trigger.id == 'lease_flag_lost' -%}{{ was in ['on', 'off'] }}"),
    ("from: a lease flag that was unknown counts", "{%- if trigger.id == 'lease_flag_lost' -%}{{ was == 'on' }}", "{%- if trigger.id == 'lease_flag_lost' -%}{{ was != 'unavailable' }}"),
    ("from: a lease flag that did not exist counts", "{%- set was = trigger.from_state.state if trigger.from_state is not none else '' -%}", "{%- set was = trigger.from_state.state if trigger.from_state is not none else 'on' -%}"),
    ("from: the lease trigger is judged as a telemetry loss", "{%- if trigger.id == 'lease_flag_lost' -%}", "{%- if trigger.id == 'telemetry_off' -%}"),
    ("from: a telemetry loss counts without a lease", "{{ was == 'on' and (is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') or is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on')) }}", "{{ was == 'on' }}"),
    ("from: a telemetry loss counts only with a Free Power lease", "{{ was == 'on' and (is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') or is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on')) }}",
     "{{ was == 'on' and (is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')) }}"),
    ("from: a telemetry flag that was off counts", "{{ was == 'on' and (is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') or", "{{ was != 'unavailable' and (is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') or"),
    ("wait: unavailable telemetry ends the wait", "{{ is_state('binary_sensor.ecco_clock_dongle_telemetry_online', 'on')\n             or (is_state", "{{ not is_state('binary_sensor.ecco_clock_dongle_telemetry_online', 'off')\n             or (is_state"),
    ("wait: either lease reported off ends the wait", "(is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'off') and is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'off')) }}\n        timeout", "(is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'off') or is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'off')) }}\n        timeout"),
    ("wait: a return never ends the wait", "{{ is_state('binary_sensor.ecco_clock_dongle_telemetry_online', 'on')\n             or (is_state", "{{ false\n             or (is_state"),
    ("final: a return is not re-checked", "{{ not is_state('binary_sensor.ecco_clock_dongle_telemetry_online', 'on')\n             and not (", "{{ true\n             and not ("),
    ("final: a lease reported over is not re-checked", "             and not (is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'off') and is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'off')) }}\n      - action", "             and true }}\n      - action"),
    ("mode: a new trigger restarts the count", "    mode: single\n    max_exceeded: silent\n    triggers:\n      - trigger: state\n        entity_id:\n          - binary_sensor.ecco_clock_dongle_free_power_active", "    mode: parallel\n    max_exceeded: silent\n    triggers:\n      - trigger: state\n        entity_id:\n          - binary_sensor.ecco_clock_dongle_free_power_active"),
    ("clear: the notice is dismissed when telemetry goes off", "        entity_id: binary_sensor.ecco_clock_dongle_telemetry_online\n        to: \"on\"\n    actions:", "        entity_id: binary_sensor.ecco_clock_dongle_telemetry_online\n        to: \"off\"\n    actions:"),
    ("clear: the dismissal names another id", "      - action: persistent_notification.dismiss\n        data:\n          notification_id: ecco_dongle_lost_in_lease", "      - action: persistent_notification.dismiss\n        data:\n          notification_id: ecco_dongle_lost_x"),
    ("create: the notification has another id", "          notification_id: ecco_dongle_lost_in_lease\n          title", "          notification_id: ecco_dongle_lost_x\n          title"),
    ("which: Free Power is named for a Dump", "trigger.entity_id == 'binary_sensor.ecco_clock_dongle_dump_to_grid_active'", "trigger.entity_id == 'binary_sensor.ecco_clock_dongle_free_power_active'"),
    ("which: both leases are not named", "{{ 'Free Power and Dump to Grid' if (a and b) else ('Free Power' if a else ('Dump to Grid' if b else 'Free Power or Dump to Grid')) }}", "{{ 'Free Power' if a else ('Dump to Grid' if b else 'Free Power or Dump to Grid') }}"),
    ("text: the guard warning is removed", "NO FIRMWARE GUARD MAY BE RUNNING", "a guard may be running"),
    ("text: the manual fallback is removed", "set the export policy back to Zero Export (this stops a forced export) or put", "set the export policy back (this stops a forced export) or put"),
    ("which: no flag reading on is not named", "('Dump to Grid' if b else 'Free Power or Dump to Grid')", "('Dump to Grid' if b else 'Dump to Grid')"),
    ("text: the self-clearing is removed", "it clears itself when the dongle's telemetry returns", "it stays"),
    ("vocabulary: a button is pressed", "      - action: persistent_notification.create\n        data:\n          notification_id: ecco_dongle_lost_in_lease", "      - action: button.press\n        data:\n          notification_id: ecco_dongle_lost_in_lease"),
    ("reads: another dongle entity is read", "{%- set a = (trigger.id == 'lease_flag_lost'", "{%- set zz = states('sensor.ecco_clock_dongle_ecco_battery_shutdown') -%}\n            {%- set a = (trigger.id == 'lease_flag_lost'"),
    ("hygiene: an address appears in a comment", "# NOT INSTALLED, NOT LIVE-PROVEN.", "# 198.51.100.7 NOT INSTALLED, NOT LIVE-PROVEN."),
    ("wording: the header drops the 5 minute reasons", "Why 5 minutes:", "Why:"),
]
total = len(MUTANTS)
killed = 0
survivors: list = []
prefer: dict = {}
for entry in MUTANTS:
    label, old, new = entry[:3]
    if PKG_TEXT.count(old) != 1:
        check(f"mutant anchor is unique: {label}", False, f"{PKG_TEXT.count(old)}x")
        continue
    mutated = PKG_TEXT.replace(old, new, 1)
    family = label.split(":", 1)[0]
    info: dict = {}
    found = battery(mutated, kill=True, prefer=prefer.get(family), info=info)
    if found:
        killed += 1
        prefer[family] = info.get("section")
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        survivors.append(label)
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{total} mutants (the 5 minutes on both sides, every trigger, every from-state rule, the wait and the final re-check, the mode, the dismissal, the ids, the lease names, the words, "
      "the vocabulary and the reads): all caught", killed == total and total >= 25, f"{killed}/{total} {survivors[:3]}")
_harmless = PKG_TEXT.replace("# WHY. A Free Power or Dump to Grid lease is guarded", "# WHY, restated. A Free Power or Dump to Grid lease is guarded")
check("a harmless rewrite (a comment) survives the battery, and a rewrite of a rule does not", _harmless != PKG_TEXT and battery(_harmless, kill=True) == []
      and battery(PKG_TEXT.replace("timeout: \"00:05:00\"", "timeout: \"00:05:30\""), kill=True) != [])

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll dongle-lost alert checks passed.")
print("These prove the package against the repository's own automation interpreter; nothing was installed, nothing was written live, and the package only informs.")
