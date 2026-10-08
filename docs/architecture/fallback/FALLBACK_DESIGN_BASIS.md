# Fallback, supervision and failback: design basis and status

> **Status, as recorded on 2026-10-08.** This page is the public design basis of ECCO's supervision, fallback-profile and
> shadow-failback work, and the record of what each stage has and has not proven. It describes what is implemented.
> **Restoring a saved profile (operator Restore) and automatic failback are NOT implemented and NOT enabled.** If Home
> Assistant is lost, ECCO does not put the inverter back to a saved profile; it records what a future failback *would* do.
>
> The detailed design reviews, implementation notes and live-proof logs of these stages belong to the project's private
> development archive ([project history](../../project-history/README.md)). This page carries the decisions and facts that a
> public reviewer needs. Where this page and the code disagree, the code and its offline proofs are authoritative; please report
> the difference.

## 1. Scope and terms

| Term | Meaning |
|---|---|
| **Supervision** | The controller's own judgement of whether Home Assistant (HA) is actively supervising it, based only on a heartbeat |
| **Fallback profile** | The *data*: one user-captured, known-good inverter configuration, stored in the controller's non-volatile storage |
| **Failback** | The *behaviour*: what the controller would do when supervision is lost. Today it exists only in **shadow** form |
| **Shadow** | An observe-only evaluation. It computes and publishes what a future failback would do and is never used to decide anything |
| **Lease** | A temporary operation that owns inverter registers until it restores them: Free Power, Dump-to-Grid, and the register 244 policy transaction |
| **Obligation** | A durable record that a lease still has to restore something. Unknown or unreadable means *not clear* |
| **Live Match** | The comparison between the saved profile and the live inverter configuration |

Stage names used below: **FB-A** (schema), **FB-B0 to FB-B3** (the fallback profile), **FB-C1 to FB-C3** (the shadow
evaluator and its display), **FB-D1 to FB-D5** (prerequisites), **FB-E** (operator Restore) and **FB-F** (automatic failback).

## 2. Rules that do not change

1. **The controller firmware is the only Modbus writer.** Home Assistant, the dashboard, the custom cards, Intelligence and the
   host-side `ecco_core/` model never write to the inverter; they ask, display or advise.
2. **No stage described here adds Modbus authority.** The firmware has 64 Modbus read operation sites and 52 write operation
   sites in 16 write paths, measured by `tools/analyze_write_surface.py` and pinned by the offline suites. Supervision, the
   fallback profile, Live Match, the shadow evaluator, its display and the RTC / poll liveness work changed neither number.
3. **The shadow has zero authority.** Nothing outside the shadow's own code may reference its state (a structural pin), so it
   cannot gate, start, stop or restore anything. It performs no Modbus operation and no non-volatile (NVS) read or write.
4. **Absence is not proof.** A lease record that is simply missing does not prove the lease clear; unknown is never displayed or
   treated as clear; a stale or unlatched configuration cache is never trusted for a comparison.
5. **A reboot never resumes a temporary operation.** Free Power and Dump-to-Grid leases found active at boot are ended and
   restored, never resumed.
6. **The profile never changes itself.** Drift only changes what is displayed. Only an operator Save or Invalidate changes it.
7. **Restore and Acknowledge are reserved.** The firmware's one fallback action, `fallback_profile_execute`, accepts `SAVE` and
   `INVALIDATE`; `RESTORE` and `ACKNOWLEDGE` are refused with "... REFUSED - not implemented in this firmware" (pinned).

## 3. How the parts connect

```
Home Assistant                                      Controller firmware (the only Modbus writer)
--------------                                      --------------------------------------------
heartbeat automation  --- API action, ~30 s --->    supervision (RAM): STARTUP / SUPERVISED / SUSPECT / LOST
operator wrapper scripts                            Review / Save / Invalidate of the fallback profile
  --- fallback_profile_execute(SAVE | INVALIDATE) ->   (reads the inverter; writes only its own NVS records)
                                                    durable profile store: profile record + witness record (NVS)
                                                    Live Match: saved profile vs the live configuration cache
                                                    shadow evaluator: 1 s tick, RAM only, zero authority
                                                    RTC / poll liveness (the existing clock-correction authority only)
status, health, Safety view  <--- read-only entities ---
```

