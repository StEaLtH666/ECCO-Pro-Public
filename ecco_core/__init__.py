"""ECCO core: the host-side reference model of state, freshness, device capability and write authority.

Pure, deterministic Python (standard library; PyYAML only to read the capability registry). It has no I/O of its own beyond
reading repository data files when asked, and it never talks to the inverter, the controller, Home Assistant or a network.
The ESP firmware is the only component that writes to the inverter; this package deliberately has no host-side write
transport, so nothing built on it can write either.

    state.py       Observation / Snapshot: raw, normalised and derived values kept apart, each with source and observation time
    freshness.py   one catalogue of the freshness limits the project already uses, per signal and purpose, with provenance;
                   a limit nobody has defined is UNRESOLVED, never guessed
    capability.py  device capabilities derived only from registry/inverter_capabilities.yaml; register addresses stay below
                   it; unsupported and unknown fail closed
    authority.py   the controller's write authority as reviewable data (checked against the firmware's own write surface)
                   and a pure decision model that executes nothing and never authorises an advisory origin
    bridge.py      the one crossing between system state and Intelligence: snapshot -> advisory inputs, advice -> records
                   that cannot be executed

See docs/architecture/MODULAR_ARCHITECTURE.md.
"""

CORE_VERSION = "ecco-core-0.1.0"
