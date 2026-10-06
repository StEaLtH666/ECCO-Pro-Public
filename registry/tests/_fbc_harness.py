"""FB-C1 (Failback Shadow) test harness.

Runs the REAL firmware lambdas - PR-A's ha_supervision_heartbeat action, PR-A's
1s supervision tick, PR-A's on_boot initialisation and FB-C1's own 1s interval
lambda - through registry/tests/_dump_sim.py's C++-subset transpiler, with the
pieces P-FBC-03a asks for:

  * millis_64()            - Sim.millis_64() in _dump_sim.py (a wrap-free 64-bit
                             clock; millis() is its low 32 bits)
  * TWO intervals          - the FB-C interval and the PR-A tick are scheduled
                             independently, each with its own initial phase
                             offset (ESPHome gives every interval a random
                             initial offset, scheduler.cpp) and optional
                             per-execution drift, with explicit order control
                             for same-millisecond ties
  * api_client_connected   - the template binary_sensor's `.state` modelled as
                             a settable entity
  * Z9 enforcement         - EVERY FB-C invocation is wrapped: only
                             failback_shadow_* globals may change, no Modbus /
                             NVS / script / durable event may occur, only the
                             five FB-C text sensors may be published and only
                             the allow-listed entities may be read

Self-tested by registry/tests/test_failback_shadow_core.py (section [H]). The
harness proves nothing about ESPHome timing or the compiled binary.
"""

from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _dump_sim as ds  # noqa: E402

FBC_TEXT_IDS = (
    "failback_shadow_state_text",
    "failback_shadow_episode_text",
    "failback_shadow_soak_text",
    "failback_shadow_verdict_text",
    "failback_shadow_inputs_text",
)
# Entities the FB-C tick may touch (Z9): its own five text sensors plus the
# read-only inputs of architecture S3 section 11.3 that are entities.
FBC_ACCESSIBLE_ENTITIES = frozenset(FBC_TEXT_IDS) | {"api_client_connected_sensor", "ntp_time"}


class Ref:
    """Stands in for ESPHome's StringRef action argument (`.str()`)."""

    def __init__(self, s: str):
        self.s = s

    def str(self):
        return ds.CStr(self.s)


# ---------------------------------------------------------------------------
# Extraction of the real lambdas
# ---------------------------------------------------------------------------
def heartbeat_lambda(fw: dict) -> str:
    hits = [a for a in fw["api"].get("actions", []) if a.get("action") == "ha_supervision_heartbeat"]
    assert len(hits) == 1
    then = hits[0]["then"]
    assert len(then) == 1 and set(then[0]) == {"lambda"}
    return then[0]["lambda"]


def pra_tick_lambda(fw: dict) -> str:
    """PR-A's supervision tick: the interval that mentions supervision_have_valid."""
    hits = [i for i in fw["interval"] if "supervision_have_valid" in yaml.dump(i["then"])]
    assert len(hits) == 1, "expected exactly one interval mentioning the PR-A have-valid flag"
    then = hits[0]["then"]
    assert len(then) == 1 and set(then[0]) == {"lambda"}
    return then[0]["lambda"]


def pra_init_lambda(fw: dict) -> str:
    lams = [a["lambda"] for a in fw["esphome"]["on_boot"]["then"] if "lambda" in a]
    hits = [b for b in lams if "random_uint32" in b]
    assert len(hits) == 1
    return hits[0]


def fbc_interval(fw: dict) -> dict:
    """The FB-C interval: the one that owns the readiness latch. (Selected by
    that unique global rather than by the bare prefix so a mutant that leaks
    `failback_shadow_*` into ANOTHER interval is still analysable - pin Z5
    reports the leak.)"""
    hits = [i for i in fw["interval"] if "failback_shadow_ready" in yaml.dump(i["then"])]
    assert len(hits) == 1, f"expected exactly one FB-C interval, found {len(hits)}"
    return hits[0]


def fbc_lambdas(fw: dict) -> tuple[str, str]:
    then = fbc_interval(fw)["then"]
    assert [list(a) for a in then] == [["lambda"], ["lambda"]]
    return then[0]["lambda"], then[1]["lambda"]


# ---------------------------------------------------------------------------
# Simulator with entity-access tracking
# ---------------------------------------------------------------------------
class TrackingSim(ds.Sim):
    def __init__(self, firmware: dict):
        super().__init__(firmware)
        self.accessed: set = set()
        self.track = False

    def ent(self, name):
        if self.track:
            self.accessed.add(name)
        return super().ent(name)


