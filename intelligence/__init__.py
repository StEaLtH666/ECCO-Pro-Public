"""ECCO INTELLIGENCE V1 - read -> learn -> predict -> recommend -> score.

SHADOW ONLY. This package never talks to an inverter, an ESP device, Home
Assistant or the network. It is a pure, deterministic library: the caller
supplies history and live inputs plus an explicit `now`, and gets back
predictions, recommendations and explanations. Nothing here can write a
register or arm/trigger any ECCO control. The deterministic ESP safety/control
layer stays authoritative.

See docs/intelligence/ECCO_INTELLIGENCE_V1_ARCHITECTURE.md.
"""

MODEL_VERSION = "intel-v1.0.0-shadow"
