#!/usr/bin/env python3
"""Public-tree privacy and secret scan: no file the public repository tracks may identify a site, a person or a secret.

SCOPE: every git-tracked text file. In the public export the files are scanned as they are. In the private development tree the
pub0 targets are scanned in their pub0 export form (_pub0_scope.forward), every other tracked file as it is - i.e. exactly what
the export would publish (PUBLIC_RELEASE_BUILD_SPEC C.3 6a, gates P0-P2).

  [1] the private area prefix appears exactly once in the whole tree: the one declared keep_prefix literal of _pub0_scope.py;
      the personal first name of the register-map attribution likewise, at the one declared ATTRIBUTION_PRIVATE literal
  [2] Octopus Energy: no real meter serial / MPAN id; no 13-digit run on a line that names an MPAN / meter / Octopus id
  [3] no private (RFC 1918) IPv4 address, no MAC address
  [4] no user-profile path (Windows C:\\Users\\<name>, MSYS /c/Users/<name>, macOS /Users/<name>)
  [5] no e-mail address except no-reply / example addresses
  [6] secrets: no private-key block, no well-known token shape, no tracked secrets file; every firmware `!secret` key is in
      firmware/secrets.yaml.example with a placeholder value
  [7] curation: no private-history file (handover, live-proof, CURRENT_STATE, implementation notes, superseded dashboards ...)
  [8] the owner's private pattern file (ECCO_PRIVATE_PATTERNS, never committed) when it is set; a visible notice when it is not
  [9] negative controls: every scanner flags an injected leak of its kind

Test-only, no network. I/O: git ls-files, reads tracked files (and the pattern file named by ECCO_PRIVATE_PATTERNS, if set).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _pub0_scope as P  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ---------------------------------------------------------------------------------------------------------------------------
# The public view of the tracked tree
# ---------------------------------------------------------------------------------------------------------------------------
ls = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True)
TRACKED = sorted(f for f in ls.stdout.decode("utf-8").split("\0") if f) if ls.returncode == 0 else []
check("the tracked file list could be read (git ls-files)", bool(TRACKED), ls.stderr.decode("utf-8", "replace")[:200])
VIEW: dict[str, str] = {}
BINARY: list[str] = []
for rel in TRACKED:
    p = ROOT / rel
    if not p.is_file():
        continue
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        BINARY.append(rel)
        continue
    if not P.EXPORTED and P.is_target(rel):
        text = P.forward(rel, text.replace("\r\n", "\n"))
    VIEW[rel] = text
print(f"  info  {len(VIEW)} tracked text files scanned ({'public export' if P.EXPORTED else 'pub0 export view of the private tree'}), "
      f"{len(BINARY)} binary: {BINARY or 'none'}")
check("the tree tracks no binary file (nothing that cannot be scanned)", not BINARY, str(BINARY))

# ---------------------------------------------------------------------------------------------------------------------------
# Scanners (shared by the checks and the negative controls); each returns [(rel, line, excerpt)]
# ---------------------------------------------------------------------------------------------------------------------------
OCTO_REAL = re.compile(r"octopus_energy_electricity_[0-9]{2}[a-z][0-9]{7}_[0-9]{13}")
THIRTEEN = re.compile(r"(?<![0-9])[0-9]{13}(?![0-9])")
MPAN_WORD = re.compile(r"mpan|meter|octopus|mprn", re.I)
RFC1918 = re.compile(r"(?<![0-9.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![0-9.])")
MAC = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")
USER_PATH = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}(?!<)[^\\/\s'\"<>]+|/[cC]/Users/[^/\s'\"<>]+|(?<![A-Za-z])/Users/[a-z][^/\s'\"<>]*/")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"(@users\.noreply\.github\.com|^noreply@anthropic\.com|@example\.(com|org|net)|\.(invalid|test|example|localhost))$", re.I)
SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}|\bAKIA[0-9A-Z]{16}\b"
                    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bsk-[A-Za-z0-9]{32,}|\bsk-ant-[A-Za-z0-9_-]{20,}"
                    r"|eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")
SECRET_FILE = re.compile(r"(^|/)(secrets\.yaml|\.env(\..*)?|.*\.(pem|key|p12|pfx)|id_rsa.*|ecco_site\.local\.yaml|.*_private\.yaml)$")
HISTORY_FILE = re.compile(r"(^|/)(CURRENT_STATE\.md|HANDOVER_[^/]*|[^/]*LIVE_PROOF[^/]*|SAFE_TRANSACTION_ENGINE_AUDIT[^/]*"
                          r"|FB_[A-Z0-9]+_(IMPLEMENTATION_NOTES|HA_SLICE_NOTES)\.md|FINAL_FBB_FBC_ARCHITECTURE\.md|S\d_[a-z_]+_(draft|redteam)\.md"
                          r"|ECCO_2026_FEATURE_BOARD\.md|SMARTDEYE_[^/]*|smartdeye-[^/]*|ecco_pro_dashboard_v7_[^/]*|generate_dashboard_v7_[^/]*"
                          r"|PUBLIC_RELEASE_BUILD_SPEC\.md)$")


def scan(view: dict, pattern: re.Pattern, ok=None, line_filter=None) -> list:
    hits = []
    for rel, text in view.items():
        for i, line in enumerate(text.split("\n"), 1):
            if line_filter is not None and not line_filter(line):
                continue
            for m in pattern.finditer(line):
                if ok is not None and ok(rel, line, m):
                    continue
                hits.append((rel, i, line[max(0, m.start() - 20):m.end() + 20].strip()))
    return hits


def scan_prefix(view: dict) -> list:
    return [(rel, i, line.strip()[:80]) for rel, text in view.items() for i, line in enumerate(text.split("\n"), 1)
            for _ in range(line.count(P.PRIVATE_AREA_PREFIX))]


def scan_thirteen(view: dict) -> list:
    return scan(view, THIRTEEN, line_filter=lambda line: bool(MPAN_WORD.search(line)))


def scan_email(view: dict) -> list:
    return scan(view, EMAIL, ok=lambda rel, line, m: bool(EMAIL_OK.search(m.group(0))))


def scan_secret_files(rels) -> list:
    return [r for r in rels if SECRET_FILE.search(r)]


STUB_MARKER = "<!-- ecco:private-archive-stub -->"


def is_archive_stub(rel: str, view: dict) -> bool:
    """A history-named path kept only because the proof chain declares it: a short placeholder that says so, nothing else."""
    text = view.get(rel, "")
    return (rel.startswith("docs/architecture/fallback/") and text.startswith(STUB_MARKER + "\n") and len(text) < 900
            and "private development archive and is not" in text and text.count("\n") <= 9)


def scan_history_files(rels, view: dict | None = None) -> list:
    return [r for r in rels if HISTORY_FILE.search(r) and not (view is not None and is_archive_stub(r, view))]


def _masked(hits):
    return [(r, i) for r, i, _x in hits][:8]      # never print a matched value: file and line only


# ===========================================================================
print("")
print("[1] the private area prefix")
# ===========================================================================
prefix_hits = scan_prefix(VIEW)
declared = [(rel, i) for rel, i, line in prefix_hits if rel == P.SELF_REL and line.startswith('PRIVATE_AREA_PREFIX = "')]
check("the private area prefix occurs exactly ONCE in the whole public tree, at the declared keep_prefix literal of _pub0_scope.py "
      "(the proof chain needs it to rebuild the private text; the historical hunk modules bind it, they do not spell it)",
      len(prefix_hits) == 1 and len(declared) == 1, str(_masked(prefix_hits)))
NAME = P.attribution_name()


def scan_name(view: dict) -> list:
    return [(rel, i, line.strip()[:80]) for rel, text in view.items() for i, line in enumerate(text.split("\n"), 1)
            for _ in range(line.lower().count(NAME.lower()))]


name_hits = scan_name(VIEW)
name_declared = [(rel, i) for rel, i, line in name_hits if rel == P.SELF_REL and line == f'ATTRIBUTION_PRIVATE = "{P.ATTRIBUTION_PRIVATE}"']
check("the personal first name of the register-map attribution occurs exactly ONCE in the whole public tree, at the declared "
      "ATTRIBUTION_PRIVATE literal of _pub0_scope.py (reverter data for the register map's root checkpoint; LOW risk, a first name only)",
      len(NAME) >= 2 and len(name_hits) == 1 and len(name_declared) == 1, str(_masked(name_hits)))

# ===========================================================================
print("")
print("[2] Octopus Energy identifiers")
# ===========================================================================
check("no real Octopus meter serial / MPAN entity id", not scan(VIEW, OCTO_REAL), str(_masked(scan(VIEW, OCTO_REAL))))
check("no 13-digit run on a line that names an MPAN / meter / Octopus id", not scan_thirteen(VIEW), str(_masked(scan_thirteen(VIEW))))

# ===========================================================================
print("")
print("[3] network identifiers")
# ===========================================================================
check("no private (RFC 1918) IPv4 address", not scan(VIEW, RFC1918), str(_masked(scan(VIEW, RFC1918))))
check("no MAC address", not scan(VIEW, MAC), str(_masked(scan(VIEW, MAC))))

# ===========================================================================
print("")
print("[4] user-profile paths")
# ===========================================================================
check("no user-profile path (C:\\Users\\<name>, /c/Users/<name>, /Users/<name>/)", not scan(VIEW, USER_PATH), str(_masked(scan(VIEW, USER_PATH))))

# ===========================================================================
print("")
print("[5] e-mail addresses")
# ===========================================================================
check("no e-mail address except no-reply / example ones", not scan_email(VIEW), str(_masked(scan_email(VIEW))))

# ===========================================================================
print("")
print("[6] secrets")
# ===========================================================================
check("no private-key block or well-known token shape (GitHub, AWS, Slack, OpenAI/Anthropic, JWT)", not scan(VIEW, SECRET),
      str(_masked(scan(VIEW, SECRET))))
check("no secrets / local-site / private file is tracked (secrets.yaml, .env, keys, ecco_site.local.yaml, *_private.yaml)",
      not scan_secret_files(TRACKED), str(scan_secret_files(TRACKED)))
example = VIEW.get("firmware/secrets.yaml.example", "")
ex_keys = dict(re.findall(r"^([a-z_]+):\s*\"([^\"]*)\"", example, re.M))
used = sorted({k for rel, t in VIEW.items() if rel.startswith("firmware/") and rel.endswith(".yaml") for k in re.findall(r"!secret ([a-z_]+)", t)})
check("every firmware `!secret` key is in firmware/secrets.yaml.example, each with an obvious placeholder value",
      bool(used) and all(k in ex_keys for k in used) and all(re.match(r"^(your-|replace-with-)", ex_keys[k]) for k in used),
      f"used={used} example={sorted(ex_keys)}")

# ===========================================================================
print("")
print("[7] curation: no private-history file")
# ===========================================================================
check("no private-history / superseded file is tracked (handovers, live proofs, CURRENT_STATE, implementation notes, drafts, "
      "superseded v7 dashboards and generators, the release build spec); a history-named path is allowed ONLY as a short "
      "private-archive placeholder that the proof chain requires", not scan_history_files(TRACKED, VIEW), str(scan_history_files(TRACKED, VIEW)))
stubs = [r for r in TRACKED if HISTORY_FILE.search(r) and is_archive_stub(r, VIEW)]
print(f"  info  private-archive placeholders (declared by the proof chain): {stubs or 'none'}")

# ===========================================================================
print("")
print("[8] the owner's private pattern file")
# ===========================================================================
pat_file = os.environ.get("ECCO_PRIVATE_PATTERNS")
if pat_file:
    try:
        pats = [ln.strip() for ln in Path(pat_file).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    except OSError as ex:
        pats = None
        check("ECCO_PRIVATE_PATTERNS is readable", False, str(ex))
    if pats is not None:
        hits = []
        for k, pat in enumerate(pats):
            n = sum(t.lower().count(pat.lower()) for rel, t in VIEW.items()
                    if not (pat == P.PRIVATE_AREA_PREFIX and rel == P.SELF_REL))
            if pat.lower() == NAME.lower() and len(name_declared) == 1:
                n -= 1      # the one declared ATTRIBUTION_PRIVATE literal ([1] proves it is the only occurrence)
            if n:
                hits.append(f"pattern #{k + 1}: {n} hit(s)")      # the pattern itself is never printed
        check(f"none of the owner's {len(pats)} private literal patterns occurs (case-insensitive; the declared prefix literal excepted)",
              not hits, "; ".join(hits))
else:
    print("  SKIP  ECCO_PRIVATE_PATTERNS is not set: the owner's private literal patterns were NOT applied (release gate P1 needs them)")

# ===========================================================================
print("")
print("[9] negative controls (each scanner flags an injected leak of its kind)")
# ===========================================================================
# The injected leaks are assembled at run time, so this file itself never spells one (it is scanned like every other file).
_d = lambda *parts: "".join(parts)  # noqa: E731
inj = {
    "prefix": {"x.yaml": "a: sensor." + P.PRIVATE_AREA_PREFIX + "x\n"},
    "octo": {"x.yaml": _d("s: sensor.octopus_energy_electricity_", "12a3456789", "_", "1234567", "890123", "_current_rate\n")},
    "thirteen": {"x.md": _d("import MPAN ", "1234567", "890123", "\n")},
    "ip": {"x.md": _d("dongle at 192", ".168", ".1.20\n")},
    "mac": {"x.md": _d("mac 24:6F", ":28:AA", ":BB:CC\n")},
    "path": {"x.md": _d("C:", "\\", "Users", "\\", "someone", "\\", "x\n")},
    "email": {"x.md": _d("mail someone", "@", "gmail.com\n")},
    "secret": {"x.md": _d("-----BEGIN OPENSSH ", "PRIVATE KEY-----\n")},
}
check("prefix scanner flags an injected private prefix", len(scan_prefix(inj["prefix"])) == 1)
check("first-name scanner flags an injected occurrence (any case)", len(scan_name({"x.md": "listed by " + NAME.upper() + "\n"})) == 1)
check("Octopus id scanner flags an injected real-shaped id", bool(scan(inj["octo"], OCTO_REAL)))
check("13-digit scanner flags an MPAN-shaped number on an MPAN line", bool(scan_thirteen(inj["thirteen"])))
check("RFC 1918 scanner flags an injected LAN address (and not a version string)",
      bool(scan(inj["ip"], RFC1918)) and not scan({"v.md": "esphome 2026.8.2 / idf 5.5.5 / 10.5 days\n"}, RFC1918))
check("MAC scanner flags an injected MAC (and not a time of day)", bool(scan(inj["mac"], MAC)) and not scan({"t.md": "12:34:56\n"}, MAC))
check("user-path scanner flags an injected Windows profile path (and not the <WINDOWS_USER> placeholder)",
      bool(scan(inj["path"], USER_PATH)) and not scan({"p.md": "C:\\Users\\<WINDOWS_USER>\\.ssh\n"}, USER_PATH))
check("e-mail scanner flags a personal address and accepts a no-reply one",
      bool(scan_email(inj["email"])) and not scan_email({"n.md": "x <33911698+someone@users.noreply.github.com>\n"}))
check("secret scanner flags an injected private-key block", bool(scan(inj["secret"], SECRET)))
check("secret-file and history-file scanners flag injected paths",
      scan_secret_files(["firmware/secrets.yaml", "ecco_site.local.yaml"]) == ["firmware/secrets.yaml", "ecco_site.local.yaml"]
      and len(scan_history_files(["CURRENT_STATE.md", "docs/HANDOVER_x.md", "docs/architecture/fallback/FB_C3_IMPLEMENTATION_NOTES.md"])) == 3
      and not scan_secret_files(["firmware/secrets.yaml.example", "ecco_site.example.yaml"]))
_fake = "docs/architecture/fallback/FB_C3_IMPLEMENTATION_NOTES.md"
check("a history-named file passes only as an exact placeholder: real content at that path is flagged",
      scan_history_files([_fake], {_fake: "# FB-C3 notes\nreal content\n"}) == [_fake]
      and scan_history_files([_fake], {_fake: STUB_MARKER + "\n# x\nprivate development archive and is not published\n"}) == []
      and scan_history_files(["docs/HANDOVER_x.md"], {"docs/HANDOVER_x.md": STUB_MARKER + "\nprivate development archive and is not\n"})
      == ["docs/HANDOVER_x.md"])

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All public privacy checks passed.")
print("This scan proves the absence of the listed shapes only; release gate P1 also needs the owner's private pattern file.")
