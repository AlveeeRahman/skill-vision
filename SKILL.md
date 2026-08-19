---
name: skill-vision
description: "Validate, test and score Claude Agent Skills: spec conformance, script testing, quality grade, security, token cost. Use when authoring or auditing a skill, or before uploading one to claude.ai."
metadata:
  version: "1.1.1"
---

# Skill Vision

*Boards your Agent Skills and inspects every plank before they sail — validation, script testing, and quality scoring.*

**Category**: Engineering Quality Assurance · **Dependencies**: None (Python stdlib only)

Meta-skill that validates, tests, and scores skills in this repository. Tier is computed,
not asserted: run `quality_scorer.py` and read `tier_recommendation`. Six tools, run from
the **repo root** with full paths:

1. **`scripts/spec_validator.py`** — the Agent Skills spec: does it load, upload, trigger?
2. **`scripts/claim_auditor.py`** — does the documentation tell the truth about the code?
3. **`scripts/skill_validator.py`** — structure + documentation compliance
4. **`scripts/script_tester.py`** — Python script syntax/imports/runtime/output testing
5. **`scripts/quality_scorer.py`** — multi-dimensional scoring with letter grade
6. **`scripts/security_scorer.py`** — security posture scoring (also available via `quality_scorer.py --include-security`)
7. **`scripts/skill_mapper.py`** — draws the skill's files and reference graph as a Mermaid flowchart

## Is it true, not just well-formed?

Every other tool here asks whether a skill is *structured* correctly. `claim_auditor.py`
asks whether it is *honest*. Those fail independently: a skill can pass every link check,
score an A, and still tell you in its frontmatter that a script runs offline when that
script ships your prompt to a third-party API.

```bash
python3 scripts/claim_auditor.py path/to/skill            # 0 clean · 2 contradicted
python3 scripts/claim_auditor.py path/to/skill --json
python3 scripts/claim_auditor.py path/to/skills --recursive
python3 scripts/claim_auditor.py path/to/skill --strict   # unverifiable claims fail too
```

It checks five things against the tree, never against a model's opinion: documented
commands (does the script exist, does argparse define that flag), reach claims
("offline", "stdlib only", "zero dependencies") **traced transitively through spawned
subprocesses**, inventory counts, paths named in SKILL.md/README.md, and asserted
`--help`/`--json` support.

The transitive trace is the point. A wrapper that imports nothing but `subprocess` looks
stdlib-only, and if it execs a sibling needing `requests` and an API key, it is not
offline. Judging the wrapper on its own imports is how that claim survives review.

Claims it cannot settle come back as **UNVERIFIED**, not as findings. It is deliberately
quiet about accurate disclaimers ("X is *not* an offline alternative"), historical notes,
optional `try/except ImportError` imports, placeholder filenames, and example paths in
guides. Mark a block quoting another project's commands with
`<!-- claim-audit: ignore-next-block -->` and it is skipped.

For the judgement-shaped half — stale versions, misattributed citations, unsourced
numbers, instructions that cannot be followed — [agents/hallucination-hunter.md](agents/hallucination-hunter.md)
is a subagent that runs these tools first and investigates only what they could not
decide. Every finding carries the claim as written, where it is written, and the
specific fact that contradicts it; anything it cannot settle comes back as UNVERIFIED
rather than as a finding. Copy it into `.claude/agents/` to use it.

## See the codebase, not just the verdict

The four scorers above answer "is this skill any good." `skill_mapper.py` answers a
different question: what's actually in the skill, and what can Claude reach from
SKILL.md? A file nothing links to is never read under progressive disclosure, no
matter how well it's written. That's a shape problem, and a picture shows it faster
than a list of findings does.

```bash
python3 scripts/skill_mapper.py path/to/your-skill              # Mermaid to stdout
python3 scripts/skill_mapper.py path/to/your-skill --detail      # + function/class counts, CLI flags per script
python3 scripts/skill_mapper.py path/to/your-skill --json        # the same graph as data
```

The script writes no file. It prints Mermaid to stdout, so put it in a fenced
` ```mermaid ` block in your reply — Claude Code and claude.ai both render that inline.
Save a file or publish an Artifact only if the user asks. Every node is a file that
exists, and every edge is a reference `spec_validator.py` resolved via the same
`build_graph()`, so the map and the CONFORMANT verdict can't disagree. Dashed red =
DANGLING_REFERENCE and PATH_ESCAPES_SKILL. Grey dashed = ORPHANED_REFERENCE (bundled,
unreachable). Amber dashed = REFERENCE_TOO_DEEP (reachable, but more than one hop out).

It does not draw a call graph between functions: the best published static Python
call-graph tools land around 70% recall, and a diagram that is quietly incomplete is
worse than none. Everything here is checkable against `ls` and `grep`.

> **Scope note:** this skill's tier line-count minimums measure *legacy* skills. For authoring *new* skills, `engineering/write-a-skill` (SKILL.md under ~100 lines, Matt Pocock doctrine) is the binding standard — do not pad a new skill to satisfy a tier minimum here.

## Quick Start (exact, runnable from repo root)

```bash
python3 scripts/spec_validator.py path/to/your-skill              # does it load?
python3 scripts/claim_auditor.py  path/to/your-skill              # is it true?
python3 scripts/script_tester.py  path/to/your-skill --json       # do the scripts run?
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
script rules are not applied to skills that legitimately have no scripts. Its report
header also states the skill's estimated context cost in tokens — description tokens
load every session, body tokens load when the skill triggers — so heavy skills are
visible at a glance (`--json` exposes the same numbers under `tokens`).