## 4. Supervision (heartbeat)

- An HA automation calls the ESPHome API action `ha_supervision_heartbeat` about every 30 s and echoes the controller's
  current challenge. Only a valid heartbeat moves the controller towards SUPERVISED. The action performs no Modbus and no NVS I/O.
- States (RAM only): **STARTUP**, **SUPERVISED**, **SUSPECT** (no valid heartbeat for 90 s), **LOST** (none for 300 s, or no
  valid heartbeat within 300 s of boot). **Stable** is separate: at least 3 valid heartbeats, every gap at most 45 s, spanning at
  least 55 s.
- The 300 s LOST threshold is **provisional**. It will be chosen from soak evidence before any automatic failback exists.
- Supervision changes no behaviour today. It feeds the Fallback Profile Save gate (Save needs stable supervision), the shadow
  evaluator and the display. ESPHome's default reboot policy is unchanged: with no API client for about 15 minutes the
  controller reboots (uncoordinated); the shadow reports that margin and changes nothing.

## 5. The durable fallback profile

**What is captured.** The six time-of-use (TOU) slots and the export context, classified per register:

| Class | Registers | Role |
|---|---|---|
| E1 (could be restored by a future failback) | 244 (load / export mode), 256-261 (slot powers), 268-273 (slot target SOC), 274-279 bits 0-1 (slot charge source) | Compared; the only class a future Restore could write |
| CTX (context) | 232 bit 0, 243, 248 bit 0, 250-255 (slot times) | Compared only, **never written**: a mismatch blocks |
| INFO | 230, 245, 247 | Captured and reported only; never blocks, never written |

**The V1 domain.** 244 must be 2 (Zero Export); slot powers 500-8000 W; target SOC 0-100 %; charge-source words 0 or 1. A future
failback may move 244 only from 0 to 2, never towards export; a live 244 = 1 is outside the domain and blocks. A configuration
outside V1 can be displayed but not saved.

**Storage.** Two records in the controller's NVS: the profile and a separate *witness* (a high-water record written first). Each
commit is a direct NVS write followed by a two-step direct read-back. Outcomes are **COMMITTED** (verified this boot),
**NOT_COMMITTED** (provably nothing written) or **UNKNOWN_REBOOT** (anything else; no second commit this boot). The boot-time
re-derivation is authoritative: the witness makes a profile that silently rolled back after a reboot visible as
**PROFILE_STALE** or **PROFILE_LOST** instead of a valid-looking older profile. The firmware pins the ESPHome and ESP-IDF versions
whose NVS behaviour this was verified against.

**Profile states:** `NOT_CAPTURED`, `VALID`, `INVALIDATED`, `CORRUPT`, `CORRUPT_DOMAIN`, `UNREADABLE`, `PROFILE_LOST`,
`SAVE_UNCONFIRMED`, `PROFILE_STALE`. A profile is **writer-usable** (usable by any future Restore) only when it is `VALID` with a
consistent witness. If the whole NVS partition is lost, the profile shows `NOT_CAPTURED` and the HA-side generation high-water
detects the regression (detection only).

## 6. Review, Save and Invalidate (the operator boundary)

1. **Review Current Configuration** (a button) reads the inverter fresh: two passes over registers 230-232 and 241-293 (four FC03
   reads), equal in both passes, and builds a RAM-only candidate that expires after 120 s. It writes nothing.
2. **Save** needs the **Arm** (an always-off switch that turns itself off after 120 s) and an exact confirmation phrase,
   `SAVE <16-hex review id>`, which the HA wrapper script builds from the current Review ID. Save re-reads the inverter and
   requires the candidate to be unchanged, stable supervision, trusted (NTP) time, every lease domain positively clear and the
   shared write lock free; it never overwrites an unreadable profile. A corrupt profile is replaced only with the explicit phrase
   `SAVE <id> REPLACE CORRUPT`.
3. **Invalidate** (`INVALIDATE <16-hex profile binding>`) marks a valid profile invalidated. It is synchronous and does not wait:
   it is refused while the bus is busy.
