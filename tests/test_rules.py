from __future__ import annotations

from conftest import ids, report_for, report_from_text

from vajra_verify.models import Evidence
from vajra_verify.render import render_json, render_receipt


def new_file_diff(path: str, lines: list[str]) -> str:
    body = "".join(f"+{ln}\n" for ln in lines)
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n"
            f"+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}")


def finding(report, fid):
    matches = [f for f in report.findings if f.id == fid]
    assert matches, f"{fid} not in {ids(report)}"
    return matches[0]


# Empty / low risk ---------------------------------------------------------------

def test_empty_diff_is_low_and_open() -> None:
    report = report_from_text("")
    assert report.risk == "LOW" and report.gate == "OPEN" and report.findings == []
    receipt = render_receipt(report)
    assert "Diff: 0 files · +0 / -0 lines" in receipt
    assert "Risk: LOW · Merge gate: OPEN" in receipt
    assert receipt.splitlines()[4] == "Heuristic findings; inspect cited evidence before acting."


def test_docs_only_change_is_low() -> None:
    report = report_for("low-risk.diff")
    assert report.findings == []
    assert report.risk == "LOW" and report.gate == "OPEN"


# 1. Large diff ------------------------------------------------------------------

def test_large_diff_by_production_lines() -> None:
    lines = [f"value_{i} = {i}" for i in range(401)]
    report = report_from_text(new_file_diff("src/big/module.py", lines))
    f = finding(report, "large-diff")
    assert f.severity == "MEDIUM"
    assert f.message == "Large diff; prioritize human review of these files."
    assert f.evidence == [Evidence("src/big/module.py", 1, "new")]


def test_large_diff_by_file_count_ranks_risky_paths_first() -> None:
    parts = [new_file_diff(f"src/mod{i:02d}/file.py", ["x = 1"] * (i + 1)) for i in range(15)]
    parts.append(new_file_diff("src/payments/charge.py", ["y = 2"]))
    report = report_from_text("".join(parts))
    f = finding(report, "large-diff")
    paths = [e.path for e in f.evidence]
    assert len(paths) == 5
    assert paths[0] == "src/payments/charge.py"
    assert paths[1] == "src/mod14/file.py"  # then by added-line count


def test_400_production_lines_is_not_large() -> None:
    lines = [f"value_{i} = {i}" for i in range(400)]
    report = report_from_text(new_file_diff("src/big/module.py", lines))
    assert "large-diff" not in ids(report)


# 2. Tests missing ---------------------------------------------------------------

def test_missing_relevant_test_change() -> None:
    report = report_for("missing-test.diff")
    f = finding(report, "relevant-test-not-found")
    assert f.message == "Source changed; relevant test change not found."
    assert f.severity == "MEDIUM"
    assert f.section == "UNPROVEN_BEHAVIORS"
    assert f.evidence == [Evidence("src/orders/service.py", 11, "new")]
    assert report.risk == "MEDIUM" and report.gate == "OPEN"


def test_test_in_same_area_satisfies_rule() -> None:
    report = report_for("sensitive-path.diff")
    assert "relevant-test-not-found" not in ids(report)


def test_unknown_area_with_no_tests_reports_no_changed_test_file() -> None:
    report = report_from_text(new_file_diff("main.py", ["print('hi')"]))
    f = finding(report, "no-test-changes")
    assert f.message == "Source changed; no changed test file found."


def test_unknown_relevance_is_not_reported_as_missing() -> None:
    text = (new_file_diff("src/orders/service.py", ["x = 1"])
            + new_file_diff("tests/test_everything.py", ["def test_x():", "    pass"]))
    report = report_from_text(text)
    assert not {"relevant-test-not-found", "no-test-changes"} & set(ids(report))


# 3. Deleted tests ---------------------------------------------------------------

def test_deleted_tests_cite_old_side_lines() -> None:
    report = report_for("deleted-test.diff")
    deleted = [f for f in report.findings if f.id == "deleted-test"]
    assert all(f.severity == "HIGH" for f in deleted)
    evidence = {e for f in deleted for e in f.evidence}
    assert Evidence("tests/orders/test_service.py", 23, "old") in evidence
    assert Evidence("tests/test_legacy.py", 1, "old") in evidence
    receipt = render_receipt(report)
    assert "tests/orders/test_service.py:23 (deleted)" in receipt
    assert "tests/test_legacy.py:1 (deleted)" in receipt
    assert report.risk == "HIGH" and report.gate == "BLOCKED"


def test_renamed_test_function_in_place_is_not_a_deletion() -> None:
    text = ("diff --git a/tests/a/test_x.py b/tests/a/test_x.py\n--- a/tests/a/test_x.py\n"
            "+++ b/tests/a/test_x.py\n@@ -1,2 +1,2 @@\n-def test_one():\n+def test_one():\n"
            "     assert 1\n")
    assert "deleted-test" not in ids(report_from_text(text))


