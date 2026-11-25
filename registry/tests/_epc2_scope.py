"""epc2 (stage 3 of the two-master-card energy-control work: guarded overrides and their enforcement; offline, nothing installed). FROZEN
edits (PEX): the card's README.md, src/config.ts, src/ecco-energy-actions-card.ts and rebuilt dist/ecco-energy-actions-card.js (the
bundle had not been rebuilt since the export; the rebuild carries every source change since), and the scheduled Dump to Grid package
(refuses during Hold battery / Skip tonight / Prepare for power cut, fails closed, raises the Stop SOC to the effective reserve).
CHAIN-PINNED edit: the deployment manifest (two package stanzas, and a comment block above the changed scheduled Dump to Grid package stanza: the helper
dependency and the active-override warning; the guarded start's stanza also states the unresolved Start-button limitation). ADDED: the plan helper package and the guarded start package, their
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
    'frontend/ecco-energy-actions-card/test/planEpochCancel.test.ts',
    'frontend/ecco-energy-actions-card/test/support/controlsProbe.ts',
    'frontend/ecco-energy-actions-card/test/support/mutantCard.ts',
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
override holds back ECCO's own scheduled and guarded export starts; it does not stop the battery charging or discharging and it does not
stop the dongle's own Start button. Prepare for power cut also sets the reserve ECCO's plan uses (the larger of your own reserve and the
power-cut reserve, each rounded up). It does not change the inverter's own reserve or any inverter setting, does not stop the house using
the battery, and never charges. Prepare for power cut with the battery below that reserve says so ("... Nothing is charging. Use Charge
Battery if you want it filled.") and offers nothing automatic. Without the plan helpers nothing is added (the golden renders are unchanged).
What is not enforced and what is not proven is listed in `frontend/ecco-plan-core/README.md`, "Known limitations (stated, not fixed in this change)".

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
# 19 Nov 2026 (owner decision r15: the card offers the guarded Cancel for an override the backend holds only through its epoch record or cannot read, and reads back both records):
# the pairs are re-derived from the epc1 state to the rebuilt bundle (the minified bundle renames names across the whole file when any source changes); the bundle checkpoint is re-stated in _scope_chain.py.
DIST_EDITS = (
    (_blk(r"""
