# Evidence record: TOU slot 1 target SOC writes on the ESP32-S3 dongle (10-11 October 2026)

**Prepared:** 2026-10-12, read-only.
**Subject:** four owner-performed writes of TOU slot 1 target SOC on the live ESP32-S3 dongle, through the existing path:
Manual Configuration Write Enable → Load Current Slot 1 To Manual Staging → Apply Manual Slot 1 Settings.

This record supports Advanced Configuration Stage 0. Live proof of Stage 0 itself is still owed (see the live-proof procedure).

## Evidence classes

| Class | Meaning |
|---|---|
| **RAW** | a timestamped row in a Home Assistant history export pulled read-only on 2026-10-12 (GET `/api/history/period`, full attributes, `significant_changes_only=0`) |
| **DERIVED** | computed from RAW rows |
| **RETROSPECTIVE** | only in session notes or owner statements made at the time, or inferred from the firmware source; not in raw data |

**Private evidence bundle** (not in this repository; it contains site-specific entity ids):

| File | sha256 |
|---|---|
| raw history export | `cd8c2574a4ae0777110a68b0cefebc6df1e03517b4ce62216e92cc4f2df22e42` |
| pull metadata | `a70f03876b8146ecfcdb21b1453474d5656ab45e7aa0e2b143dc2c8e877c37f9` |
| derived timeline | `022dba56281ee6078b48c5369112afba5c97c01058623c39259a49beed0370c1` |

## Results (times BST)

| Write | Change | Apply → `VERIFIED OK` | Independent readback of the slot 1 SOC | Counters (attempts / successes / failures) | Class |
|---|---|---|---|---|---|
| 1, Sat 10 Oct | 100 → 40 % | 09:34:20.913 → 09:34:25.932 | 40 at 09:34:29.494 | 1 / 1 / 0 | RAW |
| 2, Sat 10 Oct | 40 → 100 % | 09:38:29.107 → 09:38:34.037 | 100 at 09:38:37.511 | 2 / 2 / 0 | RAW |
| 3, Sat 10 Oct | 100 → 40 % | 22:32:15.082 → 22:32:20.098 | 40 at 22:32:23.571 | 3 / 3 / 0 | RAW |
| 4, Sun 11 Oct | 40 → 100 % | 07:25:21.326 → 07:25:26.254 | 100 at 07:25:29.631 | 4 / 4 / 0 | RAW |

**Each write:**
- Load, then the staged SOC change, then arm, then Apply, then `Writing Slot1 0030-0530, 8000W, NN%, Grid/None, grid charge
  ON`, then Manual Write In Progress on, then `VERIFIED OK - manual Slot 1 settings match inverter readback`. (RAW)
- The write enable and the in-progress flag turned off in the same millisecond: the dongle disarmed itself. (RAW)
- An out-of-cycle configuration read showed the new SOC 3.4-3.6 s later. (RAW, plus a DERIVED interval)

**Other slot 1 fields:** start 00:30, end (slot 2 start) 05:30, power 8000 W, charge Grid, mode None, raw flags 1 and the
grid-charge bit had no change rows in any window. (RAW)
- The written frame states the same values. (RAW)
- So only the target SOC changed in effect. (DERIVED)
- The firmware still rewrites registers 232, 250, 251, 256, 268 and 274 with those values on every Apply. (RETROSPECTIVE,
  from the firmware source)

**Refused presses, no write** (RAW; these correct the session notes):
- 09:34:01.662, an Apply while not armed, refused with "arm … first".
- 09:38:13.318, an Apply without a Load, refused with "load current Slot 1 values into staging first".

**Fallback profile live match:**
- DRIFT `dx=00080` from 09:35:33 and 22:32:51; MATCH again at 09:38:53 and 07:26:50. (RAW)
- That `dx=00080` means register 268 only is RETROSPECTIVE.
- "DRIFT 22:32-07:25" is a span with short PAUSED_IO / UNKNOWN breaks overnight, not one unbroken interval. (RAW, from a
  secondary soak export)

## Gaps

- **No dongle log** was captured. The Modbus transactions are not directly observed; the evidence is the dongle's published
  result strings, counters and the later readback.
- **HA records only changes.** "Unchanged" means "no recorded change". An identical republished value leaves no row, for
  example the 07:25:00 Load result text.
- **Counters** publish about every 30 s and lag the write by 1.4-28.9 s. Twice, attempts were published after successes.
- **Who pressed** is not recorded by HA. Owner authorship rests on the owner's statements. (RETROSPECTIVE)
- **Firmware build:** the firmware source consulted is the repository's. The live S3 build is not proven byte-identical,
  although every result string observed matches it word for word.

## What this does and does not prove

**It shows (RAW):** on the live ESP32-S3, the existing slot 1 manual TOU path wrote and verified a target SOC change four
times, with a matching independent configuration read and no change to the other slot 1 fields.

**It does not show:**
- slots 2-6;
- an interrupted or partial write;
- concurrent changes by another Modbus master;
- Stage 0's own Home Assistant workflow.
