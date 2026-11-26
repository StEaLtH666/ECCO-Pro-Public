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
from _geek_scratch import ROOT  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


sys.path.insert(0, str(ROOT / "tools"))
import geek_mode_coverage as G  # noqa: E402

# ---- the scanners: the repository's public privacy patterns (tools/tests/test_public_privacy.py), then stricter ones for the data ----
RFC1918 = re.compile(r"(?<![0-9.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![0-9.])")
MAC = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")
USER_PATH = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}(?!<)[^\\/\s'\"<>]+|/[cC]/Users/[^/\s'\"<>]+|(?<![A-Za-z])/Users/[a-z][^/\s'\"<>]*/")
# review round 8 (the NIT): the DOMAIN is not bounded at all (round 7 bounded it to 16 labels of 63 characters and a top-level domain of 24, and an address of 17 labels, or one label of 64 characters, was missed that the round-6
# form found). The local part keeps its bound of 64 (the RFC limit): a longer one still matches, from its last 64 characters, so nothing is missed, and a long run of local-part characters is not walked once per start. The domain
# starts at the at sign and is read once from each of the (at most 64) starts that reach it, so the scanner is linear.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"(@users\.noreply\.github\.com|^noreply@anthropic\.com|@example\.(com|org|net)|\.(invalid|test|example|localhost))$", re.I)
SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}|\bAKIA[0-9A-Z]{16}\b"
                    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bsk-[A-Za-z0-9]{32,}|\bsk-ant-[A-Za-z0-9_-]{20,}"
                    r"|(?<![A-Za-z0-9_-])(?>[A-Za-z0-9_-]*?eyJ)[A-Za-z0-9_-]{20,}+\.eyJ[A-Za-z0-9_-]{20,}+\.[A-Za-z0-9_-]{10,}")
# review round 8: NO BOUND ON A SEGMENT (round 7 bounded them to 512 and 4096 and a token with a longer first segment was missed). The match starts at the start of a RUN of token characters (so there is one start per run), takes the
# FIRST eyJ of the run in an atomic group (no later eyJ of the run has more characters after it, so a later one can never succeed where the first failed) and reads the rest of the run possessively (Python 3.11): every
# character is read once, whatever the length of a segment, and a text of eyJ-eyJ-eyJ- is not walked once per start. The same verdicts as the unbounded round-6 form (the differential check in [8]).
JWT_LOOSE = re.compile(r"(?<![A-Za-z0-9_-])(?>[A-Za-z0-9_-]*?eyJ)[A-Za-z0-9_-]{6,}+\.[A-Za-z0-9_-]{6,}+\.[A-Za-z0-9_-]*")
IPV4 = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
HEX_BLOB = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
B64_BLOB = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")
# review round 7: the scheme is not read as a run (one scheme character before :// is enough: a superset), so the pattern has one start per :// and is linear
URL_USERINFO = re.compile(r"[a-z0-9+.-]://[^/\s:@\"']+:[^/\s@\"']+@")
URL_TOKEN_QS = re.compile(r"[?&](?:token|access_token|api_key|apikey|key|secret|password|sig|signature)=[^&\s\"']+", re.I)
COORD = re.compile(r"[\"'](?:latitude|longitude|lat|lon|lng)[\"']\s*:\s*-?\d", re.I)
DATE = re.compile(r"(?<!\d)(?:19|20)\d\d-\d\d-\d\d(?!\d)")
ENTITY = re.compile(r"(?<![A-Za-z0-9_.])(?:sensor|binary_sensor|input_boolean|input_number|automation|light|switch|climate|device_tracker|update|script|media_player)\.(?!py\b)[a-z0-9_]*[a-z0-9]\b(?!_)")

