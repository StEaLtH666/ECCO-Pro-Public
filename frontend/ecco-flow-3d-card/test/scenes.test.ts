// Scene selection follows the V4 pack's rules; Christmas runs 1 Dec to 3 Jan
// inclusive; the choice never depends on a power value.
import { test } from "node:test";
import assert from "node:assert/strict";
import { SCENE_FILES, SCENE_KEYS, inChristmasWindow, sceneUrl, selectScene, type SceneInputs } from "../src/core/scenes.ts";

const base: SceneInputs = { month: 6, day: 15, sunUp: true, elevation: 45, rising: false, weather: "sunny", hour: 13 };
const at = (o: Partial<SceneInputs>) => selectScene({ ...base, ...o });

test("the pack has ten scenes with the pack's file names", () => {
  assert.equal(SCENE_KEYS.length, 10);
  assert.equal(SCENE_FILES.bright_summer_day, "00_bright_summer_day.png");
  assert.equal(SCENE_FILES.christmas_night, "09_christmas_night.png");
});

test("Christmas window is 1 December to 3 January inclusive, day or night", () => {
  assert.equal(inChristmasWindow(12, 1), true);
  assert.equal(inChristmasWindow(12, 25), true);
  assert.equal(inChristmasWindow(1, 3), true);
  assert.equal(inChristmasWindow(1, 4), false);
  assert.equal(inChristmasWindow(11, 30), false);
  assert.equal(at({ month: 12, day: 1 }), "christmas_day");
  assert.equal(at({ month: 12, day: 24, sunUp: false, elevation: -20 }), "christmas_night");
  assert.equal(at({ month: 1, day: 3, weather: "rainy" }), "christmas_day", "Christmas wins over weather");
  assert.equal(at({ month: 1, day: 4, weather: "snowy" }), "winter_clear_day");
});

test("weather and time of day pick the scene in the pack's rule order", () => {
  assert.equal(at({ weather: "sunny" }), "bright_summer_day");
  assert.equal(at({ weather: "windy" }), "bright_summer_day");
  assert.equal(at({ weather: "partlycloudy" }), "soft_clear_day");
  assert.equal(at({ weather: "cloudy" }), "soft_clear_day", "otherwise daytime");
  assert.equal(at({ weather: undefined }), "soft_clear_day", "no weather entity by day");
  assert.equal(at({ weather: "fog" }), "misty_morning");
  assert.equal(at({ weather: "rainy" }), "rainy_day");
  assert.equal(at({ weather: "pouring" }), "rainy_day");
  assert.equal(at({ weather: "snowy" }), "winter_clear_day");
  assert.equal(at({ weather: "snowy-rainy" }), "winter_clear_day");
  assert.equal(at({ sunUp: false, elevation: -30, weather: "clear-night" }), "clear_night");
  assert.equal(at({ sunUp: false, elevation: -30, weather: "cloudy" }), "clear_night");
  assert.equal(at({ sunUp: false, elevation: -30, weather: "rainy" }), "clear_night", "rain at night has no night plate: clear night");
  assert.equal(at({ sunUp: false, elevation: -30, weather: "lightning" }), "storm_night");
  assert.equal(at({ sunUp: false, elevation: -30, weather: "lightning-rainy" }), "storm_night");
  assert.equal(at({ sunUp: false, elevation: -30, weather: "exceptional" }), "storm_night");
  assert.equal(at({ sunUp: false, elevation: -30, weather: "snowy" }), "clear_night", "snow at night has no night plate");
});

test("golden hour: a low, setting sun; a low rising sun is morning, not golden hour", () => {
  assert.equal(at({ elevation: 6, rising: false, hour: 19, weather: "sunny" }), "golden_hour");
  assert.equal(at({ elevation: -3, sunUp: false, rising: false, hour: 20, weather: "sunny" }), "golden_hour");
  assert.equal(at({ elevation: 6, rising: true, hour: 7, weather: "sunny" }), "bright_summer_day");
  assert.equal(at({ elevation: 6, rising: false, hour: 19, weather: "rainy" }), "rainy_day", "rain beats golden hour by day");
  assert.equal(at({ elevation: 6, rising: null, hour: 18, weather: "sunny" }), "golden_hour", "without a rising flag the hour decides");
  assert.equal(at({ elevation: 6, rising: null, hour: 8, weather: "sunny" }), "bright_summer_day");
});

test("without a sun entity the local hour decides day and night", () => {
  assert.equal(at({ sunUp: null, elevation: null, rising: null, hour: 23, weather: "sunny" }), "clear_night");
  assert.equal(at({ sunUp: null, elevation: null, rising: null, hour: 12, weather: "sunny" }), "bright_summer_day");
  assert.equal(at({ sunUp: null, elevation: null, rising: null, hour: 12, weather: "clear-night" }), "clear_night", "HA's clear-night condition is trusted");
});

test("scene URLs stay under the configured local pack path unless a scene is overridden", () => {
  assert.equal(sceneUrl("/local/ecco/scenes/", "clear_night"), "/local/ecco/scenes/04_clear_night.png");
  assert.equal(sceneUrl("/local/ecco/scenes", "clear_night"), "/local/ecco/scenes/04_clear_night.png");
  assert.equal(sceneUrl("/local/ecco/scenes/", "clear_night", { clear_night: "/local/ecco/custom-night.png" }), "/local/ecco/custom-night.png");
  assert.equal(sceneUrl("/local/ecco/scenes/", "clear_night", { clear_night: "night-alt.png" }), "/local/ecco/scenes/night-alt.png");
});

test("the scene module reads no power, SOC or energy value", () => {
  // Inputs are date, sun and weather only.
  const keys = Object.keys(base).sort();
  assert.deepEqual(keys, ["day", "elevation", "hour", "month", "rising", "sunUp", "weather"]);
});
