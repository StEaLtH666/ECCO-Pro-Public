var St=Object.defineProperty;var kt=Object.getOwnPropertyDescriptor;var v=(a,r,e,t)=>{for(var i=t>1?void 0:t?kt(r,e):r,n=a.length-1,s;n>=0;n--)(s=a[n])&&(i=(t?s(r,e,i):s(i))||i);return t&&i&&St(r,e,i),i};var Z=globalThis,X=Z.ShadowRoot&&(Z.ShadyCSS===void 0||Z.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,ue=Symbol(),Le=new WeakMap,B=class{constructor(r,e,t){if(this._$cssResult$=!0,t!==ue)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=r,this.t=e}get styleSheet(){let r=this.o,e=this.t;if(X&&r===void 0){let t=e!==void 0&&e.length===1;t&&(r=Le.get(e)),r===void 0&&((this.o=r=new CSSStyleSheet).replaceSync(this.cssText),t&&Le.set(e,r))}return r}toString(){return this.cssText}},Ue=a=>new B(typeof a=="string"?a:a+"",void 0,ue),pe=(a,...r)=>{let e=a.length===1?a[0]:r.reduce((t,i,n)=>t+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+a[n+1],a[0]);return new B(e,a,ue)},Be=(a,r)=>{if(X)a.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of r){let t=document.createElement("style"),i=Z.litNonce;i!==void 0&&t.setAttribute("nonce",i),t.textContent=e.cssText,a.appendChild(t)}},he=X?a=>a:a=>a instanceof CSSStyleSheet?(r=>{let e="";for(let t of r.cssRules)e+=t.cssText;return Ue(e)})(a):a;var{is:$t,defineProperty:Dt,getOwnPropertyDescriptor:Et,getOwnPropertyNames:Tt,getOwnPropertySymbols:At,getPrototypeOf:Rt}=Object,ee=globalThis,He=ee.trustedTypes,Pt=He?He.emptyScript:"",Ct=ee.reactiveElementPolyfillSupport,H=(a,r)=>a,z={toAttribute(a,r){switch(r){case Boolean:a=a?Pt:null;break;case Object:case Array:a=a==null?a:JSON.stringify(a)}return a},fromAttribute(a,r){let e=a;switch(r){case Boolean:e=a!==null;break;case Number:e=a===null?null:Number(a);break;case Object:case Array:try{e=JSON.parse(a)}catch{e=null}}return e}},te=(a,r)=>!$t(a,r),ze={attribute:!0,type:String,converter:z,reflect:!1,useDefault:!1,hasChanged:te};Symbol.metadata??=Symbol("metadata"),ee.litPropertyMetadata??=new WeakMap;var E=class extends HTMLElement{static addInitializer(r){this._$Ei(),(this.l??=[]).push(r)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(r,e=ze){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(r)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(r,e),!e.noAccessor){let t=Symbol(),i=this.getPropertyDescriptor(r,t,e);i!==void 0&&Dt(this.prototype,r,i)}}static getPropertyDescriptor(r,e,t){let{get:i,set:n}=Et(this.prototype,r)??{get(){return this[e]},set(s){this[e]=s}};return{get:i,set(s){let o=i?.call(this);n?.call(this,s),this.requestUpdate(r,o,t)},configurable:!0,enumerable:!0}}static getPropertyOptions(r){return this.elementProperties.get(r)??ze}static _$Ei(){if(this.hasOwnProperty(H("elementProperties")))return;let r=Rt(this);r.finalize(),r.l!==void 0&&(this.l=[...r.l]),this.elementProperties=new Map(r.elementProperties)}static finalize(){if(this.hasOwnProperty(H("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(H("properties"))){let e=this.properties,t=[...Tt(e),...At(e)];for(let i of t)this.createProperty(i,e[i])}let r=this[Symbol.metadata];if(r!==null){let e=litPropertyMetadata.get(r);if(e!==void 0)for(let[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(let[e,t]of this.elementProperties){let i=this._$Eu(e,t);i!==void 0&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(r){let e=[];if(Array.isArray(r)){let t=new Set(r.flat(1/0).reverse());for(let i of t)e.unshift(he(i))}else r!==void 0&&e.push(he(r));return e}static _$Eu(r,e){let t=e.attribute;return t===!1?void 0:typeof t=="string"?t:typeof r=="string"?r.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(r=>this.enableUpdating=r),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(r=>r(this))}addController(r){(this._$EO??=new Set).add(r),this.renderRoot!==void 0&&this.isConnected&&r.hostConnected?.()}removeController(r){this._$EO?.delete(r)}_$E_(){let r=new Map,e=this.constructor.elementProperties;for(let t of e.keys())this.hasOwnProperty(t)&&(r.set(t,this[t]),delete this[t]);r.size>0&&(this._$Ep=r)}createRenderRoot(){let r=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Be(r,this.constructor.elementStyles),r}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(r=>r.hostConnected?.())}enableUpdating(r){}disconnectedCallback(){this._$EO?.forEach(r=>r.hostDisconnected?.())}attributeChangedCallback(r,e,t){this._$AK(r,t)}_$ET(r,e){let t=this.constructor.elementProperties.get(r),i=this.constructor._$Eu(r,t);if(i!==void 0&&t.reflect===!0){let n=(t.converter?.toAttribute!==void 0?t.converter:z).toAttribute(e,t.type);this._$Em=r,n==null?this.removeAttribute(i):this.setAttribute(i,n),this._$Em=null}}_$AK(r,e){let t=this.constructor,i=t._$Eh.get(r);if(i!==void 0&&this._$Em!==i){let n=t.getPropertyOptions(i),s=typeof n.converter=="function"?{fromAttribute:n.converter}:n.converter?.fromAttribute!==void 0?n.converter:z;this._$Em=i;let o=s.fromAttribute(e,n.type);this[i]=o??this._$Ej?.get(i)??o,this._$Em=null}}requestUpdate(r,e,t,i=!1,n){if(r!==void 0){let s=this.constructor;if(i===!1&&(n=this[r]),t??=s.getPropertyOptions(r),!((t.hasChanged??te)(n,e)||t.useDefault&&t.reflect&&n===this._$Ej?.get(r)&&!this.hasAttribute(s._$Eu(r,t))))return;this.C(r,e,t)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(r,e,{useDefault:t,reflect:i,wrapped:n},s){t&&!(this._$Ej??=new Map).has(r)&&(this._$Ej.set(r,s??e??this[r]),n!==!0||s!==void 0)||(this._$AL.has(r)||(this.hasUpdated||t||(e=void 0),this._$AL.set(r,e)),i===!0&&this._$Em!==r&&(this._$Eq??=new Set).add(r))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let r=this.scheduleUpdate();return r!=null&&await r,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,n]of this._$Ep)this[i]=n;this._$Ep=void 0}let t=this.constructor.elementProperties;if(t.size>0)for(let[i,n]of t){let{wrapped:s}=n,o=this[i];s!==!0||this._$AL.has(i)||o===void 0||this.C(i,void 0,n,o)}}let r=!1,e=this._$AL;try{r=this.shouldUpdate(e),r?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(t){throw r=!1,this._$EM(),t}r&&this._$AE(e)}willUpdate(r){}_$AE(r){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(r)),this.updated(r)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(r){return!0}update(r){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(r){}firstUpdated(r){}};E.elementStyles=[],E.shadowRootOptions={mode:"open"},E[H("elementProperties")]=new Map,E[H("finalized")]=new Map,Ct?.({ReactiveElement:E}),(ee.reactiveElementVersions??=[]).push("2.1.2");var ye=globalThis,We=a=>a,re=ye.trustedTypes,Ge=re?re.createPolicy("lit-html",{createHTML:a=>a}):void 0,Je="$lit$",A=`lit$${Math.random().toFixed(9).slice(2)}$`,Ze="?"+A,Nt=`<${Ze}>`,N=document,G=()=>N.createComment(""),j=a=>a===null||typeof a!="object"&&typeof a!="function",we=Array.isArray,Ot=a=>we(a)||typeof a?.[Symbol.iterator]=="function",me=`[ 	
\f\r]`,W=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,je=/-->/g,qe=/>/g,P=RegExp(`>|${me}(?:([^\\s"'>=/]+)(${me}*=${me}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Ye=/'/g,Ke=/"/g,Xe=/^(?:script|style|textarea|title)$/i,xe=a=>(r,...e)=>({_$litType$:a,strings:r,values:e}),u=xe(1),_r=xe(2),gr=xe(3),O=Symbol.for("lit-noChange"),h=Symbol.for("lit-nothing"),Qe=new WeakMap,C=N.createTreeWalker(N,129);function et(a,r){if(!we(a)||!a.hasOwnProperty("raw"))throw Error("invalid template strings array");return Ge!==void 0?Ge.createHTML(r):r}var Mt=(a,r)=>{let e=a.length-1,t=[],i,n=r===2?"<svg>":r===3?"<math>":"",s=W;for(let o=0;o<e;o++){let l=a[o],d,c,p=-1,y=0;for(;y<l.length&&(s.lastIndex=y,c=s.exec(l),c!==null);)y=s.lastIndex,s===W?c[1]==="!--"?s=je:c[1]!==void 0?s=qe:c[2]!==void 0?(Xe.test(c[2])&&(i=RegExp("</"+c[2],"g")),s=P):c[3]!==void 0&&(s=P):s===P?c[0]===">"?(s=i??W,p=-1):c[1]===void 0?p=-2:(p=s.lastIndex-c[2].length,d=c[1],s=c[3]===void 0?P:c[3]==='"'?Ke:Ye):s===Ke||s===Ye?s=P:s===je||s===qe?s=W:(s=P,i=void 0);let _=s===P&&a[o+1].startsWith("/>")?" ":"";n+=s===W?l+Nt:p>=0?(t.push(d),l.slice(0,p)+Je+l.slice(p)+A+_):l+A+(p===-2?o:_)}return[et(a,n+(a[e]||"<?>")+(r===2?"</svg>":r===3?"</math>":"")),t]},q=class a{constructor({strings:r,_$litType$:e},t){let i;this.parts=[];let n=0,s=0,o=r.length-1,l=this.parts,[d,c]=Mt(r,e);if(this.el=a.createElement(d,t),C.currentNode=this.el.content,e===2||e===3){let p=this.el.content.firstChild;p.replaceWith(...p.childNodes)}for(;(i=C.nextNode())!==null&&l.length<o;){if(i.nodeType===1){if(i.hasAttributes())for(let p of i.getAttributeNames())if(p.endsWith(Je)){let y=c[s++],_=i.getAttribute(p).split(A),w=/([.?@])?(.*)/.exec(y);l.push({type:1,index:n,name:w[2],strings:_,ctor:w[1]==="."?_e:w[1]==="?"?ge:w[1]==="@"?be:V}),i.removeAttribute(p)}else p.startsWith(A)&&(l.push({type:6,index:n}),i.removeAttribute(p));if(Xe.test(i.tagName)){let p=i.textContent.split(A),y=p.length-1;if(y>0){i.textContent=re?re.emptyScript:"";for(let _=0;_<y;_++)i.append(p[_],G()),C.nextNode(),l.push({type:2,index:++n});i.append(p[y],G())}}}else if(i.nodeType===8)if(i.data===Ze)l.push({type:2,index:n});else{let p=-1;for(;(p=i.data.indexOf(A,p+1))!==-1;)l.push({type:7,index:n}),p+=A.length-1}n++}}static createElement(r,e){let t=N.createElement("template");return t.innerHTML=r,t}};function I(a,r,e=a,t){if(r===O)return r;let i=t!==void 0?e._$Co?.[t]:e._$Cl,n=j(r)?void 0:r._$litDirective$;return i?.constructor!==n&&(i?._$AO?.(!1),n===void 0?i=void 0:(i=new n(a),i._$AT(a,e,t)),t!==void 0?(e._$Co??=[])[t]=i:e._$Cl=i),i!==void 0&&(r=I(a,i._$AS(a,r.values),i,t)),r}var fe=class{constructor(r,e){this._$AV=[],this._$AN=void 0,this._$AD=r,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(r){let{el:{content:e},parts:t}=this._$AD,i=(r?.creationScope??N).importNode(e,!0);C.currentNode=i;let n=C.nextNode(),s=0,o=0,l=t[0];for(;l!==void 0;){if(s===l.index){let d;l.type===2?d=new Y(n,n.nextSibling,this,r):l.type===1?d=new l.ctor(n,l.name,l.strings,this,r):l.type===6&&(d=new ve(n,this,r)),this._$AV.push(d),l=t[++o]}s!==l?.index&&(n=C.nextNode(),s++)}return C.currentNode=N,i}p(r){let e=0;for(let t of this._$AV)t!==void 0&&(t.strings!==void 0?(t._$AI(r,t,e),e+=t.strings.length-2):t._$AI(r[e])),e++}},Y=class a{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(r,e,t,i){this.type=2,this._$AH=h,this._$AN=void 0,this._$AA=r,this._$AB=e,this._$AM=t,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let r=this._$AA.parentNode,e=this._$AM;return e!==void 0&&r?.nodeType===11&&(r=e.parentNode),r}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(r,e=this){r=I(this,r,e),j(r)?r===h||r==null||r===""?(this._$AH!==h&&this._$AR(),this._$AH=h):r!==this._$AH&&r!==O&&this._(r):r._$litType$!==void 0?this.$(r):r.nodeType!==void 0?this.T(r):Ot(r)?this.k(r):this._(r)}O(r){return this._$AA.parentNode.insertBefore(r,this._$AB)}T(r){this._$AH!==r&&(this._$AR(),this._$AH=this.O(r))}_(r){this._$AH!==h&&j(this._$AH)?this._$AA.nextSibling.data=r:this.T(N.createTextNode(r)),this._$AH=r}$(r){let{values:e,_$litType$:t}=r,i=typeof t=="number"?this._$AC(r):(t.el===void 0&&(t.el=q.createElement(et(t.h,t.h[0]),this.options)),t);if(this._$AH?._$AD===i)this._$AH.p(e);else{let n=new fe(i,this),s=n.u(this.options);n.p(e),this.T(s),this._$AH=n}}_$AC(r){let e=Qe.get(r.strings);return e===void 0&&Qe.set(r.strings,e=new q(r)),e}k(r){we(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,t,i=0;for(let n of r)i===e.length?e.push(t=new a(this.O(G()),this.O(G()),this,this.options)):t=e[i],t._$AI(n),i++;i<e.length&&(this._$AR(t&&t._$AB.nextSibling,i),e.length=i)}_$AR(r=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);r!==this._$AB;){let t=We(r).nextSibling;We(r).remove(),r=t}}setConnected(r){this._$AM===void 0&&(this._$Cv=r,this._$AP?.(r))}},V=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(r,e,t,i,n){this.type=1,this._$AH=h,this._$AN=void 0,this.element=r,this.name=e,this._$AM=i,this.options=n,t.length>2||t[0]!==""||t[1]!==""?(this._$AH=Array(t.length-1).fill(new String),this.strings=t):this._$AH=h}_$AI(r,e=this,t,i){let n=this.strings,s=!1;if(n===void 0)r=I(this,r,e,0),s=!j(r)||r!==this._$AH&&r!==O,s&&(this._$AH=r);else{let o=r,l,d;for(r=n[0],l=0;l<n.length-1;l++)d=I(this,o[t+l],e,l),d===O&&(d=this._$AH[l]),s||=!j(d)||d!==this._$AH[l],d===h?r=h:r!==h&&(r+=(d??"")+n[l+1]),this._$AH[l]=d}s&&!i&&this.j(r)}j(r){r===h?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,r??"")}},_e=class extends V{constructor(){super(...arguments),this.type=3}j(r){this.element[this.name]=r===h?void 0:r}},ge=class extends V{constructor(){super(...arguments),this.type=4}j(r){this.element.toggleAttribute(this.name,!!r&&r!==h)}},be=class extends V{constructor(r,e,t,i,n){super(r,e,t,i,n),this.type=5}_$AI(r,e=this){if((r=I(this,r,e,0)??h)===O)return;let t=this._$AH,i=r===h&&t!==h||r.capture!==t.capture||r.once!==t.once||r.passive!==t.passive,n=r!==h&&(t===h||i);i&&this.element.removeEventListener(this.name,this,t),n&&this.element.addEventListener(this.name,this,r),this._$AH=r}handleEvent(r){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,r):this._$AH.handleEvent(r)}},ve=class{constructor(r,e,t){this.element=r,this.type=6,this._$AN=void 0,this._$AM=e,this.options=t}get _$AU(){return this._$AM._$AU}_$AI(r){I(this,r)}};var Ft=ye.litHtmlPolyfillSupport;Ft?.(q,Y),(ye.litHtmlVersions??=[]).push("3.3.3");var tt=(a,r,e)=>{let t=e?.renderBefore??r,i=t._$litPart$;if(i===void 0){let n=e?.renderBefore??null;t._$litPart$=i=new Y(r.insertBefore(G(),n),n,void 0,e??{})}return i._$AI(a),i};var Se=globalThis,R=class extends E{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let r=super.createRenderRoot();return this.renderOptions.renderBefore??=r.firstChild,r}update(r){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(r),this._$Do=tt(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return O}};R._$litElement$=!0,R.finalized=!0,Se.litElementHydrateSupport?.({LitElement:R});var It=Se.litElementPolyfillSupport;It?.({LitElement:R});(Se.litElementVersions??=[]).push("4.2.2");var rt=a=>(r,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(a,r)}):customElements.define(a,r)};var Vt={attribute:!0,type:String,converter:z,reflect:!1,hasChanged:te},Lt=(a=Vt,r,e)=>{let{kind:t,metadata:i}=e,n=globalThis.litPropertyMetadata.get(i);if(n===void 0&&globalThis.litPropertyMetadata.set(i,n=new Map),t==="setter"&&((a=Object.create(a)).wrapped=!0),n.set(e.name,a),t==="accessor"){let{name:s}=e;return{set(o){let l=r.get.call(this);r.set.call(this,o),this.requestUpdate(s,l,a,!0,o)},init(o){return o!==void 0&&this.C(s,void 0,a,o),o}}}if(t==="setter"){let{name:s}=e;return function(o){let l=this[s];r.call(this,o),this.requestUpdate(s,l,a,!0,o)}}throw Error("Unsupported decorator location: "+t)};function ie(a){return(r,e)=>typeof e=="object"?Lt(a,r,e):((t,i,n)=>{let s=i.hasOwnProperty(n);return i.constructor.createProperty(n,t),s?Object.getOwnPropertyDescriptor(i,n):void 0})(a,r,e)}function x(a){return ie({...a,state:!0,attribute:!1})}var ke="Energy Actions";var Ut=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Bt=/DEFERRED/i,Ht=/^(RESTORING|STARTING|ACTIVATION VERIFY)/i;function ne(a){let{active:r,armed:e,operationInProgress:t,statusText:i}=a;return r===null||e===null||t===null?"unavailable":i&&Ut.test(i)?"recovery_attention":i&&Bt.test(i)?"deferred":i&&Ht.test(i)?"busy":r?"active":t?"busy":e?"armed":"ready"}function it(a){return a==="armed"}function $e(a){return a!=="busy"&&a!=="unavailable"}function at(a){return a==="ready"||a==="armed"}var zt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function nt(a){return zt[a]}var Wt=/RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i,Gt=/DEFERRED/i,jt=/^(RESTORING|STARTING)/i;function se(a){let{active:r,armed:e,operationInProgress:t,snapshotValid:i,statusText:n}=a;return r===null||e===null||t===null||i===null?"unavailable":n&&Wt.test(n)?"recovery_attention":n&&Gt.test(n)?"deferred":n&&jt.test(n)?"busy":r?"active":t?"busy":i?"deferred":e?"armed":"ready"}function st(a){return a==="armed"}function oe(a){return a!=="busy"&&a!=="unavailable"}function ot(a){return a==="ready"||a==="armed"}var qt={unavailable:"Unavailable",recovery_attention:"Attention Needed",deferred:"Waiting For Inverter",busy:"Working",active:"Active",armed:"Armed",ready:"Ready"};function Yt(a){return qt[a]}function De(a,r){return a==="ready"&&r===!0?"scheduled":a}function Ee(a){return a==="scheduled"?"Scheduled":a==="interlocked"?"Interlocked":Yt(a)}var Kt=/target (\d+)\s*W export/i,Qt=/Stop SOC (\d+)\s*%/i;function lt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Kt.exec(r):null;return e?Number(e[1]):null}function dt(a,r){if(a!==null&&Number.isFinite(a))return a;let e=r?Qt.exec(r):null;return e?Number(e[1]):null}var Jt=/OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;function ct(a,r){return r===!0&&!!a&&Jt.test(a)}var Zt=/RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i,Xt=/START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i,er=/OPERATOR DECISION REQUIRED/i,tr=/press End Free Power|retry(?:ing)? restore/i,rr=/\bRECOVERY REQUIRED\b/i,ir=/snapshot retained/i,ar=/RESTORE BLOCKED/i;function ut(a){let r=a.statusText??"",e=a.snapshotValid;return Zt.test(r)?{actionable:!1,actionLabel:null,secondary:!1,explanation:"Deliberate recovery is required - this will not clear on its own."}:Xt.test(r)&&e===!1?{actionable:!1,actionLabel:null,secondary:!1,explanation:"No saved snapshot is held - there is nothing to restore."}:er.test(r)&&tr.test(r)&&e===!0?{actionable:!0,actionLabel:"Retry End & Restore",secondary:!1,explanation:null}:rr.test(r)&&e===!0?{actionable:!0,actionLabel:"Restore Saved Settings",secondary:!1,explanation:null}:ir.test(r)&&e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!0,explanation:null}:ar.test(r)?e===!0?{actionable:!0,actionLabel:"Attempt Restore",secondary:!0,explanation:"Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch."}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly."}:e===!0?{actionable:!0,actionLabel:"End & Restore Now",secondary:!1,explanation:null}:{actionable:!1,actionLabel:null,secondary:!1,explanation:"Unable to confirm a saved snapshot is held - review the firmware status directly before acting."}}var nr=new Set(["active","busy","recovery_attention","deferred"]);function sr(a){return a!==null&&nr.has(a)}function K(a,r){return(a==="ready"||a==="armed")&&sr(r)}function Q(a,r){return a&&!r}function Te(a,r){switch(r){case"busy":return`${a} is restoring inverter state.`;case"recovery_attention":case"deferred":return`${a} requires recovery before this can be used.`;default:return`${a} currently owns inverter control.`}}var pt=["recovery_attention","deferred","busy","active","armed","scheduled","interlocked","ready","unavailable"];function ht(a){let r=pt.indexOf(a);return r<0?pt.length:r}function mt(a,r){return a!=="unavailable"||r!=="unavailable"}function Ae(a,r){return ht(r)<ht(a)?"dump_to_grid":"free_power"}function ft(a){switch(a){case"recovery_attention":return"fault";case"busy":case"deferred":return"warning";case"active":return"info";default:return"none"}}function _t(a){switch(a){case"fault":return"fault";case"warning":return"warning";case"info":return"accent";default:return null}}function gt(a){return a==="dump_to_grid"?"Dump to Grid":"Free Power"}function bt(a,r,e){let t=e?.trim()??"";return t?`${a}: ${r} - ${t}`:`${a}: ${r}`}function Re(a){return a.armed===!0?"armed":"hidden"}function Pe(a){return!!a&&/^REJECTED/i.test(a.trim())}function Ce(a){return!!a&&/^BLOCKED/i.test(a.trim())}function Ne(a){return a===!0}function Oe(a,r){return a==="ready"&&r==="armed"?"scheduled":a}function Me(a){return{domain:"input_boolean",service:"turn_on",data:{entity_id:a}}}function Fe(a){return{domain:"script",service:"turn_on",data:{entity_id:a}}}function vt(a,r){return{domain:"input_datetime",service:"set_datetime",data:{entity_id:a,datetime:r}}}function Ie(a,r){return{domain:"input_number",service:"set_value",data:{entity_id:a,value:r}}}function yt(a,r){return r===null||!Number.isFinite(r)||r<=0?a:Math.min(a,r)}var or=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function M(a){if(!a)return null;let r=or.exec(a.trim());if(!r)return null;let[,e,t,i,n,s,o]=r,l=new Date(Number(e),Number(t)-1,Number(i),Number(n),Number(s),Number(o));return Number.isNaN(l.getTime())?null:l}function wt(a){let r=e=>e.toString().padStart(2,"0");return`${a.getFullYear()}-${r(a.getMonth()+1)}-${r(a.getDate())} ${r(a.getHours())}:${r(a.getMinutes())}:${r(a.getSeconds())}`}var lr=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],dr=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];function Ve(a){let r=lr[a.getDay()],e=a.getDate(),t=dr[a.getMonth()],i=a.getHours().toString().padStart(2,"0"),n=a.getMinutes().toString().padStart(2,"0");return`${r} ${e} ${t} \u2022 ${i}:${n}`}function J(a,r){let e=a-r;if(e<=0)return null;let t=Math.floor(e/1e3),i=Math.floor(t/3600),n=Math.floor(t%3600/60),s=t%60;return i>0?`${i}h ${n}m`:n>0?`${n}m ${s.toString().padStart(2,"0")}s`:`${s}s`}function T(a){return a==null||Number.isNaN(a)?"--":Math.abs(a)>=1e3?`${(a/1e3).toFixed(2)} kW`:`${a.toFixed(0)} W`}function F(a){if(a==null||Number.isNaN(a))return"--";let r=Math.round(a);if(r<60)return`${r} min`;let e=Math.floor(r/60),t=r%60;return t===0?`${e}h`:`${e}h ${t}m`}function L(a){return a==null||Number.isNaN(a)?"--":`${Math.round(a)}%`}function f(a){if(a==null||a==="unknown"||a==="unavailable"||a==="")return null;let r=Number(a);return Number.isFinite(r)?r:null}function m(a){return a==null||a==="unknown"||a==="unavailable"||a===""?null:a==="on"}var le=4e3,cr=1e3,g=class extends R{constructor(){super(...arguments);this._confirmEndRestore=!1;this._confirmEndDump=!1;this._dumpMode="now";this._nowMs=Date.now();this._mode="now";this._track=null}static getStubConfig(){return{type:"custom:ecco-energy-actions-card",title:ke,free_power:{active:"binary_sensor.free_power_active",operation_in_progress:"binary_sensor.free_power_operation_in_progress",snapshot_valid:"binary_sensor.free_power_snapshot_valid",status:"sensor.free_power_status",ends_at:"sensor.free_power_ends_at",failures:"sensor.free_power_failures_since_boot",start_attempts:"sensor.free_power_start_attempts_since_boot",start_successes:"sensor.free_power_start_successes_since_boot",restore_successes:"sensor.free_power_restore_successes_since_boot",write_enable:"switch.free_power_write_enable",max_charge_power:"number.free_power_max_charge_power",duration:"number.free_power_duration",start:"button.start_free_power_charge_now",end_restore:"button.end_free_power_restore_now"},schedule:{armed:"input_boolean.ecco_free_power_schedule_armed",start:"input_datetime.ecco_free_power_schedule_start",duration:"input_number.ecco_free_power_schedule_duration",power:"input_number.ecco_free_power_schedule_power",last_result:"input_text.ecco_free_power_schedule_last_result",status:"sensor.ecco_free_power_schedule_status",cancel:"script.ecco_free_power_cancel_schedule"},dump_to_grid:{active:"binary_sensor.dump_to_grid_active",operation_in_progress:"binary_sensor.dump_to_grid_operation_in_progress",snapshot_valid:"binary_sensor.dump_to_grid_snapshot_valid",status:"sensor.dump_to_grid_status",ends_at:"sensor.dump_to_grid_ends_at",battery_soc:"sensor.ecco_battery_soc",failures:"sensor.dump_to_grid_failures_since_boot",start_attempts:"sensor.dump_to_grid_start_attempts_since_boot",start_successes:"sensor.dump_to_grid_start_successes_since_boot",restore_successes:"sensor.dump_to_grid_restore_successes_since_boot",write_enable:"switch.dump_to_grid_write_enable",export_power:"number.dump_to_grid_export_power",stop_soc:"number.dump_to_grid_stop_soc",duration:"number.dump_to_grid_duration",start:"button.start_dump_to_grid_now",end_restore:"button.end_dump_to_grid_restore_now",active_export_power:"sensor.dump_to_grid_active_export_power",active_stop_soc:"sensor.dump_to_grid_active_stop_soc",last_end_reason:"sensor.dump_to_grid_last_end_reason",recovery_arm:"switch.dump_to_grid_recovery_arm",recovery_force_restore:"button.dump_to_grid_force_restore_original",recovery_accept:"button.dump_to_grid_accept_current_state",recovery_state:"sensor.dump_to_grid_recovery_state",schedule:{armed:"input_boolean.ecco_dump_to_grid_schedule_armed",start:"input_datetime.ecco_dump_to_grid_schedule_start",duration:"input_number.ecco_dump_to_grid_schedule_duration",power:"input_number.ecco_dump_to_grid_schedule_power",stop_soc:"input_number.ecco_dump_to_grid_schedule_stop_soc",last_result:"input_text.ecco_dump_to_grid_schedule_last_result",status:"sensor.ecco_dump_to_grid_schedule_status",cancel:"script.ecco_dump_to_grid_cancel_schedule"}}}}setConfig(e){if(!e||typeof e!="object")throw new Error("ecco-energy-actions-card: invalid configuration");if(!e.free_power)throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");this._config=e}getCardSize(){return this._config?.schedule||this._config?.dump_to_grid?.schedule?6:4}disconnectedCallback(){super.disconnectedCallback(),this._stopTicking(),this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)}shouldUpdate(e){return!!this._config}willUpdate(){let e=this._config?.free_power;if(e){this._pendingPower!==void 0&&f(this._entityState(e.max_charge_power))===this._pendingPower&&(this._pendingPower=void 0),this._pendingDuration!==void 0&&f(this._entityState(e.duration))===this._pendingDuration&&(this._pendingDuration=void 0);let n=m(this._entityState(e.active)),s=m(this._entityState(e.write_enable)),o=m(this._entityState(e.operation_in_progress)),l=this._entityState(e.status),d=ne({active:n,armed:s,operationInProgress:o,statusText:l});this._lastVisualState!==void 0&&this._lastVisualState!==d&&this._confirmEndRestore&&(this._confirmEndRestore=!1,this._confirmTimer&&clearTimeout(this._confirmTimer)),this._lastVisualState=d}let t=this._config?.schedule;t&&(this._pendingSchedulePower!==void 0&&f(this._entityState(t.power))===this._pendingSchedulePower&&(this._pendingSchedulePower=void 0),this._pendingScheduleDuration!==void 0&&f(this._entityState(t.duration))===this._pendingScheduleDuration&&(this._pendingScheduleDuration=void 0));let i=this._config?.dump_to_grid;if(i){this._pendingDumpPower!==void 0&&f(this._entityState(i.export_power))===this._pendingDumpPower&&(this._pendingDumpPower=void 0),this._pendingDumpStopSoc!==void 0&&f(this._entityState(i.stop_soc))===this._pendingDumpStopSoc&&(this._pendingDumpStopSoc=void 0),this._pendingDumpDuration!==void 0&&f(this._entityState(i.duration))===this._pendingDumpDuration&&(this._pendingDumpDuration=void 0);let n=i.schedule;n&&(this._pendingDumpSchedulePower!==void 0&&f(this._entityState(n.power))===this._pendingDumpSchedulePower&&(this._pendingDumpSchedulePower=void 0),this._pendingDumpScheduleStopSoc!==void 0&&f(this._entityState(n.stop_soc))===this._pendingDumpScheduleStopSoc&&(this._pendingDumpScheduleStopSoc=void 0),this._pendingDumpScheduleDuration!==void 0&&f(this._entityState(n.duration))===this._pendingDumpScheduleDuration&&(this._pendingDumpScheduleDuration=void 0));let s=m(this._entityState(i.active)),o=m(this._entityState(i.write_enable)),l=m(this._entityState(i.operation_in_progress)),d=m(this._entityState(i.snapshot_valid)),c=this._entityState(i.status),p=se({active:s,armed:o,operationInProgress:l,snapshotValid:d,statusText:c});this._lastDumpVisualState!==void 0&&this._lastDumpVisualState!==p&&this._confirmEndDump&&(this._confirmEndDump=!1,this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer)),this._lastDumpVisualState=p}if(this._config?.layout==="tabbed"&&this._track===null&&this.hass){let n=this._trackSummary();mt(n.fp.state,n.dump.state)&&(this._track=Ae(n.fp.state,n.dump.state))}}updated(){let e=this._active()||this._scheduleArmed()||this._dumpActive()||this._dumpScheduleArmed();e&&!this._tickTimer?this._tickTimer=setInterval(()=>{this._nowMs=Date.now()},cr):!e&&this._tickTimer&&this._stopTicking()}_stopTicking(){this._tickTimer&&(clearInterval(this._tickTimer),this._tickTimer=void 0)}_active(){let e=this._config?.free_power;return e?m(this._entityState(e.active))===!0:!1}_scheduleArmed(){let e=this._config?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_dumpActive(){let e=this._config?.dump_to_grid;return e?m(this._entityState(e.active))===!0:!1}_dumpScheduleArmed(){let e=this._config?.dump_to_grid?.schedule;return e?m(this._entityState(e.armed))===!0:!1}_freePowerVisualStateForInterlock(){let e=this._config?.free_power;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=this._entityState(e.status);return ne({active:t,armed:i,operationInProgress:n,statusText:s})}_dumpVisualStateForInterlock(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return null;let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status);return se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o})}_entityState(e){if(!(!e||!this.hass))return this.hass.states[e]?.state}_entity(e){if(!(!e||!this.hass))return this.hass.states[e]}_moreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_callService(e,t,i){this.hass?.callService&&this.hass.callService(e,t,i)}_callServiceObj(e){this._callService(e.domain,e.service,e.data)}render(){if(!this._config)return u``;let e=this._config.title??ke;return this._config.layout==="tabbed"?this._renderTabbed(e):u`
      <ha-card>
        <h1 class="card-title">${e}</h1>
        <div class="actions-grid">
          ${this._renderFreePowerTile()}
          ${this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `}_trackSummary(){let e=this._freePowerVisualStateForInterlock(),t=this._dumpVisualStateForInterlock(),i={state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0},n=this._config?.free_power;if(e!==null&&n){let l=this._config?.schedule,d=l?Oe(e,Re({armed:m(this._entityState(l.armed))})):e,c=K(e,t)?"interlocked":d;i={state:c,pill:c,label:this._labelFor(c),statusText:this._entityState(n.status)}}let s=this._config?.dump_to_grid,o=s&&this.hass?{state:"unavailable",pill:"unavailable",label:"Unavailable",statusText:void 0}:{state:"unavailable",pill:"locked",label:"Coming Soon",statusText:void 0};if(t!==null&&s){let l=s.schedule,d=De(t,l?m(this._entityState(l.armed)):null),c=K(t,e)?"interlocked":d;o={state:c,pill:c,label:Ee(c),statusText:this._entityState(s.status)}}return{fp:i,dump:o}}_selectTrack(e){this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndRestore=!1,this._confirmEndDump=!1,this._track=e}_renderTabbed(e){let t=this._trackSummary(),i=this._track??Ae(t.fp.state,t.dump.state),n=i==="free_power"?"dump_to_grid":"free_power",s=i==="free_power"?t.dump:t.fp,o=_t(ft(s.state)),l=o==="fault"?"mdi:alert-circle-outline":o==="warning"?"mdi:alert-outline":"mdi:information-outline";return u`
      <ha-card>
        <div class="tabbed-header">
          <h1 class="card-title">${e}</h1>
          <div class="track-strip">
            <span class="state-pill state-${t.fp.pill}">Free Power · ${t.fp.label}</span>
            <span class="state-pill state-${t.dump.pill}">Dump to Grid · ${t.dump.label}</span>
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
        ${o?u`
              <div class="track-alert track-alert-${o}" role="status">
                <ha-icon icon=${l}></ha-icon>
                <div class="track-alert-text">${bt(gt(n),s.label,s.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${()=>this._selectTrack(n)}>Show</button>
              </div>
            `:h}
        <div class="actions-grid is-tabbed">
          ${i==="free_power"?this._renderFreePowerTile():this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `}_renderFreePowerTile(){let e=this._config?.free_power;if(!e||!this.hass)return this._renderFreePowerUnavailable("Free Power is not configured on this card.");let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=ne({active:t,armed:i,operationInProgress:n,statusText:o});if(l==="unavailable")return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");let d=this._config?.schedule,c=d?m(this._entityState(d.armed)):null,p=Re({armed:c}),y=d?Oe(l,p):l,_=this._dumpVisualStateForInterlock(),w=K(l,_),k=w?"interlocked":y,$=w?Te("Dump to Grid",_):void 0,D=this._entity(e.max_charge_power),b=this._entity(e.duration),U=this._pendingPower??f(D?.state),S=this._pendingDuration??f(b?.state),de=this._iconFor(k),ce=this._labelFor(k);return u`
      <div class="tile free-power-tile state-${k}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${de}></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-${k}">${ce}</span>
        </div>

        <div class="free-power-body">
          ${d&&p==="armed"?this._renderScheduleBanner(d):h}
          ${w?this._renderInterlockBanner($):h}

          ${this._renderFreePowerBody(l,{fp:e,schedule:d,statusText:o,snapshotValid:s,interlocked:w,stagedPowerW:U,stagedDurationMin:S,stagedPowerEntity:D,stagedDurationEntity:b})}
        </div>
      </div>
    `}_iconFor(e){if(e==="scheduled")return"mdi:calendar-clock";if(e==="interlocked")return"mdi:lock-outline";switch(e){case"active":return"mdi:flash";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:flash-off-outline";default:return"mdi:flash-outline"}}_labelFor(e){return e==="scheduled"?"Scheduled":e==="interlocked"?"Interlocked":nt(e)}_renderInterlockBanner(e){return u`
      <div class="interlock-banner">
        <ha-icon icon="mdi:lock-outline"></ha-icon>
        <div class="interlock-banner-text">${e}</div>
      </div>
    `}_renderFreePowerUnavailable(e){return u`
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
    `}_renderFreePowerBody(e,t){switch(e){case"active":return this._renderActiveBody(t);case"busy":return this._renderBusyBody(t.statusText,t.fp.status);case"deferred":return this._renderDeferredBody(t.statusText,t.fp.status);case"recovery_attention":return this._renderAttentionBody(t);default:return this._renderReadyOrArmedBody(e,t)}}_renderReadyOrArmedBody(e,t){let i=!!t.schedule,n=i?this._mode:"now";return u`
      ${i?this._renderModeSelector():h}
      ${n==="later"&&t.schedule?this._renderLaterPanel(t.schedule):this._renderNowPanel(e,t)}
    `}_renderModeSelector(){let e=this._mode==="now";return u`
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
    `}_renderNowPanel(e,t){let i=e==="armed",n=Q(it(e),t.interlocked),s=Q(at(e),t.interlocked);return u`
      <p class="tile-description">Charge the battery from free/zero-cost grid energy.</p>

      ${this._renderNumberControl({label:"Max Charge Power",icon:"mdi:flash",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingPower=o,onCommit:o=>this._commitNumber("power",o,t.fp.max_charge_power)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDuration=o,onCommit:o=>this._commitNumber("duration",o,t.fp.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(t.statusText,t.fp.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!s}
          @click=${()=>this._toggleArm(t.fp.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Free Power"}
        </button>
        <button
          class="start-button"
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.fp.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.status),c=this._entityState(e.last_result),p=this._pendingScheduleDuration??f(o?.state),y=this._pendingSchedulePower??f(l?.state),_=d?.attributes?.effective_power_limit_w,w=typeof _=="number"?_:f(typeof _=="string"?_:void 0),k=this._numericAttr(l?.attributes?.max,8e3),$=yt(k,w),D=Pe(c),b=Ce(c),U=!i&&s!==null&&s.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${S=>this._handleScheduleStartChange(e.start,S.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Power",icon:"mdi:flash",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,maxOverride:$,formatValue:T,disabled:i||!l,onPreview:S=>this._pendingSchedulePower=S,onCommit:S=>this._commitScheduleNumber("power",S,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:S=>this._pendingScheduleDuration=S,onCommit:S=>this._commitScheduleNumber("duration",S,e.duration)})}

      ${c?u`<p class="firmware-note ${D||b?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${i||!U}
          @click=${()=>this._callServiceObj(Me(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the manual Free Power write-enable switch - Home Assistant arms and starts the inverter automatically when the time comes."}
      </p>
    `}_renderScheduleBanner(e){let t=this._entityState(e.start),i=M(t),n=f(this._entityState(e.duration)),s=f(this._entityState(e.power)),o=i?J(i.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${i?Ve(i):"--"} • ${T(s)} • ${F(n)}
          </div>
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
      <div class="active-hero">
        <div class="active-hero-time">${n??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${T(e.stagedPowerW)} target • ends ${i?this._formatClock(i):t??"--"}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${e.snapshotValid?"mdi:content-save-check-outline":"mdi:content-save-alert-outline"}></ha-icon>
        <span>${e.snapshotValid?"Original settings snapshot saved":"No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(e.statusText,e.fp.status,{alwaysShow:!0})}
      ${this._renderDiagnosticsDetails(e.fp)}
      ${this._renderEndRestoreButton(e.fp.end_restore,"End & Restore Now",!1,$e("active"))}
    `}_renderBusyBody(e,t){return u`
      <div class="transition-panel">
        <ha-icon class="spin" icon="mdi:autorenew"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Working...</div>
          ${this._renderTransitionDetail(e??"Free Power is mid-transaction.",t)}
        </div>
      </div>
      <p class="transition-hint">Controls are disabled while a transaction is in flight - this clears on its own.</p>
    `}_renderDeferredBody(e,t){return u`
      <div class="transition-panel deferred">
        <ha-icon icon="mdi:timer-sand"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Waiting for inverter bus</div>
          ${this._renderTransitionDetail(e??"Modbus bus busy - the watchdog will retry.",t)}
        </div>
      </div>
      <p class="transition-hint">This is expected occasionally - the watchdog retries automatically. No action needed.</p>
    `}_renderAttentionBody(e){let t=ut({statusText:e.statusText,snapshotValid:e.snapshotValid});return u`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(e.statusText??"Free Power requires operator attention.",e.fp.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${t.explanation??"No automatic retry. Starting a new Free Power session is disabled until this clears."}
      </p>
      ${t.actionable?this._renderEndRestoreButton(e.fp.end_restore,t.actionLabel??"End & Restore Now",t.secondary,$e("recovery_attention")):h}
    `}_renderTransitionDetail(e,t){return u`
      <div
        class="transition-detail clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(t)}
        @keydown=${i=>{(i.key==="Enter"||i.key===" ")&&(i.preventDefault(),this._moreInfo(t))}}
      >
        ${e}
      </div>
    `}_renderStatusLine(e,t,i){return!(i?.alwaysShow||!!e&&e!=="Inactive")||!e?h:u`
      <p
        class="firmware-note clickable"
        tabindex="0"
        role="button"
        @click=${()=>this._moreInfo(t)}
        @keydown=${s=>{(s.key==="Enter"||s.key===" ")&&(s.preventDefault(),this._moreInfo(t))}}
      >
        ${e}
      </p>
    `}_renderDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndRestoreButton(e,t,i,n){let s=this._confirmEndRestore;return u`
      <button
        class="end-restore-button ${i?"secondary":""} ${s?"confirming":""}"
        ?disabled=${!n}
        @click=${()=>this._handleEndRestoreClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${s?"Tap again to End & Restore":t}
        ${s?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
      </button>
    `}_handleEndRestoreClick(e){if(!this._confirmEndRestore){this._confirmEndRestore=!0,this._confirmTimer=setTimeout(()=>{this._confirmEndRestore=!1},le);return}this._confirmTimer&&clearTimeout(this._confirmTimer),this._confirmEndRestore=!1,this._callService("button","press",{entity_id:e})}_toggleArm(e,t){this._callService("switch",t?"turn_off":"turn_on",{entity_id:e})}_commitNumber(e,t,i){e==="power"?this._pendingPower=t:this._pendingDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_commitDumpNumber(e,t,i){e==="power"?this._pendingDumpPower=t:e==="stop_soc"?this._pendingDumpStopSoc=t:this._pendingDumpDuration=t,this._callService("number","set_value",{entity_id:i,value:t})}_handleEndDumpClick(e){if(!this._confirmEndDump){this._confirmEndDump=!0,this._confirmDumpTimer=setTimeout(()=>{this._confirmEndDump=!1},le);return}this._confirmDumpTimer&&clearTimeout(this._confirmDumpTimer),this._confirmEndDump=!1,this._callService("button","press",{entity_id:e})}_numericAttr(e,t){if(typeof e=="number"&&Number.isFinite(e))return e;if(typeof e=="string"){let i=f(e);if(i!==null)return i}return t}_formatClock(e){let t=e.getHours().toString().padStart(2,"0"),i=e.getMinutes().toString().padStart(2,"0");return`${t}:${i}`}_renderNumberControl(e){let t=e.entity?.attributes??{},i=this._numericAttr(t.min,e.fallbackMin),n=e.maxOverride??this._numericAttr(t.max,e.fallbackMax),s=this._numericAttr(t.step,e.fallbackStep),o=e.value??i,l=e.disabled??!e.entity,d=n>i?Math.max(0,Math.min(100,(o-i)/(n-i)*100)):0;return u`
      <div class="number-control">
        <div class="number-control-label">
          <ha-icon icon=${e.icon}></ha-icon>
          <span>${e.label}</span>
          <span class="number-control-value">${e.formatValue(o)}</span>
        </div>
        <input
          type="range"
          class="number-control-slider"
          style="--eaa-slider-fill:${d}%"
          min=${i}
          max=${n}
          step=${s}
          .value=${String(o)}
          ?disabled=${l}
          @input=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onPreview(p)}}
          @change=${c=>{let p=Number(c.target.value);Number.isFinite(p)&&e.onCommit(p)}}
        />
      </div>
    `}_renderDumpToGridTile(){let e=this._config?.dump_to_grid;if(!e||!this.hass)return this._renderDumpToGridLockedShell();let t=m(this._entityState(e.active)),i=m(this._entityState(e.write_enable)),n=m(this._entityState(e.operation_in_progress)),s=m(this._entityState(e.snapshot_valid)),o=this._entityState(e.status),l=se({active:t,armed:i,operationInProgress:n,snapshotValid:s,statusText:o});if(l==="unavailable")return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");let d=e.schedule,c=d?m(this._entityState(d.armed)):null,p=De(l,c),y=this._freePowerVisualStateForInterlock(),_=K(l,y),w=_?"interlocked":p,k=_?Te("Free Power",y):void 0,$=this._entity(e.export_power),D=this._entity(e.stop_soc),b=this._entity(e.duration),U=this._pendingDumpPower??f($?.state),S=this._pendingDumpStopSoc??f(D?.state),de=this._pendingDumpDuration??f(b?.state),ce=this._dumpIconFor(w),xt=Ee(w);return u`
      <div class="tile dump-to-grid-tile state-${w}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${ce}></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-${w}">${xt}</span>
        </div>

        <div class="dump-to-grid-body">
          ${d&&c===!0?this._renderDumpScheduleBanner(d):h}
          ${_?this._renderInterlockBanner(k):h}

          ${this._renderDumpBody(l,{dump:e,statusText:o,snapshotValid:s,interlocked:_,stagedPowerW:U,stagedStopSoc:S,stagedDurationMin:de,stagedPowerEntity:$,stagedStopSocEntity:D,stagedDurationEntity:b})}
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
    `}_dumpIconFor(e){switch(e){case"scheduled":return"mdi:calendar-clock";case"interlocked":return"mdi:lock-outline";case"active":return"mdi:transmission-tower-export";case"armed":return"mdi:shield-flash-outline";case"busy":return"mdi:autorenew";case"deferred":return"mdi:timer-sand";case"recovery_attention":return"mdi:alert-circle-outline";case"unavailable":return"mdi:transmission-tower-off";default:return"mdi:transmission-tower-export"}}_renderDumpUnavailable(e){return u`
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
    `}_renderDumpBody(e,t){switch(e){case"active":return this._renderDumpActiveBody(t);case"busy":return this._renderBusyBody(t.statusText??"Dump to Grid is mid-transaction.",t.dump.status);case"deferred":return this._renderDumpDeferredBody(t);case"recovery_attention":return this._renderDumpAttentionBody(t);default:return this._renderDumpReadyOrArmedBody(e,t)}}_renderDumpReadyOrArmedBody(e,t){let i=t.dump.schedule,n=i?this._dumpMode:"now";return u`
      ${i?this._renderDumpModeSelector():h}
      ${n==="later"&&i?this._renderDumpLaterPanel(i):this._renderDumpNowPanel(e,t)}
      ${this._renderDumpLastEndReason(t.dump)}
    `}_renderDumpModeSelector(){let e=this._dumpMode==="now";return u`
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
    `}_renderDumpNowPanel(e,t){let i=e==="armed",n=Q(st(e),t.interlocked),s=Q(ot(e),t.interlocked);return u`
      <p class="tile-description">Export stored battery energy to the grid down to a chosen floor.</p>

      ${this._renderNumberControl({label:"Export Power",icon:"mdi:transmission-tower-export",entity:t.stagedPowerEntity,value:t.stagedPowerW,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:t.interlocked,onPreview:o=>this._pendingDumpPower=o,onCommit:o=>this._commitDumpNumber("power",o,t.dump.export_power)})}
      ${this._renderNumberControl({label:"Stop SOC",icon:"mdi:battery-arrow-down",entity:t.stagedStopSocEntity,value:t.stagedStopSoc,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:t.interlocked,onPreview:o=>this._pendingDumpStopSoc=o,onCommit:o=>this._commitDumpNumber("stop_soc",o,t.dump.stop_soc)})}
      ${this._renderNumberControl({label:"Duration",icon:"mdi:timer-outline",entity:t.stagedDurationEntity,value:t.stagedDurationMin,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:t.interlocked,onPreview:o=>this._pendingDumpDuration=o,onCommit:o=>this._commitDumpNumber("duration",o,t.dump.duration)})}

      <div class="readiness-row">
        <ha-icon icon=${i?"mdi:shield-check":"mdi:shield-outline"}></ha-icon>
        <span>${i?"Armed - ready to start":"Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(t.statusText,t.dump.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${i?"is-armed":""}"
          ?disabled=${!s}
          @click=${()=>this._toggleArm(t.dump.write_enable,i)}
        >
          <ha-icon icon=${i?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
          ${i?"Disarm":"Arm Dump to Grid"}
        </button>
        <button
          class="start-button"
          ?disabled=${!n}
          @click=${()=>this._callService("button","press",{entity_id:t.dump.start})}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `}_renderDumpLaterPanel(e){let t=m(this._entityState(e.armed)),i=Ne(t),n=this._entityState(e.start),s=M(n),o=this._entity(e.duration),l=this._entity(e.power),d=this._entity(e.stop_soc),c=this._entityState(e.last_result),p=this._pendingDumpScheduleDuration??f(o?.state),y=this._pendingDumpSchedulePower??f(l?.state),_=this._pendingDumpScheduleStopSoc??f(d?.state),w=Pe(c)||!!c&&/^FAILED/i.test(c.trim()),k=Ce(c),$=!!l&&!!o&&!!d&&t!==null,D=$&&!i&&s!==null&&s.getTime()>this._nowMs;return u`
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${s?this._toDatetimeLocalValue(s):""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${i}
          @change=${b=>this._handleScheduleStartChange(e.start,b.target.value)}
        />
      </div>

      ${this._renderNumberControl({label:"Scheduled Export Power",icon:"mdi:transmission-tower-export",entity:l,value:y,fallbackMin:500,fallbackMax:8e3,fallbackStep:100,formatValue:T,disabled:i||!l,onPreview:b=>this._pendingDumpSchedulePower=b,onCommit:b=>this._commitDumpScheduleNumber("power",b,e.power)})}
      ${this._renderNumberControl({label:"Scheduled Stop SOC",icon:"mdi:battery-arrow-down",entity:d,value:_,fallbackMin:10,fallbackMax:90,fallbackStep:1,formatValue:L,disabled:i||!d,onPreview:b=>this._pendingDumpScheduleStopSoc=b,onCommit:b=>this._commitDumpScheduleNumber("stop_soc",b,e.stop_soc)})}
      ${this._renderNumberControl({label:"Scheduled Duration",icon:"mdi:timer-outline",entity:o,value:p,fallbackMin:1,fallbackMax:240,fallbackStep:1,formatValue:F,disabled:i||!o,onPreview:b=>this._pendingDumpScheduleDuration=b,onCommit:b=>this._commitDumpScheduleNumber("duration",b,e.duration)})}

      ${$?h:u`<p class="firmware-note is-warning">
            Scheduled Dump to Grid helpers are unavailable - is ecco_dump_to_grid_schedule.yaml installed?
          </p>`}
      ${c?u`<p class="firmware-note ${w||k?"is-warning":""}">${c}</p>`:h}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${!D}
          @click=${()=>this._callServiceObj(Me(e.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${i?"Fields are locked while this schedule is armed - cancel it above to edit, then re-arm.":"Arm Schedule never touches the Dump to Grid write-enable switch. At the start time Home Assistant stages these values, arms and presses Start; the firmware re-checks Stop SOC, charging TOU slots and Free Power itself. Arming is refused if it overlaps an armed Free Power schedule or a charging TOU slot."}
      </p>
    `}_renderDumpScheduleBanner(e){let t=M(this._entityState(e.start)),i=f(this._entityState(e.duration)),n=f(this._entityState(e.power)),s=f(this._entityState(e.stop_soc)),o=t?J(t.getTime(),this._nowMs):null;return u`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${t?Ve(t):"--"} • ${T(n)} • stop
            ${L(s)} • ${F(i)}
          </div>
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
      <div class="active-hero">
        <div class="active-hero-time">${n??"--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${T(o)} export • ends ${i?this._formatClock(i):t??"--"}
      </div>
      <div class="active-secondary-line">
        Battery: ${L(s)} • stops at ${L(l)}
      </div>

      <div class="readiness-row">
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
      ${this._renderEndDumpButton(e.dump.end_restore,"End & Restore Now",oe("recovery_attention"))}
    `}_renderDumpRecoveryPanel(e){let t=m(this._entityState(e.recovery_arm))===!0,i=this._entityState(e.recovery_state);return u`
      <div class="dump-recovery-panel">
        ${i&&i!=="unknown"&&i!=="unavailable"?u`<p class="firmware-note">${i}</p>`:h}
        <div class="action-row">
          <button
            class="arm-toggle ${t?"is-armed":""}"
            @click=${()=>this._toggleArm(e.recovery_arm,t)}
          >
            <ha-icon icon=${t?"mdi:shield-key":"mdi:shield-key-outline"}></ha-icon>
            ${t?"Disarm Recovery":"Arm Recovery"}
          </button>
        </div>
        <div class="action-row">
          <button
            class="start-button"
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_force_restore})}
          >
            <ha-icon icon="mdi:backup-restore"></ha-icon>
            Force Restore Original
          </button>
          <button
            class="arm-toggle"
            ?disabled=${!t}
            @click=${()=>this._callService("button","press",{entity_id:e.recovery_accept})}
          >
            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
            Accept Current State
          </button>
        </div>
      </div>
    `}_renderDumpDiagnosticsDetails(e){let t=[],i=(n,s)=>{let o=f(this._entityState(s));o!==null&&t.push({label:n,value:o.toString()})};return i("Starts",e.start_attempts),i("Started OK",e.start_successes),i("Restored OK",e.restore_successes),i("Failures",e.failures),t.length===0?h:u`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${t.map(n=>u`<span class="diagnostic-chip">${n.label}: ${n.value}</span>`)}
        </div>
      </details>
    `}_renderEndDumpButton(e,t,i){let n=this._confirmEndDump;return u`
      <button
        class="end-restore-button ${n?"confirming":""}"
        ?disabled=${!i}
        @click=${()=>this._handleEndDumpClick(e)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${n?"Tap again to End & Restore":t}
        ${n?u`<span class="confirm-progress" style="animation-duration:${le}ms"></span>`:h}
      </button>
    `}};g.styles=pe`
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
  `,v([ie({attribute:!1})],g.prototype,"hass",2),v([x()],g.prototype,"_config",2),v([x()],g.prototype,"_pendingPower",2),v([x()],g.prototype,"_pendingDuration",2),v([x()],g.prototype,"_pendingSchedulePower",2),v([x()],g.prototype,"_pendingScheduleDuration",2),v([x()],g.prototype,"_confirmEndRestore",2),v([x()],g.prototype,"_pendingDumpPower",2),v([x()],g.prototype,"_pendingDumpStopSoc",2),v([x()],g.prototype,"_pendingDumpDuration",2),v([x()],g.prototype,"_confirmEndDump",2),v([x()],g.prototype,"_dumpMode",2),v([x()],g.prototype,"_pendingDumpSchedulePower",2),v([x()],g.prototype,"_pendingDumpScheduleStopSoc",2),v([x()],g.prototype,"_pendingDumpScheduleDuration",2),v([x()],g.prototype,"_nowMs",2),v([x()],g.prototype,"_mode",2),v([x()],g.prototype,"_track",2),g=v([rt("ecco-energy-actions-card")],g);window.customCards=[...window.customCards??[],{type:"ecco-energy-actions-card",name:"ECCO Energy Actions Card",description:"Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",preview:!1}];export{g as EccoEnergyActionsCard};
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
