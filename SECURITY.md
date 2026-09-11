# Security Policy

## Posture

- **Everything runs locally.** The scripts in this repository make no network calls,
  collect no telemetry, and send nothing anywhere. They read the skill directory you
  point them at and print a report.
- **Zero runtime dependencies.** Python standard library only — there is no third-party
  supply chain to audit beyond Python itself (`pytest` is used for development testing
  only).
- **One deliberate exception to "read-only":** `scripts/script_tester.py` executes the
  Python scripts of the skill under test (with a timeout) in order to test them. Only
  run it against skill code you trust, exactly as you would before running that code
  yourself.
- **Scanned on every push.** NVIDIA SkillSpector (static analyzers, pinned version) runs in
  CI; reviewed false positives are listed with reasons in `.skillspector-baseline.yaml`, and
  each run's summary shows what was suppressed.

## Reporting a vulnerability

Report suspected vulnerabilities by opening a
[GitHub issue](https://github.com/AlveeeRahman/skill-vision/issues) on this repository.
Since this tool runs entirely locally and holds no user data, public reporting is
acceptable; include the affected script, a reproduction, and the impact you see.

## Supported versions

Only the latest commit on `main` is supported with fixes.
