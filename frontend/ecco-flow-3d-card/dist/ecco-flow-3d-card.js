var Mr=Object.defineProperty;var Tr=Object.getOwnPropertyDescriptor;var Y=(e,r,t,o)=>{for(var n=o>1?void 0:o?Tr(r,t):r,i=e.length-1,s;i>=0;i--)(s=e[i])&&(n=(o?s(r,t,n):s(n))||n);return o&&n&&Mr(r,t,n),n};var Ce=globalThis,Pe=Ce.ShadowRoot&&(Ce.ShadyCSS===void 0||Ce.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,Ke=Symbol(),kt=new WeakMap,be=class{constructor(r,t,o){if(this._$cssResult$=!0,o!==Ke)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=r,this.t=t}get styleSheet(){let r=this.o,t=this.t;if(Pe&&r===void 0){let o=t!==void 0&&t.length===1;o&&(r=kt.get(t)),r===void 0&&((this.o=r=new CSSStyleSheet).replaceSync(this.cssText),o&&kt.set(t,r))}return r}toString(){return this.cssText}},St=e=>new be(typeof e=="string"?e:e+"",void 0,Ke),Ye=(e,...r)=>{let t=e.length===1?e[0]:r.reduce((o,n,i)=>o+(s=>{if(s._$cssResult$===!0)return s.cssText;if(typeof s=="number")return s;throw Error("Value passed to 'css' function must be a 'css' function result: "+s+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(n)+e[i+1],e[0]);return new be(t,e,Ke)},At=(e,r)=>{if(Pe)e.adoptedStyleSheets=r.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(let t of r){let o=document.createElement("style"),n=Ce.litNonce;n!==void 0&&o.setAttribute("nonce",n),o.textContent=t.cssText,e.appendChild(o)}},qe=Pe?e=>e:e=>e instanceof CSSStyleSheet?(r=>{let t="";for(let o of r.cssRules)t+=o.cssText;return St(t)})(e):e;var{is:Rr,defineProperty:Cr,getOwnPropertyDescriptor:Pr,getOwnPropertyNames:Fr,getOwnPropertySymbols:Nr,getPrototypeOf:Ir}=Object,Fe=globalThis,Et=Fe.trustedTypes,Or=Et?Et.emptyScript:"",Lr=Fe.reactiveElementPolyfillSupport,xe=(e,r)=>e,$e={toAttribute(e,r){switch(r){case Boolean:e=e?Or:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,r){let t=e;switch(r){case Boolean:t=e!==null;break;case Number:t=e===null?null:Number(e);break;case Object:case Array:try{t=JSON.parse(e)}catch{t=null}}return t}},Ne=(e,r)=>!Rr(e,r),Mt={attribute:!0,type:String,converter:$e,reflect:!1,useDefault:!1,hasChanged:Ne};Symbol.metadata??=Symbol("metadata"),Fe.litPropertyMetadata??=new WeakMap;var G=class extends HTMLElement{static addInitializer(r){this._$Ei(),(this.l??=[]).push(r)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(r,t=Mt){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(r)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(r,t),!t.noAccessor){let o=Symbol(),n=this.getPropertyDescriptor(r,o,t);n!==void 0&&Cr(this.prototype,r,n)}}static getPropertyDescriptor(r,t,o){let{get:n,set:i}=Pr(this.prototype,r)??{get(){return this[t]},set(s){this[t]=s}};return{get:n,set(s){let c=n?.call(this);i?.call(this,s),this.requestUpdate(r,c,o)},configurable:!0,enumerable:!0}}static getPropertyOptions(r){return this.elementProperties.get(r)??Mt}static _$Ei(){if(this.hasOwnProperty(xe("elementProperties")))return;let r=Ir(this);r.finalize(),r.l!==void 0&&(this.l=[...r.l]),this.elementProperties=new Map(r.elementProperties)}static finalize(){if(this.hasOwnProperty(xe("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(xe("properties"))){let t=this.properties,o=[...Fr(t),...Nr(t)];for(let n of o)this.createProperty(n,t[n])}let r=this[Symbol.metadata];if(r!==null){let t=litPropertyMetadata.get(r);if(t!==void 0)for(let[o,n]of t)this.elementProperties.set(o,n)}this._$Eh=new Map;for(let[t,o]of this.elementProperties){let n=this._$Eu(t,o);n!==void 0&&this._$Eh.set(n,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(r){let t=[];if(Array.isArray(r)){let o=new Set(r.flat(1/0).reverse());for(let n of o)t.unshift(qe(n))}else r!==void 0&&t.push(qe(r));return t}static _$Eu(r,t){let o=t.attribute;return o===!1?void 0:typeof o=="string"?o:typeof r=="string"?r.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(r=>this.enableUpdating=r),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(r=>r(this))}addController(r){(this._$EO??=new Set).add(r),this.renderRoot!==void 0&&this.isConnected&&r.hostConnected?.()}removeController(r){this._$EO?.delete(r)}_$E_(){let r=new Map,t=this.constructor.elementProperties;for(let o of t.keys())this.hasOwnProperty(o)&&(r.set(o,this[o]),delete this[o]);r.size>0&&(this._$Ep=r)}createRenderRoot(){let r=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return At(r,this.constructor.elementStyles),r}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(r=>r.hostConnected?.())}enableUpdating(r){}disconnectedCallback(){this._$EO?.forEach(r=>r.hostDisconnected?.())}attributeChangedCallback(r,t,o){this._$AK(r,o)}_$ET(r,t){let o=this.constructor.elementProperties.get(r),n=this.constructor._$Eu(r,o);if(n!==void 0&&o.reflect===!0){let i=(o.converter?.toAttribute!==void 0?o.converter:$e).toAttribute(t,o.type);this._$Em=r,i==null?this.removeAttribute(n):this.setAttribute(n,i),this._$Em=null}}_$AK(r,t){let o=this.constructor,n=o._$Eh.get(r);if(n!==void 0&&this._$Em!==n){let i=o.getPropertyOptions(n),s=typeof i.converter=="function"?{fromAttribute:i.converter}:i.converter?.fromAttribute!==void 0?i.converter:$e;this._$Em=n;let c=s.fromAttribute(t,i.type);this[n]=c??this._$Ej?.get(n)??c,this._$Em=null}}requestUpdate(r,t,o,n=!1,i){if(r!==void 0){let s=this.constructor;if(n===!1&&(i=this[r]),o??=s.getPropertyOptions(r),!((o.hasChanged??Ne)(i,t)||o.useDefault&&o.reflect&&i===this._$Ej?.get(r)&&!this.hasAttribute(s._$Eu(r,o))))return;this.C(r,t,o)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(r,t,{useDefault:o,reflect:n,wrapped:i},s){o&&!(this._$Ej??=new Map).has(r)&&(this._$Ej.set(r,s??t??this[r]),i!==!0||s!==void 0)||(this._$AL.has(r)||(this.hasUpdated||o||(t=void 0),this._$AL.set(r,t)),n===!0&&this._$Em!==r&&(this._$Eq??=new Set).add(r))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}let r=this.scheduleUpdate();return r!=null&&await r,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[n,i]of this._$Ep)this[n]=i;this._$Ep=void 0}let o=this.constructor.elementProperties;if(o.size>0)for(let[n,i]of o){let{wrapped:s}=i,c=this[n];s!==!0||this._$AL.has(n)||c===void 0||this.C(n,void 0,i,c)}}let r=!1,t=this._$AL;try{r=this.shouldUpdate(t),r?(this.willUpdate(t),this._$EO?.forEach(o=>o.hostUpdate?.()),this.update(t)):this._$EM()}catch(o){throw r=!1,this._$EM(),o}r&&this._$AE(t)}willUpdate(r){}_$AE(r){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(r)),this.updated(r)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(r){return!0}update(r){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(r){}firstUpdated(r){}};G.elementStyles=[],G.shadowRootOptions={mode:"open"},G[xe("elementProperties")]=new Map,G[xe("finalized")]=new Map,Lr?.({ReactiveElement:G}),(Fe.reactiveElementVersions??=[]).push("2.1.2");var rt=globalThis,Tt=e=>e,Ie=rt.trustedTypes,Rt=Ie?Ie.createPolicy("lit-html",{createHTML:e=>e}):void 0,Ot="$lit$",q=`lit$${Math.random().toFixed(9).slice(2)}$`,Lt="?"+q,Hr=`<${Lt}>`,ne=document,ve=()=>ne.createComment(""),_e=e=>e===null||typeof e!="object"&&typeof e!="function",ot=Array.isArray,Ur=e=>ot(e)||typeof e?.[Symbol.iterator]=="function",Xe=`[ 	
\f\r]`,we=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Ct=/-->/g,Pt=/>/g,re=RegExp(`>|${Xe}(?:([^\\s"'>=/]+)(${Xe}*=${Xe}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Ft=/'/g,Nt=/"/g,Ht=/^(?:script|style|textarea|title)$/i,nt=e=>(r,...t)=>({_$litType$:e,strings:r,values:t}),I=nt(1),b=nt(2),Co=nt(3),ie=Symbol.for("lit-noChange"),m=Symbol.for("lit-nothing"),It=new WeakMap,oe=ne.createTreeWalker(ne,129);function Ut(e,r){if(!ot(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return Rt!==void 0?Rt.createHTML(r):r}var zr=(e,r)=>{let t=e.length-1,o=[],n,i=r===2?"<svg>":r===3?"<math>":"",s=we;for(let c=0;c<t;c++){let l=e[c],a,p,d=-1,u=0;for(;u<l.length&&(s.lastIndex=u,p=s.exec(l),p!==null);)u=s.lastIndex,s===we?p[1]==="!--"?s=Ct:p[1]!==void 0?s=Pt:p[2]!==void 0?(Ht.test(p[2])&&(n=RegExp("</"+p[2],"g")),s=re):p[3]!==void 0&&(s=re):s===re?p[0]===">"?(s=n??we,d=-1):p[1]===void 0?d=-2:(d=s.lastIndex-p[2].length,a=p[1],s=p[3]===void 0?re:p[3]==='"'?Nt:Ft):s===Nt||s===Ft?s=re:s===Ct||s===Pt?s=we:(s=re,n=void 0);let h=s===re&&e[c+1].startsWith("/>")?" ":"";i+=s===we?l+Hr:d>=0?(o.push(a),l.slice(0,d)+Ot+l.slice(d)+q+h):l+q+(d===-2?c:h)}return[Ut(e,i+(e[t]||"<?>")+(r===2?"</svg>":r===3?"</math>":"")),o]},ke=class e{constructor({strings:r,_$litType$:t},o){let n;this.parts=[];let i=0,s=0,c=r.length-1,l=this.parts,[a,p]=zr(r,t);if(this.el=e.createElement(a,o),oe.currentNode=this.el.content,t===2||t===3){let d=this.el.content.firstChild;d.replaceWith(...d.childNodes)}for(;(n=oe.nextNode())!==null&&l.length<c;){if(n.nodeType===1){if(n.hasAttributes())for(let d of n.getAttributeNames())if(d.endsWith(Ot)){let u=p[s++],h=n.getAttribute(d).split(q),y=/([.?@])?(.*)/.exec(u);l.push({type:1,index:i,name:y[2],strings:h,ctor:y[1]==="."?Qe:y[1]==="?"?Je:y[1]==="@"?et:ce}),n.removeAttribute(d)}else d.startsWith(q)&&(l.push({type:6,index:i}),n.removeAttribute(d));if(Ht.test(n.tagName)){let d=n.textContent.split(q),u=d.length-1;if(u>0){n.textContent=Ie?Ie.emptyScript:"";for(let h=0;h<u;h++)n.append(d[h],ve()),oe.nextNode(),l.push({type:2,index:++i});n.append(d[u],ve())}}}else if(n.nodeType===8)if(n.data===Lt)l.push({type:2,index:i});else{let d=-1;for(;(d=n.data.indexOf(q,d+1))!==-1;)l.push({type:7,index:i}),d+=q.length-1}i++}}static createElement(r,t){let o=ne.createElement("template");return o.innerHTML=r,o}};function ae(e,r,t=e,o){if(r===ie)return r;let n=o!==void 0?t._$Co?.[o]:t._$Cl,i=_e(r)?void 0:r._$litDirective$;return n?.constructor!==i&&(n?._$AO?.(!1),i===void 0?n=void 0:(n=new i(e),n._$AT(e,t,o)),o!==void 0?(t._$Co??=[])[o]=n:t._$Cl=n),n!==void 0&&(r=ae(e,n._$AS(e,r.values),n,o)),r}var Ze=class{constructor(r,t){this._$AV=[],this._$AN=void 0,this._$AD=r,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(r){let{el:{content:t},parts:o}=this._$AD,n=(r?.creationScope??ne).importNode(t,!0);oe.currentNode=n;let i=oe.nextNode(),s=0,c=0,l=o[0];for(;l!==void 0;){if(s===l.index){let a;l.type===2?a=new Se(i,i.nextSibling,this,r):l.type===1?a=new l.ctor(i,l.name,l.strings,this,r):l.type===6&&(a=new tt(i,this,r)),this._$AV.push(a),l=o[++c]}s!==l?.index&&(i=oe.nextNode(),s++)}return oe.currentNode=ne,n}p(r){let t=0;for(let o of this._$AV)o!==void 0&&(o.strings!==void 0?(o._$AI(r,o,t),t+=o.strings.length-2):o._$AI(r[t])),t++}},Se=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(r,t,o,n){this.type=2,this._$AH=m,this._$AN=void 0,this._$AA=r,this._$AB=t,this._$AM=o,this.options=n,this._$Cv=n?.isConnected??!0}get parentNode(){let r=this._$AA.parentNode,t=this._$AM;return t!==void 0&&r?.nodeType===11&&(r=t.parentNode),r}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(r,t=this){r=ae(this,r,t),_e(r)?r===m||r==null||r===""?(this._$AH!==m&&this._$AR(),this._$AH=m):r!==this._$AH&&r!==ie&&this._(r):r._$litType$!==void 0?this.$(r):r.nodeType!==void 0?this.T(r):Ur(r)?this.k(r):this._(r)}O(r){return this._$AA.parentNode.insertBefore(r,this._$AB)}T(r){this._$AH!==r&&(this._$AR(),this._$AH=this.O(r))}_(r){this._$AH!==m&&_e(this._$AH)?this._$AA.nextSibling.data=r:this.T(ne.createTextNode(r)),this._$AH=r}$(r){let{values:t,_$litType$:o}=r,n=typeof o=="number"?this._$AC(r):(o.el===void 0&&(o.el=ke.createElement(Ut(o.h,o.h[0]),this.options)),o);if(this._$AH?._$AD===n)this._$AH.p(t);else{let i=new Ze(n,this),s=i.u(this.options);i.p(t),this.T(s),this._$AH=i}}_$AC(r){let t=It.get(r.strings);return t===void 0&&It.set(r.strings,t=new ke(r)),t}k(r){ot(this._$AH)||(this._$AH=[],this._$AR());let t=this._$AH,o,n=0;for(let i of r)n===t.length?t.push(o=new e(this.O(ve()),this.O(ve()),this,this.options)):o=t[n],o._$AI(i),n++;n<t.length&&(this._$AR(o&&o._$AB.nextSibling,n),t.length=n)}_$AR(r=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);r!==this._$AB;){let o=Tt(r).nextSibling;Tt(r).remove(),r=o}}setConnected(r){this._$AM===void 0&&(this._$Cv=r,this._$AP?.(r))}},ce=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(r,t,o,n,i){this.type=1,this._$AH=m,this._$AN=void 0,this.element=r,this.name=t,this._$AM=n,this.options=i,o.length>2||o[0]!==""||o[1]!==""?(this._$AH=Array(o.length-1).fill(new String),this.strings=o):this._$AH=m}_$AI(r,t=this,o,n){let i=this.strings,s=!1;if(i===void 0)r=ae(this,r,t,0),s=!_e(r)||r!==this._$AH&&r!==ie,s&&(this._$AH=r);else{let c=r,l,a;for(r=i[0],l=0;l<i.length-1;l++)a=ae(this,c[o+l],t,l),a===ie&&(a=this._$AH[l]),s||=!_e(a)||a!==this._$AH[l],a===m?r=m:r!==m&&(r+=(a??"")+i[l+1]),this._$AH[l]=a}s&&!n&&this.j(r)}j(r){r===m?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,r??"")}},Qe=class extends ce{constructor(){super(...arguments),this.type=3}j(r){this.element[this.name]=r===m?void 0:r}},Je=class extends ce{constructor(){super(...arguments),this.type=4}j(r){this.element.toggleAttribute(this.name,!!r&&r!==m)}},et=class extends ce{constructor(r,t,o,n,i){super(r,t,o,n,i),this.type=5}_$AI(r,t=this){if((r=ae(this,r,t,0)??m)===ie)return;let o=this._$AH,n=r===m&&o!==m||r.capture!==o.capture||r.once!==o.once||r.passive!==o.passive,i=r!==m&&(o===m||n);n&&this.element.removeEventListener(this.name,this,o),i&&this.element.addEventListener(this.name,this,r),this._$AH=r}handleEvent(r){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,r):this._$AH.handleEvent(r)}},tt=class{constructor(r,t,o){this.element=r,this.type=6,this._$AN=void 0,this._$AM=t,this.options=o}get _$AU(){return this._$AM._$AU}_$AI(r){ae(this,r)}};var Dr=rt.litHtmlPolyfillSupport;Dr?.(ke,Se),(rt.litHtmlVersions??=[]).push("3.3.3");var zt=(e,r,t)=>{let o=t?.renderBefore??r,n=o._$litPart$;if(n===void 0){let i=t?.renderBefore??null;o._$litPart$=n=new Se(r.insertBefore(ve(),i),i,void 0,t??{})}return n._$AI(e),n};var it=globalThis,X=class extends G{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let r=super.createRenderRoot();return this.renderOptions.renderBefore??=r.firstChild,r}update(r){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(r),this._$Do=zt(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return ie}};X._$litElement$=!0,X.finalized=!0,it.litElementHydrateSupport?.({LitElement:X});var Br=it.litElementPolyfillSupport;Br?.({LitElement:X});(it.litElementVersions??=[]).push("4.2.2");var Dt=e=>(r,t)=>{t!==void 0?t.addInitializer(()=>{customElements.define(e,r)}):customElements.define(e,r)};var jr={attribute:!0,type:String,converter:$e,reflect:!1,hasChanged:Ne},Gr=(e=jr,r,t)=>{let{kind:o,metadata:n}=t,i=globalThis.litPropertyMetadata.get(n);if(i===void 0&&globalThis.litPropertyMetadata.set(n,i=new Map),o==="setter"&&((e=Object.create(e)).wrapped=!0),i.set(t.name,e),o==="accessor"){let{name:s}=t;return{set(c){let l=r.get.call(this);r.set.call(this,c),this.requestUpdate(s,l,e,!0,c)},init(c){return c!==void 0&&this.C(s,void 0,e,c),c}}}if(o==="setter"){let{name:s}=t;return function(c){let l=this[s];r.call(this,c),this.requestUpdate(s,l,e,!0,c)}}throw Error("Unsupported decorator location: "+o)};function Oe(e){return(r,t)=>typeof t=="object"?Gr(e,r,t):((o,n,i)=>{let s=n.hasOwnProperty(i);return n.constructor.createProperty(i,o),s?Object.getOwnPropertyDescriptor(n,i):void 0})(e,r,t)}function ue(e){return Oe({...e,state:!0,attribute:!1})}function Bt(e){return e?(Array.isArray(e)?e:[e]).filter(t=>!!t&&!!t.power):[]}var jt=180;function Gt(e){if(!e||typeof e!="object")throw new Error("ecco-flow-3d-card: invalid configuration");let r=e;if(!r.nodes||typeof r.nodes!="object"||Object.keys(r.nodes).length===0)throw new Error("ecco-flow-3d-card: at least one entry under `nodes:` is required");let t=r.ecco?.tou;for(let o of["slot_start_minutes","slot_target_soc","slot_charge_source","slot_power"]){let n=t?.[o];if(n!==void 0&&(!Array.isArray(n)||n.length!==6))throw new Error(`ecco-flow-3d-card: ecco.tou.${o} must list exactly six entities (slot 1 to slot 6)`)}}function Wt(e,r){return r==="discharge_positive"?e:-e}function Vt(e,r){return r==="export_positive"?-e:e}var Wr=150;function Kt(e,r,t){let o=r!==null&&t!==null?Math.max(0,r+t):null;return e===null||e===0&&o!==null&&o>Wr?o:Math.max(0,e)}function Yt(e,r){if(e!==null)return Math.max(0,e);let t=r.filter(o=>o!==null);return t.length===0?null:Math.max(0,t.reduce((o,n)=>o+n,0))}var W=5;function Ae(e,r,t){if(r===null)return{id:e,magnitudeW:null,idle:!1,unknown:!0,reversed:!1};let o=Math.abs(r);return{id:e,magnitudeW:o,idle:o<W,unknown:!1,reversed:t&&r<0}}function qt(e){return[Ae("solar",e.solarW===null?null:Math.max(0,e.solarW),!1),Ae("battery",e.batteryW,!0),Ae("grid",e.gridW,!0),Ae("home",e.homeW===null?null:Math.max(0,e.homeW),!1)]}function Xt(e,r,t,o){let n=s=>Ae("solar",s===null?null:Math.max(0,s),!1),i=n(e);return o>=2&&(r!==null||t!==null)?{card:i,main:n(r),garage:n(t)}:{card:i,main:n(e),garage:null}}function Zt(e){let r=e.filter(t=>!t.unknown);return r.length>0&&r.every(t=>t.idle)}function Qt(e){return e===null?"unknown":e>=W?"discharging":e<=-W?"charging":"idle"}function Jt(e){return e===null?"unknown":e>=W?"importing":e<=-W?"exporting":"idle"}var rr=6e3,Vr=2.4,Kr=.45,er=2.6,or=15,He=4,Yr=9,st=2.7,qr=5.4,lt=2.6,Xr=3.3,Zr=.6,tr=5.5,at=3.1,Qr=4.9;function Jr(e){if(!(e>W))return 0;let r=Math.log(e/W)/Math.log(rr/W),t=Math.min(1,Math.max(0,r));return Math.pow(t,Vr)}function eo(e){return e<750?1:e<3e3?2:e<6e3?3:4}var to={intensity:0,moving:!1,dashDurationS:0,dashLen:He,gapLen:or-He,packetWidthPx:st,baseWidthPx:lt,packetOpacity:0,glowPx:0,ballCount:0,ballDurationS:0,ballRadiusPx:at};function Z(e,r){if(e.unknown||e.idle||r||e.magnitudeW===null)return to;let t=e.magnitudeW,o=Jr(t),n=Math.min(1,t/rr),i=He+o*(Yr-He);return{intensity:o,moving:!0,dashDurationS:er-o*(er-Kr),dashLen:i,gapLen:or-i,packetWidthPx:st+o*(qr-st),baseWidthPx:lt+n*(Xr-lt),packetOpacity:.62+o*.36,glowPx:1.6+o*2.4,ballCount:eo(t),ballDurationS:tr-o*(tr-Zr),ballRadiusPx:at+o*(Qr-at)}}function ct(e){if(e==null||e==="unknown"||e==="unavailable"||e===""||e==="none"||e==="None")return null;let r=Number(e);return Number.isFinite(r)?r:null}function Q(e,r){if(e==null||Number.isNaN(e))return"--";let t=r?.power_unit??"auto",o=Math.abs(e);return t==="kw"||t==="auto"&&o>=1e3?`${(e/1e3).toFixed(r?.precision??2)} kW`:`${e.toFixed(r?.precision??0)} W`}function de(e){if(e==null||Number.isNaN(e))return"--";let r=Math.abs(e);return r>=1e4?`${(e/1e3).toFixed(0)} kW`:r>=1e3?`${(e/1e3).toFixed(1)} kW`:`${Math.round(e)} W`}function L(e,r){return e==null||Number.isNaN(e)?"--":`${e.toFixed(r?.energy_precision??1)} kWh`}function ut(e){return e==null||!Number.isFinite(e)?"--":`${Math.round(e)}%`}function V(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let r=Math.round(e);if(r===0)return e>0?"<1 min":"0 min";if(r<60)return`${r} min`;if(r<1440){let n=Math.floor(r/60),i=r%60;return i===0?`${n} h`:`${n} h ${i} min`}let t=Math.floor(r/1440),o=Math.floor(r%1440/60);return o===0?`${t} d`:`${t} d ${o} h`}function Ue(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let r=Math.round(e);if(r===0)return e>0?"<1m":"0m";if(r<60)return`\u2248${r}m`;if(r<1440){let n=Math.floor(r/60),i=r%60;return i===0?`\u2248${n}h`:`\u2248${n}h ${i}m`}let t=Math.floor(r/1440),o=Math.floor(r%1440/60);return o===0?`\u2248${t}d`:`\u2248${t}d ${o}h`}function dt(e){if(e==null||!Number.isFinite(e))return"--:--";let r=(Math.round(e)%1440+1440)%1440;return`${String(Math.floor(r/60)).padStart(2,"0")}:${String(r%60).padStart(2,"0")}`}function pt(e){return`${String(e.getHours()).padStart(2,"0")}:${String(e.getMinutes()).padStart(2,"0")}`}function pe(e){return e===null||!Number.isFinite(e)||e<0?"--":e<5?"just now":e<60?`${Math.floor(e)} s ago`:e<3600?`${Math.floor(e/60)} min ago`:e<86400?`${Math.floor(e/3600)} h ago`:`${Math.floor(e/86400)} d ago`}function A(e,r){return r?e[r]?.state:void 0}function _(e,r){return r?ct(e[r]?.state):null}function H(e,r){return r?e[r]?.attributes:void 0}function B(e){return e==="on"||e==="true"||e==="True"?"on":e==="off"||e==="false"||e==="False"?"off":"unknown"}var ro=new Map([["s",1/60],["min",1],["h",60],["d",1440]]);function Ee(e,r,t){if(!e)return;let o=t==null||t===""?1:ro.get(t);return o!==void 0&&r!==null&&r>=0?r*o:null}var oo=["discharging","at_reserve","charging","holding","insufficient_data","stale"];function nr(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0?e:null}function De(e,r,t){if(!e||r===void 0)return;let o=t?.status,i=oo.includes(o)?o:r!==null?"discharging":"insufficient_data";i==="discharging"&&r===null&&(i="insufficient_data");let s=i==="discharging"||i==="at_reserve",c=typeof t?.summary=="string"&&t.summary.trim()!==""?t.summary:null;return{status:i,minutes:s?r:null,low:i==="discharging"?nr(t?.minutes_low):null,high:i==="discharging"?nr(t?.minutes_high):null,beyondHorizon:i==="discharging"&&t?.beyond_horizon===!0,solarAssisted:i==="discharging"&&t?.solar_assisted===!0,summary:c}}var ir="Over 3 days";function ft(e){switch(e.status){case"discharging":return e.beyondHorizon?ir:`${Ue(e.minutes)} to reserve`;case"at_reserve":return"At reserve";case"charging":return"Charging";case"holding":return"Holding";case"stale":return"Telemetry stale";default:return"Insufficient data"}}function sr(e){if(!e)return{value:"--",sub:"No runtime entity",tone:"muted"};switch(e.status){case"discharging":return{value:e.beyondHorizon?">3 d":Ue(e.minutes),sub:e.beyondHorizon?"to reserve (estimate)":e.low!==null&&e.high!==null?`to reserve \xB7 likely ${V(e.low)} to ${V(e.high)}`:"to reserve (estimate)",tone:"ok"};case"at_reserve":return{value:"At reserve",sub:e.summary??"At or below the reserve",tone:"warn"};case"charging":return{value:"Charging",sub:"No discharge estimate while charging",tone:"ok"};case"holding":return{value:"Holding",sub:"Neither charging nor discharging",tone:"muted"};case"stale":return{value:"Stale",sub:"Estimate paused: telemetry stale",tone:"warn"};default:return{value:"--",sub:e.summary??"Insufficient data",tone:"muted"}}}function ht(e){if(e.status!=="discharging")return`Time to reserve: ${e.summary??ft(e)}`;let r=[e.beyondHorizon?`${ir} until the batteries reach the configured reserve at recent usage`:`Approximately ${V(e.minutes)} until the batteries reach the configured reserve at recent usage`];return!e.beyondHorizon&&e.low!==null&&e.high!==null&&r.push(`likely ${V(e.low)} to ${V(e.high)}`),e.solarAssisted&&r.push("solar-assisted, so it shortens as solar output falls"),r.push("an estimate, not a guarantee"),`Time to reserve: ${r.join("; ")}`}function lr(e,r){if(!e)return{value:"Not available",sub:"No ECCO entity provides a time to charge target",tone:"muted"};let t=Ee(e,_(r,e),H(r,e)?.unit_of_measurement);return t==null?{value:"--",sub:"Entity has no value",tone:"muted"}:{value:Ue(t),sub:"to charge target (entity value)",tone:"ok"}}var no=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function io(e){if(!e)return null;let r=no.exec(e.trim());if(!r)return null;let t=new Date(Number(r[1]),Number(r[2])-1,Number(r[3]),Number(r[4]),Number(r[5]),Number(r[6]));return Number.isNaN(t.getTime())?null:t}function so(e,r,t){return t?"Active \xB7 end time unavailable":r===null?"Active":e===null||e<=0?`Ends ${pt(r)} \xB7 ending`:`Ends ${pt(r)} \xB7 ${V(e)} left`}function gt(e,r,t){let o={phase:"unknown",value:"--",sub:"Not configured",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(!e.anyConfigured)return o;let n=(e.scheduleStatus??"").trim().toUpperCase(),i=io(e.endsAtText),s=(e.endsAtText??"").toLowerCase().includes("unavailable"),c=i?(i.getTime()-r)/6e4:null;if(e.active==="on"){let l=so(c,i,s);return t==="dump"&&e.exportPowerW!==null&&e.exportPowerW!==void 0&&(l=`${l} \xB7 ${Math.round(e.exportPowerW)} W export`+(e.stopSoc!==null&&e.stopSoc!==void 0?` \xB7 stop ${Math.round(e.stopSoc)}%`:"")),{phase:"active",value:"Active",sub:l,tone:"accent",remainingMin:c,endsAt:i,endTimeUnavailable:s}}if(n==="STARTING")return{phase:"starting",value:"Starting",sub:"Scheduled start in progress",tone:"accent",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(n==="ARMED"){let l=typeof e.scheduleAttrs?.scheduled_start=="string"?e.scheduleAttrs.scheduled_start:null,a=ct(String(e.scheduleAttrs?.duration_minutes??""));return{phase:"armed",value:"Armed",sub:`Scheduled ${l?l.slice(0,5):"--:--"}`+(a!==null?` \xB7 ${V(a)}`:""),tone:"ok",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}if(n==="FAILED")return{phase:"failed",value:"Failed",sub:"Last scheduled run failed \xB7 see Energy Actions",tone:"alert",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(e.active==="off"){let l=n==="COMPLETED";return{phase:l?"completed":"standby",value:l?"Completed":t==="dump"?"Ready":"Standby",sub:l?"Last scheduled run completed":"No session running",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}return{phase:"unknown",value:"--",sub:"Lease state unavailable",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}function ar(e,r,t){let o={slot:null,startMin:null,endMin:null,minutesToChange:null,value:"--",sub:"Schedule unavailable",tone:"muted"};if(e.length!==6||e.some(s=>s===null))return o;if(t==="off")return{...o,sub:"Schedule invalid",tone:"warn"};let n=e,i=(Math.floor(r)%1440+1440)%1440;for(let s=0;s<6;s++){let c=(n[s]%1440+1440)%1440,l=(n[(s+1)%6]%1440+1440)%1440;if(c<l?i>=c&&i<l:i>=c||i<l){let p=(l-i+1440)%1440;return{slot:s+1,startMin:c,endMin:l,minutesToChange:p,value:`Slot ${s+1}`,sub:`${dt(c)}\u2013${dt(l)} \xB7 ${V(p)} left`,tone:"accent"}}}return{...o,sub:"No slot matches the current time",tone:"warn"}}function cr(e){return e.getHours()*60+e.getMinutes()}function ze(e){return e.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/^ecco_/,"").replace(/_/g," ")}function yt(e,r,t){let o=[],n=[],i=[];for(let a of e){let p=(A(t,a)??"").trim().toUpperCase();p==="FAILED"?o.push(ze(a)):p==="DEGRADED"?n.push(ze(a)):p!=="HEALTHY"&&i.push(ze(a))}let s=r.filter(a=>B(A(t,a))==="on").map(ze);if(e.length+r.length===0)return{grade:"UNKNOWN",value:"--",sub:"No health entities configured",tone:"muted",failed:o,degraded:n,unknown:i,attention:s};let l=a=>a.slice(0,2).join(", ")+(a.length>2?` +${a.length-2}`:"");if(o.length>0||s.length>0){let a=[...o,...s];return{grade:"FAILED",value:"Attention",sub:l(a),tone:"alert",failed:o,degraded:n,unknown:i,attention:s}}return n.length>0?{grade:"DEGRADED",value:"Degraded",sub:l(n),tone:"warn",failed:o,degraded:n,unknown:i,attention:s}:i.length===e.length&&e.length>0?{grade:"UNKNOWN",value:"Unknown",sub:"Health entities unavailable",tone:"muted",failed:o,degraded:n,unknown:i,attention:s}:i.length>0?{grade:"HEALTHY",value:"Nominal",sub:`${i.length} unknown: ${l(i)}`,tone:"ok",failed:o,degraded:n,unknown:i,attention:s}:{grade:"HEALTHY",value:"Nominal",sub:`${e.length} subsystems healthy`,tone:"ok",failed:o,degraded:n,unknown:i,attention:s}}function ur(e,r,t,o,n){let i=null;for(let c of e){if(!c)continue;let l=r[c]?.last_updated;if(!l)continue;let a=Date.parse(l);Number.isFinite(a)&&(i===null||a>i)&&(i=a)}let s=i===null?null:Math.max(0,(o-i)/1e3);return t==="off"?{ageS:s,stale:!0,reason:"telemetry_offline",telemetry:t}:n>0&&s!==null&&s>n?{ageS:s,stale:!0,reason:"age",telemetry:t}:{ageS:s,stale:!1,reason:null,telemetry:t}}function dr(e,r){if(e){let o=typeof e.attributes?.elevation=="number"?e.attributes.elevation:null;if(e.state==="above_horizon")return o!==null&&o<8?"dusk":"day";if(e.state==="below_horizon")return o!==null&&o>-6?"dusk":"night"}let t=r.getHours();return t>=8&&t<18?"day":t>=6&&t<8||t>=18&&t<20?"dusk":"night"}var fe={sun:"M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6",pylon:"M9 22l3-19 3 19M6 22h12M7.2 9h9.6M8.4 14.5h7.2M4 9l3.2 3.5M20 9l-3.2 3.5M5 14.5l3.4 3M19 14.5l-3.4 3",home:"M3.5 11.5L12 4l8.5 7.5M6 10v10h12V10M10 20v-5h4v5",battery:"M7 5.5h10a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 17 21.5H7A1.5 1.5 0 0 1 5.5 20V7A1.5 1.5 0 0 1 7 5.5zM9.5 2.5h5M8.5 13.5h7v5h-7z",clock:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2",plug:"M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v3",target:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",leaf:"M5 19C6 11 11 5 20 4c0 9-5 15-13 15M5 19l7-7",swap:"M4 8h13l-3-3M20 16H7l3 3",heart:"M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",chevron:"M9 6l6 6-6 6",forecast:"M12 6.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v1.6M4.9 4.9l1.2 1.2M19.1 4.9l-1.2 1.2M2 10.5h1.6M20.4 10.5H22M3 19h18M6 22h12",inverter:"M4 5h16v14H4zM8 9h8M8 13h5M16 15.5h.01",alert:"M12 3l10 18H2L12 3zM12 10v5M12 18v.5",moon:"M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"};function f(e,r,t=0){return{x:205+(e-r)*11.258,y:262+(e+r)*6.5-t*13}}function E(e){return e.map(r=>`${r.x.toFixed(1)},${r.y.toFixed(1)}`).join(" ")}function Me(e,r,t,o,n,i){return{top:E([f(e,r,i),f(t,r,i),f(t,o,i),f(e,o,i)]),left:E([f(e,o,n),f(t,o,n),f(t,o,i),f(e,o,i)]),right:E([f(t,r,n),f(t,o,n),f(t,o,i),f(t,r,i)])}}function j(e,r,t,o,n){return E([f(r,e,o),f(t,e,o),f(t,e,n),f(r,e,n)])}function mt(e,r,t,o,n){return E([f(e,r,o),f(e,t,o),f(e,t,n),f(e,r,n)])}function ge(e,r,t,o,n,i){return f(e,t+(n-t)*r,o+(i-o)*r)}function Be(e){if(e.length<4)return"";let r=`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)}`;for(let t=1;t+2<e.length;t+=3){let o=e[t],n=e[t+1],i=e[t+2];r+=` C ${o.x.toFixed(1)} ${o.y.toFixed(1)}, ${n.x.toFixed(1)} ${n.y.toFixed(1)}, ${i.x.toFixed(1)} ${i.y.toFixed(1)}`}return r}var J={x0:-1,y0:-3,x1:7,y1:3,z:4.2,ridgeZ:6.6,ridgeY:0},fr={x0:7,y0:-1,x1:11,y1:3,z:2.5},he={x0:-6.2,y0:4.2,x1:-4.6,y1:5.4,z:2.4},se={x0:5.3,x1:6.3,z0:1.25,z1:2.45,y:J.y1},K=f(10.6,-4.8),bt=(()=>{let e=f((se.x0+se.x1)/2,se.y,(se.z0+se.z1)/2);return{x:e.x+1,y:e.y+2}})(),ee={solar:{x:8,y:10,w:150,h:58,port:{x:58,y:68}},grid:{x:246,y:22,w:146,h:58,port:{x:330,y:80}},home:{x:214,y:176,w:140,h:54,port:{x:236,y:230}},battery:{x:8,y:388,w:184,h:70,port:{x:108,y:388}}};var hr=12;function lo(e,r=hr){if(e.length<2)return"";let t=s=>`${s.x.toFixed(1)} ${s.y.toFixed(1)}`,o=(s,c)=>Math.hypot(c.x-s.x,c.y-s.y),n=(s,c,l)=>{let a=o(s,c)||1;return{x:s.x+(c.x-s.x)*l/a,y:s.y+(c.y-s.y)*l/a}},i=`M ${t(e[0])}`;for(let s=1;s<e.length-1;s++){let c=e[s-1],l=e[s],a=e[s+1],p=Math.min(r,o(c,l)/2,o(l,a)/2);i+=` L ${t(n(l,c,p))} Q ${t(l)} ${t(n(l,a,p))}`}return i+=` L ${t(e[e.length-1])}`,i}var ao={main_pv:{x:610,y:335,label:"Array 1 (main roof)"},main_pv_frame:{x:700,y:409,label:"Array 1 frame connection"},main_pv_edge:{x:751,y:380,label:"Array 1 frame corner / cable exit"},garage_pv:{x:1140,y:500,label:"Array 2 (garage roof)"},garage_pv_frame:{x:1044,y:508,label:"Array 2 frame connection"},garage_pv_edge:{x:1044,y:537,label:"Array 2 cable exit (fascia)"},battery_cabinet:{x:150,y:512,label:"Battery cabinet"},inverter:{x:1002,y:624,label:"Inverter underside entry"},ground_entry:{x:1002,y:722,label:"Ground convergence"},building_corner:{x:948,y:600,label:"Building corner"},chimney:{x:952,y:300,label:"Chimney (service drop landing)"},fascia_start:{x:782,y:455,label:"Fascia (right of the skylight)"},lawn_transition:{x:230,y:556,label:"Buried lawn crossing (level run)"},downpipe:{x:748,y:620,label:"Downpipe / service wall"},door_post:{x:1104,y:640,label:"Garage wall line (left of the door)"},ev_charger:{x:1048,y:655,label:"EV charger"},pylon:{x:1297,y:290,label:"Grid pylon"},house:{x:752,y:600,label:"House connection"}};var co={grid:{x:990,ground:700,side:"left"},solarMain:{x:996,ground:704,side:"left"},home:{x:1002,ground:708,side:"left"},battery:{x:1008,ground:742,side:"left"},solarGarage:{x:1014,ground:746,side:"right"}},gr=[{label:"rear garden path",points:[{x:110,y:514},{x:310,y:502}]},{label:"lawn crossing (buried, level)",points:[{x:150,y:556},{x:310,y:556}]},{label:"patio left corner drop",points:[{x:310,y:556},{x:310,y:570}]},{label:"patio front edge",points:[{x:310,y:570},{x:520,y:647}]},{label:"terrace front wall",points:[{x:520,y:647},{x:548,y:682}]},{label:"upper landing edge",points:[{x:548,y:682},{x:700,y:692}]},{label:"step 1 riser",points:[{x:560,y:694},{x:700,y:699}]},{label:"step 2 riser",points:[{x:575,y:707},{x:690,y:711}]},{label:"lower path",points:[{x:575,y:721},{x:790,y:742}]},{label:"drive paving",points:[{x:790,y:742},{x:1022,y:742}]}],yr=["cabinet base","out of the cabinet front onto the lawn","end of the level buried crossing","patio left corner","patio front edge, lawn border","terrace front wall foot","across the upper landing","down step 1 onto the tread","along the tread","down step 2 onto the lower paving","lower path and drive paving to the ground convergence","riser into the inverter"],pr=624;function xt(e){let r=ao,t=co,o=150*e,n=58*e,i=178*e,s=72*e,c=140*e,l=54*e,a={solar:{x:35,y:95,w:o,h:n,port:{x:35+o,y:95+n*.5}},grid:{x:1410-o,y:95,w:o,h:n,port:{x:r.pylon.x,y:95+n}},battery:{x:35,y:718,w:i,h:s,port:{x:r.battery_cabinet.x,y:718}},home:{x:690,y:884,w:c,h:l,port:{x:745,y:884}}},p=u=>[{x:t[u].x,y:t[u].ground},{x:t[u].x,y:pr}],d={solarInfo:[a.solar.port,{x:430,y:a.solar.port.y},{x:545,y:275}],solarMain:[r.main_pv_frame,r.main_pv_edge,{x:r.fascia_start.x,y:r.main_pv_edge.y},r.fascia_start,{x:946,y:505},{x:946,y:t.solarMain.ground},...p("solarMain")],solarGarage:[r.garage_pv_frame,r.garage_pv_edge,{x:r.door_post.x,y:554},{x:r.door_post.x,y:t.solarGarage.ground},...p("solarGarage")],batteryInfo:[a.battery.port,r.battery_cabinet],battery:[r.battery_cabinet,{x:150,y:556},{x:310,y:556},{x:310,y:570},{x:520,y:647},{x:548,y:682},{x:620,y:682},{x:620,y:707},{x:640,y:707},{x:640,y:723},...p("battery")],gridInfo:[a.grid.port,r.pylon],grid:[r.pylon,{x:r.chimney.x,y:r.pylon.y},{x:r.chimney.x,y:t.grid.ground},...p("grid")],home:[{x:t.home.x,y:pr},{x:t.home.x,y:t.home.ground},{x:760,y:t.home.ground},{x:760,y:r.house.y}],homeInfo:[{x:745,y:r.house.y+6},a.home.port]};return{width:1448,height:1086,scale:e,pills:a,inverter:r.inverter,anchors:r,entry:{x0:964,x1:1022,y0:696,y1:752},routes:d,bend:{battery:5,home:8,solarMain:8,solarGarage:8,grid:8},paths:()=>Object.fromEntries(Object.keys(d).map(u=>[u,lo(d[u],{battery:5,home:8,solarMain:8,solarGarage:8,grid:8}[u]??hr)]))}}function mr(e){return e<520?3.2:e<760?2.8:e<1100?2.3:2}var An=xt(2);function br(){let e=bt,r=ge(.2,.08,J.y1,J.z,J.ridgeY,J.ridgeZ),t=Be([ee.solar.port,{x:58,y:120},{x:150,y:150},r,{x:r.x+16,y:r.y+20},{x:e.x-24,y:e.y-26},e]),o=f(he.x1,(he.y0+he.y1)/2,he.z*.72),n=Be([{x:o.x+2,y:o.y},{x:o.x+40,y:o.y-2},{x:e.x-60,y:e.y+28},{x:e.x-24,y:e.y+24},{x:e.x-10,y:e.y+22},{x:e.x-4,y:e.y+12},e]),i={x:K.x-4,y:K.y-118},s=Be([ee.grid.port,{x:330,y:112},{x:i.x-30,y:i.y+10},{x:i.x-22,y:i.y+44},{x:i.x-14,y:K.y-6},{x:K.x-30,y:K.y+30},{x:300,y:K.y+40},{x:272,y:K.y+36},{x:e.x+10,y:e.y+24},e]),c=Be([e,{x:e.x+10,y:e.y-24},{x:e.x-12,y:e.y-48},ee.home.port]);return{solar:t,battery:n,grid:s,home:c}}var uo=15,U={solar:"#f7c948",battery:"#35e08a",grid:"#3ea6ff",home:"#22d3ee"};function $r(e,r,t,o,n){let i=o/24;return b`<g transform="translate(${r} ${t}) scale(${i})" fill="none" stroke=${n} stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d=${fe[e]}></path></g>`}function po(){let e=[f(-8,-6),f(10,-6),f(10,10),f(-8,10)],r=12,t=[e[3],e[2],{x:e[2].x,y:e[2].y+r},{x:e[3].x,y:e[3].y+r}],o=[e[2],e[1],{x:e[1].x,y:e[1].y+r},{x:e[2].x,y:e[2].y+r}],n=[f(8.2,3.05),f(10.6,3.05),f(10.6,10),f(8.2,10)],i=[f(2.2,3.05),f(3.2,3.05),f(3.2,5.6),f(-4.2,5.6),f(-4.2,4.6),f(2.2,4.6)];return b`
    <g class="ground">
      <polygon points=${E(t)} class="ground-side"></polygon>
      <polygon points=${E(o)} class="ground-side ground-side-r"></polygon>
      <polygon points=${E(e)} class="ground-top"></polygon>
      <polygon points=${E(e)} fill="url(#ef3d-ground-sheen)"></polygon>
      <polygon points=${E(n)} class="drive"></polygon>
      <polygon points=${E(i)} class="drive path"></polygon>
      ${fo()}
    </g>`}function fo(){let e=[];for(let r=0;r<6;r++){let t=-5+r*2.6;e.push(b`<polygon points=${E([f(-7.6,t),f(-1.6,t),f(-1.6,t+1.3),f(-7.6,t+1.3)])} class="lawn-stripe"></polygon>`)}return e}function je(e,r,t,o=""){let n=f(e,r);return b`
    <g class="tree ${o}">
      <ellipse cx=${n.x} cy=${n.y+2} rx=${t*.9} ry=${t*.38} class="tree-shadow"></ellipse>
      <rect x=${n.x-1.4} y=${n.y-t*1.1} width="2.8" height=${t*1.1} class="trunk"></rect>
      <circle cx=${n.x-t*.35} cy=${n.y-t*1.15} r=${t*.78} class="canopy c2"></circle>
      <circle cx=${n.x+t*.4} cy=${n.y-t*1.25} r=${t*.82} class="canopy c3"></circle>
      <circle cx=${n.x} cy=${n.y-t*1.7} r=${t*.86} class="canopy c1"></circle>
    </g>`}function ye(e,r,t){let o=f(e,r);return b`<g class="shrub"><ellipse cx=${o.x} cy=${o.y} rx=${t} ry=${t*.62} class="canopy c2"></ellipse><ellipse cx=${o.x-t*.4} cy=${o.y-t*.25} rx=${t*.7} ry=${t*.45} class="canopy c1"></ellipse></g>`}function $t(e,r){let t=f(e,r);return b`<g class="lamp"><line x1=${t.x} y1=${t.y} x2=${t.x} y2=${t.y-9} class="lamp-post"></line><circle cx=${t.x} cy=${t.y-10} r="2.2" class="lamp-light"></circle><circle cx=${t.x} cy=${t.y-10} r="6" class="lamp-halo"></circle></g>`}function ho(){let e=J,r=Me(e.x0,e.y0,e.x1,e.y1,0,e.z),t=[f(e.x0-.5,e.y1+.5,e.z-.25),f(e.x1+.5,e.y1+.5,e.z-.25),f(e.x1+.5,e.ridgeY,e.ridgeZ),f(e.x0-.5,e.ridgeY,e.ridgeZ)],o=[f(e.x0-.5,e.y0-.5,e.z-.25),f(e.x1+.5,e.y0-.5,e.z-.25),f(e.x1+.5,e.ridgeY,e.ridgeZ),f(e.x0-.5,e.ridgeY,e.ridgeZ)],n=[f(e.x1,e.y0,e.z),f(e.x1,e.y1,e.z),f(e.x1,e.ridgeY,e.ridgeZ)],i=[f(e.x1+.5,e.y1+.5,e.z-.25),f(e.x1+.5,e.y1+.5,e.z-.55),f(e.x1+.5,e.ridgeY,e.ridgeZ-.3),f(e.x1+.5,e.ridgeY,e.ridgeZ)],s=fr,c=Me(s.x0,s.y0,s.x1,s.y1,0,s.z),l=Me(s.x0-.15,s.y0-.15,s.x1+.15,s.y1+.15,s.z,s.z+.18);return b`
    <g class="house">
      <!-- soft contact shadow -->
      <polygon points=${E([f(e.x0-.6,e.y0-.2),f(s.x1+.9,s.y0-.2),f(s.x1+.9,s.y1+.9),f(e.x0-.6,e.y1+.9)])} class="contact-shadow"></polygon>
      <!-- garage (behind the house's right face order-wise it sits in front, draw after walls) -->
      <polygon points=${r.right} class="wall wall-r"></polygon>
      <polygon points=${E(n)} class="wall wall-r gable"></polygon>
      <polygon points=${r.left} class="wall wall-l"></polygon>
      <!-- windows and door on the front-left wall -->
      <polygon points=${j(e.y1+.02,.2,1.6,1.5,3.2)} class="window"></polygon>
      <polygon points=${j(e.y1+.02,2,3.4,1.5,3.2)} class="window"></polygon>
      <polygon points=${j(e.y1+.02,.2,1.6,.4,1.1)} class="window small"></polygon>
      <polygon points=${j(e.y1+.02,2.3,3.1,0,1.15)} class="door"></polygon>
      <polygon points=${j(e.y1+.02,3.9,4.8,1.5,3.2)} class="window"></polygon>
      <!-- windows on the right wall -->
      <polygon points=${mt(e.x1+.02,-2.4,-1.2,1.5,3.2)} class="window"></polygon>
      <polygon points=${mt(e.x1+.02,-2.4,-1.2,.3,1.1)} class="window small"></polygon>
      <!-- garage -->
      <polygon points=${c.right} class="wall wall-r"></polygon>
      <polygon points=${c.left} class="wall wall-l"></polygon>
      <polygon points=${j(s.y1+.02,7.6,10.4,0,1.9)} class="garage-door"></polygon>
      ${[.45,.9,1.35].map(a=>b`<polyline points=${E([f(7.6,s.y1+.03,a),f(10.4,s.y1+.03,a)])} class="garage-line"></polyline>`)}
      <polygon points=${c.top} class="roof-flat"></polygon>
      <polygon points=${l.left} class="roof-lip"></polygon>
      <polygon points=${l.right} class="roof-lip"></polygon>
      <polygon points=${l.top} class="roof-flat-top"></polygon>
      <!-- roof -->
      <polygon points=${E(o)} class="roof roof-back"></polygon>
      <polygon points=${E(t)} class="roof roof-front"></polygon>
      <polygon points=${E(i)} class="fascia"></polygon>
      <polyline points=${E([f(e.x0-.5,e.ridgeY,e.ridgeZ),f(e.x1+.5,e.ridgeY,e.ridgeZ)])} class="ridge"></polyline>
      ${go()}
      ${yo()}
    </g>`}function go(){let e=J,r=[],t=5,o=2,n=e.x0+.25,i=e.x1-.75,s=.14,c=(i-n-s*(t-1))/t,l=.16,a=.9,p=.05,d=(a-l-p*(o-1))/o;for(let u=0;u<o;u++)for(let h=0;h<t;h++){let y=n+h*(c+s),g=y+c,M=l+u*(d+p),k=M+d,x=[ge(y,M,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ge(g,M,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ge(g,k,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),ge(y,k,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ)].map(v=>({x:v.x,y:v.y-1.2}));r.push(b`<polygon points=${E(x)} class="pv"></polygon>`),r.push(b`<polygon points=${E(x)} fill="url(#ef3d-pv-glare)" class="pv-glare"></polygon>`);let C=(v,w,T)=>({x:v.x+(w.x-v.x)*T,y:v.y+(w.y-v.y)*T});for(let v of[1/3,2/3])r.push(b`<line x1=${C(x[0],x[3],v).x} y1=${C(x[0],x[3],v).y} x2=${C(x[1],x[2],v).x} y2=${C(x[1],x[2],v).y} class="pv-line"></line>`),r.push(b`<line x1=${C(x[0],x[1],v).x} y1=${C(x[0],x[1],v).y} x2=${C(x[3],x[2],v).x} y2=${C(x[3],x[2],v).y} class="pv-line"></line>`)}return r}function yo(){let e=se,r=j(e.y+.03,e.x0,e.x1,e.z0,e.z1),t=f(e.x1-.18,e.y+.05,e.z1-.22),o=n=>E([f(e.x0+.18,e.y+.05,n),f(e.x1-.18,e.y+.05,n)]);return b`
    <g class="inverter">
      <polygon points=${r} class="inverter-face"></polygon>
      <polyline points=${o(e.z0+.3)} class="inverter-vent"></polyline>
      <polyline points=${o(e.z0+.5)} class="inverter-vent"></polyline>
      <circle cx=${t.x} cy=${t.y} r="1.6" class="inverter-led"></circle>
      <circle cx=${t.x} cy=${t.y} r="4" class="inverter-led-halo"></circle>
    </g>`}function mo(e){let r=he,t=Me(r.x0,r.y0,r.x1,r.y1,0,r.z),o=r.x0+.18,n=.16,i=.3,s=r.z-.3,c=e===null?i:i+Math.max(0,Math.min(100,e))/100*(s-i),l=f((r.x0+r.x1)/2+.15,r.y1+.04,r.z*.56);return b`
    <g class="battery-cabinet">
      <ellipse cx=${f((r.x0+r.x1)/2,(r.y0+r.y1)/2).x} cy=${f((r.x0+r.x1)/2,(r.y0+r.y1)/2).y+3} rx="20" ry="7" class="contact-shadow soft"></ellipse>
      <polygon points=${t.right} class="cab cab-r"></polygon>
      <polygon points=${t.left} class="cab cab-l"></polygon>
      <polygon points=${t.top} class="cab cab-t"></polygon>
      <polygon points=${j(r.y1+.03,o,o+n,i,s)} class="cab-strip-bg"></polygon>
      ${e===null?m:b`<polygon points=${j(r.y1+.04,o,o+n,i,c)} class="cab-strip"></polygon>`}
      <text x="0" y="0" class="cab-label" transform=${`matrix(0.866 0.5 0 1 ${l.x.toFixed(1)} ${l.y.toFixed(1)})`}>ECCO</text>
    </g>`}function bo(e,r){let t=K,o=118,n={x:t.x-4,y:t.y-o},i=18,s=(p,d)=>b`<line x1=${t.x-4-d} y1=${p} x2=${t.x-4+d} y2=${p} class="pylon-line"></line>`,c=b`
    <line x1=${t.x-i} y1=${t.y} x2=${n.x-2} y2=${n.y} class="pylon-line"></line>
    <line x1=${t.x+i-8} y1=${t.y} x2=${n.x+2} y2=${n.y} class="pylon-line"></line>
    <line x1=${t.x-i+5} y1=${t.y-2} x2=${n.x} y2=${n.y+4} class="pylon-line thin"></line>
    <line x1=${t.x+i-12} y1=${t.y-2} x2=${n.x} y2=${n.y+4} class="pylon-line thin"></line>`,l=[];for(let p=1;p<7;p++){let d=t.y-o/7*p,u=(i-8)*(1-p/8)+3;l.push(b`<line x1=${t.x-4-u} y1=${d} x2=${t.x-4+u} y2=${d-6} class="pylon-line thin"></line>`),l.push(b`<line x1=${t.x-4+u} y1=${d} x2=${t.x-4-u} y2=${d-6} class="pylon-line thin"></line>`)}let a=[n.y+24,n.y+44].map(p=>b`<path d=${`M ${(t.x-4-26).toFixed(1)} ${p} Q ${(t.x+30).toFixed(1)} ${p+18} ${410} ${p-12}`} class="wire"></path>`);return b`
    <g class=${`pylon ${e?"live":""} ${r?"unknown":""}`}>
      ${c}${l}
      ${s(n.y+22,26)}${s(n.y+42,20)}
      ${a}
      <circle cx=${n.x} cy=${n.y-2} r="3" class="pylon-tip"></circle>
    </g>`}function Re(e,r,t,o,n,i=1,s=0,c=""){let{edge:l,motion:a}=o,p=U[e],d=i>1,u=`flow flow-${e} route-${r} ${d?"fine":""} ${l.unknown?"unknown":""} ${l.idle?"idle":""} ${a.moving&&n?"moving":""} ${l.reversed?"reversed":""}`,h=`ef3d-path-${r}`,y=d&&s>0?Math.max(1,Math.round(s/520)):1,g=a.ballCount*y,M=a.intensity,k=[];if(a.moving&&n){let v=d?(1.7+M*1)*i:a.ballRadiusPx;for(let w=0;w<g;w++)k.push(b`
        <g class="pulse" data-path=${h} data-duration=${(a.ballDurationS*(d?1.6:1)).toFixed(3)} data-phase=${(w/g).toFixed(3)} data-reversed=${l.reversed?"1":"0"} style=${`--pulse-colour:${p}`}>
          <circle r=${(v*(d?2.6:1.9)).toFixed(2)} class="pulse-halo"></circle>
          <circle r=${v.toFixed(2)} class="pulse-glow"></circle>
          <circle r=${(v*.45).toFixed(2)} class="pulse-core"></circle>
        </g>`)}let R=[];if(a.moving&&!n)for(let v of[.3,.55,.8])R.push(b`<g class="chevron" data-path=${h} data-phase=${v} data-reversed=${l.reversed?"1":"0"} style=${`--pulse-colour:${p}`}><path d="M -4 -4 L 2 0 L -4 4" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" transform=${`scale(${i})`}></path></g>`);if(d){let v=(.95+M*.35)*i,w=(3.4+M*2)*i,T=a.moving?.1+M*.16:0,O=a.moving?.3+M*.3:0,$=a.moving?.45+M*.3:.25;return b`
      <g class=${u} style=${`--flow-colour:${p}`}>
        <path d=${t} class="fine-base" style=${`stroke-width:${v.toFixed(2)}`}></path>
        <path d=${t} class="fine-glow" style=${`stroke-width:${w.toFixed(2)}; opacity:${T.toFixed(2)}`}></path>
        <path id=${h} d=${t} class="fine-highlight" style=${`stroke-width:${(.6*i).toFixed(2)}; opacity:${O.toFixed(2)}`}></path>
        ${c?b`<path d=${c} class="fine-riser" style=${`stroke-width:${(.95*i).toFixed(2)}; opacity:${$.toFixed(2)}`}></path>`:m}
        ${k}${R}
      </g>`}let x=a.moving?`stroke-dasharray:${a.dashLen.toFixed(1)} ${a.gapLen.toFixed(1)}; animation-duration:${a.dashDurationS.toFixed(2)}s; stroke-width:${a.packetWidthPx.toFixed(2)}; opacity:${a.packetOpacity.toFixed(2)}; --dash-travel:${(-2*uo).toFixed(1)}`:"",C=a.moving?`stroke-width:${(a.packetWidthPx*2.6).toFixed(1)}; opacity:${(.18+a.intensity*.3).toFixed(2)}`:"";return b`
    <g class=${u} style=${`--flow-colour:${p}`}>
      <path d=${t} class="flow-base" style=${`stroke-width:${a.baseWidthPx.toFixed(2)}`}></path>
      <path d=${t} class="flow-dots"></path>
      <path d=${t} class="flow-glow" style=${C}></path>
      <path id=${h} d=${t} class="flow-packets" style=${x}></path>
      ${k}${R}
    </g>`}function Ge(e,r,t,o,n){return b`<g class=${`info-link info-${e} ${o?"active":""}`} style=${`--flow-colour:${t}`}>
    <path d=${r} class="info-glow" style=${`stroke-width:${(2.4*n).toFixed(2)}`}></path>
    <path d=${r} class="info-line" style=${`stroke-width:${(.7*n).toFixed(2)}`}></path>
  </g>`}function xo(e,r){return b`<g class="cable-pit">
    <rect x=${e.x0} y=${e.y0} width=${e.x1-e.x0} height=${e.y1-e.y0} rx=${2*r} class="pit-shadow"></rect>
    <rect x=${e.x0} y=${e.y0} width=${e.x1-e.x0} height=${e.y1-e.y0} rx=${2*r} class="pit-face"></rect>
  </g>`}function Te(e,r,t,o){return b`<g class=${`node-light ${t?"active":""}`} style=${`--flow-colour:${r}`}><circle cx=${e.x} cy=${e.y} r=${(5*o).toFixed(1)} class="node-light-halo"></circle><circle cx=${e.x} cy=${e.y} r=${(1.6*o).toFixed(1)} class="node-light-core"></circle></g>`}function $o(e){let r=e.match(/-?\d+(\.\d+)?/g)?.map(Number)??[],t=0;for(let o=2;o+1<r.length;o+=2)t+=Math.hypot(r[o]-r[o-2],r[o+1]-r[o-1]);return t/1.9}function te(e,r,t,o,n,i=1){let s=U[e],c=14*i,l=e==="battery",a=19*i,p=2*Math.PI*a,d=t.soc??null,u=d===null?0:Math.max(0,Math.min(100,d))/100*p,h=r.x+52*i,y=r.x+r.w-30*i,g=r.y+r.h/2,M=n.edge.unknown?"unknown":n.edge.idle?"idle":"active";return b`
    <g class=${`pill pill-${e} tone-${t.tone} ${M} ${t.clickable?"clickable":""}`}
       style=${`--pill-colour:${s}`}
       role=${t.clickable?"button":"img"}
       tabindex=${t.clickable?0:-1}
       aria-label=${`${t.label}: ${t.value}${t.sub?", "+t.sub:""}`}
       @click=${()=>o(e)}
       @keydown=${k=>{(k.key==="Enter"||k.key===" ")&&(k.preventDefault(),o(e))}}>
      <rect x=${r.x} y=${r.y} width=${r.w} height=${r.h} rx=${c} class="pill-bg"></rect>
      <rect x=${r.x} y=${r.y} width=${r.w} height=${r.h} rx=${c} class="pill-border"></rect>
      <circle cx=${r.x+27*i} cy=${r.y+r.h/2} r=${15*i} class="pill-icon-bg"></circle>
      ${$r(t.icon,r.x+16*i,r.y+r.h/2-11*i,22*i,s)}
      <text x=${h} y=${r.y+19*i} class="pill-label">${t.label}</text>
      <text x=${h} y=${r.y+(t.sub?39:42)*i} class="pill-value">${t.value}</text>
      ${t.sub?b`<text x=${h} y=${r.y+(t.extra?52:r.h/i-8)*i} class="pill-sub">${t.sub}</text>`:m}
      ${t.extra?b`<text x=${h} y=${r.y+r.h-9*i} class="pill-extra">${t.extra}</text>`:m}
      ${l?b`
            <circle cx=${y} cy=${g} r=${a} class="ring-track"></circle>
            ${d===null?m:b`<circle cx=${y} cy=${g} r=${a} class="ring-fill" stroke-dasharray=${`${u.toFixed(1)} ${p.toFixed(1)}`} transform=${`rotate(-90 ${y} ${g})`}></circle>`}
            <text x=${y} y=${g+4*i} class="ring-value">${d===null?"--":`${Math.round(d)}%`}</text>
            <text x=${y} y=${g+14*i} class="ring-caption">SOC</text>`:t.clickable?$r("chevron",r.x+r.w-24*i,r.y+r.h/2-8*i,16*i,"rgba(255,255,255,0.45)"):m}
    </g>`}function wr(e){if(e.artwork)return wo(e,e.artwork);let r=br(),t=e.flows.grid.motion.moving,o=bt;return b`
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
        ${[[40,92],[122,46],[180,112],[236,70],[352,150],[392,60],[20,160],[288,20]].map(([n,i])=>b`<circle cx=${n} cy=${i} r="1.1" class="star"></circle>`)}
      </g>
      ${po()}
      ${je(-6.5,-4.6,13,"back")}
      ${je(-2.5,-5.2,10,"back")}
      ${je(9.5,-5.6,11,"back")}
      ${ye(-7.2,1.2,8)}
      ${ye(-6.6,-1,7)}
      ${ye(5,5.2,7)}
      ${ye(6.4,6.4,6)}
      ${ye(-1.5,7.2,8)}
      ${$t(-4.8,6.6)}
      ${$t(3.9,5.2)}
      ${$t(7.4,8.6)}
      ${bo(t,e.flows.grid.edge.unknown)}
      ${ho()}
      ${mo(e.pills.battery.soc??null)}
      ${je(-7.6,8.6,12,"front")}
      ${ye(1.2,8.8,7)}
      <g class="flows">
        ${Re("grid","grid",r.grid,e.flows.grid,e.animate)}
        ${Re("solar","solar",r.solar,e.flows.solar,e.animate)}
        ${Re("battery","battery",r.battery,e.flows.battery,e.animate)}
        ${Re("home","home",r.home,e.flows.home,e.animate)}
        <circle cx=${o.x} cy=${o.y} r="4.2" class=${`junction led-${e.inverterLed}`}></circle>
        <circle cx=${o.x} cy=${o.y} r="9" class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${te("solar",ee.solar,e.pills.solar,e.onPill,e.flows.solar)}
      ${te("grid",ee.grid,e.pills.grid,e.onPill,e.flows.grid)}
      ${te("home",ee.home,e.pills.home,e.onPill,e.flows.home)}
      ${te("battery",ee.battery,e.pills.battery,e.onPill,e.flows.battery)}
    </svg>`}function wo(e,r){let t=r.layout,o=t.paths(),n=t.scale,i=t.anchors,s=e.solarSplit??{card:e.flows.solar,main:e.flows.solar,garage:null},c=u=>{let h=t.routes[u],[y,g]=u==="home"?[h[0],h[1]]:[h[h.length-2],h[h.length-1]];return`M ${y.x} ${y.y} L ${g.x} ${g.y}`},l=(u,h,y)=>Re(u,h,o[h],y,e.animate,n,$o(o[h]),c(h)),a=u=>!!u&&u.motion.moving,p=Object.entries(t.routes),d=r.debug?b`<g class="debug">
        ${gr.map(u=>b`<polyline points=${u.points.map(h=>`${h.x},${h.y}`).join(" ")} class="debug-paving"></polyline><text x=${u.points[0].x+4*n} y=${u.points[0].y-4*n} class="debug-paving-label">${u.label}</text>`)}
        ${t.routes.battery.map((u,h)=>b`<circle cx=${u.x} cy=${u.y} r=${5*n} class="debug-waypoint"></circle><text x=${u.x+7*n} y=${u.y+4*n} class="debug-waypoint-label">${h+1} ${yr[h]??""}</text>`)}
        <line x1=${t.routes.battery[1].x} y1=${t.routes.battery[1].y} x2=${t.routes.battery[2].x} y2=${t.routes.battery[2].y} class="debug-buried"></line>
        ${p.map(([u,h])=>h.map((y,g)=>g===0||g===h.length-1?m:b`<rect x=${y.x-3*n} y=${y.y-3*n} width=${6*n} height=${6*n} class="debug-bend" data-route=${u}></rect>`))}
        ${Object.values(i).map(u=>b`<circle cx=${u.x} cy=${u.y} r=${4*n} class="debug-dot"></circle><circle cx=${u.x} cy=${u.y} r=${9*n} class="debug-ring"></circle><text x=${u.x+11*n} y=${u.y-6*n} class="debug-label">${u.label} ${u.x},${u.y}</text>`)}
        ${Object.entries(t.pills).map(([u,h])=>b`<rect x=${h.x} y=${h.y} width=${h.w} height=${h.h} class="debug-zone"></rect><circle cx=${h.port.x} cy=${h.port.y} r=${3.5*n} class="debug-port"></circle><text x=${h.port.x+8*n} y=${h.port.y+4*n} class="debug-label">${u} port</text>`)}
        <rect x=${t.entry.x0} y=${t.entry.y0} width=${t.entry.x1-t.entry.x0} height=${t.entry.y1-t.entry.y0} class="debug-zone"></rect>
        <text x=${t.entry.x1+6*n} y=${t.entry.y1+4*n} class="debug-label">ground convergence ${i.ground_entry.x},${i.ground_entry.y}</text>
        <rect x=${t.entry.x0+2} y=${t.inverter.y} width=${t.entry.x1-t.entry.x0-4} height=${t.entry.y0-t.inverter.y} class="debug-riser"></rect>
        <text x=${t.entry.x1+6*n} y=${(t.inverter.y+t.entry.y0)/2} class="debug-label">grouped riser (5 tracks)</text>
        <line x1=${t.inverter.x-30} y1=${t.inverter.y} x2=${t.inverter.x+30} y2=${t.inverter.y} class="debug-entry"></line>
      </g>`:m;return b`
    <svg class=${`scene artwork ${e.daylight} ${e.stale?"stale":""} ${e.animate?"":"still"}`} viewBox=${`0 0 ${t.width} ${t.height}`} preserveAspectRatio="xMidYMid meet" style=${`--k:${n}`} aria-label="Energy flow scene">
      <defs>
        <filter id="ef3d-blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation=${(1.6*n).toFixed(1)}></feGaussianBlur></filter>
        <filter id="ef3d-blur-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=${(3.5*n).toFixed(1)}></feGaussianBlur></filter>
      </defs>
      ${r.layers.map(u=>b`<image href=${u.url} x="0" y="0" width=${t.width} height=${t.height} preserveAspectRatio="xMidYMid meet" class=${`plate ${u.entering?"entering":""}`} data-scene=${u.key} @error=${()=>r.onError(u.url)} @load=${()=>r.onLoad(u.url)}></image>`)}
      ${xo(t.entry,n)}
      <g class="flows">
        ${Ge("solar",o.solarInfo,U.solar,a(s.card),n)}
        ${Ge("battery",o.batteryInfo,U.battery,a(e.flows.battery),n)}
        ${Ge("grid",o.gridInfo,U.grid,a(e.flows.grid),n)}
        ${Ge("home",o.homeInfo,U.home,a(e.flows.home),n)}
        ${l("grid","grid",e.flows.grid)}
        ${l("battery","battery",e.flows.battery)}
        ${l("solar","solarMain",s.main)}
        ${s.garage?l("solar","solarGarage",s.garage):m}
        ${l("home","home",e.flows.home)}
        ${Te(i.main_pv_frame,U.solar,a(s.main),n)}
        ${s.garage?Te(i.garage_pv_frame,U.solar,a(s.garage),n):m}
        ${Te(i.battery_cabinet,U.battery,a(e.flows.battery),n)}
        ${Te(i.pylon,U.grid,a(e.flows.grid),n)}
        ${Te(i.house,U.home,a(e.flows.home),n)}
        <rect x=${t.inverter.x-12*n} y=${t.inverter.y-1.2*n} width=${24*n} height=${2.4*n} rx=${1.2*n} class=${`junction-bar led-${e.inverterLed}`}></rect>
        <circle cx=${t.inverter.x} cy=${t.inverter.y} r=${(7*n).toFixed(1)} class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${d}
      ${te("solar",t.pills.solar,e.pills.solar,e.onPill,e.flows.solar,n)}
      ${te("grid",t.pills.grid,e.pills.grid,e.onPill,e.flows.grid,n)}
      ${te("home",t.pills.home,e.pills.home,e.onPill,e.flows.home,n)}
      ${te("battery",t.pills.battery,e.pills.battery,e.onPill,e.flows.battery,n)}
    </svg>`}var vr={bright_summer_day:"00_bright_summer_day.png",soft_clear_day:"01_soft_clear_day.png",misty_morning:"02_misty_morning.png",golden_hour:"03_golden_hour.png",clear_night:"04_clear_night.png",rainy_day:"05_rainy_day.png",storm_night:"06_storm_night.png",winter_clear_day:"07_winter_clear_day.png",christmas_day:"08_christmas_day.png",christmas_night:"09_christmas_night.png"},_r=Object.keys(vr);function vo(e,r){return e===12||e===1&&r<=3}function _o(e){return e.sunUp!==null?!e.sunUp:e.weather==="clear-night"?!0:e.hour<7||e.hour>=19}function ko(e){return e.elevation===null||e.elevation<-6||e.elevation>15?!1:e.rising!==null?!e.rising:e.hour>=15}function kr(e){let r=_o(e),t=(e.weather??"").toLowerCase();return vo(e.month,e.day)?r?"christmas_night":"christmas_day":!r&&(t==="snowy"||t==="snowy-rainy")?"winter_clear_day":r&&(t==="lightning"||t==="lightning-rainy"||t==="exceptional")?"storm_night":!r&&(t==="rainy"||t==="pouring")?"rainy_day":!r&&t==="fog"?"misty_morning":ko(e)?"golden_hour":t==="clear-night"||r&&["sunny","partlycloudy","cloudy","windy",""].includes(t)||r?"clear_night":t==="partlycloudy"?"soft_clear_day":t==="sunny"||t==="windy"||t==="clear"?"bright_summer_day":"soft_clear_day"}function Sr(e,r,t){let o=t?.[r]??vr[r];return/^(\/|\.|[a-z]+:)/i.test(o)&&t?.[r]?o:(e.endsWith("/")?e:e+"/")+o}var So=15e3,z=class extends X{constructor(){super(...arguments);this._detailsOpen=!1;this._nowMs=Date.now();this._layers=[];this._failedPlates=new Set;this._fadeTimer=0;this._widthPx=0;this._raf=0;this._timer=0;this._lengthCache=new WeakMap;this._onMotionPref=()=>{this.requestUpdate()}}static getStubConfig(){return{type:"custom:ecco-flow-3d-card",title:"Energy Flow",subtitle:"Live power overview",nodes:{solar:[{label:"Array 1",power:"sensor.pv1_power"}],inverter:{power:"sensor.inverter_power"},home:{power:"sensor.house_power"},battery:{power:"sensor.battery_power",soc:"sensor.battery_soc",power_sign:"charge_positive"},grid:{power:"sensor.grid_power",power_sign:"import_positive"}}}}setConfig(t){Gt(t),this._config=t,this._failedPlates=new Set}_resolveScene(t,o){let n=this._config?.scene;if(!n?.pack)return null;let i=this._config?.ecco??{},s=i.sun?t[i.sun]:void 0,c=typeof s?.attributes?.elevation=="number"?s.attributes.elevation:null,l=typeof s?.attributes?.rising=="boolean"?s.attributes.rising:null,p=(n.force&&_r.includes(n.force)?n.force:null)??kr({month:o.getMonth()+1,day:o.getDate(),sunUp:s?s.state==="above_horizon"?!0:s.state==="below_horizon"?!1:null:null,elevation:c,rising:l,weather:i.weather?A(t,i.weather):void 0,hour:o.getHours()});return{key:p,url:Sr(n.pack,p,n.scenes)}}willUpdate(){let t=this._resolveScene(this.hass?.states??{},new Date(this._nowMs));if(!t){this._layers.length&&(this._layers=[]);return}let o=this._layers[this._layers.length-1];o&&o.url===t.url||(this._layers=this._layers.length===0?[{url:t.url,key:t.key,entering:!1}]:[...this._layers.slice(-1),{url:t.url,key:t.key,entering:!0}])}_plateLoaded(t){let o=this._layers[this._layers.length-1];!o||o.url!==t||this._layers.length<2||(window.clearTimeout(this._fadeTimer),this._fadeTimer=window.setTimeout(()=>{this._layers=this._layers.filter(n=>n.url===t).map(n=>({...n,entering:!1}))},(this._config?.scene?.crossfade_ms??900)+50))}_plateFailed(t){this._failedPlates.add(t),this.requestUpdate()}getCardSize(){return 8}connectedCallback(){super.connectedCallback(),window.matchMedia&&(this._reducedMotionQuery=window.matchMedia("(prefers-reduced-motion: reduce)"),this._reducedMotionQuery.addEventListener?.("change",this._onMotionPref)),this._timer=window.setInterval(()=>{this._nowMs=Date.now()},So),typeof ResizeObserver<"u"&&(this._resize=new ResizeObserver(t=>{let o=Math.round(t[0]?.contentRect.width??0);o&&Math.abs(o-this._widthPx)>8&&(this._widthPx=o)}),this._resize.observe(this))}disconnectedCallback(){super.disconnectedCallback(),this._reducedMotionQuery?.removeEventListener?.("change",this._onMotionPref),window.clearInterval(this._timer),window.clearTimeout(this._fadeTimer),this._resize?.disconnect(),cancelAnimationFrame(this._raf),this._raf=0}firstUpdated(){this._animate()}updated(t){this._placeChevrons()}get _reducedMotion(){return!!this._reducedMotionQuery?.matches}_moreInfo(t){t&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:t},bubbles:!0,composed:!0}))}render(){let t=this._config;if(!t)return I``;let o=this.hass?.states??{},n=t.nodes??{},i=t.ecco??{},s=new Date(this._nowMs),c=Bt(n.solar),l=c.map(N=>_(o,N.power)),a=Yt(_(o,n.solar_total),l),p=_(o,n.inverter?.power),d=_(o,n.battery?.power),u=d===null?null:Wt(d,n.battery?.power_sign),h=_(o,n.grid?.power),y=h===null?null:Vt(h,n.grid?.power_sign),g=Kt(_(o,n.home?.power),p,y),M=_(o,n.battery?.soc),k=qt({solarW:a,batteryW:u,gridW:y,homeW:g}),R=Object.fromEntries(k.map(N=>[N.id,N])),x=Xt(a,l[0]??null,l[1]??null,c.length),C=B(A(o,i.telemetry_online)),v=ur([...c.map(N=>N.power),n.solar_total,n.inverter?.power,n.battery?.power,n.grid?.power,n.home?.power],o,C,this._nowMs,t.features?.stale_after_s??jt),w=v.stale,T=(t.features?.animate_flow??!0)&&!this._reducedMotion,O=n.battery?.time_to_reserve,$=De(O,Ee(O,_(o,O),H(o,O)?.unit_of_measurement),H(o,O)),P=$&&($.status==="discharging"||$.status==="at_reserve")?ft($):"",F=Qt(u),D=Jt(y),me=B(A(o,n.grid?.connected)),le={solar:{label:"Solar Generation",value:de(a),sub:c.length>1?c.map((N,Ve)=>de(l[Ve]??null)).join(" + "):"",tone:a===null?"muted":"ok",icon:"sun",clickable:!!(n.solar_total??c[0]?.power)},grid:{label:"Grid",value:de(y===null?null:Math.abs(y)),sub:me==="off"?"Disconnected":D==="importing"?"Importing":D==="exporting"?"Exporting":D==="idle"?"Idle":"Unknown",tone:me==="off"?"alert":D==="unknown"?"muted":"ok",icon:"pylon",clickable:!!n.grid?.power},home:{label:"Home Load",value:de(g),sub:"",tone:g===null?"muted":"ok",icon:"home",clickable:!!n.home?.power},battery:{label:"Battery Storage",value:de(u===null?null:Math.abs(u)),sub:F==="charging"?"Charging":F==="discharging"?"Discharging":F==="idle"?"Idle":"Unknown",extra:P,tone:F==="unknown"?"muted":"ok",icon:"battery",clickable:!!(n.battery?.power??n.battery?.soc),soc:M}},S=dr(i.sun?o[i.sun]:void 0,s),vt=this._layers[this._layers.length-1],_t=!!vt&&!this._failedPlates.has(vt.url),Ar={daylight:S,artwork:_t?{layers:this._layers,layout:xt(mr(this._widthPx||this.getBoundingClientRect().width||1200)),onError:N=>this._plateFailed(N),onLoad:N=>this._plateLoaded(N),debug:!!t.scene?.debug_anchors}:void 0,solarSplit:_t?{card:{edge:x.card,motion:Z(x.card,w)},main:{edge:x.main,motion:Z(x.main,w)},garage:x.garage?{edge:x.garage,motion:Z(x.garage,w)}:null}:void 0,flows:{solar:{edge:R.solar,motion:Z(R.solar,w)},battery:{edge:R.battery,motion:Z(R.battery,w)},grid:{edge:R.grid,motion:Z(R.grid,w)},home:{edge:R.home,motion:Z(R.home,w)}},stale:w,animate:T,pills:le,inverterLed:w?"warn":k.some(N=>!N.unknown)?"ok":"off",onPill:N=>{let Ve=N==="solar"?n.solar_total??c[0]?.power:N==="grid"?n.grid?.power:N==="home"?n.home?.power:n.battery?.power??n.battery?.soc;this._moreInfo(Ve)}},Er=Zt(k)&&!w,We=this._chip(C,v.ageS,w,v.reason);return I`
      <ha-card style=${`--ef-crossfade:${t.scene?.crossfade_ms??900}ms`}>
        <div class="card">
          <header class="head">
            <div class="titles">
              ${(t.brand??"ECCO")!==""?I`<div class="wordmark"><span class="wm-accent">${(t.brand??"ECCO").slice(0,1)}</span>${(t.brand??"ECCO").slice(1)}</div>`:m}
              <div class="brand">${t.title??"Energy Flow"}</div>
              ${t.subtitle?I`<div class="subtitle">${t.subtitle}</div>`:m}
            </div>
            <button class=${`chip tone-${We.tone}`} type="button" @click=${()=>this._moreInfo(i.telemetry_online)} title=${We.title}>
              <span class="dot"></span>${We.text}
            </button>
          </header>
          ${w?I`<div class="strip stale-strip">${v.reason==="telemetry_offline"?"Telemetry offline: the values shown are the last received, not live.":`Values are stale: the newest power reading is ${pe(v.ageS)}.`}</div>`:m}
          <div class="body">
            <div class="scene-wrap">
              ${wr(Ar)}
              ${Er?I`<div class="banner idle-banner">Site idle: no power is flowing above ${5} W.</div>`:m}
            </div>
            <div class="side">
              ${t.features?.show_status_panel===!1?m:this._renderStatus(o,s,w,v.ageS)}
              ${t.features?.show_details_panel===!1?m:this._renderDetails(o,c,l,a,p,u,y,g)}
            </div>
          </div>
        </div>
      </ha-card>
    `}_chip(t,o,n,i){return t==="off"?{text:"Telemetry offline",tone:"alert",title:"The dongle's telemetry polling is offline"}:n&&i==="age"?{text:`Stale \xB7 ${pe(o)}`,tone:"warn",title:"No power reading has updated recently"}:t==="on"?{text:"System online",tone:"ok",title:o===null?"Telemetry online":`Telemetry online \xB7 updated ${pe(o)}`}:{text:o===null?"Status unknown":`Updated ${pe(o)}`,tone:"muted",title:"No telemetry-online entity configured"}}_renderStatus(t,o,n,i){let s=this._config,c=s.ecco??{},l=s.nodes??{},a=[],p=c.tou,d=ar((p?.slot_start_minutes??[]).map(S=>_(t,S)),cr(o),p?.valid?B(A(t,p.valid)):"unknown"),u=d.slot===null?null:d.slot-1,h=u===null?void 0:p?.slot_target_soc?.[u],y=u===null?void 0:p?.slot_charge_source?.[u],g=u===null?void 0:p?.slot_power?.[u],M=_(t,h),k=A(t,y),R=_(t,g);a.push({key:"tou",icon:"clock",label:"TOU Slot",value:d.value,sub:d.sub,tone:d.tone,entity:u===null?p?.slot_start_minutes?.[0]:p?.slot_start_minutes?.[u],title:"The slot containing the current local time, from the six slot start sensors"}),a.push({key:"charge",icon:"plug",label:"Charge Source",value:y&&k&&k!=="unknown"&&k!=="unavailable"?k:"--",sub:u===null?"Needs the current slot":R!==null?`Slot limit ${Q(R,s.format)}`:"Current slot setting",tone:k&&k.toLowerCase()==="grid"?"accent":"muted",entity:y}),a.push({key:"target",icon:"target",label:"Target SOC",value:ut(M),sub:u===null?"Needs the current slot":`Slot ${d.slot} setting`,tone:M===null?"muted":"accent",entity:h});let x=l.battery?.time_to_reserve,C=Ee(x,_(t,x),H(t,x)?.unit_of_measurement),v=De(x,C,H(t,x)),w=sr(v);a.push({key:"runtime",icon:"battery",label:"Runtime",value:w.value,sub:w.sub,tone:w.tone,entity:x,title:v?ht(v):"No time-to-reserve entity configured"});let T=c.free_power,O=gt({active:B(A(t,T?.active)),endsAtText:A(t,T?.ends_at),scheduleStatus:A(t,T?.schedule_status),statusText:A(t,T?.status),scheduleAttrs:H(t,T?.schedule_status),anyConfigured:!!(T?.active||T?.status||T?.schedule_status)},this._nowMs,"free_power");a.push({key:"fp",icon:"leaf",label:"Free Power",value:O.value,sub:O.sub,tone:O.tone,entity:T?.status??T?.active??T?.schedule_status,title:A(t,T?.status)});let $=c.dump_to_grid,P=gt({active:B(A(t,$?.active)),endsAtText:A(t,$?.ends_at),scheduleStatus:A(t,$?.schedule_status),statusText:A(t,$?.status),scheduleAttrs:H(t,$?.schedule_status),exportPowerW:_(t,$?.export_power),stopSoc:_(t,$?.stop_soc),anyConfigured:!!($?.active||$?.status||$?.schedule_status)},this._nowMs,"dump");a.push({key:"dump",icon:"swap",label:"Dump to Grid",value:P.value,sub:P.sub,tone:P.tone,entity:$?.status??$?.active??$?.schedule_status,title:A(t,$?.status)});let F=yt(c.health?.sensors??[],c.health?.attention??[],t);a.push({key:"health",icon:F.grade==="FAILED"?"alert":"heart",label:"Health",value:F.value,sub:F.sub,tone:F.tone,entity:c.health?.sensors?.[0],wide:!0,title:[...F.failed.map(S=>`FAILED: ${S}`),...F.degraded.map(S=>`DEGRADED: ${S}`),...F.attention.map(S=>`attention: ${S}`),...F.unknown.map(S=>`unknown: ${S}`)].join(`
`)||"All configured subsystems healthy"});let D=_(t,c.forecast?.today),me=_(t,c.forecast?.remaining),le=_(t,s.today?.solar);return a.push({key:"forecast",icon:"forecast",label:"Forecast Today",value:L(D,s.format),sub:me!==null?`${L(me,s.format)} still expected`+(le!==null?` \xB7 ${L(le,s.format)} so far`:""):le!==null?`${L(le,s.format)} generated so far`:c.forecast?.today?"Remaining forecast unavailable":"No forecast entity configured",tone:D===null?"muted":"ok",entity:c.forecast?.remaining??c.forecast?.today,wide:!0}),I`
      <section class="status" aria-label="ECCO system status">
        <div class="status-head">
          <span class="status-title">ECCO System Status</span>
          <span class=${`status-age ${n?"stale":""}`}><span class="dot"></span>${i===null?"No timestamp":`Updated ${pe(i)}`}</span>
        </div>
        <div class="tiles">
          ${a.map(S=>I`
              <button
                type="button"
                class=${`tile tone-${S.tone} ${S.wide?"wide":""} ${S.entity?"clickable":""}`}
                title=${S.title??""}
                ?disabled=${!S.entity}
                @click=${()=>this._moreInfo(S.entity)}
              >
                <span class="tile-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d=${fe[S.icon]}></path></svg></span>
                <span class="tile-text">
                  <span class="tile-label">${S.label}</span>
                  <span class="tile-value">${S.value}</span>
                  ${S.sub?I`<span class="tile-sub">${S.sub}</span>`:m}
                </span>
                ${S.entity?I`<svg class="tile-chev" viewBox="0 0 24 24" aria-hidden="true"><path d=${fe.chevron}></path></svg>`:m}
              </button>
            `)}
        </div>
      </section>
    `}_renderDetails(t,o,n,i,s,c,l,a){let p=this._config,d=p.nodes??{},u=p.ecco??{},h=p.inverter_details??{},y=p.format,g=($,P,F,D)=>I`
      <div class=${`row ${F?"clickable":""}`} @click=${()=>this._moreInfo(F)} role=${F?"button":"listitem"} tabindex=${F?0:-1}>
        <span class="row-label">${$}</span>
        <span class="row-value">${P}${D?I`<span class="row-note">${D}</span>`:m}</span>
      </div>`,M=$=>{let P=_(t,$);return P===null?"--":`${P.toFixed(1)} \xB0C`},k=lr(d.battery?.time_to_target,t),R=B(A(t,d.grid?.connected)),x=d.battery?.time_to_reserve,C=De(x,Ee(x,_(t,x),H(t,x)?.unit_of_measurement),H(t,x)),v=yt(u.health?.sensors??[],u.health?.attention??[],t),w=p.today??{},T=Object.values(w).some(Boolean),O=_(t,u.forecast?.tomorrow);return I`
      <details class="details" ?open=${this._detailsOpen} @toggle=${$=>this._detailsOpen=$.target.open}>
        <summary>
          <span>Inverter, grid and diagnostics</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${fe.chevron}></path></svg>
        </summary>
        <div class="details-grid">
          <div class="group">
            <div class="group-title">Inverter</div>
            ${g("State",A(t,d.inverter?.state)??"--",d.inverter?.state)}
            ${g("AC output",Q(s,y),d.inverter?.power)}
            ${g("Home load",Q(a,y),d.home?.power,_(t,d.home?.power)===0&&a!==0?"derived":void 0)}
            ${g("AC transformer",M(h.ac_temperature),h.ac_temperature)}
            ${g("DC transformer",M(h.dc_temperature),h.dc_temperature)}
            ${h.temperature?g("Temperature",M(h.temperature),h.temperature):m}
          </div>
          <div class="group">
            <div class="group-title">Grid</div>
            ${g("Connected",R==="on"?"Yes":R==="off"?"No":"Unknown",d.grid?.connected)}
            ${g("Power",l===null?"--":`${Q(Math.abs(l),y)} ${l>=5?"import":l<=-5?"export":""}`,d.grid?.power)}
            ${g("Voltage",_(t,d.grid?.voltage)===null?"--":`${_(t,d.grid?.voltage).toFixed(1)} V`,d.grid?.voltage)}
            ${g("Frequency",_(t,d.grid?.frequency)===null?"--":`${_(t,d.grid?.frequency).toFixed(2)} Hz`,d.grid?.frequency)}
          </div>
          <div class="group">
            <div class="group-title">Solar</div>
            ${o.map(($,P)=>g($.label??`Array ${P+1}`,Q(n[P]??null,y),$.power))}
            ${g("Total",Q(i,y),d.solar_total,d.solar_total?void 0:o.length>1?"sum of arrays":void 0)}
            ${u.forecast?.tomorrow?g("Forecast tomorrow",L(O,y),u.forecast.tomorrow):m}
          </div>
          <div class="group">
            <div class="group-title">Battery</div>
            ${g("Power",c===null?"--":`${Q(Math.abs(c),y)} ${c>=5?"discharge":c<=-5?"charge":""}`,d.battery?.power)}
            ${g("State of charge",ut(_(t,d.battery?.soc)),d.battery?.soc)}
            ${g("Time to reserve",C?ht(C).replace(/^Time to reserve: /,""):"No entity configured",x)}
            ${g("Time to charge target",k.value,d.battery?.time_to_target,k.sub)}
            ${h.battery_temperature?g("Temperature",M(h.battery_temperature),h.battery_temperature):m}
          </div>
          ${(u.health?.sensors?.length??0)>0?I`<div class="group">
                  <div class="group-title">Health</div>
                  ${(u.health?.sensors??[]).map($=>{let P=(A(t,$)??"--").toUpperCase();return g($.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/_/g," "),P==="HEALTHY"?"Healthy":P==="DEGRADED"?"Degraded":P==="FAILED"?"Failed":"Unknown",$,typeof H(t,$)?.summary=="string"&&P!=="HEALTHY"?String(H(t,$)?.summary).trim().slice(0,80):void 0)})}
                  ${(u.health?.attention??[]).map($=>g($.replace(/^.*?\./,"").replace(/_/g," "),B(A(t,$))==="on"?"Needs attention":B(A(t,$))==="off"?"Clear":"Unknown",$))}
                  ${v.attention.length+v.failed.length>0?I`<div class="row-note block">Warnings are listed in full above; the Health tile summarises them.</div>`:m}
                </div>`:m}
          ${T?I`<div class="group today">
                  <div class="group-title">Today</div>
                  ${g("Solar",L(_(t,w.solar),y),w.solar)}
                  ${g("Load",L(_(t,w.load),y),w.load)}
                  ${g("Import",L(_(t,w.import),y),w.import)}
                  ${g("Export",L(_(t,w.export),y),w.export)}
                  ${g("Battery charge",L(_(t,w.battery_charge),y),w.battery_charge)}
                  ${g("Battery discharge",L(_(t,w.battery_discharge),y),w.battery_discharge)}
                </div>`:m}
        </div>
      </details>
    `}_pathFor(t,o){let n=t.querySelector(`#${CSS.escape(o)}`);if(!n)return null;let i=n.getAttribute("d")??"",s=this._lengthCache.get(n);return(!s||s.d!==i)&&(s={d:i,length:n.getTotalLength()},this._lengthCache.set(n,s)),s.length?{path:n,length:s.length}:null}_animate(){this._raf=requestAnimationFrame(()=>this._animate());let t=this.shadowRoot;if(!t||this._reducedMotion)return;let o=t.querySelectorAll(".pulse");if(!o.length)return;let n=performance.now()/1e3;o.forEach(i=>{let s=i.dataset.path,c=parseFloat(i.dataset.duration??""),l=parseFloat(i.dataset.phase??"0");if(!s||!c)return;let a=this._pathFor(t,s);if(!a)return;let p=(n/c+l)%1;i.dataset.reversed==="1"&&(p=1-p);let d=a.path.getPointAtLength(p*a.length);i.setAttribute("transform",`translate(${d.x.toFixed(2)},${d.y.toFixed(2)})`)})}_placeChevrons(){let t=this.shadowRoot;t&&t.querySelectorAll(".chevron").forEach(o=>{let n=o.dataset.path,i=parseFloat(o.dataset.phase??"0.5");if(!n)return;let s=this._pathFor(t,n);if(!s)return;let c=o.dataset.reversed==="1",l=(c?1-i:i)*s.length,a=s.path.getPointAtLength(Math.max(0,l-2)),p=s.path.getPointAtLength(Math.min(s.length,l+2)),d=Math.atan2(p.y-a.y,p.x-a.x)*180/Math.PI+(c?180:0),u=s.path.getPointAtLength(l);o.setAttribute("transform",`translate(${u.x.toFixed(2)},${u.y.toFixed(2)}) rotate(${d.toFixed(1)})`)})}};z.styles=Ye`
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
    .debug-riser {
      fill: rgba(255, 212, 0, 0.12);
      stroke: #ffd400;
      stroke-dasharray: 4 4;
      stroke-width: 2;
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
    .info-line {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0.38;
      stroke-dasharray: 0.01 calc(5px * var(--k, 1));
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
      opacity: 0.8;
    }
    .info-link.active .info-glow {
      opacity: 0.16;
    }
    .pit-shadow {
      fill: rgba(0, 0, 0, 0.18);
      filter: url(#ef3d-blur);
    }
    .pit-face {
      fill: rgba(20, 26, 38, 0.28);
      stroke: rgba(255, 255, 255, 0.22);
      stroke-width: calc(0.5px * var(--k, 1));
    }
    .junction-bar.led-ok {
      fill: #e7edf7;
    }
    .junction-bar.led-warn {
      fill: var(--ef-warn);
    }
    .junction-bar.led-off {
      fill: #6b778d;
      opacity: 0.6;
    }
    .debug-bend {
      fill: #ffd400;
      stroke: #000;
      stroke-width: 1;
    }
    .debug-paving {
      fill: none;
      stroke: #ffffff;
      stroke-width: 2;
      stroke-dasharray: 6 5;
      opacity: 0.9;
    }
    .debug-paving-label {
      font-size: calc(7px * var(--k, 1));
      fill: #ffffff;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.8);
      stroke-width: calc(1.6px * var(--k, 1));
    }
    .debug-waypoint {
      fill: rgba(53, 224, 138, 0.9);
      stroke: #000;
      stroke-width: 1.5;
    }
    .debug-waypoint-label {
      font-size: calc(7px * var(--k, 1));
      font-weight: 700;
      fill: #b7ffd9;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.85);
      stroke-width: calc(1.6px * var(--k, 1));
    }
    .debug-buried {
      stroke: #ff9f1a;
      stroke-width: 4;
      stroke-dasharray: 3 6;
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
  `,Y([Oe({attribute:!1})],z.prototype,"hass",2),Y([ue()],z.prototype,"_config",2),Y([ue()],z.prototype,"_detailsOpen",2),Y([ue()],z.prototype,"_nowMs",2),Y([ue()],z.prototype,"_layers",2),Y([ue()],z.prototype,"_widthPx",2),z=Y([Dt("ecco-flow-3d-card")],z);window.customCards=[...window.customCards??[],{type:"ecco-flow-3d-card",name:"ECCO 3D Energy Flow",description:"Read-only isometric energy flow scene (solar, battery, grid, home) with animated power paths and the ECCO status grid.",preview:!1}];export{z as EccoFlow3dCard};
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
