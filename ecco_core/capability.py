"""Device capability layer: what the connected inverter and controller can do, in capability terms, from evidence only.

Feature, advisory and diagnostic code asks for a capability ("control.export_mode", "telemetry.battery_soc"); register
addresses, data types and scales stay below this layer, in the device profile. A capability's status comes ONLY from the
capability registry (registry/inverter_capabilities.yaml, the audited record of each register's meaning, access, write
policy and live proof):

    SUPPORTED    every record it rests on exists, has the access the capability needs, and is live-proven on the reference
                 installation (read proof for telemetry, write proof for control)
    UNSUPPORTED  a record a control capability needs is read-only or never-write in this firmware
    UNKNOWN      a record is missing, or its proof is unknown or only documented

Nothing is inferred from a read or a write that happened to succeed, and nothing here can upgrade a status. Separately,
`proof_on()` says on which controller variant a capability has actually been exercised (SUPPORTED_HARDWARE.md: H-001 the
classic ESP32, every write feature hardware tested; H-002 the ESP32-S3 wrapper, read-only operation hardware tested, write
features offline only).

ONE register layout is described: the Deye/Sunsynk-family single-phase low-voltage layout of the reference installation
(docs/dev/register-provenance.md). Nothing here claims any other model, firmware or layout; a second layout would be a
second profile built from its own evidence, not an edit of this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .state import DERIVED, NORMALIZED, RAW, Observation

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"

TELEMETRY = "telemetry"
CONTROL = "control"

HARDWARE_TESTED = "hardware_tested"
OFFLINE_ONLY = "offline_only"
NOT_PROVEN = "not_proven"

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry" / "inverter_capabilities.yaml"
PROFILE_NAME = "deye_sunsynk_1p_lv_reference"

# SUPPORTED_HARDWARE.md, rows H-001 / H-002: what has been exercised on each controller variant.
CONTROLLER_PROOF: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "esp32_classic": MappingProxyType({TELEMETRY: HARDWARE_TESTED, CONTROL: HARDWARE_TESTED}),
    "esp32s3": MappingProxyType({TELEMETRY: HARDWARE_TESTED, CONTROL: OFFLINE_ONLY}),
})

_TOU = tuple(f"tou_slot_{n}_{f}" for n in range(1, 7)
             for f in ("start_time", "end_time", "power", "target_soc", "charge_source", "mode"))


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    kind: str                         # TELEMETRY | CONTROL
    records: tuple[str, ...]          # capability-registry record ids it rests on
    description: str
    signal: str | None = None         # the state signal a telemetry capability provides


CAPABILITIES: tuple[CapabilitySpec, ...] = (
    CapabilitySpec("telemetry.battery_soc", TELEMETRY, ("battery_soc",), "battery state of charge", "battery.soc"),
    CapabilitySpec("telemetry.battery_power", TELEMETRY, ("battery_power",), "battery power", "battery.power"),
    CapabilitySpec("telemetry.house_power", TELEMETRY, ("house_load_power",), "house load power", "house.power"),
    CapabilitySpec("telemetry.pv_power", TELEMETRY, ("pv1_power", "pv2_power", "pv3_power", "pv4_power"),
                   "PV power, the sum of four strings", "pv.power"),
    CapabilitySpec("telemetry.grid_power", TELEMETRY, ("grid_power_ct_clamp",), "grid power at the CT clamp", "grid.power"),
    CapabilitySpec("telemetry.inverter_state", TELEMETRY, ("inverter_system_state",), "inverter system state",
                   "inverter.state"),
    # one control capability per write path the controller implements ...
    CapabilitySpec("control.clock", CONTROL, ("rtc_clock",), "inverter real-time clock correction"),
    CapabilitySpec("control.tou_schedule", CONTROL, _TOU + ("tou_global_grid_charge_enable",),
                   "manual six-slot time-of-use schedule"),
    CapabilitySpec("control.grid_charge", CONTROL, ("free_power_transaction", "grid_charge_current",
                                                     "tou_global_grid_charge_enable"), "temporary grid charging (Free Power)"),
    CapabilitySpec("control.export_mode", CONTROL, ("grid_export_policy",), "load / export mode (register 244 policy)"),
    CapabilitySpec("control.dump_to_grid", CONTROL, ("dump_to_grid_transaction",), "timed closed-loop export (Dump-to-Grid)"),
    # ... and two that look like controls but are read-only in this firmware, so a request for them fails closed
    CapabilitySpec("control.export_limit", CONTROL, ("export_limit",), "export power limit"),
    CapabilitySpec("control.battery_protection", CONTROL, ("battery_shutdown_soc", "battery_restart_soc",
                                                           "battery_low_warning_soc"), "battery shutdown / restart SOC"),
)
_BY_ID: Mapping[str, CapabilitySpec] = MappingProxyType({c.id: c for c in CAPABILITIES})


@dataclass(frozen=True)
class CapabilityStatus:
    capability: str
    status: str
    registers: frozenset[int]
    evidence: tuple[str, ...]          # each record's live-proof status, "record_id=status"
    reasons: tuple[str, ...]

    @property
    def supported(self) -> bool:
        return self.status == SUPPORTED


class CapabilityUnavailable(Exception):
    """A capability that is not SUPPORTED was required."""


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    """The capability registry's records by id (read-only). Fails loudly on an unexpected schema."""
    import yaml  # the only third-party import of the package, used only here

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 2 or not isinstance(data.get("capabilities"), list):
        raise ValueError(f"{path}: not a schema_version 2 capability registry")
    out: dict[str, dict] = {}
    for rec in data["capabilities"]:
        if rec["id"] in out:
            raise ValueError(f"{path}: duplicate record id {rec['id']!r}")
        out[rec["id"]] = rec
    return out