def other_globals(sim) -> dict:
    return {k: copy.copy(v) for k, v in sim.g.items() if not k.startswith("failback_shadow_")}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class Harness:
    NONCE = 0x12345678
    TIE_FBC_FIRST = "fbc_first"
    TIE_PRA_FIRST = "pra_first"

    def __init__(self, fw: dict, nonce: int | None = None, seed: int = 0, tie: str = TIE_FBC_FIRST,
                 fbc_offset_ms: int | None = None, pra_offset_ms: int | None = None, drift_ms: int = 0,
                 boot_ms: int = 0, trace: bool = False, enforce_z9: bool = True):
        self.fw = fw
        self.tie = tie
        self.drift_ms = drift_ms
        self.trace = trace
        self.enforce_z9 = enforce_z9
        self.rng = random.Random(seed)
        self._fbc0, self._fbc1 = fbc_lambdas(fw)
        self._pra = pra_tick_lambda(fw)
        self._hb = heartbeat_lambda(fw)
        self._init = pra_init_lambda(fw)
        self.fbc_invocations = 0
        self.violations: list[str] = []
        self.log: list = []
        self.beats_sent = 0
        self._beat_times: list[int] = []
        self._fbc_off, self._pra_off = fbc_offset_ms, pra_offset_ms
        self._boot(nonce if nonce is not None else self.NONCE, boot_ms)

    # -- boot / reboot -------------------------------------------------------
    def _boot(self, nonce: int, boot_ms: int = 0):
        self.nonce = nonce
        self.sim = TrackingSim(self.fw)
        self.sim.now_ms = boot_ms
        self.boot_ms = boot_ms
        # api_client_connected model: a settable binary sensor, False at boot.
        self.sim.ent("api_client_connected_sensor").set(False)
        self.sim.run_lambda(self._init.replace("random_uint32()", f"{nonce}u"))
        # Independent initial phase offsets, ESPHome-style: [0, min(interval/2, 5000)) ms.
        lo_f = self._fbc_off if self._fbc_off is not None else self.rng.randrange(0, 500)
        lo_p = self._pra_off if self._pra_off is not None else self.rng.randrange(0, 500)
        self.fbc_next = boot_ms + lo_f
        self.pra_next = boot_ms + lo_p
        self._beat_times = []

    def reboot(self, nonce: int | None = None, boot_ms: int = 0):
        """ESP reboot: all RAM (and the simulated clock) restart; a fresh boot
        nonce; new independent interval phase offsets. Nothing survives."""
        self._fbc_off = self._pra_off = None
        self._boot(nonce if nonce is not None else (self.nonce + 0x01010101) & 0xFFFFFFFF, boot_ms)

    # -- accessors -----------------------------------------------------------
    def g(self, name):
        return self.sim.g[name]

    @property
    def now(self) -> int:
        return self.sim.now_ms

    @property
    def uptime_ms(self) -> int:
        return self.sim.now_ms - self.boot_ms

    @property
    def challenge(self) -> str:
        return str(self.g("supervision_challenge"))

    def published(self, entity):
        return [str(v) for v in self.sim.ent(entity).published]

    def text(self, entity) -> str:
        st = self.sim.ent(entity).state
        return "" if isinstance(st, float) else str(st)

    def fbc_publish_counts(self) -> dict:
        return {e: len(self.sim.ent(e).published) for e in FBC_TEXT_IDS}

    def set_client(self, connected: bool):
        self.sim.ent("api_client_connected_sensor").set(bool(connected))

    def set_ntp(self, valid: bool, epoch: int | None = None):
        self.sim.ntp_valid = valid
        self.sim.g["ntp_synced"] = valid
        if epoch is not None:
            self.sim.epoch = epoch

    # -- the ticks (each usable on its own for order-specific tests) ---------
    def pra_tick(self):
        self.sim.run_lambda(self._pra)
        if self.trace:
            self.log.append((self.sim.now_ms, "pra"))

    def fbc_tick(self):
        s = self.sim
        if self.enforce_z9:
            gbefore = other_globals(s)
            m0, n0, c0, l0, e0, x0 = (len(s.modbus_log), dict(s.nvs), len(s.nvs_commits), len(s.nvs_loads),
                                      len(s.events), len(s.executed))
            pub0 = {k: len(v.published) for k, v in s.entities.items()}
            s.accessed = set()
            s.track = True
        s.run_lambda(self._fbc1)
        if self.enforce_z9:
            s.track = False
            gafter = other_globals(s)
            changed = sorted(k for k in gafter if gafter[k] != gbefore.get(k))
            if changed:
                self.violations.append(f"t={s.now_ms}: FB-C changed non-FB globals {changed}")
            if len(s.modbus_log) != m0:
                self.violations.append(f"t={s.now_ms}: FB-C touched the Modbus log")
            if s.nvs != n0 or len(s.nvs_commits) != c0 or len(s.nvs_loads) != l0 or len(s.events) != e0:
                self.violations.append(f"t={s.now_ms}: FB-C touched NVS / the durable event timeline")
            if len(s.executed) != x0:
                self.violations.append(f"t={s.now_ms}: FB-C executed a script")
            pubbed = sorted(k for k, v in s.entities.items() if len(v.published) != pub0.get(k, 0))
            if not set(pubbed) <= set(FBC_TEXT_IDS):
                self.violations.append(f"t={s.now_ms}: FB-C published {pubbed}")
            bad = sorted(s.accessed - FBC_ACCESSIBLE_ENTITIES)
            if bad:
                self.violations.append(f"t={s.now_ms}: FB-C accessed entities {bad}")
        self.fbc_invocations += 1
        if self.trace:
            self.log.append((s.now_ms, "fbc"))

    def heartbeat(self, challenge: str):
        self.sim.run_lambda(self._hb, {"challenge": Ref(challenge)}, params=("challenge",))

    def beat(self):
        """A valid heartbeat right now (echoes the current challenge)."""
        self.heartbeat(self.challenge)
        self.beats_sent += 1
        if self.trace:
            self.log.append((self.sim.now_ms, "beat"))

    # -- scheduler -----------------------------------------------------------
    def schedule_beats(self, times_ms):
        """Absolute sim times (ms) at which a valid heartbeat arrives."""
        self._beat_times = sorted(set(self._beat_times) | set(int(t) for t in times_ms))

    def schedule_beats_every(self, start_ms: int, every_ms: int, until_ms: int):
        self.schedule_beats(range(start_ms, until_ms + 1, every_ms))

    def _next_delta(self) -> int:
        return 1000 + (self.rng.randrange(0, self.drift_ms + 1) if self.drift_ms else 0)

    def run_until(self, t_end_ms: int):
        """Executes every scheduled event with time <= t_end_ms, in time order.
        Ties: an arriving heartbeat first, then the two ticks in `tie` order."""
        while True:
            cands = []
            if self._beat_times:
                cands.append((self._beat_times[0], 0, "beat"))
            fp = 1 if self.tie == self.TIE_FBC_FIRST else 2
            pp = 2 if self.tie == self.TIE_FBC_FIRST else 1
            cands.append((self.fbc_next, fp, "fbc"))
            cands.append((self.pra_next, pp, "pra"))
            t, _, what = min(cands)
            if t > t_end_ms:
                break
            self.sim.now_ms = max(self.sim.now_ms, t)
            if what == "beat":
                self._beat_times.pop(0)
                self.beat()
            elif what == "fbc":
                self.fbc_tick()
                self.fbc_next = t + self._next_delta()
            else:
                self.pra_tick()
                self.pra_next = t + self._next_delta()
        self.sim.now_ms = max(self.sim.now_ms, t_end_ms)

    def run(self, ms: int):
        self.run_until(self.sim.now_ms + ms)

    def jump_to(self, t_ms: int):
        """Leaps the simulated clock forward WITHOUT executing the skipped
        ticks (for millis()-wrap scenarios at ~49.7 days of uptime). Only valid
        when nothing relevant happens in the skipped span; both intervals are
        re-phased from the new time."""
        assert t_ms >= self.sim.now_ms
        off_f = self.fbc_next - self.sim.now_ms if self.fbc_next >= self.sim.now_ms else 0
        off_p = self.pra_next - self.sim.now_ms if self.pra_next >= self.sim.now_ms else 0
        self.sim.now_ms = t_ms
        self.fbc_next = t_ms + off_f
        self.pra_next = t_ms + off_p

    # -- lock-step helper (one FB-C tick and one PR-A tick per second) -------
    def step(self, ms: int = 1000, order: str | None = None):
        """Advances `ms`, then runs the two ticks once in the given order
        ('fbc_first' | 'pra_first'). Used by order-specific scenarios."""
        order = order or self.tie
        self.sim.now_ms += ms
        if order == self.TIE_FBC_FIRST:
            self.fbc_tick()
            self.pra_tick()
        else:
            self.pra_tick()
            self.fbc_tick()

    # -- episode record (for comparisons) -------------------------------------
    EPISODE_FIELDS = (
        "ready", "phase", "ep", "ep_trigger", "ep_edge_ms", "ep_last_edge_ms", "ep_edge_uptime_s",
        "ep_edge_epoch", "ep_client_at_edge", "ep_reboot_margin_s", "ep_return_s", "ep_return_gap_ms",
        "ep_relost", "ep_close_s", "ep_fbf",
    )

    def episode(self) -> dict:
        return {f: self.g("failback_shadow_" + f) for f in self.EPISODE_FIELDS}

    def parse_kv(self, entity: str) -> dict:
        out = {}
        for part in self.text(entity).split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out
