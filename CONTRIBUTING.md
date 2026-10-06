# Contributing to ECCO-Pro

Thank you for considering a contribution. ECCO-Pro writes settings to battery inverters, so changes are reviewed with that in
mind: small, narrowly scoped pull requests with clear evidence are reviewed fastest. Participation is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Licence of contributions

ECCO-Pro is licensed under the GNU General Public License, version 3 or (at your option) any later version
(`GPL-3.0-or-later`, see [LICENSE](LICENSE)). By submitting a contribution you agree that it is licensed under the same terms
(inbound = outbound). There is no contributor licence agreement (CLA).

## Developer Certificate of Origin (sign-off required)

Every commit in a pull request must be signed off under the [Developer Certificate of Origin 1.1](https://developercertificate.org/)
(DCO). By adding a sign-off you certify, as the DCO states, that you wrote the contribution or otherwise have the right to submit
it under the project's open-source licence. Sign off with `git commit -s`, which adds a line of this form, using your real name
or a consistent public identity and an address you are happy to publish (a GitHub no-reply address is fine):

```
Signed-off-by: Your Name <you@users.noreply.github.com>
```

To sign off commits you already made: `git commit --amend -s` (last commit) or `git rebase --signoff main` (a branch).
Pull requests without a sign-off on every commit are not merged. The sign-off is checked in review; there is no bot yet.

You are responsible for the provenance of what you submit. Do not submit vendor documents, text or tables copied from them, or
code from other projects unless its licence is compatible and the attribution is included. This applies equally to text or code
produced with AI tools.

## Safety-critical areas

Changes to any of these get stricter review and may be slow by design:

- which inverter registers can be written (the write surface), register meanings, bounds and the capability registry
  (`registry/inverter_capabilities.yaml`);
- transaction sequencing (read, stage, arm, write, read back, verify, restore), durable records and recovery;
- ownership / arbitration between features;
- RTC correction, export control, grid charging and discharge behaviour;
- the battery reserve and anything that plans or permits discharge.

**Adding or widening a writable register needs agreement in an issue before code is written.** A pull request in these areas
must state:

- what can write, which registers, under which conditions;
- how a failure behaves and how the original state is restored;
- the evidence level: *offline only*, *hardware tested* (inverter model, every firmware string, controller board, ESPHome
  version) or *production proven* (see [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md)). CI passing is **not** hardware evidence.

Never test a write path on a system whose configuration you have not backed up (see [SAFETY.md](SAFETY.md)).

## Running the checks locally

- Python 3.12 with the packages in `requirements-ci.txt` (PyYAML, Jinja2).
- `python tools/validate_repo.py`: YAML, Python, JSON, Flux and manifest references.
- `python tools/run_offline_tests.py --all` (add `--parallel N` to use more cores): every offline suite under the roots listed in
  `tools/offline_test_roots.txt` (the one list CI reads too). Each suite is also a plain script: `python path/to/test_x.py`.
- Some suites compile the firmware headers with a host C++ compiler (set `ECCO_CXX` to a native `g++`); they are slow.
- Firmware: ESPHome **2026.8.x** (`esphome config` / `esphome compile` with your own `firmware/secrets.yaml`, see
  `firmware/secrets.yaml.example`).
- Cards: `npm ci && npm test` in `frontend/ecco-energy-actions-card` and `frontend/ecco-energy-flow-card`
  (`npm run typecheck`, `npm run build` too), and `npm test` in `frontend/ecco-fallback-recovery-card` (no dependencies). CI does
  not run the card tests yet (a planned post-0.9.0 improvement); run them locally when you change a card.

## The proof chain (pinned artifacts)

Many artifacts (the firmware YAML and headers, the capability registry, the dashboard, parts of the Home Assistant packages and
of the frontend) are pinned by sha256 and by exact-match "reverters" in `registry/tests/_scope_chain.py` and the `_*_scope.py`
modules. A change to a pinned artifact must be declared as a new chain entry with exact reverters and new checkpoints. **Never
re-hash an older pin to make a test pass.** If a suite fails because a pin moved, that is the suite doing its job.

The public tree was produced from the private development tree by one declared, reversible transition, `pub0`
(`registry/tests/_pub0_scope.py`, `tools/public/pub0.py`). Its manifest is generated and must not be hand-edited.

## Privacy

Examples, tests and issues must use placeholders. Never commit or paste secrets, serial numbers, tariff / meter / MPAN /
account identifiers, IP or MAC addresses, locations, personal paths or household telemetry. Site-specific values belong in the
git-ignored `ecco_site.local.yaml` (see `ecco_site.example.yaml` and `tools/ecco_site_render.py`).
`tools/tests/test_public_privacy.py` scans every tracked file.

## Pull requests

Use the pull request template. Keep one concern per pull request, update the docs and `SUPPORTED_HARDWARE.md` where behaviour
or evidence changes, and expect review questions about failure and restore paths.
