"""Tests for the shareable HTML card (commit_shrink.card).

The card must render from the SAME ReportRenderer the full report uses (so it
can't drift), be fully self-contained (no external assets -- safe in a sandboxed
iframe and offline), leave no CJK in an English card, and mask the subject.
"""

from __future__ import annotations

from commit_shrink.card import _mask_email, build_card_model, render_card_html
from commit_shrink.pipeline import load_config
from commit_shrink.report import ReportRenderer


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def test_mask_email_keeps_ends_and_domain():
    assert _mask_email("anderson@connect.hku.hk") == "a***n@connect.hku.hk"
    assert _mask_email("ab@x.com") == "a*@x.com"  # short local part
    assert _mask_email("solo") == "s***o"  # no domain, still masked


class TestCardModel:
    def test_core_fields_from_assessment(self, assessment):
        model = build_card_model(assessment, ReportRenderer(load_config("en")))
        assert "GIT-" in model["dx"]  # a primary diagnosis line
        assert 0 <= model["score_pct"] <= 100
        assert "@" in model["subject"] and "***" in model["subject"]

    def test_labels_present_in_both_languages(self):
        keys = (
            "section_title", "index_label", "case_label", "subject_label",
            "primary_label", "rx_label", "none_dx", "footer", "download_label",
            "saved_fmt",
        )
        for lang in ("zh", "en"):
            card = load_config(lang)["report_copy"]["card"]
            for key in keys:
                assert card.get(key), f"{lang} card.{key} missing"


class TestCardHtml:
    def _html(self, lang, assessment):
        return render_card_html(build_card_model(assessment, ReportRenderer(load_config(lang))))

    def test_is_self_contained(self, assessment):
        html = self._html("en", assessment)
        assert "<style" in html
        # No external assets: nothing to fetch, safe offline and in a sandbox.
        assert "http://" not in html and "https://" not in html and "src=" not in html

    def test_dynamic_values_are_filled(self, assessment):
        model = build_card_model(assessment, ReportRenderer(load_config("en")))
        html = render_card_html(model)
        assert f"{model['score']} / 100" in html
        assert model["dx"].split()[0] in html  # the GIT-xx.x code
        assert model["center_name"] in html

    def test_english_card_is_cjk_free(self, assessment):
        assert not _has_cjk(self._html("en", assessment))

    def test_chinese_card_has_cjk(self, assessment):
        assert _has_cjk(self._html("zh", assessment))
