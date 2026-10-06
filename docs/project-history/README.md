# Project history

ECCO-Pro was developed in a private repository before its first public release. That development history (commit history,
handovers, live-proof logs, implementation notes, internal audits and design drafts) is kept in a private archive and is not
part of this repository. It contains site-specific and personal data that cannot be published.

What this means for readers:

- Comments and test names sometimes mention private records (for example `CURRENT_STATE.md`, `CHANGELOG.md` entries, PR or task
  numbers, "LP" live-proof labels, or an `..._IMPLEMENTATION_NOTES.md` file). Those references are historical. Where a path is
  required by the offline proof chain, a short placeholder file explains that the record is kept privately.
- Some optional git cross-checks in the test suites compare against private commits. In this repository they report SKIP; the
  chain-derived proofs (`registry/tests/_scope_chain.py`) remain and are the primary evidence.
- "Hardware tested" and "live proven" statements refer to supervised tests on the reference installation; see
  [SUPPORTED_HARDWARE.md](../../SUPPORTED_HARDWARE.md) for what that does and does not mean.
