"""Submit/error-path coverage for the Streamlit app via AppTest.

test_web_app.py only smoke-tests boot + a language toggle (no form submit).
This module drives the assessment form and exercises the two front-of-house
error branches in web_app.py's run block:

  1. an INVALID ISO datetime in the `until` field -> the ValueError branch,
     which emits the (Python-literal) "not a valid ISO datetime" copy and
     short-circuits before any assessment runs; and
  2. a path that is not a git repository -> run_assessment raises
     NotARepoError, which maps to the yaml `errors.not_a_repo` clinical copy.

Like test_web_app.py, the whole module is skipped when the optional [web]
extra (streamlit/plotly) is not installed. Expected strings are hard-coded to
the app's actual current output so this file locks that behavior in place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")

from streamlit.testing.v1 import AppTest  # noqa: E402

REPO_ROOT = Path(__file__).parents[1]
APP = str(REPO_ROOT / "commit_shrink" / "web_app.py")

# Widget order in the form (all keyless, so addressed positionally):
#   text_input[0] = repository path      number_input[0] = window (days)
#   text_input[1] = author filter        text_input[2]   = end-of-period (until)
PATH_INPUT = 0
AUTHOR_INPUT = 1
UNTIL_INPUT = 2

# The NotARepoError -> not_a_repo mapping resolves to this English copy
# (default language is English; folded-scalar in data/locales/en.yaml).
NOT_A_REPO_COPY = (
    "The specified path is not a git repository. "
    "This center accepts only behavioral specimens under version control."
)


def _run_form(*, path=None, until=None, author=None, timeout=120):
    """Boot the app, fill only the given fields, click Run Assessment, rerun."""
    at = AppTest.from_file(APP, default_timeout=timeout).run()
    assert not at.exception, at.exception
    if path is not None:
        at.text_input[PATH_INPUT].set_value(path)
    if author is not None:
        at.text_input[AUTHOR_INPUT].set_value(author)
    if until is not None:
        at.text_input[UNTIL_INPUT].set_value(until)
    at.button[0].click().run()
    return at


@pytest.mark.parametrize("bad_until", ["not-a-date", "2026-13-45", "07/07/2026"])
def test_invalid_until_datetime_shows_iso_error(bad_until):
    """A non-ISO `until` hits the ValueError branch: the error echoes the raw
    input verbatim and no assessment is run."""
    at = _run_form(until=bad_until)

    assert not at.exception, at.exception
    assert len(at.error) == 1
    assert at.error[0].value == f"'{bad_until}' is not a valid ISO datetime."
    # The branch short-circuits: no assessment stored, so no report renders.
    assert at.session_state["assessment"] is None
    assert len(at.subheader) == 0


def test_invalid_until_does_not_touch_other_fields():
    """The failed submit leaves the other (untouched) widgets at their defaults,
    confirming the error is purely from the `until` parse."""
    at = _run_form(until="garbage")

    assert at.error[0].value == "'garbage' is not a valid ISO datetime."
    assert at.text_input[PATH_INPUT].value == "."
    assert at.number_input[0].value == 7


def test_non_git_repo_path_shows_not_a_repo_error(tmp_path):
    """An empty (non-git) directory drives run_assessment -> NotARepoError ->
    the not_a_repo clinical copy. A fixed, tz-aware `until` keeps the run
    deterministic (no now())."""
    at = _run_form(
        path=str(tmp_path),
        until="2026-01-05T00:00:00+00:00",
    )

    assert not at.exception, at.exception
    assert len(at.error) == 1
    assert at.error[0].value == NOT_A_REPO_COPY
    assert at.session_state["assessment"] is None
    assert len(at.subheader) == 0
