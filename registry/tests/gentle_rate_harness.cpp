// Host replay harness for docs/dev/gentle-rate-controller/proposed/ecco_gentle_rate_core.h (driven by
// test_gentle_rate_core_host.py).
//
// Reads commands on stdin, one per line, and prints exactly what docs/dev/gentle-rate-controller/vector_runner.py
// prints for the reference model, so Python can compare the two traces line by line:
//   C <config fields>                       set the configuration (vector_runner.CONFIG_FIELDS order)
//   S                                       new sequence: a fresh core with the configuration
//   B <record fields> <now_ms>              boot from a crafted record (encode, decode, boot)    -> BOOT ...
//   T <In fields> <Plan fields> <t[8]> <p[8]>  one tick                                          -> trace line
//   R <k>                                   restart: the core's own record, byte k ^ 0x5A when k >= 0,
//                                           no record at all when k == -2; decode; boot          -> BOOT ...
//   E                                       end of sequence                                      -> REC <hex>
//   K <live> <original> <v> <p> <q>         restore classifier                                   -> K <class>
//   H <hex>                                 decode a record                                      -> H <status> <fields>
//   W <live[6]> <table[6]>                  lost-lease warning mask                              -> W <mask>
// Test code only: never part of any firmware build.

#include "ecco_gentle_rate_core.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>

using namespace ecco_grc;

namespace {

char g_line[8192];

struct Tok {
  char *p;
  explicit Tok(char *s) : p(s) {}
  long long next() {
    char *e = nullptr;
    long long v = strtoll(p, &e, 10);
    if (e == p) { std::fprintf(stderr, "harness: bad number near '%.20s'\n", p); std::exit(2); }
    p = e;
    return v;
  }
};

void print_trace(const Core &c, const Out &o) {
  std::printf("%d %d %d %u %d %d %d %d %d %d %d %d %d %d %d %d %d %d %lld\n", c.state, o.action, o.value,
              (unsigned) o.seq, o.disarm ? 1 : 0, o.commit ? 1 : 0, o.event, c.v, c.p, c.q, c.changes, c.writes_night,
              c.restore_attempts, c.gain_pct, c.p_ref, c.last_reason, c.bms_limited ? 1 : 0, c.ineffective,
              (long long) c.lease_end);
}

void print_boot(const Core &c) {
  std::printf("BOOT %d %d %d %d %d %d %d %d\n", c.state, c.v, c.p, c.q, c.changes, c.writes_night, c.restore_attempts,
              c.last_reason);
}

void print_hex(const uint8_t *b, size_t n) {
  for (size_t k = 0; k < n; k++) std::printf("%02x", b[k]);
}

Record read_record(Tok &t) {
  Record r{};
  r.flags = (uint8_t) t.next();
  r.slot = (uint8_t) t.next();
  r.reason = (uint8_t) t.next();
  r.original = (uint16_t) t.next();
  r.v = (uint16_t) t.next();
  r.p = (uint16_t) t.next();
  r.night_id = (uint32_t) t.next();
  r.writes_night = (uint8_t) t.next();
  r.changes = (uint8_t) t.next();
  r.restore_attempts = (uint8_t) t.next();
  r.lease_end = (uint32_t) t.next();
  r.q = (uint16_t) t.next();
  return r;
}

}  // namespace

