# Training Log — skill-pirate

This file is a machine-parseable log of real maintenance events on this repository
(`https://github.com/Gol-D-Al/skill-pirate`). It exists so a local model can be
fine-tuned on how this repo's maintainer actually works: what changed, why, how it was
verified, what tends to go wrong, and what failure looked like when it happened.
Every entry is grounded in the git history or the working tree at the time of writing —
nothing here is invented.

## Schema for entries

Each event is one `## entry-NNN: <title>` section. Every entry contains exactly the
following labeled fields, as a bullet list, in this order, with these meanings:

```
- **timestamp**: ISO date of the event (YYYY-MM-DD)
- **task_type**: one of repo-init | rename | docs | ci | community-health | agent-behavior | cleanup
- **instruction**: what the maintainer was trying to achieve, phrased imperatively like a prompt
- **context**: repo/world state before the action
- **action_taken**: what was done, naming real files
- **diff_summary**: compact factual summary of the change
- **rationale**: why this action and not the alternatives
- **verification**: commands run and their actual results
- **likely_errors**: realistic failure modes of this kind of change
- **outcome**: success | failure | fixed-after-failure
- **lesson**: one transferable sentence
```

Rules for authors (human or agent): never invent file paths — reference only files that
exist in the repo (this file is itself link-checked by `scripts/spec_validator.py`);
record verification output as it actually appeared, including failures; if an event
failed and was fixed, log it as `fixed-after-failure` rather than pretending it went
smoothly — failure entries are the most valuable training signal in this file.

## entry-000: This training log

