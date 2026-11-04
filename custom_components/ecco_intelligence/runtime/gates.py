"""The start-up gates (no homeassistant import; pure: every byte they judge is read by store.py and handed in).

    mode_gate        the integration's mode is the constant SHADOW (anything else REFUSES SETUP, see __init__.py)
    tz_gate          ZoneInfo('Europe/London') loads and its clock changes are the known ones (25 h on 25 Oct 2026, 23 h on
                     28 Mar 2027; the BST / GMT offsets either side)
    load_site        /config/ecco/intelligence/site.local.json is UTF-8 JSON whose top level is a JSON object and which
                     holds no non-finite number (NaN, Infinity, or a literal beyond the double range such as 1e999);
                     the SITE_FILE FAIL text names which rule refused it, never a value (A49, P2); its `decisions` block
                     loads with DecisionSet.from_mapping(..., source='site_local') (the only way the runtime ever
                     obtains decisions);
                     its `shadow_runtime` entity map is strict; the V1 `sources` / `forecasts` give the history plan; the
                     reserve hints in `site` are ignored by the SHADOW path (INFO SITE_HINT_IGNORED)
    vendor_gate      the kit's VENDOR_MANIFEST.json matches the sha256 of every vendored module and integration file in place
    versions_check   the Home Assistant version and what can be said about the Python version (recorded, never a gate)

A check's text names a code, a field path or an exception type, never a value from the site file (an entity id, a key, a
record reference) and never an exception message: the texts reach the status entity and the diagnostics download. What the
owner needs to find the offending value is kept in SiteLoad.details, which only the coordinator's debug log line shows.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Mapping
from zoneinfo import ZoneInfo

from intelligence.advisory_contract import MODE, SiteFacts
from intelligence.config import SiteConfig
from intelligence.periods import AUTUMN_BACK, SPRING_FORWARD, period_profile
from intelligence.site_decisions import DecisionSet, DecisionStatus, site_hints_ignored

from . import history_source, sources
from .selftest import FAIL, INFO, PASS, WARN, Check

REQUIRED_MODE = "SHADOW"
SITE_TZ = "Europe/London"
MANIFEST_SCHEMA = "ecco-intel-vendor-manifest/1"
UTC = timezone.utc


def mode_gate(mode: object, entry_mode: object = None) -> Check:
    """PASS only for the constant SHADOW (the contract's MODE) with no other mode stored on the config entry."""
    ok = mode == REQUIRED_MODE and MODE == REQUIRED_MODE and entry_mode in (None, REQUIRED_MODE)
    return Check("MODE_SHADOW", PASS if ok else FAIL,
                 "mode is SHADOW" if ok else f"mode {mode!r} / entry mode {entry_mode!r} is not SHADOW: setup is refused")


def tz_gate(tz_name: str = SITE_TZ) -> Check:
    """The zone loads, and the UK clock changes of 2026 / 2027 come out as the fixtures say."""
    try:
        z = ZoneInfo(tz_name)
        offsets = [datetime(2026, 10, 25, 0, 30, tzinfo=UTC).astimezone(z).utcoffset(),
                   datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(z).utcoffset(),
                   datetime(2027, 3, 28, 0, 30, tzinfo=UTC).astimezone(z).utcoffset(),
                   datetime(2027, 3, 28, 1, 30, tzinfo=UTC).astimezone(z).utcoffset()]
        autumn = period_profile(date(2026, 10, 25), 0, 1440, tz_name)
        spring = period_profile(date(2027, 3, 28), 0, 1440, tz_name)
    except Exception as exc:  # noqa: BLE001 - a zone that cannot be loaded or measured is a failed gate, never a crash
        return Check("TZ_EUROPE_LONDON", FAIL, f"the zone {tz_name} cannot be used: {type(exc).__name__}")
    hour, zero = timedelta(hours=1), timedelta(0)
    ok = (offsets == [hour, zero, zero, hour] and autumn.actual_h == 25.0 and autumn.change_kind == AUTUMN_BACK
          and spring.actual_h == 23.0 and spring.change_kind == SPRING_FORWARD)
    return Check("TZ_EUROPE_LONDON", PASS if ok else FAIL,
                 "the zone loads; 25 h and 23 h days as expected" if ok else "the zone's clock changes are not the known ones")


class _NonFinite(ValueError):
    """A number the site file holds that is not a finite double: NaN, Infinity or -Infinity (not JSON), or a literal
    beyond the double range (1e999, or an integer too large for a double or past Python's integer digit limit), which
    json would read as an infinity or as a number no float holds."""


_JSON_TYPES = ((bool, "true or false"), (list, "an array"), (str, "a string"), (int, "a number"), (float, "a number"))
_UTF8_BOM = b"\xef\xbb\xbf"


def _reject_constant(_name: str) -> float:
    raise _NonFinite()


def _finite_float(text: str) -> float:
    v = float(text)
    if not math.isfinite(v):
        raise _NonFinite()
    return v


def _finite_int(text: str) -> int:
    try:
        v = int(text)                 # json passes digits only: a ValueError here is Python's integer digit limit
        float(v)
    except (ValueError, OverflowError):
        raise _NonFinite() from None
    return v


def _site_json(raw: bytes) -> tuple[Mapping | None, str]:
    """(the site file's JSON object, the SITE_FILE PASS text) or (None, the FAIL text). The FAIL text says which rule
    refused the file (a UTF-8 byte-order mark, not UTF-8 JSON, not a JSON object, a non-finite number) and names no value,
    key or position from it (P2): a JSON syntax error, a non-UTF-8 byte or a nesting too deep to read gives its exception
    type only. A file that starts with a UTF-8 byte-order mark (what Windows PowerShell 5.1 writes for `-Encoding utf8`)
    was never accepted (JSON text has none); its FAIL text says so (RR1-5)."""
    if raw.startswith(_UTF8_BOM):
        return None, "the site file starts with a UTF-8 byte-order mark (save it without one)"
    try:
        loaded = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, parse_float=_finite_float,
                            parse_int=_finite_int)
    except _NonFinite:
        return None, "the site file holds a non-finite number (NaN, Infinity or out of range)"
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return None, f"the site file is not valid JSON: {type(exc).__name__}"
    if not isinstance(loaded, dict):
        kind = next((name for t, name in _JSON_TYPES if isinstance(loaded, t)), "null")
        return None, f"the site file is JSON but not a JSON object (its top level is {kind})"
    return loaded, "the site file is a JSON object"


