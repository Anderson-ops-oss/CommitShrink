"""Complete diagnoser._empty_commit's severity ladder (GIT-00.1).

test_new_symptoms.py::TestEmptyCommit already pins n=2 -> 'II' and n=6 -> 'IV'.
This file fills in the two missing rungs -- n=1 -> 'I' and n=4 -> 'III' -- and
confirms the n=3 boundary is still 'II' (the ladder is n>=6:IV, n>=4:III,
n>=2:II, else:I), so the whole ladder is exercised across the two files.

Like test_new_symptoms.py, these are unit tests against hand-built Commit lists.
An "empty" commit changes no files and touches no lines: files_changed==0,
insertions==0, deletions==0, and it is not a merge.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from commit_shrink.diagnoser import Diagnoser
from commit_shrink.models import Commit
from commit_shrink.pipeline import load_config


def _c(message: str, *, files=("a.py",), ins: int = 3, dels: int = 0, i: int = 0) -> Commit:
    # Mirrors the _c helper in test_new_symptoms.py; empty commits pass
    # files=(), ins=0, dels=0 so files_changed/insertions/deletions are all 0.
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


def _empties(n: int):
    return [_c(".", files=(), ins=0, dels=0, i=i) for i in range(n)]


class TestEmptyCommitRungs:
    def test_single_empty_grade_I(self, diag):
        d = diag._empty_commit(_empties(1))
        assert d is not None and d.id == "empty_commit" and d.code == "GIT-00.1"
        assert d.severity == "I"
        assert len(d.evidence) == 1
        assert d.args["n"] == 1

    def test_three_empties_still_grade_II(self, diag):
        # Boundary: 3 is >= 2 but < 4, so the II rung, not yet III.
        d = diag._empty_commit(_empties(3))
        assert d is not None and d.severity == "II"
        assert len(d.evidence) == 3
        assert d.args["n"] == 3

    def test_four_empties_grade_III(self, diag):
        d = diag._empty_commit(_empties(4))
        assert d is not None and d.severity == "III"
        assert len(d.evidence) == 4
        assert d.args["n"] == 4

    def test_five_empties_still_grade_III(self, diag):
        # Upper boundary of the III rung: 5 is < 6, so not yet IV.
        d = diag._empty_commit(_empties(5))
        assert d is not None and d.severity == "III"
        assert len(d.evidence) == 5
        assert d.args["n"] == 5
