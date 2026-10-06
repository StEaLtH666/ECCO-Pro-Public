"""FB-A (fallback profile schema v1, PR #54) change scope, as a chain entry input.

FB-A is behaviour-free: it ADDED four files and edited nothing that older suites
pin byte-for-byte. Its chain entry therefore has NO reverters at all - an empty
`reverts` map is the machine-checkable statement "FB-A edited none of the
pinned artifacts", and registry/tests/test_scope_chain.py proves it by
reproducing main @ 97450aa's pinned artifacts (== main @ 004040b's) exactly.

This module only names what FB-A added, so that the includers / banned-token
pins in test_fallback_profile_schema.py can be expressed as "FB-A's own files
plus the files later chain entries declare". No I/O.
"""

from __future__ import annotations

BASE_COMMIT = "004040b91b8fb94b783a6fbd40cae610c3316e08"  # main before #54
MERGE_COMMIT = "97450aa"  # main after #54 (merge of PR #54)

HEADER = "firmware/include/ecco_fallback_profile.h"
MODEL = "registry/fallback_profile.py"
TESTS = frozenset({
    "registry/tests/test_fallback_profile_schema.py",
    "registry/tests/test_fallback_profile_host_compile.py",
})
# Files FB-A added that are allowed to name the FB-A header in an include-shaped
# string (the two FB-A suites: the schema suite's scanner regex and the
# host-compile suite's temporary translation unit).
HEADER_INCLUDERS = TESTS
ADDED_FILES = frozenset({HEADER, MODEL, *TESTS})
