from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vajra_verify.analyze import analyze  # noqa: E402
from vajra_verify.cli import main  # noqa: E402
from vajra_verify.diffparse import parse_diff  # noqa: E402
from vajra_verify.models import Report  # noqa: E402

FIXTURES = ROOT / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def report_from_text(text: str, *, strict: bool = False,
                     doc_texts: list[str] | None = None) -> Report:
    return analyze(parse_diff(text), branch="test", source={"mode": "test"},
                   strict=strict, doc_texts=doc_texts)


def report_for(name: str, **kwargs: object) -> Report:
    return report_from_text(fixture_text(name), **kwargs)  # type: ignore[arg-type]


def ids(report: Report) -> list[str]:
    return [f.id for f in report.findings]


@pytest.fixture
def run_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Run `vajra` in-process from the repo root; returns (code, stdout, stderr)."""

    def _run(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
        old = Path.cwd()
        os.chdir(cwd or ROOT)
        try:
            argv = list(args)
            if "--output-dir" not in argv:
                argv += ["--output-dir", str(tmp_path / "out")]
            try:
                code = main(argv)
            except SystemExit as exc:  # argparse usage errors
                code = int(exc.code or 0)
        finally:
            os.chdir(old)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run
