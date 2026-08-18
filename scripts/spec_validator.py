#!/usr/bin/env python3
"""Agent Skills specification conformance validator.

Checks a skill against the published Agent Skills specification
(https://agentskills.io/specification) plus the progressive-disclosure guidance in
Anthropic's skill-authoring docs. Complements skill_validator.py, which scores
house-style quality; this script checks the rules that actually determine whether a
skill loads, uploads, and triggers correctly.

Why this exists: the quality scorer enforces a house standard (tier frontmatter,
minimum line counts, a mandatory scripts/ directory). Those are opinions. The checks
here are the spec, and violating them breaks the skill rather than lowering its grade.

Standard library only. No network. Usage:

    python spec_validator.py path/to/skill
    python spec_validator.py path/to/skill --json
    python spec_validator.py path/to/skills-dir --recursive
    python spec_validator.py path/to/skill --strict     # warnings become failures
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --- Specification constants -------------------------------------------------------
# Source: https://agentskills.io/specification  (field table, name/description rules)
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Fields Claude Code understands beyond the portable spec. Not errors, but worth naming
# so authors know they are client-specific.
CLIENT_FIELDS = {
    "argument-hint", "disable-model-invocation", "user-invocable",
    "disallowed-tools", "model", "context", "agent", "hooks", "arguments",
}
# Reserved substrings in skill names, per Claude Code frontmatter validation.
RESERVED_NAME_FRAGMENTS = ("anthropic", "claude")

# Progressive-disclosure guidance (Anthropic skill-authoring docs).
SKILL_MD_MAX_LINES = 500          # hard guidance: keep the body under 500 lines
SKILL_MD_WARN_LINES = 300         # start suggesting extraction
DESCRIPTION_WARN_CHARS = 950      # close enough to 1024 to be fragile
REFERENCE_TOC_LINES = 100         # reference files past this should carry a TOC

# Token budgets. Loading is what actually costs context; lines are only a proxy.
# ~4 chars/token approximates BPE closely enough for budgeting without pulling in a
# tokenizer dependency.
CHARS_PER_TOKEN = 4
BODY_TOKEN_WARN = 5000            # spec guidance ceiling for the SKILL.md body
BODY_TOKEN_TARGET = 2500          # widely-recommended practical target
DESCRIPTION_TOKEN_NOTE = 250      # descriptions load every session, for every skill

# Files that should never ship inside a skill package.
JUNK_PATTERNS = (
    "__pycache__", ".pytest_cache", ".DS_Store", ".git", "node_modules",
    ".ipynb_checkpoints", ".venv", ".mypy_cache", ".ruff_cache",
)
JUNK_SUFFIXES = (".pyc", ".pyo", ".swp", ".orig", ".rej")


def est_tokens(text: str) -> int:
    """Approximate token count without a tokenizer dependency."""
    return max(1, round(len(text) / CHARS_PER_TOKEN))


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Finding:
    severity: str          # error | warning | info
    code: str
    message: str
    fix: str = ""


@dataclass
class Result:
    skill: str
    skill_type: str = "unknown"
    findings: list = field(default_factory=list)
    # Estimated context cost, ~4 chars/token: `description` loads into every
    # session; `body` loads when the skill triggers (how Claude Code's own
    # doctor reports per-skill cost).
    tokens: dict = field(default_factory=dict)

    def add(self, severity: str, code: str, message: str, fix: str = "") -> None:
        self.findings.append(Finding(severity, code, message, fix))

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def conformant(self) -> bool:
        return self.count("error") == 0


# --- Frontmatter parsing -----------------------------------------------------------

def split_frontmatter(text: str):
    """Return (frontmatter_text, body, error) without requiring PyYAML."""
    if not text.startswith("---"):
        return None, text, "SKILL.md does not begin with YAML frontmatter (`---`)."
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.S)
    if not m:
        return None, text, "Frontmatter opening `---` has no matching closing `---`."
    return m.group(1), text[m.end():], None


def parse_frontmatter(fm_text: str) -> dict:
    """Minimal top-level YAML mapping parser.

    Handles `key: value`, block scalars (| and >), and nested mappings well enough to
    recover top-level keys and scalar values. Uses PyYAML when available for accuracy.
    """
    try:
        import yaml  # type: ignore
        loaded = yaml.safe_load(fm_text)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass

    def flush(key, buffer, block_scalar):
        """A key with no inline value gathers indented lines. If they all look
        like `sub: value` pairs (and no block scalar was requested), the spec
        meant a nested mapping — flattening it to a string made valid
        `metadata:` blocks fail the mapping check on machines without PyYAML."""
        items = [b for b in buffer if b]
        if (not block_scalar and items
                and all(re.match(r"^[^\s:#][^:]*:", b) for b in items)):
            sub = {}
            for b in items:
                k, _, v = b.partition(":")
                sub[k.strip()] = v.strip().strip('"').strip("'")
            return sub
        return " ".join(items).strip()

    data, current, buffer, block = {}, None, [], False
    for raw in fm_text.splitlines():
        if raw.strip().startswith("#") or not raw.strip():
            if current and buffer:
                buffer.append("")
            continue
        if raw[:1] in " \t":                      # continuation / nested
            if current is not None:
                buffer.append(raw.strip())
            continue
        if current is not None:
            data[current] = flush(current, buffer, block)
            current, buffer, block = None, [], False
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        if value in ("|", ">", "|-", ">-", ""):
            current, buffer, block = key, [], value != ""
        else:
            data[key] = value.strip('"').strip("'")
    if current is not None:
        data[current] = flush(current, buffer, block)
    return data


# --- Skill type detection ----------------------------------------------------------

def detect_type(root: Path) -> str:
    """Classify the skill so rules can adapt instead of assuming every skill has scripts."""
    has_scripts = any((root / "scripts").rglob("*.py")) if (root / "scripts").is_dir() else False
    guides = list((root / "guides").glob("*.md")) if (root / "guides").is_dir() else []
    ref_dirs = [d for d in (root / "references").iterdir()
                if d.is_dir()] if (root / "references").is_dir() else []
    if len(guides) >= 2:
        return "router"          # composite skill dispatching to sub-guides
    if has_scripts and ref_dirs:
        return "toolkit"
    if has_scripts:
        return "tool"
    return "documentation"


# --- Checks ------------------------------------------------------------------------

def check_structure(root: Path, res: Result) -> str | None:
    if not root.is_dir():
        res.add("error", "NOT_A_DIRECTORY", f"{root} is not a directory.",
                "A skill is a directory containing SKILL.md.")
        return None
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        res.add("error", "MISSING_SKILL_MD", "No SKILL.md at the skill root.",
                "Every skill requires exactly one SKILL.md at its root.")
        return None

    nested = [p for p in root.rglob("SKILL.md") if p != skill_md]
    if nested:
        rel = ", ".join(str(p.relative_to(root)) for p in nested[:5])
        res.add("error", "NESTED_SKILL_MD",
                f"{len(nested)} additional SKILL.md file(s) found: {rel}",
                "A skill must contain exactly one SKILL.md, at its root. Upload validation "
                "rejects packages with more; rename nested ones (e.g. SKILL.md.fixture) or "
                "package them separately.")
    try:
        return skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        res.add("error", "UNREADABLE_SKILL_MD", f"Cannot read SKILL.md: {exc}")
        return None


def check_name(fm: dict, root: Path, res: Result) -> None:
    name = fm.get("name")
    if not name or not str(name).strip():
        res.add("error", "MISSING_NAME", "Frontmatter has no `name` field.",
                "`name` is required by the spec.")
        return
    name = str(name).strip().strip('"').strip("'")

    if len(name) > NAME_MAX:
        res.add("error", "NAME_TOO_LONG",
                f"`name` is {len(name)} characters; the maximum is {NAME_MAX}.")
    if not NAME_PATTERN.match(name):
        res.add("error", "NAME_CHARSET",
                f"`name` is {name!r}; it must be lowercase letters, digits and hyphens "
                "only, with no leading, trailing or consecutive hyphens.")
    if "<" in name or ">" in name:
        res.add("error", "NAME_XML", "`name` must not contain XML tags.")
    if name != root.name:
        res.add("error", "NAME_DIR_MISMATCH",
                f"`name` is {name!r} but the directory is {root.name!r}.",
                "The spec requires the name to match the parent directory exactly, or the "
                "skill will not load.")
    for frag in RESERVED_NAME_FRAGMENTS:
        if frag in name.lower():
            res.add("warning", "NAME_RESERVED",
                    f"`name` contains the reserved fragment {frag!r}.",
                    f"Names containing {frag!r} are reserved. Use a `cc-` prefix instead "
                    "(e.g. cc-settings rather than claude-settings).")


def check_description(fm: dict, res: Result) -> None:
    desc = fm.get("description")
    if not desc or not str(desc).strip():
        res.add("error", "MISSING_DESCRIPTION", "Frontmatter has no `description` field.",
                "`description` is required and is the primary triggering mechanism.")
        return
    desc = str(desc).strip()
    n = len(desc)

    if n > DESCRIPTION_MAX:
        res.add("error", "DESCRIPTION_TOO_LONG",
                f"`description` is {n} characters; the hard maximum is {DESCRIPTION_MAX}.",
                "Packaging and upload will reject this. Trim while keeping the trigger "
                "phrases, which are what make the skill fire.")
    elif n > DESCRIPTION_WARN_CHARS:
        res.add("warning", "DESCRIPTION_NEAR_LIMIT",
                f"`description` is {n}/{DESCRIPTION_MAX} characters — little headroom.",
                "Leave room so a later edit does not push it over the hard limit.")

    if "<" in desc and ">" in desc:
        res.add("warning", "DESCRIPTION_XML",
                "`description` appears to contain XML/HTML tags.",
                "Frontmatter validation rejects XML tags in the description.")

    # A description that says only what the skill does will under-trigger.
    trigger = ("use when", "use this", "trigger", "when the user", "whenever",
               "activate", "use for", "invoke")
    if not any(t in desc.lower() for t in trigger):
        res.add("warning", "DESCRIPTION_NO_TRIGGER",
                "`description` does not state *when* to use the skill.",
                "Descriptions must cover both what the skill does and when to use it — "
                "the 'when' half is what the agent matches against. Add explicit trigger "
                "contexts and keywords.")

    tok = est_tokens(desc)
    if tok > DESCRIPTION_TOKEN_NOTE:
        res.add("info", "DESCRIPTION_TOKEN_COST",
                f"`description` is ~{tok} tokens, loaded for every session whether or not "
                "the skill fires.",
                "Descriptions are always-on context. Keep trigger keywords, cut prose.")

    if n < 60:
        res.add("warning", "DESCRIPTION_TOO_SHORT",
                f"`description` is only {n} characters.",
                "Short descriptions under-trigger. Name concrete tasks and keywords a user "
                "would actually type.")

    # Anti-trigger phrasing introduces the very keywords that cause misfires.
    if re.search(r"\b(do not use|don't use|not for)\b.{0,40}:", desc.lower()):
        res.add("info", "DESCRIPTION_ANTI_TRIGGER",
                "`description` contains negative routing (\"do not use for ...\").",
                "Negative phrasing can backfire by injecting the wrong keywords. Prefer "
                "positive routing that states what this skill *is* for.")


def check_optional_fields(fm: dict, res: Result) -> None:
    compat = fm.get("compatibility")
    if compat and len(str(compat)) > COMPATIBILITY_MAX:
        res.add("error", "COMPATIBILITY_TOO_LONG",
                f"`compatibility` is {len(str(compat))} characters; maximum {COMPATIBILITY_MAX}.")

    meta = fm.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        res.add("warning", "METADATA_NOT_MAPPING",
                "`metadata` should be a mapping of string keys to string values.")

    unknown = set(fm) - SPEC_FIELDS - CLIENT_FIELDS
    if unknown:
        res.add("error", "UNKNOWN_FRONTMATTER_FIELDS",
                f"Non-specification frontmatter keys: {', '.join(sorted(unknown))}.",
                "Packaging rejects unknown top-level keys. Move custom data under "
                "`metadata:` or into the body.")

    client_only = set(fm) & CLIENT_FIELDS
    if client_only:
        res.add("info", "CLIENT_SPECIFIC_FIELDS",
                f"Client-specific (non-portable) keys in use: {', '.join(sorted(client_only))}.",
                "These work in Claude Code but are outside the portable spec.")


def check_body(body: str, res: Result) -> None:
    lines = body.splitlines()
    n = len(lines)
    if n == 0:
        res.add("error", "EMPTY_BODY", "SKILL.md has frontmatter but no body content.")
        return
    if n > SKILL_MD_MAX_LINES:
        res.add("error", "BODY_TOO_LONG",
                f"SKILL.md body is {n} lines; guidance is under {SKILL_MD_MAX_LINES}.",
                "Everything here loads whenever the skill triggers. Move detail into "
                "references/ and leave a pointer.")
    elif n > SKILL_MD_WARN_LINES:
        res.add("warning", "BODY_LENGTHY",
                f"SKILL.md body is {n} lines, approaching the {SKILL_MD_MAX_LINES}-line ceiling.",
                "Consider extracting the largest section into references/.")

    tok = est_tokens(body)
    if tok > BODY_TOKEN_WARN:
        res.add("error", "BODY_TOKEN_BUDGET",
                f"SKILL.md body is ~{tok} tokens, over the ~{BODY_TOKEN_WARN}-token guidance.",
                "The whole body loads on every trigger. Move detail into references/.")
    elif tok > BODY_TOKEN_TARGET:
        res.add("info", "BODY_TOKEN_ABOVE_TARGET",
                f"SKILL.md body is ~{tok} tokens (practical target ~{BODY_TOKEN_TARGET}).")

    # Unbalanced fences silently swallow the rest of the document for some parsers.
    fences = len(re.findall(r"^\s*```", body, re.M))
    if fences % 2:
        res.add("error", "UNCLOSED_CODE_FENCE",
                f"SKILL.md has {fences} code-fence markers — an odd number, so one is unclosed.",
                "An unclosed fence can swallow the remainder of the document.")

    if not re.search(r"^#{1,2} ", body, re.M):
        res.add("warning", "NO_HEADINGS",
                "Body has no markdown headings.",
                "Headings give the agent structure to navigate.")

    if re.search(r"^\s*<(instructions|workflow|objective|steps)>", body, re.M):
        res.add("info", "XML_BODY_STRUCTURE",
                "Body uses XML-style section tags.",
                "Standard markdown headings are the more portable convention.")

    # Time-sensitive content goes stale and misleads later readers.
    if re.search(r"\b(as of (today|now)|currently in beta|coming soon|last week)\b", body, re.I):
        res.add("info", "TIME_SENSITIVE",
                "Body contains time-sensitive phrasing.",
                "Skills are read long after they are written; prefer dated statements or "
                "an explicit 'verify current status' note.")


LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)\)")
BACKTICK_PATH_RE = re.compile(r"`((?:scripts|references|assets|guides)/[A-Za-z0-9_./-]+\.[a-z]{1,4})`")


def _iter_paths(text: str):
    for m in LINK_RE.finditer(text):
        yield m.group(1)
    for m in BACKTICK_PATH_RE.finditer(text):
        yield m.group(1)


# --- Reference graph ---------------------------------------------------------------
# One resolver, shared by check_links() below and scripts/skill_mapper.py. A map drawn
# from its own near-copy of this logic would drift from the validator's verdict, and a
# drifted map is a wrong map.

@dataclass
class LinkEdge:
    """A single markdown reference, resolved against the skill root."""
    source: str             # markdown file holding the link, relative to the root
    raw: str                # the reference exactly as written
    target: str = ""        # resolved path relative to the root; "" when unresolved
    status: str = "ok"      # ok | dangling | escapes | absolute
    backslash: bool = False


@dataclass
class SkillGraph:
    """What the skill actually references, and what an agent can actually walk to.

    `referenced`, `reachable` and `bundled` hold paths relative to the skill root.
    """
    edges: list = field(default_factory=list)        # LinkEdge, in document order
    referenced: set = field(default_factory=set)     # anything a markdown file resolves to
    reachable: set = field(default_factory=set)      # anything walkable from SKILL.md
    bundled: list = field(default_factory=list)      # files under references/assets/guides
    md_files: list = field(default_factory=list)     # every markdown file, SKILL.md first


def build_graph(root: Path, body: str) -> SkillGraph:
    """Resolve every markdown reference in the skill, then walk outward from SKILL.md.

    `body` is SKILL.md with its frontmatter already stripped, so a link sitting in
    frontmatter is never counted as a progressive-disclosure reference.
    """
    graph = SkillGraph()
    rroot = root.resolve()
    all_md = [root / "SKILL.md"] + [p for p in root.rglob("*.md") if p.name != "SKILL.md"]
    graph.md_files = [p.relative_to(root) for p in all_md]

    for md in all_md:
        try:
            text = body if md.name == "SKILL.md" else md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        source = str(md.relative_to(root))
        for raw in _iter_paths(text):
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            if raw.startswith("/"):
                graph.edges.append(LinkEdge(source, raw, status="absolute"))
                continue
            edge = LinkEdge(source, raw, backslash="\\" in raw)
            # The spec keeps file references relative to the skill root; some authors
            # write them relative to the containing file. Accept either, and only report
            # a dangling link when neither resolves.
            candidates = []
            for base in (root, md.parent):
                cand = (base / raw).resolve()
                if cand not in candidates:
                    candidates.append(cand)

            resolved = next((c for c in candidates if c.exists()), None)
            inside = [c for c in candidates if str(c).startswith(str(rroot))]
            if resolved is None and not inside:
                edge.status = "escapes"
            elif resolved is None:
                edge.status = "dangling"
            else:
                try:
                    rel = resolved.relative_to(rroot)
                    edge.target = str(rel)
                    graph.referenced.add(rel)
                except ValueError:
                    pass
            graph.edges.append(edge)

    # Reachability is transitive: walk outward from SKILL.md. A reference file that is
    # only mentioned by another unreachable file is itself unreachable, which a
    # direct-link check would miss.
    def paths_in(path: Path) -> set:
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return set()
        found = set()
        for raw in _iter_paths(txt):
            if raw.startswith(("http://", "https://", "mailto:", "/")):
                continue
            for base in (root, path.parent):
                cand = (base / raw).resolve()
                if cand.exists() and cand.is_file():
                    try:
                        found.add(cand.relative_to(rroot))
                    except ValueError:
                        pass
                    break
        return found

    frontier = [root / "SKILL.md"]
    while frontier:
        cur = frontier.pop()
        for rel in paths_in(cur):
            if rel in graph.reachable:
                continue
            graph.reachable.add(rel)
            nxt = root / rel
            if nxt.suffix.lower() == ".md" and nxt.is_file():
                frontier.append(nxt)

    graph.bundled = [p.relative_to(root) for d in ("references", "assets", "guides")
                     if (root / d).is_dir()
                     for p in (root / d).rglob("*")
                     if p.is_file() and not any(j in p.parts for j in JUNK_PATTERNS)]
    return graph


def check_links(root: Path, body: str, res: Result) -> None:
    """Dangling links, escapes above the skill root, and orphaned bundled files."""
    graph = build_graph(root, body)

    for edge in graph.edges:
        if edge.status == "absolute":
            res.add("warning", "ABSOLUTE_PATH",
                    f"{edge.source} references an absolute path: {edge.raw}",
                    "Use paths relative to the skill root so the skill stays portable.")
            continue
        if edge.backslash:
            res.add("warning", "BACKSLASH_PATH",
                    f"{edge.source} uses backslashes in {edge.raw}",
                    "Use forward slashes on every platform.")
        if edge.status == "escapes":
            res.add("error", "PATH_ESCAPES_SKILL",
                    f"{edge.source} references {edge.raw}, which resolves outside "
                    "the skill directory.",
                    "`../` paths break once the skill is installed on its own. Bundle "
                    "the target or drop the link.")
        elif edge.status == "dangling":
            res.add("error", "DANGLING_REFERENCE",
                    f"{edge.source} links to {edge.raw}, which does not exist.")

    # Bundled files nothing points at will never be loaded.
    orphans = [p for p in graph.bundled
               if p not in graph.reachable and p not in graph.referenced
               and p.suffix.lower() == ".md"]
    unreachable = [p for p in graph.bundled
                   if p not in graph.reachable and p in graph.referenced
                   and p.suffix.lower() == ".md"]
    for u in sorted(unreachable):
        res.add("info", "UNREACHABLE_FROM_SKILL_MD",
                f"{u} is linked from another file but not reachable from SKILL.md.",
                "The agent starts at SKILL.md; anything it cannot walk to may never load.")
    for o in sorted(orphans):
        res.add("warning", "ORPHANED_REFERENCE",
                f"{o} is bundled but never linked from any markdown file.",
                "Under progressive disclosure an unlinked file is never read. Link it from "
                "SKILL.md or remove it.")

    # Depth: SKILL.md -> reference -> reference is hard for agents to follow.
    for rel in graph.md_files:
        if rel.name == "SKILL.md":
            continue
        depth = len(rel.parts) - 1
        if depth > 2:
            res.add("info", "DEEP_NESTING",
                    f"{rel} is nested {depth} levels deep.",
                    "Keep reference files shallow so they are easy to discover.")


def check_packaging_hygiene(root: Path, res: Result) -> None:
    """Files that should never ship inside a skill package."""
    junk = []
    has_git = False
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        # .git is expected in a cloned skill and is excluded at packaging
        # time, so it gets its own informational note instead of a warning.
        if ".git" in rel.parts:
            has_git = True
            continue
        if any(part in JUNK_PATTERNS for part in rel.parts) or p.suffix in JUNK_SUFFIXES:
            junk.append(rel.parts[0] if rel.parts[0] in JUNK_PATTERNS else rel)
    if junk:
        uniq = sorted({str(j) for j in junk})[:6]
        res.add("warning", "JUNK_FILES",
                f"Build or editor artifacts present: {', '.join(uniq)}",
                "These bloat the package and leak local state. Remove before publishing.")
    if has_git:
        res.add("info", "GIT_DIR",
                "A .git directory is present (normal for a cloned skill).",
                "Exclude it when zipping for upload: "
                "zip -r skill.zip . -x '.git/*' '.git'")

    for p in root.rglob("*"):
        if p.is_file() and p.stat().st_size > 2_000_000:
            res.add("info", "LARGE_FILE",
                    f"{p.relative_to(root)} is {p.stat().st_size // 1024}KB.",
                    "Large binaries are usually generated output that need not ship.")


def check_yaml_portability(fm_text: str, res: Result) -> None:
    """The official skills-ref validator parses frontmatter strictly."""
    for line in fm_text.splitlines():
        if re.match(r"^[A-Za-z0-9_-]+:\s*\[.*\]\s*$", line.strip()):
            res.add("warning", "YAML_FLOW_SEQUENCE",
                    f"Frontmatter uses an inline flow sequence: {line.strip()[:60]}",
                    "The official skills-ref validator rejects inline `[a, b]` sequences. "
                    "Use block style, or a space-delimited string for allowed-tools.")
            break
    if "\t" in fm_text:
        res.add("warning", "YAML_TABS",
                "Frontmatter contains tab characters.",
                "YAML forbids tabs for indentation; use spaces.")


def check_reference_quality(root: Path, res: Result) -> None:
    ref_dir = root / "references"
    if not ref_dir.is_dir():
        return
    for p in sorted(ref_dir.rglob("*.md")):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        if len(lines) > REFERENCE_TOC_LINES:
            head = "\n".join(lines[:40]).lower()
            if not any(k in head for k in ("## contents", "## table of contents",
                                           "- [", "## overview")):
                res.add("info", "REFERENCE_NO_TOC",
                        f"{p.relative_to(root)} is {len(lines)} lines with no table of contents.",
                        "Reference files past ~100 lines are easier to navigate with one.")


def check_scripts(root: Path, skill_type: str, res: Result) -> None:
    """Script checks that adapt to skill type, and never demand scripts of doc skills."""
    scripts = [p for p in (root / "scripts").rglob("*.py")
               if "__pycache__" not in p.parts] if (root / "scripts").is_dir() else []
    if not scripts:
        if skill_type in ("tool", "toolkit"):
            res.add("warning", "NO_SCRIPTS", "No Python scripts found under scripts/.")
        return

    import ast
    for p in scripts:
        rel = p.relative_to(root)
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except SyntaxError as exc:
            res.add("error", "SCRIPT_SYNTAX", f"{rel}: syntax error: {exc}")
            continue
        except (OSError, UnicodeDecodeError) as exc:
            res.add("warning", "SCRIPT_UNREADABLE", f"{rel}: {exc}")
            continue

        # A module imported by siblings is a library, not a CLI. Do not demand argparse.
        is_library = p.name.startswith("_") or any(
            re.search(rf"(^|\n)\s*(from|import)\s+{re.escape(p.stem)}\b", q.read_text(
                encoding="utf-8", errors="ignore"))
            for q in scripts if q != p
        )
        if is_library:
            continue

        has_main = any(
            isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and {n.id for n in [node.test.left, *node.test.comparators]
                 if isinstance(n, ast.Name)} & {"__name__"}
            and {c.value for c in [node.test.left, *node.test.comparators]
                 if isinstance(c, ast.Constant)} & {"__main__"}
            for node in ast.walk(tree)
        )
        if not has_main:
            res.add("warning", "SCRIPT_NO_MAIN_GUARD",
                    f"{rel} has no `if __name__ == \"__main__\"` guard.",
                    "Executable scripts need one so importing them has no side effects.")

        if not re.search(r'"""|\'\'\'', src[:400]):
            res.add("info", "SCRIPT_NO_DOCSTRING",
                    f"{rel} has no module docstring.",
                    "State what the script does and how to invoke it.")