def test_removed_js_it_block_detected() -> None:
    text = ("diff --git a/src/cart/cart.test.ts b/src/cart/cart.test.ts\n"
            "--- a/src/cart/cart.test.ts\n+++ b/src/cart/cart.test.ts\n@@ -4,3 +4,0 @@\n"
            "-  it(\"adds items\", () => {\n-    expect(1).toBe(1);\n-  });\n")
    f = finding(report_from_text(text), "deleted-test")
    assert f.evidence == [Evidence("src/cart/cart.test.ts", 4, "old")]


# 4. Sensitive paths -------------------------------------------------------------

def test_sensitive_path_alone_is_medium() -> None:
    report = report_for("sensitive-path.diff")
    f = finding(report, "sensitive-path")
    assert f.severity == "MEDIUM"
    assert f.message == "High-risk domain touched."
    assert f.detail == "auth, session"
    assert report.risk == "MEDIUM"


def test_sensitive_plus_missing_tests_escalates_to_high() -> None:
    report = report_from_text(new_file_diff("src/billing/invoice.py", ["total = 0"]))
    assert finding(report, "sensitive-path").severity == "MEDIUM"
    assert finding(report, "relevant-test-not-found").severity == "HIGH"
    assert report.risk == "HIGH"


def test_sensitive_symbol_name_detected() -> None:
    text = new_file_diff("src/core/handlers.py", ["def handle_webhook(event):", "    return event"])
    f = finding(report_from_text(text), "sensitive-path")
    assert f.detail == "webhook"
    assert Evidence("src/core/handlers.py", 1, "new") in f.evidence


# 5. Config drift ----------------------------------------------------------------

def test_config_drift_flags_undocumented_identifier() -> None:
    report = report_for("config-drift.diff")
    f = finding(report, "config-drift")
    assert f.detail == "REPORTS_EXPORT_BUCKET"
    assert f.message == ("New configuration identifier is not documented in .env.example, "
                         ".env.sample, or README.")
    assert f.evidence == [Evidence("src/reports/settings.py", 3, "new")]
    # DEFAULT_TIMEOUT already existed in context, so it is not new.
    assert all(x.detail != "DEFAULT_TIMEOUT" for x in report.findings)


def test_literal_constant_defined_in_diff_is_not_config() -> None:
    text = new_file_diff("src/sync/limits.py", ["MAX_BATCH_SIZE = 500",
                                                "HOST_URL = os.environ['SYNC_HOST_URL']"])
    report = report_from_text(text)
    flagged = sorted(f.detail for f in report.findings if f.id == "config-drift")
    assert flagged == ["HOST_URL", "SYNC_HOST_URL"]


def test_config_drift_respects_documentation() -> None:
    report = report_for("config-drift.diff", doc_texts=["REPORTS_EXPORT_BUCKET=my-bucket\n"])
    assert "config-drift" not in ids(report)


def test_config_drift_respects_env_example_added_in_same_diff() -> None:
    from conftest import fixture_text
    text = fixture_text("config-drift.diff") + new_file_diff(
        ".env.example", ["REPORTS_EXPORT_BUCKET="])
    assert "config-drift" not in ids(report_from_text(text))


# 6. Dependency change -----------------------------------------------------------

def test_dependency_manifest_and_lockfile() -> None:
    report = report_for("dependency.diff")
    deps = [f for f in report.findings if f.id == "dependency-change"]
    assert sorted(e.path for f in deps for e in f.evidence) == ["package-lock.json",
                                                                "package.json"]
    assert all(f.severity == "MEDIUM" for f in deps)
    assert deps[0].message == "Dependency manifest or lockfile changed."


# 7. Secrets ---------------------------------------------------------------------

FAKE_AWS = "AKIA" + "QZ7RW3MX5TPL2KVN"
FAKE_TOKEN = "zq81" + "kd02lm55x9"
PRIVATE_KEY_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"


def test_secret_shaped_values_are_detected_and_redacted() -> None:
    text = new_file_diff("src/integrations/keys.py", [
        f'AWS_KEY_ID = "{FAKE_AWS}"',
        f'api_token = "{FAKE_TOKEN}"',
        f'KEY = """{PRIVATE_KEY_HEADER}',
        'password = "changeme"',
    ])
    report = report_from_text(text)
    secrets = [f for f in report.findings if f.id == "secret-shaped-value"]
    kinds = sorted(f.detail.split(";")[0] for f in secrets)
    assert kinds == ["AWS access key ID pattern", "private key block",
                     "token/password/secret assignment"]
    assert all(f.severity == "HIGH" for f in secrets)
    token_finding = next(f for f in secrets if f.detail.startswith("token"))
    assert token_finding.evidence == [Evidence("src/integrations/keys.py", 2, "new")]  # not line 4
    output = render_receipt(report) + render_json(report)
    for value in (FAKE_AWS, FAKE_TOKEN, "QZ7RW3MX5TPL2KVN", "changeme", "BEGIN RSA"):
        assert value not in output
    assert "[REDACTED]" in output


