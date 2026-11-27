"""Offline suite for the time trust package (home-assistant/packages/ecco_time_trust.yaml): THREE CLOCKS, ONE EXPLICIT TIMING-SAFETY INPUT, READ-ONLY.

The inverter's RTC stalls for 60 s about 85 times a day, Home Assistant starts schedules on its own clock and the dongle ends leases on its NTP time.
If trustworthy time cannot be established, anything that depends on it must fail safely. The package turns what the dongle already publishes into
that input (one state per clock, an overall state and three yes/no consumers); it builds the INPUT ONLY, reads nothing it does not need and writes
nothing. This suite proves the package against a model of Home Assistant's template entities (home-assistant/tests/_time_trust_sim.py); nothing was
installed, nothing was written live, and nothing here wires the input into a gate.

The REAL package YAML runs under the model: dependency-tracked rendering, a render at the start of every minute for a template that uses now(), the
availability template as a super template (while it is false nothing else is rendered, and an unchanged result is not delivered again), attributes,
a binary sensor with delay_on (it keeps its state while it counts, a changed result cancels the count, it takes back its last on or off state when it
is created again by a restart or a template reload), strptime and as_timestamp as Home Assistant reads them.

  [0] static      only `template:`; eleven entities; no automation, script, helper, trigger, action or service call; the eight dongle entities it reads
                  exist in the firmware; its own ids are defined nowhere else and only the packages of the READERS allow-list (pinned) may mention it;
                  ASCII, LF, no site value; the default device slug appears only as
                  entity ids (the site renderer's exact rules); a text is parsed only with strptime in the firmware's exact format; the header states the
                  constants with their reasons and the limits; the deployment manifest and the README and the CHANGELOG say the same; the firmware facts
                  the header relies on are pinned
  [1] model       control experiments on the model itself (delay_on, the availability super template, restore on a reload and a restart, re-rendering by
                  time alone, an error, unavailable drops attributes, how dates are read)
  [2] scenarios   the saved data and the agreed list: a normal 10 s with a flickering stall flag for three hours; 70 s and 130 s; NTP unsynced; the NTP
                  text frozen for 4, 5 and 6 minutes; the Home Assistant clock 130 s and 310 s out; the stall flag on for 3:29 and 3:30, for three and
                  four reads, with the OFF just before the delay; a correction stuck for 6 minutes; each input unavailable, unknown or missing, one at a
                  time; all of them at once; failed corrections above 0; maximum clock error above 120 s; the clock-change hour; a time-zone mismatch
  [2b] restarts   a dead read path and a reconnect that re-sends the stale cached values, a restart with a stale text, a stuck correction and a restart, a
                  Home Assistant clock behind by 150 s and 330 s and a reconnect that re-sends a 59 s old NTP text, a healthy blip, a blip in the middle of a
                  count, a template reload (a count in progress, a helper that was on, no state to take back), the value bound and the LIVE condition at
                  the limit, texts in the other spellings Home Assistant's own parser accepts
  [3] boundaries  every limit on both sides (skew +-119 .. 301 and +-86400, difference +-59 .. 121 and +-3600 and +-43200, failed corrections 0 to 50, maximum
                  error up to 3600, text age 299 .. 301, value age 599 .. 601, LIVE 10 s and 11 s, stall 3:29 and 3:30, correction 4:59 and 5:00)
  [4] consumers   the truth tables of the overall state and of the three yes/no consumers over every per-clock state and every unreadable value
  [5] differential every rule against an independent model over one-factor sweeps and a seeded random sample
  [6] totality    a garbage, missing, huge, non-numeric or oddly spelled input never makes a template fail and never reads TRUSTED
  [7] no writes   the model saw no service call, no notification and no write outside the package's own eleven entities
  [8] mutation    in-memory mutants of the package, each caught

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _time_trust_sim as T  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_time_trust.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
PKG_RAW = (ROOT / PKG_REL).read_bytes()
PKGS = ROOT / "home-assistant" / "packages"
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
RTC_H = (ROOT / "firmware" / "include" / "ecco_rtc_policy.h").read_text(encoding="utf-8")
MANIFEST_TEXT = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ---------------------------------------------------------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------------------------------------------------------
DONGLE = "ecco_clock_dongle"
NTP_TEXT = f"sensor.{DONGLE}_ntp_time"
INV_TEXT = f"sensor.{DONGLE}_inverter_time"
DIFF = f"sensor.{DONGLE}_clock_difference"
FAILED = f"sensor.{DONGLE}_failed_corrections_since_boot"
MAXERR = f"sensor.{DONGLE}_maximum_clock_error_since_boot"
SYNCED = f"binary_sensor.{DONGLE}_ntp_synced"
STALL = f"binary_sensor.{DONGLE}_rtc_stall_detected"
CORR = f"binary_sensor.{DONGLE}_rtc_correction_in_progress"
READS = {NTP_TEXT, INV_TEXT, DIFF, FAILED, MAXERR, SYNCED, STALL, CORR}
K = dict(HA="sensor.ecco_time_trust_ha_clock", NTP="sensor.ecco_time_trust_dongle_ntp", INV="sensor.ecco_time_trust_inverter_clock",
         ALL="sensor.ecco_time_trust", LEASES="binary_sensor.ecco_time_trusted_for_leases", SCHED="binary_sensor.ecco_time_trusted_for_ha_schedules",
         SLOT="binary_sensor.ecco_time_trusted_for_slot_edits", STALLS="binary_sensor.ecco_time_trust_rtc_stall_sustained",
         STUCK="binary_sensor.ecco_time_trust_rtc_correction_stuck", RDN="binary_sensor.ecco_time_trust_ntp_text_readable",
         RDI="binary_sensor.ecco_time_trust_inverter_text_readable")
OWN = set(K.values())
OWN_NAMES = {"ECCO Time Trust RTC Stall Sustained", "ECCO Time Trust RTC Correction Stuck", "ECCO Time Trusted For Leases",
             "ECCO Time Trusted For HA Schedules", "ECCO Time Trusted For Slot Edits", "ECCO Time Trust HA Clock", "ECCO Time Trust Dongle NTP",
             "ECCO Time Trust Inverter Clock", "ECCO Time Trust", "ECCO Time Trust NTP Text Readable", "ECCO Time Trust Inverter Text Readable"}
NAMES = ["TRUSTED", "DEGRADED", "UNKNOWN", "UNTRUSTED"]      # ranked: a known-bad reading beats an unreadable one, which beats a merely degraded one
START = "2026-11-25 12:00:00"


# ===========================================================================================================================
# [0] static
# ===========================================================================================================================
class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _v in node.value]
    dup = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dup:
        raise ValueError(f"duplicate mapping key(s) {dup}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)
UniqueKeyLoader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)   # !secret and the like


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


def package_ids(path: Path) -> set:
    d = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader) or {}
    out = set()
    for dom in ("input_boolean", "input_datetime", "input_number", "input_text", "input_select", "script", "counter", "timer"):
        for k in d.get(dom) or {}:
            out.add(f"{dom}.{k}")
    for block in d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in block.get(kind) or []:
                if isinstance(it, dict) and it.get("name"):
                    out.add(f"{kind}.{slug(it['name'])}")
    return out


def walk_keys(node, acc: set) -> set:
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(str(k))
            walk_keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            walk_keys(v, acc)
    return acc


ENTITY_KEYS = {"name", "unique_id", "icon", "state", "attributes", "availability", "delay_on"}
NO_KEYS = {"action", "actions", "service", "trigger", "triggers", "variables", "event", "data", "target", "sequence", "condition", "conditions", "mode",
           "alias", "id", "platform", "continue_on_error", "delay_off", "restore", "default_entity_id", "object_id"}
READ_RE = re.compile(r"(?<![A-Za-z0-9_])(?:states\.)?((?:binary_)?sensor\.[a-z0-9_]+)")
WRITE_DOMAIN_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:input_[a-z]+|switch|button|number|select|script|automation|climate|light|lock|cover|fan|valve|vacuum|notify|"
                             r"persistent_notification|homeassistant|esphome|modbus|mqtt|rest_command|shell_command|scene|group|timer|counter|text|"
                             r"datetime|date|time|event|update|camera|media_player|alarm_control_panel|siren|humidifier|water_heater|person|zone|"
                             r"remote|calendar|todo|tts)\.[a-z_]+")
WRITE_WORD_RE = re.compile(r"\.(?:turn_on|turn_off|toggle|set_value|press|set_datetime|set_options|create|dismiss|reload|call|write|select_option|"
                           r"send_command)\b")
FW_IDS = firmware_ids()
OTHER_PKGS = {p.name: p for p in sorted(PKGS.glob("*.yaml")) if p.name != "ecco_time_trust.yaml"}
REPO_IDS = set(FW_IDS)
for _p in OTHER_PKGS.values():
    REPO_IDS |= package_ids(_p)
OTHER_TEXT = {n: p.read_text(encoding="utf-8") for n, p in OTHER_PKGS.items()}

# THE READERS ALLOW-LIST. The packages that READ the consumers of this package, and for each the consumer ids it may read: the start gate and the Free Power time guard of the next step
# (post-export entry sgt1; neither is installed). Nothing else may mention this package: a package that is not listed and mentions it fails the check below, a listed one may mention only
# the ids it is listed with (never a per-clock sensor, the overall sensor, an internal helper or the slot-edit consumer), and the list itself is pinned by an independent second copy:
# widening it needs two deliberate edits, and a reviewer sees both.
READERS = {
    "ecco_start_gate.yaml": frozenset({K["LEASES"], K["SCHED"]}),
    "ecco_lease_guard_free_power_time.yaml": frozenset({K["LEASES"]}),
}
PINNED_READERS = {
    "ecco_start_gate.yaml": ("binary_sensor.ecco_time_trusted_for_ha_schedules", "binary_sensor.ecco_time_trusted_for_leases"),
    "ecco_lease_guard_free_power_time.yaml": ("binary_sensor.ecco_time_trusted_for_leases",),
}
MENTION_RE = re.compile(r"(?<![A-Za-z0-9_.])((?:binary_)?sensor\.ecco_time_trust[a-z0-9_]*)")


def readers_problems(others: dict, readers: dict) -> list:
    """What is wrong with the packages (name -> text) that mention this package, judged against the allow-list `readers` (name -> the consumer ids it may read)."""
    bad = []
    for name, text in sorted(others.items()):
        if "ecco_time_trust" not in text:
            continue
        if name not in readers:
            bad.append(f"{name} mentions the time trust package and is not in the READERS allow-list")
            continue
        allowed = set(readers[name])
        extra = sorted(set(MENTION_RE.findall(text)) - allowed)
        if extra:
            bad.append(f"{name} reads {extra}, which the READERS allow-list does not give it")
        rest = text.replace("ecco_time_trust.yaml", "")
        for cid in sorted(allowed, key=len, reverse=True):
            rest = rest.replace(cid, "")
        if "ecco_time_trust" in rest:
            bad.append(f"{name} mentions the time trust package in a form the READERS allow-list does not give it")
    return bad


def readers_pin_problems(readers: dict) -> list:
    """The allow-list must be exactly the pinned one (its second, independent copy)."""
    got = {n: tuple(sorted(v)) for n, v in readers.items()}
    return [] if got == PINNED_READERS else [f"the READERS allow-list {sorted(got)} is not the pinned one {sorted(PINNED_READERS)}"]
HEADER_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "(diagnostic and READ-ONLY)", "BUILDS THE INPUT ONLY", "READERS allow-list", "ecco_start_gate.yaml", "ecco_lease_guard_free_power_time.yaml",
               "fails that suite", "eleven template entities",
               "no automation, no script, no helper, no trigger, no action", "no service call", "UNKNOWN never reads better than DEGRADED",
               "TRUSTED < DEGRADED < UNKNOWN < UNTRUSTED", "TIME-ZONE ASSUMPTION", "R9", "carries NO offset", "whole hours and is UNTRUSTED, never TRUSTED",
               "repeated hour of the autumn clock change", "kLargeErrorS", "REQ-D1", "|skew| <= 120 s TRUSTED, <= 300 s DEGRADED", "ARRIVED", "text_age_s",
               "|difference| <= 60 s TRUSTED, <= 120 s DEGRADED", "failed corrections since boot > 0", "maximum clock error since boot > 120 s",
               "3 minutes 30 seconds of CONTINUOUS ON", "delay_on 00:03:30", "FOUR consecutive reads", "5 minutes of CONTINUOUS ON", "delay_on",
               "PROXY for the sync age", "item N1", "FAIL SAFE", "can NEVER produce TRUSTED", "allow-lists", "HOW A CONSUMER MUST READ IT",
               "Never test \"not off\"", "LIMITS, stated plainly", "AGREE, not that either is true", "never clears after the first sync",
               "NOT verified on a real Home Assistant", "INSTALL", "RELOAD the template entities", "no restart", "HARD RULES", "READ-ONLY",
               "Every template is total", "FRESHNESS IS JUDGED BY THE VALUES", "VALUE (the proof)", "LIVE (an extra)", "ARRIVAL (an extra",
               "|now() - text| <= 600 s", "|now() - (inverter text - difference)| <= 600 s", "a stale copy and a Home Assistant clock that is far off cannot be told apart",
               "more than 10 s after", "A TEXT IS A TIME only in the exact form the firmware writes it", "strptime", "creates no trust",
               "super template", "restores its last on or off state", "does NOT restart a count in progress", "3600 s) or half a day (43200 s)")


def header_problems(text: str) -> list[str]:
    head = re.sub(r"\s*\n#\s*", " ", text.split("\ntemplate:")[0])
    return [f"header lacks {s_!r}" for s_ in HEADER_PINS if s_ not in head]


def privacy_problems(text: str) -> list[str]:
    """ASCII, LF, no tab, no trailing space, and no site value anywhere (comments included): no address, e-mail, link, key or secret."""
    bad = []
    if not text.isascii() or "\r" in text or "\t" in text or re.search(r"[ ]+$", text, re.M):
        bad.append("not plain ASCII, LF, tab-free and trailing-space-free")
    m = re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|@|https?://|secret|token|password|api_key", text, re.I)
    if m:
        bad.append(f"a site value or secret-like word: {m.group(0)!r}")
    return bad


def static_problems(text: str) -> list[str]:
    bad: list[str] = []
    try:
        d = yaml.load(text, Loader=UniqueKeyLoader)
    except Exception as exc:  # noqa: BLE001 - a package that does not load (or repeats a key) is a failed proof
        return [f"does not load: {str(exc)[:100]}"]
    if not isinstance(d, dict) or set(d) != {"template"}:
        return [f"top-level keys {sorted(d) if isinstance(d, dict) else repr(d)[:40]}"]
    names, uids = [], []
    for block in d["template"] or []:
        if not isinstance(block, dict) or len(block) != 1 or set(block) - {"sensor", "binary_sensor"}:
            bad.append(f"a template block {sorted(block) if isinstance(block, dict) else block!r}")
            continue
        (kind, items), = block.items()
        for it in items or []:
            if not isinstance(it, dict) or set(it) - ENTITY_KEYS:
                bad.append(f"entity keys {sorted(set(it) - ENTITY_KEYS) if isinstance(it, dict) else it!r}")
                continue
            names.append(f"{kind}.{slug(it.get('name', ''))}")
            uids.append(it.get("unique_id"))
            if "state" not in it or not it.get("name") or not it.get("unique_id"):
                bad.append(f"an entity without name, unique_id or state: {it.get('name')}")
            if ("delay_on" in it) != (kind == "binary_sensor" and it.get("name", "").startswith("ECCO Time Trust RTC")):
                bad.append(f"delay_on on {it.get('name')}")
    if set(names) != OWN or len(names) != len(OWN):
        bad.append(f"entities {sorted(set(names) ^ OWN)}")
    if sorted(u for u in uids if u) != sorted(n.split(".", 1)[1] for n in names):
        bad.append("a unique_id differs from its entity id")
    keys = walk_keys(d, set())
    if keys & NO_KEYS:
        bad.append(f"forbidden key(s) {sorted(keys & NO_KEYS)}")
    nc = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))
    for m in WRITE_DOMAIN_RE.finditer(nc):
        bad.append(f"write-capable domain {m.group(0)}")
    for m in WRITE_WORD_RE.finditer(nc):
        bad.append(f"write word {m.group(0)}")
    for tok in ("esphome", "modbus", "button.press", "persistent_notification", "write_register"):
        if tok in nc:
            bad.append(f"token {tok}")
    mentioned = {m.group(1) for m in READ_RE.finditer(nc)}
    external = mentioned - OWN
    if external != READS:
        bad.append(f"entities read {sorted(external ^ READS)}")
    if not READS <= FW_IDS:
        bad.append(f"not in the firmware: {sorted(READS - FW_IDS)}")
    if not (mentioned & OWN) <= OWN:
        bad.append("own ids")
    # a text is parsed ONLY with strptime in the firmware's exact format; as_timestamp is handed a datetime (now(), a last_changed, the parsed text), never a text, because Home Assistant's own
    # parser also reads a date alone, no seconds, a T, fractions and an offset
    for m in re.finditer(r"as_timestamp\(((?:[^()]|\([^()]*\))*)\)", nc):
        arg = m.group(1).split(",")[0].strip()
        if arg not in ("now()", "o.last_changed", "mk.last_changed", "dt"):
            bad.append(f"as_timestamp of {arg!r}: a text is read with strptime, never handed to as_timestamp")
    for m in re.finditer(r"strptime\(([^()]*)\)", nc):
        if re.sub(r"\s+", "", m.group(1)) != "txt,'%Y-%m-%d%H:%M:%S',none":
            bad.append(f"strptime({m.group(1)[:40]}): not the firmware's exact format with none as the default")
    if "strptime(" not in nc:
        bad.append("no strptime: the texts are not parsed in the firmware's exact format")
    return bad + header_problems(text) + privacy_problems(text)


print("[0] static")
sp = static_problems(PKG_TEXT)
check("the package loads with no repeated key; only `template:`; eleven template entities (seven binary, four sensors) with exactly the allowed keys; no automation, "
      "script, helper, trigger, action, variables or service call; the only entities it reads are the eight the dongle publishes, and each exists in the firmware",
      sp == [], str(sp[:4]))
nc0 = "\n".join(line for line in PKG_TEXT.split("\n") if not line.lstrip().startswith("#"))
check("no write-capable domain and no write verb anywhere outside a comment (the vocabulary scan is live: it flags each injected one)",
      not WRITE_DOMAIN_RE.search(nc0) and not WRITE_WORD_RE.search(nc0) and WRITE_DOMAIN_RE.search("x: switch.foo") and WRITE_DOMAIN_RE.search("input_boolean.x")
      and WRITE_WORD_RE.search("a.turn_on(") and WRITE_WORD_RE.search("persistent_notification.create "))
DOC = yaml.load(PKG_TEXT, Loader=UniqueKeyLoader)
ENT = {f"{k}.{slug(it['name'])}": it for b in DOC["template"] for k, its in b.items() for it in its}
own_ids = set(ENT)
repo_other = set()
for _p in OTHER_PKGS.values():
    repo_other |= package_ids(_p)
check("its eleven entity ids and unique ids are defined nowhere else in the repository's packages (no repeated key inside any package, no unique_id twice)",
      own_ids == OWN and not (own_ids & repo_other))
_rp = readers_problems(OTHER_TEXT, READERS) + readers_pin_problems(READERS)
check("only the packages of the READERS allow-list mention this package (the start gate and the Free Power time guard of sgt1, each only the consumer ids it is listed with: never a per-clock "
      "sensor, the overall sensor, an internal helper or the slot-edit consumer); every other package of the repository fails the check, and the allow-list is the pinned one", _rp == [], str(_rp[:3]))
seen_u: dict = {}
dup: list = []
for _n, _p in sorted({**OTHER_PKGS, "ecco_time_trust.yaml": PKGS / "ecco_time_trust.yaml"}.items()):
    try:
        _d = yaml.load(_p.read_text(encoding="utf-8"), Loader=UniqueKeyLoader) or {}
    except Exception as exc:  # noqa: BLE001
        dup.append(f"{_n}: {exc}")
        continue
    for block in _d.get("template") or []:
        for kind in ("sensor", "binary_sensor"):
            for it in block.get(kind) or []:
                if isinstance(it, dict) and "unique_id" in it:
                    if it["unique_id"] in seen_u:
                        dup.append(f"unique_id {it['unique_id']}: {seen_u[it['unique_id']]} and {_n}")
                    seen_u[it["unique_id"]] = _n
check(f"no template unique_id is defined twice across the {len(OTHER_PKGS) + 1} packages", dup == [], str(dup[:3]))
check("the header states the constants with their reasons, the time-zone assumption, the fail-safe rule, how a consumer must read it, the limits and the install route",
      header_problems(PKG_TEXT) == [], str(header_problems(PKG_TEXT)[:3]))
check("ASCII only, LF line ends (the file's own bytes), no tab, no trailing space, and no site value anywhere, comments included (no address, e-mail, link, key or secret); "
      "the scans are live: each flags an injected value",
      privacy_problems(PKG_TEXT) == [] and b"\r" not in PKG_RAW and privacy_problems(PKG_TEXT + "# 203.0.113.5\n") and privacy_problems(PKG_TEXT + "# a@example.com\n")
      and privacy_problems(PKG_TEXT + "# the api_key\n") and privacy_problems(PKG_TEXT + "\tx\n") and privacy_problems(PKG_TEXT + "x \n")
      and header_problems(PKG_TEXT.replace("TIME-ZONE ASSUMPTION", "NOTE")) != [])
import ecco_site_render as render  # noqa: E402

site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_dongle"})
slug_spots = [m.start() for m in re.finditer(DONGLE, PKG_TEXT)]
try:
    rendered, counts = render.render_text(PKG_REL, PKG_TEXT, site, render.firmware_actions(ROOT))
except render.RenderError as exc:
    rendered, counts = "", {"error": str(exc)[:120]}
check("the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every one of them for another device slug, "
      "touches nothing else and leaves none behind",
      counts == {"entity": len(slug_spots)} and len(slug_spots) >= 8 and DONGLE not in rendered and "sensor.site_dongle_ntp_time" in rendered
      and "binary_sensor.site_dongle_rtc_stall_detected" in rendered and rendered.count("ecco_time_trust") == PKG_TEXT.count("ecco_time_trust"), str(counts))
man = yaml.safe_load(MANIFEST_TEXT)
stanza = [p for p in man["home_assistant_packages"] if p["source"] == PKG_REL]
check("the deployment manifest lists the package exactly once, to /config/packages, by ssh_file_copy, with restart_required false (a template reload installs it; the pin-chain "
      "entry ttr1 pins that stanza)",
      stanza == [{"source": PKG_REL, "destination": "/config/packages/ecco_time_trust.yaml", "method": "ssh_file_copy", "restart_required": False}], str(stanza))
README = (PKGS / "README.md").read_text(encoding="utf-8")
README_FLAT = re.sub(r"\s+", " ", README)
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
BULLET = next((ln for ln in CHANGELOG.splitlines() if "ecco_time_trust.yaml" in ln), "")
REPLAY_RE = re.compile(r"(\d[\d,]*) reads TRUSTED, (\d+) DEGRADED, (\d+) UNKNOWN, (\d+) UNTRUSTED")
_rm, _bm = REPLAY_RE.search(README_FLAT), REPLAY_RE.search(BULLET)
_rc = tuple(int(g.replace(",", "")) for g in _rm.groups()) if _rm else None
_bc = tuple(int(g.replace(",", "")) for g in _bm.groups()) if _bm else None
check("the packages README has a Time trust section that names the eleven entities, every rule and constant, the freshness conditions, the time-zone assumption, the fail-safe rule, the limits, the install route "
      "and the replay counts, and says what the replay infers (three counters and a synthesized inverter time text); the CHANGELOG has one bullet that says it is read-only, offline and installs nothing and "
      "carries the same replay counts, which add up to the 10,140 recorded reads",
      all(s in README_FLAT for s in ("## Time trust", "sensor.ecco_time_trust_ha_clock", "sensor.ecco_time_trust_dongle_ntp", "sensor.ecco_time_trust_inverter_clock",
                                     "binary_sensor.ecco_time_trusted_for_leases", "binary_sensor.ecco_time_trusted_for_ha_schedules",
                                     "binary_sensor.ecco_time_trusted_for_slot_edits", "binary_sensor.ecco_time_trust_ntp_text_readable", "_inverter_text_readable",
                                     "UNKNOWN never reads better than DEGRADED", "reload the template entities", "Eleven template entities in all", "Freshness is judged by the values",
                                     "VALUE (the proof)", "LIVE (an extra)", "ARRIVAL (an extra", "3 minutes 30 seconds of continuous ON", "four consecutive reads", "creates no trust",
                                     "super template", "Replay of the saved 10 days", "Four inputs of this replay are inferred, not recorded", "SYNTHESIZED", "a fourth inferred input",
                                     "not exercised by real data", "time-zone assumption", "NOT ESTABLISHED"))
      and all(s in BULLET for s in ("read-only", "nothing installed", "It writes nothing", "never produce TRUSTED", "restart_required: false", "eleven", "3 minutes 30 seconds", "creates no trust",
                                    "SYNTHESIZED", "fourth inferred input", "not exercised by real data"))
      and _rc is not None and _rc == _bc and sum(_rc) == 10140, f"{_rc} {_bc}")

# the firmware facts the header relies on, pinned to the repository (a changed firmware breaks the claim here, not silently)
fw_flat = re.sub(r"\s+", " ", FW_TEXT)
kLarge = re.search(r"kLargeErrorS\s*=\s*(\d+);", RTC_H)
kTxn = re.search(r"kTxnDeadlineMs\s*=\s*(\d+)u;", RTC_H)
check("the 300 s boundary is the firmware's own large-error boundary and the 90 s correction lock deadline is below the 5 minute stuck limit and the 180 s Home Assistant alert",
      kLarge is not None and int(kLarge.group(1)) == 300 and kTxn is not None and int(kTxn.group(1)) == 90000
      and "static_assert(kTxnDeadlineMs < 180000u" in RTC_H and "< 300000" not in "x" and int(kTxn.group(1)) < 5 * 60 * 1000)
check("the dongle's NTP time text is a local-time string with no offset, published every 60 s, and says 'Waiting for NTP' or 'NTP time invalid' when it has no time",
      'now.strftime("%Y-%m-%d %H:%M:%S")' in FW_TEXT and 'std::string("Waiting for NTP")' in FW_TEXT and 'std::string("NTP time invalid")' in FW_TEXT
      and re.search(r'name: "NTP Time"\s+id: ntp_clock\s+update_interval: 60s', FW_TEXT) is not None)
check("the 'NTP Synced' flag is set once, when the first NTP time arrives, and cleared only at boot: it never clears after the first sync (the reason for the freshness proxy)",
      FW_TEXT.count("id(ntp_synced) = true;") == 1 and FW_TEXT.count("id(ntp_synced) = false") == 0
      and FW_TEXT.count("id(ntp_synced_sensor).publish_state(false);") == 1 and "NTP synchronised - RTC correction system enabled" in FW_TEXT
      and re.search(r"on_boot:\s+priority: -100\s+then:\s+- lambda: \|-\s+id\(ntp_synced_sensor\)\.publish_state\(false\);", FW_TEXT) is not None)
check("the clock difference is published only by a successful read against valid NTP, and an unsynced or invalid NTP time returns before it (so a stale difference is possible: "
      "the reason for the synced flag and the inverter-time freshness rules); the inverter time text is published on every read, before that",
      "id(clock_difference).publish_state(difference);" in FW_TEXT and FW_TEXT.count("id(clock_difference).publish_state(") == 1
      and FW_TEXT.index("id(inverter_clock).publish_state(buffer);") < FW_TEXT.index("Waiting for confirmed NTP") < FW_TEXT.index("id(clock_difference).publish_state(difference);")
      and re.search(r'name: "Clock Difference"\s+id: clock_difference\s+unit_of_measurement: "s"\s+accuracy_decimals: 0\s+update_interval: never', FW_TEXT) is not None)
check("the inverter time text is the firmware's YYYY-MM-DD HH:MM:SS string of the inverter's own year, month, day, hour, minute and second (the same form as the NTP text), and the clock "
      "difference is the inverter's seconds of the day minus NTP's, wrapped to +-12 h: so the inverter text minus the difference is the NTP time of that read, on the right date, which is what "
      "the VALUE rule measures",
      'snprintf( buffer, sizeof(buffer), "%04d-%02d-%02d %02d:%02d:%02d", year, month, day, hour, minute, second ); id(inverter_clock).publish_state(buffer);' in fw_flat
      and "int difference = inverter_seconds - ntp_seconds;" in fw_flat and "if (difference > 43200) difference -= 86400;" in fw_flat
      and "if (difference < -43200) difference += 86400;" in fw_flat and "year < 2020 || year > 2099" in fw_flat)
check("the regular clock read is a 60 s interval skipped only while a correction or a manual write runs",
      re.search(r"- interval: 60s\s+startup_delay: 30s\s+then:\s+- if:\s+condition:\s+lambda: \|-\s+return !id\(correction_in_progress\) && !id\(manual_write_in_progress\);\s+then:\s+"
                r"- button\.press:\s+id: read_inverter_clock", FW_TEXT) is not None)
check("the stall flag's rule is the firmware's: stalled when the inverter advanced more than 15 s less than NTP over 45 to 90 s; the counters the package reads are 60 s template sensors "
      "of the failed corrections and the maximum clock error since boot",
      "bool stalled = inverter_elapsed < (ntp_elapsed - 15);" in FW_TEXT and "if (ntp_elapsed >= 45 && ntp_elapsed <= 90) {" in FW_TEXT
      and re.search(r'name: "Failed Corrections Since Boot"\s+id: failed_corrections_sensor\s+accuracy_decimals: 0\s+update_interval: 60s', FW_TEXT) is not None
      and re.search(r'name: "Maximum Clock Error Since Boot"\s+id: maximum_clock_error_sensor\s+unit_of_measurement: "s"\s+accuracy_decimals: 0\s+update_interval: 60s', FW_TEXT) is not None
      and "if (abs_difference > id(max_clock_error)) {" in FW_TEXT)
check("the package's R9 precedent is real: both schedule packages compare Home Assistant's now() with the dongle's NTP text as_timestamp, allowing 120 s",
      all(re.search(r"as_timestamp\(now\(\)\) - as_timestamp\(n, 0\)\) \| abs <= 120", re.sub(r"\s+", " ", (PKGS / f).read_text(encoding="utf-8"))) is not None
          for f in ("ecco_free_power_schedule.yaml", "ecco_dump_to_grid_schedule.yaml")))


# ===========================================================================================================================
# the oracle (independent of the templates) and the world builders
# ===========================================================================================================================
def readable(raw, nonneg=False):
    """How the rules read a numeric state: a finite number (below 1e9), non-negative where a counter; else None (unreadable)."""
    if raw is None:
        return None
    try:
        v = float(str(raw).strip())
    except ValueError:
        return None
    if v != v or abs(v) >= 1e9 or (nonneg and v < 0):
        return None
    return v


def o_ha(text_kind, skew, age, live=True):
    """text_kind 'time' | 'not_time' | 'unreadable' | 'missing'; skew whole seconds; age whole seconds (None = unreadable); live: the text changed since it became readable."""
    if text_kind != "time" or age is None or age > 300 or not live:
        return "UNKNOWN"
    a = abs(skew)
    return "TRUSTED" if a <= 120 else ("DEGRADED" if a <= 300 else "UNTRUSTED")


def o_ntp(synced, text_kind, age, vage=0, live=True):
    """vage: Home Assistant's clock minus the time the text carries (whole seconds)."""
    r1 = 0 if synced == "on" else (3 if synced == "off" else 2)
    r2 = {"time": 0, "not_time": 3}.get(text_kind, 2)
    r3 = 0 if r2 > 0 else (2 if age is None else (3 if age > 300 else 0))
    r4 = 0 if (r2 > 0 or r3 > 0) else (2 if abs(vage) > 600 else 0)
    r5 = 0 if (r2 > 0 or r3 > 0) else (0 if live else 2)
    return NAMES[max(r1, r2, r3, r4, r5)]


