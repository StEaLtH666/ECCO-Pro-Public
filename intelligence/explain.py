"""Advice, confidence and explanation model for the ECCO Intelligence V1.1 advisors (SHADOW only).

Every V1.1 advisor (overnight.py, charge_target.py, events.py, dump_advice.py) returns one `Advice`: what it recommends or
why it will not, how confident it is and why, the assumptions it rests on, the conditions that block it, and how old each
input was. It is plain, immutable data a UI or a reviewer can read.

The structure cannot express an instruction. `mode` is always SHADOW and `applies_nothing` is always True (construction
fails otherwise); a BLOCKED advice carries no recommendation; an OK advice cannot coexist with a blocking condition or with
a required input that is stale or of unknown age. Confidence is a product of named factors, each with a sentence, so a low
score always says where it came from.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .usage import confidence_label

MODEL_VERSION_V11 = "intel-v1.1.0-foundation-shadow"

OK = "OK"                                  # a recommendation, with its confidence
BLOCKED = "BLOCKED"                        # a required input is stale / unknown / invalid, or a precondition fails
INSUFFICIENT = "INSUFFICIENT_DATA"         # too little evidence: at most a conservative fallback, flagged as such
STATUSES = (OK, BLOCKED, INSUFFICIENT)

FRESH = "fresh"
STALE = "stale"
UNKNOWN = "unknown"
NOT_REQUIRED = "not_required"


def finite_number(x: object) -> bool:
    """True for a real, finite int/float (bool is not a number here)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def nonneg_number(x: object) -> bool:
    """A finite number >= 0."""
    return finite_number(x) and x >= 0.0


# How much a demand figure's confidence label lets an advisor trust it (a missing label is treated as LOW).
LABEL_FACTOR = {"HIGH": 1.0, "MEDIUM": 0.8, "LOW": 0.55, "INSUFFICIENT": 0.0}


@dataclass(frozen=True)
class Reason:
    code: str
    text: str

    def to_dict(self) -> dict:
        return {"code": self.code, "text": self.text}


@dataclass(frozen=True)
class Blocker:
    """A condition that withholds the recommendation (fail closed)."""
    code: str
    text: str

    def to_dict(self) -> dict:
        return {"code": self.code, "text": self.text}


@dataclass(frozen=True)
class InputAge:
    """How old one input was when the advice was computed, judged against its own freshness limit."""
    name: str
    age_s: float | None
    max_age_s: float | None
    status: str
    required: bool
    note: str | None = None

    @staticmethod
    def assess(name: str, age_s: object, max_age_s: float | None, *, required: bool = True,
               note: str | None = None) -> "InputAge":
        """Fail closed: an age that is missing, non-finite, negative (clock skew), boolean or non-numeric is UNKNOWN,
        and a required input without a defined limit is UNKNOWN too (it cannot be shown to be fresh)."""
        if not required:
            age = float(age_s) if finite_number(age_s) and age_s >= 0 else None
            return InputAge(name, age, max_age_s, NOT_REQUIRED, False, note)
        if not finite_number(age_s) or age_s < 0:
            return InputAge(name, None, max_age_s, UNKNOWN, True, note or "age missing or invalid")
        if max_age_s is None:
            return InputAge(name, float(age_s), None, UNKNOWN, True, note or "no freshness limit is defined for this input")
        return InputAge(name, float(age_s), float(max_age_s), FRESH if age_s <= max_age_s else STALE, True, note)

    @property
    def blocks(self) -> bool:
        return self.required and self.status in (STALE, UNKNOWN)

    def to_dict(self) -> dict:
        return {"name": self.name, "age_s": self.age_s, "max_age_s": self.max_age_s, "status": self.status,
                "required": self.required, "note": self.note}


@dataclass(frozen=True)
class ConfidenceFactor:
    """One multiplicative effect on confidence, in [0, 1] (1 = no effect)."""
    name: str
    value: float
    text: str

    def to_dict(self) -> dict:
        return {"name": self.name, "value": round(self.value, 3), "text": self.text}


