"""Tests for the gh-user aggregate feature: spec parsing, multi-repo cloning,
the merged-timeline assess_repos(), and person-anchored trend continuity.

All offline: multi-clone uses file:// URLs of throwaway repos built here, and
the one end-to-end run_assessment() path stubs the GitHub API and redirects the
history cache into tmp so it never touches the real cache.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from commit_shrink.pipeline import assess_repo, assess_repos, load_config
from commit_shrink.remote import (
    RemoteAuthorRequiredError,
    is_user_spec,
    local_repos,
    parse_user_spec,
    require_author_for_remote,
)
from commit_shrink.history import user_fingerprint

WED = datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc)  # a Wednesday
UNTIL = datetime(2026, 3, 8, 23, 59, tzinfo=timezone.utc)  # that Sunday


def _mini_repo(path, subjects_emails, base=WED):
    """A throwaway git repo: subjects_emails is [(message, author_email), ...],
    one commit per entry, spaced an hour apart from `base`."""
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    for i, (subj, email) in enumerate(subjects_emails):
        (path / f"f{i}.txt").write_text(f"{i}\n")
        subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
        when = (base + timedelta(hours=i)).isoformat()
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
            "GIT_AUTHOR_NAME": "Dev", "GIT_COMMITTER_NAME": "Dev",
            "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email,
        }
        subprocess.run(
            ["git", "-C", str(path), "commit", "-m", subj], check=True, capture_output=True, env=env
        )
    return path


def _fake_assessment(email, period_end_iso, composite):
    """Minimal stand-in for an Assessment, enough for history.finalize()."""
    from commit_shrink.history import DISPLAYED_METRIC_IDS

    def metric(value, display):
        return SimpleNamespace(value=value, display=display)

    metrics = {mid: metric(0.0, "0") for mid in DISPLAYED_METRIC_IDS}
    metrics["composite_score"] = metric(float(composite), str(composite))
    return SimpleNamespace(
        patient_email=email,
        period_end=datetime.fromisoformat(period_end_iso),
        metrics=metrics,
        diagnoses=[],
    )


class TestUserSpec:
    def test_recognizes_and_parses(self):
        assert is_user_spec("gh-user:Anderson-ops-oss")
        assert parse_user_spec("gh-user:Anderson-ops-oss") == "Anderson-ops-oss"

    def test_recognizes_at_me_self_spec(self):
        assert is_user_spec("gh-user:@me")
        assert parse_user_spec("gh-user:@me") == "@me"

    def test_rejects_non_user_specs(self):
        assert not is_user_spec("github:owner/repo")
        assert not is_user_spec("Anderson-ops-oss")  # bare name is not a spec
        assert not is_user_spec("https://github.com/owner/repo")

    def test_requires_author(self):
        with pytest.raises(RemoteAuthorRequiredError):
            require_author_for_remote("gh-user:x", None)
        require_author_for_remote("gh-user:x", "me@example.com")  # ok with author


class TestAssessRepos:
    def test_merges_commits_across_repos(self, tmp_path):
        r1 = _mini_repo(tmp_path / "r1", [("a", "me@x"), ("b", "me@x")])
        r2 = _mini_repo(tmp_path / "r2", [("c", "me@x"), ("d", "me@x"), ("e", "me@x")])
        a = assess_repos([r1, r2], days=7, until=UNTIL, cfg=load_config())
        assert a.stats.total == 5 and a.patient_email == "me@x"

    def test_dedupes_shared_history(self, tmp_path):
        r1 = _mini_repo(tmp_path / "r1", [("a", "me@x"), ("b", "me@x")])
        a = assess_repos([r1, r1], days=7, until=UNTIL, cfg=load_config())
        assert a.stats.total == 2  # same shas -> not double-counted

    def test_keeps_multiple_identities_unlike_single_repo(self, tmp_path):
        # Same person, two emails. assess_repos keeps all (a person's records
        # span identities); assess_repo narrows to the dominant email.
        r = _mini_repo(tmp_path / "r", [("a", "alt@x"), ("b", "me@x"), ("c", "me@x")])
        agg = assess_repos([r], days=7, until=UNTIL, cfg=load_config())
        single = assess_repo(r, days=7, until=UNTIL, cfg=load_config())
        assert agg.stats.total == 3
        assert single.stats.total == 2


class TestLocalRepos:
    def test_clones_multiple_and_cleans_up(self, tmp_path):
        r1 = _mini_repo(tmp_path / "r1", [("a", "me@x")])
        # Allow partial (blobless) clones over file://, as GitHub does.
        subprocess.run(
            ["git", "-C", str(r1), "config", "uploadpack.allowFilter", "true"],
            check=True, capture_output=True,
        )
        urls = [f"file://{r1}", f"file://{r1}"]
        with local_repos(urls, days=7, until=UNTIL) as paths:
            assert len(paths) == 2
            for p in paths:
                assert (p / ".git").exists()
        for p in paths:
            assert not p.exists()  # temp parent removed on exit


class TestTrendContinuity:
    def test_user_fingerprint_is_lowercased_and_person_scoped(self):
        assert user_fingerprint("Anderson-Ops") == "user:anderson-ops"

    def test_trend_survives_repo_set_change(self, tmp_path):
        """Two periods recorded under the same user_fingerprint connect into a
        trend even though the underlying repo set may differ week to week --
        the whole point of person-anchored keying."""
        from commit_shrink.history import (
            DISPLAYED_METRIC_IDS,
            HistoryEntry,
            append_entry,
            compute_trend,
            load_history,
        )

        fp = user_fingerprint("octocat")
        hist = tmp_path / "h.jsonl"
        metrics = {m: {"value": 0.0, "display": "0"} for m in DISPLAYED_METRIC_IDS}
        metrics["composite_score"] = {"value": 80.0, "display": "80"}
        append_entry(
            HistoryEntry(
                patient_email="me@x", repo_fingerprint=fp, source="remote",
                period_end="2026-01-04T23:59:00+00:00",
                recorded_at="2026-01-04T23:59:00+00:00",
                metrics=metrics, diagnoses=[], techdebt_hashes=[],
            ),
            path=hist,
        )
        prior = load_history("me@x", fp, path=hist)
        week2 = SimpleNamespace(
            period_end=datetime.fromisoformat("2026-01-11T23:59:00+00:00"),
            patient_email="me@x",
            metrics={"composite_score": SimpleNamespace(display="78")},
        )
        trend = compute_trend(week2, prior)
        assert trend.composite_delta == -2  # 78 - 80, connected across weeks


class TestReviewRegressions:
    """Guards for the four defects the adversarial review found."""

    def test_no_false_fix_loop_across_repos(self, tmp_path):
        # #2: one 'fix' commit each in three repos, all touching a same-named
        # file (f0.txt) within 2h. No single repo has a chain; the merged
        # timeline must NOT fabricate a length-3 GIT-42.2 from the collision.
        r1 = _mini_repo(tmp_path / "r1", [("fix login bug", "me@x")], base=WED)
        r2 = _mini_repo(tmp_path / "r2", [("fix login bug again", "me@x")], base=WED + timedelta(minutes=30))
        r3 = _mini_repo(tmp_path / "r3", [("really fix login bug", "me@x")], base=WED + timedelta(minutes=60))
        a = assess_repos([r1, r2, r3], days=7, until=UNTIL, cfg=load_config())
        assert not any(d.id == "repeated_fix_loop" for d in a.diagnoses)

    def test_binge_not_falsely_fired_across_identities(self):
        # #3: a big commit under a secondary email, preceded by recent activity
        # under the primary email, is NOT "72h of silence".
        from datetime import datetime, timezone

        from commit_shrink.diagnoser import Diagnoser
        from commit_shrink.models import Commit

        diag = Diagnoser(load_config())
        base = datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc)
        recent = [
            Commit(sha=f"{i:040x}", author_name="Dev", author_email="me@work",
                   ts=base - timedelta(days=d), message="daily work",
                   file_paths=["a.py"], insertions=5)
            for i, d in enumerate((3, 2, 1), start=1)
        ]
        big = Commit(sha="f" * 40, author_name="Dev", author_email="me@personal",
                     ts=base, message="big update",
                     file_paths=[f"m{n}.py" for n in range(25)], insertions=1500)
        window = sorted(recent + [big], key=lambda c: c.ts)
        assert diag._binge([big], window) is None

    def test_aggregate_trend_survives_dominant_email_drift(self, tmp_path):
        # #1: the person-anchored (patient_scoped=False) trend must connect
        # across weeks even when the volume-dominant email drifts.
        from commit_shrink.history import HistoryContext, finalize

        fp = user_fingerprint("octocat")
        hist = tmp_path / "h.jsonl"
        ctx = HistoryContext(fingerprint=fp, techdebt_index={})
        finalize(ctx, _fake_assessment("alice@work", "2026-01-04T23:59:00+00:00", 80),
                 [], source="remote", path=hist, patient_scoped=False)
        trend = finalize(ctx, _fake_assessment("alice@home", "2026-01-11T23:59:00+00:00", 78),
                         [], source="remote", path=hist, patient_scoped=False)
        assert trend.composite_delta == -2  # connected despite the email change

    def test_patient_scoped_would_break_on_email_drift(self, tmp_path):
        # Documents WHY the aggregate must not be patient_scoped: the same drift
        # under email scoping (the single-repo default) fragments the trend.
        from commit_shrink.history import HistoryContext, finalize

        fp = user_fingerprint("octocat")
        hist = tmp_path / "h.jsonl"
        ctx = HistoryContext(fingerprint=fp, techdebt_index={})
        finalize(ctx, _fake_assessment("alice@work", "2026-01-04T23:59:00+00:00", 80),
                 [], source="remote", path=hist, patient_scoped=True)
        trend = finalize(ctx, _fake_assessment("alice@home", "2026-01-11T23:59:00+00:00", 78),
                         [], source="remote", path=hist, patient_scoped=True)
        assert trend.composite_delta is None  # NO_TREND: the drift split the streak


class TestGitAuthEnv:
    def test_none_token_is_empty(self):
        from commit_shrink.collector import git_auth_env

        assert git_auth_env(None) == {}

    def test_token_goes_into_config_env_not_argv(self, monkeypatch):
        import base64

        from commit_shrink.collector import git_auth_env

        monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
        env = git_auth_env("tok")
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
        expected = base64.b64encode(b"x-access-token:tok").decode()
        assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected}"
        # The raw token appears only inside the base64 value, never as a bare key.
        assert "tok" not in env["GIT_CONFIG_KEY_0"]

    def test_appends_to_existing_config_env(self, monkeypatch):
        # A caller/CI already injecting config via GIT_CONFIG_* must keep it:
        # append at the next free index, don't clobber index 0 / reset count.
        from commit_shrink.collector import git_auth_env

        monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
        env = git_auth_env("tok")
        assert env["GIT_CONFIG_COUNT"] == "3"
        assert env["GIT_CONFIG_KEY_2"] == "http.extraHeader"
        assert "GIT_CONFIG_KEY_0" not in env  # the user's existing 0/1 survive


class TestClonePersistsAuth:
    def test_token_written_to_clone_config(self, tmp_path):
        # Fix: later git ops on the clone (lazy --numstat fetch, backfill) must
        # authenticate, so the header is persisted into the clone's own config.
        import base64

        from commit_shrink.remote import _clone_blobless

        src = _mini_repo(tmp_path / "src", [("a", "me@x")])
        subprocess.run(
            ["git", "-C", str(src), "config", "uploadpack.allowFilter", "true"],
            check=True, capture_output=True,
        )
        dest = tmp_path / "clone"
        _clone_blobless(f"file://{src}", dest, token="sekret")
        config = (dest / ".git" / "config").read_text(encoding="utf-8")
        assert "extraHeader" in config
        assert base64.b64encode(b"x-access-token:sekret").decode() in config

    def test_no_token_leaves_config_clean(self, tmp_path):
        from commit_shrink.remote import _clone_blobless

        src = _mini_repo(tmp_path / "src", [("a", "me@x")])
        subprocess.run(
            ["git", "-C", str(src), "config", "uploadpack.allowFilter", "true"],
            check=True, capture_output=True,
        )
        dest = tmp_path / "clone"
        _clone_blobless(f"file://{src}", dest)
        assert "extraHeader" not in (dest / ".git" / "config").read_text(encoding="utf-8")


class TestRunAssessmentUserPath:
    def test_end_to_end_with_stubbed_api(self, tmp_path, monkeypatch):
        """gh-user path: stub discovery to a file:// repo, clone for real, assess
        the merged timeline, and confirm the RunResult + coverage counts. Cache
        is redirected into tmp so history never touches the real user cache."""
        from commit_shrink import run

        repo = _mini_repo(tmp_path / "src", [("a", "me@x"), ("b", "me@x")])
        subprocess.run(
            ["git", "-C", str(repo), "config", "uploadpack.allowFilter", "true"],
            check=True, capture_output=True,
        )
        monkeypatch.setenv("COMMIT_SHRINK_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setattr(run, "list_user_public_repos", lambda *a, **k: [f"file://{repo}"])

        result = run.run_assessment(
            "gh-user:octocat", days=7, until=UNTIL, author="me@x", cfg=load_config()
        )
        assert result.discovered_count == 1
        assert result.repo_count == 1
        assert result.assessment.stats.total == 2


class TestRunAssessmentSelfPath:
    def test_me_without_token_raises(self, monkeypatch):
        from commit_shrink import run

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with pytest.raises(run.TokenRequiredError):
            run.run_assessment("gh-user:@me", days=7, until=UNTIL, author="me@x", cfg=load_config())

    def test_me_end_to_end_with_token(self, tmp_path, monkeypatch):
        """@me path: token present, discovery/login stubbed to a file:// repo
        (file transport ignores the auth header), merged timeline assessed."""
        from commit_shrink import run

        repo = _mini_repo(tmp_path / "src", [("a", "me@x"), ("b", "me@x"), ("c", "me@x")])
        subprocess.run(
            ["git", "-C", str(repo), "config", "uploadpack.allowFilter", "true"],
            check=True, capture_output=True,
        )
        monkeypatch.setenv("GITHUB_TOKEN", "faketok")
        monkeypatch.setenv("COMMIT_SHRINK_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(run, "get_authenticated_login", lambda token: "octocat")
        monkeypatch.setattr(run, "list_authenticated_user_repos", lambda token, **k: [f"file://{repo}"])

        result = run.run_assessment(
            "gh-user:@me", days=7, until=UNTIL, author="me@x", cfg=load_config()
        )
        assert result.discovered_count == 1
        assert result.assessment.stats.total == 3

    def test_me_empty_is_flagged_self(self, monkeypatch):
        from commit_shrink import run

        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setattr(run, "get_authenticated_login", lambda t: "octocat")
        monkeypatch.setattr(run, "list_authenticated_user_repos", lambda t, **k: [])
        with pytest.raises(run.NoReposError) as ei:
            run.run_assessment("gh-user:@me", days=7, until=UNTIL, author="me@x", cfg=load_config())
        assert ei.value.is_self is True  # -> renders no_owned_repos, not "public"

    def test_other_empty_is_not_flagged_self(self, monkeypatch):
        from commit_shrink import run

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setattr(run, "list_user_public_repos", lambda *a, **k: [])
        with pytest.raises(run.NoReposError) as ei:
            run.run_assessment("gh-user:ghost", days=7, until=UNTIL, author="me@x", cfg=load_config())
        assert ei.value.is_self is False

    def test_no_owned_repos_key_in_both_locales(self):
        for lang in ("zh", "en"):
            assert load_config(lang)["report_copy"]["errors"]["no_owned_repos"]