# --- Reporting ---------------------------------------------------------------------

ICON = {"error": "✗", "warning": "!", "info": "·"}


def validate(root: Path) -> Result:
    root = root.resolve()
    res = Result(skill=root.name)
    text = check_structure(root, res)
    if text is None:
        return res
    res.skill_type = detect_type(root)

    fm_text, body, err = split_frontmatter(text)
    if err:
        res.add("error", "BAD_FRONTMATTER", err)
        return res
    fm = parse_frontmatter(fm_text)
    if not fm:
        res.add("error", "EMPTY_FRONTMATTER", "Frontmatter parsed as empty.")
        return res

    desc_tokens = est_tokens(str(fm.get("description", "")))
    body_tokens = est_tokens(body)
    res.tokens = {
        "description": desc_tokens,   # loaded every session
        "body": body_tokens,          # loaded when the skill triggers
        "total": desc_tokens + body_tokens,
    }

    check_yaml_portability(fm_text, res)
    check_name(fm, root, res)
    check_description(fm, res)
    check_optional_fields(fm, res)
    check_body(body, res)
    check_links(root, body, res)
    check_reference_quality(root, res)
    check_packaging_hygiene(root, res)
    check_scripts(root, res.skill_type, res)
    return res


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def render(res: Result, strict: bool) -> str:
    header = f"=== {res.skill}  [{res.skill_type}]"
    if res.tokens:
        header += (f" · ~{_fmt_tokens(res.tokens['total'])} tokens"
                   f" (description {_fmt_tokens(res.tokens['description'])}"
                   f" every session + body {_fmt_tokens(res.tokens['body'])} on trigger)")
    out = [header + " ==="]
    if not res.findings:
        out.append("  conformant — no findings")
    for sev in ("error", "warning", "info"):
        for f in [x for x in res.findings if x.severity == sev]:
            out.append(f"  {ICON[sev]} {sev.upper():7} {f.code}: {f.message}")
            if f.fix:
                out.append(f"              → {f.fix}")
    e, w, i = res.count("error"), res.count("warning"), res.count("info")
    verdict = "CONFORMANT" if (res.conformant and not (strict and w)) else "NOT CONFORMANT"
    out.append(f"  {verdict}  ({e} errors, {w} warnings, {i} notes)")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate a skill against the Agent Skills specification.")
    ap.add_argument("path", help="skill directory, or a directory of skills with --recursive")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--recursive", action="store_true", help="validate every skill beneath path")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = ap.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return 2

    targets = sorted(p for p in root.iterdir()
                     if p.is_dir() and (p / "SKILL.md").is_file()) if args.recursive else [root]
    if args.recursive and not targets:
        print(f"error: no skills found beneath {root}", file=sys.stderr)
        return 2

    results = [validate(t) for t in targets]

    if args.json:
        print(json.dumps([{**asdict(r),
                           "errors": r.count("error"),
                           "warnings": r.count("warning"),
                           "conformant": r.conformant} for r in results],
                         indent=2, sort_keys=True))
    else:
        for r in results:
            print(render(r, args.strict))
            if len(results) > 1:
                print()
        if len(results) > 1:
            ok = sum(1 for r in results if r.conformant)
            print(f"{ok}/{len(results)} skills conformant")

    failed = any(not r.conformant or (args.strict and r.count("warning")) for r in results)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
