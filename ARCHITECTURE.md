# ECCO-Pro architecture (overview)

This is a short tour for someone who has not seen the project before. It describes how the pieces fit and where the safety decisions are made. Per-feature behaviour and limits are in [SAFETY.md](SAFETY.md), evidence levels in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md), and the developer notes in [CONTRIBUTING.md](CONTRIBUTING.md) and `docs/dev/`.

## 1. The big picture

```
 Inverter  ◄── RS485 / Modbus RTU ──►  Controller (ESP32 / ESP32-S3, ESPHome firmware)
                                        ├─ poller (read-only configuration + telemetry)
                                        ├─ transaction engine (snapshot → write → verify → restore)
                                        ├─ ownership / arbitration
                                        ├─ durable store (non-volatile records)
                                        └─ supervision, fallback profile, shadow check
                                                   │  ESPHome native API
                                                   ▼
                                          Home Assistant
                                          ├─ packages (helpers, templates, scripts, schedules, health)
                                          ├─ dashboard + custom cards
                                          └─ supervision heartbeat
                                                   │                 │ optional
                                                   ▼                 ▼
                                     Intelligence (advisory)     InfluxDB
```

Three layers, with a strict order of authority:

1. **The controller (authoritative).** Only the firmware talks to the inverter, and only it decides whether a write may happen.
2. **Home Assistant (operator surface).** Presents status, collects your requests and runs the schedules *you* arm. It asks the controller; it does not write registers.
3. **Intelligence (advisory).** Reads history and recommends. It has no write path and is not consulted by any safety gate.

## 2. The ESP controller

- ESPHome firmware (`firmware/`), built with ESPHome 2026.8.x. The classic ESP32 build is the base; the ESP32-S3 variant is a **hardware wrapper** that includes the base unchanged and overrides only the board/logger settings, so there is one body of application logic.
- It is the **only Modbus master** on its RS485 port (UART at 9600 baud, 8N1). All inverter traffic goes through one shared bus discipline: reads and writes do not interleave unless the arbitration rules allow it.
- Nothing in the controller depends on Home Assistant being reachable to **end or restore** a temporary action; those run on timers and a watchdog inside the controller.

## 3. Deterministic safety and control layer

The control logic is deliberately plain and deterministic: no learning, no probabilistic decisions, no hidden state.

- **Known registers only.** A fixed write surface (see [SAFETY.md](SAFETY.md)); a test fails if it widens.
- **Staged transactions.** Read current state → stage → explicit arm → write → read back and verify exactly → restore. A failed verification is a failure, never a success.
- **Durable obligations.** Before a temporary change, the controller records what it must undo in its non-volatile storage. After a reboot it reads the record: an unreadable or unrecognised record means *unknown*, which blocks writes rather than being treated as *clear*.
- **Fail closed, bounded retries.** Retries back off and are limited; an ambiguous situation ends in an operator decision, not a guess.
- **Pure, mirrored policy code.** Several safety decisions live in small, side-effect-free C++ headers (`firmware/include/*.h`) with a line-for-line Python mirror (`registry/*.py`). The mirror lets the project run exhaustive and fault-injection tests offline, and host-compile checks keep the two in step.
- **A capability registry** (`registry/inverter_capabilities.yaml`) records, per register or value, what is known, the write policy, and how it was proven. It is data for auditing and tests. The firmware does not read it at runtime.

## 4. Ownership and arbitration

Several features touch overlapping registers, or registers whose *meaning* depends on another register (for example the load/export mode changes how time-of-use power limits are interpreted). To avoid conflicting writes the controller arbitrates ownership:

- At most one writing feature holds the bus path at a time (Free Power, Dump-to-Grid, the register 244 policy, manual TOU, and clock correction).
- A feature refuses to start while another owns, or may still own, the registers it needs, including when a durable obligation is open or unknown.
- Arbitration considers **semantic conflicts**, not just identical register numbers.
- Background polling and clock correction re-check ownership immediately before each Modbus operation and defer rather than interleave.
- Where the inverter state matches neither the original nor the intended state, the controller stops and shows the evidence for a person to decide.

