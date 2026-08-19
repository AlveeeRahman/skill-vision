#!/usr/bin/env python3
"""Adversarial tests for claim_auditor.py.

Two failure modes matter equally here and both are tested:

  - False negatives. An auditor that reports TRUTHFUL because it is broken is worse
    than no auditor, so every check has a fixture that plants the defect and asserts
    it is caught.
  - False positives. An auditor that flags accurate documentation trains people to
    ignore it. Each check therefore also has a fixture of correct prose that must
    produce nothing — including the awkward cases: disclaimers, historical notes,
    hedged claims, placeholder filenames, and optional imports.

Run:  python3 -m pytest tests/test_claim_auditor.py -q
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import claim_auditor as ca  # noqa: E402

GOOD_FM = ("name: sample-skill\n"
           "description: Does a specific thing with files. Use when the user asks to "
           "do that specific thing or mentions the artifact by name.")

NET_SCRIPT = "import requests\ndef go():\n    requests.get('https://x')\n"
PURE_SCRIPT = (
    "import argparse\n"
    "def main():\n"
    "    p = argparse.ArgumentParser()\n"
    "    p.add_argument('--json', action='store_true')\n"
    "    p.parse_args()\n"
    "if __name__ == '__main__':\n    main()\n"
)
WRAPPER = (
    "import subprocess, sys\n"
    "from pathlib import Path\n"
    "def main():\n"
    "    ai = Path(__file__).parent / 'online.py'\n"
    "    subprocess.run([sys.executable, str(ai)])\n"
)


def build(tmp: Path, body: str, files: dict | None = None,
          frontmatter: str = GOOD_FM, readme: str | None = None) -> Path:
    root = tmp / "sample-skill"
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


class AuditorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def codes(self, root: Path) -> set:
        return {f.code for f in ca.audit(root).findings}

    def contradictions(self, root: Path) -> list:
        return ca.audit(root).contradictions


class TestReachClaims(AuditorTestCase):
    """The check that would have caught the real defect this tool was built for."""

    def test_transitive_network_through_a_wrapper_is_caught(self):
        root = build(
            self.tmp,
            "# T\n\n`scripts/wrapper.py` runs offline on the standard library.\n",
            {"scripts/wrapper.py": WRAPPER, "scripts/online.py": NET_SCRIPT},
        )
        found = self.contradictions(root)
        self.assertTrue(any(f.code == "REACH_CLAIM_FALSE" for f in found), found)
        self.assertTrue(any("transitively" in f.evidence for f in found),
                        [f.evidence for f in found])

    def test_direct_network_import_is_caught(self):
        root = build(self.tmp,
                     "# T\n\n`scripts/net.py` runs offline.\n",
                     {"scripts/net.py": NET_SCRIPT})
        self.assertIn("REACH_CLAIM_FALSE", self.codes(root))

    def test_genuinely_offline_script_is_not_flagged(self):
        root = build(self.tmp,
                     "# T\n\n`scripts/pure.py` runs offline on the standard library.\n",
                     {"scripts/pure.py": PURE_SCRIPT})
        self.assertNotIn("REACH_CLAIM_FALSE", self.codes(root))

    def test_a_denial_is_not_a_claim(self):
        """The exact sentence that documents the defect must not be a finding."""
        root = build(
            self.tmp,
            "# T\n\n`scripts/wrapper.py` is not an offline alternative: it runs the "
            "online one.\n",
            {"scripts/wrapper.py": WRAPPER, "scripts/online.py": NET_SCRIPT},
        )
        self.assertNotIn("REACH_CLAIM_FALSE", self.codes(root))

    def test_historical_note_is_not_a_claim(self):
        root = build(
            self.tmp,
            "# T\n\nEarlier revisions described `scripts/wrapper.py` as the offline "
            "path.\n",
            {"scripts/wrapper.py": WRAPPER, "scripts/online.py": NET_SCRIPT},
        )
        self.assertNotIn("REACH_CLAIM_FALSE", self.codes(root))

    def test_hedged_claim_treats_named_scripts_as_exceptions(self):
        """'all offline except X' says nothing about X — and must not be inverted."""
        root = build(
            self.tmp,
            "# T\n\nEvery script runs offline on the standard library, with one "
            "exception: `scripts/net.py`.\n",
            {"scripts/net.py": NET_SCRIPT, "scripts/pure.py": PURE_SCRIPT},
        )
        self.assertNotIn("REACH_CLAIM_FALSE", self.codes(root))

    def test_hedged_claim_still_catches_an_unlisted_offender(self):
        root = build(
            self.tmp,
            "# T\n\nEvery script runs offline, with one exception: `scripts/net.py`.\n",
            {"scripts/net.py": NET_SCRIPT, "scripts/other.py": NET_SCRIPT},
        )
        found = [f for f in self.contradictions(root) if f.code == "REACH_CLAIM_FALSE"]
        self.assertTrue(any("other.py" in f.evidence for f in found), found)
        self.assertFalse(any("net.py" in f.evidence and "other" not in f.evidence
                             for f in found), found)

    def test_hedge_naming_nothing_is_unverified_not_a_contradiction(self):
        root = build(self.tmp,
                     "# T\n\nAll scripts run offline, except two.\n",
                     {"scripts/net.py": NET_SCRIPT})
        result = ca.audit(root)
        self.assertIn("REACH_CLAIM_HEDGED", {f.code for f in result.findings})
        self.assertEqual(result.contradictions, [])

    def test_optional_import_is_not_a_dependency(self):
        """try/except ImportError with a fallback means zero *required* dependencies."""
        guarded = (
            "try:\n    import yaml\nexcept ImportError:\n    yaml = None\n"
            + PURE_SCRIPT
        )
        root = build(self.tmp,
                     "# T\n\nEvery script has zero runtime dependencies.\n",
                     {"scripts/g.py": guarded})
        self.assertNotIn("REACH_CLAIM_FALSE", self.codes(root))

    def test_unqualified_prose_is_not_treated_as_a_universal_claim(self):
        root = build(self.tmp,
                     "# T\n\nThe report explains offline alternatives in general.\n",
                     {"scripts/net.py": NET_SCRIPT})
        self.assertNotIn("REACH_CLAIM_FALSE", self.codes(root))


class TestCommandClaims(AuditorTestCase):
    def test_unknown_flag_is_caught(self):
        root = build(self.tmp,
                     "# T\n\n```bash\npython3 scripts/pure.py --nope\n```\n",
                     {"scripts/pure.py": PURE_SCRIPT})
        self.assertIn("COMMAND_FLAG_UNKNOWN", self.codes(root))

    def test_real_flag_is_accepted(self):
        root = build(self.tmp,
                     "# T\n\n```bash\npython3 scripts/pure.py --json\n```\n",
                     {"scripts/pure.py": PURE_SCRIPT})
        self.assertNotIn("COMMAND_FLAG_UNKNOWN", self.codes(root))

    def test_missing_script_is_caught(self):
        root = build(self.tmp, "# T\n\n```bash\npython3 scripts/ghost.py\n```\n")
        self.assertIn("COMMAND_SCRIPT_MISSING", self.codes(root))

    def test_bare_filename_that_lives_elsewhere_is_a_path_error(self):
        root = build(self.tmp,
                     "# T\n\n```bash\npython3 pure.py --json\n```\n",
                     {"scripts/pure.py": PURE_SCRIPT})
        codes = self.codes(root)
        self.assertIn("COMMAND_PATH_WRONG", codes)
        self.assertNotIn("COMMAND_SCRIPT_MISSING", codes)

    def test_placeholder_filenames_are_ignored(self):
        root = build(self.tmp,
                     "# T\n\n```bash\npython3 script.py --whatever\n```\n")
        self.assertEqual(self.contradictions(root), [])

    def test_absolute_path_is_ignored(self):
        root = build(self.tmp,
                     "# T\n\n```bash\npython3 /tmp/checkout/scripts/pure.py --x\n```\n",
                     {"scripts/pure.py": PURE_SCRIPT})
        self.assertEqual(self.contradictions(root), [])

    def test_ignore_directive_skips_a_block(self):
        body = ("# T\n\n<!-- claim-audit: ignore-next-block -->\n\n"
                "```bash\npython3 someone_elses_tool.py --flag\n```\n")
        root = build(self.tmp, body)
        self.assertEqual(self.contradictions(root), [])

    def test_ignore_directive_does_not_leak_past_its_block(self):
        body = ("# T\n\n<!-- claim-audit: ignore-next-block -->\n\n"
                "```bash\npython3 someone_elses_tool.py\n```\n\n"
                "```bash\npython3 scripts/ghost.py\n```\n")
        root = build(self.tmp, body)
        self.assertIn("COMMAND_SCRIPT_MISSING", self.codes(root))


class TestPathAndCountClaims(AuditorTestCase):
    def test_missing_path_in_skill_md_is_caught(self):
        root = build(self.tmp, "# T\n\nSee `references/ghost.md` for detail.\n")
        self.assertIn("PATH_NOT_FOUND", self.codes(root))

    def test_stale_path_reports_where_the_file_actually_is(self):
        root = build(self.tmp, "# T\n\nRun `evaluation/run.py`.\n",
                     {"scripts/evaluation/run.py": PURE_SCRIPT})
        found = [f for f in self.contradictions(root) if f.code == "PATH_STALE"]
        self.assertTrue(found)
        self.assertIn("scripts/evaluation/run.py", found[0].evidence)

    def test_dotted_directory_path_is_resolved(self):
        """`.github/workflows/ci.yml` must not be mangled into `github/...`."""
        root = build(self.tmp, "# T\n\nCI lives in `.github/workflows/ci.yml`.\n",
                     {".github/workflows/ci.yml": "name: CI\n"})
        self.assertEqual(self.contradictions(root), [])

    def test_doi_is_not_treated_as_a_path(self):
        root = build(self.tmp, "# T\n\nSee `10.48550/arXiv.2510.16234` for the paper.\n")
        self.assertEqual(self.contradictions(root), [])

    def test_example_paths_in_guides_are_not_package_claims(self):
        root = build(self.tmp, "# T\n\nSee [g](guides/a.md).\n",
                     {"guides/a.md": "Write your log to `researcher/claims/index.jsonl`.\n"})
        self.assertNotIn("PATH_NOT_FOUND", self.codes(root))

    def test_inventory_count_mismatch_is_caught(self):
        root = build(self.tmp, "# T\n\nThis skill ships 5 scripts.\n",
                     {"scripts/a.py": PURE_SCRIPT, "scripts/b.py": PURE_SCRIPT})
        self.assertIn("COUNT_MISMATCH", self.codes(root))

    def test_correct_inventory_count_passes(self):
        root = build(self.tmp, "# T\n\nThis skill ships 2 scripts.\n",
                     {"scripts/a.py": PURE_SCRIPT, "scripts/b.py": PURE_SCRIPT})
        self.assertNotIn("COUNT_MISMATCH", self.codes(root))

    def test_non_inventory_number_is_not_a_count_claim(self):
        """A tier table saying '2-3 scripts (500-800 LOC)' is not an inventory."""
        root = build(self.tmp, "# T\n\n| STANDARD | 2-3 scripts | 300-500 LOC |\n",
                     {"scripts/a.py": PURE_SCRIPT})
        self.assertNotIn("COUNT_MISMATCH", self.codes(root))


class TestCapabilityClaims(AuditorTestCase):
    """`--help` support is only real if something actually builds it."""

    HANDROLLED = (
        "import sys\n"
        "USAGE = 'usage: t.py FILE'\n"
        "def main():\n"
        "    if any(a in ('-h', '--help') for a in sys.argv[1:]):\n"
        "        print(USAGE); sys.exit(0)\n"
        "if __name__ == '__main__':\n    main()\n"
    )
    NO_HELP = "import sys\nprint(open(sys.argv[1]).read())\n"

    def test_claim_is_false_when_a_script_has_no_help(self):
        root = build(self.tmp, "# T\n\nEvery script exposes `--help`.\n",
                     {"scripts/a.py": PURE_SCRIPT, "scripts/b.py": self.NO_HELP})
        found = [f for f in self.contradictions(root)
                 if f.code == "CAPABILITY_CLAIM_FALSE"]
        self.assertTrue(found)
        self.assertIn("scripts/b.py", found[0].evidence)

    def test_hand_rolled_help_counts_as_support(self):
        """Not every CLI uses argparse. One that checks sys.argv itself still works."""
        root = build(self.tmp, "# T\n\nEvery script exposes `--help`.\n",
                     {"scripts/a.py": PURE_SCRIPT, "scripts/b.py": self.HANDROLLED})
        self.assertNotIn("CAPABILITY_CLAIM_FALSE", self.codes(root))

    def test_backticked_flag_is_still_matched(self):
        """`\\b--help` never matches after a backtick; the claim must still be read."""
        root = build(self.tmp, "# T\n\nEvery script exposes `--help`.\n",
                     {"scripts/b.py": self.NO_HELP})
        self.assertIn("CAPABILITY_CLAIM_FALSE", self.codes(root))

    def test_assets_fixtures_are_not_package_clis(self):
        """A demo skill under assets/ is sample data, not one of this skill's tools."""
        root = build(self.tmp, "# T\n\nEvery script supports `--json`.\n",
                     {"scripts/a.py": PURE_SCRIPT,
                      "assets/sample-skill/scripts/demo.py": self.NO_HELP})
        self.assertNotIn("CAPABILITY_CLAIM_FALSE", self.codes(root))

    def test_shared_module_directory_is_not_a_cli(self):
        root = build(self.tmp, "# T\n\nEvery script exposes `--help`.\n",
                     {"scripts/a.py": PURE_SCRIPT,
                      "scripts/_shared/safe_io.py": "def read(p):\n    return p\n"})
        self.assertNotIn("CAPABILITY_CLAIM_FALSE", self.codes(root))

    def test_hedged_capability_claim_excludes_named_scripts(self):
        root = build(self.tmp,
                     "# T\n\nEvery script exposes `--help`, except `scripts/b.py`.\n",
                     {"scripts/a.py": PURE_SCRIPT, "scripts/b.py": self.NO_HELP})
        self.assertNotIn("CAPABILITY_CLAIM_FALSE", self.codes(root))