int main() {
  Config cfg{};
  Core core{};
  uint32_t last_now = 0;
  while (std::fgets(g_line, sizeof g_line, stdin)) {
    char op = g_line[0];
    Tok t(g_line + 1);
    if (op == 'C') {
      int32_t *i32[] = {&cfg.floor_w, &cfg.round_w, &cfg.fw_bound_w, &cfg.max_step_w, &cfg.hyst_w,
                        &cfg.reversal_extra_w};
      for (auto *f : i32) *f = (int32_t) t.next();
      cfg.dwell_ms = (uint32_t) t.next();
      cfg.settle_ms = (uint32_t) t.next();
      cfg.judge_samples = (int32_t) t.next();
      cfg.max_changes = (int32_t) t.next();
      cfg.max_restore_attempts = (int32_t) t.next();
      cfg.night_write_ceiling = (int32_t) t.next();
      cfg.restore_backoff_ms = (uint32_t) t.next();
      cfg.op_timeout_ms = (uint32_t) t.next();
      cfg.plan_max_age_ms = (uint32_t) t.next();
      cfg.telemetry_stale_ms = (uint32_t) t.next();
      cfg.config_stale_ms = (uint32_t) t.next();
      cfg.rtc_busy_max_ms = (uint32_t) t.next();
      cfg.clock_skew_max_s = (int32_t) t.next();
      cfg.end_margin_s = (int32_t) t.next();
      cfg.min_lease_s = (int32_t) t.next();
      cfg.arm_window_ms = (uint32_t) t.next();
      int32_t *rest[] = {&cfg.charging_min_w, &cfg.response_min_pct, &cfg.wrong_dir_w, &cfg.max_ineffective,
                         &cfg.gain_min_pct, &cfg.gain_max_pct, &cfg.runaway_pct, &cfg.runaway_margin_w,
                         &cfg.runaway_samples, &cfg.stop_w, &cfg.stop_samples, &cfg.stop_soc_gap, &cfg.soc_jump_max,
                         &cfg.soc_drop_max, &cfg.guard_margin_s, &cfg.guard_derate_pct, &cfg.guard_tail_pct};
      for (auto *f : rest) *f = (int32_t) t.next();
      cfg.watchdog_extra_ms = (uint32_t) t.next();
      cfg.rx_fresh_ms = (uint32_t) t.next();
      cfg.window_match_s = (int32_t) t.next();
      cfg.capacity_floor_wh = (int32_t) t.next();
      cfg.taper_max_pct = (int32_t) t.next();
      cfg.script_steps = (int32_t) t.next();
      cfg.script_step_ms = (uint32_t) t.next();
      cfg.script_queue_ms = (uint32_t) t.next();
    } else if (op == 'S') {
      core = Core(cfg);
      last_now = 0;
    } else if (op == 'B') {
      Record r = read_record(t);
      uint32_t now = (uint32_t) t.next();
      RecordBytes b = encode_record(r);
      Decoded d = decode_record(b.b, REC_SIZE, cfg);
      core = Core(cfg);
      core.boot(d.status, d.rec, now);
      print_boot(core);
    } else if (op == 'T') {
      In i{};
      i.now_ms = (uint32_t) t.next();
      i.epoch = t.next();
      i.local_min = (int32_t) t.next();
      i.night_id = (uint32_t) t.next();
      i.clock_change_night = t.next() != 0;
      i.inv_skew_s = (int32_t) t.next();
      i.rtc_busy = t.next() != 0;
      i.mutex_busy = t.next() != 0;
      i.other = (uint32_t) t.next();
      i.fault = t.next() != 0;
      i.arm = t.next() != 0;
      i.start = t.next() != 0;
      i.end = t.next() != 0;
      i.ack = t.next() != 0;
      i.op = (uint8_t) t.next();
      i.soc = (int32_t) t.next();
      i.batt_w = (int32_t) t.next();
      i.tel_ok = t.next() != 0;
      i.tel_age_ms = (uint32_t) t.next();
      i.sample_seq = (uint32_t) t.next();
      i.cfg_age_ms = (uint32_t) t.next();
      i.live_sp = (int32_t) t.next();
      i.slot_start_min = (int32_t) t.next();
      i.slot_end_min = (int32_t) t.next();
      i.slot_grid = t.next() != 0;
      i.slot_target = (int32_t) t.next();
      i.op_seq = (uint32_t) t.next();
      i.op_kind = (uint8_t) t.next();
      i.op_value = (int32_t) t.next();
      i.rx_age_ms = (uint32_t) t.next();
      i.grid_ok = t.next() != 0;
      i.restore_req = t.next() != 0;
      Plan &pl = i.plan;
      pl.valid = t.next() != 0;
      pl.age_ms = (uint32_t) t.next();
      pl.slot = (int32_t) t.next();
      pl.target = (int32_t) t.next();
      pl.deadline = t.next();
      pl.window_end = t.next();
      pl.ceiling_w = (int32_t) t.next();
      pl.capacity_wh = (int32_t) t.next();
      pl.taper = (int32_t) t.next();
      pl.n = (int32_t) t.next();
      for (int k = 0; k < PLAN_POINTS; k++) pl.t[k] = t.next();
      for (int k = 0; k < PLAN_POINTS; k++) pl.p[k] = (int32_t) t.next();
      last_now = i.now_ms;
      Out o = core.step(i);
      print_trace(core, o);
    } else if (op == 'R') {
      long long k = t.next();
      RecordBytes b = encode_record(core.record());
      Decoded d{};
      if (k == -2) {
        d = decode_record(nullptr, 0, cfg);
      } else {
        if (k >= 0 && k < (long long) REC_SIZE) b.b[k] ^= 0x5A;
        d = decode_record(b.b, REC_SIZE, cfg);
      }
      core = Core(cfg);
      core.boot(d.status, d.rec, last_now);
      print_boot(core);
    } else if (op == 'E') {
      RecordBytes b = encode_record(core.record());
      std::printf("REC ");
      print_hex(b.b, REC_SIZE);
      std::printf("\n");
    } else if (op == 'K') {
      int32_t live = (int32_t) t.next(), orig = (int32_t) t.next(), v = (int32_t) t.next(), p = (int32_t) t.next();
      int32_t q = (int32_t) t.next();
      std::printf("K %d\n", classify_restore(live, orig, v, p, q));
    } else if (op == 'W') {
      int32_t live[6], table[6];
      for (auto &x : live) x = (int32_t) t.next();
      for (auto &x : table) x = (int32_t) t.next();
      std::printf("W %u\n", (unsigned) lost_lease_slots(live, table));
    } else if (op == 'H') {
      char *s = t.p;
      while (*s == ' ') s++;
      uint8_t buf[64];
      size_t n = 0;
      while (s[0] && s[1] && s[0] != '\n' && s[0] != '\r' && n < sizeof buf) {
        char h[3] = {s[0], s[1], 0};
        buf[n++] = (uint8_t) strtol(h, nullptr, 16);
        s += 2;
      }
      Decoded d = decode_record(buf, n, cfg);
      const Record &r = d.rec;
      std::printf("H %d %d %d %d %d %d %d %u %d %d %d %u %d\n", d.status, r.flags, r.slot, r.reason, r.original, r.v,
                  r.p, (unsigned) r.night_id, r.writes_night, r.changes, r.restore_attempts, (unsigned) r.lease_end,
                  r.q);
    } else if (op == '\n' || op == '\r' || op == '#') {
      continue;
    } else {
      std::fprintf(stderr, "harness: unknown command '%c'\n", op);
      return 2;
    }
  }
  return 0;
}
