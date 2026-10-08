// Pure HTML-string rendering for the Advanced / Experimental Configuration card.
//
// Every dynamic value goes through esc(). The only interactive elements carry data-action="search", "toggle-filter",
// "clear-filters" or "toggle-item"; all of them change local view state only. The Global Power write controls are
// rendered disabled and carry no data-action at all, so no handler exists that they could reach.
import {
  DANGER_LABEL,
  EVIDENCE_LABEL,
  EVIDENCE_ORDER,
  STATUS_HELP,
  STATUS_LABEL,
  STATUS_ORDER,
  formatNumber,
  registerLabel,
} from "./model.ts";
import type { GlobalPowerView } from "./model.ts";
import type { Catalogue, CatalogueItem, FilterState, Freshness, RawView, ValueView } from "./types.ts";

export function esc(v: unknown): string {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export const FRESHNESS_LABEL: Record<Freshness, string> = {
  live: "Live",
  unchanged: "Current (poll online)",
  stale: "Stale",
  unverified: "Freshness not verified",
  not_applicable: "No live value",
};

function rawText(raw: RawView): string {
  if (raw.kind === "unavailable") return `Not available: ${raw.note}`;
  return `${raw.hex} (${raw.value}), ${raw.kind} ${raw.note}`;
}

function row(label: string, valueHtml: string): string {
  return `<div class="kv"><dt>${esc(label)}</dt><dd>${valueHtml}</dd></div>`;
}

function optionsHtml(item: CatalogueItem): string {
  const o = item.options;
  const parts: string[] = [];
  if (o.enum && o.enum.length) {
    const list = o.enum.map((e) => `<li>${esc(e.raw)} = ${esc(e.label)}</li>`).join("");
    parts.push(`<ul class="opts">${list}</ul><div class="small">Source: ${esc(o.enum_source ?? "registry")}</div>`);
  }
  if (o.safe_min !== undefined || o.safe_max !== undefined) {
    parts.push(`<div>ECCO bound: ${esc(o.safe_min ?? "-")} to ${esc(o.safe_max ?? "-")}${item.unit ? " " + esc(item.unit) : ""}</div>`);
  }
  if (o.firmware_ceiling !== undefined) {
    parts.push(`<div>Firmware ceiling: ${esc(o.firmware_ceiling)}${item.unit ? " " + esc(item.unit) : ""} - ${esc(o.firmware_ceiling_note ?? "")}</div>`);
  }
  if (o.registry_limit !== undefined) {
    parts.push(`<div>Registry limit: ${esc(o.registry_limit)}${item.unit ? " " + esc(item.unit) : ""}</div>`);
  }
  if ("hardware_maximum" in o) {
    parts.push(`<div>Hardware maximum: not established</div>`);
  }
  if (o.bounds_note) parts.push(`<div class="small">${esc(o.bounds_note)}</div>`);
  if (item.options_note) parts.push(`<div class="small">${esc(item.options_note)}</div>`);
  return parts.length ? parts.join("") : `<span class="muted">No options are documented for this record.</span>`;
}

export function renderValueBadge(v: ValueView): string {
  return `<span class="val v-${esc(v.state)}">${esc(v.display)}</span>`;
}

export function renderFreshness(v: ValueView): string {
  return `<span class="fresh f-${esc(v.freshness)}" title="${esc(v.freshnessNote)}">${esc(FRESHNESS_LABEL[v.freshness])}</span>`;
}

export function renderItemDetails(item: CatalogueItem, v: ValueView): string {
  const ent = item.entity;
  const rawEnt = item.raw_entity;
  const d = item.decode;
  const explanation = [item.explanation, item.description, item.safety_impact].filter((x): x is string => !!x);
  return `<div class="details" id="d-${esc(item.id)}">
<dl>
${row("Current value", `${renderValueBadge(v)} ${renderFreshness(v)}<div class="small">${esc(v.freshnessNote)}</div>${v.problem ? `<div class="warn">${esc(v.problem)}</div>` : ""}`)}
${row("Register", esc(registerLabel(item)))}
${row("Raw value", esc(rawText(v.raw)))}
${row("Decoded value", v.state === "ok" ? esc(v.display) : `<span class="muted">${esc(v.display)}</span>`)}
${row("Status", `<strong>${esc(STATUS_LABEL[item.status])}</strong> - ${esc(STATUS_HELP[item.status])}`)}
${row("Why it is not writable here", esc(item.lock_reason))}
${row("Evidence", `${esc(EVIDENCE_LABEL[item.evidence])} (registry: ${esc(item.live_proof_status)}; write policy ${esc(item.write_policy)}; access ${esc(item.current_access)})`)}
${row("Danger", esc(DANGER_LABEL[item.danger] ?? item.danger))}
${row("Available options", optionsHtml(item))}
${row("Explanation", explanation.length ? explanation.map((t) => `<p>${esc(t)}</p>`).join("") : `<span class="muted">No explanation recorded.</span>`)}
${item.interactions.length ? row("Interactions", `<ul>${item.interactions.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`) : ""}
${row("Source entity", ent ? `${esc(v.entityId ?? "")}<div class="small">firmware id ${esc(ent.firmware_id)} ("${esc(ent.name)}"), linked by ${esc(ent.link ?? "-")}${d ? `, decoded in the ${esc(d.window)} poll` : ""}</div>` : `<span class="muted">No ECCO entity carries this record.</span>`)}
${rawEnt ? row("Raw-word entity", `firmware id ${esc(rawEnt.firmware_id)} ("${esc(rawEnt.name)}")`) : ""}
${row("Provenance", `<div>Registry record <code>${esc(item.provenance.registry_record)}</code></div>${item.provenance.firmware_evidence ? `<div class="small">Firmware evidence: ${esc(item.provenance.firmware_evidence)}</div>` : ""}${item.provenance.ha_evidence ? `<div class="small">HA evidence: ${esc(item.provenance.ha_evidence)}</div>` : ""}${item.write_policy_reason ? `<div class="small">Write policy reason: ${esc(item.write_policy_reason)}</div>` : ""}${item.notes ? `<div class="small">Notes: ${esc(item.notes)}</div>` : ""}`)}
</dl>
</div>`;
}

export function renderItem(item: CatalogueItem, v: ValueView, expanded: boolean): string {
  return `<li class="item s-${esc(item.status)}">
<button type="button" class="row" data-action="toggle-item" data-id="${esc(item.id)}" aria-expanded="${expanded ? "true" : "false"}" aria-controls="d-${esc(item.id)}">
<span class="name">${esc(item.name)}</span>
<span class="vcell">${renderValueBadge(v)}</span>
<span class="meta"><span class="reg">${item.registers.length ? "reg " : ""}${esc(registerLabel(item))}</span> <span class="tag t-${esc(item.status)}">${esc(STATUS_LABEL[item.status])}</span> <span class="tag">${esc(item.evidence)}</span> <span class="tag d-${esc(item.danger)}">${esc(item.danger)}</span> ${renderFreshness(v)}</span>
</button>
${expanded ? renderItemDetails(item, v) : ""}
</li>`;
}

export function renderResults(
  groups: { id: string; title: string; summary: string; items: CatalogueItem[] }[],
  values: Map<string, ValueView>,
  expanded: Set<string>,
): string {
  const visible = groups.filter((g) => g.items.length > 0);
  if (!visible.length) return `<p class="empty">No setting matches the search and filters.</p>`;
  return visible
    .map(
      (g) => `<section class="sec" aria-label="${esc(g.title)}">
<h3>${esc(g.title)} <span class="count">${g.items.length}</span></h3>
<p class="sum">${esc(g.summary)}</p>
<ul class="items">
${g.items
  .map((it) => {
    const v = values.get(it.id);
    return v ? renderItem(it, v, expanded.has(it.id)) : "";
  })
  .join("")}
</ul>
</section>`,
    )
    .join("");
}

function chip(kind: string, value: string, label: string, pressed: boolean): string {
  return `<button type="button" class="chip" data-action="toggle-filter" data-kind="${esc(kind)}" data-value="${esc(value)}" aria-pressed="${pressed ? "true" : "false"}">${esc(label)}</button>`;
}

export function renderFilters(catalogue: Catalogue, f: FilterState): string {
  const st = STATUS_ORDER.map((s) => chip("status", s, STATUS_LABEL[s], f.statuses.has(s))).join("");
  const ev = EVIDENCE_ORDER.filter((e) => catalogue.items.some((i) => i.evidence === e))
    .map((e) => chip("evidence", e, EVIDENCE_LABEL[e], f.evidence.has(e)))
    .join("");
  const sec = catalogue.sections.map((s) => chip("section", s.id, s.title, f.sections.has(s.id))).join("");
  const any = f.statuses.size + f.evidence.size + f.sections.size > 0 || f.query.length > 0;
  return `<div class="fgroup" role="group" aria-label="Status"><span class="flabel">Status</span>${st}</div>
<div class="fgroup" role="group" aria-label="Evidence"><span class="flabel">Evidence</span>${ev}</div>
<div class="fgroup" role="group" aria-label="Category"><span class="flabel">Category</span>${sec}</div>
${any ? `<button type="button" class="link" data-action="clear-filters">Clear search and filters</button>` : ""}`;
}

export function renderSummary(shown: number, total: number): string {
  return `${esc(shown)} of ${esc(total)} settings shown. This page is read-only.`;
}

export function renderGlobalPower(view: GlobalPowerView): string {
  const v = view.value;
  const valueText = v.state === "ok" && v.numeric !== null ? `${formatNumber(v.numeric)} W` : v.display;
  const controls = view.controls
    .map((c) => {
      if (c.key === "unlock" || c.key === "apply") {
        return `<div class="ctl"><button type="button" class="ctl-btn" disabled aria-disabled="true" title="${esc(c.reason)}">${esc(c.label)}</button><div class="small">${esc(c.description)}</div></div>`;
      }
      if (c.key === "staged_value") {
        return `<div class="ctl"><label>${esc(c.label)} <input type="number" class="ctl-in" disabled aria-disabled="true" placeholder="-" inputmode="numeric" title="${esc(c.reason)}"></label><div class="small">${esc(c.description)}</div></div>`;
      }
      const text =
        c.key === "permitted_range"
          ? view.permittedRangeText
          : c.key === "verification"
            ? view.verificationText
            : c.key === "previous_value"
              ? view.previousValueText
              : view.historyText;
      return `<div class="ctl"><div class="ctl-label">${esc(c.label)}</div><div>${esc(text)}</div><div class="small">${esc(c.description)}</div></div>`;
    })
    .join("");
  return `<div class="gp-panel">
<div class="gp-head"><h2>${esc(view.title)}</h2><span class="gp-reg">Register ${esc(view.register)}</span><span class="badge ro">READ ONLY</span></div>
<div class="gp-value"><span class="big v-${esc(v.state)}">${esc(valueText)}</span> ${renderFreshness(v)}</div>
${v.problem ? `<div class="warn">${esc(v.problem)}</div>` : ""}
<dl class="gp-facts">
${row("Current value", esc(valueText))}
${row("Raw value", esc(rawText(v.raw)))}
${row("Unit", "W")}
${row("Read freshness", `${esc(FRESHNESS_LABEL[v.freshness])} - ${esc(v.freshnessNote)}`)}
${row("Source entity", v.entityId ? `<code>${esc(v.entityId)}</code>` : `<span class="muted">none</span>`)}
${row("Mapping evidence", esc(view.evidence))}
${row("Status", esc(view.readOnlyText))}
${row("Hardware maximum", esc(view.hardwareMaximumText))}
${row("Regulatory export allowance", esc(view.regulatoryText))}
</dl>
<div class="gp-controls" aria-label="Future Global Power controls (disabled)">
<p class="warn">Design preview: these controls are disabled. Global Power writing is not implemented in this release.</p>
<div class="ctl-grid">${controls}</div>
</div>
<details class="gp-why"><summary>Why is Global Power read-only?</summary>
<ul>${view.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
<p class="small">Limitations:</p><ul>${view.limitations.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
<p class="small">Owner confirmation (${esc(view.ownerConfirmation.date)}): ${esc(view.ownerConfirmation.statement)}</p>
</details>
</div>`;
}

export function renderShell(title: string, styles: string, catalogue: Catalogue, footer = ""): string {
  return `<style>${styles}</style>
<ha-card>
<div class="card">
<div class="hdr">
<div class="title">${esc(title)}</div>
<div class="hdr-badges"><span class="badge ro">READ ONLY</span><span class="small">${esc(catalogue.record_count)} registry records</span></div>
${catalogue.controller_note ? `<p class="small">${esc(catalogue.controller_note)}</p>` : ""}
</div>
<div data-region="gp"></div>
<div class="controls">
<label class="search"><span class="flabel">Search</span><input type="search" data-action="search" placeholder="Name, register (e.g. 245) or description" autocomplete="off" spellcheck="false" maxlength="200"></label>
<div data-region="filters"></div>
</div>
<div class="summary" data-region="summary" aria-live="polite"></div>
<div data-region="results"></div>
${catalogue.notes ? `<p class="small foot">${esc(catalogue.notes)}</p>` : ""}
${footer ? `<p class="small">${esc(footer)}</p>` : ""}
</div>
</ha-card>`;
}
