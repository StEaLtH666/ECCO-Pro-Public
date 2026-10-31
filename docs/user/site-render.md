# Rendering the deployable files for your site

The repository is generic. Every Home Assistant entity id of the ECCO dongle uses the default device slug `ecco_clock_dongle`
(what a fresh Home Assistant install generates for the firmware's `name: ecco-clock-dongle`), and the Octopus Energy tariff
entities use the placeholders `your_meter_serial`, `your_import_mpan` and `your_export_mpan`.

If your installation uses the defaults and no Octopus tariff entities, deploy the files as they are. Otherwise render a local
copy with your values and deploy that copy. Your values never go into tracked files.

## 1. Create your site file

```
cp ecco_site.example.yaml ecco_site.local.yaml
```

`ecco_site.local.yaml` is git-ignored. Edit it:

| Key | Meaning |
|---|---|
| `device_slug` | The slug between `<domain>.` and `_<entity>` in your dongle's entity ids, e.g. `sensor.my_dongle_ecco_battery_soc` gives `my_dongle`. Lower-case letters, digits and single underscores |
| `keep_default_slug_entities` | Dongle entity ids that kept the default slug on your installation even though the device was renamed (rare) |
| `octopus` | Optional: `meter_serial`, `import_mpan`, `export_mpan` exactly as they appear (lower-case) in your Octopus Energy entity ids |
| `entity_map` | Optional: exact entity id renames for other site-specific entities the packages reference (whole ids only) |

## 2. Preview, then render

```
python tools/ecco_site_render.py --site ecco_site.local.yaml --dry-run
python tools/ecco_site_render.py --site ecco_site.local.yaml --diff
python tools/ecco_site_render.py --site ecco_site.local.yaml
```

The last command writes `dist/site/` (git-ignored): the Home Assistant packages and dashboard, the InfluxDB files, the card
assets and examples, and the local snapshot / flight-recorder tools, all with your values. `--diff` masks tariff values.

## How the renderer decides (exact rules, fail closed)

- `<domain>.ecco_clock_dongle_<object>` entity ids (sensor, binary_sensor, number, switch, button, select, ...) are rendered to
  your slug. A quoted mention of the bare slug (documentation) is rendered too.
- ESPHome action service names (`esphome.ecco_clock_dongle_<action>`) and firmware file names are **kept**: they come from the
  firmware's node name, not from Home Assistant's device slug.
- Tariff placeholders are replaced only inside whole Octopus Energy entity ids.
- Anything else that spells the default slug, a tariff placeholder outside an entity id, an `entity_map` id that occurs
  nowhere, or a site value that matches nothing stops the render with an error and writes nothing. A tree that was already
  rendered is refused as input.

The renderer is covered by `tools/tests/test_ecco_site_render.py`.

## Deploying

Deploy from `dist/site/`, not from the repository files. If you use the SSH deployment helpers, point them at the rendered
copy. Keep `dist/site/` and `ecco_site.local.yaml` out of version control and out of issue reports: they contain your
identifiers.

### Card bundles: the resource read-back gate

`tools/ecco_deploy_preflight.py plan` renders and stages each card as `dist/deploy/stage/<card>.<sha8>.js` and writes
`dist/deploy/plan.json`, without contacting Home Assistant. A card bundle then goes live in separate steps, and only the last one
proves it:

1. **Copy.** `tools/deploy-ha.ps1` copies the staged file to `/config/www/ecco/`, then `verify-served` checks the bytes Home
   Assistant serves. **Nothing a dashboard loads has changed yet.** After the copy, `deploy-ha.ps1` reads the persisted resource
   list once (read-only) and prints `RESOURCE NOT SWITCHED <card>: the dashboards still load <old URL>`, or `NOT REGISTERED`,
   `ALREADY POINTS AT THIS FILE` or `UNKNOWN`.
2. **Switch the resource by hand.** In Settings -> Dashboards -> Resources, edit the card's existing entry to
   `/local/ecco/<card>.<sha8>.js` (JavaScript module). No ECCO tool edits resources, and a resource is shared by every dashboard.
3. **Read back and verify.** Read the persisted list again now, and compare it with the plan and with a copy saved before step 2:

```powershell
cls
ssh <ha-host> "cat /config/.storage/lovelace_resources" | Out-File -Encoding utf8 resources-now.json
python tools\ecco_deploy_preflight.py verify-resource --plan dist\deploy\plan.json --resources resources-now.json --before resources-before.json --base-url <HA URL>
```

`--resources` and `--before` take the raw `lovelace_resources` storage file or the websocket `lovelace/resources` result. Both
carry the resource ids the checks need. Capture both lists the same way, because any difference in an entry counts as a change.
For each planned card, `verify-resource` checks that:

- exactly one resource loads the card, and its URL and type are the plan's;
- with `--before`, the card's entry kept its id and type, and no other resource was added, removed or changed;
- with `--base-url`, the bytes served at that exact URL hash to the plan's sha256;
- the read-back is at most `--max-age-minutes` (default 30) old.

The tool is read-only: it writes nothing, and its only network use is the optional GET. It prints one line per card:

| Line | Meaning |
|---|---|
| `RESOURCE VERIFIED <card> -> <url> (id <8>, persisted, read back at <UTC>)` | Printed only when every check of the run passed (exit 0). |
| `RESOURCE NOT SWITCHED <card>: still <url>` | The dashboards still load another bundle. |
| `RESOURCE NOT VERIFIED <card> -> <url>: <reasons>` | The URL was switched, but another check failed. |

Report a card install as done only after `verify-resource` exits 0, and quote its `RESOURCE VERIFIED` line. Until then, report
the copy as staged and not live, naming the resource the dashboards still load. Checking the card in a browser is a separate,
later step.

### Dashboard preservation gate

A site may customise its live dashboard file, for example by replacing one card with a private card or by pointing a card at
private media. A new render of this repository would silently put the generic version back. `tools/deploy-ha.ps1` (and
`tools/deploy-dashboard.ps1`, which calls it) therefore refuses to put a repository dashboard over a site's protected layer.

**What it refuses, and why.** Before its first write to the host (the backup folder, the backup copies, the upload),
`deploy-ha.ps1` copies, read-only, the site policy, the live destination file and `/config/.storage/lovelace_resources` into a
fresh temporary folder (deleted again afterwards), copies the candidate there too, prints the sha256 of the candidate, the live
file and the resource list, and runs `tools/ecco_dashboard_guard.py check` on those copies. It gates every dashboard
destination: a file under `/config/ecco/dashboards/` ending `.yaml` or `.yml`, or any destination the site policy names. The
deployment stops, with nothing written to the host, when:

- **site layer (R2):** the live file no longer matches the policy at a protected pointer (`live protected layer differs from the
  site policy`; see drift recovery below), or the candidate removes or changes a protected subtree (`candidate removes or replaces
  a protected layer`);
- **site layer (R3):** a Lovelace resource the policy requires is not registered;
- **generic layer (R4, also without a policy):** the candidate drops a `custom:` card type that the live dashboard uses (named by
  the pointer of its first use in live and a use count, never by its name);
- **refused input (R1, R5):** a file does not parse, the policy is present but unreadable (also a symlink, or a folder that
  cannot be searched) or malformed, the interpreter or PyYAML is missing, the policy protects a destination that does not exist
  on the host (every destination it names is checked, so a mistyped one is caught), or the policy names the deployed path only
  with a different letter case.

The backup folder also receives a copy of `lovelace_resources`, and the backed-up file must be the file the gate checked. The
source must still have the candidate's sha256 before anything is written, and the uploaded copy must have it before the move into
place, so the installed bytes are the checked bytes. After the post-install sha256 check, a destination the policy names is read
again and checked with `verify-live`; a failure rolls back like a failed `ha core check` (the backup is the checked live file, so
the automatic rollback keeps the protected layer). Nothing can be deployed under `/config/ecco/site-local/`.

**Rollback and Home Assistant's dashboard cache.** Home Assistant keeps serving its cached copy of a YAML dashboard while the
file is not newer than that cache. The automatic rollback therefore restores the backup with a plain `cp` followed by `touch`,
never `cp -p` (which would bring back the backup's old modification time and leave the failed deployment on screen). A rollback
of a dashboard ends with `DASHBOARD READ-BACK REQUIRED`: read the served dashboard (websocket `lovelace/config` for that
dashboard) and compare it with the restored file before reporting the rollback as complete. Restore a backup by hand the same
way: `cp`, then `touch`, then the read-back.

The deploy output and the `ECCO DEPLOYMENT PASSED` block print the gate line. **For a site with a policy, accept a dashboard
deployment only when that line names the site's gate**, `<SITE_GATE_NAME>: PASS`, not `DASHBOARD_PRESERVE_GATE: PASS`: the
default gate name means the policy did not apply to that destination. A gate pin (below) makes `deploy-ha.ps1` enforce this
itself. The guard prints JSON pointers, counts, 12-hex prefixes of
subtree hashes and full sha256 values of whole files only, never a dashboard, overlay, resource or card type value, and a usage
error never echoes an argument. Exit codes: 0 PASS, 3 BLOCKED by a rule, 2 refused input (the first line says BLOCKED for both);
`classify` exits 4 for "not a dashboard destination".

**Pinning the site's gate (`-ExpectedSiteGate`, `ecco_dashboard_gate.local.txt`).** Without a policy on the host, a dashboard
passes under `DASHBOARD_PRESERVE_GATE`, the generic layer only. So a host policy that was moved aside, replaced, or no longer
names the destination would silently drop the site layer's protection. A pin closes that gap. Give `deploy-ha.ps1` (or
`deploy-dashboard.ps1`) `-ExpectedSiteGate <SITE_GATE_NAME>`, or put the gate name in `ecco_dashboard_gate.local.txt` at the root
of the checkout (git-ignored; one name, blank and `#` comment lines ignored; the parameter takes precedence). The pin is read
before the host is contacted, and a pin file that is not exactly one gate name stops the deployment. With a pin:

- a dashboard destination must pass under exactly the pinned gate, otherwise the deployment stops before its first write;
- any other destination (a package, a card bundle) needs the site policy present on the host;
- `-ExpectedSiteGate DASHBOARD_PRESERVE_GATE` is the deliberate way to deploy a dashboard the policy does not protect (it blocks a
  destination the policy does protect).

The pin covers the dashboard destinations. A destination the policy names outside `/config/ecco/dashboards/` is gated only while
the policy names it.

**Drift recovery (`-AllowDriftRecovery`).** When live no longer matches the policy at a protected pointer, the gate blocks every
candidate, including one that carries the policy's layer exactly. Live may hold newer site values than the policy; then make a
new policy instead (**Making a policy**, below). When the policy is right and live drifted (for example, a generic file was copied
over it outside `deploy-ha.ps1`), deploy a candidate that carries the policy's layer (the output of `apply`, below) with
`-AllowDriftRecovery`. The gate
then passes and prints `WARNING R2 drift: ...` for each drifted pointer and a `WARNING drift recovery: ...` line. `deploy-ha.ps1`
repeats them as PowerShell warnings, and its `ECCO DEPLOYMENT PASSED` block adds `Drift : RECOVERED` with the backup that holds
the drifted file. A candidate that does not carry the protected layer exactly stays BLOCKED with or without the switch. The
switch waives nothing else (R3, R4). If live fell back to a generic card, the recovery also needs `-AcceptRemovedCardType` for
the generic card type the candidate drops. `verify-live` never accepts drift.

**The interpreter.** The guard runs as `python -I -B -X utf8`, with the `python` on PATH or the interpreter named by `-Python
<python.exe>` on `deploy-ha.ps1` and `deploy-dashboard.ps1`. `-I` (isolated mode) ignores the user site-packages folder, so PyYAML
must be installed in that interpreter itself; a PyYAML installed with `pip install --user` does not count. Without it every
dashboard deployment is BLOCKED (fail closed). While a site policy is present, every deployment, packages and cards included,
needs that interpreter, because the policy is classified for every destination.

**The site-local policy.** It lives on the host at `/config/ecco/site-local/dashboard-protection.json`, schema
`ecco-dashboard-protection/1`:

| Key | Meaning |
|---|---|
| `gate` | The gate name printed for the destinations the policy names (upper case, e.g. `EXAMPLE_SITE_PRESERVE_GATE`); other destinations print `DASHBOARD_PRESERVE_GATE` |
| `dashboards[].destination` | The protected file on the host, spelled exactly as deployed (each destination once; it must exist on the host) |
| `dashboards[].protect[]` | `{pointer, sha256}`: an RFC 6901 pointer into the parsed YAML and the canonical sha256 of that subtree |
| `dashboards[].overlay[]` | `{pointer, value}`: the scalar values that make up the site layer, inside a protected pointer (used by `apply`) |
| `dashboards[].require_resources[]` | `{url}`: Lovelace resources that must be registered |

`deployment/dashboard-protection.example.json` shows the shape with fictional values. A real policy holds the site's values: it
stays on the host and in the site's own offline records, never in a repository, an issue or a pull request. A policy that is
present must be valid; there is no "empty" policy (to retire protection, see below).

**Making a policy.** From the base render the site deployed and a copy of the live file:

```powershell
cls
python tools\ecco_dashboard_guard.py make-policy --gate <SITE_GATE_NAME> --destination /config/ecco/dashboards/ecco_pro.yaml --base <rendered ecco_pro.yaml> --live <copy of the live ecco_pro.yaml> --pointer <JSON pointer of the customised subtree> --require-resource <resource URL> --out <local policy file>
```

`--require-resource` is optional and repeatable. `make-policy` refuses when live and the base differ anywhere outside
`--pointer` (it prints those pointers, never the values), when a differing leaf is not a scalar or sits in a list, or when live
removed a key, and it proves the policy (applied to the base, it gives live) before writing it. Copying the policy to
`/config/ecco/site-local/` on the host is a deliberate owner step; no ECCO tool writes there.

**Deploying a new render over a protected dashboard.** A fresh render (and `deploy-dashboard.ps1`, which copies the repository
file as it is) carries the generic layer, so the gate blocks it. `apply` writes the policy's overlay into the render's text:

```powershell
cls
python tools\ecco_dashboard_guard.py apply --policy <local copy of the host policy> --destination /config/ecco/dashboards/ecco_pro.yaml --candidate dist\deploy\stage\ecco_pro.yaml --out dist\protected\ecco_pro.yaml
.\tools\deploy-ha.ps1 -Source dist\protected\ecco_pro.yaml -Destination /config/ecco/dashboards/ecco_pro.yaml
```

`ecco_deploy_preflight.py plan --site-policy <local copy of the host policy>` prints these two steps in the plan's deploy
commands, with `apply`'s `--out` under the plan's `stage/` (named by the render and the policy). It also runs `apply` in memory and
reports whether it will succeed on this render (FAIL when it would refuse, for example after a release that changes the protected
card). Without `--site-policy`, the plan says that its dashboard command deploys the render as it is.

`apply` replaces single-line scalars in place, inserts missing keys at their mapping's indentation and leaves every other line as
it was; the result does not depend on the order of the overlay operations. It writes only when the result parses to the render
with exactly the overlay values set and matches every protect hash; otherwise it writes nothing (exit 3). It refuses a missing
parent, a flow mapping, a list, an anchor or alias, a merge key and a target that is not a plain scalar. `--out` must not exist
yet and its folder must exist (`dist/` is git-ignored).

**A release that changes the protected card.** The policy freezes the whole subtree at its pointer. When a release changes a
generic attribute of that card (or moves it to another index), `apply` refuses (`post-condition: ... still differs from the
protected layer`), and `make-policy` cannot simply be re-run against the new render while live still holds the old card. The
owner procedure, one deliberate step at a time:

1. Hand-merge the site values into the new render (start from `apply`'s refusal: the overlay pointers name every site value),
   giving a merged candidate under `dist/`.
2. Move the host policy aside, out of `/config/ecco/site-local/` (an owner decision; the site is unprotected until step 5).
3. Deploy the merged candidate with `deploy-ha.ps1`. The generic layer still runs: R4 passes because the merged candidate keeps
   the site's custom card type. With a gate pin, this one deployment needs `-ExpectedSiteGate DASHBOARD_PRESERVE_GATE`, given
   deliberately.
4. Make the new policy: `make-policy --base <new render> --live <copy of the new live file> --pointer <the card's pointer in the
   new render>`.
5. Install the new policy on the host (owner step), then prove it: `ecco_dashboard_guard.py verify-live --policy <the new policy>
   --destination <destination> --live <a fresh copy of the live file>` must print `<SITE_GATE_NAME>: PASS`.

**Replacing a custom card, and rolling back across it (`-AcceptRemovedCardType`).** The generic layer applies to every site, with
or without a policy: a release that replaces one custom card with another (for example a new card type on the Overview) drops a
`custom:` type the live dashboard uses, and so does a rollback to the file from before such a release. Each of those deployments
needs `-AcceptRemovedCardType custom:<the dropped card>`, given deliberately for that deployment. It waives R4 for exactly the
named types (`custom:<name>`, name `[A-Za-z0-9][A-Za-z0-9._-]*`); every other dropped type still blocks, and it never waives a
protected layer or a required resource.

**Retiring protection (an owner decision).** To retire protection, move the host policy aside (out of
`/config/ecco/site-local/`), remove the local gate pin (`ecco_dashboard_gate.local.txt`), then deploy with
`-AcceptRemovedCardType custom:<card>` for each custom card type the live dashboard uses that the render drops. A manual
rollback to a file without the protected layer (for example the previous generic render) is blocked in the same way and needs
the same deliberate step.

**Tests.** The guard is covered by `tools/tests/test_ecco_dashboard_guard.py` (run in CI). The PowerShell side, including a
deploy-ha.ps1 run against a stubbed host that proves a BLOCKED gate (or a gate pin that does not match) writes nothing, and a
rollback on a fictional tree under a local POSIX sh that proves the restored file is newer than the cache, is covered by
`tools/tests/Test-EccoDeploy.ps1`, which CI does not run (CI only parses `tools/*.ps1`): run `powershell -NoProfile -ExecutionPolicy Bypass -File
tools\tests\Test-EccoDeploy.ps1 -Python <python.exe with PyYAML>` with Windows PowerShell 5.1 as a required local pre-push step
for every change to the deploy tooling or the guard.
