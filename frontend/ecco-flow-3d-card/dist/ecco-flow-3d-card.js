var dn=Object.defineProperty;var un=Object.getOwnPropertyDescriptor;var Q=(e,r,t,n)=>{for(var o=n>1?void 0:n?un(r,t):r,i=e.length-1,s;i>=0;i--)(s=e[i])&&(o=(n?s(r,t,o):s(o))||o);return n&&o&&dn(r,t,o),o};var ze=globalThis,Ue=ze.ShadowRoot&&(ze.ShadyCSS===void 0||ze.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,lt=Symbol(),Bt=new WeakMap,ve=class{constructor(r,t,n){if(this._$cssResult$=!0,n!==lt)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=r,this.t=t}get styleSheet(){let r=this.o,t=this.t;if(Ue&&r===void 0){let n=t!==void 0&&t.length===1;n&&(r=Bt.get(t)),r===void 0&&((this.o=r=new CSSStyleSheet).replaceSync(this.cssText),n&&Bt.set(t,r))}return r}toString(){return this.cssText}},Vt=e=>new ve(typeof e=="string"?e:e+"",void 0,lt),ct=(e,...r)=>{let t=e.length===1?e[0]:r.reduce((n,o,i)=>n+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(o)+e[i+1],e[0]);return new ve(t,e,lt)},Wt=(e,r)=>{if(Ue)e.adoptedStyleSheets=r.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(let t of r){let n=document.createElement("style"),o=ze.litNonce;o!==void 0&&n.setAttribute("nonce",o),n.textContent=t.cssText,e.appendChild(n)}},dt=Ue?e=>e:e=>e instanceof CSSStyleSheet?(r=>{let t="";for(let n of r.cssRules)t+=n.cssText;return Vt(t)})(e):e;var{is:pn,defineProperty:fn,getOwnPropertyDescriptor:gn,getOwnPropertyNames:hn,getOwnPropertySymbols:yn,getPrototypeOf:mn}=Object,De=globalThis,Yt=De.trustedTypes,bn=Yt?Yt.emptyScript:"",xn=De.reactiveElementPolyfillSupport,ke=(e,r)=>e,Ae={toAttribute(e,r){switch(r){case Boolean:e=e?bn:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,r){let t=e;switch(r){case Boolean:t=e!==null;break;case Number:t=e===null?null:Number(e);break;case Object:case Array:try{t=JSON.parse(e)}catch{t=null}}return t}},He=(e,r)=>!pn(e,r),qt={attribute:!0,type:String,converter:Ae,reflect:!1,useDefault:!1,hasChanged:He};Symbol.metadata??=Symbol("metadata"),De.litPropertyMetadata??=new WeakMap;var Y=class extends HTMLElement{static addInitializer(r){this._$Ei(),(this.l??=[]).push(r)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(r,t=qt){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(r)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(r,t),!t.noAccessor){let n=Symbol(),o=this.getPropertyDescriptor(r,n,t);o!==void 0&&fn(this.prototype,r,o)}}static getPropertyDescriptor(r,t,n){let{get:o,set:i}=gn(this.prototype,r)??{get(){return this[t]},set(s){this[t]=s}};return{get:o,set(s){let l=o?.call(this);i?.call(this,s),this.requestUpdate(r,l,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(r){return this.elementProperties.get(r)??qt}static _$Ei(){if(this.hasOwnProperty(ke("elementProperties")))return;let r=mn(this);r.finalize(),r.l!==void 0&&(this.l=[...r.l]),this.elementProperties=new Map(r.elementProperties)}static finalize(){if(this.hasOwnProperty(ke("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(ke("properties"))){let t=this.properties,n=[...hn(t),...yn(t)];for(let o of n)this.createProperty(o,t[o])}let r=this[Symbol.metadata];if(r!==null){let t=litPropertyMetadata.get(r);if(t!==void 0)for(let[n,o]of t)this.elementProperties.set(n,o)}this._$Eh=new Map;for(let[t,n]of this.elementProperties){let o=this._$Eu(t,n);o!==void 0&&this._$Eh.set(o,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(r){let t=[];if(Array.isArray(r)){let n=new Set(r.flat(1/0).reverse());for(let o of n)t.unshift(dt(o))}else r!==void 0&&t.push(dt(r));return t}static _$Eu(r,t){let n=t.attribute;return n===!1?void 0:typeof n=="string"?n:typeof r=="string"?r.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(r=>this.enableUpdating=r),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(r=>r(this))}addController(r){(this._$EO??=new Set).add(r),this.renderRoot!==void 0&&this.isConnected&&r.hostConnected?.()}removeController(r){this._$EO?.delete(r)}_$E_(){let r=new Map,t=this.constructor.elementProperties;for(let n of t.keys())this.hasOwnProperty(n)&&(r.set(n,this[n]),delete this[n]);r.size>0&&(this._$Ep=r)}createRenderRoot(){let r=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return Wt(r,this.constructor.elementStyles),r}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(r=>r.hostConnected?.())}enableUpdating(r){}disconnectedCallback(){this._$EO?.forEach(r=>r.hostDisconnected?.())}attributeChangedCallback(r,t,n){this._$AK(r,n)}_$ET(r,t){let n=this.constructor.elementProperties.get(r),o=this.constructor._$Eu(r,n);if(o!==void 0&&n.reflect===!0){let i=(n.converter?.toAttribute!==void 0?n.converter:Ae).toAttribute(t,n.type);this._$Em=r,i==null?this.removeAttribute(o):this.setAttribute(o,i),this._$Em=null}}_$AK(r,t){let n=this.constructor,o=n._$Eh.get(r);if(o!==void 0&&this._$Em!==o){let i=n.getPropertyOptions(o),s=typeof i.converter=="function"?{fromAttribute:i.converter}:i.converter?.fromAttribute!==void 0?i.converter:Ae;this._$Em=o;let l=s.fromAttribute(t,i.type);this[o]=l??this._$Ej?.get(o)??l,this._$Em=null}}requestUpdate(r,t,n,o=!1,i){if(r!==void 0){let s=this.constructor;if(o===!1&&(i=this[r]),n??=s.getPropertyOptions(r),!((n.hasChanged??He)(i,t)||n.useDefault&&n.reflect&&i===this._$Ej?.get(r)&&!this.hasAttribute(s._$Eu(r,n))))return;this.C(r,t,n)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(r,t,{useDefault:n,reflect:o,wrapped:i},s){n&&!(this._$Ej??=new Map).has(r)&&(this._$Ej.set(r,s??t??this[r]),i!==!0||s!==void 0)||(this._$AL.has(r)||(this.hasUpdated||n||(t=void 0),this._$AL.set(r,t)),o===!0&&this._$Em!==r&&(this._$Eq??=new Set).add(r))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}let r=this.scheduleUpdate();return r!=null&&await r,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[o,i]of this._$Ep)this[o]=i;this._$Ep=void 0}let n=this.constructor.elementProperties;if(n.size>0)for(let[o,i]of n){let{wrapped:s}=i,l=this[o];s!==!0||this._$AL.has(o)||l===void 0||this.C(o,void 0,i,l)}}let r=!1,t=this._$AL;try{r=this.shouldUpdate(t),r?(this.willUpdate(t),this._$EO?.forEach(n=>n.hostUpdate?.()),this.update(t)):this._$EM()}catch(n){throw r=!1,this._$EM(),n}r&&this._$AE(t)}willUpdate(r){}_$AE(r){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(r)),this.updated(r)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(r){return!0}update(r){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(r){}firstUpdated(r){}};Y.elementStyles=[],Y.shadowRootOptions={mode:"open"},Y[ke("elementProperties")]=new Map,Y[ke("finalized")]=new Map,xn?.({ReactiveElement:Y}),(De.reactiveElementVersions??=[]).push("2.1.2");var mt=globalThis,Xt=e=>e,Ke=mt.trustedTypes,Zt=Ke?Ke.createPolicy("lit-html",{createHTML:e=>e}):void 0,nr="$lit$",J=`lit$${Math.random().toFixed(9).slice(2)}$`,or="?"+J,wn=`<${or}>`,ce=document,Re=()=>ce.createComment(""),Pe=e=>e===null||typeof e!="object"&&typeof e!="function",bt=Array.isArray,_n=e=>bt(e)||typeof e?.[Symbol.iterator]=="function",ut=`[ 	
\f\r]`,Se=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Qt=/-->/g,Jt=/>/g,ae=RegExp(`>|${ut}(?:([^\\s"'>=/]+)(${ut}*=${ut}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),er=/'/g,tr=/"/g,ir=/^(?:script|style|textarea|title)$/i,xt=e=>(r,...t)=>({_$litType$:e,strings:r,values:t}),L=xt(1),$=xt(2),Ao=xt(3),de=Symbol.for("lit-noChange"),w=Symbol.for("lit-nothing"),rr=new WeakMap,le=ce.createTreeWalker(ce,129);function sr(e,r){if(!bt(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return Zt!==void 0?Zt.createHTML(r):r}var $n=(e,r)=>{let t=e.length-1,n=[],o,i=r===2?"<svg>":r===3?"<math>":"",s=Se;for(let l=0;l<t;l++){let a=e[l],c,u,d=-1,m=0;for(;m<a.length&&(s.lastIndex=m,u=s.exec(a),u!==null);)m=s.lastIndex,s===Se?u[1]==="!--"?s=Qt:u[1]!==void 0?s=Jt:u[2]!==void 0?(ir.test(u[2])&&(o=RegExp("</"+u[2],"g")),s=ae):u[3]!==void 0&&(s=ae):s===ae?u[0]===">"?(s=o??Se,d=-1):u[1]===void 0?d=-2:(d=s.lastIndex-u[2].length,c=u[1],s=u[3]===void 0?ae:u[3]==='"'?tr:er):s===tr||s===er?s=ae:s===Qt||s===Jt?s=Se:(s=ae,o=void 0);let h=s===ae&&e[l+1].startsWith("/>")?" ":"";i+=s===Se?a+wn:d>=0?(n.push(c),a.slice(0,d)+nr+a.slice(d)+J+h):a+J+(d===-2?l:h)}return[sr(e,i+(e[t]||"<?>")+(r===2?"</svg>":r===3?"</math>":"")),n]},Me=class e{constructor({strings:r,_$litType$:t},n){let o;this.parts=[];let i=0,s=0,l=r.length-1,a=this.parts,[c,u]=$n(r,t);if(this.el=e.createElement(c,n),le.currentNode=this.el.content,t===2||t===3){let d=this.el.content.firstChild;d.replaceWith(...d.childNodes)}for(;(o=le.nextNode())!==null&&a.length<l;){if(o.nodeType===1){if(o.hasAttributes())for(let d of o.getAttributeNames())if(d.endsWith(nr)){let m=u[s++],h=o.getAttribute(d).split(J),p=/([.?@])?(.*)/.exec(m);a.push({type:1,index:i,name:p[2],strings:h,ctor:p[1]==="."?ft:p[1]==="?"?gt:p[1]==="@"?ht:ge}),o.removeAttribute(d)}else d.startsWith(J)&&(a.push({type:6,index:i}),o.removeAttribute(d));if(ir.test(o.tagName)){let d=o.textContent.split(J),m=d.length-1;if(m>0){o.textContent=Ke?Ke.emptyScript:"";for(let h=0;h<m;h++)o.append(d[h],Re()),le.nextNode(),a.push({type:2,index:++i});o.append(d[m],Re())}}}else if(o.nodeType===8)if(o.data===or)a.push({type:2,index:i});else{let d=-1;for(;(d=o.data.indexOf(J,d+1))!==-1;)a.push({type:7,index:i}),d+=J.length-1}i++}}static createElement(r,t){let n=ce.createElement("template");return n.innerHTML=r,n}};function fe(e,r,t=e,n){if(r===de)return r;let o=n!==void 0?t._$Co?.[n]:t._$Cl,i=Pe(r)?void 0:r._$litDirective$;return o?.constructor!==i&&(o?._$AO?.(!1),i===void 0?o=void 0:(o=new i(e),o._$AT(e,t,n)),n!==void 0?(t._$Co??=[])[n]=o:t._$Cl=o),o!==void 0&&(r=fe(e,o._$AS(e,r.values),o,n)),r}var pt=class{constructor(r,t){this._$AV=[],this._$AN=void 0,this._$AD=r,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(r){let{el:{content:t},parts:n}=this._$AD,o=(r?.creationScope??ce).importNode(t,!0);le.currentNode=o;let i=le.nextNode(),s=0,l=0,a=n[0];for(;a!==void 0;){if(s===a.index){let c;a.type===2?c=new Ce(i,i.nextSibling,this,r):a.type===1?c=new a.ctor(i,a.name,a.strings,this,r):a.type===6&&(c=new yt(i,this,r)),this._$AV.push(c),a=n[++l]}s!==a?.index&&(i=le.nextNode(),s++)}return le.currentNode=ce,o}p(r){let t=0;for(let n of this._$AV)n!==void 0&&(n.strings!==void 0?(n._$AI(r,n,t),t+=n.strings.length-2):n._$AI(r[t])),t++}},Ce=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(r,t,n,o){this.type=2,this._$AH=w,this._$AN=void 0,this._$AA=r,this._$AB=t,this._$AM=n,this.options=o,this._$Cv=o?.isConnected??!0}get parentNode(){let r=this._$AA.parentNode,t=this._$AM;return t!==void 0&&r?.nodeType===11&&(r=t.parentNode),r}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(r,t=this){r=fe(this,r,t),Pe(r)?r===w||r==null||r===""?(this._$AH!==w&&this._$AR(),this._$AH=w):r!==this._$AH&&r!==de&&this._(r):r._$litType$!==void 0?this.$(r):r.nodeType!==void 0?this.T(r):_n(r)?this.k(r):this._(r)}O(r){return this._$AA.parentNode.insertBefore(r,this._$AB)}T(r){this._$AH!==r&&(this._$AR(),this._$AH=this.O(r))}_(r){this._$AH!==w&&Pe(this._$AH)?this._$AA.nextSibling.data=r:this.T(ce.createTextNode(r)),this._$AH=r}$(r){let{values:t,_$litType$:n}=r,o=typeof n=="number"?this._$AC(r):(n.el===void 0&&(n.el=Me.createElement(sr(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===o)this._$AH.p(t);else{let i=new pt(o,this),s=i.u(this.options);i.p(t),this.T(s),this._$AH=i}}_$AC(r){let t=rr.get(r.strings);return t===void 0&&rr.set(r.strings,t=new Me(r)),t}k(r){bt(this._$AH)||(this._$AH=[],this._$AR());let t=this._$AH,n,o=0;for(let i of r)o===t.length?t.push(n=new e(this.O(Re()),this.O(Re()),this,this.options)):n=t[o],n._$AI(i),o++;o<t.length&&(this._$AR(n&&n._$AB.nextSibling,o),t.length=o)}_$AR(r=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);r!==this._$AB;){let n=Xt(r).nextSibling;Xt(r).remove(),r=n}}setConnected(r){this._$AM===void 0&&(this._$Cv=r,this._$AP?.(r))}},ge=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(r,t,n,o,i){this.type=1,this._$AH=w,this._$AN=void 0,this.element=r,this.name=t,this._$AM=o,this.options=i,n.length>2||n[0]!==""||n[1]!==""?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=w}_$AI(r,t=this,n,o){let i=this.strings,s=!1;if(i===void 0)r=fe(this,r,t,0),s=!Pe(r)||r!==this._$AH&&r!==de,s&&(this._$AH=r);else{let l=r,a,c;for(r=i[0],a=0;a<i.length-1;a++)c=fe(this,l[n+a],t,a),c===de&&(c=this._$AH[a]),s||=!Pe(c)||c!==this._$AH[a],c===w?r=w:r!==w&&(r+=(c??"")+i[a+1]),this._$AH[a]=c}s&&!o&&this.j(r)}j(r){r===w?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,r??"")}},ft=class extends ge{constructor(){super(...arguments),this.type=3}j(r){this.element[this.name]=r===w?void 0:r}},gt=class extends ge{constructor(){super(...arguments),this.type=4}j(r){this.element.toggleAttribute(this.name,!!r&&r!==w)}},ht=class extends ge{constructor(r,t,n,o,i){super(r,t,n,o,i),this.type=5}_$AI(r,t=this){if((r=fe(this,r,t,0)??w)===de)return;let n=this._$AH,o=r===w&&n!==w||r.capture!==n.capture||r.once!==n.once||r.passive!==n.passive,i=r!==w&&(n===w||o);o&&this.element.removeEventListener(this.name,this,n),i&&this.element.addEventListener(this.name,this,r),this._$AH=r}handleEvent(r){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,r):this._$AH.handleEvent(r)}},yt=class{constructor(r,t,n){this.element=r,this.type=6,this._$AN=void 0,this._$AM=t,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(r){fe(this,r)}};var vn=mt.litHtmlPolyfillSupport;vn?.(Me,Ce),(mt.litHtmlVersions??=[]).push("3.3.3");var ar=(e,r,t)=>{let n=t?.renderBefore??r,o=n._$litPart$;if(o===void 0){let i=t?.renderBefore??null;n._$litPart$=o=new Ce(r.insertBefore(Re(),i),i,void 0,t??{})}return o._$AI(e),o};var wt=globalThis,ee=class extends Y{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let r=super.createRenderRoot();return this.renderOptions.renderBefore??=r.firstChild,r}update(r){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(r),this._$Do=ar(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return de}};ee._$litElement$=!0,ee.finalized=!0,wt.litElementHydrateSupport?.({LitElement:ee});var kn=wt.litElementPolyfillSupport;kn?.({LitElement:ee});(wt.litElementVersions??=[]).push("4.2.2");var lr=e=>(r,t)=>{t!==void 0?t.addInitializer(()=>{customElements.define(e,r)}):customElements.define(e,r)};var An={attribute:!0,type:String,converter:Ae,reflect:!1,hasChanged:He},Sn=(e=An,r,t)=>{let{kind:n,metadata:o}=t,i=globalThis.litPropertyMetadata.get(o);if(i===void 0&&globalThis.litPropertyMetadata.set(o,i=new Map),n==="setter"&&((e=Object.create(e)).wrapped=!0),i.set(t.name,e),n==="accessor"){let{name:s}=t;return{set(l){let a=r.get.call(this);r.set.call(this,l),this.requestUpdate(s,a,e,!0,l)},init(l){return l!==void 0&&this.C(s,void 0,e,l),l}}}if(n==="setter"){let{name:s}=t;return function(l){let a=this[s];r.call(this,l),this.requestUpdate(s,a,e,!0,l)}}throw Error("Unsupported decorator location: "+n)};function je(e){return(r,t)=>typeof t=="object"?Sn(e,r,t):((n,o,i)=>{let s=o.hasOwnProperty(i);return o.constructor.createProperty(i,n),s?Object.getOwnPropertyDescriptor(o,i):void 0})(e,r,t)}function he(e){return je({...e,state:!0,attribute:!1})}function cr(e){return e?(Array.isArray(e)?e:[e]).filter(t=>!!t&&!!t.power):[]}var dr=180;function _t(e){if(e==null||e===!0)return"pulse";if(e===!1)return"off";if(typeof e=="string"){let r=e.trim().toLowerCase();if(r==="pulse"||r==="particles"||r==="off")return r}return null}function ur(e){if(!e||typeof e!="object")throw new Error("ecco-flow-3d-card: invalid configuration");let r=e;if(!r.nodes||typeof r.nodes!="object"||Object.keys(r.nodes).length===0)throw new Error("ecco-flow-3d-card: at least one entry under `nodes:` is required");let t=r.ecco?.tou;for(let n of["slot_start_minutes","slot_target_soc","slot_charge_source","slot_power"]){let o=t?.[n];if(o!==void 0&&(!Array.isArray(o)||o.length!==6))throw new Error(`ecco-flow-3d-card: ecco.tou.${n} must list exactly six entities (slot 1 to slot 6)`)}if(_t(r.scene?.links)===null)throw new Error("ecco-flow-3d-card: scene.links must be pulse, particles or off")}function pr(e,r){return r==="discharge_positive"?e:-e}function fr(e,r){return r==="export_positive"?-e:e}var Rn=150;function gr(e,r,t){let n=r!==null&&t!==null?Math.max(0,r+t):null;return e===null||e===0&&n!==null&&n>Rn?n:Math.max(0,e)}function hr(e,r){if(e!==null)return Math.max(0,e);let t=r.filter(n=>n!==null);return t.length===0?null:Math.max(0,t.reduce((n,o)=>n+o,0))}var q=5;function Ee(e,r,t){if(r===null)return{id:e,magnitudeW:null,idle:!1,unknown:!0,reversed:!1};let n=Math.abs(r);return{id:e,magnitudeW:n,idle:n<q,unknown:!1,reversed:t&&r<0}}function yr(e){return[Ee("solar",e.solarW===null?null:Math.max(0,e.solarW),!1),Ee("battery",e.batteryW,!0),Ee("grid",e.gridW,!0),Ee("home",e.homeW===null?null:Math.max(0,e.homeW),!1)]}function mr(e){return e.id==="home"?!e.reversed:e.reversed}function br(e,r,t,n){let o=s=>Ee("solar",s===null?null:Math.max(0,s),!1),i=o(e);return n>=2&&(r!==null||t!==null)?{card:i,main:o(r),garage:o(t)}:{card:i,main:o(e),garage:null}}function xr(e){let r=e.filter(t=>!t.unknown);return r.length>0&&r.every(t=>t.idle)}function wr(e){return e===null?"unknown":e>=q?"discharging":e<=-q?"charging":"idle"}function _r(e){return e===null?"unknown":e>=q?"importing":e<=-q?"exporting":"idle"}var kr=6e3,Pn=2.4,Mn=.45,$r=2.6,Ar=15,Be=4,Cn=9,$t=2.7,En=5.4,vt=2.6,Tn=3.3,In=.6,vr=5.5,kt=3.1,Fn=4.9;function On(e){if(!(e>q))return 0;let r=Math.log(e/q)/Math.log(kr/q),t=Math.min(1,Math.max(0,r));return Math.pow(t,Pn)}function Ln(e){return e<750?1:e<3e3?2:e<6e3?3:4}var Nn={intensity:0,moving:!1,dashDurationS:0,dashLen:Be,gapLen:Ar-Be,packetWidthPx:$t,baseWidthPx:vt,packetOpacity:0,glowPx:0,ballCount:0,ballDurationS:0,ballRadiusPx:kt};function te(e,r){if(e.unknown||e.idle||r||e.magnitudeW===null)return Nn;let t=e.magnitudeW,n=On(t),o=Math.min(1,t/kr),i=Be+n*(Cn-Be);return{intensity:n,moving:!0,dashDurationS:$r-n*($r-Mn),dashLen:i,gapLen:Ar-i,packetWidthPx:$t+n*(En-$t),baseWidthPx:vt+o*(Tn-vt),packetOpacity:.62+n*.36,glowPx:1.6+n*2.4,ballCount:Ln(t),ballDurationS:vr-n*(vr-In),ballRadiusPx:kt+n*(Fn-kt)}}var zn=625,Un=300;function At(e,r){return Math.max(.35,e.ballDurationS*r/zn)}function Sr(e,r){return!e.moving||!(r>0)?{count:0,durationS:0}:{count:Math.max(1,Math.min(8,Math.round(r*e.ballCount/Un))),durationS:At(e,r)}}var Dn=4.5;function Rr(e){return .5-.5*Math.cos(2*Math.PI*e/Dn)}var Pr=.05,St=.16,Mr=.2,Rt=.42;function Pt(e){if(e==null||e==="unknown"||e==="unavailable"||e===""||e==="none"||e==="None")return null;let r=Number(e);return Number.isFinite(r)?r:null}function re(e,r){if(e==null||Number.isNaN(e))return"--";let t=r?.power_unit??"auto",n=Math.abs(e);return t==="kw"||t==="auto"&&n>=1e3?`${(e/1e3).toFixed(r?.precision??2)} kW`:`${e.toFixed(r?.precision??0)} W`}function ye(e){if(e==null||Number.isNaN(e))return"--";let r=Math.abs(e);return r>=1e4?`${(e/1e3).toFixed(0)} kW`:r>=1e3?`${(e/1e3).toFixed(1)} kW`:`${Math.round(e)} W`}function z(e,r){return e==null||Number.isNaN(e)?"--":`${e.toFixed(r?.energy_precision??1)} kWh`}function Ve(e){return e==null||!Number.isFinite(e)?"--":`${Math.round(e)}%`}function X(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let r=Math.round(e);if(r===0)return e>0?"<1 min":"0 min";if(r<60)return`${r} min`;if(r<1440){let o=Math.floor(r/60),i=r%60;return i===0?`${o} h`:`${o} h ${i} min`}let t=Math.floor(r/1440),n=Math.floor(r%1440/60);return n===0?`${t} d`:`${t} d ${n} h`}function We(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let r=Math.round(e);if(r===0)return e>0?"<1m":"0m";if(r<60)return`\u2248${r}m`;if(r<1440){let o=Math.floor(r/60),i=r%60;return i===0?`\u2248${o}h`:`\u2248${o}h ${i}m`}let t=Math.floor(r/1440),n=Math.floor(r%1440/60);return n===0?`\u2248${t}d`:`\u2248${t}d ${n}h`}function Mt(e){return e==null||!Number.isFinite(e)?"--":`${e.toFixed(1)} V`}function Ct(e){return e==null||!Number.isFinite(e)?"--":`${e.toFixed(2)} Hz`}function Ye(e){return e==null||!Number.isFinite(e)?"--":`${e.toFixed(1)} \xB0C`}function Cr(e,r){return e===null||r===null||!(r>0)?null:Math.max(0,Math.min(1,e/r))}function Et(e){if(e==null||!Number.isFinite(e))return"--:--";let r=(Math.round(e)%1440+1440)%1440;return`${String(Math.floor(r/60)).padStart(2,"0")}:${String(r%60).padStart(2,"0")}`}function Tt(e){return`${String(e.getHours()).padStart(2,"0")}:${String(e.getMinutes()).padStart(2,"0")}`}function me(e){return e===null||!Number.isFinite(e)||e<0?"--":e<5?"just now":e<60?`${Math.floor(e)} s ago`:e<3600?`${Math.floor(e/60)} min ago`:e<86400?`${Math.floor(e/3600)} h ago`:`${Math.floor(e/86400)} d ago`}function F(e,r){return r?e[r]?.state:void 0}function R(e,r){return r?Pt(e[r]?.state):null}function K(e,r){return r?e[r]?.attributes:void 0}function G(e){return e==="on"||e==="true"||e==="True"?"on":e==="off"||e==="false"||e==="False"?"off":"unknown"}var Hn=new Map([["s",1/60],["min",1],["h",60],["d",1440]]);function Te(e,r,t){if(!e)return;let n=t==null||t===""?1:Hn.get(t);return n!==void 0&&r!==null&&r>=0?r*n:null}var Kn=["discharging","at_reserve","charging","holding","insufficient_data","stale"];function Er(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0?e:null}function Xe(e,r,t){if(!e||r===void 0)return;let n=t?.status,i=Kn.includes(n)?n:r!==null?"discharging":"insufficient_data";i==="discharging"&&r===null&&(i="insufficient_data");let s=i==="discharging"||i==="at_reserve",l=typeof t?.summary=="string"&&t.summary.trim()!==""?t.summary:null;return{status:i,minutes:s?r:null,low:i==="discharging"?Er(t?.minutes_low):null,high:i==="discharging"?Er(t?.minutes_high):null,beyondHorizon:i==="discharging"&&t?.beyond_horizon===!0,solarAssisted:i==="discharging"&&t?.solar_assisted===!0,summary:l}}var Tr="Over 3 days";function It(e){switch(e.status){case"discharging":return e.beyondHorizon?Tr:`${We(e.minutes)} to reserve`;case"at_reserve":return"At reserve";case"charging":return"Charging";case"holding":return"Holding";case"stale":return"Telemetry stale";default:return"Insufficient data"}}function Ir(e){if(!e)return{value:"--",sub:"No runtime entity",tone:"muted"};switch(e.status){case"discharging":return{value:e.beyondHorizon?">3 d":We(e.minutes),sub:e.beyondHorizon?"to reserve (estimate)":e.low!==null&&e.high!==null?`to reserve \xB7 likely ${X(e.low)} to ${X(e.high)}`:"to reserve (estimate)",tone:"ok"};case"at_reserve":return{value:"At reserve",sub:e.summary??"At or below the reserve",tone:"warn"};case"charging":return{value:"Charging",sub:"No discharge estimate while charging",tone:"ok"};case"holding":return{value:"Holding",sub:"Neither charging nor discharging",tone:"muted"};case"stale":return{value:"Stale",sub:"Estimate paused: telemetry stale",tone:"warn"};default:return{value:"--",sub:e.summary??"Insufficient data",tone:"muted"}}}function Ft(e){if(e.status!=="discharging")return`Time to reserve: ${e.summary??It(e)}`;let r=[e.beyondHorizon?`${Tr} until the batteries reach the configured reserve at recent usage`:`Approximately ${X(e.minutes)} until the batteries reach the configured reserve at recent usage`];return!e.beyondHorizon&&e.low!==null&&e.high!==null&&r.push(`likely ${X(e.low)} to ${X(e.high)}`),e.solarAssisted&&r.push("solar-assisted, so it shortens as solar output falls"),r.push("an estimate, not a guarantee"),`Time to reserve: ${r.join("; ")}`}function Fr(e,r){if(!e)return{value:"Not available",sub:"No ECCO entity provides a time to charge target",tone:"muted"};let t=Te(e,R(r,e),K(r,e)?.unit_of_measurement);return t==null?{value:"--",sub:"Entity has no value",tone:"muted"}:{value:We(t),sub:"to charge target (entity value)",tone:"ok"}}var jn=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function Gn(e){if(!e)return null;let r=jn.exec(e.trim());if(!r)return null;let t=new Date(Number(r[1]),Number(r[2])-1,Number(r[3]),Number(r[4]),Number(r[5]),Number(r[6]));return Number.isNaN(t.getTime())?null:t}function Bn(e,r,t){return t?"Active \xB7 end time unavailable":r===null?"Active":e===null||e<=0?`Ends ${Tt(r)} \xB7 ending`:`Ends ${Tt(r)} \xB7 ${X(e)} left`}function Ot(e,r,t){let n={phase:"unknown",value:"--",sub:"Not configured",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(!e.anyConfigured)return n;let o=(e.scheduleStatus??"").trim().toUpperCase(),i=Gn(e.endsAtText),s=(e.endsAtText??"").toLowerCase().includes("unavailable"),l=i?(i.getTime()-r)/6e4:null;if(e.active==="on"){let a=Bn(l,i,s);return t==="dump"&&e.exportPowerW!==null&&e.exportPowerW!==void 0&&(a=`${a} \xB7 ${Math.round(e.exportPowerW)} W export`+(e.stopSoc!==null&&e.stopSoc!==void 0?` \xB7 stop ${Math.round(e.stopSoc)}%`:"")),{phase:"active",value:"Active",sub:a,tone:"accent",remainingMin:l,endsAt:i,endTimeUnavailable:s}}if(o==="STARTING")return{phase:"starting",value:"Starting",sub:"Scheduled start in progress",tone:"accent",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(o==="ARMED"){let a=typeof e.scheduleAttrs?.scheduled_start=="string"?e.scheduleAttrs.scheduled_start:null,c=Pt(String(e.scheduleAttrs?.duration_minutes??""));return{phase:"armed",value:"Armed",sub:`Scheduled ${a?a.slice(0,5):"--:--"}`+(c!==null?` \xB7 ${X(c)}`:""),tone:"ok",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}if(o==="FAILED")return{phase:"failed",value:"Failed",sub:"Last scheduled run failed \xB7 see Energy Actions",tone:"alert",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(e.active==="off"){let a=o==="COMPLETED";return{phase:a?"completed":"standby",value:a?"Completed":t==="dump"?"Ready":"Standby",sub:a?"Last scheduled run completed":"No session running",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}return{phase:"unknown",value:"--",sub:"Lease state unavailable",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}function Or(e,r,t){let n={slot:null,startMin:null,endMin:null,minutesToChange:null,value:"--",sub:"Schedule unavailable",tone:"muted"};if(e.length!==6||e.some(s=>s===null))return n;if(t==="off")return{...n,sub:"Schedule invalid",tone:"warn"};let o=e,i=(Math.floor(r)%1440+1440)%1440;for(let s=0;s<6;s++){let l=(o[s]%1440+1440)%1440,a=(o[(s+1)%6]%1440+1440)%1440;if(l<a?i>=l&&i<a:i>=l||i<a){let u=(a-i+1440)%1440;return{slot:s+1,startMin:l,endMin:a,minutesToChange:u,value:`Slot ${s+1}`,sub:`${Et(l)}\u2013${Et(a)} \xB7 ${X(u)} left`,tone:"accent"}}}return{...n,sub:"No slot matches the current time",tone:"warn"}}function Lr(e){return e.getHours()*60+e.getMinutes()}function qe(e){return e.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/^ecco_/,"").replace(/_/g," ")}function Lt(e,r,t){let n=[],o=[],i=[];for(let c of e){let u=(F(t,c)??"").trim().toUpperCase();u==="FAILED"?n.push(qe(c)):u==="DEGRADED"?o.push(qe(c)):u!=="HEALTHY"&&i.push(qe(c))}let s=r.filter(c=>G(F(t,c))==="on").map(qe);if(e.length+r.length===0)return{grade:"UNKNOWN",value:"--",sub:"No health entities configured",tone:"muted",failed:n,degraded:o,unknown:i,attention:s};let a=c=>c.slice(0,2).join(", ")+(c.length>2?` +${c.length-2}`:"");if(n.length>0||s.length>0){let c=[...n,...s];return{grade:"FAILED",value:"Attention",sub:a(c),tone:"alert",failed:n,degraded:o,unknown:i,attention:s}}return o.length>0?{grade:"DEGRADED",value:"Degraded",sub:a(o),tone:"warn",failed:n,degraded:o,unknown:i,attention:s}:i.length===e.length&&e.length>0?{grade:"UNKNOWN",value:"Unknown",sub:"Health entities unavailable",tone:"muted",failed:n,degraded:o,unknown:i,attention:s}:i.length>0?{grade:"HEALTHY",value:"Nominal",sub:`${i.length} unknown: ${a(i)}`,tone:"ok",failed:n,degraded:o,unknown:i,attention:s}:{grade:"HEALTHY",value:"Nominal",sub:`${e.length} subsystems healthy`,tone:"ok",failed:n,degraded:o,unknown:i,attention:s}}function Nr(e,r,t,n,o){let i=null;for(let l of e){if(!l)continue;let a=r[l]?.last_updated;if(!a)continue;let c=Date.parse(a);Number.isFinite(c)&&(i===null||c>i)&&(i=c)}let s=i===null?null:Math.max(0,(n-i)/1e3);return t==="off"?{ageS:s,stale:!0,reason:"telemetry_offline",telemetry:t}:o>0&&s!==null&&s>o?{ageS:s,stale:!0,reason:"age",telemetry:t}:{ageS:s,stale:!1,reason:null,telemetry:t}}function zr(e,r){if(e){let n=typeof e.attributes?.elevation=="number"?e.attributes.elevation:null;if(e.state==="above_horizon")return n!==null&&n<8?"dusk":"day";if(e.state==="below_horizon")return n!==null&&n>-6?"dusk":"night"}let t=r.getHours();return t>=8&&t<18?"day":t>=6&&t<8||t>=18&&t<20?"dusk":"night"}var Ur={bright_summer_day:"00_bright_summer_day.png",soft_clear_day:"01_soft_clear_day.png",misty_morning:"02_misty_morning.png",golden_hour:"03_golden_hour.png",clear_night:"04_clear_night.png",rainy_day:"05_rainy_day.png",storm_night:"06_storm_night.png",winter_clear_day:"07_winter_clear_day.png",christmas_day:"08_christmas_day.png",christmas_night:"09_christmas_night.png"},Dr=Object.keys(Ur);function Vn(e,r){return e===12||e===1&&r<=3}function Wn(e){return e.sunUp!==null?!e.sunUp:e.weather==="clear-night"?!0:e.hour<7||e.hour>=19}function Yn(e){return e.elevation===null||e.elevation<-6||e.elevation>15?!1:e.rising!==null?!e.rising:e.hour>=15}function Hr(e){let r=Wn(e),t=(e.weather??"").toLowerCase();return Vn(e.month,e.day)?r?"christmas_night":"christmas_day":!r&&(t==="snowy"||t==="snowy-rainy")?"winter_clear_day":r&&(t==="lightning"||t==="lightning-rainy"||t==="exceptional")?"storm_night":!r&&(t==="rainy"||t==="pouring")?"rainy_day":!r&&t==="fog"?"misty_morning":Yn(e)?"golden_hour":t==="clear-night"||r&&["sunny","partlycloudy","cloudy","windy",""].includes(t)||r?"clear_night":t==="partlycloudy"?"soft_clear_day":t==="sunny"||t==="windy"||t==="clear"?"bright_summer_day":"soft_clear_day"}function Kr(e,r,t){let n=t?.[r]??Ur[r];return/^(\/|\.|[a-z]+:)/i.test(n)&&t?.[r]?n:(e.endsWith("/")?e:e+"/")+n}function jr(e){return e==="clear_night"||e==="storm_night"||e==="christmas_night"}var be={sun:"M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6",pylon:"M9 22l3-19 3 19M6 22h12M7.2 9h9.6M8.4 14.5h7.2M4 9l3.2 3.5M20 9l-3.2 3.5M5 14.5l3.4 3M19 14.5l-3.4 3",home:"M3.5 11.5L12 4l8.5 7.5M6 10v10h12V10M10 20v-5h4v5",battery:"M7 5.5h10a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 17 21.5H7A1.5 1.5 0 0 1 5.5 20V7A1.5 1.5 0 0 1 7 5.5zM9.5 2.5h5M8.5 13.5h7v5h-7z",clock:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2",plug:"M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v3",target:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",leaf:"M5 19C6 11 11 5 20 4c0 9-5 15-13 15M5 19l7-7",swap:"M4 8h13l-3-3M20 16H7l3 3",heart:"M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",chevron:"M9 6l6 6-6 6",forecast:"M12 6.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v1.6M4.9 4.9l1.2 1.2M19.1 4.9l-1.2 1.2M2 10.5h1.6M20.4 10.5H22M3 19h18M6 22h12",inverter:"M4 5h16v14H4zM8 9h8M8 13h5M16 15.5h.01",alert:"M12 3l10 18H2L12 3zM12 10v5M12 18v.5",moon:"M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"};var f=(...e)=>Array.from({length:Math.floor(e.length/2)},(r,t)=>({x:e[2*t],y:e[2*t+1]})),Ze={canvas:{width:1448,height:1086},perspective:{X:{field:[12.105,-6.495,14.665,9.607,-3.853,4.53],size:[1448,1086]},Y:{field:[-8.448,-2.224,-7.895,.724,-1.106,.985],size:[1448,1086]},Z:{field:[90,0,0,0,0,0],size:[1448,1086]},S_main:{field:[-38.14,-9.444,-5.991,-6.568,-9.7,-4.422],size:[1448,1086]},S_garage:{vp:{x:-820.3,y:-370.7}}},anchors:{main_pv:{x:610,y:335,label:"Array 1 (main roof)"},garage_pv:{x:1140,y:500,label:"Array 2 (garage roof)"},battery_cabinet:{x:150,y:512,label:"Battery cabinet"},inverter:{x:1002,y:624,label:"Inverter"},pylon_light:{x:1319.5,y:89.5,label:"Pylon top light"},house:{x:784,y:594.5,label:"House connection (wall light)"},chimney:{x:952,y:300,label:"Chimney"}},underside:{from:{x:958,y:621.8},to:{x:1010.5,y:642.8}},power:{solarMain:[{x:752.8,y:375},{x:825.4,y:289.9},{x:924,y:312.3},{x:924,y:485.4},{x:1100.5,y:572},{x:1100.5,y:735.5},{x:1050.8,y:749.1},{x:961,y:712.6},{x:1007,y:699.3},{x:1007,y:641.4}],solarGarage:[{x:1299.4,y:503},{x:1323.6,y:513},{x:1118.5,y:566},{x:1118.5,y:735.5},{x:1127.9,y:739.3},{x:1049.6,y:760.8},{x:926.9,y:710.4},{x:991.5,y:691.9},{x:991.5,y:635.2}],battery:[{x:136,y:523.5},{x:167.7,y:535.1},{x:197.7,y:528.5},{x:532,y:654.7},{x:546.6,y:660.2},{x:653.6,y:700.6},{x:702.4,y:719},{x:744.2,y:734.8},{x:775.1,y:746.5},{x:842.7,y:727.2},{x:985.5,y:686.5},{x:985.5,y:632.8}],grid:[{x:1259,y:228.5},{x:970.8,y:290.5},{x:970.8,y:470},{x:936.7,y:478.1},{x:1109.5,y:561.6},{x:1109.5,y:738.5},{x:1049.9,y:754.8},{x:943.8,y:711.4},{x:998.5,y:695.7},{x:998.5,y:638}],home:[{x:978.5,y:630},{x:978.5,y:644},{x:954.5,y:635.2},{x:954.5,y:535.5},{x:931.5,y:528.2},{x:784,y:564},{x:784,y:594.5}]},buried:{battery:[[3,4],[5,6],[7,9]]},cards:{solar:{at:{x:760,y:10},align:"top-right"},grid:{at:{x:1164.5,y:10},align:"top-right"},battery:{at:{x:381,y:1076},align:"bottom-right"},home:{at:{x:1040,y:928},align:"top-left"}},cardsCompact:{solar:{at:{x:757,y:10},align:"top-right"},grid:{at:{x:1248,y:10},align:"top-right"},battery:{at:{x:10,y:1076},align:"bottom-left"},home:{at:{x:1008,y:926},align:"top-left"}},compactFrom:2.8,info:{solarInfoMain:{card:"solar",port:{side:"bottom",at:.55},elbow:["Z","X"],points:[{x:625,y:226},{x:625,y:296}]},solarInfoGarage:{card:"solar",port:{side:"bottom",at:.925},elbow:["Z","X"],points:[{x:1045,y:264.5},{x:1045,y:490}]},batteryInfo:{card:"battery",port:{side:"top",at:.2875,x:127.5},points:[{x:127.5,y:502}]},gridInfo:{card:"grid",port:{side:"right",at:.2725},elbow:["X","Z"],points:[{x:1319.5,y:92.8}]},homeInfo:{card:"home",port:{side:"top",at:.4,x:1131},elbow:["Z","X"],points:[{x:1e3,y:571}]}},bend:{},traces:[{label:"W6 painted service wire (pylon LL insulator -> chimney right edge), Y",points:f(1259,228.5,1239,233.3,1215,240.7,1191,247.7,1167,254.4,1143,260.6,1127,263.7,1103,267,1079,271.9,1055,275.6,1031,278.1,1007,282.2,991,285,971,286)},{label:"W8 painted wire into the chimney (the grid lands at its contact)",points:f(1071,280.4,1047,283.8,1023,286.2,999,288.2,971,291)},{label:"pylon LL insulator, Z",points:f(1259,199.5,1259,229)},{label:"chimney right (back) edge, Z",points:f(970.6,281,970.6,468.5)},{label:"chimney foot on garage roof, Y",points:f(970.6,468.5,935.6,475.5)},{label:"chimney left edge / gable-glazing frame junction, Z",points:f(924,312.3,924,485.4)},{label:"garage front-left verge tile edge, S_garage",points:f(930,475.5,1108,560)},{label:"garage front-left fascia bottom = top of inverter wall, S_garage",points:f(924.4,486.5,1114.9,577.6)},{label:"garage front corner, Z",points:f(1109.5,575.5,1109.5,738.5)},{label:"door-wall eave tile edge / gutter, Y",points:f(1119.5,565.4,1349,506.8)},{label:"corner downpipe (gooseneck + vertical), Z",points:f(1130.3,571.5,1127.5,580.8,1119.5,588,1118.5,592,1118.5,733,1121.5,736)},{label:"ridge-cap underside shadow line, X (Array 1 route to the chimney)",points:f(815,287.5,924,312.3)},{label:"Array 1 right frame edge, S_main",points:f(809.7,306.8,688,446)},{label:"Array 2 frame L-F-R-B",points:f(987.2,481.9,1114.7,544.6,1298.9,499.6,1170.8,445,987.2,481.9)},{label:"inverter wall plinth bottom / paving, X",points:f(968,682.5,1109.5,738.5)},{label:"door wall base (corner to door jamb), Y",points:f(1109.5,738.5,1133,730.8)},{label:"landing riser-1 foot Y3",points:f(834,719.9,962,682.1)},{label:"lower-step nosing Y4 (battery C2 track)",points:f(841,728.3,972,690.3)},{label:"step foot / gravel junction Y5",points:f(841,739.4,975,699.1)},{label:"pot + EV loop front clearance (inner X track reference)",points:f(1009,724,1025,731,1054,739,1068,738.5,1078,735)},{label:"inverter underside front edge = connection bar, X",points:f(958,621.8,1010.5,642.8)},{label:"painted cable C1",points:f(978.5,639,978.5,680,977,683,974,684.2,967,682.5)},{label:"painted cable C2",points:f(985.5,642,985.5,687,984,690.5,980,692.5,975,693.5)},{label:"painted cable C3",points:f(991.5,645,991.5,691,989.5,694.5,984,696,977,696.5)},{label:"painted cable C4",points:f(998.5,648,998.5,693,996.5,697.5,990,699,978,699)},{label:"painted cable C5",points:f(1007,650,1007,692,1005,697.5,1e3,700.5,991,702.5,979,701.5)},{label:"inverter front face, left edge, Z (the home feed runs up beside it)",points:f(957.5,534,957.5,622)},{label:"internal corner, garage wall / house wall, Z (the home feed turns onto the house wall)",points:f(931.5,490,931.5,618)},{label:"upper window bottom edge, Y (top of the home feed's wall band)",points:f(825,538,918,515)},{label:"dining glazing top edge, Y (bottom of the home feed's wall band)",points:f(795,577.5,916,547.5)},{label:"wall light left of the dining glazing (the home feed ends on it)",points:f(784,595.5,784,609.5)},{label:"battery cabinet front-base ground line, Y (battery exit)",points:f(119.5,527,203.5,509)},{label:"rear path / lawn edge, Y (battery lawn turn)",points:f(100,549.5,320,502.5)},{label:"patio slab front riser foot, X (battery, to the patio corner)",points:f(316,573.5,490,638.8)},{label:"tiered planter box A right face (the battery comes out from behind it)",points:f(842,716,842,745)}],obstacles:[{label:"lawn:flowerbed_lower_left",points:f(47,568,55,575,82,577,112,582,130,595,150,602,175,602,200,612,250,625,265,620,290,627.5,315,637.5,340,655,365,667.5,385,662.5,415,662.5,440,652.5,457.5,640,470,636,490,644,503,646,512,650,518,662,532,677,525,684,334,734.6,325,745,245,721,145,686,100,677,67,660,33,647,0,640,0,575,12,572,28,563,42,562)},{label:"foreground:hedge_front_row",points:f(88,668,125,683,250,722,300,747,350,757,450,787,500,804,550,818,600,835,650,855,690,866,698,880,692,935,690,992,88,775)},{label:"foreground:car",points:f(1188,700,1190,672,1197,660,1215,652,1240,645,1300,632,1330,630,1360,634,1395,645,1420,662,1440,680,1448,690,1448,763,1430,768,1360,780,1340,782,1320,780,1305,762,1268,752,1235,735,1215,730,1197,728,1190,715)},{label:"foreground:bedB_front_raised_bed_planting",points:f(694,862,720,856,760,850,790,856,800,866,962,820,980,840,1015,888,706,970,692,962,690,935,692,880)},{label:"front:flowerbed_front",points:f(605,750,612,720,626,700,655,701,690,698,706,727,782,760,810,752,842,756,860,766,900,768,928,790,928,800,721,800)},{label:"lawn:planting_bed_lower_right",points:f(604,752,622,712,640,704,660,702,680,705,700,722,712,730,790,761.5,800,775,800,838,604,754.8)},{label:"foreground:bedA_rear_bed_planting",points:f(605,748,612,712,650,710,705,725,750,742,790,760,830,768,870,772,910,782,966,800,966,806,800,852,785,852,605,752)},{label:"garage:Left pot + plant on top step",points:f(906,628,912,619,922,613,935,612,946,616,953,624,952,633,945,640,945,666,936,671,915,668,914,642,907,637)},{label:"garage:EV charger cable drop + ground loop",points:f(1079,679,1085,679,1086,720,1084,729,1078,735,1068,738.5,1054,739,1046,736.5,1040.5,731,1041,726,1078,726)},{label:"lawn:sofa",points:f(389,549,394,543,430,535,472,528,540,550,548,557,525,587,470,568,440,576,415,587,390,578)},{label:"lawn:hedge_lower_left",points:f(0,640,33,647,67,660,100,677,267,728,345,750,362,760,0,760)},{label:"lawn:planting_house_corner",points:f(355,515,360,500,378,491,437,479,445,485,447,530,430,532,400,540,388,548,383,556,360,548,356,535)},{label:"foreground:ev_charger_and_cable",points:f(1072,634,1096,634,1096,680,1087,684,1087,733,1078,739,1045,739,1040,731,1048,724,1078,726,1078,684,1072,680)},{label:"front:tiered_planters",points:f(746,700,760,692,775,700,815,695,838,712,842,722,841,748,800,750,752,750,745,735,748,715)},{label:"garage:Large pot + plant below-right of inverter",points:f(1008,690,1011,681,1019,674,1030,670,1041,672,1050,680,1053,690,1051,699,1051,725,1025,731,1009,724)},{label:"garage:Shrubs / trees right of and behind garage",points:f(1339.5,620.5,1339.5,521,1356,509,1349,505,1300,486,1250,462,1200,446,1172,435,1165,420,1448,420,1448,652)},{label:"lawn:shrub_left_of_cabinet",points:f(0,458,20,452,38,468,52,490,70,530,70,547,28,563,12,572,0,575)},{label:"front:plant_pot_porch_right",points:f(660,640,668,612,690,605,712,615,726,632,712,655,703,660,703,697,672,697,671,662,658,655)},{label:"front:plant_pots_by_downpipe",points:f(702,672,712,652,732,646,752,660,758,680,752,690,750,715,718,715,717,707,703,707)},{label:"garage:EV charger body",points:f(1072,640,1074,636,1083,634.5,1093,635,1096,638,1096,674,1093,679,1076,679,1072,675)},{label:"garage:Garage door",points:f(1133.4,596.3,1313.7,547,1313,628,1290,636,1247,641,1215,648,1199,657,1192,668,1190,702.3,1134,720.1)},{label:"garage:Raised flowerbed with planting",points:f(840,760,900,768,924,776,944,812,967.5,817.5,967.5,845,985,860,995,900,840,900)},{label:"front:plant_pot_under_dining",points:f(775,668,783,650,800,645,820,652,827,668,816,682,815,708,788,708,787,684)},{label:"garage:Path light 1",points:f(929.5,777,935,774.5,940.5,777,940.5,811,944,812,944,817.5,924,817.5,924,812,929.5,811)},{label:"lawn:rear_fence_bed",points:f(204,410,225,380,440,380,440,461,320,483,318,486.8,205,510.1)},{label:"lawn:pot_P3_conifer_by_house_corner",points:f(380,450,385,420,398,385,410,379,425,395,430,430,428,452,415,466,396,466)},{label:"lawn:pot_P4_patio",points:f(311,545,318,528,335,518,352,522,360,535,356,551,354,573,328,573,325,551)},{label:"lawn:pot_P6_by_porch",points:f(515,590,522,575,540,570,558,580,560,600,547,603,546,627,523,628,521,602)},{label:"lawn:pot_P7_by_porch",points:f(543,612,548,598,560,592,575,600,577,615,573,616,573,640,549,641,547,616)},{label:"front:porch_entrance_glazing",points:f(597.5,506,617,508,664,539,665,674,597.5,648)},{label:"garage:Small plant beside step",points:f(949,663,950,655,954,650,959,650,963,655,963,663,960,670,951,670)},{label:"lawn:pot_P2_right_of_cabinet",points:f(205,470,212,455,228,452,245,460,244,483,241,505,211,506)},{label:"lawn:pot_P5_patio",points:f(357,530,365,518,380,520,386,535,381,566,361,567)},{label:"roof:skylight",points:f(790,381.5,825.5,388.5,776,456.5,740,442.5)},{label:"roof:gable_glazing_upper",points:f(824.5,462.6,915,347.5,915,517,824.5,535.5)},{label:"roof:right_gable_glazing",points:f(971,332.5,1014.5,364.5,1014.5,460,971,468)},{label:"front:raised_bed_left",points:f(520,653,530,655,545,680,561,679,561,703,520,713)},{label:"lawn:pot_P1_left_of_cabinet",points:f(74,500,82,487,98,484,112,490,112,541,80,541)},{label:"foreground:hedge_left_end_top_corner",points:f(0,640,20,640,32,646,30,660,20,676,0,679)},{label:"front:dining_glazing",points:f(795,577.5,916,547.5,916,659.5,795,694)},{label:"front:bollard_left",points:f(533,642,545,642,546,670,549,679,531,680,533,670)},{label:"front:bollard_mid",points:f(688,686,698,686,698,712,700,718,686,718,688,712)},{label:"front:bollard_steps",points:f(829,734,838,734,838,750,840,756,827,756,829,750)},{label:"lawn:coffee_table",points:f(430.5,576,466,571.5,494,583,493,600,465,606,431,594)},{label:"roof:wall_light_front_left",points:f(452,464,456,463.5,459,465,459,473,451.5,473)},{label:"roof:wall_light_gable_by_corner",points:f(780.5,597,784,595.5,787.5,597,787.5,608,784,609.5,780.5,608)},{label:"front:first_floor_window",points:f(825,464,853,420,916,420,918,515,825,538)},{label:"garage:Path light on right garden wall",points:f(1394.5,615,1398,612,1402,614,1402.5,637,1395,637)},{label:"garage:Path light 2",points:f(983,854,988.5,852,994,854,995,895,982,895)},{label:"foreground:path_light_PL_a",points:f(135,666,146,666,146,691,135,691)},{label:"foreground:path_light_PL_b",points:f(325,724,335,724,335,749,325,749)},{label:"foreground:path_light_PL_g",points:f(693,864,704,864,704,897,693,897)},{label:"foreground:path_light_PL_h",points:f(756,925,770,925,770,956,756,956)},{label:"front:porch_lamp_left",points:f(583,552,591,552,591,568,583,568)},{label:"front:porch_lamp_right",points:f(671,575,679,575,679,591,671,591)},{label:"front:mini_downlight",points:f(733.5,626,739.5,626,739.5,632.5,733.5,632.5)},{label:"garage:Patio glazing, right part",points:f(880,557.2,915.5,548.5,915.5,661,880,668)},{label:"garage:Upper window, right part",points:f(880,427,914.5,420,914.5,517,880,523.5)},{label:"lawn:path_light_PL1",points:f(74,522,83,522,83,550,74,550)},{label:"lawn:path_light_PL2",points:f(245,467,252.5,467,252.5,500,245,500)},{label:"lawn:path_light_PL3",points:f(358,448,364.5,448,364.5,474,358,474)},{label:"lawn:path_light_PL6",points:f(533,642,543,642,543,679,533,679)},{label:"lawn:path_light_PL7",points:f(689,686,697.5,686,697.5,717.5,689,717.5)},{label:"lawn:patio_glazing_approx",points:f(477,452,575,497,575,585,477,548)},{label:"lawn:porch_door",points:f(602,508,641,525,641,664,605,649)},{label:"lawn:porch_side_glazing",points:f(641,525,665,538,665,674,641,664)},{label:"lawn:white_wall_glazing_approx",points:f(795,568,820,560,820,678,795,688)}],equipment:[{label:"Array 1",x:478,y:256,w:334,h:192},{label:"Array 2",x:985,y:443,w:316,h:112},{label:"Battery cabinet",x:93,y:393,w:114,h:134},{label:"Inverter",x:954,y:526,w:72,h:124},{label:"Pylon",x:1252,y:84,w:136,h:348},{label:"Chimney",x:905,y:256,w:72,h:222},{label:"EV charger",x:1066,y:626,w:34,h:60},{label:"Car",x:1183,y:622,w:265,h:165}],nodes:{solarMain:["array1_right_frame_outer_side_at_row_divider_junction","ridge_cap_underside_above_array1_TR_corner","ridge_end_at_chimney_left_edge (roof top-right corner)","garage_fascia_bottom_left_end","garage_fascia_bottom_at_garage_outer_end","inverter_wall_base_beside_garage_corner","ground_turn_onto_inner_X_track","bundle_turn_into_C5_track","C5_riser_base","C5_gland_on_underside_edge"],solarGarage:["array2_frame_R_corner","eave_gutter_below_R","eave_gutter_at_downpipe_head_roof_front_corner","downpipe_foot","downpipe_shoe_kick","ground_turn_onto_outer_X_track","bundle_turn_into_C3_track_at_step_foot","C3_riser_base","C3_gland_on_underside_edge"],battery:["cabinet_exit_front_base_below_status_strip","rear_path_lawn_edge_turn","patio_riser_foot_line_on_lawn_edge","behind bollard_left, path_light_PL6 (hidden from here)","open paving (drawn from here)","behind bollard_mid, flowerbed_front, path_light_PL7, planting_bed_lower_right (hidden from here)","open paving (drawn from here)","behind tiered_planters (hidden from here)","corner under the tiered planters (hidden)","lower-step nosing past planter box A (drawn to the inverter)","C2_riser_base","C2_gland_on_underside_edge"],grid:["pylon_LL_insulator_bottom (W6 attachment)","chimney_right_edge_below_cap (W8 contact; W6 contact 4.5 px above)","chimney_right_edge_foot_on_garage_roof","chimney_front_foot_on_verge_tile_edge","verge_tile_edge_above_garage_front_corner","garage_front_corner_base","ground_turn_onto_middle_X_track","bundle_turn_into_C4_track_at_step_foot","C4_riser_base","C4_gland_on_underside_edge"],home:["C1_gland_on_underside_edge","C1_drop_below_gland","turn_under_inverter_bottom_left_corner","inverter_left_side_at_top (turn into the corner)","internal_corner_garage_wall_house_wall","house_wall_band_above_wall_light","wall_light_top (home end)"]}},Ie=e=>!!e&&Number.isFinite(e.x)&&Number.isFinite(e.y),Nt=(e,r)=>Array.isArray(e)&&e.length>=r&&e.every(Ie)?e.map(t=>({x:t.x,y:t.y})):null,D=e=>!!e&&typeof e=="object"&&!Array.isArray(e),ne=e=>typeof e=="number"&&Number.isFinite(e),V=(e,r)=>typeof r=="string"&&Object.prototype.hasOwnProperty.call(e,r),qn=["top-left","top-right","bottom-left","bottom-right","top-center","bottom-center"],Xn=["top","bottom","left","right"],Gr=(e,r)=>{if(!Array.isArray(e))return null;let t=[];for(let n of e){let o=D(n)&&typeof n.label=="string"?Nt(n.points,r):null;if(!o)return null;t.push({label:n.label,points:o})}return t};function Br(e,r){if(!D(r))return e;let t={...e.anchors};for(let[h,p]of Object.entries(D(r.anchors)?r.anchors:{}))!D(p)||!V(t,h)||(t[h]={x:ne(p.x)?p.x:t[h].x,y:ne(p.y)?p.y:t[h].y,label:typeof p.label=="string"?p.label:t[h].label});let n={...e.perspective};for(let[h,p]of Object.entries(D(r.perspective)?r.perspective:{})){if(h==="__proto__")continue;let g=p;g&&Ie(g.vp)?n[h]={vp:{x:g.vp.x,y:g.vp.y}}:g&&Array.isArray(g.field)&&g.field.length===6&&g.field.every(Number.isFinite)&&Array.isArray(g.size)&&g.size.length===2&&g.size.every(A=>Number.isFinite(A)&&A>0)&&(n[h]={field:[...g.field],size:[g.size[0],g.size[1]]})}let o={...e.power};for(let[h,p]of Object.entries(D(r.power)?r.power:{})){let g=Nt(p,2);g&&V(o,h)&&(o[h]=g)}let i={...e.buried};for(let h of Object.keys(i))o[h]!==e.power[h]&&delete i[h];let s=h=>Array.isArray(h)&&h.length===2&&h.every(Number.isInteger)&&h[0]>=0&&h[0]<h[1];for(let[h,p]of Object.entries(D(r.buried)?r.buried:{}))Array.isArray(p)&&V(o,h)&&(i[h]=p.filter(s).map(([g,A])=>[g,A]));let l=(h,p)=>{let g={...h};for(let[A,P]of Object.entries(D(p)?p:{})){if(!D(P)||!V(e.cards,A))continue;let M=g[A]??e.cards[A];g[A]={at:Ie(P.at)?{x:P.at.x,y:P.at.y}:M.at,align:qn.includes(P.align)?P.align:M.align}}return g},a={...e.info};for(let[h,p]of Object.entries(D(r.info)?r.info:{})){if(!D(p)||!V(a,h))continue;let g=a[h],A={...g.port};if(D(p.port)){let _=Xn.includes(p.port.side)?p.port.side:g.port.side,E=_!==g.port.side||ne(p.port.at);A.side=_,ne(p.port.at)&&(A.at=p.port.at);for(let k of["x","y"])ne(p.port[k])?A[k]=p.port[k]:(p.port[k]===null||E&&p.port[k]===void 0)&&delete A[k]}let P=Array.isArray(p.elbow)&&p.elbow.length===2&&p.elbow.every(_=>V(n,_))&&p.elbow[0]!==p.elbow[1]?[p.elbow[0],p.elbow[1]]:null,M=p.elbow===null?void 0:P??g.elbow;a[h]={card:V(e.cards,p.card)?p.card:g.card,port:A,...M?{elbow:M}:{},points:p.points===void 0?g.points:Nt(p.points,1)??g.points}}let c={...e.bend};for(let[h,p]of Object.entries(D(r.bend)?r.bend:{}))(V(e.power,h)||V(e.info,h))&&ne(p)&&p>=0&&(c[h]=p);let u={...e.nodes};for(let[h,p]of Object.entries(D(r.nodes)?r.nodes:{}))V(u,h)&&Array.isArray(p)&&p.every(g=>typeof g=="string")&&(u[h]=[...p]);let d=D(r.underside)?r.underside:{},m=Array.isArray(r.equipment)&&r.equipment.every(h=>D(h)&&typeof h.label=="string"&&["x","y","w","h"].every(p=>ne(h[p])))?r.equipment.map(h=>({label:h.label,x:h.x,y:h.y,w:h.w,h:h.h})):e.equipment;return{canvas:e.canvas,perspective:n,anchors:t,underside:{from:Ie(d.from)?{x:d.from.x,y:d.from.y}:e.underside.from,to:Ie(d.to)?{x:d.to.x,y:d.to.y}:e.underside.to},power:o,buried:i,cards:l(e.cards,r.cards),cardsCompact:l(e.cardsCompact,r.cardsCompact),compactFrom:ne(r.compactFrom)?r.compactFrom:e.compactFrom,info:a,bend:c,traces:Gr(r.traces,2)??e.traces,obstacles:Gr(r.obstacles,3)??e.obstacles,equipment:m,nodes:u}}var Fe=Math.PI/180;function Qe(e,r){let t;if("vp"in e)t=Math.atan2(e.vp.y-r.y,e.vp.x-r.x)/Fe;else{let[n=0,o=0,i=0,s=0,l=0,a=0]=e.field,c=r.x/e.size[0],u=r.y/e.size[1];t=n+o*c+i*u+s*c*u+l*c*c+a*u*u}for(;t<=-90;)t+=180;for(;t>90;)t-=180;return t}function Vr(e,r,t,n){let o={x:Math.cos(r*Fe),y:Math.sin(r*Fe)},i={x:Math.cos(n*Fe),y:Math.sin(n*Fe)},s=o.x*i.y-o.y*i.x;if(Math.abs(s)<1e-9)return null;let l=((t.x-e.x)*i.y-(t.y-e.y)*i.x)/s;return{x:e.x+o.x*l,y:e.y+o.y*l}}function Wr(e,r,t,n,o){let i=o[r],s=o[n];if(!i||!s)return{x:t.x,y:t.y};let l=Vr(e,Qe(i,e),t,Qe(s,t));for(let a=0;a<8&&l;a++){let c=Vr(e,Qe(i,{x:(e.x+l.x)/2,y:(e.y+l.y)/2}),t,Qe(s,{x:(t.x+l.x)/2,y:(t.y+l.y)/2}));if(!c)break;let u=Math.hypot(c.x-l.x,c.y-l.y);if(l=c,u<.01)break}return l??{x:t.x,y:t.y}}var nt=400,zt=470,Ut=13,Zn=.866*Ut,Qn=.5*Ut,Jn=205,eo=262;function b(e,r,t=0){return{x:Jn+(e-r)*Zn,y:eo+(e+r)*Qn-t*Ut}}function O(e){return e.map(r=>`${r.x.toFixed(1)},${r.y.toFixed(1)}`).join(" ")}function Oe(e,r,t,n,o,i){return{top:O([b(e,r,i),b(t,r,i),b(t,n,i),b(e,n,i)]),left:O([b(e,n,o),b(t,n,o),b(t,n,i),b(e,n,i)]),right:O([b(t,r,o),b(t,n,o),b(t,n,i),b(t,r,i)])}}function W(e,r,t,n,o){return O([b(r,e,n),b(t,e,n),b(t,e,o),b(r,e,o)])}function Dt(e,r,t,n,o){return O([b(e,r,n),b(e,t,n),b(e,t,o),b(e,r,o)])}function _e(e,r,t,n,o,i){return b(e,t+(o-t)*r,n+(i-n)*r)}function Je(e){if(e.length<4)return"";let r=`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)}`;for(let t=1;t+2<e.length;t+=3){let n=e[t],o=e[t+1],i=e[t+2];r+=` C ${n.x.toFixed(1)} ${n.y.toFixed(1)}, ${o.x.toFixed(1)} ${o.y.toFixed(1)}, ${i.x.toFixed(1)} ${i.y.toFixed(1)}`}return r}var oe={x0:-1,y0:-3,x1:7,y1:3,z:4.2,ridgeZ:6.6,ridgeY:0},Xr={x0:7,y0:-1,x1:11,y1:3,z:2.5},xe={x0:-6.2,y0:4.2,x1:-4.6,y1:5.4,z:2.4},ue={x0:5.3,x1:6.3,z0:1.25,z1:2.45,y:oe.y1},Z=b(10.6,-4.8),Ht=(()=>{let e=b((ue.x0+ue.x1)/2,ue.y,(ue.z0+ue.z1)/2);return{x:e.x+1,y:e.y+2}})(),ie={solar:{x:8,y:10,w:150,h:58,port:{x:58,y:68}},grid:{x:246,y:22,w:146,h:58,port:{x:330,y:80}},home:{x:214,y:176,w:140,h:54,port:{x:236,y:230}},battery:{x:8,y:388,w:184,h:70,port:{x:108,y:388}}};var we=["solarMain","solarGarage","battery","grid","home"],Yr=["solarInfoMain","solarInfoGarage","batteryInfo","gridInfo","homeInfo"],to=["solar","grid","battery","home"],qr={solar:{w:150,h:58},grid:{w:150,h:58},battery:{w:192,h:72},home:{w:140,h:54}},et=10;function tt(e,r=3){if(e.length<2)return"";let t=s=>`${s.x.toFixed(1)} ${s.y.toFixed(1)}`,n=(s,l)=>Math.hypot(l.x-s.x,l.y-s.y),o=(s,l,a)=>{let c=n(s,l)||1;return{x:s.x+(l.x-s.x)*a/c,y:s.y+(l.y-s.y)*a/c}},i=`M ${t(e[0])}`;for(let s=1;s<e.length-1;s++){let l=e[s-1],a=e[s],c=e[s+1],u=Math.min(r,n(l,a)*.3,n(a,c)*.3);i+=` L ${t(o(a,l,u))} Q ${t(a)} ${t(o(a,c,u))}`}return i+=` L ${t(e[e.length-1])}`,i}function ro(e,r=[],t=3){let n=e.length-1,o=[],i=[],s=0;for(let[l,a]of[...r].sort((c,u)=>c[0]-u[0]))l<s||a>n||l>=a||(l>s&&o.push(tt(e.slice(s,l+1),t)),i.push(tt(e.slice(l,a+1),t)),s=a);return s<n&&o.push(tt(e.slice(s),t)),{drawn:o.join(" "),buried:i.join(" ")}}var ki=Ze.anchors,Ai=Ze.perspective;function no(e,r,t,n){let o=e.align.endsWith("left")?e.at.x:e.align.endsWith("right")?e.at.x-r:e.at.x-r/2,i=e.align.startsWith("top")?e.at.y:e.at.y-t;return{x:Math.max(et,Math.min(n.width-et-r,o)),y:Math.max(et,Math.min(n.height-et-t,i))}}function oo(e,r){let t=Math.max(0,Math.min(1,r.at)),n=(o,i,s)=>Number.isFinite(o)?Math.max(i,Math.min(i+s,o)):i+s*t;return r.side==="top"?{x:n(r.x,e.x,e.w),y:e.y}:r.side==="bottom"?{x:n(r.x,e.x,e.w),y:e.y+e.h}:r.side==="left"?{x:e.x,y:n(r.y,e.y,e.h)}:{x:e.x+e.w,y:n(r.y,e.y,e.h)}}function ot(e,r){let t=Br(Ze,r),n=e>=t.compactFrom,o={};for(let a of to){let c=qr[a].w*e,u=qr[a].h*e,{x:d,y:m}=no(n&&t.cardsCompact[a]||t.cards[a],c,u,t.canvas);o[a]={x:d,y:m,w:c,h:u,port:{x:d+c/2,y:m+u/2}}}let i={},s=new Set;for(let a of Yr){let c=t.info[a],u=o[c.card],d=oo(u,c.port);s.has(c.card)||(u.port=d,s.add(c.card));let m=[d];c.elbow&&c.points.length&&m.push(Wr(d,c.elbow[0],c.points[0],c.elbow[1],t.perspective)),m.push(...c.points),i[a]=m}for(let a of we)i[a]=t.power[a];let l=t.underside;return{width:t.canvas.width,height:t.canvas.height,scale:e,pills:o,inverter:{x:(l.from.x+l.to.x)/2,y:(l.from.y+l.to.y)/2},underside:l,anchors:t.anchors,routes:i,bend:t.bend,buried:t.buried,paths:()=>Object.fromEntries(Object.keys(i).map(a=>{let c=Yr.includes(a)?[...i[a]].reverse():i[a];return[a,tt(c,t.bend[a]??3)]})),spans:()=>Object.fromEntries(we.map(a=>[a,ro(i[a],t.buried[a],t.bend[a]??3)])),routing:t}}function Zr(e,r){let t=e.paths()[r],n=e.spans()[r];return n.buried?{track:t,drawn:n.drawn,duct:n.buried}:{track:t,drawn:t,duct:""}}function Qr(e){return e<520?3.2:e<760?2.8:e<1100?2.3:2}var Si=ot(2);function Jr(){let e=Ht,r=_e(.2,.08,oe.y1,oe.z,oe.ridgeY,oe.ridgeZ),t=Je([ie.solar.port,{x:58,y:120},{x:150,y:150},r,{x:r.x+16,y:r.y+20},{x:e.x-24,y:e.y-26},e]),n=b(xe.x1,(xe.y0+xe.y1)/2,xe.z*.72),o=Je([{x:n.x+2,y:n.y},{x:n.x+40,y:n.y-2},{x:e.x-60,y:e.y+28},{x:e.x-24,y:e.y+24},{x:e.x-10,y:e.y+22},{x:e.x-4,y:e.y+12},e]),i={x:Z.x-4,y:Z.y-118},s=Je([ie.grid.port,{x:330,y:112},{x:i.x-30,y:i.y+10},{x:i.x-22,y:i.y+44},{x:i.x-14,y:Z.y-6},{x:Z.x-30,y:Z.y+30},{x:300,y:Z.y+40},{x:272,y:Z.y+36},{x:e.x+10,y:e.y+24},e]),l=Je([e,{x:e.x+10,y:e.y-24},{x:e.x-12,y:e.y-48},ie.home.port]);return{solar:t,battery:o,grid:s,home:l}}var io=15,N={solar:"#f7c948",battery:"#35e08a",grid:"#3ea6ff",home:"#22d3ee"};function en(e,r,t,n,o){let i=n/24;return $`<g transform="translate(${r} ${t}) scale(${i})" fill="none" stroke=${o} stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d=${be[e]}></path></g>`}function so(){let e=[b(-8,-6),b(10,-6),b(10,10),b(-8,10)],r=12,t=[e[3],e[2],{x:e[2].x,y:e[2].y+r},{x:e[3].x,y:e[3].y+r}],n=[e[2],e[1],{x:e[1].x,y:e[1].y+r},{x:e[2].x,y:e[2].y+r}],o=[b(8.2,3.05),b(10.6,3.05),b(10.6,10),b(8.2,10)],i=[b(2.2,3.05),b(3.2,3.05),b(3.2,5.6),b(-4.2,5.6),b(-4.2,4.6),b(2.2,4.6)];return $`
    <g class="ground">
      <polygon points=${O(t)} class="ground-side"></polygon>
      <polygon points=${O(n)} class="ground-side ground-side-r"></polygon>
      <polygon points=${O(e)} class="ground-top"></polygon>
      <polygon points=${O(e)} fill="url(#ef3d-ground-sheen)"></polygon>
      <polygon points=${O(o)} class="drive"></polygon>
      <polygon points=${O(i)} class="drive path"></polygon>
      ${ao()}
    </g>`}function ao(){let e=[];for(let r=0;r<6;r++){let t=-5+r*2.6;e.push($`<polygon points=${O([b(-7.6,t),b(-1.6,t),b(-1.6,t+1.3),b(-7.6,t+1.3)])} class="lawn-stripe"></polygon>`)}return e}function it(e,r,t,n=""){let o=b(e,r);return $`
    <g class="tree ${n}">
      <ellipse cx=${o.x} cy=${o.y+2} rx=${t*.9} ry=${t*.38} class="tree-shadow"></ellipse>
      <rect x=${o.x-1.4} y=${o.y-t*1.1} width="2.8" height=${t*1.1} class="trunk"></rect>
      <circle cx=${o.x-t*.35} cy=${o.y-t*1.15} r=${t*.78} class="canopy c2"></circle>
      <circle cx=${o.x+t*.4} cy=${o.y-t*1.25} r=${t*.82} class="canopy c3"></circle>
      <circle cx=${o.x} cy=${o.y-t*1.7} r=${t*.86} class="canopy c1"></circle>
    </g>`}function $e(e,r,t){let n=b(e,r);return $`<g class="shrub"><ellipse cx=${n.x} cy=${n.y} rx=${t} ry=${t*.62} class="canopy c2"></ellipse><ellipse cx=${n.x-t*.4} cy=${n.y-t*.25} rx=${t*.7} ry=${t*.45} class="canopy c1"></ellipse></g>`}function Kt(e,r){let t=b(e,r);return $`<g class="lamp"><line x1=${t.x} y1=${t.y} x2=${t.x} y2=${t.y-9} class="lamp-post"></line><circle cx=${t.x} cy=${t.y-10} r="2.2" class="lamp-light"></circle><circle cx=${t.x} cy=${t.y-10} r="6" class="lamp-halo"></circle></g>`}function lo(){let e=oe,r=Oe(e.x0,e.y0,e.x1,e.y1,0,e.z),t=[b(e.x0-.5,e.y1+.5,e.z-.25),b(e.x1+.5,e.y1+.5,e.z-.25),b(e.x1+.5,e.ridgeY,e.ridgeZ),b(e.x0-.5,e.ridgeY,e.ridgeZ)],n=[b(e.x0-.5,e.y0-.5,e.z-.25),b(e.x1+.5,e.y0-.5,e.z-.25),b(e.x1+.5,e.ridgeY,e.ridgeZ),b(e.x0-.5,e.ridgeY,e.ridgeZ)],o=[b(e.x1,e.y0,e.z),b(e.x1,e.y1,e.z),b(e.x1,e.ridgeY,e.ridgeZ)],i=[b(e.x1+.5,e.y1+.5,e.z-.25),b(e.x1+.5,e.y1+.5,e.z-.55),b(e.x1+.5,e.ridgeY,e.ridgeZ-.3),b(e.x1+.5,e.ridgeY,e.ridgeZ)],s=Xr,l=Oe(s.x0,s.y0,s.x1,s.y1,0,s.z),a=Oe(s.x0-.15,s.y0-.15,s.x1+.15,s.y1+.15,s.z,s.z+.18);return $`
    <g class="house">
      <!-- soft contact shadow -->
      <polygon points=${O([b(e.x0-.6,e.y0-.2),b(s.x1+.9,s.y0-.2),b(s.x1+.9,s.y1+.9),b(e.x0-.6,e.y1+.9)])} class="contact-shadow"></polygon>
      <!-- garage (behind the house's right face order-wise it sits in front, draw after walls) -->
      <polygon points=${r.right} class="wall wall-r"></polygon>
      <polygon points=${O(o)} class="wall wall-r gable"></polygon>
      <polygon points=${r.left} class="wall wall-l"></polygon>
      <!-- windows and door on the front-left wall -->
      <polygon points=${W(e.y1+.02,.2,1.6,1.5,3.2)} class="window"></polygon>
      <polygon points=${W(e.y1+.02,2,3.4,1.5,3.2)} class="window"></polygon>
      <polygon points=${W(e.y1+.02,.2,1.6,.4,1.1)} class="window small"></polygon>
      <polygon points=${W(e.y1+.02,2.3,3.1,0,1.15)} class="door"></polygon>
      <polygon points=${W(e.y1+.02,3.9,4.8,1.5,3.2)} class="window"></polygon>
      <!-- windows on the right wall -->
      <polygon points=${Dt(e.x1+.02,-2.4,-1.2,1.5,3.2)} class="window"></polygon>
      <polygon points=${Dt(e.x1+.02,-2.4,-1.2,.3,1.1)} class="window small"></polygon>
      <!-- garage -->
      <polygon points=${l.right} class="wall wall-r"></polygon>
      <polygon points=${l.left} class="wall wall-l"></polygon>
      <polygon points=${W(s.y1+.02,7.6,10.4,0,1.9)} class="garage-door"></polygon>
      ${[.45,.9,1.35].map(c=>$`<polyline points=${O([b(7.6,s.y1+.03,c),b(10.4,s.y1+.03,c)])} class="garage-line"></polyline>`)}
      <polygon points=${l.top} class="roof-flat"></polygon>
      <polygon points=${a.left} class="roof-lip"></polygon>
      <polygon points=${a.right} class="roof-lip"></polygon>
      <polygon points=${a.top} class="roof-flat-top"></polygon>
      <!-- roof -->
      <polygon points=${O(n)} class="roof roof-back"></polygon>
      <polygon points=${O(t)} class="roof roof-front"></polygon>
      <polygon points=${O(i)} class="fascia"></polygon>
      <polyline points=${O([b(e.x0-.5,e.ridgeY,e.ridgeZ),b(e.x1+.5,e.ridgeY,e.ridgeZ)])} class="ridge"></polyline>
      ${co()}
      ${uo()}
    </g>`}function co(){let e=oe,r=[],t=5,n=2,o=e.x0+.25,i=e.x1-.75,s=.14,l=(i-o-s*(t-1))/t,a=.16,c=.9,u=.05,d=(c-a-u*(n-1))/n;for(let m=0;m<n;m++)for(let h=0;h<t;h++){let p=o+h*(l+s),g=p+l,A=a+m*(d+u),P=A+d,_=[_e(p,A,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),_e(g,A,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),_e(g,P,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),_e(p,P,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ)].map(k=>({x:k.x,y:k.y-1.2}));r.push($`<polygon points=${O(_)} class="pv"></polygon>`),r.push($`<polygon points=${O(_)} fill="url(#ef3d-pv-glare)" class="pv-glare"></polygon>`);let E=(k,S,T)=>({x:k.x+(S.x-k.x)*T,y:k.y+(S.y-k.y)*T});for(let k of[1/3,2/3])r.push($`<line x1=${E(_[0],_[3],k).x} y1=${E(_[0],_[3],k).y} x2=${E(_[1],_[2],k).x} y2=${E(_[1],_[2],k).y} class="pv-line"></line>`),r.push($`<line x1=${E(_[0],_[1],k).x} y1=${E(_[0],_[1],k).y} x2=${E(_[3],_[2],k).x} y2=${E(_[3],_[2],k).y} class="pv-line"></line>`)}return r}function uo(){let e=ue,r=W(e.y+.03,e.x0,e.x1,e.z0,e.z1),t=b(e.x1-.18,e.y+.05,e.z1-.22),n=o=>O([b(e.x0+.18,e.y+.05,o),b(e.x1-.18,e.y+.05,o)]);return $`
    <g class="inverter">
      <polygon points=${r} class="inverter-face"></polygon>
      <polyline points=${n(e.z0+.3)} class="inverter-vent"></polyline>
      <polyline points=${n(e.z0+.5)} class="inverter-vent"></polyline>
      <circle cx=${t.x} cy=${t.y} r="1.6" class="inverter-led"></circle>
      <circle cx=${t.x} cy=${t.y} r="4" class="inverter-led-halo"></circle>
    </g>`}function po(e){let r=xe,t=Oe(r.x0,r.y0,r.x1,r.y1,0,r.z),n=r.x0+.18,o=.16,i=.3,s=r.z-.3,l=e===null?i:i+Math.max(0,Math.min(100,e))/100*(s-i),a=b((r.x0+r.x1)/2+.15,r.y1+.04,r.z*.56);return $`
    <g class="battery-cabinet">
      <ellipse cx=${b((r.x0+r.x1)/2,(r.y0+r.y1)/2).x} cy=${b((r.x0+r.x1)/2,(r.y0+r.y1)/2).y+3} rx="20" ry="7" class="contact-shadow soft"></ellipse>
      <polygon points=${t.right} class="cab cab-r"></polygon>
      <polygon points=${t.left} class="cab cab-l"></polygon>
      <polygon points=${t.top} class="cab cab-t"></polygon>
      <polygon points=${W(r.y1+.03,n,n+o,i,s)} class="cab-strip-bg"></polygon>
      ${e===null?w:$`<polygon points=${W(r.y1+.04,n,n+o,i,l)} class="cab-strip"></polygon>`}
      <text x="0" y="0" class="cab-label" transform=${`matrix(0.866 0.5 0 1 ${a.x.toFixed(1)} ${a.y.toFixed(1)})`}>ECCO</text>
    </g>`}function fo(e,r){let t=Z,n=118,o={x:t.x-4,y:t.y-n},i=18,s=(u,d)=>$`<line x1=${t.x-4-d} y1=${u} x2=${t.x-4+d} y2=${u} class="pylon-line"></line>`,l=$`
    <line x1=${t.x-i} y1=${t.y} x2=${o.x-2} y2=${o.y} class="pylon-line"></line>
    <line x1=${t.x+i-8} y1=${t.y} x2=${o.x+2} y2=${o.y} class="pylon-line"></line>
    <line x1=${t.x-i+5} y1=${t.y-2} x2=${o.x} y2=${o.y+4} class="pylon-line thin"></line>
    <line x1=${t.x+i-12} y1=${t.y-2} x2=${o.x} y2=${o.y+4} class="pylon-line thin"></line>`,a=[];for(let u=1;u<7;u++){let d=t.y-n/7*u,m=(i-8)*(1-u/8)+3;a.push($`<line x1=${t.x-4-m} y1=${d} x2=${t.x-4+m} y2=${d-6} class="pylon-line thin"></line>`),a.push($`<line x1=${t.x-4+m} y1=${d} x2=${t.x-4-m} y2=${d-6} class="pylon-line thin"></line>`)}let c=[o.y+24,o.y+44].map(u=>$`<path d=${`M ${(t.x-4-26).toFixed(1)} ${u} Q ${(t.x+30).toFixed(1)} ${u+18} ${nt+10} ${u-12}`} class="wire"></path>`);return $`
    <g class=${`pylon ${e?"live":""} ${r?"unknown":""}`}>
      ${l}${a}
      ${s(o.y+22,26)}${s(o.y+42,20)}
      ${c}
      <circle cx=${o.x} cy=${o.y-2} r="3" class="pylon-tip"></circle>
    </g>`}var nn=(e,r)=>(2.3+e*1.2)*r;function on(e,r,t,n,o,i,s,l){return $`
    <g class="pulse" data-path=${e} data-duration=${r.toFixed(3)} data-phase=${t.toFixed(3)} data-reversed=${n?"1":"0"} style=${`--pulse-colour:${o}`}>
      <circle r=${(i*s).toFixed(2)} class="pulse-halo"></circle>
      ${l?$`<circle r=${(i*1.32).toFixed(2)} class="pulse-case"></circle>`:w}
      <circle r=${i.toFixed(2)} class="pulse-glow"></circle>
      <circle r=${(i*.45).toFixed(2)} class="pulse-core"></circle>
    </g>`}function sn(e,r,t,n,o){return $`<g class="chevron" data-path=${e} data-phase=${r} data-reversed=${t?"1":"0"} style=${`--pulse-colour:${n}`}><path d="M -4 -4 L 2 0 L -4 4" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" transform=${`scale(${o})`}></path></g>`}function Ne(e,r,t,n,o,i=1,s=0,l="",a=t,c=""){let{edge:u,motion:d}=n,m=N[e],h=i>1,p=`flow flow-${e} route-${r} ${h?"fine":""} ${u.unknown?"unknown":""} ${u.idle?"idle":""} ${d.moving&&o?"moving":""} ${u.reversed?"reversed":""}`,g=`ef3d-path-${r}`,A=h&&s>0?Math.max(1,Math.round(s/1e3)):1,P=d.ballCount*A,M=d.intensity,_=[];if(d.moving&&o){let y=h?nn(M,i):d.ballRadiusPx,x=h&&s>0?At(d,s):d.ballDurationS;for(let v=0;v<P;v++)_.push(on(g,x,v/P,u.reversed,m,y,h?2.6:1.9,h))}let E=[],k=a!==t?`${g}-drawn`:g;if(d.moving&&!o)for(let y of[.3,.55,.8])E.push(sn(k,y,u.reversed,m,i));if(h){let y=(.95+M*.35)*i,x=(3.4+M*2)*i,v=d.moving?.1+M*.16:0,C=d.moving?.3+M*.3:0,H=d.moving?.45+M*.3:.25,j=`stroke-width:${(.6*i).toFixed(2)}; opacity:${C.toFixed(2)}`;return a!==t?$`
      <g class=${p} style=${`--flow-colour:${m}`}>
        <path d=${a} class="fine-base" style=${`stroke-width:${y.toFixed(2)}`}></path>
        <path d=${a} class="fine-glow" style=${`stroke-width:${x.toFixed(2)}; opacity:${v.toFixed(2)}`}></path>
        <path d=${a} class="fine-highlight" style=${j}></path>
        <path id=${g} d=${t} class="fine-track"></path>
        <path id=${k} d=${a} class="fine-track"></path>
        ${l?$`<path d=${l} class="fine-riser" style=${`stroke-width:${(.95*i).toFixed(2)}; opacity:${H.toFixed(2)}`}></path>`:w}
        <g mask=${c?`url(#${c})`:w}>${_}</g>
        ${E}
      </g>`:$`
      <g class=${p} style=${`--flow-colour:${m}`}>
        <path d=${t} class="fine-base" style=${`stroke-width:${y.toFixed(2)}`}></path>
        <path d=${t} class="fine-glow" style=${`stroke-width:${x.toFixed(2)}; opacity:${v.toFixed(2)}`}></path>
        <path id=${g} d=${t} class="fine-highlight" style=${j}></path>
        ${l?$`<path d=${l} class="fine-riser" style=${`stroke-width:${(.95*i).toFixed(2)}; opacity:${H.toFixed(2)}`}></path>`:w}
        ${_}${E}
      </g>`}let S=d.moving?`stroke-dasharray:${d.dashLen.toFixed(1)} ${d.gapLen.toFixed(1)}; animation-duration:${d.dashDurationS.toFixed(2)}s; stroke-width:${d.packetWidthPx.toFixed(2)}; opacity:${d.packetOpacity.toFixed(2)}; --dash-travel:${(-2*io).toFixed(1)}`:"",T=d.moving?`stroke-width:${(d.packetWidthPx*2.6).toFixed(1)}; opacity:${(.18+d.intensity*.3).toFixed(2)}`:"";return $`
    <g class=${p} style=${`--flow-colour:${m}`}>
      <path d=${t} class="flow-base" style=${`stroke-width:${d.baseWidthPx.toFixed(2)}`}></path>
      <path d=${t} class="flow-dots"></path>
      <path d=${t} class="flow-glow" style=${T}></path>
      <path id=${g} d=${t} class="flow-packets" style=${S}></path>
      ${_}${E}
    </g>`}function go(e,r,t,n,o,i,s){let l=!!n&&n.motion.moving,a=`ef3d-info-${e}`,c=!!n&&mr(n.edge),u=[];if(n&&l&&o){let{count:d,durationS:m}=Sr(n.motion,s),h=nn(n.motion.intensity,i);for(let p=0;p<d;p++)u.push(on(a,m,p/d,c,t,h,2.6,!0))}else if(l)for(let d of s>300?[.3,.7]:[.5])u.push(sn(a,d,c,t,i));return $`<g class=${`info-link info-${e} ${l?"active":""} ${c?"reversed":""}`} style=${`--flow-colour:${t}`}>
    <path d=${r} class="info-glow" style=${`stroke-width:${(2.6*i).toFixed(2)}`}></path>
    <path d=${r} class="info-under" style=${`stroke-width:${(2.4*i).toFixed(2)}`}></path>
    <path id=${a} d=${r} class="info-line" style=${`stroke-width:${(1.2*i).toFixed(2)}`}></path>
    ${u}
  </g>`}function ho(e,r,t,n,o){return $`<g class=${`info-link pulse-link info-${e} ${n?"active":""}`} style=${`--flow-colour:${t}`}>
    <path d=${r} class="info-glow" style=${`stroke-width:${(2.6*o).toFixed(2)}`}></path>
    <path d=${r} class="info-under" style=${`stroke-width:${(2.4*o).toFixed(2)}`}></path>
    <path d=${r} class="info-line" style=${`stroke-width:${(1.2*o).toFixed(2)}`}></path>
  </g>`}var tn=e=>e.slice(1).reduce((r,t,n)=>r+Math.hypot(t.x-e[n].x,t.y-e[n].y),0);function yo(e,r,t,n){return $`<g class=${`node-light ${t?"active":""}`} style=${`--flow-colour:${r}`}><circle cx=${e.x} cy=${e.y} r=${(5*n).toFixed(1)} class="node-light-halo"></circle><circle cx=${e.x} cy=${e.y} r=${(1.6*n).toFixed(1)} class="node-light-core"></circle></g>`}function Le(e,r,t,n){return e?$`<g class=${`gland ${t?"active":""}`} style=${`--flow-colour:${r}`}><circle cx=${e.x} cy=${e.y} r=${(2.6*n).toFixed(1)} class="gland-halo"></circle><circle cx=${e.x} cy=${e.y} r=${(.9*n).toFixed(1)} class="gland-core"></circle></g>`:w}function se(e,r,t,n,o,i=1,s=!1){let l=N[e],a=14*i,c=e==="battery",u=19*i,d=2*Math.PI*u,m=t.soc??null,h=m===null?0:Math.max(0,Math.min(100,m))/100*d,p=r.x+52*i,g=r.x+r.w-30*i,A=r.y+r.h/2,P=o.edge.unknown?"unknown":o.edge.idle?"idle":"active";return $`
    <g class=${`pill pill-${e} tone-${t.tone} ${P} ${t.clickable?"clickable":""} ${s?"breathing":""}`}
       style=${`--pill-colour:${l}`}
       role=${t.clickable?"button":"img"}
       tabindex=${t.clickable?0:-1}
       aria-label=${`${t.label}: ${t.value}${t.sub?", "+t.sub:""}`}
       @click=${()=>n(e)}
       @keydown=${M=>{(M.key==="Enter"||M.key===" ")&&(M.preventDefault(),n(e))}}>
      <rect x=${r.x} y=${r.y} width=${r.w} height=${r.h} rx=${a} class="pill-bg"></rect>
      <rect x=${r.x} y=${r.y} width=${r.w} height=${r.h} rx=${a} class="pill-border"></rect>
      <circle cx=${r.x+27*i} cy=${r.y+r.h/2} r=${15*i} class="pill-icon-bg"></circle>
      ${en(t.icon,r.x+16*i,r.y+r.h/2-11*i,22*i,l)}
      <text x=${p} y=${r.y+19*i} class="pill-label">${t.label}</text>
      <text x=${p} y=${r.y+(t.sub?39:42)*i} class="pill-value">${t.value}</text>
      ${t.sub?$`<text x=${p} y=${r.y+(t.extra?52:r.h/i-8)*i} class="pill-sub">${t.sub}</text>`:w}
      ${t.extra?$`<text x=${p} y=${r.y+r.h-9*i} class="pill-extra">${t.extra}</text>`:w}
      ${c?$`
            <circle cx=${g} cy=${A} r=${u} class="ring-track"></circle>
            ${m===null?w:$`<circle cx=${g} cy=${A} r=${u} class="ring-fill" stroke-dasharray=${`${h.toFixed(1)} ${d.toFixed(1)}`} transform=${`rotate(-90 ${g} ${A})`}></circle>`}
            <text x=${g} y=${A+4*i} class="ring-value">${m===null?"--":`${Math.round(m)}%`}</text>
            <text x=${g} y=${A+14*i} class="ring-caption">SOC</text>`:t.clickable?en("chevron",r.x+r.w-24*i,r.y+r.h/2-8*i,16*i,"rgba(255,255,255,0.45)"):w}
    </g>`}function an(e){if(e.artwork)return bo(e,e.artwork);let r=Jr(),t=e.flows.grid.motion.moving,n=Ht;return $`
    <svg class=${`scene ${e.daylight} ${e.stale?"stale":""} ${e.animate?"":"still"}`} viewBox=${`0 0 ${nt} ${zt}`} preserveAspectRatio="xMidYMid meet" aria-label="Isometric energy flow scene">
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
      <rect x="0" y="0" width=${nt} height=${zt} fill="url(#ef3d-sky)" class="sky"></rect>
      <g class="celestial">
        <circle cx="300" cy="96" r="14" class="moon"></circle>
        <circle cx="300" cy="96" r="30" class="moon-halo"></circle>
        <circle cx="318" cy="128" r="17" class="sun-disc"></circle>
        <circle cx="318" cy="128" r="56" class="sun-halo"></circle>
        ${[[40,92],[122,46],[180,112],[236,70],[352,150],[392,60],[20,160],[288,20]].map(([o,i])=>$`<circle cx=${o} cy=${i} r="1.1" class="star"></circle>`)}
      </g>
      ${so()}
      ${it(-6.5,-4.6,13,"back")}
      ${it(-2.5,-5.2,10,"back")}
      ${it(9.5,-5.6,11,"back")}
      ${$e(-7.2,1.2,8)}
      ${$e(-6.6,-1,7)}
      ${$e(5,5.2,7)}
      ${$e(6.4,6.4,6)}
      ${$e(-1.5,7.2,8)}
      ${Kt(-4.8,6.6)}
      ${Kt(3.9,5.2)}
      ${Kt(7.4,8.6)}
      ${fo(t,e.flows.grid.edge.unknown)}
      ${lo()}
      ${po(e.pills.battery.soc??null)}
      ${it(-7.6,8.6,12,"front")}
      ${$e(1.2,8.8,7)}
      <g class="flows">
        ${Ne("grid","grid",r.grid,e.flows.grid,e.animate)}
        ${Ne("solar","solar",r.solar,e.flows.solar,e.animate)}
        ${Ne("battery","battery",r.battery,e.flows.battery,e.animate)}
        ${Ne("home","home",r.home,e.flows.home,e.animate)}
        <circle cx=${n.x} cy=${n.y} r="4.2" class=${`junction led-${e.inverterLed}`}></circle>
        <circle cx=${n.x} cy=${n.y} r="9" class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${se("solar",ie.solar,e.pills.solar,e.onPill,e.flows.solar)}
      ${se("grid",ie.grid,e.pills.grid,e.onPill,e.flows.grid)}
      ${se("home",ie.home,e.pills.home,e.onPill,e.flows.home)}
      ${se("battery",ie.battery,e.pills.battery,e.onPill,e.flows.battery)}
    </svg>`}var mo={battery:"B",solarMain:"A1.",solarGarage:"A2.",grid:"G",home:"H",solarInfoMain:"s1.",solarInfoGarage:"s2.",batteryInfo:"b",gridInfo:"g",homeInfo:"h"},rn={battery:"battery",solarMain:"solar",solarGarage:"solar",grid:"grid",home:"home",solarInfoMain:"solar",solarInfoGarage:"solar",batteryInfo:"battery",gridInfo:"grid",homeInfo:"home"};function bo(e,r){let t=r.layout,n=t.paths(),o=t.scale,i=t.anchors,s=t.routing,l=e.solarSplit??{card:e.flows.solar,main:e.flows.solar,garage:null},a=y=>{let x=t.routes[y];if(x.length<2)return"";let[v,C]=y==="home"?[x[0],x[1]]:[x[x.length-2],x[x.length-1]];return`M ${v.x} ${v.y} L ${C.x} ${C.y}`},c=r.layers[r.layers.length-1],u=!!c&&jr(c.key),d=Object.fromEntries(we.map(y=>[y,Zr(t,y)])),m=y=>`ef3d-buried-${y}`,h=we.filter(y=>d[y].duct).map(y=>$`<mask id=${m(y)} maskUnits="userSpaceOnUse" x="0" y="0" width=${t.width} height=${t.height}><rect width=${t.width} height=${t.height} fill="white"></rect><path d=${d[y].duct} fill="none" stroke="black" stroke-linecap="butt" stroke-linejoin="round" stroke-width=${(26*o).toFixed(1)} filter="url(#ef3d-duct-feather)"></path></mask>`),p=(y,x,v)=>Ne(y,x,d[x].track,v,e.animate,o,tn(t.routes[x]),a(x),d[x].drawn,d[x].duct?m(x):""),g=y=>!!y&&y.motion.moving,A=r.links==="particles"||r.links==="off"?r.links:"pulse",P=(y,x,v,C)=>A==="off"?w:A==="particles"?go(x,n[y],v,C,e.animate,o,tn(t.routes[y])):ho(x,n[y],v,g(C),o),M=[["solarInfoMain",l.main],["solarInfoGarage",l.garage],["batteryInfo",e.flows.battery],["gridInfo",e.flows.grid],["homeInfo",e.flows.home]],_={solar:!1,grid:!1,battery:!1,home:!1};if(A==="pulse")for(let[y,x]of M)g(x)&&(_[s.info[y].card]=!0);let E=y=>t.routes[y][0],k=y=>t.routes[y][t.routes[y].length-1],S=(y,x,v)=>y?yo(y,x,v,o):w,T=r.debug?$`<g class="debug">
        ${s.obstacles.map(y=>$`<polygon points=${y.points.map(x=>`${x.x},${x.y}`).join(" ")} class="debug-obstacle"><title>${y.label}</title></polygon>`)}
        ${s.equipment.map(y=>$`<rect x=${y.x} y=${y.y} width=${y.w} height=${y.h} class="debug-equipment"></rect><text x=${y.x+3*o} y=${y.y+y.h-3*o} class="debug-equipment-label">${y.label}</text>`)}
        ${s.traces.map(y=>$`<polyline points=${y.points.map(x=>`${x.x},${x.y}`).join(" ")} class="debug-paving"><title>${y.label}</title></polyline>`)}
        ${we.filter(y=>d[y].duct).map(y=>$`<path d=${d[y].duct} class="debug-buried" style=${`--flow-colour:${N[rn[y]]}`}><title>${y}: buried duct (not drawn)</title></path>`)}
        <line x1=${t.underside.from.x} y1=${t.underside.from.y} x2=${t.underside.to.x} y2=${t.underside.to.y} class="debug-entry"></line>
        <text x=${t.underside.to.x+6*o} y=${t.underside.to.y+3*o} class="debug-label">inverter underside (connection bar)</text>
        ${Object.keys(t.routes).map(y=>t.routes[y].map((x,v)=>$`<g class="debug-node" style=${`--flow-colour:${N[rn[y]]}`}><circle cx=${x.x} cy=${x.y} r=${(y.endsWith("Info")||y.startsWith("solarInfo")?2.6:3.4)*o} class="debug-node-dot"></circle><text x=${x.x+5*o} y=${x.y-4*o} class="debug-node-label">${mo[y]}${v+1}</text><title>${y} ${v+1}: ${x.x},${x.y}${s.nodes[y]?.[v]?" "+s.nodes[y][v]:""}</title></g>`))}
        ${Object.values(i).map(y=>$`<circle cx=${y.x} cy=${y.y} r=${9*o} class="debug-ring"></circle><text x=${y.x+11*o} y=${y.y+12*o} class="debug-label">${y.label} ${y.x},${y.y}</text>`)}
        ${Object.entries(t.pills).map(([y,x])=>$`<rect x=${x.x} y=${x.y} width=${x.w} height=${x.h} class="debug-zone"></rect><circle cx=${x.port.x} cy=${x.port.y} r=${3.5*o} class="debug-port"></circle><text x=${x.x+4*o} y=${x.y-4*o} class="debug-label">${y} card</text>`)}
      </g>`:w;return $`
    <svg class=${`scene artwork links-${A} ${e.daylight} ${u?"night-plate":""} ${e.stale?"stale":""} ${e.animate?"":"still"}`} viewBox=${`0 0 ${t.width} ${t.height}`} preserveAspectRatio="xMidYMid meet" style=${`--k:${o}`} aria-label="Energy flow scene">
      <defs>
        <filter id="ef3d-blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation=${(1.6*o).toFixed(1)}></feGaussianBlur></filter>
        <filter id="ef3d-blur-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=${(3.5*o).toFixed(1)}></feGaussianBlur></filter>
        ${h.length?$`<filter id="ef3d-duct-feather" filterUnits="userSpaceOnUse" x="0" y="0" width=${t.width} height=${t.height}><feGaussianBlur stdDeviation=${(1*o).toFixed(1)}></feGaussianBlur></filter>`:w}
        ${h}
      </defs>
      ${r.layers.map(y=>$`<image href=${y.url} x="0" y="0" width=${t.width} height=${t.height} preserveAspectRatio="xMidYMid meet" class=${`plate ${y.entering?"entering":""}`} data-scene=${y.key} @error=${()=>r.onError(y.url)} @load=${()=>r.onLoad(y.url)}></image>`)}
      <g class="flows">
        ${P("solarInfoMain","solar-main",N.solar,l.main)}
        ${l.garage?P("solarInfoGarage","solar-garage",N.solar,l.garage):w}
        ${P("batteryInfo","battery",N.battery,e.flows.battery)}
        ${P("gridInfo","grid",N.grid,e.flows.grid)}
        ${P("homeInfo","home",N.home,e.flows.home)}
        ${p("grid","grid",e.flows.grid)}
        ${p("battery","battery",e.flows.battery)}
        ${p("solar","solarMain",l.main)}
        ${l.garage?p("solar","solarGarage",l.garage):w}
        ${p("home","home",e.flows.home)}
        ${S(E("solarMain"),N.solar,g(l.main))}
        ${l.garage?S(E("solarGarage"),N.solar,g(l.garage)):w}
        ${S(E("battery"),N.battery,g(e.flows.battery))}
        ${S(E("grid"),N.grid,g(e.flows.grid))}
        ${S(k("home"),N.home,g(e.flows.home))}
        ${Le(k("grid"),N.grid,g(e.flows.grid),o)}
        ${Le(k("battery"),N.battery,g(e.flows.battery),o)}
        ${Le(k("solarMain"),N.solar,g(l.main),o)}
        ${l.garage?Le(k("solarGarage"),N.solar,g(l.garage),o):w}
        ${Le(E("home"),N.home,g(e.flows.home),o)}
      </g>
      ${T}
      ${se("solar",t.pills.solar,e.pills.solar,e.onPill,e.flows.solar,o,_.solar)}
      ${se("grid",t.pills.grid,e.pills.grid,e.onPill,e.flows.grid,o,_.grid)}
      ${se("home",t.pills.home,e.pills.home,e.onPill,e.flows.home,o,_.home)}
      ${se("battery",t.pills.battery,e.pills.battery,e.onPill,e.flows.battery,o,_.battery)}
    </svg>`}var xo=15e3,B=class extends ee{constructor(){super(...arguments);this._detailsOpen=!1;this._nowMs=Date.now();this._layers=[];this._failedPlates=new Set;this._fadeTimer=0;this._widthPx=0;this._raf=0;this._breathers=[];this._timer=0;this._lengthCache=new WeakMap;this._onMotionPref=()=>{this.requestUpdate()}}static getStubConfig(){return{type:"custom:ecco-flow-3d-card",title:"Energy Flow",subtitle:"Live power overview",nodes:{solar:[{label:"Array 1",power:"sensor.pv1_power"}],inverter:{power:"sensor.inverter_power"},home:{power:"sensor.house_power"},battery:{power:"sensor.battery_power",soc:"sensor.battery_soc",power_sign:"charge_positive"},grid:{power:"sensor.grid_power",power_sign:"import_positive"}}}}setConfig(t){ur(t),this._config=t,this._failedPlates=new Set}_resolveScene(t,n){let o=this._config?.scene;if(!o?.pack)return null;let i=this._config?.ecco??{},s=i.sun?t[i.sun]:void 0,l=typeof s?.attributes?.elevation=="number"?s.attributes.elevation:null,a=typeof s?.attributes?.rising=="boolean"?s.attributes.rising:null,u=(o.force&&Dr.includes(o.force)?o.force:null)??Hr({month:n.getMonth()+1,day:n.getDate(),sunUp:s?s.state==="above_horizon"?!0:s.state==="below_horizon"?!1:null:null,elevation:l,rising:a,weather:i.weather?F(t,i.weather):void 0,hour:n.getHours()});return{key:u,url:Kr(o.pack,u,o.scenes)}}willUpdate(){let t=this._resolveScene(this.hass?.states??{},new Date(this._nowMs));if(!t){this._layers.length&&(this._layers=[]);return}let n=this._layers[this._layers.length-1];n&&n.url===t.url||(this._layers=this._layers.length===0?[{url:t.url,key:t.key,entering:!1}]:[...this._layers.slice(-1),{url:t.url,key:t.key,entering:!0}])}_plateLoaded(t){let n=this._layers[this._layers.length-1];!n||n.url!==t||this._layers.length<2||(window.clearTimeout(this._fadeTimer),this._fadeTimer=window.setTimeout(()=>{this._layers=this._layers.filter(o=>o.url===t).map(o=>({...o,entering:!1}))},(this._config?.scene?.crossfade_ms??900)+50))}_plateFailed(t){this._failedPlates.add(t),this.requestUpdate()}getCardSize(){return 8}connectedCallback(){super.connectedCallback(),window.matchMedia&&(this._reducedMotionQuery=window.matchMedia("(prefers-reduced-motion: reduce)"),this._reducedMotionQuery.addEventListener?.("change",this._onMotionPref)),this._timer=window.setInterval(()=>{this._nowMs=Date.now()},xo),typeof ResizeObserver<"u"&&(this._resize=new ResizeObserver(t=>{let n=Math.round(t[0]?.contentRect.width??0);n&&Math.abs(n-this._widthPx)>8&&(this._widthPx=n)}),this._resize.observe(this)),this.hasUpdated&&!this._raf&&this._animate()}disconnectedCallback(){super.disconnectedCallback(),this._reducedMotionQuery?.removeEventListener?.("change",this._onMotionPref),window.clearInterval(this._timer),window.clearTimeout(this._fadeTimer),this._resize?.disconnect(),cancelAnimationFrame(this._raf),this._raf=0}firstUpdated(){this._raf||this._animate()}updated(t){this._placeChevrons();let n=this.shadowRoot;this._breathers=n?[...n.querySelectorAll("svg.scene.links-pulse:not(.still) .pulse-link.active, svg.scene.links-pulse:not(.still):not(.stale) .pill.breathing .pill-border")]:[],this._applyLinkPulse(performance.now()/1e3)}get _reducedMotion(){return!!this._reducedMotionQuery?.matches}_moreInfo(t){t&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:t},bubbles:!0,composed:!0}))}render(){let t=this._config;if(!t)return L``;let n=this.hass?.states??{},o=t.nodes??{},i=t.ecco??{},s=new Date(this._nowMs),l=cr(o.solar),a=l.map(U=>R(n,U.power)),c=hr(R(n,o.solar_total),a),u=R(n,o.inverter?.power),d=R(n,o.battery?.power),m=d===null?null:pr(d,o.battery?.power_sign),h=R(n,o.grid?.power),p=h===null?null:fr(h,o.grid?.power_sign),g=gr(R(n,o.home?.power),u,p),A=R(n,o.battery?.soc),P=yr({solarW:c,batteryW:m,gridW:p,homeW:g}),M=Object.fromEntries(P.map(U=>[U.id,U])),_=br(c,a[0]??null,a[1]??null,l.length),E=G(F(n,i.telemetry_online)),k=Nr([...l.map(U=>U.power),o.solar_total,o.inverter?.power,o.battery?.power,o.grid?.power,o.home?.power],n,E,this._nowMs,t.features?.stale_after_s??dr),S=k.stale,T=(t.features?.animate_flow??!0)&&!this._reducedMotion,y=o.battery?.time_to_reserve,x=Xe(y,Te(y,R(n,y),K(n,y)?.unit_of_measurement),K(n,y)),v=x&&(x.status==="discharging"||x.status==="at_reserve")?It(x):"",C=wr(m),H=_r(p),j=G(F(n,o.grid?.connected)),pe={solar:{label:"Solar Generation",value:ye(c),sub:l.length>1?l.map((U,at)=>ye(a[at]??null)).join(" + "):"",tone:c===null?"muted":"ok",icon:"sun",clickable:!!(o.solar_total??l[0]?.power)},grid:{label:"Grid",value:ye(p===null?null:Math.abs(p)),sub:j==="off"?"Disconnected":H==="importing"?"Importing":H==="exporting"?"Exporting":H==="idle"?"Idle":"Unknown",tone:j==="off"?"alert":H==="unknown"?"muted":"ok",icon:"pylon",clickable:!!o.grid?.power},home:{label:"Home Load",value:ye(g),sub:"",tone:g===null?"muted":"ok",icon:"home",clickable:!!o.home?.power},battery:{label:"Battery Storage",value:ye(m===null?null:Math.abs(m)),sub:C==="charging"?"Charging":C==="discharging"?"Discharging":C==="idle"?"Idle":"Unknown",extra:v,tone:C==="unknown"?"muted":"ok",icon:"battery",clickable:!!(o.battery?.power??o.battery?.soc),soc:A}},I=zr(i.sun?n[i.sun]:void 0,s),jt=this._layers[this._layers.length-1],Gt=!!jt&&!this._failedPlates.has(jt.url),ln={daylight:I,artwork:Gt?{layers:this._layers,layout:this._layout(Qr(this._widthPx||this.getBoundingClientRect().width||1200),t.scene?.routing),onError:U=>this._plateFailed(U),onLoad:U=>this._plateLoaded(U),debug:!!t.scene?.debug_anchors,links:_t(t.scene?.links)??"pulse"}:void 0,solarSplit:Gt?{card:{edge:_.card,motion:te(_.card,S)},main:{edge:_.main,motion:te(_.main,S)},garage:_.garage?{edge:_.garage,motion:te(_.garage,S)}:null}:void 0,flows:{solar:{edge:M.solar,motion:te(M.solar,S)},battery:{edge:M.battery,motion:te(M.battery,S)},grid:{edge:M.grid,motion:te(M.grid,S)},home:{edge:M.home,motion:te(M.home,S)}},stale:S,animate:T,pills:pe,inverterLed:S?"warn":P.some(U=>!U.unknown)?"ok":"off",onPill:U=>{let at=U==="solar"?o.solar_total??l[0]?.power:U==="grid"?o.grid?.power:U==="home"?o.home?.power:o.battery?.power??o.battery?.soc;this._moreInfo(at)}},cn=xr(P)&&!S,st=this._chip(E,k.ageS,S,k.reason);return L`
      <ha-card style=${`--ef-crossfade:${t.scene?.crossfade_ms??900}ms`}>
        <div class="card">
          <header class="head">
            <div class="titles">
              ${(t.brand??"ECCO")!==""?L`<div class="wordmark"><span class="wm-accent">${(t.brand??"ECCO").slice(0,1)}</span>${(t.brand??"ECCO").slice(1)}</div>`:w}
              <div class="brand">${t.title??"Energy Flow"}</div>
              ${t.subtitle?L`<div class="subtitle">${t.subtitle}</div>`:w}
            </div>
            <button class=${`chip tone-${st.tone}`} type="button" @click=${()=>this._moreInfo(i.telemetry_online)} title=${st.title}>
              <span class="dot"></span>${st.text}
            </button>
          </header>
          ${S?L`<div class="strip stale-strip">${k.reason==="telemetry_offline"?"Telemetry offline: the values shown are the last received, not live.":`Values are stale: the newest power reading is ${me(k.ageS)}.`}</div>`:w}
          <div class="body">
            <div class="scene-wrap">
              ${an(ln)}
              ${cn?L`<div class="banner idle-banner">Site idle: no power is flowing above ${5} W.</div>`:w}
            </div>
            <div class="side">
              ${t.features?.show_status_panel===!1?w:this._renderStatus(n,s,S,k.ageS)}
              ${this._renderStrips(n)}
            </div>
            ${t.features?.show_details_panel===!1?w:L`<div class="more">${this._renderDetails(n,l,a,c,u,m,p,g)}</div>`}
          </div>
        </div>
      </ha-card>
    `}_chip(t,n,o,i){return t==="off"?{text:"Telemetry offline",tone:"alert",title:"The dongle's telemetry polling is offline"}:o&&i==="age"?{text:`Stale \xB7 ${me(n)}`,tone:"warn",title:"No power reading has updated recently"}:t==="on"?{text:"System online",tone:"ok",title:n===null?"Telemetry online":`Telemetry online \xB7 updated ${me(n)}`}:{text:n===null?"Status unknown":`Updated ${me(n)}`,tone:"muted",title:"No telemetry-online entity configured"}}_renderStatus(t,n,o,i){let s=this._config,l=s.ecco??{},a=s.nodes??{},c=[],u=l.tou,d=Or((u?.slot_start_minutes??[]).map(I=>R(t,I)),Lr(n),u?.valid?G(F(t,u.valid)):"unknown"),m=d.slot===null?null:d.slot-1,h=m===null?void 0:u?.slot_target_soc?.[m],p=m===null?void 0:u?.slot_charge_source?.[m],g=m===null?void 0:u?.slot_power?.[m],A=R(t,h),P=F(t,p),M=R(t,g);c.push({key:"tou",icon:"clock",label:"TOU Slot",value:d.value,sub:d.sub,tone:d.tone,entity:m===null?u?.slot_start_minutes?.[0]:u?.slot_start_minutes?.[m],title:"The slot containing the current local time, from the six slot start sensors"}),c.push({key:"charge",icon:"plug",label:"Charge Source",value:p&&P&&P!=="unknown"&&P!=="unavailable"?P:"--",sub:m===null?"Needs the current slot":M!==null?`Slot limit ${re(M,s.format)}`:"Current slot setting",tone:P&&P.toLowerCase()==="grid"?"accent":"muted",entity:p}),c.push({key:"target",icon:"target",label:"Target SOC",value:Ve(A),sub:m===null?"Needs the current slot":`Slot ${d.slot} setting`,tone:A===null?"muted":"accent",entity:h});let _=a.battery?.time_to_reserve,E=Te(_,R(t,_),K(t,_)?.unit_of_measurement),k=Xe(_,E,K(t,_)),S=Ir(k);c.push({key:"runtime",icon:"battery",label:"Runtime",value:S.value,sub:S.sub,tone:S.tone,entity:_,title:k?Ft(k):"No time-to-reserve entity configured"});let T=l.free_power,y=Ot({active:G(F(t,T?.active)),endsAtText:F(t,T?.ends_at),scheduleStatus:F(t,T?.schedule_status),statusText:F(t,T?.status),scheduleAttrs:K(t,T?.schedule_status),anyConfigured:!!(T?.active||T?.status||T?.schedule_status)},this._nowMs,"free_power");c.push({key:"fp",icon:"leaf",label:"Free Power",value:y.value,sub:y.sub,tone:y.tone,entity:T?.status??T?.active??T?.schedule_status,title:F(t,T?.status)});let x=l.dump_to_grid,v=Ot({active:G(F(t,x?.active)),endsAtText:F(t,x?.ends_at),scheduleStatus:F(t,x?.schedule_status),statusText:F(t,x?.status),scheduleAttrs:K(t,x?.schedule_status),exportPowerW:R(t,x?.export_power),stopSoc:R(t,x?.stop_soc),anyConfigured:!!(x?.active||x?.status||x?.schedule_status)},this._nowMs,"dump");c.push({key:"dump",icon:"swap",label:"Dump to Grid",value:v.value,sub:v.sub,tone:v.tone,entity:x?.status??x?.active??x?.schedule_status,title:F(t,x?.status)});let C=Lt(l.health?.sensors??[],l.health?.attention??[],t);c.push({key:"health",icon:C.grade==="FAILED"?"alert":"heart",label:"Health",value:C.value,sub:C.sub,tone:C.tone,entity:l.health?.sensors?.[0],wide:!0,title:[...C.failed.map(I=>`FAILED: ${I}`),...C.degraded.map(I=>`DEGRADED: ${I}`),...C.attention.map(I=>`attention: ${I}`),...C.unknown.map(I=>`unknown: ${I}`)].join(`
`)||"All configured subsystems healthy"});let H=R(t,l.forecast?.today),j=R(t,l.forecast?.remaining),pe=R(t,s.today?.solar);return c.push({key:"forecast",icon:"forecast",label:"Forecast Today",value:z(H,s.format),sub:j!==null?`${z(j,s.format)} still expected`+(pe!==null?` \xB7 ${z(pe,s.format)} so far`:""):pe!==null?`${z(pe,s.format)} generated so far`:l.forecast?.today?"Remaining forecast unavailable":"No forecast entity configured",tone:H===null?"muted":"ok",entity:l.forecast?.remaining??l.forecast?.today,wide:!0}),L`
      <section class="status" aria-label="ECCO system status">
        <div class="status-head">
          <span class="status-title">ECCO System Status</span>
          <span class=${`status-age ${o?"stale":""}`}><span class="dot"></span>${i===null?"No timestamp":`Updated ${me(i)}`}</span>
        </div>
        <div class="tiles">
          ${c.map(I=>L`
              <button
                type="button"
                class=${`tile tone-${I.tone} ${I.wide?"wide":""} ${I.entity?"clickable":""}`}
                title=${I.title??""}
                ?disabled=${!I.entity}
                @click=${()=>this._moreInfo(I.entity)}
              >
                <span class="tile-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d=${be[I.icon]}></path></svg></span>
                <span class="tile-text">
                  <span class="tile-label">${I.label}</span>
                  <span class="tile-value">${I.value}</span>
                  ${I.sub?L`<span class="tile-sub">${I.sub}</span>`:w}
                </span>
                ${I.entity?L`<svg class="tile-chev" viewBox="0 0 24 24" aria-hidden="true"><path d=${be.chevron}></path></svg>`:w}
              </button>
            `)}
        </div>
      </section>
    `}get _diagStripOn(){return this._config?.features?.show_diagnostics_strip!==!1}get _todayStripOn(){return this._config?.features?.show_today_strip!==!1&&Object.values(this._config?.today??{}).some(Boolean)}_renderStrips(t){let n=this._config,o=n.nodes??{},i=n.inverter_details??{},s=n.today??{},l=n.format;if(!this._diagStripOn&&!this._todayStripOn)return w;let a=(h,p,g,A="",P="")=>L`
      <button type="button" class=${`metric ${A} ${g?"clickable":""}`} ?disabled=${!g} title=${P||(g??"")} @click=${()=>this._moreInfo(g)}>
        <span class="metric-label">${h}</span>
        <span class="metric-value">${p}</span>
      </button>`,c=G(F(t,o.grid?.connected)),u=R(t,s.solar),d=R(t,s.load),m=Cr(u,d);return L`
      ${this._diagStripOn?L`<section class="strip-panel diag" aria-label="Live diagnostics">
              <div class="strip-head"><span class="strip-title">Live diagnostics</span></div>
              <div class="metrics diag-metrics">
                ${a("Grid voltage",Mt(R(t,o.grid?.voltage)),o.grid?.voltage)}
                ${a("Grid frequency",Ct(R(t,o.grid?.frequency)),o.grid?.frequency)}
                ${a("Grid status",c==="on"?"Connected":c==="off"?"Disconnected":"Unknown",o.grid?.connected,c==="on"?"tone-ok":c==="off"?"tone-alert":"tone-muted")}
                ${a("AC transformer",Ye(R(t,i.ac_temperature)),i.ac_temperature)}
                ${a("DC transformer",Ye(R(t,i.dc_temperature)),i.dc_temperature)}
              </div>
            </section>`:w}
      ${this._todayStripOn?L`<section class="strip-panel today-strip" aria-label="Today">
              <div class="strip-head">
                <span class="strip-title">Today</span>
                <button type="button" class="share" ?disabled=${!s.load} title="Solar Share: today's solar energy over today's home load (the Overview's definition)" @click=${()=>this._moreInfo(s.solar)}>
                  <span class="share-label">Solar Share</span>
                  <span class="share-value">${m===null?"--":Ve(m*100)}</span>
                  <span class="share-bar" aria-hidden="true"><span style=${`width:${m===null?0:Math.round(m*100)}%`}></span></span>
                </button>
              </div>
              <div class="metrics today-metrics">
                ${a("Solar",z(u,l),s.solar,"solar")}
                ${a("Home load",z(d,l),s.load,"home")}
                ${a("Grid import",z(R(t,s.import),l),s.import,"grid")}
                ${a("Grid export",z(R(t,s.export),l),s.export,"grid")}
                ${a("Battery charged",z(R(t,s.battery_charge),l),s.battery_charge,"battery")}
                ${a("Battery discharged",z(R(t,s.battery_discharge),l),s.battery_discharge,"battery")}
              </div>
            </section>`:w}
    `}_renderDetails(t,n,o,i,s,l,a,c){let u=this._config,d=u.nodes??{},m=u.ecco??{},h=u.inverter_details??{},p=u.format,g=(v,C,H,j)=>L`
      <div class=${`row ${H?"clickable":""}`} @click=${()=>this._moreInfo(H)} role=${H?"button":"listitem"} tabindex=${H?0:-1}>
        <span class="row-label">${v}</span>
        <span class="row-value">${C}${j?L`<span class="row-note">${j}</span>`:w}</span>
      </div>`,A=v=>Ye(R(t,v)),P=Fr(d.battery?.time_to_target,t),M=G(F(t,d.grid?.connected)),_=d.battery?.time_to_reserve,E=Xe(_,Te(_,R(t,_),K(t,_)?.unit_of_measurement),K(t,_)),k=Lt(m.health?.sensors??[],m.health?.attention??[],t),S=u.today??{},T=this._diagStripOn,y=Object.values(S).some(Boolean)&&!this._todayStripOn,x=R(t,m.forecast?.tomorrow);return L`
      <details class="details" ?open=${this._detailsOpen} @toggle=${v=>this._detailsOpen=v.target.open}>
        <summary>
          <span>Inverter, grid and diagnostics</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${be.chevron}></path></svg>
        </summary>
        <div class="details-grid">
          <div class="group">
            <div class="group-title">Inverter</div>
            ${g("State",F(t,d.inverter?.state)??"--",d.inverter?.state)}
            ${g("AC output",re(s,p),d.inverter?.power)}
            ${g("Home load",re(c,p),d.home?.power,R(t,d.home?.power)===0&&c!==0?"derived":void 0)}
            ${T?w:g("AC transformer",A(h.ac_temperature),h.ac_temperature)}
            ${T?w:g("DC transformer",A(h.dc_temperature),h.dc_temperature)}
            ${h.temperature?g("Temperature",A(h.temperature),h.temperature):w}
          </div>
          <div class="group">
            <div class="group-title">Grid</div>
            ${T?w:g("Connected",M==="on"?"Yes":M==="off"?"No":"Unknown",d.grid?.connected)}
            ${g("Power",a===null?"--":`${re(Math.abs(a),p)} ${a>=5?"import":a<=-5?"export":""}`,d.grid?.power)}
            ${T?w:g("Voltage",Mt(R(t,d.grid?.voltage)),d.grid?.voltage)}
            ${T?w:g("Frequency",Ct(R(t,d.grid?.frequency)),d.grid?.frequency)}
          </div>
          <div class="group">
            <div class="group-title">Solar</div>
            ${n.map((v,C)=>g(v.label??`Array ${C+1}`,re(o[C]??null,p),v.power))}
            ${g("Total",re(i,p),d.solar_total,d.solar_total?void 0:n.length>1?"sum of arrays":void 0)}
            ${m.forecast?.tomorrow?g("Forecast tomorrow",z(x,p),m.forecast.tomorrow):w}
          </div>
          <div class="group">
            <div class="group-title">Battery</div>
            ${g("Power",l===null?"--":`${re(Math.abs(l),p)} ${l>=5?"discharge":l<=-5?"charge":""}`,d.battery?.power)}
            ${g("State of charge",Ve(R(t,d.battery?.soc)),d.battery?.soc)}
            ${g("Time to reserve",E?Ft(E).replace(/^Time to reserve: /,""):"No entity configured",_)}
            ${g("Time to charge target",P.value,d.battery?.time_to_target,P.sub)}
            ${h.battery_temperature?g("Temperature",A(h.battery_temperature),h.battery_temperature):w}
          </div>
          ${(m.health?.sensors?.length??0)>0?L`<div class="group">
                  <div class="group-title">Health</div>
                  ${(m.health?.sensors??[]).map(v=>{let C=(F(t,v)??"--").toUpperCase();return g(v.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/_/g," "),C==="HEALTHY"?"Healthy":C==="DEGRADED"?"Degraded":C==="FAILED"?"Failed":"Unknown",v,typeof K(t,v)?.summary=="string"&&C!=="HEALTHY"?String(K(t,v)?.summary).trim().slice(0,80):void 0)})}
                  ${(m.health?.attention??[]).map(v=>g(v.replace(/^.*?\./,"").replace(/_/g," "),G(F(t,v))==="on"?"Needs attention":G(F(t,v))==="off"?"Clear":"Unknown",v))}
                  ${k.attention.length+k.failed.length>0?L`<div class="row-note block">Warnings are listed in full above; the Health tile summarises them.</div>`:w}
                </div>`:w}
          ${y?L`<div class="group today">
                  <div class="group-title">Today</div>
                  ${g("Solar",z(R(t,S.solar),p),S.solar)}
                  ${g("Load",z(R(t,S.load),p),S.load)}
                  ${g("Import",z(R(t,S.import),p),S.import)}
                  ${g("Export",z(R(t,S.export),p),S.export)}
                  ${g("Battery charge",z(R(t,S.battery_charge),p),S.battery_charge)}
                  ${g("Battery discharge",z(R(t,S.battery_discharge),p),S.battery_discharge)}
                </div>`:w}
        </div>
      </details>
    `}_layout(t,n){try{return ot(t,n)}catch{return ot(t)}}_pathFor(t,n){let o=t.querySelector(`#${CSS.escape(n)}`);if(!o)return null;let i=o.getAttribute("d")??"",s=this._lengthCache.get(o);return(!s||s.d!==i)&&(s={d:i,length:o.getTotalLength()},this._lengthCache.set(o,s)),s.length?{path:o,length:s.length}:null}_animate(){this._raf=requestAnimationFrame(()=>this._animate());let t=this.shadowRoot;if(!t||this._reducedMotion)return;let n=performance.now()/1e3;this._applyLinkPulse(n);let o=t.querySelectorAll(".pulse");o.length&&o.forEach(i=>{let s=i.dataset.path,l=parseFloat(i.dataset.duration??""),a=parseFloat(i.dataset.phase??"0");if(!s||!l)return;let c=this._pathFor(t,s);if(!c)return;let u=(n/l+a)%1;i.dataset.reversed==="1"&&(u=1-u);let d=c.path.getPointAtLength(u*c.length);i.setAttribute("transform",`translate(${d.x.toFixed(2)},${d.y.toFixed(2)})`)})}_applyLinkPulse(t){if(!this._breathers.length||this._reducedMotion)return;let n=Rr(t).toFixed(3);for(let o of this._breathers)o.style.setProperty("--link-pulse",n)}_placeChevrons(){let t=this.shadowRoot;t&&t.querySelectorAll(".chevron").forEach(n=>{let o=n.dataset.path,i=parseFloat(n.dataset.phase??"0.5");if(!o)return;let s=this._pathFor(t,o);if(!s)return;let l=n.dataset.reversed==="1",a=(l?1-i:i)*s.length,c=s.path.getPointAtLength(Math.max(0,a-2)),u=s.path.getPointAtLength(Math.min(s.length,a+2)),d=Math.atan2(u.y-c.y,u.x-c.x)*180/Math.PI+(l?180:0),m=s.path.getPointAtLength(a);n.setAttribute("transform",`translate(${m.x.toFixed(2)},${m.y.toFixed(2)}) rotate(${d.toFixed(1)})`)})}};B.styles=ct`
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
      grid-template-areas: "scene" "side" "more";
      gap: 12px;
    }
    .scene-wrap {
      grid-area: scene;
    }
    .side {
      grid-area: side;
    }
    .more {
      grid-area: more;
      min-width: 0;
    }
    /* Wide: the scene with the collapsible details under it; status, diagnostics and Today beside it. */
    @container (min-width: 760px) {
      .body {
        grid-template-columns: minmax(0, 1.75fr) minmax(300px, 1fr);
        grid-template-areas: "scene side" "more side";
        grid-template-rows: auto 1fr;
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
    /* The whole centreline of a partly buried route: the particles' path, never painted. */
    .fine-track {
      fill: none;
      stroke: none;
    }
    .fine-base {
      opacity: 0.4;
    }
    .fine-riser {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      filter: drop-shadow(0 0 3px var(--flow-colour));
    }
    .flow.fine.idle .fine-base {
      opacity: 0.16;
    }
    .flow.fine.idle .fine-riser,
    .flow.fine.unknown .fine-riser {
      opacity: 0.2;
      filter: none;
    }
    .debug-entry {
      stroke: #00e5ff;
      stroke-width: 3;
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
      opacity: 0.5;
    }
    .node-light.active .node-light-core {
      fill: #ffffff;
      opacity: 0.95;
      filter: drop-shadow(0 0 4px var(--flow-colour));
    }
    .gland-halo,
    .gland-core {
      opacity: 0;
    }
    .gland.active .gland-halo {
      fill: var(--flow-colour);
      opacity: 0.45;
      filter: url(#ef3d-blur);
    }
    .gland.active .gland-core {
      fill: #ffffff;
      opacity: 0.9;
    }
    /* Connectors: coloured dots on casing dots, so a card always reads as linked to its equipment; brighter while active. */
    .info-line {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0.72;
      stroke-dasharray: 0.01 calc(6px * var(--k, 1));
    }
    .info-under {
      fill: none;
      stroke: rgb(10, 20, 35);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0.42;
      stroke-dasharray: 0.01 calc(6px * var(--k, 1));
    }
    /* Casings and cores follow the plate's day/night crossfade instead of switching ahead of it (never the group
       opacity, which carries the pulse). */
    .info-under,
    .info-line {
      transition:
        stroke 900ms ease-in-out,
        opacity 900ms ease-in-out;
    }
    .info-link.active .info-under {
      opacity: 0.6;
    }
    /* Night plates: a light casing lifts the dots off the dark sky and the unlit garden. */
    .night-plate .info-under {
      stroke: rgb(225, 236, 255);
      opacity: 0.24;
    }
    .night-plate .info-link.active .info-under {
      opacity: 0.32;
    }
    .night-plate .info-line {
      opacity: 0.85;
    }
    /* The grid's blue would vanish into a blue day sky inside its casing: a pale core keeps the dots filled. */
    .scene:not(.night-plate) .info-grid .info-line {
      stroke: #d6ebff;
    }
    .info-glow {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0;
      filter: url(#ef3d-blur);
    }
    .info-link.active .info-line {
      opacity: 1;
    }
    .info-link.active .info-glow {
      opacity: 0.16;
    }
    /* Pulse links (scene.links "pulse", the default): the dotted connector above with no moving parts. While the flow
       carries power its dots and the card's border breathe together on --link-pulse (0..1, one slow sine shared by
       every card, written by the animator on just those elements); idle, unknown and stale links rest faint, grey and
       still, below the bottom of any active breath (core/motion.ts); still mode holds active links steady. */
    .pulse-link {
      opacity: ${Pr};
    }
    .pulse-link:not(.active) .info-line {
      stroke: #8a93a6;
    }
    .pulse-link.active {
      opacity: calc(${St} + ${1-St} * var(--link-pulse, 0.6));
    }
    .scene.still .pulse-link.active {
      opacity: 0.85;
    }
    .scene.links-pulse .pill.idle .pill-border {
      opacity: ${Mr};
    }
    .scene.links-pulse:not(.still):not(.stale) .pill.breathing .pill-border {
      opacity: calc(${Rt} + ${1-Rt} * var(--link-pulse, 0.6));
      filter: drop-shadow(0 0 calc((1px + 5px * var(--link-pulse, 0.6)) * var(--k, 1)) var(--pill-colour));
    }
    /* The grid's blue border would vanish into a blue day sky: a pale stroke, like its link's pale core. */
    .scene.links-pulse:not(.night-plate) .pill.pill-grid:not(.unknown) .pill-border {
      stroke: #d6ebff;
    }
    .debug-obstacle {
      fill: rgba(255, 59, 107, 0.16);
      stroke: rgba(255, 59, 107, 0.85);
      stroke-width: calc(0.8px * var(--k, 1));
    }
    .debug-equipment {
      fill: none;
      stroke: #ffd400;
      stroke-width: calc(0.8px * var(--k, 1));
      stroke-dasharray: 3 3;
    }
    .debug-equipment-label {
      font-size: calc(6px * var(--k, 1));
      fill: #ffe77a;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.85);
      stroke-width: calc(1.4px * var(--k, 1));
    }
    .debug-node-dot {
      fill: var(--flow-colour);
      stroke: #000;
      stroke-width: calc(0.6px * var(--k, 1));
    }
    .debug-node-label {
      font-size: calc(7px * var(--k, 1));
      font-weight: 800;
      fill: #fff;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.9);
      stroke-width: calc(1.8px * var(--k, 1));
    }
    .debug-paving {
      fill: none;
      stroke: #ffffff;
      stroke-width: 2;
      stroke-dasharray: 6 5;
      opacity: 0.9;
    }
    .debug-buried {
      fill: none;
      stroke: var(--flow-colour);
      stroke-width: calc(1.2px * var(--k, 1));
      stroke-dasharray: calc(2px * var(--k, 1)) calc(3px * var(--k, 1));
      opacity: 0.95;
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
    /* Artwork particles (power routes and connectors): a soft halo, a dark casing disc that keeps them readable on
       bright sky, walls and paving (hidden on night plates, where the glow carries them), the body and a white core. */
    .flow.fine .pulse-halo,
    .info-link .pulse-halo {
      opacity: 0.38;
    }
    .flow.fine .pulse-glow,
    .info-link .pulse-glow {
      opacity: 1;
      filter: drop-shadow(0 0 4px var(--pulse-colour));
    }
    .pulse-case {
      fill: rgb(6, 12, 24);
      opacity: 0.55;
    }
    .night-plate .pulse-case {
      display: none;
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

    /* ---- always-visible strips (diagnostics, today) ---- */
    .strip-panel {
      border-radius: 16px;
      border: 1px solid var(--ef-border);
      background: var(--ef-surface);
      padding: 10px;
    }
    .strip-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 24px;
      padding: 0 4px 8px;
    }
    .strip-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ef-muted);
      font-weight: 700;
    }
    .metrics {
      display: grid;
      gap: 6px;
    }
    /* Diagnostics: one instrument row of five, divided by hairlines (grid status never narrower than its value, so
       "Disconnected" always fits); below about 420 px two rows: grid status and voltage, then frequency and the two
       transformer temperatures. */
    .diag-metrics {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(max-content, 1.2fr) minmax(0, 1fr) minmax(0, 1fr);
      gap: 0;
    }
    .diag-metrics .metric {
      align-items: center;
      text-align: center;
      border: none;
      background: none;
      padding: 3px 5px 4px;
    }
    .diag-metrics .metric + .metric {
      border-left: 1px solid var(--ef-border);
      border-radius: 0;
    }
    .diag-metrics .metric-label {
      white-space: normal;
      line-height: 1.15;
      min-height: 2.3em;
      display: flex;
      align-items: flex-end;
      justify-content: center;
    }
    .diag-metrics .metric-value {
      font-size: 13px;
      max-width: 100%;
    }
    @container (max-width: 419px) {
      .diag-metrics {
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 6px;
      }
      .diag-metrics .metric,
      .diag-metrics .metric + .metric {
        grid-column: span 2;
        border: 1px solid var(--ef-border);
        border-radius: 11px;
        background: rgba(255, 255, 255, 0.03);
      }
      .diag-metrics .metric:nth-child(1),
      .diag-metrics .metric:nth-child(3) {
        grid-column: span 3;
      }
      .diag-metrics .metric:nth-child(3) {
        order: -1;
      }
      .diag-metrics .metric-label {
        min-height: 0;
      }
    }
    /* Today: three pairs in columns (solar / home, import / export, charged / discharged). */
    .today-metrics {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      grid-template-rows: auto auto;
      grid-auto-flow: column;
    }
    .metric {
      position: relative;
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
      text-align: left;
      border-radius: 11px;
      border: 1px solid var(--ef-border);
      background: rgba(255, 255, 255, 0.03);
      color: inherit;
      font: inherit;
      padding: 7px 9px;
      cursor: default;
    }
    .metric.clickable {
      cursor: pointer;
    }
    .metric.clickable:hover,
    .metric.clickable:focus-visible,
    .share:not(:disabled):hover,
    .share:not(:disabled):focus-visible {
      background: var(--ef-surface-2);
      border-color: rgba(255, 255, 255, 0.16);
      outline: none;
    }
    .metric-label {
      font-size: 10.5px;
      color: var(--ef-muted);
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .metric-value {
      font-size: 14px;
      font-weight: 800;
      letter-spacing: -0.01em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-variant-numeric: tabular-nums;
    }
    .metric.tone-ok .metric-value {
      color: var(--ef-ok);
    }
    .metric.tone-alert .metric-value {
      color: var(--ef-alert);
    }
    .metric.tone-muted .metric-value {
      color: #c3cbdc;
    }
    /* Today's energies carry a fine accent in their flow colour. */
    .today-metrics .metric {
      padding-left: 13px;
      /* A label that wraps to two lines keeps its value on the same baseline as its row neighbours. */
      justify-content: space-between;
    }
    .today-metrics .metric-label {
      white-space: normal;
      line-height: 1.2;
    }
    .today-metrics .metric::before {
      content: "";
      position: absolute;
      left: 6px;
      top: 9px;
      bottom: 9px;
      width: 2px;
      border-radius: 2px;
      background: var(--accent, var(--ef-muted));
      opacity: 0.85;
    }
    .metric.solar {
      --accent: var(--ef-solar);
    }
    .metric.home {
      --accent: #22d3ee;
    }
    .metric.grid {
      --accent: var(--ef-grid);
    }
    .metric.battery {
      --accent: var(--ef-battery);
    }
    .share {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid rgba(247, 201, 72, 0.32);
      background: rgba(247, 201, 72, 0.07);
      color: inherit;
      font: inherit;
      border-radius: 999px;
      padding: 3px 10px;
      cursor: pointer;
    }
    .share:disabled {
      cursor: default;
    }
    .share-label {
      font-size: 11px;
      color: var(--ef-muted);
      font-weight: 600;
    }
    .share-value {
      font-size: 13px;
      font-weight: 800;
      color: var(--ef-solar);
      font-variant-numeric: tabular-nums;
    }
    .share-bar {
      width: 42px;
      height: 4px;
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.1);
      overflow: hidden;
    }
    .share-bar span {
      display: block;
      height: 100%;
      border-radius: 4px;
      background: var(--ef-solar);
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
  `,Q([je({attribute:!1})],B.prototype,"hass",2),Q([he()],B.prototype,"_config",2),Q([he()],B.prototype,"_detailsOpen",2),Q([he()],B.prototype,"_nowMs",2),Q([he()],B.prototype,"_layers",2),Q([he()],B.prototype,"_widthPx",2),B=Q([lr("ecco-flow-3d-card")],B);window.customCards=[...window.customCards??[],{type:"ecco-flow-3d-card",name:"ECCO 3D Energy Flow",description:"Read-only isometric energy flow scene (solar, battery, grid, home) with animated power paths and the ECCO status grid.",preview:!1}];export{B as EccoFlow3dCard};
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