4. The Home Assistant wrapper scripts are operator-only: no automation, schedule or helper may call them, press Review or turn
   the Arm on (pinned).

None of these writes an inverter register. They read the inverter and write only the controller's own fallback records.

## 7. Live Match and drift

- The controller compares the saved profile with the last configuration poll and publishes **ECCO Fallback Profile Live Match**:
  `m` is one of `MATCH`, `DRIFT`, `CONTEXT`, `EXPORT`, `OUT_OF_DOMAIN`, `PAUSED`, `PAUSED_IO`, `UNKNOWN` or `NO_PROFILE`, with
  per-register difference masks, a three-state export-hazard flag (unknown is never shown as "no"), the RAM lease legs and a
  cache-trust letter.
- **Trust.** The cache is used only when fresh (at most 180 s old) and only after a **write fence**: after any controller write,
  lock, lease change or write attempt, two later configuration polls must complete before a comparison is trusted again. Until
  then Live Match reads `PAUSED`, `PAUSED_IO` or `UNKNOWN`, never a guessed `MATCH`.
- **Drift never updates the profile.** HA explains the difference (for example after a Manual TOU apply) and suggests a new Review
  and Save if the change is the new normal. Context differences (slot times, 243, the global grid-charge and TOU enables) mean
  a future Restore would be refused; INFO differences are shown only.

## 8. The shadow evaluator (FB-C2)

- A pure, side-effect-free function evaluates, once per second, *what a future automatic failback would do if Home Assistant
  were lost now* (the **readiness** verdict) from RAM inputs only: supervision, the lease domains, the profile class and identity,
  and the trusted live comparison. It shares the comparison model with Live Match (one implementation).
- **Shadow episodes** (RAM, per boot): a LOST edge opens an episode and freezes the plan at that moment; HA's return moves it to
  `HA_BACK` (it does not cancel it); it closes only after 300 s of continuous stable supervision. A close that a future failback
  would want acknowledged is modelled as a latch (`WOULD_REMAIN_LATCHED`) until the next reboot. Nothing survives a reboot.
- **Plans** are small numeric codes, for example `WOULD_ALREADY_MATCH`, `WOULD_APPLY_PROFILE`, `WAIT_LIVE_DATA`,
  `BLOCKED_DURABLE_UNKNOWN`, `BLOCKED_CONTEXT_MISMATCH`, `BLOCKED_PROFILE_UNAVAILABLE`, each mapped to the FB-A failback
  result it would produce. A lease that is active at a LOST edge is projected as "would end it first" through its own restore.
- Because absence is not proof, a lease domain that has never been used since boot (no durable record) reads as not proven
  clear, so on a quiet installation the readiness verdict is usually `BLOCKED_DURABLE_UNKNOWN`, honestly. The published
  `alt` value shows what an absence-accepting engine would do.
- Telemetry: five diagnostic text sensors, `ECCO Failback Shadow State`, `Episode`, `Soak`, `Verdict` and `Inputs` (a state
  word, a plan name, and fixed-order `k=v;` strings; each at most 200 characters). The soak counters are the evidence for
  choosing the LOST threshold later.

## 9. The shadow display in Home Assistant (FB-C3)

- A decoder (`sensor.ecco_shadow_check`) turns the five strings into words; it is a mapping, not a second evaluator.
- The canonical Fallback status gains one row, **Shadow Recovery** (WARNING), shown only while a shadow episode is open, ranked
  below the lease states. A shadow verdict never makes the Fallback status "Blocked": the shadow cannot block anything.
- The Safety view shows one muted "shadow check, no action taken" line with the readiness verdict, an episode banner while an
  episode is open (it states that nothing was written) and a technical-detail block. Energy Actions and the frontend cards are
  unchanged.

## 10. RTC and polling liveness (FB-D1)

- Every RTC and poll Modbus action declares all of its terminal handlers, and a 90 s deadline breaker releases a stuck clock
  correction. The polls re-check write ownership immediately before each delayed block and owe a catch-up poll instead of
  interleaving with a writer.
