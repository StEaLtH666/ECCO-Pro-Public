# S4 - DOMAIN / WRITER PRIORITY MATRIX + SHADOW DECISION TABLE (final)

Section owner: S4_domains_decisions. Answers FB-C questions 5, 6, 7, 8, 9, 10 and 11 of `brief/USER_REQUEST.md`.
Feeds final-document sections 7 (DOMAIN / WRITER PRIORITY MATRIX) and 8 (SHADOW DECISION TABLE).
Status: FINAL. It incorporates the adversarial review; the disposition of every review issue is in §11 ("Red-team disposition").

## 0. Conventions

### 0.1 Labels
- [MAIN]: current merged behaviour @004040b (authoritative).
- [PR54]: the proposed FB-A contract (b4c357d).
- [PR52] / [PR53]: in-flight PRs.
- [ESPHOME]: ESPHome 2026.8.2 installed source. [IDF]: ESP-IDF 5.5.5 `nvs_flash`.
- [DOC]: a document claim (may be stale).
- [REC]: this section's recommendation. Every [REC] in a "LOCKED" box is proposed as a locked decision.
- [FUTURE]: FB-D / FB-E / FB-F design, not built by FB-B or FB-C.
- [INFERENCE]: reasoning from code, not directly stated anywhere.

### 0.2 Citation aliases (every line number below was opened in this session unless marked "per E0x" / "per V0x")

| Alias | Full path (tree) |
|---|---|
| `FW:N@main` | `firmware/ecco_clock_dongle_stage3_4_free_power.yaml:N@main` (same file @pr53 is cited as `FW:N@pr53`) |
| `FBH:N@pr54` | `firmware/include/ecco_fallback_profile.h:N@pr54` |
| `DS:N@main` | `firmware/include/ecco_durable_snapshot.h:N@main` |
| `ARCH:N@pr54` | `docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md:N@pr54` (lines 1-1236 identical to main per E02) |
| `WSI:N@main` | `registry/tests/test_write_surface_invariants.py:N@main` |
| `PRA-T:N@main` | `registry/tests/test_supervision_heartbeat_observe_only.py:N@main` |
| `P54-T:N@pr54` | `registry/tests/test_fallback_profile_schema.py:N@pr54` |
| `SG01P5-T:N@main` | `registry/tests/test_sg01_phase5_hardening.py:N@main` |
| `SG06-T:N@main` | `registry/tests/test_sg06_boot_durable_read_fail_closed.py:N@main` |
| `SCRIPT:N@esphome` | `esphome/components/script/script.h:N` |
| `MBC:N@esphome` | `esphome/components/modbus_client/modbus_client.h:N` |
| `PREFS:N@esphome` | `esphome/components/esp32/preferences.cpp:N` |
| `NVSP:N@idf` / `NVSS:N@idf` | `components/nvs_flash/src/nvs_page.cpp:N` / `nvs_storage.cpp:N` |
| `FE:N@main` | `frontend/ecco-energy-actions-card/src/<file>.ts:N@main` |
| S1 / S3 / S6 | sister sections: FB-B capture, FB-C core, interactions/blockers (drafts on disk; names cited are theirs) |

### 0.3 Vocabulary (charter C0, with the extensions in §10.1)
- Domains: FP, DUMP, R244, MTOU, MTOU_JOURNAL, FBP. S4 adds one pseudo-domain, BUS (the shared locks). BUS is not a durable domain, but it must be classified, because a stuck lock blocks every writer.
- C0 tri-state: CLEAR_PROVEN / OBLIGATION_<kind> / UNKNOWN_<kind>. CLEAR_PROVEN always carries an **evidence** value (§3.3); evidence decides whether a future writer may rely on it (rule R3).
- Supervision names are the firmware names: STARTUP / SUPERVISED / SUSPECT / LOST, plus Stable. "Stable supervision" is S3's `P_STABLE` (state==SUPERVISED ∧ `supervision_stable` ∧ valid_count>0 ∧ heartbeat age ≤ max gap; S3 §3.2).
- Shadow episode phases are S3's: NONE / OPEN / HA_BACK / CLOSED. "Episode open" means phase ∈ {OPEN, HA_BACK}.

### 0.4 Headline decisions (details in the sections below)
1. **Priority model.** P0..P5 is an *admission and authority* order, not a pre-emption order. [MAIN] enforces it only as mutual exclusion on `manual_write_in_progress` (first come, first served) plus cross-domain admission gates. **Nothing is pre-emptive today.** R1 is stated **per domain**: a domain's own P1/P2 path is always admissible for its own obligation; P2 is an escalation of P1 inside one domain. §1.4 lists 17 places where the order is not enforced.
2. **One shared classifier, zero NVS reads in FB-C.** Every domain is classified by one pure per-domain classifier (§2.2), implemented once and reused by the FB-B capture gate, FB-C, and later FB-E/FB-F. FB-C performs **no NVS reads** (concurs with S3 FBC-13; OVERTURNS CHARTER C7 in part). FB-C's durable evidence is the boot-time load status retained in RAM plus FB-B's per-boot probe latch (read-only).
3. **Sticky evidence rules.** Any probe finding other than CLEAR or ABSENT latches UNKNOWN for the rest of the boot and the key is never probed again. An ABSENT result after any evidence that the key existed is DIVERGED (`*_MARKER_EVIDENCE_VANISHED`). A durable operator-needed retry record with an ABSENT marker is DIVERGED (`*_MARKER_LOST`).
4. **Absence is not proof (R3).** A future autonomous writer (FB-F) never relies on CLEAR-by-absence without a witness. FB-C projects that as BLOCKED/6 with a distinct reason, and also publishes the plan that would result if absence were accepted.
5. **Plan codes.** One pure function `ecco_failback_shadow::evaluate(const ShadowInputs&) -> ShadowPlan` with a fixed first-match table (§3.4, normative). It emits **21 codes plus 1 reserved** (§8). Each code maps to exactly one FB-A `(FailbackState, FailbackResult)` or is RAM-only. The plan projects Policy B; the Policy-A result is a derived field.
6. **Dump `operator_needed` with live 244 = 0.** `BLOCKED_OPERATOR_NEEDED`, reason `DUMP_OPERATOR_NEEDED_EXPORT_LIVE`, `export_hazard = YES`, FB-A 5. Never written over. The lockout is not guaranteed to survive a reboot (§4.1). SG-02b (literal 244 := 2 containment) remains a **PRODUCT DECISION**.
7. **`export_hazard` is tri-state** (UNKNOWN / NO / YES) with one predicate for every domain (§4.2).
8. **Live 244 = 1 (Essentials)** → `BLOCKED_LIVE_OUT_OF_DOMAIN` (FB-A 9). CONTRADICTION with ARCH A9.
9. **NOT_CAPTURED** projects LATCHED/2 only when a witness proves it; otherwise BLOCKED/7 `PROFILE_ABSENT_UNPROVEN`. CONTRADICTION with a naive reading of ARCH:533 resolved.
10. **Episode binding** is a struct recorded at the LOST edge (class, generation, binding). A shadow episode never gates anything.
11. **Thresholds** are locked initial values with a revision rule (§3.7).

---

## 1. Writer-priority model (FB-C Q5)

### 1.1 Definitions [REC, LOCKED]

| Level | Name | Meaning | Members at MAIN (writers **bold**) |
|---|---|---|---|
| **P0** | Safety containment | Literal, restrictive, fail-safe writes that need no durable authority. P0 never restores and never writes 256-261. It runs *under* lockouts that block everything else | **`dump_lockout_containment`** (SG-02). Future candidate: SG-02b (§4.4) |
| **P1** | Temporary lease recovery | A lease's own automatic path back to its durable ORIGINAL, plus the neutral end requests that start it and the zero-I/O clear-only paths | **`restore_free_power_snapshot_dispatch`** when run by the watchdog; **`restore_dump_to_grid_snapshot`** when run by `request_dump_end`. Zero-write members: `restore_free_power_snapshot` (wrapper), `request_dump_end`, `dump_clear_verified_marker` |
| **P2** | Operator recovery (escalation of P1 **inside one domain**) | Human-authorised exits from that domain's own lockouts. They restore to ORIGINAL or accept live state | **`free_power_recovery_force_restore_dispatch`**, **`restore_dump_to_grid_snapshot`** with the Force bypass, **`restore_reg244_snapshot`**, **`restore_free_power_snapshot_dispatch`** with the End-button one-shot. Zero-write members: FP Review/Accept dispatch, `dump_accept_current_state` |
| **P3** | Fallback [FUTURE] | One-shot convergence to the saved profile. FB-E is operator-initiated; FB-F is autonomous on LOST | none (FB-C only *projects* it) |
| **P4** | Manual configuration and capture | Persistent operator configuration writes, and the FB-B capture reads | **`apply_manual_slot1..6`**. FB-B capture (reads under the mutex, zero writes) |
| **P5** | Starts and in-lease adjustment | Anything that *creates* a temporary obligation, or adjusts a running lease | **`start_free_power_override`**, **`start_dump_to_grid_override`**, **`apply_reg244_settings`**, **`dump_controller_tick`** |
| PX | Clock maintenance (outside the model) | Registers 22-24 only. Disjoint from every Fallback register | **`write_inverter_rtc`** |
| P∅ | Zero-write | Never writes | config/telemetry polls, FP Review dispatch, FB-C evaluator |

**Register ownership used by R1** [MAIN, from the pinned write surface `P54-T:759@pr54` "written set 22-24, 230, 232, 244, 250-261, 268-279"]:
- Owned(FP) = {230, 232, 256-261, 268-279} (FP also reads 244 as lease context, FW:1867).
- Owned(DUMP) = {244, 256-261}. Owned(R244) = {244}. MTOU has no lease, so it owns nothing durable.
- Semantic dependencies: Dep(256-261) = {244, 250-255}; Dep(268-279) = {232, 250-255}. 244 changes what 256-261 mean (`SAFE_WRITE_TRANSACTION_ARCHITECTURE.md:28-35@main`, per E02 §6.3).

