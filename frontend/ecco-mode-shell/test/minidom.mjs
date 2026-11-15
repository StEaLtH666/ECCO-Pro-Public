// A small DOM stand-in for the node tests (not a test file: the test glob is test/*.test.mjs).
//
// The Mode Shell never sets innerHTML: it builds every node with createElement / createElementNS / createTextNode,
// setAttribute and textContent. So, unlike the Intelligence card's stand-in (which parses markup), this one is a real
// node tree with events and selectors, and it makes any innerHTML / outerHTML write THROW. It also RECORDS every tag name,
// attribute name and style property the card ever creates (document.recorded), which is how the XSS tests prove that no
// element or attribute NAME is ever derived from data.
//
// It is NOT a browser: layout, painting, focus order and CSS are checked with the preview page in headless Chrome.

export class MEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = init.bubbles !== undefined ? init.bubbles : true;
    this.composed = init.composed !== undefined ? init.composed : true;
    this.detail = init.detail;
    this.key = init.key;
    this.defaultPrevented = false;
    this.target = null;
  }

  preventDefault() {
    this.defaultPrevented = true;
  }

  stopPropagation() {
    this._stopped = true;
  }
}

export class MText {
  constructor(data) {
    this.nodeType = 3;
    this.data = String(data);
    this.parentNode = null;
  }

  get textContent() {
    return this.data;
  }

  set textContent(v) {
    this.data = String(v);
  }
}

const VOID_FOR_SELECT = new Set(['input', 'select', 'textarea']);

export class MElement {
  constructor(tag, doc) {
    this.nodeType = 1;
    this.tagName = String(tag).toLowerCase();
    this.namespaceURI = null;
    this.attrs = new Map();
    this.childNodes = [];
    this.parentNode = null;
    this.ownerDocument = doc || MElement.defaultDoc;
    this._listeners = new Map();
    this._props = new Map();
    this.value = '';
    this.disabled = false;
    const owner = this;
    this.style = {
      setProperty(name, val) {
        owner.ownerDocument.recorded.styleProps.add(String(name));
        owner._props.set(String(name), String(val));
      },
      getPropertyValue(name) {
        return owner._props.get(name) || '';
      },
      removeProperty(name) {
        owner._props.delete(name);
      },
    };
  }

  // ---- attributes ----
  setAttribute(n, v) {
    this.ownerDocument.recorded.attrNames.add(String(n));
    this.attrs.set(String(n), String(v));
    if (n === 'value') this.value = String(v);
  }

  getAttribute(n) {
    return this.attrs.has(n) ? this.attrs.get(n) : null;
  }

  hasAttribute(n) {
    return this.attrs.has(n);
  }

  removeAttribute(n) {
    this.attrs.delete(n);
  }

  toggleAttribute(n, force) {
    const on = force === undefined ? !this.attrs.has(n) : !!force;
    if (on) this.setAttribute(n, '');
    else this.attrs.delete(n);
    return on;
  }

  get hidden() {
    return this.attrs.has('hidden');
  }

  set hidden(v) {
    if (v) this.setAttribute('hidden', '');
    else this.attrs.delete('hidden');
  }

  get className() {
    return this.getAttribute('class') || '';
  }

  get id() {
    return this.getAttribute('id') || '';
  }

  get classList() {
    const owner = this;
    const list = () => owner.className.split(/\s+/).filter(Boolean);
    return {
      contains: (c) => list().includes(c),
      add: (c) => owner.setAttribute('class', [...new Set([...list(), c])].join(' ')),
      remove: (c) => owner.setAttribute('class', list().filter((x) => x !== c).join(' ')),
    };
  }

  // ---- tree ----
  appendChild(node) {
    if (node instanceof MFragment) {
      for (const c of [...node.childNodes]) this.appendChild(c);
      return node;
    }
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    this.childNodes.push(node);
    return node;
  }

