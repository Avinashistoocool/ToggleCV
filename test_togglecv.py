import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

import togglecv as tc
from cv_config import ConfigError

README = """# Jet Tagger

A transformer for collider jets. Reached 84.8% accuracy and 0.985 AUC on one million test jets.

- Built a gated attention block in PyTorch that scales query and key channels.

The goal is to help students study particle physics with machine learning.
"""

JAKE = r"""\documentclass{article}
\usepackage[hidelinks]{hyperref}
\newcommand{\resumeItem}[1]{\item #1}
\newcommand{\resumeProjectHeading}[2]{\item #1 \hfill #2}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}}
\begin{document}
% \section{Old Projects} commented out, must be ignored
\section{Education}
Some school.
\section{Projects}
    \resumeSubHeadingListStart
      \resumeProjectHeading{\textbf{Old Project}}{2020}
      \resumeItemListStart
        \resumeItem{Old bullet.}
      \resumeItemListEnd
    \resumeSubHeadingListEnd

%-----------SKILLS-----------
\section{Technical Skills}
Python.
\end{document}
"""

PLAIN = r"""\documentclass{article}
\begin{document}
\section*{Experience}
Job.
\subsection*{Selected Projects}
\begin{itemize}\item Old.\end{itemize}
\subsection*{Awards}
Prize.
\end{document}
"""


def project(repo="me/jet-tagger", title="Jet Tagger", enabled=True, reviewed=True):
    return {"repo": repo, "enabled": enabled, "reviewed": reviewed, "title": title,
            "url": f"https://github.com/{repo}", "dates": "2026", "tech": "Python",
            "rac": {"result": "Reached **84.8%** accuracy & 0.985 AUC.",
                    "action": "Built a gated attention block in PyTorch.",
                    "context": "Research project on 10M jets."}}


def repo(name, number, **extra):
    return {"id": number, "name": name, "full_name": f"me/{name}", "html_url": f"https://github.com/me/{name}",
            "description": "A tool.", "language": "Python", "stargazers_count": 1, "forks_count": 0,
            "fork": False, "archived": False, "pushed_at": f"2026-10-{10 + number:02d}T00:00:00Z", **extra}


class ToggleCVTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.projects = self.dir / "projects.yaml"
        self.out = []

    def write(self, *projects, **settings):
        data = {"github_user": "me", "style": "auto", "show_language": True, "projects": list(projects), **settings}
        tc.save_projects(self.projects, data)

    def cv(self, text, name="cv.tex"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    # ---- GitHub sync
    def test_init_creates_disabled_projects_with_readme_suggestions(self):
        repos = [repo("jet-tagger", 1), repo("old", 2), repo("me", 3), repo("forked", 4, fork=True)]
        tc.sync(self.projects, "me", create=True, fetch_repos=lambda user: repos,
                fetch=lambda name: README, say=self.out.append)
        data = tc.load_projects(self.projects)
        names = [p["repo"] for p in data["projects"]]
        self.assertEqual(names, ["me/old", "me/jet-tagger"])
        first = data["projects"][1]
        self.assertFalse(first["enabled"])
        self.assertFalse(first["reviewed"])
        self.assertIn("84.8%", first["rac"]["result"])
        self.assertTrue(first["rac"]["action"].startswith("Built"))
        self.assertIn("goal", first["rac"]["context"].lower())
        self.assertTrue(self.projects.read_text().startswith("# ToggleCV"))

    def test_init_refuses_to_overwrite(self):
        self.write(project())
        with self.assertRaises(ConfigError):
            tc.sync(self.projects, "me", create=True, fetch_repos=lambda u: [], say=self.out.append)

    def test_refresh_keeps_user_edits_and_marks_missing(self):
        mine = project(repo="me/jet-tagger")
        mine["title"] = "My Custom Title"
        mine["github"] = {"id": 1, "html_url": "https://github.com/me/jet-tagger"}
        gone = project(repo="me/deleted", title="Deleted")
        self.write(mine, gone)
        tc.sync(self.projects, fetch_repos=lambda u: [repo("jet-tagger-v2", 1), repo("new", 9)],
                fetch=lambda name: README, say=self.out.append)
        data = tc.load_projects(self.projects)
        kept = data["projects"][0]
        self.assertEqual(kept["title"], "My Custom Title")
        self.assertEqual(kept["rac"], mine["rac"])
        self.assertTrue(kept["enabled"])
        self.assertEqual(kept["repo"], "me/jet-tagger-v2")
        self.assertEqual(kept["url"], "https://github.com/me/jet-tagger-v2")
        self.assertTrue(data["projects"][1]["github"]["missing"]) if "github" in data["projects"][1] else None
        self.assertEqual(data["projects"][2]["repo"], "me/new")
        self.assertFalse(data["projects"][2]["enabled"])

    def test_readme_failure_leaves_empty_bullets(self):
        def missing(name):
            raise ConfigError("no README")
        tc.sync(self.projects, "me", create=True, fetch_repos=lambda u: [repo("bare", 1, description="")],
                fetch=missing, say=self.out.append)
        rac = tc.load_projects(self.projects)["projects"][0]["rac"]
        self.assertEqual(rac, {"result": "", "action": "", "context": ""})

    def test_github_error_leaves_file_unchanged(self):
        self.write(project())
        before = self.projects.read_bytes()

        def failing(user):
            raise ConfigError("rate limited")
        with self.assertRaises(ConfigError):
            tc.sync(self.projects, fetch_repos=failing, say=self.out.append)
        self.assertEqual(self.projects.read_bytes(), before)

    # ---- validation
    def test_validation_rejects_bad_files(self):
        bad = [
            {"github_user": "me", "projects": [{**project(), "enabled": "true"}]},
            {"github_user": "me", "projects": [{**project(), "rac": {"result": "a"}}]},
            {"github_user": "me", "projects": [project(), project()]},
            {"github_user": "me", "style": "fancy", "projects": []},
            {"github_user": "me", "style": "custom", "projects": []},
            {"projects": []},
        ]
        for data in bad:
            with self.subTest(data=str(data)[:60]), self.assertRaises(ConfigError):
                tc.validate(copy.deepcopy(data))

    # ---- LaTeX section detection and replacement
    def test_jake_template_projects_section_is_replaced(self):
        self.write(project(), project(repo="me/off", title="Hidden", enabled=False))
        target = tc.apply(self.cv(JAKE), self.projects, say=self.out.append)
        text = target.read_text()
        self.assertNotIn("Old bullet", text)
        self.assertNotIn("Hidden", text)
        self.assertIn(r"\resumeProjectHeading", text)
        self.assertIn(r"\href{https://github.com/me/jet-tagger}{Jet Tagger}", text)
        self.assertIn(r"\resumeItem{Reached \textbf{84.8\%} accuracy \& 0.985 AUC.}", text)
        self.assertEqual(text.count(r"\resumeItem{"), 3)
        self.assertIn("Some school.", text)
        self.assertIn("%-----------SKILLS-----------\n\\section{Technical Skills}", text)
        self.assertIn("% \\section{Old Projects} commented out", text)
        self.assertEqual((self.dir / "cv.tex").read_text(), JAKE)

    def test_rerun_uses_markers_and_is_idempotent(self):
        self.write(project())
        first = tc.apply(self.cv(JAKE), self.projects, say=self.out.append).read_text()
        second_input = self.cv(first, "cv2.tex")
        second = tc.apply(second_input, self.projects, say=self.out.append).read_text()
        self.assertEqual(first, second)
        self.assertEqual(second.count(tc.BEGIN), 1)

    def test_plain_itemize_subsection_and_no_hyperref(self):
        self.write(project())
        text = tc.apply(self.cv(PLAIN), self.projects, say=self.out.append).read_text()
        self.assertIn(r"\subsection*{Selected Projects}", text)
        self.assertIn("\\begin{itemize}\n  \\item \\textbf{Jet Tagger} (Python) \\hfill 2026", text)
        self.assertNotIn(r"\href", text)
        self.assertIn(r"\subsection*{Awards}", text)
        self.assertNotIn("Old.", text)

    def test_custom_section_macro_is_detected(self):
        self.write(project())
        cv = PLAIN.replace(r"\section*{Experience}", r"\cvsection{Experience}").replace(
            r"\subsection*{Selected Projects}", r"\cvsection{Research \& Technical Projects}").replace(
            r"\subsection*{Awards}", r"\cvsection{Awards}")
        text = tc.apply(self.cv(cv), self.projects, say=self.out.append).read_text()
        self.assertNotIn("Old.", text)
        self.assertIn("Prize.", text)
        self.assertLess(text.index(tc.END), text.index(r"\cvsection{Awards}"))

    def test_unicode_readme_symbols_are_made_latex_safe(self):
        rendered = tc.tex("Used by H\u2192bb\u0304 jets \u00b7 10\u00d7 faster")
        self.assertEqual(rendered, r"Used by H$\rightarrow$bb jets \textperiodcentered{} 10$\times$ faster")

    def test_markers_take_priority_and_ambiguity_errors(self):
        self.write(project())
        marked = PLAIN.replace("Job.", f"Job.\n{tc.BEGIN}\nold\n{tc.END}")
        text = tc.apply(self.cv(marked), self.projects, say=self.out.append).read_text()
        self.assertIn("Old.", text)
        self.assertNotIn("\nold\n", text)
        two = PLAIN.replace("Experience", "Research Projects")
        with self.assertRaisesRegex(ConfigError, "Several"):
            tc.apply(self.cv(two), self.projects, say=self.out.append)
        none = PLAIN.replace("Selected Projects", "Work")
        with self.assertRaisesRegex(ConfigError, "TOGGLECV:BEGIN"):
            tc.apply(self.cv(none), self.projects, say=self.out.append)

    def test_unreviewed_and_incomplete_projects_are_blocked(self):
        self.write(project(reviewed=False))
        with self.assertRaisesRegex(ConfigError, "Not approved"):
            tc.apply(self.cv(JAKE), self.projects, say=self.out.append)
        tc.apply(self.cv(JAKE), self.projects, allow_unreviewed=True, say=self.out.append)
        empty = project()
        empty["rac"]["context"] = " "
        self.write(empty)
        with self.assertRaisesRegex(ConfigError, "three bullets"):
            tc.apply(self.cv(JAKE), self.projects, say=self.out.append)
        self.write(project(enabled=False))
        with self.assertRaisesRegex(ConfigError, "No project"):
            tc.apply(self.cv(JAKE), self.projects, say=self.out.append)

    def test_in_place_keeps_backup_and_crlf(self):
        self.write(project())
        path = self.dir / "cv.tex"
        path.write_bytes(JAKE.replace("\n", "\r\n").encode())
        tc.apply(path, self.projects, in_place=True, say=self.out.append)
        self.assertEqual((self.dir / "cv.tex.bak").read_bytes(), JAKE.replace("\n", "\r\n").encode())
        result = path.read_bytes()
        self.assertNotIn(b"Old bullet", result)
        self.assertNotIn(b"\r\r", result)
        self.assertEqual(result.count(b"\n"), result.count(b"\r\n"))
        tc.apply(path, self.projects, in_place=True, say=self.out.append)
        self.assertEqual(path.read_bytes(), result)
        self.assertEqual(len(list(self.dir.glob("cv.tex*.bak"))), 2)
        with self.assertRaisesRegex(ConfigError, "overwrite"):
            tc.apply(path, self.projects, out=str(path), say=self.out.append)

    def test_custom_style_template(self):
        self.write(project(), style="custom", custom={
            "before": "\\begin{enumerate}", "after": "\\end{enumerate}",
            "entry": "\\item[<<dates>>] <<title_link>> -- <<tech>>\n<<bullets>>",
            "bullet": "\\par <<bullet>>\n",
        })
        text = tc.apply(self.cv(JAKE), self.projects, say=self.out.append).read_text()
        self.assertIn(r"\item[2026] \href{https://github.com/me/jet-tagger}{Jet Tagger} -- Python", text)
        self.assertEqual(text.count("\\par "), 3)

    def test_review_saves_only_after_approval(self):
        self.write(project(reviewed=False))
        before = self.projects.read_bytes()
        answers = iter(["k", "k", "k", "n"])
        tc.review_projects(self.projects, [], ask=lambda p: next(answers), say=self.out.append,
                           fetch=lambda n: README)
        self.assertEqual(self.projects.read_bytes(), before)
        answers = iter(["1", "", "k", "e", "My context line.", "y"])
        tc.review_projects(self.projects, ["jet-tagger"], ask=lambda p: next(answers), say=self.out.append,
                           fetch=lambda n: README)
        saved = tc.load_projects(self.projects)["projects"][0]
        self.assertTrue(saved["reviewed"])
        self.assertIn("84.8%", saved["rac"]["result"])
        self.assertEqual(saved["rac"]["context"], "My context line.")

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex not installed")
    def test_generated_jake_cv_compiles(self):
        self.write(project(), project(repo="me/two", title="Second_Project #2"))
        target = tc.apply(self.cv(JAKE), self.projects, engine="pdflatex", say=self.out.append)
        self.assertTrue(target.with_suffix(".pdf").exists())


if __name__ == "__main__":
    unittest.main()
