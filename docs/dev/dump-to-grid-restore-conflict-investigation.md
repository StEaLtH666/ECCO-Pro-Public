# Investigation brief: conflict-aware Dump to Grid restoration (NOT STARTED; no behaviour change)

**Raised by:** the Advanced Configuration write assessment (2026-10-12). The owner asked for a separate firmware / control
reliability investigation. Live restoration behaviour is unchanged.

## Finding

**Free Power's restore is conflict-aware.** Before writing its snapshot back, it re-reads the registers it owns. If a register
matches neither its snapshot nor the value it wrote, it does not write and waits for an operator decision
(firmware `restore_free_power_snapshot`, the review / force-restore / accept-current-state path).

**Dump to Grid's restore is not.** `restore_dump_to_grid_snapshot` writes register 244 and then 256-261 straight from the
durable snapshot, with no re-read first. Two things limit the damage today:
- the drift check while Dump is active (`dump_controller_tick`) ends Dump if those registers change underneath it;
- the owner editors refuse while Dump owns the registers. The Stage 0 edit refuses on Dump active, transaction or owed restore,
  and on the `obl=` lease field.

**Consequence:** a change made to 244 or 256-261 while a Dump restore is owed (for example after a reboot during Dump), by
another Modbus master or by a future editor that skipped the gates, would be overwritten silently by the restore.

## Questions for the investigation

1. Can `restore_dump_to_grid_snapshot` adopt Free Power's pattern:
   - re-read 244 and 256-261;
   - compare each with the snapshot and with the last values Dump wrote;
   - restore only when every register is in one of those two states;
   - otherwise hold, publish an operator-review state, and keep the obligation?
2. How does that interact with:
   - the export containment (`dump_lockout_containment`, which forces 244 to 2);
   - the controller tick's drift handling;
   - the reboot-time recovery?
3. Durable state: does the hold need a new marker phase, as Free Power's `RESTORE_VERIFIED_PENDING_CLEAR` did?
4. HA surface: an operator review / accept path. The existing Dump recovery buttons may cover it.
5. Proof: offline simulation (`registry/tests/_dump_sim.py`) of every interleaving, then a supervised live proof.

## Out of scope here

Any firmware change, any live test, and any change to the existing Dump to Grid restoration behaviour. Those need their own
reviewed branch.
