# ToggleCV

**Your GitHub repos → a YAML file of on/off switches → the Projects section of your
own LaTeX CV.** Every project gets exactly three bullets in the
**Result / Action / Context (R-A-C)** structure, drafted from its README and only
used after you approve them.

## The R-A-C structure

| Bullet | Answers | Example |
|---|---|---|
| **Result** | What changed? Lead with a measured outcome. | Reached **91% test accuracy**, up from a 78% baseline. |
| **Action** | What did *you* build, and with what? | Trained a small CNN in PyTorch with augmentation and early stopping. |
| **Context** | Where, why, for whom, with whom? | Course project comparing baselines with deep models on a 6 GB GPU. |

Three lines per project keeps every entry the same size, puts the evidence first, and
makes it obvious when a project has no result worth stating.

## Use it with your own CV (`togglecv.py`)

```powershell
git clone https://github.com/Avinashistoocool/ToggleCV
cd ToggleCV
pip install -r requirements.txt

python togglecv.py init --user <your-github-username>   # 1. projects.yaml from your public repos
#                                                          2. edit projects.yaml: enabled: true on the ones you want
python togglecv.py review                               # 3. pick/edit/approve bullets from each README
python togglecv.py apply my_cv.tex --compile            # 4. writes my_cv.togglecv.tex (+ PDF check)
```

`projects.yaml` is the toggle file:

```yaml
github_user: your-github-username
style: auto            # auto | jake | itemize | custom
show_language: true
projects:
- repo: you/image-classifier
  enabled: true        # in the CV
  reviewed: true       # you approved the bullets
  title: Image Classifier
  url: https://github.com/you/image-classifier
  dates: Jan - Mar 2026
  tech: PyTorch
  rac:
    result: Reached **91% test accuracy** on a 10-class dataset, up from a 78% baseline.
    action: Trained a small CNN in PyTorch with augmentation and early stopping.
    context: Course project comparing classical and deep models on a 6 GB GPU.
- repo: you/old-experiment
  enabled: false       # kept, but left out of the CV
  ...
```

List order is CV order. See `projects.example.yaml` for a complete file.

| Command | What it does |
|---|---|
| `togglecv.py init --user NAME` | Create `projects.yaml`. Every repo starts **off** and **unreviewed**, with one README sentence suggested per slot. Forks and your profile README repo are skipped (`--include-forks` to keep forks). |
| `togglecv.py refresh` | Add new repos (off), update stars/language/URLs, follow renames. Never touches your switches, titles, dates or bullets. Deleted repos are kept and marked `missing`. |
| `togglecv.py list` | Show `on`/`ok` status for every project. |
| `togglecv.py review [NAME ...]` | For each enabled, unreviewed project (or the ones named): choose a README sentence per slot, edit it, write your own, or keep the current one. Saves and sets `reviewed: true` only when you answer `y`. |
| `togglecv.py apply CV.tex` | Replace the Projects section with your enabled projects. Writes `CV.togglecv.tex`; `--out FILE` or `--in-place` (keeps a `.bak`). `--compile [ENGINE]` checks it builds. |

### How `apply` finds your Projects section

1. If the file has a `% TOGGLECV:BEGIN` line and a `% TOGGLECV:END` line, only the text
   between them is replaced. `apply` adds these markers the first time, so re-running
   is safe and gives the same result.
2. Otherwise it looks for **one** heading containing "Project": `\section`,
   `\section*`, `\subsection`, or a custom macro such as `\cvsection{...}`. Everything
   after that heading up to the next heading of the same or higher level is replaced.
   Headings inside `%` comments are ignored.
3. If no heading or several headings match, it stops and tells you to paste the two
   marker lines where your projects belong.

Your original file is never modified unless you pass `--in-place`.

### Matching your CV's look

- `style: auto` uses Jake's Resume macros (`\resumeProjectHeading`, `\resumeItem`, …)
  when your file defines them, otherwise a nested `itemize`.
- `style: custom` lets you describe one entry with placeholders:

```yaml
style: custom
custom:
  before: \begin{itemize}
  entry: "\\item \\textbf{<<title_link>>} \\hfill <<dates>>\n\\begin{itemize}\n<<bullets>>\\end{itemize}"
  bullet: "\\item <<bullet>>\n"
  after: \end{itemize}
```

Placeholders: `<<title>>`, `<<title_link>>` (a link only if your CV loads `hyperref`),
`<<url>>`, `<<dates>>`, `<<tech>>`, `<<bullets>>`, and `<<bullet>>`.

### Safeguards

- `apply` refuses projects that are enabled but not `reviewed`, unless you pass
  `--allow-unreviewed`, and refuses any enabled project missing one of its three bullets.
- Suggested bullets are **sentences copied from the README**, never generated. README
  prose is often long or written as instructions; treat suggestions as raw material.
- `&`, `%`, `_`, `#` and similar are escaped. Arrows, `×`, `·` and similar are converted
  to LaTeX; combining accents are removed with a warning. Bullets over 160
  characters are flagged.
