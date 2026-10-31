import copy
import tempfile
import unittest
from pathlib import Path

from cv_config import ConfigError, load_config, save_config
from readme_draft import candidates, draft, readme_sentences
from test_cv_config import fixture

README = """# Example project

![badge](https://img.shields.io/x.svg)

A **jet classifier** for collider data. Reached 84.8% accuracy and 0.985 AUC on one million test jets.

## How it works

- Built a gated attention block in PyTorch that scales query and key channels.
- Uses ROOT files and caches per-particle arrays on disk.

The goal is to help students study particle physics with modern machine learning tools.

```python
print("this code sentence must never be extracted as a bullet")
```

| Metric | Value |
|---|---|
| Accuracy table rows are ignored too | 0.85 |
"""


def scripted(answers):
    queue = list(answers)

    def ask(prompt):
        if not queue:
            raise AssertionError(f"Unexpected prompt: {prompt}")
        return queue.pop(0)
    return ask


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.config = fixture()
        self.config["projects"]["example"]["bullets"] = []
        self.config["projects"]["example"]["enabled"] = {"research": False, "yc": False}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yaml"
        save_config(self.path, self.config)
        self.output = []

    def run_draft(self, answers, ids=("example",), fetch=lambda repo: README):
        return draft(self.path, self.config, list(ids), scripted(answers), self.output.append, fetch)

    def test_sentences_skip_code_tables_images_and_headings(self):
        sentences = readme_sentences(README)
        joined = " ".join(sentences)
        self.assertIn("Reached 84.8% accuracy and 0.985 AUC on one million test jets.", sentences)
        self.assertNotIn("print", joined)
        self.assertNotIn("table rows", joined)
        self.assertNotIn("badge", joined)
        self.assertNotIn("How it works", joined)

    def test_candidates_rank_by_slot(self):
        ranked = candidates(readme_sentences(README))
        self.assertIn("84.8%", ranked["result"][0])
        self.assertTrue(ranked["action"][0].startswith("Built"))
        self.assertIn("goal", ranked["context"][0].lower())

    def test_approved_bullets_are_saved_and_project_stays_disabled(self):
        result = self.run_draft(["1", "", "1", "Built a **gated attention** block in PyTorch.", "1", "", "y"])
        saved = load_config(self.path)["projects"]["example"]
        self.assertEqual(saved["bullets"][0], "Reached 84.8% accuracy and 0.985 AUC on one million test jets.")
        self.assertEqual(saved["bullets"][1], "Built a **gated attention** block in PyTorch.")
        self.assertEqual(saved["enabled"], {"research": False, "yc": False})
        self.assertIn("approved", saved["notes"])
        self.assertEqual(result["projects"]["example"]["bullets"], saved["bullets"])

    def test_declined_or_skipped_draft_leaves_file_unchanged(self):
        before = self.path.read_bytes()
        self.run_draft(["1", "", "1", "", "1", "", "n"])
        self.assertEqual(self.path.read_bytes(), before)
        self.run_draft(["s"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_custom_text_and_keep_existing(self):
        self.config["projects"]["example"]["bullets"] = ["Old result.", "Old action.", "Old context."]
        save_config(self.path, self.config)
        self.run_draft(["k", "e", "My own action line.", "k", "y"])
        self.assertEqual(load_config(self.path)["projects"]["example"]["bullets"],
                         ["Old result.", "My own action line.", "Old context."])

    def test_invalid_choice_reprompts(self):
        self.run_draft(["9", "x", "1", "", "1", "", "1", "", "y"])
        self.assertTrue(any("Please enter" in line for line in self.output))

    def test_fetch_failure_and_missing_repo_do_not_write(self):
        before = self.path.read_bytes()

        def failing(repo):
            raise ConfigError("no README")
        self.run_draft([], fetch=failing)
        self.assertEqual(self.path.read_bytes(), before)
        self.config["projects"]["example"]["github_repo"] = ""
        self.run_draft([])
        self.assertEqual(self.path.read_bytes(), before)

    def test_unknown_project_is_an_error(self):
        with self.assertRaises(ConfigError):
            self.run_draft([], ids=("missing",))

    def test_default_targets_only_repos_without_bullets(self):
        complete = copy.deepcopy(self.config["projects"]["example"])
        complete["bullets"] = ["a.", "b.", "c."]
        complete["github_repo"] = "example/done"
        self.config["projects"]["done"] = complete
        seen = []
        draft(self.path, self.config, [], scripted(["s"]), self.output.append,
              lambda repo: seen.append(repo) or README)
        self.assertEqual(seen, ["example/project"])

    def test_input_config_object_is_not_mutated(self):
        before = copy.deepcopy(self.config)
        self.run_draft(["1", "", "1", "", "1", "", "y"])
        self.assertEqual(self.config, before)


if __name__ == "__main__":
    unittest.main()
