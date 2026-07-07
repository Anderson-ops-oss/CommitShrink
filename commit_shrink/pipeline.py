"""Assemble collector → analyzer → diagnoser into one assessment run."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from importlib import resources
from pathlib import Path

import yaml

from .analyzer import (
    MetricValue,
    PeriodStats,
    SentimentScorer,
    apply_diagnosis_burden,
    compute_metrics,
    compute_stats,
)
from .collector import collect, count_rewrites
from .diagnoser import Diagnoser, Diagnosis
from .models import Commit

FETCH_PADDING = timedelta(days=3)  # per the data contract in docs/report-sample.md


class NoCommitsError(Exception):
    """No commits found in the assessment period."""


SUPPORTED_LANGS = ("zh", "en")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively overlay `override` onto `base` (mutates and returns base).

    Nested dicts merge key-by-key; every other value (str, list, scalar) is
    replaced wholesale. Used to splice a locale's display strings over the
    Chinese base without disturbing sibling keys.
    """
    for key, val in override.items():
        if isinstance(base.get(key), dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
    return base


def _overlay_by_id(items: list[dict], overrides: dict) -> None:
    """Overlay display fields onto list entries keyed by their `id`.

    `symptoms` and `metrics` are lists in symptoms.yaml but id-keyed maps in a
    locale file; this splices each locale entry onto the matching list item in
    place, leaving detection rules (trigger/severity/norm/…) untouched.
    """
    for item in items:
        override = overrides.get(item.get("id"))
        if override:
            _deep_merge(item, override)


def _apply_locale(cfg: dict, lang: str) -> None:
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"unsupported language {lang!r}; expected one of {SUPPORTED_LANGS}")
    ref = resources.files("commit_shrink").joinpath(f"data/locales/{lang}.yaml")
    with ref.open(encoding="utf-8") as f:
        locale = yaml.safe_load(f)
    for block in ("meta", "report_copy", "boilerplate"):
        if block in locale:
            _deep_merge(cfg.setdefault(block, {}), locale[block])
    for list_block in ("metrics", "symptoms"):
        if list_block in locale:
            _overlay_by_id(cfg.get(list_block, []), locale[list_block])


def load_config(lang: str = "zh") -> dict:
    """Load the runtime config, optionally overlaying a display-copy locale.

    Detection rules (triggers, severity thresholds, norms) always come from
    symptoms.yaml, which also carries the Chinese display copy inline. For any
    non-`zh` language, the matching data/locales/<lang>.yaml is deep-merged
    over the display fields only (see that directory).
    """
    ref = resources.files("commit_shrink").joinpath("data/symptoms.yaml")
    with ref.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if lang and lang != "zh":
        _apply_locale(cfg, lang)
    cfg["lang"] = lang or "zh"  # recorded so renderers can emit correct lang tags
    return cfg


def compute_window(days: int, until: datetime | None) -> tuple[datetime, datetime]:
    """Calendar-day assessment window: days=7 ending Sunday covers Monday
    00:00 .. Sunday, matching the golden sample's Mon-Sun week view (not an
    8-day span). Exposed so remote.py can size a shallow clone to the same
    window assess_repo() will filter to, without duplicating this logic.
    """
    end = until or datetime.now().astimezone()
    if end.tzinfo is None:
        end = end.astimezone()
    start = datetime.combine(end.date() - timedelta(days=days - 1), time.min, tzinfo=end.tzinfo)
    return start, end


@dataclass
class Assessment:
    patient_name: str
    patient_email: str
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    commits: list[Commit]
    scores: dict[str, float]
    stats: PeriodStats
    metrics: dict[str, MetricValue]
    diagnoses: list[Diagnosis]
    notes: list[str] = field(default_factory=list)
    masked_subjects: dict[str, str] = field(default_factory=dict)


def _gather(
    repo: Path, start: datetime, end: datetime, author: str | None
) -> tuple[list[Commit], list[Commit]]:
    """Read one repo's log and split it into (window, period): `window` carries
    FETCH_PADDING on both sides for the lookahead detectors; `period` is the
    strict assessment window."""
    window = collect(repo, since=start - FETCH_PADDING, until=end + FETCH_PADDING, author=author)
    period = [c for c in window if start <= c.ts <= end]
    return window, period


def _dominant_author(period: list[Commit]) -> tuple[str, str]:
    return Counter((c.author_name, c.author_email) for c in period).most_common(1)[0][0]


