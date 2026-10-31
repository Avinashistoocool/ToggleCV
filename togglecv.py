"""ToggleCV for your own LaTeX CV.

GitHub repositories -> projects.yaml (on/off switch + three R-A-C bullets each)
-> the Projects section of any .tex CV you already have.
"""
import argparse
import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

from build import esc, fmt, urlesc
from cv_config import ConfigError, UniqueKeyLoader, fetch_public_repos
from readme_draft import SLOTS, candidates, fetch_readme, readme_sentences, review

STYLES = ("auto", "jake", "itemize", "custom")
TEX_SYMBOLS = {
    "\u2192": r"$\rightarrow$", "\u2190": r"$\leftarrow$", "\u00b7": r"\textperiodcentered{}",
    "\u00d7": r"$\times$", "\u2248": r"$\approx$", "\u2264": r"$\leq$", "\u2265": r"$\geq$",
    "\u00b1": r"$\pm$", "\u2022": r"\textbullet{}", "\u2026": r"\ldots{}", "\u00a0": "~",
}
BEGIN = "% TOGGLECV:BEGIN generated from projects.yaml; edit there, not here"
END = "% TOGGLECV:END"
CUSTOM_KEYS = ("before", "entry", "bullet", "after")
REPO_NAME = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
HEADING = re.compile(r"\\([A-Za-z]*section[A-Za-z]*)\*?", re.I)
FILE_HEADER = """# ToggleCV projects: one entry per GitHub repository.
# enabled: true  -> the project goes into your CV's Projects section (list order = CV order).
# rac            -> the three bullets: Result, Action, Context. Drafted from the README; edit freely.
# reviewed: true -> you have checked the bullets. apply refuses enabled projects that are not reviewed.
# Refresh from GitHub with: python togglecv.py refresh   (keeps your toggles and edits)
"""


# ---------------------------------------------------------------- projects.yaml

def validate(data):
    if not isinstance(data, dict):
        raise ConfigError("Projects file must be a YAML mapping")
    if not isinstance(data.get("github_user"), str) or not data["github_user"].strip():
        raise ConfigError("github_user must be your GitHub username")
    data.setdefault("style", "auto")
    data.setdefault("show_language", True)
    if data["style"] not in STYLES:
        raise ConfigError(f"style must be one of: {', '.join(STYLES)}")
    if type(data["show_language"]) is not bool:
        raise ConfigError("show_language must be true or false (not quoted)")
    if data["style"] == "custom":
        custom = data.get("custom")
        if not isinstance(custom, dict) or not all(isinstance(custom.get(k), str) for k in CUSTOM_KEYS):
            raise ConfigError("style: custom needs custom.before, custom.entry, custom.bullet and custom.after")
        if "<<bullets>>" not in custom["entry"] or "<<bullet>>" not in custom["bullet"]:
            raise ConfigError("custom.entry needs <<bullets>> and custom.bullet needs <<bullet>>")
    projects = data.get("projects")
    if not isinstance(projects, list):
        raise ConfigError("projects must be a list")
    seen = set()
    for index, project in enumerate(projects):
        where = f"projects[{index}]"
        if not isinstance(project, dict):
            raise ConfigError(f"{where} must be a mapping")
        for key in ("enabled", "reviewed"):
            if type(project.get(key)) is not bool:
                raise ConfigError(f"{where}.{key} must be true or false (not quoted)")
        for key in ("repo", "title", "url", "dates", "tech"):
            project.setdefault(key, "")
            if not isinstance(project[key], str):
                raise ConfigError(f"{where}.{key} must be text; quote dates such as '2026'")
        if not project["title"].strip():
            raise ConfigError(f"{where}.title cannot be empty")
        rac = project.get("rac")
        if not isinstance(rac, dict) or set(rac) != set(SLOTS) or not all(isinstance(rac[s], str) for s in SLOTS):
            raise ConfigError(f"{where}.rac needs exactly three text fields: result, action, context")
        if project["repo"]:
            if not REPO_NAME.fullmatch(project["repo"]):
                raise ConfigError(f"{where}.repo must look like owner/name")
            key = project["repo"].casefold()
            if key in seen:
                raise ConfigError(f"{project['repo']} appears twice in the projects file")
            seen.add(key)
    return data


def load_projects(path):
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"{path} not found. Create it with: python togglecv.py init --user <github-user>")
    try:
        data = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    return validate(data)