@dataclass(frozen=True)
class SiteLoad:
    """What the site file gives the runtime. decisions is None only when the file is unusable (then a FAIL is recorded)."""
    profile: Mapping | None
    decisions: DecisionSet | None
    entity_map: sources.EntityMap
    plan: history_source.HistoryPlan
    site_facts: SiteFacts
    base_cfg: SiteConfig
    config_hash: str | None
    checks: tuple[Check, ...]
    details: tuple[tuple[str, str], ...] = ()     # (check code, detail with the offending value): a debug log line only


def _facts(profile: Mapping | None, latitude: object, longitude: object) -> tuple[SiteFacts, SiteConfig]:
    """Site facts only (never the example battery values): the PV array size from the site file, the location from Home
    Assistant's own configuration, the zone Europe/London."""
    def fin(v: object) -> float | None:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
    site = profile.get("site") if isinstance(profile, Mapping) else None
    kwp = fin(site.get("pv_array_kwp")) if isinstance(site, Mapping) else None
    kwp = kwp if kwp is not None and kwp > 0 else None
    lat, lon = fin(latitude), fin(longitude)
    lat = lat if lat is not None and -90.0 <= lat <= 90.0 else None
    lon = lon if lon is not None and -180.0 <= lon <= 180.0 else None
    facts = SiteFacts(pv_array_kwp=kwp, latitude=lat, longitude=lon, tz=SITE_TZ)
    if lat is not None and lon is not None:
        return facts, SiteConfig(tz=SITE_TZ, pv_array_kwp=kwp, latitude=lat, longitude=lon)
    return facts, SiteConfig(tz=SITE_TZ, pv_array_kwp=kwp)


