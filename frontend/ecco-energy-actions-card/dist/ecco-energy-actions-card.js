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
      <ha-card>
        <h1 class="card-title">${t}</h1>
        <div class="actions-grid">
          ${this._renderFreePowerTile()}
          ${this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
    `}_renderPlan(){return lr(this._config,this.hass?.states,void 0,br(t=>this._callPlanService(t)))}_callPlanService(t){pr(t,this._config?.dump_to_grid?.guarded_start)&&this._callService(t.domain,t.service,t.data)}_pressDumpStart(t){if(t.guarded_start!==void 0&&t.guarded_start!==""){let r=ur(t.guarded_start);r&&this._callPlanService(r);return}this._callService("button","press",{entity_id:t.start})}_trackSummary(){let t=this._freePowerVisualStateForInterlock(),r=this._dumpVisualStateForInterlock(),i={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},o=this._config?.free_power;if(t!==null&&o){let l=this._config?.schedule,p=l?kt(t,xt({armed:y(this._entityState(l.armed))})):t,c=Ce(t,r)?"interlocked":p;i={state:c,pill:c,label:this._labelFor(c),statusText:this._entityState(o.status)}}let a=this._config?.dump_to_grid,s=a&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(r!==null&&a){let l=a.schedule,p=bt(r,l?y(this._entityState(l.armed)):null),c=Ce(r,t)?"interlocked":p;s={state:c,pill:c,label:vt(c),statusText:this._entityState(a.status)}}return{fp:i,dump:s}}_selectTrack(t){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=t}_renderTabbed(t){let r=this._trackSummary(),i=this._track??wt(r.fp.state,r.dump.state),o=i==="free_power"?"dump_to_grid":"free_power",a=i==="free_power"?r.dump:r.fp,s=Pn(Mn(a.state)),l=s==="fault"?"mdi:alert-circle-outline":s==="warning"?"mdi:alert-outline":"mdi:information-outline";return u`
      <ha-card>
        <div class="tabbed-header">
          <h1 class="card-title">${t}</h1>
          <div class="track-strip">
            <span class="state-pill state-${r.fp.pill}">Free Power · ${r.fp.label}</span>
            <span class="state-pill state-${r.dump.pill}">Dump to Grid · ${r.dump.label}</span>
          </div>
        </div>
        <div class="mode-selector track-selector" role="tablist">
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${i==="free_power"?"is-active":""}"
            aria-selected=${i==="free_power"}
            @click=${()=>this._selectTrack("free_power")}
          >
            <ha-icon icon="mdi:flash"></ha-icon> Free Power
          </button>
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${i==="dump_to_grid"?"is-active":""}"
            aria-selected=${i==="dump_to_grid"}
            @click=${()=>this._selectTrack("dump_to_grid")}
          >
            <ha-icon icon="mdi:transmission-tower-export"></ha-icon> Dump to Grid
          </button>
        </div>
        ${s?u`
              <div class="track-alert track-alert-${s}" role="status">
                <ha-icon icon=${l}></ha-icon>
                <div class="track-alert-text">${Tn(Rn(o),a.label,a.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(o)}>Show</button>
              </div>
            `:h}
        <div class="actions-grid is-tabbed">
          ${i==="free_power"?this._renderFreePowerTile():this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
    `}_renderFreePowerTile(){let t=this._config?.free_power;if(!t||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let r=y(this._entityState(t.active)),i=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),a=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=qe({active:r,armed:i,operationInProgress:o,statusText:s});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let p=this._config?.schedule,c=p?y(this._entityState(p.armed)):null,d=xt({armed:c}),v=p?kt(l,d):l,b=this._dumpVisualStateForInterlock(),m=Ce(l,b),w=m?"interlocked":v,P=m?_t("Dump to Grid",b):void 0,E=this._entity(t.max_charge_power),_=this._entity(t.duration),A=this._pendingPower??S(E?.state),R=this._pendingDuration??S(_?.state),K=this._iconFor(w),g=this._labelFor(w);return u`
      <div class="tile free-power-tile state-${w}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${K}></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-${w}">${g}</span>
        </div>

        <div class="free-power-body">
          ${p&&d==="armed"?this._renderScheduleBanner(p):h}
          ${m?this._renderInterlockBanner(P):h}

          ${this._renderFreePowerBody(l,{fp:t,schedule:p,statusText:s,snapshotValid:a,interlocked:m,stagedPowerW:A,stagedDurationMin:R,stagedPowerEntity:E,stagedDurationEntity:_})}
        </div>
      </div>
    `}_iconFor(t){if(t==="scheduled")return"mdi:calendar-clock";if(t==="interlocked")return"mdi:lock-outline";switch(t){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(t){return t==="scheduled"?"Scheduled":t==="interlocked"?"Interlocked":gn(t)}_renderInterlockBanner(t){return u`
      <div class="interlock-banner">
        <ha-icon icon="mdi:lock-outline"></ha-icon>
        <div class="interlock-banner-text">${t}</div>
      </div>
    `}_renderFreePowerUnavailable(t){return u`
      <div class="tile free-power-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:flash-off-outline"></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${t}</p>
      </div>
    `}_renderFreePowerBody(t,r){switch(t){case"active":return this._renderActiveBody(r);case"busy":return this._renderBusyBody(r.statusText,r.fp.status);case"deferred":return this._renderDeferredBody(r.statusText,r.fp.status);case"recovery_attention":return this._renderAttentionBody(r);default:return this._renderReadyOrArmedBody(t,r)}}_renderReadyOrArmedBody(t,r){let i=!!r.schedule,o=i?this._mode:"now";return u`
      ${i?this._renderModeSelector():h}
      ${o==="later"&&r.schedule?this._renderLaterPanel(r.schedule):this._renderNowPanel(t,r)}
    `}_renderModeSelector(){let t=this._mode==="now";return u`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${t?"is-active":""}"
          aria-selected=${t}
          @click=${()=>this._mode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${t?"":"is-active"}"
          aria-selected=${!t}
          @click=${()=>this._mode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderNowPanel(t,r){let i=t==="armed",o=Ne(mn(t),r.interlocked),a=Ne(fn(t),r.interlocked);return u`
      <p class="tile-description">Charge the battery from free/zero-cost grid energy.</p>

      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:r.interlocked,onPreview:s=>this._pendingPower=s,onCommit:s=>this._commitNumber("power",s,r.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:r.interlocked,onPreview:s=>this._pendingDuration=s,onCommit:s=>this._commitNumber("duration",s,r.fp.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(r.statusText,r.fp.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!a}
          @click=${()=>this._toggleArm(r.fp.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Free Power"}
        </button>
        <button
          class="start-button"
          ?disabled=${!o}
          @click=${()=>this._callService("button","press",{entity_id:r.fp.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderLaterPanel(t){let r=y(this._entityState(t.armed)),i=Et(r),o=this._entityState(t.start),a=fe(o),s=this._entity(t.duration),l=this._entity(t.power),p=this._entity(t.status),c=this._entityState(t.last_result),d=this._pendingScheduleDuration??S(s?.state),v=this._pendingSchedulePower??S(l?.state),b=p?.attributes?.effective_power_limit_w,m=typeof b=="number"?b:S(typeof b=="string"?b:void 0),w=this._numericAttr(l?.attributes?.max,8e3),P=An(w,m),E=yt(c),_=St(c),A=!i&&a!==null&&a.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${a?this._toDatetimeLocalValue(a):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${R=>this._handleScheduleStartChange(t.start,R.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:v,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:P,formatValue:ne,disabled:i||!l,onPreview:R=>this._pendingSchedulePower=R,onCommit:R=>this._commitScheduleNumber("power",R,t.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:d,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:i||!s,onPreview:R=>this._pendingScheduleDuration=R,onCommit:R=>this._commitScheduleNumber("duration",R,t.duration)})}

      ${c?u`<p class="firmware-note ${E||_?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${i||!A}
          @click=${()=>this._callServiceObj(Mt(t.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the manual Free Power write-enable switch - Home Assistant arms and starts the inverter automatically when the time comes."}
      </p>
    `}_renderScheduleBanner(t){let r=this._entityState(t.start),i=fe(r),o=S(this._entityState(t.duration)),a=S(this._entityState(t.power)),s=i?Ie(i.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${i?Tt(i):"--"} • ${ne(a)} • ${ge(o)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pt(t.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_toDatetimeLocalValue(t){let r=i=>i.toString().padStart(2,"0");return`${t.getFullYear()}-${r(t.getMonth()+1)}-${r(t.getDate())}T${r(t.getHours())}:${r(t.getMinutes())}`}_handleScheduleStartChange(t,r){if(!r)return;let i=new Date(r);Number.isNaN(i.getTime())||this._callServiceObj(Dn(t,Cn(i)))}_commitScheduleNumber(t,r,i){t==="power"?this._pendingSchedulePower=r:this._pendingScheduleDuration=r,this._callServiceObj(Rt(i,r))}_renderActiveBody(t){let r=this._entityState(t.fp.ends_at),i=fe(r),o=i?Ie(i.getTime(),this._nowMs):null;return u`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${ne(t.stagedPowerW)} target • ends ${i?this._formatClock(i):r??"--"}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${t.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${t.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(t.statusText,t.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(t.fp)}
      ${this._renderEndRestoreButton(t.fp.end_restore,"End & Restore Now",!1,gt("active"))}
    `}_renderBusyBody(t,r){return u`
      <div class="transition-panel">
        <ha-icon class="spin" icon="mdi:autorenew"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Working...</div>
          ${this._renderTransitionDetail(t??"Free Power is mid-transaction.",r)}
        </div>
      </div>
      <p class="transition-hint">Controls are disabled while a transaction is in flight - this clears on its own.</p>
    `}_renderDeferredBody(t,r){return u`
      <div class="transition-panel deferred">
        <ha-icon icon="mdi:timer-sand"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Waiting for inverter bus</div>
          ${this._renderTransitionDetail(t??"Modbus bus busy - the watchdog will retry.",r)}
        </div>
      </div>
      <p class="transition-hint">This is expected occasionally - the watchdog retries automatically. No action needed.</p>
    `}_renderAttentionBody(t){let r=yn({statusText:t.statusText,snapshotValid:t.snapshotValid});return u`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(t.statusText??"Free Power requires operator attention.",t.fp.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${r.explanation??"No automatic retry. Starting a new Free Power session is disabled until this clears."}
      </p>
      ${r.actionable?this._renderEndRestoreButton(t.fp.end_restore,r.actionLabel??"End & Restore Now",r.secondary,gt("recovery_attention")):h}
    `}_renderTransitionDetail(t,r){return u`
      <div
        class="transition-detail clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(r)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(r))}}
      >
        ${t}
      </div>
    `}_renderStatusLine(t,r,i){return!(i?.alwaysShow||!!t&&t!=="Inactive")||!t?h:u`
      <p
        class="firmware-note clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(r)}
        @keydown=${a=>{(a.key==="Enter"||a.key===" ")&&(a.preventDefault(),this._moreInfo(r))}}
      >
        ${t}
      </p>
    `}_renderDiagnosticsDetails(t){let r=[],i=(o,a)=>{let s=S(this._entityState(a));s!==null&&r.push({label:o,value:s.toString()})};return i("Starts",t.start_attempts),i("Started OK",t.start_successes),i("Restored OK",t.restore_successes),i("Failures",t.failures),r.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(t,r,i,o){let a=this._confirmEndRestore;return u`
      <button
        class="end-restore-button ${i?"secondary":""} ${a?"confirming":""}"
        ?disabled=${!o}
        @click=${()=>this._handleEndRestoreClick(t)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${a?"Tap again to End & Restore":r}
        ${a?u`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:h}
      </button>
    `}_handleEndRestoreClick(t){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},et);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:t})}_toggleArm(t,r){this._callService("switch",r?"turn_off":"turn_on",{entity_id:t})}_commitNumber(t,r,i){t==="power"?this._pendingPower=r:this._pendingDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_commitDumpNumber(t,r,i){t==="power"?this._pendingDumpPower=r:t==="stop_soc"?this._pendingDumpStopSoc=r:this._pendingDumpDuration=r,this._callService("number","set_value",{entity_id:i,value:r})}_handleEndDumpClick(t){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},et);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:t})}_numericAttr(t,r){if(typeof t=="number"&&Number.isFinite(t))return t;if(typeof t=="string"){let i=S(t);if(i!==null)return i}return r}_formatClock(t){let r=t.getHours().toString().padStart(2,"0"),i=t.getMinutes().toString().padStart(2,"0");return`${r}:${i}`}_renderNumberControl(t){let r=t.entity?.attributes??{},i=this._numericAttr(r.min,t.fallbackMin),o=t.maxOverride??this._numericAttr(r.max,t.fallbackMax),a=this._numericAttr(r.step,t.fallbackStep),s=t.value??i,l=t.disabled??!t.entity,p=o>i?Math.max(0,Math.min(100,(s-i)/(o-i)*100)):0;return u`
      <div class="number-control">
        <div class="number-control-label">
          <ha-icon icon=${t.icon}></ha-icon>
          <span>${t.label}</span>
          <span class="number-control-value">${t.formatValue(s)}</span>
        </div>
        <input
          type="range"
          class="number-control-slider"
          style="--eaa-slider-fill:${p}%"
          min=${i}
          max=${o}
          step=${a}
          .value=${String(s)}
          ?disabled=${l}
          @input=${c=>{let d=Number(c.target.value);Number.isFinite(d)&&t.onPreview(d)}}
          @change=${c=>{let d=Number(c.target.value);Number.isFinite(d)&&t.onCommit(d)}}
        />
      </div>
    `}_renderDumpToGridTile(){let t=this._config?.dump_to_grid;if(!t||!this.hass)return this._renderDumpToGridLockedShell();let r=y(this._entityState(t.active)),i=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),a=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=Xe({active:r,armed:i,operationInProgress:o,snapshotValid:a,statusText:s});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let p=t.schedule,c=p?y(this._entityState(p.armed)):null,d=bt(l,c),v=this._freePowerVisualStateForInterlock(),b=Ce(l,v),m=b?"interlocked":d,w=b?_t("Free Power",v):void 0,P=this._entity(t.export_power),E=this._entity(t.stop_soc),_=this._entity(t.duration),A=this._pendingDumpPower??S(P?.state),R=this._pendingDumpStopSoc??S(E?.state),K=this._pendingDumpDuration??S(_?.state),g=this._dumpIconFor(m),x=vt(m);return u`
      <div class="tile dump-to-grid-tile state-${m}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${g}></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-${m}">${x}</span>
        </div>

        <div class="dump-to-grid-body">
          ${p&&c===!0?this._renderDumpScheduleBanner(p):h}
          ${b?this._renderInterlockBanner(w):h}

          ${this._renderDumpBody(l,{dump:t,statusText:s,snapshotValid:a,interlocked:b,stagedPowerW:A,stagedStopSoc:R,stagedDurationMin:K,stagedPowerEntity:P,stagedStopSocEntity:E,stagedDurationEntity:_})}
        </div>
      </div>
    `}_renderDumpToGridLockedShell(){return u`
      <div class="tile dump-to-grid-tile locked">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-export"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-locked"><ha-icon icon="mdi:lock-outline"></ha-icon> Coming Soon</span>
        </div>
        <p class="tile-description">Export stored battery energy to the grid.</p>

        <div class="locked-preview">
          <div class="locked-row"><span>Export Power</span><span>--</span></div>
          <div class="locked-row"><span>Minimum SOC</span><span>--</span></div>
          <div class="locked-row"><span>Duration</span><span>--</span></div>
        </div>

        <p class="tile-footnote">
          Configure <code>dump_to_grid:</code> on this card to enable Manual Dump to Grid V1.
        </p>
      </div>
    `}_dumpIconFor(t){switch(t){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(t){return u`
      <div class="tile dump-to-grid-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-off"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${t}</p>
      </div>
    `}_renderDumpBody(t,r){switch(t){case"active":return this._renderDumpActiveBody(r);case"busy":return this._renderBusyBody(r.statusText??"Dump to Grid is mid-transaction.",r.dump.status);case"deferred":return this._renderDumpDeferredBody(r);case"recovery_attention":return this._renderDumpAttentionBody(r);default:return this._renderDumpReadyOrArmedBody(t,r)}}_renderDumpReadyOrArmedBody(t,r){let i=r.dump.schedule,o=i?this._dumpMode:"now";return u`
      ${i?this._renderDumpModeSelector():h}
      ${o==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(t,r)}
      ${this._renderDumpLastEndReason(r.dump)}
    `}_renderDumpModeSelector(){let t=this._dumpMode==="now";return u`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${t?"is-active":""}"
          aria-selected=${t}
          @click=${()=>this._dumpMode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${t?"":"is-active"}"
          aria-selected=${!t}
          @click=${()=>this._dumpMode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderDumpNowPanel(t,r){let i=t==="armed",o=Ne(bn(t),r.interlocked),a=Ne(vn(t),r.interlocked);return u`
      <p class="tile-description">Export stored battery energy to the grid down to a chosen floor.</p>

      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:r.interlocked,onPreview:s=>this._pendingDumpPower=s,onCommit:s=>this._commitDumpNumber("power",s,r.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:r.stagedStopSocEntity,value:r.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:r.interlocked,onPreview:s=>this._pendingDumpStopSoc=s,onCommit:s=>this._commitDumpNumber("stop_soc",s,r.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:r.interlocked,onPreview:s=>this._pendingDumpDuration=s,onCommit:s=>this._commitDumpNumber("duration",s,r.dump.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(r.statusText,r.dump.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!a}
          @click=${()=>this._toggleArm(r.dump.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Dump to Grid"}
        </button>
        <button
          class="start-button"
          ?disabled=${!o}
          @click=${()=>this._pressDumpStart(r.dump)}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderDumpLaterPanel(t){let r=y(this._entityState(t.armed)),i=Et(r),o=this._entityState(t.start),a=fe(o),s=this._entity(t.duration),l=this._entity(t.power),p=this._entity(t.stop_soc),c=this._entityState(t.last_result),d=this._pendingDumpScheduleDuration??S(s?.state),v=this._pendingDumpSchedulePower??S(l?.state),b=this._pendingDumpScheduleStopSoc??S(p?.state),m=yt(c)||!!c&&/^FAILED/i.test(c.trim()),w=St(c),P=!!l&&!!s&&!!p&&r!==null,E=P&&!i&&a!==null&&a.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${a?this._toDatetimeLocalValue(a):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${_=>this._handleScheduleStartChange(t.start,_.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:v,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:i||!l,onPreview:_=>this._pendingDumpSchedulePower=_,onCommit:_=>this._commitDumpScheduleNumber("power",_,t.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:p,value:b,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:i||!p,onPreview:_=>this._pendingDumpScheduleStopSoc=_,onCommit:_=>this._commitDumpScheduleNumber("stop_soc",_,t.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:d,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:i||!s,onPreview:_=>this._pendingDumpScheduleDuration=_,onCommit:_=>this._commitDumpScheduleNumber("duration",_,t.duration)})}

      ${P?h:u`<p class="firmware-note is-warning">
            Scheduled Dump to Grid helpers are unavailable - is ecco_dump_to_grid_schedule.yaml installed?
          </p>`}
      ${c?u`<p class="firmware-note ${m||w?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${!E}
          @click=${()=>this._callServiceObj(Mt(t.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the Dump to Grid write-enable switch. At the start time Home Assistant stages these values, arms and presses Start; the firmware re-checks Stop SOC, charging TOU slots and Free Power itself. Arming is refused if it overlaps an armed Free Power schedule or a charging TOU slot."}
      </p>
    `}_renderDumpScheduleBanner(t){let r=fe(this._entityState(t.start)),i=S(this._entityState(t.duration)),o=S(this._entityState(t.power)),a=S(this._entityState(t.stop_soc)),s=r?Ie(r.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${r?Tt(r):"--"} • ${ne(o)} • stop
            ${we(a)} • ${ge(i)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Pt(t.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_commitDumpScheduleNumber(t,r,i){t==="power"?this._pendingDumpSchedulePower=r:t==="stop_soc"?this._pendingDumpScheduleStopSoc=r:this._pendingDumpScheduleDuration=r,this._callServiceObj(Rt(i,r))}_renderDumpLastEndReason(t){let r=this._entityState(t.last_end_reason);return!r||r==="unknown"||r==="unavailable"?h:u`<p class="firmware-note">Last lease ended: ${r}</p>`}_renderDumpActiveBody(t){let r=this._entityState(t.dump.ends_at),i=fe(r),o=i?Ie(i.getTime(),this._nowMs):null,a=S(this._entityState(t.dump.battery_soc)),s=_n(S(this._entityState(t.dump.active_export_power)),t.statusText),l=wn(S(this._entityState(t.dump.active_stop_soc)),t.statusText);return u`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${ne(s)} export • ends ${i?this._formatClock(i):r??"--"}
      </div>
      <div class="active-secondary-line">
        Battery: ${we(a)} • stops at ${we(l)}
      </div>

      <div class="readiness-row">
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
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(t.statusText??"Dump to Grid requires operator attention.",t.dump.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${i?"Automatic restore is stopped until you decide. Arm recovery, then Force Restore Original (writes only the saved original settings) or Accept Current State (writes nothing; refused while the inverter still shows Dump export).":"If the status above says the watchdog will retry, ECCO keeps retrying the restore automatically. Only OPERATOR DECISION REQUIRED stops automatic retries."}
      </p>
      ${i?this._renderDumpRecoveryPanel(t.dump):h}
      ${this._renderEndDumpButton(t.dump.end_restore,"End & Restore Now",Qe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(t){let r=y(this._entityState(t.recovery_arm))===!0,i=this._entityState(t.recovery_state);return u`
      <div class="dump-recovery-panel">
        ${i&&i!=="unknown"&&i!=="unavailable"?u`<p class="firmware-note">${i}</p>`:h}
        <div class="action-row">
          <button
            class="arm-toggle ${r?"is-armed":""}"
            @click=${()=>this._toggleArm(t.recovery_arm,r)}
          >
            <ha-icon icon=${r?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
            ${r?"Disarm Recovery":"Arm Recovery"}
          </button>
        </div>
        <div class="action-row">
          <button
            class="start-button"
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:t.recovery_force_restore})}
          >
            <ha-icon icon="mdi:backup-restore"></ha-icon>
            Force Restore Original
          </button>
          <button
            class="arm-toggle"
            ?disabled=${!r}
            @click=${()=>this._callService("button","press",{entity_id:t.recovery_accept})}
          >
            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
            Accept Current State
          </button>
        </div>
      </div>
    `}_renderDumpDiagnosticsDetails(t){let r=[],i=(o,a)=>{let s=S(this._entityState(a));s!==null&&r.push({label:o,value:s.toString()})};return i("Starts",t.start_attempts),i("Started OK",t.start_successes),i("Restored OK",t.restore_successes),i("Failures",t.failures),r.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(t,r,i){let o=this._confirmEndDump;return u`
      <button
        class="end-restore-button ${o?"confirming":""}"
        ?disabled=${!i}
        @click=${()=>this._handleEndDumpClick(t)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${o?"Tap again to End & Restore":r}
        ${o?u`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:h}
      </button>
    `}};T.styles=[cr,vr,de`
    :host {
      /* Container query, not a viewport media query: this card is often
         docked in a narrow dashboard column on an otherwise-wide desktop
         browser (a sidebar/split-view layout), which a viewport-width
         media query would never see as "narrow" - the responsive rules
         below need to react to the CARD's own rendered width instead. */
      container-type: inline-size;

      --eaa-bg: var(--ecco-card-background, #141c2d);
      --eaa-surface: color-mix(in srgb, var(--eaa-bg) 82%, white 6%);
      --eaa-border: color-mix(in srgb, var(--eaa-bg) 70%, white 12%);
      --eaa-text: var(--primary-text-color, #eef2f7);
      --eaa-text-muted: var(--secondary-text-color, #9aa7b8);
      --eaa-accent: var(--primary-color, #4fd1ff);
      --eaa-ok: #38d996;
      --eaa-warning: #f4b942;
      --eaa-fault: #ff5c6c;
      --eaa-armed: #ffbd3d;
      --eaa-schedule: #c07cff;
      --eaa-glow: color-mix(in srgb, var(--eaa-accent) 45%, transparent);

      display: block;
    }

    ha-card {
      background: linear-gradient(160deg, var(--eaa-bg), color-mix(in srgb, var(--eaa-bg) 88%, black 8%));
      color: var(--eaa-text);
      border-radius: 20px;
      padding: 18px 18px 20px;
      overflow: hidden;
    }

    .card-title {
      margin: 0 0 14px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: var(--eaa-text);
    }

    .actions-grid {
      display: grid;
      /* 2026-09-26 sibling card polish: Free Power and Dump to Grid are
         equal first-class siblings, not a main feature plus a secondary
         column - both tracks get the same flexible 1fr share, each with the
         same 280px floor Dump to Grid alone used to have, so neither tile's
         controls (NOW/LATER selector, sliders, Arm/Start, banners) get
         squeezed. No max-width on the grid itself: a real wide dashboard
         card should use its full width - see .free-power-body/
         .dump-to-grid-body below for where the actual controls are capped
         instead, so sliders/buttons never stretch edge-to-edge even though
         each tile's own card border now does. */
      grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr);
      gap: 16px;
      /* 2026-09-26 equal-height polish: stretch (the grid default, made
         explicit here) rather than "start" - Dump to Grid's extra Stop SOC
         row and status/last-lease line make it naturally taller than Free
         Power, and the two should still finish on the same line rather than
         Free Power ending early with a visible gap beneath it. Only has an
         effect while both tiles share one grid row (the two-column desktop/
         tablet layout above) - the single-column stack below has exactly
         one tile per row, so this is a no-op there and each stacked card
         keeps its own natural content height (see .tile's comment below). */
      align-items: stretch;
    }

    @container (max-width: 620px) {
      .actions-grid {
        grid-template-columns: 1fr;
      }
    }

    /* Caps and centres the actual staging/control area within each tile -
       the tile's own border/background still spans the full flexible grid
       column (so the tile reads as deliberately sized, not glued to one
       side with empty space beside it), but the sliders, buttons and text
       inside stay a comfortable, non-absurd width. Centring (not
       left-alignment) is what keeps the extra space either side of the
       controls, once a tile is wider than this, from reading as a leftover
       void - has no effect at all once the tile itself is narrower than
       this, which is the common case on tablet/mobile and needs no
       separate breakpoint. Both tiles share the same cap so they read as
       the same product family.
       Also a flex column (2026-09-26 equal-height polish) so it can grow to
       fill whatever extra height .actions-grid's stretch gives the shorter
       tile - see .action-row's margin-top: auto below for where that spare
       height actually goes. */
    .free-power-body,
    .dump-to-grid-body {
      max-width: 680px;
      margin: 0 auto;
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
    }

    .tile {
      border-radius: 16px;
      background: var(--eaa-surface);
      border: 1px solid var(--eaa-border);
      padding: 14px 16px 16px;
      box-sizing: border-box;
      /* Flex column (2026-09-26 equal-height polish) purely so
         .free-power-body/.dump-to-grid-body above can flex:1 to fill
         whatever height .actions-grid's align-items: stretch gives this
         tile - visually identical to plain block stacking otherwise. */
      display: flex;
      flex-direction: column;
      transition:
        border-color 0.28s ease,
        background 0.28s ease,
        box-shadow 0.28s ease;
    }

    .tile-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }

    .tile-heading {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .tile-icon {
      --mdc-icon-size: 20px;
      color: var(--eaa-text-muted);
    }

    .tile-name {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.01em;
      /* Never truncated (e.g. "Dump to Grid" -> "Dump...") - if the header
         row gets tight, the pill wraps to its own line before the name
         would ever be squeezed (see .tile-header's flex-wrap above). */
      white-space: normal;
    }

    .tile-description {
      margin: 2px 0 12px;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    .state-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 10.5px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 4px 9px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
      white-space: nowrap;
    }
    .state-pill ha-icon {
      --mdc-icon-size: 12px;
    }
    .state-pill.state-ready {
      background: color-mix(in srgb, var(--eaa-accent) 20%, transparent);
      color: var(--eaa-accent);
    }
    .state-pill.state-armed {
      background: color-mix(in srgb, var(--eaa-armed) 24%, transparent);
      color: var(--eaa-armed);
    }
    .state-pill.state-scheduled {
      background: color-mix(in srgb, var(--eaa-schedule) 24%, transparent);
      color: var(--eaa-schedule);
    }
    .state-pill.state-active {
      background: color-mix(in srgb, var(--eaa-ok) 24%, transparent);
      color: var(--eaa-ok);
    }
    .state-pill.state-busy,
    .state-pill.state-deferred {
      background: color-mix(in srgb, var(--eaa-warning) 20%, transparent);
      color: var(--eaa-warning);
    }
    .state-pill.state-recovery_attention {
      background: color-mix(in srgb, var(--eaa-fault) 24%, transparent);
      color: var(--eaa-fault);
    }
    .state-pill.state-locked {
      background: color-mix(in srgb, var(--eaa-text-muted) 16%, transparent);
      color: var(--eaa-text-muted);
    }
    .state-pill.state-interlocked {
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
    }

    /* ---- Free Power tile state tints ---- */
    .free-power-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .free-power-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .free-power-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .free-power-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .free-power-tile.state-busy,
    .free-power-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .free-power-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    .free-power-tile.state-unavailable {
      opacity: 0.6;
    }
    /* Subdued, no glow/animation - a deliberately quieter tint than
       recovery_attention/busy (this feature is not at fault, its sibling
       currently owns the inverter, see interlock.ts). */
    .free-power-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }

    /* ---- Dump to Grid tile state tints - same tokens as Free Power above ---- */
    .dump-to-grid-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .dump-to-grid-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .dump-to-grid-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .dump-to-grid-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .dump-recovery-panel {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px;
      border-radius: 12px;
      border: 1px dashed color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
    }
    .dump-to-grid-tile.state-busy,
    .dump-to-grid-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .dump-to-grid-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    /* Subdued, no glow/animation - same rationale as
       .free-power-tile.state-interlocked above. */
    .dump-to-grid-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }
    .dump-to-grid-tile.state-unavailable {
      opacity: 0.6;
    }

    @keyframes eaa-active-glow {
      0%,
      100% {
        box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-ok) 45%, transparent);
      }
      50% {
        box-shadow: 0 0 26px -4px color-mix(in srgb, var(--eaa-ok) 62%, transparent);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .free-power-tile.state-active,
      .dump-to-grid-tile.state-active {
        animation: none;
      }
      .spin {
        animation: none !important;
      }
      .confirm-progress {
        display: none;
      }
    }

    /* ---- NOW / LATER mode selector ---- */
    .mode-selector {
      display: flex;
      gap: 4px;
      padding: 3px;
      margin-bottom: 12px;
      border-radius: 10px;
      background: color-mix(in srgb, var(--eaa-bg) 60%, transparent);
      border: 1px solid var(--eaa-border);
    }
    .mode-tab {
      flex: 1 1 auto;
      border: none;
      background: transparent;
      color: var(--eaa-text-muted);
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 700;
    }
    .mode-tab ha-icon {
      --mdc-icon-size: 15px;
    }
    .mode-tab.is-active {
      background: var(--eaa-surface);
      color: var(--eaa-text);
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
    }

    /* ---- Schedule banner (shown in both Now and Later views while armed) ---- */
    .schedule-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-schedule) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .schedule-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-schedule);
      flex-shrink: 0;
    }
    .schedule-banner-text {
      min-width: 0;
      flex: 1 1 auto;
    }
    .schedule-banner-line {
      font-size: 12px;
      font-weight: 700;
      color: var(--eaa-text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .schedule-banner-countdown {
      font-size: 11px;
      color: var(--eaa-schedule);
      font-variant-numeric: tabular-nums;
    }
    .schedule-cancel-button {
      flex: 0 0 auto;
      padding: 7px 12px;
      font-size: 11px;
      min-height: 36px;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      background: transparent;
    }

    /* ---- Interlock banner - deliberately muted/neutral, not warning-
       coloured like the schedule banner above: this feature isn't at
       fault, its sibling currently owns the inverter (see interlock.ts). */
    .interlock-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, var(--eaa-surface));
      border: 1px dashed color-mix(in srgb, var(--eaa-text-muted) 40%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .interlock-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-text-muted);
      flex-shrink: 0;
    }
    .interlock-banner-text {
      min-width: 0;
      flex: 1 1 auto;
      font-size: 12px;
      font-weight: 600;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    /* ---- Schedule (LATER) fields ---- */
    .schedule-field {
      margin-bottom: 12px;
    }
    .schedule-field-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .schedule-field-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .schedule-datetime-input {
      width: 100%;
      box-sizing: border-box;
      font: inherit;
      font-size: 13px;
      color: var(--eaa-text);
      background: color-mix(in srgb, var(--eaa-bg) 55%, transparent);
      border: 1px solid var(--eaa-border);
      border-radius: 8px;
      padding: 9px 10px;
      min-height: 40px;
      color-scheme: dark;
    }
    .schedule-datetime-input:disabled {
      opacity: 0.5;
    }
    .schedule-arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-schedule) 55%, var(--eaa-border));
      color: var(--eaa-schedule);
      background: color-mix(in srgb, var(--eaa-schedule) 10%, var(--eaa-surface));
    }
    .schedule-arm-toggle:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-schedule) 18%, var(--eaa-surface));
    }

    .arm-caption {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 8px 0 0;
      opacity: 0.85;
    }

    /* ---- Number controls ---- */
    .number-control {
      margin-bottom: 12px;
    }
    .number-control-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .number-control-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .number-control-value {
      margin-left: auto;
      font-size: 13px;
      font-weight: 700;
      color: var(--eaa-text);
      font-variant-numeric: tabular-nums;
    }
    .number-control-slider {
      width: 100%;
      appearance: none;
      -webkit-appearance: none;
      height: 6px;
      border-radius: 999px;
      background: linear-gradient(
        to right,
        var(--eaa-accent) 0%,
        var(--eaa-accent) var(--eaa-slider-fill, 0%),
        color-mix(in srgb, var(--eaa-text-muted) 28%, transparent) var(--eaa-slider-fill, 0%)
      );
      outline: none;
      cursor: pointer;
    }
    .number-control-slider::-webkit-slider-thumb {
      appearance: none;
      -webkit-appearance: none;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--eaa-accent) 60%, transparent);
    }
    .number-control-slider::-moz-range-thumb {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
    }
    .number-control-slider:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .number-control-slider:focus-visible {
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--eaa-accent) 40%, transparent);
    }

    .readiness-row {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      margin: 6px 0 10px;
    }
    .readiness-row ha-icon {
      --mdc-icon-size: 15px;
    }

    .firmware-note {
      /* Deliberately quiet - a plain status line, not a boxed/input-like
         control. The literal firmware text stays fully readable and
         tappable; it just no longer competes visually with the actual
         controls above it. .is-warning (below) is the one exception - a
         schedule REJECTED/BLOCKED outcome earns the extra weight. */
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      opacity: 0.9;
      margin: 0 0 10px;
      line-height: 1.4;
      word-break: break-word;
    }
    .firmware-note.is-warning {
      background: color-mix(in srgb, var(--eaa-warning) 16%, transparent);
      color: color-mix(in srgb, var(--eaa-warning) 70%, var(--eaa-text));
      border-radius: 8px;
      padding: 6px 9px;
      opacity: 1;
    }
    .firmware-note.clickable,
    .transition-detail.clickable {
      cursor: pointer;
    }
    .firmware-note.clickable:hover {
      color: var(--eaa-text);
      opacity: 1;
    }
    .firmware-note:focus-visible,
    .transition-detail:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .action-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      /* 2026-09-26 equal-height polish: an auto top margin inside the now-
         flex-column .free-power-body/.dump-to-grid-body absorbs whatever
         spare height align-items: stretch gave the shorter tile, so the
         Arm/Start row (and the footer text right after it) settles at the
         bottom of the card instead of leaving a gap beneath it - every
         control above keeps its normal spacing untouched. Resolves to 0
         (today's exact layout) whenever there's no spare height to absorb -
         the taller tile, and every tile once stacked single-column. */
      margin-top: auto;
    }

    button {
      font: inherit;
      border: 1px solid var(--eaa-border);
      background: var(--eaa-surface);
      color: var(--eaa-text);
      border-radius: 10px;
      padding: 10px 14px;
      min-height: 44px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 12.5px;
      font-weight: 700;
      cursor: pointer;
      transition:
        background 0.18s ease,
        border-color 0.18s ease,
        opacity 0.18s ease,
        transform 0.1s ease;
      flex: 1 1 auto;
    }
    button ha-icon {
      --mdc-icon-size: 16px;
    }
    button:disabled {
      opacity: 0.38;
      cursor: not-allowed;
    }
    button:not(:disabled):active {
      transform: scale(0.98);
    }
    button:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-armed) 45%, var(--eaa-border));
      color: var(--eaa-armed);
    }
    .arm-toggle.is-armed {
      background: color-mix(in srgb, var(--eaa-armed) 18%, var(--eaa-surface));
      border-color: color-mix(in srgb, var(--eaa-armed) 70%, var(--eaa-border));
    }

    .start-button {
      border-color: color-mix(in srgb, var(--eaa-ok) 55%, var(--eaa-border));
      color: var(--eaa-ok);
      background: color-mix(in srgb, var(--eaa-ok) 10%, var(--eaa-surface));
    }
    .start-button:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-ok) 18%, var(--eaa-surface));
    }

    .end-restore-button {
      position: relative;
      overflow: hidden;
      width: 100%;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      margin-top: 4px;
    }
    .end-restore-button.secondary {
      border-color: var(--eaa-border);
      color: var(--eaa-text-muted);
      background: transparent;
      font-weight: 600;
    }
    .end-restore-button.confirming {
      background: color-mix(in srgb, var(--eaa-fault) 22%, var(--eaa-surface));
      border-color: var(--eaa-fault);
    }
    .confirm-progress {
      position: absolute;
      left: 0;
      bottom: 0;
      height: 3px;
      background: currentColor;
      animation-name: eaa-confirm-shrink;
      animation-timing-function: linear;
      animation-fill-mode: forwards;
    }
    @keyframes eaa-confirm-shrink {
      from {
        width: 100%;
      }
      to {
        width: 0%;
      }
    }

    /* ---- Active hero ---- */
    .active-hero {
      text-align: center;
      padding: 6px 0 2px;
    }
    .active-hero-time {
      font-size: 34px;
      font-weight: 800;
      color: var(--eaa-ok);
      font-variant-numeric: tabular-nums;
      line-height: 1.1;
    }
    .active-hero-label {
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--eaa-text-muted);
      margin-top: 2px;
    }
    .active-secondary-line {
      text-align: center;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      margin: 8px 0 12px;
    }

    .diagnostics-details {
      margin: 0 0 10px;
    }
    .diagnostics-details summary {
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      list-style: none;
      user-select: none;
    }
    .diagnostics-details summary::-webkit-details-marker {
      display: none;
    }
    .diagnostics-details summary::before {
      content: "▸ ";
    }
    .diagnostics-details[open] summary::before {
      content: "▾ ";
    }
    .diagnostics-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }
    .diagnostic-chip {
      font-size: 9.5px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, transparent);
      border-radius: 999px;
      padding: 3px 8px;
    }

    /* ---- Transition / attention panels ---- */
    .transition-panel,
    .attention-panel {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-warning) 10%, transparent);
      margin-bottom: 8px;
    }
    .attention-panel {
      background: color-mix(in srgb, var(--eaa-fault) 12%, transparent);
    }
    .transition-panel ha-icon,
    .attention-panel ha-icon {
      --mdc-icon-size: 22px;
      color: var(--eaa-warning);
      flex-shrink: 0;
      margin-top: 1px;
    }
    .attention-panel ha-icon {
      color: var(--eaa-fault);
    }
    .transition-panel.deferred ha-icon {
      color: var(--eaa-warning);
    }
    .transition-text {
      min-width: 0;
    }
    .transition-headline {
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 2px;
    }
    .transition-detail {
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      word-break: break-word;
    }
    .transition-hint {
      font-size: 11px;
      color: var(--eaa-text-muted);
      margin: 0 0 10px;
      line-height: 1.4;
    }

    .spin {
      animation: eaa-spin 1.6s linear infinite;
    }
    @keyframes eaa-spin {
      from {
        transform: rotate(0deg);
      }
      to {
        transform: rotate(360deg);
      }
    }

    /* ---- Dump to Grid (locked) tile ---- */
    .dump-to-grid-tile.locked {
      background: color-mix(in srgb, var(--eaa-bg) 92%, transparent);
      position: relative;
    }
    /* Scoped to .locked only - the dimmed icon is a "not available yet" cue
       for the static preview shell and must NOT bleed into the real
       interactive tile once dump_to_grid: is configured (V1). */
    .dump-to-grid-tile.locked .tile-icon {
      opacity: 0.6;
    }
    .locked-preview {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 10px;
      opacity: 0.55;
      pointer-events: none;
      user-select: none;
    }
    .locked-row {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 8%, transparent);
      border-radius: 8px;
      padding: 7px 10px;
    }
    .tile-footnote {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 0;
      opacity: 0.85;
    }

    /* Mobile: Dump to Grid collapses to a compact locked row - header +
       description + footnote only, dropping the dimmed preview rows. */
    /* Covers both the cramped-second-column case just above the 620px
       stacking point, and a typical stacked phone width below it - in
       both cases Dump to Grid has too little room to justify the three
       dimmed preview rows. */
    @container (max-width: 700px) {
      .dump-to-grid-tile .locked-preview {
        display: none;
      }
      .dump-to-grid-tile {
        padding: 12px 14px 14px;
      }
    }

    /* ---- layout: tabbed (OVW1) - one track visible at a time. The track
       tabs reuse the NOW/LATER selector's look, the header chips reuse the
       state-pill tones, and the cross-track alert banner mirrors the
       schedule banner's shape in the hidden track's own tone. ---- */
    .tabbed-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin-bottom: 12px;
    }
    .tabbed-header .card-title {
      margin: 0;
    }
    .track-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .track-selector {
      border-radius: 12px;
      margin-bottom: 10px;
    }
    .track-tab {
      min-height: 44px;
      border-radius: 9px;
      font-size: 13px;
      font-weight: 800;
    }
    .track-tab ha-icon {
      --mdc-icon-size: 17px;
    }
    .track-alert {
      --eaa-alert: var(--eaa-accent);
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-alert) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
      margin-bottom: 12px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.4;
    }
    .track-alert-warning {
      --eaa-alert: var(--eaa-warning);
    }
    .track-alert-fault {
      --eaa-alert: var(--eaa-fault);
    }
    .track-alert ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-alert);
      flex-shrink: 0;
    }
    .track-alert-text {
      min-width: 0;
      flex: 1 1 auto;
      word-break: break-word;
    }
    .track-alert-show {
      flex: 0 0 auto;
      min-height: 36px;
      padding: 7px 12px;
      font-size: 11px;
      background: transparent;
      color: var(--eaa-alert);
      border-color: color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
    }
    .actions-grid.is-tabbed {
      /* minmax(0, 1fr), not 1fr: a bare 1fr track is min-content-sized and lets a long nowrap line (the armed
         schedule banner) push the single tile wider than the card on a phone. Scoped to the tabbed layout. */
      grid-template-columns: minmax(0, 1fr);
    }
    @container (max-width: 620px) {
      .tabbed-header {
        flex-direction: column;
        align-items: flex-start;
      }
      .track-tab {
        padding: 7px 8px;
        font-size: 12px;
      }
    }
  `],C([ze({attribute:!1})],T.prototype,"hass",2),C([O()],T.prototype,"_config",2),C([O()],T.prototype,"_pendingPower",2),C([O()],T.prototype,"_pendingDuration",2),C([O()],T.prototype,"_pendingSchedulePower",2),C([O()],T.prototype,"_pendingScheduleDuration",2),C([O()],T.prototype,"_confirmEndRestore",2),C([O()],T.prototype,"_pendingDumpPower",2),C([O()],T.prototype,"_pendingDumpStopSoc",2),C([O()],T.prototype,"_pendingDumpDuration",2),C([O()],T.prototype,"_confirmEndDump",2),C([O()],T.prototype,"_dumpMode",2),C([O()],T.prototype,"_pendingDumpSchedulePower",2),C([O()],T.prototype,"_pendingDumpScheduleStopSoc",2),C([O()],T.prototype,"_pendingDumpScheduleDuration",2),C([O()],T.prototype,"_nowMs",2),C([O()],T.prototype,"_mode",2),C([O()],T.prototype,"_track",2),T=C([hn("ecco-energy-actions-card")],T);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{T as EccoEnergyActionsCard};
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
lit-html/lit-html.js:
lit-element/lit-element.js:
@lit/reactive-element/decorators/custom-element.js:
@lit/reactive-element/decorators/property.js:
@lit/reactive-element/decorators/state.js:
@lit/reactive-element/decorators/event-options.js:
@lit/reactive-element/decorators/base.js:
@lit/reactive-element/decorators/query.js:
@lit/reactive-element/decorators/query-all.js:
@lit/reactive-element/decorators/query-async.js:
@lit/reactive-element/decorators/query-assigned-nodes.js:
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

@lit/reactive-element/decorators/query-assigned-elements.js:
  (**
   * @license
   * Copyright 2021 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
