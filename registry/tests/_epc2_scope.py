"""epc2 (stage 3 of the two-master-card energy-control work: guarded overrides and their enforcement; offline, nothing installed). FROZEN
edits (PEX): the card's README.md, src/config.ts, src/ecco-energy-actions-card.ts and rebuilt dist/ecco-energy-actions-card.js (the
bundle had not been rebuilt since the export; the rebuild carries every source change since), and the scheduled Dump to Grid package
(refuses during Hold battery / Skip tonight / Prepare for power cut, fails closed, raises the Stop SOC to the effective reserve).
CHAIN-PINNED edit: the deployment manifest (two package stanzas). ADDED: the plan helper package and the guarded start package, their
three suites and test support, and the card's control sources and tests. ZERO firmware, registry data, Intelligence, ecco_core or
VERSION.yaml byte; ZERO Modbus operation; every service the new scripts call is a helper setter or a persistent notification, except the
guarded start's one press of the existing dongle start button.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked (apply then revert reproduces both texts byte for byte), and
each reverter raises unless each of its edits is present exactly once. The post-export chain entry `epc2` (registry/tests/_scope_chain.py
POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries them; its fingerprint is sealed with _pex.sealed and must be sealed again if another
entry merges first.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'epc2'

ADDED_FILES = frozenset({
    'frontend/ecco-energy-actions-card/src/plan/clock.ts',
    'frontend/ecco-energy-actions-card/src/plan/controls.ts',
    'frontend/ecco-energy-actions-card/src/plan/controlsModel.ts',
    'frontend/ecco-energy-actions-card/src/plan/planActions.ts',
    'frontend/ecco-energy-actions-card/test/planControls.test.ts',
    'frontend/ecco-energy-actions-card/test/support/controlsProbe.ts',
    'frontend/ecco-plan-core/test/overrideParity.test.ts',
    'frontend/ecco-plan-core/test/parity/override_parity_cases.json',
    'frontend/ecco-plan-core/tsconfig.card.json',
    'home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml',
    'home-assistant/packages/ecco_plan_helpers.yaml',
    'home-assistant/tests/_plan_sim.py',
    'home-assistant/tests/test_ecco_plan_enforcement.py',
    'home-assistant/tests/test_ecco_plan_helpers_package.py',
    'home-assistant/tests/test_ecco_stage3_limitation.py',
    'registry/tests/_epc2_scope.py',
})

import hashlib


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"{ID} scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"{ID} scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"{ID} scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) the card README ---------------------------------------------------------------------------
README_REL = 'frontend/ecco-energy-actions-card/README.md'
README_EDITS = (
    (_blk(r"""
### Plan views (read only, default off)
"""),
     _blk(r"""
### Plan views and guarded overrides (default off)
""")),
    (_blk(r"""
The views **display only**: no button, no handler, no service call, no entity write (a test asserts `hass.callService` is
never called). Quick overrides appear as a read-only "none active" line. Figures come from the Intelligence advice entities
"""),
     _blk(r"""
The views **display**: with no plan helper entity configured there is no button, no handler, no service call and no entity write (a
test asserts `hass.callService` is never called). Quick overrides appear as a read-only "none active" line. Figures come from the Intelligence advice entities
""")),
    (_blk(r"""
chips), `view.ts` (Lit templates).

"""),
     _blk(r"""
chips), `view.ts` (Lit templates).

**Quick overrides (stage 3, offline, nothing installed).** With the plan helper package installed
(`home-assistant/packages/ecco_plan_helpers.yaml`, see `frontend/ecco-plan-core/README.md`) the same section also offers Hold battery, Skip
tonight and Prepare for power cut: the owner's default, the lengths inside the owner's limits and "until 07:00", the running override with
its expiry and a Cancel, why a start is not offered, and the scripts' own last answer (a refusal says why, with a stable code). Each button
calls `script.turn_on` on `script.ecco_plan_override_start` or `script.ecco_plan_override_cancel` and on nothing else: `src/plan/planActions.ts`
is the closed list and the card drops any other call. Home Assistant decides again, with the same rules, and may refuse a start. An
override holds ECCO's starts back or raises a protected reserve; it never charges. Prepare for power cut with the battery below the reserve it
raised says so ("... Nothing is charging. Use Charge Battery if you want it filled.") and offers nothing automatic. Without the plan helpers
nothing is added (the golden renders are unchanged).

**Stated limitation.** Partial protection only: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant or by an assistant. These overrides and the reserve protect ECCO's own starts and this card, not an administrator, an assistant or a press of the dongle's own button, and their helpers are plain helpers that an administrator or assistant can write. Binding the Start button needs a firmware gate (a flash, approved separately).

**Guarded manual Dump to Grid start.** Set `dump_to_grid.guarded_start: script.ecco_dump_to_grid_start_guarded`
(`home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml`) and the Start button calls ONLY that script, which refuses while an override
holds export or the staged Stop SOC is below the effective reserve, and otherwise presses the same start button itself. A `guarded_start`
that is not a script id does nothing (it never falls back to the direct press). Without it the button is pressed directly, as before, and no
override binds the manual start from this card. **Residual:** the dongle's own Start button entity can still be pressed from Home Assistant
by other means (another card, the entity page, an assistant); binding that needs a firmware gate, a flash and a separate approval.

```yaml
dump_to_grid:
  # ...the entities above...
  guarded_start: script.ecco_dump_to_grid_start_guarded   # optional
```

""")),
    (_blk(r"""
Pure, DOM-free logic lives in small modules (plus the read-only plan views under `src/plan/`), all unit tested without a
DOM (see `test/`):
"""),
     _blk(r"""
