import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import build
from cv_config import (
    ConfigError, PERSON_FIELDS, PROFILES, SECTIONS, fetch_public_repos,
    load_config, merge_repositories, prepare_profile, save_config, sync_github,
)


def fixture():
    profiles = {}
    for profile in PROFILES:
        profiles[profile] = {
            "sections": {section: True for section in SECTIONS},
            "project_order": ["example"],
            "headline": "ML engineering", "summary": "An independent profile summary.",
            "links": [{"enabled": True, "label": "Website", "url": "https://example.org"}],
            "skills": [{"enabled": True, "name": "Languages", "text": "Python"}],
            "highlights": [{"enabled": True, "text": "A specific achievement"}],
            "achievements": [], "leadership": [], "education": [],
        }
    return {
        "schema_version": 1,
        "github": {"username": "example"},
        "person": {field: "Example" if field == "name" else "" for field in PERSON_FIELDS},
        "profiles": profiles,
        "projects": {"example": {
            "enabled": {"research": True, "yc": True},
            "github_repo": "example/project", "title": "Visible project",
            "url": "https://github.com/example/project", "dates": "",
            "bullets": ["A result.", "An action.", "The context."],
            "overrides": {"yc": {"title": "YC project"}},
        }},
    }


def repository(repo_id=1, name="project", **extra):
    return {
        "id": repo_id, "name": name, "full_name": f"example/{name}",
        "html_url": f"https://github.com/example/{name}", "description": "API description",
        "language": "Python", "stargazers_count": 3, "forks_count": 1, **extra,
    }


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = fixture()

    def test_profile_switches_are_independent(self):
        self.config["projects"]["example"]["enabled"]["research"] = False
        self.assertEqual(prepare_profile(self.config, "research")["projects"], [])
        self.assertEqual(prepare_profile(self.config, "yc")["projects"][0]["title"], "YC project")

    def test_true_false_true_round_trip(self):
        expected = prepare_profile(self.config, "yc")
        self.config["projects"]["example"]["enabled"]["yc"] = False
        self.assertNotIn("YC project", build.render_tex(prepare_profile(self.config, "yc"), "yc"))
        self.config["projects"]["example"]["enabled"]["yc"] = True
        self.assertEqual(prepare_profile(self.config, "yc"), expected)

    def test_quoted_false_and_numeric_flags_are_errors(self):
        for value in ("false", "true", 0, 1, None):
            with self.subTest(value=value):
                self.config["projects"]["example"]["enabled"]["yc"] = value
                with self.assertRaisesRegex(ConfigError, "true or false"):
                    prepare_profile(self.config, "yc")

    def test_item_and_section_toggles_remove_empty_headings(self):
        profile = self.config["profiles"]["yc"]
        profile["skills"][0]["enabled"] = False
        profile["highlights"][0]["enabled"] = False
        profile["sections"]["projects"] = False
        data = prepare_profile(self.config, "yc")
        tex = build.render_tex(data, "yc")
        for heading in ("Technical Skills", "Selected Engineering Projects",
                        "Recognition \\& Leadership", r"\section{Education}"):
            self.assertNotIn(heading, tex)
        self.assertEqual(build.expected_lines(data, "yc"), 0)

    def test_section_switch_overrides_enabled_items(self):
        self.config["profiles"]["research"]["sections"]["links"] = False
        self.assertEqual(prepare_profile(self.config, "research")["links"], [])

    def test_newly_enabled_unordered_project_is_appended(self):
        self.config["projects"]["second"] = copy.deepcopy(self.config["projects"]["example"])
        actual = prepare_profile(self.config, "yc")["projects"]
        self.assertEqual([item["id"] for item in actual], ["example", "second"])

    def test_unknown_and_duplicate_order_entries_fail(self):
        for order in (["missing"], ["example", "example"]):
            self.config["profiles"]["yc"]["project_order"] = order
            with self.assertRaisesRegex(ConfigError, "duplicate or unknown"):
                prepare_profile(self.config, "yc")

    def test_incomplete_drafts_only_block_when_selected(self):
        project = self.config["projects"]["example"]
        project["bullets"] = []
        project["enabled"]["yc"] = False
        self.assertEqual(prepare_profile(self.config, "yc")["projects"], [])
        project["enabled"]["yc"] = True
        with self.assertRaisesRegex(ConfigError, "three reviewed RAC bullets"):
            prepare_profile(self.config, "yc")

    def test_common_bullets_and_profile_overrides(self):
        self.config["projects"]["example"]["bullets"][0] = "Updated result."
        self.assertEqual(prepare_profile(self.config, "research")["projects"][0]["bullets"][0], "Updated result.")
        self.assertEqual(prepare_profile(self.config, "yc")["projects"][0]["bullets"][0], "Updated result.")
        self.assertNotIn("advisor", self.config["projects"]["example"])
        self.assertEqual(prepare_profile(self.config, "research")["projects"][0]["advisor"], "")

    def test_duplicate_yaml_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            path.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Duplicate"):
                load_config(path)

    def test_metadata_refresh_preserves_editorial_and_flags(self):
        original = copy.deepcopy(self.config)
        result, added = merge_repositories(self.config, [repository()], "now")
        self.assertEqual(self.config, original)
        self.assertEqual(added, [])
        project = result["projects"]["example"]
        for key in ("bullets", "title", "enabled", "overrides"):
            self.assertEqual(project[key], original["projects"]["example"][key])
        self.assertEqual(project["github"]["stargazers_count"], 3)

    def test_new_repositories_default_off_and_are_idempotent(self):
        result, added = merge_repositories(self.config, [repository(2, "new-repo", fork=True)], "now")
        self.assertEqual(added, ["new-repo"])
        new = result["projects"]["new-repo"]
        self.assertEqual(new["enabled"], {"research": False, "yc": False})
        self.assertEqual(new["bullets"], [])
        again, added = merge_repositories(result, [repository(2, "new-repo", fork=True)], "later")
        self.assertEqual(added, [])
        self.assertEqual(len(again["projects"]), 2)

    def test_renamed_repo_matches_id_and_updates_canonical_url(self):
        config, _ = merge_repositories(self.config, [repository()], "before")
        result, added = merge_repositories(config, [repository(1, "renamed")], "after")
        self.assertEqual(added, [])
        self.assertEqual(result["projects"]["example"]["url"], "https://github.com/example/renamed")
        self.assertEqual(result["projects"]["example"]["title"], "Visible project")

    def test_custom_project_url_and_missing_repo_are_preserved(self):
        self.config["projects"]["example"]["url"] = "https://example.org/demo"
        result, _ = merge_repositories(self.config, [repository()], "now")
        self.assertEqual(result["projects"]["example"]["url"], "https://example.org/demo")
        result, _ = merge_repositories(result, [], "later")
        self.assertIn("example", result["projects"])

    def test_sync_failure_leaves_file_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            save_config(path, self.config)
            before = path.read_bytes()
            with patch("cv_config.urlopen", side_effect=URLError("offline")):
                with self.assertRaisesRegex(ConfigError, "not changed"):
                    sync_github(path, self.config)
            self.assertEqual(path.read_bytes(), before)

    def test_github_pagination(self):
        batches = [[repository(i, f"repo-{i}") for i in range(100)], [repository(100, "last")]]
        responses = [io.BytesIO(json.dumps(batch).encode()) for batch in batches]
        with patch("cv_config.urlopen", side_effect=responses) as mocked:
            result = fetch_public_repos("example")
        self.assertEqual(len(result), 101)
        self.assertIn("page=2", mocked.call_args_list[1].args[0].full_url)

    def test_invalid_response_does_not_mutate_input(self):
        before = copy.deepcopy(self.config)
        with self.assertRaises(ConfigError):
            merge_repositories(self.config, [repository(), {"id": 5}], "now")
        self.assertEqual(self.config, before)

    def test_config_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            save_config(path, self.config)
            self.assertEqual(load_config(path), self.config)

    def test_fit_checks_reject_missing_wrapped_and_short_lines(self):
        for fit, expected in (("", 1), ("x:99pt:100pt:2", 1),
                              ("x:50pt:100pt:1", 1), ("x:1..2pt:100pt:1", 1)):
            with self.subTest(fit=fit), self.assertRaises(ConfigError):
                build.check_lines(fit, expected)
        build.check_lines("x:99pt:100pt:1", 1)
        build.check_lines("", 0)

    def test_bad_build_preserves_published_pdf_and_tex(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "cv.pdf").write_bytes(b"previous pdf")
            (root / "cv.tex").write_text("previous source", encoding="utf-8")

            def compiler(*args, **kwargs):
                (root / "build" / "cv.log").write_text("Output written on cv.pdf (2 pages).", encoding="latin-1")
                return type("Result", (), {"returncode": 0})()

            with patch.object(build, "ROOT", root), patch.object(build, "render_tex", return_value="new source"), \
                    patch("build.shutil.which", return_value="pdflatex"), patch("build.subprocess.run", side_effect=compiler):
                with self.assertRaisesRegex(ConfigError, "one page"):
                    build.build_profile(self.config, "research")
            self.assertEqual((root / "cv.pdf").read_bytes(), b"previous pdf")
            self.assertEqual((root / "cv.tex").read_text(encoding="utf-8"), "previous source")

    def test_unicode_and_latex_escaping(self):
        self.assertEqual(build.esc("50% & 150\u00b0"), r"50\% \& 150\textdegree{}")
        self.assertIn(r"\textbf{result}", build.fmt("A **result**"))


if __name__ == "__main__":
    unittest.main()
