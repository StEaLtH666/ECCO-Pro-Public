# Installing the ECCO 3D Energy Flow card on the PREVIEW dashboard

These steps put the card on a preview / admin dashboard only. While production runs dashboard 7.22.0 or earlier they do not
touch the production `ecco_pro` dashboard, the installed Energy Flow card or any inverter setting. **Once dashboard 7.23.0
(section 7) is installed, the card's resource, bundle file and plates also serve the production Overview**: section 5 must
not run then, and section 6 is a production change. Each step is run by the owner (or under the owner's explicit
authorisation) with the project's staged-deployment tooling; nothing here is automatic.

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
- Solar, grid, battery and home figures agree with the installed Energy Flow card on the Overview (dashboard 7.22.0 or
  earlier; same entities, same sign conventions, same home-load fallback).
- Battery charging reverses the green particles towards the cabinet; grid export reverses the blue particles towards the
  pylon; an idle grid (below 5 W) shows no particles.
- Each card's dotted link and the card's border breathe together, slowly and in step with the other cards, while that
  flow carries power; idle links rest faint and still (`scene.links: particles`
  restores travelling particles on the links, `off` removes them). The house feed runs up the inverter's left side and
  along the house wall to the wall light.
- FE-1 time to reserve appears in the battery card and the Runtime tile when the runtime entity is discharging.
- Tapping a card, tile or detail row opens the entity's more-info dialogue and nothing else.
- Phone width: two-column status tiles, the whole plate visible, cards legible.

## 5. Rollback

**Only while production runs dashboard 7.22.0 or earlier.** With 7.23.0 installed the resource, the bundle file and the
plates also serve the production Overview: roll production back to 7.22.0 first (section 7), then run this section.

Remove the card from the preview dashboard, delete the resource, delete
`/config/www/ecco/ecco-flow-3d-card.<sha256-8>.js` and `/config/www/ecco/scenes/`. No package, automation or inverter
setting is involved, so nothing else needs restoring.

## 6. Upgrading an installed preview to a new bundle (for example V2)

A Lovelace resource registers the `ecco-flow-3d-card` element for every dashboard, so two bundles of this card cannot be
loaded side by side: the upgrade swaps the ONE preview resource from the old bundle file to the new one, and the old file
stays on disk as the rollback. The scene plates are unchanged by V2 (same ten files, same hashes), and nothing outside
the preview dashboard's resource changes. A card configuration without `scene.routing` (the installed preview's has none)
works unchanged; V2 renamed and removed routing keys, so a V1 `scene.routing` override must be removed or rewritten for
V2 before the upgrade.

**With dashboard 7.23.0 installed, this resource is also the production Overview's**: swapping it changes the card on the
production Overview at the same moment as on the preview. The upgrade is then a production change: gate it as one (the
owner's approval for a production change, a fresh read of production state and a production rollback plan), not as a
preview step.

Each step needs the owner's authorisation; re-read the live state first.

1. On the PC: build and test the candidate (section 1), record its LF sha256 and the first 8 hex digits `<new8>`.
   For V2's first build on `dev/ecco-flow-3d-v2`: 132,807 B, sha256
   `0ef4ada6dbe80ec8413fb422e5fbc346218321fc5eab2b6eed3c0b3385a51bdf` (`<new8>` = `0ef4ada6`, over V1's `<old8>` =
   `cd917647`). For V2 with the animated connectors and the house feed to the wall light: `dist/ecco-flow-3d-card.js`
   134,464 B, sha256 `2cc92b30e0730511dfc1b3fc51c4b6225714550d54d8e80bb90f722d906d78aa` (`<new8>` = `2cc92b30`). For V2
   with the pulsing dotted card links (`scene.links`): `dist/ecco-flow-3d-card.js` 137,789 B, sha256
   `9bf045c25822710319c855b4d2f0c8da2e558a3cac4b0f5600ebb8d726efa701`, so `<new8>` = `9bf045c2`. `<old8>` is whichever
   bundle the preview resource currently names.
2. Pre-checks (read-only): the preview resource still points at the old file (`/local/ecco/ecco-flow-3d-card.<old8>.js`),
   the old file's sha256 still matches the record, the ten plates still match their manifest, the production `ecco_pro`
   file is unchanged (hash and mtime as recorded). If that file is dashboard 7.23.0 or later, the swap in step 4 changes
   its Overview too (see above).
3. Stage the new file with the deployment helper: `/config/www/ecco/ecco-flow-3d-card.<new8>.js`. Do NOT overwrite or
   delete `ecco-flow-3d-card.<old8>.js`. Verify the copy by sha256 on the host and the served bytes over HTTP.
4. Change the existing preview resource's URL from `<old8>` to `<new8>` (Settings → Dashboards → Resources, or the
   websocket `lovelace/resources/update` on the same resource id). Read the resource list back and run the
   `verify-resource` gate against a plan naming `<new8>`.
