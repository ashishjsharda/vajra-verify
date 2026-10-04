"""Unified-diff parser built on the Python standard library.

Handles `git diff` output (including new/deleted/renamed/binary files) and
plain `diff -u` output. Error messages reference line numbers only and never
echo diff content, so secret-shaped values cannot leak through exceptions.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from typing import Iterator

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


class DiffParseError(ValueError):
    """Raised when input is not a well-formed unified diff."""


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: str  # "+", "-", or " "
    text: str
    old_no: int | None
    new_no: int | None


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def added(self) -> list[DiffLine]:
        return [ln for ln in self.lines if ln.kind == "+"]

    @property
    def removed(self) -> list[DiffLine]:
        return [ln for ln in self.lines if ln.kind == "-"]


@dataclass(slots=True)
class FileDiff:
    old_path: str | None
    new_path: str | None
    status: str = "modified"  # added | deleted | modified | renamed
    binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    def added_lines(self) -> Iterator[DiffLine]:
        for h in self.hunks:
            yield from h.added

    def removed_lines(self) -> Iterator[DiffLine]:
        for h in self.hunks:
            yield from h.removed

    def context_lines(self) -> Iterator[DiffLine]:
        for h in self.hunks:
            yield from (ln for ln in h.lines if ln.kind == " ")

    @property
    def additions(self) -> int:
        return sum(1 for _ in self.added_lines())

    @property
    def deletions(self) -> int:
        return sum(1 for _ in self.removed_lines())

    def first_evidence(self) -> tuple[int, str]:
        """(line, side) for the first changed line in this file."""
        for ln in self.added_lines():
            return ln.new_no or 1, "new"
        for ln in self.removed_lines():
            return ln.old_no or 1, "old"
        return 1, "old" if self.status == "deleted" else "new"


@dataclass(slots=True)
class Diff:
    files: list[FileDiff]

    @property
    def lines_added(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def lines_deleted(self) -> int:
        return sum(f.deletions for f in self.files)


def _unquote(path: str) -> str:
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        raw = codecs.decode(path[1:-1], "unicode_escape")
        return raw.encode("latin-1").decode("utf-8", errors="replace")
    return path


def _clean_marker_path(raw: str, prefix: str) -> str | None:
    # "--- a/file\t2024-01-01 ..." (plain diff timestamps) -> "a/file"
    path = _unquote(raw.split("\t", 1)[0].rstrip())
    if path == "/dev/null":
        return None
    if path.startswith(prefix):
        path = path[len(prefix):]
    return path


def _paths_from_git_header(rest: str) -> tuple[str, str]:
    """Split the 'a/x b/y' part of a `diff --git` header."""
    if rest.startswith('"'):
        end = rest.find('"', 1)
        while end != -1 and rest[end - 1] == "\\":
            end = rest.find('"', end + 1)
        a = _unquote(rest[: end + 1])
        b = _unquote(rest[end + 1:].strip())
    else:
        # Prefer the split where both halves name the same path.
        a, b = rest, rest
        candidates = [m.start() for m in re.finditer(r" b/", rest)]
        chosen = None
        for idx in candidates:
            left, right = rest[:idx], rest[idx + 1:]
            if left[2:] == right[2:]:
                chosen = idx
                break
        if chosen is None and candidates:
            chosen = candidates[0]
        if chosen is not None:
            a, b = rest[:chosen], _unquote(rest[chosen + 1:])
        a = _unquote(a)
    a = a[2:] if a.startswith("a/") else a
    b = b[2:] if b.startswith("b/") else b
    return a, b


def _finalize_status(fd: FileDiff, explicit: bool) -> None:
    if explicit:
        return
    if fd.old_path is None and fd.new_path is not None:
        fd.status = "added"
    elif fd.new_path is None and fd.old_path is not None:
        fd.status = "deleted"
    elif fd.old_path != fd.new_path:
        fd.status = "renamed"
    else:
        fd.status = "modified"


def parse_diff(text: str) -> Diff:
    """Parse unified-diff text into a Diff. Raises DiffParseError."""
    lines = text.splitlines()
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    explicit_status = False
    saw_minus = False
    hunk: Hunk | None = None
    old_rem = new_rem = 0
    old_no = new_no = 0

    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        lineno = i + 1
        i += 1

        if hunk is not None and (old_rem > 0 or new_rem > 0):
            if raw.startswith("\\"):
                continue
            tag = raw[:1] if raw else " "
            body = raw[1:]
            if tag == " ":
                if old_rem <= 0 or new_rem <= 0:
                    raise DiffParseError(f"line {lineno}: hunk line counts do not match header")
                hunk.lines.append(DiffLine(" ", body, old_no, new_no))
                old_no += 1
                new_no += 1
                old_rem -= 1
                new_rem -= 1
            elif tag == "-":
                if old_rem <= 0:
                    raise DiffParseError(f"line {lineno}: hunk line counts do not match header")
                hunk.lines.append(DiffLine("-", body, old_no, None))
                old_no += 1
                old_rem -= 1
            elif tag == "+":
                if new_rem <= 0:
                    raise DiffParseError(f"line {lineno}: hunk line counts do not match header")
                hunk.lines.append(DiffLine("+", body, None, new_no))
                new_no += 1
                new_rem -= 1
            else:
                raise DiffParseError(f"line {lineno}: unexpected content inside hunk")
            continue

        if raw.startswith("diff --git "):
            if cur is not None:
                _finalize_status(cur, explicit_status)
            a, b = _paths_from_git_header(raw[len("diff --git "):])
            cur = FileDiff(old_path=a, new_path=b)
            files.append(cur)
            explicit_status = False
            saw_minus = False
            hunk = None
            continue

        if raw.startswith("--- ") and i < n and lines[i].startswith("+++ "):
            if cur is None or saw_minus or cur.hunks:
                if cur is not None:
                    _finalize_status(cur, explicit_status)
                cur = FileDiff(old_path=None, new_path=None)
                files.append(cur)
                explicit_status = False
            old = _clean_marker_path(raw[4:], "a/")
            new = _clean_marker_path(lines[i][4:], "b/")
            i += 1
            cur.old_path, cur.new_path = old, new
            saw_minus = True
            hunk = None
            continue

        if raw.startswith("@@"):
            if cur is None:
                raise DiffParseError(f"line {lineno}: hunk header before any file header")
            m = HUNK_RE.match(raw)
            if not m:
                raise DiffParseError(f"line {lineno}: malformed hunk header")
            os_, oc, ns, nc = m.group(1), m.group(2), m.group(3), m.group(4)
            hunk = Hunk(
                old_start=int(os_),
                old_count=int(oc) if oc is not None else 1,
                new_start=int(ns),
                new_count=int(nc) if nc is not None else 1,
            )
            cur.hunks.append(hunk)
            old_rem, new_rem = hunk.old_count, hunk.new_count
            old_no, new_no = hunk.old_start, hunk.new_start
            continue

        if cur is not None and not cur.hunks:
            if raw.startswith("new file mode"):
                cur.status, cur.old_path, explicit_status = "added", None, True
            elif raw.startswith("deleted file mode"):
                cur.status, cur.new_path, explicit_status = "deleted", None, True
            elif raw.startswith("rename from "):
                cur.old_path = _unquote(raw[len("rename from "):])
                cur.status, explicit_status = "renamed", True
            elif raw.startswith("rename to "):
                cur.new_path = _unquote(raw[len("rename to "):])
                cur.status, explicit_status = "renamed", True
            elif raw.startswith("copy to "):
                cur.new_path = _unquote(raw[len("copy to "):])
                cur.status, explicit_status = "added", True
            elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
                cur.binary = True
        # Any other line outside a hunk (index lines, mail headers,
        # format-patch trailers, binary payloads) is ignored.

    if hunk is not None and (old_rem > 0 or new_rem > 0):
        raise DiffParseError("unexpected end of input: truncated hunk")
    if cur is not None:
        _finalize_status(cur, explicit_status)
    if not files and text.strip():
        raise DiffParseError("input does not look like a unified diff")
    return Diff(files=files)