# review round 1: a bearer / basic credential, a credential pair (plain or JSON quoted) and a webhook path were not scanned for: a generator
# that emitted one would have passed the privacy scan (only the regeneration drift check and the node suites would have noticed)
BEARER = re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}", re.I)
CRED_PAIR = re.compile(r"[\"']?\b(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization)\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"'{}]{3,}", re.I)
# review round 8: the host of the chat services form has no bound (round 7: {1,253}, and a longer host was missed). The first alternative is the card's, character for character. The second is the round-6 form
# hooks\.[a-z0-9.-]+/services/ read once: the match starts at the start of a run of host characters, takes the FIRST hooks. of the run in an atomic group and reads the rest of the run possessively, so hooks.hooks.hooks. is not
# walked once per start. The card writes the same verdict as a look-behind from /services/ (a variable-width look-behind that Python's re does not have); [8] proves each is the round-6 form.
WEBHOOK_PATH = re.compile(r"/api/webhook/[A-Za-z0-9_-]{8,}|(?<![a-z0-9.-])(?>[a-z0-9.-]*?hooks\.)[a-z0-9.-]++/services/[A-Za-z0-9/_-]{12,}", re.I)

# review round 3: the card withheld none of these under an innocent key, and no scanner here looked for them either, so a generator that emitted one would have
# passed this scan: a MAC address written with no separator or in the dotted form, a coordinate pair with three decimals, the text of a Wi-Fi QR code and a
# password written as a pass / pw pair
MAC_BARE = re.compile(r"(?<![0-9A-Za-z])(?=[0-9A-Fa-f]*[A-Fa-f])[0-9A-Fa-f]{12}(?![0-9A-Za-z])")
# review round 8: the letter is looked for anywhere in the run of hex digits and dots that the address starts (the round-6 verdict; round 7 looked in the fourteen characters of the address only, so 2026.1114.0900.beef was
# missed). This scanner needs no trick to stay linear: an address here starts where no letter, digit or dot stands before it, so there is one start per run and the look-ahead reads each run once.
MAC_DOTTED = re.compile(r"(?<![0-9A-Za-z.])(?=[0-9A-Fa-f.]*[A-Fa-f])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![0-9A-Za-z.])")
COORD_PAIR = re.compile(r"(?<![\d.])-?\d{1,3}\.\d{3,}\s*[,;]\s*-?\d{1,3}\.\d{3,}(?![\d.])")
WIFI_QR = re.compile(r"\bWIFI:[A-Z]:", re.I)
# review round 7: the unquoted form has no prefix of segments (a prefix such as wifi_ ends at a separator, so the key word is always preceded by a character that is not a letter or digit: the same verdicts, read once)
PASS_PAIR = re.compile(r"""["']\s*(?:[a-z0-9_-]*[_-])?(?:pass|pw)\s*["']\s*:\s*["']?[^\s,;"']{3,}|(?<![a-z0-9])(?:pass|pw)=["']?[^\s,;&"']{3,}""", re.I)
# review round 4: a MAC address written with a space between the six bytes (a reviewer's probe found the card showing one); at least one letter, as for the other bare forms
MAC_SPACED = re.compile(r"(?<![0-9a-f])(?=[0-9a-f ]{0,16}[a-f])(?:[0-9a-f]{2} ){5}[0-9a-f]{2}(?![0-9a-f])", re.I)

ALL = {"private IPv4": RFC1918, "MAC": MAC, "user path": USER_PATH, "token or key shape": SECRET, "JWT-like": JWT_LOOSE, "IPv4": IPV4,
       "long hex": HEX_BLOB, "long base64": B64_BLOB, "URL with userinfo": URL_USERINFO, "token in a URL": URL_TOKEN_QS, "coordinates": COORD,
       "bearer or basic credential": BEARER, "credential pair": CRED_PAIR, "webhook path": WEBHOOK_PATH,
       "MAC without separators": MAC_BARE, "MAC, dotted": MAC_DOTTED, "coordinate pair": COORD_PAIR, "Wi-Fi QR text": WIFI_QR, "pass or pw pair": PASS_PAIR,
       "MAC, spaced": MAC_SPACED}


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
    "bearer or basic credential": "Authori" + "zation: Bear" + "er " + "a" * 24,
    "credential pair": '{"' + "tok" + 'en": "' + "abc123" + '"}',
    "webhook path": "https://x.example.invalid/api/" + "webhook/" + "abcdefgh1234",
    "MAC without separators": "id " + "aabb" + "ccdd" + "eeff",
    "MAC, dotted": "id " + "aabb" + "." + "ccdd" + "." + "eeff",
    "coordinate pair": "at " + "51.507" + ", " + "-0.127",
    "Wi-Fi QR text": "WIFI" + ":S:" + "Home" + ";T:WPA;P:" + "x1y2z3" + ";;",
    "pass or pw pair": '{"pa' + 'ss": "' + "abc123" + '"}',
    "MAC, spaced": "id " + "aa bb" + " cc dd" + " ee ff",
}
for kind, text in samples.items():
    check(f"the {kind} scanner flags an injected sample", bool(hits(text, ALL[kind])))
