"""Draft Result/Action/Context bullets from a project's GitHub README, with user approval.

Nothing is written to config.yaml unless the user explicitly approves the final bullets.
Candidate bullets are sentences extracted from the README, never generated text.
"""
import copy
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from cv_config import ConfigError, save_config

SLOTS = ("result", "action", "context")
SLOT_HELP = {
    "result": "Result: what was achieved, ideally with a measured number",
    "action": "Action: what you built and with which tools",
    "context": "Context: where, why, or for whom",
}
ACTION_VERBS = (
    "built", "build", "implemented", "implement", "trained", "train", "designed", "design", "wrote",
    "developed", "created", "added", "used", "uses", "computes", "compute", "combines", "parses",
    "generates", "fetches", "runs", "integrates", "supports", "detects", "applies", "models",
)
RESULT_WORDS = (
    "accuracy", "auc", "precision", "recall", "f1", "latency", "throughput", "speedup", "faster",
    "reduced", "reduces", "improved", "achieved", "reached", "error", "coverage", "stars", "users",
    "benchmark", "score", "loss", "rank", "%",
)
CONTEXT_WORDS = (
    "goal", "aim", "problem", "challenge", "hackathon", "course", "thesis", "internship", "for ",
    "to help", "so that", "motivation", "because", "designed for", "under prof", "supervised",
    "competition", "research", "students", "users", "team",
)
NUMBER = re.compile(r"\d")
MIN_WORDS, MAX_WORDS = 6, 40
INSTRUCTION_START = (
    "run", "set", "install", "use", "check", "if", "open", "click", "see", "note", "make", "try",
    "clone", "copy", "edit", "add", "pass", "train", "aim", "don't", "do", "please", "replace",
)
NOISE = re.compile(r"(--\w|python -m|pip install|\.env\b|\.ya?ml\b|\.py\b|https?://|\byou(r)?\b|\bdon't\b|\berror\b.*\bfix)",
                   re.I)


def _penalty(sentence):
    first = sentence.lower().lstrip("*").split()[0].strip("*:,")
    return 4 * (first in INSTRUCTION_START) + 3 * len(NOISE.findall(sentence)) + (len(sentence) > 220)


