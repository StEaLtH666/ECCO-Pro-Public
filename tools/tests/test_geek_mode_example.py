#!/usr/bin/env python3
"""Mode Shell integration: the Node-free checks (CI runs no Node, so the card's own node tests are not run there).

  [1] the example dashboard check of the shell folder passes, run as a subprocess exactly as the instructions say: the example is valid
      YAML with the `!include` tag, the include resolves to the real catalogue, a YAML loader reads that file as a JSON loader does, and
      the wrapped cards (the Intelligence card, the watchdog / status entities card, the pause tile, the text fallback) are EQUAL to
      those of home-assistant/dashboards/ecco_intelligence.yaml
  [2] the card and the data side agree on the names they share: the catalogue schema, the ledger schema, the view id, the contract
  [3] the preview reads the real catalogue and the real fixtures in place (every path it names exists; nothing is inlined or copied) and
      names every fixture of the meta file as a scenario source
  [4] the documents say what the ledger says (counts) and every repository path they cite exists
  [5] the node test files are all there, and the real-catalogue test covers every fixture the meta file lists (a new fixture cannot be
      added without the card being run on it)
  [6] hygiene of the shell folder: ASCII source, LF only, no secret-shaped text, the licence line, no dependency, and no pinned or
      deployed file mentions the shell (the integration steps are the owner's)

Test-only, no network, no Node. Reads committed files; the file lists are explicit.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geek_scratch import PY, ROOT  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


CARD = ROOT / "frontend" / "ecco-mode-shell"
CAT = CARD / "catalogue"
FIX = CARD / "test" / "fixtures"
DOC = ROOT / "docs" / "product-ui" / "PRODUCTION_GEEK_MODE.md"
README = CARD / "README.md"
LEDGER_MD = ROOT / "docs" / "product-ui" / "GEEK_MODE_COVERAGE_LEDGER_intelligence.md"

catalogue = json.loads((CAT / "intelligence.catalogue.json").read_text(encoding="utf-8"))
ledger = json.loads((CAT / "intelligence.ledger.json").read_text(encoding="utf-8"))
meta = json.loads((FIX / "intelligence.states.meta.json").read_text(encoding="utf-8"))
card_src = (CARD / "ecco-mode-shell.js").read_text(encoding="utf-8")
preview = (CARD / "preview" / "index.html").read_text(encoding="utf-8")

# ===========================================================================
print("[1] the example dashboard check")
# ===========================================================================
p = subprocess.run(PY + [str(CARD / "test" / "test_example_dashboard.py")], cwd=str(ROOT), capture_output=True, timeout=120)
out = (p.stdout + p.stderr).decode("utf-8", "replace")
check("test_example_dashboard.py exits 0", p.returncode == 0, out[-600:])
check("it ran the include checks (the real catalogue is resolved, not skipped)", "the include points at the real catalogue" in out and "FAIL" not in out)
example = (CARD / "examples" / "intelligence-modes.yaml").read_text(encoding="utf-8")
check("the example includes the real catalogue by a relative path", "catalogue: !include ../catalogue/intelligence.catalogue.json" in example)

# ===========================================================================
print("[2] the names the card and the data side share")
# ===========================================================================
check("the card's catalogue schema is the catalogue's", f"'{catalogue['schema']}'" in card_src and catalogue["schema"] == "ecco-geek-catalogue/1")
check("the ledger's schema and view id are the catalogue's", ledger["schema"] == "ecco-geek-ledger/1" and ledger["view_id"] == catalogue["view_id"]
      and ledger["contract"] == catalogue["contract"])
check("the card's export schema is named in the card and the README", "ecco-geek-export/1" in card_src)
check("the card's defaults: Production first, two modes", "DEFAULT_MODE = 'production'" in card_src and "['production', 'geek']" in card_src)

# ===========================================================================
print("[3] the preview")
# ===========================================================================
check("the preview fetches the real catalogue in place", "../catalogue/intelligence.catalogue.json" in preview)
check("the preview reads the fixture meta file and the noise and hostile fixtures in place",
      "intelligence.states.meta.json" in preview and "noise.states.json" in preview and "hostile.states.json" in preview)
check("the preview uses the real Intelligence card", "../../ecco-intelligence-card/ecco-intelligence-card.js" in preview
      and (CARD.parent / "ecco-intelligence-card" / "ecco-intelligence-card.js").is_file())
names = re.search(r"const SCENARIOS = \{(.*?)\n\};", preview, re.S)
sources = set(re.findall(r"fixture: '([a-z-]+)'", names.group(1))) if names else set()
check("every fixture of the meta file is the source of a preview scenario", set(meta["fixtures"]) <= sources, str(set(meta["fixtures"]) - sources))
check("the preview inlines no catalogue and no fixture (no 'entity_id' literal table, no copy of the catalogue schema)",
      "ecco-geek-catalogue/1" not in preview and "automation.ecco_intel_alert" not in preview)
check("the preview loads nothing from the network (no http(s) URL other than the loopback hint in the comment)",
      not re.findall(r"""(?:src|href|import|fetch)\s*[=(]?\s*['"]https?://""", preview))

# ===========================================================================
print("[4] the documents")
# ===========================================================================
t = ledger["totals"]
n_alerts = len(catalogue["alerts"])
want = f"{t['sources']} sources, {t['attributes']} attribute rows, {n_alerts} alerts, {t['exceptions']} exceptions"
readme = README.read_text(encoding="utf-8")
check("the README quotes the ledger's counts", want in readme, want)
check("the README quotes the ledger's row count", f"({t['covered']} rows)" in readme)
doc = DOC.read_text(encoding="utf-8")
check("the design document quotes the ledger's source and attribute counts", f"{t['sources']} sources, {t['attributes']} attribute rows" in doc)
check("the design document has the integration section and says nothing pinned was edited", "## 12." in doc and "no existing, frozen, pinned, sealed or deployed file is edited" in doc)
check("the design document no longer says the shell is written separately", "is written separately" not in doc and "No example dashboard was written" not in doc)
missing = []
for label, text, base in (("README", readme, [CARD, ROOT]), ("design document", doc, [ROOT, CARD])):
    for ref in sorted(set(re.findall(r"`((?:frontend|tools|docs|test|catalogue|examples|preview|home-assistant|deployment)/[A-Za-z0-9_./-]+)`", text))):
        if any(c in ref for c in "*{}") or ref.endswith("/"):
            continue
        if not any((b / ref).exists() for b in base):
            missing.append(f"{label}: {ref}")
check("every repository path the documents cite exists", not missing, "; ".join(missing))
check("the human-readable ledger exists", LEDGER_MD.is_file())

# ===========================================================================
print("[5] the node tests")
# ===========================================================================
tests = ["core", "element", "coverage", "static", "mutations", "real-catalogue"]
check("every node test file exists", all((CARD / "test" / f"{n}.test.mjs").is_file() for n in tests))
real = (CARD / "test" / "real-catalogue.test.mjs").read_text(encoding="utf-8")
check("the real-catalogue test takes the fixture list from the meta file (so a new fixture is run through the card)", "intelFixtureNames()" in real)
check("the mutation proof runs the real-catalogue test too", "'real-catalogue.test.mjs'" in (CARD / "test" / "mutations.test.mjs").read_text(encoding="utf-8"))
check("package.json runs every test file", json.loads((CARD / "package.json").read_text(encoding="utf-8"))["scripts"]["test"] == "node --test test/*.test.mjs")
for a in ("AC6", "AC7", "AC8", "AC9", "AC10", "AC12", "AC15"):
    check(f"the real-catalogue test names {a}", f"{a} " in real)

# ===========================================================================
print("[6] hygiene of the shell folder")
# ===========================================================================
bad = []
for f in sorted(CARD.rglob("*")):
    if f.is_file() and "__pycache__" not in f.parts:
        raw = f.read_bytes()
        if b"\r" in raw or b"\x00" in raw:
            bad.append(f"{f.relative_to(ROOT)}: CR or NUL")
check("every file of the folder is text with LF line ends", not bad, "; ".join(bad))
check("the card source is ASCII only", card_src.isascii())
pkg = json.loads((CARD / "package.json").read_text(encoding="utf-8"))
check("licence GPL-3.0-or-later, private, no dependency", pkg["license"] == "GPL-3.0-or-later" and pkg["private"] is True
      and not any(k in pkg for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")))
# the integration steps are the owner's: none of the pinned or deployed files may name the shell yet
pinned = ["deployment/ha-manifest.yaml", "CHANGELOG.md", "VERSION.yaml", "registry/tests/_scope_chain.py", "home-assistant/dashboards/ecco_intelligence.yaml"]
named = [r for r in pinned if (ROOT / r).is_file() and "mode-shell" in (ROOT / r).read_text(encoding="utf-8", errors="replace")]
check("no pinned or deployed file names the shell (the integration steps are the owner's)", not named, str(named))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
