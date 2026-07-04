"""Tests for commit_shrink.remote -- fully offline via file:// URLs.

A real network clone against github.com is exercised manually, not here:
CI shouldn't depend on network availability or GitHub's uptime/rate limits.
git itself supports file:// as a first-class transport, so cloning a local
fixture repo through that scheme exercises the exact same clone/cleanup
code path a real https:// URL would, with zero network dependency.
"""

from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from commit_shrink.collector import GIT_WINDOW_SLACK, collect
from commit_shrink.pipeline import FETCH_PADDING, assess_repo, compute_window
from commit_shrink.remote import (
    CloneError,
    RemoteAuthorRequiredError,
    is_remote_spec,
    local_repo,
    require_author_for_remote,
)


def _window_blob_oids(repo: Path, since) -> set[str]:
    """Blob object ids a --numstat over the window would need (tree-level)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "log", "--raw", "--no-abbrev",
         f"--since={since.isoformat()}", "--pretty=format:"],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout
    oids: set[str] = set()
    for line in out.splitlines():
        if line.startswith(":") and not line.startswith("::"):
            parts = line.split()
            if len(parts) >= 4:
                for oid in (parts[2], parts[3]):
                    if oid != "0" * 40 and len(oid) == 40:
                        oids.add(oid)
    return oids


def _local_object_ids(repo: Path) -> set[str]:
    """Object ids physically present in the local store (missing promisor
    objects are not enumerated, so this excludes not-yet-fetched blobs)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch-check=%(objectname)",
         "--batch-all-objects"],
        capture_output=True, text=True,
    ).stdout
    return set(out.split())


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

    def test_clone_is_blobless_partial_and_backfills_window(self, fixture_repo):
        """The clone is a blobless partial clone (not shallow), so full history
        metadata is present; backfill_window_blobs then pre-populates the
        window's diff blobs locally, so collect()'s --numstat needs no lazy
        fetch.
        """
        source_repo, _start, period_end = fixture_repo

        with local_repo(f"file://{source_repo}", days=7, until=period_end) as cloned:
            pcf = subprocess.run(
                ["git", "-C", str(cloned), "config", "--get", "remote.origin.partialclonefilter"],
                capture_output=True, text=True,
            ).stdout.strip()
            assert pcf == "blob:none"  # blobless partial clone...
            assert not (cloned / ".git" / "shallow").exists()  # ...not a shallow one

            # Full history is present: the old shallow clone excluded the
            # bootstrap commit; a blobless clone keeps every commit/tree.
            all_commits = collect(cloned, since=period_end.replace(year=2000), until=period_end)
            assert any(c.subject == "chore: bootstrap project" for c in all_commits)

            # The window's diff blobs were fetched up front, not left as
            # promised-but-missing objects.
            start, _ = compute_window(7, period_end)
            backfill_since = start - FETCH_PADDING - GIT_WINDOW_SLACK
            window_oids = _window_blob_oids(cloned, backfill_since)
            assert window_oids, "expected the fixture window to touch some files"
            assert window_oids <= _local_object_ids(cloned)

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

    def test_clone_and_collect_survive_a_non_utf8_default_locale(self, fixture_repo, monkeypatch):
        """The fixture repo's Friday commit ("修复缓存又崩了 卧槽") is CJK text.
        Forcing subprocess's text-mode encoding resolution to cp1252 (the
        typical Windows default) reproduces, on any platform, what a
        Windows machine hit before local_repo()'s clone and collect() both
        pinned encoding="utf-8" explicitly: git's UTF-8 output silently
        failed to decode and calling code crashed on a None stdout.
        """
        monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
        source_repo, _start, period_end = fixture_repo

        with local_repo(f"file://{source_repo}", days=7, until=period_end) as cloned_path:
            commits = collect(cloned_path, since=period_end - timedelta(days=7), until=period_end)

        assert any("修复缓存又崩了" in c.message for c in commits)
