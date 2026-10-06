#!/usr/bin/env python3
"""Fail-closed path containment for repository-relative manifest sources.

Shared by tools/build_ha_bundle.py (copies the files) and tools/validate_repo.py (checks the manifest).
The manifest is data a pull request can change, so every `source` is untrusted: it must name a regular,
non-symlink file that lives inside the repository root, under an approved directory, with an approved
suffix, and (for the bundle builder) is recorded by git as a regular file. Git's own record decides that last
point, so a symlink committed to the tree is refused even where the checkout (core.symlinks=false) wrote it out
as a plain file. Nothing here reads file contents.

Every violation raises UnsafePathError; callers turn that into a non-zero exit. There is no "skip and continue".
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path, PurePosixPath

# Directories a deployment source may live under, plus the two root files the bundle also carries.
ALLOWED_PREFIXES = (
    "home-assistant/packages/",
    "home-assistant/dashboards/",
    "influxdb/",
    "frontend/",
    "firmware/",
)
ALLOWED_ROOT_FILES = ("VERSION.yaml", "deployment/ha-manifest.yaml")
ALLOWED_SUFFIXES = (".yaml", ".yml", ".flux", ".js", ".json", ".md")
# Never bundled even inside an allowed directory (credential-shaped names).
DENIED_BASENAME_PREFIXES = ("secrets", ".env")
DENIED_BASENAME_SUFFIXES = ("_private.yaml", "_private.yml", ".pem", ".key")
FORBIDDEN_CHARS = ("\\", "\x00", ":", "~")


class UnsafePathError(ValueError):
    """A manifest source (or destination) that is not provably a safe in-repo regular file."""


def check_relative_source(source: object, *, allowed_prefixes: tuple[str, ...] = ALLOWED_PREFIXES,
                          allowed_root_files: tuple[str, ...] = ALLOWED_ROOT_FILES,
                          allowed_suffixes: tuple[str, ...] = ALLOWED_SUFFIXES) -> PurePosixPath:
    """Purely lexical validation (no filesystem access). Returns the normalised POSIX path."""
    if not isinstance(source, str) or not source:
        raise UnsafePathError(f"source must be a non-empty string, got {source!r}")
    for bad in FORBIDDEN_CHARS:
        if bad in source:
            raise UnsafePathError(f"source {source!r} contains forbidden character {bad!r}")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in source):
        raise UnsafePathError(f"source {source!r} contains a control character")
    try:
        source.encode("utf-8")  # a lone surrogate (YAML "\ud800") names no portable file and cannot match git's UTF-8 paths
    except UnicodeEncodeError:
        raise UnsafePathError(f"source {source!r} is not valid Unicode text") from None
    if source.startswith("/"):
        raise UnsafePathError(f"source {source!r} is absolute")
    parts = source.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise UnsafePathError(f"source {source!r} has an empty, '.' or '..' component")
        if part.endswith((".", " ")):
            raise UnsafePathError(f"source {source!r} has a component ending in '.' or space")
        if part.lower().startswith(".git"):
            raise UnsafePathError(f"source {source!r} touches a .git* path")
    base = parts[-1].lower()
    if base.startswith(DENIED_BASENAME_PREFIXES) or base.endswith(DENIED_BASENAME_SUFFIXES):
        raise UnsafePathError(f"source {source!r} has a credential-shaped file name")
    if source not in allowed_root_files:
        if not source.startswith(allowed_prefixes):
            raise UnsafePathError(f"source {source!r} is outside the approved directories {allowed_prefixes}")
        if not base.endswith(allowed_suffixes):
            raise UnsafePathError(f"source {source!r} does not have an approved suffix {allowed_suffixes}")
    return PurePosixPath(source)


def is_link_like(path: Path) -> bool:
    """Symlink, or (Windows) junction / any reparse point."""
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None and isjunction(path):
        return True
    try:
        attrs = os.lstat(path).st_file_attributes  # type: ignore[attr-defined]  # Windows only
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def git_tracked_regular(root: Path, rel: str) -> bool:
    """True iff the git index records exactly `rel` as ONE merged (stage 0) regular file (mode 100644 / 100755).

    Exact, never pattern-matched: `--literal-pathspecs` switches off git's pathspec globbing (without it the source
    `x[1].yaml` matches a tracked `x1.yaml`, so an untracked file passed) and the single NUL-terminated record's path
    must equal `rel` byte for byte. A symlink (120000), gitlink (160000), unmerged or missing entry, a record for any
    other path, or any git failure -> False (fail closed).
    """
    try:
        want = rel.encode("utf-8")
        out = subprocess.run(["git", "--literal-pathspecs", "-C", str(root), "ls-files", "--stage", "-z", "--error-unmatch",
                              "--", rel], capture_output=True, timeout=60, check=True).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    records = [r for r in out.split(b"\0") if r]
    if len(records) != 1:
        return False
    meta, tab, path = records[0].partition(b"\t")  # "<mode> <object> <stage>\t<path>"
    fields = meta.split(b" ")
    return (tab == b"\t" and path == want and len(fields) == 3
            and fields[0] in (b"100644", b"100755") and fields[2] == b"0")


def resolve_source(root: Path, source: object, *, require_tracked: bool = True, **lexical) -> Path:
    """Validate `source` and return the real path of the file it names, or raise UnsafePathError."""
    rel = check_relative_source(source, **lexical)
    real_root = root.resolve(strict=True)
    current = real_root
    for part in rel.parts:
        current = current / part
        try:
            if is_link_like(current):
                raise UnsafePathError(f"source {source!r}: {current.relative_to(real_root).as_posix()} is a symlink/junction")
            mode = os.lstat(current).st_mode
        except (FileNotFoundError, NotADirectoryError):  # ENOTDIR: a parent component is a file (POSIX; Windows says not-found)
            raise UnsafePathError(f"source {source!r} does not exist") from None
        except OSError as exc:  # permission, loop, name too long...: not provably safe, so a refusal - never a crash
            raise UnsafePathError(f"source {source!r}: cannot inspect {current.relative_to(real_root).as_posix()}: "
                                  f"{exc.strerror or type(exc).__name__}") from None
    if not stat.S_ISREG(mode):
        raise UnsafePathError(f"source {source!r} is not a regular file")
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError) as exc:  # vanished or looped since the walk above
        raise UnsafePathError(f"source {source!r} cannot be resolved ({type(exc).__name__})") from None
    if not resolved.is_relative_to(real_root):
        raise UnsafePathError(f"source {source!r} resolves outside the repository root")
    if require_tracked and not git_tracked_regular(real_root, rel.as_posix()):
        raise UnsafePathError(f"source {source!r} is not a git-tracked regular file")
    return resolved


def safe_destination(out_root: Path, rel: PurePosixPath) -> Path:
    """Destination inside `out_root` for `rel` (already lexically validated). Never follows links."""
    real_out = out_root.resolve(strict=True)
    dst = real_out.joinpath(*rel.parts)
    if not dst.resolve().is_relative_to(real_out):
        raise UnsafePathError(f"destination for {rel} escapes the bundle directory")
    return dst
