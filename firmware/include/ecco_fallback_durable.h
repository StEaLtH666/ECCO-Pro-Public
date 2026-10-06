#pragma once

// FB-B0: Fallback durable foundation - the ESP32 NVS ADAPTER, and nothing else.
//
// EspNvs binds the NVS policy of ecco_fallback_durable_model.h to ESPHome's
// own preference store: the "esphome" namespace handle that
// esphome::global_preferences opened, and the decimal key strings ESPHome
// itself uses (uint32_to_str). All logic - the two-step direct read, the
// outcome table, the witness-first transaction, the write latch and the
// health gate - lives in the host-tested model templates.
//
// Pinned by registry/tests/test_fallback_durable_model.py:
//   - this is the ONLY file in the repository allowed to contain
//     nvs_set_blob (or any NVS erase), with exactly one set-blob call site;
//   - the adapter is branch-free: no if, no ?:, no loop, no switch;
//   - EspNvs is the only NVS policy in firmware/, and FB-B0 has ZERO runtime
//     call sites: no firmware YAML lambda references ecco_fbdurable at all
//     (FB-B1 adds the read-only boot / REVIEW paths; FB-B2 the SAVE and
//     INVALIDATE commits, witness first, in the same PR as the first profile
//     write).
// No nvs_commit: it is a no-op in ESP-IDF 5.5.5 (every set is immediate).
//
// esphome::global_preferences is assigned in app_main() (setup_preferences)
// before any component or lambda runs, so it is never null where this is
// used; a zero handle (both nvs_open attempts failed) is handled by the
// model as STORAGE_UNAVAILABLE before any adapter call.

#include <nvs.h>

#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/preferences.h"

#include "ecco_fallback_version_pins.h"
#include "ecco_fallback_durable_model.h"

namespace ecco_fbdurable {

// The model's numeric error codes are exactly IDF 5.5.5's.
static_assert(IDF_OK == ESP_OK && IDF_ERR_NVS_NOT_INITIALIZED == ESP_ERR_NVS_NOT_INITIALIZED &&
                  IDF_ERR_NVS_NOT_FOUND == ESP_ERR_NVS_NOT_FOUND && IDF_ERR_NVS_READ_ONLY == ESP_ERR_NVS_READ_ONLY &&
                  IDF_ERR_NVS_INVALID_HANDLE == ESP_ERR_NVS_INVALID_HANDLE,
              "ecco_fbdurable: IDF error codes drifted from the model's mirror");
static_assert(std::is_same<nvs_handle_t, uint32_t>::value, "ecco_fbdurable: nvs_handle_t is uint32_t");
static_assert(std::is_same<decltype(esphome::ESPPreferences::nvs_handle), uint32_t>::value,
              "ecco_fbdurable: ESPHome's preference store exposes a public uint32_t nvs_handle");
static_assert(esphome::UINT32_MAX_STR_SIZE == sizeof(KeyString), "ecco_fbdurable: decimal key buffer size");

struct EspNvs {
  uint32_t handle() const { return esphome::global_preferences->nvs_handle; }
  int32_t set_blob(uint32_t key, const void *data, size_t len) {
    char k[esphome::UINT32_MAX_STR_SIZE];
    esphome::uint32_to_str(k, key);
    return nvs_set_blob(this->handle(), k, data, len);
  }
  int32_t get_blob(uint32_t key, void *out, size_t *len) {
    char k[esphome::UINT32_MAX_STR_SIZE];
    esphome::uint32_to_str(k, key);
    return nvs_get_blob(this->handle(), k, out, len);
  }
  int32_t get_stats() const {
    nvs_stats_t st{};
    return nvs_get_stats(nullptr, &st);
  }
  // Parenthesised so an Arduino-framework `#define micros()` glue macro can
  // never expand it (esp-idf builds emit no such macro).
  uint32_t now_us() const { return (esphome::micros)(); }
};

// A1 health gate on the real store: RAM-only, no flash I/O, no erase.
inline bool nvs_healthy() { return storage_healthy(EspNvs{}); }

}  // namespace ecco_fbdurable