**Ordering rules** [REC, LOCKED]:
- **R1 (no cross-domain overlay).** A writer W acting for domain X is admitted only if, for every **other** domain Y ≠ X, either Y is CLEAR_PROVEN, or `(Reg(W) ∪ Dep(Reg(W))) ∩ Owned(Y) = ∅`. A domain's own P1 path and its P2 escalation are **always admissible for that domain's own obligation**, subject only to that domain's own gates. P2 is not a lower tier than P1 across domains; it is the same domain's recovery with operator authority. An UNKNOWN or corrupt domain counts as holding an unresolved obligation on everything it owns. P0 is governed by R5, not R1.
- **R2 (no mid-transaction pre-emption).** ECCO never aborts an in-flight Modbus transaction. Priority acts only in three ways: at admission, through lease-end *requests* (which hand control to the lease's own P1 path), and through refusal of new starts.
- **R3 (Fallback is the final writer; positive evidence only).** P3 may write only when every temporary domain (FP, DUMP, R244, MTOU, MTOU_JOURNAL, BUS) is CLEAR_PROVEN **with evidence in {MARKER_CLEAR_PROBE, NO_DURABLE_RECORD, NOT_IMPLEMENTED, IDLE}** (§3.3), where MARKER_CLEAR_PROBE is established by the writer's own precheck probe (ARCH row 11, "durable probe positively CLEAR", `ARCH:532@pr54`). **MARKER_ABSENT is never sufficient for FB-F** unless an FB-D witness proves the absence (`absence_witness`, §2.10); otherwise the domain is BLOCKED_DURABLE_UNKNOWN. Named operator-attended exceptions:
  - **FB-B capture** (not a P3 writer; charter C6) may accept MARKER_ABSENT, except where §2.4-§2.6 turn absence into DIVERGED.
  - **FB-E** (operator Restore) may accept MARKER_ABSENT only if its Review step names every absent domain ("no saved record for <domain>; ECCO cannot prove it is clear") and the operator's confirmation explicitly covers it [FUTURE, locked requirement].
  - P3 never pre-empts P0, P1 or P2. It pre-empts P5 leases only via their neutral end request.
- **R4 (start refusal) [FUTURE, FB-D].** P5 is refused unless supervision is stable (S3 `P_STABLE`) and no **FB-D/FB-F failback episode** is open (a durable FailbackStateV1 not CLEAR). A shadow (FB-C) episode never gates any runtime behaviour: S3's non-authority pin Z5 forbids any YAML block other than FB-C's own from referencing `failback_shadow_`. FB-C only reports `would_refuse_starts`.
- **R5 (P0 independence).** P0 is admitted under lockouts that block P1/P2 (for example `dump_recovery_metadata_corrupt`). It writes only a literal restrictive value and must not be delayed indefinitely by a lower level. Known residual: P0 does not check other domains' obligations (N16).

### 1.2 Verification of the 16 pinned write paths [MAIN]

The pinned set is `EXPECTED_WRITE_PATHS` at WSI:72-127@main (16 scripts; the "fourteen"/"eleven" labels at WSI:66-71,137@main are stale). Mutex acquire sites were enumerated by grep: 20 scripts set `manual_write_in_progress = true` (FW:6603, 7748, 7918, 9348, 9867, 9908, 10880, 10935, 11488, 11831, 12098, 12365, 12632, 12899, 13933, 14393, 14996, 16049, 16452, 17091@main).

| # | Script (start line) | P | Gate code (@main) | Cross-domain terms in the gate | Waits on the mutex? | Pre-empts anything? | Order enforced today? |
|---|---|---|---|---|---|---|---|
| 1 | `write_inverter_rtc` (FW:6439) | PX | Defers if `manual_write_in_progress` (FW:6457); needs `ntp_synced && now().is_valid()` (FW:6468-6470). **Never sets the mutex**: `KNOWN_UNGUARDED` (WSI:255) | none | checks at dispatch only | no | **No** (N9). Its lock `correction_in_progress` can block P0/P1 (N2) |
| 2 | `start_free_power_override` (FW:6553) | P5 | FW:6559-6598: arm, `!FP AP/SV/OIP`, `!MWIP`, `!correction`, `!reg244_snapshot_valid` (6574), `!dump_active_persisted`/`!dump_snapshot_valid` (6582-6583), `!FP corrupt` (6587), config online, NTP (6589-6590), battery, bus quiet | FP, R244, DUMP (corrupt is implied because every corrupt site also sets `*_snapshot_valid`, E04 §1.4) | yes | no | **Admission yes; supervision no** (N5) |
| 3 | `restore_free_power_snapshot_dispatch` (FW:7913) | P1 (watchdog), or P2 (End one-shot) | Wrapper gate FW:7726-7734: `SV && !MC && !OIP && !MWIP && !correction && bus quiet`, then the operator-lockout/backoff gate. The dispatch acquires unconditionally (FW:7917-7918; `KNOWN_LOCK_TAKEN_WITHOUT_CHECK`, WSI:286). Watchdog condition FW:18250-18288 | **none** | **yes**: watchdog FW:18256 and wrapper FW:7730 require `!MWIP` | no | Mutex only. Starved by a stuck `correction_in_progress` (N2). No cross-domain terms (N17) |
| 4 | `free_power_recovery_force_restore_dispatch` (FW:9903) | P2 | Wrapper refusal chain FW:9817-9853: busy (`OIP`, `MWIP`, `correction`, `reg244_apply_in_progress`, bus) FW:9819-9827; arm FW:9828; `!MC` FW:9830; `SV && MS==RR` check FW:9832 (refusal text 9833); evidence < 120 s FW:9836; ID FW:9838-9844; phrase FW:9846-9848 | only `reg244_apply_in_progress` | yes | no | yes (own-domain P2, same ORIGINAL target as P1; R1-consistent) |
| 5-10 | `apply_manual_slot1..6` (FW:11401, 11769, 12036, 12303, 12570, 12837) | P4 | Slot 1 FW:11428-11450 (slots 2-6 at FW:11796, 12063, 12330, 12597, 12864): arm, staging loaded, cache valid, config online, `!correction`, `!MWIP`, `!reg244_snapshot_valid`, `!FP corrupt`, `!reg244 corrupt`, HHMM/power/SOC checks. **No FP/DUMP obligation terms and no bus-quiet check.** The only callers are the buttons (FW:17812, 17866, 17919, 17972, 18025, 18078), whose gate (FW:17808-17809) adds `!FP AP && !FP SV && !DUMP A && !DUMP S` | MAIN: R244 only at script level (FP/DUMP at button level, pinned as a known gap WSI:375-397). [PR53] script level adds FP AP/SV/OIP, DUMP A/S/O/corrupt, `reg244_apply_in_progress` and bus quiet (FW:11444-11478@pr53) | yes | no | Effectively yes on MAIN (button is the only caller); **structurally no** (N6). **No supervision gate** (N7) |
| 11 | `apply_reg244_settings` (FW:13877) | P5 | FW:13889-13921: arm, staging, config online, `!correction`, `!MWIP`, `!rAIP`, `!rSV`, `!rMC` (13890-13900); `!FP AP/SV` (13908-13909); `!DUMP A/S` (13913-13914); bus quiet (13919-13920); target ∈ {0,1,2} (13921) | FP, DUMP | yes | no | **Admission yes; supervision no.** Can write 244 := 0 (Allow Export) in any supervision state (N7) |
| 12 | `restore_reg244_snapshot` (FW:14361) | P2 (the only recovery path) | FW:14366-14388: arm, `rSV`, `!rMC`, PC or `value<=2`, config online, `!correction`, `!MWIP`, `!rAIP` (14368-14376); `!FP AP/SV` (14381-14382); `!DUMP A/S` (14385-14386); bus quiet (14387-14388) | FP, DUMP (own-domain P2 waits for other domains: R1-consistent) | yes | no | yes. **But** no automatic path exists, and the drift guard (condition FW:14511, reject branch FW:14512-14524) can refuse forever (N11) |
| 13 | `start_dump_to_grid_override` (FW:14864) | P5 | FW:14923-14991: arm, `!DUMP A/S/O`, `!MWIP`, `!correction`, `!FP AP/SV/OIP` (14933-14935), `!rSV` (14939), `!rAIP` (14940), `!DUMP corrupt` (14944), telemetry/config freshness, bus quiet | FP, R244 | yes | no | **Admission yes; supervision no** (N5) |
| 14 | `restore_dump_to_grid_snapshot` (FW:16412) | P1 (watchdog / `request_dump_end`), or P2 (Force bypass) | Bypass consumed first (FW:16423-16424). Gate FW:16425-16447: `S && M==RR && !C && (!N || force) && !O && !MWIP && !correction && (force || backoff elapsed) && bus quiet`. Watchdog trigger FW:18307-18321 | **none** | **yes** (FW:18309 and gate) | no | Mutex only. Starved by a stuck `correction_in_progress` (N2). No cross-domain terms (N17) |
| 15 | `dump_controller_tick` (FW:15725) | P5 (in-lease) | Defensive FW:15733-15735 (`A && !R && !O && !C`). Lock gate FW:16045-16046 (`!MWIP && !correction && bus quiet`); takes MWIP at FW:16049 but **not** `dump_operation_in_progress`. Only run from the watchdog when `!R` (FW:18479-18484) | none | yes | no | Mostly. The restore trigger runs first in the same tick (FW:18304-18331). [DOC] ARCH A1 residual: one bounded controller write may still go out (N14) |
| 16 | `dump_lockout_containment` (FW:17069) | **P0** | FW:17075-17087: `S && C && K∈{1,5} && !O && !MWIP && !correction && !FP OIP && !rAIP && backoff && bus quiet`. Triggered only from the watchdog step (FW:18515-18521). D5 exemption (read 256-261, compare with the trusted original) FW:17135-17150 | FP/R244 in-flight flags only (no `rSV`) | **yes** | **no** | **No** (N1, N2): P0 queues behind any mutex holder. Not armed for UNKNOWN (K=8) or `operator_needed` (N12, N13). May overlay a trusted R244 obligation (N16) |

**Zero-write paths that carry authority** [MAIN]:
- `end_free_power_button` (FW:17645-17742) grants the P2 one-shot operator override. It clears `operator_needed` in RAM and durably (FW:7823-7849 per E04).
- The Dump END button calls `request_dump_end` (FW:18222). That is a **neutral** P1 end request: the restore gate still refuses while `dump_operator_needed` (FW:16432) unless the Force bypass is armed.
- `dump_force_restore_original` (FW:16879-16897) requires `dump_operator_needed && arm && S` (FW:16885), sets the bypass (FW:16888), then runs the shared worker (FW:16890).
- `dump_accept_current_state` (FW:16918-17033) is P2 with zero I/O. It refuses while live 244 == 0 unless the live 244/256-261 set equals the original (per E05 §6.6, V4 (5)).

### 1.3 Answers to the three specific verification questions

**Q5a. Does SG-02 containment pre-empt? No [MAIN].**
- Its gate requires `!manual_write_in_progress && !correction_in_progress && !dump_operation_in_progress && !free_power_operation_in_progress && !reg244_apply_in_progress` and a quiet bus (FW:17079-17087).
- It is dispatched only once per 15 s watchdog tick, as the last step (FW:18515-18521).
- It is therefore strictly first-come-first-served behind any holder.

In practice this is bounded, because a corrupt Dump lockout sets `dump_snapshot_valid`. That refuses:
- FP START (FW:6582-6583);
- Dump START (FW:14926);
- reg244 Apply (FW:13914) and reg244 Restore (FW:14386);
- the manual-slot buttons (FW:17808-17809).

The remaining concurrent writers are therefore only:
- a trusted FP RESTORE_REQUIRED restore (P1), possible when the Dump marker is malformed and FP holds a trusted obligation, because the FP/Dump arbitration at FW:904-921 requires both sides to be non-corrupt (this is an R1 overlay, N17);
- the RTC write (PX);
- an in-flight lock leak.

A leaked `correction_in_progress` (RTC S6, open even at PR53) starves P0 indefinitely (N2).

**Q5b. Does the FP watchdog restore wait for manual writes? Yes, it waits; it does not pre-empt [MAIN].**
- The watchdog condition returns false while `free_power_operation_in_progress || manual_write_in_progress || correction_in_progress` (FW:18256).
- The wrapper gate re-checks `!manual_write_in_progress` (FW:7730).
- A Manual TOU apply cannot start while an FP obligation exists (button gate FW:17808-17809; [PR53] script gate FW:11469-11471@pr53). So "P1 waits for P4" can happen only through a lock *leak*. Two leaks are possible:
  - the MAIN Manual TOU verify-read leak (S6 manual part, fixed by PR53);
  - the RTC `correction_in_progress` leak (open).
  Either is an unbounded priority inversion (N2).

**Q5c. Can a Manual TOU apply run while an FP obligation exists, at script level? MAIN: yes structurally, no in practice. PR53: no.**
- [MAIN] The script admission FW:11428-11450 has no FP/DUMP terms.
- The only barrier is the button (FW:17805-17816), which is currently the only caller (the six buttons: FW:17812, 17866, 17919, 17972, 18025, 18078).
- WSI:375-397@main pins this as a known layering gap.
- [PR53] adds `!free_power_active_persisted`, `!free_power_snapshot_valid`, `!free_power_operation_in_progress`, the DUMP terms, `!reg244_apply_in_progress` and bus quiet at script level (FW:11444-11478@pr53).
- Neither tree gates Manual TOU on supervision.

### 1.4 Every place the proposed ordering is NOT enforced today

| ID | Gap | Evidence | Consequence for Fallback | Must be fixed before |
|---|---|---|---|---|
| N1 | No pre-emption primitive. Every level, P0 included, is first-come-first-served on one RAM mutex | FW:1477; gates above | P0 can be delayed by P4/P5 (bounded by transaction length) | Accepted (R2). Document only |
| N2 | Lock leaks invert priority without bound. There is no enforcing lock-age watchdog | `correction_in_progress` blocks P0 (FW:17081), P1 FP (FW:18256, 7731) and P1 Dump (FW:18309). RTC read/write lack `on_not_sent`/`on_custom_response` (E06 D4). Diagnostics only (FW:18712-18735) | Leases can stay applied. FB-C reports WAIT_WRITE_IN_FLIGHT (LOCK_STUCK reasons) | FB-E (RTC S6 fix + lock-age breaker) |
| N3 | Lockout exits require HA-reachable operator actions (P2) | End/Force/Accept are buttons or API actions (FW:1119-1138, 18225-18241) | During LOST, nothing resolves FP ON or a held/PC reg244 | FB-F (accepted: BLOCKED) |
| N4 | FP has no neutral end primitive. End grants the P2 one-shot | FW:17651-17653, 7823-7849; `request_free_power_end` does not exist (E04 P13) | FB-F cannot pre-empt FP without borrowing operator authority | FB-F (FB-D deliverable) |
| N5 | P5 starts are not refused in STARTUP/SUSPECT/LOST | No supervision reference in any gate (E07 finding 1; V7 (3)) | "Refuse starts at SUSPECT" is unimplemented | FB-F (FB-D, R4); FB-C only reports `would_refuse_starts` |
| N6 | Manual TOU script-level gate lacks FP/DUMP terms on MAIN | FW:11428-11450 vs FW:17808-17809 | Layering only (button is the sole caller) | PR53 merge (preferred before FB-B) |
| N7 | P4 Manual TOU and P5 reg244 Apply have no supervision or failback gate | E06 D9; ARCH:629@main matrix unimplemented | With HA connected but heartbeat dead (ARCH A6), an operator can apply during LOST, including reg244 → 0 | FB-F (FB-D) |
| N8 | The config poll re-checks the mutex only at entry | FW:13394-13398; Block B dispatched after `delay: 2500ms` (FW:13518-13523) (E06 D1, V6 (1)) | Reads interleave with transactions. Affects FB-B/FB-E fresh reads and FB-C's cache fence, not write priority | FB-B (capture) |
| N9 | RTC write is outside the mutex | WSI:255; FW:6457 | Frames interleave; registers are disjoint | Accepted (PX) |
| N10 | No FP↔R244 dual-obligation arbitration at boot | Only S4 (FW:815-840) and FP/Dump (FW:904-921) | FP RR plus R244 RR can coexist after a ghost | FB-C reports both; FB-F BLOCKED |
| N11 | R244 has no P1 path. P2 restore can be refused forever by the drift guard, and `last_applied_*` are `restore_value: yes` | FW:14511-14524, FW:2784-2791 | Fallback blocked indefinitely | FB-F (FB-D: R244 escape or automatic strict restore) |
| N12 | P0 does not cover Dump `operator_needed` with 244 = 0 | Containment requires `C` (FW:17077, 18495) | Export stays enabled and unguarded (§4) | PRODUCT DECISION (FB-D) |
| N13 | P0 is not armed for Dump UNKNOWN (K=8); containment can end REFUSED (6) or EXPORT_REENABLED_EXTERNALLY (7), and CONTAINED (4) is revocable (4 → 7 when a later poll reads 244==0, FW:18507-18510) | FW:588, 923-924, 18507-18510 | 244 may stay or return to 0 | Accepted residual. FB-C reports `export_hazard` |
| N14 | [DOC] A Dump controller R3 read in flight at an end request can still issue one bounded write | ARCH A1 (per E02 §3.11) | P5 is not instantly stopped by P1 | Accepted residual (bounded 500-3000 W) |
| N15 | P3 does not exist, so "Fallback is the final writer" is not enforced after a write | A ghost Dump/FP marker makes the next boot restore a stale ORIGINAL (E05 §12.1; E04 §8.3). A later P4/P5 can overwrite. No latch gate exists | A future FB-E/FB-F write could be silently undone | FB-E (probe gate) / FB-F (latch + start refusal) |
| **N16** | P0 can overlay a **trusted** R244 obligation. The S4 arbitration fires only when both sides are non-corrupt (FW:815-819); SG-02's gate has no `rSV` term (FW:17075-17087) | Dump marker malformed or data-bad (C set, K armed) + R244 RR trusted at the same boot → containment may write 244 := 2 over a held harness value; the harness restore then hits its drift guard (FW:14511) | R244 dead end (N11) | Accepted residual (restrictive direction). FB-C: DUMP L3 wins; R244 is still reported |
| **N17** | P1 restores (FP and Dump) carry no cross-domain terms. With the other domain corrupt/unknown (so the boot arbitrations FW:815-822 / 904-911 do not fire), a trusted P1 restore writes the shared 256-261 over the other domain's unresolved obligation. This violates R1 as restated | FW:7726-7734, 16425-16447 (no other-domain terms) | Both domains still block Fallback; the write direction is the domain's own ORIGINAL | Accepted residual; FB-D may add `!other_corrupt` terms. FB-C: L3 of the corrupt domain wins |

### 1.5 Consequences for FB-C [REC, LOCKED]
- **§3.4 is normative.** It is *kind-major*: rows are ordered by kind of finding (pre-empt, latched lockout, divergence, operator-needed, absence, stuck lock, waits, profile, live). Inside one row the tie-break is the fixed domain order **DUMP → FP → R244 → BUS → MTOU → MTOU_JOURNAL**. DUMP comes first because it is the only domain whose unresolved state can leave 244 = 0 (Allow Export).
- FB-C never assumes a lower level will yield. Where the future engine would *wait*, FB-C emits `WAIT_*`.
- **Reachability note [MAIN].** Corrupt flags are set only in on_boot (§5), and every lease ACTIVE at boot is converted to restore-requested (FP FW:373-381; Dump FW:650-654). Every START refuses while any other domain's `*_snapshot_valid` is set. **So in reachable MAIN states at most one temporary domain is non-CLEAR at a time.** The exceptions are:
  - the dual-obligation boot results (turned into corrupt by S4 and FP/Dump arbitration);
  - FP + R244 after a ghost (N10);
  - an untrusted domain alongside a trusted obligation in another (N16, N17; the SG-06 decision in CURRENT_STATE.md:31-33@main, per E04).
  The cross-domain precedence therefore matters only in those cases. It is fixed for determinism and defence.

---

## 2. Per-domain classification (FB-C Q6)

### 2.1 Inputs, abbreviations and new RAM inputs

**FP** [MAIN] (all `restore_value: no`):

| Abbrev | Global | Line |
|---|---|---|
| SV | `free_power_snapshot_valid` | FW:1640 |
| AP | `free_power_active_persisted` | FW:1644 |
| EE | `free_power_end_epoch` | FW:1648 |
| RQ | `free_power_restore_requested` | FW:1652 |
| OIP | `free_power_operation_in_progress` | FW:1766 |
| LC | `free_power_lease_context_reg244` | FW:1867 |
| MS | `free_power_marker_state` | FW:1937 |
| MC | `free_power_recovery_metadata_corrupt` | FW:1947 |
| NA | `free_power_restore_next_attempt_ms` | FW:1968 |
| ON | `free_power_operator_needed` (loaded at boot **not** gated on SV, FW:484-487) | FW:1979 |
| FIP | `free_power_recovery_force_in_progress` | FW:2314 |
| AIP | `free_power_recovery_accept_in_progress` | FW:2531 |

FP snapshot registers are at FW:1656-1735.

**DUMP** [MAIN]:

| Abbrev | Global | Line |
|---|---|---|
| S | `dump_snapshot_valid` | FW:2834 |
| A | `dump_active_persisted` | FW:2838 |
| DE | `dump_end_epoch` | FW:2842 |
| R | `dump_restore_requested` | FW:2846 |
| M | `dump_marker_state` | FW:2850 |
| O | `dump_operation_in_progress` (set by START FW:14995, restore FW:16451, containment FW:17090; **not** by the controller) | FW:2980 |
| C | `dump_recovery_metadata_corrupt` | FW:3012 |
| N | `dump_operator_needed` (loaded as `have_retry && operator_needed && S`, FW:676) | FW:3020 |
| FB | `dump_force_restore_bypass` | FW:3037 |
| DNA | `dump_restore_next_attempt_ms` | FW:3045 |
| K | `dump_containment_state` | FW:3456 |
| DL | `dump_snapshot_data_loaded` | FW:3466 |

Also used: `dump_snapshot_reg244` (FW:2854) and `dump_snapshot_reg256..261` (FW:2858-2878). Documentation only: `dump_verify_mismatch_count` (FW:3081), `dump_comms_restore_attempts` (FW:3041).

**R244** [MAIN]:

| Abbrev | Global | Line |
|---|---|---|
| rAIP | `reg244_apply_in_progress` | FW:2730 |
| rMS | `reg244_marker_state` | FW:2748 |
| rMC | `reg244_recovery_metadata_corrupt` | FW:2753 |
| rSV | `reg244_snapshot_valid` | FW:2767 |
| rV | `reg244_snapshot_value` | FW:2771 |
| LA | `reg244_last_applied_value` (restore_value: yes) | FW:2784 |
| LAV | `reg244_last_applied_valid` (restore_value: yes; set true only after a verified Apply FW:14197-14198 or Restore FW:14650-14651) | FW:2788 |

**BUS** [MAIN]:

| Abbrev | Global | Line |
|---|---|---|
| MWIP | `manual_write_in_progress` | FW:1477 |
| CIP | `correction_in_progress` | FW:1283 |
| — | `diag_write_lock_held` / `diag_write_lock_since_ms` / `diag_write_lock_max_ms` | FW:3630 / 3634 / 3638 |
| — | `diag_correction_lock_held` / `diag_correction_lock_since_ms` | FW:3642 / 3646 |

The lock diagnostics are sampled by the PR-A 1 s tick (FW:18712-18735).

**Supervision** [MAIN, read-only]: `supervision_state` FW:3539, `supervision_last_valid_ms` FW:3547, `supervision_valid_count` FW:3574, `supervision_stable` FW:3600, `supervision_generation` FW:3610. FB-C never reads the token `supervision_have_valid`; "has a valid beat" is `supervision_valid_count > 0` (S3 §3.2), because PRA-T:278-280 pins that exactly one interval mentions `supervision_have_valid`.

**Marker constants** [MAIN]: CLEAR=0, RR=1, PC=2 (DS:184-188 per E04). LoadStatus: OK=0, ABSENT=1, WRONG_SIZE=2, READ_ERROR=3 (DS:134-139).

**Script-running attribution** [ESPHOME]: `id(<script>).is_running()` (SCRIPT:44). It is true while any action of the script is still running, including `delay`/`wait_until`. It does **not** cover:
- a Modbus response still pending after the script finished: `modbus_client` actions are fire-and-forget (`play()` queues and returns, MBC:59-62, 98), so an `on_response` can still own a lock after its script ended; `apply_manual_slot1`, for example, ends with a `delay: 900ms` (FW:11722);
- a `script.execute` discarded by `mode: single` (SCRIPT:72-87), which leaves no trace except flags the caller set.
Therefore every "flag set, no script running" predicate has a grace period (§2.4 F4, §2.5 D5, §2.6 G4, §2.9 B1). No MAIN code uses `is_running()` yet; FB-C2 introduces it (read-only).

**`expired` (FP)** := `clock_valid && EE != 0 ? now_epoch >= EE : now_ms >= 300000`. This mirrors FW:18272-18288 with the grace `ecco_free_power_invalid_clock_grace_ms` = 300000 (FW:21). **`expired` (DUMP)** is the same over DE (FW:18314-18321).

**`backoff` (FP)** := `NA != 0 && (int32_t)(now_ms - NA) < 0` (wrapper gate, FW:7867-7871 per E04). **`backoff` (DUMP)** := the same over DNA (FW:16436-16437).

**New RAM inputs** [REC, LOCKED]. All are RAM-only (`restore_value: no`), add zero Modbus operations and zero durable writes.

| Owner | New input | Why | Set where |
|---|---|---|---|
| FB-B1 (S1) | `fallback_profile_boot_loaded` (bool) | Obligation mirrors are meaningful only after the on_boot loader (E04 P2). S6 X-5 adopts S1's name for all classifiers | Last statement of on_boot lambda[0] (S1 §4.1) |
| FB-B1 (retention, S6 BLK-11 / S3 P-FBC-05) | `fp_marker_boot_load`, `dump_marker_boot_load`, `reg244_marker_boot_load` (u8 LoadStatus; 0xFF = not assigned) | CLEAR-with-marker vs CLEAR-by-absence exists today only in lambda locals (E04 P3) | Assigned from the existing `marker_load` locals immediately after FW:319-320, 575-576, 729-730 |
| FB-B1 (retention) | `fp_lockout_cause`, `dump_lockout_cause`, `reg244_lockout_cause` (u8 Cause, §8.4; 0 = none) | UNKNOWN vs CORRUPT and the cause exist only in locals and status text (E04 P3). The data-record loads use a bare-bool `load_record` (FW:368, 609, 757), so a data READ_ERROR cannot be told from bad data without changing those calls (which would move the pinned load counts); the cause code `DATA_UNTRUSTED` is honest about that | One assignment next to each of the 14 set sites (FW:334, 346, 460, 470, 587, 592, 657, 741, 746, 763, 821, 822, 910, 911). Each flag's cause is assigned exactly once: every later set site of the same flag is guarded by `!…_metadata_corrupt` (FW:816-817, 905-906) |
| FB-B1 (retention) | `dump_retry_boot_on_raw` (bool) | N is gated on S at boot (FW:676), which discards the evidence "a durable operator lockout exists while the marker is absent" | `have_retry && retry.operator_needed != 0`, next to FW:676 (before the S gate). FP needs no equivalent: ON is already the raw value (FW:487) |
| FB-B1 (probe latch; widens S1's `fallback_profile_probe_alarm`) | `fallback_profile_probe_latch` (u16; FP bits 0-3, DUMP 4-7, R244 8-11; bits per §2.2) | Makes probe findings sticky for the boot (§2.2) | Updated only by the FB-B probe caller (and later FB-E/FB-F). FB-C reads it only |
| RAW_CACHE_EXT (S3 §11.5) | `manual_cfg_reg230_raw`, `manual_cfg_reg243_raw`, `manual_cfg_reg245_raw`, `manual_cfg_reg247_raw`, `manual_cfg_reg248_raw` | No raw cache exists for these (V6 (2)) | Poll Block A `values[30]` and Block B `values[2]`, `[4]`, `[6]`, `[7]` (S3 §11.5) |
| FB-C2 (prefix `failback_shadow_`) | `live_regs` (`std::array<uint16_t,31>`, FallbackProfileV1 field order), `live_latched_seq`, `live_latched_dispatch_seq`, `live_latched_valid` | Torn-snapshot protection (§7.6) | Copied from the raw caches on the first FB-C tick after `cfg_block_b_seq` changes |
| FB-C2 | `live_fence_seq` (u32) | The cache holds lease overlays and pre-write values until a post-release poll (PR53 FW:1625-1631@pr53) | §7.6 |
| FB-C2 | `used_mask` (u8: bit per FP/DUMP/R244 whose `*_snapshot_valid` was observed true this boot), `aborted_start_mask` (u8: OIP/O/rAIP observed true in an operation that ended without SV/S/rSV ever becoming true) | Evidence value MARKER_CLEAR_RUNTIME and the ghost-risk detail (§2.10) | FB-C tick |
| FB-C2 | `fp_orphan_since_ms`, `dump_orphan_since_ms`, `r244_orphan_since_ms`, `mwip_orphan_since_ms` (u32; 0 = not orphaned) | Grace periods (§3.7) | FB-C tick: set on the first tick where the flag is set and no owner script runs; cleared otherwise |
| FB-C2 (S3 episode record) | `ep_prof_bound` (bool), `ep_prof_class` (u8), `ep_prof_gen` (u32), `ep_prof_binding` (u64) | Episode binding (§6.2) | S3 transition E1 (LOST edge) |
| FB-C2 | `exh_since_ms`, `exh_yes_s`, `exh_unknown_s` | `export_hazard` soak accounting (§4.2) | FB-C tick |

### 2.2 The shared classifier contract [REC, LOCKED]

**One implementation.** The per-domain classifiers `classify_fp`, `classify_dump`, `classify_r244`, `classify_mtou`, `classify_bus` (pure, `constexpr`, POD in, `DomainClass {c0, kind, evidence, reason, detail}` out) are implemented **once**, in FB-B1's pure header (S1 names it `ecco_fallback_capture.h`), with a Python mirror alongside FB-B's mirror. FB-C2's `ecco_failback_shadow.h` includes that header; FB-E/FB-F reuse it. The rows in §2.4-§2.9 are the normative specification; where S1 §4.3 differs, S4 wins (see §10.3). A test asserts mirror parity and that no second classifier implementation exists. The header itself contains no I/O (no `nvs_`, `load_record`, `id(`, `modbus`); the probe I/O lives in FB-B0's durable helper (S2's direct reader).

**Callers and their durable leg.**

| Caller | `probe` input | Latch | CLEAR evidence the caller may accept |
|---|---|---|---|
| FB-C (shadow) | always `PROBE_NOT_RUN` (FB-C performs zero NVS reads, S3 FBC-13) | read-only | MARKER_CLEAR_BOOT / MARKER_CLEAR_RUNTIME as a *projection* of FB-F's probe (flag `durable_leg_projected`); MARKER_ABSENT → R3 block (§2.10) |
| FB-B REVIEW and SAVE | fresh direct two-step probe (S2's reader: size probe, then data read; **not** `load_record_status`, S1 §4.2) | read and update | MARKER_CLEAR_PROBE; MARKER_ABSENT (charter C6, operator-attended) |
| FB-E precheck [FUTURE] | fresh probe | read and update | MARKER_CLEAR_PROBE; MARKER_ABSENT only with explicit operator acknowledgement (R3) |
| FB-F precheck [FUTURE] | fresh probe | read and update | MARKER_CLEAR_PROBE; MARKER_ABSENT only with `absence_witness` (R3) |

**Probe latch (per domain, 4 bits, RAM, per boot)** — bit P `PRESENT_SEEN` (a probe returned CLEAR/RR/PC/MALFORMED), bit U `UNREADABLE_SEEN`, bit M `MALFORMED_SEEN`, bit D `DIVERGED_SEEN` (RR or PC while the RAM mirror was clear-shaped).
- **Update** (probing callers only): after each probe, OR in the bit(s) for the result.
- **No re-read**: a caller must not probe a key whose U, M or D bit is set; it classifies from the latch and refuses without I/O. This prevents the IDF sequence "READ_ERROR, then ESP_FAIL (index erased), then NOT_FOUND" (V1 (1), (3); NVSP:280-285, NVSS:697-702) from ever reaching ABSENT through ECCO's own re-reads.
- **Consumption** (every caller, including FB-C): D → UNKNOWN_DIVERGED; else U → UNKNOWN_DURABLE_UNREADABLE; else M → UNKNOWN_METADATA_CORRUPT. The latch outranks the current probe result.
- **Vanish rule**: a current ABSENT after any evidence that the key existed (latch P, or boot load OK, or the domain used since boot) is UNKNOWN_DIVERGED, reason `<D>_MARKER_EVIDENCE_VANISHED`. Markers are never deleted by firmware: CLEAR is committed as state 0, superseded records are kept (DS:753-761), and no `nvs_erase*` call exists in firmware (grep, 0 hits). So "existed, now absent" can only be NVS loss.
- The latch is RAM and dies at reboot. The next boot's ABSENT is therefore unprovable again. That residual is why the existing "reboot to re-read" advice must go (§5 rule c) and why R3 blocks absence for FB-F.

**Probe side effects [IDF] — why probes are rare and never in FB-C.**
- A data chunk whose CRC fails is erased by the read, which returns NOT_FOUND (NVSP:280-285).
- A read whose chunk is missing erases the index and all chunks (NVSS:697-702).
- A size probe can erase an inconsistent entry of a **different** key, and a read error marks the whole page INVALID for the boot (NVSP:948-952, 904-905). A later read of any blob whose chunk sits on that page then permanently erases an intact index (NVSS:672-676, 697-700; V1 N3). That blob could be the profile, a lease data record, or FB-B's own readback.
- Therefore probes run only at operator-attended FB-B REVIEW/SAVE and (future) writer prechecks, never periodically, never in FB-C. A pinned test enumerates the call sites of the direct reader. The FB-B PR documents this collateral.

**Probe pending (FB-E/FB-F only) [FUTURE, LOCKED].** While a writer's precheck probe has not yet completed, the domain classifies with kind `PROBE_PENDING`, which projects to a WAIT (PREEMPT_REQUIRED/0), never to BLOCKED/6. Probes may run while `manual_write_in_progress` is held: NVS reads do not touch Modbus, and all preference I/O runs on the single loop task (V2 (7)).

**Fail-closed zero-init.** A zero-initialised `DomainClass` reads C0_UNKNOWN.

### 2.3 Overview matrix (C0 / shadow decision at LOST)

`—` means the state does not exist for that domain. Detailed predicates follow in §2.4-§2.9.

| Domain | IDLE/CLEAR | ACTIVE (incl. STARTING) | RESTORE_REQUIRED | PENDING_CLEAR | ENDING | CORRUPT | UNKNOWN | OPERATOR_NEEDED | CONTAINMENT |
|---|---|---|---|---|---|---|---|---|---|
| FP | CLEAR_PROVEN (marker evidence) → continue; by absence → R3 block (`FP_MARKER_ABSENT_UNPROVEN`) | ACTIVE / STARTING → `WOULD_PREEMPT_FREE_POWER` | → `WAIT_FREE_POWER_RESTORE` | → `WAIT_FREE_POWER_RESTORE` | → `WAIT_FREE_POWER_RESTORE` | METADATA_CORRUPT → `BLOCKED_RECOVERY_METADATA` | DURABLE_UNREADABLE (boot) → `BLOCKED_RECOVERY_METADATA`; DIVERGED / latched probe findings → `BLOCKED_DURABLE_UNKNOWN`; flag settling/stuck → `WAIT_WRITE_IN_FLIGHT` | → `BLOCKED_OPERATOR_NEEDED` | — |
| DUMP | as FP (`DUMP_MARKER_ABSENT_UNPROVEN`) | → `WOULD_PREEMPT_DUMP` | → `WAIT_DUMP_RESTORE` (`export_hazard` if live 244 = 0) | → `WAIT_DUMP_RESTORE` | → `WAIT_DUMP_RESTORE` (incl. a queued Force) | METADATA_CORRUPT (C, K≠8) → `BLOCKED_RECOVERY_METADATA` | K==8: DURABLE_UNREADABLE → `BLOCKED_RECOVERY_METADATA`; runtime → `BLOCKED_DURABLE_UNKNOWN` | → `BLOCKED_OPERATOR_NEEDED` (+`export_hazard`) | Sub-state of CORRUPT: K 1/5 P0 pending/retrying, 3 in flight, 4 contained but externally revocable, {2,6,7,8} terminal for the boot → `BLOCKED_RECOVERY_METADATA` |
| R244 | as FP (`R244_MARKER_ABSENT_UNPROVEN`) | — (a held test is OPERATOR_NEEDED); Apply running → `WAIT_WRITE_IN_FLIGHT` | — (no automatic restore) | → `BLOCKED_OPERATOR_NEEDED` (operator press only) | operator Restore running → `WAIT_WRITE_IN_FLIGHT` | → `BLOCKED_RECOVERY_METADATA` | as FP | held (RR, not in flight) → `BLOCKED_OPERATOR_NEEDED` | — |
| MTOU | CLEAR_PROVEN (NO_DURABLE_RECORD) | — (persistent config, not a lease) | — | — | apply running → `WAIT_WRITE_IN_FLIGHT` | — | leaked lock → BUS row | — (a failed apply is visible only as drift) | — |
| MTOU_JOURNAL | CLEAR_PROVEN (NOT_IMPLEMENTED) [FUTURE] | — | [FUTURE] | [FUTURE] | [FUTURE] | [FUTURE] | [FUTURE] | [FUTURE] | — |
| FBP | NOT_CAPTURED → `BLOCKED_NO_PROFILE` (proven) or `BLOCKED_PROFILE_UNAVAILABLE` (unproven) | VALID → site/live checks | — | — | — | CORRUPT / CORRUPT_DOMAIN → `BLOCKED_PROFILE_CORRUPT` | UNREADABLE / PROFILE_LOST / SAVE_UNCONFIRMED / changed since LOST → `BLOCKED_PROFILE_UNAVAILABLE` | INVALIDATED → `BLOCKED_PROFILE_INVALIDATED` | — |
| BUS | no lock held → CLEAR_PROVEN (IDLE) | lock held by a running owner → `WAIT_WRITE_IN_FLIGHT` | — | — | — | — | MWIP with no owner ≥ 10 s, or CIP ≥ 60 s → `WAIT_WRITE_IN_FLIGHT` (stuck) | — | — |

### 2.4 FP classifier (first match wins) [REC over MAIN globals, LOCKED]

| # | Column | Predicate | C0 / kind / evidence | Shadow decision at LOST (reason) | Notes |
|---|---|---|---|---|---|
| F0 | — | `!boot_loaded` | UNKNOWN / BOOT_NOT_LOADED | NOT_EVALUATED | S1 flag |
| F1 | CORRUPT / UNKNOWN | `MC` | cause MARKER_UNREADABLE → UNKNOWN / DURABLE_UNREADABLE; any other cause (MALFORMED, DATA_UNTRUSTED, CONTEXT_FIELD_CORRUPT, DUAL_FP_DUMP, or NONE if retention is missing) → UNKNOWN / METADATA_CORRUPT, `detail` = cause | BLOCKED_RECOVERY_METADATA (FP_MARKER_UNREADABLE / FP_METADATA_CORRUPT) | **Test MC first.** MS is 0 (the CLEAR default) only for the marker READ_ERROR and malformed branches (FW:334, 346). For DATA_UNTRUSTED (FW:470), CONTEXT_FIELD_CORRUPT (FW:460) and DUAL_FP_DUMP (FW:910), MS is already RR (FW:350 runs first; V5 (2)). Never cleared |
| F2 | ACTIVE (STARTING) | `OIP && running.START` | OBLIGATION / STARTING | WOULD_PREEMPT_FREE_POWER (FP_STARTING: pre-empt once START completes; ARCH row 7) | START cannot be aborted (R2) |
| F3 | ENDING | `(OIP || FIP || AIP) && running ∩ {RESTORE (wrapper or dispatch), FORCE (wrapper or dispatch), ACCEPT (wrapper or dispatch), REVIEW (wrapper or dispatch)}` | OBLIGATION / ENDING | WAIT_FREE_POWER_RESTORE (FP_RESTORE_RUNNING or FP_OPERATOR_ACTION_RUNNING) | Review holds OIP/MWIP (FW:9347-9348) |
| F4a | IN_FLIGHT | `(OIP || FIP || AIP)`, no F2/F3 script running, orphan age < 10 s | OBLIGATION / IN_FLIGHT | WAIT_WRITE_IN_FLIGHT (FP_OP_FLAG_SETTLING) | A Modbus callback can still be pending (§2.1) |
| F4b | UNKNOWN | same, orphan age ≥ 10 s | UNKNOWN / BUS_OR_LOCK_STUCK | WAIT_WRITE_IN_FLIGHT (FP_OP_FLAG_STUCK) | defensive |
| F5 | PENDING_CLEAR | `SV && MS==PC` | OBLIGATION / PENDING_CLEAR | WAIT_FREE_POWER_RESTORE (FP_CLEAR_PENDING) | Watchdog clear-only every 15 s (FW:18267) |
| F6 | OPERATOR_NEEDED | `SV && MS==RR && ON` | OBLIGATION / OPERATOR_NEEDED | BLOCKED_OPERATOR_NEEDED (FP_OPERATOR_NEEDED) | Exits: End / Force / Accept (P2) |
| F7 | RESTORE_REQUIRED | `SV && MS==RR && (RQ || !AP || expired)` | OBLIGATION / RESTORE_REQUIRED | WAIT_FREE_POWER_RESTORE (FP_RESTORE_DUE, or FP_RESTORE_BACKOFF if `backoff`) | Includes "START aborted after commit" and boot AP→RQ. If `LC == -1`, flag `fp_ctx_unknown` (an INTENDED/SELF_PARTIAL result will context-hold → ON) |
| F8 | ACTIVE | `SV && MS==RR && AP && !RQ && !expired` | OBLIGATION / ACTIVE | WOULD_PREEMPT_FREE_POWER (FP_ACTIVE) | AP stays true after expiry, so it is not the lease-running predicate (E04 P6) |
| F9 | UNKNOWN | `SV` and none of F5-F8 | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (FP_RAM_INCONSISTENT) | defensive |
| F10 | UNKNOWN | `!SV && (AP || RQ)` | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (FP_RAM_INCONSISTENT) | RQ is set only when SV (FW:17651-17653) |
| F11 | CLEAR / UNKNOWN | `!SV && !MC && MS==CLEAR`: durable leg, first match: | | | |
| F11.0 | | boot load ∉ {OK, ABSENT} (WRONG_SIZE / READ_ERROR set MC on MAIN, so this is unreachable; 0xFF = retention missing) | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (FP_RAM_INCONSISTENT) | defensive |
| F11.a | | latch D | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (FP_MARKER_DIVERGED) | Phase-B ghost found by a probe (ARCH row 10) |
| F11.b | | latch U | UNKNOWN / DURABLE_UNREADABLE | BLOCKED_DURABLE_UNKNOWN (FP_PROBE_UNREADABLE) | sticky for the boot |
| F11.c | | latch M | UNKNOWN / METADATA_CORRUPT | BLOCKED_DURABLE_UNKNOWN (FP_PROBE_MALFORMED) | sticky |
| F11.d | | probe ∈ {RR, PC} | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (FP_MARKER_DIVERGED) | caller sets D |
| F11.e | | probe UNREADABLE | UNKNOWN / DURABLE_UNREADABLE | BLOCKED_DURABLE_UNKNOWN (FP_PROBE_UNREADABLE) | caller sets U |
| F11.f | | probe MALFORMED | UNKNOWN / METADATA_CORRUPT | BLOCKED_DURABLE_UNKNOWN (FP_PROBE_MALFORMED) | caller sets M |
| F11.g | | `absent_now && (latch P || (probe==ABSENT && (boot load OK || used since boot)))`, where `absent_now := probe==ABSENT || (probe==NOT_RUN && boot load ABSENT && !used since boot)` | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (FP_MARKER_EVIDENCE_VANISHED) | vanish rule (§2.2) |
| F11.h | | `absent_now && ON` | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (FP_MARKER_LOST) | ON=1 is committed only inside restore/Force attempts of an RR obligation (FW:8742-8743, 8791-8792, 8829-8830, 9030-9031, 10722-10723), and the FP retry tag (commit 5c3575f) postdates the FP marker tag (694d10d). So a durable ON with no marker proves the marker was lost (NVS self-heal, orphan clean-up or partition erase). Prevents capturing a stranded FP overlay (E04 P10) |
| F11.i | | `absent_now` | CLEAR_PROVEN / MARKER_ABSENT | continue in §3.4 to the R3 row (L6): FP_MARKER_ABSENT_UNPROVEN | C6: reported distinctly |
| F11.j | | otherwise | CLEAR_PROVEN / MARKER_CLEAR_PROBE if probe==CLEAR, else MARKER_CLEAR_RUNTIME if used since boot, else MARKER_CLEAR_BOOT | continue | If ON: flag `fp_stale_operator_needed` (non-blocking). A stale ON with a present CLEAR marker is reachable deterministically (a Force/Accept Phase-D failure, then a clear-only retry; V5 (3)) and is latent on MAIN because every consumer gates on SV/RR |

### 2.5 DUMP classifier [REC over MAIN globals, LOCKED; identical for PR52 (E05 §12.2)]

| # | Column | Predicate | C0 / kind / evidence | Shadow decision (reason) | Notes |
|---|---|---|---|---|---|
| D0 | — | `!boot_loaded` | UNKNOWN / BOOT_NOT_LOADED | NOT_EVALUATED | |
| D1 | UNKNOWN | `C && (cause==MARKER_UNREADABLE || K==8)` | UNKNOWN / DURABLE_UNREADABLE | BLOCKED_RECOVERY_METADATA (DUMP_MARKER_UNREADABLE); `export_hazard` per §4.2 | K=8 is set only at FW:588 (READ_ERROR). Containment is not armed (FW:923-924) |
| D2 | CORRUPT (+CONTAINMENT) | `C` otherwise | UNKNOWN / METADATA_CORRUPT; `detail` = cause and K | BLOCKED_RECOVERY_METADATA (DUMP_METADATA_CORRUPT); `export_hazard` per §4.2 | Set sites FW:587, 592, 657, 821, 911; never cleared. K semantics (V4 (6), verified): 1 PENDING_READ and 5 RETRYING re-run P0; 3 CONTAINING is transient inside the script; **4 CONTAINED is revocable**: the watchdog moves it to 7 when a post-containment poll reads 244==0 (FW:18507-18510); 2, 6, 7, 8 are absorbing for the boot. CONTRADICTION #8: the comment at FW:3455 says "2/4/6/7/8 are terminal" |
| D3 | ACTIVE (STARTING) | `O && running.START` | OBLIGATION / STARTING | WOULD_PREEMPT_DUMP (DUMP_STARTING) | |
| D4 | ENDING | `O && running.RESTORE` | OBLIGATION / ENDING | WAIT_DUMP_RESTORE (DUMP_RESTORE_RUNNING) | Includes a Force-bypass run (P2) |
| D5a | IN_FLIGHT | `O`, neither START nor RESTORE running, orphan age < 10 s | OBLIGATION / IN_FLIGHT | WAIT_WRITE_IN_FLIGHT (DUMP_OP_FLAG_SETTLING) | Containment sets O only under C (caught by D1/D2) |
| D5b | UNKNOWN | same, orphan age ≥ 10 s | UNKNOWN / BUS_OR_LOCK_STUCK | WAIT_WRITE_IN_FLIGHT (DUMP_OP_FLAG_STUCK) | defensive |
| D6 | PENDING_CLEAR | `S && M==PC` | OBLIGATION / PENDING_CLEAR | WAIT_DUMP_RESTORE (DUMP_CLEAR_PENDING) | clear-only `dump_clear_verified_marker` has no N term (FW:16835-16840) |
| D7a | ENDING (P2 queued) | `S && M==RR && N && FB` | OBLIGATION / ENDING | WAIT_DUMP_RESTORE (DUMP_FORCE_QUEUED) | [MAIN, V4 NEW] If Force is pressed while a restore is already running, `mode: single` discards the execute (SCRIPT:72-87) and the bypass stays armed; the next watchdog `request_dump_end` (≤ 15 s) consumes it as a Force (FW:16423-16424), skipping the `!N` gate and the backoff |
| D7 | OPERATOR_NEEDED | `S && M==RR && N` | OBLIGATION / OPERATOR_NEEDED | BLOCKED_OPERATOR_NEEDED (DUMP_OPERATOR_NEEDED_EXPORT_LIVE if `export_hazard==YES`, else DUMP_OPERATOR_NEEDED) | §4 |
| D8 | RESTORE_REQUIRED | `S && M==RR && (R || !A || expired)` | OBLIGATION / RESTORE_REQUIRED | WAIT_DUMP_RESTORE (DUMP_RESTORE_DUE / DUMP_RESTORE_BACKOFF); `export_hazard` per §4.2 | The comms path retries forever with every guard suspended (FW:16727-16733, 18351-18355; V4 NEW). Also the post-reboot form of a non-durable lockout (§4.1) |
| D9 | ACTIVE | `S && M==RR && A && !R && !expired` | OBLIGATION / ACTIVE | WOULD_PREEMPT_DUMP (DUMP_ACTIVE) | `request_dump_end` is already a neutral end primitive |
| D10 | UNKNOWN | `S` otherwise | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (DUMP_RAM_INCONSISTENT) | |
| D11 | UNKNOWN | `!S && (A || N || K != 0)` | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (DUMP_RAM_INCONSISTENT) | **R is deliberately not a term**: `request_dump_end` sets it unconditionally (FW:16802) |
| D12 | CLEAR / UNKNOWN | `!S && !C && !O && M==CLEAR`: durable leg exactly as F11.0-F11.j, with reasons `DUMP_*`, where F11.h reads `absent_now && dump_retry_boot_on_raw` → DUMP_MARKER_LOST, and F11.j sets flag `dump_stale_operator_needed` when `dump_retry_boot_on_raw` | as F11 | as F11 | M alone is 0 under UNKNOWN/malformed (FW:585-593), so it is used only after the C/S terms. The stale durable retry with a CLEAR marker is the documented case at FW:666-675. DUMP_VALID_TAG and DUMP_RETRY_TAG were introduced in the same commit (95deec7) |

### 2.6 R244 classifier [REC over MAIN globals, LOCKED]

| # | Column | Predicate | C0 / kind / evidence | Shadow decision (reason) | Notes |
|---|---|---|---|---|---|
| G0 | — | `!boot_loaded` | UNKNOWN / BOOT_NOT_LOADED | NOT_EVALUATED | |
| G1 | CORRUPT / UNKNOWN | `rMC` | cause MARKER_UNREADABLE → DURABLE_UNREADABLE; else METADATA_CORRUPT (`detail` = cause) | BLOCKED_RECOVERY_METADATA (R244_MARKER_UNREADABLE / R244_METADATA_CORRUPT) | Set sites FW:741, 746, 763, 822; never cleared |
| G2 | ACTIVE (STARTING) | `rAIP && running.APPLY` | OBLIGATION / STARTING | WAIT_WRITE_IN_FLIGHT (R244_APPLY_RUNNING); `projected_after` = BLOCKED_OPERATOR_NEEDED | P5 in flight; after its commit the domain is RR |
| G3 | ENDING | `rAIP && running.RESTORE` | OBLIGATION / ENDING | WAIT_WRITE_IN_FLIGHT (R244_RESTORE_RUNNING) | only after an operator press |
| G4a/b | IN_FLIGHT / UNKNOWN | `rAIP`, neither running; orphan age < 10 s / ≥ 10 s | IN_FLIGHT / BUS_OR_LOCK_STUCK | WAIT_WRITE_IN_FLIGHT (R244_OP_FLAG_SETTLING / R244_OP_FLAG_STUCK) | |
| G5 | PENDING_CLEAR | `rSV && rMS==PC` | OBLIGATION / PENDING_CLEAR | BLOCKED_OPERATOR_NEEDED (R244_CLEAR_PENDING_OPERATOR) | Cleared only by an armed manual Restore with config online (FW:14366-14373, 14397-14422) |
| G6 | OPERATOR_NEEDED (the only "ACTIVE" form) | `rSV && rMS==RR` | OBLIGATION / OPERATOR_NEEDED | BLOCKED_OPERATOR_NEEDED (R244_HELD, or R244_HELD_DRIFT_GUARD when `LAV && live244 != LA`: the restore would be refused, FW:14511) | R244 has no watchdog, expiry or automatic restore (E04 §5.3). ARCH §6.3 row 8 folds "reg244 obligation pending (v1)" into LEASE_RESTORE_LOCKED (ARCH:529@pr54) |
| G7 | UNKNOWN | `rSV` otherwise | UNKNOWN / DIVERGED | BLOCKED_DURABLE_UNKNOWN (R244_RAM_INCONSISTENT) | |
| G8 | CLEAR / UNKNOWN | `!rSV && !rMC && rMS==CLEAR`: durable leg as F11.0-F11.j with reasons `R244_*`, **without** an F11.h rule | as F11 | as F11 | **LAV/LA are not obligation state.** `LAV && absent_now` only sets the non-blocking flag `r244_lav_marker_absent`: LAV was introduced (a72bd5f) before the reg244 marker tag (694d10d), so a LAV=true with no marker can be legitimate history, not proof of loss |

**CONTRADICTION (doc vs doc; resolved here) [DOC→REC].**
- ARCH §6.3 row 8 (ARCH:529@pr54) says BLOCKED(LEASE_RESTORE_LOCKED).
- ARCH §6.5 / §6.6 / A25 (ARCH:581, 589, 913@pr54) say BLOCKED(REG244_PENDING), and list it as ACK-able.
- FB-A has no REG244_PENDING code (FBH:275-291@pr54).
- **LOCKED:** a pending R244 obligation → `BLOCKED_OPERATOR_NEEDED` → FB-A 5 LEASE_RESTORE_LOCKED. The exit is "resolve the lease first" (ARCH:590@pr54 semantics), never ACK.

### 2.7 MTOU classifier (MAIN and PR53 identical) [REC, LOCKED]

| # | Column | Predicate | C0 / kind / evidence | Decision |
|---|---|---|---|---|
| T1 | ENDING / in flight | any `apply_manual_slot1..6.is_running()` | OBLIGATION / IN_FLIGHT | WAIT_WRITE_IN_FLIGHT (MTOU_APPLY_RUNNING) |
| T2 | CLEAR | otherwise | CLEAR_PROVEN / NO_DURABLE_RECORD | continue |

- PR53 adds no MTOU in-flight global and no durable key (E06 §8; `manual_tou_owner_seen` FW:1621@pr53 is an FP/Dump staging fence, not an MTOU obligation). The predicate is identical in both trees.
- After the slot script ends, its verify callback may still hold MWIP (§2.1); that tail is reported by the BUS row (B3 settling), not MTOU. On MAIN, a diverted verify leaks MWIP with no MTOU script running; that is B1.
- **Residual:** a reboot during an apply leaves no trace (E06 §6.4). The partial state is visible to FB-C only as E1/CTX drift (§7).

### 2.8 MTOU_JOURNAL placeholder [FUTURE, interface LOCKED now]
- FB-C2 carries an input `mtou_journal_class`. The only value produced until a journal exists is `MTJ_NOT_IMPLEMENTED`, which classifies as CLEAR_PROVEN (evidence NOT_IMPLEMENTED). A test pins that no other value is produced (S1 §4.3 adds a tag-name tripwire).
- When a durable Manual TOU journal lands, it must provide a classifier with the same contract (§2.2), including the latch and vanish rules. The mapping must be:
  - ABSENT → CLEAR_PROVEN(MARKER_ABSENT), subject to R3;
  - CLEAR → CLEAR_PROVEN(MARKER_CLEAR_*);
  - RR with an automatic resolution → OBLIGATION_RESTORE_REQUIRED → reserved plan `WAIT_MANUAL_TOU_RECOVERY` (16);
  - RR without automatic resolution → OBLIGATION_OPERATOR_NEEDED → BLOCKED_OPERATOR_NEEDED;
  - malformed → BLOCKED_RECOVERY_METADATA (boot) or BLOCKED_DURABLE_UNKNOWN (runtime);
  - READ_ERROR → the same split.
- Precedence position: row L11 (§3.4).

### 2.9 BUS pseudo-domain [REC, LOCKED]

**Owner list (pinned).** Exactly the 20 scripts that assign `manual_write_in_progress = true` (§1.2 grep), plus the FB-B capture script(s):
- `start_free_power_override`
- `restore_free_power_snapshot`, `restore_free_power_snapshot_dispatch`
- `free_power_recovery_review_dispatch`
- `free_power_recovery_force_restore`, `free_power_recovery_force_restore_dispatch`
- `free_power_recovery_accept_current_state`, `free_power_recovery_accept_current_state_dispatch`
- `apply_manual_slot1..6`
- `apply_reg244_settings`, `restore_reg244_snapshot`
- `start_dump_to_grid_override`, `dump_controller_tick`, `restore_dump_to_grid_snapshot`, `dump_lockout_containment`

A test must assert that the set of scripts assigning `manual_write_in_progress = true` equals this list.

| # | Predicate | C0 / kind / evidence | Decision |
|---|---|---|---|
| B1 | `MWIP && !any_owner_running && mwip_orphan_ms >= 10000` | UNKNOWN / BUS_OR_LOCK_STUCK | WAIT_WRITE_IN_FLIGHT (LOCK_HELD_NO_KNOWN_OWNER) |
| B2 | `CIP && cip_held_ms >= 60000` | UNKNOWN / BUS_OR_LOCK_STUCK | WAIT_WRITE_IN_FLIGHT (RTC_LOCK_STUCK) |
| B3 | `MWIP` (owner running, or no owner for < 10 s) | OBLIGATION / IN_FLIGHT | WAIT_WRITE_IN_FLIGHT (FBB_CAPTURE_RUNNING / LOCK_HELD_OWNER_RUNNING / LOCK_HELD_SETTLING) |
| B4 | `CIP` | OBLIGATION / IN_FLIGHT | WAIT_WRITE_IN_FLIGHT (RTC_CORRECTION_RUNNING) |
| B5 | otherwise | CLEAR_PROVEN / IDLE | continue |

`cip_held_ms` = `now - diag_correction_lock_since_ms` while `diag_correction_lock_held` (FW:3642-3646; sampled by the PR-A tick). `mwip_orphan_ms` comes from FB-C's own timer (§2.1), not from the PR-A diagnostic, because it must reset whenever an owner is running. Thresholds: §3.7.

### 2.10 The durable leg inside FB-C: no NVS reads [REC, LOCKED]

- **No probes.** FB-C performs zero NVS reads (concurs with S3 FBC-13 and S6 X-1; OVERTURNS CHARTER C7 in part). Any read could erase a corrupt entry and turn the next boot's fail-closed READ_ERROR into ABSENT (§2.2 side effects), and FB-C has no authority to act on what it finds. FB-C's YAML and header contain no `nvs_`, `load_record`, `global_preferences` (S3 pin Z3).
- **Evidence FB-C uses.** Boot-load retention (`*_marker_boot_load`), lockout causes, `dump_retry_boot_on_raw`, `used_mask`, and FB-B's probe latch (read-only RAM). Evidence values: MARKER_CLEAR_BOOT, MARKER_CLEAR_RUNTIME (the domain was active since boot and its CLEAR commit returned true), MARKER_ABSENT, plus the latch-derived UNKNOWN classes. FB-C marks its projection `durable_leg_projected = 1` whenever it accepts MARKER_CLEAR_BOOT/RUNTIME in place of FB-F's precheck probe.
- **R3 projection.** A domain CLEAR_PROVEN by MARKER_ABSENT, with `absence_witness == false`, makes the plan `BLOCKED_DURABLE_UNKNOWN` with reason `<D>_MARKER_ABSENT_UNPROVEN` (row L6). `absence_relied = 1`. The evaluator also publishes `alt_plan_absence_accepted`, the plan that would result if absence were accepted (§3.5), so soak data still shows what an absence-accepting engine would have done.
- **`absence_witness`** is an input reserved for FB-D's witness strategy [FUTURE]. FB-C2 always passes `false`; a test pins that no other value is produced. The preferred FB-D design [FUTURE, REC] is lease-marker provisioning: once, under an operator-attended action with every domain RAM-idle and CLEAR by absence, write a CLEAR marker into each absent lease domain with direct readback, so that from then on ABSENT on that domain means loss (DIVERGED). This needs FB-D's own relaxation of §5 rule (a) and is not built by FB-B or FB-C.
- **Blind spots (reported, not hidden).**
  1. A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear) is invisible unless FB-B's REVIEW/SAVE probe latched it this boot. FB-F's precheck probe owns it (ARCH row 10, `ARCH:531`; A17 `ARCH:905`). The detail `aborted_start_mask` flags START attempts that ended without an obligation in RAM (ghost possible).
  2. Runtime corruption of a present marker is invisible until probed.
  3. A partition erase (E04 P10; ESPHome erases the partition when `nvs_open` fails, V2 (5)) makes every marker ABSENT. F11.h/D12 catch it only if a retry record survived; otherwise R3 blocks FB-F by absence anyway.
  4. The FBP record: FB-C uses FB-B's RAM mirror, authoritative for the episode (§6.3).

---

## 3. Pure evaluator specification (FB-C Q11 deliverable c)

### 3.1 Placement and purity [REC, LOCKED]
- **Header.** `firmware/include/ecco_failback_shadow.h` (S3's header; the evaluator lives in namespace `ecco_failback_shadow`). Standalone, `constexpr`, no `id(`, no `modbus`, no `nvs_`, no `commit_record`/`load_record`, no `App.`. It includes only the FB-A header (`ecco_fallback_profile.h`) and FB-B1's classifier header (S3 pin Z3's include allowlist must list the latter).
- **Python mirror.** `registry/failback_shadow.py`, stdlib only. It must avoid the tokens `self_partial` / `start_journal` (test_sg01_phase0_harness.py:182-187@main per E10).
- **Collector.** Step 5 of S3's FB-C tick lambda (S3 §3.8; the FB-C interval placed immediately before the PR-A tick, S3 FBC-15). It fills `ShadowInputs` from globals by value, holds no lock, performs no I/O, and calls the header. No second interval is added.
- **Calls per tick.** `evaluate(MODE_IF_LOST)` every tick ("readiness"; frozen as S3's edge plan `v0` at E1) and `evaluate(MODE_ACTUAL)` (the verdict, including the supervision rows). Inside `evaluate`, at most two one-level re-runs (`projected_after`, `alt_plan_absence_accepted`). Pure RAM compute.

### 3.2 Input struct

```cpp
namespace ecco_failback_shadow {
enum Mode : uint8_t { MODE_ACTUAL = 0, MODE_IF_LOST = 1 };
enum Probe : uint8_t { PROBE_NOT_RUN = 0, PROBE_ABSENT = 1, PROBE_CLEAR = 2, PROBE_RR = 3, PROBE_PC = 4,
                       PROBE_MALFORMED = 5, PROBE_UNREADABLE = 6 };
constexpr uint8_t LATCH_P = 1, LATCH_U = 2, LATCH_M = 4, LATCH_D = 8;   // per-domain nibble (§2.2)
// FBP class: 0..5 == ecco_fallback::ProfileClass (FBH:542-549@pr54); 16 PROFILE_LOST and 17 SAVE_UNCONFIRMED
// are FB-B RAM views (16 matches S1's candidate-binding code for PROFILE_LOST).
enum FbpClass : uint8_t { FBP_UNREADABLE = 0, FBP_NOT_CAPTURED = 1, FBP_CORRUPT = 2, FBP_CORRUPT_DOMAIN = 3,
                          FBP_INVALIDATED = 4, FBP_VALID = 5, FBP_PROFILE_LOST = 16, FBP_SAVE_UNCONFIRMED = 17 };
struct Durable { uint8_t boot_load /*LoadStatus, 0xFF none*/, cause, probe, latch; bool used_since_boot,
                 retry_on_raw /*FP: ON; DUMP: dump_retry_boot_on_raw; R244: false*/, absence_witness /*false*/; };
struct SupIn   { uint8_t state; bool p_stable; bool episode_open; };
struct FpIn    { bool sv, mc, ap, rq, on, oip, fip, aip; uint8_t ms; int8_t lease_ctx; uint32_t end_epoch, next_attempt_ms;
                 uint8_t running; /*bit0 START,1 RESTORE,2 FORCE,3 ACCEPT,4 REVIEW (wrapper|dispatch)*/
                 uint32_t orphan_ms; Durable d; uint16_t snap232, snap256[6], snap268[6], snap274[6]; };
struct DumpIn  { bool s, a, r, o, n, c, dl, force_bypass; uint8_t m, k; uint32_t end_epoch, next_attempt_ms;
                 uint8_t running; /*bit0 START,1 RESTORE,2 CONTAINMENT,3 CONTROLLER*/
                 uint32_t orphan_ms; Durable d; uint16_t snap244, snap256[6]; };
struct R244In  { bool rsv, rmc, raip, lav; uint8_t rms; uint16_t la, snap_value;
                 uint8_t running; /*bit0 APPLY,1 RESTORE*/ uint32_t orphan_ms; Durable d; };
struct BusIn   { bool mwip, cip, any_owner_running, fbb_capture_running; uint8_t mtou_running; /*6 bits*/
                 uint32_t mwip_orphan_ms, cip_held_ms; };
struct LiveIn  { bool latched, latched_valid; uint8_t cache_state; /*S3 'ca': 'F','S','I','O'*/
                 uint32_t latched_dispatch_seq, fence_seq;
                 uint16_t regs[31]; /* FallbackProfileV1 payload order: 244, 256-261, 268-273, 274-279,
                                       232, 243, 248, 250-255, 230, 245, 247 */ };
struct FbpIn   { uint8_t cls; bool not_captured_proven; ecco_fallback::FallbackProfileV1 rec;
                 /* rec meaningful iff cls in {VALID, INVALIDATED, CORRUPT_DOMAIN} */ };
struct EpProf  { bool bound; uint8_t cls; uint32_t gen; uint64_t binding; };
struct ShadowInputs {
  uint8_t mode; bool boot_loaded; uint32_t now_ms; bool clock_valid; uint32_t now_epoch;
  SupIn sup; FpIn fp; DumpIn dump; R244In r244; BusIn bus; uint8_t mtou_journal /*0 = NOT_IMPLEMENTED*/;
  FbpIn fbp; EpProf ep_prof; LiveIn live; uint16_t site_tou_ceiling_w;
};
}
```

**Field sources** [MAIN unless marked]:

| Field | Source |
|---|---|
| `sup.state` | `supervision_state` FW:3539 |
| `sup.p_stable` | S3 `P_STABLE(now)` over `supervision_state`, `supervision_stable` (FW:3600), `supervision_valid_count` (FW:3574), `supervision_last_valid_ms` (FW:3547) |
| `sup.episode_open` | S3 `failback_shadow_phase ∈ {OPEN, HA_BACK}` |
| `boot_loaded` | `fallback_profile_boot_loaded` (S1; S6 X-5) |
| `now_ms` | `millis()` |
| `clock_valid` / `now_epoch` | `ntp_time.now().is_valid()` / `.timestamp`. The same predicate the watchdogs use (FW:18272-18273), **not** `ntp_synced`: FB-C mirrors the lease expiry rule exactly |
| `fp.*` | FP globals in §2.1. `running` from `is_running()` of `start_free_power_override`, `restore_free_power_snapshot`, `restore_free_power_snapshot_dispatch`, `free_power_recovery_force_restore(_dispatch)`, `free_power_recovery_accept_current_state(_dispatch)`, `free_power_recovery_review(_dispatch)`. `snap*` from FW:1656-1735. `d` from the retention globals, the latch nibble and `used_mask`; `retry_on_raw` = ON |
| `dump.*` | DUMP globals in §2.1; `force_bypass` = `dump_force_restore_bypass` FW:3037. `snap244` FW:2854; `snap256` FW:2858-2878 |
| `r244.*` | R244 globals in §2.1 |
| `bus.mwip` / `bus.cip` | FW:1477 / FW:1283 |
| `bus.cip_held_ms` | `now - diag_correction_lock_since_ms` when `diag_correction_lock_held` (FW:3642-3646) |
| `bus.any_owner_running` | OR of `is_running()` over the §2.9 owner list |
| `bus.fbb_capture_running` | FB-B capture script (S1) |
| `bus.mtou_running` | `apply_manual_slot1..6.is_running()` |
| `fbp.cls` / `fbp.rec` | FB-B RAM mirror (S1/S2 names). PROFILE_LOST exists only if FB-B adopts the witness (charter C3) |
| `fbp.not_captured_proven` | FB-B witness view: true only if a witness record is present, valid, and its high-water generation is 0. Constant `false` if S2 does not adopt a witness (pinned) |
| `ep_prof` | S3 episode record (§2.1 FB-C2 rows) |
| `live.*` | FB-C2 latch (§7.6); `cache_state` per S3 §11.5 (O: `!configuration_polling` FW:4050; I: `!manual_config_raw_cache_valid` FW:1361 or `!configuration_online` FW:4315; S: `cfg_block_b_seq == 0` FW:3120 or `now - cfg_block_b_ok_ms > ${ecco_failback_shadow_cache_max_age_ms}` FW:3124) |
| `site_tou_ceiling_w` | `${ecco_inverter_tou_power_ceiling_w}` = 8000 (FW:13) |

### 3.3 Output struct and enums

```cpp
enum ExportHazard : uint8_t { EXH_UNKNOWN = 0, EXH_NO = 1, EXH_YES = 2 };   // zero-init reads UNKNOWN
struct ShadowPlan {
  uint8_t  plan;                      // PlanCode (§8.1)
  uint16_t reason;                    // ReasonCode (§8.3)
  uint8_t  blocking_domain;           // 0 NONE,1 SUPERVISION,2 BOOT,3 DUMP,4 FP,5 R244,6 BUS,7 MTOU,8 MTOU_JOURNAL,9 FBP,10 SITE,11 LIVE
  uint8_t  fba_state, fba_result;     // Policy-B projection: ecco_fallback::FailbackState/Result, or 0xFF = RAM-only
  uint8_t  fba_result_policy_a;       // derived (§3.5)
  uint8_t  projected_after;           // PlanCode after the awaited pre-emption/restore (best effort), else = plan
  uint8_t  alt_plan_absence_accepted; // PlanCode if MARKER_ABSENT were accepted, else = plan
  uint8_t  export_hazard;             // ExportHazard (§4.2)
  bool would_refuse_starts, would_preempt_fp, would_preempt_dump, would_apply, would_write_244;
  bool absence_relied, durable_leg_projected, fp_stale_operator_needed, dump_stale_operator_needed,
       r244_lav_marker_absent, fp_ctx_unknown, profile_changed_since_lost, dump_force_bypass_armed;
  uint8_t  aborted_start_mask;        // copied from the collector
  uint32_t e1_delta_mask;             // bit0 244; bits1-6 256-261; bits7-12 268-273; bits13-18 274-279
  uint32_t out_of_domain_mask;        // same layout
  uint16_t ctx_mismatch_mask;         // bit0 232.b0; bit1 243; bit2 248.b0; bits3-8 250-255
  uint8_t  info_mismatch_mask;        // bit0 230; bit1 245; bit2 247; bit3 232 bits1-15; bit4 248 bits1-15
  uint8_t  projected_frames;          // bit0 F244(0->2); bit1 F256_DOWN; bit2 F268_279; bit3 F256_UP
  uint8_t  projected_frame_count;
  uint8_t  dom_c0[7], dom_kind[7], dom_evidence[7], dom_detail[7]; // order: DUMP, FP, R244, BUS, MTOU, MTOU_JOURNAL, FBP
};
```

S3's publication fields map as: `fbr` = `fba_result`; `preempt_mask` = {`would_preempt_fp`, `would_preempt_dump`}; `blocks_rmp` = R (F244 + F256_DOWN), M (F268_279), P (F256_UP).

C0 enum (fail-closed zero-init): `C0_UNKNOWN=0, C0_OBLIGATION=1, C0_CLEAR_PROVEN=2`.

Kind enum:

| Value | Kind | | Value | Kind |
|---|---|---|---|---|
| 0 | NONE | | 16 | DURABLE_UNREADABLE |
| 1 | ACTIVE | | 17 | METADATA_CORRUPT |
| 2 | STARTING | | 19 | BOOT_NOT_LOADED |
| 3 | RESTORE_REQUIRED | | 20 | DIVERGED |
| 4 | ENDING | | 21 | BUS_OR_LOCK_STUCK |
| 5 | PENDING_CLEAR | | 23 | PROBE_PENDING (FB-E/FB-F only; never produced by FB-C) |
| 6 | OPERATOR_NEEDED | | | |
| 7 | IN_FLIGHT | | | |

(18 and 22 are intentionally unused: the earlier METADATA_LOCKOUT and NOT_PROBED kinds were withdrawn; see §11 items 5 and 17.)

Evidence enum (CLEAR_PROVEN only): `0 NONE, 1 MARKER_CLEAR_BOOT, 2 MARKER_CLEAR_RUNTIME, 3 MARKER_CLEAR_PROBE, 4 MARKER_ABSENT, 5 NO_DURABLE_RECORD, 6 NOT_IMPLEMENTED, 7 IDLE`.

### 3.4 Deterministic precedence (first match wins) [REC, LOCKED, NORMATIVE]

Pre-step: every domain is classified by §2.4-§2.9 (pure), FBP by §6, and `export_hazard` by §4.2. Within a row, the domain tie-break is DUMP → FP → R244 → BUS → MTOU → MTOU_JOURNAL.

| Row | Condition | Plan | Reason | Blocking |
|---|---|---|---|---|
| E0 | any enum input out of range (e.g. `fbp.cls ∉ {0..5,16,17}`, `k > 8`, `m > 2`) | NOT_EVALUATED | INPUT_INVALID | BOOT |
| E1 | `!boot_loaded` | NOT_EVALUATED | BOOT_NOT_LOADED | BOOT |
| S0 | Let `effective_lost := mode==IF_LOST || sup.state==LOST(3) || sup.episode_open`. Set `would_refuse_starts := !sup.p_stable || sup.episode_open || mode==IF_LOST` | (no emission) | | |
| S1 | `!effective_lost && sup.p_stable` | NO_ACTION | SUP_STABLE | NONE |
| S2 | `!effective_lost` (STARTUP / SUSPECT / SUPERVISED without stable) | WOULD_REFUSE_STARTS | SUP_STARTUP / SUP_SUSPECT / SUP_UNSTABLE | SUPERVISION |
| — | *Every row below is the LOST branch. Reason detail SUP_RETURNED_EPISODE_OPEN is set when an episode is open and state ≠ LOST* | | | |
| L1 | DUMP ∈ {ACTIVE, STARTING} | WOULD_PREEMPT_DUMP | DUMP_ACTIVE / DUMP_STARTING | DUMP |
| L2 | FP ∈ {ACTIVE, STARTING} | WOULD_PREEMPT_FREE_POWER | FP_ACTIVE / FP_STARTING | FP |
| L3 | a RAM hard lockout: D1/D2, F1, G1 | BLOCKED_RECOVERY_METADATA | domain-specific | that domain |
| L4 | kind DIVERGED (F9-F11.h, D10-D12, G7-G8), or a latch/probe-derived DURABLE_UNREADABLE / METADATA_CORRUPT (F11.b/c/e/f and D/G equivalents) | BLOCKED_DURABLE_UNKNOWN | `*_MARKER_DIVERGED` / `*_MARKER_EVIDENCE_VANISHED` / `*_MARKER_LOST` / `*_PROBE_*` / `*_RAM_INCONSISTENT` | that domain |
| L5 | OPERATOR_NEEDED: D7, F6, G5, G6 | BLOCKED_OPERATOR_NEEDED | DUMP_OPERATOR_NEEDED[_EXPORT_LIVE] / FP_OPERATOR_NEEDED / R244_HELD[_DRIFT_GUARD] / R244_CLEAR_PENDING_OPERATOR | that domain |
| L6 | R3: a temporary domain CLEAR_PROVEN with evidence MARKER_ABSENT and `!absence_witness` (skipped in the `alt_plan_absence_accepted` re-run) | BLOCKED_DURABLE_UNKNOWN | `*_MARKER_ABSENT_UNPROVEN` | that domain |
| L7 | stuck: BUS B1/B2, or F4b/D5b/G4b | WAIT_WRITE_IN_FLIGHT | LOCK_HELD_NO_KNOWN_OWNER / RTC_LOCK_STUCK / `*_OP_FLAG_STUCK` | BUS / that domain |
| L8 | DUMP ∈ {RESTORE_REQUIRED, ENDING (incl. D7a), PENDING_CLEAR} | WAIT_DUMP_RESTORE | DUMP_RESTORE_DUE / _BACKOFF / _RUNNING / DUMP_FORCE_QUEUED / DUMP_CLEAR_PENDING | DUMP |
| L9 | FP ∈ {RESTORE_REQUIRED, ENDING, PENDING_CLEAR} | WAIT_FREE_POWER_RESTORE | FP_RESTORE_DUE / _BACKOFF / _RUNNING / FP_OPERATOR_ACTION_RUNNING / FP_CLEAR_PENDING | FP |
| L10 | in flight: R244 STARTING/ENDING (G2/G3), any IN_FLIGHT kind (F4a/D5a/G4a, MTOU T1, BUS B3/B4) | WAIT_WRITE_IN_FLIGHT | R244_APPLY_RUNNING / R244_RESTORE_RUNNING / `*_OP_FLAG_SETTLING` / MTOU_APPLY_RUNNING / FBB_CAPTURE_RUNNING / LOCK_HELD_OWNER_RUNNING / LOCK_HELD_SETTLING / RTC_CORRECTION_RUNNING | R244 / that domain / MTOU / BUS |
| L11 | MTOU_JOURNAL not CLEAR_PROVEN [FUTURE] | per §2.8 | MTOU_JOURNAL_OBLIGATION | MTOU_JOURNAL |
| — | *Invariant: every temporary domain is CLEAR_PROVEN with R3-accepted evidence (§1.1; MARKER_CLEAR_BOOT/RUNTIME accepted as a projection, `durable_leg_projected`)* | | | |
| L12 | `sup.episode_open && ep_prof.bound && (ep_prof.cls != fbp.cls || (meaningful(fbp.cls) && (fbp.rec.generation != ep_prof.gen || fbp.rec.binding != ep_prof.binding)))`, where `meaningful(c) := c ∈ {VALID, INVALIDATED, CORRUPT_DOMAIN}`; `fbp.rec` is never read otherwise | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_CHANGED_SINCE_LOST | FBP |
| L13 | `fbp.cls == SAVE_UNCONFIRMED` | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_SAVE_UNCONFIRMED | FBP |
| L14 | UNREADABLE | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_UNREADABLE | FBP |
| L15 | PROFILE_LOST | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_LOST | FBP |
| L16 | CORRUPT | BLOCKED_PROFILE_CORRUPT | PROFILE_CORRUPT | FBP |
| L17 | CORRUPT_DOMAIN | BLOCKED_PROFILE_CORRUPT | PROFILE_CORRUPT_DOMAIN | FBP |
| L18 | NOT_CAPTURED && `!fbp.not_captured_proven` | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_ABSENT_UNPROVEN | FBP |
| L19 | NOT_CAPTURED && `fbp.not_captured_proven` | BLOCKED_NO_PROFILE | PROFILE_NOT_CAPTURED | FBP |
| L20 | INVALIDATED | BLOCKED_PROFILE_INVALIDATED | PROFILE_INVALIDATED | FBP |
| — | *`fbp.cls == VALID` from here on* | | | |
| L21 | any `fbp.rec.reg256_261[i] > site_tou_ceiling_w` | BLOCKED_SITE_CEILING | SITE_CEILING_BELOW_PROFILE | SITE |
| L22 | live not trustworthy (§7.6) | WAIT_LIVE_DATA | LIVE_NOT_LATCHED / LIVE_POLLING_OFF / LIVE_CACHE_INVALID / LIVE_CACHE_STALE / LIVE_CACHE_PRE_FENCE | LIVE |
| L23 | `ctx_mismatch_mask != 0` (§7.2) | BLOCKED_CONTEXT_MISMATCH | CTX_SLOT_TIMES / CTX_243 / CTX_232_BIT0 / CTX_248_BIT0 / CTX_MULTIPLE | LIVE |
| L24 | `out_of_domain_mask != 0` (§7.4) | BLOCKED_LIVE_OUT_OF_DOMAIN | LIVE_244_ESSENTIALS / LIVE_244_UNRECOGNISED / LIVE_POWER_OUT_OF_RANGE / LIVE_SOC_OUT_OF_RANGE / LIVE_SOURCE_WORD_UNSUPPORTED / LIVE_MULTIPLE_OUT_OF_DOMAIN | LIVE |
| L25 | `e1_delta_mask == 0` | WOULD_ALREADY_MATCH | MATCH_E1_AND_CTX | NONE |
| L26 | otherwise | WOULD_APPLY_PROFILE | E1_DELTA | NONE |

**Rationale for the order:**
- **L1-L2 before the lockout rows.** Pre-emption at the LOST edge is a P1 *request*: it lets the lease's own recovery run and has no register effect of its own (ARCH §6.3 rows 4-6, ARCH:525-527@pr54). On MAIN, ACTIVE/STARTING cannot coexist with any corrupt flag or `operator_needed` (§1.5), so this is determinism only.
- **L3 before L4.** RAM hard lockouts are permanent for the boot. Divergence findings are runtime or cross-record findings.
- **L3-L6 before the waits (L7-L10).** Each fixes the final outcome for this episode; reporting it early is more honest than reporting WAIT. L6 comes after L4/L5 because divergence and operator-needed reasons are more specific.
- **L7 before L8-L9.** A stuck lock prevents the awaited restore from ever running (N2).
- **L12 before L13-L20.** A profile that changed under the episode is the most specific FBP finding. Its test reads the record only for meaningful classes.
- **L13-L18 before L19-L20.** "Unknown storage" classes come before the proven classes, so a doubtful store never reads as "nothing saved".
- **L21 before L22.** The site ceiling needs no live data.
- **L23 before L24.** Context mismatch means the profile's meaning may not hold; out-of-domain means FROM cannot be recorded. Both are zero-write blocks.
- Every mask and flag is computed on **every** evaluation where its inputs exist (masks only when live is trustworthy and the profile is VALID or CORRUPT_DOMAIN). Telemetry is independent of which row won.

### 3.5 Projection rules [REC, LOCKED]

- **Projected write set.** The ARCH §6.4 apply shape (ARCH:538-559@pr54) with every 230 step removed per Addendum B.2 (ARCH:1295@pr54). [FUTURE] FB-E owns the final algorithm, and FB-C's projection function must be re-pinned against FB-E's when FB-E lands. Frames:
  - **F244** iff `live244 == 0` (the only permitted write, `reg244_write_permitted(0,2)`, FBH:176-178@pr54);
  - **F256_DOWN** iff any `profile256[i] < live256[i]` (writes `min(live, profile)` per slot);
  - **F268_279** iff any 268-273 or 274-279 word differs (one 12-register FC16, full words; safe because live and profile words are both in {0,1} once L24 passed);
  - **F256_UP** iff any `profile256[i] > live256[i]`.
- **`would_write_244`** := F244.
- **`projected_after`** (best effort; never changes `plan`). For L1, L2, L8, L9 the evaluator is re-run once with a transformed input:
  - the named domain → CLEAR_PROVEN (evidence MARKER_CLEAR_RUNTIME);
  - for FP: live 232, 256-261, 268-279 → the FP snapshot (valid because the domain was not MC and MS==RR);
  - for DUMP: live 244 and 256-261 → the Dump snapshot (only if `dl`);
  - for PENDING_CLEAR, live is unchanged (hardware is already ORIGINAL).
  If a snapshot is unavailable, `projected_after = WAIT_LIVE_DATA`. No recursion beyond one level.
- **`alt_plan_absence_accepted`.** Re-run once with row L6 disabled. It equals `plan` whenever L6 did not fire.
- **Policy A vs B [LOCKED for FB-C].** The plan projects **Policy B** ("B as the architecture", ARCH Q1, `ARCH:991@pr54`; brief "one-shot convergence"). `fba_result_policy_a` is derived: `LATCHED_COMPLETE / 1 PREEMPTED_ONLY` if the plan was produced by any row L12-L26 (every temporary domain positively clear, ARCH row 11 Policy A, `ARCH:532`); otherwise it equals the Policy-B projection. FB-D's choice between A and B changes no FB-C code.

### 3.6 Fail-closed and determinism rules [REC, LOCKED]
- A zero-initialised `ShadowPlan` reads `NOT_EVALUATED` / C0_UNKNOWN / `EXH_UNKNOWN` / fba 0xFF.
- The evaluator reads no clock, no global and no NVS. Identical inputs give identical outputs; a golden-vector test pins this.
- The evaluator never returns WOULD_APPLY_PROFILE or WOULD_ALREADY_MATCH unless all of these hold:
  - every temporary domain is C0_CLEAR_PROVEN with R3-accepted evidence (`absence_witness` required for MARKER_ABSENT);
  - `fbp.cls == VALID` and the episode binding (if any) is unchanged;
  - live is trustworthy;
  - the site, CTX and domain checks pass.
  This is the "positively clear" contract. A test enumerates every other class and evidence value and asserts this.
- FB-C's wording never advises a reboot for any `*_MARKER_UNREADABLE` / `*_PROBE_*` / `*_MARKER_*` reason (§5 rule c); a string test pins it.

### 3.7 Thresholds [REC, LOCKED initial values + revision rule]

| Constant (header `constexpr`, `ecco_failback_shadow.h`) | Initial value | Used by | Basis |
|---|---|---|---|
| `kOwnerGraceMs` | 10 000 ms | F4, D5, G4 settling vs stuck; B1 / B3 no-owner | Longest legitimate callback tail after a script ends is a pending Modbus reply: 2000 ms response timeout plus 600 ms turnaround (V6 (6)), behind at most one queued frame; 10 s is ≥ 2× that |
| `kCipStuckMs` | 60 000 ms | B2 | An RTC correction is a handful of frames; ARCH's breaker uses 300 s (per E02 §3.8). FB-C only reports, so a short threshold is safe |
| `kFenceOffset` | 2 | §7.6 | PR53 technique (FW:1625-1631@pr53): Block A of an in-flight poll is pre-fence |
| cache max age | 180 000 ms, via S3's substitution `ecco_failback_shadow_cache_max_age_ms` (= `ecco_dump_cfg_stale_ms`, FW:36) | cache state S | Two 60 s polls plus margin (S3) |

**Revision rule.** The lock constants are header `constexpr` (not substitutions), so the PR-A substitution pin (PRA-T:382-384) is untouched by S4; the cache-age substitution is S3's and uses S3's single amendment (FBC-21). A value may change only in a PR that cites FB-C soak data: new value = max(current, 2 × the largest legitimately observed value), taken from `diag_write_lock_max_ms` per boot and FB-C's own per-owner maxima. A value is never lowered below 2 × the observed maximum. A golden test pins the values. They affect telemetry only, never a write.

---

## 4. Dump `operator_needed` with register 244 = 0 (FB-C Q7)

### 4.1 Facts [MAIN, verified]
- **Trigger.** A restore verify mismatch increments `dump_verify_mismatch_count` (FW:16702); at ≥ 2 the lockout is set (FW:16703-16720). The counter is reset only at START (FW:15023), a verified restore (FW:16660), the clear-only path (FW:16849), Accept (FW:17003), and by reboot (RAM, FW:3081-3084). A comms failure does not reset it (FW:16727-16733). So the trigger is the **second mismatch since the last reset**, not "two consecutive" (the log text at FW:16720 says "consecutive"; CONTRADICTION #11). If the mismatch was on 244, the 256-261 restore is skipped (FW:16542-16545 per E05).
- **Result.** 244 holds whatever the inverter kept, possibly **0 (Allow Export)**; 256-261 hold the last controller ceiling (500-3000 W).
- **Guards.** With R=1, every lease guard and the controller are suspended (FW:18351-18355). SG-02 does not run, because it requires C (FW:17077, 18495). N and C can coexist at boot (a stale durable retry record plus an untrusted marker, or an arbitration after FW:676); then containment does run (V4 (3)).
- **Durability is best effort.** The lockout is committed to the Dump retry record (FW:16704-16706). If that commit fails, N is enforced **in RAM only** ("enforced for this runtime only", FW:16706-16711). The commit result itself can be a false negative or a false positive, because ESPHome's `sync()` aggregates every pending key and clears the queue unconditionally (PREFS `sync()`; V2 (3), V4 NEW).
- **Reboot.** N is reloaded only when the retry record durably holds `operator_needed=1`, loads, **and** the marker yields S (FW:664-676). Otherwise N is false after reboot, and the watchdog restores automatically again with a fresh mismatch count (two more attempts). Any reboot qualifies, including the ESPHome 15-min no-client API reboot during a long LOST (V3 (1)-(3)). After such a reboot the domain classifies as D8 WAIT_DUMP_RESTORE, not D7.
- **No ECCO path writes 244 while S is set,** except SG-02 under C:
  - reg244 Apply/Restore refuse (FW:13914, 14386);
  - FP START refuses (FW:6583);
  - Accept refuses while live 244 == 0 unless the live 244/256-261 set equals the original (E05 §6.6, V4 (5)).
- **Exits.** Force Restore Original (P2); an out-of-band change of 244 followed by Accept; a reboot when the lockout was not durable (fail-open for pacing only; the obligation remains and the watchdog retries); an NVS loss of the marker (ABSENT reads as CLEAR at boot; §2.5 D12 turns it into DUMP_MARKER_LOST only if the retry record survived).

### 4.2 FB-C decision and the `export_hazard` predicate [REC, LOCKED]

**One predicate for every domain.**

```
export_hazard :=
  !live_trustworthy (§7.6)                                         -> EXH_UNKNOWN
  live244 != 0                                                     -> EXH_NO
  no domain D in {DUMP, FP, R244} with C0(D) != CLEAR_PROVEN
       and kind(D) not in {ACTIVE, STARTING}                       -> EXH_NO   // a guarded running lease, or the
                                                                               // operator's own persistent Allow Export
  dump.dl && dump.snap244 == 0 && live256_261 == dump.snap256      -> EXH_NO   // SG-02's D5 exemption verbatim (FW:17135-17150)
  otherwise                                                        -> EXH_YES
```

- UNKNOWN is never reported as "no hazard". Right after a Dump restore attempt the fence makes live untrustworthy for up to ~125 s (§7.6), so the flag reads UNKNOWN exactly then.
- The predicate is the same for D1, D2, D7, D8, F-rows and G-rows. The only exemption is the one firmware already trusts (a loaded Dump original that was itself Allow Export with 256-261 unchanged). A held R244 test with live 244 = 0 is YES.

| Condition | Plan | Reason | Blocking | FB-A projection | `export_hazard` |
|---|---|---|---|---|---|
| D7 and `export_hazard == YES` | BLOCKED_OPERATOR_NEEDED | DUMP_OPERATOR_NEEDED_EXPORT_LIVE | DUMP | BLOCKED / 5 LEASE_RESTORE_LOCKED | YES |
| D7 and `export_hazard ∈ {NO, UNKNOWN}` | BLOCKED_OPERATOR_NEEDED | DUMP_OPERATOR_NEEDED | DUMP | BLOCKED / 5 | NO or UNKNOWN (reported as such, with the LIVE reason as detail) |
| D7a (Force queued) | WAIT_DUMP_RESTORE | DUMP_FORCE_QUEUED | DUMP | PREEMPT_REQUIRED / 0 | per predicate |
| D1/D2 (UNKNOWN / corrupt) | BLOCKED_RECOVERY_METADATA | DUMP_MARKER_UNREADABLE / DUMP_METADATA_CORRUPT | DUMP | BLOCKED / 5 | per predicate; K reported (K=4 is revocable, so it is computed from live 244, never assumed NO) |

- **`would_apply = 0`** in all cases. A Fallback **must never write 244 := 2 over an unresolved Dump obligation**, even though `reg244_write_permitted(0,2)` is true. Three reasons:
  - a later Dump Force or restore writes 244 := ORIGINAL, so Fallback would not be the final writer (R3);
  - the write changes the evidence the operator's Accept decision relies on (the Accept residue gate);
  - a P3 write would overlay an unresolved P1/P2 obligation (R1; brief SAFETY BOUNDARIES).
- **Telemetry.** FB-C accumulates per boot the seconds with `export_hazard == YES` (`exh_yes_s`) and with UNKNOWN (`exh_unknown_s`), and the start time of the current YES run. This is soak evidence for §4.4.
- ARCH A19 (ARCH:907@pr54) already maps this case to BLOCKED(LEASE_RESTORE_LOCKED); the decision here agrees.

### 4.3 What FB-E and FB-F must do instead [FUTURE, LOCKED requirements]
- **FB-E (operator Restore Known-Good Profile)**:
  - refuse at precheck with FB-A result 5 and wording that names the Dump domain, e.g. "Dump to Grid needs your decision first (Force or Accept)";
  - never write, never arm, never retry automatically;
  - the dashboard offers the existing Dump Force/Accept affordances, not a Fallback bypass.
- **FB-F (autonomous)**:
  - enter durable BLOCKED(LEASE_RESTORE_LOCKED) with `lease_preempted` set if a pre-emption happened;
  - raise an operator-needed alarm ("export may still be enabled" when YES; "export state unknown" when UNKNOWN);
  - never write and never set the FP one-shot (ARCH I19);
  - re-evaluate only after the Dump domain is CLEAR_PROVEN (ARCH:590@pr54);
  - **never assume the lockout survives a reboot** (§4.1): after the 15-min API reboot a non-durable lockout re-appears as an automatic restore (D8). FB-F's episode logic must re-derive from the domain classifier after every boot, not from a remembered "operator needed".

### 4.4 SG-02-style containment extension - PRODUCT DECISION (flagged, not decided here)
- **Proposal "SG-02b" [REC as an FB-D candidate].** A P0 writer of the literal 244 := 2. Trigger:
  - `S && !C && M==RR && N` (and, if the owner also chooses S6 OWN-25, the D8 comms route);
  - a fresh read shows 244 == 0;
  - not (`dl && dump_snapshot_reg244 == 0 && live 256-261 == snapshot`), SG-02's D5 exemption.
- Behaviour: once per boot with bounded retries; zero durable writes; never writes 256-261; independent of supervision; the same REFUSED / REENABLED_EXTERNALLY non-reassertion as SG-02 (FW:17274-17320, 18507-18510). It is a Dump safety action, **not a Fallback write**. FB-C would still report BLOCKED_OPERATOR_NEEDED.
- **The tension the owner must weigh (named explicitly).** §4.2 forbids a *Fallback* 244 write partly because it changes the evidence Accept relies on. SG-02b makes the same write, so the same objection applies to it:
  - after SG-02b, Accept Current State becomes usable (live 244 ∈ {1,2}) and adopts 244 = 2 as the accepted state;
  - when the original 244 was 0 (an Allow-Export policy) but 256-261 carry residue (so the D5 exemption did not apply), Accept after SG-02b loses the original export policy unless the operator re-applies it;
  - the difference from a Fallback write is authority, not effect: SG-02b is the Dump domain's own P0 (like SG-02), not a P3 overlay.
- **ARCH Q7 says "No by default … conflicts with reg244 ownership" (ARCH:997@pr54).** [INFERENCE] That objection does not hold on MAIN, because a Dump obligation and a reg244 obligation cannot coexist outside a corrupt state:
  - reg244 Apply refuses on `dump_snapshot_valid` (FW:13914);
  - Dump START refuses on `reg244_snapshot_valid` (FW:14939);
  - dual RR becomes corrupt at boot (S4, FW:815-822).
  The product owner must decide (S6 OWN-01 / OWN-25). FB-C does not depend on the outcome.

---

## 5. Permanent corrupt flags and hard lockouts (FB-C Q8)

"Permanent" means that no assignment to false exists anywhere in the firmware. Every `*_metadata_corrupt` assignment was grepped at MAIN; all 14 are `= true`: FW:334, 346, 460, 470, 587, 592, 657, 741, 746, 763, 821, 822, 910, 911. The same 14 sites exist @pr52/@pr53/@pr54 (count verified). The power-on initial value is the only way back to false, after which boot re-derives the flag from NVS (V5 (1)).

| Flag (decl) | Set sites → cause code (§8.4) | Path to false | Shadow identification | Reason code(s) | Plan / FB-A | Operator exit |
|---|---|---|---|---|---|---|
| `free_power_recovery_metadata_corrupt` (FW:1947) | 334 → MARKER_UNREADABLE; 346 → MARKER_MALFORMED; 460 → CONTEXT_FIELD_CORRUPT (plus1>3); 470 → DATA_UNTRUSTED; 910 → DUAL_FP_DUMP | **none** (boot re-derives) | F1 via `fp_lockout_cause` | FP_MARKER_UNREADABLE / FP_METADATA_CORRUPT (+cause) | BLOCKED_RECOVERY_METADATA / 5 | Out-of-band NVS handling (never "just reboot"; rule c) |
| `dump_recovery_metadata_corrupt` (FW:3012) | 587 → MARKER_UNREADABLE (K=8); 592 → MARKER_MALFORMED; 657 → DATA_UNTRUSTED (data unreadable or reg244>2); 821 → DUAL_S4; 911 → DUAL_FP_DUMP | **none**. While C is set, S cannot clear: every clear path requires `!C` (FW:16431, 16834, 16979 per E05) | D1 (UNREADABLE), D2 (corrupt) | DUMP_MARKER_UNREADABLE / DUMP_METADATA_CORRUPT (+cause, K) | BLOCKED_RECOVERY_METADATA / 5 | Out-of-band (docs/DUMP_TO_GRID_V1.md:1578-1581@main per E05) |
| `reg244_recovery_metadata_corrupt` (FW:2753) | 741 → MARKER_UNREADABLE; 746 → MARKER_MALFORMED; 763 → DATA_UNTRUSTED (data unreadable or value>2); 822 → DUAL_S4 | **none** | G1 | R244_MARKER_UNREADABLE / R244_METADATA_CORRUPT (+cause) | BLOCKED_RECOVERY_METADATA / 5 | Out-of-band |
| `dump_containment_state` (FW:3456) | 8 at FW:588; 1 at FW:936 (boot seeding) and FW:18504 (watchdog); 2/3/4/5/6 inside the script (FW:17274-17320); 7 at FW:18510 | Reset to 0 only when `!(S && C)` (FW:18495-18499), impossible while C holds. **Absorbing for the boot: 2, 6, 7, 8. Revocable: 4 (→7). Re-run: 1, 5. Transient: 3.** CONTRADICTION #8 with the comment FW:3451-3455 | D1/D2 detail K | same as above, plus detail K | same | reboot re-arms (K 1) unless K=8 |
| (not a flag) `reg244_last_applied_valid/value` (FW:2784-2791, `restore_value: yes`) | a verified Apply or Restore (FW:14197-14198, 14650-14651) | yes (many `=false` sites; E04 §5.1). Survives reboots | G6 detail: `LAV && live244 != LA` | R244_HELD_DRIFT_GUARD | BLOCKED_OPERATOR_NEEDED / 5 | Put 244 back to LA externally, then Restore (a dead end otherwise, N11) |
| (not permanent) `free_power_operator_needed` (FW:1979) | lockouts (FW:8742-8830, 9030, 10722) | yes (End/Force/Accept/START) | F6 when `SV && MS==RR`; F11.h when the marker is absent (FP_MARKER_LOST); else flag `fp_stale_operator_needed` | FP_OPERATOR_NEEDED / FP_MARKER_LOST | BLOCKED_OPERATOR_NEEDED / 5, or BLOCKED_DURABLE_UNKNOWN / 6 | P2 |
| (not permanent) `dump_operator_needed` (FW:3020) | second verify mismatch (§4.1) | yes (Force / Accept / restore success; **also any reboot if the lockout commit did not land**) | D7; D12 via `dump_retry_boot_on_raw` | DUMP_OPERATOR_NEEDED[_EXPORT_LIVE] / DUMP_MARKER_LOST | BLOCKED_OPERATOR_NEEDED / 5, or BLOCKED / 6 | P2 (§4) |

**Rules [REC, LOCKED]:**
- **(a)** No FB-B, FB-C, FB-E or FB-F code path ever writes, clears or commits over any lease record while its domain is not CLEAR_PROVEN. Pinned test: no new `commit_record` of any FP/Dump/reg244 tag, and no assignment of any `*_metadata_corrupt`, outside the existing sites. (FB-D's absence provisioning, §2.10, would need its own reviewed exception.)
- **(b)** FB-C reports latched lockouts (L3) separately from runtime/cross-record doubt (L4) and from absence (L6), so the HA contract never presents a permanent lockout as transient.
- **(c) Reboot advice is fail-open (staged once: before FB-B1).** Boot turns a data-CRC READ_ERROR marker into ABSENT on the next boot (NVS init erases the orphaned index; V1 (4)). The existing status texts "… - reboot to re-read" at FW:680 (Dump), FW:947 (FP) and FW:1030 (reg244) therefore advise the one action that converts UNKNOWN into CLEAR. Because FB-B capture accepts CLEAR-by-absence (C6), "reboot as advised, then capture" is a laundering path. The texts must change **before FB-B1 merges** to "do NOT reboot; a reboot may make the record read as absent; record the state and repair out-of-band". FB-C's own wording never advises a reboot (§3.6). This is the only staging of this fix.
- **(d)** The lockout cause is retained in RAM (§2.1), so no plan or reason depends on parsing status text (S6 BLK-63 principle).

---

## 6. Profile states → shadow decision (FB-C Q9)

### 6.1 Classes [PR54 + REC, LOCKED]

The source is FB-A `classify_profile` (FBH:559-574@pr54): precedence load → magic → schema → size → binding → reserved → flags → generation → domain → INVALIDATED → VALID. ABSENT is the only route to NOT_CAPTURED; WRONG_SIZE → CORRUPT; any other non-OK load → UNREADABLE. PROFILE_LOST and SAVE_UNCONFIRMED are FB-B RAM views (charter C0).

| Class | Meaning (who produces it) | FB-C plan (LOST branch, all temporary domains clear) | Reason | FB-A projection | Readiness wording hint (HA section decides) |
|---|---|---|---|---|---|
| NOT_CAPTURED, **proven** | load ABSENT **and** FB-B's witness is present, valid, with high-water generation 0 (`not_captured_proven`) | BLOCKED_NO_PROFILE | PROFILE_NOT_CAPTURED | LATCHED_COMPLETE / 2 PREEMPTED_NO_PROFILE | Not Captured |
| NOT_CAPTURED, **unproven** | load ABSENT with no witness adopted, or a witness that is absent/unreadable | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_ABSENT_UNPROVEN | BLOCKED / 7 PROFILE_UNAVAILABLE | Not Captured (detail: "cannot prove none was saved") |
| VALID | no defect, flag clear | continue to L21-L26 | — | 3 or 4, or blocked 8/9/10 | Ready / Drifted |
| INVALIDATED | authentic record with flag bit0 (FBH:569-570) | BLOCKED_PROFILE_INVALIDATED | PROFILE_INVALIDATED | LATCHED_COMPLETE / 2 | Invalidated |
| CORRUPT | structural defect or WRONG_SIZE; **generation untrusted** | BLOCKED_PROFILE_CORRUPT | PROFILE_CORRUPT (+ `profile_defect` 1-7 as detail) | BLOCKED / 7 | Blocked (profile damaged) |
| CORRUPT_DOMAIN | authentic, E1 out of V1 domain (binding must match first, V8 (1)) | BLOCKED_PROFILE_CORRUPT | PROFILE_CORRUPT_DOMAIN | BLOCKED / 7 | Blocked (profile damaged) |
| UNREADABLE | READ_ERROR / STORAGE_UNAVAILABLE / unknown load | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_UNREADABLE | BLOCKED / 7 | Blocked (storage) |
| PROFILE_LOST | ABSENT while the FB-B witness expects generation ≥ 1 (only if FB-B adopts C3) | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_LOST | BLOCKED / 7 | Blocked (profile lost) |
| SAVE_UNCONFIRMED | FB-B durable outcome UNKNOWN this boot (C2). RAM keeps the prior mirror | BLOCKED_PROFILE_UNAVAILABLE (**even if the prior mirror is VALID**) | PROFILE_SAVE_UNCONFIRMED | BLOCKED / 7 | Blocked (save unconfirmed) |
| (episode) profile changed since LOST | §6.2 | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_CHANGED_SINCE_LOST | BLOCKED / 7 | — |

**CONTRADICTION #9 (explicit).** ARCH §6.3 row 12 (ARCH:533@pr54) allows PREEMPTED_NO_PROFILE "**only** when proven NOT CAPTURED or INVALIDATED", and requires BLOCKED(PROFILE_LOST/CORRUPT) when a profile was expected but is not VALID. FB-A's `classify_profile` maps every ABSENT to NOT_CAPTURED, and NVS turns corruption into ABSENT (V1 (1)-(4); E03 §1). ABSENT alone is therefore **not** proof. **LOCKED:** both witness branches as in the table. If S2 does not adopt a witness, or adopts one that has no "present with generation 0" state, NOT_CAPTURED is never proven and every no-profile episode projects BLOCKED/7. Either way nothing is written; only the terminal state differs (LATCHED/2 closes quietly, BLOCKED/7 asks for attention).

- **Temporary obligations take precedence over the profile class.** A LOST with an active lease and no profile is `WOULD_PREEMPT_*` with `projected_after` = the no-profile plan. This reflects ARCH: leases are pre-empted irrespective of profile availability.
- **Capture candidates.** A candidate in RAM (FB-B) is never an input to FB-C. Only the committed, reloaded mirror is.

### 6.2 Episode binding [REC, LOCKED]
- **Record.** At S3's transition E1 (LOST edge opens an episode), FB-C records `ep_prof = {bound = true, cls = fbp.cls, gen = meaningful ? rec.generation : 0, binding = meaningful ? rec.binding : 0}`, with `meaningful := cls ∈ {VALID, INVALIDATED, CORRUPT_DOMAIN}`. A re-loss inside the same episode (S3 E3/E5) does not re-bind.
- **Test (L12).** Any difference in class, or in generation/binding for a meaningful class, gives PROFILE_CHANGED_SINCE_LOST. This covers the case a plain "binding 0 = none" sentinel misses: an episode opened with NOT_CAPTURED or UNREADABLE, HA returns (HA_BACK; the episode stays open), and the operator captures. The bound class 1 differs from the current class 5, so the plan is BLOCKED/7, never WOULD_APPLY_PROFILE.
- **Why a struct, not "binding 0 = none".** 0 would mean both "no episode" and "episode with no profile". FB-A's durable record does use `profile_generation == 0 ⇔ profile_binding == 0` for "no profile bound" (FBH:645@pr54). That is sound for FB-F only because FB-F-era capture is gated (next bullet), which is not true in the FB-B/FB-C era.
- **Capture during an episode.** FB-B SAVE and INVALIDATE are **not** refused because a *shadow* episode is open: a shadow episode must never gate runtime behaviour (R4; S3 pin Z5). In the FB-F era the gate is FB-B's FBS slot (S1 §4.3), which refuses capture and invalidation while a durable FailbackStateV1 is not CLEAR. **CONTRADICTION #10:** ARCH A28 (ARCH:916@pr54) says re-capture during an episode is "Impossible (capture is gated)". That holds only from FB-F onward; in the FB-B/FB-C era FB-C handles it through L12.
- **Survival.** The binding is RAM, per boot, like the whole S3 episode. After an ESP reboot (including the 15-min API reboot) the episode is gone; if supervision is still absent, a new episode opens at 300 s uptime (S3 trigger S) and binds afresh (row 76).

### 6.3 FBP durable leg at LOST [REC, LOCKED]
FB-C does not re-read the profile at the LOST edge (it reads no NVS). FB-B's RAM mirror is authoritative for the shadow episode. FB-F must re-read the profile freshly at APPLY_PRECHECK and compare generation/binding with its durable record (ARCH rows 12-13, `ARCH:533-534@pr54`).

---

## 7. Drift, context and live-data rules (FB-C Q10)

### 7.1 E1 (drives apply) [PR54 classes; REC compare rules, LOCKED]

| Register | Compare | Delta ⇒ | Notes |
|---|---|---|---|
| 244 | `live == 2` matches. `live == 0` is a delta (F244). `live == 1` or `> 2` → out of domain (§7.4) | WOULD_APPLY (only 0→2) | `reg244_write_permitted(live,2)` true only for live 0 (FBH:176-178); FROM domain {0,2} (FBH:175) |
| 256-261 | exact word | WOULD_APPLY (F256_DOWN / F256_UP) | domain 500..8000 (FBH:163-168) |
| 268-273 | exact word | WOULD_APPLY (F268_279) | domain ≤ 100 |
| 274-279 | **full word** (not the 0x0003 mask) | WOULD_APPLY (F268_279) | Answers E01 open question 5. A live 0x0005 matches profile 0x0001 under the mask, but it is out of domain and cannot be converged without writing mode bits outside the E1 mask 0x0003 (FBH:124-136). Full-word equality is the only honest "already at profile" |

- **WOULD_APPLY_PROFILE carries a delta list.** `e1_delta_mask` plus from→to values. [REC] The compact encoding, owned by the HA section, is `d=244:0>2,256:3000>8000,…` capped at 200 chars, with a `+N` suffix when truncated.
- **Manual TOU changes after capture** show as E1 deltas (powers, SOCs, source bits) or CTX mismatches (slot times, 232 bit0). The profile is **never** updated (C1). This matches ARCH Q9, "mark stale; do not suppress" (ARCH:999@pr54).

### 7.2 CTX (blocks, never written) [PR54 masks; REC per-register semantics, LOCKED]

The comparison uses FB-A `ctx_matches(addr, profile, live)` (FBH:140-143@pr54) exactly.

| Register | Compared bits | Mismatch ⇒ | Reason | Why it blocks |
|---|---|---|---|---|
| 250-255 | full word, each register independently. Any change, including a ring rotation or a midnight-wrap move, is a mismatch. No tolerance, no ring re-normalisation | BLOCKED_CONTEXT_MISMATCH | CTX_SLOT_TIMES (bits 3-8) | E1 per-slot values only mean what they meant at capture if the slot boundaries are identical. An invalid or unordered live ring is still just a mismatch (the ring rule is FB-B's capture-time job) |
| 243 | full word | BLOCKED_CONTEXT_MISMATCH | CTX_243 | Battery-first vs load-first changes TOU semantics (E09 §3.4; semantics unproven) |
| 232 | bit 0 (mask 0x0001, FBH:122) | BLOCKED_CONTEXT_MISMATCH | CTX_232_BIT0 | The global grid-charge enable decides whether the source bits do anything (ARCH:323@pr54 per E09) |
| 232 bits 1-15 | — | INFO only | info bit3 | undecoded |
| 248 | bit 0 (FBH:123) | BLOCKED_CONTEXT_MISMATCH | CTX_248_BIT0 | TOU master enable. Differs from the FP context gate, which excludes 248 (E09 §3.8); blocking is fail-safe (zero writes) |
| 248 bits 1-15 | — | INFO only | info bit4 | |

More than one category mismatching → reason CTX_MULTIPLE; the mask carries the detail.

### 7.3 INFO (report only, never block) [PR54]
- 230, 245, 247 differ → `info_mismatch_mask` bits 0-2, published as detail only.
- 245 is **never** presented as export-limit or compliance evidence (E09 §3.6).
- 230 is never written in V1 (FBH:99-100), so a changed grid-charge current is not corrected by Fallback. The wording must say so.

### 7.4 Live outside the V1 domain → BLOCKED_LIVE_OUT_OF_DOMAIN (FB-A 9) [REC, LOCKED]

`out_of_domain_mask` bit i is set when the live E1 value would fail `failback_from_domain_valid` (FBH:623-632@pr54):

| Register | Out of domain when | Reason |
|---|---|---|
| 244 | `live ∉ {0,2}`: 1 → Essentials; > 2 → unrecognised | LIVE_244_ESSENTIALS / LIVE_244_UNRECOGNISED |
| 256-261 | outside 500..8000 (Manual TOU permits 0..8000, FW:11445) | LIVE_POWER_OUT_OF_RANGE |
| 268-273 | > 100 | LIVE_SOC_OUT_OF_RANGE |
| 274-279 | word ∉ {0,1}: generator source 2/3, any mode bit 0x04/0x08/0x10, any bit 5-15 | LIVE_SOURCE_WORD_UNSUPPORTED |

- Two or more categories → reason LIVE_MULTIPLE_OUT_OF_DOMAIN.
- **Live 244 = 1 verified [PR54].** `reg244_write_permitted(1,2) == false` (FBH:176-178, static_assert FBH:867-870); `from_244_domain_valid(1) == false` (FBH:175); the header states "a live 244 = 1 is unsupported and must block" (FBH:148-150).
- **CONTRADICTION #1 [DOC vs PR54].** ARCH A9 says "BLOCKED(CONTEXT_244)" (ARCH:897@pr54). FB-A has no CONTEXT_244 code, and 244 is E1, not CTX. **LOCKED: LIVE_OUT_OF_DOMAIN (9).**

### 7.5 Site ceiling lower than the profile → BLOCKED_SITE_CEILING (FB-A 10) [REC, LOCKED]
- **Representation.** Input `site_tou_ceiling_w` = `${ecco_inverter_tou_power_ceiling_w}` (FW:13) = 8000 = `V1_TOU_POWER_MAX_W` (FBH:164). The check is `any(profile256[i] > site_tou_ceiling_w)`.
- **Today it is unreachable.** No dongle-side site limit below 8000 exists (E09 §7.2). The HA operating limit is not a safety primitive and is not visible to the dongle. [REC] Add `static_assert(site ≥ V1 min)` and a test asserting unreachability with the current substitution; golden vectors exercise the row with a synthetic lower ceiling.
- A future runtime dongle-side limit (FB-D/FB-E) feeds the same input. It must never make a stored profile CORRUPT_DOMAIN (FBH:151-157).

### 7.6 Live trustworthiness → WAIT_LIVE_DATA (never assume a match) [REC, LOCKED]

**Latch (torn-snapshot protection).** Block A (200-240: 230, 232) and Block B (241-293: 243-279) of one poll are 2.5 s apart (FW:13518, `delay: 2500ms`; Block B dispatch stamp FW:13523). A tick between them would pair Block A of poll n+1 with Block B of poll n. FB-C therefore copies the 31 profile-relevant raw cache words into `failback_shadow_live_regs` only on the first FB-C tick after `cfg_block_b_seq` (incremented at Block B success, FW:13720) changes. It records `live_latched_seq`, `live_latched_dispatch_seq` (= `cfg_block_b_response_dispatch_seq`, FW:13725) and `live_latched_valid` (= `manual_config_raw_cache_valid`, set to `configuration_block1_ok` at Block B success, FW:13714). The next Block A arrives about 55 s later, so the latched pair is always from one poll. All live-derived outputs (masks, `live244`, frames, `export_hazard`) use the latched copy.

**Fence.** On every FB-C tick where `manual_write_in_progress` is held or any §2.9 owner is running, and on every temporary-domain obligation→clear edge, FB-C sets `live_fence_seq := cfg_block_b_dispatch_seq + 2`. The value only grows, because the dispatch counter only grows. The +2 is required because Block A of a poll already in flight at the fence moment is pre-fence (PR53's technique, FW:1625-1631@pr53). **Worst-case blind window ≈ 125 s:** the fence can land just after a Block B dispatch, and the config poll runs every 60 s (FW:18548), so the first acceptable Block B response comes two polls later (~120 s + 2.5 s + reply). The best case is ~60 s. Residual [INFERENCE]: a writer whose whole MWIP hold falls between two 1 s FB-C samples is missed. Every E1/CTX writer path sends several Modbus frames, each preceded by the 600 ms turnaround (V6 (6)), so this needs a loop stall; the consequence is at most one poll of stale shadow comparison, never a write. The FB-E/FB-F engines use fresh reads, not the cache.

`live_trustworthy` requires every term below (the first failing term gives the reason):

| Term | Source | Failing reason |
|---|---|---|
| a latch exists | FB-C2 latch | LIVE_NOT_LATCHED |
| `cache_state != 'O'` | `configuration_polling` FW:4050 | LIVE_POLLING_OFF |
| `cache_state != 'I'` and `live_latched_valid` | FW:1361, FW:4315 | LIVE_CACHE_INVALID |
| `cache_state != 'S'` | `cfg_block_b_seq != 0` (FW:3120), `now - cfg_block_b_ok_ms ≤ 180000` (FW:3124; S3 substitution) | LIVE_CACHE_STALE |
| `live_latched_dispatch_seq >= live_fence_seq` | FW:3145 vs the fence | LIVE_CACHE_PRE_FENCE |

- A diverted poll reply (MAIN has no `on_custom_response`; E06 D3, V6 (4)) does not advance `cfg_block_b_seq` or `cfg_block_b_ok_ms`, so it ages into LIVE_CACHE_STALE.
- A stuck MWIP also stops the config poll entirely (its interval requires `!manual_write_in_progress`, FW:18548-18557), which ages into STALE while B1 reports the lock.
- WAIT_LIVE_DATA describes the shadow's own blindness and projects to the non-terminal PREEMPT_REQUIRED / NONE.

---

## 8. Plan code set (FB-C Q11)

### 8.1 Codes [REC, LOCKED - numeric values frozen from FB-C2 onward, never reused]

**21 emitted codes plus 1 reserved** (0, 1, 2, 10-15, 20-27, 30, 31, 40, 41 emitted; 16 reserved). The FB-A projection column gives (FailbackState / FailbackResult) per FBH:260-291@pr54; every pair is legal under `failback_invariants_hold` (FBH:642-669). "RAM-only" means no failback record would exist.

Every wording is ≤ 60 characters and was checked case-insensitively against the card patterns:
- `RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED` (FE `dumpState.ts:57`, `freePowerState.ts:45`);
- `DEFERRED` (`:58`/`:46`);
- `^(RESTORING|STARTING|ACTIVATION VERIFY)` (`:59`/`:47`);
- `inverter writes? (are |is )?locked|deliberate recovery required` (`recoveryPresentation.ts:41`);
- `^BLOCKED` (`schedule.ts:51`, scoped to the schedule's last result, but avoided anyway).

No wording matches any of them.

| # | Code | Meaning | Emitted by | FB-A projection (Policy B) | Operator wording (≤ 60 chars) |
|---|---|---|---|---|---|
| 0 | NOT_EVALUATED | No valid evaluation | E0/E1 | RAM-only | Shadow evaluator not ready yet |
| 1 | NO_ACTION | Supervised and stable, no episode | S1 | RAM-only | No action: supervision healthy |
| 2 | WOULD_REFUSE_STARTS | FB-D would refuse new managed starts | S2 | RAM-only | Would refuse new managed starts |
| 10 | WOULD_PREEMPT_DUMP | Would request the Dump lease end | L1 | PREEMPT_REQUIRED / 0, `lease_preempted` | Would end Dump to Grid, then continue failback |
| 11 | WOULD_PREEMPT_FREE_POWER | Would request the FP lease end (needs the FB-D neutral primitive, N4) | L2 | PREEMPT_REQUIRED / 0, `lease_preempted` | Would end Free Power, then continue failback |
| 12 | WAIT_DUMP_RESTORE | Dump's own restore, clear or queued Force is due or running | L8 | PREEMPT_REQUIRED / 0 | Would wait for Dump to Grid to put settings back |
| 13 | WAIT_FREE_POWER_RESTORE | FP's own restore, clear, Force or Accept is due or running | L9 | PREEMPT_REQUIRED / 0 | Would wait for Free Power to put settings back |
| 14 | WAIT_WRITE_IN_FLIGHT | Another transaction (incl. an operator reg244 Apply/Restore) holds the bus or a flag, or a lock is stuck | L7, L10 | PREEMPT_REQUIRED / 0 | Would wait: another inverter write is running |
| 15 | WAIT_LIVE_DATA | Live data not trustworthy (shadow cache) | L22 | PREEMPT_REQUIRED / 0 (non-terminal; the engine would re-read) | Would wait: live inverter settings not current |
| 16 | WAIT_MANUAL_TOU_RECOVERY | **Reserved** [FUTURE MTOU_JOURNAL]; never emitted by FB-C2 | (L11) | PREEMPT_REQUIRED / 0 | Would wait for Manual TOU recovery to finish |
| 20 | BLOCKED_RECOVERY_METADATA | A lease domain has a latched corrupt/unknown lockout | L3 | BLOCKED / 5 LEASE_RESTORE_LOCKED | Would hold: saved lease records unreadable or corrupt |
| 21 | BLOCKED_DURABLE_UNKNOWN | Durable lease state not positively clear: divergence, vanished/lost marker, latched probe finding, or absence without a witness | L4, L6 | BLOCKED / 6 MARKER_DIVERGENCE | Would hold: saved lease state not confirmed |
| 22 | BLOCKED_OPERATOR_NEEDED | A lease needs an operator exit (FP/Dump ON, R244 held/PC) | L5 | BLOCKED / 5 LEASE_RESTORE_LOCKED | Would hold: a lease needs your decision first |
| 23 | BLOCKED_PROFILE_CORRUPT | Profile CORRUPT or CORRUPT_DOMAIN | L16-L17 | BLOCKED / 7 PROFILE_UNAVAILABLE | Would hold: saved profile is damaged |
| 24 | BLOCKED_PROFILE_UNAVAILABLE | Profile UNREADABLE / LOST / SAVE_UNCONFIRMED / changed since LOST / absent but unproven | L12-L15, L18 | BLOCKED / 7 | Would hold: saved profile cannot be confirmed now |
| 25 | BLOCKED_SITE_CEILING | Profile power above the site ceiling (unreachable today) | L21 | BLOCKED / 10 SITE_CEILING | Would hold: profile power above site limit |
| 26 | BLOCKED_CONTEXT_MISMATCH | CTX differs from the profile | L23 | BLOCKED / 8 CONTEXT_MISMATCH | Would hold: schedule or context changed since save |
| 27 | BLOCKED_LIVE_OUT_OF_DOMAIN | Live E1 not representable as FROM | L24 | BLOCKED / 9 LIVE_OUT_OF_DOMAIN | Would hold: live settings outside profile range |
| 30 | BLOCKED_NO_PROFILE | No profile captured (proven) | L19 | LATCHED_COMPLETE / 2 PREEMPTED_NO_PROFILE | No failback possible: no known-good profile saved |
| 31 | BLOCKED_PROFILE_INVALIDATED | Profile invalidated | L20 | LATCHED_COMPLETE / 2 | No failback possible: profile was invalidated |
| 40 | WOULD_ALREADY_MATCH | E1 and CTX already equal the profile | L25 | LATCHED_COMPLETE / 3 ALREADY_AT_PROFILE | Would do nothing: inverter already matches profile |
| 41 | WOULD_APPLY_PROFILE | E1 differs, all gates pass | L26 | (APPLY_IN_PROGRESS →) LATCHED_COMPLETE / 4 APPLIED_VERIFIED (projected success; the real engine may end at 11) | Would apply known-good profile (N registers) |

**FB-A results FB-C never projects as the Policy-B result:** 1 PREEMPTED_ONLY (it appears only in `fba_result_policy_a`, §3.5) and 11 APPLY_FAILED (requires real writes).

**BLOCKED/6 and FB-F's divergence reboot.** ARCH row 10 (ARCH:531) answers MARKER_DIVERGENCE with one quiescent reboot so on_boot adopts the marker. [LOCKED requirement for FB-F] That reboot applies only to reason `*_MARKER_DIVERGED` (RR/PC found under a clear RAM mirror). It never applies to `*_MARKER_ABSENT_UNPROVEN`, `*_MARKER_LOST`, `*_MARKER_EVIDENCE_VANISHED` or `*_PROBE_*`: a reboot cannot restore an absent record, and for a latched READ_ERROR it would complete the laundering to ABSENT (§5 rule c).

### 8.2 Merges and trims relative to the brief's list (justified)
- **Pre-emption codes.** WOULD_PREEMPT_FREE_POWER_THEN_APPLY / WOULD_PREEMPT_DUMP_THEN_APPLY become WOULD_PREEMPT_FREE_POWER / WOULD_PREEMPT_DUMP plus `projected_after`. What follows a pre-emption depends on the lease's restore result, which changes live E1. "THEN_APPLY" would claim a projection that is only best effort, and would multiply the code count (THEN_APPLY / THEN_MATCH / THEN_BLOCKED_x).
- **Profile codes.** BLOCKED_PROFILE_UNREADABLE is renamed BLOCKED_PROFILE_UNAVAILABLE and widened to LOST / SAVE_UNCONFIRMED / CHANGED / ABSENT_UNPROVEN. It then matches the FB-A 7 name; PROFILE_UNREADABLE survives as a reason.
- **Context code.** The brief's BLOCKED_CONTEXT_DRIFT becomes BLOCKED_CONTEXT_MISMATCH (the FB-A 8 name). "Drift" stays a dashboard word for readiness, not a plan code.
- **Waits.** The operator-started reg244 restore is an in-flight write like any other, so it is WAIT_WRITE_IN_FLIGHT with reason R244_RESTORE_RUNNING (no separate code). A shadow cache problem is a wait, so it is named WAIT_LIVE_DATA, not BLOCKED_*.
- **New codes.** NOT_EVALUATED, WAIT_WRITE_IN_FLIGHT, WAIT_LIVE_DATA, BLOCKED_OPERATOR_NEEDED (distinct from metadata: the operator exits differ). Reserved: WAIT_MANUAL_TOU_RECOVERY.

### 8.3 Reason codes [REC; RAM-only, numeric, extensible - new values appended only]

| Range | Codes |
|---|---|
| General | 1 SUP_STABLE, 2 SUP_STARTUP, 3 SUP_SUSPECT, 4 SUP_UNSTABLE, 5 SUP_LOST, 6 SUP_RETURNED_EPISODE_OPEN, 7 IF_LOST_READINESS, 10 BOOT_NOT_LOADED, 11 INPUT_INVALID |
| DUMP | 101 DUMP_ACTIVE, 102 DUMP_STARTING, 103 DUMP_RESTORE_DUE, 104 DUMP_RESTORE_BACKOFF, 105 DUMP_RESTORE_RUNNING, 106 DUMP_CLEAR_PENDING, 107 DUMP_OPERATOR_NEEDED, 108 DUMP_OPERATOR_NEEDED_EXPORT_LIVE, 109 DUMP_FORCE_QUEUED, 110 DUMP_METADATA_CORRUPT, 111 DUMP_MARKER_UNREADABLE, 112 DUMP_MARKER_DIVERGED, 113 DUMP_PROBE_UNREADABLE, 114 DUMP_PROBE_MALFORMED, 115 DUMP_MARKER_EVIDENCE_VANISHED, 116 DUMP_MARKER_LOST, 117 DUMP_MARKER_ABSENT_UNPROVEN, 118 DUMP_RAM_INCONSISTENT, 119 DUMP_OP_FLAG_STUCK, 120 DUMP_OP_FLAG_SETTLING |
| FP | 201 FP_ACTIVE, 202 FP_STARTING, 203 FP_RESTORE_DUE, 204 FP_RESTORE_BACKOFF, 205 FP_RESTORE_RUNNING, 206 FP_OPERATOR_ACTION_RUNNING, 207 FP_CLEAR_PENDING, 208 FP_OPERATOR_NEEDED, 210 FP_METADATA_CORRUPT, 211 FP_MARKER_UNREADABLE, 212 FP_MARKER_DIVERGED, 213 FP_PROBE_UNREADABLE, 214 FP_PROBE_MALFORMED, 215 FP_MARKER_EVIDENCE_VANISHED, 216 FP_MARKER_LOST, 217 FP_MARKER_ABSENT_UNPROVEN, 218 FP_RAM_INCONSISTENT, 219 FP_OP_FLAG_STUCK, 220 FP_OP_FLAG_SETTLING |
| R244 | 301 R244_HELD, 302 R244_HELD_DRIFT_GUARD, 303 R244_CLEAR_PENDING_OPERATOR, 304 R244_APPLY_RUNNING, 305 R244_RESTORE_RUNNING, 307 R244_METADATA_CORRUPT, 308 R244_MARKER_UNREADABLE, 309 R244_MARKER_DIVERGED, 310 R244_PROBE_UNREADABLE, 311 R244_PROBE_MALFORMED, 312 R244_MARKER_EVIDENCE_VANISHED, 313 R244_RAM_INCONSISTENT, 314 R244_OP_FLAG_STUCK, 315 R244_MARKER_ABSENT_UNPROVEN, 316 R244_OP_FLAG_SETTLING |
| BUS/MTOU | 401 MTOU_APPLY_RUNNING, 402 FBB_CAPTURE_RUNNING, 403 RTC_CORRECTION_RUNNING, 404 LOCK_HELD_OWNER_RUNNING, 405 LOCK_HELD_NO_KNOWN_OWNER, 406 RTC_LOCK_STUCK, 407 LOCK_HELD_SETTLING, 410 MTOU_JOURNAL_OBLIGATION (reserved) |
| FBP | 501 PROFILE_NOT_CAPTURED, 502 PROFILE_INVALIDATED, 503 PROFILE_CORRUPT, 504 PROFILE_CORRUPT_DOMAIN, 505 PROFILE_UNREADABLE, 506 PROFILE_LOST, 507 PROFILE_SAVE_UNCONFIRMED, 508 PROFILE_CHANGED_SINCE_LOST, 509 PROFILE_ABSENT_UNPROVEN |
| Site/live/CTX | 601 SITE_CEILING_BELOW_PROFILE; 610 LIVE_CACHE_INVALID, 611 LIVE_CACHE_STALE, 612 LIVE_POLLING_OFF, 613 LIVE_CACHE_PRE_FENCE, 614 LIVE_NOT_LATCHED; 620 CTX_SLOT_TIMES, 621 CTX_243, 622 CTX_232_BIT0, 623 CTX_248_BIT0, 624 CTX_MULTIPLE; 630 LIVE_244_ESSENTIALS, 631 LIVE_244_UNRECOGNISED, 632 LIVE_POWER_OUT_OF_RANGE, 633 LIVE_SOC_OUT_OF_RANGE, 634 LIVE_SOURCE_WORD_UNSUPPORTED, 635 LIVE_MULTIPLE_OUT_OF_DOMAIN |
| Outcome | 701 MATCH_E1_AND_CTX, 702 E1_DELTA |

(209 and 306 are intentionally unused: the earlier `*_METADATA_LOCKOUT` reasons were withdrawn because the cause is now retained.)

### 8.4 Detail codes [REC, LOCKED]
- **Cause** (`*_lockout_cause`, `dom_detail` low nibble for L3): 0 NONE, 1 MARKER_UNREADABLE, 2 MARKER_MALFORMED, 3 DATA_UNTRUSTED (data record unreadable or invalid; the bare-bool data load cannot tell which), 4 CONTEXT_FIELD_CORRUPT (FP plus1>3), 5 DUAL_S4, 6 DUAL_FP_DUMP.
- **Containment K** (`dom_detail` high nibble for DUMP): the firmware values 0-8 unchanged, with the semantics of §5.
- **Durable leg per domain** (published by the HA section): `B` boot evidence, `R` runtime clear commit, `L` latched FB-B finding, `P` probe (never produced by FB-C).

---

## 9. Shadow decision table (FB-C deliverable i)

**Legend.**
- Columns: Sup = supervision (SUP+ = stable; SUP- = SUPERVISED without stable; EP = episode open); Pre = would_preempt (FP/D); App = would_apply; Writes = projected frames; FB-A = projected Policy-B state/result.
- Domain states: `-` = CLEAR_PROVEN with **marker** evidence (MARKER_CLEAR_BOOT or _RUNTIME); Cabs = CLEAR by absence (boot ABSENT, unused); A = ACTIVE; St = STARTING; RR = restore due; BO = backoff; EN = ENDING; PC = pending clear; ON = operator needed; MC = latched corrupt; UK = latched unreadable; IF = in flight; LK = lock stuck.
- Live is relative to a VALID profile unless noted. "match" means E1 and CTX equal. EXH = `export_hazard`.
- **Policy A (not a column):** for every row whose plan comes from L12-L26, `fba_result_policy_a` = LATCHED/1; for every other row it equals the FB-A column.
- `alt` = `alt_plan_absence_accepted`, shown only where it differs from the plan.

| # | Sup | DUMP | FP | R244 | MTOU/BUS | FBP | Live | Plan | Reason | Block | Pre | App | Writes | FB-A | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | SUP+ | - | - | - | - | VALID | match | NO_ACTION | SUP_STABLE | — | — | 0 | — | RAM | Readiness (IF_LOST) = WOULD_ALREADY_MATCH ("Ready") |
| 2 | SUP+ | - | A | - | - | VALID | overlay | NO_ACTION | SUP_STABLE | — | — | 0 | — | RAM | Readiness = WOULD_PREEMPT_FREE_POWER; projected_after from the FP snapshot |
| 3 | SUP+ | - | - | - | - | NOT_CAPTURED | — | NO_ACTION | SUP_STABLE | — | — | 0 | — | RAM | Readiness = BLOCKED_NO_PROFILE if proven, else BLOCKED_PROFILE_UNAVAILABLE (PROFILE_ABSENT_UNPROVEN); both shown "Not Captured" |
| 4 | STARTUP (<300 s) | - | RR (boot AP→RQ) | - | - | VALID | — | WOULD_REFUSE_STARTS | SUP_STARTUP | SUPERVISION | — | 0 | — | RAM | The FP watchdog restores on its own (P1); FB-C does nothing |
| 5 | SUP- | - | - | - | - | VALID | match | WOULD_REFUSE_STARTS | SUP_UNSTABLE | SUPERVISION | — | 0 | — | RAM | Stable needs 3 beats / ≤45 s gaps / ≥55 s span (E07) |
| 6 | SUSPECT | - | - | - | - | VALID | match | WOULD_REFUSE_STARTS | SUP_SUSPECT | SUPERVISION | — | 0 | — | RAM | N5: not enforced today |
| 7 | SUSPECT | - | A | - | - | VALID | overlay | WOULD_REFUSE_STARTS | SUP_SUSPECT | SUPERVISION | — | 0 | — | RAM | The lease continues; no pre-emption before LOST |
| 8 | LOST | - | - | - | - | VALID | match | WOULD_ALREADY_MATCH | MATCH_E1_AND_CTX | — | — | 0 | none | LATCHED/3 | `durable_leg_projected=1` |
| 9 | LOST | - | - | - | - | VALID | 256 = 3000 vs 8000 | WOULD_APPLY_PROFILE | E1_DELTA | — | — | 1 | F256_UP | LATCHED/4 | delta `256:3000>8000` |
| 10 | LOST | - | - | - | - | VALID | 244 = 0, rest match | WOULD_APPLY_PROFILE | E1_DELTA | — | — | 1 | F244 | LATCHED/4 | the only permitted 244 write, 0→2. EXH NO (no domain open) |
| 11 | LOST | - | - | - | - | VALID | 268/274 differ | WOULD_APPLY_PROFILE | E1_DELTA | — | — | 1 | F268_279 | LATCHED/4 | one 12-register frame |
| 12 | LOST | - | - | - | - | VALID | 244 = 1 | BLOCKED_LIVE_OUT_OF_DOMAIN | LIVE_244_ESSENTIALS | LIVE | — | 0 | none | BLOCKED/9 | CONTRADICTION #1 (ARCH A9) |
| 13 | LOST | - | - | - | - | VALID | 274 = 0x0005 (mode General) | BLOCKED_LIVE_OUT_OF_DOMAIN | LIVE_SOURCE_WORD_UNSUPPORTED | LIVE | — | 0 | none | BLOCKED/9 | Manual TOU can create this (FW:11458-11468) |
| 14 | LOST | - | - | - | - | VALID | 256 = 300 W | BLOCKED_LIVE_OUT_OF_DOMAIN | LIVE_POWER_OUT_OF_RANGE | LIVE | — | 0 | none | BLOCKED/9 | |
| 15 | LOST | - | - | - | - | VALID | 254 slot time edited | BLOCKED_CONTEXT_MISMATCH | CTX_SLOT_TIMES | LIVE | — | 0 | none | BLOCKED/8 | E1 delta also reported |
| 16 | LOST | - | - | - | - | VALID | 232 bit0 toggled | BLOCKED_CONTEXT_MISMATCH | CTX_232_BIT0 | LIVE | — | 0 | none | BLOCKED/8 | |
| 17 | LOST | - | - | - | - | VALID | 232 bits 1-15 differ only | WOULD_ALREADY_MATCH | MATCH_E1_AND_CTX | — | — | 0 | none | LATCHED/3 | info bit3 |
| 18 | LOST | - | - | - | - | VALID | 243 differs | BLOCKED_CONTEXT_MISMATCH | CTX_243 | LIVE | — | 0 | none | BLOCKED/8 | |
| 19 | LOST | - | - | - | - | VALID | 248 bit0 = 0 | BLOCKED_CONTEXT_MISMATCH | CTX_248_BIT0 | LIVE | — | 0 | none | BLOCKED/8 | |
| 20 | LOST | - | - | - | - | VALID | only 230/245/247 differ | WOULD_ALREADY_MATCH | MATCH_E1_AND_CTX | — | — | 0 | none | LATCHED/3 | info bits 0-2. 245 is not compliance evidence |
| 21 | LOST | - | - | - | - | VALID | Block B not updated > 180 s | WAIT_LIVE_DATA | LIVE_CACHE_STALE | LIVE | — | 0 | — | PREEMPT/0 | never assume a match |
| 22 | LOST | - | - | - | - | VALID | polling switched off | WAIT_LIVE_DATA | LIVE_POLLING_OFF | LIVE | — | 0 | — | PREEMPT/0 | |
| 23 | LOST | - | - (just cleared) | - | - | VALID | no poll since fence | WAIT_LIVE_DATA | LIVE_CACHE_PRE_FENCE | LIVE | — | 0 | — | PREEMPT/0 | transient, ~60-125 s (fence = dispatch+2, 60 s poll FW:18548) |
| 24 | LOST | - | - | - | - | VALID | no Block B since boot | WAIT_LIVE_DATA | LIVE_NOT_LATCHED | LIVE | — | 0 | — | PREEMPT/0 | also after FB-C2's first ready tick |
| 25 | LOST | - | - | - | - | NOT_CAPTURED, proven (witness hw=0) | — | BLOCKED_NO_PROFILE | PROFILE_NOT_CAPTURED | FBP | — | 0 | — | LATCHED/2 | |
| 26 | LOST | - | - | - | - | NOT_CAPTURED, unproven | — | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_ABSENT_UNPROVEN | FBP | — | 0 | — | BLOCKED/7 | CONTRADICTION #9 resolved |
| 27 | LOST | - | - | - | - | INVALIDATED | — | BLOCKED_PROFILE_INVALIDATED | PROFILE_INVALIDATED | FBP | — | 0 | — | LATCHED/2 | |
| 28 | LOST | - | - | - | - | CORRUPT | — | BLOCKED_PROFILE_CORRUPT | PROFILE_CORRUPT | FBP | — | 0 | — | BLOCKED/7 | defect detail |
| 29 | LOST | - | - | - | - | CORRUPT_DOMAIN | — | BLOCKED_PROFILE_CORRUPT | PROFILE_CORRUPT_DOMAIN | FBP | — | 0 | — | BLOCKED/7 | |
| 30 | LOST | - | - | - | - | UNREADABLE | — | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_UNREADABLE | FBP | — | 0 | — | BLOCKED/7 | |
| 31 | LOST | - | - | - | - | SAVE_UNCONFIRMED (prior VALID) | match | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_SAVE_UNCONFIRMED | FBP | — | 0 | — | BLOCKED/7 | never uses the prior mirror |
| 32 | LOST | - | - | - | - | PROFILE_LOST | — | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_LOST | FBP | — | 0 | — | BLOCKED/7 | only with the FB-B witness |
| 33 | LOST | - | A | - | - | VALID | overlay | WOULD_PREEMPT_FREE_POWER | FP_ACTIVE | FP | FP | 0 | — | PREEMPT/0 | `projected_after` from the FP snapshot vs profile. Needs FB-D `request_free_power_end` (N4) |
| 34 | LOST | - | A | - | - | NOT_CAPTURED, unproven | overlay | WOULD_PREEMPT_FREE_POWER | FP_ACTIVE | FP | FP | 0 | — | PREEMPT/0 | projected_after = BLOCKED_PROFILE_UNAVAILABLE (BLOCKED/7) |
| 35 | LOST | - | St | - | IF | VALID | — | WOULD_PREEMPT_FREE_POWER | FP_STARTING | FP | FP | 0 | — | PREEMPT/0 | pre-empt once START ends (ARCH row 7) |
| 36 | LOST | - | RR (expired) | - | - | VALID | — | WAIT_FREE_POWER_RESTORE | FP_RESTORE_DUE | FP | — | 0 | — | PREEMPT/0 | watchdog within 15 s |
| 37 | LOST | - | BO | - | - | VALID | — | WAIT_FREE_POWER_RESTORE | FP_RESTORE_BACKOFF | FP | — | 0 | — | PREEMPT/0 | COMMS backoff 15-300 s |
| 38 | LOST | - | PC | - | - | VALID | — | WAIT_FREE_POWER_RESTORE | FP_CLEAR_PENDING | FP | — | 0 | — | PREEMPT/0 | self-clears within about 15 s |
| 39 | LOST | - | ON | - | - | VALID | — | BLOCKED_OPERATOR_NEEDED | FP_OPERATOR_NEEDED | FP | — | 0 | — | BLOCKED/5 | |
| 40 | LOST | - | MC (cause MALFORMED) | - | - | VALID | — | BLOCKED_RECOVERY_METADATA | FP_METADATA_CORRUPT | FP | — | 0 | — | BLOCKED/5 | detail cause=2 |
| 41 | LOST | - | UK (cause MARKER_UNREADABLE) | - | - | VALID | — | BLOCKED_RECOVERY_METADATA | FP_MARKER_UNREADABLE | FP | — | 0 | — | BLOCKED/5 | wording never suggests a reboot (§5 c) |
| 42 | LOST | - | OIP set, no FP script running, 4 s | - | - | VALID | — | WAIT_WRITE_IN_FLIGHT | FP_OP_FLAG_SETTLING | FP | — | 0 | — | PREEMPT/0 | pending Modbus callback (§2.1) |
| 43 | LOST | - | same, 15 s | - | - | VALID | — | WAIT_WRITE_IN_FLIGHT | FP_OP_FLAG_STUCK | FP | — | 0 | — | PREEMPT/0 | L7 |
| 44 | LOST | A, live 244 = 0 | - | - | - | VALID | overlay | WOULD_PREEMPT_DUMP | DUMP_ACTIVE | DUMP | D | 0 | — | PREEMPT/0 | `request_dump_end` already exists (neutral). EXH NO (guarded lease) |
| 45 | LOST | EN, live 244 = 0 | - | - | IF | VALID | — | WAIT_DUMP_RESTORE | DUMP_RESTORE_RUNNING | DUMP | — | 0 | — | PREEMPT/0 | EXH YES while live is trusted; UNKNOWN after the fence |
| 46 | LOST | RR, BO, live 244 = 0 | - | - | - | VALID | — | WAIT_DUMP_RESTORE | DUMP_RESTORE_BACKOFF | DUMP | — | 0 | — | PREEMPT/0 | EXH YES (comms path: guards suspended, V4 NEW) |
| 47 | LOST | ON, live 244 = 0 | - | - | - | VALID | — | BLOCKED_OPERATOR_NEEDED | DUMP_OPERATOR_NEEDED_EXPORT_LIVE | DUMP | — | 0 | — | BLOCKED/5 | EXH YES. **Never write** (§4) |
| 48 | LOST | ON, live 244 = 2 | - | - | - | VALID | — | BLOCKED_OPERATOR_NEEDED | DUMP_OPERATOR_NEEDED | DUMP | — | 0 | — | BLOCKED/5 | EXH NO; 256-261 residue reported |
| 49 | LOST | ON, live pre-fence (just after the mismatch) | - | - | - | VALID | — | BLOCKED_OPERATOR_NEEDED | DUMP_OPERATOR_NEEDED | DUMP | — | 0 | — | BLOCKED/5 | EXH **UNKNOWN**, never 0/NO |
| 50 | LOST | ON + Force bypass armed | - | - | - | VALID | — | WAIT_DUMP_RESTORE | DUMP_FORCE_QUEUED | DUMP | — | 0 | — | PREEMPT/0 | V4 bypass leak: next watchdog tick runs a Force (D7a) |
| 51 | LOST, after an ESP reboot | RR (lockout commit had not landed, so N=false) | - | - | - | VALID | — | WAIT_DUMP_RESTORE | DUMP_RESTORE_DUE | DUMP | — | 0 | — | PREEMPT/0 | §4.1: a non-durable lockout re-appears as an automatic restore with a fresh mismatch count; EXH YES if live 244 = 0 |
| 52 | LOST | MC, K=4, live 244 = 2 | - | - | - | VALID | — | BLOCKED_RECOVERY_METADATA | DUMP_METADATA_CORRUPT | DUMP | — | 0 | — | BLOCKED/5 | contained but revocable; EXH NO |
| 53 | LOST | MC, K=4, live 244 = 0 | - | - | - | VALID | — | BLOCKED_RECOVERY_METADATA | DUMP_METADATA_CORRUPT | DUMP | — | 0 | — | BLOCKED/5 | EXH YES; the watchdog moves K to 7 (FW:18507-18510) |
| 54 | LOST | MC, K=3 | - | - | IF | VALID | — | BLOCKED_RECOVERY_METADATA | DUMP_METADATA_CORRUPT | DUMP | — | 0 | — | BLOCKED/5 | P0 running; the lockout outranks the wait |
| 55 | LOST | UK, K=8, live 244 = 0 | - | - | - | VALID | — | BLOCKED_RECOVERY_METADATA | DUMP_MARKER_UNREADABLE | DUMP | — | 0 | — | BLOCKED/5 | EXH YES; containment not armed (N13) |
| 56 | LOST | - | - | ON (held after a 2→0 test), live 244 = 0 | - | VALID | — | BLOCKED_OPERATOR_NEEDED | R244_HELD | R244 | — | 0 | — | BLOCKED/5 | ARCH A25 resolved to LEASE_RESTORE_LOCKED; EXH YES |
| 57 | LOST | - | - | ON + drift guard | - | VALID | — | BLOCKED_OPERATOR_NEEDED | R244_HELD_DRIFT_GUARD | R244 | — | 0 | — | BLOCKED/5 | firmware dead end (N11) |
| 58 | LOST | - | - | PC | - | VALID | — | BLOCKED_OPERATOR_NEEDED | R244_CLEAR_PENDING_OPERATOR | R244 | — | 0 | — | BLOCKED/5 | manual press only |
| 59 | LOST | - | - | EN | IF | VALID | — | WAIT_WRITE_IN_FLIGHT | R244_RESTORE_RUNNING | R244 | — | 0 | — | PREEMPT/0 | only via an HA press (A6 case) |
| 60 | LOST | - | - | MC | - | VALID | — | BLOCKED_RECOVERY_METADATA | R244_METADATA_CORRUPT | R244 | — | 0 | — | BLOCKED/5 | |
| 61 | LOST | - (RAM; NVS holds a ghost RR), no FB-B probe this boot | - | - | - | VALID | match | WOULD_ALREADY_MATCH | MATCH_E1_AND_CTX | — | — | 0 | none | LATCHED/3 | **Blind spot** (§2.10): FB-F's precheck probe would find it → BLOCKED/6 (ARCH A17). `durable_leg_projected=1`; `aborted_start_mask` may flag it |
| 62 | LOST | - (RAM), FB-B REVIEW probe latched RR this boot | - | - | - | VALID | match | BLOCKED_DURABLE_UNKNOWN | DUMP_MARKER_DIVERGED | DUMP | — | 0 | — | BLOCKED/6 | latch D; FB-F reboot rule applies (§8.1) |
| 63 | LOST | - | - (RAM), FB-B probe latched UNREADABLE | - | - | VALID | — | BLOCKED_DURABLE_UNKNOWN | FP_PROBE_UNREADABLE | FP | — | 0 | — | BLOCKED/6 | sticky for the boot; no re-probe |
| 64 | LOST | - | - (RAM), FB-B probe 1 = CLEAR (latch P), probe 2 = ABSENT | - | - | VALID | — | BLOCKED_DURABLE_UNKNOWN | FP_MARKER_EVIDENCE_VANISHED | FP | — | 0 | — | BLOCKED/6 | vanish rule. With probe 1 = UNREADABLE, probe 2 never runs (latch U) and row 63 applies |
| 65 | LOST | Cabs | Cabs | Cabs | - | VALID | match | BLOCKED_DURABLE_UNKNOWN | DUMP_MARKER_ABSENT_UNPROVEN | DUMP | — | 0 | — | BLOCKED/6 | R3 (L6); `absence_relied=1`; alt = WOULD_ALREADY_MATCH. FB-D witness removes it |
| 66 | LOST | - | ON stale, marker CLEAR at boot | - | - | VALID | match | WOULD_ALREADY_MATCH | MATCH_E1_AND_CTX | — | — | 0 | none | LATCHED/3 | `fp_stale_operator_needed=1` (V5 (3)); not blocking |
| 67 | LOST | - | ON, marker ABSENT at boot | - | - | VALID | — | BLOCKED_DURABLE_UNKNOWN | FP_MARKER_LOST | FP | — | 0 | — | BLOCKED/6 | F11.h; FB-B capture refuses too |
| 68 | LOST | retry ON raw, marker ABSENT at boot | - | - | - | VALID | — | BLOCKED_DURABLE_UNKNOWN | DUMP_MARKER_LOST | DUMP | — | 0 | — | BLOCKED/6 | D12 via `dump_retry_boot_on_raw` |
| 69 | LOST (A6: HA connected, heartbeat dead) | - | - | - | MTOU IF | VALID | — | WAIT_WRITE_IN_FLIGHT | MTOU_APPLY_RUNNING | MTOU | — | 0 | — | PREEMPT/0 | N7 |
| 70 | LOST | - | - | - | LK (MWIP, no owner ≥ 10 s) | VALID | — | WAIT_WRITE_IN_FLIGHT | LOCK_HELD_NO_KNOWN_OWNER | BUS | — | 0 | — | PREEMPT/0 | MAIN S6 leak; the config poll also stops (cache ages to STALE) |
| 71 | LOST | - | RR | - | LK (CIP ≥ 60 s) | VALID | — | WAIT_WRITE_IN_FLIGHT | RTC_LOCK_STUCK | BUS | — | 0 | — | PREEMPT/0 | L7 precedes L9: the restore cannot run (N2) |
| 72 | LOST | - | - | - | - | VALID (256 = 8000), site 6000 [synthetic] | — | BLOCKED_SITE_CEILING | SITE_CEILING_BELOW_PROFILE | SITE | — | 0 | — | BLOCKED/10 | unreachable with FW:13 = 8000 |
| 73 | SUP- + EP | - | - | - | - | VALID | 256 differs | WOULD_APPLY_PROFILE | E1_DELTA (+SUP_RETURNED_EPISODE_OPEN) | — | — | 1 | F256_UP | LATCHED/4 | HA return does not cancel the episode |
| 74 | SUP+ + EP | - | - | - | - | VALID g4, re-captured after LOST (bound VALID g3) | match | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_CHANGED_SINCE_LOST | FBP | — | 0 | — | BLOCKED/7 | §6.2 |
| 75 | SUP+ + EP | - | - | - | - | VALID, captured after an episode that opened NOT_CAPTURED | match | BLOCKED_PROFILE_UNAVAILABLE | PROFILE_CHANGED_SINCE_LOST | FBP | — | 0 | — | BLOCKED/7 | bound class 1 ≠ 5; a 0-sentinel binding would have said WOULD_APPLY |
| 76 | LOST after an ESP reboot (uptime ≥ 300 s, no beat; new episode, trigger S) | - | RR (lease ended at boot) | - | - | VALID | — | WAIT_FREE_POWER_RESTORE | FP_RESTORE_DUE | FP | — | 0 | — | PREEMPT/0 | FP ends at boot (FW:373-381); the previous RAM episode is gone (S3 breadcrumb only); binding re-recorded |
| 77 | any | any | any | any | any | any | any, `boot_loaded=0` | NOT_EVALUATED | BOOT_NOT_LOADED | BOOT | — | 0 | — | RAM | |
| 78 | LOST | RR | RR | - | - | VALID | — | WAIT_DUMP_RESTORE | DUMP_RESTORE_DUE | DUMP | — | 0 | — | PREEMPT/0 | Unreachable on MAIN: dual RR becomes corrupt at boot (FW:904-921). Row pins the domain tie-break |
| 79 | LOST | - | RR | ON | - | VALID | — | BLOCKED_OPERATOR_NEEDED | R244_HELD | R244 | — | 0 | — | BLOCKED/5 | FP+R244 after a ghost (N10). L5 precedes L9 |
| 80 | LOST | MC (malformed) | - | ON (trusted) | - | VALID | — | BLOCKED_RECOVERY_METADATA | DUMP_METADATA_CORRUPT | DUMP | — | 0 | — | BLOCKED/5 | N16: P0 may overlay the held 244 value; R244 still reported |
| 81 | LOST | MC (malformed) | EN (trusted RR restore running) | - | IF | VALID | — | BLOCKED_RECOVERY_METADATA | DUMP_METADATA_CORRUPT | DUMP | — | 0 | — | BLOCKED/5 | N17: FP's P1 restore writes 256-261 over Dump's unresolved obligation; L3 outranks the wait |

---

## 10. Charter overturns, contradictions, cross-section items, prerequisites, pins, tests

### 10.1 Charter changes
- **OVERTURNS CHARTER C7 (part), concurring with S3 FBC-13 and S6 X-1.** C7 allowed FB-C "read-only durable marker probes (NVS reads) at decision edges". FB-C performs **no** NVS reads.
  - **Reason:** an NVS read can erase a CRC-bad chunk, erase an index whose chunk is missing, erase an inconsistent entry of another key, and invalidate a page so that later reads erase intact records (NVSP:280-285, 904-905, 948-952; NVSS:672-676, 697-702; V1 (1)-(3), N3). A same-boot re-probe turns READ_ERROR into ABSENT (the laundering sequence). FB-C has no authority to act on any finding, so every probe would be pure risk.
  - **What replaces it:** boot-load retention, lockout causes, the Dump retry raw bit, activity tracking, and FB-B's per-boot probe latch (all RAM).
  - **Affected sections:** HA entity/API contract (no divergence field computed by FB-C itself; `durable_leg` letters), test plan (Z3 bans `nvs_`/`load_record` in FB-C), FB-D/FB-F (own the probe and the divergence reboot), FB-B (owns the latch).
- **OVERTURNS CHARTER C0 (partial).** C0 lists CONTAINMENT (SG-02 K≠0) as an OBLIGATION kind. This section classifies a Dump domain with C set as **UNKNOWN_METADATA_CORRUPT with a `containment=K` detail**, not as OBLIGATION_CONTAINMENT.
  - **Reason:** containment exists only while `dump_recovery_metadata_corrupt` is set (FW:17076-17077, 18495), and that flag is a hard lockout with no false path. Fail-closed dominance says UNKNOWN outranks OBLIGATION. A single C0 value per domain keeps "positively clear" simple. S6 X-2 adopts this.
  - **Affected sections:** HA contract (domain state strings), dashboard shadow detail, test plan, and S1 §4.3 (its DUMP row 3 must carry K as detail instead).
- **Refines C0/C6 (not an overturn).** CLEAR_PROVEN keeps MARKER_ABSENT as an evidence value (C0), but R3 locks that FB-F never relies on it without a witness (exactly C6's caveat, now LOCKED rather than open). FB-C projects that rule.
- **Extensions to C0.** New OBLIGATION kinds STARTING and IN_FLIGHT; new UNKNOWN kind PROBE_PENDING (FB-E/FB-F only); CLEAR evidence values MARKER_CLEAR_BOOT / _RUNTIME / _PROBE, MARKER_ABSENT, NO_DURABLE_RECORD, NOT_IMPLEMENTED, IDLE; new DIVERGED reasons MARKER_EVIDENCE_VANISHED and MARKER_LOST.

### 10.2 CONTRADICTIONS (explicit, not reconciled silently)
1. ARCH A9 BLOCKED(CONTEXT_244) (ARCH:897@pr54) vs FB-A (244 is E1; no such code; FBH:148-150, 275-291). **Locked: LIVE_OUT_OF_DOMAIN (9).**
2. ARCH §6.3 row 8 LEASE_RESTORE_LOCKED (ARCH:529@pr54) vs §6.5/§6.6/A25 REG244_PENDING (ARCH:581, 589, 913@pr54). **Locked: LEASE_RESTORE_LOCKED (5), not ACK-able.**
3. ARCH §6.6 lists REG244_PENDING and METADATA among the ACK-able "BLOCKED before any fallback write" states (ARCH:589@pr54). With LEASE_RESTORE_LOCKED the exit is "resolve the lease first" (ARCH:590@pr54). Consequence for FB-F: BLOCKED_RECOVERY_METADATA and BLOCKED_OPERATOR_NEEDED are **not** ACK-able.
4. ARCH Q7 "No by default; conflicts with reg244 ownership" (ARCH:997@pr54). The rationale does not hold on MAIN (§4.4). Product decision flagged.
5. [MAIN comment] WSI:66-71, 137 say "eleven"/"fourteen" write paths; the pinned set has 16 (WSI:72-127).
6. [MAIN runtime text] FW:277 "automatic writes disabled" vs unattended P0/P1/P5 writers (§1.2) (per E06 §12.5).
7. [DOC] ARCH §2.x lists S1-S4 as open. MAIN has them fixed, which the gate verification above relies on (E02 C-7).
8. **[MAIN comment vs MAIN code]** FW:3451-3455 says containment states "2/4/6/7/8 are terminal for this boot"; the watchdog moves 4 → 7 (FW:18507-18510). **Locked: absorbing {2,6,7,8}; 4 revocable.**
9. **[DOC vs FB-A/NVS]** ARCH:533 requires PREEMPTED_NO_PROFILE "only when proven NOT CAPTURED"; FB-A classifies every ABSENT as NOT_CAPTURED, and NVS turns corruption into ABSENT. **Locked: both witness branches (§6.1).**
10. **[DOC vs FB-B/FB-C era]** ARCH A28 (ARCH:916@pr54) "re-capture between LOST and apply: Impossible (capture is gated)". No gate exists until a durable failback record exists (FB-F era, S1 FBS slot). **Locked: FB-C detects it via the episode binding (§6.2).**
11. **[MAIN log text vs MAIN code]** FW:16720 logs "Second consecutive restore verify mismatch"; the counter is not reset by comms failures (FW:16727-16733), so "consecutive" is imprecise (V4 (1)).
12. **[MAIN status text vs SG-06 semantics]** FW:680, 947, 1030 advise "reboot to re-read" for an UNKNOWN marker; a reboot is precisely what turns it into ABSENT = CLEAR. **Locked: text fix before FB-B1 (§5 c).**

### 10.3 Cross-section conflicts resolved here (for the integrator)
- **S1 §4.3 per-domain tables vs S4 §2.4-§2.9.** S4 is normative (one implementation, §2.2). Differences S1 must adopt: CONTAINMENT carried as detail of METADATA_CORRUPT (S6 X-2); STARTING/ENDING attributed by `is_running()` plus the grace rule rather than `OIP && SV`; the latch consumption and vanish rules (S1 already has the alarm; it must widen it to the 4-bit latch and never re-probe a latched key); F11.h / D12 MARKER_LOST (S1 currently shows `fp_on_stale` as a warning even when the marker is ABSENT); a latch result from REVIEW binds SAVE.
- **S3 §11.3 allowlist and Z3.** Add read-only `is_running()` of the §2.9 owner list and the FP/Dump/R244 scripts, `dump_force_restore_bypass`, the retention globals, `fallback_profile_probe_latch`, `fallback_profile_boot_loaded`, and FB-B1's classifier header in the header include allowlist.
- **S3 §7.1 episode record.** Add the four `ep_prof_*` fields (§6.2), recorded at E1.
- **S3 §11.4 interface.** S4's `ShadowInputs`/`ShadowPlan` (§3.2-§3.3) supersede S3's sketch; the field mapping is in §3.3.
- **S6 X-5.** FB-C2 classifiers use `fallback_profile_boot_loaded`; FB-C1 keeps S3's `supervision_generation != 0` readiness.
- **S6 BLK-11.** Retention is **HARD** before FB-C2 (not SOFT): without it FB-C cannot distinguish marker from absence evidence, R3 cannot be projected, and MARKER_LOST cannot be detected.
- **S2 witness decision.** Only `fbp.not_captured_proven` and PROFILE_LOST depend on it; both branches are locked (§6.1).

### 10.4 Prerequisites (with stage)

| Stage | Prerequisite |
|---|---|
| Before FB-B0 (first FB include) | PR54 [9] absolute pins converted to scope/delta form (§10.5 items 5-9; S3 P-FBC-10) |
| Before FB-B (FB-B1) | Reboot-advice text fix at FW:680 / 947 / 1030 (§5 c) |
| Before FB-B (FB-B1) | Shared classifier (§2.2) with latch and vanish rules; `fallback_profile_probe_latch`; no re-probe of a latched key |
| Before FB-B (FB-B1) | Retention globals: `*_marker_boot_load`, `*_lockout_cause`, `dump_retry_boot_on_raw` (S6 BLK-11; S3 P-FBC-05) |
| Before FB-B (FB-B1) | Simulator NVS CRC-erase fault model (READ_ERROR → ESP_FAIL → NOT_FOUND per V1 (1)/(3)) and the pinned test "READ_ERROR then ABSENT in the same boot stays BLOCKED" (E10 and E03: no such model exists today) |
| Before FB-C (FB-C2) | FB-B2 profile RAM mirror, class enum and `not_captured_proven` view (names from S1/S2) |
| Before FB-C (FB-C2) | RAW_CACHE_EXT (S3 §11.5) |
| Before FB-C (FB-C2) | Simulator support for one `std::array` global, script `is_running()` and the FB-C interval tick (S3 P-FBC-03) |
| Before FB-C (FB-C2) | Pinned MWIP-owner list test (§2.9) and probe call-site test (§2.2) |
| Before FB-C (preferred) | PR53 merged, so BUS "no owner" stops firing from the MAIN S6 leak (soft; S6 X-3) |
| Before FB-E | RTC S6 `on_not_sent` / `on_custom_response` fix (N2) |
| Before FB-E | Lock-age breaker or an equivalent operator procedure |
| Before FB-E | Fresh-read precheck (never the cache) and the precheck probe with latch rules (R3) |
| Before FB-E | Refusal wording naming the blocking domain (§4.3) and the absence acknowledgement in Review (R3) |
| Before FB-F (FB-D) | `request_free_power_end` neutral primitive (N4) |
| Before FB-F (FB-D) | Supervision/failback-episode gates on every P5 start and on P4 Manual TOU / reg244 Apply (R4; N5, N7) |
| Before FB-F (FB-D) | R244 escape: strict automatic restore or an operator Force/Accept equivalent, plus a clear-only path for R244 PC (N11) |
| Before FB-F (FB-D) | SG-02b product decision (N12; S6 OWN-01/OWN-25) |
| Before FB-F (FB-D) | Absence witness strategy (`absence_witness`, §2.10; S6 OWN-12) |
| Before FB-F (FB-D) | Latch gating so "Fallback is the final writer" (N15) |
| Before FB-F (FB-D) | Policy A vs B decision (FB-C already projects both) |
| Before FB-F (FB-D) | Episode logic re-derives Dump lockout state after every reboot (§4.3); the divergence reboot is restricted to `*_MARKER_DIVERGED` (§8.1) |

### 10.5 Pin impact of the locked placement (enumerated, each with its planned amendment)

| # | Pin | Effect of FB-B1/FB-C2 as specified here | Planned treatment |
|---|---|---|---|
| 1 | PRA-T:278-280 — exactly one interval contains `supervision_have_valid` | FB-C would break it if it read that token | FB-C derives "has a valid beat" from `supervision_valid_count > 0` (S3 §3.2); an FB-C test asserts the token is absent. **No amendment** |
| 2 | PRA-T:382-384 — no non-`ecco_supervision_*` substitution added | S4 adds no substitution (thresholds are header `constexpr`, §3.7); S3's cache-age substitution needs its one-line prefix filter | S3 FBC-21 amendment only |
| 3 | PRA-T:316-331 — 52/60 Modbus actions; 55 commits; (6,3) loads | FB-C adds no Modbus action and no NVS call. The retention edits reuse the existing locals and add no `load_record(_status)` call. FB-B's direct reader is not `load_record_status` (S1 §4.2) | **No amendment** |
| 4 | PRA-T:334-338 — 30 scripts; no "supervision" in scripts | FB-C adds no script | **No amendment** |
| 5 | P54-T:703-704 — sha256 of 6 files incl. the firmware YAML (V8 NEW) | Any FB-B/FB-C firmware edit trips it | Convert to scope form before FB-B0 (S3 P-FBC-10) |
| 6 | P54-T:706-707 — `esphome.includes` equals exactly the two pre-existing headers | FB-B adds FBH and its classifier header; FB-C2 adds `ecco_failback_shadow.h` | Convert to "pre-existing two ⊆ includes ⊆ pre-existing ∪ {FB headers}" |
| 7 | P54-T:719-725 — no file includes the FB-A header | The classifier header and `ecco_failback_shadow.h` `#include` it | Allowlist the FB-B/FB-C headers and the YAML includes entry. **Renaming the shadow header would not avoid this**: it must include FB-A types |
| 8 | P54-T:726-730 — BANNED `ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback` in the firmware YAML and HA/frontend/deployment | The YAML necessarily contains `ecco_fallback_profile.h` (FB-B) and `ecco_failback_shadow` (FB-C) | Scope the ban to `home-assistant/`, `frontend/`, `deployment/` until FB-B3/FB-C3 |
| 9 | P54-T:750-753 — 30 scripts / 418 globals / 2 API actions / 8 intervals / entity counts | FB-B adds globals, scripts, an API action, entities; FB-C1 adds 1 interval and 5 text sensors; FB-C2 adds globals | Convert to delta pins with provenance arithmetic |
| 10 | P54-T:754-756 — (55, 6, 3) durable call counts | Unchanged by FB-C; FB-B per S2 | FB-B's section |
| 11 | SG01P5-T:262-268 — on_boot lambda equals the 6c62417 one plus exactly one inserted block (after reverting SG-06 edits) | The retention assignments and the text fix edit lambda[0] | A chained `_fbb_scope` revert module (S1/S3/S6 scope-chain) that removes exactly the FB-B1 on_boot edits |
| 12 | SG01P5-T:274-280 — hashes of `on_boot[1:]`, **all intervals**, the API block | FB-C1 inserts an interval; FB-B adds an API action | Chained `_fbc_scope`/`_fbb_scope` reverts (S3 §11.6) |
| 13 | SG01P5-T:281-290 — `_pre_globals` hash (only the 9 SG-01 globals added) | Every new global | Same chained revert, filtering `fallback_profile_*`, `failback_shadow_*` and the retention globals |
| 14 | SG06-T:268 and 282-284 — on_boot with SG-06 edits reverted equals 049c37e; `esphome` minus on_boot unchanged | Retention edits in lambda[0]; new includes | `_sg06_scope` chain extended by the FB-B1 edits |
| 15 | SG06-T:536-541 — behavioural "every RAM global and every entity publish identical to main's on_boot" | The retention globals differ by construction; the text fix changes three published strings | Filter the retention globals and compare the three texts against the new wording explicitly |
| 16 | `test_sg01_self_partial_phase3_4.py:1235-1236` — interval hash | FB-C1's interval | Chained revert |
| 17 | WSI, analyzer, `test_sg01_phase0_harness.py:182-187` | Unchanged write surface; `registry/failback_shadow.py` avoids `self_partial`/`start_journal` | **Must stay green unchanged** |
| 18 | New: MWIP-owner list equality (§2.9); probe call sites (only FB-B REVIEW/SAVE, later FB-E/F precheck); FB-C contains no `nvs_`/`load_record` (S3 Z3); no YAML outside FB-C references `failback_shadow_` (S3 Z5) | — | Added by FB-B1 / FB-C2 |

### 10.6 Test classes and section mutation ideas

**What is pinned purely** (golden vectors, C++ `static_assert` in the host-compile test, Python-mirror parity):
- every classifier row F0-F11.j, D0-D12, G0-G8, T1-T2, B1-B5, including the latch consumption, vanish and MARKER_LOST rules;
- the §3.4 precedence (for every pair of rows that can fire together, the earlier wins);
- the plan → FB-A mapping, checked against `failback_invariants_hold` legality (FBH:642-669);
- the `export_hazard` truth table (§4.2) including UNKNOWN;
- R3 evidence acceptance, `alt_plan_absence_accepted`, `projected_after`, `fba_result_policy_a`;
- episode binding (L12) with every class pair;
- zero-init fail-closed values; the 21+1 code set; string lengths and card-regex avoidance; threshold values.

**What needs a harness extension** (S3 P-FBC-03; E10 says `_dump_sim` runs scripts synchronously, has no interval scheduler and no NVS CRC model):
- `is_running()` and the grace timers (F4/D5/G4/B1) on the real FB-C lambda;
- the live latch on `cfg_block_b_seq`, the fence, and the torn-snapshot case;
- the NVS CRC-erase sequence for FB-B's probe and latch (prerequisite before FB-B1).

**What needs live proof:**
- fence latency distribution (expected ~60-125 s);
- per-owner MWIP hold maxima (threshold revision, §3.7);
- no false `*_OP_FLAG_STUCK` or `LOCK_HELD_NO_KNOWN_OWNER` during an FP/Dump/MTOU soak;
- `export_hazard` UNKNOWN windows after Dump restore attempts.

**Section mutation ideas** (each must be killed by the named detector):
1. Latched U but current probe ABSENT treated as CLEAR → latch/vanish golden vector (row 63/64).
2. Remove F11.h (ON && ABSENT) → row 67 vector.
3. Remove the D12 retry-raw rule → row 68 vector.
4. Accept MARKER_ABSENT in the R3 projection → row 65 vector and the "positively clear" enumeration test.
5. `export_hazard` UNKNOWN encoded as NO → row 49 vector.
6. K=4 treated as terminal/no hazard → row 53 vector.
7. L12 reads `fbp.rec` for a non-meaningful class → golden vector with garbage `rec` under NOT_CAPTURED.
8. Episode binding reduced to a 0-sentinel binding → row 75 vector.
9. Grace removed from F4 → row 42 vector.
10. Fence offset +1 instead of +2 → harness case "invalidate between Block A and Block B".
11. NOT_CAPTURED projected LATCHED/2 without proof → row 26 vector.
12. `R` added as a D11 term → vector with `!S && R` (must be CLEAR).
13. MS tested before MC in F1 → vector with MC and MS==RR (cause DATA_UNTRUSTED).
14. D7a removed → row 50 vector.
15. An `nvs_`/`load_record` token or a probe call added to FB-C → S3 Z3 / call-site pin.
16. Live compared from the unlatched cache → torn-snapshot harness case.
17. L6 moved after L10 → vector with FP RR and R244 Cabs (plan must be BLOCKED_DURABLE_UNKNOWN).
18. Policy-A field equal to the Policy-B result for L25 → row 8 vector (must be LATCHED/1).

### 10.7 Residuals and items that cannot be settled here (and why)
- **Readiness wording** (Ready / Drifted / Invalidated / Not Captured / Blocked / Shadow Recovery) belongs to the HA section. Suggestions are in §6.1.
- **The 274-279 compare.** Full-word equality assumes the inverter never sets undecoded bits spontaneously (E09 §5: only 0/1 observed). A spontaneous bit would surface as BLOCKED_LIVE_OUT_OF_DOMAIN, which is fail-safe; FB-B/FB-C would revisit it on live evidence.
- **`projected_after`** is best effort. An FP restore can end in NEITHER / context hold (→ operator needed) and a Dump restore in a mismatch; neither is predictable from RAM.
- **Blind spots of a probe-free shadow** (§2.10): ghost markers and runtime corruption are invisible until FB-B probes or FB-F's precheck runs. This is the accepted cost of never weakening SG-06.
- **SG-02b** stays a product decision (§4.4). FB-C's decision does not depend on it.
- **The FBS record after a downgrade** (a durable FailbackStateV1 left by future FB-E/FB-F firmware) is not an FB-C input; FB-B's capture gate covers it (S1 §4.3 FBS slot).

---

## 11. Red-team disposition

| # | Severity | Issue | Disposition | How it was fixed, or why rejected (evidence) |
|---|---|---|---|---|
| 1 | BLOCKER | FB-C's own re-probe turns UNKNOWN into CLEAR (READ_ERROR → ABSENT → CLEAR_PROVEN in one boot) | **ACCEPTED (strengthened)** | Trace verified: DS:141-163 `classify_load_failure`; PREFS:109-128; NVSP:280-285; NVSS:697-702. FB-C now performs **zero** NVS reads (§2.10; concurs with S3 FBC-13), so FB-C cannot launder anything. The shared classifier (§2.2), used by FB-B capture, adds the per-boot sticky latch (U/M/D bits), the vanish rule (`*_MARKER_EVIDENCE_VANISHED`), "never re-probe a latched key", and the direct two-step reader (not `load_record_status`). FB-B's gate consumes the latch; FB-C reads it. The sim CRC-erase fault model and the pinned test "READ_ERROR then ABSENT stays BLOCKED" are a prerequisite before FB-B1 (§10.4). Rows 63-64 |
| 2 | MAJOR | F11 ignores durable operator_needed=1 exactly when it proves the marker was lost | **ACCEPTED for FP and Dump; R244 variant ACCEPTED as detail only** | Verified: ON commits only inside RR restore/Force paths (FW:8742-8743, 8791-8792, 8829-8830, 9030-9031, 10722-10723); no `nvs_erase*` call exists; the FP retry tag (5c3575f) postdates the FP marker tag (694d10d); Dump tags share commit 95deec7. F11.h → FP_MARKER_LOST; D12 via new `dump_retry_boot_on_raw` → DUMP_MARKER_LOST (rows 67-68). The stale-ON flag is kept only with present-marker evidence. The R244 `LAV && ABSENT` signal stays non-blocking (`r244_lav_marker_absent`): LAV (a72bd5f) predates the reg244 marker tag (694d10d), so it is not proof of loss |
| 3 | MAJOR | R3 (LOCKED) admits P3 on CLEAR-by-absence, contradicting C6 | **ACCEPTED** | R3 now requires evidence ∈ {MARKER_CLEAR_PROBE, NO_DURABLE_RECORD, NOT_IMPLEMENTED, IDLE}; MARKER_ABSENT only with `absence_witness` (FB-D). Operator-attended exceptions named: FB-B capture (C6) and FB-E with explicit acknowledgement (§1.1). FB-C projects it as row L6 → BLOCKED/6 `*_MARKER_ABSENT_UNPROVEN`, plus `alt_plan_absence_accepted` (row 65) |
| 4 | MAJOR | R1 refuses P2 operator recovery of the obligation it exists to resolve | **ACCEPTED** | R1 restated per domain with an explicit ownership/dependency map; a domain's own P1/P2 is always admissible for its own obligation; P2 = escalation of P1 within a domain (§1.1). The ill-posed case (FP P1 while Dump corrupt) is now defined: an R1 overlay recorded as gap N17 (verified: no other-domain terms at FW:7726-7734, 16425-16447) |
| 5 | MAJOR | NOT_PROBED gives durable BLOCKED/6 and outranks WAIT; contradictory probe rules | **ACCEPTED (superseded)** | NOT_PROBED no longer exists: FB-C has no probe, so both contradictory rules are gone. For FB-E/FB-F, a pending probe is kind PROBE_PENDING → WAIT (PREEMPT_REQUIRED/0), never BLOCKED/6, and probes may run while MWIP is held (§2.2). BLOCKED/6 is used only for real divergence, latched findings and absence-unproven |
| 6 | MAJOR | `export_hazard` encodes UNKNOWN as 0; inconsistent exemptions; R244 undefined | **ACCEPTED** | Tri-state `ExportHazard` (zero-init UNKNOWN) and one predicate for every domain, whose only exemption is SG-02's D5 rule verbatim (verified FW:17135-17150) (§4.2). Defined for R244 (row 56), D7/D8 (rows 45-51) and K=4 (rows 52-53). UNKNOWN time is accumulated separately |
| 7 | MAJOR | Containment K=4 treated as terminal | **ACCEPTED** | Verified FW:3455 (comment) vs FW:18507-18510 (4 → 7). Absorbing {2,6,7,8}; 4 revocable; 1/5 re-run; 3 transient (§2.5 D2, §5). Row 44 of the draft split into rows 52-53 with the hazard from live 244. CONTRADICTION #8 added |
| 8 | MAJOR | §4.1 Dump lockout facts restate claims V4 corrected | **ACCEPTED** | Verified FW:16697-16733 (RAM-only branch 16706-16711), FW:3081-3084, resets at FW:15023/16660/16849/17003, reload FW:664-676. §4.1 rewritten: best-effort durability, "second mismatch since last reset", reboot as an exit, NVS loss as an exit. New row 51 (post-reboot D8). FB-F rule "never assume the lockout survives a reboot" (§4.3). CONTRADICTION #11 (log text) added |
| 9 | MAJOR | Episode-binding sentinel 0; L12 reads an undefined field; capture during episode | **ACCEPTED in part** | Struct binding {bound, class, generation, binding} recorded at S3's E1; L12 reads the record only for meaningful classes (§6.2; rows 74-75). **REJECTED part:** "refuse FB-B SAVE/INVALIDATE while `episode_open`". A shadow episode must never gate runtime behaviour: S3's non-authority pin Z5 forbids any non-FB-C YAML from referencing `failback_shadow_`, and the review's own minor issue (R4) makes the same point. The FB-F-era gate is S1's FBS slot. CONTRADICTION #10 (ARCH A28) flagged |
| 10 | MAJOR | NOT_CAPTURED projected LATCHED/2 without proof; CONTRADICTION with ARCH:533 | **ACCEPTED** | Verified ARCH:533. Both branches locked: proven (witness present, hw = 0) → BLOCKED_NO_PROFILE LATCHED/2; otherwise BLOCKED_PROFILE_UNAVAILABLE `PROFILE_ABSENT_UNPROVEN` BLOCKED/7, wording still "Not Captured" (§6.1; rows 25-26). CONTRADICTION #9 flagged |
| 11 | MAJOR | Probe side effects on other keys unanalysed; periodic probing | **ACCEPTED (superseded)** | FB-C never probes. The collateral (other-key erase, page INVALID, intact-index erase; NVSP:904-905, 948-952; NVSS:672-676, 697-700) is documented in §2.2 for FB-B's REVIEW/SAVE probes and future prechecks, which are operator-attended or one-shot, never periodic. A call-site pin is added (§10.5 #18) |
| 12 | MAJOR | Pin impact of the LOCKED placement incomplete | **ACCEPTED; header rename REJECTED** | Verified PRA-T:278-280, 316-331, 382-384; P54-T:703-756; SG01P5-T:262-288; SG06-T:268, 282-284, 536-541. 18 pins enumerated with treatments (§10.5). `supervision_have_valid` avoided (derived from `supervision_valid_count`). Thresholds are header `constexpr`, so no new substitution. Renaming `ecco_failback_shadow.h` is rejected: the includers scan (P54-T:719-725) catches any header that includes FB-A, and the BANNED regex already catches `ecco_fallback_profile.h` in the YAML, which FB-B must include; the real fix is converting PR54 [9] before FB-B0 |
| 13 | MINOR | Wrong or imprecise firmware citations | **ACCEPTED (with two corrections to the review)** | Fixed: reg244 Apply gate FW:13889-13921 (FP 13908-13909, Dump 13913-13914); Restore FW:14366-14388 (Dump 14385-14386); drift guard condition FW:14511, reject 14512-14524; FP Force check FW:9832 (text 9833); §1.3 → FW:13914. Corrections: Dump START's `rSV` term is **FW:14939** (14938 is a comment line); the config poll is the interval at **FW:18548** (FW:18523 is the RTC read) |
| 14 | MINOR | Plan-code count is 22, not 21 | **ACCEPTED** | After the merges (WAIT_REG244_RESTORE folded; BLOCKED_LIVE_UNKNOWN renamed WAIT_LIVE_DATA and renumbered) the set is exactly 21 emitted + 1 reserved, listed by number (§8.1) |
| 15 | MINOR | Fence blind window ~125 s; sampled edge detection fragile | **ACCEPTED** | Bound corrected to ~60-125 s (row 23). The fence is set on every FB-C tick where MWIP is held or an owner runs, and on obligation→clear edges (monotonic; not a single sampled edge). The residual (a whole hold between two samples) is stated (§7.6) |
| 16 | MINOR | `is_running()` misses pending modbus callbacks; no grace in F4/D5/G4 | **ACCEPTED** | Verified MBC:59-62, 98 (fire-and-forget) and FW:11722. 10 s grace with a SETTLING kind (IN_FLIGHT) before STUCK (F4a/b, D5a/b, G4a/b, B1/B3). Limits of `is_running()` documented (§2.1) |
| 17 | MINOR | Dead/misnamed codes; precedence description contradicts §3.4 | **ACCEPTED** | METADATA_LOCKOUT (kind 18, reasons 209/306) withdrawn: the cause is retained per set site (§2.1, §8.4), with DATA_UNTRUSTED honest about the bare-bool data load. BLOCKED_LIVE_UNKNOWN → WAIT_LIVE_DATA. WAIT_REG244_RESTORE folded into WAIT_WRITE_IN_FLIGHT. §1.5 states §3.4 is normative and kind-major, with a DUMP → FP → R244 tie-break |
| 18 | MINOR | "MS is 0 in these branches" is wrong for 460, 470, 910 | **ACCEPTED** | F1 note restricted to FW:334/346; MS is already RR for 460/470/910 (FW:350 runs first; V5 (2)). Mutation #13 |
| 19 | MINOR | R4 lets a shadow episode gate P5 starts | **ACCEPTED** | R4 limited to an FB-D/FB-F failback episode (durable record not CLEAR); a shadow episode never gates anything (§1.1) |
| 20 | MINOR | SG-02b rationale contradicts §4.2 reason 2 | **ACCEPTED** | The tension is named in the product-decision item, including Accept adopting 244 = 2 and losing an Allow-Export original when residue blocks the D5 exemption (§4.4) |
| 21 | MINOR | FBP not re-probed at LOST; torn live snapshot; force-bypass leak not modelled | **ACCEPTED** | FBP: "RAM mirror authoritative for the shadow episode; FB-F re-reads at precheck" (§6.3). Torn snapshot: live latched only on `cfg_block_b_seq` change (§7.6; verified FW:13518-13523, 13714-13725). Bypass: `dump_force_restore_bypass` read; D7a `DUMP_FORCE_QUEUED` (verified FW:16423-16424, 16888-16890; SCRIPT:72-87; row 50) |
| 22 | MINOR | Collector behaviour untestable in `_dump_sim`; hedged thresholds; text fix staged twice | **ACCEPTED** | §10.6 splits pure pins, harness-extension pins and live proof. Thresholds locked with initial values and a revision rule (§3.7). The reboot-advice text fix is staged once: before FB-B1 (§5 c), because capture accepts absence |

**Unanswered-question disposition (from the review's list):**

| Question | Locked answer here |
|---|---|
| FB-C Q7 add-on: SG-02b | FB-C's decision is locked (§4.2). SG-02b stays a PRODUCT DECISION, with the tension named (§4.4) and routed to S6 OWN-01/OWN-25 |
| FB-C Q9: no-witness branch of NOT_CAPTURED / PROFILE_LOST | Locked: unproven → BLOCKED/7 PROFILE_ABSENT_UNPROVEN; proven → LATCHED/2; PROFILE_LOST only with a witness (§6.1) |
| FB-F absence policy pre-empted by R3 | Locked fail-closed: no absence without a witness for FB-F; FB-D's preferred witness is lease-marker provisioning [FUTURE] (§1.1 R3, §2.10) |
| Policy A vs B | FB-C projects B; `fba_result_policy_a` is derived; FB-D's choice changes no FB-C code (§3.5) |
| Thresholds provisional | Locked initial values (10 s / 60 s / +2 / 180 s) plus a soak-based revision rule; probe cadences no longer exist (§3.7) |
| Episode layer dependency | S3 owns open/close; S4 locks the consumption: `episode_open` = S3 phase OPEN/HA_BACK, struct binding at E1, RAM-only, lost at reboot, re-bound on the next episode (row 76) (§6.2) |
| Capture/invalidate during an open episode; FBP durable leg at LOST | Not gated by the shadow episode (non-authority); FB-F-era gate is S1's FBS slot; FBP RAM mirror authoritative for the shadow episode; FB-F re-reads at precheck (§6.2-§6.3) |
