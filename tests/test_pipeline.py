"""End-to-end assertions against the deterministic fixture repository.

Each test pins one symptom's detection and grading to the spec in
symptoms.yaml; docstrings reference the trigger being exercised.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta

import pytest
from rich.console import Console

from commit_shrink.analyzer import SentimentScorer, normalize_message, techdebt_hash
from commit_shrink.history import Trend
from commit_shrink.pipeline import NoCommitsError, assess_repo, load_config
from commit_shrink.report import ReportRenderer

from conftest import by_id


class TestSymptoms:
    def test_fix_loop_grade_iv(self, assessment):
        """5-commit chain, all-caps sample, entirely within 00:00-05:59."""
        d = by_id(assessment, "repeated_fix_loop")
        assert d is not None
        assert d.severity == "IV"
        assert len(d.evidence) == 5
        assert any(c.message == "PLEASE WORK" for c in d.evidence)

    def test_naming_collapse_grade_ii(self, assessment):
        """4 deduped final-variants -> grade II (3-4 variants)."""
        d = by_id(assessment, "naming_collapse")
        assert d is not None
        assert d.severity == "II"
        assert "4" in d.text

    def test_decision_regret_grade_iv(self, assessment):
        """Revert of a revert -> second-order rumination, grade IV."""
        d = by_id(assessment, "decision_regret")
        assert d is not None
        assert d.severity == "IV"

    def test_p0_incident(self, assessment):
        """Sunday 04:47 hotfix mentioning prod."""
        d = by_id(assessment, "p0_incident")
        assert d is not None
        assert d.severity == "IV"

    def test_magical_thinking_grade_iv(self, assessment):
        """'should work' inside the night production incident."""
        d = by_id(assessment, "magical_thinking")
        assert d is not None
        assert d.severity == "IV"

    def test_binge_grade_iv(self, assessment):
        """25 files after >=72h silence, message 'update'."""
        d = by_id(assessment, "binge_committing")
        assert d is not None
        assert d.severity == "IV"

    def test_time_perception_grade_iv(self, assessment):
        """'quick fix' that spawned a confirmed GIT-42.2 chain."""
        d = by_id(assessment, "time_perception")
        assert d is not None
        assert d.severity == "IV"

    def test_emotional_outburst_no_false_positive(self, assessment):
        """Plain 'why' must not trigger; wtf + 卧槽 must (exactly 2 hits)."""
        d = by_id(assessment, "emotional_outburst")
        assert d is not None
        assert len(d.evidence) == 2
        assert all("document why" not in c.message for c in d.evidence)

    def test_alexithymia_grade_ii(self, assessment):
        """Low-information ratio in the 25-40% band."""
        d = by_id(assessment, "alexithymia")
        assert d is not None
        assert d.severity == "II"

    def test_commitment_avoidance_via_chain(self, assessment):
        """WIP ratio below 15% but a 3-commit WIP chain exists."""
        d = by_id(assessment, "commitment_avoidance")
        assert d is not None
        assert d.severity == "I"

    def test_anxious_committing_two_episodes(self, assessment):
        d = by_id(assessment, "anxious_committing")
        assert d is not None

    def test_night_and_boundary_triggered(self, assessment):
        assert by_id(assessment, "night_despair") is not None
        assert by_id(assessment, "boundary_dissolution") is not None

    def test_stockholm_techdebt(self, assessment):
        """With no cross-period history supplied, severity is graded purely
        by this period's hit count and caps out below IV."""
        d = by_id(assessment, "stockholm_techdebt")
        assert d is not None
        assert d.severity == "I"