def o_inv(diff, failed, maxerr, stall, stuck, synced, text_kind, text_age, rage=0, live=True):
    """text_kind 'time' | 'not_time' | 'unreadable' | 'missing'; rage: Home Assistant's clock minus (the inverter text minus the difference), whole seconds."""
    d, f, m = readable(diff), readable(failed, True), readable(maxerr, True)
    unread = text_kind in ("unreadable", "missing") or text_age is None or text_age > 300
    ranks = [2 if d is None else (3 if abs(d) > 120 else (1 if abs(d) > 60 else 0)),
             2 if f is None else (1 if f > 0 else 0),
             2 if m is None else (1 if m > 120 else 0),
             {"off": 0, "on": 1}.get(stall, 2),
             {"off": 0, "on": 3}.get(stuck, 2),
             0 if synced == "on" else 2,
             2 if unread else 0,
             0 if (unread or d is None) else (2 if (text_kind != "time" or abs(rage) > 600) else 0),
             0 if unread else (0 if live else 2)]
    return NAMES[max(ranks)]


def o_all(*clocks):
    return NAMES[max(NAMES.index(c) if c in NAMES else 2 for c in clocks)]


def o_leases(ntp, ha):
    return "on" if ntp == "TRUSTED" and ha in ("TRUSTED", "DEGRADED") else "off"


def o_slot(inv):
    return "on" if inv == "TRUSTED" else "off"


class Killed(Exception):
    pass


def world(text, *, diff="10", failed="0", maxerr="77", synced="on", stall="off", corr="off", ha_offset=0, ntp="live", inv="live", warm=120,
          start=START, ha_zone="Europe/London", dongle_zone=None, restore=None, readable_age=86400.0):
    """A healthy dongle (published every 60 s, on the minute) and Home Assistant, run for `warm` seconds. A value of None leaves the entity absent; `ntp` and `inv` are
    'live' (a text every 60 s), None (never published) or a constant text. `readable_age`: how long the two texts have been readable (a day by default: the LIVE
    condition is long satisfied); None leaves the helpers as the world made them. `restore`: the state a delayed helper takes back when it is created ('on', 'off' or None)."""
    tw = T.TrustWorld(text, start=start, zone=ha_zone, restore=restore)
    tw.w.clock_offset = ha_offset
    for eid, v in ((DIFF, diff), (FAILED, failed), (MAXERR, maxerr), (SYNCED, synced), (STALL, stall), (CORR, corr)):
        if v is not None:
            tw.put(eid, v)
    tw.h_ntp = tw.feed(NTP_TEXT, zone=dongle_zone) if ntp == "live" else None
    if ntp not in ("live", None):
        tw.put(NTP_TEXT, ntp)
    tw.h_inv = tw.feed(INV_TEXT, offset_s=7, zone=dongle_zone) if inv == "live" else None
    if inv not in ("live", None):
        tw.put(INV_TEXT, inv)
    tw.advance(warm)
    if readable_age is not None:
        tw.age(K["RDN"], readable_age)
        tw.age(K["RDI"], readable_age)
    return tw


def inv_text(tw, read_age, difference=10.0):
    """An inverter time text recording a read that is `read_age` seconds old by Home Assistant's own clock (the text minus the difference is the NTP time of the read)."""
    return tw.local_text(tw.w.t + tw.w.clock_offset - read_age + difference)


def _raw(tw, eid):
    st = tw.w.states.get(eid)
    return None if st is None else st[0]


def _text_view(tw, eid, helper, now):
    """What a dongle text is, read from the world's raw states and timestamps alone (no template): (text, unreadable, time as local epoch or None, arrival age, value age, live)."""
    s = _raw(tw, eid)
    txt = "unknown" if s is None else s
    unreadable = txt in ("unknown", "unavailable", "")
    ts = None
    if not unreadable:
        try:
            ts = T.datetime.strptime(txt, T.FMT).replace(tzinfo=tw.zone).timestamp()
        except ValueError:
            ts = None
    lc = tw.w.changed_at.get(eid) if s is not None else None
    age = None if lc is None else round(now - lc)
    vage = None if ts is None else round(now - ts)
    hlc = tw.w.changed_at.get(K[helper])
    live = lc is not None and hlc is not None and _raw(tw, K[helper]) == "on" and (lc - hlc) > 10
    return txt, unreadable, ts, age, vage, live


def expected_reasons(tw, key) -> list[str]:
    """The fragments, in order, that the `reasons` of a per-clock sensor must show, from the world's raw states alone (independent of the templates)."""
    now = tw.rendered_at[K[key]] + tw.w.clock_offset
    if key == "HA":
        _txt, unreadable, ts, age, _v, live = _text_view(tw, NTP_TEXT, "RDN", now)
        if unreadable:
            return ["NTP time text cannot be read ("]
        if ts is None:
            return ["NTP time text is not a time, so the Home Assistant clock"]
        if age is None:
            return ["age of the dongle NTP time text cannot be read"]
        if age > 300:
            return [("has not changed for", r"changed for (\d+) s", age)]
        if not live:
            return ["since it became readable"]
        lc = tw.w.changed_at.get(NTP_TEXT)
        skew = round(lc - ts)
        return [("Home Assistant clock minus the dongle NTP time text", r"skew ([+-]\d+) s", skew)]
    if key == "NTP":
        _txt, unreadable, ts, age, vage, live = _text_view(tw, NTP_TEXT, "RDN", now)
        sy = _raw(tw, SYNCED)
        out = []
        if sy == "off":
            out.append("reports that NTP is not synced")
        elif sy != "on":
            out.append("NTP synced flag cannot be read")
        if unreadable:
            out.append("NTP time text cannot be read (")
        elif ts is None:
            out.append("NTP time text is not a time")
        elif age is None:
            out.append("age of the dongle NTP time text cannot be read")
        elif age > 300:
            out.append(("has not changed for", r"changed for (\d+) s", age))
        else:
            if abs(vage) > 600:
                out.append(("from the Home Assistant clock (limit 600 s)", r"is (\d+) s from the Home Assistant clock", abs(vage)))
            if not live:
                out.append("since it became readable")
        return out or ["TRUSTED: synced, and the NTP time text is advancing"]
    _txt, unreadable, ts, age, _v, live = _text_view(tw, INV_TEXT, "RDI", now)
    d, f, m = readable(_raw(tw, DIFF)), readable(_raw(tw, FAILED), True), readable(_raw(tw, MAXERR), True)
    out = []
    if d is None:
        out.append("clock difference cannot be read")
    elif abs(d) > 120:
        out.append(("is above 120 s", r"clock difference (-?\d+) s is above", int(round(d))))
    elif abs(d) > 60:
        out.append(("is above 60 s", r"clock difference (-?\d+) s is above", int(round(d))))
    if f is None:
        out.append("failed corrections counter cannot be read")
    elif f > 0:
        out.append(("failed RTC correction(s)", r"DEGRADED: (\d+) failed RTC", int(f)))
    if m is None:
        out.append("maximum clock error since boot cannot be read")
    elif m > 120:
        out.append(("clock error reached", r"reached (\d+) s since", int(m)))
    st, cs, sy = _raw(tw, K["STALLS"]), _raw(tw, K["STUCK"]), _raw(tw, SYNCED)
    if st not in ("on", "off"):
        out.append("stall flag cannot be read")
    elif st == "on":
        out.append("stall flag has been on for 3 minutes 30 seconds")
    if cs not in ("on", "off"):
        out.append("correction flag cannot be read")
    elif cs == "on":
        out.append("correction has been in progress for 5 minutes")
    if sy != "on":
        out.append("NTP is not synced or its flag cannot be read")
    if unreadable or age is None or age > 300:
        out.append("cannot be read or has not changed for more than 300 s")
    else:
        if d is not None and (ts is None or abs(round(now - (ts - d))) > 600):
            out.append(("the read it records", r"is (\d+) s from the Home Assistant clock", None if ts is None else abs(round(now - (ts - d)))))
        if not live:
            out.append("since it became readable")
    return out or ["TRUSTED: every rule is within its limit"]


def reasons_problems(tw) -> list[str]:
    """Each per-clock sensor's `reasons` is a non-empty list whose strongest tag is the state, and which names exactly the causes an independent reading of the raw states finds."""
    bad = []
    for key in ("HA", "NTP", "INV"):
        st, rs = tw.state(K[key]), tw.attr(K[key], "reasons")
        if st not in NAMES:
            bad.append(f"{key} state {st!r}")
        elif not (isinstance(rs, list) and rs and all(isinstance(r, str) and r.split(":", 1)[0] in NAMES for r in rs)):
            bad.append(f"{key} reasons {str(rs)[:60]!r}")
        elif NAMES[max(NAMES.index(r.split(":", 1)[0]) for r in rs)] != st:
            bad.append(f"{key} reasons say {NAMES[max(NAMES.index(r.split(':', 1)[0]) for r in rs)]}, state {st}")
        else:
            want = [w if isinstance(w, tuple) else (w, None, None) for w in expected_reasons(tw, key)]
            if len(want) != len(rs) or not all(w[0] in r for w, r in zip(want, rs)):
                bad.append(f"{key} reasons {[r[:70] for r in rs]} do not name {[w[0] for w in want]}")
            else:
                for (frag, rx, num), r in zip(want, rs):
                    if rx is None or num is None:
                        continue
                    m = re.search(rx, r)
                    if m is None or int(m.group(1)) != num:
                        bad.append(f"{key} reason {r[:90]!r} does not show {num}")
    return bad


def derived_problems(tw) -> list[str]:
    """The overall state and the three consumers are what the per-clock states they read say, whatever those are."""
    ha, ntp, inv = tw.state(K["HA"]), tw.state(K["NTP"]), tw.state(K["INV"])
    bad = []
    for key, want in (("ALL", o_all(ha, ntp, inv)), ("LEASES", o_leases(ntp, ha)), ("SCHED", o_leases(ntp, ha)), ("SLOT", o_slot(inv))):
        if tw.state(K[key]) != want:
            bad.append(f"{key} {tw.state(K[key])!r} != {want!r}")
    for attr, state in (("ha_clock", ha), ("dongle_ntp", ntp), ("inverter_clock", inv)):
        if tw.attr(K["ALL"], attr) != (state if state in NAMES else "UNKNOWN"):
            bad.append(f"overall {attr} {tw.attr(K['ALL'], attr)!r}")
    # the overall reasons: one entry for each clock that is not TRUSTED (naming the clock and carrying that clock's own reasons), or the one TRUSTED line
    rs = tw.attr(K["ALL"], "reasons")
    if not (isinstance(rs, list) and rs and all(isinstance(r, str) for r in rs)):
        bad.append(f"overall reasons {str(rs)[:50]!r}")
    else:
        want_n = 0
        for label, key, state in (("HA clock", "HA", ha), ("dongle NTP", "NTP", ntp), ("inverter clock", "INV", inv)):
            mine = [r for r in rs if r.startswith(label + ": ")]
            if state == "TRUSTED":
                if mine:
                    bad.append(f"overall reasons name the TRUSTED {label}")
                continue
            want_n += 1
            own = tw.attr(K[key], "reasons")
            if len(mine) != 1 or (state in NAMES and not (isinstance(own, list) and mine[0] == f"{label}: " + "; ".join(own))):
                bad.append(f"overall reasons for {label}: {mine[:1]}")
        if want_n == 0 and rs != ["TRUSTED: all three clocks are TRUSTED"]:
            bad.append(f"overall reasons {rs}")
        if want_n and len(rs) != want_n:
            bad.append(f"overall reasons count {len(rs)} != {want_n}")
    return bad


