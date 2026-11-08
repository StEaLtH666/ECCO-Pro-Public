// A small DOM stand-in for the node tests (not a test file: the test glob is test/*.test.mjs). It follows the approach of
// frontend/ecco-fallback-recovery-card/test/minidom.mjs, much reduced: this card only sets innerHTML on its shadow root and
// reads back details[data-k] elements, so the stand-in parses the markup the card renders into real node trees, serialises
// them, answers simple selectors and records every innerHTML write. It is NOT a browser: layout and painting are checked
// with the preview page in headless Chrome instead.

const ENT = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };
export const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (e) => ENT[e]);
const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link', 'wbr']);
const RAW = new Set(['style', 'script']);

export class MText {
  constructor(value) {
    this.nodeType = 3;
    this.value = value;
    this.parentNode = null;
  }

  get textContent() {
    return decode(this.value);
  }
}

export class MElement {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toLowerCase();
    this.attrs = new Map();
    this.childNodes = [];
    this.parentNode = null;
  }

  getAttribute(n) {
    return this.attrs.has(n) ? decode(this.attrs.get(n)) : null;
  }

  hasAttribute(n) {
    return this.attrs.has(n);
  }

  setAttribute(n, v) {
    this.attrs.set(n, String(v));
  }

  get classList() {
    const c = (this.getAttribute('class') || '').split(/\s+/).filter(Boolean);
    return { contains: (x) => c.includes(x) };
  }

  get textContent() {
    if (RAW.has(this.tagName)) return '';
    return this.childNodes.map((n) => n.textContent).join('');
  }

  get innerHTML() {
    return this.childNodes.map(serialize).join('');
  }

  set innerHTML(html) {
    this.childNodes = parseHtml(html);
    for (const n of this.childNodes) n.parentNode = this;
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
    const m = compile(sel);
    return [...this.descendants()].filter(m);
  }

  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }

  closest(sel) {
    const m = compile(sel);
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (m(n)) return n;
    return null;
  }
}

export class MShadowRoot extends MElement {
  constructor(host) {
    super('#shadow-root');
    this.host = host;
    this.writes = 0;
  }

  set innerHTML(html) {
    this.writes += 1;
    super.innerHTML = html;
  }

  get innerHTML() {
    return super.innerHTML;
  }
}

/** Parse the markup the card renders (double-quoted attributes, no comments needed but tolerated). */
export function parseHtml(html) {
  const root = new MElement('#fragment');
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w-]*)((?:\s+[^\s=>/]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)|(<)/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const top = stack[stack.length - 1];
    if (m[0].startsWith('<!--')) continue;
    if (m[5] !== undefined || m[6] !== undefined) {
      const t = new MText(m[5] !== undefined ? m[5] : '<');
      t.parentNode = top;
      top.childNodes.push(t);
      continue;
    }
    const [, close, tagRaw, attrText, selfClose] = m;
    const tag = tagRaw.toLowerCase();
    if (close) {
      for (let i = stack.length - 1; i > 0; i -= 1) {
        if (stack[i].tagName === tag) {
          stack.length = i;
          break;
        }
      }
      continue;
    }
    const el = new MElement(tag);
    for (const a of attrText.matchAll(/([^\s=>/]+)(?:="([^"]*)")?/g)) el.attrs.set(a[1], a[2] === undefined ? '' : a[2]);
    el.parentNode = top;
    top.childNodes.push(el);
    if (RAW.has(tag)) {
      const end = html.indexOf(`</${tag}>`, re.lastIndex);
      const stop = end < 0 ? html.length : end;
      el.childNodes.push(new MText(html.slice(re.lastIndex, stop)));
      re.lastIndex = end < 0 ? html.length : end + tag.length + 3;
      continue;
    }
    if (!VOID.has(tag) && !selfClose) stack.push(el);
  }
  return root.childNodes;
}

export function serialize(n) {
  if (n.nodeType === 3) return n.value;
  const attrs = [...n.attrs].map(([k, v]) => (v === '' ? ` ${k}` : ` ${k}="${v}"`)).join('');
  if (VOID.has(n.tagName)) return `<${n.tagName}${attrs}>`;
  return `<${n.tagName}${attrs}>${n.childNodes.map(serialize).join('')}</${n.tagName}>`;
}

// ---- tiny selectors: tag, .class, [attr], [attr="value"], compounds of these; no combinators ----
function compile(sel) {
  const parts = sel.trim().match(/^([a-z][\w-]*)?((?:\.[\w-]+|\[[^\]]+\])*)$/i);
  if (!parts) throw new Error(`minidom: unsupported selector ${sel}`);
  const tag = parts[1] ? parts[1].toLowerCase() : null;
  const tests = [];
  for (const t of (parts[2] || '').match(/\.[\w-]+|\[[^\]]+\]/g) || []) {
    if (t.startsWith('.')) tests.push((e) => e.classList.contains(t.slice(1)));
    else {
      const a = t.slice(1, -1).match(/^([\w-]+)(?:="([^"]*)")?$/);
      if (!a) throw new Error(`minidom: unsupported attribute selector ${t}`);
      tests.push(a[2] === undefined ? (e) => e.hasAttribute(a[1]) : (e) => e.getAttribute(a[1]) === a[2]);
    }
  }
  return (e) => e.nodeType === 1 && (!tag || e.tagName === tag) && tests.every((f) => f(e));
}

/** A fragment for an HTML string, for structural assertions on the pure renderers. */
export function fragment(html) {
  const f = new MElement('#fragment');
  f.innerHTML = html;
  return f;
}

/** Install the browser globals the module's registration needs, BEFORE the card module is evaluated. */
export function installDom() {
  const registry = new Map();
  class HTMLElementStub {
    attachShadow() {
      this.shadowRoot = new MShadowRoot(this);
      return this.shadowRoot;
    }
  }
  globalThis.HTMLElement = HTMLElementStub;
  globalThis.customElements = { get: (n) => registry.get(n), define: (n, c) => registry.set(n, c), registry };
  globalThis.window = {};
  return registry;
}
