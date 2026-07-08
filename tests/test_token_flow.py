"""The web form can supply a GitHub token per-call. That token must take
precedence over the environment, fall back to the environment when absent, and
crucially must NOT be written to os.environ -- a shared, multi-user hosted
process would otherwise leak one visitor's token into another's request.
"""

from __future__ import annotations

import os

import pytest

from commit_shrink import run as run_mod
from commit_shrink.pipeline import load_config
from commit_shrink.run import NoReposError, run_assessment


@pytest.fixture
def captured(monkeypatch):
    """Stub the GitHub API calls _run_user makes so no network is needed and we
    can record which token reached them. Returning [] short-circuits to
    NoReposError before any clone is attempted."""
    seen: dict[str, str | None] = {}

    def fake_login(token):
        seen["login_token"] = token
        return "me"

    def fake_authed_repos(token, since=None):
        seen["repos_token"] = token
        return []

    def fake_public_repos(username, since=None, token=None):
        seen["public_token"] = token
        return []

    monkeypatch.setattr(run_mod, "get_authenticated_login", fake_login)
    monkeypatch.setattr(run_mod, "list_authenticated_user_repos", fake_authed_repos)
    monkeypatch.setattr(run_mod, "list_user_public_repos", fake_public_repos)
    return seen


def _cfg():
    return load_config("en")


def _assess(spec, **kw):
    return run_assessment(spec, days=7, until=None, author="a@b.c", cfg=_cfg(), **kw)


def test_explicit_token_beats_env(monkeypatch, captured):
    monkeypatch.setattr(run_mod, "get_token", lambda: "ENV")
    with pytest.raises(NoReposError):
        _assess("gh-user:@me", token="EXPLICIT")
    assert captured["login_token"] == "EXPLICIT"
    assert captured["repos_token"] == "EXPLICIT"


def test_falls_back_to_env_when_no_explicit_token(monkeypatch, captured):
    monkeypatch.setattr(run_mod, "get_token", lambda: "ENV")
    with pytest.raises(NoReposError):
        _assess("gh-user:@me")
    assert captured["repos_token"] == "ENV"


def test_token_argument_is_never_written_to_environ(monkeypatch, captured):
    monkeypatch.setattr(run_mod, "get_token", lambda: None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(NoReposError):
        _assess("gh-user:@me", token="SECRET")
    assert captured["repos_token"] == "SECRET"  # it did reach the API call
    # ...but only as an argument -- the process environment stays clean.
    assert "SECRET" not in os.environ.values()
    assert os.environ.get("GITHUB_TOKEN") is None
    assert os.environ.get("GH_TOKEN") is None


def test_public_user_forwards_token_for_rate_limit(monkeypatch, captured):
    monkeypatch.setattr(run_mod, "get_token", lambda: None)
    with pytest.raises(NoReposError):
        _assess("gh-user:octocat", token="RATELIMIT")
    assert captured["public_token"] == "RATELIMIT"
