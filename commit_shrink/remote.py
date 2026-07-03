"""Resolve a repository "spec" -- a local path or a remote URL/shorthand --
into a local filesystem path that collector.collect() can read unmodified.

This is the RepoSource seam from plan-commit-shrink.md's Day 3-4 addendum:
analyzer.py, diagnoser.py, pipeline.py, and report.py stay completely
unaware that a repository might not already be on disk. Only this module,
and the small dispatch in cli.py/web_app.py that decides whether to use it,
know about URLs at all.

Remote specs are shallow-cloned into a temporary directory, bounded to the
assessment window (+ the same FETCH_PADDING collector.collect() itself uses)
via --shallow-since rather than a fixed commit count, so a single day's
activity in a huge repository and a whole week's activity in a quiet one
both fetch roughly the right amount of history. The clone always lives in a
TemporaryDirectory, so it is removed when the caller's `with` block exits,
success or failure.

Not detectable for a freshly cloned repository: history rewrites from
before the clone (GIT-88.8 degrades to its documented reflog-unavailable
copy, same as any repo without local reflog history -- no special-casing
needed). Also not covered: a commit whose author date falls inside the
assessment window but whose committer date is more than FETCH_PADDING in
the past (the rare case collector.GIT_WINDOW_SLACK exists to catch for
fully-cloned local repos) -- widening the shallow window to cover that too
would mean cloning ~30 extra days of history on every remote assessment,
defeating the point of a shallow clone. Tracked as a known, accepted
limitation in docs/bug_need_fix.md, not fixed here.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .pipeline import FETCH_PADDING, compute_window

CLONE_TIMEOUT_SECONDS = 60

_GITHUB_SHORTHAND_RE = re.compile(r"^github:([\w.-]+)/([\w.-]+?)(\.git)?/?$")
_URL_RE = re.compile(r"^(https?|git|ssh|file)://|^git@", re.IGNORECASE)


class CloneError(Exception):
    """A remote repository could not be cloned."""


class RemoteAuthorRequiredError(Exception):
    """A remote spec was given without --author to identify the patient."""


def is_remote_spec(spec: str) -> bool:
    return bool(_GITHUB_SHORTHAND_RE.match(spec) or _URL_RE.match(spec))


def require_author_for_remote(spec: str, author: str | None) -> None:
    """Refuse to guess a patient on a repository the caller doesn't own.

    assess_repo() picks "the dominant author in the period" when no
    --author is given, which is the right default for your own local repo
    but the wrong one for someone else's -- it would silently diagnose
    whoever committed the most that week, not the person you meant to look
    at (easily a bot, a maintainer merging others' PRs, etc).
    """
    if is_remote_spec(spec) and not (author and author.strip()):
        raise RemoteAuthorRequiredError(spec)


def _resolve_clone_url(spec: str) -> str:
    m = _GITHUB_SHORTHAND_RE.match(spec)
    if m:
        owner, repo = m.group(1), m.group(2)
        return f"https://github.com/{owner}/{repo}.git"
    return spec


@contextmanager
def local_repo(spec: str, days: int, until: datetime | None) -> Iterator[Path]:
    """Yield a local path for `spec`: itself if local, a fresh shallow clone
    if remote. `days`/`until` size the clone to the same window assess_repo()
    will use, via the shared compute_window() + FETCH_PADDING.
    """
    if not is_remote_spec(spec):
        yield Path(spec)
        return

    url = _resolve_clone_url(spec)
    start, _end = compute_window(days, until)
    since = start - FETCH_PADDING

    with tempfile.TemporaryDirectory(prefix="commit-shrink-") as tmp:
        args = [
            "git",
            "clone",
            "--quiet",
            "--single-branch",
            f"--shallow-since={since.isoformat()}",
            url,
            tmp,
        ]
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=CLONE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise CloneError(
                f"cloning {url} did not finish within {CLONE_TIMEOUT_SECONDS}s"
            )
        if proc.returncode != 0:
            raise CloneError(proc.stderr.strip() or f"git clone of {url} failed")
        yield Path(tmp)
