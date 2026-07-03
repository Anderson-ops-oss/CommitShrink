"""Tests for commit_shrink.history: fingerprinting and the JSONL cache."""

from __future__ import annotations

import dataclasses
import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from commit_shrink.collector import remote_origin_url, root_commit_shas
from commit_shrink.pipeline import assess_repo
from commit_shrink.history import (
    NO_TREND,
    FingerprintError,
    HistoryEntry,
    append_entry,
    build_techdebt_index,
    compute_trend,
    entry_from_assessment,
    finalize,
    load_context,
    load_history,
    record_assessment,
    repo_fingerprint,
)


def _init_repo(path: Path) -> Path:
    """Each repo's file content includes its own path so distinct repos never
    produce byte-identical initial commits -- git hashes commits by content,
    not location, so two repos with the same message/tree/timestamp would
    otherwise collide onto the same root commit sha.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "A"], cwd=path, check=True)
    (path / "f.txt").write_text(str(path))
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "init"], cwd=path, check=True)
    return path


class TestCollectorGitPlumbing:
    def test_remote_origin_url_present(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/x/y.git"], cwd=repo, check=True
        )
        assert remote_origin_url(repo) == "https://github.com/x/y.git"

    def test_remote_origin_url_absent(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        assert remote_origin_url(repo) is None

    def test_root_commit_shas(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        roots = root_commit_shas(repo)
        assert len(roots) == 1
        assert len(roots[0]) == 40

    def test_root_commit_shas_no_commits(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=empty, check=True)
        assert root_commit_shas(empty) == []


class TestRepoFingerprint:
    def test_same_origin_url_form_is_stable(self, tmp_path):
        a = _init_repo(tmp_path / "a")
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/owner/repo.git"], cwd=a, check=True
        )
        b = _init_repo(tmp_path / "b")
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"], cwd=b, check=True
        )
        assert repo_fingerprint([a]) == repo_fingerprint([b])

    def test_different_origin_urls_differ(self, tmp_path):
        a = _init_repo(tmp_path / "a")
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/owner/repo-one.git"],
            cwd=a,
            check=True,
        )
        b = _init_repo(tmp_path / "b")
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/owner/repo-two.git"],
            cwd=b,
            check=True,
        )
        assert repo_fingerprint([a]) != repo_fingerprint([b])

    def test_no_remote_falls_back_to_root_commit(self, tmp_path):
        a = _init_repo(tmp_path / "a")
        b = _init_repo(tmp_path / "b")
        assert repo_fingerprint([a]) != repo_fingerprint([b])

    def test_no_remote_and_no_commits_raises(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=empty, check=True)
        with pytest.raises(FingerprintError):
            repo_fingerprint([empty])

    def test_multi_repo_fingerprint_is_order_independent(self, tmp_path):
        a = _init_repo(tmp_path / "a")
        b = _init_repo(tmp_path / "b")
        assert repo_fingerprint([a, b]) == repo_fingerprint([b, a])
        assert repo_fingerprint([a, b]) != repo_fingerprint([a])


class TestAppendAndLoadHistory:
    def test_load_history_on_missing_file_returns_empty(self, tmp_path):
        assert load_history("dev@example.com", "fp1", path=tmp_path / "nope.jsonl") == []

    def test_round_trips_and_filters_by_key(self, tmp_path, assessment):
        target = tmp_path / "history.jsonl"
        e1 = entry_from_assessment(assessment, "fp1", "local")
        append_entry(e1, path=target)

        other_patient = entry_from_assessment(assessment, "fp1", "local")
        other_patient.patient_email = "someone-else@example.com"
        append_entry(other_patient, path=target)

        other_repo = entry_from_assessment(assessment, "fp2", "local")
        append_entry(other_repo, path=target)

        loaded = load_history(assessment.patient_email, "fp1", path=target)
        assert len(loaded) == 1
        assert loaded[0].period_end == assessment.period_end.isoformat()
        assert loaded[0].metrics["composite_score"]["display"] == (
            assessment.metrics["composite_score"].display
        )
        assert [d["id"] for d in loaded[0].diagnoses] == [d.id for d in assessment.diagnoses]

    def test_rerun_of_same_period_collapses_to_latest(self, tmp_path, assessment):
        target = tmp_path / "history.jsonl"
        first = entry_from_assessment(assessment, "fp1", "local")
        append_entry(first, path=target)

        second = entry_from_assessment(assessment, "fp1", "local")
        second.metrics["composite_score"]["display"] = "0"
        append_entry(second, path=target)

        loaded = load_history(assessment.patient_email, "fp1", path=target)
        assert len(loaded) == 1
        assert loaded[0].metrics["composite_score"]["display"] == "0"

    def test_multiple_periods_sort_oldest_first(self, tmp_path, assessment):
        target = tmp_path / "history.jsonl"
        older = entry_from_assessment(assessment, "fp1", "local")
        older.period_end = "2026-06-01T23:59:00+00:00"
        append_entry(older, path=target)

        newer = entry_from_assessment(assessment, "fp1", "local")
        newer.period_end = "2026-06-08T23:59:00+00:00"
        append_entry(newer, path=target)

        loaded = load_history(assessment.patient_email, "fp1", path=target)
        assert [e.period_end for e in loaded] == [older.period_end, newer.period_end]

    def test_appended_lines_are_one_json_object_each(self, tmp_path, assessment):
        target = tmp_path / "history.jsonl"
        append_entry(entry_from_assessment(assessment, "fp1", "local"), path=target)
        append_entry(entry_from_assessment(assessment, "fp1", "local"), path=target)
        lines = target.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # must not raise


class TestRecordAssessment:
    def test_records_a_loadable_entry(self, tmp_path, fixture_repo, assessment):
        repo, _start, _period_end = fixture_repo
        target = tmp_path / "history.jsonl"
        record_assessment(assessment, [repo], source="local", path=target)
        loaded = load_history(assessment.patient_email, repo_fingerprint([repo]), path=target)
        assert len(loaded) == 1
        assert loaded[0].source == "local"

    def test_swallows_fingerprint_failure(self, tmp_path, assessment):
        empty = tmp_path / "not-a-repo"
        empty.mkdir()
        target = tmp_path / "history.jsonl"
        record_assessment(assessment, [empty], source="local", path=target)
        assert not target.exists()

    def test_load_history_without_patient_filter_returns_all_patients(self, tmp_path, assessment):
        """Used by the GIT-77.7 recurrence check, which is repo-scoped, not
        patient-scoped -- the same 'temporary fix' text matters regardless
        of who committed it."""
        target = tmp_path / "history.jsonl"
        mine = entry_from_assessment(assessment, "fp1", "local")
        append_entry(mine, path=target)
        theirs = entry_from_assessment(assessment, "fp1", "local")
        theirs.patient_email = "someone-else@example.com"
        theirs.period_end = "2026-05-01T23:59:00+00:00"
        append_entry(theirs, path=target)

        loaded = load_history(None, "fp1", path=target)
        assert {e.patient_email for e in loaded} == {mine.patient_email, "someone-else@example.com"}

    def test_dedup_keys_on_patient_and_period_not_period_alone(self, tmp_path, assessment):
        """Two different patients recording the same period_end for the same
        repo must not collapse into a single entry."""
        target = tmp_path / "history.jsonl"
        a = entry_from_assessment(assessment, "fp1", "local")
        b = entry_from_assessment(assessment, "fp1", "local")
        b.patient_email = "someone-else@example.com"
        append_entry(a, path=target)
        append_entry(b, path=target)

        loaded = load_history(None, "fp1", path=target)
        assert len(loaded) == 2


def _entry(period_end: str, composite_display: str, techdebt_hashes=None, patient="dev@example.com"):
    return HistoryEntry(
        patient_email=patient,
        repo_fingerprint="fp1",
        source="local",
        period_end=period_end,
        recorded_at=period_end,
        metrics={
            "night_despair_index": {"value": 1.0, "display": "1.0"},
            "composite_score": {"value": float(composite_display), "display": composite_display},
        },
        diagnoses=[],
        techdebt_hashes=techdebt_hashes or [],
    )


class TestBuildTechdebtIndex:
    def test_picks_earliest_period_per_hash(self):
        entries = [
            _entry("2026-03-01T23:59:00+00:00", "50", techdebt_hashes=["h1"]),
            _entry("2026-01-01T23:59:00+00:00", "60", techdebt_hashes=["h1", "h2"]),
        ]
        index = build_techdebt_index(entries)
        assert index["h1"] == "2026-01-01T23:59:00+00:00"
        assert index["h2"] == "2026-01-01T23:59:00+00:00"

    def test_empty_entries_yield_empty_index(self):
        assert build_techdebt_index([]) == {}


def _fake_assessment(period_end: datetime, composite_display: str):
    """A minimal stand-in for Assessment: compute_trend only ever reads
    `.period_end` and `.metrics["composite_score"].display` off its input,
    so this avoids mutating the real (session-scoped, shared-across-tests)
    `assessment` fixture just to exercise different composite values.
    """
    return SimpleNamespace(
        period_end=period_end,
        metrics={"composite_score": SimpleNamespace(display=composite_display)},
    )


class TestComputeTrend:
    def test_no_prior_history_returns_no_trend(self, assessment):
        assert compute_trend(assessment, []) is NO_TREND

    def test_entry_for_the_same_period_is_excluded(self, assessment):
        """A rerun of the current period must not be compared to itself."""
        same_period = _entry(assessment.period_end.isoformat(), "999")
        assert compute_trend(assessment, [same_period]) is NO_TREND

    def test_single_prior_period_improving_has_no_streak(self):
        end = datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc)
        current = _fake_assessment(end, "40")
        prior = _entry((end - timedelta(days=7)).isoformat(), "35")
        trend = compute_trend(current, [prior])
        assert trend.composite_delta == 5
        assert trend.decline_streak == 1
        assert trend.extrapolated_week is None

    def test_single_prior_period_declining_is_streak_two(self):
        end = datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc)
        current = _fake_assessment(end, "34")
        prior = _entry((end - timedelta(days=7)).isoformat(), "39")
        trend = compute_trend(current, [prior])
        assert trend.composite_delta == -5
        assert trend.decline_streak == 2
        assert trend.extrapolated_week == end.isocalendar().week + math.ceil(34 / 5)

    def test_golden_sample_streak_and_extrapolation(self):
        """Reproduces docs/report-sample.md: composite 52 -> 43 -> 34, a
        3-period decline at slope -9, projected to hit 0 in 4 more periods."""
        end = datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc)
        current = _fake_assessment(end, "34")
        prior = [
            _entry((end - timedelta(days=14)).isoformat(), "52"),
            _entry((end - timedelta(days=7)).isoformat(), "43"),
        ]
        trend = compute_trend(current, prior)
        assert trend.composite_delta == -9
        assert trend.decline_streak == 3
        assert trend.extrapolated_week == end.isocalendar().week + 4

    def test_streak_stops_at_first_non_decline_scanning_backward(self):
        end = datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc)
        current = _fake_assessment(end, "34")
        prior = [
            _entry((end - timedelta(days=21)).isoformat(), "30"),
            _entry((end - timedelta(days=14)).isoformat(), "50"),
            _entry((end - timedelta(days=7)).isoformat(), "43"),
        ]
        trend = compute_trend(current, prior)
        # 30 -> 50 rises, breaking the decline before it reaches the 30 entry.
        assert trend.decline_streak == 3

    def test_metric_previous_reads_from_the_latest_prior_entry(self):
        end = datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc)
        current = _fake_assessment(end, "34")
        prior = [
            _entry((end - timedelta(days=14)).isoformat(), "52"),
            _entry((end - timedelta(days=7)).isoformat(), "43"),
        ]
        trend = compute_trend(current, prior)
        assert trend.metric_previous["night_despair_index"] == "1.0"


class TestLoadContextAndFinalize:
    def test_load_context_on_fresh_repo_has_no_techdebt_yet(self, tmp_path, fixture_repo):
        repo, _start, _period_end = fixture_repo
        ctx = load_context([repo], path=tmp_path / "history.jsonl")
        assert ctx.fingerprint is not None
        assert ctx.techdebt_index == {}

    def test_load_context_degrades_on_unidentifiable_repo(self, tmp_path):
        empty = tmp_path / "not-a-repo"
        empty.mkdir()
        ctx = load_context([empty], path=tmp_path / "history.jsonl")
        assert ctx.fingerprint is None
        assert ctx.techdebt_index == {}

    def test_finalize_with_no_fingerprint_returns_no_trend_and_writes_nothing(
        self, tmp_path, assessment
    ):
        empty = tmp_path / "not-a-repo"
        empty.mkdir()
        ctx = load_context([empty], path=tmp_path / "history.jsonl")
        target = tmp_path / "history.jsonl"
        trend = finalize(ctx, assessment, [empty], source="local", path=target)
        assert trend is NO_TREND
        assert not target.exists()

    def test_finalize_records_and_next_run_sees_the_trend(self, tmp_path, fixture_repo):
        """End-to-end: first run has no history; recording it makes a second
        run for a later period see it as the 'previous' period. The fixture
        repo only has one week of commits, so the "later" run is simulated
        by replacing a1's period_end rather than re-collecting from git --
        compute_trend's actual math is already covered by TestComputeTrend;
        this test is only about the load_context/finalize wiring.
        """
        repo, _start, period_end = fixture_repo
        target = tmp_path / "history.jsonl"

        ctx1 = load_context([repo], path=target)
        a1 = assess_repo(repo, days=7, until=period_end, techdebt_history=ctx1.techdebt_index)
        trend1 = finalize(ctx1, a1, [repo], source="local", path=target)
        assert trend1 is NO_TREND
        assert target.exists()

        a2 = dataclasses.replace(a1, period_end=period_end + timedelta(days=7))
        ctx2 = load_context([repo], path=target)
        trend2 = finalize(ctx2, a2, [repo], source="local", path=target)
        assert trend2.composite_delta == 0
        assert trend2.metric_previous["composite_score"] == a1.metrics["composite_score"].display