- A pure policy (`firmware/include/ecco_rtc_policy.h`, mirrored in `registry/rtc_policy.py`) decides when an automatic clock
  correction may start: two confirming reads for background corrections (threshold at least 30 s), one precision correction
  60-120 s before each inverter TOU zone start, quiet windows around half hours and zone starts, no correction across a
  boundary the inverter has already passed, and a hold while a lease runs.
- After a correction, two catch-up configuration polls let the unchanged Live Match write fence clear within seconds.
- It adds no Modbus operation and no new authority: the clock correction still writes registers 22-24 only, as before.

## 11. What is authoritative and what is not

| Authoritative (decides) | Not authoritative (displays, records or advises) |
|---|---|
| The firmware's write gates, ownership flags, arm switches, durable lease records and verify-after-write | Live Match (B10) |
| The fallback profile's durable records and their boot re-derivation | The shadow evaluator and its five entities |
| The firmware's refusal of `RESTORE` / `ACKNOWLEDGE` | Home Assistant status, health rows, Safety view, banners |
| The pinned write surface (64 / 52) | Intelligence and `ecco_core/` (advisory, host-side; they never act during an HA loss) |

## 12. Stage status

Vocabulary: **implemented** = in this repository and covered by its offline suites; **deployed** = running on the reference
installation; **live-proven** = a supervised live proof of the stage's scope passed on the reference installation;
**partially live-proven** = part of the scope proven live, the rest offline only. These map onto the proof levels of
[SUPPORTED_HARDWARE.md](../../../SUPPORTED_HARDWARE.md): "Hardware tested" means live-proven for the stated scope, and nothing is
production proven.

| Stage | What | Status | Live evidence (reference installation) | Still owed |
|---|---|---|---|---|
| Supervision heartbeat | Heartbeat, challenge, states, Stable | Implemented, deployed, live-proven (observe-only) | Heartbeat and Stable observed; a planned HA restart with a ~90 s heartbeat gap stayed SUPERVISED | The classified soak that will set the LOST threshold |
| FB-A | Profile / failback schema and model | Implemented | Schema only (no runtime role) | - |
| FB-C1 | Shadow instrumentation | Implemented, deployed | Telemetry publishing | - |
| FB-B0 | Durable profile store (witness first) | Implemented, deployed, live-proven | Commits verified and surviving reboots (with FB-B2) | Fault cases are offline only by design (no fault is induced live) |
| FB-B1 | Review Current Configuration | Implemented, deployed, live-proven | Used in the FB-B2 and FB-B3 live proofs | - |
| FB-B2 | Save / Replace Corrupt / Invalidate | Implemented, deployed, live-proven (2026-10-02) | Every commit verified, reboot persistence, refusal drills, no fallback-attributable inverter write | Replace Corrupt: offline only |
| **FB-B3** | HA contract, Live Match, raw-cache extension, write fence | **Implemented, deployed, live-proven (2026-10-03); closed** | Entity ids, wrapper Save / Invalidate, Live Match MATCH / DRIFT / CONTEXT / NO_PROFILE / PAUSED_IO / UNKNOWN on the real inverter, InfluxDB export | Not exercised live (only inside a separately approved test): Replace Damaged, EXPORT, OUT_OF_DOMAIN |
| **FB-C2** | Shadow evaluator | **Implemented, deployed (2026-10-04), partially live-proven** | Baseline: the real evaluator output decodes; the readiness verdict is the predicted one | Authorised HA-loss drills: episode verdicts against the offline goldens (no lease; a lease active at the LOST edge; a Manual TOU drift; a slot-time change) |
| **FB-C3** | Shadow display | **Implemented, deployed (2026-10-04), partially live-proven** | The everyday display path: readiness wording, canonical status, health rows, Safety view | The supervision-loss path: Shadow Recovery status, episode banner and episode detail during a real episode |
| **FB-D1** | RTC and poll liveness | **Implemented, deployed (2026-10-04), partially live-proven** | Post-update checks passed; a precision correction before a TOU zone start observed working; rare no-op corrections from stale clock reads observed (a documented limitation) | A 7-day continuous run of this firmware (earliest 2026-10-11) and its 24-48 h counters; the programme is not complete |
| FB-D2 to FB-D5 | Prerequisites for FB-E / FB-F | **Not implemented** | - | Section 14 |
| FB-E | Operator Restore (the first fallback register writer) | **Not implemented**; `RESTORE` refused | - | Section 14 |
| FB-F | Automatic failback | **Not implemented, not enabled** | - | Section 14 |

