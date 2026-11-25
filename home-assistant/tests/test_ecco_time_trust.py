"""Offline suite for the time trust package (home-assistant/packages/ecco_time_trust.yaml): THREE CLOCKS, ONE EXPLICIT TIMING-SAFETY INPUT, READ-ONLY.

The inverter's RTC stalls for 60 s about 85 times a day, Home Assistant starts schedules on its own clock and the dongle ends leases on its NTP time.
If trustworthy time cannot be established, anything that depends on it must fail safely. The package turns what the dongle already publishes into
that input (one state per clock, an overall state and three yes/no consumers); it builds the INPUT ONLY, reads nothing it does not need and writes
nothing. This suite proves the package against a model of Home Assistant's template entities (home-assistant/tests/_time_trust_sim.py); nothing was
installed, nothing was written live, and nothing here wires the input into a gate.

The REAL package YAML runs under the model: dependency-tracked rendering, a render at the start of every minute for a template that uses now(), the
availability template, attributes, a binary sensor with delay_on (it keeps its state while it counts, a change of the result cancels the count).

  [0] static      only `template:`; nine entities; no automation, script, helper, trigger, action or service call; the eight dongle entities it reads
                  exist in the firmware; its own ids are defined nowhere else; ASCII, LF, no site value; the default device slug appears only as
                  entity ids (the site renderer's exact rules); the header states the constants with their reasons and the limits; the deployment
                  manifest and the README and the CHANGELOG say the same; the firmware facts the header relies on are pinned
  [1] model       control experiments on the model itself (delay_on, availability, re-rendering by time alone, an error, unavailable drops attributes)
  [2] scenarios   the saved data and the agreed list: a normal 10 s with a flickering stall flag for three hours; 70 s and 130 s; NTP unsynced; the NTP
                  text frozen for 4, 5 and 6 minutes; the Home Assistant clock 130 s and 310 s out; the stall flag on for 9 and 11 minutes; a correction
                  stuck for 6 minutes; each input unavailable, unknown or missing, one at a time; all of them at once; failed corrections above 0;
                  maximum clock error above 120 s; the clock-change hour; a time-zone mismatch; the age of the text; a template reload and a restart with the flag already on
  [3] boundaries  every limit on both sides (skew +-119 .. 301, difference +-59 .. 121, text age 299 .. 301, stall 9:59 and 10:00, correction 4:59 and 5:00)
  [4] consumers   the truth tables of the overall state and of the three yes/no consumers over every per-clock state and every unreadable value
  [5] differential every rule against an independent model over one-factor sweeps and a seeded random sample
  [6] totality    a garbage, missing, huge or non-numeric input never makes a template fail and never reads TRUSTED
  [7] no writes   the model saw no service call, no notification and no write outside the package's own nine entities
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
         STUCK="binary_sensor.ecco_time_trust_rtc_correction_stuck")
OWN = set(K.values())
OWN_NAMES = {"ECCO Time Trust RTC Stall Sustained", "ECCO Time Trust RTC Correction Stuck", "ECCO Time Trusted For Leases",
             "ECCO Time Trusted For HA Schedules", "ECCO Time Trusted For Slot Edits", "ECCO Time Trust HA Clock", "ECCO Time Trust Dongle NTP",
             "ECCO Time Trust Inverter Clock", "ECCO Time Trust"}
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
HEADER_PINS = ("NOT INSTALLED, NOT LIVE-PROVEN", "(diagnostic and READ-ONLY)", "BUILDS THE INPUT ONLY", "nothing reads it yet", "nine template entities", "no automation, no script, no helper, no trigger, no action",
               "no service call", "UNKNOWN never reads better than DEGRADED", "TRUSTED < DEGRADED < UNKNOWN < UNTRUSTED", "TIME-ZONE ASSUMPTION", "R9",
               "carries NO offset", "whole hours and is UNTRUSTED, never TRUSTED", "repeated hour of the autumn clock change", "kLargeErrorS", "REQ-D1",
               "|skew| <= 120 s TRUSTED, <= 300 s DEGRADED", "ARRIVED", "text_age_s", "|difference| <= 60 s TRUSTED, <= 120 s DEGRADED", "failed corrections since boot > 0",
               "maximum clock error since boot > 120 s", "10 minutes of CONTINUOUS ON", "5 minutes of CONTINUOUS ON", "delay_on", "PROXY for the sync age",
               "item N1", "FAIL SAFE", "can NEVER produce TRUSTED", "allow-lists", "HOW A CONSUMER MUST READ IT", "Never test \"not off\"", "LIMITS, stated plainly",
               "AGREE, not that either is true", "never clears after the first sync", "Recalled, NOT verified", "INSTALL", "RELOAD the template entities",
               "no restart", "HARD RULES", "READ-ONLY", "Every template is total")


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
    return bad + header_problems(text) + privacy_problems(text)


print("[0] static")
sp = static_problems(PKG_TEXT)
check("the package loads with no repeated key; only `template:`; nine template entities (five binary, four sensors) with exactly the allowed keys; no automation, "
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
check("its nine entity ids and unique ids are defined nowhere else in the repository's packages (no repeated key inside any package, no unique_id twice)",
      own_ids == OWN and not (own_ids & repo_other) and not [n for n, p in OTHER_PKGS.items() if "ecco_time_trust" in p.read_text(encoding="utf-8")])
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
check("the packages README has a Time trust section that names the nine entities, every rule and constant, the time-zone assumption, the fail-safe rule, the limits, the install route and "
      "the replay counts; the CHANGELOG has one bullet that says it is read-only, offline and installs nothing",
      all(s in README_FLAT for s in ("## Time trust", "sensor.ecco_time_trust_ha_clock", "sensor.ecco_time_trust_dongle_ntp", "sensor.ecco_time_trust_inverter_clock",
                                     "binary_sensor.ecco_time_trusted_for_leases", "binary_sensor.ecco_time_trusted_for_ha_schedules",
                                     "binary_sensor.ecco_time_trusted_for_slot_edits", "UNKNOWN never reads better than DEGRADED", "reload the template entities",
                                     "Replay of the saved 10 days", "never longer in the saved data", "time-zone assumption", "NOT ESTABLISHED"))
      and all(s in BULLET for s in ("read-only", "nothing installed", "It writes nothing", "never produce TRUSTED", "restart_required: false")), "")

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


def o_ha(text_kind, skew, age):
    """text_kind 'time' | 'not_time' | 'unreadable' | 'missing'; skew whole seconds; age whole seconds (None = unreadable)."""
    if text_kind != "time" or age is None or age > 300:
        return "UNKNOWN"
    a = abs(skew)
    return "TRUSTED" if a <= 120 else ("DEGRADED" if a <= 300 else "UNTRUSTED")


def o_ntp(synced, text_kind, age):
    r1 = 0 if synced == "on" else (3 if synced == "off" else 2)
    r2 = {"time": 0, "not_time": 3}.get(text_kind, 2)
    r3 = 0 if r2 > 0 else (2 if age is None else (3 if age > 300 else 0))
    return NAMES[max(r1, r2, r3)]


def o_inv(diff, failed, maxerr, stall, stuck, synced, text_kind, text_age):
    d, f, m = readable(diff), readable(failed, True), readable(maxerr, True)
    ranks = [2 if d is None else (3 if abs(d) > 120 else (1 if abs(d) > 60 else 0)),
             2 if f is None else (1 if f > 0 else 0),
             2 if m is None else (1 if m > 120 else 0),
             {"off": 0, "on": 1}.get(stall, 2),
             {"off": 0, "on": 3}.get(stuck, 2),
             0 if synced == "on" else 2,
             2 if (text_kind != "time" or text_age is None or text_age > 300) else 0]
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
          start=START, ha_zone="Europe/London", dongle_zone=None, restore_off=False):
    """A healthy dongle (published every 60 s, on the minute) and Home Assistant, run for `warm` seconds. A value of None leaves the entity absent; `ntp` and `inv` are
    'live' (a text every 60 s), None (never published) or a constant text."""
    tw = T.TrustWorld(text, start=start, zone=ha_zone, restore_off=restore_off)
    tw.w.clock_offset = ha_offset
    for eid, v in ((DIFF, diff), (FAILED, failed), (MAXERR, maxerr), (SYNCED, synced), (STALL, stall), (CORR, corr)):
        if v is not None:
            tw.put(eid, v)
    tw.h_ntp = tw.feed(NTP_TEXT, zone=dongle_zone) if ntp == "live" else None
    if ntp not in ("live", None):
        tw.put(NTP_TEXT, ntp)
    tw.h_inv = tw.feed(INV_TEXT, offset_s=7) if inv == "live" else None
    if inv not in ("live", None):
        tw.put(INV_TEXT, inv)
    tw.advance(warm)
    return tw


def reasons_problems(tw) -> list[str]:
    """Each per-clock sensor's `reasons` is a non-empty list whose strongest tag is the state."""
    bad = []
    for key in ("HA", "NTP", "INV"):
        st, rs = tw.state(K[key]), tw.attr(K[key], "reasons")
        if st not in NAMES:
            bad.append(f"{key} state {st!r}")
        elif not (isinstance(rs, list) and rs and all(isinstance(r, str) and r.split(":", 1)[0] in NAMES for r in rs)):
            bad.append(f"{key} reasons {str(rs)[:60]!r}")
        elif NAMES[max(NAMES.index(r.split(":", 1)[0]) for r in rs)] != st:
            bad.append(f"{key} reasons say {NAMES[max(NAMES.index(r.split(':', 1)[0]) for r in rs)]}, state {st}")
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
def battery(text: str, mode: str = "kill") -> list[str]:
    """mode 'report': every proof is a check() line. mode 'kill': return at the first failing proof (a mutant is caught) with its name, else []."""
    rec = make_rec(mode)
    try:
        sp = static_problems(text)
        rec("the package is static-clean (template entities only, read-only, the eight dongle entities, the header, no site value)", not sp, str(sp[:3]))
        thorough = mode == "report"
        if thorough:                  # the report reads in the order of the sections above; a mutant meets the cheap, sharp proofs first
            sec_model(rec)
            order = (sec_scenarios, sec_boundaries, sec_consumers, sec_differential, sec_totality, sec_nowrite)
        else:
            order = (sec_boundaries, sec_consumers, sec_differential, sec_scenarios, sec_totality, sec_nowrite)
        for sec in order:
            if sec in (sec_differential, sec_totality):
                sec(text, rec, thorough=thorough)
            else:
                sec(text, rec)
    except Killed as k:
        return [str(k)]
    return []


