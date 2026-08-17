# Agent Skills specification — authoritative rules

The rules `scripts/spec_validator.py` enforces, and where they come from. Keep this file
in sync with that script; when the two disagree, the sources below win.

## Contents

- [Why this is separate from the quality rubric](#why-this-is-separate-from-the-quality-rubric)
- [Frontmatter](#frontmatter)
- [Body and progressive disclosure](#body-and-progressive-disclosure)
- [File references](#file-references)
- [Description quality](#description-quality)
- [Skill types](#skill-types)
- [Sources](#sources)

---

## Why this is separate from the quality rubric

Two different questions get confused constantly:

- **Does this skill conform to the spec?** Violations break the skill — it fails to
  upload, fails to load, or never triggers. Binary, objective, non-negotiable.
- **Is this skill any good?** House conventions, section layout, script style. Opinions,
  useful ones, but a skill that ignores them still works.

`spec_validator.py` answers the first. `skill_validator.py` and `quality_scorer.py`
answer the second. Mixing them produces the failure mode where a correct, concise skill
is marked POOR for lacking a `Tier:` field that no specification mentions, while a real
defect — a description 200 characters over the hard limit — goes unreported.

---

## Frontmatter

| Field | Required | Constraint |
|---|---|---|
| `name` | Yes | 1–64 chars. Lowercase letters, digits, hyphens only. No leading, trailing, or consecutive hyphens. **Must match the parent directory name.** No XML tags. |
| `description` | Yes | 1–1024 chars, non-empty. States what the skill does **and when to use it**. No XML tags. |
| `license` | No | License name, or a reference to a bundled license file. |
| `compatibility` | No | Max 500 chars. Environment requirements only. |
| `metadata` | No | Mapping of string keys to string values. Namespace your keys to avoid collisions. |
| `allowed-tools` | No | Space-delimited pre-approved tools. Experimental; support varies by client. |

**No other top-level keys are portable.** Packaging rejects unknown fields. Custom data
belongs under `metadata:`.

Claude Code additionally understands `argument-hint`, `disable-model-invocation`,
`user-invocable`, `disallowed-tools`, `model`, `context`, `agent`, `hooks`, and
`arguments`. These are client-specific rather than part of the portable spec, so the
validator reports them as informational.

**Reserved name fragments.** Names containing `claude` or `anthropic` are reserved. Use a
`cc-` prefix instead — `cc-settings`, not `claude-settings`.

**Exactly one SKILL.md, at the root.** Nested `SKILL.md` files cause upload validation to
reject the whole package; only Claude Code's filesystem loader tolerates them. If you
need to bundle a sample skill as a fixture, rename its file (`SKILL.md.fixture`).

---

## Body and progressive disclosure

Skills load in three tiers, and this is the whole reason size matters:

| Tier | Content | Cost |
|---|---|---|
| Metadata | `name` + `description` | ~100 tokens, always in context for every installed skill |
| Instructions | SKILL.md body | Loaded whenever the skill triggers |
| Resources | `references/`, `assets/` | Loaded only when read |

So: **the description determines whether the skill fires; the body competes with the
user's actual conversation once it does.** Guidance is under 500 lines for the body, with
detail pushed into `references/`.

There is **no minimum length**. A 40-line SKILL.md that answers the question is better
than a 300-line one that pads to hit a target. Any rule that fails a skill for being too
short is measuring the wrong thing.

Scripts are a third case: they execute without being loaded into context, so only their
output costs tokens. That is why deterministic, repetitive work belongs in a script
rather than in prose instructions.

---

## File references

- Keep paths **relative to the skill root**, using forward slashes on every platform.
- Never use `../` to escape the skill directory. It resolves in a repo checkout and
  breaks the moment the skill is installed standalone — a failure that testing inside the
  source repo will not catch.
- Keep references **one level deep**. `SKILL.md → references/topic.md` is fine;
  `SKILL.md → a.md → b.md` risks the agent only partially following the chain.
- **Every bundled file should be reachable from SKILL.md.** An unlinked reference is
  never loaded, so it is pure package weight. This is the most common silent defect in
  otherwise well-built skills.
- Reference files past ~100 lines benefit from a table of contents.

---

## Description quality

The description is the only thing the agent sees when deciding whether to load the skill,
which makes it the highest-leverage text in the whole package.

- Cover **both** halves: what it does *and* when to use it. A description that only
  describes capability will under-trigger, because there is nothing for the agent to
  match a user's phrasing against.
- Include concrete trigger keywords — the words a user would actually type, including
  artifact names ("my methods section", "reviewer 2 says") rather than only category
  labels.
- Be slightly pushy. Under-triggering is the more common failure by a wide margin.
- Prefer positive routing. Negative phrasing ("do not use for X") can backfire by
  injecting exactly the keywords that cause the wrong skill to fire.
- Write in the third person.

---

## Skill types

Rules that assume every skill ships executable scripts misfire on most real skills. The
validator classifies first, then applies only the rules that fit:

| Type | Shape | Script rules apply? |
|---|---|---|
| `documentation` | SKILL.md plus references, no scripts | No |
| `tool` | Ships scripts | Yes |
| `toolkit` | Scripts plus namespaced references | Yes |
| `router` | Two or more sub-guides under `guides/` | Only where scripts exist |

Within a scripts directory, a module imported by its siblings (or prefixed with `_`) is a
**library**, not a CLI. Demanding `argparse` and a `__main__` guard from it is a category
error.

---

## Sources

- Agent Skills specification — <https://agentskills.io/specification>
- Anthropic, skill authoring best practices — <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview>
- Anthropic engineering, "Equipping agents for the real world with Agent Skills" — <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
- Anthropic skills repository — <https://github.com/anthropics/skills>

Version-sensitive details drift. Re-check the specification page before relying on an
exact numeric limit.
