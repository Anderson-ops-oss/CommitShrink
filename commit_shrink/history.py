"""Cross-period history: a local, append-only record of past assessments.

Storage lives in a user-level cache directory, not inside the assessed repo
(see plan-commit-shrink.md, Day 3-4 addendum, section 1) -- the history is
about a *person*, not a property of whichever checkout happens to be on disk,
and a remote assessment has no repo of the user's own to write into anyway.

Keying is (patient_email, repo_fingerprint). `repo_fingerprint` takes a list
of repo paths rather than a single path: today every caller passes a single-
element list, but a future multi-repo aggregate assessment can pass several
and get one stable, order-independent fingerprint for the set, without a
storage format migration.

Each entry also records `source` ("local" or "remote"), derived automatically
from whether the assessed path was a remote spec. Nothing here uses it yet;
it exists so a future feature can distinguish "my own tracked history" from
"a public repo I looked at once" without another migration.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .collector import remote_origin_url, root_commit_shas
from .pipeline import Assessment

DISPLAYED_METRIC_IDS = [
    "night_despair_index",
    "boundary_integrity",
    "emotional_baseline",
    "fix_loop_density",
    "alexithymia_index",
    "composite_score",
]

# Matches https://host/path(.git), git://host/path(.git), ssh://user@host/path(.git),
# and the scp-like user@host:path(.git) form -- the shapes GitHub/GitLab/etc. hand out.
# Anything else (e.g. a bare file:// path) falls back to a lowercased literal.
_REMOTE_URL_RE = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?(?P<host>[^:/]+)[:/]+(?P<path>.+?)/?(?:\.git)?/?$",
    re.IGNORECASE,
)


class FingerprintError(Exception):
    """Raised when a repo has neither a remote origin nor a discoverable root commit."""


def _normalize_remote_url(url: str) -> str:
    m = _REMOTE_URL_RE.match(url.strip())
    if not m:
        return url.strip().lower()
    return f"{m.group('host').lower()}/{m.group('path').strip('/')}"


def _single_repo_basis(repo: Path) -> str:
    origin = remote_origin_url(repo)
    if origin:
        return _normalize_remote_url(origin)
    roots = root_commit_shas(repo)
    if not roots:
        raise FingerprintError(str(repo))
    return ",".join(roots)


def repo_fingerprint(repos: Sequence[Path]) -> str:
    """Stable identity for one repo, or a set of repos assessed together.

    Order-independent: the same set of repos always yields the same
    fingerprint no matter what order they're passed in.
    """
    bases = sorted(_single_repo_basis(r) for r in repos)
    return hashlib.sha256("\n".join(bases).encode()).hexdigest()[:16]


def _cache_dir() -> Path:
    override = os.environ.get("COMMIT_SHRINK_CACHE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "commit-shrink"


def history_path() -> Path:
    return _cache_dir() / "history.jsonl"


@dataclass
class HistoryEntry:
    patient_email: str
    repo_fingerprint: str
    source: str  # "local" | "remote"
    period_end: str  # Assessment.period_end.isoformat()
    recorded_at: str  # wall-clock time this entry was appended, isoformat
    metrics: dict[str, dict[str, float | str]]  # DISPLAYED_METRIC_IDS -> {value, display}
    diagnoses: list[dict[str, str]]  # [{id, code, severity}, ...]


def entry_from_assessment(assessment: Assessment, fingerprint: str, source: str) -> HistoryEntry:
    metrics = {
        mid: {"value": assessment.metrics[mid].value, "display": assessment.metrics[mid].display}
        for mid in DISPLAYED_METRIC_IDS
    }
    diagnoses = [{"id": d.id, "code": d.code, "severity": d.severity} for d in assessment.diagnoses]
    return HistoryEntry(
        patient_email=assessment.patient_email,
        repo_fingerprint=fingerprint,
        source=source,
        period_end=assessment.period_end.isoformat(),
        recorded_at=datetime.now().astimezone().isoformat(),
        metrics=metrics,
        diagnoses=diagnoses,
    )


def append_entry(entry: HistoryEntry, path: Path | None = None) -> None:
    target = path or history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def load_history(patient_email: str, fingerprint: str, path: Path | None = None) -> list[HistoryEntry]:
    """All recorded assessments for this (patient, repo) pair, oldest first.

    Storage is append-only, so rerunning the same period_end writes a second
    line rather than editing the first; this collapses reruns to the last
    entry written for each period_end.
    """
    target = path or history_path()
    if not target.exists():
        return []
    by_period: dict[str, HistoryEntry] = {}
    with target.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if raw.get("patient_email") != patient_email or raw.get("repo_fingerprint") != fingerprint:
                continue
            entry = HistoryEntry(**raw)
            by_period[entry.period_end] = entry
    return sorted(by_period.values(), key=lambda e: e.period_end)


def record_assessment(
    assessment: Assessment,
    repos: Sequence[Path],
    source: str,
    path: Path | None = None,
) -> None:
    """Best-effort recording: swallow fingerprint/IO failures so a cache
    hiccup never blocks the report the user actually came here for.
    """
    try:
        fingerprint = repo_fingerprint(repos)
        entry = entry_from_assessment(assessment, fingerprint, source)
        append_entry(entry, path=path)
    except (FingerprintError, OSError):
        pass
