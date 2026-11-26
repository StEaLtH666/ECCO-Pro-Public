var Cr=Object.defineProperty;var Nr=Object.getOwnPropertyDescriptor;var O=(e,n,t,r)=>{for(var a=r>1?void 0:r?Nr(n,t):n,o=e.length-1,i;o>=0;o--)(i=e[o])&&(a=(r?i(n,t,a):i(a))||a);return r&&a&&Cr(n,t,a),a};var je=globalThis,ze=je.ShadowRoot&&(je.ShadyCSS===void 0||je.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,st=Symbol(),Zt=new WeakMap,Re=class{constructor(n,t,r){if(this._$cssResult$=!0,r!==st)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=n,this.t=t}get styleSheet(){let n=this.o,t=this.t;if(ze&&n===void 0){let r=t!==void 0&&t.length===1;r&&(n=Zt.get(t)),n===void 0&&((this.o=n=new CSSStyleSheet).replaceSync(this.cssText),r&&Zt.set(t,n))}return n}toString(){return this.cssText}},en=e=>new Re(typeof e=="string"?e:e+"",void 0,st),de=(e,...n)=>{let t=e.length===1?e[0]:n.reduce((r,a,o)=>r+(i=>{if(i._$cssResult$===!0)return i.cssText;if(typeof i=="number")return i;throw Error("Value passed to 'css' function must be a 'css' function result: "+i+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(a)+e[o+1],e[0]);return new Re(t,e,st)},tn=(e,n)=>{if(ze)e.adoptedStyleSheets=n.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(let t of n){let r=document.createElement("style"),a=je.litNonce;a!==void 0&&r.setAttribute("nonce",a),r.textContent=t.cssText,e.appendChild(r)}},lt=ze?e=>e:e=>e instanceof CSSStyleSheet?(n=>{let t="";for(let r of n.cssRules)t+=r.cssText;return en(t)})(e):e;var{is:Ir,defineProperty:Or,getOwnPropertyDescriptor:$r,getOwnPropertyNames:Lr,getOwnPropertySymbols:Wr,getPrototypeOf:Fr}=Object,Ye=globalThis,nn=Ye.trustedTypes,Vr=nn?nn.emptyScript:"",Ur=Ye.reactiveElementPolyfillSupport,Pe=(e,n)=>e,Te={toAttribute(e,n){switch(n){case Boolean:e=e?Vr:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,n){let t=e;switch(n){case Boolean:t=e!==null;break;case Number:t=e===null?null:Number(e);break;case Object:case Array:try{t=JSON.parse(e)}catch{t=null}}return t}},qe=(e,n)=>!Ir(e,n),rn={attribute:!0,type:String,converter:Te,reflect:!1,useDefault:!1,hasChanged:qe};Symbol.metadata??=Symbol("metadata"),Ye.litPropertyMetadata??=new WeakMap;var te=class extends HTMLElement{static addInitializer(n){this._$Ei(),(this.l??=[]).push(n)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(n,t=rn){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(n)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(n,t),!t.noAccessor){let r=Symbol(),a=this.getPropertyDescriptor(n,r,t);a!==void 0&&Or(this.prototype,n,a)}}static getPropertyDescriptor(n,t,r){let{get:a,set:o}=$r(this.prototype,n)??{get(){return this[t]},set(i){this[t]=i}};return{get:a,set(i){let s=a?.call(this);o?.call(this,i),this.requestUpdate(n,s,r)},configurable:!0,enumerable:!0}}static getPropertyOptions(n){return this.elementProperties.get(n)??rn}static _$Ei(){if(this.hasOwnProperty(Pe("elementProperties")))return;let n=Fr(this);n.finalize(),n.l!==void 0&&(this.l=[...n.l]),this.elementProperties=new Map(n.elementProperties)}static finalize(){if(this.hasOwnProperty(Pe("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(Pe("properties"))){let t=this.properties,r=[...Lr(t),...Wr(t)];for(let a of r)this.createProperty(a,t[a])}let n=this[Symbol.metadata];if(n!==null){let t=litPropertyMetadata.get(n);if(t!==void 0)for(let[r,a]of t)this.elementProperties.set(r,a)}this._$Eh=new Map;for(let[t,r]of this.elementProperties){let a=this._$Eu(t,r);a!==void 0&&this._$Eh.set(a,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(n){let t=[];if(Array.isArray(n)){let r=new Set(n.flat(1/0).reverse());for(let a of r)t.unshift(lt(a))}else n!==void 0&&t.push(lt(n));return t}static _$Eu(n,t){let r=t.attribute;return r===!1?void 0:typeof r=="string"?r:typeof n=="string"?n.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(n=>this.enableUpdating=n),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(n=>n(this))}addController(n){(this._$EO??=new Set).add(n),this.renderRoot!==void 0&&this.isConnected&&n.hostConnected?.()}removeController(n){this._$EO?.delete(n)}_$E_(){let n=new Map,t=this.constructor.elementProperties;for(let r of t.keys())this.hasOwnProperty(r)&&(n.set(r,this[r]),delete this[r]);n.size>0&&(this._$Ep=n)}createRenderRoot(){let n=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return tn(n,this.constructor.elementStyles),n}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(n=>n.hostConnected?.())}enableUpdating(n){}disconnectedCallback(){this._$EO?.forEach(n=>n.hostDisconnected?.())}attributeChangedCallback(n,t,r){this._$AK(n,r)}_$ET(n,t){let r=this.constructor.elementProperties.get(n),a=this.constructor._$Eu(n,r);if(a!==void 0&&r.reflect===!0){let o=(r.converter?.toAttribute!==void 0?r.converter:Te).toAttribute(t,r.type);this._$Em=n,o==null?this.removeAttribute(a):this.setAttribute(a,o),this._$Em=null}}_$AK(n,t){let r=this.constructor,a=r._$Eh.get(n);if(a!==void 0&&this._$Em!==a){let o=r.getPropertyOptions(a),i=typeof o.converter=="function"?{fromAttribute:o.converter}:o.converter?.fromAttribute!==void 0?o.converter:Te;this._$Em=a;let s=i.fromAttribute(t,o.type);this[a]=s??this._$Ej?.get(a)??s,this._$Em=null}}requestUpdate(n,t,r,a=!1,o){if(n!==void 0){let i=this.constructor;if(a===!1&&(o=this[n]),r??=i.getPropertyOptions(n),!((r.hasChanged??qe)(o,t)||r.useDefault&&r.reflect&&o===this._$Ej?.get(n)&&!this.hasAttribute(i._$Eu(n,r))))return;this.C(n,t,r)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(n,t,{useDefault:r,reflect:a,wrapped:o},i){r&&!(this._$Ej??=new Map).has(n)&&(this._$Ej.set(n,i??t??this[n]),o!==!0||i!==void 0)||(this._$AL.has(n)||(this.hasUpdated||r||(t=void 0),this._$AL.set(n,t)),a===!0&&this._$Em!==n&&(this._$Eq??=new Set).add(n))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}let n=this.scheduleUpdate();return n!=null&&await n,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[a,o]of this._$Ep)this[a]=o;this._$Ep=void 0}let r=this.constructor.elementProperties;if(r.size>0)for(let[a,o]of r){let{wrapped:i}=o,s=this[a];i!==!0||this._$AL.has(a)||s===void 0||this.C(a,void 0,o,s)}}let n=!1,t=this._$AL;try{n=this.shouldUpdate(t),n?(this.willUpdate(t),this._$EO?.forEach(r=>r.hostUpdate?.()),this.update(t)):this._$EM()}catch(r){throw n=!1,this._$EM(),r}n&&this._$AE(t)}willUpdate(n){}_$AE(n){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(n)),this.updated(n)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(n){return!0}update(n){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(n){}firstUpdated(n){}};te.elementStyles=[],te.shadowRootOptions={mode:"open"},te[Pe("elementProperties")]=new Map,te[Pe("finalized")]=new Map,Ur?.({ReactiveElement:te}),(Ye.reactiveElementVersions??=[]).push("2.1.2");var ft=globalThis,an=e=>e,Xe=ft.trustedTypes,on=Xe?Xe.createPolicy("lit-html",{createHTML:e=>e}):void 0,pn="$lit$",ie=`lit$${Math.random().toFixed(9).slice(2)}$`,hn="?"+ie,Hr=`<${hn}>`,he=document,Ae=()=>he.createComment(""),Ce=e=>e===null||typeof e!="object"&&typeof e!="function",gt=Array.isArray,Gr=e=>gt(e)||typeof e?.[Symbol.iterator]=="function",ct=`[ 	
\f\r]`,De=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,sn=/-->/g,ln=/>/g,ue=RegExp(`>|${ct}(?:([^\\s"'>=/]+)(${ct}*=${ct}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),cn=/'/g,dn=/"/g,mn=/^(?:script|style|textarea|title)$/i,bt=e=>(n,...t)=>({_$litType$:e,strings:n,values:t}),u=bt(1),Qo=bt(2),Jo=bt(3),me=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),un=new WeakMap,pe=he.createTreeWalker(he,129);function fn(e,n){if(!gt(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return on!==void 0?on.createHTML(n):n}var Kr=(e,n)=>{let t=e.length-1,r=[],a,o=n===2?"<svg>":n===3?"<math>":"",i=De;for(let s=0;s<t;s++){let l=e[s],c,d,p=-1,v=0;for(;v<l.length&&(i.lastIndex=v,d=i.exec(l),d!==null);)v=i.lastIndex,i===De?d[1]==="!--"?i=sn:d[1]!==void 0?i=ln:d[2]!==void 0?(mn.test(d[2])&&(a=RegExp("</"+d[2],"g")),i=ue):d[3]!==void 0&&(i=ue):i===ue?d[0]===">"?(i=a??De,p=-1):d[1]===void 0?p=-2:(p=i.lastIndex-d[2].length,c=d[1],i=d[3]===void 0?ue:d[3]==='"'?dn:cn):i===dn||i===cn?i=ue:i===sn||i===ln?i=De:(i=ue,a=void 0);let b=i===ue&&e[s+1].startsWith("/>")?" ":"";o+=i===De?l+Hr:p>=0?(r.push(c),l.slice(0,p)+pn+l.slice(p)+ie+b):l+ie+(p===-2?s:b)}return[fn(e,o+(e[t]||"<?>")+(n===2?"</svg>":n===3?"</math>":"")),r]},Ne=class e{constructor({strings:n,_$litType$:t},r){let a;this.parts=[];let o=0,i=0,s=n.length-1,l=this.parts,[c,d]=Kr(n,t);if(this.el=e.createElement(c,r),pe.currentNode=this.el.content,t===2||t===3){let p=this.el.content.firstChild;p.replaceWith(...p.childNodes)}for(;(a=pe.nextNode())!==null&&l.length<s;){if(a.nodeType===1){if(a.hasAttributes())for(let p of a.getAttributeNames())if(p.endsWith(pn)){let v=d[i++],b=a.getAttribute(p).split(ie),g=/([.?@])?(.*)/.exec(v);l.push({type:1,index:o,name:g[2],strings:b,ctor:g[1]==="."?ut:g[1]==="?"?pt:g[1]==="@"?ht:_e}),a.removeAttribute(p)}else p.startsWith(ie)&&(l.push({type:6,index:o}),a.removeAttribute(p));if(mn.test(a.tagName)){let p=a.textContent.split(ie),v=p.length-1;if(v>0){a.textContent=Xe?Xe.emptyScript:"";for(let b=0;b<v;b++)a.append(p[b],Ae()),pe.nextNode(),l.push({type:2,index:++o});a.append(p[v],Ae())}}}else if(a.nodeType===8)if(a.data===hn)l.push({type:2,index:o});else{let p=-1;for(;(p=a.data.indexOf(ie,p+1))!==-1;)l.push({type:7,index:o}),p+=ie.length-1}o++}}static createElement(n,t){let r=he.createElement("template");return r.innerHTML=n,r}};function ve(e,n,t=e,r){if(n===me)return n;let a=r!==void 0?t._$Co?.[r]:t._$Cl,o=Ce(n)?void 0:n._$litDirective$;return a?.constructor!==o&&(a?._$AO?.(!1),o===void 0?a=void 0:(a=new o(e),a._$AT(e,t,r)),r!==void 0?(t._$Co??=[])[r]=a:t._$Cl=a),a!==void 0&&(n=ve(e,a._$AS(e,n.values),a,r)),n}var dt=class{constructor(n,t){this._$AV=[],this._$AN=void 0,this._$AD=n,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(n){let{el:{content:t},parts:r}=this._$AD,a=(n?.creationScope??he).importNode(t,!0);pe.currentNode=a;let o=pe.nextNode(),i=0,s=0,l=r[0];for(;l!==void 0;){if(i===l.index){let c;l.type===2?c=new Ie(o,o.nextSibling,this,n):l.type===1?c=new l.ctor(o,l.name,l.strings,this,n):l.type===6&&(c=new mt(o,this,n)),this._$AV.push(c),l=r[++s]}i!==l?.index&&(o=pe.nextNode(),i++)}return pe.currentNode=he,a}p(n){let t=0;for(let r of this._$AV)r!==void 0&&(r.strings!==void 0?(r._$AI(n,r,t),t+=r.strings.length-2):r._$AI(n[t])),t++}},Ie=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(n,t,r,a){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=n,this._$AB=t,this._$AM=r,this.options=a,this._$Cv=a?.isConnected??!0}get parentNode(){let n=this._$AA.parentNode,t=this._$AM;return t!==void 0&&n?.nodeType===11&&(n=t.parentNode),n}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(n,t=this){n=ve(this,n,t),Ce(n)?n===h||n==null||n===""?(this._$AH!==h&&this._$AR(),this._$AH=h):n!==this._$AH&&n!==me&&this._(n):n._$litType$!==void 0?this.$(n):n.nodeType!==void 0?this.T(n):Gr(n)?this.k(n):this._(n)}O(n){return this._$AA.parentNode.insertBefore(n,this._$AB)}T(n){this._$AH!==n&&(this._$AR(),this._$AH=this.O(n))}_(n){this._$AH!==h&&Ce(this._$AH)?this._$AA.nextSibling.data=n:this.T(he.createTextNode(n)),this._$AH=n}$(n){let{values:t,_$litType$:r}=n,a=typeof r=="number"?this._$AC(n):(r.el===void 0&&(r.el=Ne.createElement(fn(r.h,r.h[0]),this.options)),r);if(this._$AH?._$AD===a)this._$AH.p(t);else{let o=new dt(a,this),i=o.u(this.options);o.p(t),this.T(i),this._$AH=o}}_$AC(n){let t=un.get(n.strings);return t===void 0&&un.set(n.strings,t=new Ne(n)),t}k(n){gt(this._$AH)||(this._$AH=[],this._$AR());let t=this._$AH,r,a=0;for(let o of n)a===t.length?t.push(r=new e(this.O(Ae()),this.O(Ae()),this,this.options)):r=t[a],r._$AI(o),a++;a<t.length&&(this._$AR(r&&r._$AB.nextSibling,a),t.length=a)}_$AR(n=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);n!==this._$AB;){let r=an(n).nextSibling;an(n).remove(),n=r}}setConnected(n){this._$AM===void 0&&(this._$Cv=n,this._$AP?.(n))}},_e=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(n,t,r,a,o){this.type=1,this._$AH=h,this._$AN=void 0,this.element=n,this.name=t,this._$AM=a,this.options=o,r.length>2||r[0]!==""||r[1]!==""?(this._$AH=Array(r.length-1).fill(new String),this.strings=r):this._$AH=h}_$AI(n,t=this,r,a){let o=this.strings,i=!1;if(o===void 0)n=ve(this,n,t,0),i=!Ce(n)||n!==this._$AH&&n!==me,i&&(this._$AH=n);else{let s=n,l,c;for(n=o[0],l=0;l<o.length-1;l++)c=ve(this,s[r+l],t,l),c===me&&(c=this._$AH[l]),i||=!Ce(c)||c!==this._$AH[l],c===h?n=h:n!==h&&(n+=(c??"")+o[l+1]),this._$AH[l]=c}i&&!a&&this.j(n)}j(n){n===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,n??"")}},ut=class extends _e{constructor(){super(...arguments),this.type=3}j(n){this.element[this.name]=n===h?void 0:n}},pt=class extends _e{constructor(){super(...arguments),this.type=4}j(n){this.element.toggleAttribute(this.name,!!n&&n!==h)}},ht=class extends _e{constructor(n,t,r,a,o){super(n,t,r,a,o),this.type=5}_$AI(n,t=this){if((n=ve(this,n,t,0)??h)===me)return;let r=this._$AH,a=n===h&&r!==h||n.capture!==r.capture||n.once!==r.once||n.passive!==r.passive,o=n!==h&&(r===h||a);a&&this.element.removeEventListener(this.name,this,r),o&&this.element.addEventListener(this.name,this,n),this._$AH=n}handleEvent(n){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,n):this._$AH.handleEvent(n)}},mt=class{constructor(n,t,r){this.element=n,this.type=6,this._$AN=void 0,this._$AM=t,this.options=r}get _$AU(){return this._$AM._$AU}_$AI(n){ve(this,n)}};var Br=ft.litHtmlPolyfillSupport;Br?.(Ne,Ie),(ft.litHtmlVersions??=[]).push("3.3.3");var gn=(e,n,t)=>{let r=t?.renderBefore??n,a=r._$litPart$;if(a===void 0){let o=t?.renderBefore??null;r._$litPart$=a=new Ie(n.insertBefore(Ae(),o),o,void 0,t??{})}return a._$AI(e),a};var vt=globalThis,se=class extends te{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let n=super.createRenderRoot();return this.renderOptions.renderBefore??=n.firstChild,n}update(n){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(n),this._$Do=gn(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return me}};se._$litElement$=!0,se.finalized=!0,vt.litElementHydrateSupport?.({LitElement:se});var jr=vt.litElementPolyfillSupport;jr?.({LitElement:se});(vt.litElementVersions??=[]).push("4.2.2");var bn=e=>(n,t)=>{t!==void 0?t.addInitializer(()=>{customElements.define(e,n)}):customElements.define(e,n)};var zr={attribute:!0,type:String,converter:Te,reflect:!1,hasChanged:qe},Yr=(e=zr,n,t)=>{let{kind:r,metadata:a}=t,o=globalThis.litPropertyMetadata.get(a);if(o===void 0&&globalThis.litPropertyMetadata.set(a,o=new Map),r==="setter"&&((e=Object.create(e)).wrapped=!0),o.set(t.name,e),r==="accessor"){let{name:i}=t;return{set(s){let l=n.get.call(this);n.set.call(this,s),this.requestUpdate(i,l,e,!0,s)},init(s){return s!==void 0&&this.C(i,void 0,e,s),s}}}if(r==="setter"){let{name:i}=t;return function(s){let l=this[i];n.call(this,s),this.requestUpdate(i,l,e,!0,s)}}throw Error("Unsupported decorator location: "+r)};function Qe(e){return(n,t)=>typeof t=="object"?Yr(e,n,t):((r,a,o)=>{let i=a.hasOwnProperty(o);return a.constructor.createProperty(o,r),i?Object.getOwnPropertyDescriptor(a,o):void 0})(e,n,t)}function V(e){return Qe({...e,state:!0,attribute:!1})}var _t="Energy Actions";var qr=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Xr=/DEFERRED/i,Qr=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function Ze(e){let{active:n,armed:t,operationInProgress:r,statusText:a}=e;return n===null||t===null||r===null?"unavailable":a&&qr.test(a)?"recovery_attention":a&&Xr.test(a)?"deferred":a&&Qr.test(a)?"busy":n?"active":r?"busy":t?"armed":"ready"}function vn(e){return e==="armed"}function wt(e){return e!=="busy"&&e!=="unavailable"}function _n(e){return e==="ready"||e==="armed"}var Jr={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function wn(e){return Jr[e]}var Zr=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,ea=/DEFERRED/i,ta=/^(RESTORING|STARTING)/i;function et(e){let{active:n,armed:t,operationInProgress:r,snapshotValid:a,statusText:o}=e;return n===null||t===null||r===null||a===null?"unavailable":o&&Zr.test(o)?"recovery_attention":o&&ea.test(o)?"deferred":o&&ta.test(o)?"busy":n?"active":r?"busy":a?"deferred":t?"armed":"ready"}function xn(e){return e==="armed"}function tt(e){return e!=="busy"&&e!=="unavailable"}function yn(e){return e==="ready"||e==="armed"}var na={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function ra(e){return na[e]}function xt(e,n){return e==="ready"&&n===!0?"scheduled":e}function yt(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":ra(e)}var aa=/target (\d+)\s*W export/i,oa=/Stop SOC (\d+)\s*%/i;function Sn(e,n){if(e!==null&&Number.isFinite(e))return e;let t=n?aa.exec(n):null;return t?Number(t[1]):null}function En(e,n){if(e!==null&&Number.isFinite(e))return e;let t=n?oa.exec(n):null;return t?Number(t[1]):null}var ia=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function kn(e,n){return n===!0&&!!e&&ia.test(e)}var sa=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,la=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,ca=/OPERATOR DECISION REQUIRED/i,da=/press End Free Power|retry(?:ing)? restore/i,ua=/\bRECOVERY REQUIRED\b/i,pa=/snapshot retained/i,ha=/RESTORE BLOCKED/i;function Mn(e){let n=e.statusText??"",t=e.snapshotValid;return sa.test(n)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:la.test(n)&&t===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:ca.test(n)&&da.test(n)&&t===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:ua.test(n)&&t===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:pa.test(n)&&t===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:ha.test(n)?t===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:t===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var ma=new Set(["active","busy","recovery_attention","deferred"]);function fa(e){return e!==null&&ma.has(e)}function Oe(e,n){return(e==="ready"||e==="armed")&&fa(n)}function $e(e,n){return e&&!n}function St(e,n){switch(n){case"busy":return`${e} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${e} requires recovery before this can be used.`;default:return`${e} currently owns inverter control.`}}var Rn=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function Pn(e){let n=Rn.indexOf(e);return n<0?Rn.length:n}function Tn(e,n){return e!=="unavailable"||n!=="unavailable"}function Et(e,n){return Pn(n)<Pn(e)?"dump_to_grid":"free_power"}function Dn(e){switch(e){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function An(e){switch(e){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function Cn(e){return e==="dump_to_grid"?"Dump to Grid":"Free Power"}function Nn(e,n,t){let r=t?.trim()??"";return r?`${e}: ${n} - ${r}`:`${e}: ${n}`}function kt(e){return e.armed===!0?"armed":"hidden"}function Mt(e){return!!e&&/^REJECTED/i.test(e.trim())}function Rt(e){return!!e&&/^BLOCKED/i.test(e.trim())}function Pt(e){return e===!0}function Tt(e,n){return e==="ready"&&n==="armed"?"scheduled":e}function Dt(e){return{domain:"input_boolean",service:"turn_on",data:{entity_id:e}}}function At(e){return{domain:"script",service:"turn_on",data:{entity_id:e}}}function In(e,n){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:e,datetime:n}}}function Ct(e,n){return{domain:"input_number",service:"set_value",data:{entity_id:e,value:n}}}function On(e,n){return n===null||!Number.isFinite(n)||n<=0?e:Math.min(e,n)}var ga=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function fe(e){if(!e)return null;let n=ga.exec(e.trim());if(!n)return null;let[,t,r,a,o,i,s]=n,l=new Date(Number(t),Number(r)-1,Number(a),Number(o),Number(i),Number(s));return Number.isNaN(l.getTime())?null:l}function $n(e){let n=t=>t.toString().padStart(2,"0");return`${e.getFullYear()}-${n(e.getMonth()+1)}-${n(e.getDate())} ${n(e.getHours())}:${n(e.getMinutes())}:${n(e.getSeconds())}`}var ba=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],va=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Nt(e){let n=ba[e.getDay()],t=e.getDate(),r=va[e.getMonth()],a=e.getHours().toString().padStart(2,"0"),o=e.getMinutes().toString().padStart(2,"0");return`${n} ${t} ${r} \u2022 ${a}:${o}`}function Le(e,n){let t=e-n;if(t<=0)return null;let r=Math.floor(t/1e3),a=Math.floor(r/3600),o=Math.floor(r%3600/60),i=r%60;return a>0?`${a}h ${o}m`:o>0?`${o}m ${i.toString().padStart(2,"0")}s`:`${i}s`}function ne(e){return e==null||Number.isNaN(e)?"--":Math.abs(e)>=1e3?`${(e/1e3).toFixed(2)} kW`:`${e.toFixed(0)} W`}function ge(e){if(e==null||Number.isNaN(e))return"--";let n=Math.round(e);if(n<60)return`${n} min`;let t=Math.floor(n/60),r=n%60;return r===0?`${t}h`:`${t}h ${r}m`}function we(e){return e==null||Number.isNaN(e)?"--":`${Math.round(e)}%`}function S(e){if(e==null||e==="unknown"||e==="unavailable"||e==="")return null;let n=Number(e);return Number.isFinite(n)?n:null}function y(e){return e==null||e==="unknown"||e==="unavailable"||e===""?null:e==="on"}function re(e){return(Math.round(e)%1440+1440)%1440}function K(e,n){return re(n-e)}function B(e){let n=re(e),t=r=>(r<10?"0":"")+r;return t(Math.floor(n/60))+":"+t(n%60)}function We(e){return Number.isInteger(e)&&e>=0&&e<1440&&e%5===0}var Ln=Object.freeze({changeAtMin:0,deltaMin:0});function Wn(e){return e.deltaMin!==0}function Fe(e,n,t){if(t.deltaMin===0||n<=0)return n;let r=K(e,t.changeAtMin);return r>0&&r<n?n-t.deltaMin:n}function Fn(e,n){for(let t=0;t<=n;t+=5)if(re(e+t)<180)return!0;return!1}var qi=Object.freeze({owner:3,intelligence:2,native:1}),It=["MISMATCH","PROPOSED","ARMED","EXECUTING","APPLIED_VERIFIED"],m=Object.freeze({slots:6,minSlotMin:5,bufferMin:0,bufferMax:120,stopSocMin:10,stopSocMax:90,chargeTargetMin:20,chargeTargetMax:100,chargePowerMin:500,chargePowerMax:8e3,exportPowerMin:500,exportPowerMax:3e3,exportDurationMin:10,exportDurationMax:240,reserveMin:10,reserveMax:100}),J={"charge.targetSoc":{label:"Charge target",unit:"%",min:m.chargeTargetMin,max:m.chargeTargetMax,step:1,views:["charge-card","tou-table","tomorrow-plan"]},"charge.bufferMin":{label:"Finish before the window ends",unit:"min",min:m.bufferMin,max:m.bufferMax,step:5,views:["charge-card","tomorrow-plan"]},"charge.powerW":{label:"Maximum charge power",unit:"W",min:m.chargePowerMin,max:m.chargePowerMax,step:100,views:["charge-card","tou-table","tomorrow-plan"]},"charge.windowStartMin":{label:"Charge window start",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"charge.windowEndMin":{label:"Charge window end",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"export.stopSoc":{label:"Export down to (Stop SOC)",unit:"%",min:m.stopSocMin,max:m.stopSocMax,step:1,views:["export-card","tou-table","tomorrow-plan","reserve-summary"]},"export.powerW":{label:"Export power",unit:"W",min:m.exportPowerMin,max:m.exportPowerMax,step:100,views:["export-card","tou-table","tomorrow-plan"]},"export.startMin":{label:"Export start",unit:"",min:0,max:1439,step:5,time:!0,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"export.durationMin":{label:"Export duration",unit:"min",min:m.exportDurationMin,max:m.exportDurationMax,step:5,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"reserve.backupPct":{label:"Backup reserve (enforced)",unit:"%",min:m.reserveMin,max:m.reserveMax,step:1,views:["charge-card","export-card","reserve-summary","tomorrow-plan"]},"reserve.planningPct":{label:"Planning reserve (advice)",unit:"%",min:m.reserveMin,max:m.reserveMax,step:1,views:["reserve-summary","tomorrow-plan"]}},xe=Object.freeze(Object.keys(J));function Ve(e,n){if(!Object.prototype.hasOwnProperty.call(J,e))return{ok:!1,error:"Unknown setting."};let t=J[e];if(typeof n!="number"||!Number.isFinite(n))return{ok:!1,error:t.label+" needs a number."};if(t.time)return We(n)?{ok:!0,value:n}:{ok:!1,error:t.label+" must be a time on the 5-minute grid."};if(n<t.min)return e==="export.stopSoc"?{ok:!1,error:"Stop SOC below "+t.min+" % is not available and is refused, not clamped."}:{ok:!1,error:t.label+" must be at least "+t.min+(t.unit?" "+t.unit:"")+"."};if(n>t.max)return e==="export.stopSoc"?{ok:!1,error:"Stop SOC above "+t.max+" % is not available and is refused, not clamped."}:{ok:!1,error:t.label+" can be at most "+t.max+(t.unit?" "+t.unit:"")+"."};let r=(n-t.min)/t.step;return Math.abs(r-Math.round(r))>1e-9?{ok:!1,error:t.label+" moves in steps of "+t.step+(t.unit?" "+t.unit:"")+"."}:{ok:!0,value:n}}function Vn(e,n="owner"){let t={};for(let r of xe){let a=Ve(r,e[r]);if(!a.ok)throw new Error(r+": "+a.error);t[r]={value:a.value,source:n,revision:1,state:"PROPOSED",observed:null,proposal:null,external:null}}return{revision:1,fields:t}}function _a(e){return JSON.parse(JSON.stringify(e))}function L(e,n){return{ok:!1,settings:e,error:n,updates:[]}}function ae(e,n,t){let r=t==="proposal"?n.proposal?.value:t==="external"?n.external?.value:n.value;return r===void 0?[]:J[e].views.map(o=>({view:o,path:e,kind:t,value:r,state:n.state,preview:n.state!=="APPLIED_VERIFIED"}))}function nt(e,n){if(!Object.prototype.hasOwnProperty.call(J,n.path))return L(e,"Unknown setting.");let t=_a(e),r=t.fields[n.path],a=()=>++t.revision;switch(n.type){case"edit":{if(n.expectedRevision!==void 0&&n.expectedRevision!==e.revision)return L(e,"The settings changed (revision "+e.revision+") since this edit was prepared; reload and review.");let o=Ve(n.path,n.value);return o.ok?r.state==="EXECUTING"?L(e,"An apply is in progress for this setting; it cannot be edited until it ends."):r.external?L(e,"The native side was changed outside ECCO; resolve that first (adopt it or keep the intended value)."):n.source==="intelligence"?o.value===r.value?{ok:!0,settings:e,updates:[]}:(r.proposal={value:o.value,revision:a()},{ok:!0,settings:t,updates:ae(n.path,r,"proposal")}):o.value===r.value&&r.source==="owner"?{ok:!0,settings:e,updates:[]}:(r.value=o.value,r.source="owner",r.revision=a(),r.state=r.observed===o.value?"APPLIED_VERIFIED":"PROPOSED",r.proposal&&r.proposal.value===o.value&&(r.proposal=null),{ok:!0,settings:t,updates:ae(n.path,r,"value")}):L(e,o.error)}case"adopt-proposal":return r.proposal?r.state==="EXECUTING"?L(e,"An apply is in progress for this setting."):r.external?L(e,"Resolve the external native change first."):(r.value=r.proposal.value,r.source="intelligence",r.proposal=null,r.revision=a(),r.state=r.observed===r.value?"APPLIED_VERIFIED":"PROPOSED",{ok:!0,settings:t,updates:ae(n.path,r,"value")}):L(e,"There is no Intelligence proposal to adopt.");case"dismiss-proposal":return r.proposal?(r.proposal=null,a(),{ok:!0,settings:t,updates:[]}):L(e,"There is no Intelligence proposal to dismiss.");case"arm":return r.external?L(e,"Resolve the external native change before arming."):r.state!=="PROPOSED"&&r.state!=="MISMATCH"?L(e,"Only a proposed or mismatched setting can be armed (it is "+r.state+")."):(r.state="ARMED",a(),{ok:!0,settings:t,updates:ae(n.path,r,"value")});case"disarm":return r.state!=="ARMED"?L(e,"Only an armed setting can be disarmed."):(r.state="PROPOSED",a(),{ok:!0,settings:t,updates:ae(n.path,r,"value")});case"begin":return r.external?L(e,"Resolve the external native change before executing."):r.state!=="ARMED"?L(e,"Only an armed setting can start executing."):(r.state="EXECUTING",a(),{ok:!0,settings:t,updates:ae(n.path,r,"value")});case"fail":return r.state!=="EXECUTING"?L(e,"Only an executing setting can fail."):(r.state="MISMATCH",a(),{ok:!0,settings:t,updates:ae(n.path,r,"value")});case"readback":{let o=r.observed,i=n.observed;return i!==null&&!Number.isFinite(i)?L(e,"A read-back must be a finite number or null."):i===o?{ok:!0,settings:e,updates:[]}:(r.observed=i,i===null?r.state==="APPLIED_VERIFIED"&&(r.state="PROPOSED"):i===r.value?(r.state="APPLIED_VERIFIED",r.external=null):r.state==="EXECUTING"?r.state="MISMATCH":(r.state==="APPLIED_VERIFIED"||r.state==="MISMATCH"||o!==null&&o!==i)&&(r.external={value:i,revision:t.revision+1},r.state==="APPLIED_VERIFIED"&&(r.state="MISMATCH")),a(),{ok:!0,settings:t,updates:ae(n.path,r,r.external?"external":"value")})}case"resolve-external":{if(!r.external)return L(e,"There is no external change to resolve.");if(n.choice==="adopt-native"){let o=Ve(n.path,r.external.value);if(!o.ok)return L(e,"The native value is outside what ECCO accepts ("+o.error+") and cannot be adopted; keep the intended value.");r.value=r.external.value,r.source="native",r.observed=r.external.value,r.state="APPLIED_VERIFIED"}else r.state="PROPOSED";return r.external=null,r.revision=a(),{ok:!0,settings:t,updates:ae(n.path,r,"value")}}default:return L(e,"Unknown action.")}}function Un(e,n){let t=It.length-1;for(let r of n)t=Math.min(t,It.indexOf(e.fields[r].state));return It[t]??"MISMATCH"}function ye(e){if(!Array.isArray(e)||e.length!==m.slots)return{ok:!1,why:"the table does not have six slots"};for(let t of e){if(!t||!We(t.startMin))return{ok:!1,why:"a slot start is unreadable or off the 5-minute grid"};if(t.source!=="Grid"&&t.source!=="None")return{ok:!1,why:"a slot has an unknown charge source"};if(!Number.isFinite(t.powerW)||!Number.isFinite(t.targetSoc))return{ok:!1,why:"a slot power or target SOC is unreadable"}}let n=0;for(let t=0;t<m.slots;t++){let r=e[t].startMin,a=e[(t+1)%m.slots].startMin,o=K(r,a);if(o<m.minSlotMin)return{ok:!1,why:"slot "+(t+1)+" is shorter than 5 minutes"};n+=o}return n!==1440?{ok:!1,why:"the six starts are not one 24-hour cycle in slot order"}:{ok:!0}}function Ot(e,n){return e.startMin===n.startMin&&e.powerW===n.powerW&&e.targetSoc===n.targetSoc&&e.source===n.source}function Hn(e,n){return e.length===n.length&&e.every((t,r)=>Ot(t,n[r]))}var Ue=1440/5,Gn=e=>e.source+"|"+e.powerW+"|"+e.targetSoc;function wa(e){let n=[];for(let t=0;t<Ue;t++){let r=t*5,a=e[0];for(let o=0;o<e.length;o++){let i=e[o],s=e[(o+1)%e.length];if(K(i.startMin,r)<K(i.startMin,s.startMin)){a=i;break}}n.push({powerW:a.powerW,targetSoc:a.targetSoc,source:a.source,from:null})}return n}function q(e,n,t,r={}){let a=e.baseline.map(o=>({...o}));return{status:n,reasons:t,slots:a,slotReports:jn(a,a.map(()=>"native-fallback"),e.observed??null),fallback:!0,edits:[],intervals:[],refused:[],slotsNeeded:0,deferredToAfterClockChange:!1,...r}}function jn(e,n,t){return e.map((r,a)=>{let o=t&&t.length===e.length?t[a]:null,i=o===null?"PROPOSED":Ot(o,r)?"APPLIED_VERIFIED":"MISMATCH";return{index:a+1,intended:{...r},origin:n[a],observed:o?{...o}:null,state:i}})}function Kn(e,n){let t=[];return n.forEach((r,a)=>{let o=e&&e.length===n.length?e[a]:null,i=["startMin","powerW","targetSoc","source"];for(let s of i)(o===null||o[s]!==r[s])&&t.push({slot:a+1,field:s,from:o===null?null:o[s],to:r[s]})}),t}function xa(e){return{powerW:e.powerW,targetSoc:e.targetSoc,source:e.action==="charge"?"Grid":"None",from:e.action}}function ya(e){if(e.action!=="charge"&&e.action!=="export")return"unknown action";if(!We(e.startMin))return e.action+" start is not on the 5-minute grid";if(!Number.isInteger(e.durationMin)||e.durationMin<m.minSlotMin||e.durationMin%5!==0)return e.action+" duration must be a multiple of 5 minutes, at least 5";if(e.durationMin>=1440)return e.action+" cannot cover the whole day";if(e.action==="export"){if(!Number.isInteger(e.targetSoc)||e.targetSoc<m.stopSocMin||e.targetSoc>m.stopSocMax)return"export Stop SOC must be "+m.stopSocMin+"-"+m.stopSocMax+" %";if(e.powerW<m.exportPowerMin||e.powerW>m.exportPowerMax)return"export power is outside "+m.exportPowerMin+"-"+m.exportPowerMax+" W"}else{if(!Number.isFinite(e.targetSoc)||e.targetSoc<m.chargeTargetMin||e.targetSoc>m.chargeTargetMax)return"charge target SOC is outside "+m.chargeTargetMin+"-"+m.chargeTargetMax+" %";if(e.powerW<m.chargePowerMin||e.powerW>m.chargePowerMax)return"charge power is outside "+m.chargePowerMin+"-"+m.chargePowerMax+" W"}return null}function Sa(e,n){let t=0;for(let r=0;r<e.length;r++)Ot(e[r],n[r])||t++;return t}function zn(e){let n=e.day??Ln,t=Math.max(5,e.handoverGapMin??5);if(e.transactionOwner)return q(e,"REFUSED",["Single writer: "+e.transactionOwner+" owns the inverter right now; nothing is compiled until it ends and its restore is verified."]);let r=ye(e.baseline);if(!r.ok)return q(e,"REFUSED",["The native baseline is not a valid six-slot day: "+r.why+"."]);if(e.observed){let f=ye(e.observed);if(!f.ok)return q(e,"CONFLICT",["The observed inverter table is not a valid six-slot day: "+f.why+"; reconcile before planning."]);let w=e.lastApplied??e.baseline;if(!Hn(e.observed,w)){let D=Kn(w,e.observed);return q(e,"CONFLICT",["The inverter table differs from "+(e.lastApplied?"what ECCO last applied":"the owner's baseline")+" ("+D.length+" field(s), first: slot "+D[0].slot+" "+D[0].field+"). It looks edited outside ECCO; review and adopt it or restore before anything is compiled."])}}let a=[],o=e.intervals.filter(f=>f.action==="export"&&e.controlLocked!==!1?(a.push({action:"export",reason:"Control is locked (grid-loss lock): every export start is refused."}),!1):!0);for(let f of o){let w=ya(f);if(w)return q(e,"REFUSED",["Invalid derived interval: "+w+"."],{refused:a})}if(o.filter(f=>f.action==="charge").length>1||o.filter(f=>f.action==="export").length>1)return q(e,"REFUSED",["Only one charge and one export interval can be derived per cycle."],{refused:a});let i=o.find(f=>f.action==="charge"),s=o.find(f=>f.action==="export");if(i&&s){let f=K(s.startMin+s.durationMin,i.startMin),w=K(i.startMin+i.durationMin,s.startMin);if(K(i.startMin,s.startMin)<i.durationMin||K(s.startMin,i.startMin)<s.durationMin)return q(e,"REFUSED",["The export would overlap the charge window; the firmware refuses an export that touches a charge slot."],{refused:a});if(f<t||w<t)return q(e,"REFUSED",["Fewer than "+t+" minutes between the export and the charge window; time is needed to restore and verify."],{refused:a})}let l=!1;if(Wn(n)){for(let f of o){let w=re(f.startMin+f.durationMin);(f.action==="export"?Fn(f.startMin,f.durationMin):f.startMin<180||w<180)&&(l=!0)}if(l)return q(e,"REFUSED",["Clock-change night: derived changes that start, end or run between 00:00 and 03:00 wait until the night is over; the native table keeps running unchanged."],{refused:a,deferredToAfterClockChange:!0})}let c=wa(e.baseline);for(let f of o){let w=xa(f);for(let D=0;D<f.durationMin;D+=5)c[(f.startMin+D)/5%Ue]={...w}}let d=[];for(let f=0;f<Ue;f++){let w=c[(f+Ue-1)%Ue];Gn(w)!==Gn(c[f])&&d.push(f*5)}d.length===0&&d.push(e.baseline[0].startMin);let p=d.length;if(p>m.slots)return q(e,"INFEASIBLE",["Six native slots are not enough: this plan needs "+p+" distinct slots (changes at "+d.map(f=>B(f)).join(", ")+") and the inverter has exactly "+m.slots+". Nothing is truncated; the native table stays as it is."],{refused:a,slotsNeeded:p,intervals:Bn(o,n)});let v=new Set(d);for(let f of e.baseline){if(d.length>=m.slots)break;v.has(f.startMin)||(d.push(f.startMin),v.add(f.startMin))}for(d.sort((f,w)=>f-w);d.length<m.slots;){let f=-1,w=0;for(let $=0;$<d.length;$++){let T=K(d[$],d[($+1)%d.length])||1440;T>w&&(w=T,f=$)}let D=re(d[f]+Math.floor(w/2/5)*5);d.push(D),d.sort(($,T)=>$-T)}let b=f=>c[f/5],g=d.map(f=>{let w=b(f);return{startMin:f,powerW:w.powerW,targetSoc:w.targetSoc,source:w.source}}),E=(f,w)=>{let D=K(f,w)||1440;for(let $=0;$<D;$+=5){let T=b(re(f+$)).from;if(T)return T==="charge"?"derived:charge":"derived:export"}return"native-fallback"},_=0,R=1/0;for(let f=0;f<m.slots;f++){let w=g.map(($,T)=>g[(T+f)%m.slots]),D=Sa(w,e.baseline);D<R&&(R=D,_=f)}let x=g.map((f,w)=>({...g[(w+_)%m.slots]})),C=g.map((f,w)=>{let D=(w+_)%m.slots;return E(g[D].startMin,g[(D+1)%m.slots].startMin)}),P=ye(x);if(!P.ok)return q(e,"REFUSED",["Internal check failed ("+P.why+"); the native table stays as it is."],{refused:a});let W=Hn(x,e.baseline);return{status:"OK",reasons:a.map(f=>f.reason),slots:x,slotReports:jn(x,C,e.observed??null),fallback:W,edits:Kn(e.observed??e.baseline,x),intervals:Bn(o,n),refused:a,slotsNeeded:p,deferredToAfterClockChange:!1}}function Bn(e,n){return e.map(t=>({action:t.action,startMin:t.startMin,wallMin:t.durationMin,elapsedMin:Fe(t.startMin,t.durationMin,n)}))}var le=["hold_battery","skip_tonight","prepare_power_cut"];function Yn(e,n,t,r){if(!le.includes(e))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(!Number.isFinite(n))return{ok:!1,error:"The current time is unknown; an override cannot be started without it.",code:"TIME_UNKNOWN"};let a=t??r.defaultExpiryMin[e];if(typeof a!="number"||!Number.isFinite(a))return{ok:!1,error:"An override needs an expiry; there is no open-ended override.",code:"EXPIRY_MISSING"};if(a<r.minExpiryMin)return{ok:!1,error:"The expiry must be at least "+r.minExpiryMin+" minutes.",code:"EXPIRY_BELOW_MIN"};let o=r.maxExpiryMin[e];if(a>o)return{ok:!1,error:"The expiry can be at most "+o+" minutes for this override.",code:"EXPIRY_ABOVE_CAP"};let i={kind:e,startedAtMin:n,expiresAtMin:n+a};if(e==="prepare_power_cut"){let s=r.powerCutReservePct;if(!Number.isFinite(s)||s<m.reserveMin||s>m.reserveMax)return{ok:!1,error:"The power-cut reserve must be "+m.reserveMin+"-"+m.reserveMax+" %.",code:"POWER_CUT_RESERVE_RANGE"};i.reservePct=s}return{ok:!0,override:i}}var He={min_expiry:{min:5,max:60,step:5,unit:"min"},hold_default:{min:5,max:4320,step:5,unit:"min"},hold_cap:{min:5,max:4320,step:5,unit:"min"},skip_until:{min:180,max:1435,step:5,unit:"minute of day"},skip_cap:{min:5,max:2160,step:5,unit:"min"},cut_default:{min:5,max:10080,step:5,unit:"min"},cut_cap:{min:5,max:10080,step:5,unit:"min"},cut_reserve:{min:10,max:100,step:1,unit:"%"},revision:{min:0,max:1e9,step:1,unit:""}},ce=Object.freeze({hold_battery:He.hold_cap.max,skip_tonight:He.skip_cap.max,prepare_power_cut:He.cut_cap.max}),X=Object.freeze({hold_battery:"Hold battery",skip_tonight:"Skip tonight",prepare_power_cut:"Prepare for power cut"}),Ea=[{key:"minExpiryMin",bound:"min_expiry",label:"Shortest allowed override"},{key:"holdDefaultMin",bound:"hold_default",label:"Hold battery default"},{key:"holdCapMin",bound:"hold_cap",label:"Hold battery maximum"},{key:"skipUntilMin",bound:"skip_until",label:"Skip tonight ends at"},{key:"skipCapMin",bound:"skip_cap",label:"Skip tonight maximum"},{key:"cutDefaultMin",bound:"cut_default",label:"Prepare for power cut default"},{key:"cutCapMin",bound:"cut_cap",label:"Prepare for power cut maximum"},{key:"cutReservePct",bound:"cut_reserve",label:"Power-cut reserve"}];function Z(e){if(typeof e!="number"||!Number.isFinite(e)||e<0)return"unknown";let n=Math.round(e);if(n<60)return n+" min";let t=Math.floor(n/1440),r=Math.floor((n-t*1440)/60),a=n%60,o=[];return t>0&&o.push(t+(t===1?" day":" days")),r>0&&o.push(r+" h"),a>0&&o.push(a+" min"),o.join(" ")}function qn(e,n){if(e.bound==="skip_until")return B(n);let t=He[e.bound];return t.unit==="min"?Z(n):n+" "+t.unit}function ka(e,n,t){let r=He[e.bound];return typeof n!="number"||!Number.isFinite(n)?(t.push(e.label+" is not set or cannot be read."),null):Number.isInteger(n)?n<r.min?(t.push(e.label+" must be at least "+qn(e,r.min)+"."),null):n>r.max?(t.push(e.label+" can be at most "+qn(e,r.max)+"."),null):(n-r.min)%r.step!==0?(t.push(e.label+" moves in steps of "+r.step+(r.unit==="%"?" %":" min")+"."),null):n:(t.push(e.label+" must be a whole number."),null)}function $t(e,n={}){if(e==null||typeof e!="object")return{ok:!1,reasons:["No override limits are configured, so no override can be started."],codes:["POLICY_UNCONFIRMED"]};let t=[],r=[];e.confirmed!==!0&&t.push("The owner has not confirmed the override limits (the switch is off or cannot be read), so no override can be started.");let a={};for(let d of Ea){let p=ka(d,e[d.key],t);p!==null&&(a[d.key]=p)}let o=a.minExpiryMin,i=(d,p,v)=>{o!==void 0&&p!==void 0&&p<o&&t.push(d+" default is shorter than the shortest allowed override."),p!==void 0&&v!==void 0&&p>v&&t.push(d+" default is longer than its maximum.")};i("Hold battery",a.holdDefaultMin,a.holdCapMin),i("Prepare for power cut",a.cutDefaultMin,a.cutCapMin),o!==void 0&&a.skipCapMin!==void 0&&a.skipCapMin<o&&t.push("Skip tonight maximum is shorter than the shortest allowed override.");let s=a.cutReservePct;s!==void 0&&(s<m.reserveMin||s>m.reserveMax)&&t.push("The power-cut reserve must be "+m.reserveMin+"-"+m.reserveMax+" %.");let l=n.currentReservePct;if(typeof l=="number"&&Number.isFinite(l)?s!==void 0&&s<l&&t.push("The power-cut reserve ("+s+" %) is below the current backup reserve ("+l+" %); it would not raise anything."):r.push("The current backup reserve is not known, so the power-cut reserve cannot be compared with it here. An override can only raise a reserve."),t.length>0){let d=[];return e.confirmed!==!0&&d.push("POLICY_UNCONFIRMED"),t.length>d.length&&d.push("POLICY_INVALID"),{ok:!1,reasons:t,codes:d}}return{ok:!0,config:Object.freeze({minExpiryMin:a.minExpiryMin,holdDefaultMin:a.holdDefaultMin,holdCapMin:a.holdCapMin,skipUntilMin:a.skipUntilMin,skipCapMin:a.skipCapMin,cutDefaultMin:a.cutDefaultMin,cutCapMin:a.cutCapMin,cutReservePct:a.cutReservePct}),warnings:r}}function Ma(e){return!!e&&(e.deltaMin===0||e.deltaMin===60||e.deltaMin===-60)&&Number.isInteger(e.changeAtMin)&&e.changeAtMin>=0&&e.changeAtMin<1440}function Xn(e,n,t){if(!Number.isInteger(e)||e<0||e>=1440)return{ok:!1,error:"The local time is unknown."};if(!Number.isInteger(n)||n<0||n>=1440)return{ok:!1,error:"The end time is not a time of day."};if(!Ma(t))return{ok:!1,error:"The clock-change information is not valid."};let r=K(e,n),a=r===0?1440:r,o=Fe(e,a,t);return o>0?{ok:!0,wallMin:a,expiryMin:o}:{ok:!1,error:"The end time is not in the future."}}function Ra(e,n){let t=NaN;if(n){let r=Xn(n.nowWallMin,e.skipUntilMin,n.day);r.ok&&(t=r.expiryMin)}return{minExpiryMin:e.minExpiryMin,defaultExpiryMin:{hold_battery:e.holdDefaultMin,skip_tonight:t,prepare_power_cut:e.cutDefaultMin},maxExpiryMin:{hold_battery:e.holdCapMin,skip_tonight:e.skipCapMin,prepare_power_cut:e.cutCapMin},powerCutReservePct:e.cutReservePct}}var Pa=[30,60,120,240,480,720,1440,2880,4320,10080];function Qn(e,n,t){let r=e==="hold_battery"?n.holdCapMin:e==="skip_tonight"?n.skipCapMin:n.cutCapMin,a=e==="hold_battery"?n.holdDefaultMin:e==="prepare_power_cut"?n.cutDefaultMin:null,o=new Set;for(let s of Pa)s>=n.minExpiryMin&&s<=r&&o.add(s);a!==null&&o.add(a),o.add(r);let i=[...o].filter(s=>s>=n.minExpiryMin&&s<=r).map(s=>({id:"d"+s,label:Z(s),expiryMin:s,untilMin:null,isDefault:a===s}));if((e==="hold_battery"||e==="skip_tonight")&&t){let s=Xn(t.nowWallMin,n.skipUntilMin,t.day);s.ok&&s.expiryMin>=n.minExpiryMin&&s.expiryMin<=r&&i.push({id:"until",label:"until "+B(n.skipUntilMin),expiryMin:s.expiryMin,untilMin:n.skipUntilMin,isDefault:e==="skip_tonight"})}return i.sort((s,l)=>s.expiryMin-l.expiryMin||s.id.localeCompare(l.id))}function Jn(e,n,t,r,a){if(!r||r.ok!==!0||!r.config)return{ok:!1,error:"The override limits are not valid, so no override can be started."+(r&&r.ok===!1&&r.reasons.length?" "+r.reasons.join(" "):""),code:r&&r.ok===!1&&r.codes&&r.codes[0]||"POLICY_INVALID"};let o=r.config;if(!le.includes(e))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(t!=null&&(typeof t!="number"||!Number.isInteger(t)))return{ok:!1,error:"The expiry must be a whole number of minutes.",code:"EXPIRY_NOT_WHOLE"};if(e==="prepare_power_cut"){let l=a.currentReservePct;if(typeof l!="number"||!Number.isFinite(l))return{ok:!1,error:"The current backup reserve is not known, so it cannot be shown that the power-cut reserve raises it.",code:"RESERVE_UNKNOWN"};if(o.cutReservePct<l)return{ok:!1,error:"The power-cut reserve ("+o.cutReservePct+" %) is below the current backup reserve ("+l+" %); an override never lowers a reserve.",code:"RESERVE_BELOW_CURRENT"}}let i=Yn(e,n,t,Ra(o,a.clock));if(!i.ok)return i;let s=i.override.expiresAtMin-i.override.startedAtMin;return!(s>0)||!(s<=ce[e])?{ok:!1,error:"The expiry is beyond the hard ceiling of "+Z(ce[e])+".",code:"EXPIRY_ABOVE_CEILING"}:i}var Ta=[{key:"minExpiryMin",value:15,why:"Under a quarter hour is almost certainly a mis-tap and would make the plan flicker."},{key:"holdDefaultMin",value:240,why:"Covers an evening of extra use (cooking, guests) without outliving it."},{key:"holdCapMin",value:1440,why:"A forgotten hold costs at most one night of export; two days needs a deliberate restart."},{key:"skipUntilMin",value:420,why:"Skips tonight's export and the overnight charge, then planning resumes before the morning sun."},{key:"skipCapMin",value:1440,why:"Skip is a one-night action; a day is the most it needs."},{key:"cutDefaultMin",value:1440,why:"Most warnings and outages are shorter than a day; extending is a conscious step."},{key:"cutCapMin",value:4320,why:"Matches the design example of 72 h; a raised reserve only costs forgone export."},{key:"cutReservePct",value:80,why:"Hours of essential load while still leaving room for solar; the design example."}],Zn=Object.freeze(Ta.map(e=>Object.freeze({...e})));var Da=["HIGH","MEDIUM","LOW","INSUFFICIENT"];function rt(e){return{known:!1,reason:e,state:"PROPOSED"}}function Lt(e,n){if(!e)return rt("No Intelligence advice is available.");let t=e[n];return t==null?rt("Intelligence did not provide this."):typeof t!="number"||!Number.isFinite(t)||t<0?rt("Intelligence provided a value that is not a valid amount."):{known:!0,value:t,state:"PROPOSED",origin:"intelligence",simulated:!1}}var Aa=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"];function er(e){let{advice:n,settings:t,chargePlan:r}=e,a=[],o="UNKNOWN";n&&typeof n.confidence=="string"&&Da.includes(n.confidence)&&(o=n.confidence);let i={known:o!=="UNKNOWN",level:o,state:"PROPOSED"},s,l=n?.chargeFinishMin;if(typeof l=="number"&&Number.isFinite(l)&&l>=0&&l<1440)s={known:!0,value:Math.round(l),state:"PROPOSED",origin:"intelligence",simulated:!1};else if(r&&(r.status==="OK"||r.status==="BUFFER_TOO_SMALL")&&r.finishNominalMin!==null){let b=t.fields["charge.windowStartMin"].value;s={known:!0,value:re(b+r.finishNominalMin),state:Un(t,Aa),origin:"planner",simulated:!0},r.status==="BUFFER_TOO_SMALL"&&a.push({origin:"planner",text:"Buffer too small: the stress case overruns the charge window (simulated, not measured)."})}else s=rt(r&&r.status==="NOTHING_TO_CHARGE"?"No overnight charge is expected to be needed.":"No finish time is available from advice or the planner.");let c=t.fields["reserve.backupPct"],d={known:!0,value:c.value,state:c.state,origin:"settings",simulated:!1};if(n&&Array.isArray(n.why))for(let b of n.why.slice(0,8))typeof b=="string"&&b.trim()&&a.push({origin:"advice",text:b.trim().slice(0,200)});let p=t.fields["charge.targetSoc"];a.push({origin:"settings",text:"Charge target "+p.value+" % ("+p.source+", revision "+p.revision+", "+p.state+")."});let v=t.fields["export.stopSoc"];return a.push({origin:"settings",text:"Export stops at "+v.value+" % ("+v.source+", revision "+v.revision+", "+v.state+")."}),a.push({origin:"settings",text:"Backup reserve "+c.value+" % ("+c.source+", "+c.state+")."}),i.known?o!=="HIGH"&&a.push({origin:"advice",text:"Confidence is "+o+": ECCO holds rather than acts on this forecast."}):a.push({origin:"advice",text:"Confidence is unknown, so nothing here is presented as a firm forecast."}),{importKwh:Lt(n,"expectedImportKwh"),exportKwh:Lt(n,"expectedExportKwh"),solarKwh:Lt(n,"expectedSolarKwh"),chargeFinishMin:s,reservePct:d,confidence:i,why:a}}var Ca=60,gs=Object.freeze({targetMin:10,targetMax:100,bufferMin:m.bufferMin,bufferMax:m.bufferMax,bufferStep:5,replanMin:5,replanMax:15});var Na=Object.freeze({stepW:100,minW:m.chargePowerMin,hardMaxW:m.chargePowerMax,hysteresisW:500,dwellMin:30,decreaseSlackMin:15,replanMin:10,maxChanges:6,maxSocAgeMin:15,socResolutionPct:1,chargeEff:.95,taperStartSocPct:90,taperEndFraction:.15,topHoldMin:20,demandMarginPct:20,assumedDemandW:2e3,maxHouseholdAgeMin:15,maxDecreaseStepW:m.chargePowerMax}),bs=Object.freeze({maxDecreaseStepW:1e3}),Ia=Object.freeze({fallbackPolicy:"KEEP_CURRENT",unknownDemandPolicy:"ASSUME_PROVISIONAL"}),tr={stepW:["OWNER_SET","the editor's setpoint step"],minW:["OWNER_SET","the editor's minimum charge power"],hardMaxW:["OWNER_SET","the editor's maximum charge power"],hysteresisW:["PROVISIONAL","the owner's confirmation after watching real nights"],dwellMin:["PROVISIONAL","the owner's confirmation and the actuator's settle time"],decreaseSlackMin:["PROVISIONAL","the owner's confirmation after watching real nights"],replanMin:["PROVISIONAL","the owner's confirmation and the actuator's cadence"],maxChanges:["PROVISIONAL","the write budget of a proven actuator"],maxSocAgeMin:["PROVISIONAL","the real update rate of the SOC sensor"],socResolutionPct:["PROVISIONAL","the real resolution of the SOC sensor"],chargeEff:["PROVISIONAL","the measured grid-to-battery energy ratio over several nights"],taperStartSocPct:["MEASURED_REQUIRED","the BMS taper curve measured over several full charges"],taperEndFraction:["MEASURED_REQUIRED","the BMS taper curve measured over several full charges"],topHoldMin:["MEASURED_REQUIRED","the measured time from the last taper step to the BMS finishing the top of charge"],demandMarginPct:["PROVISIONAL","the measured spread of real demand against its forecast"],assumedDemandW:["MEASURED_REQUIRED","the measured overnight household demand profile (unknown today)"],maxHouseholdAgeMin:["PROVISIONAL","the real update rate of the demand and solar sensors"],maxDecreaseStepW:["PROVISIONAL","the owner's confirmation (recommended 1000 W; off by default)"],fallbackPolicy:["PROVISIONAL","the owner's choice"],unknownDemandPolicy:["PROVISIONAL","the owner's choice"],targetSocPct:["OWNER_SET","the owner's charge target"],bufferMin:["OWNER_SET","the owner's finish-early buffer"],gridImportLimitW:["OWNER_SET","the owner's or installer's safe grid import limit (unknown means no headroom constraint)"]};function Oa(){let e={},n={...Na,...Ia,targetSocPct:"owner setting",bufferMin:Ca,gridImportLimitW:"owner setting or unknown"};for(let t of Object.keys(tr)){let r=tr[t];e[t]=Object.freeze({kind:r[0],value:n[t],replacedBy:r[1]})}return Object.freeze(e)}var vs=Oa(),_s=2*1440;var $a=Object.freeze({status:"sensor.ecco_intel_status",charge_target:"sensor.ecco_intel_charge_target",export_event:"sensor.ecco_intel_export_event",pv_tomorrow:"sensor.ecco_intel_pv_tomorrow",fresh:"binary_sensor.ecco_intel_fresh",paused:"input_boolean.ecco_intel_paused"}),La=6,Wa=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/,Fa=/^(\d{2}):(\d{2})$/,Va=/^\d{4}-\d{2}-\d{2} (\d{2}):(\d{2}):\d{2}$/;function G(e,n){if(!n)return null;let t=e[n]?.state;return typeof t!="string"||t===""||t==="unavailable"||t==="unknown"?null:t}function M(e,n){let t=G(e,n);if(t===null)return null;let r=t.trim();if(!Wa.test(r))return null;let a=Number(r);return Number.isFinite(a)?a:null}var j=(e,n)=>G(e,n)==="on";function Ua(e){if(e===null)return null;let n=Fa.exec(e.trim());if(!n)return null;let t=Number(n[1]),r=Number(n[2]);return t>23||r>59?null:t*60+r}function nr(e){if(e===null)return null;let n=Va.exec(e.trim());if(!n)return null;let t=Number(n[1]),r=Number(n[2]);return t>23||r>59?null:t*60+r}function Ha(e,n){let t=`sensor.${e}_ecco_timezone${n}_`;return{time:`${t}time`,power:`${t}power`,soc:`${t}soc`,charge:`${t}charge`}}function Ga(e){return{fpActive:`binary_sensor.${e}_free_power_active`,fpOp:`binary_sensor.${e}_free_power_operation_in_progress`,fpSnapshot:`binary_sensor.${e}_free_power_snapshot_valid`,dgActive:`binary_sensor.${e}_dump_to_grid_active`,dgOp:`binary_sensor.${e}_dump_to_grid_operation_in_progress`,dgSnapshot:`binary_sensor.${e}_dump_to_grid_snapshot_valid`}}function Wt(e,n){let t=e[n]?.attributes;return t&&typeof t=="object"?t:{}}function rr(e){return typeof e=="number"&&Number.isFinite(e)?e:null}function Ka(e,n){let t=g=>({advice:null,available:!1,note:g,chargeTargetPct:null}),r=G(e,n.status);if(r===null)return t("The Intelligence advice is not available (its status cannot be read).");if(j(e,n.paused))return t("Intelligence is paused by the owner; it publishes no advice.");if(r!=="OK")return t("Intelligence status is "+r+"; it publishes no figures.");if(G(e,n.fresh)!=="on")return t("The Intelligence advice is not fresh; it is not shown as a forecast.");let a=n.charge_target,o=Wt(e,a).advice,i=o&&typeof o=="object"&&!Array.isArray(o)?o:{},s=Wt(e,a).confidence,l=[],c=M(e,a),d=i.binding_constraint;c!==null&&l.push("Charge target advice "+c+" %"+(typeof d=="string"?" (limited by "+d.toLowerCase().replace(/_/g," ")+")":"")+"."),i.conservative_fallback===!0&&l.push("Not enough demand evidence yet, so Intelligence advises keeping the battery well charged.");let p=rr(i.net_need_kwh);p!==null&&l.push("Net overnight need after solar credit: "+p.toFixed(1)+" kWh.");let v=Wt(e,a).blockers;if(Array.isArray(v))for(let g of v.slice(0,4)){let E=g&&typeof g=="object"?g.text:null;typeof E=="string"&&E.trim()&&l.push("Blocked: "+E.trim())}return l.push("Import is the grid energy Intelligence plans for the overnight charge; it does not include daytime import."),{advice:{expectedImportKwh:rr(i.grid_charge_kwh),expectedExportKwh:M(e,n.export_event),expectedSolarKwh:M(e,n.pv_tomorrow),chargeFinishMin:null,confidence:typeof s=="string"?s:null,why:l},available:!0,note:null,chargeTargetPct:c}}function Ba(e,n){let t=[],r=[];for(let o=1;o<=La;o++){let i=Ha(n,o),s=Ua(G(e,i.time)),l=M(e,i.power),c=M(e,i.soc),d=G(e,i.charge),p=[];s===null&&p.push("start time"),l===null&&p.push("power"),c===null&&p.push("target SOC"),d!=="Grid"&&d!=="None"&&p.push("charge source"),p.length?r.push("slot "+o+" "+p.join(", ")):t.push({startMin:s,powerW:l,targetSoc:c,source:d})}if(r.length)return{table:null,reason:"The six TOU slots cannot all be read ("+r.join("; ")+"), so no comparison is possible."};let a=ye(t);return a.ok?{table:t,reason:null}:{table:null,reason:"The inverter's six slots are not a valid six-slot day ("+a.why+"), so no comparison is made."}}var Se=0,Ee=100;function ja(e,n){if(!n)return{known:!1,value:null,reason:"No backup reserve entity is configured (plan.reserve)."};if(e[n]===void 0)return{known:!1,value:null,reason:"The backup reserve entity was not found, so the reserve now is not known."};let t=G(e,n);if(t===null)return{known:!1,value:null,reason:"The backup reserve cannot be read."};let r=M(e,n);return r===null?{known:!1,value:null,reason:"The backup reserve ("+t.trim().slice(0,24)+") is not a number, so it is not used."}:r<Se||r>Ee?{known:!1,value:null,reason:"The backup reserve reads "+r+", which is not a percentage from "+Se+" to "+Ee+", so it is not used."}:{known:!0,value:r,reason:""}}function oe(e,n,t,r=null){if(n===null)return{value:null,reason:t,observed:null};let a=Ve(e,n);return a.ok?{value:a.value,reason:"",observed:r}:{value:null,reason:"The value "+n+" is outside what ECCO accepts ("+a.error+")",observed:null}}function ar(e,n){let t=e.plan??{},r=e.free_power,a=e.schedule,o=e.dump_to_grid,i=o?.schedule,s=t.entity_prefix,l={...$a,...t.advice??{}},c=Ka(n,l),d=s?Ba(n,s):{table:null,reason:"No TOU slot prefix is configured (plan.entity_prefix), so the six slots are not read."},p=d.table,v=p?p.filter(k=>k.source==="Grid"):[],b=v.length===1?v[0]:null,g={};for(let k of xe)g[k]={value:null,reason:"This card has no entity for it.",observed:null};let E=a?nr(G(n,a.start)):null,_=a?M(n,a.duration):null,R=a?M(n,a.power):r?M(n,r.max_charge_power):null;g["charge.powerW"]=oe("charge.powerW",R,"The charge power cannot be read."),g["charge.windowStartMin"]=oe("charge.windowStartMin",E,a?"The scheduled charge start cannot be read.":"No schedule is configured, so there is no charge window.");let x=null;E!==null&&_!==null&&Number.isInteger(_)&&_>0&&_<1440&&(x=(E+_)%1440),g["charge.windowEndMin"]=oe("charge.windowEndMin",x,a?"The scheduled charge end cannot be worked out (start or duration unreadable, or not on the 5-minute grid).":"No schedule is configured, so there is no charge window."),g["charge.targetSoc"]=oe("charge.targetSoc",b?b.targetSoc:null,"The charge target is not stated: the inverter table has no single grid-charge slot to read it from.",b?b.targetSoc:null),g["charge.bufferMin"]={value:null,reason:"No finish-before-window-end buffer is set by any entity this card reads.",observed:null};let C=o?j(n,o.active):!1,P=i?M(n,i.power):o?M(n,o.export_power):null,W=i?M(n,i.stop_soc):o?M(n,o.stop_soc):null,f=o&&C?M(n,o.active_export_power):null,w=o&&C?M(n,o.active_stop_soc):null,D=i?nr(G(n,i.start)):null,$=i?M(n,i.duration):o?M(n,o.duration):null;g["export.powerW"]=oe("export.powerW",P,"The export power cannot be read.",f),g["export.stopSoc"]=oe("export.stopSoc",W,"The Stop SOC cannot be read.",w),g["export.startMin"]=oe("export.startMin",D,i?"The scheduled export start cannot be read.":"No export schedule is configured, so there is no export start time."),g["export.durationMin"]=oe("export.durationMin",$,"The export duration cannot be read.");let T=ja(n,t.reserve);g["reserve.backupPct"]=T.known?oe("reserve.backupPct",T.value,T.reason):{value:null,reason:T.reason,observed:null},g["reserve.planningPct"]={value:null,reason:"Intelligence's planning reserve is not read by this card.",observed:null};let ke={};for(let k of xe)ke[k]=g[k].value!==null?g[k].value:J[k].min;let Q=Vn(ke,"owner"),Bt=a?j(n,a.armed):!1,ot=r?j(n,r.active):!1,jt=i?j(n,i.armed):!1,Tr=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"],Dr=["export.stopSoc","export.powerW","export.startMin","export.durationMin"],it=(k,N)=>{let F=nt(Q,{type:N,path:k});F.ok&&(Q=F.settings)},zt=(k,N,F)=>{for(let I of k)g[I].value!==null&&(F?(it(I,"arm"),it(I,"begin")):N&&it(I,"arm"))};zt(Tr,Bt,ot),zt(Dr,jt,C);for(let k of xe){let N=g[k];if(N.value===null||N.observed===null)continue;let F=nt(Q,{type:"readback",path:k,observed:N.observed});F.ok&&(Q=F.settings)}let Yt=null;if(c.chargeTargetPct!==null&&g["charge.targetSoc"].value!==null&&c.chargeTargetPct!==g["charge.targetSoc"].value){let k=nt(Q,{type:"edit",path:"charge.targetSoc",value:c.chargeTargetPct,source:"intelligence"});k.ok&&(Q=k.settings,Yt=Q.fields["charge.targetSoc"].proposal?.value??null)}let qt=xe.map(k=>{let N=g[k],F=Q.fields[k],I=J[k];return k==="reserve.backupPct"&&N.value===null&&T.known&&T.value!==null?{path:k,label:I.label,unit:I.unit,known:!0,value:T.value,state:F.state,source:F.source,observed:null,proposal:null,note:"Read from your backup reserve helper. The plan's own settings model holds whole percents from "+I.min+" to "+I.max+" only, so it keeps no figure for this value; the installed overrides accept any reserve from "+Se+" to "+Ee+" %."}:{path:k,label:I.label,unit:I.unit,known:N.value!==null,...N.value===null?{reason:N.reason}:{},value:F.value,state:F.state,source:F.source,observed:F.observed,proposal:k==="charge.targetSoc"?Yt:null}}),Be=[],Xt=null;if(p){let k=[],N=ee=>g[ee].value;if(Bt||ot){let ee=N("charge.windowStartMin"),Me=N("charge.powerW"),be=N("charge.targetSoc");ee===null||_===null||Me===null||be===null?Be.push("The armed charge could not be placed in the table: "+(be===null?"its target SOC is unknown.":"its start, duration or power is unreadable.")):k.push({action:"charge",startMin:ee,durationMin:_,targetSoc:be,powerW:Me})}if(jt||C){let ee=N("export.startMin"),Me=N("export.powerW"),be=N("export.stopSoc"),Jt=N("export.durationMin");ee===null||Me===null||be===null||Jt===null?Be.push("The armed export could not be placed in the table: a start, duration, power or Stop SOC is unreadable."):k.push({action:"export",startMin:ee,durationMin:Jt,targetSoc:be,powerW:Me})}let F=null,I=s?Ga(s):null;I&&(j(n,I.fpActive)||j(n,I.fpOp)||j(n,I.fpSnapshot))||ot||r&&(j(n,r.operation_in_progress)||j(n,r.snapshot_valid))?F="Free Power":(I&&(j(n,I.dgActive)||j(n,I.dgOp)||j(n,I.dgSnapshot))||C||o&&(j(n,o.operation_in_progress)||j(n,o.snapshot_valid)))&&(F="Dump to Grid");let Qt=t.control_lock?G(n,t.control_lock)==="off":!1;!Qt&&k.some(ee=>ee.action==="export")&&Be.push(t.control_lock?"Control is locked or its state is unreadable, so the export is not placed in the table (fail-safe).":"No grid-loss lock state is configured (plan.control_lock), so an export is not placed in the table (fail-safe)."),Xt=zn({baseline:p,intervals:k,observed:p,lastApplied:null,transactionOwner:F,controlLocked:!Qt})}let Ar=za(er({advice:c.advice,settings:Q}),qt,c);return{settings:Q,fields:qt,tomorrow:Ar,tou:{readable:p!==null,reason:d.reason,observed:p,compile:Xt,notes:Be},overrides:[],adviceAvailable:c.available,adviceNote:c.note,currentReserve:T}}function za(e,n,t){let r=c=>n.find(d=>d.path===c)?.known===!0,a=n.find(c=>c.path==="reserve.backupPct"),o=a!==void 0&&a.known&&a.note!==void 0,i=e.why.filter(c=>c.origin!=="settings"?!0:c.text.startsWith("Charge target ")?r("charge.targetSoc"):c.text.startsWith("Export stops at ")?r("export.stopSoc"):c.text.startsWith("Backup reserve ")?r("reserve.backupPct"):!0).map(c=>c.origin==="settings"&&c.text.startsWith("Backup reserve ")&&o?{...c,text:"Backup reserve "+a.value+" % (owner's helper, no read-back)."}:c);r("charge.targetSoc")||i.push({origin:"settings",text:"Charge target: unknown (no single grid-charge slot to read it from)."}),r("export.stopSoc")||i.push({origin:"settings",text:"Export Stop SOC: unknown (not readable)."}),r("reserve.backupPct")||i.push({origin:"settings",text:"Backup reserve: unknown (no entity configured or readable)."});let s=c=>!c.known&&t.note?{...c,reason:t.note}:c,l=e.reservePct.known&&!r("reserve.backupPct")?{known:!1,reason:n.find(c=>c.path==="reserve.backupPct")?.reason??"Unknown.",state:"PROPOSED"}:e.reservePct.known&&o?{...e.reservePct,value:a.value}:e.reservePct;return{...e,why:i,importKwh:s(e.importKwh),exportKwh:s(e.exportKwh),solarKwh:s(e.solarKwh),chargeFinishMin:s(e.chargeFinishMin),reservePct:l}}var U={confirmed:"input_boolean.ecco_plan_overrides_enabled",revision:"input_number.ecco_plan_revision",min_expiry:"input_number.ecco_plan_policy_min_expiry",hold_default:"input_number.ecco_plan_policy_hold_default",hold_cap:"input_number.ecco_plan_policy_hold_cap",skip_until:"input_datetime.ecco_plan_policy_skip_until",skip_cap:"input_number.ecco_plan_policy_skip_cap",cut_default:"input_number.ecco_plan_policy_cut_default",cut_cap:"input_number.ecco_plan_policy_cut_cap",cut_reserve:"input_number.ecco_plan_policy_cut_reserve",hold_battery_start:"input_datetime.ecco_plan_override_hold_battery_start",hold_battery_expires:"input_datetime.ecco_plan_override_hold_battery_expires",skip_tonight_start:"input_datetime.ecco_plan_override_skip_tonight_start",skip_tonight_expires:"input_datetime.ecco_plan_override_skip_tonight_expires",prepare_power_cut_start:"input_datetime.ecco_plan_override_prepare_power_cut_start",prepare_power_cut_expires:"input_datetime.ecco_plan_override_prepare_power_cut_expires",prepare_power_cut_reserve:"input_number.ecco_plan_override_prepare_power_cut_reserve",hold_battery_expires_epoch:"input_number.ecco_plan_override_hold_battery_expires_epoch",skip_tonight_expires_epoch:"input_number.ecco_plan_override_skip_tonight_expires_epoch",prepare_power_cut_expires_epoch:"input_number.ecco_plan_override_prepare_power_cut_expires_epoch"},Ya=/^(\d{2}):(\d{2})(?::(\d{2}))?$/,qa=/^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2}$/;function Xa(e){if(e===null)return null;let n=Ya.exec(e.trim());if(!n)return null;let t=Number(n[1]),r=Number(n[2]),a=n[3]===void 0?0:Number(n[3]);return t>23||r>59||a>59?null:t*60+r+a/60}function Qa(e,n){let t=G(e,n);return t==="on"?!0:t==="off"?!1:null}function or(e,n,t){let r=G(e,n);if(r===null)return{ok:!1,reason:t+" cannot be read."};let a=qa.exec(r.trim());if(!a)return{ok:!1,reason:t+" is not a date and time."};let o=e[n]?.attributes?.timestamp;return typeof o!="number"||!Number.isFinite(o)?{ok:!1,reason:t+" has no timestamp, so its moment cannot be placed."}:{ok:!0,min:Math.round(o/60),text:a[1]+" "+a[2]+":"+a[3]}}var ir=4102444800,Ja="Held through the absolute epoch record: the date-and-time record does not show it running (it reads earlier, has ended or cannot be read). Home Assistant follows the later of the two.",Za="A record of this override cannot be read here, so it is not shown as ended. Home Assistant keeps the hold, and any raised reserve, until a cancel settles it.",eo="This record is not trusted here (see the problem listed), but Home Assistant keeps the hold, and any raised reserve, while it runs. A cancel ends it.";function to(e){let n=Math.floor(e/1440),t=e-n*1440,r=n+719468,a=Math.floor(r/146097),o=r-a*146097,i=Math.floor((o-Math.floor(o/1460)+Math.floor(o/36524)-Math.floor(o/146096))/365),s=o-(365*i+Math.floor(i/4)-Math.floor(i/100)),l=Math.floor((5*s+2)/153),c=s-Math.floor((153*l+2)/5)+1,d=l<10?l+3:l-9,p=i+a*400+(d<=2?1:0),v=b=>(b<10?"0":"")+b;return p+"-"+v(d)+"-"+v(c)+" "+v(Math.floor(t/60))+":"+v(t%60)}function no(e,n,t){if(e[n]===void 0)return{ok:!1,absent:!0,reason:t+" absolute expiry record is not installed."};let r=M(e,n);if(r===null)return{ok:!1,reason:t+" absolute expiry record cannot be read."};if(r<0||r>ir)return{ok:!1,reason:t+" absolute expiry record is not a time between 0 and "+ir+" seconds."};let a=Math.ceil(r/60);return{ok:!0,min:a,text:to(a)+" UTC"}}function ro(e,n,t){if(e.ok&&n.ok){let r=n.min>e.min,a=r?n.min:e.min;return{read:a>t?"active":"cleared",endMin:a,endFrom:r?"epoch":"datetime"}}return e.ok&&!n.ok&&"absent"in n?{read:e.min>t?"active":"cleared",endMin:e.min,endFrom:"datetime"}:e.ok&&e.min>t?{read:"active",endMin:e.min,endFrom:"datetime"}:n.ok&&n.min>t?{read:"active",endMin:n.min,endFrom:"epoch"}:{read:"unreadable",endMin:null,endFrom:null}}function ao(e,n,t){let r=[],a=[];if(n===null)return t.push("The current time is not known, so stored override records cannot be judged."),{rows:r,records:a};let o=[];for(let i of le){let s=X[i],l=U[i+"_start"],c=U[i+"_expires"],d=U[i+"_expires_epoch"],p=or(e,c,s+" expiry"),v=no(e,d,s);p.ok||t.push(p.reason),v.ok||("absent"in v?o.push(s):t.push(v.reason));let b=ro(p,v,n),g=b.endFrom==="epoch"&&v.ok?v.text:p.ok?p.text:null,E=null;if(b.read==="active"&&b.endMin!==null){let _=b.endMin,R=or(e,l,s+" start");if(!R.ok)t.push(R.reason+" The record is not trusted.");else{let x=_-R.min;if(!(x>0))t.push(s+" starts at or after its expiry. The record is not trusted.");else if(x>ce[i])t.push(s+" lasts longer than its hard ceiling. The record is not trusted.");else{let C={kind:i,startedAtMin:R.min,expiresAtMin:_},P=!0;if(i==="prepare_power_cut"){let W=M(e,U.prepare_power_cut_reserve);W===null||!Number.isInteger(W)||W<m.reserveMin||W>m.reserveMax?(t.push(s+" has no readable reserve inside "+m.reserveMin+"-"+m.reserveMax+" %. The record is not trusted."),P=!1):C.reservePct=W}P&&(E={override:C,label:s,expiresText:g??"",remainingMin:Math.max(1,_-n),note:b.endFrom==="epoch"?Ja:""})}}}E&&r.push(E),a.push({kind:i,label:s,read:b.read,endMin:b.endMin,endText:b.endMin===null?null:g,note:E?E.note:b.read==="active"?eo:b.read==="unreadable"?Za:"",epochMissing:!v.ok&&"absent"in v})}return o.length>0&&t.push("The absolute expiry record of "+o.join(", ")+" is not installed (an older helper package), so "+(o.length===1?"it is":"they are")+" judged by the date-and-time record only."),{rows:r,records:a}}function oo(e){let n=M(e,U.revision);return n===null?{known:!1,value:null,reason:"The stored plan revision cannot be read."}:!Number.isInteger(n)||n<0?{known:!1,value:null,reason:"The stored plan revision is not a whole number."}:{known:!0,value:n,reason:""}}function io(e,n,t,r=null){let a=Object.values(U),o=a.filter(g=>e[g]===void 0);if(o.length===a.length)return null;let i=Qa(e,U.confirmed),s={confirmed:i,minExpiryMin:M(e,U.min_expiry),holdDefaultMin:M(e,U.hold_default),holdCapMin:M(e,U.hold_cap),skipUntilMin:Xa(G(e,U.skip_until)),skipCapMin:M(e,U.skip_cap),cutDefaultMin:M(e,U.cut_default),cutCapMin:M(e,U.cut_cap),cutReservePct:M(e,U.cut_reserve)},l=$t(s,{currentReservePct:t}),c=$t(s),d=[],{rows:p,records:v}=ao(e,n,d),b=v.filter(g=>g.read!=="cleared"&&!p.some(E=>E.override.kind===g.kind));return{missing:o,confirmed:i,policy:l,startPolicy:c,socPct:r,revision:oo(e),active:p,records:v,held:b,problems:d,nowMin:n}}function sr(e,n,t){let r=ar(e,n),a=r.fields.find(l=>l.path==="reserve.backupPct"),o=e.plan?.battery_soc??e.dump_to_grid?.battery_soc,i=o?M(n,o):null,s=io(n,t,a&&a.known?a.value:null,i);return s?{...r,overrides:s.active.map(l=>l.override),helpers:s}:{...r,helpers:null}}var Ge=Object.freeze({PROPOSED:{kind:"PROPOSED",label:"Proposed",icon:"mdi:lightbulb-outline",meaning:"Proposed: shown for review, not armed and not applied."},ARMED:{kind:"ARMED",label:"Armed",icon:"mdi:shield-check-outline",meaning:"Armed: scheduled and waiting to start, not yet running."},EXECUTING:{kind:"EXECUTING",label:"Executing",icon:"mdi:progress-clock",meaning:"Executing: a session is running now and no read-back has confirmed this value yet."},APPLIED_VERIFIED:{kind:"APPLIED_VERIFIED",label:"Applied and verified",icon:"mdi:check-circle-outline",meaning:"Applied and verified: a read-back from the system equals this value."},MISMATCH:{kind:"MISMATCH",label:"Mismatch",icon:"mdi:alert-circle-outline",meaning:"Mismatch: what the system reports differs from the intended value."},UNKNOWN:{kind:"UNKNOWN",label:"Unknown",icon:"mdi:help-circle-outline",meaning:"Unknown: this cannot be read, so no value is shown."}}),so="SHADOW / advice only. Nothing shown here is applied by this view: it displays what Home Assistant, the inverter and Intelligence report, and it writes nothing.",lo="Quick overrides: none active. Shown as status only; starting one needs a plan helper that does not exist yet.",co="Quick overrides: none active.",uo="Status only: nothing in this view starts, cancels or enforces an override. An override can only hold back ECCO's own export starts or raise the reserve ECCO's plan uses; it never writes the inverter's table, does not change the inverter's own reserve and never stops a running session.",po="This list only shows the records Home Assistant holds: nothing in it starts, cancels or enforces an override. Start and Cancel are under Quick overrides. An override only holds back ECCO's own export starts or raises the reserve ECCO's plan uses, and never stops a running session.";function Ut(e,n){return"The battery is at "+Math.round(e)+" percent, below the "+Math.round(n)+" percent reserve. Nothing is charging. Use Charge Battery if you want it filled."}function Ht(e,n){return e.endMin!==null&&e.endText!==null&&n!==null&&e.endMin>n?"Held by Home Assistant until "+e.endText+" (ends in "+Z(e.endMin-n)+")":"Held by Home Assistant (a record cannot be read here)"}var ho={HIGH:"High",MEDIUM:"Medium",LOW:"Low",INSUFFICIENT:"Insufficient evidence"},Ft=e=>e.toFixed(1)+" kWh";function Vt(e){return Ge[e]}function lr(e){return`${B(e.startMin)} ${e.source==="Grid"?"charge from grid":"no grid charge"}, ${e.powerW} W, to ${e.targetSoc} %`}var mo=e=>"time"in J[e.path];function cr(e,n){return mo(e)?B(n):e.unit?`${n} ${e.unit}`:String(n)}function fo(e){if(!e.known)return{path:e.path,label:e.label,known:!1,text:"Unknown",reason:e.reason??"Not readable.",chip:Ge.UNKNOWN,remarks:[]};let n=[],t=r=>cr(e,r);return e.observed!==null&&e.observed!==e.value&&n.push(`The system reports ${t(e.observed)}, not ${t(e.value)}.`),e.proposal!==null&&n.push(`Intelligence suggests ${t(e.proposal)} (not adopted; nothing here changes it).`),e.state==="PROPOSED"&&e.observed===null&&n.push("No read-back is available for this value."),e.note&&n.push(e.note),{path:e.path,label:e.label,known:!0,text:cr(e,e.value),reason:"",chip:Vt(e.state),remarks:n}}function go(e){let n=e.intended,t=e.observed;if(!t)return null;let r=[];return n.startMin!==t.startMin&&r.push(`start ${B(n.startMin)} intended, ${B(t.startMin)} on the inverter`),n.source!==t.source&&r.push(`charge source ${n.source} intended, ${t.source} on the inverter`),n.powerW!==t.powerW&&r.push(`power ${n.powerW} W intended, ${t.powerW} W on the inverter`),n.targetSoc!==t.targetSoc&&r.push(`target ${n.targetSoc} % intended, ${t.targetSoc} % on the inverter`),r.length?`Slot ${e.index} differs from the inverter: ${r.join("; ")}. It is not applied there, and this view does not apply it.`:null}var bo={"native-fallback":"Native (unchanged)","derived:charge":"Derived from the charge plan","derived:export":"Derived from the export plan"},vo={OK:"Compiled",INFEASIBLE:"Does not fit six slots",CONFLICT:"Conflict with a manual change",REFUSED:"Not compiled"};function _o(e){let n=e.tou;if(!n.readable||!n.compile)return{readable:!1,headline:n.reason??"The six slots cannot be read.",statusText:null,reasons:[...n.notes],slots:[],mismatchCount:0};let t=n.compile,r=t.slotReports.map((s,l)=>{let c=t.slotReports[(l+1)%t.slotReports.length],d=s.state==="MISMATCH"?go(s):null,p=s.state==="APPLIED_VERIFIED"?"APPLIED_VERIFIED":s.state==="MISMATCH"?"MISMATCH":"PROPOSED";return{index:s.index,rangeText:`${B(s.intended.startMin)} to ${B(c.intended.startMin)}`,spanMin:K(s.intended.startMin,c.intended.startMin)||1440,intendedText:lr(s.intended),inverterText:s.observed?lr(s.observed):null,originText:bo[s.origin]??s.origin,chip:Ge[p],mismatch:d}}),a=r.filter(s=>s.mismatch!==null).length,o=[...new Set([...t.reasons,...n.notes])],i;return t.status==="OK"&&t.fallback?i="No armed charge or export changes the table: the six slots are as the inverter reports them.":t.status==="OK"?i=`If the armed plan were compiled, ${a} of the six slots would differ from what the inverter reports.`:t.status==="INFEASIBLE"?i="The plan does not fit the inverter's six slots. Nothing is truncated; the native table stays as it is.":t.status==="CONFLICT"?i="The inverter's table looks changed outside ECCO. Nothing is planned until that is reviewed.":i="The plan is not compiled; the native table stays as it is.",{readable:!0,headline:i,statusText:vo[t.status]??t.status,reasons:o,slots:r,mismatchCount:a}}var wo={hold_battery:()=>"Intended: ECCO's own scheduled and guarded export starts are held; charging and the inverter table are untouched.",skip_tonight:()=>"Intended: ECCO's own export starts tonight are held; charging continues.",prepare_power_cut:e=>`Intended: the reserve ECCO's plan uses is ${e??"?"} % or more, and ECCO's own export starts are held. The inverter's own reserve is not changed.`};function xo(){let e=(t,r)=>t==="skipUntilMin"?B(r):t==="cutReservePct"?`${r} %`:Z(r),n={minExpiryMin:"Shortest allowed override",holdDefaultMin:"Hold battery default",holdCapMin:"Hold battery maximum",skipUntilMin:"Skip tonight ends at",skipCapMin:"Skip tonight maximum",cutDefaultMin:"Prepare for power cut default",cutCapMin:"Prepare for power cut maximum",cutReservePct:"Power-cut reserve"};return Zn.map(t=>`${n[t.key]??t.key}: ${e(t.key,t.value)}. ${t.why}`)}function dr(e){let n=t=>Z(t);return`Limits set by you: ${X.hold_battery} default ${n(e.holdDefaultMin)}, up to ${n(e.holdCapMin)}; ${X.skip_tonight} until ${B(e.skipUntilMin)}, up to ${n(e.skipCapMin)}; ${X.prepare_power_cut} default ${n(e.cutDefaultMin)}, up to ${n(e.cutCapMin)}, reserve ${e.cutReservePct} %. Hard ceilings no setting can exceed: ${n(ce.hold_battery)}, ${n(ce.skip_tonight)}, ${n(ce.prepare_power_cut)}.`}function yo(e){return e.held.length>0?" Home Assistant also holds, or cannot read the record of: "+e.held.map(n=>X[n.kind]).join(", ")+" (see below).":""}function So(e){let n=e.policy,t=!n.ok&&e.startPolicy.ok,r=e.active.map(o=>({kind:o.override.kind,label:o.label,untilText:`until ${o.expiresText}`,countdownText:`ends in ${Z(o.remainingMin)}`,effectText:wo[o.override.kind](o.override.reservePct),belowReserve:o.override.kind==="prepare_power_cut"&&typeof o.override.reservePct=="number"&&e.socPct!==null&&e.socPct<o.override.reservePct?Ut(e.socPct,o.override.reservePct):null,note:o.note})),a=e.revision.known?e.revision.value===0?"Plan revision: none recorded yet.":`Plan revision ${e.revision.value} (stored in the plan helper).`:`Plan revision: unknown (${e.revision.reason})`;return{policyOk:n.ok||t,policyLine:n.ok?dr(n.config):e.startPolicy.ok?dr(e.startPolicy.config)+" The power-cut reserve is not above the reserve now, so Prepare for power cut is not offered.":"The override limits are not usable, so no override can be started. Nothing falls back to proposed values.",reasons:n.ok||t?[]:[...n.reasons],warnings:n.ok?[...n.warnings]:[],missing:[...e.missing],proposed:n.ok||t?[]:xo(),revisionText:a,rows:r,held:e.held.map(o=>({kind:o.kind,label:o.label,text:Ht(o,e.nowMin),note:o.note})),problems:[...e.problems],note:uo,recordsNote:po}}function pr(e){let n=e.helpers??null,t=e.tomorrow,r=(o,i,s,l)=>s.known?{key:o,label:i,known:!0,text:l(s.value),reason:"",note:s.simulated?"simulated, not measured":"",chip:Vt(s.state)}:{key:o,label:i,known:!1,text:"Unknown",reason:s.reason,note:"",chip:Ge.UNKNOWN},a=[r("import","Expected import",t.importKwh,Ft),r("export","Expected export",t.exportKwh,Ft),r("solar","Expected solar",t.solarKwh,Ft),r("finish","Charge finishes",t.chargeFinishMin,o=>B(o)),r("reserve","Reserve",t.reservePct,o=>`${o} %`)];return a.push(t.confidence.known?{key:"confidence",label:"Confidence",known:!0,text:ho[t.confidence.level]??t.confidence.level,reason:"",note:"",chip:Vt(t.confidence.state)}:{key:"confidence",label:"Confidence",known:!1,text:"Unknown",reason:"Intelligence did not state how sure it is.",note:"",chip:Ge.UNKNOWN}),{statusLine:so,adviceNote:e.adviceNote,figures:a,why:t.why.map(o=>({origin:o.origin,text:o.text})),settings:e.fields.map(fo),tou:_o(e),overridesLine:n?(e.overrides.length===0?co:`Quick overrides active: ${e.overrides.map(o=>X[o.kind]).join(", ")} (status only).`)+yo(n):e.overrides.length===0?lo:`Quick overrides active: ${e.overrides.map(o=>o.kind).join(", ")} (status only).`,overrideBlock:n?So(n):null}}var ur={import:"Import",export:"Export",solar:"Solar",reserve:"Your reserve"};function hr(e){let n=e.figures.filter(s=>s.known&&ur[s.key]!==void 0).map(s=>ur[s.key]+" "+s.text),t=n.length>0?n.join(" \xB7 "):e.adviceNote??"No figures yet.",r=e.overrideBlock,a=e.tou.headline,o=null,i=!1;if(r){let s=[r.policyOk?"Limits in force":"Limits not usable"];r.problems.length>0&&s.push(r.problems.length+(r.problems.length===1?" record problem":" record problems")),r.missing.length>0&&s.push(r.missing.length+" helper"+(r.missing.length===1?"":"s")+" not found"),s.push(r.revisionText.replace(/ \(stored in the plan helper\)\.$/,".").replace(/\.$/,"")),o=s.join(" \xB7 "),i=!r.policyOk||r.problems.length>0||r.missing.length>0}return{tomorrow:t,tou:a,limits:o,limitsAttention:i}}function Gt(e){return u`<span class="plan-chip chip-${e.kind.toLowerCase()}" title=${e.meaning}><ha-icon icon=${e.icon} aria-hidden="true"></ha-icon><span class="plan-chip-text">${e.label}</span></span>`}function mr(e){return u`
    <div class="plan-figure ${e.known?"":"is-unknown"}" data-figure=${e.key}>
      <dt>${e.label}</dt>
      <dd>
        <span class="plan-figure-value">${e.text}</span>
        ${e.note?u`<span class="plan-note">${e.note}</span>`:h}
        ${Gt(e.chip)}
        ${e.known?h:u`<span class="plan-reason">${e.reason}</span>`}
      </dd>
    </div>
  `}function fr(e){return u`
    <li class="plan-setting ${e.known?"":"is-unknown"}" data-setting=${e.path}>
      <span class="plan-setting-label">${e.label}</span>
      <span class="plan-setting-value">${e.text}</span>
      ${Gt(e.chip)}
      ${e.known?e.remarks.map(n=>u`<span class="plan-reason">${n}</span>`):u`<span class="plan-reason">${e.reason}</span>`}
    </li>
  `}function Eo(e){return u`
    <li class="plan-setting" data-override=${e.kind}>
      <span class="plan-setting-label">${e.label}</span>
      <span class="plan-setting-value">${e.untilText}</span>
      <span class="plan-note">${e.countdownText}</span>
      <span class="plan-reason">${e.effectText}</span>
      ${e.note?u`<span class="plan-reason" data-override-note>${e.note}</span>`:h}
      ${e.belowReserve?u`<span class="plan-reason plan-below-reserve" data-below-reserve role="note">${e.belowReserve}</span>`:h}
    </li>
  `}function ko(e){return u`
    <li class="plan-setting" data-override-held=${e.kind}>
      <span class="plan-setting-label">${e.label}</span>
      <span class="plan-setting-value">${e.text}</span>
      <span class="plan-reason">${e.note}</span>
    </li>
  `}function gr(e,n=!1){return u`
    <div class="plan-override-block" data-block="overrides">
      ${e.rows.length?u`<ul class="plan-settings">${e.rows.map(Eo)}</ul>`:h}${e.held.length?u`<ul class="plan-settings" data-override-held-list>${e.held.map(ko)}</ul>`:h}${n&&(e.rows.length||e.held.length)?u`<p class="plan-reason" data-records-note>${e.recordsNote}</p>`:h}
      <p class="plan-reason" data-override-policy=${e.policyOk?"ok":"unusable"}>${e.policyLine}</p>
      ${e.reasons.length?u`<ul class="plan-reasons">${e.reasons.map(t=>u`<li>${t}</li>`)}</ul>`:h}
      ${e.warnings.length?u`<ul class="plan-reasons">${e.warnings.map(t=>u`<li>${t}</li>`)}</ul>`:h}
      ${e.problems.length?u`<ul class="plan-reasons" data-override-problems>${e.problems.map(t=>u`<li>${t}</li>`)}</ul>`:h}
      ${e.missing.length?u`<p class="plan-reason">Plan helper entities not found: ${e.missing.join(", ")}.</p>`:h}
      ${e.proposed.length?u`
            <details class="plan-why">
              <summary>Proposed values (not in use)</summary>
              <ul>${e.proposed.map(t=>u`<li>${t}</li>`)}</ul>
            </details>
          `:h}
      <p class="plan-reason">${e.revisionText}</p>${n?h:u`
      <p class="plan-reason">${e.note}</p>`}
    </div>
  `}function br(e){return u`
    <li class="plan-slot ${e.mismatch?"is-mismatch":""}" data-slot=${e.index}>
      <div class="plan-slot-head">
        <span class="plan-slot-name">Slot ${e.index}</span>
        <span class="plan-slot-range">${e.rangeText}</span>
        ${Gt(e.chip)}
      </div>
      <div class="plan-slot-line"><span class="plan-slot-key">Intended</span> ${e.intendedText} <span class="plan-note">${e.originText}</span></div>
      <div class="plan-slot-line"><span class="plan-slot-key">Inverter</span> ${e.inverterText??"not read"}</div>
      ${e.mismatch?u`<p class="plan-mismatch" role="note"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon><span>${e.mismatch}</span></p>`:h}
    </li>
  `}function Mo(e,n,t){let r=e.tou;return u`
      <h2 class="plan-title">Plan <span class="plan-badge"><ha-icon icon="mdi:shield-check-outline" aria-hidden="true"></ha-icon>Guarded controls</span></h2>
      <p class="plan-statusline" role="status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon><span>${e.statusLine}</span></p>

      <div class="plan-block" data-block="tomorrow">
        <details class="plan-why plan-fold" data-fold="tomorrow">
          <summary><h3 class="plan-heading">Tomorrow's Plan</h3><span class="plan-fold-line" data-summary="tomorrow">${t.tomorrow}</span></summary>
          ${e.adviceNote?u`<p class="plan-reason plan-advice-note">${e.adviceNote}</p>`:h}
          <dl class="plan-figures">${e.figures.map(a=>mr(a.key==="reserve"?{...a,label:"Your reserve"}:a))}</dl>
          <details class="plan-why">
            <summary>Why?</summary>
            <ul>${e.why.map(a=>u`<li data-origin=${a.origin}>${a.text}</li>`)}</ul>
          </details>
          <details class="plan-why plan-settings-details">
            <summary>Planned settings</summary>
            <ul class="plan-settings">${e.settings.map(fr)}</ul>
          </details>
        </details>
        <p class="plan-overrides">${e.overridesLine}</p>${e.overrideBlock?u`<details class="plan-why plan-fold ${t.limitsAttention?"needs-attention":""}" data-fold="limits">
              <summary><span class="plan-fold-title">Override limits and records</span><span class="plan-fold-line" data-summary="limits">${t.limits}</span></summary>
              ${gr(e.overrideBlock,!0)}
            </details>`:h}${n}
      </div>

      <div class="plan-block" data-block="tou">
        <details class="plan-why plan-fold" data-fold="tou">
          <summary><h3 class="plan-heading">Six-slot TOU timeline${r.statusText?u` <span class="plan-note">${r.statusText}</span>`:h}</h3><span class="plan-fold-line" data-summary="tou">${t.tou}</span></summary>
          <p class="plan-tou-headline">${r.headline}</p>
          ${r.reasons.length?u`<ul class="plan-reasons">${r.reasons.map(a=>u`<li>${a}</li>`)}</ul>`:h}
          ${r.slots.length?u`
                <div class="plan-bar" aria-hidden="true">
                  ${r.slots.map(a=>u`<span class="plan-seg ${a.mismatch?"is-mismatch":""}" style=${"flex-grow:"+a.spanMin}>${a.index}</span>`)}
                </div>
                <ol class="plan-slots">${r.slots.map(br)}</ol>
              `:h}
        </details>
      </div>
    `}function Ro(e,n,t){let r=e.tou,a=t?u`<span class="plan-badge"><ha-icon icon="mdi:shield-check-outline" aria-hidden="true"></ha-icon>Guarded controls</span>`:u`<span class="plan-badge"><ha-icon icon="mdi:eye-outline" aria-hidden="true"></ha-icon>Read only</span>`;return u`
      <h2 class="plan-title">Plan ${a}</h2>
      <p class="plan-statusline" role="status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon><span>${e.statusLine}</span></p>

      <div class="plan-block" data-block="tomorrow">
        <h3 class="plan-heading">Tomorrow's Plan</h3>
        ${e.adviceNote?u`<p class="plan-reason plan-advice-note">${e.adviceNote}</p>`:h}
        <dl class="plan-figures">${e.figures.map(mr)}</dl>
        <details class="plan-why">
          <summary>Why?</summary>
          <ul>${e.why.map(o=>u`<li data-origin=${o.origin}>${o.text}</li>`)}</ul>
        </details>
        <details class="plan-why plan-settings-details">
          <summary>Planned settings</summary>
          <ul class="plan-settings">${e.settings.map(fr)}</ul>
        </details>
        <p class="plan-overrides">${e.overridesLine}</p>${e.overrideBlock?gr(e.overrideBlock):h}${n}
      </div>

      <div class="plan-block" data-block="tou">
        <h3 class="plan-heading">Six-slot TOU timeline${r.statusText?u` <span class="plan-note">${r.statusText}</span>`:h}</h3>
        <p class="plan-tou-headline">${r.headline}</p>
        ${r.reasons.length?u`<ul class="plan-reasons">${r.reasons.map(o=>u`<li>${o}</li>`)}</ul>`:h}
        ${r.slots.length?u`
              <div class="plan-bar" aria-hidden="true">
                ${r.slots.map(o=>u`<span class="plan-seg ${o.mismatch?"is-mismatch":""}" style=${"flex-grow:"+o.spanMin}>${o.index}</span>`)}
              </div>
              <ol class="plan-slots">${r.slots.map(br)}</ol>
            `:h}
      </div>
    `}function Po(e,n=h){return n!==h?u`
    <section class="plan-section plan-compact" aria-label="Plan, with guarded controls">${Mo(e,n,hr(e))}</section>
  `:u`
    <section class="plan-section" aria-label="Plan, read only">${Ro(e,h,!1)}</section>
  `}function vr(e,n,t,r){if(!e||e.show_plan!==!0)return h;let a=typeof t=="number"&&Number.isFinite(t)?t:Date.now(),o=sr(e,n??{},Math.floor(a/6e4)),i=pr(o),s=e.dump_to_grid?.guarded_start;return Po(i,r?r({snap:o,states:n??{},nowMs:a,guardedStart:typeof s=="string"?s:null}):h)}var _r=de`
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
  /* The compact guarded view: folded regions with an always-visible one-line summary. */
  .plan-compact .plan-block {
    margin-top: 6px;
  }
  .plan-compact .plan-statusline {
    margin: 0 0 6px;
    font-size: 12px;
  }
  .plan-fold {
    margin-top: 6px;
    border-top: 1px solid var(--eaa-border);
  }
  .plan-fold > summary {
    flex-wrap: wrap;
    gap: 2px 10px;
    min-height: 36px;
  }
  .plan-fold > summary .plan-heading,
  .plan-fold > summary .plan-fold-title {
    margin: 0;
    font-size: 14px;
    font-weight: 700;
  }
  .plan-fold > summary::before {
    content: "";
    flex: 0 0 auto;
    align-self: center;
    border-left: 6px solid var(--eaa-text-muted);
    border-top: 4px solid transparent;
    border-bottom: 4px solid transparent;
    margin-right: 2px;
  }
  .plan-fold[open] > summary::before {
    transform: rotate(90deg);
  }
  .plan-fold-line {
    flex: 1 1 200px;
    min-width: 0;
    font-size: 12px;
    font-weight: 400;
    color: var(--eaa-text-muted);
    overflow-wrap: anywhere;
  }
  .plan-fold.needs-attention > summary .plan-fold-line {
    color: var(--eaa-warning);
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
`;var H={last_result:"input_text.ecco_plan_last_result",start_script:"script.ecco_plan_override_start",cancel_script:"script.ecco_plan_override_cancel"};function Kt(e,n,t){let r={kind:e};return n.untilLocal===!0?r.until_local=!0:typeof n.expiryMin=="number"&&(r.expiry_min=n.expiryMin),typeof t=="number"&&(r.expected_revision=t),{domain:"script",service:"turn_on",data:{entity_id:H.start_script,variables:r}}}function wr(e,n){let t={kind:e};return typeof n=="number"&&(t.expected_revision=n),{domain:"script",service:"turn_on",data:{entity_id:H.cancel_script,variables:t}}}function xr(e){return/^script\.[a-z0-9_]+$/.test(e)?{domain:"script",service:"turn_on",data:{entity_id:e}}:null}function yr(e,n){if(typeof e!="object"||e===null)return!1;let t=e;if(t.domain!=="script"||t.service!=="turn_on"||typeof t.data!="object"||t.data===null)return!1;let r=t.data;if(Object.keys(t.data).some(i=>i!=="entity_id"&&i!=="variables"))return!1;let a=r.entity_id,o=typeof n=="string"&&n!==""&&a===n;return a!==H.start_script&&a!==H.cancel_script&&!o?!1:r.variables===void 0?!0:typeof r.variables!="object"||r.variables===null||o?!1:Object.keys(r.variables).every(i=>i==="kind"||i==="expiry_min"||i==="until_local"||i==="expected_revision")}var To=["NOT_ACTIVE","REVISION_CONFLICT","REVISION_UNREADABLE","UNKNOWN_KIND"],Do=" Home Assistant keeps the hold, and any raised reserve, until a cancel is confirmed.";function Sr(e,n,t){let r=n.data.variables??{},a=le.find(o=>o===r.kind);a!==void 0&&(n.data.entity_id===H.cancel_script?e[a]={revision:typeof r.expected_revision=="number"?r.expected_revision:null,answer:t}:n.data.entity_id===H.start_script&&delete e[a])}function Ao(e,n,t,r,a,o){if(!t)return null;let i=t.revision;if(i!==null&&r!==null&&r>i+1)return null;let s=i!==null&&r!==null&&r>i,l=a!==t.answer,c=a==="CANCELLED "+e+".",d=a!==null&&To.some(E=>a.startsWith("REFUSED "+E+" "));if(l&&!c&&!d)return null;if(!s&&!l)return{outcome:"pending",text:"Cancel sent for "+n+". Waiting for Home Assistant to answer: the plan revision and both records are read back before it is called cancelled."};if(o===void 0)return{outcome:"pending",text:"Cancel sent for "+n+". The records cannot be read back because the current time is not known."};let p=o.read==="cleared",v=o.epochMissing?"the date-and-time record reads as ended (the absolute record is not installed)":"both records read as ended";if(p&&s)return{outcome:"confirmed",text:"Cancel confirmed for "+n+": "+v+(r!==null?" (plan revision "+r+")":"")+"."};if(p&&d)return{outcome:"confirmed",text:"Nothing to cancel for "+n+": "+(o.epochMissing?"the date-and-time record already reads as ended (the absolute record is not installed)":"both records already read as ended")+"."};if(p)return{outcome:"not_confirmed",text:"Cancel NOT confirmed for "+n+": "+v+", but the plan revision did not move as a cancel moves it (or cannot be read), so the answer is not taken on trust."};let b=o.read==="active"?"a record still holds it until "+(o.endText??"an unknown time"):"a record cannot be read here",g=d&&!s?"Home Assistant did not carry it out. Its answer was: "+a+" "+b.charAt(0).toUpperCase()+b.slice(1):b;return{outcome:"not_confirmed",text:"Cancel NOT confirmed for "+n+": "+g+"."+Do}}var Ke={effective_reserve:"sensor.ecco_plan_effective_reserve",export_hold:"sensor.ecco_plan_export_hold"};function Co(e,n){let t=p=>e[p]!==void 0,r=t(H.start_script),a=t(H.cancel_script),o=t(U.confirmed),i=t(Ke.effective_reserve),s=t(Ke.export_hold),l=typeof n=="string"&&n!==""?n:null,c=l===null?"not_configured":t(l)?"installed":"missing",d=[];return r||d.push(H.start_script),a||d.push(H.cancel_script),o||d.push(U.confirmed),i||d.push(Ke.effective_reserve),s||d.push(Ke.export_hold),c==="missing"&&l!==null&&d.push(l),{startScript:r,cancelScript:a,confirmationSwitch:o,effectiveReserve:i,exportHold:s,guardedDump:c,missing:d}}var No="Overrides ready.",Io="Overrides only partly ready.",Oo="Turn on the confirmation switch: override limits reviewed and confirmed.";function $o(e,n,t,r){if(!e.startScript&&!e.cancelScript)return{kind:"not_installed",text:"Overrides are not installed: the guarded scripts ("+H.start_script+", "+H.cancel_script+") were not found."};if(!e.startScript||!e.cancelScript)return{kind:"partial",text:"Only part of the override package is installed: "+(e.startScript?H.cancel_script:H.start_script)+" was not found, so overrides cannot be started or cancelled here."};if(n===!1)return{kind:"needs_confirmation",text:Oo};if(n===null)return{kind:"confirmation_unreadable",text:"The confirmation switch (override limits reviewed and confirmed) cannot be read, so no override can be started."};if(!t.ok)return{kind:"limits_unusable",text:"The override limits are not usable: "+(t.reasons&&t.reasons[0]||"see the limits below.")};if(r!==null)return{kind:"revision_unreadable",text:r.replace(/\.$/,"")+", so no override can be started."};let a=[];return e.effectiveReserve||a.push("the effective-reserve sensor"),e.exportHold||a.push("the export-hold sensor"),e.guardedDump==="missing"&&a.push("the guarded Dump to Grid start script"),a.length?{kind:"ready_with_gaps",text:Io+" Not found: "+a.join(", ")+"."}:{kind:"ready",text:No}}function Lo(e){let n=Ke.effective_reserve;if(e[n]===void 0)return{known:!1,value:null,reason:"the effective-reserve sensor was not found"};if(G(e,n)===null)return{known:!1,value:null,reason:"the effective-reserve sensor cannot be read"};let t=M(e,n);return t===null||t<Se||t>Ee?{known:!1,value:null,reason:"the effective-reserve sensor does not read a percentage from "+Se+" to "+Ee}:{known:!0,value:t,reason:""}}function Wo(e,n,t,r,a=null){let o=e!==null&&t!==null?t>Math.ceil(e):null,i=a!==null?"Your reserve":"Reserve now";return{nowPct:e,nowReason:n,targetPct:t,targetReason:r,planPct:a!==null&&a.known?a.value:null,planReason:a!==null&&!a.known?a.reason:"",nowText:e!==null?i+" "+e+" %":i+" unknown ("+n+")",targetText:t!==null?"Power cut target "+t+" %":"Power cut target unknown ("+r+")",planText:a===null?null:a.known?"Plan reserve now "+a.value+" %":"Plan reserve now unknown ("+a.reason+")",canRaise:o}}function Er(e){let n=e.snap.helpers;if(!n)return null;let t=Math.floor(e.nowMs/6e4),r=n.revision.known?n.revision.value:null,a=[H.start_script,H.cancel_script].filter(_=>e.states[_]===void 0),o=e.snap.fields.find(_=>_.path==="reserve.backupPct"),i=o&&o.known?o.value:null,s=n.startPolicy.ok?n.startPolicy.config:null,l=Co(e.states,e.guardedStart),c=$o(l,n.confirmed,n.startPolicy.ok?{ok:!0}:{ok:!1,reasons:n.startPolicy.reasons},n.revision.known?null:n.revision.reason),d=e.snap.currentReserve,p=Lo(e.states),v=n.active.length>0||n.held.length>0||p.known&&(i===null||p.value!==i),b=Wo(i,d?d.reason:"The backup reserve cannot be read.",s?s.cutReservePct:null,"the override limits are not usable",v?p:null),g=G(e.states,H.last_result);return{kinds:le.map(_=>{let R=n.active.find(w=>w.override.kind===_)??null,x=[],C=null;if(!s)C=n.startPolicy.ok?null:n.startPolicy.reasons[0]??"The override limits are not usable.";else{let w=Qn(_,s,e.clock),D=w.length?w[0]:null,$=Jn(_,t,D?D.expiryMin:null,n.startPolicy,{clock:e.clock,currentReservePct:i});if(!$.ok&&($.code==="RESERVE_UNKNOWN"||$.code==="RESERVE_BELOW_CURRENT"))C=$.error;else if(_==="prepare_power_cut"&&b.canRaise===!1){let T=b.nowPct,ke=Math.ceil(T);C="The power cut target ("+b.targetPct+" %) is not above the reserve now ("+T+" %"+(ke===T?"":", which the plan uses as "+ke+" %")+"), so it cannot raise the reserve."}else w.length===0?C="No length fits the owner's limits.":x=w.map(T=>({id:T.id,label:T.label,isDefault:T.isDefault,call:T.untilMin!==null?Kt(_,{untilLocal:!0},r):Kt(_,{expiryMin:T.expiryMin},r)}))}let P=n.held.find(w=>w.kind===_)??null,W=R||null,f=_==="prepare_power_cut"&&W&&typeof W.override.reservePct=="number"&&n.socPct!==null&&n.socPct<W.override.reservePct?Ut(n.socPct,W.override.reservePct):null;return{kind:_,label:X[_],active:R!==null,activeText:R?"Active until "+R.expiresText+" (ends in "+Z(R.remainingMin)+")":P?Ht(P,t):null,held:P!==null,note:(R?R.note:P?P.note:"")||null,readback:Ao(_,X[_],e.cancels?.[_],r,g,n.records.find(w=>w.kind===_)),choices:x,blockedReason:C,cancel:R||P?wr(_,r):null,belowReserve:f,reserve:_==="prepare_power_cut"?b:null}}),install:l,readiness:c,lastResult:g,missingScripts:a}}function Fo(e,n){if(typeof e!="number"||!Number.isFinite(e))return null;let r=(c=>((Math.floor(c/6e4)-n(c))%1440+1440)%1440)(e),a=n(e),o=a-n(e+864e5);if(o===0)return{nowWallMin:r,day:{changeAtMin:0,deltaMin:0}};if(o!==60&&o!==-60)return null;let i=e,s=e+864e5;for(;s-i>6e4;){let c=Math.floor((i+s)/2);n(c)===a?i=c:s=c}let l=((Math.floor(s/6e4)-a)%1440+1440)%1440;return{nowWallMin:r,day:{changeAtMin:l,deltaMin:o}}}function kr(e){return Fo(e,n=>new Date(n).getTimezoneOffset())}var Vo={hold_battery:"Holds back ECCO's own scheduled and guarded export starts. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",skip_tonight:"Holds back ECCO's own scheduled and guarded export starts tonight. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",prepare_power_cut:"Sets the reserve ECCO's plan uses to the larger of your own reserve and the power-cut reserve, and holds back ECCO's own export starts. It does not change the inverter's own reserve and does not stop the house using the battery. It does not charge the battery."},Uo={hold_battery:"Holds back ECCO's own export starts.",skip_tonight:"Holds back ECCO's own export starts tonight.",prepare_power_cut:"Raises the reserve ECCO's plan uses and holds back its export starts. Never charges."},Ho="Partial protection only: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant or by an assistant. These overrides and the reserve protect ECCO's own starts and this card, not an administrator, an assistant or a press of the dongle's own button, and their helpers are plain helpers that an administrator or assistant can write. Binding the Start button needs a firmware gate (a flash, approved separately).";function Go(e,n){return u`
    <div class="plan-control" data-control=${e.kind}>
      <div class="plan-control-head">
        <span class="plan-setting-label">${e.label}</span>
        ${e.activeText?e.held?u`<span class="plan-setting-value" data-control-held>${e.activeText}</span>`:u`<span class="plan-setting-value" data-control-active>${e.activeText}</span>`:h}
      </div>
      <p class="plan-reason plan-effect" data-effect>${Uo[e.kind]??""}</p>
      ${e.reserve?u`<p class="plan-reason plan-reserve-line" data-reserve-line><span data-reserve-now>${e.reserve.nowText}</span>${e.reserve.planText!==null?u` &middot; <span data-reserve-plan>${e.reserve.planText}</span>`:h} &middot; <span data-reserve-target>${e.reserve.targetText}</span></p>`:h}
      ${e.note?u`<p class="plan-reason" data-control-note role="note">${e.note}</p>`:h}
      ${e.belowReserve?u`<p class="plan-reason plan-below-reserve" data-below-reserve role="note">${e.belowReserve}</p>`:h}
      ${e.blockedReason?u`<p class="plan-reason" data-control-blocked>${e.blockedReason}</p>`:h}
      <div class="plan-control-buttons">
        ${e.choices.length?u`<span class="plan-note">${e.active?"Start again for":"Start for"}</span>`:h}
        ${e.choices.map(t=>u`<button type="button" class="plan-control-btn ${t.isDefault?"is-default":""}" data-choice=${t.id}
            aria-label=${e.label+": start for "+t.label} @click=${()=>n(t.call)}>${t.label}</button>`)}
        ${e.cancel?u`<button type="button" class="plan-control-btn is-cancel" data-cancel aria-label=${"Cancel "+e.label} @click=${()=>n(e.cancel)}>Cancel</button>`:h}
      </div>
      <details class="plan-why plan-fold plan-kind-more" data-fold="kind-more">
        <summary>What ${e.label} does</summary>
        <p class="plan-reason">${Vo[e.kind]??""}</p>
      </details>
      ${e.readback?u`<p class="plan-reason plan-readback" data-readback=${e.readback.outcome} role="status">${e.readback.text}</p>`:h}
    </div>
  `}function Ko(e,n){return u`
    <div class="plan-controls" data-block="controls">
      <div class="plan-controls-head">
        <h3 class="plan-heading">Quick overrides</h3>
        ${e.readiness.kind!=="not_installed"&&e.readiness.kind!=="partial"?u`<span class="plan-readiness" data-readiness=${e.readiness.kind} role="status">${e.readiness.text}</span>`:h}
      </div>
      <details class="plan-why plan-fold plan-intro" data-fold="overrides-intro">
        <summary>What quick overrides do</summary>
        <p class="plan-reason">They hold back ECCO's own export starts and, for Prepare for power cut, set the reserve ECCO's plan uses. They do not change the inverter's own reserve or any inverter setting, do not stop the house using the battery and never charge it. Home Assistant checks every one against your limits again and may refuse it.</p>
      </details>
      <p class="plan-reason plan-limitation" data-plan-limitation role="note">${Ho}</p>
      ${e.missingScripts.length?u`<p class="plan-reason" data-controls-missing data-readiness=${e.readiness.kind}>${e.readiness.kind==="partial"?e.readiness.text:"The guarded scripts were not found ("+e.missingScripts.join(", ")+"), so the overrides are not installed here and no override can be started or cancelled."}</p>`:e.kinds.map(t=>Go(t,n))}
      ${e.lastResult?u`<p class="plan-reason plan-result" data-plan-result role="status">Last answer: ${e.lastResult}</p>`:h}
    </div>
  `}var Mr={};function Rr(e){return({snap:n,states:t,nowMs:r,guardedStart:a})=>{let o=Er({snap:n,states:t,nowMs:r,clock:kr(r),cancels:Mr,guardedStart:a});return o?Ko(o,i=>{Sr(Mr,i,o.lastResult),e(i)}):h}}var Pr=de`
  .plan-controls {
    margin-top: 8px;
    min-width: 0;
  }
  .plan-controls-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 10px;
  }
  .plan-controls-head .plan-heading {
    margin: 0;
  }
  .plan-readiness {
    font-size: 12px;
    font-weight: 600;
    color: var(--eaa-ok);
  }
  .plan-readiness[data-readiness="needs_confirmation"],
  .plan-readiness[data-readiness="confirmation_unreadable"],
  .plan-readiness[data-readiness="limits_unusable"],
  .plan-readiness[data-readiness="ready_with_gaps"],
  .plan-readiness[data-readiness="revision_unreadable"] {
    color: var(--eaa-warning);
  }
  .plan-effect,
  .plan-reserve-line {
    margin: 2px 0 0;
  }
  .plan-reserve-line {
    font-weight: 600;
    color: inherit;
  }
  .plan-kind-more,
  .plan-intro {
    margin-top: 2px;
    border-top: 0;
  }
  .plan-kind-more > summary,
  .plan-intro > summary {
    min-height: 28px;
    font-size: 12px;
    font-weight: 600;
    color: var(--eaa-text-muted);
  }
  .plan-control {
    padding: 6px 0;
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
`;var at=4e3,Bo=1e3,A=class extends se{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:_t,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(t){if(!t||typeof t!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!t.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=t}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(t){return!!this._config}willUpdate(){let t=this._config?.free_power;if(t){this._pendingPower!==void 0&&S(this._entityState(t.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&S(this._entityState(t.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let o=y(this._entityState(t.active)),i=y(this._entityState(t.write_enable)),s=y(this._entityState(t.operation_in_progress)),l=this._entityState(t.status),c=Ze({active:o,armed:i,operationInProgress:s,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==c&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=c}let r=this._config?.schedule;r&&(this._pendingSchedulePower!==void 0&&S(this._entityState(r.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&S(this._entityState(r.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let a=this._config?.dump_to_grid;if(a){this._pendingDumpPower!==void 0&&S(this._entityState(a.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&S(this._entityState(a.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&S(this._entityState(a.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let o=a.schedule;o&&(this._pendingDumpSchedulePower!==void 0&&S(this._entityState(o.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&S(this._entityState(o.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&S(this._entityState(o.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let i=y(this._entityState(a.active)),s=y(this._entityState(a.write_enable)),l=y(this._entityState(a.operation_in_progress)),c=y(this._entityState(a.snapshot_valid)),d=this._entityState(a.status),p=et({active:i,armed:s,operationInProgress:l,snapshotValid:c,statusText:d});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==p&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=p}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let o=this._trackSummary();Tn(o.fp.state,o.dump.state)&&(this._track=Et(o.fp.state,o.dump.state))}}updated(){let t=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();t&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},Bo):!t&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let t=this._config?.free_power;return t?y(this._entityState(t.active))===!0:!1}_scheduleArmed(){let t=this._config?.schedule;return t?y(this._entityState(t.armed))===!0:!1}_dumpActive(){let t=this._config?.dump_to_grid;return t?y(this._entityState(t.active))===!0:!1}_dumpScheduleArmed(){let t=this._config?.dump_to_grid?.schedule;return t?y(this._entityState(t.armed))===!0:!1}_freePowerVisualStateForInterlock(){let t=this._config?.free_power;if(!t||!this.hass)return null;let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=this._entityState(t.status);return Ze({active:r,armed:a,operationInProgress:o,statusText:i})}_dumpVisualStateForInterlock(){let t=this._config?.dump_to_grid;if(!t||!this.hass)return null;let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status);return et({active:r,armed:a,operationInProgress:o,snapshotValid:i,statusText:s})}_entityState(t){if(!(!t||!this.hass))return this.hass.states[t]?.state}_entity(t){if(!(!t||!this.hass))return this.hass.states[t]}_moreInfo(t){t&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:t},bubbles:!0,composed:!0}))}_callService(t,r,a){this.hass?.callService&&this.hass.callService(t,r,a)}_callServiceObj(t){this._callService(t.domain,t.service,t.data)}render(){if(!this._config)return u``;let t=this._config.title??_t;return this._config.layout==="tabbed"?this._renderTabbed(t):u`
      <ha-card>
        <h1 class="card-title">${t}</h1>
        <div class="actions-grid">
          ${this._renderFreePowerTile()}
          ${this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
    `}_renderPlan(){return vr(this._config,this.hass?.states,void 0,Rr(t=>this._callPlanService(t)))}_callPlanService(t){yr(t,this._config?.dump_to_grid?.guarded_start)&&this._callService(t.domain,t.service,t.data)}_pressDumpStart(t){if(t.guarded_start!==void 0&&t.guarded_start!==""){let r=xr(t.guarded_start);r&&this._callPlanService(r);return}this._callService("button","press",{entity_id:t.start})}_trackSummary(){let t=this._freePowerVisualStateForInterlock(),r=this._dumpVisualStateForInterlock(),a={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},o=this._config?.free_power;if(t!==null&&o){let l=this._config?.schedule,c=l?Tt(t,kt({armed:y(this._entityState(l.armed))})):t,d=Oe(t,r)?"interlocked":c;a={state:d,pill:d,label:this._labelFor(d),statusText:this._entityState(o.status)}}let i=this._config?.dump_to_grid,s=i&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(r!==null&&i){let l=i.schedule,c=xt(r,l?y(this._entityState(l.armed)):null),d=Oe(r,t)?"interlocked":c;s={state:d,pill:d,label:yt(d),statusText:this._entityState(i.status)}}return{fp:a,dump:s}}_selectTrack(t){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=t}_renderTabbed(t){let r=this._trackSummary(),a=this._track??Et(r.fp.state,r.dump.state),o=a==="free_power"?"dump_to_grid":"free_power",i=a==="free_power"?r.dump:r.fp,s=An(Dn(i.state)),l=s==="fault"?"mdi:alert-circle-outline":s==="warning"?"mdi:alert-outline":"mdi:information-outline";return u`
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
            class="mode-tab track-tab ${a==="free_power"?"is-active":""}"
            aria-selected=${a==="free_power"}
            @click=${()=>this._selectTrack("free_power")}
          >
            <ha-icon icon="mdi:flash"></ha-icon> Free Power
          </button>
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${a==="dump_to_grid"?"is-active":""}"
            aria-selected=${a==="dump_to_grid"}
            @click=${()=>this._selectTrack("dump_to_grid")}
          >
            <ha-icon icon="mdi:transmission-tower-export"></ha-icon> Dump to Grid
          </button>
        </div>
        ${s?u`
              <div class="track-alert track-alert-${s}" role="status">
                <ha-icon icon=${l}></ha-icon>
                <div class="track-alert-text">${Nn(Cn(o),i.label,i.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(o)}>Show</button>
              </div>
            `:h}
        <div class="actions-grid is-tabbed">
          ${a==="free_power"?this._renderFreePowerTile():this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
    `}_renderFreePowerTile(){let t=this._config?.free_power;if(!t||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=Ze({active:r,armed:a,operationInProgress:o,statusText:s});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let c=this._config?.schedule,d=c?y(this._entityState(c.armed)):null,p=kt({armed:d}),v=c?Tt(l,p):l,b=this._dumpVisualStateForInterlock(),g=Oe(l,b),E=g?"interlocked":v,_=g?St("Dump to Grid",b):void 0,R=this._entity(t.max_charge_power),x=this._entity(t.duration),C=this._pendingPower??S(R?.state),P=this._pendingDuration??S(x?.state),W=this._iconFor(E),f=this._labelFor(E);return u`
      <div class="tile free-power-tile state-${E}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${W}></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-${E}">${f}</span>
        </div>

        <div class="free-power-body">
          ${c&&p==="armed"?this._renderScheduleBanner(c):h}
          ${g?this._renderInterlockBanner(_):h}

          ${this._renderFreePowerBody(l,{fp:t,schedule:c,statusText:s,snapshotValid:i,interlocked:g,stagedPowerW:C,stagedDurationMin:P,stagedPowerEntity:R,stagedDurationEntity:x})}
        </div>
      </div>
    `}_iconFor(t){if(t==="scheduled")return"mdi:calendar-clock";if(t==="interlocked")return"mdi:lock-outline";switch(t){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(t){return t==="scheduled"?"Scheduled":t==="interlocked"?"Interlocked":wn(t)}_renderInterlockBanner(t){return u`
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
    `}_renderFreePowerBody(t,r){switch(t){case"active":return this._renderActiveBody(r);case"busy":return this._renderBusyBody(r.statusText,r.fp.status);case"deferred":return this._renderDeferredBody(r.statusText,r.fp.status);case"recovery_attention":return this._renderAttentionBody(r);default:return this._renderReadyOrArmedBody(t,r)}}_renderReadyOrArmedBody(t,r){let a=!!r.schedule,o=a?this._mode:"now";return u`
      ${a?this._renderModeSelector():h}
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
    `}_renderNowPanel(t,r){let a=t==="armed",o=$e(vn(t),r.interlocked),i=$e(_n(t),r.interlocked);return u`
      <p class="tile-description">Charge the battery from free/zero-cost grid energy.</p>

      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:r.interlocked,onPreview:s=>this._pendingPower=s,onCommit:s=>this._commitNumber("power",s,r.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:r.interlocked,onPreview:s=>this._pendingDuration=s,onCommit:s=>this._commitNumber("duration",s,r.fp.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${a?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${a?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(r.statusText,r.fp.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${a?"is-armed":""}"
          ?disabled=${!i}
          @click=${()=>this._toggleArm(r.fp.write_enable,a)}
        >
          <ha-icon icon=${a?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${a?"Disarm":"Arm Free Power"}
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
    `}_renderLaterPanel(t){let r=y(this._entityState(t.armed)),a=Pt(r),o=this._entityState(t.start),i=fe(o),s=this._entity(t.duration),l=this._entity(t.power),c=this._entity(t.status),d=this._entityState(t.last_result),p=this._pendingScheduleDuration??S(s?.state),v=this._pendingSchedulePower??S(l?.state),b=c?.attributes?.effective_power_limit_w,g=typeof b=="number"?b:S(typeof b=="string"?b:void 0),E=this._numericAttr(l?.attributes?.max,8e3),_=On(E,g),R=Mt(d),x=Rt(d),C=!a&&i!==null&&i.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${i?this._toDatetimeLocalValue(i):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${a}
          @change=${P=>this._handleScheduleStartChange(t.start,P.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:v,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:_,formatValue:ne,disabled:a||!l,onPreview:P=>this._pendingSchedulePower=P,onCommit:P=>this._commitScheduleNumber("power",P,t.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:a||!s,onPreview:P=>this._pendingScheduleDuration=P,onCommit:P=>this._commitScheduleNumber("duration",P,t.duration)})}

      ${d?u`<p class="firmware-note ${R||x?"is-warning":""}">${d}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${a||!C}
          @click=${()=>this._callServiceObj(Dt(t.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${a?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the manual Free Power write-enable switch - Home Assistant arms and starts the inverter automatically when the time comes."}
      </p>
    `}_renderScheduleBanner(t){let r=this._entityState(t.start),a=fe(r),o=S(this._entityState(t.duration)),i=S(this._entityState(t.power)),s=a?Le(a.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${a?Nt(a):"--"} • ${ne(i)} • ${ge(o)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(At(t.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_toDatetimeLocalValue(t){let r=a=>a.toString().padStart(2,"0");return`${t.getFullYear()}-${r(t.getMonth()+1)}-${r(t.getDate())}T${r(t.getHours())}:${r(t.getMinutes())}`}_handleScheduleStartChange(t,r){if(!r)return;let a=new Date(r);Number.isNaN(a.getTime())||this._callServiceObj(In(t,$n(a)))}_commitScheduleNumber(t,r,a){t==="power"?this._pendingSchedulePower=r:this._pendingScheduleDuration=r,this._callServiceObj(Ct(a,r))}_renderActiveBody(t){let r=this._entityState(t.fp.ends_at),a=fe(r),o=a?Le(a.getTime(),this._nowMs):null;return u`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${ne(t.stagedPowerW)} target • ends ${a?this._formatClock(a):r??"--"}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${t.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${t.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(t.statusText,t.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(t.fp)}
      ${this._renderEndRestoreButton(t.fp.end_restore,"End & Restore Now",!1,wt("active"))}
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
    `}_renderAttentionBody(t){let r=Mn({statusText:t.statusText,snapshotValid:t.snapshotValid});return u`
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
      ${r.actionable?this._renderEndRestoreButton(t.fp.end_restore,r.actionLabel??"End & Restore Now",r.secondary,wt("recovery_attention")):h}
    `}_renderTransitionDetail(t,r){return u`
      <div
        class="transition-detail clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(r)}
        @keydown=${a=>{(a.key==="Enter"||a.key===" ")&&(a.preventDefault(),this._moreInfo(r))}}
      >
        ${t}
      </div>
    `}_renderStatusLine(t,r,a){return!(a?.alwaysShow||!!t&&t!=="Inactive")||!t?h:u`
      <p
        class="firmware-note clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(r)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(r))}}
      >
        ${t}
      </p>
    `}_renderDiagnosticsDetails(t){let r=[],a=(o,i)=>{let s=S(this._entityState(i));s!==null&&r.push({label:o,value:s.toString()})};return a("Starts",t.start_attempts),a("Started OK",t.start_successes),a("Restored OK",t.restore_successes),a("Failures",t.failures),r.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(t,r,a,o){let i=this._confirmEndRestore;return u`
      <button
        class="end-restore-button ${a?"secondary":""} ${i?"confirming":""}"
        ?disabled=${!o}
        @click=${()=>this._handleEndRestoreClick(t)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${i?"Tap again to End & Restore":r}
        ${i?u`<span class="confirm-progress" style="animation-duration:${at}ms"></span>`:h}
      </button>
    `}_handleEndRestoreClick(t){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},at);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:t})}_toggleArm(t,r){this._callService("switch",r?"turn_off":"turn_on",{entity_id:t})}_commitNumber(t,r,a){t==="power"?this._pendingPower=r:this._pendingDuration=r,this._callService("number","set_value",{entity_id:a,value:r})}_commitDumpNumber(t,r,a){t==="power"?this._pendingDumpPower=r:t==="stop_soc"?this._pendingDumpStopSoc=r:this._pendingDumpDuration=r,this._callService("number","set_value",{entity_id:a,value:r})}_handleEndDumpClick(t){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},at);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:t})}_numericAttr(t,r){if(typeof t=="number"&&Number.isFinite(t))return t;if(typeof t=="string"){let a=S(t);if(a!==null)return a}return r}_formatClock(t){let r=t.getHours().toString().padStart(2,"0"),a=t.getMinutes().toString().padStart(2,"0");return`${r}:${a}`}_renderNumberControl(t){let r=t.entity?.attributes??{},a=this._numericAttr(r.min,t.fallbackMin),o=t.maxOverride??this._numericAttr(r.max,t.fallbackMax),i=this._numericAttr(r.step,t.fallbackStep),s=t.value??a,l=t.disabled??!t.entity,c=o>a?Math.max(0,Math.min(100,(s-a)/(o-a)*100)):0;return u`
      <div class="number-control">
        <div class="number-control-label">
          <ha-icon icon=${t.icon}></ha-icon>
          <span>${t.label}</span>
          <span class="number-control-value">${t.formatValue(s)}</span>
        </div>
        <input
          type="range"
          class="number-control-slider"
          style="--eaa-slider-fill:${c}%"
          min=${a}
          max=${o}
          step=${i}
          .value=${String(s)}
          ?disabled=${l}
          @input=${d=>{let p=Number(d.target.value);Number.isFinite(p)&&t.onPreview(p)}}
          @change=${d=>{let p=Number(d.target.value);Number.isFinite(p)&&t.onCommit(p)}}
        />
      </div>
    `}_renderDumpToGridTile(){let t=this._config?.dump_to_grid;if(!t||!this.hass)return this._renderDumpToGridLockedShell();let r=y(this._entityState(t.active)),a=y(this._entityState(t.write_enable)),o=y(this._entityState(t.operation_in_progress)),i=y(this._entityState(t.snapshot_valid)),s=this._entityState(t.status),l=et({active:r,armed:a,operationInProgress:o,snapshotValid:i,statusText:s});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let c=t.schedule,d=c?y(this._entityState(c.armed)):null,p=xt(l,d),v=this._freePowerVisualStateForInterlock(),b=Oe(l,v),g=b?"interlocked":p,E=b?St("Free Power",v):void 0,_=this._entity(t.export_power),R=this._entity(t.stop_soc),x=this._entity(t.duration),C=this._pendingDumpPower??S(_?.state),P=this._pendingDumpStopSoc??S(R?.state),W=this._pendingDumpDuration??S(x?.state),f=this._dumpIconFor(g),w=yt(g);return u`
      <div class="tile dump-to-grid-tile state-${g}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${f}></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-${g}">${w}</span>
        </div>

        <div class="dump-to-grid-body">
          ${c&&d===!0?this._renderDumpScheduleBanner(c):h}
          ${b?this._renderInterlockBanner(E):h}

          ${this._renderDumpBody(l,{dump:t,statusText:s,snapshotValid:i,interlocked:b,stagedPowerW:C,stagedStopSoc:P,stagedDurationMin:W,stagedPowerEntity:_,stagedStopSocEntity:R,stagedDurationEntity:x})}
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
    `}_renderDumpBody(t,r){switch(t){case"active":return this._renderDumpActiveBody(r);case"busy":return this._renderBusyBody(r.statusText??"Dump to Grid is mid-transaction.",r.dump.status);case"deferred":return this._renderDumpDeferredBody(r);case"recovery_attention":return this._renderDumpAttentionBody(r);default:return this._renderDumpReadyOrArmedBody(t,r)}}_renderDumpReadyOrArmedBody(t,r){let a=r.dump.schedule,o=a?this._dumpMode:"now";return u`
      ${a?this._renderDumpModeSelector():h}
      ${o==="later"&&a?this._renderDumpLaterPanel(a):this._renderDumpNowPanel(t,r)}
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
    `}_renderDumpNowPanel(t,r){let a=t==="armed",o=$e(xn(t),r.interlocked),i=$e(yn(t),r.interlocked);return u`
      <p class="tile-description">Export stored battery energy to the grid down to a chosen floor.</p>

      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:r.stagedPowerEntity,value:r.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:r.interlocked,onPreview:s=>this._pendingDumpPower=s,onCommit:s=>this._commitDumpNumber("power",s,r.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:r.stagedStopSocEntity,value:r.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:r.interlocked,onPreview:s=>this._pendingDumpStopSoc=s,onCommit:s=>this._commitDumpNumber("stop_soc",s,r.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:r.stagedDurationEntity,value:r.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:r.interlocked,onPreview:s=>this._pendingDumpDuration=s,onCommit:s=>this._commitDumpNumber("duration",s,r.dump.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${a?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${a?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(r.statusText,r.dump.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${a?"is-armed":""}"
          ?disabled=${!i}
          @click=${()=>this._toggleArm(r.dump.write_enable,a)}
        >
          <ha-icon icon=${a?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${a?"Disarm":"Arm Dump to Grid"}
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
    `}_renderDumpLaterPanel(t){let r=y(this._entityState(t.armed)),a=Pt(r),o=this._entityState(t.start),i=fe(o),s=this._entity(t.duration),l=this._entity(t.power),c=this._entity(t.stop_soc),d=this._entityState(t.last_result),p=this._pendingDumpScheduleDuration??S(s?.state),v=this._pendingDumpSchedulePower??S(l?.state),b=this._pendingDumpScheduleStopSoc??S(c?.state),g=Mt(d)||!!d&&/^FAILED/i.test(d.trim()),E=Rt(d),_=!!l&&!!s&&!!c&&r!==null,R=_&&!a&&i!==null&&i.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${i?this._toDatetimeLocalValue(i):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${a}
          @change=${x=>this._handleScheduleStartChange(t.start,x.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:v,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:ne,disabled:a||!l,onPreview:x=>this._pendingDumpSchedulePower=x,onCommit:x=>this._commitDumpScheduleNumber("power",x,t.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:c,value:b,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:we,disabled:a||!c,onPreview:x=>this._pendingDumpScheduleStopSoc=x,onCommit:x=>this._commitDumpScheduleNumber("stop_soc",x,t.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:ge,disabled:a||!s,onPreview:x=>this._pendingDumpScheduleDuration=x,onCommit:x=>this._commitDumpScheduleNumber("duration",x,t.duration)})}

      ${_?h:u`<p class="firmware-note is-warning">
            Scheduled Dump to Grid helpers are unavailable - is ecco_dump_to_grid_schedule.yaml installed?
          </p>`}
      ${d?u`<p class="firmware-note ${g||E?"is-warning":""}">${d}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${!R}
          @click=${()=>this._callServiceObj(Dt(t.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${a?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the Dump to Grid write-enable switch. At the start time Home Assistant stages these values, arms and presses Start; the firmware re-checks Stop SOC, charging TOU slots and Free Power itself. Arming is refused if it overlaps an armed Free Power schedule or a charging TOU slot."}
      </p>
    `}_renderDumpScheduleBanner(t){let r=fe(this._entityState(t.start)),a=S(this._entityState(t.duration)),o=S(this._entityState(t.power)),i=S(this._entityState(t.stop_soc)),s=r?Le(r.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${r?Nt(r):"--"} • ${ne(o)} • stop
            ${we(i)} • ${ge(a)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(At(t.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_commitDumpScheduleNumber(t,r,a){t==="power"?this._pendingDumpSchedulePower=r:t==="stop_soc"?this._pendingDumpScheduleStopSoc=r:this._pendingDumpScheduleDuration=r,this._callServiceObj(Ct(a,r))}_renderDumpLastEndReason(t){let r=this._entityState(t.last_end_reason);return!r||r==="unknown"||r==="unavailable"?h:u`<p class="firmware-note">Last lease ended: ${r}</p>`}_renderDumpActiveBody(t){let r=this._entityState(t.dump.ends_at),a=fe(r),o=a?Le(a.getTime(),this._nowMs):null,i=S(this._entityState(t.dump.battery_soc)),s=Sn(S(this._entityState(t.dump.active_export_power)),t.statusText),l=En(S(this._entityState(t.dump.active_stop_soc)),t.statusText);return u`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${ne(s)} export • ends ${a?this._formatClock(a):r??"--"}
      </div>
      <div class="active-secondary-line">
        Battery: ${we(i)} • stops at ${we(l)}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${t.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${t.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(t.statusText,t.dump.status,{alwaysShow:!0})}
      ${this._renderDumpDiagnosticsDetails(t.dump)}
      ${this._renderEndDumpButton(t.dump.end_restore,"End & Restore Now",tt("active"))}
    `}_renderDumpDeferredBody(t){return u`
      ${this._renderDeferredBody(t.statusText,t.dump.status)}
      ${t.snapshotValid===!0?this._renderEndDumpButton(t.dump.end_restore,"End & Restore Now",tt("deferred")):h}
    `}_renderDumpAttentionBody(t){let a=!!t.dump.recovery_arm&&!!t.dump.recovery_force_restore&&!!t.dump.recovery_accept&&kn(t.statusText,t.snapshotValid);return u`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(t.statusText??"Dump to Grid requires operator attention.",t.dump.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${a?"Automatic restore is stopped until you decide. Arm recovery, then Force Restore Original (writes only the saved original settings) or Accept Current State (writes nothing; refused while the inverter still shows Dump export).":"If the status above says the watchdog will retry, ECCO keeps retrying the restore automatically. Only OPERATOR DECISION REQUIRED stops automatic retries."}
      </p>
      ${a?this._renderDumpRecoveryPanel(t.dump):h}
      ${this._renderEndDumpButton(t.dump.end_restore,"End & Restore Now",tt("recovery_attention"))}
    `}_renderDumpRecoveryPanel(t){let r=y(this._entityState(t.recovery_arm))===!0,a=this._entityState(t.recovery_state);return u`
      <div class="dump-recovery-panel">
        ${a&&a!=="unknown"&&a!=="unavailable"?u`<p class="firmware-note">${a}</p>`:h}
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
    `}_renderDumpDiagnosticsDetails(t){let r=[],a=(o,i)=>{let s=S(this._entityState(i));s!==null&&r.push({label:o,value:s.toString()})};return a("Starts",t.start_attempts),a("Started OK",t.start_successes),a("Restored OK",t.restore_successes),a("Failures",t.failures),r.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${r.map(o=>u`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(t,r,a){let o=this._confirmEndDump;return u`
      <button
        class="end-restore-button ${o?"confirming":""}"
        ?disabled=${!a}
        @click=${()=>this._handleEndDumpClick(t)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${o?"Tap again to End & Restore":r}
        ${o?u`<span class="confirm-progress" style="animation-duration:${at}ms"></span>`:h}
      </button>
    `}};A.styles=[_r,Pr,de`
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
  `],O([Qe({attribute:!1})],A.prototype,"hass",2),O([V()],A.prototype,"_config",2),O([V()],A.prototype,"_pendingPower",2),O([V()],A.prototype,"_pendingDuration",2),O([V()],A.prototype,"_pendingSchedulePower",2),O([V()],A.prototype,"_pendingScheduleDuration",2),O([V()],A.prototype,"_confirmEndRestore",2),O([V()],A.prototype,"_pendingDumpPower",2),O([V()],A.prototype,"_pendingDumpStopSoc",2),O([V()],A.prototype,"_pendingDumpDuration",2),O([V()],A.prototype,"_confirmEndDump",2),O([V()],A.prototype,"_dumpMode",2),O([V()],A.prototype,"_pendingDumpSchedulePower",2),O([V()],A.prototype,"_pendingDumpScheduleStopSoc",2),O([V()],A.prototype,"_pendingDumpScheduleDuration",2),O([V()],A.prototype,"_nowMs",2),O([V()],A.prototype,"_mode",2),O([V()],A.prototype,"_track",2),A=O([bn("ecco-energy-actions-card")],A);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{A as EccoEnergyActionsCard};
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
