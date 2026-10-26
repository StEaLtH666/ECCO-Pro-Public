var an=Object.defineProperty;var cn=Object.getOwnPropertyDescriptor;var re=(e,t,n,o)=>{for(var r=o>1?void 0:o?cn(t,n):t,s=e.length-1,i;s>=0;s--)(i=e[s])&&(r=(o?i(t,n,r):i(r))||r);return o&&r&&an(t,n,r),r};var _e=globalThis,ke=_e.ShadowRoot&&(_e.ShadyCSS===void 0||_e.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,De=Symbol(),ht=new WeakMap,fe=class{constructor(t,n,o){if(this._$cssResult$=!0,o!==De)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=n}get styleSheet(){let t=this.o,n=this.t;if(ke&&t===void 0){let o=n!==void 0&&n.length===1;o&&(t=ht.get(n)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),o&&ht.set(n,t))}return t}toString(){return this.cssText}},gt=e=>new fe(typeof e=="string"?e:e+"",void 0,De),ze=(e,...t)=>{let n=e.length===1?e[0]:t.reduce((o,r,s)=>o+(i=>{if(i._$cssResult$===!0)return i.cssText;if(typeof i=="number")return i;throw Error("Value passed to 'css' function must be a 'css' function result: "+i+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(r)+e[s+1],e[0]);return new fe(n,e,De)},mt=(e,t)=>{if(ke)e.adoptedStyleSheets=t.map(n=>n instanceof CSSStyleSheet?n:n.styleSheet);else for(let n of t){let o=document.createElement("style"),r=_e.litNonce;r!==void 0&&o.setAttribute("nonce",r),o.textContent=n.cssText,e.appendChild(o)}},Be=ke?e=>e:e=>e instanceof CSSStyleSheet?(t=>{let n="";for(let o of t.cssRules)n+=o.cssText;return gt(n)})(e):e;var{is:un,defineProperty:dn,getOwnPropertyDescriptor:pn,getOwnPropertyNames:fn,getOwnPropertySymbols:hn,getPrototypeOf:gn}=Object,Ae=globalThis,yt=Ae.trustedTypes,mn=yt?yt.emptyScript:"",yn=Ae.reactiveElementPolyfillSupport,he=(e,t)=>e,ge={toAttribute(e,t){switch(t){case Boolean:e=e?mn:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,t){let n=e;switch(t){case Boolean:n=e!==null;break;case Number:n=e===null?null:Number(e);break;case Object:case Array:try{n=JSON.parse(e)}catch{n=null}}return n}},Se=(e,t)=>!un(e,t),bt={attribute:!0,type:String,converter:ge,reflect:!1,useDefault:!1,hasChanged:Se};Symbol.metadata??=Symbol("metadata"),Ae.litPropertyMetadata??=new WeakMap;var z=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,n=bt){if(n.state&&(n.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((n=Object.create(n)).wrapped=!0),this.elementProperties.set(t,n),!n.noAccessor){let o=Symbol(),r=this.getPropertyDescriptor(t,o,n);r!==void 0&&dn(this.prototype,t,r)}}static getPropertyDescriptor(t,n,o){let{get:r,set:s}=pn(this.prototype,t)??{get(){return this[n]},set(i){this[n]=i}};return{get:r,set(i){let a=r?.call(this);s?.call(this,i),this.requestUpdate(t,a,o)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??bt}static _$Ei(){if(this.hasOwnProperty(he("elementProperties")))return;let t=gn(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(he("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(he("properties"))){let n=this.properties,o=[...fn(n),...hn(n)];for(let r of o)this.createProperty(r,n[r])}let t=this[Symbol.metadata];if(t!==null){let n=litPropertyMetadata.get(t);if(n!==void 0)for(let[o,r]of n)this.elementProperties.set(o,r)}this._$Eh=new Map;for(let[n,o]of this.elementProperties){let r=this._$Eu(n,o);r!==void 0&&this._$Eh.set(r,n)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let n=[];if(Array.isArray(t)){let o=new Set(t.flat(1/0).reverse());for(let r of o)n.unshift(Be(r))}else t!==void 0&&n.push(Be(t));return n}static _$Eu(t,n){let o=n.attribute;return o===!1?void 0:typeof o=="string"?o:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,n=this.constructor.elementProperties;for(let o of n.keys())this.hasOwnProperty(o)&&(t.set(o,this[o]),delete this[o]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return mt(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,n,o){this._$AK(t,o)}_$ET(t,n){let o=this.constructor.elementProperties.get(t),r=this.constructor._$Eu(t,o);if(r!==void 0&&o.reflect===!0){let s=(o.converter?.toAttribute!==void 0?o.converter:ge).toAttribute(n,o.type);this._$Em=t,s==null?this.removeAttribute(r):this.setAttribute(r,s),this._$Em=null}}_$AK(t,n){let o=this.constructor,r=o._$Eh.get(t);if(r!==void 0&&this._$Em!==r){let s=o.getPropertyOptions(r),i=typeof s.converter=="function"?{fromAttribute:s.converter}:s.converter?.fromAttribute!==void 0?s.converter:ge;this._$Em=r;let a=i.fromAttribute(n,s.type);this[r]=a??this._$Ej?.get(r)??a,this._$Em=null}}requestUpdate(t,n,o,r=!1,s){if(t!==void 0){let i=this.constructor;if(r===!1&&(s=this[t]),o??=i.getPropertyOptions(t),!((o.hasChanged??Se)(s,n)||o.useDefault&&o.reflect&&s===this._$Ej?.get(t)&&!this.hasAttribute(i._$Eu(t,o))))return;this.C(t,n,o)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,n,{useDefault:o,reflect:r,wrapped:s},i){o&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,i??n??this[t]),s!==!0||i!==void 0)||(this._$AL.has(t)||(this.hasUpdated||o||(n=void 0),this._$AL.set(t,n)),r===!0&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(n){Promise.reject(n)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[r,s]of this._$Ep)this[r]=s;this._$Ep=void 0}let o=this.constructor.elementProperties;if(o.size>0)for(let[r,s]of o){let{wrapped:i}=s,a=this[r];i!==!0||this._$AL.has(r)||a===void 0||this.C(r,void 0,s,a)}}let t=!1,n=this._$AL;try{t=this.shouldUpdate(n),t?(this.willUpdate(n),this._$EO?.forEach(o=>o.hostUpdate?.()),this.update(n)):this._$EM()}catch(o){throw t=!1,this._$EM(),o}t&&this._$AE(n)}willUpdate(t){}_$AE(t){this._$EO?.forEach(n=>n.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(n=>this._$ET(n,this[n])),this._$EM()}updated(t){}firstUpdated(t){}};z.elementStyles=[],z.shadowRootOptions={mode:"open"},z[he("elementProperties")]=new Map,z[he("finalized")]=new Map,yn?.({ReactiveElement:z}),(Ae.reactiveElementVersions??=[]).push("2.1.2");var Xe=globalThis,xt=e=>e,Ee=Xe.trustedTypes,$t=Ee?Ee.createPolicy("lit-html",{createHTML:e=>e}):void 0,St="$lit$",V=`lit$${Math.random().toFixed(9).slice(2)}$`,Et="?"+V,bn=`<${Et}>`,ee=document,ye=()=>ee.createComment(""),be=e=>e===null||typeof e!="object"&&typeof e!="function",Ze=Array.isArray,xn=e=>Ze(e)||typeof e?.[Symbol.iterator]=="function",We=`[ 	
\f\r]`,me=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,wt=/-->/g,vt=/>/g,Q=RegExp(`>|${We}(?:([^\\s"'>=/]+)(${We}*=${We}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),_t=/'/g,kt=/"/g,Mt=/^(?:script|style|textarea|title)$/i,Ke=e=>(t,...n)=>({_$litType$:e,strings:t,values:n}),N=Ke(1),v=Ke(2),to=Ke(3),te=Symbol.for("lit-noChange"),y=Symbol.for("lit-nothing"),At=new WeakMap,J=ee.createTreeWalker(ee,129);function Tt(e,t){if(!Ze(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return $t!==void 0?$t.createHTML(t):t}var $n=(e,t)=>{let n=e.length-1,o=[],r,s=t===2?"<svg>":t===3?"<math>":"",i=me;for(let a=0;a<n;a++){let l=e[a],u,p,c=-1,f=0;for(;f<l.length&&(i.lastIndex=f,p=i.exec(l),p!==null);)f=i.lastIndex,i===me?p[1]==="!--"?i=wt:p[1]!==void 0?i=vt:p[2]!==void 0?(Mt.test(p[2])&&(r=RegExp("</"+p[2],"g")),i=Q):p[3]!==void 0&&(i=Q):i===Q?p[0]===">"?(i=r??me,c=-1):p[1]===void 0?c=-2:(c=i.lastIndex-p[2].length,u=p[1],i=p[3]===void 0?Q:p[3]==='"'?kt:_t):i===kt||i===_t?i=Q:i===wt||i===vt?i=me:(i=Q,r=void 0);let g=i===Q&&e[a+1].startsWith("/>")?" ":"";s+=i===me?l+bn:c>=0?(o.push(u),l.slice(0,c)+St+l.slice(c)+V+g):l+V+(c===-2?a:g)}return[Tt(e,s+(e[n]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),o]},xe=class e{constructor({strings:t,_$litType$:n},o){let r;this.parts=[];let s=0,i=0,a=t.length-1,l=this.parts,[u,p]=$n(t,n);if(this.el=e.createElement(u,o),J.currentNode=this.el.content,n===2||n===3){let c=this.el.content.firstChild;c.replaceWith(...c.childNodes)}for(;(r=J.nextNode())!==null&&l.length<a;){if(r.nodeType===1){if(r.hasAttributes())for(let c of r.getAttributeNames())if(c.endsWith(St)){let f=p[i++],g=r.getAttribute(c).split(V),h=/([.?@])?(.*)/.exec(f);l.push({type:1,index:s,name:h[2],strings:g,ctor:h[1]==="."?Ge:h[1]==="?"?Ve:h[1]==="@"?qe:ie}),r.removeAttribute(c)}else c.startsWith(V)&&(l.push({type:6,index:s}),r.removeAttribute(c));if(Mt.test(r.tagName)){let c=r.textContent.split(V),f=c.length-1;if(f>0){r.textContent=Ee?Ee.emptyScript:"";for(let g=0;g<f;g++)r.append(c[g],ye()),J.nextNode(),l.push({type:2,index:++s});r.append(c[f],ye())}}}else if(r.nodeType===8)if(r.data===Et)l.push({type:2,index:s});else{let c=-1;for(;(c=r.data.indexOf(V,c+1))!==-1;)l.push({type:7,index:s}),c+=V.length-1}s++}}static createElement(t,n){let o=ee.createElement("template");return o.innerHTML=t,o}};function se(e,t,n=e,o){if(t===te)return t;let r=o!==void 0?n._$Co?.[o]:n._$Cl,s=be(t)?void 0:t._$litDirective$;return r?.constructor!==s&&(r?._$AO?.(!1),s===void 0?r=void 0:(r=new s(e),r._$AT(e,n,o)),o!==void 0?(n._$Co??=[])[o]=r:n._$Cl=r),r!==void 0&&(t=se(e,r._$AS(e,t.values),r,o)),t}var je=class{constructor(t,n){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=n}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:n},parts:o}=this._$AD,r=(t?.creationScope??ee).importNode(n,!0);J.currentNode=r;let s=J.nextNode(),i=0,a=0,l=o[0];for(;l!==void 0;){if(i===l.index){let u;l.type===2?u=new $e(s,s.nextSibling,this,t):l.type===1?u=new l.ctor(s,l.name,l.strings,this,t):l.type===6&&(u=new Ye(s,this,t)),this._$AV.push(u),l=o[++a]}i!==l?.index&&(s=J.nextNode(),i++)}return J.currentNode=ee,r}p(t){let n=0;for(let o of this._$AV)o!==void 0&&(o.strings!==void 0?(o._$AI(t,o,n),n+=o.strings.length-2):o._$AI(t[n])),n++}},$e=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,n,o,r){this.type=2,this._$AH=y,this._$AN=void 0,this._$AA=t,this._$AB=n,this._$AM=o,this.options=r,this._$Cv=r?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,n=this._$AM;return n!==void 0&&t?.nodeType===11&&(t=n.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,n=this){t=se(this,t,n),be(t)?t===y||t==null||t===""?(this._$AH!==y&&this._$AR(),this._$AH=y):t!==this._$AH&&t!==te&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):xn(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==y&&be(this._$AH)?this._$AA.nextSibling.data=t:this.T(ee.createTextNode(t)),this._$AH=t}$(t){let{values:n,_$litType$:o}=t,r=typeof o=="number"?this._$AC(t):(o.el===void 0&&(o.el=xe.createElement(Tt(o.h,o.h[0]),this.options)),o);if(this._$AH?._$AD===r)this._$AH.p(n);else{let s=new je(r,this),i=s.u(this.options);s.p(n),this.T(i),this._$AH=s}}_$AC(t){let n=At.get(t.strings);return n===void 0&&At.set(t.strings,n=new xe(t)),n}k(t){Ze(this._$AH)||(this._$AH=[],this._$AR());let n=this._$AH,o,r=0;for(let s of t)r===n.length?n.push(o=new e(this.O(ye()),this.O(ye()),this,this.options)):o=n[r],o._$AI(s),r++;r<n.length&&(this._$AR(o&&o._$AB.nextSibling,r),n.length=r)}_$AR(t=this._$AA.nextSibling,n){for(this._$AP?.(!1,!0,n);t!==this._$AB;){let o=xt(t).nextSibling;xt(t).remove(),t=o}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},ie=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,n,o,r,s){this.type=1,this._$AH=y,this._$AN=void 0,this.element=t,this.name=n,this._$AM=r,this.options=s,o.length>2||o[0]!==""||o[1]!==""?(this._$AH=Array(o.length-1).fill(new String),this.strings=o):this._$AH=y}_$AI(t,n=this,o,r){let s=this.strings,i=!1;if(s===void 0)t=se(this,t,n,0),i=!be(t)||t!==this._$AH&&t!==te,i&&(this._$AH=t);else{let a=t,l,u;for(t=s[0],l=0;l<s.length-1;l++)u=se(this,a[o+l],n,l),u===te&&(u=this._$AH[l]),i||=!be(u)||u!==this._$AH[l],u===y?t=y:t!==y&&(t+=(u??"")+s[l+1]),this._$AH[l]=u}i&&!r&&this.j(t)}j(t){t===y?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},Ge=class extends ie{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===y?void 0:t}},Ve=class extends ie{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==y)}},qe=class extends ie{constructor(t,n,o,r,s){super(t,n,o,r,s),this.type=5}_$AI(t,n=this){if((t=se(this,t,n,0)??y)===te)return;let o=this._$AH,r=t===y&&o!==y||t.capture!==o.capture||t.once!==o.once||t.passive!==o.passive,s=t!==y&&(o===y||r);r&&this.element.removeEventListener(this.name,this,o),s&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},Ye=class{constructor(t,n,o){this.element=t,this.type=6,this._$AN=void 0,this._$AM=n,this.options=o}get _$AU(){return this._$AM._$AU}_$AI(t){se(this,t)}};var wn=Xe.litHtmlPolyfillSupport;wn?.(xe,$e),(Xe.litHtmlVersions??=[]).push("3.3.3");var Ct=(e,t,n)=>{let o=n?.renderBefore??t,r=o._$litPart$;if(r===void 0){let s=n?.renderBefore??null;o._$litPart$=r=new $e(t.insertBefore(ye(),s),s,void 0,n??{})}return r._$AI(e),r};var Qe=globalThis,q=class extends z{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){let n=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=Ct(n,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return te}};q._$litElement$=!0,q.finalized=!0,Qe.litElementHydrateSupport?.({LitElement:q});var vn=Qe.litElementPolyfillSupport;vn?.({LitElement:q});(Qe.litElementVersions??=[]).push("4.2.2");var Rt=e=>(t,n)=>{n!==void 0?n.addInitializer(()=>{customElements.define(e,t)}):customElements.define(e,t)};var _n={attribute:!0,type:String,converter:ge,reflect:!1,hasChanged:Se},kn=(e=_n,t,n)=>{let{kind:o,metadata:r}=n,s=globalThis.litPropertyMetadata.get(r);if(s===void 0&&globalThis.litPropertyMetadata.set(r,s=new Map),o==="setter"&&((e=Object.create(e)).wrapped=!0),s.set(n.name,e),o==="accessor"){let{name:i}=n;return{set(a){let l=t.get.call(this);t.set.call(this,a),this.requestUpdate(i,l,e,!0,a)},init(a){return a!==void 0&&this.C(i,void 0,e,a),a}}}if(o==="setter"){let{name:i}=n;return function(a){let l=this[i];t.call(this,a),this.requestUpdate(i,l,e,!0,a)}}throw Error("Unsupported decorator location: "+o)};function Me(e){return(t,n)=>typeof n=="object"?kn(e,t,n):((o,r,s)=>{let i=r.hasOwnProperty(s);return r.constructor.createProperty(s,o),i?Object.getOwnPropertyDescriptor(r,s):void 0})(e,t,n)}function Te(e){return Me({...e,state:!0,attribute:!1})}function Pt(e){return e?(Array.isArray(e)?e:[e]).filter(n=>!!n&&!!n.power):[]}var Nt=180;function Ft(e){if(!e||typeof e!="object")throw new Error("ecco-flow-3d-card: invalid configuration");let t=e;if(!t.nodes||typeof t.nodes!="object"||Object.keys(t.nodes).length===0)throw new Error("ecco-flow-3d-card: at least one entry under `nodes:` is required");let n=t.ecco?.tou;for(let o of["slot_start_minutes","slot_target_soc","slot_charge_source","slot_power"]){let r=n?.[o];if(r!==void 0&&(!Array.isArray(r)||r.length!==6))throw new Error(`ecco-flow-3d-card: ecco.tou.${o} must list exactly six entities (slot 1 to slot 6)`)}}function It(e,t){return t==="discharge_positive"?e:-e}function Ot(e,t){return t==="export_positive"?-e:e}var An=150;function Ht(e,t,n){let o=t!==null&&n!==null?Math.max(0,t+n):null;return e===null||e===0&&o!==null&&o>An?o:Math.max(0,e)}function Lt(e,t){if(e!==null)return Math.max(0,e);let n=t.filter(o=>o!==null);return n.length===0?null:Math.max(0,n.reduce((o,r)=>o+r,0))}var B=5;function Re(e,t,n){if(t===null)return{id:e,magnitudeW:null,idle:!1,unknown:!0,reversed:!1};let o=Math.abs(t);return{id:e,magnitudeW:o,idle:o<B,unknown:!1,reversed:n&&t<0}}function Ut(e){return[Re("solar",e.solarW===null?null:Math.max(0,e.solarW),!1),Re("battery",e.batteryW,!0),Re("grid",e.gridW,!0),Re("home",e.homeW===null?null:Math.max(0,e.homeW),!1)]}function Dt(e){let t=e.filter(n=>!n.unknown);return t.length>0&&t.every(n=>n.idle)}function zt(e){return e===null?"unknown":e>=B?"discharging":e<=-B?"charging":"idle"}function Bt(e){return e===null?"unknown":e>=B?"importing":e<=-B?"exporting":"idle"}var Gt=6e3,Sn=2.4,En=.45,Wt=2.6,Vt=15,Pe=4,Mn=9,Je=2.7,Tn=5.4,et=2.6,Cn=3.3,Rn=.6,jt=5.5,tt=3.1,Pn=4.9;function Nn(e){if(!(e>B))return 0;let t=Math.log(e/B)/Math.log(Gt/B),n=Math.min(1,Math.max(0,t));return Math.pow(n,Sn)}function Fn(e){return e<750?1:e<3e3?2:e<6e3?3:4}var In={intensity:0,moving:!1,dashDurationS:0,dashLen:Pe,gapLen:Vt-Pe,packetWidthPx:Je,baseWidthPx:et,packetOpacity:0,glowPx:0,ballCount:0,ballDurationS:0,ballRadiusPx:tt};function we(e,t){if(e.unknown||e.idle||t||e.magnitudeW===null)return In;let n=e.magnitudeW,o=Nn(n),r=Math.min(1,n/Gt),s=Pe+o*(Mn-Pe);return{intensity:o,moving:!0,dashDurationS:Wt-o*(Wt-En),dashLen:s,gapLen:Vt-s,packetWidthPx:Je+o*(Tn-Je),baseWidthPx:et+r*(Cn-et),packetOpacity:.62+o*.36,glowPx:1.6+o*2.4,ballCount:Fn(n),ballDurationS:jt-o*(jt-Rn),ballRadiusPx:tt+o*(Pn-tt)}}function nt(e){if(e==null||e==="unknown"||e==="unavailable"||e===""||e==="none"||e==="None")return null;let t=Number(e);return Number.isFinite(t)?t:null}function Y(e,t){if(e==null||Number.isNaN(e))return"--";let n=t?.power_unit??"auto",o=Math.abs(e);return n==="kw"||n==="auto"&&o>=1e3?`${(e/1e3).toFixed(t?.precision??2)} kW`:`${e.toFixed(t?.precision??0)} W`}function le(e){if(e==null||Number.isNaN(e))return"--";let t=Math.abs(e);return t>=1e4?`${(e/1e3).toFixed(0)} kW`:t>=1e3?`${(e/1e3).toFixed(1)} kW`:`${Math.round(e)} W`}function O(e,t){return e==null||Number.isNaN(e)?"--":`${e.toFixed(t?.energy_precision??1)} kWh`}function ot(e){return e==null||!Number.isFinite(e)?"--":`${Math.round(e)}%`}function W(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let t=Math.round(e);if(t===0)return e>0?"<1 min":"0 min";if(t<60)return`${t} min`;if(t<1440){let r=Math.floor(t/60),s=t%60;return s===0?`${r} h`:`${r} h ${s} min`}let n=Math.floor(t/1440),o=Math.floor(t%1440/60);return o===0?`${n} d`:`${n} d ${o} h`}function Ne(e){if(e==null||!Number.isFinite(e)||e<0)return"--";let t=Math.round(e);if(t===0)return e>0?"<1m":"0m";if(t<60)return`\u2248${t}m`;if(t<1440){let r=Math.floor(t/60),s=t%60;return s===0?`\u2248${r}h`:`\u2248${r}h ${s}m`}let n=Math.floor(t/1440),o=Math.floor(t%1440/60);return o===0?`\u2248${n}d`:`\u2248${n}d ${o}h`}function rt(e){if(e==null||!Number.isFinite(e))return"--:--";let t=(Math.round(e)%1440+1440)%1440;return`${String(Math.floor(t/60)).padStart(2,"0")}:${String(t%60).padStart(2,"0")}`}function st(e){return`${String(e.getHours()).padStart(2,"0")}:${String(e.getMinutes()).padStart(2,"0")}`}function ae(e){return e===null||!Number.isFinite(e)||e<0?"--":e<5?"just now":e<60?`${Math.floor(e)} s ago`:e<3600?`${Math.floor(e/60)} min ago`:e<86400?`${Math.floor(e/3600)} h ago`:`${Math.floor(e/86400)} d ago`}function E(e,t){return t?e[t]?.state:void 0}function w(e,t){return t?nt(e[t]?.state):null}function L(e,t){return t?e[t]?.attributes:void 0}function U(e){return e==="on"||e==="true"||e==="True"?"on":e==="off"||e==="false"||e==="False"?"off":"unknown"}var On=new Map([["s",1/60],["min",1],["h",60],["d",1440]]);function Ie(e,t,n){if(!e)return;let o=n==null||n===""?1:On.get(n);return o!==void 0&&t!==null&&t>=0?t*o:null}var Hn=["discharging","at_reserve","charging","holding","insufficient_data","stale"];function qt(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0?e:null}function it(e,t,n){if(!e||t===void 0)return;let o=n?.status,s=Hn.includes(o)?o:t!==null?"discharging":"insufficient_data";s==="discharging"&&t===null&&(s="insufficient_data");let i=s==="discharging"||s==="at_reserve",a=typeof n?.summary=="string"&&n.summary.trim()!==""?n.summary:null;return{status:s,minutes:i?t:null,low:s==="discharging"?qt(n?.minutes_low):null,high:s==="discharging"?qt(n?.minutes_high):null,beyondHorizon:s==="discharging"&&n?.beyond_horizon===!0,solarAssisted:s==="discharging"&&n?.solar_assisted===!0,summary:a}}var Yt="Over 3 days";function Ln(e){switch(e.status){case"discharging":return e.beyondHorizon?Yt:`${Ne(e.minutes)} to reserve`;case"at_reserve":return"At reserve";case"charging":return"Charging";case"holding":return"Holding";case"stale":return"Telemetry stale";default:return"Insufficient data"}}function Xt(e){if(!e)return{value:"--",sub:"No runtime entity",tone:"muted"};switch(e.status){case"discharging":return{value:e.beyondHorizon?">3 d":Ne(e.minutes),sub:e.beyondHorizon?"to reserve (estimate)":e.low!==null&&e.high!==null?`to reserve \xB7 likely ${W(e.low)} to ${W(e.high)}`:"to reserve (estimate)",tone:"ok"};case"at_reserve":return{value:"At reserve",sub:e.summary??"At or below the reserve",tone:"warn"};case"charging":return{value:"Charging",sub:"No discharge estimate while charging",tone:"ok"};case"holding":return{value:"Holding",sub:"Neither charging nor discharging",tone:"muted"};case"stale":return{value:"Stale",sub:"Estimate paused: telemetry stale",tone:"warn"};default:return{value:"--",sub:e.summary??"Insufficient data",tone:"muted"}}}function lt(e){if(e.status!=="discharging")return`Time to reserve: ${e.summary??Ln(e)}`;let t=[e.beyondHorizon?`${Yt} until the batteries reach the configured reserve at recent usage`:`Approximately ${W(e.minutes)} until the batteries reach the configured reserve at recent usage`];return!e.beyondHorizon&&e.low!==null&&e.high!==null&&t.push(`likely ${W(e.low)} to ${W(e.high)}`),e.solarAssisted&&t.push("solar-assisted, so it shortens as solar output falls"),t.push("an estimate, not a guarantee"),`Time to reserve: ${t.join("; ")}`}function Zt(e,t){if(!e)return{value:"Not available",sub:"No ECCO entity provides a time to charge target",tone:"muted"};let n=Ie(e,w(t,e),L(t,e)?.unit_of_measurement);return n==null?{value:"--",sub:"Entity has no value",tone:"muted"}:{value:Ne(n),sub:"to charge target (entity value)",tone:"ok"}}var Un=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;function Dn(e){if(!e)return null;let t=Un.exec(e.trim());if(!t)return null;let n=new Date(Number(t[1]),Number(t[2])-1,Number(t[3]),Number(t[4]),Number(t[5]),Number(t[6]));return Number.isNaN(n.getTime())?null:n}function zn(e,t,n){return n?"Active \xB7 end time unavailable":t===null?"Active":e===null||e<=0?`Ends ${st(t)} \xB7 ending`:`Ends ${st(t)} \xB7 ${W(e)} left`}function at(e,t,n){let o={phase:"unknown",value:"--",sub:"Not configured",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(!e.anyConfigured)return o;let r=(e.scheduleStatus??"").trim().toUpperCase(),s=Dn(e.endsAtText),i=(e.endsAtText??"").toLowerCase().includes("unavailable"),a=s?(s.getTime()-t)/6e4:null;if(e.active==="on"){let l=zn(a,s,i);return n==="dump"&&e.exportPowerW!==null&&e.exportPowerW!==void 0&&(l=`${l} \xB7 ${Math.round(e.exportPowerW)} W export`+(e.stopSoc!==null&&e.stopSoc!==void 0?` \xB7 stop ${Math.round(e.stopSoc)}%`:"")),{phase:"active",value:"Active",sub:l,tone:"accent",remainingMin:a,endsAt:s,endTimeUnavailable:i}}if(r==="STARTING")return{phase:"starting",value:"Starting",sub:"Scheduled start in progress",tone:"accent",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(r==="ARMED"){let l=typeof e.scheduleAttrs?.scheduled_start=="string"?e.scheduleAttrs.scheduled_start:null,u=nt(String(e.scheduleAttrs?.duration_minutes??""));return{phase:"armed",value:"Armed",sub:`Scheduled ${l?l.slice(0,5):"--:--"}`+(u!==null?` \xB7 ${W(u)}`:""),tone:"ok",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}if(r==="FAILED")return{phase:"failed",value:"Failed",sub:"Last scheduled run failed \xB7 see Energy Actions",tone:"alert",remainingMin:null,endsAt:null,endTimeUnavailable:!1};if(e.active==="off"){let l=r==="COMPLETED";return{phase:l?"completed":"standby",value:l?"Completed":n==="dump"?"Ready":"Standby",sub:l?"Last scheduled run completed":"No session running",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}return{phase:"unknown",value:"--",sub:"Lease state unavailable",tone:"muted",remainingMin:null,endsAt:null,endTimeUnavailable:!1}}function Kt(e,t,n){let o={slot:null,startMin:null,endMin:null,minutesToChange:null,value:"--",sub:"Schedule unavailable",tone:"muted"};if(e.length!==6||e.some(i=>i===null))return o;if(n==="off")return{...o,sub:"Schedule invalid",tone:"warn"};let r=e,s=(Math.floor(t)%1440+1440)%1440;for(let i=0;i<6;i++){let a=(r[i]%1440+1440)%1440,l=(r[(i+1)%6]%1440+1440)%1440;if(a<l?s>=a&&s<l:s>=a||s<l){let p=(l-s+1440)%1440;return{slot:i+1,startMin:a,endMin:l,minutesToChange:p,value:`Slot ${i+1}`,sub:`${rt(a)}\u2013${rt(l)} \xB7 ${W(p)} left`,tone:"accent"}}}return{...o,sub:"No slot matches the current time",tone:"warn"}}function Qt(e){return e.getHours()*60+e.getMinutes()}function Fe(e){return e.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/^ecco_/,"").replace(/_/g," ")}function ct(e,t,n){let o=[],r=[],s=[];for(let u of e){let p=(E(n,u)??"").trim().toUpperCase();p==="FAILED"?o.push(Fe(u)):p==="DEGRADED"?r.push(Fe(u)):p!=="HEALTHY"&&s.push(Fe(u))}let i=t.filter(u=>U(E(n,u))==="on").map(Fe);if(e.length+t.length===0)return{grade:"UNKNOWN",value:"--",sub:"No health entities configured",tone:"muted",failed:o,degraded:r,unknown:s,attention:i};let l=u=>u.slice(0,2).join(", ")+(u.length>2?` +${u.length-2}`:"");if(o.length>0||i.length>0){let u=[...o,...i];return{grade:"FAILED",value:"Attention",sub:l(u),tone:"alert",failed:o,degraded:r,unknown:s,attention:i}}return r.length>0?{grade:"DEGRADED",value:"Degraded",sub:l(r),tone:"warn",failed:o,degraded:r,unknown:s,attention:i}:s.length===e.length&&e.length>0?{grade:"UNKNOWN",value:"Unknown",sub:"Health entities unavailable",tone:"muted",failed:o,degraded:r,unknown:s,attention:i}:s.length>0?{grade:"HEALTHY",value:"Nominal",sub:`${s.length} unknown: ${l(s)}`,tone:"ok",failed:o,degraded:r,unknown:s,attention:i}:{grade:"HEALTHY",value:"Nominal",sub:`${e.length} subsystems healthy`,tone:"ok",failed:o,degraded:r,unknown:s,attention:i}}function Jt(e,t,n,o,r){let s=null;for(let a of e){if(!a)continue;let l=t[a]?.last_updated;if(!l)continue;let u=Date.parse(l);Number.isFinite(u)&&(s===null||u>s)&&(s=u)}let i=s===null?null:Math.max(0,(o-s)/1e3);return n==="off"?{ageS:i,stale:!0,reason:"telemetry_offline",telemetry:n}:r>0&&i!==null&&i>r?{ageS:i,stale:!0,reason:"age",telemetry:n}:{ageS:i,stale:!1,reason:null,telemetry:n}}function en(e,t){if(e){let o=typeof e.attributes?.elevation=="number"?e.attributes.elevation:null;if(e.state==="above_horizon")return o!==null&&o<8?"dusk":"day";if(e.state==="below_horizon")return o!==null&&o>-6?"dusk":"night"}let n=t.getHours();return n>=8&&n<18?"day":n>=6&&n<8||n>=18&&n<20?"dusk":"night"}var ce={sun:"M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6",pylon:"M9 22l3-19 3 19M6 22h12M7.2 9h9.6M8.4 14.5h7.2M4 9l3.2 3.5M20 9l-3.2 3.5M5 14.5l3.4 3M19 14.5l-3.4 3",home:"M3.5 11.5L12 4l8.5 7.5M6 10v10h12V10M10 20v-5h4v5",battery:"M7 5.5h10a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 17 21.5H7A1.5 1.5 0 0 1 5.5 20V7A1.5 1.5 0 0 1 7 5.5zM9.5 2.5h5M8.5 13.5h7v5h-7z",clock:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2",plug:"M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v3",target:"M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",leaf:"M5 19C6 11 11 5 20 4c0 9-5 15-13 15M5 19l7-7",swap:"M4 8h13l-3-3M20 16H7l3 3",heart:"M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",chevron:"M9 6l6 6-6 6",forecast:"M12 6.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v1.6M4.9 4.9l1.2 1.2M19.1 4.9l-1.2 1.2M2 10.5h1.6M20.4 10.5H22M3 19h18M6 22h12",inverter:"M4 5h16v14H4zM8 9h8M8 13h5M16 15.5h.01",alert:"M12 3l10 18H2L12 3zM12 10v5M12 18v.5",moon:"M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"};function d(e,t,n=0){return{x:205+(e-t)*11.258,y:262+(e+t)*6.5-n*13}}function k(e){return e.map(t=>`${t.x.toFixed(1)},${t.y.toFixed(1)}`).join(" ")}function ve(e,t,n,o,r,s){return{top:k([d(e,t,s),d(n,t,s),d(n,o,s),d(e,o,s)]),left:k([d(e,o,r),d(n,o,r),d(n,o,s),d(e,o,s)]),right:k([d(n,t,r),d(n,o,r),d(n,o,s),d(n,t,s)])}}function D(e,t,n,o,r){return k([d(t,e,o),d(n,e,o),d(n,e,r),d(t,e,r)])}function ut(e,t,n,o,r){return k([d(e,t,o),d(e,n,o),d(e,n,r),d(e,t,r)])}function de(e,t,n,o,r,s){return d(e,n+(r-n)*t,o+(s-o)*t)}function Oe(e){if(e.length<4)return"";let t=`M ${e[0].x.toFixed(1)} ${e[0].y.toFixed(1)}`;for(let n=1;n+2<e.length;n+=3){let o=e[n],r=e[n+1],s=e[n+2];t+=` C ${o.x.toFixed(1)} ${o.y.toFixed(1)}, ${r.x.toFixed(1)} ${r.y.toFixed(1)}, ${s.x.toFixed(1)} ${s.y.toFixed(1)}`}return t}var X={x0:-1,y0:-3,x1:7,y1:3,z:4.2,ridgeZ:6.6,ridgeY:0},tn={x0:7,y0:-1,x1:11,y1:3,z:2.5},ue={x0:-6.2,y0:4.2,x1:-4.6,y1:5.4,z:2.4},ne={x0:5.3,x1:6.3,z0:1.25,z1:2.45,y:X.y1},j=d(10.6,-4.8),dt=(()=>{let e=d((ne.x0+ne.x1)/2,ne.y,(ne.z0+ne.z1)/2);return{x:e.x+1,y:e.y+2}})(),Z={solar:{x:8,y:10,w:150,h:58,port:{x:58,y:68}},grid:{x:246,y:22,w:146,h:58,port:{x:330,y:80}},home:{x:214,y:176,w:140,h:54,port:{x:236,y:230}},battery:{x:8,y:388,w:184,h:70,port:{x:108,y:388}}};function nn(){let e=dt,t=de(.2,.08,X.y1,X.z,X.ridgeY,X.ridgeZ),n=Oe([Z.solar.port,{x:58,y:120},{x:150,y:150},t,{x:t.x+16,y:t.y+20},{x:e.x-24,y:e.y-26},e]),o=d(ue.x1,(ue.y0+ue.y1)/2,ue.z*.72),r=Oe([{x:o.x+2,y:o.y},{x:o.x+40,y:o.y-2},{x:e.x-60,y:e.y+28},{x:e.x-24,y:e.y+24},{x:e.x-10,y:e.y+22},{x:e.x-4,y:e.y+12},e]),s={x:j.x-4,y:j.y-118},i=Oe([Z.grid.port,{x:330,y:112},{x:s.x-30,y:s.y+10},{x:s.x-22,y:s.y+44},{x:s.x-14,y:j.y-6},{x:j.x-30,y:j.y+30},{x:300,y:j.y+40},{x:272,y:j.y+36},{x:e.x+10,y:e.y+24},e]),a=Oe([e,{x:e.x+10,y:e.y-24},{x:e.x-12,y:e.y-48},Z.home.port]);return{solar:n,battery:r,grid:i,home:a}}var sn={solar:"#f7c948",battery:"#35e08a",grid:"#3ea6ff",home:"#a9dcff"};function rn(e,t,n,o,r){let s=o/24;return v`<g transform="translate(${t} ${n}) scale(${s})" fill="none" stroke=${r} stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d=${ce[e]}></path></g>`}function Bn(){let e=[d(-8,-6),d(10,-6),d(10,10),d(-8,10)],t=12,n=[e[3],e[2],{x:e[2].x,y:e[2].y+t},{x:e[3].x,y:e[3].y+t}],o=[e[2],e[1],{x:e[1].x,y:e[1].y+t},{x:e[2].x,y:e[2].y+t}],r=[d(8.2,3.05),d(10.6,3.05),d(10.6,10),d(8.2,10)],s=[d(2.2,3.05),d(3.2,3.05),d(3.2,5.6),d(-4.2,5.6),d(-4.2,4.6),d(2.2,4.6)];return v`
    <g class="ground">
      <polygon points=${k(n)} class="ground-side"></polygon>
      <polygon points=${k(o)} class="ground-side ground-side-r"></polygon>
      <polygon points=${k(e)} class="ground-top"></polygon>
      <polygon points=${k(e)} fill="url(#ef3d-ground-sheen)"></polygon>
      <polygon points=${k(r)} class="drive"></polygon>
      <polygon points=${k(s)} class="drive path"></polygon>
      ${Wn()}
    </g>`}function Wn(){let e=[];for(let t=0;t<6;t++){let n=-5+t*2.6;e.push(v`<polygon points=${k([d(-7.6,n),d(-1.6,n),d(-1.6,n+1.3),d(-7.6,n+1.3)])} class="lawn-stripe"></polygon>`)}return e}function He(e,t,n,o=""){let r=d(e,t);return v`
    <g class="tree ${o}">
      <ellipse cx=${r.x} cy=${r.y+2} rx=${n*.9} ry=${n*.38} class="tree-shadow"></ellipse>
      <rect x=${r.x-1.4} y=${r.y-n*1.1} width="2.8" height=${n*1.1} class="trunk"></rect>
      <circle cx=${r.x-n*.35} cy=${r.y-n*1.15} r=${n*.78} class="canopy c2"></circle>
      <circle cx=${r.x+n*.4} cy=${r.y-n*1.25} r=${n*.82} class="canopy c3"></circle>
      <circle cx=${r.x} cy=${r.y-n*1.7} r=${n*.86} class="canopy c1"></circle>
    </g>`}function pe(e,t,n){let o=d(e,t);return v`<g class="shrub"><ellipse cx=${o.x} cy=${o.y} rx=${n} ry=${n*.62} class="canopy c2"></ellipse><ellipse cx=${o.x-n*.4} cy=${o.y-n*.25} rx=${n*.7} ry=${n*.45} class="canopy c1"></ellipse></g>`}function pt(e,t){let n=d(e,t);return v`<g class="lamp"><line x1=${n.x} y1=${n.y} x2=${n.x} y2=${n.y-9} class="lamp-post"></line><circle cx=${n.x} cy=${n.y-10} r="2.2" class="lamp-light"></circle><circle cx=${n.x} cy=${n.y-10} r="6" class="lamp-halo"></circle></g>`}function jn(){let e=X,t=ve(e.x0,e.y0,e.x1,e.y1,0,e.z),n=[d(e.x0-.5,e.y1+.5,e.z-.25),d(e.x1+.5,e.y1+.5,e.z-.25),d(e.x1+.5,e.ridgeY,e.ridgeZ),d(e.x0-.5,e.ridgeY,e.ridgeZ)],o=[d(e.x0-.5,e.y0-.5,e.z-.25),d(e.x1+.5,e.y0-.5,e.z-.25),d(e.x1+.5,e.ridgeY,e.ridgeZ),d(e.x0-.5,e.ridgeY,e.ridgeZ)],r=[d(e.x1,e.y0,e.z),d(e.x1,e.y1,e.z),d(e.x1,e.ridgeY,e.ridgeZ)],s=[d(e.x1+.5,e.y1+.5,e.z-.25),d(e.x1+.5,e.y1+.5,e.z-.55),d(e.x1+.5,e.ridgeY,e.ridgeZ-.3),d(e.x1+.5,e.ridgeY,e.ridgeZ)],i=tn,a=ve(i.x0,i.y0,i.x1,i.y1,0,i.z),l=ve(i.x0-.15,i.y0-.15,i.x1+.15,i.y1+.15,i.z,i.z+.18);return v`
    <g class="house">
      <!-- soft contact shadow -->
      <polygon points=${k([d(e.x0-.6,e.y0-.2),d(i.x1+.9,i.y0-.2),d(i.x1+.9,i.y1+.9),d(e.x0-.6,e.y1+.9)])} class="contact-shadow"></polygon>
      <!-- garage (behind the house's right face order-wise it sits in front, draw after walls) -->
      <polygon points=${t.right} class="wall wall-r"></polygon>
      <polygon points=${k(r)} class="wall wall-r gable"></polygon>
      <polygon points=${t.left} class="wall wall-l"></polygon>
      <!-- windows and door on the front-left wall -->
      <polygon points=${D(e.y1+.02,.2,1.6,1.5,3.2)} class="window"></polygon>
      <polygon points=${D(e.y1+.02,2,3.4,1.5,3.2)} class="window"></polygon>
      <polygon points=${D(e.y1+.02,.2,1.6,.4,1.1)} class="window small"></polygon>
      <polygon points=${D(e.y1+.02,2.3,3.1,0,1.15)} class="door"></polygon>
      <polygon points=${D(e.y1+.02,3.9,4.8,1.5,3.2)} class="window"></polygon>
      <!-- windows on the right wall -->
      <polygon points=${ut(e.x1+.02,-2.4,-1.2,1.5,3.2)} class="window"></polygon>
      <polygon points=${ut(e.x1+.02,-2.4,-1.2,.3,1.1)} class="window small"></polygon>
      <!-- garage -->
      <polygon points=${a.right} class="wall wall-r"></polygon>
      <polygon points=${a.left} class="wall wall-l"></polygon>
      <polygon points=${D(i.y1+.02,7.6,10.4,0,1.9)} class="garage-door"></polygon>
      ${[.45,.9,1.35].map(u=>v`<polyline points=${k([d(7.6,i.y1+.03,u),d(10.4,i.y1+.03,u)])} class="garage-line"></polyline>`)}
      <polygon points=${a.top} class="roof-flat"></polygon>
      <polygon points=${l.left} class="roof-lip"></polygon>
      <polygon points=${l.right} class="roof-lip"></polygon>
      <polygon points=${l.top} class="roof-flat-top"></polygon>
      <!-- roof -->
      <polygon points=${k(o)} class="roof roof-back"></polygon>
      <polygon points=${k(n)} class="roof roof-front"></polygon>
      <polygon points=${k(s)} class="fascia"></polygon>
      <polyline points=${k([d(e.x0-.5,e.ridgeY,e.ridgeZ),d(e.x1+.5,e.ridgeY,e.ridgeZ)])} class="ridge"></polyline>
      ${Gn()}
      ${Vn()}
    </g>`}function Gn(){let e=X,t=[],n=5,o=2,r=e.x0+.25,s=e.x1-.75,i=.14,a=(s-r-i*(n-1))/n,l=.16,u=.9,p=.05,c=(u-l-p*(o-1))/o;for(let f=0;f<o;f++)for(let g=0;g<n;g++){let h=r+g*(a+i),m=h+a,R=l+f*(c+p),P=R+c,x=[de(h,R,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),de(m,R,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),de(m,P,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ),de(h,P,e.y1+.5,e.z-.25,e.ridgeY,e.ridgeZ)].map($=>({x:$.x,y:$.y-1.2}));t.push(v`<polygon points=${k(x)} class="pv"></polygon>`),t.push(v`<polygon points=${k(x)} fill="url(#ef3d-pv-glare)" class="pv-glare"></polygon>`);let M=($,A,S)=>({x:$.x+(A.x-$.x)*S,y:$.y+(A.y-$.y)*S});for(let $ of[1/3,2/3])t.push(v`<line x1=${M(x[0],x[3],$).x} y1=${M(x[0],x[3],$).y} x2=${M(x[1],x[2],$).x} y2=${M(x[1],x[2],$).y} class="pv-line"></line>`),t.push(v`<line x1=${M(x[0],x[1],$).x} y1=${M(x[0],x[1],$).y} x2=${M(x[3],x[2],$).x} y2=${M(x[3],x[2],$).y} class="pv-line"></line>`)}return t}function Vn(){let e=ne,t=D(e.y+.03,e.x0,e.x1,e.z0,e.z1),n=d(e.x1-.18,e.y+.05,e.z1-.22),o=r=>k([d(e.x0+.18,e.y+.05,r),d(e.x1-.18,e.y+.05,r)]);return v`
    <g class="inverter">
      <polygon points=${t} class="inverter-face"></polygon>
      <polyline points=${o(e.z0+.3)} class="inverter-vent"></polyline>
      <polyline points=${o(e.z0+.5)} class="inverter-vent"></polyline>
      <circle cx=${n.x} cy=${n.y} r="1.6" class="inverter-led"></circle>
      <circle cx=${n.x} cy=${n.y} r="4" class="inverter-led-halo"></circle>
    </g>`}function qn(e){let t=ue,n=ve(t.x0,t.y0,t.x1,t.y1,0,t.z),o=t.x0+.18,r=.16,s=.3,i=t.z-.3,a=e===null?s:s+Math.max(0,Math.min(100,e))/100*(i-s),l=d((t.x0+t.x1)/2+.15,t.y1+.04,t.z*.56);return v`
    <g class="battery-cabinet">
      <ellipse cx=${d((t.x0+t.x1)/2,(t.y0+t.y1)/2).x} cy=${d((t.x0+t.x1)/2,(t.y0+t.y1)/2).y+3} rx="20" ry="7" class="contact-shadow soft"></ellipse>
      <polygon points=${n.right} class="cab cab-r"></polygon>
      <polygon points=${n.left} class="cab cab-l"></polygon>
      <polygon points=${n.top} class="cab cab-t"></polygon>
      <polygon points=${D(t.y1+.03,o,o+r,s,i)} class="cab-strip-bg"></polygon>
      ${e===null?y:v`<polygon points=${D(t.y1+.04,o,o+r,s,a)} class="cab-strip"></polygon>`}
      <text x="0" y="0" class="cab-label" transform=${`matrix(0.866 0.5 0 1 ${l.x.toFixed(1)} ${l.y.toFixed(1)})`}>ECCO</text>
    </g>`}function Yn(e,t){let n=j,o=118,r={x:n.x-4,y:n.y-o},s=18,i=(p,c)=>v`<line x1=${n.x-4-c} y1=${p} x2=${n.x-4+c} y2=${p} class="pylon-line"></line>`,a=v`
    <line x1=${n.x-s} y1=${n.y} x2=${r.x-2} y2=${r.y} class="pylon-line"></line>
    <line x1=${n.x+s-8} y1=${n.y} x2=${r.x+2} y2=${r.y} class="pylon-line"></line>
    <line x1=${n.x-s+5} y1=${n.y-2} x2=${r.x} y2=${r.y+4} class="pylon-line thin"></line>
    <line x1=${n.x+s-12} y1=${n.y-2} x2=${r.x} y2=${r.y+4} class="pylon-line thin"></line>`,l=[];for(let p=1;p<7;p++){let c=n.y-o/7*p,f=(s-8)*(1-p/8)+3;l.push(v`<line x1=${n.x-4-f} y1=${c} x2=${n.x-4+f} y2=${c-6} class="pylon-line thin"></line>`),l.push(v`<line x1=${n.x-4+f} y1=${c} x2=${n.x-4-f} y2=${c-6} class="pylon-line thin"></line>`)}let u=[r.y+24,r.y+44].map(p=>v`<path d=${`M ${(n.x-4-26).toFixed(1)} ${p} Q ${(n.x+30).toFixed(1)} ${p+18} ${410} ${p-12}`} class="wire"></path>`);return v`
    <g class=${`pylon ${e?"live":""} ${t?"unknown":""}`}>
      ${a}${l}
      ${i(r.y+22,26)}${i(r.y+42,20)}
      ${u}
      <circle cx=${r.x} cy=${r.y-2} r="3" class="pylon-tip"></circle>
    </g>`}function Le(e,t,n,o){let{edge:r,motion:s}=n,i=sn[e],a=`flow flow-${e} ${r.unknown?"unknown":""} ${r.idle?"idle":""} ${s.moving&&o?"moving":""} ${r.reversed?"reversed":""}`,l=`ef3d-path-${e}`,u=s.moving?`stroke-dasharray:${s.dashLen.toFixed(1)} ${s.gapLen.toFixed(1)}; animation-duration:${s.dashDurationS.toFixed(2)}s; stroke-width:${s.packetWidthPx.toFixed(2)}; opacity:${s.packetOpacity.toFixed(2)}`:"",p=s.moving?`stroke-width:${(s.packetWidthPx*2.6).toFixed(1)}; opacity:${(.18+s.intensity*.3).toFixed(2)}`:"",c=[];if(s.moving&&o){let g=s.ballCount;for(let h=0;h<g;h++)c.push(v`
        <g class="pulse" data-path=${l} data-duration=${s.ballDurationS.toFixed(3)} data-phase=${(h/g).toFixed(3)} data-reversed=${r.reversed?"1":"0"} style=${`--pulse-colour:${i}`}>
          <circle r=${(s.ballRadiusPx*1.9).toFixed(2)} class="pulse-halo"></circle>
          <circle r=${s.ballRadiusPx.toFixed(2)} class="pulse-glow"></circle>
          <circle r=${(s.ballRadiusPx*.42).toFixed(2)} class="pulse-core"></circle>
        </g>`)}let f=[];if(s.moving&&!o)for(let g of[.3,.55,.8])f.push(v`<g class="chevron" data-path=${l} data-phase=${g} data-reversed=${r.reversed?"1":"0"} style=${`--pulse-colour:${i}`}><path d="M -4 -4 L 2 0 L -4 4" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path></g>`);return v`
    <g class=${a} style=${`--flow-colour:${i}`}>
      <path d=${t} class="flow-base" style=${`stroke-width:${s.baseWidthPx.toFixed(2)}`}></path>
      <path d=${t} class="flow-dots"></path>
      <path d=${t} class="flow-glow" style=${p}></path>
      <path id=${l} d=${t} class="flow-packets" style=${u}></path>
      ${c}${f}
    </g>`}function Ue(e,t,n,o,r){let s=sn[e],i=14,a=e==="battery",l=22,u=2*Math.PI*l,p=n.soc??null,c=p===null?0:Math.max(0,Math.min(100,p))/100*u,f=t.x+52,g=t.x+t.w-36,h=t.y+t.h/2,m=r.edge.unknown?"unknown":r.edge.idle?"idle":"active";return v`
    <g class=${`pill pill-${e} tone-${n.tone} ${m} ${n.clickable?"clickable":""}`}
       style=${`--pill-colour:${s}`}
       role=${n.clickable?"button":"img"}
       tabindex=${n.clickable?0:-1}
       aria-label=${`${n.label}: ${n.value}${n.sub?", "+n.sub:""}`}
       @click=${()=>o(e)}
       @keydown=${R=>{(R.key==="Enter"||R.key===" ")&&(R.preventDefault(),o(e))}}>
      <rect x=${t.x} y=${t.y} width=${t.w} height=${t.h} rx=${i} class="pill-bg"></rect>
      <rect x=${t.x} y=${t.y} width=${t.w} height=${t.h} rx=${i} class="pill-border"></rect>
      <circle cx=${t.x+27} cy=${t.y+t.h/2} r="15" class="pill-icon-bg"></circle>
      ${rn(n.icon,t.x+16,t.y+t.h/2-11,22,s)}
      <text x=${f} y=${t.y+19} class="pill-label">${n.label}</text>
      <text x=${f} y=${t.y+(n.sub?39:42)} class="pill-value">${n.value}</text>
      ${n.sub?v`<text x=${f} y=${t.y+t.h-8} class="pill-sub">${n.sub}</text>`:y}
      ${a?v`
            <circle cx=${g} cy=${h} r=${l} class="ring-track"></circle>
            ${p===null?y:v`<circle cx=${g} cy=${h} r=${l} class="ring-fill" stroke-dasharray=${`${c.toFixed(1)} ${u.toFixed(1)}`} transform=${`rotate(-90 ${g} ${h})`}></circle>`}
            <text x=${g} y=${h+4} class="ring-value">${p===null?"--":`${Math.round(p)}%`}</text>
            <text x=${g} y=${h+14} class="ring-caption">SOC</text>`:n.clickable?rn("chevron",t.x+t.w-24,t.y+t.h/2-8,16,"rgba(255,255,255,0.45)"):y}
    </g>`}function ln(e){let t=nn(),n=e.flows.grid.motion.moving,o=dt;return v`
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
        ${[[40,92],[122,46],[180,112],[236,70],[352,150],[392,60],[20,160],[288,20]].map(([r,s])=>v`<circle cx=${r} cy=${s} r="1.1" class="star"></circle>`)}
      </g>
      ${Bn()}
      ${He(-6.5,-4.6,13,"back")}
      ${He(-2.5,-5.2,10,"back")}
      ${He(9.5,-5.6,11,"back")}
      ${pe(-7.2,1.2,8)}
      ${pe(-6.6,-1,7)}
      ${pe(5,5.2,7)}
      ${pe(6.4,6.4,6)}
      ${pe(-1.5,7.2,8)}
      ${pt(-4.8,6.6)}
      ${pt(3.9,5.2)}
      ${pt(7.4,8.6)}
      ${Yn(n,e.flows.grid.edge.unknown)}
      ${jn()}
      ${qn(e.pills.battery.soc??null)}
      ${He(-7.6,8.6,12,"front")}
      ${pe(1.2,8.8,7)}
      <g class="flows">
        ${Le("grid",t.grid,e.flows.grid,e.animate)}
        ${Le("solar",t.solar,e.flows.solar,e.animate)}
        ${Le("battery",t.battery,e.flows.battery,e.animate)}
        ${Le("home",t.home,e.flows.home,e.animate)}
        <circle cx=${o.x} cy=${o.y} r="4.2" class=${`junction led-${e.inverterLed}`}></circle>
        <circle cx=${o.x} cy=${o.y} r="9" class=${`junction-halo led-${e.inverterLed}`}></circle>
      </g>
      ${Ue("solar",Z.solar,e.pills.solar,e.onPill,e.flows.solar)}
      ${Ue("grid",Z.grid,e.pills.grid,e.onPill,e.flows.grid)}
      ${Ue("home",Z.home,e.pills.home,e.onPill,e.flows.home)}
      ${Ue("battery",Z.battery,e.pills.battery,e.onPill,e.flows.battery)}
    </svg>`}var Xn=15e3,G=class extends q{constructor(){super(...arguments);this._detailsOpen=!1;this._nowMs=Date.now();this._raf=0;this._timer=0;this._lengthCache=new WeakMap;this._onMotionPref=()=>{this.requestUpdate()}}static getStubConfig(){return{type:"custom:ecco-flow-3d-card",title:"Energy Flow",subtitle:"Live power overview",nodes:{solar:[{label:"Array 1",power:"sensor.pv1_power"}],inverter:{power:"sensor.inverter_power"},home:{power:"sensor.house_power"},battery:{power:"sensor.battery_power",soc:"sensor.battery_soc",power_sign:"charge_positive"},grid:{power:"sensor.grid_power",power_sign:"import_positive"}}}}setConfig(n){Ft(n),this._config=n}getCardSize(){return 8}connectedCallback(){super.connectedCallback(),window.matchMedia&&(this._reducedMotionQuery=window.matchMedia("(prefers-reduced-motion: reduce)"),this._reducedMotionQuery.addEventListener?.("change",this._onMotionPref)),this._timer=window.setInterval(()=>{this._nowMs=Date.now()},Xn)}disconnectedCallback(){super.disconnectedCallback(),this._reducedMotionQuery?.removeEventListener?.("change",this._onMotionPref),window.clearInterval(this._timer),cancelAnimationFrame(this._raf),this._raf=0}firstUpdated(){this._animate()}updated(n){this._placeChevrons()}get _reducedMotion(){return!!this._reducedMotionQuery?.matches}_moreInfo(n){n&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:n},bubbles:!0,composed:!0}))}render(){let n=this._config;if(!n)return N``;let o=this.hass?.states??{},r=n.nodes??{},s=n.ecco??{},i=new Date(this._nowMs),a=Pt(r.solar),l=a.map(C=>w(o,C.power)),u=Lt(w(o,r.solar_total),l),p=w(o,r.inverter?.power),c=w(o,r.battery?.power),f=c===null?null:It(c,r.battery?.power_sign),g=w(o,r.grid?.power),h=g===null?null:Ot(g,r.grid?.power_sign),m=Ht(w(o,r.home?.power),p,h),R=w(o,r.battery?.soc),P=Ut({solarW:u,batteryW:f,gridW:h,homeW:m}),F=Object.fromEntries(P.map(C=>[C.id,C])),x=U(E(o,s.telemetry_online)),M=Jt([...a.map(C=>C.power),r.solar_total,r.inverter?.power,r.battery?.power,r.grid?.power,r.home?.power],o,x,this._nowMs,n.features?.stale_after_s??Nt),$=M.stale,A=(n.features?.animate_flow??!0)&&!this._reducedMotion,S=zt(f),H=Bt(h),b=U(E(o,r.grid?.connected)),T={solar:{label:"Solar Generation",value:le(u),sub:a.length>1?a.map((C,_)=>le(l[_]??null)).join(" + "):"",tone:u===null?"muted":"ok",icon:"sun",clickable:!!(r.solar_total??a[0]?.power)},grid:{label:"Grid",value:le(h===null?null:Math.abs(h)),sub:b==="off"?"Disconnected":H==="importing"?"Importing":H==="exporting"?"Exporting":H==="idle"?"Idle":"Unknown",tone:b==="off"?"alert":H==="unknown"?"muted":"ok",icon:"pylon",clickable:!!r.grid?.power},home:{label:"Home Load",value:le(m),sub:"",tone:m===null?"muted":"ok",icon:"home",clickable:!!r.home?.power},battery:{label:"Battery Storage",value:le(f===null?null:Math.abs(f)),sub:S==="charging"?"Charging":S==="discharging"?"Discharging":S==="idle"?"Idle":"Unknown",tone:S==="unknown"?"muted":"ok",icon:"battery",clickable:!!(r.battery?.power??r.battery?.soc),soc:R}},I={daylight:en(s.sun?o[s.sun]:void 0,i),flows:{solar:{edge:F.solar,motion:we(F.solar,$)},battery:{edge:F.battery,motion:we(F.battery,$)},grid:{edge:F.grid,motion:we(F.grid,$)},home:{edge:F.home,motion:we(F.home,$)}},stale:$,animate:A,pills:T,inverterLed:$?"warn":P.some(C=>!C.unknown)?"ok":"off",onPill:C=>{let _=C==="solar"?r.solar_total??a[0]?.power:C==="grid"?r.grid?.power:C==="home"?r.home?.power:r.battery?.power??r.battery?.soc;this._moreInfo(_)}},K=Dt(P)&&!$,oe=this._chip(x,M.ageS,$,M.reason);return N`
      <ha-card>
        <div class="card">
          <header class="head">
            <div class="titles">
              <div class="brand">${n.title??"Energy Flow"}</div>
              ${n.subtitle?N`<div class="subtitle">${n.subtitle}</div>`:y}
            </div>
            <button class=${`chip tone-${oe.tone}`} type="button" @click=${()=>this._moreInfo(s.telemetry_online)} title=${oe.title}>
              <span class="dot"></span>${oe.text}
            </button>
          </header>
          ${$?N`<div class="strip stale-strip">${M.reason==="telemetry_offline"?"Telemetry offline: the values shown are the last received, not live.":`Values are stale: the newest power reading is ${ae(M.ageS)}.`}</div>`:y}
          <div class="body">
            <div class="scene-wrap">
              ${ln(I)}
              ${K?N`<div class="banner idle-banner">Site idle: no power is flowing above ${5} W.</div>`:y}
            </div>
            <div class="side">
              ${n.features?.show_status_panel===!1?y:this._renderStatus(o,i,$,M.ageS)}
              ${n.features?.show_details_panel===!1?y:this._renderDetails(o,a,l,u,p,f,h,m)}
            </div>
          </div>
        </div>
      </ha-card>
    `}_chip(n,o,r,s){return n==="off"?{text:"Telemetry offline",tone:"alert",title:"The dongle's telemetry polling is offline"}:r&&s==="age"?{text:`Stale \xB7 ${ae(o)}`,tone:"warn",title:"No power reading has updated recently"}:n==="on"?{text:"System online",tone:"ok",title:o===null?"Telemetry online":`Telemetry online \xB7 updated ${ae(o)}`}:{text:o===null?"Status unknown":`Updated ${ae(o)}`,tone:"muted",title:"No telemetry-online entity configured"}}_renderStatus(n,o,r,s){let i=this._config,a=i.ecco??{},l=i.nodes??{},u=[],p=a.tou,c=Kt((p?.slot_start_minutes??[]).map(_=>w(n,_)),Qt(o),p?.valid?U(E(n,p.valid)):"unknown"),f=c.slot===null?null:c.slot-1,g=f===null?void 0:p?.slot_target_soc?.[f],h=f===null?void 0:p?.slot_charge_source?.[f],m=f===null?void 0:p?.slot_power?.[f],R=w(n,g),P=E(n,h),F=w(n,m);u.push({key:"tou",icon:"clock",label:"TOU Slot",value:c.value,sub:c.sub,tone:c.tone,entity:f===null?p?.slot_start_minutes?.[0]:p?.slot_start_minutes?.[f],title:"The slot containing the current local time, from the six slot start sensors"}),u.push({key:"charge",icon:"plug",label:"Charge Source",value:h&&P&&P!=="unknown"&&P!=="unavailable"?P:"--",sub:f===null?"Needs the current slot":F!==null?`Slot limit ${Y(F,i.format)}`:"Current slot setting",tone:P&&P.toLowerCase()==="grid"?"accent":"muted",entity:h}),u.push({key:"target",icon:"target",label:"Target SOC",value:ot(R),sub:f===null?"Needs the current slot":`Slot ${c.slot} setting`,tone:R===null?"muted":"accent",entity:g});let x=l.battery?.time_to_reserve,M=Ie(x,w(n,x),L(n,x)?.unit_of_measurement),$=it(x,M,L(n,x)),A=Xt($);u.push({key:"runtime",icon:"battery",label:"Runtime",value:A.value,sub:A.sub,tone:A.tone,entity:x,title:$?lt($):"No time-to-reserve entity configured"});let S=a.free_power,H=at({active:U(E(n,S?.active)),endsAtText:E(n,S?.ends_at),scheduleStatus:E(n,S?.schedule_status),statusText:E(n,S?.status),scheduleAttrs:L(n,S?.schedule_status),anyConfigured:!!(S?.active||S?.status||S?.schedule_status)},this._nowMs,"free_power");u.push({key:"fp",icon:"leaf",label:"Free Power",value:H.value,sub:H.sub,tone:H.tone,entity:S?.status??S?.active??S?.schedule_status,title:E(n,S?.status)});let b=a.dump_to_grid,T=at({active:U(E(n,b?.active)),endsAtText:E(n,b?.ends_at),scheduleStatus:E(n,b?.schedule_status),statusText:E(n,b?.status),scheduleAttrs:L(n,b?.schedule_status),exportPowerW:w(n,b?.export_power),stopSoc:w(n,b?.stop_soc),anyConfigured:!!(b?.active||b?.status||b?.schedule_status)},this._nowMs,"dump");u.push({key:"dump",icon:"swap",label:"Dump to Grid",value:T.value,sub:T.sub,tone:T.tone,entity:b?.status??b?.active??b?.schedule_status,title:E(n,b?.status)});let I=ct(a.health?.sensors??[],a.health?.attention??[],n);u.push({key:"health",icon:I.grade==="FAILED"?"alert":"heart",label:"Health",value:I.value,sub:I.sub,tone:I.tone,entity:a.health?.sensors?.[0],wide:!0,title:[...I.failed.map(_=>`FAILED: ${_}`),...I.degraded.map(_=>`DEGRADED: ${_}`),...I.attention.map(_=>`attention: ${_}`),...I.unknown.map(_=>`unknown: ${_}`)].join(`
`)||"All configured subsystems healthy"});let K=w(n,a.forecast?.today),oe=w(n,a.forecast?.remaining),C=w(n,i.today?.solar);return u.push({key:"forecast",icon:"forecast",label:"Forecast Today",value:O(K,i.format),sub:oe!==null?`${O(oe,i.format)} still expected`+(C!==null?` \xB7 ${O(C,i.format)} so far`:""):C!==null?`${O(C,i.format)} generated so far`:a.forecast?.today?"Remaining forecast unavailable":"No forecast entity configured",tone:K===null?"muted":"ok",entity:a.forecast?.remaining??a.forecast?.today,wide:!0}),N`
      <section class="status" aria-label="ECCO system status">
        <div class="status-head">
          <span class="status-title">ECCO System Status</span>
          <span class=${`status-age ${r?"stale":""}`}><span class="dot"></span>${s===null?"No timestamp":`Updated ${ae(s)}`}</span>
        </div>
        <div class="tiles">
          ${u.map(_=>N`
              <button
                type="button"
                class=${`tile tone-${_.tone} ${_.wide?"wide":""} ${_.entity?"clickable":""}`}
                title=${_.title??""}
                ?disabled=${!_.entity}
                @click=${()=>this._moreInfo(_.entity)}
              >
                <span class="tile-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d=${ce[_.icon]}></path></svg></span>
                <span class="tile-text">
                  <span class="tile-label">${_.label}</span>
                  <span class="tile-value">${_.value}</span>
                  ${_.sub?N`<span class="tile-sub">${_.sub}</span>`:y}
                </span>
                ${_.entity?N`<svg class="tile-chev" viewBox="0 0 24 24" aria-hidden="true"><path d=${ce.chevron}></path></svg>`:y}
              </button>
            `)}
        </div>
      </section>
    `}_renderDetails(n,o,r,s,i,a,l,u){let p=this._config,c=p.nodes??{},f=p.ecco??{},g=p.inverter_details??{},h=p.format,m=(b,T,I,K)=>N`
      <div class=${`row ${I?"clickable":""}`} @click=${()=>this._moreInfo(I)} role=${I?"button":"listitem"} tabindex=${I?0:-1}>
        <span class="row-label">${b}</span>
        <span class="row-value">${T}${K?N`<span class="row-note">${K}</span>`:y}</span>
      </div>`,R=b=>{let T=w(n,b);return T===null?"--":`${T.toFixed(1)} \xB0C`},P=Zt(c.battery?.time_to_target,n),F=U(E(n,c.grid?.connected)),x=c.battery?.time_to_reserve,M=it(x,Ie(x,w(n,x),L(n,x)?.unit_of_measurement),L(n,x)),$=ct(f.health?.sensors??[],f.health?.attention??[],n),A=p.today??{},S=Object.values(A).some(Boolean),H=w(n,f.forecast?.tomorrow);return N`
      <details class="details" ?open=${this._detailsOpen} @toggle=${b=>this._detailsOpen=b.target.open}>
        <summary>
          <span>Inverter, grid and diagnostics</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${ce.chevron}></path></svg>
        </summary>
        <div class="details-grid">
          <div class="group">
            <div class="group-title">Inverter</div>
            ${m("State",E(n,c.inverter?.state)??"--",c.inverter?.state)}
            ${m("AC output",Y(i,h),c.inverter?.power)}
            ${m("Home load",Y(u,h),c.home?.power,w(n,c.home?.power)===0&&u!==0?"derived":void 0)}
            ${m("AC transformer",R(g.ac_temperature),g.ac_temperature)}
            ${m("DC transformer",R(g.dc_temperature),g.dc_temperature)}
            ${g.temperature?m("Temperature",R(g.temperature),g.temperature):y}
          </div>
          <div class="group">
            <div class="group-title">Grid</div>
            ${m("Connected",F==="on"?"Yes":F==="off"?"No":"Unknown",c.grid?.connected)}
            ${m("Power",l===null?"--":`${Y(Math.abs(l),h)} ${l>=5?"import":l<=-5?"export":""}`,c.grid?.power)}
            ${m("Voltage",w(n,c.grid?.voltage)===null?"--":`${w(n,c.grid?.voltage).toFixed(1)} V`,c.grid?.voltage)}
            ${m("Frequency",w(n,c.grid?.frequency)===null?"--":`${w(n,c.grid?.frequency).toFixed(2)} Hz`,c.grid?.frequency)}
          </div>
          <div class="group">
            <div class="group-title">Solar</div>
            ${o.map((b,T)=>m(b.label??`Array ${T+1}`,Y(r[T]??null,h),b.power))}
            ${m("Total",Y(s,h),c.solar_total,c.solar_total?void 0:o.length>1?"sum of arrays":void 0)}
            ${f.forecast?.tomorrow?m("Forecast tomorrow",O(H,h),f.forecast.tomorrow):y}
          </div>
          <div class="group">
            <div class="group-title">Battery</div>
            ${m("Power",a===null?"--":`${Y(Math.abs(a),h)} ${a>=5?"discharge":a<=-5?"charge":""}`,c.battery?.power)}
            ${m("State of charge",ot(w(n,c.battery?.soc)),c.battery?.soc)}
            ${m("Time to reserve",M?lt(M).replace(/^Time to reserve: /,""):"No entity configured",x)}
            ${m("Time to charge target",P.value,c.battery?.time_to_target,P.sub)}
            ${g.battery_temperature?m("Temperature",R(g.battery_temperature),g.battery_temperature):y}
          </div>
          ${(f.health?.sensors?.length??0)>0?N`<div class="group">
                  <div class="group-title">Health</div>
                  ${(f.health?.sensors??[]).map(b=>{let T=(E(n,b)??"--").toUpperCase();return m(b.replace(/^.*?\./,"").replace(/^ecco_health_/,"").replace(/_/g," "),T==="HEALTHY"?"Healthy":T==="DEGRADED"?"Degraded":T==="FAILED"?"Failed":"Unknown",b,typeof L(n,b)?.summary=="string"&&T!=="HEALTHY"?String(L(n,b)?.summary).trim().slice(0,80):void 0)})}
                  ${(f.health?.attention??[]).map(b=>m(b.replace(/^.*?\./,"").replace(/_/g," "),U(E(n,b))==="on"?"Needs attention":U(E(n,b))==="off"?"Clear":"Unknown",b))}
                  ${$.attention.length+$.failed.length>0?N`<div class="row-note block">Warnings are listed in full above; the Health tile summarises them.</div>`:y}
                </div>`:y}
          ${S?N`<div class="group today">
                  <div class="group-title">Today</div>
                  ${m("Solar",O(w(n,A.solar),h),A.solar)}
                  ${m("Load",O(w(n,A.load),h),A.load)}
                  ${m("Import",O(w(n,A.import),h),A.import)}
                  ${m("Export",O(w(n,A.export),h),A.export)}
                  ${m("Battery charge",O(w(n,A.battery_charge),h),A.battery_charge)}
                  ${m("Battery discharge",O(w(n,A.battery_discharge),h),A.battery_discharge)}
                </div>`:y}
        </div>
      </details>
    `}_pathFor(n,o){let r=n.querySelector(`#${CSS.escape(o)}`);if(!r)return null;let s=r.getAttribute("d")??"",i=this._lengthCache.get(r);return(!i||i.d!==s)&&(i={d:s,length:r.getTotalLength()},this._lengthCache.set(r,i)),i.length?{path:r,length:i.length}:null}_animate(){this._raf=requestAnimationFrame(()=>this._animate());let n=this.shadowRoot;if(!n||this._reducedMotion)return;let o=n.querySelectorAll(".pulse");if(!o.length)return;let r=performance.now()/1e3;o.forEach(s=>{let i=s.dataset.path,a=parseFloat(s.dataset.duration??""),l=parseFloat(s.dataset.phase??"0");if(!i||!a)return;let u=this._pathFor(n,i);if(!u)return;let p=(r/a+l)%1;s.dataset.reversed==="1"&&(p=1-p);let c=u.path.getPointAtLength(p*u.length);s.setAttribute("transform",`translate(${c.x.toFixed(2)},${c.y.toFixed(2)})`)})}_placeChevrons(){let n=this.shadowRoot;n&&n.querySelectorAll(".chevron").forEach(o=>{let r=o.dataset.path,s=parseFloat(o.dataset.phase??"0.5");if(!r)return;let i=this._pathFor(n,r);if(!i)return;let a=o.dataset.reversed==="1",l=(a?1-s:s)*i.length,u=i.path.getPointAtLength(Math.max(0,l-2)),p=i.path.getPointAtLength(Math.min(i.length,l+2)),c=Math.atan2(p.y-u.y,p.x-u.x)*180/Math.PI+(a?180:0),f=i.path.getPointAtLength(l);o.setAttribute("transform",`translate(${f.x.toFixed(2)},${f.y.toFixed(2)}) rotate(${c.toFixed(1)})`)})}};G.styles=ze`
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
        grid-template-columns: minmax(0, 1.2fr) minmax(300px, 1fr);
        align-items: start;
      }
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
        stroke-dashoffset: -30;
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
  `,re([Me({attribute:!1})],G.prototype,"hass",2),re([Te()],G.prototype,"_config",2),re([Te()],G.prototype,"_detailsOpen",2),re([Te()],G.prototype,"_nowMs",2),G=re([Rt("ecco-flow-3d-card")],G);window.customCards=[...window.customCards??[],{type:"ecco-flow-3d-card",name:"ECCO 3D Energy Flow",description:"Read-only isometric energy flow scene (solar, battery, grid, home) with animated power paths and the ECCO status grid.",preview:!1}];export{G as EccoFlow3dCard};
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