# --- [1] the model itself ---------------------------------------------------------------------------------------------------
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
    tw.put("sensor.in", "unavailable")
    un = (tw.state(d), tw.state(p))
    tw.put("sensor.in", "on")
    tw.advance(300)
    rec("model: an unreadable input makes the delayed entity unavailable and the count restarts (on, unavailable, on for 5 min: not on)", un == ("unavailable", "off") and tw.state(d) == "off", f"{un} {tw.state(d)}")
    n0 = tw.state("sensor.probe_now")
    r_now, r_plain, r_other = tw.renders.get("sensor.probe_now", 0), tw.renders.get("sensor.probe_no_now", 0), tw.renders.get("sensor.probe_other", 0)
    tw.advance(180)
    rec("model: a template that calls now() is rendered again every minute with no entity changing; one that does not is not (dependency tracking)",
        tw.state("sensor.probe_now") != n0 and tw.renders["sensor.probe_now"] - r_now == 3 and tw.renders.get("sensor.probe_no_now", 0) == r_plain, f"{tw.renders}")
    tw.put("sensor.unrelated", "1")
    tw.put("sensor.other", "z")
    rec("model: an entity is rendered again only when an entity it read changes",
        tw.renders.get("sensor.probe_no_now", 0) == r_plain and tw.renders.get("sensor.probe_other", 0) > r_other)
    tw.put("sensor.in", "abc")
    rec("model: a render error leaves the entity unknown and is recorded", tw.state("sensor.probe_error") == "unknown" and any("probe_error" in e for e in tw.errors), str(tw.errors[:1]))
    tw.put("sensor.in", "7")
    attrs = tw.w.states["sensor.probe_no_now"][1]
    rec("model: attributes are parsed natively (a list, a number)", attrs.get("a") == ["x", 1] and attrs.get("n") == 12, str(attrs))
    # a cold start with the input already on, with and without a restored state
    cold = T.TrustWorld(MODEL_PKG, preload={"sensor.in": "on"})
    restored = T.TrustWorld(MODEL_PKG, restore_off=True, preload={"sensor.in": "on"})
    cold.advance(599)
    restored.advance(599)
    c1, r1 = cold.state(d), restored.state(d)
    cold.advance(1)
    restored.advance(1)
    rec("model: a delayed binary sensor whose first result is true (the input already on when it is first rendered) reads unknown (off when a state is restored) and is on after the delay",
        (c1, r1, cold.state(d), restored.state(d)) == ("unknown", "off", "on", "on"), f"{c1} {r1}")


