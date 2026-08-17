# Contributing to skill-doctor

Thanks for considering a contribution. This is a small, focused QA tool — the bar for
changes is correctness, not size.

## Running the tests

The only development dependency is `pytest`:

```bash
pip install pytest
python3 -m pytest tests -q
```

All 117 tests must pass on Python 3.9 through 3.13 (CI runs the full matrix on every
push and pull request).

## Two hard rules

1. **The repo must stay spec-conformant.** skill-doctor validates itself; this command
   must report `CONFORMANT` (zero errors) before and after your change:

   ```bash
   python3 scripts/spec_validator.py .
   ```

2. **Standard library only in `scripts/`.** Everything under `scripts/` runs on a clean
   Python install with no `pip install` step. Do not add external runtime dependencies —
   pull requests that import third-party packages in `scripts/` will be declined.
   (`pytest` is fine, because it is a test-only dependency.)

## Proposing changes

- **Bugs and feature requests** — open a GitHub issue using the provided templates;
  they are labeled `bug` and `enhancement` automatically. For validator bugs, a minimal
  broken-skill fixture that reproduces the false positive/negative is the most useful
  thing you can include.
- **Pull requests are welcome.** Keep them small and focused. New validator checks
  should come with tests that construct a deliberately broken skill and assert the
  defect is caught — the existing tests in `tests/` show the pattern.
- For anything larger than a bugfix, open an issue first so the approach can be agreed
  before you write code.

## Checklist before opening a PR

- [ ] `python3 -m pytest tests -q` passes
- [ ] `python3 scripts/spec_validator.py .` reports `CONFORMANT`
- [ ] No new imports outside the Python standard library in `scripts/`