check("[r1] the credential-pair scanner also flags the single-quoted, unquoted and equals-sign shapes, and the bearer scanner the Basic shape",
      all(hits(s, CRED_PAIR) for s in ("'" + "pass" + "word" + "': 'abc123'", "api" + "_key=abc123", "pass" + "word: abc123"))
      and bool(hits("Bas" + "ic " + "dXNlcjpwYXNzd29yZA==", BEARER)) and bool(hits("https://hooks.slack" + ".com/services/" + "T00000000/B00000000/abcdefghijkl", WEBHOOK_PATH)))
check("[r1] ordinary text near those words is not flagged (no hit on 'a token of thanks', 'password protected', 'basic setup', 'the webhook is off')",
      not any(hits(s, pat) for s in ("a token of thanks", "password protected: no", "a basic setup", "the webhook is off", "bearer of news", "secret: ") for pat in (BEARER, CRED_PAIR, WEBHOOK_PATH)))
check("the e-mail scanner flags a personal address and accepts a no-reply and an example one",
      bool(email_hits("a " + "someone" + "@" + "gmail" + ".com")) and not email_hits("a noreply" + "@" + "anthropic.com b x" + "@" + "host.example.invalid"))
check("the private-key block is flagged", bool(hits("-----BEGIN " + "RSA PRIVATE KEY-----", SECRET)))
check("the entity-id scanner finds ids", ENTITY.findall("x sensor.abc_1 y") == ["sensor.abc_1"])
check("the date scanner finds a date", bool(DATE.findall("on 2026-11-14 it")))
check("a clean text has no hit for any scanner", not any(hits("nothing to see: version 0.1.0, 60 s, 80 %", p) for p in ALL.values()) and not email_hits("nothing"))
# review round 2 (reviewer probe P11): the card withheld a webhook URL only under a key named like a secret, because it had no value rule while this scanner had one:
# the two sides disagreed. The card's rule is now the same pattern, and this check keeps it so.
_card_src = (ROOT / "frontend" / "ecco-mode-shell" / "ecco-mode-shell.js").read_text(encoding="utf-8")
_rule = re.search(r"\['webhook path', '/', /(.+)/i\],", _card_src)
# review round 8: the two sides still agree, but no longer by being the same text. The card's first alternative is this scanner's, character for character; the card's second is the round-6 form
# hooks\.HOST/services/TAIL with its head moved into a look-behind from /services/ (a variable-width look-behind: JavaScript has it, Python's re does not), and this scanner's second reads the same run once with an atomic
# group and a possessive quantifier (Python 3.11). That each is exactly the round-6 form is proved by the differential checks of [8] (here) and by test/differential.test.mjs (the card).
_R6_HEAD = r"hooks\.[a-z0-9.-]+"
_TAIL = r"/services/[A-Za-z0-9/_-]{12,}"
_card_alts = [] if _rule is None else _rule.group(1).replace("\\/", "/").split("|")
_py_alts = WEBHOOK_PATH.pattern.split("|")
check("[r2] the card's value rule for a webhook path and this scanner's pattern agree: the same first alternative, and a second that is the round-6 form (the host of any length) written by each side its own way",
      _rule is not None and len(_card_alts) == 2 and len(_py_alts) == 2 and _card_alts[0] == _py_alts[0]
      and _card_alts[1] == "(?<=" + _R6_HEAD + ")" + _TAIL and _py_alts[1] == r"(?<![a-z0-9.-])(?>[a-z0-9.-]*?hooks\.)[a-z0-9.-]++" + _TAIL, "" if _rule is None else _rule.group(1))
check("[r2] and the scanner flags the two shapes the card's hostile fixtures use (assembled here from fragments)",
      all(hits(s, WEBHOOK_PATH) for s in ("https://hooks.example.test/api/" + "webhook/" + "abcdef123456", "hooks.example.test/" + "services/" + "team-alpha/chan-beta/abcdefghijkl")))
# review round 3: the card's rules for a pass / pw pair and for the Wi-Fi QR text are these scanners' patterns, and each scanner flags what the card's hostile fixtures
# hold and leaves plain prose alone ("pass: true", a version number, twelve plain digits, a coarse pair)
for _name, _rx, _pat in (("pass pair", r"\['pass pair', null, /(.+)/i\],", PASS_PAIR), ("wifi credentials", r"\['wifi credentials', ':', /(.+)/i\],", WIFI_QR)):
    _m = re.search(_rx, _card_src)
    check(f"[r3] the card's value rule '{_name}' is this scanner's pattern (the two sides agree)", _m is not None and _m.group(1) == _pat.pattern, "" if _m is None else _m.group(1))