- `projects.yaml`, `*.togglecv.tex`, `*.togglecv.pdf` and `*.bak` are git-ignored.
- Public repos need no token; set `GITHUB_TOKEN` for private repos or higher rate limits.

---

## Built-in two-profile builder (`build.py`)

The rest of this README covers `build.py`, which renders complete one-page CVs from its
own templates instead of editing an existing `.tex`.

**One YAML file in, one-page PDFs out.** A config-driven CV builder that keeps every
project you've done in one place, drafts Result/Action/Context bullets from your
GitHub READMEs (saved only when you approve them), lets you switch each project on
or off per audience with a boolean, and refuses to publish a PDF that has half-empty
lines, wrapped bullets, or spills onto a second page.

```
GitHub READMEs ──► --draft (you pick/edit/approve) ──┐
                                                     ▼
config.yaml ──► validate ──► select per profile ──► Jinja2 → LaTeX ──► pdfLaTeX ──► line-fit + 1-page check ──► cv.pdf / YC_CV.pdf
     ▲
     └── python build.py --sync-github   (imports new repos, switched off)
```

### Why

Keeping several CV versions in sync by hand goes wrong fast: a metric gets updated in
one file but not the other, a new project never makes it in, or a bullet wraps onto a
second line and leaves white space. This tool keeps **one source of truth** and makes
the layout rules machine-checked.

### Quick start

Requirements: Python 3.10+, `PyYAML`, `Jinja2`, and a TeX distribution with
`pdflatex` (MiKTeX or TeX Live).

```powershell
copy config.example.yaml config.yaml   # macOS/Linux: cp config.example.yaml config.yaml
python build.py --all                  # build both CVs
```

`config.yaml`, the generated PDFs/LaTeX and `assets/` are git-ignored so your
personal details stay out of the repository. To show a logo and photo on the
research CV, put the images in `assets/`, set `person.logo` / `person.photo`, and
turn on `profiles.research.sections.logo` / `photo`.

| Command | What it does |
|---|---|
| `python build.py` | Research CV → `cv.tex`, `cv.pdf` |
| `python build.py --yc` | Startup/industry CV → `YC_CV.tex`, `YC_CV.pdf` |
| `python build.py --all` | Both |
| `python build.py --list` | Show every project and its on/off switches |
| `python build.py -v` | Also print how full each line is |
| `python build.py --sync-github` | Refresh GitHub metadata in `config.yaml` |
| `python build.py --draft [ID ...]` | Pick RAC bullets from GitHub READMEs, saved only on approval |
| `python build.py --tex-only` | Write LaTeX without compiling (no checks) |
| `python -m unittest test_cv_config -v` | Run the test suite |

### Turning a project on or off

Every project has one switch per CV profile:

```yaml
projects:
  agnostos-v2:
    enabled:
      research: false   # left out of cv.pdf
      yc: true          # included in YC_CV.pdf
```

Use real YAML booleans. `"false"` in quotes, `0`, or `1` are rejected with an error
instead of being guessed. Disabling a project keeps all of its text, so you can bring
it back later by flipping the switch.

Whole sections and individual list entries work the same way:

```yaml
profiles:
  yc:
    sections:
      highlights: true
    skills:
    - enabled: false
      name: Applied Engineering
      text: Transformers, MoE, model evaluation, ...
```

`python build.py --list` prints the current state:

```text
Project ID                               Research  YC
gated-dual-stream-particle-transformer   true      true
agnostos-v2                              false     true
asclepius                                false     false
...
```

### Writing a project

```yaml
projects:
  my-project:
    enabled: {research: true, yc: false}
    github_repo: Avinashistoocool/my-project   # empty for non-GitHub work
    title: My Project | What It Is
    url: https://github.com/Avinashistoocool/my-project
    dates: Jan - Mar 2027
    bullets:                                   # exactly three, one line each
    - Result: what changed, with a measured number.
    - Action: what you built and with which tools.
    - Context: where, why, and who you worked with.
    notes: Where the numbers come from. Not printed.
    overrides:
      yc:                                      # optional per-profile wording
        title: My Project | Shorter Title
```

Inline formatting: `**bold**`, `*italic*`, `[label](url)`. LaTeX special characters
are escaped for you.

An override replaces the shared field for that profile only. If an edit "doesn't
show up", check whether that profile has an override for the same field.

### Drafting bullets from GitHub READMEs

```powershell
python build.py --draft                 # every repo-linked project with no bullets yet
python build.py --draft my-project      # one or more specific project IDs
```

ToggleCV fetches the project's README through the GitHub API, strips code blocks,
tables, images, badges and headings, then ranks the remaining sentences into the
three slots:

| Slot | Favours sentences that… |
|---|---|
| **Result** | contain numbers or outcome words (accuracy, latency, reduced, stars…) |
| **Action** | start with or contain build verbs (built, trained, implemented, uses…) |
| **Context** | describe purpose or setting (goal, for, hackathon, course, team…) |

Setup instructions ("Run…", "Install…", command-line flags, file paths) are
pushed down the list. For each slot you choose a numbered candidate (and can edit
it), write your own (`e`), keep the existing bullet (`k`), or skip the project
(`s`). Nothing is written until you confirm **Save these to config.yaml? [y/N]**.

