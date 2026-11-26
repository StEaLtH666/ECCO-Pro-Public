# Gentle charging: what must be proven independently before any live actuation

Status: **nothing here actuates.** `planGentle` (`src/gentleController.ts`) and `adviseGentleRate` (`src/gentleAdvice.ts`) are read-only: pure data in, data
out, labelled "model, not a command", `actuationSupported: false`. They publish nothing and change no helper, schedule or mode. This page is the short list
of proofs that must exist, each by someone other than its author and each with the owner's own authorisation, before any code is allowed to apply a
recommended charge rate to a real inverter. It does not authorise any of them, and it is not a design for the actuator. The longer engineering list is
"Before an actuator, and the limits that remain" in `README.md`; this is the gate.

Today's firmware fixes the Free Power rate at START and verifies against it, so a recommended change cannot be applied at all.

## The proofs

1. **A guarded actuator exists, is reviewed, and is the only write path.** A Free Power rate controller on the Dump to Grid V1.1 pattern: the intended
   value saved durably before every write, read-back verification, a deadband and settle time, a write budget that counts EVERY write (the start and the
   safety decreases included), an owner pause that stops it at once, and fail closed on any unreadable state. Reviewed independently, with its failure
   modes tested offline first (lost reading, restart in the middle of a run, offline dongle, a clock-change night). The model's own limits (ceiling,
   grid cap, practical minimum, target never lowered) are enforced in the trusted backend, not only in the card.
2. **The inverter really takes a rate change mid-run, and the start-button bypass is closed or fenced.** Supervised proof, on one night with the owner
   present, that a change from outside during a lease neither blocks the automatic restore nor leaves the inverter at the wrong rate. The existing dongle
   Start-button bypass stays a blocker: no claim of full protection until it is resolved by its own decision.
3. **The setpoint basis is settled by measurement.** What a commanded watt value means (grid side, battery side, or amps at which voltage) is shown by
   commanded value against measured battery-side and grid-side power at several setpoints. If the measured charge power is ever above the configured
   maximum, the meaning of that configured figure must be explained first. Until then `setpointBasis` stays `UNSETTLED`.
4. **The response at low and middle rates is measured, not assumed.** Charging at the maximum rate says little about a lower one. A supervised series at several
   lower rates (the BMS does not override the rate, the charger holds it, the stored energy per kWh delivered, the charge efficiency at low power) must show
   the rate the model asks for is the rate the battery gets.
5. **The taper and the top of charge are measured over several full charges**, and the owner's configuration (not the repository defaults) takes the
   measured values: the SOC at which the rate begins to fall, the shape of the fall, the time the battery then needs to finish, the capacity band, the
   charge efficiency. The defaults stay deliberately conservative and generic.
6. **The safe limits are real and carry an age.** The live battery limits and any derating are readable with a time stamp (a ceiling with no age is trusted
   today); the real safe grid import limit is known; the household demand forecast has a measured error against the real demand; no solar is credited inside
   the hard grid limit until a measured forecast-skill gate exists.
7. **Shadow evidence on real nights, judged against criteria written down first.** The advice recorded beside what the battery actually does for a
   stretch of nights the owner sets (the offline replay tool is the first step): targets missed, at-risk flagged early enough to act on, no advice whenever
   data is missing or stale, the advised rate never above any limit, and the owner's review of the differences. Intelligence stays SHADOW until its own
   acceptance problems are resolved.
8. **A stop at the target exists** (Free Power has no SOC stop today: the model only says `stopRecommended`) and **the clock-change rulings are settled**
   (the repeated hour of an autumn change, the firmware START gate).
9. **A staged, reversible first live step.** The first live use is one supervised night, with its own backup and rollback verification, a way to return to
   today's fixed-rate behaviour in one step, a quiet window and no new exposed entity without the owner's decision. Each live step needs its own
   authorisation; passing CI, a replay or a review authorises nothing.

If any proof is missing, the controller stays read-only and the advice stays a display.
