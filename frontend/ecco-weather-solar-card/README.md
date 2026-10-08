# ECCO Weather & Solar card

A **read-only** Home Assistant Lovelace card that puts the weather and the solar forecast in one place:

- current weather, the hourly forecast and the next five days;
- sunrise, sunset, the length of the day and the daylight left;
- the ECCO blended solar forecast (today, remaining today, tomorrow) with its Solcast and Forecast.Solar inputs;
- an hourly solar chart: Solcast's profile with its P10-P90 range, actual PV generation, cloud cover and rain;
- how fresh each forecast is;
- the existing ECCO day-ahead accuracy scorecard;
- short explanatory notes.

It is a dependency-free web component (no Lit, no runtime library). The committed bundle is
`dist/ecco-weather-solar-card.js`.

## Read-only guarantee

The card cannot change anything in Home Assistant or on the inverter.

- The `hass` setter keeps three things only:
  - the states map;
  - the time zone and location from `hass.config`;
  - a reader (`src/reader.ts`) that can send exactly two read-only websocket messages.
- Neither the Home Assistant object nor its connection is kept.
- The two messages are:
  - `weather/subscribe_forecast`, the hourly and daily forecast of the weather entity;
  - `recorder/statistics_during_period`, the hourly `change` of one energy counter, for actual PV.
- There is no service or action call, no event subscription, no network request, no storage and no timer.
- The only interactive element is the Today / Tomorrow switch of the chart, which changes the card's own view.
- `test/static.test.ts` and `tools/tests/test_weather_solar_card.py` pin all of this over the source and the bundle.

## Where the data comes from

| Section | Source |
|---|---|
| Current weather | `weather.forecast_home` (Met.no) state and attributes |
| Hourly / daily forecast | `weather/subscribe_forecast`: the same data as the `weather.get_forecasts` action, pushed whenever Met.no updates |
| Sun | `sun.sun` `next_rising` / `next_setting` |
| Blended forecast | `sensor.ecco_solar_forecast_today`, `_remaining`, `_tomorrow` |
| Hourly forecast | the Solcast sensors' `detailedHourly` attribute |
| Actual PV | long-term statistics of `sensor.<dongle>_ecco_total_pv_energy` (hourly `change`) |
| Forecast.Solar hour markers | `sensor.energy_current_hour` and `sensor.energy_next_hour` |
| Accuracy | the ECCO scorecard sensors (`sensor.ecco_*_mae`, `_error`, `ecco_forecast_best_source`, `ecco_forecast_learning_days`) |

**Forecast:** a weather entity's attributes carry no forecast array. A card gets the forecast through the
subscription, which Home Assistant's own weather card also uses.

**Sun:** the Sun integration exposes only the *next* events. A sunrise or sunset that already happened today is
calculated from the Home Assistant location with the NOAA algorithm (the same as `intelligence/timeutil.py`), and is
marked `calc`.

**Blend:** the blend is a 50/50 mean of the two daily totals, with single-source fallback, as defined in
`home-assistant/packages/ecco_pro.yaml`.
- The card **reads** it: it never recomputes or re-weights it.
- The Solcast and Forecast.Solar values shown are the blend sensor's own `solcast_kwh` / `forecast_solar_kwh`
  attributes, so they are the values the blend actually used.

**Hourly series:**
- Solcast's `pv_estimate` per hour is kWh for that hour; the 24 values sum to the daily total.
- Forecast.Solar's hourly series is not available in Home Assistant unless Forecast.Solar is linked in the Energy
  dashboard. So the chart's hourly profile is Solcast's.
- The ECCO blend exists as daily totals only.

**Actual PV:** the recorder writes one row per completed hour, so the current hour has no bar yet.

**Rain:** Met.no forecasts rain amounts (mm) and cloud cover but **no rain probability**. The probability column appears
only when the weather entity supplies one.

## Freshness and missing data

- Each source shows when it last updated, and is flagged **stale** past its limit:
  - Met.no: 3 h, from the current-conditions update time, or the forecast's first hour lying in the past;
  - Solcast: 24 h, from its "API last polled" sensor;
  - Forecast.Solar: 6 h, from its sensors' update time.
- The ECCO blend sensors re-sample every 5 minutes, so their update time is never used as data freshness.
- Unknown values show `--`, never `0`. A real zero is shown as zero.
- A missing entity, a failed subscription, missing Solcast detail or missing statistics each produce a plain message
  saying what is missing. The rest of the card keeps working.
- A failed forecast subscription is retried after 5 minutes. Statistics are re-queried at most every 10 minutes.

## Time zones

Dates and hours follow the **Home Assistant time zone** (`hass.config.time_zone`), not the browser's. "Today", the
chart's hours, the daily rows and every time shown are those of the installation. Days with a DST change have 23 or 25
hours, and the tests cover both.

## Configuration

```yaml
type: custom:ecco-weather-solar-card
title: Weather & Solar      # optional
hourly_hours: 12            # 1-48
daily_days: 5               # 1-7
show_accuracy: true
show_insights: true
entities:                   # every key is optional; defaults shown in examples/weather-solar-example.yaml
  weather: weather.forecast_home
  pv_energy_statistic: "sensor.ecco_clock_dongle_ecco_total_pv_energy"
stale:                      # hours
  weather_hours: 3
  solcast_hours: 24
  forecast_solar_hours: 6
```

- **Entity keys:**
  - `weather`, `sun`;
  - `blend_today`, `blend_remaining`, `blend_tomorrow`;
  - `solcast_today`, `solcast_tomorrow`, `solcast_remaining`, `solcast_last_polled`;
  - `forecast_solar_today`, `forecast_solar_remaining`, `forecast_solar_tomorrow`, `forecast_solar_current_hour`,
    `forecast_solar_next_hour`;
  - `pv_power`, `pv_today`, `pv_energy_statistic`;
  - `blend_mae`, `solcast_mae`, `forecast_solar_mae`, `blend_error`, `solcast_error`, `forecast_solar_error`;
  - `best_source`, `learning_days`.
- An unknown key or a malformed entity id is refused, and Home Assistant shows its error card.
- The dongle-slug entity ids are rewritten for other installations by `tools/ecco_site_render.py`.

## Integration (a later, separate step)

The card ships undeployed: it is on no dashboard and in no manifest. Adding it needs a reviewed post-export (PEX)
entry, because the ECCO dashboard is frozen by the public export. The options are:

- the dashboard alone (a declared frozen edit), deploying the bundle like the flow card;
- or a `deployment/ha-manifest.yaml` `frontend_assets` stanza as well. The manifest is chain-pinned, and two older
  suites pin exactly two frontend assets.

Until then, to try it by hand:
1. Copy `dist/ecco-weather-solar-card.js` to `/config/www/`.
2. Add it as a Lovelace resource (`/local/ecco-weather-solar-card.js`, JavaScript module).

## Development

```bash
npm ci
npm run typecheck
npm test          # node --test; Node 22.18+ runs the TypeScript tests directly
npm run build     # deterministic: test/build.test.ts compares a rebuild with dist/
```

## License

GPL-3.0-or-later, like the rest of ECCO.
