// A minimal, recording stand-in for the browser pieces the card touches: HTMLElement + an open shadow root,
// customElements, window.customCards, and network / timer APIs that must never be used. Install it BEFORE importing the
// card module (the card's class extends HTMLElement at evaluation time).
import type { StatesLike } from "../src/types.ts";

type Listener = (ev: unknown) => void;

export class FakeRegion {
  private _html = "";
  writes = 0;
  value: unknown = undefined;
  get innerHTML(): string {
    return this._html;
  }
  set innerHTML(v: string) {
    this._html = v;
    this.writes++;
  }
}

/** The shadow root: replacing its HTML replaces its regions, like the DOM does. */
export class FakeRoot {
  private _html = "";
  regions = new Map<string, FakeRegion>();
  listeners = new Map<string, Listener[]>();
  shellWrites = 0;
  get innerHTML(): string {
    return this._html;
  }
  set innerHTML(v: string) {
    this._html = v;
    this.shellWrites++;
    this.regions = new Map();
    for (const m of v.matchAll(/data-region="([a-z]+)"/g)) this.regions.set(m[1] ?? "", new FakeRegion());
    if (v.includes('data-action="search"')) this.regions.set("@search", new FakeRegion());
  }
  querySelector(selector: string): FakeRegion | null {
    const m = /^\[data-region="([a-z]+)"\]$/.exec(selector);
    if (m) return this.regions.get(m[1] ?? "") ?? null;
    if (selector === 'input[data-action="search"]') return this.regions.get("@search") ?? null;
    throw new Error(`the card used an unexpected selector: ${selector}`);
  }
  addEventListener(type: string, fn: Listener): void {
    const list = this.listeners.get(type) ?? [];
    list.push(fn);
    this.listeners.set(type, list);
  }
  dispatch(type: string, target: unknown): void {
    for (const fn of this.listeners.get(type) ?? []) fn({ type, target });
  }
  region(name: string): string {
    return this.regions.get(name)?.innerHTML ?? "";
  }
  writesOf(name: string): number {
    return this.regions.get(name)?.writes ?? -1;
  }
}

export class FakeHTMLElement {
  shadowRoot: FakeRoot | null = null;
  attachShadow(init: { mode: string }): FakeRoot {
    if (init.mode !== "open") throw new Error("the card must use an open shadow root");
    if (this.shadowRoot) throw new Error("attachShadow called twice");
    this.shadowRoot = new FakeRoot();
    return this.shadowRoot;
  }
}

export interface FakeEl {
  tag: string;
  attrs: Map<string, string>;
  value?: unknown;
  getAttribute(name: string): string | null;
  closest(selector: string): FakeEl | null;
}

