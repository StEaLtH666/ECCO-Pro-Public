#!/usr/bin/env python3
"""FB-B0 - re-verify the ESPHome / ESP-IDF SOURCE facts the Fallback durable
primitive depends on, against the INSTALLED ESPHome package and an ESP-IDF
source tree (architecture 4.1 / 4.2; S2 Part A m9; the version pins in
firmware/include/ecco_fallback_version_pins.h name this script: re-run it
against the new sources before bumping either bound).

Usage:
  python registry/tests/check_fbb_esphome_source_facts.py [--idf PATH | --no-idf]

ESPHome must be importable (pip install "esphome==2026.8.2"): this FAILS
otherwise - it never skips. ESP-IDF: --idf PATH or $ECCO_IDF_PATH (an esp-idf
v5.5.x checkout or framework package); --no-idf leaves the IDF half out
EXPLICITLY and says so. Not part of the offline suite (it is not a test_*.py:
the offline CI job has no ESPHome); read-only; no network, no hardware.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "registry" / "tests" / "fixtures" / "fbb_nvs_keyhash_fixture.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def read(base: Path, rel: str) -> str:
    p = base / rel
    if not p.is_file():
        check(f"source file present: {rel}", False, str(p))
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def squash(text: str) -> str:
    return " ".join(text.split())


args = sys.argv[1:]
no_idf = "--no-idf" in args
idf_path = None
if "--idf" in args:
    idf_path = Path(args[args.index("--idf") + 1])
elif os.environ.get("ECCO_IDF_PATH"):
    idf_path = Path(os.environ["ECCO_IDF_PATH"])

# ===========================================================================
print("[1] ESPHome (installed package)")
# ===========================================================================
try:
    import esphome  # noqa: F401
    from esphome import const as esphome_const
    from esphome import helpers as esphome_helpers
except ImportError as e:
    print(f"  FAIL  ESPHome is not importable ({e}) - install esphome==2026.8.2; this check never skips")
    sys.exit(1)
E = Path(esphome.__file__).resolve().parent
ver = tuple(int(x) for x in re.findall(r"\d+", esphome_const.__version__)[:3])
print(f"  info  esphome {esphome_const.__version__} at {E}")
check("installed ESPHome is inside the pinned range [2026.8.2, 2026.9.0)", (2026, 8, 2) <= ver < (2026, 9, 0),
      esphome_const.__version__)

prefs_h = read(E, "components/esp32/preferences.h")
cls = re.search(r"class ESP32Preferences final : public PreferencesMixin<ESP32Preferences> \{(.*?)\n\};", prefs_h, re.S)
public_part = cls.group(1).split(" protected:")[0] if cls else ""
check("esp32/preferences.h: ESP32Preferences declares `uint32_t nvs_handle;` in its PUBLIC section, and the file "
      "binds it with DECLARE_PREFERENCE_ALIASES(esphome::esp32::ESP32Preferences)",
      cls is not None and " public:" in cls.group(1) and "uint32_t nvs_handle;" in public_part
      and "DECLARE_PREFERENCE_ALIASES(esphome::esp32::ESP32Preferences)" in prefs_h)
backend = squash(read(E, "core/preference_backend.h"))
check("core/preference_backend.h: the alias macro makes esphome::ESPPreferences the platform class and declares "
      "`extern ESPPreferences *global_preferences`",
      "using Preferences = platform_class;" in backend and "using ESPPreferences = Preferences;" in backend
      and "extern ESPPreferences *global_preferences;" in backend)
prefs_cpp = read(E, "components/esp32/preferences.cpp")
open_fn = re.search(r"void ESP32Preferences::open\(\) \{(.*?)\n\}", prefs_cpp, re.S)
of = squash(open_fn.group(1)) if open_fn else ""
check("open(): namespace \"esphome\" (NVS_READWRITE); on failure deinit + ERASE the whole partition + init + reopen; "
      "a second failure leaves nvs_handle = 0 (the model's STORAGE_UNAVAILABLE)",
      of.count('nvs_open("esphome", NVS_READWRITE, &this->nvs_handle);') == 2
      and "nvs_flash_deinit(); nvs_flash_erase(); nvs_flash_init();" in of and "this->nvs_handle = 0;" in of, of[:200])
check("keys: every nvs_get_blob / nvs_set_blob uses a key string rendered by uint32_to_str(key_str, key)",
      prefs_cpp.count("uint32_to_str(key_str,") >= 2 and "nvs_get_blob(this->nvs_handle, key_str" in prefs_cpp
      and "nvs_set_blob(this->nvs_handle, key_str" in prefs_cpp)
sync_fn = re.search(r"bool ESP32Preferences::sync\(\) \{(.*?)\n\}", prefs_cpp, re.S)
sy = squash(sync_fn.group(1)) if sync_fn else ""
check("load() serves the pending save queue FIRST; sync() writes every queued key, counts failures, CLEARS the queue "
      "regardless and returns one aggregate result; nvs_commit is a no-op on esp-idf (why FB keys never use it)",
      "try find in pending saves and load from that" in prefs_cpp and "for (const auto &save : s_pending_save)" in sy
      and "failed++;" in sy and "s_pending_save.clear();" in sy and "commit on esp-idf currently is a no-op" in sy)
helpers_h = read(E, "core/helpers.h")
helpers_cpp = read(E, "core/helpers.cpp")
u2s = re.search(r"char \*uint32_to_str_unchecked\(char \*buf, uint32_t val\) \{(.*?)\n\}", helpers_cpp, re.S)
check("helpers: UINT32_MAX_STR_SIZE = 11 and uint32_to_str(std::span<char, 11>, uint32_t) renders base 10, '0' for 0, "
      "no sign, no leading zeros (digits reversed in place)",
      "static constexpr size_t UINT32_MAX_STR_SIZE = 11;" in helpers_h
      and "inline size_t uint32_to_str(std::span<char, UINT32_MAX_STR_SIZE> buf, uint32_t val) {" in helpers_h
      and u2s is not None and "*buf++ = '0';" in u2s.group(1) and "'0' + (val % 10)" in u2s.group(1)
      and "std::reverse(start, buf);" in u2s.group(1))
check("hal: on ESP32, core/hal.h dispatches to components/esp32/hal.h, whose esphome::micros() is an inline uint32_t "
      "wrapper (the adapter's duration clock); the Arduino `#define micros()` glue is emitted only for the Arduino "
      "framework (the adapter parenthesises the call either way)",
      '#include "esphome/components/esp32/hal.h"' in read(E, "core/hal.h")
      and re.search(r"inline uint32_t micros\(\) \{", read(E, "components/esp32/hal.h")) is not None
      and "if CORE.using_arduino:" in read(E, "core/config.py") and "#define micros() esphome::micros()" in read(E, "core/config.py"))
writer = read(E, "writer.py")
check("esphome/core/version.h is GENERATED per build (writer.py VERSION_H_FORMAT: ESPHOME_VERSION_CODE via VERSION_CODE)",
      'VERSION_H_TARGET = "esphome/core/version.h"' in writer and "#define ESPHOME_VERSION_CODE VERSION_CODE({}, {}, {})" in writer
      and "((major) << 16 | (minor) << 8 | (patch))" in squash(read(E, "core/macros.h")))
esp32_init = read(E, "components/esp32/__init__.py")
idf_lookup = re.search(r"ESP_IDF_FRAMEWORK_VERSION_LOOKUP = \{(.*?)\}", esp32_init, re.S)
check("esp32: the RECOMMENDED esp-idf (used when the YAML gives no framework version) is 5.5.5",
      idf_lookup is not None and '"recommended": cv.Version(5, 5, 5)' in idf_lookup.group(1))
cfg = read(E, "core/config.py")
check("esphome: includes: each listed file is COPIED next to main.cpp and included as #include \"<basename>\" - so every "
      "header a listed header includes must itself be listed; min_version is validated against the running version",
      "copy_file_if_changed(path, dst)" in cfg and "cg.add_global(cg.RawStatement(f'#include \"{basename}\"'))" in cfg
      and "cv.Optional(CONF_MIN_VERSION, default=ESPHOME_VERSION): cv.All(" in cfg and "cv.validate_esphome_version" in cfg)

# Key derivations used by the key-hash proof (registry/tests/test_fallback_nvs_keyhash.py + fixture).
fx = FIXTURE["esphome"]
check("safe_mode RTC_KEY == fixture (233825507)",
      f"constexpr uint32_t RTC_KEY = {fx['safe_mode_key']['value']}UL;" in read(E, "components/safe_mode/safe_mode.h"))
check("API noise PSK key == fixture (88491486)",
      f"uint32_t hash = {fx['api_noise_key']['value']}UL;" in read(E, "components/api/api_server.cpp"))
wifi_cpp = read(E, "components/wifi/wifi_component.cpp")
check("Wi-Fi SavedWifiSettings key: config-version hash with STA, else 88491487 (fixture)",
      f"uint32_t hash = this->has_sta() ? App.get_config_version_hash() : {fx['wifi_no_sta_key']['value']}UL;" in wifi_cpp)
callers = sorted({p.relative_to(E).as_posix() for p in E.rglob("*.[ch]*") if p.suffix in (".cpp", ".h")
                  and re.search(r"(?<!this)(?:->|\.)save_wifi_sta\(", p.read_text(encoding="utf-8", errors="replace"))})
# (`this->save_wifi_sta(` is WiFiComponent's own overload delegation, not a caller)
check("save_wifi_sta() (the only SavedWifiSettings writer) is called only by captive_portal, esp32_improv, "
      "improv_serial and the wifi.configure action - none of which the firmware configures (documented residual)",
      callers == ["components/captive_portal/captive_portal.cpp", "components/esp32_improv/esp32_improv_component.cpp",
                  "components/improv_serial/improv_serial_component.cpp", "components/wifi/automation.h"], str(callers))
check("globals: restore key = 1944399030 ^ name_hash_, name_hash_ = int(md5(id).hexdigest()[:8], 16) (fixture seed)",
      f"make_preference<T>({fx['globals_key_seed']['value']}U ^ this->name_hash_)" in read(E, "components/globals/globals_component.h")
      and "int(hashlib.md5(value).hexdigest()[:8], 16)" in read(E, "components/globals/__init__.py"))
dbg = read(E, "components/debug/debug_esp32.cpp")
check("debug: reboot-source key = fnv1_hash_extend(fnv1_hash(\"reboot_source\"), App.get_name())",
      'static const char *const REBOOT_KEY = "reboot_source";' in dbg
      and "fnv1_hash_extend(fnv1_hash(REBOOT_KEY), App.get_name().c_str())" in dbg)
check("entities: make_entity_preference_ key = get_preference_hash() ^ version, preference hash = object-id hash "
      "(^ device id 0); switch / template number / template select use version 0",
      "uint32_t key = this->get_preference_hash() ^ version;" in read(E, "core/entity_base.cpp")
      and "this->rtc_ = this->make_entity_preference<bool>();" in read(E, "components/switch/switch.cpp")
      and "this->pref_ = this->make_entity_preference<float>();" in read(E, "components/template/number/template_number.cpp"))


def object_id_hash(name: str) -> int:  # the offline suite's formula (test_fallback_nvs_keyhash.object_id_hash)
    h = 0x811C9DC5
    for ch in name.encode("utf-8"):
        c = ord("_") if ch == 0x20 else (ch + 32 if 0x41 <= ch <= 0x5A else ch)
        c = c if (c in b"-_" or 0x30 <= c <= 0x39 or 0x61 <= c <= 0x7A or 0x41 <= c <= 0x5A) else ord("_")
        h = ((h * 0x01000193) & 0xFFFFFFFF) ^ c
    return h


import yaml  # noqa: E402 - ESPHome depends on PyYAML

names = set()
for yml in sorted((ROOT / "firmware").glob("*.yaml")):
    for m in re.finditer(r"^\s+name: ['\"]?([^'\"\n]+?)['\"]?\s*$", yml.read_text(encoding="utf-8"), re.M):
        names.add(m.group(1))
mismatch = [n for n in sorted(names) if esphome_helpers.fnv1_hash_object_id(n) != object_id_hash(n)]
check(f"ESPHome's own fnv1_hash_object_id == the offline suite's formula for every entity name in the firmware YAMLs "
      f"({len(names)} names)", len(names) > 50 and not mismatch, str(mismatch[:5]))
check("...and the offline suite's pinned known answers are what ESPHome computes (object-id and 2026.8-beta raw-name keys)",
      (esphome_helpers.fnv1_hash_object_id("Clock Correction Threshold"), esphome_helpers.fnv1_hash_name("Clock Correction Threshold"),
       esphome_helpers.fnv1_hash_object_id("Automatic Clock Sync"), esphome_helpers.fnv1_hash_name("Automatic Clock Sync"))
      == (3507116908, 2340601518, 2578858645, 2949609849))

# ===========================================================================
print("[2] ESP-IDF source tree")
# ===========================================================================
if no_idf:
    print("  info  --no-idf: the ESP-IDF half was NOT checked in this run (it is not a pass)")
elif idf_path is None or not idf_path.is_dir():
    check("an ESP-IDF source tree is given (--idf PATH or $ECCO_IDF_PATH), or --no-idf is passed explicitly", False,
          str(idf_path))
else:
    I = idf_path
    vh = read(I, "components/esp_common/include/esp_idf_version.h")
    iv = tuple(int(re.search(rf"#define ESP_IDF_VERSION_{k}\s+(\d+)", vh).group(1)) for k in ("MAJOR", "MINOR", "PATCH")) \
        if vh else (0, 0, 0)
    print(f"  info  esp-idf {'.'.join(map(str, iv))} at {I}")
    check("esp-idf is inside the pinned range [5.5.5, 5.6.0)", (5, 5, 5) <= iv < (5, 6, 0), str(iv))
    types_cpp = squash(read(I, "components/nvs_flash/src/nvs_types.cpp"))
    check("item hash = crc32_le(0xffffffff) over nsIndex (1 byte), key[16], chunkIndex - datatype NOT included",
          "uint32_t result = 0xffffffff;" in types_cpp
          and "esp_rom_crc32_le(result, p + offsetof(Item, nsIndex), offsetof(Item, datatype) - offsetof(Item, nsIndex));" in types_cpp
          and "esp_rom_crc32_le(result, p + offsetof(Item, key), sizeof(key));" in types_cpp
          and "esp_rom_crc32_le(result, p + offsetof(Item, chunkIndex), sizeof(chunkIndex));" in types_cpp)
    check("the hash list keeps 24 bits (calculateCrc32WithoutValue() & 0xffffff)",
          read(I, "components/nvs_flash/src/nvs_item_hash_list.cpp").count("item.calculateCrc32WithoutValue() & 0xffffff") >= 2)
    page = squash(read(I, "components/nvs_flash/src/nvs_page.cpp"))
    check("Page::load erases an earlier item with the same 24-bit hash without comparing keys (F11)",
          "size_t duplicateIndex = mHashList.find(0, item);" in page and "if (duplicateIndex < i) { eraseEntryAndSpan(duplicateIndex); }" in page)
    api = read(I, "components/nvs_flash/src/nvs_api.cpp")
    find = re.search(r"static esp_err_t nvs_find_ns_handle\(.*?\n\}", api, re.S)
    setb = re.search(r'extern "C" esp_err_t nvs_set_blob\(.*?\n\}', api, re.S)
    simple = squash(read(I, "components/nvs_flash/src/nvs_handle_simple.cpp"))
    storage = squash(read(I, "components/nvs_flash/src/nvs_storage.cpp"))
    check("nvs_set_blob returns INVALID_HANDLE (handle lookup), READ_ONLY (handle) or NOT_INITIALIZED (storage not "
          "ACTIVE) BEFORE any flash access - the only three pre-write codes of the outcome table",
          find is not None and re.findall(r"return (ESP_\w+);", find.group(0)) == ["ESP_ERR_NVS_INVALID_HANDLE", "ESP_OK"]
          and setb is not None and "return handle->set_blob(key, value, length);" in setb.group(0)
          and "if (!valid) return ESP_ERR_NVS_INVALID_HANDLE; if (mReadOnly) return ESP_ERR_NVS_READ_ONLY; "
              "return mStoragePtr->writeItem(mNsIndex, nvs::ItemType::BLOB, key, blob, len);" in simple
          and "esp_err_t Storage::writeItem(uint8_t nsIndex, ItemType datatype, const char* key, const void* data, "
              "size_t dataSize) { if(mState != StorageState::ACTIVE) { return ESP_ERR_NVS_NOT_INITIALIZED; }" in storage)
    stats = re.search(r'extern "C" esp_err_t nvs_get_stats\(.*?\n\}', api, re.S)
    calc = re.search(r"esp_err_t Page::calcEntries\(nvs_stats_t &nvsStats\)(.*?)\n\}", read(I, "components/nvs_flash/src/nvs_page.cpp"), re.S)
    check("nvs_get_stats is RAM-only: NOT_INITIALIZED without storage, NVS_INVALID_STATE for invalid storage, and "
          "Page::calcEntries reports ESP_ERR_INVALID_STATE for an INVALID page (the nvs_healthy() gate)",
          stats is not None and "return ESP_ERR_NVS_NOT_INITIALIZED;" in stats.group(0)
          and "return ESP_ERR_NVS_INVALID_STATE;" in stats.group(0) and "return pStorage->fillStats(*nvs_stats);" in stats.group(0)
          and calc is not None and "return ESP_ERR_INVALID_STATE;" in calc.group(1))
    check("storage init erases blob indexes whose chunks are missing (eraseMismatchedBlobIndexes)",
          "eraseMismatchedBlobIndexes(blobIdxList);" in storage)
    rom = read(I, "components/esp_rom/test_apps/linux_rom_apis/main/rom_test.cpp")
    rom_bytes = bytes(int(b, 16) for b in re.findall(r"0x([0-9a-f]{2})", re.search(r"original \[\] = \{(.*?)\};", rom, re.S).group(1))) \
        if rom else b""
    check("the ROM CRC test vector in the tree equals the committed fixture (and zlib reproduces 0xd4dc5010)",
          rom_bytes.hex() == FIXTURE["rom_crc_vector"]["data_hex"] and zlib.crc32(rom_bytes, 0xFFFFFFFF) == 0xD4DC5010)
    phy = read(I, "components/esp_phy/src/phy_init.c")
    check("PHY namespace and keys == fixture (phy / cal_version / cal_mac / cal_data)",
          all(f'= "{v}";' in phy for v in ["phy", *FIXTURE["phy"]["keys"]]))
    sub = subprocess.run(["git", "-C", str(I), "ls-tree", "HEAD", "components/esp_wifi/lib"], capture_output=True, text=True)
    if sub.returncode == 0 and sub.stdout.strip():
        check("components/esp_wifi/lib is the esp32-wifi-lib commit the committed Wi-Fi key fixture was extracted from",
              FIXTURE["wifi_keys"]["commit"] in sub.stdout, sub.stdout.strip())
    else:
        print("  info  not a git checkout: the esp_wifi/lib submodule pin is recorded in the fixture, not re-read here")
    lib = I / "components" / "esp_wifi" / "lib" / "esp32" / "libnet80211.a"
    if lib.is_file():
        check("the libnet80211.a in the tree is the fixture's archive (sha256)",
              hashlib.sha256(lib.read_bytes()).hexdigest() == FIXTURE["wifi_keys"]["archive_sha256"])
    else:
        print("  info  esp_wifi/lib binaries not present in this tree: the archive sha256 is recorded in the fixture")

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-B0 ESPHome / ESP-IDF source facts hold" + (" (ESP-IDF half not checked: --no-idf)." if no_idf else "."))