- **timestamp**: 2026-08-17
- **task_type**: docs
- **instruction**: Create `TRAINING_LOG.md` at the repo root: a strict, labeled-field log of every real maintenance event so far, suitable as fine-tuning data for a local maintainer model.
- **context**: The repo had one commit (6746799) plus a set of uncommitted community-health/CI/docs changes in the working tree, and two undocumented pre-push events (the double rename and the repo-keeper hallucination incident) that existed only in the maintainer's memory and shell history.
- **action_taken**: Ran `git log --stat`, `git status`, and `git diff` to ground every claim; read `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `.github/workflows/ci.yml`, and both issue templates; wrote this file with one entry per event in the schema above.
- **diff_summary**: One new file, `TRAINING_LOG.md`, ~8 entries; no existing file modified.
- **rationale**: A labeled, fixed-order field schema is trivially parseable into (instruction, context, action, outcome) training pairs, unlike free-form prose in a CHANGELOG; putting it at repo root keeps it next to the history it describes. Paths are written as inline code rather than markdown links because `scripts/spec_validator.py` link-checks every `.md` file in the repo and a stylistic link to a moved file would fail validation.
- **verification**: After writing: `/Users/alverahmanakash/Desktop/dev/metal_env/bin/python -m pytest tests -q` → `93 passed`; `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors)`.
- **likely_errors**: Referencing a path that does not exist (spec_validator reports `DANGLING_REFERENCE` and the repo stops being CONFORMANT); drifting from the field order so downstream parsers break; retroactively embellishing events instead of logging what actually happened.
- **outcome**: success
- **lesson**: A training log is only as good as its grounding — derive every entry from `git log`/`git diff`/real command output, and log failures with the same rigor as successes.

## entry-001: Initial release as a standalone repository

- **timestamp**: 2026-08-17
- **task_type**: repo-init
- **instruction**: Extract the skill-QA meta-skill from the claude-skills monorepo into its own standalone repository, with the repo root being the skill itself, and make the initial commit.
- **context**: The skill lived inside a claude-skills monorepo where it validated sibling skills. Standalone, the directory layout had to double as a valid Agent Skills package: `SKILL.md` at root, tools under `scripts/`, docs under `references/`, a demo skill under `assets/`, and `expected_outputs/` populated.
- **action_taken**: Created commit 6746799 ("Initial release: skill-pirate — QA meta-skill for Agent Skills", author MrPirate) containing 23 files: `SKILL.md`, `README.md`, `.gitignore`, five stdlib-only tools (`scripts/spec_validator.py`, `scripts/skill_validator.py`, `scripts/script_tester.py`, `scripts/quality_scorer.py`, `scripts/security_scorer.py`), five reference docs under `references/`, the test suite (`tests/test_spec_validator.py`, `tests/test_security_scorer.py`), a complete sample skill under `assets/sample-skill/` (with `assets/sample-skill/SKILL.md.fixture` as its fixture manifest), and `expected_outputs/sample_validation_report.json`.
- **diff_summary**: 23 files changed, 8145 insertions(+), 0 deletions — everything new.
- **rationale**: Making the repo root the skill itself (rather than nesting the skill one level down) means the tool can validate itself with `python3 scripts/spec_validator.py .`, which becomes both the smoke test and the marketing claim; a QA tool that cannot pass its own checks is folklore.
- **verification**: `python3 -m pytest tests -q` → 93 passed; `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors)`; `git log --stat` confirms 23 files / 8145 insertions in 6746799.
- **likely_errors**: Monorepo extraction leaving behind `../`-style relative paths that escape the new root (spec_validator flags these as `PATH_ESCAPES_SKILL`); forgetting to carry test fixtures over so the suite passes in the monorepo but not standalone; committing editor/OS junk on the first commit because `.gitignore` was written last.
- **outcome**: success
- **lesson**: When extracting a component into its own repo, make the extracted root satisfy the packaging spec directly so self-validation is a one-command smoke test.

## entry-002: Rename twice before first push (skill-tester → skill-shakedown → skill-pirate)

- **timestamp**: 2026-08-17
- **task_type**: rename
- **instruction**: Give the project a unique name before its first public push; if the working name collides with existing projects, rename until it does not.
- **context**: The working name was `skill-tester`. Web research showed the name was already taken several times over — `Facets-cloud/claude-skill-tester`, `skill-tester-swarm`, `openclaw-skill-tester`, plus `skill-tester` directories inside claude-skills monorepos — and the first alternative considered, `skillassay`, was also taken. `skill-shakedown` was verified unique, but the owner preferred `skill-pirate` (also unique; its nearest neighbor is Google Gemini's unrelated `pirate-skill` conversational demo, a name distance documented in the README).
- **action_taken**: Renamed the project twice: `skill-tester` → `skill-shakedown` → `skill-pirate`. Each rename touched four places in lockstep: the directory name, the `name:` field in `SKILL.md` frontmatter, the headings/prose in `SKILL.md` and `README.md`, and every documentation path that embedded the old name. A "Why skill-pirate, and not another skill-tester?" section was added to `README.md` recording the collision research.
- **diff_summary**: Directory rename plus string replacement of the project name across `SKILL.md`, `README.md`, and `references/` docs; no code logic changed.
- **rationale**: A colliding name costs discoverability and invites confusion with unmaintained lookalikes; renaming before the first push is nearly free, while renaming after publication breaks clones, badges, and inbound links. The renames could not be partial: the Agent Skills spec requires SKILL.md frontmatter `name:` to match the directory name, so directory, frontmatter, and docs had to change together or the repo would fail its own validator.
- **verification**: After each of the two renames: `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors)` and `python3 -m pytest tests -q` → 93/93 passed. The name-collision claims were verified by web search against the live projects listed above.
- **likely_errors**: Renaming the directory but not the frontmatter `name:` (spec_validator fails the name/directory match check); stale old-name strings surviving in prose or example commands; case-only renames silently misbehaving on macOS's case-insensitive filesystem; forgetting that the GitHub remote URL also embeds the name.
- **outcome**: success
- **lesson**: A rename is a single atomic change spread across many files — enumerate every place the name is load-bearing (directory, manifest, docs, remotes) and verify with the spec validator after each step, not just at the end.

## entry-003: Community health files (LICENSE, CONTRIBUTING, SECURITY, templates)

- **timestamp**: 2026-08-17
- **task_type**: community-health
- **instruction**: Add the standard community health files a public GitHub repo needs: a license, contribution guidelines, a security policy, and issue/PR templates.
- **context**: After the initial commit the repo had no `LICENSE` (legally "all rights reserved" despite being public), no stated contribution rules, and no templates, so issues would arrive unstructured. These files are currently untracked in the working tree (`git status` shows `?? LICENSE`, `?? CONTRIBUTING.md`, `?? SECURITY.md`, `?? .github/`).
- **action_taken**: Created `LICENSE` (MIT, copyright 2026 MrPirate); `CONTRIBUTING.md` with two hard rules — `python3 scripts/spec_validator.py .` must stay `CONFORMANT` before and after any change, and `scripts/` stays Python-stdlib-only (pytest allowed as a test-only dependency); `SECURITY.md` stating everything runs locally with no network calls or telemetry, plus the honest caveat that `scripts/script_tester.py` deliberately executes the skill-under-test's Python scripts (with a timeout), so it should only be pointed at trusted code; `.github/ISSUE_TEMPLATE/bug_report.md` (auto-label `bug`, asks for script, command, output, minimal broken-skill reproduction) and `.github/ISSUE_TEMPLATE/feature_request.md` (auto-label `enhancement`, asks which of the five tools the check belongs in and includes a stdlib-only constraints checkbox); `.github/PULL_REQUEST_TEMPLATE.md` whose checklist mirrors CI exactly (pytest passes, spec_validator CONFORMANT, no non-stdlib imports in `scripts/`).
- **diff_summary**: Six new files (`LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, two issue templates, one PR template); no existing file modified in this event.
- **rationale**: MIT matches the "zero friction, run it anywhere" positioning of a stdlib-only tool; the two hard rules in `CONTRIBUTING.md` encode the repo's only real invariants instead of generic style prose; the security policy admits the `script_tester.py` execution behavior up front because hiding it would be discovered anyway and cost trust; templates mirror CI so contributors self-check before the robot does.
- **verification**: `/Users/alverahmanakash/Desktop/dev/metal_env/bin/python -m pytest tests -q` → `93 passed`; `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors, 1 warnings, 4 notes)` — the new markdown introduced no dangling references because spec_validator link-checks every `.md` file in the repo.
- **likely_errors**: Issue templates with malformed YAML frontmatter (GitHub silently falls back to a blank issue form); `labels:` naming labels that don't exist in the repo so auto-labeling fails; a security policy that overclaims ("fully sandboxed") and is later contradicted by the code; adding markdown that links to files which don't exist, which this repo's own validator turns into a hard failure.
- **outcome**: success
- **lesson**: Community health files should encode the project's actual invariants and actual risks — a checklist that mirrors CI and a security policy that admits what the tool really executes beat boilerplate.

