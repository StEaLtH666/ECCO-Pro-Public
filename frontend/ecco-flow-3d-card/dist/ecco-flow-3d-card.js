var kr=Object.defineProperty;var Sr=Object.getOwnPropertyDescriptor;var Y=(e,t,r,n)=>{for(var o=n>1?void 0:n?Sr(t,r):t,i=e.length-1,s;i>=0;i--)(s=e[i])&&(o=(n?s(t,r,o):s(o))||o);return n&&o&&kr(t,r,o),o};var Pe=globalThis,Fe=Pe.ShadowRoot&&(Pe.ShadyCSS===void 0||Pe.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,Ye=Symbol(),kt=new WeakMap,xe=class{constructor(t,r,n){if(this._$cssResult$=!0,n!==Ye)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=r}get styleSheet(){let t=this.o,r=this.t;if(Fe&&t===void 0){let n=r!==void 0&&r.length===1;n&&(t=kt.get(r)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),n&&kt.set(r,t))}return t}toString(){return this.cssText}},St=e=>new xe(typeof e=="string"?e:e+"",void 0,Ye),qe=(e,...t)=>{let r=e.length===1?e[0]:t.reduce((n,o,i)=>n+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(o)+e[i+1],e[0]);return new xe(r,e,Ye)},At=(e,t)=>{if(Fe)e.adoptedStyleSheets=t.map(r=>r instanceof CSSStyleSheet?r:r.styleSheet);else for(let r of t){let n=document.createElement("style"),o=Pe.litNonce;o!==void 0&&n.setAttribute("nonce",o),n.textContent=r.cssText,e.appendChild(n)}},Ke=Fe?e=>e:e=>e instanceof CSSStyleSheet?(t=>{let r="";for(let n of t.cssRules)r+=n.cssText;return St(r)})(e):e;var{is:Ar,defineProperty:Er,getOwnPropertyDescriptor:Mr,getOwnPropertyNames:Cr,getOwnPropertySymbols:Tr,getPrototypeOf:Rr}=Object,Ne=globalThis,Et=Ne.trustedTypes,Pr=Et?Et.emptyScript:"",Fr=Ne.reactiveElementPolyfillSupport,we=(e,t)=>e,$e={toAttribute(e,t){switch(t){case Boolean:e=e?Pr:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,t){let r=e;switch(t){case Boolean:r=e!==null;break;case Number:r=e===null?null:Number(e);break;case Object:case Array:try{r=JSON.parse(e)}catch{r=null}}return r}},Oe=(e,t)=>!Ar(e,t),Mt={attribute:!0,type:String,converter:$e,reflect:!1,useDefault:!1,hasChanged:Oe};Symbol.metadata??=Symbol("metadata"),Ne.litPropertyMetadata??=new WeakMap;var j=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,r=Mt){if(r.state&&(r.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((r=Object.create(r)).wrapped=!0),this.elementProperties.set(t,r),!r.noAccessor){let n=Symbol(),o=this.getPropertyDescriptor(t,n,r);o!==void 0&&Er(this.prototype,t,o)}}static getPropertyDescriptor(t,r,n){let{get:o,set:i}=Mr(this.prototype,t)??{get(){return this[r]},set(s){this[r]=s}};return{get:o,set(s){let a=o?.call(this);i?.call(this,s),this.requestUpdate(t,a,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??Mt}static _$Ei(){if(this.hasOwnProperty(we("elementProperties")))return;let t=Rr(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(we("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(we("properties"))){let r=this.properties,n=[...Cr(r),...Tr(r)];for(let o of n)this.createProperty(o,r[o])}let t=this[Symbol.metadata];if(t!==null){let r=litPropertyMetadata.get(t);if(r!==void 0)for(let[n,o]of r)this.elementProperties.set(n,o)}this._$Eh=new Map;for(let[r,n]of this.elementProperties){let o=this._$Eu(r,n);o!==void 0&&this._$Eh.set(o,r)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let r=[];if(Array.isArray(t)){let n=new Set(t.flat(1/0).reverse());for(let o of n)r.unshift(Ke(o))}else t!==void 0&&r.push(Ke(t));return r}static _$Eu(t,r){let n=r.attribute;return n===!1?void 0:typeof n=="string"?n:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,r=this.constructor.elementProperties;for(let n of r.keys())this.hasOwnProperty(n)&&(t.set(n,this[n]),delete this[n]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return At(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,r,n){this._$AK(t,n)}_$ET(t,r){let n=this.constructor.elementProperties.get(t),o=this.constructor._$Eu(t,n);if(o!==void 0&&n.reflect===!0){let i=(n.converter?.toAttribute!==void 0?n.converter:$e).toAttribute(r,n.type);this._$Em=t,i==null?this.removeAttribute(o):this.setAttribute(o,i),this._$Em=null}}_$AK(t,r){let n=this.constructor,o=n._$Eh.get(t);if(o!==void 0&&this._$Em!==o){let i=n.getPropertyOptions(o),s=typeof i.converter=="function"?{fromAttribute:i.converter}:i.converter?.fromAttribute!==void 0?i.converter:$e;this._$Em=o;let a=s.fromAttribute(r,i.type);this[o]=a??this._$Ej?.get(o)??a,this._$Em=null}}requestUpdate(t,r,n,o=!1,i){if(t!==void 0){let s=this.constructor;if(o===!1&&(i=this[t]),n??=s.getPropertyOptions(t),!((n.hasChanged??Oe)(i,r)||n.useDefault&&n.reflect&&i===this._$Ej?.get(t)&&!this.hasAttribute(s._$Eu(t,n))))return;this.C(t,r,n)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,r,{useDefault:n,reflect:o,wrapped:i},s){n&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,s??r??this[t]),i!==!0||s!==void 0)||(this._$AL.has(t)||(this.hasUpdated||n||(r=void 0),this._$AL.set(t,r)),o===!0&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(r){Promise.reject(r)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[o,i]of this._$Ep)this[o]=i;this._$Ep=void 0}let n=this.constructor.elementProperties;if(n.size>0)for(let[o,i]of n){let{wrapped:s}=i,a=this[o];s!==!0||this._$AL.has(o)||a===void 0||this.C(o,void 0,i,a)}}let t=!1,r=this._$AL;try{t=this.shouldUpdate(r),t?(this.willUpdate(r),this._$EO?.forEach(n=>n.hostUpdate?.()),this.update(r)):this._$EM()}catch(n){throw t=!1,this._$EM(),n}t&&this._$AE(r)}willUpdate(t){}_$AE(t){this._$EO?.forEach(r=>r.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(r=>this._$ET(r,this[r])),this._$EM()}updated(t){}firstUpdated(t){}};j.elementStyles=[],j.shadowRootOptions={mode:"open"},j[we("elementProperties")]=new Map,j[we("finalized")]=new Map,Fr?.({ReactiveElement:j}),(Ne.reactiveElementVersions??=[]).push("2.1.2");var rt=globalThis,Ct=e=>e,Ie=rt.trustedTypes,Tt=Ie?Ie.createPolicy("lit-html",{createHTML:e=>e}):void 0,It="$lit$",q=`lit$${Math.random().toFixed(9).slice(2)}$`,Lt="?"+q,Nr=`<${Lt}>`,ne=document,_e=()=>ne.createComment(""),ke=e=>e===null||typeof e!="object"&&typeof e!="function",nt=Array.isArray,Or=e=>nt(e)||typeof e?.[Symbol.iterator]=="function",Xe=`[ 	
\f\r]`,ve=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Rt=/-->/g,Pt=/>/g,te=RegExp(`>|${Xe}(?:([^\\s"'>=/]+)(${Xe}*=${Xe}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Ft=/'/g,Nt=/"/g,Ht=/^(?:script|style|textarea|title)$/i,ot=e=>(t,...r)=>({_$litType$:e,strings:t,values:r}),O=ot(1),x=ot(2),kn=ot(3),oe=Symbol.for("lit-noChange"),g=Symbol.for("lit-nothing"),Ot=new WeakMap,re=ne.createTreeWalker(ne,129);function Ut(e,t){if(!nt(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return Tt!==void 0?Tt.createHTML(t):t}var Ir=(e,t)=>{let r=e.length-1,n=[],o,i=t===2?"<svg>":t===3?"<math>":"",s=ve;for(let a=0;a<r;a++){let l=e[a],d,c,u=-1,f=0;for(;f<l.length&&(s.lastIndex=f,c=s.exec(l),c!==null);)f=s.lastIndex,s===ve?c[1]==="!--"?s=Rt:c[1]!==void 0?s=Pt:c[2]!==void 0?(Ht.test(c[2])&&(o=RegExp("</"+c[2],"g")),s=te):c[3]!==void 0&&(s=te):s===te?c[0]===">"?(s=o??ve,u=-1):c[1]===void 0?u=-2:(u=s.lastIndex-c[2].length,d=c[1],s=c[3]===void 0?te:c[3]==='"'?Nt:Ft):s===Nt||s===Ft?s=te:s===Rt||s===Pt?s=ve:(s=te,o=void 0);let w=s===te&&e[a+1].startsWith("/>")?" ":"";i+=s===ve?l+Nr:u>=0?(n.push(d),l.slice(0,u)+It+l.slice(u)+q+w):l+q+(u===-2?a:w)}return[Ut(e,i+(e[r]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),n]},Se=class e{constructor({strings:t,_$litType$:r},n){let o;this.parts=[];let i=0,s=0,a=t.length-1,l=this.parts,[d,c]=Ir(t,r);if(this.el=e.createElement(d,n),re.currentNode=this.el.content,r===2||r===3){let u=this.el.content.firstChild;u.replaceWith(...u.childNodes)}for(;(o=re.nextNode())!==null&&l.length<a;){if(o.nodeType===1){if(o.hasAttributes())for(let u of o.getAttributeNames())if(u.endsWith(It)){let f=c[s++],w=o.getAttribute(u).split(q),y=/([.?@])?(.*)/.exec(f);l.push({type:1,index:i,name:y[2],strings:w,ctor:y[1]==="."?Qe:y[1]==="?"?Je:y[1]==="@"?et:ce}),o.removeAttribute(u)}else u.startsWith(q)&&(l.push({type:6,index:i}),o.removeAttribute(u));if(Ht.test(o.tagName)){let u=o.textContent.split(q),f=u.length-1;if(f>0){o.textContent=Ie?Ie.emptyScript:"";for(let w=0;w<f;w++)o.append(u[w],_e()),re.nextNode(),l.push({type:2,index:++i});o.append(u[f],_e())}}}else if(o.nodeType===8)if(o.data===Lt)l.push({type:2,index:i});else{let u=-1;for(;(u=o.data.indexOf(q,u+1))!==-1;)l.push({type:7,index:i}),u+=q.length-1}i++}}static createElement(t,r){let n=ne.createElement("template");return n.innerHTML=t,n}};function ae(e,t,r=e,n){if(t===oe)return t;let o=n!==void 0?r._$Co?.[n]:r._$Cl,i=ke(t)?void 0:t._$litDirective$;return o?.constructor!==i&&(o?._$AO?.(!1),i===void 0?o=void 0:(o=new i(e),o._$AT(e,r,n)),n!==void 0?(r._$Co??=[])[n]=o:r._$Cl=o),o!==void 0&&(t=ae(e,o._$AS(e,t.values),o,n)),t}var Ze=class{constructor(t,r){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=r}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:r},parts:n}=this._$AD,o=(t?.creationScope??ne).importNode(r,!0);re.currentNode=o;let i=re.nextNode(),s=0,a=0,l=n[0];for(;l!==void 0;){if(s===l.index){let d;l.type===2?d=new Ae(i,i.nextSibling,this,t):l.type===1?d=new l.ctor(i,l.name,l.strings,this,t):l.type===6&&(d=new tt(i,this,t)),this._$AV.push(d),l=n[++a]}s!==l?.index&&(i=re.nextNode(),s++)}return re.currentNode=ne,o}p(t){let r=0;for(let n of this._$AV)n!==void 0&&(n.strings!==void 0?(n._$AI(t,n,r),r+=n.strings.length-2):n._$AI(t[r])),r++}},Ae=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,r,n,o){this.type=2,this._$AH=g,this._$AN=void 0,this._$AA=t,this._$AB=r,this._$AM=n,this.options=o,this._$Cv=o?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,r=this._$AM;return r!==void 0&&t?.nodeType===11&&(t=r.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,r=this){t=ae(this,t,r),ke(t)?t===g||t==null||t===""?(this._$AH!==g&&this._$AR(),this._$AH=g):t!==this._$AH&&t!==oe&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):Or(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==g&&ke(this._$AH)?this._$AA.nextSibling.data=t:this.T(ne.createTextNode(t)),this._$AH=t}$(t){let{values:r,_$litType$:n}=t,o=typeof n=="number"?this._$AC(t):(n.el===void 0&&(n.el=Se.createElement(Ut(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===o)this._$AH.p(r);else{let i=new Ze(o,this),s=i.u(this.options);i.p(r),this.T(s),this._$AH=i}}_$AC(t){let r=Ot.get(t.strings);return r===void 0&&Ot.set(t.strings,r=new Se(t)),r}k(t){nt(this._$AH)||(this._$AH=[],this._$AR());let r=this._$AH,n,o=0;for(let i of t)o===r.length?r.push(n=new e(this.O(_e()),this.O(_e()),this,this.options)):n=r[o],n._$AI(i),o++;o<r.length&&(this._$AR(n&&n._$AB.nextSibling,o),r.length=o)}_$AR(t=this._$AA.nextSibling,r){for(this._$AP?.(!1,!0,r);t!==this._$AB;){let n=Ct(t).nextSibling;Ct(t).remove(),t=n}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},ce=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,r,n,o,i){this.type=1,this._$AH=g,this._$AN=void 0,this.element=t,this.name=r,this._$AM=o,this.options=i,n.length>2||n[0]!==""||n[1]!==""?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=g}_$AI(t,r=this,n,o){let i=this.strings,s=!1;if(i===void 0)t=ae(this,t,r,0),s=!ke(t)||t!==this._$AH&&t!==oe,s&&(this._$AH=t);else{let a=t,l,d;for(t=i[0],l=0;l<i.length-1;l++)d=ae(this,a[n+l],r,l),d===oe&&(d=this._$AH[l]),s||=!ke(d)||d!==this._$AH[l],d===g?t=g:t!==g&&(t+=(d??"")+i[l+1]),this._$AH[l]=d}s&&!o&&this.j(t)}j(t){t===g?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},Qe=class extends ce{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===g?void 0:t}},Je=class extends ce{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==g)}},et=class extends ce{constructor(t,r,n,o,i){super(t,r,n,o,i),this.type=5}_$AI(t,r=this){if((t=ae(this,t,r,0)??g)===oe)return;let n=this._$AH,o=t===g&&n!==g||t.capture!==n.capture||t.once!==n.once||t.passive!==n.passive,i=t!==g&&(n===g||o);o&&this.element.removeEventListener(this.name,this,n),i&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},tt=class{constructor(t,r,n){this.element=t,this.type=6,this._$AN=void 0,this._$AM=r,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(t){ae(this,t)}};var Lr=rt.litHtmlPolyfillSupport;Lr?.(Se,Ae),(rt.litHtmlVersions??=[]).push("3.3.3");var zt=(e,t,r)=>{let n=r?.renderBefore??t,o=n._$litPart$;if(o===void 0){let i=r?.renderBefore??null;n._$litPart$=o=new Ae(t.insertBefore(_e(),i),i,void 0,r??{})}return o._$AI(e),o};var it=globalThis,K=class extends j{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){let r=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=zt(r,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return oe}};K._$litElement$=!0,K.finalized=!0,it.litElementHydrateSupport?.({LitElement:K});var Hr=it.litElementPolyfillSupport;Hr?.({LitElement:K});(it.litElementVersions??=[]).push("4.2.2");var Dt=e=>(t,r)=>{r!==void 0?r.addInitializer(()=>{customElements.define(e,t)}):customElements.define(e,t)};var Ur={attribute:!0,type:String,converter:$e,reflect:!1,hasChanged:Oe},zr=(e=Ur,t,r)=>{let{kind:n,metadata:o}=r,i=globalThis.litPropertyMetadata.get(o);if(i===void 0&&globalThis.litPropertyMetadata.set(o,i=new Map),n==="setter"&&((e=Object.create(e)).wrapped=!0),i.set(r.name,e),n==="accessor"){let{name:s}=r;return{set(a){let l=t.get.call(this);t.set.call(this,a),this.requestUpdate(s,l,e,!0,a)},init(a){return a!==void 0&&this.C(s,void 0,e,a),a}}}if(n==="setter"){let{name:s}=r;return function(a){let l=this[s];t.call(this,a),this.requestUpdate(s,l,e,!0,a)}}throw Error("Unsupported decorator location: "+n)};function Le(e){return(t,r)=>typeof r=="object"?zr(e,t,r):((n,o,i)=>{let s=o.hasOwnProperty(i);return o.constructor.createProperty(i,n),s?Object.getOwnPropertyDescriptor(o,i):void 0})(e,t,r)}function ue(e){return Le({...e,state:!0,attribute:!1})}function Bt(e){return e?(Array.isArray(e)?e:[e]).filter(r=>!!r&&!!r.power):[]}var jt=180;function Gt(e){if(!e||typeof e!="object")throw new Error("ecco-flow-3d-card: invalid configuration");let t=e;if(!t.nodes||typeof t.nodes!="object"||Object.keys(t.nodes).length===0)throw new Error("ecco-flow-3d-card: at least one entry under `nodes:` is required");let r=t.ecco?.tou;for(let n of["slot_start_minutes","slot_target_soc","slot_charge_source","slot_power"]){let o=r?.[n];if(o!==void 0&&(!Array.isArray(o)||o.length!==6))throw new Error(`ecco-flow-3d-card: ecco.tou.${n} must list exactly six entities (slot 1 to slot 6)`)}}function Wt(e,t){return t==="discharge_positive"?e:-e}function Vt(e,t){return t==="export_positive"?-e:e}var Dr=150;function Yt(e,t,r){let n=t!==null&&r!==null?Math.max(0,t+r):null;return e===null||e===0&&n!==null&&n>Dr?n:Math.max(0,e)}function qt(e,t){if(e!==null)return Math.max(0,e);let r=t.filter(n=>n!==null);return r.length===0?null:Math.max(0,r.reduce((n,o)=>n+o,0))}var G=5;function Ee(e,t,r){if(t===null)return{id:e,magnitudeW:null,idle:!1,unknown:!0,reversed:!1};let n=Math.abs(t);return{id:e,magnitudeW:n,idle:n<G,unknown:!1,reversed:r&&t<0}}function Kt(e){return[Ee("solar",e.solarW===null?null:Math.max(0,e.solarW),!1),Ee("battery",e.batteryW,!0),Ee("grid",e.gridW,!0),Ee("home",e.homeW===null?null:Math.max(0,e.homeW),!1)]}function Xt(e,t,r,n){let o=s=>Ee("solar",s===null?null:Math.max(0,s),!1),i=o(e);return n>=2&&(t!==null||r!==null)?{card:i,main:o(t),garage:o(r)}:{card:i,main:o(e),garage:null}}function Zt(e){let t=e.filter(r=>!r.unknown);return t.length>0&&t.every(r=>r.idle)}function Qt(e){return e===null?"unknown":e>=G?"discharging":e<=-G?"charging":"idle"}function Jt(e){return e===null?"unknown":e>=G?"importing":e<=-G?"exporting":"idle"}var rr=6e3,Br=2.4,jr=.45,er=2.6,nr=15,Ue=4,Gr=9,st=2.7,Wr=5.4,lt=2.6,Vr=3.3,Yr=.6,tr=5.5,at=3.1,qr=4.9;function Kr(e){if(!(e>G))return 0;let t=Math.log(e/G)/Math.log(rr/G),r=Math.min(1,Math.max(0,t));return Math.pow(r,Br)}function Xr(e){return e<750?1:e<3e3?2:e<6e3?3:4}var Zr={intensity:0,moving:!1,dashDurationS:0,dashLen:Ue,gapLen:nr-Ue,packetWidthPx:st,baseWidthPx:lt,packetOpacity:0,glowPx:0,ballCount:0,ballDurationS:0,ballRadiusPx:at};function X(e,t){if(e.unknown||e.idle||t||e.magnitudeW===null)return Zr;let r=e.magnitudeW,n=Kr(r),o=Math.min(1,r/rr),i=Ue+n*(Gr-Ue);return{intensity:n,moving:!0,dashDurationS:er-n*(er-jr),dashLen:i,gapLen:nr-i,packetWidthPx:st+n*(Wr-st),baseWidthPx:lt+o*(Vr-lt),packetOpacity:.62+n*.36,glowPx:1.6+n*2.4,ballCount:Xr(r),ballDurationS:tr-n*(tr-Yr),ballRadiusPx:at+n*(qr-at)}}function ct(e){if(e==null||e==="unknown"||e==="unavailable"||e===""||e==="none"||e==="None")return null;let t=Number(e);return Number.isFinite(t)?t:null}function Z(e,t){if(e==null||Number.isNaN(e))return"--";let r=t?.power_unit??"auto",n=Math.abs(e);return r==="kw"||r==="auto"&&n>=1e3?`${(e/1e3).toFixed(t?.precision??2)} kW`:`${e.toFixed(t?.precision??0)} W`}function de(e){if(e==null||Number.isNaN(e))return"--";let t=Math.abs(e);return t>=1e4?`${(e/1e3).toFixed(0)} kW`:t>=1e3?`${(e/1e3).toFixed(1)} kW`:`${Math.round(e)} W`}function I(e,t){return e==null||Number.isNaN(e)?"--":`${e.toFixed(t?.energy_precision??1)} kWh`}function ut(e){return e==null||!Number.isFinite(e)?"--":`${Math.round(e)}%`}function W(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let t=Math.round(e);if(t===0)return e>0?"<1 min":"0 min";if(t<60)return`${t} min`;if(t<1440){let o=Math.floor(t/60),i=t%60;return i===0?`${o} h`:`${o} h ${i} min`}let r=Math.floor(t/1440),n=Math.floor(t%1440/60);return n===0?`${r} d`:`${r} d ${n} h`}function ze(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let t=Math.round(e);if(t===0)return e>0?"<1m":"0m";if(t<60)return`\u2248${t}m`;if(t<1440){let o=Math.floor(t/60),i=t%60;return i===0?`\u2248${o}h`:`\u2248${o}h ${i}m`}let r=Math.floor(t/1440),n=Math.floor(t%1440/60);return n===0?`\u2248${r}d`:`\u2248${r}d ${n}h`}function dt(e){if(e==null||!Number.isFinite(e))return"--:--";let t=(Math.round(e)%1440+1440)%1440;return`${String(Math.floor(t/60)).padStart(2,"0")}:${String(t%60).padStart(2,"0")}`}function pt(e){return`${String(e.getHours()).padStart(2,"0")}:${String(e.getMinutes()).padStart(2,"0")}`}function pe(e){return e===null||!Number.isFinite(e)||e<0?"--":e<5?"just now":e<60?`${Math.floor(e)} s ago`:e<3600?`${Math.floor(e/60)} min ago`:e<86400?`${Math.floor(e/3600)} h ago`:`${Math.floor(e/86400)} d ago`}function E(e,t){return t?e[t]?.state:void 0}function _(e,t){return t?ct(e[t]?.state):null}function L(e,t){return t?e[t]?.attributes:void 0}function D(e){return e==="on"||e==="true"||e==="True"?"on":e==="off"||e==="false"||e==="False"?"off":"unknown"}var Qr=new Map([["s",1/60],["min",1],["h",60],["d",1440]]);function Me(e,t,r){if(!e)return;let n=r==null||r===""?1:Qr.get(r);return n!==void 0&&t!==null&&t>=0?t*n:null}var Jr=["discharging","at_reserve","charging","holding","insufficient_data","stale"];function or(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0?e:null}function Be(e,t,r){if(!e||t===void 0)return;let n=r?.status,i=Jr.includes(n)?n:t!==null?"discharging":"insufficient_data";i==="discharging"&&t===null&&(i="insufficient_data");let s=i==="discharging"||i==="at_reserve",a=typeof r?.summary=="string"&&r.summary.trim()!==""?r.summary:null;return{status:i,minutes:s?t:null,low:i==="discharging"?or(r?.minutes_low):null,high:i==="discharging"?or(r?.minutes_high):null,beyondHorizon:i==="discharging"&&r?.beyond_horizon===!0,solarAssisted:i==="discharging"&&r?.solar_assisted===!0,summary:a}}var ir="Over 3 days";function ft(e){switch(e.status){case"discharging":return e.beyondHorizon?ir:`${ze(e.minutes)} to reserve`;case"at_reserve":return"At reserve";case"charging":return"Charging";case"holding":return"Holding";case"stale":return"Telemetry stale";default:return"Insufficient data"}}function sr(e){if(!e)return{value:"--",sub:"No runtime entity",tone:"muted"};switch(e.status){case"discharging":return{value:e.beyondHorizon?">3 d":ze(e.minutes),sub:e.beyondHorizon?"to reserve (estimate)":e.low!==null&&e.high!==null?`to reserve \xB7 likely ${W(e.low)} to ${W(e.high)}`:"to reserve (estimate)",tone:"ok"};case"at_reserve":return{value:"At reserve",sub:e.summary??"At or below the reserve",tone:"warn"};case"charging":return{value:"Charging",sub:"No discharge estimate while charging",tone:"ok"};case"holding":return{value:"Holding",sub:"Neither charging nor discharging",tone:"muted"};case"stale":return{value:"Stale",sub:"Estimate paused: telemetry stale",tone:"warn"};default:return{value:"--",sub:e.summary??"Insufficient data",tone:"muted"}}}function ht(e){if(e.status!=="discharging")return`Time to reserve: ${e.summary??ft(e)}`;let t=[e.beyondHorizon?`${ir} until the batteries reach the configured reserve at recent usage`:`Approximately ${W(e.minutes)} until the batteries reach the configured reserve at recent usage`];return!e.beyondHorizon&&e.low!==null&&e.high!==null&&t.push(`likely ${W(e.low)} to ${W(e.high)}`),e.solarAssisted&&t.push("solar-assisted, so it shortens as solar output falls"),t.push("an estimate, not a guarantee"),`Time to reserve: ${t.join("; ")}`}function lr(e,t){if(!e)return{value:"Not available",sub:"No ECCO entity provides a time to charge target",tone:"muted"};let r=Me(e,_(t,e),L(t,e)?.unit_of_measurement);return r==null?{value:"--",sub:"Entity has no value",tone:"muted"}:{value:ze(r),sub:"to charge target (entity value)",tone:"ok"}}var en=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function tn(e){if(!e)return null;let t=en.exec(e.trim());if(!t)return null;let r=new Date(Number(t[1]),Number(t[2])-1,Number(t[3]),Number(t[4]),Number(t[5]),Number(t[6]));return Number.isNaN(r.getTime())?null:r}function rn(e,t,r){return r?"Active \xB7 end time unavailable":t===null?"Active":e===null||e<=0?`Ends ${pt(t)} \xB7 ending`:`Ends ${pt(t)} \xB7 ${W(e)} left`}function gt(e,t,r){let n={phase:"unknown",value:"--",sub:"Not configured",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(!e.anyConfigured)return n;let o=(e.scheduleStatus??"").trim().toUpperCase(),i=tn(e.endsAtText),s=(e.endsAtText??"").toLowerCase().includes("unavailable"),a=i?(i.getTime()-t)/6e4:null;if(e.active==="on"){let l=rn(a,i,s);return r==="dump"&&e.exportPowerW!==null&&e.exportPowerW!==void 0&&(l=`${l} \xB7 ${Math.round(e.exportPowerW)} W export`+(e.stopSoc!==null&&e.stopSoc!==void 0?` \xB7 stop ${Math.round(e.stopSoc)}%`:"")),{phase:"active",value:"Active",sub:l,tone:"accent",remainingMin:a,endsAt:i,endTimeUnavailable:s}}if(o==="STARTING")return{phase:"starting",value:"Starting",sub:"Scheduled start in progress",tone:"accent",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(o==="ARMED"){let l=typeof e.scheduleAttrs?.scheduled_start=="string"?e.scheduleAttrs.scheduled_start:null,d=ct(String(e.scheduleAttrs?.duration_minutes??""));return{phase:"armed",value:"Armed",sub:`Scheduled ${l?l.slice(0,5):"--:--"}`+(d!==null?` \xB7 ${W(d)}`:""),tone:"ok",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}if(o==="FAILED")return{phase:"failed",value:"Failed",sub:"Last scheduled run failed \xB7 see Energy Actions",tone:"alert",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(e.active==="off"){let l=o==="COMPLETED";return{phase:l?"completed":"standby",value:l?"Completed":r==="dump"?"Ready":"Standby",sub:l?"Last scheduled run completed":"No session running",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}return{phase:"unknown",value:"--",sub:"Lease state unavailable",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}function ar(e,t,r){let n={slot:null,startMin:null,endMin:null,minutesToChange:null,value:"--",sub:"Schedule unavailable",tone:"muted"};if(e.length!==6||e.some(s=>s===null))return n;if(r==="off")return{...n,sub:"Schedule invalid",tone:"warn"};let o=e,i=(Math.floor(t)%1440+1440)%1440;for(let s=0;s<6;s++){let a=(o[s]%1440+1440)%1440,l=(o[(s+1)%6]%1440+1440)%1440;if(a<l?i>=a&&i<l:i>=a||i<l){let c=(l-i+1440)%1440;return{slot:s+1,startMin:a,endMin:l,minutesToChange:c,value:`Slot ${s+1}`,sub:`${dt(a)}\u2013${dt(l)} \xB7 ${W(c)} left`,tone:"accent"}}}return{...n,sub:"No slot matches the current time",tone:"warn"}}function cr(e){return e.getHours()*60+e.getMinutes()}function De(e){return e.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/^ecco_/,"").replace(/_/g," ")}function yt(e,t,r){let n=[],o=[],i=[];for(let d of e){let c=(E(r,d)??"").trim().toUpperCase();c==="FAILED"?n.push(De(d)):c==="DEGRADED"?o.push(De(d)):c!=="HEALTHY"&&i.push(De(d))}let s=t.filter(d=>D(E(r,d))==="on").map(De);if(e.length+t.length===0)return{grade:"UNKNOWN",value:"--",sub:"No health entities configured",tone:"muted",failed:n,degraded:o,unknown:i,attention:s};let l=d=>d.slice(0,2).join(", ")+(d.length>2?` +${d.length-2}`:"");if(n.length>0||s.length>0){let d=[...n,...s];return{grade:"FAILED",value:"Attention",sub:l(d),tone:"alert",failed:n,degraded:o,unknown:i,attention:s}}return o.length>0?{grade:"DEGRADED",value:"Degraded",sub:l(o),tone:"warn",failed:n,degraded:o,unknown:i,attention:s}:i.length===e.length&&e.length>0?{grade:"UNKNOWN",value:"Unknown",sub:"Health entities unavailable",tone:"muted",failed:n,degraded:o,unknown:i,attention:s}:i.length>0?{grade:"HEALTHY",value:"Nominal",sub:`${i.length} unknown: ${l(i)}`,tone:"ok",failed:n,degraded:o,unknown:i,attention:s}:{grade:"HEALTHY",value:"Nominal",sub:`${e.length} subsystems healthy`,tone:"ok",failed:n,degraded:o,unknown:i,attention:s}}function ur(e,t,r,n,o){let i=null;for(let a of e){if(!a)continue;let l=t[a]?.last_updated;if(!l)continue;let d=Date.parse(l);Number.isFinite(d)&&(i===null||d>i)&&(i=d)}let s=i===null?null:Math.max(0,(n-i)/1e3);return r==="off"?{ageS:s,stale:!0,reason:"telemetry_offline",telemetry:r}:o>0&&s!==null&&s>o?{ageS:s,stale:!0,reason:"age",telemetry:r}:{ageS:s,stale:!1,reason:null,telemetry:r}}function dr(e,t){if(e){let n=typeof e.attributes?.elevation=="number"?e.attributes.elevation:null;if(e.state==="above_horizon")return n!==null&&n<8?"dusk":"day";if(e.state==="below_horizon")return n!==null&&n>-6?"dusk":"night"}let r=t.getHours();return r>=8&&r<18?"day":r>=6&&r<8||r>=18&&r<20?"dusk":"night"}var fe={sun:"M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6",pylon:"M9 22l3-19 3 19M6 22h12M7.2 9h9.6M8.4 14.5h7.2M4 9l3.2 3.5M20 9l-3.2 3.5M5 14.5l3.4 3M19 14.5l-3.4 3",home:"M3.5 11.5L12 4l8.5 7.5M6 10v10h12V10M10 20v-5h4v5",battery:"M7 5.5h10a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 17 21.5H7A1.5 1.5 0 0 1 5.5 20V7A1.5 1.5 0 0 1 7 5.5zM9.5 2.5h5M8.5 13.5h7v5h-7z",clock:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2",plug:"M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v3",target:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",leaf:"M5 19C6 11 11 5 20 4c0 9-5 15-13 15M5 19l7-7",swap:"M4 8h13l-3-3M20 16H7l3 3",heart:"M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",chevron:"M9 6l6 6-6 6",forecast:"M12 6.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v1.6M4.9 4.9l1.2 1.2M19.1 4.9l-1.2 1.2M2 10.5h1.6M20.4 10.5H22M3 19h18M6 22h12",inverter:"M4 5h16v14H4zM8 9h8M8 13h5M16 15.5h.01",alert:"M12 3l10 18H2L12 3zM12 10v5M12 18v.5",moon:"M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"};function p(e,t,r=0){return{x:205+(e-t)*11.258,y:262+(e+t)*6.5-r*13}}function M(e){return e.map(t=>`${t.x.toFixed(1)},${t.y.toFixed(1)}`).join(" ")}function Ce(e,t,r,n,o,i){return{top:M([p(e,t,i),p(r,t,i),p(r,n,i),p(e,n,i)]),left:M([p(e,n,o),p(r,n,o),p(r,n,i),p(e,n,i)]),right:M([p(r,t,o),p(r,n,o),p(r,n,i),p(r,t,i)])}}function B(e,t,r,n,o){return M([p(t,e,n),p(r,e,n),p(r,e,o),p(t,e,o)])}function mt(e,t,r,n,o){return M([p(e,t,n),p(e,r,n),p(e,r,o),p(e,t,o)])}function ye(e,t,r,n,o,i){return p(e,r+(o-r)*t,n+(i-n)*t)}function je(e){if(e.length<4)return"";let t=`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)}`;for(let r=1;r+2<e.length;r+=3){let n=e[r],o=e[r+1],i=e[r+2];t+=` C ${n.x.toFixed(1)} ${n.y.toFixed(1)}, ${o.x.toFixed(1)} ${o.y.toFixed(1)}, ${i.x.toFixed(1)} ${i.y.toFixed(1)}`}return t}var Q={x0:-1,y0:-3,x1:7,y1:3,z:4.2,ridgeZ:6.6,ridgeY:0},pr={x0:7,y0:-1,x1:11,y1:3,z:2.5},ge={x0:-6.2,y0:4.2,x1:-4.6,y1:5.4,z:2.4},ie={x0:5.3,x1:6.3,z0:1.25,z1:2.45,y:Q.y1},V=p(10.6,-4.8),bt=(()=>{let e=p((ie.x0+ie.x1)/2,ie.y,(ie.z0+ie.z1)/2);return{x:e.x+1,y:e.y+2}})(),J={solar:{x:8,y:10,w:150,h:58,port:{x:58,y:68}},grid:{x:246,y:22,w:146,h:58,port:{x:330,y:80}},home:{x:214,y:176,w:140,h:54,port:{x:236,y:230}},battery:{x:8,y:388,w:184,h:70,port:{x:108,y:388}}};function he(e,t=.5){if(e.length<2)return"";if(e.length===2)return`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)} L ${e[1].x.toFixed(1)} ${e[1].y.toFixed(1)}`;let r=`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)}`;for(let n=0;n<e.length-1;n++){let o=e[Math.max(0,n-1)],i=e[n],s=e[n+1],a=e[Math.min(e.length-1,n+2)],l={x:i.x+(s.x-o.x)/6*t*2,y:i.y+(s.y-o.y)/6*t*2},d={x:s.x-(a.x-i.x)/6*t*2,y:s.y-(a.y-i.y)/6*t*2};r+=` C ${l.x.toFixed(1)} ${l.y.toFixed(1)}, ${d.x.toFixed(1)} ${d.y.toFixed(1)}, ${s.x.toFixed(1)} ${s.y.toFixed(1)}`}return r}var nn={main_pv:{x:610,y:335,label:"Main PV array"},garage_pv:{x:1140,y:500,label:"Garage PV array"},battery_cabinet:{x:150,y:512,label:"Battery cabinet"},inverter:{x:1e3,y:622,label:"Wall inverter"},ev_charger:{x:1048,y:655,label:"EV charger"},pylon:{x:1297,y:290,label:"Grid pylon"},house:{x:752,y:600,label:"House connection"}};function xt(e){let t=nn,r=150*e,n=58*e,o=178*e,i=72*e,s=140*e,a=54*e,l={solar:{x:35,y:95,w:r,h:n,port:{x:35+r*.82,y:95+n}},grid:{x:1410-r,y:95,w:r,h:n,port:{x:1410-r*.3,y:95+n}},battery:{x:35,y:718,w:o,h:i,port:{x:35+Math.min(o*.36,117),y:718}},home:{x:690,y:884,w:s,h:a,port:{x:690+s*.42,y:884}}};return{width:1448,height:1086,scale:e,pills:l,inverter:t.inverter,anchors:t,paths:()=>({solarCard:he([l.solar.port,{x:400,y:262},{x:500,y:288},t.main_pv]),solarMain:he([t.main_pv,{x:680,y:400},{x:735,y:442},{x:830,y:480},{x:905,y:512},{x:962,y:560},{x:985,y:600},t.inverter]),solarGarage:he([t.garage_pv,{x:1070,y:545},{x:1040,y:585},{x:1018,y:612},t.inverter]),battery:he([l.battery.port,{x:150,y:640},{x:148,y:560},t.battery_cabinet,{x:250,y:530},{x:335,y:548},{x:470,y:612},{x:600,y:662},{x:740,y:700},{x:880,y:690},{x:960,y:655},t.inverter]),grid:he([l.grid.port,{x:1300,y:250},t.pylon,{x:1300,y:370},{x:1290,y:425},{x:1180,y:418},{x:1040,y:428},{x:975,y:468},{x:968,y:540},{x:980,y:596},t.inverter]),home:he([t.inverter,{x:950,y:636},{x:880,y:622},{x:810,y:610},t.house,{x:748,y:690},{x:770,y:790},l.home.port])})}}function fr(e){return e<520?3.2:e<760?2.8:e<1100?2.3:2}var xo=xt(2);function hr(){let e=bt,t=ye(.2,.08,Q.y1,Q.z,Q.ridgeY,Q.ridgeZ),r=je([J.solar.port,{x:58,y:120},{x:150,y:150},t,{x:t.x+16,y:t.y+20},{x:e.x-24,y:e.y-26},e]),n=p(ge.x1,(ge.y0+ge.y1)/2,ge.z*.72),o=je([{x:n.x+2,y:n.y},{x:n.x+40,y:n.y-2},{x:e.x-60,y:e.y+28},{x:e.x-24,y:e.y+24},{x:e.x-10,y:e.y+22},{x:e.x-4,y:e.y+12},e]),i={x:V.x-4,y:V.y-118},s=je([J.grid.port,{x:330,y:112},{x:i.x-30,y:i.y+10},{x:i.x-22,y:i.y+44},{x:i.x-14,y:V.y-6},{x:V.x-30,y:V.y+30},{x:300,y:V.y+40},{x:272,y:V.y+36},{x:e.x+10,y:e.y+24},e]),a=je([e,{x:e.x+10,y:e.y-24},{x:e.x-12,y:e.y-48},J.home.port]);return{solar:r,battery:o,grid:s,home:a}}var on=15,se={solar:"#f7c948",battery:"#35e08a",grid:"#3ea6ff",home:"#22d3ee"};function yr(e,t,r,n,o){let i=n/24;return x`<g transform="translate(${t} ${r}) scale(${i})" fill="none" stroke=${o} stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d=${fe[e]}></path></g>`}function sn(){let e=[p(-8,-6),p(10,-6),p(10,10),p(-8,10)],t=12,r=[e[3],e[2],{x:e[2].x,y:e[2].y+t},{x:e[3].x,y:e[3].y+t}],n=[e[2],e[1],{x:e[1].x,y:e[1].y+t},{x:e[2].x,y:e[2].y+t}],o=[p(8.2,3.05),p(10.6,3.05),p(10.6,10),p(8.2,10)],i=[p(2.2,3.05),p(3.2,3.05),p(3.2,5.6),p(-4.2,5.6),p(-4.2,4.6),p(2.2,4.6)];return x`
    <g class="ground">
      <polygon points=${M(r)} class="ground-side"></polygon>
      <polygon points=${M(n)} class="ground-side ground-side-r"></polygon>
      <polygon points=${M(e)} class="ground-top"></polygon>
      <polygon points=${M(e)} fill="url(#ef3d-ground-sheen)"></polygon>
      <polygon points=${M(o)} class="drive"></polygon>
      <polygon points=${M(i)} class="drive path"></polygon>
      ${ln()}
    </g>`}function ln(){let e=[];for(let t=0;t<6;t++){let r=-5+t*2.6;e.push(x`<polygon points=${M([p(-7.6,r),p(-1.6,r),p(-1.6,r+1.3),p(-7.6,r+1.3)])} class="lawn-stripe"></polygon>`)}return e}function Ge(e,t,r,n=""){let o=p(e,t);return x`
    <g class="tree ${n}">
      <ellipse cx=${o.x} cy=${o.y+2} rx=${r*.9} ry=${r*.38} class="tree-shadow"></ellipse>
      <rect x=${o.x-1.4} y=${o.y-r*1.1} width="2.8" height=${r*1.1} class="trunk"></rect>
      <circle cx=${o.x-r*.35} cy=${o.y-r*1.15} r=${r*.78} class="canopy c2"></circle>
      <circle cx=${o.x+r*.4} cy=${o.y-r*1.25} r=${r*.82} class="canopy c3"></circle>
      <circle cx=${o.x} cy=${o.y-r*1.7} r=${r*.86} class="canopy c1"></circle>
    </g>`}function me(e,t,r){let n=p(e,t);return x`<g class="shrub"><ellipse cx=${n.x} cy=${n.y} rx=${r} ry=${r*.62} class="canopy c2"></ellipse><ellipse cx=${n.x-r*.4} cy=${n.y-r*.25} rx=${r*.7} ry=${r*.45} class="canopy c1"></ellipse></g>`}function wt(e,t){let r=p(e,t);return x`<g class="lamp"><line x1=${r.x} y1=${r.y} x2=${r.x} y2=${r.y-9} class="lamp-post"></line><circle cx=${r.x} cy=${r.y-10} r="2.2" class="lamp-light"></circle><circle cx=${r.x} cy=${r.y-10} r="6" class="lamp-halo"></circle></g>`}function an(){let e=Q,t=Ce(e.x0,e.y0,e.x1,e.y1,0,e.z),r=[p(e.x0-.5,e.y1+.5,e.z-.25),p(e.x1+.5,e.y1+.5,e.z-.25),p(e.x1+.5,e.ridgeY,e.ridgeZ),p(e.x0-.5,e.ridgeY,e.ridgeZ)],n=[p(e.x0-.5,e.y0-.5,e.z-.25),p(e.x1+.5,e.y0-.5,e.z-.25),p(e.x1+.5,e.ridgeY,e.ridgeZ),p(e.x0-.5,e.ridgeY,e.ridgeZ)],o=[p(e.x1,e.y0,e.z),p(e.x1,e.y1,e.z),p(e.x1,e.ridgeY,e.ridgeZ)],i=[p(e.x1+.5,e.y1+.5,e.z-.25),p(e.x1+.5,e.y1+.5,e.z-.55),p(e.x1+.5,e.ridgeY,e.ridgeZ-.3),p(e.x1+.5,e.ridgeY,e.ridgeZ)],s=pr,a=Ce(s.x0,s.y0,s.x1,s.y1,0,s.z),l=Ce(s.x0-.15,s.y0-.15,s.x1+.15,s.y1+.15,s.z,s.z+.18);return x`
    <g class="house">
      <!-- soft contact shadow -->
      <polygon points=${M([p(e.x0-.6,e.y0-.2),p(s.x1+.9,s.y0-.2),p(s.x1+.9,s.y1+.9),p(e.x0-.6,e.y1+.9)])} class="contact-shadow"></polygon>
      <!-- garage (behind the house's right face order-wise it sits in front, draw after walls) -->
      <polygon points=${t.right} class="wall wall-r"></polygon>
      <polygon points=${M(o)} class="wall wall-r gable"></polygon>
      <polygon points=${t.left} class="wall wall-l"></polygon>
      <!-- windows and door on the front-left wall -->
      <polygon points=${B(e.y1+.02,.2,1.6,1.5,3.2)} class="window"></polygon>
      <polygon points=${B(e.y1+.02,2,3.4,1.5,3.2)} class="window"></polygon>
      <polygon points=${B(e.y1+.02,.2,1.6,.4,1.1)} class="window small"></polygon>
      <polygon points=${B(e.y1+.02,2.3,3.1,0,1.15)} class="door"></polygon>
      <polygon points=${B(e.y1+.02,3.9,4.8,1.5,3.2)} class="window"></polygon>
      <!-- windows on the right wall -->
      <polygon points=${mt(e.x1+.02,-2.4,-1.2,1.5,3.2)} class="window"></polygon>
      <polygon points=${mt(e.x1+.02,-2.4,-1.2,.3,1.1)} class="window small"></polygon>
      <!-- garage -->
      <polygon points=${a.right} class="wall wall-r"></polygon>
      <polygon points=${a.left} class="wall wall-l"></polygon>
      <polygon points=${B(s.y1+.02,7.6,10.4,0,1.9)} class="garage-door"></polygon>
      ${[.45,.9,1.35].map(d=>x`<polyline points=${M([p(7.6,s.y1+.03,d),p(10.4,s.y1+.03,d)])} class="garage-line"></polyline>`)}
      <polygon points=${a.top} class="roof-flat"></polygon>
      <polygon points=${l.left} class="roof-lip"></polygon>
      <polygon points=${l.right} class="roof-lip"></polygon>
      <polygon points=${l.top} class="roof-flat-top"></polygon>
      <!-- roof -->
      <polygon points=${M(n)} class="roof roof-back"></polygon>
      <polygon points=${M(r)} class="roof roof-front"></polygon>
      <polygon points=${M(i)} class="fascia"></polygon>
      <polyline points=${M([p(e.x0-.5,e.ridgeY,e.ridgeZ),p(e.x1+.5,e.ridgeY,e.ridgeZ)])} class="ridge"></polyline>
      ${cn()}
      ${un()}
    </g>`}function cn(){let e=Q,t=[],r=5,n=2,o=e.x0+.25,i=e.x1-.75,s=.14,a=(i-o-s*(r-1))/r,l=.16,d=.9,c=.05,u=(d-l-c*(n-1))/n;for(let f=0;f<n;f++)for(let w=0;w<r;w++){let y=o+w*(a+s),h=y+a,T=l+f*(u+c),k=T+u,m=[ye(y,T,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ye(h,T,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ye(h,k,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ye(y,k,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ)].map($=>({x:$.x,y:$.y-1.2}));t.push(x`<polygon points=${M(m)} class="pv"></polygon>`),t.push(x`<polygon points=${M(m)} fill="url(#ef3d-pv-glare)" class="pv-glare"></polygon>`);let S=($,v,C)=>({x:$.x+(v.x-$.x)*C,y:$.y+(v.y-$.y)*C});for(let $ of[1/3,2/3])t.push(x`<line x1=${S(m[0],m[3],$).x} y1=${S(m[0],m[3],$).y} x2=${S(m[1],m[2],$).x} y2=${S(m[1],m[2],$).y} class="pv-line"></line>`),t.push(x`<line x1=${S(m[0],m[1],$).x} y1=${S(m[0],m[1],$).y} x2=${S(m[3],m[2],$).x} y2=${S(m[3],m[2],$).y} class="pv-line"></line>`)}return t}function un(){let e=ie,t=B(e.y+.03,e.x0,e.x1,e.z0,e.z1),r=p(e.x1-.18,e.y+.05,e.z1-.22),n=o=>M([p(e.x0+.18,e.y+.05,o),p(e.x1-.18,e.y+.05,o)]);return x`
    <g class="inverter">
      <polygon points=${t} class="inverter-face"></polygon>
      <polyline points=${n(e.z0+.3)} class="inverter-vent"></polyline>
      <polyline points=${n(e.z0+.5)} class="inverter-vent"></polyline>
      <circle cx=${r.x} cy=${r.y} r="1.6" class="inverter-led"></circle>
      <circle cx=${r.x} cy=${r.y} r="4" class="inverter-led-halo"></circle>
    </g>`}function dn(e){let t=ge,r=Ce(t.x0,t.y0,t.x1,t.y1,0,t.z),n=t.x0+.18,o=.16,i=.3,s=t.z-.3,a=e===null?i:i+Math.max(0,Math.min(100,e))/100*(s-i),l=p((t.x0+t.x1)/2+.15,t.y1+.04,t.z*.56);return x`
    <g class="battery-cabinet">
      <ellipse cx=${p((t.x0+t.x1)/2,(t.y0+t.y1)/2).x} cy=${p((t.x0+t.x1)/2,(t.y0+t.y1)/2).y+3} rx="20" ry="7" class="contact-shadow soft"></ellipse>
      <polygon points=${r.right} class="cab cab-r"></polygon>
      <polygon points=${r.left} class="cab cab-l"></polygon>
      <polygon points=${r.top} class="cab cab-t"></polygon>
      <polygon points=${B(t.y1+.03,n,n+o,i,s)} class="cab-strip-bg"></polygon>
      ${e===null?g:x`<polygon points=${B(t.y1+.04,n,n+o,i,a)} class="cab-strip"></polygon>`}
      <text x="0" y="0" class="cab-label" transform=${`matrix(0.866 0.5 0 1 ${l.x.toFixed(1)} ${l.y.toFixed(1)})`}>ECCO</text>
    </g>`}function pn(e,t){let r=V,n=118,o={x:r.x-4,y:r.y-n},i=18,s=(c,u)=>x`<line x1=${r.x-4-u} y1=${c} x2=${r.x-4+u} y2=${c} class="pylon-line"></line>`,a=x`
    <line x1=${r.x-i} y1=${r.y} x2=${o.x-2} y2=${o.y} class="pylon-line"></line>
    <line x1=${r.x+i-8} y1=${r.y} x2=${o.x+2} y2=${o.y} class="pylon-line"></line>
    <line x1=${r.x-i+5} y1=${r.y-2} x2=${o.x} y2=${o.y+4} class="pylon-line thin"></line>
    <line x1=${r.x+i-12} y1=${r.y-2} x2=${o.x} y2=${o.y+4} class="pylon-line thin"></line>`,l=[];for(let c=1;c<7;c++){let u=r.y-n/7*c,f=(i-8)*(1-c/8)+3;l.push(x`<line x1=${r.x-4-f} y1=${u} x2=${r.x-4+f} y2=${u-6} class="pylon-line thin"></line>`),l.push(x`<line x1=${r.x-4+f} y1=${u} x2=${r.x-4-f} y2=${u-6} class="pylon-line thin"></line>`)}let d=[o.y+24,o.y+44].map(c=>x`<path d=${`M ${(r.x-4-26).toFixed(1)} ${c} Q ${(r.x+30).toFixed(1)} ${c+18} ${410} ${c-12}`} class="wire"></path>`);return x`
    <g class=${`pylon ${e?"live":""} ${t?"unknown":""}`}>
      ${a}${l}
      ${s(o.y+22,26)}${s(o.y+42,20)}
      ${d}
      <circle cx=${o.x} cy=${o.y-2} r="3" class="pylon-tip"></circle>
    </g>`}function Re(e,t,r,n,o,i=1,s=0){let{edge:a,motion:l}=n,d=se[e],c=i>1,u=`flow flow-${e} route-${t} ${c?"fine":""} ${a.unknown?"unknown":""} ${a.idle?"idle":""} ${l.moving&&o?"moving":""} ${a.reversed?"reversed":""}`,f=`ef3d-path-${t}`,w=c&&s>0?Math.max(1,Math.round(s/520)):1,y=l.ballCount*w,h=l.intensity,T=[];if(l.moving&&o){let S=c?(1.7+h*1)*i:l.ballRadiusPx;for(let $=0;$<y;$++)T.push(x`
        <g class="pulse" data-path=${f} data-duration=${(l.ballDurationS*(c?1.6:1)).toFixed(3)} data-phase=${($/y).toFixed(3)} data-reversed=${a.reversed?"1":"0"} style=${`--pulse-colour:${d}`}>
          <circle r=${(S*(c?2.6:1.9)).toFixed(2)} class="pulse-halo"></circle>
          <circle r=${S.toFixed(2)} class="pulse-glow"></circle>
          <circle r=${(S*.45).toFixed(2)} class="pulse-core"></circle>
        </g>`)}let k=[];if(l.moving&&!o)for(let S of[.3,.55,.8])k.push(x`<g class="chevron" data-path=${f} data-phase=${S} data-reversed=${a.reversed?"1":"0"} style=${`--pulse-colour:${d}`}><path d="M -4 -4 L 2 0 L -4 4" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" transform=${`scale(${i})`}></path></g>`);if(c){let S=(1.15+h*.6)*i,$=(4.2+h*3)*i,v=l.moving?.22+h*.3:0,C=l.moving?.5+h*.4:0;return x`
      <g class=${u} style=${`--flow-colour:${d}`}>
        <path d=${r} class="fine-base" style=${`stroke-width:${S.toFixed(2)}`}></path>
        <path d=${r} class="fine-glow" style=${`stroke-width:${$.toFixed(2)}; opacity:${v.toFixed(2)}`}></path>
        <path id=${f} d=${r} class="fine-highlight" style=${`stroke-width:${(.7*i).toFixed(2)}; opacity:${C.toFixed(2)}`}></path>
        ${T}${k}
      </g>`}let F=l.moving?`stroke-dasharray:${l.dashLen.toFixed(1)} ${l.gapLen.toFixed(1)}; animation-duration:${l.dashDurationS.toFixed(2)}s; stroke-width:${l.packetWidthPx.toFixed(2)}; opacity:${l.packetOpacity.toFixed(2)}; --dash-travel:${(-2*on).toFixed(1)}`:"",m=l.moving?`stroke-width:${(l.packetWidthPx*2.6).toFixed(1)}; opacity:${(.18+l.intensity*.3).toFixed(2)}`:"";return x`
    <g class=${u} style=${`--flow-colour:${d}`}>
      <path d=${r} class="flow-base" style=${`stroke-width:${l.baseWidthPx.toFixed(2)}`}></path>
      <path d=${r} class="flow-dots"></path>
      <path d=${r} class="flow-glow" style=${m}></path>
      <path id=${f} d=${r} class="flow-packets" style=${F}></path>
      ${T}${k}
    </g>`}function Te(e,t,r,n){return x`<g class=${`node-light ${r?"active":""}`} style=${`--flow-colour:${t}`}><circle cx=${e.x} cy=${e.y} r=${(5*n).toFixed(1)} class="node-light-halo"></circle><circle cx=${e.x} cy=${e.y} r=${(1.6*n).toFixed(1)} class="node-light-core"></circle></g>`}function fn(e){let t=e.match(/-?\d+(\.\d+)?/g)?.map(Number)??[],r=0;for(let n=2;n+1<t.length;n+=2)r+=Math.hypot(t[n]-t[n-2],t[n+1]-t[n-1]);return r/1.9}function ee(e,t,r,n,o,i=1){let s=se[e],a=14*i,l=e==="battery",d=19*i,c=2*Math.PI*d,u=r.soc??null,f=u===null?0:Math.max(0,Math.min(100,u))/100*c,w=t.x+52*i,y=t.x+t.w-30*i,h=t.y+t.h/2,T=o.edge.unknown?"unknown":o.edge.idle?"idle":"active";return x`
    <g class=${`pill pill-${e} tone-${r.tone} ${T} ${r.clickable?"clickable":""}`}
       style=${`--pill-colour:${s}`}
       role=${r.clickable?"button":"img"}
       tabindex=${r.clickable?0:-1}
       aria-label=${`${r.label}: ${r.value}${r.sub?", "+r.sub:""}`}
       @click=${()=>n(e)}
       @keydown=${k=>{(k.key==="Enter"||k.key===" ")&&(k.preventDefault(),n(e))}}>
      <rect x=${t.x} y=${t.y} width=${t.w} height=${t.h} rx=${a} class="pill-bg"></rect>
      <rect x=${t.x} y=${t.y} width=${t.w} height=${t.h} rx=${a} class="pill-border"></rect>
      <circle cx=${t.x+27*i} cy=${t.y+t.h/2} r=${15*i} class="pill-icon-bg"></circle>
      ${yr(r.icon,t.x+16*i,t.y+t.h/2-11*i,22*i,s)}
      <text x=${w} y=${t.y+19*i} class="pill-label">${r.label}</text>
      <text x=${w} y=${t.y+(r.sub?39:42)*i} class="pill-value">${r.value}</text>
      ${r.sub?x`<text x=${w} y=${t.y+(r.extra?52:t.h/i-8)*i} class="pill-sub">${r.sub}</text>`:g}
      ${r.extra?x`<text x=${w} y=${t.y+t.h-9*i} class="pill-extra">${r.extra}</text>`:g}
      ${l?x`
            <circle cx=${y} cy=${h} r=${d} class="ring-track"></circle>
            ${u===null?g:x`<circle cx=${y} cy=${h} r=${d} class="ring-fill" stroke-dasharray=${`${f.toFixed(1)} ${c.toFixed(1)}`} transform=${`rotate(-90 ${y} ${h})`}></circle>`}
            <text x=${y} y=${h+4*i} class="ring-value">${u===null?"--":`${Math.round(u)}%`}</text>
            <text x=${y} y=${h+14*i} class="ring-caption">SOC</text>`:r.clickable?yr("chevron",t.x+t.w-24*i,t.y+t.h/2-8*i,16*i,"rgba(255,255,255,0.45)"):g}
    </g>`}function mr(e){if(e.artwork)return hn(e,e.artwork);let t=hr(),r=e.flows.grid.motion.moving,n=bt;return x`
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
        ${[[40,92],[122,46],[180,112],[236,70],[352,150],[392,60],[20,160],[288,20]].map(([o,i])=>x`<circle cx=${o} cy=${i} r="1.1" class="star"></circle>`)}
      </g>
      ${sn()}
      ${Ge(-6.5,-4.6,13,"back")}
      ${Ge(-2.5,-5.2,10,"back")}
      ${Ge(9.5,-5.6,11,"back")}
      ${me(-7.2,1.2,8)}
      ${me(-6.6,-1,7)}
      ${me(5,5.2,7)}
      ${me(6.4,6.4,6)}
      ${me(-1.5,7.2,8)}
      ${wt(-4.8,6.6)}
      ${wt(3.9,5.2)}
      ${wt(7.4,8.6)}
      ${pn(r,e.flows.grid.edge.unknown)}
      ${an()}
      ${dn(e.pills.battery.soc??null)}
      ${Ge(-7.6,8.6,12,"front")}
      ${me(1.2,8.8,7)}
      <g class="flows">
        ${Re("grid","grid",t.grid,e.flows.grid,e.animate)}
        ${Re("solar","solar",t.solar,e.flows.solar,e.animate)}
        ${Re("battery","battery",t.battery,e.flows.battery,e.animate)}
        ${Re("home","home",t.home,e.flows.home,e.animate)}
        <circle cx=${n.x} cy=${n.y} r="4.2" class=${`junction led-${e.inverterLed}`}></circle>
        <circle cx=${n.x} cy=${n.y} r="9" class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${ee("solar",J.solar,e.pills.solar,e.onPill,e.flows.solar)}
      ${ee("grid",J.grid,e.pills.grid,e.onPill,e.flows.grid)}
      ${ee("home",J.home,e.pills.home,e.onPill,e.flows.home)}
      ${ee("battery",J.battery,e.pills.battery,e.onPill,e.flows.battery)}
    </svg>`}function hn(e,t){let r=t.layout,n=r.paths(),o=r.scale,i=r.anchors,s=e.solarSplit??{card:e.flows.solar,main:e.flows.solar,garage:null},a=(c,u,f)=>Re(c,u,n[u],f,e.animate,o,fn(n[u])),l=c=>!!c&&c.motion.moving,d=t.debug?x`<g class="debug">
        ${Object.values(i).map(c=>x`<circle cx=${c.x} cy=${c.y} r=${4*o} class="debug-dot"></circle><circle cx=${c.x} cy=${c.y} r=${9*o} class="debug-ring"></circle><text x=${c.x+11*o} y=${c.y-6*o} class="debug-label">${c.label} ${c.x},${c.y}</text>`)}
        ${Object.entries(r.pills).map(([c,u])=>x`<rect x=${u.x} y=${u.y} width=${u.w} height=${u.h} class="debug-zone"></rect><circle cx=${u.port.x} cy=${u.port.y} r=${3.5*o} class="debug-port"></circle><text x=${u.port.x+8*o} y=${u.port.y+4*o} class="debug-label">${c} port</text>`)}
      </g>`:g;return x`
    <svg class=${`scene artwork ${e.daylight} ${e.stale?"stale":""} ${e.animate?"":"still"}`} viewBox=${`0 0 ${r.width} ${r.height}`} preserveAspectRatio="xMidYMid meet" style=${`--k:${o}`} aria-label="Energy flow scene">
      <defs>
        <filter id="ef3d-blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation=${(1.6*o).toFixed(1)}></feGaussianBlur></filter>
        <filter id="ef3d-blur-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=${(3.5*o).toFixed(1)}></feGaussianBlur></filter>
      </defs>
      ${t.layers.map(c=>x`<image href=${c.url} x="0" y="0" width=${r.width} height=${r.height} preserveAspectRatio="xMidYMid meet" class=${`plate ${c.entering?"entering":""}`} data-scene=${c.key} @error=${()=>t.onError(c.url)} @load=${()=>t.onLoad(c.url)}></image>`)}
      <g class="flows">
        ${a("grid","grid",e.flows.grid)}
        ${a("battery","battery",e.flows.battery)}
        ${a("solar","solarCard",s.card)}
        ${a("solar","solarMain",s.main)}
        ${s.garage?a("solar","solarGarage",s.garage):g}
        ${a("home","home",e.flows.home)}
        ${Te(i.main_pv,se.solar,l(s.main),o)}
        ${s.garage?Te(i.garage_pv,se.solar,l(s.garage),o):g}
        ${Te(i.battery_cabinet,se.battery,l(e.flows.battery),o)}
        ${Te(i.pylon,se.grid,l(e.flows.grid),o)}
        ${Te(i.house,se.home,l(e.flows.home),o)}
        <circle cx=${r.inverter.x} cy=${r.inverter.y} r=${(2.6*o).toFixed(1)} class=${`junction led-${e.inverterLed}`}></circle>
        <circle cx=${r.inverter.x} cy=${r.inverter.y} r=${(7*o).toFixed(1)} class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${d}
      ${ee("solar",r.pills.solar,e.pills.solar,e.onPill,e.flows.solar,o)}
      ${ee("grid",r.pills.grid,e.pills.grid,e.onPill,e.flows.grid,o)}
      ${ee("home",r.pills.home,e.pills.home,e.onPill,e.flows.home,o)}
      ${ee("battery",r.pills.battery,e.pills.battery,e.onPill,e.flows.battery,o)}
    </svg>`}var br={bright_summer_day:"00_bright_summer_day.png",soft_clear_day:"01_soft_clear_day.png",misty_morning:"02_misty_morning.png",golden_hour:"03_golden_hour.png",clear_night:"04_clear_night.png",rainy_day:"05_rainy_day.png",storm_night:"06_storm_night.png",winter_clear_day:"07_winter_clear_day.png",christmas_day:"08_christmas_day.png",christmas_night:"09_christmas_night.png"},xr=Object.keys(br);function gn(e,t){return e===12||e===1&&t<=3}function yn(e){return e.sunUp!==null?!e.sunUp:e.weather==="clear-night"?!0:e.hour<7||e.hour>=19}function mn(e){return e.elevation===null||e.elevation<-6||e.elevation>15?!1:e.rising!==null?!e.rising:e.hour>=15}function wr(e){let t=yn(e),r=(e.weather??"").toLowerCase();return gn(e.month,e.day)?t?"christmas_night":"christmas_day":!t&&(r==="snowy"||r==="snowy-rainy")?"winter_clear_day":t&&(r==="lightning"||r==="lightning-rainy"||r==="exceptional")?"storm_night":!t&&(r==="rainy"||r==="pouring")?"rainy_day":!t&&r==="fog"?"misty_morning":mn(e)?"golden_hour":r==="clear-night"||t&&["sunny","partlycloudy","cloudy","windy",""].includes(r)||t?"clear_night":r==="partlycloudy"?"soft_clear_day":r==="sunny"||r==="windy"||r==="clear"?"bright_summer_day":"soft_clear_day"}function $r(e,t,r){let n=r?.[t]??br[t];return/^(\/|\.|[a-z]+:)/i.test(n)&&r?.[t]?n:(e.endsWith("/")?e:e+"/")+n}var bn=15e3,U=class extends K{constructor(){super(...arguments);this._detailsOpen=!1;this._nowMs=Date.now();this._layers=[];this._failedPlates=new Set;this._fadeTimer=0;this._widthPx=0;this._raf=0;this._timer=0;this._lengthCache=new WeakMap;this._onMotionPref=()=>{this.requestUpdate()}}static getStubConfig(){return{type:"custom:ecco-flow-3d-card",title:"Energy Flow",subtitle:"Live power overview",nodes:{solar:[{label:"Array 1",power:"sensor.pv1_power"}],inverter:{power:"sensor.inverter_power"},home:{power:"sensor.house_power"},battery:{power:"sensor.battery_power",soc:"sensor.battery_soc",power_sign:"charge_positive"},grid:{power:"sensor.grid_power",power_sign:"import_positive"}}}}setConfig(r){Gt(r),this._config=r,this._failedPlates=new Set}_resolveScene(r,n){let o=this._config?.scene;if(!o?.pack)return null;let i=this._config?.ecco??{},s=i.sun?r[i.sun]:void 0,a=typeof s?.attributes?.elevation=="number"?s.attributes.elevation:null,l=typeof s?.attributes?.rising=="boolean"?s.attributes.rising:null,c=(o.force&&xr.includes(o.force)?o.force:null)??wr({month:n.getMonth()+1,day:n.getDate(),sunUp:s?s.state==="above_horizon"?!0:s.state==="below_horizon"?!1:null:null,elevation:a,rising:l,weather:i.weather?E(r,i.weather):void 0,hour:n.getHours()});return{key:c,url:$r(o.pack,c,o.scenes)}}willUpdate(){let r=this._resolveScene(this.hass?.states??{},new Date(this._nowMs));if(!r){this._layers.length&&(this._layers=[]);return}let n=this._layers[this._layers.length-1];n&&n.url===r.url||(this._layers=this._layers.length===0?[{url:r.url,key:r.key,entering:!1}]:[...this._layers.slice(-1),{url:r.url,key:r.key,entering:!0}])}_plateLoaded(r){let n=this._layers[this._layers.length-1];!n||n.url!==r||this._layers.length<2||(window.clearTimeout(this._fadeTimer),this._fadeTimer=window.setTimeout(()=>{this._layers=this._layers.filter(o=>o.url===r).map(o=>({...o,entering:!1}))},(this._config?.scene?.crossfade_ms??900)+50))}_plateFailed(r){this._failedPlates.add(r),this.requestUpdate()}getCardSize(){return 8}connectedCallback(){super.connectedCallback(),window.matchMedia&&(this._reducedMotionQuery=window.matchMedia("(prefers-reduced-motion: reduce)"),this._reducedMotionQuery.addEventListener?.("change",this._onMotionPref)),this._timer=window.setInterval(()=>{this._nowMs=Date.now()},bn),typeof ResizeObserver<"u"&&(this._resize=new ResizeObserver(r=>{let n=Math.round(r[0]?.contentRect.width??0);n&&Math.abs(n-this._widthPx)>8&&(this._widthPx=n)}),this._resize.observe(this))}disconnectedCallback(){super.disconnectedCallback(),this._reducedMotionQuery?.removeEventListener?.("change",this._onMotionPref),window.clearInterval(this._timer),window.clearTimeout(this._fadeTimer),this._resize?.disconnect(),cancelAnimationFrame(this._raf),this._raf=0}firstUpdated(){this._animate()}updated(r){this._placeChevrons()}get _reducedMotion(){return!!this._reducedMotionQuery?.matches}_moreInfo(r){r&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:r},bubbles:!0,composed:!0}))}render(){let r=this._config;if(!r)return O``;let n=this.hass?.states??{},o=r.nodes??{},i=r.ecco??{},s=new Date(this._nowMs),a=Bt(o.solar),l=a.map(N=>_(n,N.power)),d=qt(_(n,o.solar_total),l),c=_(n,o.inverter?.power),u=_(n,o.battery?.power),f=u===null?null:Wt(u,o.battery?.power_sign),w=_(n,o.grid?.power),y=w===null?null:Vt(w,o.grid?.power_sign),h=Yt(_(n,o.home?.power),c,y),T=_(n,o.battery?.soc),k=Kt({solarW:d,batteryW:f,gridW:y,homeW:h}),F=Object.fromEntries(k.map(N=>[N.id,N])),m=Xt(d,l[0]??null,l[1]??null,a.length),S=D(E(n,i.telemetry_online)),$=ur([...a.map(N=>N.power),o.solar_total,o.inverter?.power,o.battery?.power,o.grid?.power,o.home?.power],n,S,this._nowMs,r.features?.stale_after_s??jt),v=$.stale,C=(r.features?.animate_flow??!0)&&!this._reducedMotion,H=o.battery?.time_to_reserve,b=Be(H,Me(H,_(n,H),L(n,H)?.unit_of_measurement),L(n,H)),R=b&&(b.status==="discharging"||b.status==="at_reserve")?ft(b):"",P=Qt(f),z=Jt(y),be=D(E(n,o.grid?.connected)),le={solar:{label:"Solar Generation",value:de(d),sub:a.length>1?a.map((N,Ve)=>de(l[Ve]??null)).join(" + "):"",tone:d===null?"muted":"ok",icon:"sun",clickable:!!(o.solar_total??a[0]?.power)},grid:{label:"Grid",value:de(y===null?null:Math.abs(y)),sub:be==="off"?"Disconnected":z==="importing"?"Importing":z==="exporting"?"Exporting":z==="idle"?"Idle":"Unknown",tone:be==="off"?"alert":z==="unknown"?"muted":"ok",icon:"pylon",clickable:!!o.grid?.power},home:{label:"Home Load",value:de(h),sub:"",tone:h===null?"muted":"ok",icon:"home",clickable:!!o.home?.power},battery:{label:"Battery Storage",value:de(f===null?null:Math.abs(f)),sub:P==="charging"?"Charging":P==="discharging"?"Discharging":P==="idle"?"Idle":"Unknown",extra:R,tone:P==="unknown"?"muted":"ok",icon:"battery",clickable:!!(o.battery?.power??o.battery?.soc),soc:T}},A=dr(i.sun?n[i.sun]:void 0,s),vt=this._layers[this._layers.length-1],_t=!!vt&&!this._failedPlates.has(vt.url),vr={daylight:A,artwork:_t?{layers:this._layers,layout:xt(fr(this._widthPx||this.getBoundingClientRect().width||1200)),onError:N=>this._plateFailed(N),onLoad:N=>this._plateLoaded(N),debug:!!r.scene?.debug_anchors}:void 0,solarSplit:_t?{card:{edge:m.card,motion:X(m.card,v)},main:{edge:m.main,motion:X(m.main,v)},garage:m.garage?{edge:m.garage,motion:X(m.garage,v)}:null}:void 0,flows:{solar:{edge:F.solar,motion:X(F.solar,v)},battery:{edge:F.battery,motion:X(F.battery,v)},grid:{edge:F.grid,motion:X(F.grid,v)},home:{edge:F.home,motion:X(F.home,v)}},stale:v,animate:C,pills:le,inverterLed:v?"warn":k.some(N=>!N.unknown)?"ok":"off",onPill:N=>{let Ve=N==="solar"?o.solar_total??a[0]?.power:N==="grid"?o.grid?.power:N==="home"?o.home?.power:o.battery?.power??o.battery?.soc;this._moreInfo(Ve)}},_r=Zt(k)&&!v,We=this._chip(S,$.ageS,v,$.reason);return O`
      <ha-card style=${`--ef-crossfade:${r.scene?.crossfade_ms??900}ms`}>
        <div class="card">
          <header class="head">
            <div class="titles">
              ${(r.brand??"ECCO")!==""?O`<div class="wordmark"><span class="wm-accent">${(r.brand??"ECCO").slice(0,1)}</span>${(r.brand??"ECCO").slice(1)}</div>`:g}
              <div class="brand">${r.title??"Energy Flow"}</div>
              ${r.subtitle?O`<div class="subtitle">${r.subtitle}</div>`:g}
            </div>
            <button class=${`chip tone-${We.tone}`} type="button" @click=${()=>this._moreInfo(i.telemetry_online)} title=${We.title}>
              <span class="dot"></span>${We.text}
            </button>
          </header>
          ${v?O`<div class="strip stale-strip">${$.reason==="telemetry_offline"?"Telemetry offline: the values shown are the last received, not live.":`Values are stale: the newest power reading is ${pe($.ageS)}.`}</div>`:g}
          <div class="body">
            <div class="scene-wrap">
              ${mr(vr)}
              ${_r?O`<div class="banner idle-banner">Site idle: no power is flowing above ${5} W.</div>`:g}
            </div>
            <div class="side">
              ${r.features?.show_status_panel===!1?g:this._renderStatus(n,s,v,$.ageS)}
              ${r.features?.show_details_panel===!1?g:this._renderDetails(n,a,l,d,c,f,y,h)}
            </div>
          </div>
        </div>
      </ha-card>
    `}_chip(r,n,o,i){return r==="off"?{text:"Telemetry offline",tone:"alert",title:"The dongle's telemetry polling is offline"}:o&&i==="age"?{text:`Stale \xB7 ${pe(n)}`,tone:"warn",title:"No power reading has updated recently"}:r==="on"?{text:"System online",tone:"ok",title:n===null?"Telemetry online":`Telemetry online \xB7 updated ${pe(n)}`}:{text:n===null?"Status unknown":`Updated ${pe(n)}`,tone:"muted",title:"No telemetry-online entity configured"}}_renderStatus(r,n,o,i){let s=this._config,a=s.ecco??{},l=s.nodes??{},d=[],c=a.tou,u=ar((c?.slot_start_minutes??[]).map(A=>_(r,A)),cr(n),c?.valid?D(E(r,c.valid)):"unknown"),f=u.slot===null?null:u.slot-1,w=f===null?void 0:c?.slot_target_soc?.[f],y=f===null?void 0:c?.slot_charge_source?.[f],h=f===null?void 0:c?.slot_power?.[f],T=_(r,w),k=E(r,y),F=_(r,h);d.push({key:"tou",icon:"clock",label:"TOU Slot",value:u.value,sub:u.sub,tone:u.tone,entity:f===null?c?.slot_start_minutes?.[0]:c?.slot_start_minutes?.[f],title:"The slot containing the current local time, from the six slot start sensors"}),d.push({key:"charge",icon:"plug",label:"Charge Source",value:y&&k&&k!=="unknown"&&k!=="unavailable"?k:"--",sub:f===null?"Needs the current slot":F!==null?`Slot limit ${Z(F,s.format)}`:"Current slot setting",tone:k&&k.toLowerCase()==="grid"?"accent":"muted",entity:y}),d.push({key:"target",icon:"target",label:"Target SOC",value:ut(T),sub:f===null?"Needs the current slot":`Slot ${u.slot} setting`,tone:T===null?"muted":"accent",entity:w});let m=l.battery?.time_to_reserve,S=Me(m,_(r,m),L(r,m)?.unit_of_measurement),$=Be(m,S,L(r,m)),v=sr($);d.push({key:"runtime",icon:"battery",label:"Runtime",value:v.value,sub:v.sub,tone:v.tone,entity:m,title:$?ht($):"No time-to-reserve entity configured"});let C=a.free_power,H=gt({active:D(E(r,C?.active)),endsAtText:E(r,C?.ends_at),scheduleStatus:E(r,C?.schedule_status),statusText:E(r,C?.status),scheduleAttrs:L(r,C?.schedule_status),anyConfigured:!!(C?.active||C?.status||C?.schedule_status)},this._nowMs,"free_power");d.push({key:"fp",icon:"leaf",label:"Free Power",value:H.value,sub:H.sub,tone:H.tone,entity:C?.status??C?.active??C?.schedule_status,title:E(r,C?.status)});let b=a.dump_to_grid,R=gt({active:D(E(r,b?.active)),endsAtText:E(r,b?.ends_at),scheduleStatus:E(r,b?.schedule_status),statusText:E(r,b?.status),scheduleAttrs:L(r,b?.schedule_status),exportPowerW:_(r,b?.export_power),stopSoc:_(r,b?.stop_soc),anyConfigured:!!(b?.active||b?.status||b?.schedule_status)},this._nowMs,"dump");d.push({key:"dump",icon:"swap",label:"Dump to Grid",value:R.value,sub:R.sub,tone:R.tone,entity:b?.status??b?.active??b?.schedule_status,title:E(r,b?.status)});let P=yt(a.health?.sensors??[],a.health?.attention??[],r);d.push({key:"health",icon:P.grade==="FAILED"?"alert":"heart",label:"Health",value:P.value,sub:P.sub,tone:P.tone,entity:a.health?.sensors?.[0],wide:!0,title:[...P.failed.map(A=>`FAILED: ${A}`),...P.degraded.map(A=>`DEGRADED: ${A}`),...P.attention.map(A=>`attention: ${A}`),...P.unknown.map(A=>`unknown: ${A}`)].join(`
`)||"All configured subsystems healthy"});let z=_(r,a.forecast?.today),be=_(r,a.forecast?.remaining),le=_(r,s.today?.solar);return d.push({key:"forecast",icon:"forecast",label:"Forecast Today",value:I(z,s.format),sub:be!==null?`${I(be,s.format)} still expected`+(le!==null?` \xB7 ${I(le,s.format)} so far`:""):le!==null?`${I(le,s.format)} generated so far`:a.forecast?.today?"Remaining forecast unavailable":"No forecast entity configured",tone:z===null?"muted":"ok",entity:a.forecast?.remaining??a.forecast?.today,wide:!0}),O`
      <section class="status" aria-label="ECCO system status">
        <div class="status-head">
          <span class="status-title">ECCO System Status</span>
          <span class=${`status-age ${o?"stale":""}`}><span class="dot"></span>${i===null?"No timestamp":`Updated ${pe(i)}`}</span>
        </div>
        <div class="tiles">
          ${d.map(A=>O`
              <button
                type="button"
                class=${`tile tone-${A.tone} ${A.wide?"wide":""} ${A.entity?"clickable":""}`}
                title=${A.title??""}
                ?disabled=${!A.entity}
                @click=${()=>this._moreInfo(A.entity)}
              >
                <span class="tile-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d=${fe[A.icon]}></path></svg></span>
                <span class="tile-text">
                  <span class="tile-label">${A.label}</span>
                  <span class="tile-value">${A.value}</span>
                  ${A.sub?O`<span class="tile-sub">${A.sub}</span>`:g}
                </span>
                ${A.entity?O`<svg class="tile-chev" viewBox="0 0 24 24" aria-hidden="true"><path d=${fe.chevron}></path></svg>`:g}
              </button>
            `)}
        </div>
      </section>
    `}_renderDetails(r,n,o,i,s,a,l,d){let c=this._config,u=c.nodes??{},f=c.ecco??{},w=c.inverter_details??{},y=c.format,h=(b,R,P,z)=>O`
      <div class=${`row ${P?"clickable":""}`} @click=${()=>this._moreInfo(P)} role=${P?"button":"listitem"} tabindex=${P?0:-1}>
        <span class="row-label">${b}</span>
        <span class="row-value">${R}${z?O`<span class="row-note">${z}</span>`:g}</span>
      </div>`,T=b=>{let R=_(r,b);return R===null?"--":`${R.toFixed(1)} \xB0C`},k=lr(u.battery?.time_to_target,r),F=D(E(r,u.grid?.connected)),m=u.battery?.time_to_reserve,S=Be(m,Me(m,_(r,m),L(r,m)?.unit_of_measurement),L(r,m)),$=yt(f.health?.sensors??[],f.health?.attention??[],r),v=c.today??{},C=Object.values(v).some(Boolean),H=_(r,f.forecast?.tomorrow);return O`
      <details class="details" ?open=${this._detailsOpen} @toggle=${b=>this._detailsOpen=b.target.open}>
        <summary>
          <span>Inverter, grid and diagnostics</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${fe.chevron}></path></svg>
        </summary>
        <div class="details-grid">
          <div class="group">
            <div class="group-title">Inverter</div>
            ${h("State",E(r,u.inverter?.state)??"--",u.inverter?.state)}
            ${h("AC output",Z(s,y),u.inverter?.power)}
            ${h("Home load",Z(d,y),u.home?.power,_(r,u.home?.power)===0&&d!==0?"derived":void 0)}
            ${h("AC transformer",T(w.ac_temperature),w.ac_temperature)}
            ${h("DC transformer",T(w.dc_temperature),w.dc_temperature)}
            ${w.temperature?h("Temperature",T(w.temperature),w.temperature):g}
          </div>
          <div class="group">
            <div class="group-title">Grid</div>
            ${h("Connected",F==="on"?"Yes":F==="off"?"No":"Unknown",u.grid?.connected)}
            ${h("Power",l===null?"--":`${Z(Math.abs(l),y)} ${l>=5?"import":l<=-5?"export":""}`,u.grid?.power)}
            ${h("Voltage",_(r,u.grid?.voltage)===null?"--":`${_(r,u.grid?.voltage).toFixed(1)} V`,u.grid?.voltage)}
            ${h("Frequency",_(r,u.grid?.frequency)===null?"--":`${_(r,u.grid?.frequency).toFixed(2)} Hz`,u.grid?.frequency)}
          </div>
          <div class="group">
            <div class="group-title">Solar</div>
            ${n.map((b,R)=>h(b.label??`Array ${R+1}`,Z(o[R]??null,y),b.power))}
            ${h("Total",Z(i,y),u.solar_total,u.solar_total?void 0:n.length>1?"sum of arrays":void 0)}
            ${f.forecast?.tomorrow?h("Forecast tomorrow",I(H,y),f.forecast.tomorrow):g}
          </div>
          <div class="group">
            <div class="group-title">Battery</div>
            ${h("Power",a===null?"--":`${Z(Math.abs(a),y)} ${a>=5?"discharge":a<=-5?"charge":""}`,u.battery?.power)}
            ${h("State of charge",ut(_(r,u.battery?.soc)),u.battery?.soc)}
            ${h("Time to reserve",S?ht(S).replace(/^Time to reserve: /,""):"No entity configured",m)}
            ${h("Time to charge target",k.value,u.battery?.time_to_target,k.sub)}
            ${w.battery_temperature?h("Temperature",T(w.battery_temperature),w.battery_temperature):g}
          </div>
          ${(f.health?.sensors?.length??0)>0?O`<div class="group">
                  <div class="group-title">Health</div>
                  ${(f.health?.sensors??[]).map(b=>{let R=(E(r,b)??"--").toUpperCase();return h(b.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/_/g," "),R==="HEALTHY"?"Healthy":R==="DEGRADED"?"Degraded":R==="FAILED"?"Failed":"Unknown",b,typeof L(r,b)?.summary=="string"&&R!=="HEALTHY"?String(L(r,b)?.summary).trim().slice(0,80):void 0)})}
                  ${(f.health?.attention??[]).map(b=>h(b.replace(/^.*?\./,"").replace(/_/g," "),D(E(r,b))==="on"?"Needs attention":D(E(r,b))==="off"?"Clear":"Unknown",b))}
                  ${$.attention.length+$.failed.length>0?O`<div class="row-note block">Warnings are listed in full above; the Health tile summarises them.</div>`:g}
                </div>`:g}
          ${C?O`<div class="group today">
                  <div class="group-title">Today</div>
                  ${h("Solar",I(_(r,v.solar),y),v.solar)}
                  ${h("Load",I(_(r,v.load),y),v.load)}
                  ${h("Import",I(_(r,v.import),y),v.import)}
                  ${h("Export",I(_(r,v.export),y),v.export)}
                  ${h("Battery charge",I(_(r,v.battery_charge),y),v.battery_charge)}
                  ${h("Battery discharge",I(_(r,v.battery_discharge),y),v.battery_discharge)}
                </div>`:g}
        </div>
      </details>
    `}_pathFor(r,n){let o=r.querySelector(`#${CSS.escape(n)}`);if(!o)return null;let i=o.getAttribute("d")??"",s=this._lengthCache.get(o);return(!s||s.d!==i)&&(s={d:i,length:o.getTotalLength()},this._lengthCache.set(o,s)),s.length?{path:o,length:s.length}:null}_animate(){this._raf=requestAnimationFrame(()=>this._animate());let r=this.shadowRoot;if(!r||this._reducedMotion)return;let n=r.querySelectorAll(".pulse");if(!n.length)return;let o=performance.now()/1e3;n.forEach(i=>{let s=i.dataset.path,a=parseFloat(i.dataset.duration??""),l=parseFloat(i.dataset.phase??"0");if(!s||!a)return;let d=this._pathFor(r,s);if(!d)return;let c=(o/a+l)%1;i.dataset.reversed==="1"&&(c=1-c);let u=d.path.getPointAtLength(c*d.length);i.setAttribute("transform",`translate(${u.x.toFixed(2)},${u.y.toFixed(2)})`)})}_placeChevrons(){let r=this.shadowRoot;r&&r.querySelectorAll(".chevron").forEach(n=>{let o=n.dataset.path,i=parseFloat(n.dataset.phase??"0.5");if(!o)return;let s=this._pathFor(r,o);if(!s)return;let a=n.dataset.reversed==="1",l=(a?1-i:i)*s.length,d=s.path.getPointAtLength(Math.max(0,l-2)),c=s.path.getPointAtLength(Math.min(s.length,l+2)),u=Math.atan2(c.y-d.y,c.x-d.x)*180/Math.PI+(a?180:0),f=s.path.getPointAtLength(l);n.setAttribute("transform",`translate(${f.x.toFixed(2)},${f.y.toFixed(2)}) rotate(${u.toFixed(1)})`)})}};U.styles=qe`
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
    /* Artwork routes: thin base, soft glow, crisp highlight, travelling particles. */
    .fine-base {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0.55;
    }
    .fine-glow {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      filter: url(#ef3d-blur);
    }
    .fine-highlight {
      fill: none;
      stroke: #ffffff;
      stroke-linecap: round;
      stroke-linejoin: round;
      mix-blend-mode: screen;
    }
    .flow.fine.idle .fine-base {
      opacity: 0.22;
    }
    .flow.fine.unknown .fine-base {
      stroke: #9aa6bd;
      stroke-dasharray: 4 6;
      opacity: 0.35;
    }
    .scene.stale .fine-base {
      opacity: 0.18;
    }
    .node-light-halo {
      fill: var(--flow-colour);
      opacity: 0.1;
      filter: url(#ef3d-blur-soft);
    }
    .node-light-core {
      fill: var(--flow-colour);
      opacity: 0.35;
    }
    .node-light.active .node-light-halo {
      opacity: 0.38;
    }
    .node-light.active .node-light-core {
      fill: #ffffff;
      opacity: 0.95;
      filter: drop-shadow(0 0 4px var(--flow-colour));
    }
    .debug-dot {
      fill: #ff3b6b;
    }
    .debug-ring {
      fill: none;
      stroke: #ff3b6b;
      stroke-width: 2;
    }
    .debug-port {
      fill: #fff;
      stroke: #ff3b6b;
      stroke-width: 2;
    }
    .debug-zone {
      fill: none;
      stroke: #ff3b6b;
      stroke-dasharray: 8 6;
      stroke-width: 2;
    }
    .debug-label {
      font-size: calc(10px * var(--k, 1));
      font-weight: 700;
      fill: #fff;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.8);
      stroke-width: calc(2px * var(--k, 1));
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
    .flow.fine .pulse-halo {
      opacity: 0.3;
    }
    .flow.fine .pulse-glow {
      opacity: 0.95;
      filter: drop-shadow(0 0 4px var(--pulse-colour));
    }
    .flow.fine .pulse-halo {
      opacity: 0.38;
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
  `,Y([Le({attribute:!1})],U.prototype,"hass",2),Y([ue()],U.prototype,"_config",2),Y([ue()],U.prototype,"_detailsOpen",2),Y([ue()],U.prototype,"_nowMs",2),Y([ue()],U.prototype,"_layers",2),Y([ue()],U.prototype,"_widthPx",2),U=Y([Dt("ecco-flow-3d-card")],U);window.customCards=[...window.customCards??[],{type:"ecco-flow-3d-card",name:"ECCO 3D Energy Flow",description:"Read-only isometric energy flow scene (solar, battery, grid, home) with animated power paths and the ECCO status grid.",preview:!1}];export{U as EccoFlow3dCard};
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
