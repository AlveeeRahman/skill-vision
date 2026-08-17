---
name: skill-pirate
description: "Validate, test, and score the quality of skills within the claude-skills ecosystem. Comprehensive meta-skill: structure validation, Python script testing (syntax + imports + runtime + output format), multi-dimensional quality scoring with letter grades and tier classification (BASIC/STANDARD/POWERFUL). Use when authoring a new skill, auditing existing skills for tier promotion, setting up pre-commit hooks for skill quality, or integrating skill QA into CI."
---

# Skill Pirate

*Boards your Agent Skills and inspects every plank before they sail — validation, script testing, and quality scoring.*

**Tier**: POWERFUL · **Category**: Engineering Quality Assurance · **Dependencies**: None (Python stdlib only)

Meta-skill that validates, tests, and scores skills in this repository. Four tools, run from the **repo root** with full paths:

1. **`scripts/skill_validator.py`** — structure + documentation compliance
2. **`scripts/script_tester.py`** — Python script syntax/imports/runtime/output testing
3. **`scripts/quality_scorer.py`** — multi-dimensional scoring with letter grade
4. **`scripts/security_scorer.py`** — security posture scoring (also available via `quality_scorer.py --include-security`)

> **Scope note:** this skill's tier line-count minimums measure *legacy* skills. For authoring *new* skills, `engineering/write-a-skill` (SKILL.md under ~100 lines, Matt Pocock doctrine) is the binding standard — do not pad a new skill to satisfy a tier minimum here.

## Quick Start (exact, runnable from repo root)

```bash
# 1. Validate structure (exit non-zero on failure — usable as a gate)
python3 scripts/skill_validator.py path/to/your-skill --json

# 2. Test the skill's Python scripts (30s default timeout per script)
python3 scripts/script_tester.py path/to/your-skill --json

# 3. Score quality (fail CI below threshold with --minimum-score)
python3 scripts/quality_scorer.py path/to/your-skill --json --detailed --minimum-score 75
```

Consume the JSON: validator emits `overall_score`, `compliance_level`, per-check `checks{}`; scorer emits `overall_score`, `letter_grade`, `tier_recommendation`, `dimensions`, and an `improvement_roadmap` — work the roadmap top-down, then re-run until the target score is met.

## Spec conformance vs quality score

Two separate questions, two separate tools. Run both.

```bash
# 1. Does it conform to the Agent Skills spec? Failures here break the skill.
python3 scripts/spec_validator.py path/to/skill
python3 scripts/spec_validator.py path/to/skills-dir --recursive
python3 scripts/spec_validator.py path/to/skill --strict   # warnings fail too

# 2. Is it any good by this repo's house standard? Failures here are opinions.
python3 scripts/skill_validator.py path/to/skill
```

`spec_validator.py` checks the rules that determine whether a skill loads, uploads and
triggers: name charset and directory match, the 1024-character description limit, the
500-character compatibility limit, unknown frontmatter keys, nested `SKILL.md` files,
dangling and escaping file references, orphaned bundled files, and the 500-line body
ceiling. It classifies the skill first (`documentation`, `tool`, `toolkit`, `router`) so
script rules are not applied to skills that legitimately have no scripts.

How this compares to `skills-ref`, `agent-ecosystem/skill-validator` and
`agent-skills-lint` — including where those tools are ahead — is in
[references/validator-comparison.md](references/validator-comparison.md).

Both scripts are covered by tests: `python3 -m pytest tests/ -q` runs 93 checks,
including adversarial fixtures that build deliberately broken skills and assert each
defect is caught.

The authoritative rules and their sources are in
[references/agent-skills-spec.md](references/agent-skills-spec.md). Scoring rubric detail
is in [references/quality-scoring-rubric.md](references/quality-scoring-rubric.md), tier
definitions in [references/tier-requirements-matrix.md](references/tier-requirements-matrix.md),
and structural expectations in
[references/skill-structure-specification.md](references/skill-structure-specification.md).

**Where the two disagree, the spec wins.** The house standard asks for a minimum SKILL.md
length, `Tier`/`Category`/`Version` frontmatter, and a `scripts/` directory. None of those
appear in the specification. Do not pad a concise skill, or invent scripts it does not
need, to raise a score.

For repo-wide auditing the upstream claude-skills repository provides an `audit_skills` script at its repository root (not bundled with this skill), which wraps the write-a-skill checklist runner across all skills. That script is part of the repository, not of this skill package — to audit many skills here, loop `scripts/skill_validator.py` over the directories instead:

```bash
for d in path/to/skills/*/; do python3 scripts/skill_validator.py "$d"; done
```

## What Each Tool Checks

### skill_validator.py
- SKILL.md frontmatter parsing, required sections, minimum line counts per tier (`--tier BASIC|STANDARD|POWERFUL`)
- Required structure: SKILL.md, README.md, scripts/, references/, assets/, expected_outputs/
- Python scripts: argparse present, stdlib-only imports

### script_tester.py
- AST-based syntax validation; import analysis (flags external dependencies)
- Controlled execution with timeout protection (`--timeout`, default 30s)
- `--help` functionality verification; sample-data runs compared against expected_outputs/

### quality_scorer.py
Four dimensions, 25% each: **Documentation** (depth, examples, references), **Code Quality** (complexity, error handling, output consistency), **Completeness** (required dirs, sample data, expected outputs), **Usability** (help text, example clarity). Outputs 0-100 + A-F grade + tier recommendation.

## Tier Classification

| Tier | SKILL.md | Scripts | CLI surface |
|---|---|---|---|
| BASIC | ≥ 100 lines | 1 (100-300 LOC) | basic argparse |
| STANDARD | ≥ 200 lines | 1-2 (300-500 LOC) | subcommands, JSON + text output |
| POWERFUL | ≥ 300 lines | 2-3 (500-800 LOC) | multiple modes, CI integration |

(Advisory for legacy skills; new skills follow write-a-skill — see scope note above.)

## CI Integration

```yaml
# GitHub Actions: gate changed skills
- name: "validate-changed-skills"
  run: |
    for skill in $changed_skills; do
      python3 skill-pirate/scripts/skill_validator.py "$skill" --json
      python3 skill-pirate/scripts/script_tester.py "$skill"
      python3 skill-pirate/scripts/quality_scorer.py "$skill" --minimum-score 75
    done
```

Pre-commit hook: run the validator on the staged skill directory and block the commit on non-zero exit.

## Verification Loop

A skill "passes" when, in one run from repo root:

1. `skill_validator.py <skill> --json` exits 0,
2. `script_tester.py <skill>` reports all scripts passing, and
3. `quality_scorer.py <skill> --minimum-score <target>` exits 0.

If any step fails, apply the top `improvement_roadmap` item and re-run all three — never report a partial pass.

## Troubleshooting

- **Timeout errors** → raise `--timeout` or optimize the script under test
- **Import failures** → external deps detected; stdlib-only is the repo policy
- **Tier misclassification** → check line counts/LOC against the tier table; remember the write-a-skill exception for new skills

References: `references/` holds the structure specification, tier requirements matrix, and scoring rubric the tools implement.
