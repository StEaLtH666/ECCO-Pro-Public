#pragma once

// Durable, checkable preference commit for ECCO's power-loss recovery snapshots
// (Free Power, Register 244).
//
// Why this exists instead of the existing restore_value: yes globals:
// ESPHome's RestoringGlobalsComponent only queues a changed value for flash
// write from its own 1000ms poll (or on_shutdown); a plain `id(foo) = x;`
// assignment in a lambda never touches the preferences backend by itself, and
// global_preferences->sync() only flushes whatever is already queued - it
// returns true trivially if nothing is queued yet. See
// docs/research/esphome-2026.9.0-durability-modbus-sequencing-audit-2026-09-21.md
// for the full source-verified trace.
//
// commit_record()/load_record() below call ESPPreferenceObject::save() and
// global_preferences->sync() directly, bypassing RestoringGlobalsComponent's
// poll entirely, so the save is queued and (if commit_record returns true)
// flushed to flash synchronously, within the same call.

#include <type_traits>
#include <cstddef>
#include <cstdint>
#include <unordered_map>

#include "esphome/core/preferences.h"
#include "esphome/core/helpers.h"

// SG-06: load_record_status() below asks NVS directly why a load failed.
#include <nvs.h>

// SG-01: the Free Power START journal binding (below) reuses the canonical
// 64-bit FNV-1a constants already pinned for the recovery-evidence
// fingerprint, rather than restating them.
#include "ecco_recovery_evidence.h"

