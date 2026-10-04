from __future__ import annotations

import pytest
from conftest import fixture_text

from vajra_verify.diffparse import DiffParseError, parse_diff


def test_empty_input_is_an_empty_diff() -> None:
    diff = parse_diff("")
    assert diff.files == []
    assert diff.lines_added == diff.lines_deleted == 0


def test_payment_fixture_line_numbers_and_statuses() -> None:
    diff = parse_diff(fixture_text("payment-retry.diff"))
    by_path = {f.path: f for f in diff.files}
    assert set(by_path) == {"src/payments/config.ts", "src/payments/retry.ts",
                            "tests/notifications/email.test.ts"}
    assert by_path["src/payments/retry.ts"].status == "added"
    assert by_path["src/payments/retry.ts"].additions == 20
    assert by_path["tests/notifications/email.test.ts"].status == "modified"
    added = list(by_path["tests/notifications/email.test.ts"].added_lines())
    assert [ln.new_no for ln in added] == [15, 16, 17, 18]
    assert diff.lines_added == 26 and diff.lines_deleted == 0


def test_deleted_file_uses_old_side_numbers() -> None:
    diff = parse_diff(fixture_text("deleted-test.diff"))
    legacy = next(f for f in diff.files if f.old_path == "tests/test_legacy.py")
    assert legacy.status == "deleted" and legacy.new_path is None
    assert legacy.first_evidence() == (1, "old")


def test_rename_and_binary_headers() -> None:
    text = (
        "diff --git a/old/name.py b/new/name.py\n"
        "similarity index 100%\n"
        "rename from old/name.py\n"
        "rename to new/name.py\n"
        "diff --git a/logo.png b/logo.png\n"
        "index 1111111..2222222 100644\n"
        "Binary files a/logo.png and b/logo.png differ\n"
    )
    diff = parse_diff(text)
    assert diff.files[0].status == "renamed"
    assert (diff.files[0].old_path, diff.files[0].new_path) == ("old/name.py", "new/name.py")
    assert diff.files[1].binary


def test_plain_diff_u_without_git_header() -> None:
    text = (
        "--- a.txt\t2024-01-01 00:00:00\n"
        "+++ a.txt\t2024-01-02 00:00:00\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    diff = parse_diff(text)
    assert diff.files[0].path == "a.txt"
    assert diff.lines_added == 1 and diff.lines_deleted == 1


def test_truncated_hunk_is_an_error_without_echoing_content() -> None:
    text = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n"
        "+password = 'hunter2hunter2'\n"
    )
    with pytest.raises(DiffParseError) as exc:
        parse_diff(text)
    assert "hunter2" not in str(exc.value)


def test_non_diff_text_is_rejected() -> None:
    with pytest.raises(DiffParseError):
        parse_diff("this is not a diff\njust words\n")
