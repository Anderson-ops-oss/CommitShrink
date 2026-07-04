"""Data contract shared across the pipeline.

Mirrors Appendix A of docs/report-sample.md: everything comes from a single
`git log --pretty --numstat` pass, nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Commit:
    sha: str
    author_name: str
    author_email: str
    ts: datetime  # timezone-aware, author-local time
    message: str  # full raw message body
    parents: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    renames: list[tuple[str, str]] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    # Identifies which repo a commit came from. Empty for a single-repo
    # assessment; set per-repo by pipeline.assess_repos so that detectors keying
    # on file-path overlap don't group commits from *different* repos that
    # happen to touch identically-named files (README.md, __init__.py, ...).
    repo_key: str = ""

    @property
    def files_changed(self) -> int:
        return len(self.file_paths)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def subject(self) -> str:
        return self.message.strip().splitlines()[0] if self.message.strip() else ""

    @property
    def is_night(self) -> bool:
        """00:00-05:59 in the author's local time."""
        return 0 <= self.ts.hour <= 5

    @property
    def is_weekend(self) -> bool:
        return self.ts.weekday() >= 5

    @property
    def short(self) -> str:
        return self.sha[:7]
