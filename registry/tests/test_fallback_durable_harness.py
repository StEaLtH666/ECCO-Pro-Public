#!/usr/bin/env python3
"""FB-B0 - self-tests of registry/tests/_fbb_harness.py (Phase-0 style).

The FB-B harness is only as trustworthy as its own model of NVS and of the
firmware runtime, so every feature is exercised here against its
specification before any suite relies on it (architecture 11.1; S1 P-B4;
S6 BLK-07/18/42/43; S2 Part A m16):

  [1] DirectNvs: decimal keys, the two-step read and its side effects
      (CRC-erase -> NOT_FOUND -> ESP_FAIL -> ABSENT), size probe, capacity,
      handle 0, NOT_INITIALIZED, queued read errors, cross-key erase, the
      between-read-steps and after-set hooks, INVALID page health, power cuts
      before / after every event;
  [2] per-key write faults (result code x visible state x next-boot state x
      health) and the next-boot resolver, IDF init clean-up, init-time loss,
      partition wipe; strictness on unmodelled faults;
  [3] ESPHome's pending preference queue and the queue-presence tripwire,
      plus the ecco_durable tripwire on a _dump_sim.Sim;
  [4] the shared scenario runner (the host fault driver's Python side);
  [5] FB record / aggregate value semantics (C widths, arrays, copies);
  [6] FbbSim: strict global types (the REAL firmware loads - scalars and, from
      FB-B1, std::array globals; an unknown struct type raises instead of
      reading 0), FB record globals, the
      ecco_fallback:: / ecco_fbdurable:: adapter through transpiled lambdas,
      `name.field[i]` / `id(g).field` stores, is_running(), wait_until
      timeouts, delay, background tasks, the Modbus hub model.

No I/O beyond reading repository files, no hardware.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402
import _dump_sim as ds  # noqa: E402
import _fbb_harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def raises(fn, exc) -> BaseException | None:
    try:
        fn()
    except exc as e:
        return e
    return None


GOLD7 = fp.seal_profile(fp.blank_profile(
    magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
    reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30], reg274_279=[1, 0, 1, 0, 0, 1],
    reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1,
    reserved0=0, reserved1=0, binding=0))
PB = fp.pack_profile(GOLD7)
K_P, K_W = fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_KEY
W7 = fd.pack_provision(fd.make_provision(7, GOLD7["binding"], 6, 0x6666, K_P, 1, fd.PROV_OP_SAVE))

# ===========================================================================
print("[1] DirectNvs: keys, two-step read, read side effects, hooks, health, power cuts")
# ===========================================================================
n = H.DirectNvs()
n.put(K_P, PB)
e1 = n.get_blob(K_P, None)
e2 = n.get_blob(K_P, 96)
check("size probe returns (OK, length, no data); the data read returns the bytes; the op log uses ESPHome's decimal "
      "key string", e1 == (fd.IDF_OK, 96, None) and e2 == (fd.IDF_OK, 96, PB)
      and n.ops == [("get", "1609458070", 0), ("read", "1609458070", 0)])
check("a too-small capacity returns INVALID_LENGTH with the stored length (no data)",
      n.get_blob(K_P, 48) == (fd.IDF_ERR_NVS_INVALID_LENGTH, 96, None))
check("an absent key returns NOT_FOUND on the probe", n.get_blob(K_W, None)[0] == fd.IDF_ERR_NVS_NOT_FOUND)
n = H.DirectNvs()
n.put(K_P, PB, crc_ok=False)
chain = [n.get_blob(K_P, None)[0], n.get_blob(K_P, 96)[0], n.get_blob(K_P, None)[0], n.get_blob(K_P, 96)[0],
         n.get_blob(K_P, None)[0]]
check("read side effects (architecture 11.1): CRC-bad chunk -> probe OK, data read ERASES the chunk and returns "
      "NOT_FOUND; the index survives (probe OK); the next data read erases the index and returns ESP_FAIL; then ABSENT",
      chain == [fd.IDF_OK, fd.IDF_ERR_NVS_NOT_FOUND, fd.IDF_OK, fd.IDF_FAIL, fd.IDF_ERR_NVS_NOT_FOUND], str(chain))
loads = []
n = H.DirectNvs()
n.put(K_P, PB, crc_ok=False)
for _ in range(3):
    loads.append(fd.read_direct(n, K_P, 96)[0])
check("...so read_direct gives READ_ERROR, READ_ERROR, then ABSENT: a same-step retry would convert an unreadable "
      "record into 'absent' (why reads are never retried and the read latch exists)",
      loads == [fp.LOAD_READ_ERROR, fp.LOAD_READ_ERROR, fp.LOAD_ABSENT], str(loads))
n = H.DirectNvs()
n.put(K_P, PB, chunk_present=False)
check("a missing chunk (N9): probe OK, data read erases the index and returns ESP_FAIL",
      (n.get_blob(K_P, None)[0], n.get_blob(K_P, 96)[0], K_P in n.blobs) == (fd.IDF_OK, fd.IDF_FAIL, False))
n0 = H.DirectNvs(handle=0)
n0.put(K_P, PB)
check("handle 0: every get and set returns INVALID_HANDLE and changes nothing; read_direct reports STORAGE_UNAVAILABLE",
      n0.get_blob(K_P, None)[0] == fd.IDF_ERR_NVS_INVALID_HANDLE and n0.set_blob(K_P, bytes(96)) == fd.IDF_ERR_NVS_INVALID_HANDLE
      and n0.blobs[K_P].data == PB and fd.read_direct(n0, K_P, 96)[0] == fp.LOAD_STORAGE_UNAVAILABLE)
n = H.DirectNvs()
n.put(K_P, PB)
n.unavailable = True
check("storage not initialised: reads return NOT_INITIALIZED (read_direct: STORAGE_UNAVAILABLE)",
      n.get_blob(K_P, None)[0] == fd.IDF_ERR_NVS_NOT_INITIALIZED and fd.read_direct(n, K_P, 96)[0] == fp.LOAD_STORAGE_UNAVAILABLE)
n = H.DirectNvs()
n.put(K_P, PB)
n.read_faults[K_P] = [fd.IDF_ERR_FLASH_OP_FAIL, fd.IDF_OK]
check("queued read faults: one injected flash error, then a clean read",
      [fd.read_direct(n, K_P, 96)[0], fd.read_direct(n, K_P, 96)[0]] == [fp.LOAD_READ_ERROR, fp.LOAD_OK])
n = H.DirectNvs()
n.put(K_P, PB)
n.put(K_W, W7)
n.poisoned.add(K_W)
first = n.get_blob(K_P, None)[0]
check("cross-key erase: a scan triggered by reading FBP erases a poisoned FBW entry (another key's inconsistency)",
      first == fd.IDF_OK and K_W not in n.blobs and not n.poisoned)
n = H.DirectNvs()
n.put(K_P, PB)
n.between_read_steps = lambda nv, key: nv.blobs.pop(key, None)
check("between-read-steps hook (interleaved Wi-Fi GC / IntervalSyncer): the key vanishes between probe and data read "
      "-> NOT_FOUND on the data step -> READ_ERROR (not ABSENT)", fd.read_direct(n, K_P, 96)[0] == fp.LOAD_READ_ERROR)
seen = []
n = H.DirectNvs()
n.after_set = lambda nv, key: seen.append(fd.decimal_key(key))
n.set_blob(K_W, W7)
n.set_blob(K_P, PB)
check("after-set hook runs after every set, in order (witness first here)", seen == ["1000595297", "1609458070"])
n = H.DirectNvs()
check("get_stats: OK while healthy; INVALID_STATE with an INVALID page", n.get_stats() == fd.IDF_OK
      and (setattr(n, "healthy", False) or n.get_stats() == fd.IDF_ERR_INVALID_STATE))
cut_points = {}
for cut in range(0, 6):
    n = H.DirectNvs()
    n.put(K_P, PB)
    n.cut_at = cut
    try:
        n.get_stats()
        n.set_blob(K_W, W7)
        n.get_blob(K_W, None)
        cut_points[cut] = "none"
    except H.PowerCut:
        cut_points[cut] = (n.events, K_W in n.blobs, n.set_count())
check("power cut point 2n is BEFORE event n and 2n+1 AFTER it (events: get_stats, set_blob, get_blob): cut 2 = before "
      "the set (nothing written), cut 3 = after the set (FBW written, counted)",
      cut_points == {0: (0, False, 0), 1: (0, False, 0), 2: (1, False, 0), 3: (1, True, 1), 4: (2, True, 1),
                     5: (2, True, 1)}, str(cut_points))
check("state_of renders ABS / OK / CRCBAD / NOCHUNK with the length and the FNV-1a-64 of the bytes",
      H.DirectNvs().state_of(K_P) == "ABS" and (lambda nv: (nv.put(K_P, PB), nv.state_of(K_P))[1])(H.DirectNvs())
      == f"OK:96:{H.fnv64_hex(PB)}" and (lambda nv: (nv.put(K_P, PB, crc_ok=False), nv.state_of(K_P))[1])(H.DirectNvs())
      .startswith("CRCBAD:96:") and (lambda nv: (nv.put(K_P, PB, chunk_present=False), nv.state_of(K_P))[1])(H.DirectNvs())
      .startswith("NOCHUNK:96:"))

# ===========================================================================
print("[2] Write faults, next-boot resolver, init clean-up, wipe")
# ===========================================================================
NEW = fd.pack_provision(fd.make_provision(8, 0x88, 7, GOLD7["binding"], K_P, 1, fd.PROV_OP_SAVE))
OTHER = fd.pack_provision(fd.make_provision(99, 0x99, 98, 0x98, K_P, 1, fd.PROV_OP_SAVE))


def after_fault(fault: H.WriteFault, prior=W7):
    nv = H.DirectNvs()
    if prior is not None:
        nv.put(K_W, prior)
    nv.faults[K_W] = [fault]
    r = nv.set_blob(K_W, NEW)
    return nv, r


VIS_EXPECT = {
    H.VIS_NEW: ("OK", NEW), H.VIS_OLD: ("OK", W7), H.VIS_ABSENT: ("ABS", None), H.VIS_CRCBAD: ("CRCBAD", NEW),
    H.VIS_NOCHUNK_OLD: ("NOCHUNK", W7), H.VIS_OTHER: ("OK", OTHER), H.VIS_WRONGSIZE: ("OK", bytes(52)),
    H.VIS_UNAVAILABLE: ("OK", NEW),
}
bad_vis = []
for vis, (tag, data) in VIS_EXPECT.items():
    nv, r = after_fault(H.WriteFault(fd.IDF_ERR_TIMEOUT, vis, other=OTHER if vis == H.VIS_OTHER else b"",
                                     wrong_len=52 if vis == H.VIS_WRONGSIZE else 0))
    st = nv.state_of(K_W)
    if r != fd.IDF_ERR_TIMEOUT or (st != "ABS" if tag == "ABS" else st != f"{tag}:{len(data)}:{H.fnv64_hex(data)}"):
        bad_vis.append((vis, st))
    if vis == H.VIS_UNAVAILABLE and nv.get_blob(K_W, None)[0] != fd.IDF_ERR_NVS_NOT_INITIALIZED:
        bad_vis.append(("unavailable reads", vis))
check("every visible post-write state (NEW, OLD, ABSENT, CRCBAD, NOCHUNK_OLD, OTHER, WRONGSIZE, UNAVAILABLE) is what "
      "a readback then sees, independent of the returned code (here TIMEOUT)", not bad_vis, str(bad_vis))
nv, _r = after_fault(H.WriteFault(fd.IDF_OK, H.VIS_NOCHUNK_OLD), prior=None)
check("NOCHUNK_OLD without an old record leaves the key absent", nv.state_of(K_W) == "ABS")
check("strict: an unknown visible / boot state, OTHER bytes of the wrong size and a WRONGSIZE of the record's own size "
      "raise FbbNotModelled",
      raises(lambda: H.WriteFault(visible="LANDED_SOMEWHERE"), H.FbbNotModelled) is not None
      and raises(lambda: H.WriteFault(boot="MAYBE"), H.FbbNotModelled) is not None
      and raises(lambda: after_fault(H.WriteFault(fd.IDF_OK, H.VIS_OTHER, other=b"x")), H.FbbNotModelled) is not None
      and raises(lambda: after_fault(H.WriteFault(fd.IDF_OK, H.VIS_WRONGSIZE, wrong_len=48)), H.FbbNotModelled) is not None)
nv, _r = after_fault(H.WriteFault(fd.IDF_OK, H.VIS_NEW, healthy_after=False))
check("a write can leave an INVALID page: get_stats fails for the rest of the boot, and a reboot clears the RAM state",
      nv.get_stats() == fd.IDF_ERR_INVALID_STATE and nv.reboot().get_stats() == fd.IDF_OK)
boot = {}
for b in H.BOOT_STATES:
    nv, _r = after_fault(H.WriteFault(fd.IDF_ERR_TIMEOUT, H.VIS_OLD, b))
    boot[b] = nv.reboot().state_of(K_W)
check("next-boot resolver: ASIS keeps the end-of-boot state (OLD here), NEW lands the written bytes, OLD restores the "
      "prior, ABSENT loses the key",
      boot == {H.BOOT_ASIS: f"OK:48:{H.fnv64_hex(W7)}", H.BOOT_NEW: f"OK:48:{H.fnv64_hex(NEW)}",
               H.BOOT_OLD: f"OK:48:{H.fnv64_hex(W7)}", H.BOOT_ABSENT: "ABS"}, str(boot))
nv, _r = after_fault(H.WriteFault(fd.IDF_ERR_TIMEOUT, H.VIS_OLD, H.BOOT_OLD), prior=None)
check("BOOT_OLD after a first write (no prior) resolves to ABSENT", nv.reboot().state_of(K_W) == "ABS")
nv = H.DirectNvs()
nv.put(K_P, PB, chunk_present=False)
nv.put(K_W, W7, crc_ok=False)
rb = nv.reboot()
check("IDF init clean-up at reboot: an index whose chunk is missing is erased; a CRC-bad chunk survives until read",
      rb.state_of(K_P) == "ABS" and rb.state_of(K_W).startswith("CRCBAD:"))
nv = H.DirectNvs()
nv.put(K_P, PB)
nv.put(K_W, W7)
nv.healthy, nv.unavailable, nv.faults[K_P] = False, True, [H.WriteFault()]
rb = nv.reboot(absent_keys=(K_P,))
check("reboot(absent_keys) models an init-time loss (F11 duplicate-hash erase); RAM state (health, unavailable, "
      "queued faults, hooks, cut) resets", rb.state_of(K_P) == "ABS" and rb.state_of(K_W).startswith("OK:")
      and rb.healthy and not rb.unavailable and not rb.faults and rb.cut_at is None)
check("wipe(): ESPHome's whole-partition erase after a failed nvs_open leaves nothing", H.DirectNvs.wipe().blobs == {})

# ===========================================================================
print("[3] ESPHome pending preference queue and the tripwires")
# ===========================================================================
nv = H.DirectNvs()
prefs = H.EspHomePrefs(nv)
prefs.save(123, b"\x01\x02")
prefs.save(123, b"\x03\x04")
prefs.save(456, b"\x05")
check("save() only queues (same key replaces; nothing reaches flash) and load() serves the QUEUE first",
      not nv.blobs and prefs.load(123, 2) == b"\x03\x04" and prefs.load(123, 3) is None)
nv.faults[456] = [H.WriteFault(fd.IDF_ERR_NVS_NOT_ENOUGH_SPACE, H.VIS_OLD)]
ok = prefs.sync()
check("sync() flushes EVERY queued key, clears the queue even on failure and returns one aggregate result",
      ok is False and not prefs.pending and nv.state_of(123).startswith("OK:2:") and nv.state_of(456) == "ABS"
      and prefs.sync_count == 1)
check("load() after sync reads flash through the two-step read", prefs.load(123, 2) == b"\x03\x04" and prefs.load(789, 1) is None)
trips = [raises(lambda k=k: prefs.save(k, b"x"), H.FbbTripwire) is not None for k in
         (K_P, K_W, fd.FAILBACK_STATE_KEY, fp.FALLBACK_PROFILE_TAG, fd.FAILBACK_PROVISION_TAG, "1609458070")]
check("queue-presence tripwire: save/load of an FB key (as int, tag or decimal string) raises FbbTripwire",
      all(trips) and raises(lambda: prefs.load(K_W, 48), H.FbbTripwire) is not None, str(trips))
FW = ds.load_firmware(FIRMWARE_PATH)
dsim = ds.Sim(FW)
H.install_durable_tripwire(dsim)
rec = ds.Record("DumpToGridSnapshotData") if hasattr(ds, "Record") else None
blocked = [raises(lambda k=k: dsim.D.commit_record(k, rec), H.FbbTripwire) is not None
           for k in (fp.FALLBACK_PROFILE_TAG, fd.FAILBACK_PROVISION_TAG, K_P, "2156168643")]
check("durable tripwire on a _dump_sim.Sim: ecco_durable::commit_record / load_record / load_record_status naming an FB "
      "tag or key raise (runtime twin of X3); other tags pass through untouched",
      all(blocked) and raises(lambda: dsim.D.load_record(fd.FAILBACK_PROVISION_TAG, rec), H.FbbTripwire) is not None
      and raises(lambda: dsim.D.load_record_status(K_P, rec), H.FbbTripwire) is not None
      and dsim.D.load_record(ds.Durable.DUMP_TO_GRID_VALID_TAG, rec) is False, str(blocked))

# ===========================================================================
print("[4] The shared scenario runner")
# ===========================================================================
G8 = fp.seal_profile(dict(GOLD7, generation=8, captured_epoch=1790086400))
W8 = fd.pack_provision(fd.make_provision(8, G8["binding"], 7, GOLD7["binding"], K_P, 1, fd.PROV_OP_SAVE))
sc = H.Scenario("probe", (H.PRIOR_OK, PB), (H.PRIOR_OK, W7), fp.pack_profile(G8), W8)
line = H.run_scenario(sc)
check("run_scenario: a clean recapture commits both keys, witness first (2 sets), next boot VALID / NONE via B10",
      line.startswith("probe ld=0/0 sets=2 ") and " txn=1 ref=1 " in line and " boot=5/0/10 " in line
      and f"fp=OK:96:{H.fnv64_hex(fp.pack_profile(G8))}" in line and f"fw=OK:48:{H.fnv64_hex(W8)}" in line, line)
cut = H.run_scenario(H.Scenario("cut", (H.PRIOR_OK, PB), (H.PRIOR_OK, W7), fp.pack_profile(G8), W8, cut=3))
check("a power cut right after the FBW set leaves FBW new and FBP old: next boot PROFILE_STALE / INTERRUPTED (B12)",
      cut.endswith(" txn=CUT latch=0") and " boot=8/1/12" in cut and " sets=1 " in cut, cut)
h0 = H.run_scenario(H.Scenario("h0", (H.PRIOR_OK, PB), (H.PRIOR_OK, W7), fp.pack_profile(G8), W8, handle_at_commit=0))
check("handle_at_commit: reads with a valid handle, commit with handle 0 -> refused STORAGE_UNAVAILABLE, nothing written",
      " txn=3 ref=4 " in h0 and " sets=0 " in h0, h0)
init = H.scenario_cxx_initializer(sc)
check("scenario_cxx_initializer renders the same scenario as a C++ aggregate (name, both priors as hex, the new "
      "records, handle, health, latch, 2 fault slots, cut, boot mask, wipe, handle_at_commit)",
      init.startswith('{"probe", {1, "') and init.endswith(", -1, 0, 0, -1}") and PB.hex() in init and W8.hex() in init
      and init.count("{0, 0, 0, 0, 1, \"\", 0u}") == 2, init[-120:])
check("strict: an unknown prior kind raises FbbNotModelled",
      raises(lambda: H.run_scenario(H.Scenario("x", (9, b""), (H.PRIOR_ABSENT, b""), b"", b"")), H.FbbNotModelled) is not None)

# ===========================================================================
print("[5] FB record / aggregate value semantics")
# ===========================================================================
r = H.FbRecord("FallbackProfileV1")
r.reg244 = 0x1FFFF
r.generation = -1
r.set_elem("reg256_261", 2, 70000)
check("C widths on every store: u16 0x1FFFF -> 0xFFFF, u32 -1 -> 0xFFFFFFFF, array element 70000 -> 4464",
      (r.reg244, r.generation, r.reg256_261[2]) == (0xFFFF, 0xFFFFFFFF, 4464))
check("strict: unknown field, wrong array length, out-of-range index, scalar indexing and an unknown record kind raise",
      raises(lambda: setattr(r, "nope", 1), H.FbbNotModelled) is not None
      and raises(lambda: setattr(r, "reg256_261", [1, 2]), H.FbbNotModelled) is not None
      and raises(lambda: r.set_elem("reg256_261", 6, 1), H.FbbNotModelled) is not None
      and raises(lambda: r.set_elem("reg244", 0, 1), H.FbbNotModelled) is not None
      and raises(lambda: H.FbRecord("FooV1"), H.FbbNotModelled) is not None)
w = H.FbRecord("FailbackProvisionV1", fd.PROVISION_MAGIC, 1, 48, 3)
check("brace-init fills fields in declaration order (and rejects too many values)",
      (w.magic, w.schema, w.size, w.hw_generation, w.binding) == (fd.PROVISION_MAGIC, 1, 48, 3, 0)
      and raises(lambda: H.FbRecord("FailbackProvisionV1", *range(13)), H.FbbNotModelled) is not None)
a = H.FbRecord.from_bytes("FallbackProfileV1", PB)
b = H.fb_copy(a)
b.set_elem("reg256_261", 0, 1)
check("copy semantics: fb_copy / copy() give an independent record; equality is byte equality; to/from bytes round trip",
      a.reg256_261[0] == 8000 and b.reg256_261[0] == 1 and a != b and a == H.FbRecord.from_bytes("FallbackProfileV1", PB)
      and a.to_bytes() == PB)
pl = H.Plain("PriorDesc", ("load", "stored_len"), 1, 96)
check("aggregates: brace-init in order, unknown field raises, copies are deep",
      (pl.load, pl.stored_len) == (1, 96) and raises(lambda: setattr(pl, "x", 1), H.FbbNotModelled) is not None
      and H.fb_copy(pl) is not pl and (H.fb_copy(pl).load, H.fb_copy(pl).stored_len) == (1, 96))

# ===========================================================================
print("[6] FbbSim: strict types, FB globals, the C++-exact adapter, scheduler, hub")
# ===========================================================================
real = H.FbbSim(FW)
# FB-B1 (CONTRACT 1 D1 / 3): no header-defined type may be a `globals:` type (ESPHome emits the includes AFTER the
# globals), so the live firmware's non-scalar globals are std::array<> only - exactly these six (the live firmware always
# carries them from FB-B1 on; a missing array is a failure, not a pass).
# FB-B2: the sixth is the SAVE context's candidate words copy (fallback_profile_save_ctx_words, 31 x uint16_t, taken in the SAVE
# gate's accept branch and read only by the SAVE final lambdas); no other array is added.
FBB1_ARRAY_GLOBALS = {"fallback_profile_bytes": ("uint8_t", 96), "fallback_witness_bytes": ("uint8_t", 48),
                      "fallback_profile_pass1": ("uint16_t", 31), "fallback_profile_pass2": ("uint16_t", 31),
                      "fallback_profile_cand_words": ("uint16_t", 31),
                      "fallback_profile_save_ctx_words": ("uint16_t", 31),
                      # FB-C2: the Failback Shadow's torn-snapshot latch of the 31 cached configuration words (RAM-only, shadow tick only)
                      "failback_shadow_live_regs": ("uint16_t", 31)}
check(f"the REAL firmware loads in FbbSim: all {len(FW['globals'])} globals have a known type (scalar or std::array; "
      "no silent 0) and none is an FB record / struct global",
      len(real.g) == len(FW["globals"]) and not real.fb_globals)
check("the live firmware's std::array globals are exactly the FB-B1 set (5: profile / witness byte images, pass1, pass2, "
      "candidate words) plus FB-B2's one SAVE-context words copy plus FB-C2's shadow live latch (7; element type and size pinned) "
      "and each is a zero-initialised FbArray",
      real.array_globals == FBB1_ARRAY_GLOBALS
      and all(isinstance(real.g[n], H.FbArray) and len(real.g[n]) == real.array_globals[n][1] and not any(real.g[n])
              for n in real.array_globals),
      str(real.array_globals))
fw_bad = copy.deepcopy(FW)
fw_bad["globals"] = fw_bad["globals"] + [{"id": "mystery", "type": "MyStruct", "initial_value": "{}"}]
base_value = ds.Sim(fw_bad).g["mystery"]
check("an unknown struct-typed global: _dump_sim.Sim silently keeps a placeholder, FbbSim RAISES FbbNotModelled "
      "(S2 Part A m16)", base_value == "{}" and raises(lambda: H.FbbSim(fw_bad), H.FbbNotModelled) is not None)
fw = copy.deepcopy(FW)
fw["globals"] = fw["globals"] + [
    {"id": "fbt_p", "type": "ecco_fallback::FallbackProfileV1"},
    {"id": "fbt_w", "type": "ecco_fbdurable::FailbackProvisionV1"},
    {"id": "fbt_load", "type": "uint8_t", "initial_value": "0"},
    {"id": "fbt_gen", "type": "uint32_t", "initial_value": "0"},
    {"id": "fbt_flag", "type": "bool", "initial_value": "false"},
    {"id": "fbt_txn", "type": "uint8_t", "initial_value": "0"},
]
fw["script"] = fw["script"] + [
    {"id": "fbt_running", "then": [{"lambda": "id(fbt_flag) = id(fbt_running).is_running();"}]},
    {"id": "fbt_wait", "then": [{"wait_until": {"condition": {"lambda": "return id(fbt_flag);"}, "timeout": "1s"}},
                                {"lambda": "id(fbt_gen) = 7;"}]},
    {"id": "fbt_forever", "then": [{"wait_until": {"condition": {"lambda": "return id(fbt_flag);"}}}]},
    {"id": "fbt_delay", "then": [{"delay": "250ms"}, {"lambda": "id(fbt_gen) = 3;"}]},
]
sim = H.FbbSim(fw)
check("FB record globals hold zero-initialised FbRecords of their type",
      isinstance(sim.g["fbt_p"], H.FbRecord) and sim.g["fbt_p"]._kind == "FallbackProfileV1"
      and sim.g["fbt_w"]._kind == "FailbackProvisionV1" and sim.g["fbt_p"].to_bytes() == bytes(96))
fw_init = copy.deepcopy(fw)
fw_init["globals"][-6]["initial_value"] = "{1, 2}"
check("an FB record global with a non-empty initial_value raises (only zero-initialisation is modelled)",
      raises(lambda: H.FbbSim(fw_init), H.FbbNotModelled) is not None)
sim.nvs_direct.put(K_P, PB)
sim.run_lambda(
    "ecco_fbdurable::EspNvs nvs;\n"
    "ecco_fallback::FallbackProfileV1 p;\n"
    "ecco_fbdurable::ReadDiag d;\n"
    "uint8_t l = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, d);\n"
    "id(fbt_load) = l;\n"
    "id(fbt_p) = p;\n"
    "id(fbt_gen) = p.generation;\n"
    "p.reg256_261[0] = 1234;\n")
check("a transpiled lambda reads FBP through ecco_fbdurable::EspNvs + read_direct_t (the adapter binds the Sim's "
      "DirectNvs); assigning the local to a global COPIES it (a later p.reg256_261[0] store does not leak)",
      (sim.g["fbt_load"], sim.g["fbt_gen"], sim.g["fbt_p"].reg256_261[0]) == (fp.LOAD_OK, 7, 8000)
      and [op[0] for op in sim.nvs_direct.ops] == ["get", "read"])
sim.run_lambda("id(fbt_p).generation = 9;\nid(fbt_p).reg256_261[1] = 70000;")
check("`id(g).field = v` and `id(g).field[i] = v` store into the global record with C widths",
      (sim.g["fbt_p"].generation, sim.g["fbt_p"].reg256_261[1]) == (9, 4464))
check("assigning a record of the wrong kind to an FB global raises",
      raises(lambda: sim.set_global("fbt_p", H.FbRecord("FailbackProvisionV1")), H.FbbNotModelled) is not None
      and raises(lambda: sim.set_global("fbt_w", 5), H.FbbNotModelled) is not None)
check("an unmodelled ecco_fbdurable:: or ecco_fallback:: symbol raises FbbNotModelled (never a silent default)",
      raises(lambda: sim.run_lambda("id(fbt_gen) = ecco_fbdurable::nonexistent_fn(1);"), H.FbbNotModelled) is not None
      and raises(lambda: sim.run_lambda("id(fbt_gen) = ecco_fallback::nonexistent_fn(1);"), H.FbbNotModelled) is not None)
sim.nvs_direct = H.DirectNvs()
sim.nvs_direct.put(K_P, PB)
sim.nvs_direct.put(K_W, W7)
sim.run_lambda(
    "ecco_fbdurable::EspNvs nvs;\n"
    "ecco_fbdurable::ReadLatch latch;\n"
    "ecco_fallback::FallbackProfileV1 pp;\n"
    "ecco_fbdurable::FailbackProvisionV1 wp;\n"
    "ecco_fbdurable::ReadDiag dp;\n"
    "ecco_fbdurable::ReadDiag dw;\n"
    "uint8_t pl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, pp, dp);\n"
    "uint8_t wl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, wp, dw);\n"
    "ecco_fallback::FallbackProfileV1 pn = pp;\n"
    "pn.generation = 8;\n"
    "pn.captured_epoch = 1790086400;\n"
    "pn = ecco_fallback::seal_profile(pn);\n"
    "ecco_fbdurable::FailbackProvisionV1 wn = ecco_fbdurable::make_provision(8, pn.binding, 7, pp.binding, "
    "ecco_fbdurable::FALLBACK_PROFILE_KEY, 1, ecco_fbdurable::PROV_OP_SAVE);\n"
    "ecco_fbdurable::TxnResult r;\n"
    "id(fbt_txn) = ecco_fbdurable::commit_transition_t(nvs, wn, wp, ecco_fbdurable::PriorDesc{wl, dw.stored_len}, pn, pp, "
    "ecco_fbdurable::PriorDesc{pl, dp.stored_len}, r);\n")
sets = [op[1] for op in sim.nvs_direct.ops if op[0] == "set"]
check("the whole witness-first transaction runs from a transpiled lambda: commit_transition_t COMMITTED, FBW set "
      "before FBP, flash holds the new pair, the Sim's write latch stays clear",
      sim.g["fbt_txn"] == fd.TXN_COMMITTED and sets == ["1000595297", "1609458070"]
      and sim.nvs_direct.state_of(K_P) == f"OK:96:{H.fnv64_hex(fp.pack_profile(G8))}" and not sim.write_latch.write_latched)
sim.execute("fbt_running")
check("is_running() is true for the script that is executing", sim.g["fbt_flag"] is True)
check("is_running() on something that is not a script raises",
      raises(lambda: sim.run_lambda("id(fbt_flag) = id(ntp_time_nonexistent).is_running();"), H.FbbNotModelled) is not None)
sim.g["fbt_flag"] = False
t0 = sim.now_ms
sim.execute("fbt_wait")
check("wait_until with a timeout that never becomes true advances the clock by exactly the timeout, then continues",
      sim.now_ms - t0 == 1000 and sim.g["fbt_gen"] == 7)
sim.g["fbt_flag"], sim.g["fbt_gen"] = False, 0
flip = {"at": sim.now_ms + 300}
sim.background.append(lambda s: s.g.__setitem__("fbt_flag", True) if s.now_ms >= flip["at"] else None)
t0 = sim.now_ms
sim.execute("fbt_wait")
check("background tasks run between polls: the condition turns true at +300 ms and the wait ends there",
      sim.now_ms - t0 == 300 and sim.g["fbt_gen"] == 7)
sim.background.clear()
sim.g["fbt_flag"] = False
check("wait_until WITHOUT a timeout that never becomes true raises after MAX_WAIT_MS (never loops forever)",
      raises(lambda: sim.execute("fbt_forever"), H.FbbNotModelled) is not None)
t0 = sim.now_ms
sim.execute("fbt_delay")
check("delay advances the cooperative clock by its duration", sim.now_ms - t0 == 250 and sim.g["fbt_gen"] == 3)
check("durations: 250ms, 10s, 5min, 7 (ms); anything else raises",
      (H.duration_ms("250ms"), H.duration_ms("10s"), H.duration_ms("5min"), H.duration_ms(7)) == (250, 10000, 300000, 7)
      and raises(lambda: H.duration_ms("soon"), H.FbbNotModelled) is not None)
hub = H.HubModel(frame_ms=100)
states = [(hub.tx_buffer_empty(), hub.tx_blocked())]
hub.enqueue(2)
states.append((hub.tx_buffer_empty(), hub.tx_blocked()))
hub.tick(0)
states.append((hub.tx_buffer_empty(), hub.tx_blocked()))
hub.tick(100)
states.append((hub.tx_buffer_empty(), hub.tx_blocked()))
hub.tick(200)
states.append((hub.tx_buffer_empty(), hub.tx_blocked()))
check("hub model: queued frames make tx_buffer_empty false; one frame in flight blocks until its reply time; then idle",
      states == [(True, False), (False, False), (False, True), (True, True), (True, False)], str(states))
sim.hub.enqueue(1)
check("entities expose the hub to lambdas (tx_buffer_empty / tx_blocked on any modbus id)",
      sim.ent("modbus_hub_probe").tx_buffer_empty() is False)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-B0 harness self-tests passed.")
