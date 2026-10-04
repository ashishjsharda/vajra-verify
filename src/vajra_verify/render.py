"""Deterministic rendering of reports as a text/Markdown receipt and JSON."""

from __future__ import annotations

import json

from . import __version__
from .classify import sensitive_terms
from .models import (
    HUMAN_MUST_READ, RISK_HITS, SEVERITY_RANK, UNPROVEN_BEHAVIORS, WHAT_CHANGED, Evidence,
    Finding, Report,
)

SCHEMA_VERSION = "0.1"
MAX_EVIDENCE_SHOWN = 4
NONE_LINE = "(none detected)"


def render_evidence(evidence: list[Evidence]) -> str:
    shown = ", ".join(e.render() for e in evidence[:MAX_EVIDENCE_SHOWN])
    extra = len(evidence) - MAX_EVIDENCE_SHOWN
    return f"evidence: {shown}" + (f" (+{extra} more)" if extra > 0 else "")


def _finding_text(f: Finding) -> str:
    parts = [f.message]
    if f.detail:
        parts.append(f.detail)
    parts.append(render_evidence(f.evidence))
    return " — ".join(parts)


def _human_must_read(report: Report) -> list[str]:
    entries: dict[str, dict[str, object]] = {}
    for f in report.findings:
        if f.section != HUMAN_MUST_READ:
            continue
        reason = f.message if f.id == "large-diff" else (
            f.message.rstrip(".") + (f" ({f.detail})" if f.detail else "") + ".")
        for ev in f.evidence:
            entry = entries.setdefault(ev.path, {"reasons": [], "evidence": [], "rank": 9})
            reasons: list[str] = entry["reasons"]  # type: ignore[assignment]
            evs: list[Evidence] = entry["evidence"]  # type: ignore[assignment]
            if reason not in reasons:
                reasons.append(reason)
            if ev not in evs:
                evs.append(ev)
            entry["rank"] = min(int(entry["rank"]), SEVERITY_RANK[f.severity])  # type: ignore[arg-type]

    def key(path: str) -> tuple[object, ...]:
        return (entries[path]["rank"], 0 if sensitive_terms(path) else 1,
                -report.additions_by_path.get(path, 0), path)

    lines = []
    for i, path in enumerate(sorted(entries, key=key), start=1):
        reasons = " ".join(entries[path]["reasons"])  # type: ignore[arg-type]
        evs = sorted(entries[path]["evidence"])  # type: ignore[arg-type]
        lines.append(f"{i}. {path} — {reasons} — {render_evidence(evs)}")
    return lines


def render_receipt(report: Report) -> str:
    out: list[str] = [
        "VAJRA CHANGE RECEIPT",
        f"Branch: {report.branch}",
        f"Diff: {report.files_changed} files · +{report.lines_added} / -{report.lines_deleted} lines",
        f"Risk: {report.risk} · Merge gate: {report.gate}"
        + (" (strict)" if report.strict else ""),
        "Heuristic findings; inspect cited evidence before acting.",
        "",
        "WHAT CHANGED",
    ]
    what = [f"• {c.summary} — {render_evidence(c.evidence)}" for c in report.changes]
    what += [f"• {_finding_text(f)}" for f in report.findings if f.section == WHAT_CHANGED]
    out += what or [NONE_LINE]

    out += ["", "HUMAN MUST READ"]
    out += _human_must_read(report) or [NONE_LINE]

    out += ["", "RISK HITS"]
    hits = [f"! [{f.severity}] {_finding_text(f)}" for f in report.findings
            if f.section == RISK_HITS]
    out += hits or [NONE_LINE]

    out += ["", "UNPROVEN BEHAVIORS"]
    unproven = [f"• [{f.severity}] {_finding_text(f)}" for f in report.findings
                if f.section == UNPROVEN_BEHAVIORS]
    out += unproven or [NONE_LINE]

    out += ["", "REQUIRED BEFORE MERGE"]
    seen: set[str] = set()
    actions: list[str] = []
    for f in report.findings:
        item = f.suggested_action
        if f.evidence and not any(e.path in item for e in f.evidence):
            item += f" — {f.evidence[0].render()}"
        if item in seen:
            continue
        seen.add(item)
        actions.append(f"[ ] {item}")
    out += actions or ["(nothing required by detected signals)"]
    return "\n".join(out) + "\n"


def report_to_dict(report: Report) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "vajra-verify", "version": __version__},
        "branch": report.branch,
        "source": report.source,
        "strict": report.strict,
        "diff_stats": {
            "files_changed": report.files_changed,
            "lines_added": report.lines_added,
            "lines_deleted": report.lines_deleted,
        },
        "risk": report.risk,
        "gate": report.gate,
        "changes": [c.to_json() for c in report.changes],
        "findings": [f.to_json() for f in report.findings],
    }


def render_json(report: Report) -> str:
    return json.dumps(report_to_dict(report), indent=2, ensure_ascii=False) + "\n"