class TestStockholmRecurrence:
    """GIT-77.7 grade IV: the same normalized 'temporary fix' message
    reappearing >=90 days after history.py first saw it (symptoms.yaml,
    stockholm_techdebt.severity.IV).
    """

    def _techdebt_hit(self, fixture_repo):
        repo, _start, period_end = fixture_repo
        baseline = assess_repo(repo, days=7, until=period_end)
        hit = next(c for c in baseline.commits if "temporary workaround" in c.message)
        return repo, period_end, hit

    def test_grade_iv_when_seen_90_days_ago(self, fixture_repo):
        repo, period_end, hit = self._techdebt_hit(fixture_repo)
        techdebt_history = {
            techdebt_hash(normalize_message(hit.message)): (hit.ts - timedelta(days=91)).isoformat()
        }
        recurring = assess_repo(repo, days=7, until=period_end, techdebt_history=techdebt_history)
        d = by_id(recurring, "stockholm_techdebt")
        assert d.severity == "IV"

    def test_stays_capped_under_90_days(self, fixture_repo):
        repo, period_end, hit = self._techdebt_hit(fixture_repo)
        techdebt_history = {
            techdebt_hash(normalize_message(hit.message)): (hit.ts - timedelta(days=10)).isoformat()
        }
        recent = assess_repo(repo, days=7, until=period_end, techdebt_history=techdebt_history)
        d = by_id(recent, "stockholm_techdebt")
        assert d.severity == "I"

    def test_unrelated_hash_does_not_trigger(self, fixture_repo):
        repo, period_end, hit = self._techdebt_hit(fixture_repo)
        techdebt_history = {
            techdebt_hash("some other message entirely"): (hit.ts - timedelta(days=200)).isoformat()
        }
        unaffected = assess_repo(repo, days=7, until=period_end, techdebt_history=techdebt_history)
        d = by_id(unaffected, "stockholm_techdebt")
        assert d.severity == "I"


class TestMetrics:
    def test_composite_in_range(self, assessment):
        composite = assessment.metrics["composite_score"].value
        assert 0 <= composite <= 100

    def test_composite_reflects_diagnosis_burden(self, assessment):
        """A patient with six grade-IV disorders cannot score in the healthy
        band the norms claim is unobserved (reference: >= 70)."""
        assert assessment.metrics["composite_score"].value < 70

    def test_wip_not_treated_as_scream(self, assessment):
        """'WIP' is a conventional abbreviation; the ALL-CAPS despair offset
        must only fire on real screams like 'PLEASE WORK'."""
        wip = next(c for c in assessment.commits if c.message == "WIP")
        scream = next(c for c in assessment.commits if c.message == "PLEASE WORK")
        assert assessment.scores[wip.sha] == 0.0
        assert abs(assessment.scores[scream.sha] - (-0.87)) < 0.01

    def test_diagnosis_text_has_no_folded_scalar_gaps(self, assessment):
        """YAML folded scalars insert spaces between CJK chars; they must be
        collapsed ('98 分钟内' not '98 分钟 内')."""
        d = by_id(assessment, "repeated_fix_loop")
        assert "分钟 内" not in d.text
        assert "分钟内对同一问题" in d.text

    def test_despair_positive(self, assessment):
        assert assessment.metrics["night_despair_index"].value > 3.0

    def test_all_displayed_metrics_have_percentiles(self, assessment):
        for mid in (
            "night_despair_index",
            "boundary_integrity",
            "emotional_baseline",
            "fix_loop_density",
            "alexithymia_index",
        ):
            assert assessment.metrics[mid].percentile is not None


@pytest.fixture(scope="module")
def scorer():
    cfg = load_config()
    stoplist = next(s for s in cfg["symptoms"] if s["id"] == "alexithymia")["trigger"]["stoplist"]
    return SentimentScorer(cfg["lexicon_patch"], stoplist=stoplist)


class TestScoring:
    def test_cjk_with_acronym_is_not_a_scream(self, scorer):
        """str.isupper() ignores caseless CJK; '修复BUG' must not be despair-corrected."""
        assert scorer.score("修复BUG") == 0.0
        assert scorer.score("终于搞定API") > 0.3  # positive lexicon entries apply

    def test_short_latin_upper_is_not_a_scream(self, scorer):
        assert scorer.score("OK") >= 0.0

    def test_real_scream_is_corrected(self, scorer):
        assert abs(scorer.score("PLEASE WORK") - (-0.87)) < 0.01