# --- [2] scenarios ----------------------------------------------------------------------------------------------------------
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
    verify(rec, "the NTP text published again: TRUSTED at once", tw, exp())
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
    # --- the stall flag and the correction flag over time
    tw = world(text)
    tw.put(STALL, "on")
    tw.advance(540)
    verify(rec, "the stall flag on for 9 minutes: not counted (the inverter clock TRUSTED)", tw, exp())
    tw.advance(59)
    verify(rec, "the stall flag on for 9 minutes 59 s: not counted", tw, exp())
    tw.advance(1)
    verify(rec, "the stall flag on for 10 minutes: counted: the inverter clock DEGRADED, the overall state DEGRADED, slot edits off, leases and schedules still on", tw,
           exp(INV="DEGRADED", ALL="DEGRADED", SLOT="off", STALLS="on"))
    tw.advance(60)
    verify(rec, "the stall flag on for 11 minutes: still DEGRADED", tw, exp(INV="DEGRADED", ALL="DEGRADED", SLOT="off", STALLS="on"))
    tw.put(STALL, "off")
    verify(rec, "the stall flag off: TRUSTED again at once", tw, exp())
    tw.put(STALL, "on")
    tw.advance(540)
    tw.put(STALL, "off")
    tw.advance(1)
    tw.put(STALL, "on")
    tw.advance(540)
    verify(rec, "9 minutes on, 1 s off, 9 minutes on: the count restarted, never counted", tw, exp())
    tw.put(STALL, "unavailable")
    verify(rec, "an unreadable stall flag is never a quiet off: the helper is unavailable and the inverter clock UNKNOWN", tw, exp(INV="UNKNOWN", ALL="UNKNOWN", SLOT="off", STALLS="unavailable"))
    tw.advance(1)
    tw.put(STALL, "on")
    tw.advance(540)
    verify(rec, "an unreadable flag in the middle of a long on restarts the count (9 minutes on after it: not counted)", tw, exp())
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
    # --- the failure counters (latched until the dongle reboots)
    for failed, maxerr, diff, want in (("1", "77", "10", "DEGRADED"), ("3", "77", "10", "DEGRADED"), ("0", "121", "10", "DEGRADED"), ("0", "500", "10", "DEGRADED"),
                                       ("1", "77", "130", "UNTRUSTED"), ("0", "77", "10", "TRUSTED"), ("0", "120", "10", "TRUSTED")):
        tw = world(text, failed=failed, maxerr=maxerr, diff=diff)
        verify(rec, f"failed corrections {failed}, maximum clock error {maxerr} s, difference {diff} s: the inverter clock is {want}", tw,
               exp(INV=want, ALL=want, SLOT="on" if want == "TRUSTED" else "off"))
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
           dict(HA="UNKNOWN", NTP="UNKNOWN", INV="UNKNOWN", ALL="UNKNOWN", LEASES="off", SCHED="off", SLOT="off", STALLS="unavailable", STUCK="unavailable"))
    for eid, v in ((DIFF, "10"), (FAILED, "0"), (MAXERR, "77"), (SYNCED, "on"), (STALL, "off"), (CORR, "off")):
        tw.put(eid, v)
    tw.h_ntp = tw.feed(NTP_TEXT)
    tw.h_inv = tw.feed(INV_TEXT, offset_s=7)
    tw.advance(60)
    verify(rec, "the dongle back: every clock TRUSTED within a minute (nothing latches an outage)", tw, exp())
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
    # --- a template reload with the stall flag already on, and a restart: the count restarts, so a stall that began earlier is noticed up to 10 minutes late (documented)
    pre = {SYNCED: "on", DIFF: "10", FAILED: "0", MAXERR: "77", STALL: "on", CORR: "off"}
    for restore, first in ((False, "UNKNOWN"), (True, "TRUSTED")):
        tw = T.TrustWorld(text, start=START, restore_off=restore, preload=pre)
        tw.feed(NTP_TEXT)
        tw.feed(INV_TEXT, offset_s=7)
        tw.advance(540)
        a = tw.state(K["INV"])
        tw.advance(60)
        verify(rec, f"a template reload with the stall flag already on ({'a restored off' if restore else 'no restored state'}): the inverter clock reads {first} for the first 10 minutes "
               "(documented: the count restarts, so it can only delay DEGRADED; an unknown helper is UNKNOWN) and DEGRADED after", tw,
               exp(INV="DEGRADED", ALL="DEGRADED", SLOT="off", STALLS="on"), extra=[] if a == first else [f"first {a}"])
    tw = T.TrustWorld(text, start=START)                             # a restart: the dongle's entities are not there yet when the templates are first rendered
    for eid, v in ((SYNCED, "on"), (DIFF, "10"), (FAILED, "0"), (MAXERR, "77"), (STALL, "on"), (CORR, "off")):
        tw.put(eid, v)
    tw.feed(NTP_TEXT)
    tw.feed(INV_TEXT, offset_s=7)
    tw.advance(540)
    a = tw.state(K["INV"])
    tw.advance(60)
    verify(rec, "a restart with a stall flag that had been on for longer: the helper reads off for the first 10 minutes (documented: the count starts when Home Assistant first sees the flag "
           "on) and DEGRADED after", tw, exp(INV="DEGRADED", ALL="DEGRADED", SLOT="off", STALLS="on"), extra=[] if a == "TRUSTED" else [f"first {a}"])
    # --- the clock-change hour, and a time-zone mismatch (the R9 assumption)
    tw = world(text, start="2026-10-25 00:30:00", warm=3600)            # 00:30 BST + 1 h = 00:30 UTC, the first 01:30 (BST)
    ok_first = tw.state(K["HA"])
    tw.advance(3600)                                                     # 01:30 UTC, the second 01:30 (GMT): the text reads 01:30, which is read as the first one
    in_second = (tw.state(K["HA"]), tw.attr(K["HA"], "skew_s"), tw.state(K["LEASES"]), tw.state(K["SCHED"]))
    tw.advance(3600)                                                     # 02:30 UTC
    after = tw.state(K["HA"])
    rec("the autumn clock change: the Home Assistant clock is TRUSTED before the repeated hour, UNTRUSTED (skew +3600 s, leases and schedules off) for the second pass of it "
        "(the repeated local time is read as its first occurrence: documented, it fails safe) and TRUSTED again after", (ok_first, in_second, after) == ("TRUSTED", ("UNTRUSTED", 3600, "off", "off"), "TRUSTED")
        and not tw.errors, f"{ok_first} {in_second} {after}")
    tw = world(text, start="2026-07-01 12:00:00", ha_zone="UTC", dongle_zone="Europe/London")
    verify(rec, "the R9 time-zone assumption: Home Assistant in UTC and a dongle in Europe/London in summer: the skew reads whole hours (-3600 s), UNTRUSTED, never TRUSTED", tw,
           exp(HA="UNTRUSTED", ALL="UNTRUSTED", LEASES="off", SCHED="off"), extra=[] if tw.attr(K["HA"], "skew_s") == -3600 else [str(tw.attr(K["HA"], "skew_s"))])
    tw = world(text, start="2026-07-01 12:00:00")
    verify(rec, "the same summer day with Home Assistant and the dongle in the same zone: TRUSTED", tw, exp())


