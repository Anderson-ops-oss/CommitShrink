"""Detector tests for the two symptoms added after v0.1: GIT-45.0
CI-Appeasement Disorder and GIT-00.1 Existential Empty-Commit Disorder.

These are unit-tested against hand-built Commit lists (not the shared demo
fixture) because both are deliberately *inert* on that fixture -- every fixture
commit writes files and none begs a pipeline -- which is also asserted here, so
the golden-sample report and its assertions are provably unaffected.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from commit_shrink.diagnoser import Diagnoser
from commit_shrink.models import Commit
from commit_shrink.pipeline import assess_repo, load_config


def _c(message: str, *, files=("a.py",), ins: int = 3, dels: int = 0, i: int = 0) -> Commit:
    return Commit(
        sha=f"{i:040x}",
        author_name="Dev",
        author_email="dev@example.com",
        ts=datetime(2026, 1, 5, 12, i % 60, tzinfo=timezone.utc),
        message=message,
        file_paths=list(files),
        insertions=ins,
        deletions=dels,
    )


@pytest.fixture(scope="module")
def diag() -> Diagnoser:
    return Diagnoser(load_config())


class TestCiAppeasement:
    def test_four_hits_grade_III(self, diag):
        d = diag._ci_appeasement([_c("fix ci", i=i) for i in range(4)])
        assert d is not None and d.id == "ci_appeasement" and d.code == "GIT-45.0"
        assert d.severity == "III"
        assert len(d.evidence) == 4

    def test_single_hit_grade_I(self, diag):
        d = diag._ci_appeasement([_c("please pass", i=1)])
        assert d is not None and d.severity == "I"

    def test_six_hits_grade_IV(self, diag):
        d = diag._ci_appeasement([_c("make ci green", i=i) for i in range(6)])
        assert d.severity == "IV"

    def test_allcaps_pleading_upgrades_to_III(self, diag):
        # Only two hits, but an all-caps plea pushes it to III.
        d = diag._ci_appeasement([_c("PLEASE PASS", i=1), _c("fix ci", i=2)])
        assert d.severity == "III"

    def test_chinese_appeasement_matches(self, diag):
        d = diag._ci_appeasement([_c("求过", i=1), _c("让 ci 过", i=2)])
        assert d is not None and d.severity == "II"

    def test_no_false_positive_on_benign_messages(self, diag):
        benign = [
            _c("add green button", i=1),
            _c("fix the parser bug", i=2),
            _c("please review this PR", i=3),
        ]
        assert diag._ci_appeasement(benign) is None


class TestEmptyCommit:
    def test_detects_zero_change_commits(self, diag):
        empties = [_c("trigger ci", files=(), ins=0, dels=0, i=i) for i in range(2)]
        d = diag._empty_commit(empties)
        assert d is not None and d.id == "empty_commit" and d.code == "GIT-00.1"
        assert d.severity == "II" and len(d.evidence) == 2

    def test_ignores_commits_that_change_files(self, diag):
        assert diag._empty_commit([_c("real work", files=("a.py",), ins=5, i=1)]) is None

    def test_six_empties_grade_IV(self, diag):
        empties = [_c(".", files=(), ins=0, dels=0, i=i) for i in range(6)]
        assert diag._empty_commit(empties).severity == "IV"


class TestNewSymptomsRender:
    """Detection produces language-neutral args; this exercises the render path
    (diagnosis/prescription templates) that the detector unit tests don't touch,
    catching any {placeholder} mismatch in the yaml copy."""

    def test_render_in_both_languages(self, diag):
        from commit_shrink.report import ReportRenderer

        ci = diag._ci_appeasement([_c("fix ci", i=i) for i in range(4)])
        empty = diag._empty_commit([_c("trigger ci", files=(), ins=0, dels=0, i=i) for i in range(2)])
        for lang in ("zh", "en"):
            r = ReportRenderer(load_config(lang))
            for d in (ci, empty):
                text = r.diagnosis_text(d)
                rx = r.diagnosis_prescription(d)
                assert text and "{" not in text and "}" not in text
                assert rx and "{" not in rx and "}" not in rx
                assert r.diagnosis_name(d)


class TestInertOnStandardFixture:
    def test_new_symptoms_do_not_fire_on_demo_fixture(self, fixture_repo):
        repo, _start, period_end = fixture_repo
        a = assess_repo(repo, days=7, until=period_end)
        ids = {d.id for d in a.diagnoses}
        assert "ci_appeasement" not in ids
        assert "empty_commit" not in ids