check("[r3] the scanners flag the shapes the card's round-three hostile fixtures use (assembled here from fragments)",
      all(hits(s, pat) for s, pat in (("wifi_pa" + "ss=hun" + "ter22x", PASS_PAIR), ("db-p" + 'w="hun' + 'ter22x"', PASS_PAIR), ("{'p" + "w': 'hun" + "ter22'}", PASS_PAIR),
                                      ("A1B2" + "C3D4" + "E5F6", MAC_BARE), ("aabb" + ".ccdd" + ".eeff", MAC_DOTTED), ("-33.865" + ";" + "151.209", COORD_PAIR),
                                      ("wifi" + ":T:WPA;S:" + "Home" + ";P:" + "hunter22" + ";;", WIFI_QR))))
check("[r3] and they leave look-alikes alone: 'pass: true', a version, twelve plain digits, a coarse pair, a pair with one fine number",
      not any(hits(s, pat) for s, pat in (("self-test pass: true", PASS_PAIR), ("pass: ok today", PASS_PAIR), ("2026.1114.0900", MAC_DOTTED), ("123456789012", MAC_BARE),
                                          ("51.5, -0.1", COORD_PAIR), ("1.250, 3.5", COORD_PAIR), ("wifi: connected", WIFI_QR), ("compass=north", PASS_PAIR))))
# review round 4: the card's rule for a MAC address written with spaces is this scanner's pattern, and the scanner flags it and leaves six numbers alone
_m = re.search(r"\['MAC address \(spaced\)', ' ', /(.+)/i\],", _card_src)
check("[r4] the card's value rule 'MAC address (spaced)' is this scanner's pattern (the two sides agree)", _m is not None and _m.group(1) == MAC_SPACED.pattern, "" if _m is None else _m.group(1))
check("[r4] the spaced-MAC scanner flags the shapes the card's round-four fixtures use (assembled from fragments) and leaves six numbers, a short run and long groups alone",
      all(hits(s, MAC_SPACED) for s in ("AA BB" + " CC DD" + " EE FF", "a1 b2 " + "c3 d4 " + "e5 f6", "seen on aa 1b cc " + "dd e5 07" + " today"))
      and not any(hits(s, MAC_SPACED) for s in ("10 20 30 40 50 60", "aa bb cc dd ee", "1aa bb cc dd ee ff", "aa bb cc dd ee fff", "aabb ccdd eeff", "at 10 11 12 13 14 15 hours")))

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
def strict_findings(t: str, is_ledger: bool) -> list[str]:
    bad = []
    for kind, pat in ALL.items():
        ok = (lambda h: h in digests) if (is_ledger and kind in ("long hex", "long base64")) else None
        bad += [f"{kind}: {h[:24]}" for h in hits(t, pat, ok)]
    bad += [f"e-mail: {h}" for h in email_hits(t)]
    return bad


_healthy_text = (FXD / "intelligence.states.healthy.json").read_text(encoding="utf-8")
_anchor = '"mode": "SHADOW"'
check("[r1] the strict scan reports a value injected into a fixture (a 24-character bearer value, a credential pair, a webhook path): it no longer depends on the drift check",
      _anchor in _healthy_text and all(strict_findings(_healthy_text.replace(_anchor, _anchor + ', "zz": "' + inj + '"', 1), False)
                                      for inj in ("Bear" + "er " + "q" * 24, "to" + "ken=" + "abc123def", "https://x.example.invalid/api/" + "webhook/" + "abcdefgh1234"))
      and not strict_findings(_healthy_text, False))
for p in STRICT:
    t = p.read_text(encoding="utf-8")
    is_ledger = p.name.startswith("intelligence.ledger") or p.name.startswith("GEEK_MODE_COVERAGE_LEDGER")
    bad = strict_findings(t, is_ledger)
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

# ===========================================================================
print("")
print("[7] review round 7: every scanner is linear in the text it reads (the card's value rules were quadratic on near-miss text, and so were some of these)")
# ===========================================================================
import time  # noqa: E402