# --- [3] boundaries ----------------------------------------------------------------------------------------------------------
def sec_boundaries(text, rec):
    ha_table = ((0, "TRUSTED"), (119, "TRUSTED"), (120, "TRUSTED"), (121, "DEGRADED"), (299, "DEGRADED"), (300, "DEGRADED"), (301, "UNTRUSTED"),
                (-119, "TRUSTED"), (-120, "TRUSTED"), (-121, "DEGRADED"), (-299, "DEGRADED"), (-300, "DEGRADED"), (-301, "UNTRUSTED"), (3600, "UNTRUSTED"),
                (120.4, "TRUSTED"), (120.6, "DEGRADED"), (300.4, "DEGRADED"), (300.6, "UNTRUSTED"), (-120.4, "TRUSTED"), (-120.6, "DEGRADED"), (-300.6, "UNTRUSTED"))
    bad = []
    for off, want in ha_table:
        tw = world(text, ha_offset=off, warm=120)
        got = tw.state(K["HA"])
        if got != want or tw.attr(K["HA"], "skew_s") != round(off) or snapshot_problems(tw):
            bad.append(f"{off}: {got}")
    rec("the Home Assistant clock skew at every limit and both signs (+-119, 120, 121, 299, 300, 301, 3600, and 120.4 / 120.6 / 300.4 / 300.6, which round to whole seconds): TRUSTED up to and "
        "including 120 s, DEGRADED up to and including 300 s, UNTRUSTED above", not bad, str(bad[:3]))
    inv_table = (("0", "TRUSTED"), ("10", "TRUSTED"), ("59", "TRUSTED"), ("60", "TRUSTED"), ("61", "DEGRADED"), ("119", "DEGRADED"), ("120", "DEGRADED"), ("121", "UNTRUSTED"),
                 ("-59", "TRUSTED"), ("-60", "TRUSTED"), ("-61", "DEGRADED"), ("-120", "DEGRADED"), ("-121", "UNTRUSTED"), ("300", "UNTRUSTED"), ("60.4", "DEGRADED"))
    bad = []
    tw = world(text)
    for diff, want in inv_table:
        tw.put(DIFF, diff)
        if tw.state(K["INV"]) != want or snapshot_problems(tw):
            bad.append(f"{diff}: {tw.state(K['INV'])}")
        if tw.state(K["SLOT"]) != ("on" if want == "TRUSTED" else "off"):
            bad.append(f"slot at {diff}")
    tw.put(DIFF, "10")
    rec("the inverter clock difference at every limit and both signs (+-59, 60, 61, 119, 120, 121, 300): TRUSTED up to and including 60 s, DEGRADED up to and including 120 s, UNTRUSTED above; "
        "slot edits on only when TRUSTED", not bad, str(bad[:3]))
    bad = []
    for failed, want in (("0", "TRUSTED"), ("1", "DEGRADED"), ("2", "DEGRADED"), ("0.0", "TRUSTED")):
        tw.put(FAILED, failed)
        if tw.state(K["INV"]) != want:
            bad.append(f"failed {failed}: {tw.state(K['INV'])}")
    tw.put(FAILED, "0")
    for maxerr, want in (("0", "TRUSTED"), ("119", "TRUSTED"), ("120", "TRUSTED"), ("121", "DEGRADED"), ("77", "TRUSTED")):
        tw.put(MAXERR, maxerr)
        if tw.state(K["INV"]) != want:
            bad.append(f"max {maxerr}: {tw.state(K['INV'])}")
    rec("failed corrections above 0 and a maximum clock error above 120 s (both since boot) degrade the inverter clock, at the limit on both sides", not bad, str(bad[:3]))
    # the age of the NTP text and of the inverter time text, exactly
    bad = []
    tw = world(text)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    for age, want_ntp, want_ha, want_inv in ((0, "TRUSTED", "TRUSTED", "TRUSTED"), (299, "TRUSTED", "TRUSTED", "TRUSTED"), (300, "TRUSTED", "TRUSTED", "TRUSTED"),
                                            (301, "UNTRUSTED", "UNKNOWN", "UNKNOWN"), (3600, "UNTRUSTED", "UNKNOWN", "UNKNOWN")):
        tw.put(NTP_TEXT, tw.local_text(tw.w.t + tw.w.clock_offset - age))      # a text a perfect dongle published `age` seconds ago
        tw.age(NTP_TEXT, age)
        tw.age(INV_TEXT, age)
        got = (tw.state(K["NTP"]), tw.state(K["HA"]), tw.state(K["INV"]))
        if got != (want_ntp, want_ha, want_inv) or snapshot_problems(tw):
            bad.append(f"age {age}: {got}")
    rec("the age of the NTP text and of the inverter time text at the limit (0, 299, 300 TRUSTED; 301 and 3600: the dongle NTP UNTRUSTED, the HA clock UNKNOWN, the inverter clock UNKNOWN)", not bad, str(bad[:3]))
    # the two timers, exactly
    bad = []
    for flag, helper, limit, on_state, inv_on in ((STALL, K["STALLS"], 600, "DEGRADED", "DEGRADED"), (CORR, K["STUCK"], 300, "UNTRUSTED", "UNTRUSTED")):
        tw = world(text)
        tw.put(flag, "on")
        tw.advance(limit - 1)
        a = (tw.state(helper), tw.state(K["INV"]))
        tw.advance(1)
        b = (tw.state(helper), tw.state(K["INV"]))
        if a != ("off", "TRUSTED") or b != ("on", inv_on) or snapshot_problems(tw):
            bad.append(f"{flag}: {a} {b}")
    rec("the two timers at the second: the stall helper is off at 9:59 and on at 10:00 (DEGRADED), the correction helper off at 4:59 and on at 5:00 (UNTRUSTED)", not bad, str(bad[:2]))


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


