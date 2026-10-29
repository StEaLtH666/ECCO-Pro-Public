// Scene selection for the approved V4 scene pack (ten fixed-perspective
// variants of the same house). Pure functions over the sun, the date and a
// Home Assistant weather condition; the rules are the pack's
// weather-scene-map.json, in order. The chosen scene is ambience only: no
// value shown on the card depends on it.

export const SCENE_FILES = {
  bright_summer_day: "00_bright_summer_day.png",
  soft_clear_day: "01_soft_clear_day.png",
  misty_morning: "02_misty_morning.png",
  golden_hour: "03_golden_hour.png",
  clear_night: "04_clear_night.png",
  rainy_day: "05_rainy_day.png",
  storm_night: "06_storm_night.png",
  winter_clear_day: "07_winter_clear_day.png",
  christmas_day: "08_christmas_day.png",
  christmas_night: "09_christmas_night.png",
} as const;

export type SceneKey = keyof typeof SCENE_FILES;
export const SCENE_KEYS = Object.keys(SCENE_FILES) as SceneKey[];

export interface SceneInputs {
  /** Local date (month 1-12, day 1-31). */
  month: number;
  day: number;
  /** Sun above the horizon (null when no sun entity). */
  sunUp: boolean | null;
  /** Sun elevation in degrees (null when unknown). */
  elevation: number | null;
  /** Sun currently rising (HA sun.sun `rising`); null when unknown. */
  rising: boolean | null;
  /** HA weather condition (e.g. "sunny", "clear-night", "fog"); undefined when no weather entity. */
  weather?: string;
  /** Local hour 0-23, used only when there is no sun entity. */
  hour: number;
}

/** 1 December to 3 January inclusive. */
export function inChristmasWindow(month: number, day: number): boolean {
  return month === 12 || (month === 1 && day <= 3);
}

function isNight(i: SceneInputs): boolean {
  if (i.sunUp !== null) return !i.sunUp;
  if (i.weather === "clear-night") return true;
  return i.hour < 7 || i.hour >= 19;
}

function isGoldenHour(i: SceneInputs): boolean {
  // Sun low (between -6 and 15 degrees) and setting. Without a rising flag, the
  // local hour decides whether it is evening.
  if (i.elevation === null || i.elevation < -6 || i.elevation > 15) return false;
  if (i.rising !== null) return !i.rising;
  return i.hour >= 15;
}

/** Applies the pack's rules in order and returns the scene key. */
export function selectScene(i: SceneInputs): SceneKey {
  const night = isNight(i);
  const w = (i.weather ?? "").toLowerCase();
  if (inChristmasWindow(i.month, i.day)) return night ? "christmas_night" : "christmas_day";
  if (!night && (w === "snowy" || w === "snowy-rainy")) return "winter_clear_day";
  if (night && (w === "lightning" || w === "lightning-rainy" || w === "exceptional")) return "storm_night";
  if (!night && (w === "rainy" || w === "pouring")) return "rainy_day";
  if (!night && w === "fog") return "misty_morning";
  if (isGoldenHour(i)) return "golden_hour";
  if (w === "clear-night" || (night && ["sunny", "partlycloudy", "cloudy", "windy", ""].includes(w))) return "clear_night";
  if (night) return "clear_night";
  if (w === "partlycloudy") return "soft_clear_day";
  if (w === "sunny" || w === "windy" || w === "clear") return "bright_summer_day";
  return "soft_clear_day";
}

/** The scene's image URL under the configured pack base (a local resource path, never a CDN). */
export function sceneUrl(base: string, key: SceneKey, overrides?: Partial<Record<SceneKey, string>>): string {
  const file = overrides?.[key] ?? SCENE_FILES[key];
  if (/^(\/|\.|[a-z]+:)/i.test(file) && overrides?.[key]) return file;
  return (base.endsWith("/") ? base : base + "/") + file;
}

/** Scenes that are night-time variants (pills keep the same style; used for the preview and tests). */
export function sceneIsNight(key: SceneKey): boolean {
  return key === "clear_night" || key === "storm_night" || key === "christmas_night";
}
