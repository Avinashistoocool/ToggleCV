# ToggleCV

**Your GitHub repos → a YAML file of on/off switches → the Projects section of your
own LaTeX CV.** Each project gets exactly three bullets in the
**Result / Action / Context (R-A-C)** structure. The tool drafts the bullets from the README of the project. It
uses them only after you approve them.

## The R-A-C structure

| Bullet | Contents | Example |
|---|---|---|
| **Result** | The change. Start with a measured result. | Reached **91% test accuracy**, up from a 78% baseline. |
| **Action** | The item that *you* built, and the tools. | Trained a small CNN in PyTorch with augmentation and early stopping. |
| **Context** | The location, the reason, the users and the team. | Course project comparing baselines with deep models on a 6 GB GPU. |

With three lines for each project:

- All entries have the same size.
- The evidence comes first.
- You can easily see when a project has no result to state.

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

The sequence of the list is the sequence in the CV. For a complete file, refer to `projects.example.yaml`.

| Command | Function |
|---|---|
| `togglecv.py init --user NAME` | Make `projects.yaml`. Each repo starts **off** and **unreviewed**, with one README sentence as a suggestion for each slot. The command skips forks and your profile README repo (to keep forks, use `--include-forks`). |
| `togglecv.py refresh` | Add new repos (off), update stars/language/URLs, and follow renames. This command never changes your switches, titles, dates or bullets. It keeps deleted repos and marks them `missing`. |
| `togglecv.py list` | Show the `on`/`ok` status for each project. |
| `togglecv.py review [NAME ...]` | For each enabled, unreviewed project (or each named project): select a README sentence for each slot, edit it, write your own, or keep the current one. The command saves and sets `reviewed: true` only when you answer `y`. |
| `togglecv.py apply CV.tex` | Replace the Projects section with your enabled projects. The command writes `CV.togglecv.tex`. Use `--out FILE` or `--in-place` (keeps a `.bak`). `--compile [ENGINE]` checks that the file builds. |

### How `apply` finds your Projects section

1. If the file has a `% TOGGLECV:BEGIN` line and a `% TOGGLECV:END` line, `apply` replaces only the text
   between them. `apply` adds these markers the first time. Thus, you can run it again safely,
   and the result is the same.
2. If not, it looks for **one** heading that contains "Project": `\section`,
   `\section*`, `\subsection`, or a custom macro such as `\cvsection{...}`. It replaces all text
   after that heading, up to the next heading of the same or a higher level.
   It ignores headings in `%` comments.
3. If no heading or two or more headings agree, it stops. It tells you to paste the two
   marker lines where your projects must go.

`apply` does not change your original file, unless you use `--in-place`.

### Match the appearance of your CV

- `style: auto` uses the Jake's Resume macros (`\resumeProjectHeading`, `\resumeItem`, …)
  when your file defines them. If not, it uses a nested `itemize`.
- With `style: custom`, you can describe one entry with placeholders:

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

- `apply` refuses projects that are enabled but not `reviewed`, unless you use
  `--allow-unreviewed`. It also refuses each enabled project that does not have all three bullets.
- The suggested bullets are **sentences copied from the README**. The tool never generates them. README
  text is frequently long or written as instructions. Thus, use the suggestions only as raw material.
- The tool escapes `&`, `%`, `_`, `#` and similar characters. It converts arrows, `×`, `·` and similar characters
  to LaTeX. It removes combining accents and gives a warning. It identifies bullets that are longer than 160
  characters.
- Git ignores `projects.yaml`, `*.togglecv.tex`, `*.togglecv.pdf` and `*.bak`.
- Public repos do not need a token. Set `GITHUB_TOKEN` for private repos or for higher rate limits.

---

## Built-in two-profile builder (`build.py`)

The remaining part of this README is about `build.py`. This script makes complete one-page CVs from its
own templates. It does not edit a `.tex` file that you already have.

**One YAML file in, one-page PDFs out.** This config-driven CV builder does these tasks:

- It keeps all of your projects in one location.
- It drafts Result/Action/Context bullets from your GitHub READMEs, and saves them only when you approve them.
- It lets you set each project on or off for each audience with a boolean.
- It refuses to publish a PDF that has half-empty lines or wrapped bullets, or that goes onto a second page.

