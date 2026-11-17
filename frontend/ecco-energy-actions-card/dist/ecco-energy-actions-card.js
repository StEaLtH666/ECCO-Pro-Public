var bn=Object.defineProperty;var vn=Object.getOwnPropertyDescriptor;var D=(t,r,e,n)=>{for(var i=n>1?void 0:n?vn(r,e):r,o=t.length-1,a;o>=0;o--)(a=t[o])&&(i=(n?a(r,e,i):a(i))||i);return n&&i&&bn(r,e,i),i};var We=globalThis,He=We.ShadowRoot&&(We.ShadyCSS===void 0||We.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,nt=Symbol(),Yt=new WeakMap,ke=class{constructor(r,e,n){if(this._$cssResult$=!0,n!==nt)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=r,this.t=e}get styleSheet(){let r=this.o,e=this.t;if(He&&r===void 0){let n=e!==void 0&&e.length===1;n&&(r=Yt.get(e)),r===void 0&&((this.o=r=new CSSStyleSheet).replaceSync(this.cssText),n&&Yt.set(e,r))}return r}toString(){return this.cssText}},qt=t=>new ke(typeof t=="string"?t:t+"",void 0,nt),ce=(t,...r)=>{let e=t.length===1?t[0]:r.reduce((n,i,o)=>n+(a=>{if(a._$cssResult$===!0)return a.cssText;if(typeof a=="number")return a;throw Error("Value passed to 'css' function must be a 'css' function result: "+a+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+t[o+1],t[0]);return new ke(e,t,nt)},Xt=(t,r)=>{if(He)t.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of r){let n=document.createElement("style"),i=We.litNonce;i!==void 0&&n.setAttribute("nonce",i),n.textContent=e.cssText,t.appendChild(n)}},it=He?t=>t:t=>t instanceof CSSStyleSheet?(r=>{let e="";for(let n of r.cssRules)e+=n.cssText;return qt(e)})(t):t;var{is:_n,defineProperty:xn,getOwnPropertyDescriptor:wn,getOwnPropertyNames:yn,getOwnPropertySymbols:Sn,getPrototypeOf:kn}=Object,Be=globalThis,Qt=Be.trustedTypes,En=Qt?Qt.emptyScript:"",Pn=Be.reactiveElementPolyfillSupport,Ee=(t,r)=>t,Pe={toAttribute(t,r){switch(r){case Boolean:t=t?En:null;break;case Object:case Array:t=t==null?t:JSON.stringify(t)}return t},fromAttribute(t,r){let e=t;switch(r){case Boolean:e=t!==null;break;case Number:e=t===null?null:Number(t);break;case Object:case Array:try{e=JSON.parse(t)}catch{e=null}}return e}},Ke=(t,r)=>!_n(t,r),Jt={attribute:!0,type:String,converter:Pe,reflect:!1,useDefault:!1,hasChanged:Ke};Symbol.metadata??=Symbol("metadata"),Be.litPropertyMetadata??=new WeakMap;var Q=class extends HTMLElement{static addInitializer(r){this._$Ei(),(this.l??=[]).push(r)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(r,e=Jt){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(r)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(r,e),!e.noAccessor){let n=Symbol(),i=this.getPropertyDescriptor(r,n,e);i!==void 0&&xn(this.prototype,r,i)}}static getPropertyDescriptor(r,e,n){let{get:i,set:o}=wn(this.prototype,r)??{get(){return this[e]},set(a){this[e]=a}};return{get:i,set(a){let s=i?.call(this);o?.call(this,a),this.requestUpdate(r,s,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(r){return this.elementProperties.get(r)??Jt}static _$Ei(){if(this.hasOwnProperty(Ee("elementProperties")))return;let r=kn(this);r.finalize(),r.l!==void 0&&(this.l=[...r.l]),this.elementProperties=new Map(r.elementProperties)}static finalize(){if(this.hasOwnProperty(Ee("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(Ee("properties"))){let e=this.properties,n=[...yn(e),...Sn(e)];for(let i of n)this.createProperty(i,e[i])}let r=this[Symbol.metadata];if(r!==null){let e=litPropertyMetadata.get(r);if(e!==void 0)for(let[n,i]of e)this.elementProperties.set(n,i)}this._$Eh=new Map;for(let[e,n]of this.elementProperties){let i=this._$Eu(e,n);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(r){let e=[];if(Array.isArray(r)){let n=new Set(r.flat(1/0).reverse());for(let i of n)e.unshift(it(i))}else r!==void 0&&e.push(it(r));return e}static _$Eu(r,e){let n=e.attribute;return n===!1?void 0:typeof n=="string"?n:typeof r=="string"?r.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(r=>this.enableUpdating=r),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(r=>r(this))}addController(r){(this._$EO??=new Set).add(r),this.renderRoot!==void 0&&this.isConnected&&r.hostConnected?.()}removeController(r){this._$EO?.delete(r)}_$E_(){let r=new Map,e=this.constructor.elementProperties;for(let n of e.keys())this.hasOwnProperty(n)&&(r.set(n,this[n]),delete this[n]);r.size>0&&(this._$Ep=r)}createRenderRoot(){let r=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Xt(r,this.constructor.elementStyles),r}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(r=>r.hostConnected?.())}enableUpdating(r){}disconnectedCallback(){this._$EO?.forEach(r=>r.hostDisconnected?.())}attributeChangedCallback(r,e,n){this._$AK(r,n)}_$ET(r,e){let n=this.constructor.elementProperties.get(r),i=this.constructor._$Eu(r,n);if(i!==void 0&&n.reflect===!0){let o=(n.converter?.toAttribute!==void 0?n.converter:Pe).toAttribute(e,n.type);this._$Em=r,o==null?this.removeAttribute(i):this.setAttribute(i,o),this._$Em=null}}_$AK(r,e){let n=this.constructor,i=n._$Eh.get(r);if(i!==void 0&&this._$Em!==i){let o=n.getPropertyOptions(i),a=typeof o.converter=="function"?{fromAttribute:o.converter}:o.converter?.fromAttribute!==void 0?o.converter:Pe;this._$Em=i;let s=a.fromAttribute(e,o.type);this[i]=s??this._$Ej?.get(i)??s,this._$Em=null}}requestUpdate(r,e,n,i=!1,o){if(r!==void 0){let a=this.constructor;if(i===!1&&(o=this[r]),n??=a.getPropertyOptions(r),!((n.hasChanged??Ke)(o,e)||n.useDefault&&n.reflect&&o===this._$Ej?.get(r)&&!this.hasAttribute(a._$Eu(r,n))))return;this.C(r,e,n)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(r,e,{useDefault:n,reflect:i,wrapped:o},a){n&&!(this._$Ej??=new Map).has(r)&&(this._$Ej.set(r,a??e??this[r]),o!==!0||a!==void 0)||(this._$AL.has(r)||(this.hasUpdated||n||(e=void 0),this._$AL.set(r,e)),i===!0&&this._$Em!==r&&(this._$Eq??=new Set).add(r))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let r=this.scheduleUpdate();return r!=null&&await r,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,o]of this._$Ep)this[i]=o;this._$Ep=void 0}let n=this.constructor.elementProperties;if(n.size>0)for(let[i,o]of n){let{wrapped:a}=o,s=this[i];a!==!0||this._$AL.has(i)||s===void 0||this.C(i,void 0,o,s)}}let r=!1,e=this._$AL;try{r=this.shouldUpdate(e),r?(this.willUpdate(e),this._$EO?.forEach(n=>n.hostUpdate?.()),this.update(e)):this._$EM()}catch(n){throw r=!1,this._$EM(),n}r&&this._$AE(e)}willUpdate(r){}_$AE(r){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(r)),this.updated(r)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(r){return!0}update(r){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(r){}firstUpdated(r){}};Q.elementStyles=[],Q.shadowRootOptions={mode:"open"},Q[Ee("elementProperties")]=new Map,Q[Ee("finalized")]=new Map,Pn?.({ReactiveElement:Q}),(Be.reactiveElementVersions??=[]).push("2.1.2");var ut=globalThis,Zt=t=>t,ze=ut.trustedTypes,er=ze?ze.createPolicy("lit-html",{createHTML:t=>t}):void 0,ar="$lit$",ie=`lit$${Math.random().toFixed(9).slice(2)}$`,sr="?"+ie,Mn=`<${sr}>`,pe=document,Re=()=>pe.createComment(""),De=t=>t===null||typeof t!="object"&&typeof t!="function",pt=Array.isArray,Rn=t=>pt(t)||typeof t?.[Symbol.iterator]=="function",ot=`[ 	
\f\r]`,Me=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,tr=/-->/g,rr=/>/g,de=RegExp(`>|${ot}(?:([^\\s"'>=/]+)(${ot}*=${ot}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),nr=/'/g,ir=/"/g,lr=/^(?:script|style|textarea|title)$/i,ht=t=>(r,...e)=>({_$litType$:t,strings:r,values:e}),p=ht(1),ho=ht(2),mo=ht(3),he=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),or=new WeakMap,ue=pe.createTreeWalker(pe,129);function cr(t,r){if(!pt(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return er!==void 0?er.createHTML(r):r}var Dn=(t,r)=>{let e=t.length-1,n=[],i,o=r===2?"<svg>":r===3?"<math>":"",a=Me;for(let s=0;s<e;s++){let l=t[s],d,c,u=-1,b=0;for(;b<l.length&&(a.lastIndex=b,c=a.exec(l),c!==null);)b=a.lastIndex,a===Me?c[1]==="!--"?a=tr:c[1]!==void 0?a=rr:c[2]!==void 0?(lr.test(c[2])&&(i=RegExp("</"+c[2],"g")),a=de):c[3]!==void 0&&(a=de):a===de?c[0]===">"?(a=i??Me,u=-1):c[1]===void 0?u=-2:(u=a.lastIndex-c[2].length,d=c[1],a=c[3]===void 0?de:c[3]==='"'?ir:nr):a===ir||a===nr?a=de:a===tr||a===rr?a=Me:(a=de,i=void 0);let v=a===de&&t[s+1].startsWith("/>")?" ":"";o+=a===Me?l+Mn:u>=0?(n.push(d),l.slice(0,u)+ar+l.slice(u)+ie+v):l+ie+(u===-2?s:v)}return[cr(t,o+(t[e]||"<?>")+(r===2?"</svg>":r===3?"</math>":"")),n]},Te=class t{constructor({strings:r,_$litType$:e},n){let i;this.parts=[];let o=0,a=0,s=r.length-1,l=this.parts,[d,c]=Dn(r,e);if(this.el=t.createElement(d,n),ue.currentNode=this.el.content,e===2||e===3){let u=this.el.content.firstChild;u.replaceWith(...u.childNodes)}for(;(i=ue.nextNode())!==null&&l.length<s;){if(i.nodeType===1){if(i.hasAttributes())for(let u of i.getAttributeNames())if(u.endsWith(ar)){let b=c[a++],v=i.getAttribute(u).split(ie),g=/([.?@])?(.*)/.exec(b);l.push({type:1,index:o,name:g[2],strings:v,ctor:g[1]==="."?st:g[1]==="?"?lt:g[1]==="@"?ct:_e}),i.removeAttribute(u)}else u.startsWith(ie)&&(l.push({type:6,index:o}),i.removeAttribute(u));if(lr.test(i.tagName)){let u=i.textContent.split(ie),b=u.length-1;if(b>0){i.textContent=ze?ze.emptyScript:"";for(let v=0;v<b;v++)i.append(u[v],Re()),ue.nextNode(),l.push({type:2,index:++o});i.append(u[b],Re())}}}else if(i.nodeType===8)if(i.data===sr)l.push({type:2,index:o});else{let u=-1;for(;(u=i.data.indexOf(ie,u+1))!==-1;)l.push({type:7,index:o}),u+=ie.length-1}o++}}static createElement(r,e){let n=pe.createElement("template");return n.innerHTML=r,n}};function ve(t,r,e=t,n){if(r===he)return r;let i=n!==void 0?e._$Co?.[n]:e._$Cl,o=De(r)?void 0:r._$litDirective$;return i?.constructor!==o&&(i?._$AO?.(!1),o===void 0?i=void 0:(i=new o(t),i._$AT(t,e,n)),n!==void 0?(e._$Co??=[])[n]=i:e._$Cl=i),i!==void 0&&(r=ve(t,i._$AS(t,r.values),i,n)),r}var at=class{constructor(r,e){this._$AV=[],this._$AN=void 0,this._$AD=r,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(r){let{el:{content:e},parts:n}=this._$AD,i=(r?.creationScope??pe).importNode(e,!0);ue.currentNode=i;let o=ue.nextNode(),a=0,s=0,l=n[0];for(;l!==void 0;){if(a===l.index){let d;l.type===2?d=new $e(o,o.nextSibling,this,r):l.type===1?d=new l.ctor(o,l.name,l.strings,this,r):l.type===6&&(d=new dt(o,this,r)),this._$AV.push(d),l=n[++s]}a!==l?.index&&(o=ue.nextNode(),a++)}return ue.currentNode=pe,i}p(r){let e=0;for(let n of this._$AV)n!==void 0&&(n.strings!==void 0?(n._$AI(r,n,e),e+=n.strings.length-2):n._$AI(r[e])),e++}},$e=class t{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(r,e,n,i){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=r,this._$AB=e,this._$AM=n,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let r=this._$AA.parentNode,e=this._$AM;return e!==void 0&&r?.nodeType===11&&(r=e.parentNode),r}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(r,e=this){r=ve(this,r,e),De(r)?r===h||r==null||r===""?(this._$AH!==h&&this._$AR(),this._$AH=h):r!==this._$AH&&r!==he&&this._(r):r._$litType$!==void 0?this.$(r):r.nodeType!==void 0?this.T(r):Rn(r)?this.k(r):this._(r)}O(r){return this._$AA.parentNode.insertBefore(r,this._$AB)}T(r){this._$AH!==r&&(this._$AR(),this._$AH=this.O(r))}_(r){this._$AH!==h&&De(this._$AH)?this._$AA.nextSibling.data=r:this.T(pe.createTextNode(r)),this._$AH=r}$(r){let{values:e,_$litType$:n}=r,i=typeof n=="number"?this._$AC(r):(n.el===void 0&&(n.el=Te.createElement(cr(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===i)this._$AH.p(e);else{let o=new at(i,this),a=o.u(this.options);o.p(e),this.T(a),this._$AH=o}}_$AC(r){let e=or.get(r.strings);return e===void 0&&or.set(r.strings,e=new Te(r)),e}k(r){pt(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,n,i=0;for(let o of r)i===e.length?e.push(n=new t(this.O(Re()),this.O(Re()),this,this.options)):n=e[i],n._$AI(o),i++;i<e.length&&(this._$AR(n&&n._$AB.nextSibling,i),e.length=i)}_$AR(r=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);r!==this._$AB;){let n=Zt(r).nextSibling;Zt(r).remove(),r=n}}setConnected(r){this._$AM===void 0&&(this._$Cv=r,this._$AP?.(r))}},_e=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(r,e,n,i,o){this.type=1,this._$AH=h,this._$AN=void 0,this.element=r,this.name=e,this._$AM=i,this.options=o,n.length>2||n[0]!==""||n[1]!==""?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=h}_$AI(r,e=this,n,i){let o=this.strings,a=!1;if(o===void 0)r=ve(this,r,e,0),a=!De(r)||r!==this._$AH&&r!==he,a&&(this._$AH=r);else{let s=r,l,d;for(r=o[0],l=0;l<o.length-1;l++)d=ve(this,s[n+l],e,l),d===he&&(d=this._$AH[l]),a||=!De(d)||d!==this._$AH[l],d===h?r=h:r!==h&&(r+=(d??"")+o[l+1]),this._$AH[l]=d}a&&!i&&this.j(r)}j(r){r===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,r??"")}},st=class extends _e{constructor(){super(...arguments),this.type=3}j(r){this.element[this.name]=r===h?void 0:r}},lt=class extends _e{constructor(){super(...arguments),this.type=4}j(r){this.element.toggleAttribute(this.name,!!r&&r!==h)}},ct=class extends _e{constructor(r,e,n,i,o){super(r,e,n,i,o),this.type=5}_$AI(r,e=this){if((r=ve(this,r,e,0)??h)===he)return;let n=this._$AH,i=r===h&&n!==h||r.capture!==n.capture||r.once!==n.once||r.passive!==n.passive,o=r!==h&&(n===h||i);i&&this.element.removeEventListener(this.name,this,n),o&&this.element.addEventListener(this.name,this,r),this._$AH=r}handleEvent(r){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,r):this._$AH.handleEvent(r)}},dt=class{constructor(r,e,n){this.element=r,this.type=6,this._$AN=void 0,this._$AM=e,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(r){ve(this,r)}};var Tn=ut.litHtmlPolyfillSupport;Tn?.(Te,$e),(ut.litHtmlVersions??=[]).push("3.3.3");var dr=(t,r,e)=>{let n=e?.renderBefore??r,i=n._$litPart$;if(i===void 0){let o=e?.renderBefore??null;n._$litPart$=i=new $e(r.insertBefore(Re(),o),o,void 0,e??{})}return i._$AI(t),i};var mt=globalThis,oe=class extends Q{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let r=super.createRenderRoot();return this.renderOptions.renderBefore??=r.firstChild,r}update(r){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(r),this._$Do=dr(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return he}};oe._$litElement$=!0,oe.finalized=!0,mt.litElementHydrateSupport?.({LitElement:oe});var $n=mt.litElementPolyfillSupport;$n?.({LitElement:oe});(mt.litElementVersions??=[]).push("4.2.2");var ur=t=>(r,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(t,r)}):customElements.define(t,r)};var Cn={attribute:!0,type:String,converter:Pe,reflect:!1,hasChanged:Ke},An=(t=Cn,r,e)=>{let{kind:n,metadata:i}=e,o=globalThis.litPropertyMetadata.get(i);if(o===void 0&&globalThis.litPropertyMetadata.set(i,o=new Map),n==="setter"&&((t=Object.create(t)).wrapped=!0),o.set(e.name,t),n==="accessor"){let{name:a}=e;return{set(s){let l=r.get.call(this);r.set.call(this,s),this.requestUpdate(a,l,t,!0,s)},init(s){return s!==void 0&&this.C(a,void 0,t,s),s}}}if(n==="setter"){let{name:a}=e;return function(s){let l=this[a];r.call(this,s),this.requestUpdate(a,l,t,!0,s)}}throw Error("Unsupported decorator location: "+n)};function Ge(t){return(r,e)=>typeof e=="object"?An(t,r,e):((n,i,o)=>{let a=i.hasOwnProperty(o);return i.constructor.createProperty(o,n),a?Object.getOwnPropertyDescriptor(i,o):void 0})(t,r,e)}function I(t){return Ge({...t,state:!0,attribute:!1})}var ft="Energy Actions";var In=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Nn=/DEFERRED/i,On=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function Ye(t){let{active:r,armed:e,operationInProgress:n,statusText:i}=t;return r===null||e===null||n===null?"unavailable":i&&In.test(i)?"recovery_attention":i&&Nn.test(i)?"deferred":i&&On.test(i)?"busy":r?"active":n?"busy":e?"armed":"ready"}function pr(t){return t==="armed"}function gt(t){return t!=="busy"&&t!=="unavailable"}function hr(t){return t==="ready"||t==="armed"}var Fn={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function mr(t){return Fn[t]}var Ln=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Vn=/DEFERRED/i,Un=/^(RESTORING|STARTING)/i;function qe(t){let{active:r,armed:e,operationInProgress:n,snapshotValid:i,statusText:o}=t;return r===null||e===null||n===null||i===null?"unavailable":o&&Ln.test(o)?"recovery_attention":o&&Vn.test(o)?"deferred":o&&Un.test(o)?"busy":r?"active":n?"busy":i?"deferred":e?"armed":"ready"}function fr(t){return t==="armed"}function Xe(t){return t!=="busy"&&t!=="unavailable"}function gr(t){return t==="ready"||t==="armed"}var Wn={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function Hn(t){return Wn[t]}function bt(t,r){return t==="ready"&&r===!0?"scheduled":t}function vt(t){return t==="scheduled"?"Scheduled":t==="interlocked"?"Interlocked":Hn(t)}var Bn=/target (\d+)\s*W export/i,Kn=/Stop SOC (\d+)\s*%/i;function br(t,r){if(t!==null&&Number.isFinite(t))return t;let e=r?Bn.exec(r):null;return e?Number(e[1]):null}function vr(t,r){if(t!==null&&Number.isFinite(t))return t;let e=r?Kn.exec(r):null;return e?Number(e[1]):null}var zn=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function _r(t,r){return r===!0&&!!t&&zn.test(t)}var Gn=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,jn=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,Yn=/OPERATOR DECISION REQUIRED/i,qn=/press End Free Power|retry(?:ing)? restore/i,Xn=/\bRECOVERY REQUIRED\b/i,Qn=/snapshot retained/i,Jn=/RESTORE BLOCKED/i;function xr(t){let r=t.statusText??"",e=t.snapshotValid;return Gn.test(r)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:jn.test(r)&&e===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:Yn.test(r)&&qn.test(r)&&e===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:Xn.test(r)&&e===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:Qn.test(r)&&e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:Jn.test(r)?e===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var Zn=new Set(["active","busy","recovery_attention","deferred"]);function ei(t){return t!==null&&Zn.has(t)}function Ce(t,r){return(t==="ready"||t==="armed")&&ei(r)}function Ae(t,r){return t&&!r}function _t(t,r){switch(r){case"busy":return`${t} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${t} requires recovery before this can be used.`;default:return`${t} currently owns inverter control.`}}var wr=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function yr(t){let r=wr.indexOf(t);return r<0?wr.length:r}function Sr(t,r){return t!=="unavailable"||r!=="unavailable"}function xt(t,r){return yr(r)<yr(t)?"dump_to_grid":"free_power"}function kr(t){switch(t){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function Er(t){switch(t){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function Pr(t){return t==="dump_to_grid"?"Dump to Grid":"Free Power"}function Mr(t,r,e){let n=e?.trim()??"";return n?`${t}: ${r} - ${n}`:`${t}: ${r}`}function wt(t){return t.armed===!0?"armed":"hidden"}function yt(t){return!!t&&/^REJECTED/i.test(t.trim())}function St(t){return!!t&&/^BLOCKED/i.test(t.trim())}function kt(t){return t===!0}function Et(t,r){return t==="ready"&&r==="armed"?"scheduled":t}function Pt(t){return{domain:"input_boolean",service:"turn_on",data:{entity_id:t}}}function Mt(t){return{domain:"script",service:"turn_on",data:{entity_id:t}}}function Rr(t,r){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:t,datetime:r}}}function Rt(t,r){return{domain:"input_number",service:"set_value",data:{entity_id:t,value:r}}}function Dr(t,r){return r===null||!Number.isFinite(r)||r<=0?t:Math.min(t,r)}var ti=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function me(t){if(!t)return null;let r=ti.exec(t.trim());if(!r)return null;let[,e,n,i,o,a,s]=r,l=new Date(Number(e),Number(n)-1,Number(i),Number(o),Number(a),Number(s));return Number.isNaN(l.getTime())?null:l}function Tr(t){let r=e=>e.toString().padStart(2,"0");return`${t.getFullYear()}-${r(t.getMonth()+1)}-${r(t.getDate())} ${r(t.getHours())}:${r(t.getMinutes())}:${r(t.getSeconds())}`}var ri=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],ni=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Dt(t){let r=ri[t.getDay()],e=t.getDate(),n=ni[t.getMonth()],i=t.getHours().toString().padStart(2,"0"),o=t.getMinutes().toString().padStart(2,"0");return`${r} ${e} ${n} \u2022 ${i}:${o}`}function Ie(t,r){let e=t-r;if(e<=0)return null;let n=Math.floor(e/1e3),i=Math.floor(n/3600),o=Math.floor(n%3600/60),a=n%60;return i>0?`${i}h ${o}m`:o>0?`${o}m ${a.toString().padStart(2,"0")}s`:`${a}s`}function J(t){return t==null||Number.isNaN(t)?"--":Math.abs(t)>=1e3?`${(t/1e3).toFixed(2)} kW`:`${t.toFixed(0)} W`}function fe(t){if(t==null||Number.isNaN(t))return"--";let r=Math.round(t);if(r<60)return`${r} min`;let e=Math.floor(r/60),n=r%60;return n===0?`${e}h`:`${e}h ${n}m`}function xe(t){return t==null||Number.isNaN(t)?"--":`${Math.round(t)}%`}function y(t){if(t==null||t==="unknown"||t==="unavailable"||t==="")return null;let r=Number(t);return Number.isFinite(r)?r:null}function w(t){return t==null||t==="unknown"||t==="unavailable"||t===""?null:t==="on"}function Z(t){return(Math.round(t)%1440+1440)%1440}function L(t,r){return Z(r-t)}function V(t){let r=Z(t),e=n=>(n<10?"0":"")+n;return e(Math.floor(r/60))+":"+e(r%60)}function Ne(t){return Number.isInteger(t)&&t>=0&&t<1440&&t%5===0}var $r=Object.freeze({changeAtMin:0,deltaMin:0});function Cr(t){return t.deltaMin!==0}function Qe(t,r,e){if(e.deltaMin===0||r<=0)return r;let n=L(t,e.changeAtMin);return n>0&&n<r?r-e.deltaMin:r}function Ar(t,r){for(let e=0;e<=r;e+=5)if(Z(t+e)<180)return!0;return!1}var ua=Object.freeze({owner:3,intelligence:2,native:1}),Tt=["MISMATCH","PROPOSED","ARMED","EXECUTING","APPLIED_VERIFIED"],f=Object.freeze({slots:6,minSlotMin:5,bufferMin:0,bufferMax:120,stopSocMin:10,stopSocMax:90,chargeTargetMin:20,chargeTargetMax:100,chargePowerMin:500,chargePowerMax:8e3,exportPowerMin:500,exportPowerMax:3e3,exportDurationMin:10,exportDurationMax:240,reserveMin:10,reserveMax:100}),q={"charge.targetSoc":{label:"Charge target",unit:"%",min:f.chargeTargetMin,max:f.chargeTargetMax,step:1,views:["charge-card","tou-table","tomorrow-plan"]},"charge.bufferMin":{label:"Finish before the window ends",unit:"min",min:f.bufferMin,max:f.bufferMax,step:5,views:["charge-card","tomorrow-plan"]},"charge.powerW":{label:"Maximum charge power",unit:"W",min:f.chargePowerMin,max:f.chargePowerMax,step:100,views:["charge-card","tou-table","tomorrow-plan"]},"charge.windowStartMin":{label:"Charge window start",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"charge.windowEndMin":{label:"Charge window end",unit:"",min:0,max:1439,step:5,time:!0,views:["charge-card","export-card","tou-table","tomorrow-plan"]},"export.stopSoc":{label:"Export down to (Stop SOC)",unit:"%",min:f.stopSocMin,max:f.stopSocMax,step:1,views:["export-card","tou-table","tomorrow-plan","reserve-summary"]},"export.powerW":{label:"Export power",unit:"W",min:f.exportPowerMin,max:f.exportPowerMax,step:100,views:["export-card","tou-table","tomorrow-plan"]},"export.startMin":{label:"Export start",unit:"",min:0,max:1439,step:5,time:!0,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"export.durationMin":{label:"Export duration",unit:"min",min:f.exportDurationMin,max:f.exportDurationMax,step:5,views:["export-card","charge-card","tou-table","tomorrow-plan"]},"reserve.backupPct":{label:"Backup reserve (enforced)",unit:"%",min:f.reserveMin,max:f.reserveMax,step:1,views:["charge-card","export-card","reserve-summary","tomorrow-plan"]},"reserve.planningPct":{label:"Planning reserve (advice)",unit:"%",min:f.reserveMin,max:f.reserveMax,step:1,views:["reserve-summary","tomorrow-plan"]}},we=Object.freeze(Object.keys(q));function Oe(t,r){if(!Object.prototype.hasOwnProperty.call(q,t))return{ok:!1,error:"Unknown setting."};let e=q[t];if(typeof r!="number"||!Number.isFinite(r))return{ok:!1,error:e.label+" needs a number."};if(e.time)return Ne(r)?{ok:!0,value:r}:{ok:!1,error:e.label+" must be a time on the 5-minute grid."};if(r<e.min)return t==="export.stopSoc"?{ok:!1,error:"Stop SOC below "+e.min+" % is not available and is refused, not clamped."}:{ok:!1,error:e.label+" must be at least "+e.min+(e.unit?" "+e.unit:"")+"."};if(r>e.max)return t==="export.stopSoc"?{ok:!1,error:"Stop SOC above "+e.max+" % is not available and is refused, not clamped."}:{ok:!1,error:e.label+" can be at most "+e.max+(e.unit?" "+e.unit:"")+"."};let n=(r-e.min)/e.step;return Math.abs(n-Math.round(n))>1e-9?{ok:!1,error:e.label+" moves in steps of "+e.step+(e.unit?" "+e.unit:"")+"."}:{ok:!0,value:r}}function Ir(t,r="owner"){let e={};for(let n of we){let i=Oe(n,t[n]);if(!i.ok)throw new Error(n+": "+i.error);e[n]={value:i.value,source:r,revision:1,state:"PROPOSED",observed:null,proposal:null,external:null}}return{revision:1,fields:e}}function ii(t){return JSON.parse(JSON.stringify(t))}function C(t,r){return{ok:!1,settings:t,error:r,updates:[]}}function ee(t,r,e){let n=e==="proposal"?r.proposal?.value:e==="external"?r.external?.value:r.value;return n===void 0?[]:q[t].views.map(o=>({view:o,path:t,kind:e,value:n,state:r.state,preview:r.state!=="APPLIED_VERIFIED"}))}function Je(t,r){if(!Object.prototype.hasOwnProperty.call(q,r.path))return C(t,"Unknown setting.");let e=ii(t),n=e.fields[r.path],i=()=>++e.revision;switch(r.type){case"edit":{if(r.expectedRevision!==void 0&&r.expectedRevision!==t.revision)return C(t,"The settings changed (revision "+t.revision+") since this edit was prepared; reload and review.");let o=Oe(r.path,r.value);return o.ok?n.state==="EXECUTING"?C(t,"An apply is in progress for this setting; it cannot be edited until it ends."):n.external?C(t,"The native side was changed outside ECCO; resolve that first (adopt it or keep the intended value)."):r.source==="intelligence"?o.value===n.value?{ok:!0,settings:t,updates:[]}:(n.proposal={value:o.value,revision:i()},{ok:!0,settings:e,updates:ee(r.path,n,"proposal")}):o.value===n.value&&n.source==="owner"?{ok:!0,settings:t,updates:[]}:(n.value=o.value,n.source="owner",n.revision=i(),n.state=n.observed===o.value?"APPLIED_VERIFIED":"PROPOSED",n.proposal&&n.proposal.value===o.value&&(n.proposal=null),{ok:!0,settings:e,updates:ee(r.path,n,"value")}):C(t,o.error)}case"adopt-proposal":return n.proposal?n.state==="EXECUTING"?C(t,"An apply is in progress for this setting."):n.external?C(t,"Resolve the external native change first."):(n.value=n.proposal.value,n.source="intelligence",n.proposal=null,n.revision=i(),n.state=n.observed===n.value?"APPLIED_VERIFIED":"PROPOSED",{ok:!0,settings:e,updates:ee(r.path,n,"value")}):C(t,"There is no Intelligence proposal to adopt.");case"dismiss-proposal":return n.proposal?(n.proposal=null,i(),{ok:!0,settings:e,updates:[]}):C(t,"There is no Intelligence proposal to dismiss.");case"arm":return n.external?C(t,"Resolve the external native change before arming."):n.state!=="PROPOSED"&&n.state!=="MISMATCH"?C(t,"Only a proposed or mismatched setting can be armed (it is "+n.state+")."):(n.state="ARMED",i(),{ok:!0,settings:e,updates:ee(r.path,n,"value")});case"disarm":return n.state!=="ARMED"?C(t,"Only an armed setting can be disarmed."):(n.state="PROPOSED",i(),{ok:!0,settings:e,updates:ee(r.path,n,"value")});case"begin":return n.external?C(t,"Resolve the external native change before executing."):n.state!=="ARMED"?C(t,"Only an armed setting can start executing."):(n.state="EXECUTING",i(),{ok:!0,settings:e,updates:ee(r.path,n,"value")});case"fail":return n.state!=="EXECUTING"?C(t,"Only an executing setting can fail."):(n.state="MISMATCH",i(),{ok:!0,settings:e,updates:ee(r.path,n,"value")});case"readback":{let o=n.observed,a=r.observed;return a!==null&&!Number.isFinite(a)?C(t,"A read-back must be a finite number or null."):a===o?{ok:!0,settings:t,updates:[]}:(n.observed=a,a===null?n.state==="APPLIED_VERIFIED"&&(n.state="PROPOSED"):a===n.value?(n.state="APPLIED_VERIFIED",n.external=null):n.state==="EXECUTING"?n.state="MISMATCH":(n.state==="APPLIED_VERIFIED"||n.state==="MISMATCH"||o!==null&&o!==a)&&(n.external={value:a,revision:e.revision+1},n.state==="APPLIED_VERIFIED"&&(n.state="MISMATCH")),i(),{ok:!0,settings:e,updates:ee(r.path,n,n.external?"external":"value")})}case"resolve-external":{if(!n.external)return C(t,"There is no external change to resolve.");if(r.choice==="adopt-native"){let o=Oe(r.path,n.external.value);if(!o.ok)return C(t,"The native value is outside what ECCO accepts ("+o.error+") and cannot be adopted; keep the intended value.");n.value=n.external.value,n.source="native",n.observed=n.external.value,n.state="APPLIED_VERIFIED"}else n.state="PROPOSED";return n.external=null,n.revision=i(),{ok:!0,settings:e,updates:ee(r.path,n,"value")}}default:return C(t,"Unknown action.")}}function Nr(t,r){let e=Tt.length-1;for(let n of r)e=Math.min(e,Tt.indexOf(t.fields[n].state));return Tt[e]??"MISMATCH"}function ye(t){if(!Array.isArray(t)||t.length!==f.slots)return{ok:!1,why:"the table does not have six slots"};for(let e of t){if(!e||!Ne(e.startMin))return{ok:!1,why:"a slot start is unreadable or off the 5-minute grid"};if(e.source!=="Grid"&&e.source!=="None")return{ok:!1,why:"a slot has an unknown charge source"};if(!Number.isFinite(e.powerW)||!Number.isFinite(e.targetSoc))return{ok:!1,why:"a slot power or target SOC is unreadable"}}let r=0;for(let e=0;e<f.slots;e++){let n=t[e].startMin,i=t[(e+1)%f.slots].startMin,o=L(n,i);if(o<f.minSlotMin)return{ok:!1,why:"slot "+(e+1)+" is shorter than 5 minutes"};r+=o}return r!==1440?{ok:!1,why:"the six starts are not one 24-hour cycle in slot order"}:{ok:!0}}function $t(t,r){return t.startMin===r.startMin&&t.powerW===r.powerW&&t.targetSoc===r.targetSoc&&t.source===r.source}function Or(t,r){return t.length===r.length&&t.every((e,n)=>$t(e,r[n]))}var Fe=1440/5,Fr=t=>t.source+"|"+t.powerW+"|"+t.targetSoc;function oi(t){let r=[];for(let e=0;e<Fe;e++){let n=e*5,i=t[0];for(let o=0;o<t.length;o++){let a=t[o],s=t[(o+1)%t.length];if(L(a.startMin,n)<L(a.startMin,s.startMin)){i=a;break}}r.push({powerW:i.powerW,targetSoc:i.targetSoc,source:i.source,from:null})}return r}function j(t,r,e,n={}){let i=t.baseline.map(o=>({...o}));return{status:r,reasons:e,slots:i,slotReports:Ur(i,i.map(()=>"native-fallback"),t.observed??null),fallback:!0,edits:[],intervals:[],refused:[],slotsNeeded:0,deferredToAfterClockChange:!1,...n}}function Ur(t,r,e){return t.map((n,i)=>{let o=e&&e.length===t.length?e[i]:null,a=o===null?"PROPOSED":$t(o,n)?"APPLIED_VERIFIED":"MISMATCH";return{index:i+1,intended:{...n},origin:r[i],observed:o?{...o}:null,state:a}})}function Lr(t,r){let e=[];return r.forEach((n,i)=>{let o=t&&t.length===r.length?t[i]:null,a=["startMin","powerW","targetSoc","source"];for(let s of a)(o===null||o[s]!==n[s])&&e.push({slot:i+1,field:s,from:o===null?null:o[s],to:n[s]})}),e}function ai(t){return{powerW:t.powerW,targetSoc:t.targetSoc,source:t.action==="charge"?"Grid":"None",from:t.action}}function si(t){if(t.action!=="charge"&&t.action!=="export")return"unknown action";if(!Ne(t.startMin))return t.action+" start is not on the 5-minute grid";if(!Number.isInteger(t.durationMin)||t.durationMin<f.minSlotMin||t.durationMin%5!==0)return t.action+" duration must be a multiple of 5 minutes, at least 5";if(t.durationMin>=1440)return t.action+" cannot cover the whole day";if(t.action==="export"){if(!Number.isInteger(t.targetSoc)||t.targetSoc<f.stopSocMin||t.targetSoc>f.stopSocMax)return"export Stop SOC must be "+f.stopSocMin+"-"+f.stopSocMax+" %";if(t.powerW<f.exportPowerMin||t.powerW>f.exportPowerMax)return"export power is outside "+f.exportPowerMin+"-"+f.exportPowerMax+" W"}else{if(!Number.isFinite(t.targetSoc)||t.targetSoc<f.chargeTargetMin||t.targetSoc>f.chargeTargetMax)return"charge target SOC is outside "+f.chargeTargetMin+"-"+f.chargeTargetMax+" %";if(t.powerW<f.chargePowerMin||t.powerW>f.chargePowerMax)return"charge power is outside "+f.chargePowerMin+"-"+f.chargePowerMax+" W"}return null}function li(t,r){let e=0;for(let n=0;n<t.length;n++)$t(t[n],r[n])||e++;return e}function Wr(t){let r=t.day??$r,e=Math.max(5,t.handoverGapMin??5);if(t.transactionOwner)return j(t,"REFUSED",["Single writer: "+t.transactionOwner+" owns the inverter right now; nothing is compiled until it ends and its restore is verified."]);let n=ye(t.baseline);if(!n.ok)return j(t,"REFUSED",["The native baseline is not a valid six-slot day: "+n.why+"."]);if(t.observed){let m=ye(t.observed);if(!m.ok)return j(t,"CONFLICT",["The observed inverter table is not a valid six-slot day: "+m.why+"; reconcile before planning."]);let x=t.lastApplied??t.baseline;if(!Or(t.observed,x)){let R=Lr(x,t.observed);return j(t,"CONFLICT",["The inverter table differs from "+(t.lastApplied?"what ECCO last applied":"the owner's baseline")+" ("+R.length+" field(s), first: slot "+R[0].slot+" "+R[0].field+"). It looks edited outside ECCO; review and adopt it or restore before anything is compiled."])}}let i=[],o=t.intervals.filter(m=>m.action==="export"&&t.controlLocked!==!1?(i.push({action:"export",reason:"Control is locked (grid-loss lock): every export start is refused."}),!1):!0);for(let m of o){let x=si(m);if(x)return j(t,"REFUSED",["Invalid derived interval: "+x+"."],{refused:i})}if(o.filter(m=>m.action==="charge").length>1||o.filter(m=>m.action==="export").length>1)return j(t,"REFUSED",["Only one charge and one export interval can be derived per cycle."],{refused:i});let a=o.find(m=>m.action==="charge"),s=o.find(m=>m.action==="export");if(a&&s){let m=L(s.startMin+s.durationMin,a.startMin),x=L(a.startMin+a.durationMin,s.startMin);if(L(a.startMin,s.startMin)<a.durationMin||L(s.startMin,a.startMin)<s.durationMin)return j(t,"REFUSED",["The export would overlap the charge window; the firmware refuses an export that touches a charge slot."],{refused:i});if(m<e||x<e)return j(t,"REFUSED",["Fewer than "+e+" minutes between the export and the charge window; time is needed to restore and verify."],{refused:i})}let l=!1;if(Cr(r)){for(let m of o){let x=Z(m.startMin+m.durationMin);(m.action==="export"?Ar(m.startMin,m.durationMin):m.startMin<180||x<180)&&(l=!0)}if(l)return j(t,"REFUSED",["Clock-change night: derived changes that start, end or run between 00:00 and 03:00 wait until the night is over; the native table keeps running unchanged."],{refused:i,deferredToAfterClockChange:!0})}let d=oi(t.baseline);for(let m of o){let x=ai(m);for(let R=0;R<m.durationMin;R+=5)d[(m.startMin+R)/5%Fe]={...x}}let c=[];for(let m=0;m<Fe;m++){let x=d[(m+Fe-1)%Fe];Fr(x)!==Fr(d[m])&&c.push(m*5)}c.length===0&&c.push(t.baseline[0].startMin);let u=c.length;if(u>f.slots)return j(t,"INFEASIBLE",["Six native slots are not enough: this plan needs "+u+" distinct slots (changes at "+c.map(m=>V(m)).join(", ")+") and the inverter has exactly "+f.slots+". Nothing is truncated; the native table stays as it is."],{refused:i,slotsNeeded:u,intervals:Vr(o,r)});let b=new Set(c);for(let m of t.baseline){if(c.length>=f.slots)break;b.has(m.startMin)||(c.push(m.startMin),b.add(m.startMin))}for(c.sort((m,x)=>m-x);c.length<f.slots;){let m=-1,x=0;for(let H=0;H<c.length;H++){let K=L(c[H],c[(H+1)%c.length])||1440;K>x&&(x=K,m=H)}let R=Z(c[m]+Math.floor(x/2/5)*5);c.push(R),c.sort((H,K)=>H-K)}let v=m=>d[m/5],g=c.map(m=>{let x=v(m);return{startMin:m,powerW:x.powerW,targetSoc:x.targetSoc,source:x.source}}),M=(m,x)=>{let R=L(m,x)||1440;for(let H=0;H<R;H+=5){let K=v(Z(m+H)).from;if(K)return K==="charge"?"derived:charge":"derived:export"}return"native-fallback"},k=0,N=1/0;for(let m=0;m<f.slots;m++){let x=g.map((H,K)=>g[(K+m)%f.slots]),R=li(x,t.baseline);R<N&&(N=R,k=m)}let _=g.map((m,x)=>({...g[(x+k)%f.slots]})),T=g.map((m,x)=>{let R=(x+k)%f.slots;return M(g[R].startMin,g[(R+1)%f.slots].startMin)}),A=ye(_);if(!A.ok)return j(t,"REFUSED",["Internal check failed ("+A.why+"); the native table stays as it is."],{refused:i});let le=Or(_,t.baseline);return{status:"OK",reasons:i.map(m=>m.reason),slots:_,slotReports:Ur(_,T,t.observed??null),fallback:le,edits:Lr(t.observed??t.baseline,_),intervals:Vr(o,r),refused:i,slotsNeeded:u,deferredToAfterClockChange:!1}}function Vr(t,r){return t.map(e=>({action:e.action,startMin:e.startMin,wallMin:e.durationMin,elapsedMin:Qe(e.startMin,e.durationMin,r)}))}var ge=["hold_battery","skip_tonight","prepare_power_cut"];function Hr(t,r,e,n){if(!ge.includes(t))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(!Number.isFinite(r))return{ok:!1,error:"The current time is unknown; an override cannot be started without it.",code:"TIME_UNKNOWN"};let i=e??n.defaultExpiryMin[t];if(typeof i!="number"||!Number.isFinite(i))return{ok:!1,error:"An override needs an expiry; there is no open-ended override.",code:"EXPIRY_MISSING"};if(i<n.minExpiryMin)return{ok:!1,error:"The expiry must be at least "+n.minExpiryMin+" minutes.",code:"EXPIRY_BELOW_MIN"};let o=n.maxExpiryMin[t];if(i>o)return{ok:!1,error:"The expiry can be at most "+o+" minutes for this override.",code:"EXPIRY_ABOVE_CAP"};let a={kind:t,startedAtMin:r,expiresAtMin:r+i};if(t==="prepare_power_cut"){let s=n.powerCutReservePct;if(!Number.isFinite(s)||s<f.reserveMin||s>f.reserveMax)return{ok:!1,error:"The power-cut reserve must be "+f.reserveMin+"-"+f.reserveMax+" %.",code:"POWER_CUT_RESERVE_RANGE"};a.reservePct=s}return{ok:!0,override:a}}var Le={min_expiry:{min:5,max:60,step:5,unit:"min"},hold_default:{min:5,max:4320,step:5,unit:"min"},hold_cap:{min:5,max:4320,step:5,unit:"min"},skip_until:{min:180,max:1435,step:5,unit:"minute of day"},skip_cap:{min:5,max:2160,step:5,unit:"min"},cut_default:{min:5,max:10080,step:5,unit:"min"},cut_cap:{min:5,max:10080,step:5,unit:"min"},cut_reserve:{min:10,max:100,step:1,unit:"%"},revision:{min:0,max:1e9,step:1,unit:""}},ae=Object.freeze({hold_battery:Le.hold_cap.max,skip_tonight:Le.skip_cap.max,prepare_power_cut:Le.cut_cap.max}),te=Object.freeze({hold_battery:"Hold battery",skip_tonight:"Skip tonight",prepare_power_cut:"Prepare for power cut"}),ci=[{key:"minExpiryMin",bound:"min_expiry",label:"Shortest allowed override"},{key:"holdDefaultMin",bound:"hold_default",label:"Hold battery default"},{key:"holdCapMin",bound:"hold_cap",label:"Hold battery maximum"},{key:"skipUntilMin",bound:"skip_until",label:"Skip tonight ends at"},{key:"skipCapMin",bound:"skip_cap",label:"Skip tonight maximum"},{key:"cutDefaultMin",bound:"cut_default",label:"Prepare for power cut default"},{key:"cutCapMin",bound:"cut_cap",label:"Prepare for power cut maximum"},{key:"cutReservePct",bound:"cut_reserve",label:"Power-cut reserve"}];function re(t){if(typeof t!="number"||!Number.isFinite(t)||t<0)return"unknown";let r=Math.round(t);if(r<60)return r+" min";let e=Math.floor(r/1440),n=Math.floor((r-e*1440)/60),i=r%60,o=[];return e>0&&o.push(e+(e===1?" day":" days")),n>0&&o.push(n+" h"),i>0&&o.push(i+" min"),o.join(" ")}function Br(t,r){if(t.bound==="skip_until")return V(r);let e=Le[t.bound];return e.unit==="min"?re(r):r+" "+e.unit}function di(t,r,e){let n=Le[t.bound];return typeof r!="number"||!Number.isFinite(r)?(e.push(t.label+" is not set or cannot be read."),null):Number.isInteger(r)?r<n.min?(e.push(t.label+" must be at least "+Br(t,n.min)+"."),null):r>n.max?(e.push(t.label+" can be at most "+Br(t,n.max)+"."),null):(r-n.min)%n.step!==0?(e.push(t.label+" moves in steps of "+n.step+(n.unit==="%"?" %":" min")+"."),null):r:(e.push(t.label+" must be a whole number."),null)}function Ct(t,r={}){if(t==null||typeof t!="object")return{ok:!1,reasons:["No override limits are configured, so no override can be started."],codes:["POLICY_UNCONFIRMED"]};let e=[],n=[];t.confirmed!==!0&&e.push("The owner has not confirmed the override limits (the switch is off or cannot be read), so no override can be started.");let i={};for(let c of ci){let u=di(c,t[c.key],e);u!==null&&(i[c.key]=u)}let o=i.minExpiryMin,a=(c,u,b)=>{o!==void 0&&u!==void 0&&u<o&&e.push(c+" default is shorter than the shortest allowed override."),u!==void 0&&b!==void 0&&u>b&&e.push(c+" default is longer than its maximum.")};a("Hold battery",i.holdDefaultMin,i.holdCapMin),a("Prepare for power cut",i.cutDefaultMin,i.cutCapMin),o!==void 0&&i.skipCapMin!==void 0&&i.skipCapMin<o&&e.push("Skip tonight maximum is shorter than the shortest allowed override.");let s=i.cutReservePct;s!==void 0&&(s<f.reserveMin||s>f.reserveMax)&&e.push("The power-cut reserve must be "+f.reserveMin+"-"+f.reserveMax+" %.");let l=r.currentReservePct;if(typeof l=="number"&&Number.isFinite(l)?s!==void 0&&s<l&&e.push("The power-cut reserve ("+s+" %) is below the current backup reserve ("+l+" %); it would not raise anything."):n.push("The current backup reserve is not known, so the power-cut reserve cannot be compared with it here. An override can only raise a reserve."),e.length>0){let c=[];return t.confirmed!==!0&&c.push("POLICY_UNCONFIRMED"),e.length>c.length&&c.push("POLICY_INVALID"),{ok:!1,reasons:e,codes:c}}return{ok:!0,config:Object.freeze({minExpiryMin:i.minExpiryMin,holdDefaultMin:i.holdDefaultMin,holdCapMin:i.holdCapMin,skipUntilMin:i.skipUntilMin,skipCapMin:i.skipCapMin,cutDefaultMin:i.cutDefaultMin,cutCapMin:i.cutCapMin,cutReservePct:i.cutReservePct}),warnings:n}}function ui(t){return!!t&&(t.deltaMin===0||t.deltaMin===60||t.deltaMin===-60)&&Number.isInteger(t.changeAtMin)&&t.changeAtMin>=0&&t.changeAtMin<1440}function Kr(t,r,e){if(!Number.isInteger(t)||t<0||t>=1440)return{ok:!1,error:"The local time is unknown."};if(!Number.isInteger(r)||r<0||r>=1440)return{ok:!1,error:"The end time is not a time of day."};if(!ui(e))return{ok:!1,error:"The clock-change information is not valid."};let n=L(t,r),i=n===0?1440:n,o=Qe(t,i,e);return o>0?{ok:!0,wallMin:i,expiryMin:o}:{ok:!1,error:"The end time is not in the future."}}function pi(t,r){let e=NaN;if(r){let n=Kr(r.nowWallMin,t.skipUntilMin,r.day);n.ok&&(e=n.expiryMin)}return{minExpiryMin:t.minExpiryMin,defaultExpiryMin:{hold_battery:t.holdDefaultMin,skip_tonight:e,prepare_power_cut:t.cutDefaultMin},maxExpiryMin:{hold_battery:t.holdCapMin,skip_tonight:t.skipCapMin,prepare_power_cut:t.cutCapMin},powerCutReservePct:t.cutReservePct}}var hi=[30,60,120,240,480,720,1440,2880,4320,10080];function zr(t,r,e){let n=t==="hold_battery"?r.holdCapMin:t==="skip_tonight"?r.skipCapMin:r.cutCapMin,i=t==="hold_battery"?r.holdDefaultMin:t==="prepare_power_cut"?r.cutDefaultMin:null,o=new Set;for(let s of hi)s>=r.minExpiryMin&&s<=n&&o.add(s);i!==null&&o.add(i),o.add(n);let a=[...o].filter(s=>s>=r.minExpiryMin&&s<=n).map(s=>({id:"d"+s,label:re(s),expiryMin:s,untilMin:null,isDefault:i===s}));if((t==="hold_battery"||t==="skip_tonight")&&e){let s=Kr(e.nowWallMin,r.skipUntilMin,e.day);s.ok&&s.expiryMin>=r.minExpiryMin&&s.expiryMin<=n&&a.push({id:"until",label:"until "+V(r.skipUntilMin),expiryMin:s.expiryMin,untilMin:r.skipUntilMin,isDefault:t==="skip_tonight"})}return a.sort((s,l)=>s.expiryMin-l.expiryMin||s.id.localeCompare(l.id))}function Gr(t,r,e,n,i){if(!n||n.ok!==!0||!n.config)return{ok:!1,error:"The override limits are not valid, so no override can be started."+(n&&n.ok===!1&&n.reasons.length?" "+n.reasons.join(" "):""),code:n&&n.ok===!1&&n.codes&&n.codes[0]||"POLICY_INVALID"};let o=n.config;if(!ge.includes(t))return{ok:!1,error:"Unknown override.",code:"UNKNOWN_KIND"};if(e!=null&&(typeof e!="number"||!Number.isInteger(e)))return{ok:!1,error:"The expiry must be a whole number of minutes.",code:"EXPIRY_NOT_WHOLE"};if(t==="prepare_power_cut"){let l=i.currentReservePct;if(typeof l!="number"||!Number.isFinite(l))return{ok:!1,error:"The current backup reserve is not known, so it cannot be shown that the power-cut reserve raises it.",code:"RESERVE_UNKNOWN"};if(o.cutReservePct<l)return{ok:!1,error:"The power-cut reserve ("+o.cutReservePct+" %) is below the current backup reserve ("+l+" %); an override never lowers a reserve.",code:"RESERVE_BELOW_CURRENT"}}let a=Hr(t,r,e,pi(o,i.clock));if(!a.ok)return a;let s=a.override.expiresAtMin-a.override.startedAtMin;return!(s>0)||!(s<=ae[t])?{ok:!1,error:"The expiry is beyond the hard ceiling of "+re(ae[t])+".",code:"EXPIRY_ABOVE_CEILING"}:a}var mi=[{key:"minExpiryMin",value:15,why:"Under a quarter hour is almost certainly a mis-tap and would make the plan flicker."},{key:"holdDefaultMin",value:240,why:"Covers an evening of extra use (cooking, guests) without outliving it."},{key:"holdCapMin",value:1440,why:"A forgotten hold costs at most one night of export; two days needs a deliberate restart."},{key:"skipUntilMin",value:420,why:"Skips tonight's export and the overnight charge, then planning resumes before the morning sun."},{key:"skipCapMin",value:1440,why:"Skip is a one-night action; a day is the most it needs."},{key:"cutDefaultMin",value:1440,why:"Most warnings and outages are shorter than a day; extending is a conscious step."},{key:"cutCapMin",value:4320,why:"Matches the design example of 72 h; a raised reserve only costs forgone export."},{key:"cutReservePct",value:80,why:"Hours of essential load while still leaving room for solar; the design example."}],jr=Object.freeze(mi.map(t=>Object.freeze({...t})));var fi=["HIGH","MEDIUM","LOW","INSUFFICIENT"];function Ze(t){return{known:!1,reason:t,state:"PROPOSED"}}function At(t,r){if(!t)return Ze("No Intelligence advice is available.");let e=t[r];return e==null?Ze("Intelligence did not provide this."):typeof e!="number"||!Number.isFinite(e)||e<0?Ze("Intelligence provided a value that is not a valid amount."):{known:!0,value:e,state:"PROPOSED",origin:"intelligence",simulated:!1}}var gi=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"];function Yr(t){let{advice:r,settings:e,chargePlan:n}=t,i=[],o="UNKNOWN";r&&typeof r.confidence=="string"&&fi.includes(r.confidence)&&(o=r.confidence);let a={known:o!=="UNKNOWN",level:o,state:"PROPOSED"},s,l=r?.chargeFinishMin;if(typeof l=="number"&&Number.isFinite(l)&&l>=0&&l<1440)s={known:!0,value:Math.round(l),state:"PROPOSED",origin:"intelligence",simulated:!1};else if(n&&(n.status==="OK"||n.status==="BUFFER_TOO_SMALL")&&n.finishNominalMin!==null){let v=e.fields["charge.windowStartMin"].value;s={known:!0,value:Z(v+n.finishNominalMin),state:Nr(e,gi),origin:"planner",simulated:!0},n.status==="BUFFER_TOO_SMALL"&&i.push({origin:"planner",text:"Buffer too small: the stress case overruns the charge window (simulated, not measured)."})}else s=Ze(n&&n.status==="NOTHING_TO_CHARGE"?"No overnight charge is expected to be needed.":"No finish time is available from advice or the planner.");let d=e.fields["reserve.backupPct"],c={known:!0,value:d.value,state:d.state,origin:"settings",simulated:!1};if(r&&Array.isArray(r.why))for(let v of r.why.slice(0,8))typeof v=="string"&&v.trim()&&i.push({origin:"advice",text:v.trim().slice(0,200)});let u=e.fields["charge.targetSoc"];i.push({origin:"settings",text:"Charge target "+u.value+" % ("+u.source+", revision "+u.revision+", "+u.state+")."});let b=e.fields["export.stopSoc"];return i.push({origin:"settings",text:"Export stops at "+b.value+" % ("+b.source+", revision "+b.revision+", "+b.state+")."}),i.push({origin:"settings",text:"Backup reserve "+d.value+" % ("+d.source+", "+d.state+")."}),a.known?o!=="HIGH"&&i.push({origin:"advice",text:"Confidence is "+o+": ECCO holds rather than acts on this forecast."}):i.push({origin:"advice",text:"Confidence is unknown, so nothing here is presented as a firm forecast."}),{importKwh:At(r,"expectedImportKwh"),exportKwh:At(r,"expectedExportKwh"),solarKwh:At(r,"expectedSolarKwh"),chargeFinishMin:s,reservePct:c,confidence:a,why:i}}var bi=Object.freeze({status:"sensor.ecco_intel_status",charge_target:"sensor.ecco_intel_charge_target",export_event:"sensor.ecco_intel_export_event",pv_tomorrow:"sensor.ecco_intel_pv_tomorrow",fresh:"binary_sensor.ecco_intel_fresh",paused:"input_boolean.ecco_intel_paused"}),vi=6,_i=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/,xi=/^(\d{2}):(\d{2})$/,wi=/^\d{4}-\d{2}-\d{2} (\d{2}):(\d{2}):\d{2}$/;function W(t,r){if(!r)return null;let e=t[r]?.state;return typeof e!="string"||e===""||e==="unavailable"||e==="unknown"?null:e}function E(t,r){let e=W(t,r);if(e===null)return null;let n=e.trim();if(!_i.test(n))return null;let i=Number(n);return Number.isFinite(i)?i:null}var U=(t,r)=>W(t,r)==="on";function yi(t){if(t===null)return null;let r=xi.exec(t.trim());if(!r)return null;let e=Number(r[1]),n=Number(r[2]);return e>23||n>59?null:e*60+n}function qr(t){if(t===null)return null;let r=wi.exec(t.trim());if(!r)return null;let e=Number(r[1]),n=Number(r[2]);return e>23||n>59?null:e*60+n}function Si(t,r){let e=`sensor.${t}_ecco_timezone${r}_`;return{time:`${e}time`,power:`${e}power`,soc:`${e}soc`,charge:`${e}charge`}}function ki(t){return{fpActive:`binary_sensor.${t}_free_power_active`,fpOp:`binary_sensor.${t}_free_power_operation_in_progress`,fpSnapshot:`binary_sensor.${t}_free_power_snapshot_valid`,dgActive:`binary_sensor.${t}_dump_to_grid_active`,dgOp:`binary_sensor.${t}_dump_to_grid_operation_in_progress`,dgSnapshot:`binary_sensor.${t}_dump_to_grid_snapshot_valid`}}function It(t,r){let e=t[r]?.attributes;return e&&typeof e=="object"?e:{}}function Xr(t){return typeof t=="number"&&Number.isFinite(t)?t:null}function Ei(t,r){let e=g=>({advice:null,available:!1,note:g,chargeTargetPct:null}),n=W(t,r.status);if(n===null)return e("The Intelligence advice is not available (its status cannot be read).");if(U(t,r.paused))return e("Intelligence is paused by the owner; it publishes no advice.");if(n!=="OK")return e("Intelligence status is "+n+"; it publishes no figures.");if(W(t,r.fresh)!=="on")return e("The Intelligence advice is not fresh; it is not shown as a forecast.");let i=r.charge_target,o=It(t,i).advice,a=o&&typeof o=="object"&&!Array.isArray(o)?o:{},s=It(t,i).confidence,l=[],d=E(t,i),c=a.binding_constraint;d!==null&&l.push("Charge target advice "+d+" %"+(typeof c=="string"?" (limited by "+c.toLowerCase().replace(/_/g," ")+")":"")+"."),a.conservative_fallback===!0&&l.push("Not enough demand evidence yet, so Intelligence advises keeping the battery well charged.");let u=Xr(a.net_need_kwh);u!==null&&l.push("Net overnight need after solar credit: "+u.toFixed(1)+" kWh.");let b=It(t,i).blockers;if(Array.isArray(b))for(let g of b.slice(0,4)){let M=g&&typeof g=="object"?g.text:null;typeof M=="string"&&M.trim()&&l.push("Blocked: "+M.trim())}return l.push("Import is the grid energy Intelligence plans for the overnight charge; it does not include daytime import."),{advice:{expectedImportKwh:Xr(a.grid_charge_kwh),expectedExportKwh:E(t,r.export_event),expectedSolarKwh:E(t,r.pv_tomorrow),chargeFinishMin:null,confidence:typeof s=="string"?s:null,why:l},available:!0,note:null,chargeTargetPct:d}}function Pi(t,r){let e=[],n=[];for(let o=1;o<=vi;o++){let a=Si(r,o),s=yi(W(t,a.time)),l=E(t,a.power),d=E(t,a.soc),c=W(t,a.charge),u=[];s===null&&u.push("start time"),l===null&&u.push("power"),d===null&&u.push("target SOC"),c!=="Grid"&&c!=="None"&&u.push("charge source"),u.length?n.push("slot "+o+" "+u.join(", ")):e.push({startMin:s,powerW:l,targetSoc:d,source:c})}if(n.length)return{table:null,reason:"The six TOU slots cannot all be read ("+n.join("; ")+"), so no comparison is possible."};let i=ye(e);return i.ok?{table:e,reason:null}:{table:null,reason:"The inverter's six slots are not a valid six-slot day ("+i.why+"), so no comparison is made."}}function ne(t,r,e,n=null){if(r===null)return{value:null,reason:e,observed:null};let i=Oe(t,r);return i.ok?{value:i.value,reason:"",observed:n}:{value:null,reason:"The value "+r+" is outside what ECCO accepts ("+i.error+")",observed:null}}function Qr(t,r){let e=t.plan??{},n=t.free_power,i=t.schedule,o=t.dump_to_grid,a=o?.schedule,s=e.entity_prefix,l={...bi,...e.advice??{}},d=Ei(r,l),c=s?Pi(r,s):{table:null,reason:"No TOU slot prefix is configured (plan.entity_prefix), so the six slots are not read."},u=c.table,b=u?u.filter(S=>S.source==="Grid"):[],v=b.length===1?b[0]:null,g={};for(let S of we)g[S]={value:null,reason:"This card has no entity for it.",observed:null};let M=i?qr(W(r,i.start)):null,k=i?E(r,i.duration):null,N=i?E(r,i.power):n?E(r,n.max_charge_power):null;g["charge.powerW"]=ne("charge.powerW",N,"The charge power cannot be read."),g["charge.windowStartMin"]=ne("charge.windowStartMin",M,i?"The scheduled charge start cannot be read.":"No schedule is configured, so there is no charge window.");let _=null;M!==null&&k!==null&&Number.isInteger(k)&&k>0&&k<1440&&(_=(M+k)%1440),g["charge.windowEndMin"]=ne("charge.windowEndMin",_,i?"The scheduled charge end cannot be worked out (start or duration unreadable, or not on the 5-minute grid).":"No schedule is configured, so there is no charge window."),g["charge.targetSoc"]=ne("charge.targetSoc",v?v.targetSoc:null,"The charge target is not stated: the inverter table has no single grid-charge slot to read it from.",v?v.targetSoc:null),g["charge.bufferMin"]={value:null,reason:"No finish-before-window-end buffer is set by any entity this card reads.",observed:null};let T=o?U(r,o.active):!1,A=a?E(r,a.power):o?E(r,o.export_power):null,le=a?E(r,a.stop_soc):o?E(r,o.stop_soc):null,m=o&&T?E(r,o.active_export_power):null,x=o&&T?E(r,o.active_stop_soc):null,R=a?qr(W(r,a.start)):null,H=a?E(r,a.duration):o?E(r,o.duration):null;g["export.powerW"]=ne("export.powerW",A,"The export power cannot be read.",m),g["export.stopSoc"]=ne("export.stopSoc",le,"The Stop SOC cannot be read.",x),g["export.startMin"]=ne("export.startMin",R,a?"The scheduled export start cannot be read.":"No export schedule is configured, so there is no export start time."),g["export.durationMin"]=ne("export.durationMin",H,"The export duration cannot be read."),g["reserve.backupPct"]=ne("reserve.backupPct",e.reserve?E(r,e.reserve):null,e.reserve?"The backup reserve cannot be read.":"No backup reserve entity is configured (plan.reserve)."),g["reserve.planningPct"]={value:null,reason:"Intelligence's planning reserve is not read by this card.",observed:null};let K={};for(let S of we)K[S]=g[S].value!==null?g[S].value:q[S].min;let Y=Ir(K,"owner"),Ut=i?U(r,i.armed):!1,tt=n?U(r,n.active):!1,Wt=a?U(r,a.armed):!1,mn=["charge.targetSoc","charge.bufferMin","charge.powerW","charge.windowStartMin","charge.windowEndMin"],fn=["export.stopSoc","export.powerW","export.startMin","export.durationMin"],rt=(S,$)=>{let O=Je(Y,{type:$,path:S});O.ok&&(Y=O.settings)},Ht=(S,$,O)=>{for(let F of S)g[F].value!==null&&(O?(rt(F,"arm"),rt(F,"begin")):$&&rt(F,"arm"))};Ht(mn,Ut,tt),Ht(fn,Wt,T);for(let S of we){let $=g[S];if($.value===null||$.observed===null)continue;let O=Je(Y,{type:"readback",path:S,observed:$.observed});O.ok&&(Y=O.settings)}let Bt=null;if(d.chargeTargetPct!==null&&g["charge.targetSoc"].value!==null&&d.chargeTargetPct!==g["charge.targetSoc"].value){let S=Je(Y,{type:"edit",path:"charge.targetSoc",value:d.chargeTargetPct,source:"intelligence"});S.ok&&(Y=S.settings,Bt=Y.fields["charge.targetSoc"].proposal?.value??null)}let Kt=we.map(S=>{let $=g[S],O=Y.fields[S],F=q[S];return{path:S,label:F.label,unit:F.unit,known:$.value!==null,...$.value===null?{reason:$.reason}:{},value:O.value,state:O.state,source:O.source,observed:O.observed,proposal:S==="charge.targetSoc"?Bt:null}}),Ue=[],zt=null;if(u){let S=[],$=X=>g[X].value;if(Ut||tt){let X=$("charge.windowStartMin"),Se=$("charge.powerW"),be=$("charge.targetSoc");X===null||k===null||Se===null||be===null?Ue.push("The armed charge could not be placed in the table: "+(be===null?"its target SOC is unknown.":"its start, duration or power is unreadable.")):S.push({action:"charge",startMin:X,durationMin:k,targetSoc:be,powerW:Se})}if(Wt||T){let X=$("export.startMin"),Se=$("export.powerW"),be=$("export.stopSoc"),jt=$("export.durationMin");X===null||Se===null||be===null||jt===null?Ue.push("The armed export could not be placed in the table: a start, duration, power or Stop SOC is unreadable."):S.push({action:"export",startMin:X,durationMin:jt,targetSoc:be,powerW:Se})}let O=null,F=s?ki(s):null;F&&(U(r,F.fpActive)||U(r,F.fpOp)||U(r,F.fpSnapshot))||tt||n&&(U(r,n.operation_in_progress)||U(r,n.snapshot_valid))?O="Free Power":(F&&(U(r,F.dgActive)||U(r,F.dgOp)||U(r,F.dgSnapshot))||T||o&&(U(r,o.operation_in_progress)||U(r,o.snapshot_valid)))&&(O="Dump to Grid");let Gt=e.control_lock?W(r,e.control_lock)==="off":!1;!Gt&&S.some(X=>X.action==="export")&&Ue.push(e.control_lock?"Control is locked or its state is unreadable, so the export is not placed in the table (fail-safe).":"No grid-loss lock state is configured (plan.control_lock), so an export is not placed in the table (fail-safe)."),zt=Wr({baseline:u,intervals:S,observed:u,lastApplied:null,transactionOwner:O,controlLocked:!Gt})}let gn=Mi(Yr({advice:d.advice,settings:Y}),Kt,d);return{settings:Y,fields:Kt,tomorrow:gn,tou:{readable:u!==null,reason:c.reason,observed:u,compile:zt,notes:Ue},overrides:[],adviceAvailable:d.available,adviceNote:d.note}}function Mi(t,r,e){let n=s=>r.find(l=>l.path===s)?.known===!0,i=t.why.filter(s=>s.origin!=="settings"?!0:s.text.startsWith("Charge target ")?n("charge.targetSoc"):s.text.startsWith("Export stops at ")?n("export.stopSoc"):s.text.startsWith("Backup reserve ")?n("reserve.backupPct"):!0);n("charge.targetSoc")||i.push({origin:"settings",text:"Charge target: unknown (no single grid-charge slot to read it from)."}),n("export.stopSoc")||i.push({origin:"settings",text:"Export Stop SOC: unknown (not readable)."}),n("reserve.backupPct")||i.push({origin:"settings",text:"Backup reserve: unknown (no entity configured or readable)."});let o=s=>!s.known&&e.note?{...s,reason:e.note}:s,a=t.reservePct.known&&!n("reserve.backupPct")?{known:!1,reason:r.find(s=>s.path==="reserve.backupPct")?.reason??"Unknown.",state:"PROPOSED"}:t.reservePct;return{...t,why:i,importKwh:o(t.importKwh),exportKwh:o(t.exportKwh),solarKwh:o(t.solarKwh),chargeFinishMin:o(t.chargeFinishMin),reservePct:a}}var B={confirmed:"input_boolean.ecco_plan_overrides_enabled",revision:"input_number.ecco_plan_revision",min_expiry:"input_number.ecco_plan_policy_min_expiry",hold_default:"input_number.ecco_plan_policy_hold_default",hold_cap:"input_number.ecco_plan_policy_hold_cap",skip_until:"input_datetime.ecco_plan_policy_skip_until",skip_cap:"input_number.ecco_plan_policy_skip_cap",cut_default:"input_number.ecco_plan_policy_cut_default",cut_cap:"input_number.ecco_plan_policy_cut_cap",cut_reserve:"input_number.ecco_plan_policy_cut_reserve",hold_battery_start:"input_datetime.ecco_plan_override_hold_battery_start",hold_battery_expires:"input_datetime.ecco_plan_override_hold_battery_expires",skip_tonight_start:"input_datetime.ecco_plan_override_skip_tonight_start",skip_tonight_expires:"input_datetime.ecco_plan_override_skip_tonight_expires",prepare_power_cut_start:"input_datetime.ecco_plan_override_prepare_power_cut_start",prepare_power_cut_expires:"input_datetime.ecco_plan_override_prepare_power_cut_expires",prepare_power_cut_reserve:"input_number.ecco_plan_override_prepare_power_cut_reserve"},Ri=/^(\d{2}):(\d{2})(?::(\d{2}))?$/,Di=/^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2}$/;function Ti(t){if(t===null)return null;let r=Ri.exec(t.trim());if(!r)return null;let e=Number(r[1]),n=Number(r[2]),i=r[3]===void 0?0:Number(r[3]);return e>23||n>59||i>59?null:e*60+n+i/60}function $i(t,r){let e=W(t,r);return e==="on"?!0:e==="off"?!1:null}function Jr(t,r,e){let n=W(t,r);if(n===null)return{ok:!1,reason:e+" cannot be read."};let i=Di.exec(n.trim());if(!i)return{ok:!1,reason:e+" is not a date and time."};let o=t[r]?.attributes?.timestamp;return typeof o!="number"||!Number.isFinite(o)?{ok:!1,reason:e+" has no timestamp, so its moment cannot be placed."}:{ok:!0,min:Math.round(o/60),text:i[1]+" "+i[2]+":"+i[3]}}function Ci(t,r,e){let n=[];if(r===null)return e.push("The current time is not known, so stored override records cannot be judged."),n;for(let i of ge){let o=te[i],a=B[i+"_start"],s=B[i+"_expires"],l=Jr(t,s,o+" expiry");if(!l.ok){e.push(l.reason);continue}if(l.min<=r)continue;let d=Jr(t,a,o+" start");if(!d.ok){e.push(d.reason+" The record is not trusted.");continue}let c=l.min-d.min;if(!(c>0)){e.push(o+" starts at or after its expiry. The record is not trusted.");continue}if(c>ae[i]){e.push(o+" lasts longer than its hard ceiling. The record is not trusted.");continue}let u={kind:i,startedAtMin:d.min,expiresAtMin:l.min};if(i==="prepare_power_cut"){let b=E(t,B.prepare_power_cut_reserve);if(b===null||!Number.isInteger(b)||b<f.reserveMin||b>f.reserveMax){e.push(o+" has no readable reserve inside "+f.reserveMin+"-"+f.reserveMax+" %. The record is not trusted.");continue}u.reservePct=b}n.push({override:u,label:o,expiresText:l.text,remainingMin:Math.max(1,l.min-r)})}return n}function Ai(t){let r=E(t,B.revision);return r===null?{known:!1,value:null,reason:"The stored plan revision cannot be read."}:!Number.isInteger(r)||r<0?{known:!1,value:null,reason:"The stored plan revision is not a whole number."}:{known:!0,value:r,reason:""}}function Ii(t,r,e,n=null){let i=Object.values(B),o=i.filter(b=>t[b]===void 0);if(o.length===i.length)return null;let a=$i(t,B.confirmed),s={confirmed:a,minExpiryMin:E(t,B.min_expiry),holdDefaultMin:E(t,B.hold_default),holdCapMin:E(t,B.hold_cap),skipUntilMin:Ti(W(t,B.skip_until)),skipCapMin:E(t,B.skip_cap),cutDefaultMin:E(t,B.cut_default),cutCapMin:E(t,B.cut_cap),cutReservePct:E(t,B.cut_reserve)},l=Ct(s,{currentReservePct:e}),d=Ct(s),c=[],u=Ci(t,r,c);return{missing:o,confirmed:a,policy:l,startPolicy:d,socPct:n,revision:Ai(t),active:u,problems:c,nowMin:r}}function Zr(t,r,e){let n=Qr(t,r),i=n.fields.find(l=>l.path==="reserve.backupPct"),o=t.plan?.battery_soc??t.dump_to_grid?.battery_soc,a=o?E(r,o):null,s=Ii(r,e,i&&i.known?i.value:null,a);return s?{...n,overrides:s.active.map(l=>l.override),helpers:s}:{...n,helpers:null}}var Ve=Object.freeze({PROPOSED:{kind:"PROPOSED",label:"Proposed",icon:"mdi:lightbulb-outline",meaning:"Proposed: shown for review, not armed and not applied."},ARMED:{kind:"ARMED",label:"Armed",icon:"mdi:shield-check-outline",meaning:"Armed: scheduled and waiting to start, not yet running."},EXECUTING:{kind:"EXECUTING",label:"Executing",icon:"mdi:progress-clock",meaning:"Executing: a session is running now and no read-back has confirmed this value yet."},APPLIED_VERIFIED:{kind:"APPLIED_VERIFIED",label:"Applied and verified",icon:"mdi:check-circle-outline",meaning:"Applied and verified: a read-back from the system equals this value."},MISMATCH:{kind:"MISMATCH",label:"Mismatch",icon:"mdi:alert-circle-outline",meaning:"Mismatch: what the system reports differs from the intended value."},UNKNOWN:{kind:"UNKNOWN",label:"Unknown",icon:"mdi:help-circle-outline",meaning:"Unknown: this cannot be read, so no value is shown."}}),Ni="SHADOW / advice only. Nothing shown here is applied by this view: it displays what Home Assistant, the inverter and Intelligence report, and it writes nothing.",Oi="Quick overrides: none active. Shown as status only; starting one needs a plan helper that does not exist yet.",Fi="Quick overrides: none active. Shown as status only; starting one needs the guarded start path, which is not installed.",Li="Status only: nothing in this view starts, cancels or enforces an override. An override can only hold back a start or raise a reserve; it never writes the inverter's table and never stops a running session.";function Ft(t,r){return"The battery is at "+Math.round(t)+" percent, below the "+Math.round(r)+" percent reserve. Nothing is charging. Use Charge Battery if you want it filled."}var Vi={HIGH:"High",MEDIUM:"Medium",LOW:"Low",INSUFFICIENT:"Insufficient evidence"},Nt=t=>t.toFixed(1)+" kWh";function Ot(t){return Ve[t]}function en(t){return`${V(t.startMin)} ${t.source==="Grid"?"charge from grid":"no grid charge"}, ${t.powerW} W, to ${t.targetSoc} %`}var Ui=t=>"time"in q[t.path];function tn(t,r){return Ui(t)?V(r):t.unit?`${r} ${t.unit}`:String(r)}function Wi(t){if(!t.known)return{path:t.path,label:t.label,known:!1,text:"Unknown",reason:t.reason??"Not readable.",chip:Ve.UNKNOWN,remarks:[]};let r=[],e=n=>tn(t,n);return t.observed!==null&&t.observed!==t.value&&r.push(`The system reports ${e(t.observed)}, not ${e(t.value)}.`),t.proposal!==null&&r.push(`Intelligence suggests ${e(t.proposal)} (not adopted; nothing here changes it).`),t.state==="PROPOSED"&&t.observed===null&&r.push("No read-back is available for this value."),{path:t.path,label:t.label,known:!0,text:tn(t,t.value),reason:"",chip:Ot(t.state),remarks:r}}function Hi(t){let r=t.intended,e=t.observed;if(!e)return null;let n=[];return r.startMin!==e.startMin&&n.push(`start ${V(r.startMin)} intended, ${V(e.startMin)} on the inverter`),r.source!==e.source&&n.push(`charge source ${r.source} intended, ${e.source} on the inverter`),r.powerW!==e.powerW&&n.push(`power ${r.powerW} W intended, ${e.powerW} W on the inverter`),r.targetSoc!==e.targetSoc&&n.push(`target ${r.targetSoc} % intended, ${e.targetSoc} % on the inverter`),n.length?`Slot ${t.index} differs from the inverter: ${n.join("; ")}. It is not applied there, and this view does not apply it.`:null}var Bi={"native-fallback":"Native (unchanged)","derived:charge":"Derived from the charge plan","derived:export":"Derived from the export plan"},Ki={OK:"Compiled",INFEASIBLE:"Does not fit six slots",CONFLICT:"Conflict with a manual change",REFUSED:"Not compiled"};function zi(t){let r=t.tou;if(!r.readable||!r.compile)return{readable:!1,headline:r.reason??"The six slots cannot be read.",statusText:null,reasons:[...r.notes],slots:[],mismatchCount:0};let e=r.compile,n=e.slotReports.map((s,l)=>{let d=e.slotReports[(l+1)%e.slotReports.length],c=s.state==="MISMATCH"?Hi(s):null,u=s.state==="APPLIED_VERIFIED"?"APPLIED_VERIFIED":s.state==="MISMATCH"?"MISMATCH":"PROPOSED";return{index:s.index,rangeText:`${V(s.intended.startMin)} to ${V(d.intended.startMin)}`,spanMin:L(s.intended.startMin,d.intended.startMin)||1440,intendedText:en(s.intended),inverterText:s.observed?en(s.observed):null,originText:Bi[s.origin]??s.origin,chip:Ve[u],mismatch:c}}),i=n.filter(s=>s.mismatch!==null).length,o=[...new Set([...e.reasons,...r.notes])],a;return e.status==="OK"&&e.fallback?a="No armed charge or export changes the table: the six slots are as the inverter reports them.":e.status==="OK"?a=`If the armed plan were compiled, ${i} of the six slots would differ from what the inverter reports.`:e.status==="INFEASIBLE"?a="The plan does not fit the inverter's six slots. Nothing is truncated; the native table stays as it is.":e.status==="CONFLICT"?a="The inverter's table looks changed outside ECCO. Nothing is planned until that is reviewed.":a="The plan is not compiled; the native table stays as it is.",{readable:!0,headline:a,statusText:Ki[e.status]??e.status,reasons:o,slots:n,mismatchCount:i}}var Gi={hold_battery:()=>"Intended: no export starts and no discretionary rate edits; charging and the inverter table are untouched.",skip_tonight:()=>"Intended: tonight's export is held; charging continues.",prepare_power_cut:t=>`Intended: the reserve is raised to ${t??"?"} % (never lowered) and export starts are held.`};function ji(){let t=(e,n)=>e==="skipUntilMin"?V(n):e==="cutReservePct"?`${n} %`:re(n),r={minExpiryMin:"Shortest allowed override",holdDefaultMin:"Hold battery default",holdCapMin:"Hold battery maximum",skipUntilMin:"Skip tonight ends at",skipCapMin:"Skip tonight maximum",cutDefaultMin:"Prepare for power cut default",cutCapMin:"Prepare for power cut maximum",cutReservePct:"Power-cut reserve"};return jr.map(e=>`${r[e.key]??e.key}: ${t(e.key,e.value)}. ${e.why}`)}function Yi(t){let r=e=>re(e);return`Limits set by you: ${te.hold_battery} default ${r(t.holdDefaultMin)}, up to ${r(t.holdCapMin)}; ${te.skip_tonight} until ${V(t.skipUntilMin)}, up to ${r(t.skipCapMin)}; ${te.prepare_power_cut} default ${r(t.cutDefaultMin)}, up to ${r(t.cutCapMin)}, reserve ${t.cutReservePct} %. Hard ceilings no setting can exceed: ${r(ae.hold_battery)}, ${r(ae.skip_tonight)}, ${r(ae.prepare_power_cut)}.`}function qi(t){let r=t.policy,e=t.active.map(i=>({kind:i.override.kind,label:i.label,untilText:`until ${i.expiresText}`,countdownText:`ends in ${re(i.remainingMin)}`,effectText:Gi[i.override.kind](i.override.reservePct),belowReserve:i.override.kind==="prepare_power_cut"&&typeof i.override.reservePct=="number"&&t.socPct!==null&&t.socPct<i.override.reservePct?Ft(t.socPct,i.override.reservePct):null})),n=t.revision.known?t.revision.value===0?"Plan revision: none recorded yet.":`Plan revision ${t.revision.value} (stored in the plan helper).`:`Plan revision: unknown (${t.revision.reason})`;return{policyOk:r.ok,policyLine:r.ok?Yi(r.config):"The override limits are not usable, so no override can be started. Nothing falls back to proposed values.",reasons:r.ok?[]:[...r.reasons],warnings:r.ok?[...r.warnings]:[],missing:[...t.missing],proposed:r.ok?[]:ji(),revisionText:n,rows:e,problems:[...t.problems],note:Li}}function rn(t){let r=t.helpers??null,e=t.tomorrow,n=(o,a,s,l)=>s.known?{key:o,label:a,known:!0,text:l(s.value),reason:"",note:s.simulated?"simulated, not measured":"",chip:Ot(s.state)}:{key:o,label:a,known:!1,text:"Unknown",reason:s.reason,note:"",chip:Ve.UNKNOWN},i=[n("import","Expected import",e.importKwh,Nt),n("export","Expected export",e.exportKwh,Nt),n("solar","Expected solar",e.solarKwh,Nt),n("finish","Charge finishes",e.chargeFinishMin,o=>V(o)),n("reserve","Reserve",e.reservePct,o=>`${o} %`)];return i.push(e.confidence.known?{key:"confidence",label:"Confidence",known:!0,text:Vi[e.confidence.level]??e.confidence.level,reason:"",note:"",chip:Ot(e.confidence.state)}:{key:"confidence",label:"Confidence",known:!1,text:"Unknown",reason:"Intelligence did not state how sure it is.",note:"",chip:Ve.UNKNOWN}),{statusLine:Ni,adviceNote:t.adviceNote,figures:i,why:e.why.map(o=>({origin:o.origin,text:o.text})),settings:t.fields.map(Wi),tou:zi(t),overridesLine:r?t.overrides.length===0?Fi:`Quick overrides active: ${t.overrides.map(o=>te[o.kind]).join(", ")} (status only).`:t.overrides.length===0?Oi:`Quick overrides active: ${t.overrides.map(o=>o.kind).join(", ")} (status only).`,overrideBlock:r?qi(r):null}}function Lt(t){return p`<span class="plan-chip chip-${t.kind.toLowerCase()}" title=${t.meaning}><ha-icon icon=${t.icon} aria-hidden="true"></ha-icon><span class="plan-chip-text">${t.label}</span></span>`}function Xi(t){return p`
    <div class="plan-figure ${t.known?"":"is-unknown"}" data-figure=${t.key}>
      <dt>${t.label}</dt>
      <dd>
        <span class="plan-figure-value">${t.text}</span>
        ${t.note?p`<span class="plan-note">${t.note}</span>`:h}
        ${Lt(t.chip)}
        ${t.known?h:p`<span class="plan-reason">${t.reason}</span>`}
      </dd>
    </div>
  `}function Qi(t){return p`
    <li class="plan-setting ${t.known?"":"is-unknown"}" data-setting=${t.path}>
      <span class="plan-setting-label">${t.label}</span>
      <span class="plan-setting-value">${t.text}</span>
      ${Lt(t.chip)}
      ${t.known?t.remarks.map(r=>p`<span class="plan-reason">${r}</span>`):p`<span class="plan-reason">${t.reason}</span>`}
    </li>
  `}function Ji(t){return p`
    <li class="plan-setting" data-override=${t.kind}>
      <span class="plan-setting-label">${t.label}</span>
      <span class="plan-setting-value">${t.untilText}</span>
      <span class="plan-note">${t.countdownText}</span>
      <span class="plan-reason">${t.effectText}</span>
      ${t.belowReserve?p`<span class="plan-reason plan-below-reserve" data-below-reserve role="note">${t.belowReserve}</span>`:h}
    </li>
  `}function Zi(t){return p`
    <div class="plan-override-block" data-block="overrides">
      ${t.rows.length?p`<ul class="plan-settings">${t.rows.map(Ji)}</ul>`:h}
      <p class="plan-reason" data-override-policy=${t.policyOk?"ok":"unusable"}>${t.policyLine}</p>
      ${t.reasons.length?p`<ul class="plan-reasons">${t.reasons.map(r=>p`<li>${r}</li>`)}</ul>`:h}
      ${t.warnings.length?p`<ul class="plan-reasons">${t.warnings.map(r=>p`<li>${r}</li>`)}</ul>`:h}
      ${t.problems.length?p`<ul class="plan-reasons" data-override-problems>${t.problems.map(r=>p`<li>${r}</li>`)}</ul>`:h}
      ${t.missing.length?p`<p class="plan-reason">Plan helper entities not found: ${t.missing.join(", ")}.</p>`:h}
      ${t.proposed.length?p`
            <details class="plan-why">
              <summary>Proposed values (not in use)</summary>
              <ul>${t.proposed.map(r=>p`<li>${r}</li>`)}</ul>
            </details>
          `:h}
      <p class="plan-reason">${t.revisionText}</p>
      <p class="plan-reason">${t.note}</p>
    </div>
  `}function eo(t){return p`
    <li class="plan-slot ${t.mismatch?"is-mismatch":""}" data-slot=${t.index}>
      <div class="plan-slot-head">
        <span class="plan-slot-name">Slot ${t.index}</span>
        <span class="plan-slot-range">${t.rangeText}</span>
        ${Lt(t.chip)}
      </div>
      <div class="plan-slot-line"><span class="plan-slot-key">Intended</span> ${t.intendedText} <span class="plan-note">${t.originText}</span></div>
      <div class="plan-slot-line"><span class="plan-slot-key">Inverter</span> ${t.inverterText??"not read"}</div>
      ${t.mismatch?p`<p class="plan-mismatch" role="note"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon><span>${t.mismatch}</span></p>`:h}
    </li>
  `}function nn(t,r,e){let n=t.tou,i=e?p`<span class="plan-badge"><ha-icon icon="mdi:shield-check-outline" aria-hidden="true"></ha-icon>Guarded controls</span>`:p`<span class="plan-badge"><ha-icon icon="mdi:eye-outline" aria-hidden="true"></ha-icon>Read only</span>`;return p`
      <h2 class="plan-title">Plan ${i}</h2>
      <p class="plan-statusline" role="status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon><span>${t.statusLine}</span></p>

      <div class="plan-block" data-block="tomorrow">
        <h3 class="plan-heading">Tomorrow's Plan</h3>
        ${t.adviceNote?p`<p class="plan-reason plan-advice-note">${t.adviceNote}</p>`:h}
        <dl class="plan-figures">${t.figures.map(Xi)}</dl>
        <details class="plan-why">
          <summary>Why?</summary>
          <ul>${t.why.map(o=>p`<li data-origin=${o.origin}>${o.text}</li>`)}</ul>
        </details>
        <details class="plan-why plan-settings-details">
          <summary>Planned settings</summary>
          <ul class="plan-settings">${t.settings.map(Qi)}</ul>
        </details>
        <p class="plan-overrides">${t.overridesLine}</p>${t.overrideBlock?Zi(t.overrideBlock):h}${r}
      </div>

      <div class="plan-block" data-block="tou">
        <h3 class="plan-heading">Six-slot TOU timeline${n.statusText?p` <span class="plan-note">${n.statusText}</span>`:h}</h3>
        <p class="plan-tou-headline">${n.headline}</p>
        ${n.reasons.length?p`<ul class="plan-reasons">${n.reasons.map(o=>p`<li>${o}</li>`)}</ul>`:h}
        ${n.slots.length?p`
              <div class="plan-bar" aria-hidden="true">
                ${n.slots.map(o=>p`<span class="plan-seg ${o.mismatch?"is-mismatch":""}" style=${"flex-grow:"+o.spanMin}>${o.index}</span>`)}
              </div>
              <ol class="plan-slots">${n.slots.map(eo)}</ol>
            `:h}
      </div>
    `}function to(t,r=h){return r!==h?p`
    <section class="plan-section" aria-label="Plan, with guarded controls">${nn(t,r,!0)}</section>
  `:p`
    <section class="plan-section" aria-label="Plan, read only">${nn(t,h,!1)}</section>
  `}function on(t,r,e,n){if(!t||t.show_plan!==!0)return h;let i=typeof e=="number"&&Number.isFinite(e)?e:Date.now(),o=Zr(t,r??{},Math.floor(i/6e4)),a=rn(o);return to(a,n?n({snap:o,states:r??{},nowMs:i}):h)}var an=ce`
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
`;var se={last_result:"input_text.ecco_plan_last_result",start_script:"script.ecco_plan_override_start",cancel_script:"script.ecco_plan_override_cancel"};function Vt(t,r,e){let n={kind:t};return r.untilLocal===!0?n.until_local=!0:typeof r.expiryMin=="number"&&(n.expiry_min=r.expiryMin),typeof e=="number"&&(n.expected_revision=e),{domain:"script",service:"turn_on",data:{entity_id:se.start_script,variables:n}}}function sn(t,r){let e={kind:t};return typeof r=="number"&&(e.expected_revision=r),{domain:"script",service:"turn_on",data:{entity_id:se.cancel_script,variables:e}}}function ln(t){return/^script\.[a-z0-9_]+$/.test(t)?{domain:"script",service:"turn_on",data:{entity_id:t}}:null}function cn(t,r){if(typeof t!="object"||t===null)return!1;let e=t;if(e.domain!=="script"||e.service!=="turn_on"||typeof e.data!="object"||e.data===null)return!1;let n=e.data;if(Object.keys(e.data).some(a=>a!=="entity_id"&&a!=="variables"))return!1;let i=n.entity_id,o=typeof r=="string"&&r!==""&&i===r;return i!==se.start_script&&i!==se.cancel_script&&!o?!1:n.variables===void 0?!0:typeof n.variables!="object"||n.variables===null||o?!1:Object.keys(n.variables).every(a=>a==="kind"||a==="expiry_min"||a==="until_local"||a==="expected_revision")}function dn(t){let r=t.snap.helpers;if(!r)return null;let e=Math.floor(t.nowMs/6e4),n=r.revision.known?r.revision.value:null,i=[se.start_script,se.cancel_script].filter(c=>t.states[c]===void 0),o=t.snap.fields.find(c=>c.path==="reserve.backupPct"),a=o&&o.known?o.value:null,s=r.startPolicy.ok?r.startPolicy.config:null,l=W(t.states,se.last_result);return{kinds:ge.map(c=>{let u=r.active.find(k=>k.override.kind===c)??null,b=[],v=null;if(!s)v=r.startPolicy.ok?null:r.startPolicy.reasons[0]??"The override limits are not usable.";else{let k=zr(c,s,t.clock),N=k.length?k[0]:null,_=Gr(c,e,N?N.expiryMin:null,r.startPolicy,{clock:t.clock,currentReservePct:a});!_.ok&&(_.code==="RESERVE_UNKNOWN"||_.code==="RESERVE_BELOW_CURRENT")?v=_.error:k.length===0?v="No length fits the owner's limits.":b=k.map(T=>({id:T.id,label:T.label,isDefault:T.isDefault,call:T.untilMin!==null?Vt(c,{untilLocal:!0},n):Vt(c,{expiryMin:T.expiryMin},n)}))}let g=u||null,M=c==="prepare_power_cut"&&g&&typeof g.override.reservePct=="number"&&r.socPct!==null&&r.socPct<g.override.reservePct?Ft(r.socPct,g.override.reservePct):null;return{kind:c,label:te[c],active:u!==null,activeText:u?"Active until "+u.expiresText+" (ends in "+re(u.remainingMin)+")":null,choices:b,blockedReason:v,cancel:u?sn(c,n):null,belowReserve:M}}),lastResult:l,missingScripts:i}}function ro(t,r){if(typeof t!="number"||!Number.isFinite(t))return null;let n=(d=>((Math.floor(d/6e4)-r(d))%1440+1440)%1440)(t),i=r(t),o=i-r(t+864e5);if(o===0)return{nowWallMin:n,day:{changeAtMin:0,deltaMin:0}};if(o!==60&&o!==-60)return null;let a=t,s=t+864e5;for(;s-a>6e4;){let d=Math.floor((a+s)/2);r(d)===i?a=d:s=d}let l=((Math.floor(s/6e4)-i)%1440+1440)%1440;return{nowWallMin:n,day:{changeAtMin:l,deltaMin:o}}}function un(t){return ro(t,r=>new Date(r).getTimezoneOffset())}var no={hold_battery:"Holds ECCO back from starting an export. Charging and the battery's own work carry on.",skip_tonight:"Holds tonight's export. Charging continues.",prepare_power_cut:"Raises a protected reserve (never lowers it) and holds exports. It does not charge the battery."};function io(t,r){return p`
    <div class="plan-control" data-control=${t.kind}>
      <div class="plan-control-head">
        <span class="plan-setting-label">${t.label}</span>
        ${t.activeText?p`<span class="plan-setting-value" data-control-active>${t.activeText}</span>`:h}
      </div>
      <p class="plan-reason">${no[t.kind]??""}</p>
      ${t.belowReserve?p`<p class="plan-reason plan-below-reserve" data-below-reserve role="note">${t.belowReserve}</p>`:h}
      ${t.blockedReason?p`<p class="plan-reason" data-control-blocked>${t.blockedReason}</p>`:h}
      <div class="plan-control-buttons">
        ${t.choices.length?p`<span class="plan-note">${t.active?"Start again for":"Start for"}</span>`:h}
        ${t.choices.map(e=>p`<button type="button" class="plan-control-btn ${e.isDefault?"is-default":""}" data-choice=${e.id}
            aria-label=${t.label+": start for "+e.label} @click=${()=>r(e.call)}>${e.label}</button>`)}
        ${t.cancel?p`<button type="button" class="plan-control-btn is-cancel" data-cancel aria-label=${"Cancel "+t.label} @click=${()=>r(t.cancel)}>Cancel</button>`:h}
      </div>
    </div>
  `}function oo(t,r){return p`
    <div class="plan-controls" data-block="controls">
      <h3 class="plan-heading">Quick overrides</h3>
      <p class="plan-reason">They only hold ECCO's starts back or raise a protected reserve. Home Assistant checks every one against your limits again and may refuse it.</p>
      ${t.missingScripts.length?p`<p class="plan-reason" data-controls-missing>The guarded scripts were not found (${t.missingScripts.join(", ")}), so no override can be started or cancelled here.</p>`:t.kinds.map(e=>io(e,r))}
      ${t.lastResult?p`<p class="plan-reason plan-result" data-plan-result role="status">Last answer: ${t.lastResult}</p>`:h}
    </div>
  `}function pn(t){return({snap:r,states:e,nowMs:n})=>{let i=dn({snap:r,states:e,nowMs:n,clock:un(n)});return i?oo(i,t):h}}var hn=ce`
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
  .plan-below-reserve {
    color: var(--eaa-warning);
  }
  .plan-result {
    margin-top: 8px;
  }
`;var et=4e3,ao=1e3,P=class extends oe{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:ft,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!e.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=e}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(e){return!!this._config}willUpdate(){let e=this._config?.free_power;if(e){this._pendingPower!==void 0&&y(this._entityState(e.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&y(this._entityState(e.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let o=w(this._entityState(e.active)),a=w(this._entityState(e.write_enable)),s=w(this._entityState(e.operation_in_progress)),l=this._entityState(e.status),d=Ye({active:o,armed:a,operationInProgress:s,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==d&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=d}let n=this._config?.schedule;n&&(this._pendingSchedulePower!==void 0&&y(this._entityState(n.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&y(this._entityState(n.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&y(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&y(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&y(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let o=i.schedule;o&&(this._pendingDumpSchedulePower!==void 0&&y(this._entityState(o.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&y(this._entityState(o.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&y(this._entityState(o.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let a=w(this._entityState(i.active)),s=w(this._entityState(i.write_enable)),l=w(this._entityState(i.operation_in_progress)),d=w(this._entityState(i.snapshot_valid)),c=this._entityState(i.status),u=qe({active:a,armed:s,operationInProgress:l,snapshotValid:d,statusText:c});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==u&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=u}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let o=this._trackSummary();Sr(o.fp.state,o.dump.state)&&(this._track=xt(o.fp.state,o.dump.state))}}updated(){let e=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();e&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},ao):!e&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let e=this._config?.free_power;return e?w(this._entityState(e.active))===!0:!1}_scheduleArmed(){let e=this._config?.schedule;return e?w(this._entityState(e.armed))===!0:!1}_dumpActive(){let e=this._config?.dump_to_grid;return e?w(this._entityState(e.active))===!0:!1}_dumpScheduleArmed(){let e=this._config?.dump_to_grid?.schedule;return e?w(this._entityState(e.armed))===!0:!1}_freePowerVisualStateForInterlock(){let e=this._config?.free_power;if(!e||!this.hass)return null;let n=w(this._entityState(e.active)),i=w(this._entityState(e.write_enable)),o=w(this._entityState(e.operation_in_progress)),a=this._entityState(e.status);return Ye({active:n,armed:i,operationInProgress:o,statusText:a})}_dumpVisualStateForInterlock(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return null;let n=w(this._entityState(e.active)),i=w(this._entityState(e.write_enable)),o=w(this._entityState(e.operation_in_progress)),a=w(this._entityState(e.snapshot_valid)),s=this._entityState(e.status);return qe({active:n,armed:i,operationInProgress:o,snapshotValid:a,statusText:s})}_entityState(e){if(!(!e||!this.hass))return this.hass.states[e]?.state}_entity(e){if(!(!e||!this.hass))return this.hass.states[e]}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_callService(e,n,i){this.hass?.callService&&this.hass.callService(e,n,i)}_callServiceObj(e){this._callService(e.domain,e.service,e.data)}render(){if(!this._config)return p``;let e=this._config.title??ft;return this._config.layout==="tabbed"?this._renderTabbed(e):p`
      <ha-card>
        <h1 class="card-title">${e}</h1>
        <div class="actions-grid">
          ${this._renderFreePowerTile()}
          ${this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
    `}_renderPlan(){return on(this._config,this.hass?.states,void 0,pn(e=>this._callPlanService(e)))}_callPlanService(e){cn(e,this._config?.dump_to_grid?.guarded_start)&&this._callService(e.domain,e.service,e.data)}_pressDumpStart(e){if(e.guarded_start!==void 0&&e.guarded_start!==""){let n=ln(e.guarded_start);n&&this._callPlanService(n);return}this._callService("button","press",{entity_id:e.start})}_trackSummary(){let e=this._freePowerVisualStateForInterlock(),n=this._dumpVisualStateForInterlock(),i={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},o=this._config?.free_power;if(e!==null&&o){let l=this._config?.schedule,d=l?Et(e,wt({armed:w(this._entityState(l.armed))})):e,c=Ce(e,n)?"interlocked":d;i={state:c,pill:c,label:this._labelFor(c),statusText:this._entityState(o.status)}}let a=this._config?.dump_to_grid,s=a&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(n!==null&&a){let l=a.schedule,d=bt(n,l?w(this._entityState(l.armed)):null),c=Ce(n,e)?"interlocked":d;s={state:c,pill:c,label:vt(c),statusText:this._entityState(a.status)}}return{fp:i,dump:s}}_selectTrack(e){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=e}_renderTabbed(e){let n=this._trackSummary(),i=this._track??xt(n.fp.state,n.dump.state),o=i==="free_power"?"dump_to_grid":"free_power",a=i==="free_power"?n.dump:n.fp,s=Er(kr(a.state)),l=s==="fault"?"mdi:alert-circle-outline":s==="warning"?"mdi:alert-outline":"mdi:information-outline";return p`
      <ha-card>
        <div class="tabbed-header">
          <h1 class="card-title">${e}</h1>
          <div class="track-strip">
            <span class="state-pill state-${n.fp.pill}">Free Power · ${n.fp.label}</span>
            <span class="state-pill state-${n.dump.pill}">Dump to Grid · ${n.dump.label}</span>
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
        ${s?p`
              <div class="track-alert track-alert-${s}" role="status">
                <ha-icon icon=${l}></ha-icon>
                <div class="track-alert-text">${Mr(Pr(o),a.label,a.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(o)}>Show</button>
              </div>
            `:h}
        <div class="actions-grid is-tabbed">
          ${i==="free_power"?this._renderFreePowerTile():this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
    `}_renderFreePowerTile(){let e=this._config?.free_power;if(!e||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let n=w(this._entityState(e.active)),i=w(this._entityState(e.write_enable)),o=w(this._entityState(e.operation_in_progress)),a=w(this._entityState(e.snapshot_valid)),s=this._entityState(e.status),l=Ye({active:n,armed:i,operationInProgress:o,statusText:s});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let d=this._config?.schedule,c=d?w(this._entityState(d.armed)):null,u=wt({armed:c}),b=d?Et(l,u):l,v=this._dumpVisualStateForInterlock(),g=Ce(l,v),M=g?"interlocked":b,k=g?_t("Dump to Grid",v):void 0,N=this._entity(e.max_charge_power),_=this._entity(e.duration),T=this._pendingPower??y(N?.state),A=this._pendingDuration??y(_?.state),le=this._iconFor(M),m=this._labelFor(M);return p`
      <div class="tile free-power-tile state-${M}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${le}></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-${M}">${m}</span>
        </div>

        <div class="free-power-body">
          ${d&&u==="armed"?this._renderScheduleBanner(d):h}
          ${g?this._renderInterlockBanner(k):h}

          ${this._renderFreePowerBody(l,{fp:e,schedule:d,statusText:s,snapshotValid:a,interlocked:g,stagedPowerW:T,stagedDurationMin:A,stagedPowerEntity:N,stagedDurationEntity:_})}
        </div>
      </div>
    `}_iconFor(e){if(e==="scheduled")return"mdi:calendar-clock";if(e==="interlocked")return"mdi:lock-outline";switch(e){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":mr(e)}_renderInterlockBanner(e){return p`
      <div class="interlock-banner">
        <ha-icon icon="mdi:lock-outline"></ha-icon>
        <div class="interlock-banner-text">${e}</div>
      </div>
    `}_renderFreePowerUnavailable(e){return p`
      <div class="tile free-power-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:flash-off-outline"></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
    `}_renderFreePowerBody(e,n){switch(e){case"active":return this._renderActiveBody(n);case"busy":return this._renderBusyBody(n.statusText,n.fp.status);case"deferred":return this._renderDeferredBody(n.statusText,n.fp.status);case"recovery_attention":return this._renderAttentionBody(n);default:return this._renderReadyOrArmedBody(e,n)}}_renderReadyOrArmedBody(e,n){let i=!!n.schedule,o=i?this._mode:"now";return p`
      ${i?this._renderModeSelector():h}
      ${o==="later"&&n.schedule?this._renderLaterPanel(n.schedule):this._renderNowPanel(e,n)}
    `}_renderModeSelector(){let e=this._mode==="now";return p`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._mode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._mode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderNowPanel(e,n){let i=e==="armed",o=Ae(pr(e),n.interlocked),a=Ae(hr(e),n.interlocked);return p`
      <p class="tile-description">Charge the battery from free/zero-cost grid energy.</p>

      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:n.stagedPowerEntity,value:n.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:J,disabled:n.interlocked,onPreview:s=>this._pendingPower=s,onCommit:s=>this._commitNumber("power",s,n.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:n.stagedDurationEntity,value:n.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:n.interlocked,onPreview:s=>this._pendingDuration=s,onCommit:s=>this._commitNumber("duration",s,n.fp.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(n.statusText,n.fp.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!a}
          @click=${()=>this._toggleArm(n.fp.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Free Power"}
        </button>
        <button
          class="start-button"
          ?disabled=${!o}
          @click=${()=>this._callService("button","press",{entity_id:n.fp.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderLaterPanel(e){let n=w(this._entityState(e.armed)),i=kt(n),o=this._entityState(e.start),a=me(o),s=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.status),c=this._entityState(e.last_result),u=this._pendingScheduleDuration??y(s?.state),b=this._pendingSchedulePower??y(l?.state),v=d?.attributes?.effective_power_limit_w,g=typeof v=="number"?v:y(typeof v=="string"?v:void 0),M=this._numericAttr(l?.attributes?.max,8e3),k=Dr(M,g),N=yt(c),_=St(c),T=!i&&a!==null&&a.getTime()>this._nowMs;return p`
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${a?this._toDatetimeLocalValue(a):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${A=>this._handleScheduleStartChange(e.start,A.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:b,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:k,formatValue:J,disabled:i||!l,onPreview:A=>this._pendingSchedulePower=A,onCommit:A=>this._commitScheduleNumber("power",A,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:u,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:i||!s,onPreview:A=>this._pendingScheduleDuration=A,onCommit:A=>this._commitScheduleNumber("duration",A,e.duration)})}

      ${c?p`<p class="firmware-note ${N||_?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${i||!T}
          @click=${()=>this._callServiceObj(Pt(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the manual Free Power write-enable switch - Home Assistant arms and starts the inverter automatically when the time comes."}
      </p>
    `}_renderScheduleBanner(e){let n=this._entityState(e.start),i=me(n),o=y(this._entityState(e.duration)),a=y(this._entityState(e.power)),s=i?Ie(i.getTime(),this._nowMs):null;return p`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${i?Dt(i):"--"} • ${J(a)} • ${fe(o)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Mt(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_toDatetimeLocalValue(e){let n=i=>i.toString().padStart(2,"0");return`${e.getFullYear()}-${n(e.getMonth()+1)}-${n(e.getDate())}T${n(e.getHours())}:${n(e.getMinutes())}`}_handleScheduleStartChange(e,n){if(!n)return;let i=new Date(n);Number.isNaN(i.getTime())||this._callServiceObj(Rr(e,Tr(i)))}_commitScheduleNumber(e,n,i){e==="power"?this._pendingSchedulePower=n:this._pendingScheduleDuration=n,this._callServiceObj(Rt(i,n))}_renderActiveBody(e){let n=this._entityState(e.fp.ends_at),i=me(n),o=i?Ie(i.getTime(),this._nowMs):null;return p`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${J(e.stagedPowerW)} target • ends ${i?this._formatClock(i):n??"--"}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(e.fp)}
      ${this._renderEndRestoreButton(e.fp.end_restore,"End & Restore Now",!1,gt("active"))}
    `}_renderBusyBody(e,n){return p`
      <div class="transition-panel">
        <ha-icon class="spin" icon="mdi:autorenew"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Working...</div>
          ${this._renderTransitionDetail(e??"Free Power is mid-transaction.",n)}
        </div>
      </div>
      <p class="transition-hint">Controls are disabled while a transaction is in flight - this clears on its own.</p>
    `}_renderDeferredBody(e,n){return p`
      <div class="transition-panel deferred">
        <ha-icon icon="mdi:timer-sand"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Waiting for inverter bus</div>
          ${this._renderTransitionDetail(e??"Modbus bus busy - the watchdog will retry.",n)}
        </div>
      </div>
      <p class="transition-hint">This is expected occasionally - the watchdog retries automatically. No action needed.</p>
    `}_renderAttentionBody(e){let n=xr({statusText:e.statusText,snapshotValid:e.snapshotValid});return p`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(e.statusText??"Free Power requires operator attention.",e.fp.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${n.explanation??"No automatic retry. Starting a new Free Power session is disabled until this clears."}
      </p>
      ${n.actionable?this._renderEndRestoreButton(e.fp.end_restore,n.actionLabel??"End & Restore Now",n.secondary,gt("recovery_attention")):h}
    `}_renderTransitionDetail(e,n){return p`
      <div
        class="transition-detail clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(n)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(n))}}
      >
        ${e}
      </div>
    `}_renderStatusLine(e,n,i){return!(i?.alwaysShow||!!e&&e!=="Inactive")||!e?h:p`
      <p
        class="firmware-note clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(n)}
        @keydown=${a=>{(a.key==="Enter"||a.key===" ")&&(a.preventDefault(),this._moreInfo(n))}}
      >
        ${e}
      </p>
    `}_renderDiagnosticsDetails(e){let n=[],i=(o,a)=>{let s=y(this._entityState(a));s!==null&&n.push({label:o,value:s.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),n.length===0?h:p`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${n.map(o=>p`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(e,n,i,o){let a=this._confirmEndRestore;return p`
      <button
        class="end-restore-button ${i?"secondary":""} ${a?"confirming":""}"
        ?disabled=${!o}
        @click=${()=>this._handleEndRestoreClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${a?"Tap again to End & Restore":n}
        ${a?p`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:h}
      </button>
    `}_handleEndRestoreClick(e){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},et);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:e})}_toggleArm(e,n){this._callService("switch",n?"turn_off":"turn_on",{entity_id:e})}_commitNumber(e,n,i){e==="power"?this._pendingPower=n:this._pendingDuration=n,this._callService("number","set_value",{entity_id:i,value:n})}_commitDumpNumber(e,n,i){e==="power"?this._pendingDumpPower=n:e==="stop_soc"?this._pendingDumpStopSoc=n:this._pendingDumpDuration=n,this._callService("number","set_value",{entity_id:i,value:n})}_handleEndDumpClick(e){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},et);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:e})}_numericAttr(e,n){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"){let i=y(e);if(i!==null)return i}return n}_formatClock(e){let n=e.getHours().toString().padStart(2,"0"),i=e.getMinutes().toString().padStart(2,"0");return`${n}:${i}`}_renderNumberControl(e){let n=e.entity?.attributes??{},i=this._numericAttr(n.min,e.fallbackMin),o=e.maxOverride??this._numericAttr(n.max,e.fallbackMax),a=this._numericAttr(n.step,e.fallbackStep),s=e.value??i,l=e.disabled??!e.entity,d=o>i?Math.max(0,Math.min(100,(s-i)/(o-i)*100)):0;return p`
      <div class="number-control">
        <div class="number-control-label">
          <ha-icon icon=${e.icon}></ha-icon>
          <span>${e.label}</span>
          <span class="number-control-value">${e.formatValue(s)}</span>
        </div>
        <input
          type="range"
          class="number-control-slider"
          style="--eaa-slider-fill:${d}%"
          min=${i}
          max=${o}
          step=${a}
          .value=${String(s)}
          ?disabled=${l}
          @input=${c=>{let u=Number(c.target.value);Number.isFinite(u)&&e.onPreview(u)}}
          @change=${c=>{let u=Number(c.target.value);Number.isFinite(u)&&e.onCommit(u)}}
        />
      </div>
    `}_renderDumpToGridTile(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return this._renderDumpToGridLockedShell();let n=w(this._entityState(e.active)),i=w(this._entityState(e.write_enable)),o=w(this._entityState(e.operation_in_progress)),a=w(this._entityState(e.snapshot_valid)),s=this._entityState(e.status),l=qe({active:n,armed:i,operationInProgress:o,snapshotValid:a,statusText:s});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let d=e.schedule,c=d?w(this._entityState(d.armed)):null,u=bt(l,c),b=this._freePowerVisualStateForInterlock(),v=Ce(l,b),g=v?"interlocked":u,M=v?_t("Free Power",b):void 0,k=this._entity(e.export_power),N=this._entity(e.stop_soc),_=this._entity(e.duration),T=this._pendingDumpPower??y(k?.state),A=this._pendingDumpStopSoc??y(N?.state),le=this._pendingDumpDuration??y(_?.state),m=this._dumpIconFor(g),x=vt(g);return p`
      <div class="tile dump-to-grid-tile state-${g}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${m}></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-${g}">${x}</span>
        </div>

        <div class="dump-to-grid-body">
          ${d&&c===!0?this._renderDumpScheduleBanner(d):h}
          ${v?this._renderInterlockBanner(M):h}

          ${this._renderDumpBody(l,{dump:e,statusText:s,snapshotValid:a,interlocked:v,stagedPowerW:T,stagedStopSoc:A,stagedDurationMin:le,stagedPowerEntity:k,stagedStopSocEntity:N,stagedDurationEntity:_})}
        </div>
      </div>
    `}_renderDumpToGridLockedShell(){return p`
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
    `}_dumpIconFor(e){switch(e){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(e){return p`
      <div class="tile dump-to-grid-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-off"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${e}</p>
      </div>
    `}_renderDumpBody(e,n){switch(e){case"active":return this._renderDumpActiveBody(n);case"busy":return this._renderBusyBody(n.statusText??"Dump to Grid is mid-transaction.",n.dump.status);case"deferred":return this._renderDumpDeferredBody(n);case"recovery_attention":return this._renderDumpAttentionBody(n);default:return this._renderDumpReadyOrArmedBody(e,n)}}_renderDumpReadyOrArmedBody(e,n){let i=n.dump.schedule,o=i?this._dumpMode:"now";return p`
      ${i?this._renderDumpModeSelector():h}
      ${o==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(e,n)}
      ${this._renderDumpLastEndReason(n.dump)}
    `}_renderDumpModeSelector(){let e=this._dumpMode==="now";return p`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"is-active":""}"
          aria-selected=${e}
          @click=${()=>this._dumpMode="now"}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${e?"":"is-active"}"
          aria-selected=${!e}
          @click=${()=>this._dumpMode="later"}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `}_renderDumpNowPanel(e,n){let i=e==="armed",o=Ae(fr(e),n.interlocked),a=Ae(gr(e),n.interlocked);return p`
      <p class="tile-description">Export stored battery energy to the grid down to a chosen floor.</p>

      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:n.stagedPowerEntity,value:n.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:J,disabled:n.interlocked,onPreview:s=>this._pendingDumpPower=s,onCommit:s=>this._commitDumpNumber("power",s,n.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:n.stagedStopSocEntity,value:n.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:xe,disabled:n.interlocked,onPreview:s=>this._pendingDumpStopSoc=s,onCommit:s=>this._commitDumpNumber("stop_soc",s,n.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:n.stagedDurationEntity,value:n.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:n.interlocked,onPreview:s=>this._pendingDumpDuration=s,onCommit:s=>this._commitDumpNumber("duration",s,n.dump.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(n.statusText,n.dump.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!a}
          @click=${()=>this._toggleArm(n.dump.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Dump to Grid"}
        </button>
        <button
          class="start-button"
          ?disabled=${!o}
          @click=${()=>this._pressDumpStart(n.dump)}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderDumpLaterPanel(e){let n=w(this._entityState(e.armed)),i=kt(n),o=this._entityState(e.start),a=me(o),s=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.stop_soc),c=this._entityState(e.last_result),u=this._pendingDumpScheduleDuration??y(s?.state),b=this._pendingDumpSchedulePower??y(l?.state),v=this._pendingDumpScheduleStopSoc??y(d?.state),g=yt(c)||!!c&&/^FAILED/i.test(c.trim()),M=St(c),k=!!l&&!!s&&!!d&&n!==null,N=k&&!i&&a!==null&&a.getTime()>this._nowMs;return p`
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${a?this._toDatetimeLocalValue(a):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${_=>this._handleScheduleStartChange(e.start,_.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:b,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:J,disabled:i||!l,onPreview:_=>this._pendingDumpSchedulePower=_,onCommit:_=>this._commitDumpScheduleNumber("power",_,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:d,value:v,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:xe,disabled:i||!d,onPreview:_=>this._pendingDumpScheduleStopSoc=_,onCommit:_=>this._commitDumpScheduleNumber("stop_soc",_,e.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:s,value:u,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:fe,disabled:i||!s,onPreview:_=>this._pendingDumpScheduleDuration=_,onCommit:_=>this._commitDumpScheduleNumber("duration",_,e.duration)})}

      ${k?h:p`<p class="firmware-note is-warning">
            Scheduled Dump to Grid helpers are unavailable - is ecco_dump_to_grid_schedule.yaml installed?
          </p>`}
      ${c?p`<p class="firmware-note ${g||M?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${!N}
          @click=${()=>this._callServiceObj(Pt(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the Dump to Grid write-enable switch. At the start time Home Assistant stages these values, arms and presses Start; the firmware re-checks Stop SOC, charging TOU slots and Free Power itself. Arming is refused if it overlaps an armed Free Power schedule or a charging TOU slot."}
      </p>
    `}_renderDumpScheduleBanner(e){let n=me(this._entityState(e.start)),i=y(this._entityState(e.duration)),o=y(this._entityState(e.power)),a=y(this._entityState(e.stop_soc)),s=n?Ie(n.getTime(),this._nowMs):null;return p`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${n?Dt(n):"--"} • ${J(o)} • stop
            ${xe(a)} • ${fe(i)}
          </div>
          <div class="schedule-banner-countdown">${s?`Starts in ${s}`:"Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${()=>this._callServiceObj(Mt(e.cancel))}
        >
          Cancel
        </button>
      </div>
    `}_commitDumpScheduleNumber(e,n,i){e==="power"?this._pendingDumpSchedulePower=n:e==="stop_soc"?this._pendingDumpScheduleStopSoc=n:this._pendingDumpScheduleDuration=n,this._callServiceObj(Rt(i,n))}_renderDumpLastEndReason(e){let n=this._entityState(e.last_end_reason);return!n||n==="unknown"||n==="unavailable"?h:p`<p class="firmware-note">Last lease ended: ${n}</p>`}_renderDumpActiveBody(e){let n=this._entityState(e.dump.ends_at),i=me(n),o=i?Ie(i.getTime(),this._nowMs):null,a=y(this._entityState(e.dump.battery_soc)),s=br(y(this._entityState(e.dump.active_export_power)),e.statusText),l=vr(y(this._entityState(e.dump.active_stop_soc)),e.statusText);return p`
      <div class="active-hero">
        <div class="active-hero-time">${o??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${J(s)} export • ends ${i?this._formatClock(i):n??"--"}
      </div>
      <div class="active-secondary-line">
        Battery: ${xe(a)} • stops at ${xe(l)}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.dump.status,{alwaysShow:!0})}
      ${this._renderDumpDiagnosticsDetails(e.dump)}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",Xe("active"))}
    `}_renderDumpDeferredBody(e){return p`
      ${this._renderDeferredBody(e.statusText,e.dump.status)}
      ${e.snapshotValid===!0?this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",Xe("deferred")):h}
    `}_renderDumpAttentionBody(e){let i=!!e.dump.recovery_arm&&!!e.dump.recovery_force_restore&&!!e.dump.recovery_accept&&_r(e.statusText,e.snapshotValid);return p`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(e.statusText??"Dump to Grid requires operator attention.",e.dump.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${i?"Automatic restore is stopped until you decide. Arm recovery, then Force Restore Original (writes only the saved original settings) or Accept Current State (writes nothing; refused while the inverter still shows Dump export).":"If the status above says the watchdog will retry, ECCO keeps retrying the restore automatically. Only OPERATOR DECISION REQUIRED stops automatic retries."}
      </p>
      ${i?this._renderDumpRecoveryPanel(e.dump):h}
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",Xe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(e){let n=w(this._entityState(e.recovery_arm))===!0,i=this._entityState(e.recovery_state);return p`
      <div class="dump-recovery-panel">
        ${i&&i!=="unknown"&&i!=="unavailable"?p`<p class="firmware-note">${i}</p>`:h}
        <div class="action-row">
          <button
            class="arm-toggle ${n?"is-armed":""}"
            @click=${()=>this._toggleArm(e.recovery_arm,n)}
          >
            <ha-icon icon=${n?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
            ${n?"Disarm Recovery":"Arm Recovery"}
          </button>
        </div>
        <div class="action-row">
          <button
            class="start-button"
            ?disabled=${!n}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_force_restore})}
          >
            <ha-icon icon="mdi:backup-restore"></ha-icon>
            Force Restore Original
          </button>
          <button
            class="arm-toggle"
            ?disabled=${!n}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_accept})}
          >
            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
            Accept Current State
          </button>
        </div>
      </div>
    `}_renderDumpDiagnosticsDetails(e){let n=[],i=(o,a)=>{let s=y(this._entityState(a));s!==null&&n.push({label:o,value:s.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),n.length===0?h:p`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${n.map(o=>p`<span class="diagnostic-chip">${o.label}: ${o.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(e,n,i){let o=this._confirmEndDump;return p`
      <button
        class="end-restore-button ${o?"confirming":""}"
        ?disabled=${!i}
        @click=${()=>this._handleEndDumpClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${o?"Tap again to End & Restore":n}
        ${o?p`<span class="confirm-progress" style="animation-duration:${et}ms"></span>`:h}
      </button>
    `}};P.styles=[an,hn,ce`
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
  `],D([Ge({attribute:!1})],P.prototype,"hass",2),D([I()],P.prototype,"_config",2),D([I()],P.prototype,"_pendingPower",2),D([I()],P.prototype,"_pendingDuration",2),D([I()],P.prototype,"_pendingSchedulePower",2),D([I()],P.prototype,"_pendingScheduleDuration",2),D([I()],P.prototype,"_confirmEndRestore",2),D([I()],P.prototype,"_pendingDumpPower",2),D([I()],P.prototype,"_pendingDumpStopSoc",2),D([I()],P.prototype,"_pendingDumpDuration",2),D([I()],P.prototype,"_confirmEndDump",2),D([I()],P.prototype,"_dumpMode",2),D([I()],P.prototype,"_pendingDumpSchedulePower",2),D([I()],P.prototype,"_pendingDumpScheduleStopSoc",2),D([I()],P.prototype,"_pendingDumpScheduleDuration",2),D([I()],P.prototype,"_nowMs",2),D([I()],P.prototype,"_mode",2),D([I()],P.prototype,"_track",2),P=D([ur("ecco-energy-actions-card")],P);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{P as EccoEnergyActionsCard};
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