namespace ecco_durable {

// Derives a stable NVS key from a human-readable tag. Two calls with the same
// tag always produce the same key, so this can be used independently at the
// write site and at the boot-time load site without sharing a constant.
inline uint32_t key_for(const char *tag) { return esphome::fnv1_hash(tag); }

// S2 fix (2026-09-27, docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md
// defect ledger): esphome::ESPPreferenceObject (esphome/core/preference_backend.h,
// vendored ESPHome core, not part of this repo) holds its backend as a plain
// non-owning `PreferenceBackend *` with no destructor to release it,
// and esphome::esp32::ESP32Preferences::make_preference()
// (esphome/components/esp32/preferences.cpp) heap-allocates a fresh
// ESP32PreferenceBackend via `new` on EVERY call. sizeof(ESP32PreferenceBackend)
// is 12 bytes (two uint32_t, one uint16_t, two uint8_t, no padding); the
// actual heap allocation is a few bytes larger once the IDF allocator's own
// per-block header is counted. commit_record()/load_record() used to call
// make_preference<T>(key) fresh on every invocation - the normal, documented
// ESPHome usage pattern is to call it ONCE per key at setup and keep the
// returned object for the device's lifetime, which this file's original
// call-every-time pattern did not follow - so every durable commit or load
// leaked one backend allocation forever. With 58 commit_record/load_record
// call sites in firmware/ecco_clock_dongle_stage3_4_free_power.yaml and a
// stuck Dump obligation's watchdog re-driving a commit roughly every 15s,
// that is ~5760 leaked allocations/day, matching the ledger's "~92 KB/day"
// estimate.
//
// Fix, at the narrowest possible layer (this file only - no change to
// vendored ESPHome core, no change to any firmware call site's own
// commit_record()/load_record() call): cache one ESPPreferenceObject per
// (T, key) pair the first time it is needed, in a function-local static map
// keyed by `key` (distinct record types never share this cache, since each
// is a separate template instantiation of preference_for<T> with its own
// static local `cache`), and reuse it on every later call for that same
// key. This makes make_preference<T>() run exactly once per distinct
// (T, key) pair for the life of the device - 10 tags are used by this
// firmware today (8 before SG-01 added FREE_POWER_START_JOURNAL_TAG; Dump V2
// added DUMP_TO_GRID_DATA_TAG_V1 for its rollback tombstone), so at most 10
// one-time allocations total, never growing further -
// instead of once per call. A reference into an unordered_map stays valid
// across further insertions (only erasure invalidates it, and this cache
// never erases), so returning `it->second` by reference here is safe even
// though the very first commit for a new key can trigger a rehash of
// entries already cached under other keys.
template<typename T> inline esphome::ESPPreferenceObject &preference_for(uint32_t key) {
  static std::unordered_map<uint32_t, esphome::ESPPreferenceObject> cache;
  auto it = cache.find(key);
  if (it == cache.end()) {
    it = cache.emplace(key, esphome::global_preferences->make_preference<T>(key)).first;
  }
  return it->second;
}

// Writes `record` under `key` and durably flushes it before returning.
// Returns true only if BOTH the queue step and the flash sync succeeded -
// callers must not treat this record as committed otherwise, and must not
// perform a dependent hardware write.
template<typename T> inline bool commit_record(uint32_t key, const T &record) {
  static_assert(std::is_trivially_copyable<T>::value, "ecco_durable record must be trivially copyable");
  auto &pref = preference_for<T>(key);
  if (!pref.save(&record))
    return false;
  return esphome::global_preferences->sync();
}

// Loads `record` from `key`. Returns false if no matching data exists yet
// (first boot) or the stored size does not match T (schema change) - either
// way `record` must be treated as not present. It ALSO returns false when
// NVS could not be read at all (see SG-06 below): a caller for which absence
// means "no recovery obligation" must use load_record_status() instead.
template<typename T> inline bool load_record(uint32_t key, T &record) {
  auto &pref = preference_for<T>(key);
  return pref.load(&record);
}

// SG-06 (boot-time durable-read fail-closed). load_record() returns a bare
// bool because ESP32PreferenceBackend::load() (esphome/components/esp32/
// preferences.cpp, vendored ESPHome 2026.8.2, not part of this repo) does:
// ESP_ERR_NVS_NOT_FOUND (key genuinely never written), a stored-length
// mismatch, ESP_ERR_NVS_INVALID_HANDLE (ESP32Preferences::open() left
// nvs_handle 0 after its erase-and-retry nvs_open also failed) and any other
// nvs_get_blob() error all come back as the same `false`. For a validity
// marker, whose ABSENCE is the only evidence that no recovery obligation
// exists, that turns "could not establish whether an obligation exists" into
// "there is no obligation".
//
// load_record_status() is the same load through the same cached preference
// object (so the S2 cache and ESPHome's pending-save lookup behave exactly
// as in load_record(): LOAD_OK iff load_record() would have returned true).
// Only on failure does it ask NVS WHY - one read-only nvs_get_blob() length
// probe on ESPHome's own handle, with the same decimal key string ESPHome
// itself uses. No allocation, no write, no erase, no retry.
//   LOAD_ABSENT      ESP_ERR_NVS_NOT_FOUND: nothing was ever stored under
//                    this key. The ONLY result that is evidence of absence.
//   LOAD_WRONG_SIZE  something IS stored under this key, but not sizeof(T)
//                    bytes - it cannot be this record.
//   LOAD_READ_ERROR  anything else: NVS unavailable (handle 0), any other
//                    nvs_get_blob() error, or the length matched but the
//                    data read itself failed. Existence is UNKNOWN.
enum LoadStatus : uint8_t {
  LOAD_OK = 0,
  LOAD_ABSENT = 1,
  LOAD_WRONG_SIZE = 2,
  LOAD_READ_ERROR = 3,
};

inline LoadStatus classify_load_failure(uint32_t key, size_t expected_len) {
  auto *prefs = esphome::global_preferences;
  if (prefs == nullptr || prefs->nvs_handle == 0)
    return LOAD_READ_ERROR;
  char key_str[esphome::UINT32_MAX_STR_SIZE];
  esphome::uint32_to_str(key_str, key);
  size_t stored_len = 0;
  esp_err_t err = nvs_get_blob(prefs->nvs_handle, key_str, nullptr, &stored_len);
  if (err == ESP_ERR_NVS_NOT_FOUND)
    return LOAD_ABSENT;
  if (err != ESP_OK)
    return LOAD_READ_ERROR;
  if (stored_len != expected_len)
    return LOAD_WRONG_SIZE;
  return LOAD_READ_ERROR;
}

template<typename T> inline LoadStatus load_record_status(uint32_t key, T &record) {
  auto &pref = preference_for<T>(key);
  if (pref.load(&record))
    return LOAD_OK;
  return classify_load_failure(key, sizeof(T));
}

// Magic stamped into every validity marker so a marker record can be told
// apart from zero-initialized/garbage NVS data of the right size.
constexpr uint32_t VALID_MARKER_MAGIC = 0x45434356u;  // 'ECCV'

// The marker is a small durable state machine, not a bool. A verified
// hardware restore must be recorded BEFORE the marker is cleared, so a power
// cut between "restore verified" and "marker cleared" does not reconstruct a
// stale recovery obligation on reboot (2026-09-21 follow-up review) - see
// docs/research/esphome-2026.9.0-durability-modbus-sequencing-audit-2026-09-21.md.
//
//   CLEAR                       no recovery obligation.
//   RESTORE_REQUIRED            snapshot data is durable; the inverter may
//                                (or may not yet) have been written from it;
//                                on boot, recover using the snapshot data.
//   RESTORE_VERIFIED_PENDING_CLEAR
//                                the hardware restore has ALREADY been
//                                verified - no inverter write may occur for
//                                this state, on boot or in any runtime. Only
//                                a durable commit back to CLEAR remains.
enum MarkerState : uint8_t {
  MARKER_CLEAR = 0,
  MARKER_RESTORE_REQUIRED = 1,
  MARKER_RESTORE_VERIFIED_PENDING_CLEAR = 2,
};

struct ValidMarker {
  uint32_t magic;
  uint8_t state;  // one of MarkerState
};

// Phase A payload for the Free Power override snapshot. Mirrors every field
// start_free_power_override / restore_free_power_snapshot need to restore the
// inverter exactly - see those scripts in
// firmware/ecco_clock_dongle_stage3_4_free_power.yaml.
//
// 2026-09-22 hardening (blocker 3, corrective pass): added `reg230_intended`
// - the ONE piece of Free Power's INTENDED (active-override) state that is
// not already deterministically derivable from the fields above, needed so
// the restore-time recovery classifier can tell "live still matches what
// ECCO intended" apart from "live matches neither the original snapshot nor
// the intended state" (unexplained drift/partial landing) - see
// FREE_POWER_DATA_TAG below and restore_free_power_snapshot_dispatch. Every
// other owned-register intended value IS deterministic from the fields
// already here and is recomputed at the call site rather than duplicated:
//   reg232_intended  = reg232 | 0x0001            (grid-charge bit forced on)
//   reg268..273_intended = 100                    (all six slots forced to 100% SOC)
//   reg274..279_intended = (regN & 0xFFFC) | 0x0001 (source bits forced to Grid)
// This field was ADDED, which changes sizeof(FreePowerSnapshotData) - see
// the OTA/schema-version safety rules below: this alone is why
// FREE_POWER_DATA_TAG was bumped to a new "_v2" tag rather than kept as
// "_v1" (rule 1 - a new tag, not rule 2's same-tag same-size-check reliance
// - is the one this codebase actually applies here, since rule 1 is always
// preferred "whenever there is any doubt").
//
// 2026-09-23 hardening (TOU Power / registers 256-261 ownership promotion):
// added `reg_tou_power_intended`. Post-reboot live characterisation
// (CURRENT_STATE.md "Post-reboot inverter characterization") proved
// registers 256-261 (TOU Power) are the inverter's native battery
// charge/discharge power ceiling, in both Zero Export and Allow Export
// Load Limit modes - not a cosmetic display field. Free Power previously
// treated 256-261 as WITNESSED ONLY (read and logged, never written or
// gated on) specifically so a legitimate third-party TOU Power change
// during an override would not cause a false RESTORE VERIFY FAILED.
// That stance is now obsolete: because TOU Power actually caps battery
// discharge/charge, leaving it witness-only meant Free Power's requested
// override power could be silently capped by whatever TOU Power ceiling
// happened to be active in the current slot - the override was not fully
// authoritative. Free Power now OWNS 256-261: it overlays all six slots to
// the requested/effective override wattage (so a lease surviving a TOU
// slot boundary keeps the same ceiling in every slot) and restores the
// exact original per-slot values afterward, exactly like every other
// owned register. `reg_tou_power_intended` is the one piece of that
// INTENDED state that is not deterministically derivable from the fields
// already here (unlike reg268..279's intended values, which are pure
// functions of the snapshot) - it is the requested/effective wattage
// actually used for the transaction, needed by the restore-time
// classifier so a reboot mid-lease can still tell "live matches what
// ECCO intended for TOU Power" apart from unexplained drift. This is
// another field ADDED to the struct, so per rule 1 below the tag is
// bumped again, to "_v3" - reg256..261 themselves are unchanged (already
// present in the v2 struct as the ORIGINAL snapshot; only the INTENDED
// value is new).
// 2026-09-24 hardening (PR-A: register-244 active-lease context): added
// `reg244_lease_context_plus1`. Register 244 (Load/Export Mode: 0=Allow
// Export, 1=Essentials, 2=Zero Export) changes the operating context/meaning
// of TOU Power (256-261). If an external actor changes 244 while a Free
// Power lease is outstanding, ECCO must not automatically restore its owned
// registers back into a DIFFERENT 244 context without fresh proof the
// context still matches the one the lease started under - see
// restore_free_power_snapshot_dispatch's pre-write and pre-floor context
// gates in firmware/ecco_clock_dongle_stage3_4_free_power.yaml.
//
// FAIL-CLOSED "plus-one" encoding (deliberately NOT the raw 0/1/2 register
// value):
//   0 = context not captured / invalid / unknown
//   1 = raw register 244 value 0 (Allow Export)
//   2 = raw register 244 value 1 (Essentials)
//   3 = raw register 244 value 2 (Zero Export)
//   >3 = invalid/corrupt
// Zero is deliberately INVALID rather than meaning "Allow Export": a
// zero-initialized struct (e.g. a rebuild site that forgets to populate this
// field) must never be silently read back as a valid, live-matchable
// context - it must fail closed as "context unknown" instead.
//
// THIS FIELD DOES NOT CHANGE sizeof(FreePowerSnapshotData) - IT MUST NOT
// REUSE THE V3 TAG. Field-by-field layout of the V3 struct above (25
// fields: one uint32_t, two uint8_t, twenty-two uint16_t) packs to exactly
// 50 bytes of raw data with no internal padding, then pads to a 52-byte
// struct size (rounded up to the 4-byte alignment `end_epoch` requires) -
// i.e. V3 already carries 2 bytes of unused tail padding. Appending this ONE
// extra uint16_t below lands exactly in those 2 previously-unused padding
// bytes: the new raw data size is 52 bytes, already a multiple of 4, so no
// further tail padding is added. sizeof(FreePowerSnapshotData) is 52 for
// BOTH the V3 layout (without this field) and the V4 layout (with it) - the
// struct literally cannot tell V3 and V4 apart by size the way rule 2 below
// normally allows. A V3 record loaded under a reused tag would therefore
// pass load_record()'s length check and be silently misread as V4, with
// this field reading whatever value happened to occupy V3's tail padding -
// not a reliable "0 = unknown" signal. The tag bump below (rule 1, not rule
// 2) is what actually separates V3 from V4 here; sizeof deliberately cannot.
struct FreePowerSnapshotData {
  uint32_t end_epoch;
  uint8_t active_persisted;
  uint8_t restore_requested;
  uint16_t reg230;
  uint16_t reg232;
  uint16_t reg256;
  uint16_t reg257;
  uint16_t reg258;
  uint16_t reg259;
  uint16_t reg260;
  uint16_t reg261;
  uint16_t reg268;
  uint16_t reg269;
  uint16_t reg270;
  uint16_t reg271;
  uint16_t reg272;
  uint16_t reg273;
  uint16_t reg274;
  uint16_t reg275;
  uint16_t reg276;
  uint16_t reg277;
  uint16_t reg278;
  uint16_t reg279;
  uint16_t reg230_intended;
  // 2026-09-23 hardening: the intended (requested/effective) TOU Power
  // wattage applied to ALL SIX of registers 256-261 for the duration of
  // this transaction - see the header comment above this struct.
  uint16_t reg_tou_power_intended;
  // 2026-09-24 hardening (PR-A): the register-244 lease context captured
  // fresh, immediately before this transaction's first inverter write - see
  // the comment above this struct. Fail-closed "plus-one" encoding: 0 =
  // unknown/invalid, 1..3 = raw 244 value 0..2, >3 = corrupt.
  uint16_t reg244_lease_context_plus1;
};

// Phase A payload for the Register 244 (Load/Export Mode) proof snapshot.
struct Reg244SnapshotData {
  uint16_t value;
};

// Payload for the Manual Dump-to-Grid V1 transaction snapshot. Mirrors every
// field start_dump_to_grid_override / restore_dump_to_grid_snapshot need to
// restore the inverter exactly - see those scripts in
// firmware/ecco_clock_dongle_stage3_4_free_power.yaml.
//
// Deliberately NOT modelled on the full FreePowerSnapshotData shape: Dump-to-
// Grid's write surface is exactly {244, 256, 257, 258, 259, 260, 261} - see
// docs/DUMP_TO_GRID_V1.md for the register-by-register justification for why
// 268-279 (six per-slot charge-target SOC / charge-source-and-mode fields)
// are witnessed only, never written, by this feature. Register 244's
// "intended" value during an active Dump lease is always the constant 0
// (Allow Export) and is not stored - only `reg_dump_power_intended` needs to
// be recorded, for the same reason FreePowerSnapshotData.reg_tou_power_intended
// exists: it is the one piece of Dump's INTENDED state that is not
// deterministically derivable from anything else already in this record.
//
// `reg_dump_power_intended` is the BATTERY DISCHARGE CEILING associated with
// this transaction, applied to all six of 256-261 - it is NOT the
// user-requested net export target. Initially (2026-09-27, V1.2 bounded
// feed-forward START) it is the feed-forward-computed or conservative-
// fallback ceiling chosen at START; later, each time the durable record is
// re-committed, it is rewritten with the closed-loop controller's latest
// VERIFIED ceiling - see start_dump_to_grid_override / dump_controller_tick
// in firmware/ecco_clock_dongle_stage3_4_free_power.yaml. Before V1.2 the
// requested export target and this ceiling were always numerically equal at
// START, which the firmware's own on_boot loader used to rely on for
// display; that equality no longer holds in general, so on_boot loads this
// field into dump_target_power (the ceiling) only, and deliberately leaves
// the user-requested export target (dump_target_export_power) at its
// RAM-only default - the export target is never persisted at all, exactly
// like Stop SOC below, since a reboot never resumes a Dump lease.
//
// Stop SOC (the user's requested minimum battery percentage) is deliberately
// NOT part of this durable record. It is enforced entirely in software
// against the existing trusted ecco_battery_soc sensor while ACTIVE, and is
// never written to any inverter register. Because it is not persisted, a
// reboot while a Dump lease is active cannot safely resume enforcing it -
// see the Dump-to-Grid block in the firmware's on_boot lambda, which forces
// restore_requested for any record loaded with active_persisted set, so the
// watchdog ends and restores the lease rather than resuming it blind.
//
// Dump V2 ownership evidence (2026-09-29): added `reg_dump_power_pending`.
// Before V2, the closed-loop controller's dynamic 256-261 ceilings lived
// only in RAM, so after a reboot the durable record could not say which
// ceiling Dump itself may have left live - a later ownership-aware restore
// could not tell Dump's own residue from a third-party/front-panel change.
// V2 records, per lease, the evidence set a future classifier needs; for
// each of registers 256-261 (index i) Dump may have left live ONLY:
//   ORIGINAL[i]              (reg256..reg261 above - the START snapshot)
//   reg_dump_power_intended  the ceiling Dump last committed as current;
//                            the live value before the next ceiling write
//   reg_dump_power_pending   the next ceiling, whose write MAY have landed
// Scalar fields suffice because START and dump_controller_tick both only
// ever write one common ceiling to all six registers ({p,p,p,p,p,p}); a
// per-register partial landing still leaves each register at either its
// prior value or `p`, both of which are in the set.
//
// Maintenance (write-ahead, the SG-01 principle, no separate journal):
//   - START's pre-write commit records intended = pending = C0 (the START
//     ceiling). Nothing has been written yet; ORIGINAL covers that state.
//   - For each dynamic controller write, once the bus/lock checks pass and
//     BEFORE R3's pre-write ownership read and the FC16 write,
//     dump_controller_tick sets the RAM pending mirror to the new ceiling P,
//     then commits intended = V (the verified ceiling, dump_target_power),
//     pending = P. If that commit fails, neither R3's read nor the write is
//     issued, and the lease fails closed through request_dump_end. R3 itself
//     is unchanged: it still requires all six registers to read V.
//   - Only after the exact six-register readback does V advance to P, in
//     RAM only (dump_target_power). No extra commit is needed, because the
//     durable {V, P} already contains the verified value. The next commit
//     of any kind (the next pre-write commit, request_dump_end) catches up.
//     V for that next commit always comes from RAM, never from the durable
//     record, which may still hold the previous V.
//   - EVERY rebuild site (START, the ACTIVE commit, request_dump_end, the
//     controller) writes `pending` from the RAM mirror
//     dump_evidence_pending_ceiling, which on_boot reloads, so no re-commit
//     - before or after a reboot - can drop a possibly-landed ceiling.
// So exactly ONE extra durable commit per controller write attempt. 0 is
// never a "none" sentinel: both fields always hold a real ceiling.
//
// NOTHING READS THIS EVIDENCE YET. Restore, Force Restore Original and
// Accept Current State are unchanged and still ownership-blind (they use
// only the ORIGINAL fields); the ownership classifier is a later PR. The
// offline reference model is registry/tests/_dump_v2_evidence_model.py.
//
// V2 DOES NOT CHANGE sizeof(DumpToGridSnapshotData) - IT MUST NOT REUSE
// THE V1 TAG. The V1 layout (DumpToGridSnapshotDataV1 below) is one
// uint32_t, two uint8_t and eight uint16_t = 22 bytes of data, padded to 24
// for end_epoch's 4-byte alignment. The new uint16_t lands exactly in those
// 2 padding bytes, so V2 is also 24 bytes (no padding at all). A V1 record
// read under a reused tag would pass load_record()'s size check and be
// silently misread, with `reg_dump_power_pending` taken from V1's padding.
// Only the tag bump (DUMP_TO_GRID_DATA_TAG_V2 below) separates them - the
// same situation as FreePowerSnapshotData's V3 -> V4 bump.
struct DumpToGridSnapshotData {
  uint32_t end_epoch;
  uint8_t active_persisted;
  uint8_t restore_requested;
  uint16_t reg244;
  uint16_t reg256;
  uint16_t reg257;
  uint16_t reg258;
  uint16_t reg259;
  uint16_t reg260;
  uint16_t reg261;
  uint16_t reg_dump_power_intended;
  // Dump V2: the ceiling whose write may have landed - see above.
  uint16_t reg_dump_power_pending;
};

// The retired V1 layout. Never read as a snapshot by this firmware. It is
// used for exactly two things: the build proves the size collision that
// makes the tag bump mandatory (static_asserts below), and START commits the
// V1 rollback TOMBSTONE in this shape under DUMP_TO_GRID_DATA_TAG_V1 (see
// DUMP_V1_TOMBSTONE_REG244). on_boot's fail-closed branch also loads it,
// read-only, only to name a legacy V1 obligation in the log.
struct DumpToGridSnapshotDataV1 {
  uint32_t end_epoch;
  uint8_t active_persisted;
  uint8_t restore_requested;
  uint16_t reg244;
  uint16_t reg256;
  uint16_t reg257;
  uint16_t reg258;
  uint16_t reg259;
  uint16_t reg260;
  uint16_t reg261;
  uint16_t reg_dump_power_intended;
};

// Layout pins (mirrored byte-for-byte by registry/tests/_dump_v2_evidence_model.py,
// which registry/tests/test_dump_v2_ownership_evidence.py checks against
// these lines).
static_assert(sizeof(DumpToGridSnapshotData) == 24, "Dump V2 record must be exactly 24 bytes");
static_assert(offsetof(DumpToGridSnapshotData, end_epoch) == 0 &&
                  offsetof(DumpToGridSnapshotData, active_persisted) == 4 &&
                  offsetof(DumpToGridSnapshotData, restore_requested) == 5 &&
                  offsetof(DumpToGridSnapshotData, reg244) == 6 && offsetof(DumpToGridSnapshotData, reg256) == 8 &&
                  offsetof(DumpToGridSnapshotData, reg257) == 10 && offsetof(DumpToGridSnapshotData, reg258) == 12 &&
                  offsetof(DumpToGridSnapshotData, reg259) == 14 && offsetof(DumpToGridSnapshotData, reg260) == 16 &&
                  offsetof(DumpToGridSnapshotData, reg261) == 18 &&
                  offsetof(DumpToGridSnapshotData, reg_dump_power_intended) == 20 &&
                  offsetof(DumpToGridSnapshotData, reg_dump_power_pending) == 22,
              "Dump V2 field offsets must be 0/4/5/6/8/10/12/14/16/18/20/22");
static_assert(sizeof(DumpToGridSnapshotDataV1) == 24 &&
                  offsetof(DumpToGridSnapshotDataV1, reg_dump_power_intended) == 20,
              "Dump V1 record is 24 bytes (22 data + 2 tail padding)");
static_assert(sizeof(DumpToGridSnapshotData) == sizeof(DumpToGridSnapshotDataV1),
              "V1 and V2 are the SAME size: only the tag bump separates them");
static_assert(std::is_trivially_copyable<DumpToGridSnapshotData>::value, "ecco_durable record must be trivially copyable");

// Dump V2 rollback tombstone. start_dump_to_grid_override commits a
// value-initialised DumpToGridSnapshotDataV1 with reg244 = this value under
// DUMP_TO_GRID_DATA_TAG_V1, BEFORE the V2 data record and the
// RESTORE_REQUIRED marker. Pre-V2 firmware (main @ 004040b and earlier)
// accepts a V1 record only if reg244 <= 2, so after a rollback while a V2
// obligation is open, it finds the shared marker plus this tombstone and
// fails closed (RECOVERY BLOCKED, SG-02 containment armed). It never
// restores a stale V1 snapshot left over from an older lease. No real
// snapshot can carry it, because START refuses an original 244 above 2.
constexpr uint16_t DUMP_V1_TOMBSTONE_REG244 = 0xFFFF;
static_assert(DUMP_V1_TOMBSTONE_REG244 > 2, "the V1 tombstone must fail the pre-V2 loader's reg244 <= 2 check");

// Tags for key_for(); kept together here so the write site and the
// boot-time load site can never drift apart.
//
// 2026-09-22 hardening (blocker 3, corrective pass): FreePowerSnapshotData
// grew a field (reg230_intended - see the struct above), so per rule 1
// below, the tag was bumped rather than reused. FREE_POWER_DATA_TAG_V1 is
// kept, unchanged and unused, purely as a documented historical record that
// this tag/schema pair existed and is retired - not repurposed, not read or
// written by anything in this firmware anymore. FREE_POWER_DATA_TAG (no
// suffix) is a stable alias that always names the CURRENT schema's tag, so
// call sites do not need to change again on some future bump; as of the
// 2026-09-24 PR-A bump below, it currently points at V4. FREE_POWER_VALID_TAG
// (the marker) is unchanged - the marker struct's layout did not change,
// only the paired data record's did.
//
// 2026-09-23 hardening (TOU Power / registers 256-261 ownership promotion):
// FreePowerSnapshotData grew another field (reg_tou_power_intended - see
// the struct above), so the tag is bumped again to "_v3" for the same
// reason as the v1->v2 bump: a grown struct read under an old tag would
// otherwise be a length mismatch that load_record() already treats as
// "not present" (safe), but rule 1 (a new tag) is preferred over relying
// on that whenever there is any doubt. FREE_POWER_DATA_TAG_V2 is kept,
// unchanged and unused, as the same kind of documented historical record
// FREE_POWER_DATA_TAG_V1 already is.
//
// 2026-09-24 hardening (PR-A: register-244 active-lease context): grew
// another field (reg244_lease_context_plus1 - see the struct above), so the
// tag is bumped again to "_v4". This bump is MANDATORY, not merely
// preferred: unlike every earlier bump, appending this field does NOT
// change sizeof(FreePowerSnapshotData) (see the struct comment - V3 already
// carried 2 bytes of tail padding that this field exactly fills), so rule
// 2's "a grown struct fails the length check" safety net would NOT fire
// here - a V3 record read back under a reused tag would be silently
// misinterpreted as a V4 record. FREE_POWER_DATA_TAG_V3 is kept, unchanged
// and unused, as the same kind of documented historical record
// FREE_POWER_DATA_TAG_V1/V2 already are - firmware must use only the
// FREE_POWER_DATA_TAG alias below, which now points at V4. A durable
// RESTORE_REQUIRED marker whose only data record is under the old V3 tag
// therefore has NO V4 record to load (load_record() against the V4 tag
// simply finds nothing, the normal "not present" outcome) and must fail
// closed exactly like any other missing/unreadable data record - there is
// no migration of an outstanding V3 obligation across this bump, matching
// this file's own OTA rule below (never flash across an incompatible Free
// Power schema while the marker is non-CLEAR).
constexpr const char *FREE_POWER_DATA_TAG_V1 = "ecco_free_power_snapshot_data_v1";
constexpr const char *FREE_POWER_DATA_TAG_V2 = "ecco_free_power_snapshot_data_v2";
constexpr const char *FREE_POWER_DATA_TAG_V3 = "ecco_free_power_snapshot_data_v3";
constexpr const char *FREE_POWER_DATA_TAG_V4 = "ecco_free_power_snapshot_data_v4";
constexpr const char *FREE_POWER_DATA_TAG = FREE_POWER_DATA_TAG_V4;
constexpr const char *FREE_POWER_VALID_TAG = "ecco_free_power_snapshot_valid_v1";
constexpr const char *REG244_DATA_TAG = "ecco_reg244_snapshot_data_v1";
constexpr const char *REG244_VALID_TAG = "ecco_reg244_snapshot_valid_v1";

// Manual Dump-to-Grid V1 (2026-09-26). New feature, new tags from the start.
// Any future change to DumpToGridSnapshotData must follow the same rule 1
// (new tag, never reuse) documented below.
//
// Dump V2 ownership evidence (2026-09-29): DumpToGridSnapshotData gained
// reg_dump_power_pending WITHOUT changing its size (see the struct), so the
// data tag is bumped to "_v2". This is MANDATORY, not merely preferred, for
// the same reason as FREE_POWER_DATA_TAG_V4: the size check cannot tell V1
// from V2. DUMP_TO_GRID_DATA_TAG_V1 is kept as the retired historical tag:
// no snapshot is ever read from it, and the snapshot alias
// DUMP_TO_GRID_DATA_TAG now points at V2. It is written only with the
// rollback tombstone (see DUMP_V1_TOMBSTONE_REG244), and read only by
// on_boot's diagnostic legacy probe. There is NO migration: V1 bytes are
// never read under V2 semantics. A RESTORE_REQUIRED marker whose only data
// record is a legacy V1 record therefore finds no V2 record at boot and
// fails closed through the existing "data record unreadable or invalid" path
// (RECOVERY BLOCKED, writes locked, SG-02 containment armed - never CLEAR,
// never SG-06's UNKNOWN). Nothing is cleared or overwritten: boot commits
// nothing, and request_dump_end, the restore worker and Accept Current State
// all refuse while dump_recovery_metadata_corrupt is set.
// DUMP_TO_GRID_VALID_TAG (the marker) is deliberately NOT bumped: its layout
// did not change, and older firmware must still see an outstanding Dump
// obligation. The OTA rule below (only flash with every marker CLEAR) still
// applies.
constexpr const char *DUMP_TO_GRID_DATA_TAG_V1 = "ecco_dump_to_grid_snapshot_data_v1";
constexpr const char *DUMP_TO_GRID_DATA_TAG_V2 = "ecco_dump_to_grid_snapshot_data_v2";
constexpr const char *DUMP_TO_GRID_DATA_TAG = DUMP_TO_GRID_DATA_TAG_V2;
constexpr const char *DUMP_TO_GRID_VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1";

// 2026-09-22 Free Power firmware hardening (see docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md
// F4/R3 and the "Free Power firmware hardening" task). Durable retry/lockout
// state for the automatic (watchdog-driven) restore path: once a SECOND
// consecutive verify mismatch happens, automatic hardware writes must stop
// until a human acts, and that must remain true even across a reboot -
// otherwise a reboot would silently re-authorise the exact unattended
// retries this exists to prevent. Deliberately a SEPARATE record/tag from
// FreePowerSnapshotData/ValidMarker above, not a new field bolted onto
// either of them:
//   - it is retry PACING, not the recovery obligation itself - the
//     obligation is, and remains, whatever FREE_POWER_VALID_TAG /
//     FREE_POWER_DATA_TAG already say it is, independent of this record;
//   - keeping it separate means it can safely default to "automatic
//     retries permitted" (all-zero / absent) without that default ever
//     being mistaken for "no restore obligation exists" - those are
//     orthogonal questions answered by two different durable records.
// A load failure here (absent, or wrong size after some future firmware
// changed this struct) MUST default to "automatic retries permitted"
// (fail OPEN on pacing only) - never to "operator needed", which would be
// an unrecoverable lockout with no way for firmware to durably clear it
// again short of an operator action that itself needs the lockout gone to
// take effect. This is the one deliberate fail-open in this file, and it
// is safe only because it governs pacing, never the underlying obligation.
// SG-06 leaves it unchanged, NVS read errors included (the retry records
// still load through load_record()): an unreadable retry record never
// hides an obligation - the marker/data load decides that - and failing
// it closed would also block the corrective automatic restore.
struct FreePowerRetryState {
  uint8_t operator_needed;  // 1 once a second consecutive verify mismatch has occurred
};
constexpr const char *FREE_POWER_RETRY_TAG = "ecco_free_power_retry_state_v1";

// Same retry-pacing/lockout model as FreePowerRetryState above, kept as its
// own separate record for the same reason: Dump-to-Grid's lockout is
// independent of Free Power's, and this record's absence must fail OPEN
// (automatic retries permitted) rather than being mistaken for "operator
// needed" - see the comment above FreePowerRetryState, which applies here
// unchanged.
struct DumpToGridRetryState {
  uint8_t operator_needed;
};
constexpr const char *DUMP_TO_GRID_RETRY_TAG = "ecco_dump_to_grid_retry_state_v1";

// Cause-aware bounded retry backoff for COMMS failures (hardening target 5).
// Mirrors registry/transaction_state_machine.py's comms_backoff_seconds():
// 15s, 30s, 60s, 120s, then holds at 300s. A pure function of the attempt
// count alone (attempt_number is 1-based: 1 = the delay before the FIRST
// retry) - the caller supplies the count, this never reads or writes any
// state itself.
inline uint32_t comms_backoff_ms(int attempt_number) {
  static const uint32_t table_ms[] = {15000, 30000, 60000, 120000, 300000};
  constexpr int table_len = sizeof(table_ms) / sizeof(table_ms[0]);
  int index = attempt_number - 1;
  if (index < 0) index = 0;
  if (index >= table_len) index = table_len - 1;
  return table_ms[index];
}

// ---------------------------------------------------------------------------
// SG-01: Free Power START journal (Phase 1 schema/binding, Phase 2 commits)
// ---------------------------------------------------------------------------
//
// start_free_power_override issues its four mutation writes as a strict
// prefix (PR #45): B1 = reg232, B2 = reg230, B3 = regs 268-279, B4 = regs
// 256-261, each gated on every earlier success. The journal durably records
// which of those writes START had become ELIGIBLE to issue: bit N is
// committed immediately BEFORE the corresponding write, and if that commit
// fails the write (and every later one) is not issued. A committed bit
// therefore means "this block MAY have been written" - the block can still
// be ORIGINAL (reboot between the commit and the write, or a lost write) -
// and a clear bit means "START never wrote this block".
//
// It is PERMISSION evidence only, never a recovery obligation: the
// FREE_POWER_VALID_TAG marker + FREE_POWER_DATA_TAG snapshot remain the sole
// authority on whether a Free Power recovery exists. Consequently:
//   - a missing, unreadable, wrong-size, malformed or unbound journal is
//     simply "no journal evidence" (RAM valid=false) - it NEVER sets
//     free_power_recovery_metadata_corrupt and never locks anything out;
//   - the journal is never explicitly cleared. Once the marker is CLEAR the
//     journal is inert, and the next START's B1 commit overwrites it;
//   - there is no reset commit: START resets only its RAM mirrors, and the
//     B1 commit is the first durable journal write of a new transaction;
//   - boot only LOADS it (on_boot never commits anything).
//
// Layout (16 bytes, natural alignment, no implicit padding):
//   offset 0  magic            FREE_POWER_START_JOURNAL_MAGIC
//   offset 4  start_attempted  prefix mask: 0, 1, 3, 7 or 15 only
//   offset 5  flags            bit0 = START_VERIFIED; every other bit invalid
//   offset 6  reserved         MUST be zero
//   offset 8  binding          free_power_start_journal_binding() of the
//                              durable FreePowerSnapshotData this START
//                              committed - ties the journal to exactly one
//                              lease, so a stale journal from an earlier
//                              transaction can never vouch for a later one.
//
// START_VERIFIED (v1-narrow): written, best effort, only after the existing
// activation verify has positively verified the lease, and only together
// with start_attempted == 15. Failing to persist it never undoes, rolls back
// or re-verifies an already-verified activation.
//
// Offline mirror: registry/tests/_sg01_journal_model.py (byte-for-byte; the
// golden vectors below are pinned against it by
// registry/tests/test_sg01_journal_phase1_2.py).
constexpr uint32_t FREE_POWER_START_JOURNAL_MAGIC = 0x4543534Au;  // 'ECSJ'

struct FreePowerStartJournal {
  uint32_t magic;
  uint8_t start_attempted;
  uint8_t flags;
  uint16_t reserved;
  uint64_t binding;
};
static_assert(sizeof(FreePowerStartJournal) == 16, "SG-01 START journal record must be exactly 16 bytes");
static_assert(offsetof(FreePowerStartJournal, magic) == 0 && offsetof(FreePowerStartJournal, start_attempted) == 4 &&
                  offsetof(FreePowerStartJournal, flags) == 5 && offsetof(FreePowerStartJournal, reserved) == 6 &&
                  offsetof(FreePowerStartJournal, binding) == 8,
              "SG-01 START journal field offsets must be 0/4/5/6/8");
static_assert(std::is_trivially_copyable<FreePowerStartJournal>::value, "ecco_durable record must be trivially copyable");

// A new record type under a new tag from the start (rule 1 below): nothing
// else was ever stored under this key.
constexpr const char *FREE_POWER_START_JOURNAL_TAG = "ecco_free_power_start_journal_v1";

// start_attempted: the only masks START can ever commit, one per write stage.
constexpr uint8_t FREE_POWER_START_JOURNAL_MASK_B1 = 0x01;  // + reg232
constexpr uint8_t FREE_POWER_START_JOURNAL_MASK_B2 = 0x03;  // + reg230
constexpr uint8_t FREE_POWER_START_JOURNAL_MASK_B3 = 0x07;  // + regs 268-279
constexpr uint8_t FREE_POWER_START_JOURNAL_MASK_B4 = 0x0F;  // + regs 256-261
constexpr uint8_t FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED = 0x01;
constexpr uint8_t FREE_POWER_START_JOURNAL_KNOWN_FLAGS = FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED;

// Binding domain: exactly these 24 ASCII bytes. The array's terminating NUL
// is NOT hashed (see the `sizeof(...) - 1` bound below).
constexpr char FREE_POWER_START_JOURNAL_BINDING_DOMAIN[] = "ECCO-FP-START-JOURNAL-v1";
static_assert(sizeof(FREE_POWER_START_JOURNAL_BINDING_DOMAIN) - 1 == 24, "binding domain is 24 bytes, no NUL");

// One FNV-1a-64 byte step over ecco_recovery_evidence's canonical constants.
// ecco_recovery_evidence::fnv1a64_update*() compute the identical step but
// are not constexpr (strlen / reinterpret_cast), so the compile-time golden
// vectors below could not be evaluated through them.
constexpr uint64_t fnv1a64_step(uint64_t hash, uint8_t byte) {
  return (hash ^ byte) * ecco_recovery_evidence::FNV64_PRIME;
}
constexpr uint64_t fnv1a64_step_u16le(uint64_t hash, uint16_t v) {
  return fnv1a64_step(fnv1a64_step(hash, (uint8_t) (v & 0xFF)), (uint8_t) ((v >> 8) & 0xFF));
}
constexpr uint64_t fnv1a64_step_u32le(uint64_t hash, uint32_t v) {
  return fnv1a64_step_u16le(fnv1a64_step_u16le(hash, (uint16_t) (v & 0xFFFF)), (uint16_t) ((v >> 16) & 0xFFFF));
}

// FNV-1a-64 over: the domain bytes; end_epoch (u32 LE); then reg230, reg232,
// reg256..261, reg268..279, reg230_intended, reg_tou_power_intended,
// reg244_lease_context_plus1 (each u16 LE, FreePowerSnapshotData order).
// active_persisted and restore_requested are deliberately EXCLUDED: they are
// lifecycle flags that legitimately change during a lease (the best-effort
// active_persisted re-commit after verify), so binding them would make the
// journal fail to match its own snapshot.
constexpr uint64_t free_power_start_journal_binding(const FreePowerSnapshotData &s) {
  uint64_t h = ecco_recovery_evidence::FNV64_OFFSET_BASIS;
  for (size_t i = 0; i + 1 < sizeof(FREE_POWER_START_JOURNAL_BINDING_DOMAIN); i++)
    h = fnv1a64_step(h, (uint8_t) FREE_POWER_START_JOURNAL_BINDING_DOMAIN[i]);
  h = fnv1a64_step_u32le(h, s.end_epoch);
  h = fnv1a64_step_u16le(h, s.reg230);
  h = fnv1a64_step_u16le(h, s.reg232);
  h = fnv1a64_step_u16le(h, s.reg256);
  h = fnv1a64_step_u16le(h, s.reg257);
  h = fnv1a64_step_u16le(h, s.reg258);
  h = fnv1a64_step_u16le(h, s.reg259);
  h = fnv1a64_step_u16le(h, s.reg260);
  h = fnv1a64_step_u16le(h, s.reg261);
  h = fnv1a64_step_u16le(h, s.reg268);
  h = fnv1a64_step_u16le(h, s.reg269);
  h = fnv1a64_step_u16le(h, s.reg270);
  h = fnv1a64_step_u16le(h, s.reg271);
  h = fnv1a64_step_u16le(h, s.reg272);
  h = fnv1a64_step_u16le(h, s.reg273);
  h = fnv1a64_step_u16le(h, s.reg274);
  h = fnv1a64_step_u16le(h, s.reg275);
  h = fnv1a64_step_u16le(h, s.reg276);
  h = fnv1a64_step_u16le(h, s.reg277);
  h = fnv1a64_step_u16le(h, s.reg278);
  h = fnv1a64_step_u16le(h, s.reg279);
  h = fnv1a64_step_u16le(h, s.reg230_intended);
  h = fnv1a64_step_u16le(h, s.reg_tou_power_intended);
  h = fnv1a64_step_u16le(h, s.reg244_lease_context_plus1);
  return h;
}

constexpr bool free_power_start_journal_mask_valid(uint8_t mask) {
  return mask == 0 || mask == FREE_POWER_START_JOURNAL_MASK_B1 || mask == FREE_POWER_START_JOURNAL_MASK_B2 ||
         mask == FREE_POWER_START_JOURNAL_MASK_B3 || mask == FREE_POWER_START_JOURNAL_MASK_B4;
}

// Schema + binding validation of a journal that load_record() returned
// (load_record() itself only checks the stored size). Every defect is simply
// "not valid" - the caller must never treat an invalid journal as metadata
// corruption.
constexpr bool free_power_start_journal_valid(const FreePowerStartJournal &j, uint64_t expected_binding) {
  return j.magic == FREE_POWER_START_JOURNAL_MAGIC && j.reserved == 0 &&
         (j.flags & (uint8_t) ~FREE_POWER_START_JOURNAL_KNOWN_FLAGS) == 0 &&
         free_power_start_journal_mask_valid(j.start_attempted) &&
         ((j.flags & FREE_POWER_START_JOURNAL_FLAG_START_VERIFIED) == 0 ||
          j.start_attempted == FREE_POWER_START_JOURNAL_MASK_B4) &&
         j.binding == expected_binding;
}

// Compile-time pins (evaluated by every firmware build). FNV-1a-64 known
// answer, then the golden vectors registry/tests/_sg01_journal_model.py
// reproduces byte-for-byte (registry/tests/test_sg01_journal_phase1_2.py
// parses these lines and checks the Python mirror yields the same values).
static_assert(fnv1a64_step(fnv1a64_step(fnv1a64_step(fnv1a64_step(fnv1a64_step(fnv1a64_step(
                  ecco_recovery_evidence::FNV64_OFFSET_BASIS, 'f'), 'o'), 'o'), 'b'), 'a'), 'r') ==
                  0x85944171F73967E8ULL,
              "FNV-1a-64 known answer ('foobar')");
// SG01_GOLDEN zero: all-zero snapshot.
static_assert(free_power_start_journal_binding(FreePowerSnapshotData{}) == 0x9752C546FF6459E7ULL,
              "SG-01 binding golden vector: all-zero snapshot");
// SG01_GOLDEN typical: {end_epoch, active_persisted, restore_requested, reg230, reg232, reg256..261,
// reg268..279, reg230_intended, reg_tou_power_intended, reg244_lease_context_plus1}.
static_assert(free_power_start_journal_binding(FreePowerSnapshotData{
                  1790003600u, 1, 0, 0x0002, 0x0140, 1000, 1100, 1200, 1300, 1400, 1500, 50, 60, 70, 80, 90, 100,
                  0x0102, 0x0102, 0x0102, 0x0102, 0x0102, 0x0102, 0x0006, 4000, 3}) == 0x2B4C46D4D207B486ULL,
              "SG-01 binding golden vector: typical snapshot");
// SG01_GOLDEN typical_flags_flipped: identical to `typical` except active_persisted/restore_requested -
// the excluded lifecycle flags must not change the binding.
static_assert(free_power_start_journal_binding(FreePowerSnapshotData{
                  1790003600u, 0, 1, 0x0002, 0x0140, 1000, 1100, 1200, 1300, 1400, 1500, 50, 60, 70, 80, 90, 100,
                  0x0102, 0x0102, 0x0102, 0x0102, 0x0102, 0x0102, 0x0006, 4000, 3}) == 0x2B4C46D4D207B486ULL,
              "SG-01 binding excludes active_persisted / restore_requested");
// SG01_GOLDEN all_ones: every bound field at its maximum.
static_assert(free_power_start_journal_binding(FreePowerSnapshotData{
                  0xFFFFFFFFu, 0xFF, 0xFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF,
                  0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF,
                  0xFFFF, 0xFFFF}) == 0x9FFACD2E50744DADULL,
              "SG-01 binding golden vector: all-ones snapshot");

// Validation pins: every accepted shape and every rejection class.
static_assert(free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 0, 0, 0, 7}, 7) &&
                  free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 1, 0, 0, 7}, 7) &&
                  free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 3, 0, 0, 7}, 7) &&
                  free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 7, 0, 0, 7}, 7) &&
                  free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 15, 0, 0, 7}, 7) &&
                  free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 15, 1, 0, 7}, 7),
              "SG-01 journal: prefix masks 0/1/3/7/15 and 15+START_VERIFIED are valid");
