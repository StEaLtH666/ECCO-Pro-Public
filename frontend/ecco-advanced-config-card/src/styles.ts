// Card styles. Mobile first: one column by default, wider layouts from 700px. Every interactive control is at least
// 44px tall (touch target), long register text wraps instead of overflowing, and state is never shown by colour alone.
export const MOBILE_BREAKPOINT_PX = 700;
export const TOUCH_TARGET_PX = 44;

export const STYLES = `
:host{display:block;--acc-gap:12px;--acc-radius:10px;--acc-muted:var(--secondary-text-color,#6b6b6b);--acc-line:var(--divider-color,rgba(127,127,127,.25));--acc-warn:var(--warning-color,#b26a00);--acc-err:var(--error-color,#c62828);--acc-ok:var(--success-color,#2e7d32)}
.card{padding:16px;color:var(--primary-text-color,inherit);overflow-wrap:anywhere;word-break:normal}
.hdr .title{font-size:1.25rem;font-weight:600;line-height:1.3}
.hdr-badges{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.75rem;font-weight:600;border:1px solid currentColor}
.badge.ro{color:var(--acc-warn)}
.small{font-size:.82rem;color:var(--acc-muted)}
.muted{color:var(--acc-muted)}
.warn{color:var(--acc-warn);font-weight:500}
code{font-size:.82rem;overflow-wrap:anywhere}
.gp-panel{border:2px solid var(--acc-warn);border-radius:var(--acc-radius);padding:12px;margin:12px 0}
.gp-head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.gp-head h2{margin:0;font-size:1.1rem}
.gp-reg{font-weight:600}
.gp-value{margin:8px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.gp-value .big{font-size:1.6rem;font-weight:600}
dl{margin:0}
.kv{display:grid;grid-template-columns:1fr;gap:2px;padding:6px 0;border-top:1px solid var(--acc-line)}
.kv dt{font-weight:600;font-size:.85rem}
.kv dd{margin:0}
.kv dd p{margin:0 0 6px}
.kv dd p:last-child{margin-bottom:0}
.kv dd ul{margin:0;padding-left:18px}
.gp-controls{margin-top:10px}
.ctl-grid{display:grid;grid-template-columns:1fr;gap:var(--acc-gap)}
.ctl{border:1px dashed var(--acc-line);border-radius:8px;padding:8px}
.ctl-label{font-weight:600}
.ctl-btn,.ctl-in{min-height:${44}px;width:100%;box-sizing:border-box;font:inherit;opacity:.55;cursor:not-allowed}
.gp-why{margin-top:10px}
.gp-why summary{min-height:${44}px;display:flex;align-items:center;cursor:pointer}
.controls{margin:12px 0}
.search{display:flex;flex-direction:column;gap:4px}
.search input{min-height:${44}px;width:100%;box-sizing:border-box;font:inherit;padding:8px;border-radius:8px;border:1px solid var(--acc-line);background:var(--card-background-color,transparent);color:inherit}
.fgroup{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0}
.flabel{font-size:.82rem;font-weight:600;margin-right:4px}
.chip{min-height:${44}px;padding:6px 12px;border-radius:999px;border:1px solid var(--acc-line);background:transparent;color:inherit;font:inherit;cursor:pointer}
.chip[aria-pressed="true"]{border-color:var(--primary-color,#03a9f4);font-weight:600;box-shadow:inset 0 0 0 1px var(--primary-color,#03a9f4)}
.chip[aria-pressed="true"]::before{content:"\\2713 "}
.link{min-height:${44}px;background:none;border:none;color:var(--primary-color,#03a9f4);font:inherit;cursor:pointer;padding:0 4px}
.summary{margin:8px 0;font-size:.85rem;color:var(--acc-muted)}
.sec h3{margin:16px 0 2px;font-size:1rem}
.sec .count{font-weight:400;color:var(--acc-muted)}
.sec .sum{margin:0 0 6px}
.items{list-style:none;margin:0;padding:0}
.item{border-top:1px solid var(--acc-line)}
.row{display:grid;grid-template-columns:1fr auto;gap:4px 8px;width:100%;min-height:${44}px;padding:8px 0;background:none;border:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.row .name{font-weight:500}
.row .meta{grid-column:1 / -1;display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:.8rem;color:var(--acc-muted)}
.tag{border:1px solid var(--acc-line);border-radius:6px;padding:0 6px}
.tag.t-LOCKED,.tag.t-UNSUPPORTED{font-weight:600}
.tag.d-D3,.tag.d-D4{font-weight:600}
.val{font-weight:600}
.v-unavailable,.v-unknown,.v-missing,.v-unmapped{color:var(--acc-muted);font-style:italic;font-weight:400}
.v-unexpected{color:var(--acc-err)}
.fresh{font-size:.78rem;border-radius:6px;padding:0 6px;border:1px solid var(--acc-line)}
.f-live{color:var(--acc-ok)}
.f-stale,.f-unverified{color:var(--acc-warn)}
.details{padding:4px 0 12px}
.opts{margin:0;padding-left:18px}
.empty{color:var(--acc-muted)}
.foot{margin-top:16px}
@media (min-width:${700}px){
.kv{grid-template-columns:minmax(150px,32%) 1fr;gap:8px}
.ctl-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.row{grid-template-columns:minmax(0,1fr) minmax(0,auto)}
}
@media (max-width:${700 - 1}px){
.card{padding:12px}
.gp-value .big{font-size:1.35rem}
}
`;
