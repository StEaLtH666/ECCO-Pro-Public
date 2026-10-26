# Installing the ECCO 3D Energy Flow card on the PREVIEW dashboard

These steps put the card on a preview / admin dashboard only. They do not touch the
production `ecco_pro` dashboard, the installed Energy Flow card or any inverter
setting. Each step is run by the owner (or under the owner's explicit authorisation)
with the project's staged-deployment tooling; nothing here is automatic.

## 0. What gets installed

| Item | Source | Destination on Home Assistant |
|---|---|---|
| Card bundle | `frontend/ecco-flow-3d-card/dist/ecco-flow-3d-card.js` (sha256 recorded in the status update) | `/config/www/ecco/ecco-flow-3d-card.<sha256-8>.js` |
| Scene pack | the ten approved V4 plates (`00_bright_summer_day.png` … `09_christmas_night.png`, 1448 × 1086) | `/config/www/ecco/scenes/` |
| Lovelace resource | one JavaScript-module resource | `/local/ecco/ecco-flow-3d-card.<sha256-8>.js` |
| Card configuration | `examples/ecco-example.yaml` | one card on the preview dashboard |

The card is read-only: it reads entity states and opens Home Assistant's own
more-info dialogue. It calls no service and writes nothing (enforced by
`test/safety.test.ts` and `tools/tests/test_flow_3d_card.py`).

## 1. Before copying anything

1. Build and test on the PC (local first): `npm ci`, `npm run typecheck`, `npm run build`, `npm test` in this folder, and
   `python -I -B tools/tests/test_flow_3d_card.py` from the repository root. Record the bundle hash:
   `sha256sum dist/ecco-flow-3d-card.js` (LF content; the committed `dist/` must equal a fresh build).
2. Confirm the entity ids in `examples/ecco-example.yaml` against the live entity registry (Developer tools → States). The
   example's ids come from this repository (packages, dashboard, firmware names) and have not been live-verified by this
   prototype. Anything missing shows as `--` on the card; nothing is fabricated.
3. Decide where the plates live: deploy-only under `/config/www/ecco/scenes/` (default below) or committed to the
   repository first. The card reads them from `scene.pack`.

## 2. Stage the files (owner-authorised step, staged tooling)

Use the existing deployment helper so the resource read-back gate applies (PR #40): copy the bundle to
`/config/www/ecco/` under its hash name and the ten plates to `/config/www/ecco/scenes/`. Do not overwrite the installed
`ecco-energy-flow-card.*.js`. Verify the copies by hash before continuing.

Rollback for this step: delete the two new paths. Nothing else changed.

## 3. Register the resource (owner action in the UI)

Settings → Dashboards → Resources → Add resource:
URL `/local/ecco/ecco-flow-3d-card.<sha256-8>.js`, type **JavaScript module**. Reload the browser (hard refresh).

## 4. Add the card to the PREVIEW dashboard

Open the preview / admin dashboard (not `ecco_pro`) → Edit → Add card → Manual → paste the contents of
`examples/ecco-example.yaml`. The `scene:` block already points at `/local/ecco/scenes/`. Save.

Checks on the preview dashboard:

- The scene plate loads and matches the time of day / weather; the "System online" chip is green when the dongle's
  telemetry sensor is on.
- Solar, grid, battery and home figures agree with the installed Energy Flow card on the Overview (same entities, same
  sign conventions, same home-load fallback).
- Battery charging reverses the green particles towards the cabinet; grid export reverses the blue particles towards the
  pylon; an idle grid (below 5 W) shows no particles.
- FE-1 time to reserve appears in the battery card and the Runtime tile when the runtime entity is discharging.
- Tapping a card, tile or detail row opens the entity's more-info dialogue and nothing else.
- Phone width: two-column status tiles, the whole plate visible, cards legible.

## 5. Rollback

Remove the card from the preview dashboard, delete the resource, delete
`/config/www/ecco/ecco-flow-3d-card.<sha256-8>.js` and `/config/www/ecco/scenes/`. No package, automation or inverter
setting is involved, so nothing else needs restoring.

## 6. After a successful preview

Write an inbox status update in the private repository (what was installed, hashes, what was checked, what was not). Moving
the card to the production Overview is a separate, later decision and job.
