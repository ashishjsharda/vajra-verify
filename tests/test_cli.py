from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT


def test_payment_fixture_exit_1_and_writes_outputs(run_cli, tmp_path: Path) -> None:
    out = tmp_path / "receipts"
    code, stdout, _ = run_cli("verify", "--diff", "fixtures/payment-retry.diff",
                              "--output-dir", str(out))
    assert code == 1
    assert stdout.startswith("VAJRA CHANGE RECEIPT\n")
    assert "Risk: HIGH · Merge gate: BLOCKED" in stdout
    assert (out / "receipt.md").read_text(encoding="utf-8") == stdout
    data = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert data["gate"] == "BLOCKED"
    assert "9c4f2e7a1b8d6f30e5a2c9b7d4f1e8a6" not in stdout + json.dumps(data)


def test_json_schema_essentials(run_cli, tmp_path: Path) -> None:
    out = tmp_path / "o"
    run_cli("verify", "--diff", "fixtures/payment-retry.diff", "--output-dir", str(out))
    data = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "0.1"
    assert isinstance(data["branch"], str)
    assert set(data["diff_stats"]) == {"files_changed", "lines_added", "lines_deleted"}
    assert data["diff_stats"] == {"files_changed": 3, "lines_added": 26, "lines_deleted": 0}
    assert data["risk"] in {"LOW", "MEDIUM", "HIGH"}
    assert data["gate"] in {"OPEN", "BLOCKED"}
    sections = {"WHAT_CHANGED", "HUMAN_MUST_READ", "RISK_HITS", "UNPROVEN_BEHAVIORS"}
    for f in data["findings"]:
        assert {"id", "severity", "section", "message", "evidence",
                "suggested_action"} <= set(f)
        assert f["severity"] in {"HIGH", "MEDIUM"} and f["section"] in sections
        assert f["evidence"]
        for ev in f["evidence"]:
            assert set(ev) == {"path", "line", "side"}
            assert isinstance(ev["line"], int) and ev["side"] in {"new", "old"}
    retry = next(f for f in data["findings"] if f["id"] == "retry-cap-not-detected")
    assert retry == {
        "id": "retry-cap-not-detected",
        "severity": "HIGH",
        "section": "RISK_HITS",
        "message": "Retry cap not detected in this diff hunk.",
        "evidence": [{"path": "src/payments/retry.ts", "line": 11, "side": "new"}],
        "suggested_action": "Add an explicit retry cap and a corresponding test.",
    }


def test_default_output_dir_is_created(run_cli, tmp_path: Path) -> None:
    diff = tmp_path / "change.diff"
    diff.write_text((ROOT / "fixtures/low-risk.diff").read_text(), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    old = Path.cwd()
    os.chdir(work)
    try:
        from vajra_verify.cli import main
        code = main(["verify", "--diff", str(diff)])
    finally:
        os.chdir(old)
    assert code == 0
    assert (work / ".vajra-verify" / "receipt.md").is_file()
    assert (work / ".vajra-verify" / "receipt.json").is_file()
    assert not (work / ".gitignore").exists()


def test_medium_exits_0_without_strict_and_1_with_strict(run_cli) -> None:
    code, stdout, _ = run_cli("verify", "--diff", "fixtures/missing-test.diff")
    assert code == 0 and "Risk: MEDIUM · Merge gate: OPEN" in stdout
    code, stdout, _ = run_cli("verify", "--diff", "fixtures/missing-test.diff", "--strict")
    assert code == 1 and "Risk: MEDIUM · Merge gate: BLOCKED (strict)" in stdout


def test_low_exits_0_even_with_strict(run_cli) -> None:
    code, stdout, _ = run_cli("verify", "--diff", "fixtures/low-risk.diff", "--strict")
    assert code == 0 and "Risk: LOW · Merge gate: OPEN" in stdout


def test_incompatible_sources_are_usage_errors(run_cli) -> None:
    code, _, err = run_cli("verify", "--staged", "--diff", "fixtures/low-risk.diff")
    assert code == 2 and "not allowed with" in err
    code, _, err = run_cli("verify", "--base", "main", "--staged")
    assert code == 2


def test_unreadable_diff_file_is_exit_2(run_cli) -> None:
    code, stdout, err = run_cli("verify", "--diff", "fixtures/does-not-exist.diff")
    assert code == 2 and stdout == "" and "cannot read diff file" in err


def test_malformed_diff_is_exit_2_without_echo(run_cli, tmp_path: Path) -> None:
    bad = tmp_path / "bad.diff"
    bad.write_text("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n"
                   "+token = 'abcd1234efgh5678'\n", encoding="utf-8")
    code, stdout, err = run_cli("verify", "--diff", str(bad))
    assert code == 2 and "could not parse diff" in err
    assert "abcd1234" not in stdout + err


def test_missing_subcommand_is_exit_2(run_cli) -> None:
    code, _, _ = run_cli()
    assert code == 2


# Live git modes -------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "orders").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "src" / "orders" / "service.py").write_text("def total(xs):\n    return sum(xs)\n")
    (root / "README.md").write_text("Set ORDERS_DOCUMENTED_FLAG to enable.\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "checkout", "-q", "-b", "feature/orders")
    return root


def test_base_mode_against_git(repo: Path, run_cli, monkeypatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    (repo / "src" / "orders" / "service.py").write_text(
        "def total(xs):\n    return sum(xs) + ORDERS_DOCUMENTED_FLAG + ORDERS_NEW_FLAG\n")
    _git(repo, "commit", "-qam", "change")
    code, stdout, _ = run_cli("verify", "--base", "main", cwd=repo)
    assert code == 0
    assert "Branch: feature/orders" in stdout
    assert "src/orders/service.py:2" in stdout
    assert "ORDERS_NEW_FLAG" in stdout            # undocumented -> flagged
    assert "ORDERS_DOCUMENTED_FLAG" not in stdout  # found in README.md


def test_staged_and_working_tree_modes(repo: Path, run_cli) -> None:
    target = repo / "src" / "orders" / "service.py"
    target.write_text("def total(xs):\n    return sum(xs) * 1\n")
    _git(repo, "add", ".")
    code, stdout, _ = run_cli("verify", "--staged", cwd=repo)
    assert code == 0 and "Modified src/orders/service.py (+1 / -1)" in stdout
    code, stdout, _ = run_cli("verify", cwd=repo)
    assert code == 0 and "Diff: 0 files" in stdout  # nothing unstaged
    target.write_text("def total(xs):\n    return sum(xs) * 2\n")
    code, stdout, _ = run_cli("verify", cwd=repo)
    assert "Modified src/orders/service.py (+1 / -1)" in stdout


def test_bad_base_ref_is_exit_2(repo: Path, run_cli) -> None:
    code, _, err = run_cli("verify", "--base", "no-such-ref", cwd=repo)
    assert code == 2 and "git diff" in err
