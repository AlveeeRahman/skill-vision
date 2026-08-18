#!/usr/bin/env python3
"""Tests for skill_mapper.py.

Two things matter here more than the diagram's looks. First, every node and edge
must be checkable against the filesystem — a fixture asserts that against `ls`/`cat`
directly, not against the mapper's own idea of itself. Second, the mapper and
spec_validator.check_links() both read build_graph() — a fixture proves they report
the same broken/orphaned files on the same skill, because a map that disagrees with
the validator it shares a resolver with would mean the resolver itself drifted.

Run:  python3 -m pytest tests/test_skill_mapper.py -q
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import skill_mapper as sm  # noqa: E402
import spec_validator as sv  # noqa: E402


def build(tmp: Path, name: str, frontmatter: str, body: str = "# Title\n\nSome body.\n",
          files: dict | None = None) -> Path:
    root = tmp / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    for rel, content in (files or {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


GOOD_FM = ("name: sample-skill\n"
           "description: Does a specific thing with files. Use when the user asks to do "
           "that specific thing, mentions the artifact by name, or needs it automated.")


class SkillMapperTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- accuracy: every drawn node is a real file ---------------------------------

    def test_every_node_path_exists_on_disk(self):
        root = build(self.tmp, "s", GOOD_FM, body="See [g](references/g.md).\n",
                     files={"references/g.md": "# G\n", "scripts/tool.py": "import argparse\n"})
        model = sm.collect(root)
        for node in model["nodes"]:
            self.assertTrue((root / node["path"]).is_file(),
                            f"drawn node {node['path']} does not exist on disk")

    def test_every_resolved_edge_target_is_a_real_file(self):
        root = build(self.tmp, "s", GOOD_FM, body="See [g](references/g.md).\n",
                     files={"references/g.md": "# G\n"})
        model = sm.collect(root)
        for edge in model["edges"]:
            self.assertTrue((root / edge["target"]).is_file(),
                            f"edge target {edge['target']} does not exist on disk")

    def test_unlinked_script_still_appears(self):
        # Scripts are reached by execution, not by markdown links — an unlinked one is
        # still part of the codebase and must not vanish from the map.
        root = build(self.tmp, "s", GOOD_FM, files={"scripts/orphan_tool.py": "x = 1\n"})
        model = sm.collect(root)
        self.assertIn("scripts/orphan_tool.py", {n["path"] for n in model["nodes"]})

    def test_file_count_matches_ls(self):
        root = build(self.tmp, "s", GOOD_FM,
                     body="[g](references/g.md) [a](assets/a.txt)\n",
                     files={"references/g.md": "# G\n", "assets/a.txt": "data\n",
                            "scripts/tool.py": "x = 1\n"})
        model = sm.collect(root)
        on_disk = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        self.assertEqual(model["counts"]["files_on_disk"], len(on_disk))

    # --- parity with spec_validator: same resolver, same verdict -------------------

    def test_broken_and_orphaned_findings_match_validator(self):
        root = build(
            self.tmp, "s", GOOD_FM,
            body=("[good](references/g.md) [gone](references/missing.md) "
                  "[out](../outside.md)\n"),
            files={"references/g.md": "# G\n", "references/stranded.md": "# Alone\n"},
        )
        model = sm.collect(root)
        result = sv.validate(root)

        mapper_broken = {m["raw"] for m in model["missing"]}
        validator_broken = {f.message.split(" links to ")[-1].split(",")[0]
                            for f in result.findings if f.code == "DANGLING_REFERENCE"}
        validator_broken |= {f.message.split("references ")[-1].split(",")[0]
                             for f in result.findings if f.code == "PATH_ESCAPES_SKILL"}
        self.assertEqual(mapper_broken, validator_broken)

        mapper_stranded = {n["path"] for n in model["nodes"] if n.get("stranded")}
        validator_orphaned = {f.message.split(" is bundled")[0]
                              for f in result.findings if f.code == "ORPHANED_REFERENCE"}
        self.assertEqual(mapper_stranded, validator_orphaned)

    def test_clean_skill_has_no_broken_or_stranded_nodes(self):
        root = build(self.tmp, "s", GOOD_FM, body="[g](references/g.md)\n",
                     files={"references/g.md": "# G\n"})
        model = sm.collect(root)
        self.assertEqual(model["counts"]["broken_links"], 0)
        self.assertEqual(model["counts"]["stranded"], 0)
        self.assertEqual(model["counts"]["too_deep"], 0)

    def test_too_deep_nodes_match_validator_findings(self):
        root = build(
            self.tmp, "s", GOOD_FM,
            body="[guide](guides/a.md)\n",
            files={"guides/a.md": "[deep](references/b.md)\n",
                   "references/b.md": "[deeper](references/c.md)\n",
                   "references/c.md": "# C\n"},
        )
        model = sm.collect(root)
        result = sv.validate(root)

        mapper_deep = {n["path"] for n in model["nodes"] if n.get("too_deep")}
        validator_deep = {f.message.split(" is ")[0]
                          for f in result.findings if f.code == "REFERENCE_TOO_DEEP"}
        self.assertEqual(mapper_deep, validator_deep)
        self.assertEqual(mapper_deep, {"references/b.md", "references/c.md"})

    def test_hop_counts_recorded_on_nodes(self):
        root = build(self.tmp, "s", GOOD_FM, body="[guide](guides/a.md)\n",
                     files={"guides/a.md": "[deep](references/b.md)\n",
                            "references/b.md": "# B\n"})
        hops = {n["path"]: n.get("hops") for n in sm.collect(root)["nodes"]}
        self.assertEqual(hops["SKILL.md"], 0)
        self.assertEqual(hops["guides/a.md"], 1)
        self.assertEqual(hops["references/b.md"], 2)

    # --- rendering -------------------------------------------------------------

    def test_render_stays_valid_mermaid_flowchart(self):
        root = build(self.tmp, "s", GOOD_FM, body="[g](references/g.md)\n",
                     files={"references/g.md": "# G\n", "scripts/tool.py": "x = 1\n"})
        diagram, _ = sm.render_mermaid(sm.collect(root))
        self.assertTrue(diagram.startswith("flowchart "))
        self.assertEqual(diagram.count("flowchart"), 1)

    def test_broken_and_stranded_nodes_get_their_own_style_class(self):
        root = build(self.tmp, "s", GOOD_FM,
                     body="[gone](references/missing.md)\n",
                     files={"references/stranded.md": "# Alone\n"})
        diagram, _ = sm.render_mermaid(sm.collect(root))
        self.assertIn("class n_missing_0 broken", diagram.replace(" ", " "))
        self.assertIn("orphan", diagram)

    def test_max_nodes_trims_the_largest_group_and_reports_it(self):
        files = {f"references/r{i}.md": f"# R{i}\n" for i in range(20)}
        body = " ".join(f"[r{i}](references/r{i}.md)" for i in range(20))
        root = build(self.tmp, "s", GOOD_FM, body=body, files=files)
        model = sm.collect(root)
        diagram, notices = sm.render_mermaid(model, max_nodes=10)
        self.assertTrue(notices, "trimming below the file count must be announced")
        self.assertIn("collapsed", notices[0])
        drawn = diagram.count("r0_md") + diagram.count("r19_md")
        self.assertLessEqual(diagram.count('.md"]'), 15)

    def test_direction_flag_changes_the_flowchart_header(self):
        root = build(self.tmp, "s", GOOD_FM)
        diagram, _ = sm.render_mermaid(sm.collect(root), direction="LR")
        self.assertTrue(diagram.startswith("flowchart LR"))

    # --- detail mode: AST facts, no call inference ----------------------------

    def test_detail_reports_ast_function_and_flag_counts_exactly(self):
        script = (
            "import argparse\n"
            "def a():\n    pass\n"
            "def b():\n    pass\n"
            "class C:\n    pass\n"
            "def main():\n"
            "    p = argparse.ArgumentParser()\n"
            "    p.add_argument('--json')\n"
            "    p.add_argument('--verbose')\n"
        )
        root = build(self.tmp, "s", GOOD_FM, files={"scripts/tool.py": script})
        model = sm.collect(root, detail=True)
        node = next(n for n in model["nodes"] if n["path"] == "scripts/tool.py")
        self.assertEqual(node["facts"]["functions"], 3)
        self.assertEqual(node["facts"]["classes"], 1)
        self.assertEqual(set(node["facts"]["flags"]), {"--json", "--verbose"})

    def test_detail_on_unparseable_script_reports_error_not_crash(self):
        root = build(self.tmp, "s", GOOD_FM, files={"scripts/broken.py": "def f(:\n"})
        model = sm.collect(root, detail=True)
        node = next(n for n in model["nodes"] if n["path"] == "scripts/broken.py")
        self.assertTrue(node["facts"]["parse_error"])

    # --- code edges: import statements are AST facts, unlike call graphs -------

    def test_import_edge_drawn_between_sibling_scripts(self):
        root = build(self.tmp, "s", GOOD_FM,
                     files={"scripts/mapper.py": "from helper import thing\n",
                            "scripts/helper.py": "thing = 1\n"})
        model = sm.collect(root)
        code_edges = [e for e in model["edges"] if e["kind"] == "code"]
        self.assertEqual(code_edges,
                         [{"source": "scripts/mapper.py", "target": "scripts/helper.py",
                           "status": "ok", "kind": "code"}])
        self.assertEqual(model["counts"]["code_deps"], 1)

    def test_import_edge_not_drawn_across_directories(self):
        # These flat script folders resolve local imports via sys.path.insert(0, own
        # dir), so a same-named file in a different directory is not what "import
        # helper" actually reaches — matching it would be a false edge.
        root = build(self.tmp, "s", GOOD_FM,
                     files={"scripts/mapper.py": "import helper\n",
                            "other/helper.py": "x = 1\n"})
        model = sm.collect(root)
        self.assertEqual([e for e in model["edges"] if e["kind"] == "code"], [])

    def test_stdlib_import_does_not_fabricate_an_edge(self):
        root = build(self.tmp, "s", GOOD_FM, files={"scripts/tool.py": "import json\n"})
        model = sm.collect(root)
        self.assertEqual([e for e in model["edges"] if e["kind"] == "code"], [])

    def test_facts_available_for_code_edges_even_without_detail(self):
        # Import edges are structural, not decoration, so they must not require --detail
        # — but the fn/cls/flags annotation stays detail-gated, so facts don't leak.
        root = build(self.tmp, "s", GOOD_FM,
                     files={"scripts/mapper.py": "from helper import thing\n",
                            "scripts/helper.py": "thing = 1\n"})
        model = sm.collect(root, detail=False)
        self.assertEqual(model["counts"]["code_deps"], 1)
        self.assertTrue(all("facts" not in n for n in model["nodes"]))

    def test_code_edge_rendered_with_needs_label_and_distinct_style(self):
        root = build(self.tmp, "s", GOOD_FM,
                     files={"scripts/mapper.py": "from helper import thing\n",
                            "scripts/helper.py": "thing = 1\n"})
        diagram, _ = sm.render_mermaid(sm.collect(root))
        self.assertIn("n_scripts_mapper_py ==>|needs| n_scripts_helper_py", diagram)
        self.assertIn("linkStyle", diagram)

    # --- CLI surface -----------------------------------------------------------

    def test_missing_skill_md_is_a_clean_error_not_a_traceback(self):
        root = self.tmp / "not-a-skill"
        root.mkdir()
        with self.assertRaises(FileNotFoundError):
            sm.collect(root)

    def test_json_output_is_the_same_model_collect_returns(self):
        import json
        import subprocess
        root = build(self.tmp, "s", GOOD_FM, body="[g](references/g.md)\n",
                     files={"references/g.md": "# G\n"})
        mapper = Path(__file__).resolve().parents[1] / "scripts" / "skill_mapper.py"
        out = subprocess.run([sys.executable, str(mapper), str(root), "--json"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0)
        payload = json.loads(out.stdout)
        self.assertEqual(payload["counts"], sm.collect(root)["counts"])


if __name__ == "__main__":
    unittest.main()
