// A small DOM for the node tests (not a test file: the test glob is test/*.test.mjs).
//
// It is NOT a browser. It gives the card REAL node trees to patch: node identity, attributes, text nodes,
// an HTML parser for the markup the card renders, serialisation, live ranges (a text selection) that follow
// the DOM spec's adjustment rules for replaceData / node removal, focus, and a mutation log. Layout, painting
// and real selection / scrolling behaviour are checked against the preview in a real browser instead.

const ENT = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (e) => ENT[e]);
const escText = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escAttr = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link']);

export class MNode {
  constructor(doc) {
    this.ownerDocument = doc;
    this.parentNode = null;
    this.childNodes = [];
  }

  get firstChild() {
    return this.childNodes[0] || null;
  }

  get isConnected() {
    let n = this;
    while (n.parentNode) n = n.parentNode;
    return n.nodeType === 11 || n.nodeType === 9 ? n.isRoot === true : false;
  }

  _detach() {
    const p = this.parentNode;
    if (!p) return;
    const idx = p.childNodes.indexOf(this);
    p.childNodes.splice(idx, 1);
    this.parentNode = null;
    this.ownerDocument._removed(this, p, idx);
    this.ownerDocument._log('childList', p);
  }

  appendChild(n) {
    return this.insertBefore(n, null);
  }

  insertBefore(n, ref) {
    if (n.nodeType === 11) {
      for (const c of [...n.childNodes]) this.insertBefore(c, ref);
      return n;
    }
    n._detach();
    const at = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
    this.childNodes.splice(at, 0, n);
    n.parentNode = this;
    this.ownerDocument._log('childList', this);
    return n;
  }

  removeChild(n) {
    if (n.parentNode !== this) throw new Error('removeChild: not a child');
    n._detach();
    return n;
  }

  replaceWith(...nodes) {
    const p = this.parentNode;
    if (!p) return;
    const ref = p.childNodes[p.childNodes.indexOf(this) + 1] || null;
    this._detach();
    for (const n of nodes) p.insertBefore(n, ref);
  }

  remove() {
    this._detach();
  }

  contains(n) {
    for (let c = n; c; c = c.parentNode) if (c === this) return true;
    return false;
  }
}

export class MText extends MNode {
  constructor(doc, value) {
    super(doc);
    this.nodeType = 3;
    this.nodeName = '#text';
    this._v = value;
  }

  get nodeValue() {
    return this._v;
  }

  // assigning the value is "replace data over the whole string" (DOM spec): live ranges inside it collapse
  set nodeValue(v) {
    this.replaceData(0, this._v.length, String(v));
  }

  get data() {
    return this._v;
  }

  get textContent() {
    return this._v;
  }

  replaceData(offset, count, data) {
    this.ownerDocument._log('replaceData', this, { offset, count, data });
    this._v = this._v.slice(0, offset) + data + this._v.slice(offset + count);
    for (const r of this.ownerDocument.ranges) {
      for (const k of ['start', 'end']) {
        if (r[`${k}Node`] !== this) continue;
        const o = r[`${k}Offset`];
        if (o > offset && o <= offset + count) r[`${k}Offset`] = offset;
        else if (o > offset + count) r[`${k}Offset`] = o + data.length - count;
      }
    }
  }
}

export class MElement extends MNode {
  constructor(doc, tag) {
    super(doc);
    this.nodeType = 1;
    this.nodeName = tag.toUpperCase();
    this.tagName = this.nodeName;
    this.attrs = new Map();
    this.style = { _p: {}, setProperty(k, v) { this._p[k] = v; }, getPropertyValue(k) { return this._p[k] || ''; } };
    this.dataset = {};
    this.scrollLeft = 0;
    this.offsetWidth = 0;
  }

  get attributes() {
    return [...this.attrs].map(([name, value]) => ({ name, value }));
  }

  getAttribute(k) {
    return this.attrs.has(k) ? this.attrs.get(k) : null;
  }

  hasAttribute(k) {
    return this.attrs.has(k);
  }

  setAttribute(k, v) {
    this.attrs.set(k, String(v));
    this.ownerDocument._log('attributes', this, { name: k });
  }

  removeAttribute(k) {
    if (this.attrs.delete(k)) this.ownerDocument._log('attributes', this, { name: k });
  }

  get id() {
    return this.getAttribute('id') || '';
  }

  get className() {
    return this.getAttribute('class') || '';
  }

  set className(v) {
    this.setAttribute('class', v);
  }

  get children() {
    return this.childNodes.filter((n) => n.nodeType === 1);
  }

