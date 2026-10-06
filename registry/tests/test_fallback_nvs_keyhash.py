#!/usr/bin/env python3
"""FB-B0 - NVS 24-bit item-hash collision proof for the Fallback keys over the
FULL key universe (S6 BLK-60 rev 3; S2 X5; architecture 11.1).

Why: at NVS init, Page::load() on the ACTIVE page erases an earlier item
whose 24-bit hash equals a later one WITHOUT comparing keys (IDF 5.5.5,
F11). The hash is crc32_le(0xffffffff, [nsIndex] || key[16] || [chunkIndex])
& 0xFFFFFF (Item::calculateCrc32WithoutValue; the datatype is not included).
So an FB record could be silently erased by ANY other item sharing its page
whose hash collides - an ESPHome preference, a Wi-Fi or PHY key or a
namespace entry.

The universe (nothing hand-waved):
  - the three FB keys (FBP, FBW, FBS) as ESPHome decimal key strings;
  - every *_TAG declared in any firmware header (13 durable, the evidence
    fingerprint domain, the two FB-A tags, the FB-B0 witness tag) plus FB-A's
    prospective tags;
  - the restore_value globals of EVERY firmware YAML (1944399030 ^ md5 hash);
  - the entity preferences of every firmware YAML: template numbers / selects
    with restore_value and every template switch (the ALWAYS_OFF ones as a
    historic superset), under the object-id key AND the 2026.8-beta raw-name
    key (fnv1_hash_name);
  - ESPHome component keys: safe_mode, API noise PSK, the Wi-Fi no-STA key
    (superset) and debug's reboot-source key; the build-dependent Wi-Fi STA
    key is a documented residual (never written by this config);
  - the 84 Wi-Fi keys of namespace nvs.net80211, extracted from the exact
    esp32-wifi-lib commit IDF 5.5.5 pins (committed fixture with section
    sha256), the PHY keys (cal_data as a multi-chunk blob), namespace misc;
  - the namespace entries themselves (namespace 0).
Every (nsIndex 1..8 assignment, chunkIndex 0xFF / 0x00 / 0x80) combination
of every coexisting pair is checked. Collisions that involve an FB item FAIL;
pre-existing collisions between non-FB items are reported, not failed.

Offline: stdlib + the committed fixture. No I/O beyond reading repository files.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zlib
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "registry" / "tests" / "fixtures" / "fbb_nvs_keyhash_fixture.json"
INCLUDE_DIR = ROOT / "firmware" / "include"

sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import _dump_sim as ds  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


if not FIXTURE_PATH.is_file():
    print(f"  FAIL  required fixture not found: {FIXTURE_PATH}")
    sys.exit(1)
FX = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
ESPH = FX["esphome"]


def item_hash(ns: int, key, chunk: int) -> int:
    """IDF 5.5.5 Item::calculateCrc32WithoutValue() & 0xffffff."""
    k = key.encode("ascii") if isinstance(key, str) else bytes(key)
    if len(k) > 15:
        raise ValueError(f"NVS keys are at most 15 bytes: {key!r}")
    return zlib.crc32(bytes([ns]) + k.ljust(16, b"\0") + bytes([chunk]), 0xFFFFFFFF) & 0xFFFFFF


def fnv1_32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= b
    return h


def object_id_hash(name: str) -> int:
    """ESPHome helpers.h fnv1_hash_object_id: FNV-1 over to_sanitized_char(to_snake_case_char(c))."""
    out = bytearray()
    for ch in name.encode("utf-8"):
        c = ord("_") if ch == 0x20 else (ch + 32 if 0x41 <= ch <= 0x5A else ch)
        ok = c in b"-_" or 0x30 <= c <= 0x39 or 0x61 <= c <= 0x7A or 0x41 <= c <= 0x5A
        out.append(c if ok else ord("_"))
    return fnv1_32(bytes(out))


def raw_name_hash(name: str) -> int:
    """ESPHome helpers.py fnv1_hash_name (2026.8 beta keys): FNV-1 over the raw UTF-8 name."""
    return fnv1_32(name.encode("utf-8"))


def globals_key(gid: str) -> int:
    return ESPH["globals_key_seed"]["value"] ^ int(hashlib.md5(gid.encode()).hexdigest()[:8], 16)


# ===========================================================================
print("[1] The item-hash function (IDF goldens, ROM vector, negative controls)")
# ===========================================================================
rom = FX["rom_crc_vector"]
check("the Python CRC is esp_rom_crc32_le: IDF's own ROM test vector crc32_le(0xffffffff, 28 bytes) == 0xd4dc5010",
      zlib.crc32(bytes.fromhex(rom["data_hex"]), 0xFFFFFFFF) == int(rom["expected"], 16) == 0xD4DC5010)
GOLD = [(ns, key, chunk, int(h, 16)) for ns, key, chunk, h in FX["item_hash_goldens"]["vectors"]]
check(f"the formula reproduces all {len(GOLD)} item-hash goldens computed by IDF 5.5.5's own Item code (FBP / FBW index "
      "and both data chunk versions, FBS, namespace entries, a 15-character Wi-Fi key, a PHY multi-chunk index, ns 254)",
      len(GOLD) == 12 and all(item_hash(ns, key, chunk) == h for ns, key, chunk, h in GOLD),
      str([(ns, key, chunk) for ns, key, chunk, h in GOLD if item_hash(ns, key, chunk) != h]))
check("IDF verified the hash is datatype-independent (fixture), which the formula encodes by excluding the datatype",
      FX["item_hash_goldens"]["datatype_independent"] is True and FX["hash_function"]["datatype_included"] is False)
MUTANT_HASHES = {
    "datatype byte included": lambda ns, k, c: zlib.crc32(bytes([ns, 0x42]) + k.encode().ljust(16, b"\0") + bytes([c]), 0xFFFFFFFF) & 0xFFFFFF,
    "key not NUL-padded to 16": lambda ns, k, c: zlib.crc32(bytes([ns]) + k.encode() + bytes([c]), 0xFFFFFFFF) & 0xFFFFFF,
    "chunk index excluded": lambda ns, k, c: zlib.crc32(bytes([ns]) + k.encode().ljust(16, b"\0"), 0xFFFFFFFF) & 0xFFFFFF,
    "namespace excluded": lambda ns, k, c: zlib.crc32(k.encode().ljust(16, b"\0") + bytes([c]), 0xFFFFFFFF) & 0xFFFFFF,
    "zero initial value": lambda ns, k, c: zlib.crc32(bytes([ns]) + k.encode().ljust(16, b"\0") + bytes([c])) & 0xFFFFFF,
    "high 24 bits": lambda ns, k, c: zlib.crc32(bytes([ns]) + k.encode().ljust(16, b"\0") + bytes([c]), 0xFFFFFFFF) >> 8,
}
survivors = [n for n, fn in MUTANT_HASHES.items() if all(fn(ns, key, chunk) == h for ns, key, chunk, h in GOLD)]
check(f"negative controls: every mutated hash definition ({len(MUTANT_HASHES)}) disagrees with the IDF goldens",
      not survivors, str(survivors))

# ===========================================================================
print("[2] The key universe (derived from repository files + the committed fixture)")
# ===========================================================================
TAG_DECL = re.compile(r'constexpr (?:const )?char (?:\*\s*)?([A-Z0-9_]+_TAG(?:_V\d+)?)(?:\[\])? = "([^"]+)";')
TAGS = {}
for h in sorted(INCLUDE_DIR.glob("*.h")):
    for name, value in TAG_DECL.findall(h.read_text(encoding="utf-8")):
        TAGS[f"{h.name}:{name}"] = value
by_header = {}
for k in TAGS:
    by_header[k.split(":")[0]] = by_header.get(k.split(":")[0], 0) + 1
check("independent tag inventory: 13 durable tags, the evidence fingerprint domain, the two FB-A tags and the FB-B0 "
      "witness tag (17 declarations across 4 headers) - all included",
      by_header == {"ecco_durable_snapshot.h": 13, "ecco_recovery_evidence.h": 1, "ecco_fallback_profile.h": 2,
                    "ecco_fallback_durable_model.h": 1}, str(by_header))
TAG_STRINGS = sorted(set(TAGS.values()) | set(fp.PROSPECTIVE_TAGS))
FB_TAG_KEYS = {fp.FALLBACK_PROFILE_TAG: fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_TAG: fd.FAILBACK_PROVISION_KEY,
               fp.FAILBACK_STATE_TAG: fd.FAILBACK_STATE_KEY}
check("the FB keys are the FNV-1 32 keys of their tags (FBP 0x5FEE6196 '1609458070', FBW 0x3BA3DF61 '1000595297', "
      "FBS 0x808485C3 '2156168643')", all(fnv1_32(t.encode()) == k for t, k in FB_TAG_KEYS.items())
      and [str(k) for k in FB_TAG_KEYS.values()] == ["1609458070", "1000595297", "2156168643"])

# Hardware-only wrappers (registry/tests/_hardware_wrappers.py) carry no application identity - no node name, entities,
# globals or restore preferences; they only package the production YAML and override esp32 / logger, so they add nothing to
# the key universe below. Their shape is pinned by test_esp32s3_variant.py.
import _hardware_wrappers as hw  # noqa: E402

YAMLS = {p.name: ds.load_firmware(p) for p in sorted((ROOT / "firmware").glob("*.yaml"))
         if p.name != "secrets.yaml" and not hw.is_hardware_wrapper(p)}
check("the hardware-wrapper allowlist is exactly the one S3 wrapper, it exists, and the production YAMLs scanned are the three "
      "historic firmware files",
      hw.HARDWARE_WRAPPERS == ("ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml",)
      and (ROOT / "firmware" / hw.HARDWARE_WRAPPERS[0]).is_file()
      and sorted(YAMLS) == ["ecco_clock_dongle_stage3_2_manual_slot1.yaml", "ecco_clock_dongle_stage3_3_manual_tou6.yaml",
                            "ecco_clock_dongle_stage3_4_free_power.yaml"])
RESTORE_GLOBALS = sorted({g["id"] for doc in YAMLS.values() for g in doc.get("globals") or [] if g.get("restore_value")})
check("restore_value globals of every firmware YAML: exactly reg244_last_applied_value / _valid, keys "
      "1944399030 ^ md5(id)[:8] = 1425646640 / 1452813359 (known answers from ESPHome 2026.8.2's own codegen)",
      RESTORE_GLOBALS == ["reg244_last_applied_valid", "reg244_last_applied_value"]
      and (globals_key("reg244_last_applied_value"), globals_key("reg244_last_applied_valid")) == (1425646640, 1452813359))
ENTITIES = set()
for doc in YAMLS.values():
    for plat in ("number", "select"):
        for e in doc.get(plat) or []:
            if e.get("restore_value"):
                ENTITIES.add((plat, e["name"]))
    for e in doc.get("switch") or []:
        ENTITIES.add(("switch", e["name"]))
ENTITIES = sorted(ENTITIES)
n_num = sum(1 for p, _n in ENTITIES if p == "number")
n_sw = sum(1 for p, _n in ENTITIES if p == "switch")
check(f"entity preferences: {n_num} restore numbers and {n_sw} switches across all YAMLs (3 RESTORE_DEFAULT_ON + the "
      "ALWAYS_OFF ones as a historic superset), each under its object-id key and its 2026.8-beta raw-name key",
      # FB-B2: n_sw 9 -> 10 - the one new template switch `ECCO Fallback Profile Arm` (fallback_profile_arm, restore_mode
      # ALWAYS_OFF: no preference key is created for it; like the other ALWAYS_OFF arms it is counted as a historic superset, and
      # its two entity keys are covered by the collision checks below).
      n_num == 6 and n_sw == 10 and not any(p == "select" for p, _n in ENTITIES))
check("entity key known answers (ESPHome 2026.8.2 helpers): 'Clock Correction Threshold' 3507116908 / beta 2340601518, "
      "'Automatic Clock Sync' 2578858645 / 2949609849, 'Dump to Grid Stop SOC' 3156274043 / 1118637223",
      (object_id_hash("Clock Correction Threshold"), raw_name_hash("Clock Correction Threshold"),
       object_id_hash("Automatic Clock Sync"), raw_name_hash("Automatic Clock Sync"),
       object_id_hash("Dump to Grid Stop SOC"), raw_name_hash("Dump to Grid Stop SOC"))
      == (3507116908, 2340601518, 2578858645, 2949609849, 3156274043, 1118637223))
DEVICE_NAMES = sorted({str(doc["esphome"]["name"]) for doc in YAMLS.values()})
debug_keys = [fnv1_32(b"reboot_source" + n.encode()) for n in DEVICE_NAMES]
check("debug's reboot-source key fnv1_hash_extend(fnv1_hash(\"reboot_source\"), App.get_name()) for every device name "
      "(ecco-clock-dongle -> 1400698313, known answer)", DEVICE_NAMES == ["ecco-clock-dongle"] and debug_keys == [1400698313])

# (label, namespace, key string, chunk set, is FB)
ENTRIES: dict[tuple[str, str], dict] = {}
BLOB_CHUNKS = (0xFF, 0x00, 0x80)


def add(label: str, ns: str, key: str, chunks=BLOB_CHUNKS, fb: bool = False) -> None:
    e = ENTRIES.setdefault((ns, key), {"labels": set(), "chunks": set(), "fb": False})
    e["labels"].add(label)
    e["chunks"] |= set(chunks)
    e["fb"] = e["fb"] or fb


for tag, k in FB_TAG_KEYS.items():
    add(f"FB {tag}", "esphome", str(k), fb=True)
for t in TAG_STRINGS:
    add(f"tag {t}", "esphome", str(fnv1_32(t.encode())), fb=t in FB_TAG_KEYS)
for g in RESTORE_GLOBALS:
    add(f"global {g}", "esphome", str(globals_key(g)))
for plat, name in ENTITIES:
    add(f"{plat} {name!r}", "esphome", str(object_id_hash(name)))
    add(f"{plat} {name!r} (2026.8 beta key)", "esphome", str(raw_name_hash(name)))
for label in ("safe_mode_key", "api_noise_key", "wifi_no_sta_key"):
    add(f"esphome {label}", "esphome", str(ESPH[label]["value"]))
for n, k in zip(DEVICE_NAMES, debug_keys):
    add(f"debug reboot_source ({n})", "esphome", str(k))
WIFI = FX["wifi_keys"]
for k in WIFI["keys_in_section_order"]:
    add(f"wifi {k}", WIFI["namespace"], k)
PHY = FX["phy"]
for k in PHY["keys"]:
    add(f"phy {k}", PHY["namespace"], k,
        chunks=(0xFF, *range(0, 8), *range(0x80, 0x88)) if k == PHY["multi_chunk_blob"] else BLOB_CHUNKS)
for ns in FX["namespaces"]:
    add(f"namespace entry {ns}", "", ns, chunks=(0xFF,))
section = b"".join(k.encode() + b"\0" for k in WIFI["keys_in_section_order"])
check("the committed Wi-Fi key list IS the binary section: re-joined it has the recorded length (973) and sha256 "
      f"({WIFI['section_sha256'][:12]}...) of {WIFI['object']} {WIFI['section']} in {WIFI['archive']} @ esp32-wifi-lib "
      f"{WIFI['commit'][:10]} (the commit esp-idf {FX['esp_idf']['version']} pins)",
      len(WIFI["keys_in_section_order"]) == 84 and len(section) == WIFI["section_len"] == 973
      and hashlib.sha256(section).hexdigest() == WIFI["section_sha256"])
check("every key in the universe fits the 15-byte NVS key limit and is ASCII",
      all(len(key.encode("ascii")) <= 15 for (_ns, key) in ENTRIES))
N_ESPHOME = sum(1 for (ns, _k) in ENTRIES if ns == "esphome")
print(f"  info  universe: {len(ENTRIES)} distinct (namespace, key) items - {N_ESPHOME} in esphome, "
      f"{sum(1 for (ns, _k) in ENTRIES if ns == WIFI['namespace'])} in nvs.net80211, "
      f"{sum(1 for (ns, _k) in ENTRIES if ns == 'phy')} in phy, 0 in misc, {len(FX['namespaces'])} namespace entries")
print(f"  info  residual (documented, not in the universe): {ESPH['wifi_sta_key']['residual']}")

# ===========================================================================
print("[3] 32-bit distinctness of the ESPHome preference keys")
# ===========================================================================
esphome_items = {key: e for (ns, key), e in ENTRIES.items() if ns == "esphome"}
fb_multi = {key: sorted(e["labels"]) for key, e in esphome_items.items() if e["fb"] and
            {lbl.split(" ", 1)[1] for lbl in e["labels"]} - {f"{t}" for t in FB_TAG_KEYS}}
check("each FB key (FBP, FBW, FBS) is used by NOTHING else in namespace esphome (32-bit keys; the only labels on an FB "
      "key are its own tag)", not fb_multi and sum(1 for e in esphome_items.values() if e["fb"]) == 3, str(fb_multi))
shared = {key: sorted(e["labels"]) for key, e in esphome_items.items() if not e["fb"] and len(e["labels"]) > 1}
print(f"  info  pre-existing shared 32-bit keys among non-FB items: {len(shared)} {shared if shared else ''}")

# ===========================================================================
print("[4] 24-bit item hashes: every coexisting pair, nsIndex assignments 1..8, chunks 0xFF / 0x00 / 0x80")
# ===========================================================================
NS_INDEX_RANGE = range(1, 9)


def collisions(entries: dict, cross_namespace: bool = True) -> list:
    table: dict[int, list] = {}
    for (ns, key), e in entries.items():
        for idx in ((0,) if ns == "" else NS_INDEX_RANGE):
            for chunk in sorted(e["chunks"]):
                table.setdefault(item_hash(idx, key, chunk), []).append((ns, key, idx, chunk))
    out = []
    for h, items in table.items():
        for a, b in combinations(items, 2):
            if (a[0], a[1]) == (b[0], b[1]):
                if a[2] != b[2]:
                    continue  # one key, one namespace, one index: different indices never coexist
            elif a[0] == b[0] and a[2] != b[2]:
                continue  # the same namespace has a single index
            elif a[0] != b[0] and (a[2] == b[2] or not cross_namespace):
                continue  # distinct namespaces have distinct indices
            out.append((h, a, b))
    return out


ALL = collisions(ENTRIES)
FB_KEYS = {(ns, key) for (ns, key), e in ENTRIES.items() if e["fb"]}
fb_hits = [c for c in ALL if (c[1][0], c[1][1]) in FB_KEYS or (c[2][0], c[2][1]) in FB_KEYS]
pre_existing = [c for c in ALL if c not in fb_hits]
n_hashes = sum(len(e["chunks"]) * (1 if ns == "" else len(NS_INDEX_RANGE)) for (ns, _k), e in ENTRIES.items())
check(f"NO 24-bit item-hash collision involves an FB item: FBP / FBW / FBS (index 0xFF and data chunks 0x00 / 0x80) vs "
      f"every item of the universe and vs each other, under every nsIndex assignment 1..8 ({n_hashes} item hashes)",
      not fb_hits, str([(hex(h), a, b) for h, a, b in fb_hits[:4]]))
print(f"  info  pre-existing 24-bit collisions between non-FB items (reported, not FB-B0's to fix): {len(pre_existing)}")
for h, a, b in pre_existing[:10]:
    print(f"  info    {h:06X}: {a} vs {b}")

# ===========================================================================
print("[5] Negative controls: planted collisions are detected")
# ===========================================================================
NS_BY_INDEX_HINT = {1: "esphome", 2: WIFI["namespace"]}


def planted_hits(nc: dict, cross_namespace: bool = True) -> list:
    ns_name = NS_BY_INDEX_HINT[nc["ns"]]
    planted = {k: dict(v, labels=set(v["labels"]), chunks=set(v["chunks"])) for k, v in ENTRIES.items()}
    planted[(ns_name, nc["key"])] = {"labels": {"planted"}, "chunks": {nc["chunk"]}, "fb": False}
    return [c for c in collisions(planted, cross_namespace)
            if (ns_name, nc["key"]) in ((c[1][0], c[1][1]), (c[2][0], c[2][1]))
            and ("esphome", nc["collides_with"][1]) in ((c[1][0], c[1][1]), (c[2][0], c[2][1]))]


for nc in FX["negative_controls"]:
    ns_name = NS_BY_INDEX_HINT[nc["ns"]]
    w_ns, w_key, w_chunk = nc["collides_with"]
    found = planted_hits(nc)
    check(f"planted key {nc['key']!r} in {ns_name} (chunk {nc['chunk']:#04x}) has item hash {nc['hash']} == FB "
          f"{w_key} chunk {w_chunk:#04x} and the detector reports that FB collision "
          f"({'same' if ns_name == 'esphome' else 'cross'}-namespace)",
          item_hash(nc["ns"], nc["key"], nc["chunk"]) == item_hash(w_ns, w_key, w_chunk) == int(nc["hash"], 16)
          and bool(found), f"{len(found)} found")
cross = [nc for nc in FX["negative_controls"] if nc["ns"] != 1]
check("sensitivity: a detector that skipped cross-namespace pairs would MISS the cross-namespace plant (so that "
      "rule is load-bearing), and dropping the chunk-0x80 items would miss it too",
      len(cross) == 1 and not planted_hits(cross[0], cross_namespace=False)
      and item_hash(1, cross[0]["collides_with"][1], 0x00) != int(cross[0]["hash"], 16))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-B0 NVS key-hash checks passed.")
