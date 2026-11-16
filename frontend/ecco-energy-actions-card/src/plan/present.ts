// Presentation model for the read-only plan views: turns a PlanSnapshot into plain strings, chips and rows. Pure (no Lit, no DOM,
// no clock), so every wording and every state mapping is unit-tested. Nothing here can call a service.
import { EXPIRY_CEILING_MIN, FIELD_DEFS, OVERRIDE_LABELS, PROPOSED_DEFAULTS, fmt, formatDurationMin, span } from "../../../ecco-plan-core/src/index.ts";
import type { NativeSlot, OverrideConfig, OverrideKind, SlotReport } from "../../../ecco-plan-core/src/index.ts";
import type { ChipState, FieldInfo, PlanSnapshot } from "./adapter.ts";
import type { HelperSnapshot } from "./helpers.ts";

export type ChipKind = ChipState | "UNKNOWN";

export interface Chip {
  kind: ChipKind;
  label: string;
  icon: string;
  /** One sentence for the title/tooltip and screen readers. */
  meaning: string;
}

/** Text AND icon for every state, so no state relies on colour alone. */
export const CHIPS: Readonly<Record<ChipKind, Chip>> = Object.freeze({
  PROPOSED: { kind: "PROPOSED", label: "Proposed", icon: "mdi:lightbulb-outline", meaning: "Proposed: shown for review, not armed and not applied." },
  ARMED: { kind: "ARMED", label: "Armed", icon: "mdi:shield-check-outline", meaning: "Armed: scheduled and waiting to start, not yet running." },
  EXECUTING: { kind: "EXECUTING", label: "Executing", icon: "mdi:progress-clock", meaning: "Executing: a session is running now and no read-back has confirmed this value yet." },
  APPLIED_VERIFIED: { kind: "APPLIED_VERIFIED", label: "Applied and verified", icon: "mdi:check-circle-outline", meaning: "Applied and verified: a read-back from the system equals this value." },
  MISMATCH: { kind: "MISMATCH", label: "Mismatch", icon: "mdi:alert-circle-outline", meaning: "Mismatch: what the system reports differs from the intended value." },
  UNKNOWN: { kind: "UNKNOWN", label: "Unknown", icon: "mdi:help-circle-outline", meaning: "Unknown: this cannot be read, so no value is shown." },
});

export const STATUS_LINE =
  "SHADOW / advice only. Nothing shown here is applied by this view: it displays what Home Assistant, the inverter and Intelligence report, and it writes nothing.";

export const OVERRIDES_LINE_NONE =
  "Quick overrides: none active. Shown as status only; starting one needs a plan helper that does not exist yet.";

export const OVERRIDES_LINE_NONE_HELPER =
  "Quick overrides: none active. Shown as status only; starting one needs the guarded start path, which is not installed.";

export const OVERRIDES_STATUS_NOTE =
  "Status only: nothing in this view starts, cancels or enforces an override. An override can only hold back a start or raise a reserve; it never writes the inverter's table and never stops a running session.";

export interface FigureVM {
  key: string;
  label: string;
  known: boolean;
  /** The value text, or "Unknown". */
  text: string;
  /** Why it is unknown (empty when known). */
  reason: string;
  /** Extra qualifier, for example "simulated, not measured". */
  note: string;
  chip: Chip;
}

export interface SettingRowVM {
  path: string;
  label: string;
  known: boolean;
  text: string;
  reason: string;
  chip: Chip;
  /** Read-back or proposal remarks in plain words (may be empty). */
  remarks: string[];
}

export interface SlotVM {
  index: number;
  rangeText: string;
  /** Minutes, for the proportional bar. */
  spanMin: number;
  intendedText: string;
  /** null when the inverter's slot was not read. */
  inverterText: string | null;
  originText: string;
  chip: Chip;
  /** Plain-words mismatch (null when none). */
  mismatch: string | null;
}

export interface TouVM {
  readable: boolean;
  headline: string;
  /** compile status in words, or null when not compiled. */
  statusText: string | null;
  reasons: string[];
  slots: SlotVM[];
  mismatchCount: number;
}

