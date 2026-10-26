var kr=Object.defineProperty;var Sr=Object.getOwnPropertyDescriptor;var q=(e,t,r,n)=>{for(var o=n>1?void 0:n?Sr(t,r):t,s=e.length-1,i;s>=0;s--)(i=e[s])&&(o=(n?i(t,r,o):i(o))||o);return n&&o&&kr(t,r,o),o};var Te=globalThis,Ce=Te.ShadowRoot&&(Te.ShadyCSS===void 0||Te.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,Ye=Symbol(),_t=new WeakMap,be=class{constructor(t,r,n){if(this._$cssResult$=!0,n!==Ye)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=r}get styleSheet(){let t=this.o,r=this.t;if(Ce&&t===void 0){let n=r!==void 0&&r.length===1;n&&(t=_t.get(r)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),n&&_t.set(r,t))}return t}toString(){return this.cssText}},kt=e=>new be(typeof e=="string"?e:e+"",void 0,Ye),qe=(e,...t)=>{let r=e.length===1?e[0]:t.reduce((n,o,s)=>n+(i=>{if(i._$cssResult$===!0)return i.cssText;if(typeof i=="number")return i;throw Error("Value passed to 'css' function must be a 'css' function result: "+i+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(o)+e[s+1],e[0]);return new be(r,e,Ye)},St=(e,t)=>{if(Ce)e.adoptedStyleSheets=t.map(r=>r instanceof CSSStyleSheet?r:r.styleSheet);else for(let r of t){let n=document.createElement("style"),o=Te.litNonce;o!==void 0&&n.setAttribute("nonce",o),n.textContent=r.cssText,e.appendChild(n)}},Ke=Ce?e=>e:e=>e instanceof CSSStyleSheet?(t=>{let r="";for(let n of t.cssRules)r+=n.cssText;return kt(r)})(e):e;var{is:Ar,defineProperty:Er,getOwnPropertyDescriptor:Mr,getOwnPropertyNames:Tr,getOwnPropertySymbols:Cr,getPrototypeOf:Rr}=Object,Re=globalThis,At=Re.trustedTypes,Pr=At?At.emptyScript:"",Nr=Re.reactiveElementPolyfillSupport,xe=(e,t)=>e,we={toAttribute(e,t){switch(t){case Boolean:e=e?Pr:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,t){let r=e;switch(t){case Boolean:r=e!==null;break;case Number:r=e===null?null:Number(e);break;case Object:case Array:try{r=JSON.parse(e)}catch{r=null}}return r}},Pe=(e,t)=>!Ar(e,t),Et={attribute:!0,type:String,converter:we,reflect:!1,useDefault:!1,hasChanged:Pe};Symbol.metadata??=Symbol("metadata"),Re.litPropertyMetadata??=new WeakMap;var B=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,r=Et){if(r.state&&(r.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((r=Object.create(r)).wrapped=!0),this.elementProperties.set(t,r),!r.noAccessor){let n=Symbol(),o=this.getPropertyDescriptor(t,n,r);o!==void 0&&Er(this.prototype,t,o)}}static getPropertyDescriptor(t,r,n){let{get:o,set:s}=Mr(this.prototype,t)??{get(){return this[r]},set(i){this[r]=i}};return{get:o,set(i){let a=o?.call(this);s?.call(this,i),this.requestUpdate(t,a,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??Et}static _$Ei(){if(this.hasOwnProperty(xe("elementProperties")))return;let t=Rr(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(xe("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(xe("properties"))){let r=this.properties,n=[...Tr(r),...Cr(r)];for(let o of n)this.createProperty(o,r[o])}let t=this[Symbol.metadata];if(t!==null){let r=litPropertyMetadata.get(t);if(r!==void 0)for(let[n,o]of r)this.elementProperties.set(n,o)}this._$Eh=new Map;for(let[r,n]of this.elementProperties){let o=this._$Eu(r,n);o!==void 0&&this._$Eh.set(o,r)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let r=[];if(Array.isArray(t)){let n=new Set(t.flat(1/0).reverse());for(let o of n)r.unshift(Ke(o))}else t!==void 0&&r.push(Ke(t));return r}static _$Eu(t,r){let n=r.attribute;return n===!1?void 0:typeof n=="string"?n:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,r=this.constructor.elementProperties;for(let n of r.keys())this.hasOwnProperty(n)&&(t.set(n,this[n]),delete this[n]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return St(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,r,n){this._$AK(t,n)}_$ET(t,r){let n=this.constructor.elementProperties.get(t),o=this.constructor._$Eu(t,n);if(o!==void 0&&n.reflect===!0){let s=(n.converter?.toAttribute!==void 0?n.converter:we).toAttribute(r,n.type);this._$Em=t,s==null?this.removeAttribute(o):this.setAttribute(o,s),this._$Em=null}}_$AK(t,r){let n=this.constructor,o=n._$Eh.get(t);if(o!==void 0&&this._$Em!==o){let s=n.getPropertyOptions(o),i=typeof s.converter=="function"?{fromAttribute:s.converter}:s.converter?.fromAttribute!==void 0?s.converter:we;this._$Em=o;let a=i.fromAttribute(r,s.type);this[o]=a??this._$Ej?.get(o)??a,this._$Em=null}}requestUpdate(t,r,n,o=!1,s){if(t!==void 0){let i=this.constructor;if(o===!1&&(s=this[t]),n??=i.getPropertyOptions(t),!((n.hasChanged??Pe)(s,r)||n.useDefault&&n.reflect&&s===this._$Ej?.get(t)&&!this.hasAttribute(i._$Eu(t,n))))return;this.C(t,r,n)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,r,{useDefault:n,reflect:o,wrapped:s},i){n&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,i??r??this[t]),s!==!0||i!==void 0)||(this._$AL.has(t)||(this.hasUpdated||n||(r=void 0),this._$AL.set(t,r)),o===!0&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(r){Promise.reject(r)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[o,s]of this._$Ep)this[o]=s;this._$Ep=void 0}let n=this.constructor.elementProperties;if(n.size>0)for(let[o,s]of n){let{wrapped:i}=s,a=this[o];i!==!0||this._$AL.has(o)||a===void 0||this.C(o,void 0,s,a)}}let t=!1,r=this._$AL;try{t=this.shouldUpdate(r),t?(this.willUpdate(r),this._$EO?.forEach(n=>n.hostUpdate?.()),this.update(r)):this._$EM()}catch(n){throw t=!1,this._$EM(),n}t&&this._$AE(r)}willUpdate(t){}_$AE(t){this._$EO?.forEach(r=>r.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(r=>this._$ET(r,this[r])),this._$EM()}updated(t){}firstUpdated(t){}};B.elementStyles=[],B.shadowRootOptions={mode:"open"},B[xe("elementProperties")]=new Map,B[xe("finalized")]=new Map,Nr?.({ReactiveElement:B}),(Re.reactiveElementVersions??=[]).push("2.1.2");var rt=globalThis,Mt=e=>e,Ne=rt.trustedTypes,Tt=Ne?Ne.createPolicy("lit-html",{createHTML:e=>e}):void 0,It="$lit$",K=`lit$${Math.random().toFixed(9).slice(2)}$`,Ot="?"+K,Fr=`<${Ot}>`,se=document,ve=()=>se.createComment(""),_e=e=>e===null||typeof e!="object"&&typeof e!="function",nt=Array.isArray,Ir=e=>nt(e)||typeof e?.[Symbol.iterator]=="function",Xe=`[ 	
\f\r]`,$e=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Ct=/-->/g,Rt=/>/g,ne=RegExp(`>|${Xe}(?:([^\\s"'>=/]+)(${Xe}*=${Xe}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Pt=/'/g,Nt=/"/g,Lt=/^(?:script|style|textarea|title)$/i,ot=e=>(t,...r)=>({_$litType$:e,strings:t,values:r}),N=ot(1),w=ot(2),kn=ot(3),ie=Symbol.for("lit-noChange"),y=Symbol.for("lit-nothing"),Ft=new WeakMap,oe=se.createTreeWalker(se,129);function Ht(e,t){if(!nt(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return Tt!==void 0?Tt.createHTML(t):t}var Or=(e,t)=>{let r=e.length-1,n=[],o,s=t===2?"<svg>":t===3?"<math>":"",i=$e;for(let a=0;a<r;a++){let l=e[a],c,p,u=-1,f=0;for(;f<l.length&&(i.lastIndex=f,p=i.exec(l),p!==null);)f=i.lastIndex,i===$e?p[1]==="!--"?i=Ct:p[1]!==void 0?i=Rt:p[2]!==void 0?(Lt.test(p[2])&&(o=RegExp("</"+p[2],"g")),i=ne):p[3]!==void 0&&(i=ne):i===ne?p[0]===">"?(i=o??$e,u=-1):p[1]===void 0?u=-2:(u=i.lastIndex-p[2].length,c=p[1],i=p[3]===void 0?ne:p[3]==='"'?Nt:Pt):i===Nt||i===Pt?i=ne:i===Ct||i===Rt?i=$e:(i=ne,o=void 0);let m=i===ne&&e[a+1].startsWith("/>")?" ":"";s+=i===$e?l+Fr:u>=0?(n.push(c),l.slice(0,u)+It+l.slice(u)+K+m):l+K+(u===-2?a:m)}return[Ht(e,s+(e[r]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),n]},ke=class e{constructor({strings:t,_$litType$:r},n){let o;this.parts=[];let s=0,i=0,a=t.length-1,l=this.parts,[c,p]=Or(t,r);if(this.el=e.createElement(c,n),oe.currentNode=this.el.content,r===2||r===3){let u=this.el.content.firstChild;u.replaceWith(...u.childNodes)}for(;(o=oe.nextNode())!==null&&l.length<a;){if(o.nodeType===1){if(o.hasAttributes())for(let u of o.getAttributeNames())if(u.endsWith(It)){let f=p[i++],m=o.getAttribute(u).split(K),g=/([.?@])?(.*)/.exec(f);l.push({type:1,index:s,name:g[2],strings:m,ctor:g[1]==="."?Qe:g[1]==="?"?Je:g[1]==="@"?et:ue}),o.removeAttribute(u)}else u.startsWith(K)&&(l.push({type:6,index:s}),o.removeAttribute(u));if(Lt.test(o.tagName)){let u=o.textContent.split(K),f=u.length-1;if(f>0){o.textContent=Ne?Ne.emptyScript:"";for(let m=0;m<f;m++)o.append(u[m],ve()),oe.nextNode(),l.push({type:2,index:++s});o.append(u[f],ve())}}}else if(o.nodeType===8)if(o.data===Ot)l.push({type:2,index:s});else{let u=-1;for(;(u=o.data.indexOf(K,u+1))!==-1;)l.push({type:7,index:s}),u+=K.length-1}s++}}static createElement(t,r){let n=se.createElement("template");return n.innerHTML=t,n}};function ce(e,t,r=e,n){if(t===ie)return t;let o=n!==void 0?r._$Co?.[n]:r._$Cl,s=_e(t)?void 0:t._$litDirective$;return o?.constructor!==s&&(o?._$AO?.(!1),s===void 0?o=void 0:(o=new s(e),o._$AT(e,r,n)),n!==void 0?(r._$Co??=[])[n]=o:r._$Cl=o),o!==void 0&&(t=ce(e,o._$AS(e,t.values),o,n)),t}var Ze=class{constructor(t,r){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=r}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:r},parts:n}=this._$AD,o=(t?.creationScope??se).importNode(r,!0);oe.currentNode=o;let s=oe.nextNode(),i=0,a=0,l=n[0];for(;l!==void 0;){if(i===l.index){let c;l.type===2?c=new Se(s,s.nextSibling,this,t):l.type===1?c=new l.ctor(s,l.name,l.strings,this,t):l.type===6&&(c=new tt(s,this,t)),this._$AV.push(c),l=n[++a]}i!==l?.index&&(s=oe.nextNode(),i++)}return oe.currentNode=se,o}p(t){let r=0;for(let n of this._$AV)n!==void 0&&(n.strings!==void 0?(n._$AI(t,n,r),r+=n.strings.length-2):n._$AI(t[r])),r++}},Se=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,r,n,o){this.type=2,this._$AH=y,this._$AN=void 0,this._$AA=t,this._$AB=r,this._$AM=n,this.options=o,this._$Cv=o?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,r=this._$AM;return r!==void 0&&t?.nodeType===11&&(t=r.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,r=this){t=ce(this,t,r),_e(t)?t===y||t==null||t===""?(this._$AH!==y&&this._$AR(),this._$AH=y):t!==this._$AH&&t!==ie&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):Ir(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==y&&_e(this._$AH)?this._$AA.nextSibling.data=t:this.T(se.createTextNode(t)),this._$AH=t}$(t){let{values:r,_$litType$:n}=t,o=typeof n=="number"?this._$AC(t):(n.el===void 0&&(n.el=ke.createElement(Ht(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===o)this._$AH.p(r);else{let s=new Ze(o,this),i=s.u(this.options);s.p(r),this.T(i),this._$AH=s}}_$AC(t){let r=Ft.get(t.strings);return r===void 0&&Ft.set(t.strings,r=new ke(t)),r}k(t){nt(this._$AH)||(this._$AH=[],this._$AR());let r=this._$AH,n,o=0;for(let s of t)o===r.length?r.push(n=new e(this.O(ve()),this.O(ve()),this,this.options)):n=r[o],n._$AI(s),o++;o<r.length&&(this._$AR(n&&n._$AB.nextSibling,o),r.length=o)}_$AR(t=this._$AA.nextSibling,r){for(this._$AP?.(!1,!0,r);t!==this._$AB;){let n=Mt(t).nextSibling;Mt(t).remove(),t=n}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},ue=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,r,n,o,s){this.type=1,this._$AH=y,this._$AN=void 0,this.element=t,this.name=r,this._$AM=o,this.options=s,n.length>2||n[0]!==""||n[1]!==""?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=y}_$AI(t,r=this,n,o){let s=this.strings,i=!1;if(s===void 0)t=ce(this,t,r,0),i=!_e(t)||t!==this._$AH&&t!==ie,i&&(this._$AH=t);else{let a=t,l,c;for(t=s[0],l=0;l<s.length-1;l++)c=ce(this,a[n+l],r,l),c===ie&&(c=this._$AH[l]),i||=!_e(c)||c!==this._$AH[l],c===y?t=y:t!==y&&(t+=(c??"")+s[l+1]),this._$AH[l]=c}i&&!o&&this.j(t)}j(t){t===y?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},Qe=class extends ue{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===y?void 0:t}},Je=class extends ue{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==y)}},et=class extends ue{constructor(t,r,n,o,s){super(t,r,n,o,s),this.type=5}_$AI(t,r=this){if((t=ce(this,t,r,0)??y)===ie)return;let n=this._$AH,o=t===y&&n!==y||t.capture!==n.capture||t.once!==n.once||t.passive!==n.passive,s=t!==y&&(n===y||o);o&&this.element.removeEventListener(this.name,this,n),s&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},tt=class{constructor(t,r,n){this.element=t,this.type=6,this._$AN=void 0,this._$AM=r,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(t){ce(this,t)}};var Lr=rt.litHtmlPolyfillSupport;Lr?.(ke,Se),(rt.litHtmlVersions??=[]).push("3.3.3");var Ut=(e,t,r)=>{let n=r?.renderBefore??t,o=n._$litPart$;if(o===void 0){let s=r?.renderBefore??null;n._$litPart$=o=new Se(t.insertBefore(ve(),s),s,void 0,r??{})}return o._$AI(e),o};var st=globalThis,X=class extends B{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){let r=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=Ut(r,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return ie}};X._$litElement$=!0,X.finalized=!0,st.litElementHydrateSupport?.({LitElement:X});var Hr=st.litElementPolyfillSupport;Hr?.({LitElement:X});(st.litElementVersions??=[]).push("4.2.2");var zt=e=>(t,r)=>{r!==void 0?r.addInitializer(()=>{customElements.define(e,t)}):customElements.define(e,t)};var Ur={attribute:!0,type:String,converter:we,reflect:!1,hasChanged:Pe},zr=(e=Ur,t,r)=>{let{kind:n,metadata:o}=r,s=globalThis.litPropertyMetadata.get(o);if(s===void 0&&globalThis.litPropertyMetadata.set(o,s=new Map),n==="setter"&&((e=Object.create(e)).wrapped=!0),s.set(r.name,e),n==="accessor"){let{name:i}=r;return{set(a){let l=t.get.call(this);t.set.call(this,a),this.requestUpdate(i,l,e,!0,a)},init(a){return a!==void 0&&this.C(i,void 0,e,a),a}}}if(n==="setter"){let{name:i}=r;return function(a){let l=this[i];t.call(this,a),this.requestUpdate(i,l,e,!0,a)}}throw Error("Unsupported decorator location: "+n)};function Fe(e){return(t,r)=>typeof r=="object"?zr(e,t,r):((n,o,s)=>{let i=o.hasOwnProperty(s);return o.constructor.createProperty(s,n),i?Object.getOwnPropertyDescriptor(o,s):void 0})(e,t,r)}function de(e){return Fe({...e,state:!0,attribute:!1})}function Dt(e){return e?(Array.isArray(e)?e:[e]).filter(r=>!!r&&!!r.power):[]}var Wt=180;function Bt(e){if(!e||typeof e!="object")throw new Error("ecco-flow-3d-card: invalid configuration");let t=e;if(!t.nodes||typeof t.nodes!="object"||Object.keys(t.nodes).length===0)throw new Error("ecco-flow-3d-card: at least one entry under `nodes:` is required");let r=t.ecco?.tou;for(let n of["slot_start_minutes","slot_target_soc","slot_charge_source","slot_power"]){let o=r?.[n];if(o!==void 0&&(!Array.isArray(o)||o.length!==6))throw new Error(`ecco-flow-3d-card: ecco.tou.${n} must list exactly six entities (slot 1 to slot 6)`)}}function jt(e,t){return t==="discharge_positive"?e:-e}function Gt(e,t){return t==="export_positive"?-e:e}var Dr=150;function Vt(e,t,r){let n=t!==null&&r!==null?Math.max(0,t+r):null;return e===null||e===0&&n!==null&&n>Dr?n:Math.max(0,e)}function Yt(e,t){if(e!==null)return Math.max(0,e);let r=t.filter(n=>n!==null);return r.length===0?null:Math.max(0,r.reduce((n,o)=>n+o,0))}var j=5;function Oe(e,t,r){if(t===null)return{id:e,magnitudeW:null,idle:!1,unknown:!0,reversed:!1};let n=Math.abs(t);return{id:e,magnitudeW:n,idle:n<j,unknown:!1,reversed:r&&t<0}}function Le(e){return[Oe("solar",e.solarW===null?null:Math.max(0,e.solarW),!1),Oe("battery",e.batteryW,!0),Oe("grid",e.gridW,!0),Oe("home",e.homeW===null?null:Math.max(0,e.homeW),!1)]}function qt(e){let t=e.filter(r=>!r.unknown);return t.length>0&&t.every(r=>r.idle)}function Kt(e){return e===null?"unknown":e>=j?"discharging":e<=-j?"charging":"idle"}function Xt(e){return e===null?"unknown":e>=j?"importing":e<=-j?"exporting":"idle"}var Jt=6e3,Wr=2.4,Br=.45,Zt=2.6,er=15,He=4,jr=9,it=2.7,Gr=5.4,lt=2.6,Vr=3.3,Yr=.6,Qt=5.5,at=3.1,qr=4.9;function Kr(e){if(!(e>j))return 0;let t=Math.log(e/j)/Math.log(Jt/j),r=Math.min(1,Math.max(0,t));return Math.pow(r,Wr)}function Xr(e){return e<750?1:e<3e3?2:e<6e3?3:4}var Zr={intensity:0,moving:!1,dashDurationS:0,dashLen:He,gapLen:er-He,packetWidthPx:it,baseWidthPx:lt,packetOpacity:0,glowPx:0,ballCount:0,ballDurationS:0,ballRadiusPx:at};function le(e,t){if(e.unknown||e.idle||t||e.magnitudeW===null)return Zr;let r=e.magnitudeW,n=Kr(r),o=Math.min(1,r/Jt),s=He+n*(jr-He);return{intensity:n,moving:!0,dashDurationS:Zt-n*(Zt-Br),dashLen:s,gapLen:er-s,packetWidthPx:it+n*(Gr-it),baseWidthPx:lt+o*(Vr-lt),packetOpacity:.62+n*.36,glowPx:1.6+n*2.4,ballCount:Xr(r),ballDurationS:Qt-n*(Qt-Yr),ballRadiusPx:at+n*(qr-at)}}function ct(e){if(e==null||e==="unknown"||e==="unavailable"||e===""||e==="none"||e==="None")return null;let t=Number(e);return Number.isFinite(t)?t:null}function Z(e,t){if(e==null||Number.isNaN(e))return"--";let r=t?.power_unit??"auto",n=Math.abs(e);return r==="kw"||r==="auto"&&n>=1e3?`${(e/1e3).toFixed(t?.precision??2)} kW`:`${e.toFixed(t?.precision??0)} W`}function pe(e){if(e==null||Number.isNaN(e))return"--";let t=Math.abs(e);return t>=1e4?`${(e/1e3).toFixed(0)} kW`:t>=1e3?`${(e/1e3).toFixed(1)} kW`:`${Math.round(e)} W`}function L(e,t){return e==null||Number.isNaN(e)?"--":`${e.toFixed(t?.energy_precision??1)} kWh`}function ut(e){return e==null||!Number.isFinite(e)?"--":`${Math.round(e)}%`}function G(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let t=Math.round(e);if(t===0)return e>0?"<1 min":"0 min";if(t<60)return`${t} min`;if(t<1440){let o=Math.floor(t/60),s=t%60;return s===0?`${o} h`:`${o} h ${s} min`}let r=Math.floor(t/1440),n=Math.floor(t%1440/60);return n===0?`${r} d`:`${r} d ${n} h`}function Ue(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let t=Math.round(e);if(t===0)return e>0?"<1m":"0m";if(t<60)return`\u2248${t}m`;if(t<1440){let o=Math.floor(t/60),s=t%60;return s===0?`\u2248${o}h`:`\u2248${o}h ${s}m`}let r=Math.floor(t/1440),n=Math.floor(t%1440/60);return n===0?`\u2248${r}d`:`\u2248${r}d ${n}h`}function dt(e){if(e==null||!Number.isFinite(e))return"--:--";let t=(Math.round(e)%1440+1440)%1440;return`${String(Math.floor(t/60)).padStart(2,"0")}:${String(t%60).padStart(2,"0")}`}function pt(e){return`${String(e.getHours()).padStart(2,"0")}:${String(e.getMinutes()).padStart(2,"0")}`}function fe(e){return e===null||!Number.isFinite(e)||e<0?"--":e<5?"just now":e<60?`${Math.floor(e)} s ago`:e<3600?`${Math.floor(e/60)} min ago`:e<86400?`${Math.floor(e/3600)} h ago`:`${Math.floor(e/86400)} d ago`}function A(e,t){return t?e[t]?.state:void 0}function $(e,t){return t?ct(e[t]?.state):null}function H(e,t){return t?e[t]?.attributes:void 0}function z(e){return e==="on"||e==="true"||e==="True"?"on":e==="off"||e==="false"||e==="False"?"off":"unknown"}var Qr=new Map([["s",1/60],["min",1],["h",60],["d",1440]]);function Ae(e,t,r){if(!e)return;let n=r==null||r===""?1:Qr.get(r);return n!==void 0&&t!==null&&t>=0?t*n:null}var Jr=["discharging","at_reserve","charging","holding","insufficient_data","stale"];function tr(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0?e:null}function De(e,t,r){if(!e||t===void 0)return;let n=r?.status,s=Jr.includes(n)?n:t!==null?"discharging":"insufficient_data";s==="discharging"&&t===null&&(s="insufficient_data");let i=s==="discharging"||s==="at_reserve",a=typeof r?.summary=="string"&&r.summary.trim()!==""?r.summary:null;return{status:s,minutes:i?t:null,low:s==="discharging"?tr(r?.minutes_low):null,high:s==="discharging"?tr(r?.minutes_high):null,beyondHorizon:s==="discharging"&&r?.beyond_horizon===!0,solarAssisted:s==="discharging"&&r?.solar_assisted===!0,summary:a}}var rr="Over 3 days";function ft(e){switch(e.status){case"discharging":return e.beyondHorizon?rr:`${Ue(e.minutes)} to reserve`;case"at_reserve":return"At reserve";case"charging":return"Charging";case"holding":return"Holding";case"stale":return"Telemetry stale";default:return"Insufficient data"}}function nr(e){if(!e)return{value:"--",sub:"No runtime entity",tone:"muted"};switch(e.status){case"discharging":return{value:e.beyondHorizon?">3 d":Ue(e.minutes),sub:e.beyondHorizon?"to reserve (estimate)":e.low!==null&&e.high!==null?`to reserve \xB7 likely ${G(e.low)} to ${G(e.high)}`:"to reserve (estimate)",tone:"ok"};case"at_reserve":return{value:"At reserve",sub:e.summary??"At or below the reserve",tone:"warn"};case"charging":return{value:"Charging",sub:"No discharge estimate while charging",tone:"ok"};case"holding":return{value:"Holding",sub:"Neither charging nor discharging",tone:"muted"};case"stale":return{value:"Stale",sub:"Estimate paused: telemetry stale",tone:"warn"};default:return{value:"--",sub:e.summary??"Insufficient data",tone:"muted"}}}function ht(e){if(e.status!=="discharging")return`Time to reserve: ${e.summary??ft(e)}`;let t=[e.beyondHorizon?`${rr} until the batteries reach the configured reserve at recent usage`:`Approximately ${G(e.minutes)} until the batteries reach the configured reserve at recent usage`];return!e.beyondHorizon&&e.low!==null&&e.high!==null&&t.push(`likely ${G(e.low)} to ${G(e.high)}`),e.solarAssisted&&t.push("solar-assisted, so it shortens as solar output falls"),t.push("an estimate, not a guarantee"),`Time to reserve: ${t.join("; ")}`}function or(e,t){if(!e)return{value:"Not available",sub:"No ECCO entity provides a time to charge target",tone:"muted"};let r=Ae(e,$(t,e),H(t,e)?.unit_of_measurement);return r==null?{value:"--",sub:"Entity has no value",tone:"muted"}:{value:Ue(r),sub:"to charge target (entity value)",tone:"ok"}}var en=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function tn(e){if(!e)return null;let t=en.exec(e.trim());if(!t)return null;let r=new Date(Number(t[1]),Number(t[2])-1,Number(t[3]),Number(t[4]),Number(t[5]),Number(t[6]));return Number.isNaN(r.getTime())?null:r}function rn(e,t,r){return r?"Active \xB7 end time unavailable":t===null?"Active":e===null||e<=0?`Ends ${pt(t)} \xB7 ending`:`Ends ${pt(t)} \xB7 ${G(e)} left`}function gt(e,t,r){let n={phase:"unknown",value:"--",sub:"Not configured",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(!e.anyConfigured)return n;let o=(e.scheduleStatus??"").trim().toUpperCase(),s=tn(e.endsAtText),i=(e.endsAtText??"").toLowerCase().includes("unavailable"),a=s?(s.getTime()-t)/6e4:null;if(e.active==="on"){let l=rn(a,s,i);return r==="dump"&&e.exportPowerW!==null&&e.exportPowerW!==void 0&&(l=`${l} \xB7 ${Math.round(e.exportPowerW)} W export`+(e.stopSoc!==null&&e.stopSoc!==void 0?` \xB7 stop ${Math.round(e.stopSoc)}%`:"")),{phase:"active",value:"Active",sub:l,tone:"accent",remainingMin:a,endsAt:s,endTimeUnavailable:i}}if(o==="STARTING")return{phase:"starting",value:"Starting",sub:"Scheduled start in progress",tone:"accent",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(o==="ARMED"){let l=typeof e.scheduleAttrs?.scheduled_start=="string"?e.scheduleAttrs.scheduled_start:null,c=ct(String(e.scheduleAttrs?.duration_minutes??""));return{phase:"armed",value:"Armed",sub:`Scheduled ${l?l.slice(0,5):"--:--"}`+(c!==null?` \xB7 ${G(c)}`:""),tone:"ok",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}if(o==="FAILED")return{phase:"failed",value:"Failed",sub:"Last scheduled run failed \xB7 see Energy Actions",tone:"alert",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(e.active==="off"){let l=o==="COMPLETED";return{phase:l?"completed":"standby",value:l?"Completed":r==="dump"?"Ready":"Standby",sub:l?"Last scheduled run completed":"No session running",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}return{phase:"unknown",value:"--",sub:"Lease state unavailable",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}function sr(e,t,r){let n={slot:null,startMin:null,endMin:null,minutesToChange:null,value:"--",sub:"Schedule unavailable",tone:"muted"};if(e.length!==6||e.some(i=>i===null))return n;if(r==="off")return{...n,sub:"Schedule invalid",tone:"warn"};let o=e,s=(Math.floor(t)%1440+1440)%1440;for(let i=0;i<6;i++){let a=(o[i]%1440+1440)%1440,l=(o[(i+1)%6]%1440+1440)%1440;if(a<l?s>=a&&s<l:s>=a||s<l){let p=(l-s+1440)%1440;return{slot:i+1,startMin:a,endMin:l,minutesToChange:p,value:`Slot ${i+1}`,sub:`${dt(a)}\u2013${dt(l)} \xB7 ${G(p)} left`,tone:"accent"}}}return{...n,sub:"No slot matches the current time",tone:"warn"}}function ir(e){return e.getHours()*60+e.getMinutes()}function ze(e){return e.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/^ecco_/,"").replace(/_/g," ")}function yt(e,t,r){let n=[],o=[],s=[];for(let c of e){let p=(A(r,c)??"").trim().toUpperCase();p==="FAILED"?n.push(ze(c)):p==="DEGRADED"?o.push(ze(c)):p!=="HEALTHY"&&s.push(ze(c))}let i=t.filter(c=>z(A(r,c))==="on").map(ze);if(e.length+t.length===0)return{grade:"UNKNOWN",value:"--",sub:"No health entities configured",tone:"muted",failed:n,degraded:o,unknown:s,attention:i};let l=c=>c.slice(0,2).join(", ")+(c.length>2?` +${c.length-2}`:"");if(n.length>0||i.length>0){let c=[...n,...i];return{grade:"FAILED",value:"Attention",sub:l(c),tone:"alert",failed:n,degraded:o,unknown:s,attention:i}}return o.length>0?{grade:"DEGRADED",value:"Degraded",sub:l(o),tone:"warn",failed:n,degraded:o,unknown:s,attention:i}:s.length===e.length&&e.length>0?{grade:"UNKNOWN",value:"Unknown",sub:"Health entities unavailable",tone:"muted",failed:n,degraded:o,unknown:s,attention:i}:s.length>0?{grade:"HEALTHY",value:"Nominal",sub:`${s.length} unknown: ${l(s)}`,tone:"ok",failed:n,degraded:o,unknown:s,attention:i}:{grade:"HEALTHY",value:"Nominal",sub:`${e.length} subsystems healthy`,tone:"ok",failed:n,degraded:o,unknown:s,attention:i}}function lr(e,t,r,n,o){let s=null;for(let a of e){if(!a)continue;let l=t[a]?.last_updated;if(!l)continue;let c=Date.parse(l);Number.isFinite(c)&&(s===null||c>s)&&(s=c)}let i=s===null?null:Math.max(0,(n-s)/1e3);return r==="off"?{ageS:i,stale:!0,reason:"telemetry_offline",telemetry:r}:o>0&&i!==null&&i>o?{ageS:i,stale:!0,reason:"age",telemetry:r}:{ageS:i,stale:!1,reason:null,telemetry:r}}function ar(e,t){if(e){let n=typeof e.attributes?.elevation=="number"?e.attributes.elevation:null;if(e.state==="above_horizon")return n!==null&&n<8?"dusk":"day";if(e.state==="below_horizon")return n!==null&&n>-6?"dusk":"night"}let r=t.getHours();return r>=8&&r<18?"day":r>=6&&r<8||r>=18&&r<20?"dusk":"night"}var he={sun:"M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6",pylon:"M9 22l3-19 3 19M6 22h12M7.2 9h9.6M8.4 14.5h7.2M4 9l3.2 3.5M20 9l-3.2 3.5M5 14.5l3.4 3M19 14.5l-3.4 3",home:"M3.5 11.5L12 4l8.5 7.5M6 10v10h12V10M10 20v-5h4v5",battery:"M7 5.5h10a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 17 21.5H7A1.5 1.5 0 0 1 5.5 20V7A1.5 1.5 0 0 1 7 5.5zM9.5 2.5h5M8.5 13.5h7v5h-7z",clock:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2",plug:"M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v3",target:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",leaf:"M5 19C6 11 11 5 20 4c0 9-5 15-13 15M5 19l7-7",swap:"M4 8h13l-3-3M20 16H7l3 3",heart:"M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",chevron:"M9 6l6 6-6 6",forecast:"M12 6.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v1.6M4.9 4.9l1.2 1.2M19.1 4.9l-1.2 1.2M2 10.5h1.6M20.4 10.5H22M3 19h18M6 22h12",inverter:"M4 5h16v14H4zM8 9h8M8 13h5M16 15.5h.01",alert:"M12 3l10 18H2L12 3zM12 10v5M12 18v.5",moon:"M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"};function d(e,t,r=0){return{x:205+(e-t)*11.258,y:262+(e+t)*6.5-r*13}}function E(e){return e.map(t=>`${t.x.toFixed(1)},${t.y.toFixed(1)}`).join(" ")}function Me(e,t,r,n,o,s){return{top:E([d(e,t,s),d(r,t,s),d(r,n,s),d(e,n,s)]),left:E([d(e,n,o),d(r,n,o),d(r,n,s),d(e,n,s)]),right:E([d(r,t,o),d(r,n,o),d(r,n,s),d(r,t,s)])}}function D(e,t,r,n,o){return E([d(t,e,n),d(r,e,n),d(r,e,o),d(t,e,o)])}function mt(e,t,r,n,o){return E([d(e,t,n),d(e,r,n),d(e,r,o),d(e,t,o)])}function ye(e,t,r,n,o,s){return d(e,r+(o-r)*t,n+(s-n)*t)}function We(e){if(e.length<4)return"";let t=`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)}`;for(let r=1;r+2<e.length;r+=3){let n=e[r],o=e[r+1],s=e[r+2];t+=` C ${n.x.toFixed(1)} ${n.y.toFixed(1)}, ${o.x.toFixed(1)} ${o.y.toFixed(1)}, ${s.x.toFixed(1)} ${s.y.toFixed(1)}`}return t}var Q={x0:-1,y0:-3,x1:7,y1:3,z:4.2,ridgeZ:6.6,ridgeY:0},cr={x0:7,y0:-1,x1:11,y1:3,z:2.5},ge={x0:-6.2,y0:4.2,x1:-4.6,y1:5.4,z:2.4},ae={x0:5.3,x1:6.3,z0:1.25,z1:2.45,y:Q.y1},V=d(10.6,-4.8),bt=(()=>{let e=d((ae.x0+ae.x1)/2,ae.y,(ae.z0+ae.z1)/2);return{x:e.x+1,y:e.y+2}})(),J={solar:{x:8,y:10,w:150,h:58,port:{x:58,y:68}},grid:{x:246,y:22,w:146,h:58,port:{x:330,y:80}},home:{x:214,y:176,w:140,h:54,port:{x:236,y:230}},battery:{x:8,y:388,w:184,h:70,port:{x:108,y:388}}};function Ee(e,t=.5){if(e.length<2)return"";if(e.length===2)return`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)} L ${e[1].x.toFixed(1)} ${e[1].y.toFixed(1)}`;let r=`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)}`;for(let n=0;n<e.length-1;n++){let o=e[Math.max(0,n-1)],s=e[n],i=e[n+1],a=e[Math.min(e.length-1,n+2)],l={x:s.x+(i.x-o.x)/6*t*2,y:s.y+(i.y-o.y)/6*t*2},c={x:i.x-(a.x-s.x)/6*t*2,y:i.y-(a.y-s.y)/6*t*2};r+=` C ${l.x.toFixed(1)} ${l.y.toFixed(1)}, ${c.x.toFixed(1)} ${c.y.toFixed(1)}, ${i.x.toFixed(1)} ${i.y.toFixed(1)}`}return r}var nn={main_solar_array:{x:684,y:466},garage_solar_array:{x:1086,y:582},wall_inverter:{x:1002,y:698},battery_cabinet:{x:150,y:622},ev_charger:{x:1090,y:761},house_energy_center:{x:748,y:694},grid_pylon:{x:1317,y:452}},on={top_banner:{x:44,y:30,w:1360,h:122},left_info_column:{x:36,y:170,w:280,h:705},right_info_column:{x:1128,y:170,w:284,h:705},bottom_strip:{x:58,y:920,w:1330,h:120}};function xt(e){let t=nn,r=on,n=150*e,o=58*e,s=182*e,i=78*e,a=140*e,l=54*e,c={solar:{x:r.top_banner.x,y:r.top_banner.y,w:n,h:o,port:{x:r.top_banner.x+n*.72,y:r.top_banner.y+o}},grid:{x:r.top_banner.x+r.top_banner.w-n,y:r.top_banner.y,w:n,h:o,port:{x:r.top_banner.x+r.top_banner.w-n*.28,y:r.top_banner.y+o}},battery:{x:r.left_info_column.x,y:672,w:s,h:i,port:t.battery_cabinet},home:{x:930-a/2,y:r.bottom_strip.y+r.bottom_strip.h+26-l,w:a,h:l,port:{x:930,y:r.bottom_strip.y+r.bottom_strip.h+26-l}}};return{width:1448,height:1086,scale:e,pills:c,inverter:t.wall_inverter,paths:()=>({solar:Ee([c.solar.port,{x:440,y:290},{x:570,y:385},t.main_solar_array,{x:758,y:522},{x:868,y:610},{x:975,y:692},t.wall_inverter]),solar2:Ee([t.garage_solar_array,{x:1068,y:624},{x:1042,y:660},{x:1016,y:688},t.wall_inverter]),battery:Ee([t.battery_cabinet,{x:350,y:622},{x:560,y:636},{x:790,y:670},t.wall_inverter]),grid:Ee([c.grid.port,{x:1314,y:320},t.grid_pylon,{x:1288,y:550},{x:1190,y:626},{x:1088,y:682},t.wall_inverter]),home:Ee([t.wall_inverter,{x:928,y:704},{x:846,y:705},{x:790,y:700},t.house_energy_center,{x:840,y:(t.house_energy_center.y+c.home.port.y)/2+10},c.home.port])})}}function ur(e){return e<520?3.4:e<760?3.2:e<1100?3.1:3}var xo=xt(3);function dr(){let e=bt,t=ye(.2,.08,Q.y1,Q.z,Q.ridgeY,Q.ridgeZ),r=We([J.solar.port,{x:58,y:120},{x:150,y:150},t,{x:t.x+16,y:t.y+20},{x:e.x-24,y:e.y-26},e]),n=d(ge.x1,(ge.y0+ge.y1)/2,ge.z*.72),o=We([{x:n.x+2,y:n.y},{x:n.x+40,y:n.y-2},{x:e.x-60,y:e.y+28},{x:e.x-24,y:e.y+24},{x:e.x-10,y:e.y+22},{x:e.x-4,y:e.y+12},e]),s={x:V.x-4,y:V.y-118},i=We([J.grid.port,{x:330,y:112},{x:s.x-30,y:s.y+10},{x:s.x-22,y:s.y+44},{x:s.x-14,y:V.y-6},{x:V.x-30,y:V.y+30},{x:300,y:V.y+40},{x:272,y:V.y+36},{x:e.x+10,y:e.y+24},e]),a=We([e,{x:e.x+10,y:e.y-24},{x:e.x-12,y:e.y-48},J.home.port]);return{solar:r,battery:o,grid:i,home:a}}var sn=15,hr={solar:"#f7c948",solar2:"#f7c948",battery:"#35e08a",grid:"#3ea6ff",home:"#22d3ee"};function fr(e,t,r,n,o){let s=n/24;return w`<g transform="translate(${t} ${r}) scale(${s})" fill="none" stroke=${o} stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d=${he[e]}></path></g>`}function ln(){let e=[d(-8,-6),d(10,-6),d(10,10),d(-8,10)],t=12,r=[e[3],e[2],{x:e[2].x,y:e[2].y+t},{x:e[3].x,y:e[3].y+t}],n=[e[2],e[1],{x:e[1].x,y:e[1].y+t},{x:e[2].x,y:e[2].y+t}],o=[d(8.2,3.05),d(10.6,3.05),d(10.6,10),d(8.2,10)],s=[d(2.2,3.05),d(3.2,3.05),d(3.2,5.6),d(-4.2,5.6),d(-4.2,4.6),d(2.2,4.6)];return w`
    <g class="ground">
      <polygon points=${E(r)} class="ground-side"></polygon>
      <polygon points=${E(n)} class="ground-side ground-side-r"></polygon>
      <polygon points=${E(e)} class="ground-top"></polygon>
      <polygon points=${E(e)} fill="url(#ef3d-ground-sheen)"></polygon>
      <polygon points=${E(o)} class="drive"></polygon>
      <polygon points=${E(s)} class="drive path"></polygon>
      ${an()}
    </g>`}function an(){let e=[];for(let t=0;t<6;t++){let r=-5+t*2.6;e.push(w`<polygon points=${E([d(-7.6,r),d(-1.6,r),d(-1.6,r+1.3),d(-7.6,r+1.3)])} class="lawn-stripe"></polygon>`)}return e}function Be(e,t,r,n=""){let o=d(e,t);return w`
    <g class="tree ${n}">
      <ellipse cx=${o.x} cy=${o.y+2} rx=${r*.9} ry=${r*.38} class="tree-shadow"></ellipse>
      <rect x=${o.x-1.4} y=${o.y-r*1.1} width="2.8" height=${r*1.1} class="trunk"></rect>
      <circle cx=${o.x-r*.35} cy=${o.y-r*1.15} r=${r*.78} class="canopy c2"></circle>
      <circle cx=${o.x+r*.4} cy=${o.y-r*1.25} r=${r*.82} class="canopy c3"></circle>
      <circle cx=${o.x} cy=${o.y-r*1.7} r=${r*.86} class="canopy c1"></circle>
    </g>`}function me(e,t,r){let n=d(e,t);return w`<g class="shrub"><ellipse cx=${n.x} cy=${n.y} rx=${r} ry=${r*.62} class="canopy c2"></ellipse><ellipse cx=${n.x-r*.4} cy=${n.y-r*.25} rx=${r*.7} ry=${r*.45} class="canopy c1"></ellipse></g>`}function wt(e,t){let r=d(e,t);return w`<g class="lamp"><line x1=${r.x} y1=${r.y} x2=${r.x} y2=${r.y-9} class="lamp-post"></line><circle cx=${r.x} cy=${r.y-10} r="2.2" class="lamp-light"></circle><circle cx=${r.x} cy=${r.y-10} r="6" class="lamp-halo"></circle></g>`}function cn(){let e=Q,t=Me(e.x0,e.y0,e.x1,e.y1,0,e.z),r=[d(e.x0-.5,e.y1+.5,e.z-.25),d(e.x1+.5,e.y1+.5,e.z-.25),d(e.x1+.5,e.ridgeY,e.ridgeZ),d(e.x0-.5,e.ridgeY,e.ridgeZ)],n=[d(e.x0-.5,e.y0-.5,e.z-.25),d(e.x1+.5,e.y0-.5,e.z-.25),d(e.x1+.5,e.ridgeY,e.ridgeZ),d(e.x0-.5,e.ridgeY,e.ridgeZ)],o=[d(e.x1,e.y0,e.z),d(e.x1,e.y1,e.z),d(e.x1,e.ridgeY,e.ridgeZ)],s=[d(e.x1+.5,e.y1+.5,e.z-.25),d(e.x1+.5,e.y1+.5,e.z-.55),d(e.x1+.5,e.ridgeY,e.ridgeZ-.3),d(e.x1+.5,e.ridgeY,e.ridgeZ)],i=cr,a=Me(i.x0,i.y0,i.x1,i.y1,0,i.z),l=Me(i.x0-.15,i.y0-.15,i.x1+.15,i.y1+.15,i.z,i.z+.18);return w`
    <g class="house">
      <!-- soft contact shadow -->
      <polygon points=${E([d(e.x0-.6,e.y0-.2),d(i.x1+.9,i.y0-.2),d(i.x1+.9,i.y1+.9),d(e.x0-.6,e.y1+.9)])} class="contact-shadow"></polygon>
      <!-- garage (behind the house's right face order-wise it sits in front, draw after walls) -->
      <polygon points=${t.right} class="wall wall-r"></polygon>
      <polygon points=${E(o)} class="wall wall-r gable"></polygon>
      <polygon points=${t.left} class="wall wall-l"></polygon>
      <!-- windows and door on the front-left wall -->
      <polygon points=${D(e.y1+.02,.2,1.6,1.5,3.2)} class="window"></polygon>
      <polygon points=${D(e.y1+.02,2,3.4,1.5,3.2)} class="window"></polygon>
      <polygon points=${D(e.y1+.02,.2,1.6,.4,1.1)} class="window small"></polygon>
      <polygon points=${D(e.y1+.02,2.3,3.1,0,1.15)} class="door"></polygon>
      <polygon points=${D(e.y1+.02,3.9,4.8,1.5,3.2)} class="window"></polygon>
      <!-- windows on the right wall -->
      <polygon points=${mt(e.x1+.02,-2.4,-1.2,1.5,3.2)} class="window"></polygon>
      <polygon points=${mt(e.x1+.02,-2.4,-1.2,.3,1.1)} class="window small"></polygon>
      <!-- garage -->
      <polygon points=${a.right} class="wall wall-r"></polygon>
      <polygon points=${a.left} class="wall wall-l"></polygon>
      <polygon points=${D(i.y1+.02,7.6,10.4,0,1.9)} class="garage-door"></polygon>
      ${[.45,.9,1.35].map(c=>w`<polyline points=${E([d(7.6,i.y1+.03,c),d(10.4,i.y1+.03,c)])} class="garage-line"></polyline>`)}
      <polygon points=${a.top} class="roof-flat"></polygon>
      <polygon points=${l.left} class="roof-lip"></polygon>
      <polygon points=${l.right} class="roof-lip"></polygon>
      <polygon points=${l.top} class="roof-flat-top"></polygon>
      <!-- roof -->
      <polygon points=${E(n)} class="roof roof-back"></polygon>
      <polygon points=${E(r)} class="roof roof-front"></polygon>
      <polygon points=${E(s)} class="fascia"></polygon>
      <polyline points=${E([d(e.x0-.5,e.ridgeY,e.ridgeZ),d(e.x1+.5,e.ridgeY,e.ridgeZ)])} class="ridge"></polyline>
      ${un()}
      ${dn()}
    </g>`}function un(){let e=Q,t=[],r=5,n=2,o=e.x0+.25,s=e.x1-.75,i=.14,a=(s-o-i*(r-1))/r,l=.16,c=.9,p=.05,u=(c-l-p*(n-1))/n;for(let f=0;f<n;f++)for(let m=0;m<r;m++){let g=o+m*(a+i),h=g+a,O=l+f*(u+p),T=O+u,x=[ye(g,O,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ye(h,O,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ye(h,T,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ye(g,T,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ)].map(v=>({x:v.x,y:v.y-1.2}));t.push(w`<polygon points=${E(x)} class="pv"></polygon>`),t.push(w`<polygon points=${E(x)} fill="url(#ef3d-pv-glare)" class="pv-glare"></polygon>`);let I=(v,S,k)=>({x:v.x+(S.x-v.x)*k,y:v.y+(S.y-v.y)*k});for(let v of[1/3,2/3])t.push(w`<line x1=${I(x[0],x[3],v).x} y1=${I(x[0],x[3],v).y} x2=${I(x[1],x[2],v).x} y2=${I(x[1],x[2],v).y} class="pv-line"></line>`),t.push(w`<line x1=${I(x[0],x[1],v).x} y1=${I(x[0],x[1],v).y} x2=${I(x[3],x[2],v).x} y2=${I(x[3],x[2],v).y} class="pv-line"></line>`)}return t}function dn(){let e=ae,t=D(e.y+.03,e.x0,e.x1,e.z0,e.z1),r=d(e.x1-.18,e.y+.05,e.z1-.22),n=o=>E([d(e.x0+.18,e.y+.05,o),d(e.x1-.18,e.y+.05,o)]);return w`
    <g class="inverter">
      <polygon points=${t} class="inverter-face"></polygon>
      <polyline points=${n(e.z0+.3)} class="inverter-vent"></polyline>
      <polyline points=${n(e.z0+.5)} class="inverter-vent"></polyline>
      <circle cx=${r.x} cy=${r.y} r="1.6" class="inverter-led"></circle>
      <circle cx=${r.x} cy=${r.y} r="4" class="inverter-led-halo"></circle>
    </g>`}function pn(e){let t=ge,r=Me(t.x0,t.y0,t.x1,t.y1,0,t.z),n=t.x0+.18,o=.16,s=.3,i=t.z-.3,a=e===null?s:s+Math.max(0,Math.min(100,e))/100*(i-s),l=d((t.x0+t.x1)/2+.15,t.y1+.04,t.z*.56);return w`
    <g class="battery-cabinet">
      <ellipse cx=${d((t.x0+t.x1)/2,(t.y0+t.y1)/2).x} cy=${d((t.x0+t.x1)/2,(t.y0+t.y1)/2).y+3} rx="20" ry="7" class="contact-shadow soft"></ellipse>
      <polygon points=${r.right} class="cab cab-r"></polygon>
      <polygon points=${r.left} class="cab cab-l"></polygon>
      <polygon points=${r.top} class="cab cab-t"></polygon>
      <polygon points=${D(t.y1+.03,n,n+o,s,i)} class="cab-strip-bg"></polygon>
      ${e===null?y:w`<polygon points=${D(t.y1+.04,n,n+o,s,a)} class="cab-strip"></polygon>`}
      <text x="0" y="0" class="cab-label" transform=${`matrix(0.866 0.5 0 1 ${l.x.toFixed(1)} ${l.y.toFixed(1)})`}>ECCO</text>
    </g>`}function fn(e,t){let r=V,n=118,o={x:r.x-4,y:r.y-n},s=18,i=(p,u)=>w`<line x1=${r.x-4-u} y1=${p} x2=${r.x-4+u} y2=${p} class="pylon-line"></line>`,a=w`
    <line x1=${r.x-s} y1=${r.y} x2=${o.x-2} y2=${o.y} class="pylon-line"></line>
    <line x1=${r.x+s-8} y1=${r.y} x2=${o.x+2} y2=${o.y} class="pylon-line"></line>
    <line x1=${r.x-s+5} y1=${r.y-2} x2=${o.x} y2=${o.y+4} class="pylon-line thin"></line>
    <line x1=${r.x+s-12} y1=${r.y-2} x2=${o.x} y2=${o.y+4} class="pylon-line thin"></line>`,l=[];for(let p=1;p<7;p++){let u=r.y-n/7*p,f=(s-8)*(1-p/8)+3;l.push(w`<line x1=${r.x-4-f} y1=${u} x2=${r.x-4+f} y2=${u-6} class="pylon-line thin"></line>`),l.push(w`<line x1=${r.x-4+f} y1=${u} x2=${r.x-4-f} y2=${u-6} class="pylon-line thin"></line>`)}let c=[o.y+24,o.y+44].map(p=>w`<path d=${`M ${(r.x-4-26).toFixed(1)} ${p} Q ${(r.x+30).toFixed(1)} ${p+18} ${410} ${p-12}`} class="wire"></path>`);return w`
    <g class=${`pylon ${e?"live":""} ${t?"unknown":""}`}>
      ${a}${l}
      ${i(o.y+22,26)}${i(o.y+42,20)}
      ${c}
      <circle cx=${o.x} cy=${o.y-2} r="3" class="pylon-tip"></circle>
    </g>`}function Y(e,t,r,n,o=1){let{edge:s,motion:i}=r,a=hr[e],l=`flow flow-${e} ${s.unknown?"unknown":""} ${s.idle?"idle":""} ${i.moving&&n?"moving":""} ${s.reversed?"reversed":""}`,c=`ef3d-path-${e}`,p=i.moving?`stroke-dasharray:${(i.dashLen*o).toFixed(1)} ${(i.gapLen*o).toFixed(1)}; animation-duration:${i.dashDurationS.toFixed(2)}s; stroke-width:${(i.packetWidthPx*o).toFixed(2)}; opacity:${i.packetOpacity.toFixed(2)}; --dash-travel:${(-2*sn*o).toFixed(1)}`:"",u=i.moving?`stroke-width:${(i.packetWidthPx*2.6*o).toFixed(1)}; opacity:${(.18+i.intensity*.3).toFixed(2)}`:"",f=[];if(i.moving&&n){let g=i.ballCount;for(let h=0;h<g;h++)f.push(w`
        <g class="pulse" data-path=${c} data-duration=${i.ballDurationS.toFixed(3)} data-phase=${(h/g).toFixed(3)} data-reversed=${s.reversed?"1":"0"} style=${`--pulse-colour:${a}`}>
          <circle r=${(i.ballRadiusPx*1.9*o).toFixed(2)} class="pulse-halo"></circle>
          <circle r=${(i.ballRadiusPx*o).toFixed(2)} class="pulse-glow"></circle>
          <circle r=${(i.ballRadiusPx*.42*o).toFixed(2)} class="pulse-core"></circle>
        </g>`)}let m=[];if(i.moving&&!n)for(let g of[.3,.55,.8])m.push(w`<g class="chevron" data-path=${c} data-phase=${g} data-reversed=${s.reversed?"1":"0"} style=${`--pulse-colour:${a}`}><path d="M -4 -4 L 2 0 L -4 4" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" transform=${`scale(${o})`}></path></g>`);return w`
    <g class=${l} style=${`--flow-colour:${a}`}>
      <path d=${t} class="flow-base" style=${`stroke-width:${(i.baseWidthPx*o).toFixed(2)}`}></path>
      <path d=${t} class="flow-dots" style=${`stroke-width:${(2.4*o).toFixed(1)}; stroke-dasharray:0.1 ${(7*o).toFixed(1)}`}></path>
      <path d=${t} class="flow-glow" style=${u}></path>
      <path id=${c} d=${t} class="flow-packets" style=${p}></path>
      ${f}${m}
    </g>`}function ee(e,t,r,n,o,s=1){let i=hr[e],a=14*s,l=e==="battery",c=20*s,p=2*Math.PI*c,u=r.soc??null,f=u===null?0:Math.max(0,Math.min(100,u))/100*p,m=t.x+52*s,g=t.x+t.w-32*s,h=t.y+t.h/2,O=o.edge.unknown?"unknown":o.edge.idle?"idle":"active";return w`
    <g class=${`pill pill-${e} tone-${r.tone} ${O} ${r.clickable?"clickable":""}`}
       style=${`--pill-colour:${i}`}
       role=${r.clickable?"button":"img"}
       tabindex=${r.clickable?0:-1}
       aria-label=${`${r.label}: ${r.value}${r.sub?", "+r.sub:""}`}
       @click=${()=>n(e)}
       @keydown=${T=>{(T.key==="Enter"||T.key===" ")&&(T.preventDefault(),n(e))}}>
      <rect x=${t.x} y=${t.y} width=${t.w} height=${t.h} rx=${a} class="pill-bg"></rect>
      <rect x=${t.x} y=${t.y} width=${t.w} height=${t.h} rx=${a} class="pill-border"></rect>
      <circle cx=${t.x+27*s} cy=${t.y+t.h/2} r=${15*s} class="pill-icon-bg"></circle>
      ${fr(r.icon,t.x+16*s,t.y+t.h/2-11*s,22*s,i)}
      <text x=${m} y=${t.y+19*s} class="pill-label">${r.label}</text>
      <text x=${m} y=${t.y+(r.sub?39:42)*s} class="pill-value">${r.value}</text>
      ${r.sub?w`<text x=${m} y=${t.y+(r.extra?52:t.h/s-8)*s} class="pill-sub">${r.sub}</text>`:y}
      ${r.extra?w`<text x=${m} y=${t.y+t.h-9*s} class="pill-extra">${r.extra}</text>`:y}
      ${l?w`
            <circle cx=${g} cy=${h} r=${c} class="ring-track"></circle>
            ${u===null?y:w`<circle cx=${g} cy=${h} r=${c} class="ring-fill" stroke-dasharray=${`${f.toFixed(1)} ${p.toFixed(1)}`} transform=${`rotate(-90 ${g} ${h})`}></circle>`}
            <text x=${g} y=${h+4*s} class="ring-value">${u===null?"--":`${Math.round(u)}%`}</text>
            <text x=${g} y=${h+14*s} class="ring-caption">SOC</text>`:r.clickable?fr("chevron",t.x+t.w-24*s,t.y+t.h/2-8*s,16*s,"rgba(255,255,255,0.45)"):y}
    </g>`}function gr(e){if(e.artwork)return hn(e,e.artwork);let t=dr(),r=e.flows.grid.motion.moving,n=bt;return w`
    <svg class=${`scene ${e.daylight} ${e.stale?"stale":""} ${e.animate?"":"still"}`} viewBox=${`0 0 ${400} ${470}`} preserveAspectRatio="xMidYMid meet" aria-label="Isometric energy flow scene">
      <defs>
        <radialGradient id="ef3d-sky" cx="30%" cy="12%" r="80%">
          <stop offset="0%" class="sky-a"></stop>
          <stop offset="100%" class="sky-b"></stop>
        </radialGradient>
        <linearGradient id="ef3d-ground-sheen" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.07"></stop>
          <stop offset="55%" stop-color="#ffffff" stop-opacity="0"></stop>
          <stop offset="100%" stop-color="#000000" stop-opacity="0.18"></stop>
        </linearGradient>
        <linearGradient id="ef3d-pv-glare" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.22"></stop>
          <stop offset="45%" stop-color="#ffffff" stop-opacity="0.02"></stop>
          <stop offset="100%" stop-color="#ffffff" stop-opacity="0"></stop>
        </linearGradient>
        <filter id="ef3d-blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.4"></feGaussianBlur></filter>
        <filter id="ef3d-blur-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5"></feGaussianBlur></filter>
      </defs>
      <rect x="0" y="0" width=${400} height=${470} fill="url(#ef3d-sky)" class="sky"></rect>
      <g class="celestial">
        <circle cx="300" cy="96" r="14" class="moon"></circle>
        <circle cx="300" cy="96" r="30" class="moon-halo"></circle>
        <circle cx="318" cy="128" r="17" class="sun-disc"></circle>
        <circle cx="318" cy="128" r="56" class="sun-halo"></circle>
        ${[[40,92],[122,46],[180,112],[236,70],[352,150],[392,60],[20,160],[288,20]].map(([o,s])=>w`<circle cx=${o} cy=${s} r="1.1" class="star"></circle>`)}
      </g>
      ${ln()}
      ${Be(-6.5,-4.6,13,"back")}
      ${Be(-2.5,-5.2,10,"back")}
      ${Be(9.5,-5.6,11,"back")}
      ${me(-7.2,1.2,8)}
      ${me(-6.6,-1,7)}
      ${me(5,5.2,7)}
      ${me(6.4,6.4,6)}
      ${me(-1.5,7.2,8)}
      ${wt(-4.8,6.6)}
      ${wt(3.9,5.2)}
      ${wt(7.4,8.6)}
      ${fn(r,e.flows.grid.edge.unknown)}
      ${cn()}
      ${pn(e.pills.battery.soc??null)}
      ${Be(-7.6,8.6,12,"front")}
      ${me(1.2,8.8,7)}
      <g class="flows">
        ${Y("grid",t.grid,e.flows.grid,e.animate)}
        ${Y("solar",t.solar,e.flows.solar,e.animate)}
        ${Y("battery",t.battery,e.flows.battery,e.animate)}
        ${Y("home",t.home,e.flows.home,e.animate)}
        <circle cx=${n.x} cy=${n.y} r="4.2" class=${`junction led-${e.inverterLed}`}></circle>
        <circle cx=${n.x} cy=${n.y} r="9" class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${ee("solar",J.solar,e.pills.solar,e.onPill,e.flows.solar)}
      ${ee("grid",J.grid,e.pills.grid,e.onPill,e.flows.grid)}
      ${ee("home",J.home,e.pills.home,e.onPill,e.flows.home)}
      ${ee("battery",J.battery,e.pills.battery,e.onPill,e.flows.battery)}
    </svg>`}function hn(e,t){let r=t.layout,n=r.paths(),o=r.scale,s=r.inverter,i=e.solar2;return w`
    <svg class=${`scene artwork ${e.daylight} ${e.stale?"stale":""} ${e.animate?"":"still"}`} viewBox=${`0 0 ${r.width} ${r.height}`} preserveAspectRatio="xMidYMid meet" style=${`--k:${o}`} aria-label="Energy flow scene">
      <defs>
        <filter id="ef3d-blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation=${(2.4*o).toFixed(1)}></feGaussianBlur></filter>
        <filter id="ef3d-blur-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=${(5*o).toFixed(1)}></feGaussianBlur></filter>
      </defs>
      ${t.layers.map(a=>w`<image href=${a.url} x="0" y="0" width=${r.width} height=${r.height} preserveAspectRatio="xMidYMid meet" class=${`plate ${a.entering?"entering":""}`} data-scene=${a.key} @error=${()=>t.onError(a.url)} @load=${()=>t.onLoad(a.url)}></image>`)}
      <g class="flows">
        ${Y("grid",n.grid,e.flows.grid,e.animate,o)}
        ${Y("solar",n.solar,e.flows.solar,e.animate,o)}
        ${i?Y("solar2",n.solar2,i,e.animate,o):y}
        ${Y("battery",n.battery,e.flows.battery,e.animate,o)}
        ${Y("home",n.home,e.flows.home,e.animate,o)}
        <circle cx=${s.x} cy=${s.y} r=${(4.2*o).toFixed(1)} class=${`junction led-${e.inverterLed}`}></circle>
        <circle cx=${s.x} cy=${s.y} r=${(9*o).toFixed(1)} class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${ee("solar",r.pills.solar,e.pills.solar,e.onPill,e.flows.solar,o)}
      ${ee("grid",r.pills.grid,e.pills.grid,e.onPill,e.flows.grid,o)}
      ${ee("home",r.pills.home,e.pills.home,e.onPill,e.flows.home,o)}
      ${ee("battery",r.pills.battery,e.pills.battery,e.onPill,e.flows.battery,o)}
    </svg>`}var yr={bright_summer_day:"00_bright_summer_day.png",soft_clear_day:"01_soft_clear_day.png",misty_morning:"02_misty_morning.png",golden_hour:"03_golden_hour.png",clear_night:"04_clear_night.png",rainy_day:"05_rainy_day.png",storm_night:"06_storm_night.png",winter_clear_day:"07_winter_clear_day.png",christmas_day:"08_christmas_day.png",christmas_night:"09_christmas_night.png"},mr=Object.keys(yr);function gn(e,t){return e===12||e===1&&t<=3}function yn(e){return e.sunUp!==null?!e.sunUp:e.weather==="clear-night"?!0:e.hour<7||e.hour>=19}function mn(e){return e.elevation===null||e.elevation<-6||e.elevation>15?!1:e.rising!==null?!e.rising:e.hour>=15}function br(e){let t=yn(e),r=(e.weather??"").toLowerCase();return gn(e.month,e.day)?t?"christmas_night":"christmas_day":!t&&(r==="snowy"||r==="snowy-rainy")?"winter_clear_day":t&&(r==="lightning"||r==="lightning-rainy"||r==="exceptional")?"storm_night":!t&&(r==="rainy"||r==="pouring")?"rainy_day":!t&&r==="fog"?"misty_morning":mn(e)?"golden_hour":r==="clear-night"||t&&["sunny","partlycloudy","cloudy","windy",""].includes(r)||t?"clear_night":r==="partlycloudy"?"soft_clear_day":r==="sunny"||r==="windy"||r==="clear"?"bright_summer_day":"soft_clear_day"}function xr(e,t,r){let n=r?.[t]??yr[t];return/^(\/|\.|[a-z]+:)/i.test(n)&&r?.[t]?n:(e.endsWith("/")?e:e+"/")+n}var bn=15e3,U=class extends X{constructor(){super(...arguments);this._detailsOpen=!1;this._nowMs=Date.now();this._layers=[];this._failedPlates=new Set;this._fadeTimer=0;this._widthPx=0;this._raf=0;this._timer=0;this._lengthCache=new WeakMap;this._onMotionPref=()=>{this.requestUpdate()}}static getStubConfig(){return{type:"custom:ecco-flow-3d-card",title:"Energy Flow",subtitle:"Live power overview",nodes:{solar:[{label:"Array 1",power:"sensor.pv1_power"}],inverter:{power:"sensor.inverter_power"},home:{power:"sensor.house_power"},battery:{power:"sensor.battery_power",soc:"sensor.battery_soc",power_sign:"charge_positive"},grid:{power:"sensor.grid_power",power_sign:"import_positive"}}}}setConfig(r){Bt(r),this._config=r,this._failedPlates=new Set}_resolveScene(r,n){let o=this._config?.scene;if(!o?.pack)return null;let s=this._config?.ecco??{},i=s.sun?r[s.sun]:void 0,a=typeof i?.attributes?.elevation=="number"?i.attributes.elevation:null,l=typeof i?.attributes?.rising=="boolean"?i.attributes.rising:null,p=(o.force&&mr.includes(o.force)?o.force:null)??br({month:n.getMonth()+1,day:n.getDate(),sunUp:i?i.state==="above_horizon"?!0:i.state==="below_horizon"?!1:null:null,elevation:a,rising:l,weather:s.weather?A(r,s.weather):void 0,hour:n.getHours()});return{key:p,url:xr(o.pack,p,o.scenes)}}willUpdate(){let r=this._resolveScene(this.hass?.states??{},new Date(this._nowMs));if(!r){this._layers.length&&(this._layers=[]);return}let n=this._layers[this._layers.length-1];n&&n.url===r.url||(this._layers=this._layers.length===0?[{url:r.url,key:r.key,entering:!1}]:[...this._layers.slice(-1),{url:r.url,key:r.key,entering:!0}])}_plateLoaded(r){let n=this._layers[this._layers.length-1];!n||n.url!==r||this._layers.length<2||(window.clearTimeout(this._fadeTimer),this._fadeTimer=window.setTimeout(()=>{this._layers=this._layers.filter(o=>o.url===r).map(o=>({...o,entering:!1}))},(this._config?.scene?.crossfade_ms??900)+50))}_plateFailed(r){this._failedPlates.add(r),this.requestUpdate()}getCardSize(){return 8}connectedCallback(){super.connectedCallback(),window.matchMedia&&(this._reducedMotionQuery=window.matchMedia("(prefers-reduced-motion: reduce)"),this._reducedMotionQuery.addEventListener?.("change",this._onMotionPref)),this._timer=window.setInterval(()=>{this._nowMs=Date.now()},bn),typeof ResizeObserver<"u"&&(this._resize=new ResizeObserver(r=>{let n=Math.round(r[0]?.contentRect.width??0);n&&Math.abs(n-this._widthPx)>8&&(this._widthPx=n)}),this._resize.observe(this))}disconnectedCallback(){super.disconnectedCallback(),this._reducedMotionQuery?.removeEventListener?.("change",this._onMotionPref),window.clearInterval(this._timer),window.clearTimeout(this._fadeTimer),this._resize?.disconnect(),cancelAnimationFrame(this._raf),this._raf=0}firstUpdated(){this._animate()}updated(r){this._placeChevrons()}get _reducedMotion(){return!!this._reducedMotionQuery?.matches}_moreInfo(r){r&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:r},bubbles:!0,composed:!0}))}render(){let r=this._config;if(!r)return N``;let n=this.hass?.states??{},o=r.nodes??{},s=r.ecco??{},i=new Date(this._nowMs),a=Dt(o.solar),l=a.map(P=>$(n,P.power)),c=Yt($(n,o.solar_total),l),p=$(n,o.inverter?.power),u=$(n,o.battery?.power),f=u===null?null:jt(u,o.battery?.power_sign),m=$(n,o.grid?.power),g=m===null?null:Gt(m,o.grid?.power_sign),h=Vt($(n,o.home?.power),p,g),O=$(n,o.battery?.soc),T=Le({solarW:c,batteryW:f,gridW:g,homeW:h}),F=Object.fromEntries(T.map(P=>[P.id,P])),x=a.length>=2&&(l[0]!==null||l[1]!==null),I=x?Le({solarW:l[0]??null,batteryW:null,gridW:null,homeW:null})[0]:F.solar,v=x?Le({solarW:l[1]??null,batteryW:null,gridW:null,homeW:null})[0]:null,S=z(A(n,s.telemetry_online)),k=lr([...a.map(P=>P.power),o.solar_total,o.inverter?.power,o.battery?.power,o.grid?.power,o.home?.power],n,S,this._nowMs,r.features?.stale_after_s??Wt),C=k.stale,b=(r.features?.animate_flow??!0)&&!this._reducedMotion,M=o.battery?.time_to_reserve,R=De(M,Ae(M,$(n,M),H(n,M)?.unit_of_measurement),H(n,M)),te=R&&(R.status==="discharging"||R.status==="at_reserve")?ft(R):"",re=Kt(f),W=Xt(g),_=z(A(n,o.grid?.connected)),wr={solar:{label:"Solar Generation",value:pe(c),sub:a.length>1?a.map((P,Ve)=>pe(l[Ve]??null)).join(" + "):"",tone:c===null?"muted":"ok",icon:"sun",clickable:!!(o.solar_total??a[0]?.power)},grid:{label:"Grid",value:pe(g===null?null:Math.abs(g)),sub:_==="off"?"Disconnected":W==="importing"?"Importing":W==="exporting"?"Exporting":W==="idle"?"Idle":"Unknown",tone:_==="off"?"alert":W==="unknown"?"muted":"ok",icon:"pylon",clickable:!!o.grid?.power},home:{label:"Home Load",value:pe(h),sub:"",tone:h===null?"muted":"ok",icon:"home",clickable:!!o.home?.power},battery:{label:"Battery Storage",value:pe(f===null?null:Math.abs(f)),sub:re==="charging"?"Charging":re==="discharging"?"Discharging":re==="idle"?"Idle":"Unknown",extra:te,tone:re==="unknown"?"muted":"ok",icon:"battery",clickable:!!(o.battery?.power??o.battery?.soc),soc:O}},$r=ar(s.sun?n[s.sun]:void 0,i),vt=this._layers[this._layers.length-1],je=!!vt&&!this._failedPlates.has(vt.url),vr={daylight:$r,artwork:je?{layers:this._layers,layout:xt(ur(this._widthPx||this.getBoundingClientRect().width||1200)),onError:P=>this._plateFailed(P),onLoad:P=>this._plateLoaded(P)}:void 0,solar2:je&&v?{edge:v,motion:le(v,C)}:void 0,flows:{solar:je?{edge:I,motion:le(I,C)}:{edge:F.solar,motion:le(F.solar,C)},battery:{edge:F.battery,motion:le(F.battery,C)},grid:{edge:F.grid,motion:le(F.grid,C)},home:{edge:F.home,motion:le(F.home,C)}},stale:C,animate:b,pills:wr,inverterLed:C?"warn":T.some(P=>!P.unknown)?"ok":"off",onPill:P=>{let Ve=P==="solar"?o.solar_total??a[0]?.power:P==="grid"?o.grid?.power:P==="home"?o.home?.power:o.battery?.power??o.battery?.soc;this._moreInfo(Ve)}},_r=qt(T)&&!C,Ge=this._chip(S,k.ageS,C,k.reason);return N`
      <ha-card style=${`--ef-crossfade:${r.scene?.crossfade_ms??900}ms`}>
        <div class="card">
          <header class="head">
            <div class="titles">
              ${(r.brand??"ECCO")!==""?N`<div class="wordmark"><span class="wm-accent">${(r.brand??"ECCO").slice(0,1)}</span>${(r.brand??"ECCO").slice(1)}</div>`:y}
              <div class="brand">${r.title??"Energy Flow"}</div>
              ${r.subtitle?N`<div class="subtitle">${r.subtitle}</div>`:y}
            </div>
            <button class=${`chip tone-${Ge.tone}`} type="button" @click=${()=>this._moreInfo(s.telemetry_online)} title=${Ge.title}>
              <span class="dot"></span>${Ge.text}
            </button>
          </header>
          ${C?N`<div class="strip stale-strip">${k.reason==="telemetry_offline"?"Telemetry offline: the values shown are the last received, not live.":`Values are stale: the newest power reading is ${fe(k.ageS)}.`}</div>`:y}
          <div class="body">
            <div class="scene-wrap">
              ${gr(vr)}
              ${_r?N`<div class="banner idle-banner">Site idle: no power is flowing above ${5} W.</div>`:y}
            </div>
            <div class="side">
              ${r.features?.show_status_panel===!1?y:this._renderStatus(n,i,C,k.ageS)}
              ${r.features?.show_details_panel===!1?y:this._renderDetails(n,a,l,c,p,f,g,h)}
            </div>
          </div>
        </div>
      </ha-card>
    `}_chip(r,n,o,s){return r==="off"?{text:"Telemetry offline",tone:"alert",title:"The dongle's telemetry polling is offline"}:o&&s==="age"?{text:`Stale \xB7 ${fe(n)}`,tone:"warn",title:"No power reading has updated recently"}:r==="on"?{text:"System online",tone:"ok",title:n===null?"Telemetry online":`Telemetry online \xB7 updated ${fe(n)}`}:{text:n===null?"Status unknown":`Updated ${fe(n)}`,tone:"muted",title:"No telemetry-online entity configured"}}_renderStatus(r,n,o,s){let i=this._config,a=i.ecco??{},l=i.nodes??{},c=[],p=a.tou,u=sr((p?.slot_start_minutes??[]).map(_=>$(r,_)),ir(n),p?.valid?z(A(r,p.valid)):"unknown"),f=u.slot===null?null:u.slot-1,m=f===null?void 0:p?.slot_target_soc?.[f],g=f===null?void 0:p?.slot_charge_source?.[f],h=f===null?void 0:p?.slot_power?.[f],O=$(r,m),T=A(r,g),F=$(r,h);c.push({key:"tou",icon:"clock",label:"TOU Slot",value:u.value,sub:u.sub,tone:u.tone,entity:f===null?p?.slot_start_minutes?.[0]:p?.slot_start_minutes?.[f],title:"The slot containing the current local time, from the six slot start sensors"}),c.push({key:"charge",icon:"plug",label:"Charge Source",value:g&&T&&T!=="unknown"&&T!=="unavailable"?T:"--",sub:f===null?"Needs the current slot":F!==null?`Slot limit ${Z(F,i.format)}`:"Current slot setting",tone:T&&T.toLowerCase()==="grid"?"accent":"muted",entity:g}),c.push({key:"target",icon:"target",label:"Target SOC",value:ut(O),sub:f===null?"Needs the current slot":`Slot ${u.slot} setting`,tone:O===null?"muted":"accent",entity:m});let x=l.battery?.time_to_reserve,I=Ae(x,$(r,x),H(r,x)?.unit_of_measurement),v=De(x,I,H(r,x)),S=nr(v);c.push({key:"runtime",icon:"battery",label:"Runtime",value:S.value,sub:S.sub,tone:S.tone,entity:x,title:v?ht(v):"No time-to-reserve entity configured"});let k=a.free_power,C=gt({active:z(A(r,k?.active)),endsAtText:A(r,k?.ends_at),scheduleStatus:A(r,k?.schedule_status),statusText:A(r,k?.status),scheduleAttrs:H(r,k?.schedule_status),anyConfigured:!!(k?.active||k?.status||k?.schedule_status)},this._nowMs,"free_power");c.push({key:"fp",icon:"leaf",label:"Free Power",value:C.value,sub:C.sub,tone:C.tone,entity:k?.status??k?.active??k?.schedule_status,title:A(r,k?.status)});let b=a.dump_to_grid,M=gt({active:z(A(r,b?.active)),endsAtText:A(r,b?.ends_at),scheduleStatus:A(r,b?.schedule_status),statusText:A(r,b?.status),scheduleAttrs:H(r,b?.schedule_status),exportPowerW:$(r,b?.export_power),stopSoc:$(r,b?.stop_soc),anyConfigured:!!(b?.active||b?.status||b?.schedule_status)},this._nowMs,"dump");c.push({key:"dump",icon:"swap",label:"Dump to Grid",value:M.value,sub:M.sub,tone:M.tone,entity:b?.status??b?.active??b?.schedule_status,title:A(r,b?.status)});let R=yt(a.health?.sensors??[],a.health?.attention??[],r);c.push({key:"health",icon:R.grade==="FAILED"?"alert":"heart",label:"Health",value:R.value,sub:R.sub,tone:R.tone,entity:a.health?.sensors?.[0],wide:!0,title:[...R.failed.map(_=>`FAILED: ${_}`),...R.degraded.map(_=>`DEGRADED: ${_}`),...R.attention.map(_=>`attention: ${_}`),...R.unknown.map(_=>`unknown: ${_}`)].join(`
`)||"All configured subsystems healthy"});let te=$(r,a.forecast?.today),re=$(r,a.forecast?.remaining),W=$(r,i.today?.solar);return c.push({key:"forecast",icon:"forecast",label:"Forecast Today",value:L(te,i.format),sub:re!==null?`${L(re,i.format)} still expected`+(W!==null?` \xB7 ${L(W,i.format)} so far`:""):W!==null?`${L(W,i.format)} generated so far`:a.forecast?.today?"Remaining forecast unavailable":"No forecast entity configured",tone:te===null?"muted":"ok",entity:a.forecast?.remaining??a.forecast?.today,wide:!0}),N`
      <section class="status" aria-label="ECCO system status">
        <div class="status-head">
          <span class="status-title">ECCO System Status</span>
          <span class=${`status-age ${o?"stale":""}`}><span class="dot"></span>${s===null?"No timestamp":`Updated ${fe(s)}`}</span>
        </div>
        <div class="tiles">
          ${c.map(_=>N`
              <button
                type="button"
                class=${`tile tone-${_.tone} ${_.wide?"wide":""} ${_.entity?"clickable":""}`}
                title=${_.title??""}
                ?disabled=${!_.entity}
                @click=${()=>this._moreInfo(_.entity)}
              >
                <span class="tile-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d=${he[_.icon]}></path></svg></span>
                <span class="tile-text">
                  <span class="tile-label">${_.label}</span>
                  <span class="tile-value">${_.value}</span>
                  ${_.sub?N`<span class="tile-sub">${_.sub}</span>`:y}
                </span>
                ${_.entity?N`<svg class="tile-chev" viewBox="0 0 24 24" aria-hidden="true"><path d=${he.chevron}></path></svg>`:y}
              </button>
            `)}
        </div>
      </section>
    `}_renderDetails(r,n,o,s,i,a,l,c){let p=this._config,u=p.nodes??{},f=p.ecco??{},m=p.inverter_details??{},g=p.format,h=(b,M,R,te)=>N`
      <div class=${`row ${R?"clickable":""}`} @click=${()=>this._moreInfo(R)} role=${R?"button":"listitem"} tabindex=${R?0:-1}>
        <span class="row-label">${b}</span>
        <span class="row-value">${M}${te?N`<span class="row-note">${te}</span>`:y}</span>
      </div>`,O=b=>{let M=$(r,b);return M===null?"--":`${M.toFixed(1)} \xB0C`},T=or(u.battery?.time_to_target,r),F=z(A(r,u.grid?.connected)),x=u.battery?.time_to_reserve,I=De(x,Ae(x,$(r,x),H(r,x)?.unit_of_measurement),H(r,x)),v=yt(f.health?.sensors??[],f.health?.attention??[],r),S=p.today??{},k=Object.values(S).some(Boolean),C=$(r,f.forecast?.tomorrow);return N`
      <details class="details" ?open=${this._detailsOpen} @toggle=${b=>this._detailsOpen=b.target.open}>
        <summary>
          <span>Inverter, grid and diagnostics</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${he.chevron}></path></svg>
        </summary>
        <div class="details-grid">
          <div class="group">
            <div class="group-title">Inverter</div>
            ${h("State",A(r,u.inverter?.state)??"--",u.inverter?.state)}
            ${h("AC output",Z(i,g),u.inverter?.power)}
            ${h("Home load",Z(c,g),u.home?.power,$(r,u.home?.power)===0&&c!==0?"derived":void 0)}
            ${h("AC transformer",O(m.ac_temperature),m.ac_temperature)}
            ${h("DC transformer",O(m.dc_temperature),m.dc_temperature)}
            ${m.temperature?h("Temperature",O(m.temperature),m.temperature):y}
          </div>
          <div class="group">
            <div class="group-title">Grid</div>
            ${h("Connected",F==="on"?"Yes":F==="off"?"No":"Unknown",u.grid?.connected)}
            ${h("Power",l===null?"--":`${Z(Math.abs(l),g)} ${l>=5?"import":l<=-5?"export":""}`,u.grid?.power)}
            ${h("Voltage",$(r,u.grid?.voltage)===null?"--":`${$(r,u.grid?.voltage).toFixed(1)} V`,u.grid?.voltage)}
            ${h("Frequency",$(r,u.grid?.frequency)===null?"--":`${$(r,u.grid?.frequency).toFixed(2)} Hz`,u.grid?.frequency)}
          </div>
          <div class="group">
            <div class="group-title">Solar</div>
            ${n.map((b,M)=>h(b.label??`Array ${M+1}`,Z(o[M]??null,g),b.power))}
            ${h("Total",Z(s,g),u.solar_total,u.solar_total?void 0:n.length>1?"sum of arrays":void 0)}
            ${f.forecast?.tomorrow?h("Forecast tomorrow",L(C,g),f.forecast.tomorrow):y}
          </div>
          <div class="group">
            <div class="group-title">Battery</div>
            ${h("Power",a===null?"--":`${Z(Math.abs(a),g)} ${a>=5?"discharge":a<=-5?"charge":""}`,u.battery?.power)}
            ${h("State of charge",ut($(r,u.battery?.soc)),u.battery?.soc)}
            ${h("Time to reserve",I?ht(I).replace(/^Time to reserve: /,""):"No entity configured",x)}
            ${h("Time to charge target",T.value,u.battery?.time_to_target,T.sub)}
            ${m.battery_temperature?h("Temperature",O(m.battery_temperature),m.battery_temperature):y}
          </div>
          ${(f.health?.sensors?.length??0)>0?N`<div class="group">
                  <div class="group-title">Health</div>
                  ${(f.health?.sensors??[]).map(b=>{let M=(A(r,b)??"--").toUpperCase();return h(b.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/_/g," "),M==="HEALTHY"?"Healthy":M==="DEGRADED"?"Degraded":M==="FAILED"?"Failed":"Unknown",b,typeof H(r,b)?.summary=="string"&&M!=="HEALTHY"?String(H(r,b)?.summary).trim().slice(0,80):void 0)})}
                  ${(f.health?.attention??[]).map(b=>h(b.replace(/^.*?\./,"").replace(/_/g," "),z(A(r,b))==="on"?"Needs attention":z(A(r,b))==="off"?"Clear":"Unknown",b))}
                  ${v.attention.length+v.failed.length>0?N`<div class="row-note block">Warnings are listed in full above; the Health tile summarises them.</div>`:y}
                </div>`:y}
          ${k?N`<div class="group today">
                  <div class="group-title">Today</div>
                  ${h("Solar",L($(r,S.solar),g),S.solar)}
                  ${h("Load",L($(r,S.load),g),S.load)}
                  ${h("Import",L($(r,S.import),g),S.import)}
                  ${h("Export",L($(r,S.export),g),S.export)}
                  ${h("Battery charge",L($(r,S.battery_charge),g),S.battery_charge)}
                  ${h("Battery discharge",L($(r,S.battery_discharge),g),S.battery_discharge)}
                </div>`:y}
        </div>
      </details>
    `}_pathFor(r,n){let o=r.querySelector(`#${CSS.escape(n)}`);if(!o)return null;let s=o.getAttribute("d")??"",i=this._lengthCache.get(o);return(!i||i.d!==s)&&(i={d:s,length:o.getTotalLength()},this._lengthCache.set(o,i)),i.length?{path:o,length:i.length}:null}_animate(){this._raf=requestAnimationFrame(()=>this._animate());let r=this.shadowRoot;if(!r||this._reducedMotion)return;let n=r.querySelectorAll(".pulse");if(!n.length)return;let o=performance.now()/1e3;n.forEach(s=>{let i=s.dataset.path,a=parseFloat(s.dataset.duration??""),l=parseFloat(s.dataset.phase??"0");if(!i||!a)return;let c=this._pathFor(r,i);if(!c)return;let p=(o/a+l)%1;s.dataset.reversed==="1"&&(p=1-p);let u=c.path.getPointAtLength(p*c.length);s.setAttribute("transform",`translate(${u.x.toFixed(2)},${u.y.toFixed(2)})`)})}_placeChevrons(){let r=this.shadowRoot;r&&r.querySelectorAll(".chevron").forEach(n=>{let o=n.dataset.path,s=parseFloat(n.dataset.phase??"0.5");if(!o)return;let i=this._pathFor(r,o);if(!i)return;let a=n.dataset.reversed==="1",l=(a?1-s:s)*i.length,c=i.path.getPointAtLength(Math.max(0,l-2)),p=i.path.getPointAtLength(Math.min(i.length,l+2)),u=Math.atan2(p.y-c.y,p.x-c.x)*180/Math.PI+(a?180:0),f=i.path.getPointAtLength(l);n.setAttribute("transform",`translate(${f.x.toFixed(2)},${f.y.toFixed(2)}) rotate(${u.toFixed(1)})`)})}};U.styles=qe`
    :host {
      display: block;
      --ef-bg-a: #0a1220;
      --ef-bg-b: #0d1626;
      --ef-surface: rgba(255, 255, 255, 0.045);
      --ef-surface-2: rgba(255, 255, 255, 0.07);
      --ef-border: rgba(255, 255, 255, 0.09);
      --ef-text: #e9eefb;
      --ef-muted: #8e9bb7;
      --ef-ok: #35e08a;
      --ef-warn: #f5b942;
      --ef-alert: #ff6b6b;
      --ef-accent: #5aa9ff;
      --ef-solar: #f7c948;
      --ef-grid: #3ea6ff;
      --ef-battery: #35e08a;
      --ef-home: #a9dcff;
      color: var(--ef-text);
      font-family: var(--paper-font-body1_-_font-family, "Inter", "Segoe UI", Roboto, system-ui, sans-serif);
    }
    ha-card {
      background: radial-gradient(120% 90% at 20% 0%, #14213a 0%, var(--ef-bg-a) 48%, var(--ef-bg-b) 100%);
      border-radius: 24px;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.06);
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
    }
    .card {
      container-type: inline-size;
      padding: 14px 14px 10px;
    }
    .head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 4px 4px 8px;
    }
    .wordmark {
      font-size: 15px;
      font-weight: 900;
      letter-spacing: 0.34em;
      color: #dfe7f7;
      margin-bottom: 2px;
    }
    .wm-accent {
      color: var(--ef-ok);
    }
    .brand {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.02em;
      line-height: 1.1;
    }
    .subtitle {
      color: var(--ef-muted);
      font-size: 13px;
      margin-top: 3px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--ef-border);
      background: var(--ef-surface);
      color: var(--ef-text);
      border-radius: 999px;
      padding: 8px 14px;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--ef-muted);
      box-shadow: 0 0 10px currentColor;
      flex: none;
    }
    .tone-ok .dot,
    .status-age .dot {
      background: var(--ef-ok);
      color: var(--ef-ok);
    }
    .tone-warn .dot,
    .status-age.stale .dot {
      background: var(--ef-warn);
      color: var(--ef-warn);
    }
    .tone-alert .dot {
      background: var(--ef-alert);
      color: var(--ef-alert);
    }
    .body {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
    }
    @container (min-width: 760px) {
      .body {
        grid-template-columns: minmax(0, 1.75fr) minmax(300px, 1fr);
        align-items: start;
      }
    }
    /* Artwork plates: the whole 1448 x 1086 canvas at every width (no crop, so the hardware anchors never move). */
    .scene.artwork {
      aspect-ratio: 1448 / 1086;
      max-height: none;
      height: auto;
      background: #0a1322;
    }
    .scene.artwork .plate {
      image-rendering: auto;
    }
    .scene.artwork .plate.entering {
      animation: ef3d-plate-in var(--ef-crossfade, 900ms) ease-in-out both;
    }
    @keyframes ef3d-plate-in {
      from {
        opacity: 0;
      }
      to {
        opacity: 1;
      }
    }
    .scene.artwork .pill-label {
      font-size: calc(11px * var(--k, 1));
    }
    .scene.artwork .pill-value {
      font-size: calc(19px * var(--k, 1));
    }
    .scene.artwork .pill-sub {
      font-size: calc(10px * var(--k, 1));
    }
    .scene.artwork .ring-value {
      font-size: calc(12px * var(--k, 1));
    }
    .scene.artwork .ring-caption {
      font-size: calc(6.5px * var(--k, 1));
    }
    .scene.artwork .pill-border {
      stroke-width: calc(1.4px * var(--k, 1));
    }
    .scene.artwork .ring-track,
    .scene.artwork .ring-fill {
      stroke-width: calc(5px * var(--k, 1));
    }
    .scene.artwork .pill-bg {
      fill: rgba(7, 12, 24, 0.78);
    }
    .scene.artwork .chevron path {
      stroke-width: 2;
    }
    .scene-wrap {
      position: relative;
      border-radius: 20px;
      overflow: hidden;
      background: #0a1322;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .scene {
      display: block;
      width: 100%;
      height: auto;
      max-height: 640px;
      user-select: none;
    }
    .banner {
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 12px;
      padding: 8px 12px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
      background: rgba(10, 15, 28, 0.82);
      border: 1px solid var(--ef-border);
      backdrop-filter: blur(6px);
    }
    .strip {
      margin: 0 0 10px;
      padding: 9px 14px;
      border-radius: 12px;
      font-size: 12.5px;
      font-weight: 600;
      border: 1px solid var(--ef-border);
      background: var(--ef-surface);
    }
    .stale-strip {
      color: var(--ef-warn);
      border-color: rgba(245, 185, 66, 0.45);
      background: rgba(245, 185, 66, 0.08);
    }
    .side {
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      container-type: inline-size;
    }
    .idle-banner {
      color: var(--ef-muted);
      bottom: auto;
      top: 92px;
      left: auto;
      right: 12px;
      max-width: 46%;
      font-weight: 500;
    }

    /* ---- scene palette (night default) ---- */
    .scene {
      --sky-a: #182845;
      --sky-b: #0a1322;
      --ground-top: #10322d;
      --ground-side: #07160f;
      --lawn: rgba(255, 255, 255, 0.03);
      --drive: #2a3346;
      --wall-l: #3b4356;
      --wall-r: #272e3d;
      --roof: #1a2130;
      --roof-back: #121826;
      --window: #ffd37a;
      --window-glow: 0.75;
      --pv: #163a74;
      --pv-line: rgba(140, 190, 255, 0.35);
      --canopy-1: #1f5a3c;
      --canopy-2: #184830;
      --canopy-3: #12392a;
      --lamp: 1;
      --star: 0.8;
      --moon: 1;
      --sun: 0;
      --cab: #d9dde6;
      --cab-r: #aab1c0;
      --cab-t: #eef1f6;
      --wire: rgba(170, 190, 220, 0.4);
    }
    .scene.dusk {
      --sky-a: #3a3558;
      --sky-b: #121a2e;
      --ground-top: #1c4635;
      --wall-l: #5a5f73;
      --wall-r: #3b4052;
      --window-glow: 0.5;
      --pv: #1b4a8f;
      --star: 0.25;
      --moon: 0.5;
      --sun: 0.55;
      --canopy-1: #2b6a46;
      --canopy-2: #205538;
      --canopy-3: #18432d;
    }
    .scene.day {
      --sky-a: #35598f;
      --sky-b: #16243f;
      --ground-top: #2f6b45;
      --ground-side: #16331f;
      --lawn: rgba(255, 255, 255, 0.05);
      --drive: #4a5569;
      --wall-l: #cdc7bb;
      --wall-r: #9b958b;
      --roof: #2d3443;
      --roof-back: #232a38;
      --window: #2f4b73;
      --window-glow: 0;
      --pv: #2460bb;
      --pv-line: rgba(200, 225, 255, 0.45);
      --canopy-1: #3f8c57;
      --canopy-2: #2f7246;
      --canopy-3: #245a37;
      --lamp: 0;
      --star: 0;
      --moon: 0;
      --sun: 1;
      --wire: rgba(210, 225, 245, 0.45);
    }
    .sky-a {
      stop-color: var(--sky-a);
    }
    .sky-b {
      stop-color: var(--sky-b);
    }
    .star {
      fill: #ffffff;
      opacity: var(--star);
    }
    .moon {
      fill: #e9f0ff;
      opacity: var(--moon);
    }
    .moon-halo {
      fill: #cfe0ff;
      opacity: calc(var(--moon) * 0.12);
      filter: url(#ef3d-blur-soft);
    }
    .sun-disc {
      fill: #ffe9a8;
      opacity: var(--sun);
    }
    .sun-halo {
      fill: #ffd56a;
      opacity: calc(var(--sun) * 0.22);
      filter: url(#ef3d-blur-soft);
    }
    .ground-top {
      fill: var(--ground-top);
    }
    .ground-side {
      fill: var(--ground-side);
    }
    .ground-side-r {
      filter: brightness(0.8);
    }
    .lawn-stripe {
      fill: var(--lawn);
    }
    .drive {
      fill: var(--drive);
      opacity: 0.9;
    }
    .drive.path {
      opacity: 0.55;
    }
    .tree-shadow {
      fill: rgba(0, 0, 0, 0.35);
    }
    .trunk {
      fill: #3b2a1e;
    }
    .canopy.c1 {
      fill: var(--canopy-1);
    }
    .canopy.c2 {
      fill: var(--canopy-2);
    }
    .canopy.c3 {
      fill: var(--canopy-3);
    }
    .lamp-post {
      stroke: #6a7388;
      stroke-width: 1.2;
    }
    .lamp-light {
      fill: #ffe6a0;
      opacity: calc(0.25 + var(--lamp) * 0.75);
    }
    .lamp-halo {
      fill: #ffd36a;
      opacity: calc(var(--lamp) * 0.28);
      filter: url(#ef3d-blur);
    }
    .contact-shadow {
      fill: rgba(0, 0, 0, 0.42);
      filter: url(#ef3d-blur);
    }
    .contact-shadow.soft {
      fill: rgba(0, 0, 0, 0.5);
    }
    .wall-l {
      fill: var(--wall-l);
    }
    .wall-r {
      fill: var(--wall-r);
    }
    .gable {
      filter: brightness(1.06);
    }
    .window {
      fill: var(--window);
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
      filter: drop-shadow(0 0 calc(var(--window-glow) * 6px) rgba(255, 200, 100, var(--window-glow)));
    }
    .window.small {
      opacity: 0.85;
    }
    .door {
      fill: #5a3d2b;
      stroke: rgba(0, 0, 0, 0.4);
      stroke-width: 0.6;
    }
    .garage-door {
      fill: rgba(255, 255, 255, 0.16);
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
    }
    .garage-line {
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
      fill: none;
    }
    .roof-front {
      fill: var(--roof);
    }
    .roof-back {
      fill: var(--roof-back);
    }
    .roof-flat {
      fill: var(--roof-back);
    }
    .roof-flat-top {
      fill: var(--roof);
    }
    .roof-lip {
      fill: #0f1420;
    }
    .fascia {
      fill: #0d111a;
    }
    .ridge {
      stroke: rgba(255, 255, 255, 0.18);
      stroke-width: 1;
      fill: none;
    }
    .pv {
      fill: var(--pv);
      stroke: rgba(190, 220, 255, 0.55);
      stroke-width: 0.7;
    }
    .pv-line {
      stroke: var(--pv-line);
      stroke-width: 0.5;
    }
    .inverter-face {
      fill: #c9ced8;
      stroke: rgba(0, 0, 0, 0.45);
      stroke-width: 0.6;
    }
    .inverter-vent {
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
      fill: none;
    }
    .inverter-led {
      fill: var(--ef-ok);
    }
    .inverter-led-halo {
      fill: var(--ef-ok);
      opacity: 0.35;
      filter: url(#ef3d-blur);
    }
    .cab-l {
      fill: var(--cab);
    }
    .cab-r {
      fill: var(--cab-r);
    }
    .cab-t {
      fill: var(--cab-t);
    }
    .cab-strip-bg {
      fill: #1b2230;
    }
    .cab-strip {
      fill: var(--ef-battery);
      filter: drop-shadow(0 0 4px rgba(53, 224, 138, 0.9));
    }
    .cab-label {
      font-size: 7.5px;
      font-weight: 800;
      letter-spacing: 0.12em;
      fill: #2b3140;
      text-anchor: middle;
    }
    .pylon-line {
      stroke: #7a879e;
      stroke-width: 1.6;
      stroke-linecap: round;
    }
    .pylon-line.thin {
      stroke-width: 0.8;
      opacity: 0.8;
    }
    .wire {
      stroke: var(--wire);
      stroke-width: 1;
      fill: none;
    }
    .pylon-tip {
      fill: #ff6b6b;
      opacity: 0.9;
    }
    .pylon.live .pylon-line {
      filter: drop-shadow(0 0 3px rgba(62, 166, 255, 0.6));
    }
    .pylon.unknown {
      opacity: 0.6;
    }

    /* ---- flows ---- */
    .flow-base {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      opacity: 0.22;
    }
    .flow-dots {
      fill: none;
      stroke: var(--flow-colour);
      stroke-width: 2.4;
      stroke-linecap: round;
      stroke-dasharray: 0.1 7;
      opacity: 0.55;
    }
    .flow-glow {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      opacity: 0;
      filter: url(#ef3d-blur);
    }
    .flow-packets {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      opacity: 0;
      filter: drop-shadow(0 0 3px var(--flow-colour));
    }
    .flow.moving .flow-packets {
      animation: ef3d-dash linear infinite;
    }
    .flow.moving.reversed .flow-packets {
      animation-direction: reverse;
    }
    .flow.idle .flow-base,
    .flow.idle .flow-dots {
      opacity: 0.14;
    }
    .flow.unknown .flow-base {
      stroke: #6b778d;
      stroke-dasharray: 3 5;
      opacity: 0.45;
    }
    .flow.unknown .flow-dots {
      display: none;
    }
    .scene.stale .flow-base,
    .scene.stale .flow-dots {
      opacity: 0.12;
    }
    .pulse-halo {
      fill: var(--pulse-colour);
      opacity: 0.22;
      filter: url(#ef3d-blur);
    }
    .pulse-glow {
      fill: var(--pulse-colour);
      opacity: 0.9;
    }
    .pulse-core {
      fill: #ffffff;
    }
    .chevron path {
      stroke: var(--pulse-colour);
    }
    .scene.still .pulse {
      display: none;
    }
    .junction {
      fill: #e7edf7;
    }
    .junction-halo {
      opacity: 0.35;
      filter: url(#ef3d-blur);
    }
    .junction.led-ok,
    .junction-halo.led-ok {
      fill: #e7edf7;
    }
    .junction.led-warn,
    .junction-halo.led-warn {
      fill: var(--ef-warn);
    }
    .junction.led-off,
    .junction-halo.led-off {
      fill: #6b778d;
      opacity: 0.6;
    }
    @keyframes ef3d-dash {
      to {
        stroke-dashoffset: var(--dash-travel, -30);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .flow.moving .flow-packets {
        animation: none;
      }
      .pulse {
        display: none;
      }
    }

    /* ---- pills ---- */
    .pill {
      cursor: default;
    }
    .pill.clickable {
      cursor: pointer;
    }
    .pill-bg {
      fill: rgba(9, 14, 26, 0.84);
    }
    .pill-border {
      fill: none;
      stroke: var(--pill-colour);
      stroke-width: 1.4;
      opacity: 0.85;
      filter: drop-shadow(0 0 6px var(--pill-colour));
    }
    .pill.idle .pill-border,
    .pill.unknown .pill-border {
      opacity: 0.35;
      filter: none;
    }
    .pill.unknown .pill-border {
      stroke: #6b778d;
      stroke-dasharray: 4 3;
    }
    .pill.clickable:hover .pill-bg,
    .pill.clickable:focus-visible .pill-bg {
      fill: rgba(20, 28, 46, 0.92);
    }
    .pill:focus {
      outline: none;
    }
    .pill-icon-bg {
      fill: rgba(255, 255, 255, 0.06);
    }
    .pill-label {
      font-size: 11px;
      font-weight: 600;
      fill: #c8d2e6;
      letter-spacing: 0.01em;
    }
    .pill-value {
      font-size: 19px;
      font-weight: 800;
      fill: #ffffff;
      letter-spacing: -0.01em;
    }
    .pill.unknown .pill-value {
      fill: #8e9bb7;
    }
    .pill-sub {
      font-size: 10px;
      font-weight: 600;
      fill: var(--pill-colour);
    }
    .pill-extra {
      font-size: 10px;
      font-weight: 600;
      fill: #dfe7f7;
    }
    .scene.artwork .pill-extra {
      font-size: calc(10px * var(--k, 1));
    }
    .pill.tone-alert .pill-sub {
      fill: var(--ef-alert);
    }
    .pill.unknown .pill-sub,
    .pill.idle .pill-sub {
      fill: #8e9bb7;
    }
    .ring-track {
      fill: none;
      stroke: rgba(255, 255, 255, 0.1);
      stroke-width: 5;
    }
    .ring-fill {
      fill: none;
      stroke: var(--pill-colour);
      stroke-width: 5;
      stroke-linecap: round;
      filter: drop-shadow(0 0 4px var(--pill-colour));
    }
    .ring-value {
      font-size: 12px;
      font-weight: 800;
      fill: #fff;
      text-anchor: middle;
    }
    .ring-caption {
      font-size: 6.5px;
      font-weight: 700;
      fill: #8e9bb7;
      text-anchor: middle;
      letter-spacing: 0.1em;
    }

    /* ---- status grid ---- */
    .status {
      border-radius: 20px;
      background: var(--ef-surface);
      border: 1px solid var(--ef-border);
      padding: 12px;
    }
    .status-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 2px 4px 10px;
    }
    .status-title {
      font-weight: 700;
      font-size: 15px;
    }
    .status-age {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--ef-muted);
      font-size: 12px;
    }
    .status-age.stale {
      color: var(--ef-warn);
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .tile {
      display: grid;
      grid-template-columns: 30px minmax(0, 1fr) 12px;
      align-items: center;
      gap: 7px;
      text-align: left;
      border-radius: 14px;
      border: 1px solid var(--ef-border);
      background: rgba(255, 255, 255, 0.035);
      color: inherit;
      padding: 9px 6px 9px 8px;
      font: inherit;
      min-height: 72px;
      cursor: default;
    }
    /* Row three: Health (one column) and Solar Forecast (two columns), as in the reference. */
    .tiles .tile:nth-child(8) {
      grid-column: span 2;
    }
    /* Phones: two readable columns; three columns need about 150 px per tile. */
    @container (max-width: 459px) {
      .tiles {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .tiles .tile:nth-child(8) {
        grid-column: span 1;
      }
    }
    .tile.clickable {
      cursor: pointer;
    }
    .tile.clickable:hover,
    .tile.clickable:focus-visible {
      background: var(--ef-surface-2);
      border-color: rgba(255, 255, 255, 0.16);
      outline: none;
    }
    .tile-icon {
      width: 30px;
      height: 30px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: rgba(255, 255, 255, 0.06);
      color: var(--ef-accent);
    }
    .tile-icon svg,
    .tile-chev,
    summary svg {
      width: 18px;
      height: 18px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.9;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .tile-chev {
      width: 12px;
      height: 12px;
      color: rgba(255, 255, 255, 0.4);
    }
    .tone-ok .tile-icon {
      color: var(--ef-ok);
    }
    .tone-warn .tile-icon {
      color: var(--ef-warn);
    }
    .tone-alert .tile-icon {
      color: var(--ef-alert);
      background: rgba(255, 107, 107, 0.14);
    }
    .tone-accent .tile-icon {
      color: #b8a4ff;
    }
    .tone-muted .tile-icon {
      color: var(--ef-muted);
    }
    .tile-text {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    .tile-label {
      font-size: 11px;
      color: var(--ef-muted);
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tile-value {
      font-size: 16px;
      font-weight: 800;
      letter-spacing: -0.01em;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tone-muted .tile-value {
      color: #c3cbdc;
    }
    .tone-alert .tile-value {
      color: var(--ef-alert);
    }
    .tone-warn .tile-value {
      color: var(--ef-warn);
    }
    .tile-sub {
      font-size: 10.5px;
      color: var(--ef-muted);
      margin-top: 2px;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }

    /* ---- details ---- */
    .details {
      border-radius: 16px;
      border: 1px solid var(--ef-border);
      background: var(--ef-surface);
    }
    summary {
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 14px;
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
      color: #c8d2e6;
    }
    summary::-webkit-details-marker {
      display: none;
    }
    summary svg {
      width: 16px;
      height: 16px;
      transform: rotate(90deg);
      transition: transform 0.2s ease;
    }
    .details[open] summary svg {
      transform: rotate(-90deg);
    }
    .details-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 10px 18px;
      padding: 0 14px 14px;
    }
    .group-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ef-muted);
      font-weight: 700;
      padding: 8px 0 4px;
    }
    .row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 5px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      font-size: 13px;
    }
    .row.clickable {
      cursor: pointer;
    }
    .row.clickable:hover .row-value {
      color: #fff;
    }
    .row-label {
      color: var(--ef-muted);
      text-transform: capitalize;
    }
    .row-value {
      text-align: right;
      font-weight: 600;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
    }
    .row-note {
      font-size: 10.5px;
      color: var(--ef-muted);
      font-weight: 500;
    }
    .row-note.block {
      padding: 6px 0;
    }
  `,q([Fe({attribute:!1})],U.prototype,"hass",2),q([de()],U.prototype,"_config",2),q([de()],U.prototype,"_detailsOpen",2),q([de()],U.prototype,"_nowMs",2),q([de()],U.prototype,"_layers",2),q([de()],U.prototype,"_widthPx",2),U=q([zt("ecco-flow-3d-card")],U);window.customCards=[...window.customCards??[],{type:"ecco-flow-3d-card",name:"ECCO 3D Energy Flow",description:"Read-only isometric energy flow scene (solar, battery, grid, home) with animated power paths and the ECCO status grid.",preview:!1}];export{U as EccoFlow3dCard};
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
