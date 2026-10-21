// A minimal, recording stand-in for the browser and Home Assistant pieces the card touches: HTMLElement with an open shadow
// root, customElements, window.customCards, network / timer APIs that must never be used, and a Home Assistant object whose
// connection records every websocket message. Install it BEFORE importing the card module (the class extends HTMLElement).
import type { StatesLike } from "../src/types.ts";

type Listener = (ev: unknown) => void;

export class FakeRegion {
  private _html = "";
  writes = 0;
  /** the region's hourly strip (`.hours`), a new element after every write, with its own scroll position */
  strip: { scrollLeft: number; getAttribute(name: string): string | null } | null = null;
  /** called on every write with the replaced HTML: like a browser, a rewrite drops focus from the elements it replaced */
  onWrite: (replaced: string) => void = () => undefined;
  get innerHTML(): string {
    return this._html;
  }
  set innerHTML(v: string) {
    const replaced = this._html;
    this._html = v;
    this.writes++;
    const tag = /<div class="hours"[^>]*>/.exec(v)?.[0];
    this.strip = tag === undefined ? null : { scrollLeft: 0, getAttribute: tagElement(tag).getAttribute };
    this.onWrite(replaced);
  }
  querySelector(selector: string) {
    if (selector !== ".hours") throw new Error(`the card used an unexpected region selector: ${selector}`);
    return this.strip;
  }
}

