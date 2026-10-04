"""The README's sample output must be the real payment-retry fixture output."""

from __future__ import annotations

import re

from conftest import ROOT

COMMAND = "$ vajra verify --diff fixtures/payment-retry.diff"
H1 = "# AI wrote 2,000 lines. Understand what actually changed before you merge."


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_h1_is_exact() -> None:
    assert _readme().splitlines()[0] == H1


def test_readme_sample_matches_real_fixture_output(run_cli) -> None:
    blocks = re.findall(r"```(?:text|console)?\n(.*?)```", _readme(), flags=re.S)
    sample = next(b for b in blocks if b.startswith(COMMAND))
    expected = sample[len(COMMAND) + 1:]
    code, stdout, _ = run_cli("verify", "--diff", "fixtures/payment-retry.diff")
    assert code == 1
    assert stdout == expected
