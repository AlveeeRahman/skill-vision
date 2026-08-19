#!/usr/bin/env python3
"""
Claim Auditor — check what a skill's documentation *says* against what its files *do*.

The other validators in this skill ask whether a skill is well-formed. This one asks a
different question: is it telling the truth? Those are independent failures. A skill can
be perfectly structured, pass every link check, score an A, and still state in its
frontmatter that a script runs offline when that script ships your prompt to a
third-party API. Nothing else here catches that, because nothing else compares prose to
behaviour.

Every check is deterministic and evidence-backed. No model is consulted, no claim is
judged on plausibility: each finding names the sentence, the file, and the fact that
contradicts it. Claims this tool cannot decide are reported as UNVERIFIED rather than
guessed at — an auditor that bluffs is the thing it exists to catch.

What it audits:

  1. COMMANDS      Every documented `python3 scripts/x.py --flag` invocation: the script
                   exists, and every flag it is called with is a real flag on that
                   script's parser (read off the AST, not by running it).
  2. REACH         "offline" / "standard library only" / "no dependencies" claims, traced
                   *transitively*: a stdlib-only wrapper that subprocesses a sibling
                   needing `requests` and an API key is not offline, and this is the
                   check that says so.
  3. COUNTS        "N tests", "23 CLIs", "40+ references": compared against what is on
                   disk and in the test suite.
  4. PATHS         Paths named anywhere in prose or code fences that do not exist.
  5. CAPABILITIES  "exposes --help", "supports --json" asserted for scripts that do not.

Exit codes:
  0  no contradictions found
  1  the audit could not run (bad path, unreadable SKILL.md)
  2  at least one documented claim is contradicted by the tree
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_validator import split_frontmatter  # noqa: E402

# Modules whose presence means "this touches the network", regardless of what the
# surrounding prose promises.
NETWORK_MODULES = {
    "requests", "urllib", "urllib3", "http", "httpx", "aiohttp", "socket",
    "ftplib", "smtplib", "telnetlib", "xmlrpc", "websockets", "boto3",
}

def _stdlib_names() -> frozenset:
    """Standard-library module names for the running interpreter.

    `sys.stdlib_module_names` arrived in 3.10. Falling back to an empty set on 3.9
    silently classified *every* import as third-party, including `argparse`, which
    turned every correct "stdlib only" claim into a contradiction. The CI matrix
    caught it on 3.9 and nowhere else.

    The fallback reads the stdlib directory listing instead. Nothing is imported, so
    no module side effects run during an audit.
    """
    names = set(getattr(sys, "stdlib_module_names", ()) or ())
    if names:
        return frozenset(names)

    import os
    import sysconfig

    names = set(sys.builtin_module_names)
    stdlib_dir = sysconfig.get_paths().get("stdlib")
    if stdlib_dir and os.path.isdir(stdlib_dir):
        for entry in os.listdir(stdlib_dir):
            path = os.path.join(stdlib_dir, entry)
            if entry.endswith(".py"):
                names.add(entry[:-3])
            elif entry != "site-packages" and os.path.isdir(path):
                names.add(entry)
    return frozenset(names)


_STDLIB = _stdlib_names()

DOC_FILES = ("SKILL.md", "README.md")

# Explicit opt-out. Documentation sometimes quotes commands from *another* project on
# purpose — an upstream CI pipeline kept for provenance, a comparison with a competing
# tool. Those are not claims about this package, and there is no reliable way to infer
# that from prose. Mark the block and the auditor skips it:
#
#     <!-- claim-audit: ignore-next-block -->
#     ```bash
#     uv run some-other-projects-tool ...
#     ```
IGNORE_DIRECTIVE = re.compile(r"<!--\s*claim-audit:\s*ignore-next-block\s*-->",
                              re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")

# `python3 scripts/foo.py --bar baz` inside a fenced block or inline code.
CMD_RE = re.compile(
    r"(?:^|\s)(?:python3?|uv\s+run(?:\s+python3?)?)\s+"
    r"(?P<script>[\w./-]+\.py)(?P<rest>[^\n`]*)"
)
FLAG_RE = re.compile(r"(?<![\w-])(--[a-zA-Z][\w-]*)")

# Claims of offline / dependency-free operation. Matched against a whole sentence, not
# a line: the surrounding words decide whether this is an assertion or a disclaimer.
OFFLINE_RE = re.compile(
    r"\b(?:runs?\s+offline|offline\s+(?:alternative|path|diagram|generator|version)|"
    r"standard[- ]library(?:\s+only)?|stdlib[- ]only|no\s+(?:external\s+)?dependencies|"
    r"zero\s+(?:runtime\s+)?dependencies|no\s+network(?:\s+access)?)\b",
    re.IGNORECASE,
)

# A sentence that *denies* offline operation is documentation doing its job, not a false
# claim. "generate_schematic.py is not an offline alternative" must never be reported as
# an untrue offline claim — flagging accurate disclaimers is how an auditor teaches
# people to ignore it.
NEGATION_RE = re.compile(
    r"\b(?:not|isn't|is\s+not|never|no\s+longer|rather\s+than|instead\s+of|"
    r"cannot|can't|does\s+not|doesn't|there\s+is\s+no|nothing)\b",
    re.IGNORECASE,
)

# "…except two", "…with one exception", "…apart from x" — the sentence is already
# carving out exceptions, so only scripts it names by filename can be judged.
HEDGE_RE = re.compile(
    r"\b(?:except|apart\s+from|other\s+than|with\s+(?:one|two|three|\d+)\s+exceptions?|"
    r"with\s+the\s+exception|unless|aside\s+from|but\s+for)\b",
    re.IGNORECASE,
)

# Prose describing what the docs *used to* say is not a live claim. A changelog line
# like "earlier revisions described it as the offline path" is the fix, not the defect.
HISTORICAL_RE = re.compile(
    r"\b(?:earlier|previously|formerly|used\s+to|no\s+longer|older?\s+(?:revision|version)s?|"
    r"in\s+the\s+past|was\s+(?:described|documented|called))\b",
    re.IGNORECASE,
)

# Only a sentence that quantifies over the whole package may be checked against every
# script. Without a named script and without a universal, the subject is ambiguous, and
# guessing "it must mean all of them" manufactures findings.
UNIVERSAL_RE = re.compile(
    r"\b(?:every|all|each|both)\s+(?:bundled\s+|other\s+)?(?:script|tool|cli|generator)s?\b"
    r"|\bno\s+(?:external\s+|runtime\s+)?dependenc(?:y|ies)\b"
    r"|\bzero\s+(?:runtime\s+)?dependenc(?:y|ies)\b"
    r"|\bthese\s+scripts\b|\bthe\s+(?:whole\s+)?(?:skill|package)\b",
    re.IGNORECASE,
)

# Sentence splitting that survives technical prose: a period inside `foo.py`, `3.10`,
# `e.g.`, or a version string does not end a sentence.
_SENTINEL = "\x00"
_PROTECT = [
    (re.compile(r"(\w)\.(py|md|json|csv|txt|yml|yaml|sh|toml|cfg)\b"),
     "\\1" + _SENTINEL + "\\2"),
    (re.compile(r"(\d)\.(\d)"), "\\1" + _SENTINEL + "\\2"),
    (re.compile(r"\b(e|i)\.(g|e)\.", re.IGNORECASE),
     "\\1" + _SENTINEL + "\\2" + _SENTINEL),
    (re.compile(r"\b(vs|etc|approx|Dr|Mr|Ms|Inc|Ltd)\.", re.IGNORECASE),
     "\\1" + _SENTINEL),
]


def sentences(text: str) -> Iterable[str]:
    """Split prose into sentences without breaking on filenames or version numbers."""
    protected = text
    for pattern, repl in _PROTECT:
        protected = pattern.sub(repl, protected)
    for part in re.split(r"(?<=[.!?;])\s+|\n", protected):
        s = part.replace(_SENTINEL, ".").strip()
        if s:
            yield s

# Inventory claims only. "2-3 scripts (500-800 LOC)" in a tier table, or "3 scripts"
# inside a worked example about someone else's project, is not a statement about what
# this package contains. Requiring an inventory verb is what separates the two.
COUNT_RE = re.compile(
    r"\b(?:ships?|bundles?|contains?|includes?|provides?|has|holds?|"
    r"comes\s+with|there\s+are)\s+"
    r"(?:only\s+)?(\d+)\s*(\+)?\s*"
    r"(tests?|checks?|scripts?|CLIs?|guides?|reference\s+documents?|references?)\b",
    re.IGNORECASE,
)

PATH_RE = re.compile(r"`([\w./-]+/[\w./-]+\.\w{1,5})`|\(([\w./-]+/[\w./-]+\.\w{1,5})\)")

# A DOI looks like a path and is not one.
DOI_RE = re.compile(r"^\d+\.\d{4,}/")

# Filenames that stand in for "your script here". A template showing
# `python script.py --format json` is teaching a CLI shape, not referencing a file.
PLACEHOLDER_SCRIPTS = {
    "script.py", "my_script.py", "your_script.py", "example.py", "foo.py",
    "bar.py", "tool.py", "main.py", "name.py", "skill.py", "app.py",
}

# Checks that only make sense against the files describing *this package*. Guides and
# references carry domain content — example directory layouts, other projects' commands,
# hypothetical harness paths — where a non-existent path is the point, not a defect.
PACKAGE_DOCS = {"SKILL.md", "SKILL.md (frontmatter)", "README.md"}


@dataclass
class Finding:
    severity: str            # contradiction | unverified
    code: str
    claim: str               # the sentence or fragment as written
    where: str               # doc file (and line) the claim appears in
    evidence: str            # the fact that contradicts it
    fix: str = ""


@dataclass
class AuditResult:
    skill: str = ""
    findings: list = field(default_factory=list)
    checked: dict = field(default_factory=dict)

    def add(self, severity: str, code: str, claim: str, where: str,
            evidence: str, fix: str = "") -> None:
        self.findings.append(Finding(severity, code, claim.strip(), where,
                                     evidence, fix))

    @property
    def contradictions(self) -> list:
        return [f for f in self.findings if f.severity == "contradiction"]


# --- script facts -------------------------------------------------------------------

@dataclass
class ScriptFacts:
    path: Path
    exists: bool = False
    parse_error: str = ""
    imports: set = field(default_factory=set)      # required top-level module names
    optional: set = field(default_factory=set)     # guarded by try/except ImportError
    flags: set = field(default_factory=set)        # --flags its parser accepts
    has_argparse: bool = False
    spawns: set = field(default_factory=set)       # sibling .py files it subprocesses


def _module_root(name: str) -> str:
    return (name or "").split(".")[0]


def script_facts(path: Path) -> ScriptFacts:
    """Read a script's imports, CLI flags, and the siblings it shells out to.

    Everything comes off the AST. The script is never executed — auditing a skill
    must not run that skill's code.
    """
    facts = ScriptFacts(path=path, exists=path.is_file())
    if not facts.exists:
        return facts
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError) as exc:
        facts.parse_error = str(exc)
        return facts

    # An import wrapped in `try: import x / except ImportError: <fallback>` is an
    # optional enhancement, not a dependency. A skill that degrades gracefully without
    # pyyaml is entitled to say it has zero required dependencies, and counting the
    # guarded import against it would turn correct documentation into a finding.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # `except Exception:` and a bare `except:` both swallow ImportError, so both
        # make the import optional in practice. Judge by what is actually caught.
        catch_names = ("ImportError", "ModuleNotFoundError", "Exception", "BaseException")
        catches_import = any(
            (h.type is None)
            or (isinstance(h.type, ast.Name) and h.type.id in catch_names)
            or (isinstance(h.type, ast.Tuple)
                and any(isinstance(e, ast.Name) and e.id in catch_names
                        for e in h.type.elts))
            for h in node.handlers
        )
        if not catches_import:
            continue
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Import):
                    for alias in sub.names:
                        facts.optional.add(_module_root(alias.name))
                elif isinstance(sub, ast.ImportFrom) and sub.level == 0 and sub.module:
                    facts.optional.add(_module_root(sub.module))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                facts.imports.add(_module_root(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                facts.imports.add(_module_root(node.module))
        elif isinstance(node, ast.Call):
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else "")
            if name == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                            and arg.value.startswith("--"):
                        facts.flags.add(arg.value)
            if name in ("ArgumentParser",):
                facts.has_argparse = True
            # A sibling script named in any string argument of a subprocess-ish call
            # is a spawn: `[sys.executable, str(ai_script), ...]`.
            if name in ("run", "Popen", "call", "check_output", "check_call",
                        "create_subprocess_exec", "create_subprocess_shell"):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                            and sub.value.endswith(".py"):
                        facts.spawns.add(Path(sub.value).name)

    # `ai_script = script_dir / "generate_schematic_ai.py"` then passed to a Popen list
    # is the common shape and is not a Constant inside the Call node. Catch any .py
    # string literal assigned anywhere, when the module imports subprocess at all.
    if "subprocess" in facts.imports:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value.endswith(".py") \
                    and node.value != path.name:
                facts.spawns.add(Path(node.value).name)

    facts.imports -= facts.optional
    # `--help` only exists if something builds it. Adding it unconditionally made the
    # capability check unfalsifiable: a script that parses sys.argv by hand and treats
    # `--help` as a filename would still have counted as supporting it.
    #
    # argparse supplies it automatically. A hand-rolled parser supplies it only if the
    # source actually mentions the flag, so look for the literal before crediting it —
    # several scripts here do the check by hand and answer correctly.
    if facts.has_argparse:
        facts.flags.update(("--help", "-h"))
    else:
        literals = {n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if "--help" in literals:
            facts.flags.add("--help")
        if "-h" in literals:
            facts.flags.add("-h")
    return facts


def is_third_party(module: str, local_modules: set) -> bool:
    """True when a module is neither stdlib nor a file bundled inside the skill."""
    if not module or module in local_modules:
        return False
    if module in _STDLIB:
        return False
    if module in sys.builtin_module_names:
        return False
    return True


def reach_of(name: str, facts_by_name: dict, seen: set | None = None) -> tuple:
    """Transitive (third_party, network) module sets for a script and everything it spawns.

    This is the check that catches a "thin offline wrapper" whose whole job is to run
    the online one. Following spawns is the entire point: judging the wrapper on its own
    imports says stdlib, and stdlib is not the same as offline.
    """
    seen = seen if seen is not None else set()
    if name in seen:
        return set(), set()
    seen.add(name)
    facts = facts_by_name.get(name)
    if facts is None:
        return set(), set()
    local = set(facts_by_name)
    local_mods = {Path(n).stem for n in facts_by_name}
    third = {m for m in facts.imports if is_third_party(m, local_mods)}
    net = {m for m in facts.imports if _module_root(m) in NETWORK_MODULES}
    for spawned in facts.spawns:
        if spawned in local:
            t2, n2 = reach_of(spawned, facts_by_name, seen)
            third |= t2
            net |= n2
    return third, net


# --- document scanning --------------------------------------------------------------

def doc_files(root: Path) -> list:
    """Documentation Claude actually reads and acts on.

    SKILL.md and README.md are the front door, but the commands people mis-copy live in
    the guides and references — those are instructions an agent follows literally, so a
    flag that does not exist there is a real failure, not a typo in a readme.
    """
    files = [root / n for n in DOC_FILES]
    for sub in ("guides", "references"):
        d = root / sub
        if d.is_dir():
            files.extend(sorted(d.rglob("*.md")))
    return [p for p in files if p.is_file()]


def _drop_ignored_blocks(text: str) -> str:
    """Blank out fenced blocks preceded by the ignore directive, keeping line numbers."""
    lines = text.splitlines()
    out, armed, in_block = [], False, False
    for line in lines:
        if IGNORE_DIRECTIVE.search(line):
            armed = True
            out.append("")
            continue
        if armed and FENCE_RE.match(line) and not in_block:
            in_block, armed = True, False
            out.append("")
            continue
        if in_block:
            out.append("")
            if FENCE_RE.match(line):
                in_block = False
            continue
        out.append(line)
    return "\n".join(out)


def doc_lines(root: Path) -> list:
    """(docfile, lineno, text) for every line of every documentation file present."""
    out = []
    for p in doc_files(root):
        name = str(p.relative_to(root))
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = _drop_ignored_blocks(text)
        if name == "SKILL.md":
            fm, body, _ = split_frontmatter(text)
            # Frontmatter claims ship to claude.ai and the API, so they are audited
            # too — the `compatibility` field is exactly where an untrue "runs
            # offline" does the most damage.
            for i, line in enumerate((fm or "").splitlines(), start=1):
                out.append((f"{name} (frontmatter)", i, line))
            offset = len((fm or "").splitlines()) + 2
            for i, line in enumerate(body.splitlines(), start=1):
                out.append((name, i + offset, line))
        else:
            for i, line in enumerate(text.splitlines(), start=1):
                out.append((name, i, line))
    return out


def audit_commands(root: Path, lines: list, facts_by_rel: dict,
                   facts_by_name: dict, res: AuditResult) -> None:
    """Documented invocations must name a real script and use flags it accepts."""
    checked = 0
    for where, lineno, line in lines:
        for m in CMD_RE.finditer(line):
            raw = m.group("script")
            if raw.startswith("/") or raw.startswith("~"):
                # An absolute path is a deliberate install or checkout location
                # (`/tmp/skill-vision/scripts/...` in a CI snippet), not a claim
                # about where this package keeps its files.
                continue
            rel = raw[2:] if raw.startswith("./") else raw
            base = Path(rel).name
            if base in PLACEHOLDER_SCRIPTS:
                continue

            facts = facts_by_rel.get(rel)
            if facts is None and "/" in rel:
                # Written from the repo root, i.e. with the skill directory prefixed.
                facts = facts_by_rel.get(rel.split("/", 1)[1])
            if facts is None:
                # A bare filename that exists elsewhere in the package is not a missing
                # script — it is a command that will not run from where the docs say to
                # run it. Different failure, different finding.
                elsewhere = facts_by_name.get(base)
                if elsewhere is not None:
                    actual = str(elsewhere.path.relative_to(root))
                    if actual != rel:
                        res.add("contradiction", "COMMAND_PATH_WRONG", line.strip(),
                                f"{where}:{lineno}",
                                f"{raw} is not at that path; the script is at {actual}",
                                f"Write the command as `python3 {actual} …`.")
                    facts = elsewhere
                else:
                    if (root / rel).is_file():
                        continue
                    res.add("contradiction", "COMMAND_SCRIPT_MISSING", line.strip(),
                            f"{where}:{lineno}",
                            f"{raw} does not exist anywhere in the skill",
                            "Correct the path or ship the script.")
                    continue
            checked += 1
            if not facts.has_argparse:
                continue
            for flag in FLAG_RE.findall(m.group("rest")):
                if flag not in facts.flags:
                    res.add("contradiction", "COMMAND_FLAG_UNKNOWN", line.strip(),
                            f"{where}:{lineno}",
                            f"{facts.path.name} has no {flag} option "
                            f"(accepts: {', '.join(sorted(facts.flags)) or 'none'})",
                            f"Remove {flag} from the example, or add it to the parser.")
    res.checked["documented_commands"] = checked


def _reach_detail(rel: str, facts: ScriptFacts, facts_by_name: dict) -> str:
    """Human-readable account of why a script is not offline, or '' if it is."""
    third, net = reach_of(facts.path.name, facts_by_name)
    if not (third or net):
        return ""
    detail = []
    if net:
        detail.append(f"reaches the network via {', '.join(sorted(net))}")
    extra = sorted(third - net)
    if extra:
        detail.append(f"needs third-party {', '.join(extra)}")
    direct_net = {m for m in facts.imports if _module_root(m) in NETWORK_MODULES}
    chain = facts.spawns & set(facts_by_name)
    via = (f" (transitively, through {', '.join(sorted(chain))})"
           if chain and not direct_net else "")
    return f"{rel} {' and '.join(detail)}{via}"


def doc_paragraphs(lines: list) -> list:
    """(docfile, first_lineno, joined_text) per blank-line-separated block.

    Prose wraps. "…runs offline on the standard library, with three\\nexceptions:"
    is one sentence across two lines, and judging each line alone loses the hedge —
    which turns an accurate, carefully qualified sentence into a false positive.
    """
    out, buf, start, cur = [], [], 0, None
    for where, lineno, line in lines:
        if cur is not None and where != cur:
            if buf:
                out.append((cur, start, " ".join(buf)))
            buf, cur = [], where
        cur = where if cur is None else cur
        if line.strip():
            if not buf:
                start = lineno
            buf.append(line.strip())
        elif buf:
            out.append((cur, start, " ".join(buf)))
            buf = []
    if buf and cur is not None:
        out.append((cur, start, " ".join(buf)))
    return out


def audit_reach(root: Path, lines: list, facts_by_name: dict,
                facts_by_rel: dict, res: AuditResult) -> None:
    """Offline / stdlib-only / no-dependency claims, traced through spawned scripts.

    Deliberately conservative. A sentence is only treated as a claim when it asserts
    offline operation without negating it. Sentences that *deny* offline operation, or
    that hedge without naming which scripts they cover, are not contradictions —
    reporting those would make the tool untrustworthy in exactly the way it is meant to
    detect.
    """
    checked = 0
    seen: set = set()
    for where, lineno, paragraph in doc_paragraphs(lines):
        for sentence in sentences(paragraph):
            if not OFFLINE_RE.search(sentence):
                continue
            key = (where, lineno, sentence)
            if key in seen:
                continue
            seen.add(key)
            checked += 1

            if NEGATION_RE.search(sentence):
                continue          # a disclaimer, not a claim
            if HISTORICAL_RE.search(sentence):
                continue          # narration about a previous revision

            named = [rel for rel in facts_by_rel
                     if rel in sentence or Path(rel).name in sentence]
            hedged = bool(HEDGE_RE.search(sentence))

            if hedged:
                # In a hedged sentence the named scripts are the *exceptions*, not the
                # subject: "every script runs offline except a.py and b.py" asserts
                # nothing about a.py and b.py, and everything about the rest. Treating
                # the named ones as the subject inverts the sentence and reports the
                # clearest possible documentation as a lie.
                excepted = set(named) or {
                    rel for rel in facts_by_rel
                    if rel in paragraph or Path(rel).name in paragraph}
                if not excepted:
                    res.add("unverified", "REACH_CLAIM_HEDGED", sentence,
                            f"{where}:{lineno}",
                            "the sentence carves out exceptions but neither it nor its "
                            "paragraph names a script, so its scope cannot be checked",
                            "Name the scripts the exception applies to, so the claim "
                            "can be checked.")
                    continue
                targets = [rel for rel in sorted(facts_by_rel) if rel not in excepted]
            elif named:
                targets = named
            elif UNIVERSAL_RE.search(sentence):
                targets = sorted(facts_by_rel)
            else:
                # No subject to test the claim against. Silence beats a guess.
                continue
            for rel in targets:
                evidence = _reach_detail(rel, facts_by_rel[rel], facts_by_name)
                if evidence:
                    res.add("contradiction", "REACH_CLAIM_FALSE", sentence,
                            f"{where}:{lineno}", evidence,
                            "State what leaves the machine, or narrow the claim to "
                            "the scripts it is true of.")
    res.checked["reach_claims"] = checked


def audit_counts(root: Path, lines: list, res: AuditResult) -> None:
    """Numeric claims about things that can be counted on disk."""
    actual = {
        "script": len([p for p in root.rglob("scripts/**/*.py")
                       if "__pycache__" not in p.parts]),
        "cli": len([p for p in root.rglob("scripts/**/*.py")
                    if "__pycache__" not in p.parts
                    and not p.name.startswith("_")]),
        "guide": len(list((root / "guides").glob("*.md"))) if (root / "guides").is_dir() else 0,
        "reference": len([p for p in (root / "references").rglob("*.md")]) if (root / "references").is_dir() else 0,
    }
    actual["reference document"] = actual["reference"]

    checked = 0
    for where, lineno, line in lines:
        if where not in PACKAGE_DOCS:
            continue
        for m in COUNT_RE.finditer(line):
            claimed = int(m.group(1))
            approx = bool(m.group(2))
            noun = m.group(3).lower().rstrip("s").replace("  ", " ").strip()
            noun = {"cli": "cli", "reference document": "reference document"}.get(
                noun, noun)
            if noun not in actual:
                continue
            checked += 1
            real = actual[noun]
            ok = (real >= claimed) if approx else (real == claimed)
            if not ok:
                res.add("contradiction", "COUNT_MISMATCH", m.group(0),
                        f"{where}:{lineno}",
                        f"{real} {noun}(s) found on disk, documentation says "
                        f"{m.group(0).strip()}",
                        f"Update the number to {real}.")
    res.checked["count_claims"] = checked


def audit_paths(root: Path, lines: list, res: AuditResult) -> None:
    """Paths named in SKILL.md or README.md that are not in the package.

    Scoped to the two files that describe the package. A guide showing
    `researcher/claims/index.jsonl` is illustrating a harness layout the reader is
    meant to build, not referencing a bundled file, and flagging those would drown
    the real findings.
    """
    all_files = {str(p.relative_to(root)) for p in root.rglob("*")
                 if p.is_file() and ".git" not in p.parts}
    by_name: dict = {}
    for rel in all_files:
        by_name.setdefault(Path(rel).name, rel)

    checked = 0
    for where, lineno, line in lines:
        if where not in PACKAGE_DOCS:
            continue
        for m in PATH_RE.finditer(line):
            raw = (m.group(1) or m.group(2) or "").strip()
            if not raw or raw.startswith(("http", "mailto:", "#", "~", "/")):
                continue
            if DOI_RE.match(raw):
                continue          # a DOI, not a path
            checked += 1
            rel = raw[2:] if raw.startswith("./") else raw
            if rel in all_files or (root / rel).exists():
                continue
            # Written from the repo root, i.e. with the skill directory prefixed.
            if "/" in rel and rel.split("/", 1)[1] in all_files:
                continue
            if (root.parent / rel).exists():
                continue
            # Present under a different parent: the file ships, the path is stale.
            actual = by_name.get(Path(rel).name)
            if actual:
                res.add("contradiction", "PATH_STALE", raw,
                        f"{where}:{lineno}",
                        f"{raw} does not exist; the file is at {actual}",
                        f"Update the path to {actual}.")
                continue
            res.add("contradiction", "PATH_NOT_FOUND", raw,
                    f"{where}:{lineno}",
                    f"{raw} is named in the documentation but is not in the package",
                    "Fix the path or ship the file.")
    res.checked["path_mentions"] = checked


def audit_capabilities(root: Path, lines: list, facts_by_rel: dict,
                       res: AuditResult) -> None:
    """`--help` / `--json` support asserted for scripts that do not have it."""
    # `\b--help` never matches: a hyphen and a preceding backtick are both non-word
    # characters, so there is no boundary between them. Use the same lookbehind FLAG_RE
    # uses, and match over sentences so a wrapped claim is not cut in half.
    universal = re.compile(r"\b(?:every|all|each|both)\s+(?:bundled\s+)?(?:script|tool|cli)s?\b",
                           re.IGNORECASE)
    flag_in_text = re.compile(r"(?<![\w-])(--(?:help|json))\b", re.IGNORECASE)

    checked = 0
    seen: set = set()
    for where, lineno, paragraph in doc_paragraphs(lines):
        for sentence in sentences(paragraph):
            if not universal.search(sentence):
                continue
            wanted = {f.lower() for f in flag_in_text.findall(sentence)}
            if not wanted:
                continue
            if NEGATION_RE.search(sentence) or HISTORICAL_RE.search(sentence):
                continue
            # A hedged sentence names its exceptions; those scripts are excluded.
            excepted = set()
            if HEDGE_RE.search(sentence):
                excepted = {rel for rel in facts_by_rel
                            if rel in paragraph or Path(rel).name in paragraph}
            for want in sorted(wanted):
                key = (where, lineno, sentence, want)
                if key in seen:
                    continue
                seen.add(key)
                checked += 1
                # Underscore-prefixed files *and* directories are shared modules,
                # imported by their siblings rather than run. `scripts/_shared/safe_io.py`
                # having no CLI is the design, not a missing feature.
                missing = sorted(rel for rel, f in facts_by_rel.items()
                                 if not any(part.startswith("_")
                                            for part in Path(rel).parts)
                                 # assets/ holds sample data and demo fixtures, not
                                 # this package's own tools. "every script" means the
                                 # skill's scripts, not the ones it ships to practice on.
                                 and not rel.startswith("assets/")
                                 and rel not in excepted
                                 and want not in {x.lower() for x in f.flags})
                if missing:
                    res.add("contradiction", "CAPABILITY_CLAIM_FALSE", sentence,
                            f"{where}:{lineno}",
                            f"{len(missing)} script(s) have no working {want}: "
                            f"{', '.join(missing[:4])}"
                            f"{' and more' if len(missing) > 4 else ''}",
                            f"Add {want}, or narrow the claim to the scripts it holds for.")
    res.checked["capability_claims"] = checked


# --- driver -------------------------------------------------------------------------

def audit(root: Path) -> AuditResult:
    res = AuditResult(skill=str(root))
    scripts = [p for p in sorted(root.rglob("*.py"))
               if "__pycache__" not in p.parts and ".git" not in p.parts
               and not p.name.startswith("test_")
               and "tests" not in p.parts]
    facts_by_rel = {str(p.relative_to(root)): script_facts(p) for p in scripts}
    facts_by_name: dict = {}
    for rel, f in facts_by_rel.items():
        facts_by_name.setdefault(Path(rel).name, f)

    lines = doc_lines(root)
    audit_commands(root, lines, facts_by_rel, facts_by_name, res)
    audit_reach(root, lines, facts_by_name, facts_by_rel, res)
    audit_counts(root, lines, res)
    audit_paths(root, lines, res)
    audit_capabilities(root, lines, facts_by_rel, res)
    res.checked["scripts_analysed"] = len(scripts)
    return res


def render(res: AuditResult) -> str:
    out = [f"=== claim audit: {Path(res.skill).name} ==="]
    counts = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in res.checked.items())
    out.append(f"  checked: {counts}")
    if not res.findings:
        out.append("  TRUTHFUL  (0 contradictions)")
        return "\n".join(out)
    for f in res.findings:
        marker = "✗ CONTRADICTION" if f.severity == "contradiction" else "? UNVERIFIED"
        claim = f.claim if len(f.claim) <= 110 else f.claim[:107] + "..."
        out.append(f"  {marker} {f.code}  [{f.where}]")
        out.append(f"      says:     {claim}")
        out.append(f"      but:      {f.evidence}")
        if f.fix:
            out.append(f"      →         {f.fix}")
    n = len(res.contradictions)
    unver = len(res.findings) - n
    verdict = "CONTRADICTED" if n else "TRUTHFUL"
    out.append(f"  {verdict}  ({n} contradictions, {unver} unverified)")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="claim_auditor.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Check a skill's documentation claims against what its files do.",
        epilog="""
