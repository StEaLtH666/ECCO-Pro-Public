"""The runtime self-test record (no homeassistant import; pure).

Each check has a short code and a level:

    PASS   the check holds
    INFO   a fact worth recording (versions, an ignored site hint); never a problem
    WARN   degraded but safe (for example the pause helper is missing: not paused, pause_control MISSING)
    FAIL   the integration publishes SELF_TEST_FAILED (all nulls) and computes nothing until the entry is reloaded

The envelope's own `self_test` attribute accepts only 'PASS' / 'FAIL: ...' (advisory_contract), so the published
SELF_TEST_FAILED envelope carries the FAIL checks; PASS / INFO / WARN appear in the integration's diagnostics download.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

PASS, INFO, WARN, FAIL = "PASS", "INFO", "WARN", "FAIL"
LEVELS = (PASS, INFO, WARN, FAIL)
MAX_CODE = 64
MAX_TEXT = 160


@dataclass(frozen=True)
class Check:
    code: str
    level: str
    text: str = ""

    def __post_init__(self) -> None:
        if not (isinstance(self.code, str) and 0 < len(self.code) <= MAX_CODE and self.code.upper() == self.code):
            raise ValueError("a check code is a short upper-case string")
        if self.level not in LEVELS:
            raise ValueError(f"a check level is one of {LEVELS}")

    @property
    def short(self) -> str:
        return str(self.text)[:MAX_TEXT]


class SelfTest:
    """An ordered record of checks; a later check with the same code replaces the earlier one."""

    def __init__(self, checks: tuple[Check, ...] = ()) -> None:
        self._checks: dict[str, Check] = {}
        for c in checks:
            self.add(c)

    def add(self, check: Check) -> "SelfTest":
        if not isinstance(check, Check):
            raise ValueError("only Check records are added")
        self._checks[check.code] = check
        return self

    def record(self, code: str, level: str, text: str = "") -> "SelfTest":
        return self.add(Check(code, level, text))

    def get(self, code: str) -> Check | None:
        return self._checks.get(code)

    @property
    def failed(self) -> bool:
        return any(c.level == FAIL for c in self._checks.values())

    def failures(self) -> Mapping[str, str]:
        """{code: text} of the FAIL checks: what self_test_failed_envelope publishes."""
        return MappingProxyType({c.code: c.short or "failed" for c in self._checks.values() if c.level == FAIL})

    def warnings(self) -> Mapping[str, str]:
        return MappingProxyType({c.code: c.short for c in self._checks.values() if c.level == WARN})

    def as_dict(self) -> dict[str, str]:
        """{code: 'PASS' | 'INFO: ...' | 'WARN: ...' | 'FAIL: ...'} for diagnostics."""
        return {c.code: (c.level if c.level == PASS else f"{c.level}: {c.short}") for c in self._checks.values()}