## entry-004: GitHub Actions CI workflow

- **timestamp**: 2026-08-17
- **task_type**: ci
- **instruction**: Add a CI workflow that runs the test suite across all supported Python versions and self-validates the repo against the Agent Skills spec on every push and pull request.
- **context**: The repo had no CI; the README claimed broad Python support that nothing was actually testing. The two commands a contributor must keep green (`pytest` and `spec_validator.py .`) existed but ran only on the maintainer's machine.
- **action_taken**: Created `.github/workflows/ci.yml`: triggers on push and pull_request to `main`; top-level least-privilege `permissions: contents: read`; a `fail-fast: false` matrix over Python 3.9, 3.10, 3.11, 3.12, 3.13 on ubuntu-latest; steps are `actions/checkout@v7`, `actions/setup-python@v7`, `pip install pytest`, `python -m pytest tests -q`, and a final self-validation step `python scripts/spec_validator.py .`. Action major versions v7 were verified current against the GitHub releases pages as of August 2026 rather than copied from older examples.
- **diff_summary**: One new file, `.github/workflows/ci.yml` (36 lines): 1 workflow, 1 job, 5-version matrix, 5 steps.
- **rationale**: The matrix's floor (3.9) and ceiling (3.13) define the support claim the docs are allowed to make — which forced the README's stale "3.7+" claim to change in entry-005; `fail-fast: false` so one version's failure still shows results for the others; least-privilege permissions because the job only reads the checkout; the spec_validator step makes CI enforce CONTRIBUTING.md's hard rule #1 mechanically. Pinned-to-major (`@v7`) was chosen over SHA-pinning as the usual trade-off for a small repo: auto-patching over supply-chain paranoia.
- **verification**: Local equivalents of every CI step: `/Users/alverahmanakash/Desktop/dev/metal_env/bin/python -m pytest tests -q` → `93 passed`; `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors)`. The workflow itself cannot run before the branch is pushed — a known, accepted gap recorded in likely_errors.
- **likely_errors**: The README's CI badge shows "no status" until the workflow's first run on GitHub (known and accepted here); YAML that lints locally but is rejected by Actions (wrong key nesting, unquoted version numbers like 3.10 parsing as 3.1); using outdated action majors from copied examples; a matrix floor lower than the code's real syntax requirements so old-Python jobs fail on syntax the maintainer never runs locally.
- **outcome**: success
- **lesson**: CI should mechanically enforce exactly the invariants CONTRIBUTING.md states, and the test matrix — not the README — is the source of truth for what "supported" means.