def _addresses(rec: Mapping) -> list[int]:
    return [int(r["address"]) for r in ((rec.get("modbus") or {}).get("registers") or [])]


class DeviceProfile:
    """One register layout, built from capability-registry records. Immutable after construction."""

    def __init__(self, records: Mapping[str, Mapping], name: str = PROFILE_NAME):
        self.name = name
        self._records = MappingProxyType({k: MappingProxyType(dict(v)) for k, v in records.items()})

    @classmethod
    def from_registry(cls, path: Path = REGISTRY_PATH) -> "DeviceProfile":
        return cls(load_registry(path))

    # --- status -------------------------------------------------------------------------------------------------------
    def status(self, capability: str) -> CapabilityStatus:
        spec = _BY_ID.get(capability)
        if spec is None:
            return CapabilityStatus(capability, UNKNOWN, frozenset(), (), ("not a capability this model knows",))
        regs: set[int] = set()
        evidence, unsupported, unknown = [], [], []
        for rid in spec.records:
            rec = self._records.get(rid)
            if rec is None:
                unknown.append(f"registry record {rid!r} is missing")
                evidence.append(f"{rid}=missing")
                continue
            proof = rec.get("live_proof_status")
            evidence.append(f"{rid}={proof}")
            addrs = _addresses(rec)
            regs.update(addrs)
            if not addrs:
                unknown.append(f"{rid}: no register identified")
            if spec.kind == CONTROL:
                if rec.get("current_access") != "read_write" or rec.get("write_policy") in ("R0", "WX"):
                    unsupported.append(f"{rid}: {rec.get('current_access')} / {rec.get('write_policy')} in this firmware")
                elif proof != "live_proven_write":
                    unknown.append(f"{rid}: write proof is {proof!r}")
            elif proof not in ("live_proven_read", "live_proven_write"):
                unknown.append(f"{rid}: read proof is {proof!r}")
        if unsupported:
            st, why = UNSUPPORTED, unsupported + unknown
        elif unknown:
            st, why = UNKNOWN, unknown
        else:
            st, why = SUPPORTED, ["every record is live-proven on the reference installation"]
        return CapabilityStatus(capability, st, frozenset(regs), tuple(evidence), tuple(why))

    def require(self, capability: str) -> CapabilityStatus:
        st = self.status(capability)
        if not st.supported:
            raise CapabilityUnavailable(f"{capability} is {st.status}: " + "; ".join(st.reasons))
        return st

    def proof_on(self, capability: str, variant: str) -> str:
        """HARDWARE_TESTED / OFFLINE_ONLY on that controller variant for a SUPPORTED capability; NOT_PROVEN otherwise
        (an unknown variant or a capability that is not supported is never proven)."""
        spec = _BY_ID.get(capability)
        if spec is None or variant not in CONTROLLER_PROOF or not self.status(capability).supported:
            return NOT_PROVEN
        return CONTROLLER_PROOF[variant][spec.kind]

    def registers(self, capability: str) -> frozenset[int]:
        """Device-specific detail for the layers below (and for tests); feature code should not need it."""
        return self.status(capability).registers

    def read_write_records(self) -> dict[str, frozenset[int]]:
        """Every registry record marked read_write, with its registers (the registry's view of the write surface)."""
        return {rid: frozenset(_addresses(r)) for rid, r in self._records.items() if r.get("current_access") == "read_write"}

    # --- decoding (simulation and diagnostics: register words -> observations) -----------------------------------------
    def decode(self, capability: str, words: Mapping[int, int], observed_at: datetime | None,
               source: str = "simulation") -> list[Observation]:
        """Observations for a SUPPORTED telemetry capability from raw 16-bit register words, using only the registry's
        declared data type, signedness and scale. A word that is missing or out of range, an unsupported capability or a
        data type this decoder does not handle yields an unavailable observation, never a guessed number."""
        spec = _BY_ID.get(capability)
        if spec is None or spec.kind != TELEMETRY:
            raise ValueError(f"{capability!r} is not a telemetry capability")
        st = self.status(capability)
        if not st.supported:
            return [Observation(spec.signal, None, observed_at, source, NORMALIZED, quality=(f"capability_{st.status}",))]
        if capability == "telemetry.pv_power":
            parts = []
            for n, rid in enumerate(spec.records, 1):
                parts.append(self._decode_record(rid, words, observed_at, source, f"pv.string_power.{n}"))
            total = None if any(p.value is None for p in parts) else float(sum(p.value for p in parts))
            return parts + [Observation("pv.power", total, observed_at, source, DERIVED,
                                        derived_from=tuple(p.signal for p in parts))]
        return [self._decode_record(spec.records[0], words, observed_at, source, spec.signal)]

    def _decode_record(self, rid: str, words: Mapping[int, int], observed_at: datetime | None, source: str,
                       signal: str) -> Observation:
        rec = self._records[rid]
        m = rec.get("modbus") or {}
        addrs = _addresses(rec)
        src = f"{source}:register:{addrs[0] if addrs else '?'}"
        word = words.get(addrs[0]) if len(addrs) == 1 else None
        if not isinstance(word, int) or isinstance(word, bool) or not 0 <= word <= 0xFFFF:
            return Observation(signal, None, observed_at, src, RAW, raw=word, quality=("word_missing_or_invalid",))
        dt = m.get("datatype")
        if dt in ("uint16", "int16"):
            v = word - 0x10000 if (dt == "int16" and word & 0x8000) else word
            scale = m.get("scale", 1)
            if isinstance(scale, bool) or not isinstance(scale, (int, float)):
                return Observation(signal, None, observed_at, src, RAW, raw=word, quality=("scale_not_numeric",))
            return Observation(signal, float(v * scale), observed_at, src, NORMALIZED, raw=word)
        if dt == "enum_uint16":
            label = (rec.get("enum_mapping") or {}).get(word)
            return Observation(signal, label, observed_at, src, NORMALIZED, raw=word,
                               quality=() if label is not None else ("enum_value_unknown",))
        return Observation(signal, None, observed_at, src, RAW, raw=word, quality=(f"datatype_{dt}_not_decoded",))


def inverter_healthy(state: Observation) -> Observation:
    """DERIVED: the inverter is known to be in normal operation. Only the 'normal' state counts; an unknown state is
    unknown (None), never healthy."""
    v = None if state.value is None else (state.value == "normal")
    return Observation("inverter.healthy", v, state.observed_at, state.source, DERIVED, derived_from=(state.signal,))