export interface OverrideRowVM {
  kind: OverrideKind;
  label: string;
  /** "until 2026-11-17 07:00" in the helper's local time. */
  untilText: string;
  /** "ends in 3 h 20 min". */
  countdownText: string;
  /** What the override is meant to do, in plain words (not a claim that anything enforces it yet). */
  effectText: string;
}

export interface OverrideBlockVM {
  policyOk: boolean;
  /** One sentence: the limits in force, or why none are usable. */
  policyLine: string;
  reasons: string[];
  warnings: string[];
  /** Proposed entities that were not found. */
  missing: string[];
  /** The proposed defaults, shown only while the limits are not usable. They are never applied. */
  proposed: string[];
  revisionText: string;
  rows: OverrideRowVM[];
  problems: string[];
  note: string;
}

export interface PlanVM {
  statusLine: string;
  adviceNote: string | null;
  figures: FigureVM[];
  why: { origin: string; text: string }[];
  settings: SettingRowVM[];
  tou: TouVM;
  overridesLine: string;
  /** Present only when the proposed plan helper entities exist; null leaves the view exactly as it was. */
  overrideBlock: OverrideBlockVM | null;
}

const CONFIDENCE_TEXT: Record<string, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low", INSUFFICIENT: "Insufficient evidence" };

const kwh = (v: number): string => v.toFixed(1) + " kWh";

function chipFor(state: ChipState): Chip {
  return CHIPS[state];
}

export function slotText(s: NativeSlot): string {
  return `${fmt(s.startMin)} ${s.source === "Grid" ? "charge from grid" : "no grid charge"}, ${s.powerW} W, to ${s.targetSoc} %`;
}

const isTime = (f: FieldInfo): boolean => "time" in FIELD_DEFS[f.path];

function showValue(f: FieldInfo, v: number): string {
  if (isTime(f)) return fmt(v);
  return f.unit ? `${v} ${f.unit}` : String(v);
}

function settingRow(f: FieldInfo): SettingRowVM {
  if (!f.known) return { path: f.path, label: f.label, known: false, text: "Unknown", reason: f.reason ?? "Not readable.", chip: CHIPS.UNKNOWN, remarks: [] };
  const remarks: string[] = [];
  const shown = (v: number) => showValue(f, v);
  if (f.observed !== null && f.observed !== f.value) remarks.push(`The system reports ${shown(f.observed)}, not ${shown(f.value)}.`);
  if (f.proposal !== null) remarks.push(`Intelligence suggests ${shown(f.proposal)} (not adopted; nothing here changes it).`);
  if (f.state === "PROPOSED" && f.observed === null) remarks.push("No read-back is available for this value.");
  return { path: f.path, label: f.label, known: true, text: showValue(f, f.value), reason: "", chip: chipFor(f.state), remarks };
}

function mismatchWords(report: SlotReport): string | null {
  const i = report.intended;
  const o = report.observed;
  if (!o) return null;
  const parts: string[] = [];
  if (i.startMin !== o.startMin) parts.push(`start ${fmt(i.startMin)} intended, ${fmt(o.startMin)} on the inverter`);
  if (i.source !== o.source) parts.push(`charge source ${i.source} intended, ${o.source} on the inverter`);
  if (i.powerW !== o.powerW) parts.push(`power ${i.powerW} W intended, ${o.powerW} W on the inverter`);
  if (i.targetSoc !== o.targetSoc) parts.push(`target ${i.targetSoc} % intended, ${o.targetSoc} % on the inverter`);
  return parts.length ? `Slot ${report.index} differs from the inverter: ${parts.join("; ")}. It is not applied there, and this view does not apply it.` : null;
}

const ORIGIN_TEXT: Record<string, string> = {
  "native-fallback": "Native (unchanged)",
  "derived:charge": "Derived from the charge plan",
  "derived:export": "Derived from the export plan",
};

const STATUS_TEXT: Record<string, string> = {
  OK: "Compiled",
  INFEASIBLE: "Does not fit six slots",
  CONFLICT: "Conflict with a manual change",
  REFUSED: "Not compiled",
};

