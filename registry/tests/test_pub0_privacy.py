#!/usr/bin/env python3
"""pub0 public-export privacy proofs: what the PUBLIC EXPORT carries must not identify the owner's site.

SCOPE: the public-export view only. In the private development tree the scanned texts are pub0's in-memory export of every target
(forward()); the private files themselves are never scanned, so private development never fails for containing its own site
configuration. In the public export the scanned texts are the live target files. pub0's own files (the manifest, the tool, its suites)
are scanned as they are in both trees. Files outside pub0's targets are the later curation job's (spec B / gate P1).

  [1] the private device slug / area prefix: only at pub0's declared keep sites (the historical hunk modules + the one literal
      private_view() needs), nowhere else; the personal first name of the attribution sites: exactly once, at the
      ATTRIBUTION_PRIVATE literal (reverter data), nowhere else
  [2] Octopus: no real meter serial / MPAN id; every Octopus id is the placeholder form; no 13-digit value next to an Octopus / MPAN word
  [3] no private (RFC 1918) IPv4 address
  [4] no Windows user-profile path
  [5] no MAC address
  [6] the owner's private pattern file (ECCO_PRIVATE_PATTERNS, never committed) when it is present; a visible notice when it is not
  [7] negative controls: every scanner flags an injected leak of its kind

Test-only, no network. I/O: reads repo files (and the pattern file named by ECCO_PRIVATE_PATTERNS, if set).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import _pub0_scope as P  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def notice(text: str) -> None:
    print(f"  SKIP  {text}")


# ---------------------------------------------------------------------------------------------------------------------------
# The public-export view
# ---------------------------------------------------------------------------------------------------------------------------
VIEW: dict[str, str] = {}
broken = []
for rel in P.TARGETS:
    text = P.read_repo(rel)
    if P.EXPORTED:
        VIEW[rel] = text
    else:
        try:
            VIEW[rel] = P.forward(rel, text)
        except P.Pub0Error as ex:
            broken.append(f"{rel}: {str(ex)[:120]}")
OWN = ("registry/tests/fixtures/pub0_manifest.json", "tools/public/pub0.py", "registry/tests/test_pub0_transition.py",
       "registry/tests/test_pub0_privacy.py", "registry/tests/test_fresh_history_fallback.py")
for rel in OWN:
    VIEW[rel] = P.read_repo(rel)
print(f"  info  scanning the public-export view of {len(P.TARGETS)} pub0 targets + {len(OWN)} pub0 files "
      f"({'live export' if P.EXPORTED else 'in-memory export of the private tree'})")
check("the public-export view could be built for every target (else nothing below proves anything)", not broken, str(broken[:3]))

# The declared keep sites: (path, line, column) -> the token kept there.
KEPT = {}
for f in P.manifest()["files"]:
    for n, _h, sites in f["lines"]:
        for c, k in sites:
            if k in ("keep", "keep_prefix"):
                KEPT[(f["path"], n, c)] = P.PUBLIC_TOKEN[k]

# ---------------------------------------------------------------------------------------------------------------------------
# Scanners (shared by the checks and by the negative controls)
# ---------------------------------------------------------------------------------------------------------------------------
RFC1918 = re.compile(r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d.])")
WIN_USER = re.compile(r"(?i)\b[a-z]:[\\/]{1,2}users[\\/]{1,2}(?!<)[^\\/\s<>\"'`]+")
MAC = re.compile(r"(?i)(?<![0-9a-f:])[0-9a-f]{2}(?::[0-9a-f]{2}){5}(?![0-9a-f:])")
MPAN_NEAR = re.compile(r"(?i)(?:octopus|mpan)[^\n]{0,40}(?<!\d)\d{13}(?!\d)|(?<!\d)\d{13}(?!\d)[^\n]{0,40}mpan")
OCTO_ANY = re.compile(r"octopus_energy_electricity_[a-z0-9_]+")
OCTO_PLACEHOLDER = re.compile(r"octopus_energy_electricity_your_meter_serial_your_(?:import|export)_mpan_")


def prefix_leaks(rel: str, text: str) -> list:
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        for mo in re.finditer(re.escape(P.PRIVATE_AREA_PREFIX), line):
            if (rel, i, mo.start()) not in KEPT:
                out.append((rel, i))
    return out


def octopus_leaks(rel: str, text: str) -> list:
    out = [(rel, "real id") for _ in P.OCTOPUS_ID.finditer(text)]
    out += [(rel, "not a placeholder id") for mo in OCTO_ANY.finditer(text) if not OCTO_PLACEHOLDER.match(text, mo.start())
            and rel not in OWN]
    if rel != P.MANIFEST_REL:   # the manifest is ints, hashes and kind names only (test_pub0_transition.py [0]); its hex is not prose
        out += [(rel, "13-digit value near octopus/mpan") for _ in MPAN_NEAR.finditer(text)]
    return out


def regex_leaks(rx, rel: str, text: str) -> list:
    return [(rel, i) for i, line in enumerate(text.split("\n"), 1) if rx.search(line)]


def scan(fn, view) -> list:
    return [x for rel, t in view.items() for x in fn(rel, t)]


# ===========================================================================
print("[1] the private device slug / area prefix")
# ===========================================================================
leaks = scan(prefix_leaks, VIEW)
check("the private area prefix (and so the private device slug) occurs ONLY at pub0's declared keep sites", not leaks, str(leaks[:5]))
kept_files = sorted({k[0] for k in KEPT})
check("the keep sites are exactly the two generated historical hunk modules and the one literal in _pub0_scope.py",
      kept_files == sorted([*P.KEEP_FILES, P.SELF_REL]) and sum(1 for k in KEPT if k[0] == P.SELF_REL) == 1, str(kept_files))
check("every declared keep site really holds the kept token in the public view (the exemption is not wider than what is there)",
      all(VIEW[rel].split("\n")[n - 1][c:c + len(tok)] == tok for (rel, n, c), tok in KEPT.items()))
non_keep_slug = [rel for rel in P.TARGETS if rel not in P.KEEP_FILES and P.PRIVATE_SLUG in VIEW.get(rel, "")]
check("no target outside the keep files spells the private device slug", not non_keep_slug, str(non_keep_slug))
# The personal first name (kind attribution): reverter data in exactly one literal of _pub0_scope.py (LOW risk, a first name only).
NAME = P.attribution_name()
name_hits = [(rel, i, m.start()) for rel, t in VIEW.items() for i, line in enumerate(t.split("\n"), 1)
             for m in re.finditer(re.escape(NAME), line, re.I)]
_self_lines = VIEW[P.SELF_REL].split("\n")
_decl = [i for i, line in enumerate(_self_lines, 1) if line == f'ATTRIBUTION_PRIVATE = "{P.ATTRIBUTION_PRIVATE}"']
NAME_KEPT = {(P.SELF_REL, _decl[0], len('ATTRIBUTION_PRIVATE = "SmartDeye/')): NAME} if len(_decl) == 1 else {}
check("the personal first name occurs EXACTLY ONCE in the public-export view: inside the ATTRIBUTION_PRIVATE literal of "
      "_pub0_scope.py (reverter data for the root checkpoint of the register map); file / line / column machine-checked",
      len(NAME) >= 2 and len(_decl) == 1 and name_hits == [k for k in NAME_KEPT], f"{len(name_hits)} hit(s) at {[(r, i) for r, i, _c in name_hits]}")
check("the public attribution wording names no person", P.ATTRIBUTION_PUBLIC == "SmartDeye-listed"
      and NAME.lower() not in P.ATTRIBUTION_PUBLIC.lower() and NAME.lower() not in P.manifest()["kinds"]["attribution"]["public"].lower())

# ===========================================================================
print("")
print("[2] Octopus meter serial / MPAN")
# ===========================================================================
o = scan(octopus_leaks, VIEW)
check("no real Octopus serial / MPAN id, no non-placeholder Octopus id, no 13-digit value next to an Octopus / MPAN word", not o, str(o[:5]))
octo_ids = [mo.group(0) for rel in P.OCTOPUS_FILES for mo in OCTO_ANY.finditer(VIEW.get(rel, ""))]
check("the Octopus file still names its tariff entities, all in the placeholder form (your_meter_serial / your_import_mpan / "
      "your_export_mpan)", len(octo_ids) >= 40 and all(OCTO_PLACEHOLDER.match(i) for i in octo_ids), str(len(octo_ids)))

# ===========================================================================
print("")
print("[3] [4] [5] network addresses, user paths, MAC addresses")
# ===========================================================================
for label, rx in (("private (RFC 1918) IPv4 address", RFC1918), ("Windows user-profile path", WIN_USER), ("MAC address", MAC)):
    hits = scan(lambda rel, t, rx=rx: regex_leaks(rx, rel, t), VIEW)
    check(f"no {label} in the public-export view", not hits, str(hits[:5]))

# ===========================================================================
print("")
print("[6] the owner's private pattern file")
# ===========================================================================
pat_file = os.environ.get("ECCO_PRIVATE_PATTERNS", "")
if not pat_file:
    notice("ECCO_PRIVATE_PATTERNS is not set: the owner's private literal patterns were NOT applied (gate P1 needs them)")
elif not Path(pat_file).is_file():
    check("ECCO_PRIVATE_PATTERNS names a readable file", False, "(path not shown)")
else:
    pats = [ln.strip() for ln in Path(pat_file).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]

    def masked(rel: str, text: str) -> str:
        """The view with exactly the declared keep sites blanked (the exemption [1] proved), so an owner pattern for the slug still
        catches every OTHER occurrence."""
        lines = text.split("\n")
        for (r, n, c), tok in {**KEPT, **NAME_KEPT}.items():
            if r == rel:
                lines[n - 1] = lines[n - 1][:c] + " " * len(tok) + lines[n - 1][c + len(tok):]
        return "\n".join(lines)

    MASKED = {rel: masked(rel, t) for rel, t in VIEW.items()}
    bad_rx, hits = [], []
    for idx, p in enumerate(pats, 1):
        try:
            rx = re.compile(p)
        except re.error:
            bad_rx.append(idx)
            continue
        hits += [(idx, rel) for rel, t in MASKED.items() if rx.search(t)]
    check(f"every owner pattern compiles ({len(pats)} patterns; the patterns themselves are never printed)", not bad_rx, str(bad_rx))
    check("no owner pattern matches the public-export view outside pub0's declared keep sites (pattern index, file)", not hits, str(hits[:5]))

# ===========================================================================
print("")
print("[7] negative controls (every scanner flags an injected leak of its kind)")
# ===========================================================================
SAMPLE = "home-assistant/packages/ecco_runtime_config.yaml"
base = VIEW.get(SAMPLE, "")
fake_mpan = "9" * 13
injected = {
    "private slug": (prefix_leaks, f"\n# sensor.{P.PRIVATE_SLUG}_x\n"),
    "bare private prefix": (prefix_leaks, f"\n# {P.PRIVATE_AREA_PREFIX}other\n"),
    "real-shaped Octopus id": (octopus_leaks, f"\n# sensor.octopus_energy_electricity_{'12a' + '3' * 7}_{fake_mpan}_current_rate\n"),
    "MPAN next to the word": (octopus_leaks, f"\n# import MPAN {fake_mpan}\n"),
    "RFC 1918 address": (lambda r, t: regex_leaks(RFC1918, r, t), "\n# " + ".".join(["192", "168", "1", "20"]) + "\n"),
    "Windows user path": (lambda r, t: regex_leaks(WIN_USER, r, t), "\n# C:" + "\\" + "Users" + "\\" + "someone\\x\n"),
    "MAC address": (lambda r, t: regex_leaks(MAC, r, t), "\n# " + ":".join(["aa", "bb", "cc", "dd", "ee", "ff"]) + "\n"),
    "personal first name": (lambda r, t: [(r, i) for i, line in enumerate(t.split("\n"), 1) if NAME.lower() in line.lower()],
                            "\n# listed by " + NAME.upper() + "\n"),
}
for label, (fn, extra) in injected.items():
    check(f"control: the clean sample is clean and an injected {label} is flagged", base != "" and not fn(SAMPLE, base) and bool(fn(SAMPLE, base + extra)))
check("control: a placeholder in a doc-style example path is not a user path, a version string is not an address",
      not regex_leaks(WIN_USER, SAMPLE, "C:/Users/<WINDOWS_USER>/.ssh/x") and not regex_leaks(RFC1918, SAMPLE, "v10.1.2.3.4 or 2026.10.1.2"))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All pub0 public-export privacy checks passed.")