function unescapeHtml(s: string): string {
  return s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

export function makeEl(tag: string, attrs: Record<string, string> | Map<string, string>): FakeEl {
  const map = attrs instanceof Map ? attrs : new Map(Object.entries(attrs));
  const el: FakeEl = {
    tag,
    attrs: map,
    getAttribute: (name) => (map.has(name) ? (map.get(name) ?? "") : null),
    closest: (selector) => {
      if (selector !== "[data-action]") throw new Error(`unexpected closest() selector ${selector}`);
      return map.has("data-action") ? el : null;
    },
  };
  return el;
}

/** Every <button> / <input> start tag in `html`, as an element the card's handlers can be given as an event target. */
export function elementsIn(html: string): FakeEl[] {
  const out: FakeEl[] = [];
  for (const m of html.matchAll(/<(button|input)\b([^>]*)>/g)) {
    const attrs = new Map<string, string>();
    for (const a of (m[2] ?? "").matchAll(/([a-z][a-z-]*)(?:="([^"]*)")?/g)) attrs.set(a[1] ?? "", unescapeHtml(a[2] ?? ""));
    out.push(makeEl(m[1] ?? "", attrs));
  }
  return out;
}

export interface Recorder {
  /** every property read on the hass object */
  reads: string[];
  /** every forbidden thing that happened: service / websocket / API calls, writes to hass or its states, network, timers */
  calls: string[];
}

/** A Home Assistant object that records every property read and every call; its states map refuses (and records) writes. */
export function recordingHass(states: StatesLike, rec: Recorder): unknown {
  const spy = (name: string) => (..._args: unknown[]) => {
    rec.calls.push(name);
    return Promise.resolve(undefined);
  };
  const guard = <T extends object>(obj: T, label: string): T =>
    new Proxy(obj, {
      set(_t, p) {
        rec.calls.push(`${label} set ${String(p)}`);
        return false;
      },
      deleteProperty(_t, p) {
        rec.calls.push(`${label} delete ${String(p)}`);
        return false;
      },
      defineProperty(_t, p) {
        rec.calls.push(`${label} define ${String(p)}`);
        return false;
      },
    });
  const guardedStates: StatesLike = {};
  for (const [k, v] of Object.entries(states)) guardedStates[k] = v ? guard({ ...v, attributes: guard({ ...(v.attributes ?? {}) }, `${k}.attributes`) }, k) : v;
  const real = {
    states: guard(guardedStates, "states"),
    callService: spy("hass.callService"),
    callWS: spy("hass.callWS"),
    callApi: spy("hass.callApi"),
    fetchWithAuth: spy("hass.fetchWithAuth"),
    sendMessage: spy("hass.sendMessage"),
    connection: {
      sendMessage: spy("connection.sendMessage"),
      sendMessagePromise: spy("connection.sendMessagePromise"),
      subscribeMessage: spy("connection.subscribeMessage"),
      subscribeEvents: spy("connection.subscribeEvents"),
    },
    user: { is_admin: true, name: "Owner" },
  };
  return new Proxy(real, {
    get(t, p, r) {
      rec.reads.push(String(p));
      return Reflect.get(t, p, r);
    },
    has(t, p) {
      rec.reads.push(`has ${String(p)}`);
      return Reflect.has(t, p);
    },
    ownKeys(t) {
      rec.reads.push("ownKeys");
      return Reflect.ownKeys(t);
    },
    set(_t, p) {
      rec.calls.push(`hass set ${String(p)}`);
      return false;
    },
  });
}

export interface Shim {
  defined: Map<string, unknown>;
  window: { customCards?: Array<Record<string, unknown>> };
  rec: Recorder;
  /** Run `fn` with setTimeout / setInterval / requestAnimationFrame / queueMicrotask recording into rec.calls. */
  noTimers<T>(fn: () => T): T;
}

export function installDomShim(): Shim {
  const g = globalThis as unknown as Record<string, unknown>;
  const defined = new Map<string, unknown>();
  const rec: Recorder = { reads: [], calls: [] };
  const win: { customCards?: Array<Record<string, unknown>> } = {};
  g.HTMLElement = FakeHTMLElement;
  g.customElements = {
    define(name: string, ctor: unknown) {
      if (defined.has(name)) throw new Error(`${name} defined twice`);
      defined.set(name, ctor);
    },
    get(name: string) {
      return defined.get(name);
    },
  };
  g.window = win;
  g.fetch = (..._a: unknown[]) => {
    rec.calls.push("fetch");
    return Promise.reject(new Error("no network in tests"));
  };
  for (const name of ["XMLHttpRequest", "WebSocket", "EventSource", "BroadcastChannel", "Worker"]) {
    g[name] = class {
      constructor() {
        rec.calls.push(name);
      }
    };
  }
  return {
    defined,
    window: win,
    rec,
    noTimers<T>(fn: () => T): T {
      const saved = {
        setTimeout: g.setTimeout,
        setInterval: g.setInterval,
        requestAnimationFrame: g.requestAnimationFrame,
        queueMicrotask: g.queueMicrotask,
      };
      for (const k of Object.keys(saved)) {
        g[k] = () => {
          rec.calls.push(k);
          return 0;
        };
      }
      try {
        return fn();
      } finally {
        Object.assign(g, saved);
      }
    },
  };
}
