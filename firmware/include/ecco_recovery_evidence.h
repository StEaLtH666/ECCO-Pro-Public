#pragma once

// PR 1 of 3 - Free Power operator recovery: READ-ONLY evidence fingerprint.
//
// This header defines nothing durable: no preference key, no schema, no
// marker. It exists purely so the canonical 64-bit FNV-1a evidence
// fingerprint byte order can be pinned ONCE and reused identically by the
// firmware (free_power_recovery_review, in
// firmware/ecco_clock_dongle_stage3_4_free_power.yaml) and by an
// independent Python re-implementation used for offline test vectors (see
// registry/free_power_recovery_evidence.py and
// registry/tests/test_free_power_recovery_evidence.py). Nothing in this
// header performs Modbus I/O, touches ecco_durable's preference records, or
// writes to the inverter - see ecco_durable_snapshot.h for that.

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace ecco_recovery_evidence {

// Standard 64-bit FNV-1a constants.
constexpr uint64_t FNV64_OFFSET_BASIS = 0xcbf29ce484222325ULL;
constexpr uint64_t FNV64_PRIME = 0x100000001b3ULL;

inline uint64_t fnv1a64_update(uint64_t hash, const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len; i++) {
    hash ^= data[i];
    hash *= FNV64_PRIME;
  }
  return hash;
}

inline uint64_t fnv1a64_update_str(uint64_t hash, const char *s) {
  return fnv1a64_update(hash, reinterpret_cast<const uint8_t *>(s), strlen(s));
}

// Little-endian, exactly 2 bytes.
inline uint64_t fnv1a64_update_u16le(uint64_t hash, uint16_t v) {
  uint8_t b[2] = {(uint8_t) (v & 0xFF), (uint8_t) ((v >> 8) & 0xFF)};
  return fnv1a64_update(hash, b, sizeof(b));
}

// Little-endian, exactly 4 bytes.
inline uint64_t fnv1a64_update_u32le(uint64_t hash, uint32_t v) {
  uint8_t b[4] = {
    (uint8_t) (v & 0xFF), (uint8_t) ((v >> 8) & 0xFF), (uint8_t) ((v >> 16) & 0xFF), (uint8_t) ((v >> 24) & 0xFF)
  };
  return fnv1a64_update(hash, b, sizeof(b));
}

// Canonical domain-separation tag - the first thing hashed, always. Bumping
// the trailing version suffix is the escape hatch if the canonical field
// order below ever needs to change incompatibly.
constexpr const char *FINGERPRINT_DOMAIN_TAG = "ECCO-FP-RECOVERY-EVIDENCE-v1";

}  // namespace ecco_recovery_evidence
