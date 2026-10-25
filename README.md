# Vajra Verify

**AI wrote 2,000 lines. Do you actually know what changed?**

[![PyPI](https://img.shields.io/pypi/v/vajra-verify)](https://pypi.org/project/vajra-verify/)
[![Downloads](https://img.shields.io/pypi/dm/vajra-verify)](https://pypi.org/project/vajra-verify/)
[![Python](https://img.shields.io/pypi/pyversions/vajra-verify)](https://pypi.org/project/vajra-verify/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

I built Vajra Verify because code review stopped scaling the moment AI assistants started writing most of the diff. The PR looks clean, the tests pass, and somewhere in line 1,400 there's a retry loop with no cap hitting your payment gateway.

Vajra Verify reads a git diff and gives you a **change receipt**: a short, plain-English summary of what changed, what could break, and which files a human really needs to look at before merging. It runs on your machine, uses fixed rules you can read, and never sends your code anywhere.

## See it in action

This is real output from a sample diff in this repo, a small payment-retry change:

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

In 26 lines of diff it caught a hardcoded secret, a retry loop with no limit, an undocumented env variable, and payment code with no new tests. Every finding points to an exact `file:line`, so you can jump straight to it. Secrets are always redacted in the output.

## What it is (and isn't)

I want to be upfront about this, because "AI code review" means a lot of things right now.

- **No AI inside.** There's no model and no LLM call. Vajra Verify is a set of plain rules, and the same diff always produces the same receipt.
- **Your code stays on your machine.** No network calls, no telemetry, no account, no API key. The only thing it runs is your local `git`, just to read the diff.
- **It doesn't change anything.** It won't edit code, open PRs, or take actions for you. It tells you where to look; you decide.
- **It can be wrong.** These are heuristics. A finding means "this looks worth checking," not "this is definitely a bug." Think of it as a sharp-eyed checklist, not a verdict.

## Install

You'll need Python 3.11 or newer. `git` is only needed if you're checking live changes rather than a saved diff. There are no other dependencies.

```bash
pipx install vajra-verify     # recommended: gives you a clean, isolated `vajra` command
pip install vajra-verify      # or install into your current environment
```

Want to hack on it? Install from source:

```bash
git clone https://github.com/ashishjsharda/vajra-verify
cd vajra-verify
pip install -e .      # editable install for development
pipx install .        # or an isolated install from your checkout
```

## Using it

Run it from inside your repo. Pick whichever matches what you want to check:

```bash
vajra verify --base origin/main          # your whole branch vs main (git diff origin/main...HEAD)
vajra verify --staged                    # just what you've staged (git diff --cached)
vajra verify                             # unstaged changes in your working tree (git diff)
vajra verify --diff path/to/change.diff  # a saved diff file, no git needed
```

A couple of useful options:

```bash
vajra verify --base origin/main --strict       # also block on MEDIUM risk, not just HIGH
vajra verify --output-dir path/to/output       # save receipts somewhere other than .vajra-verify/
```

`--base`, `--staged`, and `--diff` can't be combined; pick one.

The receipt prints to your terminal and is also saved as `.vajra-verify/receipt.md` (for humans) and `.vajra-verify/receipt.json` (for tools). Vajra Verify won't touch your `.gitignore`, so add `.vajra-verify/` yourself if you don't want receipts committed.

**A note on config checks:** to tell whether a new env variable is documented, Vajra Verify looks at `.env.example`, `.env.sample`, `README`, and `README.md` at the root of your repo. When you pass a saved file with `--diff`, it doesn't know which repo the diff came from, so it skips those files unless you point it at one with `--repo-root DIR`. If the diff itself adds or updates those files, that counts too.

## What it checks

Version 0 ships with ten rules. Each one has a severity, and the highest severity found sets the overall risk.

| # | What it looks for | Why it matters | Severity |
|---|---|---|---|
| 1 | **Large diff:** more than 400 production lines added, or more than 15 files changed | Big diffs are where things slip through. It suggests up to 5 files to read first, riskiest ones on top. | MEDIUM |
| 2 | **Missing tests:** production code changed but no test changed in the same area | Untested changes are unproven changes. Areas are matched by the first two folders after `src/`, `app/`, `lib/`, or `packages/<name>/src/`. | MEDIUM, or HIGH in a sensitive area |
| 3 | **Deleted tests:** a test file removed, or test functions like `def test_*`, `it(`, `test(`, `describe(`, `func Test*`, `#[test]` deleted | Deleting a test is the quickest way to make a failing build pass. | HIGH |
| 4 | **Sensitive areas:** file paths or function names containing auth, payment, charge, billing, permission, webhook, migration, upload, secret, session, or password | These are the places where a small mistake costs the most. | MEDIUM |
| 5 | **Undocumented config:** a new `SCREAMING_SNAKE_CASE` setting that isn't in `.env.example`, `.env.sample`, or the README | Saves the next person from a mystery crash on deploy. Common language constants and plain literals are ignored. | MEDIUM |
| 6 | **Dependency changes:** edits to package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml, or a lockfile | New dependencies deserve a second look. | MEDIUM |
| 7 | **Possible secrets:** AWS-style access keys, private key blocks, or token/password/secret values that aren't obvious placeholders | Catch it before it's in your git history forever. The value is never printed. | HIGH |
| 8 | **Uncapped retries:** retry or backoff logic, or a loop around a network call, with no visible limit (`maxRetries`, `max_attempts`, `MAX_RETRIES`, `retry_limit`, `limit`, `attempt <`, or a number) | Unbounded retries turn a brief outage into a hammered API or a double charge. This is a hint, not proof. | HIGH |
| 9 | **Database migrations:** files under `migrations/` or schema-related `.sql` files | Schema changes are hard to undo. | HIGH |
| 10 | **Public API changes:** `export` statements added, removed, or changed in `.ts`, `.tsx`, `.js`, `.jsx` files | Someone else's code may depend on it. Best effort, line by line. | MEDIUM |

**How it tells tests apart:** files in `/test/`, `/tests/`, `/__tests__/`, or `/spec/`, plus names like `*_test.py`, `test_*.py`, `.test.ts`, `.test.tsx`, `.spec.ts`, `.spec.tsx`, `*_test.go`, and `*_test.rs`. Anything that isn't a test, doc, fixture, known config file, CI workflow, or lockfile counts as production code.

## Risk levels and the merge gate

| Overall risk | When | Merge gate | With `--strict` |
|---|---|---|---|
| HIGH | Any HIGH finding | BLOCKED | BLOCKED |
| MEDIUM | MEDIUM findings, no HIGH | OPEN | BLOCKED |
| LOW | Nothing found | OPEN | OPEN |

The **Required before merge** checklist only lists things tied to what was actually found. No filler.

## Exit codes

Handy for scripts and CI:

| Code | Meaning |
|---|---|
| 0 | LOW or MEDIUM risk, gate OPEN |
| 1 | HIGH risk, or gate BLOCKED (MEDIUM with `--strict`) |
| 2 | Something went wrong: bad arguments, unreadable diff file, git error, or a diff that couldn't be parsed |

## Use it in CI

Drop [`examples/github-action.yml`](examples/github-action.yml) into your workflow. It installs Vajra Verify and runs `vajra verify --base origin/main --strict` on each pull request, failing the check when the gate is blocked.

## JSON output

If you want to build on top of the receipt, `receipt.json` follows a stable format (`schema_version: "0.1"`). It includes `branch`, `source`, `strict`, `diff_stats` (`files_changed`, `lines_added`, `lines_deleted`), `risk`, `gate`, `changes`, and `findings`.

Each finding has an `id`, `severity`, `section` (`WHAT_CHANGED`, `HUMAN_MUST_READ`, `RISK_HITS`, or `UNPROVEN_BEHAVIORS`), `message`, an optional `detail`, `evidence` (`path`, `line`, and `side`), and a `suggested_action`.

About `side`: added or changed lines use the new file's line number (`new`). Deleted code uses the old file's line number (`old`) and is marked `(deleted)` in the text output. The output has no timestamps and a fixed order, so receipts are easy to diff and compare.

## Contributing

Ideas, bug reports, and new rules are all welcome. To get set up:

```bash
pip install -e ".[test]"
pytest
```

Tests run against the sample diffs in [`fixtures/`](fixtures/) and don't need a network connection. One test also checks that the example output at the top of this README matches a real run, so the README can't quietly drift out of date.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [SUPPORT.md](SUPPORT.md) for help. If you find a security issue, or a case where a secret leaks into the output, please report it privately as described in [SECURITY.md](SECURITY.md) rather than opening a public issue.

## About

Built by [Ashish Sharda](https://github.com/ashishjsharda). If Vajra Verify catches something for you, I'd love to hear about it.

## License

[MIT](LICENSE) © 2026 Ashish Sharda