/** An element standing for the focused control: answers getAttribute from the attributes of its opening tag. */
function tagElement(tag: string) {
  const attrs = new Map([...tag.matchAll(/\s([a-z-]+)="([^"]*)"/g)].map((m) => [m[1] ?? "", m[2] ?? ""]));
  return { tag, getAttribute: (name: string) => (attrs.has(name) ? (attrs.get(name) ?? "") : null) };
}

export class FakeRoot {
  private _html = "";
  regions = new Map<string, FakeRegion>();
  listeners = new Map<string, Listener[]>();
  shellWrites = 0;
  /** every control the card moved keyboard focus to, as the selector it used, with the options it passed */
  focused: Array<{ selector: string; options: unknown }> = [];
  /** ShadowRoot.activeElement: the focused control inside the card, or null (focus elsewhere, or its element was replaced) */
  activeElement: ReturnType<typeof tagElement> | null = null;
  get innerHTML(): string {
    return this._html;
  }
  set innerHTML(v: string) {
    this._html = v;
    this.shellWrites++;
    this.activeElement = null;
    this.regions = new Map();
    for (const m of v.matchAll(/data-region="([a-z]+)"/g)) {
      const region = new FakeRegion();
      region.onWrite = (replaced) => {
        if (this.activeElement && replaced.includes(this.activeElement.tag)) this.activeElement = null;
      };
      this.regions.set(m[1] ?? "", region);
    }
  }
  querySelector(selector: string): FakeRegion | { focus(options?: unknown): void } | null {
    const m = /^\[data-region="([a-z]+)"\]$/.exec(selector);
    if (m) return this.regions.get(m[1] ?? "") ?? null;
    // A view control, found the way a browser would: an element whose opening tag carries the attribute(s).
    const a = /^\[data-action="([a-z-]+)"\](?:\[data-date="(\d{4}-\d{2}-\d{2})"\])?$/.exec(selector);
    const s = /^\[data-strip="(\d{4}-\d{2}-\d{2})"\]$/.exec(selector);
    if (a || s) {
      const want = a ? [`data-action="${a[1]}"`, ...(a[2] ? [`data-date="${a[2]}"`] : [])] : [`data-strip="${s![1]}"`];
      const html = [...this.regions.values()].map((r) => r.innerHTML).join("");
      const tag = [...html.matchAll(/<[a-z-]+\s[^>]*>/g)].map((t) => t[0]).find((t) => want.every((w) => t.includes(w)));
      return tag === undefined ? null : {
        focus: (options?: unknown) => {
          this.focused.push({ selector, options });
          this.activeElement = tagElement(tag);
        },
      };
    }
    throw new Error(`the card used an unexpected selector: ${selector}`);
  }
  /** Moves focus to the first control whose opening tag contains `fragment` (a user tabbing to it), or away from the card. */
  focusOn(fragment: string | null): void {
    const html = [...this.regions.values()].map((r) => r.innerHTML).join("");
    const tag = fragment === null ? undefined : [...html.matchAll(/<[a-z-]+\s[^>]*>/g)].map((t) => t[0]).find((t) => t.includes(fragment));
    if (fragment !== null && tag === undefined) throw new Error(`no control with ${fragment}`);
    this.activeElement = tag === undefined ? null : tagElement(tag);
  }
  addEventListener(type: string, fn: Listener): void {
    const list = this.listeners.get(type) ?? [];
    list.push(fn);
    this.listeners.set(type, list);
  }
  /** Delivers an event; `detail` is a click's count (1 a single click, 2 the second click of a double click, 0 keyboard). */
  dispatch(type: string, target: unknown, detail?: number): void {
    for (const fn of this.listeners.get(type) ?? []) fn(detail === undefined ? { type, target } : { type, target, detail });
  }
  region(name: string): string {
    return this.regions.get(name)?.innerHTML ?? "";
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

/** An element the click handler can be given: closest("[data-action]") returns itself when it carries data-action. */
export function makeEl(attrs: Record<string, string>) {
  const map = new Map(Object.entries(attrs));
  const el = {
    getAttribute: (name: string) => (map.has(name) ? (map.get(name) ?? "") : null),
    closest: (selector: string) => {
      if (selector !== "[data-action]") throw new Error(`unexpected closest() selector ${selector}`);
      return map.has("data-action") ? el : null;
    },
  };
  return el;
}

export interface Subscription {
  message: Record<string, unknown>;
  callback: (msg: unknown) => void;
  unsubscribed: boolean;
}

export interface Recorder {
  /** every property read on the hass object */
  reads: string[];
  /** every forbidden thing: service / API calls, writes to hass or its states, network, timers */
  calls: string[];
  /** every websocket message sent through connection.subscribeMessage / sendMessagePromise, in order */
  messages: Array<Record<string, unknown>>;
  subscriptions: Subscription[];
}

export interface FakeConnectionOptions {
  /** reject subscribeMessage with this error (per forecast_type, or for both) */
  subscribeError?: unknown;
  /** reject only the subscriptions of these forecast types, with the error given for each */
  subscribeErrorFor?: Record<string, unknown>;
  /** what sendMessagePromise resolves to (statistics); or an error to reject with */
  statistics?: unknown;
  statisticsError?: unknown;
}

export function fakeConnection(rec: Recorder, opts: FakeConnectionOptions = {}) {
  return {
    subscribeMessage(callback: (msg: unknown) => void, message: Record<string, unknown>) {
      rec.messages.push(message);
      if (opts.subscribeError !== undefined) return Promise.reject(opts.subscribeError);
      const kindError = opts.subscribeErrorFor?.[String(message.forecast_type)];
      if (kindError !== undefined) return Promise.reject(kindError);
      const sub: Subscription = { message, callback, unsubscribed: false };
      rec.subscriptions.push(sub);
      return Promise.resolve(() => {
        sub.unsubscribed = true;
        return Promise.resolve();
      });
    },
    sendMessagePromise(message: Record<string, unknown>) {
      rec.messages.push(message);
      if (opts.statisticsError !== undefined) return Promise.reject(opts.statisticsError);
      return Promise.resolve(opts.statistics ?? {});
    },
    sendMessage(..._a: unknown[]) {
      rec.calls.push("connection.sendMessage");
    },
    subscribeEvents(..._a: unknown[]) {
      rec.calls.push("connection.subscribeEvents");
      return Promise.resolve(() => undefined);
    },
  };
}

/** A Home Assistant object that records every property read and every forbidden call; its states map refuses writes. */
export function recordingHass(states: StatesLike, rec: Recorder, connection: unknown, config: unknown): unknown {
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
    });
  const guardedStates: StatesLike = {};
  for (const [k, v] of Object.entries(states)) guardedStates[k] = v ? guard({ ...v, attributes: guard({ ...(v.attributes ?? {}) }, `${k}.attributes`) }, k) : v;
  const real = {
    states: guard(guardedStates, "states"),
    config,
    connection,
    callService: spy("hass.callService"),
    callWS: spy("hass.callWS"),
    callApi: spy("hass.callApi"),
    fetchWithAuth: spy("hass.fetchWithAuth"),
    sendMessage: spy("hass.sendMessage"),
    user: { is_admin: true, name: "Owner" },
  };
  return new Proxy(real, {
    get(t, p, r) {
      rec.reads.push(String(p));
      return Reflect.get(t, p, r);
    },
    set(_t, p) {
      rec.calls.push(`hass set ${String(p)}`);
      return false;
    },
  });
}

export function newRecorder(): Recorder {
  return { reads: [], calls: [], messages: [], subscriptions: [] };
}

export interface Shim {
  defined: Map<string, unknown>;
  window: { customCards?: Array<Record<string, unknown>> };
  rec: Recorder;
  /** Run `fn` with setTimeout / setInterval / requestAnimationFrame recording into rec.calls. */
  noTimers<T>(fn: () => T): T;
}

export function installDomShim(): Shim {
  const g = globalThis as unknown as Record<string, unknown>;
  const defined = new Map<string, unknown>();
  const rec = newRecorder();
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
      const saved = { setTimeout: g.setTimeout, setInterval: g.setInterval, requestAnimationFrame: g.requestAnimationFrame };
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