class TestStdlibDetection(unittest.TestCase):
    """Pins the 3.9 regression: an empty stdlib set makes every import third-party."""

    def test_common_stdlib_modules_are_recognised(self):
        for mod in ("argparse", "json", "os", "sys", "re", "pathlib", "subprocess"):
            self.assertIn(mod, ca._STDLIB, mod)

    def test_fallback_path_finds_the_stdlib_without_sys_attribute(self):
        saved = getattr(sys, "stdlib_module_names", None)
        try:
            if saved is not None:
                del sys.stdlib_module_names
            names = ca._stdlib_names()
        finally:
            if saved is not None:
                sys.stdlib_module_names = saved
        for mod in ("argparse", "json", "pathlib"):
            self.assertIn(mod, names, f"{mod} missing from the pre-3.10 fallback")

    def test_third_party_still_reads_as_third_party(self):
        self.assertTrue(ca.is_third_party("requests", set()))
        self.assertFalse(ca.is_third_party("argparse", set()))


class TestSentenceSplitting(unittest.TestCase):
    def test_filenames_do_not_end_sentences(self):
        got = list(ca.sentences("Run generate_schematic.py now. Then stop."))
        self.assertEqual(got, ["Run generate_schematic.py now.", "Then stop."])

    def test_version_numbers_do_not_end_sentences(self):
        got = list(ca.sentences("Needs Python 3.10 or newer."))
        self.assertEqual(got, ["Needs Python 3.10 or newer."])


class TestExitContract(AuditorTestCase):
    def test_clean_skill_exits_zero(self):
        root = build(self.tmp, "# T\n\nNothing controversial here.\n")
        self.assertEqual(ca.main([str(root)]), 0)

    def test_contradiction_exits_two(self):
        root = build(self.tmp, "# T\n\nSee `references/ghost.md`.\n")
        self.assertEqual(ca.main([str(root)]), 2)

    def test_strict_promotes_unverified_to_failure(self):
        root = build(self.tmp, "# T\n\nAll scripts run offline, except two.\n",
                     {"scripts/net.py": NET_SCRIPT})
        self.assertEqual(ca.main([str(root)]), 0)
        self.assertEqual(ca.main([str(root), "--strict"]), 2)

    def test_missing_directory_exits_one(self):
        self.assertEqual(ca.main([str(self.tmp / "nope")]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