How this compares to `skills-ref`, `agent-ecosystem/skill-validator` and
`agent-skills-lint` — including where those tools are ahead — is in
[references/validator-comparison.md](references/validator-comparison.md).

`spec_validator.py` also reports **REFERENCE_TOO_DEEP**: a reference file more than one
link hop from SKILL.md. Anthropic's authoring guidance is explicit — *"Keep references one
level deep from SKILL.md"* — because past one hop an agent tends to preview a file with
`head -100` instead of reading it, so the end is silently never seen. This is **link
distance, not directory depth**: a file two directories down may be one hop away or six,
depending only on who links it. `DEEP_NESTING` measures directory depth and is advisory;
this one maps to a real failure.

The scripts are covered by tests: `python3 -m pytest tests/ -q` runs 196 checks,
including adversarial fixtures that build deliberately broken skills and assert each
defect is caught, a parity suite asserting `skill_mapper.py` and `spec_validator.py`
report the same broken, orphaned and too-deep files off the same graph, and false-positive
fixtures asserting that correct skills produce no findings.

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

### skill_mapper.py
- File and reference graph, resolved by the same `build_graph()` spec_validator.py uses
- Mermaid flowchart, grouped by directory; broken and unreachable references drawn as red/grey nodes
- `--detail` reads each script's function/class counts and CLI flags off the AST, no call-graph guessing
- `--json` for the same graph as data; past `--max-nodes` (default 40), oversized directories auto-collapse

## Tier Classification

| Tier | SKILL.md | Scripts | CLI surface |
|---|---|---|---|
| BASIC | ≥ 100 lines | 1 (100-300 LOC) | basic argparse |
| STANDARD | ≥ 200 lines | 1-2 (300-500 LOC) | subcommands, JSON + text output |
| POWERFUL | ≥ 300 lines | 2-3 (500-800 LOC) | multiple modes, CI integration |

**Read this table as a description of legacy skills, never as a target.** Its thresholds
measure volume; the spec measures restraint. Padding a SKILL.md to clear a line count, or
splitting one good script into two, makes a skill worse and raises its tier. Never do
either. New skills follow write-a-skill — see the scope note above.

The scorers no longer apply a tool's checklist to skills that are not tools:
`quality_scorer.py` reads the same `documentation`/`tool`/`toolkit`/`router`
classification `spec_validator.py` uses, so a guidance skill is not told to invent an
`assets/` directory or expand its scripts.

## CI Integration

```yaml
# GitHub Actions: gate changed skills
- name: "validate-changed-skills"
  run: |
    for skill in $changed_skills; do
      python3 skill-vision/scripts/spec_validator.py "$skill"
      python3 skill-vision/scripts/claim_auditor.py "$skill"
      python3 skill-vision/scripts/quality_scorer.py "$skill" --minimum-score 75
      # script_tester exits 2 for PARTIAL. `|| code=$?` is required: steps run under
      # `bash -e`, so a bare failing command aborts before any exit-code branch runs.
      code=0
      python3 skill-vision/scripts/script_tester.py "$skill" || code=$?
      [ "$code" -eq 1 ] && exit 1
      [ "$code" -eq 2 ] && echo "::warning::$skill has PARTIAL scripts"
    done
```

Pre-commit hook: run the validator on the staged skill directory and block the commit on non-zero exit.

## Verification Loop

A skill "passes" when, in one run from repo root, all four exit 0:

1. `spec_validator.py <skill>` — it loads, uploads and triggers,
2. `claim_auditor.py <skill>` — the documentation is not lying about the code,
3. `script_tester.py <skill>` — exit 0 means *every* script passed every check; exit 2
   means at least one is PARTIAL, and
4. `quality_scorer.py <skill> --minimum-score <target>`.

Check the exit code, not the summary text. `script_tester.py` exits 2 when any script is
PARTIAL — a suite of 27 partial scripts and zero passing ones is exit 2, not exit 0.

If any step fails, apply the top `improvement_roadmap` item and re-run all four — never
report a partial pass.

## Troubleshooting

- **Timeout errors** → raise `--timeout` or optimize the script under test
- **Import failures** → external deps detected; stdlib-only is the repo policy
- **Tier misclassification** → check line counts/LOC against the tier table; remember the write-a-skill exception for new skills

References: `references/` holds the structure specification, tier requirements matrix, and scoring rubric the tools implement.

A complete demo skill for practicing the tools lives at [assets/sample-skill/README.md](assets/sample-skill/README.md), with its API details in [assets/sample-skill/references/api-reference.md](assets/sample-skill/references/api-reference.md). Its manifest ships as `SKILL.md.fixture` (a package may contain exactly one `SKILL.md`) — restore the name only while testing against it.