  append(...nodes) {
    for (const n of nodes) this.appendChild(typeof n === 'string' ? this.ownerDocument.createTextNode(n) : n);
  }

  insertBefore(node, ref) {
    if (!ref) return this.appendChild(node);
    if (node.parentNode) node.parentNode.removeChild(node);
    const i = this.childNodes.indexOf(ref);
    node.parentNode = this;
    this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, node);
    return node;
  }

  removeChild(node) {
    const i = this.childNodes.indexOf(node);
    if (i >= 0) this.childNodes.splice(i, 1);
    node.parentNode = null;
    return node;
  }

  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }

  replaceChildren(...nodes) {
    for (const c of [...this.childNodes]) this.removeChild(c);
    this.append(...nodes);
  }

  get firstChild() {
    return this.childNodes[0] || null;
  }

  get children() {
    return this.childNodes.filter((n) => n.nodeType === 1);
  }

  get isConnected() {
    let n = this;
    while (n.parentNode) n = n.parentNode;
    return n instanceof MShadowRoot || n instanceof MDocument || n === this.ownerDocument.body;
  }

  get textContent() {
    return this.childNodes.map((n) => n.textContent).join('');
  }

  set textContent(v) {
    for (const c of [...this.childNodes]) this.removeChild(c);
    const s = v === null || v === undefined ? '' : String(v);
    if (s !== '') this.appendChild(this.ownerDocument.createTextNode(s));
  }

  get innerHTML() {
    throw new Error('minidom: innerHTML is forbidden (the Mode Shell builds nodes, never markup)');
  }

  set innerHTML(_v) {
    this.ownerDocument.recorded.innerHTMLAttempts += 1;
    throw new Error('minidom: innerHTML is forbidden (the Mode Shell builds nodes, never markup)');
  }

  get outerHTML() {
    throw new Error('minidom: outerHTML is forbidden');
  }

  set outerHTML(_v) {
    throw new Error('minidom: outerHTML is forbidden');
  }

  insertAdjacentHTML() {
    throw new Error('minidom: insertAdjacentHTML is forbidden');
  }

  contains(n) {
    for (let x = n; x; x = x.parentNode) if (x === this) return true;
    return false;
  }

  getRootNode() {
    let n = this;
    while (n.parentNode) n = n.parentNode;
    return n;
  }

  *descendants() {
    for (const c of this.childNodes) {
      if (c.nodeType === 1) {
        yield c;
        yield* c.descendants();
      }
    }
  }

  querySelectorAll(sel) {
    const alts = parseSelector(sel);
    const out = [];
    for (const el of this.descendants()) if (alts.some((chain) => matchChain(el, chain, this))) out.push(el);
    return out;
  }

  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }

  closest(sel) {
    const alts = parseSelector(sel);
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (alts.some((chain) => matchChain(n, chain, null))) return n;
    return null;
  }

  matches(sel) {
    return parseSelector(sel).some((chain) => matchChain(this, chain, null));
  }

  // ---- events ----
  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }

  removeEventListener(type, fn) {
    const l = this._listeners.get(type);
    if (l) this._listeners.set(type, l.filter((f) => f !== fn));
  }

  dispatchEvent(ev) {
    try {
      ev.target = this;
    } catch {
      // a native Event (CustomEvent) has a read-only target; the handlers under test do not read it
    }
    let n = this;
    const path = [];
    while (n) {
      path.push(n);
      n = n.parentNode || (n instanceof MShadowRoot && ev.composed ? n.host : null);
    }
    for (const node of path) {
      for (const fn of [...((node._listeners && node._listeners.get(ev.type)) || [])]) fn.call(node, ev);
      if (!ev.bubbles || ev._stopped) break;
    }
    return !ev.defaultPrevented;
  }

  click() {
    this.dispatchEvent(new MEvent('click'));
  }

  focus() {
    const root = this.getRootNode();
    if (root instanceof MShadowRoot) root.activeElement = this;
    this.ownerDocument.activeElement = this;
  }

  blur() {
    const root = this.getRootNode();
    if (root instanceof MShadowRoot && root.activeElement === this) root.activeElement = null;
  }

  /**
   * Any real element can take a shadow root (and a shadow root with no slot hides what the element holds). The card gives one to its own host and to nothing else:
   * modelling it on every element lets the element tests see a break that gives one to the alert strip (review round 5, reviewer mutant AR08).
   */
  attachShadow() {
    this.shadowRoot = new MShadowRoot(this);
    return this.shadowRoot;
  }

  scrollIntoView() {}

  getBoundingClientRect() {
    return { width: 100, height: 20, top: 0, left: 0, right: 100, bottom: 20 };
  }
}

