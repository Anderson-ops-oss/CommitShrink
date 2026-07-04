"""Resolve a GitHub username to its public repositories' clone URLs.

Stdlib only (urllib + json) -- no new dependency -- and works unauthenticated
for public data: GitHub's 60 requests/hour anonymous limit is plenty to list
one user's repos (a page or two). When private-repo support is added later, a
token slots in here as an Authorization header without changing the shape.

Scope (MVP): repositories the user *owns*. This misses contributions to repos
they don't own (that needs the commit-search API, which is heavily throttled
without a token); callers should surface the covered count so the boundary is
never silent.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import quote

API_ROOT = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 5  # safety bound; sort=pushed means active repos come first
DEFAULT_MAX_REPOS = 30
REQUEST_TIMEOUT_SECONDS = 15


class GitHubAPIError(Exception):
    """A GitHub API lookup failed (no such user, rate limit, network, ...)."""


def _parse_ts(value: str) -> datetime:
    # GitHub timestamps look like "2026-01-05T12:00:00Z"; 3.10's fromisoformat
    # doesn't accept the trailing "Z", so normalize it to an explicit offset.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _get_json(url: str) -> list:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "commit-shrink",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise GitHubAPIError("no such GitHub user") from e
        if e.code in (403, 429):
            raise GitHubAPIError(
                "GitHub API rate limit reached (try again later, or with a token)"
            ) from e
        raise GitHubAPIError(f"GitHub API returned HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GitHubAPIError(f"could not reach the GitHub API: {e}") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise GitHubAPIError("GitHub API returned an unreadable response") from e


def list_user_public_repos(
    username: str,
    since: datetime | None = None,
    *,
    max_repos: int = DEFAULT_MAX_REPOS,
) -> list[str]:
    """Clone URLs of `username`'s owned public repos, most-recently-pushed first.

    If `since` is given, repos not pushed since then are skipped -- and because
    results are sorted by push time descending, scanning stops at the first
    older repo. Capped at `max_repos` (a busy user's older repos are dropped;
    callers report the covered count so the cap isn't silent).
    """
    urls: list[str] = []
    user = quote(username, safe="")
    for page in range(1, MAX_PAGES + 1):
        url = (
            f"{API_ROOT}/users/{user}/repos"
            f"?per_page={PER_PAGE}&type=owner&sort=pushed&direction=desc&page={page}"
        )
        repos = _get_json(url)
        if not isinstance(repos, list) or not repos:
            break
        for repo in repos:
            pushed = repo.get("pushed_at")
            if since is not None:
                if not pushed:
                    # Never-pushed / unknown push time: outside the window, so
                    # skip it (don't waste a clone) -- but keep scanning, since
                    # a null pushed_at isn't guaranteed to sort last.
                    continue
                if _parse_ts(pushed) < since:
                    return urls  # sorted desc: everything after this is older too
            clone_url = repo.get("clone_url")
            if clone_url:
                urls.append(clone_url)
                if len(urls) >= max_repos:
                    return urls
        if len(repos) < PER_PAGE:
            break
    return urls