var St=Object.defineProperty;var kt=Object.getOwnPropertyDescriptor;var v=(a,r,e,t)=>{for(var i=t>1?void 0:t?kt(r,e):r,n=a.length-1,s;n>=0;n--)(s=a[n])&&(i=(t?s(r,e,i):s(i))||i);return t&&i&&St(r,e,i),i};var Z=globalThis,X=Z.ShadowRoot&&(Z.ShadyCSS===void 0||Z.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,ue=Symbol(),Le=new WeakMap,B=class{constructor(r,e,t){if(this._$cssResult$=!0,t!==ue)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=r,this.t=e}get styleSheet(){let r=this.o,e=this.t;if(X&&r===void 0){let t=e!==void 0&&e.length===1;t&&(r=Le.get(e)),r===void 0&&((this.o=r=new CSSStyleSheet).replaceSync(this.cssText),t&&Le.set(e,r))}return r}toString(){return this.cssText}},Ue=a=>new B(typeof a=="string"?a:a+"",void 0,ue),pe=(a,...r)=>{let e=a.length===1?a[0]:r.reduce((t,i,n)=>t+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+a[n+1],a[0]);return new B(e,a,ue)},Be=(a,r)=>{if(X)a.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of r){let t=document.createElement("style"),i=Z.litNonce;i!==void 0&&t.setAttribute("nonce",i),t.textContent=e.cssText,a.appendChild(t)}},he=X?a=>a:a=>a instanceof CSSStyleSheet?(r=>{let e="";for(let t of r.cssRules)e+=t.cssText;return Ue(e)})(a):a;var{is:$t,defineProperty:Dt,getOwnPropertyDescriptor:Et,getOwnPropertyNames:Tt,getOwnPropertySymbols:At,getPrototypeOf:Rt}=Object,ee=globalThis,He=ee.trustedTypes,Pt=He?He.emptyScript:"",Ct=ee.reactiveElementPolyfillSupport,H=(a,r)=>a,z={toAttribute(a,r){switch(r){case Boolean:a=a?Pt:null;break;case Object:case Array:a=a==null?a:JSON.stringify(a)}return a},fromAttribute(a,r){let e=a;switch(r){case Boolean:e=a!==null;break;case Number:e=a===null?null:Number(a);break;case Object:case Array:try{e=JSON.parse(a)}catch{e=null}}return e}},te=(a,r)=>!$t(a,r),ze={attribute:!0,type:String,converter:z,reflect:!1,useDefault:!1,hasChanged:te};Symbol.metadata??=Symbol("metadata"),ee.litPropertyMetadata??=new WeakMap;var E=class extends HTMLElement{static addInitializer(r){this._$Ei(),(this.l??=[]).push(r)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(r,e=ze){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(r)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(r,e),!e.noAccessor){let t=Symbol(),i=this.getPropertyDescriptor(r,t,e);i!==void 0&&Dt(this.prototype,r,i)}}static getPropertyDescriptor(r,e,t){let{get:i,set:n}=Et(this.prototype,r)??{get(){return this[e]},set(s){this[e]=s}};return{get:i,set(s){let o=i?.call(this);n?.call(this,s),this.requestUpdate(r,o,t)},configurable:!0,enumerable:!0}}static getPropertyOptions(r){return this.elementProperties.get(r)??ze}static _$Ei(){if(this.hasOwnProperty(H("elementProperties")))return;let r=Rt(this);r.finalize(),r.l!==void 0&&(this.l=[...r.l]),this.elementProperties=new Map(r.elementProperties)}static finalize(){if(this.hasOwnProperty(H("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(H("properties"))){let e=this.properties,t=[...Tt(e),...At(e)];for(let i of t)this.createProperty(i,e[i])}let r=this[Symbol.metadata];if(r!==null){let e=litPropertyMetadata.get(r);if(e!==void 0)for(let[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(let[e,t]of this.elementProperties){let i=this._$Eu(e,t);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(r){let e=[];if(Array.isArray(r)){let t=new Set(r.flat(1/0).reverse());for(let i of t)e.unshift(he(i))}else r!==void 0&&e.push(he(r));return e}static _$Eu(r,e){let t=e.attribute;return t===!1?void 0:typeof t=="string"?t:typeof r=="string"?r.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(r=>this.enableUpdating=r),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(r=>r(this))}addController(r){(this._$EO??=new Set).add(r),this.renderRoot!==void 0&&this.isConnected&&r.hostConnected?.()}removeController(r){this._$EO?.delete(r)}_$E_(){let r=new Map,e=this.constructor.elementProperties;for(let t of e.keys())this.hasOwnProperty(t)&&(r.set(t,this[t]),delete this[t]);r.size>0&&(this._$Ep=r)}createRenderRoot(){let r=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Be(r,this.constructor.elementStyles),r}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(r=>r.hostConnected?.())}enableUpdating(r){}disconnectedCallback(){this._$EO?.forEach(r=>r.hostDisconnected?.())}attributeChangedCallback(r,e,t){this._$AK(r,t)}_$ET(r,e){let t=this.constructor.elementProperties.get(r),i=this.constructor._$Eu(r,t);if(i!==void 0&&t.reflect===!0){let n=(t.converter?.toAttribute!==void 0?t.converter:z).toAttribute(e,t.type);this._$Em=r,n==null?this.removeAttribute(i):this.setAttribute(i,n),this._$Em=null}}_$AK(r,e){let t=this.constructor,i=t._$Eh.get(r);if(i!==void 0&&this._$Em!==i){let n=t.getPropertyOptions(i),s=typeof n.converter=="function"?{fromAttribute:n.converter}:n.converter?.fromAttribute!==void 0?n.converter:z;this._$Em=i;let o=s.fromAttribute(e,n.type);this[i]=o??this._$Ej?.get(i)??o,this._$Em=null}}requestUpdate(r,e,t,i=!1,n){if(r!==void 0){let s=this.constructor;if(i===!1&&(n=this[r]),t??=s.getPropertyOptions(r),!((t.hasChanged??te)(n,e)||t.useDefault&&t.reflect&&n===this._$Ej?.get(r)&&!this.hasAttribute(s._$Eu(r,t))))return;this.C(r,e,t)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(r,e,{useDefault:t,reflect:i,wrapped:n},s){t&&!(this._$Ej??=new Map).has(r)&&(this._$Ej.set(r,s??e??this[r]),n!==!0||s!==void 0)||(this._$AL.has(r)||(this.hasUpdated||t||(e=void 0),this._$AL.set(r,e)),i===!0&&this._$Em!==r&&(this._$Eq??=new Set).add(r))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let r=this.scheduleUpdate();return r!=null&&await r,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,n]of this._$Ep)this[i]=n;this._$Ep=void 0}let t=this.constructor.elementProperties;if(t.size>0)for(let[i,n]of t){let{wrapped:s}=n,o=this[i];s!==!0||this._$AL.has(i)||o===void 0||this.C(i,void 0,n,o)}}let r=!1,e=this._$AL;try{r=this.shouldUpdate(e),r?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(t){throw r=!1,this._$EM(),t}r&&this._$AE(e)}willUpdate(r){}_$AE(r){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(r)),this.updated(r)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(r){return!0}update(r){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(r){}firstUpdated(r){}};E.elementStyles=[],E.shadowRootOptions={mode:"open"},E[H("elementProperties")]=new Map,E[H("finalized")]=new Map,Ct?.({ReactiveElement:E}),(ee.reactiveElementVersions??=[]).push("2.1.2");var ye=globalThis,We=a=>a,re=ye.trustedTypes,Ge=re?re.createPolicy("lit-html",{createHTML:a=>a}):void 0,Je="$lit$",A=`lit$${Math.random().toFixed(9).slice(2)}$`,Ze="?"+A,Nt=`<${Ze}>`,N=document,G=()=>N.createComment(""),j=a=>a===null||typeof a!="object"&&typeof a!="function",we=Array.isArray,Ot=a=>we(a)||typeof a?.[Symbol.iterator]=="function",me=`[ 	
\f\r]`,W=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,je=/-->/g,qe=/>/g,P=RegExp(`>|${me}(?:([^\\s"'>=/]+)(${me}*=${me}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Ye=/'/g,Ke=/"/g,Xe=/^(?:script|style|textarea|title)$/i,xe=a=>(r,...e)=>({_$litType$:a,strings:r,values:e}),u=xe(1),_r=xe(2),gr=xe(3),O=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),Qe=new WeakMap,C=N.createTreeWalker(N,129);function et(a,r){if(!we(a)||!a.hasOwnProperty("raw"))throw Error("invalid template strings array");return Ge!==void 0?Ge.createHTML(r):r}var Mt=(a,r)=>{let e=a.length-1,t=[],i,n=r===2?"<svg>":r===3?"<math>":"",s=W;for(let o=0;o<e;o++){let l=a[o],d,c,p=-1,y=0;for(;y<l.length&&(s.lastIndex=y,c=s.exec(l),c!==null);)y=s.lastIndex,s===W?c[1]==="!--"?s=je:c[1]!==void 0?s=qe:c[2]!==void 0?(Xe.test(c[2])&&(i=RegExp("</"+c[2],"g")),s=P):c[3]!==void 0&&(s=P):s===P?c[0]===">"?(s=i??W,p=-1):c[1]===void 0?p=-2:(p=s.lastIndex-c[2].length,d=c[1],s=c[3]===void 0?P:c[3]==='"'?Ke:Ye):s===Ke||s===Ye?s=P:s===je||s===qe?s=W:(s=P,i=void 0);let _=s===P&&a[o+1].startsWith("/>")?" ":"";n+=s===W?l+Nt:p>=0?(t.push(d),l.slice(0,p)+Je+l.slice(p)+A+_):l+A+(p===-2?o:_)}return[et(a,n+(a[e]||"<?>")+(r===2?"</svg>":r===3?"</math>":"")),t]},q=class a{constructor({strings:r,_$litType$:e},t){let i;this.parts=[];let n=0,s=0,o=r.length-1,l=this.parts,[d,c]=Mt(r,e);if(this.el=a.createElement(d,t),C.currentNode=this.el.content,e===2||e===3){let p=this.el.content.firstChild;p.replaceWith(...p.childNodes)}for(;(i=C.nextNode())!==null&&l.length<o;){if(i.nodeType===1){if(i.hasAttributes())for(let p of i.getAttributeNames())if(p.endsWith(Je)){let y=c[s++],_=i.getAttribute(p).split(A),w=/([.?@])?(.*)/.exec(y);l.push({type:1,index:n,name:w[2],strings:_,ctor:w[1]==="."?_e:w[1]==="?"?ge:w[1]==="@"?be:V}),i.removeAttribute(p)}else p.startsWith(A)&&(l.push({type:6,index:n}),i.removeAttribute(p));if(Xe.test(i.tagName)){let p=i.textContent.split(A),y=p.length-1;if(y>0){i.textContent=re?re.emptyScript:"";for(let _=0;_<y;_++)i.append(p[_],G()),C.nextNode(),l.push({type:2,index:++n});i.append(p[y],G())}}}else if(i.nodeType===8)if(i.data===Ze)l.push({type:2,index:n});else{let p=-1;for(;(p=i.data.indexOf(A,p+1))!==-1;)l.push({type:7,index:n}),p+=A.length-1}n++}}static createElement(r,e){let t=N.createElement("template");return t.innerHTML=r,t}};function I(a,r,e=a,t){if(r===O)return r;let i=t!==void 0?e._$Co?.[t]:e._$Cl,n=j(r)?void 0:r._$litDirective$;return i?.constructor!==n&&(i?._$AO?.(!1),n===void 0?i=void 0:(i=new n(a),i._$AT(a,e,t)),t!==void 0?(e._$Co??=[])[t]=i:e._$Cl=i),i!==void 0&&(r=I(a,i._$AS(a,r.values),i,t)),r}var fe=class{constructor(r,e){this._$AV=[],this._$AN=void 0,this._$AD=r,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(r){let{el:{content:e},parts:t}=this._$AD,i=(r?.creationScope??N).importNode(e,!0);C.currentNode=i;let n=C.nextNode(),s=0,o=0,l=t[0];for(;l!==void 0;){if(s===l.index){let d;l.type===2?d=new Y(n,n.nextSibling,this,r):l.type===1?d=new l.ctor(n,l.name,l.strings,this,r):l.type===6&&(d=new ve(n,this,r)),this._$AV.push(d),l=t[++o]}s!==l?.index&&(n=C.nextNode(),s++)}return C.currentNode=N,i}p(r){let e=0;for(let t of this._$AV)t!==void 0&&(t.strings!==void 0?(t._$AI(r,t,e),e+=t.strings.length-2):t._$AI(r[e])),e++}},Y=class a{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(r,e,t,i){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=r,this._$AB=e,this._$AM=t,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let r=this._$AA.parentNode,e=this._$AM;return e!==void 0&&r?.nodeType===11&&(r=e.parentNode),r}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(r,e=this){r=I(this,r,e),j(r)?r===h||r==null||r===""?(this._$AH!==h&&this._$AR(),this._$AH=h):r!==this._$AH&&r!==O&&this._(r):r._$litType$!==void 0?this.$(r):r.nodeType!==void 0?this.T(r):Ot(r)?this.k(r):this._(r)}O(r){return this._$AA.parentNode.insertBefore(r,this._$AB)}T(r){this._$AH!==r&&(this._$AR(),this._$AH=this.O(r))}_(r){this._$AH!==h&&j(this._$AH)?this._$AA.nextSibling.data=r:this.T(N.createTextNode(r)),this._$AH=r}$(r){let{values:e,_$litType$:t}=r,i=typeof t=="number"?this._$AC(r):(t.el===void 0&&(t.el=q.createElement(et(t.h,t.h[0]),this.options)),t);if(this._$AH?._$AD===i)this._$AH.p(e);else{let n=new fe(i,this),s=n.u(this.options);n.p(e),this.T(s),this._$AH=n}}_$AC(r){let e=Qe.get(r.strings);return e===void 0&&Qe.set(r.strings,e=new q(r)),e}k(r){we(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,t,i=0;for(let n of r)i===e.length?e.push(t=new a(this.O(G()),this.O(G()),this,this.options)):t=e[i],t._$AI(n),i++;i<e.length&&(this._$AR(t&&t._$AB.nextSibling,i),e.length=i)}_$AR(r=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);r!==this._$AB;){let t=We(r).nextSibling;We(r).remove(),r=t}}setConnected(r){this._$AM===void 0&&(this._$Cv=r,this._$AP?.(r))}},V=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(r,e,t,i,n){this.type=1,this._$AH=h,this._$AN=void 0,this.element=r,this.name=e,this._$AM=i,this.options=n,t.length>2||t[0]!==""||t[1]!==""?(this._$AH=Array(t.length-1).fill(new String),this.strings=t):this._$AH=h}_$AI(r,e=this,t,i){let n=this.strings,s=!1;if(n===void 0)r=I(this,r,e,0),s=!j(r)||r!==this._$AH&&r!==O,s&&(this._$AH=r);else{let o=r,l,d;for(r=n[0],l=0;l<n.length-1;l++)d=I(this,o[t+l],e,l),d===O&&(d=this._$AH[l]),s||=!j(d)||d!==this._$AH[l],d===h?r=h:r!==h&&(r+=(d??"")+n[l+1]),this._$AH[l]=d}s&&!i&&this.j(r)}j(r){r===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,r??"")}},_e=class extends V{constructor(){super(...arguments),this.type=3}j(r){this.element[this.name]=r===h?void 0:r}},ge=class extends V{constructor(){super(...arguments),this.type=4}j(r){this.element.toggleAttribute(this.name,!!r&&r!==h)}},be=class extends V{constructor(r,e,t,i,n){super(r,e,t,i,n),this.type=5}_$AI(r,e=this){if((r=I(this,r,e,0)??h)===O)return;let t=this._$AH,i=r===h&&t!==h||r.capture!==t.capture||r.once!==t.once||r.passive!==t.passive,n=r!==h&&(t===h||i);i&&this.element.removeEventListener(this.name,this,t),n&&this.element.addEventListener(this.name,this,r),this._$AH=r}handleEvent(r){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,r):this._$AH.handleEvent(r)}},ve=class{constructor(r,e,t){this.element=r,this.type=6,this._$AN=void 0,this._$AM=e,this.options=t}get _$AU(){return this._$AM._$AU}_$AI(r){I(this,r)}};var Ft=ye.litHtmlPolyfillSupport;Ft?.(q,Y),(ye.litHtmlVersions??=[]).push("3.3.3");var tt=(a,r,e)=>{let t=e?.renderBefore??r,i=t._$litPart$;if(i===void 0){let n=e?.renderBefore??null;t._$litPart$=i=new Y(r.insertBefore(G(),n),n,void 0,e??{})}return i._$AI(a),i};var Se=globalThis,R=class extends E{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let r=super.createRenderRoot();return this.renderOptions.renderBefore??=r.firstChild,r}update(r){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(r),this._$Do=tt(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return O}};R._$litElement$=!0,R.finalized=!0,Se.litElementHydrateSupport?.({LitElement:R});var It=Se.litElementPolyfillSupport;It?.({LitElement:R});(Se.litElementVersions??=[]).push("4.2.2");var rt=a=>(r,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(a,r)}):customElements.define(a,r)};var Vt={attribute:!0,type:String,converter:z,reflect:!1,hasChanged:te},Lt=(a=Vt,r,e)=>{let{kind:t,metadata:i}=e,n=globalThis.litPropertyMetadata.get(i);if(n===void 0&&globalThis.litPropertyMetadata.set(i,n=new Map),t==="setter"&&((a=Object.create(a)).wrapped=!0),n.set(e.name,a),t==="accessor"){let{name:s}=e;return{set(o){let l=r.get.call(this);r.set.call(this,o),this.requestUpdate(s,l,a,!0,o)},init(o){return o!==void 0&&this.C(s,void 0,a,o),o}}}if(t==="setter"){let{name:s}=e;return function(o){let l=this[s];r.call(this,o),this.requestUpdate(s,l,a,!0,o)}}throw Error("Unsupported decorator location: "+t)};function ie(a){return(r,e)=>typeof e=="object"?Lt(a,r,e):((t,i,n)=>{let s=i.hasOwnProperty(n);return i.constructor.createProperty(n,t),s?Object.getOwnPropertyDescriptor(i,n):void 0})(a,r,e)}function x(a){return ie({...a,state:!0,attribute:!1})}var ke="Energy Actions";var Ut=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Bt=/DEFERRED/i,Ht=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function ne(a){let{active:r,armed:e,operationInProgress:t,statusText:i}=a;return r===null||e===null||t===null?"unavailable":i&&Ut.test(i)?"recovery_attention":i&&Bt.test(i)?"deferred":i&&Ht.test(i)?"busy":r?"active":t?"busy":e?"armed":"ready"}function it(a){return a==="armed"}function $e(a){return a!=="busy"&&a!=="unavailable"}function at(a){return a==="ready"||a==="armed"}var zt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function nt(a){return zt[a]}var Wt=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Gt=/DEFERRED/i,jt=/^(RESTORING|STARTING)/i;function se(a){let{active:r,armed:e,operationInProgress:t,snapshotValid:i,statusText:n}=a;return r===null||e===null||t===null||i===null?"unavailable":n&&Wt.test(n)?"recovery_attention":n&&Gt.test(n)?"deferred":n&&jt.test(n)?"busy":r?"active":t?"busy":i?"deferred":e?"armed":"ready"}function st(a){return a==="armed"}function oe(a){return a!=="busy"&&a!=="unavailable"}function ot(a){return a==="ready"||a==="armed"}var qt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function Yt(a){return qt[a]}function De(a,r){return a==="ready"&&r===!0?"scheduled":a}function Ee(a){return a==="scheduled"?"Scheduled":a==="interlocked"?"Interlocked":Yt(a)}var Kt=/target (\d+)\s*W export/i,Qt=/Stop SOC (\d+)\s*%/i;function lt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Kt.exec(r):null;return e?Number(e[1]):null}function dt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Qt.exec(r):null;return e?Number(e[1]):null}var Jt=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function ct(a,r){return r===!0&&!!a&&Jt.test(a)}var Zt=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,Xt=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,er=/OPERATOR DECISION REQUIRED/i,tr=/press End Free Power|retry(?:ing)? restore/i,rr=/\bRECOVERY REQUIRED\b/i,ir=/snapshot retained/i,ar=/RESTORE BLOCKED/i;function ut(a){let r=a.statusText??"",e=a.snapshotValid;return Zt.test(r)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:Xt.test(r)&&e===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:er.test(r)&&tr.test(r)&&e===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:rr.test(r)&&e===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:ir.test(r)&&e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:ar.test(r)?e===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var nr=new Set(["active","busy","recovery_attention","deferred"]);function sr(a){return a!==null&&nr.has(a)}function K(a,r){return(a==="ready"||a==="armed")&&sr(r)}function Q(a,r){return a&&!r}function Te(a,r){switch(r){case"busy":return`${a} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${a} requires recovery before this can be used.`;default:return`${a} currently owns inverter control.`}}var pt=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function ht(a){let r=pt.indexOf(a);return r<0?pt.length:r}function mt(a,r){return a!=="unavailable"||r!=="unavailable"}function Ae(a,r){return ht(r)<ht(a)?"dump_to_grid":"free_power"}function ft(a){switch(a){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function _t(a){switch(a){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function gt(a){return a==="dump_to_grid"?"Dump to Grid":"Free Power"}function bt(a,r,e){let t=e?.trim()??"";return t?`${a}: ${r} - ${t}`:`${a}: ${r}`}function Re(a){return a.armed===!0?"armed":"hidden"}function Pe(a){return!!a&&/^REJECTED/i.test(a.trim())}function Ce(a){return!!a&&/^BLOCKED/i.test(a.trim())}function Ne(a){return a===!0}function Oe(a,r){return a==="ready"&&r==="armed"?"scheduled":a}function Me(a){return{domain:"input_boolean",service:"turn_on",data:{entity_id:a}}}function Fe(a){return{domain:"script",service:"turn_on",data:{entity_id:a}}}function vt(a,r){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:a,datetime:r}}}function Ie(a,r){return{domain:"input_number",service:"set_value",data:{entity_id:a,value:r}}}function yt(a,r){return r===null||!Number.isFinite(r)||r<=0?a:Math.min(a,r)}var or=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function M(a){if(!a)return null;let r=or.exec(a.trim());if(!r)return null;let[,e,t,i,n,s,o]=r,l=new Date(Number(e),Number(t)-1,Number(i),Number(n),Number(s),Number(o));return Number.isNaN(l.getTime())?null:l}function wt(a){let r=e=>e.toString().padStart(2,"0");return`${a.getFullYear()}-${r(a.getMonth()+1)}-${r(a.getDate())} ${r(a.getHours())}:${r(a.getMinutes())}:${r(a.getSeconds())}`}var lr=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],dr=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Ve(a){let r=lr[a.getDay()],e=a.getDate(),t=dr[a.getMonth()],i=a.getHours().toString().padStart(2,"0"),n=a.getMinutes().toString().padStart(2,"0");return`${r} ${e} ${t} \u2022 ${i}:${n}`}function J(a,r){let e=a-r;if(e<=0)return null;let t=Math.floor(e/1e3),i=Math.floor(t/3600),n=Math.floor(t%3600/60),s=t%60;return i>0?`${i}h ${n}m`:n>0?`${n}m ${s.toString().padStart(2,"0")}s`:`${s}s`}function T(a){return a==null||Number.isNaN(a)?"--":Math.abs(a)>=1e3?`${(a/1e3).toFixed(2)} kW`:`${a.toFixed(0)} W`}function F(a){if(a==null||Number.isNaN(a))return"--";let r=Math.round(a);if(r<60)return`${r} min`;let e=Math.floor(r/60),t=r%60;return t===0?`${e}h`:`${e}h ${t}m`}function L(a){return a==null||Number.isNaN(a)?"--":`${Math.round(a)}%`}function f(a){if(a==null||a==="unknown"||a==="unavailable"||a==="")return null;let r=Number(a);return Number.isFinite(r)?r:null}function m(a){return a==null||a==="unknown"||a==="unavailable"||a===""?null:a==="on"}var le=4e3,cr=1e3,g=class extends R{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:ke,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!e.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=e}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(e){return!!this._config}willUpdate(){let e=this._config?.free_power;if(e){this._pendingPower!==void 0&&f(this._entityState(e.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&f(this._entityState(e.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let n=m(this._entityState(e.active)),s=m(this._entityState(e.write_enable)),o=m(this._entityState(e.operation_in_progress)),l=this._entityState(e.status),d=ne({active:n,armed:s,operationInProgress:o,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==d&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=d}let t=this._config?.schedule;t&&(this._pendingSchedulePower!==void 0&&f(this._entityState(t.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&f(this._entityState(t.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&f(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&f(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&f(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let n=i.schedule;n&&(this._pendingDumpSchedulePower!==void 0&&f(this._entityState(n.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&f(this._entityState(n.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&f(this._entityState(n.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let s=m(this._entityState(i.active)),o=m(this._entityState(i.write_enable)),l=m(this._entityState(i.operation_in_progress)),d=m(this._entityState(i.snapshot_valid)),c=this._entityState(i.status),p=se({active:s,armed:o,operationInProgress:l,snapshotValid:d,statusText:c});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==p&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=p}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let n=this._trackSummary();mt(n.fp.state,n.dump.state)&&(this._track=Ae(n.fp.state,n.dump.state))}}updated(){let e=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();e&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},cr):!e&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let e=this._config?.free_power;return e?m(this._entityState(e.active))===!0:!1}_scheduleArmed(){let e=this._config?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_dumpActive(){let e=this._config?.dump_to_grid;return e?m(this._entityState(e.active))===!0:!1}_dumpScheduleArmed(){let e=this._config?.dump_to_grid?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_freePowerVisualStateForInterlock(){let e=this._config?.free_power;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=this._entityState(e.status);return ne({active:t,armed:i,operationInProgress:n,statusText:s})}_dumpVisualStateForInterlock(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status);return se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o})}_entityState(e){if(!(!e||!this.hass))return this.hass.states[e]?.state}_entity(e){if(!(!e||!this.hass))return this.hass.states[e]}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_callService(e,t,i){this.hass?.callService&&this.hass.callService(e,t,i)}_callServiceObj(e){this._callService(e.domain,e.service,e.data)}render(){if(!this._config)return u``;let e=this._config.title??ke;return this._config.layout==="tabbed"?this._renderTabbed(e):u`
"""),
     _blk(r"""
var yr=Object.defineProperty;var Sr=Object.getOwnPropertyDescriptor;var C=(e,n,t,r)=>{for(var i=r>1?void 0:r?Sr(n,t):n,o=e.length-1,a;o>=0;o--)(a=e[o])&&(i=(r?a(n,t,i):a(i))||i);return r&&i&&yr(n,t,i),i};var He=globalThis,Ge=He.ShadowRoot&&(He.ShadyCSS===void 0||He.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,rt=Symbol(),qt=new WeakMap,Ee=class{constructor(n,t,r){if(this._$cssResult$=!0,r!==rt)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=n,this.t=t}get styleSheet(){let n=this.o,t=this.t;if(Ge&&n===void 0){let r=t!==void 0&&t.length===1;r&&(n=qt.get(t)),n===void 0&&((this.o=n=new CSSStyleSheet).replaceSync(this.cssText),r&&qt.set(t,n))}return n}toString(){return this.cssText}},Xt=e=>new Ee(typeof e=="string"?e:e+"",void 0,rt),de=(e,...n)=>{let t=e.length===1?e[0]:n.reduce((r,i,o)=>r+(a=>{if(a._$cssResult$===!0)return a.cssText;if(typeof a=="number")return a;throw Error("Value passed to 'css' function must be a 'css' function result: "+a+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+e[o+1],e[0]);return new Ee(t,e,rt)},Qt=(e,n)=>{if(Ge)e.adoptedStyleSheets=n.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(let t of n){let r=document.createElement("style"),i=He.litNonce;i!==void 0&&r.setAttribute("nonce",i),r.textContent=t.cssText,e.appendChild(r)}},it=Ge?e=>e:e=>e instanceof CSSStyleSheet?(n=>{let t="";for(let r of n.cssRules)t+=r.cssText;return Xt(t)})(e):e;var{is:Er,defineProperty:kr,getOwnPropertyDescriptor:Mr,getOwnPropertyNames:Pr,getOwnPropertySymbols:Rr,getPrototypeOf:Tr}=Object,Ke=globalThis,Jt=Ke.trustedTypes,Dr=Jt?Jt.emptyScript:"",Ar=Ke.reactiveElementPolyfillSupport,ke=(e,n)=>e,Me={toAttribute(e,n){switch(n){case Boolean:e=e?Dr:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,n){let t=e;switch(n){case Boolean:t=e!==null;break;case Number:t=e===null?null:Number(e);break;case Object:case Array:try{t=JSON.parse(e)}catch{t=null}}return t}},Be=(e,n)=>!Er(e,n),Zt={attribute:!0,type:String,converter:Me,reflect:!1,useDefault:!1,hasChanged:Be};Symbol.metadata??=Symbol("metadata"),Ke.litPropertyMetadata??=new WeakMap;var te=class extends HTMLElement{static addInitializer(n){this._$Ei(),(this.l??=[]).push(n)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(n,t=Zt){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(n)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(n,t),!t.noAccessor){let r=Symbol(),i=this.getPropertyDescriptor(n,r,t);i!==void 0&&kr(this.prototype,n,i)}}static getPropertyDescriptor(n,t,r){let{get:i,set:o}=Mr(this.prototype,n)??{get(){return this[t]},set(a){this[t]=a}};return{get:i,set(a){let s=i?.call(this);o?.call(this,a),this.requestUpdate(n,s,r)},configurable:!0,enumerable:!0}}static getPropertyOptions(n){return this.elementProperties.get(n)??Zt}static _$Ei(){if(this.hasOwnProperty(ke("elementProperties")))return;let n=Tr(this);n.finalize(),n.l!==void 0&&(this.l=[...n.l]),this.elementProperties=new Map(n.elementProperties)}static finalize(){if(this.hasOwnProperty(ke("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(ke("properties"))){let t=this.properties,r=[...Pr(t),...Rr(t)];for(let i of r)this.createProperty(i,t[i])}let n=this[Symbol.metadata];if(n!==null){let t=litPropertyMetadata.get(n);if(t!==void 0)for(let[r,i]of t)this.elementProperties.set(r,i)}this._$Eh=new Map;for(let[t,r]of this.elementProperties){let i=this._$Eu(t,r);i!==void 0&&this._$Eh.set(i,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(n){let t=[];if(Array.isArray(n)){let r=new Set(n.flat(1/0).reverse());for(let i of r)t.unshift(it(i))}else n!==void 0&&t.push(it(n));return t}static _$Eu(n,t){let r=t.attribute;return r===!1?void 0:typeof r=="string"?r:typeof n=="string"?n.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(n=>this.enableUpdating=n),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(n=>n(this))}addController(n){(this._$EO??=new Set).add(n),this.renderRoot!==void 0&&this.isConnected&&n.hostConnected?.()}removeController(n){this._$EO?.delete(n)}_$E_(){let n=new Map,t=this.constructor.elementProperties;for(let r of t.keys())this.hasOwnProperty(r)&&(n.set(r,this[r]),delete this[r]);n.size>0&&(this._$Ep=n)}createRenderRoot(){let n=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Qt(n,this.constructor.elementStyles),n}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(n=>n.hostConnected?.())}enableUpdating(n){}disconnectedCallback(){this._$EO?.forEach(n=>n.hostDisconnected?.())}attributeChangedCallback(n,t,r){this._$AK(n,r)}_$ET(n,t){let r=this.constructor.elementProperties.get(n),i=this.constructor._$Eu(n,r);if(i!==void 0&&r.reflect===!0){let o=(r.converter?.toAttribute!==void 0?r.converter:Me).toAttribute(t,r.type);this._$Em=n,o==null?this.removeAttribute(i):this.setAttribute(i,o),this._$Em=null}}_$AK(n,t){let r=this.constructor,i=r._$Eh.get(n);if(i!==void 0&&this._$Em!==i){let o=r.getPropertyOptions(i),a=typeof o.converter=="function"?{fromAttribute:o.converter}:o.converter?.fromAttribute!==void 0?o.converter:Me;this._$Em=i;let s=a.fromAttribute(t,o.type);this[i]=s??this._$Ej?.get(i)??s,this._$Em=null}}requestUpdate(n,t,r,i=!1,o){if(n!==void 0){let a=this.constructor;if(i===!1&&(o=this[n]),r??=a.getPropertyOptions(n),!((r.hasChanged??Be)(o,t)||r.useDefault&&r.reflect&&o===this._$Ej?.get(n)&&!this.hasAttribute(a._$Eu(n,r))))return;this.C(n,t,r)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(n,t,{useDefault:r,reflect:i,wrapped:o},a){r&&!(this._$Ej??=new Map).has(n)&&(this._$Ej.set(n,a??t??this[n]),o!==!0||a!==void 0)||(this._$AL.has(n)||(this.hasUpdated||r||(t=void 0),this._$AL.set(n,t)),i===!0&&this._$Em!==n&&(this._$Eq??=new Set).add(n))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}let n=this.scheduleUpdate();return n!=null&&await n,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,o]of this._$Ep)this[i]=o;this._$Ep=void 0}let r=this.constructor.elementProperties;if(r.size>0)for(let[i,o]of r){let{wrapped:a}=o,s=this[i];a!==!0||this._$AL.has(i)||s===void 0||this.C(i,void 0,o,s)}}let n=!1,t=this._$AL;try{n=this.shouldUpdate(t),n?(this.willUpdate(t),this._$EO?.forEach(r=>r.hostUpdate?.()),this.update(t)):this._$EM()}catch(r){throw n=!1,this._$EM(),r}n&&this._$AE(t)}willUpdate(n){}_$AE(n){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(n)),this.updated(n)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(n){return!0}update(n){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(n){}firstUpdated(n){}};te.elementStyles=[],te.shadowRootOptions={mode:"open"},te[ke("elementProperties")]=new Map,te[ke("finalized")]=new Map,Ar?.({ReactiveElement:te}),(Ke.reactiveElementVersions??=[]).push("2.1.2");var ut=globalThis,en=e=>e,je=ut.trustedTypes,tn=je?je.createPolicy("lit-html",{createHTML:e=>e}):void 0,ln="$lit$",ae=`lit$${Math.random().toFixed(9).slice(2)}$`,cn="?"+ae,Cr=`<${cn}>`,he=document,Re=()=>he.createComment(""),Te=e=>e===null||typeof e!="object"&&typeof e!="function",pt=Array.isArray,Nr=e=>pt(e)||typeof e?.[Symbol.iterator]=="function",ot=`[ 	
\f\r]`,Pe=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,nn=/-->/g,rn=/>/g,ue=RegExp(`>|${ot}(?:([^\\s"'>=/]+)(${ot}*=${ot}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),on=/'/g,an=/"/g,dn=/^(?:script|style|textarea|title)$/i,ht=e=>(n,...t)=>({_$litType$:e,strings:n,values:t}),u=ht(1),Io=ht(2),Oo=ht(3),me=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),sn=new WeakMap,pe=he.createTreeWalker(he,129);function un(e,n){if(!pt(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return tn!==void 0?tn.createHTML(n):n}var Ir=(e,n)=>{let t=e.length-1,r=[],i,o=n===2?"<svg>":n===3?"<math>":"",a=Pe;for(let s=0;s<t;s++){let l=e[s],p,c,d=-1,v=0;for(;v<l.length&&(a.lastIndex=v,c=a.exec(l),c!==null);)v=a.lastIndex,a===Pe?c[1]==="!--"?a=nn:c[1]!==void 0?a=rn:c[2]!==void 0?(dn.test(c[2])&&(i=RegExp("</"+c[2],"g")),a=ue):c[3]!==void 0&&(a=ue):a===ue?c[0]===">"?(a=i??Pe,d=-1):c[1]===void 0?d=-2:(d=a.lastIndex-c[2].length,p=c[1],a=c[3]===void 0?ue:c[3]==='"'?an:on):a===an||a===on?a=ue:a===nn||a===rn?a=Pe:(a=ue,i=void 0);let b=a===ue&&e[s+1].startsWith("/>")?" ":"";o+=a===Pe?l+Cr:d>=0?(r.push(p),l.slice(0,d)+ln+l.slice(d)+ae+b):l+ae+(d===-2?s:b)}return[un(e,o+(e[t]||"<?>")+(n===2?"</svg>":n===3?"</math>":"")),r]},De=class e{constructor({strings:n,_$litType$:t},r){let i;this.parts=[];let o=0,a=0,s=n.length-1,l=this.parts,[p,c]=Ir(n,t);if(this.el=e.createElement(p,r),pe.currentNode=this.el.content,t===2||t===3){let d=this.el.content.firstChild;d.replaceWith(...d.childNodes)}for(;(i=pe.nextNode())!==null&&l.length<s;){if(i.nodeType===1){if(i.hasAttributes())for(let d of i.getAttributeNames())if(d.endsWith(ln)){let v=c[a++],b=i.getAttribute(d).split(ae),m=/([.?@])?(.*)/.exec(v);l.push({type:1,index:o,name:m[2],strings:b,ctor:m[1]==="."?st:m[1]==="?"?lt:m[1]==="@"?ct:_e}),i.removeAttribute(d)}else d.startsWith(ae)&&(l.push({type:6,index:o}),i.removeAttribute(d));if(dn.test(i.tagName)){let d=i.textContent.split(ae),v=d.length-1;if(v>0){i.textContent=je?je.emptyScript:"";for(let b=0;b<v;b++)i.append(d[b],Re()),pe.nextNode(),l.push({type:2,index:++o});i.append(d[v],Re())}}}else if(i.nodeType===8)if(i.data===cn)l.push({type:2,index:o});else{let d=-1;for(;(d=i.data.indexOf(ae,d+1))!==-1;)l.push({type:7,index:o}),d+=ae.length-1}o++}}static createElement(n,t){let r=he.createElement("template");return r.innerHTML=n,r}};function ve(e,n,t=e,r){if(n===me)return n;let i=r!==void 0?t._$Co?.[r]:t._$Cl,o=Te(n)?void 0:n._$litDirective$;return i?.constructor!==o&&(i?._$AO?.(!1),o===void 0?i=void 0:(i=new o(e),i._$AT(e,t,r)),r!==void 0?(t._$Co??=[])[r]=i:t._$Cl=i),i!==void 0&&(n=ve(e,i._$AS(e,n.values),i,r)),n}var at=class{constructor(n,t){this._$AV=[],this._$AN=void 0,this._$AD=n,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(n){let{el:{content:t},parts:r}=this._$AD,i=(n?.creationScope??he).importNode(t,!0);pe.currentNode=i;let o=pe.nextNode(),a=0,s=0,l=r[0];for(;l!==void 0;){if(a===l.index){let p;l.type===2?p=new Ae(o,o.nextSibling,this,n):l.type===1?p=new l.ctor(o,l.name,l.strings,this,n):l.type===6&&(p=new dt(o,this,n)),this._$AV.push(p),l=r[++s]}a!==l?.index&&(o=pe.nextNode(),a++)}return pe.currentNode=he,i}p(n){let t=0;for(let r of this._$AV)r!==void 0&&(r.strings!==void 0?(r._$AI(n,r,t),t+=r.strings.length-2):r._$AI(n[t])),t++}},Ae=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(n,t,r,i){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=n,this._$AB=t,this._$AM=r,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let n=this._$AA.parentNode,t=this._$AM;return t!==void 0&&n?.nodeType===11&&(n=t.parentNode),n}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(n,t=this){n=ve(this,n,t),Te(n)?n===h||n==null||n===""?(this._$AH!==h&&this._$AR(),this._$AH=h):n!==this._$AH&&n!==me&&this._(n):n._$litType$!==void 0?this.$(n):n.nodeType!==void 0?this.T(n):Nr(n)?this.k(n):this._(n)}O(n){return this._$AA.parentNode.insertBefore(n,this._$AB)}T(n){this._$AH!==n&&(this._$AR(),this._$AH=this.O(n))}_(n){this._$AH!==h&&Te(this._$AH)?this._$AA.nextSibling.data=n:this.T(he.createTextNode(n)),this._$AH=n}$(n){let{values:t,_$litType$:r}=n,i=typeof r=="number"?this._$AC(n):(r.el===void 0&&(r.el=De.createElement(un(r.h,r.h[0]),this.options)),r);if(this._$AH?._$AD===i)this._$AH.p(t);else{let o=new at(i,this),a=o.u(this.options);o.p(t),this.T(a),this._$AH=o}}_$AC(n){let t=sn.get(n.strings);return t===void 0&&sn.set(n.strings,t=new De(n)),t}k(n){pt(this._$AH)||(this._$AH=[],this._$AR());let t=this._$AH,r,i=0;for(let o of n)i===t.length?t.push(r=new e(this.O(Re()),this.O(Re()),this,this.options)):r=t[i],r._$AI(o),i++;i<t.length&&(this._$AR(r&&r._$AB.nextSibling,i),t.length=i)}_$AR(n=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);n!==this._$AB;){let r=en(n).nextSibling;en(n).remove(),n=r}}setConnected(n){this._$AM===void 0&&(this._$Cv=n,this._$AP?.(n))}},_e=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(n,t,r,i,o){this.type=1,this._$AH=h,this._$AN=void 0,this.element=n,this.name=t,this._$AM=i,this.options=o,r.length>2||r[0]!==""||r[1]!==""?(this._$AH=Array(r.length-1).fill(new String),this.strings=r):this._$AH=h}_$AI(n,t=this,r,i){let o=this.strings,a=!1;if(o===void 0)n=ve(this,n,t,0),a=!Te(n)||n!==this._$AH&&n!==me,a&&(this._$AH=n);else{let s=n,l,p;for(n=o[0],l=0;l<o.length-1;l++)p=ve(this,s[r+l],t,l),p===me&&(p=this._$AH[l]),a||=!Te(p)||p!==this._$AH[l],p===h?n=h:n!==h&&(n+=(p??"")+o[l+1]),this._$AH[l]=p}a&&!i&&this.j(n)}j(n){n===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,n??"")}},st=class extends _e{constructor(){super(...arguments),this.type=3}j(n){this.element[this.name]=n===h?void 0:n}},lt=class extends _e{constructor(){super(...arguments),this.type=4}j(n){this.element.toggleAttribute(this.name,!!n&&n!==h)}},ct=class extends _e{constructor(n,t,r,i,o){super(n,t,r,i,o),this.type=5}_$AI(n,t=this){if((n=ve(this,n,t,0)??h)===me)return;let r=this._$AH,i=n===h&&r!==h||n.capture!==r.capture||n.once!==r.once||n.passive!==r.passive,o=n!==h&&(r===h||i);i&&this.element.removeEventListener(this.name,this,r),o&&this.element.addEventListener(this.name,this,n),this._$AH=n}handleEvent(n){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,n):this._$AH.handleEvent(n)}},dt=class{constructor(n,t,r){this.element=n,this.type=6,this._$AN=void 0,this._$AM=t,this.options=r}get _$AU(){return this._$AM._$AU}_$AI(n){ve(this,n)}};var Or=ut.litHtmlPolyfillSupport;Or?.(De,Ae),(ut.litHtmlVersions??=[]).push("3.3.3");var pn=(e,n,t)=>{let r=t?.renderBefore??n,i=r._$litPart$;if(i===void 0){let o=t?.renderBefore??null;r._$litPart$=i=new Ae(n.insertBefore(Re(),o),o,void 0,t??{})}return i._$AI(e),i};var mt=globalThis,se=class extends te{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let n=super.createRenderRoot();return this.renderOptions.renderBefore??=n.firstChild,n}update(n){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(n),this._$Do=pn(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return me}};se._$litElement$=!0,se.finalized=!0,mt.litElementHydrateSupport?.({LitElement:se});var $r=mt.litElementPolyfillSupport;$r?.({LitElement:se});(mt.litElementVersions??=[]).push("4.2.2");var hn=e=>(n,t)=>{t!==void 0?t.addInitializer(()=>{customElements.define(e,n)}):customElements.define(e,n)};var Lr={attribute:!0,type:String,converter:Me,reflect:!1,hasChanged:Be},Wr=(e=Lr,n,t)=>{let{kind:r,metadata:i}=t,o=globalThis.litPropertyMetadata.get(i);if(o===void 0&&globalThis.litPropertyMetadata.set(i,o=new Map),r==="setter"&&((e=Object.create(e)).wrapped=!0),o.set(t.name,e),r==="accessor"){let{name:a}=t;return{set(s){let l=n.get.call(this);n.set.call(this,s),this.requestUpdate(a,l,e,!0,s)},init(s){return s!==void 0&&this.C(a,void 0,e,s),s}}}if(r==="setter"){let{name:a}=t;return function(s){let l=this[a];n.call(this,s),this.requestUpdate(a,l,e,!0,s)}}throw Error("Unsupported decorator location: "+r)};function ze(e){return(n,t)=>typeof t=="object"?Wr(e,n,t):((r,i,o)=>{let a=i.hasOwnProperty(o);return i.constructor.createProperty(o,r),a?Object.getOwnPropertyDescriptor(i,o):void 0})(e,n,t)}function O(e){return ze({...e,state:!0,attribute:!1})}var ft="Energy Actions";var Fr=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Vr=/DEFERRED/i,Ur=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function qe(e){let{active:n,armed:t,operationInProgress:r,statusText:i}=e;return n===null||t===null||r===null?"unavailable":i&&Fr.test(i)?"recovery_attention":i&&Vr.test(i)?"deferred":i&&Ur.test(i)?"busy":n?"active":r?"busy":t?"armed":"ready"}function mn(e){return e==="armed"}function gt(e){return e!=="busy"&&e!=="unavailable"}function fn(e){return e==="ready"||e==="armed"}var Hr={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function gn(e){return Hr[e]}var Gr=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Kr=/DEFERRED/i,Br=/^(RESTORING|STARTING)/i;function Xe(e){let{active:n,armed:t,operationInProgress:r,snapshotValid:i,statusText:o}=e;return n===null||t===null||r===null||i===null?"unavailable":o&&Gr.test(o)?"recovery_attention":o&&Kr.test(o)?"deferred":o&&Br.test(o)?"busy":n?"active":r?"busy":i?"deferred":t?"armed":"ready"}function bn(e){return e==="armed"}function Qe(e){return e!=="busy"&&e!=="unavailable"}function vn(e){return e==="ready"||e==="armed"}var jr={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function zr(e){return jr[e]}function bt(e,n){return e==="ready"&&n===!0?"scheduled":e}function vt(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":zr(e)}var Yr=/target (\d+)\s*W export/i,qr=/Stop SOC (\d+)\s*%/i;function _n(e,n){if(e!==null&&Number.isFinite(e))return e;let t=n?Yr.exec(n):null;return t?Number(t[1]):null}function wn(e,n){if(e!==null&&Number.isFinite(e))return e;let t=n?qr.exec(n):null;return t?Number(t[1]):null}var Xr=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function xn(e,n){return n===!0&&!!e&&Xr.test(e)}var Qr=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,Jr=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,Zr=/OPERATOR DECISION REQUIRED/i,ei=/press End Free Power|retry(?:ing)? restore/i,ti=/\bRECOVERY REQUIRED\b/i,ni=/snapshot retained/i,ri=/RESTORE BLOCKED/i;function yn(e){let n=e.statusText??"",t=e.snapshotValid;return Qr.test(n)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:Jr.test(n)&&t===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:Zr.test(n)&&ei.test(n)&&t===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:ti.test(n)&&t===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:ni.test(n)&&t===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:ri.test(n)?t===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:t===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var ii=new Set(["active","busy","recovery_attention","deferred"]);function oi(e){return e!==null&&ii.has(e)}function Ce(e,n){return(e==="ready"||e==="armed")&&oi(n)}function Ne(e,n){return e&&!n}function _t(e,n){switch(n){case"busy":return`${e} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${e} requires recovery before this can be used.`;default:return`${e} currently owns inverter control.`}}var Sn=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function En(e){let n=Sn.indexOf(e);return n<0?Sn.length:n}function kn(e,n){return e!=="unavailable"||n!=="unavailable"}function wt(e,n){return En(n)<En(e)?"dump_to_grid":"free_power"}function Mn(e){switch(e){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function Pn(e){switch(e){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function Rn(e){return e==="dump_to_grid"?"Dump to Grid":"Free Power"}function Tn(e,n,t){let r=t?.trim()??"";return r?`${e}: ${n} - ${r}`:`${e}: ${n}`}function xt(e){return e.armed===!0?"armed":"hidden"}function yt(e){return!!e&&/^REJECTED/i.test(e.trim())}function St(e){return!!e&&/^BLOCKED/i.test(e.trim())}function Et(e){return e===!0}function kt(e,n){return e==="ready"&&n==="armed"?"scheduled":e}function Mt(e){return{domain:"input_boolean",service:"turn_on",data:{entity_id:e}}}function Pt(e){return{domain:"script",service:"turn_on",data:{entity_id:e}}}function Dn(e,n){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:e,datetime:n}}}function Rt(e,n){return{domain:"input_number",service:"set_value",data:{entity_id:e,value:n}}}function An(e,n){return n===null||!Number.isFinite(n)||n<=0?e:Math.min(e,n)}var ai=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function fe(e){if(!e)return null;let n=ai.exec(e.trim());if(!n)return null;let[,t,r,i,o,a,s]=n,l=new Date(Number(t),Number(r)-1,Number(i),Number(o),Number(a),Number(s));return Number.isNaN(l.getTime())?null:l}function Cn(e){let n=t=>t.toString().padStart(2,"0");return`${e.getFullYear()}-${n(e.getMonth()+1)}-${n(e.getDate())} ${n(e.getHours())}:${n(e.getMinutes())}:${n(e.getSeconds())}`}var si=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],li=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Tt(e){let n=si[e.getDay()],t=e.getDate(),r=li[e.getMonth()],i=e.getHours().toString().padStart(2,"0"),o=e.getMinutes().toString().padStart(2,"0");return`${n} ${t} ${r} \u2022 ${i}:${o}`}function Ie(e,n){let t=e-n;if(t<=0)return null;let r=Math.floor(t/1e3),i=Math.floor(r/3600),o=Math.floor(r%3600/60),a=r%60;return i>0?`${i}h ${o}m`:o>0?`${o}m ${a.toString().padStart(2,"0")}s`:`${a}s`}function ne(e){return e==null||Number.isNaN(e)?"--":Math.abs(e)>=1e3?`${(e/1e3).toFixed(2)} kW`:`${e.toFixed(0)} W`}function ge(e){if(e==null||Number.isNaN(e))return"--";let n=Math.round(e);if(n<60)return`${n} min`;let t=Math.floor(n/60),r=n%60;return r===0?`${t}h`:`${t}h ${r}m`}function we(e){return e==null||Number.isNaN(e)?"--":`${Math.round(e)}%`}function S(e){if(e==null||e==="unknown"||e==="unavailable"||e==="")return null;let n=Number(e);return Number.isFinite(n)?n:null}function y(e){return e==null||e==="unknown"||e==="unavailable"||e===""?null:e==="on"}function re(e){return(Math.round(e)%1440+1440)%1440}function W(e,n){return re(n-e)}function F(e){let n=re(e),t=r=>(r<10?"0":"")+r;return t(Math.floor(n/60))+":"+t(n%60)}function Oe(e){return Number.isInteger(e)&&e>=0&&e<1440&&e%5===0}var Nn=Object.freeze({changeAtMin:0,deltaMin:0});function In(e){return e.deltaMin!==0}function $e(e,n,t){if(t.deltaMin===0||n<=0)return n;let r=W(e,t.changeAtMin);return r>0&&r<n?n-t.deltaMin:n}function On(e,n){for(let t=0;t<=n;t+=5)if(re(e+t)<180)return!0;return!1}var Ca=Object.freeze({owner:3,intelligence:2,native:1}),Dt=["MISMATCH","PROPOSED","ARMED","EXECUTING","APPLIED_VERIFIED"],f=Object.freeze({slots:6,minSlotMin:5,bufferMin:0,bufferMax:120,stopSocMin:10,stopSocMax:90,chargeTargetMin:20,chargeTargetMax:100,chargePowerMin:500,chargePowerMax:8e3,exportPowerMin:500,exportPowerMax:3e3,exportDurationMin:10,exportDurationMax:240,reserveMin:10,reserveMax:100}),Q={"charge.targetSoc":{label:"Charge target",unit:"%",min:f.chargeTargetMin,max:f.chargeTargetMax,step:1,views:["charge-card","tou-table","tomorrow-plan"]},"charge.bufferMin":{label:"Finish before the window ends",unit:"min",min:f.bufferMin,max:f.bufferMax,step:5,views:["charge-card","tomorrow-plan"]},"charge.powerW":{label:"Maximum charge power",unit:"W",min:f.chargePowerMin,max:f.chargePowerMax,step:100,views:["charge-card","tou-table","tomorrow-plan"]},"charge.windowStartMin":{label:"Charge window start",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"charge.windowEndMin":{label:"Charge window end",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"export.stopSoc":{label:"Export down to (Stop SOC)",unit:"%",min:f.stopSocMin,max:f.stopSocMax,step:1,views:["export-card","tou-table","tomorrow-plan","reserve-summary"]},"export.powerW":{label:"Export power",unit:"W",min:f.exportPowerMin,max:f.exportPowerMax,step:100,views:["export-card","tou-table","tomorrow-plan"]},"export.startMin":{label:"Export start",unit:"",min:0,max:1439,step:5,time:!0,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"export.durationMin":{label:"Export duration",unit:"min",min:f.exportDurationMin,max:f.exportDurationMax,step:5,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"reserve.backupPct":{label:"Backup reserve (enforced)",unit:"%",min:f.reserveMin,max:f.reserveMax,step:1,views:["charge-card","export-card","reserve-summary","tomorrow-plan"]},"reserve.planningPct":{label:"Planning reserve (advice)",unit:"%",min:f.reserveMin,max:f.reserveMax,step:1,views:["reserve-summary","tomorrow-plan"]}},xe=Object.freeze(Object.keys(Q));function Le(e,n){if(!Object.prototype.hasOwnProperty.call(Q,e))return{ok:!1,error:"Unknown setting."};let t=Q[e];if(typeof n!="number"||!Number.isFinite(n))return{ok:!1,error:t.label+" needs a number."};if(t.time)return Oe(n)?{ok:!0,value:n}:{ok:!1,error:t.label+" must be a time on the 5-minute grid."};if(n<t.min)return e==="export.stopSoc"?{ok:!1,error:"Stop SOC below "+t.min+" % is not available and is refused, not clamped."}:{ok:!1,error:t.label+" must be at least "+t.min+(t.unit?" "+t.unit:"")+"."};if(n>t.max)return e==="export.stopSoc"?{ok:!1,error:"Stop SOC above "+t.max+" % is not available and is refused, not clamped."}:{ok:!1,error:t.label+" can be at most "+t.max+(t.unit?" "+t.unit:"")+"."};let r=(n-t.min)/t.step;return Math.abs(r-Math.round(r))>1e-9?{ok:!1,error:t.label+" moves in steps of "+t.step+(t.unit?" "+t.unit:"")+"."}:{ok:!0,value:n}}function $n(e,n="owner"){let t={};for(let r of xe){let i=Le(r,e[r]);if(!i.ok)throw new Error(r+": "+i.error);t[r]={value:i.value,source:n,revision:1,state:"PROPOSED",observed:null,proposal:null,external:null}}return{revision:1,fields:t}}function ci(e){return JSON.parse(JSON.stringify(e))}function I(e,n){return{ok:!1,settings:e,error:n,updates:[]}}function ie(e,n,t){let r=t==="proposal"?n.proposal?.value:t==="external"?n.external?.value:n.value;return r===void 0?[]:Q[e].views.map(o=>({view:o,path:e,kind:t,value:r,state:n.state,preview:n.state!=="APPLIED_VERIFIED"}))}function Je(e,n){if(!Object.prototype.hasOwnProperty.call(Q,n.path))return I(e,"Unknown setting.");let t=ci(e),r=t.fields[n.path],i=()=>++t.revision;switch(n.type){case"edit":{if(n.expectedRevision!==void 0&&n.expectedRevision!==e.revision)return I(e,"The settings changed (revision "+e.revision+") since this edit was prepared; reload and review.");let o=Le(n.path,n.value);return o.ok?r.state==="EXECUTING"?I(e,"An apply is in progress for this setting; it cannot be edited until it ends."):r.external?I(e,"The native side was changed outside ECCO; resolve that first (adopt it or keep the intended value)."):n.source==="intelligence"?o.value===r.value?{ok:!0,settings:e,updates:[]}:(r.proposal={value:o.value,revision:i()},{ok:!0,settings:t,updates:ie(n.path,r,"proposal")}):o.value===r.value&&r.source==="owner"?{ok:!0,settings:e,updates:[]}:(r.value=o.value,r.source="owner",r.revision=i(),r.state=r.observed===o.value?"APPLIED_VERIFIED":"PROPOSED",r.proposal&&r.proposal.value===o.value&&(r.proposal=null),{ok:!0,settings:t,updates:ie(n.path,r,"value")}):I(e,o.error)}case"adopt-proposal":return r.proposal?r.state==="EXECUTING"?I(e,"An apply is in progress for this setting."):r.external?I(e,"Resolve the external native change first."):(r.value=r.proposal.value,r.source="intelligence",r.proposal=null,r.revision=i(),r.state=r.observed===r.value?"APPLIED_VERIFIED":"PROPOSED",{ok:!0,settings:t,updates:ie(n.path,r,"value")}):I(e,"There is no Intelligence proposal to adopt.");case"dismiss-proposal":return r.proposal?(r.proposal=null,i(),{ok:!0,settings:t,updates:[]}):I(e,"There is no Intelligence proposal to dismiss.");case"arm":return r.external?I(e,"Resolve the external native change before arming."):r.state!=="PROPOSED"&&r.state!=="MISMATCH"?I(e,"Only a proposed or mismatched setting can be armed (it is "+r.state+")."):(r.state="ARMED",i(),{ok:!0,settings:t,updates:ie(n.path,r,"value")});case"disarm":return r.state!=="ARMED"?I(e,"Only an armed setting can be disarmed."):(r.state="PROPOSED",i(),{ok:!0,settings:t,updates:ie(n.path,r,"value")});case"begin":return r.external?I(e,"Resolve the external native change before executing."):r.state!=="ARMED"?I(e,"Only an armed setting can start executing."):(r.state="EXECUTING",i(),{ok:!0,settings:t,updates:ie(n.path,r,"value")});case"fail":return r.state!=="EXECUTING"?I(e,"Only an executing setting can fail."):(r.state="MISMATCH",i(),{ok:!0,settings:t,updates:ie(n.path,r,"value")});case"readback":{let o=r.observed,a=n.observed;return a!==null&&!Number.isFinite(a)?I(e,"A read-back must be a finite number or null."):a===o?{ok:!0,settings:e,updates:[]}:(r.observed=a,a===null?r.state==="APPLIED_VERIFIED"&&(r.state="PROPOSED"):a===r.value?(r.state="APPLIED_VERIFIED",r.external=null):r.state==="EXECUTING"?r.state="MISMATCH":(r.state==="APPLIED_VERIFIED"||r.state==="MISMATCH"||o!==null&&o!==a)&&(r.external={value:a,revision:t.revision+1},r.state==="APPLIED_VERIFIED"&&(r.state="MISMATCH")),i(),{ok:!0,settings:t,updates:ie(n.path,r,r.external?"external":"value")})}case"resolve-external":{if(!r.external)return I(e,"There is no external change to resolve.");if(n.choice==="adopt-native"){let o=Le(n.path,r.external.value);if(!o.ok)return I(e,"The native value is outside what ECCO accepts ("+o.error+") and cannot be adopted; keep the intended value.");r.value=r.external.value,r.source="native",r.observed=r.external.value,r.state="APPLIED_VERIFIED"}else r.state="PROPOSED";return r.external=null,r.revision=i(),{ok:!0,settings:t,updates:ie(n.path,r,"value")}}default:return I(e,"Unknown action.")}}function Ln(e,n){let t=Dt.length-1;for(let r of n)t=Math.min(t,Dt.indexOf(e.fields[r].state));return Dt[t]??"MISMATCH"}function ye(e){if(!Array.isArray(e)||e.length!==f.slots)return{ok:!1,why:"the table does not have six slots"};for(let t of e){if(!t||!Oe(t.startMin))return{ok:!1,why:"a slot start is unreadable or off the 5-minute grid"};if(t.source!=="Grid"&&t.source!=="None")return{ok:!1,why:"a slot has an unknown charge source"};if(!Number.isFinite(t.powerW)||!Number.isFinite(t.targetSoc))return{ok:!1,why:"a slot power or target SOC is unreadable"}}let n=0;for(let t=0;t<f.slots;t++){let r=e[t].startMin,i=e[(t+1)%f.slots].startMin,o=W(r,i);if(o<f.minSlotMin)return{ok:!1,why:"slot "+(t+1)+" is shorter than 5 minutes"};n+=o}return n!==1440?{ok:!1,why:"the six starts are not one 24-hour cycle in slot order"}:{ok:!0}}function At(e,n){return e.startMin===n.startMin&&e.powerW===n.powerW&&e.targetSoc===n.targetSoc&&e.source===n.source}function Wn(e,n){return e.length===n.length&&e.every((t,r)=>At(t,n[r]))}var We=1440/5,Fn=e=>e.source+"|"+e.powerW+"|"+e.targetSoc;function di(e){let n=[];for(let t=0;t<We;t++){let r=t*5,i=e[0];for(let o=0;o<e.length;o++){let a=e[o],s=e[(o+1)%e.length];if(W(a.startMin,r)<W(a.startMin,s.startMin)){i=a;break}}n.push({powerW:i.powerW,targetSoc:i.targetSoc,source:i.source,from:null})}return n}function Y(e,n,t,r={}){let i=e.baseline.map(o=>({...o}));return{status:n,reasons:t,slots:i,slotReports:Hn(i,i.map(()=>"native-fallback"),e.observed??null),fallback:!0,edits:[],intervals:[],refused:[],slotsNeeded:0,deferredToAfterClockChange:!1,...r}}function Hn(e,n,t){return e.map((r,i)=>{let o=t&&t.length===e.length?t[i]:null,a=o===null?"PROPOSED":At(o,r)?"APPLIED_VERIFIED":"MISMATCH";return{index:i+1,intended:{...r},origin:n[i],observed:o?{...o}:null,state:a}})}function Vn(e,n){let t=[];return n.forEach((r,i)=>{let o=e&&e.length===n.length?e[i]:null,a=["startMin","powerW","targetSoc","source"];for(let s of a)(o===null||o[s]!==r[s])&&t.push({slot:i+1,field:s,from:o===null?null:o[s],to:r[s]})}),t}function ui(e){return{powerW:e.powerW,targetSoc:e.targetSoc,source:e.action==="charge"?"Grid":"None",from:e.action}}function pi(e){if(e.action!=="charge"&&e.action!=="export")return"unknown action";if(!Oe(e.startMin))return e.action+" start is not on the 5-minute grid";if(!Number.isInteger(e.durationMin)||e.durationMin<f.minSlotMin||e.durationMin%5!==0)return e.action+" duration must be a multiple of 5 minutes, at least 5";if(e.durationMin>=1440)return e.action+" cannot cover the whole day";if(e.action==="export"){if(!Number.isInteger(e.targetSoc)||e.targetSoc<f.stopSocMin||e.targetSoc>f.stopSocMax)return"export Stop SOC must be "+f.stopSocMin+"-"+f.stopSocMax+" %";if(e.powerW<f.exportPowerMin||e.powerW>f.exportPowerMax)return"export power is outside "+f.exportPowerMin+"-"+f.exportPowerMax+" W"}else{if(!Number.isFinite(e.targetSoc)||e.targetSoc<f.chargeTargetMin||e.targetSoc>f.chargeTargetMax)return"charge target SOC is outside "+f.chargeTargetMin+"-"+f.chargeTargetMax+" %";if(e.powerW<f.chargePowerMin||e.powerW>f.chargePowerMax)return"charge power is outside "+f.chargePowerMin+"-"+f.chargePowerMax+" W"}return null}function hi(e,n){let t=0;for(let r=0;r<e.length;r++)At(e[r],n[r])||t++;return t}function Gn(e){let n=e.day??Nn,t=Math.max(5,e.handoverGapMin??5);if(e.transactionOwner)return Y(e,"REFUSED",["Single writer: "+e.transactionOwner+" owns the inverter right now; nothing is compiled until it ends and its restore is verified."]);let r=ye(e.baseline);if(!r.ok)return Y(e,"REFUSED",["The native baseline is not a valid six-slot day: "+r.why+"."]);if(e.observed){let g=ye(e.observed);if(!g.ok)return Y(e,"CONFLICT",["The observed inverter table is not a valid six-slot day: "+g.why+"; reconcile before planning."]);let x=e.lastApplied??e.baseline;if(!Wn(e.observed,x)){let D=Vn(x,e.observed);return Y(e,"CONFLICT",["The inverter table differs from "+(e.lastApplied?"what ECCO last applied":"the owner's baseline")+" ("+D.length+" field(s), first: slot "+D[0].slot+" "+D[0].field+"). It looks edited outside ECCO; review and adopt it or restore before anything is compiled."])}}let i=[],o=e.intervals.filter(g=>g.action==="export"&&e.controlLocked!==!1?(i.push({action:"export",reason:"Control is locked (grid-loss lock): every export start is refused."}),!1):!0);for(let g of o){let x=pi(g);if(x)return Y(e,"REFUSED",["Invalid derived interval: "+x+"."],{refused:i})}if(o.filter(g=>g.action==="charge").length>1||o.filter(g=>g.action==="export").length>1)return Y(e,"REFUSED",["Only one charge and one export interval can be derived per cycle."],{refused:i});let a=o.find(g=>g.action==="charge"),s=o.find(g=>g.action==="export");if(a&&s){let g=W(s.startMin+s.durationMin,a.startMin),x=W(a.startMin+a.durationMin,s.startMin);if(W(a.startMin,s.startMin)<a.durationMin||W(s.startMin,a.startMin)<s.durationMin)return Y(e,"REFUSED",["The export would overlap the charge window; the firmware refuses an export that touches a charge slot."],{refused:i});if(g<t||x<t)return Y(e,"REFUSED",["Fewer than "+t+" minutes between the export and the charge window; time is needed to restore and verify."],{refused:i})}let l=!1;if(In(n)){for(let g of o){let x=re(g.startMin+g.durationMin);(g.action==="export"?On(g.startMin,g.durationMin):g.startMin<180||x<180)&&(l=!0)}if(l)return Y(e,"REFUSED",["Clock-change night: derived changes that start, end or run between 00:00 and 03:00 wait until the night is over; the native table keeps running unchanged."],{refused:i,deferredToAfterClockChange:!0})}let p=di(e.baseline);for(let g of o){let x=ui(g);for(let D=0;D<g.durationMin;D+=5)p[(g.startMin+D)/5%We]={...x}}let c=[];for(let g=0;g<We;g++){let x=p[(g+We-1)%We];Fn(x)!==Fn(p[g])&&c.push(g*5)}c.length===0&&c.push(e.baseline[0].startMin);let d=c.length;if(d>f.slots)return Y(e,"INFEASIBLE",["Six native slots are not enough: this plan needs "+d+" distinct slots (changes at "+c.map(g=>F(g)).join(", ")+") and the inverter has exactly "+f.slots+". Nothing is truncated; the native table stays as it is."],{refused:i,slotsNeeded:d,intervals:Un(o,n)});let v=new Set(c);for(let g of e.baseline){if(c.length>=f.slots)break;v.has(g.startMin)||(c.push(g.startMin),v.add(g.startMin))}for(c.sort((g,x)=>g-x);c.length<f.slots;){let g=-1,x=0;for(let G=0;G<c.length;G++){let B=W(c[G],c[(G+1)%c.length])||1440;B>x&&(x=B,g=G)}let D=re(c[g]+Math.floor(x/2/5)*5);c.push(D),c.sort((G,B)=>G-B)}let b=g=>p[g/5],m=c.map(g=>{let x=b(g);return{startMin:g,powerW:x.powerW,targetSoc:x.targetSoc,source:x.source}}),w=(g,x)=>{let D=W(g,x)||1440;for(let G=0;G<D;G+=5){let B=b(re(g+G)).from;if(B)return B==="charge"?"derived:charge":"derived:export"}return"native-fallback"},P=0,E=1/0;for(let g=0;g<f.slots;g++){let x=m.map((G,B)=>m[(B+g)%f.slots]),D=hi(x,e.baseline);D<E&&(E=D,P=g)}let _=m.map((g,x)=>({...m[(x+P)%f.slots]})),A=m.map((g,x)=>{let D=(x+P)%f.slots;return w(m[D].startMin,m[(D+1)%f.slots].startMin)}),R=ye(_);if(!R.ok)return Y(e,"REFUSED",["Internal check failed ("+R.why+"); the native table stays as it is."],{refused:i});let K=Wn(_,e.baseline);return{status:"OK",reasons:i.map(g=>g.reason),slots:_,slotReports:Hn(_,A,e.observed??null),fallback:K,edits:Vn(e.observed??e.baseline,_),intervals:Un(o,n),refused:i,slotsNeeded:d,deferredToAfterClockChange:!1}}function Un(e,n){return e.map(t=>({action:t.action,startMin:t.startMin,wallMin:t.durationMin,elapsedMin:$e(t.startMin,t.durationMin,n)}))}var le=["hold_battery","skip_tonight","prepare_power_cut"];function Kn(e,n,t,r){if(!le.includes(e))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(!Number.isFinite(n))return{ok:!1,error:"The current time is unknown; an override cannot be started without it.",code:"TIME_UNKNOWN"};let i=t??r.defaultExpiryMin[e];if(typeof i!="number"||!Number.isFinite(i))return{ok:!1,error:"An override needs an expiry; there is no open-ended override.",code:"EXPIRY_MISSING"};if(i<r.minExpiryMin)return{ok:!1,error:"The expiry must be at least "+r.minExpiryMin+" minutes.",code:"EXPIRY_BELOW_MIN"};let o=r.maxExpiryMin[e];if(i>o)return{ok:!1,error:"The expiry can be at most "+o+" minutes for this override.",code:"EXPIRY_ABOVE_CAP"};let a={kind:e,startedAtMin:n,expiresAtMin:n+i};if(e==="prepare_power_cut"){let s=r.powerCutReservePct;if(!Number.isFinite(s)||s<f.reserveMin||s>f.reserveMax)return{ok:!1,error:"The power-cut reserve must be "+f.reserveMin+"-"+f.reserveMax+" %.",code:"POWER_CUT_RESERVE_RANGE"};a.reservePct=s}return{ok:!0,override:a}}var Fe={min_expiry:{min:5,max:60,step:5,unit:"min"},hold_default:{min:5,max:4320,step:5,unit:"min"},hold_cap:{min:5,max:4320,step:5,unit:"min"},skip_until:{min:180,max:1435,step:5,unit:"minute of day"},skip_cap:{min:5,max:2160,step:5,unit:"min"},cut_default:{min:5,max:10080,step:5,unit:"min"},cut_cap:{min:5,max:10080,step:5,unit:"min"},cut_reserve:{min:10,max:100,step:1,unit:"%"},revision:{min:0,max:1e9,step:1,unit:""}},ce=Object.freeze({hold_battery:Fe.hold_cap.max,skip_tonight:Fe.skip_cap.max,prepare_power_cut:Fe.cut_cap.max}),q=Object.freeze({hold_battery:"Hold battery",skip_tonight:"Skip tonight",prepare_power_cut:"Prepare for power cut"}),mi=[{key:"minExpiryMin",bound:"min_expiry",label:"Shortest allowed override"},{key:"holdDefaultMin",bound:"hold_default",label:"Hold battery default"},{key:"holdCapMin",bound:"hold_cap",label:"Hold battery maximum"},{key:"skipUntilMin",bound:"skip_until",label:"Skip tonight ends at"},{key:"skipCapMin",bound:"skip_cap",label:"Skip tonight maximum"},{key:"cutDefaultMin",bound:"cut_default",label:"Prepare for power cut default"},{key:"cutCapMin",bound:"cut_cap",label:"Prepare for power cut maximum"},{key:"cutReservePct",bound:"cut_reserve",label:"Power-cut reserve"}];function J(e){if(typeof e!="number"||!Number.isFinite(e)||e<0)return"unknown";let n=Math.round(e);if(n<60)return n+" min";let t=Math.floor(n/1440),r=Math.floor((n-t*1440)/60),i=n%60,o=[];return t>0&&o.push(t+(t===1?" day":" days")),r>0&&o.push(r+" h"),i>0&&o.push(i+" min"),o.join(" ")}function Bn(e,n){if(e.bound==="skip_until")return F(n);let t=Fe[e.bound];return t.unit==="min"?J(n):n+" "+t.unit}function fi(e,n,t){let r=Fe[e.bound];return typeof n!="number"||!Number.isFinite(n)?(t.push(e.label+" is not set or cannot be read."),null):Number.isInteger(n)?n<r.min?(t.push(e.label+" must be at least "+Bn(e,r.min)+"."),null):n>r.max?(t.push(e.label+" can be at most "+Bn(e,r.max)+"."),null):(n-r.min)%r.step!==0?(t.push(e.label+" moves in steps of "+r.step+(r.unit==="%"?" %":" min")+"."),null):n:(t.push(e.label+" must be a whole number."),null)}function Ct(e,n={}){if(e==null||typeof e!="object")return{ok:!1,reasons:["No override limits are configured, so no override can be started."],codes:["POLICY_UNCONFIRMED"]};let t=[],r=[];e.confirmed!==!0&&t.push("The owner has not confirmed the override limits (the switch is off or cannot be read), so no override can be started.");let i={};for(let c of mi){let d=fi(c,e[c.key],t);d!==null&&(i[c.key]=d)}let o=i.minExpiryMin,a=(c,d,v)=>{o!==void 0&&d!==void 0&&d<o&&t.push(c+" default is shorter than the shortest allowed override."),d!==void 0&&v!==void 0&&d>v&&t.push(c+" default is longer than its maximum.")};a("Hold battery",i.holdDefaultMin,i.holdCapMin),a("Prepare for power cut",i.cutDefaultMin,i.cutCapMin),o!==void 0&&i.skipCapMin!==void 0&&i.skipCapMin<o&&t.push("Skip tonight maximum is shorter than the shortest allowed override.");let s=i.cutReservePct;s!==void 0&&(s<f.reserveMin||s>f.reserveMax)&&t.push("The power-cut reserve must be "+f.reserveMin+"-"+f.reserveMax+" %.");let l=n.currentReservePct;if(typeof l=="number"&&Number.isFinite(l)?s!==void 0&&s<l&&t.push("The power-cut reserve ("+s+" %) is below the current backup reserve ("+l+" %); it would not raise anything."):r.push("The current backup reserve is not known, so the power-cut reserve cannot be compared with it here. An override can only raise a reserve."),t.length>0){let c=[];return e.confirmed!==!0&&c.push("POLICY_UNCONFIRMED"),t.length>c.length&&c.push("POLICY_INVALID"),{ok:!1,reasons:t,codes:c}}return{ok:!0,config:Object.freeze({minExpiryMin:i.minExpiryMin,holdDefaultMin:i.holdDefaultMin,holdCapMin:i.holdCapMin,skipUntilMin:i.skipUntilMin,skipCapMin:i.skipCapMin,cutDefaultMin:i.cutDefaultMin,cutCapMin:i.cutCapMin,cutReservePct:i.cutReservePct}),warnings:r}}function gi(e){return!!e&&(e.deltaMin===0||e.deltaMin===60||e.deltaMin===-60)&&Number.isInteger(e.changeAtMin)&&e.changeAtMin>=0&&e.changeAtMin<1440}function jn(e,n,t){if(!Number.isInteger(e)||e<0||e>=1440)return{ok:!1,error:"The local time is unknown."};if(!Number.isInteger(n)||n<0||n>=1440)return{ok:!1,error:"The end time is not a time of day."};if(!gi(t))return{ok:!1,error:"The clock-change information is not valid."};let r=W(e,n),i=r===0?1440:r,o=$e(e,i,t);return o>0?{ok:!0,wallMin:i,expiryMin:o}:{ok:!1,error:"The end time is not in the future."}}function bi(e,n){let t=NaN;if(n){let r=jn(n.nowWallMin,e.skipUntilMin,n.day);r.ok&&(t=r.expiryMin)}return{minExpiryMin:e.minExpiryMin,defaultExpiryMin:{hold_battery:e.holdDefaultMin,skip_tonight:t,prepare_power_cut:e.cutDefaultMin},maxExpiryMin:{hold_battery:e.holdCapMin,skip_tonight:e.skipCapMin,prepare_power_cut:e.cutCapMin},powerCutReservePct:e.cutReservePct}}var vi=[30,60,120,240,480,720,1440,2880,4320,10080];function zn(e,n,t){let r=e==="hold_battery"?n.holdCapMin:e==="skip_tonight"?n.skipCapMin:n.cutCapMin,i=e==="hold_battery"?n.holdDefaultMin:e==="prepare_power_cut"?n.cutDefaultMin:null,o=new Set;for(let s of vi)s>=n.minExpiryMin&&s<=r&&o.add(s);i!==null&&o.add(i),o.add(r);let a=[...o].filter(s=>s>=n.minExpiryMin&&s<=r).map(s=>({id:"d"+s,label:J(s),expiryMin:s,untilMin:null,isDefault:i===s}));if((e==="hold_battery"||e==="skip_tonight")&&t){let s=jn(t.nowWallMin,n.skipUntilMin,t.day);s.ok&&s.expiryMin>=n.minExpiryMin&&s.expiryMin<=r&&a.push({id:"until",label:"until "+F(n.skipUntilMin),expiryMin:s.expiryMin,untilMin:n.skipUntilMin,isDefault:e==="skip_tonight"})}return a.sort((s,l)=>s.expiryMin-l.expiryMin||s.id.localeCompare(l.id))}function Yn(e,n,t,r,i){if(!r||r.ok!==!0||!r.config)return{ok:!1,error:"The override limits are not valid, so no override can be started."+(r&&r.ok===!1&&r.reasons.length?" "+r.reasons.join(" "):""),code:r&&r.ok===!1&&r.codes&&r.codes[0]||"POLICY_INVALID"};let o=r.config;if(!le.includes(e))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(t!=null&&(typeof t!="number"||!Number.isInteger(t)))return{ok:!1,error:"The expiry must be a whole number of minutes.",code:"EXPIRY_NOT_WHOLE"};if(e==="prepare_power_cut"){let l=i.currentReservePct;if(typeof l!="number"||!Number.isFinite(l))return{ok:!1,error:"The current backup reserve is not known, so it cannot be shown that the power-cut reserve raises it.",code:"RESERVE_UNKNOWN"};if(o.cutReservePct<l)return{ok:!1,error:"The power-cut reserve ("+o.cutReservePct+" %) is below the current backup reserve ("+l+" %); an override never lowers a reserve.",code:"RESERVE_BELOW_CURRENT"}}let a=Kn(e,n,t,bi(o,i.clock));if(!a.ok)return a;let s=a.override.expiresAtMin-a.override.startedAtMin;return!(s>0)||!(s<=ce[e])?{ok:!1,error:"The expiry is beyond the hard ceiling of "+J(ce[e])+".",code:"EXPIRY_ABOVE_CEILING"}:a}var _i=[{key:"minExpiryMin",value:15,why:"Under a quarter hour is almost certainly a mis-tap and would make the plan flicker."},{key:"holdDefaultMin",value:240,why:"Covers an evening of extra use (cooking, guests) without outliving it."},{key:"holdCapMin",value:1440,why:"A forgotten hold costs at most one night of export; two days needs a deliberate restart."},{key:"skipUntilMin",value:420,why:"Skips tonight's export and the overnight charge, then planning resumes before the morning sun."},{key:"skipCapMin",value:1440,why:"Skip is a one-night action; a day is the most it needs."},{key:"cutDefaultMin",value:1440,why:"Most warnings and outages are shorter than a day; extending is a conscious step."},{key:"cutCapMin",value:4320,why:"Matches the design example of 72 h; a raised reserve only costs forgone export."},{key:"cutReservePct",value:80,why:"Hours of essential load while still leaving room for solar; the design example."}],qn=Object.freeze(_i.map(e=>Object.freeze({...e})));var wi=["HIGH","MEDIUM","LOW","INSUFFICIENT"];function Ze(e){return{known:!1,reason:e,state:"PROPOSED"}}function Nt(e,n){if(!e)return Ze("No Intelligence advice is available.");let t=e[n];return t==null?Ze("Intelligence did not provide this."):typeof t!="number"||!Number.isFinite(t)||t<0?Ze("Intelligence provided a value that is not a valid amount."):{known:!0,value:t,state:"PROPOSED",origin:"intelligence",simulated:!1}}var xi=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"];function Xn(e){let{advice:n,settings:t,chargePlan:r}=e,i=[],o="UNKNOWN";n&&typeof n.confidence=="string"&&wi.includes(n.confidence)&&(o=n.confidence);let a={known:o!=="UNKNOWN",level:o,state:"PROPOSED"},s,l=n?.chargeFinishMin;if(typeof l=="number"&&Number.isFinite(l)&&l>=0&&l<1440)s={known:!0,value:Math.round(l),state:"PROPOSED",origin:"intelligence",simulated:!1};else if(r&&(r.status==="OK"||r.status==="BUFFER_TOO_SMALL")&&r.finishNominalMin!==null){let b=t.fields["charge.windowStartMin"].value;s={known:!0,value:re(b+r.finishNominalMin),state:Ln(t,xi),origin:"planner",simulated:!0},r.status==="BUFFER_TOO_SMALL"&&i.push({origin:"planner",text:"Buffer too small: the stress case overruns the charge window (simulated, not measured)."})}else s=Ze(r&&r.status==="NOTHING_TO_CHARGE"?"No overnight charge is expected to be needed.":"No finish time is available from advice or the planner.");let p=t.fields["reserve.backupPct"],c={known:!0,value:p.value,state:p.state,origin:"settings",simulated:!1};if(n&&Array.isArray(n.why))for(let b of n.why.slice(0,8))typeof b=="string"&&b.trim()&&i.push({origin:"advice",text:b.trim().slice(0,200)});let d=t.fields["charge.targetSoc"];i.push({origin:"settings",text:"Charge target "+d.value+" % ("+d.source+", revision "+d.revision+", "+d.state+")."});let v=t.fields["export.stopSoc"];return i.push({origin:"settings",text:"Export stops at "+v.value+" % ("+v.source+", revision "+v.revision+", "+v.state+")."}),i.push({origin:"settings",text:"Backup reserve "+p.value+" % ("+p.source+", "+p.state+")."}),a.known?o!=="HIGH"&&i.push({origin:"advice",text:"Confidence is "+o+": ECCO holds rather than acts on this forecast."}):i.push({origin:"advice",text:"Confidence is unknown, so nothing here is presented as a firm forecast."}),{importKwh:Nt(n,"expectedImportKwh"),exportKwh:Nt(n,"expectedExportKwh"),solarKwh:Nt(n,"expectedSolarKwh"),chargeFinishMin:s,reservePct:c,confidence:a,why:i}}var yi=60,Za=Object.freeze({targetMin:10,targetMax:100,bufferMin:f.bufferMin,bufferMax:f.bufferMax,bufferStep:5,replanMin:5,replanMax:15});var Si=Object.freeze({stepW:100,minW:f.chargePowerMin,hardMaxW:f.chargePowerMax,hysteresisW:500,dwellMin:30,decreaseSlackMin:15,replanMin:10,maxChanges:6,maxSocAgeMin:15,socResolutionPct:1,chargeEff:.95,taperStartSocPct:90,taperEndFraction:.15,topHoldMin:20,demandMarginPct:20,assumedDemandW:2e3,maxHouseholdAgeMin:15,maxDecreaseStepW:f.chargePowerMax}),es=Object.freeze({maxDecreaseStepW:1e3}),Ei=Object.freeze({fallbackPolicy:"KEEP_CURRENT",unknownDemandPolicy:"ASSUME_PROVISIONAL"}),Qn={stepW:["OWNER_SET","the editor's setpoint step"],minW:["OWNER_SET","the editor's minimum charge power"],hardMaxW:["OWNER_SET","the editor's maximum charge power"],hysteresisW:["PROVISIONAL","the owner's confirmation after watching real nights"],dwellMin:["PROVISIONAL","the owner's confirmation and the actuator's settle time"],decreaseSlackMin:["PROVISIONAL","the owner's confirmation after watching real nights"],replanMin:["PROVISIONAL","the owner's confirmation and the actuator's cadence"],maxChanges:["PROVISIONAL","the write budget of a proven actuator"],maxSocAgeMin:["PROVISIONAL","the real update rate of the SOC sensor"],socResolutionPct:["PROVISIONAL","the real resolution of the SOC sensor"],chargeEff:["PROVISIONAL","the measured grid-to-battery energy ratio over several nights"],taperStartSocPct:["MEASURED_REQUIRED","the BMS taper curve measured over several full charges"],taperEndFraction:["MEASURED_REQUIRED","the BMS taper curve measured over several full charges"],topHoldMin:["MEASURED_REQUIRED","the measured time from the last taper step to the BMS finishing the top of charge"],demandMarginPct:["PROVISIONAL","the measured spread of real demand against its forecast"],assumedDemandW:["MEASURED_REQUIRED","the measured overnight household demand profile (unknown today)"],maxHouseholdAgeMin:["PROVISIONAL","the real update rate of the demand and solar sensors"],maxDecreaseStepW:["PROVISIONAL","the owner's confirmation (recommended 1000 W; off by default)"],fallbackPolicy:["PROVISIONAL","the owner's choice"],unknownDemandPolicy:["PROVISIONAL","the owner's choice"],targetSocPct:["OWNER_SET","the owner's charge target"],bufferMin:["OWNER_SET","the owner's finish-early buffer"],gridImportLimitW:["OWNER_SET","the owner's or installer's safe grid import limit (unknown means no headroom constraint)"]};function ki(){let e={},n={...Si,...Ei,targetSocPct:"owner setting",bufferMin:yi,gridImportLimitW:"owner setting or unknown"};for(let t of Object.keys(Qn)){let r=Qn[t];e[t]=Object.freeze({kind:r[0],value:n[t],replacedBy:r[1]})}return Object.freeze(e)}var ts=ki(),ns=2*1440;var Mi=Object.freeze({status:"sensor.ecco_intel_status",charge_target:"sensor.ecco_intel_charge_target",export_event:"sensor.ecco_intel_export_event",pv_tomorrow:"sensor.ecco_intel_pv_tomorrow",fresh:"binary_sensor.ecco_intel_fresh",paused:"input_boolean.ecco_intel_paused"}),Pi=6,Ri=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/,Ti=/^(\d{2}):(\d{2})$/,Di=/^\d{4}-\d{2}-\d{2} (\d{2}):(\d{2}):\d{2}$/;function U(e,n){if(!n)return null;let t=e[n]?.state;return typeof t!="string"||t===""||t==="unavailable"||t==="unknown"?null:t}function M(e,n){let t=U(e,n);if(t===null)return null;let r=t.trim();if(!Ri.test(r))return null;let i=Number(r);return Number.isFinite(i)?i:null}var V=(e,n)=>U(e,n)==="on";function Ai(e){if(e===null)return null;let n=Ti.exec(e.trim());if(!n)return null;let t=Number(n[1]),r=Number(n[2]);return t>23||r>59?null:t*60+r}function Jn(e){if(e===null)return null;let n=Di.exec(e.trim());if(!n)return null;let t=Number(n[1]),r=Number(n[2]);return t>23||r>59?null:t*60+r}function Ci(e,n){let t=`sensor.${e}_ecco_timezone${n}_`;return{time:`${t}time`,power:`${t}power`,soc:`${t}soc`,charge:`${t}charge`}}function Ni(e){return{fpActive:`binary_sensor.${e}_free_power_active`,fpOp:`binary_sensor.${e}_free_power_operation_in_progress`,fpSnapshot:`binary_sensor.${e}_free_power_snapshot_valid`,dgActive:`binary_sensor.${e}_dump_to_grid_active`,dgOp:`binary_sensor.${e}_dump_to_grid_operation_in_progress`,dgSnapshot:`binary_sensor.${e}_dump_to_grid_snapshot_valid`}}function It(e,n){let t=e[n]?.attributes;return t&&typeof t=="object"?t:{}}function Zn(e){return typeof e=="number"&&Number.isFinite(e)?e:null}function Ii(e,n){let t=m=>({advice:null,available:!1,note:m,chargeTargetPct:null}),r=U(e,n.status);if(r===null)return t("The Intelligence advice is not available (its status cannot be read).");if(V(e,n.paused))return t("Intelligence is paused by the owner; it publishes no advice.");if(r!=="OK")return t("Intelligence status is "+r+"; it publishes no figures.");if(U(e,n.fresh)!=="on")return t("The Intelligence advice is not fresh; it is not shown as a forecast.");let i=n.charge_target,o=It(e,i).advice,a=o&&typeof o=="object"&&!Array.isArray(o)?o:{},s=It(e,i).confidence,l=[],p=M(e,i),c=a.binding_constraint;p!==null&&l.push("Charge target advice "+p+" %"+(typeof c=="string"?" (limited by "+c.toLowerCase().replace(/_/g," ")+")":"")+"."),a.conservative_fallback===!0&&l.push("Not enough demand evidence yet, so Intelligence advises keeping the battery well charged.");let d=Zn(a.net_need_kwh);d!==null&&l.push("Net overnight need after solar credit: "+d.toFixed(1)+" kWh.");let v=It(e,i).blockers;if(Array.isArray(v))for(let m of v.slice(0,4)){let w=m&&typeof m=="object"?m.text:null;typeof w=="string"&&w.trim()&&l.push("Blocked: "+w.trim())}return l.push("Import is the grid energy Intelligence plans for the overnight charge; it does not include daytime import."),{advice:{expectedImportKwh:Zn(a.grid_charge_kwh),expectedExportKwh:M(e,n.export_event),expectedSolarKwh:M(e,n.pv_tomorrow),chargeFinishMin:null,confidence:typeof s=="string"?s:null,why:l},available:!0,note:null,chargeTargetPct:p}}function Oi(e,n){let t=[],r=[];for(let o=1;o<=Pi;o++){let a=Ci(n,o),s=Ai(U(e,a.time)),l=M(e,a.power),p=M(e,a.soc),c=U(e,a.charge),d=[];s===null&&d.push("start time"),l===null&&d.push("power"),p===null&&d.push("target SOC"),c!=="Grid"&&c!=="None"&&d.push("charge source"),d.length?r.push("slot "+o+" "+d.join(", ")):t.push({startMin:s,powerW:l,targetSoc:p,source:c})}if(r.length)return{table:null,reason:"The six TOU slots cannot all be read ("+r.join("; ")+"), so no comparison is possible."};let i=ye(t);return i.ok?{table:t,reason:null}:{table:null,reason:"The inverter's six slots are not a valid six-slot day ("+i.why+"), so no comparison is made."}}function oe(e,n,t,r=null){if(n===null)return{value:null,reason:t,observed:null};let i=Le(e,n);return i.ok?{value:i.value,reason:"",observed:r}:{value:null,reason:"The value "+n+" is outside what ECCO accepts ("+i.error+")",observed:null}}function er(e,n){let t=e.plan??{},r=e.free_power,i=e.schedule,o=e.dump_to_grid,a=o?.schedule,s=t.entity_prefix,l={...Mi,...t.advice??{}},p=Ii(n,l),c=s?Oi(n,s):{table:null,reason:"No TOU slot prefix is configured (plan.entity_prefix), so the six slots are not read."},d=c.table,v=d?d.filter(k=>k.source==="Grid"):[],b=v.length===1?v[0]:null,m={};for(let k of xe)m[k]={value:null,reason:"This card has no entity for it.",observed:null};let w=i?Jn(U(n,i.start)):null,P=i?M(n,i.duration):null,E=i?M(n,i.power):r?M(n,r.max_charge_power):null;m["charge.powerW"]=oe("charge.powerW",E,"The charge power cannot be read."),m["charge.windowStartMin"]=oe("charge.windowStartMin",w,i?"The scheduled charge start cannot be read.":"No schedule is configured, so there is no charge window.");let _=null;w!==null&&P!==null&&Number.isInteger(P)&&P>0&&P<1440&&(_=(w+P)%1440),m["charge.windowEndMin"]=oe("charge.windowEndMin",_,i?"The scheduled charge end cannot be worked out (start or duration unreadable, or not on the 5-minute grid).":"No schedule is configured, so there is no charge window."),m["charge.targetSoc"]=oe("charge.targetSoc",b?b.targetSoc:null,"The charge target is not stated: the inverter table has no single grid-charge slot to read it from.",b?b.targetSoc:null),m["charge.bufferMin"]={value:null,reason:"No finish-before-window-end buffer is set by any entity this card reads.",observed:null};let A=o?V(n,o.active):!1,R=a?M(n,a.power):o?M(n,o.export_power):null,K=a?M(n,a.stop_soc):o?M(n,o.stop_soc):null,g=o&&A?M(n,o.active_export_power):null,x=o&&A?M(n,o.active_stop_soc):null,D=a?Jn(U(n,a.start)):null,G=a?M(n,a.duration):o?M(n,o.duration):null;m["export.powerW"]=oe("export.powerW",R,"The export power cannot be read.",g),m["export.stopSoc"]=oe("export.stopSoc",K,"The Stop SOC cannot be read.",x),m["export.startMin"]=oe("export.startMin",D,a?"The scheduled export start cannot be read.":"No export schedule is configured, so there is no export start time."),m["export.durationMin"]=oe("export.durationMin",G,"The export duration cannot be read."),m["reserve.backupPct"]=oe("reserve.backupPct",t.reserve?M(n,t.reserve):null,t.reserve?"The backup reserve cannot be read.":"No backup reserve entity is configured (plan.reserve)."),m["reserve.planningPct"]={value:null,reason:"Intelligence's planning reserve is not read by this card.",observed:null};let B={};for(let k of xe)B[k]=m[k].value!==null?m[k].value:Q[k].min;let X=$n(B,"owner"),Ut=i?V(n,i.armed):!1,tt=r?V(n,r.active):!1,Ht=a?V(n,a.armed):!1,_r=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"],wr=["export.stopSoc","export.powerW","export.startMin","export.durationMin"],nt=(k,N)=>{let $=Je(X,{type:N,path:k});$.ok&&(X=$.settings)},Gt=(k,N,$)=>{for(let L of k)m[L].value!==null&&($?(nt(L,"arm"),nt(L,"begin")):N&&nt(L,"arm"))};Gt(_r,Ut,tt),Gt(wr,Ht,A);for(let k of xe){let N=m[k];if(N.value===null||N.observed===null)continue;let $=Je(X,{type:"readback",path:k,observed:N.observed});$.ok&&(X=$.settings)}let Kt=null;if(p.chargeTargetPct!==null&&m["charge.targetSoc"].value!==null&&p.chargeTargetPct!==m["charge.targetSoc"].value){let k=Je(X,{type:"edit",path:"charge.targetSoc",value:p.chargeTargetPct,source:"intelligence"});k.ok&&(X=k.settings,Kt=X.fields["charge.targetSoc"].proposal?.value??null)}let Bt=xe.map(k=>{let N=m[k],$=X.fields[k],L=Q[k];return{path:k,label:L.label,unit:L.unit,known:N.value!==null,...N.value===null?{reason:N.reason}:{},value:$.value,state:$.state,source:$.source,observed:$.observed,proposal:k==="charge.targetSoc"?Kt:null}}),Ue=[],jt=null;if(d){let k=[],N=ee=>m[ee].value;if(Ut||tt){let ee=N("charge.windowStartMin"),Se=N("charge.powerW"),be=N("charge.targetSoc");ee===null||P===null||Se===null||be===null?Ue.push("The armed charge could not be placed in the table: "+(be===null?"its target SOC is unknown.":"its start, duration or power is unreadable.")):k.push({action:"charge",startMin:ee,durationMin:P,targetSoc:be,powerW:Se})}if(Ht||A){let ee=N("export.startMin"),Se=N("export.powerW"),be=N("export.stopSoc"),Yt=N("export.durationMin");ee===null||Se===null||be===null||Yt===null?Ue.push("The armed export could not be placed in the table: a start, duration, power or Stop SOC is unreadable."):k.push({action:"export",startMin:ee,durationMin:Yt,targetSoc:be,powerW:Se})}let $=null,L=s?Ni(s):null;L&&(V(n,L.fpActive)||V(n,L.fpOp)||V(n,L.fpSnapshot))||tt||r&&(V(n,r.operation_in_progress)||V(n,r.snapshot_valid))?$="Free Power":(L&&(V(n,L.dgActive)||V(n,L.dgOp)||V(n,L.dgSnapshot))||A||o&&(V(n,o.operation_in_progress)||V(n,o.snapshot_valid)))&&($="Dump to Grid");let zt=t.control_lock?U(n,t.control_lock)==="off":!1;!zt&&k.some(ee=>ee.action==="export")&&Ue.push(t.control_lock?"Control is locked or its state is unreadable, so the export is not placed in the table (fail-safe).":"No grid-loss lock state is configured (plan.control_lock), so an export is not placed in the table (fail-safe)."),jt=Gn({baseline:d,intervals:k,observed:d,lastApplied:null,transactionOwner:$,controlLocked:!zt})}let xr=$i(Xn({advice:p.advice,settings:X}),Bt,p);return{settings:X,fields:Bt,tomorrow:xr,tou:{readable:d!==null,reason:c.reason,observed:d,compile:jt,notes:Ue},overrides:[],adviceAvailable:p.available,adviceNote:p.note}}function $i(e,n,t){let r=s=>n.find(l=>l.path===s)?.known===!0,i=e.why.filter(s=>s.origin!=="settings"?!0:s.text.startsWith("Charge target ")?r("charge.targetSoc"):s.text.startsWith("Export stops at ")?r("export.stopSoc"):s.text.startsWith("Backup reserve ")?r("reserve.backupPct"):!0);r("charge.targetSoc")||i.push({origin:"settings",text:"Charge target: unknown (no single grid-charge slot to read it from)."}),r("export.stopSoc")||i.push({origin:"settings",text:"Export Stop SOC: unknown (not readable)."}),r("reserve.backupPct")||i.push({origin:"settings",text:"Backup reserve: unknown (no entity configured or readable)."});let o=s=>!s.known&&t.note?{...s,reason:t.note}:s,a=e.reservePct.known&&!r("reserve.backupPct")?{known:!1,reason:n.find(s=>s.path==="reserve.backupPct")?.reason??"Unknown.",state:"PROPOSED"}:e.reservePct;return{...e,why:i,importKwh:o(e.importKwh),exportKwh:o(e.exportKwh),solarKwh:o(e.solarKwh),chargeFinishMin:o(e.chargeFinishMin),reservePct:a}}var H={confirmed:"input_boolean.ecco_plan_overrides_enabled",revision:"input_number.ecco_plan_revision",min_expiry:"input_number.ecco_plan_policy_min_expiry",hold_default:"input_number.ecco_plan_policy_hold_default",hold_cap:"input_number.ecco_plan_policy_hold_cap",skip_until:"input_datetime.ecco_plan_policy_skip_until",skip_cap:"input_number.ecco_plan_policy_skip_cap",cut_default:"input_number.ecco_plan_policy_cut_default",cut_cap:"input_number.ecco_plan_policy_cut_cap",cut_reserve:"input_number.ecco_plan_policy_cut_reserve",hold_battery_start:"input_datetime.ecco_plan_override_hold_battery_start",hold_battery_expires:"input_datetime.ecco_plan_override_hold_battery_expires",skip_tonight_start:"input_datetime.ecco_plan_override_skip_tonight_start",skip_tonight_expires:"input_datetime.ecco_plan_override_skip_tonight_expires",prepare_power_cut_start:"input_datetime.ecco_plan_override_prepare_power_cut_start",prepare_power_cut_expires:"input_datetime.ecco_plan_override_prepare_power_cut_expires",prepare_power_cut_reserve:"input_number.ecco_plan_override_prepare_power_cut_reserve",hold_battery_expires_epoch:"input_number.ecco_plan_override_hold_battery_expires_epoch",skip_tonight_expires_epoch:"input_number.ecco_plan_override_skip_tonight_expires_epoch",prepare_power_cut_expires_epoch:"input_number.ecco_plan_override_prepare_power_cut_expires_epoch"},Li=/^(\d{2}):(\d{2})(?::(\d{2}))?$/,Wi=/^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2}$/;function Fi(e){if(e===null)return null;let n=Li.exec(e.trim());if(!n)return null;let t=Number(n[1]),r=Number(n[2]),i=n[3]===void 0?0:Number(n[3]);return t>23||r>59||i>59?null:t*60+r+i/60}function Vi(e,n){let t=U(e,n);return t==="on"?!0:t==="off"?!1:null}function tr(e,n,t){let r=U(e,n);if(r===null)return{ok:!1,reason:t+" cannot be read."};let i=Wi.exec(r.trim());if(!i)return{ok:!1,reason:t+" is not a date and time."};let o=e[n]?.attributes?.timestamp;return typeof o!="number"||!Number.isFinite(o)?{ok:!1,reason:t+" has no timestamp, so its moment cannot be placed."}:{ok:!0,min:Math.round(o/60),text:i[1]+" "+i[2]+":"+i[3]}}var nr=4102444800,Ui="Held through the absolute epoch record: the date-and-time record does not show it running (it reads earlier, has ended or cannot be read). Home Assistant follows the later of the two.",Hi="A record of this override cannot be read here, so it is not shown as ended. Home Assistant keeps the hold, and any raised reserve, until a cancel settles it.",Gi="This record is not trusted here (see the problem listed), but Home Assistant keeps the hold, and any raised reserve, while it runs. A cancel ends it.";function Ki(e){let n=Math.floor(e/1440),t=e-n*1440,r=n+719468,i=Math.floor(r/146097),o=r-i*146097,a=Math.floor((o-Math.floor(o/1460)+Math.floor(o/36524)-Math.floor(o/146096))/365),s=o-(365*a+Math.floor(a/4)-Math.floor(a/100)),l=Math.floor((5*s+2)/153),p=s-Math.floor((153*l+2)/5)+1,c=l<10?l+3:l-9,d=a+i*400+(c<=2?1:0),v=b=>(b<10?"0":"")+b;return d+"-"+v(c)+"-"+v(p)+" "+v(Math.floor(t/60))+":"+v(t%60)}function Bi(e,n,t){if(e[n]===void 0)return{ok:!1,absent:!0,reason:t+" absolute expiry record is not installed."};let r=M(e,n);if(r===null)return{ok:!1,reason:t+" absolute expiry record cannot be read."};if(r<0||r>nr)return{ok:!1,reason:t+" absolute expiry record is not a time between 0 and "+nr+" seconds."};let i=Math.ceil(r/60);return{ok:!0,min:i,text:Ki(i)+" UTC"}}function ji(e,n,t){if(e.ok&&n.ok){let r=n.min>e.min,i=r?n.min:e.min;return{read:i>t?"active":"cleared",endMin:i,endFrom:r?"epoch":"datetime"}}return e.ok&&!n.ok&&"absent"in n?{read:e.min>t?"active":"cleared",endMin:e.min,endFrom:"datetime"}:e.ok&&e.min>t?{read:"active",endMin:e.min,endFrom:"datetime"}:n.ok&&n.min>t?{read:"active",endMin:n.min,endFrom:"epoch"}:{read:"unreadable",endMin:null,endFrom:null}}function zi(e,n,t){let r=[],i=[];if(n===null)return t.push("The current time is not known, so stored override records cannot be judged."),{rows:r,records:i};let o=[];for(let a of le){let s=q[a],l=H[a+"_start"],p=H[a+"_expires"],c=H[a+"_expires_epoch"],d=tr(e,p,s+" expiry"),v=Bi(e,c,s);d.ok||t.push(d.reason),v.ok||("absent"in v?o.push(s):t.push(v.reason));let b=ji(d,v,n),m=b.endFrom==="epoch"&&v.ok?v.text:d.ok?d.text:null,w=null;if(b.read==="active"&&b.endMin!==null){let P=b.endMin,E=tr(e,l,s+" start");if(!E.ok)t.push(E.reason+" The record is not trusted.");else{let _=P-E.min;if(!(_>0))t.push(s+" starts at or after its expiry. The record is not trusted.");else if(_>ce[a])t.push(s+" lasts longer than its hard ceiling. The record is not trusted.");else{let A={kind:a,startedAtMin:E.min,expiresAtMin:P},R=!0;if(a==="prepare_power_cut"){let K=M(e,H.prepare_power_cut_reserve);K===null||!Number.isInteger(K)||K<f.reserveMin||K>f.reserveMax?(t.push(s+" has no readable reserve inside "+f.reserveMin+"-"+f.reserveMax+" %. The record is not trusted."),R=!1):A.reservePct=K}R&&(w={override:A,label:s,expiresText:m??"",remainingMin:Math.max(1,P-n),note:b.endFrom==="epoch"?Ui:""})}}}w&&r.push(w),i.push({kind:a,label:s,read:b.read,endMin:b.endMin,endText:b.endMin===null?null:m,note:w?w.note:b.read==="active"?Gi:b.read==="unreadable"?Hi:"",epochMissing:!v.ok&&"absent"in v})}return o.length>0&&t.push("The absolute expiry record of "+o.join(", ")+" is not installed (an older helper package), so "+(o.length===1?"it is":"they are")+" judged by the date-and-time record only."),{rows:r,records:i}}function Yi(e){let n=M(e,H.revision);return n===null?{known:!1,value:null,reason:"The stored plan revision cannot be read."}:!Number.isInteger(n)||n<0?{known:!1,value:null,reason:"The stored plan revision is not a whole number."}:{known:!0,value:n,reason:""}}function qi(e,n,t,r=null){let i=Object.values(H),o=i.filter(m=>e[m]===void 0);if(o.length===i.length)return null;let a=Vi(e,H.confirmed),s={confirmed:a,minExpiryMin:M(e,H.min_expiry),holdDefaultMin:M(e,H.hold_default),holdCapMin:M(e,H.hold_cap),skipUntilMin:Fi(U(e,H.skip_until)),skipCapMin:M(e,H.skip_cap),cutDefaultMin:M(e,H.cut_default),cutCapMin:M(e,H.cut_cap),cutReservePct:M(e,H.cut_reserve)},l=Ct(s,{currentReservePct:t}),p=Ct(s),c=[],{rows:d,records:v}=zi(e,n,c),b=v.filter(m=>m.read!=="cleared"&&!d.some(w=>w.override.kind===m.kind));return{missing:o,confirmed:a,policy:l,startPolicy:p,socPct:r,revision:Yi(e),active:d,records:v,held:b,problems:c,nowMin:n}}function rr(e,n,t){let r=er(e,n),i=r.fields.find(l=>l.path==="reserve.backupPct"),o=e.plan?.battery_soc??e.dump_to_grid?.battery_soc,a=o?M(n,o):null,s=qi(n,t,i&&i.known?i.value:null,a);return s?{...r,overrides:s.active.map(l=>l.override),helpers:s}:{...r,helpers:null}}var Ve=Object.freeze({PROPOSED:{kind:"PROPOSED",label:"Proposed",icon:"mdi:lightbulb-outline",meaning:"Proposed: shown for review, not armed and not applied."},ARMED:{kind:"ARMED",label:"Armed",icon:"mdi:shield-check-outline",meaning:"Armed: scheduled and waiting to start, not yet running."},EXECUTING:{kind:"EXECUTING",label:"Executing",icon:"mdi:progress-clock",meaning:"Executing: a session is running now and no read-back has confirmed this value yet."},APPLIED_VERIFIED:{kind:"APPLIED_VERIFIED",label:"Applied and verified",icon:"mdi:check-circle-outline",meaning:"Applied and verified: a read-back from the system equals this value."},MISMATCH:{kind:"MISMATCH",label:"Mismatch",icon:"mdi:alert-circle-outline",meaning:"Mismatch: what the system reports differs from the intended value."},UNKNOWN:{kind:"UNKNOWN",label:"Unknown",icon:"mdi:help-circle-outline",meaning:"Unknown: this cannot be read, so no value is shown."}}),Xi="SHADOW / advice only. Nothing shown here is applied by this view: it displays what Home Assistant, the inverter and Intelligence report, and it writes nothing.",Qi="Quick overrides: none active. Shown as status only; starting one needs a plan helper that does not exist yet.",Ji="Quick overrides: none active. Shown as status only; starting one needs the guarded start path, which is not installed.",Zi="Status only: nothing in this view starts, cancels or enforces an override. An override can only hold back ECCO's own export starts or raise the reserve ECCO's plan uses; it never writes the inverter's table, does not change the inverter's own reserve and never stops a running session.";function Lt(e,n){return"The battery is at "+Math.round(e)+" percent, below the "+Math.round(n)+" percent reserve. Nothing is charging. Use Charge Battery if you want it filled."}function Wt(e,n){return e.endMin!==null&&e.endText!==null&&n!==null&&e.endMin>n?"Held by Home Assistant until "+e.endText+" (ends in "+J(e.endMin-n)+")":"Held by Home Assistant (a record cannot be read here)"}var eo={HIGH:"High",MEDIUM:"Medium",LOW:"Low",INSUFFICIENT:"Insufficient evidence"},Ot=e=>e.toFixed(1)+" kWh";function $t(e){return Ve[e]}function ir(e){return`${F(e.startMin)} ${e.source==="Grid"?"charge from grid":"no grid charge"}, ${e.powerW} W, to ${e.targetSoc} %`}var to=e=>"time"in Q[e.path];function or(e,n){return to(e)?F(n):e.unit?`${n} ${e.unit}`:String(n)}function no(e){if(!e.known)return{path:e.path,label:e.label,known:!1,text:"Unknown",reason:e.reason??"Not readable.",chip:Ve.UNKNOWN,remarks:[]};let n=[],t=r=>or(e,r);return e.observed!==null&&e.observed!==e.value&&n.push(`The system reports ${t(e.observed)}, not ${t(e.value)}.`),e.proposal!==null&&n.push(`Intelligence suggests ${t(e.proposal)} (not adopted; nothing here changes it).`),e.state==="PROPOSED"&&e.observed===null&&n.push("No read-back is available for this value."),{path:e.path,label:e.label,known:!0,text:or(e,e.value),reason:"",chip:$t(e.state),remarks:n}}function ro(e){let n=e.intended,t=e.observed;if(!t)return null;let r=[];return n.startMin!==t.startMin&&r.push(`start ${F(n.startMin)} intended, ${F(t.startMin)} on the inverter`),n.source!==t.source&&r.push(`charge source ${n.source} intended, ${t.source} on the inverter`),n.powerW!==t.powerW&&r.push(`power ${n.powerW} W intended, ${t.powerW} W on the inverter`),n.targetSoc!==t.targetSoc&&r.push(`target ${n.targetSoc} % intended, ${t.targetSoc} % on the inverter`),r.length?`Slot ${e.index} differs from the inverter: ${r.join("; ")}. It is not applied there, and this view does not apply it.`:null}var io={"native-fallback":"Native (unchanged)","derived:charge":"Derived from the charge plan","derived:export":"Derived from the export plan"},oo={OK:"Compiled",INFEASIBLE:"Does not fit six slots",CONFLICT:"Conflict with a manual change",REFUSED:"Not compiled"};function ao(e){let n=e.tou;if(!n.readable||!n.compile)return{readable:!1,headline:n.reason??"The six slots cannot be read.",statusText:null,reasons:[...n.notes],slots:[],mismatchCount:0};let t=n.compile,r=t.slotReports.map((s,l)=>{let p=t.slotReports[(l+1)%t.slotReports.length],c=s.state==="MISMATCH"?ro(s):null,d=s.state==="APPLIED_VERIFIED"?"APPLIED_VERIFIED":s.state==="MISMATCH"?"MISMATCH":"PROPOSED";return{index:s.index,rangeText:`${F(s.intended.startMin)} to ${F(p.intended.startMin)}`,spanMin:W(s.intended.startMin,p.intended.startMin)||1440,intendedText:ir(s.intended),inverterText:s.observed?ir(s.observed):null,originText:io[s.origin]??s.origin,chip:Ve[d],mismatch:c}}),i=r.filter(s=>s.mismatch!==null).length,o=[...new Set([...t.reasons,...n.notes])],a;return t.status==="OK"&&t.fallback?a="No armed charge or export changes the table: the six slots are as the inverter reports them.":t.status==="OK"?a=`If the armed plan were compiled, ${i} of the six slots would differ from what the inverter reports.`:t.status==="INFEASIBLE"?a="The plan does not fit the inverter's six slots. Nothing is truncated; the native table stays as it is.":t.status==="CONFLICT"?a="The inverter's table looks changed outside ECCO. Nothing is planned until that is reviewed.":a="The plan is not compiled; the native table stays as it is.",{readable:!0,headline:a,statusText:oo[t.status]??t.status,reasons:o,slots:r,mismatchCount:i}}var so={hold_battery:()=>"Intended: ECCO's own scheduled and guarded export starts are held; charging and the inverter table are untouched.",skip_tonight:()=>"Intended: ECCO's own export starts tonight are held; charging continues.",prepare_power_cut:e=>`Intended: the reserve ECCO's plan uses is ${e??"?"} % or more, and ECCO's own export starts are held. The inverter's own reserve is not changed.`};function lo(){let e=(t,r)=>t==="skipUntilMin"?F(r):t==="cutReservePct"?`${r} %`:J(r),n={minExpiryMin:"Shortest allowed override",holdDefaultMin:"Hold battery default",holdCapMin:"Hold battery maximum",skipUntilMin:"Skip tonight ends at",skipCapMin:"Skip tonight maximum",cutDefaultMin:"Prepare for power cut default",cutCapMin:"Prepare for power cut maximum",cutReservePct:"Power-cut reserve"};return qn.map(t=>`${n[t.key]??t.key}: ${e(t.key,t.value)}. ${t.why}`)}function co(e){let n=t=>J(t);return`Limits set by you: ${q.hold_battery} default ${n(e.holdDefaultMin)}, up to ${n(e.holdCapMin)}; ${q.skip_tonight} until ${F(e.skipUntilMin)}, up to ${n(e.skipCapMin)}; ${q.prepare_power_cut} default ${n(e.cutDefaultMin)}, up to ${n(e.cutCapMin)}, reserve ${e.cutReservePct} %. Hard ceilings no setting can exceed: ${n(ce.hold_battery)}, ${n(ce.skip_tonight)}, ${n(ce.prepare_power_cut)}.`}function uo(e){return e.held.length>0?" Home Assistant also holds, or cannot read the record of: "+e.held.map(n=>q[n.kind]).join(", ")+" (see below).":""}function po(e){let n=e.policy,t=e.active.map(i=>({kind:i.override.kind,label:i.label,untilText:`until ${i.expiresText}`,countdownText:`ends in ${J(i.remainingMin)}`,effectText:so[i.override.kind](i.override.reservePct),belowReserve:i.override.kind==="prepare_power_cut"&&typeof i.override.reservePct=="number"&&e.socPct!==null&&e.socPct<i.override.reservePct?Lt(e.socPct,i.override.reservePct):null,note:i.note})),r=e.revision.known?e.revision.value===0?"Plan revision: none recorded yet.":`Plan revision ${e.revision.value} (stored in the plan helper).`:`Plan revision: unknown (${e.revision.reason})`;return{policyOk:n.ok,policyLine:n.ok?co(n.config):"The override limits are not usable, so no override can be started. Nothing falls back to proposed values.",reasons:n.ok?[]:[...n.reasons],warnings:n.ok?[...n.warnings]:[],missing:[...e.missing],proposed:n.ok?[]:lo(),revisionText:r,rows:t,held:e.held.map(i=>({kind:i.kind,label:i.label,text:Wt(i,e.nowMin),note:i.note})),problems:[...e.problems],note:Zi}}function ar(e){let n=e.helpers??null,t=e.tomorrow,r=(o,a,s,l)=>s.known?{key:o,label:a,known:!0,text:l(s.value),reason:"",note:s.simulated?"simulated, not measured":"",chip:$t(s.state)}:{key:o,label:a,known:!1,text:"Unknown",reason:s.reason,note:"",chip:Ve.UNKNOWN},i=[r("import","Expected import",t.importKwh,Ot),r("export","Expected export",t.exportKwh,Ot),r("solar","Expected solar",t.solarKwh,Ot),r("finish","Charge finishes",t.chargeFinishMin,o=>F(o)),r("reserve","Reserve",t.reservePct,o=>`${o} %`)];return i.push(t.confidence.known?{key:"confidence",label:"Confidence",known:!0,text:eo[t.confidence.level]??t.confidence.level,reason:"",note:"",chip:$t(t.confidence.state)}:{key:"confidence",label:"Confidence",known:!1,text:"Unknown",reason:"Intelligence did not state how sure it is.",note:"",chip:Ve.UNKNOWN}),{statusLine:Xi,adviceNote:e.adviceNote,figures:i,why:t.why.map(o=>({origin:o.origin,text:o.text})),settings:e.fields.map(no),tou:ao(e),overridesLine:n?(e.overrides.length===0?Ji:`Quick overrides active: ${e.overrides.map(o=>q[o.kind]).join(", ")} (status only).`)+uo(n):e.overrides.length===0?Qi:`Quick overrides active: ${e.overrides.map(o=>o.kind).join(", ")} (status only).`,overrideBlock:n?po(n):null}}function Ft(e){return u`<span class="plan-chip chip-${e.kind.toLowerCase()}" title=${e.meaning}><ha-icon icon=${e.icon} aria-hidden="true"></ha-icon><span class="plan-chip-text">${e.label}</span></span>`}function ho(e){return u`
    <div class="plan-figure ${e.known?"":"is-unknown"}" data-figure=${e.key}>
      <dt>${e.label}</dt>
      <dd>
        <span class="plan-figure-value">${e.text}</span>
        ${e.note?u`<span class="plan-note">${e.note}</span>`:h}
        ${Ft(e.chip)}
        ${e.known?h:u`<span class="plan-reason">${e.reason}</span>`}
      </dd>
    </div>
  `}function mo(e){return u`
    <li class="plan-setting ${e.known?"":"is-unknown"}" data-setting=${e.path}>
      <span class="plan-setting-label">${e.label}</span>
      <span class="plan-setting-value">${e.text}</span>
      ${Ft(e.chip)}
      ${e.known?e.remarks.map(n=>u`<span class="plan-reason">${n}</span>`):u`<span class="plan-reason">${e.reason}</span>`}
    </li>
  `}function fo(e){return u`
    <li class="plan-setting" data-override=${e.kind}>
      <span class="plan-setting-label">${e.label}</span>
      <span class="plan-setting-value">${e.untilText}</span>
      <span class="plan-note">${e.countdownText}</span>
      <span class="plan-reason">${e.effectText}</span>
      ${e.note?u`<span class="plan-reason" data-override-note>${e.note}</span>`:h}
      ${e.belowReserve?u`<span class="plan-reason plan-below-reserve" data-below-reserve role="note">${e.belowReserve}</span>`:h}
    </li>
  `}function go(e){return u`
    <li class="plan-setting" data-override-held=${e.kind}>
      <span class="plan-setting-label">${e.label}</span>
      <span class="plan-setting-value">${e.text}</span>
      <span class="plan-reason">${e.note}</span>
    </li>
  `}function bo(e){return u`
    <div class="plan-override-block" data-block="overrides">
      ${e.rows.length?u`<ul class="plan-settings">${e.rows.map(fo)}</ul>`:h}${e.held.length?u`<ul class="plan-settings" data-override-held-list>${e.held.map(go)}</ul>`:h}
      <p class="plan-reason" data-override-policy=${e.policyOk?"ok":"unusable"}>${e.policyLine}</p>
      ${e.reasons.length?u`<ul class="plan-reasons">${e.reasons.map(n=>u`<li>${n}</li>`)}</ul>`:h}
      ${e.warnings.length?u`<ul class="plan-reasons">${e.warnings.map(n=>u`<li>${n}</li>`)}</ul>`:h}
      ${e.problems.length?u`<ul class="plan-reasons" data-override-problems>${e.problems.map(n=>u`<li>${n}</li>`)}</ul>`:h}
      ${e.missing.length?u`<p class="plan-reason">Plan helper entities not found: ${e.missing.join(", ")}.</p>`:h}
      ${e.proposed.length?u`
            <details class="plan-why">
              <summary>Proposed values (not in use)</summary>
              <ul>${e.proposed.map(n=>u`<li>${n}</li>`)}</ul>
            </details>
          `:h}
      <p class="plan-reason">${e.revisionText}</p>
      <p class="plan-reason">${e.note}</p>
    </div>
  `}function vo(e){return u`
    <li class="plan-slot ${e.mismatch?"is-mismatch":""}" data-slot=${e.index}>
      <div class="plan-slot-head">
        <span class="plan-slot-name">Slot ${e.index}</span>
        <span class="plan-slot-range">${e.rangeText}</span>
        ${Ft(e.chip)}
      </div>
      <div class="plan-slot-line"><span class="plan-slot-key">Intended</span> ${e.intendedText} <span class="plan-note">${e.originText}</span></div>
      <div class="plan-slot-line"><span class="plan-slot-key">Inverter</span> ${e.inverterText??"not read"}</div>
      ${e.mismatch?u`<p class="plan-mismatch" role="note"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon><span>${e.mismatch}</span></p>`:h}
    </li>
  `}function sr(e,n,t){let r=e.tou,i=t?u`<span class="plan-badge"><ha-icon icon="mdi:shield-check-outline" aria-hidden="true"></ha-icon>Guarded controls</span>`:u`<span class="plan-badge"><ha-icon icon="mdi:eye-outline" aria-hidden="true"></ha-icon>Read only</span>`;return u`
      <h2 class="plan-title">Plan ${i}</h2>
      <p class="plan-statusline" role="status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon><span>${e.statusLine}</span></p>

      <div class="plan-block" data-block="tomorrow">
        <h3 class="plan-heading">Tomorrow's Plan</h3>
        ${e.adviceNote?u`<p class="plan-reason plan-advice-note">${e.adviceNote}</p>`:h}
        <dl class="plan-figures">${e.figures.map(ho)}</dl>
        <details class="plan-why">
          <summary>Why?</summary>
          <ul>${e.why.map(o=>u`<li data-origin=${o.origin}>${o.text}</li>`)}</ul>
        </details>
        <details class="plan-why plan-settings-details">
          <summary>Planned settings</summary>
          <ul class="plan-settings">${e.settings.map(mo)}</ul>
        </details>
        <p class="plan-overrides">${e.overridesLine}</p>${e.overrideBlock?bo(e.overrideBlock):h}${n}
      </div>

      <div class="plan-block" data-block="tou">
        <h3 class="plan-heading">Six-slot TOU timeline${r.statusText?u` <span class="plan-note">${r.statusText}</span>`:h}</h3>
        <p class="plan-tou-headline">${r.headline}</p>
        ${r.reasons.length?u`<ul class="plan-reasons">${r.reasons.map(o=>u`<li>${o}</li>`)}</ul>`:h}
        ${r.slots.length?u`
              <div class="plan-bar" aria-hidden="true">
                ${r.slots.map(o=>u`<span class="plan-seg ${o.mismatch?"is-mismatch":""}" style=${"flex-grow:"+o.spanMin}>${o.index}</span>`)}
              </div>
              <ol class="plan-slots">${r.slots.map(vo)}</ol>
            `:h}
      </div>
    `}function _o(e,n=h){return n!==h?u`
    <section class="plan-section" aria-label="Plan, with guarded controls">${sr(e,n,!0)}</section>
  `:u`
    <section class="plan-section" aria-label="Plan, read only">${sr(e,h,!1)}</section>
  `}function lr(e,n,t,r){if(!e||e.show_plan!==!0)return h;let i=typeof t=="number"&&Number.isFinite(t)?t:Date.now(),o=rr(e,n??{},Math.floor(i/6e4)),a=ar(o);return _o(a,r?r({snap:o,states:n??{},nowMs:i}):h)}var cr=de`
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
`;var Z={last_result:"input_text.ecco_plan_last_result",start_script:"script.ecco_plan_override_start",cancel_script:"script.ecco_plan_override_cancel"};function Vt(e,n,t){let r={kind:e};return n.untilLocal===!0?r.until_local=!0:typeof n.expiryMin=="number"&&(r.expiry_min=n.expiryMin),typeof t=="number"&&(r.expected_revision=t),{domain:"script",service:"turn_on",data:{entity_id:Z.start_script,variables:r}}}function dr(e,n){let t={kind:e};return typeof n=="number"&&(t.expected_revision=n),{domain:"script",service:"turn_on",data:{entity_id:Z.cancel_script,variables:t}}}function ur(e){return/^script\.[a-z0-9_]+$/.test(e)?{domain:"script",service:"turn_on",data:{entity_id:e}}:null}function pr(e,n){if(typeof e!="object"||e===null)return!1;let t=e;if(t.domain!=="script"||t.service!=="turn_on"||typeof t.data!="object"||t.data===null)return!1;let r=t.data;if(Object.keys(t.data).some(a=>a!=="entity_id"&&a!=="variables"))return!1;let i=r.entity_id,o=typeof n=="string"&&n!==""&&i===n;return i!==Z.start_script&&i!==Z.cancel_script&&!o?!1:r.variables===void 0?!0:typeof r.variables!="object"||r.variables===null||o?!1:Object.keys(r.variables).every(a=>a==="kind"||a==="expiry_min"||a==="until_local"||a==="expected_revision")}var wo=["NOT_ACTIVE","REVISION_CONFLICT","REVISION_UNREADABLE","UNKNOWN_KIND"],xo=" Home Assistant keeps the hold, and any raised reserve, until a cancel is confirmed.";function hr(e,n,t){let r=n.data.variables??{},i=le.find(o=>o===r.kind);i!==void 0&&(n.data.entity_id===Z.cancel_script?e[i]={revision:typeof r.expected_revision=="number"?r.expected_revision:null,answer:t}:n.data.entity_id===Z.start_script&&delete e[i])}function yo(e,n,t,r,i,o){if(!t)return null;let a=t.revision;if(a!==null&&r!==null&&r>a+1)return null;let s=a!==null&&r!==null&&r>a,l=i!==t.answer,p=i==="CANCELLED "+e+".",c=i!==null&&wo.some(w=>i.startsWith("REFUSED "+w+" "));if(l&&!p&&!c)return null;if(!s&&!l)return{outcome:"pending",text:"Cancel sent for "+n+". Waiting for Home Assistant to answer: the plan revision and both records are read back before it is called cancelled."};if(o===void 0)return{outcome:"pending",text:"Cancel sent for "+n+". The records cannot be read back because the current time is not known."};let d=o.read==="cleared",v=o.epochMissing?"the date-and-time record reads as ended (the absolute record is not installed)":"both records read as ended";if(d&&s)return{outcome:"confirmed",text:"Cancel confirmed for "+n+": "+v+(r!==null?" (plan revision "+r+")":"")+"."};if(d&&c)return{outcome:"confirmed",text:"Nothing to cancel for "+n+": "+(o.epochMissing?"the date-and-time record already reads as ended (the absolute record is not installed)":"both records already read as ended")+"."};if(d)return{outcome:"not_confirmed",text:"Cancel NOT confirmed for "+n+": "+v+", but the plan revision did not move as a cancel moves it (or cannot be read), so the answer is not taken on trust."};let b=o.read==="active"?"a record still holds it until "+(o.endText??"an unknown time"):"a record cannot be read here",m=c&&!s?"Home Assistant did not carry it out. Its answer was: "+i+" "+b.charAt(0).toUpperCase()+b.slice(1):b;return{outcome:"not_confirmed",text:"Cancel NOT confirmed for "+n+": "+m+"."+xo}}function mr(e){let n=e.snap.helpers;if(!n)return null;let t=Math.floor(e.nowMs/6e4),r=n.revision.known?n.revision.value:null,i=[Z.start_script,Z.cancel_script].filter(c=>e.states[c]===void 0),o=e.snap.fields.find(c=>c.path==="reserve.backupPct"),a=o&&o.known?o.value:null,s=n.startPolicy.ok?n.startPolicy.config:null,l=U(e.states,Z.last_result);return{kinds:le.map(c=>{let d=n.active.find(E=>E.override.kind===c)??null,v=[],b=null;if(!s)b=n.startPolicy.ok?null:n.startPolicy.reasons[0]??"The override limits are not usable.";else{let E=zn(c,s,e.clock),_=E.length?E[0]:null,A=Yn(c,t,_?_.expiryMin:null,n.startPolicy,{clock:e.clock,currentReservePct:a});!A.ok&&(A.code==="RESERVE_UNKNOWN"||A.code==="RESERVE_BELOW_CURRENT")?b=A.error:E.length===0?b="No length fits the owner's limits.":v=E.map(R=>({id:R.id,label:R.label,isDefault:R.isDefault,call:R.untilMin!==null?Vt(c,{untilLocal:!0},r):Vt(c,{expiryMin:R.expiryMin},r)}))}let m=n.held.find(E=>E.kind===c)??null,w=d||null,P=c==="prepare_power_cut"&&w&&typeof w.override.reservePct=="number"&&n.socPct!==null&&n.socPct<w.override.reservePct?Lt(n.socPct,w.override.reservePct):null;return{kind:c,label:q[c],active:d!==null,activeText:d?"Active until "+d.expiresText+" (ends in "+J(d.remainingMin)+")":m?Wt(m,t):null,held:m!==null,note:(d?d.note:m?m.note:"")||null,readback:yo(c,q[c],e.cancels?.[c],r,l,n.records.find(E=>E.kind===c)),choices:v,blockedReason:b,cancel:d||m?dr(c,r):null,belowReserve:P}}),lastResult:l,missingScripts:i}}function So(e,n){if(typeof e!="number"||!Number.isFinite(e))return null;let r=(p=>((Math.floor(p/6e4)-n(p))%1440+1440)%1440)(e),i=n(e),o=i-n(e+864e5);if(o===0)return{nowWallMin:r,day:{changeAtMin:0,deltaMin:0}};if(o!==60&&o!==-60)return null;let a=e,s=e+864e5;for(;s-a>6e4;){let p=Math.floor((a+s)/2);n(p)===i?a=p:s=p}let l=((Math.floor(s/6e4)-i)%1440+1440)%1440;return{nowWallMin:r,day:{changeAtMin:l,deltaMin:o}}}function fr(e){return So(e,n=>new Date(n).getTimezoneOffset())}var Eo={hold_battery:"Holds back ECCO's own scheduled and guarded export starts. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",skip_tonight:"Holds back ECCO's own scheduled and guarded export starts tonight. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",prepare_power_cut:"Sets the reserve ECCO's plan uses to the larger of your own reserve and the power-cut reserve, and holds back ECCO's own export starts. It does not change the inverter's own reserve and does not stop the house using the battery. It does not charge the battery."},ko="Partial protection only: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant or by an assistant. These overrides and the reserve protect ECCO's own starts and this card, not an administrator, an assistant or a press of the dongle's own button, and their helpers are plain helpers that an administrator or assistant can write. Binding the Start button needs a firmware gate (a flash, approved separately).";function Mo(e,n){return u`
    <div class="plan-control" data-control=${e.kind}>
      <div class="plan-control-head">
        <span class="plan-setting-label">${e.label}</span>
        ${e.activeText?e.held?u`<span class="plan-setting-value" data-control-held>${e.activeText}</span>`:u`<span class="plan-setting-value" data-control-active>${e.activeText}</span>`:h}
      </div>
      <p class="plan-reason">${Eo[e.kind]??""}</p>
      ${e.note?u`<p class="plan-reason" data-control-note role="note">${e.note}</p>`:h}
      ${e.belowReserve?u`<p class="plan-reason plan-below-reserve" data-below-reserve role="note">${e.belowReserve}</p>`:h}
      ${e.blockedReason?u`<p class="plan-reason" data-control-blocked>${e.blockedReason}</p>`:h}
      <div class="plan-control-buttons">
        ${e.choices.length?u`<span class="plan-note">${e.active?"Start again for":"Start for"}</span>`:h}
        ${e.choices.map(t=>u`<button type="button" class="plan-control-btn ${t.isDefault?"is-default":""}" data-choice=${t.id}
            aria-label=${e.label+": start for "+t.label} @click=${()=>n(t.call)}>${t.label}</button>`)}
        ${e.cancel?u`<button type="button" class="plan-control-btn is-cancel" data-cancel aria-label=${"Cancel "+e.label} @click=${()=>n(e.cancel)}>Cancel</button>`:h}
      </div>
      ${e.readback?u`<p class="plan-reason plan-readback" data-readback=${e.readback.outcome} role="status">${e.readback.text}</p>`:h}
    </div>
  `}function Po(e,n){return u`
    <div class="plan-controls" data-block="controls">
      <h3 class="plan-heading">Quick overrides</h3>
      <p class="plan-reason">They hold back ECCO's own export starts and, for Prepare for power cut, set the reserve ECCO's plan uses. They do not change the inverter's own reserve or any inverter setting, do not stop the house using the battery and never charge it. Home Assistant checks every one against your limits again and may refuse it.</p>
      <p class="plan-reason plan-limitation" data-plan-limitation role="note">${ko}</p>
      ${e.missingScripts.length?u`<p class="plan-reason" data-controls-missing>The guarded scripts were not found (${e.missingScripts.join(", ")}), so no override can be started or cancelled here.</p>`:e.kinds.map(t=>Mo(t,n))}
      ${e.lastResult?u`<p class="plan-reason plan-result" data-plan-result role="status">Last answer: ${e.lastResult}</p>`:h}
    </div>
  `}var gr={};function br(e){return({snap:n,states:t,nowMs:r})=>{let i=mr({snap:n,states:t,nowMs:r,clock:fr(r),cancels:gr});return i?Po(i,o=>{hr(gr,o,i.lastResult),e(o)}):h}}var vr=de`
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
  .plan-readback[data-readback="confirmed"] {
    color: var(--eaa-ok);
  }
  .plan-readback[data-readback="not_confirmed"] {
    color: var(--eaa-fault);
  }
`;var et=4e3,Ro=1e3,T=class extends se{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:ft,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(t){if(!t||typeof t!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!t.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=t}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(t){return!!this._config}willUpdate(){let t=this._config?.free_power;if(t){this._pendingPower!==void 0&&S(this._entityState(t.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&S(this._entityState(t.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let o=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),s=y(this._entityState(t.operation_in_progress)),l=this._entityState(t.status),p=qe({active:o,armed:a,operationInProgress:s,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==p&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=p}let r=this._config?.schedule;r&&(this._pendingSchedulePower!==void 0&&S(this._entityState(r.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&S(this._entityState(r.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&S(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&S(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&S(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let o=i.schedule;o&&(this._pendingDumpSchedulePower!==void 0&&S(this._entityState(o.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&S(this._entityState(o.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&S(this._entityState(o.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let a=y(this._entityState(i.active)),s=y(this._entityState(i.write_enable)),l=y(this._entityState(i.operation_in_progress)),p=y(this._entityState(i.snapshot_valid)),c=this._entityState(i.status),d=Xe({active:a,armed:s,operationInProgress:l,snapshotValid:p,statusText:c});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==d&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=d}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let o=this._trackSummary();kn(o.fp.state,o.dump.state)&&(this._track=wt(o.fp.state,o.dump.state))}}updated(){let t=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();t&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},Ro):!t&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let t=this._config?.free_power;return t?y(this._entityState(t.active))===!0:!1}_scheduleArmed(){let t=this._config?.schedule;return t?y(this._entityState(t.armed))===!0:!1}_dumpActive(){let t=this._config?.dump_to_grid;return t?y(this._entityState(t.active))===!0:!1}_dumpScheduleArmed(){let t=this._config?.dump_to_grid?.schedule;return t?y(this._entityState(t.armed))===!0:!1}_freePowerVisualStateForInterlock(){let t=this._config?.free_power;if(!t||!this.hass)return null;let r=y(this._entityState(t.active)),i=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),a=this._entityState(t.status);return qe({active:r,armed:i,operationInProgress:o,statusText:a})}_dumpVisualStateForInterlock(){let t=this._config?.dump_to_grid;if(!t||!this.hass)return null;let r=y(this._entityState(t.active)),i=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),a=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status);return Xe({active:r,armed:i,operationInProgress:o,snapshotValid:a,statusText:s})}_entityState(t){if(!(!t||!this.hass))return this.hass.states[t]?.state}_entity(t){if(!(!t||!this.hass))return this.hass.states[t]}_moreInfo(t){t&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:t},bubbles:!0,composed:!0}))}_callService(t,r,i){this.hass?.callService&&this.hass.callService(t,r,i)}_callServiceObj(t){this._callService(t.domain,t.service,t.data)}render(){if(!this._config)return u``;let t=this._config.title??ft;return this._config.layout==="tabbed"?this._renderTabbed(t):u`
""")),
    (_blk(r"""
      <ha-card>
        <h1 class="card-title">${e}</h1>
        <div class="actions-grid">
"""),
     _blk(r"""
      <ha-card>
        <h1 class="card-title">${t}</h1>
        <div class="actions-grid">
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
    `}_renderPlan(){return lr(this._config,this.hass?.states,void 0,br(t=>this._callPlanService(t)))}_callPlanService(t){pr(t,this._config?.dump_to_grid?.guarded_start)&&this._callService(t.domain,t.service,t.data)}_pressDumpStart(t){if(t.guarded_start!==void 0&&t.guarded_start!==""){let r=ur(t.guarded_start);r&&this._callPlanService(r);return}this._callService("button","press",{entity_id:t.start})}_trackSummary(){let t=this._freePowerVisualStateForInterlock(),r=this._dumpVisualStateForInterlock(),i={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},o=this._config?.free_power;if(t!==null&&o){let l=this._config?.schedule,p=l?kt(t,xt({armed:y(this._entityState(l.armed))})):t,c=Ce(t,r)?"interlocked":p;i={state:c,pill:c,label:this._labelFor(c),statusText:this._entityState(o.status)}}let a=this._config?.dump_to_grid,s=a&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(r!==null&&a){let l=a.schedule,p=bt(r,l?y(this._entityState(l.armed)):null),c=Ce(r,t)?"interlocked":p;s={state:c,pill:c,label:vt(c),statusText:this._entityState(a.status)}}return{fp:i,dump:s}}_selectTrack(t){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=t}_renderTabbed(t){let r=this._trackSummary(),i=this._track??wt(r.fp.state,r.dump.state),o=i==="free_power"?"dump_to_grid":"free_power",a=i==="free_power"?r.dump:r.fp,s=Pn(Mn(a.state)),l=s==="fault"?"mdi:alert-circle-outline":s==="warning"?"mdi:alert-outline":"mdi:information-outline";return u`
""")),
    (_blk(r"""
          <h1 class="card-title">${e}</h1>
"""),
     _blk(r"""
          <h1 class="card-title">${t}</h1>
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
        ${s?u`
              <div class="track-alert track-alert-${s}" role="status">
""")),
    (_blk(r"""
                <div class="track-alert-text">${bt(gt(n),s.label,s.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(n)}>Show</button>
"""),
     _blk(r"""
                <div class="track-alert-text">${Tn(Rn(o),a.label,a.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(o)}>Show</button>
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
    `}_renderFreePowerTile(){let t=this._config?.free_power;if(!t||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let r=y(this._entityState(t.active)),i=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),a=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=qe({active:r,armed:i,operationInProgress:o,statusText:s});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let p=this._config?.schedule,c=p?y(this._entityState(p.armed)):null,d=xt({armed:c}),v=p?kt(l,d):l,b=this._dumpVisualStateForInterlock(),m=Ce(l,b),w=m?"interlocked":v,P=m?_t("Dump to Grid",b):void 0,E=this._entity(t.max_charge_power),_=this._entity(t.duration),A=this._pendingPower??S(E?.state),R=this._pendingDuration??S(_?.state),K=this._iconFor(w),g=this._labelFor(w);return u`
      <div class="tile free-power-tile state-${w}">
""")),
    (_blk(r"""
            <ha-icon class="tile-icon" icon=${de}></ha-icon>
"""),
     _blk(r"""
            <ha-icon class="tile-icon" icon=${K}></ha-icon>
""")),
    (_blk(r"""
          <span class="state-pill state-${k}">${ce}</span>
"""),
     _blk(r"""
          <span class="state-pill state-${w}">${g}</span>
""")),
    (_blk(r"""
          ${d&&p==="armed"?this._renderScheduleBanner(d):h}
          ${w?this._renderInterlockBanner($):h}
"""),
     _blk(r"""
          ${p&&d==="armed"?this._renderScheduleBanner(p):h}
          ${m?this._renderInterlockBanner(P):h}
""")),
    (_blk(r"""
          ${this._renderFreePowerBody(l,{fp:e,schedule:d,statusText:o,snapshotValid:s,interlocked:w,stagedPowerW:U,stagedDurationMin:S,stagedPowerEntity:D,stagedDurationEntity:b})}
"""),
     _blk(r"""
          ${this._renderFreePowerBody(l,{fp:t,schedule:p,statusText:s,snapshotValid:a,interlocked:m,stagedPowerW:A,stagedDurationMin:R,stagedPowerEntity:E,stagedDurationEntity:_})}
""")),
    (_blk(r"""
    `}_iconFor(e){if(e==="scheduled")return"mdi:calendar-clock";if(e==="interlocked")return"mdi:lock-outline";switch(e){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":nt(e)}_renderInterlockBanner(e){return u`
"""),
     _blk(r"""
    `}_iconFor(t){if(t==="scheduled")return"mdi:calendar-clock";if(t==="interlocked")return"mdi:lock-outline";switch(t){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(t){return t==="scheduled"?"Scheduled":t==="interlocked"?"Interlocked":gn(t)}_renderInterlockBanner(t){return u`
""")),
    (_blk(r"""
        <div class="interlock-banner-text">${e}</div>
"""),
     _blk(r"""
        <div class="interlock-banner-text">${t}</div>
""")),
    (_blk(r"""
    `}_renderFreePowerUnavailable(e){return u`
"""),
     _blk(r"""
    `}_renderFreePowerUnavailable(t){return u`
""")),
    (_blk(r"""
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
"""),
     _blk(r"""
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${t}</p>
      </div>
""")),
    (_blk(r"""
    `}_renderFreePowerBody(e,t){switch(e){case"active":return this._renderActiveBody(t);case"busy":return this._renderBusyBody(t.statusText,t.fp.status);case"deferred":return this._renderDeferredBody(t.statusText,t.fp.status);case"recovery_attention":return this._renderAttentionBody(t);default:return this._renderReadyOrArmedBody(e,t)}}_renderReadyOrArmedBody(e,t){let i=!!t.schedule,n=i?this._mode:"now";return u`
"""),
     _blk(r"""
    `}_renderFreePowerBody(t,r){switch(t){case"active":return this._renderActiveBody(r);case"busy":return this._renderBusyBody(r.statusText,r.fp.status);case"deferred":return this._renderDeferredBody(r.statusText,r.fp.status);case"recovery_attention":return this._renderAttentionBody(r);default:return this._renderReadyOrArmedBody(t,r)}}_renderReadyOrArmedBody(t,r){let i=!!r.schedule,o=i?this._mode:"now";return u`
""")),
    (_blk(r"""
      ${n==="later"&&t.schedule?this._renderLaterPanel(t.schedule):this._renderNowPanel(e,t)}
    `}_renderModeSelector(){let e=this._mode==="now";return u`
"""),
     _blk(r"""
      ${o==="later"&&r.schedule?this._renderLaterPanel(r.schedule):this._renderNowPanel(t,r)}
    `}_renderModeSelector(){let t=this._mode==="now";return u`
""")),
    (_blk(r"""
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._mode="now"}
"""),
     _blk(r"""
          role="tab"
          class="mode-tab ${t?"is-active":""}"
          aria-selected=${t}
          @click=${()=>this._mode="now"}
""")),
    (_blk(r"""
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._mode="later"}
"""),
     _blk(r"""
          role="tab"
          class="mode-tab ${t?"":"is-active"}"
          aria-selected=${!t}
          @click=${()=>this._mode="later"}
""")),
    (_blk(r"""
    `}_renderNowPanel(e,t){let i=e==="armed",n=Q(it(e),t.interlocked),s=Q(at(e),t.interlocked);return u`
"""),
     _blk(r"""
    `}_renderNowPanel(t,r){let i=t==="armed",o=Ne(mn(t),r.interlocked),a=Ne(fn(t),r.interlocked);return u`
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingPower=o,onCommit:o=>this._commitNumber("power",o,t.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDuration=o,onCommit:o=>this._commitNumber("duration",o,t.fp.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:r.interlocked,onPreview:s=>this._pendingPower=s,onCommit:s=>this._commitNumber("power",s,r.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:r.interlocked,onPreview:s=>this._pendingDuration=s,onCommit:s=>this._commitNumber("duration",s,r.fp.duration)})}
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
          ?disabled=${!a}
          @click=${()=>this._toggleArm(r.fp.write_enable,i)}
""")),
    (_blk(r"""
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.fp.start})}
"""),
     _blk(r"""
          ?disabled=${!o}
          @click=${()=>this._callService("button","press",{entity_id:r.fp.start})}
""")),
    (_blk(r"""
    `}_renderLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.status),c=this._entityState(e.last_result),p=this._pendingScheduleDuration??f(o?.state),y=this._pendingSchedulePower??f(l?.state),_=d?.attributes?.effective_power_limit_w,w=typeof _=="number"?_:f(typeof _=="string"?_:void 0),k=this._numericAttr(l?.attributes?.max,8e3),$=yt(k,w),D=Pe(c),b=Ce(c),U=!i&&s!==null&&s.getTime()>this._nowMs;return u`
"""),
     _blk(r"""
    `}_renderLaterPanel(t){let r=y(this._entityState(t.armed)),i=Et(r),o=this._entityState(t.start),a=fe(o),s=this._entity(t.duration),l=this._entity(t.power),p=this._entity(t.status),c=this._entityState(t.last_result),d=this._pendingScheduleDuration??S(s?.state),v=this._pendingSchedulePower??S(l?.state),b=p?.attributes?.effective_power_limit_w,m=typeof b=="number"?b:S(typeof b=="string"?b:void 0),w=this._numericAttr(l?.attributes?.max,8e3),P=An(w,m),E=yt(c),_=St(c),A=!i&&a!==null&&a.getTime()>this._nowMs;return u`
""")),
    (_blk(r"""
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
"""),
     _blk(r"""
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${a?this._toDatetimeLocalValue(a):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
""")),
    (_blk(r"""
          @change=${S=>this._handleScheduleStartChange(e.start,S.target.value)}
"""),
     _blk(r"""
          @change=${R=>this._handleScheduleStartChange(t.start,R.target.value)}
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:$,formatValue:T,disabled:i||!l,onPreview:S=>this._pendingSchedulePower=S,onCommit:S=>this._commitScheduleNumber("power",S,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:S=>this._pendingScheduleDuration=S,onCommit:S=>this._commitScheduleNumber("duration",S,e.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:v,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:P,formatValue:ne,disabled:i||!l,onPreview:R=>this._pendingSchedulePower=R,onCommit:R=>this._commitScheduleNumber("power",R,t.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:d,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:i||!s,onPreview:R=>this._pendingScheduleDuration=R,onCommit:R=>this._commitScheduleNumber("duration",R,t.duration)})}
""")),
    (_blk(r"""
      ${c?u`<p class="firmware-note ${D||b?"is-warning":""}">${c}</p>`:h}
"""),
     _blk(r"""
      ${c?u`<p class="firmware-note ${E||_?"is-warning":""}">${c}</p>`:h}
""")),
    (_blk(r"""
          ?disabled=${i||!U}
          @click=${()=>this._callServiceObj(Me(e.armed))}
"""),
     _blk(r"""
          ?disabled=${i||!A}
          @click=${()=>this._callServiceObj(Mt(t.armed))}
""")),
    (_blk(r"""
    `}_renderScheduleBanner(e){let t=this._entityState(e.start),i=M(t),n=f(this._entityState(e.duration)),s=f(this._entityState(e.power)),o=i?J(i.getTime(),this._nowMs):null;return u`
"""),
     _blk(r"""
    `}_renderScheduleBanner(t){let r=this._entityState(t.start),i=fe(r),o=S(this._entityState(t.duration)),a=S(this._entityState(t.power)),s=i?Ie(i.getTime(),this._nowMs):null;return u`
""")),
    (_blk(r"""
            ${i?Ve(i):"--"} • ${T(s)} • ${F(n)}
          </div>
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Fe(e.cancel))}
"""),
     _blk(r"""
            ${i?Tt(i):"--"} • ${ne(a)} • ${ge(o)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pt(t.cancel))}
""")),
    (_blk(r"""
    `}_toDatetimeLocalValue(e){let t=i=>i.toString().padStart(2,"0");return`${e.getFullYear()}-${t(e.getMonth()+1)}-${t(e.getDate())}T${t(e.getHours())}:${t(e.getMinutes())}`}_handleScheduleStartChange(e,t){if(!t)return;let i=new Date(t);Number.isNaN(i.getTime())||this._callServiceObj(vt(e,wt(i)))}_commitScheduleNumber(e,t,i){e==="power"?this._pendingSchedulePower=t:this._pendingScheduleDuration=t,this._callServiceObj(Ie(i,t))}_renderActiveBody(e){let t=this._entityState(e.fp.ends_at),i=M(t),n=i?J(i.getTime(),this._nowMs):null;return u`
      <div class="active-hero">
        <div class="active-hero-time">${n??"--:--"}</div>
"""),
     _blk(r"""
    `}_toDatetimeLocalValue(t){let r=i=>i.toString().padStart(2,"0");return`${t.getFullYear()}-${r(t.getMonth()+1)}-${r(t.getDate())}T${r(t.getHours())}:${r(t.getMinutes())}`}_handleScheduleStartChange(t,r){if(!r)return;let i=new Date(r);Number.isNaN(i.getTime())||this._callServiceObj(Dn(t,Cn(i)))}_commitScheduleNumber(t,r,i){t==="power"?this._pendingSchedulePower=r:this._pendingScheduleDuration=r,this._callServiceObj(Rt(i,r))}_renderActiveBody(t){let r=this._entityState(t.fp.ends_at),i=fe(r),o=i?Ie(i.getTime(),this._nowMs):null;return u`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
""")),
    (_blk(r"""
        ${T(e.stagedPowerW)} target • ends ${i?this._formatClock(i):t??"--"}
"""),
     _blk(r"""
        ${ne(t.stagedPowerW)} target • ends ${i?this._formatClock(i):r??"--"}
""")),
    (_blk(r"""
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(e.fp)}
      ${this._renderEndRestoreButton(e.fp.end_restore,"End & Restore Now",!1,$e("active"))}
    `}_renderBusyBody(e,t){return u`
"""),
     _blk(r"""
        <ha-icon icon=${t.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${t.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(t.statusText,t.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(t.fp)}
      ${this._renderEndRestoreButton(t.fp.end_restore,"End & Restore Now",!1,gt("active"))}
    `}_renderBusyBody(t,r){return u`
""")),
    (_blk(r"""
          ${this._renderTransitionDetail(e??"Free Power is mid-transaction.",t)}
"""),
     _blk(r"""
          ${this._renderTransitionDetail(t??"Free Power is mid-transaction.",r)}
""")),
    (_blk(r"""
    `}_renderDeferredBody(e,t){return u`
"""),
     _blk(r"""
    `}_renderDeferredBody(t,r){return u`
""")),
    (_blk(r"""
          ${this._renderTransitionDetail(e??"Modbus bus busy - the watchdog will retry.",t)}
"""),
     _blk(r"""
          ${this._renderTransitionDetail(t??"Modbus bus busy - the watchdog will retry.",r)}
""")),
    (_blk(r"""
    `}_renderAttentionBody(e){let t=ut({statusText:e.statusText,snapshotValid:e.snapshotValid});return u`
"""),
     _blk(r"""
    `}_renderAttentionBody(t){let r=yn({statusText:t.statusText,snapshotValid:t.snapshotValid});return u`
""")),
    (_blk(r"""
          ${this._renderTransitionDetail(e.statusText??"Free Power requires operator attention.",e.fp.status)}
"""),
     _blk(r"""
          ${this._renderTransitionDetail(t.statusText??"Free Power requires operator attention.",t.fp.status)}
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
      ${r.actionable?this._renderEndRestoreButton(t.fp.end_restore,r.actionLabel??"End & Restore Now",r.secondary,gt("recovery_attention")):h}
    `}_renderTransitionDetail(t,r){return u`
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
      >
        ${e}
      </div>
"""),
     _blk(r"""
      >
        ${t}
      </div>
""")),
    (_blk(r"""
    `}_renderStatusLine(e,t,i){return!(i?.alwaysShow||!!e&&e!=="Inactive")||!e?h:u`
"""),
     _blk(r"""
    `}_renderStatusLine(t,r,i){return!(i?.alwaysShow||!!t&&t!=="Inactive")||!t?h:u`
""")),
    (_blk(r"""
        @click=${()=>this._moreInfo(t)}
        @keydown=${s=>{(s.key==="Enter"||s.key===" ")&&(s.preventDefault(),this._moreInfo(t))}}
"""),
     _blk(r"""
        @click=${()=>this._moreInfo(r)}
        @keydown=${a=>{(a.key==="Enter"||a.key===" ")&&(a.preventDefault(),this._moreInfo(r))}}
""")),
    (_blk(r"""
      >
        ${e}
      </p>
"""),
     _blk(r"""
      >
        ${t}
      </p>
""")),
    (_blk(r"""
    `}_renderDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
"""),
     _blk(r"""
    `}_renderDiagnosticsDetails(t){let r=[],i=(o,a)=>{let s=S(this._entityState(a));s!==null&&r.push({label:o,value:s.toString()})};return i("Starts",t.start_attempts),i("Started OK",t.start_successes),i("Restored OK",t.restore_successes),i("Failures",t.failures),r.length===0?h:u`
""")),
    (_blk(r"""
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(e,t,i,n){let s=this._confirmEndRestore;return u`
"""),
     _blk(r"""
          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(t,r,i,o){let a=this._confirmEndRestore;return u`
""")),
    (_blk(r"""
        class="end-restore-button ${i?"secondary":""} ${s?"confirming":""}"
        ?disabled=${!n}
        @click=${()=>this._handleEndRestoreClick(e)}
"""),
     _blk(r"""
        class="end-restore-button ${i?"secondary":""} ${a?"confirming":""}"
        ?disabled=${!o}
        @click=${()=>this._handleEndRestoreClick(t)}
""")),
    (_blk(r"""
        ${s?"Tap again to End & Restore":t}
        ${s?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
"""),
     _blk(r"""
        ${a?"Tap again to End & Restore":r}
        ${a?u`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:h}
""")),
    (_blk(r"""
    `}_handleEndRestoreClick(e){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},le);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:e})}_toggleArm(e,t){this._callService("switch",t?"turn_off":"turn_on",{entity_id:e})}_commitNumber(e,t,i){e==="power"?this._pendingPower=t:this._pendingDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_commitDumpNumber(e,t,i){e==="power"?this._pendingDumpPower=t:e==="stop_soc"?this._pendingDumpStopSoc=t:this._pendingDumpDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_handleEndDumpClick(e){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},le);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:e})}_numericAttr(e,t){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"){let i=f(e);if(i!==null)return i}return t}_formatClock(e){let t=e.getHours().toString().padStart(2,"0"),i=e.getMinutes().toString().padStart(2,"0");return`${t}:${i}`}_renderNumberControl(e){let t=e.entity?.attributes??{},i=this._numericAttr(t.min,e.fallbackMin),n=e.maxOverride??this._numericAttr(t.max,e.fallbackMax),s=this._numericAttr(t.step,e.fallbackStep),o=e.value??i,l=e.disabled??!e.entity,d=n>i?Math.max(0,Math.min(100,(o-i)/(n-i)*100)):0;return u`
"""),
     _blk(r"""
    `}_handleEndRestoreClick(t){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},et);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:t})}_toggleArm(t,r){this._callService("switch",r?"turn_off":"turn_on",{entity_id:t})}_commitNumber(t,r,i){t==="power"?this._pendingPower=r:this._pendingDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_commitDumpNumber(t,r,i){t==="power"?this._pendingDumpPower=r:t==="stop_soc"?this._pendingDumpStopSoc=r:this._pendingDumpDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_handleEndDumpClick(t){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},et);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:t})}_numericAttr(t,r){if(typeof t=="number"&&Number.isFinite(t))return t;if(typeof t=="string"){let i=S(t);if(i!==null)return i}return r}_formatClock(t){let r=t.getHours().toString().padStart(2,"0"),i=t.getMinutes().toString().padStart(2,"0");return`${r}:${i}`}_renderNumberControl(t){let r=t.entity?.attributes??{},i=this._numericAttr(r.min,t.fallbackMin),o=t.maxOverride??this._numericAttr(r.max,t.fallbackMax),a=this._numericAttr(r.step,t.fallbackStep),s=t.value??i,l=t.disabled??!t.entity,p=o>i?Math.max(0,Math.min(100,(s-i)/(o-i)*100)):0;return u`
""")),
    (_blk(r"""
          <ha-icon icon=${e.icon}></ha-icon>
          <span>${e.label}</span>
          <span class="number-control-value">${e.formatValue(o)}</span>
"""),
     _blk(r"""
          <ha-icon icon=${t.icon}></ha-icon>
          <span>${t.label}</span>
          <span class="number-control-value">${t.formatValue(s)}</span>
""")),
    (_blk(r"""
          style="--eaa-slider-fill:${d}%"
"""),
     _blk(r"""
          style="--eaa-slider-fill:${p}%"
""")),
    (_blk(r"""
          max=${n}
          step=${s}
          .value=${String(o)}
"""),
     _blk(r"""
          max=${o}
          step=${a}
          .value=${String(s)}
""")),
    (_blk(r"""
          @input=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onPreview(p)}}
          @change=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onCommit(p)}}
"""),
     _blk(r"""
          @input=${c=>{let d=Number(c.target.value);Number.isFinite(d)&&t.onPreview(d)}}
          @change=${c=>{let d=Number(c.target.value);Number.isFinite(d)&&t.onCommit(d)}}
""")),
    (_blk(r"""
    `}_renderDumpToGridTile(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return this._renderDumpToGridLockedShell();let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let d=e.schedule,c=d?m(this._entityState(d.armed)):null,p=De(l,c),y=this._freePowerVisualStateForInterlock(),_=K(l,y),w=_?"interlocked":p,k=_?Te("Free Power",y):void 0,$=this._entity(e.export_power),D=this._entity(e.stop_soc),b=this._entity(e.duration),U=this._pendingDumpPower??f($?.state),S=this._pendingDumpStopSoc??f(D?.state),de=this._pendingDumpDuration??f(b?.state),ce=this._dumpIconFor(w),xt=Ee(w);return u`
      <div class="tile dump-to-grid-tile state-${w}">
"""),
     _blk(r"""
    `}_renderDumpToGridTile(){let t=this._config?.dump_to_grid;if(!t||!this.hass)return this._renderDumpToGridLockedShell();let r=y(this._entityState(t.active)),i=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),a=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=Xe({active:r,armed:i,operationInProgress:o,snapshotValid:a,statusText:s});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let p=t.schedule,c=p?y(this._entityState(p.armed)):null,d=bt(l,c),v=this._freePowerVisualStateForInterlock(),b=Ce(l,v),m=b?"interlocked":d,w=b?_t("Free Power",v):void 0,P=this._entity(t.export_power),E=this._entity(t.stop_soc),_=this._entity(t.duration),A=this._pendingDumpPower??S(P?.state),R=this._pendingDumpStopSoc??S(E?.state),K=this._pendingDumpDuration??S(_?.state),g=this._dumpIconFor(m),x=vt(m);return u`
      <div class="tile dump-to-grid-tile state-${m}">
""")),
    (_blk(r"""
            <ha-icon class="tile-icon" icon=${ce}></ha-icon>
"""),
     _blk(r"""
            <ha-icon class="tile-icon" icon=${g}></ha-icon>
""")),
    (_blk(r"""
          <span class="state-pill state-${w}">${xt}</span>
"""),
     _blk(r"""
          <span class="state-pill state-${m}">${x}</span>
""")),
    (_blk(r"""
          ${d&&c===!0?this._renderDumpScheduleBanner(d):h}
          ${_?this._renderInterlockBanner(k):h}
"""),
     _blk(r"""
          ${p&&c===!0?this._renderDumpScheduleBanner(p):h}
          ${b?this._renderInterlockBanner(w):h}
""")),
    (_blk(r"""
          ${this._renderDumpBody(l,{dump:e,statusText:o,snapshotValid:s,interlocked:_,stagedPowerW:U,stagedStopSoc:S,stagedDurationMin:de,stagedPowerEntity:$,stagedStopSocEntity:D,stagedDurationEntity:b})}
"""),
     _blk(r"""
          ${this._renderDumpBody(l,{dump:t,statusText:s,snapshotValid:a,interlocked:b,stagedPowerW:A,stagedStopSoc:R,stagedDurationMin:K,stagedPowerEntity:P,stagedStopSocEntity:E,stagedDurationEntity:_})}
""")),
    (_blk(r"""
    `}_dumpIconFor(e){switch(e){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(e){return u`
"""),
     _blk(r"""
    `}_dumpIconFor(t){switch(t){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(t){return u`
""")),
    (_blk(r"""
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
"""),
     _blk(r"""
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${t}</p>
      </div>
""")),
    (_blk(r"""
    `}_renderDumpBody(e,t){switch(e){case"active":return this._renderDumpActiveBody(t);case"busy":return this._renderBusyBody(t.statusText??"Dump to Grid is mid-transaction.",t.dump.status);case"deferred":return this._renderDumpDeferredBody(t);case"recovery_attention":return this._renderDumpAttentionBody(t);default:return this._renderDumpReadyOrArmedBody(e,t)}}_renderDumpReadyOrArmedBody(e,t){let i=t.dump.schedule,n=i?this._dumpMode:"now";return u`
"""),
     _blk(r"""
    `}_renderDumpBody(t,r){switch(t){case"active":return this._renderDumpActiveBody(r);case"busy":return this._renderBusyBody(r.statusText??"Dump to Grid is mid-transaction.",r.dump.status);case"deferred":return this._renderDumpDeferredBody(r);case"recovery_attention":return this._renderDumpAttentionBody(r);default:return this._renderDumpReadyOrArmedBody(t,r)}}_renderDumpReadyOrArmedBody(t,r){let i=r.dump.schedule,o=i?this._dumpMode:"now";return u`
""")),
    (_blk(r"""
      ${n==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(e,t)}
      ${this._renderDumpLastEndReason(t.dump)}
    `}_renderDumpModeSelector(){let e=this._dumpMode==="now";return u`
"""),
     _blk(r"""
      ${o==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(t,r)}
      ${this._renderDumpLastEndReason(r.dump)}
    `}_renderDumpModeSelector(){let t=this._dumpMode==="now";return u`
""")),
    (_blk(r"""
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._dumpMode="now"}
"""),
     _blk(r"""
          role="tab"
          class="mode-tab ${t?"is-active":""}"
          aria-selected=${t}
          @click=${()=>this._dumpMode="now"}
""")),
    (_blk(r"""
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._dumpMode="later"}
"""),
     _blk(r"""
          role="tab"
          class="mode-tab ${t?"":"is-active"}"
          aria-selected=${!t}
          @click=${()=>this._dumpMode="later"}
""")),
    (_blk(r"""
    `}_renderDumpNowPanel(e,t){let i=e==="armed",n=Q(st(e),t.interlocked),s=Q(ot(e),t.interlocked);return u`
"""),
     _blk(r"""
    `}_renderDumpNowPanel(t,r){let i=t==="armed",o=Ne(bn(t),r.interlocked),a=Ne(vn(t),r.interlocked);return u`
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingDumpPower=o,onCommit:o=>this._commitDumpNumber("power",o,t.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:t.stagedStopSocEntity,value:t.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:t.interlocked,onPreview:o=>this._pendingDumpStopSoc=o,onCommit:o=>this._commitDumpNumber("stop_soc",o,t.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDumpDuration=o,onCommit:o=>this._commitDumpNumber("duration",o,t.dump.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:r.interlocked,onPreview:s=>this._pendingDumpPower=s,onCommit:s=>this._commitDumpNumber("power",s,r.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:r.stagedStopSocEntity,value:r.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:r.interlocked,onPreview:s=>this._pendingDumpStopSoc=s,onCommit:s=>this._commitDumpNumber("stop_soc",s,r.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:r.interlocked,onPreview:s=>this._pendingDumpDuration=s,onCommit:s=>this._commitDumpNumber("duration",s,r.dump.duration)})}
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
          ?disabled=${!a}
          @click=${()=>this._toggleArm(r.dump.write_enable,i)}
""")),
    (_blk(r"""
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.dump.start})}
"""),
     _blk(r"""
          ?disabled=${!o}
          @click=${()=>this._pressDumpStart(r.dump)}
""")),
    (_blk(r"""
    `}_renderDumpLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.stop_soc),c=this._entityState(e.last_result),p=this._pendingDumpScheduleDuration??f(o?.state),y=this._pendingDumpSchedulePower??f(l?.state),_=this._pendingDumpScheduleStopSoc??f(d?.state),w=Pe(c)||!!c&&/^FAILED/i.test(c.trim()),k=Ce(c),$=!!l&&!!o&&!!d&&t!==null,D=$&&!i&&s!==null&&s.getTime()>this._nowMs;return u`
"""),
     _blk(r"""
    `}_renderDumpLaterPanel(t){let r=y(this._entityState(t.armed)),i=Et(r),o=this._entityState(t.start),a=fe(o),s=this._entity(t.duration),l=this._entity(t.power),p=this._entity(t.stop_soc),c=this._entityState(t.last_result),d=this._pendingDumpScheduleDuration??S(s?.state),v=this._pendingDumpSchedulePower??S(l?.state),b=this._pendingDumpScheduleStopSoc??S(p?.state),m=yt(c)||!!c&&/^FAILED/i.test(c.trim()),w=St(c),P=!!l&&!!s&&!!p&&r!==null,E=P&&!i&&a!==null&&a.getTime()>this._nowMs;return u`
""")),
    (_blk(r"""
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
"""),
     _blk(r"""
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${a?this._toDatetimeLocalValue(a):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
""")),
    (_blk(r"""
          @change=${b=>this._handleScheduleStartChange(e.start,b.target.value)}
"""),
     _blk(r"""
          @change=${_=>this._handleScheduleStartChange(t.start,_.target.value)}
""")),
    (_blk(r"""
      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:i||!l,onPreview:b=>this._pendingDumpSchedulePower=b,onCommit:b=>this._commitDumpScheduleNumber("power",b,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:d,value:_,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:i||!d,onPreview:b=>this._pendingDumpScheduleStopSoc=b,onCommit:b=>this._commitDumpScheduleNumber("stop_soc",b,e.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:b=>this._pendingDumpScheduleDuration=b,onCommit:b=>this._commitDumpScheduleNumber("duration",b,e.duration)})}
"""),
     _blk(r"""
      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:v,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:i||!l,onPreview:_=>this._pendingDumpSchedulePower=_,onCommit:_=>this._commitDumpScheduleNumber("power",_,t.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:p,value:b,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:i||!p,onPreview:_=>this._pendingDumpScheduleStopSoc=_,onCommit:_=>this._commitDumpScheduleNumber("stop_soc",_,t.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:d,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:i||!s,onPreview:_=>this._pendingDumpScheduleDuration=_,onCommit:_=>this._commitDumpScheduleNumber("duration",_,t.duration)})}
""")),
    (_blk(r"""
      ${$?h:u`<p class="firmware-note is-warning">
"""),
     _blk(r"""
      ${P?h:u`<p class="firmware-note is-warning">
""")),
    (_blk(r"""
      ${c?u`<p class="firmware-note ${w||k?"is-warning":""}">${c}</p>`:h}
"""),
     _blk(r"""
      ${c?u`<p class="firmware-note ${m||w?"is-warning":""}">${c}</p>`:h}
""")),
    (_blk(r"""
          ?disabled=${!D}
          @click=${()=>this._callServiceObj(Me(e.armed))}
"""),
     _blk(r"""
          ?disabled=${!E}
          @click=${()=>this._callServiceObj(Mt(t.armed))}
""")),
    (_blk(r"""
    `}_renderDumpScheduleBanner(e){let t=M(this._entityState(e.start)),i=f(this._entityState(e.duration)),n=f(this._entityState(e.power)),s=f(this._entityState(e.stop_soc)),o=t?J(t.getTime(),this._nowMs):null;return u`
"""),
     _blk(r"""
    `}_renderDumpScheduleBanner(t){let r=fe(this._entityState(t.start)),i=S(this._entityState(t.duration)),o=S(this._entityState(t.power)),a=S(this._entityState(t.stop_soc)),s=r?Ie(r.getTime(),this._nowMs):null;return u`
""")),
    (_blk(r"""
            ${t?Ve(t):"--"} • ${T(n)} • stop
            ${L(s)} • ${F(i)}
          </div>
          <div class="schedule-banner-countdown">${o?`Starts in ${o}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Fe(e.cancel))}
"""),
     _blk(r"""
            ${r?Tt(r):"--"} • ${ne(o)} • stop
            ${we(a)} • ${ge(i)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pt(t.cancel))}
""")),
    (_blk(r"""
    `}_commitDumpScheduleNumber(e,t,i){e==="power"?this._pendingDumpSchedulePower=t:e==="stop_soc"?this._pendingDumpScheduleStopSoc=t:this._pendingDumpScheduleDuration=t,this._callServiceObj(Ie(i,t))}_renderDumpLastEndReason(e){let t=this._entityState(e.last_end_reason);return!t||t==="unknown"||t==="unavailable"?h:u`<p class="firmware-note">Last lease ended: ${t}</p>`}_renderDumpActiveBody(e){let t=this._entityState(e.dump.ends_at),i=M(t),n=i?J(i.getTime(),this._nowMs):null,s=f(this._entityState(e.dump.battery_soc)),o=lt(f(this._entityState(e.dump.active_export_power)),e.statusText),l=dt(f(this._entityState(e.dump.active_stop_soc)),e.statusText);return u`
      <div class="active-hero">
        <div class="active-hero-time">${n??"--:--"}</div>
"""),
     _blk(r"""
    `}_commitDumpScheduleNumber(t,r,i){t==="power"?this._pendingDumpSchedulePower=r:t==="stop_soc"?this._pendingDumpScheduleStopSoc=r:this._pendingDumpScheduleDuration=r,this._callServiceObj(Rt(i,r))}_renderDumpLastEndReason(t){let r=this._entityState(t.last_end_reason);return!r||r==="unknown"||r==="unavailable"?h:u`<p class="firmware-note">Last lease ended: ${r}</p>`}_renderDumpActiveBody(t){let r=this._entityState(t.dump.ends_at),i=fe(r),o=i?Ie(i.getTime(),this._nowMs):null,a=S(this._entityState(t.dump.battery_soc)),s=_n(S(this._entityState(t.dump.active_export_power)),t.statusText),l=wn(S(this._entityState(t.dump.active_stop_soc)),t.statusText);return u`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
""")),
    (_blk(r"""
        Target ${T(o)} export • ends ${i?this._formatClock(i):t??"--"}
"""),
     _blk(r"""
        Target ${ne(s)} export • ends ${i?this._formatClock(i):r??"--"}
""")),
    (_blk(r"""
        Battery: ${L(s)} • stops at ${L(l)}
"""),
     _blk(r"""
        Battery: ${we(a)} • stops at ${we(l)}
""")),
    (_blk(r"""
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.dump.status,{alwaysShow:!0})}
      ${this._renderDumpDiagnosticsDetails(e.dump)}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("active"))}
    `}_renderDumpDeferredBody(e){return u`
      ${this._renderDeferredBody(e.statusText,e.dump.status)}
      ${e.snapshotValid===!0?this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("deferred")):h}
    `}_renderDumpAttentionBody(e){let i=!!e.dump.recovery_arm&&!!e.dump.recovery_force_restore&&!!e.dump.recovery_accept&&ct(e.statusText,e.snapshotValid);return u`
"""),
     _blk(r"""
        <ha-icon icon=${t.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${t.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(t.statusText,t.dump.status,{alwaysShow:!0})}
      ${this._renderDumpDiagnosticsDetails(t.dump)}
      ${this._renderEndDumpButton(t.dump.end_restore,"End & Restore Now",Qe("active"))}
    `}_renderDumpDeferredBody(t){return u`
      ${this._renderDeferredBody(t.statusText,t.dump.status)}
      ${t.snapshotValid===!0?this._renderEndDumpButton(t.dump.end_restore,"End & Restore Now",Qe("deferred")):h}
    `}_renderDumpAttentionBody(t){let i=!!t.dump.recovery_arm&&!!t.dump.recovery_force_restore&&!!t.dump.recovery_accept&&xn(t.statusText,t.snapshotValid);return u`
""")),
    (_blk(r"""
          ${this._renderTransitionDetail(e.statusText??"Dump to Grid requires operator attention.",e.dump.status)}
"""),
     _blk(r"""
          ${this._renderTransitionDetail(t.statusText??"Dump to Grid requires operator attention.",t.dump.status)}
""")),
    (_blk(r"""
      ${i?this._renderDumpRecoveryPanel(e.dump):h}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(e){let t=m(this._entityState(e.recovery_arm))===!0,i=this._entityState(e.recovery_state);return u`
"""),
     _blk(r"""
      ${i?this._renderDumpRecoveryPanel(t.dump):h}
      ${this._renderEndDumpButton(t.dump.end_restore,"End & Restore Now",Qe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(t){let r=y(this._entityState(t.recovery_arm))===!0,i=this._entityState(t.recovery_state);return u`
""")),
    (_blk(r"""
            class="arm-toggle ${t?"is-armed":""}"
            @click=${()=>this._toggleArm(e.recovery_arm,t)}
"""),
     _blk(r"""
            class="arm-toggle ${r?"is-armed":""}"
            @click=${()=>this._toggleArm(t.recovery_arm,r)}
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
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_force_restore})}
"""),
     _blk(r"""
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:t.recovery_force_restore})}
""")),
    (_blk(r"""
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_accept})}
"""),
     _blk(r"""
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:t.recovery_accept})}
""")),
    (_blk(r"""
    `}_renderDumpDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
"""),
     _blk(r"""
    `}_renderDumpDiagnosticsDetails(t){let r=[],i=(o,a)=>{let s=S(this._entityState(a));s!==null&&r.push({label:o,value:s.toString()})};return i("Starts",t.start_attempts),i("Started OK",t.start_successes),i("Restored OK",t.restore_successes),i("Failures",t.failures),r.length===0?h:u`
""")),
    (_blk(r"""
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(e,t,i){let n=this._confirmEndDump;return u`
"""),
     _blk(r"""
          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(t,r,i){let o=this._confirmEndDump;return u`
""")),
    (_blk(r"""
        class="end-restore-button ${n?"confirming":""}"
"""),
     _blk(r"""
        class="end-restore-button ${o?"confirming":""}"
""")),
    (_blk(r"""
        @click=${()=>this._handleEndDumpClick(e)}
"""),
     _blk(r"""
        @click=${()=>this._handleEndDumpClick(t)}
""")),
    (_blk(r"""
        ${n?"Tap again to End & Restore":t}
        ${n?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
"""),
     _blk(r"""
        ${o?"Tap again to End & Restore":r}
        ${o?u`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:h}
""")),
    (_blk(r"""
    `}};g.styles=pe`
"""),
     _blk(r"""
    `}};T.styles=[cr,vr,de`
""")),
    (_blk(r"""
  `,v([ie({attribute:!1})],g.prototype,"hass",2),v([x()],g.prototype,"_config",2),v([x()],g.prototype,"_pendingPower",2),v([x()],g.prototype,"_pendingDuration",2),v([x()],g.prototype,"_pendingSchedulePower",2),v([x()],g.prototype,"_pendingScheduleDuration",2),v([x()],g.prototype,"_confirmEndRestore",2),v([x()],g.prototype,"_pendingDumpPower",2),v([x()],g.prototype,"_pendingDumpStopSoc",2),v([x()],g.prototype,"_pendingDumpDuration",2),v([x()],g.prototype,"_confirmEndDump",2),v([x()],g.prototype,"_dumpMode",2),v([x()],g.prototype,"_pendingDumpSchedulePower",2),v([x()],g.prototype,"_pendingDumpScheduleStopSoc",2),v([x()],g.prototype,"_pendingDumpScheduleDuration",2),v([x()],g.prototype,"_nowMs",2),v([x()],g.prototype,"_mode",2),v([x()],g.prototype,"_track",2),g=v([rt("ecco-energy-actions-card")],g);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{g as EccoEnergyActionsCard};
"""),
     _blk(r"""
  `],C([ze({attribute:!1})],T.prototype,"hass",2),C([O()],T.prototype,"_config",2),C([O()],T.prototype,"_pendingPower",2),C([O()],T.prototype,"_pendingDuration",2),C([O()],T.prototype,"_pendingSchedulePower",2),C([O()],T.prototype,"_pendingScheduleDuration",2),C([O()],T.prototype,"_confirmEndRestore",2),C([O()],T.prototype,"_pendingDumpPower",2),C([O()],T.prototype,"_pendingDumpStopSoc",2),C([O()],T.prototype,"_pendingDumpDuration",2),C([O()],T.prototype,"_confirmEndDump",2),C([O()],T.prototype,"_dumpMode",2),C([O()],T.prototype,"_pendingDumpSchedulePower",2),C([O()],T.prototype,"_pendingDumpScheduleStopSoc",2),C([O()],T.prototype,"_pendingDumpScheduleDuration",2),C([O()],T.prototype,"_nowMs",2),C([O()],T.prototype,"_mode",2),C([O()],T.prototype,"_track",2),T=C([hn("ecco-energy-actions-card")],T);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{T as EccoEnergyActionsCard};
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
# Re-derived for the r9 + stage 3 merge: anchored on the text FOLLOWING the insertion (the first helper block), so the pair matches the
# combined package (r9's paragraph precedes the PLAN paragraph) and the package without r9 alike.
# 19 Nov 2026 (owner decision r14: a press-time BLOCKED result is no longer overwritten with STARTED OK): the header pair's `after` text carries the new header
# lines, and two pairs were added at the end: the post-loop overwrite step (it now excludes a BLOCKED result) and the end-of-run alert's message (one sentence, only while
# Dump to Grid is active). The pairs are exact and the apply/revert round trip is byte for byte (the epc2 reverter still lands on the r9 state).
# 19 Nov 2026 (owner decision r15: a STARTING, FAILED or CANCELLED result is not overwritten with STARTED OK either): the header pair's `after` text carries the new last bullet, the post-loop step pair's `after`
# text is the new step (it acts on a STARTING result only and writes no success text; its `before` now spans the whole r9 step, its `then` included) and the alert pair's `after` text carries the two-way
# sentence (BLOCKED: this run did not start it; FAILED: this run did not confirm that it started it). The pairs stay exact and the round trip byte for byte.
# 19 Nov 2026 (owner decision r15, the last path of known limitation 20: the startup recovery no longer writes STARTED OK over a result this schedule did not verify): the header pair's `after` text carries one more
# bullet (next to the r15 one) and ONE pair was added at the end: the recovery's active-in-window branch (its comment, a choose for a STARTED / a FAILED, BLOCKED or CANCELLED / any other result, and the old disarm).
# The new pair's `before` is the branch as the r9 state has it; the pairs stay exact and the round trip byte for byte.
DUMP_EDITS = (
    (_blk(r"""

input_boolean:
  ecco_dump_to_grid_schedule_armed:
"""),
     _blk(r"""
#
# PLAN (stage 3, home-assistant/packages/ecco_plan_helpers.yaml, which must be installed with or before this file): the start also
# refuses, with its own BLOCKED result text (the end-of-run alert below raises the persistent notification) and with nothing
# staged or pressed,
#   - while a Hold battery, Skip tonight or Prepare for power cut is active (sensor.ecco_plan_export_hold reads held), and while that
#     cannot be read (unknown, unavailable or the entity missing: it fails closed);
#   - while the effective reserve (sensor.ecco_plan_effective_reserve: the larger of the owner's reserve and a running power-cut reserve)
#     cannot be read (reason RESERVE_UNKNOWN), is not a finite number from 0 to 100 (reason RESERVE_INVALID), or leaves no room under
#     the 90 % Stop SOC limit (reason RESERVE_TOO_HIGH). The reserve passes only as a finite number from 0 to 100, tested as a positive
#     range: nan, infinity and anything else is refused before anything is staged, so a bad reading fails closed;
# and it raises the Stop SOC it stages to at least the effective reserve (rounded up), never lowers it. The scheduled start is the
# trusted backend: the dashboard and the card are not what keeps an override.
#
# PLAN, press-time recheck: a run can wait up to 10 minutes for the dongle (offline, or another write in progress), and the owner can start
# a Hold battery, Skip tonight or Prepare for power cut in that time. So the hold and the reserve are read AGAIN immediately before the
# press. If the hold is no longer clear (held, or cannot be read), or the reserve can no longer be read or is not a finite number from 0
# to 100, or the Stop SOC staged for THIS run is below the rounded-up reserve of that moment, the run ends as a BLOCKED result with the
# same reason codes (RESERVE_TOO_HIGH for the staged Stop SOC) that says it happened while the run was waiting, nothing is pressed, the
# write enable ends off, it is never retried, and the end-of-run alert raises the notification, also when Dump to Grid is found active when
# the loop ends (see the last point below). The re-read is a moment before the press,
# not part of it: an override started in that moment is not seen. What else the recheck does and does not do:
#   - It runs on EVERY attempt, the first included: after the staging (up to about six seconds: three numbers, the arm and its
#     confirmation) and before the press. A "while this run was waiting" text can therefore also come from a change during that staging.
#   - It fails closed, and that has a cost: a hold or reserve sensor that is momentarily unknown or unavailable at that moment (a
#     template reload, a Home Assistant start) ends the run as BLOCKED, alerts and disarms the schedule, so that night's scheduled
#     export is lost until the owner arms it again. It is not refused for good: the next armed run reads the sensors afresh.
#   - The staging of that attempt stays on the dongle (export power, Stop SOC and duration) with the write enable off; nothing starts
#     without arming again and pressing, as after any other failed attempt.
#   - Fixed 19 Nov 2026 (owner decision r14: a refusal stays a refusal): this BLOCKED text is written inside the retry loop, so, unlike
#     the start-time BLOCKED results, the steps after the loop still run. They no longer overwrite it: a result that starts with BLOCKED
#     is never replaced by "STARTED OK - Dump to Grid is active; this run could not confirm the start as its own ...", also when Dump to
#     Grid is active when the loop ends (started from the dongle's own Start button, which no override binds (RG-ST3), or by a manual
#     start). The end-of-run alert is raised as for any BLOCKED result, the schedule notifications are not dismissed, and the alert says
#     that Dump to Grid is active now and that this run did not start it: check it, and the plan overrides, before assuming it is held.
#     This script presses nothing in that case.
#   - Fixed 19 Nov 2026 (owner decision r15: every final status reflects the actual outcome): the steps after the loop never write a success
#     text. A FAILED or CANCELLED result is final too: it stays exactly as written when Dump to Grid is active (started some other way), and
#     so does a BLOCKED one. A result that is still STARTING when Dump to Grid is found active has no verified start of this run: it becomes
#     CANCELLED if the owner cancelled the schedule, else a FAILED TO START text that says the retries ended, repeats the last status and says
#     that Dump to Grid is active now and that this run did not confirm that it started it. STARTED OK is written only inside the loop, after
#     this run's own press, a start transaction that began and Dump to Grid active; that path is unchanged. A result this script did not write
#     (ARMED, REJECTED, MISSED) is left alone. The alert's sentence says "this run did not start it" for a BLOCKED result only (nothing was
#     pressed); for a FAILED result it says this run did not CONFIRM that it started it, because an unconfirmed outcome can be a late start of
#     this run's own press. Still true: such a FAILED text can be a false negative (the dongle started late after a start transaction that
#     began); the alert flags it. Nothing is pressed after the loop, the write enable ends off, and nothing changes while Dump to Grid is not active.
#   - Fixed 19 Nov 2026 (owner decision r15, the last path of known limitation 20): the startup recovery after a Home Assistant restart no longer writes
#     STARTED OK over a result this schedule did not verify. It used to write "STARTED OK - running (Home Assistant restarted during the session)" whenever
#     the schedule was armed, now was inside the window and Dump to Grid was active, whatever the last result was, so a refused (BLOCKED), failed, cancelled
#     or restart-killed STARTING run read as a success when the dongle's own Start button (which no override binds (RG-ST3)), a manual start or another path
#     had started Dump to Grid. The recovery cannot tell who started it, so it trusts only the record: a last result that already starts with STARTED (this
#     schedule's own verified start, recorded before the restart) keeps that text and the disarm, byte for byte; a result that starts with FAILED, BLOCKED or
#     CANCELLED is final and is left exactly as written (the schedule is still disarmed and no alert is added: the text stays visible and, for FAILED or BLOCKED,
#     so does the status FAILED once Dump to Grid is not active); every other result (STARTING, ARMED, empty, REJECTED, MISSED, foreign text) becomes an UNCONFIRMED
#     text that says Dump to Grid is active after a Home Assistant restart and that this schedule did not confirm that it started it. The recovery presses and starts nothing, and
#     every other branch of it and every case with Dump to Grid not active is unchanged. Still true: a FAILED text it leaves in place can be a false negative
#     (the dongle started late after a start transaction that began), and the Free Power schedule package has its own old fallback and recovery, unchanged.

input_boolean:
  ecco_dump_to_grid_schedule_armed:
""")),
    (_blk(r"""
          requested_stop_soc: "{{ stop_soc | int(25) }}"
"""),
     _blk(r"""
          # The plan's hold and reserve, read at the start of the run. A run can then wait up to 10 minutes (dongle offline or another
          # write in progress), so both are read AGAIN immediately before the press (press_block, in the retry loop below): a change that
          # came in while the run waited ends THIS run, it does not wait for the next one.
          plan_hold: "{{ states('sensor.ecco_plan_export_hold') }}"
          # The reserve must be a finite number from 0 to 100, tested as a positive range: a comparison with nan is always false, so a test
          # that only refused a too-big value would let nan through, and float() also accepts nan, inf and -inf (inf cannot be rounded, and
          # the offline interpreter keeps nan and inf as text, so every comparison then raises). A value outside the range is therefore
          # replaced here by a negative code, and nothing below ever compares, rounds or stages a bad reserve:
          # -1 = cannot be read, or below 0 (RESERVE_UNKNOWN); -2 = not a finite number from 0 to 100 (RESERVE_INVALID).
          plan_reserve: >-
            {%- set r = states('sensor.ecco_plan_effective_reserve') | float(-1) -%}
            {%- if r >= 0 and r <= 100 -%}{{ r }}
            {%- elif r < 0 -%}-1
            {%- else -%}-2
            {%- endif -%}
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
          # PLAN: no known effective reserve, or one that is not a finite number from 0 to 100: fail closed (plan_reserve is negative for
          # both, so this one branch refuses both; the text says which).
          - conditions:
              - condition: template
                value_template: "{{ plan_reserve < 0 }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: >-
                    {%- if plan_reserve == -2 -%}BLOCKED - the effective reserve is not a number from 0 to 100; nothing started (reason RESERVE_INVALID)
                    {%- else -%}BLOCKED - the effective reserve cannot be read; nothing started (reason RESERVE_UNKNOWN)
                    {%- endif -%}
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
    (_blk(r"""
                    - delay:
                        seconds: 1
                    - if:
"""),
     _blk(r"""
                    - delay:
                        seconds: 1
                    # PLAN (press-time recheck): this run may have waited (dongle offline or another write in progress, up to 10 minutes) since it
                    # read the plan at its start, and the owner may have started a Hold battery, Skip tonight or Prepare for power cut in the
                    # meantime. The hold and the reserve are therefore read AGAIN here, immediately before the press, and sanitised as at the
                    # start (the reserve passes only as a finite number from 0 to 100: below 0 is RESERVE_UNKNOWN, nan or anything above 100 is
                    # RESERVE_INVALID). press_block is empty (press, exactly as before) or the reason: OVERRIDE_ACTIVE (held), OVERRIDE_UNREADABLE
                    # (anything but held or clear), RESERVE_UNKNOWN, RESERVE_INVALID, or RESERVE_TOO_HIGH (the Stop SOC staged for THIS run is
                    # below the rounded-up reserve of now: never press with a Stop SOC below the reserve).
                    - variables:
                        press_block: >-
                          {%- set h = states('sensor.ecco_plan_export_hold') -%}
                          {%- set r = states('sensor.ecco_plan_effective_reserve') | float(-1) -%}
                          {%- if h == 'held' -%}OVERRIDE_ACTIVE
                          {%- elif h != 'clear' -%}OVERRIDE_UNREADABLE
                          {%- elif r < 0 -%}RESERVE_UNKNOWN
                          {%- elif not (r >= 0 and r <= 100) -%}RESERVE_INVALID
                          {%- elif (r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH
                          {%- endif -%}
                    - if:
""")),
    (_blk(r"""
                               and as_timestamp(states.input_boolean.ecco_dump_to_grid_schedule_armed.last_changed, 0) <= (run_started | float(0)) }}
                      then:
"""),
     _blk(r"""
                               and as_timestamp(states.input_boolean.ecco_dump_to_grid_schedule_armed.last_changed, 0) <= (run_started | float(0)) }}
                        # PLAN (press-time recheck): nothing is pressed while the hold or the reserve read just above says no.
                        - condition: template
                          value_template: "{{ (press_block | string | trim) == '' }}"
                      then:
""")),
    (_blk(r"""
                        - delay:
                            seconds: 5
              until:
"""),
     _blk(r"""
                        - delay:
                            seconds: 5
                    # PLAN (press-time recheck): the plan changed while this run waited. This ends THIS run for good: the BLOCKED text below is one
                    # of the results the loop's `until` stops on (the write enable was turned off just above, nothing was pressed, and the end-of-run
                    # alert raises the notification), so no later attempt stages or presses anything.
                    - if:
                        - condition: template
                          value_template: "{{ (press_block | string | trim) != '' }}"
                      then:
                        - action: input_text.set_value
                          target:
                            entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                          data:
                            value: >-
                              {%- if press_block == 'OVERRIDE_ACTIVE' -%}BLOCKED - a Hold battery, Skip tonight or Prepare for power cut became active while this run was waiting ({{ state_attr('sensor.ecco_plan_export_hold', 'held_by') }}); nothing started (reason OVERRIDE_ACTIVE)
                              {%- elif press_block == 'OVERRIDE_UNREADABLE' -%}BLOCKED - the plan override records could not be read while this run was waiting; nothing started (reason OVERRIDE_UNREADABLE)
                              {%- elif press_block == 'RESERVE_UNKNOWN' -%}BLOCKED - the effective reserve could not be read while this run was waiting; nothing started (reason RESERVE_UNKNOWN)
                              {%- elif press_block == 'RESERVE_INVALID' -%}BLOCKED - the effective reserve was not a number from 0 to 100 while this run was waiting; nothing started (reason RESERVE_INVALID)
                              {%- elif press_block == 'RESERVE_TOO_HIGH' -%}BLOCKED - the effective reserve rose above the Stop SOC staged for this run ({{ requested_stop_soc }}%) while it was waiting; nothing started (reason RESERVE_TOO_HIGH)
                              {%- else -%}BLOCKED - the plan could not be checked while this run was waiting; nothing started (reason OVERRIDE_UNREADABLE)
                              {%- endif -%}
              until:
""")),
    (_blk(r"""
          - if:
              - condition: template
                value_template: >-
                  {% set r = states('input_text.ecco_dump_to_grid_schedule_last_result') %}
                  {{ is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and not r.startswith('STARTED') }}
            then:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: "STARTED OK - Dump to Grid is active; this run could not confirm the start as its own (check power, Stop SOC and end time)"
"""),
     _blk(r"""
          # Owner decision r15 (19 Nov 2026): the steps after the loop never turn a result into a success. STARTED OK is written only inside the loop,
          # by this run's own verified start (its press, a start transaction that began, then Dump to Grid active). A FAILED, CANCELLED or BLOCKED result
          # stays exactly as written, whatever Dump to Grid is doing (started some other way: the dongle's own Start button, which is not bound by
          # any override (RG-ST3), or by hand); the alert below then says so. A result that is still STARTING when Dump to Grid is found active was not confirmed by
          # this run: it becomes CANCELLED if the owner cancelled the schedule, else a FAILED TO START text that says Dump to Grid is active now and that
          # this run did not confirm that it started it. A result this script did not write (ARMED, REJECTED, MISSED) is left alone.
          - if:
              - condition: template
                value_template: >-
                  {% set r = states('input_text.ecco_dump_to_grid_schedule_last_result') %}
                  {{ is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and r.startswith('STARTING') }}
            then:
              - choose:
                  # Cancelled by the owner (tested as the loop top and the step above test it): the run reads CANCELLED, not failed.
                  - conditions:
                      - condition: template
                        value_template: >-
                          {{ not (is_state('input_boolean.ecco_dump_to_grid_schedule_armed', 'on')
                                  and as_timestamp(states.input_boolean.ecco_dump_to_grid_schedule_armed.last_changed, 0)
                                      <= (run_started | float(0))) }}
                    sequence:
                      - action: input_text.set_value
                        target:
                          entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                        data:
                          value: "CANCELLED - scheduled Dump to Grid cancelled before it started"
                default:
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                    data:
                      value: >-
                        FAILED TO START - retries ended at {{ now().strftime('%H:%M') }}:
                        {{ states('sensor.ecco_clock_dongle_dump_to_grid_status')[:120] }};
                        Dump to Grid is active now, but this run did not confirm that it started it
""")),
    (_blk(r"""
              title: "ECCO: scheduled Dump to Grid did NOT start"
              message: >-
                {{ states('input_text.ecco_dump_to_grid_schedule_last_result') }}

                Authorised window ends {{ (window_end | float(0)) | timestamp_custom('%H:%M') }}.
"""),
     _blk(r"""
              title: "ECCO: scheduled Dump to Grid did NOT start"
              # Owner decision r14: while Dump to Grid is active at this moment the notice says so. Owner decision r15: for a BLOCKED result (nothing was
              # pressed) it says this run did not start it; for any other result (a FAILED one) it says only that this run did not CONFIRM that it started it,
              # because an unconfirmed outcome can be a late start of this run's own press.
              message: >-
                {{ states('input_text.ecco_dump_to_grid_schedule_last_result') }}
                {%- if is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') %}

                {% if states('input_text.ecco_dump_to_grid_schedule_last_result').startswith('BLOCKED') -%}
                Dump to Grid is active now, and this run did not start it (it may have been started from the dongle's own Start button or by hand).
                Check it, and the plan overrides, before assuming it is held.
                {%- else -%}
                Dump to Grid is active now, but this run did not confirm that it started it (it may have been started from the dongle's own Start button or by hand, or, if a start transaction had begun, late by this run's own press).
                Check it, and the plan overrides, before assuming it is held.
                {%- endif %}
                {%- endif %}

                Authorised window ends {{ (window_end | float(0)) | timestamp_custom('%H:%M') }}.
""")),
    (_blk(r"""
          # Restarted while the session runs: it started; record it and disarm.
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active
                state: "on"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: "STARTED OK - running (Home Assistant restarted during the session)"
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
"""),
     _blk(r"""
          # Restarted while the session runs and Dump to Grid is active. Owner decision r15 (19 Nov 2026): the recovery never turns a result into a success that
          # this schedule did not verify. It cannot tell who started Dump to Grid (the dongle's own Start button, which no override binds (RG-ST3), a manual start,
          # or this schedule's own press), so it trusts only the record. A last result that already starts with STARTED (this schedule's own verified start, recorded
          # before the restart) keeps the old text. A FAILED, BLOCKED or CANCELLED result is final: it is not written again (the text stays as the run left it and, for
          # FAILED or BLOCKED, the status reads FAILED once Dump to Grid is not active; no new alert). Any other result (STARTING, ARMED, empty, REJECTED, MISSED, foreign text) gets a text that
          # says Dump to Grid is active after a restart and that this schedule did not confirm that it started it. Nothing is pressed or started here. The schedule is
          # disarmed in every case, as before, so the watchdog cannot turn a refusal into a MISSED record.
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active
                state: "on"
            sequence:
              - choose:
                  - conditions:
                      - condition: template
                        value_template: "{{ states('input_text.ecco_dump_to_grid_schedule_last_result').startswith('STARTED') }}"
                    sequence:
                      - action: input_text.set_value
                        target:
                          entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                        data:
                          value: "STARTED OK - running (Home Assistant restarted during the session)"
                  - conditions:
                      - condition: template
                        value_template: >-
                          {% set r = states('input_text.ecco_dump_to_grid_schedule_last_result') %}
                          {{ r.startswith('FAILED') or r.startswith('BLOCKED') or r.startswith('CANCELLED') }}
                    sequence: []
                default:
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                    data:
                      value: "UNCONFIRMED - Dump to Grid is active after a Home Assistant restart, but this schedule did not confirm that it started it (it may have been started some other way). Check it, and the plan overrides, before assuming it is held."
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
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
  # they never call a charge, discharge, TOU, inverter or dongle service) and the export-hold / effective-reserve sensors. Install it in
  # the SAME deployment as the guarded start below and the changed ecco_dump_to_grid_schedule.yaml, before the ONE full Home Assistant
  # restart (the order of the stanzas in this list does not matter): both refuse every start while these sensors cannot be read. The
  # first Home Assistant start writes the owner's accepted limits once; the confirmation switch stays off.
  - source: home-assistant/packages/ecco_plan_helpers.yaml
    destination: /config/packages/ecco_plan_helpers.yaml
    method: ssh_file_copy
    restart_required: true
  # The guarded manual Dump to Grid start the Energy Actions card calls when it is configured with dump_to_grid.guarded_start. It
  # presses the same dongle start button, but only while no override holds export and the staged Stop SOC is at least the effective
  # reserve. Needs ecco_plan_helpers.yaml installed in the SAME deployment, before the ONE full Home Assistant restart (the order of the
  # stanzas in this list does not matter). Until the plan helpers are installed and Home Assistant has restarted fully, every guarded start
  # is refused. While an override is active, or the plan records cannot be read, or the effective reserve or the staged Stop SOC is invalid,
  # it refuses, says why in the plan last-result text and raises one notification, and presses nothing.
  # The dongle's own Start button is not bound by these protections (unresolved; it needs a firmware gate, approved separately).
  - source: home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml
    destination: /config/packages/ecco_dump_to_grid_guarded_start.yaml
    method: ssh_file_copy
    restart_required: true

dashboard:
""")),
    (_blk(r"""
  - source: home-assistant/packages/ecco_dump_to_grid_schedule.yaml
"""),
     _blk(r"""
  # Stage 3 (epc2; offline, not live-proven). HELPER DEPENDENCY: this package now needs ecco_plan_helpers.yaml installed in the SAME
  # deployment, before the ONE full Home Assistant restart (the R9 note above: a FULL restart, not a reload). The order of the stanzas in
  # this list does not matter: the deploy tool copies every package, checks the configuration, and restarts Home Assistant only as a
  # separately approved step. Until the plan helpers are installed and Home Assistant has restarted fully, every scheduled start is refused
  # (reason OVERRIDE_UNREADABLE) and every guarded start is refused, because the plan sensors cannot be read.
  # ACTIVE-OVERRIDE WARNING: while a Hold battery, Skip tonight or Prepare for power cut override is active, or the plan records cannot be
  # read, or the effective reserve is not a valid number, every scheduled start and every guarded manual start is REFUSED. The owner sees this
  # only at the start time, through the blocked alert and the last-result text, not when the override is set: check before an armed start time.
  - source: home-assistant/packages/ecco_dump_to_grid_schedule.yaml
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
