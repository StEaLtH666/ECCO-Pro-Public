var mt=Object.defineProperty;var bt=Object.getOwnPropertyDescriptor;var O=(i,t,e,r)=>{for(var o=r>1?void 0:r?bt(t,e):t,n=i.length-1,a;n>=0;n--)(a=i[n])&&(o=(r?a(t,e,o):a(o))||o);return r&&o&&mt(t,e,o),o};var te=globalThis,re=te.ShadowRoot&&(te.ShadyCSS===void 0||te.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,ue=Symbol(),Pe=new WeakMap,G=class{constructor(t,e,r){if(this._$cssResult$=!0,r!==ue)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o,e=this.t;if(re&&t===void 0){let r=e!==void 0&&e.length===1;r&&(t=Pe.get(e)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),r&&Pe.set(e,t))}return t}toString(){return this.cssText}},Ne=i=>new G(typeof i=="string"?i:i+"",void 0,ue),pe=(i,...t)=>{let e=i.length===1?i[0]:t.reduce((r,o,n)=>r+(a=>{if(a._$cssResult$===!0)return a.cssText;if(typeof a=="number")return a;throw Error("Value passed to 'css' function must be a 'css' function result: "+a+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(o)+i[n+1],i[0]);return new G(e,i,ue)},Re=(i,t)=>{if(re)i.adoptedStyleSheets=t.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of t){let r=document.createElement("style"),o=te.litNonce;o!==void 0&&r.setAttribute("nonce",o),r.textContent=e.cssText,i.appendChild(r)}},ge=re?i=>i:i=>i instanceof CSSStyleSheet?(t=>{let e="";for(let r of t.cssRules)e+=r.cssText;return Ne(e)})(i):i;var{is:ft,defineProperty:vt,getOwnPropertyDescriptor:yt,getOwnPropertyNames:xt,getOwnPropertySymbols:wt,getPrototypeOf:_t}=Object,oe=globalThis,Me=oe.trustedTypes,$t=Me?Me.emptyScript:"",kt=oe.reactiveElementPolyfillSupport,V=(i,t)=>i,K={toAttribute(i,t){switch(t){case Boolean:i=i?$t:null;break;case Object:case Array:i=i==null?i:JSON.stringify(i)}return i},fromAttribute(i,t){let e=i;switch(t){case Boolean:e=i!==null;break;case Number:e=i===null?null:Number(i);break;case Object:case Array:try{e=JSON.parse(i)}catch{e=null}}return e}},ie=(i,t)=>!ft(i,t),Oe={attribute:!0,type:String,converter:K,reflect:!1,useDefault:!1,hasChanged:ie};Symbol.metadata??=Symbol("metadata"),oe.litPropertyMetadata??=new WeakMap;var E=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=Oe){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){let r=Symbol(),o=this.getPropertyDescriptor(t,r,e);o!==void 0&&vt(this.prototype,t,o)}}static getPropertyDescriptor(t,e,r){let{get:o,set:n}=yt(this.prototype,t)??{get(){return this[e]},set(a){this[e]=a}};return{get:o,set(a){let l=o?.call(this);n?.call(this,a),this.requestUpdate(t,l,r)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??Oe}static _$Ei(){if(this.hasOwnProperty(V("elementProperties")))return;let t=_t(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(V("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(V("properties"))){let e=this.properties,r=[...xt(e),...wt(e)];for(let o of r)this.createProperty(o,e[o])}let t=this[Symbol.metadata];if(t!==null){let e=litPropertyMetadata.get(t);if(e!==void 0)for(let[r,o]of e)this.elementProperties.set(r,o)}this._$Eh=new Map;for(let[e,r]of this.elementProperties){let o=this._$Eu(e,r);o!==void 0&&this._$Eh.set(o,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let e=[];if(Array.isArray(t)){let r=new Set(t.flat(1/0).reverse());for(let o of r)e.unshift(ge(o))}else t!==void 0&&e.push(ge(t));return e}static _$Eu(t,e){let r=e.attribute;return r===!1?void 0:typeof r=="string"?r:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,e=this.constructor.elementProperties;for(let r of e.keys())this.hasOwnProperty(r)&&(t.set(r,this[r]),delete this[r]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Re(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,r){this._$AK(t,r)}_$ET(t,e){let r=this.constructor.elementProperties.get(t),o=this.constructor._$Eu(t,r);if(o!==void 0&&r.reflect===!0){let n=(r.converter?.toAttribute!==void 0?r.converter:K).toAttribute(e,r.type);this._$Em=t,n==null?this.removeAttribute(o):this.setAttribute(o,n),this._$Em=null}}_$AK(t,e){let r=this.constructor,o=r._$Eh.get(t);if(o!==void 0&&this._$Em!==o){let n=r.getPropertyOptions(o),a=typeof n.converter=="function"?{fromAttribute:n.converter}:n.converter?.fromAttribute!==void 0?n.converter:K;this._$Em=o;let l=a.fromAttribute(e,n.type);this[o]=l??this._$Ej?.get(o)??l,this._$Em=null}}requestUpdate(t,e,r,o=!1,n){if(t!==void 0){let a=this.constructor;if(o===!1&&(n=this[t]),r??=a.getPropertyOptions(t),!((r.hasChanged??ie)(n,e)||r.useDefault&&r.reflect&&n===this._$Ej?.get(t)&&!this.hasAttribute(a._$Eu(t,r))))return;this.C(t,e,r)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,e,{useDefault:r,reflect:o,wrapped:n},a){r&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,a??e??this[t]),n!==!0||a!==void 0)||(this._$AL.has(t)||(this.hasUpdated||r||(e=void 0),this._$AL.set(t,e)),o===!0&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[o,n]of this._$Ep)this[o]=n;this._$Ep=void 0}let r=this.constructor.elementProperties;if(r.size>0)for(let[o,n]of r){let{wrapped:a}=n,l=this[o];a!==!0||this._$AL.has(o)||l===void 0||this.C(o,void 0,n,l)}}let t=!1,e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(r=>r.hostUpdate?.()),this.update(e)):this._$EM()}catch(r){throw t=!1,this._$EM(),r}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(t){}firstUpdated(t){}};E.elementStyles=[],E.shadowRootOptions={mode:"open"},E[V("elementProperties")]=new Map,E[V("finalized")]=new Map,kt?.({ReactiveElement:E}),(oe.reactiveElementVersions??=[]).push("2.1.2");var we=globalThis,Fe=i=>i,ne=we.trustedTypes,Le=ne?ne.createPolicy("lit-html",{createHTML:i=>i}):void 0,We="$lit$",N=`lit$${Math.random().toFixed(9).slice(2)}$`,Be="?"+N,St=`<${Be}>`,z=document,Y=()=>z.createComment(""),J=i=>i===null||typeof i!="object"&&typeof i!="function",_e=Array.isArray,At=i=>_e(i)||typeof i?.[Symbol.iterator]=="function",me=`[ 	
\f\r]`,X=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,ze=/-->/g,De=/>/g,F=RegExp(`>|${me}(?:([^\\s"'>=/]+)(${me}*=${me}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Ie=/'/g,He=/"/g,qe=/^(?:script|style|textarea|title)$/i,$e=i=>(t,...e)=>({_$litType$:i,strings:t,values:e}),x=$e(1),ae=$e(2),or=$e(3),D=Symbol.for("lit-noChange"),b=Symbol.for("lit-nothing"),Ue=new WeakMap,L=z.createTreeWalker(z,129);function je(i,t){if(!_e(i)||!i.hasOwnProperty("raw"))throw Error("invalid template strings array");return Le!==void 0?Le.createHTML(t):t}var Ct=(i,t)=>{let e=i.length-1,r=[],o,n=t===2?"<svg>":t===3?"<math>":"",a=X;for(let l=0;l<e;l++){let s=i[l],c,h,d=-1,p=0;for(;p<s.length&&(a.lastIndex=p,h=a.exec(s),h!==null);)p=a.lastIndex,a===X?h[1]==="!--"?a=ze:h[1]!==void 0?a=De:h[2]!==void 0?(qe.test(h[2])&&(o=RegExp("</"+h[2],"g")),a=F):h[3]!==void 0&&(a=F):a===F?h[0]===">"?(a=o??X,d=-1):h[1]===void 0?d=-2:(d=a.lastIndex-h[2].length,c=h[1],a=h[3]===void 0?F:h[3]==='"'?He:Ie):a===He||a===Ie?a=F:a===ze||a===De?a=X:(a=F,o=void 0);let f=a===F&&i[l+1].startsWith("/>")?" ":"";n+=a===X?s+St:d>=0?(r.push(c),s.slice(0,d)+We+s.slice(d)+N+f):s+N+(d===-2?l:f)}return[je(i,n+(i[e]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),r]},Q=class i{constructor({strings:t,_$litType$:e},r){let o;this.parts=[];let n=0,a=0,l=t.length-1,s=this.parts,[c,h]=Ct(t,e);if(this.el=i.createElement(c,r),L.currentNode=this.el.content,e===2||e===3){let d=this.el.content.firstChild;d.replaceWith(...d.childNodes)}for(;(o=L.nextNode())!==null&&s.length<l;){if(o.nodeType===1){if(o.hasAttributes())for(let d of o.getAttributeNames())if(d.endsWith(We)){let p=h[a++],f=o.getAttribute(d).split(N),u=/([.?@])?(.*)/.exec(p);s.push({type:1,index:n,name:u[2],strings:f,ctor:u[1]==="."?fe:u[1]==="?"?ve:u[1]==="@"?ye:U}),o.removeAttribute(d)}else d.startsWith(N)&&(s.push({type:6,index:n}),o.removeAttribute(d));if(qe.test(o.tagName)){let d=o.textContent.split(N),p=d.length-1;if(p>0){o.textContent=ne?ne.emptyScript:"";for(let f=0;f<p;f++)o.append(d[f],Y()),L.nextNode(),s.push({type:2,index:++n});o.append(d[p],Y())}}}else if(o.nodeType===8)if(o.data===Be)s.push({type:2,index:n});else{let d=-1;for(;(d=o.data.indexOf(N,d+1))!==-1;)s.push({type:7,index:n}),d+=N.length-1}n++}}static createElement(t,e){let r=z.createElement("template");return r.innerHTML=t,r}};function H(i,t,e=i,r){if(t===D)return t;let o=r!==void 0?e._$Co?.[r]:e._$Cl,n=J(t)?void 0:t._$litDirective$;return o?.constructor!==n&&(o?._$AO?.(!1),n===void 0?o=void 0:(o=new n(i),o._$AT(i,e,r)),r!==void 0?(e._$Co??=[])[r]=o:e._$Cl=o),o!==void 0&&(t=H(i,o._$AS(i,t.values),o,r)),t}var be=class{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:e},parts:r}=this._$AD,o=(t?.creationScope??z).importNode(e,!0);L.currentNode=o;let n=L.nextNode(),a=0,l=0,s=r[0];for(;s!==void 0;){if(a===s.index){let c;s.type===2?c=new Z(n,n.nextSibling,this,t):s.type===1?c=new s.ctor(n,s.name,s.strings,this,t):s.type===6&&(c=new xe(n,this,t)),this._$AV.push(c),s=r[++l]}a!==s?.index&&(n=L.nextNode(),a++)}return L.currentNode=z,o}p(t){let e=0;for(let r of this._$AV)r!==void 0&&(r.strings!==void 0?(r._$AI(t,r,e),e+=r.strings.length-2):r._$AI(t[e])),e++}},Z=class i{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,r,o){this.type=2,this._$AH=b,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=r,this.options=o,this._$Cv=o?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,e=this._$AM;return e!==void 0&&t?.nodeType===11&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=H(this,t,e),J(t)?t===b||t==null||t===""?(this._$AH!==b&&this._$AR(),this._$AH=b):t!==this._$AH&&t!==D&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):At(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==b&&J(this._$AH)?this._$AA.nextSibling.data=t:this.T(z.createTextNode(t)),this._$AH=t}$(t){let{values:e,_$litType$:r}=t,o=typeof r=="number"?this._$AC(t):(r.el===void 0&&(r.el=Q.createElement(je(r.h,r.h[0]),this.options)),r);if(this._$AH?._$AD===o)this._$AH.p(e);else{let n=new be(o,this),a=n.u(this.options);n.p(e),this.T(a),this._$AH=n}}_$AC(t){let e=Ue.get(t.strings);return e===void 0&&Ue.set(t.strings,e=new Q(t)),e}k(t){_e(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,r,o=0;for(let n of t)o===e.length?e.push(r=new i(this.O(Y()),this.O(Y()),this,this.options)):r=e[o],r._$AI(n),o++;o<e.length&&(this._$AR(r&&r._$AB.nextSibling,o),e.length=o)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){let r=Fe(t).nextSibling;Fe(t).remove(),t=r}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},U=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,r,o,n){this.type=1,this._$AH=b,this._$AN=void 0,this.element=t,this.name=e,this._$AM=o,this.options=n,r.length>2||r[0]!==""||r[1]!==""?(this._$AH=Array(r.length-1).fill(new String),this.strings=r):this._$AH=b}_$AI(t,e=this,r,o){let n=this.strings,a=!1;if(n===void 0)t=H(this,t,e,0),a=!J(t)||t!==this._$AH&&t!==D,a&&(this._$AH=t);else{let l=t,s,c;for(t=n[0],s=0;s<n.length-1;s++)c=H(this,l[r+s],e,s),c===D&&(c=this._$AH[s]),a||=!J(c)||c!==this._$AH[s],c===b?t=b:t!==b&&(t+=(c??"")+n[s+1]),this._$AH[s]=c}a&&!o&&this.j(t)}j(t){t===b?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},fe=class extends U{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===b?void 0:t}},ve=class extends U{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==b)}},ye=class extends U{constructor(t,e,r,o,n){super(t,e,r,o,n),this.type=5}_$AI(t,e=this){if((t=H(this,t,e,0)??b)===D)return;let r=this._$AH,o=t===b&&r!==b||t.capture!==r.capture||t.once!==r.once||t.passive!==r.passive,n=t!==b&&(r===b||o);o&&this.element.removeEventListener(this.name,this,r),n&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},xe=class{constructor(t,e,r){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=r}get _$AU(){return this._$AM._$AU}_$AI(t){H(this,t)}};var Et=we.litHtmlPolyfillSupport;Et?.(Q,Z),(we.litHtmlVersions??=[]).push("3.3.3");var Ge=(i,t,e)=>{let r=e?.renderBefore??t,o=r._$litPart$;if(o===void 0){let n=e?.renderBefore??null;r._$litPart$=o=new Z(t.insertBefore(Y(),n),n,void 0,e??{})}return o._$AI(i),o};var ke=globalThis,R=class extends E{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=Ge(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return D}};R._$litElement$=!0,R.finalized=!0,ke.litElementHydrateSupport?.({LitElement:R});var Tt=ke.litElementPolyfillSupport;Tt?.({LitElement:R});(ke.litElementVersions??=[]).push("4.2.2");var Ve=i=>(t,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(i,t)}):customElements.define(i,t)};var Pt={attribute:!0,type:String,converter:K,reflect:!1,hasChanged:ie},Nt=(i=Pt,t,e)=>{let{kind:r,metadata:o}=e,n=globalThis.litPropertyMetadata.get(o);if(n===void 0&&globalThis.litPropertyMetadata.set(o,n=new Map),r==="setter"&&((i=Object.create(i)).wrapped=!0),n.set(e.name,i),r==="accessor"){let{name:a}=e;return{set(l){let s=t.get.call(this);t.set.call(this,l),this.requestUpdate(a,s,i,!0,l)},init(l){return l!==void 0&&this.C(a,void 0,i,l),l}}}if(r==="setter"){let{name:a}=e;return function(l){let s=this[a];t.call(this,l),this.requestUpdate(a,s,i,!0,l)}}throw Error("Unsupported decorator location: "+r)};function se(i){return(t,e)=>typeof e=="object"?Nt(i,t,e):((r,o,n)=>{let a=o.hasOwnProperty(n);return o.constructor.createProperty(n,r),a?Object.getOwnPropertyDescriptor(o,n):void 0})(i,t,e)}function ee(i){return se({...i,state:!0,attribute:!1})}var w=i=>i??b;function Ke(i){return i?(Array.isArray(i)?i:[i]).filter(e=>!!e&&!!e.power):[]}var $={solar:"Solar",solar_total:"Solar Total",inverter:"Inverter",home:"Home",battery:"Battery",grid:"Grid",generator:"Generator"},T={solar:"mdi:solar-power",solar_total:"mdi:solar-power-variant-outline",inverter:"mdi:power-plug-outline",home:"mdi:home-lightning-bolt-outline",battery:"mdi:battery-high",grid:"mdi:transmission-tower",generator:"mdi:engine-outline"};function Xe(i,t){return t==="discharge_positive"?i:-i}function Ye(i,t){return t==="export_positive"?-i:i}var Rt=150;function Je(i,t,e){let r=t!==null&&e!==null?Math.max(0,t+e):null;return i===null||i===0&&r!==null&&r>Rt?r:Math.max(0,i)}function S(i,t){if(i==null||Number.isNaN(i))return"--";let e=t?.power_unit??"auto",r=Math.abs(i);if(e==="kw"||e==="auto"&&r>=1e3){let a=t?.precision??2;return`${(i/1e3).toFixed(a)} kW`}let n=t?.precision??0;return`${i.toFixed(n)} W`}function Qe(i,t){if(i==null||Number.isNaN(i))return"--";let e=t?.energy_precision??1;return`${i.toFixed(e)} kWh`}function Se(i){if(i==null||Number.isNaN(i))return"--";let t=Math.max(0,Math.min(1,i));return`${Math.round(t*100)}%`}function Ze(i){if(i==null||!Number.isFinite(i)||i<0)return"--";let t=Math.round(i);if(t===0)return i>0?"<1 min":"0 min";if(t<60)return`${t} min`;if(t<1440){let o=Math.floor(t/60),n=t%60;return n===0?`${o} h`:`${o} h ${n} min`}let e=Math.floor(t/1440),r=Math.floor(t%1440/60);return r===0?`${e} d`:`${e} d ${r} h`}function et(i){if(i==null||i==="unknown"||i==="unavailable"||i==="")return null;let t=Number(i);return Number.isFinite(t)?t:null}function tt(i,t){return i===null?{label:"--",colour:"battery-idle"}:i>=t?{label:"Discharging",colour:"battery-discharge"}:i<=-t?{label:"Charging",colour:"battery-charge"}:{label:"Idle",colour:"battery-idle"}}function rt(i,t){return i===null?{text:t?"--":"",fillPct:null}:{text:`${Math.round(i)}%`,fillPct:Math.max(0,Math.min(100,i))}}function ce(i){return i==="on"||i==="true"?"connected":i==="off"||i==="false"?"disconnected":"unknown"}function Ae(i){return i==="connected"?{value:"Connected",detailValue:"Yes",icon:"mdi:check-circle-outline",variant:"ok"}:i==="disconnected"?{value:"Disconnected",detailValue:"No",icon:"mdi:alert-circle-outline",variant:"fault"}:{value:"Unknown",detailValue:"Unknown",icon:"mdi:help-circle-outline"}}var Mt=new Map([["s",1/60],["min",1],["h",60],["d",1440]]);function ot(i,t,e){if(!i)return;let r=e==null||e===""?1:Mt.get(e);return r!==void 0&&t!==null&&t>=0?t*r:null}var ut=6e3,Ot=.45,it=2.6,C=5,nt=2.6,Ft=3.3,at=2.7,Lt=5.4,st=3.1,zt=4.9,Dt=.6,lt=5.5,It=2.4;function Ee(i){if(i<=C)return 0;let t=Math.log(i/C)/Math.log(ut/C),e=Math.min(1,Math.max(0,t));return Math.pow(e,It)}function Ht(i){return i<750?1:i<3e3?2:i<6e3?3:4}var Ut=1.3,ct=6.5,Wt=7,Bt=2.3;function qt(i,t){if(i==="connected-idle")return Wt;if(i==="disconnected")return Bt;let e=Ee(Math.abs(t));return ct-e*(ct-Ut)}var jt=15,dt=4,Gt=9,Vt=20,de=.4,W=.3,Ce=.52,ht=.4,Kt=["fault","alarm","error"],Xt=["warning","standby","self-check","self check"];function B(i){return`${i.x.toFixed(1)},${i.y.toFixed(1)}`}function Yt(i,t,e,r){let o=Math.hypot(i.x-t.x,i.y-t.y)||1,n=Math.hypot(e.x-i.x,e.y-i.y)||1,a=Math.max(0,Math.min(r,o*.5,n*.5));return{enter:{x:i.x-(i.x-t.x)/o*a,y:i.y-(i.y-t.y)/o*a},exit:{x:i.x+(e.x-i.x)/n*a,y:i.y+(e.y-i.y)/n*a},r:a}}function Jt(i,t,e,r,o,n,a){let s=t.x-i.x,c=t.y-i.y,h;if(e==="v"&&r==="v"&&Math.abs(s)<1.5)h=[];else if(e==="h"&&r==="h"&&Math.abs(c)<1.5)h=[];else if(e==="v"&&r==="v"){let g=i.y+c*o;h=[{x:i.x,y:g},{x:t.x,y:g}]}else if(e==="h"&&r==="h"){let g=i.x+s*o;h=[{x:g,y:i.y},{x:g,y:t.y}]}else e==="v"?h=[{x:i.x,y:t.y}]:h=[{x:t.x,y:i.y}];let d=[i,...h,t],p=a?[...d].reverse():d,f=`M ${B(p[0])}`,u=p[0];for(let g=1;g<p.length-1;g++){let v=p[g-1],y=p[g],_=p[g+1],k=Yt(y,v,_,n);k.r>=1?(f+=` L ${B(k.enter)} Q ${B(y)} ${B(k.exit)}`,u=k.exit):(f+=` L ${B(y)}`,u=y)}let m=p[p.length-1];return f+=` L ${B(m)}`,{d:f,arrowTangentFrom:u,end:m}}var A=class extends R{constructor(){super(...arguments);this._detailsOpen=!1;this._ports={};this._flowSize={w:0,h:0};this._measureRaf=0;this._observedNodeCount=-1;this._ballRaf=0;this._ballPathLengthCache=new WeakMap}static getStubConfig(){return{type:"custom:ecco-energy-flow-card",title:"Energy Flow",nodes:{solar:{power:"sensor.solar_power"},inverter:{power:"sensor.inverter_power",state:"sensor.inverter_state"},home:{power:"sensor.home_power"},battery:{power:"sensor.battery_power",soc:"sensor.battery_soc",power_sign:"charge_positive"},grid:{power:"sensor.grid_power",power_sign:"import_positive"}},today:{solar:"sensor.solar_energy_today",load:"sensor.load_energy_today",import:"sensor.grid_import_today",export:"sensor.grid_export_today",battery_charge:"sensor.battery_charge_today",battery_discharge:"sensor.battery_discharge_today"}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-flow-card: invalid configuration");if(!e.nodes||Object.keys(e.nodes).length===0)throw new Error("ecco-energy-flow-card: at least one entry under `nodes:` is required");this._config=e}getCardSize(){return 5}shouldUpdate(e){return this._config?e.has("_config")||e.has("_detailsOpen")||e.has("_ports")||e.has("_flowSize")?!0:e.has("hass"):!1}firstUpdated(){this._syncResizeObserver(),this._scheduleMeasure(),this._animateBalls()}updated(e){e.has("_config")&&this._syncResizeObserver(),(e.has("_config")||e.has("_flowSize"))&&this._scheduleMeasure()}disconnectedCallback(){super.disconnectedCallback(),this._resizeObserver?.disconnect(),this._measureRaf&&cancelAnimationFrame(this._measureRaf),this._ballRaf&&cancelAnimationFrame(this._ballRaf)}_syncResizeObserver(){let e=this.shadowRoot;if(!e)return;let r=e.querySelector(".flow"),o=e.querySelectorAll(".node-html");r&&(this._observedNodeCount===o.length&&this._resizeObserver||(this._observedNodeCount=o.length,this._resizeObserver?.disconnect(),this._resizeObserver=new ResizeObserver(()=>this._scheduleMeasure()),this._resizeObserver.observe(r),o.forEach(n=>this._resizeObserver.observe(n))))}_scheduleMeasure(){this._measureRaf&&cancelAnimationFrame(this._measureRaf),this._measureRaf=requestAnimationFrame(()=>{this._measureRaf=0,this._measurePorts()})}_measurePorts(){let e=this.shadowRoot,r=e?.querySelector(".flow");if(!e||!r)return;let o=r.getBoundingClientRect();if(o.width<1||o.height<1)return;let n={};e.querySelectorAll("[data-port]").forEach(s=>{let c=s.dataset.port;if(!c)return;let h=s.getBoundingClientRect();n[c]={x:h.left+h.width/2-o.left,y:h.top+h.height/2-o.top}});let a=.1;Object.keys(n).length===Object.keys(this._ports).length&&Object.entries(n).every(([s,c])=>{let h=this._ports[s];return h&&Math.abs(h.x-c.x)<a&&Math.abs(h.y-c.y)<a})||(this._ports=n),(Math.abs(this._flowSize.w-o.width)>a||Math.abs(this._flowSize.h-o.height)>a)&&(this._flowSize={w:o.width,h:o.height})}_state(e){if(!(!e||!this.hass))return this.hass.states[e]}_numeric(e){return et(this._state(e)?.state)}_gridState(e,r){let o=ce(r)==="disconnected",n=r==="unavailable"||r==="unknown";return o?{kind:"disconnected",colour:"grid-disconnected",statusLabel:"Disconnected"}:n||e===null?{kind:"unavailable",colour:"grid-unavailable",statusLabel:"Unavailable"}:Math.abs(e)<C?{kind:"connected-idle",colour:"grid-idle",statusLabel:"Idle"}:e>0?{kind:"importing",colour:"grid-import",statusLabel:"Importing"}:{kind:"exporting",colour:"grid-export",statusLabel:"Exporting"}}render(){if(!this._config)return x``;let e=this._config,r=e.nodes??{},o=Ke(r.solar),n=o.map(j=>this._numeric(j.power)??0),a=this._numeric(r.inverter?.power),l=this._numeric(r.battery?.power),s=l===null?null:Xe(l,r.battery?.power_sign),c=this._numeric(r.battery?.soc),h=!!r.battery?.soc,d=r.battery?.time_to_reserve,p=ot(d,this._numeric(d),this._state(d)?.attributes?.unit_of_measurement),f=this._numeric(r.grid?.power),u=f===null?null:Ye(f,r.grid?.power_sign),m=this._state(e.inverter_details?.grid_connected)?.state,g=this._gridState(u,m),v=Je(this._numeric(r.home?.power),a,u),y=!!r.generator?.power,_=y?this._numeric(r.generator?.power)??0:null,k=this._layout(o,y,this._flowSize.w||360),q={solar:o.map(j=>j.power),solarTotal:r.solar_total,inverter:r.inverter?.power??r.inverter?.state,home:r.home?.power,battery:r.battery?.power??r.battery?.soc,grid:r.grid?.power,generator:r.generator?.power},I=this._numeric(r.solar_total),P=n.reduce((j,gt)=>j+gt,0),M=o.length>1?I??P:null,he=this._buildLines(k,{solarPowers:n,homeW:v,batteryW:s,gridW:u,gridState:g,generatorW:_,combinerW:M}),Te=this._state(r.inverter?.state)?.state,pt=this._severityFor(Te);return x`
      <ha-card>
        ${e.title?x`<h1 class="card-title">${e.title}</h1>`:b}
        <div class="content">
          ${this._renderFlow(k,he,{solarPowers:n,inverterW:a,homeW:v,batteryW:s,batterySoc:c,batterySocConfigured:h,timeToReserveMinutes:p,gridW:u,gridState:g,generatorW:_,combinerW:M},Te,pt,q)}
          ${this._renderQuickMetrics()}
          ${this._renderToday()}
          ${this._renderBadges()}
          ${this._renderDetailsToggle()}
        </div>
      </ha-card>
    `}_fanOut(e,r,o=40){if(e<=0)return[];if(e===1)return[r/2];let n=r-o*2;return Array.from({length:e},(a,l)=>o+n*l/(e-1))}_layout(e,r,o){let a=e.length>0,l=o>=550,s=l?215:189,c=a?176:108,h=[],d=null;if(a){let k=this._fanOut(e.length,360,96),q=e.length===2?[110,270]:k;h=e.map((I,P)=>({kind:"solar",id:`solar-${P}`,label:I.label??(e.length>1?`${$.solar} ${P+1}`:$.solar),icon:I.icon??T.solar,x:q[P],y:46})),e.length>2&&(d={kind:"solar_total",id:"solar-total",label:$.solar_total,icon:T.solar_total,x:190,y:108})}let p={kind:"inverter",id:"inverter",label:$.inverter,icon:T.inverter,x:s,y:c},f=58,u={kind:"home",id:"home",label:$.home,icon:T.home,x:s+(l?46:30),y:c+100},m=r?{kind:"generator",id:"generator",label:$.generator,icon:T.generator,x:u.x+f,y:u.y}:null,g={kind:"battery",id:"battery",label:$.battery,icon:T.battery,x:s-140,y:c+74},v={kind:"grid",id:"grid",label:$.grid,icon:T.grid,x:s+(l?95:123),y:c-26};return{inverter:p,solar:h,solarTotal:d,home:u,battery:g,grid:v,generator:m}}_buildLines(e,r){let o=[],n=this._ports,a=u=>n[u]??null,l=a("inverter-pv"),s=a("inverter-battery"),c=a("inverter-grid"),h=a("inverter-home");if(!l||!s||!c||!h)return o;if(e.solarTotal){let u=a("solar-total");u&&(e.solar.forEach((m,g)=>{let v=a(m.id);v&&o.push(this._routeLine(m.id,v,u,"v","v",W,r.solarPowers[g]??0,!1,!1,"solar"))}),o.push(this._routeLine("solar-total",u,l,"v","v",W,r.combinerW??0,!1,!1,"solar")))}else if(e.solar.length>=2){let u=e.solar.map(m=>a(m.id));if(u.every(m=>!!m)){let m=u.reduce((v,y)=>v+y.y,0)/u.length,g={x:l.x,y:m+(l.y-m)*ht};e.solar.forEach((v,y)=>{o.push(this._routeLine(v.id,u[y],g,"v","v",W,r.solarPowers[y]??0,!1,!1,"solar"))}),o.push(this._routeLine("pv-trunk",g,l,"v","v",W,r.combinerW??0,!1,!1,"solar"))}}else if(e.solar.length===1){let u=a(e.solar[0].id);u&&o.push(this._routeLine(e.solar[0].id,u,l,"v","v",W,r.solarPowers[0]??0,!1,!1,"solar"))}let d=a("home");d&&o.push(this._routeLine("home",h,d,"v","v",W,r.homeW??0,r.homeW===null,!1,"home"));let p=a("battery");if(p){let u=r.batteryW??0,g=r.batteryW===null||Math.abs(u)<C?"battery-idle":u>=0?"battery-discharge":"battery-charge";o.push(this._routeLine("battery",p,s,"h","h",Ce,u,r.batteryW===null,!0,g))}let f=a("grid");if(f){let u=r.gridW??0,{kind:m,colour:g}=r.gridState,v=m==="disconnected"||m==="unavailable";o.push(this._routeLine("grid",f,c,"h","h",Ce,u,v,!0,g))}if(e.generator){let u=a("generator");u&&o.push(this._routeLine("generator",u,h,"v","v",Ce,r.generatorW??0,r.generatorW===null,!1,"generator"))}return o}_routeLine(e,r,o,n,a,l,s,c,h,d){let p=Math.abs(s),f=c||p<C,u=h&&s<0,m=o.x-r.x,g=o.y-r.y,v=Math.hypot(m,g)||1,y=m/v,_=g/v,k={x:r.x+y*de,y:r.y+_*de},q={x:o.x-y*de,y:o.y-_*de},{d:I,arrowTangentFrom:P,end:M}=Jt(k,q,n,a,l,Vt,u),he=Math.atan2(M.y-P.y,M.x-P.x)*180/Math.PI;return{id:e,d:I,magnitudeW:p,idle:f,colour:d,arrow:{x:M.x,y:M.y,angleDeg:he}}}_renderFlow(e,r,o,n,a,l){let c=e.home.y+60,h=`aspect-ratio: 360 / ${c};`,d=this._config,p=e.solar.length>2,f=this._flowSize.w||360,u=this._flowSize.h||c,m=this._computeJunction(e),g=!e.solarTotal&&e.solar.length>=2;return x`
      <div class="flow" style=${h}>
        <svg
          class="flow-svg"
          width=${f}
          height=${u}
          viewBox="0 0 ${f} ${u}"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Live energy flow"
        >
          ${r.map(v=>this._renderLine(v))}
          ${m?this._renderJunction(m,(o.combinerW??0)<C):b}
          ${r.map(v=>this._renderEnergyBalls(v))}
        </svg>
        ${e.solar.map((v,y)=>this._renderSolarNode(v,S(o.solarPowers[y]??0,d.format),360,c,p,(o.solarPowers[y]??0)<C,l.solar[y]))}
        ${e.solarTotal?this._renderSolarTotalNode(e.solarTotal,S(o.combinerW??void 0,d.format),360,c,(o.combinerW??0)<C,l.solarTotal):b}
        ${this._renderInverterNode(e.inverter,o.inverterW,g?o.combinerW:null,n,a,360,c,l.inverter)}
        ${this._renderBottomNode(e.home,o,360,c,l)}
        ${this._renderBottomNode(e.battery,o,360,c,l)}
        ${this._renderBottomNode(e.grid,o,360,c,l)}
        ${e.generator?this._renderBottomNode(e.generator,o,360,c,l):b}
      </div>
    `}_computeJunction(e){if(e.solarTotal||e.solar.length<2)return null;let r=this._ports["inverter-pv"],o=e.solar.map(a=>this._ports[a.id]);if(!r||!o.every(a=>!!a))return null;let n=o.reduce((a,l)=>a+l.y,0)/o.length;return{x:r.x,y:n+(r.y-n)*ht}}_renderJunction(e,r){return ae`<circle class="flow-junction colour-solar${r?" idle":""}" cx=${e.x.toFixed(1)} cy=${e.y.toFixed(1)} r="3.2"></circle>`}_renderLine(e){let r=Ee(e.magnitudeW),o=it-r*(it-Ot),n=Math.min(1,e.magnitudeW/ut),a=nt+n*(Ft-nt),l=at+r*(Lt-at),s=`--ecco-line-w:${a.toFixed(2)}`,c=dt+r*(Gt-dt),h=jt-c,d=(.62+r*.36).toFixed(2),p=(1.6+r*2.4).toFixed(1),f=`animation-duration:${o.toFixed(2)}s; --ecco-line-w:${l.toFixed(2)}; stroke-dasharray:${c.toFixed(1)} ${h.toFixed(1)}; opacity:${d}; --ecco-glow-px:${p}px`,u=e.idle?" idle":"",m=`colour-${e.colour}`,g=`translate(${e.arrow.x.toFixed(1)},${e.arrow.y.toFixed(1)}) rotate(${e.arrow.angleDeg.toFixed(1)})`;return ae`
      <path id="flow-path-${e.id}" class="flow-line-base ${m}${u}" data-line-id=${e.id} style=${s} d=${e.d}></path>
      <path class="flow-line-anim ${m}${u}" style=${f} d=${e.d}></path>
      <polygon
        class="flow-arrow ${m}${u}"
        points="0,-3 6,0 0,3"
        transform=${g}
      ></polygon>
    `}_renderEnergyBalls(e){if(e.idle)return[];let r=Ee(e.magnitudeW),o=lt-r*(lt-Dt),n=st+r*(zt-st),a=(3+r*3).toFixed(1),l=Ht(e.magnitudeW),s=`colour-${e.colour}`,c=`flow-path-${e.id}`;return Array.from({length:l},(h,d)=>ae`
        <g
          class="energy-ball ${s}"
          data-ball-path=${c}
          data-ball-duration=${o.toFixed(3)}
          data-ball-phase=${(d/l).toFixed(3)}
          style=${`--ecco-ball-glow:${a}px`}
        >
          <circle class="ball-glow" r=${n.toFixed(2)}></circle>
          <circle class="ball-core" r=${(n*.42).toFixed(2)}></circle>
        </g>
      `)}_animateBalls(){this._ballRaf=requestAnimationFrame(()=>this._animateBalls());let e=this.shadowRoot;if(!e||window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches)return;let r=e.querySelectorAll(".energy-ball");if(!r.length)return;let o=performance.now()/1e3;r.forEach(n=>{let a=n.dataset.ballPath,l=parseFloat(n.dataset.ballDuration??""),s=parseFloat(n.dataset.ballPhase??"0");if(!a||!l)return;let c=e.querySelector(`#${CSS.escape(a)}`);if(!c)return;let h=this._ballPathLengthCache.get(c),d=c.getAttribute("d")??"";if((!h||h.d!==d)&&(h={d,length:c.getTotalLength()},this._ballPathLengthCache.set(c,h)),!h.length)return;let p=(o/l+s)%1*h.length,f=c.getPointAtLength(p);n.setAttribute("transform",`translate(${f.x.toFixed(2)},${f.y.toFixed(2)})`)})}_positionStyle(e,r,o){let n=(e.x/r*100).toFixed(2),a=(e.y/o*100).toFixed(2);return`left:${n}%; top:${a}%;`}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_renderNode(e,r,o,n,a="home",l=!1,s=!1,c){let h=!!c;return x`
      <div class="node-html" style=${this._positionStyle(e,o,n)}>
        <div
          class="node-box colour-${a}${l?" dense":""}${s?" idle":""}${h?" clickable":""}"
          tabindex=${w(h?0:void 0)}
          role=${w(h?"button":void 0)}
          @click=${()=>this._moreInfo(c)}
          @keydown=${d=>{h&&(d.key==="Enter"||d.key===" ")&&(d.preventDefault(),this._moreInfo(c))}}
        >
          <ha-icon icon=${e.icon}></ha-icon>
          <div class="node-text">
            <div class="node-label">${e.label}</div>
            <div class="node-value">${r}</div>
          </div>
          <span class="node-port port-top" data-port=${e.id} aria-hidden="true"></span>
        </div>
      </div>
    `}_renderSolarNode(e,r,o,n,a=!1,l=!1,s){let c=!!s,h=Array.from({length:a?6:8});return x`
      <div class="node-html" style=${this._positionStyle(e,o,n)}>
        <div
          class="node-box solar-node colour-solar${a?" dense":""}${l?" idle":""}${c?" clickable":""}"
          tabindex=${w(c?0:void 0)}
          role=${w(c?"button":void 0)}
          @click=${()=>this._moreInfo(s)}
          @keydown=${d=>{c&&(d.key==="Enter"||d.key===" ")&&(d.preventDefault(),this._moreInfo(s))}}
        >
          <div class="solar-node-header">
            <span class="solar-node-title">
              <span class="solar-sun" aria-hidden="true"></span>
              <span class="node-label">${e.label}</span>
            </span>
            <span class="node-value">${r}</span>
          </div>
          <div class="panel-grid" aria-hidden="true">${h.map(()=>x`<span class="panel-cell"></span>`)}</div>
          <span class="node-port port-bottom" data-port=${e.id} aria-hidden="true"></span>
        </div>
      </div>
    `}_renderSolarTotalNode(e,r,o,n,a=!1,l){let s=!!l;return x`
      <div class="node-html" style=${this._positionStyle(e,o,n)}>
        <div
          class="node-box combiner colour-solar${a?" idle":""}${s?" clickable":""}"
          tabindex=${w(s?0:void 0)}
          role=${w(s?"button":void 0)}
          @click=${()=>this._moreInfo(l)}
          @keydown=${c=>{s&&(c.key==="Enter"||c.key===" ")&&(c.preventDefault(),this._moreInfo(l))}}
        >
          <ha-icon icon=${e.icon}></ha-icon>
          <div class="node-text">
            <div class="node-label">${e.label}</div>
            <div class="node-value">${r}</div>
          </div>
          <span class="node-port port-bottom" data-port="solar-total" aria-hidden="true"></span>
        </div>
      </div>
    `}_renderInverterNode(e,r,o,n,a,l,s,c){let h=this._config,d=!!c;return x`
      <div class="node-html inverter-node" style=${this._positionStyle(e,l,s)}>
        <div
          class="inverter-box severity-${a}${d?" clickable":""}"
          tabindex=${w(d?0:void 0)}
          role=${w(d?"button":void 0)}
          @click=${()=>this._moreInfo(c)}
          @keydown=${p=>{d&&(p.key==="Enter"||p.key===" ")&&(p.preventDefault(),this._moreInfo(c))}}
        >
          <span class="inverter-port port-pv" data-port="inverter-pv" aria-hidden="true"></span>
          <span class="inverter-port port-battery" data-port="inverter-battery" aria-hidden="true"></span>
          <span class="inverter-port port-grid" data-port="inverter-grid" aria-hidden="true"></span>
          <span class="inverter-port port-home" data-port="inverter-home" aria-hidden="true"></span>
          <ha-icon icon=${T.inverter}></ha-icon>
          <div class="node-label">${$.inverter}</div>
          ${o!==null?x`
                <div class="inverter-metrics">
                  <div class="inverter-metric-row">
                    <span class="inverter-metric-label">PV IN</span>
                    <span class="inverter-metric-value">${S(o??void 0,h.format)}</span>
                  </div>
                  <div class="inverter-metric-row">
                    <span class="inverter-metric-label">AC OUT</span>
                    <span class="inverter-metric-value">${S(r??void 0,h.format)}</span>
                  </div>
                </div>
              `:x`
                <div class="node-value inverter-value">${S(r??void 0,h.format)}</div>
                <div class="inverter-caption">AC Output</div>
              `}
          ${n?x`<div class="state-pill severity-${a}">${n}</div>`:b}
        </div>
      </div>
    `}_renderBottomNode(e,r,o,n,a){let l=this._config,s=this._positionStyle(e,o,n),c=!1;if(e.kind==="home")return this._renderNode(e,S(r.homeW??void 0,l.format),o,n,"home",c,!1,a.home);if(e.kind==="battery"){let{text:h,fillPct:d}=rt(r.batterySoc,r.batterySocConfigured),p=S(r.batteryW!==null?Math.abs(r.batteryW):void 0,l.format),{label:f,colour:u}=tt(r.batteryW,C),m=a.battery,g=!!m,v=d!==null?`--ecco-soc:${d}%`:"",y=r.timeToReserveMinutes!==void 0?`Time to reserve: ${Ze(r.timeToReserveMinutes)}`:void 0;return x`
        <div class="node-html" style=${s}>
          <div class="battery-shell">
            <span class="battery-terminal colour-${u}" aria-hidden="true"></span>
            <div
              class="node-box battery-box colour-${u}${g?" clickable":""}${d===null?" soc-unknown":""}"
              style=${v}
              title=${w(y)}
              tabindex=${w(g?0:void 0)}
              role=${w(g?"button":void 0)}
              @click=${()=>this._moreInfo(m)}
              @keydown=${_=>{g&&(_.key==="Enter"||_.key===" ")&&(_.preventDefault(),this._moreInfo(m))}}
            >
              <div class="node-text">
                <div class="node-label">${$.battery} ${h}</div>
                <div class="node-value">${p}</div>
                <div class="node-sub">${f}</div>
              </div>
              ${d!==null?x`<div class="soc-track"><div class="soc-fill" style="width:${d}%"></div></div>`:b}
              <span class="node-port port-right" data-port="battery" aria-hidden="true"></span>
            </div>
          </div>
        </div>
      `}if(e.kind==="grid"){let h=r.gridW,{kind:d,colour:p,statusLabel:f}=r.gridState,u=a.grid,m=!!u,g=d!=="unavailable",v=g?`--ecco-pylon-pulse-duration:${qt(d,h??0).toFixed(2)}s`:"";return x`
        <div class="node-html" style=${s}>
          <div
            class="node-box grid-box colour-${p}${m?" clickable":""}"
            tabindex=${w(m?0:void 0)}
            role=${w(m?"button":void 0)}
            @click=${()=>this._moreInfo(u)}
            @keydown=${y=>{m&&(y.key==="Enter"||y.key===" ")&&(y.preventDefault(),this._moreInfo(u))}}
          >
            <div class="node-text grid-text">
              <div class="node-label">${$.grid}</div>
              <div class="node-value">${S(h??void 0,l.format)}</div>
              <div class="node-sub">${f}</div>
            </div>
            <div class="grid-graphic${g?" pylon-pulse":""}" style=${v} aria-hidden="true">
              <span class="pylon-leg leg-left"></span>
              <span class="pylon-leg leg-right"></span>
              <span class="pylon-arm arm-top"></span>
              <span class="pylon-arm arm-mid"></span>
              <span class="pylon-arm arm-base"></span>
            </div>
            <span class="node-port port-left" data-port="grid" aria-hidden="true"></span>
          </div>
        </div>
      `}return this._renderNode(e,S(r.generatorW??void 0,l.format),o,n,"generator",c,!1,a.generator)}_renderQuickMetrics(){let e=this._config.inverter_details;if(!e)return b;let r=[],o=this._numeric(e.grid_voltage);o!==null&&r.push({icon:"mdi:sine-wave",label:"Grid Voltage",value:`${o.toFixed(0)} V`});let n=this._numeric(e.ac_temperature);n!==null&&r.push({icon:"mdi:thermometer",label:"AC Temp",value:`${n.toFixed(1)}\xB0C`});let a=this._numeric(e.dc_temperature);if(a!==null&&r.push({icon:"mdi:thermometer-lines",label:"DC Temp",value:`${a.toFixed(1)}\xB0C`}),e.grid_connected){let s=this._state(e.grid_connected)?.state;if(s!==void 0){let{value:c,icon:h,variant:d}=Ae(ce(s));r.push({icon:h,label:"Grid Connected",value:c,variant:d})}}let l=this._numeric(e.frequency);return l!==null&&r.push({icon:"mdi:waveform",label:"Frequency",value:`${l.toFixed(2)} Hz`}),r.length===0?b:x`
      <div class="quick-metrics">
        ${r.map(s=>x`
            <div class="quick-metric${s.variant?` variant-${s.variant}`:""}">
              <ha-icon icon=${s.icon}></ha-icon>
              <div class="quick-metric-text">
                <span class="quick-metric-label">${s.label}</span>
                <span class="quick-metric-value">${s.value}</span>
              </div>
            </div>
          `)}
      </div>
    `}_renderToday(){let e=this._config,r=e.today;if(!r)return b;let o=[],n=(s,c,h)=>{if(!c)return;let d=this._numeric(c);o.push({label:s,value:Qe(d,e.format),colour:h})};if(n("Solar",r.solar,"solar"),n("Load",r.load,"home"),n("Imported",r.import,"grid-import"),n("Exported",r.export,"grid-export"),n("Charged",r.battery_charge,"battery-charge"),n("Discharged",r.battery_discharge,"battery-discharge"),o.length===0)return b;let a=e.features?.compact_today??!1,l=this._solarShareText();return x`
      <div class="today ${a?"compact":""}">
        <div class="today-heading-row">
          <span class="today-heading">Today</span>
          ${l?x`<span class="today-solar-share">Solar Share <strong>${l}</strong></span>`:b}
        </div>
        <div class="today-grid">
          ${o.map(s=>x`
              <div class="today-item colour-${s.colour}">
                <span class="today-label">${s.label}</span>
                <span class="today-value">${s.value}</span>
              </div>
            `)}
        </div>
      </div>
    `}_solarShareText(){let e=this._config,r=e.today,o=e.features;if(!r||!o?.solar_contribution)return null;let n=this._numeric(r.load);if(!n||n<=0)return null;let a=this._numeric(r.solar)??0;return Se(a/n)}_renderBadges(){let e=this._config,r=e.today,o=e.features;if(!r||!o?.self_sufficiency)return b;let n=this._numeric(r.load);if(!n||n<=0)return b;let l=1-(this._numeric(r.import)??0)/n;return x`<div class="badges"><div class="badge">Self-sufficiency <strong>${Se(l)}</strong></div></div>`}_renderDetailsToggle(){let e=this._config;if(e.features?.show_details_panel===!1)return b;let r=e.inverter_details,o=e.nodes?.inverter,n=r&&(r.temperature||r.ac_temperature||r.dc_temperature||r.grid_voltage||r.grid_connected||r.frequency||r.mode),a=o?.status;return!n&&!a?b:x`
      <button
        class="details-toggle"
        @click=${()=>this._detailsOpen=!this._detailsOpen}
        aria-expanded=${this._detailsOpen}
      >
        <span>Inverter details</span>
        <ha-icon icon=${this._detailsOpen?"mdi:chevron-up":"mdi:chevron-down"}></ha-icon>
      </button>
      ${this._detailsOpen?this._renderDetails():b}
    `}_renderDetails(){let e=this._config,r=e.inverter_details??{},o=e.nodes?.inverter,n=[];if(o?.status){let d=this._state(o.status)?.state;d&&n.push({label:"Status",value:d})}let a=this._numeric(r.temperature);a!==null&&n.push({label:"Temperature",value:`${a.toFixed(1)} \xB0C`});let l=this._numeric(r.ac_temperature);l!==null&&n.push({label:"AC Temperature",value:`${l.toFixed(1)} \xB0C`});let s=this._numeric(r.dc_temperature);s!==null&&n.push({label:"DC Temperature",value:`${s.toFixed(1)} \xB0C`});let c=this._numeric(r.grid_voltage);if(c!==null&&n.push({label:"Grid Voltage",value:`${c.toFixed(0)} V`}),r.grid_connected){let d=this._state(r.grid_connected)?.state;d!==void 0&&n.push({label:"Grid Connected",value:Ae(ce(d)).detailValue})}let h=this._numeric(r.frequency);if(h!==null&&n.push({label:"Frequency",value:`${h.toFixed(2)} Hz`}),r.mode){let d=this._state(r.mode)?.state;d&&n.push({label:"Mode",value:d})}return n.length===0?x`<div class="details"><div class="details-empty">No inverter detail entities configured.</div></div>`:x`
      <div class="details">
        ${n.map(d=>x`
            <div class="details-row">
              <span class="details-label">${d.label}</span>
              <span class="details-value">${d.value}</span>
            </div>
          `)}
      </div>
    `}_severityFor(e){if(!e)return"neutral";let r=e.toLowerCase();return Kt.some(o=>r.includes(o))?"fault":Xt.some(o=>r.includes(o))?"warning":r.includes("normal")||r.includes("ok")?"ok":"neutral"}};A.styles=pe`
    :host {
      /* Deliberately its own dedicated variable, --ecco-card-background,
         rather than reading the generic HA --card-background-color: a
         host theme frequently already claims that variable for its own
         purposes (e.g. a neutral charcoal/grey used across all cards
         uniformly), which silently overrides this card's own intended
         navy default with no way to opt back out short of fighting the
         theme with !important card_mod overrides from outside the
         card's shadow DOM - which do not reliably reach an internal
         custom property consumed this early in the cascade. A card-
         specific variable name means this card's own default (a real,
         complete navy look out of the box) is never accidentally
         inherited away, while remaining just as overridable as before
         for anyone who genuinely wants to re-theme it - set
         --ecco-card-background from outside instead. */
      --ecco-bg: var(--ecco-card-background, #141c2d);
      --ecco-surface: color-mix(in srgb, var(--ecco-bg) 82%, white 6%);
      --ecco-border: color-mix(in srgb, var(--ecco-bg) 70%, white 12%);
      --ecco-accent: var(--primary-color, #4fd1ff);
      --ecco-text: var(--primary-text-color, #eef2f7);
      --ecco-text-muted: var(--secondary-text-color, #9aa7b8);
      --ecco-ok: #38d996;
      --ecco-warning: #f4b942;
      --ecco-fault: #ff5c6c;
      --ecco-glow: color-mix(in srgb, var(--ecco-accent) 45%, transparent);

      /* Per-source/per-state flow line/icon/border colours. Plain literal
         fallbacks - no color-mix() or any other function in this specific
         chain - so the flow lines' critical paint path never depends on a
         CSS feature a given rendering context might not support. Override
         any of these from outside (a theme, or card-mod on this card) to
         match your own palette; nothing here is a colour baked directly
         into a selector without this variable indirection, and nothing
         here assumes an ECCO/Deye installation specifically.

         Battery and grid each have three STATE variants rather than one
         static colour (charge/discharge/idle, import/export/idle) - the
         line, the node's border, its subtle background tint, and its soft
         glow are all derived from whichever of these is currently active
         (see FlowColourKind/_buildLines()/_renderBottomNode()). Battery
         charge=green/discharge=orange matches the live "energy in vs
         energy out" convention the maintainer asked for; grid import=cyan/
         export=green-teal mirrors it without reusing the exact same hues. */
      --ecco-line-solar: #ffb454;
      --ecco-line-home: #7fb8ff;
      --ecco-line-grid-import: #45d9ff;
      --ecco-line-grid-export: #2dd4bf;
      /* Grid's 5-state model (this round): "idle" now specifically means
         connected + confirmed ~0W - genuinely alive, just quiet right now -
         so it moves to a muted steel-blue instead of the old flat grey.
         Grey is reserved for "unavailable" (no reliable signal either way).
         "disconnected" is a real fault signal only, never inferred from 0W
         power alone (see _gridState()'s own doc comment). */
      --ecco-line-grid-idle: #5b7a9e;
      --ecco-line-grid-disconnected: #e5484d;
      --ecco-line-grid-unavailable: #7c8a9e;
      --ecco-line-battery-charge: #43d17a;
      --ecco-line-battery-discharge: #ff8a3d;
      --ecco-line-battery-idle: #7c8a9e;
      --ecco-line-generator: #ffcf6b;
      display: block;
      /* Lets the narrow-card fix below (see .battery-box/.inverter-box/
         .grid-box's @container rule) query THIS element's own rendered
         width - the card's real width in whatever dashboard column it's
         placed in - rather than the browser viewport's width. A plain
         @media query would almost never fire correctly here: a narrow
         card commonly sits in a masonry/sidebar column on an otherwise
         wide desktop viewport, which is exactly the case that needs
         fixing. */
      container-type: inline-size;
    }

    ha-card {
      background: linear-gradient(160deg, var(--ecco-bg), color-mix(in srgb, var(--ecco-bg) 88%, black 8%));
      color: var(--ecco-text);
      border-radius: 20px;
      padding: 16px 16px 14px;
      overflow: hidden;
    }

    .card-title {
      font-size: 1.05rem;
      font-weight: 600;
      letter-spacing: 0.01em;
      margin: 2px 4px 10px;
      color: var(--ecco-text);
    }

    .content {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .flow {
      position: relative;
      /* Capped and centred rather than a plain 100% - on a normal-width
         card this is identical to before (min() just resolves to 100%),
         but on a much wider host (e.g. a full-width Home Assistant
         Sections column) it stops the diagram growing indefinitely. Since
         height is locked to width via aspect-ratio below, an uncapped
         100%-wide flow on a wide card grew tall enough to visually
         overlap the dashboard content beneath it - this is the actual fix
         for that, not a rows/grid_options change (which only affects how
         much space Home Assistant reserves, not how tall this SVG/HTML
         diagram wants to render). Raised 640 -> 840px (roughly +31%) per
         live-review feedback that the whole diagram still rendered too
         small, with too much unused space around it, on a normal-width
         card - node-box size/spacing (all still literal CSS px, untouched
         here) now render proportionally larger against the bigger canvas
         without needing every individual box resized to compensate.
         Quick Metrics/Today/badges/Details are siblings of .flow inside
         .content, not children of it, so this cap does not affect them -
         they still use the card's full available width. */
      width: min(100%, 840px);
      margin-inline: auto;
      /* aspect-ratio is also set inline per-render (it depends on whether
         solar/generator are configured) - this is just a safe fallback,
         matching the common case (solar configured, no generator). */
      aspect-ratio: 360 / 259;
      overflow: visible;
    }

    .flow-svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      overflow: visible;
      /* Lines never need to receive pointer events; letting clicks pass
         through means a future tap-action on a node card is never blocked
         by the line layer sitting behind it. */
      pointer-events: none;
    }

    /* Every line is drawn as TWO stacked <path> elements sharing the same
       "d" plus one arrowhead <polygon> - see _renderLine()'s own comment
       for why (guaranteed base visibility + no <marker>/url(#id) reference). */
    .flow-line-base {
      fill: none;
      /* Power-scaled per line (see _renderLine()'s inline style) - these
         numbers are just the fallback for a line with no magnitude yet. */
      stroke-width: var(--ecco-line-w, 3);
      stroke-linecap: round;
      /* Deliberately dim - this is the passive "bus/wire", not the
         indicator - but nudged 0.22 -> 0.29 (plus MIN/MAX_LINE_WIDTH_PX
         both up slightly) this round so the topology still reads clearly
         even when the packet overlay's own motion is subtle at low power;
         still comfortably under the 0.62-0.98 range that layer runs at,
         per the UniFi-topology "dim wire + bright travelling packets"
         brief. */
      opacity: 0.29;
      /* Battery/grid swap colour class (e.g. import -> export) on the same
         persisted <path> element, so this fades rather than snaps too -
         "where practical" per the maintainer's smooth-transitions request. */
      transition: stroke 0.28s ease;
    }
    /* The packet stream - see _renderLine()'s own doc comment for the
       full "why" (this replaced a round of animateMotion circle particles
       that didn't read as visible in live use). stroke-dasharray/opacity/
       --ecco-glow-px are all set inline per render, magnitude-scaled -
       the values here are just pre-JS-render fallbacks. */
    .flow-line-anim {
      fill: none;
      stroke-width: var(--ecco-line-w, 2.8);
      stroke-linecap: round;
      stroke-dasharray: 4 11;
      animation-name: ecco-dash;
      animation-timing-function: linear;
      animation-iteration-count: infinite;
      opacity: 0.8;
      filter: drop-shadow(0 0 var(--ecco-glow-px, 2px) currentColor);
      transition: stroke 0.28s ease;
    }
    .flow-line-base.idle,
    .flow-line-anim.idle,
    .flow-arrow.idle {
      opacity: 0.12;
    }
    .flow-line-anim.idle {
      animation-play-state: paused;
      filter: none;
    }
    @keyframes ecco-dash {
      to {
        stroke-dashoffset: -30;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      /* The always-solid base layer is untouched - a static, correctly
         coloured/oriented line remains visible; only the moving-dash
         packet stream is turned off - and the static arrowhead (normally
         hidden once a line's own dash pattern carries direction instead -
         see .flow-arrow below) reappears so direction is never lost, only
         the motion conveying it. */
      .flow-line-anim {
        animation: none;
        stroke-dasharray: none;
        filter: none;
      }
      .flow-arrow {
        opacity: 0.95;
      }
      .flow-arrow.idle {
        opacity: 0.12;
      }
      /* The energy-ball layer is pure motion with no static equivalent
         (unlike the dash stream, which still has a meaningful "off"
         state via stroke-dasharray:none) - so it's hidden outright here
         rather than frozen in place, where a stationary glowing dot
         sitting mid-route would just read as a rendering glitch. The
         base line + reappeared arrowhead above already carry direction
         without it. */
      .energy-ball {
        display: none;
      }
      /* Every other animation added for state-aware polish (Solar Total's
         glow pulse, the battery card's glow pulse/shimmer, the SOC bar's
         sheen) is motion-only decoration layered on top of state that is
         otherwise conveyed purely by colour - border/background/box-shadow
         are all set unconditionally in the rules above and untouched here,
         so turning the animation off never removes any actual information,
         only the movement itself. The shimmer/sheen pseudo-elements are
         also hidden outright rather than left as a static diagonal streak,
         which would just look like a rendering glitch once motionless. */
      .node-box.combiner,
      .battery-box {
        animation: none;
      }
      .battery-box::before,
      .soc-fill::after {
        animation: none;
        opacity: 0;
      }
      /* Pylon pulse (this round): colour alone still carries every Grid
         state unambiguously (see the colour-grid-* rules above) - the
         breathing glow is motion-only reinforcement on top of that, so it
         is simply turned off here, same treatment as every other purely
         decorative animation in this block. */
      .grid-graphic.pylon-pulse {
        animation: none;
        filter: none;
      }
    }

    /* Hidden by default now - the packet stream (.flow-line-anim's own
       magnitude-scaled dash pattern - see _renderLine()) is the primary
       direction indicator for an active line, and showing both would just
       duplicate the same information. Reappears (see the reduced-motion
       block above) for an idle line (nothing moving to show direction
       with) or when the OS/browser requests reduced motion (no travel
       animation to rely on there either). */
    .flow-arrow {
      opacity: 0;
      transition: fill 0.28s ease;
    }

    /* Energy-ball layer (this round's addition - see _renderEnergyBalls()'s
       own doc comment for why it's built as a bright core + coloured glow
       rather than a flat dot). pointer-events:none throughout - purely
       decorative, riding on top of everything else in the SVG. */
    .energy-ball {
      pointer-events: none;
    }
    .ball-glow {
      fill: currentColor;
      filter: drop-shadow(0 0 var(--ecco-ball-glow, 3px) currentColor);
    }
    .ball-core {
      fill: #fff9ec;
    }

    .colour-solar.flow-line-base,
    .colour-solar.flow-line-anim {
      stroke: var(--ecco-line-solar);
    }
    .colour-solar.flow-line-anim {
      color: var(--ecco-line-solar);
    }
    .colour-solar.flow-arrow {
      fill: var(--ecco-line-solar);
    }
    .colour-solar.energy-ball {
      color: var(--ecco-line-solar);
    }
    /* The PV bus junction dot (see _renderJunction()) - a real wiring-
       diagram "conductors joined here" marker, solid and static (no
       dash/animation of its own - the legs/trunk either side of it
       already carry the moving packets). Idle dims it in step with the
       rest of the solar family instead of leaving a bright dot sitting
       over a dark, sleeping bus. */
    .flow-junction {
      fill: var(--ecco-line-solar);
      opacity: 0.85;
      transition: opacity 0.28s ease;
    }
    .flow-junction.idle {
      opacity: 0.18;
    }
    .colour-home.flow-line-base,
    .colour-home.flow-line-anim {
      stroke: var(--ecco-line-home);
    }
    .colour-home.flow-line-anim {
      color: var(--ecco-line-home);
    }
    .colour-home.flow-arrow {
      fill: var(--ecco-line-home);
    }
    .colour-home.energy-ball {
      color: var(--ecco-line-home);
    }
    .colour-grid-import.flow-line-base,
    .colour-grid-import.flow-line-anim {
      stroke: var(--ecco-line-grid-import);
    }
    .colour-grid-import.flow-line-anim {
      color: var(--ecco-line-grid-import);
    }
    .colour-grid-import.flow-arrow {
      fill: var(--ecco-line-grid-import);
    }
    .colour-grid-import.energy-ball {
      color: var(--ecco-line-grid-import);
    }
    .colour-grid-export.flow-line-base,
    .colour-grid-export.flow-line-anim {
      stroke: var(--ecco-line-grid-export);
    }
    .colour-grid-export.flow-line-anim {
      color: var(--ecco-line-grid-export);
    }
    .colour-grid-export.flow-arrow {
      fill: var(--ecco-line-grid-export);
    }
    .colour-grid-export.energy-ball {
      color: var(--ecco-line-grid-export);
    }
    .colour-grid-idle.flow-line-base,
    .colour-grid-idle.flow-line-anim {
      stroke: var(--ecco-line-grid-idle);
    }
    .colour-grid-idle.flow-line-anim {
      color: var(--ecco-line-grid-idle);
    }
    .colour-grid-idle.flow-arrow {
      fill: var(--ecco-line-grid-idle);
    }
    .colour-grid-idle.energy-ball {
      color: var(--ecco-line-grid-idle);
    }
    .colour-grid-disconnected.flow-line-base,
    .colour-grid-disconnected.flow-line-anim {
      stroke: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-disconnected.flow-line-anim {
      color: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-disconnected.flow-arrow {
      fill: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-disconnected.energy-ball {
      color: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-unavailable.flow-line-base,
    .colour-grid-unavailable.flow-line-anim {
      stroke: var(--ecco-line-grid-unavailable);
    }
    .colour-grid-unavailable.flow-line-anim {
      color: var(--ecco-line-grid-unavailable);
    }
    .colour-grid-unavailable.flow-arrow {
      fill: var(--ecco-line-grid-unavailable);
    }
    .colour-grid-unavailable.energy-ball {
      color: var(--ecco-line-grid-unavailable);
    }
    .colour-battery-charge.flow-line-base,
    .colour-battery-charge.flow-line-anim {
      stroke: var(--ecco-line-battery-charge);
    }
    .colour-battery-charge.flow-line-anim {
      color: var(--ecco-line-battery-charge);
    }
    .colour-battery-charge.flow-arrow {
      fill: var(--ecco-line-battery-charge);
    }
    .colour-battery-charge.energy-ball {
      color: var(--ecco-line-battery-charge);
    }
    .colour-battery-discharge.flow-line-base,
    .colour-battery-discharge.flow-line-anim {
      stroke: var(--ecco-line-battery-discharge);
    }
    .colour-battery-discharge.flow-line-anim {
      color: var(--ecco-line-battery-discharge);
    }
    .colour-battery-discharge.flow-arrow {
      fill: var(--ecco-line-battery-discharge);
    }
    .colour-battery-discharge.energy-ball {
      color: var(--ecco-line-battery-discharge);
    }
    .colour-battery-idle.flow-line-base,
    .colour-battery-idle.flow-line-anim {
      stroke: var(--ecco-line-battery-idle);
    }
    .colour-battery-idle.flow-line-anim {
      color: var(--ecco-line-battery-idle);
    }
    .colour-battery-idle.flow-arrow {
      fill: var(--ecco-line-battery-idle);
    }
    .colour-battery-idle.energy-ball {
      color: var(--ecco-line-battery-idle);
    }
    .colour-generator.flow-line-base,
    .colour-generator.flow-line-anim {
      stroke: var(--ecco-line-generator);
    }
    .colour-generator.flow-line-anim {
      color: var(--ecco-line-generator);
    }
    .colour-generator.flow-arrow {
      fill: var(--ecco-line-generator);
    }
    .colour-generator.energy-ball {
      color: var(--ecco-line-generator);
    }

    .node-html {
      position: absolute;
      /* left/top are set inline per-node (percentage of the shared
         coordinate space) - this centres the card exactly on its point. */
      transform: translate(-50%, -50%);
      z-index: 1;
    }

    .node-box {
      display: flex;
      align-items: center;
      gap: 6px;
      width: 96px;
      padding: 6px 8px;
      border-radius: 12px;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      box-sizing: border-box;
      /* Anchors every node-box variant's own .node-port child (see its
         own CSS note) to ITS edges - variants that already set their own
         position (battery/grid/solar) simply repeat this, harmlessly. */
      position: relative;
      /* State changes (e.g. grid idle -> importing, solar sleeping ->
         active) fade in rather than snap - restrained, ~250-300ms, and
         never touches the live-data update itself, only how its colour
         change is painted. */
      transition:
        width 0.2s ease,
        border-color 0.28s ease,
        background 0.28s ease,
        box-shadow 0.28s ease;
    }
    /* Three or more solar arrays: a narrower card keeps the row from
       crowding/overlapping at typical card widths - see _fanOut()/the
       "dense" flag threaded through from _renderFlow(). */
    .node-box.dense {
      width: 74px;
      padding: 5px 6px;
      gap: 4px;
    }
    .node-box.dense ha-icon {
      --mdc-icon-size: 17px;
    }
    .node-box.dense .node-label,
    .node-box.dense .node-value {
      font-size: 0.6rem;
    }
    /* Home - compositional pass: previously wider (172px) than the
       inverter's own OLD width, which was part of why the inverter didn't
       read as the clear hub (see .inverter-box's own note). Brought down
       to sit in the same size family as Battery/Grid (132px) instead -
       still visually distinct via its own colour/glow/radius treatment,
       just no longer competing on sheer size. Keeps the same family
       treatment as .colour-solar (background/border/glow tint, using the
       existing --ecco-line-home blue, no new colour introduced).
       Hardware-identity FINAL pass: live review liked the house concept
       but found it still too shallow to read as one at a glance - taller
       now, with a genuinely bigger roof apex (12 -> 22px) over a taller
       body, and switched from an icon-left/text-right row to a stacked
       column (icon centred above the text, like the inverter's own hero
       treatment) so the silhouette reads as roof-over-body rather than a
       roof cut sitting oddly beside a horizontal row. clip-path only
       changes what's PAINTED, not the box's layout footprint, so this
       needed no markup change beyond the flex-direction switch below, and
       still doesn't disturb the port position above it (measured live off
       the real .node-port element - see the TRUE PORT GEOMETRY note above
       buildRouteD(), so a height change here needs no recalibration
       anywhere else). Its bottom two vertices sit exactly on the box's own
       bottom corners (not inset), so the existing 16px bottom rounding
       below still shows through untouched - only the top corners' 8px
       rounding is replaced by the roof cut. */
    .node-box.colour-home {
      width: 132px;
      padding: 20px 12px 13px;
      flex-direction: column;
      align-items: center;
      gap: 5px;
      text-align: center;
      border-radius: 8px 8px 16px 16px;
      background-color: color-mix(in srgb, var(--ecco-line-home) 14%, var(--ecco-surface));
      background-image: linear-gradient(to bottom, color-mix(in srgb, var(--ecco-line-home) 30%, transparent), transparent 22px);
      border-color: color-mix(in srgb, var(--ecco-line-home) 55%, var(--ecco-border));
      box-shadow: 0 0 14px -5px color-mix(in srgb, var(--ecco-line-home) 50%, transparent);
      clip-path: polygon(0 22px, 50% 0, 100% 22px, 100% 100%, 0 100%);
    }
    .node-box.colour-home ha-icon {
      --mdc-icon-size: 27px;
    }
    .node-box.colour-home .node-label {
      font-size: 0.74rem;
    }
    .node-box.colour-home .node-value {
      font-size: 1rem;
      font-weight: 700;
    }
    /* Solar Total / PV combiner node (see _renderSolarTotalNode): smaller
       and visually quieter than a regular node card, and much smaller than
       the inverter - it is a secondary "merge point", not another
       first-class node competing with the inverter for attention. The
       background is fully opaque (unlike an earlier pass that used a
       translucent fill) so the flow line's own arrival point, which is
       geometrically inset just under this box (see the line-routing
       method), is properly masked instead of visibly showing/bleeding
       through the label - the line should read as terminating AT the
       node, not running through it. Sized up again and given real warm-
       amber colour (border/background/glow, matching the solar family
       rather than a plain neutral box) per a later live-review pass, along
       with a slightly larger combiner->inverter gap in the layout method. */
    .node-box.combiner {
      width: 100px;
      padding: 7px 9px;
      gap: 4px;
      background: color-mix(in srgb, var(--ecco-line-solar) 14%, var(--ecco-surface));
      border: 1px dashed color-mix(in srgb, var(--ecco-line-solar) 60%, var(--ecco-border));
      box-shadow: 0 0 13px -5px color-mix(in srgb, var(--ecco-line-solar) 55%, transparent);
    }
    .node-box.combiner ha-icon {
      --mdc-icon-size: 19px;
    }
    .node-box.combiner .node-label {
      font-size: 0.66rem;
    }
    .node-box.combiner .node-value {
      font-size: 0.92rem;
      font-weight: 700;
    }
    /* A slow, restrained glow pulse while there is real solar generation
       flowing through the combiner - "while solar is active" per the maintainer's
       request. The :not(.idle) selector below ties this to the exact same
       near-zero check driving the node's own sleeping treatment, one
       condition, not two independent guesses. */
    @keyframes ecco-solar-pulse {
      0%,
      100% {
        box-shadow: 0 0 10px -6px color-mix(in srgb, var(--ecco-line-solar) 42%, transparent);
      }
      50% {
        box-shadow: 0 0 17px -4px color-mix(in srgb, var(--ecco-line-solar) 68%, transparent);
      }
    }
    .node-box.combiner:not(.idle) {
      animation: ecco-solar-pulse 4.5s ease-in-out infinite;
    }
    .node-box ha-icon {
      --mdc-icon-size: 22px;
      color: var(--ecco-accent);
      flex-shrink: 0;
      transition: color 0.28s ease;
    }
    /* Solar family (arrays + the Solar Total combiner, via the shared
       .colour-solar class) - a warm amber/gold accent: a stronger border,
       a very subtle warm background tint, and a soft glow, so generation
       reads as the visually "important" flow at a glance. Kept to a
       low-opacity tint/glow rather than a solid fill - still a dark,
       premium card, not a bright dashboard tile. */
    .node-box.colour-solar {
      border-color: color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-line-solar) 11%, var(--ecco-surface));
      box-shadow: 0 0 11px -5px color-mix(in srgb, var(--ecco-line-solar) 50%, transparent);
    }
    .node-box.colour-solar .node-value {
      font-weight: 700;
    }
    /* Solar Total combiner keeps its own deliberately smaller/subtler
       sizing above (see .node-box.combiner). Every OTHER solar node - one
       per string, at every source count now (see _renderSolarNode()) -
       shares this one hardware design: a compact chamfered panel
       enclosure with its own label+value header and a panel-cell strip
       beneath, reading as a real PV module rather than a generic tile.
       Sized to sit in the same size family as Battery/Grid/Home (roughly
       120-130px) so the whole network reads as one consistent set of
       hardware nodes around the inverter, not one oversized box and four
       small ones. The 3+-array "dense" variant stays narrower on purpose
       to avoid crowding a wider fan-out. */
    .node-box.colour-solar:not(.combiner) {
      width: 142px;
      padding: 9px 10px;
      border-radius: 10px;
      flex-direction: column;
      align-items: stretch;
      gap: 6px;
      background-image: linear-gradient(155deg, color-mix(in srgb, white 7%, transparent), transparent 65%);
      /* Panel-assembly treatment (hardware-identity pass): a chamfered,
         technical outline instead of a plain rounded rect - the same
         "clip the corner, keep the rest untouched" idea as a real PV
         module's frame corner. 6px stays well inside the padding, so it
         never touches the header/panel-strip content below. */
      position: relative;
      clip-path: polygon(6px 0, calc(100% - 6px) 0, 100% 6px, 100% calc(100% - 6px), calc(100% - 6px) 100%, 6px 100%, 0 calc(100% - 6px), 0 6px);
    }
    .node-box.colour-solar.dense {
      width: 92px;
      padding: 7px 8px;
    }
    /* Top/bottom "frame rail" cues - thin bars in a cooler, metallic tone
       (deliberately NOT the warm solar accent, so they read as aluminium
       framing rather than more amber glow) sitting flush on the chamfered
       top/bottom edges, like a module's own frame extrusion. */
    .node-box.colour-solar:not(.combiner)::before,
    .node-box.colour-solar:not(.combiner)::after {
      content: "";
      position: absolute;
      left: 6px;
      right: 6px;
      height: 2px;
      background: color-mix(in srgb, var(--ecco-text-muted) 55%, transparent);
      pointer-events: none;
    }
    .node-box.colour-solar:not(.combiner)::before {
      top: 0;
    }
    .node-box.colour-solar:not(.combiner)::after {
      bottom: 0;
    }
    .solar-node-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    /* Small sun-identity cue, grouped with the label rather than floating
       separately - subtle by design (the maintainer's explicit "not dominant"),
       just enough to reinforce "this is solar" at a glance alongside the
       panel-cell strip below. flex-shrink: 0 so it's never the thing that
       gives way if the row ever gets tight - the label/value text is. */
    .solar-node-title {
      display: flex;
      align-items: baseline;
      gap: 4px;
      min-width: 0;
    }
    .solar-sun {
      flex-shrink: 0;
      align-self: center;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: radial-gradient(circle at 35% 30%, #ffe9b8, var(--ecco-line-solar) 70%);
      box-shadow: 0 0 4px 0.5px color-mix(in srgb, var(--ecco-line-solar) 70%, transparent);
      transition:
        opacity 0.4s ease,
        box-shadow 0.4s ease;
    }
    /* Idle: dims like the rest of the solar family (see .colour-solar.idle
       .panel-cell above) - never fully off, matching the maintainer's "must not
       look dead/grey" brief for the node as a whole. */
    .node-box.colour-solar.idle .solar-sun {
      opacity: 0.55;
      box-shadow: none;
    }
    .solar-node .node-label {
      font-size: 0.7rem;
    }
    .solar-node .node-value {
      font-size: 0.82rem;
    }
    .panel-grid {
      display: flex;
      gap: 2px;
    }
    .panel-cell {
      /* Stretches to fill the header's own full width evenly, however
         many cells there are (8 regular, 6 dense) - adapts automatically
         to the box's width instead of assuming one fixed reference size. */
      flex: 1 1 0;
      min-width: 0;
      height: 13px;
      /* Tighter, near-rectangular corners than the default node-box
         radius scale - reads as an individual glazed PV cell, not a
         rounded UI chip. */
      border-radius: 1px;
      background:
        linear-gradient(155deg, color-mix(in srgb, white 14%, transparent) 0%, transparent 40%),
        color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-surface) 45%);
      border: 0.5px solid color-mix(in srgb, var(--ecco-line-solar) 70%, transparent);
      transition:
        background 0.28s ease,
        border-color 0.28s ease;
    }
    /* The maintainer's explicit "inactive solar must not turn dead grey" brief -
       previously fell back to the same neutral --ecco-surface/--ecco-border
       every OTHER idle node uses (see .node-box.idle below), which read as
       "disabled control", not "sleeping panel". A dim, desaturated AMBER
       instead - still visibly part of the solar family at night/near-zero
       output, just quiet. Placed after .node-box.idle below so it wins at
       equal specificity by appearing later, the same pattern every other
       state-override in this file already uses. */
    .node-box.colour-solar.idle {
      border-color: color-mix(in srgb, var(--ecco-line-solar) 22%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-line-solar) 4%, var(--ecco-surface));
    }
    .node-box.colour-solar.idle .panel-cell {
      background: color-mix(in srgb, var(--ecco-line-solar) 16%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-solar) 26%, transparent);
    }
    .node-box.colour-solar.idle ha-icon {
      opacity: 0.7;
    }
    /* "Sleeping" treatment for a near-zero flow on an otherwise state-
       coloured node - currently the solar family only (Array 1/2 and Solar
       Total dim back to neutral at night/near-zero PV, and the combiner's
       glow pulse above stops with it). Battery/grid express their own idle
       state through a dedicated colour-battery-idle/colour-grid-idle class
       instead of this modifier, since they already have a real three-way
       state machine. Placed after the coloured rules above so it wins at
       equal selector specificity by appearing later in the stylesheet. */
    .node-box.idle {
      border-color: var(--ecco-border);
      background: var(--ecco-surface);
      box-shadow: none;
    }
    .node-box.idle ha-icon {
      opacity: 0.55;
    }
    /* Any node with a configured entity for tap-to-more-info (see
       _moreInfo()/EntityIdMap) gets this affordance; a node with nothing
       configured never receives the "clickable" class at all, so it stays
       a plain, non-interactive card. A slightly snappier transition than
       the base state-colour one above (180ms vs 280ms) so the hover/press
       feedback itself feels immediate; :active is a normal touch-
       compatible pseudo-class (momentary on tap), and no JS touch handler
       is added, so this never interferes with Home Assistant's own touch
       handling. */
    .node-box.clickable,
    .inverter-box.clickable {
      cursor: pointer;
      transition:
        transform 0.18s ease,
        border-color 0.18s ease,
        box-shadow 0.18s ease;
    }
    .node-box.clickable:hover,
    .inverter-box.clickable:hover {
      border-color: color-mix(in srgb, var(--ecco-accent) 45%, var(--ecco-border));
      transform: translateY(-1px);
    }
    .node-box.clickable:active,
    .inverter-box.clickable:active {
      transform: translateY(0) scale(0.98);
    }
    .node-box.clickable:focus-visible,
    .inverter-box.clickable:focus-visible {
      outline: 2px solid var(--ecco-accent);
      outline-offset: 2px;
    }
    @media (prefers-reduced-motion: reduce) {
      /* The hover/press LIFT is motion; the border-colour/glow feedback it
         comes with is not, and stays. */
      .node-box.clickable:hover,
      .inverter-box.clickable:hover,
      .node-box.clickable:active,
      .inverter-box.clickable:active {
        transform: none;
      }
    }
    /* Icon tint matches this node's own flow-line colour - a small,
       cohesive link between each node and the line feeding it, without
       recolouring the whole card (keeps things premium, not gaudy). */
    .node-box.colour-solar ha-icon {
      color: var(--ecco-line-solar);
    }
    .node-box.colour-home ha-icon {
      color: var(--ecco-line-home);
    }
    .node-box.colour-generator ha-icon {
      color: var(--ecco-line-generator);
    }
    .node-text {
      display: flex;
      flex-direction: column;
      line-height: 1.15;
      min-width: 0;
      /* Small, consistent breathing room between label/value/status lines -
         previously only set on .battery-box specifically, which left the
         otherwise-identical three-line .grid-box inconsistent with it. */
      gap: 1px;
    }
    .node-label {
      font-size: 0.68rem;
      color: var(--ecco-text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .node-value {
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--ecco-text);
      white-space: nowrap;
      /* Tabular numerals - each digit glyph takes the same width, so a
         live value cycling through its digits (or crossing a W/kW unit
         boundary) never visibly jitters the text within its fixed-width
         node box. Applied to every live numeric display in the card. */
      font-variant-numeric: tabular-nums;
    }
    .node-sub {
      font-size: 0.62rem;
      color: var(--ecco-text-muted);
    }

    /* Hardware-identity pass: a real terminal/cap protrusion, per the maintainer's
       explicit brief ("do not reject the battery terminal idea merely
       because the existing pseudo-elements are occupied"). .battery-box
       already spends both ::before/::after on the charge shimmer and the
       SOC sheen (below) and relies on its own overflow:hidden to keep
       those clipped to its rounded corners - reusing either pseudo-element
       for a cap that must protrude ABOVE the box, past that same
       overflow:hidden, would fight that existing clipping. Cleanest fix is
       the one the maintainer asked for: a thin non-clipping .battery-shell
       wrapper (no size/shape of its own - it only exists to host the
       terminal at a position .battery-box itself can't reach) with the
       terminal as its own sibling span before the untouched
       .battery-box. Zero changes to the shimmer/SOC-fill machinery. */
    .battery-shell {
      position: relative;
    }
    .battery-terminal {
      position: absolute;
      top: -8px;
      left: 50%;
      transform: translateX(-50%);
      width: 32px;
      height: 9px;
      border-radius: 3px 3px 0 0;
      border: 1px solid var(--ecco-border);
      border-bottom: none;
      background: var(--ecco-surface);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
      transition:
        background 0.4s ease,
        border-color 0.4s ease;
      pointer-events: none;
    }
    .battery-terminal.colour-battery-charge {
      background: color-mix(in srgb, var(--ecco-line-battery-charge) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-charge) 65%, var(--ecco-border));
    }
    .battery-terminal.colour-battery-discharge {
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 65%, var(--ecco-border));
    }
    .battery-terminal.colour-battery-idle {
      background: var(--ecco-surface);
      border-color: var(--ecco-border);
    }
    /* Icon-removal pass: the maintainer felt the internal battery icon was
       redundant once the enclosure shape, terminal cap, SOC gauge and
       state colouring already say "battery" on their own - removed
       entirely (see the render method), which also removes any reason to
       keep the two-column icon+text grid this box used to need. Every
       width now uses the same single centred column the narrow
       container-query breakpoint already proved out (label+SOC/value/
       status stacked, SOC gauge spanning the full row beneath) -
       promoted here to the base rule rather than kept as a narrow-only
       override. */
    .battery-box {
      display: grid;
      grid-template-columns: 1fr;
      justify-items: center;
      text-align: center;
      row-gap: 7px;
      /* Narrowed slightly (132 -> 116px) alongside this round's routing
         pass - keeps the port comfortably clear of the inverter at every
         width (see _layout()'s battery position note), which also suits a
         taller cell's own proportions better anyway. */
      width: 116px;
      padding: 14px 12px 13px;
      /* A slightly flatter base than the default 12px - a subtle nod to a
         battery cell's own blockier silhouette; still restrained, not a
         drawn battery shape. */
      border-radius: 10px 10px 8px 8px;
      position: relative;
      z-index: 0;
      overflow: hidden;
      /* Subtle top-down sheen - part of this round's "gradients throughout
         the hardware surfaces" brief - layered above the existing per-
         state colour-mix background (background-image paints over
         background-color, both still resolve from the one shorthand-free
         declaration order already used here). */
      background-image: linear-gradient(165deg, rgba(255, 255, 255, 0.06), transparent 55%);
      transition:
        border-color 0.4s ease,
        background 0.4s ease,
        box-shadow 0.4s ease;
    }
    /* Real breathing room between label/value/status now that the box has
       the height to spend on it (was the shared 1px default) - this is
       the "spacing, not padding" half of the taller redesign. */
    .battery-box .node-text {
      gap: 4px;
      align-items: center;
    }
    /* Label+SOC on one line, live power on its own (larger) line,
       Charging/Discharging/Idle status on its own line - all centred,
       stacked in the single text row above the SOC gauge. */
    .battery-box .node-value {
      font-size: 1rem;
    }
    /* justify-items: center above sizes every grid item to its own
       content width - correct for the label/value/status text, but the
       SOC track's only child is a percentage-width fill, which can't
       establish an intrinsic size for a shrink-to-fit ancestor, so the
       track itself would collapse to 0 width without this. */
    .battery-box .soc-track {
      justify-self: stretch;
      width: 100%;
    }
    .battery-box .node-sub {
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-size: 0.68rem;
      color: var(--ecco-text);
      opacity: 0.78;
    }
    /* Very subtle SOC-proportional background fill (bottom-up) - an
       ambient, low-opacity second representation of charge level, always
       behind the shimmer sweep and the card's own text/icon (negative
       z-index within the local stacking context .battery-box establishes
       via position:relative + z-index:0), so it never competes with
       readability. The --ecco-soc custom property is set inline per render. */
    .battery-box::after {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: var(--ecco-soc, 0%);
      z-index: -2;
      transition: height 0.8s ease;
      pointer-events: none;
    }
    .battery-box.colour-battery-charge::after {
      background: color-mix(in srgb, var(--ecco-line-battery-charge) 16%, transparent);
    }
    .battery-box.colour-battery-discharge::after {
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 16%, transparent);
    }
    .battery-box.colour-battery-idle::after {
      background: color-mix(in srgb, var(--ecco-line-battery-idle) 10%, transparent);
    }
    /* Unknown SOC: no ambient fill at all, rather than a genuine-looking 0%. */
    .battery-box.soc-unknown::after {
      display: none;
    }
    /* Diagonal shimmer sweep, only while actually charging/discharging -
       visually suggests energy flowing in/out. Sits above the SOC fill but
       below the card's own text/icon (see the z-index note above). Slow
       and gentle (3.6s linear) per the maintainer's explicit "no flashing, no fast
       pulsing" instruction; disabled entirely under reduced motion below. */
    .battery-box::before {
      content: "";
      position: absolute;
      inset: -40% -60%;
      z-index: -1;
      opacity: 0;
      pointer-events: none;
    }
    .battery-box.colour-battery-charge::before {
      opacity: 1;
      background: linear-gradient(
        120deg,
        transparent 40%,
        color-mix(in srgb, var(--ecco-line-battery-charge) 20%, transparent) 50%,
        transparent 60%
      );
      animation: ecco-battery-sheen-in 3.6s linear infinite;
    }
    .battery-box.colour-battery-discharge::before {
      opacity: 1;
      background: linear-gradient(
        120deg,
        transparent 40%,
        color-mix(in srgb, var(--ecco-line-battery-discharge) 20%, transparent) 50%,
        transparent 60%
      );
      animation: ecco-battery-sheen-out 3.6s linear infinite;
    }
    @keyframes ecco-battery-sheen-in {
      0% {
        transform: translateX(-60%);
      }
      100% {
        transform: translateX(60%);
      }
    }
    @keyframes ecco-battery-sheen-out {
      0% {
        transform: translateX(60%);
      }
      100% {
        transform: translateX(-60%);
      }
    }
    /* Border/glow per state - a slow pulse while charging/discharging
       (energy actively moving), fully static (no animation property at
       all) while idle, matching the maintainer's "remove motion... no pulsing
       emphasis" instruction for that state specifically. */
    .battery-box.colour-battery-charge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-charge) 65%, var(--ecco-border));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-battery-charge) 45%, transparent);
      animation: ecco-battery-glow-charge 3.4s ease-in-out infinite;
    }
    .battery-box.colour-battery-discharge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 65%, var(--ecco-border));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-battery-discharge) 45%, transparent);
      animation: ecco-battery-glow-discharge 3.4s ease-in-out infinite;
    }
    .battery-box.colour-battery-idle {
      border-color: var(--ecco-border);
      box-shadow: none;
    }
    @keyframes ecco-battery-glow-charge {
      0%,
      100% {
        box-shadow: 0 0 9px -6px color-mix(in srgb, var(--ecco-line-battery-charge) 36%, transparent);
      }
      50% {
        /* Peak intensity deliberately kept under the inverter's own glow
           (see .inverter-box) - the battery card should feel alive, but
           never read as more visually important than the centre node. */
        box-shadow: 0 0 14px -4px color-mix(in srgb, var(--ecco-line-battery-charge) 55%, transparent);
      }
    }
    @keyframes ecco-battery-glow-discharge {
      0%,
      100% {
        box-shadow: 0 0 9px -6px color-mix(in srgb, var(--ecco-line-battery-discharge) 36%, transparent);
      }
      50% {
        box-shadow: 0 0 14px -4px color-mix(in srgb, var(--ecco-line-battery-discharge) 55%, transparent);
      }
    }
    .soc-track {
      height: 4px;
      border-radius: 2px;
      background: var(--ecco-border);
      overflow: hidden;
    }
    /* Spans both grid columns (icon + text) so the bar runs the full
       width of the now wider battery card, on its own row beneath -
       .battery-box's own row-gap provides the spacing that a margin-top
       here previously had to (removed above to avoid doubling it up).
       Taller (4 -> 8px) as part of this round's "taller enclosure" pass -
       a real gauge now, not a thin accent line - with a 5-segment
       "cell" overlay reinforcing the physical battery-gauge read, visible
       over both the filled and unfilled portion of the bar. */
    .battery-box .soc-track {
      grid-column: 1 / -1;
      height: 8px;
      border-radius: 3px;
      position: relative;
    }
    .battery-box .soc-track::after {
      content: "";
      position: absolute;
      inset: 0;
      background-image: repeating-linear-gradient(
        90deg,
        transparent 0,
        transparent calc(20% - 1.5px),
        rgba(0, 0, 0, 0.35) calc(20% - 1.5px),
        rgba(0, 0, 0, 0.35) 20%
      );
      pointer-events: none;
    }
    .soc-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--ecco-accent), var(--ecco-ok));
      border-radius: 2px;
      transition: width 0.6s ease;
      position: relative;
      overflow: hidden;
    }
    /* Same modern "moving sheen" language as the battery card's own
       shimmer, scaled down onto the thin SOC bar - only while actually
       charging/discharging, same as the card-level shimmer above. */
    .soc-fill::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.4), transparent);
      transform: translateX(-100%);
    }
    .battery-box.colour-battery-charge .soc-fill::after,
    .battery-box.colour-battery-discharge .soc-fill::after {
      animation: ecco-soc-sheen 2.6s ease-in-out infinite;
    }
    @keyframes ecco-soc-sheen {
      0% {
        transform: translateX(-100%);
      }
      100% {
        transform: translateX(100%);
      }
    }

    /* Grid - sized and weighted to match the battery card (see
       .battery-box above) per the maintainer's "should feel approximately the same
       visual weight" request, plus the same three-state (import/export/
       idle) border/background tint/glow treatment as battery. No
       animation here - unlike battery, grid state isn't asked to feel
       "alive", just clearly coloured. Was 104px against battery's 132px -
       genuinely mismatched despite this comment's own intent; matched
       properly as part of this round's "Battery and Grid should feel like
       balanced lateral branches" pass. */
    /* Hardware-identity THIRD redesign: the twin-stack silhouette from the
       previous pass improved the read but stayed too small/decorative -
       "still the weakest visual element" in live review. The maintainer's explicit
       new direction: text on the LEFT, a genuinely LARGE utility graphic
       on the RIGHT, integrated into the node's own bounds (no more
       overflow-avoiding shell needed - the previous stack redesign had to
       protrude ABOVE the box because the box itself had no room; this one
       is simply tall enough to hold the graphic directly). The box is now
       a horizontal row instead of a vertical stack, and grew (both wider
       and taller) specifically to give that graphic real presence - the
       one exception this round's brief allows to the "freeze all node
       sizes" rule, and only for Grid. */
    .grid-box {
      width: 146px;
      min-height: 92px;
      padding: 14px 14px 14px 16px;
      border-radius: 10px;
      flex-direction: row;
      align-items: center;
      justify-content: space-between;
      column-gap: 8px;
      text-align: left;
      position: relative;
      background-image: linear-gradient(165deg, rgba(255, 255, 255, 0.05), transparent 55%);
      /* A small technical chamfer on the top-left/bottom-right corners
         only - an asymmetric "enclosure" cue distinct from Battery's own
         symmetric taper, restrained rather than a full taper. */
      clip-path: polygon(9px 0, 100% 0, 100% calc(100% - 9px), calc(100% - 9px) 100%, 0 100%, 0 9px);
    }
    .grid-text {
      align-items: flex-start;
      gap: 3px;
      flex: 1 1 auto;
      min-width: 0;
    }
    .grid-box .node-value {
      font-size: 1rem;
    }
    .grid-box .node-sub {
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-size: 0.68rem;
      color: var(--ecco-text);
      opacity: 0.78;
    }
    /* The graphic zone itself - a fixed-size stage the pylon silhouette
       sits inside, vertically centred in the row alongside the text
       column so both share the same breathing room above/below. */
    .grid-graphic {
      position: relative;
      width: 42px;
      height: 48px;
      flex: 0 0 auto;
    }
    /* THIRD Grid symbol pass: the flat-topped-trapezoid "tower" from the
       first attempt at this pass read as barely-visible background noise
       behind two floating pill-shaped arms - a single solid wedge shape
       just doesn't carry the "pylon" read at all, whatever its tint.
       Replaced with two EXPLICIT diagonal legs (real rotated elements,
       not a clip-path illusion) forming a genuine splayed A-frame -
       the actual distinguishing silhouette of a transmission tower -
       crossed by three arms that narrow with height to visually match
       how the legs converge (wide low arm, narrow high arm), so the
       whole thing reads as one coherent tapered structure rather than
       arms floating over an unrelated body. */
    .pylon-leg {
      position: absolute;
      bottom: 0;
      width: 3px;
      height: 44px;
      border-radius: 1.5px 1.5px 0 0;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      transform-origin: 50% 100%;
      transition:
        background 0.4s ease,
        border-color 0.4s ease;
    }
    .pylon-leg.leg-left {
      left: 13px;
      transform: rotate(6deg);
    }
    .pylon-leg.leg-right {
      left: 26px;
      transform: rotate(-6deg);
    }
    .pylon-arm {
      position: absolute;
      left: 50%;
      transform: translateX(-50%);
      height: 3px;
      border-radius: 1.5px;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      transition:
        background 0.4s ease,
        border-color 0.4s ease;
    }
    /* Widths/positions matched to where the two 6deg-rotated legs above
       actually sit at each height (computed, not eyeballed - the legs
       pivot from their own bottom-anchored x, so the gap between them
       narrows predictably with height), each with a small overhang past
       the legs so the arm visibly crosses rather than stopping exactly
       at them. */
    .pylon-arm.arm-top {
      top: 10px;
      width: 9px;
    }
    .pylon-arm.arm-mid {
      top: 22px;
      width: 13px;
    }
    .pylon-arm.arm-base {
      top: 35px;
      width: 17px;
    }
    .pylon-leg,
    .pylon-arm {
      pointer-events: none;
    }
    .grid-box.colour-grid-import .pylon-leg,
    .grid-box.colour-grid-import .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-import) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 62%, var(--ecco-border));
    }
    .grid-box.colour-grid-export .pylon-leg,
    .grid-box.colour-grid-export .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-export) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-export) 62%, var(--ecco-border));
    }
    /* "idle" now specifically means connected + confirmed ~0W (see
       _gridState()'s doc comment) - a subtle steel-blue tint so the pylon
       still visibly reads as "alive", not the flat neutral treatment that
       used to cover every idle-ish case. "unavailable" (below) keeps that
       flat neutral look instead, since IT is the genuinely "nothing to
       report" state. */
    .grid-box.colour-grid-idle .pylon-leg,
    .grid-box.colour-grid-idle .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-idle) 18%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-idle) 50%, var(--ecco-border));
    }
    .grid-box.colour-grid-disconnected .pylon-leg,
    .grid-box.colour-grid-disconnected .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-disconnected) 26%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-disconnected) 65%, var(--ecco-border));
    }
    .grid-box.colour-grid-unavailable .pylon-leg,
    .grid-box.colour-grid-unavailable .pylon-arm {
      background: var(--ecco-surface);
      border-color: var(--ecco-border);
    }
    /* background-COLOR specifically (not the background shorthand) -
       the shorthand resets every unspecified longhand including
       background-image to none, which was silently clobbering
       .grid-box's own gradient (see its base rule above) in every state.
       .node-box.colour-home already avoids this same trap the same way. */
    .grid-box.colour-grid-import {
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 55%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-import) 10%, var(--ecco-surface));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-grid-import) 50%, transparent);
    }
    .grid-box.colour-grid-export {
      border-color: color-mix(in srgb, var(--ecco-line-grid-export) 55%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-export) 10%, var(--ecco-surface));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-grid-export) 50%, transparent);
    }
    .grid-box.colour-grid-idle {
      border-color: color-mix(in srgb, var(--ecco-line-grid-idle) 40%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-idle) 7%, var(--ecco-surface));
      box-shadow: none;
    }
    .grid-box.colour-grid-disconnected {
      border-color: color-mix(in srgb, var(--ecco-line-grid-disconnected) 60%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-disconnected) 12%, var(--ecco-surface));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-grid-disconnected) 50%, transparent);
    }
    .grid-box.colour-grid-unavailable {
      border-color: var(--ecco-border);
      background-color: var(--ecco-surface);
      box-shadow: none;
    }
    /* Pylon PULSE (this round): a smooth breathing glow on the pylon
       GRAPHIC ITSELF - .grid-graphic, not the whole .grid-box - explicitly
       NOT a blink/flash (no visibility/display toggling, no hard 0-opacity
       step). filter: brightness()+drop-shadow() both animate continuously
       through the full keyframe, so the low point is still fully visible,
       just dimmer/glow-less than the peak. --ecco-pylon-pulse-duration is
       set inline per-render (see _renderBottomNode()) from
       pylonPulseDurationS() - magnitude-scaled for importing/exporting,
       fixed for the two ~0W-ish states. --ecco-pylon-glow-colour is set
       per colour class below so the SAME keyframes/animation rule works
       for every state without four near-duplicate @keyframes blocks. */
    @keyframes ecco-pylon-pulse {
      0%,
      100% {
        filter: brightness(1) drop-shadow(0 0 0 transparent);
      }
      50% {
        filter: brightness(1.4) drop-shadow(0 0 5px var(--ecco-pylon-glow-colour, transparent));
      }
    }
    .grid-graphic.pylon-pulse {
      animation: ecco-pylon-pulse var(--ecco-pylon-pulse-duration, 4s) ease-in-out infinite;
    }
    .grid-box.colour-grid-import .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-import) 65%, transparent);
    }
    .grid-box.colour-grid-export .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-export) 65%, transparent);
    }
    .grid-box.colour-grid-idle .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-idle) 55%, transparent);
    }
    .grid-box.colour-grid-disconnected .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-disconnected) 65%, transparent);
    }

    .inverter-box {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      /* Compositional pass: this is the ONE node every other node's size
         and glow must read as subordinate to (see this round's design
         note). Every arm's reach from the inverter (_layout()'s per-node
         x/y offsets) has to grow to keep
         clearance as this box WIDENS - already-tight at the original
         156px width around a typical card width - so width only grew a
         little (156 -> 160px); the actual size/prominence increase comes
         from taller padding (a real footprint gain that only costs
         vertical room, which had far more slack than horizontal) plus a
         visibly stronger glow/gradient/border, so the inverter reads as
         the hero through PRESENCE, not primarily through occupying more
         of the card's width than Battery/Grid can spare either side of
         it. Home/Battery/Grid were brought down closer to each other's
         own width instead of the inverter being widened further to
         "win" - see .node-box.colour-home and .grid-box. */
      width: 152px;
      padding: 14px 9px;
      border-radius: 18px;
      background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--ecco-accent) 20%, var(--ecco-surface)), var(--ecco-surface));
      border: 1px solid color-mix(in srgb, var(--ecco-accent) 35%, var(--ecco-border));
      /* A soft accent glow plus a quiet downward drop shadow for a touch
         more depth/lift - both strengthened so the inverter's presence
         scales with its height rather than needing more width to read as
         dominant. */
      box-shadow:
        0 0 28px -6px var(--ecco-glow),
        0 4px 14px -4px rgba(0, 0, 0, 0.4);
      box-sizing: border-box;
      gap: 3px;
      text-align: center;
      position: relative;
    }
    .inverter-box ha-icon {
      --mdc-icon-size: 26px;
      color: var(--ecco-accent);
    }
    /* Port cues (hardware-identity pass): a small physical connector nub
       at each of the inverter's four logical ports - TOP=PV/Solar,
       LEFT=Battery, RIGHT=Grid, BOTTOM=Home/Load, matching the layout
       the maintainer specified. Static tint per arm's own line colour (not
       state-driven - these identify WHICH port, not its current value).
       TRUE PORT GEOMETRY pass: these are no longer purely decorative -
       each one also carries a data-port attribute (see the render
       method) and IS the real, measured connection point every route now
       terminates on exactly (see the class-level note above
       buildRouteD()) - so their on-screen position is load-bearing, not
       just a visual cue. */
    .inverter-port {
      position: absolute;
      border-radius: 2px;
      border: 1px solid var(--ecco-border);
      background: color-mix(in srgb, var(--ecco-text-muted) 30%, var(--ecco-surface));
      pointer-events: none;
    }
    .inverter-port.port-pv {
      top: -3px;
      left: 50%;
      width: 12px;
      height: 5px;
      transform: translateX(-50%);
      background: color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-solar) 70%, var(--ecco-border));
    }
    .inverter-port.port-home {
      bottom: -3px;
      left: 50%;
      width: 12px;
      height: 5px;
      transform: translateX(-50%);
      background: color-mix(in srgb, var(--ecco-line-home) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-home) 70%, var(--ecco-border));
    }
    .inverter-port.port-battery {
      left: -3px;
      top: 50%;
      width: 5px;
      height: 12px;
      transform: translateY(-50%);
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 60%, var(--ecco-border));
    }
    .inverter-port.port-grid {
      right: -3px;
      top: 50%;
      width: 5px;
      height: 12px;
      transform: translateY(-50%);
      background: color-mix(in srgb, var(--ecco-line-grid-import) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 60%, var(--ecco-border));
    }
    /* Every OTHER node's own port marker - Solar 1/2, the 3+-source
       combiner, Home, Generator (all top-facing, .port-top/.port-
       bottom), Battery (right-facing) and Grid (left-facing). Same
       "real, measured connection point" role as .inverter-port above,
       just unthemed by default (each node's own colour-* family tints
       it via the rules below, matching that node's own line colour - the
       same "small cohesive link" language the icon tint already uses
       elsewhere in this file). Sits centred on its edge, mostly outside
       the box's own border so the route's final approach is genuinely
       visible arriving at it, not hidden under the node.
       IMPORTANT: pointer-events:none here matters beyond the usual
       "decorative, don't intercept clicks" reason - these are also
       [data-port] measurement targets (see _measurePorts()), and a
       port sitting exactly on a clickable node's own edge must never
       itself become the hit target for that node's tap/keyboard
       more-info handler. */
    .node-port {
      position: absolute;
      width: 10px;
      height: 6px;
      border-radius: 2px;
      border: 1px solid var(--ecco-border);
      background: color-mix(in srgb, var(--ecco-text-muted) 30%, var(--ecco-surface));
      pointer-events: none;
    }
    .node-port.port-top,
    .node-port.port-bottom {
      left: 50%;
      transform: translateX(-50%);
    }
    .node-port.port-top {
      top: -3px;
    }
    .node-port.port-bottom {
      bottom: -3px;
    }
    .node-port.port-left,
    .node-port.port-right {
      top: 50%;
      width: 6px;
      height: 10px;
      transform: translateY(-50%);
    }
    .node-port.port-left {
      left: -3px;
    }
    .node-port.port-right {
      right: -3px;
    }
    .colour-solar .node-port {
      background: color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-solar) 70%, var(--ecco-border));
    }
    .colour-home .node-port {
      background: color-mix(in srgb, var(--ecco-line-home) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-home) 70%, var(--ecco-border));
    }
    .battery-box .node-port {
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 60%, var(--ecco-border));
    }
    .grid-box .node-port {
      background: color-mix(in srgb, var(--ecco-line-grid-import) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 60%, var(--ecco-border));
    }
    .colour-generator .node-port {
      background: color-mix(in srgb, var(--ecco-line-generator) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-generator) 70%, var(--ecco-border));
    }
    /* Battery/Grid's fixed CSS-px width and their (also fixed) logical-unit
       centre position (see _layout()'s battery/grid x/y offsets) only
       agree at one reference card width - live verification this round
       found that below ~520px CARD
       width, Battery's own left edge (and Grid's own right edge) render
       PAST ha-card's own edge and get genuinely clipped by its
       overflow:hidden - not merely "a bit tight", an actual missing slice
       of the box, confirmed via elementFromPoint hit-testing at the
       claimed-clipped coordinates returning nothing. This affects the
       420px "default" width, not just the 380px "narrow" one.
       @container (not @media - see :host's container-type above) so this
       responds to the CARD's own rendered width. 82px keeps Battery's/
       Grid's own half-width within the smallest tested card's (380px)
       actual available room either side of centre - verified by direct
       measurement, not guessed. Battery switches to a single centred
       column (icon above text, matching Grid's own layout) rather than
       staying icon-left/text-right, so its longest status word
       ("Discharging"/"Charging") gets the full available width instead of
       splitting it with the icon - the icon+text ROW layout is otherwise
       kept exactly as the maintainer approved; this only applies below the
       breakpoint where the row genuinely no longer fits. */
    @container (max-width: 550px) {
      .battery-box {
        width: 82px;
        padding: 10px 8px;
      }
      .battery-terminal {
        width: 24px;
        height: 7px;
      }
      /* Grid keeps its own two-region (text + graphic) layout concept at
         narrow widths rather than reverting to a plain icon - just scaled
         down proportionally so it still comfortably clears the inverter
         and the card's own edge (see _layout()'s grid position note)
         without losing the identity this round's redesign is for.
         Live-review found the first pass here too tight: the text column
         (down to 45px) was narrower than "-1.40 kW"/"Exporting" actually
         need (measured ~63px/~54px at the unshrunk 1rem/0.68rem sizes),
         so the value visibly ran into the graphic rather than just
         truncating. Fixed with FOUR small levers together rather than one
         big one - a touch more box width, tighter padding/gap, a
         slightly smaller graphic, and a slightly smaller value font -
         so no single change has to do all the work (and the box still
         stays well short of the ~104px width that verified unsafe for
         inverter/edge clearance at this breakpoint). */
      .grid-box {
        width: 96px;
        min-height: 66px;
        padding: 8px 5px 8px 8px;
        column-gap: 3px;
      }
      .grid-box .node-value {
        font-size: 0.9rem;
      }
      .grid-box .node-sub {
        font-size: 0.6rem;
        letter-spacing: 0.03em;
      }
      .grid-graphic {
        width: 19px;
        height: 31px;
      }
      .pylon-leg {
        width: 2px;
        height: 27px;
      }
      .pylon-leg.leg-left {
        left: 6px;
      }
      .pylon-leg.leg-right {
        left: 11px;
      }
      .pylon-arm.arm-top {
        top: 6px;
        width: 6px;
      }
      .pylon-arm.arm-mid {
        top: 15px;
        width: 8px;
      }
      .pylon-arm.arm-base {
        display: none;
      }
    }
    .inverter-value {
      font-size: 0.95rem;
      font-variant-numeric: tabular-nums;
    }
    /* The inverter's centre figure is AC output specifically, not total
       system throughput (it will not simply sum against home/grid/battery
       figures) - this caption makes that explicit without changing the
       underlying entity/calculation. Only shown when PV IN isn't (see
       .inverter-metrics) - i.e. the 0/1/3+ solar-source configs that keep
       the original single-value display untouched. */
    .inverter-caption {
      font-size: 0.64rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: color-mix(in srgb, var(--ecco-text-muted) 55%, var(--ecco-text) 45%);
      margin-top: 1px;
    }
    /* PV IN / AC OUT pair - replaces the single AC-output value+caption
       above when the combined 2-array Solar Total figure is available
       (see the pvInW param on _renderInverterNode()). Labels use the same
       small-caps treatment as .inverter-caption; values match the row
       styling already established on the solar node's own header
       (.solar-node-header) for visual consistency across the two
       "labelled metric row" spots in this diagram. */
    .inverter-metrics {
      display: flex;
      flex-direction: column;
      gap: 3px;
      width: 100%;
      margin-top: 2px;
    }
    .inverter-metric-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    /* Bumped size/contrast from the previous pass (0.62rem, 55/45 muted-
       text mix) per live-review feedback that PV IN/AC OUT read too
       quietly next to their values - still clearly secondary to
       .inverter-metric-value below, just no longer easy to miss. */
    .inverter-metric-label {
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: color-mix(in srgb, var(--ecco-text-muted) 35%, var(--ecco-text) 65%);
    }
    .inverter-metric-value {
      font-size: 0.86rem;
      font-weight: 700;
      color: var(--ecco-text);
      font-variant-numeric: tabular-nums;
    }
    .state-pill {
      margin-top: 2px;
      font-size: 0.6rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 1px 7px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--ecco-text-muted) 20%, transparent);
      color: var(--ecco-text-muted);
    }
    .severity-ok .state-pill,
    .state-pill.severity-ok {
      background: color-mix(in srgb, var(--ecco-ok) 22%, transparent);
      color: var(--ecco-ok);
    }
    .severity-warning .state-pill,
    .state-pill.severity-warning {
      background: color-mix(in srgb, var(--ecco-warning) 24%, transparent);
      color: var(--ecco-warning);
    }
    .severity-fault .state-pill,
    .state-pill.severity-fault {
      background: color-mix(in srgb, var(--ecco-fault) 24%, transparent);
      color: var(--ecco-fault);
    }
    .inverter-box.severity-fault {
      box-shadow: 0 0 18px -4px color-mix(in srgb, var(--ecco-fault) 55%, transparent);
    }

    /* Compact always-visible strip (grid voltage / AC temp / DC temp) -
       sits between the flow diagram and the "Today" totals, filling space
       that would otherwise sit empty. Deliberately quieter than the
       today-item tiles below (no bold heading row, smaller everything) so
       it reads as a secondary at-a-glance strip, not a second headline
       section. */
    /* Grid, not flex: up to five tiles now (was three) - auto-fit lets
       them sit in one confident row at typical/wide card widths while
       wrapping to 2-3 per row on a narrow card without ever crushing a
       label/value below a readable width (min 92px per tile), and without
       needing a separate narrow-width breakpoint. */
    .quick-metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
      gap: 6px;
    }
    .quick-metric {
      display: flex;
      align-items: center;
      gap: 5px;
      min-width: 0;
      padding: 5px 7px;
      border-radius: 10px;
      background-color: color-mix(in srgb, var(--ecco-surface) 70%, transparent);
      background-image: linear-gradient(160deg, rgba(255, 255, 255, 0.035), transparent 65%);
      border: 1px solid var(--ecco-border);
      box-sizing: border-box;
    }
    .quick-metric ha-icon {
      --mdc-icon-size: 15px;
      color: var(--ecco-text-muted);
      flex-shrink: 0;
    }
    /* Grid Connected specifically (see _renderQuickMetrics()) - reuses the
       card's existing ok/fault severity colours rather than inventing new
       ones, matching every other state-aware surface here. Connected
       stays deliberately quiet (a subtle tint, not a celebratory green);
       disconnected is the one state on this whole strip that should read
       as a real problem at a glance. */
    .quick-metric.variant-ok {
      border-color: color-mix(in srgb, var(--ecco-ok) 40%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-ok) 8%, var(--ecco-surface));
    }
    .quick-metric.variant-ok ha-icon {
      color: var(--ecco-ok);
    }
    .quick-metric.variant-fault {
      border-color: color-mix(in srgb, var(--ecco-fault) 55%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-fault) 14%, var(--ecco-surface));
    }
    .quick-metric.variant-fault ha-icon {
      color: var(--ecco-fault);
    }
    .quick-metric.variant-fault .quick-metric-value {
      color: var(--ecco-fault);
    }
    .quick-metric-text {
      display: flex;
      flex-direction: column;
      line-height: 1.1;
      min-width: 0;
    }
    .quick-metric-label {
      font-size: 0.56rem;
      color: var(--ecco-text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .quick-metric-value {
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--ecco-text);
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }

    .today {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-top: 4px;
      border-top: 1px solid var(--ecco-border);
    }
    .today-heading-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    .today-heading {
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--ecco-text-muted);
    }
    /* Solar Share folded into the "Today" heading row instead of its own
       badge row below - see _renderToday()/_solarShareText(). */
    .today-solar-share {
      font-size: 0.68rem;
      color: var(--ecco-text-muted);
      white-space: nowrap;
    }
    .today-solar-share strong {
      color: var(--ecco-text);
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .today-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px 10px;
    }
    .today.compact .today-grid {
      grid-template-columns: repeat(6, minmax(0, 1fr));
    }
    .today-item {
      display: flex;
      flex-direction: column;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      border-radius: 10px;
      padding: 6px 8px;
      min-width: 0;
    }
    /* Category colour per tile - identity, not a health judgement (see
       _renderToday()'s own comment). A quiet tint/border only, the same
       restrained treatment the flow nodes themselves use, so the row
       reads as "these six totals belong to six different parts of the
       system" at a glance without turning into a row of bright chips. */
    .today-item.colour-solar {
      border-color: color-mix(in srgb, var(--ecco-line-solar) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-solar) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-home {
      border-color: color-mix(in srgb, var(--ecco-line-home) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-home) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-grid-import {
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-grid-import) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-grid-export {
      border-color: color-mix(in srgb, var(--ecco-line-grid-export) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-grid-export) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-battery-charge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-charge) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-battery-charge) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-battery-discharge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-battery-discharge) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-label {
      font-size: 0.62rem;
      color: var(--ecco-text-muted);
    }
    .today-value {
      font-size: 0.8rem;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }

    .badges {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .badge {
      font-size: 0.7rem;
      color: var(--ecco-text-muted);
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      border-radius: 999px;
      padding: 4px 10px;
    }
    .badge strong {
      color: var(--ecco-text);
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }

    .details-toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
      background: transparent;
      border: none;
      color: var(--ecco-text-muted);
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 4px 2px;
      cursor: pointer;
    }
    .details-toggle ha-icon {
      --mdc-icon-size: 18px;
    }

    .details {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 2px 2px 4px;
    }
    .details-row {
      display: flex;
      justify-content: space-between;
      font-size: 0.76rem;
      padding: 3px 0;
      border-bottom: 1px dashed var(--ecco-border);
    }
    .details-label {
      color: var(--ecco-text-muted);
    }
    .details-value {
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .details-empty {
      font-size: 0.76rem;
      color: var(--ecco-text-muted);
    }
  `,O([se({attribute:!1})],A.prototype,"hass",2),O([ee()],A.prototype,"_config",2),O([ee()],A.prototype,"_detailsOpen",2),O([ee()],A.prototype,"_ports",2),O([ee()],A.prototype,"_flowSize",2),A=O([Ve("ecco-energy-flow-card")],A);window.customCards=[...window.customCards??[],{type:"ecco-energy-flow-card",name:"ECCO Energy Flow Card",description:"A live solar / inverter / battery / grid / home energy flow diagram with the inverter as a first-class centre node, plus daily energy totals.",preview:!1}];export{A as EccoEnergyFlowCard};
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/lit-html.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-element/lit-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/custom-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/property.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/state.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/event-options.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/base.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-all.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-async.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-assigned-elements.js:
  (**
   * @license
   * Copyright 2021 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-assigned-nodes.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/directives/if-defined.js:
  (**
   * @license
   * Copyright 2018 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