# the near-miss units: the start of a match of some scanner (or a character it treats as a boundary) that never completes; a text is a unit repeated to the length asked
NEAR_MISS_UNITS = ["a.", "a-", "ab-", "a_", "0.", "1.1.", "0123.", ".1", "a.b", "a%", "a b", " ", "ab:cd:", "aa-aa-", "Ab1", "aB+/", "eyJ", "eyJ-", "-----BEGIN ", "a://", "a://u:p", "://", "?key=", "password  ", "token=", "Server=", "host=", "pass", "\"a_pass\"", "pass=", "a_a_a_pass=", "WIFI:", "Bearer ", "@", "a@a.", "a.b@", "1.2345,", "lat ", "/api/webhook/", "hooks.", "x.local", "aabb.ccdd.", "1234.5678.", "aa bb cc dd ee ", "a.b.c@d:/x=pass 0123.4567.89ab ", " .local @ x ", "0123.@", "u:p@", "b://c@"]
SCANNERS = dict(ALL)
SCANNERS["e-mail"] = EMAIL
PY_ABS_MS = 400.0
PY_GROWTH = 3.5


def _text(unit: str, n: int) -> str:
    return (unit * (n // len(unit) + 1))[:n]


def _least_ms(pat: re.Pattern, s: str, trials: int = 1) -> float:
    best = float("inf")
    for _ in range(trials):
        t0 = time.perf_counter()
        for _m in pat.finditer(s):
            pass
        best = min(best, (time.perf_counter() - t0) * 1000.0)
    return best


def linear_problems(pat: re.Pattern, units=NEAR_MISS_UNITS, retry: bool = True) -> list[str]:
    """The (unit, time, growth) of every near-miss text on which a pattern is slow or grows by more than 3.5 for twice the length (the minimum of several runs, looked at again before it is reported)."""
    bad = []
    for u in units:
        t10, t20 = _least_ms(pat, _text(u, 10000)), _least_ms(pat, _text(u, 20000))
        growth = t20 / max(t10, 0.05)
        if retry and growth > PY_GROWTH and t20 > 3.0:
            t10, t20 = _least_ms(pat, _text(u, 10000), 7), _least_ms(pat, _text(u, 20000), 7)
            growth = t20 / max(t10, 0.05)
        if t20 > PY_ABS_MS or (growth > PY_GROWTH and t20 > 3.0):
            bad.append(f"{u!r}: {t20:.1f} ms for 20000 characters, x{growth:.2f} for twice the length")
    return bad


slow = {name: linear_problems(pat) for name, pat in SCANNERS.items()}
for name, bad in slow.items():
    check(f"[r7] the {name} scanner is linear on every near-miss text (under {PY_ABS_MS:.0f} ms at 20000 characters, growth under {PY_GROWTH} for twice the length)", not bad, "; ".join(bad[:2]))
# the net can see a quadratic pattern: the round-6 form of the pass pair scanner (a prefix of segments walked from every start) is reported
_OLD_PASS = re.compile(r"""["']\s*(?:[a-z0-9_-]*[_-])?(?:pass|pw)\s*["']\s*:\s*["']?[^\s,;"']{3,}|(?<![a-z0-9])(?:[a-z0-9]+[_-])*(?:pass|pw)=["']?[^\s,;&"']{3,}""", re.I)
_OLD_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
check("[r7] negative control: the round-6 forms of the pass pair and e-mail scanners are reported by the same check (the check can see a quadratic pattern)",
      bool(linear_problems(_OLD_PASS, ["a-"], retry=False)) and bool(linear_problems(_OLD_EMAIL, ["a."], retry=False)))

# the changed scanners still match what the round-6 forms matched, on thousands of short texts (a deterministic corpus)
_REFERENCE = {
    "pass or pw pair": (_OLD_PASS, PASS_PAIR, "exact"),
    "webhook path": (re.compile(r"/api/webhook/[A-Za-z0-9_-]{8,}|hooks\.[a-z0-9.-]+/services/[A-Za-z0-9/_-]{12,}", re.I), WEBHOOK_PATH, "exact"),
    "e-mail": (_OLD_EMAIL, EMAIL, "exact"),
    "JWT-like": (re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*"), JWT_LOOSE, "exact"),
    "URL with userinfo": (re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@\"']+:[^/\s@\"']+@"), URL_USERINFO, "superset"),
    # review round 8: exact again (round 7 narrowed it, and 2026.1114.0900.beef was no longer found)
    "MAC, dotted": (re.compile(r"(?<![0-9A-Za-z.])(?=[0-9A-Fa-f.]*[A-Fa-f])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![0-9A-Za-z.])"), MAC_DOTTED, "exact"),
    # review round 8: the JWT form of the token-or-key-shape scanner, against its round-6 form (that scanner holds other alternatives too, so it may match MORE)
    "token or key shape (the JWT form)": (re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"), SECRET, "superset"),
}
_PIECES = {
    "pass or pw pair": ["pass", "pw", "\"", "'", ":", "=", " ", "_", "-", "wifi", "a", "abc", "hunter22", ",", ";", "&", "x1", "compass", "pass=hunter22", "wifi_pass=abc", "\"pass\": \"abc\""],
    "webhook path": ["/api/webhook/", "abcdefgh", "abc", "hooks.", "example", ".com", "/services/", "T01/B02/abcdefghijkl", ".", "-", "a", "/", " ", "x"],
    "e-mail": ["a", "b", "@", ".", "com", "org", "x", "-", "_", "+", "%", "1", " ", "co", "ab.cd", "!", ","],
    "JWT-like": ["eyJ", "eyJhbGci", "abcdefg", "abcdefgh", ".", "-", "_", " ", "x", "eyJabcdefg.", "abcdefgh.abcdefgh.", "eyJabcdefg.abcdefg."],
    "URL with userinfo": ["://", "https", "a", "ws", "1", "_", ".", "-", "+", "u", ":", "p", "@", "host", "/", "?", "#", " ", "A", "https://", "user:pw@h", "mqtt://"],
    "MAC, dotted": ["aabb", "1234", "ccdd", "eeff", "5678", "0900", ".", "ab", "a", "9", ".beef", " ", "AABB", "2026", "aabb.ccdd.eeff", "1234.5678.9abc", "a1b2.c3d4.", "2026.1114.0900"],
    "token or key shape (the JWT form)": ["eyJ", "eyJabcdefghijklmnopqrstuvwx", "abcdefghijklmnopqrstuvwxyz", ".", "-", "_", " ", "x", "eyJabcdefghijklmnopqrstuvwx.", "eyJabcdefghijklmnopqrstuvwx." + "eyJabcdefghijklmnopqrstuvwx." + "abcdefghijkl"],
}


def _corpus(name: str, n: int = 6000) -> list[str]:
    state = 0xC0FFEE + len(name) * 7919

    def rnd() -> float:
        nonlocal state
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        return state / 4294967296.0

    pieces = _PIECES[name]
    out = set()
    while len(out) < n:
        out.add("".join(pieces[int(rnd() * len(pieces))] for _ in range(1 + int(rnd() * 12))))
    return sorted(out)


for name, (old, new, kind) in _REFERENCE.items():
    corpus = _corpus(name)
    old_hits = [t for t in corpus if old.search(t)]
    lost = [t for t in old_hits if not new.search(t)]
    gained = [t for t in corpus if not old.search(t) and new.search(t)]
    check(f"[r7] the {name} scanner matches everything its round-6 form matched ({len(old_hits)} of {len(corpus)} texts), {'and nothing else' if kind == 'exact' else 'and only more (a scheme-less start)'}",
          len(old_hits) >= 100 and not lost and (kind == "superset" or not gained), f"lost {lost[:2]} gained {gained[:2]}")

# the scanners the card agrees with, and the numbers they share with it
_card_src = (ROOT / "frontend" / "ecco-mode-shell" / "ecco-mode-shell.js").read_text(encoding="utf-8")
# review round 8: the dotted MAC rule of the card is the round-6 verdict in two alternatives (a letter in the address, then a letter after it in the same run), this scanner's look-ahead has no bound
_m = re.search(r"\['MAC address \(dotted\)', '\.', /(.+)/i\],", _card_src)
check("[r8] the card's dotted MAC rule has the two alternatives (a letter inside the address, a letter after it in the same run) and no bound on the run, and this scanner looks for the letter in the whole run",
      _m is not None and "{0,13}" in _m.group(1) and "(?<=\\b[0-9a-f]{4}" in _m.group(1) and "[0-9a-f.]*[a-f])" in _m.group(1) and "(?=[0-9A-Fa-f.]*[A-Fa-f])" in MAC_DOTTED.pattern and "{0,13}" not in MAC_DOTTED.pattern, "" if _m is None else _m.group(1))
# review round 8: no segment of a JWT is bounded on either side (the card: a look-behind from the second dot; this scanner: a run read once)
_m = re.search(r"\['jwt', 'eyJ', /(.+)/\],", _card_src)
check("[r8] the card's JWT rule and this scanner have no bound on any segment", _m is not None and _m.group(1) == r"(?<=\beyJ[\w-]{4,}\.[\w-]{4,})\." and not re.search(r"\d,\d+\}", _m.group(1))
      and not re.search(r"\{\d+,\d+\}", JWT_LOOSE.pattern) and not re.search(r"\{\d+,\d+\}", SECRET.pattern.split("|(?<![A-Za-z0-9_-])")[-1]) and "{6,}+" in JWT_LOOSE.pattern, "" if _m is None else _m.group(1))
_m = re.search(r"LIMITS = Object\.freeze\(\{.*?entityChars: (\d+),", _card_src, re.S)
check("[r7] the card's scan budget is 100000 characters per entity (the number the design document gives)", _m is not None and _m.group(1) == "100000", "" if _m is None else _m.group(1))
_m = re.search(r"LIMITS = Object\.freeze\(\{.*?snapshotChars: (\d+),", _card_src, re.S)
check("[r8] the card's snapshot budget is 2000000 characters across all the entities of one snapshot (the number the design document gives)", _m is not None and _m.group(1) == "2000000", "" if _m is None else _m.group(1))

# ===========================================================================
print("")
print("[8] review round 8: THE DIFFERENTIAL GATE of the scanners (a scanner may be stricter than its round-6 form, never looser): every component of every kind swept from 1 to 1000 characters")
# ===========================================================================
# Round 7 bounded some scanners to make them linear, and a bounded scanner stops matching a secret whose COMPONENT is longer than its bound (an address of 17 labels, a token with a first segment of 600
# characters, a host of 260): the same class as the card's rules (test/differential.test.mjs). The corpus below is built the same way: one family per kind of secret, ONE component swept at every length from 1 to 300 and
# at 400, 600, 1000 and 4100 (past every bound a scanner had), bare and at the start, in the middle and at the end of prose; the assertion is one direction only: whatever the round-6 form matched is still matched.
_LET = "ghijklmnopqrstuvwxyz"  # no hex digit, no digit, no capital: no other scanner reads it as a secret


def _w(n: int) -> str:
    return (_LET * (n // 20 + 1))[:n]


def _seg(n: int) -> str:
    return "".join(("-_"[(i // 9) % 2] if i % 9 == 8 and i != n - 1 else _LET[i % 20]) for i in range(n))


_AT = "@"
_DENSE_LENGTHS = list(range(1, 301)) + [400, 600, 1000, 4100]
_PROSE = "The planner checked the overnight window and the tariff boundary before it chose, and the details follow here. " * 2
_FAMILIES = {
    "JWT-like": [
        lambda n: "eyJ" + _seg(n + 6) + "." + _seg(40) + ".sig",
        lambda n: "eyJ" + _seg(10) + "." + _seg(n + 6) + ".sig",
        lambda n: "eyJ" + _seg(10) + "." + _seg(10) + "." + _seg(n),
        lambda n: "eyJ-" * n + "eyJabcdefgh.abcdefgh.sig",
        lambda n: _w(n) + "eyJabcdefgh.abcdefgh.sig",
    ],
    "token or key shape (the JWT form)": [
        lambda n: "eyJ" + _seg(n + 20) + ".eyJ" + _seg(30) + "." + _seg(12),
        lambda n: "eyJ" + _seg(30) + ".eyJ" + _seg(n + 20) + "." + _seg(12),
        lambda n: "eyJ" + _seg(30) + ".eyJ" + _seg(30) + "." + _seg(n + 10),
        lambda n: "eyJ-" * n + "eyJ" + _seg(30) + ".eyJ" + _seg(30) + "." + _seg(12),
    ],
    "e-mail": [
        lambda n: ("ghij.klmn_op%qr+st-uv" * (n // 21 + 1))[:n] + _AT + "mail.example.org",
        lambda n: "bob" + _AT + "a1." * n + "com",
        lambda n: "bob" + _AT + _w(n) + ".org",
        lambda n: "bob" + _AT + "mail." + _w(n + 1),
    ],
    "webhook path": [
        lambda n: "https://hooks." + ("ghijklmnopqrs.tuvwxyz-" * (n // 22 + 1))[:n] + ".test/services/T01/B02/" + _w(12),
        lambda n: "/api/" + "web" + "hook/" + _w(n),
        lambda n: "hooks." * n + "a/services/abcdefghijkl",
    ],
    # this scanner needs the address to STAND ALONE (nothing alphanumeric or a dot before or after it), so the run of hex digits and dots that its look-ahead reads ends where the address does: the letter is in the
    # address or nowhere, and the bound of round 7 changed no verdict here (the card's rule is a different matter: it has no such boundary, see test/differential.test.mjs). The family sweeps what stands around it.
    "MAC, dotted": [
        lambda n: " a123.4567.8901 " + "0" * n,
        lambda n: _w(n) + " 0123.4567.89ab",
        lambda n: " 2026.1114.0900 " + "9" * n + " 0123.4567.89ab " + "0" * n,
    ],
    "URL with userinfo": [
        lambda n: "https://" + _w(n) + ":pw" + _AT + "host",
        lambda n: "https://u:" + _w(n) + _AT + "host",
        lambda n: _w(n) + "://u:p" + _AT + "h",
    ],
    "pass or pw pair": [
        lambda n: "a_" * n + "pass=qwerty",
        lambda n: '"' + _w(n) + '_pass": "qwerty"',
        lambda n: "wifi_pw=" + _w(n + 3),
    ],
}


def _places(secret: str) -> list[tuple[str, str]]:
    return [("bare", secret), ("start", secret + " " + _PROSE), ("middle", _PROSE[:80] + " " + secret + " " + _PROSE[:80]), ("end", _PROSE + " " + secret)]


_long_total = 0
for _name, _builders in _FAMILIES.items():
    _old, _new, _kind = _REFERENCE[_name]
    _old_hits, _lost = 0, []
    for _bi, _build in enumerate(_builders):
        for _n in _DENSE_LENGTHS:
            for _place, _text in _places(_build(_n)):
                if _old.search(_text):
                    _old_hits += 1
                    if not _new.search(_text):
                        _lost.append(f"family {_bi} n={_n} {_place}")
    _long_total += _old_hits
    check(f"[r8] DIFFERENTIAL, long components: the {_name} scanner still matches every text its round-6 form matched ({_old_hits} texts: each component from 1 to 1000 characters and 4100, bare and in prose)",
          _old_hits >= 1000 and not _lost, f"{len(_lost)} lost: " + "; ".join(_lost[:3]))
check("[r8] the corpus is large enough to mean something (the round-6 forms match more than 20000 of its texts)", _long_total > 20000, str(_long_total))

# the gate can see the class: the round-7 BOUNDED forms of the scanners lose texts on this corpus (negative controls)
_R7 = {
    "JWT-like": re.compile(r"eyJ[A-Za-z0-9_-]{6,512}\.[A-Za-z0-9_-]{6,4096}\.[A-Za-z0-9_-]*"),
    "token or key shape (the JWT form)": re.compile(r"eyJ[A-Za-z0-9_-]{20,512}\.eyJ[A-Za-z0-9_-]{20,4096}\.[A-Za-z0-9_-]{10,}"),
    "e-mail": re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63}){0,16}\.[A-Za-z]{2,24}"),
    "webhook path": re.compile(r"/api/webhook/[A-Za-z0-9_-]{8,}|hooks\.[a-z0-9.-]{1,253}/services/[A-Za-z0-9/_-]{12,}", re.I),
}
# (the dotted MAC scanner is not in this list: it needs the address to stand alone, so the round-7 bound changed no verdict of it; see the family above)
for _name, _r7 in _R7.items():
    _old = _REFERENCE[_name][0]
    _lost7 = [f"family {_bi} n={_n}" for _bi, _build in enumerate(_FAMILIES[_name]) for _n in _DENSE_LENGTHS if _old.search(_build(_n)) and not _r7.search(_build(_n))]
    check(f"[r8] negative control: the round-7 bounded form of the {_name} scanner loses texts on this corpus ({len(_lost7)}), so the gate can see the class", len(_lost7) >= 1, "")
# the NIT, said directly: an address whose domain has more than 17 labels, every label with a digit, is found (the round-7 form did not find it), and so is one with a label of 64 characters
_many = "bob" + _AT + "a1." * 20 + "com"
_long_label = "bob" + _AT + "a" * 64 + ".com"
check("[r8] the e-mail scanner finds an address of 21 labels that all hold a digit, and one with a label of 64 characters (the round-7 form found neither)",
      bool(EMAIL.search(_many)) and bool(EMAIL.search(_long_label)) and not _R7["e-mail"].search(_many) and not _R7["e-mail"].search(_long_label))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
