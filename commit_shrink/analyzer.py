"""Sentiment scoring and quantitative metrics.

Implements the lexicon patch and metric formulas defined in
commit_shrink/data/symptoms.yaml. Scoring precedence (see lexicon_patch.note):

1. ALL-CAPS despair correction: offset applied to the raw VADER compound,
   bypassing every other patch entry.
2. Patch entries scanned as substrings (VADER tokenization never sees CJK);
   English phrase entries replace the VADER component, Chinese entries are
   blended by CJK character ratio.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from statistics import mean

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .models import Commit

_TRAILING_PUNCT = ".!?。！？…"

# Upper bound on how much a positive emotional baseline can lift the composite
# (as a negative "bad" term, weight 0.2 -> at most +6 points). Keeps the score's
# subtractive character while letting genuinely upbeat commit tone matter.
BASELINE_CREDIT_CAP = 0.3

# CJK ideographs, CJK punctuation, fullwidth forms, and common typographic
# marks used in the Chinese copy (em-dash, curly quotes, ellipsis).
_CJK_CLASS = r"[一-鿿　-〿＀-￯—‘’“”…]"
_CJK_GAP_RE = re.compile(f"(?<={_CJK_CLASS})\\s+(?={_CJK_CLASS})")


def collapse_cjk_whitespace(text: str) -> str:
    """Remove spaces between CJK characters (YAML folded scalars insert them)."""
    return _CJK_GAP_RE.sub("", text)


def has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _cjk_ratio(text: str) -> float:
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    total = cjk + latin
    return cjk / total if total else 0.0


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def normalize_message(message: str) -> str:
    """Normalization used by the low-information stoplist (GIT-11.2)."""
    return message.strip().lower().rstrip(_TRAILING_PUNCT).strip()


def is_low_info(message: str, stoplist: list[str]) -> bool:
    norm = normalize_message(message)
    if norm in {str(s).lower() for s in stoplist}:
        return True
    # The bare length floor is script-aware: a CJK character carries far more
    # information than a Latin one, so an informative 3-char Chinese subject
    # ("加日志"/"改样式"/"补测试") must not read as "unable to convey semantic
    # content." Latin text keeps the <4 rule; CJK text uses <2 (the stoplist
    # still catches genuinely empty ones like 改/更新/提交).
    threshold = 2 if has_cjk(norm) else 4
    return len(norm) < threshold


def techdebt_hash(normalized_message: str) -> str:
    """Compact identity for a normalized "temporary fix" message.

    Used by history.py's cross-period cache to notice the same fix recurring
    >=90 days later (GIT-77.7 grade IV) without storing the raw commit text
    in the cache indefinitely. Lives here rather than in history.py so
    diagnoser.py can compute it too without an import cycle (history.py
    depends on pipeline.py, which depends on diagnoser.py).
    """
    return hashlib.sha256(normalized_message.encode()).hexdigest()[:16]


def is_scream(message: str, stoplist: list[str]) -> bool:
    """ALL-CAPS despair correction gate.

    Excludes conventional abbreviations ('WIP'), tokens shorter than 4 letters,
    and any message containing CJK — str.isupper() ignores caseless characters,
    so '修复BUG' would otherwise register as a scream.
    """
    latin = sum(1 for ch in message if ch.isascii() and ch.isalpha())
    return (
        latin >= 4
        and not has_cjk(message)
        and message.isupper()
        and not is_low_info(message, stoplist)
    )


# Routine engineering vocabulary VADER reads as English negativity. "fix broken
# build" / "revert crashing migration" describe the everyday nouns and verbs of
# software work, not emotional disclosure -- zero them out so the baseline
# measures mood, not the dictionary of the job. (Genuine-affect words like
# "hate", "love", "please", "disaster" stay untouched.)
_ROUTINE_VOCAB = (
    "fix", "fixed", "fixes", "fixing", "bug", "bugs", "crash", "crashed",
    "crashes", "crashing", "fail", "failed", "failing", "fails", "broken",
    "break", "breaks", "revert", "reverts", "reverted", "error", "errors",
)


class SentimentScorer:
    def __init__(self, lexicon_cfg: dict, stoplist: list[str] | None = None):
        self._vader = SentimentIntensityAnalyzer()
        # Instance-local lexicon edit -- does not leak to other analyzers.
        for _term in _ROUTINE_VOCAB:
            self._vader.lexicon[_term] = 0.0
        self._stoplist = stoplist or []
        self.uppercase_offset = float(lexicon_cfg["uppercase_despair_offset"])
        entries = lexicon_cfg["entries"]
        self._zh_entries = [(t, float(w)) for t, w in entries.items() if has_cjk(t)]
        self._en_entries = [(t.lower(), float(w)) for t, w in entries.items() if not has_cjk(t)]

    def raw_vader(self, message: str) -> float:
        return self._vader.polarity_scores(message)["compound"]

    def score(self, message: str) -> float:
        raw = self.raw_vader(message)
        # ALL-CAPS despair correction has top precedence (skips patch entries).
        if is_scream(message, self._stoplist):
            return _clamp(raw + self.uppercase_offset)
        low = message.lower()
        en_hits = [w for term, w in self._en_entries if term in low]
        en_component = mean(en_hits) if en_hits else raw
        zh_hits = [w for term, w in self._zh_entries if term in message]
        if not zh_hits and not has_cjk(message):
            return _clamp(en_component)
        ratio = _cjk_ratio(message)
        zh_component = mean(zh_hits) if zh_hits else 0.0
        return _clamp(ratio * zh_component + (1 - ratio) * en_component)


@dataclass
class PeriodStats:
    """Aggregates shared by the metrics table and the ratio-type detectors."""

    total: int
    night_count: int
    night_ratio: float
    night_mood: float  # mean score of night commits (0.0 when none)
    day_mood: float  # mean score of non-night commits (0.0 when none)
    weekend_count: int
    weekday_count: int
    weekend_ratio: float
    uppercase_count: int
    uppercase_all_night: bool
    low_info_count: int
    low_info_ratio: float


@dataclass
class MetricValue:
    id: str
    name: str
    value: float
    display: str  # formatted value, e.g. "7.8" or "31%"
    reference: str
    percentile: float | None  # share of the fictional norm the patient is worse than
    direction: str  # higher_is_worse | lower_is_worse
    healthy: bool = False  # triggers the healthy_copy variant


def _normal_cdf(x: float, mu: float, sd: float) -> float:
    return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))


def _percentile(value: float, norm: dict | None) -> tuple[float | None, str]:
    if not norm:
        return None, "higher_is_worse"
    p = _normal_cdf(value, float(norm["mean"]), float(norm["sd"]))
    direction = norm["direction"]
    worse_share = p if direction == "higher_is_worse" else 1 - p
    return worse_share * 100, direction


def compute_stats(
    commits: list[Commit],
    scores: dict[str, float],
    stoplist: list[str],
) -> PeriodStats:
    total = len(commits)
    night = [c for c in commits if c.is_night]
    day = [c for c in commits if not c.is_night]
    night_scores = [scores[c.sha] for c in night]
    day_scores = [scores[c.sha] for c in day]
    uppercase = [c for c in commits if is_scream(c.message, stoplist)]
    weekend = sum(1 for c in commits if c.is_weekend)
    low_info = sum(1 for c in commits if is_low_info(c.message, stoplist))
    return PeriodStats(
        total=total,
        night_count=len(night),
        night_ratio=len(night) / total if total else 0.0,
        night_mood=mean(night_scores) if night_scores else 0.0,
        day_mood=mean(day_scores) if day_scores else 0.0,
        weekend_count=weekend,
        weekday_count=total - weekend,
        weekend_ratio=weekend / total if total else 0.0,
        uppercase_count=len(uppercase),
        uppercase_all_night=bool(uppercase) and all(c.is_night for c in uppercase),
        low_info_count=low_info,
        low_info_ratio=low_info / total if total else 0.0,
    )


def compute_metrics(
    commits: list[Commit],
    scores: dict[str, float],
    stats: PeriodStats,
    metrics_cfg: list[dict],
    fix_pattern: str,
) -> dict[str, MetricValue]:
    """Compute the five displayed metrics plus the composite score.

    Formulas are specified in symptoms.yaml; this function is their single
    executable interpretation (validated against the golden sample).
    """
    cfg_by_id = {m["id"]: m for m in metrics_cfg}
    result: dict[str, MetricValue] = {}

    def make(mid: str, value: float, display: str, healthy: bool = False) -> None:
        cfg = cfg_by_id[mid]
        pct, direction = _percentile(value, cfg.get("norm"))
        result[mid] = MetricValue(
            id=mid,
            name=cfg["name"],
            value=value,
            display=display,
            reference=str(cfg["reference"]),
            percentile=pct,
            direction=direction,
            healthy=healthy,
        )

    if stats.night_count:
        despair = 10 * (
            0.6 * min(1.0, stats.night_ratio / 0.4) + 0.4 * max(0.0, -stats.night_mood)
        )
    else:
        despair = 0.0
    make("night_despair_index", despair, f"{despair:.1f}", healthy=not stats.night_count)

    late_weekday = sum(1 for c in commits if not c.is_weekend and c.ts.hour >= 22)
    weighted = (
        (stats.weekend_count * 1.0 + late_weekday * 0.7) / stats.total if stats.total else 0.0
    )
    integrity = max(0.0, min(1.0, 1 - min(1.0, weighted)))
    make("boundary_integrity", integrity * 100, f"{integrity * 100:.0f}%")

    baseline = mean(scores.values()) if scores else 0.0
    make("emotional_baseline", baseline, f"{baseline:+.2f}")

    fix_re = re.compile(fix_pattern, re.IGNORECASE)
    fix_commits = sorted((c for c in commits if fix_re.search(c.message)), key=lambda c: c.ts)
    issues = 0
    prev_ts = None
    for c in fix_commits:
        if prev_ts is None or (c.ts - prev_ts).total_seconds() >= 2 * 3600:
            issues += 1
        prev_ts = c.ts
    density = len(fix_commits) / issues if issues else 0.0
    make("fix_loop_density", density, f"{density:.1f}", healthy=not fix_commits)

    make("alexithymia_index", stats.low_info_ratio * 100, f"{stats.low_info_ratio * 100:.0f}%")

    bad = [
        despair / 10,
        1 - integrity,
        # Negative baseline penalizes as before; a positive baseline now earns a
        # small bounded credit (a negative "bad", floored at -BASELINE_CREDIT_CAP)
        # so genuinely upbeat commit tone can claw back a few points instead of
        # being discarded. The 100 ceiling still holds (composite is clamped).
        max(-BASELINE_CREDIT_CAP, -baseline),
        min(1.0, max(0.0, (density - 2) / 6)),
        stats.low_info_ratio,
    ]
    weights = [0.3, 0.2, 0.2, 0.2, 0.1]
    composite = 100 * (1 - sum(w * b for w, b in zip(weights, bad)))
    composite = max(0.0, min(100.0, composite))
    make("composite_score", composite, f"{composite:.0f}")

    return result


BURDEN_WEIGHTS = {"I": 1, "II": 2, "III": 4, "IV": 6}
BURDEN_CAP = 35

# Diagnoses whose behavior is ALSO priced into a composite metric term:
#   night_despair       <-> night_despair_index
#   boundary_dissolution<-> boundary_integrity
#   repeated_fix_loop   <-> fix_loop_density
#   alexithymia         <-> alexithymia_index
# Their burden is halved so one behavior is not billed at full weight in both the
# quantitative table and the diagnosis list (emotional_baseline has no dedicated
# diagnosis, so it never double-charges).
DOUBLE_COUNTED = {"night_despair", "boundary_dissolution", "repeated_fix_loop", "alexithymia"}
DOUBLE_COUNT_DISCOUNT = 0.5


def apply_diagnosis_burden(
    metrics: dict[str, MetricValue], diagnoses: list[tuple[str, str]]
) -> None:
    """Final composite = max(0, metric base − diagnosis burden), per the formula
    in symptoms.yaml: pretty metrics cannot argue with the diagnosis list.

    `diagnoses` is a list of (symptom_id, severity) pairs. A diagnosis in
    DOUBLE_COUNTED already surfaces as a composite metric penalty, so its burden
    is discounted to avoid charging the same commits twice.
    """
    burden = 0.0
    for sid, severity in diagnoses:
        weight = BURDEN_WEIGHTS[severity]
        if sid in DOUBLE_COUNTED:
            weight *= DOUBLE_COUNT_DISCOUNT
        burden += weight
    burden = min(BURDEN_CAP, burden)
    composite = metrics["composite_score"]
    composite.value = max(0.0, composite.value - burden)
    composite.display = f"{composite.value:.0f}"