class TestWindowAndEdges:
    def test_period_covers_exactly_days_calendar_days(self, assessment):
        span = (assessment.period_end.date() - assessment.period_start.date()).days + 1
        assert span == 7
        assert assessment.period_start.hour == 0

    def test_empty_repo_raises_no_commits(self, tmp_path):
        """A freshly-initialized repo (unborn HEAD) degrades gracefully."""
        repo = tmp_path / "empty"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        with pytest.raises(NoCommitsError):
            assess_repo(repo, days=7)

    def test_rename_preserves_topic_continuity(self, tmp_path):
        """A fix chain should survive old.py -> new.py renames."""
        repo = tmp_path / "rename-chain"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "t"], check=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@t.t"], check=True
        )

        base = datetime.now().astimezone().replace(
            hour=9, minute=0, second=0, microsecond=0
        )

        def commit(
            message: str, minutes: int, path: str | None = None, content: str = ""
        ) -> None:
            when = (base + timedelta(minutes=minutes)).isoformat()
            if path:
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", message],
                check=True,
                capture_output=True,
                env=env,
            )

        commit("fix login bug", 0, "login.py", "v1\n")
        commit("fix login bug again", 10, "login.py", "v2\n")
        subprocess.run(["git", "-C", str(repo), "mv", "login.py", "auth.py"], check=True)
        commit("rename login to auth", 20)
        commit("fix auth bug", 30, "auth.py", "v3\n")

        assessment = assess_repo(repo, days=1, until=base + timedelta(hours=1))
        diagnosis = by_id(assessment, "repeated_fix_loop")
        assert diagnosis is not None
        assert [c.subject for c in diagnosis.evidence] == [
            "fix login bug",
            "fix login bug again",
            "rename login to auth",
            "fix auth bug",
        ]


class TestReport:
    def _render(self, assessment, trend=None) -> str:
        cfg = load_config()
        console = Console(record=True, width=80)
        ReportRenderer(cfg).render(console, assessment, trend)
        return console.export_text()

    def test_all_sections_present(self, assessment):
        out = self._render(assessment)
        cfg = load_config()
        for title in cfg["report_copy"]["sections"].values():
            assert title in out

    def test_no_trend_shows_first_assessment_placeholder(self, assessment):
        """Unchanged default: no Trend passed -> same output as before
        cross-period history existed (plan-commit-shrink.md: additive only).
        """
        out = self._render(assessment)
        assert "首次评估，无历史对照" in out
        assert "较上周" not in out

    def test_trend_fills_previous_period_column(self, assessment):
        trend = Trend(
            metric_previous={"night_despair_index": "6.1"},
            composite_delta=None,
            decline_streak=0,
            extrapolated_week=None,
        )
        out = self._render(assessment, trend)
        assert "6.1" in out
        assert "首次评估，无历史对照" not in out

    def test_trend_streak_matches_golden_sample_wording(self, assessment):
        """Reproduces docs/report-sample.md's own internally-consistent
        numbers: 52 -> 43 -> 34 is a 3-period decline at slope -9, which
        projects to hit 0 four periods out (ceil(34/9) = 4)."""
        week = assessment.period_end.isocalendar().week
        trend = Trend(
            metric_previous={},
            composite_delta=-9,
            decline_streak=3,
            extrapolated_week=week + 4,
        )
        # Collapse Rich's 80-column line wrapping before matching a phrase
        # that could legally fall across a wrap boundary at that width.
        out = " ".join(self._render(assessment, trend).split())
        assert "较上周 -9 分" in out
        assert "连续第 3 周下降" in out
        assert f"预计第 {week + 4} 评估周" in out

    def test_trend_without_streak_omits_extrapolation(self, assessment):
        """A single prior period (streak=1, e.g. an improvement) reports the
        delta but not a decline streak that doesn't actually exist."""
        trend = Trend(
            metric_previous={}, composite_delta=5, decline_streak=1, extrapolated_week=None
        )
        out = self._render(assessment, trend)
        assert "较上周 +5 分" in out
        assert "连续第" not in out
        assert "外推" not in out

    def test_evidence_masked(self, assessment):
        """Safety: outburst lexicon hits never appear unmasked in the report.

        Mechanism: the masked-subjects map redacts every quotable subject,
        regardless of whether the record makes the report's top-3 cut.
        """
        out = self._render(assessment)
        assert "卧槽" not in out
        d = by_id(assessment, "emotional_outburst")
        zh_commit = next(c for c in d.evidence if "修复缓存" in c.message)
        assert "卧×" in assessment.masked_subjects[zh_commit.sha]

    def test_ranking_primary_is_worst(self, assessment):
        assert assessment.diagnoses[0].severity == "IV"
