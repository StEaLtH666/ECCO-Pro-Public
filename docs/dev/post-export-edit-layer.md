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
- `VERSION.yaml`, which is enrolled because older suites pin its export-era content. The list of enrolled files only grows with
  evidence.

The `pub0` state of a frozen file is its manifest result hash, read from the manifest and never typed by hand.

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

The routed pins cover the dashboard history and view list, the Energy Actions block, the manifest's package count and release
string, and the `VERSION.yaml` facts. `pex0` changed no firmware, Home Assistant package, dashboard, manifest or registry content.
