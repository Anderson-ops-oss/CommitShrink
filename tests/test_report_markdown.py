"""Regression coverage for ``commit_shrink.report_markdown.render_report_markdown``,
the GitHub-Flavored-Markdown surface behind the "live" README sample.

No existing test imports this module; these lock in that the render (a) emits all
six report sections, (b) leaves no unfilled ``{placeholder}`` in the output (the
same guard test_new_symptoms.py applies to the diagnosis/prescription templates),
(c) does not leak Chinese boilerplate into the English render, and (d) surfaces
the composite score line. All assertions are pinned to the deterministic demo
``assessment`` fixture (composite score 40) via load_config for both locales.
"""

from __future__ import annotations

import re

import pytest

from commit_shrink.pipeline import load_config
from commit_shrink.report_markdown import render_report_markdown

# CJK punctuation + CJK Ext-A/Unified ideographs + fullwidth forms (e.g. ：（）｜　、。).
_CJK_RE = re.compile(r"[　-〿㐀-鿿＀-￯]")

# The demo fixture yields composite score 40 (observed via load_config/render).
EXPECTED_COMPOSITE_DISPLAY = "40"


@pytest.fixture(params=["zh", "en"])
def rendered(request, assessment):
    """(lang, cfg, body) for each supported locale, rendered with trend=None."""
    lang = request.param
    cfg = load_config(lang)
    body = render_report_markdown(assessment, cfg, trend=None)
    return lang, cfg, body


def test_all_six_section_headers_present(rendered):
    _lang, cfg, body = rendered
    sections = cfg["report_copy"]["sections"]
    assert len(sections) == 6
    for title in sections.values():
        assert title in body, title


def test_no_leftover_format_placeholder(rendered):
    _lang, _cfg, body = rendered
    assert "{" not in body
    assert "}" not in body


def test_composite_score_line_present(rendered):
    _lang, cfg, body = rendered
    # The exact composite display for the demo fixture is 40.
    assert f"{EXPECTED_COMPOSITE_DISPLAY} / 100" in body
    # And it is emitted via the locale's composite_fmt, not free copy.
    composite_fmt = cfg["report_copy"]["diagnosis_labels"]["composite_fmt"]
    assert composite_fmt.format(score=EXPECTED_COMPOSITE_DISPLAY) in body


def test_en_render_has_no_cjk_leak(assessment):
    """The English render must be free of Chinese boilerplate/labels; the demo
    fixture's own commit messages are all Latin, so any CJK char is a leak."""
    cfg = load_config("en")
    body = render_report_markdown(assessment, cfg, trend=None)
    stray = _CJK_RE.findall(body)
    assert stray == [], f"stray CJK in en render: {stray[:10]}"
    # The six English section titles all survive into the output.
    for title in cfg["report_copy"]["sections"].values():
        assert title in body, title