  get firstElementChild() {
    return this.children[0] || null;
  }

  get innerHTML() {
    return this.childNodes.map(serialize).join('');
  }

  set innerHTML(html) {
    for (const c of [...this.childNodes]) c._detach();
    for (const n of parseHtml(html, this.ownerDocument)) this.appendChild(n);
    this.ownerDocument._log('innerHTML', this);
  }

  get outerHTML() {
    return serialize(this);
  }

  get textContent() {
    return this.childNodes.map((n) => n.textContent).join('');
  }

  set textContent(v) {
    for (const c of [...this.childNodes]) c._detach();
    this.appendChild(new MText(this.ownerDocument, String(v)));
    this.ownerDocument._log('textContent', this);
  }

  matches(sel) {
    return matchSimple(this, sel);
  }

  closest(sel) {
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.matches(sel)) return n;
    return null;
  }

  querySelectorAll(sel) {
    return queryAll(this, sel);
  }

  querySelector(sel) {
    return queryAll(this, sel, true)[0] || null;
  }

  focus() {
    this.ownerDocument._active = this;
  }

  scrollIntoView() {}
}

export class MFragment extends MNode {
  constructor(doc) {
    super(doc);
    this.nodeType = 11;
    this.nodeName = '#document-fragment';
  }

  get children() {
    return this.childNodes.filter((n) => n.nodeType === 1);
  }

  get firstElementChild() {
    return this.children[0] || null;
  }
}

class MTemplate extends MElement {
  constructor(doc) {
    super(doc, 'template');
    this.content = new MFragment(doc);
  }

  set innerHTML(html) {
    for (const c of [...this.content.childNodes]) c._detach();
    for (const n of parseHtml(html, this.ownerDocument)) this.content.appendChild(n);
  }

  get innerHTML() {
    return this.content.childNodes.map(serialize).join('');
  }
}

export class MShadowRoot extends MFragment {
  constructor(host, doc) {
    super(doc);
    this.host = host;
    this.isRoot = true;
    this.listeners = {};
  }

  get innerHTML() {
    return this.childNodes.map(serialize).join('');
  }

  set innerHTML(html) {
    for (const c of [...this.childNodes]) c._detach();
    for (const n of parseHtml(html, this.ownerDocument)) this.appendChild(n);
  }

  get activeElement() {
    const a = this.ownerDocument._active;
    return a && this.contains(a) ? a : null;
  }

  getElementById(id) {
    return queryAll(this, `#${id}`, true)[0] || null;
  }

  querySelector(sel) {
    return queryAll(this, sel, true)[0] || null;
  }

  querySelectorAll(sel) {
    return queryAll(this, sel);
  }

  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }

  /**
   * Deliver a click on `target` to the card's listener the way the browser would (event.target + bubbling). A click made
   * by a pointer or a key press is trusted (isTrusted true); pass `{ isTrusted: false }` for an event that a script
   * dispatched, or `{}` for one that carries no flag at all.
   */
  click(target, init = { isTrusted: true }) {
    for (const fn of this.listeners.click || []) fn({ target, ...init });
  }

  getSelection() {
    return { toString: () => '' };
  }
}

export class MDocument {
  constructor() {
    this.nodeType = 9;
    this.ranges = [];
    this.mutations = [];
    this._active = null;
    this.hidden = false;
    this._events = {};
  }

  createElement(tag) {
    return tag === 'template' ? new MTemplate(this) : new MElement(this, tag);
  }

  createTextNode(v) {
    return new MText(this, String(v));
  }

  createRange() {
    const r = {
      startNode: null, startOffset: 0, endNode: null, endOffset: 0,
      setStart(n, o) { this.startNode = n; this.startOffset = o; },
      setEnd(n, o) { this.endNode = n; this.endOffset = o; },
      toString() { return this.startNode && this.startNode === this.endNode ? this.startNode.nodeValue.slice(this.startOffset, this.endOffset) : ''; },
    };
    this.ranges.push(r);
    return r;
  }

  addEventListener(type, fn) {
    (this._events[type] ||= []).push(fn);
  }

  removeEventListener(type, fn) {
    this._events[type] = (this._events[type] || []).filter((f) => f !== fn);
  }

  get activeElement() {
    return this._active;
  }

  _log(type, target, extra = {}) {
    this.mutations.push({ type, target, ...extra });
  }

  // DOM spec "remove a node": a live range with a boundary inside the removed node moves to the parent
  _removed(node, parent, idx) {
    for (const r of this.ranges) {
      for (const k of ['start', 'end']) {
        if (r[`${k}Node`] && node.contains(r[`${k}Node`])) {
          r[`${k}Node`] = parent;
          r[`${k}Offset`] = idx;
        }
      }
    }
    if (this._active && node.contains(this._active)) this._active = null;
  }
}

