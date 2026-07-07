"""Unit tests for analyzer.compute_metrics + compute_stats + MetricValue.

These pin the composite-score arithmetic directly (importing the functions and
feeding them hand-built Commit lists plus a hand-supplied ``scores`` dict),
rather than going through the full pipeline. That isolates the metric formulas
from sentiment scoring: the ``scores`` dict controls the emotional baseline and
per-commit moods, while the commit *messages* drive the message-derived signals
(fix-loop, low-information, scream). No existing test calls these two functions.

Numbers are the values actually produced by the current code (observed by
running the analyzer), not independently "expected" ideals -- so a formula edit
that shifts the headline score trips these instead of silently passing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from commit_shrink.analyzer import (
    BASELINE_CREDIT_CAP,
    MetricValue,
    compute_metrics,
    compute_stats,
)
from commit_shrink.diagnoser import Diagnoser
from commit_shrink.models import Commit
from commit_shrink.pipeline import load_config


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


@pytest.fixture(scope="module")
def diag(cfg) -> Diagnoser:
    return Diagnoser(cfg)


@pytest.fixture(scope="module")
def metrics_cfg(cfg) -> list[dict]:
    return cfg["metrics"]


@pytest.fixture(scope="module")
def fix_pattern(diag) -> str:
    # The same pattern the pipeline hands compute_metrics (diagnoser.re_fix).
    return diag.re_fix.pattern


def _c(message: str, *, day: int = 0, hour: int = 12, i: int = 0, files=("a.py",)) -> Commit:
    # Anchor on 2026-01-05 (a Monday); day 5 = Saturday, day 6 = Sunday.
    # hour in 0..5 is "night". All timestamps are timezone.utc and fixed.
    return Commit(
        sha=f"{i:040x}",
        author_name="D",
        author_email="d@d",
        ts=datetime(2026, 1, 5 + day, hour, i % 60, tzinfo=timezone.utc),
        message=message,
        file_paths=list(files),
    )


# --------------------------------------------------------------------------
# (1) All-zero-signal input -> a perfect composite of exactly 100.0.
# --------------------------------------------------------------------------


class TestAllZeroSignal:
    """No night commits, no weekend, neutral (0.0) baseline, no fix loop, no
    low-info: every "bad" term is 0, so the composite is the full 100.0 and the
    two metrics with a healthy_copy variant (despair, fix-loop) flag healthy."""

    def _run(self, metrics_cfg, fix_pattern, stoplist):
        # Three plain daytime weekday commits; scores pinned to a neutral 0.0.
        commits = [
            _c("implement authentication module", day=d, hour=12, i=d) for d in range(3)
        ]
        scores = {c.sha: 0.0 for c in commits}
        stats = compute_stats(commits, scores, stoplist)
        metrics = compute_metrics(commits, scores, stats, metrics_cfg, fix_pattern)
        return stats, metrics

    def test_stats_have_no_signal(self, diag, metrics_cfg, fix_pattern):
        stats, _ = self._run(metrics_cfg, fix_pattern, diag.stoplist)
        assert stats.total == 3
        assert stats.night_count == 0 and stats.night_ratio == 0.0
        assert stats.night_mood == 0.0 and stats.day_mood == 0.0
        assert stats.weekend_count == 0 and stats.weekday_count == 3
        assert stats.weekend_ratio == 0.0
        assert stats.low_info_count == 0 and stats.low_info_ratio == 0.0
        assert stats.uppercase_count == 0

    def test_composite_is_exactly_100(self, diag, metrics_cfg, fix_pattern):
        _, m = self._run(metrics_cfg, fix_pattern, diag.stoplist)
        comp = m["composite_score"]
        assert comp.value == 100.0
        assert comp.display == "100"
        # composite has no norm -> no percentile, direction defaults.
        assert comp.percentile is None
        assert comp.direction == "higher_is_worse"

    def test_each_of_the_five_metric_values(self, diag, metrics_cfg, fix_pattern):
        _, m = self._run(metrics_cfg, fix_pattern, diag.stoplist)

        assert m["night_despair_index"].value == 0.0
        assert m["night_despair_index"].display == "0.0"
        # no night commits -> the healthy_copy variant fires.
        assert m["night_despair_index"].healthy is True

        assert m["boundary_integrity"].value == 100.0
        assert m["boundary_integrity"].display == "100%"

        assert m["emotional_baseline"].value == 0.0
        assert m["emotional_baseline"].display == "+0.00"

        assert m["fix_loop_density"].value == 0.0
        assert m["fix_loop_density"].display == "0.0"
        # no fix commits -> healthy_copy variant fires here too.
        assert m["fix_loop_density"].healthy is True

        assert m["alexithymia_index"].value == 0.0
        assert m["alexithymia_index"].display == "0%"

    def test_returns_metricvalue_instances_with_names(self, diag, metrics_cfg, fix_pattern):
        _, m = self._run(metrics_cfg, fix_pattern, diag.stoplist)
        for mid in (
            "night_despair_index",
            "boundary_integrity",
            "emotional_baseline",
            "fix_loop_density",
            "alexithymia_index",
            "composite_score",
        ):
            mv = m[mid]
            assert isinstance(mv, MetricValue)
            assert mv.id == mid
            assert mv.name  # config-supplied display name is populated


# --------------------------------------------------------------------------
# (2) Positive baseline -> credit floor at -BASELINE_CREDIT_CAP + the 100 ceiling.
# --------------------------------------------------------------------------


class TestPositiveBaselineCreditAndCeiling:
    def test_ceiling_holds_and_bad_is_floored(self, diag, metrics_cfg, fix_pattern):
        # Strongly positive baseline (0.8), everything else zero. The baseline
        # "bad" term = max(-CAP, -0.8) = -CAP (a credit), which would push the
        # composite to 106 -- but the clamp keeps it at 100.
        commits = [
            _c("polish the delightful onboarding flow", day=d, hour=12, i=d) for d in range(3)
        ]
        scores = {c.sha: 0.8 for c in commits}
        stats = compute_stats(commits, scores, diag.stoplist)
        m = compute_metrics(commits, scores, stats, metrics_cfg, fix_pattern)

        assert m["emotional_baseline"].value == 0.8
        assert m["emotional_baseline"].display == "+0.80"

        # The documented baseline-credit floor: a big positive baseline saturates.
        assert max(-BASELINE_CREDIT_CAP, -0.8) == -0.3
        assert BASELINE_CREDIT_CAP == 0.3

        comp = m["composite_score"]
        assert comp.value == 100.0  # clamped, never exceeds the ceiling
        assert comp.value <= 100.0
        assert comp.display == "100"

    def test_credit_is_actually_applied_below_the_ceiling(self, diag, metrics_cfg, fix_pattern):
        # A modest positive baseline (0.1, below the cap) plus a low-info penalty
        # so the composite sits under 100 and the credit's effect is visible:
        #   bad = [0, 0, max(-0.3,-0.1)=-0.1, 0, low_info_ratio=0.4]
        #   composite = 100*(1 - (0.2*-0.1 + 0.1*0.4)) = 100*(1 - 0.02) = 98.0
        # Without the credit it would be 100*(1 - 0.04) = 96.0, so the +0.1
        # baseline clawed back exactly 2 points.
        commits = [_c("normal daytime work here", day=0, hour=12, i=i) for i in range(3)] + [
            _c("wip", day=1, hour=12, i=3 + i) for i in range(2)
        ]
        scores = {c.sha: 0.1 for c in commits}
        stats = compute_stats(commits, scores, diag.stoplist)
        m = compute_metrics(commits, scores, stats, metrics_cfg, fix_pattern)

        assert stats.low_info_ratio == pytest.approx(0.4)
        assert m["alexithymia_index"].value == pytest.approx(40.0)
        assert m["alexithymia_index"].display == "40%"
        assert m["emotional_baseline"].value == pytest.approx(0.1)
        assert m["emotional_baseline"].display == "+0.10"

        comp = m["composite_score"]
        assert comp.value == pytest.approx(98.0)
        assert comp.display == "98"


# --------------------------------------------------------------------------
# (3) Mixed input -> composite reconstructed by hand from the documented formula.
# --------------------------------------------------------------------------


class TestMixedComposite:
    """Four negative-mood night commits, a three-deep fix loop inside one
    2h window, a couple of weekend commits, and two low-info ``wip`` commits.
    The baseline lands slightly negative (only the night commits carry a
    non-zero, negative score)."""

    def _run(self, metrics_cfg, fix_pattern, stoplist):
        commits = []
        i = 0
        for _ in range(4):  # night, weekday (Mon), negative mood
            commits.append(_c("feature work overnight", day=0, hour=2, i=i))
            i += 1
        # Three fix commits inside a single 2h window -> one "issue", density 3.0.
        commits.append(_c("fix the parser bug", day=0, hour=10, i=i)); i += 1
        commits.append(_c("fix the parser bug again", day=0, hour=10, i=i)); i += 1
        commits.append(_c("fix the parser bug once more", day=0, hour=11, i=i)); i += 1
        # Two Saturday commits.
        commits.append(_c("weekend feature", day=5, hour=14, i=i)); i += 1
        commits.append(_c("weekend feature two", day=5, hour=15, i=i)); i += 1
        # Two low-info commits (``wip`` is in the stoplist).
        commits.append(_c("wip", day=1, hour=13, i=i)); i += 1
        commits.append(_c("wip", day=1, hour=13, i=i)); i += 1

        night_shas = {c.sha for c in commits if c.is_night}
        scores = {c.sha: (-0.5 if c.sha in night_shas else 0.0) for c in commits}
        stats = compute_stats(commits, scores, stoplist)
        metrics = compute_metrics(commits, scores, stats, metrics_cfg, fix_pattern)
        return stats, metrics

    def test_stats_and_intermediate_metrics(self, diag, metrics_cfg, fix_pattern):
        stats, m = self._run(metrics_cfg, fix_pattern, diag.stoplist)
        assert stats.total == 11
        assert stats.night_count == 4 and stats.night_ratio == pytest.approx(4 / 11)
        assert stats.night_mood == -0.5
        assert stats.weekend_count == 2 and stats.weekday_count == 9
        assert stats.low_info_count == 2 and stats.low_info_ratio == pytest.approx(2 / 11)

        assert m["night_despair_index"].value == pytest.approx(7.454545454545453)
        assert m["night_despair_index"].display == "7.5"
        assert m["boundary_integrity"].value == pytest.approx(81.81818181818181)
        assert m["boundary_integrity"].display == "82%"
        assert m["emotional_baseline"].value == pytest.approx(-0.18181818181818182)
        assert m["emotional_baseline"].display == "-0.18"
        assert m["fix_loop_density"].value == pytest.approx(3.0)
        assert m["fix_loop_density"].display == "3.0"
        assert m["alexithymia_index"].value == pytest.approx(18.181818181818183)
        assert m["alexithymia_index"].display == "18%"

    def test_composite_matches_hand_formula(self, diag, metrics_cfg, fix_pattern):
        stats, m = self._run(metrics_cfg, fix_pattern, diag.stoplist)

        # Reconstruct the composite from the documented formula, drawing the
        # intermediate metric values back out of the returned MetricValues:
        #   composite = clamp[0,100]( 100 * (1 - sum(w * bad)) )
        #   weights = [0.3, 0.2, 0.2, 0.2, 0.1]
        despair = m["night_despair_index"].value
        integrity = m["boundary_integrity"].value / 100
        baseline = m["emotional_baseline"].value
        density = m["fix_loop_density"].value
        low_info_ratio = stats.low_info_ratio
        bad = [
            despair / 10,
            1 - integrity,
            max(-BASELINE_CREDIT_CAP, -baseline),
            min(1.0, max(0.0, (density - 2) / 6)),
            low_info_ratio,
        ]
        weights = [0.3, 0.2, 0.2, 0.2, 0.1]
        expected = max(0.0, min(100.0, 100 * (1 - sum(w * b for w, b in zip(weights, bad)))))

        comp = m["composite_score"]
        assert comp.value == pytest.approx(expected, abs=1e-6)
        # And the concrete observed number the current code produces.
        assert comp.value == pytest.approx(65.2121212121212, abs=1e-6)
        assert comp.display == "65"


# --------------------------------------------------------------------------
# (4) Percentile direction is stamped per-metric.
# --------------------------------------------------------------------------


class TestPercentileDirection:
    def _any_metrics(self, metrics_cfg, fix_pattern, stoplist):
        commits = [_c("routine daytime work item", day=0, hour=12, i=i) for i in range(3)]
        scores = {c.sha: 0.0 for c in commits}
        stats = compute_stats(commits, scores, stoplist)
        return compute_metrics(commits, scores, stats, metrics_cfg, fix_pattern)

    def test_directions_and_percentile_presence(self, diag, metrics_cfg, fix_pattern):
        m = self._any_metrics(metrics_cfg, fix_pattern, diag.stoplist)

        # higher_is_worse metrics.
        assert m["night_despair_index"].direction == "higher_is_worse"
        assert m["fix_loop_density"].direction == "higher_is_worse"
        assert m["alexithymia_index"].direction == "higher_is_worse"
        # lower_is_worse metrics (a high integrity / positive baseline is good).
        assert m["boundary_integrity"].direction == "lower_is_worse"
        assert m["emotional_baseline"].direction == "lower_is_worse"

        # Every metric with a configured norm gets a numeric percentile;
        # the composite has no norm, so it stays None.
        for mid in (
            "night_despair_index",
            "boundary_integrity",
            "emotional_baseline",
            "fix_loop_density",
            "alexithymia_index",
        ):
            assert m[mid].percentile is not None
        assert m["composite_score"].percentile is None
        assert m["composite_score"].direction == "higher_is_worse"
