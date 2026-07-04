"""Resolve GitHub usernames to repository clone URLs (stdlib only).

Anonymous by default -- fine for public data, but GitHub's 60 req/hour per-IP
anonymous limit is easily exhausted on a shared/NAT'd network. A token (read
from GITHUB_TOKEN / GH_TOKEN, never a CLI arg) lifts that to 5000 req/hour
per-account and, for the authenticated user, unlocks their PRIVATE repos:

- list_user_public_repos(name)  -> that user's OWNED PUBLIC repos. A token here
  only lifts the rate limit; it never exposes another user's private repos
  (GitHub enforces that server-side).
- list_authenticated_user_repos(token) -> the token owner's OWNED repos,
  PUBLIC + PRIVATE (needs a token with repo-contents read).

Cloning private repos also needs auth; that is handled in collector.git_auth_env
(passed to git via env, so the token never lands in a URL or argv).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Callable
from urllib.parse import quote

API_ROOT = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 5  # safety bound; sort=pushed means active repos come first
DEFAULT_MAX_REPOS = 30
REQUEST_TIMEOUT_SECONDS = 15


class GitHubAPIError(Exception):
    """A GitHub API lookup failed (no such user, bad token, rate limit, ...).

    `status` carries the HTTP code when the failure was an HTTP error (so
    callers can, e.g., fall back to anonymous on a 401), else None.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def get_token() -> str | None:
    """The GitHub token from the environment, or None. Env only -- never a CLI
    argument -- so it can't leak into shell history or `ps` output."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def _parse_ts(value: str) -> datetime:
    # GitHub timestamps look like "2026-01-05T12:00:00Z"; 3.10's fromisoformat
    # doesn't accept the trailing "Z", so normalize it to an explicit offset.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _get_json(url: str, token: str | None = None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "commit-shrink",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise GitHubAPIError("GitHub token is invalid or expired", status=401) from e
        if e.code == 404:
            raise GitHubAPIError("no such GitHub user", status=404) from e
        if e.code in (403, 429):
            raise GitHubAPIError(
                "GitHub API rate limit reached (try again later, or with a token)", status=e.code
            ) from e
        raise GitHubAPIError(f"GitHub API returned HTTP {e.code}", status=e.code) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GitHubAPIError(f"could not reach the GitHub API: {e}") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise GitHubAPIError("GitHub API returned an unreadable response") from e


def _list_repos(
    url_for_page: Callable[[int], str],
    since: datetime | None,
    max_repos: int,
    token: str | None,
) -> list[str]:
    """Paginate a repos endpoint, newest-push first, applying the pushed_at
    window filter and the max_repos cap. Shared by the public and
    authenticated listings, which differ only in the endpoint URL."""
    urls: list[str] = []
    for page in range(1, MAX_PAGES + 1):
        repos = _get_json(url_for_page(page), token=token)
        if not isinstance(repos, list) or not repos:
            break
        for repo in repos:
            pushed = repo.get("pushed_at")
            if since is not None:
                if not pushed:
                    # Never-pushed / unknown push time: outside the window, so
                    # skip (don't waste a clone) but keep scanning -- a null
                    # pushed_at isn't guaranteed to sort last.
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


def list_user_public_repos(
    username: str,
    since: datetime | None = None,
    *,
    max_repos: int = DEFAULT_MAX_REPOS,
    token: str | None = None,
) -> list[str]:
    """Clone URLs of `username`'s owned PUBLIC repos, most-recently-pushed
    first. A token only lifts the rate limit here -- it never returns another
    user's private repos."""
    user = quote(username, safe="")

    def url_for_page(page: int) -> str:
        return (
            f"{API_ROOT}/users/{user}/repos"
            f"?per_page={PER_PAGE}&type=owner&sort=pushed&direction=desc&page={page}"
        )

    try:
        return _list_repos(url_for_page, since, max_repos, token)
    except GitHubAPIError as e:
        if token and e.status == 401:
            # An expired/revoked token must not block a lookup that works
            # anonymously -- this endpoint is public. Retry without it (losing
            # only the rate-limit lift).
            return _list_repos(url_for_page, since, max_repos, None)
        raise


def list_authenticated_user_repos(
    token: str,
    since: datetime | None = None,
    *,
    max_repos: int = DEFAULT_MAX_REPOS,
) -> list[str]:
    """Clone URLs of the token owner's OWNED repos, PUBLIC + PRIVATE, most-
    recently-pushed first. Requires a token with repo-contents read."""

    def url_for_page(page: int) -> str:
        return (
            f"{API_ROOT}/user/repos"
            f"?per_page={PER_PAGE}&affiliation=owner&visibility=all"
            f"&sort=pushed&direction=desc&page={page}"
        )

    return _list_repos(url_for_page, since, max_repos, token)


def get_authenticated_login(token: str) -> str:
    """The token owner's GitHub login (used to anchor the aggregate's history
    trend for `gh-user:@me`)."""
    data = _get_json(f"{API_ROOT}/user", token=token)
    login = data.get("login") if isinstance(data, dict) else None
    if not login:
        raise GitHubAPIError("could not resolve the authenticated user")
    return login
