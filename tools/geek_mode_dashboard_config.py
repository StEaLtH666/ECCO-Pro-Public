#!/usr/bin/env python3
"""The raw configuration of the NEW admin-only dashboard that hosts the ECCO Mode Shell (Production / Geek Mode), and the small
plan file that lets the existing resource read-back gate check the shell's Lovelace resource.

    python tools/geek_mode_dashboard_config.py --out <FILE>                 # write the configuration text (outside the repository, or under dist/)
    python tools/geek_mode_dashboard_config.py --check                      # regenerate twice in memory: consistent, deterministic, safe (exit 1 if not)
    python tools/geek_mode_dashboard_config.py --check <FILE>               # the same, and FILE must equal a fresh generation byte for byte
    python tools/geek_mode_dashboard_config.py --resource-plan <FILE>       # a plan.json for `ecco_deploy_preflight.py verify-resource / verify-served`
    python tools/geek_mode_dashboard_config.py --verify-storage <FILE>      # a read-back of the persisted dashboard equals the generated configuration

What it makes. A storage-mode dashboard is created by the owner in the Home Assistant UI (Settings, Dashboards, Add dashboard, "Require
admin") and its raw configuration editor is given ONE text. This tool writes that text: the same cards as the repository's example
(frontend/ecco-mode-shell/examples/intelligence-modes.yaml: the shell with its `always` and `production` lists, then the text-fallback
markdown card), with ONE difference: the example's `catalogue: !include ...` is replaced by the catalogue itself (the committed
frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json), INLINE. Home Assistant resolves an `!include` to the parsed file before the card
sees it, so the card receives exactly the same object. No `!include`, no file reference, no URL: the dashboard configuration does not need the
resource's address (the owner registers the resource separately).

The text is JSON (two-space indent, ASCII, LF, one final newline). JSON is a subset of YAML, which the raw configuration editor accepts, and
there is no indentation or quoting rule to get wrong in a 100 KB paste. The output holds the Intelligence entity ids of the repository's example
(they are the contract's ids, the same for every site) and is NOT committed: write it outside the repository or under dist/ (git-ignored).

`--resource-plan` writes the minimal plan.json that `tools/ecco_deploy_preflight.py verify-resource` and `verify-served` read (one card: tag, name,
resource_url, resource_type, sha256 of the LF file). The preflight tool lists its cards in a constant and is NOT edited: a hand-made plan is the way
to gate this one resource. The card file must be the LF file as committed (a CRLF checkout is refused: its hash would not be the content address).

`--verify-storage` compares a read-back of the persisted configuration (the raw `.storage` file of the new dashboard, whose `data.config` is read, or a
bare configuration JSON) with a fresh generation: the check that the paste arrived as generated. Read-only: it reads the files named and writes nothing.

Standard library plus PyYAML (as the repository's other generators). No network. Exit codes: 0 fine; 1 a problem or a difference; 2 bad usage or a
refused input or output path.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

TOOLS_DIR = Path(__file__).resolve().parent
REPO = TOOLS_DIR.parent

EXAMPLE_REL = "frontend/ecco-mode-shell/examples/intelligence-modes.yaml"
CATALOGUE_REL = "frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json"
CARD_REL = "frontend/ecco-mode-shell/ecco-mode-shell.js"
TAG = "ecco-mode-shell"
SHELL_TYPE = f"custom:{TAG}"
CATALOGUE_SCHEMA = "ecco-geek-catalogue/1"
PLAN_SCHEMA = "ecco-geek-u1-resource-plan/1"
MAX_BYTES = 400_000          # the raw configuration editor and the websocket (4 MiB) take far more; this keeps a paste small and a mistake visible
MAX_EXAMPLE_BYTES = 200_000

# the card types the example uses, and the ones the shell accepts in its `always` region (a mirror of ALLOWED_CARD_TYPES and DEFAULT_CUSTOM_CARDS in the
# shell): the generated dashboard must not bring a card type the repository's example does not use
ALWAYS_ALLOWED_TYPES = {"markdown", "entities", "glance", "history-graph", "statistics-graph", "sensor", "gauge", "entity", "heading",
                        "vertical-stack", "horizontal-stack", "grid", "conditional", "tile", "custom:ecco-intelligence-card"}
KNOWN_CUSTOM = {SHELL_TYPE, "custom:ecco-intelligence-card"}
SAFE_ACTIONS = {"none", "more-info", "navigate"}
CALL_KEYS = {"service", "service_data", "perform_action", "call-service", "call_service", "action_data"}

# text that must never be in the file: addresses, URLs, credentials, tokens, e-mail addresses, private paths
PRIVACY = {
    "url": re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://"),
    "ipv4": re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])"),
    "mac": re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])"),
    "email": re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    "token": re.compile(r"-----BEGIN [A-Z ]*KEY-----|\bghp_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bAKIA[0-9A-Z]{16}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}"
                        r"|\bsk-[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),
    "bearer": re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}", re.I),
    "credential_pair": re.compile(r"[\"']?\b(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|authorization)\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"'{}]{3,}", re.I),
    "hex_blob": re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])"),
    "base64_blob": re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])"),
    "user_path": re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[^\\/\s'\"<>]+|/[cC]/Users/[^/\s'\"<>]+|(?<![A-Za-z])/Users/[a-z][^/\s'\"<>]*/|/home/[a-z][^/\s'\"<>]*/"),
    "coordinates": re.compile(r"[\"'](?:latitude|longitude|lat|lon|lng)[\"']\s*:\s*-?\d", re.I),
}


class Refused(Exception):
    """An input or output path is not acceptable (exit 2)."""


# ---------------------------------------------------------------------------------------------------------------------------
# reading the example: YAML with one `!include` that is kept as a marker, never followed by the YAML loader
# ---------------------------------------------------------------------------------------------------------------------------
class Include(str):
    """The text of an `!include` tag, kept as data."""


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!include", lambda loader, node: Include(loader.construct_scalar(node)))


def load_example(text: str) -> dict:
    doc = yaml.load(text, Loader=_Loader)  # noqa: S506 - a SafeLoader subclass that only adds a text-keeping tag
    if not isinstance(doc, dict):
        raise Refused("the example is not a mapping")
    return doc


def _includes(node, out: list[str]) -> list[str]:
    if isinstance(node, Include):
        out.append(str(node))
    elif isinstance(node, dict):
        for v in node.values():
            _includes(v, out)
    elif isinstance(node, list):
        for v in node:
            _includes(v, out)
    return out


def _no_duplicate_keys(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError(f"duplicate key {k!r}")
        seen[k] = v
    return seen


def parse_json(text: str):
    """Strict JSON: no NaN or Infinity, no duplicate key (a duplicate would silently drop a card setting)."""
    def bad(c):
        raise ValueError(f"non-finite number {c}")
    return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=bad)


def read_inputs(root: Path = REPO) -> tuple[str, bytes]:
    """The example text and the catalogue bytes, read from the repository (bounded, regular files only)."""
    out = []
    for rel, cap in ((EXAMPLE_REL, MAX_EXAMPLE_BYTES), (CATALOGUE_REL, MAX_BYTES)):
        p = root / rel
        if p.is_symlink() or not p.is_file():
            raise Refused(f"{rel}: not a regular file")
        if p.stat().st_size > cap:
            raise Refused(f"{rel}: larger than {cap} bytes")
        out.append(p.read_bytes())
    try:
        return out[0].decode("utf-8"), out[1]
    except UnicodeDecodeError as ex:
        raise Refused(f"input is not UTF-8 ({ex.reason})") from None


def build_config(example_text: str, catalogue_bytes: bytes) -> dict:
    """The dashboard configuration: the example's cards with the catalogue inline in place of the one `!include` of the catalogue."""
    doc = load_example(example_text)
    includes = _includes(doc, [])
    if len(includes) != 1:
        raise Refused(f"the example must hold exactly one !include (the catalogue); it holds {len(includes)}")
    if not includes[0].replace("\\", "/").endswith("/catalogue/intelligence.catalogue.json"):
        raise Refused("the example's one !include is not the Intelligence catalogue")
    try:
        catalogue = parse_json(catalogue_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as ex:
        raise Refused(f"the catalogue is not strict JSON ({ex})") from None
    if not isinstance(catalogue, dict) or catalogue.get("schema") != CATALOGUE_SCHEMA:
        raise Refused(f"the catalogue's schema is not {CATALOGUE_SCHEMA}")

    def put(node):
        if isinstance(node, Include):
            return copy.deepcopy(catalogue)
        if isinstance(node, dict):
            return {k: put(v) for k, v in node.items()}
        if isinstance(node, list):
            return [put(v) for v in node]
        return node

    return put(doc)


def render(config: dict) -> str:
    """The text the owner pastes: JSON, two-space indent, ASCII, LF, one final newline."""
    return json.dumps(config, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def generate(root: Path = REPO) -> str:
    example_text, catalogue_bytes = read_inputs(root)
    return render(build_config(example_text, catalogue_bytes))


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------
# the checks (used by --check and by the suite, which feeds them mutants)
# ---------------------------------------------------------------------------------------------------------------------------
def _walk(node, path=""):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}/{i}")


def _cards_of(node):
    """Every card configuration in a (possibly nested) card list: a dict with a `type`, and the cards of a stack, grid or conditional."""
    if isinstance(node, list):
        for c in node:
            yield from _cards_of(c)
    elif isinstance(node, dict) and isinstance(node.get("type"), str):
        yield node
        yield from _cards_of(node.get("cards"))
        yield from _cards_of(node.get("card"))


def problems(text: str, example_text: str, catalogue_bytes: bytes) -> list[str]:
    """Every reason the text is not the generated configuration of these inputs, or is not safe to paste. Empty means fine."""
    out: list[str] = []
    if not isinstance(text, str):
        return ["the configuration is not text"]
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        out.append(f"larger than {MAX_BYTES} bytes")
    if not text.isascii():
        out.append("not ASCII")
    if "\r" in text or "\x00" in text or text.startswith("\ufeff"):
        out.append("a CR, a NUL or a byte order mark")
    if not text.endswith("\n") or text.endswith("\n\n"):
        out.append("not exactly one final newline")
    for name, rx in PRIVACY.items():
        m = rx.search(text)
        if m:
            out.append(f"{name}-like text at offset {m.start()}")
    try:
        cfg = parse_json(text)
    except ValueError as ex:
        return out + [f"not strict JSON: {ex}"]
    try:
        yaml_cfg = yaml.safe_load(text)
    except yaml.YAMLError:
        yaml_cfg = None
        out.append("the YAML loader of the raw editor cannot read it")
    if yaml_cfg is not None and yaml_cfg != cfg:
        out.append("YAML and JSON read it differently")
    if not isinstance(cfg, dict) or set(cfg) != {"title", "views"}:
        return out + ["the top level is not exactly {title, views}"]
    # it is what the generator makes from these inputs, and nothing else
    try:
        expected = build_config(example_text, catalogue_bytes)
    except Refused as ex:
        return out + [f"the inputs are refused: {ex}"]
    if render(expected) != text:
        out.append("differs from a fresh generation of the inputs")
    if cfg != expected:
        out.append("not equal to a fresh generation after parsing")
    views = cfg.get("views")
    if not isinstance(views, list) or len(views) != 1 or not isinstance(views[0], dict):
        return out + ["not exactly one view"]
    cards = views[0].get("cards")
    if not isinstance(cards, list) or len(cards) != 2 or not isinstance(cards[0], dict) or cards[0].get("type") != SHELL_TYPE:
        return out + ["the view is not [the shell, the text fallback]"]
    shell = cards[0]
    cat = shell.get("catalogue")
    try:
        want = json.loads(catalogue_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        want = None
    if not isinstance(cat, dict) or cat != want or json.dumps(cat, sort_keys=True) != json.dumps(want, sort_keys=True):
        out.append("the inline catalogue is not the committed catalogue")
    if "!include" in text:
        out.append("an !include is left in the output")
    # no card type beyond the example's, no write path in `always`, the only write action is in `production`
    for region in ("always",):
        for card in _cards_of(shell.get(region)):
            if card["type"] not in ALWAYS_ALLOWED_TYPES:
                out.append(f"{region}: card type {card['type']!r} is not one the example uses")
    for card in _cards_of(shell.get("production")):
        if card["type"] not in ALWAYS_ALLOWED_TYPES:
            out.append(f"production: card type {card['type']!r} is not one the example uses")
    for card in _cards_of(cards[1:]):
        if card["type"] not in ALWAYS_ALLOWED_TYPES:
            out.append(f"outside the shell: card type {card['type']!r} is not one the example uses")
    for p, v in _walk({k: v for k, v in shell.items() if k != "catalogue"}):
        key = p.rsplit("/", 1)[-1]
        if key in CALL_KEYS:
            out.append(f"{p}: a service-call key")
        if key == "action" and isinstance(v, str) and v not in SAFE_ACTIONS and p.startswith("/always"):
            out.append(f"{p}: action {v!r} in the always list")
    for p, v in _walk(cfg):
        if isinstance(v, str) and v.startswith("custom:") and v not in KNOWN_CUSTOM and p.endswith("/type"):
            out.append(f"{p}: custom card {v!r} is not one the example uses")
    return out


def resource_plan(card_bytes: bytes) -> dict:
    """The minimal plan.json for ecco_deploy_preflight.py verify-resource / verify-served: one card, content-addressed."""
    if b"\r" in card_bytes:
        raise Refused("the card file has CR characters: use an LF checkout (the content address is the hash of the LF file)")
    digest = sha256(card_bytes)
    name = f"{TAG}.{digest[:8]}.js"
    return {"schema": PLAN_SCHEMA, "note": "hand-made plan for the ECCO Mode Shell resource; not a preflight render",
            "cards": [{"name": name, "tag": TAG, "source": CARD_REL, "sha256": digest, "resource_url": f"/local/ecco/{name}", "resource_type": "module"}]}


def stored_config(raw: str):
    """The configuration inside a read-back: a raw `.storage` file ({"data": {"config": ...}}) or a bare configuration."""
    doc = parse_json(raw)
    if isinstance(doc, dict) and isinstance(doc.get("data"), dict) and "config" in doc["data"]:
        return doc["data"]["config"]
    return doc


# ---------------------------------------------------------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------------------------------------------------------
def safe_out(path: str, root: Path = REPO) -> Path:
    """An output path outside the repository, or under its git-ignored dist/ folder. Never a symlink, never inside tracked folders."""
    p = Path(path)
    if p.is_symlink():
        raise Refused("the output path is a symlink")
    resolved = p.resolve()
    rroot = root.resolve()
    inside = resolved == rroot or rroot in resolved.parents
    if inside and (rroot / "dist").resolve() not in resolved.parents:
        raise Refused("the output must be outside the repository or under its dist/ folder (git-ignored): it is not to be committed")
    if not resolved.parent.is_dir():
        raise Refused("the output's folder does not exist")
    return resolved


def write_text(path: Path, data: str, overwrite: bool) -> None:
    b = data.encode("utf-8")
    if path.exists() and not overwrite and path.read_bytes() != b:
        raise Refused(f"{path} exists and differs: pass --overwrite to replace it")
    path.write_bytes(b)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="write the dashboard configuration text here")
    ap.add_argument("--check", nargs="?", const="-", metavar="FILE", help="check the generation (and FILE, if given, equals it byte for byte)")
    ap.add_argument("--resource-plan", metavar="FILE", help="write the plan.json for verify-resource / verify-served here")
    ap.add_argument("--verify-storage", metavar="FILE", help="a read-back of the persisted dashboard: its configuration must equal the generated one")
    ap.add_argument("--card", default=None, help=f"the card file the plan hashes (default: the committed {CARD_REL})")
    ap.add_argument("--repo-root", type=Path, default=REPO, help="the repository whose files are read (default: this one)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing, different output file")
    a = ap.parse_args(argv)
    if not (a.out or a.check or a.resource_plan or a.verify_storage):
        ap.error("give --out, --check, --resource-plan or --verify-storage")
    root = a.repo_root
    try:
        example_text, catalogue_bytes = read_inputs(root)
        text = render(build_config(example_text, catalogue_bytes))
        rc = 0
        if a.check is not None:
            again = render(build_config(example_text, catalogue_bytes))
            found = problems(text, example_text, catalogue_bytes)
            if again != text:
                found.append("two generations differ")
            if a.check != "-":
                got = Path(a.check).read_bytes() if Path(a.check).is_file() else None
                if got is None:
                    found.append(f"{a.check}: no such file")
                elif got != text.encode("utf-8"):
                    found.append(f"{a.check}: differs from a fresh generation (sha256 {sha256(got)[:16]}, expected {sha256(text)[:16]})")
            if found:
                print("FAIL: " + "; ".join(found))
                rc = 1
            else:
                print(f"OK: {len(text.encode('utf-8'))} bytes, sha256 {sha256(text)}")
        if a.out:
            path = safe_out(a.out, root)
            write_text(path, text, a.overwrite)
            print(f"wrote {path}: {len(text.encode('utf-8'))} bytes, sha256 {sha256(text)}")
        if a.resource_plan:
            card_path = Path(a.card) if a.card else root / CARD_REL
            if card_path.is_symlink() or not card_path.is_file():
                raise Refused("the card file is not a regular file")
            plan = resource_plan(card_path.read_bytes())
            path = safe_out(a.resource_plan, root)
            write_text(path, json.dumps(plan, indent=2) + "\n", a.overwrite)
            c = plan["cards"][0]
            print(f"wrote {path}: {c['resource_url']} sha256 {c['sha256']}")
        if a.verify_storage:
            f = Path(a.verify_storage)
            if f.is_symlink() or not f.is_file():
                raise Refused("the read-back is not a regular file")
            try:
                got = stored_config(f.read_text(encoding="utf-8-sig"))
            except (ValueError, UnicodeDecodeError) as ex:
                raise Refused(f"the read-back is not strict JSON ({ex})") from None
            if got == build_config(example_text, catalogue_bytes):
                print("STORED CONFIGURATION EQUALS THE GENERATED ONE")
            else:
                print("STORED CONFIGURATION DIFFERS FROM THE GENERATED ONE")
                rc = 1
        return rc
    except Refused as ex:
        print(f"refused: {ex}", file=sys.stderr)
        return 2
    except OSError as ex:
        print(f"refused: {type(ex).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
