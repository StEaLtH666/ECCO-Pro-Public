# Deploying the ECCO Intelligence integration (SHADOW)

This is the deploy route for the ECCO Intelligence integration under `custom_components/` (PR-5). It installs, upgrades,
rolls back and uninstalls the integration kit, places the owner's site file, and retires the Intelligence package files. It
never restarts Home Assistant: the restart that loads a custom integration, and any config-entry reload, stay separately gated.
Production installation needs its own approval. The tools only make it safe and repeatable.

| Command | What it writes |
|---|---|
| `tools/deploy-ha-kit.ps1 -Action Plan\|Install\|Upgrade\|Rollback\|Uninstall` | only the exact files of a verified kit, into `/config/custom_components/ecco_intelligence` |
| `tools/place-ha-site-file.ps1` | only `/config/ecco/intelligence/site.local.json` |
| `tools/deploy-ha.ps1 -Action Retire -Destination <file>` | moves one Intelligence package, dashboard or card file into `/config/ecco-backups/<stamp>/` |

All three share `tools/EccoDeploy.psm1` (the "Intelligence kit route" region). Windows PowerShell 5.1.

## Rules every command keeps

- **Nothing is deleted.** No command sends `rm`. A replaced, failed or uninstalled integration tree is moved under
  `/config/ecco/staging/<stamp>/` (`previous/`, `failed/`, `uninstalled/`). A retired file goes into `/config/ecco-backups/<stamp>/`.
  These folders build up at about 1 MB per run. The owner cleans them up.
- **Staging** happens under `/config/ecco/staging/<stamp>/` and **never inside `custom_components/`**, where Home Assistant would
  load it as an integration. Backups go to `/config/ecco-backups/<stamp>/`. A stamp that is already used is refused.
- **No symlink escape.** `/config` itself is a symlink on the SSH add-on, so it is resolved once and pinned (next section). Before
  any write, every path segment **below** `/config` down to the folder written is tested with `[ -L ]`. Folders are created one
  level at a time, never with `mkdir -p`.
- **Verified writes.** Every staged file is hashed on the host before the swap. Every backup is verified against its
  `BACKUP_SHA256SUMS`. Every installed file is verified in place, and the site file is read back by its sha256.
- **One rollback routine** (`Invoke-EccoKitRollback`) handles every failure once the swap has started. The message says "was
  rolled back" only when the restored state was verified. Anything it cannot work out is left untouched and reported as
  `ROLLBACK NOT CONFIRMED`.
- **Each `ha` call is its own ssh command** (`ha core check`, `ha core info --raw-json`). No route here sends `ha core restart`.
- **The single-file route refuses** `/config/ecco/intelligence/**` (the site file and the runtime state) and
  `/config/ecco/staging/**`. So does `ecco_deploy_preflight.py`. A sibling such as `/config/ecco/intelligence-x/` is still an
  ordinary destination.
- **Never touched:** the runtime state folder `/config/ecco/intelligence/state/` (no command names it) and the site file, except
  through the placement command. The kit route only reads the site file's sha256 and the state folder's device:inode, before and
  after a write, and refuses if either changed.

## `/config` is a symlink (amendment A26)

On the Home Assistant SSH add-on, `/config` is itself a symlink to the real configuration folder. This is a fact of the target
platform, not an assumption. A symlink test of `/config` itself would refuse every run, so the kit route, the placement and
Retire handle `/config` like this:

- **Resolved once, read-only, right after the ssh probe**, before the target guard and before anything else is read under
  `/config`. The probe tests `[ -L '/config' ]`, then enters it with `cd -P` and prints `pwd -P`. These are POSIX shell built-ins,
  and BusyBox ash has them too. `readlink -f` is not used, because it also "resolves" a dangling symlink.
- **Accepted only** as a real folder (whose physical path is `/config`), or as a symlink that resolves to an existing real folder
  whose physical path is a plain absolute path (segments `[A-Za-z0-9_.-]`, never `/`).
