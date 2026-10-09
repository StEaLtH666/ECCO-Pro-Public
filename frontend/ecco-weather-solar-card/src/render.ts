// HTML / SVG string rendering. Pure functions of their arguments; every value that came from Home Assistant is escaped.
// The only interactive element is the Today / Tomorrow chart switch (data-action="chart-day"), which changes local view
// state only.
import { HOUR_MS, compass, condition, fmtAge, fmtDuration, fmtKwh, fmtNum, fmtTime, fmtWeekday, hasRainProbability, parseTime, toNum } from "./model.ts";
import type { AccuracyView } from "./model.ts";
import type { ForecastEntry, FreshnessView, HourPoint, Layout, Num, SolarTotals, SunView } from "./types.ts";

export function esc(v: unknown): string {
  return String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const icon = (name: string, cls = ""): string => `<ha-icon class="${esc(cls)}" icon="${esc(name)}"></ha-icon>`;
const muted = (text: string): string => `<span class="na">${esc(text)}</span>`;
const unit = (v: unknown, fallback: string): string => (typeof v === "string" && v.length <= 12 ? v : fallback);

/** The card's static frame with one empty region per section. `full` is the dedicated view; the two compact layouts hold
 *  only the regions their sections need (strip: totals / curve / fresh; next days: fresh / daily). */
export function renderShell(title: string, styles: string, layout: Layout = "full"): string {
  if (layout === "solar_strip") {
    return `<style>${styles}</style><ha-card><div class="wrap strip"><div class="srow">` +
      (title ? `<div class="stitle">${esc(title)}</div>` : "") +
      `<div class="stotals" data-region="totals"></div>` +
      `<div class="scurve" data-region="curve"></div>` +
      `<div class="fresh sfresh" data-region="fresh"></div>` +
      `</div></div></ha-card>`;
  }
  if (layout === "daily_compact") {
    return `<style>${styles}</style><ha-card><div class="wrap compact">` +
      `<div class="head">${title ? `<div class="title">${esc(title)}</div>` : ""}<div class="fresh" data-region="fresh"></div></div>` +
      `<section class="days" data-region="daily"></section>` +
      `</div></ha-card>`;
  }
  return `<style>${styles}</style><ha-card><div class="wrap">` +
    `<div class="head"><div class="title">${esc(title)}</div><div class="fresh" data-region="fresh"></div></div>` +
    `<div class="grid top"><section class="panel" data-region="now"></section><section class="panel" data-region="sun"></section></div>` +
    `<section class="panel" data-region="solar"></section>` +
    `<section class="panel" data-region="chart"></section>` +
    `<section class="panel" data-region="hourly"></section>` +
    `<section class="panel" data-region="daily"></section>` +
    `<section class="panel" data-region="accuracy"></section>` +
    `<section class="panel" data-region="insights"></section>` +
    `<div class="foot">Read-only: this card displays forecasts and sends no command to Home Assistant or the inverter.</div>` +
    `</div></ha-card>`;
}

export function renderFreshness(items: FreshnessView[]): string {
  return items.map((f) => {
    const cls = f.status === "fresh" ? "ok" : f.status === "stale" ? "warn" : "unk";
    const text = f.status === "unknown" ? `${f.label}: update time unknown` : `${f.label}: ${fmtAge(f.ageMs)}${f.status === "stale" ? " (stale)" : ""}`;
    return `<span class="chip ${cls}" title="${esc(f.detail)}">${esc(text)}</span>`;
  }).join("");
}

export interface CurrentWeather {
  found: boolean;
  entityId: string;
  condition: unknown;
  temperature: Num;
  temperatureUnit: string;
  humidity: Num;
  windSpeed: Num;
  windUnit: string;
  windBearing: unknown;
  cloud: Num;
  pressure: Num;
  pressureUnit: string;
  rainThisHour: Num;
  rainUnit: string;
  uv: Num;
}

export function renderNow(w: CurrentWeather): string {
  if (!w.found) return `<h3>Now</h3>${muted(`Weather entity ${w.entityId} not found or unavailable.`)}`;
  const c = condition(w.condition);
  const t = w.temperature === null ? "--" : `${w.temperature.toFixed(1)} ${esc(w.temperatureUnit)}`;
  const rows: Array<[string, string]> = [
    ["Humidity", w.humidity === null ? "--" : `${Math.round(w.humidity)} %`],
    ["Wind", w.windSpeed === null ? "--" : `${w.windSpeed.toFixed(0)} ${esc(w.windUnit)} ${esc(compass(w.windBearing))}`],
    ["Cloud cover", w.cloud === null ? "--" : `${Math.round(w.cloud)} %`],
    ["Rain this hour", w.rainThisHour === null ? "--" : `${w.rainThisHour.toFixed(1)} ${esc(w.rainUnit)}`],
    ["Pressure", w.pressure === null ? "--" : `${w.pressure.toFixed(0)} ${esc(w.pressureUnit)}`],
    ["UV index", w.uv === null ? "--" : w.uv.toFixed(1)],
  ];
  return `<h3>Now</h3><div class="now">${icon(c.icon, "big")}<div><div class="temp">${t}</div><div class="cond">${esc(c.label)}</div></div></div>` +
    `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

export function renderSun(s: SunView, now: number, tz: string): string {
  if (!s.available) return `<h3>Sun</h3>${muted("Sun times unavailable (no Sun integration data and no location).")}`;
  const mark = (src: string): string => (src === "calculated" ? ` <span class="calc" title="Already passed today: calculated from the Home Assistant location (the Sun integration exposes only the next event).">calc</span>` : "");
  let remaining: string;
  if (s.phase === "day") remaining = fmtDuration(s.remainingMs);
  else if (s.phase === "after_sunset") remaining = `0 min (sun has set${s.nextSunrise !== null ? `; rises ${esc(fmtTime(s.nextSunrise, tz))}` : ""})`;
  else if (s.phase === "before_sunrise") remaining = `${fmtDuration(s.remainingMs)} (sun rises in ${fmtDuration(s.sunrise !== null ? s.sunrise - now : null)})`;
  else remaining = "--";
  const rows: Array<[string, string]> = [
    ["Sunrise", `${esc(fmtTime(s.sunrise, tz))}${mark(s.sunriseSource)}`],
    ["Sunset", `${esc(fmtTime(s.sunset, tz))}${mark(s.sunsetSource)}`],
    ["Daylight", esc(fmtDuration(s.daylightMs))],
    ["Daylight left", remaining],
  ];
  const state = s.aboveHorizon === null ? "" : `<div class="sub">${s.aboveHorizon ? "Sun above the horizon" : "Sun below the horizon"}</div>`;
  return `<h3>Sun</h3>${icon(s.aboveHorizon ? "mdi:white-balance-sunny" : "mdi:weather-sunset", "mid")}${state}` +
    `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

export interface SolarPanel {
  today: SolarTotals;
  remaining: SolarTotals;
  tomorrow: SolarTotals;
  pvToday: Num;
  pvNow: Num;
}

/** What the ECCO blend was built from, as the blend sensor itself reports it. */
const basisText = (t: SolarTotals): string =>
  t.basis === "both" ? "50/50 blend" : t.basis === "solcast" ? "Solcast only" : t.basis === "forecast_solar" ? "Forecast.Solar only" : "unavailable";

export function renderSolar(p: SolarPanel): string {
  const col = (label: string, t: SolarTotals): string => {
    const basis = basisText(t);
    return `<div class="tot"><div class="lbl">${esc(label)}</div><div class="big blend">${esc(fmtKwh(t.blend))}</div>` +
      `<div class="basis ${t.basis === "both" ? "" : "warn"}">${esc(basis)}</div>` +
      `<div class="src"><span class="sc">Solcast ${esc(fmtKwh(t.solcast))}</span><span class="fs">Forecast.Solar ${esc(fmtKwh(t.forecastSolar))}</span></div></div>`;
  };
  return `<h3>Solar forecast <span class="sub">ECCO blend</span></h3><div class="grid three">` +
    `${col("Today", p.today)}${col("Remaining today", p.remaining)}${col("Tomorrow", p.tomorrow)}</div>` +
    `<div class="sub">Generated today ${esc(fmtKwh(p.pvToday))} - PV now ${p.pvNow === null ? "--" : `${esc(Math.round(p.pvNow))} W`}</div>`;
}

export interface StripTotals {
  today: SolarTotals;
  remaining: SolarTotals;
  tomorrow: SolarTotals;
  pvToday: Num;
}

/** The `solar_strip` totals: Today / Remaining today / Tomorrow from the same blend sensors (and their source attributes)
 *  as the full layout, one 10 px source line each; "generated so far" beneath Remaining. Unknown is "--", never 0. */
export function renderSolarStrip(p: StripTotals): string {
  const col = (label: string, t: SolarTotals, extra: string): string =>
    `<div class="stot"><div class="lbl">${esc(label)}</div><div class="big blend">${esc(fmtKwh(t.blend))}</div>` +
    `<div class="srcl"><span class="sc">Solcast ${esc(fmtNum(t.solcast))}</span> · <span class="fs">Forecast.Solar ${esc(fmtNum(t.forecastSolar))}</span>` +
    ` · <span class="basis ${t.basis === "both" ? "" : "warn"}">${esc(basisText(t))}</span></div>${extra}</div>`;
  return col("Today", p.today, "") +
    col("Remaining today", p.remaining, `<div class="gen">generated so far ${esc(fmtKwh(p.pvToday))}</div>`) +
    col("Tomorrow", p.tomorrow, "");
}

export interface StripChartInput {
  /** today's points (Solcast estimate and actual PV per local hour) */
  points: HourPoint[];
  now: number;
  tz: string;
  solcastNote: string | null;
  actualNote: string | null;
  sunrise: number | null;
  sunset: number | null;
}

/** The `solar_strip` sparkline (220 x 48 drawing units, stretched to its cell): today's Solcast profile as an area and
 *  line, actual PV per completed hour as bars, a "now" marker and sunrise / sunset ticks. Without Solcast's hourly detail
 *  the cell shows the plain message instead; a curve is never made up. */
export function renderStripChart(c: StripChartInput): string {
  if (c.solcastNote) return muted(c.solcastNote);
  const pts = c.points;
  const has = (p: HourPoint): boolean => (p.solcast !== null && p.solcast > 0) || (p.actual !== null && p.actual > 0);
  const firstIdx = pts.findIndex(has);
  if (firstIdx < 0) return muted("No hourly solar data for this day yet.");
  let lastIdx = pts.length - 1;
  while (lastIdx > firstIdx && !has(pts[lastIdx]!)) lastIdx--;
  const view = pts.slice(Math.max(0, firstIdx - 1), Math.min(pts.length - 1, lastIdx + 1) + 1);
  let maxV = 0;
  for (const p of view) maxV = Math.max(maxV, p.solcast ?? 0, p.actual ?? 0);
  const yMax = niceAxis(maxV * 1.05).max;
  const W = 220, H = 48, T = 3, B = 5;
  const ph = H - T - B;
  const slot = W / view.length;
  const base = view[0]!.start;
  const span = view.length * HOUR_MS;
  const xt = (t: number): number => ((t - base) / HOUR_MS) * slot;
  const y = (v: number): number => T + ph - (Math.min(v, yMax) / yMax) * ph;
  const parts: string[] = [];
  const line = view.filter((p) => p.solcast !== null);
  if (line.length) {
    const coords = line.map((p) => `${(xt(p.start) + slot / 2).toFixed(1)},${y(p.solcast as number).toFixed(1)}`);
    const floor = (T + ph).toFixed(1);
    parts.push(`<polygon class="sc-a" points="${(xt(line[0]!.start) + slot / 2).toFixed(1)},${floor} ${coords.join(" ")} ${(xt(line[line.length - 1]!.start) + slot / 2).toFixed(1)},${floor}"/>`);
  }
  for (const p of view) {
    if (p.actual === null) continue;
    const bw = slot * 0.56;
    const cx = xt(p.start) + slot / 2;
    parts.push(`<rect class="act" x="${(cx - bw / 2).toFixed(1)}" y="${y(p.actual).toFixed(1)}" width="${bw.toFixed(1)}" height="${(T + ph - y(p.actual)).toFixed(1)}">` +
      `<title>${esc(fmtTime(p.start, c.tz))} actual ${esc(p.actual.toFixed(2))} kWh</title></rect>`);
  }
  if (line.length) {
    parts.push(`<polyline class="sc-l" points="${line.map((p) => `${(xt(p.start) + slot / 2).toFixed(1)},${y(p.solcast as number).toFixed(1)}`).join(" ")}"/>`);
  }
  for (const [t, what] of [[c.sunrise, "sunrise"], [c.sunset, "sunset"]] as Array<[number | null, string]>) {
    if (t === null || t < base || t > base + span) continue;
    parts.push(`<line class="sun-t" x1="${xt(t).toFixed(1)}" x2="${xt(t).toFixed(1)}" y1="${H - B}" y2="${H}"><title>${esc(what)} ${esc(fmtTime(t, c.tz))}</title></line>`);
  }
  let nowLabel = "";
  if (c.now >= base && c.now < base + span) {
    const nx = xt(c.now);
    parts.push(`<line class="nowl" x1="${nx.toFixed(1)}" x2="${nx.toFixed(1)}" y1="${T}" y2="${T + ph}"><title>now</title></line>`);
    const pct = (nx / W) * 100;
    nowLabel = `<span class="nowlbl${pct > 70 ? " l" : ""}" style="left:${pct.toFixed(1)}%">now ${esc(fmtTime(c.now, c.tz))}</span>`;
  }
  const aria = `Hourly solar today: Solcast estimate${view.some((p) => p.actual !== null) ? " and actual generation" : ""}`;
  return `<div class="spark-box"${c.actualNote ? ` title="${esc(c.actualNote)}"` : ""}>` +
    `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}" preserveAspectRatio="none">${parts.join("")}</svg>${nowLabel}</div>`;
}

export interface ChartInput {
  day: "today" | "tomorrow";
  points: HourPoint[];
  now: number;
  tz: string;
  solcastNote: string | null;
  actualNote: string | null;
  fsCurrentHour: Num;
  fsNextHour: Num;
  sunrise: number | null;
  sunset: number | null;
}

/** A round tick step (1, 2, 2.5 or 5 x 10^n) giving about four intervals up to `v`, and the axis maximum it implies. */
export function niceAxis(v: number): { step: number; max: number } {
  const target = Math.max(v, 0.4) / 4;
  const mag = 10 ** Math.floor(Math.log10(target));
  let step = 10 * mag;
  for (const s of [1, 2, 2.5, 5]) {
    if (s * mag >= target) {
      step = s * mag;
      break;
    }
  }
  return { step, max: step * Math.max(1, Math.ceil(Math.max(v, 0.4) / step - 1e-9)) };
}

const tickLabel = (v: number): string => String(Math.round(v * 100) / 100);

export function renderChart(c: ChartInput): string {
  const tabs = `<div class="tabs" role="tablist">` +
    (["today", "tomorrow"] as const).map((d) => `<button type="button" role="tab" data-action="chart-day" data-day="${d}" aria-selected="${c.day === d}" class="${c.day === d ? "on" : ""}">${d === "today" ? "Today" : "Tomorrow"}</button>`).join("") +
    `</div>`;
  const head = `<h3>Hourly solar <span class="sub">kWh per hour</span></h3>${tabs}`;
  const pts = c.points;
  const has = (p: HourPoint): boolean => (p.solcast !== null && p.solcast > 0) || (p.actual !== null && p.actual > 0);
  const firstIdx = pts.findIndex(has);
  if (firstIdx < 0) {
    return `${head}<div>${muted(c.solcastNote ?? "No hourly solar data for this day yet.")}</div>${c.actualNote ? `<div class="note">${esc(c.actualNote)}</div>` : ""}`;
  }
  let lastIdx = pts.length - 1;
  while (lastIdx > firstIdx && !has(pts[lastIdx]!)) lastIdx--;
  const lo = Math.max(0, firstIdx - 1);
  const hi = Math.min(pts.length - 1, lastIdx + 1);
  const view = pts.slice(lo, hi + 1);
  let maxV = 0;
  for (const p of view) maxV = Math.max(maxV, p.solcast ?? 0, p.p90 ?? 0, p.actual ?? 0);
  const axis = niceAxis(maxV * 1.05);
  const yMax = axis.max;
  const W = 720, H = 250, L = 42, R = 10, T = 12, B = 58;
  const pw = W - L - R, ph = H - T - B;
  const slot = pw / view.length;
  const x = (i: number): number => L + i * slot;
  const y = (v: number): number => T + ph - (Math.min(v, yMax) / yMax) * ph;
  const parts: string[] = [];
  for (let k = 0; k * axis.step <= yMax + 1e-9; k++) {
    const v = k * axis.step;
    parts.push(`<line class="grid-l" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>` +
      `<text class="ax" x="${L - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${esc(tickLabel(v))}</text>`);
  }
  // P10-P90 band and the Solcast estimate line (hour centres)
  const band = view.map((p, i) => ({ i, p })).filter((o) => o.p.p10 !== null && o.p.p90 !== null);
  if (band.length >= 2) {
    const top = band.map((o) => `${(x(o.i) + slot / 2).toFixed(1)},${y(o.p.p90 as number).toFixed(1)}`);
    const bot = band.slice().reverse().map((o) => `${(x(o.i) + slot / 2).toFixed(1)},${y(o.p.p10 as number).toFixed(1)}`);
    parts.push(`<polygon class="band" points="${top.concat(bot).join(" ")}"><title>Solcast P10-P90 range</title></polygon>`);
  }
  view.forEach((p, i) => {
    const cx = x(i) + slot / 2;
    const label = `${fmtTime(p.start, c.tz)}`;
    if (p.actual !== null) {
      const bw = slot * 0.56;
      parts.push(`<rect class="act" x="${(cx - bw / 2).toFixed(1)}" y="${y(p.actual).toFixed(1)}" width="${bw.toFixed(1)}" height="${(T + ph - y(p.actual)).toFixed(1)}" rx="2">` +
        `<title>${esc(label)} actual ${esc(p.actual.toFixed(2))} kWh</title></rect>`);
    }
    if (p.cloud !== null) {
      const op = Math.max(0.06, Math.min(1, p.cloud / 100)).toFixed(2);
      parts.push(`<rect class="cloud" x="${(x(i) + 1).toFixed(1)}" y="${T + ph + 22}" width="${(slot - 2).toFixed(1)}" height="9" style="opacity:${op}">` +
        `<title>${esc(label)} cloud ${esc(Math.round(p.cloud))}%</title></rect>`);
    }
    if (p.rain !== null && p.rain > 0) {
      const rh = Math.min(12, 3 + p.rain * 4);
      parts.push(`<rect class="rain" x="${(cx - 3).toFixed(1)}" y="${(T + ph + 46 - rh).toFixed(1)}" width="6" height="${rh.toFixed(1)}" rx="1">` +
        `<title>${esc(label)} rain ${esc(p.rain.toFixed(1))} mm${p.rainProbability !== null ? ` (${esc(Math.round(p.rainProbability))}%)` : ""}</title></rect>`);
    }
    if (i % (view.length > 16 ? 3 : 2) === 0) parts.push(`<text class="ax" x="${cx.toFixed(1)}" y="${T + ph + 16}" text-anchor="middle">${esc(label.slice(0, 2))}</text>`);
  });
  const line = view.map((p, i) => ({ i, p })).filter((o) => o.p.solcast !== null);
  if (line.length) {
    parts.push(`<polyline class="sc-l" points="${line.map((o) => `${(x(o.i) + slot / 2).toFixed(1)},${y(o.p.solcast as number).toFixed(1)}`).join(" ")}"/>`);
    for (const o of line) {
      parts.push(`<circle class="sc-d" cx="${(x(o.i) + slot / 2).toFixed(1)}" cy="${y(o.p.solcast as number).toFixed(1)}" r="2.6">` +
        `<title>${esc(fmtTime(o.p.start, c.tz))} Solcast ${esc((o.p.solcast as number).toFixed(2))} kWh${o.p.p10 !== null && o.p.p90 !== null ? ` (P10 ${esc(o.p.p10.toFixed(2))} - P90 ${esc(o.p.p90.toFixed(2))})` : ""}</title></circle>`);
    }
  }
  if (c.day === "today") {
    const i = view.findIndex((p) => c.now >= p.start && c.now < p.start + HOUR_MS);
    if (i >= 0) {
      const nx = x(i) + ((c.now - view[i]!.start) / HOUR_MS) * slot;
      parts.push(`<line class="nowl" x1="${nx.toFixed(1)}" x2="${nx.toFixed(1)}" y1="${T}" y2="${T + ph}"><title>now</title></line>`);
      const fs: Array<[number, Num, string]> = [[i, c.fsCurrentHour, "this hour"], [i + 1, c.fsNextHour, "next hour"]];
      for (const [j, v, what] of fs) {
        if (v === null || j >= view.length) continue;
        const fx = x(j) + slot / 2;
        const fy = y(v);
        parts.push(`<path class="fs-m" d="M${fx.toFixed(1)} ${(fy - 5).toFixed(1)} L${(fx + 5).toFixed(1)} ${fy.toFixed(1)} L${fx.toFixed(1)} ${(fy + 5).toFixed(1)} L${(fx - 5).toFixed(1)} ${fy.toFixed(1)} Z">` +
          `<title>Forecast.Solar ${esc(what)} ${esc(v.toFixed(2))} kWh</title></path>`);
      }
    }
  }
  parts.push(`<text class="ax axl" x="${L}" y="${T + ph + 30}" text-anchor="end">cloud</text><text class="ax axl" x="${L}" y="${T + ph + 45}" text-anchor="end">rain</text>`);
  const aria = `Hourly solar for ${c.day}: Solcast estimate${view.some((p) => p.actual !== null) ? " and actual generation" : ""}`;
  const legend = `<div class="legend"><span class="lg act">Actual PV</span><span class="lg sc">Solcast</span><span class="lg band">Solcast P10-P90</span>` +
    `${c.day === "today" ? `<span class="lg fs">Forecast.Solar this / next hour</span>` : ""}<span class="lg cloud">Cloud cover</span><span class="lg rain">Rain</span></div>`;
  const notes = [c.solcastNote, c.actualNote, "Hourly profile: Solcast. Forecast.Solar and the ECCO blend are daily totals in Home Assistant (no hourly series)."]
    .filter((n): n is string => !!n).map((n) => `<div class="note">${esc(n)}</div>`).join("");
  return `${head}<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}" preserveAspectRatio="xMidYMid meet">${parts.join("")}</svg>${legend}${notes}`;
}

export interface WeatherListInput {
  entries: ForecastEntry[];
  tz: string;
  error: string | null;
  loading: boolean;
  tempUnit: string;
  windUnit: string;
  rainUnit: string;
}

function forecastState(i: WeatherListInput, what: string): string | null {
  if (i.error) return muted(`${what} unavailable: ${i.error}`);
  if (i.loading) return muted(`Loading ${what.toLowerCase()}...`);
  if (!i.entries.length) return muted(`${what} unavailable.`);
  return null;
}

export function renderHourly(i: WeatherListInput): string {
  const head = `<h3>Hourly weather</h3>`;
  const st = forecastState(i, "Hourly forecast");
  if (st) return head + st;
  const prob = hasRainProbability(i.entries);
  const cells = i.entries.map((f) => {
    const t = parseTime(f.datetime);
    const c = condition(f.condition);
    const temp = toNum(f.temperature);
    const rain = toNum(f.precipitation);
    const pp = toNum(f.precipitation_probability);
    const cl = toNum(f.cloud_coverage);
    return `<div class="hc"><div class="t">${esc(t === null ? "--" : fmtTime(t, i.tz))}</div>${icon(c.icon)}<div class="v" title="${esc(c.label)}">${esc(temp === null ? "--" : `${temp.toFixed(0)}${i.tempUnit}`)}</div>` +
      `<div class="r">${esc(rain === null ? "--" : `${rain.toFixed(1)} ${i.rainUnit}`)}${prob ? `<br>${esc(pp === null ? "--" : `${Math.round(pp)}%`)}` : ""}</div>` +
      `<div class="c">${esc(cl === null ? "--" : `${Math.round(cl)}%`)} cloud</div><div class="w">${esc(fmtNum(toNum(f.wind_speed), 0))} ${esc(compass(f.wind_bearing))}</div></div>`;
  }).join("");
  const note = prob ? "" : `<div class="note">Rain shows forecast amount; this weather source provides no rain probability.</div>`;
  return `${head}<div class="hours">${cells}</div>${note}`;
}

export function renderDaily(i: WeatherListInput): string {
  const head = `<h3>Next days</h3>`;
  const st = forecastState(i, "Daily forecast");
  if (st) return head + st;
  const prob = hasRainProbability(i.entries);
  const rows = i.entries.map((f) => {
    const t = parseTime(f.datetime);
    const c = condition(f.condition);
    const hiT = toNum(f.temperature);
    const loT = toNum(f.templow);
    const rain = toNum(f.precipitation);
    const pp = toNum(f.precipitation_probability);
    return `<div class="dr"><span class="d">${esc(t === null ? "--" : fmtWeekday(t, i.tz))}</span>${icon(c.icon)}<span class="cl">${esc(c.label)}</span>` +
      `<span class="hl">${esc(hiT === null ? "--" : hiT.toFixed(0))}${esc(i.tempUnit)} / ${esc(loT === null ? "--" : loT.toFixed(0))}${esc(i.tempUnit)}</span>` +
      `<span class="rn">${esc(rain === null ? "--" : `${rain.toFixed(1)} ${i.rainUnit}`)}${prob ? ` ${esc(pp === null ? "--" : `${Math.round(pp)}%`)}` : ""}</span>` +
      `<span class="wd">${esc(fmtNum(toNum(f.wind_speed), 0))} ${esc(i.windUnit)} ${esc(compass(f.wind_bearing))}</span></div>`;
  }).join("");
  return `${head}<div class="days">${rows}</div>`;
}

/** The `daily_compact` rows: one per entry (never padded), weekday / condition / high and low / rain amount, and the
 *  rain-probability column only when the weather source supplies one. Loading / error / empty states as the full list. */
export function renderDailyCompact(i: WeatherListInput): string {
  const st = forecastState(i, "Daily forecast");
  if (st) return st;
  const prob = hasRainProbability(i.entries);
  // Whole degrees, "--" for unknown; a value in (-0.5, 0) is "0", never "-0".
  const deg = (v: Num): string => {
    if (v === null) return "--";
    const s = v.toFixed(0);
    return s === "-0" ? "0" : s;
  };
  return i.entries.map((f) => {
    const t = parseTime(f.datetime);
    const c = condition(f.condition);
    const hiT = toNum(f.temperature);
    const loT = toNum(f.templow);
    const rain = toNum(f.precipitation);
    const pp = toNum(f.precipitation_probability);
    return `<div class="dc${prob ? " p" : ""}"><span class="d">${esc(t === null ? "--" : fmtWeekday(t, i.tz))}</span>${icon(c.icon)}<span class="cl">${esc(c.label)}</span>` +
      `<span class="hl" title="${esc(i.tempUnit)}">${esc(deg(hiT))}° / ${esc(deg(loT))}°</span>` +
      `<span class="rn">${esc(rain === null ? "--" : `${rain.toFixed(1)} ${i.rainUnit}`)}</span>` +
      `${prob ? `<span class="pp">${esc(pp === null ? "--" : `${Math.round(pp)}%`)}</span>` : ""}</div>`;
  }).join("");
}

export function renderAccuracy(a: AccuracyView, show: boolean): string {
  if (!show) return "";
  const head = `<h3>Forecast accuracy <span class="sub">ECCO day-ahead scorecard</span></h3>`;
  if (!a.available) return `${head}${muted("No scored days yet (the scorecard sensors are unavailable).")}`;
  const row = (r: AccuracyView["rows"][number]): string =>
    `<tr${a.bestSource === r.source ? ' class="best"' : ""}><th scope="row">${esc(r.source)}</th><td>${esc(fmtKwh(r.mae))}</td>` +
    `<td>${esc(r.error === null ? "--" : `${r.error > 0 ? "+" : ""}${r.error.toFixed(1)} kWh`)}${r.errorPct === null ? "" : ` <span class="sub">(${esc(r.errorPct > 0 ? "+" : "")}${esc(r.errorPct.toFixed(0))}%)</span>`}</td></tr>`;
  return `${head}<table class="acc"><thead><tr><th scope="col">Source</th><th scope="col">Mean abs. error</th><th scope="col">Last scored day${a.scoredDate ? ` (${esc(a.scoredDate)})` : ""}</th></tr></thead>` +
    `<tbody>${a.rows.map(row).join("")}</tbody></table>` +
    `<div class="note">${esc(a.learningDays === null ? "--" : Math.round(a.learningDays))} scored days. Most accurate so far: ${esc(a.bestSource ?? "--")}. Positive error = over-forecast. The blend weighting is fixed at 50/50; this table only reports.</div>`;
}

export function renderInsights(items: string[], show: boolean): string {
  if (!show) return "";
  const head = `<h3>ECCO insights</h3>`;
  if (!items.length) return `${head}${muted("Nothing notable in the current forecasts.")}`;
  return `${head}<ul class="ins">${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul><div class="note">Explanatory only: ECCO does not act on these notes.</div>`;
}

export { unit };