function touVM(snap: PlanSnapshot): TouVM {
  const t = snap.tou;
  if (!t.readable || !t.compile) {
    return { readable: false, headline: t.reason ?? "The six slots cannot be read.", statusText: null, reasons: [...t.notes], slots: [], mismatchCount: 0 };
  }
  const c = t.compile;
  const slots: SlotVM[] = c.slotReports.map((r, idx) => {
    const next = c.slotReports[(idx + 1) % c.slotReports.length] as SlotReport;
    const words = r.state === "MISMATCH" ? mismatchWords(r) : null;
    const chipKind: ChipKind = r.state === "APPLIED_VERIFIED" ? "APPLIED_VERIFIED" : r.state === "MISMATCH" ? "MISMATCH" : "PROPOSED";
    return {
      index: r.index,
      rangeText: `${fmt(r.intended.startMin)} to ${fmt(next.intended.startMin)}`,
      spanMin: span(r.intended.startMin, next.intended.startMin) || 1440,
      intendedText: slotText(r.intended),
      inverterText: r.observed ? slotText(r.observed) : null,
      originText: ORIGIN_TEXT[r.origin] ?? r.origin,
      chip: CHIPS[chipKind],
      mismatch: words,
    };
  });
  const mismatchCount = slots.filter((s) => s.mismatch !== null).length;
  const reasons = [...new Set([...c.reasons, ...t.notes])];
  let headline: string;
  if (c.status === "OK" && c.fallback) headline = "No armed charge or export changes the table: the six slots are as the inverter reports them.";
  else if (c.status === "OK") headline = `If the armed plan were compiled, ${mismatchCount} of the six slots would differ from what the inverter reports.`;
  else if (c.status === "INFEASIBLE") headline = "The plan does not fit the inverter's six slots. Nothing is truncated; the native table stays as it is.";
  else if (c.status === "CONFLICT") headline = "The inverter's table looks changed outside ECCO. Nothing is planned until that is reviewed.";
  else headline = "The plan is not compiled; the native table stays as it is.";
  return { readable: true, headline, statusText: STATUS_TEXT[c.status] ?? c.status, reasons, slots, mismatchCount };
}

const EFFECT_TEXT: Record<OverrideKind, (reserve: number | undefined) => string> = {
  hold_battery: () => "Intended: no export starts and no discretionary rate edits; charging and the inverter table are untouched.",
  skip_tonight: () => "Intended: tonight's export is held; charging continues.",
  prepare_power_cut: (reserve) => `Intended: the reserve is raised to ${reserve ?? "?"} % (never lowered) and export starts are held.`,
};

function proposedLines(): string[] {
  const show = (key: string, v: number): string => (key === "skipUntilMin" ? fmt(v) : key === "cutReservePct" ? `${v} %` : formatDurationMin(v));
  const names: Record<string, string> = {
    minExpiryMin: "Shortest allowed override",
    holdDefaultMin: "Hold battery default",
    holdCapMin: "Hold battery maximum",
    skipUntilMin: "Skip tonight ends at",
    skipCapMin: "Skip tonight maximum",
    cutDefaultMin: "Prepare for power cut default",
    cutCapMin: "Prepare for power cut maximum",
    cutReservePct: "Power-cut reserve",
  };
  return PROPOSED_DEFAULTS.map((p) => `${names[p.key] ?? p.key}: ${show(p.key, p.value)}. ${p.why}`);
}

function limitsLine(c: OverrideConfig): string {
  const fmtCap = (m: number): string => formatDurationMin(m);
  return (
    `Limits set by you: ${OVERRIDE_LABELS.hold_battery} default ${fmtCap(c.holdDefaultMin)}, up to ${fmtCap(c.holdCapMin)}; ` +
    `${OVERRIDE_LABELS.skip_tonight} until ${fmt(c.skipUntilMin)}, up to ${fmtCap(c.skipCapMin)}; ` +
    `${OVERRIDE_LABELS.prepare_power_cut} default ${fmtCap(c.cutDefaultMin)}, up to ${fmtCap(c.cutCapMin)}, reserve ${c.cutReservePct} %. ` +
    `Hard ceilings no setting can exceed: ${fmtCap(EXPIRY_CEILING_MIN.hold_battery)}, ${fmtCap(EXPIRY_CEILING_MIN.skip_tonight)}, ${fmtCap(EXPIRY_CEILING_MIN.prepare_power_cut)}.`
  );
}

