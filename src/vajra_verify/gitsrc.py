"""Obtain diffs from the local git binary. No network access is performed."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_DIFF_FLAGS = ["--no-color", "--no-ext-diff", "-M", "--src-prefix=a/", "--dst-prefix=b/"]


class GitError(RuntimeError):
    """Raised when a git command fails or git is unavailable."""


def _git(args: list[str], cwd: Path | None = None) -> str:
    cmd = ["git", "-c", "core.quotepath=off", *args]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        first = err[0] if err else f"exit status {proc.returncode}"
        raise GitError(f"`git {args[0]}` failed: {first}")
    return proc.stdout.decode("utf-8", errors="replace")


def repo_root(cwd: Path | None = None) -> Path:
    return Path(_git(["rev-parse", "--show-toplevel"], cwd).strip())


def current_branch(cwd: Path | None = None) -> str:
    try:
        name = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()
    except GitError:
        return "(no commits yet)"
    return "(detached HEAD)" if name == "HEAD" else name


def diff_against_base(base: str, cwd: Path | None = None) -> str:
    return _git(["diff", *GIT_DIFF_FLAGS, f"{base}...HEAD"], cwd)


def diff_staged(cwd: Path | None = None) -> str:
    return _git(["diff", "--cached", *GIT_DIFF_FLAGS], cwd)


def diff_working_tree(cwd: Path | None = None) -> str:
    return _git(["diff", *GIT_DIFF_FLAGS], cwd)