The FB-B2 and FB-B3 live proofs ran on the classic ESP32 controller (H-001). Since 2026-10-03 the reference installation runs
the ESP32-S3 wrapper (H-002), which builds the same firmware unchanged; FB-C2, FB-C3 and FB-D1 were deployed on it, and the
profile was saved again there (controller storage does not migrate). Dashboard 7.18.0 (FB-C3) keeps
`tested_in_home_assistant: false` in `VERSION.yaml`: that flag records a dashboard release exercised in full, and the
supervision-loss path has not been.

## 13. Offline evidence and live evidence

**Proven offline** (by the suites in this repository, in CI and locally): the zero-write and zero-authority pins; the
write-surface counts; the durable outcome and power-cut tables of the profile store; the profile-state composition; the capture
gates and refusals; the 81-row shadow decision table and its C++ / Python parity; the Live Match and shadow agreement; the HA
templates, wording and precedence; the RTC policy decision table and its synthetic-day simulations; mutation tests for each.

**Only a live run can show**: the real heartbeat gaps and the LOST threshold; shadow verdicts during real episodes; the Shadow
Recovery display; the RTC policy's behaviour over days of real inverter clock drift; how often the write fence leaves Live Match
settled; real inverter latencies and multi-register write behaviour (needed before any Restore).

Live drills are run only with the owner's authorisation and only through existing, approved procedures. No fault is induced on
the live controller's storage, and an HA outage is never staged without an explicit decision.

## 14. The path to operator Restore (FB-E) and automatic failback (FB-F)

**Before FB-E** (operator-attended Restore, the first fallback code that writes inverter registers) can exist:

1. Owner decisions: an interrupted Restore is **never resumed** at boot (it becomes a blocked state needing an operator
   acknowledgement); where the last failback outcome is kept; whether Restore needs stable supervision (the locked default is a
   typed confirmation and no supervision term, so a present operator can act while HA is degraded); and the statement of whether
   other Modbus masters can reach the inverter (the design assumes they may, for example through a vendor Wi-Fi logger).
2. A durable **failback-state record**, committed through the same direct-NVS primitive *before* the first write, and treated as
   a blocking domain by every start and apply path (Free Power, Dump-to-Grid, the register 244 policy, Manual TOU, Save and
   Invalidate) while a Restore is pending, interrupted or blocked, or not yet loaded after boot. Recovery paths stay allowed.
3. Restore decides on **fresh reads only** (never the cache), requires a writer-usable profile bound by generation and binding,
   writes in a fixed order (244 only from 0 to 2, restrictive changes before permissive ones, every write read back exactly before
   the next), never writes a context or INFO register, and on any failure stops in a blocked state for the operator: there is no
   automatic rollback.
4. The write surface grows deliberately, declared and pinned: one new write path; the writers of 244, 256-261 and 268-279 each
   gain one. The reserved-token refusal pins change by an explicit, reviewed decision, not as a side effect.
5. A power-cut sweep: an interruption at every step boundary must leave a blocked state, zero writes at boot and every start
   refused until acknowledged.
6. Live proofs, in this planned order: first re-prove the existing write features on the ESP32-S3 controller (its write features
   are offline only today, see [SUPPORTED_HARDWARE.md](../../../SUPPORTED_HARDWARE.md)); then the inverter's multi-register write
   behaviour, 244 from 0 to 2, and a changed slot-1 value.

**Before FB-F** (automatic failback) can exist, additionally:

1. A replacement reboot policy: no uncoordinated no-client reboot, a quiescent reboot supervisor, a lock-age breaker and a gated
   Restart button. ESPHome's reboot timers are never disabled without the replacement in the same change.