export class MFragment extends MElement {
  constructor(doc) {
    super('#fragment', doc);
  }
}

export class MShadowRoot extends MElement {
  constructor(host) {
    super('#shadow-root', host.ownerDocument);
    this.host = host;
    this.activeElement = null;
  }
}

export class MDocument {
  constructor() {
    this.recorded = { tags: new Set(), attrNames: new Set(), styleProps: new Set(), innerHTMLAttempts: 0 };
    this.registry = new Map();
    this.activeElement = null;
    this.body = new MElement('body', this);
  }

  resetRecorded() {
    this.recorded.tags.clear();
    this.recorded.attrNames.clear();
    this.recorded.styleProps.clear();
    this.recorded.innerHTMLAttempts = 0;
  }

  /** Register a factory for a tag name so createElement(tag) returns a stub child card. */
  registerElement(tag, factory) {
    this.registry.set(tag, factory);
  }

  createElement(tag) {
    this.recorded.tags.add(String(tag).toLowerCase());
    const f = this.registry.get(String(tag).toLowerCase());
    if (f) {
      const el = f(this);
      el.ownerDocument = this;
      return el;
    }
    return new MElement(tag, this);
  }

  createElementNS(ns, tag) {
    this.recorded.tags.add(String(tag).toLowerCase());
    const el = new MElement(tag, this);
    el.namespaceURI = ns;
    return el;
  }

  createTextNode(s) {
    return new MText(s);
  }

  createDocumentFragment() {
    return new MFragment(this);
  }
}

// ---------------------------------------------------------------------------------------------------------------------------
// selectors: tag, #id, .class, [attr], [attr="v"], [attr^="v"], [attr*="v"], [attr$="v"]; descendant (space) and child (>)
// combinators; comma lists.
// ---------------------------------------------------------------------------------------------------------------------------
const cache = new Map();

