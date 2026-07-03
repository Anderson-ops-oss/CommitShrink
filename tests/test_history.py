"""Tests for commit_shrink.history: fingerprinting and the JSONL cache."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from commit_shrink.collector import remote_origin_url, root_commit_shas
from commit_shrink.history import (
    FingerprintError,
    append_entry,
    entry_from_assessment,
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
