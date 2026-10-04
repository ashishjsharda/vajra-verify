# Contributing

Thanks for helping. Vajra Verify stays small on purpose, so a few ground rules:

- **Deterministic only.** No network calls, LLMs, telemetry, or hosted services. The same diff must always produce the same receipt.
- **Evidence or it didn't happen.** Every finding cites `path:line`. Wording stays hedged ("detected", "may", "not detected in this diff").
- **Never print secret values.** Not in receipts, JSON, exceptions, or logs.
- **New rules start as an issue.** Open a [rule request](../../issues/new?template=rule-request.yml) before writing code, so we can agree on the false-positive trade-off.

## Development

```bash
pip install -e ".[test]"
pytest
```

Every change to detection behavior needs a fixture diff in `fixtures/` and a test in `tests/`. If you change receipt output, regenerate the README sample from a real run; `tests/test_readme.py` checks that they match.

## Pull requests

Keep PRs focused and fill in the template. By contributing, you agree your work is licensed under the [MIT License](LICENSE).
