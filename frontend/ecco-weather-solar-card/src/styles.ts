// Card styles: the ECCO dashboard palette (dark navy cards, solar amber, Solcast violet, Forecast.Solar blue), overridable
// through --ecco-* custom properties, and container queries so the layout follows the card's width, not the window's.
export const STYLES = `
:host{display:block;container-type:inline-size;
--ews-bg:var(--ecco-card-background,#141c2d);--ews-panel:var(--ecco-panel-background,rgba(255,255,255,.035));
--ews-text:var(--ecco-text,#e8eefc);--ews-muted:var(--ecco-text-muted,#93a3c0);--ews-line:var(--ecco-divider,rgba(255,255,255,.08));
--ews-solar:var(--ecco-line-solar,#ffb454);--ews-blend:var(--ecco-blend,#ffbd3d);--ews-sc:var(--ecco-solcast,#b8adff);
--ews-fs:var(--ecco-forecast-solar,#7ab8ff);--ews-cloud:var(--ecco-cloud,#9fb1cc);--ews-rain:var(--ecco-rain,#4fc3f7);
--ews-ok:var(--ecco-ok,#38d996);--ews-warn:var(--ecco-warning,#f4b942);--ews-radius:var(--ecco-radius,18px)}
ha-card{background:var(--ews-bg);color:var(--ews-text);border-radius:var(--ews-radius);overflow:hidden}
.wrap{padding:16px;display:flex;flex-direction:column;gap:12px}
.head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px}
.title{font-size:1.15rem;font-weight:600;letter-spacing:.01em}
.fresh{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:.72rem;padding:3px 8px;border-radius:999px;border:1px solid var(--ews-line);color:var(--ews-muted)}
.chip.ok{border-color:rgba(56,217,150,.35)}.chip.warn{color:var(--ews-warn);border-color:rgba(244,185,66,.5)}.chip.unk{opacity:.8}
.panel{background:var(--ews-panel);border:1px solid var(--ews-line);border-radius:14px;padding:12px 14px;min-width:0}
.panel:empty{display:none}
h3{margin:0 0 8px;font-size:.95rem;font-weight:600}
.sub{color:var(--ews-muted);font-size:.78rem;font-weight:400}
.note{color:var(--ews-muted);font-size:.74rem;margin-top:6px}
.na{color:var(--ews-muted);font-style:italic;font-size:.85rem}
.grid{display:grid;gap:12px}.grid.top{grid-template-columns:1fr 1fr}.grid.three{grid-template-columns:repeat(3,1fr);gap:10px}
.now{display:flex;align-items:center;gap:12px;margin-bottom:6px}
ha-icon.big{--mdc-icon-size:48px;color:var(--ews-blend)}ha-icon.mid{--mdc-icon-size:32px;color:var(--ews-blend)}
.temp{font-size:1.7rem;font-weight:600}.cond{color:var(--ews-muted)}
dl.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;margin:6px 0 0;font-size:.85rem}
dl.kv dt{color:var(--ews-muted)}dl.kv dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
.calc{font-size:.66rem;color:var(--ews-muted);border:1px solid var(--ews-line);border-radius:6px;padding:0 4px;margin-left:4px}
.tot{background:rgba(255,255,255,.03);border-radius:12px;padding:10px;min-width:0}
.tot .lbl{color:var(--ews-muted);font-size:.78rem}.tot .big{font-size:1.35rem;font-weight:650;font-variant-numeric:tabular-nums}
.blend{color:var(--ews-blend)}.basis{font-size:.72rem;color:var(--ews-muted)}.basis.warn{color:var(--ews-warn)}
.src{display:flex;flex-direction:column;font-size:.76rem;margin-top:4px;gap:1px}.src .sc{color:var(--ews-sc)}.src .fs{color:var(--ews-fs)}
.tabs{display:inline-flex;gap:4px;margin:0 0 6px}
.tabs button{font:inherit;font-size:.78rem;min-height:32px;padding:4px 12px;border-radius:999px;border:1px solid var(--ews-line);background:transparent;color:var(--ews-muted);cursor:pointer}
.tabs button.on{color:var(--ews-text);border-color:var(--ews-blend);background:rgba(255,189,61,.12)}
svg.chart{width:100%;height:auto;display:block}
.chart .grid-l{stroke:var(--ews-line);stroke-width:1}.chart .ax{fill:var(--ews-muted);font-size:11px}
.chart .act{fill:var(--ews-solar);opacity:.85}.chart .band{fill:var(--ews-sc);opacity:.18}
.chart .sc-l{fill:none;stroke:var(--ews-sc);stroke-width:2}.chart .sc-d{fill:var(--ews-sc)}
.chart .fs-m{fill:var(--ews-fs)}.chart .nowl{stroke:var(--ews-text);stroke-dasharray:3 3;opacity:.6}
.chart .cloud{fill:var(--ews-cloud)}.chart .rain{fill:var(--ews-rain)}
.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:.72rem;color:var(--ews-muted);margin-top:4px}
.lg::before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.lg.act::before{background:var(--ews-solar)}.lg.sc::before{background:var(--ews-sc)}.lg.band::before{background:var(--ews-sc);opacity:.3}
.lg.fs::before{background:var(--ews-fs);transform:rotate(45deg) scale(.8)}.lg.cloud::before{background:var(--ews-cloud)}.lg.rain::before{background:var(--ews-rain)}
.hours{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px;scrollbar-width:thin}
.hc{flex:0 0 auto;min-width:64px;text-align:center;font-size:.76rem;padding:6px 4px;border-radius:10px;background:rgba(255,255,255,.03)}
.hc .t{color:var(--ews-muted)}.hc .v{font-size:.95rem;font-weight:600}.hc .r{color:var(--ews-rain)}.hc .c,.hc .w{color:var(--ews-muted)}
.days{display:flex;flex-direction:column}
.dr{display:grid;grid-template-columns:3.2em 28px 1fr auto auto auto;align-items:center;gap:8px;padding:5px 0;border-top:1px solid var(--ews-line);font-size:.85rem}
.dr:first-child{border-top:0}.dr .cl{color:var(--ews-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dr .rn{color:var(--ews-rain)}.dr .wd{color:var(--ews-muted)}.dr .hl{font-variant-numeric:tabular-nums}
table.acc{width:100%;border-collapse:collapse;font-size:.82rem}
table.acc th,table.acc td{text-align:left;padding:4px 6px;border-top:1px solid var(--ews-line)}
table.acc thead th{color:var(--ews-muted);font-weight:500;border-top:0}table.acc tr.best th{color:var(--ews-ok)}
ul.ins{margin:0;padding-left:18px;font-size:.85rem;display:flex;flex-direction:column;gap:4px}
.foot{color:var(--ews-muted);font-size:.7rem;text-align:center}
@container (max-width: 560px){
.grid.top{grid-template-columns:1fr}.grid.three{grid-template-columns:1fr}
.tot{display:grid;grid-template-columns:1fr auto;align-items:baseline}.tot .src{grid-column:1/-1;flex-direction:row;gap:12px;flex-wrap:wrap}
.dr{grid-template-columns:3em 24px 1fr auto;font-size:.8rem}.dr .cl,.dr .wd{display:none}
.wrap{padding:12px}
.chart .ax{font-size:18px}.chart .axl{display:none}}
`;
