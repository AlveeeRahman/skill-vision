#!/usr/bin/env python3
"""Draw a skill as a Mermaid flowchart: its files, and the paths an agent can walk.

Answers a question the other four tools do not: *what is actually in here, and what
can Claude reach?* Progressive disclosure means an agent starts at SKILL.md and follows
links outward. A file nothing links to is never read, however good it is. That is a
shape question, and shapes are easier to read as a picture than as a list of findings.

Accuracy before decoration. Every node is a file that exists on disk, and every solid
edge is a reference that resolves. Both come from `spec_validator.build_graph()`, the
same resolver behind the DANGLING_REFERENCE and ORPHANED_REFERENCE checks. The map and
the verdict cannot disagree, because there is only one resolver to disagree with.

What this deliberately does not draw: call graphs between functions. Published
measurements put the best static Python call-graph tools at roughly 70% recall, so a
third of real edges are missing and nothing on the diagram says which third. A map that
is quietly incomplete is worse than no map. Everything here is checkable against `ls`.

It does draw module-level import edges between scripts — `skill_mapper.py needs
spec_validator.py` — because those are a literal AST fact (an Import/ImportFrom node
naming a sibling file), not a resolved call target. Same accuracy bar as everything
else, different question: not "what calls what" but "what fails to run if this file is
missing."

Standard library only. No network. Usage:

    python skill_mapper.py path/to/skill                  # Mermaid to stdout
    python skill_mapper.py path/to/skill --json           # the same graph as data
    python skill_mapper.py path/to/skill --detail         # annotate scripts with their CLI
    python skill_mapper.py path/to/skill --direction LR   # left-to-right layout
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Importing (and being imported) must not litter the skill under audit —
# or the harness's own spec pass will flag the bytecode it just wrote.
sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_validator import (  # noqa: E402
    JUNK_PATTERNS, build_graph, detect_type, est_tokens, parse_frontmatter,
    split_frontmatter,
)

# Past roughly 40 nodes a flowchart stops being readable, so oversized directories are
# collapsed to a count. The collapse is always announced on stderr — a map that silently
# drops files reads as "this is everything" when it is not.
DEFAULT_MAX_NODES = 40

GROUP_ORDER = ["scripts", "references", "guides", "assets", "expected_outputs", "tests"]


def _node_id(text: str) -> str:
    """Mermaid ids allow no punctuation; prefix so an id never starts with a digit."""
    return "n_" + re.sub(r"[^A-Za-z0-9]", "_", str(text))


def _label(text: str) -> str:
    """Escape a Mermaid label. Quoted labels tolerate most punctuation except quotes."""
    return str(text).replace('"', "&quot;")


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def script_facts(path: Path) -> dict:
    """Top-level shape of a Python file, read straight from its AST.

    Only what the syntax tree states outright: how many functions and classes are
    defined, which flags argparse registers, and which modules it imports. No call
    resolution, no inference — `imports` is names as written, unresolved to a path.
    """
    facts = {"functions": 0, "classes": 0, "flags": [], "imports": [], "parse_error": ""}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError, ValueError) as exc:
        facts["parse_error"] = type(exc).__name__
        return facts
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts["functions"] += 1
        elif isinstance(node, ast.ClassDef):
            facts["classes"] += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    facts["flags"].append(arg.value)
        elif isinstance(node, ast.Import):
            facts["imports"].extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:      # skip "from . import x": no name to match
                facts["imports"].append(node.module.split(".")[0])
    facts["imports"] = sorted(set(facts["imports"]))
    return facts


def collect(root: Path, detail: bool = False) -> dict:
    """Resolve the skill into nodes and edges, using the validator's own resolver."""
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"{root} has no SKILL.md — not a skill directory.")

    text = skill_md.read_text(encoding="utf-8", errors="ignore")
    fm_text, body, err = split_frontmatter(text)
    frontmatter = {} if err else (parse_frontmatter(fm_text) or {})
    graph = build_graph(root, body if not err else text)

    description = str(frontmatter.get("description", ""))
    tokens = {"description": est_tokens(description), "body": est_tokens(body)}
    tokens["total"] = tokens["description"] + tokens["body"]

    nodes: dict = {}

    def add_node(rel: str, kind: str, **extra) -> None:
        if rel in nodes:
            nodes[rel].update({k: v for k, v in extra.items() if v})
            return
        node = {"path": rel, "name": Path(rel).name, "kind": kind,
                "group": Path(rel).parts[0] if len(Path(rel).parts) > 1 else "."}
        node.update(extra)
        nodes[rel] = node

    add_node("SKILL.md", "entry", tokens=tokens["body"])

    edges, missing = [], []
    for edge in graph.edges:
        if edge.status == "ok":
            if edge.target == edge.source:      # a file citing its own name is not a hop
                continue
            target = root / edge.target
            add_node(edge.source, "markdown")
            add_node(edge.target,
                     "script" if target.suffix == ".py" else
                     "markdown" if target.suffix == ".md" else "asset")
            edges.append({"source": edge.source, "target": edge.target, "status": "ok",
                         "kind": "doc"})
        elif edge.status in ("dangling", "escapes"):
            add_node(edge.source, "markdown")
            missing.append({"source": edge.source, "raw": edge.raw, "status": edge.status})

    reachable = {str(p) for p in graph.reachable}
    referenced = {str(p) for p in graph.referenced}
    bundled = {str(p) for p in graph.bundled}
    for rel, node in nodes.items():
        node["reachable"] = rel == "SKILL.md" or rel in reachable
        # Only files the agent is meant to load count as stranded. README.md, LICENSE and
        # friends are written for humans and are not reachable from SKILL.md by design —
        # flagging them would put the map at odds with the validator, which does not
        # report them either.
        # Match check_links() exactly: only bundled markdown is reported orphaned. A
        # script or a CSV is reached by being executed or opened, not by being linked,
        # so calling it stranded would contradict the validator on the same skill.
        node["bundled"] = rel in bundled
        node["stranded"] = (node["bundled"] and not node["reachable"]
                            and rel.lower().endswith(".md"))
        # Same hop counts spec_validator reports as REFERENCE_TOO_DEEP, off the same
        # graph, so the picture and the verdict cannot disagree about which files an
        # agent has to walk two links to reach.
        node["hops"] = 0 if rel == "SKILL.md" else graph.hops.get(Path(rel))
        node["too_deep"] = bool(node["hops"] and node["hops"] > 1
                                and rel.lower().endswith(".md"))

    # Python is reached by being run, not by being linked, so a script no markdown
    # mentions is still part of the codebase. Draw every one of them or the map would
    # report a file count lower than `ls` does.
    for py in sorted(root.rglob("*.py")):
        if any(j in py.parts for j in JUNK_PATTERNS):
            continue
        add_node(str(py.relative_to(root)), "script")

    # Bundled files nothing links to never load. They are part of the truth about the
    # skill, so they belong on the map — drawn detached, which is what they are.
    for rel_path in graph.bundled:
        rel = str(rel_path)
        if rel not in nodes and rel not in referenced:
            add_node(rel, "orphan", reachable=False, bundled=True,
                     stranded=rel.lower().endswith(".md"))

    # Everything on disk, so the summary can say what it left out rather than letting a
    # smaller number pass for the whole directory.
    on_disk = sum(1 for f in root.rglob("*")
                  if f.is_file() and not any(j in f.parts for j in JUNK_PATTERNS)
                  and f.name != ".DS_Store")

    # Import edges answer "what needs what to run" — a question doc links can't, since a
    # script that imports a sibling is never required to link to it in prose. Resolved
    # by module name against scripts in the *same directory only*, matching the
    # sys.path.insert(0, own-dir) convention these flat script folders actually use —
    # matching repo-wide would risk pairing a stdlib/third-party name with an unrelated
    # local file of the same name.
    facts_by_path = {rel: script_facts(root / rel)
                     for rel, node in nodes.items() if node["kind"] == "script"}
    for rel, node in nodes.items():
        if node["kind"] == "script":
            node["facts"] = facts_by_path[rel]

    code_edges = []
    by_dir: dict = {}
    for rel in facts_by_path:
        by_dir.setdefault(str(Path(rel).parent), {})[Path(rel).stem] = rel
    for rel, facts in facts_by_path.items():
        if facts.get("parse_error"):
            continue
        siblings = by_dir.get(str(Path(rel).parent), {})
        for name in facts["imports"]:
            target = siblings.get(name)
            if target and target != rel:
                code_edges.append({"source": rel, "target": target, "status": "ok",
                                   "kind": "code"})
    edges.extend(code_edges)

    if not detail:
        for node in nodes.values():
            node.pop("facts", None)

    return {
        "skill": root.name,
        "type": detect_type(root),
        "tokens": tokens,
        "nodes": list(nodes.values()),
        "edges": edges,
        "missing": missing,
        "counts": {
            "files": len(nodes),
            "files_on_disk": on_disk,
            "links": len(edges) - len(code_edges),
            "code_deps": len(code_edges),
            "broken_links": len(missing),
            "stranded": sum(1 for n in nodes.values() if n.get("stranded")),
            "too_deep": sum(1 for n in nodes.values() if n.get("too_deep")),
        },
    }