# --- [5] differential ---------------------------------------------------------------------------------------------------------
def sec_differential(text, rec, thorough):
    rng = random.Random(25112026)
    # the HA clock and the dongle NTP over the text, the flag, the age and the skew
    tw = world(text)
    tw.h_ntp["on"] = tw.h_inv["on"] = False
    bad, n = [], 0
    kinds = {"time": None, "not_time": ("Waiting for NTP", "NTP time invalid", "abc"), "unreadable": ("unknown", "unavailable", ""), "missing": (None,)}
    syncs = ("on", "off", "unavailable", "unknown", None, "ON", "abc")
    skews = (0, 1, 119, 120, 121, 299, 300, 301, -119, -120, -121, -299, -300, -301, 3600, -3600) if thorough else (0, 120, 121, 300, 301, -121, -301)
    ages = (0, 60, 299, 300, 301, 3600) if thorough else (0, 300, 301)
    for sy in syncs:
        tw.put(SYNCED, sy)
        for kind, samples in kinds.items():
            pairs = [(s_, a_) for s_ in skews for a_ in ages] if kind == "time" else [(0, 0), (0, 301)]
            for skew, age in pairs:
                if kind == "time":
                    # a text whose content is `skew` seconds behind Home Assistant's own clock, stamped `age` seconds ago
                    tw.put(NTP_TEXT, tw.local_text(tw.w.t + tw.w.clock_offset - age - skew))
                else:
                    tw.put(NTP_TEXT, samples[(skew + age) % len(samples)])
                if kind == "missing":
                    tw.force()
                else:
                    tw.age(NTP_TEXT, age)
                want_ha = o_ha(kind, skew, None if kind == "missing" else age)
                want_ntp = o_ntp(sy, kind, None if kind == "missing" else age)
                got = (tw.state(K["HA"]), tw.state(K["NTP"]))
                n += 1
                if got != (want_ha, want_ntp):
                    bad.append(f"sync {sy} {kind} skew {skew} age {age}: {got} != {(want_ha, want_ntp)}")
            if len(bad) > 3:
                break
        if len(bad) > 3:
            break
    rec(f"the Home Assistant clock and the dongle NTP clock against an independent model over {n} combinations of synced flag (7 values), text (a time, not a time, unreadable, missing), "
        "skew and age", not bad and not snapshot_problems(tw), str(bad[:2]))
    # the inverter clock: one factor at a time, then a seeded random sample
    tw = world(text)
    base = dict(diff="10", failed="0", maxerr="77", synced="on", stall="off", stuck="off", itext="time", iage=0)
    diffs = ("-300", "-121", "-120", "-61", "-60", "-1", "0", "10", "60", "61", "119", "120", "121", "300", "unavailable", "unknown", "", "abc", "nan", "inf", "-inf", "1e999", None)
    fails = ("0", "1", "2", "-1", "unavailable", "unknown", "", "abc", "nan", "inf", None)
    maxes = ("0", "77", "119", "120", "121", "500", "-5", "unavailable", "unknown", "", "abc", "inf", None)
    flags = ("off", "on", "unavailable", "unknown", "")
    syncs2 = ("on", "off", "unavailable", "unknown", None)
    itexts = (("time", 0), ("time", 299), ("time", 300), ("time", 301), ("time", 7200), ("unreadable", 0), ("missing", 0))

    def apply(cfg):
        tw.put(DIFF, cfg["diff"])
        tw.put(FAILED, cfg["failed"])
        tw.put(MAXERR, cfg["maxerr"])
        tw.put(SYNCED, cfg["synced"])
        tw.override(K["STALLS"], cfg["stall"])
        tw.override(K["STUCK"], cfg["stuck"])
        kind, age = cfg["itext"] if isinstance(cfg["itext"], tuple) else (cfg["itext"], cfg["iage"])
        if kind == "time":
            tw.put(INV_TEXT, tw.local_text(tw.w.t + tw.w.clock_offset + age + 1))     # a new text each time (the previous one differs)
            tw.age(INV_TEXT, age)
        elif kind == "unreadable":
            tw.put(INV_TEXT, "unavailable")
            tw.force()
        else:
            tw.put(INV_TEXT, None)
        want = o_inv(cfg["diff"], cfg["failed"], cfg["maxerr"], cfg["stall"], cfg["stuck"], cfg["synced"], kind, None if kind == "missing" else age)
        got = tw.state(K["INV"])
        return got, want

    bad, n = [], 0
    for field, values in (("diff", diffs), ("failed", fails), ("maxerr", maxes), ("stall", flags), ("stuck", flags), ("synced", syncs2), ("itext", itexts)):
        for v in values:
            cfg = dict(base)
            cfg[field] = v
            got, want = apply(cfg)
            n += 1
            if got != want or snapshot_problems(tw):
                bad.append(f"{field}={v!r}: {got} != {want} {snapshot_problems(tw)[:1]}")
    rec(f"the inverter clock against an independent model, one input at a time over every value (including unreadable and non-finite ones): {n} cases", not bad, str(bad[:2]))
    bad = []
    samples = 700 if thorough else 120
    for _ in range(samples):
        cfg = dict(diff=rng.choice(diffs), failed=rng.choice(fails), maxerr=rng.choice(maxes), stall=rng.choice(flags), stuck=rng.choice(flags), synced=rng.choice(syncs2),
                   itext=rng.choice(itexts), iage=0)
        got, want = apply(cfg)
        if got != want or snapshot_problems(tw):
            bad.append(f"{cfg}: {got} != {want} {snapshot_problems(tw)[:1]}")
            break
    rec(f"the inverter clock against an independent model over {samples} seeded random combinations of its seven inputs", not bad, str(bad[:1]))


