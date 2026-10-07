# Firmware: files, build and flashing

ESPHome firmware for the ECCO dongle: an ESP32 that talks to the inverter over RS485/Modbus (9600 8N1, UART on GPIO17 TX /
GPIO16 RX) and exposes telemetry, RTC correction and the guarded write transactions to Home Assistant.

**Read [SAFETY.md](../../SAFETY.md) before flashing.** This firmware can write inverter settings when its write-enable switches are
turned on. Start read-only.

## Files

| File | Status | Use |
|---|---|---|
| `firmware/ecco_clock_dongle_stage3_4_free_power.yaml` | current firmware, hardware-verified on the reference installation | flash this on a classic ESP32 dongle |
| `firmware/ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml` | hardware-only wrapper of the file above for an ESP32-S3 (N16R8) board | flash this instead on an ESP32-S3 |
| `firmware/include/*.h` | first-party C++ headers the firmware includes | not flashed on their own |
| `firmware/ecco_clock_dongle_stage3_2_manual_slot1.yaml`, `firmware/ecco_clock_dongle_stage3_3_manual_tou6.yaml` | **historical, do not flash** | kept only as fixtures that offline tests read and hash |
| `firmware/secrets.yaml.example` | template | copy to `secrets.yaml` (git-ignored) and fill in |

The S3 wrapper keeps the same node name (`ecco-clock-dongle`) as the classic firmware. Never run both dongles at once: two
nodes with one hostname, or two Modbus masters on one inverter bus, are not allowed.

## Build

ESPHome **2026.8.x only** (the firmware's `static_assert`s refuse 2026.9.0 and later). With your own `firmware/secrets.yaml`:

```
esphome config  firmware/ecco_clock_dongle_stage3_4_free_power.yaml
esphome compile firmware/ecco_clock_dongle_stage3_4_free_power.yaml
```

Use the `_esp32s3.yaml` file instead for an ESP32-S3 board. CI compiles both variants with placeholder secrets on every change
(`.github/workflows/validate.yml`).

### Dump-to-Grid command ceiling (build-time)

Dump-to-Grid never commands more battery discharge than `ecco_dump_controller_max_ceiling_w`. The default is 3000 W, the only
hardware-tested value. A different value is chosen when you build, never from Home Assistant:

```
esphome -s ecco_dump_controller_max_ceiling_w 6000 compile firmware/ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml
```

The build refuses any value that is not a plain decimal integer above 500 W, in 100 W steps, at most the site TOU power
ceiling and at most 8000 W. Read [docs/dev/dump-to-grid-ceiling.md](../dev/dump-to-grid-ceiling.md) before raising it: values above
3000 W are not hardware tested, and ECCO cannot check your battery, inverter, cabling or export permission.

## Pinned artifacts

The firmware YAML, its headers and `firmware/README.md` are pinned by sha256 and by exact-match reverters in the offline proof chain
(`registry/tests/_scope_chain.py`). Do not reformat or "tidy" them: a change must go through a declared chain entry, never a
silent re-hash. See [CONTRIBUTING.md](../../CONTRIBUTING.md).

Some comments inside these pinned files mention private development records (for example `CURRENT_STATE.md` or a
`docs/...` design note) that are not part of this repository, or use the shorthand "Deye protocol" for the register layout.
They are historical comments in hardware-verified source and are left byte-identical on purpose; see
[docs/dev/register-provenance.md](../../docs/dev/register-provenance.md).