def load_site(raw: bytes | None, read_problem: str | None = None, *, latitude: object = None,
              longitude: object = None) -> SiteLoad:
    checks: list[Check] = []
    details: list[tuple[str, str]] = []
    profile: Mapping | None = None
    decisions: DecisionSet | None = None
    emap = sources.EMPTY_MAP
    config_hash = None if raw is None else hashlib.sha256(raw).hexdigest()[:16]
    if raw is None:
        checks.append(Check("SITE_FILE", FAIL, read_problem or "ecco/intelligence/site.local.json is missing"))
    else:
        profile, text = _site_json(raw)
        checks.append(Check("SITE_FILE", PASS if profile is not None else FAIL, text))
    if profile is not None:
        block = profile.get("decisions")
        try:
            decisions = DecisionSet.from_mapping(block if block is not None else {}, source="site_local")
            if block is None:
                checks.append(Check("SITE_DECISIONS", WARN, "no decisions block: every I-D decision is OPEN"))
            else:
                invalid = [k for k, v in decisions.status_map().items() if v == DecisionStatus.INVALID]
                checks.append(Check("SITE_DECISIONS", WARN if invalid else PASS,
                                    ("INVALID (each blocks what it gates): " + ", ".join(invalid)) if invalid
                                    else "the decisions block loads (site_local)"))
        except ValueError as exc:
            decisions = None
            # the published text is cut at 80 characters: the short form fits
            checks.append(Check("SITE_DECISIONS", FAIL, "refused: unknown key, repeated id or malformed entry (detail in "
                                                        "the debug log)"))
            details.append(("SITE_DECISIONS", str(exc)))
        try:
            emap = sources.parse_entity_map(profile)
            checks.append(Check("SITE_ENTITY_MAP", PASS if emap.present else WARN,
                                f"{len(emap.entity_ids())} mapped entities" if emap.present
                                else "no shadow_runtime block: no live input is mapped (every gated item BLOCKS)"))
        except sources.EntityMapError as exc:
            emap = sources.EMPTY_MAP
            checks.append(Check("SITE_ENTITY_MAP", FAIL, f"refused: {exc.public}"))       # the field path comes first
            details.append(("SITE_ENTITY_MAP", exc.detail))
        except ValueError as exc:
            emap = sources.EMPTY_MAP
            checks.append(Check("SITE_ENTITY_MAP", FAIL, f"refused ({type(exc).__name__}; detail in the debug log)"))
            details.append(("SITE_ENTITY_MAP", str(exc)))
        for f in site_hints_ignored(profile.get("site")):
            checks.append(Check(f"{f.code}_{f.subject.split('.')[-1].upper()}"[:64], INFO, f.text))
    plan = history_source.plan_history(profile)
    if profile is not None:
        checks.append(Check("SITE_HISTORY_SOURCES", WARN if plan.problem or plan.skipped else PASS,
                            plan.problem or (f"{len(plan.skipped)} invalid statistic ids are never queried" if plan.skipped
                                             else f"{len(plan.statistic_ids)} statistic ids")))
    facts, cfg = _facts(profile, latitude, longitude)
    return SiteLoad(profile, decisions, emap, plan, facts, cfg, config_hash, tuple(checks), tuple(details))


def manifest_paths(manifest_raw: bytes | None) -> tuple[dict | None, dict[str, str], str | None]:
    """(manifest, {package-relative path: expected sha256}, problem)."""
    if manifest_raw is None:
        return None, {}, "VENDOR_MANIFEST.json is missing (not a built kit)"
    try:
        man = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, {}, "VENDOR_MANIFEST.json is not valid JSON"
    if not isinstance(man, dict) or man.get("schema") != MANIFEST_SCHEMA:
        return None, {}, "VENDOR_MANIFEST.json has an unknown schema"
    want: dict[str, str] = {}
    try:
        for m in man["modules"]:
            want[m["output"]] = m["output_sha256"]
        for f in man["integration_files"]:
            want[f["path"]] = f["output_sha256"]
    except (KeyError, TypeError):
        return None, {}, "VENDOR_MANIFEST.json is malformed"
    if not want or any(not isinstance(k, str) or not isinstance(v, str) for k, v in want.items()):
        return None, {}, "VENDOR_MANIFEST.json lists no file"
    return man, want, None


def vendor_gate(manifest: dict | None, want: Mapping[str, str], actual: Mapping[str, str | None],
                problem: str | None) -> Check:
    if problem is not None or manifest is None:
        return Check("VENDOR_MANIFEST", FAIL, problem or "no vendor manifest")
    bad = sorted(p for p, sha in want.items() if actual.get(p) != sha)
    if bad:
        return Check("VENDOR_MANIFEST", FAIL, f"{len(bad)} of {len(want)} files differ from the kit manifest, e.g. {bad[0]}")
    return Check("VENDOR_MANIFEST", PASS, f"{len(want)} files match the kit manifest")


def python_feature_floor() -> str:
    """What the running Python provides, judged by features only (the runtime allowlist has no sys / platform):
    datetime.time.strptime is new in 3.14, copy.replace in 3.13. The exact version stays UNKNOWN here."""
    if hasattr(time, "strptime"):
        return ">=3.14"
    if hasattr(copy, "replace"):
        return "3.13"
    return "<3.13"


def versions_check(ha_version: object, required_python: object) -> Check:
    req = ".".join(str(x) for x in required_python) if isinstance(required_python, (tuple, list)) else str(required_python)
    return Check("VERSIONS", INFO, f"Home Assistant {ha_version}; HA requires Python >= {req}; features {python_feature_floor()}")
