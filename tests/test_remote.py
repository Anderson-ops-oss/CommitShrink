"""Tests for commit_shrink.remote -- fully offline via file:// URLs.

A real network clone against github.com is exercised manually, not here:
CI shouldn't depend on network availability or GitHub's uptime/rate limits.
git itself supports file:// as a first-class transport, so cloning a local
fixture repo through that scheme exercises the exact same clone/cleanup
code path a real https:// URL would, with zero network dependency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from commit_shrink.collector import collect
from commit_shrink.pipeline import assess_repo
from commit_shrink.remote import (
    CloneError,
    RemoteAuthorRequiredError,
    is_remote_spec,
    local_repo,
    require_author_for_remote,
)


class TestIsRemoteSpec:
    @pytest.mark.parametrize(
        "spec",
        [
            "https://github.com/owner/repo",
            "https://github.com/owner/repo.git",
            "http://example.com/x/y.git",
            "git@github.com:owner/repo.git",
            "ssh://git@github.com/owner/repo.git",
            "file:///tmp/some-repo",
            "github:owner/repo",
            "github:owner/repo.git",
        ],
    )
    def test_recognizes_remote_forms(self, spec):
        assert is_remote_spec(spec) is True

    @pytest.mark.parametrize(
        "spec",
        [
            ".",
            "..",
            "/absolute/local/path",
            "relative/sub/dir",
            "fixture-repo",
            "owner/repo",  # deliberately NOT recognized without a github: prefix
        ],
    )
    def test_local_paths_are_not_remote(self, spec):
        assert is_remote_spec(spec) is False


class TestRequireAuthorForRemote:
    def test_remote_without_author_raises(self):
        with pytest.raises(RemoteAuthorRequiredError):
            require_author_for_remote("github:owner/repo", None)
        with pytest.raises(RemoteAuthorRequiredError):
            require_author_for_remote("github:owner/repo", "   ")

    def test_remote_with_author_ok(self):
        require_author_for_remote("github:owner/repo", "dev@example.com")

    def test_local_never_raises(self):
        require_author_for_remote(".", None)
        require_author_for_remote("/some/path", "anyone@example.com")


class TestLocalRepoContextManager:
    def test_local_spec_yields_path_unchanged_without_cloning(self, tmp_path):
        with local_repo(str(tmp_path), days=7, until=None) as resolved:
            assert resolved == tmp_path

    def test_remote_clone_via_file_url_round_trips_through_assess_repo(self, fixture_repo):
        """The clone must be usable by the exact same assess_repo() pipeline,
        and produce the same diagnosis as reading the source repo directly.
        """
        source_repo, _start, period_end = fixture_repo
        direct = assess_repo(source_repo, days=7, until=period_end)

        file_url = f"file://{source_repo}"
        assert is_remote_spec(file_url)

        with local_repo(file_url, days=7, until=period_end) as cloned_path:
            assert cloned_path != source_repo
            assert cloned_path.is_dir()
            assert (cloned_path / ".git").exists()
            via_clone = assess_repo(cloned_path, days=7, until=period_end)

        # The clone is torn down once the `with` block exits.
        assert not cloned_path.exists()

        assert via_clone.stats.total == direct.stats.total
        assert via_clone.patient_email == direct.patient_email
        assert [d.id for d in via_clone.diagnoses] == [d.id for d in direct.diagnoses]

    def test_shallow_clone_is_bounded_not_full_history(self, fixture_repo):
        """--shallow-since must actually shorten the clone, not silently
        fall back to a full clone (which would defeat the point). The fixture
        repo's bootstrap commit sits 5 days before the assessed Monday, one
        day earlier than the shallow-since cutoff (start - FETCH_PADDING =
        Monday - 3 days), so a real shallow clone must exclude exactly it.
        """
        source_repo, _start, period_end = fixture_repo
        far_past = period_end.replace(year=2000)
        full_commits = collect(source_repo, since=far_past, until=period_end)

        with local_repo(f"file://{source_repo}", days=7, until=period_end) as cloned_path:
            assert (cloned_path / ".git" / "shallow").exists(), "expected a shallow clone marker"
            shallow_commits = collect(cloned_path, since=far_past, until=period_end)

        assert len(shallow_commits) == len(full_commits) - 1
        assert not any(c.subject == "chore: bootstrap project" for c in shallow_commits)
        assert any(c.subject == "chore: bootstrap project" for c in full_commits)

    def test_clone_failure_raises_clone_error_not_a_crash(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(CloneError):
            with local_repo(f"file://{nonexistent}", days=7, until=None):
                pass

    def test_github_shorthand_expands_to_https_url(self):
        from commit_shrink.remote import _resolve_clone_url

        assert _resolve_clone_url("github:torvalds/linux") == "https://github.com/torvalds/linux.git"
        assert _resolve_clone_url("github:a/b.git") == "https://github.com/a/b.git"
        assert _resolve_clone_url("https://gitlab.com/x/y.git") == "https://gitlab.com/x/y.git"
