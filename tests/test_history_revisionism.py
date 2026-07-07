"""Detector tests for GIT-88.8 History Revisionism (diagnoser.Diagnoser._history).

This detector is unusual: it reads a single integer (the count of reflog-observed
history rewrites) rather than a Commit list, and it has a graceful-degradation
branch -- when the reflog is unavailable the caller passes ``rewrites=None`` and
the detector records a 'specimen declined' note instead of grading. Both the
None-degradation path and the severity ladder are exercised here by calling
``_history`` directly, mirroring the unit-test style of test_new_symptoms.py.
"""

from __future__ import annotations

import pytest

from commit_shrink.diagnoser import Diagnoser
from commit_shrink.pipeline import load_config


@pytest.fixture(scope="module")
def diag() -> Diagnoser:
    return Diagnoser(load_config())


class TestReflogUnavailable:
    def test_none_returns_none_and_appends_note(self, diag):
        # Reflog unavailable: no diagnosis, but the 'specimen declined' note is
        # recorded so the report can render the missing-data boilerplate.
        notes: list[str] = []
        assert diag._history(None, notes) is None
        assert notes == ["history_revisionism"]

    def test_none_appends_to_existing_notes(self, diag):
        notes = ["some_other_note"]
        diag._history(None, notes)
        assert notes == ["some_other_note", "history_revisionism"]


class TestNoRewrites:
    def test_zero_returns_none_and_leaves_notes_untouched(self, diag):
        notes: list[str] = []
        assert diag._history(0, notes) is None
        assert notes == []


class TestSeverityLadder:
    @pytest.mark.parametrize(
        "rewrites, expected",
        [
            (1, "I"),
            (2, "I"),
            (3, "II"),
            (5, "II"),
            (6, "III"),
            (9, "III"),
            (10, "IV"),
        ],
    )
    def test_ladder(self, diag, rewrites, expected):
        notes: list[str] = []
        d = diag._history(rewrites, notes)
        assert d is not None
        assert d.id == "history_revisionism"
        assert d.code == "GIT-88.8"
        assert d.severity == expected
        # The count is threaded through as a render arg; no commit evidence and
        # no note is recorded on the graded path.
        assert d.args == {"n": rewrites}
        assert d.evidence == []
        assert notes == []

    def test_graded_diagnosis_uses_default_template(self, diag):
        d = diag._history(3, [])
        assert d.masked is False
        assert d.template_key == "diagnosis"
        assert d.notes == {}
