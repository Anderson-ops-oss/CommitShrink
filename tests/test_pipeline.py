"""End-to-end assertions against the deterministic fixture repository.

Each test pins one symptom's detection and grading to the spec in
symptoms.yaml; docstrings reference the trigger being exercised.
"""

from __future__ import annotations

import subprocess

import pytest
from rich.console import Console

from commit_shrink.analyzer import SentimentScorer
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
        d = by_id(assessment, "stockholm_techdebt")
        assert d is not None
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


class TestReport:
    def _render(self, assessment) -> str:
        cfg = load_config()
        console = Console(record=True, width=80)
        ReportRenderer(cfg).render(console, assessment)
        return console.export_text()

    def test_all_sections_present(self, assessment):
        out = self._render(assessment)
        cfg = load_config()
        for title in cfg["report_copy"]["sections"].values():
            assert title in out

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