// ---- parsing / serialising ---------------------------------------------------------
const TOKEN =
  /<!--[\s\S]*?-->|<\/([a-zA-Z][\w:-]*)\s*>|<([a-zA-Z][\w:-]*)((?:\s+[^\s"'<>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'<>=`]+))?)*)\s*(\/?)>|([^<]+|<)/g;
const ATTR = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>=`]+)))?/g;

export function parseHtml(html, doc) {
  const root = new MFragment(doc);
  const stack = [root];
  let m;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(html)) !== null) {
    const top = stack[stack.length - 1];
    if (m[1]) {
      // a closing tag pops to the matching open element (ignored when there is none)
      for (let i = stack.length - 1; i > 0; i -= 1) {
        if (stack[i].nodeName === m[1].toUpperCase()) { stack.length = i; break; }
      }
    } else if (m[2]) {
      const el = doc.createElement(m[2]);
      let a;
      ATTR.lastIndex = 0;
      while ((a = ATTR.exec(m[3])) !== null) el.attrs.set(a[1], decode(a[2] ?? a[3] ?? a[4] ?? ''));
      top.appendChild(el);
      if (m[2].toLowerCase() === 'style' && !m[4]) {
        const end = html.toLowerCase().indexOf('</style>', TOKEN.lastIndex);
        el.appendChild(doc.createTextNode(html.slice(TOKEN.lastIndex, end)));
        TOKEN.lastIndex = end + '</style>'.length;
      } else if (!m[4] && !VOID.has(m[2].toLowerCase())) stack.push(el);
    } else if (m[5] !== undefined) {
      top.appendChild(doc.createTextNode(decode(m[5])));
    }
  }
  const out = [...root.childNodes];
  for (const n of out) n._detach();
  return out;
}

export function serialize(n) {
  if (n.nodeType === 3) return escText(n.nodeValue);
  if (n.nodeName === 'STYLE') return `<style>${n.childNodes.map((c) => c.nodeValue).join('')}</style>`;
  const a = [...n.attrs].map(([k, v]) => ` ${k}="${escAttr(v)}"`).join('');
  const tag = n.nodeName.toLowerCase();
  return `<${tag}${a}>${n.childNodes.map(serialize).join('')}</${tag}>`;
}

// ---- tiny selectors: #id  .class  tag  [attr]  [attr="value"] (no combinators) ------------
function matchSimple(el, sel) {
  const re = /(#[\w-]+|\.[\w-]+|\[[\w:-]+(?:="[^"]*")?\]|^[a-zA-Z][\w-]*)/g;
  const parts = sel.match(re);
  if (!parts || parts.join('') !== sel) throw new Error(`minidom: unsupported selector ${sel}`);
  return parts.every((p) => {
    if (p[0] === '#') return el.getAttribute('id') === p.slice(1);
    if (p[0] === '.') return (el.getAttribute('class') || '').split(/\s+/).includes(p.slice(1));
    if (p[0] === '[') {
      const m = /^\[([\w:-]+)(?:="([^"]*)")?\]$/.exec(p);
      return m[2] === undefined ? el.hasAttribute(m[1]) : el.getAttribute(m[1]) === m[2];
    }
    return el.nodeName === p.toUpperCase();
  });
}

function queryAll(root, sel, firstOnly = false) {
  const out = [];
  const walk = (n) => {
    for (const c of n.childNodes) {
      if (c.nodeType !== 1) continue;
      if (matchSimple(c, sel)) {
        out.push(c);
        if (firstOnly) return true;
      }
      if (walk(c) && firstOnly) return true;
    }
    return false;
  };
  walk(root);
  return out;
}

// ---- globals the card module needs, installed before it is imported -----------------------
export function installDom() {
  const doc = new MDocument();
  class HTMLElementStub {
    attachShadow() {
      this.shadowRoot = new MShadowRoot(this, doc);
      return this.shadowRoot;
    }

    dispatchEvent(e) {
      (this.events ||= []).push(e);
      return true;
    }
  }
  const registry = new Map();
  globalThis.document = doc;
  globalThis.HTMLElement = HTMLElementStub;
  globalThis.customElements = { get: (n) => registry.get(n), define: (n, c) => registry.set(n, c) };
  globalThis.window = {};
  globalThis.CustomEvent = class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } };
  const store = new Map();
  globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
  return { doc, store, registry };
}