def attr_problems(tw) -> list[str]:
    """The numbers the sensors show are the numbers their verdicts were made from."""
    bad = []
    exists = NTP_TEXT in tw.w.states
    for key in ("HA", "NTP"):                            # what a sensor shows is as of its last render
        true_age = round(tw.rendered_at[K[key]] + tw.w.clock_offset - tw.w.changed_at.get(NTP_TEXT, 0)) if exists else "unknown"
        got = tw.attr(K[key], "text_age_s")
        if got != true_age:
            bad.append(f"{key} text_age_s {got!r} != {true_age!r}")
    st, sk = tw.state(K["HA"]), tw.attr(K["HA"], "skew_s")
    if st == "UNKNOWN":
        if sk != "unknown":
            bad.append(f"HA skew_s {sk!r} while UNKNOWN")
    elif not isinstance(sk, int) or isinstance(sk, bool) or o_ha("time", sk, 0) != st:
        bad.append(f"HA skew_s {sk!r} does not make {st}")
    else:
        rs = tw.attr(K["HA"], "reasons")
        if not (isinstance(rs, list) and rs and f"skew {'+' if sk >= 0 else ''}{sk} s," in rs[0]):
            bad.append(f"HA reasons do not show skew {sk}: {str(rs)[:70]}")
    d = readable(tw.state(DIFF))
    want_d = "unknown" if d is None else int(round(d))
    if tw.attr(K["INV"], "difference_s") != want_d:
        bad.append(f"INV difference_s {tw.attr(K['INV'], 'difference_s')!r} != {want_d!r}")
    return bad


def snapshot_problems(tw) -> list[str]:
    return reasons_problems(tw) + derived_problems(tw) + attr_problems(tw) + [f"template error {e}" for e in tw.errors[:2]]


def make_rec(mode: str, results: list | None = None):
    def rec(name: str, ok: bool, detail: str = ""):
        if mode == "report":
            check(name, ok, detail)
        elif not ok:
            raise Killed(f"{name}{(' - ' + detail) if detail else ''}")
        return ok
    return rec


def verify(rec, name, tw, expect: dict, extra=None):
    bad = [f"{k} {tw.state(K[k])!r} != {v!r}" for k, v in expect.items() if tw.state(K[k]) != v]
    bad += snapshot_problems(tw)
    if extra:
        bad += extra
    rec(name, not bad, "; ".join(bad[:3]))


HEALTHY = dict(HA="TRUSTED", NTP="TRUSTED", INV="TRUSTED", ALL="TRUSTED", LEASES="on", SCHED="on", SLOT="on", STALLS="off", STUCK="off")


def exp(**kw):
    return {**HEALTHY, **kw}


# ===========================================================================================================================
# the battery: every proof that depends on the package text (also run on each mutant)
# ===========================================================================================================================
def battery(text: str, mode: str = "kill", prefer=None, info=None) -> list[str]:
    """mode 'report': every proof is a check() line. mode 'kill': return at the first failing proof (a mutant is caught) with its name, else []. `prefer`: the section to try first
    (the one that caught the last mutant of the same family: the verdict never depends on the order, only the time it takes); `info['section']` names the section that caught it."""
    rec = make_rec(mode)
    try:
        sp = static_problems(text)
        rec("the package is static-clean (template entities only, read-only, the eight dongle entities, the header, no site value)", not sp, str(sp[:3]))
        thorough = mode == "report"
        if thorough:                  # the report reads in the order of the sections above; a mutant meets the cheap, sharp proofs first
            sec_model(rec)
            order = (sec_scenarios, sec_restarts, sec_boundaries, sec_consumers, sec_differential, sec_totality, sec_nowrite)
        else:
            order = [sec_boundaries, sec_consumers, sec_differential, sec_restarts, sec_scenarios, sec_totality, sec_nowrite]
            if prefer in order:
                order.remove(prefer)
                order.insert(0, prefer)
        for sec in order:
            if info is not None:
                info["section"] = sec
            if sec in (sec_differential, sec_totality):
                sec(text, rec, thorough=thorough)
            else:
                sec(text, rec)
    except Killed as k:
        return [str(k)]
    return []


# --- [1] the model itself -------------------------------------------------------------------------
MODEL_PKG = """
template:
  - binary_sensor:
      - name: probe delayed
        delay_on: "00:10:00"
        availability: "{{ states('sensor.in') in ['on', 'off'] }}"
        state: "{{ is_state('sensor.in', 'on') }}"
      - name: probe plain
        state: "{{ is_state('sensor.in', 'on') }}"
  - sensor:
      - name: probe now
        state: "{{ (as_timestamp(now()) / 60) | int }}"
      - name: probe no now
        state: "{{ states('sensor.in') }}"
        attributes:
          a: "{{ ['x', 1] }}"
          n: "{{ 12 }}"
      - name: probe error
        state: "{{ states('sensor.in') | int }}"
      - name: probe other
        state: "{{ states('sensor.other') }}"
      - name: probe super
        availability: "{{ states('sensor.gate') == 'go' }}"
        state: "{{ states('sensor.val') }}"
"""


def sec_model(rec):
    tw = T.TrustWorld(MODEL_PKG)
    tw.put("sensor.in", "off")
    d, p = "binary_sensor.probe_delayed", "binary_sensor.probe_plain"
    tw.put("sensor.in", "on")
    tw.advance(599)
    a = (tw.state(d), tw.state(p))
    tw.advance(1)
    b = tw.state(d)
    tw.put("sensor.in", "off")
    c = (tw.state(d), tw.state(p))
    rec("model: a delayed binary sensor keeps its state for the whole delay (599 s), turns on at 600 s and off at once; a plain one follows at once", a == ("off", "on") and b == "on" and c == ("off", "off"), f"{a} {b} {c}")
    tw.put("sensor.in", "on")
    tw.advance(540)
    tw.put("sensor.in", "off")
    tw.advance(1)
    tw.put("sensor.in", "on")
    tw.advance(599)
    e1 = tw.state(d)
    tw.advance(1)
    e2 = tw.state(d)
    rec("model: a change of the result cancels the count (9 min on, 1 s off, then 599 s on: still off; on only after 600 s of continuous on)", e1 == "off" and e2 == "on", f"{e1} {e2}")
    # the availability template is a super template: a blip of unavailability neither restarts a count nor delivers an unchanged result again
    sw = T.TrustWorld(MODEL_PKG)
    sw.put("sensor.in", "off")
    sw.put("sensor.in", "on")
    sw.advance(300)
    sw.put("sensor.in", "unavailable")
    un = (sw.state(d), sw.state(p))
    sw.advance(5)
    sw.put("sensor.in", "on")
    sw.advance(294)
    f1 = sw.state(d)
    sw.advance(1)
    f2 = sw.state(d)
    rec("model: the availability template is a super template: an unreadable input makes the delayed entity unavailable (a plain one reads off) and does NOT restart the count "
        "(on, unavailable for 5 s at 300 s, on again: still off at 599 s, on at 600 s counted from the first on)", un == ("unavailable", "off") and f1 == "off" and f2 == "on", f"{un} {f1} {f2}")
    sw = T.TrustWorld(MODEL_PKG)
    sw.put("sensor.in", "on")
    sw.advance(100)
    sw.put("sensor.in", "unavailable")
    sw.advance(600)
    during = sw.state(d)
    sw.put("sensor.in", "on")
    after = sw.state(d)
    rec("model: a count that ends while the entity is unavailable (its timer is not cancelled by the gap) leaves it on as soon as the input is readable again", during == "unavailable" and after == "on", f"{during} {after}")
    sw = T.TrustWorld(MODEL_PKG)
    sw.put("sensor.in", "on")
    sw.advance(100)
    sw.put("sensor.in", "unavailable")
    sw.advance(50)
    sw.put("sensor.in", "off")
    sw.advance(2000)
    rec("model: an input that returns with a CHANGED result (off) after the gap cancels the count: the entity never turns on", not any(h[1] == d and h[2] == "on" for h in sw.w.history), "")
    sw = T.TrustWorld(MODEL_PKG)
    sw.put("sensor.gate", "stop")
    sw.put("sensor.val", "1")
    r0 = sw.renders.get("sensor.probe_super", 0)
    sw.put("sensor.val", "2")
    sw.put("sensor.val", "3")
    shut = (sw.state("sensor.probe_super"), sw.renders.get("sensor.probe_super", 0) - r0)
    sw.put("sensor.gate", "go")
    rec("model: while the availability template is false the state template is not rendered (a change of what it reads does not render the entity) and the entity is unavailable; "
        "when it turns true the entity shows the current value", shut == ("unavailable", 0) and sw.state("sensor.probe_super") == "3", f"{shut} {sw.state('sensor.probe_super')}")
    tw.put("sensor.in", "unavailable")
    tw.put("sensor.in", "on")
    tw.advance(300)
    n0 = tw.state("sensor.probe_now")
    r_now, r_plain, r_other = tw.renders.get("sensor.probe_now", 0), tw.renders.get("sensor.probe_no_now", 0), tw.renders.get("sensor.probe_other", 0)
    tw.advance(180)
    rec("model: a template that calls now() is rendered again every minute with no entity changing; one that does not is not (dependency tracking)",
        tw.state("sensor.probe_now") != n0 and tw.renders["sensor.probe_now"] - r_now == 3 and tw.renders.get("sensor.probe_no_now", 0) == r_plain, f"{tw.renders}")
    tw.put("sensor.unrelated", "1")
    tw.put("sensor.other", "z")
    rec("model: an entity is rendered again only when an entity it read changed",
        tw.renders.get("sensor.probe_no_now", 0) == r_plain and tw.renders.get("sensor.probe_other", 0) > r_other)
    tw.put("sensor.in", "abc")
    rec("model: a render error leaves the entity unknown and is recorded", tw.state("sensor.probe_error") == "unknown" and any("probe_error" in e for e in tw.errors), str(tw.errors[:1]))
    tw.put("sensor.in", "7")
    attrs = tw.w.states["sensor.probe_no_now"][1]
    rec("model: attributes are parsed natively (a list, a number)", attrs.get("a") == ["x", 1] and attrs.get("n") == 12, str(attrs))
    # a cold start with the input already on, with and without a restored state
    cold = T.TrustWorld(MODEL_PKG, preload={"sensor.in": "on"})
    restored = T.TrustWorld(MODEL_PKG, restore="off", preload={"sensor.in": "on"})
    kept = T.TrustWorld(MODEL_PKG, restore="on", preload={"sensor.in": "on"})
    cold.advance(599)
    restored.advance(599)
    c1, r1, k1 = cold.state(d), restored.state(d), kept.state(d)
    cold.advance(1)
    restored.advance(1)
    rec("model: a delayed binary sensor whose first result is true (the input already on when it is first rendered) reads unknown with no state to take back, off when it takes back off "
        "and on when it takes back on; the first two are on after the delay", (c1, r1, k1, cold.state(d), restored.state(d)) == ("unknown", "off", "on", "on", "on"), f"{c1} {r1} {k1}")
    # a template reload: a delayed binary sensor takes back the state it had when it was removed (on or off, not unavailable or unknown); a count in progress restarts
    rl = T.TrustWorld(MODEL_PKG)
    rl.put("sensor.in", "on")
    rl.advance(700)
    was_on = rl.state(d)
    rl.reload()
    now_on = rl.state(d)
    rl2 = T.TrustWorld(MODEL_PKG)
    rl2.put("sensor.in", "off")
    rl2.put("sensor.in", "on")
    rl2.advance(300)
    rl2.reload()
    counting = rl2.state(d)
    rl2.advance(599)
    c_599 = rl2.state(d)
    rl2.advance(1)
    c_600 = rl2.state(d)
    rl3 = T.TrustWorld(MODEL_PKG)
    rl3.put("sensor.in", "unavailable")
    rl3.reload()
    rl3.put("sensor.in", "on")
    gone = rl3.state(d)
    rec("model: a template reload creates every entity again and a delayed binary sensor takes back its last on or off state: on stays on; a count in progress restarts (off, then on "
        "after the full delay); one that was unavailable has nothing to take back (unknown until the delay ends)",
        (was_on, now_on, counting, c_599, c_600, gone) == ("on", "on", "off", "off", "on", "unknown"), f"{was_on} {now_on} {counting} {c_599} {c_600} {gone}")
    # dates, as Home Assistant reads them
    z = T.ZoneInfo("Europe/London")
    base = T.datetime(2026, 11, 25, 12, 0, 0, tzinfo=z).timestamp()
    reads = {"2026-11-25 12:00:00": base, "2026-11-25 12:00": base, "2026-11-25T12:00:00": base, "2026-11-25 12:00:00.5": base + 0.5, "2026-11-25 12:00:00+00:00": base,
             "2026-11-25 12:00:00+01:00": base - 3600, "2026-11-25 12:00:00Z": base, "2026-11-25": base - 12 * 3600}
    bad = []
    for txt, want in reads.items():
        try:
            got = T.ha_as_timestamp(txt, z)
        except ValueError:
            got = None
        if got != want:
            bad.append(f"{txt!r} -> {got}")
    errs = []
    for junk in ("abc", "", "5", "2026-13-45 12:00:00", "2026-02-30 12:00:00", None, 5, "12:00:00"):
        try:
            T.ha_as_timestamp(junk, z)
            errs.append(repr(junk))
        except (ValueError, TypeError):
            pass
    fixed = {t_: T.datetime.strptime(t_, T.FMT) for t_ in ("2026-11-25 12:00:00",)}
    rec("model: as_timestamp reads what Home Assistant's own parser reads (the date alone, no seconds, a T, fractions, an offset, Z), as local time in the zone when there is no offset, and "
        "refuses anything else (a number, an impossible date); strptime is Python's (the exact format only)",
        not bad and not errs and fixed["2026-11-25 12:00:00"] == T.datetime(2026, 11, 25, 12, 0, 0), f"{bad} {errs}")
    sp = T.TrustWorld(MODEL_PKG)
    env = sp.w.env
    probe = env.from_string("{{ strptime(t, '%Y-%m-%d %H:%M:%S', none) is none }}")
    exact = [probe.render(t=t_) for t_ in ("2026-11-25 12:00:00", "2026-11-25 12:00", "2026-11-25", "2026-11-25T12:00:00", "2026-11-25 12:00:00.5", "2026-11-25 12:00:00+01:00",
                                         " 2026-11-25 12:00:00", "2026-11-25 12:00:00 ", "2026-11-25 12:00:00\n", "abc", "")]
    rec("model: strptime with the firmware's format (and a default) reads only that exact form: every other spelling gives the default",
        exact == ["False"] + ["True"] * 10, str(exact))