## entry-005: README brought up to standalone-repo standard

- **timestamp**: 2026-08-17
- **task_type**: docs
- **instruction**: Upgrade `README.md` for a public standalone repo: badges, a table of contents, a copy-pasteable Getting Started section, and version claims that match what CI actually tests.
- **context**: `README.md` was written for the monorepo era: no badges, no TOC, no clone-and-run instructions, a "Python 3.7+" claim nothing verified, an embedded CI example using outdated `actions/checkout@v3` / `actions/setup-python@v4`, and a Contributing section that pointed at `SKILL.md` because `CONTRIBUTING.md` did not exist yet.
- **action_taken**: Modified `README.md` (uncommitted, visible in `git diff`): added four badges (CI status for the `ci.yml` workflow, MIT license, Python 3.9+, zero runtime dependencies); a 16-entry table of contents; a Getting Started section with a `git clone` flow, the three main commands, and the self-test trick `python3 scripts/spec_validator.py .` for users with no skill handy; updated all "Python 3.7+" claims to "Python 3.9+ (CI-tested on 3.9–3.13)"; refreshed the embedded CI example to `checkout@v7` / `setup-python@v7` / Python 3.13; repointed the Contributing section to `CONTRIBUTING.md` (summarizing its two hard rules) and added a License section pointing at `LICENSE`.
- **diff_summary**: `README.md` +59/−11 lines (269 → ~317 lines): badges, TOC, Getting Started added; version claims 3.7+ → 3.9+; action versions v3/v4 → v7; Contributing/License sections rewritten.
- **rationale**: The version claim was changed to match CI rather than widening CI to match the claim, because an untested claim is a latent bug report; the Getting Started section leads with "no install step" since zero-dependency clone-and-run is the tool's main adoption advantage; the badge was added before the workflow's first run, accepting a temporary "no status" badge over forgetting to add it later.
- **verification**: `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors)` — significant because spec_validator link-checks every `.md` file, so the new TOC anchors and the new links to `CONTRIBUTING.md` and `LICENSE` are machine-verified to resolve; `/Users/alverahmanakash/Desktop/dev/metal_env/bin/python -m pytest tests -q` → `93 passed` (README changes cannot break tests, run as a habit-invariant anyway).
- **likely_errors**: TOC anchor slugs not matching GitHub's slugification of unusual headings (quotes, em-dashes — this README has both); badge URLs pointing at the wrong workflow filename or branch; docs claiming support for Python versions CI does not test; embedded example snippets drifting out of date again because nothing executes them.
- **outcome**: success
- **lesson**: Documentation claims that nothing enforces will drift — tie every claim in the README (versions, badges, commands) to something CI or a validator actually checks.

## entry-006: repo-keeper agent hallucinated paths in its first issue reply

