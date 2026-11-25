"""Refresh README badges from public GitHub issues and pull requests."""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


REPO = r"s4na/[A-Za-z0-9_-][A-Za-z0-9_.-]*"
URL = rf"https://github\.com/({REPO})"
PLAIN = re.compile(rf"^(?:\s*[*+-]\s+)?{URL}/?\s*$")
MANAGED = re.compile(rf"^\* \[[^\]]+\]\({URL}\) .* <!-- profile-badges -->$")


def render_row(repo):
    name = repo.split("/")[1]
    base = quote(f"repo:{repo} is:open sort:updated-asc", safe="")
    issues = f"https://github.com/issues?q={base}%20is%3Aissue"
    pulls = f"https://github.com/pulls?q={base}%20is%3Apr%20-is%3Adraft%20-author%3Aapp%2Fdependabot"
    return (
        f"* [{name}](https://github.com/{repo}) "
        f"[![Issue 30d+](badges/{name}-issues.svg)]({issues}) "
        f"[![PR 14d+](badges/{name}-prs.svg)]({pulls}) <!-- profile-badges -->"
    )


def render_readme(readme):
    repos = {}
    lines = []
    for line in readme.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        match = PLAIN.fullmatch(text) or MANAGED.fullmatch(text)
        if match:
            repo = match[1]
            repos[repo] = None
            line = render_row(repo) + line[len(text):]
        lines.append(line)
    return list(repos), "".join(lines)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(path, token):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "s4na-profile-badges"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with build_opener(NoRedirect()).open(
        Request(f"https://api.github.com/{path}", headers=headers), timeout=20
    ) as response:
        return json.load(response)


def open_items(repo, kind, token):
    page = 1
    while True:
        batch = get(f"repos/{repo}/{kind}?state=open&per_page=100&page={page}", token)
        if not isinstance(batch, list):
            raise ValueError(f"{repo}/{kind}: expected a list")
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def eligible(item, kind):
    if kind == "issues":
        return "pull_request" not in item
    return not item["draft"] and (item.get("user") or {}).get("login", "").lower() not in {
        "dependabot[bot]", "dependabot-preview[bot]"
    }


def staleness(items, kind, now, threshold):
    ages = []
    for item in items:
        if not eligible(item, kind):
            continue
        updated = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
        age = (now - updated).days
        if age >= threshold:
            ages.append(age)
    return len(ages), max(ages, default=0)


def badge(label, message, color):
    width = 89 + 7 * max(9, len(message))
    right = (width + 82) / 2
    title = escape(f"{label}: {message}")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="22" role="img" aria-label="{title}">
  <title>{title}</title>
  <rect width="{width}" height="22" rx="4" fill="{color}"/>
  <path d="M4 0h78v22H4a4 4 0 0 1-4-4V4a4 4 0 0 1 4-4Z" fill="#343d48"/>
  <g fill="white" text-anchor="middle" dominant-baseline="middle" font-family="Arial, sans-serif" font-size="11">
    <text x="41" y="11">{escape(label)}</text>
    <text x="{right}" y="11">{escape(message)}</text>
  </g>
</svg>
'''


def collect(repos, token, now):
    result = {}
    for repo in repos:
        try:
            info = get(f"repos/{repo}", token)
        except HTTPError as error:
            if error.code not in {301, 404, 410}:
                raise
            info = {}
        public = info.get("private") is False
        for kind, endpoint, label, days, severe in (
            ("issues", "issues", "Issue 30d+", 30, 90),
            ("prs", "pulls", "PR 14d+", 14, 30),
        ):
            if not public or (kind == "issues" and not info["has_issues"]):
                message, color = "N/A", "#57606a"
            else:
                count, oldest = staleness(open_items(repo, endpoint, token), kind, now, days)
                message = f"{count} · max {oldest}d" if count else "0"
                color = "#b42318" if oldest >= severe else "#8a4b00" if count else "#3d5261"
            result[f"{repo.split('/')[1]}-{kind}.svg"] = badge(label, message, color)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("badges"))
    parser.add_argument("--write-readme", action="store_true")
    args = parser.parse_args()
    readme_path = Path("README.md")
    before = readme_path.read_text(encoding="utf-8")
    repos, rendered = render_readme(before)
    if not repos:
        raise ValueError("No s4na repository URLs found in README.md")
    # Do not overwrite existing badges with zeroes on an API error.
    files = collect(repos, os.environ.get("GH_TOKEN"), datetime.now(timezone.utc))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.output / name).write_text(content, encoding="utf-8")
    for path in args.output.glob("*.svg"):
        if re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*-(issues|prs)\.svg", path.name) and path.name not in files:
            path.unlink()
    if args.write_readme and rendered != before:
        readme_path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
