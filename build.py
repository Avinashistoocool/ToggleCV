"""ToggleCV: build selected CV projects from config.yaml; refresh public repos with --sync-github."""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2

from cv_config import ConfigError, load_config, prepare_profile, sync_github

ROOT = Path(__file__).resolve().parent
MIN_FILL = 94.0
DEFAULT_LAYOUT = {
    "section_before": "6pt plus 12pt", "section_after": "3pt plus 4pt",
    "item_sep": "2pt plus 4pt", "header_height": "0.85in",
}
SPECIALS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "\u00b0": r"\textdegree{}", "\u2019": "'", "\u2018": "`", "\u201c": "``", "\u201d": "''",
    "\u2013": "--", "\u2014": "---", "\u00b5": r"\textmu{}",
    "<": r"\textless{}", ">": r"\textgreater{}",
}


def esc(text):
    return "".join(SPECIALS.get(char, char) for char in str(text))


def urlesc(url):
    return str(url).replace("%", r"\%").replace("#", r"\#")


def fmt(text):
    """Escape LaTeX, then apply the CV's lightweight emphasis/link syntax."""
    links = []

    def keep_link(match):
        links.append((match.group(1), match.group(2)))
        return f"\x00{len(links) - 1}\x00"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", keep_link, str(text))
    text = esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)\*", r"\\textit{\1}", text)
    for i, (label, url) in enumerate(links):
        text = text.replace(f"\x00{i}\x00", rf"\href{{{urlesc(url)}}}{{\underline{{{esc(label)}}}}}")
    return text


def visible(items):
    return [item for item in items or [] if not (isinstance(item, dict) and item.get("hidden"))]


def render_tex(data, profile):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROOT),
        block_start_string=r"\BLOCK{", block_end_string="}",
        variable_start_string=r"\VAR{", variable_end_string="}",
        comment_start_string=r"\#{", comment_end_string="}",
        trim_blocks=True, lstrip_blocks=True, autoescape=False, undefined=jinja2.StrictUndefined,
    )
    env.filters.update(esc=esc, fmt=fmt, visible=visible, urlesc=urlesc)
    context = {**data, "layout": {**DEFAULT_LAYOUT, **data.get("layout", {})}, "data": data}
    template = "yc.tex.j2" if profile == "yc" else "template.tex.j2"
    return env.get_template(template).render(**context)


def expected_lines(data, profile):
    count = sum(len(project["bullets"]) for project in data["projects"]) + len(data["skills"])
    if profile == "yc":
        return count + len(data["highlights"])
    return count + len(data["achievements"]) + len(data["leadership"]) + bool(data["research_interests"])


def check_lines(fit, expected, verbose=False):
    rows = fit.splitlines()
    if len(rows) != expected:
        raise ConfigError(f"Incomplete line measurements: expected {expected}, got {len(rows)}")
    ok = True
    for row in rows:
        match = re.fullmatch(r"([^:\n]+):(\d+(?:\.\d+)?)pt:(\d+(?:\.\d+)?)pt:(\d+)", row)
        if not match:
            raise ConfigError(f"Invalid line measurement: {row}")
        name, width, available, lines = match.groups()
        if float(available) <= 0:
            raise ConfigError(f"Invalid available width for {name}")
        fill = float(width) / float(available) * 100
        if int(lines) != 1:
            print(f"  TOO LONG  {fill:6.1f}%  {name}: rewrite as one line")
            ok = False
        elif fill < MIN_FILL:
            print(f"  TOO SHORT {fill:6.1f}%  {name}: expand wording without inventing claims")
            ok = False
        elif verbose:
            print(f"  ok        {fill:6.1f}%  {name}")
    if not ok:
        raise ConfigError("Line check failed; previous PDF retained. Edit the selected project's config wording.")
    print("Line check: all selected lines fill end-to-end.")


def build_profile(config, profile, tex_only=False, verbose=False):
    data = prepare_profile(config, profile)
    stem = "YC_CV" if profile == "yc" else "cv"
    tex = render_tex(data, profile)
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    source = build / f"{stem}.tex"
    source.write_text(tex, encoding="utf-8")
    if tex_only:
        shutil.copyfile(source, ROOT / f"{stem}.tex")
        print(f"Wrote {stem}.tex (PDF was not rebuilt)")
        return
    if not shutil.which("pdflatex"):
        raise ConfigError("pdflatex is required; install MiKTeX or use --tex-only")
    result = subprocess.run(
        ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
         f"-output-directory={build}", str(source)],
        cwd=ROOT, capture_output=True, text=True, errors="replace",
    )
    if result.returncode != 0:
        print(result.stdout[-3000:])
        if result.stderr:
            print(result.stderr[-1000:])
        raise ConfigError(f"pdfLaTeX failed; inspect build\\{stem}.log. Previous PDF retained.")
    log = (build / f"{stem}.log").read_text(encoding="latin-1")
    pages = re.search(r"Output written on.*?\((\d+)\s+page", log, re.S)
    if not pages or pages.group(1) != "1":
        raise ConfigError(
            f"{profile} CV exceeds one page or page count is missing. Disable projects/sections "
            "in config.yaml or shorten content; previous PDF retained."
        )
    if re.search(r"Overfull \\[hv]box", log):
        raise ConfigError(f"{profile} has overflowing content; inspect build\\{stem}.log. Previous PDF retained.")
    check_lines((build / f"{stem}.fit").read_text(encoding="latin-1"),
                expected_lines(data, profile), verbose)
    shutil.copyfile(source, ROOT / f"{stem}.tex")
    shutil.copyfile(build / f"{stem}.pdf", ROOT / f"{stem}.pdf")
    print(f"Wrote {stem}.pdf: 1 page, {len(data['projects'])} selected projects.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--yc", action="store_true", help="build YC_CV.pdf instead of the research CV")
    profiles.add_argument("--all", action="store_true", help="build both profiles")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--sync-github", action="store_true", help="refresh metadata; new repos stay disabled")
    parser.add_argument("--list", action="store_true", help="list project IDs and their inclusion switches")
    parser.add_argument("--tex-only", action="store_true", help="export selected LaTeX without compiling")
    parser.add_argument("--strict", action="store_true", help="compatibility flag; validation is always strict")
    parser.add_argument("-v", action="store_true", help="show line fill measurements")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.sync_github:
            config = sync_github(args.config, config)
        if args.list:
            print(f"{'Project ID':45} Research  YC")
            for project_id, project in config["projects"].items():
                selected = project["enabled"]
                print(f"{project_id:45} {str(selected['research']).lower():8}  {str(selected['yc']).lower()}")
            return 0
        if args.sync_github and not (args.yc or args.all or args.tex_only):
            print("Metadata refreshed only. Run python build.py --all to rebuild the PDFs.")
            return 0
        for profile in (("research", "yc") if args.all else ("yc" if args.yc else "research",)):
            build_profile(config, profile, args.tex_only, args.v)
    except (ConfigError, OSError, jinja2.TemplateError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
