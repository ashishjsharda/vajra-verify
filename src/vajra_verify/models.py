"""Core data types for findings and reports."""

from __future__ import annotations

from dataclasses import dataclass, field

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
SEVERITY_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

WHAT_CHANGED = "WHAT_CHANGED"
HUMAN_MUST_READ = "HUMAN_MUST_READ"
RISK_HITS = "RISK_HITS"
UNPROVEN_BEHAVIORS = "UNPROVEN_BEHAVIORS"


@dataclass(frozen=True, slots=True, order=True)
class Evidence:
    path: str
    line: int
    side: str  # "new" or "old"

    def render(self) -> str:
        suffix = " (deleted)" if self.side == "old" else ""
        return f"{self.path}:{self.line}{suffix}"

    def to_json(self) -> dict[str, object]:
        return {"path": self.path, "line": self.line, "side": self.side}


@dataclass(slots=True)
class Finding:
    id: str
    severity: str
    section: str
    message: str
    evidence: list[Evidence]
    suggested_action: str
    rule: int
    detail: str | None = None

    def sort_key(self) -> tuple[object, ...]:
        first = self.evidence[0] if self.evidence else Evidence("", 0, "new")
        return (SEVERITY_RANK[self.severity], self.rule, first.path, first.line,
                self.detail or "", self.id)

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {
            "id": self.id,
            "severity": self.severity,
            "section": self.section,
            "message": self.message,
        }
        if self.detail:
            out["detail"] = self.detail
        out["evidence"] = [e.to_json() for e in self.evidence]
        out["suggested_action"] = self.suggested_action
        return out


@dataclass(slots=True)
class Change:
    """A structural change summary for WHAT CHANGED (not a risk finding)."""

    summary: str
    evidence: list[Evidence]

    def to_json(self) -> dict[str, object]:
        return {"summary": self.summary, "evidence": [e.to_json() for e in self.evidence]}


@dataclass(slots=True)
class Report:
    branch: str
    source: dict[str, object]
    files_changed: int
    lines_added: int
    lines_deleted: int
    risk: str
    gate: str
    strict: bool
    changes: list[Change] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    additions_by_path: dict[str, int] = field(default_factory=dict)
