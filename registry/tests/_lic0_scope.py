"""lic0 - PUBLIC-RELEASE LICENCE ALIGNMENT (v0.9.0) as ONE declared, exact, reversible transition.

WHY. The project is released under GPL-3.0-or-later and its bundled third-party code must keep its licence notices
(docs/public-release spec E.2/E.3). The Energy Actions card declared MIT and its bundle was built with
`legalComments: "none"`, which strips Lit's BSD-3-Clause notices. Three older suites pin that card's folder (one sha256 over every
Git-tracked file: test_ecco_fallback_packages [19], test_ecco_shadow_check_ux [20], test_fallback_recovery_dashboard FB-B3), and
re-hashing a pin is forbidden (_scope_chain.py). So the alignment is a declared transition: every edit is listed here, applied
exactly, and undone exactly for those pins, which therefore stay byte-for-byte what they were.

WHAT lic0 CHANGES (the complete list; all in frontend/ecco-energy-actions-card/):
  build.mjs           legalComments: "none" -> "eof" (esbuild keeps the bundled packages' licence comments at the end of the file)
  dist/ecco-energy-actions-card.js
                      rebuilt from the UNCHANGED source with that one option: the bytes before the end are IDENTICAL to the
                      previous bundle, followed by ONE appended legal-comment block (DIST_BLOCK_LEN bytes, DIST_BLOCK_SHA256,
                      Lit's BSD-3-Clause notices only). Proved by test_lic0_transition.py, which also re-derives the old bundle.
  package.json        "license": "MIT" -> "GPL-3.0-or-later"
  package-lock.json   the ROOT package's "license" (packages[""]) only; no dependency licence is touched
  README.md           the License section
Nothing else: no source file, no test, no example, no behaviour. The firmware, the HA packages and every chain-pinned artifact are
untouched, so the chain Entry (_scope_chain.LIC0) has no reverter, no checkpoint and zero deltas, like fbc3.

pre_lic0_bytes(rel, data) is what an older folder pin hashes (after pub0's private_view_bytes): the identity for every file lic0 does
not touch; for the five files above, the exact pre-lic0 bytes. It raises unless every declared edit is present exactly once and
the appended block is exactly the declared one - so any OTHER change still breaks the pins that use it.

Both the private development tree and the public export carry lic0 (a real change of the release, not an export sanitisation).
No I/O.
"""

from __future__ import annotations

import hashlib

CARD = "frontend/ecco-energy-actions-card/"
DIST = CARD + "dist/ecco-energy-actions-card.js"

# The bundle before lic0 (legalComments "none"; main @ 87e6151, the FB-B3 pins) and after it, LF bytes.
DIST_PRE_SHA256 = "62760742b2fdc27b6249d67832777b2edf333701e23b8d0aa228b081477e00a4"
DIST_POST_SHA256 = "c1bd37deb0dab7ad1933e5276e70388643b14b55ed57842f055eadfb1933c207"
DIST_BLOCK_LEN = 2193
DIST_BLOCK_SHA256 = "e3599891f1197529df78235648a1b241f4d64b2d0fb51e888b2109e621138ca3"
DIST_BLOCK_HEAD = b"/*! Bundled license information:\n"

README_PRE = "MIT (see `package.json`).\n"
README_POST = ("GPL-3.0-or-later, the licence of the ECCO-Pro project (see the repository's `LICENSE` file).\n"
               "\n"
               "The built file `dist/ecco-energy-actions-card.js` also contains the Lit library (BSD-3-Clause, Copyright 2017\n"
               "Google LLC). Its licence notices are kept at the end of that file, and the full Lit licence text is in\n"
               "`frontend/LIT-LICENSE.txt`.\n")

# rel -> [(text before lic0, text after lic0)], each present exactly once in its file.
TEXT_EDITS: dict = {
    CARD + "build.mjs": [('  legalComments: "none",\n', '  legalComments: "eof",\n')],
    CARD + "package.json": [('  "license": "MIT",\n', '  "license": "GPL-3.0-or-later",\n')],
    CARD + "package-lock.json": [('      "name": "ecco-energy-actions-card",\n      "version": "0.1.0",\n      "license": "MIT",\n',
                                  '      "name": "ecco-energy-actions-card",\n      "version": "0.1.0",\n      "license": "GPL-3.0-or-later",\n')],
    CARD + "README.md": [("## License\n\n" + README_PRE, "## License\n\n" + README_POST)],
}
TARGETS = tuple(sorted([*TEXT_EDITS, DIST]))


class Lic0Error(AssertionError):
    """A declared lic0 edit is absent, altered or duplicated (a failed proof, never a skipped one)."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_dist_block(data: bytes) -> bytes:
    """The bundle before lic0: the declared appended block removed (it must be exactly that block)."""
    if len(data) <= DIST_BLOCK_LEN:
        raise Lic0Error(f"lic0 {DIST}: shorter than the declared licence block")
    head, block = data[:-DIST_BLOCK_LEN], data[-DIST_BLOCK_LEN:]
    if not block.startswith(DIST_BLOCK_HEAD) or sha(block) != DIST_BLOCK_SHA256:
        raise Lic0Error(f"lic0 {DIST}: the end of the bundle is not the declared licence block")
    if DIST_BLOCK_HEAD in head:
        raise Lic0Error(f"lic0 {DIST}: a second licence block precedes the declared one")
    return head


def pre_lic0_bytes(rel: str, data: bytes) -> bytes:
    """`data` (LF bytes of `rel`) exactly as it was before lic0; the identity for every file lic0 does not touch."""
    if rel == DIST:
        return strip_dist_block(data)
    if rel not in TEXT_EDITS:
        return data
    text = data.decode("utf-8")
    for before, after in TEXT_EDITS[rel]:
        if text.count(after) != 1:
            raise Lic0Error(f"lic0 {rel}: the declared edit is present {text.count(after)} times (exactly once is declared)")
        text = text.replace(after, before)
    return text.encode("utf-8")


def post_lic0_bytes(rel: str, data: bytes, block: bytes) -> bytes:
    """The forward direction (used by the transition suite's round trip): `block` is the appended licence block."""
    if rel == DIST:
        if sha(block) != DIST_BLOCK_SHA256:
            raise Lic0Error("lic0: not the declared licence block")
        return data + block
    if rel not in TEXT_EDITS:
        return data
    text = data.decode("utf-8")
    for before, after in TEXT_EDITS[rel]:
        if text.count(before) != 1:
            raise Lic0Error(f"lic0 {rel}: the pre-lic0 text is present {text.count(before)} times (exactly once is declared)")
        text = text.replace(before, after)
    return text.encode("utf-8")