static_assert(!free_power_start_journal_valid(FreePowerStartJournal{0x4543534Bu, 1, 0, 0, 7}, 7),
              "SG-01 journal: wrong magic rejected");
static_assert(!free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 1, 0, 1, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 1, 0, 0x8000, 7}, 7),
              "SG-01 journal: non-zero reserved rejected");
static_assert(!free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 15, 0x02, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 15, 0x80, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 15, 0xFF, 0, 7}, 7),
              "SG-01 journal: unknown flag bits rejected");
static_assert(!free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 2, 0, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 5, 0, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 14, 0, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 16, 0, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 31, 0, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 255, 0, 0, 7}, 7),
              "SG-01 journal: non-prefix start_attempted masks rejected");
static_assert(!free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 0, 1, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 1, 1, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 3, 1, 0, 7}, 7) &&
                  !free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 7, 1, 0, 7}, 7),
              "SG-01 journal: START_VERIFIED with a partial mask rejected");
static_assert(!free_power_start_journal_valid(FreePowerStartJournal{FREE_POWER_START_JOURNAL_MAGIC, 15, 1, 0, 7}, 8),
              "SG-01 journal: binding mismatch rejected");

// ---------------------------------------------------------------------------
// OTA / schema-version safety (hardening target 9)
// ---------------------------------------------------------------------------
//
// None of the structs above carry a CRC or an explicit version field, and
// that is a deliberate choice, not an oversight: ESPPreferenceObject::load()
// (see commit_record()/load_record() above) already refuses to interpret
// stored bytes whose length does not match sizeof(T) for the type requested
// at the call site - see the "_v1" suffix already present on every tag
// above, which exists for exactly this reason.
//
// The rule any future change to these structs (or to a new struct sharing
// one of these tags) MUST follow:
//
//   1. NEVER change a struct's layout while keeping its existing tag. Bump
//      the tag's version suffix instead (_v1 -> _v2 -> ...) and add a new
//      constant; do not repurpose an old one. This guarantees an
//      old-schema record is simply NOT FOUND under the new tag (load_record
//      returns false, the normal/only route to "not present"), never
//      misread as a new-schema record - the exact "reinterpret old bytes as
//      a new record" failure this rule exists to rule out.
//   2. Growing a struct (adding fields) while KEEPING its tag is safe only
//      because it changes sizeof(T), so an old, smaller stored record fails
//      the length check and load_record() returns false - the caller must
//      still treat that fail-closed per the marker rules in this file (see
//      MarkerState and every on_boot loader in the firmware). Prefer rule 1
//      (a new tag) whenever there is any doubt.
//   3. A marker whose magic or state does not parse (MarkerState::MALFORMED
//      in the recovery-classifier-v2 model; the boot-time `marker_malformed`
//      check in the firmware) must NEVER be coerced to CLEAR or guessed as
//      RESTORE_REQUIRED - this is already enforced and must stay that way
//      through any future schema change.
//
// Operational rule for OTA-updating a device that may hold live durable
// records under these tags: only OTA when every marker this file defines
// reads CLEAR on the device being updated (i.e. no outstanding Free Power,
// register 244, OR Manual Dump-to-Grid recovery obligation -
// DUMP_TO_GRID_VALID_TAG's marker included). This is the simplest rule that is
// actually safe, and is preferred here over inventing a versioned
// migration path, per the hardening task's own guidance not to build a
// migration mechanism this codebase does not yet need. If an OTA ever DOES
// need to change one of these structs while an obligation could plausibly
// be outstanding on a fielded device, use rule 1 (a new tag) rather than
// attempting to migrate the old bytes in place.
//
// This rule applies to EVERY flash in EITHER direction - upgrade, rollback/
// downgrade, or re-flash - not only to installing a newer schema. The marker
// tags are shared across data-schema versions and do not record which
// schema created an obligation, and superseded data records are never
// erased, so a firmware reading an older/newer tag can find a STALE record
// that is not the one the marker refers to. In particular, rolling back to
// the v2 Free Power firmware while a v3-created obligation is outstanding
// is NOT safe (v2 would act on a stale v2 record and does not own TOU Power
// 256-261 at all). See CURRENT_STATE.md's OTA/flash rule.

}  // namespace ecco_durable
