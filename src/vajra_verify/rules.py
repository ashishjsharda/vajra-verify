"""The ten deterministic v0 rules. Each rule is a pure function of the diff.

Rules never copy diff line text into findings; only paths, line numbers,
identifiers, and fixed messages are emitted.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import classify as C
from .diffparse import Diff, DiffLine, FileDiff, Hunk
from .models import (
    HIGH, HUMAN_MUST_READ, MEDIUM, RISK_HITS, UNPROVEN_BEHAVIORS, WHAT_CHANGED,
    Evidence, Finding,
)

LARGE_DIFF_LINES = 400
LARGE_DIFF_FILES = 15
READ_FIRST_LIMIT = 5

DEF_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
    r"(?:def|function\*?|func|fn|class|interface)\s+(?:\([^)]*\)\s*)?([A-Za-z_$][\w$]*)"
)
ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
    r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>"
)


def definition_name(text: str) -> str | None:
    m = DEF_RE.match(text) or ARROW_RE.match(text)
    return m.group(1) if m else None


@dataclass(slots=True)
class Context:
    diff: Diff
    doc_texts: list[str] = field(default_factory=list)


def _ev(fd: FileDiff) -> Evidence:
    line, side = fd.first_evidence()
    return Evidence(fd.path if side == "new" else (fd.old_path or fd.path), line, side)


def _new(fd: FileDiff, ln: DiffLine) -> Evidence:
    return Evidence(fd.path, ln.new_no or 1, "new")


def _old(fd: FileDiff, ln: DiffLine) -> Evidence:
    return Evidence(fd.old_path or fd.path, ln.old_no or 1, "old")


def _changed_production(diff: Diff) -> list[FileDiff]:
    return [f for f in diff.files if f.status != "deleted" and C.is_production(f.path)
            and (f.additions or f.deletions or f.binary or f.status in ("added", "renamed"))]


def _file_sensitive_terms(fd: FileDiff) -> list[str]:
    terms = set(C.sensitive_terms(fd.path))
    if fd.old_path:
        terms.update(C.sensitive_terms(fd.old_path))
    return sorted(terms)


# 1. Large diff ---------------------------------------------------------------

def rule_large_diff(ctx: Context) -> list[Finding]:
    diff = ctx.diff
    prod = [f for f in diff.files if C.is_production(f.path)]
    prod_added = sum(f.additions for f in prod)
    n_files = len(diff.files)
    if prod_added <= LARGE_DIFF_LINES and n_files <= LARGE_DIFF_FILES:
        return []
    pool = [f for f in prod if f.status != "deleted"] or [
        f for f in diff.files if f.status != "deleted"] or list(diff.files)
    ranked = sorted(pool, key=lambda f: (0 if _file_sensitive_terms(f) else 1,
                                         -f.additions, f.path))[:READ_FIRST_LIMIT]
    dirs = {posixpath.dirname(f.path) or "." for f in diff.files}
    names = ", ".join(f.path for f in ranked)
    return [Finding(
        id="large-diff", severity=MEDIUM, section=HUMAN_MUST_READ,
        message="Large diff; prioritize human review of these files.",
        detail=f"{n_files} files, +{prod_added} production lines, {len(dirs)} directories",
        evidence=[_ev(f) for f in ranked],
        suggested_action=f"Review the read-first files before the rest of the diff: {names}.",
        rule=1,
    )]


# 2. Tests missing ------------------------------------------------------------

def rule_tests_missing(ctx: Context) -> list[Finding]:
    diff = ctx.diff
    prod = _changed_production(diff)
    if not prod:
        return []
    tests = [f for f in diff.files if f.status != "deleted" and C.is_test(f.path)]
    test_areas = [C.area(f.path) for f in tests]
    has_unknown_test_area = any(not a for a in test_areas)

    groups: dict[tuple[str, ...], list[FileDiff]] = {}
    for f in prod:
        groups.setdefault(C.area(f.path), []).append(f)

    findings: list[Finding] = []
    for area_key in sorted(groups):
        files = sorted(groups[area_key], key=lambda f: f.path)
        sensitive = any(_file_sensitive_terms(f) for f in files)
        severity = HIGH if sensitive else MEDIUM
        evidence = [_ev(f) for f in files]
        if area_key:
            if any(C.areas_related(area_key, ta) for ta in test_areas):
                continue
            if has_unknown_test_area:
                continue  # relevance cannot be determined
            label = "/".join(area_key)
            detail = f"area: {label}" + ("; high-risk domain" if sensitive else "")
            findings.append(Finding(
                id="relevant-test-not-found", severity=severity, section=UNPROVEN_BEHAVIORS,
                message="Source changed; relevant test change not found.",
                detail=detail, evidence=evidence,
                suggested_action=(f"Add or update tests covering the `{label}` changes, "
                                  "or confirm existing coverage."),
                rule=2,
            ))
        elif not tests:
            findings.append(Finding(
                id="no-test-changes", severity=severity, section=UNPROVEN_BEHAVIORS,
                message="Source changed; no changed test file found.",
                detail="area undetermined" + ("; high-risk domain" if sensitive else ""),
                evidence=evidence,
                suggested_action=("Add or update tests for the changed source files, "
                                  "or confirm existing coverage."),
                rule=2,
            ))
    return findings


# 3. Deleted tests ------------------------------------------------------------

TEST_DEF_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\("),
    re.compile(r"^\s*((?:it|test|describe)(?:\.\w+)*\s*\(\s*(['\"`]).*?\2)"),
    re.compile(r"^\s*func\s+(Test\w*)\s*\("),
    re.compile(r"^\s*(#\[(?:tokio::)?test\])"),
)
RUST_TEST_ATTR = TEST_DEF_PATTERNS[3]


def _test_name(text: str, test_file: bool) -> str | None:
    patterns = TEST_DEF_PATTERNS if test_file else (RUST_TEST_ATTR, TEST_DEF_PATTERNS[0])
    for rx in patterns:
        m = rx.match(text)
        if m:
            return re.sub(r"\s+", " ", m.group(1))
    return None


def rule_deleted_tests(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for fd in ctx.diff.files:
        old_path = fd.old_path or fd.path
        if fd.status == "deleted" and C.is_test(old_path):
            findings.append(Finding(
                id="deleted-test", severity=HIGH, section=RISK_HITS,
                message="Test file deleted.", detail=None, evidence=[_ev(fd)],
                suggested_action=f"Confirm the deletion of {old_path} is intentional "
                                 "and its coverage is replaced.",
                rule=3,
            ))
            continue
        if fd.status == "deleted":
            continue
        test_file = C.is_test(fd.path)
        removed: list[tuple[str, DiffLine]] = []
        added: Counter[str] = Counter()
        for ln in fd.removed_lines():
            name = _test_name(ln.text, test_file)
            if name:
                removed.append((name, ln))
        if not removed:
            continue
        for ln in fd.added_lines():
            name = _test_name(ln.text, test_file)
            if name:
                added[name] += 1
        evidence: list[Evidence] = []
        for name, ln in removed:
            if added[name] > 0:
                added[name] -= 1  # renamed/edited in place, not removed
                continue
            evidence.append(_old(fd, ln))
        if evidence:
            findings.append(Finding(
                id="deleted-test", severity=HIGH, section=RISK_HITS,
                message="Test removal detected in this diff.",
                detail=f"{len(evidence)} test definition(s) removed",
                evidence=evidence,
                suggested_action=f"Confirm the removed test(s) in {fd.path} are intentional "
                                 "and their coverage is replaced.",
                rule=3,
            ))
    return findings


# 4. Sensitive paths ----------------------------------------------------------

def rule_sensitive_paths(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for fd in ctx.diff.files:
        if not C.is_production(fd.old_path or fd.path) and not C.is_production(fd.path):
            continue
        terms = set(_file_sensitive_terms(fd))
        evidence: list[Evidence] = [_ev(fd)] if terms else []
        for ln in list(fd.added_lines()) + list(fd.removed_lines()):
            name = definition_name(ln.text)
            if not name:
                continue
            hit = C.sensitive_terms(name)
            if hit:
                new_terms = set(hit) - terms
                terms.update(hit)
                if new_terms:
                    evidence.append(_new(fd, ln) if ln.kind == "+" else _old(fd, ln))
        if not terms:
            continue
        label = ", ".join(sorted(terms))
        findings.append(Finding(
            id="sensitive-path", severity=MEDIUM, section=HUMAN_MUST_READ,
            message="High-risk domain touched.", detail=label,
            evidence=sorted(set(evidence)),
            suggested_action=f"Have an owner of the {label} domain review {fd.path}.",
            rule=4,
        ))
    return findings


# 5. Config drift -------------------------------------------------------------

SCREAMING_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
COMMON_CONSTANTS = {
    "MAX_VALUE", "MIN_VALUE", "MAX_SAFE_INTEGER", "MIN_SAFE_INTEGER", "POSITIVE_INFINITY",
    "NEGATIVE_INFINITY", "NODE_ENV", "EXIT_SUCCESS", "EXIT_FAILURE", "SEEK_SET", "SEEK_CUR",
    "SEEK_END", "O_RDONLY", "O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC",
    "STDIN_FILENO", "STDOUT_FILENO", "STDERR_FILENO", "INT_MAX", "INT_MIN", "UINT_MAX",
    "SIZE_MAX", "LONG_MAX", "LONG_MIN", "CHAR_BIT", "FLT_MAX", "DBL_MAX", "AF_INET",
    "AF_INET6", "SOCK_STREAM", "SOCK_DGRAM", "IPPROTO_TCP", "SOL_SOCKET", "SO_REUSEADDR",
    "E_ALL", "E_STRICT", "PHP_EOL", "PHP_VERSION", "UTF_8", "US_ASCII", "ISO_8859_1",
    "CASE_INSENSITIVE", "HTTP_OK", "TYPE_CHECKING", "ALL_CAPS",
}
DOC_BASENAMES = {".env.example", ".env.sample", "readme", "readme.md"}


def load_doc_texts(repo_root: Path | None) -> list[str]:
    if repo_root is None:
        return []
    texts: list[str] = []
    for name in (".env.example", ".env.sample", "README", "README.md"):
        p = repo_root / name
        try:
            if p.is_file():
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return texts


def _reads_env(text: str, ident: str) -> bool:
    name = re.escape(ident)
    if re.search(rf"(?i)\benv\??\.{name}\b", text):  # process.env.X, import.meta.env.X
        return True
    return bool(re.search(r"(?i)env", text) and re.search(rf"['\"]{name}['\"]", text))


def _assigns(text: str, ident: str) -> bool:
    return bool(re.search(rf"\b{re.escape(ident)}\b\s*(?::\s*[^=]+?)?\s*:?=(?!=)", text))


def rule_config_drift(ctx: Context) -> list[Finding]:
    docs = list(ctx.doc_texts)
    for fd in ctx.diff.files:
        if C.basename(fd.path) in DOC_BASENAMES:
            docs.append("\n".join(ln.text for ln in fd.added_lines()))
    doc_blob = "\n".join(docs)

    occurrences: dict[str, list[Evidence]] = {}
    env_read: set[str] = set()
    assigned: set[str] = set()
    for fd in ctx.diff.files:
        if fd.status == "deleted" or not C.is_production(fd.path) or not C.is_code(fd.path):
            continue
        existing: set[str] = set()
        for ln in list(fd.removed_lines()) + list(fd.context_lines()):
            existing.update(SCREAMING_RE.findall(ln.text))
        seen_here: set[str] = set()
        for ln in fd.added_lines():
            idents = SCREAMING_RE.findall(ln.text)
            line_reads_env = any(_reads_env(ln.text, i) for i in idents)
            for ident in idents:
                if ident in COMMON_CONSTANTS or ident in existing:
                    continue
                if line_reads_env:
                    env_read.add(ident)
                elif _assigns(ln.text, ident):
                    assigned.add(ident)
                if ident in seen_here:
                    continue
                seen_here.add(ident)
                occurrences.setdefault(ident, []).append(_new(fd, ln))

    findings: list[Finding] = []
    for ident in sorted(occurrences):
        # A constant defined from a literal in this diff, never read from the
        # environment, is a language constant rather than configuration.
        if ident in assigned and ident not in env_read:
            continue
        if re.search(rf"\b{re.escape(ident)}\b", doc_blob):
            continue
        findings.append(Finding(
            id="config-drift", severity=MEDIUM, section=RISK_HITS,
            message=("New configuration identifier is not documented in .env.example, "
                     ".env.sample, or README."),
            detail=ident, evidence=sorted(occurrences[ident]),
            suggested_action=(f"Document {ident} in .env.example or README, "
                              "or confirm it is not configuration."),
            rule=5,
        ))
    return findings


# 6. Dependency change --------------------------------------------------------

def rule_dependency_change(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for fd in ctx.diff.files:
        if not (C.is_dependency_file(fd.path) or C.is_dependency_file(fd.old_path or "")):
            continue
        kind = "lockfile" if C.is_lockfile(fd.path or fd.old_path or "") else "manifest"
        findings.append(Finding(
            id="dependency-change", severity=MEDIUM, section=RISK_HITS,
            message="Dependency manifest or lockfile changed.", detail=kind,
            evidence=[_ev(fd)],
            suggested_action=(f"Review the dependency change in {fd.path} "
                              "(versions, licenses, lockfile consistency)."),
            rule=6,
        ))
    return findings


# 7. Secret-shaped additions --------------------------------------------------

AWS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")
GENERIC_SECRET_RE = re.compile(
    r"(?i)\b[\w.-]*(?:token|password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?key)"
    r"[\w.-]*['\"]?\s*(?::=|=|:)\s*(['\"])([^'\"\s]{8,})\1"
)
PLACEHOLDER_MARKERS = ("<", ">", "${", "{{", "%(", "xxx", "changeme", "change_me", "example",
                       "placeholder", "dummy", "your_", "your-", "redacted", "sample",
                       "fake", "***", "todo", "replace", "insert")


def _is_placeholder(value: str) -> bool:
    low = value.lower()
    if any(m in low for m in PLACEHOLDER_MARKERS):
        return True
    if len(set(low)) <= 2:
        return True
    return low.startswith(("$", "env:", "process.env", "os.environ"))


def secret_kinds(text: str) -> list[str]:
    kinds: list[str] = []
    if AWS_KEY_RE.search(text):
        kinds.append("AWS access key ID pattern")
    if PRIVATE_KEY_RE.search(text):
        kinds.append("private key block")
    for m in GENERIC_SECRET_RE.finditer(text):
        if not _is_placeholder(m.group(2)):
            kinds.append("token/password/secret assignment")
            break
    return kinds


def rule_secrets(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for fd in ctx.diff.files:
        if fd.status == "deleted" or C.is_lockfile(fd.path):
            continue
        by_kind: dict[str, list[Evidence]] = {}
        for ln in fd.added_lines():
            for kind in secret_kinds(ln.text):
                by_kind.setdefault(kind, []).append(_new(fd, ln))
        for kind in sorted(by_kind):
            ev = by_kind[kind]
            where = ", ".join(e.render() for e in ev[:3])
            findings.append(Finding(
                id="secret-shaped-value", severity=HIGH, section=RISK_HITS,
                message="Potential secret-shaped value added; review and rotate if real.",
                detail=f"{kind}; value [REDACTED]", evidence=ev,
                suggested_action=(f"Verify the value at {where} is not a real credential; "
                                  "remove it and rotate if real."),
                rule=7,
            ))
    return findings


# 8. Retry risk ---------------------------------------------------------------

RETRY_LANG_RE = re.compile(r"(?i)retr(?:y|ies|ied|ying)|back_?off|reattempt")
LOOP_RE = re.compile(r"(?:^|[^\w.])(?:while|for|loop|until|repeat)\b|\bdo\s*\{|\.forEach\s*\(")
NETWORK_CALL_RE = re.compile(
    r"(?:\bfetch|\baxios(?:\.\w+)?|\burlopen|\brequests\.\w+|\bhttpx\.\w+|\bhttps?\.\w+|"
    r"\b\w*[Cc]lient\.\w+|\bsession\.\w+|\bapi\.\w+|\binvoke|\bsend\w*|\bconnect\w*)\s*\("
)
NUMERIC_LIMIT_RE = re.compile(
    r"(?:<=?|>=?|==|!=)\s*\d+|\brange\s*\(\s*\d+|\d+\s*\.\s*times\b|\btake\s*\(\s*\d+|"
    r"(?i:\b\w*(?:retries|attempts|tries|max\w*))\s*[:=]\s*\d+"
)
CAP_RE = re.compile(
    r"(?i)max_?retries|max_?attempts|max_?tries|retry_?limit|\blimit\b|"
    r"\b(?:attempts?|retries|tries)\s*<"
)


def _hunk_retry_evidence(hunk: Hunk) -> DiffLine | None:
    lines = [ln for ln in hunk.lines if ln.kind != "-"]
    loop_hit: DiffLine | None = None
    for idx, ln in enumerate(lines):
        if ln.kind == "+" and LOOP_RE.search(ln.text):
            window = lines[max(0, idx - 3): idx + 4]
            if any(NETWORK_CALL_RE.search(w.text) for w in window):
                loop_hit = ln
                break
    retry_hit = next((ln for ln in hunk.added if RETRY_LANG_RE.search(ln.text)), None)
    trigger = loop_hit or retry_hit  # prefer citing the loop line
    if trigger is None:
        return None
    body = "\n".join(ln.text for ln in lines)
    if NUMERIC_LIMIT_RE.search(body) or CAP_RE.search(body):
        return None
    return trigger


def rule_retry(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for fd in ctx.diff.files:
        if fd.status == "deleted" or not C.is_production(fd.path) or not C.is_code(fd.path):
            continue
        for hunk in fd.hunks:
            ln = _hunk_retry_evidence(hunk)
            if ln is None:
                continue
            findings.append(Finding(
                id="retry-cap-not-detected", severity=HIGH, section=RISK_HITS,
                message="Retry cap not detected in this diff hunk.", detail=None,
                evidence=[_new(fd, ln)],
                suggested_action="Add an explicit retry cap and a corresponding test.",
                rule=8,
            ))
    return findings


# 9. Migrations ---------------------------------------------------------------

DDL_RE = re.compile(r"(?i)\b(?:create|alter|drop)\s+(?:table|index|column|schema|view|type)\b")


def _is_migration(fd: FileDiff) -> bool:
    for path in filter(None, (fd.new_path, fd.old_path)):
        p = "/" + path.lower()
        if "/migrations/" in p:
            return True
        if p.endswith(".sql"):
            if "schema" in p:
                return True
            if any(DDL_RE.search(ln.text) for h in fd.hunks for ln in h.lines if ln.kind != " "):
                return True
    return False


def rule_migrations(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for fd in ctx.diff.files:
        if not _is_migration(fd):
            continue
        findings.append(Finding(
            id="migration", severity=HIGH, section=HUMAN_MUST_READ,
            message="Database migration or schema change requires review.", detail=None,
            evidence=[_ev(fd)],
            suggested_action=(f"Review {fd.path} for locking, backfill, and rollback "
                              "behavior before merge."),
            rule=9,
        ))
    return findings


# 10. Public surface ----------------------------------------------------------

EXPORT_RE = re.compile(r"^\s*(?:export\b|module\.exports\b|exports\.[\w$]+\s*=)")


def rule_public_surface(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for fd in ctx.diff.files:
        path = fd.path
        if not C.is_js_like(path) or C.is_test(path):
            continue
        added = [ln for ln in fd.added_lines() if EXPORT_RE.match(ln.text)]
        removed = [ln for ln in fd.removed_lines() if EXPORT_RE.match(ln.text)]
        # Lines moved verbatim are not a surface change.
        added_counts = Counter(ln.text.strip() for ln in added)
        removed_counts = Counter(ln.text.strip() for ln in removed)
        common = added_counts & removed_counts
        ev: list[Evidence] = []
        for lines, side in ((added, "new"), (removed, "old")):
            budget = Counter(common)
            for ln in lines:
                key = ln.text.strip()
                if budget[key] > 0:
                    budget[key] -= 1
                    continue
                ev.append(_new(fd, ln) if side == "new" else _old(fd, ln))
        if not ev:
            continue
        n_add = sum(1 for e in ev if e.side == "new")
        n_rem = len(ev) - n_add
        findings.append(Finding(
            id="public-export-changed", severity=MEDIUM, section=WHAT_CHANGED,
            message="Public export changed; callers may need review.",
            detail=f"{n_add} export line(s) added, {n_rem} removed",
            evidence=ev,
            suggested_action=f"Check callers of the changed exports in {path}.",
            rule=10,
        ))
    return findings


ALL_RULES = (
    rule_large_diff, rule_tests_missing, rule_deleted_tests, rule_sensitive_paths,
    rule_config_drift, rule_dependency_change, rule_secrets, rule_retry, rule_migrations,
    rule_public_surface,
)