def save_projects(path, data):
    validate(data)
    path = Path(path).resolve()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(FILE_HEADER)
            yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True, width=1000)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def suggest_rac(readme, description=""):
    """Pick one README sentence per slot (never invented text); fall back to the repo description."""
    ranked = candidates(readme_sentences(readme), 5) if readme else {slot: [] for slot in SLOTS}
    rac, used = {}, set()
    for slot in SLOTS:
        rac[slot] = next((s for s in ranked[slot] if s not in used), "")
        used.add(rac[slot])
    description = (description or "").strip()
    if not rac["context"] and description:
        rac["context"] = description if description.endswith((".", "!", "?")) else description + "."
    return rac


def metadata(repo, fetched_at):
    keys = ("id", "description", "language", "stargazers_count", "forks_count", "fork", "archived",
            "pushed_at", "html_url")
    return {**{key: repo.get(key) for key in keys}, "fetched_at": fetched_at}


def sync(path, user=None, include_forks=False, create=False, fetch_repos=fetch_public_repos,
         fetch=fetch_readme, say=print):
    """Create or refresh projects.yaml from GitHub. Your toggles, order and bullets are never overwritten."""
    path = Path(path)
    if create:
        if path.exists():
            raise ConfigError(f"{path} already exists; use: python togglecv.py refresh")
        if not user:
            raise ConfigError("init needs --user <github-user>")
        data = {"github_user": user, "style": "auto", "show_language": True, "projects": []}
    else:
        data = copy.deepcopy(load_projects(path))
        if user:
            data["github_user"] = user
    repos = fetch_repos(data["github_user"])
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    projects = data["projects"]
    by_id = {p["github"]["id"]: p for p in projects
             if isinstance(p.get("github"), dict) and p["github"].get("id") is not None}
    by_name = {p["repo"].casefold(): p for p in projects if p["repo"]}
    profile_repo = f"{data['github_user']}/{data['github_user']}".casefold()
    seen, added = set(), []
    for repo in sorted(repos, key=lambda r: (r or {}).get("pushed_at") or "", reverse=True):
        if not isinstance(repo, dict) or not all(isinstance(repo.get(k), str) and repo[k]
                                                 for k in ("name", "full_name", "html_url")):
            raise ConfigError("GitHub returned incomplete repository data; projects file not changed")
        name = repo["full_name"]
        existing = by_id.get(repo.get("id")) or by_name.get(name.casefold())
        if existing is not None:
            previous = (existing.get("github") or {}).get("html_url")
            if existing["url"] in ("", previous, f"https://github.com/{existing['repo']}"):
                existing["url"] = repo["html_url"]
            existing["repo"] = name
            existing["github"] = metadata(repo, fetched_at)
            seen.add(id(existing))
            continue
        if (repo.get("fork") and not include_forks) or name.casefold() == profile_repo:
            continue
        try:
            readme = fetch(name)
        except ConfigError as error:
            say(f"  {name}: {error}; bullets left empty")
            readme = ""
        project = {
            "repo": name, "enabled": False, "reviewed": False, "title": repo["name"],
            "url": repo["html_url"], "dates": "", "tech": repo.get("language") or "",
            "rac": suggest_rac(readme, repo.get("description")), "github": metadata(repo, fetched_at),
        }
        projects.append(project)
        seen.add(id(project))
        added.append(name)
    missing = []
    for project in projects:
        if project["repo"] and id(project) not in seen:
            missing.append(project["repo"])
            if isinstance(project.get("github"), dict):
                project["github"]["missing"] = True
    save_projects(path, data)
    say(f"{'Created' if create else 'Refreshed'} {path}: {len(repos)} repositories on GitHub, "
        f"{len(added)} added (switched off), {len(missing)} no longer found (kept).")
    if added:
        say("Next: open the file, set enabled: true on the projects you want, edit their rac bullets, "
            "set reviewed: true (or run: python togglecv.py review).")
    return data


def select(data, selectors):
    if not selectors:
        return [p for p in data["projects"] if p["enabled"] and not p["reviewed"]]
    chosen = []
    for selector in selectors:
        key = selector.casefold()
        matches = [p for p in data["projects"]
                   if key in (p["repo"].casefold(), p["repo"].split("/")[-1].casefold(), p["title"].casefold())]
        if not matches:
            raise ConfigError(f"No project matches {selector!r}. Run: python togglecv.py list")
        chosen.extend(m for m in matches if m not in chosen)
    return chosen