5. Hard-refresh the preview dashboard; check the scene, the four cards and their connectors, the diagnostics and Today
   strips and the browser console.
6. Rollback (one step): set the resource URL back to `/local/ecco/ecco-flow-3d-card.<old8>.js` and hard-refresh. The new
   file may then be deleted. Plates, dashboard files and every other resource were never touched; with 7.23.0 installed the
   rollback also returns the production Overview to the old bundle.

## 7. After a successful preview; the production placement (ovw3)

Write an inbox status update in the private repository (what was installed, hashes, what was checked, what was not). Moving
the card to the production Overview is a separate decision and job.

**Production placement (post-export entry `ovw3`, dashboard 7.23.0, staged).** Section S3 of the production `ecco_pro`
Overview shows this card in place of the 2D Energy Flow card, configured as `examples/ecco-example.yaml` plus the
dashboard's grid layout, in the dashboard's generic entity naming (the site renderer renders it for the site). It needs no
new file and no new resource: it loads through the resource and the plates the preview already uses, so the deployment is
the dashboard file alone.

**Prerequisite.** This card's bundle, its JavaScript-module resource and the ten plates under `/config/www/ecco/scenes/`
must already be installed (sections 2 and 3), for the bundle of the tree being deployed, and production must run dashboard
7.22.0 with this tree's other ECCO card bundles and resources installed (a dashboard-only plan neither stages nor checks them;
compare its unchanged-card list with the live resources). Before installing 7.23.0, check read-only:

- the persisted Lovelace resource list (the raw `lovelace_resources` file or the websocket `lovelace/resources` result) has
  exactly one resource whose file name starts with `ecco-flow-3d-card`, its URL is
  `/local/ecco/ecco-flow-3d-card.<sha256-8>.js` for this tree's `dist/ecco-flow-3d-card.js` (LF sha256; `9bf045c2` for V2 as
  merged) and its type is `module`;
- `/config/www/ecco/ecco-flow-3d-card.<sha256-8>.js` on the host has that sha256, and the ten plates match their manifest.

Known limitation: `tools/ecco_deploy_preflight.py plan` does not make this check. It verifies the resources only of the cards
it deploys and the registration of the third-party cards, and it leaves this card out of its default card list (`flow-3d`), so
a missing or stale resource for it is not reported. Make the check above by hand and record it.

**Plan (dashboard only).** From the repository root of the clean merged tree:

```
python -I -B tools/ecco_deploy_preflight.py plan --root . --site <site file> --snapshot <fresh /api/states dump> --baseline-dashboard <live ecco_pro.yaml> --resources <persisted lovelace_resources> --expect-sha <merged sha> --deploy= --out <directory outside the repository>
```

Write `--deploy=` exactly: Windows PowerShell 5.1 drops the empty argument of `--deploy ""`, so the tool refuses that command
(`expected one argument`), and leaving `--deploy` out would plan the default card list. The plan must stage only `ecco_pro.yaml` (no card copy), plan no resource action and require no restart,
and show 0 FAIL; its one deploy command copies the staged dashboard to `/config/ecco/dashboards/ecco_pro.yaml`.

Once the 7.23.0 dashboard is installed:

- the preview's resource, its bundle file and `/config/www/ecco/scenes/` are shared with the production Overview: section 5
  must not run (roll production back to 7.22.0 first), and a section 6 upgrade changes the production Overview and is gated
  as a production change;
- rolling back the production placement is the dashboard file alone: put back the site render of the 7.22.0 `ecco_pro.yaml`
  (its sha256 is recorded with the deployment); the resource, the bundle and the plates stay as they are.