Pure, DOM-free logic lives in small modules (plus the plan views and controls under `src/plan/`: `planActions.ts` the closed list of calls,
`controlsModel.ts` what is offered, `controls.ts` the buttons, `clock.ts` the browser's zone), all unit tested without a DOM (see `test/`):
""")),
)


def pre_epc2_readme(text: str) -> str:
    """frontend/ecco-energy-actions-card/README.md with exactly epc2's edits undone (a reverter of chain entry epc2, PEX): its text as of the entry before."""
    return _revert(text, README_EDITS, README_REL)


pre_epc2_readme.edits = README_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc2_readme(text: str) -> str:
    """Applies epc2's edits to frontend/ecco-energy-actions-card/README.md as of the entry before (the round trip)."""
    return _apply(text, README_EDITS, README_REL)


# ---- (PEX frozen edit) src/config.ts -----------------------------------------------------------------------------
CONFIG_REL = 'frontend/ecco-energy-actions-card/src/config.ts'
CONFIG_EDITS = (
    (_blk(r"""
  schedule?: DumpScheduleEntities;
}
"""),
     _blk(r"""
  schedule?: DumpScheduleEntities;
  /**
   * script (optional) - the guarded manual start (home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml). When set, the Start
   * button calls ONLY this script, which refuses while a Hold battery / Skip tonight / Prepare for power cut is active or the staged Stop
   * SOC is below the effective reserve, and otherwise presses `start` itself. When omitted, Start presses `start` directly, as before
   * (then no override binds the manual start from this card).
   */
  guarded_start?: string;
}
""")),
    (_blk(r"""
  reserve?: string;
  /** Grid-loss lock state: only an explicit "off" counts as unlocked; absent or anything else is treated as locked (fail-safe). */
"""),
     _blk(r"""
  reserve?: string;
  /** sensor - the battery level in percent (read only). Default: dump_to_grid.battery_soc. Only used to say when a raised reserve is not reached. */
  battery_soc?: string;
  /** Grid-loss lock state: only an explicit "off" counts as unlocked; absent or anything else is treated as locked (fail-safe). */
""")),
    (_blk(r"""
   * Default false. When exactly `true` the card also shows read-only plan views (Tomorrow's Plan and the six-slot TOU timeline).
   * Absent, false or any other value: the card renders exactly as before. The views display only; they make no service call.
"""),
     _blk(r"""
   * Default false. When exactly `true` the card also shows the plan views (Tomorrow's Plan and the six-slot TOU timeline), which only
   * display. When the plan helper entities (home-assistant/packages/ecco_plan_helpers.yaml) are also configured, the plan section adds
   * start and cancel controls for Hold battery, Skip tonight and Prepare for power cut; they call ONLY the package's two guarded scripts.
   * Absent, false or any other value: the card renders exactly as before.
""")),
)


def pre_epc2_config(text: str) -> str:
    """frontend/ecco-energy-actions-card/src/config.ts with exactly epc2's edits undone (a reverter of chain entry epc2, PEX): its text as of the entry before."""
    return _revert(text, CONFIG_EDITS, CONFIG_REL)


pre_epc2_config.edits = CONFIG_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc2_config(text: str) -> str:
    """Applies epc2's edits to frontend/ecco-energy-actions-card/src/config.ts as of the entry before (the round trip)."""
    return _apply(text, CONFIG_EDITS, CONFIG_REL)


# ---- (PEX frozen edit) src/ecco-energy-actions-card.ts -----------------------------------------------------------
SRC_REL = 'frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts'
SRC_EDITS = (
    (_blk(r"""
import { planStyles, renderPlanSection } from "./plan/view.ts";

"""),
     _blk(r"""
import { planStyles, renderPlanSection } from "./plan/view.ts";
import { controlStyles, renderPlanControls } from "./plan/controls.ts";
import { guardedDumpStartCall, isPlanServiceCall } from "./plan/planActions.ts";
import type { PlanServiceCall } from "./plan/planActions.ts";

""")),
    (_blk(r"""
   * Read-only plan views (Tomorrow's Plan, six-slot TOU timeline). `nothing` unless the config has `show_plan: true`; the views
   * display only and make no service call. See src/plan/.
"""),
     _blk(r"""
   * Plan views (Tomorrow's Plan, six-slot TOU timeline). `nothing` unless the config has `show_plan: true`. The views display only; with
   * the plan helper entities configured the section also carries start and cancel controls, which can call ONLY the guarded scripts
   * (src/plan/planActions.ts, checked again in _callPlanService). See src/plan/.
""")),
    (_blk(r"""
    return renderPlanSection(this._config, this.hass?.states);
"""),
     _blk(r"""
    return renderPlanSection(this._config, this.hass?.states, undefined, renderPlanControls((call) => this._callPlanService(call)));
  }

  /** The only way the plan section reaches Home Assistant: a call that is not exactly one of the guarded scripts is dropped. */
  private _callPlanService(call: PlanServiceCall): void {
    if (!isPlanServiceCall(call, this._config?.dump_to_grid?.guarded_start)) return;
    this._callService(call.domain, call.service, call.data as Record<string, unknown>);
  }

  /**
   * Manual Dump to Grid Start. With `dump_to_grid.guarded_start` the ONLY call is that guarded script (it refuses during an override or
   * below the effective reserve, then presses the start button itself); a guarded_start that is not a script id does nothing (fails
   * closed). Without it the start button is pressed directly, as before.
   */
  private _pressDumpStart(dump: NonNullable<EccoEnergyActionsCardConfig["dump_to_grid"]>): void {
    if (dump.guarded_start !== undefined && dump.guarded_start !== "") {
      const guarded = guardedDumpStartCall(dump.guarded_start);
      if (guarded) this._callPlanService(guarded);
      return;
    }
    this._callService("button", "press", { entity_id: dump.start });
""")),
    (_blk(r"""
          @click=${() => this._callService("button", "press", { entity_id: ctx.dump.start })}
"""),
     _blk(r"""
          @click=${() => this._pressDumpStart(ctx.dump)}
""")),
    (_blk(r"""
  static styles = [planStyles, css`
"""),
     _blk(r"""
  static styles = [planStyles, controlStyles, css`
""")),
)


def pre_epc2_card(text: str) -> str:
    """frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts with exactly epc2's edits undone (a reverter of chain entry epc2, PEX): its text as of the entry before."""
    return _revert(text, SRC_EDITS, SRC_REL)


pre_epc2_card.edits = SRC_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc2_card(text: str) -> str:
    """Applies epc2's edits to frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts as of the entry before (the round trip)."""
    return _apply(text, SRC_EDITS, SRC_REL)


# ---- (PEX frozen edit) the rebuilt bundle ------------------------------------------------------------------------
DIST_REL = 'frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js'
DIST_EDITS = (
    (_blk(r"""
var St=Object.defineProperty;var kt=Object.getOwnPropertyDescriptor;var v=(a,r,e,t)=>{for(var i=t>1?void 0:t?kt(r,e):r,n=a.length-1,s;n>=0;n--)(s=a[n])&&(i=(t?s(r,e,i):s(i))||i);return t&&i&&St(r,e,i),i};var Z=globalThis,X=Z.ShadowRoot&&(Z.ShadyCSS===void 0||Z.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,ue=Symbol(),Le=new WeakMap,B=class{constructor(r,e,t){if(this._$cssResult$=!0,t!==ue)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=r,this.t=e}get styleSheet(){let r=this.o,e=this.t;if(X&&r===void 0){let t=e!==void 0&&e.length===1;t&&(r=Le.get(e)),r===void 0&&((this.o=r=new CSSStyleSheet).replaceSync(this.cssText),t&&Le.set(e,r))}return r}toString(){return this.cssText}},Ue=a=>new B(typeof a=="string"?a:a+"",void 0,ue),pe=(a,...r)=>{let e=a.length===1?a[0]:r.reduce((t,i,n)=>t+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+a[n+1],a[0]);return new B(e,a,ue)},Be=(a,r)=>{if(X)a.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of r){let t=document.createElement("style"),i=Z.litNonce;i!==void 0&&t.setAttribute("nonce",i),t.textContent=e.cssText,a.appendChild(t)}},he=X?a=>a:a=>a instanceof CSSStyleSheet?(r=>{let e="";for(let t of r.cssRules)e+=t.cssText;return Ue(e)})(a):a;var{is:$t,defineProperty:Dt,getOwnPropertyDescriptor:Et,getOwnPropertyNames:Tt,getOwnPropertySymbols:At,getPrototypeOf:Rt}=Object,ee=globalThis,He=ee.trustedTypes,Pt=He?He.emptyScript:"",Ct=ee.reactiveElementPolyfillSupport,H=(a,r)=>a,z={toAttribute(a,r){switch(r){case Boolean:a=a?Pt:null;break;case Object:case Array:a=a==null?a:JSON.stringify(a)}return a},fromAttribute(a,r){let e=a;switch(r){case Boolean:e=a!==null;break;case Number:e=a===null?null:Number(a);break;case Object:case Array:try{e=JSON.parse(a)}catch{e=null}}return e}},te=(a,r)=>!$t(a,r),ze={attribute:!0,type:String,converter:z,reflect:!1,useDefault:!1,hasChanged:te};Symbol.metadata??=Symbol("metadata"),ee.litPropertyMetadata??=new WeakMap;var E=class extends HTMLElement{static addInitializer(r){this._$Ei(),(this.l??=[]).push(r)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(r,e=ze){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(r)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(r,e),!e.noAccessor){let t=Symbol(),i=this.getPropertyDescriptor(r,t,e);i!==void 0&&Dt(this.prototype,r,i)}}static getPropertyDescriptor(r,e,t){let{get:i,set:n}=Et(this.prototype,r)??{get(){return this[e]},set(s){this[e]=s}};return{get:i,set(s){let o=i?.call(this);n?.call(this,s),this.requestUpdate(r,o,t)},configurable:!0,enumerable:!0}}static getPropertyOptions(r){return this.elementProperties.get(r)??ze}static _$Ei(){if(this.hasOwnProperty(H("elementProperties")))return;let r=Rt(this);r.finalize(),r.l!==void 0&&(this.l=[...r.l]),this.elementProperties=new Map(r.elementProperties)}static finalize(){if(this.hasOwnProperty(H("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(H("properties"))){let e=this.properties,t=[...Tt(e),...At(e)];for(let i of t)this.createProperty(i,e[i])}let r=this[Symbol.metadata];if(r!==null){let e=litPropertyMetadata.get(r);if(e!==void 0)for(let[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(let[e,t]of this.elementProperties){let i=this._$Eu(e,t);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(r){let e=[];if(Array.isArray(r)){let t=new Set(r.flat(1/0).reverse());for(let i of t)e.unshift(he(i))}else r!==void 0&&e.push(he(r));return e}static _$Eu(r,e){let t=e.attribute;return t===!1?void 0:typeof t=="string"?t:typeof r=="string"?r.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(r=>this.enableUpdating=r),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(r=>r(this))}addController(r){(this._$EO??=new Set).add(r),this.renderRoot!==void 0&&this.isConnected&&r.hostConnected?.()}removeController(r){this._$EO?.delete(r)}_$E_(){let r=new Map,e=this.constructor.elementProperties;for(let t of e.keys())this.hasOwnProperty(t)&&(r.set(t,this[t]),delete this[t]);r.size>0&&(this._$Ep=r)}createRenderRoot(){let r=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Be(r,this.constructor.elementStyles),r}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(r=>r.hostConnected?.())}enableUpdating(r){}disconnectedCallback(){this._$EO?.forEach(r=>r.hostDisconnected?.())}attributeChangedCallback(r,e,t){this._$AK(r,t)}_$ET(r,e){let t=this.constructor.elementProperties.get(r),i=this.constructor._$Eu(r,t);if(i!==void 0&&t.reflect===!0){let n=(t.converter?.toAttribute!==void 0?t.converter:z).toAttribute(e,t.type);this._$Em=r,n==null?this.removeAttribute(i):this.setAttribute(i,n),this._$Em=null}}_$AK(r,e){let t=this.constructor,i=t._$Eh.get(r);if(i!==void 0&&this._$Em!==i){let n=t.getPropertyOptions(i),s=typeof n.converter=="function"?{fromAttribute:n.converter}:n.converter?.fromAttribute!==void 0?n.converter:z;this._$Em=i;let o=s.fromAttribute(e,n.type);this[i]=o??this._$Ej?.get(i)??o,this._$Em=null}}requestUpdate(r,e,t,i=!1,n){if(r!==void 0){let s=this.constructor;if(i===!1&&(n=this[r]),t??=s.getPropertyOptions(r),!((t.hasChanged??te)(n,e)||t.useDefault&&t.reflect&&n===this._$Ej?.get(r)&&!this.hasAttribute(s._$Eu(r,t))))return;this.C(r,e,t)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(r,e,{useDefault:t,reflect:i,wrapped:n},s){t&&!(this._$Ej??=new Map).has(r)&&(this._$Ej.set(r,s??e??this[r]),n!==!0||s!==void 0)||(this._$AL.has(r)||(this.hasUpdated||t||(e=void 0),this._$AL.set(r,e)),i===!0&&this._$Em!==r&&(this._$Eq??=new Set).add(r))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let r=this.scheduleUpdate();return r!=null&&await r,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,n]of this._$Ep)this[i]=n;this._$Ep=void 0}let t=this.constructor.elementProperties;if(t.size>0)for(let[i,n]of t){let{wrapped:s}=n,o=this[i];s!==!0||this._$AL.has(i)||o===void 0||this.C(i,void 0,n,o)}}let r=!1,e=this._$AL;try{r=this.shouldUpdate(e),r?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(t){throw r=!1,this._$EM(),t}r&&this._$AE(e)}willUpdate(r){}_$AE(r){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(r)),this.updated(r)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(r){return!0}update(r){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(r){}firstUpdated(r){}};E.elementStyles=[],E.shadowRootOptions={mode:"open"},E[H("elementProperties")]=new Map,E[H("finalized")]=new Map,Ct?.({ReactiveElement:E}),(ee.reactiveElementVersions??=[]).push("2.1.2");var ye=globalThis,We=a=>a,re=ye.trustedTypes,Ge=re?re.createPolicy("lit-html",{createHTML:a=>a}):void 0,Je="$lit$",A=`lit$${Math.random().toFixed(9).slice(2)}$`,Ze="?"+A,Nt=`<${Ze}>`,N=document,G=()=>N.createComment(""),j=a=>a===null||typeof a!="object"&&typeof a!="function",we=Array.isArray,Ot=a=>we(a)||typeof a?.[Symbol.iterator]=="function",me=`[ 	
\f\r]`,W=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,je=/-->/g,qe=/>/g,P=RegExp(`>|${me}(?:([^\\s"'>=/]+)(${me}*=${me}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Ye=/'/g,Ke=/"/g,Xe=/^(?:script|style|textarea|title)$/i,xe=a=>(r,...e)=>({_$litType$:a,strings:r,values:e}),u=xe(1),_r=xe(2),gr=xe(3),O=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),Qe=new WeakMap,C=N.createTreeWalker(N,129);function et(a,r){if(!we(a)||!a.hasOwnProperty("raw"))throw Error("invalid template strings array");return Ge!==void 0?Ge.createHTML(r):r}var Mt=(a,r)=>{let e=a.length-1,t=[],i,n=r===2?"<svg>":r===3?"<math>":"",s=W;for(let o=0;o<e;o++){let l=a[o],d,c,p=-1,y=0;for(;y<l.length&&(s.lastIndex=y,c=s.exec(l),c!==null);)y=s.lastIndex,s===W?c[1]==="!--"?s=je:c[1]!==void 0?s=qe:c[2]!==void 0?(Xe.test(c[2])&&(i=RegExp("</"+c[2],"g")),s=P):c[3]!==void 0&&(s=P):s===P?c[0]===">"?(s=i??W,p=-1):c[1]===void 0?p=-2:(p=s.lastIndex-c[2].length,d=c[1],s=c[3]===void 0?P:c[3]==='"'?Ke:Ye):s===Ke||s===Ye?s=P:s===je||s===qe?s=W:(s=P,i=void 0);let _=s===P&&a[o+1].startsWith("/>")?" ":"";n+=s===W?l+Nt:p>=0?(t.push(d),l.slice(0,p)+Je+l.slice(p)+A+_):l+A+(p===-2?o:_)}return[et(a,n+(a[e]||"<?>")+(r===2?"</svg>":r===3?"</math>":"")),t]},q=class a{constructor({strings:r,_$litType$:e},t){let i;this.parts=[];let n=0,s=0,o=r.length-1,l=this.parts,[d,c]=Mt(r,e);if(this.el=a.createElement(d,t),C.currentNode=this.el.content,e===2||e===3){let p=this.el.content.firstChild;p.replaceWith(...p.childNodes)}for(;(i=C.nextNode())!==null&&l.length<o;){if(i.nodeType===1){if(i.hasAttributes())for(let p of i.getAttributeNames())if(p.endsWith(Je)){let y=c[s++],_=i.getAttribute(p).split(A),w=/([.?@])?(.*)/.exec(y);l.push({type:1,index:n,name:w[2],strings:_,ctor:w[1]==="."?_e:w[1]==="?"?ge:w[1]==="@"?be:V}),i.removeAttribute(p)}else p.startsWith(A)&&(l.push({type:6,index:n}),i.removeAttribute(p));if(Xe.test(i.tagName)){let p=i.textContent.split(A),y=p.length-1;if(y>0){i.textContent=re?re.emptyScript:"";for(let _=0;_<y;_++)i.append(p[_],G()),C.nextNode(),l.push({type:2,index:++n});i.append(p[y],G())}}}else if(i.nodeType===8)if(i.data===Ze)l.push({type:2,index:n});else{let p=-1;for(;(p=i.data.indexOf(A,p+1))!==-1;)l.push({type:7,index:n}),p+=A.length-1}n++}}static createElement(r,e){let t=N.createElement("template");return t.innerHTML=r,t}};function I(a,r,e=a,t){if(r===O)return r;let i=t!==void 0?e._$Co?.[t]:e._$Cl,n=j(r)?void 0:r._$litDirective$;return i?.constructor!==n&&(i?._$AO?.(!1),n===void 0?i=void 0:(i=new n(a),i._$AT(a,e,t)),t!==void 0?(e._$Co??=[])[t]=i:e._$Cl=i),i!==void 0&&(r=I(a,i._$AS(a,r.values),i,t)),r}var fe=class{constructor(r,e){this._$AV=[],this._$AN=void 0,this._$AD=r,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(r){let{el:{content:e},parts:t}=this._$AD,i=(r?.creationScope??N).importNode(e,!0);C.currentNode=i;let n=C.nextNode(),s=0,o=0,l=t[0];for(;l!==void 0;){if(s===l.index){let d;l.type===2?d=new Y(n,n.nextSibling,this,r):l.type===1?d=new l.ctor(n,l.name,l.strings,this,r):l.type===6&&(d=new ve(n,this,r)),this._$AV.push(d),l=t[++o]}s!==l?.index&&(n=C.nextNode(),s++)}return C.currentNode=N,i}p(r){let e=0;for(let t of this._$AV)t!==void 0&&(t.strings!==void 0?(t._$AI(r,t,e),e+=t.strings.length-2):t._$AI(r[e])),e++}},Y=class a{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(r,e,t,i){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=r,this._$AB=e,this._$AM=t,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let r=this._$AA.parentNode,e=this._$AM;return e!==void 0&&r?.nodeType===11&&(r=e.parentNode),r}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(r,e=this){r=I(this,r,e),j(r)?r===h||r==null||r===""?(this._$AH!==h&&this._$AR(),this._$AH=h):r!==this._$AH&&r!==O&&this._(r):r._$litType$!==void 0?this.$(r):r.nodeType!==void 0?this.T(r):Ot(r)?this.k(r):this._(r)}O(r){return this._$AA.parentNode.insertBefore(r,this._$AB)}T(r){this._$AH!==r&&(this._$AR(),this._$AH=this.O(r))}_(r){this._$AH!==h&&j(this._$AH)?this._$AA.nextSibling.data=r:this.T(N.createTextNode(r)),this._$AH=r}$(r){let{values:e,_$litType$:t}=r,i=typeof t=="number"?this._$AC(r):(t.el===void 0&&(t.el=q.createElement(et(t.h,t.h[0]),this.options)),t);if(this._$AH?._$AD===i)this._$AH.p(e);else{let n=new fe(i,this),s=n.u(this.options);n.p(e),this.T(s),this._$AH=n}}_$AC(r){let e=Qe.get(r.strings);return e===void 0&&Qe.set(r.strings,e=new q(r)),e}k(r){we(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,t,i=0;for(let n of r)i===e.length?e.push(t=new a(this.O(G()),this.O(G()),this,this.options)):t=e[i],t._$AI(n),i++;i<e.length&&(this._$AR(t&&t._$AB.nextSibling,i),e.length=i)}_$AR(r=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);r!==this._$AB;){let t=We(r).nextSibling;We(r).remove(),r=t}}setConnected(r){this._$AM===void 0&&(this._$Cv=r,this._$AP?.(r))}},V=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(r,e,t,i,n){this.type=1,this._$AH=h,this._$AN=void 0,this.element=r,this.name=e,this._$AM=i,this.options=n,t.length>2||t[0]!==""||t[1]!==""?(this._$AH=Array(t.length-1).fill(new String),this.strings=t):this._$AH=h}_$AI(r,e=this,t,i){let n=this.strings,s=!1;if(n===void 0)r=I(this,r,e,0),s=!j(r)||r!==this._$AH&&r!==O,s&&(this._$AH=r);else{let o=r,l,d;for(r=n[0],l=0;l<n.length-1;l++)d=I(this,o[t+l],e,l),d===O&&(d=this._$AH[l]),s||=!j(d)||d!==this._$AH[l],d===h?r=h:r!==h&&(r+=(d??"")+n[l+1]),this._$AH[l]=d}s&&!i&&this.j(r)}j(r){r===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,r??"")}},_e=class extends V{constructor(){super(...arguments),this.type=3}j(r){this.element[this.name]=r===h?void 0:r}},ge=class extends V{constructor(){super(...arguments),this.type=4}j(r){this.element.toggleAttribute(this.name,!!r&&r!==h)}},be=class extends V{constructor(r,e,t,i,n){super(r,e,t,i,n),this.type=5}_$AI(r,e=this){if((r=I(this,r,e,0)??h)===O)return;let t=this._$AH,i=r===h&&t!==h||r.capture!==t.capture||r.once!==t.once||r.passive!==t.passive,n=r!==h&&(t===h||i);i&&this.element.removeEventListener(this.name,this,t),n&&this.element.addEventListener(this.name,this,r),this._$AH=r}handleEvent(r){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,r):this._$AH.handleEvent(r)}},ve=class{constructor(r,e,t){this.element=r,this.type=6,this._$AN=void 0,this._$AM=e,this.options=t}get _$AU(){return this._$AM._$AU}_$AI(r){I(this,r)}};var Ft=ye.litHtmlPolyfillSupport;Ft?.(q,Y),(ye.litHtmlVersions??=[]).push("3.3.3");var tt=(a,r,e)=>{let t=e?.renderBefore??r,i=t._$litPart$;if(i===void 0){let n=e?.renderBefore??null;t._$litPart$=i=new Y(r.insertBefore(G(),n),n,void 0,e??{})}return i._$AI(a),i};var Se=globalThis,R=class extends E{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let r=super.createRenderRoot();return this.renderOptions.renderBefore??=r.firstChild,r}update(r){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(r),this._$Do=tt(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return O}};R._$litElement$=!0,R.finalized=!0,Se.litElementHydrateSupport?.({LitElement:R});var It=Se.litElementPolyfillSupport;It?.({LitElement:R});(Se.litElementVersions??=[]).push("4.2.2");var rt=a=>(r,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(a,r)}):customElements.define(a,r)};var Vt={attribute:!0,type:String,converter:z,reflect:!1,hasChanged:te},Lt=(a=Vt,r,e)=>{let{kind:t,metadata:i}=e,n=globalThis.litPropertyMetadata.get(i);if(n===void 0&&globalThis.litPropertyMetadata.set(i,n=new Map),t==="setter"&&((a=Object.create(a)).wrapped=!0),n.set(e.name,a),t==="accessor"){let{name:s}=e;return{set(o){let l=r.get.call(this);r.set.call(this,o),this.requestUpdate(s,l,a,!0,o)},init(o){return o!==void 0&&this.C(s,void 0,a,o),o}}}if(t==="setter"){let{name:s}=e;return function(o){let l=this[s];r.call(this,o),this.requestUpdate(s,l,a,!0,o)}}throw Error("Unsupported decorator location: "+t)};function ie(a){return(r,e)=>typeof e=="object"?Lt(a,r,e):((t,i,n)=>{let s=i.hasOwnProperty(n);return i.constructor.createProperty(n,t),s?Object.getOwnPropertyDescriptor(i,n):void 0})(a,r,e)}function x(a){return ie({...a,state:!0,attribute:!1})}var ke="Energy Actions";var Ut=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Bt=/DEFERRED/i,Ht=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function ne(a){let{active:r,armed:e,operationInProgress:t,statusText:i}=a;return r===null||e===null||t===null?"unavailable":i&&Ut.test(i)?"recovery_attention":i&&Bt.test(i)?"deferred":i&&Ht.test(i)?"busy":r?"active":t?"busy":e?"armed":"ready"}function it(a){return a==="armed"}function $e(a){return a!=="busy"&&a!=="unavailable"}function at(a){return a==="ready"||a==="armed"}var zt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function nt(a){return zt[a]}var Wt=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Gt=/DEFERRED/i,jt=/^(RESTORING|STARTING)/i;function se(a){let{active:r,armed:e,operationInProgress:t,snapshotValid:i,statusText:n}=a;return r===null||e===null||t===null||i===null?"unavailable":n&&Wt.test(n)?"recovery_attention":n&&Gt.test(n)?"deferred":n&&jt.test(n)?"busy":r?"active":t?"busy":i?"deferred":e?"armed":"ready"}function st(a){return a==="armed"}function oe(a){return a!=="busy"&&a!=="unavailable"}function ot(a){return a==="ready"||a==="armed"}var qt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function Yt(a){return qt[a]}function De(a,r){return a==="ready"&&r===!0?"scheduled":a}function Ee(a){return a==="scheduled"?"Scheduled":a==="interlocked"?"Interlocked":Yt(a)}var Kt=/target (\d+)\s*W export/i,Qt=/Stop SOC (\d+)\s*%/i;function lt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Kt.exec(r):null;return e?Number(e[1]):null}function dt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Qt.exec(r):null;return e?Number(e[1]):null}var Jt=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function ct(a,r){return r===!0&&!!a&&Jt.test(a)}var Zt=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,Xt=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,er=/OPERATOR DECISION REQUIRED/i,tr=/press End Free Power|retry(?:ing)? restore/i,rr=/\bRECOVERY REQUIRED\b/i,ir=/snapshot retained/i,ar=/RESTORE BLOCKED/i;function ut(a){let r=a.statusText??"",e=a.snapshotValid;return Zt.test(r)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:Xt.test(r)&&e===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:er.test(r)&&tr.test(r)&&e===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:rr.test(r)&&e===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:ir.test(r)&&e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:ar.test(r)?e===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var nr=new Set(["active","busy","recovery_attention","deferred"]);function sr(a){return a!==null&&nr.has(a)}function K(a,r){return(a==="ready"||a==="armed")&&sr(r)}function Q(a,r){return a&&!r}function Te(a,r){switch(r){case"busy":return`${a} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${a} requires recovery before this can be used.`;default:return`${a} currently owns inverter control.`}}var pt=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function ht(a){let r=pt.indexOf(a);return r<0?pt.length:r}function mt(a,r){return a!=="unavailable"||r!=="unavailable"}function Ae(a,r){return ht(r)<ht(a)?"dump_to_grid":"free_power"}function ft(a){switch(a){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function _t(a){switch(a){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function gt(a){return a==="dump_to_grid"?"Dump to Grid":"Free Power"}function bt(a,r,e){let t=e?.trim()??"";return t?`${a}: ${r} - ${t}`:`${a}: ${r}`}function Re(a){return a.armed===!0?"armed":"hidden"}function Pe(a){return!!a&&/^REJECTED/i.test(a.trim())}function Ce(a){return!!a&&/^BLOCKED/i.test(a.trim())}function Ne(a){return a===!0}function Oe(a,r){return a==="ready"&&r==="armed"?"scheduled":a}function Me(a){return{domain:"input_boolean",service:"turn_on",data:{entity_id:a}}}function Fe(a){return{domain:"script",service:"turn_on",data:{entity_id:a}}}function vt(a,r){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:a,datetime:r}}}function Ie(a,r){return{domain:"input_number",service:"set_value",data:{entity_id:a,value:r}}}function yt(a,r){return r===null||!Number.isFinite(r)||r<=0?a:Math.min(a,r)}var or=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function M(a){if(!a)return null;let r=or.exec(a.trim());if(!r)return null;let[,e,t,i,n,s,o]=r,l=new Date(Number(e),Number(t)-1,Number(i),Number(n),Number(s),Number(o));return Number.isNaN(l.getTime())?null:l}function wt(a){let r=e=>e.toString().padStart(2,"0");return`${a.getFullYear()}-${r(a.getMonth()+1)}-${r(a.getDate())} ${r(a.getHours())}:${r(a.getMinutes())}:${r(a.getSeconds())}`}var lr=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],dr=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Ve(a){let r=lr[a.getDay()],e=a.getDate(),t=dr[a.getMonth()],i=a.getHours().toString().padStart(2,"0"),n=a.getMinutes().toString().padStart(2,"0");return`${r} ${e} ${t} \u2022 ${i}:${n}`}function J(a,r){let e=a-r;if(e<=0)return null;let t=Math.floor(e/1e3),i=Math.floor(t/3600),n=Math.floor(t%3600/60),s=t%60;return i>0?`${i}h ${n}m`:n>0?`${n}m ${s.toString().padStart(2,"0")}s`:`${s}s`}function T(a){return a==null||Number.isNaN(a)?"--":Math.abs(a)>=1e3?`${(a/1e3).toFixed(2)} kW`:`${a.toFixed(0)} W`}function F(a){if(a==null||Number.isNaN(a))return"--";let r=Math.round(a);if(r<60)return`${r} min`;let e=Math.floor(r/60),t=r%60;return t===0?`${e}h`:`${e}h ${t}m`}function L(a){return a==null||Number.isNaN(a)?"--":`${Math.round(a)}%`}function f(a){if(a==null||a==="unknown"||a==="unavailable"||a==="")return null;let r=Number(a);return Number.isFinite(r)?r:null}function m(a){return a==null||a==="unknown"||a==="unavailable"||a===""?null:a==="on"}var le=4e3,cr=1e3,g=class extends R{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:ke,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!e.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=e}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(e){return!!this._config}willUpdate(){let e=this._config?.free_power;if(e){this._pendingPower!==void 0&&f(this._entityState(e.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&f(this._entityState(e.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let n=m(this._entityState(e.active)),s=m(this._entityState(e.write_enable)),o=m(this._entityState(e.operation_in_progress)),l=this._entityState(e.status),d=ne({active:n,armed:s,operationInProgress:o,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==d&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=d}let t=this._config?.schedule;t&&(this._pendingSchedulePower!==void 0&&f(this._entityState(t.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&f(this._entityState(t.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&f(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&f(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&f(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let n=i.schedule;n&&(this._pendingDumpSchedulePower!==void 0&&f(this._entityState(n.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&f(this._entityState(n.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&f(this._entityState(n.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let s=m(this._entityState(i.active)),o=m(this._entityState(i.write_enable)),l=m(this._entityState(i.operation_in_progress)),d=m(this._entityState(i.snapshot_valid)),c=this._entityState(i.status),p=se({active:s,armed:o,operationInProgress:l,snapshotValid:d,statusText:c});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==p&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=p}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let n=this._trackSummary();mt(n.fp.state,n.dump.state)&&(this._track=Ae(n.fp.state,n.dump.state))}}updated(){let e=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();e&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},cr):!e&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let e=this._config?.free_power;return e?m(this._entityState(e.active))===!0:!1}_scheduleArmed(){let e=this._config?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_dumpActive(){let e=this._config?.dump_to_grid;return e?m(this._entityState(e.active))===!0:!1}_dumpScheduleArmed(){let e=this._config?.dump_to_grid?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_freePowerVisualStateForInterlock(){let e=this._config?.free_power;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=this._entityState(e.status);return ne({active:t,armed:i,operationInProgress:n,statusText:s})}_dumpVisualStateForInterlock(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status);return se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o})}_entityState(e){if(!(!e||!this.hass))return this.hass.states[e]?.state}_entity(e){if(!(!e||!this.hass))return this.hass.states[e]}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_callService(e,t,i){this.hass?.callService&&this.hass.callService(e,t,i)}_callServiceObj(e){this._callService(e.domain,e.service,e.data)}render(){if(!this._config)return u``;let e=this._config.title??ke;return this._config.layout==="tabbed"?this._renderTabbed(e):u`
"""),
     _blk(r"""
var vr=Object.defineProperty;var _r=Object.getOwnPropertyDescriptor;var D=(t,n,e,r)=>{for(var i=r>1?void 0:r?_r(n,e):n,a=t.length-1,o;a>=0;a--)(o=t[a])&&(i=(r?o(n,e,i):o(i))||i);return r&&i&&vr(n,e,i),i};var He=globalThis,Ge=He.ShadowRoot&&(He.ShadyCSS===void 0||He.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,rt=Symbol(),Yt=new WeakMap,Ee=class{constructor(n,e,r){if(this._$cssResult$=!0,r!==rt)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=n,this.t=e}get styleSheet(){let n=this.o,e=this.t;if(Ge&&n===void 0){let r=e!==void 0&&e.length===1;r&&(n=Yt.get(e)),n===void 0&&((this.o=n=new CSSStyleSheet).replaceSync(this.cssText),r&&Yt.set(e,n))}return n}toString(){return this.cssText}},qt=t=>new Ee(typeof t=="string"?t:t+"",void 0,rt),ce=(t,...n)=>{let e=t.length===1?t[0]:n.reduce((r,i,a)=>r+(o=>{if(o._$cssResult$===!0)return o.cssText;if(typeof o=="number")return o;throw Error("Value passed to 'css' function must be a 'css' function result: "+o+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+t[a+1],t[0]);return new Ee(e,t,rt)},Xt=(t,n)=>{if(Ge)t.adoptedStyleSheets=n.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of n){let r=document.createElement("style"),i=He.litNonce;i!==void 0&&r.setAttribute("nonce",i),r.textContent=e.cssText,t.appendChild(r)}},it=Ge?t=>t:t=>t instanceof CSSStyleSheet?(n=>{let e="";for(let r of n.cssRules)e+=r.cssText;return qt(e)})(t):t;var{is:wr,defineProperty:yr,getOwnPropertyDescriptor:xr,getOwnPropertyNames:Sr,getOwnPropertySymbols:Er,getPrototypeOf:kr}=Object,Be=globalThis,Qt=Be.trustedTypes,Mr=Qt?Qt.emptyScript:"",Pr=Be.reactiveElementPolyfillSupport,ke=(t,n)=>t,Me={toAttribute(t,n){switch(n){case Boolean:t=t?Mr:null;break;case Object:case Array:t=t==null?t:JSON.stringify(t)}return t},fromAttribute(t,n){let e=t;switch(n){case Boolean:e=t!==null;break;case Number:e=t===null?null:Number(t);break;case Object:case Array:try{e=JSON.parse(t)}catch{e=null}}return e}},Ke=(t,n)=>!wr(t,n),Jt={attribute:!0,type:String,converter:Me,reflect:!1,useDefault:!1,hasChanged:Ke};Symbol.metadata??=Symbol("metadata"),Be.litPropertyMetadata??=new WeakMap;var Q=class extends HTMLElement{static addInitializer(n){this._$Ei(),(this.l??=[]).push(n)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(n,e=Jt){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(n)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(n,e),!e.noAccessor){let r=Symbol(),i=this.getPropertyDescriptor(n,r,e);i!==void 0&&yr(this.prototype,n,i)}}static getPropertyDescriptor(n,e,r){let{get:i,set:a}=xr(this.prototype,n)??{get(){return this[e]},set(o){this[e]=o}};return{get:i,set(o){let s=i?.call(this);a?.call(this,o),this.requestUpdate(n,s,r)},configurable:!0,enumerable:!0}}static getPropertyOptions(n){return this.elementProperties.get(n)??Jt}static _$Ei(){if(this.hasOwnProperty(ke("elementProperties")))return;let n=kr(this);n.finalize(),n.l!==void 0&&(this.l=[...n.l]),this.elementProperties=new Map(n.elementProperties)}static finalize(){if(this.hasOwnProperty(ke("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(ke("properties"))){let e=this.properties,r=[...Sr(e),...Er(e)];for(let i of r)this.createProperty(i,e[i])}let n=this[Symbol.metadata];if(n!==null){let e=litPropertyMetadata.get(n);if(e!==void 0)for(let[r,i]of e)this.elementProperties.set(r,i)}this._$Eh=new Map;for(let[e,r]of this.elementProperties){let i=this._$Eu(e,r);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(n){let e=[];if(Array.isArray(n)){let r=new Set(n.flat(1/0).reverse());for(let i of r)e.unshift(it(i))}else n!==void 0&&e.push(it(n));return e}static _$Eu(n,e){let r=e.attribute;return r===!1?void 0:typeof r=="string"?r:typeof n=="string"?n.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(n=>this.enableUpdating=n),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(n=>n(this))}addController(n){(this._$EO??=new Set).add(n),this.renderRoot!==void 0&&this.isConnected&&n.hostConnected?.()}removeController(n){this._$EO?.delete(n)}_$E_(){let n=new Map,e=this.constructor.elementProperties;for(let r of e.keys())this.hasOwnProperty(r)&&(n.set(r,this[r]),delete this[r]);n.size>0&&(this._$Ep=n)}createRenderRoot(){let n=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Xt(n,this.constructor.elementStyles),n}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(n=>n.hostConnected?.())}enableUpdating(n){}disconnectedCallback(){this._$EO?.forEach(n=>n.hostDisconnected?.())}attributeChangedCallback(n,e,r){this._$AK(n,r)}_$ET(n,e){let r=this.constructor.elementProperties.get(n),i=this.constructor._$Eu(n,r);if(i!==void 0&&r.reflect===!0){let a=(r.converter?.toAttribute!==void 0?r.converter:Me).toAttribute(e,r.type);this._$Em=n,a==null?this.removeAttribute(i):this.setAttribute(i,a),this._$Em=null}}_$AK(n,e){let r=this.constructor,i=r._$Eh.get(n);if(i!==void 0&&this._$Em!==i){let a=r.getPropertyOptions(i),o=typeof a.converter=="function"?{fromAttribute:a.converter}:a.converter?.fromAttribute!==void 0?a.converter:Me;this._$Em=i;let s=o.fromAttribute(e,a.type);this[i]=s??this._$Ej?.get(i)??s,this._$Em=null}}requestUpdate(n,e,r,i=!1,a){if(n!==void 0){let o=this.constructor;if(i===!1&&(a=this[n]),r??=o.getPropertyOptions(n),!((r.hasChanged??Ke)(a,e)||r.useDefault&&r.reflect&&a===this._$Ej?.get(n)&&!this.hasAttribute(o._$Eu(n,r))))return;this.C(n,e,r)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(n,e,{useDefault:r,reflect:i,wrapped:a},o){r&&!(this._$Ej??=new Map).has(n)&&(this._$Ej.set(n,o??e??this[n]),a!==!0||o!==void 0)||(this._$AL.has(n)||(this.hasUpdated||r||(e=void 0),this._$AL.set(n,e)),i===!0&&this._$Em!==n&&(this._$Eq??=new Set).add(n))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let n=this.scheduleUpdate();return n!=null&&await n,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,a]of this._$Ep)this[i]=a;this._$Ep=void 0}let r=this.constructor.elementProperties;if(r.size>0)for(let[i,a]of r){let{wrapped:o}=a,s=this[i];o!==!0||this._$AL.has(i)||s===void 0||this.C(i,void 0,a,s)}}let n=!1,e=this._$AL;try{n=this.shouldUpdate(e),n?(this.willUpdate(e),this._$EO?.forEach(r=>r.hostUpdate?.()),this.update(e)):this._$EM()}catch(r){throw n=!1,this._$EM(),r}n&&this._$AE(e)}willUpdate(n){}_$AE(n){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(n)),this.updated(n)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(n){return!0}update(n){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(n){}firstUpdated(n){}};Q.elementStyles=[],Q.shadowRootOptions={mode:"open"},Q[ke("elementProperties")]=new Map,Q[ke("finalized")]=new Map,Pr?.({ReactiveElement:Q}),(Be.reactiveElementVersions??=[]).push("2.1.2");var dt=globalThis,Zt=t=>t,je=dt.trustedTypes,en=je?je.createPolicy("lit-html",{createHTML:t=>t}):void 0,sn="$lit$",ie=`lit$${Math.random().toFixed(9).slice(2)}$`,ln="?"+ie,Rr=`<${ln}>`,pe=document,Re=()=>pe.createComment(""),De=t=>t===null||typeof t!="object"&&typeof t!="function",pt=Array.isArray,Dr=t=>pt(t)||typeof t?.[Symbol.iterator]=="function",at=`[ 	
\f\r]`,Pe=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,tn=/-->/g,nn=/>/g,ue=RegExp(`>|${at}(?:([^\\s"'>=/]+)(${at}*=${at}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),rn=/'/g,an=/"/g,cn=/^(?:script|style|textarea|title)$/i,ht=t=>(n,...e)=>({_$litType$:t,strings:n,values:e}),p=ht(1),va=ht(2),_a=ht(3),he=Symbol.for("lit-noChange"),m=Symbol.for("lit-nothing"),on=new WeakMap,de=pe.createTreeWalker(pe,129);function un(t,n){if(!pt(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return en!==void 0?en.createHTML(n):n}var Tr=(t,n)=>{let e=t.length-1,r=[],i,a=n===2?"<svg>":n===3?"<math>":"",o=Pe;for(let s=0;s<e;s++){let l=t[s],u,c,d=-1,b=0;for(;b<l.length&&(o.lastIndex=b,c=o.exec(l),c!==null);)b=o.lastIndex,o===Pe?c[1]==="!--"?o=tn:c[1]!==void 0?o=nn:c[2]!==void 0?(cn.test(c[2])&&(i=RegExp("</"+c[2],"g")),o=ue):c[3]!==void 0&&(o=ue):o===ue?c[0]===">"?(o=i??Pe,d=-1):c[1]===void 0?d=-2:(d=o.lastIndex-c[2].length,u=c[1],o=c[3]===void 0?ue:c[3]==='"'?an:rn):o===an||o===rn?o=ue:o===tn||o===nn?o=Pe:(o=ue,i=void 0);let v=o===ue&&t[s+1].startsWith("/>")?" ":"";a+=o===Pe?l+Rr:d>=0?(r.push(u),l.slice(0,d)+sn+l.slice(d)+ie+v):l+ie+(d===-2?s:v)}return[un(t,a+(t[e]||"<?>")+(n===2?"</svg>":n===3?"</math>":"")),r]},Te=class t{constructor({strings:n,_$litType$:e},r){let i;this.parts=[];let a=0,o=0,s=n.length-1,l=this.parts,[u,c]=Tr(n,e);if(this.el=t.createElement(u,r),de.currentNode=this.el.content,e===2||e===3){let d=this.el.content.firstChild;d.replaceWith(...d.childNodes)}for(;(i=de.nextNode())!==null&&l.length<s;){if(i.nodeType===1){if(i.hasAttributes())for(let d of i.getAttributeNames())if(d.endsWith(sn)){let b=c[o++],v=i.getAttribute(d).split(ie),g=/([.?@])?(.*)/.exec(b);l.push({type:1,index:a,name:g[2],strings:v,ctor:g[1]==="."?st:g[1]==="?"?lt:g[1]==="@"?ct:_e}),i.removeAttribute(d)}else d.startsWith(ie)&&(l.push({type:6,index:a}),i.removeAttribute(d));if(cn.test(i.tagName)){let d=i.textContent.split(ie),b=d.length-1;if(b>0){i.textContent=je?je.emptyScript:"";for(let v=0;v<b;v++)i.append(d[v],Re()),de.nextNode(),l.push({type:2,index:++a});i.append(d[b],Re())}}}else if(i.nodeType===8)if(i.data===ln)l.push({type:2,index:a});else{let d=-1;for(;(d=i.data.indexOf(ie,d+1))!==-1;)l.push({type:7,index:a}),d+=ie.length-1}a++}}static createElement(n,e){let r=pe.createElement("template");return r.innerHTML=n,r}};function ve(t,n,e=t,r){if(n===he)return n;let i=r!==void 0?e._$Co?.[r]:e._$Cl,a=De(n)?void 0:n._$litDirective$;return i?.constructor!==a&&(i?._$AO?.(!1),a===void 0?i=void 0:(i=new a(t),i._$AT(t,e,r)),r!==void 0?(e._$Co??=[])[r]=i:e._$Cl=i),i!==void 0&&(n=ve(t,i._$AS(t,n.values),i,r)),n}var ot=class{constructor(n,e){this._$AV=[],this._$AN=void 0,this._$AD=n,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(n){let{el:{content:e},parts:r}=this._$AD,i=(n?.creationScope??pe).importNode(e,!0);de.currentNode=i;let a=de.nextNode(),o=0,s=0,l=r[0];for(;l!==void 0;){if(o===l.index){let u;l.type===2?u=new Ae(a,a.nextSibling,this,n):l.type===1?u=new l.ctor(a,l.name,l.strings,this,n):l.type===6&&(u=new ut(a,this,n)),this._$AV.push(u),l=r[++s]}o!==l?.index&&(a=de.nextNode(),o++)}return de.currentNode=pe,i}p(n){let e=0;for(let r of this._$AV)r!==void 0&&(r.strings!==void 0?(r._$AI(n,r,e),e+=r.strings.length-2):r._$AI(n[e])),e++}},Ae=class t{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(n,e,r,i){this.type=2,this._$AH=m,this._$AN=void 0,this._$AA=n,this._$AB=e,this._$AM=r,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let n=this._$AA.parentNode,e=this._$AM;return e!==void 0&&n?.nodeType===11&&(n=e.parentNode),n}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(n,e=this){n=ve(this,n,e),De(n)?n===m||n==null||n===""?(this._$AH!==m&&this._$AR(),this._$AH=m):n!==this._$AH&&n!==he&&this._(n):n._$litType$!==void 0?this.$(n):n.nodeType!==void 0?this.T(n):Dr(n)?this.k(n):this._(n)}O(n){return this._$AA.parentNode.insertBefore(n,this._$AB)}T(n){this._$AH!==n&&(this._$AR(),this._$AH=this.O(n))}_(n){this._$AH!==m&&De(this._$AH)?this._$AA.nextSibling.data=n:this.T(pe.createTextNode(n)),this._$AH=n}$(n){let{values:e,_$litType$:r}=n,i=typeof r=="number"?this._$AC(n):(r.el===void 0&&(r.el=Te.createElement(un(r.h,r.h[0]),this.options)),r);if(this._$AH?._$AD===i)this._$AH.p(e);else{let a=new ot(i,this),o=a.u(this.options);a.p(e),this.T(o),this._$AH=a}}_$AC(n){let e=on.get(n.strings);return e===void 0&&on.set(n.strings,e=new Te(n)),e}k(n){pt(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,r,i=0;for(let a of n)i===e.length?e.push(r=new t(this.O(Re()),this.O(Re()),this,this.options)):r=e[i],r._$AI(a),i++;i<e.length&&(this._$AR(r&&r._$AB.nextSibling,i),e.length=i)}_$AR(n=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);n!==this._$AB;){let r=Zt(n).nextSibling;Zt(n).remove(),n=r}}setConnected(n){this._$AM===void 0&&(this._$Cv=n,this._$AP?.(n))}},_e=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(n,e,r,i,a){this.type=1,this._$AH=m,this._$AN=void 0,this.element=n,this.name=e,this._$AM=i,this.options=a,r.length>2||r[0]!==""||r[1]!==""?(this._$AH=Array(r.length-1).fill(new String),this.strings=r):this._$AH=m}_$AI(n,e=this,r,i){let a=this.strings,o=!1;if(a===void 0)n=ve(this,n,e,0),o=!De(n)||n!==this._$AH&&n!==he,o&&(this._$AH=n);else{let s=n,l,u;for(n=a[0],l=0;l<a.length-1;l++)u=ve(this,s[r+l],e,l),u===he&&(u=this._$AH[l]),o||=!De(u)||u!==this._$AH[l],u===m?n=m:n!==m&&(n+=(u??"")+a[l+1]),this._$AH[l]=u}o&&!i&&this.j(n)}j(n){n===m?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,n??"")}},st=class extends _e{constructor(){super(...arguments),this.type=3}j(n){this.element[this.name]=n===m?void 0:n}},lt=class extends _e{constructor(){super(...arguments),this.type=4}j(n){this.element.toggleAttribute(this.name,!!n&&n!==m)}},ct=class extends _e{constructor(n,e,r,i,a){super(n,e,r,i,a),this.type=5}_$AI(n,e=this){if((n=ve(this,n,e,0)??m)===he)return;let r=this._$AH,i=n===m&&r!==m||n.capture!==r.capture||n.once!==r.once||n.passive!==r.passive,a=n!==m&&(r===m||i);i&&this.element.removeEventListener(this.name,this,r),a&&this.element.addEventListener(this.name,this,n),this._$AH=n}handleEvent(n){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,n):this._$AH.handleEvent(n)}},ut=class{constructor(n,e,r){this.element=n,this.type=6,this._$AN=void 0,this._$AM=e,this.options=r}get _$AU(){return this._$AM._$AU}_$AI(n){ve(this,n)}};var Ar=dt.litHtmlPolyfillSupport;Ar?.(Te,Ae),(dt.litHtmlVersions??=[]).push("3.3.3");var dn=(t,n,e)=>{let r=e?.renderBefore??n,i=r._$litPart$;if(i===void 0){let a=e?.renderBefore??null;r._$litPart$=i=new Ae(n.insertBefore(Re(),a),a,void 0,e??{})}return i._$AI(t),i};var mt=globalThis,ae=class extends Q{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let n=super.createRenderRoot();return this.renderOptions.renderBefore??=n.firstChild,n}update(n){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(n),this._$Do=dn(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return he}};ae._$litElement$=!0,ae.finalized=!0,mt.litElementHydrateSupport?.({LitElement:ae});var Cr=mt.litElementPolyfillSupport;Cr?.({LitElement:ae});(mt.litElementVersions??=[]).push("4.2.2");var pn=t=>(n,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(t,n)}):customElements.define(t,n)};var Nr={attribute:!0,type:String,converter:Me,reflect:!1,hasChanged:Ke},Ir=(t=Nr,n,e)=>{let{kind:r,metadata:i}=e,a=globalThis.litPropertyMetadata.get(i);if(a===void 0&&globalThis.litPropertyMetadata.set(i,a=new Map),r==="setter"&&((t=Object.create(t)).wrapped=!0),a.set(e.name,t),r==="accessor"){let{name:o}=e;return{set(s){let l=n.get.call(this);n.set.call(this,s),this.requestUpdate(o,l,t,!0,s)},init(s){return s!==void 0&&this.C(o,void 0,t,s),s}}}if(r==="setter"){let{name:o}=e;return function(s){let l=this[o];n.call(this,s),this.requestUpdate(o,l,t,!0,s)}}throw Error("Unsupported decorator location: "+r)};function ze(t){return(n,e)=>typeof e=="object"?Ir(t,n,e):((r,i,a)=>{let o=i.hasOwnProperty(a);return i.constructor.createProperty(a,r),o?Object.getOwnPropertyDescriptor(i,a):void 0})(t,n,e)}function I(t){return ze({...t,state:!0,attribute:!1})}var ft="Energy Actions";var Or=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,$r=/DEFERRED/i,Lr=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function qe(t){let{active:n,armed:e,operationInProgress:r,statusText:i}=t;return n===null||e===null||r===null?"unavailable":i&&Or.test(i)?"recovery_attention":i&&$r.test(i)?"deferred":i&&Lr.test(i)?"busy":n?"active":r?"busy":e?"armed":"ready"}function hn(t){return t==="armed"}function gt(t){return t!=="busy"&&t!=="unavailable"}function mn(t){return t==="ready"||t==="armed"}var Wr={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function fn(t){return Wr[t]}var Fr=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Vr=/DEFERRED/i,Ur=/^(RESTORING|STARTING)/i;function Xe(t){let{active:n,armed:e,operationInProgress:r,snapshotValid:i,statusText:a}=t;return n===null||e===null||r===null||i===null?"unavailable":a&&Fr.test(a)?"recovery_attention":a&&Vr.test(a)?"deferred":a&&Ur.test(a)?"busy":n?"active":r?"busy":i?"deferred":e?"armed":"ready"}function gn(t){return t==="armed"}function Qe(t){return t!=="busy"&&t!=="unavailable"}function bn(t){return t==="ready"||t==="armed"}var Hr={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function Gr(t){return Hr[t]}function bt(t,n){return t==="ready"&&n===!0?"scheduled":t}function vt(t){return t==="scheduled"?"Scheduled":t==="interlocked"?"Interlocked":Gr(t)}var Br=/target (\d+)\s*W export/i,Kr=/Stop SOC (\d+)\s*%/i;function vn(t,n){if(t!==null&&Number.isFinite(t))return t;let e=n?Br.exec(n):null;return e?Number(e[1]):null}function _n(t,n){if(t!==null&&Number.isFinite(t))return t;let e=n?Kr.exec(n):null;return e?Number(e[1]):null}var jr=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function wn(t,n){return n===!0&&!!t&&jr.test(t)}var zr=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,Yr=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,qr=/OPERATOR DECISION REQUIRED/i,Xr=/press End Free Power|retry(?:ing)? restore/i,Qr=/\bRECOVERY REQUIRED\b/i,Jr=/snapshot retained/i,Zr=/RESTORE BLOCKED/i;function yn(t){let n=t.statusText??"",e=t.snapshotValid;return zr.test(n)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:Yr.test(n)&&e===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:qr.test(n)&&Xr.test(n)&&e===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:Qr.test(n)&&e===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:Jr.test(n)&&e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:Zr.test(n)?e===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var ei=new Set(["active","busy","recovery_attention","deferred"]);function ti(t){return t!==null&&ei.has(t)}function Ce(t,n){return(t==="ready"||t==="armed")&&ti(n)}function Ne(t,n){return t&&!n}function _t(t,n){switch(n){case"busy":return`${t} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${t} requires recovery before this can be used.`;default:return`${t} currently owns inverter control.`}}var xn=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function Sn(t){let n=xn.indexOf(t);return n<0?xn.length:n}function En(t,n){return t!=="unavailable"||n!=="unavailable"}function wt(t,n){return Sn(n)<Sn(t)?"dump_to_grid":"free_power"}function kn(t){switch(t){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function Mn(t){switch(t){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function Pn(t){return t==="dump_to_grid"?"Dump to Grid":"Free Power"}function Rn(t,n,e){let r=e?.trim()??"";return r?`${t}: ${n} - ${r}`:`${t}: ${n}`}function yt(t){return t.armed===!0?"armed":"hidden"}function xt(t){return!!t&&/^REJECTED/i.test(t.trim())}function St(t){return!!t&&/^BLOCKED/i.test(t.trim())}function Et(t){return t===!0}function kt(t,n){return t==="ready"&&n==="armed"?"scheduled":t}function Mt(t){return{domain:"input_boolean",service:"turn_on",data:{entity_id:t}}}function Pt(t){return{domain:"script",service:"turn_on",data:{entity_id:t}}}function Dn(t,n){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:t,datetime:n}}}function Rt(t,n){return{domain:"input_number",service:"set_value",data:{entity_id:t,value:n}}}function Tn(t,n){return n===null||!Number.isFinite(n)||n<=0?t:Math.min(t,n)}var ni=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function me(t){if(!t)return null;let n=ni.exec(t.trim());if(!n)return null;let[,e,r,i,a,o,s]=n,l=new Date(Number(e),Number(r)-1,Number(i),Number(a),Number(o),Number(s));return Number.isNaN(l.getTime())?null:l}function An(t){let n=e=>e.toString().padStart(2,"0");return`${t.getFullYear()}-${n(t.getMonth()+1)}-${n(t.getDate())} ${n(t.getHours())}:${n(t.getMinutes())}:${n(t.getSeconds())}`}var ri=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],ii=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Dt(t){let n=ri[t.getDay()],e=t.getDate(),r=ii[t.getMonth()],i=t.getHours().toString().padStart(2,"0"),a=t.getMinutes().toString().padStart(2,"0");return`${n} ${e} ${r} \u2022 ${i}:${a}`}function Ie(t,n){let e=t-n;if(e<=0)return null;let r=Math.floor(e/1e3),i=Math.floor(r/3600),a=Math.floor(r%3600/60),o=r%60;return i>0?`${i}h ${a}m`:a>0?`${a}m ${o.toString().padStart(2,"0")}s`:`${o}s`}function J(t){return t==null||Number.isNaN(t)?"--":Math.abs(t)>=1e3?`${(t/1e3).toFixed(2)} kW`:`${t.toFixed(0)} W`}function fe(t){if(t==null||Number.isNaN(t))return"--";let n=Math.round(t);if(n<60)return`${n} min`;let e=Math.floor(n/60),r=n%60;return r===0?`${e}h`:`${e}h ${r}m`}function we(t){return t==null||Number.isNaN(t)?"--":`${Math.round(t)}%`}function x(t){if(t==null||t==="unknown"||t==="unavailable"||t==="")return null;let n=Number(t);return Number.isFinite(n)?n:null}function y(t){return t==null||t==="unknown"||t==="unavailable"||t===""?null:t==="on"}function Z(t){return(Math.round(t)%1440+1440)%1440}function W(t,n){return Z(n-t)}function F(t){let n=Z(t),e=r=>(r<10?"0":"")+r;return e(Math.floor(n/60))+":"+e(n%60)}function Oe(t){return Number.isInteger(t)&&t>=0&&t<1440&&t%5===0}var Cn=Object.freeze({changeAtMin:0,deltaMin:0});function Nn(t){return t.deltaMin!==0}function $e(t,n,e){if(e.deltaMin===0||n<=0)return n;let r=W(t,e.changeAtMin);return r>0&&r<n?n-e.deltaMin:n}function In(t,n){for(let e=0;e<=n;e+=5)if(Z(t+e)<180)return!0;return!1}var bo=Object.freeze({owner:3,intelligence:2,native:1}),Tt=["MISMATCH","PROPOSED","ARMED","EXECUTING","APPLIED_VERIFIED"],h=Object.freeze({slots:6,minSlotMin:5,bufferMin:0,bufferMax:120,stopSocMin:10,stopSocMax:90,chargeTargetMin:20,chargeTargetMax:100,chargePowerMin:500,chargePowerMax:8e3,exportPowerMin:500,exportPowerMax:3e3,exportDurationMin:10,exportDurationMax:240,reserveMin:10,reserveMax:100}),q={"charge.targetSoc":{label:"Charge target",unit:"%",min:h.chargeTargetMin,max:h.chargeTargetMax,step:1,views:["charge-card","tou-table","tomorrow-plan"]},"charge.bufferMin":{label:"Finish before the window ends",unit:"min",min:h.bufferMin,max:h.bufferMax,step:5,views:["charge-card","tomorrow-plan"]},"charge.powerW":{label:"Maximum charge power",unit:"W",min:h.chargePowerMin,max:h.chargePowerMax,step:100,views:["charge-card","tou-table","tomorrow-plan"]},"charge.windowStartMin":{label:"Charge window start",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"charge.windowEndMin":{label:"Charge window end",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"export.stopSoc":{label:"Export down to (Stop SOC)",unit:"%",min:h.stopSocMin,max:h.stopSocMax,step:1,views:["export-card","tou-table","tomorrow-plan","reserve-summary"]},"export.powerW":{label:"Export power",unit:"W",min:h.exportPowerMin,max:h.exportPowerMax,step:100,views:["export-card","tou-table","tomorrow-plan"]},"export.startMin":{label:"Export start",unit:"",min:0,max:1439,step:5,time:!0,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"export.durationMin":{label:"Export duration",unit:"min",min:h.exportDurationMin,max:h.exportDurationMax,step:5,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"reserve.backupPct":{label:"Backup reserve (enforced)",unit:"%",min:h.reserveMin,max:h.reserveMax,step:1,views:["charge-card","export-card","reserve-summary","tomorrow-plan"]},"reserve.planningPct":{label:"Planning reserve (advice)",unit:"%",min:h.reserveMin,max:h.reserveMax,step:1,views:["reserve-summary","tomorrow-plan"]}},ye=Object.freeze(Object.keys(q));function Le(t,n){if(!Object.prototype.hasOwnProperty.call(q,t))return{ok:!1,error:"Unknown setting."};let e=q[t];if(typeof n!="number"||!Number.isFinite(n))return{ok:!1,error:e.label+" needs a number."};if(e.time)return Oe(n)?{ok:!0,value:n}:{ok:!1,error:e.label+" must be a time on the 5-minute grid."};if(n<e.min)return t==="export.stopSoc"?{ok:!1,error:"Stop SOC below "+e.min+" % is not available and is refused, not clamped."}:{ok:!1,error:e.label+" must be at least "+e.min+(e.unit?" "+e.unit:"")+"."};if(n>e.max)return t==="export.stopSoc"?{ok:!1,error:"Stop SOC above "+e.max+" % is not available and is refused, not clamped."}:{ok:!1,error:e.label+" can be at most "+e.max+(e.unit?" "+e.unit:"")+"."};let r=(n-e.min)/e.step;return Math.abs(r-Math.round(r))>1e-9?{ok:!1,error:e.label+" moves in steps of "+e.step+(e.unit?" "+e.unit:"")+"."}:{ok:!0,value:n}}function On(t,n="owner"){let e={};for(let r of ye){let i=Le(r,t[r]);if(!i.ok)throw new Error(r+": "+i.error);e[r]={value:i.value,source:n,revision:1,state:"PROPOSED",observed:null,proposal:null,external:null}}return{revision:1,fields:e}}function ai(t){return JSON.parse(JSON.stringify(t))}function C(t,n){return{ok:!1,settings:t,error:n,updates:[]}}function ee(t,n,e){let r=e==="proposal"?n.proposal?.value:e==="external"?n.external?.value:n.value;return r===void 0?[]:q[t].views.map(a=>({view:a,path:t,kind:e,value:r,state:n.state,preview:n.state!=="APPLIED_VERIFIED"}))}function Je(t,n){if(!Object.prototype.hasOwnProperty.call(q,n.path))return C(t,"Unknown setting.");let e=ai(t),r=e.fields[n.path],i=()=>++e.revision;switch(n.type){case"edit":{if(n.expectedRevision!==void 0&&n.expectedRevision!==t.revision)return C(t,"The settings changed (revision "+t.revision+") since this edit was prepared; reload and review.");let a=Le(n.path,n.value);return a.ok?r.state==="EXECUTING"?C(t,"An apply is in progress for this setting; it cannot be edited until it ends."):r.external?C(t,"The native side was changed outside ECCO; resolve that first (adopt it or keep the intended value)."):n.source==="intelligence"?a.value===r.value?{ok:!0,settings:t,updates:[]}:(r.proposal={value:a.value,revision:i()},{ok:!0,settings:e,updates:ee(n.path,r,"proposal")}):a.value===r.value&&r.source==="owner"?{ok:!0,settings:t,updates:[]}:(r.value=a.value,r.source="owner",r.revision=i(),r.state=r.observed===a.value?"APPLIED_VERIFIED":"PROPOSED",r.proposal&&r.proposal.value===a.value&&(r.proposal=null),{ok:!0,settings:e,updates:ee(n.path,r,"value")}):C(t,a.error)}case"adopt-proposal":return r.proposal?r.state==="EXECUTING"?C(t,"An apply is in progress for this setting."):r.external?C(t,"Resolve the external native change first."):(r.value=r.proposal.value,r.source="intelligence",r.proposal=null,r.revision=i(),r.state=r.observed===r.value?"APPLIED_VERIFIED":"PROPOSED",{ok:!0,settings:e,updates:ee(n.path,r,"value")}):C(t,"There is no Intelligence proposal to adopt.");case"dismiss-proposal":return r.proposal?(r.proposal=null,i(),{ok:!0,settings:e,updates:[]}):C(t,"There is no Intelligence proposal to dismiss.");case"arm":return r.external?C(t,"Resolve the external native change before arming."):r.state!=="PROPOSED"&&r.state!=="MISMATCH"?C(t,"Only a proposed or mismatched setting can be armed (it is "+r.state+")."):(r.state="ARMED",i(),{ok:!0,settings:e,updates:ee(n.path,r,"value")});case"disarm":return r.state!=="ARMED"?C(t,"Only an armed setting can be disarmed."):(r.state="PROPOSED",i(),{ok:!0,settings:e,updates:ee(n.path,r,"value")});case"begin":return r.external?C(t,"Resolve the external native change before executing."):r.state!=="ARMED"?C(t,"Only an armed setting can start executing."):(r.state="EXECUTING",i(),{ok:!0,settings:e,updates:ee(n.path,r,"value")});case"fail":return r.state!=="EXECUTING"?C(t,"Only an executing setting can fail."):(r.state="MISMATCH",i(),{ok:!0,settings:e,updates:ee(n.path,r,"value")});case"readback":{let a=r.observed,o=n.observed;return o!==null&&!Number.isFinite(o)?C(t,"A read-back must be a finite number or null."):o===a?{ok:!0,settings:t,updates:[]}:(r.observed=o,o===null?r.state==="APPLIED_VERIFIED"&&(r.state="PROPOSED"):o===r.value?(r.state="APPLIED_VERIFIED",r.external=null):r.state==="EXECUTING"?r.state="MISMATCH":(r.state==="APPLIED_VERIFIED"||r.state==="MISMATCH"||a!==null&&a!==o)&&(r.external={value:o,revision:e.revision+1},r.state==="APPLIED_VERIFIED"&&(r.state="MISMATCH")),i(),{ok:!0,settings:e,updates:ee(n.path,r,r.external?"external":"value")})}case"resolve-external":{if(!r.external)return C(t,"There is no external change to resolve.");if(n.choice==="adopt-native"){let a=Le(n.path,r.external.value);if(!a.ok)return C(t,"The native value is outside what ECCO accepts ("+a.error+") and cannot be adopted; keep the intended value.");r.value=r.external.value,r.source="native",r.observed=r.external.value,r.state="APPLIED_VERIFIED"}else r.state="PROPOSED";return r.external=null,r.revision=i(),{ok:!0,settings:e,updates:ee(n.path,r,"value")}}default:return C(t,"Unknown action.")}}function $n(t,n){let e=Tt.length-1;for(let r of n)e=Math.min(e,Tt.indexOf(t.fields[r].state));return Tt[e]??"MISMATCH"}function xe(t){if(!Array.isArray(t)||t.length!==h.slots)return{ok:!1,why:"the table does not have six slots"};for(let e of t){if(!e||!Oe(e.startMin))return{ok:!1,why:"a slot start is unreadable or off the 5-minute grid"};if(e.source!=="Grid"&&e.source!=="None")return{ok:!1,why:"a slot has an unknown charge source"};if(!Number.isFinite(e.powerW)||!Number.isFinite(e.targetSoc))return{ok:!1,why:"a slot power or target SOC is unreadable"}}let n=0;for(let e=0;e<h.slots;e++){let r=t[e].startMin,i=t[(e+1)%h.slots].startMin,a=W(r,i);if(a<h.minSlotMin)return{ok:!1,why:"slot "+(e+1)+" is shorter than 5 minutes"};n+=a}return n!==1440?{ok:!1,why:"the six starts are not one 24-hour cycle in slot order"}:{ok:!0}}function At(t,n){return t.startMin===n.startMin&&t.powerW===n.powerW&&t.targetSoc===n.targetSoc&&t.source===n.source}function Ln(t,n){return t.length===n.length&&t.every((e,r)=>At(e,n[r]))}var We=1440/5,Wn=t=>t.source+"|"+t.powerW+"|"+t.targetSoc;function oi(t){let n=[];for(let e=0;e<We;e++){let r=e*5,i=t[0];for(let a=0;a<t.length;a++){let o=t[a],s=t[(a+1)%t.length];if(W(o.startMin,r)<W(o.startMin,s.startMin)){i=o;break}}n.push({powerW:i.powerW,targetSoc:i.targetSoc,source:i.source,from:null})}return n}function z(t,n,e,r={}){let i=t.baseline.map(a=>({...a}));return{status:n,reasons:e,slots:i,slotReports:Un(i,i.map(()=>"native-fallback"),t.observed??null),fallback:!0,edits:[],intervals:[],refused:[],slotsNeeded:0,deferredToAfterClockChange:!1,...r}}function Un(t,n,e){return t.map((r,i)=>{let a=e&&e.length===t.length?e[i]:null,o=a===null?"PROPOSED":At(a,r)?"APPLIED_VERIFIED":"MISMATCH";return{index:i+1,intended:{...r},origin:n[i],observed:a?{...a}:null,state:o}})}function Fn(t,n){let e=[];return n.forEach((r,i)=>{let a=t&&t.length===n.length?t[i]:null,o=["startMin","powerW","targetSoc","source"];for(let s of o)(a===null||a[s]!==r[s])&&e.push({slot:i+1,field:s,from:a===null?null:a[s],to:r[s]})}),e}function si(t){return{powerW:t.powerW,targetSoc:t.targetSoc,source:t.action==="charge"?"Grid":"None",from:t.action}}function li(t){if(t.action!=="charge"&&t.action!=="export")return"unknown action";if(!Oe(t.startMin))return t.action+" start is not on the 5-minute grid";if(!Number.isInteger(t.durationMin)||t.durationMin<h.minSlotMin||t.durationMin%5!==0)return t.action+" duration must be a multiple of 5 minutes, at least 5";if(t.durationMin>=1440)return t.action+" cannot cover the whole day";if(t.action==="export"){if(!Number.isInteger(t.targetSoc)||t.targetSoc<h.stopSocMin||t.targetSoc>h.stopSocMax)return"export Stop SOC must be "+h.stopSocMin+"-"+h.stopSocMax+" %";if(t.powerW<h.exportPowerMin||t.powerW>h.exportPowerMax)return"export power is outside "+h.exportPowerMin+"-"+h.exportPowerMax+" W"}else{if(!Number.isFinite(t.targetSoc)||t.targetSoc<h.chargeTargetMin||t.targetSoc>h.chargeTargetMax)return"charge target SOC is outside "+h.chargeTargetMin+"-"+h.chargeTargetMax+" %";if(t.powerW<h.chargePowerMin||t.powerW>h.chargePowerMax)return"charge power is outside "+h.chargePowerMin+"-"+h.chargePowerMax+" W"}return null}function ci(t,n){let e=0;for(let r=0;r<t.length;r++)At(t[r],n[r])||e++;return e}function Hn(t){let n=t.day??Cn,e=Math.max(5,t.handoverGapMin??5);if(t.transactionOwner)return z(t,"REFUSED",["Single writer: "+t.transactionOwner+" owns the inverter right now; nothing is compiled until it ends and its restore is verified."]);let r=xe(t.baseline);if(!r.ok)return z(t,"REFUSED",["The native baseline is not a valid six-slot day: "+r.why+"."]);if(t.observed){let f=xe(t.observed);if(!f.ok)return z(t,"CONFLICT",["The observed inverter table is not a valid six-slot day: "+f.why+"; reconcile before planning."]);let w=t.lastApplied??t.baseline;if(!Ln(t.observed,w)){let R=Fn(w,t.observed);return z(t,"CONFLICT",["The inverter table differs from "+(t.lastApplied?"what ECCO last applied":"the owner's baseline")+" ("+R.length+" field(s), first: slot "+R[0].slot+" "+R[0].field+"). It looks edited outside ECCO; review and adopt it or restore before anything is compiled."])}}let i=[],a=t.intervals.filter(f=>f.action==="export"&&t.controlLocked!==!1?(i.push({action:"export",reason:"Control is locked (grid-loss lock): every export start is refused."}),!1):!0);for(let f of a){let w=li(f);if(w)return z(t,"REFUSED",["Invalid derived interval: "+w+"."],{refused:i})}if(a.filter(f=>f.action==="charge").length>1||a.filter(f=>f.action==="export").length>1)return z(t,"REFUSED",["Only one charge and one export interval can be derived per cycle."],{refused:i});let o=a.find(f=>f.action==="charge"),s=a.find(f=>f.action==="export");if(o&&s){let f=W(s.startMin+s.durationMin,o.startMin),w=W(o.startMin+o.durationMin,s.startMin);if(W(o.startMin,s.startMin)<o.durationMin||W(s.startMin,o.startMin)<s.durationMin)return z(t,"REFUSED",["The export would overlap the charge window; the firmware refuses an export that touches a charge slot."],{refused:i});if(f<e||w<e)return z(t,"REFUSED",["Fewer than "+e+" minutes between the export and the charge window; time is needed to restore and verify."],{refused:i})}let l=!1;if(Nn(n)){for(let f of a){let w=Z(f.startMin+f.durationMin);(f.action==="export"?In(f.startMin,f.durationMin):f.startMin<180||w<180)&&(l=!0)}if(l)return z(t,"REFUSED",["Clock-change night: derived changes that start, end or run between 00:00 and 03:00 wait until the night is over; the native table keeps running unchanged."],{refused:i,deferredToAfterClockChange:!0})}let u=oi(t.baseline);for(let f of a){let w=si(f);for(let R=0;R<f.durationMin;R+=5)u[(f.startMin+R)/5%We]={...w}}let c=[];for(let f=0;f<We;f++){let w=u[(f+We-1)%We];Wn(w)!==Wn(u[f])&&c.push(f*5)}c.length===0&&c.push(t.baseline[0].startMin);let d=c.length;if(d>h.slots)return z(t,"INFEASIBLE",["Six native slots are not enough: this plan needs "+d+" distinct slots (changes at "+c.map(f=>F(f)).join(", ")+") and the inverter has exactly "+h.slots+". Nothing is truncated; the native table stays as it is."],{refused:i,slotsNeeded:d,intervals:Vn(a,n)});let b=new Set(c);for(let f of t.baseline){if(c.length>=h.slots)break;b.has(f.startMin)||(c.push(f.startMin),b.add(f.startMin))}for(c.sort((f,w)=>f-w);c.length<h.slots;){let f=-1,w=0;for(let H=0;H<c.length;H++){let B=W(c[H],c[(H+1)%c.length])||1440;B>w&&(w=B,f=H)}let R=Z(c[f]+Math.floor(w/2/5)*5);c.push(R),c.sort((H,B)=>H-B)}let v=f=>u[f/5],g=c.map(f=>{let w=v(f);return{startMin:f,powerW:w.powerW,targetSoc:w.targetSoc,source:w.source}}),P=(f,w)=>{let R=W(f,w)||1440;for(let H=0;H<R;H+=5){let B=v(Z(f+H)).from;if(B)return B==="charge"?"derived:charge":"derived:export"}return"native-fallback"},E=0,O=1/0;for(let f=0;f<h.slots;f++){let w=g.map((H,B)=>g[(B+f)%h.slots]),R=ci(w,t.baseline);R<O&&(O=R,E=f)}let _=g.map((f,w)=>({...g[(w+E)%h.slots]})),T=g.map((f,w)=>{let R=(w+E)%h.slots;return P(g[R].startMin,g[(R+1)%h.slots].startMin)}),N=xe(_);if(!N.ok)return z(t,"REFUSED",["Internal check failed ("+N.why+"); the native table stays as it is."],{refused:i});let le=Ln(_,t.baseline);return{status:"OK",reasons:i.map(f=>f.reason),slots:_,slotReports:Un(_,T,t.observed??null),fallback:le,edits:Fn(t.observed??t.baseline,_),intervals:Vn(a,n),refused:i,slotsNeeded:d,deferredToAfterClockChange:!1}}function Vn(t,n){return t.map(e=>({action:e.action,startMin:e.startMin,wallMin:e.durationMin,elapsedMin:$e(e.startMin,e.durationMin,n)}))}var ge=["hold_battery","skip_tonight","prepare_power_cut"];function Gn(t,n,e,r){if(!ge.includes(t))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(!Number.isFinite(n))return{ok:!1,error:"The current time is unknown; an override cannot be started without it.",code:"TIME_UNKNOWN"};let i=e??r.defaultExpiryMin[t];if(typeof i!="number"||!Number.isFinite(i))return{ok:!1,error:"An override needs an expiry; there is no open-ended override.",code:"EXPIRY_MISSING"};if(i<r.minExpiryMin)return{ok:!1,error:"The expiry must be at least "+r.minExpiryMin+" minutes.",code:"EXPIRY_BELOW_MIN"};let a=r.maxExpiryMin[t];if(i>a)return{ok:!1,error:"The expiry can be at most "+a+" minutes for this override.",code:"EXPIRY_ABOVE_CAP"};let o={kind:t,startedAtMin:n,expiresAtMin:n+i};if(t==="prepare_power_cut"){let s=r.powerCutReservePct;if(!Number.isFinite(s)||s<h.reserveMin||s>h.reserveMax)return{ok:!1,error:"The power-cut reserve must be "+h.reserveMin+"-"+h.reserveMax+" %.",code:"POWER_CUT_RESERVE_RANGE"};o.reservePct=s}return{ok:!0,override:o}}var Fe={min_expiry:{min:5,max:60,step:5,unit:"min"},hold_default:{min:5,max:4320,step:5,unit:"min"},hold_cap:{min:5,max:4320,step:5,unit:"min"},skip_until:{min:180,max:1435,step:5,unit:"minute of day"},skip_cap:{min:5,max:2160,step:5,unit:"min"},cut_default:{min:5,max:10080,step:5,unit:"min"},cut_cap:{min:5,max:10080,step:5,unit:"min"},cut_reserve:{min:10,max:100,step:1,unit:"%"},revision:{min:0,max:1e9,step:1,unit:""}},oe=Object.freeze({hold_battery:Fe.hold_cap.max,skip_tonight:Fe.skip_cap.max,prepare_power_cut:Fe.cut_cap.max}),te=Object.freeze({hold_battery:"Hold battery",skip_tonight:"Skip tonight",prepare_power_cut:"Prepare for power cut"}),ui=[{key:"minExpiryMin",bound:"min_expiry",label:"Shortest allowed override"},{key:"holdDefaultMin",bound:"hold_default",label:"Hold battery default"},{key:"holdCapMin",bound:"hold_cap",label:"Hold battery maximum"},{key:"skipUntilMin",bound:"skip_until",label:"Skip tonight ends at"},{key:"skipCapMin",bound:"skip_cap",label:"Skip tonight maximum"},{key:"cutDefaultMin",bound:"cut_default",label:"Prepare for power cut default"},{key:"cutCapMin",bound:"cut_cap",label:"Prepare for power cut maximum"},{key:"cutReservePct",bound:"cut_reserve",label:"Power-cut reserve"}];function ne(t){if(typeof t!="number"||!Number.isFinite(t)||t<0)return"unknown";let n=Math.round(t);if(n<60)return n+" min";let e=Math.floor(n/1440),r=Math.floor((n-e*1440)/60),i=n%60,a=[];return e>0&&a.push(e+(e===1?" day":" days")),r>0&&a.push(r+" h"),i>0&&a.push(i+" min"),a.join(" ")}function Bn(t,n){if(t.bound==="skip_until")return F(n);let e=Fe[t.bound];return e.unit==="min"?ne(n):n+" "+e.unit}function di(t,n,e){let r=Fe[t.bound];return typeof n!="number"||!Number.isFinite(n)?(e.push(t.label+" is not set or cannot be read."),null):Number.isInteger(n)?n<r.min?(e.push(t.label+" must be at least "+Bn(t,r.min)+"."),null):n>r.max?(e.push(t.label+" can be at most "+Bn(t,r.max)+"."),null):(n-r.min)%r.step!==0?(e.push(t.label+" moves in steps of "+r.step+(r.unit==="%"?" %":" min")+"."),null):n:(e.push(t.label+" must be a whole number."),null)}function Ct(t,n={}){if(t==null||typeof t!="object")return{ok:!1,reasons:["No override limits are configured, so no override can be started."],codes:["POLICY_UNCONFIRMED"]};let e=[],r=[];t.confirmed!==!0&&e.push("The owner has not confirmed the override limits (the switch is off or cannot be read), so no override can be started.");let i={};for(let c of ui){let d=di(c,t[c.key],e);d!==null&&(i[c.key]=d)}let a=i.minExpiryMin,o=(c,d,b)=>{a!==void 0&&d!==void 0&&d<a&&e.push(c+" default is shorter than the shortest allowed override."),d!==void 0&&b!==void 0&&d>b&&e.push(c+" default is longer than its maximum.")};o("Hold battery",i.holdDefaultMin,i.holdCapMin),o("Prepare for power cut",i.cutDefaultMin,i.cutCapMin),a!==void 0&&i.skipCapMin!==void 0&&i.skipCapMin<a&&e.push("Skip tonight maximum is shorter than the shortest allowed override.");let s=i.cutReservePct;s!==void 0&&(s<h.reserveMin||s>h.reserveMax)&&e.push("The power-cut reserve must be "+h.reserveMin+"-"+h.reserveMax+" %.");let l=n.currentReservePct;if(typeof l=="number"&&Number.isFinite(l)?s!==void 0&&s<l&&e.push("The power-cut reserve ("+s+" %) is below the current backup reserve ("+l+" %); it would not raise anything."):r.push("The current backup reserve is not known, so the power-cut reserve cannot be compared with it here. An override can only raise a reserve."),e.length>0){let c=[];return t.confirmed!==!0&&c.push("POLICY_UNCONFIRMED"),e.length>c.length&&c.push("POLICY_INVALID"),{ok:!1,reasons:e,codes:c}}return{ok:!0,config:Object.freeze({minExpiryMin:i.minExpiryMin,holdDefaultMin:i.holdDefaultMin,holdCapMin:i.holdCapMin,skipUntilMin:i.skipUntilMin,skipCapMin:i.skipCapMin,cutDefaultMin:i.cutDefaultMin,cutCapMin:i.cutCapMin,cutReservePct:i.cutReservePct}),warnings:r}}function pi(t){return!!t&&(t.deltaMin===0||t.deltaMin===60||t.deltaMin===-60)&&Number.isInteger(t.changeAtMin)&&t.changeAtMin>=0&&t.changeAtMin<1440}function Kn(t,n,e){if(!Number.isInteger(t)||t<0||t>=1440)return{ok:!1,error:"The local time is unknown."};if(!Number.isInteger(n)||n<0||n>=1440)return{ok:!1,error:"The end time is not a time of day."};if(!pi(e))return{ok:!1,error:"The clock-change information is not valid."};let r=W(t,n),i=r===0?1440:r,a=$e(t,i,e);return a>0?{ok:!0,wallMin:i,expiryMin:a}:{ok:!1,error:"The end time is not in the future."}}function hi(t,n){let e=NaN;if(n){let r=Kn(n.nowWallMin,t.skipUntilMin,n.day);r.ok&&(e=r.expiryMin)}return{minExpiryMin:t.minExpiryMin,defaultExpiryMin:{hold_battery:t.holdDefaultMin,skip_tonight:e,prepare_power_cut:t.cutDefaultMin},maxExpiryMin:{hold_battery:t.holdCapMin,skip_tonight:t.skipCapMin,prepare_power_cut:t.cutCapMin},powerCutReservePct:t.cutReservePct}}var mi=[30,60,120,240,480,720,1440,2880,4320,10080];function jn(t,n,e){let r=t==="hold_battery"?n.holdCapMin:t==="skip_tonight"?n.skipCapMin:n.cutCapMin,i=t==="hold_battery"?n.holdDefaultMin:t==="prepare_power_cut"?n.cutDefaultMin:null,a=new Set;for(let s of mi)s>=n.minExpiryMin&&s<=r&&a.add(s);i!==null&&a.add(i),a.add(r);let o=[...a].filter(s=>s>=n.minExpiryMin&&s<=r).map(s=>({id:"d"+s,label:ne(s),expiryMin:s,untilMin:null,isDefault:i===s}));if((t==="hold_battery"||t==="skip_tonight")&&e){let s=Kn(e.nowWallMin,n.skipUntilMin,e.day);s.ok&&s.expiryMin>=n.minExpiryMin&&s.expiryMin<=r&&o.push({id:"until",label:"until "+F(n.skipUntilMin),expiryMin:s.expiryMin,untilMin:n.skipUntilMin,isDefault:t==="skip_tonight"})}return o.sort((s,l)=>s.expiryMin-l.expiryMin||s.id.localeCompare(l.id))}function zn(t,n,e,r,i){if(!r||r.ok!==!0||!r.config)return{ok:!1,error:"The override limits are not valid, so no override can be started."+(r&&r.ok===!1&&r.reasons.length?" "+r.reasons.join(" "):""),code:r&&r.ok===!1&&r.codes&&r.codes[0]||"POLICY_INVALID"};let a=r.config;if(!ge.includes(t))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(e!=null&&(typeof e!="number"||!Number.isInteger(e)))return{ok:!1,error:"The expiry must be a whole number of minutes.",code:"EXPIRY_NOT_WHOLE"};if(t==="prepare_power_cut"){let l=i.currentReservePct;if(typeof l!="number"||!Number.isFinite(l))return{ok:!1,error:"The current backup reserve is not known, so it cannot be shown that the power-cut reserve raises it.",code:"RESERVE_UNKNOWN"};if(a.cutReservePct<l)return{ok:!1,error:"The power-cut reserve ("+a.cutReservePct+" %) is below the current backup reserve ("+l+" %); an override never lowers a reserve.",code:"RESERVE_BELOW_CURRENT"}}let o=Gn(t,n,e,hi(a,i.clock));if(!o.ok)return o;let s=o.override.expiresAtMin-o.override.startedAtMin;return!(s>0)||!(s<=oe[t])?{ok:!1,error:"The expiry is beyond the hard ceiling of "+ne(oe[t])+".",code:"EXPIRY_ABOVE_CEILING"}:o}var fi=[{key:"minExpiryMin",value:15,why:"Under a quarter hour is almost certainly a mis-tap and would make the plan flicker."},{key:"holdDefaultMin",value:240,why:"Covers an evening of extra use (cooking, guests) without outliving it."},{key:"holdCapMin",value:1440,why:"A forgotten hold costs at most one night of export; two days needs a deliberate restart."},{key:"skipUntilMin",value:420,why:"Skips tonight's export and the overnight charge, then planning resumes before the morning sun."},{key:"skipCapMin",value:1440,why:"Skip is a one-night action; a day is the most it needs."},{key:"cutDefaultMin",value:1440,why:"Most warnings and outages are shorter than a day; extending is a conscious step."},{key:"cutCapMin",value:4320,why:"Matches the design example of 72 h; a raised reserve only costs forgone export."},{key:"cutReservePct",value:80,why:"Hours of essential load while still leaving room for solar; the design example."}],Yn=Object.freeze(fi.map(t=>Object.freeze({...t})));var gi=["HIGH","MEDIUM","LOW","INSUFFICIENT"];function Ze(t){return{known:!1,reason:t,state:"PROPOSED"}}function Nt(t,n){if(!t)return Ze("No Intelligence advice is available.");let e=t[n];return e==null?Ze("Intelligence did not provide this."):typeof e!="number"||!Number.isFinite(e)||e<0?Ze("Intelligence provided a value that is not a valid amount."):{known:!0,value:e,state:"PROPOSED",origin:"intelligence",simulated:!1}}var bi=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"];function qn(t){let{advice:n,settings:e,chargePlan:r}=t,i=[],a="UNKNOWN";n&&typeof n.confidence=="string"&&gi.includes(n.confidence)&&(a=n.confidence);let o={known:a!=="UNKNOWN",level:a,state:"PROPOSED"},s,l=n?.chargeFinishMin;if(typeof l=="number"&&Number.isFinite(l)&&l>=0&&l<1440)s={known:!0,value:Math.round(l),state:"PROPOSED",origin:"intelligence",simulated:!1};else if(r&&(r.status==="OK"||r.status==="BUFFER_TOO_SMALL")&&r.finishNominalMin!==null){let v=e.fields["charge.windowStartMin"].value;s={known:!0,value:Z(v+r.finishNominalMin),state:$n(e,bi),origin:"planner",simulated:!0},r.status==="BUFFER_TOO_SMALL"&&i.push({origin:"planner",text:"Buffer too small: the stress case overruns the charge window (simulated, not measured)."})}else s=Ze(r&&r.status==="NOTHING_TO_CHARGE"?"No overnight charge is expected to be needed.":"No finish time is available from advice or the planner.");let u=e.fields["reserve.backupPct"],c={known:!0,value:u.value,state:u.state,origin:"settings",simulated:!1};if(n&&Array.isArray(n.why))for(let v of n.why.slice(0,8))typeof v=="string"&&v.trim()&&i.push({origin:"advice",text:v.trim().slice(0,200)});let d=e.fields["charge.targetSoc"];i.push({origin:"settings",text:"Charge target "+d.value+" % ("+d.source+", revision "+d.revision+", "+d.state+")."});let b=e.fields["export.stopSoc"];return i.push({origin:"settings",text:"Export stops at "+b.value+" % ("+b.source+", revision "+b.revision+", "+b.state+")."}),i.push({origin:"settings",text:"Backup reserve "+u.value+" % ("+u.source+", "+u.state+")."}),o.known?a!=="HIGH"&&i.push({origin:"advice",text:"Confidence is "+a+": ECCO holds rather than acts on this forecast."}):i.push({origin:"advice",text:"Confidence is unknown, so nothing here is presented as a firm forecast."}),{importKwh:Nt(n,"expectedImportKwh"),exportKwh:Nt(n,"expectedExportKwh"),solarKwh:Nt(n,"expectedSolarKwh"),chargeFinishMin:s,reservePct:c,confidence:o,why:i}}var vi=60,Wo=Object.freeze({targetMin:10,targetMax:100,bufferMin:h.bufferMin,bufferMax:h.bufferMax,bufferStep:5,replanMin:5,replanMax:15});var _i=Object.freeze({stepW:100,minW:h.chargePowerMin,hardMaxW:h.chargePowerMax,hysteresisW:500,dwellMin:30,decreaseSlackMin:15,replanMin:10,maxChanges:6,maxSocAgeMin:15,socResolutionPct:1,chargeEff:.95,taperStartSocPct:90,taperEndFraction:.15,topHoldMin:20,demandMarginPct:20,assumedDemandW:2e3,maxHouseholdAgeMin:15,maxDecreaseStepW:h.chargePowerMax}),Fo=Object.freeze({maxDecreaseStepW:1e3}),wi=Object.freeze({fallbackPolicy:"KEEP_CURRENT",unknownDemandPolicy:"ASSUME_PROVISIONAL"}),Xn={stepW:["OWNER_SET","the editor's setpoint step"],minW:["OWNER_SET","the editor's minimum charge power"],hardMaxW:["OWNER_SET","the editor's maximum charge power"],hysteresisW:["PROVISIONAL","the owner's confirmation after watching real nights"],dwellMin:["PROVISIONAL","the owner's confirmation and the actuator's settle time"],decreaseSlackMin:["PROVISIONAL","the owner's confirmation after watching real nights"],replanMin:["PROVISIONAL","the owner's confirmation and the actuator's cadence"],maxChanges:["PROVISIONAL","the write budget of a proven actuator"],maxSocAgeMin:["PROVISIONAL","the real update rate of the SOC sensor"],socResolutionPct:["PROVISIONAL","the real resolution of the SOC sensor"],chargeEff:["PROVISIONAL","the measured grid-to-battery energy ratio over several nights"],taperStartSocPct:["MEASURED_REQUIRED","the BMS taper curve measured over several full charges"],taperEndFraction:["MEASURED_REQUIRED","the BMS taper curve measured over several full charges"],topHoldMin:["MEASURED_REQUIRED","the measured time from the last taper step to the BMS finishing the top of charge"],demandMarginPct:["PROVISIONAL","the measured spread of real demand against its forecast"],assumedDemandW:["MEASURED_REQUIRED","the measured overnight household demand profile (unknown today)"],maxHouseholdAgeMin:["PROVISIONAL","the real update rate of the demand and solar sensors"],maxDecreaseStepW:["PROVISIONAL","the owner's confirmation (recommended 1000 W; off by default)"],fallbackPolicy:["PROVISIONAL","the owner's choice"],unknownDemandPolicy:["PROVISIONAL","the owner's choice"],targetSocPct:["OWNER_SET","the owner's charge target"],bufferMin:["OWNER_SET","the owner's finish-early buffer"],gridImportLimitW:["OWNER_SET","the owner's or installer's safe grid import limit (unknown means no headroom constraint)"]};function yi(){let t={},n={..._i,...wi,targetSocPct:"owner setting",bufferMin:vi,gridImportLimitW:"owner setting or unknown"};for(let e of Object.keys(Xn)){let r=Xn[e];t[e]=Object.freeze({kind:r[0],value:n[e],replacedBy:r[1]})}return Object.freeze(t)}var Vo=yi(),Uo=2*1440;var xi=Object.freeze({status:"sensor.ecco_intel_status",charge_target:"sensor.ecco_intel_charge_target",export_event:"sensor.ecco_intel_export_event",pv_tomorrow:"sensor.ecco_intel_pv_tomorrow",fresh:"binary_sensor.ecco_intel_fresh",paused:"input_boolean.ecco_intel_paused"}),Si=6,Ei=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/,ki=/^(\d{2}):(\d{2})$/,Mi=/^\d{4}-\d{2}-\d{2} (\d{2}):(\d{2}):\d{2}$/;function U(t,n){if(!n)return null;let e=t[n]?.state;return typeof e!="string"||e===""||e==="unavailable"||e==="unknown"?null:e}function k(t,n){let e=U(t,n);if(e===null)return null;let r=e.trim();if(!Ei.test(r))return null;let i=Number(r);return Number.isFinite(i)?i:null}var V=(t,n)=>U(t,n)==="on";function Pi(t){if(t===null)return null;let n=ki.exec(t.trim());if(!n)return null;let e=Number(n[1]),r=Number(n[2]);return e>23||r>59?null:e*60+r}function Qn(t){if(t===null)return null;let n=Mi.exec(t.trim());if(!n)return null;let e=Number(n[1]),r=Number(n[2]);return e>23||r>59?null:e*60+r}function Ri(t,n){let e=`sensor.${t}_ecco_timezone${n}_`;return{time:`${e}time`,power:`${e}power`,soc:`${e}soc`,charge:`${e}charge`}}function Di(t){return{fpActive:`binary_sensor.${t}_free_power_active`,fpOp:`binary_sensor.${t}_free_power_operation_in_progress`,fpSnapshot:`binary_sensor.${t}_free_power_snapshot_valid`,dgActive:`binary_sensor.${t}_dump_to_grid_active`,dgOp:`binary_sensor.${t}_dump_to_grid_operation_in_progress`,dgSnapshot:`binary_sensor.${t}_dump_to_grid_snapshot_valid`}}function It(t,n){let e=t[n]?.attributes;return e&&typeof e=="object"?e:{}}function Jn(t){return typeof t=="number"&&Number.isFinite(t)?t:null}function Ti(t,n){let e=g=>({advice:null,available:!1,note:g,chargeTargetPct:null}),r=U(t,n.status);if(r===null)return e("The Intelligence advice is not available (its status cannot be read).");if(V(t,n.paused))return e("Intelligence is paused by the owner; it publishes no advice.");if(r!=="OK")return e("Intelligence status is "+r+"; it publishes no figures.");if(U(t,n.fresh)!=="on")return e("The Intelligence advice is not fresh; it is not shown as a forecast.");let i=n.charge_target,a=It(t,i).advice,o=a&&typeof a=="object"&&!Array.isArray(a)?a:{},s=It(t,i).confidence,l=[],u=k(t,i),c=o.binding_constraint;u!==null&&l.push("Charge target advice "+u+" %"+(typeof c=="string"?" (limited by "+c.toLowerCase().replace(/_/g," ")+")":"")+"."),o.conservative_fallback===!0&&l.push("Not enough demand evidence yet, so Intelligence advises keeping the battery well charged.");let d=Jn(o.net_need_kwh);d!==null&&l.push("Net overnight need after solar credit: "+d.toFixed(1)+" kWh.");let b=It(t,i).blockers;if(Array.isArray(b))for(let g of b.slice(0,4)){let P=g&&typeof g=="object"?g.text:null;typeof P=="string"&&P.trim()&&l.push("Blocked: "+P.trim())}return l.push("Import is the grid energy Intelligence plans for the overnight charge; it does not include daytime import."),{advice:{expectedImportKwh:Jn(o.grid_charge_kwh),expectedExportKwh:k(t,n.export_event),expectedSolarKwh:k(t,n.pv_tomorrow),chargeFinishMin:null,confidence:typeof s=="string"?s:null,why:l},available:!0,note:null,chargeTargetPct:u}}function Ai(t,n){let e=[],r=[];for(let a=1;a<=Si;a++){let o=Ri(n,a),s=Pi(U(t,o.time)),l=k(t,o.power),u=k(t,o.soc),c=U(t,o.charge),d=[];s===null&&d.push("start time"),l===null&&d.push("power"),u===null&&d.push("target SOC"),c!=="Grid"&&c!=="None"&&d.push("charge source"),d.length?r.push("slot "+a+" "+d.join(", ")):e.push({startMin:s,powerW:l,targetSoc:u,source:c})}if(r.length)return{table:null,reason:"The six TOU slots cannot all be read ("+r.join("; ")+"), so no comparison is possible."};let i=xe(e);return i.ok?{table:e,reason:null}:{table:null,reason:"The inverter's six slots are not a valid six-slot day ("+i.why+"), so no comparison is made."}}function re(t,n,e,r=null){if(n===null)return{value:null,reason:e,observed:null};let i=Le(t,n);return i.ok?{value:i.value,reason:"",observed:r}:{value:null,reason:"The value "+n+" is outside what ECCO accepts ("+i.error+")",observed:null}}function Zn(t,n){let e=t.plan??{},r=t.free_power,i=t.schedule,a=t.dump_to_grid,o=a?.schedule,s=e.entity_prefix,l={...xi,...e.advice??{}},u=Ti(n,l),c=s?Ai(n,s):{table:null,reason:"No TOU slot prefix is configured (plan.entity_prefix), so the six slots are not read."},d=c.table,b=d?d.filter(S=>S.source==="Grid"):[],v=b.length===1?b[0]:null,g={};for(let S of ye)g[S]={value:null,reason:"This card has no entity for it.",observed:null};let P=i?Qn(U(n,i.start)):null,E=i?k(n,i.duration):null,O=i?k(n,i.power):r?k(n,r.max_charge_power):null;g["charge.powerW"]=re("charge.powerW",O,"The charge power cannot be read."),g["charge.windowStartMin"]=re("charge.windowStartMin",P,i?"The scheduled charge start cannot be read.":"No schedule is configured, so there is no charge window.");let _=null;P!==null&&E!==null&&Number.isInteger(E)&&E>0&&E<1440&&(_=(P+E)%1440),g["charge.windowEndMin"]=re("charge.windowEndMin",_,i?"The scheduled charge end cannot be worked out (start or duration unreadable, or not on the 5-minute grid).":"No schedule is configured, so there is no charge window."),g["charge.targetSoc"]=re("charge.targetSoc",v?v.targetSoc:null,"The charge target is not stated: the inverter table has no single grid-charge slot to read it from.",v?v.targetSoc:null),g["charge.bufferMin"]={value:null,reason:"No finish-before-window-end buffer is set by any entity this card reads.",observed:null};let T=a?V(n,a.active):!1,N=o?k(n,o.power):a?k(n,a.export_power):null,le=o?k(n,o.stop_soc):a?k(n,a.stop_soc):null,f=a&&T?k(n,a.active_export_power):null,w=a&&T?k(n,a.active_stop_soc):null,R=o?Qn(U(n,o.start)):null,H=o?k(n,o.duration):a?k(n,a.duration):null;g["export.powerW"]=re("export.powerW",N,"The export power cannot be read.",f),g["export.stopSoc"]=re("export.stopSoc",le,"The Stop SOC cannot be read.",w),g["export.startMin"]=re("export.startMin",R,o?"The scheduled export start cannot be read.":"No export schedule is configured, so there is no export start time."),g["export.durationMin"]=re("export.durationMin",H,"The export duration cannot be read."),g["reserve.backupPct"]=re("reserve.backupPct",e.reserve?k(n,e.reserve):null,e.reserve?"The backup reserve cannot be read.":"No backup reserve entity is configured (plan.reserve)."),g["reserve.planningPct"]={value:null,reason:"Intelligence's planning reserve is not read by this card.",observed:null};let B={};for(let S of ye)B[S]=g[S].value!==null?g[S].value:q[S].min;let Y=On(B,"owner"),Vt=i?V(n,i.armed):!1,tt=r?V(n,r.active):!1,Ut=o?V(n,o.armed):!1,fr=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"],gr=["export.stopSoc","export.powerW","export.startMin","export.durationMin"],nt=(S,A)=>{let $=Je(Y,{type:A,path:S});$.ok&&(Y=$.settings)},Ht=(S,A,$)=>{for(let L of S)g[L].value!==null&&($?(nt(L,"arm"),nt(L,"begin")):A&&nt(L,"arm"))};Ht(fr,Vt,tt),Ht(gr,Ut,T);for(let S of ye){let A=g[S];if(A.value===null||A.observed===null)continue;let $=Je(Y,{type:"readback",path:S,observed:A.observed});$.ok&&(Y=$.settings)}let Gt=null;if(u.chargeTargetPct!==null&&g["charge.targetSoc"].value!==null&&u.chargeTargetPct!==g["charge.targetSoc"].value){let S=Je(Y,{type:"edit",path:"charge.targetSoc",value:u.chargeTargetPct,source:"intelligence"});S.ok&&(Y=S.settings,Gt=Y.fields["charge.targetSoc"].proposal?.value??null)}let Bt=ye.map(S=>{let A=g[S],$=Y.fields[S],L=q[S];return{path:S,label:L.label,unit:L.unit,known:A.value!==null,...A.value===null?{reason:A.reason}:{},value:$.value,state:$.state,source:$.source,observed:$.observed,proposal:S==="charge.targetSoc"?Gt:null}}),Ue=[],Kt=null;if(d){let S=[],A=X=>g[X].value;if(Vt||tt){let X=A("charge.windowStartMin"),Se=A("charge.powerW"),be=A("charge.targetSoc");X===null||E===null||Se===null||be===null?Ue.push("The armed charge could not be placed in the table: "+(be===null?"its target SOC is unknown.":"its start, duration or power is unreadable.")):S.push({action:"charge",startMin:X,durationMin:E,targetSoc:be,powerW:Se})}if(Ut||T){let X=A("export.startMin"),Se=A("export.powerW"),be=A("export.stopSoc"),zt=A("export.durationMin");X===null||Se===null||be===null||zt===null?Ue.push("The armed export could not be placed in the table: a start, duration, power or Stop SOC is unreadable."):S.push({action:"export",startMin:X,durationMin:zt,targetSoc:be,powerW:Se})}let $=null,L=s?Di(s):null;L&&(V(n,L.fpActive)||V(n,L.fpOp)||V(n,L.fpSnapshot))||tt||r&&(V(n,r.operation_in_progress)||V(n,r.snapshot_valid))?$="Free Power":(L&&(V(n,L.dgActive)||V(n,L.dgOp)||V(n,L.dgSnapshot))||T||a&&(V(n,a.operation_in_progress)||V(n,a.snapshot_valid)))&&($="Dump to Grid");let jt=e.control_lock?U(n,e.control_lock)==="off":!1;!jt&&S.some(X=>X.action==="export")&&Ue.push(e.control_lock?"Control is locked or its state is unreadable, so the export is not placed in the table (fail-safe).":"No grid-loss lock state is configured (plan.control_lock), so an export is not placed in the table (fail-safe)."),Kt=Hn({baseline:d,intervals:S,observed:d,lastApplied:null,transactionOwner:$,controlLocked:!jt})}let br=Ci(qn({advice:u.advice,settings:Y}),Bt,u);return{settings:Y,fields:Bt,tomorrow:br,tou:{readable:d!==null,reason:c.reason,observed:d,compile:Kt,notes:Ue},overrides:[],adviceAvailable:u.available,adviceNote:u.note}}function Ci(t,n,e){let r=s=>n.find(l=>l.path===s)?.known===!0,i=t.why.filter(s=>s.origin!=="settings"?!0:s.text.startsWith("Charge target ")?r("charge.targetSoc"):s.text.startsWith("Export stops at ")?r("export.stopSoc"):s.text.startsWith("Backup reserve ")?r("reserve.backupPct"):!0);r("charge.targetSoc")||i.push({origin:"settings",text:"Charge target: unknown (no single grid-charge slot to read it from)."}),r("export.stopSoc")||i.push({origin:"settings",text:"Export Stop SOC: unknown (not readable)."}),r("reserve.backupPct")||i.push({origin:"settings",text:"Backup reserve: unknown (no entity configured or readable)."});let a=s=>!s.known&&e.note?{...s,reason:e.note}:s,o=t.reservePct.known&&!r("reserve.backupPct")?{known:!1,reason:n.find(s=>s.path==="reserve.backupPct")?.reason??"Unknown.",state:"PROPOSED"}:t.reservePct;return{...t,why:i,importKwh:a(t.importKwh),exportKwh:a(t.exportKwh),solarKwh:a(t.solarKwh),chargeFinishMin:a(t.chargeFinishMin),reservePct:o}}var G={confirmed:"input_boolean.ecco_plan_overrides_enabled",revision:"input_number.ecco_plan_revision",min_expiry:"input_number.ecco_plan_policy_min_expiry",hold_default:"input_number.ecco_plan_policy_hold_default",hold_cap:"input_number.ecco_plan_policy_hold_cap",skip_until:"input_datetime.ecco_plan_policy_skip_until",skip_cap:"input_number.ecco_plan_policy_skip_cap",cut_default:"input_number.ecco_plan_policy_cut_default",cut_cap:"input_number.ecco_plan_policy_cut_cap",cut_reserve:"input_number.ecco_plan_policy_cut_reserve",hold_battery_start:"input_datetime.ecco_plan_override_hold_battery_start",hold_battery_expires:"input_datetime.ecco_plan_override_hold_battery_expires",skip_tonight_start:"input_datetime.ecco_plan_override_skip_tonight_start",skip_tonight_expires:"input_datetime.ecco_plan_override_skip_tonight_expires",prepare_power_cut_start:"input_datetime.ecco_plan_override_prepare_power_cut_start",prepare_power_cut_expires:"input_datetime.ecco_plan_override_prepare_power_cut_expires",prepare_power_cut_reserve:"input_number.ecco_plan_override_prepare_power_cut_reserve"},Ni=/^(\d{2}):(\d{2})(?::(\d{2}))?$/,Ii=/^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2}$/;function Oi(t){if(t===null)return null;let n=Ni.exec(t.trim());if(!n)return null;let e=Number(n[1]),r=Number(n[2]),i=n[3]===void 0?0:Number(n[3]);return e>23||r>59||i>59?null:e*60+r+i/60}function $i(t,n){let e=U(t,n);return e==="on"?!0:e==="off"?!1:null}function er(t,n,e){let r=U(t,n);if(r===null)return{ok:!1,reason:e+" cannot be read."};let i=Ii.exec(r.trim());if(!i)return{ok:!1,reason:e+" is not a date and time."};let a=t[n]?.attributes?.timestamp;return typeof a!="number"||!Number.isFinite(a)?{ok:!1,reason:e+" has no timestamp, so its moment cannot be placed."}:{ok:!0,min:Math.round(a/60),text:i[1]+" "+i[2]+":"+i[3]}}function Li(t,n,e){let r=[];if(n===null)return e.push("The current time is not known, so stored override records cannot be judged."),r;for(let i of ge){let a=te[i],o=G[i+"_start"],s=G[i+"_expires"],l=er(t,s,a+" expiry");if(!l.ok){e.push(l.reason);continue}if(l.min<=n)continue;let u=er(t,o,a+" start");if(!u.ok){e.push(u.reason+" The record is not trusted.");continue}let c=l.min-u.min;if(!(c>0)){e.push(a+" starts at or after its expiry. The record is not trusted.");continue}if(c>oe[i]){e.push(a+" lasts longer than its hard ceiling. The record is not trusted.");continue}let d={kind:i,startedAtMin:u.min,expiresAtMin:l.min};if(i==="prepare_power_cut"){let b=k(t,G.prepare_power_cut_reserve);if(b===null||!Number.isInteger(b)||b<h.reserveMin||b>h.reserveMax){e.push(a+" has no readable reserve inside "+h.reserveMin+"-"+h.reserveMax+" %. The record is not trusted.");continue}d.reservePct=b}r.push({override:d,label:a,expiresText:l.text,remainingMin:Math.max(1,l.min-n)})}return r}function Wi(t){let n=k(t,G.revision);return n===null?{known:!1,value:null,reason:"The stored plan revision cannot be read."}:!Number.isInteger(n)||n<0?{known:!1,value:null,reason:"The stored plan revision is not a whole number."}:{known:!0,value:n,reason:""}}function Fi(t,n,e,r=null){let i=Object.values(G),a=i.filter(b=>t[b]===void 0);if(a.length===i.length)return null;let o=$i(t,G.confirmed),s={confirmed:o,minExpiryMin:k(t,G.min_expiry),holdDefaultMin:k(t,G.hold_default),holdCapMin:k(t,G.hold_cap),skipUntilMin:Oi(U(t,G.skip_until)),skipCapMin:k(t,G.skip_cap),cutDefaultMin:k(t,G.cut_default),cutCapMin:k(t,G.cut_cap),cutReservePct:k(t,G.cut_reserve)},l=Ct(s,{currentReservePct:e}),u=Ct(s),c=[],d=Li(t,n,c);return{missing:a,confirmed:o,policy:l,startPolicy:u,socPct:r,revision:Wi(t),active:d,problems:c,nowMin:n}}function tr(t,n,e){let r=Zn(t,n),i=r.fields.find(l=>l.path==="reserve.backupPct"),a=t.plan?.battery_soc??t.dump_to_grid?.battery_soc,o=a?k(n,a):null,s=Fi(n,e,i&&i.known?i.value:null,o);return s?{...r,overrides:s.active.map(l=>l.override),helpers:s}:{...r,helpers:null}}var Ve=Object.freeze({PROPOSED:{kind:"PROPOSED",label:"Proposed",icon:"mdi:lightbulb-outline",meaning:"Proposed: shown for review, not armed and not applied."},ARMED:{kind:"ARMED",label:"Armed",icon:"mdi:shield-check-outline",meaning:"Armed: scheduled and waiting to start, not yet running."},EXECUTING:{kind:"EXECUTING",label:"Executing",icon:"mdi:progress-clock",meaning:"Executing: a session is running now and no read-back has confirmed this value yet."},APPLIED_VERIFIED:{kind:"APPLIED_VERIFIED",label:"Applied and verified",icon:"mdi:check-circle-outline",meaning:"Applied and verified: a read-back from the system equals this value."},MISMATCH:{kind:"MISMATCH",label:"Mismatch",icon:"mdi:alert-circle-outline",meaning:"Mismatch: what the system reports differs from the intended value."},UNKNOWN:{kind:"UNKNOWN",label:"Unknown",icon:"mdi:help-circle-outline",meaning:"Unknown: this cannot be read, so no value is shown."}}),Vi="SHADOW / advice only. Nothing shown here is applied by this view: it displays what Home Assistant, the inverter and Intelligence report, and it writes nothing.",Ui="Quick overrides: none active. Shown as status only; starting one needs a plan helper that does not exist yet.",Hi="Quick overrides: none active. Shown as status only; starting one needs the guarded start path, which is not installed.",Gi="Status only: nothing in this view starts, cancels or enforces an override. An override can only hold back a start or raise a reserve; it never writes the inverter's table and never stops a running session.";function Lt(t,n){return"The battery is at "+Math.round(t)+" percent, below the "+Math.round(n)+" percent reserve. Nothing is charging. Use Charge Battery if you want it filled."}var Bi={HIGH:"High",MEDIUM:"Medium",LOW:"Low",INSUFFICIENT:"Insufficient evidence"},Ot=t=>t.toFixed(1)+" kWh";function $t(t){return Ve[t]}function nr(t){return`${F(t.startMin)} ${t.source==="Grid"?"charge from grid":"no grid charge"}, ${t.powerW} W, to ${t.targetSoc} %`}var Ki=t=>"time"in q[t.path];function rr(t,n){return Ki(t)?F(n):t.unit?`${n} ${t.unit}`:String(n)}function ji(t){if(!t.known)return{path:t.path,label:t.label,known:!1,text:"Unknown",reason:t.reason??"Not readable.",chip:Ve.UNKNOWN,remarks:[]};let n=[],e=r=>rr(t,r);return t.observed!==null&&t.observed!==t.value&&n.push(`The system reports ${e(t.observed)}, not ${e(t.value)}.`),t.proposal!==null&&n.push(`Intelligence suggests ${e(t.proposal)} (not adopted; nothing here changes it).`),t.state==="PROPOSED"&&t.observed===null&&n.push("No read-back is available for this value."),{path:t.path,label:t.label,known:!0,text:rr(t,t.value),reason:"",chip:$t(t.state),remarks:n}}function zi(t){let n=t.intended,e=t.observed;if(!e)return null;let r=[];return n.startMin!==e.startMin&&r.push(`start ${F(n.startMin)} intended, ${F(e.startMin)} on the inverter`),n.source!==e.source&&r.push(`charge source ${n.source} intended, ${e.source} on the inverter`),n.powerW!==e.powerW&&r.push(`power ${n.powerW} W intended, ${e.powerW} W on the inverter`),n.targetSoc!==e.targetSoc&&r.push(`target ${n.targetSoc} % intended, ${e.targetSoc} % on the inverter`),r.length?`Slot ${t.index} differs from the inverter: ${r.join("; ")}. It is not applied there, and this view does not apply it.`:null}var Yi={"native-fallback":"Native (unchanged)","derived:charge":"Derived from the charge plan","derived:export":"Derived from the export plan"},qi={OK:"Compiled",INFEASIBLE:"Does not fit six slots",CONFLICT:"Conflict with a manual change",REFUSED:"Not compiled"};function Xi(t){let n=t.tou;if(!n.readable||!n.compile)return{readable:!1,headline:n.reason??"The six slots cannot be read.",statusText:null,reasons:[...n.notes],slots:[],mismatchCount:0};let e=n.compile,r=e.slotReports.map((s,l)=>{let u=e.slotReports[(l+1)%e.slotReports.length],c=s.state==="MISMATCH"?zi(s):null,d=s.state==="APPLIED_VERIFIED"?"APPLIED_VERIFIED":s.state==="MISMATCH"?"MISMATCH":"PROPOSED";return{index:s.index,rangeText:`${F(s.intended.startMin)} to ${F(u.intended.startMin)}`,spanMin:W(s.intended.startMin,u.intended.startMin)||1440,intendedText:nr(s.intended),inverterText:s.observed?nr(s.observed):null,originText:Yi[s.origin]??s.origin,chip:Ve[d],mismatch:c}}),i=r.filter(s=>s.mismatch!==null).length,a=[...new Set([...e.reasons,...n.notes])],o;return e.status==="OK"&&e.fallback?o="No armed charge or export changes the table: the six slots are as the inverter reports them.":e.status==="OK"?o=`If the armed plan were compiled, ${i} of the six slots would differ from what the inverter reports.`:e.status==="INFEASIBLE"?o="The plan does not fit the inverter's six slots. Nothing is truncated; the native table stays as it is.":e.status==="CONFLICT"?o="The inverter's table looks changed outside ECCO. Nothing is planned until that is reviewed.":o="The plan is not compiled; the native table stays as it is.",{readable:!0,headline:o,statusText:qi[e.status]??e.status,reasons:a,slots:r,mismatchCount:i}}var Qi={hold_battery:()=>"Intended: no export starts and no discretionary rate edits; charging and the inverter table are untouched.",skip_tonight:()=>"Intended: tonight's export is held; charging continues.",prepare_power_cut:t=>`Intended: the reserve is raised to ${t??"?"} % (never lowered) and export starts are held.`};function Ji(){let t=(e,r)=>e==="skipUntilMin"?F(r):e==="cutReservePct"?`${r} %`:ne(r),n={minExpiryMin:"Shortest allowed override",holdDefaultMin:"Hold battery default",holdCapMin:"Hold battery maximum",skipUntilMin:"Skip tonight ends at",skipCapMin:"Skip tonight maximum",cutDefaultMin:"Prepare for power cut default",cutCapMin:"Prepare for power cut maximum",cutReservePct:"Power-cut reserve"};return Yn.map(e=>`${n[e.key]??e.key}: ${t(e.key,e.value)}. ${e.why}`)}function Zi(t){let n=e=>ne(e);return`Limits set by you: ${te.hold_battery} default ${n(t.holdDefaultMin)}, up to ${n(t.holdCapMin)}; ${te.skip_tonight} until ${F(t.skipUntilMin)}, up to ${n(t.skipCapMin)}; ${te.prepare_power_cut} default ${n(t.cutDefaultMin)}, up to ${n(t.cutCapMin)}, reserve ${t.cutReservePct} %. Hard ceilings no setting can exceed: ${n(oe.hold_battery)}, ${n(oe.skip_tonight)}, ${n(oe.prepare_power_cut)}.`}function ea(t){let n=t.policy,e=t.active.map(i=>({kind:i.override.kind,label:i.label,untilText:`until ${i.expiresText}`,countdownText:`ends in ${ne(i.remainingMin)}`,effectText:Qi[i.override.kind](i.override.reservePct),belowReserve:i.override.kind==="prepare_power_cut"&&typeof i.override.reservePct=="number"&&t.socPct!==null&&t.socPct<i.override.reservePct?Lt(t.socPct,i.override.reservePct):null})),r=t.revision.known?t.revision.value===0?"Plan revision: none recorded yet.":`Plan revision ${t.revision.value} (stored in the plan helper).`:`Plan revision: unknown (${t.revision.reason})`;return{policyOk:n.ok,policyLine:n.ok?Zi(n.config):"The override limits are not usable, so no override can be started. Nothing falls back to proposed values.",reasons:n.ok?[]:[...n.reasons],warnings:n.ok?[...n.warnings]:[],missing:[...t.missing],proposed:n.ok?[]:Ji(),revisionText:r,rows:e,problems:[...t.problems],note:Gi}}function ir(t){let n=t.helpers??null,e=t.tomorrow,r=(a,o,s,l)=>s.known?{key:a,label:o,known:!0,text:l(s.value),reason:"",note:s.simulated?"simulated, not measured":"",chip:$t(s.state)}:{key:a,label:o,known:!1,text:"Unknown",reason:s.reason,note:"",chip:Ve.UNKNOWN},i=[r("import","Expected import",e.importKwh,Ot),r("export","Expected export",e.exportKwh,Ot),r("solar","Expected solar",e.solarKwh,Ot),r("finish","Charge finishes",e.chargeFinishMin,a=>F(a)),r("reserve","Reserve",e.reservePct,a=>`${a} %`)];return i.push(e.confidence.known?{key:"confidence",label:"Confidence",known:!0,text:Bi[e.confidence.level]??e.confidence.level,reason:"",note:"",chip:$t(e.confidence.state)}:{key:"confidence",label:"Confidence",known:!1,text:"Unknown",reason:"Intelligence did not state how sure it is.",note:"",chip:Ve.UNKNOWN}),{statusLine:Vi,adviceNote:t.adviceNote,figures:i,why:e.why.map(a=>({origin:a.origin,text:a.text})),settings:t.fields.map(ji),tou:Xi(t),overridesLine:n?t.overrides.length===0?Hi:`Quick overrides active: ${t.overrides.map(a=>te[a.kind]).join(", ")} (status only).`:t.overrides.length===0?Ui:`Quick overrides active: ${t.overrides.map(a=>a.kind).join(", ")} (status only).`,overrideBlock:n?ea(n):null}}function Wt(t){return p`<span class="plan-chip chip-${t.kind.toLowerCase()}" title=${t.meaning}><ha-icon icon=${t.icon} aria-hidden="true"></ha-icon><span class="plan-chip-text">${t.label}</span></span>`}function ta(t){return p`
    <div class="plan-figure ${t.known?"":"is-unknown"}" data-figure=${t.key}>
      <dt>${t.label}</dt>
      <dd>
        <span class="plan-figure-value">${t.text}</span>
        ${t.note?p`<span class="plan-note">${t.note}</span>`:m}
        ${Wt(t.chip)}
        ${t.known?m:p`<span class="plan-reason">${t.reason}</span>`}
      </dd>
    </div>
  `}function na(t){return p`
    <li class="plan-setting ${t.known?"":"is-unknown"}" data-setting=${t.path}>
      <span class="plan-setting-label">${t.label}</span>
      <span class="plan-setting-value">${t.text}</span>
      ${Wt(t.chip)}
      ${t.known?t.remarks.map(n=>p`<span class="plan-reason">${n}</span>`):p`<span class="plan-reason">${t.reason}</span>`}
    </li>
  `}function ra(t){return p`
    <li class="plan-setting" data-override=${t.kind}>
      <span class="plan-setting-label">${t.label}</span>
      <span class="plan-setting-value">${t.untilText}</span>
      <span class="plan-note">${t.countdownText}</span>
      <span class="plan-reason">${t.effectText}</span>
      ${t.belowReserve?p`<span class="plan-reason plan-below-reserve" data-below-reserve role="note">${t.belowReserve}</span>`:m}
    </li>
  `}function ia(t){return p`
    <div class="plan-override-block" data-block="overrides">
      ${t.rows.length?p`<ul class="plan-settings">${t.rows.map(ra)}</ul>`:m}
      <p class="plan-reason" data-override-policy=${t.policyOk?"ok":"unusable"}>${t.policyLine}</p>
      ${t.reasons.length?p`<ul class="plan-reasons">${t.reasons.map(n=>p`<li>${n}</li>`)}</ul>`:m}
      ${t.warnings.length?p`<ul class="plan-reasons">${t.warnings.map(n=>p`<li>${n}</li>`)}</ul>`:m}
      ${t.problems.length?p`<ul class="plan-reasons" data-override-problems>${t.problems.map(n=>p`<li>${n}</li>`)}</ul>`:m}
      ${t.missing.length?p`<p class="plan-reason">Plan helper entities not found: ${t.missing.join(", ")}.</p>`:m}
      ${t.proposed.length?p`
            <details class="plan-why">
              <summary>Proposed values (not in use)</summary>
              <ul>${t.proposed.map(n=>p`<li>${n}</li>`)}</ul>
            </details>
          `:m}
      <p class="plan-reason">${t.revisionText}</p>
      <p class="plan-reason">${t.note}</p>
    </div>
  `}function aa(t){return p`
    <li class="plan-slot ${t.mismatch?"is-mismatch":""}" data-slot=${t.index}>
      <div class="plan-slot-head">
        <span class="plan-slot-name">Slot ${t.index}</span>
        <span class="plan-slot-range">${t.rangeText}</span>
        ${Wt(t.chip)}
      </div>
      <div class="plan-slot-line"><span class="plan-slot-key">Intended</span> ${t.intendedText} <span class="plan-note">${t.originText}</span></div>
      <div class="plan-slot-line"><span class="plan-slot-key">Inverter</span> ${t.inverterText??"not read"}</div>
      ${t.mismatch?p`<p class="plan-mismatch" role="note"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon><span>${t.mismatch}</span></p>`:m}
    </li>
  `}function ar(t,n,e){let r=t.tou,i=e?p`<span class="plan-badge"><ha-icon icon="mdi:shield-check-outline" aria-hidden="true"></ha-icon>Guarded controls</span>`:p`<span class="plan-badge"><ha-icon icon="mdi:eye-outline" aria-hidden="true"></ha-icon>Read only</span>`;return p`
      <h2 class="plan-title">Plan ${i}</h2>
      <p class="plan-statusline" role="status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon><span>${t.statusLine}</span></p>

      <div class="plan-block" data-block="tomorrow">
        <h3 class="plan-heading">Tomorrow's Plan</h3>
        ${t.adviceNote?p`<p class="plan-reason plan-advice-note">${t.adviceNote}</p>`:m}
        <dl class="plan-figures">${t.figures.map(ta)}</dl>
        <details class="plan-why">
          <summary>Why?</summary>
          <ul>${t.why.map(a=>p`<li data-origin=${a.origin}>${a.text}</li>`)}</ul>
        </details>
        <details class="plan-why plan-settings-details">
          <summary>Planned settings</summary>
          <ul class="plan-settings">${t.settings.map(na)}</ul>
        </details>
        <p class="plan-overrides">${t.overridesLine}</p>${t.overrideBlock?ia(t.overrideBlock):m}${n}
      </div>

      <div class="plan-block" data-block="tou">
        <h3 class="plan-heading">Six-slot TOU timeline${r.statusText?p` <span class="plan-note">${r.statusText}</span>`:m}</h3>
        <p class="plan-tou-headline">${r.headline}</p>
        ${r.reasons.length?p`<ul class="plan-reasons">${r.reasons.map(a=>p`<li>${a}</li>`)}</ul>`:m}
        ${r.slots.length?p`
              <div class="plan-bar" aria-hidden="true">
                ${r.slots.map(a=>p`<span class="plan-seg ${a.mismatch?"is-mismatch":""}" style=${"flex-grow:"+a.spanMin}>${a.index}</span>`)}
              </div>
              <ol class="plan-slots">${r.slots.map(aa)}</ol>
            `:m}
      </div>
    `}function oa(t,n=m){return n!==m?p`
    <section class="plan-section" aria-label="Plan, with guarded controls">${ar(t,n,!0)}</section>
  `:p`
    <section class="plan-section" aria-label="Plan, read only">${ar(t,m,!1)}</section>
  `}function or(t,n,e,r){if(!t||t.show_plan!==!0)return m;let i=typeof e=="number"&&Number.isFinite(e)?e:Date.now(),a=tr(t,n??{},Math.floor(i/6e4)),o=ir(a);return oa(o,r?r({snap:a,states:n??{},nowMs:i}):m)}var sr=ce`
  .plan-section {
    margin-top: 18px;
    padding: 14px;
    border-radius: 16px;
    background: var(--eaa-surface);
    border: 1px solid var(--eaa-border);
    min-width: 0;
  }
  .plan-title {
    margin: 0 0 8px;
    font-size: 16px;
    font-weight: 700;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .plan-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid var(--eaa-border);
    color: var(--eaa-text-muted);
  }
  .plan-badge ha-icon,
  .plan-statusline ha-icon,
  .plan-mismatch ha-icon {
    --mdc-icon-size: 16px;
    flex: 0 0 auto;
  }
  .plan-statusline {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    margin: 0 0 12px;
    font-size: 13px;
    color: var(--eaa-text-muted);
    overflow-wrap: anywhere;
  }
  .plan-block {
    margin-top: 12px;
    min-width: 0;
  }
  .plan-heading {
    margin: 0 0 6px;
    font-size: 14px;
    font-weight: 700;
  }
  .plan-figures {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 10px;
    margin: 0;
  }
  .plan-figure {
    min-width: 0;
    padding: 8px 10px;
    border-radius: 12px;
    border: 1px solid var(--eaa-border);
  }
  .plan-figure dt {
    font-size: 12px;
    color: var(--eaa-text-muted);
  }
  .plan-figure dd {
    margin: 2px 0 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
    min-width: 0;
  }
  .plan-figure-value {
    font-size: 18px;
    font-weight: 700;
  }
  .plan-figure.is-unknown .plan-figure-value {
    font-size: 15px;
    font-style: italic;
    color: var(--eaa-text-muted);
  }
  .plan-note {
    font-size: 11px;
    color: var(--eaa-text-muted);
  }
  .plan-reason {
    flex-basis: 100%;
    font-size: 12px;
    color: var(--eaa-text-muted);
    overflow-wrap: anywhere;
  }
  .plan-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    border: 1px solid currentColor;
    white-space: nowrap;
  }
  .plan-chip ha-icon {
    --mdc-icon-size: 14px;
  }
  .chip-proposed { color: var(--eaa-schedule); }
  .chip-armed { color: var(--eaa-armed); }
  .chip-executing { color: var(--eaa-accent); }
  .chip-applied_verified { color: var(--eaa-ok); }
  .chip-mismatch { color: var(--eaa-fault); }
  .chip-unknown { color: var(--eaa-text-muted); border-style: dashed; }
  .plan-why {
    margin-top: 10px;
    font-size: 13px;
  }
  .plan-why summary {
    cursor: pointer;
    min-height: 36px;
    display: flex;
    align-items: center;
    font-weight: 600;
  }
  .plan-why ul,
  .plan-reasons,
  .plan-slots,
  .plan-settings {
    margin: 4px 0 0;
    padding-left: 18px;
  }
  .plan-why li,
  .plan-reasons li {
    overflow-wrap: anywhere;
    margin-bottom: 4px;
  }
  .plan-settings,
  .plan-slots {
    list-style: none;
    padding-left: 0;
  }
  .plan-setting {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
    padding: 6px 0;
    border-top: 1px solid var(--eaa-border);
  }
  .plan-setting-label {
    flex: 1 1 160px;
    min-width: 0;
  }
  .plan-setting-value {
    font-weight: 600;
  }
  .plan-setting.is-unknown .plan-setting-value {
    font-style: italic;
    color: var(--eaa-text-muted);
  }
  .plan-overrides {
    margin: 10px 0 0;
    font-size: 12px;
    color: var(--eaa-text-muted);
  }
  .plan-tou-headline {
    margin: 0 0 6px;
    font-size: 13px;
    overflow-wrap: anywhere;
  }
  .plan-reasons {
    font-size: 12px;
    color: var(--eaa-warning);
  }
  .plan-bar {
    display: flex;
    gap: 2px;
    margin: 8px 0;
    height: 24px;
  }
  .plan-seg {
    flex-basis: 0;
    min-width: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    border-radius: 6px;
    background: color-mix(in srgb, var(--eaa-accent) 22%, transparent);
    border: 1px solid var(--eaa-border);
  }
  .plan-seg.is-mismatch {
    background: color-mix(in srgb, var(--eaa-fault) 28%, transparent);
    border-style: dashed;
  }
  .plan-slot {
    padding: 8px 10px;
    margin-bottom: 8px;
    border-radius: 12px;
    border: 1px solid var(--eaa-border);
    font-size: 13px;
    min-width: 0;
  }
  .plan-slot.is-mismatch {
    border-color: var(--eaa-fault);
    border-style: dashed;
  }
  .plan-slot-head {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
  }
  .plan-slot-name {
    font-weight: 700;
  }
  .plan-slot-key {
    display: inline-block;
    min-width: 64px;
    color: var(--eaa-text-muted);
  }
  .plan-slot-line {
    margin-top: 2px;
    overflow-wrap: anywhere;
  }
  .plan-mismatch {
    display: flex;
    gap: 6px;
    align-items: flex-start;
    margin: 6px 0 0;
    font-size: 12px;
    color: var(--eaa-fault);
    overflow-wrap: anywhere;
  }
`;var se={last_result:"input_text.ecco_plan_last_result",start_script:"script.ecco_plan_override_start",cancel_script:"script.ecco_plan_override_cancel"};function Ft(t,n,e){let r={kind:t};return n.untilLocal===!0?r.until_local=!0:typeof n.expiryMin=="number"&&(r.expiry_min=n.expiryMin),typeof e=="number"&&(r.expected_revision=e),{domain:"script",service:"turn_on",data:{entity_id:se.start_script,variables:r}}}function lr(t,n){let e={kind:t};return typeof n=="number"&&(e.expected_revision=n),{domain:"script",service:"turn_on",data:{entity_id:se.cancel_script,variables:e}}}function cr(t){return/^script\.[a-z0-9_]+$/.test(t)?{domain:"script",service:"turn_on",data:{entity_id:t}}:null}function ur(t,n){if(typeof t!="object"||t===null)return!1;let e=t;if(e.domain!=="script"||e.service!=="turn_on"||typeof e.data!="object"||e.data===null)return!1;let r=e.data;if(Object.keys(e.data).some(o=>o!=="entity_id"&&o!=="variables"))return!1;let i=r.entity_id,a=typeof n=="string"&&n!==""&&i===n;return i!==se.start_script&&i!==se.cancel_script&&!a?!1:r.variables===void 0?!0:typeof r.variables!="object"||r.variables===null||a?!1:Object.keys(r.variables).every(o=>o==="kind"||o==="expiry_min"||o==="until_local"||o==="expected_revision")}function dr(t){let n=t.snap.helpers;if(!n)return null;let e=Math.floor(t.nowMs/6e4),r=n.revision.known?n.revision.value:null,i=[se.start_script,se.cancel_script].filter(c=>t.states[c]===void 0),a=t.snap.fields.find(c=>c.path==="reserve.backupPct"),o=a&&a.known?a.value:null,s=n.startPolicy.ok?n.startPolicy.config:null,l=U(t.states,se.last_result);return{kinds:ge.map(c=>{let d=n.active.find(E=>E.override.kind===c)??null,b=[],v=null;if(!s)v=n.startPolicy.ok?null:n.startPolicy.reasons[0]??"The override limits are not usable.";else{let E=jn(c,s,t.clock),O=E.length?E[0]:null,_=zn(c,e,O?O.expiryMin:null,n.startPolicy,{clock:t.clock,currentReservePct:o});!_.ok&&(_.code==="RESERVE_UNKNOWN"||_.code==="RESERVE_BELOW_CURRENT")?v=_.error:E.length===0?v="No length fits the owner's limits.":b=E.map(T=>({id:T.id,label:T.label,isDefault:T.isDefault,call:T.untilMin!==null?Ft(c,{untilLocal:!0},r):Ft(c,{expiryMin:T.expiryMin},r)}))}let g=d||null,P=c==="prepare_power_cut"&&g&&typeof g.override.reservePct=="number"&&n.socPct!==null&&n.socPct<g.override.reservePct?Lt(n.socPct,g.override.reservePct):null;return{kind:c,label:te[c],active:d!==null,activeText:d?"Active until "+d.expiresText+" (ends in "+ne(d.remainingMin)+")":null,choices:b,blockedReason:v,cancel:d?lr(c,r):null,belowReserve:P}}),lastResult:l,missingScripts:i}}function sa(t,n){if(typeof t!="number"||!Number.isFinite(t))return null;let r=(u=>((Math.floor(u/6e4)-n(u))%1440+1440)%1440)(t),i=n(t),a=i-n(t+864e5);if(a===0)return{nowWallMin:r,day:{changeAtMin:0,deltaMin:0}};if(a!==60&&a!==-60)return null;let o=t,s=t+864e5;for(;s-o>6e4;){let u=Math.floor((o+s)/2);n(u)===i?o=u:s=u}let l=((Math.floor(s/6e4)-i)%1440+1440)%1440;return{nowWallMin:r,day:{changeAtMin:l,deltaMin:a}}}function pr(t){return sa(t,n=>new Date(n).getTimezoneOffset())}var la={hold_battery:"Holds ECCO back from starting an export. Charging and the battery's own work carry on.",skip_tonight:"Holds tonight's export. Charging continues.",prepare_power_cut:"Raises a protected reserve (never lowers it) and holds exports. It does not charge the battery."},ca="Partial protection only: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant or by an assistant. These overrides and the reserve protect ECCO's own starts and this card, not an administrator, an assistant or a press of the dongle's own button, and their helpers are plain helpers that an administrator or assistant can write. Binding the Start button needs a firmware gate (a flash, approved separately).";function ua(t,n){return p`
    <div class="plan-control" data-control=${t.kind}>
      <div class="plan-control-head">
        <span class="plan-setting-label">${t.label}</span>
        ${t.activeText?p`<span class="plan-setting-value" data-control-active>${t.activeText}</span>`:m}
      </div>
      <p class="plan-reason">${la[t.kind]??""}</p>
      ${t.belowReserve?p`<p class="plan-reason plan-below-reserve" data-below-reserve role="note">${t.belowReserve}</p>`:m}
      ${t.blockedReason?p`<p class="plan-reason" data-control-blocked>${t.blockedReason}</p>`:m}
      <div class="plan-control-buttons">
        ${t.choices.length?p`<span class="plan-note">${t.active?"Start again for":"Start for"}</span>`:m}
        ${t.choices.map(e=>p`<button type="button" class="plan-control-btn ${e.isDefault?"is-default":""}" data-choice=${e.id}
            aria-label=${t.label+": start for "+e.label} @click=${()=>n(e.call)}>${e.label}</button>`)}
        ${t.cancel?p`<button type="button" class="plan-control-btn is-cancel" data-cancel aria-label=${"Cancel "+t.label} @click=${()=>n(t.cancel)}>Cancel</button>`:m}
      </div>
    </div>
  `}function da(t,n){return p`
    <div class="plan-controls" data-block="controls">
      <h3 class="plan-heading">Quick overrides</h3>
      <p class="plan-reason">They only hold ECCO's starts back or raise a protected reserve. Home Assistant checks every one against your limits again and may refuse it.</p>
      <p class="plan-reason plan-limitation" data-plan-limitation role="note">${ca}</p>
      ${t.missingScripts.length?p`<p class="plan-reason" data-controls-missing>The guarded scripts were not found (${t.missingScripts.join(", ")}), so no override can be started or cancelled here.</p>`:t.kinds.map(e=>ua(e,n))}
      ${t.lastResult?p`<p class="plan-reason plan-result" data-plan-result role="status">Last answer: ${t.lastResult}</p>`:m}
    </div>
  `}function hr(t){return({snap:n,states:e,nowMs:r})=>{let i=dr({snap:n,states:e,nowMs:r,clock:pr(r)});return i?da(i,t):m}}var mr=ce`
  .plan-controls {
    margin-top: 12px;
    min-width: 0;
  }
  .plan-control {
    padding: 8px 0;
    border-top: 1px solid var(--eaa-border);
    min-width: 0;
  }
  .plan-control-head {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
  }
  .plan-control-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 8px;
    align-items: center;
    margin-top: 4px;
  }
  .plan-control-btn {
    min-height: 40px;
    min-width: 44px;
    padding: 6px 14px;
    border-radius: 999px;
    border: 1px solid var(--eaa-border);
    background: transparent;
    color: inherit;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .plan-control-btn.is-default {
    border-color: var(--eaa-accent);
  }
  .plan-control-btn.is-cancel {
    border-color: var(--eaa-fault);
    color: var(--eaa-fault);
  }
  .plan-control-btn:focus-visible {
    outline: 2px solid var(--eaa-accent);
    outline-offset: 2px;
  }
  .plan-below-reserve,
  .plan-limitation {
    color: var(--eaa-warning);
  }
  .plan-result {
    margin-top: 8px;
  }
`;var et=4e3,pa=1e3,M=class extends ae{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:ft,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!e.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=e}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(e){return!!this._config}willUpdate(){let e=this._config?.free_power;if(e){this._pendingPower!==void 0&&x(this._entityState(e.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&x(this._entityState(e.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let a=y(this._entityState(e.active)),o=y(this._entityState(e.write_enable)),s=y(this._entityState(e.operation_in_progress)),l=this._entityState(e.status),u=qe({active:a,armed:o,operationInProgress:s,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==u&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=u}let r=this._config?.schedule;r&&(this._pendingSchedulePower!==void 0&&x(this._entityState(r.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&x(this._entityState(r.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&x(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&x(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&x(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let a=i.schedule;a&&(this._pendingDumpSchedulePower!==void 0&&x(this._entityState(a.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&x(this._entityState(a.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&x(this._entityState(a.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let o=y(this._entityState(i.active)),s=y(this._entityState(i.write_enable)),l=y(this._entityState(i.operation_in_progress)),u=y(this._entityState(i.snapshot_valid)),c=this._entityState(i.status),d=Xe({active:o,armed:s,operationInProgress:l,snapshotValid:u,statusText:c});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==d&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=d}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let a=this._trackSummary();En(a.fp.state,a.dump.state)&&(this._track=wt(a.fp.state,a.dump.state))}}updated(){let e=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();e&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},pa):!e&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let e=this._config?.free_power;return e?y(this._entityState(e.active))===!0:!1}_scheduleArmed(){let e=this._config?.schedule;return e?y(this._entityState(e.armed))===!0:!1}_dumpActive(){let e=this._config?.dump_to_grid;return e?y(this._entityState(e.active))===!0:!1}_dumpScheduleArmed(){let e=this._config?.dump_to_grid?.schedule;return e?y(this._entityState(e.armed))===!0:!1}_freePowerVisualStateForInterlock(){let e=this._config?.free_power;if(!e||!this.hass)return null;let r=y(this._entityState(e.active)),i=y(this._entityState(e.write_enable)),a=y(this._entityState(e.operation_in_progress)),o=this._entityState(e.status);return qe({active:r,armed:i,operationInProgress:a,statusText:o})}_dumpVisualStateForInterlock(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return null;let r=y(this._entityState(e.active)),i=y(this._entityState(e.write_enable)),a=y(this._entityState(e.operation_in_progress)),o=y(this._entityState(e.snapshot_valid)),s=this._entityState(e.status);return Xe({active:r,armed:i,operationInProgress:a,snapshotValid:o,statusText:s})}_entityState(e){if(!(!e||!this.hass))return this.hass.states[e]?.state}_entity(e){if(!(!e||!this.hass))return this.hass.states[e]}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_callService(e,r,i){this.hass?.callService&&this.hass.callService(e,r,i)}_callServiceObj(e){this._callService(e.domain,e.service,e.data)}render(){if(!this._config)return p``;let e=this._config.title??ft;return this._config.layout==="tabbed"?this._renderTabbed(e):p`
""")),
    (_blk(r"""
          ${this._renderDumpToGridTile()}
        </div>
      </ha-card>
"""),
     _blk(r"""
          ${this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
""")),
    (_blk(r"""
    `}_trackSummary(){let e=this._freePowerVisualStateForInterlock(),t=this._dumpVisualStateForInterlock(),i={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},n=this._config?.free_power;if(e!==null&&n){let l=this._config?.schedule,d=l?Oe(e,Re({armed:m(this._entityState(l.armed))})):e,c=K(e,t)?"interlocked":d;i={state:c,pill:c,label:this._labelFor(c),statusText:this._entityState(n.status)}}let s=this._config?.dump_to_grid,o=s&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(t!==null&&s){let l=s.schedule,d=De(t,l?m(this._entityState(l.armed)):null),c=K(t,e)?"interlocked":d;o={state:c,pill:c,label:Ee(c),statusText:this._entityState(s.status)}}return{fp:i,dump:o}}_selectTrack(e){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=e}_renderTabbed(e){let t=this._trackSummary(),i=this._track??Ae(t.fp.state,t.dump.state),n=i==="free_power"?"dump_to_grid":"free_power",s=i==="free_power"?t.dump:t.fp,o=_t(ft(s.state)),l=o==="fault"?"mdi:alert-circle-outline":o==="warning"?"mdi:alert-outline":"mdi:information-outline";return u`
"""),
     _blk(r"""
    `}_renderPlan(){return or(this._config,this.hass?.states,void 0,hr(e=>this._callPlanService(e)))}_callPlanService(e){ur(e,this._config?.dump_to_grid?.guarded_start)&&this._callService(e.domain,e.service,e.data)}_pressDumpStart(e){if(e.guarded_start!==void 0&&e.guarded_start!==""){let r=cr(e.guarded_start);r&&this._callPlanService(r);return}this._callService("button","press",{entity_id:e.start})}_trackSummary(){let e=this._freePowerVisualStateForInterlock(),r=this._dumpVisualStateForInterlock(),i={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},a=this._config?.free_power;if(e!==null&&a){let l=this._config?.schedule,u=l?kt(e,yt({armed:y(this._entityState(l.armed))})):e,c=Ce(e,r)?"interlocked":u;i={state:c,pill:c,label:this._labelFor(c),statusText:this._entityState(a.status)}}let o=this._config?.dump_to_grid,s=o&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(r!==null&&o){let l=o.schedule,u=bt(r,l?y(this._entityState(l.armed)):null),c=Ce(r,e)?"interlocked":u;s={state:c,pill:c,label:vt(c),statusText:this._entityState(o.status)}}return{fp:i,dump:s}}_selectTrack(e){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=e}_renderTabbed(e){let r=this._trackSummary(),i=this._track??wt(r.fp.state,r.dump.state),a=i==="free_power"?"dump_to_grid":"free_power",o=i==="free_power"?r.dump:r.fp,s=Mn(kn(o.state)),l=s==="fault"?"mdi:alert-circle-outline":s==="warning"?"mdi:alert-outline":"mdi:information-outline";return p`
""")),
    (_blk(r"""
            <span class="state-pill state-${t.fp.pill}">Free Power · ${t.fp.label}</span>
            <span class="state-pill state-${t.dump.pill}">Dump to Grid · ${t.dump.label}</span>
"""),
     _blk(r"""
            <span class="state-pill state-${r.fp.pill}">Free Power · ${r.fp.label}</span>
            <span class="state-pill state-${r.dump.pill}">Dump to Grid · ${r.dump.label}</span>
""")),
    (_blk(r"""
        ${o?u`
              <div class="track-alert track-alert-${o}" role="status">
"""),
     _blk(r"""
        ${s?p`
              <div class="track-alert track-alert-${s}" role="status">
""")),
    (_blk(r"""
                <div class="track-alert-text">${bt(gt(n),s.label,s.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(n)}>Show</button>
"""),
     _blk(r"""
                <div class="track-alert-text">${Rn(Pn(a),o.label,o.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(a)}>Show</button>
""")),
    (_blk(r"""
              </div>
            `:h}
        <div class="actions-grid is-tabbed">
"""),
     _blk(r"""
              </div>
            `:m}
        <div class="actions-grid is-tabbed">
""")),
    (_blk(r"""
          ${i==="free_power"?this._renderFreePowerTile():this._renderDumpToGridTile()}
        </div>
      </ha-card>
"""),
     _blk(r"""
          ${i==="free_power"?this._renderFreePowerTile():this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
""")),
    (_blk(r"""
    `}_renderFreePowerTile(){let e=this._config?.free_power;if(!e||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=ne({active:t,armed:i,operationInProgress:n,statusText:o});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let d=this._config?.schedule,c=d?m(this._entityState(d.armed)):null,p=Re({armed:c}),y=d?Oe(l,p):l,_=this._dumpVisualStateForInterlock(),w=K(l,_),k=w?"interlocked":y,$=w?Te("Dump to Grid",_):void 0,D=this._entity(e.max_charge_power),b=this._entity(e.duration),U=this._pendingPower??f(D?.state),S=this._pendingDuration??f(b?.state),de=this._iconFor(k),ce=this._labelFor(k);return u`
      <div class="tile free-power-tile state-${k}">
"""),
     _blk(r"""
    `}_renderFreePowerTile(){let e=this._config?.free_power;if(!e||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let r=y(this._entityState(e.active)),i=y(this._entityState(e.write_enable)),a=y(this._entityState(e.operation_in_progress)),o=y(this._entityState(e.snapshot_valid)),s=this._entityState(e.status),l=qe({active:r,armed:i,operationInProgress:a,statusText:s});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let u=this._config?.schedule,c=u?y(this._entityState(u.armed)):null,d=yt({armed:c}),b=u?kt(l,d):l,v=this._dumpVisualStateForInterlock(),g=Ce(l,v),P=g?"interlocked":b,E=g?_t("Dump to Grid",v):void 0,O=this._entity(e.max_charge_power),_=this._entity(e.duration),T=this._pendingPower??x(O?.state),N=this._pendingDuration??x(_?.state),le=this._iconFor(P),f=this._labelFor(P);return p`
      <div class="tile free-power-tile state-${P}">
""")),
    (_blk(r"""
            <ha-icon class="tile-icon" icon=${de}></ha-icon>
"""),
     _blk(r"""
            <ha-icon class="tile-icon" icon=${le}></ha-icon>
""")),
    (_blk(r"""
          <span class="state-pill state-${k}">${ce}</span>
"""),
     _blk(r"""
          <span class="state-pill state-${P}">${f}</span>
""")),
    (_blk(r"""
          ${d&&p==="armed"?this._renderScheduleBanner(d):h}
          ${w?this._renderInterlockBanner($):h}
"""),
     _blk(r"""
          ${u&&d==="armed"?this._renderScheduleBanner(u):m}
          ${g?this._renderInterlockBanner(E):m}
""")),
    (_blk(r"""
          ${this._renderFreePowerBody(l,{fp:e,schedule:d,statusText:o,snapshotValid:s,interlocked:w,stagedPowerW:U,stagedDurationMin:S,stagedPowerEntity:D,stagedDurationEntity:b})}
"""),
     _blk(r"""
          ${this._renderFreePowerBody(l,{fp:e,schedule:u,statusText:s,snapshotValid:o,interlocked:g,stagedPowerW:T,stagedDurationMin:N,stagedPowerEntity:O,stagedDurationEntity:_})}
""")),
    (_blk(r"""
    `}_iconFor(e){if(e==="scheduled")return"mdi:calendar-clock";if(e==="interlocked")return"mdi:lock-outline";switch(e){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":nt(e)}_renderInterlockBanner(e){return u`
"""),
     _blk(r"""
    `}_iconFor(e){if(e==="scheduled")return"mdi:calendar-clock";if(e==="interlocked")return"mdi:lock-outline";switch(e){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":fn(e)}_renderInterlockBanner(e){return p`
""")),
    (_blk(r"""
    `}_renderFreePowerUnavailable(e){return u`
"""),
     _blk(r"""
    `}_renderFreePowerUnavailable(e){return p`
""")),
    (_blk(r"""
    `}_renderFreePowerBody(e,t){switch(e){case"active":return this._renderActiveBody(t);case"busy":return this._renderBusyBody(t.statusText,t.fp.status);case"deferred":return this._renderDeferredBody(t.statusText,t.fp.status);case"recovery_attention":return this._renderAttentionBody(t);default:return this._renderReadyOrArmedBody(e,t)}}_renderReadyOrArmedBody(e,t){let i=!!t.schedule,n=i?this._mode:"now";return u`
      ${i?this._renderModeSelector():h}
      ${n==="later"&&t.schedule?this._renderLaterPanel(t.schedule):this._renderNowPanel(e,t)}
    `}_renderModeSelector(){let e=this._mode==="now";return u`
"""),
     _blk(r"""
    `}_renderFreePowerBody(e,r){switch(e){case"active":return this._renderActiveBody(r);case"busy":return this._renderBusyBody(r.statusText,r.fp.status);case"deferred":return this._renderDeferredBody(r.statusText,r.fp.status);case"recovery_attention":return this._renderAttentionBody(r);default:return this._renderReadyOrArmedBody(e,r)}}_renderReadyOrArmedBody(e,r){let i=!!r.schedule,a=i?this._mode:"now";return p`
      ${i?this._renderModeSelector():m}
      ${a==="later"&&r.schedule?this._renderLaterPanel(r.schedule):this._renderNowPanel(e,r)}
    `}_renderModeSelector(){let e=this._mode==="now";return p`
""")),
    (_blk(r"""
    `}_renderNowPanel(e,t){let i=e==="armed",n=Q(it(e),t.interlocked),s=Q(at(e),t.interlocked);return u`
"""),
     _blk(r"""
    `}_renderNowPanel(e,r){let i=e==="armed",a=Ne(hn(e),r.interlocked),o=Ne(mn(e),r.interlocked);return p`
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingPower=o,onCommit:o=>this._commitNumber("power",o,t.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDuration=o,onCommit:o=>this._commitNumber("duration",o,t.fp.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:J,disabled:r.interlocked,onPreview:s=>this._pendingPower=s,onCommit:s=>this._commitNumber("power",s,r.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:r.interlocked,onPreview:s=>this._pendingDuration=s,onCommit:s=>this._commitNumber("duration",s,r.fp.duration)})}
""")),
    (_blk(r"""
      ${this._renderStatusLine(t.statusText,t.fp.status)}
"""),
     _blk(r"""
      ${this._renderStatusLine(r.statusText,r.fp.status)}
""")),
    (_blk(r"""
          ?disabled=${!s}
          @click=${()=>this._toggleArm(t.fp.write_enable,i)}
"""),
     _blk(r"""
          ?disabled=${!o}
          @click=${()=>this._toggleArm(r.fp.write_enable,i)}
""")),
    (_blk(r"""
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.fp.start})}
"""),
     _blk(r"""
          ?disabled=${!a}
          @click=${()=>this._callService("button","press",{entity_id:r.fp.start})}
""")),
    (_blk(r"""
    `}_renderLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.status),c=this._entityState(e.last_result),p=this._pendingScheduleDuration??f(o?.state),y=this._pendingSchedulePower??f(l?.state),_=d?.attributes?.effective_power_limit_w,w=typeof _=="number"?_:f(typeof _=="string"?_:void 0),k=this._numericAttr(l?.attributes?.max,8e3),$=yt(k,w),D=Pe(c),b=Ce(c),U=!i&&s!==null&&s.getTime()>this._nowMs;return u`
"""),
     _blk(r"""
    `}_renderLaterPanel(e){let r=y(this._entityState(e.armed)),i=Et(r),a=this._entityState(e.start),o=me(a),s=this._entity(e.duration),l=this._entity(e.power),u=this._entity(e.status),c=this._entityState(e.last_result),d=this._pendingScheduleDuration??x(s?.state),b=this._pendingSchedulePower??x(l?.state),v=u?.attributes?.effective_power_limit_w,g=typeof v=="number"?v:x(typeof v=="string"?v:void 0),P=this._numericAttr(l?.attributes?.max,8e3),E=Tn(P,g),O=xt(c),_=St(c),T=!i&&o!==null&&o.getTime()>this._nowMs;return p`
""")),
    (_blk(r"""
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${S=>this._handleScheduleStartChange(e.start,S.target.value)}
"""),
     _blk(r"""
          .value=${o?this._toDatetimeLocalValue(o):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${N=>this._handleScheduleStartChange(e.start,N.target.value)}
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:$,formatValue:T,disabled:i||!l,onPreview:S=>this._pendingSchedulePower=S,onCommit:S=>this._commitScheduleNumber("power",S,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:S=>this._pendingScheduleDuration=S,onCommit:S=>this._commitScheduleNumber("duration",S,e.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:b,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:E,formatValue:J,disabled:i||!l,onPreview:N=>this._pendingSchedulePower=N,onCommit:N=>this._commitScheduleNumber("power",N,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:d,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:i||!s,onPreview:N=>this._pendingScheduleDuration=N,onCommit:N=>this._commitScheduleNumber("duration",N,e.duration)})}
""")),
    (_blk(r"""
      ${c?u`<p class="firmware-note ${D||b?"is-warning":""}">${c}</p>`:h}
"""),
     _blk(r"""
      ${c?p`<p class="firmware-note ${O||_?"is-warning":""}">${c}</p>`:m}
""")),
    (_blk(r"""
          ?disabled=${i||!U}
          @click=${()=>this._callServiceObj(Me(e.armed))}
"""),
     _blk(r"""
          ?disabled=${i||!T}
          @click=${()=>this._callServiceObj(Mt(e.armed))}
""")),
    (_blk(r"""
    `}_renderScheduleBanner(e){let t=this._entityState(e.start),i=M(t),n=f(this._entityState(e.duration)),s=f(this._entityState(e.power)),o=i?J(i.getTime(),this._nowMs):null;return u`
"""),
     _blk(r"""
    `}_renderScheduleBanner(e){let r=this._entityState(e.start),i=me(r),a=x(this._entityState(e.duration)),o=x(this._entityState(e.power)),s=i?Ie(i.getTime(),this._nowMs):null;return p`
""")),
    (_blk(r"""
            ${i?Ve(i):"--"} • ${T(s)} • ${F(n)}
"""),
     _blk(r"""
            ${i?Dt(i):"--"} • ${J(o)} • ${fe(a)}
""")),
    (_blk(r"""
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Fe(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_toDatetimeLocalValue(e){let t=i=>i.toString().padStart(2,"0");return`${e.getFullYear()}-${t(e.getMonth()+1)}-${t(e.getDate())}T${t(e.getHours())}:${t(e.getMinutes())}`}_handleScheduleStartChange(e,t){if(!t)return;let i=new Date(t);Number.isNaN(i.getTime())||this._callServiceObj(vt(e,wt(i)))}_commitScheduleNumber(e,t,i){e==="power"?this._pendingSchedulePower=t:this._pendingScheduleDuration=t,this._callServiceObj(Ie(i,t))}_renderActiveBody(e){let t=this._entityState(e.fp.ends_at),i=M(t),n=i?J(i.getTime(),this._nowMs):null;return u`
"""),
     _blk(r"""
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pt(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_toDatetimeLocalValue(e){let r=i=>i.toString().padStart(2,"0");return`${e.getFullYear()}-${r(e.getMonth()+1)}-${r(e.getDate())}T${r(e.getHours())}:${r(e.getMinutes())}`}_handleScheduleStartChange(e,r){if(!r)return;let i=new Date(r);Number.isNaN(i.getTime())||this._callServiceObj(Dn(e,An(i)))}_commitScheduleNumber(e,r,i){e==="power"?this._pendingSchedulePower=r:this._pendingScheduleDuration=r,this._callServiceObj(Rt(i,r))}_renderActiveBody(e){let r=this._entityState(e.fp.ends_at),i=me(r),a=i?Ie(i.getTime(),this._nowMs):null;return p`
""")),
    (_blk(r"""
        <div class="active-hero-time">${n??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${T(e.stagedPowerW)} target • ends ${i?this._formatClock(i):t??"--"}
"""),
     _blk(r"""
        <div class="active-hero-time">${a??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${J(e.stagedPowerW)} target • ends ${i?this._formatClock(i):r??"--"}
""")),
    (_blk(r"""
      ${this._renderEndRestoreButton(e.fp.end_restore,"End & Restore Now",!1,$e("active"))}
    `}_renderBusyBody(e,t){return u`
"""),
     _blk(r"""
      ${this._renderEndRestoreButton(e.fp.end_restore,"End & Restore Now",!1,gt("active"))}
    `}_renderBusyBody(e,r){return p`
""")),
    (_blk(r"""
          ${this._renderTransitionDetail(e??"Free Power is mid-transaction.",t)}
"""),
     _blk(r"""
          ${this._renderTransitionDetail(e??"Free Power is mid-transaction.",r)}
""")),
    (_blk(r"""
    `}_renderDeferredBody(e,t){return u`
"""),
     _blk(r"""
    `}_renderDeferredBody(e,r){return p`
""")),
    (_blk(r"""
          ${this._renderTransitionDetail(e??"Modbus bus busy - the watchdog will retry.",t)}
"""),
     _blk(r"""
          ${this._renderTransitionDetail(e??"Modbus bus busy - the watchdog will retry.",r)}
""")),
    (_blk(r"""
    `}_renderAttentionBody(e){let t=ut({statusText:e.statusText,snapshotValid:e.snapshotValid});return u`
"""),
     _blk(r"""
    `}_renderAttentionBody(e){let r=yn({statusText:e.statusText,snapshotValid:e.snapshotValid});return p`
""")),
    (_blk(r"""
        ${t.explanation??"No automatic retry. Starting a new Free Power session is disabled until this clears."}
"""),
     _blk(r"""
        ${r.explanation??"No automatic retry. Starting a new Free Power session is disabled until this clears."}
""")),
    (_blk(r"""
      ${t.actionable?this._renderEndRestoreButton(e.fp.end_restore,t.actionLabel??"End & Restore Now",t.secondary,$e("recovery_attention")):h}
    `}_renderTransitionDetail(e,t){return u`
"""),
     _blk(r"""
      ${r.actionable?this._renderEndRestoreButton(e.fp.end_restore,r.actionLabel??"End & Restore Now",r.secondary,gt("recovery_attention")):m}
    `}_renderTransitionDetail(e,r){return p`
""")),
    (_blk(r"""
        @click=${()=>this._moreInfo(t)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(t))}}
"""),
     _blk(r"""
        @click=${()=>this._moreInfo(r)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(r))}}
""")),
    (_blk(r"""
    `}_renderStatusLine(e,t,i){return!(i?.alwaysShow||!!e&&e!=="Inactive")||!e?h:u`
"""),
     _blk(r"""
    `}_renderStatusLine(e,r,i){return!(i?.alwaysShow||!!e&&e!=="Inactive")||!e?m:p`
""")),
    (_blk(r"""
        @click=${()=>this._moreInfo(t)}
        @keydown=${s=>{(s.key==="Enter"||s.key===" ")&&(s.preventDefault(),this._moreInfo(t))}}
"""),
     _blk(r"""
        @click=${()=>this._moreInfo(r)}
        @keydown=${o=>{(o.key==="Enter"||o.key===" ")&&(o.preventDefault(),this._moreInfo(r))}}
""")),
    (_blk(r"""
    `}_renderDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
"""),
     _blk(r"""
    `}_renderDiagnosticsDetails(e){let r=[],i=(a,o)=>{let s=x(this._entityState(o));s!==null&&r.push({label:a,value:s.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),r.length===0?m:p`
""")),
    (_blk(r"""
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(e,t,i,n){let s=this._confirmEndRestore;return u`
"""),
     _blk(r"""
          ${r.map(a=>p`<span class="diagnostic-chip">${a.label}: ${a.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(e,r,i,a){let o=this._confirmEndRestore;return p`
""")),
    (_blk(r"""
        class="end-restore-button ${i?"secondary":""} ${s?"confirming":""}"
        ?disabled=${!n}
"""),
     _blk(r"""
        class="end-restore-button ${i?"secondary":""} ${o?"confirming":""}"
        ?disabled=${!a}
""")),
    (_blk(r"""
        ${s?"Tap again to End & Restore":t}
        ${s?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
"""),
     _blk(r"""
        ${o?"Tap again to End & Restore":r}
        ${o?p`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:m}
""")),
    (_blk(r"""
    `}_handleEndRestoreClick(e){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},le);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:e})}_toggleArm(e,t){this._callService("switch",t?"turn_off":"turn_on",{entity_id:e})}_commitNumber(e,t,i){e==="power"?this._pendingPower=t:this._pendingDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_commitDumpNumber(e,t,i){e==="power"?this._pendingDumpPower=t:e==="stop_soc"?this._pendingDumpStopSoc=t:this._pendingDumpDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_handleEndDumpClick(e){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},le);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:e})}_numericAttr(e,t){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"){let i=f(e);if(i!==null)return i}return t}_formatClock(e){let t=e.getHours().toString().padStart(2,"0"),i=e.getMinutes().toString().padStart(2,"0");return`${t}:${i}`}_renderNumberControl(e){let t=e.entity?.attributes??{},i=this._numericAttr(t.min,e.fallbackMin),n=e.maxOverride??this._numericAttr(t.max,e.fallbackMax),s=this._numericAttr(t.step,e.fallbackStep),o=e.value??i,l=e.disabled??!e.entity,d=n>i?Math.max(0,Math.min(100,(o-i)/(n-i)*100)):0;return u`
"""),
     _blk(r"""
    `}_handleEndRestoreClick(e){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},et);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:e})}_toggleArm(e,r){this._callService("switch",r?"turn_off":"turn_on",{entity_id:e})}_commitNumber(e,r,i){e==="power"?this._pendingPower=r:this._pendingDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_commitDumpNumber(e,r,i){e==="power"?this._pendingDumpPower=r:e==="stop_soc"?this._pendingDumpStopSoc=r:this._pendingDumpDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_handleEndDumpClick(e){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},et);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:e})}_numericAttr(e,r){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"){let i=x(e);if(i!==null)return i}return r}_formatClock(e){let r=e.getHours().toString().padStart(2,"0"),i=e.getMinutes().toString().padStart(2,"0");return`${r}:${i}`}_renderNumberControl(e){let r=e.entity?.attributes??{},i=this._numericAttr(r.min,e.fallbackMin),a=e.maxOverride??this._numericAttr(r.max,e.fallbackMax),o=this._numericAttr(r.step,e.fallbackStep),s=e.value??i,l=e.disabled??!e.entity,u=a>i?Math.max(0,Math.min(100,(s-i)/(a-i)*100)):0;return p`
""")),
    (_blk(r"""
          <span class="number-control-value">${e.formatValue(o)}</span>
"""),
     _blk(r"""
          <span class="number-control-value">${e.formatValue(s)}</span>
""")),
    (_blk(r"""
          style="--eaa-slider-fill:${d}%"
"""),
     _blk(r"""
          style="--eaa-slider-fill:${u}%"
""")),
    (_blk(r"""
          max=${n}
          step=${s}
          .value=${String(o)}
"""),
     _blk(r"""
          max=${a}
          step=${o}
          .value=${String(s)}
""")),
    (_blk(r"""
          @input=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onPreview(p)}}
          @change=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onCommit(p)}}
"""),
     _blk(r"""
          @input=${c=>{let d=Number(c.target.value);Number.isFinite(d)&&e.onPreview(d)}}
          @change=${c=>{let d=Number(c.target.value);Number.isFinite(d)&&e.onCommit(d)}}
""")),
    (_blk(r"""
    `}_renderDumpToGridTile(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return this._renderDumpToGridLockedShell();let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let d=e.schedule,c=d?m(this._entityState(d.armed)):null,p=De(l,c),y=this._freePowerVisualStateForInterlock(),_=K(l,y),w=_?"interlocked":p,k=_?Te("Free Power",y):void 0,$=this._entity(e.export_power),D=this._entity(e.stop_soc),b=this._entity(e.duration),U=this._pendingDumpPower??f($?.state),S=this._pendingDumpStopSoc??f(D?.state),de=this._pendingDumpDuration??f(b?.state),ce=this._dumpIconFor(w),xt=Ee(w);return u`
      <div class="tile dump-to-grid-tile state-${w}">
"""),
     _blk(r"""
    `}_renderDumpToGridTile(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return this._renderDumpToGridLockedShell();let r=y(this._entityState(e.active)),i=y(this._entityState(e.write_enable)),a=y(this._entityState(e.operation_in_progress)),o=y(this._entityState(e.snapshot_valid)),s=this._entityState(e.status),l=Xe({active:r,armed:i,operationInProgress:a,snapshotValid:o,statusText:s});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let u=e.schedule,c=u?y(this._entityState(u.armed)):null,d=bt(l,c),b=this._freePowerVisualStateForInterlock(),v=Ce(l,b),g=v?"interlocked":d,P=v?_t("Free Power",b):void 0,E=this._entity(e.export_power),O=this._entity(e.stop_soc),_=this._entity(e.duration),T=this._pendingDumpPower??x(E?.state),N=this._pendingDumpStopSoc??x(O?.state),le=this._pendingDumpDuration??x(_?.state),f=this._dumpIconFor(g),w=vt(g);return p`
      <div class="tile dump-to-grid-tile state-${g}">
""")),
    (_blk(r"""
            <ha-icon class="tile-icon" icon=${ce}></ha-icon>
"""),
     _blk(r"""
            <ha-icon class="tile-icon" icon=${f}></ha-icon>
""")),
    (_blk(r"""
          <span class="state-pill state-${w}">${xt}</span>
"""),
     _blk(r"""
          <span class="state-pill state-${g}">${w}</span>
""")),
    (_blk(r"""
          ${d&&c===!0?this._renderDumpScheduleBanner(d):h}
          ${_?this._renderInterlockBanner(k):h}
"""),
     _blk(r"""
          ${u&&c===!0?this._renderDumpScheduleBanner(u):m}
          ${v?this._renderInterlockBanner(P):m}
""")),
    (_blk(r"""
          ${this._renderDumpBody(l,{dump:e,statusText:o,snapshotValid:s,interlocked:_,stagedPowerW:U,stagedStopSoc:S,stagedDurationMin:de,stagedPowerEntity:$,stagedStopSocEntity:D,stagedDurationEntity:b})}
"""),
     _blk(r"""
          ${this._renderDumpBody(l,{dump:e,statusText:s,snapshotValid:o,interlocked:v,stagedPowerW:T,stagedStopSoc:N,stagedDurationMin:le,stagedPowerEntity:E,stagedStopSocEntity:O,stagedDurationEntity:_})}
""")),
    (_blk(r"""
    `}_renderDumpToGridLockedShell(){return u`
"""),
     _blk(r"""
    `}_renderDumpToGridLockedShell(){return p`
""")),
    (_blk(r"""
    `}_dumpIconFor(e){switch(e){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(e){return u`
"""),
     _blk(r"""
    `}_dumpIconFor(e){switch(e){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(e){return p`
""")),
    (_blk(r"""
    `}_renderDumpBody(e,t){switch(e){case"active":return this._renderDumpActiveBody(t);case"busy":return this._renderBusyBody(t.statusText??"Dump to Grid is mid-transaction.",t.dump.status);case"deferred":return this._renderDumpDeferredBody(t);case"recovery_attention":return this._renderDumpAttentionBody(t);default:return this._renderDumpReadyOrArmedBody(e,t)}}_renderDumpReadyOrArmedBody(e,t){let i=t.dump.schedule,n=i?this._dumpMode:"now";return u`
      ${i?this._renderDumpModeSelector():h}
      ${n==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(e,t)}
      ${this._renderDumpLastEndReason(t.dump)}
    `}_renderDumpModeSelector(){let e=this._dumpMode==="now";return u`
"""),
     _blk(r"""
    `}_renderDumpBody(e,r){switch(e){case"active":return this._renderDumpActiveBody(r);case"busy":return this._renderBusyBody(r.statusText??"Dump to Grid is mid-transaction.",r.dump.status);case"deferred":return this._renderDumpDeferredBody(r);case"recovery_attention":return this._renderDumpAttentionBody(r);default:return this._renderDumpReadyOrArmedBody(e,r)}}_renderDumpReadyOrArmedBody(e,r){let i=r.dump.schedule,a=i?this._dumpMode:"now";return p`
      ${i?this._renderDumpModeSelector():m}
      ${a==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(e,r)}
      ${this._renderDumpLastEndReason(r.dump)}
    `}_renderDumpModeSelector(){let e=this._dumpMode==="now";return p`
""")),
    (_blk(r"""
    `}_renderDumpNowPanel(e,t){let i=e==="armed",n=Q(st(e),t.interlocked),s=Q(ot(e),t.interlocked);return u`
"""),
     _blk(r"""
    `}_renderDumpNowPanel(e,r){let i=e==="armed",a=Ne(gn(e),r.interlocked),o=Ne(bn(e),r.interlocked);return p`
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingDumpPower=o,onCommit:o=>this._commitDumpNumber("power",o,t.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:t.stagedStopSocEntity,value:t.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:t.interlocked,onPreview:o=>this._pendingDumpStopSoc=o,onCommit:o=>this._commitDumpNumber("stop_soc",o,t.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDumpDuration=o,onCommit:o=>this._commitDumpNumber("duration",o,t.dump.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:J,disabled:r.interlocked,onPreview:s=>this._pendingDumpPower=s,onCommit:s=>this._commitDumpNumber("power",s,r.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:r.stagedStopSocEntity,value:r.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:r.interlocked,onPreview:s=>this._pendingDumpStopSoc=s,onCommit:s=>this._commitDumpNumber("stop_soc",s,r.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:r.interlocked,onPreview:s=>this._pendingDumpDuration=s,onCommit:s=>this._commitDumpNumber("duration",s,r.dump.duration)})}
""")),
    (_blk(r"""
      ${this._renderStatusLine(t.statusText,t.dump.status)}
"""),
     _blk(r"""
      ${this._renderStatusLine(r.statusText,r.dump.status)}
""")),
    (_blk(r"""
          ?disabled=${!s}
          @click=${()=>this._toggleArm(t.dump.write_enable,i)}
"""),
     _blk(r"""
          ?disabled=${!o}
          @click=${()=>this._toggleArm(r.dump.write_enable,i)}
""")),
    (_blk(r"""
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.dump.start})}
"""),
     _blk(r"""
          ?disabled=${!a}
          @click=${()=>this._pressDumpStart(r.dump)}
""")),
    (_blk(r"""
    `}_renderDumpLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.stop_soc),c=this._entityState(e.last_result),p=this._pendingDumpScheduleDuration??f(o?.state),y=this._pendingDumpSchedulePower??f(l?.state),_=this._pendingDumpScheduleStopSoc??f(d?.state),w=Pe(c)||!!c&&/^FAILED/i.test(c.trim()),k=Ce(c),$=!!l&&!!o&&!!d&&t!==null,D=$&&!i&&s!==null&&s.getTime()>this._nowMs;return u`
"""),
     _blk(r"""
    `}_renderDumpLaterPanel(e){let r=y(this._entityState(e.armed)),i=Et(r),a=this._entityState(e.start),o=me(a),s=this._entity(e.duration),l=this._entity(e.power),u=this._entity(e.stop_soc),c=this._entityState(e.last_result),d=this._pendingDumpScheduleDuration??x(s?.state),b=this._pendingDumpSchedulePower??x(l?.state),v=this._pendingDumpScheduleStopSoc??x(u?.state),g=xt(c)||!!c&&/^FAILED/i.test(c.trim()),P=St(c),E=!!l&&!!s&&!!u&&r!==null,O=E&&!i&&o!==null&&o.getTime()>this._nowMs;return p`
""")),
    (_blk(r"""
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${b=>this._handleScheduleStartChange(e.start,b.target.value)}
"""),
     _blk(r"""
          .value=${o?this._toDatetimeLocalValue(o):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${_=>this._handleScheduleStartChange(e.start,_.target.value)}
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:i||!l,onPreview:b=>this._pendingDumpSchedulePower=b,onCommit:b=>this._commitDumpScheduleNumber("power",b,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:d,value:_,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:i||!d,onPreview:b=>this._pendingDumpScheduleStopSoc=b,onCommit:b=>this._commitDumpScheduleNumber("stop_soc",b,e.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:b=>this._pendingDumpScheduleDuration=b,onCommit:b=>this._commitDumpScheduleNumber("duration",b,e.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:b,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:J,disabled:i||!l,onPreview:_=>this._pendingDumpSchedulePower=_,onCommit:_=>this._commitDumpScheduleNumber("power",_,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:u,value:v,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:i||!u,onPreview:_=>this._pendingDumpScheduleStopSoc=_,onCommit:_=>this._commitDumpScheduleNumber("stop_soc",_,e.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:d,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:i||!s,onPreview:_=>this._pendingDumpScheduleDuration=_,onCommit:_=>this._commitDumpScheduleNumber("duration",_,e.duration)})}
""")),
    (_blk(r"""
      ${$?h:u`<p class="firmware-note is-warning">
"""),
     _blk(r"""
      ${E?m:p`<p class="firmware-note is-warning">
""")),
    (_blk(r"""
      ${c?u`<p class="firmware-note ${w||k?"is-warning":""}">${c}</p>`:h}
"""),
     _blk(r"""
      ${c?p`<p class="firmware-note ${g||P?"is-warning":""}">${c}</p>`:m}
""")),
    (_blk(r"""
          ?disabled=${!D}
          @click=${()=>this._callServiceObj(Me(e.armed))}
"""),
     _blk(r"""
          ?disabled=${!O}
          @click=${()=>this._callServiceObj(Mt(e.armed))}
""")),
    (_blk(r"""
    `}_renderDumpScheduleBanner(e){let t=M(this._entityState(e.start)),i=f(this._entityState(e.duration)),n=f(this._entityState(e.power)),s=f(this._entityState(e.stop_soc)),o=t?J(t.getTime(),this._nowMs):null;return u`
"""),
     _blk(r"""
    `}_renderDumpScheduleBanner(e){let r=me(this._entityState(e.start)),i=x(this._entityState(e.duration)),a=x(this._entityState(e.power)),o=x(this._entityState(e.stop_soc)),s=r?Ie(r.getTime(),this._nowMs):null;return p`
""")),
    (_blk(r"""
            ${t?Ve(t):"--"} • ${T(n)} • stop
            ${L(s)} • ${F(i)}
"""),
     _blk(r"""
            ${r?Dt(r):"--"} • ${J(a)} • stop
            ${we(o)} • ${fe(i)}
""")),
    (_blk(r"""
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Fe(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_commitDumpScheduleNumber(e,t,i){e==="power"?this._pendingDumpSchedulePower=t:e==="stop_soc"?this._pendingDumpScheduleStopSoc=t:this._pendingDumpScheduleDuration=t,this._callServiceObj(Ie(i,t))}_renderDumpLastEndReason(e){let t=this._entityState(e.last_end_reason);return!t||t==="unknown"||t==="unavailable"?h:u`<p class="firmware-note">Last lease ended: ${t}</p>`}_renderDumpActiveBody(e){let t=this._entityState(e.dump.ends_at),i=M(t),n=i?J(i.getTime(),this._nowMs):null,s=f(this._entityState(e.dump.battery_soc)),o=lt(f(this._entityState(e.dump.active_export_power)),e.statusText),l=dt(f(this._entityState(e.dump.active_stop_soc)),e.statusText);return u`
"""),
     _blk(r"""
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pt(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_commitDumpScheduleNumber(e,r,i){e==="power"?this._pendingDumpSchedulePower=r:e==="stop_soc"?this._pendingDumpScheduleStopSoc=r:this._pendingDumpScheduleDuration=r,this._callServiceObj(Rt(i,r))}_renderDumpLastEndReason(e){let r=this._entityState(e.last_end_reason);return!r||r==="unknown"||r==="unavailable"?m:p`<p class="firmware-note">Last lease ended: ${r}</p>`}_renderDumpActiveBody(e){let r=this._entityState(e.dump.ends_at),i=me(r),a=i?Ie(i.getTime(),this._nowMs):null,o=x(this._entityState(e.dump.battery_soc)),s=vn(x(this._entityState(e.dump.active_export_power)),e.statusText),l=_n(x(this._entityState(e.dump.active_stop_soc)),e.statusText);return p`
""")),
    (_blk(r"""
        <div class="active-hero-time">${n??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${T(o)} export • ends ${i?this._formatClock(i):t??"--"}
"""),
     _blk(r"""
        <div class="active-hero-time">${a??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${J(s)} export • ends ${i?this._formatClock(i):r??"--"}
""")),
    (_blk(r"""
        Battery: ${L(s)} • stops at ${L(l)}
"""),
     _blk(r"""
        Battery: ${we(o)} • stops at ${we(l)}
""")),
    (_blk(r"""
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("active"))}
    `}_renderDumpDeferredBody(e){return u`
"""),
     _blk(r"""
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",Qe("active"))}
    `}_renderDumpDeferredBody(e){return p`
""")),
    (_blk(r"""
      ${e.snapshotValid===!0?this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("deferred")):h}
    `}_renderDumpAttentionBody(e){let i=!!e.dump.recovery_arm&&!!e.dump.recovery_force_restore&&!!e.dump.recovery_accept&&ct(e.statusText,e.snapshotValid);return u`
"""),
     _blk(r"""
      ${e.snapshotValid===!0?this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",Qe("deferred")):m}
    `}_renderDumpAttentionBody(e){let i=!!e.dump.recovery_arm&&!!e.dump.recovery_force_restore&&!!e.dump.recovery_accept&&wn(e.statusText,e.snapshotValid);return p`
""")),
    (_blk(r"""
      ${i?this._renderDumpRecoveryPanel(e.dump):h}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(e){let t=m(this._entityState(e.recovery_arm))===!0,i=this._entityState(e.recovery_state);return u`
"""),
     _blk(r"""
      ${i?this._renderDumpRecoveryPanel(e.dump):m}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",Qe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(e){let r=y(this._entityState(e.recovery_arm))===!0,i=this._entityState(e.recovery_state);return p`
""")),
    (_blk(r"""
        ${i&&i!=="unknown"&&i!=="unavailable"?u`<p class="firmware-note">${i}</p>`:h}
"""),
     _blk(r"""
        ${i&&i!=="unknown"&&i!=="unavailable"?p`<p class="firmware-note">${i}</p>`:m}
""")),
    (_blk(r"""
            class="arm-toggle ${t?"is-armed":""}"
            @click=${()=>this._toggleArm(e.recovery_arm,t)}
"""),
     _blk(r"""
            class="arm-toggle ${r?"is-armed":""}"
            @click=${()=>this._toggleArm(e.recovery_arm,r)}
""")),
    (_blk(r"""
            <ha-icon icon=${t?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
            ${t?"Disarm Recovery":"Arm Recovery"}
"""),
     _blk(r"""
            <ha-icon icon=${r?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
            ${r?"Disarm Recovery":"Arm Recovery"}
""")),
    (_blk(r"""
            class="start-button"
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_force_restore})}
"""),
     _blk(r"""
            class="start-button"
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_force_restore})}
""")),
    (_blk(r"""
            class="arm-toggle"
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_accept})}
"""),
     _blk(r"""
            class="arm-toggle"
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_accept})}
""")),
    (_blk(r"""
    `}_renderDumpDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
"""),
     _blk(r"""
    `}_renderDumpDiagnosticsDetails(e){let r=[],i=(a,o)=>{let s=x(this._entityState(o));s!==null&&r.push({label:a,value:s.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),r.length===0?m:p`
""")),
    (_blk(r"""
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(e,t,i){let n=this._confirmEndDump;return u`
"""),
     _blk(r"""
          ${r.map(a=>p`<span class="diagnostic-chip">${a.label}: ${a.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(e,r,i){let a=this._confirmEndDump;return p`
""")),
    (_blk(r"""
        class="end-restore-button ${n?"confirming":""}"
"""),
     _blk(r"""
        class="end-restore-button ${a?"confirming":""}"
""")),
    (_blk(r"""
        ${n?"Tap again to End & Restore":t}
        ${n?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
"""),
     _blk(r"""
        ${a?"Tap again to End & Restore":r}
        ${a?p`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:m}
""")),
    (_blk(r"""
    `}};g.styles=pe`
"""),
     _blk(r"""
    `}};M.styles=[sr,mr,ce`
""")),
    (_blk(r"""
  `,v([ie({attribute:!1})],g.prototype,"hass",2),v([x()],g.prototype,"_config",2),v([x()],g.prototype,"_pendingPower",2),v([x()],g.prototype,"_pendingDuration",2),v([x()],g.prototype,"_pendingSchedulePower",2),v([x()],g.prototype,"_pendingScheduleDuration",2),v([x()],g.prototype,"_confirmEndRestore",2),v([x()],g.prototype,"_pendingDumpPower",2),v([x()],g.prototype,"_pendingDumpStopSoc",2),v([x()],g.prototype,"_pendingDumpDuration",2),v([x()],g.prototype,"_confirmEndDump",2),v([x()],g.prototype,"_dumpMode",2),v([x()],g.prototype,"_pendingDumpSchedulePower",2),v([x()],g.prototype,"_pendingDumpScheduleStopSoc",2),v([x()],g.prototype,"_pendingDumpScheduleDuration",2),v([x()],g.prototype,"_nowMs",2),v([x()],g.prototype,"_mode",2),v([x()],g.prototype,"_track",2),g=v([rt("ecco-energy-actions-card")],g);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{g as EccoEnergyActionsCard};
"""),
     _blk(r"""
  `],D([ze({attribute:!1})],M.prototype,"hass",2),D([I()],M.prototype,"_config",2),D([I()],M.prototype,"_pendingPower",2),D([I()],M.prototype,"_pendingDuration",2),D([I()],M.prototype,"_pendingSchedulePower",2),D([I()],M.prototype,"_pendingScheduleDuration",2),D([I()],M.prototype,"_confirmEndRestore",2),D([I()],M.prototype,"_pendingDumpPower",2),D([I()],M.prototype,"_pendingDumpStopSoc",2),D([I()],M.prototype,"_pendingDumpDuration",2),D([I()],M.prototype,"_confirmEndDump",2),D([I()],M.prototype,"_dumpMode",2),D([I()],M.prototype,"_pendingDumpSchedulePower",2),D([I()],M.prototype,"_pendingDumpScheduleStopSoc",2),D([I()],M.prototype,"_pendingDumpScheduleDuration",2),D([I()],M.prototype,"_nowMs",2),D([I()],M.prototype,"_mode",2),D([I()],M.prototype,"_track",2),M=D([pn("ecco-energy-actions-card")],M);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{M as EccoEnergyActionsCard};
""")),
)


def pre_epc2_bundle(text: str) -> str:
    """frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js with exactly epc2's edits undone (a reverter of chain entry epc2, PEX): its text as of the entry before."""
    return _revert(text, DIST_EDITS, DIST_REL)


pre_epc2_bundle.edits = DIST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc2_bundle(text: str) -> str:
    """Applies epc2's edits to frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js as of the entry before (the round trip)."""
    return _apply(text, DIST_EDITS, DIST_REL)


# ---- (PEX frozen edit) the scheduled Dump to Grid package --------------------------------------------------------
DUMP_REL = 'home-assistant/packages/ecco_dump_to_grid_schedule.yaml'
DUMP_EDITS = (
    (_blk(r"""
#     persistent notification for every failure or miss; the write enable always ends off.

"""),
     _blk(r"""
#     persistent notification for every failure or miss; the write enable always ends off.
#
# PLAN (stage 3, home-assistant/packages/ecco_plan_helpers.yaml, which must be installed with or before this file): the start also
# refuses, with its own BLOCKED result text (the end-of-run alert below raises the persistent notification) and with nothing
# staged or pressed,
#   - while a Hold battery, Skip tonight or Prepare for power cut is active (sensor.ecco_plan_export_hold reads held), and while that
#     cannot be read (unknown, unavailable or the entity missing: it fails closed);
#   - while the effective reserve (sensor.ecco_plan_effective_reserve: the larger of the owner's reserve and a running power-cut reserve)
#     cannot be read, or leaves no room under the 90 % Stop SOC limit;
# and it raises the Stop SOC it stages to at least the effective reserve (rounded up), never lowers it. The scheduled start is the
# trusted backend: the dashboard and the card are not what keeps an override.

""")),
    (_blk(r"""
          requested_stop_soc: "{{ stop_soc | int(25) }}"
"""),
     _blk(r"""
          # The plan's hold and reserve, read once at the start of the run (a later change ends the NEXT start, not this one).
          plan_hold: "{{ states('sensor.ecco_plan_export_hold') }}"
          plan_reserve: "{{ states('sensor.ecco_plan_effective_reserve') | float(-1) }}"
          requested_stop_soc_raw: "{{ stop_soc | int(25) }}"
          # Raise-only: at least the effective reserve, rounded up; never below what the owner asked for.
          requested_stop_soc: "{{ [stop_soc | int(25), (plan_reserve | round(0, 'ceil') | int) if plan_reserve >= 0 else 0] | max }}"
""")),
    (_blk(r"""
          run_started: "{{ as_timestamp(now()) }}"
      - choose:
          - conditions:
              - condition: template
"""),
     _blk(r"""
          run_started: "{{ as_timestamp(now()) }}"
      - choose:
          # PLAN: an active Hold battery / Skip tonight / Prepare for power cut holds the start. (The alert at the end of this script
          # already raises one persistent notification, with this text, for every BLOCKED result.)
          - conditions:
              - condition: template
                value_template: "{{ plan_hold == 'held' }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: >-
                    BLOCKED - a Hold battery, Skip tonight or Prepare for power cut is active ({{ state_attr('sensor.ecco_plan_export_hold', 'held_by') }});
                    nothing started (reason OVERRIDE_ACTIVE). Cancel it on the Energy Actions card to allow this start.
          # PLAN: the override records cannot be read (or the plan helper package is not installed): fail closed.
          - conditions:
              - condition: template
                value_template: "{{ plan_hold != 'clear' }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: >-
                    BLOCKED - the plan override records cannot be read ({{ plan_hold }}); nothing started (reason OVERRIDE_UNREADABLE).
                    Check that the ECCO plan helper package is installed and its helpers are available.
          # PLAN: no known effective reserve: fail closed.
          - conditions:
              - condition: template
                value_template: "{{ plan_reserve < 0 }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: "BLOCKED - the effective reserve cannot be read; nothing started (reason RESERVE_UNKNOWN)"
          # PLAN: the reserve the Stop SOC must respect leaves no room under the 90 % limit.
          - conditions:
              - condition: template
                value_template: "{{ (requested_stop_soc | int(0)) > 90 and (requested_stop_soc_raw | int(0)) <= 90 }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: "BLOCKED - the effective reserve ({{ plan_reserve | round(0) | int }}%) leaves no room under the 90% Stop SOC limit; nothing started (reason RESERVE_TOO_HIGH)"
          - conditions:
              - condition: template
""")),
    (_blk(r"""
                STARTING - {{ requested_power }}W, Stop SOC {{ requested_stop_soc }}%, until
"""),
     _blk(r"""
                STARTING - {{ requested_power }}W, Stop SOC {{ requested_stop_soc }}%{{ ' (raised from ' ~ requested_stop_soc_raw ~ '% to the effective reserve)' if (requested_stop_soc | int(0)) > (requested_stop_soc_raw | int(0)) else '' }}, until
""")),
)


def pre_epc2_dump_schedule(text: str) -> str:
    """home-assistant/packages/ecco_dump_to_grid_schedule.yaml with exactly epc2's edits undone (a reverter of chain entry epc2, PEX): its text as of the entry before."""
    return _revert(text, DUMP_EDITS, DUMP_REL)


pre_epc2_dump_schedule.edits = DUMP_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc2_dump_schedule(text: str) -> str:
    """Applies epc2's edits to home-assistant/packages/ecco_dump_to_grid_schedule.yaml as of the entry before (the round trip)."""
    return _apply(text, DUMP_EDITS, DUMP_REL)


# ---- (chain-pinned edit) deployment/ha-manifest.yaml -------------------------------------------------------------
MANIFEST_REL = 'deployment/ha-manifest.yaml'
MANIFEST_EDITS = (
    (_blk(r"""

dashboard:
"""),
     _blk(r"""

  # ECCO plan overrides - epc2 (stage 3 of the two-master-card energy-control work; NOT installed, NOT live-proven). The plan helper
  # package: the owner's limits, the plan revision, the override records, the two guarded scripts (the only writers of the records;
  # they never call a charge, discharge, TOU, inverter or dongle service) and the export-hold / effective-reserve sensors. Install it
  # BEFORE the guarded start below and BEFORE the changed ecco_dump_to_grid_schedule.yaml: both refuse every start while these
  # sensors cannot be read. The first Home Assistant start writes the owner's accepted limits once; the confirmation switch stays off.
  - source: home-assistant/packages/ecco_plan_helpers.yaml
    destination: /config/packages/ecco_plan_helpers.yaml
    method: ssh_file_copy
    restart_required: true
  # The guarded manual Dump to Grid start the Energy Actions card calls when it is configured with dump_to_grid.guarded_start. It
  # presses the same dongle start button, but only while no override holds export and the staged Stop SOC is at least the effective
  # reserve. Needs ecco_plan_helpers.yaml installed first.
  - source: home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml
    destination: /config/packages/ecco_dump_to_grid_guarded_start.yaml
    method: ssh_file_copy
    restart_required: true

dashboard:
""")),
)


def pre_epc2_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly epc2's edits undone (a reverter of chain entry epc2, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_epc2_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc2_manifest(text: str) -> str:
    """Applies epc2's edits to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The frozen files this entry edits, with their reverters (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    README_REL: pre_epc2_readme,
    CONFIG_REL: pre_epc2_config,
    SRC_REL: pre_epc2_card,
    DIST_REL: pre_epc2_bundle,
    DUMP_REL: pre_epc2_dump_schedule,
}
# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_epc2_manifest,
}
