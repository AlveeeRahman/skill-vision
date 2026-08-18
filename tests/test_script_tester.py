#!/usr/bin/env python3
"""
Tests for script_tester.py — regression tests for the 2026-08 field-audit defects.

Each test pins a defect the field audit proved with real skills:
- non-recursive glob silently skipped 71% of a 145-script corpus
- results keyed by basename dropped scripts whose names repeat across sub-packages
- basic_execution accepted uncaught tracebacks (exit 1) as passes
- stdlib modules (stat, posixpath, concurrent) and skill-local packages were
  reported as external dependencies
- one passing script diluted a suite with hard failures down to PARTIAL

Run with: python -m unittest test_script_tester
"""

import unittest
import tempfile
import shutil
from pathlib import Path

import sys
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import ast
from script_tester import ScriptTester, ScriptTestResult
from script_tester import TestSuite as ResultSuite  # alias: not a pytest class


def make_skill(tmp: Path, scripts: dict) -> Path:
    """Create a throwaway skill directory with the given scripts mapping
    (relative path under scripts/ -> file content)."""
    root = tmp / "sample-skill"
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: sample-skill\ndescription: x\n---\n# S\n")
    for rel, content in scripts.items():
        p = root / "scripts" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


GOOD_CLI = (
    "import argparse\n"
    "def main():\n"
    "    p = argparse.ArgumentParser()\n"
    "    p.parse_args()\n"
    "if __name__ == '__main__':\n"
    "    main()\n"
)


class TestRecursiveDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_nested_scripts_are_discovered(self):
        root = make_skill(self.tmp, {
            "top.py": GOOD_CLI,
            "nested/inner.py": GOOD_CLI,
            "nested/deeper/leaf.py": GOOD_CLI,
        })
        suite = ScriptTester(str(root)).test_all_scripts()
        self.assertEqual(suite.summary["total_scripts"], 3)

    def test_pycache_is_not_a_script(self):
        root = make_skill(self.tmp, {
            "top.py": GOOD_CLI,
            "__pycache__/junk.py": "x = 1\n",
        })
        suite = ScriptTester(str(root)).test_all_scripts()
        self.assertEqual(suite.summary["total_scripts"], 1)

    def test_duplicate_basenames_do_not_collide(self):
        root = make_skill(self.tmp, {
            "a/_common.py": GOOD_CLI,
            "b/_common.py": GOOD_CLI,
        })
        suite = ScriptTester(str(root)).test_all_scripts()
        self.assertEqual(suite.summary["total_scripts"], 2)


class TestBasicExecution(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _run(self, content):
        root = make_skill(self.tmp, {"one.py": content})
        suite = ScriptTester(str(root)).test_all_scripts()
        return suite.script_results["one.py"].tests["basic_execution"]

    def test_uncaught_traceback_is_a_crash(self):
        check = self._run("raise RuntimeError('boom')\n")
        self.assertFalse(check["passed"])

    def test_graceful_exit_1_still_passes(self):
        check = self._run("import sys\nprint('usage: one.py FILE')\nsys.exit(1)\n")
        self.assertTrue(check["passed"])


class TestImportClassification(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _externals(self, scripts, target="main.py"):
        root = make_skill(self.tmp, scripts)
        tester = ScriptTester(str(root))
        tree = ast.parse((root / "scripts" / target).read_text())
        return tester._find_external_imports(tree, root / "scripts" / target)

    def test_forgotten_stdlib_modules_are_stdlib(self):
        ext = self._externals({"main.py": "import stat\nimport posixpath\nimport concurrent.futures\n"})
        self.assertEqual(ext, [])

    def test_skill_local_sibling_module_is_not_external(self):
        ext = self._externals({
            "main.py": "import helpers\nfrom office import soffice\n",
            "helpers.py": "x = 1\n",
            "office/__init__.py": "",
            "office/soffice.py": "y = 2\n",
        })
        self.assertEqual(ext, [])

    def test_genuine_third_party_import_is_still_external(self):
        ext = self._externals({"main.py": "import requests\n"})
        self.assertEqual(ext, ["requests"])


class TestSuiteAggregation(unittest.TestCase):
    def _suite(self, *statuses):
        suite = ResultSuite("skill")
        for i, status in enumerate(statuses):
            r = ScriptTestResult(f"skill/scripts/s{i}.py")
            r.overall_status = status
            suite.add_script_result(r)
        suite.calculate_summary()
        return suite.summary

    def test_one_pass_does_not_dilute_failures(self):
        self.assertEqual(self._suite("PASS", "FAIL")["overall_status"], "FAIL")

    def test_partial_scripts_do_not_report_pass(self):
        # The defect this pins: research-hound reported 0 passed / 27 partial as
        # overall PASS with exit 0, because calculate_summary never read `partial`.
        summary = self._suite(*(["PARTIAL"] * 27))
        self.assertEqual(summary["passed"], 0)
        self.assertEqual(summary["partial"], 27)
        self.assertEqual(summary["overall_status"], "PARTIAL")

    def test_one_partial_downgrades_an_otherwise_clean_suite(self):
        self.assertEqual(self._suite("PASS", "PASS", "PARTIAL")["overall_status"], "PARTIAL")

    def test_failure_outranks_partial(self):
        self.assertEqual(self._suite("PARTIAL", "FAIL")["overall_status"], "FAIL")

    def test_all_passing_is_the_only_way_to_pass(self):
        self.assertEqual(self._suite("PASS", "PASS")["overall_status"], "PASS")

    def test_no_tests_still_downgrades(self):
        self.assertEqual(self._suite("PASS", "NO_TESTS")["overall_status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