- **timestamp**: 2026-08-17
- **task_type**: agent-behavior
- **instruction**: Put the repo under watch by "repo-keeper", a local autonomous maintainer agent (Ollama running qwen3.5:9b, with aider for code edits) that replies to GitHub issues and fixes CI failures on `agent/*` branches behind quality gates, and never pushes to `main` — then verify its first live cycle is trustworthy.
- **context**: repo-keeper was newly wired to this repo. GitHub issue #1 arrived asking "what does this project do?" — a softball question fully answered by `README.md` and `SKILL.md`. The orchestrator's triage prompt at that point contained only the issue text, with no repository content.
- **action_taken**: FAILURE FIRST: repo-keeper answered issue #1 with a hallucinated reply — it invented a `validators/` directory and a `./run_validators.sh` script, neither of which exists anywhere in the repo (the real tools live in `scripts/` and there is no shell script in the project). Root cause: with no repository content in the prompt, the model produced a plausible-sounding generic answer. FIX: the orchestrator's triage/reply prompts were changed to inject a "REPOSITORY CONTEXT" block (full `SKILL.md`, the head of `README.md`, and the repo file list) plus the explicit rule "never invent paths; say unsure if the context lacks the answer"; the hallucinated comment on issue #1 was deleted.
- **diff_summary**: No change to this repo's files — the fix landed in the repo-keeper orchestrator's prompt assembly; on GitHub, one hallucinated issue comment deleted and one grounded reply posted.
- **rationale**: Deleting the bad comment mattered as much as fixing the prompt, because a public wrong answer about the repo's layout would keep misleading readers; context injection was chosen over fine-tuning or a bigger model because the failure was an information-availability problem, not a capability problem — the model was never shown the repo it was asked about.
- **verification**: Re-test with a harder, path-specific question ("where exactly are the validator scripts?") posted to the agent: the reply was fully grounded, correctly naming `scripts/spec_validator.py` and all five real validator/scorer scripts, with no invented paths. Manual `ls` against every path in both replies confirmed the first was fabricated and the second was accurate.
- **likely_errors**: An LLM agent asked about a codebase it cannot see will confidently invent idiomatic-looking paths (`validators/`, `run_*.sh`) rather than say it does not know; context injection can still fail if the injected excerpt omits the relevant file, or silently truncates on small local-model context windows; deleted comments survive in email notifications, so speed of correction matters.
- **outcome**: fixed-after-failure
- **lesson**: Never let an agent answer questions about a repository whose content is not in its prompt — ground every reply in injected repository context and require "unsure" over invention.

## entry-007: Fixture audit and local junk cleanup

- **timestamp**: 2026-08-17
- **task_type**: cleanup
- **instruction**: Audit `assets/sample-skill/SKILL.md.fixture` for redundancy (tests appear to build their own fixtures) and remove any local junk files from the working tree.
- **context**: The working tree had accumulated macOS and pytest artifacts (`.DS_Store`, `.pytest_cache/`, `__pycache__/`), and `.gitignore` did not yet cover `.pytest_cache/`; spec_validator's `JUNK_FILES` warning listed them. The sample-skill fixture looked like dead weight because the test suite never reads it.
- **action_taken**: Investigated and KEPT `assets/sample-skill/SKILL.md.fixture`: the tests in `tests/test_spec_validator.py` do construct their own throwaway fixtures, but the README's demo flow uses the bundled sample skill, and the `.fixture` suffix is load-bearing — the Agent Skills spec allows exactly one `SKILL.md` per package, so renaming it to `SKILL.md` would make `python3 scripts/spec_validator.py .` fail the whole repo (two manifests found). Also kept `expected_outputs/sample_validation_report.json`, which fills the required `expected_outputs/` directory. Deleted local junk only: `.DS_Store`, `.pytest_cache/`, `__pycache__/`. Extended `.gitignore` with `.pytest_cache/` (it already covered `.DS_Store`, `__pycache__/`, `*.pyc`).
- **diff_summary**: `.gitignore` +1 line (`.pytest_cache/`); untracked junk deleted from disk; zero tracked project files removed — the investigated fixture and expected-output files were deliberately retained.
- **rationale**: "Unused by tests" is not the same as "unused" — the fixture serves the README demo and the spec's one-manifest-per-package rule explains its odd suffix, so deleting or renaming it would break either the docs or the validator; the durable fix for regenerating junk is `.gitignore`, since `.pytest_cache/` reappears on every test run no matter how often it is deleted.
- **verification**: `/Users/alverahmanakash/Desktop/dev/metal_env/bin/python -m pytest tests -q` → `93 passed` (confirming nothing deleted was needed); `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors)`; `git status` clean of junk apart from the intentional `.gitignore` modification (note: running pytest regenerates `.pytest_cache/`, which is exactly why it went into `.gitignore`).
- **likely_errors**: Deleting a "redundant" fixture that documentation or demo flows silently depend on; renaming a `.fixture` file to its real name and colliding with a one-per-package spec rule; cleaning junk without updating `.gitignore` so it returns on the next test run; overly broad ignore patterns (`*.json`) that swallow tracked files.
- **outcome**: success
- **lesson**: Before deleting an apparently redundant file, check every consumer — docs, demos, and spec rules — not just the test suite, and prefer a `.gitignore` entry over repeated manual deletion for anything that regenerates.

