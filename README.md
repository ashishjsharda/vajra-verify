# AI wrote 2,000 lines. Understand what actually changed before you merge.

[![PyPI](https://img.shields.io/pypi/v/vajra-verify)](https://pypi.org/project/vajra-verify/)
[![Downloads](https://img.shields.io/pypi/dm/vajra-verify)](https://pypi.org/project/vajra-verify/)
[![Python](https://img.shields.io/pypi/pyversions/vajra-verify)](https://pypi.org/project/vajra-verify/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Vajra Verify** turns a git diff into a human-readable **change receipt**: what changed, what can break, and what a human must read before merge. It runs locally, uses deterministic rules, and never sends your code anywhere.

Here is the real output for the payment-retry fixture in this repository:

```text
$ vajra verify --diff fixtures/payment-retry.diff
VAJRA CHANGE RECEIPT
Branch: n/a (saved diff: fixtures/payment-retry.diff)
Diff: 3 files · +26 / -0 lines
Risk: HIGH · Merge gate: BLOCKED
Heuristic findings; inspect cited evidence before acting.

WHAT CHANGED
• New file src/payments/config.ts (+2) — evidence: src/payments/config.ts:1
• New file src/payments/retry.ts (+20); defines `sleep`, `chargeWithRetry` (inferred) — evidence: src/payments/retry.ts:1, src/payments/retry.ts:4, src/payments/retry.ts:6
• Modified tests/notifications/email.test.ts (+4 / -0) — evidence: tests/notifications/email.test.ts:15
• Public export changed; callers may need review. — 2 export line(s) added, 0 removed — evidence: src/payments/config.ts:1, src/payments/config.ts:2
• Public export changed; callers may need review. — 1 export line(s) added, 0 removed — evidence: src/payments/retry.ts:6

HUMAN MUST READ
1. src/payments/retry.ts — High-risk domain touched (charge, payment). — evidence: src/payments/retry.ts:1, src/payments/retry.ts:6
2. src/payments/config.ts — High-risk domain touched (payment). — evidence: src/payments/config.ts:1

RISK HITS
! [HIGH] Potential secret-shaped value added; review and rotate if real. — token/password/secret assignment; value [REDACTED] — evidence: src/payments/config.ts:1
! [HIGH] Retry cap not detected in this diff hunk. — evidence: src/payments/retry.ts:11
! [MEDIUM] New configuration identifier is not documented in .env.example, .env.sample, or README. — PAYMENT_GATEWAY_URL — evidence: src/payments/config.ts:2

UNPROVEN BEHAVIORS
• [HIGH] Source changed; relevant test change not found. — area: payments; high-risk domain — evidence: src/payments/config.ts:1, src/payments/retry.ts:1

REQUIRED BEFORE MERGE
[ ] Add or update tests covering the `payments` changes, or confirm existing coverage. — src/payments/config.ts:1
[ ] Verify the value at src/payments/config.ts:1 is not a real credential; remove it and rotate if real.
[ ] Add an explicit retry cap and a corresponding test. — src/payments/retry.ts:11
[ ] Have an owner of the payment domain review src/payments/config.ts.
[ ] Have an owner of the charge, payment domain review src/payments/retry.ts.
[ ] Document PAYMENT_GATEWAY_URL in .env.example or README, or confirm it is not configuration. — src/payments/config.ts:2
[ ] Check callers of the changed exports in src/payments/config.ts.
[ ] Check callers of the changed exports in src/payments/retry.ts.
```

Every finding cites `path:line` evidence. Added or modified lines use the new-side line number; deleted code uses the old-side line number, marked `(deleted)`. Secret-shaped values are always redacted.

## What it is, and what it is not

- **It is not an agent.** It does not edit code, open pull requests, or take actions.
- **It is not an AI reviewer.** There is no model, no LLM call, and no AI-generated summary.
- **It does not send code anywhere.** No network access, no telemetry, no accounts, no API keys. The only external program it runs is your local `git`, and only to read a diff.
- **It uses deterministic heuristics and can produce false positives.** A finding means a signal was *detected*, not that a bug, vulnerability, or breaking change definitely exists. The same diff always produces the same receipt.

## Install

Requires Python 3.11+ and `git` (only for live diffs). No runtime dependencies.

```bash
pipx install vajra-verify     # recommended: isolated `vajra` command
pip install vajra-verify      # or into the current environment
```

From source:

```bash
git clone https://github.com/ashishjsharda/vajra-verify
cd vajra-verify
pip install -e .      # editable install for development
pipx install .        # or: isolated install from the checkout
```

## Usage

```bash
vajra verify --base origin/main                  # branch vs base: git diff origin/main...HEAD
vajra verify --staged                            # staged changes: git diff --cached
vajra verify                                     # unstaged working-tree changes: git diff
vajra verify --diff path/to/change.diff          # a saved unified diff (no git needed)
vajra verify --base origin/main --strict         # also block the merge gate on MEDIUM risk
vajra verify --output-dir path/to/output         # write receipts somewhere other than .vajra-verify/
```

`--base`, `--staged`, and `--diff` are mutually exclusive.

The receipt is printed to stdout and written to `.vajra-verify/receipt.md` and `.vajra-verify/receipt.json` (or `--output-dir`). The directory is created if needed. Vajra Verify does not touch your `.gitignore`; add `.vajra-verify/` yourself if you don't want receipts tracked.

For config-drift checks, Vajra Verify reads `.env.example`, `.env.sample`, `README`, and `README.md` from the git top-level directory for live diffs. For `--diff`, the saved file isn't tied to a checkout, so no local files are read unless you pass `--repo-root DIR`. Those doc files are also honored when the diff itself adds them.

## Rules (v0)

Exactly ten deterministic rules. Severity drives the overall risk.

| # | Rule | Finding | Severity |
|---|------|---------|----------|
| 1 | Large diff | `Large diff; prioritize human review of these files.` when production lines added > 400 or files changed > 15. Up to 5 read-first files, ranked by risk-path match, then added lines. | MEDIUM |
| 2 | Tests missing | `Source changed; relevant test change not found.` when production code changed and no test changed in the same area (first two meaningful path components after `src/`, `app/`, `lib/`, `packages/<name>/src/`). If relevance can't be determined and no test changed: `Source changed; no changed test file found.` | MEDIUM (HIGH when the same area touches a sensitive path) |
| 3 | Deleted tests | A deleted test file, or removed `def test_*`, `it(`, `test(`, `describe(`, `func Test*`, `#[test]` definitions, cited with old-side lines. | HIGH |
| 4 | Sensitive paths | `High-risk domain touched.` for paths or defined symbols containing auth, payment, charge, billing, permission, webhook, migration, upload, secret, session, password. | MEDIUM |
| 5 | Config drift | `New configuration identifier is not documented in .env.example, .env.sample, or README.` for newly added `SCREAMING_SNAKE_CASE` identifiers in source. Common language constants are ignored, as are constants the diff itself assigns from a literal without reading the environment. | MEDIUM |
| 6 | Dependency change | `Dependency manifest or lockfile changed.` for package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml, and recognized lockfiles. | MEDIUM |
| 7 | Secret-shaped additions | `Potential secret-shaped value added; review and rotate if real.` for AWS access-key patterns, private-key blocks, and token/password/secret assignments with non-placeholder values. Values are never printed. | HIGH |
| 8 | Retry risk | `Retry cap not detected in this diff hunk.` when a hunk adds retry/backoff language or a loop near a network-style call, and the hunk has neither a numeric limit nor a cap pattern (`maxRetries`, `max_attempts`, `MAX_RETRIES`, `retry_limit`, `limit`, `attempt <`). A heuristic, not proof of unbounded retries. | HIGH |
| 9 | Migrations | `Database migration or schema change requires review.` for files under `migrations/` or schema-related `.sql` files. | HIGH |
| 10 | Public surface | `Public export changed; callers may need review.` for added, removed, or changed `export` statements in `.ts`, `.tsx`, `.js`, `.jsx` files (line-level, best effort). | MEDIUM |

Test files are recognized by `/test/`, `/tests/`, `/__tests__/`, `/spec/`, `*_test.py`, `test_*.py`, `.test.ts`, `.test.tsx`, `.spec.ts`, `.spec.tsx`, `*_test.go`, `*_test.rs`. Production files are everything that isn't a test, doc, fixture, recognized config, CI/workflow file, or lockfile.

## Risk and merge gate

| Overall risk | When | Merge gate | `--strict` gate |
|---|---|---|---|
| HIGH | any HIGH finding | BLOCKED | BLOCKED |
| MEDIUM | any MEDIUM finding, no HIGH | OPEN | BLOCKED |
| LOW | no findings | OPEN | OPEN |

The `REQUIRED BEFORE MERGE` checklist contains only actions that correspond to detected findings.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | LOW or MEDIUM risk; gate OPEN |
| 1 | HIGH risk, or gate BLOCKED (MEDIUM with `--strict`) |
| 2 | Usage error, invalid arguments, unreadable diff file, git failure, or diff parse error |

## JSON output

`receipt.json` is a stable report (`schema_version: "0.1"`) with `branch`, `source`, `strict`, `diff_stats` (`files_changed`, `lines_added`, `lines_deleted`), `risk`, `gate`, `changes`, and `findings`. Each finding has `id`, `severity`, `section` (`WHAT_CHANGED`, `HUMAN_MUST_READ`, `RISK_HITS`, `UNPROVEN_BEHAVIORS`), `message`, optional `detail`, `evidence` (`path`, `line`, `side`: `new` or `old`), and `suggested_action`. Ordering is deterministic and output contains no timestamps.

## CI

[`examples/github-action.yml`](examples/github-action.yml) installs the CLI and runs `vajra verify --base origin/main --strict`. An exit code of 1 fails the check.

## Development

```bash
pip install -e ".[test]"
pytest
```

The test suite runs against fixture diffs in [`fixtures/`](fixtures/) and needs no network. It also checks that the sample output above matches a real run of the payment-retry fixture.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SUPPORT.md](SUPPORT.md). Report vulnerabilities or leaked-secret bugs privately as described in [SECURITY.md](SECURITY.md).

## Author

Built by [Ashish Sharda](https://github.com/ashishjsharda).

## License

[MIT](LICENSE) © 2026 Ashish Sharda.