def render_mermaid(model: dict, direction: str = "TD",
                   max_nodes: int = DEFAULT_MAX_NODES) -> tuple:
    """Render the model as a Mermaid flowchart. Returns (diagram, notices)."""
    nodes = {n["path"]: n for n in model["nodes"]}
    notices = []

    groups: dict = {}
    for node in nodes.values():
        groups.setdefault(node["group"], []).append(node)

    # Trim only if over budget, largest group first, and say so out loud.
    budget = max(len(groups) + 1, max_nodes)
    hidden: dict = {}
    while len(nodes) - sum(hidden.values()) > budget:
        biggest = max(groups, key=lambda g: len(groups[g]) - hidden.get(g, 0))
        if len(groups[biggest]) - hidden.get(biggest, 0) <= 3:
            break
        hidden[biggest] = hidden.get(biggest, 0) + 1
    shown = set()
    for group, members in groups.items():
        keep = sorted(members, key=lambda n: n["path"])
        drop = hidden.get(group, 0)
        if drop:
            keep = keep[: len(keep) - drop]
            notices.append(f"{group}/: showing {len(keep)} of {len(members)} files "
                           f"({drop} collapsed to fit the {max_nodes}-node budget)")
        shown.update(n["path"] for n in keep)

    out = [f"flowchart {direction}"]
    tokens = model["tokens"]
    out.append(f'  {_node_id("SKILL.md")}["SKILL.md<br/>~{_fmt_tokens(tokens["body"])} '
               f'tokens on trigger"]')

    for group in sorted(groups, key=lambda g: (GROUP_ORDER.index(g)
                                               if g in GROUP_ORDER else 99, g)):
        members = [n for n in sorted(groups[group], key=lambda n: n["path"])
                   if n["path"] in shown and n["path"] != "SKILL.md"]
        if not members:
            continue
        if group == ".":
            for node in members:
                out.append(f'  {_node_id(node["path"])}["{_label(node["name"])}"]')
            continue
        out.append(f'  subgraph {_node_id("g_" + group)}["{_label(group)}/"]')
        for node in members:
            label = _label(node["name"])
            facts = node.get("facts")
            if facts and not facts.get("parse_error"):
                label += (f'<br/>{facts["functions"]} fn · {facts["classes"]} cls')
                if facts["flags"]:
                    label += "<br/>" + _label(" ".join(sorted(set(facts["flags"]))[:4]))
            out.append(f'    {_node_id(node["path"])}["{label}"]')
        out.append("  end")

    for i, miss in enumerate(model["missing"]):
        out.append(f'  {_node_id("missing_%d" % i)}["{_label(miss["raw"])}<br/>'
                   f'{"outside the skill" if miss["status"] == "escapes" else "missing"}"]')

    seen = set()
    link_index = 0
    code_link_indices = []
    for edge in model["edges"]:
        if edge["source"] not in shown and edge["source"] != "SKILL.md":
            continue
        if edge["target"] not in shown:
            continue
        kind = edge.get("kind", "doc")
        key = (edge["source"], edge["target"], kind)
        if key in seen:
            continue
        seen.add(key)
        if kind == "code":
            out.append(f'  {_node_id(edge["source"])} ==>|needs| {_node_id(edge["target"])}')
            code_link_indices.append(link_index)
        else:
            out.append(f'  {_node_id(edge["source"])} --> {_node_id(edge["target"])}')
        link_index += 1
    for i, miss in enumerate(model["missing"]):
        out.append(f'  {_node_id(miss["source"])} -.-> {_node_id("missing_%d" % i)}')
        link_index += 1

    stranded = [n for n in nodes.values()
                if n.get("stranded") and n["path"] in shown and n["path"] != "SKILL.md"]
    # Reachable, but only via another reference. Not broken, so not red; distinct from
    # orphaned, because the agent can get there — it just tends to skim instead of read.
    too_deep = [n for n in nodes.values()
                if n.get("too_deep") and n["path"] in shown
                and not n.get("stranded") and n["path"] != "SKILL.md"]

    out.append("  classDef entry fill:#f59e0b,stroke:#b45309,color:#1f2937")
    out.append("  classDef orphan fill:#e5e7eb,stroke:#9ca3af,color:#6b7280,"
               "stroke-dasharray:4 3")
    out.append("  classDef broken fill:#fecaca,stroke:#dc2626,color:#7f1d1d")
    out.append("  classDef deep fill:#fef3c7,stroke:#d97706,color:#78350f,"
               "stroke-dasharray:2 2")
    out.append(f'  class {_node_id("SKILL.md")} entry')
    if stranded:
        out.append("  class " + ",".join(_node_id(n["path"]) for n in stranded)
                   + " orphan")
    if too_deep:
        out.append("  class " + ",".join(_node_id(n["path"]) for n in too_deep)
                   + " deep")
    if model["missing"]:
        out.append("  class " + ",".join(_node_id("missing_%d" % i)
                                         for i in range(len(model["missing"]))) + " broken")
    if code_link_indices:
        out.append("  linkStyle " + ",".join(str(i) for i in code_link_indices)
                   + " stroke:#2563eb,stroke-width:2px")
    return "\n".join(out), notices


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Draw a skill's files and reference graph as a Mermaid flowchart.")
    ap.add_argument("path", help="skill directory containing SKILL.md")
    ap.add_argument("--json", action="store_true",
                    help="emit the graph as JSON instead of Mermaid")
    ap.add_argument("--detail", action="store_true",
                    help="annotate scripts with their definition counts and CLI flags")
    ap.add_argument("--direction", default="TD", choices=["TD", "LR", "BT", "RL"],
                    help="Mermaid layout direction (default: TD)")
    ap.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES,
                    help=f"readability budget (default: {DEFAULT_MAX_NODES})")
    ap.add_argument("--fence", action="store_true",
                    help="wrap the diagram in a ```mermaid block for pasting into markdown")
    args = ap.parse_args()

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        model = collect(root.resolve(), detail=args.detail)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(model, indent=2, sort_keys=True))
        return 0

    diagram, notices = render_mermaid(model, args.direction, args.max_nodes)
    print(f"```mermaid\n{diagram}\n```" if args.fence else diagram)

    counts = model["counts"]
    summary = (f"{counts['files']} files mapped · {counts['links']} resolved links · "
               f"{counts['code_deps']} code dependencies · "
               f"{counts['broken_links']} broken · "
               f"{counts['stranded']} stranded from SKILL.md · "
               f"{counts['too_deep']} more than one hop away")
    print(f"\n{summary}", file=sys.stderr)
    skipped = counts["files_on_disk"] - counts["files"]
    if skipped > 0:
        print(f"note: {skipped} further files on disk are outside the skill surface "
              f"(repo scaffolding, docs sites, dotfiles) and are not drawn",
              file=sys.stderr)
    for notice in notices:
        print(f"note: {notice}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