function splitTop(s, sep) {
  const out = [];
  let depth = 0;
  let q = null;
  let cur = '';
  for (const ch of s) {
    if (q) {
      if (ch === q) q = null;
    } else if (ch === '"' || ch === "'") q = ch;
    else if (ch === '[') depth += 1;
    else if (ch === ']') depth -= 1;
    if (!q && depth === 0 && ch === sep) {
      out.push(cur);
      cur = '';
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

function parseCompound(s) {
  const m = s.match(/^([a-zA-Z][\w-]*|\*)?((?:#[\w-]+|\.[\w-]+|\[[^\]]+\])*)$/);
  if (!m) throw new Error(`minidom: unsupported selector part ${s}`);
  const tests = [];
  const tag = m[1] && m[1] !== '*' ? m[1].toLowerCase() : null;
  for (const t of m[2].match(/#[\w-]+|\.[\w-]+|\[[^\]]+\]/g) || []) {
    if (t[0] === '#') tests.push((e) => e.id === t.slice(1));
    else if (t[0] === '.') tests.push((e) => e.classList.contains(t.slice(1)));
    else {
      const a = t.slice(1, -1).match(/^([\w:-]+)(?:([~^$*|]?=)(?:"([^"]*)"|'([^']*)'|([^\]]*)))?$/);
      if (!a) throw new Error(`minidom: unsupported attribute selector ${t}`);
      const [, name, op, d, sgl, bare] = a;
      const val = d !== undefined ? d : sgl !== undefined ? sgl : bare;
      tests.push((e) => {
        if (!e.hasAttribute(name)) return false;
        if (!op) return true;
        const v = e.getAttribute(name);
        if (op === '=') return v === val;
        if (op === '^=') return v.startsWith(val);
        if (op === '$=') return v.endsWith(val);
        if (op === '*=') return v.includes(val);
        throw new Error(`minidom: unsupported operator ${op}`);
      });
    }
  }
  return (e) => e.nodeType === 1 && (!tag || e.tagName === tag) && tests.every((f) => f(e));
}

/** A chain is an array of {combinator, test}, rightmost last. */
function parseSelector(sel) {
  if (cache.has(sel)) return cache.get(sel);
  const alts = splitTop(sel, ',').map((alt) => {
    const tokens = [];
    let comb = ' ';
    for (const part of splitTop(alt.trim().replace(/\s*>\s*/g, ' > '), ' ')) {
      if (part === '') continue;
      if (part === '>') comb = '>';
      else {
        tokens.push({ comb, test: parseCompound(part) });
        comb = ' ';
      }
    }
    return tokens;
  });
  cache.set(sel, alts);
  return alts;
}

function matchChain(el, chain, scope) {
  const last = chain.length - 1;
  if (!chain[last].test(el)) return false;
  let node = el;
  for (let i = last; i > 0; i -= 1) {
    const { comb } = chain[i];
    const want = chain[i - 1].test;
    let p = node.parentNode;
    if (comb === '>') {
      if (!p || p === scope || !want(p)) return false;
      node = p;
    } else {
      while (p && p !== scope && !want(p)) p = p.parentNode;
      if (!p || p === scope) return false;
      node = p;
    }
  }
  return true;
}

// ---------------------------------------------------------------------------------------------------------------------------
// the window and the custom element host
// ---------------------------------------------------------------------------------------------------------------------------
export class MWindow {
  constructor() {
    this._l = new Map();
    this.location = { pathname: '/view-a' };
    this.customCards = undefined;
  }

  addEventListener(t, f) {
    if (!this._l.has(t)) this._l.set(t, []);
    this._l.get(t).push(f);
  }

  removeEventListener(t, f) {
    const l = this._l.get(t);
    if (l) this._l.set(t, l.filter((x) => x !== f));
  }

  dispatchEvent(ev) {
    for (const f of [...(this._l.get(ev.type) || [])]) f(ev);
  }

  listenerCount(t) {
    return (this._l.get(t) || []).length;
  }
}

/** Install the browser globals the module's registration needs, BEFORE the card module is evaluated. */
export function installDom() {
  const doc = new MDocument();
  MElement.defaultDoc = doc;
  const registry = new Map();
  class HTMLElementStub extends MElement {
    constructor() {
      super('ecco-mode-shell', doc);
    }

    attachShadow() {
      this.shadowRoot = new MShadowRoot(this);
      return this.shadowRoot;
    }
  }
  globalThis.HTMLElement = HTMLElementStub;
  globalThis.customElements = { get: (n) => registry.get(n), define: (n, c) => registry.set(n, c), registry };
  const win = new MWindow();
  globalThis.window = win;
  return { registry, doc, win };
}

/** A ResizeObserver stand-in the tests drive by hand (the element reports hidden as a 0 x 0 content box). */
export function installResizeObserver() {
  const instances = [];
  globalThis.ResizeObserver = class {
    constructor(cb) {
      this.cb = cb;
      this.targets = [];
      this.disconnected = false;
      instances.push(this);
    }

    observe(t) {
      this.targets.push(t);
    }

    unobserve() {}

    disconnect() {
      this.disconnected = true;
    }

    fire(width, height) {
      this.cb(this.targets.map((target) => ({ target, contentRect: { width, height } })));
    }
  };
  return instances;
}