```
GitHub READMEs ──► --draft (you pick/edit/approve) ──┐
                                                     ▼
config.yaml ──► validate ──► select per profile ──► Jinja2 → LaTeX ──► pdfLaTeX ──► line-fit + 1-page check ──► cv.pdf / YC_CV.pdf
     ▲
     └── python build.py --sync-github   (imports new repos, switched off)
```

### Reason for the tool

If you keep different CV versions in sync manually, errors occur quickly:

- You update a metric in one file but not in the other file.
- A new project does not get into the CV.
- A bullet wraps onto a second line and leaves white space.

This tool keeps **one source of truth**, and a machine checks the layout rules.

### Quick start

Requirements: Python 3.10+, `PyYAML`, `Jinja2`, and a TeX distribution with
`pdflatex` (MiKTeX or TeX Live).

```powershell
copy config.example.yaml config.yaml   # macOS/Linux: cp config.example.yaml config.yaml
python build.py --all                  # build both CVs
```

Git ignores `config.yaml`, the generated PDFs/LaTeX and `assets/`. Thus, your
personal data stays out of the repository. To show a logo and a photo on the
research CV, do these steps:

1. Put the images in `assets/`.
2. Set `person.logo` / `person.photo`.
3. Set `profiles.research.sections.logo` / `photo` to on.

| Command | Function |
|---|---|
| `python build.py` | Research CV → `cv.tex`, `cv.pdf` |
| `python build.py --yc` | Startup/industry CV → `YC_CV.tex`, `YC_CV.pdf` |
| `python build.py --all` | Both |
| `python build.py --list` | Show each project and its on/off switches |
| `python build.py -v` | Also print the fill of each line |
| `python build.py --sync-github` | Refresh the GitHub metadata in `config.yaml` |
| `python build.py --draft [ID ...]` | Select RAC bullets from GitHub READMEs; saves them only on approval |
| `python build.py --tex-only` | Write LaTeX without compilation (no checks) |
| `python -m unittest test_cv_config -v` | Run the test suite |

### Set a project on or off

Each project has one switch for each CV profile:

```yaml
projects:
  agnostos-v2:
    enabled:
      research: false   # left out of cv.pdf
      yc: true          # included in YC_CV.pdf
```

Use real YAML booleans. The tool rejects `"false"` in quotes, `0`, or `1` with an error.
It does not guess the value. When you disable a project, the tool keeps all of its text. Thus, you can add
it back later with the switch.

Full sections and individual list entries operate in the same way:

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

### Write a project

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

Inline formatting: `**bold**`, `*italic*`, `[label](url)`. The tool escapes the LaTeX special characters
for you.

An override replaces the shared field only for that profile. If you do not see an edit in the output,
make sure that the profile does not have an override for the same field.

### Draft bullets from GitHub READMEs

```powershell
python build.py --draft                 # every repo-linked project with no bullets yet
python build.py --draft my-project      # one or more specific project IDs
```

ToggleCV gets the README of the project through the GitHub API. It removes code blocks,
tables, images, badges and headings. Then it puts the remaining sentences in order for the
three slots:

| Slot | Gives priority to sentences that… |
|---|---|
| **Result** | contain numbers or result words (accuracy, latency, reduced, stars…) |
| **Action** | start with or contain build verbs (built, trained, implemented, uses…) |
| **Context** | describe the purpose or setting (goal, for, hackathon, course, team…) |

Setup instructions ("Run…", "Install…", command-line flags, file paths) get a lower position in the list.
For each slot, you can do one of these actions:

- Select a numbered candidate (you can edit it).
- Write your own (`e`).
- Keep the current bullet (`k`).
- Skip the project (`s`).

The tool writes nothing until you confirm **Save these to config.yaml? [y/N]**.

```text
== Result: what was achieved, ideally with a measured number ==
  [1] On the v2 10M checkpoint, the upcycled model reached val acc 0.8479 ...
  [2] ...
  [e] write your own   [s] skip project (nothing saved)
Choice: 1
Edit (Enter keeps it as shown): Kept **84.8% accuracy** after upcycling a dense jet tagger into an 8-expert MoE.
```

Rules of the tool:

- The candidates are **copied from your README**. The tool never generates them. No LLM, no API key.
- You approve each project separately. If you decline or push Ctrl+C, `config.yaml` does not change.
- A save does **not** set a project to on. Set `enabled.<profile>` yourself.
- The tool adds a dated note to the `notes` of the project, so that you know the source of the text.
- README sentences are usually too long for one CV line. Make them shorter, then run
  `python build.py --all -v` to check the fit.