@dataclass(frozen=True)
class Confidence:
    score: float
    label: str
    factors: tuple[ConfidenceFactor, ...]

    @staticmethod
    def combine(factors: Iterable[ConfidenceFactor], cap_label: str | None = None) -> "Confidence":
        """Score = product of the factor values (each clipped to [0, 1]); label from the V1 scale (usage.confidence_label).
        `cap_label` caps the label (e.g. INSUFFICIENT when the evidence floor is not met, whatever the score)."""
        fs = tuple(factors)
        score = 1.0
        for f in fs:
            score *= min(1.0, max(0.0, f.value)) if finite_number(f.value) else 0.0
        label = confidence_label(score)
        order = ("INSUFFICIENT", "LOW", "MEDIUM", "HIGH")
        if cap_label is not None and order.index(cap_label) < order.index(label):
            label = cap_label
        return Confidence(score, label, fs)

    def to_dict(self) -> dict:
        return {"score": round(self.score, 3), "label": self.label, "factors": [f.to_dict() for f in self.factors]}


def _frozen_json(value: object) -> object:
    """Validate JSON-safety (finite numbers only; already-frozen mappings and tuples are fine) and return an immutable copy
    (tuples / read-only mappings). Anything else is a ValueError, never a TypeError from deep inside json."""
    try:
        json.dumps(_thawed(value), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"a recommendation must be strict JSON data: {exc}") from None
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _frozen_json(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_frozen_json(v) for v in value)
    return value


def _thawed(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: _thawed(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thawed(v) for v in value]
    return value


@dataclass(frozen=True)
class Advice:
    """One advisor's answer. Immutable; cannot represent an instruction (see the module docstring)."""
    kind: str
    status: str
    recommendation: Mapping | None
    confidence: Confidence
    reasons: tuple[Reason, ...] = ()
    assumptions: tuple[str, ...] = ()
    blocking: tuple[Blocker, ...] = ()
    inputs: tuple[InputAge, ...] = ()
    model_version: str = MODEL_VERSION_V11
    mode: str = "SHADOW"
    applies_nothing: bool = True

    def __post_init__(self) -> None:
        if self.mode != "SHADOW" or self.applies_nothing is not True:
            raise ValueError("Advice is shadow-only: mode must be SHADOW and applies_nothing True")
        if self.status not in STATUSES:
            raise ValueError(f"unknown Advice status {self.status!r}")
        if self.status == BLOCKED and (self.recommendation is not None or not self.blocking):
            raise ValueError("a BLOCKED advice names at least one blocker and carries no recommendation")
        if self.status != BLOCKED and self.blocking:
            raise ValueError("an advice with blocking conditions must be BLOCKED")
        if self.status == OK and any(i.blocks for i in self.inputs):
            raise ValueError("an OK advice cannot rest on a required input that is stale or of unknown age")
        if self.status == OK and self.recommendation is None:
            raise ValueError("an OK advice carries a recommendation")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "blocking", tuple(self.blocking))
        object.__setattr__(self, "inputs", tuple(self.inputs))
        if self.recommendation is not None:
            object.__setattr__(self, "recommendation", _frozen_json(self.recommendation))

    def to_dict(self) -> dict:
        return {"kind": self.kind, "status": self.status, "mode": self.mode, "applies_nothing": self.applies_nothing,
                "model_version": self.model_version,
                "recommendation": None if self.recommendation is None else _thawed(self.recommendation),
                "confidence": self.confidence.to_dict(), "reasons": [r.to_dict() for r in self.reasons],
                "assumptions": list(self.assumptions), "blocking": [b.to_dict() for b in self.blocking],
                "inputs": [i.to_dict() for i in self.inputs]}


def blocked(kind: str, blockers: Iterable[Blocker], inputs: Iterable[InputAge] = (), reasons: Iterable[Reason] = (),
            assumptions: Iterable[str] = ()) -> Advice:
    """A BLOCKED advice: no recommendation, confidence INSUFFICIENT, every blocker stated."""
    bl = tuple(blockers)
    conf = Confidence.combine([ConfidenceFactor("blocked", 0.0, "advice withheld: " + "; ".join(b.text for b in bl))])
    return Advice(kind, BLOCKED, None, conf, tuple(reasons), tuple(assumptions), bl, tuple(inputs))


def input_blockers(inputs: Iterable[InputAge]) -> list[Blocker]:
    """One blocker per required input that is stale or of unknown age."""
    out = []
    for i in inputs:
        if i.blocks:
            if i.status == STALE:
                out.append(Blocker(f"STALE_{i.name.upper()}",
                                   f"{i.name} is {i.age_s / 60:.0f} min old (limit {i.max_age_s / 60:.0f} min)"))
            else:
                out.append(Blocker(f"UNKNOWN_{i.name.upper()}", f"{i.name} has no usable age ({i.note})"))
    return out
