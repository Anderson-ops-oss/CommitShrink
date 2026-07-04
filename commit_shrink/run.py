"""One entry point that turns any spec into an (Assessment, Trend) pair.

Keeps the "which kind of spec is this?" branching in a single place so the CLI
and the Streamlit app share identical resolve -> clone -> assess -> record
behavior. The heavy, blocking work (cloning, git log) happens here, so callers
run it on the worker thread behind the rotating status messages.

- a local path or single remote repo  -> local_repo + assess_repo
- a `gh-user:<name>` spec              -> discover the user's public repos,
  clone them all, and assess_repos() them as one merged, person-anchored
  timeline (see history.user_fingerprint).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import history
from .github_api import list_user_public_repos
from .history import Trend
from .pipeline import Assessment, assess_repo, assess_repos, compute_window
from .remote import (
    is_remote_spec,
    is_user_spec,
    local_repo,
    local_repos,
    parse_user_spec,
)


class NoReposError(Exception):
    """A gh-user spec resolved to no assessable public repos in the window."""


@dataclass
class RunResult:
    assessment: Assessment
    trend: Trend
    repo_count: int  # repos actually assessed (1 for a single spec)
    discovered_count: int | None  # repos discovered for a gh-user spec, else None


def run_assessment(
    spec: str,
    days: int,
    until: datetime | None,
    author: str | None,
    cfg: dict,
) -> RunResult:
    if is_user_spec(spec):
        return _run_user(spec, days, until, author, cfg)
    return _run_single(spec, days, until, author, cfg)


def _run_single(spec, days, until, author, cfg) -> RunResult:
    with local_repo(spec, days=days, until=until, author=author) as repo:
        ctx = history.load_context([repo])
        assessment = assess_repo(
            repo, days=days, until=until, author=author,
            cfg=cfg, techdebt_history=ctx.techdebt_index,
        )
        source = "remote" if is_remote_spec(spec) else "local"
        trend = history.finalize(ctx, assessment, [repo], source=source)
    return RunResult(assessment, trend, repo_count=1, discovered_count=None)


def _run_user(spec, days, until, author, cfg) -> RunResult:
    username = parse_user_spec(spec)
    start, _end = compute_window(days, until)
    urls = list_user_public_repos(username, since=start)  # may raise GitHubAPIError
    if not urls:
        raise NoReposError(username)
    with local_repos(urls, days=days, until=until, author=author) as repos:
        if not repos:  # every clone failed/timed out
            raise NoReposError(username)
        fingerprint = history.user_fingerprint(username)
        ctx = history.load_context(repos, fingerprint_override=fingerprint)
        assessment = assess_repos(
            repos, days=days, until=until, author=author,
            cfg=cfg, techdebt_history=ctx.techdebt_index,
        )
        # patient_scoped=False: the fingerprint is already person-specific
        # (user:<name>), and the volume-dominant email can drift week to week,
        # so match prior periods by fingerprint alone to keep the trend intact.
        trend = history.finalize(ctx, assessment, repos, source="remote", patient_scoped=False)
    return RunResult(assessment, trend, repo_count=len(repos), discovered_count=len(urls))
