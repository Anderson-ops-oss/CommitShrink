"""Tests for commit_shrink.github_api -- fully offline (urlopen is stubbed).

Exercises repo-URL parsing, the pushed_at window filter (and the sorted-desc
early stop), the max_repos cap, and the clinical mapping of 404 / rate-limit
responses to GitHubAPIError.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone

import pytest

from commit_shrink import github_api
from commit_shrink.github_api import GitHubAPIError, list_user_public_repos


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")
        self.headers = {}

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch(monkeypatch, payload=None, error=None):
    def fake_urlopen(req, timeout=None):
        if error is not None:
            raise error
        return _FakeResp(payload)

    monkeypatch.setattr(github_api.urllib.request, "urlopen", fake_urlopen)


def _repo(name, pushed):
    return {"clone_url": f"https://github.com/u/{name}.git", "pushed_at": pushed}


def test_parses_clone_urls_in_order(monkeypatch):
    _patch(monkeypatch, [_repo("a", "2026-02-01T00:00:00Z"), _repo("b", "2026-01-15T00:00:00Z")])
    assert list_user_public_repos("u") == [
        "https://github.com/u/a.git",
        "https://github.com/u/b.git",
    ]


def test_since_stops_at_first_older_repo(monkeypatch):
    _patch(
        monkeypatch,
        [
            _repo("a", "2026-02-01T00:00:00Z"),
            _repo("b", "2026-01-15T00:00:00Z"),
            _repo("c", "2025-06-01T00:00:00Z"),  # older than since -> stop here
        ],
    )
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert list_user_public_repos("u", since=since) == [
        "https://github.com/u/a.git",
        "https://github.com/u/b.git",
    ]


def test_caps_at_max_repos(monkeypatch):
    _patch(monkeypatch, [_repo(n, "2026-02-01T00:00:00Z") for n in "abcd"])
    assert len(list_user_public_repos("u", max_repos=2)) == 2


def test_404_maps_to_no_such_user(monkeypatch):
    _patch(monkeypatch, error=urllib.error.HTTPError("http://x", 404, "Not Found", {}, None))
    with pytest.raises(GitHubAPIError, match="no such GitHub user"):
        list_user_public_repos("nope")


def test_rate_limit_maps_to_clinical_error(monkeypatch):
    _patch(monkeypatch, error=urllib.error.HTTPError("http://x", 403, "rate", {}, None))
    with pytest.raises(GitHubAPIError, match="rate limit"):
        list_user_public_repos("u")


def test_network_failure_maps_to_error(monkeypatch):
    _patch(monkeypatch, error=urllib.error.URLError("no route"))
    with pytest.raises(GitHubAPIError, match="could not reach"):
        list_user_public_repos("u")


def test_null_pushed_at_skipped_when_since_set(monkeypatch):
    # A never-pushed repo (pushed_at=null) must not bypass the window filter and
    # get cloned; and a null in the middle must not early-stop the scan.
    _patch(
        monkeypatch,
        [
            _repo("live", "2026-02-01T00:00:00Z"),
            {"clone_url": "https://github.com/u/empty.git", "pushed_at": None},
            _repo("also", "2026-01-20T00:00:00Z"),
        ],
    )
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    urls = list_user_public_repos("u", since=since)
    assert urls == ["https://github.com/u/live.git", "https://github.com/u/also.git"]


def test_null_pushed_at_kept_when_no_since(monkeypatch):
    _patch(monkeypatch, [{"clone_url": "https://github.com/u/empty.git", "pushed_at": None}])
    assert list_user_public_repos("u") == ["https://github.com/u/empty.git"]


def _capture_auth(monkeypatch, payload):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = next(
            (v for k, v in req.headers.items() if k.lower() == "authorization"), None
        )
        return _FakeResp(payload)

    monkeypatch.setattr(github_api.urllib.request, "urlopen", fake_urlopen)
    return captured


def test_token_adds_bearer_header(monkeypatch):
    captured = _capture_auth(monkeypatch, [])
    list_user_public_repos("u", token="tok123")
    assert captured["auth"] == "Bearer tok123"


def test_no_token_no_auth_header(monkeypatch):
    captured = _capture_auth(monkeypatch, [])
    list_user_public_repos("u")
    assert captured["auth"] is None


def test_authenticated_user_repos_parses(monkeypatch):
    _patch(monkeypatch, [_repo("a", "2026-02-01T00:00:00Z"), _repo("b", "2026-01-15T00:00:00Z")])
    assert github_api.list_authenticated_user_repos("tok") == [
        "https://github.com/u/a.git",
        "https://github.com/u/b.git",
    ]


def test_get_authenticated_login(monkeypatch):
    _patch(monkeypatch, {"login": "octocat"})
    assert github_api.get_authenticated_login("tok") == "octocat"


def test_401_maps_to_token_error(monkeypatch):
    _patch(monkeypatch, error=urllib.error.HTTPError("http://x", 401, "unauth", {}, None))
    with pytest.raises(GitHubAPIError, match="invalid or expired"):
        github_api.list_authenticated_user_repos("badtok")


def test_public_lookup_retries_anonymously_on_401(monkeypatch):
    # An expired token must not block a lookup that works anonymously.
    seen = []

    def fake_urlopen(req, timeout=None):
        auth = next((v for k, v in req.headers.items() if k.lower() == "authorization"), None)
        seen.append(auth)
        if auth:
            raise urllib.error.HTTPError("http://x", 401, "unauth", {}, None)
        return _FakeResp([_repo("a", "2026-02-01T00:00:00Z")])

    monkeypatch.setattr(github_api.urllib.request, "urlopen", fake_urlopen)
    urls = list_user_public_repos("u", token="expired")
    assert urls == ["https://github.com/u/a.git"]
    assert seen[0] is not None and seen[-1] is None  # tried token, then anonymous


def test_authenticated_lookup_does_not_retry_on_401(monkeypatch):
    # @me can't fall back to anonymous, so a bad token must surface.
    _patch(monkeypatch, error=urllib.error.HTTPError("http://x", 401, "unauth", {}, None))
    with pytest.raises(GitHubAPIError, match="invalid or expired"):
        github_api.list_authenticated_user_repos("expired")


def test_get_token_env_precedence(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert github_api.get_token() is None
    monkeypatch.setenv("GH_TOKEN", "z")
    assert github_api.get_token() == "z"
    monkeypatch.setenv("GITHUB_TOKEN", "a")
    assert github_api.get_token() == "a"  # GITHUB_TOKEN wins
