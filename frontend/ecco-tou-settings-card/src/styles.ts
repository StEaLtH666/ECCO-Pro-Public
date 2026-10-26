// Card styles. Mobile first: the slot table is a stacked list by default and a grid from 700px. Every interactive control
// is at least 44px tall (touch target); state is never shown by colour alone (every tone also has a word).
export const MOBILE_BREAKPOINT_PX = 700;
export const TOUCH_TARGET_PX = 44;

export const STYLES = `
:host{display:block;--tou-gap:12px;--tou-radius:10px;--tou-muted:var(--secondary-text-color,#6b6b6b);--tou-line:var(--divider-color,rgba(127,127,127,.25));--tou-warn:var(--warning-color,#b26a00);--tou-err:var(--error-color,#c62828);--tou-ok:var(--success-color,#2e7d32);--tou-accent:var(--primary-color,#03a9f4)}
.card{padding:16px;color:var(--primary-text-color,inherit);overflow-wrap:anywhere;word-break:normal}
.hdr{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;justify-content:space-between}
.hdr .title{font-size:1.25rem;font-weight:600;line-height:1.3}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.75rem;font-weight:600;border:1px solid currentColor}
.badge.ok{color:var(--tou-ok)}
.badge.warn{color:var(--tou-warn)}
.badge.muted{color:var(--tou-muted)}
.status{margin:10px 0;padding:10px 12px;border-radius:var(--tou-radius);border:1px solid var(--tou-line);display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center}
.status.block{border-color:var(--tou-warn)}
.status.lock{border-color:var(--tou-err);border-width:2px}
.status .word{font-weight:600}
.small{font-size:.82rem;color:var(--tou-muted)}
.muted{color:var(--tou-muted)}
.warn{color:var(--tou-warn);font-weight:500}
.err{color:var(--tou-err);font-weight:600}
.ok{color:var(--tou-ok);font-weight:600}
code{font-size:.85rem;overflow-wrap:anywhere}
.slots{list-style:none;margin:0;padding:0}
.slot{border-top:1px solid var(--tou-line);padding:8px 0;display:grid;grid-template-columns:1fr;gap:4px 8px}
.slot.active{background:linear-gradient(90deg,rgba(3,169,244,.08),transparent)}
.slot.owned{opacity:.6}
.slot .head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-weight:600}
.cell{display:flex;flex-wrap:wrap;gap:6px;align-items:center;min-height:${TOUCH_TARGET_PX}px}
.cell .k{font-size:.78rem;color:var(--tou-muted);min-width:5.5em}
.cell .v{font-weight:500}
.pen{min-height:${TOUCH_TARGET_PX}px;min-width:${TOUCH_TARGET_PX}px;border-radius:8px;border:1px solid var(--tou-line);background:transparent;color:var(--tou-accent);font:inherit;cursor:pointer}
.pen[disabled]{color:var(--tou-muted);cursor:not-allowed;opacity:.6}
.lockicon{min-height:${TOUCH_TARGET_PX}px;min-width:${TOUCH_TARGET_PX}px;border-radius:8px;border:1px dashed var(--tou-line);background:transparent;color:var(--tou-muted);font:inherit;cursor:pointer}
.fresh{font-size:.76rem;border:1px solid var(--tou-line);border-radius:6px;padding:0 6px}
.f-live{color:var(--tou-ok)}
.f-stale,.f-missing{color:var(--tou-warn)}
.panel{margin:12px 0;padding:12px;border-radius:var(--tou-radius);border:1px solid var(--tou-line)}
.panel.confirm{border-color:var(--tou-accent);border-width:2px}
.panel.outcome.applied{border-color:var(--tou-ok);border-width:2px}
.panel.outcome.failed,.panel.outcome.refused{border-color:var(--tou-warn);border-width:2px}
.panel.outcome.uncertain,.panel.locked{border-color:var(--tou-err);border-width:2px}
.panel h2{margin:0 0 8px;font-size:1.05rem}
.panel p{margin:6px 0}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.btn{min-height:${TOUCH_TARGET_PX}px;padding:0 14px;border-radius:8px;border:1px solid var(--tou-line);background:transparent;color:inherit;font:inherit;cursor:pointer}
.btn.primary{border-color:var(--tou-accent);color:var(--tou-accent);font-weight:600}
.btn.danger{border-color:var(--tou-err);color:var(--tou-err);font-weight:600}
.btn[aria-pressed="true"]{box-shadow:inset 0 0 0 1px var(--tou-accent);border-color:var(--tou-accent);font-weight:600}
.btn[disabled]{opacity:.55;cursor:not-allowed}
.in{min-height:${TOUCH_TARGET_PX}px;box-sizing:border-box;font:inherit;padding:8px;border-radius:8px;border:1px solid var(--tou-line);background:var(--card-background-color,transparent);color:inherit}
.in.num{width:7em;text-align:right}
.in.phrase{width:100%;font-family:ui-monospace,Menlo,Consolas,monospace}
.phrase-show{font-family:ui-monospace,Menlo,Consolas,monospace;font-weight:600;padding:6px 8px;border:1px dashed var(--tou-line);border-radius:6px;display:inline-block;user-select:all}
.steps{list-style:none;margin:8px 0;padding:0;display:grid;gap:4px}
.steps li{display:flex;gap:8px;align-items:center;min-height:28px}
.steps .dot{width:12px;height:12px;border-radius:50%;border:2px solid var(--tou-line);display:inline-block;flex:none}
.steps .seen .dot{background:var(--tou-ok);border-color:var(--tou-ok)}
.steps .seen{font-weight:500}
.steps .pending{color:var(--tou-muted)}
.verbatim{white-space:pre-wrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.85rem;border-left:3px solid var(--tou-line);padding:6px 10px;margin:6px 0}
ul.plain{margin:4px 0;padding-left:18px}
.foot{margin-top:14px}
@media (min-width:${MOBILE_BREAKPOINT_PX}px){
.slot{grid-template-columns:3.2em 7.5em minmax(7em,1fr) minmax(6em,1fr) minmax(6em,1fr) minmax(6em,1fr) auto;align-items:center}
.slot .head{grid-column:auto}
.cell .k{display:none}
.slot.hdrrow{font-size:.78rem;color:var(--tou-muted);border-top:none;padding:0}
.in.num{width:8em}
}
@media (max-width:${MOBILE_BREAKPOINT_PX - 1}px){
.card{padding:12px}
.slot.hdrrow{display:none}
}
`;
