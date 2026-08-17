#!/usr/bin/env python3
"""Adversarial tests for spec_validator.py.

Each test builds a throwaway skill with one known defect and asserts the validator
reports exactly that defect — and, just as importantly, that a clean skill produces no
findings. A validator with no false-negative tests is untrustworthy; a validator with no
false-positive tests is unusable.

Run:  python3 -m pytest tests/test_spec_validator.py -q
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import spec_validator as sv  # noqa: E402


def build(tmp: Path, name: str, frontmatter: str, body: str = "# Title\n\nSome body.\n",
          files: dict | None = None) -> Path:
    """Create a skill directory and return its path."""
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


class SpecValidatorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def codes(self, root: Path) -> set:
        return {f.code for f in sv.validate(root).findings}

    def result(self, root: Path):
        return sv.validate(root)

    # --- false positives: a clean skill must be silent ----------------------------

    def test_clean_skill_is_conformant(self):
        root = build(self.tmp, "sample-skill", GOOD_FM)
        res = self.result(root)
        self.assertTrue(res.conformant, f"clean skill flagged: {[f.code for f in res.findings]}")
        self.assertEqual(res.count("error"), 0)

    def test_clean_skill_with_references_is_conformant(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\nSee [the guide](references/guide.md).\n",
                     files={"references/guide.md": "# Guide\n\nDetail.\n"})
        res = self.result(root)
        self.assertTrue(res.conformant)
        self.assertNotIn("ORPHANED_REFERENCE", {f.code for f in res.findings})

    def test_root_relative_paths_from_nested_file_resolve(self):
        """Regression: paths in guides/ are relative to the skill root, not the file."""
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\nSee [guide](guides/a.md).\n",
                     files={"guides/a.md": "See `references/deep/x.md` for detail.\n",
                            "references/deep/x.md": "# X\n"})
        self.assertNotIn("DANGLING_REFERENCE", self.codes(root))

    def test_documentation_skill_not_penalised_for_missing_scripts(self):
        root = build(self.tmp, "sample-skill", GOOD_FM)
        res = self.result(root)
        self.assertEqual(res.skill_type, "documentation")
        self.assertNotIn("NO_SCRIPTS", {f.code for f in res.findings})

    def test_library_module_not_required_to_have_cli(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     files={"scripts/_common.py": "VALUE = 1\n",
                            "scripts/tool.py": ("from _common import VALUE\n"
                                                "if __name__ == '__main__':\n    print(VALUE)\n")})
        codes = self.codes(root)
        self.assertNotIn("SCRIPT_NO_MAIN_GUARD", codes)

    def test_single_quoted_main_guard_is_detected(self):
        """Regression: substring matching missed single-quoted guards."""
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     files={"scripts/tool.py": "if __name__ == '__main__':\n    pass\n"})
        self.assertNotIn("SCRIPT_NO_MAIN_GUARD", self.codes(root))

    # --- name rules ---------------------------------------------------------------

    def test_name_must_match_directory(self):
        root = build(self.tmp, "actual-dir", "name: different-name\ndescription: " + "x " * 40)
        self.assertIn("NAME_DIR_MISMATCH", self.codes(root))

    def test_name_rejects_uppercase(self):
        root = build(self.tmp, "Bad-Name", "name: Bad-Name\ndescription: " + "x " * 40)
        self.assertIn("NAME_CHARSET", self.codes(root))

    def test_name_rejects_consecutive_hyphens(self):
        root = build(self.tmp, "bad--name", "name: bad--name\ndescription: " + "x " * 40)
        self.assertIn("NAME_CHARSET", self.codes(root))

    def test_name_rejects_underscores(self):
        root = build(self.tmp, "bad_name", "name: bad_name\ndescription: " + "x " * 40)
        self.assertIn("NAME_CHARSET", self.codes(root))

    def test_name_too_long(self):
        long = "a" * 70
        root = build(self.tmp, long, f"name: {long}\ndescription: " + "x " * 40)
        self.assertIn("NAME_TOO_LONG", self.codes(root))

    def test_reserved_name_fragment_warned(self):
        root = build(self.tmp, "claude-helper",
                     "name: claude-helper\ndescription: " + "x " * 40)
        self.assertIn("NAME_RESERVED", self.codes(root))

    def test_missing_name(self):
        root = build(self.tmp, "sample-skill", "description: " + "x " * 40)
        self.assertIn("MISSING_NAME", self.codes(root))

    # --- description rules --------------------------------------------------------

    def test_description_over_hard_limit(self):
        root = build(self.tmp, "sample-skill",
                     "name: sample-skill\ndescription: " + "word " * 250)
        self.assertIn("DESCRIPTION_TOO_LONG", self.codes(root))

    def test_description_near_limit_warns(self):
        desc = "Use when " + "x" * 970
        root = build(self.tmp, "sample-skill", f"name: sample-skill\ndescription: {desc}")
        self.assertIn("DESCRIPTION_NEAR_LIMIT", self.codes(root))

    def test_description_without_trigger_language(self):
        root = build(self.tmp, "sample-skill",
                     "name: sample-skill\ndescription: A tool that converts files from one "
                     "format into another format reliably and quickly every time.")
        self.assertIn("DESCRIPTION_NO_TRIGGER", self.codes(root))

    def test_missing_description(self):
        root = build(self.tmp, "sample-skill", "name: sample-skill")
        self.assertIn("MISSING_DESCRIPTION", self.codes(root))

    # --- frontmatter structure ----------------------------------------------------

    def test_unknown_frontmatter_field(self):
        root = build(self.tmp, "sample-skill", GOOD_FM + "\nTier: BASIC\nCategory: dev")
        self.assertIn("UNKNOWN_FRONTMATTER_FIELDS", self.codes(root))

    def test_spec_optional_fields_accepted(self):
        fm = GOOD_FM + "\nlicense: MIT\ncompatibility: Requires Python 3.10+\nmetadata:\n  author: me"
        root = build(self.tmp, "sample-skill", fm)
        self.assertNotIn("UNKNOWN_FRONTMATTER_FIELDS", self.codes(root))

    def test_compatibility_over_limit(self):
        fm = GOOD_FM + "\ncompatibility: " + "x" * 520
        root = build(self.tmp, "sample-skill", fm)
        self.assertIn("COMPATIBILITY_TOO_LONG", self.codes(root))

    def test_missing_frontmatter_entirely(self):
        root = self.tmp / "sample-skill"
        root.mkdir()
        (root / "SKILL.md").write_text("# No frontmatter\n", encoding="utf-8")
        self.assertIn("BAD_FRONTMATTER", self.codes(root))

    def test_yaml_flow_sequence_flagged(self):
        fm = GOOD_FM + "\nallowed-tools: [Read, Write]"
        root = build(self.tmp, "sample-skill", fm)
        self.assertIn("YAML_FLOW_SEQUENCE", self.codes(root))

    # --- structure ----------------------------------------------------------------

    def test_nested_skill_md_is_error(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     files={"assets/inner/SKILL.md": "---\nname: inner\n---\n# Inner\n"})
        self.assertIn("NESTED_SKILL_MD", self.codes(root))

    def test_missing_skill_md(self):
        root = self.tmp / "empty-skill"
        root.mkdir()
        self.assertIn("MISSING_SKILL_MD", self.codes(root))

    # --- links and reachability ---------------------------------------------------

    def test_dangling_reference_detected(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\nSee [missing](references/nope.md).\n")
        self.assertIn("DANGLING_REFERENCE", self.codes(root))

    def test_parent_escape_detected(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\nSee [sibling](../other-skill/SKILL.md).\n")
        self.assertIn("PATH_ESCAPES_SKILL", self.codes(root))

    def test_orphaned_reference_detected(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     files={"references/never-linked.md": "# Unused\n"})
        self.assertIn("ORPHANED_REFERENCE", self.codes(root))

    def test_transitive_reachability(self):
        """B is linked only from A; if SKILL.md links A, B is reachable."""
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\nSee [a](references/a.md).\n",
                     files={"references/a.md": "See [b](references/b.md).\n",
                            "references/b.md": "# B\n"})
        codes = self.codes(root)
        self.assertNotIn("ORPHANED_REFERENCE", codes)
        self.assertNotIn("DANGLING_REFERENCE", codes)

    def test_url_not_treated_as_path(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\nSee [docs](https://example.com/scripts/x.py).\n")
        self.assertNotIn("DANGLING_REFERENCE", self.codes(root))

    # --- body ---------------------------------------------------------------------

    def test_body_over_line_ceiling(self):
        body = "# Title\n\n" + "\n".join(f"line {i}" for i in range(600))
        root = build(self.tmp, "sample-skill", GOOD_FM, body=body)
        self.assertIn("BODY_TOO_LONG", self.codes(root))

    def test_short_body_is_not_an_error(self):
        """Regression: brevity is a virtue, never a failure."""
        root = build(self.tmp, "sample-skill", GOOD_FM, body="# Title\n\nDo the thing.\n")
        res = self.result(root)
        self.assertTrue(res.conformant)

    def test_unclosed_code_fence(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\n```python\nprint(1)\n")
        self.assertIn("UNCLOSED_CODE_FENCE", self.codes(root))

    def test_balanced_fences_pass(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# Title\n\n```python\nprint(1)\n```\n")
        self.assertNotIn("UNCLOSED_CODE_FENCE", self.codes(root))

    def test_body_token_budget(self):
        body = "# Title\n\n" + ("word " * 6000)
        root = build(self.tmp, "sample-skill", GOOD_FM, body=body)
        self.assertIn("BODY_TOKEN_BUDGET", self.codes(root))

    # --- packaging hygiene --------------------------------------------------------

    def test_junk_files_flagged(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     files={"scripts/__pycache__/x.cpython-312.pyc": "junk"})
        self.assertIn("JUNK_FILES", self.codes(root))

    def test_clean_package_has_no_junk_finding(self):
        root = build(self.tmp, "sample-skill", GOOD_FM)
        self.assertNotIn("JUNK_FILES", self.codes(root))

    # --- skill type detection -----------------------------------------------------

    def test_type_detection_router(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# T\n\n[a](guides/a.md) [b](guides/b.md)\n",
                     files={"guides/a.md": "# A\n", "guides/b.md": "# B\n"})
        self.assertEqual(self.result(root).skill_type, "router")

    def test_type_detection_tool(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     files={"scripts/t.py": "if __name__ == '__main__':\n    pass\n"})
        self.assertEqual(self.result(root).skill_type, "tool")

    def test_type_detection_toolkit(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     body="# T\n\nSee `references/ns/a.md` and `scripts/t.py`.\n",
                     files={"scripts/t.py": "if __name__ == '__main__':\n    pass\n",
                            "references/ns/a.md": "# A\n"})
        self.assertEqual(self.result(root).skill_type, "toolkit")

    # --- exit semantics -----------------------------------------------------------

    def test_conformant_property_ignores_warnings(self):
        root = build(self.tmp, "sample-skill", GOOD_FM,
                     files={"references/never-linked.md": "# Unused\n"})
        res = self.result(root)
        self.assertGreater(res.count("warning"), 0)
        self.assertTrue(res.conformant, "warnings alone must not fail conformance")


if __name__ == "__main__":
    unittest.main(verbosity=2)
