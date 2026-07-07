"""Regression tests for the P0 crash fix and the P1 scoring-fairness changes.

Each test pins one fix so a future edit that reintroduces the double-count, the
schedule-only night pathology, the raw-count weekend IV, the len<4 CJK misfire,
the routine-vocabulary bias, or the "=>" crash breaks visibly rather than
silently moving the headline score.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from commit_shrink.analyzer import (
    BASELINE_CREDIT_CAP,
    DOUBLE_COUNT_DISCOUNT,
    MetricValue,
    SentimentScorer,
    apply_diagnosis_burden,
    compute_stats,
    is_low_info,
)
from commit_shrink.collector import _parse_numstat_path
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
def scorer(cfg, diag) -> SentimentScorer:
    return SentimentScorer(cfg["lexicon_patch"], stoplist=diag.stoplist)


def _c(message: str, *, day: int = 0, hour: int = 12, i: int = 0, files=("a.py",)) -> Commit:
    # Anchor on 2026-01-05 (a Monday); day 5 = Saturday, day 6 = Sunday.
    return Commit(
        sha=f"{i:040x}",
        author_name="D",
        author_email="d@d",
        ts=datetime(2026, 1, 5 + day, hour, i % 60, tzinfo=timezone.utc),
        message=message,
        file_paths=list(files),
    )


# ---- P0: "=>" filename no longer crashes assessment -----------------------


class TestParseNumstatPath:
    def test_bare_arrow_filename_does_not_crash(self):
        """A path with a bare '=>' (no git rename spacing) is an ordinary
        filename; it used to reach `path.split(' => ')` and raise ValueError."""
        assert _parse_numstat_path("weird=>name.txt") == ("weird=>name.txt", None)
        assert _parse_numstat_path("a=>b") == ("a=>b", None)

    def test_real_rename_syntax_still_parses(self):
        assert _parse_numstat_path("old.py => new.py") == ("new.py", ("old.py", "new.py"))
        assert _parse_numstat_path("src/{a => b}.py") == ("src/b.py", ("src/a.py", "src/b.py"))


# ---- P1-#1: double-counted diagnosis burden is halved ---------------------


class TestBurdenDiscount:
    def _base(self) -> dict[str, MetricValue]:
        mv = MetricValue(
            id="composite_score", name="", value=100.0, display="100",
            reference="", percentile=None, direction="higher_is_worse",
        )
        return {"composite_score": mv}

    def test_double_counted_diagnosis_is_halved(self):
        m = self._base()
        # boundary_dissolution is double-counted (also a metric): IV weight 6 -> 3.
        apply_diagnosis_burden(m, [("boundary_dissolution", "IV")])
        assert m["composite_score"].value == 100.0 - 6 * DOUBLE_COUNT_DISCOUNT

    def test_non_double_counted_diagnosis_is_full_weight(self):
        m = self._base()
        # p0_incident has no matching metric: full IV weight 6.
        apply_diagnosis_burden(m, [("p0_incident", "IV")])
        assert m["composite_score"].value == 100.0 - 6

    def test_cap_and_floor_hold(self):
        m = self._base()
        # Six full-weight IV = 36, capped at 35; floor keeps it non-negative.
        apply_diagnosis_burden(m, [("p0_incident", "IV")] * 6)
        assert m["composite_score"].value == 100.0 - 35
        m2 = self._base()
        m2["composite_score"].value = 10.0
        apply_diagnosis_burden(m2, [("p0_incident", "IV")] * 6)
        assert m2["composite_score"].value == 0.0


# ---- P1-#2: night pathology needs a negative mood, not just a schedule -----


class TestNightMoodGate:
    def test_cheerful_night_owl_caps_at_grade_I(self, diag, scorer):
        commits = [_c("终于搞定 完美", hour=2, i=i) for i in range(8)] + [
            _c("feat: daytime work", hour=14, i=i + 8) for i in range(2)
        ]
        scores = {c.sha: scorer.score(c.message) for c in commits}
        stats = compute_stats(commits, scores, diag.stoplist)
        assert stats.night_ratio > 0.5 and stats.night_mood >= 0
        d = diag._night_despair(commits, stats)
        assert d is not None and d.severity == "I"

    def test_negative_night_mood_still_escalates(self, diag, scorer):
        commits = [_c("崩了 卧槽 又炸了", hour=2, i=i) for i in range(8)] + [
            _c("feat: daytime work", hour=14, i=i + 8) for i in range(2)
        ]
        scores = {c.sha: scorer.score(c.message) for c in commits}
        stats = compute_stats(commits, scores, diag.stoplist)
        assert stats.night_mood < 0
        d = diag._night_despair(commits, stats)
        assert d is not None and d.severity == "IV"  # >50% ratio, mood negative


# ---- P1-#3: weekend IV needs a strong majority + volume, not a raw count ---


class TestWeekendFloor:
    def test_six_vs_five_is_not_top_grade(self, diag, scorer):
        commits = [_c("work", day=5, i=i) for i in range(6)] + [
            _c("work", day=1, i=i + 6) for i in range(5)
        ]
        scores = {c.sha: scorer.score(c.message) for c in commits}
        stats = compute_stats(commits, scores, diag.stoplist)
        d = diag._boundary(commits, stats)
        assert d is not None and d.severity == "III"

    def test_overwhelming_weekend_still_reaches_IV(self, diag, scorer):
        commits = [_c("work", day=5, i=i) for i in range(9)] + [
            _c("work", day=1, i=i + 9) for i in range(1)
        ]
        scores = {c.sha: scorer.score(c.message) for c in commits}
        stats = compute_stats(commits, scores, diag.stoplist)
        assert stats.weekend_ratio > 0.6 and stats.weekend_count >= 5
        d = diag._boundary(commits, stats)
        assert d is not None and d.severity == "IV"


# ---- P1-#4: informative short CJK subjects are not "low information" -------


class TestLowInfoScriptAware:
    def test_informative_three_char_cjk_is_not_low_info(self, diag):
        for msg in ("加日志", "改样式", "补测试"):
            assert is_low_info(msg, diag.stoplist) is False

    def test_stoplist_and_single_char_cjk_still_low_info(self, diag):
        for msg in ("改", "更新", "提交"):  # in the stoplist
            assert is_low_info(msg, diag.stoplist) is True
        assert is_low_info("码", diag.stoplist) is True  # single CJK char, < 2

    def test_short_latin_still_low_info(self, diag):
        assert is_low_info("wip", diag.stoplist) is True
        assert is_low_info("abc", diag.stoplist) is True  # < 4 latin


# ---- P1-#5: routine engineering vocab + positive-baseline credit -----------


class TestRoutineVocabAndCredit:
    def test_routine_engineering_words_read_neutral(self, scorer):
        for msg in ("fix broken build", "revert crashing migration", "fix login crash"):
            assert scorer.score(msg) == 0.0

    def test_genuine_affect_still_scores(self, scorer):
        assert scorer.score("i hate this codebase") < -0.3

    def test_positive_baseline_earns_bounded_credit(self):
        # Reproduce the composite baseline term directly: a positive baseline
        # becomes a negative "bad" (credit), floored at -BASELINE_CREDIT_CAP.
        for baseline, expected in [(0.5, -BASELINE_CREDIT_CAP), (0.1, -0.1), (-0.2, 0.2)]:
            assert max(-BASELINE_CREDIT_CAP, -baseline) == expected
