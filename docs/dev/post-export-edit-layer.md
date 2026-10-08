# Post-export edit layer (PEX)

Schema `ecco-pex/1`. Foundation entry: `pex0`. Code: `registry/tests/_pex.py`, `registry/tests/_pex0_scope.py`.
Proofs: `registry/tests/test_pex_transition.py` and `registry/tests/test_pub0_transition.py`.

## Why it exists

This repository was published as the `pub0` export of the project's earlier private development tree. `pub0` is a declared,
exact, reversible transition: its manifest (`registry/tests/fixtures/pub0_manifest.json`) records the result hash of every file it
sanitised (57 files: Home Assistant packages, the dashboard, several test suites, the capability registry and some tools).

Those files are therefore **frozen**. Editing one directly makes the `pub0` proof fail, and that is correct: the proof says that the
published files are exactly the export. The manifest cannot be regenerated here, and re-hashing an older pin is never allowed (see
[CONTRIBUTING.md](../../CONTRIBUTING.md)).

PEX is the supported way to change a frozen file after the export. Every such change is declared as a **post-export chain entry**.
The proofs then undo the declared changes exactly and check that what remains is still the `pub0` export, byte for byte.

## What is frozen

- Every `pub0` target that is not already pinned by the scope chain. The pinned artifacts (firmware YAML, durable headers, capability
  registry, transaction state machine, `deployment/ha-manifest.yaml`) keep their own chain mechanism.
- The enrolled files, whose export-era content older suites pin. The list only grows with such evidence, by an owner decision
  (O3):
  - `VERSION.yaml`;
  - since `esb1` (O3 amendment): the Energy Actions card's `package.json`, `package-lock.json` and built bundle
    `dist/ecco-energy-actions-card.js`, which the FB-B3 / FB-C3 card-folder pins and the lic0 proofs pin.

The `pub0` state of a frozen file is its manifest result hash, read from the manifest and never typed by hand. For an enrolled
file it is the recorded hash of the file at the export commit (883068d).

## Making a change to a frozen or chain-pinned file

1. Make the change on a branch, as usual.
2. Add one module `registry/tests/_<id>_scope.py` with the exact `(before, after)` pairs of every edit. Generate the pairs from the
   real diff and check that they round-trip. Each reverter must expose its pairs as `.edits`.
3. Append one `Entry` at the end of `POST_EXPORT_ENTRIES` in `registry/tests/_scope_chain.py`:
   - `reverts` and `checkpoints` for the chain-pinned artifacts it edits;
   - `frozen_reverts` and `frozen_checkpoints` (the sha256 after the change) for the frozen files it edits;
   - its counted deltas and other declarations, exactly as for any chain entry;
   - its `fingerprint`, computed with `_pex.fingerprint()`. It hashes the previous entry's fingerprint, so an older entry cannot be
     rewritten without changing every later one.
4. If an older suite pins the export-era state of a file you change, read that pin through `_pex.as_of_pub0(...)`. Mark the line
   with a `PEX` comment, and add it to the ledger in `test_pex_transition.py`. Checks that protect live behaviour (safety, privacy,
   control surfaces) keep reading the live file. Declaring an edit never switches them off.
5. Use a neutral, versioned entry id (for example `dtgp1` or `hd1`). Order is merge order on `main`. If another entry lands first,
   rebase and regenerate your pairs, checkpoints and fingerprint on top of it. Never edit an entry that is already merged.

## What the proofs check

- Every post-export edit is exact: one altered character, a missing hunk or a duplicated hunk is refused.
- Every entry reproduces its recorded checkpoints, and undoing it lands on the declared state before it.
- Live files are exactly the newest declared state: an undeclared edit to any frozen or chain-pinned file fails.
- Undoing every entry reproduces the 57 `pub0` result hashes byte for byte, and `test_pub0_transition.py` proves `pub0` on that state.
- No post-export hunk and no added file spells a private value.
- The `pub0` module, its manifest and every scope module that existed at the export are byte-identical to the export.
- The pre-export chain record is unchanged, and the `pub0` proof file is hash-pinned after `pex0`.
- The fingerprints are hash-linked back to the `pub0` manifest fingerprint.

## What pex0 changed

`pex0` added the layer and its proofs. It also routed the export-era pins of three older suites through `_pex.as_of_pub0`:

- `test_fallback_recovery_dashboard.py`;
- `test_ecco_fallback_packages.py`;
- `test_ecco_shadow_check_ux.py`.

The routed pins cover:

- the dashboard history and view list;
- the Energy Actions block;
- the manifest's package count and release string;
- the `VERSION.yaml` facts;
- the set of packages that one control-surface pin covers. A package that a post-export entry declares as added is not part of
  it; the package contents are still read live.

The view-list pins kept their live part as a new live check: Fallback / Recovery, Safety and Manual Controls stay consecutive.

Two suites now read their historical baselines through the tree's full chain, so a later declared edit to a chain-pinned file is
undone first:

- `test_fallback_live_match.py`, for its one as-of measurement;
- `test_fbd1_liveness.py`, for its pre-FB-D1 firmware baseline.

`pex0` changed no firmware, Home Assistant package, dashboard, manifest or registry content.

## What esb1 changed

`esb1` builds the Energy Actions card with esbuild 0.28.1 (`registry/tests/_esb1_scope.py`, proofs in
`registry/tests/test_esb1_transition.py`). The bundle's executable code is byte-identical; only its trailing Lit licence block is
regrouped. Its frozen edits are the three enrolled card files and one routing in each of the three suites that pin the card
folder's FB-B3 state: their folder pin now reads a frozen card file as of `pub0` and every other file live, and the pinned value
is unchanged. `test_lic0_transition.py` reads the lic0-era card files the same way; its live licence checks still read the live
files.
