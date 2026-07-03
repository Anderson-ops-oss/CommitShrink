"""Tests for commit_shrink.collector: git log parsing and encoding safety."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from commit_shrink import collector
from commit_shrink.collector import collect


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "A"], cwd=path, check=True)
    return path


def _commit(path: Path, message: str, when: datetime) -> None:
    (path / "f.txt").write_text(message, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    iso = when.isoformat()
    env = {**os.environ, "GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso}
    subprocess.run(
        ["git", "commit", "--quiet", "-m", message], cwd=path, check=True, env=env
    )


class TestNonUtf8LocaleSafety:
    """`_run_git`/`remote_origin_url` must decode git's output (always UTF-8)
    as UTF-8 regardless of the platform's default locale encoding. Before
    this was pinned explicitly, `subprocess.run(text=True)` fell back to
    `locale.getencoding()` -- cp1252 on a typical Windows machine -- which
    cannot decode CJK commit messages (the exact content this tool's
    lexicon patch targets). The decode error happened in a background
    reader thread, so it never raised in the caller; `proc.stdout` was
    simply left None, and `collect()` crashed on `None.split(...)`.

    `subprocess._text_encoding` is monkeypatched (rather than the process
    locale, which utf8_mode can short-circuit) so this reproduces on any
    platform/CI, not just a non-UTF-8-locale machine.
    """

    def test_collect_survives_a_non_utf8_default_locale(self, tmp_path, monkeypatch):
        monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
        repo = _init_repo(tmp_path / "r")
        when = datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc)
        _commit(repo, "修复缓存又崩了 卧槽", when)

        commits = collect(repo, since=when - timedelta(days=1), until=when + timedelta(days=1))

        assert len(commits) == 1
        assert commits[0].message.strip() == "修复缓存又崩了 卧槽"

    def test_remote_origin_url_survives_a_non_utf8_default_locale(self, tmp_path, monkeypatch):
        monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
        repo = _init_repo(tmp_path / "r")
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/x/y.git"],
            cwd=repo,
            check=True,
        )

        assert collector.remote_origin_url(repo) == "https://github.com/x/y.git"