def _build_assessment(
    *,
    window: list[Commit],
    period: list[Commit],
    cfg: dict,
    techdebt_history: dict[str, str] | None,
    patient_name: str,
    patient_email: str,
    start: datetime,
    end: datetime,
    rewrites: int | None,
) -> Assessment:
    """Run the analyzer + diagnoser over an already-selected commit set. Shared
    by assess_repo (one repo, one patient) and assess_repos (a merged timeline
    across repos)."""
    diagnoser = Diagnoser(cfg)
    scorer = SentimentScorer(cfg["lexicon_patch"], stoplist=diagnoser.stoplist)
    scores = {c.sha: scorer.score(c.message) for c in period}

    stats = compute_stats(period, scores, diagnoser.stoplist)
    fix_pattern = diagnoser.re_fix.pattern
    metrics = compute_metrics(period, scores, stats, cfg["metrics"], fix_pattern)
    diagnoses, notes = diagnoser.run(period, window, scores, stats, rewrites, techdebt_history)
    apply_diagnosis_burden(metrics, [(d.id, d.severity) for d in diagnoses])

    masked_subjects = {c.sha: diagnoser.mask(c.subject)[0] for c in period}

    return Assessment(
        patient_name=patient_name,
        patient_email=patient_email,
        period_start=start,
        period_end=end,
        generated_at=datetime.now().astimezone(),
        commits=period,
        scores=scores,
        stats=stats,
        metrics=metrics,
        diagnoses=diagnoses,
        notes=notes,
        masked_subjects=masked_subjects,
    )


def assess_repo(
    repo: Path,
    days: int = 7,
    until: datetime | None = None,
    author: str | None = None,
    cfg: dict | None = None,
    techdebt_history: dict[str, str] | None = None,
) -> Assessment:
    cfg = cfg or load_config()
    start, end = compute_window(days, until)

    window, period = _gather(repo, start, end, author)
    if not period:
        raise NoCommitsError(str(repo))

    # The report assesses a single patient: restrict every statistic and piece
    # of evidence to the dominant author (or the --author filter's survivor).
    patient_name, patient_email = _dominant_author(period)
    period = [c for c in period if c.author_email == patient_email]
    window = [c for c in window if c.author_email == patient_email]

    return _build_assessment(
        window=window,
        period=period,
        cfg=cfg,
        techdebt_history=techdebt_history,
        patient_name=patient_name,
        patient_email=patient_email,
        start=start,
        end=end,
        rewrites=count_rewrites(repo, start, end),
    )


def _dedupe_by_sha(commits: list[Commit]) -> list[Commit]:
    """First occurrence wins; forks that share history don't double-count."""
    seen: set[str] = set()
    out: list[Commit] = []
    for c in commits:
        if c.sha not in seen:
            seen.add(c.sha)
            out.append(c)
    return out


def assess_repos(
    repos: list[Path],
    days: int = 7,
    until: datetime | None = None,
    author: str | None = None,
    cfg: dict | None = None,
    techdebt_history: dict[str, str] | None = None,
) -> Assessment:
    """Assess one person across several repos as a single merged commit
    timeline (used by the `gh-user:` spec).

    Deliberately different from assess_repo in two ways: (1) it does NOT
    re-narrow to the single dominant email -- the caller has already filtered
    each repo by --author, and a person's records legitimately span multiple
    name/email identities across their repos, all of which should count; and
    (2) reflog-based rewrite detection (GIT-88.8) is unavailable across a repo
    set (each clone lacks the original local reflog), so it degrades exactly as
    any remote assessment does. Commits are deduped by sha so shared/forked
    history isn't counted twice.
    """
    cfg = cfg or load_config()
    start, end = compute_window(days, until)

    windows: list[Commit] = []
    periods: list[Commit] = []
    for repo in repos:
        w, p = _gather(repo, start, end, author)
        # Tag each commit with its source repo so path-overlap detectors don't
        # group same-named files across different repos (p ⊂ w, same objects).
        for c in w:
            c.repo_key = str(repo)
        windows.extend(w)
        periods.extend(p)

    period = _dedupe_by_sha(sorted(periods, key=lambda c: c.ts))
    window = _dedupe_by_sha(sorted(windows, key=lambda c: c.ts))
    if not period:
        raise NoCommitsError(", ".join(str(r) for r in repos))

    patient_name, patient_email = _dominant_author(period)
    return _build_assessment(
        window=window,
        period=period,
        cfg=cfg,
        techdebt_history=techdebt_history,
        patient_name=patient_name,
        patient_email=patient_email,
        start=start,
        end=end,
        rewrites=None,
    )