def review_projects(path, selectors, ask=input, say=print, fetch=fetch_readme):
    data = copy.deepcopy(load_projects(path))
    targets = select(data, selectors)
    if not targets:
        say("Nothing to review: every enabled project is already reviewed. Name projects to re-review them.")
        return data
    changed = False
    for project in targets:
        if not project["repo"]:
            say(f"{project['title']}: no repo; edit its rac bullets in the file directly")
            continue
        try:
            readme = fetch(project["repo"])
        except ConfigError as error:
            say(f"{project['repo']}: {error}")
            continue
        bullets = review(project["repo"], {"github_repo": project["repo"],
                                           "bullets": [project["rac"][s] or None for s in SLOTS]},
                         readme, ask, say, target=Path(path).name)
        if bullets:
            project["rac"] = dict(zip(SLOTS, bullets))
            project["reviewed"] = True
            changed = True
    if changed:
        save_projects(path, data)
        say(f"Saved {path}.")
    return data


# ---------------------------------------------------------------- LaTeX

def mask_comments(text):
    """Blank out % comments (keeping every index) so headings in comments are ignored."""
    output = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        index, cut = 0, None
        while index < len(body):
            if body[index] == "\\":
                index += 2
                continue
            if body[index] == "%":
                cut = index
                break
            index += 1
        output.append((body if cut is None else body[:cut] + " " * (len(body) - cut)) + ending)
    return "".join(output)


def group_end(text, index):
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise ConfigError("Unbalanced braces in a section heading")


def headings(masked, start, stop):
    found = []
    for match in HEADING.finditer(masked, start, stop):
        index = match.end()
        while index < stop and masked[index] in " \t\r\n":
            index += 1
        if index < stop and masked[index] == "[":
            close = masked.find("]", index, stop)
            if close == -1:
                continue
            index = close + 1
            while index < stop and masked[index] in " \t\r\n":
                index += 1
        if index >= stop or masked[index] != "{":
            continue
        end = group_end(masked, index)
        command = match.group(1).lower()
        title = re.sub(r"\\[A-Za-z]+\*?|[{}]", " ", masked[index + 1:end - 1])
        rank = 3 if "subsub" in command else 2 if "sub" in command else 1
        found.append({"start": match.start(), "end": end, "title": " ".join(title.split()), "rank": rank})
    return found


def find_projects(text):
    """Return (start, end, mode) of the text to replace."""
    begins = list(re.finditer(r"(?m)^[ \t]*% TOGGLECV:BEGIN[^\r\n]*", text))
    ends = list(re.finditer(r"(?m)^[ \t]*% TOGGLECV:END[ \t]*(?=\r?$)", text))
    if begins or ends:
        if len(begins) != 1 or len(ends) != 1 or ends[0].start() < begins[0].end():
            raise ConfigError("Expected exactly one '% TOGGLECV:BEGIN' line followed by one '% TOGGLECV:END' line")
        return begins[0].start(), ends[0].end(), "markers"
    masked = mask_comments(text)
    document = masked.find("\\begin{document}")
    if document == -1:
        raise ConfigError("No \\begin{document} found; is this a complete .tex CV?")
    stop = masked.find("\\end{document}", document)
    stop = len(text) if stop == -1 else stop
    found = headings(masked, document, stop)
    matches = [h for h in found if re.search(r"project", h["title"], re.I)]
    hint = f"Put these two lines where your projects should go:\n  {BEGIN}\n  {END}"
    if not matches:
        raise ConfigError("No section heading containing 'Project' was found. " + hint)
    if len(matches) > 1:
        titles = ", ".join(repr(h["title"]) for h in matches)
        raise ConfigError(f"Several headings mention projects ({titles}). " + hint)
    heading = matches[0]
    end = next((h["start"] for h in found if h["start"] > heading["start"] and h["rank"] <= heading["rank"]), stop)
    line_end = text.find("\n", heading["end"])
    start = heading["end"] if line_end == -1 or line_end >= end else line_end + 1
    lines = text[start:end].splitlines(keepends=True)
    # Comment banners and blank lines just before the next heading belong to that heading.
    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith("%")):
        lines.pop()
    return start, start + len("".join(lines)), "heading"


def detect_style(text):
    masked = mask_comments(text)
    needed = ("\\resumeProjectHeading", "\\resumeItem", "\\resumeSubHeadingListStart", "\\resumeItemListStart")
    return "jake" if all(name in masked for name in needed) else "itemize"


def has_hyperref(text):
    masked = mask_comments(text)
    document = masked.find("\\begin{document}")
    preamble = masked if document == -1 else masked[:document]
    return bool(re.search(r"\\usepackage\s*(\[[^\]]*\])?\s*\{[^}]*\bhyperref\b", preamble))