- Public repos do not need a token. Set `GITHUB_TOKEN` for private repos or to prevent rate limits.

### Layout rules of the build

The tool writes a PDF only if all of these checks pass:

- **Exactly one page**, with no overflowing boxes.
- **Each bullet, skill row, achievement and leadership line is on one line.** It
  fills a minimum of **94%** of the line before justification. Thus, there are no
  half-empty lines.
- **Each enabled project has three bullets that are not empty.**
- The profiles, project sequence, booleans and field types are valid. The tool rejects duplicate YAML keys.

When a check fails, you get the line and its fill percentage:

```text
TOO SHORT   88.5%  project 5 bullet 1: expand wording without inventing claims
TOO LONG   104.4%  project 1 bullet 3: rewrite as one line
```

The previous `cv.pdf` and `.tex` do not change. The failed attempt and its log
stay in `build/`. The tool never makes the fonts smaller, and it never removes projects without a message.
Thus, correct the text or set a project to off.

### Sync with GitHub

```powershell
python build.py --sync-github          # update config.yaml only
python build.py --sync-github --all    # update, then rebuild
```

This command reads all public repositories for `github.username`. It does not need a token, but the anonymous
rate limit of GitHub applies. The command does these tasks:

- It refreshes the stored metadata, for example description, language, stars, forks and dates.
- It follows renamed repositories by their GitHub ID.
- It adds new repositories **switched off with empty bullets**. Thus, nothing gets into a PDF
  until you write it.
- It never deletes or disables current entries. It never edits your bullets, titles or
  switches.
- If an error occurs, `config.yaml` does not change.

The command does not run repository code or generate claims. It does not copy the star counts
into your bullets automatically.

> **CAUTION:** Put each comment that you want to keep in the `notes` field of a project. The sync writes the YAML layout again and removes custom comments.

## Files

| Path | Purpose |
|---|---|
| `togglecv.py` | GitHub → `projects.yaml` → Projects section of your own `.tex` |
| `projects.example.yaml` | Example toggle file for `togglecv.py` |
| `test_togglecv.py` | Tests for sync, section detection, rendering, approval and compilation |
| `config.yaml` | Your content and switches (git-ignored; start from `config.example.yaml`) |
| `config.example.yaml` | Sanitized example that builds both CVs |
| `build.py` | CLI: render, compile, check, publish |
| `cv_config.py` | Validation, profile selection, GitHub sync |
| `readme_draft.py` | README fetch, sentence ranking, interactive approval |
| `test_readme_draft.py` | Tests for extraction and approve/decline behaviour |
| `template.tex.j2` | Research CV layout (logo, photo, academic table) |
| `yc.tex.j2` | Industry CV layout (text first, no photo) |
| `assets/` | Logo and photo for the research CV |
| `test_cv_config.py` | Tests for toggles, overrides, sync and failure handling |
| `build/` | Intermediate LaTeX output and logs (git-ignored) |

### Config reference

| Field | Meaning |
|---|---|
| `person` | Name, email, phone, website, logo and photo paths |
| `github.username` | Account that `--sync-github` uses |
| `profiles.<p>.sections` | On/off for full sections |
| `profiles.<p>.project_order` | Preferred sequence; the tool adds the other enabled projects at the end |
| `profiles.<p>.links/skills/education/...` | Entries, each with `enabled` |
| `projects.<id>.enabled` | Switches for each profile |
| `projects.<id>.title/url/dates/bullets` | Shared content |
| `projects.<id>.overrides.<p>` | Replacements for each profile |
| `projects.<id>.github` | Fetched metadata (read-only; the sync refreshes it) |
| `projects.<id>.notes` | Private source notes; never printed |

## Overleaf

`cv.tex` and `YC_CV.tex` are standalone pdfLaTeX documents. For the research CV, also
upload the `assets` folder.

### Add a profile

The schema has the profiles `research` and `yc`. To add a third profile (for example `quant`), do these steps at this time:

1. Add it to `PROFILES` in `cv_config.py`.
2. Give it a `profiles.quant` block.
3. Add an `enabled.quant` switch to each project.
4. Add a template.

## Accuracy of the content

The build checks the layout, not the truth. Keep the source of each number in `notes`.

> **CAUTION:** Do not add claims that you cannot prove to a bullet because of a line-length warning. You can change the words, but do not invent content.
