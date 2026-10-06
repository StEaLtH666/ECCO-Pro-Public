#pragma once

// FB-B0: two-sided ESPHome / ESP-IDF version pins for the Fallback durable
// primitive (docs/architecture/fallback/FINAL_FBB_FBC_ARCHITECTURE.md 4.2,
// S2 Part A m9). Kept in its own tiny header so the host negative-compile
// control (registry/tests/test_fallback_durable_host_compile.py) needs only
// the two version macros.
//
// Why an UPPER bound as well: the Fallback durable design depends on
// version-specific internals that were verified in source for exactly these
// versions -
//   ESPHome 2026.8.x: ESP32Preferences::nvs_handle is public and reachable
//     through esphome::global_preferences; the preference key string is the
//     decimal uint32_to_str() of the 32-bit key; the namespace is "esphome";
//     load() serves the pending save queue first and sync() reports one
//     aggregate result (which is why FB keys are written only directly);
//     a failed nvs_open() erases the whole partition;
//   ESP-IDF 5.5.x: nvs_set_blob() returns INVALID_HANDLE / READ_ONLY /
//     NOT_INITIALIZED only before any flash access; the overwrite order
//     (new chunk, new index, erase old index, erase old chunk); the
//     read-side CRC erase; nvs_get_stats() reporting an INVALID page; the
//     24-bit item hash used by the ACTIVE-page duplicate erase at init.
// A compile error on an upgrade forces a deliberate re-verification of
// those facts (re-run registry/tests/check_fbb_esphome_source_facts.py
// against the new source, then bump the bounds here) instead of a silent
// change of durable semantics.
//
// esphome/core/version.h is the file ESPHome GENERATES per build
// (esphome/writer.py); the copy shipped inside the ESPHome Python package
// is an IDE placeholder (2099.12.0) and would fail the pin, which is
// intended.

#include "esphome/core/version.h"
#include "esp_idf_version.h"

static_assert(ESPHOME_VERSION_CODE >= VERSION_CODE(2026, 8, 2) && ESPHOME_VERSION_CODE < VERSION_CODE(2026, 9, 0),
              "ecco_fbdurable: ESPHome preference facts verified for 2026.8.x (>= 2026.8.2) only - re-verify, then bump");
static_assert(ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 5, 5) && ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 6, 0),
              "ecco_fbdurable: ESP-IDF NVS facts verified for 5.5.x (>= 5.5.5) only - re-verify, then bump");
