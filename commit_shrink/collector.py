"""Read commits from a git repository.

Single `git log --pretty --numstat` pass, zero non-stdlib dependencies.

Windowing: git's --since/--until filter on *committer* dates, while the whole
pipeline reasons in *author* time (%ad). After a rebase those diverge, and a
git-side --until would silently drop commits whose author time is in the
period. We therefore fetch a widened committer-window (no --until) and filter
precisely on author time here.

Parsing: %B is the only field that can contain arbitrary bytes, including our
delimiters. Records are validated by their leading 40-hex sha (a RECORD_SEP
inside a message re-attaches to the previous record) and the body is rebuilt
from the middle fields (a FIELD_SEP inside a message cannot shift numstat).
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .models import Commit

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
# %B is the raw body; the trailing FIELD_SEP separates it from numstat lines.
PRETTY = f"{RECORD_SEP}%H{FIELD_SEP}%an{FIELD_SEP}%ae{FIELD_SEP}%ad{FIELD_SEP}%P{FIELD_SEP}%B{FIELD_SEP}"

# Committer dates may lag author dates by however long a branch lives before
# a rebase; a month of slack covers ordinary workflows.
GIT_WINDOW_SLACK = timedelta(days=30)

_NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_RENAME_BRACES_RE = re.compile(
    r"^(?P<prefix>.*?)\{(?P<old>[^{}]*?) => (?P<new>[^{}]*?)\}(?P<suffix>.*)$"
)
_UNBORN_MARKERS = ("does not have any commits yet", "bad default revision")
_NOT_REPO_MARKERS = ("not a git repository", "cannot change to", "no such file or directory")


class NotARepoError(Exception):
    """Raised when the target path is not a git repository."""


def _run_git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0: # ran failed
        stderr = proc.stderr.lower()
        if any(marker in stderr for marker in _NOT_REPO_MARKERS):
            raise NotARepoError(str(repo))
        raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def _normalize_path(path: str) -> str:
    """Resolve numstat rename syntax to the post-rename path."""
    return _parse_numstat_path(path)[0]

def _parse_numstat_path(path: str) -> tuple[str, tuple[str, str] | None]:
    """Return (display_path, rename_pair) for a git numstat path.

    `file_paths` should keep the post-rename path for counts/reporting, while
    `renames` preserves both identities for topic-overlap detection.
    """
    if "=>" not in path:
        return path, None
    brace_match = _RENAME_BRACES_RE.match(path)
    if brace_match:
        prefix = brace_match.group("prefix")
        suffix = brace_match.group("suffix")
        old_path = f"{prefix}{brace_match.group('old')}{suffix}".replace("//", "/")
        new_path = f"{prefix}{brace_match.group('new')}{suffix}".replace("//", "/")
        return new_path, (old_path, new_path)
    old_path, new_path = path.split(" => ", 1)
    return new_path, (old_path, new_path)


def collect(
    repo: Path,
    since: datetime,
    until: datetime,
    author: str | None = None,
) -> list[Commit]:
    """Return commits with author time in [since, until], ascending."""
    args = [
        "log",
        "--date=iso-strict",
        f"--pretty=format:{PRETTY}",
        "--numstat",
        f"--since={(since - GIT_WINDOW_SLACK).isoformat()}",
    ]
    if author:
        args.append(f"--author={author}")
    try:
        out = _run_git(repo, args)
    except RuntimeError as e:
        if any(marker in str(e).lower() for marker in _UNBORN_MARKERS):
            return []  # freshly-initialized repo: empty history, not an error
        raise

    # Re-attach fragments created by a RECORD_SEP inside a commit message.
    records: list[str] = []
    for fragment in out.split(RECORD_SEP):
        if not fragment.strip():
            continue
        head = fragment.split(FIELD_SEP, 1)[0]
        if _SHA_RE.fullmatch(head) or not records:
            records.append(fragment)
        else:
            records[-1] += RECORD_SEP + fragment

    commits: list[Commit] = []
    for record in records:
        parts = record.split(FIELD_SEP)
        if len(parts) < 7:
            continue
        sha, author_name, author_email, ad, parents_raw = parts[:5]
        tail = parts[-1]  # numstat block; FIELD_SEP in the body cannot reach it
        body = FIELD_SEP.join(parts[5:-1])
        file_paths: list[str] = []
        renames: list[tuple[str, str]] = []
        insertions = deletions = 0
        for line in tail.splitlines():
            m = _NUMSTAT_RE.match(line.strip("\n"))
            if not m:
                continue
            ins, dels, path = m.groups()
            normalized_path, rename = _parse_numstat_path(path)
            file_paths.append(normalized_path)
            if rename:
                renames.append(rename)
            insertions += 0 if ins == "-" else int(ins)
            deletions += 0 if dels == "-" else int(dels)
        commits.append(
            Commit(
                sha=sha,
                author_name=author_name,
                author_email=author_email,
                ts=datetime.fromisoformat(ad),
                message=body.strip("\n"),
                parents=parents_raw.split(),
                file_paths=file_paths,
                renames=renames,
                insertions=insertions,
                deletions=deletions,
            )
        )
    commits = [c for c in commits if since <= c.ts <= until]
    commits.sort(key=lambda c: c.ts)
    return commits


def remote_origin_url(repo: Path) -> str | None:
    """The `origin` remote URL, or None if the repo has no remote configured.

    Used by history.py to fingerprint a repo by its remote identity rather
    than its local path, so the same GitHub repo cloned to two different
    directories (or cloned fresh into a temp dir for a remote assessment)
    shares one cross-period history. `git config --get` on a missing key
    exits non-zero with empty stderr -- not a real error, so this bypasses
    _run_git's error handling rather than reusing it.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() or None


def root_commit_shas(repo: Path) -> list[str]:
    """Every root (parentless) commit reachable from HEAD, sorted for a
    deterministic fingerprint. Fallback identity for history.py when a repo
    has no remote configured (a pure-local repo). Empty if the repo has no
    commits or HEAD cannot be resolved.
    """
    try:
        out = _run_git(repo, ["rev-list", "--max-parents=0", "HEAD"])
    except (NotARepoError, RuntimeError):
        return []
    return sorted(out.split())


def count_rewrites(repo: Path, since: datetime, until: datetime) -> int | None:
    """Count history rewrites (amends + rebase sessions) in the HEAD reflog.

    Returns None when the reflog is unavailable (bare clone, disabled reflog),
    in which case GIT-88.8 degrades to the "specimen declined" copy.
    Rebases are counted per session (their '(finish)' entry), not per picked
    commit. Force-pushes need remote-side data and are not detected in v0.1.
    Committer date of the rewritten commit approximates the entry time.
    """
    try:
        out = _run_git(repo, ["reflog", "show", f"--format=%cI{FIELD_SEP}%gs"])
    except (NotARepoError, RuntimeError):
        return None
    if not out.strip():
        return None
    count = 0
    for line in out.splitlines():
        if FIELD_SEP not in line:
            continue
        when_raw, subject = line.split(FIELD_SEP, 1)
        try:
            when = datetime.fromisoformat(when_raw)
        except ValueError:
            continue
        if not (since <= when <= until):
            continue
        if "commit (amend)" in subject:
            count += 1
        elif subject.startswith("rebase") and "finish" in subject:
            count += 1
    return count