function overrideBlockVM(h: HelperSnapshot): OverrideBlockVM {
  const policy = h.policy;
  const rows: OverrideRowVM[] = h.active.map((r) => ({
    kind: r.override.kind,
    label: r.label,
    untilText: `until ${r.expiresText}`,
    countdownText: `ends in ${formatDurationMin(r.remainingMin)}`,
    effectText: EFFECT_TEXT[r.override.kind](r.override.reservePct),
  }));
  const revisionText = !h.revision.known
    ? `Plan revision: unknown (${h.revision.reason})`
    : h.revision.value === 0
      ? "Plan revision: none recorded yet."
      : `Plan revision ${h.revision.value} (stored in the plan helper).`;
  return {
    policyOk: policy.ok,
    policyLine: policy.ok ? limitsLine(policy.config) : "The override limits are not usable, so no override can be started. Nothing falls back to proposed values.",
    reasons: policy.ok ? [] : [...policy.reasons],
    warnings: policy.ok ? [...policy.warnings] : [],
    missing: [...h.missing],
    proposed: policy.ok ? [] : proposedLines(),
    revisionText,
    rows,
    problems: [...h.problems],
    note: OVERRIDES_STATUS_NOTE,
  };
}

export function presentPlan(snap: PlanSnapshot & { helpers?: HelperSnapshot | null }): PlanVM {
  const helpers = snap.helpers ?? null;
  const t = snap.tomorrow;
  const figure = (key: string, label: string, item: { known: true; value: number; state: ChipState; simulated: boolean } | { known: false; reason: string }, fmtv: (v: number) => string): FigureVM => {
    if (!item.known) return { key, label, known: false, text: "Unknown", reason: item.reason, note: "", chip: CHIPS.UNKNOWN };
    return { key, label, known: true, text: fmtv(item.value), reason: "", note: item.simulated ? "simulated, not measured" : "", chip: chipFor(item.state) };
  };
  const figures: FigureVM[] = [
    figure("import", "Expected import", t.importKwh, kwh),
    figure("export", "Expected export", t.exportKwh, kwh),
    figure("solar", "Expected solar", t.solarKwh, kwh),
    figure("finish", "Charge finishes", t.chargeFinishMin, (v) => fmt(v)),
    figure("reserve", "Reserve", t.reservePct, (v) => `${v} %`),
  ];
  figures.push(
    t.confidence.known
      ? { key: "confidence", label: "Confidence", known: true, text: CONFIDENCE_TEXT[t.confidence.level] ?? t.confidence.level, reason: "", note: "", chip: chipFor(t.confidence.state) }
      : { key: "confidence", label: "Confidence", known: false, text: "Unknown", reason: "Intelligence did not state how sure it is.", note: "", chip: CHIPS.UNKNOWN },
  );
  return {
    statusLine: STATUS_LINE,
    adviceNote: snap.adviceNote,
    figures,
    why: t.why.map((w) => ({ origin: w.origin, text: w.text })),
    settings: snap.fields.map(settingRow),
    tou: touVM(snap),
    overridesLine: helpers
      ? snap.overrides.length === 0
        ? OVERRIDES_LINE_NONE_HELPER
        : `Quick overrides active: ${snap.overrides.map((o) => OVERRIDE_LABELS[o.kind]).join(", ")} (status only).`
      : snap.overrides.length === 0
        ? OVERRIDES_LINE_NONE
        : `Quick overrides active: ${snap.overrides.map((o) => o.kind).join(", ")} (status only).`,
    overrideBlock: helpers ? overrideBlockVM(helpers) : null,
  };
}
