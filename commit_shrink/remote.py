"""Resolve a repository "spec" -- a local path or a remote URL/shorthand --
into a local filesystem path that collector.collect() can read unmodified.

This is the RepoSource seam from plan-commit-shrink.md's Day 3-4 addendum:
analyzer.py, diagnoser.py, pipeline.py, and report.py stay completely
unaware that a repository might not already be on disk. Only this module,
and the small dispatch in cli.py/web_app.py that decides whether to use it,
know about URLs at all.

Remote specs are cloned with `--filter=blob:none --no-checkout` (a blobless
partial clone): git downloads only commit and tree objects, not file
contents, and skips the working-tree checkout entirely -- CommitShrink never
needs a working tree, only `git log`. This makes the clone cheap regardless
of repository size (a 450 MB repo whose history is mostly binaries clones in
seconds instead of timing out). The blobs collect() actually needs for its
--numstat diffs over the assessment window are then pre-fetched in one batch
per chunk by collector.backfill_window_blobs(), so reading the log is fully
local rather than incurring a network round-trip per commit. The clone always
lives in a TemporaryDirectory, removed when the caller's `with` block exits,
success or failure.

Full single-branch history is fetched -- but only its metadata, which is
small -- so the author-time vs committer-time window edge cases that
collector.GIT_WINDOW_SLACK guards are handled naturally: no history is
truncated. History rewrites from before the clone remain undetectable
(GIT-88.8 degrades to its documented reflog-unavailable copy, the same as
any repo without local reflog history -- no special-casing needed).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .collector import backfill_window_blobs
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
def local_repo(
    spec: str, days: int, until: datetime | None, author: str | None = None
) -> Iterator[Path]:
    """Yield a local path for `spec`: itself if local, a fresh blobless partial
    clone if remote. `days`/`until`/`author` mirror the window assess_repo()
    will use so backfill_window_blobs() pre-fetches exactly the diff blobs
    collect() needs (see this module's docstring).
    """
    if not is_remote_spec(spec):
        yield Path(spec)
        return

    url = _resolve_clone_url(spec)
    start, _end = compute_window(days, until)

    with tempfile.TemporaryDirectory(prefix="commit-shrink-") as tmp:
        args = [
            "git",
            "clone",
            "--quiet",
            "--single-branch",
            "--filter=blob:none",
            "--no-checkout",
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
        # Bulk-fetch the window's diff blobs up front so collect()'s --numstat
        # reads entirely from the local object store, using the same window and
        # author collect() will.
        backfill_window_blobs(Path(tmp), since=start - FETCH_PADDING, author=author)
        yield Path(tmp)