def tex(text):
    """build.fmt (escaping, **bold**, links) plus common README symbols pdfLaTeX cannot typeset."""
    text = unicodedata.normalize("NFC", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    result = fmt(text)
    for char, replacement in TEX_SYMBOLS.items():
        result = result.replace(char, replacement)
    return result


def render(projects, style, show_language, hyperref, custom=None):
    def title(project):
        text = esc(project["title"])
        return f"\\href{{{urlesc(project['url'])}}}{{{text}}}" if project["url"] and hyperref else text

    lines = []
    if style == "jake":
        lines.append("\\resumeSubHeadingListStart")
        for p in projects:
            tech = f" $|$ \\emph{{{esc(p['tech'])}}}" if show_language and p["tech"] else ""
            lines += ["  \\resumeProjectHeading",
                      f"    {{\\textbf{{{title(p)}}}{tech}}}{{{esc(p['dates'])}}}",
                      "    \\resumeItemListStart"]
            lines += [f"      \\resumeItem{{{tex(p['rac'][slot])}}}" for slot in SLOTS]
            lines.append("    \\resumeItemListEnd")
        lines.append("\\resumeSubHeadingListEnd")
    elif style == "itemize":
        lines.append("\\begin{itemize}")
        for p in projects:
            tech = f" ({esc(p['tech'])})" if show_language and p["tech"] else ""
            dates = f" \\hfill {esc(p['dates'])}" if p["dates"] else ""
            lines += [f"  \\item \\textbf{{{title(p)}}}{tech}{dates}", "  \\begin{itemize}"]
            lines += [f"    \\item {tex(p['rac'][slot])}" for slot in SLOTS]
            lines.append("  \\end{itemize}")
        lines.append("\\end{itemize}")
    elif style == "custom":
        lines.append(custom["before"])
        for p in projects:
            entry = custom["entry"]
            values = {"title": esc(p["title"]), "title_link": title(p), "url": urlesc(p["url"]),
                      "dates": esc(p["dates"]), "tech": esc(p["tech"])}
            for key, value in values.items():
                entry = entry.replace(f"<<{key}>>", value)
            bullets = "".join(custom["bullet"].replace("<<bullet>>", fmt(p["rac"][slot])) for slot in SLOTS)
            lines.append(entry.replace("<<bullets>>", bullets))
        lines.append(custom["after"])
    else:
        raise ConfigError(f"Unknown style {style!r}")
    return "\n".join(lines)


def replace_projects(text, block):
    start, end, mode = find_projects(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    generated = "\n".join([BEGIN, block, END]).replace("\r\n", "\n").replace("\n", newline)
    if mode == "markers":
        return text[:start] + generated + text[end:]
    prefix = "" if start == 0 or text[start - 1] == "\n" else newline
    return text[:start] + prefix + generated + newline + text[end:]


def compile_check(target, engine, say=print):
    executable = shutil.which(engine)
    if not executable:
        raise ConfigError(f"{engine} was not found on PATH")
    with tempfile.TemporaryDirectory(prefix="togglecv-") as folder:
        result = subprocess.run(
            [executable, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
             f"-output-directory={folder}", target.name],
            cwd=target.parent, capture_output=True, text=True, errors="replace", timeout=300,
        )
        log_path = Path(folder) / (target.stem + ".log")
        log = log_path.read_text(encoding="latin-1") if log_path.exists() else result.stdout
        if result.returncode != 0:
            say(log[-2500:])
            raise ConfigError(f"{engine} failed. {target.name} was written but does not compile; see the log above")
        pages = re.search(r"Output written on.*?\((\d+)\s+page", log, re.S)
        pdf = Path(folder) / (target.stem + ".pdf")
        if pdf.exists():
            shutil.copy2(pdf, target.with_suffix(".pdf"))
        say(f"Compiled with {engine}: {pages.group(1) if pages else '?'} page(s) -> {target.with_suffix('.pdf').name}")


def apply(tex_path, projects_path, out=None, in_place=False, style=None, allow_unreviewed=False,
          engine=None, say=print):
    data = load_projects(projects_path)
    chosen = [p for p in data["projects"] if p["enabled"]]
    if not chosen:
        raise ConfigError("No project has enabled: true in the projects file")
    incomplete = [p["title"] for p in chosen if not all(p["rac"][slot].strip() for slot in SLOTS)]
    if incomplete:
        raise ConfigError("Enabled projects need all three bullets (result, action, context): " + ", ".join(incomplete))
    unreviewed = [p["title"] for p in chosen if not p["reviewed"]]
    if unreviewed and not allow_unreviewed:
        raise ConfigError("Not approved yet (set reviewed: true or run: python togglecv.py review): "
                          + ", ".join(unreviewed))
    tex_path = Path(tex_path)
    try:
        with tex_path.open(encoding="utf-8-sig", newline="") as stream:
            text = stream.read()
    except UnicodeDecodeError as error:
        raise ConfigError(f"{tex_path} is not UTF-8 text") from error
    style = style or data["style"]
    if style == "auto":
        style = detect_style(text)
    block = render(chosen, style, data["show_language"], has_hyperref(text), data.get("custom"))
    updated = replace_projects(text, block)

    for p in chosen:
        for slot in SLOTS:
            if len(p["rac"][slot]) > 160:
                say(f"  note: {p['title']} {slot} bullet is {len(p['rac'][slot])} characters; it will wrap")
    unusual = sorted({char for char in block if ord(char) > 127})
    if unusual and "fontspec" not in text:
        say("  note: non-ASCII characters " + " ".join(unusual) + " may not compile with pdfLaTeX; edit them out "
            "or use XeLaTeX/LuaLaTeX")
    for p in chosen:
        if any(unicodedata.combining(c) for slot in SLOTS for c in unicodedata.normalize("NFC", p["rac"][slot])):
            say(f"  note: {p['title']}: removed combining accents (e.g. the bar in b̄); check the wording")

    if in_place:
        target = tex_path
        backup = tex_path.with_name(tex_path.name + ".bak")
        if backup.exists():
            backup = tex_path.with_name(f"{tex_path.name}.{datetime.now():%Y%m%d-%H%M%S}.bak")
        shutil.copy2(tex_path, backup)
        say(f"Backup: {backup}")
    else:
        target = Path(out) if out else tex_path.with_name(tex_path.stem + ".togglecv.tex")
        if target.resolve() == tex_path.resolve():
            raise ConfigError("Output would overwrite the input; use --in-place for that")
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        stream.write(updated)
    os.replace(temporary, target)
    say(f"Wrote {target}: {len(chosen)} projects, {style} style.")
    if engine:
        compile_check(target, engine, say)
    return target


# ---------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--projects", default="projects.yaml", help="projects file (default: projects.yaml)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create projects.yaml from your public GitHub repos")
    init.add_argument("--user", required=True)
    init.add_argument("--include-forks", action="store_true")
    refresh = commands.add_parser("refresh", help="add new repos and update metadata; keeps your edits")
    refresh.add_argument("--include-forks", action="store_true")
    commands.add_parser("list", help="show projects and their switches")
    reviewer = commands.add_parser("review", help="pick/edit bullets from READMEs and approve them")
    reviewer.add_argument("names", nargs="*", help="repo or title (default: enabled, unreviewed projects)")
    applier = commands.add_parser("apply", help="write enabled projects into a .tex CV")
    applier.add_argument("tex")
    target = applier.add_mutually_exclusive_group()
    target.add_argument("--out", help="output .tex (default: <name>.togglecv.tex)")
    target.add_argument("--in-place", action="store_true", help="overwrite the input, keeping a .bak copy")
    applier.add_argument("--style", choices=STYLES, help="override the style in projects.yaml")
    applier.add_argument("--allow-unreviewed", action="store_true")
    applier.add_argument("--compile", nargs="?", const="pdflatex", metavar="ENGINE",
                         help="check that the result compiles (default engine: pdflatex)")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            sync(args.projects, args.user, args.include_forks, create=True)
        elif args.command == "refresh":
            sync(args.projects, include_forks=args.include_forks)
        elif args.command == "list":
            data = load_projects(args.projects)
            width = max([10] + [len(p["repo"] or "(manual)") for p in data["projects"]]) + 2
            print(f"{'On':4}{'OK':4}{'Repository':{width}}Title")
            for p in data["projects"]:
                print(f"{'on' if p['enabled'] else '-':4}{'ok' if p['reviewed'] else '-':4}"
                      f"{p['repo'] or '(manual)':{width}}{p['title']}")
        elif args.command == "review":
            review_projects(args.projects, args.names)
        else:
            apply(args.tex, args.projects, args.out, args.in_place, args.style, args.allow_unreviewed, args.compile)
    except ConfigError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; nothing saved.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