def fetch_readme(full_name):
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", full_name or ""):
        raise ConfigError(f"Not a GitHub owner/repository name: {full_name!r}")
    owner, repo = full_name.split("/")
    headers = {
        "Accept": "application/vnd.github.raw", "User-Agent": "ToggleCV",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/readme"
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            return response.read(1_000_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        if error.code == 404:
            raise ConfigError(f"{full_name} has no README (or is private)") from error
        raise ConfigError(f"GitHub returned HTTP {error.code} for {full_name}; check rate limits or set GITHUB_TOKEN") from error
    except (URLError, TimeoutError, OSError) as error:
        raise ConfigError(f"Could not fetch README for {full_name}: {error}") from error


def readme_sentences(markdown):
    """Plain-text sentences from prose; code, tables, images, HTML and headings are dropped."""
    text = re.sub(r"```.*?```|~~~.*?~~~", " ", markdown, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if (not stripped or stripped.startswith(("#", "|", ">", "    ", "\t", "<", "![", "[!["))
                or re.fullmatch(r"[-*_=]{3,}", stripped)):
            kept.append("")
            continue
        stripped = re.sub(r"^([-*+]|\d+[.)])\s+", "", stripped)
        kept.append(stripped)
    text = "\n".join(kept)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\[\d+\]", "", text)
    sentences = []
    for paragraph in re.split(r"\n\s*\n|\n(?=[A-Z])", text):
        paragraph = " ".join(paragraph.split())
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9*])", paragraph):
            sentence = sentence.strip(" -:")
            words = sentence.split()
            if MIN_WORDS <= len(words) <= MAX_WORDS and re.search(r"[A-Za-z]", sentence):
                sentence = sentence.rstrip(":")
                if not sentence.endswith((".", "!", "?")):
                    sentence += "."
                if sentence not in sentences:
                    sentences.append(sentence)
    return sentences


def _score(sentence, slot):
    lower = sentence.lower()
    first = lower.split()[0].strip("*")
    if slot == "result":
        score = 3 * bool(NUMBER.search(sentence)) + sum(word in lower for word in RESULT_WORDS)
    elif slot == "action":
        score = 3 * (first in ACTION_VERBS) + sum(f" {verb} " in f" {lower} " for verb in ACTION_VERBS)
    else:
        score = sum(word in lower for word in CONTEXT_WORDS)
    return score - _penalty(sentence) if score > 0 else 0


def candidates(sentences, limit=5):
    """Rank README sentences for each RAC slot. A sentence may appear under several slots."""
    ranked = {}
    for slot in SLOTS:
        scored = [(_score(s, slot), index, s) for index, s in enumerate(sentences)]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked[slot] = [s for _, _, s in scored[:limit]]
    return ranked


def _choose(slot, options, current, ask, say):
    say("")
    say(f"== {SLOT_HELP[slot]} ==")
    if current:
        say(f"  [k] keep current: {current}")
    for number, option in enumerate(options, 1):
        say(f"  [{number}] {option}")
    if not options:
        say("  (no README sentence matched this slot)")
    say("  [e] write your own   [s] skip project (nothing saved)")
    while True:
        answer = ask("Choice: ").strip().lower()
        if answer == "s":
            return None
        if answer == "k" and current:
            return current
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            picked = options[int(answer) - 1]
            edited = ask("Edit (Enter keeps it as shown): ").strip()
            return edited or picked
        if answer == "e":
            written = ask("Bullet: ").strip()
            if written:
                return written
        say("  Please enter a listed number, e, s" + (", or k" if current else "") + ".")


def review(project_id, project, readme, ask=input, say=print):
    """Interactively pick one bullet per slot. Returns three bullets, or None if skipped/rejected."""
    options = candidates(readme_sentences(readme))
    current = project.get("bullets") or []
    say(f"\nDrafting RAC bullets for {project_id} ({project.get('github_repo')}).")
    say("Candidates are copied from the README. Add bold metrics with **...**; keep each to one line.")
    chosen = []
    for index, slot in enumerate(SLOTS):
        bullet = _choose(slot, options[slot], current[index] if index < len(current) else None, ask, say)
        if bullet is None:
            say("Skipped; config not changed.")
            return None
        chosen.append(bullet)
    say("\nProposed bullets:")
    for slot, bullet in zip(SLOTS, chosen):
        say(f"  {slot[0].upper()}: {bullet}")
        if len(bullet) > 125:
            say(f"     note: {len(bullet)} characters; likely too long for one line")
    if ask("Save these to config.yaml? [y/N]: ").strip().lower() != "y":
        say("Not saved; config not changed.")
        return None
    return chosen


def draft(config_path, config, project_ids, ask=input, say=print, fetch=fetch_readme):
    result = copy.deepcopy(config)
    projects = result["projects"]
    targets = project_ids or [key for key, value in projects.items()
                              if value.get("github_repo") and not value.get("bullets")]
    if not targets:
        say("No projects to draft. Name a project ID, or sync GitHub to import repositories.")
        return config
    changed = []
    for project_id in targets:
        if project_id not in projects:
            raise ConfigError(f"Unknown project ID: {project_id}. Run --list to see IDs")
        project = projects[project_id]
        if not project.get("github_repo"):
            say(f"{project_id}: no github_repo set; skipped")
            continue
        try:
            readme = fetch(project["github_repo"])
        except ConfigError as error:
            say(f"{project_id}: {error}")
            continue
        bullets = review(project_id, project, readme, ask, say)
        if bullets is None:
            continue
        project["bullets"] = bullets
        stamp = datetime.now(timezone.utc).date().isoformat()
        note = f"Bullets drafted from the GitHub README and approved on {stamp}."
        project["notes"] = (project.get("notes", "") + " " + note).strip()
        changed.append(project_id)
        if any(project["enabled"].values()):
            say("Note: this project is enabled; a profile override may still replace these bullets.")
        else:
            say(f"Saved, but {project_id} is still disabled. Set enabled.research/yc to true to use it.")
    if changed:
        save_config(config_path, result)
        say(f"\nUpdated config.yaml for: {', '.join(changed)}. Run python build.py --all -v to check line fit.")
        return result
    return config
