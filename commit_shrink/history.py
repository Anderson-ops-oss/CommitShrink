"""Cross-period history: a local, append-only record of past assessments.

Storage lives in a user-level cache directory, not inside the assessed repo
-- the history is about a *person*, not a property of whichever checkout
happens to be on disk,
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
import math
import os
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .analyzer import normalize_message, techdebt_hash
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


def user_fingerprint(username: str) -> str:
    """Person-anchored identity for a `gh-user:` aggregate assessment.

    Keyed on the user, NOT on the set of repos, so the trend line survives the
    user adding or archiving repos week to week -- a repo-set fingerprint would
    change and silently reset the streak. Human-readable on purpose (it lands
    in history.jsonl).
    """
    return f"user:{username.lower()}"


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
    techdebt_hashes: list[str] = field(default_factory=list)  # GIT-77.7 hit messages, hashed


def entry_from_assessment(assessment: Assessment, fingerprint: str, source: str) -> HistoryEntry:
    metrics = {
        mid: {"value": assessment.metrics[mid].value, "display": assessment.metrics[mid].display}
        for mid in DISPLAYED_METRIC_IDS
    }
    diagnoses = [{"id": d.id, "code": d.code, "severity": d.severity} for d in assessment.diagnoses]
    techdebt = next((d for d in assessment.diagnoses if d.id == "stockholm_techdebt"), None)
    techdebt_hashes = sorted(
        {techdebt_hash(normalize_message(c.message)) for c in techdebt.evidence} if techdebt else []
    )
    return HistoryEntry(
        patient_email=assessment.patient_email,
        repo_fingerprint=fingerprint,
        source=source,
        period_end=assessment.period_end.isoformat(),
        recorded_at=datetime.now().astimezone().isoformat(),
        metrics=metrics,
        diagnoses=diagnoses,
        techdebt_hashes=techdebt_hashes,
    )


def append_entry(entry: HistoryEntry, path: Path | None = None) -> None:
    target = path or history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def load_history(
    patient_email: str | None, fingerprint: str, path: Path | None = None
) -> list[HistoryEntry]:
    """Recorded assessments for this repo, oldest first.

    `patient_email=None` returns every patient recorded against this repo
    fingerprint -- used by the GIT-77.7 recurrence check, which is a property
    of the repo (has this exact "temporary fix" text shown up before,
    regardless of who wrote it) rather than of one person's trend line.

    Storage is append-only, so rerunning the same period_end writes a second
    line rather than editing the first; this collapses reruns to the last
    entry written for each (patient, period_end) pair.
    """
    target = path or history_path()
    if not target.exists():
        return []
    by_key: dict[tuple[str, str], HistoryEntry] = {}
    with target.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if raw.get("repo_fingerprint") != fingerprint:
                continue
            if patient_email is not None and raw.get("patient_email") != patient_email:
                continue
            entry = HistoryEntry(**raw)
            by_key[(entry.patient_email, entry.period_end)] = entry
    return sorted(by_key.values(), key=lambda e: datetime.fromisoformat(e.period_end))


def build_techdebt_index(entries: list[HistoryEntry]) -> dict[str, str]:
    """Earliest period_end each techdebt message hash was seen, across every
    entry passed in (deliberately not patient-scoped -- see load_history).
    """
    earliest: dict[str, datetime] = {}
    for entry in entries:
        seen_at = datetime.fromisoformat(entry.period_end)
        for h in entry.techdebt_hashes:
            if h not in earliest or seen_at < earliest[h]:
                earliest[h] = seen_at
    return {h: ts.isoformat() for h, ts in earliest.items()}


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


@dataclass
class Trend:
    metric_previous: dict[str, str]  # metric_id -> previous period's display string
    composite_delta: int | None  # current - previous composite, None with no prior period
    decline_streak: int  # 0 = no prior period; 1 = prior period exists, not declining; >=2 = streak
    extrapolated_week: int | None  # ISO week the composite is projected to hit 0 (streak >= 2 only)


NO_TREND = Trend(metric_previous={}, composite_delta=None, decline_streak=0, extrapolated_week=None)


def compute_trend(assessment: Assessment, history_entries: list[HistoryEntry]) -> Trend:
    """Compare this assessment against the most recent *earlier* period.

    `history_entries` may include an entry for this exact period (a rerun)
    or later synthetic entries in tests; both are excluded so a rerun never
    gets compared against itself.
    """
    prior = sorted(
        (e for e in history_entries if datetime.fromisoformat(e.period_end) < assessment.period_end),
        key=lambda e: datetime.fromisoformat(e.period_end),
    )
    if not prior:
        return NO_TREND

    latest = prior[-1]
    metric_previous = {
        mid: latest.metrics[mid]["display"] for mid in DISPLAYED_METRIC_IDS if mid in latest.metrics
    }

    # Compare the already-rounded display values (not the raw floats) so the
    # shown delta always matches what a reader can verify by hand from the
    # two numbers actually printed in the report.
    current = int(assessment.metrics["composite_score"].display)
    series = [int(e.metrics["composite_score"]["display"]) for e in prior] + [current]
    composite_delta = series[-1] - series[-2]

    streak = 1
    for i in range(len(series) - 1, 0, -1):
        if series[i] < series[i - 1]:
            streak += 1
        else:
            break

    extrapolated_week = None
    if streak >= 2:
        start_value = series[len(series) - streak]
        slope = (current - start_value) / (streak - 1)  # strictly negative when streak >= 2
        weeks_to_zero = math.ceil(current / abs(slope))
        extrapolated_week = assessment.period_end.isocalendar().week + weeks_to_zero

    return Trend(
        metric_previous=metric_previous,
        composite_delta=composite_delta,
        decline_streak=streak,
        extrapolated_week=extrapolated_week,
    )


@dataclass
class HistoryContext:
    """Everything assess_repo() can use from cross-period history, resolved
    before the run (repo_fingerprint needs the repo on disk, which a remote
    clone's temp dir won't have once the assessment finishes).
    """

    fingerprint: str | None
    techdebt_index: dict[str, str]


def load_context(
    repos: Sequence[Path],
    path: Path | None = None,
    fingerprint_override: str | None = None,
) -> HistoryContext:
    """Degrades to an empty context if the repo has no discoverable identity
    yet (no remote and no commits) -- the caller still renders a normal
    first-assessment report, just without cross-period data.

    `fingerprint_override` (e.g. history.user_fingerprint(username)) keys the
    history by something other than the repo set -- the gh-user aggregate uses
    it so trend continuity survives the user's repo set changing.
    """
    if fingerprint_override is not None:
        fingerprint = fingerprint_override
    else:
        try:
            fingerprint = repo_fingerprint(repos)
        except FingerprintError:
            return HistoryContext(fingerprint=None, techdebt_index={})
    techdebt_index = build_techdebt_index(load_history(None, fingerprint, path=path))
    return HistoryContext(fingerprint=fingerprint, techdebt_index=techdebt_index)


def finalize(
    ctx: HistoryContext,
    assessment: Assessment,
    repos: Sequence[Path],
    source: str,
    path: Path | None = None,
    patient_scoped: bool = True,
) -> Trend:
    """Compute this assessment's trend against prior periods, then record it
    for next time. Call once, after assess_repo()/assess_repos() succeeds, with
    the same `ctx` returned by load_context() for this run.

    Records against ctx.fingerprint (which may be a user_fingerprint override),
    not a freshly recomputed repo fingerprint.

    `patient_scoped` controls how the prior-period lookup is keyed:
    - True  (single repo): prior periods are matched by (patient_email,
      fingerprint) -- a repo fingerprint is shared by everyone who committed to
      it, so the email is what isolates *this* person's trend line.
    - False (gh-user aggregate): the fingerprint is ALREADY person-specific
      (user_fingerprint(username)), so we match by fingerprint alone. Scoping by
      email here would break continuity, because assess_repos deliberately keeps
      multiple identities and the volume-dominant email can drift week to week.
    """
    if ctx.fingerprint is None:
        return NO_TREND
    lookup_email = None if not patient_scoped else assessment.patient_email
    prior = load_history(lookup_email, ctx.fingerprint, path=path)
    trend = compute_trend(assessment, prior)
    try:
        append_entry(entry_from_assessment(assessment, ctx.fingerprint, source), path=path)
    except OSError:
        # Best-effort: a cache write hiccup never blocks the report itself.
        pass
    return trend
