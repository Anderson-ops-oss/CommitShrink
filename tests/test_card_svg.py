"""Tests for the shareable SVG card (commit_shrink.card.render_card_svg).

The SVG card is the link-previewable / GitHub-embeddable artifact: it must be
well-formed XML, fully self-contained (no external fetches -- safe offline and
when hot-linked), escape untrusted text, keep an English card CJK-free, and lay
out deterministically in both languages.
"""

from __future__ import annotations

import xml.dom.minidom as minidom

from commit_shrink.card import (
    _display_width,
    _wrap,
    build_card_model,
    render_card_svg,
)
from commit_shrink.pipeline import load_config
from commit_shrink.report import ReportRenderer


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


_NS = "http://www.w3.org/2000/svg"


def _model(*, dx="GIT-42.2 Compulsive Fix Disorder", rx="Take a walk.", score="40",
           score_pct=40, center="CommitShrink Center", lang="en"):
    """A hand-built card model, so escaping/score-color/wrap can be tested without
    routing a whole Assessment through the pipeline."""
    return {
        "lang": lang,
        "center_name": center,
        "case_no": "CS-2026-W26-0001",
        "subject": "d***v@example.com",
        "score": score,
        "score_pct": score_pct,
        "dx": dx,
        "rx": rx,
        "labels": {
            "index": "Mental Health Index", "case": "Case No.", "subject": "Subject",
            "primary": "Primary Dx", "rx": "Rx", "footer": "Generate your own assessment",
        },
    }


class TestWrapHelper:
    def test_latin_wraps_on_spaces(self):
        lines = _wrap("alpha beta gamma delta", budget=6, max_lines=3)
        assert all(" " in line or _display_width(line) <= 6 for line in lines)
        assert " ".join(lines).replace("…", "") .startswith("alpha")

    def test_cjk_wraps_per_glyph(self):
        lines = _wrap("一二三四五六七八", budget=3, max_lines=4)
        assert len(lines) >= 2 and all(_display_width(line) <= 3 for line in lines)

    def test_overflow_truncates_with_ellipsis(self):
        lines = _wrap("one two three four five six seven eight", budget=4, max_lines=2)
        assert len(lines) == 2
        assert lines[-1].endswith("…")

    def test_display_width_cjk_wider_than_latin(self):
        assert _display_width("ab") == 1.0  # 2 latin * 0.5
        assert _display_width("你好") == 2.0  # 2 cjk * 1.0


class TestSvgStructure:
    def _svg(self, lang, assessment):
        return render_card_svg(build_card_model(assessment, ReportRenderer(load_config(lang))))

    def test_is_well_formed_xml(self, assessment):
        for lang in ("zh", "en"):
            minidom.parseString(self._svg(lang, assessment))  # raises on malformed

    def test_is_self_contained(self, assessment):
        svg = self._svg("en", assessment)
        # The only URL allowed is the SVG namespace; nothing is fetched.
        residue = svg.replace(_NS, "")
        assert "http" not in residue
        assert "<image" not in svg and "xlink:href" not in svg and "src=" not in svg
        assert "url(http" not in svg

    def test_dynamic_values_present(self, assessment):
        model = build_card_model(assessment, ReportRenderer(load_config("en")))
        svg = render_card_svg(model)
        assert f"{model['score']} / 100" in svg
        assert model["dx"].split()[0] in svg  # the GIT-xx.x code
        assert "1200" in svg and "630" in svg  # OG dimensions

    def test_english_card_is_cjk_free(self, assessment):
        assert not _has_cjk(self._svg("en", assessment))

    def test_chinese_card_has_cjk(self, assessment):
        assert _has_cjk(self._svg("zh", assessment))


class TestSvgSafety:
    def test_untrusted_text_is_escaped(self):
        svg = render_card_svg(_model(dx='<script>alert(1)</script> & "x"', center="A<b>C"))
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg and "&amp;" in svg
        minidom.parseString(svg)  # still well-formed after injecting metacharacters


class TestSvgScoreColor:
    def test_low_score_uses_dark_ink_over_pale_track(self):
        # pale unfilled track on the right -> dark score text
        assert 'fill="#1a1a1a">40 / 100' in render_card_svg(_model(score="40", score_pct=40))

    def test_high_score_uses_light_ink_over_dark_fill(self):
        assert 'fill="#fbfbf7">95 / 100' in render_card_svg(_model(score="95", score_pct=95))


class TestSvgWrapIntegration:
    def test_long_diagnosis_is_capped_to_two_lines(self):
        import re

        long_dx = "GIT-99.9 " + "Extremely Verbose Diagnosis Name " * 6
        svg = render_card_svg(_model(dx=long_dx.strip()))
        # The dx <text> is the bold block anchored at x="72" (the header is also
        # bold but anchored at x="596"); it holds at most two truncating <tspan>s.
        dx_text = re.search(r'<text x="72"[^>]*font-weight="700"[^>]*>(.*?)</text>', svg, re.S)
        assert dx_text is not None
        assert dx_text.group(1).count("<tspan") <= 2
        assert "…" in dx_text.group(1)  # truncation marker present

    def test_no_prescription_omits_rx_block(self):
        svg = render_card_svg(_model(rx=""))
        assert "font-style=\"italic\"" not in svg