Examples:
  python3 claim_auditor.py path/to/skill
  python3 claim_auditor.py path/to/skill --json
  python3 claim_auditor.py path/to/skills-dir --recursive
  python3 claim_auditor.py path/to/skill --strict     # unverified claims fail too

Exit codes:
  0  no contradictions
  1  the audit could not run
  2  at least one documented claim is contradicted by the tree
        """,
    )
    ap.add_argument("path", type=Path, help="skill directory to audit")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    ap.add_argument("--recursive", action="store_true",
                    help="audit every skill directory beneath PATH")
    ap.add_argument("--strict", action="store_true",
                    help="treat UNVERIFIED claims as failures too")
    args = ap.parse_args(argv)

    root = args.path
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1

    targets = ([p.parent for p in sorted(root.rglob("SKILL.md"))]
               if args.recursive else [root])
    if not targets:
        print(f"error: no SKILL.md found under {root}", file=sys.stderr)
        return 1
    if not args.recursive and not (root / "SKILL.md").is_file():
        print(f"error: {root}/SKILL.md not found", file=sys.stderr)
        return 1

    results = [audit(t) for t in targets]
    if args.json:
        print(json.dumps([{
            "skill": r.skill,
            "checked": r.checked,
            "findings": [asdict(f) for f in r.findings],
            "contradictions": len(r.contradictions),
        } for r in results], indent=2, sort_keys=True))
    else:
        print("\n\n".join(render(r) for r in results))

    failed = sum(len(r.contradictions) for r in results)
    if args.strict:
        failed += sum(len(r.findings) - len(r.contradictions) for r in results)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