- **Refused (BLOCKED, nothing written):**
  - a dangling symlink;
  - a symlink to a file or another non-folder;
  - a symlink loop;
  - a plain file;
  - an absent `/config`, or a folder the ssh user cannot enter;
  - an answer that cannot be read.
- **Printed** on every run as the `Config root` line: in `Plan`, in the placement's `-Plan`, during the run and in every PASSED
  block. For example: `Config root : /config -> /<real folder> (a symlink to a real folder, ...)`.
- **Pinned until the first write.** Immediately before the first write, a read-only re-check must find `/config` resolving to the
  same root. Otherwise the run is BLOCKED and nothing is written. Every folder-creating command, the first write included,
  starts with the same test: `( cd -P '/config' && pwd -P ) | grep -Fqx '<root>'`. So a root that changes after the re-check still
  creates nothing.
- **Residual race (accepted, amendment A29):** the writes after that root-guarded folder creation (the uploads, the backup copy,
  the renames and Retire's move) name `/config` again without repeating the root test, so a `/config` re-pointed in between is
  not caught by the root test (most of those writes then fail only because the fresh `<stamp>` folders exist in the pinned root
  alone), a check-then-rename race that needs root on the SSH add-on to exploit.
- **Every segment below `/config`** keeps the per-segment symlink refusal (amendment A15) exactly as before. A symlinked
  `/config/ecco/staging`, `/config/custom_components` or `/config/packages` is still refused.

The single-file route (`deploy-ha.ps1` without `-Action Retire`) does not test `/config` per segment. Its read-only checks of the
test-instance marker and the site policy read through a `/config` that resolves to a real folder. Below a dangling, looping or
to-a-file `/config` they never report "absent", so the target guard blocks before any write.

## The `-Target Test|Production` guard

Every command takes `-Target`. The kit commands always require it. `deploy-ha.ps1` requires it whenever `-SshHost` is not the
production alias `ecco-ha`, and with `ecco-ha` it defaults to Production. The guard runs in two halves:

- **Locally, before any ssh call:** the target is given; the alias is a plain host alias; `-SshConfigFile` is accepted only with
  `-Target Test`.
- **On the host, read-only, before the first write:**
  - Test: `ssh -G` resolves the alias to a loopback address; the marker `/config/.ecco_l3_test_instance` is a regular file holding
    exactly `ECCO-L3-TEST <uuid>`; `ha core info --raw-json` reports `data.machine` = `ecco-l3-test`.
  - Production: not loopback, the marker proven absent, and a machine name that can be read and is not `ecco-l3-test`.

The isolated test instance is reached through a harness-owned ssh configuration: `-SshConfigFile <file>` adds `-F <file>` to every
ssh and scp call. Your own `~/.ssh/config` is not used or changed.

## The dashboard preservation gate and the gate pin

The kit route and the placement are not dashboard destinations, but they still run the gate's read-only policy read and
`classify`:

- a site policy that cannot be read, or is malformed, blocks the run;
- a policy that names anything under `/config/custom_components/` blocks the kit route, and one that names anything under
  `/config/ecco/intelligence/` blocks the placement.

The gate pin works exactly as in `deploy-ha.ps1`: `-ExpectedSiteGate`, or the git-ignored `ecco_dashboard_gate.local.txt`. With a
site gate pinned and the host policy moved aside, the run is refused. The one-run override is
`-ExpectedSiteGate DASHBOARD_PRESERVE_GATE`; keep the pin.

## 1. Build and record the kit (offline)

Build from a clean checkout at the commit you install from. The route compares the kit's `git_sha` with that checkout's HEAD and
rebuilds it there.

```powershell
cls
$PY = "<path to a Python 3.12 interpreter>"
$KIT = "<absolute kit directory outside the repository>"
& $PY -I -B tools\build_ha_integration.py --out $KIT --git-sha (git rev-parse HEAD)
(Get-FileHash -Algorithm SHA256 (Join-Path $KIT 'SHA256SUMS')).Hash.ToLower()
```

Record that sha256 offline. It is the `-ExpectedSumsSha256` of every run with this kit.

**Kit equivalence (production).** A production run also needs `-ReferenceKit <the L3-tested kit>` and `-ReferenceSumsSha256`,
the sha256 of that kit's SHA256SUMS recorded from the L3 run. The reference folder needs only its `SHA256SUMS` and
`VENDOR_MANIFEST.json`. The kit is accepted when its sums are identical to the reference's (IDENTICAL), or identical except the
two `VENDOR_MANIFEST.json` lines, with manifests that differ only in `git_sha` and so carry the same `modules` list (EQUIVALENT).

**Local checks before any ssh call:**

- the sums sha matches `-ExpectedSumsSha256`;
- every SHA256SUMS line is exactly `<sha256>  <path>`, with paths only under `custom_components/ecco_intelligence/`, `.py` and
  `.json` files, `[a-z0-9_]` folders, at most 4 levels, and no duplicates or case collisions;
- the folder holds exactly the listed files, with no junction or symlink, and every hash matches;
- the two manifest copies are equal, and `manifest.json` names the domain `ecco_intelligence`;
- `git_sha` = HEAD, and a rebuild with the frozen CLI gives identical SHA256SUMS bytes. A checkout without
  `tools/build_ha_integration.py` cannot install a kit.

Before the kit checks, the kit commands and `deploy-ha.ps1` run the repository validation (`validate-ecco.ps1`) unless
`-SkipValidation` is given. They pass their own `-Python` to it, so the repository validator runs under the same interpreter as
the gate's guard and the rebuild, never the `python` on PATH instead (review L3W-5). A relative `-Python` is resolved in the
directory you run the command from, for the validator as for the guard and the rebuild (review DRD-6). `validate-ecco.ps1` prints
the interpreter it used; a `-Python` that names no interpreter stops the run. Run on its own without `-Python`, it still uses the
`python` on PATH (else `py -3`) and says so.

## 2. Plan, then install or upgrade

```powershell
cls
.\tools\deploy-ha-kit.ps1 -Action Plan -SshHost ecco-ha -Target Production -ExpectedHaVersion <version> `
    -Kit $KIT -ExpectedSumsSha256 <sha256> -ReferenceKit <L3 kit> -ReferenceSumsSha256 <L3 sha256> -Python $PY
```

`Plan` sends read-only commands only and prints:

- the target, the resolved `/config` root, the HA version, the gate and pin lines;
- the kit, its equivalence and the installed state;
- the device and free-space checks;
- the site file (sha256 only, never content) and the config-entry count;
- every destination with the first 8 hex digits of its sha256;
- the staging and backup paths, the exact swap command, the never-touched list, the restart line and the rollback command;
- the owner's preconditions: a protected Home Assistant backup taken, `input_boolean.ecco_intel_paused` ON, and no other live
  change in progress.

`Install` (nothing installed) and `Upgrade` (an integration installed) do what `Plan` printed:

1. Read-only checks:
   - the ssh probe, the `/config` root (resolved and printed) and the target guard;
   - the gate and the pin;
   - `/config/.HA_VERSION` = `-ExpectedHaVersion`;
   - the symlink test of every segment below `/config`: `custom_components`, the integration folder, `ecco`, `ecco/staging` and
     `ecco-backups`;
   - `custom_components` and `ecco/` on one device, so the swap is an atomic rename;
   - free space;
   - the installed tree: regular files and folders only, safe names, and only files a kit could have written;
   - the protected snapshot and the config-entry count.
2. Re-check that `/config` still resolves to the printed root. Then create `staging/<stamp>/new/ecco_intelligence/...` and, for
   an upgrade, `staging/<stamp>/previous/` and `ecco-backups/<stamp>/`, in one command that tests the root again first.
3. Upload with one `scp` per folder, using exact file names (no `-r`), then verify the staged tree on the host: exactly the
   allowlist, every sha256.
4. Upgrade only: `cp -R` the installed tree to `ecco-backups/<stamp>/custom_components__ecco_intelligence`. Verify it (with
   `__pycache__` left out) and upload `BACKUP_SHA256SUMS`.
5. The swap. For an upgrade, rename the installed folder to `previous/`, then rename the staged folder into place. Each rename runs
   only when its target does not exist, so nothing ever nests.
6. Verify in place (`__pycache__` ignored), check the protected snapshot, then run `ha core check`.

A failure in steps 2-4 stops before the swap: nothing installed changed. A failure from step 5 on goes through the rollback.
Nothing is deleted. If the folder-creating command in step 2 does not report success, the message names only the folders this
run tried to create (the staging folder, and the backup folder when a tree is installed; an install creates no backup folder),
says they may not have been created and lists none as kept, since a used stamp's folder belongs to an earlier run (reviews
DR3-2 and DR4R-2). Once that command has succeeded, a later stop lists this run's `staging/<stamp>` (and, with a tree
installed, `ecco-backups/<stamp>`) as kept for inspection (review DR3-2).

The PASSED block prints the backup path and **RESTART REQUIRED - separately gated, not performed**. Keep
`input_boolean.ecco_intel_paused` ON until after that restart: lazy imports could otherwise load new modules into the old process.
It also prints the command that undoes the run, with `-SshConfigFile` when the run used one.

## 3. Roll back or uninstall

```powershell
cls
.\tools\deploy-ha-kit.ps1 -Action Rollback -BackupStamp <stamp> -SshHost ecco-ha -Target Production -ExpectedHaVersion <version>
.\tools\deploy-ha-kit.ps1 -Action Uninstall -SshHost ecco-ha -Target Production -ExpectedHaVersion <version>
```

- **`Rollback -BackupStamp`** verifies the backup against its `BACKUP_SHA256SUMS` and copies the listed files to
  `staging/<new stamp>/restore/`. It verifies them, backs up the current tree, then swaps exactly as an upgrade does.
- **`Uninstall`** is refused while Home Assistant's config-entry store names `ecco_intelligence`; only the count leaves the host.
  Delete the integration's entry in the UI first. It then backs up the tree and moves it to `staging/<stamp>/uninstalled/`. Its
  output names that step as a move aside (`Moved aside (not deleted): <install path> -> <staging>/uninstalled/...`) and its
  check as the install folder absent with the moved tree verified at the new path, never as a swap or "verified in place"; a stop
  before it reads `STOPPED before the move aside`, and a failed `ha core check` after it is rolled back as "failed after the move
  aside" (reviews L3W-6, DRD-5).

Both end with `ha core check` and leave the restart to you.

## 4. Place the site file

Record the site file's sha256 offline first. The file must stay outside every repository.

```powershell
cls
.\tools\place-ha-site-file.ps1 -SiteFile <site.local.json> -ExpectedSha256 <sha256> -SshHost ecco-ha -Target Production -Plan
.\tools\place-ha-site-file.ps1 -SiteFile <site.local.json> -ExpectedSha256 <sha256> -SshHost ecco-ha -Target Production
```

**Local checks:** the file is a regular file outside every git working tree, at most 256 KiB (the runtime's cap), UTF-8 without a
byte-order mark, a JSON object, and has the expected sha256. It must also be strict JSON, because the runtime reads it with
Python's `json.loads` and refuses the rest (`SITE_FILE` FAIL), while Windows PowerShell's `ConvertFrom-Json` would read several of
these forms. The placement refuses every file the runtime refuses, each with its own message, and never relies on
`ConvertFrom-Json` for that (reviews P1, DRD-2):

- `NaN`, `Infinity` and `-Infinity`;
- a number beyond the double range, which the runtime reads as non-finite: `1e999`, `1.797693134862315808e308`, or an integer
  too large for a double (2^1024 - 2^970 or more in magnitude, just above `1.7976931348623158e308`, which is accepted).
  The largest double, `1.7976931348623157e308`, and a number that underflows to zero, such as `1e-999`, are accepted;
- any other form that is not strict JSON: a bare word, a single quote, a comment, a number such as `+1`, `.5`, `01` or `1.`,
  and a control character or an unknown escape inside a string;
- JSON out of order: a missing or extra comma or colon, a trailing comma, a key that is not a string, a bracket not closed or
  not matched, or more than one value;
- arrays and objects nested more than 100 deep. The runtime reads deeper, until Python runs out of recursion room; a site file
  nests about five deep.

These words inside a string (`"NaN"`) are ordinary text and are accepted. The placement also refuses two keys that differ only in
case and an empty key, which the runtime would read but `ConvertFrom-Json` cannot (stricter, never looser).

**On the host:**

- the `/config` root is resolved, printed (also by `-Plan`) and re-checked before the first write; every segment below it is
  symlink-tested;
- `/config/ecco/intelligence` is created, one level, only when absent;
- an existing file is replaced only with `-ReplaceExistingSha256 <its live sha256>`, after a verified backup to
  `ecco-backups/<stamp>/`;
- the upload goes to a temporary file in the same folder, is hashed, renamed into place and read back;
- an upload that does not arrive intact (scp failed, or its sha256 on the host differs) stops the run before any rename. One
  command with markers moves the temporary file to `ecco-backups/<stamp>/site.local.json.upload-rejected`, never deleting it.
  The move runs only into the run's own backup folder (a real folder) and only when nothing is at that path. The STOPPED message
  names only what the marker shows:
  - moved aside, once the host shows the file at its new path;
  - no upload on the host;
  - something other than a regular file left in place;
  - the upload left in place and not moved aside, when the move's own guards refuse it (the backup folder missing or not a real
    folder, or something already at the rejected-upload path); this has its own marker (review DR4R-1);
  - with no single marker (a lost connection or a failed move), both places the upload may be (review DR3-1);
- a failure after the rename restores the backup, or moves a first placement into the backup folder. A connection lost before the
  read-back counts as a failure, because the new file may already be in place. The message says "was rolled back" only when the
  restore was verified, and otherwise says it could NOT be confirmed;
- a lost rename command goes to the same rollback. If the rename never ran, the upload stays in
  `/config/ecco/intelligence/site.local.json.ecco-upload-<stamp>.tmp`. The message names that file and says it was left in
  place, nothing deleted, for a first placement and a replacement alike; a first placement then reports that nothing was placed.
  It reports the temporary file as left in place only while the host still holds it (and says so when its state cannot be
  read), and names a moved-aside file only after it was seen on the host (review DR-4).

The PLACED block, like `-Plan`, prints the `Target` line of the guard. Every run creates its `ecco-backups/<stamp>/` folder before
the upload, for the rollback. After a first placement that passes, the folder is kept and empty, and the `Backup` line says so
(`none (first placement); /config/ecco-backups/<stamp> was created for a rollback and is kept, empty`) instead of a bare `none`
(review L3W-6). `deploy-ha.ps1` does the same for a new file: its `Backup` line names the kept backup folder and says whether this
run copied the Lovelace resource list into it or nothing at all.

The output shows sizes and hashes only, never the content. The file takes effect only at a separately gated config-entry reload
or restart.

## 5. Retire an Intelligence file

```powershell
cls
.\tools\deploy-ha.ps1 -Action Retire -Destination /config/packages/ecco_intelligence.yaml
```

Only the Intelligence files PR-6 installs can be retired:

- `/config/packages/ecco_intelligence*.yaml`;
- `/config/ecco/dashboards/ecco_intelligence*.yaml`;
- `/config/www/ecco/ecco-intelligence-card[.<sha8>].js`.

Extending that list is a safety-gate change.

Retire refuses:

- a file the site policy protects;
- a card file a Lovelace resource still loads (remove the resource in the UI first);
- a `/config` that does not resolve to a real folder, or a root that changed before the first write;
- any symlinked segment below `/config`.

A pinned site gate needs the one-run `-ExpectedSiteGate DASHBOARD_PRESERVE_GATE` for an unprotected dashboard. The file is moved,
never deleted. A failed `ha core check` copies it back. So does a read-back after the move that fails or does not match, a lost
connection included; the message then says that the configuration check after the move was not run, and says "was rolled back"
only when the copy back was verified. `-Restart` is refused with `-Action Retire`. The PASSED block prints the `Target` line of
the guard.

## For the L3 test harness

The route expects from the isolated test instance:

- the marker file `/config/.ecco_l3_test_instance` holding `ECCO-L3-TEST <lower-case uuid>`;
- an `ha` stub whose `core info --raw-json` prints `{"result": "ok", "data": {"machine": "ecco-l3-test", ...}}` and whose
  `core check` runs the configuration check;
- an alias that resolves to `127.0.0.1` in the harness-owned ssh configuration passed as `-SshConfigFile`;
- `/config` as a symlink to the real folder mounted elsewhere, as on the production SSH add-on (amendment A26);
- POSIX `find`, `sha256sum`, `stat -c`, `df -k`, `cp -R`, `mv`, `mkdir`, `grep -Fqx`, `head`, `cut` and `cat`, and the `cd -P` and
  `pwd -P` built-ins, in the shell that runs the commands.

## Tests

`tools/tests/Test-EccoDeploy.ps1` sections 17-24 cover the route offline, on fictional kits and a fictional `/config` tree driven
by stubbed ssh and scp under the local POSIX sh:

- the refusals, the kit and sums checks, equivalence and the rebuild;
- the target guard, including the placement and `Retire` in both directions (`-Target Production` on the marked loopback test
  instance, `-Target Test` on an unmarked host that is not loopback), and the `Target` line in the placement's Plan and PLACED
  blocks and in Retire's PASSED block;
- every read-only BLOCK case, including a symlinked `ecco/staging`, and `Uninstall` while the config-entry store cannot be read
  (absent, a symlink, or a failing `grep`);
- install, upgrade, both rollbacks and uninstall end to end, including a failed check, a corrupted upload, a lost connection after
  the swap and a folder reappearing between the renames;
- a folder-creating command that does not report success, or a stamp already used: no stamp folder is listed as kept, and both
  lines of the message name only the folders the run tried to create (an install names no backup folder); and, after a later
  stop, the two stamp folders that are listed exist (reviews DR3-2 and DR4R-2);
- the placement, `Plan`, `Retire`, and static checks for `rm`, restart and compounded `ha` calls, including a connection lost right
  after the placement's rename or Retire's move (rolled back, or reported as NOT confirmed), and the placement's rename command
  itself lost, for a first placement and a replacement, whether or not the rename ran (the temporary upload reported as left in
  place only while it is there);
- the placement's rejected upload: moved aside and seen there, scp failing with no file, something else at the upload path, a
  move answering its marker without the file appearing, a lost move and a failed move (both places named), and the move refused
  by its own guards with its own marker for a folder already at the rejected-upload path, a symlinked backup folder and a backup
  folder gone (the upload named as left in place) (reviews DR3-1 and DR4R-1);
- the kit `Plan`'s preconditions line, exactly;
- amendment A26 (sections 23-24, plus the probe cases in section 13):
  - `Plan`, install, upgrade, the placement and `Retire` through a `/config` junction to a real folder;
  - a dangling `/config`, one to a file, a loop and a plain file are refused before any write;
  - a symlinked segment below a symlinked `/config` is still refused;
  - a root re-pointed between the read-only checks and the first write is refused by the re-check, and one re-pointed just
    after it is refused by the folder-creating command itself;
  - the probe, its reading and the root test as pure logic.

Run the suite serially; it uses global ssh/scp stubs. The preflight mirror is covered by `tools/tests/test_ecco_deploy_preflight.py`.

**Still to verify on the isolated test instance (L3) and, read-only, on the production host:**

- the BusyBox or coreutils behaviour of these commands on the real SSH add-on, including `cd -P`, `pwd -P` and `grep -Fqx` in its
  login shell, and the resolved root it prints;
- `ha core info --raw-json` on production;
- the real `ha core check`;
- that a real restart loads the integration;
- a kill-sshd-after-the-rename drill for the placement and for `Retire` (amendment A37): the rollback message against the
  files the host really holds afterwards.