```text
== Result: what was achieved, ideally with a measured number ==
  [1] On the v2 10M checkpoint, the upcycled model reached val acc 0.8479 ...
  [2] ...
  [e] write your own   [s] skip project (nothing saved)
Choice: 1
Edit (Enter keeps it as shown): Kept **84.8% accuracy** after upcycling a dense jet tagger into an 8-expert MoE.
```

Rules it follows:

- Candidates are **copied from your README**, never generated. No LLM, no API key.
- Approval is per project; declining or pressing Ctrl+C leaves `config.yaml` untouched.
- Saving does **not** switch a project on. Flip `enabled.<profile>` yourself.
- A dated note is added to the project's `notes` so you know where the text came from.
- README sentences are usually too long for one CV line: edit them down, then run
  `python build.py --all -v` to check fit.
- Public repos need no token. Set `GITHUB_TOKEN` for private repos or to avoid rate limits.

### Layout rules the build enforces

A PDF is only written if all of these pass:

- **Exactly one page**, with no overflowing boxes.
- **Every bullet, skill row, achievement and leadership line fits on one line** and
  fills at least **94%** of the line before justification, so there are no ragged
  half-lines.
- **Each enabled project has three non-empty bullets.**
- Profiles, project order, booleans and field types are valid; duplicate YAML keys
  are rejected.

When a check fails you get the exact line and its fill percentage:

```text
TOO SHORT   88.5%  project 5 bullet 1: expand wording without inventing claims
TOO LONG   104.4%  project 1 bullet 3: rewrite as one line
```

The previous `cv.pdf` and `.tex` are left untouched; the failed attempt and its log
stay in `build/`. Fonts are never shrunk and projects are never dropped silently, so
fix the wording or switch a project off.

### Syncing with GitHub

```powershell
python build.py --sync-github          # update config.yaml only
python build.py --sync-github --all    # update, then rebuild
```

This reads all public repositories for `github.username` (no token needed; GitHub's
anonymous rate limit applies). It:

- refreshes stored metadata such as description, language, stars, forks and dates;
- follows renamed repositories by GitHub ID;
- adds new repositories **switched off with empty bullets**, so nothing reaches a PDF
  until you write it;
- never deletes or disables existing entries and never edits your bullets, titles or
  switches;
- leaves `config.yaml` unchanged if anything goes wrong.

It does not run repository code or generate claims. Star counts it fetches are not
copied into your bullets automatically.

Syncing rewrites the YAML layout and drops custom comments. Put anything you want to
keep in a project's `notes` field.

## Files

| Path | Purpose |
|---|---|
| `togglecv.py` | GitHub → `projects.yaml` → Projects section of your own `.tex` |
| `projects.example.yaml` | Example toggle file for `togglecv.py` |
| `test_togglecv.py` | Tests for sync, section detection, rendering, approval and compiling |
| `config.yaml` | Your content and switches (git-ignored; start from `config.example.yaml`) |
| `config.example.yaml` | Sanitized example that builds both CVs |
| `build.py` | CLI: render, compile, check, publish |
| `cv_config.py` | Validation, profile selection, GitHub sync |
| `readme_draft.py` | README fetch, sentence ranking, interactive approval |
| `test_readme_draft.py` | Tests for extraction and approve/decline behaviour |
| `template.tex.j2` | Research CV layout (logo, photo, academic table) |
| `yc.tex.j2` | Industry CV layout (text-first, no photo) |
| `assets/` | Logo and photo for the research CV |
| `test_cv_config.py` | Tests for toggles, overrides, sync and failure handling |
| `build/` | Intermediate LaTeX output and logs (git-ignored) |

### Config reference

| Field | Meaning |
|---|---|
| `person` | Name, email, phone, website, logo and photo paths |
| `github.username` | Account used by `--sync-github` |
| `profiles.<p>.sections` | On/off for whole sections |
| `profiles.<p>.project_order` | Preferred order; other enabled projects are appended |
| `profiles.<p>.links/skills/education/...` | Entries, each with `enabled` |
| `projects.<id>.enabled` | Per-profile switches |
| `projects.<id>.title/url/dates/bullets` | Shared content |
| `projects.<id>.overrides.<p>` | Per-profile replacements |
| `projects.<id>.github` | Fetched metadata (read-only, refreshed by sync) |
| `projects.<id>.notes` | Private source notes, never printed |

## Overleaf

`cv.tex` and `YC_CV.tex` are standalone pdfLaTeX documents. For the research CV, also
upload the `assets` folder.

### Adding another profile

The schema ships with `research` and `yc`. Adding a third (for example `quant`)
currently means adding it to `PROFILES` in `cv_config.py`, giving it a
`profiles.quant` block, an `enabled.quant` switch on each project, and a template.

## Keeping it honest

The build checks layout, not truth. Keep the source of each number in `notes`, and
don't let a line-length warning push you into padding a bullet with claims you can't
back up. Rewording is fine; inventing isn't.