## entry-008: README made interactive per 2026 best practices

- **timestamp**: 2026-08-17
- **task_type**: docs
- **instruction**: Make the README genuinely interactive the way top 2026 open-source repos present — research current best practice on the live web first, then apply it without deleting substantive content.
- **context**: README already had badges, a TOC, and Getting Started from the community-health pass, but read as one long static page; the repo owner explicitly asked for "more interactive things" and mandated web research via Firecrawl before editing.
- **action_taken**: A research-first agent ran three Firecrawl searches (awesome-readme corpus, high-star README guides, GitHub/GitLab flavored-markdown docs), then added: a "Try it in 30 seconds" block under the badges with genuine `python3 scripts/spec_validator.py .` output; a mermaid `flowchart LR` of the five-validator pipeline; a ✅/❌ comparison table inside the "Why skill-pirate" section; collapsible `<details>` blocks around six long sections (Features, CI/CD Integration, Quality Standards, Advanced Usage, Error Handling, Output Formats) with H2 headings left visible so TOC anchors keep working; curated emoji on 4 of 18 H2s; a rebuilt TOC; and a footer CTA noting the repo is maintained by an autonomous local agent.
- **diff_summary**: Only README.md modified; all prior prose preserved (long sections collapsed, not removed); net structure went from a flat page to above-the-fold proof + expand-on-demand detail.
- **rationale**: Research showed the 2026 pattern is dense above-the-fold (badges → one-liner → quick start → immediate proof) with `<details>` and native mermaid for depth; GFM requires blank lines inside `<details>` tags or content renders literal, so the blocks were written to that rule rather than guessed.
- **verification**: `python3 scripts/spec_validator.py .` → `CONFORMANT (0 errors, 1 warnings, 4 notes)`; `/Users/alverahmanakash/Desktop/dev/metal_env/bin/python -m pytest tests -q` → `93 passed`; spec_validator's link-checker scans fenced blocks too, so the mermaid and sample-output blocks were confirmed free of dangling backticked paths.
- **likely_errors**: Missing blank lines inside `<details>` making markdown render as literal text; exotic mermaid syntax failing GitHub's renderer (kept to quoted single-line labels); emoji headings shifting GitHub slug anchors and silently breaking the TOC; badge/footer links 404ing until the referenced files are actually pushed.
- **outcome**: success
- **lesson**: Interactivity in a README is structure, not decoration — put proof above the fold, collapse depth behind `<details>`, and verify renderer-specific rules (blank lines, slugs, mermaid dialect) instead of assuming markdown is markdown.

## How to add entries

Append new events to the end of this file as `## entry-NNN: <title>` sections, where
NNN continues the sequence (next: entry-009). Copy the exact field list from the schema
block at the top — same fields, same order, one bullet per field. Ground every claim in
`git log`, `git diff`, or real command output; paste verification results as they
actually appeared. Use inline code for file paths, reference only paths that exist
(this file is link-checked by `scripts/spec_validator.py`), and record failures honestly
with `outcome: failure` or `fixed-after-failure` — a truthful failure entry is worth
more as training data than a polished success. After appending, re-run
`python3 scripts/spec_validator.py .` and confirm the repo is still `CONFORMANT`.
