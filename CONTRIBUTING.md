# Contributing

Use synthetic calendars only in issues, pull requests, and tests. Real calendar
exports can expose private identities, descriptions, locations and schedules.
Report a bug with the command, dependency versions, a small synthetic before/after
pair, expected occurrences, and the actual report. A clean report is limited to
the supported profile and explicit time window.

```bash
python -m venv .venv
# Activate the environment with the command for your platform.
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check .
ruff format --check .
python -m build
```

Add a regression that fails for the reported behavior and a nearby valid control.
Use explicit matching rules; do not add title matching, guessed UID changes, or
silent fallbacks that turn an incomplete interpretation into a clean report.
Dependency upgrades must rerun recurrence, DST, embedded-timezone, resource-limit,
privacy and installed-CLI tests. The parser runs in a fresh process for each input.

AI-assisted contributions are welcome with disclosure of the tool and which
implementation or validation work it helped perform. Review and test generated
changes; do not claim human review or verification that did not happen.
