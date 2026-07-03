"""Headless smoke test for the Streamlit app via streamlit.testing.AppTest.

streamlit/plotly live in the optional [web] extra, so this whole module is
skipped when they are not installed (e.g. CI, which installs only [dev]).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")

from streamlit.testing.v1 import AppTest  # noqa: E402

REPO_ROOT = Path(__file__).parents[1]
APP = str(REPO_ROOT / "commit_shrink" / "web_app.py")


def test_app_boots_with_language_selector():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    # A language selector is present in the sidebar.
    assert any("Language" in (r.label or "") for r in at.sidebar.radio)
    # Default language is English (matches the CLI default).
    assert "Developmental Mental Health Assessment" in at.title[0].value


def test_switching_language_rerenders_without_error():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert "Developmental Mental Health Assessment" in at.title[0].value

    at.sidebar.radio[0].set_value("中文").run()
    assert not at.exception, at.exception
    # The clinic name (and thus the whole chrome) switched language on a pure
    # rerun -- no assessment was submitted.
    assert "开发者心理健康评估中心" in at.title[0].value
