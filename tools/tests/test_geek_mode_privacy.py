#!/usr/bin/env python3
"""Geek Mode privacy and honesty scan: nothing committed for the Geek Mode proof is secret-like, private-looking or a real measured
value, and the scanners themselves are proven (negative controls).

  [1] negative controls: every scanner below flags an injected sample of its kind (the samples are assembled at run time, so this
      file itself holds no secret-shaped text)
  [2] STRICT targets (the catalogue, the ledger, the live shape listing, the intelligence fixtures and their meta file): zero hits
      for every scanner: no secret-like, private or blob-like value, no address, no coordinates, no entity id outside the contract
  [3] the live shape listing holds NAMES, TYPES and SIZES only: no value, no measured age
  [4] no real measured value: every timestamp in the fixtures is a fictional 2030 one; the catalogue and ledger hold no timestamp
  [5] the noise fixture: the decoys are exactly the expected ones (marked synthetic, below the repository scanners' thresholds) and
      the repository's own secret, address, e-mail and path scanners still find nothing in it
  [6] every file of the proof (tools, tests, docs, data): the repository's public privacy patterns find nothing; plain ASCII, LF only,
      no control characters, no mojibake marker

Test-only, no network. Reads the committed files; the scan list is explicit, so a stray __pycache__ cannot matter.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geek_scratch import ROOT, check, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
import geek_mode_coverage as G  # noqa: E402

# ---- the scanners: the repository's public privacy patterns (tools/tests/test_public_privacy.py), then stricter ones for the data ----
RFC1918 = re.compile(r"(?<![0-9.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![0-9.])")
MAC = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")
USER_PATH = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}(?!<)[^\\/\s'\"<>]+|/[cC]/Users/[^/\s'\"<>]+|(?<![A-Za-z])/Users/[a-z][^/\s'\"<>]*/")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"(@users\.noreply\.github\.com|^noreply@anthropic\.com|@example\.(com|org|net)|\.(invalid|test|example|localhost))$", re.I)
SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}|\bAKIA[0-9A-Z]{16}\b"
                    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bsk-[A-Za-z0-9]{32,}|\bsk-ant-[A-Za-z0-9_-]{20,}"
                    r"|eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")
JWT_LOOSE = re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*")
IPV4 = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
HEX_BLOB = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
B64_BLOB = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")
URL_USERINFO = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@\"']+:[^/\s@\"']+@")
URL_TOKEN_QS = re.compile(r"[?&](?:token|access_token|api_key|apikey|key|secret|password|sig|signature)=[^&\s\"']+", re.I)
COORD = re.compile(r"[\"'](?:latitude|longitude|lat|lon|lng)[\"']\s*:\s*-?\d", re.I)
DATE = re.compile(r"(?<!\d)(?:19|20)\d\d-\d\d-\d\d(?!\d)")
ENTITY = re.compile(r"(?<![A-Za-z0-9_.])(?:sensor|binary_sensor|input_boolean|input_number|automation|light|switch|climate|device_tracker|update|script|media_player)\.(?!py\b)[a-z0-9_]*[a-z0-9]\b(?!_)")

ALL = {"private IPv4": RFC1918, "MAC": MAC, "user path": USER_PATH, "token or key shape": SECRET, "JWT-like": JWT_LOOSE, "IPv4": IPV4,
       "long hex": HEX_BLOB, "long base64": B64_BLOB, "URL with userinfo": URL_USERINFO, "token in a URL": URL_TOKEN_QS, "coordinates": COORD}


def hits(text: str, pat: re.Pattern, ok=None) -> list[str]:
    return [m.group(0) for m in pat.finditer(text) if not (ok and ok(m.group(0)))]


def email_hits(text: str) -> list[str]:
    return [m.group(0) for m in EMAIL.finditer(text) if not EMAIL_OK.search(m.group(0))]


# ===========================================================================
print("[1] negative controls (samples assembled at run time)")
# ===========================================================================
samples = {
    "private IPv4": "host " + ".".join(["192", "168", "1", "20"]),
    "MAC": "id " + ":".join(["a1", "b2", "c3", "d4", "e5", "f6"]),
    "user path": "C:" + "\\" + "Users" + "\\" + "someone" + "\\" + "x",
    "token or key shape": "ghp_" + "a" * 36,
    "JWT-like": "eyJ" + "a" * 12 + "." + "eyJ" + "b" * 12 + "." + "c" * 12,
    "IPv4": "peer " + ".".join(["198", "51", "100", "9"]),
    "long hex": "0123456789abcdef" * 3,
    "long base64": "QUJD" * 12,
    "URL with userinfo": "mqtt://" + "user" + ":" + "pw" + "@" + "broker.example.invalid",
    "token in a URL": "https://x.example.invalid/a?" + "token" + "=" + "abc",
    "coordinates": '"' + "latitude" + '": 51.5',
}
for kind, text in samples.items():
    check(f"the {kind} scanner flags an injected sample", bool(hits(text, ALL[kind])))
check("the e-mail scanner flags a personal address and accepts a no-reply and an example one",
      bool(email_hits("a " + "someone" + "@" + "gmail" + ".com")) and not email_hits("a noreply" + "@" + "anthropic.com b x" + "@" + "host.example.invalid"))
check("the private-key block is flagged", bool(hits("-----BEGIN " + "RSA PRIVATE KEY-----", SECRET)))
check("the entity-id scanner finds ids", ENTITY.findall("x sensor.abc_1 y") == ["sensor.abc_1"])
check("the date scanner finds a date", bool(DATE.findall("on 2026-11-14 it")))
check("a clean text has no hit for any scanner", not any(hits("nothing to see: version 0.1.0, 60 s, 80 %", p) for p in ALL.values()) and not email_hits("nothing"))

# ===========================================================================
print("")
print("[2] strict targets: zero hits for every scanner")
# ===========================================================================
CATD = ROOT / "frontend" / "ecco-mode-shell" / "catalogue"
FXD = ROOT / G.FIXTURE_DIR_REL
STRICT = [CATD / "intelligence.catalogue.json", CATD / "intelligence.ledger.json", CATD / "live-shape.intelligence.json",
          ROOT / G.LEDGER_MD_REL] + [FXD / f"intelligence.states.{n}.json" for n in G.FIXTURE_NAMES] + [FXD / "intelligence.states.meta.json"]
led = json.loads((CATD / "intelligence.ledger.json").read_text(encoding="utf-8"))
digests = {led["catalogue_sha256"], led["live_shape_sha256"], *led["fixtures_sha256"].values()}
check("every strict target exists", all(p.is_file() for p in STRICT), str([p.name for p in STRICT if not p.is_file()]))
for p in STRICT:
    t = p.read_text(encoding="utf-8")
    is_ledger = p.name.startswith("intelligence.ledger") or p.name.startswith("GEEK_MODE_COVERAGE_LEDGER")
    bad = []
    for kind, pat in ALL.items():
        ok = (lambda h: h in digests) if (is_ledger and kind in ("long hex", "long base64")) else None
        bad += [f"{kind}: {h[:24]}" for h in hits(t, pat, ok)]
    bad += [f"e-mail: {h}" for h in email_hits(t)]
    check(f"{p.name}: no secret-like, private, blob-like, address or coordinate text (ledger: only its own sha256 digests)", not bad, str(bad[:3]))
catalogue_entities = {s["entity_id"] for s in json.loads((CATD / "intelligence.catalogue.json").read_text(encoding="utf-8"))["sources"]}
extras_ok = {"sensor.ecco_intel_future_probe", "binary_sensor.ecco_intel_future_flag", "automation.ecco_intel_alert_future_check",
             "input_number.ecco_intel_future_knob", "sensor.ecco_intelligence_status", "sensor.xecco_intel_foo", "sensor.ecco_intel",
             "light.ecco_intel_lamp", "sensor.ecco_other_thing"}
for p in STRICT:
    if p.name.endswith("meta.json") and False:
        continue
    t = p.read_text(encoding="utf-8")
    found = set(ENTITY.findall(t))
    stray = sorted(e for e in found if e not in catalogue_entities and e not in extras_ok and not e.startswith(("sensor.ecco_intelligence_decoy",)))
    check(f"{p.name}: every entity id in it is a catalogued contract entity or one of the deliberate synthetic extras (no site entity id)", not stray, str(stray[:4]))

# ===========================================================================
print("")
print("[3] the live shape listing: names, types and sizes only")
# ===========================================================================
shape = json.loads((CATD / "live-shape.intelligence.json").read_text(encoding="utf-8"))
check("the listing's top level is the provenance note and the entity list, nothing else (no total, no count of other entities)", set(shape) == {"_provenance", "ecco_intel"})
check("the provenance says it holds no value and what was removed", "no state value" in shape["_provenance"]["what"] and any("age_s" in x for x in shape["_provenance"]["removed_from_the_raw_listing"]))
row_keys_ok = all(set(r) == {"entity_id", "state_type", "state_len", "attributes"} for r in shape["ecco_intel"])
attr_keys_ok = all(set(a) == {"type", "bytes", "top_keys"} for r in shape["ecco_intel"] for a in r["attributes"].values())
check("each entity has only entity_id, state_type, state_len, attributes; each attribute only type, bytes, top_keys", row_keys_ok and attr_keys_ok)
check("every type is a type name (str, int, float, bool, null, list[n], dict[n]), never a value",
      all(re.fullmatch(r"str|int|float|bool|null|(list|dict)\[\d+\]", a["type"]) for r in shape["ecco_intel"] for a in r["attributes"].values()))
check("top_keys hold key NAMES (identifiers) only", all(re.fullmatch(r"[A-Za-z0-9_-]+", k) for r in shape["ecco_intel"] for a in r["attributes"].values() for k in (a["top_keys"] or [])))
check("no measured age and no timestamp in the listing (one capture date in the provenance note only)", "age_s" not in json.dumps(shape["ecco_intel"])
      and len(DATE.findall(json.dumps(shape))) == 1)

# ===========================================================================
print("")
print("[4] no real measured value")
# ===========================================================================
for n in G.FIXTURE_NAMES:
    t = (FXD / f"intelligence.states.{n}.json").read_text(encoding="utf-8")
    d = DATE.findall(t)
    check(f"fixture {n}: every date is in the fictional year 2030", d and all(x.startswith("2030-") for x in d), str(set(d)))
for p in (CATD / "intelligence.catalogue.json", CATD / "intelligence.ledger.json", ROOT / G.LEDGER_MD_REL):
    check(f"{p.name}: no date or timestamp at all (a catalogue and a ledger hold no measurement)", not DATE.findall(p.read_text(encoding="utf-8")))
fxt = {n: json.loads((FXD / f"intelligence.states.{n}.json").read_text(encoding="utf-8")) for n in G.FIXTURE_NAMES}
check("no fixture carries coordinates or a location", not any(re.search(r"latitude|longitude|location", json.dumps(s)) for s in fxt.values()))
sy = {s["attributes"].get("integration_version") for s in fxt["healthy"].values() if "integration_version" in s["attributes"]}
check("versions and revisions in the fixtures are the contract fixtures' invented ones (a fixture version, a 7-zero revision, a placeholder fingerprint)",
      sy == {"0.1.0-fixture"} and fxt["healthy"]["sensor.ecco_intel_status"]["attributes"]["git_sha"] == "0000000"
      and fxt["healthy"]["sensor.ecco_intel_status"]["attributes"]["config_hash"] == "fixture00000hash")
check("the healthy fixture's reason codes say it is synthetic", "SYNTHETIC_FIXTURE" in fxt["healthy"]["sensor.ecco_intel_status"]["attributes"]["reason_codes"])
check("the meta file says everything is synthetic", "SYNTHETIC" in json.loads((FXD / "intelligence.states.meta.json").read_text(encoding="utf-8"))["note"])

# ===========================================================================
print("")
print("[5] the noise fixture's decoys")
# ===========================================================================
nt = (FXD / "noise.states.json").read_text(encoding="utf-8")
check("the repository's own scanners find nothing in the noise fixture: no private address, MAC, user path, token shape, private-key block, e-mail",
      not hits(nt, RFC1918) and not hits(nt, MAC) and not hits(nt, USER_PATH) and not hits(nt, SECRET) and not email_hits(nt))
jwt = hits(nt, JWT_LOOSE)
check("exactly the two JWT-shaped decoys (a state and a key name), both the same synthetic text", len(jwt) == 2 and len(set(jwt)) == 1, str(jwt))
check("the JWT-shaped decoy decodes to a synthetic placeholder, not a credential",
      __import__("base64").urlsafe_b64decode(jwt[0].split(".")[1] + "==") == b'{"synthetic":1}')
ips = hits(nt, IPV4)
check("the only address is from the documentation range 203.0.113.0/24 (twice: state and attribute)", len(ips) == 2 and set(ips) == {"203.0.113.7"}, str(ips))
check("long hex blobs are exactly the three synthetic ones (64, 64 and a 48-character key name)", sorted(len(h) for h in hits(nt, HEX_BLOB)) == [48, 64, 64])
b64 = [h for h in hits(nt, B64_BLOB) if not re.fullmatch(r"[0-9A-Fa-f]+", h)]
check("one long base64 decoy (the hex blobs aside), which decodes to a synthetic placeholder", len(b64) == 1
      and b"SYNTHETIC" in __import__("base64").b64decode(b64[0]), str(b64))
ui = hits(nt, URL_USERINFO)
check("userinfo URLs are exactly the two synthetic connection strings on a non-routable host", len(ui) == 2 and all("synthetic:decoy@" in x for x in ui), str(ui))
check("one token-in-a-URL decoy, marked synthetic", len(hits(nt, URL_TOKEN_QS)) == 1 and "SYNTHETIC-DECOY" in hits(nt, URL_TOKEN_QS)[0])
check("coordinates appear once each, as the invented pair 1.2345 / 5.4321", len(hits(nt, COORD)) == 2 and '"latitude": 1.2345' in nt and '"longitude": 5.4321' in nt)
from urllib.parse import urlsplit  # noqa: E402
hosts = [urlsplit(u).hostname for u in re.findall(r"[a-z][a-z0-9+.-]*://[^\s\"']+", nt)]
check("every URL host in the noise is on a reserved name (.invalid)", hosts and all(h and h.endswith(".invalid") for h in hosts), str(hosts))
decoy_values = re.findall(r"SYNTHETIC-DECOY-\d{4}[\w-]*", nt)
check("twelve numbered synthetic decoy values, all marked SYNTHETIC-DECOY", len(set(decoy_values)) == 12, str(len(set(decoy_values))))

# ===========================================================================
print("")
print("[6] every file of the proof")
# ===========================================================================
PROOF = ["tools/geek_mode_coverage.py", "tools/geek_mode_texts_intelligence.py", "tools/gen_geek_fixtures.py", "tools/tests/_geek_scratch.py",
         "tools/tests/test_geek_mode_catalogue.py", "tools/tests/test_geek_mode_coverage.py", "tools/tests/test_geek_mode_ledger.py",
         "tools/tests/test_geek_mode_fixtures.py", "tools/tests/test_geek_mode_privacy.py", G.LEDGER_MD_REL, "docs/product-ui/PRODUCTION_GEEK_MODE.md"]
PROOF += [str(p.relative_to(ROOT)).replace("\\", "/") for p in STRICT] + [str((FXD / "noise.states.json").relative_to(ROOT)).replace("\\", "/")]
PROOF = sorted(set(PROOF))
check("every file of the proof exists", all((ROOT / r).is_file() for r in PROOF), str([r for r in PROOF if not (ROOT / r).is_file()]))
for rel in PROOF:
    if not (ROOT / rel).is_file():
        continue
    raw = (ROOT / rel).read_bytes()
    t = raw.decode("utf-8", "replace")
    bad = []
    if not raw.isascii():
        bad.append("not ASCII")
    if b"\r" in raw:
        bad.append("CR")
    if not raw.endswith(b"\n"):
        bad.append("no final newline")
    if any(ord(c) < 32 and c not in "\t\n" for c in t):
        bad.append("control character")
    if any(m in t for m in (chr(0x00C2), chr(0x00C3), chr(0xFFFD))):
        bad.append("mojibake marker")
    if rel.endswith((".py", ".md")) and re.search(r"[ \t]+\n", t):
        bad.append("trailing whitespace")
    check(f"{rel}: plain ASCII, LF, final newline, no control character, no mojibake marker", not bad, ", ".join(bad))
    if not rel.endswith("test_geek_mode_privacy.py"):
        pub = hits(t, RFC1918) + hits(t, MAC) + hits(t, USER_PATH) + hits(t, SECRET) + email_hits(t)
        check(f"{rel}: the repository's public privacy patterns find nothing (no private address, MAC, user path, secret, personal e-mail)", not pub, str(pub[:2]))
check("the privacy suite itself holds no secret-shaped literal (it assembles its samples)", not any(
    hits((ROOT / "tools/tests/test_geek_mode_privacy.py").read_text(encoding="utf-8"), p) for p in (RFC1918, MAC, USER_PATH, SECRET)) and not email_hits(
        (ROOT / "tools/tests/test_geek_mode_privacy.py").read_text(encoding="utf-8")))
print(f"  info  {len(PROOF)} files scanned; ledger digests allowed: {len(digests)}; sha256 of the catalogue {hashlib.sha256((CATD / 'intelligence.catalogue.json').read_bytes()).hexdigest()[:12]}...")

finish()