# --- [2] scenarios --------------------------------------------------------------------------------
def sec_scenarios(text, rec):
    # --- normal, and the stall flag that flickers (three hours): the usual 60 s and 120 s episodes never trip anything
    tw = world(text)
    verify(rec, "normal (difference 10 s, NTP synced and advancing, no flag): every clock TRUSTED, the overall state TRUSTED, the three consumers on, "
           "skew 0 s, text age 0 s", tw, exp(),
           extra=[] if (tw.attr(K["HA"], "skew_s"), tw.attr(K["HA"], "text_age_s"), tw.attr(K["INV"], "difference_s"), tw.attr(K["ALL"], "ha_clock_skew_s"),
                        tw.attr(K["ALL"], "inverter_difference_s")) == (0, 0, 10, 0, 10) else ["attributes"])
    bad = []
    on_minutes = {m for m in range(180) if m % 17 == 0} | {m + 1 for m in range(0, 180, 85)}
    for minute in range(180):
        tw.put(STALL, "on" if minute in on_minutes else "off")
        tw.put(CORR, "on" if minute % 30 == 5 else "off")
        tw.advance(60)
        got = (tw.state(K["INV"]), tw.state(K["SLOT"]), tw.state(K["ALL"]), tw.state(K["STALLS"]), tw.state(K["STUCK"]))
        if got != ("TRUSTED", "on", "TRUSTED", "off", "off"):
            bad.append(f"minute {minute}: {got}")
            break
    rec("normal with the saved data's flicker for three hours (the stall flag on for 60 s every 17 minutes and for 120 s every 85, a correction in progress for a minute every "
        "30): the inverter clock stays TRUSTED and slot edits stay on at every minute (180 reads)", not bad and not tw.errors, str(bad[:1] + tw.errors[:1]))
    # --- the difference
    for diff, want, slot in (("70", "DEGRADED", "off"), ("-70", "DEGRADED", "off"), ("130", "UNTRUSTED", "off"), ("-130", "UNTRUSTED", "off")):
        tw = world(text, diff=diff)
        verify(rec, f"a clock difference of {diff} s: the inverter clock is {want}, slot edits {slot}, the other two clocks and the lease and schedule consumers unaffected",
               tw, exp(INV=want, ALL=want, SLOT=slot))
    # --- NTP unsynced: the dongle NTP is UNTRUSTED, leases and schedules off, and the inverter clock cannot be measured (UNKNOWN)
    tw = world(text, synced="off")
    verify(rec, "NTP not synced: the dongle NTP clock is UNTRUSTED, the overall state UNTRUSTED, leases and schedules off; the inverter clock is UNKNOWN (its difference is "
           "measured against that NTP) and slot edits are off; the Home Assistant clock is still compared against the text", tw,
           exp(NTP="UNTRUSTED", INV="UNKNOWN", ALL="UNTRUSTED", LEASES="off", SCHED="off", SLOT="off"))
    # --- the NTP text frozen: noticed by time alone
    tw = world(text)
    tw.h_ntp["on"] = False
    tw.advance(240)
    verify(rec, "the NTP text frozen for 4 minutes: still TRUSTED (text age 240 s)", tw, exp(),
           extra=[] if tw.attr(K["NTP"], "text_age_s") == 240 else ["age"])
    tw.advance(60)
    verify(rec, "the NTP text frozen for exactly 5 minutes (age 300 s): still TRUSTED (changed within the last 5 minutes)", tw, exp())
    tw.advance(1)
    tw.force()
    verify(rec, "the NTP text frozen for 5 minutes and 1 second: the dongle NTP clock is UNTRUSTED, the Home Assistant clock UNKNOWN (it cannot be compared), the overall state "
           "UNTRUSTED, leases and schedules off; the inverter clock and slot edits are unaffected", tw,
           exp(HA="UNKNOWN", NTP="UNTRUSTED", ALL="UNTRUSTED", LEASES="off", SCHED="off"))
    tw.advance(59)
    verify(rec, "the NTP text frozen for 6 minutes, with no entity changing: still UNTRUSTED (the minute render sees the age by itself)", tw,
           exp(HA="UNKNOWN", NTP="UNTRUSTED", ALL="UNTRUSTED", LEASES="off", SCHED="off"))
    tw.h_ntp = tw.feed(NTP_TEXT)
    verify(rec, "the NTP text published again: TRUSTED at once (it never stopped being readable, so the LIVE condition is met)", tw, exp())
    # --- what the dongle says it has instead of a time
    for text_in, label in (("Waiting for NTP", "'Waiting for NTP'"), ("NTP time invalid", "'NTP time invalid'")):
        tw = world(text, ntp=text_in)
        verify(rec, f"the NTP text says {label} while the flag is on: the dongle NTP clock is UNTRUSTED (not a time), the Home Assistant clock UNKNOWN, leases and schedules off", tw,
               exp(HA="UNKNOWN", NTP="UNTRUSTED", ALL="UNTRUSTED", LEASES="off", SCHED="off"))
    # --- the Home Assistant clock
    for off, want, lease in ((130, "DEGRADED", "on"), (-130, "DEGRADED", "on"), (310, "UNTRUSTED", "off"), (-310, "UNTRUSTED", "off")):
        tw = world(text, ha_offset=off)
        verify(rec, f"the Home Assistant clock {off:+d} s from the dongle's NTP: the HA clock is {want}, the overall state {want}, leases and schedules {lease}; slot edits unaffected",
               tw, exp(HA=want, ALL=want, LEASES=lease, SCHED=lease),
               extra=[] if tw.attr(K["HA"], "skew_s") == off and tw.attr(K["ALL"], "ha_clock_skew_s") == off else [f"skew_s {tw.attr(K['HA'], 'skew_s')}"])
    tw = world(text, ha_offset=100, warm=300)
    tw.advance(30)
    tw.force()
    verify(rec, "the skew is measured when the text arrived, so it does not grow with the text's age: a clock 100 s ahead reads +100 s (TRUSTED) 30 s after the last publication, with text_age_s 30", tw,
           exp(), extra=[] if (tw.attr(K["HA"], "skew_s"), tw.attr(K["HA"], "text_age_s")) == (100, 30) else [str((tw.attr(K["HA"], "skew_s"), tw.attr(K["HA"], "text_age_s")))])
    # --- the stall flag and the correction flag over time (the stall count is 3 minutes 30 s: four consecutive reads trip it, three do not)
    tw = world(text)
    tw.put(STALL, "on")
    tw.advance(150)
    verify(rec, "the stall flag on for 2 minutes 30 s (more than the usual 60 s and 120 s episodes): not counted (the inverter clock TRUSTED)", tw, exp())
    tw.advance(59)
    verify(rec, "the stall flag on for 3 minutes 29 s (three reads, 180 s, and a margin): not counted", tw, exp())
    tw.advance(1)
    verify(rec, "the stall flag on for 3 minutes 30 s (four reads): counted: the inverter clock DEGRADED, the overall state DEGRADED, slot edits off, leases and schedules still on", tw,
           exp(INV="DEGRADED", ALL="DEGRADED", SLOT="off", STALLS="on"))
    tw.advance(60)
    verify(rec, "the stall flag on for 4 minutes 30 s: still DEGRADED", tw, exp(INV="DEGRADED", ALL="DEGRADED", SLOT="off", STALLS="on"))
    tw.put(STALL, "off")
    verify(rec, "the stall flag off: TRUSTED again at once", tw, exp())
    tw.put(STALL, "on")
    tw.advance(180)
    tw.put(STALL, "off")
    tw.advance(1)
    tw.put(STALL, "on")
    tw.advance(180)
    verify(rec, "3 minutes on, 1 s off, 3 minutes on: the count restarted, never counted", tw, exp())
    tw.put(STALL, "unavailable")
    verify(rec, "an unreadable stall flag is never a quiet off: the helper is unavailable and the inverter clock UNKNOWN", tw, exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off", STALLS="unavailable"))
    tw = world(text)
    tw.put(CORR, "on")
    tw.advance(240)
    verify(rec, "a correction in progress for 4 minutes: not stuck (TRUSTED)", tw, exp())
    tw.advance(60)
    verify(rec, "a correction in progress for 5 minutes: stuck: the inverter clock UNTRUSTED, slot edits off, the overall state UNTRUSTED", tw,
           exp(INV="UNTRUSTED", ALL="UNTRUSTED", SLOT="off", STUCK="on"))
    tw.advance(60)
    verify(rec, "a correction in progress for 6 minutes: still UNTRUSTED", tw, exp(INV="UNTRUSTED", ALL="UNTRUSTED", SLOT="off", STUCK="on"))
    tw.put(CORR, "off")
    verify(rec, "the correction finished: TRUSTED at once", tw, exp())
    # --- the failure counters (latched until the dongle reboots), however large
    for failed, maxerr, diff, want in (("1", "77", "10", "DEGRADED"), ("3", "77", "10", "DEGRADED"), ("5", "77", "10", "DEGRADED"), ("50", "77", "10", "DEGRADED"),
                                       ("0", "121", "10", "DEGRADED"), ("0", "500", "10", "DEGRADED"), ("0", "1000", "10", "DEGRADED"), ("0", "3600", "10", "DEGRADED"),
                                       ("1", "77", "130", "UNTRUSTED"), ("0", "77", "10", "TRUSTED"), ("0", "120", "10", "TRUSTED")):
        tw = world(text, failed=failed, maxerr=maxerr, diff=diff)
        verify(rec, f"failed corrections {failed}, maximum clock error {maxerr} s, difference {diff} s: the inverter clock is {want}", tw,
               exp(INV=want, ALL=want, SLOT="on" if want == "TRUSTED" else "off"))
    # --- a whole hour or half a day of difference is UNTRUSTED like any other large difference (the clock-change hour is 3600 s)
    for diff in ("3600", "-3600", "7200", "43200", "-43200", "999999999"):
        tw = world(text, diff=diff)
        verify(rec, f"a clock difference of {diff} s: the inverter clock is UNTRUSTED (never forgiven as a whole hour or half a day), slot edits off", tw, exp(INV="UNTRUSTED", ALL="UNTRUSTED", SLOT="off"))
    # --- each input unreadable, one at a time (unavailable, unknown, and an entity that does not exist)
    one = {
        "the NTP time text": dict(ntp=None, expect=exp(HA="UNKNOWN", NTP="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off"), put=(NTP_TEXT,)),
        "the NTP synced flag": dict(synced=None, expect=exp(NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"), put=(SYNCED,)),
        "the inverter time text": dict(inv=None, expect=exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off"), put=(INV_TEXT,)),
        "the clock difference": dict(diff=None, expect=exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off"), put=(DIFF,)),
        "the failed corrections counter": dict(failed=None, expect=exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off"), put=(FAILED,)),
        "the maximum clock error": dict(maxerr=None, expect=exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off"), put=(MAXERR,)),
        "the stall flag": dict(stall=None, expect=exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off", STALLS="unavailable"), put=(STALL,)),
        "the correction flag": dict(corr=None, expect=exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off", STUCK="unavailable"), put=(CORR,)),
    }
    for label, spec in one.items():
        for how in ("missing", "unavailable", "unknown"):
            kw = {k: v for k, v in spec.items() if k not in ("expect", "put")}
            tw = world(text, **kw)
            if how != "missing":
                for eid in spec["put"]:
                    tw.put(eid, how)
                    if eid in (NTP_TEXT, INV_TEXT):
                        for h in (tw.h_ntp, tw.h_inv):
                            if h:
                                h["on"] = False
                tw.advance(60)
            verify(rec, f"{label} {how}: only the clocks that read it fall to UNKNOWN (never TRUSTED), the overall state is UNKNOWN, the consumers that depend on them are off", tw, spec["expect"])
    tw = world(text)
    for eid in (NTP_TEXT, INV_TEXT, DIFF, FAILED, MAXERR, SYNCED, STALL, CORR):
        tw.put(eid, "unavailable")
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    tw.advance(60)
    verify(rec, "the dongle unavailable (every input at once): every clock UNKNOWN, the overall state UNKNOWN (never better than DEGRADED), every consumer off", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off", STALLS="unavailable", STUCK="unavailable", RDN="off", RDI="off"))
    for eid, v in ((DIFF, "10"), (FAILED, "0"), (MAXERR, "77"), (SYNCED, "on"), (STALL, "off"), (CORR, "off")):
        tw.put(eid, v)
    tw.h_ntp = tw.feed(NTP_TEXT)
    tw.h_inv = tw.feed(INV_TEXT, offset_s=7)
    tw.advance(59)
    verify(rec, "the dongle back, 59 s after its values returned: every clock still UNKNOWN (the texts have not changed since they became readable: what returns first is the copy "
           "that was re-sent, which proves nothing), every consumer off", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off", STALLS="off", STUCK="off", RDN="on", RDI="on"))
    tw.advance(1)
    verify(rec, "the dongle back, 60 s after (its first live publication and read): every clock TRUSTED (nothing latches an outage)", tw, exp())
    tw = world(text)
    for eid in (NTP_TEXT, INV_TEXT, DIFF, FAILED, MAXERR, SYNCED, STALL, CORR):
        tw.put(eid, None)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    tw.advance(60)
    verify(rec, "every dongle entity missing (a fresh installation, a renamed device): every clock UNKNOWN, every consumer off", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"))
    # --- the inverter time text that stopped (a dead read path leaves the last difference in place)
    tw = world(text)
    tw.h_inv["on"] = False
    tw.advance(300)
    verify(rec, "the inverter time text unchanged for 5 minutes: still TRUSTED", tw, exp())
    tw.advance(1)
    tw.force()
    verify(rec, "the inverter time text unchanged for 5 minutes 1 s (the clock is no longer being read, the last difference still says 10 s): the inverter clock is UNKNOWN, slot edits off; "
           "the Home Assistant clock and the dongle NTP are unaffected", tw, exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off"))
    # --- the clock-change hour, and a time-zone mismatch (the R9 assumption)
    tw = world(text, start="2026-10-25 00:30:00", warm=3600)            # 00:30 BST + 1 h = 00:30 UTC, the first 01:30 (BST)
    ok_first = tw.state(K["HA"])
    tw.advance(3600)                                                     # 01:30 UTC, the second 01:30 (GMT): the text reads 01:30, which is read as the first one
    in_second = (tw.state(K["HA"]), tw.attr(K["HA"], "skew_s"), tw.state(K["LEASES"]), tw.state(K["SCHED"]), tw.state(K["NTP"]), tw.state(K["INV"]), tw.state(K["SLOT"]))
    tw.advance(3600)                                                     # 02:30 UTC
    after = tw.state(K["HA"])
    rec("the autumn clock change: the Home Assistant clock is TRUSTED before the repeated hour and UNTRUSTED (skew +3600 s, leases and schedules off) for the second pass of it "
        "(the repeated local time is read as its first occurrence: documented, it fails safe); the texts are then an hour from Home Assistant's clock, so the dongle NTP and the inverter "
        "clock are UNKNOWN and slot edits are off; TRUSTED again after",
        (ok_first, in_second, after) == ("TRUSTED", ("UNTRUSTED", 3600, "off", "off", "UNKNOWN", "UNKNOWN", "off"), "TRUSTED") and not tw.errors, f"{ok_first} {in_second} {after}")
    tw = world(text, start="2026-07-01 12:00:00", ha_zone="UTC", dongle_zone="Europe/London")
    verify(rec, "the R9 time-zone assumption: Home Assistant in UTC and a dongle in Europe/London in summer: the skew reads whole hours (-3600 s), UNTRUSTED, never TRUSTED; the dongle NTP "
           "and the inverter clock are UNKNOWN (their texts are an hour from Home Assistant's clock) and slot edits are off", tw,
           exp(HA="UNTRUSTED", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNTRUSTED", LEASES="off", SCHED="off", SLOT="off"),
           extra=[] if tw.attr(K["HA"], "skew_s") == -3600 else [str(tw.attr(K["HA"], "skew_s"))])
    tw = world(text, start="2026-07-01 12:00:00")
    verify(rec, "the same summer day with Home Assistant and the dongle in the same zone: TRUSTED", tw, exp())


# --- [2b] restarts, reconnects, reloads, spellings ------------------------------------------------
def sec_restarts(text, rec):
    ALL_DONGLE = (NTP_TEXT, INV_TEXT, DIFF, FAILED, MAXERR, SYNCED, STALL, CORR)

    def blip(tw, gap=20.0, eids=ALL_DONGLE):
        """The dongle's API drops and comes back: every dongle entity reads unavailable for `gap` seconds. Returns the values they had (what ESPHome re-sends on subscribe)."""
        cached = {e: tw.state(e) for e in eids}
        for h in (getattr(tw, "h_ntp", None), getattr(tw, "h_inv", None)):
            if h:
                h["on"] = False
        for e in eids:
            tw.put(e, "unavailable")
        tw.advance(gap)
        return cached

    def feeds_after(tw, delay):
        """The dongle's own publications resume `delay` s from now (the first one is live)."""
        def go():
            tw.h_ntp = tw.feed(NTP_TEXT)
            tw.h_inv = tw.feed(INV_TEXT, offset_s=7)
        tw.w.after(delay, go)

    def restart(start, cached, restore="off", ha_offset=0):
        """Home Assistant restarts: the package's entities are created first and the dongle's entities arrive afterwards with the values they had."""
        tw = T.TrustWorld(text, start=start, restore=restore)
        tw.w.clock_offset = ha_offset
        for e, v in cached.items():
            tw.put(e, v)
        return tw

    def never_trusted(tw, keys, minutes, step=30.0, gate=("SLOT",)):
        bad = []
        for _ in range(int(minutes * 60 / step) + 1):
            for k in keys:
                if tw.state(K[k]) == "TRUSTED":
                    bad.append(f"{k} TRUSTED at +{int(_ * step)} s")
            for g in gate:
                if tw.state(K[g]) == "on":
                    bad.append(f"{g} on at +{int(_ * step)} s")
            tw.advance(step)
        return bad

    # --- the MAJOR finding: a read path that has been dead for hours, then a reconnect that re-sends the stale cached values
    tw = world(text)
    tw.h_inv["on"] = False
    tw.advance(7200)
    verify(rec, "a read path dead for 2 hours (the inverter time text frozen): the inverter clock UNKNOWN, slot edits off; the other two clocks TRUSTED", tw, exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off"))
    stale_text = tw.state(INV_TEXT)
    cached = blip(tw, 20.0)
    for e, v in cached.items():
        if e != NTP_TEXT:
            tw.put(e, v)                                                  # the cached copies, the stale inverter text among them
    tw.put(NTP_TEXT, cached[NTP_TEXT])
    verify(rec, "the dongle's API reconnects after 20 s and re-sends its cached values (the inverter time text two hours old, last_changed now): every clock is UNKNOWN, every consumer off "
           "(before the fix: the inverter clock TRUSTED and slot edits on for about 6 minutes)", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"), extra=[] if tw.state(INV_TEXT) == stale_text else ["text"])
    feeds_after(tw, 60.0)
    tw.advance(60)
    verify(rec, "the dongle's own publications resume 60 s later (a live NTP publication and a live inverter read): every clock TRUSTED again, the consumers on", tw, exp())
    tw = world(text)
    tw.h_inv["on"] = False
    tw.advance(7200)
    cached = blip(tw, 20.0)
    for e, v in cached.items():
        tw.put(e, v)
    tw.h_ntp = tw.feed(NTP_TEXT)                                          # the NTP text keeps being published; the inverter read path stays dead
    bad = never_trusted(tw, ("INV",), 11)
    rec("the same reconnect with the inverter read path still dead: the inverter clock stays UNKNOWN and slot edits stay off at every 30 s for 11 minutes", not bad, str(bad[:2]))
    verify(rec, "and the Home Assistant clock and the dongle NTP are TRUSTED again after their first live publication (a dead inverter read path does not cost leases or schedules)", tw,
           exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off"))
    # --- a Home Assistant restart that delivers the stale text
    cached = {INV_TEXT: "2026-11-25 12:02:07", DIFF: "10", FAILED: "0", MAXERR: "77", SYNCED: "on", STALL: "off", CORR: "off"}
    tw = restart("2026-11-25 14:00:00", cached)
    tw.feed(NTP_TEXT)
    tw.advance(30)
    verify(rec, "a Home Assistant restart that finds the inverter time text two hours old (the dead read path, and the cached copy delivered as the dongle connects): every clock UNKNOWN, consumers off", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"))
    bad = never_trusted(tw, ("INV",), 12)
    rec("and the inverter clock never reads TRUSTED, nor slot edits on, in the 12 minutes that follow while the read path stays dead", not bad, str(bad[:2]))
    # --- a correction stuck for 4 minutes, then a Home Assistant restart: the reads are skipped, so the text is stale and the debounce count starts again
    tw = world(text)
    tw.h_inv["on"] = False
    tw.put(CORR, "on")
    tw.advance(240)
    verify(rec, "a correction in progress for 4 minutes with the reads skipped (the firmware does not read the clock during one): not yet counted, the text 4 minutes old", tw, exp())
    pre = {e: tw.state(e) for e in (INV_TEXT, DIFF, FAILED, MAXERR, SYNCED, STALL, CORR)}
    tw = restart("2026-11-25 12:06:00", pre)
    tw.feed(NTP_TEXT)
    tw.advance(10)
    a = (tw.state(K["INV"]), tw.state(K["SLOT"]), tw.state(K["STUCK"]))
    bad = never_trusted(tw, ("INV",), 4.5)
    tw.advance(30)
    b = (tw.state(K["INV"]), tw.state(K["SLOT"]), tw.state(K["STUCK"]))
    rec("the restart (the helper takes back off, the flag is still on, the inverter time text stale): the inverter clock is UNKNOWN at once and never TRUSTED, slot edits off, and "
        "UNTRUSTED when the restarted count reaches 5 minutes (before the fix: TRUSTED with slot edits on for about 5 more minutes, 9 minutes after the correction began)",
        a == ("UNKNOWN", "off", "off") and not bad and b == ("UNTRUSTED", "off", "on"), f"{a} {b} {bad[:1]}")
    # --- a Home Assistant clock behind the dongle's time, and a reconnect that re-sends a cached NTP text (up to one publication old)
    for off, before, lease in ((-150, "DEGRADED", "on"), (-330, "UNTRUSTED", "off")):
        for full in (False, True):
            tw = world(text, ha_offset=off, warm=125)
            b0 = (tw.state(K["HA"]), tw.attr(K["HA"], "skew_s"), tw.state(K["LEASES"]), tw.state(K["SCHED"]))
            cached_ntp = tw.local_text(tw.w.t - 59)                       # what the dongle published 59 s ago (its cached state)
            if full:
                cached = blip(tw, 1.0)
                for e, v in cached.items():
                    if e != NTP_TEXT:
                        tw.put(e, v)
            else:
                tw.h_ntp["on"] = False
                tw.put(NTP_TEXT, "unavailable")
                tw.advance(1)
            tw.put(NTP_TEXT, cached_ntp)
            r0 = (tw.state(K["HA"]), tw.attr(K["HA"], "skew_s"), tw.state(K["LEASES"]), tw.state(K["SCHED"]))
            tw.advance(30)
            r1 = (tw.state(K["HA"]), tw.state(K["LEASES"]), tw.state(K["SCHED"]), tw.state(K["ALL"]))
            tw.h_ntp = tw.feed(NTP_TEXT)                                  # the dongle publishes again: a live text, 31 s after the text became readable
            tw.advance(1)
            r2 = (tw.state(K["HA"]), tw.attr(K["HA"], "skew_s"), tw.state(K["LEASES"]), tw.state(K["SCHED"]))
            which = "every dongle entity" if full else "the NTP text alone"
            rec(f"a Home Assistant clock {-off} s behind ({before}, leases {lease}) and a reconnect of {which} that re-sends a 59 s old NTP text (up to one publication old): the Home Assistant clock is "
                f"UNKNOWN with leases and schedules off (the old rule read skew {off + 59}, a better verdict than the truth) and still UNKNOWN 30 s later; the next live publication "
                f"gives {before} with skew {off} s again", b0 == (before, off, lease, lease)
                and r0 == ("UNKNOWN", "unknown", "off", "off") and r1[:3] == ("UNKNOWN", "off", "off") and r2 == (before, off, lease, lease), f"{b0} {r0} {r1} {r2}")
    # --- a healthy blip: every value comes back as the cached copy and nothing counts until the dongle publishes again
    tw = world(text)
    cached = blip(tw, 20.0)
    for e, v in cached.items():
        tw.put(e, v)
    feeds_after(tw, 60.0)
    verify(rec, "a healthy dongle that drops for 20 s: the cached values return and every clock is UNKNOWN, every consumer off, until the dongle publishes again", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"))
    tw.advance(59)
    verify(rec, "59 s after the cached values returned: still UNKNOWN", tw, dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"))
    tw.advance(1)
    verify(rec, "at the dongle's next publication and read: every clock TRUSTED, the consumers on", tw, exp())
    # --- one text alone becomes unreadable and readable again (every spelling of unreadable): the first value back is the cached copy, not a publication
    for key, eid, who, handle in (("RDN", NTP_TEXT, ("HA", "NTP"), "h_ntp"), ("RDI", INV_TEXT, ("INV",), "h_inv")):
        for gone in ("unavailable", "unknown", ""):
            tw = world(text)
            getattr(tw, handle)["on"] = False
            tw.put(eid, gone)
            mid = tuple(tw.state(K[k]) for k in who)
            tw.advance(30)
            tw.put(eid, tw.local_text(tw.w.t + tw.w.clock_offset) if eid == NTP_TEXT else inv_text(tw, 0))
            back = tuple(tw.state(K[k]) for k in who)
            tw.advance(30)
            later = tuple(tw.state(K[k]) for k in who)
            setattr(tw, handle, tw.feed(eid) if eid == NTP_TEXT else tw.feed(eid, offset_s=7))
            fresh = tuple(tw.state(K[k]) for k in who)
            rec(f"the {'NTP' if eid == NTP_TEXT else 'inverter'} time text alone reads {gone!r} for 30 s and then the cached copy returns: {'/'.join(who)} UNKNOWN while it is unreadable, UNKNOWN when it returns "
                "and 30 s later (nothing was published), TRUSTED at the next live publication",
                mid == ("UNKNOWN",) * len(who) and back == ("UNKNOWN",) * len(who) and later == ("UNKNOWN",) * len(who) and fresh == ("TRUSTED",) * len(who)
                and tw.state(K[key]) == "on", f"{mid} {back} {later} {fresh}")
    # --- the two LIVE helpers do not exist (a partial load, or a reload that has not created them yet): nothing that needs them can read TRUSTED
    cut_text = re.sub(r"      - name: ECCO Time Trust (?:NTP|Inverter) Text Readable\n(?:        .*\n)+\n", "", text)
    tw = world(cut_text)
    verify(rec, "the helpers of the LIVE condition missing: every clock UNKNOWN (never TRUSTED), every consumer off, and no template fails", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"), extra=[] if (cut_text != text and K["RDN"] not in tw.w.states) else ["not removed"])
    # --- an unreadable flag in the middle of a count: the availability template is a super template, so the count is not restarted
    tw = world(text)
    tw.put(STALL, "on")
    tw.advance(100)
    tw.put(STALL, "unavailable")
    verify(rec, "the stall flag unreadable in the middle of a count: the helper is unavailable and the inverter clock UNKNOWN", tw, exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off", STALLS="unavailable"))
    tw.advance(1)
    tw.put(STALL, "on")
    tw.advance(108)
    mid = (tw.state(K["STALLS"]), tw.state(K["INV"]))
    tw.advance(1)
    end = (tw.state(K["STALLS"]), tw.state(K["INV"]))
    rec("and back on after 1 s: the count was NOT restarted: still off at 3 minutes 29 s from the first on, on at 3 minutes 30 s (the helper's own availability template is a super template)",
        mid == ("off", "TRUSTED") and end == ("on", "DEGRADED"), f"{mid} {end}")
    tw = world(text)
    tw.put(STALL, "on")
    tw.advance(100)
    tw.put(STALL, "unavailable")
    tw.advance(50)
    tw.put(STALL, "off")
    tw.advance(2000)
    rec("a flag that returns OFF after the gap cancels the count: the helper never turns on", not any(h[1] == K["STALLS"] and h[2] == "on" for h in tw.w.history)
        and tw.state(K["STALLS"]) == "off" and tw.state(K["INV"]) == "TRUSTED", tw.state(K["STALLS"]))
    tw = world(text)
    tw.put(STALL, "on")
    tw.advance(60)
    tw.put(STALL, "unavailable")
    tw.advance(210)
    during = (tw.state(K["STALLS"]), tw.state(K["INV"]))
    tw.put(STALL, "on")
    after = (tw.state(K["STALLS"]), tw.state(K["INV"]))
    rec("a 60 s episode, then an outage of 3.5 minutes after which the flag is on again: the count ran through the gap, so the helper is on as soon as the flag is readable and the inverter clock "
        "DEGRADED (documented: it fails safe; the old model restarted the count)", during == ("unavailable", "UNKNOWN") and after == ("on", "DEGRADED"), f"{during} {after}")
    # --- a template reload: the helpers that read the texts are created again (the LIVE minute), the debounce helpers take back their state
    tw = world(text)
    tw.reload()
    verify(rec, "a template reload on a healthy world: every clock UNKNOWN (no text has changed since the new helpers saw it readable) and every consumer off; the two debounce helpers take back off", tw,
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off", STALLS="off", STUCK="off", RDN="on", RDI="on"))
    tw.advance(59)
    verify(rec, "59 s after the reload: still UNKNOWN", tw, dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off"))
    tw.advance(1)
    verify(rec, "at the next publication and read: TRUSTED again (a reload costs one minute, once)", tw, exp())
    tw = world(text)
    tw.put(STALL, "on")
    tw.advance(300)
    verify(rec, "the stall flag on for 5 minutes: the helper is on and the inverter clock DEGRADED", tw, exp(INV="DEGRADED", ALL="DEGRADED", SLOT="off", STALLS="on"))
    tw.reload()
    rl_on = (tw.state(K["STALLS"]), tw.state(K["INV"]))
    tw.advance(60)
    rl_on2 = (tw.state(K["STALLS"]), tw.state(K["INV"]), tw.state(K["SLOT"]))
    rec("a template reload with the sustained stall helper on: it takes back on at once (a reload does not clear a sustained stall), the inverter clock UNKNOWN for the LIVE minute and DEGRADED after",
        rl_on == ("on", "UNKNOWN") and rl_on2 == ("on", "DEGRADED", "off") and not tw.errors, f"{rl_on} {rl_on2}")
    tw = world(text)
    tw.put(STALL, "on")
    tw.advance(100)
    tw.reload()
    tw.advance(209)
    c1 = (tw.state(K["STALLS"]), tw.state(K["INV"]))
    tw.advance(1)
    c2 = (tw.state(K["STALLS"]), tw.state(K["INV"]))
    rec("a template reload with the stall count in progress (100 s): the helper takes back off and the count restarts, on 3 minutes 30 s after the reload (a stall that began earlier is noticed up to "
        "3.5 minutes late; documented)", c1 == ("off", "TRUSTED") and c2 == ("on", "DEGRADED"), f"{c1} {c2}")
    # --- the first installation (no state to take back) and a restart with the helper on, with the stall flag already on
    pre = {SYNCED: "on", DIFF: "10", FAILED: "0", MAXERR: "77", STALL: "on", CORR: "off"}
    for restore, want_a, label in ((None, ("unknown", "UNKNOWN"), "a first installation (no state to take back): the helper reads unknown for 3 minutes 30 s, which is UNKNOWN for the inverter clock"),
                                   ("off", ("off", "TRUSTED"), "a restart with the helper last off: the helper reads off for 3 minutes 30 s (documented: the count starts when Home Assistant first sees "
                                                               "the flag on, so a stall that began earlier is noticed up to 3.5 minutes late)"),
                                   ("on", ("on", "DEGRADED"), "a restart with the helper last on: it takes back on at once, the sustained stall is not forgotten")):
        tw = T.TrustWorld(text, start=START, restore=restore, preload=pre)
        tw.feed(NTP_TEXT)
        tw.feed(INV_TEXT, offset_s=7)
        tw.advance(209)
        a = (tw.state(K["STALLS"]), tw.state(K["INV"]))
        tw.advance(1)
        b = (tw.state(K["STALLS"]), tw.state(K["INV"]))
        rec(f"{label}, the stall flag already on; on at 3 minutes 30 s and the inverter clock DEGRADED", a == want_a and b == ("on", "DEGRADED"), f"{a} {b}")
    # --- texts in the other spellings Home Assistant's own parser accepts: none of them is a time, whatever second of the day the text arrives at
    tw = world(text, start="2026-11-25 00:00:00", warm=0, ntp=None, inv=None)
    tw.advance(30)
    bad = []
    for spelled in ("2026-11-25", "2026-11-25 00:00", "2026-11-25T00:00:30", "2026-11-25 00:00:30.5", "2026-11-25 00:00:30+00:00", "2026-11-25 00:00:30Z",
                    " 2026-11-25 00:00:30", "2026-11-25 00:00:30 ", "2026-11-25 00:00:30\n", "2026-11-25  00:00:30x"):
        tw.put(NTP_TEXT, spelled)
        tw.age(NTP_TEXT, 0)
        got = (tw.state(K["HA"]), tw.state(K["NTP"]), tw.state(K["LEASES"]), tw.state(K["SCHED"]))
        if got != ("UNKNOWN", "UNTRUSTED", "off", "off") or snapshot_problems(tw):
            bad.append(f"{spelled!r}: {got}")
    rec("a date alone (read as midnight, 30 s away), no seconds, a T, fractions, an offset, Z, a leading or trailing space or newline: not a time: the Home Assistant clock UNKNOWN, the dongle NTP "
        "UNTRUSTED, leases and schedules off (Home Assistant's own parser would read most of these as a time, and read the date alone as TRUSTED at 00:00:30)", not bad, str(bad[:2]))
    bad = []
    tw = world(text, start="2026-11-25 00:00:00", warm=0, ntp=None, inv=None)
    tw.advance(30)
    for spelled in ("2026-11-25", "2026-11-25 00:00", "2026-11-25T00:00:30", "2026-11-25 00:00:30.5", "2026-11-25 00:00:30+00:00", " 2026-11-25 00:00:30", "2026-11-25 00:00:30\n"):
        tw.put(INV_TEXT, spelled)
        tw.age(INV_TEXT, 0)
        got = (tw.state(K["INV"]), tw.state(K["SLOT"]))
        if got != ("UNKNOWN", "off") or snapshot_problems(tw):
            bad.append(f"{spelled!r}: {got}")
    rec("the same spellings as the inverter time text: not a time, so the inverter clock is UNKNOWN and slot edits are off", not bad, str(bad[:2]))
    # --- a stuck correction with the stall flag on and the reads stopped (the firmware skips the reads during a correction: the stall flag keeps its last value)
    tw = world(text)
    tw.put(STALL, "on")
    tw.put(CORR, "on")
    tw.h_inv["on"] = False
    tw.advance(301)
    verify(rec, "a correction in progress for 5 minutes with the stall flag on and the reads stopped: the stuck helper counts although the stall flag is on (the inverter clock UNTRUSTED, not merely "
           "DEGRADED by the stall), slot edits off", tw, exp(INV="UNTRUSTED", ALL="UNTRUSTED", SLOT="off", STALLS="on", STUCK="on"))


# --- [3] boundaries -------------------------------------------------------------------------------
def sec_boundaries(text, rec):
    ha_table = ((0, "TRUSTED"), (119, "TRUSTED"), (120, "TRUSTED"), (121, "DEGRADED"), (299, "DEGRADED"), (300, "DEGRADED"), (301, "UNTRUSTED"),
                (-119, "TRUSTED"), (-120, "TRUSTED"), (-121, "DEGRADED"), (-299, "DEGRADED"), (-300, "DEGRADED"), (-301, "UNTRUSTED"), (3600, "UNTRUSTED"),
                (-3600, "UNTRUSTED"), (43200, "UNTRUSTED"), (86400, "UNTRUSTED"), (-86400, "UNTRUSTED"),
                (120.4, "TRUSTED"), (120.6, "DEGRADED"), (300.4, "DEGRADED"), (300.6, "UNTRUSTED"), (-120.4, "TRUSTED"), (-120.6, "DEGRADED"), (-300.6, "UNTRUSTED"))
    bad = []
    tw = world(text)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    for off, want in ha_table:
        tw.w.clock_offset = off                                  # Home Assistant's clock is `off` s from the dongle's; a text arrives now
        tw.put(NTP_TEXT, tw.local_text(tw.w.t))
        tw.age(NTP_TEXT, 0)
        tw.age(K["RDN"], 86400)                                 # it has been readable for a day, by Home Assistant's clock at this offset
        got = tw.state(K["HA"])
        if got != want or tw.attr(K["HA"], "skew_s") != round(off) or snapshot_problems(tw):
            bad.append(f"{off}: {got}")
    tw.w.clock_offset = 0
    rec("the Home Assistant clock skew at every limit and both signs (+-119, 120, 121, 299, 300, 301, 3600, 43200, 86400, and 120.4 / 120.6 / 300.4 / 300.6, which round to whole seconds): "
        "TRUSTED up to and including 120 s, DEGRADED up to and including 300 s, UNTRUSTED above, however large (a day too)", not bad, str(bad[:3]))
    for off in (3600, -3600, 43200, 86400, -86400):
        tw = world(text, ha_offset=off)
        verify(rec, f"a Home Assistant clock {off:+d} s from the dongle (a time zone, a host booting with a stale date): the HA clock UNTRUSTED with that skew, the overall state UNTRUSTED, leases and "
               "schedules off; the dongle NTP and the inverter clock UNKNOWN (their texts are far from Home Assistant's clock: the VALUE rule), slot edits off", tw,
               exp(HA="UNTRUSTED", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNTRUSTED", LEASES="off", SCHED="off", SLOT="off"),
               extra=[] if tw.attr(K["HA"], "skew_s") == off else [str(tw.attr(K["HA"], "skew_s"))])
    inv_table = (("0", "TRUSTED"), ("10", "TRUSTED"), ("59", "TRUSTED"), ("60", "TRUSTED"), ("61", "DEGRADED"), ("119", "DEGRADED"), ("120", "DEGRADED"), ("121", "UNTRUSTED"),
                 ("-59", "TRUSTED"), ("-60", "TRUSTED"), ("-61", "DEGRADED"), ("-120", "DEGRADED"), ("-121", "UNTRUSTED"), ("300", "UNTRUSTED"), ("60.4", "DEGRADED"),
                 ("3600", "UNTRUSTED"), ("-3600", "UNTRUSTED"), ("7200", "UNTRUSTED"), ("43200", "UNTRUSTED"), ("-43200", "UNTRUSTED"), ("43199", "UNTRUSTED"), ("999999999", "UNTRUSTED"),
                 ("-999999999", "UNTRUSTED"))
    bad = []
    tw = world(text)
    for diff, want in inv_table:
        tw.put(DIFF, diff)
        if tw.state(K["INV"]) != want or snapshot_problems(tw):
            bad.append(f"{diff}: {tw.state(K['INV'])}")
        if tw.state(K["SLOT"]) != ("on" if want == "TRUSTED" else "off"):
            bad.append(f"slot at {diff}")
    tw.put(DIFF, "10")
    rec("the inverter clock difference at every limit and both signs (+-59, 60, 61, 119, 120, 121, 300, and a whole hour 3600, 7200, half a day 43200 and 999999999): TRUSTED up to and including 60 s, "
        "DEGRADED up to and including 120 s, UNTRUSTED above, however large; slot edits on only when TRUSTED", not bad, str(bad[:3]))
    bad = []
    for failed, want in (("0", "TRUSTED"), ("1", "DEGRADED"), ("2", "DEGRADED"), ("3", "DEGRADED"), ("4", "DEGRADED"), ("5", "DEGRADED"), ("6", "DEGRADED"), ("10", "DEGRADED"),
                         ("50", "DEGRADED"), ("1000", "DEGRADED"), ("999999999", "DEGRADED"), ("0.0", "TRUSTED")):
        tw.put(FAILED, failed)
        if tw.state(K["INV"]) != want:
            bad.append(f"failed {failed}: {tw.state(K['INV'])}")
    tw.put(FAILED, "0")
    for maxerr, want in (("0", "TRUSTED"), ("119", "TRUSTED"), ("120", "TRUSTED"), ("121", "DEGRADED"), ("77", "TRUSTED"), ("500", "DEGRADED"), ("999", "DEGRADED"), ("1000", "DEGRADED"),
                         ("1001", "DEGRADED"), ("3600", "DEGRADED"), ("43200", "DEGRADED"), ("999999999", "DEGRADED")):
        tw.put(MAXERR, maxerr)
        if tw.state(K["INV"]) != want:
            bad.append(f"max {maxerr}: {tw.state(K['INV'])}")
    rec("failed corrections above 0 (1, 2, 5, 10, 50 and more: none is forgiven) and a maximum clock error above 120 s (121, 1000 and more, 3600: none is forgiven), both since boot, degrade the "
        "inverter clock, at the limit on both sides", not bad, str(bad[:3]))
    # the age of the NTP text and of the inverter time text, exactly (the arrival rule)
    bad = []
    tw = world(text)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    for age, want_ntp, want_ha, want_inv in ((0, "TRUSTED", "TRUSTED", "TRUSTED"), (299, "TRUSTED", "TRUSTED", "TRUSTED"), (300, "TRUSTED", "TRUSTED", "TRUSTED"),
                                            (300.4, "TRUSTED", "TRUSTED", "TRUSTED"), (300.6, "UNTRUSTED", "UNKNOWN", "UNKNOWN"),
                                            (301, "UNTRUSTED", "UNKNOWN", "UNKNOWN"), (3600, "UNTRUSTED", "UNKNOWN", "UNKNOWN")):
        tw.put(NTP_TEXT, tw.local_text(tw.w.t + tw.w.clock_offset - age))      # a text a perfect dongle published `age` seconds ago
        tw.age(NTP_TEXT, age)
        tw.put(INV_TEXT, inv_text(tw, age))
        tw.age(INV_TEXT, age)
        got = (tw.state(K["NTP"]), tw.state(K["HA"]), tw.state(K["INV"]))
        if got != (want_ntp, want_ha, want_inv) or snapshot_problems(tw):
            bad.append(f"age {age}: {got}")
    rec("the age of the NTP text and of the inverter time text at the limit (0, 299, 300 and 300.4 TRUSTED; 300.6, 301 and 3600: the dongle NTP UNTRUSTED, the HA clock UNKNOWN, the inverter clock UNKNOWN; "
        "the age is rounded to whole seconds)", not bad, str(bad[:3]))
    # the VALUE rule: the time a text carries against Home Assistant's clock, with the arrival fresh and the text live
    bad = []
    tw = world(text)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    for v in (0, 120, 300, 599, 600, 601, 900, 3600, -299, -300, -599, -600, -601, -3600):
        tw.put(NTP_TEXT, tw.local_text(tw.w.t + tw.w.clock_offset - v))        # a text that is `v` s behind Home Assistant's clock, arriving now
        tw.age(NTP_TEXT, 0)
        got = (tw.state(K["NTP"]), tw.state(K["HA"]))
        want = ("TRUSTED" if abs(v) <= 600 else "UNKNOWN", o_ha("time", v, 0))
        if got != want or snapshot_problems(tw):
            bad.append(f"{v}: {got} != {want}")
    rec("the VALUE rule for the dongle's NTP text: a text within 600 s of Home Assistant's clock (either side: 599, 600) leaves the dongle NTP TRUSTED, one beyond (601, 900, 3600) makes it UNKNOWN, "
        "although it arrived now and is live; the Home Assistant clock is judged by the skew alone", not bad, str(bad[:3]))
    bad = []
    for v in (0, 300, 599, 600, 601, 900, 3600, 86400, -299, -300, -599, -600, -601, -3600, -86400):
        tw.put(INV_TEXT, inv_text(tw, v))                                      # the read it records is `v` s old by Home Assistant's clock (the difference is 10 s)
        tw.age(INV_TEXT, 0)
        got = (tw.state(K["INV"]), tw.state(K["SLOT"]))
        want = ("TRUSTED", "on") if abs(v) <= 600 else ("UNKNOWN", "off")
        if got != want or snapshot_problems(tw):
            bad.append(f"{v}: {got}")
    rec("the VALUE rule for the inverter: the read the text records (the text minus the difference) within 600 s of Home Assistant's clock (599, 600, either side) leaves the inverter clock TRUSTED, "
        "one beyond (601, 900, a day) makes it UNKNOWN and slot edits off, although the text arrived now and is live", not bad, str(bad[:3]))
    tw = world(text, ha_offset=0.4)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    tw.put(NTP_TEXT, tw.local_text(tw.w.t - 600))
    tw.age(NTP_TEXT, 0)
    a_ntp = tw.state(K["NTP"])
    sp_a_ntp = snapshot_problems(tw)
    tw = world(text, ha_offset=0.6)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    tw.put(NTP_TEXT, tw.local_text(tw.w.t - 600))
    tw.age(NTP_TEXT, 0)
    b_ntp = tw.state(K["NTP"])
    sp_b_ntp = snapshot_problems(tw)
    tw = world(text, diff="10.4")
    tw.h_inv["on"] = False
    tw.put(INV_TEXT, inv_text(tw, 600, 10.4))
    tw.age(INV_TEXT, 0)
    a_inv = tw.state(K["INV"])
    sp_a_inv = snapshot_problems(tw)
    tw = world(text, diff="10.6")
    tw.h_inv["on"] = False
    tw.put(INV_TEXT, inv_text(tw, 600, 10.6))
    tw.age(INV_TEXT, 0)
    b_inv = tw.state(K["INV"])
    sp_b_inv = snapshot_problems(tw)
    rec("the value age is rounded to whole seconds: 600.4 s reads 600 (inside the limit) and 600.6 s reads 601 (outside it), for the NTP text and for the inverter read",
        (a_ntp, b_ntp, a_inv, b_inv) == ("TRUSTED", "UNKNOWN", "TRUSTED", "UNKNOWN") and not (sp_a_ntp or sp_b_ntp or sp_a_inv or sp_b_inv),
        f"{a_ntp} {b_ntp} {a_inv} {b_inv} {(sp_a_ntp + sp_b_ntp + sp_a_inv + sp_b_inv)[:1]}")
    tw = world(text, diff="-45")
    tw.h_inv["on"] = False
    tw.put(INV_TEXT, inv_text(tw, 595, -45.0))                                 # the text is 640 s behind the clock; minus the difference of -45 s the read is 595 s old
    tw.age(INV_TEXT, 0)
    neg = (tw.state(K["INV"]), tw.attr(K["INV"], "difference_s"))
    tw = world(text, diff="45")
    tw.h_inv["on"] = False
    tw.put(INV_TEXT, inv_text(tw, 605, 45.0))                                  # the text is 560 s behind the clock; minus the difference of +45 s the read is 605 s old
    tw.age(INV_TEXT, 0)
    pos = tw.state(K["INV"])
    rec("the read age is the text MINUS the difference, with its sign: a text 640 s behind the clock for a difference of -45 s records a read 595 s old (inside the limit), a text 560 s behind the "
        "clock for a difference of +45 s records one 605 s old (outside it); adding the difference instead would swap the two", neg == ("TRUSTED", -45) and pos == "UNKNOWN", f"{neg} {pos}")
    # the LIVE rule: the text changed more than 10 s after its helper last changed
    bad = []
    for helper, text_eid, label in ((K["RDN"], NTP_TEXT, "NTP"), (K["RDI"], INV_TEXT, "INV")):
        for gap, live in ((-60, False), (0, False), (9, False), (10, False), (11, True), (60, True), (3600, True)):
            tw = world(text)
            tw.h_ntp["on"] = tw.h_inv["on"] = False
            tw.age(text_eid, 100)
            tw.age(helper, 100 + gap)
            if label == "NTP":
                want = dict(HA="TRUSTED" if live else "UNKNOWN", NTP="TRUSTED" if live else "UNKNOWN", INV="TRUSTED")
            else:
                want = dict(HA="TRUSTED", NTP="TRUSTED", INV="TRUSTED" if live else "UNKNOWN")
            got = {k: tw.state(K[k]) for k in ("HA", "NTP", "INV")}
            if got != want or snapshot_problems(tw):
                bad.append(f"{label} gap {gap}: {got}")
    rec("the LIVE rule at the limit, for each text: a text that changed 11 s or more after it became readable is live (TRUSTED); 10 s, 9 s, 0 s or before is not (the dongle NTP and the Home Assistant "
        "clock UNKNOWN for the NTP text, the inverter clock UNKNOWN for the inverter text)", not bad, str(bad[:3]))
    # the helper must read on: while it reads off, unavailable or unknown with the text readable (a helper that has not yet followed the text in a state change) the text is not live
    bad = []
    for key, who in (("RDN", ("HA", "NTP")), ("RDI", ("INV",))):
        for shown in ("off", "unavailable", "unknown"):
            tw = world(text)
            tw.override(K[key], shown)
            tw.age(K[key], 86400)                                  # a helper that still carries its old last_changed while it does not read on
            got = {k: tw.state(K[k]) for k in ("HA", "NTP", "INV")}
            want = {k: ("UNKNOWN" if k in who else "TRUSTED") for k in ("HA", "NTP", "INV")}
            if got != want or snapshot_problems(tw):
                bad.append(f"{key} {shown}: {got} {snapshot_problems(tw)[:1]}")
    rec("the LIVE rule needs the text's helper to read on: with the text readable but the helper off, unavailable or unknown (it has not yet followed the text in a state change; its last_changed "
        "is old) the text is not live", not bad, str(bad[:3]))
    # the two timers, exactly
    bad = []
    for flag, helper, limit, inv_on in ((STALL, K["STALLS"], 210, "DEGRADED"), (CORR, K["STUCK"], 300, "UNTRUSTED")):
        tw = world(text)
        tw.put(flag, "on")
        tw.advance(limit - 1)
        a = (tw.state(helper), tw.state(K["INV"]))
        tw.advance(1)
        b = (tw.state(helper), tw.state(K["INV"]))
        if a != ("off", "TRUSTED") or b != ("on", inv_on) or snapshot_problems(tw):
            bad.append(f"{flag}: {a} {b}")
    rec("the two timers at the second: the stall helper is off at 3:29 and on at 3:30 (DEGRADED), the correction helper off at 4:59 and on at 5:00 (UNTRUSTED)", not bad, str(bad[:2]))
    # a stall episode of exactly the required length: four consecutive reads (240 s) trip, three (180 s) do not, whatever the timing jitter of the reads and of the OFF
    bad = []
    for dur, trips in ((120.0, False), (180.0, False), (185.0, False), (209.0, False), (209.9, False), (210.0, True), (211.0, True), (225.0, True), (235.0, True), (240.0, True), (300.0, True)):
        tw = world(text)
        tw.put(STALL, "on")
        tw.advance(dur)
        tw.put(STALL, "off")
        seen_on = any(h[1] == K["STALLS"] and h[2] == "on" for h in tw.w.history)
        seen_deg = any(h[1] == K["INV"] and h[2] == "DEGRADED" for h in tw.w.history)
        if (seen_on, seen_deg) != (trips, trips):
            bad.append(f"{dur}: on {seen_on} degraded {seen_deg}")
    rec("a stall episode that ends just before the delay never trips the helper (209.9 s, three reads of 180 s), one of four reads (235 s, 240 s) and anything from 210 s does: the delay is "
        "strictly below the 240 s that four reads last, so a timing race cannot decide", not bad, str(bad[:3]))


# --- [4] consumers ------------------------------------------------------------------------------------------------------------
def sec_consumers(text, rec):
    values = NAMES + ["unavailable", "unknown", "", "trusted", "None", "TRUSTED ", "ok"]
    tw = world(text)
    bad = []
    for ha in values:
        tw.override(K["HA"], ha)
        for ntp in values:
            tw.override(K["NTP"], ntp)
            for inv in ("TRUSTED", "DEGRADED", "UNKNOWN", "UNTRUSTED", "unavailable", "unknown", ""):
                tw.override(K["INV"], inv)
                want = (o_all(ha, ntp, inv), o_leases(ntp, ha), o_leases(ntp, ha), o_slot(inv), *(c if c in NAMES else "UNKNOWN" for c in (ha, ntp, inv)))
                got = (tw.state(K["ALL"]), tw.state(K["LEASES"]), tw.state(K["SCHED"]), tw.state(K["SLOT"]),
                       tw.attr(K["ALL"], "ha_clock"), tw.attr(K["ALL"], "dongle_ntp"), tw.attr(K["ALL"], "inverter_clock"))
                if got != want:
                    bad.append(f"{ha!r}/{ntp!r}/{inv!r}: {got} != {want}")
    rec(f"the overall state and the three consumers over every per-clock value ({len(values)} x {len(values)} x 7, unreadable ones included): the overall state is the worst "
        "(UNKNOWN never better than DEGRADED, a missing sensor is UNKNOWN); leases and schedules are on only for a TRUSTED dongle NTP and a TRUSTED or DEGRADED HA clock (UNKNOWN, "
        "UNTRUSTED, unavailable, empty or any other text is off); slot edits only for a TRUSTED inverter clock; the overall attributes name each clock's state (UNKNOWN for anything else)", not bad and not tw.errors, str(bad[:2] + tw.errors[:1]))
    for ha, ntp, inv, want in (("TRUSTED", "TRUSTED", "UNKNOWN", "UNKNOWN"), ("DEGRADED", "TRUSTED", "UNKNOWN", "UNKNOWN"), ("TRUSTED", "UNKNOWN", "DEGRADED", "UNKNOWN"),
                               ("UNKNOWN", "UNKNOWN", "UNTRUSTED", "UNTRUSTED"), ("DEGRADED", "DEGRADED", "TRUSTED", "DEGRADED"), ("TRUSTED", "TRUSTED", "TRUSTED", "TRUSTED")):
        tw.override(K["HA"], ha)
        tw.override(K["NTP"], ntp)
        tw.override(K["INV"], inv)
        rec(f"the overall state of ({ha}, {ntp}, {inv}) is {want}", tw.state(K["ALL"]) == want, tw.state(K["ALL"]))
    tw.override(K["HA"], None)
    tw.override(K["NTP"], None)
    tw.override(K["INV"], None)
    rec("releasing the three per-clock sensors returns the real rules (TRUSTED on a healthy world)", derived_problems(tw) == [] and tw.state(K["ALL"]) == "TRUSTED", str(derived_problems(tw)))


# --- [5] differential -----------------------------------------------------------------------------
def sec_differential(text, rec, thorough):
    rng = random.Random(25112026)
    # the HA clock and the dongle NTP over the text, the flag, the age, the skew and whether the text changed since it became readable
    tw = world(text)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    bad, n = [], 0
    kinds = {"time": None, "not_time": ("Waiting for NTP", "NTP time invalid", "abc"), "unreadable": ("unknown", "unavailable", ""), "missing": (None,)}
    syncs = ("on", "off", "unavailable", "unknown", None, "ON", "abc")
    skews = (0, 1, 119, 120, 121, 299, 300, 301, -119, -120, -121, -299, -300, -301, 3600, -3600) if thorough else (0, 120, 121, 300, 301, -121, -301)
    ages = (0, 60, 299, 300, 301, 3600) if thorough else (0, 300, 301)
    not_live = [(s_, a_) for s_ in ((0, 121, 301) if thorough else (0, 301)) for a_ in ((0, 300, 301) if thorough else (0, 301))]
    for sy in syncs:
        tw.put(SYNCED, sy)
        for kind, samples in kinds.items():
            pairs = [(s_, a_, True) for s_ in skews for a_ in ages] + [(s_, a_, False) for s_, a_ in not_live] if kind == "time" else [(0, 0, True), (0, 301, True), (0, 2, True)]
            for skew, age, live in pairs:
                if kind == "time":
                    # a text whose content is `skew` seconds behind Home Assistant's own clock, stamped `age` seconds ago; live: it changed 3600 s after its helper did (else 5 s)
                    tw.put(NTP_TEXT, tw.local_text(tw.w.t + tw.w.clock_offset - age - skew))
                else:
                    tw.put(NTP_TEXT, samples[(skew + age) % len(samples)])
                if kind == "missing":
                    tw.force()
                else:
                    tw.age(NTP_TEXT, age)
                    if kind == "time":
                        tw.age(K["RDN"], age + (3600 if live else 5))
                want_age = None if kind == "missing" else age
                want_ha = o_ha(kind, skew, want_age, live)
                want_ntp = o_ntp(sy, kind, want_age, age + skew, live)
                got = (tw.state(K["HA"]), tw.state(K["NTP"]))
                n += 1
                if got != (want_ha, want_ntp):
                    bad.append(f"sync {sy} {kind} skew {skew} age {age} live {live}: {got} != {(want_ha, want_ntp)}")
            if len(bad) > 3:
                break
        if len(bad) > 3:
            break
    rec(f"the Home Assistant clock and the dongle NTP clock against an independent model over {n} combinations of synced flag (7 values), text (a time, not a time, unreadable, missing), "
        "skew, age and whether the text changed since it became readable", not bad and not snapshot_problems(tw), str(bad[:2]))
    # the inverter clock: one factor at a time, then a seeded random sample
    tw = world(text)
    base = dict(diff="10", failed="0", maxerr="77", synced="on", stall="off", stuck="off", itext=("time", 0), irage=0, live=True)
    diffs = ("-300", "-121", "-120", "-61", "-60", "-1", "0", "10", "60", "61", "119", "120", "121", "300", "3600", "-43200", "unavailable", "unknown", "", "abc", "nan", "inf", "-inf", "1e999", None)
    fails = ("0", "1", "2", "5", "50", "-1", "unavailable", "unknown", "", "abc", "nan", "inf", None)
    maxes = ("0", "77", "119", "120", "121", "500", "1000", "3600", "-5", "unavailable", "unknown", "", "abc", "inf", None)
    flags = ("off", "on", "unavailable", "unknown", "")
    syncs2 = ("on", "off", "unavailable", "unknown", None)
    itexts = (("time", 0), ("time", 299), ("time", 300), ("time", 301), ("time", 7200), ("not_time", 0), ("unreadable", 0), ("missing", 0))
    irages = (0, 300, 599, 600, 601, 3600, 86400, -599, -600, -601, -86400)

    def apply(cfg):
        tw.put(DIFF, cfg["diff"])
        tw.put(FAILED, cfg["failed"])
        tw.put(MAXERR, cfg["maxerr"])
        tw.put(SYNCED, cfg["synced"])
        tw.override(K["STALLS"], cfg["stall"])
        tw.override(K["STUCK"], cfg["stuck"])
        kind, age = cfg["itext"]
        d = readable(cfg["diff"])
        if kind == "time":
            tw.put(INV_TEXT, inv_text(tw, cfg["irage"], d if d is not None else 0.0))
            tw.age(INV_TEXT, age)
            tw.age(K["RDI"], age + (3600 if cfg["live"] else 5))
        elif kind == "not_time":
            tw.put(INV_TEXT, "abc")
            tw.age(INV_TEXT, age)
        elif kind == "unreadable":
            tw.put(INV_TEXT, "unavailable")
            tw.force()
        else:
            tw.put(INV_TEXT, None)
        want = o_inv(cfg["diff"], cfg["failed"], cfg["maxerr"], cfg["stall"], cfg["stuck"], cfg["synced"], kind, None if kind == "missing" else age, cfg["irage"], cfg["live"])
        got = tw.state(K["INV"])
        return got, want

    bad, n = [], 0
    for field, values in (("diff", diffs), ("failed", fails), ("maxerr", maxes), ("stall", flags), ("stuck", flags), ("synced", syncs2), ("itext", itexts), ("irage", irages),
                          ("live", (True, False))):
        for v in values:
            cfg = dict(base)
            cfg[field] = v
            got, want = apply(cfg)
            n += 1
            if got != want or snapshot_problems(tw):
                bad.append(f"{field}={v!r}: {got} != {want} {snapshot_problems(tw)[:1]}")
    rec(f"the inverter clock against an independent model, one input at a time over every value (including unreadable and non-finite ones, a whole hour and half a day, the read age and whether "
        f"the text changed since it became readable): {n} cases", not bad, str(bad[:2]))
    bad = []
    samples = 700 if thorough else 120
    for _ in range(samples):
        cfg = dict(diff=rng.choice(diffs), failed=rng.choice(fails), maxerr=rng.choice(maxes), stall=rng.choice(flags), stuck=rng.choice(flags), synced=rng.choice(syncs2),
                   itext=rng.choice(itexts), irage=rng.choice(irages), live=rng.choice((True, True, False)))
        got, want = apply(cfg)
        if got != want or snapshot_problems(tw):
            bad.append(f"{cfg}: {got} != {want} {snapshot_problems(tw)[:1]}")
            break
    rec(f"the inverter clock against an independent model over {samples} seeded random combinations of its nine inputs", not bad, str(bad[:1]))


# --- [6] totality ---------------------------------------------------------------------------------
def sec_totality(text, rec, thorough):
    garbage = ("", "unknown", "unavailable", "None", "null", "abc", "nan", "NaN", "inf", "-inf", "1e999", "-1e999", "--5", "5 s", "0x10", "1,5", "ON", "On", "true", "1", "0",
               "2026-11-25", "2026-11-25T12:00:00+00:00", "2026-11-25 12:00", "2026-11-25T12:00:00", "2026-11-25 12:00:00.5", "2026-11-25 12:00:00+01:00", " 2026-11-25 12:00:00",
               "2026-11-25 12:00:00\n", "2026-13-45 99:99:99", "2026-02-30 12:00:00", "0000-00-00 00:00:00", "99999999999999999999", "'", "\"", "{{ 1 }}", "{% if %}", "\\", "a" * 255)
    if not thorough:                                     # a mutant: the values that exercise every branch of the readings, not every spelling
        garbage = ("", "unknown", "unavailable", "abc", "nan", "inf", "-inf", "1e999", "ON", "1", "'", "{{ 1 }}", "2026-11-25", "2026-11-25 12:00:00.5", "2026-13-45 99:99:99")
    bad, trusted = [], []
    for eid in sorted(READS):
        for g in garbage:
            tw = world(text, warm=120)
            tw.put(eid, g)
            if eid in (NTP_TEXT, INV_TEXT):
                (tw.h_ntp if eid == NTP_TEXT else tw.h_inv)["on"] = False
            tw.advance(60)
            if tw.errors:
                bad.append(f"{eid}={g[:12]!r}: {tw.errors[0][:90]}")
            if snapshot_problems(tw):
                bad.append(f"{eid}={g[:12]!r}: {snapshot_problems(tw)[:1]}")
    rec(f"{len(READS)} inputs x {len(garbage)} garbage values (empty, text, nan, infinities, huge, quotes, template syntax, 255 characters, other spellings of a date): no template ever fails and the "
        "overall state and consumers stay what the clock states say", not bad, str(bad[:2]))
    # a value that is not a sane reading of an input can never leave the clock that reads it TRUSTED where the value is meaningless
    bad = []
    texts_bad = ("", "unknown", "unavailable", "abc", "2026-11-25", "2026-11-25 12:00", "2026-11-25T12:00:00", "2026-11-25 12:00:00.5", "2026-11-25 12:00:00+01:00", " 2026-11-25 12:00:00")
    for eid, values, keys in ((SYNCED, ("", "unknown", "unavailable", "ON", "abc", "true", "1"), ("NTP",)), (DIFF, ("", "unknown", "unavailable", "abc", "nan", "inf", "-inf", "1e999", "5 s"), ("INV",)),
                              (FAILED, ("", "unknown", "unavailable", "abc", "nan", "inf", "-1"), ("INV",)), (MAXERR, ("", "unknown", "unavailable", "abc", "nan", "inf", "-1"), ("INV",)),
                              (STALL, ("", "unknown", "unavailable", "ON", "abc"), ("INV",)), (CORR, ("", "unknown", "unavailable", "ON", "abc"), ("INV",)),
                              (NTP_TEXT, texts_bad, ("NTP", "HA")), (INV_TEXT, texts_bad, ("INV",))):
        for g in values:
            tw = world(text, warm=120)
            tw.put(eid, g)
            if eid in (NTP_TEXT, INV_TEXT):
                (tw.h_ntp if eid == NTP_TEXT else tw.h_inv)["on"] = False
            tw.advance(60)
            if any(tw.state(K[k]) == "TRUSTED" for k in keys) or tw.state(K["ALL"]) == "TRUSTED":
                bad.append(f"{eid}={g!r} -> {[tw.state(K[k]) for k in keys]}")
    rec("an input that is not a sane reading (unreadable, not a number, not finite, negative where a counter, a flag that is neither on nor off, a text that is not exactly YYYY-MM-DD HH:MM:SS) never "
        "leaves a TRUSTED clock or a TRUSTED overall state", not bad, str(bad[:3]))


# --- [7] no writes ------------------------------------------------------------------------------------------------------------
def sec_nowrite(text, rec):
    tw = world(text)
    tw.put(STALL, "on")
    tw.put(CORR, "on")
    tw.advance(900)
    tw.put(SYNCED, "off")
    tw.advance(120)
    written = {eid for _t, eid, _s in tw.w.history}
    inputs = READS
    rec("the model saw no service call and no notification, and every entity written was one of the package's eleven or an input the test set (the package writes nothing it does not own)",
        tw.w.service_log == [] and tw.w.notifications == {} and tw.w.notification_log == [] and written <= (OWN | inputs), str(sorted(written - OWN - inputs)[:3]))


# ===========================================================================================================================
# run the battery on the package as written, in report mode
# ===========================================================================================================================
print("[1] the model of Home Assistant's template entities, [2] scenarios, [3] boundaries, [4] consumers, [5] differential, [6] totality, [7] no writes")
bad_pkg = battery(PKG_TEXT, mode="report")
check("the full battery holds on the package as written", bad_pkg == [] and not FAILURES, str(bad_pkg[:1] + FAILURES[:1]))


# ===========================================================================================================================
# [8] mutation
# ===========================================================================================================================
print("[8] mutation: in-memory mutants of the package are each caught")


def occurrences(text: str, anchor: str) -> int:
    return text.count(anchor)


def nth_replace(text: str, old: str, new: str, n: int) -> str:
    idx = -1
    for _ in range(n + 1):
        idx = text.index(old, idx + 1)
    return text[:idx] + new + text[idx + len(old):]


STATE_MAX = "[[rd, rf, rm, rs, rc, ry, ra, rv, rl] | max]"
NTP_MAX = "{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3, r4, r5] | max] }}"
MUT = [
    # ---- the Home Assistant clock
    ("HA clock: TRUSTED limit 121 s", "(skew | abs) <= 120", ["(skew | abs) <= 121"]),
    ("HA clock: TRUSTED limit 119 s", "(skew | abs) <= 120", ["(skew | abs) <= 119"]),
    ("HA clock: TRUSTED limit exclusive (< 120)", "(skew | abs) <= 120", ["(skew | abs) < 120"]),
    ("HA clock: TRUSTED limit read without the sign (a clock that is behind passes)", "(skew | abs) <= 120", ["skew <= 120"]),
    ("HA clock: DEGRADED limit 301 s", "(skew | abs) <= 300", ["(skew | abs) <= 301"]),
    ("HA clock: DEGRADED limit 299 s", "(skew | abs) <= 300", ["(skew | abs) <= 299"]),
    ("HA clock: DEGRADED limit exclusive (< 300)", "(skew | abs) <= 300", ["(skew | abs) < 300"]),
    ("HA clock: DEGRADED limit read without the sign", "(skew | abs) <= 300", ["skew <= 300"]),
    ("HA clock: the freshness of the reference text is not required", "skew is none or age is none or age > 300", ["skew is none or age is none"]),
    ("HA clock: a text older than 301 s still serves as the reference", "skew is none or age is none or age > 300", ["skew is none or age is none or age > 301"]),
    ("HA clock: a text older than 299 s no longer serves", "skew is none or age is none or age > 300", ["skew is none or age is none or age > 299"]),
    ("HA clock: an unreadable reference is TRUSTED", "{{ 'UNKNOWN' if (skew is none", ["{{ 'TRUSTED' if (skew is none"]),
    ("HA clock: an unreadable reference is UNTRUSTED (an accusation of Home Assistant)", "{{ 'UNKNOWN' if (skew is none", ["{{ 'UNTRUSTED' if (skew is none"]),
    ("HA clock: a text that is not a time reads as 0 (the R9 default) and the clock is compared with 1970", "{%- set ref = as_timestamp(dt, none) if dt is not none else none -%}",
     ["{%- set ref = as_timestamp(dt, 0) if dt is not none else 0 -%}"]),
    ("HA clock: a text is handed to as_timestamp as it is (Home Assistant's own parser also reads a date alone, no seconds, a T, fractions and an offset)",
     "{%- set ref = as_timestamp(dt, none) if dt is not none else none -%}", ["{%- set ref = as_timestamp(txt, none) if txt not in ['unknown', 'unavailable', ''] else none -%}"]),
    ("a text is read with another format than the firmware's", "strptime(txt, '%Y-%m-%d %H:%M:%S', none)", ["strptime(txt, '%Y-%m-%d %H:%M', none)"]),
    ("a text that does not match the format reads as 0, not as none", "strptime(txt, '%Y-%m-%d %H:%M:%S', none)", ["strptime(txt, '%Y-%m-%d %H:%M:%S', 0)"]),
    ("HA clock: the LIVE condition is not required", "skew is none or age is none or age > 300 or not live)", ["skew is none or age is none or age > 300)"], (0,)),
    ("HA clock: the skew is not rounded to whole seconds", "((as_timestamp(o.last_changed) - ref) | round(0))", ["(as_timestamp(o.last_changed) - ref)"]),
    ("HA clock: the skew is taken against now() (it carries the age of the text)", "((as_timestamp(o.last_changed) - ref) | round(0))", ["((as_timestamp(now()) - ref) | round(0))"]),
    ("HA clock: the shown skew has the wrong sign (the verdict reads |skew|, so only the shown number and the reasons can tell)", "((as_timestamp(o.last_changed) - ref) | round(0))",
     ["((ref - as_timestamp(o.last_changed)) | round(0))"], (1, 2)),
    ("HA clock: the age is read from the wrong end (text newer than now)", "as_timestamp(now()) - as_timestamp(o.last_changed)", ["as_timestamp(o.last_changed) - as_timestamp(now())"]),
    # ---- the dongle NTP
    ("dongle NTP: a flag that is off is not UNTRUSTED", "{%- set r1 = 0 if sy == 'on' else (3 if sy == 'off' else 2) -%}", ["{%- set r1 = 0 if sy == 'on' else (2 if sy == 'off' else 2) -%}"]),
    ("dongle NTP: an unreadable flag is TRUSTED", "{%- set r1 = 0 if sy == 'on' else (3 if sy == 'off' else 2) -%}", ["{%- set r1 = 0 if sy != 'off' else 3 -%}", "{%- set r1 = 0 if sy == 'on' else (3 if sy == 'off' else 0) -%}"]),
    ("dongle NTP: an unreadable text is TRUSTED", "{%- set r2 = 2 if txt in ['unknown', 'unavailable', ''] else (3 if ref is none else 0) -%}", ["{%- set r2 = 0 if txt in ['unknown', 'unavailable', ''] else (3 if ref is none else 0) -%}"]),
    ("dongle NTP: a text that is not a time is UNKNOWN, not UNTRUSTED", "{%- set r2 = 2 if txt in ['unknown', 'unavailable', ''] else (3 if ref is none else 0) -%}", ["{%- set r2 = 2 if txt in ['unknown', 'unavailable', ''] else (2 if ref is none else 0) -%}"]),
    ("dongle NTP: a text that is not a time is TRUSTED", "{%- set r2 = 2 if txt in ['unknown', 'unavailable', ''] else (3 if ref is none else 0) -%}", ["{%- set r2 = 2 if txt in ['unknown', 'unavailable', ''] else 0 -%}"]),
    ("dongle NTP: the freshness is not required", "{%- set r3 = 0 if r2 > 0 else (2 if age is none else (3 if age > 300 else 0)) -%}", ["{%- set r3 = 0 -%}"]),
    ("dongle NTP: the freshness limit is 301 s", "{%- set r3 = 0 if r2 > 0 else (2 if age is none else (3 if age > 300 else 0)) -%}", ["{%- set r3 = 0 if r2 > 0 else (2 if age is none else (3 if age > 301 else 0)) -%}"]),
    ("dongle NTP: the freshness limit is 299 s", "{%- set r3 = 0 if r2 > 0 else (2 if age is none else (3 if age > 300 else 0)) -%}", ["{%- set r3 = 0 if r2 > 0 else (2 if age is none else (3 if age > 299 else 0)) -%}"]),
    ("dongle NTP: a stale text is UNKNOWN, not UNTRUSTED", "{%- set r3 = 0 if r2 > 0 else (2 if age is none else (3 if age > 300 else 0)) -%}", ["{%- set r3 = 0 if r2 > 0 else (2 if age is none else (2 if age > 300 else 0)) -%}"]),
    ("dongle NTP: the synced flag is not read", NTP_MAX, ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r2, r3, r4, r5] | max] }}"]),
    ("dongle NTP: the text is not read", NTP_MAX, ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r3, r4, r5] | max] }}"]),
    ("dongle NTP: the age is not read", NTP_MAX, ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r4, r5] | max] }}"]),
    ("dongle NTP: the value against Home Assistant's clock is not read", NTP_MAX, ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3, r5] | max] }}"]),
    ("dongle NTP: the LIVE condition is not read", NTP_MAX, ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3, r4] | max] }}"]),
    ("dongle NTP: the best of its rules, not the worst", NTP_MAX, [NTP_MAX.replace("| max]", "| min]")]),
    ("dongle NTP: a text 601 s from Home Assistant's clock is still fresh", "(vage | abs) > 600", ["(vage | abs) > 601"]),
    ("dongle NTP: a text 600 s from Home Assistant's clock is stale", "(vage | abs) > 600", ["(vage | abs) >= 600"]),
    ("dongle NTP: a text 599 s from Home Assistant's clock is stale", "(vage | abs) > 600", ["(vage | abs) > 599"]),
    ("dongle NTP: only a text that is behind Home Assistant's clock is stale (read without the sign)", "(vage | abs) > 600", ["vage > 600"]),
    ("dongle NTP: only a text that is ahead of Home Assistant's clock is stale (read without the sign)", "(vage | abs) > 600", ["vage < -600"]),
    ("dongle NTP: a text beyond the value bound is UNTRUSTED, not UNKNOWN", "{%- set r4 = 0 if (r2 > 0 or r3 > 0 or txt in ['unknown', 'unavailable', '']) else (2 if (vage is none or (vage | abs) > 600) else 0) -%}",
     ["{%- set r4 = 0 if (r2 > 0 or r3 > 0 or txt in ['unknown', 'unavailable', '']) else (3 if (vage is none or (vage | abs) > 600) else 0) -%}"]),
    ("dongle NTP: a text beyond the value bound is not stale", "{%- set r4 = 0 if (r2 > 0 or r3 > 0 or txt in ['unknown', 'unavailable', '']) else (2 if (vage is none or (vage | abs) > 600) else 0) -%}", ["{%- set r4 = 0 -%}"]),
    ("dongle NTP: a text that has not changed since it became readable is TRUSTED", "{%- set r5 = 0 if (r2 > 0 or r3 > 0 or txt in ['unknown', 'unavailable', '']) else (0 if live else 2) -%}", ["{%- set r5 = 0 -%}"]),
    ("dongle NTP: a text that has not changed since it became readable is UNTRUSTED, not UNKNOWN", "{%- set r5 = 0 if (r2 > 0 or r3 > 0 or txt in ['unknown', 'unavailable', '']) else (0 if live else 2) -%}",
     ["{%- set r5 = 0 if (r2 > 0 or r3 > 0 or txt in ['unknown', 'unavailable', '']) else (0 if live else 3) -%}"]),
    ("dongle NTP: the value is the text's own age, not its distance from Home Assistant's clock (the arrival is used twice)", "{%- set vage = ((as_timestamp(now()) - ref) | round(0)) if ref is not none else none -%}",
     ["{%- set vage = age -%}"]),
    # ---- the inverter clock
    ("inverter clock: UNTRUSTED above 121 s", "(d | abs) > 120", ["(d | abs) > 121"]),
    ("inverter clock: UNTRUSTED from 120 s", "(d | abs) > 120", ["(d | abs) >= 120"]),
    ("inverter clock: DEGRADED above 61 s", "(d | abs) > 60", ["(d | abs) > 61"]),
    ("inverter clock: DEGRADED from 60 s", "(d | abs) > 60", ["(d | abs) >= 60"]),
    ("inverter clock: DEGRADED above 59 s", "(d | abs) > 60", ["(d | abs) > 59"]),
    ("inverter clock: the 120 s limit is read without the sign", "(3 if (d | abs) > 120", ["(3 if d > 120"]),
    ("inverter clock: the 60 s limit is read without the sign", "(1 if (d | abs) > 60", ["(1 if d > 60"]),
    ("inverter clock: an unreadable difference is TRUSTED", "{%- set rd = 2 if d is none else", ["{%- set rd = 0 if d is none else"]),
    ("inverter clock: a difference beyond 120 s is only DEGRADED", "(3 if (d | abs) > 120 else (1 if (d | abs) > 60 else 0))", ["(1 if (d | abs) > 120 else (1 if (d | abs) > 60 else 0))"]),
    ("inverter clock: a failed correction is not counted", "(1 if f > 0 else 0)", ["(0 if f > 0 else 0)"]),
    ("inverter clock: one failed correction is forgiven (> 1)", "(1 if f > 0 else 0)", ["(1 if f > 1 else 0)"]),
    ("inverter clock: an unreadable failure counter is TRUSTED", "{%- set rf = 2 if f is none else", ["{%- set rf = 0 if f is none else"]),
    ("inverter clock: a failure counter that is negative is read", "f >= 0 and f < 1000000000", ["f < 1000000000"]),
    ("inverter clock: a maximum error of 121 s is forgiven", "(1 if m > 120 else 0)", ["(1 if m > 121 else 0)"]),
    ("inverter clock: a maximum error of exactly 120 s degrades", "(1 if m > 120 else 0)", ["(1 if m >= 120 else 0)"]),
    ("inverter clock: the maximum error is not counted", "(1 if m > 120 else 0)", ["(0 if m > 120 else 0)"]),
    ("inverter clock: an unreadable maximum error is TRUSTED", "{%- set rm = 2 if m is none else", ["{%- set rm = 0 if m is none else"]),
    ("inverter clock: a sustained stall is not counted", "{%- set rs = 0 if st == 'off' else (1 if st == 'on' else 2) -%}", ["{%- set rs = 0 if st == 'off' else (0 if st == 'on' else 2) -%}"]),
    ("inverter clock: a sustained stall is UNTRUSTED", "{%- set rs = 0 if st == 'off' else (1 if st == 'on' else 2) -%}", ["{%- set rs = 0 if st == 'off' else (3 if st == 'on' else 2) -%}"]),
    ("inverter clock: an unreadable stall helper is TRUSTED", "{%- set rs = 0 if st == 'off' else (1 if st == 'on' else 2) -%}", ["{%- set rs = 0 if st != 'on' else 1 -%}"]),
    ("inverter clock: a stuck correction is only DEGRADED", "{%- set rc = 0 if cs == 'off' else (3 if cs == 'on' else 2) -%}", ["{%- set rc = 0 if cs == 'off' else (1 if cs == 'on' else 2) -%}"]),
    ("inverter clock: a stuck correction is not counted", "{%- set rc = 0 if cs == 'off' else (3 if cs == 'on' else 2) -%}", ["{%- set rc = 0 if cs == 'off' else (0 if cs == 'on' else 2) -%}"]),
    ("inverter clock: an unreadable correction helper is TRUSTED", "{%- set rc = 0 if cs == 'off' else (3 if cs == 'on' else 2) -%}", ["{%- set rc = 0 if cs != 'on' else 3 -%}"]),
    ("inverter clock: the synced flag is not required", "{%- set ry = 0 if sy == 'on' else 2 -%}", ["{%- set ry = 0 -%}"]),
    ("inverter clock: only a flag that is off (not an unreadable one) withdraws trust", "{%- set ry = 0 if sy == 'on' else 2 -%}", ["{%- set ry = 0 if sy != 'off' else 2 -%}"]),
    ("inverter clock: the inverter time text's freshness is not required", "{%- set ra = 2 if (age is none or txt in ['unknown', 'unavailable', '']) else (2 if age > 300 else 0) -%}", ["{%- set ra = 2 if (age is none or txt in ['unknown', 'unavailable', '']) else 0 -%}"]),
    ("inverter clock: an unreadable inverter time text is TRUSTED", "{%- set ra = 2 if (age is none or txt in ['unknown', 'unavailable', '']) else (2 if age > 300 else 0) -%}", ["{%- set ra = 2 if age is none else (2 if age > 300 else 0) -%}"]),
    ("inverter clock: a stale inverter time text limit of 301 s", "{%- set ra = 2 if (age is none or txt in ['unknown', 'unavailable', '']) else (2 if age > 300 else 0) -%}", ["{%- set ra = 2 if (age is none or txt in ['unknown', 'unavailable', '']) else (2 if age > 301 else 0) -%}"]),
    ("inverter clock: a stale inverter time text is UNTRUSTED", "{%- set ra = 2 if (age is none or txt in ['unknown', 'unavailable', '']) else (2 if age > 300 else 0) -%}", ["{%- set ra = 2 if (age is none or txt in ['unknown', 'unavailable', '']) else (3 if age > 300 else 0) -%}"]),
    ("inverter clock: the best of its rules, not the worst", STATE_MAX, [STATE_MAX.replace("| max]", "| min]")]),
    ("inverter clock: the difference is not read", STATE_MAX, ["[[rf, rm, rs, rc, ry, ra, rv, rl] | max]"]),
    ("inverter clock: the failure counter is not read", STATE_MAX, ["[[rd, rm, rs, rc, ry, ra, rv, rl] | max]"]),
    ("inverter clock: the maximum error is not read", STATE_MAX, ["[[rd, rf, rs, rc, ry, ra, rv, rl] | max]"]),
    ("inverter clock: the stall helper is not read", STATE_MAX, ["[[rd, rf, rm, rc, ry, ra, rv, rl] | max]"]),
    ("inverter clock: the correction helper is not read", STATE_MAX, ["[[rd, rf, rm, rs, ry, ra, rv, rl] | max]"]),
    ("inverter clock: the synced flag is not read", STATE_MAX, ["[[rd, rf, rm, rs, rc, ra, rv, rl] | max]"]),
    ("inverter clock: the text age is not read", STATE_MAX, ["[[rd, rf, rm, rs, rc, ry, rv, rl] | max]"]),
    ("inverter clock: the value age is not read", STATE_MAX, ["[[rd, rf, rm, rs, rc, ry, ra, rl] | max]"]),
    ("inverter clock: the LIVE condition is not read", STATE_MAX, ["[[rd, rf, rm, rs, rc, ry, ra, rv] | max]"]),
    ("inverter clock: a difference that is not finite still counts as read", "and (d | abs) < 1000000000", [""]),
    ("inverter clock: a failure counter that is not finite still counts as read", "and f < 1000000000", [""]),
    ("inverter clock: a maximum error that is not finite still counts as read", "and m < 1000000000", [""]),
    ("inverter clock: a difference that is not a number counts as read", "(d is number and (d | abs) < 1000000000)", ["((d | abs) < 1000000000)"]),
    ("inverter clock: a failure counter that is not a number counts as read", "(f is number and f >= 0", ["(f >= 0"]),
    ("inverter clock: a maximum error that is not a number counts as read", "(m is number and m >= 0", ["(m >= 0"]),
    # ---- the two debounce helpers
    ("stall helper: no delay (a 60 s episode trips it)", '        delay_on: "00:03:30"\n', [""]),
    ("stall helper: a 3 minute delay (three reads trip it)", 'delay_on: "00:03:30"', ['delay_on: "00:03:00"']),
    ("stall helper: a 3 minute 29 s delay", 'delay_on: "00:03:30"', ['delay_on: "00:03:29"']),
    ("stall helper: a 3 minute 31 s delay", 'delay_on: "00:03:30"', ['delay_on: "00:03:31"']),
    ("stall helper: a 4 minute delay (a four-read episode of 240 s trips only by a timing race)", 'delay_on: "00:03:30"', ['delay_on: "00:04:00"']),
    ("stall helper: a 5 minute delay", 'delay_on: "00:03:30"', ['delay_on: "00:05:00"']),
    ("stall helper: the old 10 minute delay (an episode of exactly 10 minutes trips it only by a timing race)", 'delay_on: "00:03:30"', ['delay_on: "00:10:00"']),
    ("correction helper: no delay", '        delay_on: "00:05:00"\n', [""]),
    ("correction helper: a 4 minute delay", 'delay_on: "00:05:00"', ['delay_on: "00:04:00"']),
    ("correction helper: a 6 minute delay", 'delay_on: "00:05:00"', ['delay_on: "00:06:00"']),
    ("stall helper: an unreadable flag is a quiet off (no availability)", "        availability: \"{{ states('binary_sensor.ecco_clock_dongle_rtc_stall_detected') in ['on', 'off'] }}\"\n", [""]),
    ("correction helper: an unreadable flag is a quiet off (no availability)", "        availability: \"{{ states('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress') in ['on', 'off'] }}\"\n", [""]),
    ("stall helper: availability accepts any text", "states('binary_sensor.ecco_clock_dongle_rtc_stall_detected') in ['on', 'off']", ["states('binary_sensor.ecco_clock_dongle_rtc_stall_detected') != 'unavailable'"]),
    ("stall helper: the flag is inverted", "is_state('binary_sensor.ecco_clock_dongle_rtc_stall_detected', 'on')", ["is_state('binary_sensor.ecco_clock_dongle_rtc_stall_detected', 'off')"]),
    ("correction helper: the flag is inverted", "is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'on')", ["is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'off')"]),
    ("stall helper reads the correction flag", "is_state('binary_sensor.ecco_clock_dongle_rtc_stall_detected', 'on')", ["is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'on')"]),
    # ---- the overall state
    ("overall: UNKNOWN ranks best (below TRUSTED)", "{'TRUSTED': 0, 'DEGRADED': 1, 'UNKNOWN': 2, 'UNTRUSTED': 3}", ["{'TRUSTED': 1, 'DEGRADED': 2, 'UNKNOWN': 0, 'UNTRUSTED': 3}"]),
    ("overall: UNKNOWN ties with DEGRADED", "{'TRUSTED': 0, 'DEGRADED': 1, 'UNKNOWN': 2, 'UNTRUSTED': 3}", ["{'TRUSTED': 0, 'DEGRADED': 1, 'UNKNOWN': 1, 'UNTRUSTED': 3}"]),
    ("overall: UNKNOWN reads better than DEGRADED", "{'TRUSTED': 0, 'DEGRADED': 1, 'UNKNOWN': 2, 'UNTRUSTED': 3}", ["{'TRUSTED': 0, 'DEGRADED': 2, 'UNKNOWN': 1, 'UNTRUSTED': 3}"]),
    ("overall: UNKNOWN beats UNTRUSTED", "{'TRUSTED': 0, 'DEGRADED': 1, 'UNKNOWN': 2, 'UNTRUSTED': 3}", ["{'TRUSTED': 0, 'DEGRADED': 1, 'UNKNOWN': 3, 'UNTRUSTED': 2}"]),
    ("overall: the best of the three, not the worst", "[rk[a] if a in rk else 2, rk[b] if b in rk else 2, rk[c] if c in rk else 2] | max]", ["[rk[a] if a in rk else 2, rk[b] if b in rk else 2, rk[c] if c in rk else 2] | min]"]),
    ("overall: a missing per-clock sensor is TRUSTED", "rk[a] if a in rk else 2", ["rk[a] if a in rk else 0"]),
    ("overall: a missing dongle NTP sensor is TRUSTED", "rk[b] if b in rk else 2", ["rk[b] if b in rk else 0"]),
    ("overall: a missing inverter sensor is TRUSTED", "rk[c] if c in rk else 2", ["rk[c] if c in rk else 0"]),
    ("overall: a missing HA clock sensor is DEGRADED only", "rk[a] if a in rk else 2", ["rk[a] if a in rk else 1"]),
    ("overall: the HA clock is not read", "[rk[a] if a in rk else 2, rk[b] if b in rk else 2, rk[c] if c in rk else 2] | max]", ["[rk[b] if b in rk else 2, rk[c] if c in rk else 2] | max]"]),
    ("overall: the dongle NTP is not read", "[rk[a] if a in rk else 2, rk[b] if b in rk else 2, rk[c] if c in rk else 2] | max]", ["[rk[a] if a in rk else 2, rk[c] if c in rk else 2] | max]"]),
    ("overall: the inverter clock is not read", "[rk[a] if a in rk else 2, rk[b] if b in rk else 2, rk[c] if c in rk else 2] | max]", ["[rk[a] if a in rk else 2, rk[b] if b in rk else 2] | max]"]),
    ("overall: the skew attribute is read from the wrong attribute", "state_attr('sensor.ecco_time_trust_ha_clock', 'skew_s')", ["state_attr('sensor.ecco_time_trust_ha_clock', 'text_age_s')"]),
    ("overall: the difference attribute is read from the wrong sensor", "state_attr('sensor.ecco_time_trust_inverter_clock', 'difference_s')", ["state_attr('sensor.ecco_time_trust_ha_clock', 'skew_s')"]),
    ("overall: the HA clock attribute reads the dongle NTP sensor", "{%- set a = states('sensor.ecco_time_trust_ha_clock') -%}\n            {{ a if a in", ["{%- set a = states('sensor.ecco_time_trust_dongle_ntp') -%}\n            {{ a if a in"]),
    ("overall: an unreadable clock is not UNKNOWN in the attributes", "{{ a if a in ['TRUSTED', 'DEGRADED', 'UNTRUSTED', 'UNKNOWN'] else 'UNKNOWN' }}", ["{{ a }}"]),
    ("overall: the reasons name no clock", "{%- set ns.r = ns.r + [label ~ ': ' ~", ["{%- set ns.r = ns.r + ['' ~"]),
    ("overall: the reasons say all TRUSTED while one is not", "{{ ns.r if (ns.r | length) > 0 else ['TRUSTED: all three clocks are TRUSTED'] }}", ["{{ ['TRUSTED: all three clocks are TRUSTED'] }}"]),
    ("overall: the reasons skip an UNKNOWN clock", "{%- elif s in ['DEGRADED', 'UNTRUSTED', 'UNKNOWN'] -%}", ["{%- elif s in ['DEGRADED', 'UNTRUSTED'] -%}"]),
    # ---- the consumers
    ("leases: the dongle NTP condition is dropped", "{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}",
     ["{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}"]),
    ("leases: the HA clock condition is dropped", "{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}",
     ["{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}"]),
    ("leases: 'and' is 'or'", "{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}",
     ["{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') or states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}"]),
    ("leases: the HA clock must not be UNTRUSTED (an unreadable or unknown clock passes)", "states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}",
     ["states('sensor.ecco_time_trust_ha_clock') != 'UNTRUSTED' }}"]),
    ("leases: a DEGRADED HA clock is not enough", "{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}",
     ["{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED'] }}"]),
    ("leases: an UNKNOWN HA clock passes", "{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}",
     ["{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED', 'UNKNOWN'] }}"]),
    ("leases: a DEGRADED dongle NTP passes", "{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}",
     ["{{ states('sensor.ecco_time_trust_dongle_ntp') in ['TRUSTED', 'DEGRADED'] and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}"]),
    ("schedules: the dongle NTP condition is dropped", "{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] and is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}",
     ["{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}"]),
    ("schedules: the HA clock condition is dropped", "{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] and is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}",
     ["{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}"]),
    ("schedules: 'and' is 'or'", "{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] and is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}",
     ["{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] or is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}"]),
    ("schedules: only a TRUSTED HA clock", "{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] and is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}",
     ["{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED'] and is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}"]),
    ("schedules: the HA clock must not be UNTRUSTED", "{{ states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] and is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}",
     ["{{ states('sensor.ecco_time_trust_ha_clock') != 'UNTRUSTED' and is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}"]),
    ("slot edits: a DEGRADED inverter clock is enough", "{{ is_state('sensor.ecco_time_trust_inverter_clock', 'TRUSTED') }}", ["{{ states('sensor.ecco_time_trust_inverter_clock') in ['TRUSTED', 'DEGRADED'] }}"]),
    ("slot edits: the inverter clock must not be UNTRUSTED", "{{ is_state('sensor.ecco_time_trust_inverter_clock', 'TRUSTED') }}", ["{{ states('sensor.ecco_time_trust_inverter_clock') != 'UNTRUSTED' }}"]),
    ("slot edits: read from the dongle NTP clock", "{{ is_state('sensor.ecco_time_trust_inverter_clock', 'TRUSTED') }}", ["{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') }}"]),
    ("slot edits: read from the overall state", "{{ is_state('sensor.ecco_time_trust_inverter_clock', 'TRUSTED') }}", ["{{ is_state('sensor.ecco_time_trust', 'TRUSTED') }}"]),
    ("slot edits: always on", "{{ is_state('sensor.ecco_time_trust_inverter_clock', 'TRUSTED') }}", ["{{ true }}"]),
    ("leases: always on", "{{ is_state('sensor.ecco_time_trust_dongle_ntp', 'TRUSTED') and states('sensor.ecco_time_trust_ha_clock') in ['TRUSTED', 'DEGRADED'] }}", ["{{ true }}"]),
    # ---- the reasons attribute (it must say what the state says)
    ("the LIVE gap is 11 s", "> 10) if (o is not none and mk is not none and mk.state == 'on') else false", ["> 11) if (o is not none and mk is not none and mk.state == 'on') else false"]),
    ("the LIVE gap is 9 s", "> 10) if (o is not none and mk is not none and mk.state == 'on') else false", ["> 9) if (o is not none and mk is not none and mk.state == 'on') else false"]),
    ("the LIVE gap counts from 10 s", "> 10) if (o is not none and mk is not none and mk.state == 'on') else false", [">= 10) if (o is not none and mk is not none and mk.state == 'on') else false"]),
    ("a change at the same instant as the helper is live (gap > 0)", "> 10) if (o is not none and mk is not none and mk.state == 'on') else false", ["> 0) if (o is not none and mk is not none and mk.state == 'on') else false"]),
    ("the LIVE gap is measured the wrong way round", "(as_timestamp(o.last_changed) - as_timestamp(mk.last_changed)) > 10", ["(as_timestamp(mk.last_changed) - as_timestamp(o.last_changed)) > 10"]),
    ("the LIVE helper need not read on", "and mk.state == 'on') else false", [") else false"]),
    ("a missing LIVE helper counts as live", "> 10) if (o is not none and mk is not none and mk.state == 'on') else false -%}", ["> 10) if (o is not none and mk is not none and mk.state == 'on') else true -%}"]),
    ("the NTP text's value age is not rounded", "{%- set vage = ((as_timestamp(now()) - ref) | round(0)) if ref is not none else none -%}",
     ["{%- set vage = (as_timestamp(now()) - ref) if ref is not none else none -%}"]),
    ("the NTP text's LIVE helper reads the inverter text", "{%- set mk = states['binary_sensor.ecco_time_trust_ntp_text_readable'] -%}", ["{%- set mk = states['binary_sensor.ecco_time_trust_inverter_text_readable'] -%}"]),
    ("the inverter text's LIVE helper reads the NTP text", "{%- set mk = states['binary_sensor.ecco_time_trust_inverter_text_readable'] -%}", ["{%- set mk = states['binary_sensor.ecco_time_trust_ntp_text_readable'] -%}"]),
    ("the NTP text's helper counts an empty text as readable", "state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', 'unavailable'] }}\""]),
    ("the NTP text's helper counts an unknown text as readable", "state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unavailable', ''] }}\""]),
    ("the NTP text's helper counts an unavailable text as readable", "state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', ''] }}\""]),
    ("the NTP text's helper is always on", "state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', 'unavailable', ''] }}\"", ["state: \"{{ true }}\""]),
    ("the inverter text's helper counts an empty text as readable", "state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', 'unavailable'] }}\""]),
    ("the inverter text's helper counts an unknown text as readable", "state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unavailable', ''] }}\""]),
    ("the inverter text's helper counts an unavailable text as readable", "state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', ''] }}\""]),
    ("the inverter text's helper is always on", "state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', 'unavailable', ''] }}\"", ["state: \"{{ true }}\""]),
    ("the NTP text's helper reads the inverter text", "state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', 'unavailable', ''] }}\""]),
    ("the inverter text's helper reads the NTP text", "state: \"{{ states('sensor.ecco_clock_dongle_inverter_time') not in ['unknown', 'unavailable', ''] }}\"",
     ["state: \"{{ states('sensor.ecco_clock_dongle_ntp_time') not in ['unknown', 'unavailable', ''] }}\""]),
    # ---- the inverter read age (value) and its LIVE rule
    ("inverter clock: the read age is the text PLUS the difference", "(as_timestamp(now()) - (ia - d)) | round(0)", ["(as_timestamp(now()) - (ia + d)) | round(0)"]),
    ("inverter clock: the read age ignores the difference", "(as_timestamp(now()) - (ia - d)) | round(0)", ["(as_timestamp(now()) - ia) | round(0)"]),
    ("inverter clock: the read age is not rounded", "(as_timestamp(now()) - (ia - d)) | round(0)", ["(as_timestamp(now()) - (ia - d))"], (0,)),
    ("inverter clock: a read 601 s old is still fresh", "(rage | abs) > 600", ["(rage | abs) > 601"]),
    ("inverter clock: a read 600 s old is stale", "(rage | abs) > 600", ["(rage | abs) >= 600"]),
    ("inverter clock: a read 599 s old is stale", "(rage | abs) > 600", ["(rage | abs) > 599"]),
    ("inverter clock: only a read that is old is stale (read without the sign)", "(rage | abs) > 600", ["rage > 600"]),
    ("inverter clock: only a read from the future is stale (read without the sign)", "(rage | abs) > 600", ["rage < -600"]),
    ("inverter clock: a text that is not a time reads as fresh", "{%- set rv = 0 if (ra > 0 or d is none or txt in ['unknown', 'unavailable', '']) else (2 if (rage is none or (rage | abs) > 600) else 0) -%}",
     ["{%- set rv = 0 if (ra > 0 or d is none or txt in ['unknown', 'unavailable', '']) else (2 if (rage is not none and (rage | abs) > 600) else 0) -%}"]),
    ("inverter clock: a read beyond the value bound is UNTRUSTED, not UNKNOWN", "{%- set rv = 0 if (ra > 0 or d is none or txt in ['unknown', 'unavailable', '']) else (2 if (rage is none or (rage | abs) > 600) else 0) -%}",
     ["{%- set rv = 0 if (ra > 0 or d is none or txt in ['unknown', 'unavailable', '']) else (3 if (rage is none or (rage | abs) > 600) else 0) -%}"]),
    ("inverter clock: the value bound is not applied", "{%- set rv = 0 if (ra > 0 or d is none or txt in ['unknown', 'unavailable', '']) else (2 if (rage is none or (rage | abs) > 600) else 0) -%}", ["{%- set rv = 0 -%}"]),
    ("inverter clock: a text that has not changed since it became readable is TRUSTED", "{%- set rl = 0 if (ra > 0 or txt in ['unknown', 'unavailable', '']) else (0 if live else 2) -%}", ["{%- set rl = 0 -%}"]),
    ("inverter clock: a text that has not changed since it became readable is UNTRUSTED, not UNKNOWN", "{%- set rl = 0 if (ra > 0 or txt in ['unknown', 'unavailable', '']) else (0 if live else 2) -%}",
     ["{%- set rl = 0 if (ra > 0 or txt in ['unknown', 'unavailable', '']) else (0 if live else 3) -%}"]),
    ("inverter clock: the read age is taken from the NTP text's helper", "{%- set mk = states['binary_sensor.ecco_time_trust_inverter_text_readable'] -%}",
     ["{%- set mk = states['binary_sensor.ecco_time_trust_ntp_text_readable'] -%}"]),
    # ---- the reviewer's mutants M1 to M7 and M11 (a whole hour, a large error, five failures, a day of skew, the rounding, the empty text, a stuck correction with the stall flag on)
    ("M1 inverter: a whole-hour difference (the clock-change hour) is forgiven", "{%- set d = d if (d is number and (d | abs) < 1000000000) else none -%}",
     ["{%- set d = d if (d is number and (d | abs) < 1000000000) else none -%}{%- set d = (d - 3600 * ((d / 3600) | round(0))) if d is not none else none -%}"]),
    ("M2 inverter: a difference of 1000 s or more counts as unreadable (UNKNOWN, not UNTRUSTED)", "(d is number and (d | abs) < 1000000000)", ["(d is number and (d | abs) < 1000)"]),
    ("M3 inverter: a maximum clock error since boot of 1000 s or more is forgiven", "(1 if m > 120 else 0)", ["(1 if (m > 120 and m < 1000) else 0)"]),
    ("M4 inverter: failed corrections are forgiven from 5 on", "(1 if f > 0 else 0)", ["(1 if (f > 0 and f < 5) else 0)"]),
    ("M5 HA clock: a skew of a day or more (a host booting with a stale date) reads DEGRADED (consumers on)", "('DEGRADED' if (skew | abs) <= 300 else 'UNTRUSTED')",
     ["('DEGRADED' if ((skew | abs) <= 300 or (skew | abs) >= 86400) else 'UNTRUSTED')"]),
    ("M6 HA clock: the text age is not rounded (0.5 s boundary)", "{%- set age = ((as_timestamp(now()) - as_timestamp(o.last_changed)) | round(0)) if o is not none else none -%}\n          {%- set live",
     ["{%- set age = (as_timestamp(now()) - as_timestamp(o.last_changed)) if o is not none else none -%}\n          {%- set live"]),
    ("M7 dongle NTP: an empty text is 'not a time' (UNTRUSTED) instead of unreadable (UNKNOWN)", "{%- set r2 = 2 if txt in ['unknown', 'unavailable', ''] else", ["{%- set r2 = 2 if txt in ['unknown', 'unavailable'] else"]),
    ("M11 correction helper: a stuck correction counts only while the stall flag is off (the reads stop during a correction, so the stall flag can stay on)",
     "state: \"{{ is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'on') }}\"",
     ["state: \"{{ is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'on') and is_state('binary_sensor.ecco_clock_dongle_rtc_stall_detected', 'off') }}\""]),
    ("HA clock reasons: a skew of 121 s is reported TRUSTED", "('TRUSTED' if (skew | abs) <= 120 else", ["('TRUSTED' if (skew | abs) <= 121 else"]),
    ("inverter reasons: a difference beyond 60 s is reported TRUSTED", "elif rd == 1 -%}", ["elif rd == 9 -%}"]),
    ("inverter reasons: a stuck correction is not reported", "elif rc == 3 -%}", ["elif rc == 9 -%}"]),
    ("dongle NTP reasons: a frozen text is not reported", "{%- if r3 == 3 -%}", ["{%- if r3 == 9 -%}"]),
    ("dongle NTP reasons: an unsynced flag is reported UNKNOWN", "['UNTRUSTED: the dongle reports that NTP is not synced']", ["['UNKNOWN: the dongle reports that NTP is not synced']"]),
    # ---- what the package must never contain (static)
    ("an automation is added", "\ntemplate:\n", ["\nautomation:\n  - alias: x\n    triggers: []\n    actions: []\n\ntemplate:\n"]),
    ("a helper is added", "\ntemplate:\n", ["\ninput_boolean:\n  ecco_time_trust_x: {}\n\ntemplate:\n"]),
    ("a trigger-based template is added", "  - sensor:\n      - name: ECCO Time Trust HA Clock", ["  - triggers: []\n    sensor:\n      - name: ECCO Time Trust HA Clock"]),
    ("an action is added to an entity", "        icon: mdi:timer-check-outline\n", ["        icon: mdi:timer-check-outline\n        action: persistent_notification.create\n"]),
    ("a variables block is added to an entity", "        icon: mdi:table-clock\n", ["        icon: mdi:table-clock\n        variables: {}\n"]),
    ("a dongle entity is written by a service call inside a template", "{{ is_state('sensor.ecco_time_trust_inverter_clock', 'TRUSTED') }}", ["{{ is_state('sensor.ecco_time_trust_inverter_clock', 'TRUSTED') }}{{ 'button.press' }}"]),
    ("a ninth dongle entity is read", "{%- set rk = {'TRUSTED': 0,", ["{%- set zz = states('sensor.ecco_clock_dongle_battery_soc') -%}{%- set rk = {'TRUSTED': 0,"]),
    ("the NTP text is read from a site entity (the slug is not generic)", "sensor.ecco_clock_dongle_ntp_time", ["sensor.site_dongle_ntp_time"]),
    ("the header no longer says it is not installed", "# NOT INSTALLED, NOT LIVE-PROVEN.", ["# Installed."], None, True),
    ("the header loses the time-zone assumption", "TIME-ZONE ASSUMPTION", ["TIME ZONE NOTE"], None, True),
    ("the header no longer says who may read it", "READERS allow-list", ["READERS note"], None, True),
    ("the header no longer names the start gate as a reader", "ecco_start_gate.yaml", ["ecco_start_gates.yaml"], None, True),
    ("the header no longer names the Free Power time guard as a reader", "ecco_lease_guard_free_power_time.yaml", ["ecco_lease_guards.yaml"], None, True),
    ("the header no longer says that another reader fails the suite", "fails that suite", ["is fine"], None, True),
    ("the header no longer says how a consumer must read it", "HOW A CONSUMER MUST READ IT", ["NOTE"], None, True),
    ("the header drops the limit that the sync flag never clears", "flag never clears after", ["flag clears when NTP is lost, after"], None, True),
    ("the header drops the VALUE rule", "VALUE (the proof).", ["VALUE (a note)."], None, True),
    ("the header drops the LIVE rule", "LIVE (an extra).", ["LIVE (a note)."], None, True),
    ("the header no longer names the stall delay", "delay_on 00:03:30 on a binary helper", ["delay_on 00:10:00 on a binary helper"], None, True),
    ("the header no longer says that a text is a time only in the firmware's form", "A TEXT IS A TIME only in the exact form the firmware writes it", ["A TEXT IS A TIME in any form"], None, True),
    ("the header claims a restart or reload can only withdraw trust", "creates no trust", ["can only withdraw trust"], None, True),
    ("a tab is added", "\ntemplate:\n", ["\n\ntemplate:\n\t"]),
    ("a site value is added (an address)", "\ntemplate:\n", ["\n# the dongle is at 203.0.113.20\n\ntemplate:\n"]),
    ("a unique_id is repeated", "unique_id: ecco_time_trusted_for_slot_edits", ["unique_id: ecco_time_trusted_for_leases"]),
]


def positions(text: str, anchor: str) -> list[int]:
    out, idx = [], -1
    while True:
        idx = text.find(anchor, idx + 1)
        if idx < 0:
            return out
        out.append(idx)


def in_comment(text: str, idx: int) -> bool:
    return text[text.rfind("\n", 0, idx) + 1:].lstrip().startswith("#")


def mutants():
    for entry in MUT:
        label, anchor, news = entry[:3]
        only = entry[3] if len(entry) > 3 else None          # the copies that are not equivalent (a copy whose change no state or text can show is left out, named in the label)
        with_comments = len(entry) > 4 and entry[4]          # a change inside a comment changes no behaviour: only the header mutants are made there
        pos = positions(PKG_TEXT, anchor)
        n = len(pos)
        if n == 0:
            yield label, None, None, "anchor not found"
            continue
        copies = [i for i in range(n) if (only is None or i in only) and (with_comments or not in_comment(PKG_TEXT, pos[i]))]
        if not copies:
            yield label, None, None, "anchor only in comments"
            continue
        for new in news:
            for i in copies:
                tag = f" (copy {i + 1} of {n})" if n > 1 else ""
                yield label + tag, nth_replace(PKG_TEXT, anchor, new, i), new, ""


killed = survived = 0
prefer: dict = {}                       # family of mutants (the label before its colon) -> the section that caught the last one: tried first
survivors: list = []
total = 0
for label, mutated, _new, err in mutants():
    total += 1
    if err:
        check(f"mutant anchor: {label}", False, err)
        continue
    if mutated == PKG_TEXT:
        check(f"mutant changes the text: {label}", False, "identical")
        continue
    family = label.split(":", 1)[0] if ":" in label else " ".join(label.split()[:2])
    info: dict = {}
    found = battery(mutated, mode="kill", prefer=prefer.get(family), info=info)
    if found:
        killed += 1
        prefer[family] = info.get("section")
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        survived += 1
        survivors.append(label)
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{total} mutants (every threshold on both sides, every unreadable-input branch, the debounce delays and availability, every term of each worst-of, the ranks of the overall state, "
      f"every consumer's allow-list, the reasons, and what the package must never contain): all caught", killed == total and total >= 150, f"{killed}/{total} {survivors[:3]}")
# ---- the READERS allow-list is PINNED: mutants of the repository's packages and of the allow-list itself, each caught. The clause is live: a third reader, a reader that reads more than it is listed
# with, a widened or emptied allow-list, a missing allow-list entry all fail it.
_gate_like = "# reads binary_sensor.ecco_time_trusted_for_leases and binary_sensor.ecco_time_trusted_for_ha_schedules (ecco_time_trust.yaml)\n"
_guard_like = "# reads binary_sensor.ecco_time_trusted_for_leases (ecco_time_trust.yaml)\n"
_readers_world = {**OTHER_TEXT, "ecco_start_gate.yaml": _gate_like, "ecco_lease_guard_free_power_time.yaml": _guard_like}
READER_MUTANTS = [
    ("a third package reads the leases consumer", {**_readers_world, "ecco_third.yaml": "state: \"{{ is_state('binary_sensor.ecco_time_trusted_for_leases', 'on') }}\"\n"}, READERS),
    ("a third package reads the schedules consumer", {**_readers_world, "ecco_third.yaml": "state: \"{{ is_state('binary_sensor.ecco_time_trusted_for_ha_schedules', 'on') }}\"\n"}, READERS),
    ("a third package reads the slot-edit consumer", {**_readers_world, "ecco_third.yaml": "state: \"{{ is_state('binary_sensor.ecco_time_trusted_for_slot_edits', 'on') }}\"\n"}, READERS),
    ("a third package reads the overall sensor", {**_readers_world, "ecco_third.yaml": "state: \"{{ states('sensor.ecco_time_trust') }}\"\n"}, READERS),
    ("a third package mentions only the file name", {**_readers_world, "ecco_third.yaml": "# needs ecco_time_trust.yaml\n"}, READERS),
    ("the Free Power time guard also reads the schedules consumer", {**_readers_world, "ecco_lease_guard_free_power_time.yaml": _guard_like + "# binary_sensor.ecco_time_trusted_for_ha_schedules\n"}, READERS),
    ("the start gate also reads the slot-edit consumer", {**_readers_world, "ecco_start_gate.yaml": _gate_like + "# binary_sensor.ecco_time_trusted_for_slot_edits\n"}, READERS),
    ("a reader reads an internal helper", {**_readers_world, "ecco_start_gate.yaml": _gate_like + "# binary_sensor.ecco_time_trust_rtc_stall_sustained\n"}, READERS),
    ("a reader reads a per-clock sensor", {**_readers_world, "ecco_lease_guard_free_power_time.yaml": _guard_like + "# sensor.ecco_time_trust_ha_clock\n"}, READERS),
    ("a reader names a consumer without its domain", {**_readers_world, "ecco_start_gate.yaml": _gate_like + "# ecco_time_trusted_for_slot_edits\n"}, READERS),
    ("the clause is removed: an empty allow-list lets no reader through", _readers_world, {}),
    ("the allow-list gains a third package", _readers_world, {**READERS, "ecco_third.yaml": frozenset({K["LEASES"]})}),
    ("the allow-list gives the Free Power time guard the schedules consumer", _readers_world, {**READERS, "ecco_lease_guard_free_power_time.yaml": frozenset({K["LEASES"], K["SCHED"]})}),
    ("the allow-list gives the start gate the slot-edit consumer", _readers_world, {**READERS, "ecco_start_gate.yaml": frozenset({K["LEASES"], K["SCHED"], K["SLOT"]})}),
    ("the allow-list drops the start gate", _readers_world, {k: v for k, v in READERS.items() if k != "ecco_start_gate.yaml"}),
]
_reader_survivors = []
for _label, _world, _allow in READER_MUTANTS:
    _found = readers_problems(_world, _allow) + readers_pin_problems(_allow)
    if _found:
        print(f"  PASS  mutant caught: {_label} ({_found[0][:90]})")
    else:
        _reader_survivors.append(_label)
        FAILURES.append(f"mutant survived: {_label}")
        print(f"  FAIL  mutant survived: {_label}")
check(f"the READERS allow-list is pinned: the two listed readers alone pass, and all {len(READER_MUTANTS)} mutants (a third reader, a reader that reads more than it is listed with, a widened, emptied or "
      "shortened allow-list) are caught", readers_problems(_readers_world, READERS) + readers_pin_problems(READERS) == [] and not _reader_survivors, str(_reader_survivors[:3]))
_harmless = PKG_TEXT.replace("# WHY. ECCO acts on time in three places", "# WHY, restated. ECCO acts on time in three places")
check("a harmless rewrite (a comment) survives the battery, and a rewrite of a rule does not",
      _harmless != PKG_TEXT and battery(_harmless, mode="kill") == [] and battery(PKG_TEXT.replace("age > 300", "age > 3000"), mode="kill") != [])

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll time trust checks passed.")
print("These prove the package against a model of Home Assistant's template entities; nothing was installed, nothing was written live, and nothing here wires the input into a gate.")
