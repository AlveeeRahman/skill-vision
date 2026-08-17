# How this validator compares to other tooling

An honest capability map against the skill validators available publicly, so you know
when to reach for something else. Researched February 2026; tooling in this space moves
quickly, so re-check before relying on a row.

## Contents

- [The alternatives](#the-alternatives)
- [Capability map](#capability-map)
- [Where this one is genuinely ahead](#where-this-one-is-genuinely-ahead)
- [Where the others are ahead](#where-the-others-are-ahead)
- [Recommended combination](#recommended-combination)

## The alternatives

| Tool | What it is |
|---|---|
| **`skills-ref` / `agentskills validate`** | The official reference validator from the `agentskills/agentskills` repo. Frontmatter and naming conformance. |
| **`agent-ecosystem/skill-validator`** | The most capable third-party CLI. Spec checks, link resolution, token counts, contamination analysis, optional LLM-as-judge scoring. |
| **`swarmclawai/agent-skills-lint`** | npx linter with install, index, and cross-install name-collision detection. |
| **`Flash-Brew-Digital/validate-skill`** | GitHub Action wrapping spec validation with optional reference checking. |
| **this skill** | `spec_validator.py` for conformance, `skill_validator.py` + `quality_scorer.py` + `security_scorer.py` for quality and security. |

## Capability map

| Check | skills-ref | skill-validator | agent-skills-lint | this skill |
|---|:--:|:--:|:--:|:--:|
| Frontmatter required fields | ✅ | ✅ | ✅ | ✅ |
| `name` charset / length / directory match | ✅ | ✅ | ✅ | ✅ |
| `description` 1024-char limit | ✅ | ✅ | ✅ | ✅ |
| `compatibility` 500-char limit | ✅ | ✅ | — | ✅ |
| Unknown frontmatter keys | ✅ | ✅ | ✅ | ✅ |
| Reserved name fragments (`claude`, `anthropic`) | — | — | — | ✅ |
| Nested `SKILL.md` detection | — | ✅ | ✅ | ✅ |
| Dangling file references | — | ✅ | opt-in | ✅ |
| `../` escapes above skill root | — | — | — | ✅ |
| Orphaned / unreachable bundled files | — | ✅ | — | ✅ |
| Transitive reachability from SKILL.md | — | ✅ | — | ✅ |
| Token counts | — | ✅ (exact) | — | ⚠️ estimated |
| Body line / token ceiling | — | ✅ | — | ✅ |
| Unclosed code fences | — | ✅ | — | ✅ |
| Junk files (`__pycache__`, `.DS_Store`) | — | ✅ | — | ✅ |
| YAML flow-sequence portability | — | — | — | ✅ |
| **Skill-type awareness** (doc / tool / router) | — | — | — | ✅ |
| **Library vs CLI script distinction** | — | — | — | ✅ |
| Description trigger-quality heuristics | — | ✅ | — | ✅ |
| Script syntax / runtime testing | — | — | — | ✅ |
| Security scanning | — | — | — | ✅ |
| Quality scoring with letter grades | — | ✅ (LLM) | — | ✅ (rubric) |
| Cross-install name collisions | — | — | ✅ | — |
| Cross-language contamination analysis | — | ✅ | — | — |
| LLM-as-judge scoring | — | ✅ | — | — |
| Runs offline, zero dependencies | ✅ | — | — | ✅ |

## Where this one is genuinely ahead

**Skill-type awareness.** Every other validator applies one rule set to every skill. That
is the single largest source of false failures in practice: a documentation-only skill
gets marked down for having no `scripts/` directory, and a router skill for having no
tests. This validator classifies first — `documentation`, `tool`, `toolkit`, `router` —
and only applies the rules that fit. Adding this alone moved five of our own skills from
NEEDS_IMPROVEMENT to ACCEPTABLE or better without changing a line of their content.

**Library vs CLI distinction.** A module imported by its siblings is not a CLI, and
demanding `argparse` and a `__main__` guard from it is a category error no other tool
avoids.

**`../` escape detection.** Relative paths that climb above the skill root resolve fine
in a repo checkout and break the moment the skill is installed standalone. Testing inside
the source repo will never catch this. It is the defect most likely to ship undetected,
and we found it in real published skills.

**Reserved name fragments.** Names containing `claude` or `anthropic` are reserved; no
other validator checks for it.

**Fix-oriented output.** Every finding carries a `→` line saying what to do, not just
what is wrong.

## Where the others are ahead

**Exact token counts.** `skill-validator` uses a real tokenizer; this one estimates at
~4 characters per token to stay dependency-free. The estimate is fine for budgeting and
wrong for precise accounting. If you need exact numbers, use `skill-validator` or pipe
files through `tiktoken`.

**LLM-as-judge scoring.** `skill-validator` can score clarity, actionability and novelty
with a model. This validator is entirely deterministic — faster, free, offline, and
unable to assess whether prose is any good.

**Cross-install collision detection.** `agent-skills-lint` finds two skills with the same
name across your install directories. Worth running separately if you install widely.

**Contamination analysis.** `skill-validator` detects cross-language contamination in
multilingual skills. Not implemented here.

## Recommended combination

No single tool covers everything. A reasonable pipeline:

```bash
# 1. Conformance — fast, offline, catches what breaks a skill
python3 scripts/spec_validator.py path/to/skill --strict

# 2. Quality and security — house standard, script testing
python3 scripts/skill_validator.py path/to/skill
python3 scripts/security_scorer.py path/to/skill

# 3. Official conformance second opinion, before publishing
skills-ref validate path/to/skill

# 4. Exact token accounting, if the budget is tight
#    (agent-ecosystem/skill-validator)
```

Running `skills-ref` as well is worthwhile: it is the reference implementation, so it is
the definition of conformance where anything disagrees. This validator aims to catch
strictly more, not to replace it.