2. Firmware gating of every start and apply on stable supervision ("managed actions permitted"), with the HA schedules treating
   an unavailable gate as blocked.
3. A neutral Free Power end request, handling of a lease record that diverges within a boot, and protection against a lease record
   that reappears after a reboot.
4. Owner decisions on: containing a Dump-to-Grid operator-needed state that leaves export enabled; the register 244 test
   harness; evidence for an absent lease record (a lease-marker witness); the firmware-update safety rule; the procedure for a
   corrupt durable record.
5. The LOST threshold chosen from soak evidence measured under the replacement reboot policy (300 s stays provisional until then).
6. "No lease records, no profile and no witness" is treated as *no profile*, never as a clean slate that permits a write.

## 15. Changing this area

- Every change made after the public export is declared as a post-export chain entry
  ([docs/dev/post-export-edit-layer.md](../../dev/post-export-edit-layer.md)). The HA packages, the dashboard, several older test
  suites and `VERSION.yaml` are frozen by the export; editing one needs a declared entry with exact reverters.
- The FB-C3 contract suite hashes every git-tracked `.h`, `.yaml` and `.md` file under `firmware/` (only the main firmware YAML
  is reverted through the chain). Existing firmware headers, `firmware/README.md` and the ESP32-S3 wrapper therefore cannot be
  edited without a reviewed change to the post-export schema. New logic belongs in the main firmware YAML or in a **new** header
  that the entry declares as added.
- Older suites are never re-hashed to make a change pass; their historical pins are routed through the chain, and their live
  safety invariants keep reading the live files.
- Deploy Home Assistant files through a site render (`tools/ecco_site_render.py`) if your device slug differs from the default.

## 16. Where the code and proofs are

| Area | Firmware | Python mirror | Main suites |
|---|---|---|---|
| Supervision | main YAML (`ha_supervision_heartbeat`, supervision globals) | - | `registry/tests/test_supervision_heartbeat_observe_only.py` |
| Profile schema (FB-A) | `firmware/include/ecco_fallback_profile.h` | `registry/fallback_profile.py` | `registry/tests/test_fallback_profile_schema.py` |
| Durable store (FB-B0) | `ecco_fallback_durable_model.h`, `ecco_fallback_durable.h`, `ecco_fallback_version_pins.h` | `registry/fallback_durable.py` | `test_fallback_durable_model.py`, `test_fallback_durable_host_compile.py`, `test_fallback_nvs_keyhash.py` |
| Review / capture (FB-B1) | `ecco_fallback_capture.h` | `registry/fallback_capture.py` | `test_fallback_profile_capture.py`, `test_fallback_capture_model.py` |
| Save / Invalidate (FB-B2) | `ecco_fallback_save.h` | `registry/fallback_save.py` | `test_fallback_save_gates.py`, `test_fallback_save_durable.py`, `test_fallback_invalidate.py` |
| HA contract, Live Match (FB-B3) | `ecco_fallback_capture.h` | `registry/fallback_capture.py` | `test_fallback_live_match.py`, `test_fallback_ha_contract.py`, `home-assistant/tests/test_ecco_fallback_packages.py` |
| Shadow evaluator (FB-C1, FB-C2) | `ecco_failback_shadow.h` | `registry/failback_shadow.py` | `test_failback_shadow_core.py`, `test_failback_shadow_evaluator.py`, `test_failback_shadow_tick.py` |
| Shadow display (FB-C3) | - | - | `home-assistant/tests/test_ecco_shadow_check_ux.py`, `registry/tests/test_failback_shadow_ha_contract.py` |
| RTC / poll liveness (FB-D1) | `ecco_rtc_policy.h` | `registry/rtc_policy.py` | `test_rtc_policy.py`, `test_fbd1_liveness.py` |
| Change scope | - | - | `test_scope_chain.py`, `test_pub0_transition.py`, `test_pex_transition.py` |

Home Assistant side: `home-assistant/packages/ecco_supervision_heartbeat.yaml`, `ecco_fallback_status.yaml`,
`ecco_fallback_profile_actions.yaml`, `ecco_system_health.yaml` and the Safety view of `home-assistant/dashboards/ecco_pro.yaml`.
