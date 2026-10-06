#!/usr/bin/env python3
"""Build a reviewable Home Assistant deployment bundle from the tracked manifest.

The bundle is intentionally non-deploying. It packages only approved source
files and never reads secrets or talks to a live Home Assistant instance.

REVIEW ONLY. The output is built from whatever the checked-out manifest names, which on a pull request is
untrusted input. It must never be used as a deployment source; deploy only from a reviewed, merged commit.

Path safety (tools/_safe_paths.py): every manifest `source` must be a lexically clean repo-relative path under an
approved directory with an approved suffix, every component must be a non-symlink, the file must be a regular
git-tracked file, and it must resolve inside the repository root. Any violation aborts the build, exits non-zero
and removes the partial bundle. There is no skip-and-continue.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _safe_paths import (  # noqa: E402
    UnsafePathError, check_relative_source, is_link_like, resolve_source, safe_destination,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = "deployment/ha-manifest.yaml"
OUT_REL = "dist/ecco-ha-bundle"

REVIEW_ONLY = (
    "REVIEW ONLY - NOT A DEPLOYMENT ARTIFACT.\n"
    "Built by tools/build_ha_bundle.py from a checkout that may be an unreviewed pull request. Do not copy it to a\n"
    "Home Assistant instance, an ESPHome device or an InfluxDB task. Deploy only from a reviewed, merged commit.\n"
)


def collect_sources(node: object, found: list[str] | None = None) -> list[str]:
    """Every `source` value anywhere in the manifest, in document order. A non-string `source` is an error."""
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "source":
                if not isinstance(value, str):
                    raise UnsafePathError(f"manifest source must be a string, got {value!r}")
                found.append(value)
            else:
                collect_sources(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_sources(item, found)
    return found


def build(root: Path, out_rel: str = OUT_REL, *, require_tracked: bool = True) -> Path:
    """Build the bundle under root/out_rel. Raises UnsafePathError (and leaves no output) on any violation."""
    root = root.resolve(strict=True)
    out = root / out_rel
    # Fail closed: a refused build never leaves a bundle behind, not even a stale one from an earlier run.
    for p in (out.parent, out):
        if is_link_like(p):
            raise UnsafePathError(f"{p} is a symlink/junction")
    if out.exists():
        shutil.rmtree(out)

    manifest_path = resolve_source(root, MANIFEST_REL, require_tracked=require_tracked)
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise UnsafePathError(f"{MANIFEST_REL} is not a mapping")
    sources = collect_sources(data)
    if not sources:
        raise UnsafePathError(f"{MANIFEST_REL} lists no sources")
    sources.append("VERSION.yaml")

    # Validate every source before anything is written.
    plan: dict[str, Path] = {}
    for source in sources:
        rel = check_relative_source(source).as_posix()
        if rel in plan and rel != "VERSION.yaml":
            raise UnsafePathError(f"duplicate bundle destination: {rel}")
        plan[rel] = resolve_source(root, rel, require_tracked=require_tracked)

    out.mkdir(parents=True)
    try:
        if not out.resolve().is_relative_to(root):
            raise UnsafePathError("output directory resolves outside the repository root")
        for rel, src in plan.items():
            dst = safe_destination(out, check_relative_source(rel))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst, follow_symlinks=False)
        shutil.copyfile(manifest_path, out / "ha-manifest.yaml", follow_symlinks=False)
        readme = (
            f"# ECCO Pro deployment bundle (REVIEW ONLY)\n\nRelease: {data.get('release', 'unknown')}\n\n"
            "This bundle is generated from the repository deployment manifest. It does not contain secrets and it "
            "does not deploy automatically. It is for REVIEW ONLY: it is not a trusted deployment input.\n\n"
            "Home Assistant packages are copied to `/config/packages/` and require a configuration check/restart. The "
            "dashboard is currently applied through the Lovelace Raw Configuration Editor. ESPHome firmware and the "
            "InfluxDB task remain deliberate/manual because they can affect live inverter operation or data processing.\n"
        )
        (out / "README.md").write_text(readme, encoding="utf-8")
        (out / "REVIEW-ONLY.txt").write_text(REVIEW_ONLY, encoding="utf-8")
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-untracked", action="store_true",
                    help="skip the git-tracked check (for a source archive with no .git); every other containment check still applies")
    args = ap.parse_args(argv)
    try:
        out = build(ROOT, require_tracked=not args.allow_untracked)
    except UnsafePathError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"Built {out} (REVIEW ONLY)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
