"""Run the rules, summarize structural changes, and decide risk and gate."""

from __future__ import annotations

from .diffparse import Diff, FileDiff
from .models import HIGH, LOW, MEDIUM, Change, Evidence, Finding, Report
from .rules import ALL_RULES, Context, definition_name


def overall_risk(findings: list[Finding]) -> str:
    severities = {f.severity for f in findings}
    if HIGH in severities:
        return HIGH
    if MEDIUM in severities:
        return MEDIUM
    return LOW


def merge_gate(risk: str, strict: bool) -> str:
    if risk == HIGH or (risk == MEDIUM and strict):
        return "BLOCKED"
    return "OPEN"


def _defs(fd: FileDiff) -> tuple[list[tuple[str, Evidence]], list[tuple[str, Evidence]]]:
    added: list[tuple[str, Evidence]] = []
    removed: list[tuple[str, Evidence]] = []
    for ln in fd.added_lines():
        name = definition_name(ln.text)
        if name:
            added.append((name, Evidence(fd.path, ln.new_no or 1, "new")))
    for ln in fd.removed_lines():
        name = definition_name(ln.text)
        if name:
            removed.append((name, Evidence(fd.old_path or fd.path, ln.old_no or 1, "old")))
    added_names = {n for n, _ in added}
    removed_names = {n for n, _ in removed}
    return ([d for d in added if d[0] not in removed_names],
            [d for d in removed if d[0] not in added_names])


def summarize_changes(diff: Diff) -> list[Change]:
    changes: list[Change] = []
    for fd in sorted(diff.files, key=lambda f: f.path):
        a, d = fd.additions, fd.deletions
        if fd.status == "added":
            text = f"New file {fd.path} (+{a})"
        elif fd.status == "deleted":
            text = f"Deleted file {fd.old_path} (-{d})"
        elif fd.status == "renamed":
            text = f"Renamed {fd.old_path} → {fd.new_path} (+{a} / -{d})"
        else:
            text = f"Modified {fd.path} (+{a} / -{d})"
        if fd.binary:
            text += " [binary]"
        line, side = fd.first_evidence()
        evidence = [Evidence(fd.path if side == "new" else (fd.old_path or fd.path), line, side)]
        added_defs, removed_defs = _defs(fd) if fd.status != "deleted" else ([], [])
        if added_defs:
            names = ", ".join(f"`{n}`" for n, _ in added_defs[:3])
            more = f" +{len(added_defs) - 3} more" if len(added_defs) > 3 else ""
            text += f"; defines {names}{more} (inferred)"
            evidence.extend(e for _, e in added_defs[:3])
        if removed_defs:
            names = ", ".join(f"`{n}`" for n, _ in removed_defs[:3])
            more = f" +{len(removed_defs) - 3} more" if len(removed_defs) > 3 else ""
            text += f"; removes {names}{more} (inferred)"
            evidence.extend(e for _, e in removed_defs[:3])
        changes.append(Change(summary=text, evidence=sorted(set(evidence))))
    return changes


def analyze(diff: Diff, *, branch: str, source: dict[str, object], strict: bool,
            doc_texts: list[str] | None = None) -> Report:
    ctx = Context(diff=diff, doc_texts=list(doc_texts or []))
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule(ctx))
    findings.sort(key=Finding.sort_key)
    risk = overall_risk(findings)
    return Report(
        branch=branch, source=source,
        files_changed=len(diff.files), lines_added=diff.lines_added,
        lines_deleted=diff.lines_deleted, risk=risk, gate=merge_gate(risk, strict),
        strict=strict, changes=summarize_changes(diff), findings=findings,
        additions_by_path={f.path: f.additions for f in diff.files},
    )
