"""Configuration, legacy migration, and public GitHub project discovery."""
import copy
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import yaml

PROFILES = ("research", "yc")
PERSON_FIELDS = ("name", "email", "phone", "website", "logo", "photo")
SECTIONS = ("projects", "education", "skills", "achievements", "leadership",
            "highlights", "links", "research_interests", "logo", "photo")
HEADER = """# Single source of truth for both CVs.
# projects.<id>.enabled.research / enabled.yc: true includes, false excludes.
# Use real YAML booleans, not quoted "true" or "false".
# profiles.<profile>.sections switches whole sections; individual entries use enabled.
# GitHub refresh preserves editorial fields and switches; new repositories start disabled.
# Edit this file, then run: python build.py --all
"""


class ConfigError(ValueError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConfigError("Configuration mapping keys must be strings")
        if key in mapping:
            raise ConfigError(f"Duplicate configuration key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def require_mapping(value, where):
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    return value


def require_boolean(value, where):
    if type(value) is not bool:
        raise ConfigError(f"{where} must be true or false (not quoted)")
    return value


def validate_config(config):
    require_mapping(config, "config")
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise ConfigError("schema_version must be 1")
    github = require_mapping(config.get("github"), "github")
    if not isinstance(github.get("username"), str):
        raise ConfigError("github.username must be text")
    person = require_mapping(config.get("person"), "person")
    for field in PERSON_FIELDS:
        if not isinstance(person.get(field), str):
            raise ConfigError(f"person.{field} must be text (empty text is allowed)")
    profiles = require_mapping(config.get("profiles"), "profiles")
    projects = require_mapping(config.get("projects"), "projects")
    for profile in PROFILES:
        settings = require_mapping(profiles.get(profile), f"profiles.{profile}")
        sections = require_mapping(settings.get("sections"), f"profiles.{profile}.sections")
        if set(sections) != set(SECTIONS):
            raise ConfigError(f"profiles.{profile}.sections must contain: {', '.join(SECTIONS)}")
        for section, enabled in sections.items():
            require_boolean(enabled, f"profiles.{profile}.sections.{section}")
        for key in ("headline", "summary", "research_interests"):
            if not isinstance(settings.get(key, ""), str):
                raise ConfigError(f"profiles.{profile}.{key} must be text")
        layout = require_mapping(settings.get("layout", {}), f"profiles.{profile}.layout")
        if any(not isinstance(value, str) for value in layout.values()):
            raise ConfigError(f"profiles.{profile}.layout values must be LaTeX dimension strings")
        order = settings.get("project_order")
        if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
            raise ConfigError(f"profiles.{profile}.project_order must be a list of project IDs")
        if len(order) != len(set(order)) or set(order) - projects.keys():
            raise ConfigError(f"profiles.{profile}.project_order has duplicate or unknown project IDs")
        for section in ("links", "skills", "achievements", "leadership", "highlights", "education"):
            entries = settings.get(section, [])
            if not isinstance(entries, list):
                raise ConfigError(f"profiles.{profile}.{section} must be a list")
            for i, entry in enumerate(entries):
                where = f"profiles.{profile}.{section}[{i}]"
                require_mapping(entry, where)
                require_boolean(entry.get("enabled"), f"{where}.enabled")
                fields = {
                    "links": ("label", "url"), "skills": ("name", "text"),
                    "achievements": ("title", "text", "year"), "leadership": ("title", "text", "year"),
                    "highlights": ("text",),
                    "education": (("institute", "degree", "graduation") if profile == "yc"
                                  else ("year", "degree", "institute", "score")),
                }[section]
                for field in fields:
                    if not isinstance(entry.get(field), str):
                        raise ConfigError(f"{where}.{field} must be text; quote numeric values")
    for project_id, entry in projects.items():
        require_mapping(entry, f"projects.{project_id}")
        if not isinstance(entry.get("github_repo", ""), str):
            raise ConfigError(f"projects.{project_id}.github_repo must be text")
        require_mapping(entry.get("github", {}), f"projects.{project_id}.github")
        enabled = require_mapping(entry.get("enabled"), f"projects.{project_id}.enabled")
        if set(enabled) != set(PROFILES):
            raise ConfigError(f"projects.{project_id}.enabled must contain research and yc")
        for profile, value in enabled.items():
            require_boolean(value, f"projects.{project_id}.enabled.{profile}")
        overrides = require_mapping(entry.get("overrides", {}), f"projects.{project_id}.overrides")
        if set(overrides) - set(PROFILES):
            raise ConfigError(f"projects.{project_id}.overrides contains an unknown profile")
        for profile, values in overrides.items():
            require_mapping(values, f"projects.{project_id}.overrides.{profile}")
            if set(values) - {"title", "url", "dates", "advisor", "course", "bullets"}:
                raise ConfigError(f"projects.{project_id}.overrides.{profile} has unsupported fields")
    return config


def load_config(path):
    try:
        config = yaml.load(Path(path).read_text(encoding="utf-8-sig"), Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    return validate_config(config)


def save_config(path, config):
    validate_config(config)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".yaml.tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(HEADER)
            yaml.safe_dump(config, stream, sort_keys=False, allow_unicode=True, width=150)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def selected_items(settings, section):
    if not settings["sections"][section]:
        return []
    return [
        {key: value for key, value in item.items() if key != "enabled"}
        for item in settings.get(section, []) if item["enabled"]
    ]


def prepare_profile(config, profile):
    validate_config(config)
    if profile not in PROFILES:
        raise ConfigError(f"Unknown profile: {profile}")
    settings = config["profiles"][profile]
    data = copy.deepcopy(config["person"])
    for key in ("headline", "summary", "research_interests", "layout"):
        data[key] = copy.deepcopy(settings.get(key, {} if key == "layout" else ""))
    for key in ("logo", "photo", "research_interests"):
        if not settings["sections"][key]:
            data[key] = ""
    for key in ("links", "achievements", "leadership"):
        data[key] = selected_items(settings, key)
    skills = selected_items(settings, "skills")
    if len({s["name"] for s in skills}) != len(skills):
        raise ConfigError(f"profiles.{profile}.skills contains duplicate enabled names")
    data["skills"] = {item["name"]: item["text"] for item in skills}
    data["highlights"] = [item["text"] for item in selected_items(settings, "highlights")]
    education = selected_items(settings, "education")
    if profile == "yc" and len(education) > 1:
        raise ConfigError("The YC template supports one education entry; disable the additional entries")
    data["education"] = (education[0] if education else None) if profile == "yc" else education
    data["projects"] = []
    if settings["sections"]["projects"]:
        order = settings["project_order"]
        order = order + [key for key in config["projects"] if key not in order]
        for project_id in order:
            project = config["projects"][project_id]
            if not project["enabled"][profile]:
                continue
            resolved = {key: copy.deepcopy(project.get(key, "")) for key in
                        ("title", "url", "dates", "advisor", "course", "bullets")}
            resolved.update(copy.deepcopy(project.get("overrides", {}).get(profile, {})))
            bullets = resolved["bullets"]
            if not isinstance(bullets, list) or len(bullets) != 3 or not all(
                isinstance(bullet, str) and bullet.strip() for bullet in bullets
            ):
                raise ConfigError(
                    f"projects.{project_id}: supply three reviewed RAC bullets before enabling {profile}"
                )
            for key in ("title", "url", "dates", "advisor", "course"):
                if not isinstance(resolved[key], str):
                    raise ConfigError(f"projects.{project_id}.{key} must be text")
            if not resolved["title"].strip():
                raise ConfigError(f"projects.{project_id}.title cannot be empty")
            resolved["id"] = project_id
            data["projects"].append(resolved)
    return data


def fetch_public_repos(username):
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        raise ConfigError("github.username must be a valid GitHub username")
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{quote(username)}/repos?per_page=100&type=owner&sort=full_name&page={page}"
        request = Request(url, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "Dynamic-CV",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urlopen(request, timeout=30) as response:
                batch = json.load(response)
        except HTTPError as error:
            raise ConfigError(
                f"GitHub returned HTTP {error.code}. Check username/rate limits; config was not changed"
            ) from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise ConfigError(f"GitHub refresh failed; config was not changed: {error}") from error
        if not isinstance(batch, list):
            raise ConfigError("GitHub returned an unexpected response; config was not changed")
        repos.extend(batch)
        if len(batch) < 100:
            return repos
        page += 1


def merge_repositories(config, repositories, fetched_at):
    result = copy.deepcopy(config)
    projects = result["projects"]
    added = []
    for repo in repositories:
        required = {"id", "name", "full_name", "html_url"}
        if not isinstance(repo, dict) or not required <= repo.keys():
            raise ConfigError("GitHub repository metadata is incomplete; config was not changed")
        if type(repo["id"]) is not int or not all(
            isinstance(repo[key], str) and repo[key] for key in ("name", "full_name", "html_url")
        ):
            raise ConfigError("GitHub repository metadata has invalid types; config was not changed")
        full_name = repo["full_name"]
        matches = [
            item for item in projects.values()
            if item.get("github_repo", "").casefold() == full_name.casefold()
            or item.get("github", {}).get("id") == repo["id"]
        ]
        if len(matches) > 1:
            raise ConfigError(f"Multiple projects are linked to {full_name}; resolve before refreshing")
        if matches:
            project = matches[0]
            old_url = project.get("github", {}).get("html_url", "https://github.com/" + project["github_repo"])
            if project.get("url") == old_url:
                project["url"] = repo["html_url"]
        else:
            project_id = re.sub(r"[^a-z0-9-]+", "-", repo["name"].lower()).strip("-")
            if project_id in projects:
                project_id += f"-{repo['id']}"
            project = {
                "enabled": {profile: False for profile in PROFILES},
                "github_repo": full_name, "title": repo["name"], "url": repo["html_url"],
                "dates": "", "bullets": [],
                "notes": "Imported from GitHub. Add three evidence-based RAC bullets before enabling.",
                "overrides": {},
            }
            projects[project_id] = project
            added.append(project_id)
        project["github_repo"] = full_name
        project["github"] = {key: repo.get(key) for key in (
            "id", "full_name", "html_url", "description", "language", "stargazers_count",
            "forks_count", "fork", "archived", "created_at", "pushed_at", "default_branch",
        )}
        project["github"]["fetched_at"] = fetched_at
    result["github"]["last_synced_at"] = fetched_at
    return validate_config(result), added


def sync_github(path, config):
    github = require_mapping(config.get("github"), "github")
    repositories = fetch_public_repos(github.get("username"))
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result, added = merge_repositories(config, repositories, timestamp)
    save_config(path, result)
    print(f"Refreshed {len(repositories)} public repositories; added {len(added)} disabled entries.")
    if added:
        print("New projects: " + ", ".join(added))
    return result


def migrate_legacy(root):
    """One-time migration, retaining each profile's wording and ordering."""
    root = Path(root)
    target = root / "config.yaml"
    if target.exists():
        raise ConfigError("config.yaml already exists; migration will not overwrite it")
    legacy = {
        profile: yaml.safe_load((root / name).read_text(encoding="utf-8-sig"))
        for profile, name in (("research", "cv.yaml"), ("yc", "yc.yaml"))
    }
    result = {
        "schema_version": 1, "github": {"username": "Avinashistoocool"},
        "person": {key: legacy["research"].get(key, "") for key in PERSON_FIELDS},
        "profiles": {}, "projects": {},
    }
    identities = {}
    for profile, old in legacy.items():
        settings = {key: copy.deepcopy(value) for key, value in old.items()
                    if key not in PERSON_FIELDS and key != "projects"}
        settings["sections"] = {key: bool(old.get(key)) for key in SECTIONS}
        settings["project_order"] = []
        for section in ("links", "achievements", "leadership", "education"):
            items = old.get(section, [])
            if isinstance(items, dict):
                items = [items]
            settings[section] = [
                {"enabled": not item.get("hidden", False),
                 **{key: value for key, value in item.items() if key != "hidden"}}
                for item in items
            ]
        settings["skills"] = [
            {"enabled": True, "name": name, "text": text} for name, text in old.get("skills", {}).items()
        ]
        settings["highlights"] = [{"enabled": True, "text": text} for text in old.get("highlights", [])]
        for project in old["projects"]:
            identity = project["url"] or "medial-axis"
            if identity not in identities:
                if urlparse(identity).hostname == "github.com":
                    github_repo = urlparse(identity).path.strip("/")
                    project_id = github_repo.split("/")[-1].lower()
                else:
                    github_repo = ""
                    project_id = "medial-axis" if not project["url"] else "ultrasonic-radar"
                identities[identity] = project_id
                result["projects"][project_id] = {
                    "enabled": {name: False for name in PROFILES},
                    "github_repo": github_repo,
                    **{key: copy.deepcopy(value) for key, value in project.items() if key != "hidden"},
                    "overrides": {},
                }
            project_id = identities[identity]
            shared = result["projects"][project_id]
            shared["enabled"][profile] = not project.get("hidden", False)
            overrides = {key: value for key, value in project.items()
                         if key != "hidden" and value != shared.get(key)}
            if overrides:
                shared["overrides"][profile] = overrides
            settings["project_order"].append(project_id)
        result["profiles"][profile] = settings
    save_config(target, result)
    return result