def test_placeholder_secret_is_ignored() -> None:
    text = new_file_diff("src/conf/defaults.py", ['api_key = "<your-api-key-here>"'])
    assert "secret-shaped-value" not in ids(report_from_text(text))


# 8. Retry ------------------------------------------------------------------------

def test_retry_without_cap_is_high() -> None:
    report = report_for("retry-uncapped.diff")
    f = finding(report, "retry-cap-not-detected")
    assert f.message == "Retry cap not detected in this diff hunk."
    assert f.severity == "HIGH"
    assert f.evidence == [Evidence("src/sync/client.py", 9, "new")]


def test_retry_with_numeric_limit_is_not_flagged() -> None:
    assert "retry-cap-not-detected" not in ids(report_for("retry-capped.diff"))


def test_retry_with_named_cap_is_not_flagged() -> None:
    text = new_file_diff("src/jobs/worker.ts", [
        "while (attempt < maxRetries) {",
        "  await client.send(job);",
        "  attempt++;",
        "}",
    ])
    assert "retry-cap-not-detected" not in ids(report_from_text(text))


def test_plain_loop_without_network_call_is_not_flagged() -> None:
    text = new_file_diff("src/math/sum.py", ["def total(xs):", "    for x in xs:",
                                             "        yield x * 2"])
    assert "retry-cap-not-detected" not in ids(report_from_text(text))


# 9. Migrations ------------------------------------------------------------------

def test_migration_is_high() -> None:
    report = report_for("migration.diff")
    f = finding(report, "migration")
    assert f.severity == "HIGH"
    assert f.message == "Database migration or schema change requires review."
    assert f.evidence == [Evidence("db/migrations/0003_add_orders_index.sql", 1, "new")]
    assert report.gate == "BLOCKED"


def test_schema_sql_outside_migrations_dir() -> None:
    text = new_file_diff("db/schema.sql", ["ALTER TABLE orders ADD COLUMN note text;"])
    assert "migration" in ids(report_from_text(text))


# 10. Public surface -------------------------------------------------------------

def test_public_export_change() -> None:
    report = report_for("public-export.diff")
    f = finding(report, "public-export-changed")
    assert f.severity == "MEDIUM"
    assert f.message == "Public export changed; callers may need review."
    assert set(f.evidence) == {Evidence("src/ui/button.ts", 1, "new"),
                               Evidence("src/ui/button.ts", 1, "old")}
    assert report.risk == "MEDIUM"


def test_moved_export_line_is_not_a_change() -> None:
    text = ("diff --git a/src/ui/a.ts b/src/ui/a.ts\n--- a/src/ui/a.ts\n+++ b/src/ui/a.ts\n"
            "@@ -1,2 +1,2 @@\n-export const A = 1;\n const x = 2;\n+export const A = 1;\n")
    assert "public-export-changed" not in ids(report_from_text(text))


# Payment-retry end to end -------------------------------------------------------

def test_payment_retry_fixture_is_high_and_blocked() -> None:
    report = report_for("payment-retry.diff")
    assert report.risk == "HIGH" and report.gate == "BLOCKED"
    sensitive = [f for f in report.findings if f.id == "sensitive-path"]
    assert any("payment" in (f.detail or "") for f in sensitive)
    assert finding(report, "retry-cap-not-detected").evidence == [
        Evidence("src/payments/retry.ts", 11, "new")]
    missing = finding(report, "relevant-test-not-found")
    assert missing.severity == "HIGH" and "payments" in (missing.detail or "")
    output = render_receipt(report) + render_json(report)
    assert "9c4f2e7a1b8d6f30e5a2c9b7d4f1e8a6" not in output


def test_every_semantic_finding_cites_evidence() -> None:
    for name in ("payment-retry.diff", "deleted-test.diff", "migration.diff",
                 "dependency.diff", "config-drift.diff", "public-export.diff"):
        report = report_for(name)
        assert report.findings
        for f in report.findings:
            assert f.evidence, f.id
        receipt = render_receipt(report)
        for line in receipt.splitlines():
            if line.startswith(("• ", "! ")) or line[:1].isdigit():
                assert "evidence: " in line, line
        assert "claims" not in receipt.lower()


def test_rendering_is_deterministic() -> None:
    a = report_for("payment-retry.diff")
    b = report_for("payment-retry.diff")
    assert render_receipt(a) == render_receipt(b)
    assert render_json(a) == render_json(b)