## 5. Modules (what exists today)

| Module | Role | Proof level (see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md)) |
|---|---|---|
| Telemetry and configuration polling | Read-only blocks; publishes entities | Hardware tested |
| Clock (RTC) correction | Drift detection and correction with a policy that avoids sensitive moments | Hardware tested |
| Manual six-slot TOU | Stage, review, apply, verify | Hardware tested |
| Free Power | Temporary grid-charge override, timer, exact restore, operator recovery | Hardware tested (normal path); recovery tools offline only |
| Export-mode policy (reg. 244) | Staged policy write with durable restore | Hardware tested |
| Dump-to-Grid | Timed, closed-loop export with durable restore; firmware stop-level bounds only (it does not use the battery reserve in 0.9.0) | Hardware tested (two scenarios); every other path offline only |
| Supervision, fallback profile, shadow check | Heartbeat, save/invalidate/compare a known-good profile, observe-only evaluation | Hardware tested (profile, heartbeat, and the shadow check, which is observe-only). **Restore/failback not implemented** |
| System Health | Home Assistant-side checks and reason codes | Hardware tested (on the reference installation's Home Assistant) |
| Intelligence V1 | Advisory, shadow-only; recommendations respect the effective battery reserve; no write path | Offline only |

## 6. Home Assistant integration

- **Packages** (`home-assistant/packages/`): helpers, template sensors, scripts, schedules, canonical telemetry, runtime configuration, health, the heartbeat, fallback status and operator-only wrappers. Plain YAML you deploy yourself; nothing is pushed to Home Assistant automatically.
- **Dashboard** and three **custom cards** (`frontend/`): live energy flow, energy actions, fallback/recovery review.
- **Contract:** Home Assistant sets staged values and presses buttons that exist as controller entities and actions. It cannot widen what the controller will do. The controller's write-enable switches restore to *off* at every boot.
- **Optional InfluxDB:** history and the learned Battery Outlook.
- **Prerequisites** such as extra custom cards, tariff and forecast integrations are installed by the user and are not bundled ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).

## 7. Intelligence advisory layer

`intelligence/` is a pure-Python (standard library) pipeline: read Home Assistant statistics read-only → learn usage → predict with uncertainty → recommend a target and a safe export amount → score the prediction later. It:

- imports no network, serial or process modules and has no control vocabulary (enforced by a static test; the one allow-listed exception is the developer preview tool, which runs a local Node.js process),
- writes only a report, optional read-only Home Assistant display sensors and its own SQLite scorecard file,
- is **shadow-only** in this release, with synthetic-data examples and tests.

The deterministic layer stays authoritative. If Intelligence is wrong, absent or turned off, nothing about the safety behaviour changes.

## 8. Proof, not just tests

- **Offline tests** are extensive (simulation, fault injection, static analysis of the firmware, host compile of headers, Home Assistant template tests, card tests). A proof-chain of pinned artifacts detects unintended changes.
- **Hardware proof** is recorded separately, per feature, and is the only thing that moves a feature from *offline only* to *hardware tested*. A green test run is never permission to write to hardware.

## 9. Future modularisation (direction, not a promise)

These are directions, not commitments, and none is implemented yet:

- Split the large single firmware YAML into reusable ESPHome packages and components, keeping the pure headers as the shared core.
- A tariff-adapter layer so the Home Assistant packages stop referencing specific integration entity ids.
- Per-inverter-family profiles, so register maps and write surfaces can be selected and proven independently.
- Separating the transaction engine behind a smaller, formally tested interface that other capabilities can reuse.
- Moving the user-reserve logic into one shared definition used by Home Assistant, Intelligence and, if justified, the firmware. Today only Intelligence resolves the reserve (`SiteConfig.effective_reserve()`); Dump-to-Grid and the Home Assistant scripts do not yet use it.
- Any step towards automatic control would need a separate design, review and hardware proof, and would remain subordinate to the deterministic layer.