# --- [6] totality -------------------------------------------------------------------------------------------------------------
def sec_totality(text, rec, thorough):
    garbage = ("", "unknown", "unavailable", "None", "null", "abc", "nan", "NaN", "inf", "-inf", "1e999", "-1e999", "--5", "5 s", "0x10", "1,5", "ON", "On", "true", "1", "0",
               "2026-11-25", "2026-11-25T12:00:00+00:00", "99999999999999999999", "'", "\"", "{{ 1 }}", "{% if %}", "\\", "a" * 255)
    if not thorough:                                     # a mutant: the values that exercise every branch of the readings, not every spelling
        garbage = ("", "unknown", "unavailable", "abc", "nan", "inf", "-inf", "1e999", "ON", "1", "'", "{{ 1 }}")
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
    rec(f"{len(READS)} inputs x {len(garbage)} garbage values (empty, text, nan, infinities, huge, quotes, template syntax, 255 characters): no template ever fails and the overall state "
        "and consumers stay what the clock states say", not bad, str(bad[:2]))
    # a value that is not a sane reading of an input can never leave the clock that reads it TRUSTED where the value is meaningless
    bad = []
    for eid, values, key in ((SYNCED, ("", "unknown", "unavailable", "ON", "abc", "true", "1"), "NTP"), (DIFF, ("", "unknown", "unavailable", "abc", "nan", "inf", "-inf", "1e999", "5 s"), "INV"),
                             (FAILED, ("", "unknown", "unavailable", "abc", "nan", "inf", "-1"), "INV"), (MAXERR, ("", "unknown", "unavailable", "abc", "nan", "inf", "-1"), "INV"),
                             (STALL, ("", "unknown", "unavailable", "ON", "abc"), "INV"), (CORR, ("", "unknown", "unavailable", "ON", "abc"), "INV")):
        for g in values:
            tw = world(text, warm=120)
            tw.put(eid, g)
            tw.advance(60)
            if tw.state(K[key]) == "TRUSTED" or tw.state(K["ALL"]) == "TRUSTED":
                bad.append(f"{eid}={g!r} -> {tw.state(K[key])}")
    rec("an input that is not a sane reading (unreadable, not a number, not finite, negative where a counter, a flag that is neither on nor off) never leaves a TRUSTED clock "
        "or a TRUSTED overall state", not bad, str(bad[:3]))


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
    rec("the model saw no service call and no notification, and every entity written was one of the package's nine or an input the test set (the package writes nothing it does not own)",
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


STATE_MAX = "[[rd, rf, rm, rs, rc, ry, ra] | max]"
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
    ("HA clock: a text that is not a time reads as 0 (the R9 default) and the clock is compared with 1970", "as_timestamp(txt, none)", ["as_timestamp(txt, 0)"]),
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
    ("dongle NTP: the synced flag is not read", "{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3] | max] }}", ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r2, r3] | max] }}"]),
    ("dongle NTP: the text is not read", "{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3] | max] }}", ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r3] | max] }}"]),
    ("dongle NTP: the age is not read", "{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3] | max] }}", ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2] | max] }}"]),
    ("dongle NTP: the best of its rules, not the worst", "{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3] | max] }}", ["{{ ['TRUSTED', 'DEGRADED', 'UNKNOWN', 'UNTRUSTED'][[r1, r2, r3] | min] }}"]),
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
    ("inverter clock: the difference is not read", STATE_MAX, ["[[rf, rm, rs, rc, ry, ra] | max]"]),
    ("inverter clock: the failure counter is not read", STATE_MAX, ["[[rd, rm, rs, rc, ry, ra] | max]"]),
    ("inverter clock: the maximum error is not read", STATE_MAX, ["[[rd, rf, rs, rc, ry, ra] | max]"]),
    ("inverter clock: the stall helper is not read", STATE_MAX, ["[[rd, rf, rm, rc, ry, ra] | max]"]),
    ("inverter clock: the correction helper is not read", STATE_MAX, ["[[rd, rf, rm, rs, ry, ra] | max]"]),
    ("inverter clock: the synced flag is not read", STATE_MAX, ["[[rd, rf, rm, rs, rc, ra] | max]"]),
    ("inverter clock: the text age is not read", STATE_MAX, ["[[rd, rf, rm, rs, rc, ry] | max]"]),
    ("inverter clock: a difference that is not finite still counts as read", "and (d | abs) < 1000000000", [""]),
    ("inverter clock: a failure counter that is not finite still counts as read", "and f < 1000000000", [""]),
    ("inverter clock: a maximum error that is not finite still counts as read", "and m < 1000000000", [""]),
    ("inverter clock: a difference that is not a number counts as read", "(d is number and (d | abs) < 1000000000)", ["((d | abs) < 1000000000)"]),
    ("inverter clock: a failure counter that is not a number counts as read", "(f is number and f >= 0", ["(f >= 0"]),
    ("inverter clock: a maximum error that is not a number counts as read", "(m is number and m >= 0", ["(m >= 0"]),
    # ---- the two debounce helpers
    ("stall helper: no delay (a 60 s episode trips it)", '        delay_on: "00:10:00"\n', [""]),
    ("stall helper: a 9 minute delay", 'delay_on: "00:10:00"', ['delay_on: "00:09:00"']),
    ("stall helper: an 11 minute delay", 'delay_on: "00:10:00"', ['delay_on: "00:11:00"']),
    ("stall helper: a 2 minute delay", 'delay_on: "00:10:00"', ['delay_on: "00:02:00"']),
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
    ("the header no longer says that nothing is wired to a gate", "nothing reads it yet", ["something reads it"], None, True),
    ("the header no longer says how a consumer must read it", "HOW A CONSUMER MUST READ IT", ["NOTE"], None, True),
    ("the header drops the limit that the sync flag never clears", "flag never clears after", ["flag clears when NTP is lost, after"], None, True),
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
    found = battery(mutated, mode="kill")
    if found:
        killed += 1
        print(f"  PASS  mutant caught: {label} ({found[0][:90]})")
    else:
        survived += 1
        survivors.append(label)
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{total} mutants (every threshold on both sides, every unreadable-input branch, the debounce delays and availability, every term of each worst-of, the ranks of the overall state, "
      f"every consumer's allow-list, the reasons, and what the package must never contain): all caught", killed == total and total >= 150, f"{killed}/{total} {survivors[:3]}")
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
